"""Regression tests for the grand-finale trigger (_check_timed_finale),
2026-08-06: consumes the mixer's set-clock hint (plan section 6.3,
vj_api.get_session()) when available, in preference order:

1. final_peak_in_s (fires _finale_peak_lead_s seconds before the analysed
   final track's biggest drop, so the finale sequence's own buildup
   climaxes with the music instead of lagging behind it)
2. seconds_left (the mixer's own best set-end estimate)
3. state.session_remaining_s (the original wall-clock fallback, config
   show_duration_min/show_duration_s -- unchanged when no mixer hint
   exists at all)
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_SPEC = importlib.util.spec_from_file_location('test_auto_vj_timed_finale_module', _AUTO_VJ_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
AutoVJController = _MOD.AutoVJController


class _FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def mark(self, action: str, **info) -> None:
        self.calls.append((action, info))


class _FakeVjApi:
    def __init__(self, session_hint: dict | None = None, trigger_result: bool = True) -> None:
        self.session_hint = session_hint
        self.trigger_result = trigger_result
        self.trigger_calls = 0

    def get_session(self, exclude: str = '') -> dict | None:
        return self.session_hint

    def trigger_grand_finale(self) -> bool:
        self.trigger_calls += 1
        return self.trigger_result


def _controller(*, session_hint: dict | None = None, trigger_result: bool = True, **overrides) -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._timed_finale_fired = False
    inst._finale_auto_trigger = True
    inst._finale_lead_s = 45.0
    inst._finale_peak_lead_s = 43.0
    inst._engine = _FakeEngine()
    inst._app = SimpleNamespace(vj_api=_FakeVjApi(session_hint, trigger_result))
    inst._mode = 'CRUISE'
    inst._grid = None
    for k, v in overrides.items():
        setattr(inst, k, v)
    return inst


def _state(session_remaining_s: float | None) -> SimpleNamespace:
    return SimpleNamespace(session_remaining_s=session_remaining_s)


def test_fires_from_peak_timing_within_lead_window() -> None:
    inst = _controller(session_hint={'phase': 'final', 'final_peak_in_s': 40.0})
    inst._check_timed_finale(_state(None))

    assert inst._app.vj_api.trigger_calls == 1
    assert inst._timed_finale_fired is True


def test_does_not_fire_from_peak_timing_when_still_far_away() -> None:
    inst = _controller(session_hint={'phase': 'final', 'final_peak_in_s': 120.0})
    inst._check_timed_finale(_state(None))

    assert inst._app.vj_api.trigger_calls == 0
    assert inst._timed_finale_fired is False


def test_fires_from_seconds_left_when_no_peak_timing() -> None:
    inst = _controller(session_hint={'phase': 'closing', 'seconds_left': 30.0})
    inst._check_timed_finale(_state(None))

    assert inst._app.vj_api.trigger_calls == 1


def test_does_not_fire_from_seconds_left_when_still_far_away() -> None:
    inst = _controller(session_hint={'phase': 'running', 'seconds_left': 600.0})
    inst._check_timed_finale(_state(None))

    assert inst._app.vj_api.trigger_calls == 0


def test_peak_timing_takes_priority_over_seconds_left() -> None:
    """A hint with both fields present must use final_peak_in_s, not
    seconds_left, even if seconds_left alone would also cross its own
    (different) threshold."""
    inst = _controller(session_hint={
        'phase': 'final', 'final_peak_in_s': 200.0, 'seconds_left': 200.0,
    })
    inst._check_timed_finale(_state(None))

    # 200 > _finale_peak_lead_s (43) -- must not fire, even though 200 is
    # also > _finale_lead_s (45) which would be irrelevant here anyway.
    assert inst._app.vj_api.trigger_calls == 0


def test_falls_back_to_wall_clock_when_no_session_hint() -> None:
    inst = _controller(session_hint=None)
    inst._check_timed_finale(_state(30.0))

    assert inst._app.vj_api.trigger_calls == 1


def test_wall_clock_fallback_respects_its_own_lead_window() -> None:
    inst = _controller(session_hint=None)
    inst._check_timed_finale(_state(600.0))

    assert inst._app.vj_api.trigger_calls == 0


def test_wall_clock_fallback_does_nothing_when_remaining_is_none() -> None:
    inst = _controller(session_hint=None)
    inst._check_timed_finale(_state(None))

    assert inst._app.vj_api.trigger_calls == 0


def test_already_fired_is_a_noop_regardless_of_fresh_data() -> None:
    inst = _controller(session_hint={'phase': 'final', 'final_peak_in_s': 1.0}, _timed_finale_fired=True)
    inst._check_timed_finale(_state(None))

    assert inst._app.vj_api.trigger_calls == 0


def test_auto_trigger_disabled_is_a_noop() -> None:
    inst = _controller(session_hint={'phase': 'final', 'final_peak_in_s': 1.0}, _finale_auto_trigger=False)
    inst._check_timed_finale(_state(None))

    assert inst._app.vj_api.trigger_calls == 0


def test_marks_the_decision_log_event_on_fire() -> None:
    inst = _controller(session_hint={'phase': 'final', 'final_peak_in_s': 10.0})
    inst._check_timed_finale(_state(None))

    assert inst._engine.calls[0][0] == 'grand_finale'
    assert inst._engine.calls[0][1]['remaining_s'] == 10.0


def test_grand_finale_unavailable_still_marks_fired_but_no_log_event() -> None:
    """trigger_grand_finale() returning falsy (e.g. drop-in absent) must
    not crash and must not leave the trigger re-armed for next tick --
    matches the pre-existing one-shot behavior."""
    inst = _controller(session_hint={'phase': 'final', 'final_peak_in_s': 10.0}, trigger_result=False)
    inst._check_timed_finale(_state(None))

    assert inst._timed_finale_fired is True
    assert inst._engine.calls == []


def test_schedules_via_next_downbeat_when_bpm_locked() -> None:
    calls: list = []
    inst = _controller(session_hint={'phase': 'final', 'final_peak_in_s': 10.0})
    inst._grid = SimpleNamespace(bpm=124.0, schedule_for_next_downbeat=lambda fn: calls.append(fn))

    inst._check_timed_finale(_state(None))

    assert len(calls) == 1
    assert inst._app.vj_api.trigger_calls == 0  # not fired yet -- scheduled
    calls[0]()  # simulate the downbeat arriving
    assert inst._app.vj_api.trigger_calls == 1


def test_fires_immediately_when_no_bpm_lock() -> None:
    inst = _controller(session_hint={'phase': 'final', 'final_peak_in_s': 10.0})
    inst._grid = SimpleNamespace(bpm=0.0)

    inst._check_timed_finale(_state(None))

    assert inst._app.vj_api.trigger_calls == 1
