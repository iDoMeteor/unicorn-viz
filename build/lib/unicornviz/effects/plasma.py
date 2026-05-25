"""
Plasma — classic sin/cos color-field shader.
Audio-reactive: bass drives warp amplitude, treble drives color speed.
"""
from __future__ import annotations

import numpy as np
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
uniform float iTreble;
uniform float iSpeed;
uniform float iPalette;   // 0..1 palette index shift
in  vec2 v_uv;
out vec4 fragColor;

vec3 palette(float t) {
    // Classic demoscene 4-color smooth palette
    vec3 a = vec3(0.5, 0.5, 0.5);
    vec3 b = vec3(0.5, 0.5, 0.5);
    vec3 c = vec3(1.0, 1.0, 1.0);
    vec3 d = vec3(0.00, 0.33, 0.67);
    return a + b * cos(6.28318 * (c * t + d + iPalette));
}

void main() {
    vec2 uv = v_uv * vec2(iResolution.x / iResolution.y, 1.0);
    float t = iTime * iSpeed;
    float warp = 1.0 + iBass * 2.0;

    float v1 = sin(uv.x * 3.0 * warp + t);
    float v2 = sin(uv.y * 3.0 * warp + t * 0.7);
    float v3 = sin((uv.x + uv.y) * 2.5 * warp + t * 1.3);
    float v4 = sin(sqrt(uv.x*uv.x + uv.y*uv.y) * 5.0 * warp - t * 0.9);
    float v5 = sin(uv.x * 4.0 + sin(uv.y * 2.0 + t) + t * 0.5);

    float val = (v1 + v2 + v3 + v4 + v5) * 0.2;  // normalise to ~[-1,1]
    val += iTreble * 0.3;

    fragColor = vec4(palette((val + 1.0) * 0.5), 1.0);
}
"""


class Plasma(BaseEffect):
    NAME = "Plasma"
    AUTHOR = "unicorn-viz"
    TAGS = ["classic", "audio"]
    PING_PONG_FRIENDS = ['Fire', 'Kaleidoscope']

    def _init(self) -> None:
        self.parameters = {
            "speed": float(self.config.get("speed", 1.0)),
            "palette": float(self.rng.uniform(0.0, 1.0)),
        }
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()

    def render(self) -> None:
        self._prog["iTime"].value = self.time
        self._prog["iResolution"].value = (float(self.width), float(self.height))
        self._prog["iSpeed"].value = self.parameters["speed"]
        self._prog["iPalette"].value = self.parameters["palette"]
        self._prog["iBass"].value = self._bass
        self._prog["iTreble"].value = self._treble
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass_n
        self._treble = audio.treble_n
        # Slowly drift palette
        self.parameters["palette"] = (
            self.parameters["palette"] + dt * 0.05 * self.parameters["speed"]
        ) % 1.0

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
