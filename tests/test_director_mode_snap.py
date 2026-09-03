"""Director placement E6/E3/E8: mode-transition quantization + persistence
+ per-mode snap unit / allowed-from source gating.

E6 applies E1's `_schedule_drop()` deferral mechanism to `_enter_build()` /
`_enter_breakdown()` / `_enter_climax()`, generalized under E8 to a per-mode
`snap_unit` ('off'/'downbeat'/'phrase') and `phrase_within_bars` pair:
'off' fires immediately; 'downbeat' always defers to the next downbeat;
'phrase' defers to the next downbeat AND chains further to the 8-bar phrase
boundary (`phrase_snap_unit`) when within `phrase_within_bars` of it --
never earlier than the original decision. Unlike a drop (revalidated only
against its own captured score/confidence at fire time), a deferred mode
entry is revalidated against the SAME live trend that justified scheduling
it; if the trend has reversed by the time the deferred boundary arrives,
the entry is cancelled and counted rather than fired stale. `do_enter`
receives the effective applied label ('off'/'downbeat'/'phrase' -- what
actually happened, not the configured intent).

E8 also gates each transition on its source mode (`mode_allowed_from_
<mode>`, a set of upper-case mode-name strings) -- checked in the
`_enter_*()` wrappers before scheduling, not in `_schedule_mode_transition`
itself; a blocked transition increments `_mode_blocked_by_source_count`
and never schedules.

E3 raises the `sustained_rise`/`sustained_fall` requirement from a pure
time-sustain to an additional bars-of-monotone-slope floor
(`mode_persist_bars_rise`/`_fall`), checked before `_enter_build`/
`_enter_breakdown` are even called (not part of the E6/E8 deferral
mechanism).

Uses bare controller instances and a stub grid, mirroring
test_director_phrase_snap.py's style.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

_AUTO_VJ = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_SPEC = importlib.util.spec_from_file_location('test_mode_snap_auto_vj', _AUTO_VJ)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules['test_mode_snap_auto_vj'] = _MOD
_SPEC.loader.exec_module(_MOD)
AutoVJController = _MOD.AutoVJController
_CRUISE = _MOD._CRUISE
_BUILD = _MOD._BUILD
_BREAKDOWN = _MOD._BREAKDOWN
_DROP = _MOD._DROP


class _Grid:
    bpm = 125.0
    energy_slope = 0.5
    energy = 0.5
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


def _downbeats_until(fired_attr_getter, grid, limit: int = 12) -> int:
    n = 0
    while not fired_attr_getter() and n < limit:
        grid.downbeat()
        n += 1
    return n


def _bare(*, bars_since_track_start: int = 5, snap_unit: str = 'phrase',
          phrase_within_bars: float = 0.0, unit: int = 8, evidence: bool = True):
    c = object.__new__(AutoVJController)
    c._grid = _Grid()
    c._mode_snap_pending = False
    c._phrase_snap_unit = unit
    c._mode_snap_count = 0
    c._mode_phrase_snap_count = 0
    c._mode_snap_cancelled_count = 0
    c._mode_last_snap_bars = 0
    c._bars_since_track_start = bars_since_track_start
    c.entered = 0
    c.applied_log: list = []
    def _do_enter(applied):
        c.entered += 1
        c.applied_log.append(applied)
    c._do_enter = _do_enter  # type: ignore[attr-defined]
    c._evidence_flag = evidence
    c._evidence = lambda: c._evidence_flag
    c._snap_unit = snap_unit
    c._phrase_within_bars = phrase_within_bars
    return c


def _schedule(c) -> None:
    c._schedule_mode_transition(c._do_enter, c._evidence, 'sustained_rise',
                                 c._snap_unit, c._phrase_within_bars)


# ---------------------------------------------------------------------------
# _schedule_mode_transition() -- the scheduling mechanism in isolation
# ---------------------------------------------------------------------------

def test_snap_unit_off_fires_immediately() -> None:
    c = _bare(snap_unit='off')
    _schedule(c)
    assert c.entered == 1
    assert c.applied_log == ['off']
    assert c._mode_snap_count == 0


def test_snap_unit_downbeat_defers_one_downbeat_and_never_phrase_chains() -> None:
    c = _bare(bars_since_track_start=6, snap_unit='downbeat', phrase_within_bars=2.0)  # 2 bars to boundary, but unit=downbeat ignores it
    _schedule(c)
    assert c.entered == 0
    assert c._mode_snap_count == 1
    assert c._mode_phrase_snap_count == 0
    assert _downbeats_until(lambda: c.entered, c._grid) == 1
    assert c.applied_log == ['downbeat']


def test_snap_unit_phrase_defers_to_next_downbeat_when_not_near_boundary() -> None:
    c = _bare(bars_since_track_start=1, snap_unit='phrase', phrase_within_bars=2.0)   # 7 bars to the boundary, > 2
    _schedule(c)
    assert c.entered == 0
    assert c._mode_snap_count == 1
    assert c._mode_phrase_snap_count == 0
    assert _downbeats_until(lambda: c.entered, c._grid) == 1
    assert c.applied_log == ['downbeat']  # not within range -> applied as plain downbeat


def test_snap_unit_phrase_chains_to_the_boundary_when_within_range() -> None:
    c = _bare(bars_since_track_start=5, snap_unit='phrase', phrase_within_bars=2.0)   # 3 bars to boundary, > 2 -> no chain
    _schedule(c)
    assert _downbeats_until(lambda: c.entered, c._grid) == 1
    assert c.applied_log == ['downbeat']

    c2 = _bare(bars_since_track_start=6, snap_unit='phrase', phrase_within_bars=2.0)  # 2 bars to boundary, within range
    _schedule(c2)
    assert c2._mode_phrase_snap_count == 1
    assert c2._mode_last_snap_bars == 2
    assert _downbeats_until(lambda: c2.entered, c2._grid) == 2
    assert c2.applied_log == ['phrase']


def test_evidence_reversed_cancels_instead_of_firing() -> None:
    c = _bare(bars_since_track_start=6, snap_unit='phrase', phrase_within_bars=2.0, evidence=False)
    _schedule(c)
    _downbeats_until(lambda: c._mode_snap_cancelled_count, c._grid)
    assert c.entered == 0
    assert c._mode_snap_cancelled_count == 1
    assert c._mode_snap_pending is False  # cleared even on cancellation


def test_second_schedule_while_pending_is_ignored() -> None:
    c = _bare(bars_since_track_start=6, snap_unit='phrase', phrase_within_bars=2.0)
    _schedule(c)
    _schedule(c)  # no-op: already pending
    assert c._mode_snap_count == 1
    assert _downbeats_until(lambda: c.entered, c._grid) == 2
    assert c.entered == 1


def test_grid_not_ready_fires_immediately_regardless_of_snap_unit() -> None:
    c = _bare(snap_unit='phrase', phrase_within_bars=2.0)
    c._grid.bpm = 0.0
    _schedule(c)
    assert c.entered == 1
    assert c.applied_log == ['off']
    assert c._mode_snap_pending is False


# ---------------------------------------------------------------------------
# Evidence-revalidation predicates
# ---------------------------------------------------------------------------

def test_build_evidence_invalid_only_if_slope_swings_to_breakdown_worthy() -> None:
    """Hysteresis fix (2026-09-03): cancelling on a mere dip below build's
    own soft give-up threshold cancelled ~70% of scheduled builds in the
    first offline cell -- most of them ordinary signal wobble on a slope
    signal whose own averaging window is comparable to the deferral window
    itself. Cancel only if the trend has swung all the way to what would
    justify BREAKDOWN instead."""
    c = object.__new__(AutoVJController)
    c._mode = _CRUISE
    c._grid = _Grid()
    c._breakdown_slope_threshold = -0.1
    c._breakdown_energy_threshold = 0.9
    c._grid.energy_slope = -0.05  # dipped, but not into breakdown territory
    c._grid.energy = 0.5
    assert c._build_evidence_still_valid(_CRUISE) is True
    c._grid.energy_slope = -0.5  # now genuinely breakdown-worthy
    c._grid.energy = 0.3
    assert c._build_evidence_still_valid(_CRUISE) is False


def test_build_evidence_invalid_if_mode_changed_to_something_else() -> None:
    c = object.__new__(AutoVJController)
    c._mode = _DROP  # something unrelated fired while this was pending
    c._grid = _Grid()
    c._breakdown_slope_threshold = -0.1
    c._breakdown_energy_threshold = 0.9
    assert c._build_evidence_still_valid(_CRUISE) is False


def test_build_evidence_valid_when_still_in_cruise_trending_up() -> None:
    c = object.__new__(AutoVJController)
    c._mode = _CRUISE
    c._grid = _Grid()
    c._grid.energy_slope = 0.3
    c._grid.energy = 0.6
    c._breakdown_slope_threshold = -0.1
    c._breakdown_energy_threshold = 0.9
    assert c._build_evidence_still_valid(_CRUISE) is True


def test_build_evidence_valid_from_breakdown_recovery_path() -> None:
    """The actual bug found live: _enter_build() is also called from
    BREAKDOWN's own recovery-to-build branch, not just CRUISE. A build
    scheduled with from_mode=BREAKDOWN must stay valid while self._mode is
    still BREAKDOWN (that's exactly where it's scheduled FROM) -- an
    earlier version hardcoded `self._mode != _CRUISE`, which rejected every
    single recovery-path build outright and was the dominant cause of the
    ~70% cancellation rate, not signal noise."""
    c = object.__new__(AutoVJController)
    c._mode = _BREAKDOWN
    c._grid = _Grid()
    c._grid.energy_slope = 0.2
    c._grid.energy = 0.6
    c._breakdown_slope_threshold = -0.1
    c._breakdown_energy_threshold = 0.9
    assert c._build_evidence_still_valid(_BREAKDOWN) is True


def test_breakdown_evidence_cancels_only_if_slope_swings_to_build_worthy() -> None:
    c = object.__new__(AutoVJController)
    c._mode = _CRUISE
    c._grid = _Grid()
    c._build_energy_threshold = 0.45
    c._grid.energy_slope = 0.1  # recovered a little, not build-worthy
    assert c._breakdown_evidence_still_valid(_CRUISE) is True
    c._grid.energy_slope = 0.6  # now genuinely build-worthy
    assert c._breakdown_evidence_still_valid(_CRUISE) is False


def test_breakdown_evidence_from_build_uses_the_same_opposite_mode_bar() -> None:
    c = object.__new__(AutoVJController)
    c._mode = _BUILD
    c._grid = _Grid()
    c._build_energy_threshold = 0.45
    c._grid.energy_slope = -0.2
    assert c._breakdown_evidence_still_valid(_BUILD) is True
    c._grid.energy_slope = 0.6
    assert c._breakdown_evidence_still_valid(_BUILD) is False


def test_climax_evidence_requires_drop_mode_and_major_tier() -> None:
    c = object.__new__(AutoVJController)
    c._mode = _DROP
    c._peak_tier = 'major'
    c._grid = _Grid()
    c._grid.downbeat_confidence = 0.9
    c._grid.drop_score = 0.95
    c._climax_min_downbeat_confidence = 0.6
    c._climax_entry_score = 0.7
    c._climax_early_override_score = 0.9
    c._climax_min_song_progress = 0.5
    c._current_song_progress = lambda: None  # unknown progress -> only early override counts
    assert c._climax_evidence_still_valid() is True  # score clears the early-override bar
    c._grid.drop_score = 0.75  # clears entry_score but progress is unknown
    assert c._climax_evidence_still_valid() is False
    c._mode = _DROP
    c._peak_tier = 'minor'
    c._grid.drop_score = 0.95
    assert c._climax_evidence_still_valid() is False  # minor tier never qualifies


# ---------------------------------------------------------------------------
# _mode_persist_bars_elapsed() -- E3
# ---------------------------------------------------------------------------

def test_persist_bars_zero_is_always_satisfied() -> None:
    c = object.__new__(AutoVJController)
    c._grid = _Grid()
    c._now = lambda: time.monotonic()
    assert c._mode_persist_bars_elapsed(time.monotonic(), 0.0) is True


def test_persist_bars_unsatisfied_before_enough_time_elapsed() -> None:
    c = object.__new__(AutoVJController)
    c._grid = _Grid()
    c._grid.bpm = 120.0  # bar_s = 2.0s
    onset_t = time.monotonic()
    c._now = lambda: onset_t + 1.0  # only half a bar elapsed
    assert c._mode_persist_bars_elapsed(onset_t, 1.0) is False


def test_persist_bars_satisfied_once_enough_time_elapsed() -> None:
    c = object.__new__(AutoVJController)
    c._grid = _Grid()
    c._grid.bpm = 120.0  # bar_s = 2.0s
    onset_t = time.monotonic()
    c._now = lambda: onset_t + 2.5
    assert c._mode_persist_bars_elapsed(onset_t, 1.0) is True


def test_persist_bars_falls_back_true_when_grid_not_ready() -> None:
    c = object.__new__(AutoVJController)
    c._grid = None
    c._now = lambda: time.monotonic()
    assert c._mode_persist_bars_elapsed(time.monotonic() - 100.0, 8.0) is True


# ---------------------------------------------------------------------------
# Shipped E6 defaults, pinned against silent drift (mirrors
# test_director_phrase_snap.py's test_shipped_default_is_snap_4...)
# ---------------------------------------------------------------------------

def test_shipped_e6_defaults() -> None:
    src = _AUTO_VJ.read_text(encoding='utf-8')
    assert "_cfg.get('mode_snap_downbeat', 1)" in src
    assert "_cfg.get('mode_phrase_snap_bars', 2.0)" in src


# ---------------------------------------------------------------------------
# E8: mode_snap_unit_<mode> / mode_phrase_within_bars_<mode> resolution
# ---------------------------------------------------------------------------

def test_resolve_snap_unit_derives_phrase_from_old_globals_by_default() -> None:
    """No new key set, old globals at their own shipped defaults (downbeat
    on, phrase_snap_bars=2) -- derives 'phrase', reproducing the panel-
    tested 2-bar candidate without any new key needing to be set."""
    c = object.__new__(AutoVJController)
    unit = c._resolve_mode_snap_unit({}, 'build')
    assert unit == 'phrase'
    assert c._resolve_mode_phrase_within_bars({}, 'build', unit) == 2.0


def test_resolve_snap_unit_off_when_old_downbeat_flag_is_off() -> None:
    c = object.__new__(AutoVJController)
    unit = c._resolve_mode_snap_unit({'mode_snap_downbeat': 0}, 'breakdown')
    assert unit == 'off'


def test_resolve_snap_unit_downbeat_when_old_phrase_bars_is_zero() -> None:
    c = object.__new__(AutoVJController)
    unit = c._resolve_mode_snap_unit({'mode_phrase_snap_bars': 0}, 'climax')
    assert unit == 'downbeat'
    assert c._resolve_mode_phrase_within_bars({}, 'climax', unit) == 0.0


def test_resolve_snap_unit_explicit_new_key_wins_over_old_globals() -> None:
    c = object.__new__(AutoVJController)
    cfg = {'mode_snap_unit_build': 'downbeat', 'mode_phrase_snap_bars': 4.0}
    unit = c._resolve_mode_snap_unit(cfg, 'build')
    assert unit == 'downbeat'  # explicit key wins even though the old global would derive 'phrase'


def test_resolve_phrase_within_bars_explicit_key_wins() -> None:
    c = object.__new__(AutoVJController)
    cfg = {'mode_phrase_within_bars_build': 1.0, 'mode_phrase_snap_bars': 2.0}
    assert c._resolve_mode_phrase_within_bars(cfg, 'build', 'phrase') == 1.0


def test_parse_mode_list_accepts_list_or_csv_string() -> None:
    c = object.__new__(AutoVJController)
    assert c._parse_mode_list(['CRUISE', 'breakdown']) == {'CRUISE', 'BREAKDOWN'}
    assert c._parse_mode_list('cruise, breakdown') == {'CRUISE', 'BREAKDOWN'}
    assert c._parse_mode_list('DROP') == {'DROP'}


# ---------------------------------------------------------------------------
# E8: mode_allowed_from_<mode> gating in the _enter_*() wrappers
# ---------------------------------------------------------------------------

def _bare_gated(*, mode: str, allowed_from_build=None, allowed_from_breakdown=None,
                allowed_from_climax=None):
    c = object.__new__(AutoVJController)
    c._mode = mode
    c._mode_snap_pending = False
    c._mode_blocked_by_source_count = 0
    c._mode_allowed_from_build = allowed_from_build or {'CRUISE', 'BREAKDOWN'}
    c._mode_allowed_from_breakdown = allowed_from_breakdown or {'CRUISE', 'BUILD', 'DROP'}
    c._mode_allowed_from_climax = allowed_from_climax or {'DROP'}
    c._mode_snap_unit_build = 'off'
    c._mode_snap_unit_breakdown = 'off'
    c._mode_snap_unit_climax = 'off'
    c._mode_phrase_within_bars_build = 0.0
    c._mode_phrase_within_bars_breakdown = 0.0
    c._mode_phrase_within_bars_climax = 0.0
    c.scheduled = 0
    c._schedule_mode_transition = lambda *a, **kw: setattr(c, 'scheduled', c.scheduled + 1)  # type: ignore[method-assign]
    return c


def test_build_blocked_when_source_not_allowed() -> None:
    c = _bare_gated(mode=_CRUISE, allowed_from_build={'BREAKDOWN'})  # owner variant: build only from breakdown
    c._enter_build()
    assert c.scheduled == 0
    assert c._mode_blocked_by_source_count == 1


def test_build_allowed_when_source_matches() -> None:
    c = _bare_gated(mode=_BREAKDOWN, allowed_from_build={'BREAKDOWN'})
    c._enter_build()
    assert c.scheduled == 1
    assert c._mode_blocked_by_source_count == 0


def test_build_default_allows_both_real_source_paths() -> None:
    for mode in (_CRUISE, _BREAKDOWN):
        c = _bare_gated(mode=mode)
        c._enter_build()
        assert c.scheduled == 1
        assert c._mode_blocked_by_source_count == 0


def test_climax_default_only_allows_drop() -> None:
    c = _bare_gated(mode=_BUILD)  # climax cannot fire from BUILD directly
    c._enter_climax()
    assert c.scheduled == 0
    assert c._mode_blocked_by_source_count == 1

    c2 = _bare_gated(mode=_DROP)
    c2._enter_climax()
    assert c2.scheduled == 1
    assert c2._mode_blocked_by_source_count == 0
