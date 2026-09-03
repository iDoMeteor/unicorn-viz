"""Control-row onset source: this project's own existing spectral-flux
onset value, resampled to 100 Hz and fed through the SAME direct-write-
to-ring path (`v3_odf_tracker.py`) the complex-domain "odf" row already
uses.

Why this exists: the "odf" row (`complex_onset.py` + `v3_odf_tracker.py`)
changes two things at once relative to stock production behavior — the
onset function itself (complex-domain vs this project's spectral flux)
*and* the write path (a continuous 100 Hz direct ring write vs discrete,
peak-picked `OnsetEvent` pulses). This "stock-odf" control row isolates
the write-path variable alone: same onset *function* production already
uses (`unicornviz/audio/analyzer.py`'s per-block `spectral_flux`, before
its own peak-picking/adaptive-threshold step), routed through the direct-
write path instead of the discrete-event path. If this control lands near
the stock/e5 rows, the complex-domain onset function is carrying the
"odf" row's gain; if it lands near the "odf" row instead, the write path
itself was the effect.

`StockFluxOnsetSource` does not run its own spectral analysis — the
caller already runs `Analyzer.process()` for bands/energy/kick_regularity
and reads `audio.spectral_flux` off the returned `AudioData` each block;
this class only resamples that already-computed value onto the fixed
100 Hz tick grid (zero-order hold — mirrors `Analyzer`'s own internal
`_push_envelope()` resampling, read there for the pattern, not imported)
and normalizes it the same way `complex_onset.py` normalizes its ODF (see
`causal_norm.py`), so the two onset sources are on the same scale before
either one is written into the ring.
"""
from __future__ import annotations

import logging

from causal_norm import CausalMedianMadNormalizer

logger = logging.getLogger(__name__)

_ODF_RATE_HZ = 100.0


class StockFluxOnsetSource:
    """Resamples one Analyzer's per-block `spectral_flux` onto a 100 Hz stream.

    Lifecycle: call `warm_up(sample_rate)` once, then `feed_flux(flux_value,
    block_start_s, block_end_s)` once per `Analyzer.process()` call the
    caller already makes (`flux_value` is that call's `audio.spectral_flux`).
    Returns the `(t, odf_z)` ticks completed within `[block_start_s,
    block_end_s)`, zero-order-held at `flux_value` (the analyzer does not
    compute intra-block flux, so this is the same approximation its own
    internal envelope-threshold ring already makes). Not thread-safe; one
    instance per stream.
    """

    def __init__(self) -> None:
        self._next_t = 0.0
        self._normalizer = CausalMedianMadNormalizer(rate_hz=_ODF_RATE_HZ)

    def warm_up(self, sample_rate: int) -> None:  # noqa: ARG002 -- kept for interface parity with ComplexOnsetDetector
        """Reset per-stream state. `sample_rate` is accepted for interface
        parity with `ComplexOnsetDetector.warm_up()` but unused: this class
        resamples onto a fixed 100 Hz tick grid measured in audio-time
        seconds, not samples."""
        self._next_t = 0.0
        self._normalizer.reset()

    def feed_flux(
        self, flux_value: float, block_start_s: float, block_end_s: float,  # noqa: ARG002
    ) -> list[tuple[float, float]]:
        """Emit the 100 Hz ticks covered by `[block_start_s, block_end_s)`,
        each holding `flux_value` (zero-order hold — the analyzer computes
        one flux value per block, not per 10 ms slot)."""
        ticks: list[tuple[float, float]] = []
        step = 1.0 / _ODF_RATE_HZ
        while self._next_t < block_end_s:
            ticks.append((self._next_t, self._normalizer.normalize(float(flux_value))))
            self._next_t += step
        return ticks
