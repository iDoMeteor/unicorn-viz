"""AudioData.bpm must carry the tracker's tempo, not the constructor default.

2026-09-05 audit: Analyzer.process() never assigned data.bpm, so every
effect read 120.0 forever even while the BeatTracker fed a confident
estimate back through set_expected_bpm().  These tests pin the feed-through,
the default before any estimate, and the sticky behaviour across a
confidence dip that the analyzer already documented.
"""
from __future__ import annotations

import numpy as np

from unicornviz.audio.analyzer import Analyzer
from unicornviz.effects.base import AudioData

_RATE = 48000


def _block(n: int = 1024) -> np.ndarray:
    t = np.arange(n, dtype=np.float32) / _RATE
    return (0.5 * np.sin(2.0 * np.pi * 110.0 * t)).astype(np.float32)


def test_bpm_defaults_to_120_before_any_estimate() -> None:
    out = Analyzer(fft_bands=512).process(_block(), out=AudioData())
    assert out.bpm == 120.0


def test_confident_estimate_reaches_the_snapshot() -> None:
    an = Analyzer(fft_bands=512)
    an.set_expected_bpm(128.0, confidence=0.9)
    out = an.process(_block(), out=AudioData())
    assert out.bpm == 128.0


def test_estimate_is_sticky_through_a_confidence_dip() -> None:
    an = Analyzer(fft_bands=512)
    an.set_expected_bpm(140.0, confidence=0.9)
    an.set_expected_bpm(140.0, confidence=0.1)      # dip: refractory off, tempo kept
    out = an.process(_block(), out=AudioData())
    assert out.bpm == 140.0


def test_every_frame_carries_it_not_just_the_first() -> None:
    an = Analyzer(fft_bands=512)
    an.set_expected_bpm(96.0, confidence=1.0)
    buf = AudioData()
    for _ in range(5):
        an.process(_block(), out=buf)
    assert buf.bpm == 96.0
