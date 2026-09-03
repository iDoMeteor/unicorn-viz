"""Complex-domain onset detection function — hand-designed, no training data.

Reimplementation of:

  J. P. Bello, C. Duxbury, M. Davies and M. Sandler, "On the Use of Phase
  and Energy for Musical Onset Detection in the Complex Domain," IEEE
  Signal Processing Letters, vol. 11, no. 6, June 2004.

Built from the paper's description only. This module does **not** read or
copy BTrack's C++ source (BTrack is GPL-3.0 and this benchmarking prototype
must stay clean of it) — the algorithm's shape was already known from the
paper: for each STFT bin, predict this frame's complex value from the
previous two frames (predicted magnitude = previous frame's magnitude;
predicted phase = previous phase plus the previous phase increment, i.e.
the linear/constant-phase-advance assumption), then take the Euclidean
distance between the predicted and observed complex spectra, summed across
bins, as the frame's onset detection function (ODF) value. Purely causal:
no centering, no lookahead, uses only past frames (the current frame plus
its two immediate predecessors).

This exists purely as a **benchmarking prototype** for
`tools/beat-tracker-bench/` (auto-vj-v3 roadmap Part 0, Program B): testing
whether a hand-designed onset function closes the observation-function gap
between this project's own detector and madmom/BTrack (both of which land
on the same ~76% Acc1 ceiling against unicorn-viz's ~66%). It is never
imported by the shipped application.

Sample-rate independence: the analysis window is a fixed 1024 samples, but
the hop is derived from the caller's own sample rate as
``round(sample_rate / 100)`` so the output always lands on the exact 100 Hz
cadence `beat_grid.py`'s envelope ring expects (480 samples at 48000 Hz,
441 at 44100 Hz — both exact). Never hardcode a specific rate/hop pair; the
production capture rate is whatever PipeWire's `default_samplerate`
actually is, read at runtime by `unicornviz/audio/capture.py` and pushed
into `Analyzer.set_sample_rate()` (see that module's own `_ASSUMED_SAMPLE_
RATE` comment) — 48000 Hz is simply what this bench run uses because it
matches `track_replay.py`'s `TARGET_SR` and the rest of this bench's own
standard rate, not because it is the only supported value here.

numpy only, no new dependencies. Vectorized per-frame (one small rfft per
hop); this is a benchmarking prototype, not a hot-path implementation.
"""
from __future__ import annotations

import logging
from collections import deque

import numpy as np

logger = logging.getLogger(__name__)

_FFT_SIZE = 1024
_ODF_RATE_HZ = 100.0
# Causal running-median/MAD normalization window for turning the raw
# (unbounded, track-dependent-scale) ODF value into a continuous z-score-
# like quantity comparable to this project's own onset "strength"
# (analyzer.py's OnsetEvent.strength -- always >= 1.0 at a detected onset,
# derived the same way: (value - median) / MAD over a trailing window).
# 8 s matches beat_grid.py's own ACF envelope window (_V2_ENV_WINDOW_S) so
# the normalization horizon is the same order of magnitude as what the
# tracker's own comb filter looks back over.
_NORM_WINDOW_S = 8.0
_NORM_MIN_HISTORY = 8  # ticks before the running median/MAD is trusted


def _princarg(phase: np.ndarray) -> np.ndarray:
    """Wrap phase (radians) into (-pi, pi]."""
    return np.mod(phase + np.pi, 2.0 * np.pi) - np.pi


class ComplexOnsetDetector:
    """Streams PCM audio through a causal complex-domain onset detection function.

    Lifecycle mirrors `tools/beat-tracker-bench/madmom/adapter.py`'s
    `ExternalBeatTracker`: call `warm_up(sample_rate)` once, then `feed()`
    once per incoming PCM block (any block size — smaller than one hop is
    buffered until enough audio has accumulated, matching the madmom
    adapter's own ring-buffer pattern). Unlike that adapter, this class is
    not itself a beat tracker: `feed()` returns the list of `(t, odf_z)`
    ticks completed by this call, at a fixed 100 Hz cadence (`t` is audio
    time in seconds), so a caller can push them directly into a
    `beat_grid.py`-style envelope ring in place of its usual onset-event
    stream. Not thread-safe; one instance per audio stream.
    """

    def __init__(self, fft_size: int = _FFT_SIZE) -> None:
        """Store the analysis window size; per-stream state is set in `warm_up()`."""
        self._fft_size = int(fft_size)
        self._window: np.ndarray = np.hanning(self._fft_size).astype(np.float64)
        n_bins = self._fft_size // 2 + 1

        self._sample_rate: int | None = None
        self._hop: int = 0
        self._pcm = np.zeros(0, dtype=np.float64)
        self._pcm_offset = 0
        self._next_frame_index = 0

        # Two-frame magnitude/phase history for the phase-and-energy
        # prediction (Bello et al. section III): frame n needs frames
        # n-1 and n-2 to predict its own complex spectrum.
        self._mag_prev = np.zeros(n_bins, dtype=np.float64)
        self._mag_prev2 = np.zeros(n_bins, dtype=np.float64)
        self._phase_prev = np.zeros(n_bins, dtype=np.float64)
        self._phase_prev2 = np.zeros(n_bins, dtype=np.float64)
        self._frames_seen = 0

        # Causal running-median/MAD normalization state.
        self._raw_history: deque[float] = deque()
        self._raw_window_n = 0

    def warm_up(self, sample_rate: int) -> None:
        """Reset per-stream state and derive the 100 Hz hop for `sample_rate`.

        Must be called before `feed()`.
        """
        self._sample_rate = int(sample_rate)
        self._hop = max(1, int(round(self._sample_rate / _ODF_RATE_HZ)))
        self._raw_window_n = max(1, int(round(_NORM_WINDOW_S * _ODF_RATE_HZ)))
        self._pcm = np.zeros(0, dtype=np.float64)
        self._pcm_offset = 0
        self._next_frame_index = 0
        self._mag_prev[:] = 0.0
        self._mag_prev2[:] = 0.0
        self._phase_prev[:] = 0.0
        self._phase_prev2[:] = 0.0
        self._frames_seen = 0
        self._raw_history.clear()

    def feed(
        self, block: np.ndarray, block_start_s: float = 0.0,  # noqa: ARG002
    ) -> list[tuple[float, float]]:
        """Consume one live-cadence PCM block (mono float, any dtype/size).

        `block_start_s` is accepted for interface parity with the madmom
        adapter but is not needed here: hop boundaries are tracked purely
        by sample count fed so far, the same pattern the madmom adapter
        uses for its own frame cadence.

        Returns the `(t, odf_z)` ticks completed within this call, oldest
        first. `t` is audio time in seconds at the end of the analysis
        window (causal: the window never extends past `t`). `odf_z` is the
        causally-normalized, non-negative onset strength described in the
        module docstring — 0.0 for the first two hops of a stream (not
        enough frame history yet for a phase prediction).
        """
        if self._sample_rate is None:
            raise RuntimeError('warm_up() must be called before feed()')
        samples = np.asarray(block, dtype=np.float64).reshape(-1)
        self._pcm = np.concatenate([self._pcm, samples])

        ticks: list[tuple[float, float]] = []
        while True:
            frame_end = (self._next_frame_index + 1) * self._hop
            if frame_end > self._pcm_offset + len(self._pcm):
                break
            local_end = frame_end - self._pcm_offset
            local_start = local_end - self._fft_size
            if local_start < 0:
                window = np.concatenate((
                    np.zeros(-local_start, dtype=np.float64),
                    self._pcm[:local_end],
                ))
            else:
                window = self._pcm[local_start:local_end]
            raw = self._process_frame(window)
            t = frame_end / self._sample_rate
            ticks.append((t, self._normalize(raw)))
            self._next_frame_index += 1

        # Keep only the trailing history a future frame could still need.
        if len(self._pcm) > self._fft_size:
            trim = len(self._pcm) - self._fft_size
            self._pcm = self._pcm[trim:]
            self._pcm_offset += trim
        return ticks

    def _process_frame(self, window: np.ndarray) -> float:
        """Run one causal frame through the complex-domain ODF (Bello et al. eq. 2-4)."""
        windowed = window * self._window
        spec = np.fft.rfft(windowed)
        mag = np.abs(spec)
        phase = np.angle(spec)
        self._frames_seen += 1

        if self._frames_seen <= 2:
            # Not enough history for a two-frame phase prediction yet.
            odf = 0.0
        else:
            mag_pred = self._mag_prev
            # Constant-phase-advance assumption: predicted phase = previous
            # phase + previous phase increment = 2*phase[n-1] - phase[n-2].
            phase_pred = _princarg(2.0 * self._phase_prev - self._phase_prev2)
            # Euclidean distance between predicted and observed complex
            # values via the law of cosines, summed across bins.
            d2 = (
                mag ** 2 + mag_pred ** 2
                - 2.0 * mag * mag_pred * np.cos(phase - phase_pred)
            )
            odf = float(np.sqrt(np.clip(d2, 0.0, None)).sum())

        self._mag_prev2 = self._mag_prev
        self._mag_prev = mag
        self._phase_prev2 = self._phase_prev
        self._phase_prev = phase
        return odf

    def _normalize(self, raw: float) -> float:
        """Causal running median/MAD z-score of `raw`, floored at 0.0.

        Matches the sign convention of this project's own onset strength
        (analyzer.py's `OnsetEvent.strength`): "how far above the recent
        baseline," never negative. Uses only values seen so far (the
        history deque is appended to after computing this tick's z-score,
        and trimmed to `_raw_window_n` ticks — an 8 s trailing window), so
        this stays causal end to end.
        """
        hist = self._raw_history
        if len(hist) >= _NORM_MIN_HISTORY:
            arr = np.fromiter(hist, dtype=np.float64, count=len(hist))
            med = float(np.median(arr))
            mad = max(float(np.median(np.abs(arr - med))), 1e-6)
            z = max(0.0, (raw - med) / mad)
        else:
            z = 0.0
        hist.append(raw)
        while len(hist) > self._raw_window_n:
            hist.popleft()
        return z
