"""
Metaballs — GLSL SDF-based orbs that attract/repel each other.
Audio-reactive: bass grows orb radii, beat fires a new orb burst.
"""
from __future__ import annotations

import math

import moderngl
import numpy as np

from unicornviz.effects.base import BaseEffect, AudioData

_MAX_BALLS = 14
_MIN_BALLS = 7

_VERT = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv = in_vert * vec2(1.777, 1.0);  // aspect-corrected
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_FRAG = f"""
#version 330
#define N {_MAX_BALLS}
// Flat float array: ball data packed as x0,y0,r0, x1,y1,r1, ...
uniform float balls[N * 3];
uniform float iTime;
uniform float iBeat;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
uniform int iBallCount;
uniform float iZoom;
in vec2 v_uv;
out vec4 fragColor;

vec3 palette(float t) {{
    vec3 a = vec3(0.5, 0.5, 0.5);
    vec3 b = vec3(0.5, 0.5, 0.5);
    vec3 c = vec3(2.0, 1.0, 0.0);
    vec3 d = vec3(0.5, 0.20, 0.25);
    return a + b * cos(6.28318 * (c * t + d));
}}

void main() {{
    vec2 uv = v_uv / max(iZoom, 0.05);
    float field = 0.0;
    for (int i = 0; i < N; i++) {{
        if (i >= iBallCount) {{
            continue;
        }}
        float bx = balls[i * 3];
        float by = balls[i * 3 + 1];
        float br = balls[i * 3 + 2];
        vec2 d = uv - vec2(bx, by);
        field += br * br / max(dot(d, d), 0.0001);
    }}

    float surface = clamp((field - 1.0) * (1.1 + iBass * 0.7), 0.0, 1.0);
    float edge = abs(field - 1.2);
    float glow = 1.0 / (1.0 + edge * edge * (70.0 - iTreble * 20.0));

    vec3 col = palette(field * 0.15 + iTime * (0.05 + iMid * 0.05) + iMid * 0.25);
    col = mix(vec3(0.0), col, surface);
    col += vec3(0.3, 0.6, 1.0) * glow * (0.35 + iBeat * 0.75 + iTreble * 0.35);

    float spark = smoothstep(0.985, 1.0, sin(gl_FragCoord.x * 0.11 + gl_FragCoord.y * 0.07 + iTime * (2.0 + iTreble * 4.0)) * 0.5 + 0.5);
    col += vec3(0.8, 0.9, 1.0) * spark * glow * (0.04 + iTreble * 0.10);

    col *= 0.9 + 0.1 * sin(gl_FragCoord.y * 3.14159 * 2.0);

    fragColor = vec4(col, 1.0);
}}
"""


class Metaballs(BaseEffect):
    NAME = "Metaballs"
    AUTHOR = "unicorn-viz"
    TAGS = ["classic", "audio"]
    PING_PONG_FRIENDS = ['Plasma', 'Kaleidoscope', 'Fractal Zoom']

    def _init(self) -> None:
        self.parameters = {
            "speed": float(self.config.get("speed", 1.0)),
            "zoom": float(self.config.get("zoom", self.rng.uniform(0.75, 1.35))),
        }
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()
        self._ball_count = int(self.rng.integers(_MIN_BALLS, _MAX_BALLS + 1))

        # Startup-randomized orbital state.
        self._phases = self.rng.uniform(0.0, math.tau, (_MAX_BALLS, 4))
        self._freqs = self.rng.uniform(0.25, 1.25, (_MAX_BALLS, 4))
        self._amps = self.rng.uniform(0.35, 1.25, (_MAX_BALLS, 2))
        self._radii = self.rng.uniform(0.10, 0.24, _MAX_BALLS)
        self._ball_data = np.zeros(_MAX_BALLS * 3, dtype=np.float32)

        self._bass = 0.0
        self._mid = 0.0
        self._treble = 0.0
        self._beat = 0.0
        self._retarget_timer = 0.0
        self._retarget_interval = self._next_retarget_interval()

    def _is_raver_mode(self) -> bool:
        """Return True when Auto VJ currently reports the raver profile."""
        return bool(getattr(self, '_raver_mode_active', False))

    def _next_retarget_interval(self) -> float:
        """Sample next retarget interval with raver-mode pacing boost."""
        if self._is_raver_mode():
            # ~75% toward old (4..8s) from current calm (7..13s): 4.75..9.25s
            return float(self.rng.uniform(4.75, 9.25))
        return float(self.rng.uniform(7.0, 13.0))

    def _retarget_motion(self) -> None:
        """Re-seed orbital profiles and sometimes vary active ball count."""
        raver = self._is_raver_mode()
        change_chance = 0.3875 if raver else 0.20
        if float(self.rng.uniform(0.0, 1.0)) < change_chance:
            if raver and float(self.rng.uniform(0.0, 1.0)) < 0.35:
                self._ball_count = int(self.rng.integers(_MIN_BALLS, _MAX_BALLS + 1))
            else:
                delta_span = 4 if raver else 2
                delta = int(self.rng.integers(-delta_span, delta_span + 1))
                self._ball_count = int(np.clip(self._ball_count + delta, _MIN_BALLS, _MAX_BALLS))
        self._phases = self.rng.uniform(0.0, math.tau, (_MAX_BALLS, 4))
        self._freqs = self.rng.uniform(0.25, 1.35, (_MAX_BALLS, 4))
        self._amps = self.rng.uniform(0.35, 1.28, (_MAX_BALLS, 2))
        self._radii = self.rng.uniform(0.10, 0.24, _MAX_BALLS)

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass_n
        self._mid = audio.mid_n
        self._treble = audio.treble_n
        if audio.beat > 0.5:
            self._beat = 1.0
            # Beat can occasionally jump to a fresh cluster personality.
            beat_retarget_chance = 0.30 if self._is_raver_mode() else 0.15
            if float(self.rng.uniform(0.0, 1.0)) < beat_retarget_chance:
                self._retarget_motion()
        self._beat = max(0.0, self._beat - dt * 3.0)

        self._retarget_timer += dt
        if self._retarget_timer >= self._retarget_interval:
            self._retarget_timer = 0.0
            self._retarget_interval = self._next_retarget_interval()
            self._retarget_motion()

    def render(self) -> None:
        t = self.time * self.parameters["speed"]
        for i in range(_MAX_BALLS):
            base = i * 3
            if i < self._ball_count:
                x = (
                    math.sin(t * self._freqs[i, 0] + self._phases[i, 0]) * self._amps[i, 0]
                    + math.sin(t * self._freqs[i, 1] + self._phases[i, 1]) * 0.35
                )
                y = (
                    math.cos(t * self._freqs[i, 2] + self._phases[i, 2]) * (self._amps[i, 1] * 0.7)
                    + math.sin(t * self._freqs[i, 3] + self._phases[i, 3]) * 0.24
                )
                x *= 1.05
                y *= 0.88
                r = self._radii[i] * (1.0 + self._bass * 0.75 + self._mid * 0.25)
                self._ball_data[base] = x
                self._ball_data[base + 1] = y
                self._ball_data[base + 2] = r
            else:
                self._ball_data[base:base + 3] = 0.0

        self._prog["iTime"].value = self.time
        self._prog["iBeat"].value = self._beat
        self._prog["iBass"].value = self._bass
        self._prog["iMid"].value = self._mid
        self._prog["iTreble"].value = self._treble
        self._prog["iBallCount"].value = int(self._ball_count)
        self._prog["iZoom"].value = float(self.parameters["zoom"])
        # Set entire float array in one call (moderngl exposes 'balls' not 'balls[0]')
        self._prog["balls"].value = tuple(self._ball_data)

        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
