"""Scene-crossfade signalling to effects.

During a blend the app renders *two* effects every frame, so it is the worst
moment for an effect to do expensive deferrable work.  ``transition_active``
lets an effect hold that work; ProjectM uses it to keep a synchronous shader
compile out of the blend.
"""
from __future__ import annotations

from unicornviz.effects.base import BaseEffect


class _Effect(BaseEffect):
    """Minimal concrete effect; BaseEffect.render is abstract."""

    NAME = 'flag probe'

    def __init__(self) -> None:  # noqa: D107 - bypasses GL setup on purpose
        self.parameters = {}

    def render(self) -> None:
        pass


def test_defaults_to_not_transitioning() -> None:
    """Effects that never look at the flag must behave as before."""
    assert BaseEffect.transition_active is False
    assert _Effect().transition_active is False


def test_flag_is_per_instance_not_shared() -> None:
    """Setting it on one effect must not mark every other effect too."""
    a, b = _Effect(), _Effect()
    a.transition_active = True
    assert b.transition_active is False
    assert BaseEffect.transition_active is False


class _App:
    """The app's per-frame flag maintenance, isolated from the render loop."""

    def __init__(self, current, nxt) -> None:
        self._current_effect = current
        self._next_effect = nxt

    def mark(self) -> None:
        blending = self._next_effect is not None
        if self._current_effect is not None:
            self._current_effect.transition_active = blending
        if self._next_effect is not None:
            self._next_effect.transition_active = True


def test_both_effects_marked_while_blending() -> None:
    cur, nxt = _Effect(), _Effect()
    _App(cur, nxt).mark()
    assert cur.transition_active is True
    assert nxt.transition_active is True


def test_flag_clears_when_the_blend_finishes() -> None:
    """Derived from live state each frame, so it cannot stick on."""
    cur = _Effect()
    cur.transition_active = True
    _App(cur, None).mark()
    assert cur.transition_active is False


def test_no_current_effect_is_harmless() -> None:
    _App(None, None).mark()  # must not raise
