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
_BEAT_THRESHOLD = 1.4   # standard deviations above mean


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

        # Band energy
        lo = max(1, self._bands // 32)   # bass: ~0–1 kHz
        mid_lo = self._bands // 8
        mid_hi = self._bands // 2
        data.bass = float(self._smoothed[:lo].mean()) * 4.0
        data.mid = float(self._smoothed[lo:mid_hi].mean()) * 4.0
        data.treble = float(self._smoothed[mid_hi:].mean()) * 6.0
        data.bass = min(1.0, data.bass)
        data.mid = min(1.0, data.mid)
        data.treble = min(1.0, data.treble)

        # Spectral flux onset detection
        np.subtract(spectrum, self._prev_spectrum, out=self._flux_delta)
        np.maximum(self._flux_delta, 0.0, out=self._flux_delta)
        flux = float(np.sum(self._flux_delta))
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
                self._beat_cooldown = 10   # 10 frames min between beats
            else:
                data.beat = 0.0

        return data
