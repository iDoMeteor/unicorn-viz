"""Hotkey integration tests for the show-presets modal.

Covers Ctrl+Shift+P open, list nav, load (Enter), delete (D), and the inline
name-entry save flow (S -> type -> Enter). Drives a real CatalogBrowser through
the fake overlay; app-side actions are recorded on a fake.
"""
from __future__ import annotations

import sdl2

from unicornviz.catalog_browser import CatalogBrowser
from unicornviz.hotkeys import HotkeyHandler


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
    effects_browser_visible = False

    def __init__(self) -> None:
        self.presets_visible = False
        self.presets_browser = CatalogBrowser()
        self.presets_browser.set_entries([
            {'display_name': 'Ambient', 'category_key': 'preset', 'tags': []},
            {'display_name': 'Streaming', 'category_key': 'preset', 'tags': []},
        ])
        self._name_mode = False
        self._name_text = ''
        self.messages: list[str] = []

    def toggle_presets(self) -> None:
        self.presets_visible = not self.presets_visible

    def set_presets_entries(self, names) -> None:
        self.presets_browser.set_entries(
            [{'display_name': str(n), 'category_key': 'preset', 'tags': []} for n in names]
        )

    @property
    def presets_name_mode(self) -> bool:
        return self._name_mode

    def set_presets_name_mode(self, active: bool) -> None:
        self._name_mode = bool(active)
        if not self._name_mode:
            self._name_text = ''

    @property
    def presets_name_text(self) -> str:
        return self._name_text

    def set_presets_name_text(self, text: str) -> None:
        self._name_text = str(text)

    def flash_message(self, text, *_a, **_kw) -> None:
        self.messages.append(str(text))


class _App:
    def __init__(self, overlay: _Overlay) -> None:
        self.vj_api = _VJApi()
        self.auto_vj_controller = None
        self.current_effect = None
        self.current_effect_name = '-'
        self._keystroke_logger = None
        self._midi_manager = None
        self._overlay = overlay
        self.saved: list[str] = []
        self.calls: list[tuple[str, object]] = []

    def open_presets(self) -> None:
        self.calls.append(('open', None))
        if not self._overlay.presets_visible:
            self._overlay.toggle_presets()

    def close_presets(self) -> None:
        self.calls.append(('close', None))
        if self._overlay.presets_visible:
            self._overlay.toggle_presets()

    def presets_load_selected(self):
        entry = self._overlay.presets_browser.selected_entry()
        name = entry['display_name'] if entry else None
        self.calls.append(('load', name))
        if name:
            self._overlay.toggle_presets()
        return name

    def presets_delete_selected(self):
        entry = self._overlay.presets_browser.selected_entry()
        name = entry['display_name'] if entry else None
        self.calls.append(('delete', name))
        return name

    def presets_save_named(self, name):
        self.saved.append(name)
        self.calls.append(('save', name))
        return name


class _Audio:
    def list_profiles(self):
        return ['house']

    def get_profile_key(self):
        return 'house'

    def get_profile(self):
        return type('P', (), {'name': 'house'})()

    def set_profile(self, _n):
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
    return HotkeyHandler(app, _Playlist(), overlay, _Audio()), app, overlay


def test_ctrl_shift_p_opens_presets():
    handler, app, overlay = _setup()
    handler.handle(sdl2.SDLK_p, sdl2.KMOD_CTRL | sdl2.KMOD_SHIFT)
    assert overlay.presets_visible
    assert ('open', None) in app.calls


def test_context_resolver_reports_presets():
    handler, _app, overlay = _setup()
    overlay.presets_visible = True
    assert handler._active_midi_context() == 'presets'


def test_enter_loads_selected_preset():
    handler, app, overlay = _setup()
    overlay.presets_visible = True
    handler.handle(sdl2.SDLK_DOWN, 0)         # select 'Streaming'
    handler.handle(sdl2.SDLK_RETURN, 0)
    assert ('load', 'Streaming') in app.calls
    assert not overlay.presets_visible


def test_d_deletes_selected_preset():
    handler, app, overlay = _setup()
    overlay.presets_visible = True
    handler.handle(sdl2.SDLK_d, 0)
    assert ('delete', 'Ambient') in app.calls


def test_save_flow_s_then_type_then_enter():
    handler, app, overlay = _setup()
    overlay.presets_visible = True
    handler.handle(sdl2.SDLK_s, 0)            # enter name-entry mode
    assert overlay.presets_name_mode
    for ch in (sdl2.SDLK_r, sdl2.SDLK_a, sdl2.SDLK_v, sdl2.SDLK_e):
        handler.handle(ch, 0)
    assert overlay.presets_name_text == 'rave'
    handler.handle(sdl2.SDLK_RETURN, 0)       # confirm save
    assert app.saved == ['rave']
    assert not overlay.presets_name_mode


def test_escape_closes_presets():
    handler, app, overlay = _setup()
    overlay.presets_visible = True
    handler.handle(sdl2.SDLK_ESCAPE, 0)
    assert ('close', None) in app.calls
    assert not overlay.presets_visible


def test_context_slot_navigates_presets():
    """Slot 1 must drive the open modal.

    The 'presets' context had no slot table, so every slot fell back to the
    performance bindings; the modal then swallowed those chords, leaving all
    eight slots inert while the modal was open.
    """
    handler, app, overlay = _setup()
    overlay.presets_visible = True
    overlay.presets_browser.move_selection(1)          # start on 'Streaming'

    assert handler._dispatch_context_slot(1) is True    # slot 1 -> up

    assert overlay.presets_browser.selected_entry()['display_name'] == 'Ambient'
    assert not any(kind == 'load' for kind, _ in app.calls)


def test_unbound_presets_context_slot_is_swallowed():
    """A slot the context leaves unbound must not leak a performance action.

    Slot 6 is deliberately unbound in the presets context (its only candidates
    were destructive delete / a text field). It must no-op rather than firing
    performance slot 6.
    """
    handler, app, overlay = _setup()
    overlay.presets_visible = True

    assert handler._dispatch_context_slot(6) is True    # handled, but a no-op

    assert app.calls == []
    assert overlay.presets_visible
