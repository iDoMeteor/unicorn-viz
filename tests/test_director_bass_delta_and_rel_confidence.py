"""Director placement E2/E7: drop bass-delta gate + relative build-confidence
floor (both pre-registered in
docs/planning/director-placement-scoring-2026-09-03.md, both cfg-gated,
default off).

E2: a scheduled drop only actually fires once the bass over the coming bar
clears `drop_bass_delta_min` times the bass over the preceding two bars,
evaluated at the next downbeat; a failing candidate re-arms (fresh baseline
each time) for up to `drop_bass_delta_wait_bars` attempts, then lapses
without ever firing. 0 = off (byte-identical immediate fire, same as
pre-E2 behaviour).

E7: `mode_source_min_confidence_build_rel` gates a CRUISE->build transition
on a quantile of the session's own rolling `downbeat_confidence` history
instead of (or alongside) the existing absolute floor
(`mode_source_min_confidence_build`) -- an absolute number is hostage to
material/detector-state drift across a session, the same lesson E4 already
learned for the drop trigger.

Uses bare controller instances and a stub grid, mirroring
test_director_mode_snap.py's style.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_AUTO_VJ = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_SPEC = importlib.util.spec_from_file_location('test_bass_delta_rel_conf_auto_vj', _AUTO_VJ)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules['test_bass_delta_rel_conf_auto_vj'] = _MOD
_SPEC.loader.exec_module(_MOD)
AutoVJController = _MOD.AutoVJController
_CRUISE = _MOD._CRUISE
_BREAKDOWN = _MOD._BREAKDOWN
_SRC = _AUTO_VJ.read_text(encoding='utf-8')


class _Grid:
    bpm = 120.0  # bar_s = 240/120 = 2.0s
    downbeat_confidence = 0.9

    def __init__(self) -> None:
        self.queue: list = []

    def schedule_for_next_downbeat(self, cb) -> None:
        self.queue.append(cb)

    def downbeat(self) -> None:
        cbs, self.queue = self.queue, []
        for cb in cbs:
            cb()


# ---------------------------------------------------------------------------
# E2 -- drop bass-delta gate
# ---------------------------------------------------------------------------

def _bare_drop(*, delta_min: float = 0.0, wait_bars: int = 2, bpm: float = 120.0):
    c = object.__new__(AutoVJController)
    c._grid = _Grid()
    c._grid.bpm = bpm
    c._drop_pending = True
    c._bass_delta_hist: list = []
    c._drop_bass_delta_min = delta_min
    c._drop_bass_delta_wait_bars = wait_bars
    c._drop_delta_gate_blocked_count = 0
    c._drop_delta_gate_deferred_count = 0
    c.fired = 0
    c._fire_drop = lambda: setattr(c, 'fired', c.fired + 1)  # type: ignore[attr-defined]
    c._clock = [0.0]
    c._now = lambda: c._clock[0]
    return c


def test_gate_off_fires_immediately() -> None:
    c = _bare_drop(delta_min=0.0)
    c._maybe_fire_drop_with_bass_gate()
    assert c.fired == 1
    assert c._drop_delta_gate_blocked_count == 0
    assert c._drop_delta_gate_deferred_count == 0


def test_gate_on_fires_when_bass_genuinely_rises() -> None:
    c = _bare_drop(delta_min=1.10, wait_bars=2)
    c._bass_delta_hist = [(-4.0, 0.2), (-3.0, 0.2), (-2.0, 0.2), (-1.0, 0.2)]
    c._maybe_fire_drop_with_bass_gate()
    assert c.fired == 0
    assert len(c._grid.queue) == 1
    c._clock[0] = 2.0
    c._bass_delta_hist.extend([(0.5, 1.0), (1.5, 1.0)])
    c._grid.downbeat()
    assert c.fired == 1
    assert c._drop_delta_gate_blocked_count == 0
    assert c._drop_delta_gate_deferred_count == 0


def test_gate_rearms_then_lapses_when_bass_never_rises() -> None:
    c = _bare_drop(delta_min=1.10, wait_bars=2)
    c._bass_delta_hist = [(-4.0, 0.5), (-2.0, 0.5)]
    c._maybe_fire_drop_with_bass_gate()
    assert len(c._grid.queue) == 1

    c._clock[0] = 2.0
    c._bass_delta_hist.append((1.0, 0.5))
    c._grid.downbeat()
    assert c.fired == 0
    assert c._drop_delta_gate_deferred_count == 1
    assert c._drop_delta_gate_blocked_count == 0
    assert len(c._grid.queue) == 1  # re-armed for another downbeat

    c._clock[0] = 4.0
    c._bass_delta_hist.append((3.0, 0.5))
    c._grid.downbeat()
    assert c.fired == 0
    assert c._drop_delta_gate_deferred_count == 2
    assert c._drop_delta_gate_blocked_count == 1
    assert c._drop_pending is False
    assert len(c._grid.queue) == 0  # gave up, no further re-arm


def test_gate_fires_immediately_without_grid_or_bpm() -> None:
    c = _bare_drop(delta_min=1.10)
    c._grid = None
    c._maybe_fire_drop_with_bass_gate()
    assert c.fired == 1

    c2 = _bare_drop(delta_min=1.10)
    c2._grid.bpm = 0.0
    c2._maybe_fire_drop_with_bass_gate()
    assert c2.fired == 1


def test_gate_config_is_global_cfg_read() -> None:
    assert "_cfg.get('drop_bass_delta_min'" in _SRC
    assert "_cfg.get('drop_bass_delta_wait_bars'" in _SRC
    assert "_cfg.get('drop_bass_delta_window_s'" in _SRC


def test_schedule_drop_routes_through_the_gate_entry_point() -> None:
    """_schedule_drop()'s three firing paths (E1 phrase-chain terminal step,
    plain next-downbeat, and the no-grid fallback) must all call the E2
    entry point, not _fire_drop directly, so the gate can't be silently
    bypassed by one path."""
    assert '_step()' not in _SRC or 'self._maybe_fire_drop_with_bass_gate()' in _SRC
    assert 'self._grid.schedule_for_next_downbeat(self._maybe_fire_drop_with_bass_gate)' in _SRC


# ---------------------------------------------------------------------------
# E7 -- relative build-confidence floor
# ---------------------------------------------------------------------------

def _bare_build(*, from_mode: str = _CRUISE, abs_floor: float = 0.0,
                 rel_floor: float = 0.0, dconf: float = 0.9,
                 history: list | None = None):
    c = object.__new__(AutoVJController)
    c._mode = from_mode
    c._mode_allowed_from_build = {'CRUISE', 'BREAKDOWN'}
    c._mode_blocked_by_source_count = 0
    c._mode_source_min_confidence_build = abs_floor
    c._mode_source_min_confidence_build_rel = rel_floor
    c._build_blocked_by_confidence_count = 0
    c._build_blocked_by_rel_confidence_count = 0
    c._build_rel_confidence_quantile_value = 0.0
    c._downbeat_confidence_hist = list(history or [])
    c._grid = _Grid()
    c._grid.downbeat_confidence = dconf
    c._mode_snap_unit_build = 'off'
    c._mode_phrase_within_bars_build = 0.0
    c._mode_phrase_unit_build = 8.0
    c.scheduled = False
    c._schedule_mode_transition = lambda *a, **k: setattr(c, 'scheduled', True)  # type: ignore[attr-defined]
    return c


def _flat_history(value: float, n: int = 40) -> list:
    return [(float(i), value) for i in range(n)]


def test_rel_floor_off_leaves_absolute_only_behaviour_unchanged() -> None:
    c = _bare_build(abs_floor=0.0, rel_floor=0.0, dconf=0.01)
    c._enter_build()
    assert c.scheduled is True
    assert c._build_blocked_by_confidence_count == 0
    assert c._build_blocked_by_rel_confidence_count == 0


def test_rel_floor_with_insufficient_history_does_not_block() -> None:
    """Fewer than 30 samples: the quantile isn't trustworthy yet, so the
    relative gate doesn't engage (matches E4's rolling-p90 gate's own
    len(hw) >= 30 threshold)."""
    c = _bare_build(rel_floor=0.5, dconf=0.01, history=_flat_history(0.9, n=10))
    c._enter_build()
    assert c.scheduled is True
    assert c._build_blocked_by_rel_confidence_count == 0


def test_rel_floor_blocks_below_the_quantile() -> None:
    # history: half at 0.3, half at 0.9 -> the q=0.5 index (int-truncated)
    # lands on the last 0.3 sample, so the computed quantile value is 0.3.
    history = _flat_history(0.3, n=20) + _flat_history(0.9, n=20)
    c = _bare_build(rel_floor=0.5, dconf=0.25, history=history)
    c._enter_build()
    assert c.scheduled is False
    assert c._build_blocked_by_rel_confidence_count == 1
    assert c._build_rel_confidence_quantile_value == 0.3


def test_rel_floor_admits_above_the_quantile() -> None:
    history = _flat_history(0.3, n=20) + _flat_history(0.9, n=20)
    c = _bare_build(rel_floor=0.5, dconf=0.95, history=history)
    c._enter_build()
    assert c.scheduled is True
    assert c._build_blocked_by_rel_confidence_count == 0


def test_absolute_floor_still_a_hard_minimum_with_relative_gate_on() -> None:
    """Doc's recommended mode: a low absolute floor (e.g. 0.25) stays live
    as a hard minimum even while the relative gate does the real work."""
    history = _flat_history(0.1, n=40)  # a very low-confidence session
    c = _bare_build(abs_floor=0.25, rel_floor=0.5, dconf=0.20, history=history)
    c._enter_build()
    assert c.scheduled is False
    assert c._build_blocked_by_confidence_count == 1
    # absolute floor short-circuits before the relative check even runs
    assert c._build_blocked_by_rel_confidence_count == 0


def test_breakdown_source_never_checked_by_either_gate() -> None:
    """BREAKDOWN's recovery path has no downbeat_confidence-shaped signal
    behind it in the same sense -- neither the absolute nor the relative
    floor applies to it, same as the pre-existing absolute-floor behaviour."""
    c = _bare_build(from_mode=_BREAKDOWN, abs_floor=0.9, rel_floor=0.9,
                     dconf=0.01, history=_flat_history(0.9, n=40))
    c._enter_build()
    assert c.scheduled is True
    assert c._build_blocked_by_confidence_count == 0
    assert c._build_blocked_by_rel_confidence_count == 0


def test_rel_floor_config_is_global_cfg_read() -> None:
    assert "_cfg.get('mode_source_min_confidence_build_rel'" in _SRC
    assert "_cfg.get('mode_confidence_rel_window_s'" in _SRC


def test_downbeat_confidence_history_sampled_every_tick_and_time_windowed() -> None:
    assert 'self._downbeat_confidence_hist.append((now, dconf))' in _SRC
    assert '_dconf_hist_cutoff = now - float(getattr(self, \'_mode_confidence_rel_window_s\', 60.0) or 60.0)' in _SRC
