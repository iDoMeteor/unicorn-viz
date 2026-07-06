"""Numeric-hotkey dynamic re-pack + slot pinning — regression tests.

Covers the fix for two bugs: (1) numeric hotkeys mapped into a snapshot of
*all* effects taken once at startup, so enabling/disabling an effect never
changed the mapping and a stray press could land on a disabled effect;
(2) there was no way to pin a favourite effect to a specific slot so it
survives re-packing. See docs/planning/vj-tags-and-hotkey-system-plan.md §3.
"""
from __future__ import annotations

from pathlib import Path

import sdl2

from unicornviz.app import App
from unicornviz.hotkeys import hotkey_slot_label, numeric_slot_index
from unicornviz.playlist import Playlist
from unicornviz.runtime_state import RuntimeStateStore


def _fx(name: str):
    return type(name, (), {'NAME': name, 'TAGS': []})


class _StubCfg:
    def get(self, *_keys, default=None):
        return default


def _playlist(names: list[str]) -> Playlist:
    return Playlist([_fx(n) for n in names], _StubCfg())


# --------------------------------------------------------------------------- #
# numeric_slot_index / hotkey_slot_label
# --------------------------------------------------------------------------- #

def test_numeric_slot_index_naked_and_modifiers() -> None:
    assert numeric_slot_index(sdl2.SDLK_1, 0) == 0
    assert numeric_slot_index(sdl2.SDLK_9, 0) == 8
    assert numeric_slot_index(sdl2.SDLK_0, 0) == 9
    assert numeric_slot_index(sdl2.SDLK_1, sdl2.KMOD_SHIFT) == 10
    assert numeric_slot_index(sdl2.SDLK_0, sdl2.KMOD_SHIFT) == 19
    assert numeric_slot_index(sdl2.SDLK_1, sdl2.KMOD_CTRL) == 20
    assert numeric_slot_index(sdl2.SDLK_0, sdl2.KMOD_CTRL) == 29
    assert numeric_slot_index(sdl2.SDLK_1, sdl2.KMOD_ALT) == 30
    assert numeric_slot_index(sdl2.SDLK_0, sdl2.KMOD_ALT) == 39


def test_numeric_slot_index_shift_symbol_fallback() -> None:
    assert numeric_slot_index(sdl2.SDLK_EXCLAIM, 0) == 10
    assert numeric_slot_index(sdl2.SDLK_RIGHTPAREN, 0) == 19


def test_numeric_slot_index_non_number_returns_none() -> None:
    assert numeric_slot_index(sdl2.SDLK_a, 0) is None
    assert numeric_slot_index(sdl2.SDLK_F1, 0) is None


def test_hotkey_slot_label() -> None:
    assert hotkey_slot_label(0) == '1'
    assert hotkey_slot_label(9) == '0'
    assert hotkey_slot_label(10) == 'S+1'
    assert hotkey_slot_label(19) == 'S+0'
    assert hotkey_slot_label(20) == 'C+1'
    assert hotkey_slot_label(30) == 'A+1'
    assert hotkey_slot_label(39) == 'A+0'


# --------------------------------------------------------------------------- #
# Playlist: dynamic re-pack over the enabled set
# --------------------------------------------------------------------------- #

def test_shortcut_effects_excludes_disabled() -> None:
    p = _playlist(['Plasma', 'Tunnel', 'Cosmos'])
    p.set_disabled({'Tunnel'})
    names = [c.NAME for c in p.shortcut_effects]
    assert names == ['Plasma', 'Cosmos']


def test_shortcut_effects_recomputes_live_no_caching() -> None:
    p = _playlist(['Plasma', 'Tunnel', 'Cosmos'])
    assert [c.NAME for c in p.shortcut_effects] == ['Plasma', 'Tunnel', 'Cosmos']
    p.set_disabled({'Plasma'})
    # Same property access, fresh result reflecting the new disabled set.
    assert [c.NAME for c in p.shortcut_effects] == ['Tunnel', 'Cosmos']
    p.set_disabled(set())
    assert [c.NAME for c in p.shortcut_effects] == ['Plasma', 'Tunnel', 'Cosmos']


def test_shortcut_effects_excludes_unicorn_tears() -> None:
    # The real class name is "UnicornTears" (no space); NAME is the display
    # name "Unicorn Tears". Exclusion checks __name__, matching the real class.
    unicorn_tears = type('UnicornTears', (), {'NAME': 'Unicorn Tears', 'TAGS': []})
    p = Playlist([_fx('Plasma'), unicorn_tears], _StubCfg())
    names = [c.NAME for c in p.shortcut_effects]
    assert names == ['Plasma']


def test_shortcut_effects_consolidates_gaps() -> None:
    # Disabling an effect in the middle must not leave a hole; later effects
    # shift down to fill it (the "consolidate/expand" behaviour requested).
    p = _playlist(['A', 'B', 'C', 'D'])
    p.set_disabled({'B'})
    assert [c.NAME for c in p.shortcut_effects] == ['A', 'C', 'D']


# --------------------------------------------------------------------------- #
# Playlist: slot pinning
# --------------------------------------------------------------------------- #

def test_pin_claims_its_slot() -> None:
    p = _playlist(['A', 'B', 'C', 'D'])
    p.set_hotkey_pins({2: 'D'})
    names = [c.NAME for c in p.shortcut_effects]
    assert names[2] == 'D'
    assert set(names) == {'A', 'B', 'C', 'D'}
    assert len(names) == 4


def test_pin_ignored_while_effect_disabled_then_restored() -> None:
    p = _playlist(['A', 'B', 'C'])
    p.set_hotkey_pins({0: 'C'})
    assert [c.NAME for c in p.shortcut_effects][0] == 'C'
    p.set_disabled({'C'})
    # Pin can't be honoured while disabled; list just consolidates to the rest.
    assert [c.NAME for c in p.shortcut_effects] == ['A', 'B']
    p.set_disabled(set())
    # Recomputed fresh -> pin re-applies automatically, no stale state.
    assert [c.NAME for c in p.shortcut_effects][0] == 'C'


def test_pin_beyond_enabled_count_not_honoured() -> None:
    p = _playlist(['A', 'B'])
    p.set_hotkey_pins({5: 'A'})  # only 2 enabled effects; slot 5 unreachable
    names = [c.NAME for c in p.shortcut_effects]
    assert names == ['A', 'B']  # falls back to catalog order


def test_set_hotkey_pins_replaces_and_validates() -> None:
    p = _playlist(['A', 'B'])
    p.set_hotkey_pins({0: 'A', 1: 'B'})
    p.set_hotkey_pins({'0': 'B'})  # string key + full replace
    assert p.hotkey_pins() == {0: 'B'}
    p.set_hotkey_pins({-1: 'A', 999: 'A', 0: ''})  # invalid slots/empty name dropped
    assert p.hotkey_pins() == {}


def test_pin_accepts_display_name_or_class_name() -> None:
    p = _playlist(['Plasma'])
    p.set_hotkey_pins({0: 'Plasma'})  # matches both NAME and __name__ here
    assert p.shortcut_effects[0].NAME == 'Plasma'


# --------------------------------------------------------------------------- #
# App: pin persistence + query API
# --------------------------------------------------------------------------- #

def _app(tmp_path: Path) -> App:
    app = object.__new__(App)
    app._runtime_state = RuntimeStateStore(tmp_path / 'state.json')
    app._hotkey_pins = {
        int(k): str(v)
        for k, v in (app._runtime_state.get('effects.hotkey_pins', {}) or {}).items()
    }
    app._playlist = None
    app._overlays = None
    return app


def test_app_set_and_query_pin(tmp_path: Path) -> None:
    app = _app(tmp_path)
    assert app.hotkey_pin_slot_for('Plasma') is None
    app.set_hotkey_pin(3, 'Plasma')
    assert app.hotkey_pins() == {3: 'Plasma'}
    assert app.hotkey_pin_slot_for('Plasma') == 3


def test_app_pin_persists_across_instances(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.set_hotkey_pin(7, 'Tunnel')
    app2 = _app(tmp_path)
    assert app2.hotkey_pins() == {7: 'Tunnel'}


def test_app_pinning_effect_to_new_slot_drops_old_pin(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.set_hotkey_pin(1, 'Plasma')
    app.set_hotkey_pin(4, 'Plasma')
    assert app.hotkey_pins() == {4: 'Plasma'}


def test_app_toggle_hotkey_pin(tmp_path: Path) -> None:
    app = _app(tmp_path)
    assert app.toggle_hotkey_pin(2, 'Plasma') is True
    assert app.hotkey_pins() == {2: 'Plasma'}
    assert app.toggle_hotkey_pin(2, 'Plasma') is False
    assert app.hotkey_pins() == {}


def test_app_clear_pin_with_none(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.set_hotkey_pin(0, 'Plasma')
    app.set_hotkey_pin(0, None)
    assert app.hotkey_pins() == {}


# --------------------------------------------------------------------------- #
# App: effects_browser_toggle_pin_slot (live model update)
# --------------------------------------------------------------------------- #

class _StubBrowser:
    def __init__(self, entries: list[dict]) -> None:
        self._entries = entries
        self._selected = 0

    def selected_entry(self):
        return self._entries[self._selected] if self._entries else None

    def entries(self):
        return list(self._entries)


class _StubOverlays:
    def __init__(self, entries: list[dict]) -> None:
        self.effects_browser = _StubBrowser(entries)


def test_effects_browser_toggle_pin_slot_updates_live_model(tmp_path: Path) -> None:
    app = _app(tmp_path)
    entries = [
        {'display_name': 'Plasma', 'hotkey_slot': None},
        {'display_name': 'Tunnel', 'hotkey_slot': None},
    ]
    app._overlays = _StubOverlays(entries)

    msg = app.effects_browser_toggle_pin_slot(2)
    assert 'pinned to key 3' in msg
    assert entries[0]['hotkey_slot'] == 2
    assert entries[1]['hotkey_slot'] is None

    # Selecting a different entry and pinning the SAME slot reassigns it.
    app._overlays.effects_browser._selected = 1
    msg2 = app.effects_browser_toggle_pin_slot(2)
    assert 'pinned to key 3' in msg2
    assert entries[0]['hotkey_slot'] is None   # Plasma lost its pin
    assert entries[1]['hotkey_slot'] == 2       # Tunnel now holds slot 2

    # Re-pressing the same chord on the effect that now holds it unpins.
    msg3 = app.effects_browser_toggle_pin_slot(2)
    assert 'unpinned' in msg3
    assert entries[1]['hotkey_slot'] is None
