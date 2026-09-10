"""Regression tests for the F8 kick-band fix (2026-08-31).

Audit F8: kick_regularity sampled ``bands[0:6]`` — 30–54 Hz sub-bass on
the 64 log-spaced 30 Hz→16 kHz axis — while its own comment claimed
"~31–99 Hz"; the intended window is bands 0–11 (edge 12 ≈ 97 Hz). Fixed
at both the live sampling site and ``kick_regularity_fit``'s
``exp_kick`` (the audit: "change both together"), plus the replay
harness mirror. These tests pin the band math and every sampling width
so a drift back to sub-bass is a deliberate act.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[1]


def test_band_edge_math_backs_the_fix() -> None:
    """The audit's arithmetic, executable: edge 6 ≈ 54 Hz (the old
    window's ceiling — sub-bass), edge 12 ≈ 97 Hz (the kick window)."""
    edge = lambda i: 30.0 * (16000.0 / 30.0) ** (i / 64.0)  # noqa: E731
    assert 52.0 < edge(6) < 56.0
    assert 94.0 < edge(12) < 100.0


def test_live_sampling_uses_the_kick_window() -> None:
    """2026-09-10 (zone-map batch): the F8 window (bands 0-11, ~30-97 Hz)
    is unchanged as the total sampled span -- what changed is that it's
    now split into sub (0:_SUB_KICK_SPLIT_BAND) and kick-punch
    (_SUB_KICK_SPLIT_BAND:12) sub-windows instead of one undifferentiated
    mean over 0:12. See docs/adr/vj-system.md "Sub/Kick Split +
    Kick-Regularity Reshape"."""
    src = (_REPO / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py').read_text(encoding='utf-8')
    assert 'kick_bands[0:self._SUB_KICK_SPLIT_BAND].mean()' in src
    assert 'kick_bands[self._SUB_KICK_SPLIT_BAND:12].mean()' in src
    assert 'kick_bands[0:12].mean()' not in src
    assert 'kick_bands[0:6].mean()' not in src
    # exp_kick's own window is untouched by the sub/kick split (still the
    # full 12-band kick_regularity_fit comparison basis).
    assert 'expected_bands[i] for i in range(12)' in src
    assert 'expected_bands[i] for i in range(6)' not in src


def test_replay_harness_mirror_matches_live() -> None:
    """2026-09-10 (zone-map batch): the mirror stays faithful to the
    reshaped live sampling (sub/kick split), same reasoning as above."""
    src = (_REPO / 'drop-ins' / 'training-kit-01' / 'tools'
           / 'track_replay.py').read_text(encoding='utf-8')
    assert 'bands[_SUB_KICK_SPLIT_BAND:12].mean()' in src
    assert 'bands[0:12].mean()' not in src
    assert 'bands[0:6].mean()' not in src


def test_perc_band_axis_is_what_the_fix_assumes() -> None:
    """The fix's Hz claims depend on the analyzer's 64-band log axis
    actually running 30 Hz → 16 kHz; pin that so a future axis change
    re-opens F8 loudly instead of silently."""
    import sys
    sys.path.insert(0, str(_REPO))
    from unicornviz.audio.analyzer import PERC_BAND_CENTERS_HZ

    assert len(PERC_BAND_CENTERS_HZ) == 64
    assert 28.0 < PERC_BAND_CENTERS_HZ[0] < 35.0
    # Center of band 11 (the new window's last band) sits inside the
    # 54-97 Hz half the old window was missing.
    assert 54.0 < PERC_BAND_CENTERS_HZ[11] < 100.0
    # And band 5 (old ceiling) is genuinely sub-bass.
    assert PERC_BAND_CENTERS_HZ[5] < 55.0
