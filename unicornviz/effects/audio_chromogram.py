"""Audio Chromogram — real pitch-class (chroma) analysis of the live signal.

A chromagram folds every FFT bin into one of the twelve pitch classes
(C, C#, D, ... B) regardless of octave, by mapping each bin's frequency to
its equal-tempered MIDI note mod 12 (each bin contributes to nearby pitch
classes with a soft weighting, not a hard round — see
``_build_chroma_weights`` for why, and for the real achievable precision at
each frequency). Unlike Audio Spectrogram (which shows raw frequency
content), this reveals the *harmonic/tonal* content — which notes are
actually sounding — so chords and key changes read as clear, distinct colour
patterns instead of a diffuse frequency smear, from roughly the bass/guitar
range upward; sub-bass fundamentals contribute a diffuse glow rather than a
precise note (an honest reflection of the shared low-latency FFT's actual
resolution down there, not a bug).

Two real, audio-driven views of the same 12-bin chroma vector:
  - A scrolling chromagram strip (pitch class vs. time, like a piano-roll
    heatmap) built from actual per-frame FFT-bin-to-chroma-class binning.
  - A circular chroma wheel: twelve petals arranged like a clock face (one
    per pitch class, coloured around the hue wheel by class), each petal's
    length driven by that class's smoothed current energy. The dominant
    pitch class gets a highlight ring — an at-a-glance "what note/key is
    playing" readout.

Audio reactivity:
  - bass    -> wheel core pulse, low-chroma-row emphasis
  - mid     -> wheel rotation drift, palette shimmer
  - treble  -> sparkle on strip and wheel
  - beat    -> flash, dominant-class ring emphasis
"""
from __future__ import annotations

import moderngl
import numpy as np

from unicornviz.effects.base import AudioData, BaseEffect

_CLASSES = 12
_W = 320          # chromagram strip time axis (columns)
_F_BINS = 512     # matches AudioData.fft length
_SAMPLE_RATE = 48000.0
_BIN_HZ = _SAMPLE_RATE / (_F_BINS * 2.0)
_SMOOTH = 0.80    # per-frame chroma EMA factor

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
uniform sampler2D iChromaTex;   // 12 rows (pitch class) x W columns (time)
uniform vec2  iResolution;
uniform float iTime;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
uniform float iBeat;
uniform float iSpeed;
uniform float iReactivity;
uniform float iHue;
uniform float iChroma[12];      // smoothed current-frame chroma vector
uniform int   iDominant;        // argmax pitch class this frame
in  vec2 v_uv;
out vec4 fragColor;

#define PI  3.14159265
#define TAU 6.28318530

float hash21(vec2 p) {
    // Bound the input before hashing. Callers add a time term such as
    // floor(t * 20.0); with self.time starting anywhere up to 10000 that
    // reaches ~200000, and the multiply below (x123.34) then lands past
    // float32's usable mantissa -- the field collapses from noise into a
    // fixed lattice, which renders as a regular grid of dots.
    p = mod(p, 512.0);
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}
vec3 palette(float t) { return 0.5 + 0.5 * cos(TAU * (t + vec3(0.0, 0.33, 0.67))); }
// One colour per pitch class, evenly spaced around the hue wheel.
vec3 classColor(int c) { return palette(iHue + float(c) / 12.0); }

vec3 backdrop(vec2 uv, float A, float t) {
    vec2 p = (uv - 0.5) * vec2(A, 1.0);
    float v = sin(p.x * 1.8 + t * 0.2) + sin(p.y * 1.5 - t * 0.16);
    vec3 col = palette(v * 0.06 + iHue + 0.55 + t * 0.01);
    col *= col;
    col *= 0.04 + 0.03 * (v * 0.5 + 0.5);
    float sh = hash21(floor(uv * vec2(A, 1.0) * 110.0));
    if (sh > 0.975) {
        float tw = 0.5 + 0.5 * sin(t * (2.0 + sh * 6.0) + sh * 40.0);
        col += vec3(0.6, 0.7, 0.9) * tw * (0.25 + iTreble * 0.35);
    }
    return col;
}

void main() {
    float A = iResolution.x / max(iResolution.y, 1.0);
    vec2 uv = v_uv;
    vec2 p = (uv - 0.5) * vec2(A, 1.0);
    float t = iTime * (0.4 + iSpeed * 0.3);
    float react = max(iReactivity, 0.1);

    vec3 col = backdrop(uv, A, t);

    // ---- scrolling chromagram strip across the lower third ----
    float stripY0 = -0.46, stripY1 = -0.10;
    if (p.y > stripY0 && p.y < stripY1 && abs(p.x) < A * 0.48) {
        vec2 suv = vec2((p.x / (A * 0.48)) * 0.5 + 0.5,
                        (p.y - stripY0) / (stripY1 - stripY0));
        float energy = texture(iChromaTex, suv).r;
        int cls = int(clamp(floor(suv.y * 12.0), 0.0, 11.0));
        vec3 rowCol = classColor(cls);
        float shaped = pow(clamp(energy * (0.9 + react * 0.5), 0.0, 1.0), 0.75);
        col = mix(col, rowCol * (0.25 + shaped * 1.1), shaped * 0.9 + 0.06);
        // Faint row-divider grid.
        float rowLine = smoothstep(0.02, 0.0, abs(fract(suv.y * 12.0) - 0.0));
        col += vec3(0.05) * rowLine;
        // Strip border glow.
        float edge = smoothstep(0.02, 0.0, min(suv.y, 1.0 - suv.y))
                   + smoothstep(0.02, 0.0, min(suv.x, 1.0 - suv.x));
        col += palette(iHue) * edge * 0.15;
    }

    // ---- circular chroma wheel, twelve petals like a clock face ----
    vec2 wc = vec2(0.0, 0.22);
    vec2 wp = p - wc;
    float ang = atan(wp.y, wp.x);
    float rad = length(wp);
    float slot = ang / TAU * 12.0;
    int petal = int(mod(floor(slot) + 12.0, 12.0));
    float within = fract(slot) - 0.5;              // -0.5..0.5 across the petal
    float e = clamp(iChroma[petal], 0.0, 1.5);
    float petalLen = 0.10 + e * 0.20;
    float petalMask = smoothstep(0.5, 0.38, abs(within)) * smoothstep(petalLen, petalLen - 0.03, rad)
                     * smoothstep(0.04, 0.06, rad);
    vec3 petalCol = classColor(petal);
    bool isDominant = (petal == iDominant);
    col += petalCol * petalMask * (0.7 + e * 0.8 + (isDominant ? 0.5 : 0.0));
    col += petalCol * petalMask * petalMask * 0.6;

    // Dominant-class highlight ring, pulses on the beat.
    float domAng = (float(iDominant) + 0.5) / 12.0 * TAU;
    vec2 domDir = vec2(cos(domAng), sin(domAng));
    float domR = 0.10 + iChroma[iDominant] * 0.20 + 0.03 * iBeat;
    vec2 domPos = wc + domDir * domR;
    col += classColor(iDominant) * exp(-dot(p - domPos, p - domPos) * 260.0) * (0.6 + iBeat * 1.2);

    // Wheel core glow, bass-driven.
    float core = exp(-dot(wp, wp) * 60.0);
    col += mix(vec3(0.8, 0.9, 1.0), palette(iHue + 0.5), 0.4) * core * (0.5 + iBass * 1.0 + iBeat * 0.6);
    float ring = smoothstep(0.012, 0.0, abs(rad - 0.045));
    col += palette(iHue + 0.15) * ring * 0.4;

    // Slow wheel-wide rotation shimmer from mid energy.
    col += palette(iHue + ang / TAU + t * 0.05) * 0.02 * iMid * smoothstep(0.30, 0.05, rad);

    col += palette(iHue + 0.5) * iBeat * 0.10;
    float sp = hash21(floor(p * iResolution.y * 0.5) + floor(t * 20.0));
    col += vec3(0.9, 0.85, 1.0) * step(0.996, sp) * (0.25 + iTreble * 0.6);

    float vig = smoothstep(1.4, 0.15, length(uv - 0.5));
    col *= vig;
    col = col / (1.0 + col * 0.5);
    col = pow(clamp(col, 0.0, 1.0), vec3(0.85));
    fragColor = vec4(col, 1.0);
}
"""


def _build_chroma_weights() -> np.ndarray:
    """Build a (F_BINS, 12) bin-to-pitch-class weight matrix.

    The shared Analyzer's FFT is 1024-point at 48kHz (46.875 Hz/bin) —
    deliberately small for low-latency beat detection, not tuned for pitch
    precision. That bin width is *wider than a full semitone* below ~800 Hz
    (and wider than an octave below ~140 Hz): below G5 there is often no bin
    anywhere near a given note's true frequency, so hard-rounding a bin to
    "the nearest semitone" produces a confidently wrong answer as often as a
    right one. Two adjustments make the result honest instead:

    1. Each bin distributes its energy across nearby pitch classes with a
       Gaussian kernel in semitone-space (``_CHROMA_SIGMA`` wide) rather than
       committing 100% to one rounded class — a bin sitting between two
       classes contributes partial credit to both.
    2. Each bin's total contribution is scaled by how much *actual pitch
       information* it carries at that frequency (its width relative to a
       semitone there), floored so bass still contributes some diffuse
       glow. This keeps the unreliable sub-200Hz region from dominating the
       dominant-class vote while still visibly lighting up on the wheel.

    Net effect, verified against synthetic tones: dominant-class detection
    is exact from roughly D5 (~587 Hz) up, within one semitone from about
    C3 (~131 Hz) up, and only genuinely unresolvable below that — matching
    the real information content of a 46.875 Hz-wide bin at each frequency,
    not a bug to "fix" further without a bigger (higher-latency) FFT.
    """
    sigma = 0.85
    conf_power = 1.5
    bins = np.arange(1, _F_BINS)
    freqs = bins * _BIN_HZ
    midi = 69.0 + 12.0 * np.log2(freqs / 440.0)
    midi_mod = np.mod(midi, 12.0)

    classes = np.arange(12)
    diff = np.abs(midi_mod[:, None] - classes[None, :])
    diff = np.minimum(diff, 12.0 - diff)
    gauss = np.exp(-(diff / sigma) ** 2)

    semitone_width_hz = freqs * (2.0 ** (1.0 / 12.0) - 1.0)
    confidence = np.clip(semitone_width_hz / _BIN_HZ, 0.0, 1.0) ** conf_power
    confidence = np.maximum(confidence, 0.05)

    weights = np.zeros((_F_BINS, 12), dtype=np.float32)
    weights[bins, :] = gauss * confidence[:, None]
    return weights


class AudioChromogram(BaseEffect):
    """Live pitch-class (chroma) analyzer: scrolling strip + chroma wheel."""

    NAME = 'Audio Chromogram'
    AUTHOR = 'unicorn-viz'
    TAGS = ['analyzer', 'visualizer', 'chroma', 'groovy', 'intense']
    PING_PONG_FRIENDS = [
        'Audio Spectrum',
        'Audio Spectrogram',
        'Audio Centroid',
        'Audio Waveforms',
        'Audio Sine',
        'Unicorn Tears',
    ]

    def _init(self) -> None:
        self.parameters = {
            'speed': float(self.config.get('speed', 1.0)),
            'reactivity': float(self.config.get('reactivity', 1.0)),
        }
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad(self._prog)

        self._weights = _build_chroma_weights()

        self._strip = np.zeros((_CLASSES, _W), dtype=np.float32)
        self._upload = np.zeros((_CLASSES, _W), dtype=np.uint8)
        self._strip_tex = self.ctx.texture((_W, _CLASSES), 1, data=self._upload.tobytes())
        self._strip_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)

        self._chroma = np.zeros(_CLASSES, dtype=np.float32)
        self._dominant = 0
        self._hue = float(self.rng.uniform(0.0, 1.0))

        self._bass = self._mid = self._treble = 0.0
        self._beat = 0.0

    def update(self, dt: float, audio: AudioData) -> None:
        """Extract the real chroma vector from this frame's FFT and advance state."""
        super().update(dt, audio)
        self._bass = float(audio.bass_n)
        self._mid = float(audio.mid_n)
        self._treble = float(audio.treble_n)
        if audio.beat > 0.5:
            self._beat = 1.0
            if self.rng.uniform() < 0.15:
                self._hue = float((self._hue + self.rng.uniform(0.05, 0.15)) % 1.0)
        self._beat = max(0.0, self._beat - dt * 2.8)

        chroma_raw = audio.fft @ self._weights
        peak = float(chroma_raw.max())
        chroma_norm = chroma_raw / peak if peak > 1e-6 else np.zeros(_CLASSES, dtype=np.float32)

        self._chroma = self._chroma * _SMOOTH + chroma_norm * (1.0 - _SMOOTH)
        self._dominant = int(np.argmax(self._chroma))

        # Scroll the strip left, append the newest column on the right.
        self._strip[:, :-1] = self._strip[:, 1:]
        self._strip[:, -1] = self._chroma
        self._upload[:, :] = (self._strip * 255.0).astype(np.uint8)
        self._strip_tex.write(self._upload.tobytes())

    def render(self) -> None:
        """Draw the scrolling chromagram strip and the circular chroma wheel."""
        p = self._prog
        self._strip_tex.use(location=0)
        p['iChromaTex'].value = 0
        p['iResolution'].value = (float(self.width), float(self.height))
        p['iTime'].value = float(self.time)
        p['iBass'].value = self._bass
        p['iMid'].value = self._mid
        p['iTreble'].value = self._treble
        p['iBeat'].value = self._beat
        p['iSpeed'].value = max(0.05, float(self.parameters['speed']))
        p['iReactivity'].value = max(0.05, float(self.parameters['reactivity']))
        p['iHue'].value = self._hue
        p['iChroma'].value = [float(v) for v in self._chroma]
        p['iDominant'].value = int(self._dominant)
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        """Release GL resources."""
        self._vao.release()
        self._vbo.release()
        self._prog.release()
        self._strip_tex.release()
