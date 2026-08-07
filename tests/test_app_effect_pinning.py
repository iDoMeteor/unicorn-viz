"""Regression tests for the pinned-effect-pair hard-cut path.

2026-08-07: auto-vj-01's effect ping-pong repeatedly alternates between the
same two effects, but every swap went through the normal goto_effect() ->
_switch_effect() path -- a full instantiate + destroy (shader compile) on
every single swap, even though both effects are needed again a few beats
later. pin_effect_pair()/cut_to_pinned()/unpin_effect_pair() instantiate
both once and hard-cut between them: each swap after the initial pin
becomes a pointer assignment.

The real App methods are exercised unbound against a minimal stub -- no
SDL/GL context is created, matching the pattern in
test_effect_crash_isolation.py.
"""
from __future__ import annotations

from typing import Any

from unicornviz.app import App


class _Effect:
    NAME = 'Test Effect'

    def __init__(self, *_a: Any, **_kw: Any) -> None:
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class _EffectA(_Effect):
    NAME = 'Effect A'


class _EffectB(_Effect):
    NAME = 'Effect B'


class _BoomInit(_Effect):
    NAME = 'Boom Init'

    def __init__(self, *_a: Any, **_kw: Any) -> None:
        raise RuntimeError('shader compile failed')


class _AppStub:
    """Bare attribute surface for the effect-pinning methods."""

    def __init__(self) -> None:
        self._pinned_pair: dict[str, Any] | None = None
        self._current_effect: Any = None
        self._next_effect: Any = None
        self._transition_t = 0.5
        self._invert_colors = True
        self._projectm_manager_modal_active = False

    def _instantiate(self, cls: type, width: int | None = None,
                     height: int | None = None) -> Any:
        return cls(None, 64, 64, {})

    pin_effect_pair = App.pin_effect_pair
    cut_to_pinned = App.cut_to_pinned
    unpin_effect_pair = App.unpin_effect_pair


def test_pin_effect_pair_instantiates_both_and_returns_true() -> None:
    app = _AppStub()

    ok = app.pin_effect_pair(_EffectA, _EffectB)

    assert ok is True
    assert app._pinned_pair is not None
    assert isinstance(app._pinned_pair['a'], _EffectA)
    assert isinstance(app._pinned_pair['b'], _EffectB)


def test_pin_effect_pair_refuses_when_already_pinned() -> None:
    app = _AppStub()
    app.pin_effect_pair(_EffectA, _EffectB)
    first_pair = app._pinned_pair

    ok = app.pin_effect_pair(_EffectA, _EffectB)

    assert ok is False
    assert app._pinned_pair is first_pair  # untouched, not silently replaced


def test_pin_effect_pair_refuses_while_projectm_manager_open() -> None:
    app = _AppStub()
    app._projectm_manager_modal_active = True

    assert app.pin_effect_pair(_EffectA, _EffectB) is False
    assert app._pinned_pair is None


def test_pin_effect_pair_destroys_the_first_instance_if_the_second_fails() -> None:
    """A failed pin must not leak the first effect's GL resources."""
    app = _AppStub()

    ok = app.pin_effect_pair(_EffectA, _BoomInit)

    assert ok is False
    assert app._pinned_pair is None


def test_cut_to_pinned_swaps_the_current_effect_pointer() -> None:
    app = _AppStub()
    app.pin_effect_pair(_EffectA, _EffectB)
    pair = app._pinned_pair

    ok = app.cut_to_pinned('b')

    assert ok is True
    assert app._current_effect is pair['b']
    assert app._current_effect is not pair['a']


def test_cut_to_pinned_does_not_instantiate_or_destroy_anything() -> None:
    """The whole point: repeated cuts are pure pointer swaps."""
    app = _AppStub()
    app.pin_effect_pair(_EffectA, _EffectB)
    pair = app._pinned_pair

    app.cut_to_pinned('a')
    app.cut_to_pinned('b')
    app.cut_to_pinned('a')

    assert pair['a'].destroyed is False
    assert pair['b'].destroyed is False


def test_cut_to_pinned_clears_any_in_flight_transition() -> None:
    app = _AppStub()
    app.pin_effect_pair(_EffectA, _EffectB)
    app._next_effect = object()
    app._transition_t = 0.5

    app.cut_to_pinned('a')

    assert app._next_effect is None
    assert app._transition_t == 0.0


def test_cut_to_pinned_returns_false_with_no_pair_pinned() -> None:
    app = _AppStub()
    assert app.cut_to_pinned('a') is False


def test_cut_to_pinned_returns_false_for_an_unknown_slot() -> None:
    app = _AppStub()
    app.pin_effect_pair(_EffectA, _EffectB)
    assert app.cut_to_pinned('c') is False


def test_unpin_effect_pair_destroys_the_offscreen_instance_only() -> None:
    app = _AppStub()
    app.pin_effect_pair(_EffectA, _EffectB)
    pair = app._pinned_pair
    app.cut_to_pinned('b')  # 'b' is on screen, 'a' is not

    app.unpin_effect_pair()

    assert pair['a'].destroyed is True
    assert pair['b'].destroyed is False       # still rendering -- left alive
    assert app._current_effect is pair['b']   # untouched
    assert app._pinned_pair is None


def test_unpin_effect_pair_is_a_noop_with_no_pair_pinned() -> None:
    app = _AppStub()
    app.unpin_effect_pair()  # must not raise
    assert app._pinned_pair is None
