"""
Copper Bars — Amiga-style horizontal raster/color bars.
Each bar is a gradient band whose position oscillates on a sine.
Audio-reactive: bass drives bar spread, beat flashes palette.
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
    v_uv = in_vert * 0.5 + 0.5;   // 0..1
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_FRAG = """
#version 330
uniform float iTime;
uniform float iBass;
uniform float iBeat;
uniform float iSpeed;
uniform int   iModeA;
uniform int   iModeB;
uniform float iMorph;
uniform float iAngleA;
uniform float iAngleB;
uniform float iZoomA;
uniform float iZoomB;
in vec2 v_uv;
out vec4 fragColor;

#define NUM_BARS 6

vec3 bar_color(int idx, float phase) {
    // Six classic Amiga colour schemes
    vec3 palette[6];
    palette[0] = vec3(1.0, 0.0, 0.2);   // red
    palette[1] = vec3(0.0, 0.5, 1.0);   // cyan
    palette[2] = vec3(1.0, 0.7, 0.0);   // gold
    palette[3] = vec3(0.2, 1.0, 0.3);   // green
    palette[4] = vec3(0.8, 0.0, 1.0);   // purple
    palette[5] = vec3(0.0, 1.0, 1.0);   // aqua
    return palette[idx] * (0.5 + 0.5 * cos(phase));
}

vec2 transform_uv(vec2 uv, float angle, float zoom) {
    vec2 p = uv - vec2(0.5);
    float c = cos(angle);
    float s = sin(angle);
    mat2 rot = mat2(c, -s, s, c);
    p = rot * p / max(zoom, 0.01);
    return p + vec2(0.5);
}

float axis_for_mode(int mode, vec2 uv) {
    if (mode == 0) {
        // Horizontal bars
        return uv.y;
    }
    if (mode == 1) {
        // Vertical bars
        return uv.x;
    }
    // Diagonal bars
    return clamp((uv.x + uv.y) * 0.5, 0.0, 1.0);
}

vec3 bars_for_axis(float axis, vec2 uv, float t, float spread, float beat) {
    vec3 col = vec3(0.02);
    for (int i = 0; i < NUM_BARS; i++) {
        float fi = float(i) / float(NUM_BARS);
        float center = 0.5
            + sin(t * (0.7 + fi * 0.4) + fi * 2.5) * 0.35
            + sin(t * 0.3 + fi) * 0.1;

        float dist = abs(axis - center);
        if (dist < spread) {
            float blend = 1.0 - dist / spread;
            blend = blend * blend * (3.0 - 2.0 * blend);
            vec3 bc = bar_color(i, t * 2.0 + fi * 3.14);
            bc *= 1.0 + beat * 0.5;
            col = mix(col, bc, blend);
        }
    }

    float scan = 0.85 + 0.15 * sin(uv.y * 1080.0 * 3.14159);
    col *= scan;
    return col;
}

void main() {
    float t = iTime * iSpeed;
    float spread = 0.12 + iBass * 0.08;

    vec2 uv_a = transform_uv(v_uv, iAngleA, iZoomA);
    vec2 uv_b = transform_uv(v_uv, iAngleB, iZoomB);
    float axis_a = axis_for_mode(iModeA, uv_a);
    float axis_b = axis_for_mode(iModeB, uv_b);

    vec3 col_a = bars_for_axis(axis_a, uv_a, t, spread, iBeat);
    vec3 col_b = bars_for_axis(axis_b, uv_b, t, spread, iBeat);
    vec3 col = mix(col_a, col_b, clamp(iMorph, 0.0, 1.0));

    fragColor = vec4(col, 1.0);
}
"""


class CopperBars(BaseEffect):
    NAME = "Copper Bars"
    AUTHOR = "unicorn-viz"
    TAGS = ["classic", "amiga", "audio"]
    PING_PONG_FRIENDS = [
        'Sine Scroller 3.1',
        'Plasma',
        'Vector',
        'Escher',
        'Fireworks',
        'Hexy Stars',
        'Metaballs',
        'Particle Storm',
        'Prism Lattice',
        'Psychedelic',
        'Starfield',
        'Tunnel',
        'Unicorn Tears',
        'Van Gogh',
        'Wavey Gravy',
        'Tron Grid',
        'Kaleidoscope',
        'Breakout',
    ]

    def _init(self) -> None:
        self.parameters = {
            "speed": float(self.config.get("speed", 1.0)),
            "mode_interval": 15.0,
        }
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()
        self._bass = 0.0
        self._beat = 0.0
        self._mode_a = 0
        self._mode_b = 0
        self._mode_timer = 0.0
        self._mode_transition = 1.0
        self._mode_transition_duration = 1.4
        self._angle_a = 0.0
        self._angle_b = 0.0
        self._zoom_a = 1.0
        self._zoom_b = 1.0

    def _mode_base_angle(self, mode: int) -> float:
        if mode == 0:
            return 0.0
        if mode == 1:
            return 1.57079632679
        return 0.78539816339

    def _pick_next_mode(self, current: int) -> int:
        choices = [0, 1, 2]
        choices.remove(current)
        return int(self.rng.choice(choices))

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass
        self._beat = max(0.0, self._beat - dt * 4.0)
        if audio.beat > 0.5:
            self._beat = 1.0

        self._mode_timer += dt
        interval = max(2.0, float(self.parameters.get("mode_interval", 15.0)))
        if self._mode_timer >= interval:
            self._mode_timer = 0.0
            self._mode_a = self._mode_b
            self._angle_a = self._angle_b
            self._zoom_a = self._zoom_b

            self._mode_b = self._pick_next_mode(self._mode_a)
            base = self._mode_base_angle(self._mode_b)
            self._angle_b = base + float(self.rng.uniform(-0.28, 0.28))
            self._zoom_b = float(self.rng.uniform(0.86, 1.24))
            self._mode_transition = 0.0

        if self._mode_transition < 1.0:
            self._mode_transition = min(
                1.0,
                self._mode_transition + dt / self._mode_transition_duration,
            )

    def render(self) -> None:
        self._prog["iTime"].value = self.time
        self._prog["iBass"].value = self._bass
        self._prog["iBeat"].value = self._beat
        self._prog["iSpeed"].value = self.parameters["speed"]
        self._prog["iModeA"].value = int(self._mode_a)
        self._prog["iModeB"].value = int(self._mode_b)
        self._prog["iMorph"].value = float(self._mode_transition)
        self._prog["iAngleA"].value = float(self._angle_a)
        self._prog["iAngleB"].value = float(self._angle_b)
        self._prog["iZoomA"].value = float(self._zoom_a)
        self._prog["iZoomB"].value = float(self._zoom_b)
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
