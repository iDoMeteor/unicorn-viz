"""Adapter that wraps BeatNet's causal "online" mode behind the shared
``ExternalBeatTracker`` interface used by the beat-tracker benchmarking
harness.

This module is dev-only tooling for comparing unicorn-viz's own in-house
beat tracker against BeatNet (https://github.com/mjhydri/BeatNet, CRNN +
particle filtering, ISMIR 2021). It is intentionally standalone: nothing
under ``unicornviz/`` imports it, and it is never installed into the
project's shipped runtime environment.

Why "online" mode and not "streaming" mode
-------------------------------------------
BeatNet exposes four working modes. "Streaming" mode opens a live
microphone via ``pyaudio`` -- unusable (and unwanted) for a benchmarking
harness fed from an in-memory buffer. "Online" mode runs the same causal
algorithm as "realtime" mode but reads a pre-supplied audio array/file
faster than real time, producing identical results to "realtime". This
adapter drives "online" mode exclusively; "streaming" mode is never
invoked (see ``pyaudio`` note below).

Why buffering + periodic re-run instead of true incremental feeding
---------------------------------------------------------------------
BeatNet's public API (``BeatNet.process(audio_path)``) takes a whole
in-memory array or file path per call; there is no documented method to
push one small PCM block at a time into a live-updating causal state.
Internally, "online" mode is still just as causal as "realtime" mode --
it extracts activations for the whole given array in one forward pass and
decodes them with a particle filter that starts fresh for that call.

To approximate genuine incremental feeding, this adapter takes the
"accumulate buffered audio and periodically re-run BeatNet's online
inference over the buffer-so-far" approach called out as acceptable in
the task brief: each call to :meth:`ExternalBeatTracker.feed` appends the
block to an internal buffer, and every ``recompute_stride_s`` seconds of
newly buffered audio, the adapter re-runs BeatNet's online algorithm
(CRNN activation extraction + a freshly reset particle filter) over the
*entire* buffer collected so far, as if it were a brand-new file. This
keeps the algorithm's own causality guarantee (it never sees audio beyond
"now") but means later re-runs redundantly reprocess earlier audio, and
the running BPM only updates once per ``recompute_stride_s`` rather than
every block. This is a fairness caveat for later comparison against a
tracker that updates every block -- see README.md.

A second consequence: the very last few blocks fed (fewer than
``recompute_stride_s`` seconds worth) will not trigger another recompute,
so the final cached BPM can lag the true end of the buffer by up to
``recompute_stride_s`` seconds. This is documented rather than patched
around, to keep the adapter's four public methods exactly matching the
shared sibling interface (no extra "flush" method).

pyaudio stub
------------
BeatNet's ``BeatNet.py`` does an unconditional module-level
``import pyaudio``, even though pyaudio is only used inside the
microphone-based "streaming" mode this adapter never invokes. Installing
real ``pyaudio`` needs the system PortAudio headers, which are not
present on this machine and would require a system package manager
install this tool is not permitted to perform. This tool's isolated venv
therefore carries a minimal stub ``pyaudio`` module (see
``.venv/lib*/python3.11/site-packages/pyaudio.py``) that satisfies the
import and raises ``NotImplementedError`` if "streaming" mode is ever
accidentally exercised. See README.md for the full rationale.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# BeatNet's CRNN and feature pipeline are fixed to operate at 22050 Hz
# (BeatNet.__init__ sets self.sample_rate = 22050 unconditionally).
_BEATNET_SAMPLE_RATE = 22050

# BeatNet ships three pretrained CRNN weight sets (1=GTZAN, 2=Ballroom,
# 3=Rock_corpus). 1 is used as a generic default; it is not tuned for any
# particular genre of the audio this adapter will be benchmarked against.
_DEFAULT_MODEL = 1

# How often (in seconds of newly buffered audio) to re-run BeatNet's
# online inference over the buffer collected so far. Smaller values track
# tempo changes more closely but cost more CPU, since each re-run
# reprocesses the whole buffer from the start.
_DEFAULT_RECOMPUTE_STRIDE_S = 0.5

# Minimum amount of buffered audio required before the first recompute.
# BeatNet's log-mel feature extractor needs a handful of frames to
# produce anything meaningful, and a very short buffer cannot contain a
# usable inter-beat interval anyway.
_DEFAULT_MIN_ANALYSIS_S = 2.0

# Only the trailing beats are used to compute the running BPM, so the
# estimate can track tempo drift instead of averaging over the full
# buffer.
_TRAILING_BEATS_FOR_BPM = 16


class ExternalBeatTracker:
    """BeatNet-backed implementation of the shared benchmarking interface.

    Lifecycle: construct, call :meth:`warm_up` once with the live sample
    rate, then call :meth:`feed` repeatedly with sequential mono PCM
    blocks. Read :attr:`bpm` / :attr:`confidence` at any time; they
    reflect the most recent completed BeatNet re-run (see module
    docstring for why this is periodic rather than per-block).

    Not thread-safe: intended for single-threaded offline/online-mode
    benchmarking loops, not for concurrent feed/read access.
    """

    def __init__(
        self,
        recompute_stride_s: float = _DEFAULT_RECOMPUTE_STRIDE_S,
        min_analysis_s: float = _DEFAULT_MIN_ANALYSIS_S,
        model: int = _DEFAULT_MODEL,
    ) -> None:
        """Configure recompute cadence and which pretrained model to load.

        Parameters are adapter-specific tuning knobs, not part of the
        shared four-method interface; they only affect how often and
        with which BeatNet weights this adapter re-runs inference.
        """
        self._recompute_stride_s = recompute_stride_s
        self._min_analysis_s = min_analysis_s
        self._model_id = model
        self._beatnet: Any = None
        self._input_sample_rate: int | None = None
        self._buffer_chunks: list[np.ndarray] = []
        self._buffer_len_samples = 0
        self._last_recompute_len_samples = 0
        self._bpm = 0.0
        self._confidence = 0.0

    def warm_up(self, sample_rate: int) -> None:
        """Load BeatNet's pretrained CRNN weights and reset internal state.

        Must be called once before :meth:`feed`. ``sample_rate`` is the
        rate of the PCM blocks that will be passed to :meth:`feed`; it
        need not equal BeatNet's fixed 22050 Hz operating rate, since
        :meth:`feed` resamples each block internally.
        """
        # Imported here, not at module scope, so simply importing this
        # adapter module never pulls in torch/madmom/librosa -- only
        # calling warm_up() does.
        from BeatNet.BeatNet import BeatNet

        self._input_sample_rate = sample_rate
        self._beatnet = BeatNet(
            self._model_id,
            mode="online",
            inference_model="PF",
            plot=[],
            thread=False,
            device="cpu",
        )
        self._reset_estimator()
        self._buffer_chunks = []
        self._buffer_len_samples = 0
        self._last_recompute_len_samples = 0
        self._bpm = 0.0
        self._confidence = 0.0

    def _reset_estimator(self) -> None:
        """Replace BeatNet's stateful particle filter with a fresh one.

        ``BeatNet.estimator`` (a ``particle_filter_cascade``) is created
        once in ``BeatNet.__init__`` and normally accumulates state
        across repeated calls to ``BeatNet.process()``. Since each
        recompute in this adapter re-runs inference over the *whole*
        buffer from the start (see module docstring), the estimator must
        be reset first each time to match what a brand-new
        ``BeatNet(...).process(buffer)`` call on that buffer would do.
        """
        from BeatNet.particle_filtering_cascade import particle_filter_cascade

        self._beatnet.estimator = particle_filter_cascade(
            beats_per_bar=[], fps=50, plot=[], mode=self._beatnet.mode
        )

    def feed(self, block: np.ndarray, block_start_s: float) -> None:
        """Consume one live-cadence PCM block (mono float32).

        Appends ``block`` (resampled to BeatNet's 22050 Hz if needed) to
        the internal buffer. Every ``recompute_stride_s`` seconds of new
        audio, re-runs BeatNet's online algorithm over the full buffer
        and updates the cached :attr:`bpm`. ``block_start_s`` is accepted
        for interface parity with sibling adapters but is not needed here
        since blocks are assumed to arrive in strict sequential order.
        """
        if self._beatnet is None:
            raise RuntimeError("warm_up() must be called before feed()")
        del block_start_s  # unused: blocks are consumed strictly in order

        block = np.asarray(block, dtype=np.float32).reshape(-1)
        if self._input_sample_rate != _BEATNET_SAMPLE_RATE:
            import librosa

            block = librosa.resample(
                block,
                orig_sr=self._input_sample_rate,
                target_sr=_BEATNET_SAMPLE_RATE,
            ).astype(np.float32)

        self._buffer_chunks.append(block)
        self._buffer_len_samples += block.shape[0]

        buffered_s = self._buffer_len_samples / _BEATNET_SAMPLE_RATE
        new_s = (
            self._buffer_len_samples - self._last_recompute_len_samples
        ) / _BEATNET_SAMPLE_RATE
        if buffered_s >= self._min_analysis_s and new_s >= self._recompute_stride_s:
            self._recompute()

    def _recompute(self) -> None:
        """Re-run BeatNet's causal online algorithm over the full buffer."""
        buffer = np.concatenate(self._buffer_chunks)
        self._reset_estimator()
        preds = self._beatnet.activation_extractor_online(buffer)
        beats = self._beatnet.estimator.process(preds)
        self._last_recompute_len_samples = self._buffer_len_samples

        bpm = _bpm_from_beats(beats)
        if bpm is not None:
            self._bpm = bpm
        # BeatNet's public (time, beat_number) output carries no per-beat
        # confidence score, so self._confidence is left at its default
        # 0.0 per the shared adapter contract.

    @property
    def bpm(self) -> float:
        """Most recent running BPM estimate.

        Stays ``0.0`` until at least ``min_analysis_s`` seconds have been
        fed. Reflects the last completed recompute, which can lag the
        true end of the fed audio by up to ``recompute_stride_s`` seconds
        (see module docstring).
        """
        return self._bpm

    @property
    def confidence(self) -> float:
        """Always ``0.0``: BeatNet does not expose a confidence score."""
        return self._confidence


def _bpm_from_beats(beats: np.ndarray | None) -> float | None:
    """Convert BeatNet's ``(time_s, beat_number)`` rows into a BPM value.

    Uses the median inter-beat interval over the trailing
    ``_TRAILING_BEATS_FOR_BPM`` beats so the estimate can track tempo
    drift. Returns ``None`` if there are too few beats to form an
    interval.
    """
    if beats is None or len(beats) < 2:
        return None
    times = np.asarray(beats)[:, 0]
    intervals = np.diff(times)
    intervals = intervals[intervals > 0]
    if intervals.size == 0:
        return None
    window = intervals[-_TRAILING_BEATS_FOR_BPM:]
    median_interval = float(np.median(window))
    if median_interval <= 0:
        return None
    return 60.0 / median_interval
