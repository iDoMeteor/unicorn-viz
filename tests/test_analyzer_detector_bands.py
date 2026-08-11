"""Tests: AudioData.bass_det/mid_det/treble_det (detector-facing band levels).

2026-08-11: bass/mid/treble's _shape() gains (6.6/5.8/7.2) are tuned for
effects (want to read as "alive" even when quiet), and verified against real
session data to leave bass specifically pegged near ceiling almost always
(median 0.97-0.98 across every director mode, including BREAKDOWN -- a 1.6%
spread). bass_det/mid_det/treble_det are a separate channel, same pre-curve
input, gain chosen for dynamic range instead -- consumed only by
drop-ins/auto-vj-01/beat_grid.py's z-score inputs, not effects. See
docs/planning/auto-vj-drop-score-redesign-plan-2026-08-11.md.
"""
from __future__ import annotations

import numpy as np

from unicornviz.audio.analyzer import Analyzer

_RATE = 48000
_BLOCK = 1024


def _tone_blocks(freq: float, n_blocks: int, amplitude: float) -> list[np.ndarray]:
    blocks = []
    t0 = 0.0
    for _ in range(n_blocks):
        t = t0 + np.arange(_BLOCK, dtype=np.float64) / _RATE
        sig = amplitude * np.sin(2.0 * np.pi * freq * t)
        blocks.append(sig.astype(np.float32))
        t0 += _BLOCK / _RATE
    return blocks


def _run(blocks: list[np.ndarray]):
    az = Analyzer()
    data = None
    t = 0.0
    for b in blocks:
        data = az.process(b, t=t)
        t += _BLOCK / _RATE
    return data


def test_bass_det_uses_a_lower_gain_than_effects_facing_bass() -> None:
    """A moderate (not maxed, not silent) bass tone should read meaningfully
    lower on bass_det than on bass -- the whole point of the lower gain.
    Bass's effects gain (6.6) saturates real material near ceiling almost
    immediately; bass_det's gain (2.0) should leave real headroom."""
    data = _run(_tone_blocks(90.0, 8, amplitude=0.15))

    assert data.bass > 0.0
    assert data.bass_det > 0.0
    assert data.bass_det < data.bass, (
        f'bass_det={data.bass_det:.3f} should read lower than '
        f'bass={data.bass:.3f} for a moderate bass tone'
    )


def test_bass_det_is_not_pegged_near_ceiling_for_moderate_input() -> None:
    """The specific complaint being fixed: a moderate bass level should not
    already read near 1.0. bass (effects gain) is allowed to saturate here;
    bass_det should not."""
    data = _run(_tone_blocks(90.0, 8, amplitude=0.15))

    assert data.bass_det < 0.9, (
        f'bass_det={data.bass_det:.3f} is pegged near ceiling for a '
        'moderate input -- the gain fix did not take effect'
    )


def test_mid_det_and_treble_det_match_their_effects_counterparts() -> None:
    """mid/treble's effects-facing gains were checked against real session
    data and found already well-tuned (every lower gain gave less cross-mode
    separation, not more) -- so mid_det/treble_det currently just mirror
    mid/treble exactly, same gain, same input. Only bass_det's gain differs."""
    data = _run(_tone_blocks(1500.0, 8, amplitude=0.15))

    assert data.mid_det == data.mid
    assert data.treble_det == data.treble


def test_bass_det_matches_bass_at_zero_gain_would_diverge_but_zero_input_agrees() -> None:
    """Silence: both channels should read exactly 0.0 regardless of gain --
    the fix changes sensitivity, not the silence floor."""
    data = _run(_tone_blocks(90.0, 4, amplitude=0.0))

    assert data.bass == 0.0
    assert data.bass_det == 0.0
