"""Regression tests for VjApi's effect-pinning wrappers.

Thin pass-through layer over App.pin_effect_pair()/cut_to_pinned()/
unpin_effect_pair() (see test_app_effect_pinning.py for the underlying
mechanics) -- these tests cover the name/class resolution VjApi adds on
top, per the "drop-ins go through vj_api, not app._private" rule.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from unicornviz.app import App
from unicornviz.config import Config


def _default_cfg() -> Config:
    return Config(Path('tests') / '_missing_config_for_tests.toml')


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


def test_pin_effect_pair_by_class_object() -> None:
    app = App(_default_cfg())

    ok = app.vj_api.pin_effect_pair(_EffectA, _EffectB)

    assert ok is True
    assert isinstance(app._pinned_pair['a'], _EffectA)
    assert isinstance(app._pinned_pair['b'], _EffectB)


def test_pin_effect_pair_returns_false_for_unresolvable_name() -> None:
    app = App(_default_cfg())

    assert app.vj_api.pin_effect_pair('Not A Real Effect', _EffectB) is False
    assert app._pinned_pair is None


def test_cut_to_pinned_effect_swaps_the_render_target() -> None:
    app = App(_default_cfg())
    app.vj_api.pin_effect_pair(_EffectA, _EffectB)
    pair = app._pinned_pair

    assert app.vj_api.cut_to_pinned_effect('b') is True
    assert app._current_effect is pair['b']


def test_unpin_effect_pair_releases_the_offscreen_instance() -> None:
    app = App(_default_cfg())
    app.vj_api.pin_effect_pair(_EffectA, _EffectB)
    pair = app._pinned_pair
    app.vj_api.cut_to_pinned_effect('a')

    app.vj_api.unpin_effect_pair()

    assert pair['b'].destroyed is True
    assert pair['a'].destroyed is False
    assert app._pinned_pair is None
