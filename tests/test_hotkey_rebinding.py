"""Global-action hotkey rebinding — regression tests.

The "enabler" for a future in-app hotkey editor: a named global action (see
hotkeys._MIDI_NOTE_KEY_BINDINGS / action_names()) can be rebound to a
different key chord. translate_override_chord() converts an incoming rebound
chord back to the action's *default* chord before the existing (unmodified)
dispatch chain in HotkeyHandler.handle() runs, so real key dispatch changes
with zero edits to the ~450-line global elif chain itself.
"""
from __future__ import annotations

from pathlib import Path

import sdl2

from unicornviz.app import App
from unicornviz.hotkeys import (
    HotkeyHandler,
    action_names,
    default_action_binding,
    translate_override_chord,
)
from unicornviz.runtime_state import RuntimeStateStore


# --------------------------------------------------------------------------- #
# translate_override_chord / default_action_binding / action_names
# --------------------------------------------------------------------------- #

def test_default_action_binding_known_and_unknown() -> None:
    assert default_action_binding('fullscreen') == (sdl2.SDLK_f, 0)
    assert default_action_binding('nope-not-real') is None


def test_action_names_includes_expected_entries() -> None:
    names = action_names()
    assert 'fullscreen' in names
    assert 'help' in names
    assert 'next' in names


def test_translate_no_overrides_is_passthrough() -> None:
    assert translate_override_chord(sdl2.SDLK_j, 0, {}) == (sdl2.SDLK_j, 0)


def test_translate_matches_override_returns_default() -> None:
    overrides = {'fullscreen': (sdl2.SDLK_j, 0)}
    # Pressing the REBOUND key (j) resolves to fullscreen's default chord (f).
    assert translate_override_chord(sdl2.SDLK_j, 0, overrides) == (sdl2.SDLK_f, 0)


def test_translate_unrelated_key_passes_through_with_overrides_set() -> None:
    overrides = {'fullscreen': (sdl2.SDLK_j, 0)}
    assert translate_override_chord(sdl2.SDLK_x, 0, overrides) == (sdl2.SDLK_x, 0)


def test_translate_respects_modifier_in_override() -> None:
    overrides = {'help': (sdl2.SDLK_j, sdl2.KMOD_CTRL)}
    # Naked 'j' must NOT translate; only Ctrl+j (the exact override) does.
    assert translate_override_chord(sdl2.SDLK_j, 0, overrides) == (sdl2.SDLK_j, 0)
    assert translate_override_chord(sdl2.SDLK_j, sdl2.KMOD_CTRL, overrides) == (
        sdl2.SDLK_h, 0
    )


# --------------------------------------------------------------------------- #
# App: override persistence
# --------------------------------------------------------------------------- #

def _app(tmp_path: Path) -> App:
    app = object.__new__(App)
    app._runtime_state = RuntimeStateStore(tmp_path / 'state.json')
    app._hotkey_overrides = {
        str(k): (int(v[0]), int(v[1]))
        for k, v in (app._runtime_state.get('hotkeys.overrides', {}) or {}).items()
        if isinstance(v, (list, tuple)) and len(v) == 2
    }
    return app


def test_app_set_and_query_override(tmp_path: Path) -> None:
    app = _app(tmp_path)
    assert app.hotkey_overrides() == {}
    app.set_hotkey_override('fullscreen', sdl2.SDLK_j, 0)
    assert app.hotkey_overrides() == {'fullscreen': (sdl2.SDLK_j, 0)}


def test_app_override_persists_across_instances(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.set_hotkey_override('help', sdl2.SDLK_k, sdl2.KMOD_CTRL)
    app2 = _app(tmp_path)
    assert app2.hotkey_overrides() == {'help': (sdl2.SDLK_k, sdl2.KMOD_CTRL)}


def test_app_clear_override_with_none(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.set_hotkey_override('fullscreen', sdl2.SDLK_j, 0)
    app.set_hotkey_override('fullscreen', None)
    assert app.hotkey_overrides() == {}


# --------------------------------------------------------------------------- #
# End-to-end: a real HotkeyHandler.handle() respects a rebind, unmodified
# dispatch chain and all.
# --------------------------------------------------------------------------- #

class _Playlist:
    mode = 'sequential'
    index = 0
    effects: list = []
    shortcut_effects: list = []


class _Audio:
    def get_reactivity(self) -> float:
        return 1.0


class _Overlay:
    help_visible = False
    midi_selector_visible = False
    name_overlay_visible = False
    controller_help_modal_visible = False
    webcam_editor_modal_visible = False
    audio_selector_visible = False
    effects_browser_visible = False
    presets_visible = False
    projectm_manager_visible = False
    context_menu_open = False
    config_editor_open = False

    def flash_message(self, *_a, **_kw) -> None:
        return

    def flash_name(self, *_a, **_kw) -> None:
        return

    def note_help_activity(self) -> None:
        return


class _VJApi:
    def mark_user_action(self, _kind: str) -> None:
        return

    def key_handler_items(self):
        return []


class _RebindableApp:
    auto_vj_controller = None
    current_effect = None
    _keystroke_logger = None

    def __init__(self, overrides: dict) -> None:
        self._overrides = dict(overrides)
        self.fullscreen_toggled = 0
        self.vj_api = _VJApi()

    def hotkey_overrides(self) -> dict:
        return dict(self._overrides)

    def toggle_fullscreen(self) -> None:
        self.fullscreen_toggled += 1


def _real_handler(overrides: dict) -> tuple[HotkeyHandler, _RebindableApp]:
    app = _RebindableApp(overrides)
    handler = HotkeyHandler(app, _Playlist(), _Overlay(), _Audio())
    return handler, app


def test_rebound_key_triggers_action_end_to_end() -> None:
    handler, app = _real_handler({'fullscreen': (sdl2.SDLK_j, 0)})
    handler.handle(sdl2.SDLK_j, 0)  # the REBOUND key, not the default 'f'
    assert app.fullscreen_toggled == 1


def test_default_key_still_works_when_unrelated_override_set() -> None:
    handler, app = _real_handler({'help': (sdl2.SDLK_k, 0)})
    handler.handle(sdl2.SDLK_f, 0)  # fullscreen's default, no override on it
    assert app.fullscreen_toggled == 1


def test_no_overrides_default_key_still_works() -> None:
    handler, app = _real_handler({})
    handler.handle(sdl2.SDLK_f, 0)
    assert app.fullscreen_toggled == 1


def test_unbound_key_does_nothing_with_overrides_set() -> None:
    handler, app = _real_handler({'fullscreen': (sdl2.SDLK_j, 0)})
    handler.handle(99999, 0)  # not a real SDL keysym; matches no dispatch branch
    assert app.fullscreen_toggled == 0
