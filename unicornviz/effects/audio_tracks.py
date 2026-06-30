"""Audio Tracks — DAW-style horizontal scrolling track lanes.

A performance-oriented interpretation of the horizontal waveform tracks seen in
DJ/DAW software. The effect keeps a scrolling history texture and renders
multiple lane waveforms with beat accents, moving playhead glow, and style
morphing over time.
"""
from __future__ import annotations

import math

import moderngl
import numpy as np

from unicornviz.effects.base import AudioData, BaseEffect

_W = 480
_H = 224
_TRACKS = 7

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
uniform sampler2D iTrackTex;
uniform vec2  iResolution;
uniform float iTime;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
uniform float iBeat;
uniform float iSpeed;
uniform float iZoom;
uniform float iReactivity;
uniform float iGlow;
uniform float iStyle;
uniform float iPlayheadX;
uniform float iPlayPhase;
in vec2 v_uv;
out vec4 fragColor;

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

vec3 palette(float t, float style) {
    vec3 a = vec3(0.5);
    vec3 b = vec3(0.5);
    vec3 c = vec3(1.0);
    vec3 d0 = vec3(0.03, 0.18, 0.42);
    vec3 d1 = vec3(0.12, 0.31, 0.56);
    vec3 d2 = vec3(0.28, 0.09, 0.48);
    vec3 d3 = vec3(0.00, 0.42, 0.24);
    vec3 d = mix(d0, d1, smoothstep(0.5, 1.5, style));
    d = mix(d, d2, smoothstep(1.5, 2.5, style));
    d = mix(d, d3, smoothstep(2.5, 3.5, style));
    return a + b * cos(6.28318 * (c * t + d));
}

void main() {
    float speed = max(iSpeed, 0.05);
    float zoom = max(iZoom, 0.1);
    float react = max(iReactivity, 0.1);

    vec2 uv = (v_uv - 0.5) / zoom + 0.5;

    // Slight tape-drift movement for life.
    uv.y += 0.004 * sin(iTime * 0.7 * speed + uv.x * 10.0 + iMid * 3.0);

    float data = texture(iTrackTex, clamp(uv, 0.0, 1.0)).r;

    // Track lane guides.
    float lanes = 0.0;
    for (int i = 0; i < 7; i++) {
        float y = (float(i) + 0.5) / 7.0;
        lanes += smoothstep(0.006, 0.0, abs(uv.y - y));
    }

    vec3 bgA = vec3(0.03, 0.04, 0.10);
    vec3 bgB = vec3(0.08, 0.02, 0.12);
    vec3 bgC = vec3(0.02, 0.10, 0.14);
    vec3 bg = mix(bgA, bgB, 0.45 + 0.35 * sin(iTime * 0.17 + iStyle));
    bg = mix(bg, bgC, smoothstep(0.2, 0.95, uv.y));
    bg += vec3(0.16, 0.22, 0.30) * lanes * 0.18;

    // Data coloring.
    float energy = pow(clamp(data * (0.9 + react * 0.6), 0.0, 1.0), 0.85);
    vec3 wave_col = palette(uv.y * 0.6 + energy * 0.45 + iTime * 0.03 * speed, iStyle);
    wave_col *= (0.75 + iBass * 0.35 + iTreble * 0.28);
    wave_col *= energy;

    // Treble spark details on peaks.
    float spark = step(0.996, hash(floor(uv * vec2(320.0, 180.0)) + floor(iTime * 10.0)));
    wave_col += vec3(1.0, 0.96, 0.85) * spark * energy * (0.12 + iTreble * 0.55);

    // Beat pulse sweeps across lanes.
    float sweep = smoothstep(0.03, 0.0, abs(fract(uv.x * 8.0 + iTime * (1.1 + iBeat * 2.4)) - 0.5));
    wave_col += vec3(0.30, 0.85, 1.00) * sweep * iBeat * 0.35;

    // Playhead highlight.
    float play = smoothstep(0.010, 0.0, abs(v_uv.x - iPlayheadX));
    float t = iTime * (1.4 + iSpeed * 0.8);
    float travel = abs(fract(iPlayPhase) * 2.0 - 1.0);         // ping-pong 0..1..0
    float laser_node = smoothstep(0.16, 0.0, abs(v_uv.y - travel));
    float laser_beam = 0.55 + 0.45 * sin((v_uv.y * 42.0) - t * 10.0 + iStyle * 1.7);
    vec3 laser_core = mix(vec3(0.12, 0.95, 1.00), vec3(1.00, 0.15, 0.88), 0.45 + 0.35 * sin(t * 0.35));
    vec3 laser_glow = vec3(0.18, 0.55, 1.00);

    float beam_energy = play * (0.22 + iGlow * 0.35 + iTreble * 0.28);
    beam_energy *= 0.75 + 0.25 * laser_beam;
    float node_energy = play * laser_node * (0.55 + iBeat * 0.45 + iBass * 0.30 + iGlow * 0.25);

    vec3 play_col = laser_glow * beam_energy + laser_core * node_energy;

    vec3 col = bg + wave_col + play_col;

    // Vignette + tone.
    float vig = 1.0 - dot(v_uv - 0.5, v_uv - 0.5) * 0.75;
    col *= vig;
    col = col / (col + 0.7);

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""


class AudioTracks(BaseEffect):
    """Horizontal scrolling multi-track waveform timeline."""

    NAME = 'Audio Tracks'
    AUTHOR = 'unicorn-viz'
    TAGS = ['audio', 'visualizer', 'timeline']
    PING_PONG_FRIENDS = [
        'Audio Spectrum',
        'Audio Spectrogram',
        'Audio Waveforms',
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

        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad(self._prog)

        self._buf = np.zeros((_H, _W), dtype=np.float32)
        self._upload = np.zeros((_H, _W), dtype=np.uint8)
        self._tex = self.ctx.texture((_W, _H), 1, data=self._upload.tobytes())
        self._tex.filter = (moderngl.LINEAR, moderngl.LINEAR)

        self._bass = 0.0
        self._mid = 0.0
        self._treble = 0.0
        self._beat = 0.0
        self._bpm = 0.0
        self._play_phase = 0.0

        self._style = int(self.parameters['style']) % 4
        self._style_timer = 0.0
        self._style_interval = float(self.rng.uniform(9.0, 15.0))

        self._playhead = 0.84

        # Precompute lane centers in texture rows.
        ys = np.linspace(0.10, 0.90, _TRACKS, dtype=np.float32)
        self._lane_rows = (ys * (_H - 1)).astype(np.int32)

    def _choose_style(self) -> None:
        nxt = int(self.rng.integers(0, 4))
        if nxt == self._style:
            nxt = (nxt + 1) % 4
        self._style = nxt
        self.parameters['style'] = float(nxt)

    def _append_column(self, audio: AudioData) -> None:
        react = max(0.1, float(self.parameters['reactivity']))
        speed = max(0.05, float(self.parameters['speed']))

        col = np.zeros(_H, dtype=np.float32)

        wave = audio.waveform
        fft = audio.fft

        for i, row in enumerate(self._lane_rows):
            # Wave chunk per lane + fft band mixture for DAW-like lane variance.
            a = int(i * len(wave) / _TRACKS)
            b = int((i + 1) * len(wave) / _TRACKS)
            w = float(np.mean(np.abs(wave[a:b])))

            fa = int(i * len(fft) / _TRACKS)
            fb = int((i + 1) * len(fft) / _TRACKS)
            f = float(np.mean(fft[fa:fb]))

            amp = (w * 0.72 + f * 0.58) * (0.85 + react * 0.55)
            amp += self._bass * 0.10 + self._beat * 0.12
            amp = float(np.clip(amp, 0.0, 1.0))

            # Width/radius around lane center.
            radius = 2.0 + amp * 9.0 + self._treble * 2.2
            lo = max(0, int(row - radius))
            hi = min(_H, int(row + radius + 1))
            y = np.arange(lo, hi, dtype=np.float32)
            shape = np.exp(-((y - row) ** 2) / max(1.0, (radius * 0.58) ** 2))
            col[lo:hi] = np.maximum(col[lo:hi], shape * amp)

            # Beat spikes as little transients.
            if self._beat > 0.2 and self.rng.uniform() < 0.22 + self._treble * 0.25:
                p = int(np.clip(row + self.rng.integers(-6, 7), 0, _H - 1))
                col[max(0, p - 1):min(_H, p + 2)] = 1.0

        # Style modulation.
        if self._style == 1:
            col = np.power(col, 0.78)
        elif self._style == 2:
            col *= 0.82 + 0.18 * np.sin(np.linspace(0.0, math.tau, _H, dtype=np.float32) + self.time * 3.2 * speed)
            col = np.clip(col, 0.0, 1.0)
        elif self._style == 3:
            col = np.tanh(col * 1.8)

        # Scroll left and append on right.
        self._buf[:, :-1] = self._buf[:, 1:]
        self._buf[:, -1] = col

        # Slight decay to keep texture dynamic.
        self._buf *= 0.995

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = float(audio.bass_n)
        self._mid = float(audio.mid_n)
        self._treble = float(audio.treble_n)
        self._bpm = float(getattr(audio, 'bpm', 0.0) or 0.0)

        if audio.beat > 0.5:
            self._beat = 1.0
            if self.rng.uniform() < 0.30:
                self._choose_style()
        self._beat = max(0.0, self._beat - dt * 3.2)

        self._style_timer += dt * max(0.1, float(self.parameters['speed']))
        if self._style_timer >= self._style_interval:
            self._style_timer = 0.0
            self._style_interval = float(self.rng.uniform(9.0, 15.0))
            self._choose_style()

        # BPM-synced playhead node motion when a valid BPM is present.
        # Fallback to prior free-run cadence otherwise.
        bpm = self._bpm
        if 40.0 <= bpm <= 240.0:
            # 1 cycle per beat; ping-pong mapping in shader turns this into up/down travel.
            self._play_phase = (self._play_phase + dt * (bpm / 60.0)) % 1.0
        else:
            self._play_phase = (self._play_phase + dt * (0.5 + float(self.parameters['speed']) * 0.35)) % 1.0

        # Add multiple columns at higher speed for faster timeline motion.
        steps = max(1, int(round(max(0.5, float(self.parameters['speed'])) * 1.6)))
        for _ in range(steps):
            self._append_column(audio)

        self._upload[:, :] = (np.clip(self._buf, 0.0, 1.0) * 255.0).astype(np.uint8)
        self._tex.write(self._upload.tobytes())

    def render(self) -> None:
        def _set(name: str, value) -> None:
            try:
                self._prog[name].value = value
            except KeyError:
                pass

        self._tex.use(location=0)
        _set('iTrackTex', 0)
        _set('iResolution', (float(self.width), float(self.height)))
        _set('iTime', self.time)
        _set('iBass', self._bass)
        _set('iMid', self._mid)
        _set('iTreble', self._treble)
        _set('iBeat', self._beat)
        _set('iSpeed', float(self.parameters['speed']))
        _set('iZoom', float(self.parameters['zoom']))
        _set('iReactivity', float(self.parameters['reactivity']))
        _set('iGlow', float(self.parameters['glow']))
        _set('iStyle', float(self._style))
        _set('iPlayheadX', float(self._playhead))
        _set('iPlayPhase', float(self._play_phase))
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
        self._tex.release()
