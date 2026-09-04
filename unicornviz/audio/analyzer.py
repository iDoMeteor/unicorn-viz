"""
FFT analyzer + beat detector.
Consumes PCM blocks from AudioCapture and produces AudioData snapshots.

P1: Analyzer now maintains an internal onset event queue.  Call
    ``drain_onsets()`` each frame to retrieve timestamped ``OnsetEvent``
    objects.  ``data.beat`` is still set for backward-compat with effects.

P2: The flux adaptive threshold uses a time-based envelope ring (100 Hz
    internal rate) and a MAD-based threshold, replacing the old fixed-count
    ``mean + std`` approach which collapsed on steady material.

P3: ``set_expected_bpm(bpm, confidence)`` lets the BeatTracker feed back its
    current estimate so the analyzer can gate the refractory window to ~70%
    of the beat period, starving sub-beat IOI pollution.

H9 fix: ``process(pcm, t=None)`` accepts an optional audio-time argument.
    Defaults to ``time.monotonic()`` for live use.  Pass ``t = block_idx *
    dt`` from the offline harness to decouple timing from wall-clock speed.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from unicornviz.effects.base import AudioData
from unicornviz.audio.profiles import AudioProfile, get_profile

log = logging.getLogger(__name__)

_FFT_BANDS = 512
_SMOOTHING = 0.75          # exponential smoothing coefficient
# 2026-08-14: fallback/default only -- never trust this as "the" rate. It was
# a hardcoded constant used directly everywhere below, never reconciled with
# AudioCapture's actual detected device rate (AudioManager.sample_rate,
# capture.py's _open_stream() already queries the real device and can land
# on 44100 or other rates, not just 48000). Found auditing a live session
# where a ~7-13 BPM overshoot was suspected to be a sample-rate mismatch --
# that specific incident turned out NOT to be this (the device really was
# 48000 Hz all night, confirmed from the session log), but the mismatch
# risk itself was real and latent. See Analyzer.set_sample_rate() below and
# docs/adr/vj-system.md.
_ASSUMED_SAMPLE_RATE = 48000

# Mid/side vocal-presence feature (2026-09-01). Replaces the failed
# hnr/fmr heuristics' MEASUREMENT role (those never separated
# instrumentals from acapellas — instrumentals read HIGHER; audit in
# the 2026-08-31 experiment ledger). Physics: lead vocals are
# center-panned mono, so the MID fraction of vocal-band energy — and
# its syllable-rate (2-8 Hz) modulation — tracks mix-vocal presence.
# Validated offline: held-out AUC ~0.75 on vocal-mix vs instrumental
# with correct population ordering (instrumentals < mixes <
# acapellas). An honest ~0.75-class instrument: usable as a soft
# population-level signal, not a per-track oracle. Requires stereo
# capture (side channel from AudioCapture); reports invalid on mono.
_VOCAL_MS_BAND_HZ = (200.0, 4000.0)
_VOCAL_MS_RING = 2048            # ~22 s of envelope at 93.75 blocks/s
_VOCAL_MS_RECOMPUTE_FRAMES = 188  # ~2 s cadence, matches fmr pattern
_VOCAL_MS_MOD_BAND_HZ = (2.0, 8.0)    # syllable-rate modulation
_VOCAL_MS_MOD_TOTAL_HZ = (0.5, 20.0)

# Spectral contrast (2026-09-01, owner-directed): per octave-ish band,
# the log gap between spectral PEAKS and the VALLEYS between them.
# Harmonic-rich material (clean leads, vocals) has tall peaks over
# quiet valleys -> high contrast; dense/noisy material (growls,
# distortion walls) fills the valleys -> low. Measures peakiness —
# something centroid/zcr/bands (where energy sits) never captured.
# DORMANT downstream by design: the recommender term ships at weight
# 0.0 with every profile mu unset until the library bake-off fits it.
_CONTRAST_BAND_EDGES_HZ = (200.0, 400.0, 800.0, 1600.0, 3200.0, 6400.0, 12800.0)
_CONTRAST_QUANTILE = 0.2               # top/bottom share defining peak/valley

# 2026-08-11: detector-facing _shape() gains -- see AudioData.bass_det's own
# field comment (unicornviz/effects/base.py) for why these exist as a
# separate channel from bass/mid/treble's effects-facing gains below.
# Grounded empirically (inverted real bass/mid/treble values from a real
# session, unicornviz/audio/profiles.py's curve unchanged, back to their
# pre-_shape() input, then swept candidate gains for the one maximizing
# cross-director-mode median separation): bass's current effects gain
# (6.6) was found badly mistuned for this purpose -- only 1.7 percentage
# points of median separation between BREAKDOWN and CRUISE -- with 2.0
# empirically best on that data (6.8pp, ~4x better). mid (5.8) and treble
# (7.2) were checked the same way and found ALREADY well-tuned for this --
# every lower gain tested gave less separation, not more -- so their
# detector-facing gains currently just mirror the effects ones rather than
# introducing an unneeded second constant. See
# docs/planning/auto-vj-drop-score-redesign-plan-2026-08-11.md.
_DETECTOR_BASS_GAIN = 2.0
_DETECTOR_MID_GAIN = 5.8
_DETECTOR_TREBLE_GAIN = 7.2

# 64 log-spaced perceptual bands shared across all consumers (effects + auto-VJ).
# Matches audio_spectrum.py exactly: 30 Hz – 16 kHz, 64 bands, raw (no visual gain).
_PERC_N_BANDS = 64
_PERC_F_MIN = 30.0
_PERC_F_MAX = 16_000.0

# Low-band resolution fix (2026-09-04) -- see Analyzer.__init__'s own
# comment on self._low_band_pcm for the full diagnosis. 8192 samples
# (170.7ms at 48kHz) leaves only the bottom ~2 of 64 bands still sharing
# an FFT bin, down from 19 at the short path's 1024-sample window --
# chosen over doubling (4096, still 7 collapsed) and over widening the
# SHARED short window that every effect's transient response depends on.
_LOW_BAND_N_FFT = 8192
# Number of low bands (0-indexed, exclusive upper bound) replaced by the
# long-window analysis -- matches exactly how many bands collapse under
# the SHORT path's own 1024-sample window at 48kHz (verified directly
# against _recompute_band_edges()'s own construction, not eyeballed).
_LOW_BAND_REPLACE_N = 25

# 2026-08-11: public (not underscore-prefixed) geometric-mean center
# frequency of each of the 64 bands above, Hz -- the same formula
# tools/gen_spectral_fingerprints.py uses to derive AudioProfile's
# spectral_centroid_mu from expected_bands (centroid = dot(centers, vec) /
# sum(vec)). Exposed so other consumers can compute a spectral centroid in
# THIS weighting basis (log-spaced bands, relative-magnitude vector) rather
# than a raw linear-FFT-bin centroid, which is a structurally different
# formula from what spectral_centroid_mu represents -- see
# docs/adr/vj-system.md "Recommender centroid_fit Weight Cut + tech_house
# Disabled" for the bug this exists to let callers avoid. First consumer:
# drop-ins/auto-vj-01/auto_vj.py's _update_profile_recommendation().
_perc_edges_hz = np.logspace(np.log10(_PERC_F_MIN), np.log10(_PERC_F_MAX), _PERC_N_BANDS + 1)
PERC_BAND_CENTERS_HZ: np.ndarray = np.sqrt(_perc_edges_hz[:-1] * _perc_edges_hz[1:])

_BASS_HZ = (40.0, 180.0)
_LOW_MID_HZ = (180.0, 700.0)
_MID_HZ = (700.0, 3200.0)
_TREBLE_HZ = (3200.0, 12000.0)
_AIR_HZ = (12000.0, 18000.0)

# P2 — time-based onset envelope
_ENV_RATE = 100.0           # Hz; independent of render FPS
_ENV_WINDOW_S = 1.5         # seconds of flux history
_ENV_LEN = int(_ENV_RATE * _ENV_WINDOW_S)   # 150 samples
_BEAT_MAD_K = 1.80          # threshold = median + k * MAD
_BEAT_ABS_FLOOR = 0.02      # minimum absolute threshold (silences silence triggers)
# 2026-08-17: onset-strength cap, a defense-in-depth backstop independent
# of the mad floor fix below -- see that constant's own comment for the
# live incident (onset_strength_max_raw hit 1,171,176,147 in a real
# session). Bounds `strength` regardless of *why* it got large (this
# floor's own edge cases, a genuine clipping/dropout transient, anything
# not anticipated here), without touching legitimate strong-vs-weak
# ordering: tools/onset_strength_mad_floor_harness.py's scenario 1 showed
# the floor fix alone already tames the pathological case to ~48-97, so
# 50.0 sits comfortably above every realistic value while still bounding
# the unanticipated case. Downstream, _pulse_envelope() (beat_grid.py)
# log-compresses on top of this anyway -- the cap protects every OTHER
# consumer of raw strength (e.g. _absorb_onset(), training-corpus
# logging) that isn't compression-protected.
_ONSET_STRENGTH_CAP = 50.0

# Vocal-presence heuristics (Auto VJ profile recommender). Neither vocal_hnr
# nor vocal_fmr is a true vocal detector -- see AudioData docstring comments
# in unicornviz/effects/base.py for the caveats. Formant band matches the
# range used across the [audio] profile literature-grounded fingerprints.
_VOCAL_HZ = (300.0, 3400.0)
_VOCAL_HNR_MIN_LAG_BINS = 2   # skip lag 0/1: dominated by envelope shape, not harmonic spacing

# FMR: track the vocal-band energy envelope at a coarse rate over a short
# window, then look for modulation energy concentrated in the syllabic/
# vibrato rate band (3-8 Hz) vs. the rest of the modulation spectrum.
_VOCAL_ENV_RATE = 40.0
_VOCAL_ENV_WINDOW_S = 2.0
_VOCAL_ENV_LEN = int(_VOCAL_ENV_RATE * _VOCAL_ENV_WINDOW_S)   # 80 samples
_VOCAL_FMR_HZ = (3.0, 8.0)
_VOCAL_FMR_RECOMPUTE_FRAMES = 8   # throttle the modulation FFT; ~130-190ms at typical block sizes


def _princarg(phase: np.ndarray) -> np.ndarray:
    """Wrap phase (radians) into (-pi, pi] -- used by the complex-domain
    onset function's constant-phase-advance prediction (see
    Analyzer._compute_complex_onset_flux)."""
    return np.mod(phase + np.pi, 2.0 * np.pi) - np.pi


@dataclass(frozen=True)
class OnsetEvent:
    """A detected onset with audio-time timestamp and relative strength.

    2026-08-14: ``band_weight`` added for BeatTracker's strength/band-
    weighted phase coherence (see beat_grid.py's ``_absorb_onset()``) --
    the fraction of this onset's flux that came from the bass/kick band,
    0..1. Defaults to 1.0 (fully bass-attributed) for any caller that
    constructs an ``OnsetEvent`` without it, matching this field's
    absence in the pre-2026-08-14 behavior, where every onset was treated
    as equally diagnostic of phase regardless of which band triggered it.
    """

    t: float                    # audio time (seconds) at detection
    strength: float              # z-score above adaptive threshold (>= 1.0)
    band_weight: float = 1.0     # fraction of this onset's flux from the bass band, 0..1


class Analyzer:
    """
    Call ``process(pcm)`` each frame (pcm = float32 mono array).
    Returns an ``AudioData`` snapshot.

    Extended interface (additive — does not break existing callers):

    ``drain_onsets() -> list[OnsetEvent]``
        Returns and clears all onset events queued since the last call.
        Thread-safe: call only from the main render thread.

    ``set_expected_bpm(bpm, confidence) -> None``
        Hint from the BeatTracker: tune the refractory window around bpm.
        Safe to call every frame; ignored when bpm <= 0 or confidence < 0.5.

    ``process(pcm, t=None) -> AudioData``
        t: optional audio-time in seconds (for offline / harness use).
        Defaults to time.monotonic() when None.
    """

    def __init__(
        self,
        fft_bands: int = _FFT_BANDS,
        profile: object = None,
        silence_rms_floor: float = 0.0060,
        silence_rms_span: float = 0.045,
    ) -> None:
        if profile is None:
            profile = get_profile("house")
        self._profile = profile
        self._bands = fft_bands
        self._smoothed = np.zeros(fft_bands, dtype=np.float32)
        self._window_cache: dict[int, np.ndarray] = {}
        self._prev_spectrum = np.zeros(fft_bands, dtype=np.float32)
        self._flux_delta = np.zeros(fft_bands, dtype=np.float32)
        self._prev_rms = 0.0
        # Complex-domain onset function (2026-09-04, Program B step 3
        # continuation) -- two-frame magnitude/phase history for the
        # phase-and-energy prediction (Bello et al. 2004 section III):
        # frame n needs frames n-1 and n-2 to predict its own complex
        # spectrum. See _compute_complex_onset_flux()'s own docstring.
        self._complex_onset_mag_prev = np.zeros(fft_bands, dtype=np.float64)
        self._complex_onset_mag_prev2 = np.zeros(fft_bands, dtype=np.float64)
        self._complex_onset_phase_prev = np.zeros(fft_bands, dtype=np.float64)
        self._complex_onset_phase_prev2 = np.zeros(fft_bands, dtype=np.float64)
        self._complex_onset_frames_seen = 0
        # Silence gate parameters. ``silence_rms_floor`` is the RMS level below
        # which the analyzer treats the input as silent (no spectrum, no
        # onsets). ``silence_rms_span`` is the additional RMS range over which
        # the spectrum scales from 0 → 1.  Defaults raised from 0.0015 / 0.05
        # so PipeWire monitor noise / ambient room hum does not register as
        # signal when no music is playing.  Tunable via [audio] in config.toml.
        self._silence_rms_floor: float = max(0.0, float(silence_rms_floor))
        self._silence_rms_span: float = max(1e-4, float(silence_rms_span))
        # Last raw input RMS (pre-gate). Exposed for HUD diagnostics so the
        # user can tell at a glance whether the input is actually silent or
        # just quiet.
        self._last_raw_rms: float = 0.0
        self._last_audio_time: float = 0.0

        # P2 — time-based onset envelope (replaces fixed-count _flux_history)
        self._env_buf: np.ndarray = np.zeros(_ENV_LEN, dtype=np.float32)
        self._env_write_idx: int = 0
        self._env_t_acc: float = 0.0
        self._env_prev_flux: float = 0.0  # for local-max peak detection
        self._env_filled: bool = False

        # P1 — onset event queue
        self._onset_queue: deque[OnsetEvent] = deque(maxlen=256)

        # Vocal-presence heuristics (see _VOCAL_HZ / AudioData docstring).
        self._vocal_slice: slice = slice(0, 1)
        self._vocal_env_buf: np.ndarray = np.zeros(_VOCAL_ENV_LEN, dtype=np.float32)
        self._vocal_env_write_idx: int = 0
        self._vocal_env_t_acc: float = 0.0
        self._vocal_env_filled: bool = False
        self._vocal_fmr_cached: float = 0.0
        self._vocal_fmr_frame_count: int = 0
        # Mid/side vocal-presence state (see _VOCAL_MS_* constants).
        self._vocal_ms_ring: deque[float] = deque(maxlen=_VOCAL_MS_RING)
        self._vocal_ms_frame_count: int = 0
        self._vocal_mid_ratio_cached: float = 0.0
        self._vocal_syl_cached: float = 0.0
        self._vocal_ms_valid: bool = False
        self._vocal_ms_frate: float = float(_ASSUMED_SAMPLE_RATE) / 512.0
        self._side_spectrum_work = np.zeros(self._bands, dtype=np.float32)
        # Spectral-contrast state: EMA-smoothed scalar (mean over bands).
        self._spectral_contrast_ema: float = 0.0

        # P3 — adaptive refractory (set by BeatTracker via set_expected_bpm)
        self._refractory_s: float | None = None
        self._beat_cooldown_until_t: float = -1e9
        # 2026-08-09 fix: set_expected_bpm() derived _refractory_s from its
        # bpm argument but never stored the value itself, so data.bpm (see
        # process() below) had nothing to read and stayed at AudioData's
        # constructor default (120.0) forever -- every effect reading
        # audio.bpm saw a constant, regardless of the real track tempo.
        # Same default as AudioData.bpm so a cold start / no-feedback-yet
        # session is bit-for-bit unchanged from before this fix.
        self._expected_bpm: float = 120.0

        # Per-band running z-score normalisation state.
        # Updated every frame so bass_n/mid_n/treble_n track relative change
        # rather than absolute level — useful when a genre keeps one band
        # near saturation the whole session.
        self._band_mean_bass: float = 0.0
        self._band_var_bass: float = 1e-4
        self._band_mean_mid: float = 0.0
        self._band_var_mid: float = 1e-4
        self._band_mean_treble: float = 0.0
        self._band_var_treble: float = 1e-4
        self._band_alpha: float = 0.08  # EMA coefficient for running stats

        # 2026-08-14: real device sample rate, synced by AudioManager via
        # set_sample_rate() once capture is live (and on every subsequent
        # frame, in case of a mid-session device/fallback switch -- the sync
        # call is a cheap early-return no-op when the rate hasn't changed).
        # Starts at the module-level fallback since the real rate isn't
        # known yet at construction time. See _ASSUMED_SAMPLE_RATE's own
        # comment and docs/adr/vj-system.md.
        self._sample_rate: int = _ASSUMED_SAMPLE_RATE

        self._n_fft = self._bands * 2
        self._bin_hz = self._sample_rate / max(1, self._n_fft)

        # Wave 3.1 — scratch buffers to avoid per-frame heap allocation
        self._spectrum_work: np.ndarray = np.zeros(fft_bands, dtype=np.float32)
        self._windowed_buf: np.ndarray = np.zeros(1024, dtype=np.float32)

        self._perc_work: np.ndarray = np.zeros(_PERC_N_BANDS, dtype=np.float32)

        # Low-band resolution fix (2026-09-04): the short FFT above (1024
        # samples at 48kHz -- 46.875 Hz/bin) cannot resolve the bottom of
        # the 64 log-spaced bands at all -- 19 of 64 collapse onto a
        # shared FFT bin (bands 0-8 ALL read the exact same bin, every
        # frame, for every track, regardless of genre), which is not
        # measurement noise, it's zero information, replicated and fed
        # into every downstream consumer (effects, spectral_shape_fit's
        # fingerprint matching) as if it were real per-band texture. Found
        # live diagnosing why every profile's data-derived expected_bands
        # fingerprint looked nearly identical to every other one
        # (>=0.94 cosine-similar across the whole roster) -- traced to
        # this, not a feature-ceiling problem. Fixed WITHOUT touching the
        # short FFT's own 21ms window (owner: effects were designed
        # assuming these numbers are real; widening the shared window
        # would slow every effect's transient response, worst at fast
        # BPM genres where a beat subdivision is already short) -- see
        # docs/adr/vj-system.md "Low-Band Resolution: Dual-Window Fix"
        # for the full option comparison (widen vs. dual-window vs.
        # constant-Q) and why this one was chosen.
        #
        # Second, dedicated, LOW-CADENCE-EQUIVALENT FFT (long window,
        # same per-tick cost as the fast path since a 8192-pt real FFT is
        # microseconds in numpy -- "slow" refers to the window's TIME
        # SPAN, not how often it runs) computed from a persistent rolling
        # PCM buffer, replacing only the low bands the short FFT cannot
        # resolve. 8192 samples (170.7ms at 48kHz) leaves only 2 of 64
        # bands still collapsed (the theoretical floor near 30 Hz itself),
        # down from 19 -- verified directly against this file's own
        # _perc_edges construction below before landing.
        self._low_band_pcm: np.ndarray = np.zeros(_LOW_BAND_N_FFT, dtype=np.float32)
        self._low_band_windowed: np.ndarray = np.zeros(_LOW_BAND_N_FFT, dtype=np.float32)
        self._low_band_window: np.ndarray = np.hanning(_LOW_BAND_N_FFT).astype(np.float32)
        self._low_band_warm_samples: int = 0  # counts toward a full buffer before first use

        self._recompute_band_edges()

        self._setup_frequency_bands()

    def _setup_frequency_bands(self) -> None:
        """Set up frequency band slices based on current profile."""
        def hz_to_bin(hz: float) -> int:
            return int(np.clip(round(hz / self._bin_hz), 1, self._bands - 1))
        
        # Use profile frequency ranges
        b0 = hz_to_bin(self._profile.bass_min)
        b1 = hz_to_bin(self._profile.bass_max)
        m0 = hz_to_bin(self._profile.mid_min)
        m1 = hz_to_bin(self._profile.mid_max)
        t0 = hz_to_bin(self._profile.treble_min)
        t1 = hz_to_bin(self._profile.treble_max)
        
        self._bass_slice = slice(min(b0, b1), max(b0 + 1, b1))
        self._mid_slice = slice(min(m0, m1), max(m0 + 1, m1))
        self._treble_slice = slice(min(t0, t1), max(t0 + 1, t1))

        # Vocal-formant band is fixed (not profile-dependent) -- it targets
        # the acoustic range voiced speech/singing occupies regardless of genre.
        v0 = hz_to_bin(_VOCAL_HZ[0])
        v1 = hz_to_bin(_VOCAL_HZ[1])
        self._vocal_slice = slice(min(v0, v1), max(v0 + 1, v1))

        # Beat detection weighting: emphasize bass + mid flux based on profile.
        # Per-band emphasis comes from the profile so kick-driven genres
        # (house/rap/techno) suppress hi-hat onsets, while broader genres
        # (rock/metal) keep mid/treble contribution for snare/cymbal hits.
        self._flux_weights = np.linspace(1.0, 0.22, self._bands, dtype=np.float32)
        self._flux_weights[self._bass_slice] *= float(
            getattr(self._profile, 'onset_bass_emphasis', 1.8)
        )
        self._flux_weights[self._mid_slice] *= float(
            getattr(self._profile, 'onset_mid_emphasis', 1.2)
        )
        self._flux_weights[self._treble_slice] *= float(
            getattr(self._profile, 'onset_treble_emphasis', 1.0)
        )
    
    def set_sample_rate(self, rate: int) -> None:
        """Sync the analyzer's assumed sample rate to the real capture rate.

        Called by AudioManager once capture is live, and again on every
        analysis frame thereafter (cheap early-return when unchanged) so a
        mid-session device/fallback switch to a differently-rated device
        can't leave this silently stale. Recomputes ``_bin_hz`` (the FFT
        bin-to-Hz mapping used by spectral centroid and the perceptual
        64-band bucketing) and the onset-envelope/vocal-heuristic ``dt``
        terms, which read ``_sample_rate`` directly. See
        ``_ASSUMED_SAMPLE_RATE``'s own comment.
        """
        rate = int(rate)
        if rate <= 0 or rate == self._sample_rate:
            return
        self._sample_rate = rate
        self._bin_hz = self._sample_rate / max(1, self._n_fft)
        self._recompute_band_edges()

    def set_profile(self, profile: AudioProfile) -> None:
        """Switch to a new profile and recalculate frequency bands."""
        self._profile = profile
        self._setup_frequency_bands()

    def set_silence_gate(self, floor: float, span: float) -> None:
        """Update the silence gate thresholds at runtime."""
        self._silence_rms_floor = max(0.0, float(floor))
        self._silence_rms_span = max(1e-4, float(span))

    def _norm_band(
        self, x: float, mean: float, var: float
    ) -> tuple[float, float, float]:
        """Running z-score normalise one band value to [0, 1].

        Uses a soft-sigmoid of the z-score so sustained levels stay in a
        meaningful range rather than collapsing to 0 or 1 indefinitely.
        Returns (normalised_value, updated_mean, updated_var).

        2026-08-11: this is the copy that produces AudioData.bass_n/mid_n/
        treble_n -- consumed by several effects (audio_spectrogram.py,
        audio_waveforms.py, audio_sine.py, audio_chromogram.py,
        audio_centroid.py, audio_tracks.py) and the live-corpus telemetry
        sample (app.py's build_live_corpus_sample()), NOT by the Auto VJ
        drop_score/band_blend computation. drop-ins/auto-vj-01/beat_grid.py
        runs the identical formula (same math, same default alpha) as two
        further independent copies with their own mean/var state -- one in
        BeatGridTracker, one in BeatTracker -- so a tuning
        change made only here does not reach the detector, and vice versa.
        Same underlying signal, three independently-drifting z-score
        trackers. See docs/adr/vj-system.md "Recommender centroid_fit
        Weight Cut..." sibling entries for the ongoing drop_score redesign
        discussion this duplication came up in.
        """
        a = self._band_alpha
        mean = mean + a * (x - mean)
        d = x - mean
        var = max(1e-6, var + a * (d * d - var))
        z = (x - mean) / (var ** 0.5 + 1e-6)
        v = 0.5 + 0.5 * (z / (1.0 + abs(z)))
        return float(np.clip(v, 0.0, 1.0)), mean, var

    @property
    def last_raw_rms(self) -> float:
        """Return the last unprocessed input RMS (pre-gate). 0.0 when silent."""
        return float(self._last_raw_rms)

    @property
    def last_audio_time(self) -> float:
        """Return the timestamp used for the most recent process() call."""
        return float(self._last_audio_time)

    @property
    def silence_rms_floor(self) -> float:
        """Return the RMS level below which the gate zeroes the spectrum."""
        return float(self._silence_rms_floor)

    # ------------------------------------------------------------------
    # P1 — onset event queue
    # ------------------------------------------------------------------

    def drain_onsets(self) -> list[OnsetEvent]:
        """Return and clear all onset events queued since the last call."""
        events = list(self._onset_queue)
        self._onset_queue.clear()
        return events

    # ------------------------------------------------------------------
    # P3 — adaptive refractory hint from BeatTracker
    # ------------------------------------------------------------------

    def set_expected_bpm(self, bpm: float, confidence: float) -> None:
        """Tune beat cooldown refractory based on the current BPM estimate.

        When confidence is sufficient, the refractory is set to 70% of the
        beat period so sub-beat onsets cannot enter the IOI stream.
        """
        if bpm > 0 and confidence >= 0.5:
            self._refractory_s = float(np.clip(0.70 * 60.0 / bpm, 0.18, 0.50))
            self._expected_bpm = float(bpm)
        else:
            self._refractory_s = None
            # Deliberately NOT reset to a default here -- a momentary
            # confidence dip shouldn't blank out data.bpm for every effect
            # reading it this frame. Sticky like a real tempo estimate;
            # only overwritten by the next confident feed.

    @property
    def refractory_s(self) -> float:
        """The currently active BPM-derived onset refractory, in seconds
        (2026-08-14, round three, audit cross-check item 12.8 #1).

        `0.0` when no confident BPM estimate is active (falls back to the
        strength-scaled cooldown instead -- see `set_expected_bpm()`'s own
        docstring). Exposed publicly so a drop-in can log it without
        reaching into `_refractory_s` directly (see CLAUDE.md's Public
        Runtime Surface Rules). Added specifically to test a candidate
        root-cause mechanism flagged by `docs/audits/2026-08-13-bpm-
        tempo-detection-audit.md` (finding T4) and cross-checked in
        `docs/planning/auto-vj-round-three-planning-2026-08-14.md` § 12.2:
        at a wrong, locked-in-error BPM, this refractory can suppress
        every other true beat at the source, making the onset evidence
        itself agree with the wrong lock. Logging this value is the cheap
        first half of testing that hypothesis; see that section for the
        full reasoning and the offline check it enables.
        """
        return float(self._refractory_s) if self._refractory_s is not None else 0.0

    # ------------------------------------------------------------------
    # P2 — time-based onset envelope helpers
    # ------------------------------------------------------------------

    def _push_envelope(self, dt: float, flux_value: float) -> None:
        """Resample a flux value into the fixed-rate (100 Hz) envelope ring."""
        self._env_t_acc += dt
        step = 1.0 / _ENV_RATE
        while self._env_t_acc >= step:
            self._env_t_acc -= step
            self._env_buf[self._env_write_idx] = flux_value
            self._env_write_idx = (self._env_write_idx + 1) % _ENV_LEN
            if self._env_write_idx == 0:
                self._env_filled = True

    def _onset_threshold(self) -> tuple[float, float]:
        """Return (threshold, mad) for current envelope state.

        Uses median + k*MAD which is robust against flux spikes and
        does not collapse on steady material the way mean+std does.

        2026-08-17: mad's floor changed from `+ 1e-6` (a literal-division-
        -by-zero guard, not a reasoned floor) to `max(raw_mad,
        _BEAT_ABS_FLOOR)`. A live session's new onset_strength_max_raw
        logging (drop-ins/auto-vj-01) caught mad collapsing toward zero
        during a near-silent/degenerate flux stretch, then the next real
        transient dividing by almost nothing at the strength call site
        (`(flux - threshold) / mad`) and producing a strength of
        1,171,176,147. `_BEAT_ABS_FLOOR` already encodes "the smallest
        meaningful flux scale" for `threshold`; reusing it here (rather
        than a fresh, untethered constant) applies the same belief to
        `mad`, and `max()` -- the same floor idiom beat_grid.py uses
        throughout (e.g. `max(_V2_LOCK_BAND_MIN, bpm*_V2_LOCK_BAND_PCT)`)
        -- makes it a true no-op once real mad already exceeds the floor,
        unlike `+ 1e-6`'s literal-addition shape (which, at a larger
        floor value, would keep inflating mad and dulling strength even
        on well-populated material -- see tools/onset_strength_mad_floor_
        harness.py's scenario 3 for the empirical comparison). See
        _ONSET_STRENGTH_CAP's own comment for the independent backstop.
        """
        arr = self._env_buf if self._env_filled else self._env_buf[:max(1, self._env_write_idx)]
        med = float(np.median(arr))
        mad = max(float(np.median(np.abs(arr - med))), _BEAT_ABS_FLOOR)
        threshold = med + _BEAT_MAD_K * mad + _BEAT_ABS_FLOOR
        return threshold, mad

    # ------------------------------------------------------------------
    # Vocal-presence heuristics: HNR (per-frame) + FMR (rolling window)
    # ------------------------------------------------------------------

    def _compute_vocal_hnr(self, spectrum: np.ndarray) -> float:
        """Return a 0-1 harmonic-to-noise-ratio proxy for the vocal formant band.

        Autocorrelates the log-compressed magnitude spectrum within the
        formant band (this is the standard cepstral-pitch trick: a harmonic
        comb in the spectrum produces a periodic ripple across frequency
        bins, which shows up as a strong autocorrelation peak at a nonzero
        lag). High for voice or any pitched tone; low for noise-like or
        percussive content sharing the same band.
        """
        band = spectrum[self._vocal_slice]
        n = band.size
        if n < 8:
            return 0.0
        log_band = np.log1p(band.astype(np.float64))
        log_band -= log_band.mean()
        energy = float(np.dot(log_band, log_band))
        if energy <= 1e-9:
            return 0.0
        f = np.fft.rfft(log_band, n=2 * n)
        acf = np.fft.irfft(f * np.conj(f))[:n]
        acf0 = acf[0]
        if acf0 <= 1e-9:
            return 0.0
        acf /= acf0
        if n <= _VOCAL_HNR_MIN_LAG_BINS + 1:
            return 0.0
        peak = float(np.max(acf[_VOCAL_HNR_MIN_LAG_BINS:]))
        return float(np.clip(peak, 0.0, 1.0))

    def _push_vocal_envelope(self, dt: float, vocal_energy: float) -> None:
        """Resample the vocal-band energy scalar into the FMR ring (40 Hz)."""
        self._vocal_env_t_acc += dt
        step = 1.0 / _VOCAL_ENV_RATE
        while self._vocal_env_t_acc >= step:
            self._vocal_env_t_acc -= step
            self._vocal_env_buf[self._vocal_env_write_idx] = vocal_energy
            self._vocal_env_write_idx = (self._vocal_env_write_idx + 1) % _VOCAL_ENV_LEN
            if self._vocal_env_write_idx == 0:
                self._vocal_env_filled = True

    def _compute_vocal_fmr(self) -> float:
        """Return the fraction of vocal-band modulation energy in 3-8 Hz.

        FFTs the vocal-band energy ring (not the audio itself -- this is a
        modulation spectrum, one level removed) and compares energy in the
        syllabic/vibrato rate band against total modulation energy excluding
        DC. High for sung/spoken delivery; low for a sustained pad (little
        modulation at all) or pure noise (modulation spread flat/broadband).
        """
        n_valid = _VOCAL_ENV_LEN if self._vocal_env_filled else self._vocal_env_write_idx
        if n_valid < 16:
            return 0.0
        if self._vocal_env_filled:
            idx = self._vocal_env_write_idx
            arr = np.concatenate([self._vocal_env_buf[idx:], self._vocal_env_buf[:idx]])
        else:
            arr = self._vocal_env_buf[:n_valid].copy()
        arr = arr.astype(np.float64)
        arr -= arr.mean()
        # Window before the modulation FFT: an un-windowed segment boundary
        # (block-rate leakage from the source FFT, or simply a non-periodic
        # slice) spreads energy across many bins, including 3-8 Hz, even when
        # the true envelope is flat -- confirmed against a synthetic
        # unmodulated tone that otherwise scored ~0.46 instead of ~0.
        arr *= np.hanning(arr.size)
        mag = np.abs(np.fft.rfft(arr))
        mod_energy = mag[1:]  # exclude DC (bin 0)
        total = float(np.sum(mod_energy))
        if total <= 1e-9:
            return 0.0
        freqs = np.fft.rfftfreq(arr.size, d=1.0 / _VOCAL_ENV_RATE)[1:]
        band_mask = (freqs >= _VOCAL_FMR_HZ[0]) & (freqs <= _VOCAL_FMR_HZ[1])
        band_energy = float(np.sum(mod_energy[band_mask]))
        return float(np.clip(band_energy / total, 0.0, 1.0))

    # ------------------------------------------------------------------
    # Existing helpers
    # ------------------------------------------------------------------

    def _shape(self, x: float, gain: float) -> float:
        """Map linear band energy to a smooth [0,1] response curve."""
        y = 1.0 - np.exp(-max(0.0, x) * gain)
        return float(np.clip(y, 0.0, 1.0))

    @staticmethod
    def _safe_mean(arr: np.ndarray, band: slice) -> float:
        sub = arr[band]
        if sub.size == 0:
            return 0.0
        return float(sub.mean())

    def _recompute_band_edges(self) -> None:
        """(Re)compute the 64-band perceptual bucketing edges for both the
        short (fast-path) and long (low-band) FFTs, from the analyzer's
        current ``_sample_rate``.

        2026-09-04: previously this was computed ONCE at construction
        time using whatever ``_sample_rate`` happened to be set then
        (the module fallback, ``_ASSUMED_SAMPLE_RATE``) and never
        recomputed -- ``set_sample_rate()`` updated ``_bin_hz`` but not
        the edge tables that formula feeds, so a real device negotiating
        a different rate (44.1kHz being the obvious case) silently left
        every band's bin-index mapping computed for the wrong rate for
        the rest of the session. Found live while making the low-band
        edges below rate-aware -- fixed for both edge tables in the same
        pass rather than leaving the short-path one newly inconsistent
        with the long-path one.
        """
        edges_hz = np.logspace(
            np.log10(_PERC_F_MIN), np.log10(_PERC_F_MAX), _PERC_N_BANDS + 1,
        )
        bin_hz = self._sample_rate / max(1, self._bands * 2)
        self._perc_edges: np.ndarray = np.clip(
            np.round(edges_hz / bin_hz).astype(int), 0, self._bands - 1,
        )
        low_bin_hz = self._sample_rate / max(1, _LOW_BAND_N_FFT)
        self._low_band_edges: np.ndarray = np.clip(
            np.round(edges_hz / low_bin_hz).astype(int), 0, _LOW_BAND_N_FFT // 2 - 1,
        )

    def _window_for(self, n: int) -> np.ndarray:
        """Return a cached Hann window for the given block length."""
        window = self._window_cache.get(n)
        if window is None:
            window = np.hanning(n).astype(np.float32)
            self._window_cache[n] = window
        return window

    def _compute_complex_onset_flux(self, fft_raw: np.ndarray) -> float:
        """Complex-domain onset detection function (Bello, Duxbury, Davies
        & Sandler, "On the Use of Phase and Energy for Musical Onset
        Detection in the Complex Domain," IEEE Signal Processing Letters,
        vol. 11, no. 6, June 2004).

        For each FFT bin, predicts this frame's complex value from the
        previous two frames (predicted magnitude = previous frame's
        magnitude; predicted phase = previous phase plus the previous
        phase increment -- the constant-phase-advance assumption), then
        takes the Euclidean distance between predicted and observed
        complex spectra, summed across bins, as the raw ODF value. Purely
        causal: uses only the current frame plus its two immediate
        predecessors, no lookahead.

        Ported from tools/beat-tracker-bench/onset-prototype/
        complex_onset.py's ComplexOnsetDetector._process_frame() (built
        for Program B's OSS beat-tracker comparison, see
        docs/adr/vj-system.md and tools/beat-tracker-bench/results/
        detector-scorecard.md) -- that module's own docstring documents
        the clean-room provenance (reimplemented from the published
        paper's own description; BTrack's GPL-3.0 source was not read).
        Reuses ``fft_raw`` (already computed once per tick for the
        magnitude spectrum / bands / flux) for its phase -- no extra FFT.

        Returns the raw (un-normalized) ODF value; ``beat_grid.py``'s
        ``env_source='dense_complex'`` path applies the same causal
        median/MAD normalization already ported there for
        ``spectral_flux``'s own ``'dense_flux'`` path, so this method
        deliberately does not normalize.
        """
        spec = fft_raw[: self._bands]
        mag = np.abs(spec).astype(np.float64)
        phase = np.angle(spec).astype(np.float64)
        self._complex_onset_frames_seen += 1

        if self._complex_onset_frames_seen <= 2:
            odf = 0.0
        else:
            mag_pred = self._complex_onset_mag_prev
            phase_pred = _princarg(
                2.0 * self._complex_onset_phase_prev - self._complex_onset_phase_prev2
            )
            d2 = (
                mag ** 2 + mag_pred ** 2
                - 2.0 * mag * mag_pred * np.cos(phase - phase_pred)
            )
            odf = float(np.sqrt(np.clip(d2, 0.0, None)).sum())

        self._complex_onset_mag_prev2 = self._complex_onset_mag_prev
        self._complex_onset_mag_prev = mag
        self._complex_onset_phase_prev2 = self._complex_onset_phase_prev
        self._complex_onset_phase_prev = phase
        return odf

    def process(
        self,
        pcm: np.ndarray | None,
        t: float | None = None,
        out: AudioData | None = None,
        side: np.ndarray | None = None,
    ) -> AudioData:
        """Process one block of PCM audio and return an AudioData snapshot.

        pcm: float32 mono array, or None for a silent frame.
        t:   optional audio-time in seconds (for offline / harness use).
             When None, wall-clock time.monotonic() is used.
        out: optional pre-allocated AudioData to fill in-place.  When provided
             the caller's buffer is mutated and returned (no allocation).
             Fields not computed for a silent frame are reset to their defaults.
        """
        data = out if out is not None else AudioData()
        now: float = t if t is not None else time.monotonic()
        self._last_audio_time = now
        # 2026-08-09 fix: data.bpm was never assigned anywhere in process()
        # -- see self._expected_bpm's field comment in __init__. Set before
        # the silent-frame early return below: a momentarily silent frame
        # shouldn't reset the known tempo estimate any more than a momentary
        # confidence dip does (same stickiness reasoning as
        # set_expected_bpm() above).
        data.bpm = self._expected_bpm

        if pcm is None or len(pcm) == 0:
            return data

        # Window + FFT — use scratch buffer to avoid per-frame allocation
        n = len(pcm)
        window = self._window_for(n)
        if n > len(self._windowed_buf):
            self._windowed_buf = np.empty(n, dtype=np.float32)
        np.multiply(pcm[:n], window, out=self._windowed_buf[:n])
        windowed = self._windowed_buf[:n]
        rms = float(np.sqrt(np.mean(windowed * windowed)))
        fft_raw = np.fft.rfft(windowed, n=self._bands * 2)
        np.abs(fft_raw[: self._bands], out=self._spectrum_work)
        spectrum = self._spectrum_work

        self._last_raw_rms = rms

        # Silence/noise gate scalar (0 = silent, 1 = full signal).
        energy = np.clip((rms - self._silence_rms_floor) / self._silence_rms_span, 0.0, 1.0)

        # --- Spectral flux (raw spectrum, BEFORE per-frame normalization) ---
        # Computing flux from the normalised spectrum was the root cause of the
        # flat onset envelope: dividing by max_val each frame erases the kick
        # transient because the spectrum *shape* barely changes even on a loud
        # kick — only its absolute magnitude does.  Using the raw FFT magnitudes
        # means a kick drum produces a large positive delta in the bass bins,
        # giving the ACF a clear periodic signal to lock onto.
        np.subtract(spectrum, self._prev_spectrum, out=self._flux_delta)
        np.maximum(self._flux_delta, 0.0, out=self._flux_delta)
        flux = float(np.sum(self._flux_delta * self._flux_weights))
        rms_rise = max(0.0, rms - self._prev_rms)
        self._prev_rms = rms
        flux += rms_rise * (0.25 * self._bands)
        # Gate: don't push noise-floor flux into the onset envelope during silence.
        if energy <= 1e-5:
            flux = 0.0
        np.copyto(self._prev_spectrum, spectrum)   # save raw for next frame

        # --- Complex-domain onset function (raw spectrum + phase) ---
        # Reuses fft_raw's phase for free -- no extra FFT. Gated like flux
        # (silence -> 0.0) but the two-frame history itself always advances,
        # same reasoning as _prev_spectrum above: keeps the prediction warm
        # so real audio resuming after a quiet patch doesn't need two more
        # frames to "recover" before producing a real value again.
        complex_onset_flux = self._compute_complex_onset_flux(fft_raw)
        data.complex_onset_flux = complex_onset_flux if energy > 1e-5 else 0.0

        # Per-band raw sub-fluxes for downbeat detection
        data.bass_flux = float(np.sum(
            self._flux_delta[self._bass_slice] * self._flux_weights[self._bass_slice]
        ))
        data.mid_flux = float(np.sum(
            self._flux_delta[self._mid_slice] * self._flux_weights[self._mid_slice]
        ))

        # Raw-path bass LEVEL (2026-08-18, drop-score redesign audit F1):
        # must be read HERE, before the per-frame max-normalization below
        # turns the spectrum into a shape fraction — the exact reason flux
        # reads the raw spectrum (comment above). log1p for perceptual
        # scaling/headroom, profile bass weight for genre comparability,
        # silence-gated like flux. See AudioData.bass_level_raw.
        if energy > 1e-5:
            data.bass_level_raw = float(np.log1p(
                self._safe_mean(spectrum, self._bass_slice)
                * self._profile.bass_weight
            ))
        else:
            data.bass_level_raw = 0.0

        # Vocal-presence heuristics -- must read the raw (pre-normalization)
        # spectrum, same as flux above, since the in-place normalize below
        # rescales per-frame and would erase the harmonic ripple shape.
        if energy > 1e-5:
            data.vocal_hnr = self._compute_vocal_hnr(spectrum)
            vocal_energy = float(spectrum[self._vocal_slice].mean())
        else:
            data.vocal_hnr = 0.0
            vocal_energy = 0.0
        # --- Spectral contrast (2026-09-01; see _CONTRAST_* constants) ---
        if energy > 1e-5:
            bin_hz = self._sample_rate / max(1, self._n_fft)
            contrasts = []
            edges = _CONTRAST_BAND_EDGES_HZ
            for lo_hz, hi_hz in zip(edges, edges[1:]):
                b0 = max(1, int(lo_hz / bin_hz))
                b1 = min(self._bands, int(hi_hz / bin_hz))
                if b1 - b0 < 4:
                    continue
                seg = spectrum[b0:b1]
                k = max(1, int(len(seg) * _CONTRAST_QUANTILE))
                part = np.partition(seg, (k - 1, len(seg) - k))
                valley = float(part[:k].mean()) + 1e-9
                peak = float(part[len(seg) - k:].mean()) + 1e-9
                contrasts.append(np.log10(peak / valley))
            if contrasts:
                val = float(np.mean(contrasts))
                self._spectral_contrast_ema += 0.1 * (val - self._spectral_contrast_ema)
        data.spectral_contrast = self._spectral_contrast_ema

        # --- Mid/side vocal presence (2026-09-01; see _VOCAL_MS_*) ---
        # The mono input IS the mid channel (capture downmix = (L+R)/2),
        # so mid-band energy comes free from the existing spectrum; only
        # the side block costs one extra rfft.
        if side is not None and len(side) >= n and energy > 1e-5:
            np.multiply(side[:n], window, out=self._windowed_buf[:n])
            side_fft = np.fft.rfft(self._windowed_buf[:n], n=self._bands * 2)
            np.abs(side_fft[: self._bands], out=self._side_spectrum_work)
            bin_hz = self._sample_rate / max(1, self._n_fft)
            b0 = max(1, int(_VOCAL_MS_BAND_HZ[0] / bin_hz))
            b1 = min(self._bands, int(_VOCAL_MS_BAND_HZ[1] / bin_hz))
            mid_band = float(np.sum(spectrum[b0:b1]))
            side_band = float(np.sum(self._side_spectrum_work[b0:b1]))
            self._vocal_ms_ring.append(mid_band / (mid_band + side_band + 1e-9))
            self._vocal_ms_frate = self._sample_rate / max(1, len(pcm))
            self._vocal_ms_frame_count += 1
            if (self._vocal_ms_frame_count >= _VOCAL_MS_RECOMPUTE_FRAMES
                    and len(self._vocal_ms_ring) >= _VOCAL_MS_RING // 4):
                self._vocal_ms_frame_count = 0
                env = np.asarray(self._vocal_ms_ring, dtype=np.float32)
                self._vocal_mid_ratio_cached = float(env.mean())
                env = env - env.mean()
                mod = np.abs(np.fft.rfft(env * np.hanning(len(env))))
                mf = np.fft.rfftfreq(len(env), 1.0 / self._vocal_ms_frate)
                lo, hi = _VOCAL_MS_MOD_BAND_HZ
                tl, th = _VOCAL_MS_MOD_TOTAL_HZ
                total = float(mod[(mf >= tl) & (mf < th)].sum()) + 1e-9
                self._vocal_syl_cached = float(
                    mod[(mf >= lo) & (mf < hi)].sum()) / total
                self._vocal_ms_valid = True
        data.vocal_mid_ratio = self._vocal_mid_ratio_cached
        data.vocal_syl = self._vocal_syl_cached
        data.vocal_ms_valid = self._vocal_ms_valid

        vocal_dt = len(pcm) / self._sample_rate
        self._push_vocal_envelope(vocal_dt, vocal_energy)
        self._vocal_fmr_frame_count += 1
        if self._vocal_fmr_frame_count >= _VOCAL_FMR_RECOMPUTE_FRAMES:
            self._vocal_fmr_frame_count = 0
            self._vocal_fmr_cached = self._compute_vocal_fmr()
        data.vocal_fmr = self._vocal_fmr_cached

        # --- Normalise spectrum for display / band-level computation ---
        max_val = spectrum.max()
        if max_val > 1e-6 and energy > 1e-5:
            spectrum /= max_val
            spectrum *= np.sqrt(energy)
        else:
            spectrum *= 0.0

        # Smoothed FFT
        self._smoothed *= _SMOOTHING
        self._smoothed += spectrum * (1.0 - _SMOOTHING)
        data.fft[:] = self._smoothed

        # Low-band resolution fix (2026-09-04): keep the long-window rolling
        # buffer warm every tick, regardless of the energy gate below, so a
        # brief quiet passage doesn't force a re-warm-up once real signal
        # resumes -- see self._low_band_pcm's own __init__ comment.
        if n >= _LOW_BAND_N_FFT:
            self._low_band_pcm[:] = pcm[-_LOW_BAND_N_FFT:]
        else:
            self._low_band_pcm[:-n] = self._low_band_pcm[n:]
            self._low_band_pcm[-n:] = pcm[:n]
        self._low_band_warm_samples = min(_LOW_BAND_N_FFT, self._low_band_warm_samples + n)

        # 64-band perceptual spectrum (raw, no visual gain) — bucket smoothed
        # FFT bins into log-spaced bands and normalize to [0, 1].
        edges = self._perc_edges
        for i in range(_PERC_N_BANDS):
            lo, hi = int(edges[i]), int(edges[i + 1])
            self._perc_work[i] = self._smoothed[lo:hi + 1].mean() if hi > lo else self._smoothed[lo]

        # Low-band resolution fix, continued: replace the bottom
        # _LOW_BAND_REPLACE_N bands (the ones the short FFT above cannot
        # resolve -- see _LOW_BAND_REPLACE_N's own comment) with values
        # from the long-window FFT, once the rolling buffer has seen a
        # full window's worth of real audio. Scale-corrected by the ratio
        # of window sums so a sustained tone's magnitude is comparable
        # between the two differently-sized Hann windows -- the short
        # path applies no normalization of its own either, so this
        # matches that existing convention rather than inventing a new
        # one. Deliberately NOT reached during silence (matches every
        # other energy-gated block in this method) -- a near-zero buffer
        # would just replace real zeros with differently-scaled near-zero
        # noise for no benefit.
        if energy > 1e-5 and self._low_band_warm_samples >= _LOW_BAND_N_FFT:
            np.multiply(self._low_band_pcm, self._low_band_window, out=self._low_band_windowed)
            low_mag = np.abs(np.fft.rfft(self._low_band_windowed))
            low_edges = self._low_band_edges
            scale = float(window.sum()) / float(self._low_band_window.sum())
            for i in range(_LOW_BAND_REPLACE_N):
                lo, hi = int(low_edges[i]), int(low_edges[i + 1])
                val = low_mag[lo:hi + 1].mean() if hi > lo else low_mag[lo]
                self._perc_work[i] = val * scale

        peak_perc = self._perc_work.max()
        if peak_perc > 1e-6:
            np.multiply(self._perc_work, 1.0 / peak_perc, out=self._perc_work)
        else:
            self._perc_work.fill(0.0)
        data.bands[:] = self._perc_work

        # Expose gated flux scalar for recommender / corpus use.
        data.spectral_flux = flux

        # Waveform (last 512 samples normalised)
        wlen = min(512, len(pcm))
        wform = pcm[-wlen:]
        peak = np.abs(wform).max()
        if energy > 1e-5 and peak > 1e-6:
            data.waveform.fill(0.0)
            data.waveform[:wlen] = (wform / peak).astype(np.float32)
        else:
            data.waveform.fill(0.0)

        # Zero-crossing rate (2026-09-03, recommender rc.27): fraction of
        # adjacent-sample sign changes in the just-written waveform window
        # -- same formula auto_vj.py's own recommender scoring already
        # computed ad hoc from audio.waveform every tick; promoted to a
        # proper Analyzer-computed field (see AudioData.zcr) so it is
        # computed once and available to the training corpus.
        if energy > 1e-5 and wlen > 1:
            wv = data.waveform[:wlen]
            data.zcr = float(np.mean(np.abs(np.diff(np.sign(wv))) > 0))
        else:
            data.zcr = 0.0

        # Band energy from normalised smoothed spectrum.
        bass_raw = self._safe_mean(self._smoothed, self._bass_slice)
        mid_raw = self._safe_mean(self._smoothed, self._mid_slice)
        treble_raw = self._safe_mean(self._smoothed, self._treble_slice)

        # Apply profile weights to normalize across genres
        bass_weighted = bass_raw * self._profile.bass_weight
        mid_weighted = mid_raw * self._profile.mid_weight
        treble_weighted = treble_raw * self._profile.treble_weight

        # Weighted perceptual channels exposed to effects with profile-specific gains
        data.bass = self._shape(bass_weighted, gain=6.6)
        data.mid = self._shape(mid_weighted, gain=5.8)
        data.treble = self._shape(treble_weighted, gain=7.2)

        # Detector-facing counterparts -- same pre-curve input, gain tuned
        # for dynamic range rather than visual saturation. See
        # AudioData.bass_det's field comment and _DETECTOR_BASS_GAIN above.
        data.bass_det = self._shape(bass_weighted, gain=_DETECTOR_BASS_GAIN)
        data.mid_det = self._shape(mid_weighted, gain=_DETECTOR_MID_GAIN)
        data.treble_det = self._shape(treble_weighted, gain=_DETECTOR_TREBLE_GAIN)

        # Per-band independently z-score normalised values (0–1).
        # These track *relative change* within each band so an effect or
        # beat detector can tell "bass is MORE active than its recent baseline"
        # even when the absolute level is near-saturated the whole session.
        data.bass_n, self._band_mean_bass, self._band_var_bass = self._norm_band(
            data.bass, self._band_mean_bass, self._band_var_bass
        )
        data.mid_n, self._band_mean_mid, self._band_var_mid = self._norm_band(
            data.mid, self._band_mean_mid, self._band_var_mid
        )
        data.treble_n, self._band_mean_treble, self._band_var_treble = self._norm_band(
            data.treble, self._band_mean_treble, self._band_var_treble
        )

        # P2: push flux into the time-based envelope ring
        dt = len(pcm) / self._sample_rate
        self._push_envelope(dt, flux)

        # P1+P2+P3: onset detection with MAD threshold and adaptive refractory
        data.beat = 0.0
        if energy > 1e-5 and now >= self._beat_cooldown_until_t:
            threshold, mad = self._onset_threshold()
            # Require local maximum (rising edge) to avoid double-triggers
            is_local_max = flux >= self._env_prev_flux
            if is_local_max and flux > threshold:
                data.beat = 1.0
                strength = (flux - threshold) / mad + 1.0
                # P3: use BeatTracker-supplied refractory when available;
                # otherwise fall back to a strength-scaled dynamic cooldown.
                if self._refractory_s is not None:
                    cooldown = self._refractory_s
                else:
                    strength_z = (flux - threshold) / mad
                    cooldown_frames = float(np.clip(12.0 - strength_z * 1.5, 6.0, 12.0))
                    cooldown = cooldown_frames / 60.0
                self._beat_cooldown_until_t = now + cooldown
                # P1: queue the onset event for the BeatTracker to consume
                if len(self._onset_queue) == self._onset_queue.maxlen:
                    log.debug('Onset queue overflow — dropping oldest event')
                # 2026-08-14: band_weight -- what fraction of this onset's
                # flux was bass-band (data.bass_flux, already computed
                # above) vs. the rest of the spectrum. Clipped to [0, 1]:
                # `flux` includes the rms_rise term (not band-attributed),
                # so the raw ratio can slightly exceed 1.0 on a broadband
                # transient. See OnsetEvent's field comment.
                band_weight = float(np.clip(data.bass_flux / max(1e-6, flux), 0.0, 1.0))
                # 2026-08-17: hard cap, independent of the mad-floor fix
                # above -- see _ONSET_STRENGTH_CAP's own comment.
                clamped_strength = min(max(1.0, float(strength)), _ONSET_STRENGTH_CAP)
                self._onset_queue.append(
                    OnsetEvent(now, clamped_strength, band_weight)
                )

        self._env_prev_flux = flux
        return data
