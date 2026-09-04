"""Effects-browser favorites (F key) — regression tests.

A favorite marks up to ``App.MAX_FAVORITE_EFFECTS`` (16) effects for a
future 1:1 mapping onto a 16-pad MIDI grid (e.g. an Akai APC mini's
clip-launch pads). Slot assignment is automatic (lowest free slot) —
mirrors the numeric-hotkey-pin persistence pattern in
test_hotkey_slot_repack_and_pinning.py, but favorites are never manually
assigned to a specific slot by the operator, only toggled on/off.
"""
from __future__ import annotations

from pathlib import Path

import sdl2

from unicornviz.app import App
from unicornviz.hotkeys import HotkeyHandler
from unicornviz.playlist import Playlist
from unicornviz.runtime_state import RuntimeStateStore


def _fx(name: str):
    return type(name, (), {'NAME': name, 'TAGS': []})


class _StubCfg:
    def get(self, *_keys, default=None):
        return default


def _app(tmp_path: Path) -> App:
    app = object.__new__(App)
    app._runtime_state = RuntimeStateStore(tmp_path / 'state.json')
    app._favorite_effects = {
        int(k): str(v)
        for k, v in (app._runtime_state.get('effects.favorites', {}) or {}).items()
        if 0 <= int(k) < App.MAX_FAVORITE_EFFECTS
    }
    app._playlist = None
    app._overlays = None
    return app


# --------------------------------------------------------------------------- #
# App: favorite query/toggle API
# --------------------------------------------------------------------------- #

def test_max_favorite_effects_is_sixteen() -> None:
    assert App.MAX_FAVORITE_EFFECTS == 16


def test_toggle_favorite_on_then_off(tmp_path: Path) -> None:
    app = _app(tmp_path)
    assert app.is_favorite('Plasma') is False

    is_fav, msg = app.toggle_favorite('Plasma')
    assert is_fav is True
    assert 'favorited' in msg
    assert app.is_favorite('Plasma') is True
    assert app.favorite_slot_for('Plasma') == 0

    is_fav2, msg2 = app.toggle_favorite('Plasma')
    assert is_fav2 is False
    assert 'removed' in msg2
    assert app.is_favorite('Plasma') is False
    assert app.favorite_slot_for('Plasma') is None


def test_favorite_slots_auto_assign_lowest_free(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.toggle_favorite('A')
    app.toggle_favorite('B')
    app.toggle_favorite('C')
    assert app.favorite_effects() == {0: 'A', 1: 'B', 2: 'C'}
    # Freeing a middle slot backfills it on the next favorite, not the tail.
    app.toggle_favorite('B')
    app.toggle_favorite('D')
    assert app.favorite_effects() == {0: 'A', 1: 'D', 2: 'C'}


def test_favorite_pool_is_capped_at_sixteen(tmp_path: Path) -> None:
    app = _app(tmp_path)
    for i in range(App.MAX_FAVORITE_EFFECTS):
        is_fav, _msg = app.toggle_favorite(f'E{i}')
        assert is_fav is True
    assert len(app.favorite_effects()) == 16

    is_fav, msg = app.toggle_favorite('One Too Many')
    assert is_fav is False
    assert '16 max' in msg
    assert app.is_favorite('One Too Many') is False
    assert len(app.favorite_effects()) == 16  # the pool didn't evict anyone


def test_set_favorite_slot_moves_and_replaces(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.set_favorite_slot(5, 'Plasma')
    assert app.favorite_effects() == {5: 'Plasma'}
    # Re-assigning the same effect to a new slot drops the old one.
    app.set_favorite_slot(2, 'Plasma')
    assert app.favorite_effects() == {2: 'Plasma'}
    # A different effect claiming slot 2 doesn't touch anything else.
    app.set_favorite_slot(9, 'Tunnel')
    app.set_favorite_slot(2, 'Cosmos')
    assert app.favorite_effects() == {2: 'Cosmos', 9: 'Tunnel'}


def test_set_favorite_slot_out_of_range_is_ignored(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.set_favorite_slot(-1, 'Plasma')
    app.set_favorite_slot(16, 'Plasma')
    app.set_favorite_slot(999, 'Plasma')
    assert app.favorite_effects() == {}


def test_set_favorite_slot_clear_with_none(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.set_favorite_slot(0, 'Plasma')
    app.set_favorite_slot(0, None)
    assert app.favorite_effects() == {}


def test_favorites_persist_across_instances(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.toggle_favorite('Tunnel')
    app2 = _app(tmp_path)
    assert app2.favorite_effects() == {0: 'Tunnel'}


# --------------------------------------------------------------------------- #
# App: effects_browser_toggle_favorite (live model update)
# --------------------------------------------------------------------------- #

class _StubBrowser:
    def __init__(self, entries: list[dict]) -> None:
        self._entries = entries
        self._selected = 0

    def selected_entry(self):
        return self._entries[self._selected] if self._entries else None


class _StubOverlays:
    def __init__(self, entries: list[dict]) -> None:
        self.effects_browser = _StubBrowser(entries)


def test_effects_browser_toggle_favorite_updates_live_model(tmp_path: Path) -> None:
    app = _app(tmp_path)
    entries = [
        {'display_name': 'Plasma', 'favorite_slot': None},
        {'display_name': 'Tunnel', 'favorite_slot': None},
    ]
    app._overlays = _StubOverlays(entries)

    msg = app.effects_browser_toggle_favorite()
    assert 'favorited' in msg
    assert entries[0]['favorite_slot'] == 0
    assert entries[1]['favorite_slot'] is None  # unrelated row untouched

    msg2 = app.effects_browser_toggle_favorite()
    assert 'removed' in msg2
    assert entries[0]['favorite_slot'] is None


def test_effects_browser_toggle_favorite_no_selection_is_noop(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app._overlays = _StubOverlays([])
    assert app.effects_browser_toggle_favorite() is None


# --------------------------------------------------------------------------- #
# _effects_browser_entries: favorite_slot field
# --------------------------------------------------------------------------- #

def test_browser_entries_carry_favorite_slot(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app._disabled_effects = set()
    app._hotkey_pins = {}
    app.toggle_favorite('Plasma')

    class _Entry:
        def __init__(self, name):
            self.name = name
            self.category = 'classic'
            self.pack = 'core'
            self.tags = []
            self.cls = _fx(name)

    import unicornviz.effects.registry as registry
    orig = registry.browser_entries
    registry.browser_entries = lambda: [_Entry('Plasma'), _Entry('Tunnel')]
    try:
        rows = app._effects_browser_entries()
    finally:
        registry.browser_entries = orig

    by_name = {r['display_name']: r for r in rows}
    assert by_name['Plasma']['favorite_slot'] == 0
    assert by_name['Tunnel']['favorite_slot'] is None


# --------------------------------------------------------------------------- #
# End-to-end: HotkeyHandler dispatches F inside the effects browser
# --------------------------------------------------------------------------- #

class _Overlay:
    help_visible = False
    midi_selector_visible = False
    name_overlay_visible = False
    controller_help_modal_visible = False
    webcam_editor_modal_visible = False
    audio_selector_visible = False
    effects_browser_visible = True
    presets_visible = False
    projectm_manager_visible = False
    context_menu_open = False
    config_editor_open = False
    tour_visible = False

    def __init__(self):
        self.messages = []

    def flash_message(self, msg, *_a, **_kw):
        self.messages.append(msg)

    def flash_name(self, *_a, **_kw):
        pass

    def note_help_activity(self):
        pass


class _Audio:
    def get_reactivity(self) -> float:
        return 1.0


class _VJApi:
    def mark_user_action(self, _kind: str) -> None:
        return

    def key_handler_items(self):
        return []


def test_end_to_end_f_key_toggles_favorite_in_browser(tmp_path: Path) -> None:
    app = _app(tmp_path)
    fx = [_fx('A'), _fx('B')]
    playlist = Playlist(fx, _StubCfg())
    app._playlist = playlist
    app._current_effect = None
    app._auto_vj = None
    app._keystroke_logger = None
    app.vj_api = _VJApi()
    app.hotkey_overrides = lambda: {}

    entries = [{'display_name': 'A', 'favorite_slot': None}]
    overlay = _Overlay()
    overlay.effects_browser = _StubBrowser(entries)
    app._overlays = overlay

    handler = HotkeyHandler(app, playlist, overlay, _Audio())
    handler.handle(sdl2.SDLK_f, 0)

    assert app.is_favorite('A') is True
    assert entries[0]['favorite_slot'] == 0
    assert any('favorited' in m for m in overlay.messages)
