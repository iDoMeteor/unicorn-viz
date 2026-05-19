"""
Crystal Pyramids — prismatic pyramid field with rainbow sky rays,
floating diamonds, and molten-gold desert glow.

Audio reactivity:
- bass   -> pyramid glow + ground pulse
- mid    -> prism hue travel + ray wobble
- treble -> sparkle density on facets and diamonds
- beat   -> strong rainbow ray burst + apex flash
"""
from __future__ import annotations

import moderngl

from unicornviz.effects.base import AudioData, BaseEffect

_VERT = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv = in_vert;
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
uniform float iSpeed;

in  vec2 v_uv;
out vec4 fragColor;

#define TAU 6.28318530718

float hash(vec2 p) {
    p = fract(p * vec2(127.1, 311.7));
    p += dot(p, p + 19.19);
    return fract(p.x * p.y);
}

vec3 rainbow(float t) {
    vec3 a = vec3(0.5, 0.5, 0.5);
    vec3 b = vec3(0.5, 0.5, 0.5);
    vec3 c = vec3(1.0, 1.0, 1.0);
    vec3 d = vec3(0.0, 0.33, 0.67);
    return a + b * cos(TAU * (c * t + d));
}

vec3 rayField(vec2 uv, float t, float gain) {
    vec2 src = vec2(-0.20, -0.10);
    vec2 p = uv - src;
    float ang = atan(p.y, p.x);
    float rad = length(p);
    float wave = sin(ang * 28.0 + t * 2.2) * 0.5 + 0.5;
    float beams = pow(max(0.0, wave), 3.0) * exp(-rad * 1.2);
    vec3 col = rainbow(ang / TAU + t * 0.10 + rad * 0.15);
    return col * beams * gain;
}

// 2D triangle SDF for upright pyramid silhouette
float sdTriangle(vec2 p, vec2 a, vec2 b, vec2 c) {
    vec2 ba = b - a; vec2 pa = p - a;
    vec2 cb = c - b; vec2 pb = p - b;
    vec2 ac = a - c; vec2 pc = p - c;
    vec2 nor = vec2(ba.y, -ba.x);
    float s = sign(dot(nor, ac));
    vec2 q = min(
        min(
            ba * clamp(dot(ba, pa) / dot(ba, ba), 0.0, 1.0) - pa,
            cb * clamp(dot(cb, pb) / dot(cb, cb), 0.0, 1.0) - pb
        ),
        ac * clamp(dot(ac, pc) / dot(ac, ac), 0.0, 1.0) - pc
    );
    float d = length(q);
    float inside = step(0.0, s * min(min(
        dot(vec2(ba.y, -ba.x), pa),
        dot(vec2(cb.y, -cb.x), pb)
    ), dot(vec2(ac.y, -ac.x), pc)));
    return mix(d, -d, inside);
}

float edgeTri(float d) {
    return smoothstep(0.06, 0.0, abs(d));
}

float sdDiamond(vec2 p, vec2 c, float r) {
    p -= c;
    p = abs(p);
    return (p.x + p.y) - r;
}

float sparkle(vec2 p, float size) {
    float r = length(p);
    if (r > size) return 0.0;
    float a = atan(p.y, p.x);
    float rays = abs(sin(a * 4.0)) * abs(cos(a * 4.0));
    float core = max(0.0, 1.0 - r / size);
    return core * core * (0.4 + 0.9 * rays);
}

void main() {
    float ar = iResolution.x / max(iResolution.y, 1.0);
    vec2 uv = vec2(v_uv.x * ar, v_uv.y);
    float t = iTime * (0.42 + iSpeed * 0.70);

    // Stage: deep-black backdrop with a tighter spotlight around the hero prism.
    vec3 col = vec3(0.01, 0.01, 0.02);
    vec2 spot_uv = (uv - vec2(0.04, 0.18)) * vec2(1.15, 2.35);
    float spot = exp(-dot(spot_uv, spot_uv) * 1.6);
    col += vec3(0.06, 0.07, 0.09) * spot * 0.26;

    // Stronger refracted rainbow rays (our style).
    col += rayField(uv, t, 0.30 + iMid * 0.25 + iBeat * 0.55);
    col += rayField(uv.yx * vec2(1.0, -1.0), t * 0.83 + 1.7, 0.18 + iBeat * 0.35);

    // Subtle lower-floor crystal base only; avoid broad scrolling curtain wash.
    float ground = 1.0 - smoothstep(-0.42, -0.06, v_uv.y);
    vec3 floorA = vec3(0.05, 0.06, 0.08);
    vec3 floorB = vec3(0.35, 0.42, 0.55);
    vec3 groundCol = mix(floorA, floorB, 0.22 + iBass * 0.12);
    col = mix(col, groundCol, ground * 0.36);

    // Pyramids (three layers)
    vec2 a1 = vec2(-0.72, -0.20), b1 = vec2(-0.30, -0.20), c1 = vec2(-0.51, 0.42);
    vec2 a2 = vec2(-0.24, -0.24), b2 = vec2( 0.34, -0.24), c2 = vec2( 0.05, 0.72); // hero
    vec2 a3 = vec2( 0.38, -0.20), b3 = vec2( 0.84, -0.20), c3 = vec2( 0.61, 0.40);

    float d1 = sdTriangle(uv, a1, b1, c1);
    float d2 = sdTriangle(uv, a2, b2, c2);
    float d3 = sdTriangle(uv, a3, b3, c3);

    float p1 = smoothstep(0.004, -0.004, d1);
    float p2 = smoothstep(0.004, -0.004, d2);
    float p3 = smoothstep(0.004, -0.004, d3);

    // Crystal facets from crossing planes; stronger refractive look.
    float f1 = 0.5 + 0.5 * sin((uv.x * 36.0 + uv.y * 45.0) + t * (1.4 + iMid));
    float f2 = 0.5 + 0.5 * sin((uv.x * 48.0 - uv.y * 34.0) - t * (1.0 + iMid * 0.9));
    float f3 = 0.5 + 0.5 * sin((uv.x * 22.0 + uv.y * 60.0) + t * 0.8);
    float facets = f1 * 0.45 + f2 * 0.35 + f3 * 0.20;

    // Refraction sample from the rainbow ray field with slight lensing.
    vec2 lens = normalize(uv - c2) * (0.012 + (1.0 - facets) * 0.018);
    vec3 refr = rayField(uv + lens, t + facets * 0.7, 1.0);

    vec3 crystal = mix(vec3(0.82, 0.90, 0.98), vec3(0.58, 0.78, 0.96), facets);
    crystal += refr * (0.55 + iMid * 0.45);
    crystal = mix(crystal, rainbow(facets + t * 0.05), 0.18 + iMid * 0.12);

    float pyramidMask = max(max(p1, p2), p3);
    col = mix(col, crystal, pyramidMask * (0.70 + iBass * 0.16));

    // Pyramid edges and apex glows
    float edge = (edgeTri(d1) + edgeTri(d2) + edgeTri(d3)) * 0.38;
    float fres = pow(1.0 - clamp(abs(uv.y - c2.y) * 2.2, 0.0, 1.0), 2.0);
    col += vec3(1.0, 0.98, 0.93) * edge * (0.30 + iTreble * 0.55 + fres * 0.25);

    vec2 apex2 = c2;
    col += rainbow(t * 0.1 + 0.2) * exp(-length(uv - apex2) * 13.0) * (0.28 + iBeat * 1.35);

    // Subtle metallic support feet under pyramid corners (cooler tone).
    vec2 g0 = vec2(-0.24, -0.25);
    vec2 g1 = vec2( 0.34, -0.25);
    vec2 g2 = vec2( 0.05, -0.07);
    float goldFeet = 0.0;
    goldFeet += smoothstep(0.050, 0.0, length(uv - g0));
    goldFeet += smoothstep(0.050, 0.0, length(uv - g1));
    goldFeet += smoothstep(0.040, 0.0, length(uv - g2));
    vec3 metal = mix(vec3(0.36, 0.38, 0.44), vec3(0.88, 0.92, 1.00), 0.5 + 0.5 * sin(t * 1.4 + uv.x * 20.0));
    col += metal * goldFeet * (0.28 + iBass * 0.22);

    // Floating diamonds: cool-white body with subtle spectral dispersion.
    vec3 dcol = vec3(0.0);
    for (int i = 0; i < 9; i++) {
        float fi = float(i);
        float hx = hash(vec2(fi, 1.3));
        float hy = hash(vec2(fi, 5.7));
        vec2 dc = vec2((hx * 2.0 - 1.0) * ar * 0.95, -0.02 + hy * 0.95);
        dc += vec2(sin(t * (0.7 + hx) + fi) * 0.05, cos(t * (0.9 + hy) + fi * 1.3) * 0.03);
        float dd = sdDiamond(uv, dc, 0.032 + hx * 0.018);
        float dm = smoothstep(0.004, -0.004, dd);
        float drim = smoothstep(0.040, 0.0, abs(dd));
        vec3 body = vec3(0.86, 0.93, 1.0) * dm;
        vec3 dispersion = rainbow(hx + t * 0.07 + drim * 0.3) * drim * 0.26;
        dcol += body + dispersion;

        // Sparkle near diamonds
        float sp = sparkle(uv - dc, 0.06 + hx * 0.03);
        dcol += vec3(0.96, 0.98, 1.0) * sp * (0.12 + iTreble * 0.34);
    }
    col += dcol * (0.24 + iTreble * 0.24 + iBeat * 0.20);

    // Subtle grain for lens-like richness
    float grain = hash(floor((uv + vec2(t * 0.02, 0.0)) * 420.0));
    col += (grain - 0.5) * 0.02;

    // Tone map + gamma
    col = col / (col + 0.65);
    col = pow(clamp(col, 0.0, 1.0), vec3(0.4545));

    fragColor = vec4(col, 1.0);
}
"""


class CrystalPyramids(BaseEffect):
    """Prismatic crystal pyramids with rainbow rays, diamonds, and molten gold."""

    NAME = "Crystal Pyramids"
    AUTHOR = "unicorn-viz"
    TAGS = ["futuristic", "audio", "mythic", "crystal"]
    PING_PONG_FRIENDS = ['Raymarcher', 'Particle Storm', 'Prism Storm']

    def _init(self) -> None:
        self.parameters = {"speed": float(self.config.get("speed", 1.0))}
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()
        self._bass = 0.0
        self._mid = 0.0
        self._treble = 0.0
        self._beat = 0.0

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass
        self._mid = audio.mid
        self._treble = audio.treble
        if audio.beat > 0.5:
            self._beat = 1.0
        self._beat = max(0.0, self._beat - dt * 3.5)

    def render(self) -> None:
        self._prog['iTime'].value = self.time
        self._prog['iResolution'].value = (float(self.width), float(self.height))
        self._prog['iBass'].value = self._bass
        self._prog['iMid'].value = self._mid
        self._prog['iTreble'].value = self._treble
        self._prog['iBeat'].value = self._beat
        self._prog['iSpeed'].value = float(self.parameters['speed'])
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
