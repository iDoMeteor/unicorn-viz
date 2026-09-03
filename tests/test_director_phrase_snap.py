"""Director placement E1: phrase-aware drop deferral in AutoVJController._schedule_drop().

Pins the 2026-09-03 mechanism: when `drop_phrase_snap_bars` > 0 and the
pending drop is within that many bars of the next phrase boundary
(`phrase_snap_unit`, default 8), the fire is chained downbeat-by-downbeat to
the boundary instead of firing at the next bar; otherwise (or at 0, the
shipped default until the panel bake lands it) the existing next-downbeat
behaviour is untouched. Impacts fire from inside _fire_drop, so they inherit
the deferral. Uses a bare controller instance and a stub grid.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_AUTO_VJ = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_SPEC = importlib.util.spec_from_file_location('test_phrase_snap_auto_vj', _AUTO_VJ)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules['test_phrase_snap_auto_vj'] = _MOD
_SPEC.loader.exec_module(_MOD)
AutoVJController = _MOD.AutoVJController


class _Grid:
    bpm = 125.0
    drop_score = 0.9
    downbeat_confidence = 0.9

    def __init__(self) -> None:
        self.queue: list = []

    def schedule_for_next_downbeat(self, cb) -> None:
        self.queue.append(cb)

    def downbeat(self) -> None:
        cbs, self.queue = self.queue, []
        for cb in cbs:
            cb()


def _bare(bars_since_track_start: int, snap: float, unit: int = 8):
    c = object.__new__(AutoVJController)
    c._grid = _Grid()
    c._drop_pending = False
    c._drop_phrase_snap_count = 0
    c._bars_since_track_start = bars_since_track_start
    c._drop_phrase_snap_bars = snap
    c._phrase_snap_unit = unit
    c.fired = 0
    c._fire_drop = lambda: setattr(c, 'fired', c.fired + 1)  # type: ignore[method-assign]
    return c


def _downbeats_until_fire(c, limit: int = 12) -> int:
    n = 0
    while not c.fired and n < limit:
        c._grid.downbeat()
        n += 1
    return n


def test_snap_off_fires_at_next_downbeat() -> None:
    c = _bare(bars_since_track_start=5, snap=0.0)
    c._schedule_drop()
    assert c._drop_pending and c._drop_phrase_snap_count == 0
    assert _downbeats_until_fire(c) == 1


def test_snap_defers_to_the_phrase_boundary_when_within_range() -> None:
    c = _bare(bars_since_track_start=5, snap=4.0)       # 3 bars to the 8-bar boundary
    c._schedule_drop()
    assert c._drop_phrase_snap_count == 1
    assert _downbeats_until_fire(c) == 3


def test_snap_does_not_defer_when_boundary_is_too_far() -> None:
    c = _bare(bars_since_track_start=1, snap=4.0)       # 7 bars away > snap
    c._schedule_drop()
    assert c._drop_phrase_snap_count == 0
    assert _downbeats_until_fire(c) == 1


def test_on_the_boundary_fires_at_next_downbeat() -> None:
    c = _bare(bars_since_track_start=16, snap=4.0)      # to_boundary == 0
    c._schedule_drop()
    assert c._drop_phrase_snap_count == 0
    assert _downbeats_until_fire(c) == 1


def test_unit_16_uses_sixteen_bar_phrases() -> None:
    c = _bare(bars_since_track_start=13, snap=4.0, unit=16)   # 3 bars to 16
    c._schedule_drop()
    assert c._drop_phrase_snap_count == 1
    assert _downbeats_until_fire(c) == 3


def test_shipped_default_is_snap_4_and_telemetry_records_the_distance() -> None:
    """Landed 2026-09-03 (director rc.13): the cfg fallback is 4 bars, and the
    scheduling-time distance to the boundary is recorded per drop."""
    src = _AUTO_VJ.read_text(encoding='utf-8')
    assert "_cfg.get('drop_phrase_snap_bars', 4.0)" in src
    c = _bare(bars_since_track_start=5, snap=4.0)
    c._drop_last_snap_bars = 0
    c._schedule_drop()
    assert c._drop_last_snap_bars == 3
    d = _bare(bars_since_track_start=1, snap=4.0)
    d._drop_last_snap_bars = 9
    d._schedule_drop()
    assert d._drop_last_snap_bars == 0                # not deferred: 7 bars out


def test_second_schedule_while_pending_is_ignored() -> None:
    c = _bare(bars_since_track_start=6, snap=4.0)
    c._schedule_drop()
    c._schedule_drop()
    assert c._drop_phrase_snap_count == 1
    assert _downbeats_until_fire(c) == 2 and c.fired == 1
