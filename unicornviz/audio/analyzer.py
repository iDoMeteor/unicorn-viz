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
_ASSUMED_SAMPLE_RATE = 48000

# 64 log-spaced perceptual bands shared across all consumers (effects + auto-VJ).
# Matches audio_spectrum.py exactly: 30 Hz – 16 kHz, 64 bands, raw (no visual gain).
_PERC_N_BANDS = 64
_PERC_F_MIN = 30.0
_PERC_F_MAX = 16_000.0
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


@dataclass(frozen=True)
class OnsetEvent:
    """A detected onset with audio-time timestamp and relative strength."""

    t: float         # audio time (seconds) at detection
    strength: float  # z-score above adaptive threshold (>= 1.0)


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

        # P3 — adaptive refractory (set by BeatTracker via set_expected_bpm)
        self._refractory_s: float | None = None
        self._beat_cooldown_until_t: float = -1e9

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

        self._n_fft = self._bands * 2
        self._bin_hz = _ASSUMED_SAMPLE_RATE / max(1, self._n_fft)

        # Wave 3.1 — scratch buffers to avoid per-frame heap allocation
        self._spectrum_work: np.ndarray = np.zeros(fft_bands, dtype=np.float32)
        self._windowed_buf: np.ndarray = np.zeros(1024, dtype=np.float32)

        # 64-band perceptual bucketing (shared with audio_spectrum.py consumers).
        # Edges are bin indices into the 512-bin FFT output; precomputed once.
        edges_hz = np.logspace(
            np.log10(_PERC_F_MIN), np.log10(_PERC_F_MAX), _PERC_N_BANDS + 1,
        )
        bin_hz = _ASSUMED_SAMPLE_RATE / max(1, fft_bands * 2)
        self._perc_edges: np.ndarray = np.clip(
            np.round(edges_hz / bin_hz).astype(int), 0, fft_bands - 1,
        )
        self._perc_work: np.ndarray = np.zeros(_PERC_N_BANDS, dtype=np.float32)

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
        else:
            self._refractory_s = None

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
        """
        arr = self._env_buf if self._env_filled else self._env_buf[:max(1, self._env_write_idx)]
        med = float(np.median(arr))
        mad = float(np.median(np.abs(arr - med))) + 1e-6
        threshold = med + _BEAT_MAD_K * mad + _BEAT_ABS_FLOOR
        return threshold, mad

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

    def _window_for(self, n: int) -> np.ndarray:
        """Return a cached Hann window for the given block length."""
        window = self._window_cache.get(n)
        if window is None:
            window = np.hanning(n).astype(np.float32)
            self._window_cache[n] = window
        return window

    def process(
        self,
        pcm: np.ndarray | None,
        t: float | None = None,
        out: AudioData | None = None,
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

        # Per-band raw sub-fluxes for downbeat detection
        data.bass_flux = float(np.sum(
            self._flux_delta[self._bass_slice] * self._flux_weights[self._bass_slice]
        ))
        data.mid_flux = float(np.sum(
            self._flux_delta[self._mid_slice] * self._flux_weights[self._mid_slice]
        ))

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

        # 64-band perceptual spectrum (raw, no visual gain) — bucket smoothed
        # FFT bins into log-spaced bands and normalize to [0, 1].
        edges = self._perc_edges
        for i in range(_PERC_N_BANDS):
            lo, hi = int(edges[i]), int(edges[i + 1])
            self._perc_work[i] = self._smoothed[lo:hi + 1].mean() if hi > lo else self._smoothed[lo]
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
        dt = len(pcm) / _ASSUMED_SAMPLE_RATE
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
                self._onset_queue.append(OnsetEvent(now, max(1.0, float(strength))))

        self._env_prev_flux = flux
        return data
