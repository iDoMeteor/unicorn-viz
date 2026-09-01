"""Functional tests for the mid/side vocal-presence feature (2026-09-01).

Replaces the measurement role of the failed hnr/fmr heuristics (see the
2026-08-31 experiment ledger's instrument audit: instrumentals read
HIGHER hnr than acapellas). Synthetic stereo with known physics: a
center-panned tone is pure mid (mid-fraction ~1); decorrelated noise
splits energy between mid and side (~0.5); mono input reports invalid.
"""
from __future__ import annotations

import numpy as np

from unicornviz.audio.analyzer import Analyzer
from unicornviz.effects.base import AudioData

SR = 48000
BLOCK = 512


def _run(analyzer: Analyzer, mono: np.ndarray, side: np.ndarray | None,
         seconds: float) -> AudioData:
    data = AudioData()
    n_blocks = int(seconds * SR) // BLOCK
    for i in range(n_blocks):
        lo, hi = i * BLOCK, (i + 1) * BLOCK
        analyzer.process(
            mono[lo:hi], t=i * BLOCK / SR, out=data,
            side=None if side is None else side[lo:hi])
    return data


def _tone(freq: float, seconds: float, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_center_panned_content_reads_high_mid_ratio() -> None:
    seconds = 8.0
    mono = _tone(440.0, seconds)          # "vocal" fully in the mid channel
    side = np.zeros_like(mono)            # nothing in the sides
    an = Analyzer()
    an.set_sample_rate(SR)
    data = _run(an, mono, side, seconds)
    assert data.vocal_ms_valid
    assert data.vocal_mid_ratio > 0.9, data.vocal_mid_ratio


def test_decorrelated_content_reads_low_mid_ratio() -> None:
    seconds = 8.0
    rng = np.random.default_rng(3)
    left = rng.normal(0, 0.2, int(seconds * SR)).astype(np.float32)
    right = rng.normal(0, 0.2, int(seconds * SR)).astype(np.float32)
    mono = ((left + right) * 0.5)
    side = ((left - right) * 0.5)
    an = Analyzer()
    an.set_sample_rate(SR)
    data = _run(an, mono, side, seconds)
    assert data.vocal_ms_valid
    assert data.vocal_mid_ratio < 0.7, data.vocal_mid_ratio


def test_mono_input_reports_invalid_not_zero_measurement() -> None:
    seconds = 4.0
    mono = _tone(440.0, seconds)
    an = Analyzer()
    an.set_sample_rate(SR)
    data = _run(an, mono, None, seconds)
    assert data.vocal_ms_valid is False
