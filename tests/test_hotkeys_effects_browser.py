"""Hotkey integration tests for the effects browser modal.

Covers naked-B open/close (core hotkey), the active-context resolver, and key
routing while the browser is visible (nav, category switch, search, commit, pin,
close). Drives a
real ``CatalogBrowser`` through the fake overlay so selection/search semantics
are exercised end-to-end; the App-side actions are recorded on a fake.
"""
from __future__ import annotations

import sdl2

from unicornviz.catalog_browser import CatalogBrowser
from unicornviz.hotkeys import HotkeyHandler


def _entry(name, category, tags, pack):
    return {
        'display_name': name,
        'category_key': category,
        'tags': list(tags),
        'pack_name': pack,
        'cls': type('E', (), {'NAME': name}),
    }


class _VJApi:
    def mark_user_action(self, _kind: str) -> None:
        pass

    def key_handler_items(self):
        return []

    def unregister_key_handler(self, _name: str) -> None:
        pass


class _Overlay:
    midi_selector_visible = False
    system_monitor_modal_visible = False
    help_visible = False
    name_overlay_visible = False
    controller_help_modal_visible = False
    webcam_editor_modal_visible = False
    audio_selector_visible = False
    projectm_manager_visible = False

    def __init__(self) -> None:
        self.effects_browser_visible = False
        self.effects_browser = CatalogBrowser()
        self.effects_browser.set_entries([
            _entry('Plasma', 'psychedelic', ['classic'], 'psychedelic-01'),
            _entry('Kaleidoscope', 'psychedelic', ['classic'], 'psychedelic-01'),
            _entry('Tron Grid', 'tech', ['neon'], 'tech-01'),
        ])
        self.messages: list[str] = []

    def toggle_effects_browser(self) -> None:
        self.effects_browser_visible = not self.effects_browser_visible

    def set_effects_browser_entries(self, entries, current_name) -> None:
        self.effects_browser.set_entries(entries)

    def flash_message(self, text, *_a, **_kw) -> None:
        self.messages.append(str(text))


class _App:
    def __init__(self, overlay: _Overlay) -> None:
        self.vj_api = _VJApi()
        self.auto_vj_controller = None
        self.current_effect = None
        self.current_effect_name = 'Plasma'
        self._keystroke_logger = None
        self._midi_manager = None
        self._overlay = overlay
        self.pinned: str = ''
        self.calls: list[tuple[str, object]] = []

    def open_effects_browser(self) -> None:
        self.calls.append(('open', None))
        if not self._overlay.effects_browser_visible:
            self._overlay.toggle_effects_browser()

    def close_effects_browser(self, commit: bool) -> None:
        self.calls.append(('close', bool(commit)))
        if self._overlay.effects_browser_visible:
            self._overlay.toggle_effects_browser()

    def effects_browser_mark_nav(self) -> None:
        self.calls.append(('nav', None))

    def effects_browser_commit(self):
        entry = self._overlay.effects_browser.selected_entry()
        name = entry['display_name'] if entry else None
        self.calls.append(('commit', name))
        self._overlay.toggle_effects_browser()
        return name

    def effects_browser_pin(self):
        entry = self._overlay.effects_browser.selected_entry()
        if entry is None:
            return None
        name = entry['display_name']
        if self.pinned == name:
            self.pinned = ''
            self.calls.append(('unpin', name))
            return f'{name}: unpinned'
        self.pinned = name
        self.calls.append(('pin', name))
        return f'{name}: pinned'

    def effects_browser_toggle_enabled(self):
        entry = self._overlay.effects_browser.selected_entry()
        if entry is None:
            return None
        name = entry['display_name']
        new_enabled = not bool(entry.get('enabled', True))
        entry['enabled'] = new_enabled
        self.calls.append(('toggle_enabled', (name, new_enabled)))
        return f'{name}: {"enabled" if new_enabled else "disabled"}'


class _Audio:
    def list_profiles(self):
        return ['house']

    def get_profile_key(self) -> str:
        return 'house'

    def get_profile(self):
        return type('P', (), {'name': 'house'})()

    def set_profile(self, _name):
        return self.get_profile()


class _Playlist:
    mode = 'sequential'
    index = 0
    effects = []
    shortcut_effects = []

    def advance(self):
        return type('E', (), {'NAME': 'Stub'})


def _setup():
    overlay = _Overlay()
    app = _App(overlay)
    handler = HotkeyHandler(app, _Playlist(), overlay, _Audio())
    return handler, app, overlay


def test_b_opens_browser():
    handler, app, overlay = _setup()
    handler.handle(sdl2.SDLK_b, 0)  # naked B — core hotkey
    assert overlay.effects_browser_visible
    assert ('open', None) in app.calls


def test_b_while_open_closes_browser():
    handler, app, overlay = _setup()
    overlay.effects_browser_visible = True
    handler.handle(sdl2.SDLK_b, 0)
    assert ('close', False) in app.calls
    assert not overlay.effects_browser_visible


def test_context_resolver_reports_effects_browser():
    handler, _app, overlay = _setup()
    overlay.effects_browser_visible = True
    assert handler._active_midi_context() == 'effects_browser'


def test_arrows_navigate_and_left_right_switch_panes():
    from unicornviz.catalog_browser import PANE_CATEGORIES, PANE_LIST

    handler, _app, overlay = _setup()
    overlay.effects_browser_visible = True
    b = overlay.effects_browser
    # Down/Up move the effect selection within the list pane.
    handler.handle(sdl2.SDLK_DOWN, 0)
    assert b.selected_index() == 1
    handler.handle(sdl2.SDLK_UP, 0)
    assert b.selected_index() == 0
    # Left focuses the categories pane; Right focuses the effects pane.
    handler.handle(sdl2.SDLK_LEFT, 0)
    assert b.focus_pane() == PANE_CATEGORIES
    handler.handle(sdl2.SDLK_RIGHT, 0)
    assert b.focus_pane() == PANE_LIST
    # With categories focused, Up/Down move the category tab.
    handler.handle(sdl2.SDLK_LEFT, 0)
    handler.handle(sdl2.SDLK_DOWN, 0)
    assert b.selected_category() != '(all)'


def test_slash_enters_search_and_typing_filters():
    handler, _app, overlay = _setup()
    overlay.effects_browser_visible = True
    b = overlay.effects_browser
    handler.handle(sdl2.SDLK_SLASH, 0)
    assert b.search_mode
    for ch in (sdl2.SDLK_t, sdl2.SDLK_r, sdl2.SDLK_o):
        handler.handle(ch, 0)
    assert b.search_query == 'tro'
    assert [e['display_name'] for e in b.filtered()] == ['Tron Grid']
    handler.handle(sdl2.SDLK_RETURN, 0)  # confirm search, leave search mode
    assert not b.search_mode


def test_enter_commits_selection():
    handler, app, overlay = _setup()
    overlay.effects_browser_visible = True
    handler.handle(sdl2.SDLK_DOWN, 0)  # select Kaleidoscope
    handler.handle(sdl2.SDLK_RETURN, 0)
    assert ('commit', 'Kaleidoscope') in app.calls
    assert not overlay.effects_browser_visible


def test_p_toggles_pin_and_keeps_browser_open():
    handler, app, overlay = _setup()
    overlay.effects_browser_visible = True
    handler.handle(sdl2.SDLK_p, 0)          # pin Plasma
    assert ('pin', 'Plasma') in app.calls
    assert app.pinned == 'Plasma'
    assert overlay.effects_browser_visible  # stays open
    handler.handle(sdl2.SDLK_p, 0)          # P again -> unpin
    assert ('unpin', 'Plasma') in app.calls
    assert app.pinned == ''


def test_space_toggles_enabled():
    handler, app, overlay = _setup()
    overlay.effects_browser_visible = True
    handler.handle(sdl2.SDLK_SPACE, 0)  # toggle selected (Plasma) off
    assert ('toggle_enabled', ('Plasma', False)) in app.calls
    assert overlay.effects_browser.selected_entry()['enabled'] is False
    handler.handle(sdl2.SDLK_SPACE, 0)  # toggle back on
    assert ('toggle_enabled', ('Plasma', True)) in app.calls
    assert overlay.effects_browser_visible  # stays open


def test_escape_closes_without_commit():
    handler, app, overlay = _setup()
    overlay.effects_browser_visible = True
    handler.handle(sdl2.SDLK_ESCAPE, 0)
    assert ('close', False) in app.calls
    assert not overlay.effects_browser_visible


def test_context_slot_2_navigates_instead_of_pinning():
    """Slot 2 must move the selection, never re-pin the selected effect.

    The 'effects_browser' context had no slot table, so slots fell back to the
    performance bindings and the chord was re-dispatched into the open browser.
    Performance slot 2 is 'p' — which the browser consumes as pin/unpin — so an
    operator reaching for "move down" silently pinned the selected effect.
    """
    from unicornviz.catalog_browser import PANE_LIST
    handler, app, overlay = _setup()
    overlay.effects_browser_visible = True
    overlay.effects_browser.set_focus_pane(PANE_LIST)
    overlay.effects_browser.move_selection(1)

    before = overlay.effects_browser.selected_entry()['display_name']
    assert handler._dispatch_context_slot(2) is True    # slot 2 -> down

    assert app.pinned == ''
    assert not any(kind == 'pin' for kind, _ in app.calls)
    assert overlay.effects_browser.selected_entry()['display_name'] != before


def test_context_slot_4_navigates_instead_of_toggling_enabled():
    """Slot 4 must move the selection, never toggle the effect's enabled state.

    Performance slot 4 is Space, which the browser consumes as toggle-enabled.
    """
    from unicornviz.catalog_browser import PANE_LIST
    handler, app, overlay = _setup()
    overlay.effects_browser_visible = True
    overlay.effects_browser.set_focus_pane(PANE_LIST)

    assert handler._dispatch_context_slot(4) is True    # slot 4 -> right

    assert not any(kind == 'toggle_enabled' for kind, _ in app.calls)
    assert all(e.get('enabled', True) for e in overlay.effects_browser.entries())
