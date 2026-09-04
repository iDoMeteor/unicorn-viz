"""Adapter wrapping BTrack's causal, frame-by-frame beat tracker behind a
shared benchmarking interface.

This module exists purely for **dev-only benchmarking**: comparing
unicorn-viz's own in-house beat tracker (`unicornviz/audio/beat_grid.py`,
not touched by this tool) against Adam Stark's BTrack
(https://github.com/adamstark/BTrack). It is never imported by the shipped
application and is not referenced from `requirements.txt`.

BTrack is **GPL-3.0-or-later**. The `btrack_streaming` extension module this
adapter imports is custom pybind11 bindings written for this project (see
`btrack_streaming.cpp`) that link directly against BTrack's compiled C++
core, so the compiled `.so` is itself a GPL-3.0 derivative work -- see the
"License" section of this directory's README.md. That's why this adapter is
dev-only and never bundled into or imported by the shipped application.

Why custom bindings were needed
--------------------------------
Upstream only ships `plugins/python-module/BTrackPythonModule.cpp`, which
binds three batch/offline functions (`detect_beats`,
`calculate_onset_detection_function`, `detect_beats_from_odf`) that each
consume a complete NumPy array up front -- none retain per-call streaming
state, so none can satisfy this project's `feed()`-once-per-live-block
interface. The underlying C++ `BTrack` class does have a real causal API
(`processAudioFrame`/`getCurrentTempoEstimate`), just never exposed to
Python upstream. `btrack_streaming.cpp` in this directory binds exactly that
slice directly. See README.md for the full investigation and build steps.

Implementation notes
---------------------
- **BTrack hardcodes a 44100 Hz assumption internally.** `BTrack.cpp`'s
  tempo/beat-period math (`calculateTempo`, `getBeatTimeInSeconds`, the
  `hopSize`-to-BPM conversions) all divide by the literal constant `44100`,
  not by any sample-rate parameter -- there isn't one; nothing in
  `BTrack::BTrack(hopSize, frameSize)` or `processAudioFrame` takes a
  sample rate at all. So unlike a library that accepts an arbitrary rate,
  BTrack is only correct when fed audio that really is at 44100 Hz with the
  canonical `hopSize=512`/`frameSize=1024` upstream uses everywhere (its own
  official bindings, `tests/main.cpp`, `example.py`). This adapter always
  resamples to `_BTRACK_SAMPLE_RATE` internally (linear interpolation, same
  lightweight no-anti-aliasing approach as the sibling essentia adapter) and
  keeps hop/frame size fixed; audio already at 44100 Hz never passes through
  the resampler.
- **`processAudioFrame`'s buffer length is `hopSize`, not `frameSize`,
  despite `BTrack.h`'s own doc comment.** The header says "[frame] should
  match the frame size that the algorithm was initialised with", but
  upstream's own `BTrackPythonModule.cpp` allocates a `hopSize`-length
  buffer and passes that -- confirmed empirically here too (a
  `frameSize`-length call raises from the bindings' own length check; a
  `hopSize`-length call produces a stable, sane tempo estimate on a
  synthetic click track). `frameSize` is BTrack's larger internal analysis
  window, held and advanced by its own `OnsetDetectionFunction` member
  across successive `hopSize`-length calls; callers never see it directly.
- **BTrack's internal tempo estimate starts at a built-in prior of 120.0
  BPM before any audio is processed at all** (confirmed by calling
  `current_tempo_estimate()` on a freshly constructed instance) --
  it is not a "no estimate yet" sentinel the way `0.0` is for the sibling
  adapters. To keep this adapter's `bpm` property honest and consistent
  with its siblings (`0.0` means "nothing real analyzed yet"), this adapter
  tracks whether at least one real hop has been processed and only starts
  reporting BTrack's own running estimate after that point.
- BTrack does not expose a bounded, documented confidence/probability
  value. `getLatestCumulativeScoreValue()` exists but is an internal,
  unnormalised beat-alignment strength signal with no fixed scale (observed
  magnitude in the thousands on a clean synthetic click track, scaling with
  signal energy and the `tightness` parameter) -- not something that can be
  honestly reported as a `[0, 1]`-ish "confidence" without an arbitrary,
  unvalidated normalisation. Per the shared interface's own "0.0 if the
  library doesn't expose one" convention, `confidence` is always `0.0` here.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np

# The compiled btrack_streaming extension lives next to this file, not on the
# default sys.path -- needed when this module is loaded via
# importlib.util.spec_from_file_location from a different working directory
# (e.g. bridge_v2.py / batch_311.py in the parent tools/beat-tracker-bench/
# directory), not just when run.py imports it directly from this directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from btrack_streaming import BTrackStream

logger = logging.getLogger(__name__)

# BTrack's tempo/beat-period math hardcodes this rate internally (see module
# docstring); audio is always resampled to it before being fed in.
_BTRACK_SAMPLE_RATE = 44100

# Canonical hop/frame size BTrack's own examples and official bindings use
# for 44100 Hz audio. frame_size is BTrack's internal analysis window
# (always 2x hop_size in every upstream example); hop_size is the number of
# samples processAudioFrame actually consumes per call.
_HOP_SIZE = 512
_FRAME_SIZE = 1024


def _resample_linear(block: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample `block` from `orig_sr` to `target_sr` by linear interpolation.

    Plain `numpy.interp` resampling with no anti-aliasing filter -- adequate
    for a click track or well-behaved music signal, not broadcast-quality.
    Feed audio already at 44100 Hz (both the `--audio` loader and
    `--synthetic-click` generator in `run.py` default to this) to avoid this
    path entirely.
    """
    if orig_sr == target_sr or block.size == 0:
        return block.astype(np.float64, copy=False)
    duration = block.size / orig_sr
    n_target = max(1, round(duration * target_sr))
    src_x = np.linspace(0.0, duration, num=block.size, endpoint=False)
    dst_x = np.linspace(0.0, duration, num=n_target, endpoint=False)
    return np.interp(dst_x, src_x, block).astype(np.float64)


class ExternalBeatTracker:
    """Streams PCM audio through BTrack's real causal C++ tracker.

    Lifecycle: call `warm_up()` once with the live sample rate, then call
    `feed()` once per incoming audio block (any block size; blocks smaller
    than one hop are buffered until enough audio has accumulated). Read
    `bpm` and `confidence` at any point to get the tracker's current running
    estimate. Not thread-safe; use one instance per audio stream.
    """

    def __init__(
        self, hop_size: int = _HOP_SIZE, frame_size: int = _FRAME_SIZE
    ) -> None:
        """Store the hop/frame size to construct BTrack with; see `warm_up()`.

        Parameters
        ----------
        hop_size, frame_size
            Passed straight through to the `BTrackStream` constructor
            (`BTrack(hopSize, frameSize)` in the underlying C++). Defaults
            match every upstream example and are only overridable for
            experimentation -- BTrack's internal tempo math is calibrated
            for 44100 Hz audio with these exact values (see module
            docstring), so changing them changes what BPM range/resolution
            the tracker can represent, not just its latency.
        """
        self._hop_size = hop_size
        self._frame_size = frame_size
        self._tracker: BTrackStream | None = None
        self._source_sample_rate: int | None = None
        self._pcm = np.zeros(0, dtype=np.float64)
        self._has_processed_frame = False
        self._bpm = 0.0
        self._confidence = 0.0

    def warm_up(self, sample_rate: int) -> None:
        """Construct the underlying BTrack instance and reset stream state.

        Must be called before `feed()`. BTrack has no model weights to
        load, so there is nothing expensive to pre-warm beyond constructing
        the C++ object; this still exists as a distinct step to match the
        sibling adapters' lifecycle and to record the live sample rate
        `feed()` needs for resampling.
        """
        self._source_sample_rate = int(sample_rate)
        self._tracker = BTrackStream(self._hop_size, self._frame_size)
        self._pcm = np.zeros(0, dtype=np.float64)
        self._has_processed_frame = False
        self._bpm = 0.0
        self._confidence = 0.0

    def feed(self, block: np.ndarray, block_start_s: float) -> None:
        """Consume one live-cadence PCM block (mono float32).

        `block_start_s` is accepted for interface parity with sibling
        adapters but is not needed here: BTrack tracks elapsed time
        internally purely via how many `hop_size`-sample frames have been
        fed so far.
        """
        if self._tracker is None:
            raise RuntimeError('warm_up() must be called before feed()')
        samples = np.asarray(block, dtype=np.float64).reshape(-1)
        if self._source_sample_rate != _BTRACK_SAMPLE_RATE:
            samples = _resample_linear(
                samples, self._source_sample_rate, _BTRACK_SAMPLE_RATE
            )
        self._pcm = np.concatenate([self._pcm, samples])

        while len(self._pcm) >= self._hop_size:
            frame = self._pcm[: self._hop_size]
            self._tracker.process_audio_frame(frame)
            self._pcm = self._pcm[self._hop_size:]
            self._has_processed_frame = True
            self._bpm = self._tracker.current_tempo_estimate()

    @property
    def bpm(self) -> float:
        """Current running BPM estimate (0.0 before the first hop is processed)."""
        return self._bpm if self._has_processed_frame else 0.0

    @property
    def confidence(self) -> float:
        """Always 0.0: BTrack exposes no bounded confidence value; see module docstring."""
        return self._confidence
