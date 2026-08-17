"""Audio Bass Machine — real playback hardware driven by the live spectrum.

Three scenes, each a piece of gear rendered head-on and wired directly to the
analyzer rather than to a decorative time function:

* **Subwoofer** — a driver seen face-on.  The cone's excursion *is* the bass
  envelope: it bulges toward the viewer, the rubber surround rolls with it, the
  dust cap catches a moving specular, and the two bass ports fire expanding
  pressure rings into the room on every beat.
* **Boombox** — twin woofers pumping on bass, a real 64-band EQ ladder driven
  by ``audio.bands``, two VU needles swinging on bass and mid, and cassette
  reels that spin at a rate set by the mid band.
* **Record player** — a platter whose grooves are displaced by the spectrum
  (each groove ring reads a different band, so the record is literally cut by
  what is playing), a label spinning with it, and a tonearm that tracks inward
  across the disc.

Everything is drippy on purpose: wet neon paint runs down the cabinet faces,
chrome trim carries a moving specular, and the surroundings are alive — a
pressure-ring field, a neon floor grid, and haze that swells with the low end.

Audio reactivity (all four bands plus the raw spectrum):
  - bass    -> cone excursion, cabinet swell, VU needles, haze
  - mid     -> reel/platter speed, EQ mid-ladder, palette drift
  - treble  -> sparkle, chrome specular, groove shimmer
  - beat    -> port pressure rings, strobe, scene punch
  - bands   -> EQ ladder heights and record-groove displacement (real FFT)

Randomised per activation: scene (never the same one twice running), palette
hue, cabinet tint, background variant, platter/reel phase, and ``self.time`` —
no two runs look alike from frame 0.

Config keys (under ``[effects.AudioBassMachine]``):
    speed, zoom, reactivity, glitter
"""
from __future__ import annotations

import moderngl
import numpy as np

from unicornviz.effects.base import AudioData, BaseEffect

_NBANDS = 64
_NSCENE = 3

_VERT = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_FRAG = """
#version 330
uniform float iTime;
uniform vec2  iResolution;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
uniform float iBeat;
uniform float iPunch;        // slower beat envelope for cabinet swell
uniform float iHue;
uniform float iZoom;
uniform float iGlitter;
uniform float iSpin;         // CPU-integrated platter / reel phase
uniform float iRing;         // CPU-integrated pressure-ring phase
uniform float iTint;         // per-activation cabinet tint pick
uniform int   iScene;
uniform int   iBackdrop;     // per-activation surroundings variant
uniform float iBands[64];
in  vec2 v_uv;
out vec4 fragColor;

#define PI  3.14159265
#define TAU 6.28318530

// Mixer palette (drop-ins/dj-mixer-01/ui.py) — the deck accents, so the gear
// reads as part of the same rig instead of drifting into muddy browns.
const vec3 MIX_CYAN    = vec3(0.00, 0.71, 1.00);
const vec3 MIX_PINK    = vec3(1.00, 0.35, 0.78);
const vec3 MIX_GREEN   = vec3(0.24, 1.00, 0.63);
const vec3 MIX_AMBER   = vec3(1.00, 0.69, 0.00);
const vec3 MIX_MAGENTA = vec3(0.92, 0.27, 0.80);
const vec3 MIX_YELLOW  = vec3(1.00, 0.82, 0.27);

const float SCENE_SCALE = 0.72;

// Bounded hash input. The classic idiom here added floor(t*20) straight into
// hash21(); with iTime starting anywhere up to 10000 that term reaches ~12000,
// and hash21's first multiply (x123.34) then lands past float32's usable
// mantissa — the "random" field collapses to a fixed ~15-value lattice, which
// is the regular dotted grid this used to show. Everything entering a hash is
// wrapped small first.
float hash21(vec2 p) {
    p = mod(p, 512.0);
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}
vec3 palette(float t) { return 0.5 + 0.5 * cos(TAU * (t + vec3(0.0, 0.33, 0.67))); }

float sdBox(vec2 p, vec2 b) {
    vec2 d = abs(p) - b;
    return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0);
}
float sdRound(vec2 p, vec2 b, float r) { return sdBox(p, b - r) - r; }
float fill(float d, float soft) { return smoothstep(soft, -soft, d); }
void paint(inout vec3 o, inout float cov, vec3 c, float m) {
    m = clamp(m, 0.0, 1.0);
    o = mix(o, c, m);
    cov = max(cov, m);
}

// Band lookup with linear interpolation, so ladders and grooves read smooth.
float band(float x) {
    x = clamp(x, 0.0, 1.0) * 63.0;
    int i = int(floor(x));
    int j = min(i + 1, 63);
    return mix(iBands[i], iBands[j], fract(x));
}

// Accent pair for this activation, always drawn from the mixer palette.
vec3 accentA() {
    if (iTint < 0.25) return MIX_CYAN;
    if (iTint < 0.50) return MIX_PINK;
    if (iTint < 0.75) return MIX_GREEN;
    return MIX_AMBER;
}
vec3 accentB() {
    if (iTint < 0.25) return MIX_PINK;
    if (iTint < 0.50) return MIX_CYAN;
    if (iTint < 0.75) return MIX_MAGENTA;
    return MIX_CYAN;
}
// Cabinet stays dark and neutral so the neon reads; it is tinted toward the
// accent rather than toward wood.
vec3 cabinetTint() { return mix(vec3(0.045, 0.050, 0.070), accentA() * 0.10, 0.6); }

// ── spectrum: real bars, pegged flush to the bottom edge, growing upward ────
// Bars used to hang *down* from the top edge, which reads as an upside-down
// analyser — a spectrum grows up off the surface it stands on.
vec3 spectrumBars(vec2 q, float baseY, float halfW, float maxH, vec3 hot, out float cov) {
    cov = 0.0;
    vec3 o = vec3(0.0);
    if (abs(q.x) > halfW + 0.02 || q.y < baseY - 0.02 || q.y > baseY + maxH + 0.06)
        return o;
    const float N = 28.0;
    float u = (q.x + halfW) / (2.0 * halfW);
    float idx = floor(u * N);
    float f = fract(u * N);
    float v = clamp(band(idx / (N - 1.0)), 0.0, 1.6);
    float h = 0.03 + v * maxH;
    float barW = 0.34;                       // in cell units, leaves a gap
    float inBar = smoothstep(0.5 + barW, 0.5 + barW - 0.10, abs(f - 0.5) * 2.0);
    float inH = smoothstep(0.004, -0.004, q.y - (baseY + h));
    float above = step(baseY, q.y);
    float m = inBar * inH * above;
    // Cool at the bottom, hot at the tip.
    vec3 c = mix(MIX_CYAN, hot, clamp((q.y - baseY) / max(h, 1e-3), 0.0, 1.0));
    paint(o, cov, c * (0.75 + v * 1.3), m);
    // Peak cap.
    paint(o, cov, vec3(1.0),
          inBar * above * smoothstep(0.012, 0.0, abs(q.y - (baseY + h))) * 0.9);
    return o;
}

// ── drips: wet paint running down from the top edge, with a fat bead ────────
float dripMask(vec2 q, float topY, float halfW, float tb, float seed) {
    if (abs(q.x) > halfW) return 0.0;
    const float LANES = 30.0;
    float u = (q.x + halfW) / (2.0 * halfW);
    float lane = floor(u * LANES);
    float h = hash21(vec2(lane, seed));
    float flow = fract(tb * (0.07 + h * 0.16) + h);
    float len = 0.10 + h * 0.30;
    float tip = topY - flow * len;
    float dy = topY - q.y;
    float across = abs(fract(u * LANES) - 0.5) * 2.0;
    float w = 0.42 - flow * 0.12;
    float streak = smoothstep(w, w * 0.35, across) * step(0.0, dy) * step(q.y, topY)
                 * smoothstep(-0.02, 0.03, q.y - tip);
    // Heavy bead at the running end.
    float bead = smoothstep(0.020, 0.0,
                            length(vec2(across * 0.022, q.y - tip))) * (0.5 + h);
    return clamp(streak + bead, 0.0, 1.0);
}

// ── neon level trough with a bead dancing along it ──────────────────────────
vec3 beadBar(vec2 q, vec2 hb, float level, float tb, vec3 c, out float cov) {
    cov = 0.0;
    vec3 o = vec3(0.0);
    float d = sdRound(q, hb, hb.y);
    if (d > 0.05) return o;
    paint(o, cov, vec3(0.02, 0.025, 0.04), fill(d, 0.004));           // trough
    o += c * fill(abs(d) - 0.005, 0.003) * (1.2 + iTreble * 1.2);      // neon rim
    // Filled portion.
    float lv = clamp(level, 0.0, 1.0);
    float x0 = -hb.x + 0.012;
    float x1 = mix(x0, hb.x - 0.012, lv);
    o += c * fill(sdRound(vec2(q.x - (x0 + x1) * 0.5, q.y),
                          vec2(max(0.0, (x1 - x0) * 0.5), hb.y * 0.45), hb.y * 0.4),
                  0.004) * 1.1;
    // The bead: rides the level, with a little overshoot bounce and a trail.
    float bx = x1 + sin(tb * 7.0) * 0.012 * lv;
    float bd = length((q - vec2(bx, 0.0)) / vec2(1.0, 1.15));
    o += mix(vec3(1.0), c, 0.35) * smoothstep(hb.y * 0.95, 0.0, bd) * (1.6 + iBass * 1.2);
    o += c * smoothstep(hb.y * 2.6, 0.0, bd) * 0.55;
    cov = max(cov, fill(d, 0.004));
    return o;
}

// Shared speaker driver. `exc` is the cone excursion in [0,1].
vec4 driver(vec2 q, float r, float exc, vec3 tint, float tb) {
    if (length(q) > r * 1.38) return vec4(0.0);
    vec3 o = vec3(0.0);
    float cov = 0.0;
    float d = length(q);
    float a = atan(q.y, q.x);

    paint(o, cov, mix(vec3(0.18, 0.19, 0.23), accentA() * 0.35, 0.4),
          fill(abs(d - r * 1.16) - r * 0.10, 0.004));
    for (int i = 0; i < 8; i++) {
        float ba = float(i) / 8.0 * TAU + 0.2;
        vec2 bp = vec2(cos(ba), sin(ba)) * r * 1.16;
        paint(o, cov, vec3(0.72, 0.76, 0.84) * (0.6 + iTreble * 0.7),
              fill(length(q - bp) - r * 0.045, 0.003));
    }

    float surR = r * 0.92 + exc * r * 0.05;
    float roll = 0.55 + 0.45 * cos((d - surR) / (r * 0.10) * PI);
    paint(o, cov, vec3(0.05, 0.05, 0.06) * (0.6 + roll * 0.9),
          fill(abs(d - surR) - r * 0.10, 0.005));

    // Cone: convex, lit from upper-left so it reads as coming toward you.
    float coneR = r * 0.86;
    float bulge = 1.0 - pow(clamp(d / coneR, 0.0, 1.0), 2.0);
    float lift = bulge * exc;
    float ridges = 0.5 + 0.5 * sin(d / coneR * 24.0 - lift * 6.0);
    vec3 cc = mix(accentB() * 0.55, accentA(), 0.35);
    cc *= 0.28 + ridges * 0.26 + lift * 1.25;
    cc += accentA() * 0.55 * pow(max(0.0, cos(a - 2.2)), 3.0) * bulge;
    // Individual cone rings fire in sequence outward from the dust cap on a
    // bass hit, so the cone reads as pumping rather than as a flat gradient.
    const float NRING = 7.0;
    float ri = floor(clamp(d / coneR, 0.0, 0.999) * NRING);
    float front = (1.0 - iPunch) * (NRING + 1.5);
    float rw = exp(-pow(ri - front, 2.0) * 1.6) * iPunch;
    cc = mix(cc, palette(iHue + ri * 0.13 + 0.20), clamp(rw * 0.85, 0.0, 1.0));
    cc += palette(iHue + ri * 0.13) * rw * (0.45 + iBass * 0.9);
    paint(o, cov, cc, fill(d - coneR, 0.005));

    float capR = r * 0.30;
    vec3 capc = mix(vec3(0.88, 0.92, 1.0), accentA(), 0.30);
    float spec = pow(max(0.0, 1.0 - length(q - vec2(-capR * 0.35, capR * 0.4)) / (capR * 0.9)), 3.0);
    paint(o, cov, capc * (0.28 + exc * 0.95) + vec3(1.0) * spec * (0.5 + iTreble),
          fill(d - capR, 0.004));
    return vec4(o, cov);
}

// ── surroundings ─────────────────────────────────────────────────────────────
vec3 backdrop(vec2 p, float A, float tb) {
    vec3 col;
    if (iBackdrop == 0) {
        col = mix(vec3(0.010, 0.006, 0.028), vec3(0.030, 0.010, 0.050), v_uv.y);
        float hz = -0.10;
        if (p.y < hz) {
            float depth = max(hz - p.y, 0.012);
            float persp = 0.055 / depth;
            float lx = smoothstep(0.05, 0.0, abs(fract(p.x * persp) - 0.5));
            float lz = smoothstep(0.05, 0.0, abs(fract(persp + tb * 0.35) - 0.5));
            float fade = smoothstep(0.0, 0.12, depth) * smoothstep(0.75, 0.15, depth);
            col += mix(MIX_CYAN, MIX_MAGENTA, 0.4) * (lx * 0.6 + lz) * fade
                 * (0.35 + iBass * 0.55);
        }
    } else if (iBackdrop == 1) {
        // Speaker wall — the cells now pump individually off the spectrum
        // instead of sitting there as static camouflage.
        col = vec3(0.010, 0.009, 0.015);
        vec2 g = vec2(p.x * 3.2, p.y * 3.2);
        vec2 c = floor(g);
        vec2 f = fract(g) - 0.5;
        float h = hash21(c);
        float v = band(fract(h * 3.7));
        float ring = fill(abs(length(f) - (0.26 + v * 0.06)) - 0.05, 0.02);
        col += mix(accentA(), accentB(), h) * ring * (0.06 + v * 0.55 + iBass * 0.25);
        col += vec3(0.04) * fill(abs(max(abs(f.x), abs(f.y)) - 0.47) - 0.01, 0.01);
    } else {
        // Skyline whose towers rise and fall with the spectrum.
        col = mix(vec3(0.022, 0.008, 0.032), vec3(0.004, 0.006, 0.020), v_uv.y);
        float lane = floor(p.x * 34.0);
        float h = hash21(vec2(lane, 3.0));
        float v = band(fract(h * 5.1));
        float bh = -0.34 + h * 0.22 + v * 0.26;
        float b = step(p.y, bh) * step(-0.55, p.y);
        float gap = smoothstep(0.12, 0.30, abs(fract(p.x * 34.0) - 0.5));
        col += mix(accentA(), MIX_MAGENTA, h) * b * gap * (0.07 + v * 0.30);
        col += MIX_YELLOW * step(0.72, hash21(floor(vec2(p.x * 120.0, p.y * 90.0))))
             * b * gap * 0.20;
    }

    for (int i = 0; i < 4; i++) {
        float ph = fract(iRing * 0.35 + float(i) * 0.25);
        float rr = ph * 1.7;
        float ring = smoothstep(0.05, 0.0, abs(length(p) - rr)) * (1.0 - ph);
        col += mix(accentA(), accentB(), float(i) * 0.33) * ring
             * (0.20 + iBass * 0.75) * (0.4 + iPunch * 1.2);
    }
    col += accentB() * exp(-dot(p, p) * 1.6) * (0.03 + iBass * 0.20);
    return col;
}

// ── scenes ───────────────────────────────────────────────────────────────────
vec4 sceneSubwoofer(vec2 p, float tb) {
    vec3 tint = cabinetTint();
    vec3 o = vec3(0.0);
    float cov = 0.0;
    vec2 q = p / (1.0 + iPunch * 0.05 + iBass * 0.04);

    // Feet, so the box can never read upside down.
    for (int s = -1; s <= 1; s += 2) {
        paint(o, cov, vec3(0.10, 0.11, 0.13),
              fill(sdRound(q - vec2(float(s) * 0.40, -0.60), vec2(0.09, 0.045), 0.02), 0.005));
    }

    float cabD = sdRound(q - vec2(0.0, 0.02), vec2(0.60, 0.54), 0.05);
    float cab = fill(cabD, 0.006);
    paint(o, cov, tint, cab);
    o += accentB() * dripMask(q, 0.54, 0.58, tb, 5.0) * cab * 1.7;
    o += mix(vec3(0.85, 0.9, 1.0), accentA(), 0.5) * fill(abs(cabD) - 0.006, 0.004)
       * (0.8 + iTreble * 1.1);

    // Tweeters flank the driver. Both were oversized before and their rings
    // ran under the woofer's basket; pulled in and spaced clear of it.
    for (int s = -1; s <= 1; s += 2) {
        vec2 pp = q - vec2(float(s) * 0.47, 0.16);
        float pd = length(pp);
        paint(o, cov, vec3(0.015), fill(pd - 0.062, 0.005));
        paint(o, cov, mix(vec3(0.80, 0.85, 0.95), accentA(), 0.45) * (0.35 + iTreble * 1.1),
              fill(pd - 0.036, 0.004));
        o += vec3(1.0) * fill(length(pp - vec2(-0.012, 0.012)) - 0.010, 0.006) * 0.5;
        o += accentA() * fill(abs(pd - 0.062) - 0.007, 0.004) * (0.8 + iTreble * 1.4);
        for (int i = 0; i < 3; i++) {
            float ph = fract(iRing * 0.5 + float(i) * 0.34);
            o += accentA() * smoothstep(0.024, 0.0, abs(pd - (0.062 + ph * 0.22)))
               * (1.0 - ph) * (0.15 + iPunch * 0.9);
        }
        // Sparkles fired out of the tweeter when the highs hit.
        for (int k = 0; k < 9; k++) {
            float fk = float(k);
            float sa = fk / 9.0 * TAU + hash21(vec2(fk, float(s) + 4.0)) * 6.28;
            float ph = fract(iRing * 1.7 + fk * 0.117);
            vec2 sq = pp - vec2(cos(sa), sin(sa)) * (0.055 + ph * 0.20);
            o += mix(vec3(1.0), palette(iHue + fk * 0.11), 0.45)
               * exp(-dot(sq, sq) * 4200.0) * (1.0 - ph)
               * (0.5 + iTreble * 2.2) * (0.25 + iPunch * 1.5);
        }
    }

    vec4 dv = driver(q - vec2(0.0, 0.16), 0.255, iBass, tint, tb);
    o = mix(o, dv.rgb, dv.a);
    cov = max(cov, dv.a);

    // Neon level trough with the bead dancing along it.
    float bc;
    vec3 bar = beadBar(q - vec2(0.0, -0.25), vec2(0.42, 0.034),
                       clamp(iBass * 0.75 + iMid * 0.25, 0.0, 1.0), tb, accentA(), bc);
    o = mix(o, bar, bc);
    o += bar * (1.0 - bc);
    cov = max(cov, bc);

    // Spectrum pegged to the cabinet's bottom edge, growing up.
    float sc;
    o += spectrumBars(q - vec2(0.0, 0.0), -0.48, 0.52, 0.13, accentB(), sc);
    cov = max(cov, sc);
    return vec4(o, cov);
}

vec4 sceneBoombox(vec2 p, float tb) {
    vec3 tint = cabinetTint();
    vec3 o = vec3(0.0);
    float cov = 0.0;
    // Shrunk so the handle clears the frame instead of being cropped.
    vec2 q = p / (0.86 + iPunch * 0.03);

    // Carry handle.
    float hd = abs(length((q - vec2(0.0, 0.40)) / vec2(1.0, 0.90)) - 0.24) - 0.020;
    paint(o, cov, vec3(0.14, 0.15, 0.18), fill(hd, 0.005) * step(q.y, 0.66));

    float bodyD = sdRound(q, vec2(0.74, 0.40), 0.05);
    float body = fill(bodyD, 0.006);
    paint(o, cov, tint, body);
    // Mask the drips out over the woofers. The drivers composite on top, but
    // their coverage has thin gaps (between surround and basket rim, and
    // outside the rim), so an unmasked drip bleeds through those rings.
    float spk = 0.0;
    for (int s = -1; s <= 1; s += 2) {
        spk = max(spk, 1.0 - smoothstep(0.238, 0.256,
                                        length(q - vec2(float(s) * 0.47, 0.11))));
    }
    o += accentB() * dripMask(q, 0.40, 0.72, tb, 9.0) * body * (1.0 - spk) * 1.6;
    o += mix(vec3(0.85, 0.9, 1.0), accentA(), 0.5) * fill(abs(bodyD) - 0.006, 0.004)
       * (0.8 + iTreble * 1.0);

    // Twin woofers, pulled outward so nothing overlaps them.
    for (int s = -1; s <= 1; s += 2) {
        vec4 dv = driver(q - vec2(float(s) * 0.47, 0.11), 0.185, iBass, tint, tb);
        o = mix(o, dv.rgb, dv.a);
        cov = max(cov, dv.a);
    }

    // Tape deck, centred between them.
    vec2 dq = q - vec2(0.0, 0.19);
    float deckD = sdRound(dq, vec2(0.155, 0.095), 0.02);
    paint(o, cov, vec3(0.04, 0.045, 0.06), fill(deckD, 0.004));
    o += accentA() * fill(abs(deckD) - 0.004, 0.003) * 1.1;
    for (int s = -1; s <= 1; s += 2) {
        vec2 rq = dq - vec2(float(s) * 0.072, 0.0);
        paint(o, cov, mix(vec3(0.10, 0.11, 0.14), accentB() * 0.5, 0.5),
              fill(length(rq) - 0.045, 0.004));
        for (int k = 0; k < 3; k++) {
            float a = iSpin * 2.2 + float(k) / 3.0 * TAU;
            vec2 dir = vec2(cos(a), sin(a));
            float along = dot(rq, dir);
            paint(o, cov, MIX_YELLOW,
                  smoothstep(0.006, 0.0, length(rq - dir * along))
                  * step(0.0, along) * step(along, 0.040));
        }
        paint(o, cov, vec3(0.05), fill(length(rq) - 0.013, 0.003));
    }

    // VU pair below the deck, still clear of the woofers.
    for (int s = -1; s <= 1; s += 2) {
        vec2 vq = q - vec2(float(s) * 0.085, -0.03);
        float dial = fill(sdRound(vq, vec2(0.078, 0.048), 0.014), 0.004);
        paint(o, cov, vec3(0.06, 0.07, 0.09), dial);
        o += accentA() * fill(abs(sdRound(vq, vec2(0.078, 0.048), 0.014)) - 0.003, 0.002) * 0.9;
        float lvl = (s < 0) ? iBass : iMid;
        float a = PI * 0.75 - clamp(lvl, 0.0, 1.4) * PI * 0.5;
        vec2 dir = vec2(cos(a), sin(a));
        float along = dot(vq - vec2(0.0, -0.028), dir);
        float perp = length((vq - vec2(0.0, -0.028)) - dir * along);
        o += MIX_PINK * smoothstep(0.004, 0.0, perp)
           * step(0.0, along) * step(along, 0.062) * dial * 3.2;
    }

    // Spectrum across the full width, pegged to the body's bottom edge.
    float sc;
    o += spectrumBars(q, -0.355, 0.66, 0.125, MIX_AMBER, sc);
    cov = max(cov, sc);
    return vec4(o, cov);
}

vec4 sceneTurntable(vec2 p, float tb) {
    vec3 tint = cabinetTint();
    vec3 o = vec3(0.0);
    float cov = 0.0;
    vec2 q = p / (1.0 + iPunch * 0.03);

    float plD = sdRound(q, vec2(0.78, 0.50), 0.05);
    float plinth = fill(plD, 0.006);
    paint(o, cov, tint, plinth);
    // The slab used to be flat and dead — brushed metal, a lit seam and a
    // corner glow give it something to look at.
    float brush = 0.5 + 0.5 * sin(q.y * 260.0 + hash21(floor(vec2(q.y * 120.0, 1.0))) * 6.0);
    o += accentA() * plinth * brush * 0.035;
    o += accentB() * plinth
       * smoothstep(0.55, 0.0, length(q - vec2(0.52, -0.34))) * (0.10 + iBass * 0.25);
    o += accentA() * fill(abs(sdRound(q, vec2(0.70, 0.43), 0.04)) - 0.0025, 0.002) * 0.5;
    o += accentB() * dripMask(q, 0.50, 0.76, tb, 13.0) * plinth * 1.6;
    o += mix(vec3(0.85, 0.9, 1.0), accentA(), 0.5) * fill(abs(plD) - 0.006, 0.004)
       * (0.8 + iTreble * 1.0);

    vec2 rq = q - vec2(-0.20, 0.05);
    float d = length(rq);
    paint(o, cov, vec3(0.10, 0.11, 0.14), fill(d - 0.305, 0.006));

    float a = atan(rq.y, rq.x) + iSpin;
    float t01 = clamp((d - 0.075) / 0.195, 0.0, 1.0);
    float v = band(1.0 - t01);
    float groove = 0.5 + 0.5 * sin(d * 320.0 + v * 26.0 - iSpin * 2.0);
    vec3 vinyl = vec3(0.040, 0.040, 0.050) * (0.55 + groove * 0.75);
    vinyl += mix(accentA(), vec3(1.0), 0.35)
           * pow(max(0.0, cos(a - 0.6)), 6.0) * (0.10 + v * 0.55 + iTreble * 0.25);
    paint(o, cov, vinyl, fill(d - 0.270, 0.005));

    vec3 lc = mix(accentB(), MIX_MAGENTA, 0.4) * (0.55 + 0.45 * step(0.5, fract(a / TAU * 6.0)));
    paint(o, cov, lc * (0.7 + iMid * 0.8), fill(d - 0.085, 0.004));
    paint(o, cov, vec3(0.02), fill(d - 0.012, 0.003));

    // Rim blocks: most are plain strobe marks, but a travelling group lights up
    // in colour and rides around with the platter glow.
    float slot = a / TAU * 40.0;
    float sIdx = floor(slot);
    float on = step(0.5, fract(slot));
    float chase = fract(sIdx / 40.0 - iSpin * 0.05);
    float hot = smoothstep(0.10, 0.0, min(chase, 1.0 - chase));
    vec3 blockCol = mix(vec3(1.0, 0.95, 0.8),
                        palette(iHue + sIdx * 0.02 + tb * 0.15), hot);
    o += blockCol * smoothstep(0.014, 0.0, abs(d - 0.290)) * on
       * (0.5 + iTreble * 0.9 + hot * (1.6 + iBass * 1.4));

    // The arm twitches on every beat — a quick angular kick that settles, the
    // way a stylus jumps in a groove.
    float twitch = iBeat * sin(tb * 42.0) * 0.055;
    float track = 0.245 - 0.115 * fract(iSpin * 0.012);
    vec2 pivot = vec2(0.44, 0.27);
    vec2 head = vec2(-0.20, 0.05) + vec2(cos(-0.55 + twitch), sin(-0.55 + twitch)) * track;
    vec2 ad = normalize(head - pivot);
    float along = dot(q - pivot, ad);
    float armLen = length(head - pivot);
    paint(o, cov, vec3(0.78, 0.81, 0.88),
          smoothstep(0.008, 0.005, length((q - pivot) - ad * along))
          * step(0.0, along) * step(along, armLen));
    paint(o, cov, MIX_PINK, fill(length(q - head) - 0.021, 0.004));
    o += MIX_PINK * exp(-pow(length(q - head), 2.0) * 900.0) * iBeat * 1.4;
    paint(o, cov, vec3(0.26, 0.28, 0.34), fill(length(q - pivot) - 0.042, 0.005));

    // Pitch fader filling the dead space on the right.
    float bc;
    vec3 bar = beadBar(q - vec2(0.44, -0.16), vec2(0.20, 0.030),
                       clamp(iMid * 0.8 + iBass * 0.2, 0.0, 1.0), tb, accentA(), bc);
    o = mix(o, bar, bc);
    o += bar * (1.0 - bc);
    cov = max(cov, bc);

    float sc;
    o += spectrumBars(q, -0.445, 0.70, 0.145, MIX_GREEN, sc);
    cov = max(cov, sc);
    return vec4(o, cov);
}

// Shooting laser streaks + rainbow drips, replacing the old sparkle field.
vec3 lasersAndDrips(vec2 p, float A, float tb) {
    vec3 col = vec3(0.0);
    for (int i = 0; i < 3; i++) {
        float fi = float(i);
        float seed = hash21(vec2(fi, floor(tb * 0.35 + fi * 7.0)));
        float ph = fract(tb * 0.35 + fi * 0.37);
        float ang = seed * TAU;
        vec2 dir = vec2(cos(ang), sin(ang));
        vec2 nrm = vec2(-dir.y, dir.x);
        vec2 origin = (vec2(seed, hash21(vec2(fi + 9.0, floor(tb * 0.35)))) - 0.5)
                    * vec2(A * 1.6, 1.4);
        float along = dot(p - origin, dir);
        float perp = dot(p - origin, nrm);
        float headPos = (ph * 2.4 - 0.6) * A;
        float body = smoothstep(0.0, 0.35, headPos - along) * step(along, headPos);
        float streak = smoothstep(0.010, 0.0, abs(perp)) * body;
        float head = exp(-pow(along - headPos, 2.0) * 260.0 - perp * perp * 900.0);
        vec3 lc = palette(iHue + seed + tb * 0.05);
        col += lc * (streak * 0.9 + head * 2.2) * sin(ph * PI) * (0.4 + iTreble * 1.1);
    }
    // Rainbow drips down the screen edges.
    float edge = smoothstep(0.55, 0.95, abs(p.x) / (A * 0.5));
    float lane = floor(p.x * 26.0);
    float h = hash21(vec2(lane, 21.0));
    float flow = fract(tb * (0.10 + h * 0.22) + h);
    float top = 0.52;
    float dy = top - p.y;
    float len = 0.25 + h * 0.55;
    float across = abs(fract(p.x * 26.0) - 0.5) * 2.0;
    float drip = smoothstep(0.35, 0.0, across) * step(0.0, dy)
               * smoothstep(len * flow + 0.03, 0.0, dy);
    col += palette(iHue + h * 0.9 + 0.2) * drip * edge * (0.25 + iMid * 0.6);
    return col;
}

void main() {
    float A = iResolution.x / max(iResolution.y, 1.0);
    vec2 p = (v_uv - 0.5) * vec2(A, 1.0) / max(iZoom, 0.05);
    float tb = mod(iTime, 120.0);

    vec3 col = backdrop(p, A, tb);

    vec2 mp = p / SCENE_SCALE;
    vec4 machine = (iScene == 0) ? sceneSubwoofer(mp, tb)
                 : (iScene == 1) ? sceneBoombox(mp, tb)
                                 : sceneTurntable(mp, tb);
    col = mix(col, machine.rgb, machine.a);

    col += palette(iHue + 0.7) * iBeat * 0.10;
    col += lasersAndDrips(p, A, tb) * iGlitter;

    col *= smoothstep(1.45, 0.20, length(v_uv - 0.5));
    col = col / (1.0 + col * 0.55);
    col = pow(clamp(col, 0.0, 1.0), vec3(0.85));
    fragColor = vec4(col, 1.0);
}
"""


class AudioBassMachine(BaseEffect):
    """Playback hardware driven by the live spectrum: sub, boombox, turntable."""

    NAME = 'Audio Bass Machine'
    AUTHOR = 'unicorn-viz'
    TAGS = ['analyzer', 'visualizer', 'bass', 'groovy', 'energetic', 'intense']
    PING_PONG_FRIENDS = [
        'Audio Spectrum', 'Audio Spectrogram', 'Audio Waveforms', 'Audio Chromogram',
        'Audio Centroid', 'Disco Ball', 'Unicorn Tears',
    ]

    # Scene shown by the previous instance, so a fresh activation never opens
    # on the same one twice running.
    _last_scene: int | None = None

    def _init(self) -> None:
        self.parameters = {
            'speed': float(self.config.get('speed', 1.0)),
            'zoom': float(self.config.get('zoom', 1.0)),
            'reactivity': float(self.config.get('reactivity', 1.3)),
            'glitter': float(self.config.get('glitter', 1.0)),
        }
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad(self._prog)

        self._bass = self._mid = self._treble = 0.0
        self._beat = 0.0
        self._punch = 0.0
        self._bands = np.zeros(_NBANDS, dtype=np.float32)

        choices = [s for s in range(_NSCENE) if s != AudioBassMachine._last_scene]
        self._scene = int(self.rng.choice(choices))
        AudioBassMachine._last_scene = self._scene
        self._scene_timer = float(self.rng.uniform(14.0, 26.0))
        self._hue = float(self.rng.uniform(0.0, 1.0))
        self._tint = float(self.rng.uniform(0.0, 1.0))
        self._backdrop = int(self.rng.integers(0, 3))
        self._spin = float(self.rng.uniform(0.0, 100.0))
        self._ring = float(self.rng.uniform(0.0, 100.0))

    def _choose_scene(self) -> None:
        choices = [s for s in range(_NSCENE) if s != self._scene]
        self._scene = int(self.rng.choice(choices))
        AudioBassMachine._last_scene = self._scene
        self._scene_timer = float(self.rng.uniform(14.0, 26.0))
        self._hue = float((self._hue + self.rng.uniform(0.15, 0.4)) % 1.0)
        self._tint = float(self.rng.uniform(0.0, 1.0))
        self._backdrop = int(self.rng.integers(0, 3))

    def update(self, dt: float, audio: AudioData) -> None:
        """Track the analyzer and advance the scene/rotation phases."""
        super().update(dt, audio)
        react = max(0.05, float(self.parameters['reactivity']))
        self._bass = float(np.clip(audio.bass_n * react, 0.0, 2.0))
        self._mid = float(np.clip(audio.mid_n * react, 0.0, 2.0))
        self._treble = float(np.clip(audio.treble_n * react, 0.0, 2.0))
        if audio.beat > 0.5:
            self._beat = 1.0
            self._punch = 1.0
        self._beat = max(0.0, self._beat - dt * 6.0)
        self._punch = max(0.0, self._punch - dt * 2.4)

        bands = np.asarray(audio.bands, dtype=np.float32)
        if bands.size >= _NBANDS:
            fresh = bands[:_NBANDS]
        else:
            fresh = np.zeros(_NBANDS, dtype=np.float32)
            fresh[:bands.size] = bands
        # Light smoothing keeps the ladder and grooves readable without
        # blunting the attack the whole effect is built around.
        self._bands = self._bands * 0.55 + np.clip(fresh * react, 0.0, 4.0) * 0.45

        speed = max(0.05, float(self.parameters['speed']))
        # Audio modulates the *rate*; multiplying an ever-growing iTime by a
        # per-frame audio value would teleport the phase every frame.
        self._spin = (self._spin + dt * speed * (0.9 + self._mid * 1.5)) % 1000.0
        self._ring = (self._ring + dt * speed * (0.5 + self._bass * 1.4)) % 1000.0

        self._scene_timer -= dt
        if self._scene_timer <= 0.0:
            self._choose_scene()

    def render(self) -> None:
        """Upload the spectrum and machine state, then draw the scene."""
        p = self._prog
        p['iTime'].value = float(self.time)
        p['iResolution'].value = (float(self.width), float(self.height))
        p['iBass'].value = self._bass
        p['iMid'].value = self._mid
        p['iTreble'].value = self._treble
        p['iBeat'].value = self._beat
        p['iPunch'].value = self._punch
        p['iHue'].value = self._hue
        p['iZoom'].value = max(0.05, float(self.parameters['zoom']))
        p['iGlitter'].value = max(0.0, float(self.parameters['glitter']))
        p['iSpin'].value = float(self._spin)
        p['iRing'].value = float(self._ring)
        p['iTint'].value = float(self._tint)
        p['iScene'].value = int(self._scene)
        p['iBackdrop'].value = int(self._backdrop)
        p['iBands'].value = [float(v) for v in self._bands]
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        """Release GL resources."""
        self._vao.release()
        self._vbo.release()
        self._prog.release()
