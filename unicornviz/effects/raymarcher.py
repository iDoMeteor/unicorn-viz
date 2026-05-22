"""
Raymarcher — SDF scene with sphere-tracing.
Morphing geometric shapes, fog, reflections, audio-reactive deformations.
Beat pulses a shockwave; bass blooms the SDF geometry.
"""
from __future__ import annotations

import moderngl

from unicornviz.effects.base import BaseEffect, AudioData

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

#define MAX_STEPS 96
#define MAX_DIST  26.0
#define SURF_DIST 0.001

float sdSphere(vec3 p, float r) { return length(p) - r; }

float sdBox(vec3 p, vec3 b) {
    vec3 q = abs(p) - b;
    return length(max(q, 0.0)) + min(max(q.x, max(q.y, q.z)), 0.0);
}

float sdTorus(vec3 p, vec2 t) {
    vec2 q = vec2(length(p.xz) - t.x, p.y);
    return length(q) - t.y;
}

float smin(float a, float b, float k) {
    float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0);
    return mix(b, a, h) - k * h * (1.0 - h);
}

mat2 rot2(float a) {
    float c = cos(a), s = sin(a);
    return mat2(c, -s, s, c);
}

float hash(vec2 p) {
    p = fract(p * vec2(127.1, 311.7));
    p += dot(p, p + 19.19);
    return fract(p.x * p.y);
}

float matNoise(vec3 p) {
    float n = 0.0;
    n += sin(p.x * 7.1 + p.y * 5.3 + p.z * 3.7) * 0.50;
    n += sin(p.x * 13.7 - p.y * 9.1 + p.z * 6.3) * 0.25;
    n += sin(p.x * 21.2 + p.y * 17.9 - p.z * 11.3) * 0.125;
    return n * 0.5 + 0.5;
}

vec3 palette(float t);

vec3 envColor(vec3 rd, float t) {
    float h = 0.5 + 0.5 * rd.y;
    float bands = 0.5 + 0.5 * sin(rd.x * 12.0 + rd.z * 10.0 + t * 0.8);
    vec3 top = vec3(0.03, 0.02, 0.08);
    vec3 bot = vec3(0.00, 0.00, 0.03);
    vec3 sky = mix(bot, top, h);
    sky += palette(bands + t * 0.03) * 0.08;
    float stars = smoothstep(0.995, 1.0, hash(floor((rd.xz + 2.0) * 140.0)));
    sky += vec3(0.7, 0.6, 1.0) * stars * 0.55;
    return sky;
}

float scene(vec3 p) {
    float t = iTime * iSpeed;
    float bass = iBass * 0.6;

    // Global group motion so shard cluster drifts as a unit.
    vec3 group = vec3(
        sin(t * 0.33) * 0.45,
        sin(t * 0.27 + 1.3) * 0.30,
        cos(t * 0.29) * 0.45
    );

    vec3 pc = p;
    pc -= group * 0.20;
    pc.xz *= rot2(t * 0.35 + p.y * 0.08);
    pc.xy *= rot2(t * 0.22);

    // Crystal core
    float crystal = sdBox(pc, vec3(0.52 + bass * 0.15, 0.58, 0.42));
    crystal = max(crystal, -sdSphere(pc, 0.86));

    // Orbital ring
    vec3 pr = p;
    pr -= group * 0.15;
    pr.y += sin(t + p.x * 0.6) * 0.06;
    pr.xz *= rot2(t * 0.7);
    float ring = sdTorus(pr, vec2(1.25 + bass * 0.2, 0.11 + iTreble * 0.08));

    // Orbiting shards
    float shards = 1e9;
    for (int i = 0; i < 6; i++) {
        float fi = float(i) / 6.0 * 6.28318;
        vec3 c = vec3(
            cos(fi + t * 0.6) * 1.7,
            sin(fi * 2.0 + t * 0.9) * 0.45,
            sin(fi + t * 0.6) * 1.7
        ) + group * 0.55;
        vec3 ps = p - c;
        ps.xy *= rot2(t * 0.9 + fi);
        ps.yz *= rot2(t * 0.6 + fi * 0.7);
        float shard = sdBox(ps, vec3(0.18, 0.03, 0.07 + iMid * 0.04));
        shards = min(shards, shard);
    }

    // Shock pulse from beat
    float shock = iBeat * exp(-length(p) * 1.1) * 0.22;

    float d = smin(crystal, ring, 0.28);
    d = smin(d, shards, 0.22);
    d += shock;

    // Slightly warped floor for depth cues
    float floor_d = p.y + 2.15 + 0.08 * sin(p.x * 3.6 + t * 0.7) * sin(p.z * 3.2 + t * 0.5);
    d = smin(d, floor_d, 0.35);

    return d;
}

vec3 normal(vec3 p) {
    vec2 e = vec2(0.0012, 0.0);
    return normalize(vec3(
        scene(p + e.xyy) - scene(p - e.xyy),
        scene(p + e.yxy) - scene(p - e.yxy),
        scene(p + e.yyx) - scene(p - e.yyx)
    ));
}

float raymarch(vec3 ro, vec3 rd) {
    float d = 0.0;
    for (int i = 0; i < MAX_STEPS; i++) {
        vec3 p = ro + rd * d;
        float ds = scene(p);
        d += ds;
        if (ds < SURF_DIST || d > MAX_DIST) break;
    }
    return d;
}

vec3 palette(float t) {
    vec3 a = vec3(0.5, 0.5, 0.52);
    vec3 b = vec3(0.5, 0.45, 0.48);
    vec3 c = vec3(1.0, 0.9, 0.65);
    vec3 d = vec3(0.06, 0.18, 0.38);
    return a + b * cos(6.28318 * (c * t + d));
}

float sparkleField(vec3 p, float t) {
    vec2 cell = floor(p.xz * 6.0 + p.y * 0.7);
    float h = hash(cell);
    if (h < 0.94) return 0.0;
    float tw = 0.5 + 0.5 * sin(t * (2.2 + h * 2.5) + h * 6.28318);
    float d = length(fract(p.xz * 6.0) - 0.5);
    return smoothstep(0.24, 0.01, d) * tw;
}

void main() {
    vec2 uv = v_uv * vec2(iResolution.x / iResolution.y, 1.0);
    float t = iTime * iSpeed;

    // Cinematic orbit camera
    vec3 ro = vec3(sin(t * 0.24) * 4.8, 1.35 + sin(t * 0.13) * 0.45, cos(t * 0.24) * 4.8);
    vec3 ta = vec3(0.0, 0.15, 0.0);
    vec3 fwd = normalize(ta - ro);
    vec3 right = normalize(cross(vec3(0.0, 1.0, 0.0), fwd));
    vec3 up = cross(fwd, right);
    vec3 rd = normalize(fwd + uv.x * right + uv.y * up);

    float d = raymarch(ro, rd);
    vec3 col = vec3(0.0);

    if (d < MAX_DIST) {
        vec3 p = ro + rd * d;
        vec3 n = normal(p);

        vec3 l1 = normalize(vec3(1.8, 2.4, 0.8));
        vec3 l2 = normalize(vec3(-1.4, 1.2, -1.8));

        float diff1 = max(dot(n, l1), 0.0);
        float diff2 = max(dot(n, l2), 0.0) * 0.55;
        float spec = pow(max(dot(reflect(-l1, n), -rd), 0.0), 52.0);

        float ao = 1.0 - clamp(scene(p + n * 0.14) / 0.14, 0.0, 1.0) * 0.55;
        float fres = pow(1.0 - max(dot(n, -rd), 0.0), 3.0);

        float tone = d / MAX_DIST + iTreble * 0.18 + iTime * 0.06 + iMid * 0.15;
        float m = matNoise(p * 1.8 + vec3(iTime * 0.12));
        vec3 baseA = palette(tone);
        vec3 baseB = palette(tone + 0.24 + m * 0.2);
        vec3 base = mix(baseA, baseB, 0.45 + m * 0.35);

        col = base * (0.16 + diff1 * 0.95 + diff2);
        col += vec3(1.0, 0.95, 0.9) * spec * (0.45 + iBass * 0.70);

        // Fresnel-tinted reflection from procedural environment.
        vec3 rdir = reflect(rd, n);
        vec3 env = envColor(rdir, t);
        col += env * fres * (0.55 + iTreble * 0.50);

        float spark = sparkleField(p, t + m * 2.0);
        col += vec3(0.95, 0.85, 1.0) * spark * (0.4 + iTreble * 0.9);
        col *= ao;

        // Volumetric-ish glow/fog
        float fog = exp(-d * 0.07);
        vec3 fogCol = vec3(0.02, 0.01, 0.05) + palette(iTime * 0.03 + m * 0.2) * 0.10;
        col = mix(fogCol, col, fog);
    } else {
        col = envColor(normalize(vec3(uv, 1.5)), t);
    }

    col += iBeat * 0.1 * vec3(0.65, 0.4, 1.0);
    col *= 1.0 - 0.22 * dot(v_uv, v_uv);

    col = col / (col + 0.75);
    col = pow(col, vec3(0.4545));

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""


class Raymarcher(BaseEffect):
    NAME = "Raymarcher"
    AUTHOR = "unicorn-viz"
    TAGS = ["futuristic", "audio", "3d"]
    PING_PONG_FRIENDS = ['Crystal Pyramids', 'Particle Storm', '3D Cube']

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
        self._bass = audio.bass_n
        self._mid = audio.mid_n
        self._treble = audio.treble_n
        if audio.beat > 0.5:
            self._beat = 1.0
        self._beat = max(0.0, self._beat - dt * 4.0)

    def render(self) -> None:
        self._prog["iTime"].value = self.time
        self._prog["iResolution"].value = (float(self.width), float(self.height))
        self._prog["iBass"].value = self._bass
        self._prog["iMid"].value = self._mid
        self._prog["iTreble"].value = self._treble
        self._prog["iBeat"].value = self._beat
        self._prog["iSpeed"].value = self.parameters["speed"]
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
