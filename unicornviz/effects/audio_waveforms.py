"""Audio Waveforms — multi-style oscilloscope visualizer.

This effect renders audio waveform data as an animated neon instrument with
style morphing over time. It is intentionally more performative than a raw
oscilloscope: multiple drawing styles, beat-triggered accents, reactive camera
motion, and energy overlays.
"""
from __future__ import annotations

import math

import moderngl
import numpy as np

from unicornviz.effects.base import AudioData, BaseEffect

_N = 512

_VERT_BG = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_FRAG_BG = """
#version 330
uniform float iTime;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
uniform float iBeat;
uniform float iStyle;
in vec2 v_uv;
out vec4 fragColor;

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

void main() {
    vec2 uv = v_uv * 2.0 - 1.0;
    float t = iTime;

    float grid_x = smoothstep(0.015, 0.0, abs(fract((uv.x + 1.0) * 12.0) - 0.5));
    float grid_y = smoothstep(0.015, 0.0, abs(fract((uv.y + 1.0) * 8.0) - 0.5));
    float grid = (grid_x + grid_y) * (0.12 + iTreble * 0.18);

    float radial = exp(-length(uv) * (1.8 - iBass * 0.4));
    float swirl = 0.5 + 0.5 * sin(uv.x * 8.0 + uv.y * 6.0 + t * (1.5 + iMid * 1.8));

    vec3 c1 = vec3(0.03, 0.05, 0.14);
    vec3 c2 = vec3(0.10, 0.02, 0.16);
    vec3 c3 = vec3(0.02, 0.12, 0.18);

    vec3 col = mix(c1, c2, swirl);
    col = mix(col, c3, 0.4 + 0.3 * sin(t * 0.27 + iStyle * 2.4));
    col += vec3(0.08, 0.16, 0.28) * radial * (0.2 + iBass * 0.28);
    col += vec3(0.14, 0.34, 0.45) * grid;

    // Beat flash around center.
    col += vec3(0.25, 0.35, 0.80) * iBeat * exp(-length(uv) * 3.2) * 0.35;

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""

_VERT_WAVE = """
#version 330
in vec2 in_pos;
in float in_amp;
out vec2 v_pos;
out float v_amp;
void main() {
    gl_Position = vec4(in_pos, 0.0, 1.0);
    v_pos = in_pos;
    v_amp = in_amp;
}
"""

_FRAG_WAVE = """
#version 330
uniform float iTime;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
uniform float iBeat;
uniform float iStyle;
uniform float iGlow;
in vec2 v_pos;
in float v_amp;
out vec4 fragColor;

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

void main() {
    float pulse = 0.75 + 0.25 * sin(iTime * (6.0 + iMid * 3.0) + v_pos.x * 10.0);
    float sparkle = step(0.995, hash(floor((v_pos + 1.0) * vec2(40.0, 14.0) + floor(iTime * 8.0))));

    vec3 baseA = vec3(0.20, 0.95, 1.00);
    vec3 baseB = vec3(1.00, 0.35, 0.92);
    vec3 baseC = vec3(0.98, 0.90, 0.35);

    float style = iStyle;
    vec3 col = mix(baseA, baseB, smoothstep(0.8, 2.2, style));
    col = mix(col, baseC, smoothstep(2.2, 3.2, style));

    float energy = 0.55 + v_amp * (0.25 + iBass * 0.45);
    energy *= pulse;
    energy += iBeat * 0.35;

    col *= energy;
    col += vec3(1.0, 0.98, 0.85) * sparkle * (0.18 + iTreble * 0.55);

    float alpha = clamp(0.36 + iGlow * 0.24 + v_amp * 0.24, 0.24, 0.95);
    fragColor = vec4(clamp(col, 0.0, 1.0), alpha);
}
"""


class AudioWaveforms(BaseEffect):
    """Animated oscilloscope with random style changes over time."""

    NAME = 'Audio Waveforms'
    AUTHOR = 'unicorn-viz'
    TAGS = ['analyzer', 'visualizer', 'oscilloscope', 'energetic', 'intense']
    PING_PONG_FRIENDS = [
        'Audio Spectrum',
        'Audio Spectrogram',
        'Audio Tracks',
        'Audio Sine',
        'Unicorn Tears',
    ]

    def _init(self) -> None:
        self.parameters = {
            'speed': float(self.config.get('speed', 1.0)),
            'zoom': float(self.config.get('zoom', 1.0)),
            'reactivity': float(self.config.get('reactivity', 1.0)),
            'glow': float(self.config.get('glow', 1.0)),
            'style': float(self.config.get('style', self.rng.integers(0, 4))),
        }

        self._bg_prog = self._make_program(_VERT_BG, _FRAG_BG)
        self._bg_vao, self._bg_vbo = self._fullscreen_quad(self._bg_prog)

        self._wave_prog = self._make_program(_VERT_WAVE, _FRAG_WAVE)
        self._wave_data = np.zeros((_N, 3), dtype=np.float32)  # x, y, amp
        self._wave_vbo = self.ctx.buffer(reserve=self._wave_data.nbytes, dynamic=True)
        self._wave_vao = self.ctx.vertex_array(
            self._wave_prog,
            [(self._wave_vbo, '2f 1f', 'in_pos', 'in_amp')],
        )

        self._wave = np.zeros(_N, dtype=np.float32)
        self._bass = 0.0
        self._mid = 0.0
        self._treble = 0.0
        self._beat = 0.0

        self._style = int(self.parameters['style']) % 4
        self._style_timer = 0.0
        self._style_interval = float(self.rng.uniform(8.0, 14.0))

    def _choose_style(self) -> None:
        next_style = int(self.rng.integers(0, 4))
        if next_style == self._style:
            next_style = (next_style + 1) % 4
        self._style = next_style
        self.parameters['style'] = float(next_style)

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = float(audio.bass_n)
        self._mid = float(audio.mid_n)
        self._treble = float(audio.treble_n)

        if audio.beat > 0.5:
            self._beat = 1.0
            if self.rng.uniform() < 0.35:
                self._choose_style()

        self._beat = max(0.0, self._beat - dt * 3.8)

        self._style_timer += dt * max(0.1, float(self.parameters['speed']))
        if self._style_timer >= self._style_interval:
            self._style_timer = 0.0
            self._style_interval = float(self.rng.uniform(8.0, 14.0))
            self._choose_style()

        self._wave[:] = audio.waveform[:_N]

    def _build_points(self) -> tuple[np.ndarray, int, int]:
        speed = max(0.05, float(self.parameters['speed']))
        zoom = max(0.2, float(self.parameters['zoom']))
        react = max(0.1, float(self.parameters['reactivity']))

        x = np.linspace(-1.0, 1.0, _N, dtype=np.float32)
        y = self._wave.astype(np.float32)

        # Basic shaping before style-specific transforms.
        y *= (0.28 + self._bass * 0.35) * react
        y = np.tanh(y * (1.2 + self._mid * 1.1))

        style = self._style
        if style == 0:
            # Clean oscilloscope.
            y *= 0.95
        elif style == 1:
            # Ribbon/phase style.
            y += 0.08 * np.sin(x * 18.0 + self.time * 2.2 * speed)
            y *= 1.05
        elif style == 2:
            # Spiral-ish fold.
            y = y * 0.65 + 0.18 * np.sin((x + y) * 14.0 + self.time * 1.8 * speed)
        else:
            # Pulse ladder style.
            y = np.sign(y) * np.power(np.abs(y), 0.65)
            y += 0.05 * np.sin(x * 36.0 + self.time * 3.6 * speed)

        y /= zoom

        amp = np.clip(np.abs(y) * 2.6, 0.0, 1.0)

        self._wave_data[:, 0] = x
        self._wave_data[:, 1] = y
        self._wave_data[:, 2] = amp
        self._wave_vbo.write(self._wave_data.tobytes())

        # Draw main and optional mirrored strip.
        mirrored = 1 if style in (1, 3) else 0
        return self._wave_data, _N, mirrored

    def render(self) -> None:
        self._bg_prog['iTime'].value = self.time
        self._bg_prog['iBass'].value = self._bass
        self._bg_prog['iMid'].value = self._mid
        self._bg_prog['iTreble'].value = self._treble
        self._bg_prog['iBeat'].value = self._beat
        self._bg_prog['iStyle'].value = float(self._style)
        self._bg_vao.render(moderngl.TRIANGLE_STRIP)

        _, n, mirrored = self._build_points()

        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE

        self._wave_prog['iTime'].value = self.time
        self._wave_prog['iBass'].value = self._bass
        self._wave_prog['iMid'].value = self._mid
        self._wave_prog['iTreble'].value = self._treble
        self._wave_prog['iBeat'].value = self._beat
        self._wave_prog['iStyle'].value = float(self._style)
        self._wave_prog['iGlow'].value = float(self.parameters['glow'])

        self.ctx.line_width = 2.0 + self._beat * 1.6 + self._bass * 0.9
        self._wave_vao.render(moderngl.LINE_STRIP, vertices=n)

        if mirrored:
            # Mirror vertically for wider stage look.
            self._wave_data[:, 1] *= -1.0
            self._wave_vbo.write(self._wave_data.tobytes())
            self._wave_vao.render(moderngl.LINE_STRIP, vertices=n)
            self._wave_data[:, 1] *= -1.0
            self._wave_vbo.write(self._wave_data.tobytes())

        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

    def destroy(self) -> None:
        self._bg_vao.release()
        self._bg_vbo.release()
        self._bg_prog.release()
        self._wave_vao.release()
        self._wave_vbo.release()
        self._wave_prog.release()
