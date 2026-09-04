"""Adapter wrapping madmom's online beat tracker behind a shared benchmarking
interface.

This module exists purely for **dev-only benchmarking**: comparing
unicorn-viz's own in-house beat tracker (`unicornviz/audio/beat_grid.py`,
not touched by this tool) against madmom's `RNNBeatProcessor` +
`DBNBeatTrackingProcessor(online=True)` pipeline. It is never imported by
the shipped application and is not referenced from `requirements.txt`.

madmom is dual-licensed: the source code is 2-clause BSD, but the bundled
pretrained model files (the `.pkl` files under `madmom/models/`) are
**CC BY-NC-SA 4.0** (non-commercial, share-alike, attribution required) —
see the "License" section of this directory's README.md for the exact text
and source. This adapter loads those models at runtime (`warm_up()`), so
any use of it inherits that non-commercial restriction; that's acceptable
for local dev-only benchmarking but must not be forgotten if this code is
ever repurposed.

Implementation notes
---------------------
madmom's own online-processing example (`madmom.processors.process_online`)
iterates a `FramedSignal(origin='online')` stream and calls each stateful
processor in the chain with `reset=False` so per-frame recurrent state
(LSTM hidden/cell state in `RNNBeatProcessor`, HMM forward-algorithm state
in `DBNBeatTrackingProcessor`) persists across calls. This adapter mirrors
that pattern manually instead of constructing madmom's `FramedSignal`
wrapper, because doing so let it work directly from arbitrary live-cadence
PCM blocks fed through `feed()`:

- Incoming PCM is buffered internally at madmom's expected 44100 Hz sample
  rate (`_MADMOM_SAMPLE_RATE`), resampling with `scipy.signal.resample_poly`
  if the live sample rate is anything else. Audio already at 44100 Hz never
  passes through the resampler and is therefore the most faithful path for
  benchmarking; other rates are a documented approximation (per-block
  resampling can introduce minor discontinuities at block edges).
- Every time `_HOP_SIZE` (441 samples, i.e. 100 fps) new samples have
  accumulated, a causal `_FRAME_SIZE` (2048 samples) window ending at that
  point is extracted (left-zero-padded only during the first frame, before
  enough history exists) and fed through `RNNBeatProcessor(online=True)`
  with `origin='stream', num_frames=1, reset=False` — this combination was
  verified empirically (see the directory's development notes) to be
  required to get exactly one activation value per hop; omitting
  `num_frames=1` makes madmom's default offline end-of-signal padding
  produce several extra boundary frames per call, which silently breaks the
  1-hop-in/1-activation-out cadence this adapter depends on.
- That single activation value is fed to `DBNBeatTrackingProcessor(
  online=True)` (`reset=False`), whose forward-algorithm state persists
  across calls the same way. Its `tempo` attribute is a running BPM
  estimate maintained internally by madmom itself (updated only when a new
  beat is registered; see `DBNBeatTrackingProcessor.process_online` in
  madmom's source) and is read directly for the `bpm` property.

madmom does not expose a dedicated confidence score for the DBN's current
state. `confidence` here is the most recent RNN beat-activation value
(madmom's own per-frame "probability of a beat" output, already in
[0, 1]) — a reasonable, honestly-labelled proxy rather than a true
posterior, per the shared interface's "0.0 if the library doesn't expose
one" fallback rule; using the RNN activation is a deliberate choice to
surface *some* signal rather than always reporting 0.0, since madmom does
expose that value.
"""

from __future__ import annotations

import logging
import warnings

import numpy as np

logger = logging.getLogger(__name__)

_MADMOM_SAMPLE_RATE = 44100
_FPS = 100.0
_FRAME_SIZE = 2048
_HOP_SIZE = int(round(_MADMOM_SAMPLE_RATE / _FPS))  # 441 samples


class ExternalBeatTracker:
    """Streams PCM audio through madmom's online RNN + DBN beat tracker.

    Lifecycle: call `warm_up()` once with the live sample rate, then call
    `feed()` once per incoming audio block (any block size; blocks smaller
    than one hop are buffered until enough audio has accumulated). Read
    `bpm` and `confidence` at any point to get the tracker's current running
    estimate. Not thread-safe; use one instance per audio stream.
    """

    def __init__(self, min_bpm: float = 55.0, max_bpm: float = 215.0) -> None:
        """Store tempo search bounds; heavy setup happens in `warm_up()`.

        Parameters
        ----------
        min_bpm, max_bpm
            Passed straight through to `DBNBeatTrackingProcessor`, which
            uses them to bound the beat state space it searches.
        """
        self._min_bpm = min_bpm
        self._max_bpm = max_bpm
        self._rnn = None
        self._dbn = None
        self._source_sample_rate: int | None = None
        self._pcm = np.zeros(0, dtype=np.float32)
        self._pcm_offset = 0
        self._next_frame_index = 0
        self._bpm = 0.0
        self._confidence = 0.0

    def warm_up(self, sample_rate: int) -> None:
        """Build the madmom processors and prime their recurrent state.

        Must be called before `feed()`. Running one silent frame through
        both processors here (rather than on the first real `feed()` call)
        keeps model loading and numpy's first-call overhead out of the
        benchmark's timing if a caller times `feed()` calls separately.
        """
        from madmom.features.beats import (
            DBNBeatTrackingProcessor,
            RNNBeatProcessor,
        )

        self._source_sample_rate = sample_rate
        self._rnn = RNNBeatProcessor(online=True)
        self._dbn = DBNBeatTrackingProcessor(
            online=True,
            fps=_FPS,
            min_bpm=self._min_bpm,
            max_bpm=self._max_bpm,
        )
        warm_frame = np.zeros(_FRAME_SIZE, dtype=np.float32)
        self._rnn(warm_frame, reset=True, origin='stream', num_frames=1)
        # A literal 0.0 activation makes the DBN's observation model take
        # log(0) internally; harmless (the resulting -inf is immediately
        # dominated by the transition model) but noisy, so silence the
        # RuntimeWarning during this throwaway warm-up call only.
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            self._dbn(0.0, reset=True)
        self._pcm = np.zeros(0, dtype=np.float32)
        self._pcm_offset = 0
        self._next_frame_index = 0
        self._bpm = 0.0
        self._confidence = 0.0

    def feed(self, block: np.ndarray, block_start_s: float) -> None:
        """Consume one live-cadence PCM block (mono float32).

        `block_start_s` is accepted for interface parity with sibling
        adapters but is not needed here: madmom's DBN tracks elapsed time
        internally via its own frame counter, driven purely by how many
        hops of audio have been fed so far.
        """
        if self._rnn is None or self._dbn is None:
            raise RuntimeError('warm_up() must be called before feed()')
        samples = np.asarray(block, dtype=np.float32).reshape(-1)
        if self._source_sample_rate != _MADMOM_SAMPLE_RATE:
            samples = _resample_to_madmom_rate(samples, self._source_sample_rate)
        self._pcm = np.concatenate([self._pcm, samples])

        while True:
            frame_end = (self._next_frame_index + 1) * _HOP_SIZE
            if frame_end > self._pcm_offset + len(self._pcm):
                break
            local_end = frame_end - self._pcm_offset
            local_start = local_end - _FRAME_SIZE
            if local_start < 0:
                window = np.concatenate((
                    np.zeros(-local_start, dtype=np.float32),
                    self._pcm[:local_end],
                ))
            else:
                window = self._pcm[local_start:local_end]
            self._process_frame(window)
            self._next_frame_index += 1

        # Keep only the trailing history a future frame could still need.
        if len(self._pcm) > _FRAME_SIZE:
            trim = len(self._pcm) - _FRAME_SIZE
            self._pcm = self._pcm[trim:]
            self._pcm_offset += trim

    def _process_frame(self, window: np.ndarray) -> None:
        """Run one causal frame through the RNN then the DBN."""
        activation = self._rnn(window, reset=False, origin='stream', num_frames=1)
        activation_value = float(np.asarray(activation))
        self._confidence = activation_value
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            self._dbn(activation_value, reset=False)
        # `tempo` is madmom's own running BPM estimate; it only changes when
        # a new beat is registered and otherwise holds its last value.
        self._bpm = float(self._dbn.tempo)

    @property
    def bpm(self) -> float:
        """Current running BPM estimate (0.0 before the first beat locks in)."""
        return self._bpm

    @property
    def confidence(self) -> float:
        """Most recent RNN beat-activation value, in [0, 1]; see module docstring."""
        return self._confidence


def _resample_to_madmom_rate(block: np.ndarray, source_sample_rate: int) -> np.ndarray:
    """Resample one PCM block from `source_sample_rate` to 44100 Hz.

    Uses polyphase resampling per block, which is only exact when
    `source_sample_rate` evenly reduces against 44100; for arbitrary rates
    it is a documented approximation (minor edge discontinuities between
    blocks are possible). Feed audio already at 44100 Hz to avoid this
    path entirely.
    """
    from math import gcd

    from scipy.signal import resample_poly

    divisor = gcd(_MADMOM_SAMPLE_RATE, source_sample_rate)
    up = _MADMOM_SAMPLE_RATE // divisor
    down = source_sample_rate // divisor
    return resample_poly(block, up, down).astype(np.float32)
