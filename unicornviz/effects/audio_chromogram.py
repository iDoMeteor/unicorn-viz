"""Audio Chromogram — real pitch-class (chroma) analysis of the live signal.

A chromagram folds every FFT bin into one of the twelve pitch classes
(C, C#, D, ... B) regardless of octave, by mapping each bin's frequency to
its equal-tempered MIDI note mod 12 (each bin contributes to nearby pitch
classes with a soft weighting, not a hard round — see
``_build_chroma_weights`` for why, and for the real achievable precision at
each frequency). Unlike Audio Spectrogram (which shows raw frequency
content), this reveals the *harmonic/tonal* content — which notes are
actually sounding — so chords and key changes read as clear, distinct colour
patterns instead of a diffuse frequency smear.

Two real, audio-driven views of the same 12-bin chroma vector:
  - A scrolling chromagram strip (pitch class vs. time) across the lower
    third, laid out like a keyboard: naturals on a lighter bed, accidentals
    darker and dash-ruled, so a lane is identifiable without note names.
  - A circular chroma wheel: twelve petals arranged like a clock face (one
    per pitch class, coloured around the hue wheel by class), each petal's
    length driven by that class's smoothed current energy, ringed by
    clock-face ticks — long for naturals, short for accidentals. The
    dominant pitch class gets a highlight ring — an at-a-glance "what
    note/key is playing" readout.

**Two sources, each used only where it is the better one.** The shared
1024-point FFT's 46.875 Hz bins are wider than an octave below ~140 Hz and
carry no pitch information down there at all — which is why this effect used
to describe its own bass end as a diffuse glow. The analyzer's 64-band
perceptual vector is backed below ~190 Hz by its own 8192-point window, about
4.5x finer at 100 Hz, so the FFT is tapered out under ``_BAND_XOVER_HZ`` and
the bands take over. Tapered rather than summed: both sources covering the
same region would simply count the low end twice, which reads as a permanent
bass-heavy tilt.

**The strip carries octave, not just class.** Its second channel is the
energy-weighted octave centroid per class, so a note is drawn at a specific
height *within* its lane — the same pitch class an octave apart lands in the
same lane at a different height. That placement is precisely what the
twelve-row fold throws away, and it is the part the 64-band vector can now
answer.

**It arrives with history already drawn.** An effect only ever sees the
current frame, so this strip used to come up empty and take its whole span to
say anything. :meth:`VJApi.get_recent_pcm_window` hands over the capture's
rolling PCM ring, and one offline pass at activation fills the strip from
audio that already played. Columns are emitted on a fixed time base rather
than once per frame, so the strip spans the same number of seconds at any
frame rate and the pre-filled history sits on the same time axis as the live
columns. All of it is optional: with no app, no audio, or a ring shorter than
the strip, it fills what it can and behaves exactly as it used to.

Audio reactivity:
  - bass    -> wheel core pulse, drip length, strip border
  - mid     -> wheel rotation drift, palette shimmer
  - treble  -> sparkle on strip and wheel
  - beat    -> flash, dominant-class ring, lane-divider and tick pulse
"""
from __future__ import annotations

import moderngl
import numpy as np

from unicornviz.audio.analyzer import PERC_BAND_CENTERS_HZ
from unicornviz.effects.base import AudioData, BaseEffect
from unicornviz.vj_api import VJApi

_CLASSES = 12
_W = 320          # chromagram strip time axis (columns)
_F_BINS = 512     # matches AudioData.fft length
_SAMPLE_RATE = 48000.0
_BIN_HZ = _SAMPLE_RATE / (_F_BINS * 2.0)
_SMOOTH = 0.80    # per-frame chroma EMA factor

# A column is emitted on a fixed time base rather than once per frame. Per
# frame, the strip's span depended on the frame rate -- 5.3s at 60fps, 2.2s at
# 144 -- so the same music scrolled at different speeds on different machines,
# and pre-filled history could not be placed on the same time axis as the live
# columns. At this cadence the strip is always _W / 60 seconds wide.
_COL_DT = 1.0 / 60.0
_STRIP_SECONDS = _W * _COL_DT

# Below this, the shared 1024-point FFT's 46.875 Hz bins are wider than an
# octave and carry no pitch information at all; the 64-band perceptual vector
# is backed down there by the analyzer's own 8192-point window (5.86 Hz bins),
# which is about 4.5x finer at 100 Hz. Above it the short FFT is the finer of
# the two, so each source is used only where it is actually the better one.
_BAND_XOVER_HZ = 190.0

# Octave axis for the strip's second channel, in log2(Hz). Covers the range a
# pitch class can meaningfully be placed in; everything outside is clamped.
_OCT_LO = np.log2(40.0)
_OCT_HI = np.log2(4000.0)

# Prefill resolution. Offline only -- run once at activation, never per frame,
# so the window can be chosen for pitch clarity rather than latency. Measured
# on a C3/E3/G3 triad, triad-to-other separation runs 2.0x at 4096, 3.8x at
# 8192 and 7.2x at 16384; 8192 is taken because it matches the analyzer's own
# long window and holds the time smear to 171ms, where 16384's 341ms would
# blur the history into flat horizontal bands at a 16.7ms column hop.
_PREFILL_N_FFT = 8192

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
                                //   .r = class energy, .g = octave position
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
// The five black keys of an octave, for markings that read as a keyboard.
bool isAccidental(int c) {
    return c == 1 || c == 3 || c == 6 || c == 8 || c == 10;
}

vec3 backdrop(vec2 uv, float A, float t) {
    vec2 p = (uv - 0.5) * vec2(A, 1.0);
    float v = sin(p.x * 1.8 + t * 0.2) + sin(p.y * 1.5 - t * 0.16);
    vec3 col = palette(v * 0.06 + iHue + 0.55 + t * 0.01);
    col *= col;
    col *= 0.04 + 0.03 * (v * 0.5 + 0.5);
    // Stars: a soft round point placed inside its cell. Filling the whole
    // cell instead -- a bare threshold on the cell hash -- is what renders
    // as a field of hard little squares.
    vec2 scell = p * 110.0;
    vec2 sg = floor(scell);
    float sh = hash21(sg);
    if (sh > 0.975) {
        vec2 sd = fract(scell) - vec2(hash21(sg + 5.3), hash21(sg + 9.1));
        float tw = 0.5 + 0.5 * sin(t * (2.0 + sh * 6.0) + sh * 40.0);
        col += vec3(0.6, 0.7, 0.9) * exp(-dot(sd, sd) * 26.0) * tw
             * (0.25 + iTreble * 0.35 + 0.05);
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
        float lane = suv.y * 12.0;
        int cls = int(clamp(floor(lane), 0.0, 11.0));
        float within = fract(lane);              // 0..1 up the lane
        vec4 cell = texture(iChromaTex, suv);
        float energy = cell.r;
        float octave = cell.g;
        vec3 rowCol = classColor(cls);
        float livePulse = clamp(iChroma[cls], 0.0, 1.5);

        // Accidentals -- the piano's black keys -- sit on a darker bed, so the
        // twelve lanes read as a keyboard instead of twelve identical stripes.
        bool sharp = isAccidental(cls);
        col = mix(col, rowCol * 0.055, sharp ? 0.55 : 0.28);

        // The note itself is placed *within* its lane by octave, not smeared
        // across the whole of it: the same pitch class an octave apart lands
        // at a different height. That is the part the twelve-row fold throws
        // away, and what the 64-band vector is here to put back.
        // Shaped harder than the old 0.75 gamma: at 0.75 almost every lane
        // sat near full and the strip read as a colour chart, which buried the
        // octave placement this channel exists to show.
        float shaped = pow(clamp(energy * (0.75 + react * 0.35), 0.0, 1.0), 1.9);
        float blob = exp(-pow((within - octave) * 5.2, 2.0));
        // A faint full-lane floor keeps quiet notes on the map; the blob is
        // what actually carries the note, so it is the dominant term.
        float body = shaped * (0.10 + blob * 1.25);
        col = mix(col, rowCol * (0.10 + shaped * 0.75), clamp(body, 0.0, 1.0) * 0.80);
        col += rowCol * blob * shaped * shaped * (0.55 + livePulse * 0.85);

        // Drips: a bright cell bleeds downward and fades, so loud notes hang
        // off their own lane instead of stopping at a hard edge.
        float dripSrc = texture(iChromaTex, vec2(suv.x, suv.y + 0.055)).r;
        float dripFall = smoothstep(0.0, 0.055, suv.y + 0.055 - (float(cls) + 1.0) / 12.0);
        col += rowCol * pow(clamp(dripSrc, 0.0, 1.0), 3.0) * dripFall * 0.40
             * (0.4 + iBass * 0.7);

        // Lane dividers pulse with that class's live energy rather than
        // sitting at a flat grey -- the markings answer the music too.
        float divider = smoothstep(0.030, 0.0, abs(within));
        col += mix(vec3(0.10), rowCol, 0.75) * divider
             * (0.10 + livePulse * 0.9 + iBeat * 0.20);
        // Accidental lanes get a dashed rule so they are identifiable at a
        // glance without needing note names.
        if (sharp) {
            float dash = step(0.55, fract(suv.x * 90.0));
            col += rowCol * divider * dash * 0.5;
        }

        // Sparkle on the hot cells only.
        vec2 spcell = vec2(suv.x * 260.0, lane * 5.0);
        vec2 spg2 = floor(spcell) + floor(t * 14.0);
        if (hash21(spg2) > 0.90) {
            vec2 spd2 = fract(spcell) - vec2(hash21(spg2 + 4.1), hash21(spg2 + 8.3));
            col += vec3(1.0) * exp(-dot(spd2, spd2) * 22.0)
                 * pow(shaped, 2.0) * (0.5 + iTreble * 1.4);
        }

        // The playhead: newest data lands at the right edge, and it burns.
        float head = smoothstep(0.012, 0.0, 1.0 - suv.x);
        col += mix(palette(iHue + 0.5), vec3(1.0), 0.45) * head
             * (0.55 + livePulse * 1.6 + iBeat * 0.9);

        // Strip border glow, pulsing on the beat.
        float edge = smoothstep(0.02, 0.0, min(suv.y, 1.0 - suv.y))
                   + smoothstep(0.02, 0.0, min(suv.x, 1.0 - suv.x));
        col += palette(iHue) * edge * (0.15 + iBeat * 0.30 + iBass * 0.20);
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
    // Neon rim along the petal's leading edge, so a petal has an edge to
    // catch the light instead of fading out into the backdrop.
    float rimMask = smoothstep(0.5, 0.38, abs(within))
                  * smoothstep(0.016, 0.0, abs(rad - petalLen))
                  * smoothstep(0.04, 0.06, rad);
    col += mix(petalCol, vec3(1.0), 0.4) * rimMask
         * (0.6 + e * 1.4 + (isDominant ? 0.8 : 0.0) + iBeat * 0.5);

    // Dominant-class highlight ring, pulses on the beat.
    float domAng = (float(iDominant) + 0.5) / 12.0 * TAU;
    vec2 domDir = vec2(cos(domAng), sin(domAng));
    float domR = 0.10 + iChroma[iDominant] * 0.20 + 0.03 * iBeat;
    vec2 domPos = wc + domDir * domR;
    col += classColor(iDominant) * exp(-dot(p - domPos, p - domPos) * 260.0) * (0.6 + iBeat * 1.2);

    // Clock-face tick marks at the twelve class boundaries -- long for the
    // naturals, short for the accidentals, so the wheel can be read as a
    // keyboard wrapped into a circle.
    if (rad > 0.055 && rad < 0.365) {
        float tickSlot = ang / TAU * 12.0;
        int tickCls = int(mod(floor(tickSlot + 0.5) + 12.0, 12.0));
        float toTick = abs(fract(tickSlot + 0.5) - 0.5);
        float tickLen = isAccidental(tickCls) ? 0.055 : 0.095;
        float tickMask = smoothstep(0.035, 0.0, toTick)
                       * smoothstep(0.325 - tickLen, 0.325, rad)
                       * smoothstep(0.365, 0.345, rad);
        col += mix(vec3(0.55), classColor(tickCls), 0.65) * tickMask
             * (0.35 + clamp(iChroma[tickCls], 0.0, 1.5) * 1.1 + iBeat * 0.30);
    }

    // Wheel core glow, bass-driven.
    float core = exp(-dot(wp, wp) * 60.0);
    col += mix(vec3(0.8, 0.9, 1.0), palette(iHue + 0.5), 0.4) * core * (0.5 + iBass * 1.0 + iBeat * 0.6);
    float ring = smoothstep(0.012, 0.0, abs(rad - 0.045));
    col += palette(iHue + 0.15) * ring * 0.4;

    // Slow wheel-wide rotation shimmer from mid energy.
    col += palette(iHue + ang / TAU + t * 0.05) * 0.02 * iMid * smoothstep(0.30, 0.05, rad);

    col += palette(iHue + 0.5) * iBeat * 0.10;
    // Sparkle: a round mote placed inside its cell. A bare threshold fills
    // the whole cell instead, which is what reads as hard little squares.
    vec2 spc = p * iResolution.y * 0.25;
    vec2 spg = floor(spc) + floor(t * 20.0);
    float sp = hash21(spg);
    if (sp > 0.987) {
        vec2 spd = fract(spc) - vec2(hash21(spg + 2.7), hash21(spg + 6.1));
        col += vec3(0.9, 0.85, 1.0) * exp(-dot(spd, spd) * 30.0)
             * (0.25 + iTreble * 0.6);
    }

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


def _prefill_weights(freqs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Bin-to-class weights and per-bin octave for the offline prefill FFT.

    Same Gaussian-in-semitone-space shape as the live paths, but without their
    confidence taper: at this FFT size the bins genuinely resolve a semitone
    across the whole range the strip plots, so there is nothing to discount.
    """
    usable = freqs > 20.0
    midi_mod = np.zeros_like(freqs)
    midi_mod[usable] = np.mod(
        69.0 + 12.0 * np.log2(freqs[usable] / 440.0), 12.0)
    diff = np.abs(midi_mod[:, None] - np.arange(_CLASSES)[None, :])
    diff = np.minimum(diff, 12.0 - diff)
    weights = np.exp(-(diff / 0.7) ** 2).astype(np.float32)
    weights[~usable, :] = 0.0
    bin_oct = np.log2(np.maximum(freqs, 1.0)).astype(np.float32)
    return weights, bin_oct


def _build_band_chroma_weights() -> np.ndarray:
    """Build a (64, 12) perceptual-band-to-pitch-class weight matrix.

    Used only for bands below ``_BAND_XOVER_HZ``. Down there the shared short
    FFT cannot resolve pitch at all -- its bin is wider than an octave below
    ~140 Hz -- while the 64-band vector is fed by the analyzer's long window
    and carries real structure. The same Gaussian-in-semitone-space and
    confidence weighting as :func:`_build_chroma_weights` applies, for the same
    reason: a band is still about 1.7 semitones wide, so committing its whole
    energy to one rounded class would be a confident guess, not a measurement.
    """
    centers = np.asarray(PERC_BAND_CENTERS_HZ, dtype=np.float64)
    weights = np.zeros((centers.size, _CLASSES), dtype=np.float32)
    usable = centers < _BAND_XOVER_HZ
    if not usable.any():
        return weights

    f = centers[usable]
    midi_mod = np.mod(69.0 + 12.0 * np.log2(f / 440.0), 12.0)
    diff = np.abs(midi_mod[:, None] - np.arange(_CLASSES)[None, :])
    diff = np.minimum(diff, 12.0 - diff)
    gauss = np.exp(-(diff / 0.85) ** 2)

    # How much of a semitone this band actually resolves, on the same footing
    # as the FFT path's confidence term.
    band_ratio = 2.0 ** (np.log2(16000.0 / 30.0) / centers.size)
    band_width = f * (band_ratio - 1.0)
    semitone_width = f * (2.0 ** (1.0 / 12.0) - 1.0)
    confidence = np.clip(semitone_width / band_width, 0.0, 1.0) ** 1.5
    confidence = np.maximum(confidence, 0.05)

    weights[usable, :] = gauss * confidence[:, None]
    return weights


def _fft_low_rolloff() -> np.ndarray:
    """Per-bin taper that hands the sub-``_BAND_XOVER_HZ`` region to the bands.

    Without it both sources would contribute down there and the low end would
    simply count twice, which reads as a permanent bass-heavy tilt across the
    whole strip.
    """
    freqs = np.arange(_F_BINS, dtype=np.float64) * _BIN_HZ
    return np.clip((freqs - _BAND_XOVER_HZ * 0.6)
                   / (_BAND_XOVER_HZ * 0.8), 0.0, 1.0).astype(np.float32)


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
        self._band_weights = _build_band_chroma_weights()
        self._fft_rolloff = _fft_low_rolloff()
        # Where each source's energy sits on the octave axis, for the strip's
        # second channel.
        self._fft_oct = np.log2(
            np.maximum(np.arange(_F_BINS, dtype=np.float64) * _BIN_HZ, 1.0),
        ).astype(np.float32)
        self._band_oct = np.log2(
            np.asarray(PERC_BAND_CENTERS_HZ, dtype=np.float64),
        ).astype(np.float32)

        # Two channels per cell: R is the class's energy, G is where that
        # energy sits on the octave axis. The octave is the part the 12-row
        # fold throws away, and it is what the 64-band vector can now answer.
        self._strip = np.zeros((_CLASSES, _W, 2), dtype=np.float32)
        self._upload = np.zeros((_CLASSES, _W, 2), dtype=np.uint8)
        self._strip_tex = self.ctx.texture(
            (_W, _CLASSES), 2, data=self._upload.tobytes())
        self._strip_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)

        self._chroma = np.zeros(_CLASSES, dtype=np.float32)
        self._octave = np.full(_CLASSES, 0.5, dtype=np.float32)
        self._dominant = 0
        self._hue = float(self.rng.uniform(0.0, 1.0))

        self._bass = self._mid = self._treble = 0.0
        self._beat = 0.0
        self._col_acc = 0.0
        self._prefilled = 0
        self._prefill()
        self._strip_tex.write(self._upload.tobytes())

    def _push_column(self, chroma: np.ndarray, octave: np.ndarray) -> None:
        """Scroll the strip left and append one column on the right."""
        self._strip[:, :-1] = self._strip[:, 1:]
        self._strip[:, -1, 0] = chroma
        self._strip[:, -1, 1] = octave

    def _prefill(self) -> None:
        """Fill the strip from audio that already played, before activation.

        An effect only ever sees the current frame, so this strip used to come
        up empty and take its full span to say anything. The capture keeps a
        rolling PCM ring; :meth:`VJApi.get_recent_pcm_window` hands it over, and
        one offline pass over it arrives with the history already drawn.

        The analysis here is a single high-resolution FFT per column rather than
        the live path's two sources, because offline there is no reason to use
        the low-latency window: the ring is raw PCM and cost does not matter.
        That makes the pre-filled region slightly better resolved than the live
        columns, not worse. It is normalised identically, so the two read as one
        continuous image.

        Entirely optional -- no app, no audio, a short ring, or any failure just
        leaves the strip as empty as it used to be.
        """
        api = VJApi.current()
        if api is None:
            return
        try:
            got = api.get_recent_pcm_window(_STRIP_SECONDS)
        except Exception:      # noqa: BLE001 - history is never load-bearing
            return
        if not got:
            return
        pcm, sample_rate = got
        pcm = np.asarray(pcm, dtype=np.float32)
        sample_rate = int(sample_rate)
        hop = max(1, int(round(_COL_DT * sample_rate)))
        if pcm.size < _PREFILL_N_FFT + hop or sample_rate <= 0:
            return

        freqs = np.fft.rfftfreq(_PREFILL_N_FFT, 1.0 / sample_rate)
        weights, bin_oct = _prefill_weights(freqs)
        window = np.hanning(_PREFILL_N_FFT).astype(np.float32)

        # Only as many columns as the ring actually holds, newest flush right.
        usable = (pcm.size - _PREFILL_N_FFT) // hop
        cols = int(min(_W, usable))
        if cols <= 0:
            return
        for i in range(cols):
            end = pcm.size - (cols - 1 - i) * hop
            block = pcm[end - _PREFILL_N_FFT:end]
            mag = np.abs(np.fft.rfft(block * window)).astype(np.float32)
            raw = mag @ weights
            oct_c = np.full(_CLASSES, 0.5, dtype=np.float32)
            live = raw > 1e-6
            if live.any():
                num = (mag * bin_oct) @ weights
                oct_c[live] = np.clip(
                    (num[live] / raw[live] - _OCT_LO) / (_OCT_HI - _OCT_LO),
                    0.0, 1.0)
            peak = float(raw.max())
            self._push_column(
                raw / peak if peak > 1e-6 else np.zeros(_CLASSES, dtype=np.float32),
                oct_c)
        self._prefilled = cols

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

        # Each source only where it is the better one: the short FFT tapers
        # out below _BAND_XOVER_HZ and the 64-band vector takes over, so the
        # low end is measured once rather than counted twice.
        e_fft = audio.fft * self._fft_rolloff
        e_band = audio.bands
        chroma_raw = e_fft @ self._weights + e_band @ self._band_weights

        # Octave centroid per class, from the same weighting that produced the
        # energy -- so a bass note and the same note two octaves up land in the
        # same lane but at different heights within it.
        num = ((e_fft * self._fft_oct) @ self._weights
               + (e_band * self._band_oct) @ self._band_weights)
        octave = np.full(_CLASSES, 0.5, dtype=np.float32)
        live = chroma_raw > 1e-6
        if live.any():
            octave[live] = np.clip(
                (num[live] / chroma_raw[live] - _OCT_LO) / (_OCT_HI - _OCT_LO),
                0.0, 1.0)

        peak = float(chroma_raw.max())
        chroma_norm = (chroma_raw / peak if peak > 1e-6
                       else np.zeros(_CLASSES, dtype=np.float32))

        self._chroma = self._chroma * _SMOOTH + chroma_norm * (1.0 - _SMOOTH)
        self._octave = self._octave * _SMOOTH + octave * (1.0 - _SMOOTH)
        self._dominant = int(np.argmax(self._chroma))

        # Columns are emitted on a fixed time base, not once per frame, so the
        # strip spans the same number of seconds at any frame rate. The cap
        # stops a stalled frame from flushing the whole strip in one go.
        self._col_acc += dt
        pushed = 0
        while self._col_acc >= _COL_DT and pushed < 8:
            self._col_acc -= _COL_DT
            self._push_column(self._chroma, self._octave)
            pushed += 1
        if pushed:
            self._col_acc = min(self._col_acc, _COL_DT)
            np.multiply(self._strip, 255.0, out=self._upload, casting='unsafe')
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
