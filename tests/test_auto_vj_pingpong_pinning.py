"""Regression tests for effect ping-pong using the pinned-pair hard-cut path.

2026-08-07: ping-pong ('effect' kind) alternates between the same two
effects for its whole run, so _enter_pingpong() now pins both once
(vj_api.pin_effect_pair()) and every swap after that is a hard cut
(vj_api.cut_to_pinned_effect()) instead of a full instantiate+destroy
transition (vj_api.goto_effect()) on every beat-threshold swap. Falls back
to the old goto_effect() path if pinning fails.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_SPEC = importlib.util.spec_from_file_location('test_pingpong_pinning_auto_vj', _AUTO_VJ_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
AutoVJController = _MOD.AutoVJController
_CRUISE = _MOD._CRUISE
_PINGPONG = _MOD._PINGPONG


class _FakeVjApi:
    def __init__(self, *, pin_succeeds: bool = True, cut_succeeds: bool = True) -> None:
        self.pin_succeeds = pin_succeeds
        self.cut_succeeds = cut_succeeds
        self.pin_calls: list[tuple[str, str]] = []
        self.cut_calls: list[str] = []
        self.goto_calls: list[str] = []
        self.unpin_calls = 0
        self._effect_name = ''

    def pin_effect_pair(self, a: str, b: str) -> bool:
        self.pin_calls.append((a, b))
        return self.pin_succeeds

    def cut_to_pinned_effect(self, which: str) -> bool:
        self.cut_calls.append(which)
        return self.cut_succeeds

    def goto_effect(self, target: str) -> bool:
        self.goto_calls.append(target)
        return True

    def unpin_effect_pair(self) -> None:
        self.unpin_calls += 1

    def state(self):
        return SimpleNamespace(effect_name=self._effect_name)

    def projectm_goto_preset(self, idx: int) -> str:
        return f'preset-{idx}'


def _controller(*, pin_succeeds: bool = True, cut_succeeds: bool = True) -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._mode = _CRUISE
    inst._pp_prev_mode = _CRUISE
    inst._pp_active = False
    inst._pp_kind = 'effect'
    inst._pp_beat_count = 0
    inst._pp_started_auto = False
    inst._pp_swaps_remaining = 0
    inst._pp_pinned = False
    inst._pp_current = 'A'
    inst._pp_slot_a = 'Tron Grid'
    inst._pp_slot_b = 'Hacker Terminal'
    inst._pp_beats = 4
    inst._preset_pp_beats = 4
    inst._pp_preset_a = 0
    inst._pp_preset_b = 1
    inst._engine = SimpleNamespace(mark=lambda *a, **kw: None)
    inst._app = SimpleNamespace(vj_api=_FakeVjApi(pin_succeeds=pin_succeeds, cut_succeeds=cut_succeeds))
    inst._mark_mode_transition = lambda *a, **kw: None
    inst._reset_swap_timer = lambda: None
    inst._choose_pingpong_swap_budget = lambda: 4
    return inst


def test_enter_pingpong_pins_both_slots() -> None:
    inst = _controller()

    inst._enter_pingpong()

    assert inst._app.vj_api.pin_calls == [('Tron Grid', 'Hacker Terminal')]
    assert inst._pp_pinned is True


def test_enter_pingpong_cuts_to_pinned_instead_of_goto_effect() -> None:
    inst = _controller()

    inst._enter_pingpong()

    assert inst._app.vj_api.cut_calls == ['a']
    assert inst._app.vj_api.goto_calls == []


def test_swap_alternates_via_hard_cut_when_pinned() -> None:
    inst = _controller()
    inst._enter_pingpong()

    inst._run_pingpong_swap()
    inst._run_pingpong_swap()
    inst._run_pingpong_swap()

    assert inst._app.vj_api.cut_calls == ['a', 'b', 'a', 'b']
    assert inst._app.vj_api.goto_calls == []


def test_exit_pingpong_releases_the_pinned_pair() -> None:
    inst = _controller()
    inst._enter_pingpong()

    inst._exit_pingpong()

    assert inst._app.vj_api.unpin_calls == 1
    assert inst._pp_pinned is False


def test_exit_pingpong_is_a_noop_unpin_when_never_pinned() -> None:
    inst = _controller(pin_succeeds=False)
    inst._enter_pingpong()  # pin fails -> falls back to goto_effect

    inst._exit_pingpong()

    assert inst._app.vj_api.unpin_calls == 0


def test_falls_back_to_goto_effect_when_pinning_fails() -> None:
    inst = _controller(pin_succeeds=False)

    inst._enter_pingpong()

    assert inst._pp_pinned is False
    assert inst._app.vj_api.goto_calls == ['Tron Grid']
    assert inst._app.vj_api.cut_calls == []


def test_swap_falls_back_to_goto_effect_for_the_whole_run_when_pin_failed() -> None:
    inst = _controller(pin_succeeds=False)
    inst._enter_pingpong()

    inst._run_pingpong_swap()
    inst._run_pingpong_swap()

    assert inst._app.vj_api.goto_calls == ['Tron Grid', 'Hacker Terminal', 'Tron Grid']
    assert inst._app.vj_api.cut_calls == []


def test_swap_self_heals_when_the_pin_was_released_externally() -> None:
    """A manual 'next effect' hotkey mid-run releases the pinned pair from
    under auto-vj-01 (App._switch_effect()'s defensive unpin). The next
    swap must notice cut_to_pinned_effect() failing and fall back to
    goto_effect() rather than silently freezing on whatever the
    interruption left on screen."""
    inst = _controller()
    inst._enter_pingpong()
    assert inst._pp_pinned is True  # pin itself succeeded, initial cut succeeded
    # Simulate an external interruption between entry and the next swap
    # (App._switch_effect() already released the pin; only cut now fails).
    inst._app.vj_api.cut_succeeds = False

    inst._run_pingpong_swap()

    assert inst._app.vj_api.cut_calls == ['a', 'b']  # entry cut, then the failed attempt
    assert inst._app.vj_api.goto_calls == ['Hacker Terminal']
    assert inst._pp_pinned is False                   # healed for the rest of the run


def test_preset_kind_pingpong_is_unaffected_by_pinning() -> None:
    """The 'preset' ping-pong variant (ProjectM preset index swap) never
    touches the effect-pinning machinery at all."""
    inst = _controller()

    inst._enter_pingpong(kind='preset')

    assert inst._app.vj_api.pin_calls == []
    assert inst._pp_pinned is False
