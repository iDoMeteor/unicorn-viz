"""Causal running-median/MAD normalization, shared by the onset-prototype's
ODF adapters.

Both `complex_onset.py` (the complex-domain onset function) and
`stock_flux_odf.py` (the "stock-odf" control row's spectral-flux source)
need to turn a raw, unbounded, track-dependent-scale onset value into a
continuous, non-negative z-score-like quantity before it can be written
into `v3_odf_tracker.py`'s direct-write envelope ring — comparable to this
project's own onset "strength" convention (`analyzer.py`'s `OnsetEvent.
strength`, always >= 1.0 at a detected onset, computed the same way:
`(value - median) / MAD` over a trailing window). Factored out here so
both adapters normalize identically and the "stock-odf" control row (which
exists specifically to isolate the write-path effect from the onset-
function effect) differs from the "odf" row *only* in which raw onset
value it feeds in, not in how that value gets scaled.
"""
from __future__ import annotations

from collections import deque

import numpy as np

_NORM_WINDOW_S = 8.0  # matches beat_grid.py's own ACF envelope window (_V2_ENV_WINDOW_S)
_NORM_MIN_HISTORY = 8  # ticks before the running median/MAD is trusted
_ODF_RATE_HZ = 100.0


class CausalMedianMadNormalizer:
    """Trailing-window median/MAD z-score, using only values seen so far.

    Call `normalize(raw)` once per tick, in time order; it both scores
    `raw` against the history collected before it and appends `raw` to
    that history for future ticks (causal end to end — no lookahead).
    """

    def __init__(self, window_s: float = _NORM_WINDOW_S, rate_hz: float = _ODF_RATE_HZ) -> None:
        self._window_n = max(1, int(round(window_s * rate_hz)))
        self._history: deque[float] = deque()

    def reset(self) -> None:
        """Clear all history (start of a new stream)."""
        self._history.clear()

    def normalize(self, raw: float) -> float:
        """Causal median/MAD z-score of `raw`, floored at 0.0.

        The MAD floor is relative to the window's own typical magnitude
        (10% of the mean absolute value), not a bare epsilon. A raw onset
        signal that is exactly 0.0 in a majority of frames (this project's
        own spectral flux is: it is effectively half-wave-rectified, see
        `stock_flux_odf.py`) pushes both the median AND the plain
        median-absolute-deviation to ~0, and a bare `1e-6` floor then
        turns any nonzero frame into a multi-million z-score before the
        ring's own log-compression saves it from overflow — the exact
        failure mode `analyzer.py`'s `_onset_threshold()` already
        documents and fixes for its own MAD floor (`_BEAT_ABS_FLOOR`,
        "the smallest meaningful flux scale", not a literal epsilon).
        Found live in this prototype (2026-09-03): the stock-flux control
        row's raw z-scores were landing in the tens of millions before
        this fix.
        """
        hist = self._history
        if len(hist) >= _NORM_MIN_HISTORY:
            arr = np.fromiter(hist, dtype=np.float64, count=len(hist))
            med = float(np.median(arr))
            raw_mad = float(np.median(np.abs(arr - med)))
            scale_floor = 0.1 * float(np.mean(np.abs(arr)))
            mad = max(raw_mad, scale_floor, 1e-6)
            z = max(0.0, (raw - med) / mad)
        else:
            z = 0.0
        hist.append(raw)
        while len(hist) > self._window_n:
            hist.popleft()
        return z
