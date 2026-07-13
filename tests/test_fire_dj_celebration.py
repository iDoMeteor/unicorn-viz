"""Regression tests for FireDJCelebration (drop-ins/auto-vj-01).

The composite/fire-sim shaders and __init__/render()/destroy() require a
real (or headless) moderngl GL context and are not covered here -- this
project has no headless-GL test harness (see DW-001 in
docs/planning/deferred-work-2026-06-18.md) and no other effect's render
path is unit tested either, so that's consistent with existing practice,
not a gap specific to this file.

What IS covered: the pure-Python choreography logic that drives the
12-second sequence -- stage/timing math, the 13-action dispatch table
(each action must fire exactly once, at the right time, with the right
args), trigger()/update() lifecycle, and ping-pong start/cleanup. None of
this touches GL at all, so it's tested directly against bare instances
built with object.__new__() (mirroring the pattern used throughout this
test suite for AutoVJController) rather than a mocked GL context.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


_FIRE_DJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'fire_dj_celebration.py'
_SPEC = importlib.util.spec_from_file_location('test_fire_dj_celebration_module', _FIRE_DJ_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
FireDJCelebration = _MOD.FireDJCelebration
_vj = _MOD._vj
_maybe_pingpong = _MOD._maybe_pingpong
_TOTAL = _MOD._TOTAL
_IMPACT_END = _MOD._IMPACT_END
_TITLE_END = _MOD._TITLE_END
_HOLD_END = _MOD._HOLD_END
_TITLE_START = _MOD._TITLE_START


class _FakeVJApi:
    """Records every choreographed call in order, mirroring the real vj_api surface."""

    def __init__(self, *, pp_slots_pinned: bool = False) -> None:
        self.calls: list[tuple] = []
        self._pp_ctrl = SimpleNamespace(
            _pp_slot_a=('EffectA', 0) if pp_slots_pinned else None,
            _pp_slot_b=('EffectB', 0) if pp_slots_pinned else None,
            _pp_active=False,
            toggle_pingpong=MagicMock(),
        )
        self._app = SimpleNamespace(_auto_vj=self._pp_ctrl)

    def trigger_screen_burst(self) -> None:
        self.calls.append(('trigger_screen_burst',))

    def trigger_rainbow_nova(self) -> None:
        self.calls.append(('trigger_rainbow_nova',))

    def set_postfx_slot(self, n: int) -> None:
        self.calls.append(('set_postfx_slot', n))

    def goto_random_effect(self, tags: list[str] | None = None) -> None:
        self.calls.append(('goto_random_effect', tuple(tags or [])))


def _bare_celebration() -> FireDJCelebration:
    """A FireDJCelebration with no GL resources -- only fields update()/
    trigger()/_dispatch_vj_actions() actually touch."""
    fc = object.__new__(FireDJCelebration)
    fc._active = False
    fc._timer = 0.0
    fc._vj_actions_fired = set()
    fc._cta_timer = 0.0
    fc._cta_active = False
    fc._pp_started = False
    fc._last_bass = 0.0
    fc._last_beat = 0.0
    return fc


def _run_full_sequence(fc: FireDJCelebration, vj_api: object, *, dt: float = 1 / 60) -> None:
    fc._active = True
    while fc._active:
        fc.update(dt, 0.5, 0.3, vj_api)


# ---------------------------------------------------------------------------
# Stage timing math (pure functions of self._timer)
# ---------------------------------------------------------------------------

class TestCurrentStage:
    def test_impact_stage(self) -> None:
        fc = _bare_celebration()
        fc._timer = 0.4
        stage, phase = fc._current_stage()
        assert stage == 0
        assert phase == pytest.approx(0.4 / _IMPACT_END)

    def test_title_stage(self) -> None:
        fc = _bare_celebration()
        fc._timer = (_IMPACT_END + _TITLE_END) / 2.0
        stage, _phase = fc._current_stage()
        assert stage == 1

    def test_hold_stage(self) -> None:
        fc = _bare_celebration()
        fc._timer = (_TITLE_END + _HOLD_END) / 2.0
        stage, _phase = fc._current_stage()
        assert stage == 2

    def test_fadeout_stage(self) -> None:
        fc = _bare_celebration()
        fc._timer = (_HOLD_END + _TOTAL) / 2.0
        stage, _phase = fc._current_stage()
        assert stage == 3

    def test_fadeout_phase_clamps_at_one(self) -> None:
        fc = _bare_celebration()
        fc._timer = _TOTAL + 5.0  # past the end -- must not exceed phase 1.0
        stage, phase = fc._current_stage()
        assert stage == 3
        assert phase == 1.0

    def test_stage_boundaries_are_contiguous_and_monotonic(self) -> None:
        """Sweeping the timer end to end must never skip or repeat a stage
        out of order, and phase must always be in [0, 1]."""
        fc = _bare_celebration()
        last_stage = -1
        t = 0.0
        while t <= _TOTAL:
            fc._timer = t
            stage, phase = fc._current_stage()
            assert stage >= last_stage
            assert stage - last_stage <= 1
            assert 0.0 <= phase <= 1.0
            last_stage = stage
            t += 0.05


class TestTitleEntryT:
    def test_zero_before_title_start(self) -> None:
        fc = _bare_celebration()
        fc._timer = _TITLE_START - 0.01
        assert fc._title_entry_t() == 0.0

    def test_reaches_one_after_entry_window(self) -> None:
        fc = _bare_celebration()
        fc._timer = _TITLE_START + 0.55  # entry window is 0.55s
        assert fc._title_entry_t() == 1.0

    def test_midway_is_between_zero_and_one(self) -> None:
        fc = _bare_celebration()
        fc._timer = _TITLE_START + 0.275
        assert 0.0 < fc._title_entry_t() < 1.0


# ---------------------------------------------------------------------------
# trigger() lifecycle
# ---------------------------------------------------------------------------

def test_trigger_resets_all_sequence_state() -> None:
    fc = _bare_celebration()
    fc._timer = 7.0
    fc._active = False
    fc._vj_actions_fired = {'burst1', 'nova1'}
    fc._cta_timer = 3.0
    fc._cta_active = True
    fc._pp_started = True
    fc._clear_fire = MagicMock()  # GL call, not under test here

    fc.trigger()

    assert fc._timer == 0.0
    assert fc._active is True
    assert fc._vj_actions_fired == set()
    assert fc._cta_timer == 0.0
    assert fc._cta_active is False
    assert fc._pp_started is False
    fc._clear_fire.assert_called_once()


# ---------------------------------------------------------------------------
# update() / _dispatch_vj_actions() -- full choreography
# ---------------------------------------------------------------------------

_EXPECTED_KEYS = {
    'burst1', 'nova1', 'fx3', 'swap', 'nova2', 'fx7', 'pingpong',
    'fx6', 'cta', 'burst2', 'fx9', 'nova3', 'fx_bubbles',
}


def test_all_thirteen_actions_fire_exactly_once_over_the_full_sequence() -> None:
    fc = _bare_celebration()
    vj_api = _FakeVJApi()
    _run_full_sequence(fc, vj_api)

    assert fc._vj_actions_fired == _EXPECTED_KEYS


def test_screen_burst_fires_exactly_twice() -> None:
    fc = _bare_celebration()
    vj_api = _FakeVJApi()
    _run_full_sequence(fc, vj_api)

    burst_calls = [c for c in vj_api.calls if c[0] == 'trigger_screen_burst']
    assert len(burst_calls) == 2


def test_rainbow_nova_fires_exactly_three_times() -> None:
    fc = _bare_celebration()
    vj_api = _FakeVJApi()
    _run_full_sequence(fc, vj_api)

    nova_calls = [c for c in vj_api.calls if c[0] == 'trigger_rainbow_nova']
    assert len(nova_calls) == 3


def test_postfx_slots_fire_in_the_documented_order() -> None:
    fc = _bare_celebration()
    vj_api = _FakeVJApi()
    _run_full_sequence(fc, vj_api)

    postfx_calls = [c[1] for c in vj_api.calls if c[0] == 'set_postfx_slot']
    assert postfx_calls == [3, 7, 6, 9, 10]


def test_goto_random_effect_fires_once_with_documented_tags() -> None:
    fc = _bare_celebration()
    vj_api = _FakeVJApi()
    _run_full_sequence(fc, vj_api)

    swap_calls = [c for c in vj_api.calls if c[0] == 'goto_random_effect']
    assert len(swap_calls) == 1
    assert swap_calls[0][1] == ('drop', 'intense', 'psychedelic', 'futuristic')


def test_actions_fire_in_chronological_order() -> None:
    """The call order recorded by the fake vj_api must match the documented
    timeline (earliest threshold first)."""
    fc = _bare_celebration()
    vj_api = _FakeVJApi()
    _run_full_sequence(fc, vj_api)

    expected_order = [
        ('trigger_screen_burst',),
        ('trigger_rainbow_nova',),
        ('set_postfx_slot', 3),
        ('goto_random_effect', ('drop', 'intense', 'psychedelic', 'futuristic')),
        ('trigger_rainbow_nova',),
        ('set_postfx_slot', 7),
        ('set_postfx_slot', 6),
        ('trigger_screen_burst',),
        ('set_postfx_slot', 9),
        ('trigger_rainbow_nova',),
        ('set_postfx_slot', 10),
    ]
    assert vj_api.calls == expected_order


def test_update_is_a_noop_when_not_active() -> None:
    fc = _bare_celebration()
    fc._active = False
    vj_api = _FakeVJApi()

    fc.update(1 / 60, 0.5, 0.3, vj_api)

    assert fc._timer == 0.0
    assert vj_api.calls == []


def test_update_deactivates_at_total_duration() -> None:
    fc = _bare_celebration()
    vj_api = _FakeVJApi()
    _run_full_sequence(fc, vj_api)

    assert fc._active is False
    assert fc._timer >= _TOTAL


def test_update_caches_bass_and_beat_for_render() -> None:
    fc = _bare_celebration()
    fc._active = True
    vj_api = _FakeVJApi()

    fc.update(1 / 60, 0.77, 0.42, vj_api)

    assert fc._last_bass == pytest.approx(0.77)
    assert fc._last_beat == pytest.approx(0.42)


def test_cta_timer_ticks_only_while_active_and_stops_at_total() -> None:
    fc = _bare_celebration()
    fc._active = True
    fc._cta_active = True
    fc._cta_timer = _MOD._CTA_TOTAL - 0.01
    vj_api = _FakeVJApi()

    fc.update(1 / 60, 0.0, 0.0, vj_api)

    assert fc._cta_active is False, 'CTA sub-sequence must end once its own total duration elapses'


def test_action_exception_does_not_propagate_or_block_other_actions() -> None:
    """A raising vj_api method must be caught (see the `once()` closure's
    try/except) so one broken action can't take down the whole sequence."""
    fc = _bare_celebration()

    class _BoomVJApi(_FakeVJApi):
        def trigger_screen_burst(self) -> None:
            raise RuntimeError('boom')

    vj_api = _BoomVJApi()
    _run_full_sequence(fc, vj_api)  # must not raise

    # Actions after the raising one must still have fired.
    assert 'nova3' in fc._vj_actions_fired
    assert fc._active is False


def test_each_action_key_fires_at_most_once_even_if_update_is_called_at_the_same_timer_value() -> None:
    fc = _bare_celebration()
    fc._active = True
    vj_api = _FakeVJApi()

    fc._timer = 0.05  # already past the t>=0.0 threshold for burst1/nova1... call dispatch twice manually
    fc._dispatch_vj_actions(vj_api)
    fc._dispatch_vj_actions(vj_api)

    burst_calls = [c for c in vj_api.calls if c[0] == 'trigger_screen_burst']
    assert len(burst_calls) == 1


# ---------------------------------------------------------------------------
# Ping-pong start / cleanup
# ---------------------------------------------------------------------------

def test_pingpong_starts_when_slots_are_pinned() -> None:
    fc = _bare_celebration()
    vj_api = _FakeVJApi(pp_slots_pinned=True)

    fc._start_pingpong(vj_api)

    vj_api._pp_ctrl.toggle_pingpong.assert_called_once()
    assert fc._pp_started is True


def test_pingpong_does_not_start_when_slots_are_not_pinned() -> None:
    fc = _bare_celebration()
    vj_api = _FakeVJApi(pp_slots_pinned=False)

    fc._start_pingpong(vj_api)

    vj_api._pp_ctrl.toggle_pingpong.assert_not_called()
    assert fc._pp_started is False


def test_pingpong_cleanup_exits_only_if_this_celebration_started_it() -> None:
    fc = _bare_celebration()
    fc._pp_started = False
    vj_api = _FakeVJApi(pp_slots_pinned=True)
    vj_api._pp_ctrl._pp_active = True

    fc._cleanup_pingpong(vj_api)

    vj_api._pp_ctrl.toggle_pingpong.assert_not_called(), 'must not exit ping-pong it did not start'


def test_pingpong_cleanup_exits_when_this_celebration_started_it_and_it_is_still_active() -> None:
    fc = _bare_celebration()
    fc._pp_started = True
    vj_api = _FakeVJApi(pp_slots_pinned=True)
    vj_api._pp_ctrl._pp_active = True

    fc._cleanup_pingpong(vj_api)

    vj_api._pp_ctrl.toggle_pingpong.assert_called_once()


def test_full_sequence_exits_pingpong_it_started_on_completion() -> None:
    fc = _bare_celebration()
    vj_api = _FakeVJApi(pp_slots_pinned=True)
    vj_api._pp_ctrl._pp_active = True  # toggle_pingpong is a mock -- simulate the flip manually

    _run_full_sequence(fc, vj_api)

    # Started once (at t=4.65) and cleaned up once (on completion) = 2 calls.
    assert vj_api._pp_ctrl.toggle_pingpong.call_count == 2


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def test_vj_helper_returns_bound_method_when_present() -> None:
    api = SimpleNamespace(trigger_screen_burst=lambda: 'called')
    fn = _vj(api, 'trigger_screen_burst')
    assert fn() == 'called'


def test_vj_helper_returns_noop_when_method_missing() -> None:
    api = SimpleNamespace()
    fn = _vj(api, 'nonexistent_method')
    assert fn() is None  # must not raise


def test_maybe_pingpong_starts_when_slots_pinned() -> None:
    vj_api = _FakeVJApi(pp_slots_pinned=True)
    _maybe_pingpong(vj_api)
    vj_api._pp_ctrl.toggle_pingpong.assert_called_once()


def test_maybe_pingpong_noop_without_auto_vj() -> None:
    vj_api = SimpleNamespace(_app=SimpleNamespace(_auto_vj=None))
    _maybe_pingpong(vj_api)  # must not raise


def test_is_active_property_reflects_internal_state() -> None:
    fc = _bare_celebration()
    fc._active = True
    assert fc.is_active is True
    fc._active = False
    assert fc.is_active is False
