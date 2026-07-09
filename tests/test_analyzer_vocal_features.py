"""Tests: vocal-presence heuristics (HNR + FMR) in the Analyzer.

Validates that:
- vocal_hnr separates harmonic/tonal content from broadband noise in the
  vocal-formant band (300 Hz-3.4 kHz).
- vocal_fmr favors modulation concentrated in the 3-8 Hz syllabic/vibrato
  rate over an unmodulated tone, noise, or modulation at the wrong rate.

Neither signal is a true vocal detector -- see AudioData's docstring
comments in unicornviz/effects/base.py for the documented caveats. These
tests check directional/relative behavior, not absolute thresholds.
"""
from __future__ import annotations

import numpy as np

from unicornviz.audio.analyzer import Analyzer


_RATE = 48000
_BLOCK = 1024


def _tone_blocks(
    freq: float,
    n_blocks: int,
    harmonics: tuple[int, ...] = (1, 2, 3, 4, 5, 6),
    mod_hz: float | None = None,
    noise: float = 0.0,
    seed: int = 0,
) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    blocks = []
    t0 = 0.0
    for _ in range(n_blocks):
        t = t0 + np.arange(_BLOCK, dtype=np.float64) / _RATE
        sig = np.zeros(_BLOCK, dtype=np.float64)
        for h in harmonics:
            sig += (1.0 / h) * np.sin(2.0 * np.pi * freq * h * t)
        if mod_hz is not None:
            sig *= 0.6 + 0.4 * np.sin(2.0 * np.pi * mod_hz * t)
        if noise:
            sig += rng.standard_normal(_BLOCK) * noise
        blocks.append(sig.astype(np.float32))
        t0 += _BLOCK / _RATE
    return blocks


def _noise_blocks(n_blocks: int, seed: int = 1) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    return [(rng.standard_normal(_BLOCK) * 0.5).astype(np.float32) for _ in range(n_blocks)]


def _run(blocks: list[np.ndarray]) -> tuple[float, float]:
    """Feed blocks through a fresh Analyzer; return (mean recent hnr, final fmr)."""
    az = Analyzer()
    hnrs = []
    fmr = 0.0
    t = 0.0
    for b in blocks:
        d = az.process(b, t=t)
        hnrs.append(d.vocal_hnr)
        fmr = d.vocal_fmr
        t += _BLOCK / _RATE
    return float(np.mean(hnrs[-20:])), fmr


def test_hnr_separates_harmonic_tone_from_noise() -> None:
    tone_hnr, _ = _run(_tone_blocks(180.0, 200, noise=0.02, seed=42))
    noise_hnr, _ = _run(_noise_blocks(200, seed=42))

    assert tone_hnr > 0.6
    assert noise_hnr < 0.4
    assert tone_hnr > noise_hnr


def test_fmr_favors_true_syllabic_rate_modulation() -> None:
    """A tone amplitude-modulated at 5 Hz (inside the 3-8 Hz target band)
    must score higher than the same tone modulated at 20 Hz (well outside
    it) or not modulated at all."""
    voice_like_fmr = _run(_tone_blocks(180.0, 200, mod_hz=5.0, noise=0.02, seed=42))[1]
    fast_mod_fmr = _run(_tone_blocks(180.0, 200, mod_hz=20.0, noise=0.02, seed=42))[1]
    unmodulated_fmr = _run(_tone_blocks(180.0, 200, mod_hz=None, noise=0.02, seed=42))[1]

    assert voice_like_fmr > fast_mod_fmr
    assert voice_like_fmr > unmodulated_fmr


def test_fmr_lowest_for_pure_noise() -> None:
    voice_like_fmr = _run(_tone_blocks(180.0, 200, mod_hz=5.0, noise=0.02, seed=42))[1]
    noise_fmr = _run(_noise_blocks(200, seed=42))[1]

    assert noise_fmr < voice_like_fmr


def test_vocal_fields_zero_during_silence() -> None:
    az = Analyzer()
    silent = np.zeros(_BLOCK, dtype=np.float32)
    d = az.process(silent, t=0.0)

    assert d.vocal_hnr == 0.0


def test_vocal_fields_default_to_zero_before_any_process_call() -> None:
    """A freshly-constructed AudioData (no process() called yet) must not
    crash consumers that read vocal_hnr/vocal_fmr before first use."""
    from unicornviz.effects.base import AudioData

    data = AudioData()

    assert data.vocal_hnr == 0.0
    assert data.vocal_fmr == 0.0
