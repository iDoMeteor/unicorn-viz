"""Scratch `BeatTrackerV3` subclass that writes the envelope ring directly
from an external 100 Hz onset-detection-function (ODF) stream.

Row 3 of the onset-prototype bench (auto-vj-v3 roadmap Part 0, Program B)
needs v3's HMM tempo decision and comb-filter observation machinery
completely unchanged, fed by the complex-domain onset function
(`complex_onset.py`) instead of this project's own spectral-flux/
adaptive-threshold onset detector (`unicornviz/audio/analyzer.py`'s
`Analyzer.process()` + `drain_onsets()`). That means bypassing the
*onset-event-driven* envelope write path — the discrete, peak-picked
`OnsetEvent` stream `BeatTracker.update()` normally consumes — while
leaving the ring's own contract (write index, wraparound, log-compression
of pulse strength) exactly as `beat_grid_e5.py` defines it.

How the bypass works: `BeatTracker.update()` (see `beat_grid_e5.py`,
~line 2211) does one of two things with the ``onsets`` argument each
tick — for each queued `OnsetEvent`, advance-then-pulse the ring at that
event's own timestamp; otherwise (``onsets`` falsy), just zero-fill the
ring up to ``now`` via `_advance_envelope()`. This class is always driven
with ``onsets=None``, so only the zero-fill path ever runs — and this
class overrides the *single* primitive both `_advance_envelope()` and
`_pulse_envelope()` funnel through in the E5-patched clock,
`_advance_env_to_index()`, so that "zero-fill" instead writes the real
ODF value for each slot's time. `_pulse_envelope()` itself is never
called (nothing in this class's driving loop ever passes ``onsets``), so
it does not need overriding — only the shared write-through primitive
does. Every other part of the tracker (ACF/comb computation, the v3 HMM
observation likelihood and transition update, phase machinery, drop-score
terms) runs completely untouched, reading the same `_env_buf` ring
whichever path filled it.

The per-slot value written is normalized and log-compressed the same way
`_pulse_envelope()` compresses a real onset strength (``1 +
log1p(strength - 1)`` above 1.0) — see that method's own docstring in
`beat_grid_e5.py` for why (bounding one freak transient's leverage over
the 8 s ACF window). `complex_onset.ComplexOnsetDetector.feed()` already
produces a continuous, causally-normalized, non-negative z-score-like
stream (see its own docstring), so the only transformation this class
adds at write time is that same compression — no new tuning, no new
normalization pass.
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def build_odf_tracker_class(beat_tracker_v3_cls: type) -> type:
    """Return an ODF-driven subclass of `beat_tracker_v3_cls`.

    Takes the class rather than importing it directly so this module has
    no hard dependency on which `beat_grid_e5.py` copy the caller loaded
    (dynamic-by-path, per this bench's own convention) — the row-3 driver
    passes in the `BeatTrackerV3` it already loaded from
    `beat_grid_e5.py`. Asserts that module's `_V2_ENV_RATE` is the 100 Hz
    this class hardcodes (matching `complex_onset.py`'s `_ODF_RATE_HZ`),
    so a future change to either constant fails loudly instead of quietly
    misaligning the ODF stream's slot spacing from the ring's.
    """
    import sys

    env_rate = getattr(sys.modules[beat_tracker_v3_cls.__module__], '_V2_ENV_RATE', None)
    if env_rate != 100.0:
        raise AssertionError(
            f'{beat_tracker_v3_cls.__module__}._V2_ENV_RATE is {env_rate!r}, '
            'expected 100.0 (ODFDrivenBeatTrackerV3 assumes it matches '
            "complex_onset.py's _ODF_RATE_HZ)."
        )

    class ODFDrivenBeatTrackerV3(beat_tracker_v3_cls):  # type: ignore[misc,valid-type]
        """`BeatTrackerV3` fed by an external ODF stream instead of onset events.

        Call `set_odf_stream(times, values)` once with the whole track's
        precomputed `(t, odf_z)` ticks (see `complex_onset.py`) before
        driving `update()` — always with ``onsets=None`` — at the normal
        60 Hz tick cadence. Precomputing the stream up front is a driver-
        loop convenience only; the ODF *function* itself
        (`ComplexOnsetDetector`) is still strictly causal (no lookahead
        past its own current frame) when it produces that stream.
        """

        def __init__(self, cfg: dict | None = None) -> None:
            super().__init__(cfg)
            self._odf_times: np.ndarray = np.zeros(0, dtype=np.float64)
            self._odf_values: np.ndarray = np.zeros(0, dtype=np.float64)

        def set_odf_stream(self, times: np.ndarray, values: np.ndarray) -> None:
            """Install the external ODF stream this tracker's envelope reads from."""
            self._odf_times = np.asarray(times, dtype=np.float64)
            self._odf_values = np.asarray(values, dtype=np.float64)

        def _odf_value_at(self, t: float) -> float:
            """Nearest ODF sample to audio time `t` (0.0 if the stream is empty)."""
            times = self._odf_times
            if times.size == 0:
                return 0.0
            idx = int(np.searchsorted(times, t))
            if idx <= 0:
                return float(self._odf_values[0])
            if idx >= times.size:
                return float(self._odf_values[-1])
            before_t, after_t = times[idx - 1], times[idx]
            nearer = idx - 1 if (t - before_t) <= (after_t - t) else idx
            return float(self._odf_values[nearer])

        def _advance_env_to_index(self, want: int) -> None:
            """Write real ODF values through index `want`, in place of zero-fill.

            Mirrors `beat_grid_e5.py`'s own `_advance_env_to_index()`
            exactly (same write-index advance, same wraparound/`_env_
            filled` bookkeeping) — only the written value changes, from a
            constant 0.0 to the ODF sample for that slot's time, log-
            compressed the same way `_pulse_envelope()` compresses a real
            onset strength.
            """
            while self._env_next_idx < want:
                t_slot = self._env_t0 + self._env_next_idx / 100.0  # _V2_ENV_RATE, asserted in build_odf_tracker_class()
                s = self._odf_value_at(t_slot)
                if s > 1.0:
                    s = 1.0 + float(np.log1p(s - 1.0))
                self._env_buf[self._env_write_idx] = s
                self._env_write_idx = (self._env_write_idx + 1) % self._env_len
                if self._env_write_idx == 0:
                    self._env_filled = True
                self._env_next_idx += 1

    return ODFDrivenBeatTrackerV3
