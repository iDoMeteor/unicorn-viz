"""Regression tests for category pinning (pin_category/unpin_category).

Requested as a companion to the existing single-effect lock/pin
(lock_effect()/effects_browser_pin()): pinning one specific effect freezes
rotation there entirely (ProjectM-only mode is the canonical case).
Pinning a *category* instead narrows rotation (auto_advance, auto-vj-01,
manual next/prev) to every effect sharing that category, but keeps things
moving within it -- the two features share the same enforcement point
(_switch_effect) and are mutually exclusive.

The real App methods are exercised unbound against a minimal stub with a
real Playlist (so set_disabled()/effects/advance() behave exactly as in
production) -- no SDL/GL context is created, matching the pattern in
test_effect_crash_isolation.py and test_app_effect_pinning.py.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from unicornviz.app import App
from unicornviz.playlist import Playlist


class _Cfg:
    def get(self, *_keys: str, default: Any = None) -> Any:
        return default


def _destroy(self: Any) -> None:
    self.destroyed = True


def _fx(name: str, tags: list[str]) -> type:
    return type(name, (), {'NAME': name, 'TAGS': tags, 'parameters': {}, 'destroy': _destroy})


# Two categories ('drop-a'/'drop-b' via TAGS[0]) plus one untagged effect,
# which falls back to its pack ('core' -- see registry.category_of()).
_EFFECT_A1 = _fx('Effect A1', ['cat-a'])
_EFFECT_A2 = _fx('Effect A2', ['cat-a'])
_EFFECT_B1 = _fx('Effect B1', ['cat-b'])
_EFFECT_B2 = _fx('Effect B2', ['cat-b'])
_EFFECT_NO_TAGS = _fx('Effect Untagged', [])


def _make_playlist() -> Playlist:
    classes = [_EFFECT_A1, _EFFECT_A2, _EFFECT_B1, _EFFECT_B2, _EFFECT_NO_TAGS]
    return Playlist(classes, _Cfg())


class _AppStub:
    """Bare attribute surface for the category-pinning + switch-effect methods."""

    def __init__(self, playlist: Playlist) -> None:
        self.cfg = _Cfg()
        self._ctx = None
        self._width = 64
        self._height = 64
        self._effect_config_overrides: dict[str, dict] = {}
        self._effect_crash_counts: dict[str, int] = {}
        self._effect_blocklist: set[str] = set()
        self._effect_crash_recover = False
        self._current_effect: Any = None
        self._next_effect: Any = None
        self._pinned_pair: Any = None
        self._previous_effect_name = ''
        self._invert_colors = False
        self._projectm_manager_modal_active = False
        self._effect_lock: str | None = None
        self._category_lock: str | None = None
        self._disabled_effects: set[str] = set()
        self._playlist: Any = playlist
        self._transition_t = 0.5
        self._rng = np.random.default_rng(0)

    def _instantiate(self, cls: type, width: int | None = None,
                     height: int | None = None) -> Any:
        inst = object.__new__(cls)
        return inst

    _register_effect_crash = App._register_effect_crash
    _resolve_unblocked_effect = App._resolve_unblocked_effect
    _handle_effect_crash = App._handle_effect_crash
    _EFFECT_CRASH_LIMIT = App._EFFECT_CRASH_LIMIT
    _switch_effect = App._switch_effect
    unpin_effect_pair = App.unpin_effect_pair
    unlock_effect = App.unlock_effect
    pin_category = App.pin_category
    unpin_category = App.unpin_category
    _sync_playlist_disabled = App._sync_playlist_disabled
    category_lock = App.category_lock


def _start_on(app: _AppStub, cls: type) -> None:
    app._playlist.go_index(app._playlist.effects.index(cls))
    app._current_effect = app._instantiate(cls)
    app._current_effect.NAME = cls.NAME


def test_pin_category_narrows_playlist_rotation() -> None:
    app = _AppStub(_make_playlist())
    ok = app.pin_category('cat-a')
    assert ok is True
    assert app.category_lock == 'cat-a'
    for _ in range(10):
        cls = app._playlist.advance()
        assert cls.NAME in {'Effect A1', 'Effect A2'}


def test_pin_category_switches_immediately_if_current_effect_is_outside_it() -> None:
    """_switch_effect only begins the transition (sets _next_effect); the
    cutover to _current_effect happens once it completes, same as any
    other effect switch -- see test_effect_crash_isolation.py."""
    app = _AppStub(_make_playlist())
    _start_on(app, _EFFECT_B1)
    app.pin_category('cat-a')
    assert app._next_effect.NAME in {'Effect A1', 'Effect A2'}


def test_pin_category_does_not_switch_if_already_inside_it() -> None:
    app = _AppStub(_make_playlist())
    _start_on(app, _EFFECT_A1)
    same_instance = app._current_effect
    app.pin_category('cat-a')
    assert app._current_effect is same_instance


def test_pin_category_returns_false_for_unknown_category() -> None:
    app = _AppStub(_make_playlist())
    assert app.pin_category('does-not-exist') is False
    assert app.category_lock is None


def test_pin_category_clears_an_active_effect_lock() -> None:
    app = _AppStub(_make_playlist())
    app._effect_lock = 'Effect B1'
    app.pin_category('cat-a')
    assert app._effect_lock is None
    assert app.category_lock == 'cat-a'


def test_switch_effect_redirects_an_out_of_category_target_within_category() -> None:
    """Simulates a caller that bypasses the playlist entirely (auto-vj-01's
    own goto_effect-style pick): _switch_effect must not leave the pinned
    category, but must also not just silently drop the switch."""
    app = _AppStub(_make_playlist())
    app.pin_category('cat-a')
    App._switch_effect(app, _EFFECT_B1)  # type: ignore[arg-type]
    assert app._next_effect.NAME in {'Effect A1', 'Effect A2'}


def test_switch_effect_allows_a_target_inside_the_pinned_category() -> None:
    app = _AppStub(_make_playlist())
    app.pin_category('cat-a')
    App._switch_effect(app, _EFFECT_A2)  # type: ignore[arg-type]
    assert app._next_effect.NAME == 'Effect A2'


def test_unpin_category_restores_full_rotation() -> None:
    app = _AppStub(_make_playlist())
    app.pin_category('cat-a')
    app.unpin_category()
    assert app.category_lock is None
    seen = {app._playlist.advance().NAME for _ in range(20)}
    assert seen == {'Effect A1', 'Effect A2', 'Effect B1', 'Effect B2', 'Effect Untagged'}


def test_unpin_category_preserves_the_operators_own_manual_disables() -> None:
    """A manual disable made before (or during) the pin must survive the
    pin/unpin round trip -- _sync_playlist_disabled() is the mechanism that
    keeps this from getting clobbered."""
    app = _AppStub(_make_playlist())
    app._disabled_effects = {'Effect B2'}
    app._sync_playlist_disabled()
    app.pin_category('cat-a')
    app.unpin_category()
    for _ in range(20):
        assert app._playlist.advance().NAME != 'Effect B2'


def test_disabling_an_in_category_effect_while_pinned_still_excludes_it() -> None:
    """set_effect_enabled()-equivalent behavior: adding to _disabled_effects
    while a category is pinned must not silently undo the category
    narrowing (the bug _sync_playlist_disabled() exists to prevent)."""
    app = _AppStub(_make_playlist())
    app.pin_category('cat-a')
    app._disabled_effects.add('Effect A2')
    app._sync_playlist_disabled()
    for _ in range(20):
        cls = app._playlist.advance()
        assert cls.NAME == 'Effect A1'  # the only cat-a effect left enabled


def test_untagged_effect_falls_back_to_its_pack_as_category() -> None:
    app = _AppStub(_make_playlist())
    ok = app.pin_category('core')  # this test module's _fx() classes have no real file
    assert ok is True
    assert app._playlist.advance().NAME == 'Effect Untagged'
