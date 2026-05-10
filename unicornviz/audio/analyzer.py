"""
FFT analyzer + beat detector.
Consumes PCM blocks from AudioCapture and produces AudioData snapshots.
"""
from __future__ import annotations

import numpy as np

from unicornviz.effects.base import AudioData

_FFT_BANDS = 512
_SMOOTHING = 0.75       # exponential smoothing coefficient
_ONSET_WINDOW = 43      # ~1 s of history at 60 fps for spectral flux
_BEAT_THRESHOLD = 1.25  # standard deviations above mean
_ASSUMED_SAMPLE_RATE = 48000
_BASS_HZ = (40.0, 180.0)
_LOW_MID_HZ = (180.0, 700.0)
_MID_HZ = (700.0, 3200.0)
_TREBLE_HZ = (3200.0, 12000.0)
_AIR_HZ = (12000.0, 18000.0)


class Analyzer:
    """
    Call `process(pcm)` each frame (pcm = float32 mono array).
    Returns an AudioData snapshot.
    """

    def __init__(self, fft_bands: int = _FFT_BANDS) -> None:
        self._bands = fft_bands
        self._smoothed = np.zeros(fft_bands, dtype=np.float32)
        self._window_cache: dict[int, np.ndarray] = {}
        self._flux_history = np.zeros(_ONSET_WINDOW, dtype=np.float32)
        self._flux_index = 0
        self._flux_count = 0
        self._prev_spectrum = np.zeros(fft_bands, dtype=np.float32)
        self._flux_delta = np.zeros(fft_bands, dtype=np.float32)
        self._beat_cooldown = 0.0   # frames remaining before next beat
        self._prev_rms = 0.0

        self._n_fft = self._bands * 2
        self._bin_hz = _ASSUMED_SAMPLE_RATE / max(1, self._n_fft)

        def hz_to_bin(hz: float) -> int:
            return int(np.clip(round(hz / self._bin_hz), 1, self._bands - 1))

        b0, b1 = hz_to_bin(_BASS_HZ[0]), hz_to_bin(_BASS_HZ[1])
        lm0, lm1 = hz_to_bin(_LOW_MID_HZ[0]), hz_to_bin(_LOW_MID_HZ[1])
        m0, m1 = hz_to_bin(_MID_HZ[0]), hz_to_bin(_MID_HZ[1])
        t0, t1 = hz_to_bin(_TREBLE_HZ[0]), hz_to_bin(_TREBLE_HZ[1])
        a0, a1 = hz_to_bin(_AIR_HZ[0]), hz_to_bin(_AIR_HZ[1])

        self._bass_slice = slice(min(b0, b1), max(b0 + 1, b1))
        self._low_mid_slice = slice(min(lm0, lm1), max(lm0 + 1, lm1))
        self._mid_slice = slice(min(m0, m1), max(m0 + 1, m1))
        self._treble_slice = slice(min(t0, t1), max(t0 + 1, t1))
        self._air_slice = slice(min(a0, a1), max(a0 + 1, a1))

        # Beat detection weighting: emphasize bass + low-mid flux.
        self._flux_weights = np.linspace(1.0, 0.22, self._bands, dtype=np.float32)
        self._flux_weights[self._bass_slice] *= 1.8
        self._flux_weights[self._low_mid_slice] *= 1.3

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

    def process(self, pcm: np.ndarray | None) -> AudioData:
        data = AudioData()

        if pcm is None or len(pcm) == 0:
            return data

        # Window + FFT
        n = len(pcm)
        window = self._window_for(n)
        windowed = pcm[:n] * window
        rms = float(np.sqrt(np.mean(windowed * windowed)))
        spectrum = np.abs(np.fft.rfft(windowed, n=self._bands * 2))
        spectrum = spectrum[: self._bands].astype(np.float32)

        # Silence/noise gate + per-frame normalization.
        # The previous implementation normalized every frame to 1.0, which made
        # low-level noise look like strong audio and masked actual signal loss.
        energy = np.clip((rms - 0.0015) / 0.05, 0.0, 1.0)
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

        # Waveform (last 512 samples normalised)
        wlen = min(512, len(pcm))
        wform = pcm[-wlen:]
        peak = np.abs(wform).max()
        if energy > 1e-5 and peak > 1e-6:
            data.waveform.fill(0.0)
            data.waveform[:wlen] = (wform / peak).astype(np.float32)
        else:
            data.waveform.fill(0.0)

        # Band energy (modern splits).
        bass_raw = self._safe_mean(self._smoothed, self._bass_slice)
        low_mid_raw = self._safe_mean(self._smoothed, self._low_mid_slice)
        mid_raw = self._safe_mean(self._smoothed, self._mid_slice)
        treble_raw = self._safe_mean(self._smoothed, self._treble_slice)
        air_raw = self._safe_mean(self._smoothed, self._air_slice)

        # Weighted perceptual channels exposed to effects.
        data.bass = self._shape(0.85 * bass_raw + 0.15 * low_mid_raw, gain=6.6)
        data.mid = self._shape(0.35 * low_mid_raw + 0.65 * mid_raw, gain=5.8)
        data.treble = self._shape(0.78 * treble_raw + 0.22 * air_raw, gain=7.2)

        # Spectral flux onset detection
        np.subtract(spectrum, self._prev_spectrum, out=self._flux_delta)
        np.maximum(self._flux_delta, 0.0, out=self._flux_delta)
        flux = float(np.sum(self._flux_delta * self._flux_weights))
        rms_rise = max(0.0, rms - self._prev_rms)
        self._prev_rms = rms
        flux += rms_rise * (0.25 * self._bands)
        np.copyto(self._prev_spectrum, spectrum)
        self._flux_history[self._flux_index] = flux
        self._flux_index = (self._flux_index + 1) % _ONSET_WINDOW
        self._flux_count = min(self._flux_count + 1, _ONSET_WINDOW)

        if self._beat_cooldown > 0:
            self._beat_cooldown -= 1
            data.beat = 0.0
        else:
            arr = self._flux_history if self._flux_count == _ONSET_WINDOW else self._flux_history[:self._flux_count]
            mean = arr.mean()
            std = arr.std()
            if std > 1e-6 and flux > mean + _BEAT_THRESHOLD * std:
                data.beat = 1.0
                # Dynamic cooldown: strong onsets can retrigger slightly sooner.
                strength = (flux - mean) / max(std, 1e-6)
                self._beat_cooldown = float(np.clip(12.0 - strength * 1.5, 6.0, 12.0))
            else:
                data.beat = 0.0

        return data
