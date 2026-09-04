"""Adapter that wraps Essentia's streaming tempo trackers behind a
per-block ``feed()`` interface.

This module exists purely for **dev-side benchmarking**: it lets us feed
raw PCM audio into Essentia's causal/real-time-oriented beat trackers
(``RhythmExtractor2013`` configured with ``method='degara'``, which is
built on ``BeatTrackerDegara`` / ``TempoTapDegara``) and read back a
running BPM estimate, so the result can be compared against
unicorn-viz's own in-house beat tracker. It is never imported by the
shipped application — see ``README.md`` in this directory for the full
rationale, the AGPL-3.0 licensing reason that isolation matters, and the
quirks discovered while bridging Essentia's dataflow-graph streaming
model into a simple frame-by-frame API.

Key finding from bridging the two models (see README "Quirks" section
for the full investigation): Essentia's streaming composite algorithms
(``BeatTrackerDegara``, ``RhythmExtractor2013``, and the ``TempoTapDegara``
they are built on) do not incrementally refine a result across separate
``essentia.run()`` calls. Each one only computes when it observes
``shouldStop()`` (an end-of-stream condition on its input), and it
computes over whatever samples were pushed into *that* run, not a
persistent history carried between calls. To get a running estimate that
actually improves as more audio arrives, this adapter keeps its own
trailing buffer of recently fed PCM in Python and periodically rebuilds a
small streaming network — one ``VectorInput`` feeding
``RhythmExtractor2013`` into a fresh ``essentia.Pool`` — and runs it once
over that whole buffer. That single-shot-per-checkin pattern is standard
Essentia usage (a ``VectorInput`` streamed to completion in one
``essentia.run()`` call); what is unusual here is that we treat "one
checkin" as "reprocess the trailing window from scratch" rather than
"process only the new samples", because the library does not expose a
cheaper incremental path for these algorithms.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

try:
    import essentia
    import essentia.streaming as es
except ImportError as exc:  # pragma: no cover - exercised only outside the venv
    raise ImportError(
        "essentia is not installed. Run this tool from its isolated venv: "
        "tools/beat-tracker-bench/essentia/.venv (see README.md)."
    ) from exc

# The streaming RhythmExtractor2013/BeatTrackerDegara/TempoTapDegara family
# hard-requires 44100 Hz input (documented on each algorithm) and produces
# garbage silently otherwise, so this is the only rate the adapter will
# hand to Essentia. Audio fed at a different rate is resampled internally.
_ESSENTIA_SAMPLE_RATE = 44100

# How much recently fed audio the adapter keeps for re-analysis. Chosen
# because TempoTapDegara's own internal analysis frame is 6 s with a 1.5 s
# hop (see BeatTrackerDegara/TempoTapDegara docs); empirically the BPM
# estimate on a stationary click track is already stable well within 10-15 s
# of audio (see README "Quirks"), so 30 s comfortably covers convergence
# without letting the per-checkin reprocessing cost grow unbounded on long
# inputs.
_TRAILING_WINDOW_S = 30.0

# Minimum trailing audio required before attempting a first estimate.
# Below this, a single-shot RhythmExtractor2013 run reliably returns 0.0
# (see README "Quirks" for the empirical block-size sweep that established
# this floor).
_MIN_AUDIO_S = 2.0

# Recompute at most this often (in seconds of newly fed audio) rather than
# on every feed() call, since each recompute reprocesses the whole trailing
# window from scratch (see module docstring).
_RECOMPUTE_INTERVAL_S = 1.0


def _resample_linear(block: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample ``block`` from ``orig_sr`` to ``target_sr`` by linear interpolation.

    This is a plain ``numpy.interp`` resample with no anti-aliasing filter,
    which is adequate for feeding a click track or well-behaved music
    signal into a tempo tracker but is not broadcast-quality resampling.
    Prefer feeding audio that is already 44100 Hz (both the ``--audio``
    loader and ``--synthetic-click`` generator in ``run.py`` do this by
    default) so this path is never exercised.
    """
    if orig_sr == target_sr or block.size == 0:
        return block.astype(np.float32, copy=False)
    duration = block.size / orig_sr
    n_target = max(1, round(duration * target_sr))
    src_x = np.linspace(0.0, duration, num=block.size, endpoint=False)
    dst_x = np.linspace(0.0, duration, num=n_target, endpoint=False)
    return np.interp(dst_x, src_x, block).astype(np.float32)


class ExternalBeatTracker:
    """Runs Essentia's streaming ``RhythmExtractor2013`` (degara method) as a
    per-block-fed running BPM estimator.

    Lifecycle: call :meth:`warm_up` once with the input sample rate, then
    call :meth:`feed` for each incoming PCM block in order. :attr:`bpm` and
    :attr:`confidence` always return the most recently computed estimate
    (0.0 / 0.0 before enough audio has accumulated). Not thread-safe; feed
    blocks from a single thread in chronological order, matching the shape
    of the sibling BTrack/madmom/BeatNet adapters this was built alongside.
    """

    def __init__(
        self,
        trailing_window_s: float = _TRAILING_WINDOW_S,
        min_audio_s: float = _MIN_AUDIO_S,
        recompute_interval_s: float = _RECOMPUTE_INTERVAL_S,
    ) -> None:
        """Create the adapter with default (or overridden) analysis window sizes.

        Parameters mirror the module-level defaults and exist mainly so a
        benchmark harness can sweep them; the CLI in ``run.py`` does not
        expose them as flags to keep its surface small.
        """
        self._trailing_window_s = trailing_window_s
        self._min_audio_s = min_audio_s
        self._recompute_interval_s = recompute_interval_s
        self._sample_rate: int | None = None
        self._buffer: np.ndarray = np.zeros(0, dtype=np.float32)
        self._total_fed_s: float = 0.0
        self._audio_since_recompute_s: float = 0.0
        self._bpm: float = 0.0
        self._confidence: float = 0.0

    def warm_up(self, sample_rate: int) -> None:
        """Record the sample rate that subsequent :meth:`feed` blocks use.

        Must be called once before the first :meth:`feed` call. Does not
        touch Essentia itself: each analysis pass builds its own short-lived
        streaming network (see module docstring), so there is nothing to
        pre-warm on the Essentia side beyond Python import and JIT-free
        C++ algorithm construction, which is already fast.
        """
        self._sample_rate = int(sample_rate)

    def feed(self, block: np.ndarray, block_start_s: float) -> None:
        """Consume one live-cadence PCM block (mono float32).

        Appends the block to an internal trailing buffer and, once enough
        audio has accumulated and the recompute throttle allows it, runs a
        fresh Essentia streaming analysis over that trailing buffer to
        refresh :attr:`bpm` and :attr:`confidence`. ``block_start_s`` is not
        used by the analysis itself (Essentia only sees raw samples); it is
        accepted to match the shared adapter interface used by the CLI's
        tick-series output.
        """
        if self._sample_rate is None:
            raise RuntimeError("warm_up() must be called before feed().")
        if block.ndim != 1:
            block = np.reshape(block, -1)
        block = block.astype(np.float32, copy=False)

        self._buffer = np.concatenate([self._buffer, block])
        block_duration_s = block.size / self._sample_rate
        self._total_fed_s += block_duration_s
        self._audio_since_recompute_s += block_duration_s

        max_samples = round(self._trailing_window_s * self._sample_rate)
        if self._buffer.size > max_samples:
            self._buffer = self._buffer[-max_samples:]

        if self._total_fed_s < self._min_audio_s:
            return
        if self._audio_since_recompute_s < self._recompute_interval_s:
            return

        self._audio_since_recompute_s = 0.0
        self._recompute()

    def _recompute(self) -> None:
        """Run one single-shot Essentia streaming analysis over the trailing buffer."""
        analysis_audio = _resample_linear(
            self._buffer, self._sample_rate, _ESSENTIA_SAMPLE_RATE
        )
        if analysis_audio.size == 0:
            return

        vector_input = es.VectorInput(analysis_audio)
        extractor = es.RhythmExtractor2013(method="degara")
        pool = essentia.Pool()

        vector_input.data >> extractor.signal
        extractor.bpm >> (pool, "bpm")
        extractor.confidence >> (pool, "confidence")
        # Declared outputs must all be connected (or explicitly discarded)
        # before the network can run.
        extractor.ticks >> None
        extractor.estimates >> None
        extractor.bpmIntervals >> None

        try:
            essentia.run(vector_input)
        except RuntimeError:
            logger.debug("Essentia RhythmExtractor2013 run failed on this window", exc_info=True)
            return

        names = pool.descriptorNames()
        if "bpm" in names:
            bpm = float(pool["bpm"])
            if bpm > 0.0:
                self._bpm = bpm
        if "confidence" in names:
            self._confidence = float(pool["confidence"])

    @property
    def bpm(self) -> float:
        """Most recently computed running BPM estimate (0.0 before one exists)."""
        return self._bpm

    @property
    def confidence(self) -> float:
        """Confidence of the current estimate.

        Always 0.0: the 'degara' method of ``RhythmExtractor2013`` does not
        estimate confidence (Essentia's own documentation says to ignore
        this output for that method), which happens to line up neatly with
        the shared adapter interface's convention for libraries that don't
        expose one.
        """
        return self._confidence
