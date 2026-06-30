"""Audio Spectrogram — reactive scrolling frequency history.

This effect renders a time-scrolling spectrogram texture and layers it with
music-reactive sweeps, pulses, and color-energy shaping so it feels like a live
stage instrument instead of a raw debug plot.
"""
from __future__ import annotations

import math

import moderngl
import numpy as np

from unicornviz.effects.base import AudioData, BaseEffect

_W = 320  # time axis (columns)
_H = 256  # frequency axis (rows)
_F_BINS = 512

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
uniform sampler2D iSpecTex;
uniform vec2  iResolution;
uniform float iTime;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
uniform float iBeat;
uniform float iSpeed;
uniform float iZoom;
uniform float iReactivity;
uniform float iStyle;
in vec2 v_uv;
out vec4 fragColor;

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

vec3 palette(float t, float style) {
    vec3 a = vec3(0.5);
    vec3 b = vec3(0.5);
    vec3 c = vec3(1.0);
    vec3 d0 = vec3(0.02, 0.19, 0.39);
    vec3 d1 = vec3(0.08, 0.33, 0.66);
    vec3 d2 = vec3(0.20, 0.05, 0.52);
    vec3 d = mix(d0, d1, smoothstep(0.5, 1.5, style));
    d = mix(d, d2, smoothstep(1.5, 2.5, style));
    return a + b * cos(6.28318 * (c * t + d));
}

void main() {
    float speed = max(iSpeed, 0.05);
    float zoom = max(iZoom, 0.1);
    float react = max(iReactivity, 0.1);

    vec2 uv = (v_uv - 0.5) / zoom + 0.5;

    // Gentle drift/warp makes the history feel alive.
    uv.x += 0.012 * sin(iTime * 0.6 * speed + uv.y * 5.0 + iMid * 3.0);
    uv.y += 0.008 * cos(iTime * 0.5 * speed + uv.x * 4.0 + iBass * 2.0);

    float s = texture(iSpecTex, clamp(uv, 0.0, 1.0)).r;

    // Frequency emphasis and dynamic range shaping.
    float low_weight = smoothstep(0.0, 0.30, uv.y);
    float hi_weight = smoothstep(0.30, 1.0, uv.y);
    float energy = s * (1.0 + low_weight * iBass * 0.65 + hi_weight * iTreble * 0.45);
    energy = pow(clamp(energy * (0.95 + react * 0.45), 0.0, 1.0), 0.82);

    // Color map.
    vec3 col = palette(energy * 0.75 + uv.y * 0.33 + iTime * 0.04 * speed, iStyle);
    col *= energy * (0.85 + iMid * 0.35);

    // Beat-driven horizontal sweep lines.
    float sweep = smoothstep(0.02, 0.0, abs(fract(uv.y * 14.0 + iTime * (0.8 + iBeat * 2.5)) - 0.5));
    col += vec3(0.28, 0.85, 1.0) * sweep * iBeat * 0.35;

    // Bass ray fan from bottom center.
    vec2 p = uv * 2.0 - 1.0;
    float a = atan(p.y + 1.0, p.x);
    float fan = pow(max(0.0, cos(a * (8.0 + iMid * 8.0) + iTime * speed)), 14.0);
    fan *= exp(-abs(p.y + 1.0) * 1.2);
    col += vec3(0.35, 0.55, 1.0) * fan * iBass * 0.28 * react;

    // Spark accents in high-energy bins.
    float spark = step(0.996, hash(floor(uv * vec2(240.0, 180.0)) + floor(iTime * 8.0)));
    col += vec3(1.0, 0.95, 0.78) * spark * energy * (0.15 + iTreble * 0.55);

    // Subtle vignette for stage focus.
    float vig = 1.0 - dot(v_uv - 0.5, v_uv - 0.5) * 0.9;
    col *= vig;

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""


def _build_log_lut(h: int, fft_bins: int) -> np.ndarray:
    """Map vertical texels to log-spaced FFT bins for perceptual balance."""
    fmin = 25.0
    fmax = 18000.0
    freqs = np.logspace(np.log10(fmin), np.log10(fmax), h)
    hz_per_bin = 48000.0 / (fft_bins * 2.0)
    bins = np.clip((freqs / hz_per_bin).astype(np.int32), 0, fft_bins - 1)
    return bins


class AudioSpectrogram(BaseEffect):
    """Scrolling spectrogram with audio-reactive stage effects."""

    NAME = 'Audio Spectrogram'
    AUTHOR = 'unicorn-viz'
    TAGS = ['audio', 'visualizer', 'spectrogram']
    PING_PONG_FRIENDS = [
        'Audio Spectrum',
        'Audio Tracks',
        'Audio Waveforms',
        'Audio Sine',
        'Unicorn Tears',
    ]

    def _init(self) -> None:
        self.parameters = {
            'speed': float(self.config.get('speed', 1.0)),
            'zoom': float(self.config.get('zoom', 1.0)),
            'reactivity': float(self.config.get('reactivity', 1.0)),
            'style': float(self.config.get('style', self.rng.integers(0, 3))),
        }

        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad(self._prog)

        self._spec = np.zeros((_H, _W), dtype=np.float32)
        self._upload = np.zeros((_H, _W), dtype=np.uint8)
        self._spec_tex = self.ctx.texture((_W, _H), 1, data=self._upload.tobytes())
        self._spec_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)

        self._lut = _build_log_lut(_H, _F_BINS)

        self._bass = 0.0
        self._mid = 0.0
        self._treble = 0.0
        self._beat = 0.0

        self._style = int(self.parameters['style']) % 3
        self._style_timer = 0.0
        self._style_interval = float(self.rng.uniform(10.0, 18.0))

    def _choose_style(self) -> None:
        nxt = int(self.rng.integers(0, 3))
        if nxt == self._style:
            nxt = (nxt + 1) % 3
        self._style = nxt
        self.parameters['style'] = float(nxt)

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = float(audio.bass_n)
        self._mid = float(audio.mid_n)
        self._treble = float(audio.treble_n)

        if audio.beat > 0.5:
            self._beat = 1.0
            if self.rng.uniform() < 0.35:
                self._choose_style()
        self._beat = max(0.0, self._beat - dt * 2.8)

        self._style_timer += dt * max(0.05, float(self.parameters['speed']))
        if self._style_timer >= self._style_interval:
            self._style_timer = 0.0
            self._style_interval = float(self.rng.uniform(10.0, 18.0))
            self._choose_style()

        # Build newest spectrogram column from FFT with log-frequency mapping.
        fft = audio.fft[:_F_BINS]
        col = fft[self._lut].astype(np.float32)
        col = np.sqrt(np.clip(col, 0.0, 1.0))

        react = max(0.1, float(self.parameters['reactivity']))
        col *= 0.92 + react * 0.28

        # Add slight emphasis pulses per band from audio components.
        y = np.linspace(0.0, 1.0, _H, dtype=np.float32)
        col += self._bass * np.exp(-((y - 0.12) ** 2) / 0.008) * 0.22
        col += self._mid * np.exp(-((y - 0.45) ** 2) / 0.020) * 0.14
        col += self._treble * np.exp(-((y - 0.82) ** 2) / 0.018) * 0.18
        col += self._beat * np.exp(-((y - 0.30) ** 2) / 0.030) * 0.16
        col = np.clip(col, 0.0, 1.0)

        # Scroll left, append newest column on the right.
        self._spec[:, :-1] = self._spec[:, 1:]
        self._spec[:, -1] = col

        # Mild temporal decay to avoid over-saturation.
        self._spec *= 0.996

        self._upload[:, :] = (self._spec * 255.0).astype(np.uint8)
        self._spec_tex.write(self._upload.tobytes())

    def render(self) -> None:
        def _set(name: str, value) -> None:
            try:
                self._prog[name].value = value
            except KeyError:
                # Some drivers optimize uniforms out if not used in final shader code.
                pass

        self._spec_tex.use(location=0)
        _set('iSpecTex', 0)
        _set('iResolution', (float(self.width), float(self.height)))
        _set('iTime', self.time)
        _set('iBass', self._bass)
        _set('iMid', self._mid)
        _set('iTreble', self._treble)
        _set('iBeat', self._beat)
        _set('iSpeed', float(self.parameters['speed']))
        _set('iZoom', float(self.parameters['zoom']))
        _set('iReactivity', float(self.parameters['reactivity']))
        _set('iStyle', float(self._style))
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
        self._spec_tex.release()
