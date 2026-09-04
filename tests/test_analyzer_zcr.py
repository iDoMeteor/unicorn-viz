"""Tests: zero-crossing rate (ZCR) in the Analyzer (AudioData.zcr).

2026-09-03 (recommender rc.27): zcr was previously computed ad hoc inline
in auto_vj.py's own recommender-scoring path (from audio.waveform, never
a proper Analyzer/AudioData field) -- promoted to a real field, computed
once, mirroring vocal_hnr/vocal_fmr's own pattern (see
tests/test_analyzer_vocal_features.py). A higher-frequency signal crosses
zero more often per unit time than a lower-frequency one at the same
sample rate, so ZCR should increase monotonically with tone frequency --
the property this module checks, plus the silence/copy-site guards every
other AudioData field of this kind already has.
"""
from __future__ import annotations

import numpy as np

from unicornviz.audio.analyzer import Analyzer

_RATE = 48000
_BLOCK = 1024


def _tone_blocks(freq: float, n_blocks: int, seed: int = 0) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    blocks = []
    t0 = 0.0
    for _ in range(n_blocks):
        t = t0 + np.arange(_BLOCK, dtype=np.float64) / _RATE
        sig = np.sin(2.0 * np.pi * freq * t) + rng.standard_normal(_BLOCK) * 0.01
        blocks.append(sig.astype(np.float32))
        t0 += _BLOCK / _RATE
    return blocks


def _run(blocks: list[np.ndarray]) -> float:
    """Feed blocks through a fresh Analyzer; return the final zcr reading."""
    az = Analyzer()
    zcr = 0.0
    t = 0.0
    for b in blocks:
        d = az.process(b, t=t)
        zcr = d.zcr
        t += _BLOCK / _RATE
    return zcr


def test_zcr_increases_with_tone_frequency() -> None:
    low = _run(_tone_blocks(110.0, 10, seed=1))
    mid = _run(_tone_blocks(880.0, 10, seed=1))
    high = _run(_tone_blocks(4000.0, 10, seed=1))

    assert low < mid < high


def test_zcr_zero_during_silence() -> None:
    az = Analyzer()
    silent = np.zeros(_BLOCK, dtype=np.float32)
    d = az.process(silent, t=0.0)

    assert d.zcr == 0.0


def test_zcr_zero_for_none_pcm() -> None:
    az = Analyzer()
    d = az.process(None, t=0.0)

    assert d.zcr == 0.0
