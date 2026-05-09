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
    float t = iTime * (0.45 + iSpeed * 0.65);

    // Sky gradient
    vec3 skyA = vec3(0.02, 0.03, 0.11);
    vec3 skyB = vec3(0.10, 0.05, 0.22);
    float skyMix = smoothstep(-1.0, 0.8, v_uv.y);
    vec3 col = mix(skyA, skyB, skyMix);

    // Rainbow rays shooting from horizon center
    vec2 src = vec2(0.0, -0.28);
    vec2 rp = uv - src;
    float ang = atan(rp.y, rp.x);
    float rad = length(rp);
    float rayWave = sin(ang * 16.0 + t * (1.5 + iMid * 1.4));
    float rayMask = pow(max(0.0, 1.0 - rad * 0.8), 2.0) * (0.4 + 1.1 * iBeat);
    vec3 rays = rainbow(ang / TAU + t * 0.08 + iMid * 0.2) * max(0.0, rayWave) * rayMask;
    col += rays * (0.22 + iBeat * 0.9);

    // Gold desert / ground
    float ground = smoothstep(-0.26, -0.08, v_uv.y);
    vec3 goldA = vec3(0.25, 0.16, 0.03);
    vec3 goldB = vec3(0.86, 0.62, 0.16);
    float dunes = 0.5 + 0.5 * sin(uv.x * 8.0 + t * 0.9) * sin(uv.x * 3.0 - t * 0.5);
    vec3 groundCol = mix(goldA, goldB, dunes * 0.45 + iBass * 0.25);
    col = mix(col, groundCol, ground);

    // Pyramids (three layers)
    vec2 a1 = vec2(-0.95, -0.20), b1 = vec2(-0.20, -0.20), c1 = vec2(-0.57, 0.50);
    vec2 a2 = vec2(-0.35, -0.22), b2 = vec2( 0.45, -0.22), c2 = vec2( 0.05, 0.62);
    vec2 a3 = vec2( 0.20, -0.20), b3 = vec2( 1.05, -0.20), c3 = vec2( 0.62, 0.46);

    float d1 = sdTriangle(uv, a1, b1, c1);
    float d2 = sdTriangle(uv, a2, b2, c2);
    float d3 = sdTriangle(uv, a3, b3, c3);

    float p1 = smoothstep(0.004, -0.004, d1);
    float p2 = smoothstep(0.004, -0.004, d2);
    float p3 = smoothstep(0.004, -0.004, d3);

    // Crystal facets from diagonal stripe field
    float f1 = 0.5 + 0.5 * sin((uv.x * 24.0 + uv.y * 31.0) + t * (1.2 + iMid));
    float f2 = 0.5 + 0.5 * sin((uv.x * 29.0 - uv.y * 20.0) - t * (0.9 + iMid * 0.7));
    float facets = f1 * 0.6 + f2 * 0.4;

    vec3 crystal = mix(vec3(0.30, 0.72, 0.95), vec3(0.92, 0.80, 1.00), facets);
    crystal = mix(crystal, rainbow(facets + t * 0.08), 0.35 + iMid * 0.25);

    float pyramidMask = max(max(p1, p2), p3);
    col = mix(col, crystal, pyramidMask * (0.58 + iBass * 0.18));

    // Pyramid edges and apex glows
    float edge = (smoothstep(0.05, 0.0, abs(d1)) + smoothstep(0.05, 0.0, abs(d2)) + smoothstep(0.05, 0.0, abs(d3))) * 0.35;
    col += vec3(1.0, 0.95, 0.86) * edge * (0.22 + iTreble * 0.5);

    vec2 apex2 = c2;
    col += rainbow(t * 0.1 + 0.2) * exp(-length(uv - apex2) * 12.0) * (0.25 + iBeat * 1.2);

    // Floating diamonds
    float diamonds = 0.0;
    vec3 dcol = vec3(0.0);
    for (int i = 0; i < 9; i++) {
        float fi = float(i);
        float hx = hash(vec2(fi, 1.3));
        float hy = hash(vec2(fi, 5.7));
        vec2 dc = vec2((hx * 2.0 - 1.0) * ar * 0.95, -0.02 + hy * 0.95);
        dc += vec2(sin(t * (0.7 + hx) + fi) * 0.05, cos(t * (0.9 + hy) + fi * 1.3) * 0.03);
        float dd = sdDiamond(uv, dc, 0.032 + hx * 0.018);
        float dm = smoothstep(0.004, -0.004, dd);
        diamonds += dm;
        dcol += rainbow(hx + t * 0.07) * dm;

        // Sparkle near diamonds
        float sp = sparkle(uv - dc, 0.06 + hx * 0.03);
        dcol += vec3(1.0, 0.95, 0.88) * sp * (0.10 + iTreble * 0.35);
    }
    col += dcol * (0.25 + iTreble * 0.25 + iBeat * 0.2);

    // Subtle grain for painterly richness
    float grain = hash(floor((uv + vec2(t * 0.02, 0.0)) * 340.0));
    col += (grain - 0.5) * 0.03;

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

    def _init(self) -> None:
        self.parameters = {"speed": 1.0}
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
