"""
Van Gogh — painterly swirling night-sky brushstroke field.

Audio reactivity:
- bass: swirl radius and brushstroke thickness
- mid: chroma modulation
- beat: bright starburst accent
"""
from __future__ import annotations

import moderngl

from unicornviz.effects.base import BaseEffect, AudioData

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
uniform float iSpeed;
uniform float iFlow;
uniform float iDrift;

in vec2 v_uv;
out vec4 fragColor;

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

float fbm(vec2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 5; i++) {
        v += a * noise(p);
        p = p * 2.0 + vec2(0.13, -0.27);
        a *= 0.5;
    }
    return v;
}

mat2 rot(float a) {
    float c = cos(a), s = sin(a);
    return mat2(c, -s, s, c);
}

void main() {
    vec2 uv = v_uv * 2.0 - 1.0;
    uv.x *= iResolution.x / max(iResolution.y, 1.0);

    float t = iTime * (0.3 + 0.8 * iSpeed);

    // Multi-center swirl field with animated centers and evolving drift.
    vec2 c1 = vec2(-0.45, 0.25) + vec2(sin(t * 0.37), cos(t * 0.29)) * 0.18 * iFlow;
    vec2 c2 = vec2( 0.30, 0.10) + vec2(cos(t * 0.31), sin(t * 0.41)) * 0.16 * iFlow;
    vec2 c3 = vec2( 0.05,-0.28) + vec2(sin(t * 0.52), cos(t * 0.47)) * 0.12 * iFlow;

    vec2 p = uv;
    p += vec2(cos(t * 0.13), sin(t * 0.17)) * iDrift;
    float d1 = length(p - c1);
    float d2 = length(p - c2);
    float d3 = length(p - c3);
    p = rot(0.8 / (0.2 + d1 + 0.2 * iBass)) * p;
    p = rot(-0.6 / (0.22 + d2 + 0.15 * iBass)) * p;
    p = rot(0.55 / (0.25 + d3 + 0.18 * iBass)) * p;

    float n = fbm(p * (2.2 + iFlow * 0.9) + vec2(t * 0.3, -t * 0.2));
    float brush = abs(sin((n + p.x * 0.7 + p.y * 0.9 + sin(t * 0.4) * iFlow) * 28.0));
    brush = pow(1.0 - brush, 3.5 - iBass * 1.2);

    vec3 deepBlue = vec3(0.03, 0.07, 0.30);
    vec3 cobalt   = vec3(0.09, 0.26, 0.75);
    vec3 yellow   = vec3(1.00, 0.84, 0.20);

    vec3 col = mix(deepBlue, cobalt, n);
    col += yellow * brush * (0.35 + 0.6 * iMid);

    // Stars + dynamic streaklets
    float stars = step(0.996, hash(floor((uv + vec2(t * (0.2 + iFlow * 0.2), 0.0)) * 120.0)));
    float streak = smoothstep(0.995, 1.0, hash(floor((uv + vec2(-t * 0.12, t * 0.07)) * 170.0)));
    col += vec3(1.0, 0.95, 0.75) * stars * (0.4 + iBeat * 0.7 + iTreble * 0.4);
    col += vec3(0.8, 0.9, 1.0) * streak * (0.05 + iTreble * 0.16);

    col += vec3(1.0, 0.9, 0.7) * iBeat * 0.08;

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""


class VanGogh(BaseEffect):
    NAME = "Van Gogh"
    AUTHOR = "unicorn-viz"
    TAGS = ["art", "audio", "shader"]
    SPEED_TIME_BIAS = 0.3
    SPEED_TIME_SCALE = 0.8
    PING_PONG_FRIENDS = ['Dali', 'Escher', 'Psychedelic']

    def _init(self) -> None:
        self.scale_when_framed = bool(self.config.get('scale_when_framed', True))
        self.parameters = {"speed": float(self.config.get("speed", 1.0))}
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()
        self._bass = 0.0
        self._mid = 0.0
        self._treble = 0.0
        self._beat = 0.0
        self._flow = float(self.rng.uniform(0.0, 1.0))
        self._drift = float(self.rng.uniform(0.0, 0.4))
        self._target_flow = self._flow
        self._target_drift = self._drift
        self._retarget_timer = 0.0
        self._retarget_interval = float(self.rng.uniform(4.0, 8.0))

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass_n
        self._mid = audio.mid_n
        self._treble = audio.treble_n
        if audio.beat > 0.5:
            self._beat = 1.0
        self._beat = max(0.0, self._beat - dt * 3.2)

        self._retarget_timer += dt
        if self._retarget_timer >= self._retarget_interval:
            self._retarget_timer = 0.0
            self._retarget_interval = float(self.rng.uniform(4.0, 8.0))
            self._target_flow = float(self.rng.uniform(0.0, 1.0))
            self._target_drift = float(self.rng.uniform(0.0, 0.55))

        blend = min(1.0, dt * 0.55)
        self._flow += (self._target_flow - self._flow) * blend
        self._drift += (self._target_drift - self._drift) * blend

    def render(self) -> None:
        self._prog["iTime"].value = self.time
        self._prog["iResolution"].value = (float(self.width), float(self.height))
        self._prog["iBass"].value = self._bass
        self._prog["iMid"].value = self._mid
        self._prog["iTreble"].value = self._treble
        self._prog["iBeat"].value = self._beat
        self._prog["iSpeed"].value = float(self.parameters["speed"])
        self._prog["iFlow"].value = self._flow
        self._prog["iDrift"].value = self._drift
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
