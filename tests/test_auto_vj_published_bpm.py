"""Tests for the display-only smoothed BPM layer (2026-08-14, philosophizing
round): _update_published_bpm(), the published_bpm property, and
hud_bpm_label reading it.

Owner: "let's turn the actual public ema score itself into a smoothed
moving average... let it breathe naturally but let the advertised bpm
linger a bit" -- with an explicit, unprompted caveat that smoothing the
only visible number risks hiding real instability. Scope is deliberately
narrow: only hud_bpm_label reads the smoothed value. Every other consumer
(gates, director timing, recommender scoring, the cross-drop-in
publish_bpm() hint bus, _detector_snapshot() training-corpus logging)
keeps reading the fast, raw self._grid.bpm unchanged -- not covered by
these tests since nothing about those call sites changed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_AUTO_VJ_SPEC = importlib.util.spec_from_file_location('test_auto_vj_published_bpm_module', _AUTO_VJ_PATH)
assert _AUTO_VJ_SPEC is not None and _AUTO_VJ_SPEC.loader is not None
_AUTO_VJ_MODULE = importlib.util.module_from_spec(_AUTO_VJ_SPEC)
_AUTO_VJ_SPEC.loader.exec_module(_AUTO_VJ_MODULE)
AutoVJController = _AUTO_VJ_MODULE.AutoVJController


def _bare_controller(*, smoothing_enabled: bool, smoothing_s: float = 4.0) -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._grid = None
    inst._published_bpm_smoothing_enabled = smoothing_enabled
    inst._published_bpm_smoothing_s = smoothing_s
    inst._published_bpm = 0.0
    return inst


def test_published_bpm_starts_at_zero() -> None:
    inst = _bare_controller(smoothing_enabled=True)
    assert inst.published_bpm == 0.0
    assert inst.hud_bpm_label == '--'


def test_disabled_smoothing_tracks_the_raw_value_exactly() -> None:
    """published_bpm_smoothing_enabled=False must behave identically to
    reading self._grid.bpm directly -- no lag at all, any dt."""
    inst = _bare_controller(smoothing_enabled=False)
    inst._update_published_bpm(124.0, dt=0.016)
    assert inst.published_bpm == pytest.approx(124.0)
    inst._update_published_bpm(90.0, dt=0.016)
    assert inst.published_bpm == pytest.approx(90.0)


def test_first_lock_snaps_instead_of_ramping_from_zero() -> None:
    """Going from no lock (published_bpm <= 0) to a real reading must snap
    immediately -- the first real number shouldn't visibly ramp up from 0,
    which would look like a detector warming up rather than a clean lock."""
    inst = _bare_controller(smoothing_enabled=True)
    inst._update_published_bpm(124.0, dt=0.016)
    assert inst.published_bpm == pytest.approx(124.0)


def test_losing_lock_snaps_to_zero_immediately() -> None:
    """Silence/reset must be reflected immediately, not linger on a stale
    number -- smoothing is for cosmetic jitter, not for hiding a real
    silence-reset event."""
    inst = _bare_controller(smoothing_enabled=True)
    inst._update_published_bpm(124.0, dt=0.016)
    inst._update_published_bpm(0.0, dt=0.016)
    assert inst.published_bpm == 0.0
    assert inst.hud_bpm_label == '--'


def test_enabled_smoothing_lags_behind_a_sudden_jump() -> None:
    """A real tempo jump should not appear instantly once already locked --
    that's the whole point of the feature."""
    inst = _bare_controller(smoothing_enabled=True, smoothing_s=4.0)
    inst._update_published_bpm(120.0, dt=0.016)
    assert inst.published_bpm == pytest.approx(120.0)  # first-lock snap

    inst._update_published_bpm(160.0, dt=0.016)
    # One small frame step should move only a small fraction of the way.
    assert 120.0 < inst.published_bpm < 125.0


def test_enabled_smoothing_converges_to_the_new_value_over_several_time_constants() -> None:
    inst = _bare_controller(smoothing_enabled=True, smoothing_s=4.0)
    inst._update_published_bpm(120.0, dt=0.016)
    for _ in range(int(20.0 / 0.016)):  # ~20s, 5x the 4s time constant
        inst._update_published_bpm(160.0, dt=0.016)
    assert inst.published_bpm == pytest.approx(160.0, abs=0.5)


def test_enabled_smoothing_is_frame_rate_independent() -> None:
    """The time-constant formula (alpha = 1 - exp(-dt/tau)) should reach
    the same point after the same elapsed real time, regardless of
    whether it got there via many small steps or few large ones."""
    fast = _bare_controller(smoothing_enabled=True, smoothing_s=4.0)
    fast._update_published_bpm(120.0, dt=0.016)
    for _ in range(int(2.0 / 0.016)):  # 2s in small 16ms steps
        fast._update_published_bpm(160.0, dt=0.016)

    slow = _bare_controller(smoothing_enabled=True, smoothing_s=4.0)
    slow._update_published_bpm(120.0, dt=0.016)
    slow._update_published_bpm(160.0, dt=2.0)  # 2s in one big step

    assert fast.published_bpm == pytest.approx(slow.published_bpm, abs=0.5)


def test_hud_bpm_label_reads_published_bpm_not_the_raw_grid_value() -> None:
    inst = _bare_controller(smoothing_enabled=True, smoothing_s=4.0)
    inst._update_published_bpm(120.0, dt=0.016)
    inst._update_published_bpm(160.0, dt=0.016)  # small step, still lagging
    label = inst.hud_bpm_label
    assert label != '160'  # would be misleading if the label caught up instantly
    assert label != '--'
