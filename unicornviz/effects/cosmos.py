"""
Cosmos — nebula clouds with starfield and warp streaks.

Audio reactivity:
- bass: warp streak strength and star brightness
- treble: sparkle detail
- beat: short white flash pulse
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
uniform float iTreble;
uniform float iBeat;
uniform float iSpeed;

in vec2 v_uv;
out vec4 fragColor;

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(41.3, 289.1))) * 74243.91);
}

float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    float a = hash(i + vec2(0.0, 0.0));
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

float fbm(vec2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 6; i++) {
        v += a * noise(p);
        p = p * 2.02 + vec2(0.37, -0.23);
        a *= 0.53;
    }
    return v;
}

void main() {
    vec2 uv = v_uv * 2.0 - 1.0;
    uv.x *= iResolution.x / max(iResolution.y, 1.0);

    float t = iTime * (0.2 + 0.8 * iSpeed);

    float n1 = fbm(uv * 1.4 + vec2(t * 0.08, -t * 0.03));
    float n2 = fbm(uv * 2.3 - vec2(t * 0.06, t * 0.05));
    float neb = smoothstep(0.35, 0.95, n1 * 0.7 + n2 * 0.5);

    vec3 nebA = vec3(0.05, 0.10, 0.35);
    vec3 nebB = vec3(0.35, 0.08, 0.45);
    vec3 nebC = vec3(0.10, 0.45, 0.70);

    vec3 col = mix(nebA, nebB, n1);
    col = mix(col, nebC, n2 * 0.8);
    col *= 0.25 + neb * 1.1;

    // Stars
    vec2 st = (uv + vec2(t * 0.2, 0.0)) * 120.0;
    vec2 cell = floor(st);
    vec2 f = fract(st) - 0.5;
    float starSeed = hash(cell);
    float star = 0.0;
    if (starSeed > 0.992) {
        float d = length(f);
        star = smoothstep(0.08, 0.0, d);
    }

    // Warp streaks around center.
    float r = length(uv);
    float ang = atan(uv.y, uv.x);
    float warp = abs(sin(ang * 70.0 + t * 9.0));
    warp = pow(1.0 - warp, 12.0) * smoothstep(1.2, 0.1, r);
    warp *= iBass * 1.4;

    float sparkle = star * (0.8 + iTreble * 1.1);
    col += vec3(1.0, 0.95, 0.9) * sparkle;
    col += vec3(0.7, 0.9, 1.0) * warp;

    col += vec3(1.0) * iBeat * 0.18;

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""


class Cosmos(BaseEffect):
    NAME = "Cosmos"
    AUTHOR = "unicorn-viz"
    TAGS = ["space", "audio", "shader"]
    SPEED_TIME_BIAS = 0.2
    SPEED_TIME_SCALE = 0.8
    PING_PONG_FRIENDS = ['Starfield', 'Alien Invasion']

    def _init(self) -> None:
        self.parameters = {"speed": float(self.config.get("speed", 1.0))}
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()
        self._bass = 0.0
        self._treble = 0.0
        self._beat = 0.0

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass_n
        self._treble = audio.treble_n
        if audio.beat > 0.5:
            self._beat = 1.0
        self._beat = max(0.0, self._beat - dt * 3.8)

    def render(self) -> None:
        self._prog["iTime"].value = self.time
        self._prog["iResolution"].value = (float(self.width), float(self.height))
        self._prog["iBass"].value = self._bass
        self._prog["iTreble"].value = self._treble
        self._prog["iBeat"].value = self._beat
        self._prog["iSpeed"].value = float(self.parameters["speed"])
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
