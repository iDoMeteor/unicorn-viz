"""
Audio Centroid — spectral brightness visualizer.

Renders a chromatic frequency iris whose color temperature tracks the spectral
centroid of the incoming audio in real time.  Bass-heavy audio (low centroid)
glows warm (reds, oranges, golds); treble-heavy audio (high centroid) shifts
cool (cyans, blues, violets).

Key visual elements
-------------------
- **Background plasma nebula** — a gentle chromatic field that breathes with
  the centroid and bass energy.
- **Spectral rings** — N concentric rings, each sampling one FFT band; a ring
  brightens and wobbles organically when its frequency band is active.
- **Centroid beacon** — a single prominent ring that tracks the real-time
  centroid frequency position; acts as a moving "center of mass" divider
  between the bass (inner, warm) and treble (outer, cool) zones.
- **Beat shockwave** — on beat onset a ring expands outward from the beacon,
  sweeping colour across the field.
- **Frequency tendrils** — radial spokes where each spoke angle maps to an FFT
  band; tendrils glow at band power, forming a polar frequency plot inside the
  innermost ring.
- **Treble sparkle** — stochastic bright points that scatter along the outer
  rings when high-frequency energy is elevated.

Startup randomization: ``color_shift``, ``speed``, and ``rings`` are seeded
from ``self.rng`` on each instantiation so no two runs look identical.
"""
from __future__ import annotations

import logging

import moderngl
import numpy as np

from unicornviz.effects.base import AudioData, BaseEffect

log = logging.getLogger(__name__)

_NYQUIST_HZ       = 22050.0
_FFT_BINS         = 512

# Centroid normalization: 8 000 Hz covers ambient (≈800 Hz) through metal / psytrance
# (3 500–5 000 Hz) with comfortable headroom; values above that clamp to 1.0.
_CENTROID_NORM_HZ = 8000.0


_VERT = """
#version 330
// Vertex — fullscreen quad to clip space; emits v_uv ∈ [0,1]² to fragment.
in  vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv        = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_FRAG = """
#version 330
// Fragment — Audio Centroid spectral iris.
// Uniforms: iTime, iResolution, iBass, iMid, iTreble, iBeat, iCentroid,
//           iFFT (sampler2D 512×1, R = FFT magnitude 0–1),
//           iBrightness, iSpeed, iColorShift, iRings (int).
// Output: fragColor (RGBA, premultiplied alpha not used).

uniform float     iTime;
uniform vec2      iResolution;
uniform float     iBass;
uniform float     iMid;
uniform float     iTreble;
uniform float     iBeat;
uniform float     iCentroid;    // normalized centroid [0 = bass … 1 = treble]
uniform sampler2D iFFT;         // 512×1 texture, R = FFT magnitude 0–1
uniform float     iBrightness;
uniform float     iSpeed;
uniform float     iColorShift;
uniform int       iRings;

in  vec2 v_uv;
out vec4 fragColor;

// Cosine palette: warm (bass) → cool (treble).
// t varies position along the colour cycle; c drives the warm/cool blend.
vec3 palette(float t, float c) {
    vec3 a = mix(vec3(0.88, 0.38, 0.08), vec3(0.08, 0.42, 0.88), c);
    vec3 b = mix(vec3(0.82, 0.52, 0.10), vec3(0.35, 0.08, 0.75), c);
    return a + b * cos(6.28318 * (t + vec3(0.0, 0.333, 0.667)));
}

// Sample FFT texture at normalized frequency fi ∈ [0,1].
float fft(float fi) {
    return texture(iFFT, vec2(clamp(fi, 0.001, 0.999), 0.5)).r;
}

void main() {
    vec2  uv  = (v_uv - 0.5) * vec2(iResolution.x / iResolution.y, 1.0) * 2.0;
    float r   = length(uv);
    float phi = atan(uv.y, uv.x);
    float t   = iTime * iSpeed;

    float halfW  = 2.0 / iResolution.y;
    int   nRings = max(4, min(iRings, 24));

    // ── Bass core bloom ───────────────────────────────────────────────
    float core = iBass * 0.40 * exp(-r * r * 5.5);

    // ── Spectral rings ────────────────────────────────────────────────
    // Each ring samples one FFT band; radius scales from inner (bass) to
    // outer (treble) across the same range as the centroid beacon.
    float ringTotal = 0.0;
    vec3  ringColor = vec3(0.0);

    for (int i = 0; i < 24; i++) {
        if (i >= nRings) break;
        float fi     = (float(i) + 0.5) / float(nRings);
        float band   = fft(fi * 0.5);       // lower half of spectrum

        float radius = 0.12 + fi * 0.78;
        float wobble = band * 0.018
                     * sin(phi * float(i + 2) * 0.7 + t * (0.8 + fi * 0.4));
        float dist   = abs(r - radius - wobble - iBass * 0.010);
        float glow   = band * smoothstep(halfW * 3.5, 0.0, dist);
        float rim    = smoothstep(halfW * 0.9, 0.0, dist) * 0.22;
        float contrib = glow + rim;

        ringTotal += contrib;
        ringColor += palette(fi + iColorShift, iCentroid) * contrib;
    }

    // ── Centroid beacon ───────────────────────────────────────────────
    // A prominent ring anchored to the centroid position; its warm/cool
    // colour is driven purely by the centroid so it reads as a "divider".
    float centR = 0.12 + iCentroid * 0.78;
    float centD = abs(r - centR - iBass * 0.012);
    float centG = 0.90 * smoothstep(halfW * 4.5, 0.0, centD)
                + 0.45 * smoothstep(halfW * 25.0, 0.0, centD);
    vec3  centC = palette(0.5 + iColorShift, iCentroid) * 1.9;

    // ── Beat shockwave ────────────────────────────────────────────────
    // Expands outward from the centroid ring position; fades as it leaves.
    float shockR = centR + (1.0 - iBeat) * 0.95;
    float shockD = abs(r - shockR);
    float shock  = iBeat
                 * smoothstep(halfW * 6.0, 0.0, shockD)
                 * smoothstep(1.15, 0.25, shockR);
    vec3  shockC = palette(0.68 + iColorShift, iCentroid) * 2.4;

    // ── Frequency tendrils ────────────────────────────────────────────
    // Each spoke angle maps to a FFT band; length ∝ band power.
    // Tendrils live inside the innermost ring (r < 0.12).
    float tfi   = mod(phi / 6.28318 + 0.5, 1.0);
    float tBand = fft(tfi * 0.5);
    float tMaxR = 0.10 + tBand * 0.52;
    float tGlow = 0.0;
    if (r < tMaxR && r > 0.02) {
        float rn = (r - 0.02) / max(tMaxR - 0.02, 0.001);
        tGlow    = tBand * pow(1.0 - rn, 1.6) * 0.42;
    }

    // ── Background plasma nebula ──────────────────────────────────────
    float bx = sin(uv.x * 2.4 + t * 0.52 + iBass * 1.4) * 0.5 + 0.5;
    float by = sin(uv.y * 2.4 - t * 0.38 + iMid  * 1.1) * 0.5 + 0.5;
    float bz = sin(length(uv) * 3.8 - t * 0.90) * 0.5 + 0.5;
    vec3  bg = palette((bx + by + bz) / 3.0 + iColorShift, iCentroid)
             * (0.052 + iBass * 0.028);

    // ── Treble sparkle ────────────────────────────────────────────────
    // Stochastic stars that appear on the outer ring band when treble peaks.
    float sa    = mod(tfi * 91.3 + floor(t * 7.0) * 0.1, 1.0);
    float spark = step(0.9940, fract(sin(sa * 127.1 + 3.7) * 43758.5))
                * iTreble
                * smoothstep(0.68, 0.0, abs(r - 0.78))
                * 2.6;

    // ── Compose layers ────────────────────────────────────────────────
    vec3 col = bg;
    col += palette(0.05 + iColorShift, iCentroid) * core;
    if (ringTotal > 0.001)
        col += (ringColor / ringTotal) * ringTotal;
    col += centC * centG;
    col += shockC * shock;
    col += palette(tfi + iColorShift, iCentroid) * tGlow;
    col += palette(0.92 + iColorShift, iCentroid) * spark;

    // Master brightness, soft power-curve gamma lift
    col *= iBrightness;
    col  = pow(clamp(col, vec3(0.0), vec3(1.0)), vec3(0.80));

    // Radial vignette — brightens at mid-radii, dims toward screen edge
    col *= 1.0 - smoothstep(0.52, 1.08, r * 0.74);

    fragColor = vec4(col, 1.0);
}
"""


class AudioCentroid(BaseEffect):
    """Spectral brightness visualizer driven by the real-time spectral centroid.

    The spectral centroid (frequency-weighted FFT mean, Hz) is computed each
    frame and smoothed with a 150 ms exponential filter.  Its normalized value
    drives the warm/cool colour temperature of the entire scene: bass-heavy
    audio produces deep reds and golds; treble-heavy audio shifts to icy blues
    and violets.

    GL resources:
        _prog     — single GLSL program (fullscreen quad)
        _vao      — fullscreen quad VAO
        _vbo      — fullscreen quad VBO
        _fft_tex  — 512×1 R32F texture updated each frame from audio.fft

    Thread safety: all GL operations happen on the main thread; audio.fft
    is read-only access to a snapshot owned by the audio thread.
    """

    NAME   = 'Audio Centroid'
    AUTHOR = 'unicorn-viz'
    TAGS = ['analyzer', 'spectrum', 'reactive']

    def _init(self) -> None:
        self.parameters = {
            'brightness':   float(self.config.get('brightness',   1.15)),
            'speed':        float(self.rng.uniform(0.55, 1.15)),
            'color_shift':  float(self.rng.uniform(0.0, 1.0)),
            'rings':        float(self.rng.integers(12, 25)),
            'glow_width':   float(self.config.get('glow_width',   2.0)),
        }

        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()

        # 512×1 single-channel float32 texture for FFT data (updated each frame).
        self._fft_tex = self.ctx.texture((_FFT_BINS, 1), 1, dtype='f4')
        self._fft_tex.filter   = moderngl.LINEAR, moderngl.LINEAR
        self._fft_tex.repeat_x = False
        self._fft_tex.repeat_y = False

        # Pre-allocated arrays — no hot-path allocation.
        self._fft_buf      = np.zeros(_FFT_BINS, dtype=np.float32)
        self._freq_weights = np.linspace(0.0, _NYQUIST_HZ, _FFT_BINS,
                                         endpoint=False, dtype=np.float32)

        # Smoothed audio state
        self._centroid  = float(self.rng.uniform(0.2, 0.6))  # random start phase
        self._bass      = 0.0
        self._mid       = 0.0
        self._treble    = 0.0
        self._beat      = 0.0

    def update(self, dt: float, audio: AudioData) -> None:
        """Compute spectral centroid, smooth all signals, upload FFT texture."""
        super().update(dt, audio)

        # Smooth band energies (50 ms attack, 80 ms decay feel)
        alpha = 1.0 - float(np.exp(-dt / 0.07))
        self._bass   += alpha * (float(audio.bass_n)   - self._bass)
        self._mid    += alpha * (float(audio.mid_n)    - self._mid)
        self._treble += alpha * (float(audio.treble_n) - self._treble)

        # Beat: one-shot trigger with exponential decay (CLAUDE.md convention)
        if audio.beat > 0.5:
            self._beat = 1.0
        self._beat = max(0.0, self._beat - dt * 3.8)

        # Spectral centroid from FFT magnitude spectrum
        fft = audio.fft          # float32[512], 0–1 magnitudes
        fft_sum = float(fft.sum())
        if fft_sum > 1e-5:
            centroid_hz = float(np.dot(self._freq_weights, fft)) / fft_sum
        else:
            centroid_hz = 0.0
        centroid_raw = float(np.clip(centroid_hz / _CENTROID_NORM_HZ, 0.0, 1.0))

        # 150 ms smoothing so the beacon ring glides rather than jitters
        c_alpha = 1.0 - float(np.exp(-dt / 0.15))
        self._centroid += c_alpha * (centroid_raw - self._centroid)

        # Upload FFT texture (copy into pre-allocated buffer to avoid allocation)
        np.copyto(self._fft_buf, fft)
        self._fft_tex.write(self._fft_buf.tobytes())

    def render(self) -> None:
        """Draw spectral iris to the currently bound FBO."""
        p = self._prog
        p['iTime'].value       = self.time
        p['iResolution'].value = (float(self.width), float(self.height))
        p['iBass'].value       = self._bass
        p['iMid'].value        = self._mid
        p['iTreble'].value     = self._treble
        p['iBeat'].value       = self._beat
        p['iCentroid'].value   = self._centroid
        p['iBrightness'].value = float(self.parameters['brightness'])
        p['iSpeed'].value      = float(self.parameters['speed'])
        p['iColorShift'].value = float(self.parameters['color_shift'])
        p['iRings'].value      = int(self.parameters['rings'])

        self._fft_tex.use(location=0)
        p['iFFT'].value = 0

        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        """Release all GL resources."""
        for obj in (self._vao, self._vbo, self._prog, self._fft_tex):
            obj.release()
