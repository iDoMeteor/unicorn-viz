"""Tests: onset detection under duplicate-block feeding.

Validates that:
- Processing the same PCM block repeatedly does not fire additional onsets
  after the initial one (the cooldown refractory enforces this).
- The MAD-based threshold stays finite and positive even when the same
  flux value is fed identically many times (degenerate input).
- A genuine new transient after silence does register as an onset.
"""
from __future__ import annotations

import numpy as np
import pytest

from unicornviz.audio.analyzer import Analyzer


_BANDS = 512
_RATE = 48000


def _make_sine_block(freq: float = 440.0, n: int = 1024, amp: float = 0.5) -> np.ndarray:
    t = np.arange(n, dtype=np.float32) / _RATE
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def _make_kick_block(n: int = 1024, amp: float = 0.9) -> np.ndarray:
    """Strong broadband transient to reliably trigger an onset.

    Uses high-amplitude white noise filling the whole block so it passes
    the silence gate (RMS > silence_rms_floor) and produces significant flux
    after a silence warmup where RMS was zero.
    """
    rng = np.random.default_rng(42)
    return (amp * rng.standard_normal(n)).clip(-1.0, 1.0).astype(np.float32)


def test_duplicate_block_does_not_refireOnset() -> None:
    """Feeding the same strong block twice must not produce two onsets."""
    a = Analyzer(fft_bands=_BANDS)
    kick = _make_kick_block()

    # Warm up the envelope with silence so kick stands out.
    silence = np.zeros(1024, dtype=np.float32)
    t = 0.0
    step = 1024 / _RATE
    for _ in range(60):  # ~0.6 s of silence fills the envelope ring
        a.process(silence, t=t)
        a.drain_onsets()
        t += step

    # Process the kick once — should produce an onset.
    a.process(kick, t=t)
    onsets_first = a.drain_onsets()
    t += step

    # Process the identical block again immediately — refractory must suppress.
    a.process(kick, t=t)
    onsets_second = a.drain_onsets()

    assert len(onsets_first) >= 1, 'Expected at least one onset on the initial transient'
    assert len(onsets_second) == 0, 'Refractory must suppress a duplicate-block onset'


def test_repeated_identical_blocks_threshold_stays_finite() -> None:
    """MAD threshold must not degenerate to zero or NaN under constant input."""
    a = Analyzer(fft_bands=_BANDS)
    block = _make_sine_block(amp=0.3)
    t = 0.0
    step = 1024 / _RATE
    for _ in range(120):
        a.process(block, t=t)
        a.drain_onsets()
        t += step

    threshold, mad = a._onset_threshold()
    assert np.isfinite(threshold), f'Threshold became non-finite: {threshold}'
    assert threshold > 0.0, f'Threshold collapsed to zero: {threshold}'
    assert np.isfinite(mad), f'MAD became non-finite: {mad}'


def test_genuine_transient_after_warmup_produces_onset() -> None:
    """A strong transient after an established steady-state must register."""
    a = Analyzer(fft_bands=_BANDS)
    silence = np.zeros(1024, dtype=np.float32)
    t = 0.0
    step = 1024 / _RATE
    # Warm up with silence.
    for _ in range(60):
        a.process(silence, t=t)
        a.drain_onsets()
        t += step
    # Fire kick.
    a.process(_make_kick_block(), t=t)
    onsets = a.drain_onsets()
    assert len(onsets) >= 1, 'Genuine transient must produce at least one onset'
    assert onsets[0].strength > 0.0, 'Onset strength must be positive'
