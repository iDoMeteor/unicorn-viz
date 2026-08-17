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

float hash21(vec2 p) {
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
// Paint a layer, tracking coverage, so the machine composites *over* the
// surroundings instead of being added to them — an additive machine lets the
// backdrop's pressure rings shine straight through the cabinet.
void paint(inout vec3 o, inout float cov, vec3 c, float m) {
    m = clamp(m, 0.0, 1.0);
    o = mix(o, c, m);
    cov = max(cov, m);
}
// The gear is drawn in its own space then shrunk to fit: at 1:1 a cabinet
// 0.60 half-tall overflows a screen that is only 0.5 half-tall.
const float SCENE_SCALE = 0.66;

// Band lookup with linear interpolation, so ladders and grooves read smooth.
float band(float x) {
    x = clamp(x, 0.0, 1.0) * 63.0;
    int i = int(floor(x));
    int j = min(i + 1, 63);
    return mix(iBands[i], iBands[j], fract(x));
}

vec3 cabinetTint() {
    if (iTint < 0.25) return vec3(0.10, 0.11, 0.14);          // graphite
    if (iTint < 0.50) return mix(vec3(0.28, 0.16, 0.06), vec3(0.35, 0.20, 0.08), 0.5);  // wood
    if (iTint < 0.75) return vec3(0.10, 0.06, 0.16);          // aubergine
    return vec3(0.05, 0.12, 0.14);                            // teal steel
}

// Wet neon running down a face — the drip.
float drips(vec2 q, float top, float width, float tb, float seed) {
    float lanes = 26.0;
    float lane = floor((q.x + width) / (2.0 * width) * lanes);
    float h = hash21(vec2(lane, seed));
    float flow = fract(tb * (0.10 + h * 0.28) + h);
    float len = 0.05 + h * 0.22;
    float dy = top - q.y;
    float across = abs(fract((q.x + width) / (2.0 * width) * lanes) - 0.5);
    return smoothstep(0.30, 0.0, across)
         * step(0.0, dy) * smoothstep(len * flow + 0.02, 0.0, dy)
         * step(abs(q.x), width);
}

// Shared speaker driver, used by the subwoofer and both boombox woofers.
// `exc` is the cone excursion in [0,1]; the cone visibly moves with it.
vec4 driver(vec2 q, float r, float exc, vec3 tint, float tb) {
    if (length(q) > r * 1.35) return vec4(0.0);
    vec3 o = vec3(0.0);
    float cov = 0.0;
    float d = length(q);
    float a = atan(q.y, q.x);

    // Basket rim + mounting bolts.
    paint(o, cov, tint * 1.7, fill(abs(d - r * 1.14) - r * 0.09, 0.004));
    for (int i = 0; i < 8; i++) {
        float ba = float(i) / 8.0 * TAU + 0.2;
        vec2 bp = vec2(cos(ba), sin(ba)) * r * 1.14;
        paint(o, cov, vec3(0.70, 0.74, 0.80) * (0.6 + iTreble * 0.7),
              fill(length(q - bp) - r * 0.045, 0.003));
    }

    // Rubber surround: a torus that rolls outward as the cone pushes.
    float surR = r * 0.92 + exc * r * 0.05;
    float roll = 0.55 + 0.45 * cos((d - surR) / (r * 0.10) * PI);
    paint(o, cov, vec3(0.06, 0.06, 0.07) * (0.6 + roll * 0.9),
          fill(abs(d - surR) - r * 0.10, 0.005));

    // Cone: concentric ridges, brighter as it comes toward the viewer.
    float coneR = r * 0.86;
    float bulge = 1.0 - pow(clamp(d / coneR, 0.0, 1.0), 2.0);
    float lift = bulge * exc;
    float ridges = 0.5 + 0.5 * sin(d / coneR * 26.0 - lift * 6.0);
    vec3 cc = mix(tint * 0.75, palette(iHue + 0.05), 0.30);
    cc *= 0.35 + ridges * 0.30 + lift * 1.15;
    cc += tint * 0.5 * pow(max(0.0, cos(a - 0.7)), 3.0) * bulge;
    paint(o, cov, cc, fill(d - coneR, 0.005));

    // Dust cap with a moving chrome specular.
    float capR = r * 0.30;
    vec3 capc = mix(vec3(0.85, 0.88, 0.95), palette(iHue + 0.4), 0.35);
    float spec = pow(max(0.0, 1.0 - length(q - vec2(-capR * 0.35, capR * 0.4)) / (capR * 0.9)), 3.0);
    paint(o, cov, capc * (0.30 + exc * 0.9) + vec3(1.0) * spec * (0.5 + iTreble),
          fill(d - capR, 0.004));
    return vec4(o, cov);
}

// ── surroundings ─────────────────────────────────────────────────────────────
vec3 backdrop(vec2 p, float A, float tb) {
    vec3 col;
    if (iBackdrop == 0) {
        // Neon floor grid receding to a horizon.
        col = mix(vec3(0.010, 0.006, 0.028), vec3(0.030, 0.010, 0.050), v_uv.y);
        float hz = -0.10;
        if (p.y < hz) {
            float depth = max(hz - p.y, 0.012);
            float persp = 0.055 / depth;
            float lx = smoothstep(0.05, 0.0, abs(fract(p.x * persp) - 0.5));
            float lz = smoothstep(0.05, 0.0, abs(fract(persp + tb * 0.35) - 0.5));
            float fade = smoothstep(0.0, 0.12, depth) * smoothstep(0.75, 0.15, depth);
            col += mix(vec3(0.15, 0.55, 1.0), palette(iHue), 0.5)
                 * (lx * 0.6 + lz) * fade * (0.35 + iBass * 0.55);
        }
    } else if (iBackdrop == 1) {
        // Stacked speaker wall.
        col = vec3(0.012, 0.010, 0.016);
        vec2 c = floor(vec2(p.x * 3.2, p.y * 3.2));
        vec2 f = fract(vec2(p.x * 3.2, p.y * 3.2)) - 0.5;
        float h = hash21(c);
        float ring = fill(abs(length(f) - 0.30) - 0.045, 0.02);
        col += mix(palette(iHue + h * 0.4), vec3(0.3), 0.4) * ring
             * (0.10 + iBass * 0.35 + h * 0.05);
        col += vec3(0.05) * fill(abs(max(abs(f.x), abs(f.y)) - 0.47) - 0.01, 0.01);
    } else {
        // City lights behind haze.
        col = mix(vec3(0.020, 0.008, 0.030), vec3(0.004, 0.006, 0.020), v_uv.y);
        float lane = floor(p.x * 40.0);
        float h = hash21(vec2(lane, 3.0));
        float bh = -0.20 + h * 0.34;
        float b = step(p.y, bh) * step(-0.55, p.y);
        // Narrow towers with a fine window grid — a coarse grid here reads as
        // a block of noise rather than a skyline.
        float gap = smoothstep(0.12, 0.30, abs(fract(p.x * 40.0) - 0.5));
        col += mix(palette(iHue + h), vec3(0.18, 0.26, 0.55), 0.55) * b * gap * 0.09;
        float win = step(0.72, hash21(floor(vec2(p.x * 150.0, p.y * 110.0))));
        col += vec3(1.0, 0.82, 0.48) * win * b * gap * 0.22;
    }

    // Pressure rings blasting outward — the room reacting to the low end.
    for (int i = 0; i < 4; i++) {
        float ph = fract(iRing * 0.35 + float(i) * 0.25);
        float rr = ph * 1.7;
        float ring = smoothstep(0.05, 0.0, abs(length(p) - rr)) * (1.0 - ph);
        col += palette(iHue + 0.15 + float(i) * 0.08) * ring
             * (0.20 + iBass * 0.75) * (0.4 + iPunch * 1.2);
    }
    // Low-end haze.
    col += palette(iHue + 0.55) * exp(-dot(p, p) * 1.6) * (0.03 + iBass * 0.20);
    return col;
}

// ── scenes ───────────────────────────────────────────────────────────────────
vec4 sceneSubwoofer(vec2 p, float tb) {
    vec3 tint = cabinetTint();
    vec3 o = vec3(0.0);
    float cov = 0.0;
    vec2 q = p / (1.0 + iPunch * 0.05 + iBass * 0.04);

    // Cabinet.
    float cabD = sdRound(q, vec2(0.62, 0.60), 0.06);
    float cab = fill(cabD, 0.006);
    paint(o, cov, tint, cab);
    o += palette(iHue + 0.5) * drips(q, 0.58, 0.60, tb, 5.0) * cab * 1.5;
    o += mix(vec3(0.8, 0.85, 0.95), palette(iHue + 0.2), 0.4)
       * fill(abs(cabD) - 0.007, 0.004) * (0.7 + iTreble * 1.1);

    // Bass ports either side, exhaling on the beat.
    for (int s = -1; s <= 1; s += 2) {
        vec2 pp = q - vec2(float(s) * 0.47, -0.40);
        paint(o, cov, vec3(0.02), fill(length(pp) - 0.085, 0.005));
        o += palette(iHue + 0.3) * fill(abs(length(pp) - 0.085) - 0.008, 0.004)
           * (0.6 + iBass);
        for (int i = 0; i < 3; i++) {
            float ph = fract(iRing * 0.5 + float(i) * 0.34);
            float rr = 0.085 + ph * 0.30;
            o += palette(iHue + 0.3) * smoothstep(0.030, 0.0, abs(length(pp) - rr))
               * (1.0 - ph) * (0.15 + iPunch * 0.9);
        }
    }

    // The driver itself.
    vec4 dv = driver(q - vec2(0.0, -0.02), 0.40, iBass, tint, tb);
    o = mix(o, dv.rgb, dv.a);
    cov = max(cov, dv.a);

    // Badge.
    paint(o, cov, mix(vec3(0.9, 0.85, 0.6), palette(iHue), 0.4) * (0.35 + iMid * 0.7),
          fill(sdRound(q - vec2(0.0, 0.48), vec2(0.16, 0.035), 0.02), 0.004));
    return vec4(o, cov);
}

vec4 sceneBoombox(vec2 p, float tb) {
    vec3 tint = cabinetTint();
    vec3 o = vec3(0.0);
    float cov = 0.0;
    vec2 q = p / (1.0 + iPunch * 0.04);

    // Carry handle.
    float hd = abs(length((q - vec2(0.0, 0.42)) / vec2(1.0, 0.85)) - 0.26) - 0.022;
    paint(o, cov, vec3(0.16, 0.16, 0.18), fill(hd, 0.005) * step(q.y, 0.62));

    // Body.
    float bodyD = sdRound(q, vec2(0.78, 0.40), 0.05);
    float body = fill(bodyD, 0.006);
    paint(o, cov, tint, body);
    o += palette(iHue + 0.45) * drips(q, 0.38, 0.76, tb, 9.0) * body * 1.4;
    o += mix(vec3(0.8, 0.85, 0.95), palette(iHue + 0.2), 0.4)
       * fill(abs(bodyD) - 0.006, 0.004) * (0.7 + iTreble * 1.0);

    // Twin woofers.
    for (int s = -1; s <= 1; s += 2) {
        vec4 dv = driver(q - vec2(float(s) * 0.50, -0.03), 0.24, iBass, tint, tb);
        o = mix(o, dv.rgb, dv.a);
        cov = max(cov, dv.a);
    }

    // Tape deck with turning reels.
    vec2 dq = q - vec2(0.0, 0.10);
    float deckD = sdRound(dq, vec2(0.21, 0.13), 0.02);
    paint(o, cov, vec3(0.05, 0.05, 0.07), fill(deckD, 0.004));
    o += vec3(0.35, 0.85, 1.0) * fill(abs(deckD) - 0.004, 0.003) * 0.8;
    for (int s = -1; s <= 1; s += 2) {
        vec2 rq = dq - vec2(float(s) * 0.095, 0.0);
        paint(o, cov, vec3(0.55, 0.40, 0.20), fill(length(rq) - 0.055, 0.004));
        for (int k = 0; k < 3; k++) {
            float a = iSpin * 2.2 + float(k) / 3.0 * TAU;
            vec2 dir = vec2(cos(a), sin(a));
            float along = dot(rq, dir);
            float perp = length(rq - dir * along);
            paint(o, cov, vec3(0.95, 0.85, 0.6),
                  smoothstep(0.007, 0.0, perp) * step(0.0, along) * step(along, 0.050));
        }
        paint(o, cov, vec3(0.10), fill(length(rq) - 0.016, 0.003));
    }

    // Real 64-band EQ ladder across the front.
    for (int i = 0; i < 16; i++) {
        float fi = float(i);
        float v = band(fi / 15.0);
        float h = 0.02 + v * 0.10;
        vec2 eq = q - vec2(-0.30 + fi * 0.04, -0.28 + h * 0.5);
        paint(o, cov, palette(iHue + fi * 0.03 + 0.1) * (0.6 + v * 1.6),
              fill(sdRound(eq, vec2(0.014, h * 0.5), 0.005), 0.003));
    }

    // VU needles: bass on the left, mid on the right.
    for (int s = -1; s <= 1; s += 2) {
        vec2 vq = q - vec2(float(s) * 0.30, 0.24);
        float dial = fill(sdRound(vq, vec2(0.10, 0.055), 0.015), 0.004);
        paint(o, cov, vec3(0.90, 0.86, 0.70) * 0.30, dial);
        float lvl = (s < 0) ? iBass : iMid;
        float a = PI * 0.75 - clamp(lvl, 0.0, 1.4) * PI * 0.5;
        vec2 dir = vec2(cos(a), sin(a));
        float along = dot(vq - vec2(0.0, -0.03), dir);
        float perp = length((vq - vec2(0.0, -0.03)) - dir * along);
        o += vec3(1.0, 0.25, 0.15) * smoothstep(0.005, 0.0, perp)
           * step(0.0, along) * step(along, 0.075) * dial * 3.0;
    }
    return vec4(o, cov);
}

vec4 sceneTurntable(vec2 p, float tb) {
    vec3 tint = cabinetTint();
    vec3 o = vec3(0.0);
    float cov = 0.0;
    vec2 q = p / (1.0 + iPunch * 0.03);

    // Plinth.
    float plD = sdRound(q - vec2(0.0, -0.03), vec2(0.80, 0.52), 0.05);
    float plinth = fill(plD, 0.006);
    paint(o, cov, tint, plinth);
    o += palette(iHue + 0.4) * drips(q - vec2(0.0, -0.03), 0.46, 0.78, tb, 13.0) * plinth * 1.4;
    o += mix(vec3(0.8, 0.85, 0.95), palette(iHue + 0.2), 0.4)
       * fill(abs(plD) - 0.006, 0.004) * (0.7 + iTreble * 1.0);

    // Platter and record.
    vec2 rq = q - vec2(-0.10, -0.02);
    float d = length(rq);
    paint(o, cov, vec3(0.13, 0.13, 0.15), fill(d - 0.42, 0.006));

    float a = atan(rq.y, rq.x) + iSpin;
    float t01 = clamp((d - 0.10) / 0.28, 0.0, 1.0);
    float v = band(1.0 - t01);
    float groove = 0.5 + 0.5 * sin(d * 320.0 + v * 26.0 - iSpin * 2.0);
    vec3 vinyl = vec3(0.045, 0.045, 0.055) * (0.55 + groove * 0.75);
    vinyl += mix(palette(iHue + 0.1), vec3(1.0), 0.35)
           * pow(max(0.0, cos(a - 0.6)), 6.0) * (0.10 + v * 0.55 + iTreble * 0.25);
    paint(o, cov, vinyl, fill(d - 0.38, 0.005));

    // Label.
    vec3 lc = palette(iHue + 0.6) * (0.55 + 0.45 * step(0.5, fract(a / TAU * 6.0)));
    paint(o, cov, lc * (0.7 + iMid * 0.8), fill(d - 0.115, 0.004));
    paint(o, cov, vec3(0.02), fill(d - 0.014, 0.003));        // spindle hole

    // Strobe dots around the platter rim, as on a real deck.
    o += mix(vec3(1.0, 0.9, 0.5), palette(iHue), 0.3)
       * smoothstep(0.016, 0.0, abs(d - 0.405))
       * step(0.5, fract(a / TAU * 40.0)) * (0.5 + iTreble * 0.9);

    // Tonearm tracking inward across the disc.
    float track = 0.34 - 0.16 * fract(iSpin * 0.012);
    vec2 pivot = vec2(0.46, 0.26);
    vec2 head = vec2(-0.10, -0.02) + vec2(cos(-0.55), sin(-0.55)) * track;
    vec2 ad = normalize(head - pivot);
    float along = dot(q - pivot, ad);
    float perp = length((q - pivot) - ad * along);
    float armLen = length(head - pivot);
    paint(o, cov, vec3(0.75, 0.78, 0.85),
          smoothstep(0.010, 0.006, perp) * step(0.0, along) * step(along, armLen));
    paint(o, cov, vec3(0.85, 0.30, 0.25), fill(length(q - head) - 0.030, 0.004));
    paint(o, cov, vec3(0.30, 0.32, 0.38), fill(length(q - pivot) - 0.055, 0.005));
    return vec4(o, cov);
}

void main() {
    float A = iResolution.x / max(iResolution.y, 1.0);
    vec2 p = (v_uv - 0.5) * vec2(A, 1.0) / max(iZoom, 0.05);
    float tb = mod(iTime, 600.0);

    vec3 col = backdrop(p, A, tb);

    vec2 mp = p / SCENE_SCALE;
    vec4 machine = (iScene == 0) ? sceneSubwoofer(mp, tb)
                 : (iScene == 1) ? sceneBoombox(mp, tb)
                                 : sceneTurntable(mp, tb);
    col = mix(col, machine.rgb, machine.a);

    // Beat strobe + sparkle.
    col += palette(iHue + 0.7) * iBeat * 0.10;
    float sp = hash21(floor(v_uv * iResolution * 0.5) + floor(tb * 20.0));
    col += vec3(0.9, 0.92, 1.0) * step(0.9965, sp) * (0.3 + iTreble * 0.8) * iGlitter;

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
