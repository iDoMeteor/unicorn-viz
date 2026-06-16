"""
Audio Spectrum — frequency bars + oscilloscope waveform.
Two sub-modes cycled with a parameter:
  mode=0  spectrum bars (FFT)
  mode=1  oscilloscope (waveform)
    mode=2  bars + matrix/binary DNA rain background
"""
from __future__ import annotations

import math
import numpy as np
import moderngl

from unicornviz.effects.base import BaseEffect, AudioData

_VERT_BARS = """
#version 330
in  vec2  in_pos;
in  float in_mag;
in  vec3  in_col;
out vec2  v_pos;
out float v_mag;
out vec3  v_col;
void main() {
    gl_Position = vec4(in_pos, 0.0, 1.0);
    v_pos = in_pos;
    v_mag = in_mag;
    v_col = in_col;
}
"""

_FRAG_BARS = """
#version 330
uniform float iTime;
uniform float iBass;
uniform float iTreble;
uniform float iGlow;
uniform float iReactivity;
in  vec2  v_pos;
in  float v_mag;
in  vec3  v_col;
out vec4  fragColor;

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

void main() {
    vec2 cell = floor((v_pos + 1.0) * vec2(12.0, 8.0));
    vec2 local_uv = fract((v_pos + 1.0) * vec2(12.0, 8.0));
    float seed = hash(cell + floor(iTime * 4.0));
    vec2 spark_pos = vec2(hash(cell + 1.37), hash(cell + 3.91));
    float spark = smoothstep(0.28, 0.0, distance(local_uv, spark_pos));
    spark *= smoothstep(0.995, 1.0, seed);

    float core = smoothstep(0.48, 0.0, distance(local_uv, vec2(0.5)));
    float shimmer = 0.65 + 0.35 * sin(iTime * 5.5 + v_pos.y * 18.0 + v_mag * 10.0);
    float glow = clamp(0.50 + v_mag * 0.42 + iGlow * 0.18 + core * 0.24, 0.35, 1.0);
    float reactivity = clamp(iReactivity, 0.1, 1.2);
    float intensity = 0.58 + v_mag * (0.26 + iBass * 0.20) * reactivity;
    vec3 sparkle_col = mix(v_col, vec3(1.0, 0.96, 0.72), 0.55);
    vec3 col = v_col * intensity;
    col += v_col * core * (0.18 + iGlow * 0.10) * shimmer * reactivity;
    col += sparkle_col * spark * (0.45 + iTreble * 0.70) * reactivity;
    fragColor = vec4(clamp(col, 0.0, 1.0), glow);
}
"""

_VERT_WAVE = """
#version 330
in  vec2 in_pos;
out float v_x;
void main() {
    gl_Position = vec4(in_pos, 0.0, 1.0);
    v_x = in_pos.x;
}
"""

_FRAG_WAVE = """
#version 330
in  float v_x;
out vec4  fragColor;
uniform vec3 uColor;
void main() {
    fragColor = vec4(uColor, 0.9);
}
"""

_VERT_FULL = """
#version 330
in  vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_FRAG_NEBULA = """
#version 330
uniform float iTime;
uniform float iBass;
uniform float iMid;
uniform vec2  iResolution;

in  vec2 v_uv;
out vec4 fragColor;

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
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
    float a = 0.55;
    for (int i = 0; i < 5; i++) {
        v += a * noise(p);
        p = p * 2.02 + vec2(0.17, -0.11);
        a *= 0.5;
    }
    return v;
}

void main() {
    vec2 uv = v_uv * 2.0 - 1.0;
    uv.x *= iResolution.x / max(iResolution.y, 1.0);

    float t = iTime * (0.12 + iBass * 0.2);
    vec2 p = uv;
    p += 0.12 * vec2(sin(t * 0.9 + uv.y * 1.8), cos(t * 0.7 + uv.x * 1.5));

    float n1 = fbm(p * 1.35 + vec2(t * 0.25, -t * 0.18));
    float n2 = fbm(p * 2.1  - vec2(t * 0.16,  t * 0.21));
    float neb = smoothstep(0.25, 0.9, n1 * 0.75 + n2 * 0.5);

    float spin = 0.5 + 0.5 * sin((uv.x + uv.y) * 3.6 + t * 1.4 + iMid * 2.0);

    vec3 c1 = vec3(0.05, 0.08, 0.20);
    vec3 c2 = vec3(0.12, 0.05, 0.22);
    vec3 c3 = vec3(0.06, 0.18, 0.26);
    vec3 col = mix(c1, c2, n1);
    col = mix(col, c3, spin * 0.7 + n2 * 0.3);
    col *= neb;

    // Increased brightness and density: now up to 90% brightness
    col = clamp(col * (0.65 + iBass * 0.35 + iMid * 0.20), 0.0, 0.90);

    fragColor = vec4(col, 1.0);
}
"""

_FRAG_RAIN = """
#version 330
uniform float iTime;
uniform float iBass;
uniform float iTreble;
uniform vec2  iResolution;

in  vec2 v_uv;
out vec4 fragColor;

float hash(float n) { return fract(sin(n) * 43758.5453123); }
float hash2(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

// 5x7 bitmap glyphs for: 0,1,A,C,G,T
float glyph6(int id, vec2 frac) {
    int x = int(floor(frac.x * 5.0));
    int y = int(floor(frac.y * 7.0));
    if (x < 0 || x > 4 || y < 0 || y > 6) return 0.0;

    // Common edges
    bool l = (x == 0);
    bool r = (x == 4);
    bool t = (y == 0);
    bool b = (y == 6);
    bool m = (y == 3);

    bool on = false;
    if (id == 0) {                 // '0'
        on = (t || b || l || r) && !(m && (x > 0 && x < 4));
    } else if (id == 1) {          // '1'
        on = (x == 2) || (y == 1 && x == 1) || (b && x > 0 && x < 4);
    } else if (id == 2) {          // 'A'
        on = t || m || l || r;
    } else if (id == 3) {          // 'C'
        on = l || t || b;
    } else if (id == 4) {          // 'G'
        on = l || t || b || (x == 4 && y >= 3) || (y == 3 && x >= 2);
    } else {                        // 'T'
        on = t || (x == 2);
    }
    return on ? 1.0 : 0.0;
}

void main() {
    // Character grid: width matches eq bar width for visual alignment
    // 64 bars = 64 chars across screen
    float charW = iResolution.x / 64.0;
    float charH = charW * 1.5;

    vec2 cell = floor(v_uv * iResolution / vec2(charW, charH));
    vec2 frac = fract(v_uv * iResolution / vec2(charW, charH));

    float col = cell.x;
    float row = cell.y;
    float nRows = iResolution.y / charH;

    // Each column has an offset and speed
    float speed  = 3.0 + hash(col * 7.3) * 7.0 + iBass * 5.0;
    float offset = hash(col * 13.1) * nRows;
    float head   = mod(iTime * speed + offset, nRows * 1.4);

    // Distance below the head
    float dist = head - row;

    if (dist < 0.0 || dist > 22.0) {
        fragColor = vec4(0.0);
        return;
    }

    // Choose cyan or purple column
    float colType = step(0.5, hash(col * 31.7));

    // Brightness falls off below head
    float bright = exp(-dist * 0.18) * (0.85 + iTreble * 0.5);
    // Head pixel extra bright
    if (dist < 1.0) bright = 1.0 + iTreble * 0.6;

    // Changing character: flicker faster near head
    float t = iTime * (1.6 + (1.0 - dist / 22.0) * 4.0);
    float r = hash2(vec2(col, floor(t) + row * 0.17));
    int gid = int(floor(r * 6.0));
    float lit = glyph6(gid, frac);

    vec3 cyan    = vec3(0.0, 1.0, 0.95);
    vec3 purple  = vec3(0.75, 0.0, 1.0);
    vec3 tint    = mix(cyan, purple, colType);

    fragColor = vec4(tint * bright * lit, bright * lit * 0.85);
}
"""

_N_BARS = 64
_N_WAVE = 512

# Frequency mapping constants.
# AudioCapture defaults to a 48 kHz stream and Analyzer runs an rfft with
# n=1024 (fft_bands * 2), so each FFT bin spans sample_rate / n_fft Hz.
# Bin i covers approximately i * 46.875 Hz at 48 kHz.
_FFT_BINS = 512
_FFT_NFFT = 1024
_SAMPLE_RATE_ASSUMED = 48000
_BIN_HZ = _SAMPLE_RATE_ASSUMED / _FFT_NFFT  # ~46.875 Hz/bin
_F_MIN = 30.0     # Hz; below this is mostly DC/sub-bass rumble
_F_MAX = 16000.0  # Hz; covers full musical range without wasting bars on hiss


def _build_log_band_edges(
    n_bars: int,
    n_fft_bins: int,
    bin_hz: float,
    f_min: float,
    f_max: float,
) -> np.ndarray:
    """Build log-spaced FFT bin edges so each EQ bar covers a perceptual band."""
    edges = np.logspace(np.log10(f_min), np.log10(f_max), n_bars + 1)
    bin_idx = np.clip(
        np.round(edges / bin_hz).astype(np.int32),
        1,
        n_fft_bins - 1,
    )
    # Force monotonic increase so each bar gets at least one bin.
    for i in range(1, len(bin_idx)):
        if bin_idx[i] <= bin_idx[i - 1]:
            bin_idx[i] = bin_idx[i - 1] + 1
    return np.clip(bin_idx, 0, n_fft_bins)


def _bar_colour(i: int, n: int) -> tuple[float, float, float]:
    """HSV-like rainbow across bar index."""
    t = i / n
    r = 0.5 + 0.5 * math.sin(t * 6.28 + 0.0)
    g = 0.5 + 0.5 * math.sin(t * 6.28 + 2.09)
    b = 0.5 + 0.5 * math.sin(t * 6.28 + 4.18)
    return r, g, b


class AudioSpectrum(BaseEffect):
    NAME = "Audio Spectrum"
    AUTHOR = "unicorn-viz"
    TAGS = ["audio", "visualizer"]
    PING_PONG_FRIENDS = [
        'Audio Spectrogram',
        'Audio Tracks',
        'Audio Waveforms',
        'Sine Scroller 3.1',
        'Unicorn Tears',
    ]

    def _init(self) -> None:
        self.parameters = {
            "mode": 2,
            "glow": 1.0,
            "reactivity": max(0.1, min(1.2, float(self.config.get('reactivity', 1.0)))),
        }
        self.scale_when_framed = bool(self.config.get('scale_when_framed', True))

        self._nebula_prog = self._make_program(_VERT_FULL, _FRAG_NEBULA)
        self._nebula_vao, self._nebula_vbo = self._fullscreen_quad(self._nebula_prog)

        self._rain_prog = self._make_program(_VERT_FULL, _FRAG_RAIN)
        self._rain_vao, self._rain_vbo = self._fullscreen_quad(self._rain_prog)

        self._bar_prog  = self._make_program(_VERT_BARS, _FRAG_BARS)
        self._wave_prog = self._make_program(_VERT_WAVE, _FRAG_WAVE)

        # Pre-allocate to worst-case size for stacked blocks (not smooth bars).
        # Worst case: 64 bars × ~37 blocks/bar × 6 verts/block × 6 floats × 4 bytes
        # = 64 × 37 × 6 × 6 × 4 ≈ 336 KB
        bar_bytes = _N_BARS * 40 * 6 * 6 * 4  # Conservative upper bound
        self._bar_vbo = self.ctx.buffer(reserve=bar_bytes)
        # Wave: _N_WAVE vec2 points × 4 bytes
        wave_bytes = _N_WAVE * 2 * 4
        self._wave_vbo = self.ctx.buffer(reserve=wave_bytes)

        # Explicit format strings: 2f=pos, 1f=mag, 3f=col (24 bytes stride)
        self._bar_vao = self.ctx.vertex_array(
            self._bar_prog,
            [(self._bar_vbo, "2f 1f 3f", "in_pos", "in_mag", "in_col")],
        )
        # Wave: 2f=pos (8 bytes stride)
        self._wave_vao = self.ctx.vertex_array(
            self._wave_prog,
            [(self._wave_vbo, "2f", "in_pos")],
        )

        self._fft  = np.zeros(_N_BARS, dtype=np.float32)
        self._wave = np.zeros(_N_WAVE, dtype=np.float32)
        self._smooth = np.zeros(_N_BARS, dtype=np.float32)
        self._peak   = np.zeros(_N_BARS, dtype=np.float32)
        self._peak_hold = np.zeros(_N_BARS, dtype=np.float32)
        self._bass   = 0.0
        self._mid    = 0.0
        self._treble = 0.0

        # Wave 2.4 — pre-allocated VBO fill buffers to eliminate Python list
        # churn in _build_bars() / _build_waveform() on every render frame.
        # Max blocks per bar matches the VBO reservation: 40 × 6 verts × 6 floats.
        self._bars_work_buf: np.ndarray = np.zeros(
            _N_BARS * 40 * 6 * 6, dtype=np.float32
        )
        # Waveform scratch: x column is constant and set once here.
        self._wave_xs: np.ndarray = np.linspace(-1.0, 1.0, _N_WAVE, dtype=np.float32)
        self._wave_work_buf: np.ndarray = np.zeros((_N_WAVE, 2), dtype=np.float32)
        self._wave_work_buf[:, 0] = self._wave_xs

        # Log-spaced band edges: each EQ bar covers [edges[i], edges[i+1]) bins.
        self._band_edges = _build_log_band_edges(
            _N_BARS, _FFT_BINS, _BIN_HZ, _F_MIN, _F_MAX,
        )
        # Mild pink-noise compensation so a flat spectrum looks roughly even
        # across the whole bar range. Computed from band centres so it does
        # not depend on per-frame audio.
        center_freqs = np.sqrt(
            (self._band_edges[:-1] * _BIN_HZ).clip(min=_F_MIN)
            * (self._band_edges[1:] * _BIN_HZ).clip(min=_F_MIN)
        )
        self._band_gain = (center_freqs / _F_MIN).astype(np.float32) ** 0.35

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass   = audio.bass
        self._mid    = audio.mid
        self._treble = audio.treble

        if audio.fft is not None and len(audio.fft) >= self._band_edges[-1]:
            src = audio.fft
            for i in range(_N_BARS):
                lo = int(self._band_edges[i])
                hi = int(self._band_edges[i + 1])
                if hi <= lo:
                    hi = lo + 1
                # Mean of bins in band, weighted by mild pink-noise gain.
                self._fft[i] = float(src[lo:hi].mean()) * self._band_gain[i]
            np.clip(self._fft, 0.0, 1.0, out=self._fft)
        else:
            self._fft.fill(0.0)

        # Smooth + peak hold
        self._smooth *= 0.8
        self._smooth += self._fft * 0.2
        np.subtract(self._peak_hold, dt * 0.4, out=self._peak_hold)
        np.maximum(self._peak_hold, 0.0, out=self._peak_hold)
        new_peaks = self._smooth > self._peak
        self._peak[new_peaks] = self._smooth[new_peaks]
        self._peak_hold[new_peaks] = 1.5
        decay_mask = self._peak_hold <= 0.0
        self._peak[decay_mask] *= 0.99

        if audio.waveform is not None and len(audio.waveform) >= _N_WAVE:
            self._wave[:] = audio.waveform[:_N_WAVE]
        else:
            self._wave.fill(0.0)

    def _build_bars(self) -> tuple[np.ndarray, int]:
        """Build bars as stacked discrete blocks (80s boombox style).

        Writes directly into the pre-allocated ``_bars_work_buf`` to avoid
        Python list allocation and the ``np.array()`` conversion on every frame.
        """
        buf = self._bars_work_buf
        ptr = 0
        bar_w = 2.0 / _N_BARS
        block_h: float = 0.05
        peak_block_h: float = 0.02

        for i in range(_N_BARS):
            h = float(self._smooth[i]) * 1.8
            x0 = -1.0 + i * bar_w + bar_w * 0.05
            x1 = x0 + bar_w * 0.90
            r, g, b = _bar_colour(i, _N_BARS)
            mag = float(self._smooth[i])

            n_blocks = max(1, min(int(h / block_h), 38))
            for k in range(n_blocks):
                by0 = -1.0 + k * block_h
                by1 = by0 + block_h * 0.9
                buf[ptr:ptr + 36] = (
                    x0, by0, mag, r, g, b,
                    x1, by0, mag, r, g, b,
                    x0, by1, mag, r, g, b,
                    x1, by0, mag, r, g, b,
                    x1, by1, mag, r, g, b,
                    x0, by1, mag, r, g, b,
                )
                ptr += 36

            py = -1.0 + float(self._peak[i]) * 1.8
            inv_r, inv_g, inv_b = 1.0 - r, 1.0 - g, 1.0 - b
            buf[ptr:ptr + 36] = (
                x0, py,                 inv_r, inv_g, inv_b, 0.6,
                x1, py,                 inv_r, inv_g, inv_b, 0.6,
                x0, py + peak_block_h,  inv_r, inv_g, inv_b, 0.6,
                x1, py,                 inv_r, inv_g, inv_b, 0.6,
                x1, py + peak_block_h,  inv_r, inv_g, inv_b, 0.6,
                x0, py + peak_block_h,  inv_r, inv_g, inv_b, 0.6,
            )
            ptr += 36

        return buf[:ptr], ptr // 6

    def _build_waveform(self, y_base: float, y_scale: float) -> tuple[np.ndarray, int]:
        """Build waveform vertex data in-place using pre-allocated scratch buffer."""
        np.multiply(self._wave, y_scale, out=self._wave_work_buf[:, 1])
        self._wave_work_buf[:, 1] += y_base
        return self._wave_work_buf, _N_WAVE

    def render(self) -> None:
        mode = int(self.parameters["mode"]) % 3
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)

        # Nebula layer (kept dim to avoid overpowering glyphs/bars)
        self._nebula_prog["iTime"].value       = self.time
        self._nebula_prog["iBass"].value       = self._bass
        self._nebula_prog["iMid"].value        = self._mid
        self._nebula_prog["iResolution"].value = (float(self.width), float(self.height))
        self._nebula_vao.render(moderngl.TRIANGLE_STRIP)

        # Matrix rain background (additive blend ON)
        self.ctx.enable(moderngl.BLEND)
        self._rain_prog["iTime"].value       = self.time
        self._rain_prog["iBass"].value       = self._bass
        self._rain_prog["iTreble"].value     = self._treble
        self._rain_prog["iResolution"].value = (float(self.width), float(self.height))
        self._rain_vao.render(moderngl.TRIANGLE_STRIP)

        if mode in (0, 2):
            bar_data, n_bar_verts = self._build_bars()
            if bar_data.nbytes <= self._bar_vbo.size:
                self._bar_vbo.write(bar_data)
                self._bar_prog["iTime"].value = self.time
                self._bar_prog["iBass"].value = self._bass
                self._bar_prog["iTreble"].value = self._treble
                self._bar_prog["iGlow"].value = float(self.parameters["glow"])
                self._bar_prog["iReactivity"].value = float(self.parameters["reactivity"])
                self._bar_vao.render(moderngl.TRIANGLES, vertices=n_bar_verts)

        # Keep squiggle waveform only in dedicated oscilloscope mode.
        if mode == 1:
            y_base  = 0.0 if mode == 1 else -0.5
            y_scale = 0.8 if mode == 1 else 0.4
            wave_data, n_wave = self._build_waveform(y_base, y_scale)
            if wave_data.nbytes <= self._wave_vbo.size:
                self._wave_vbo.write(wave_data)
                self._wave_prog["uColor"].value = (0.3, 1.0, 0.8)
                self._wave_vao.render(moderngl.LINE_STRIP, vertices=n_wave)

    def destroy(self) -> None:
        self._nebula_vao.release()
        self._nebula_vbo.release()
        self._nebula_prog.release()
        self._rain_vao.release()
        self._rain_vbo.release()
        self._rain_prog.release()
        self._bar_vao.release()
        self._wave_vao.release()
        self._bar_vbo.release()
        self._wave_vbo.release()
        self._bar_prog.release()
        self._wave_prog.release()
