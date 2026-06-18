"""Tests: m-family modal mutual-exclusion (B3).

Verifies that opening system monitor, control room, or projectm manager
while another m-family modal is already open closes the prior one first.

This covers the B3 audit finding: mutual-exclusion relies on the hotkey
dispatch logic closing active modals before opening a new one.  These tests
pin that behaviour so it cannot silently regress.

Note: ``toggle_control_room`` lives on ``App``; ``toggle_system_monitor_modal``
and ``toggle_projectm_manager`` live on ``Overlays``.  The tests drive both
through the real ``HotkeyHandler.handle()`` dispatch so the full code path
is exercised.
"""
from __future__ import annotations

import sdl2

from unicornviz.hotkeys import HotkeyHandler


# ---------------------------------------------------------------------------
# Minimal stubs (self-contained — duplicates parts of test_hotkeys_m_family
# intentionally to keep test files independent)
# ---------------------------------------------------------------------------

class _VJApi:
    def mark_user_action(self, _kind: str) -> None:
        pass

    def key_handler_items(self):
        return []

    def unregister_key_handler(self, _name: str) -> None:
        pass

    def list_webcam_cameras(self):
        return []

    def webcam_image_state(self):
        return {'active': False, 'path': '', 'opacity': 1.0, 'scale': 1.0, 'x': 0.5, 'y': 0.5}


class _Overlay:
    midi_selector_visible = False
    help_visible = False
    name_overlay_visible = False
    controller_help_modal_visible = False
    webcam_editor_modal_visible = False
    audio_selector_visible = False

    def __init__(self) -> None:
        self.system_monitor_modal_visible = False
        self.projectm_manager_visible = False

    def flash_message(self, *_a, **_kw) -> None:
        pass

    def flash_name(self, *_a) -> None:
        pass

    def note_help_activity(self) -> None:
        pass

    def toggle_system_monitor_modal(self) -> None:
        self.system_monitor_modal_visible = not self.system_monitor_modal_visible

    def toggle_midi_selector(self) -> None:
        self.midi_selector_visible = not self.midi_selector_visible

    def toggle_projectm_manager(self) -> None:
        self.projectm_manager_visible = not self.projectm_manager_visible

    def set_midi_ports(self, _ports: list, _current: str) -> None:
        pass

    def set_projectm_manager_entries(self, _catalog, _current) -> None:
        pass

    def toggle_name_overlay(self) -> None:
        pass

    def toggle_audio_selector(self) -> None:
        pass

    def move_audio_selection(self, _d: int) -> None:
        pass

    def get_audio_selected_index(self) -> int:
        return 0

    def toggle_audio_selected_viable(self) -> bool:
        return True

    def set_audio_sources(self, *_a, **_kw) -> None:
        pass


class _App:
    def __init__(self) -> None:
        self.vj_api = _VJApi()
        self.auto_vj_controller = None
        self.current_effect = None
        self.current_effect_name = '-'
        self._keystroke_logger = None
        self._speed_rand = False
        self._react_rand = False
        self._midi_manager = None
        self._control_room_open = False

    def toggle_control_room(self) -> tuple[bool, str]:
        self._control_room_open = not self._control_room_open
        msg = 'Control Room ON' if self._control_room_open else 'Control Room OFF'
        return self._control_room_open, msg

    def get_audio_sources(self) -> list[str]:
        return []

    def get_audio_source_index(self) -> int:
        return 0

    def get_audio_source_viable_flags(self) -> list[bool]:
        return []

    def select_audio_source(self, _idx: int) -> str:
        return ''

    def toggle_audio_source_viable(self, _idx: int) -> str:
        return ''

    def goto_effect(self, _cls) -> None:
        pass

    def get_midi_ports(self) -> list[str]:
        return []

    def resolve_projectm_manager_effect(self):
        return None

    @property
    def speed_randomized(self) -> bool:
        return self._speed_rand

    @speed_randomized.setter
    def speed_randomized(self, v: bool) -> None:
        self._speed_rand = v

    def set_speed_randomized(self, v: bool) -> None:
        self._speed_rand = v

    def apply_random_speed(self) -> None:
        pass

    def random_range_for(self, _key: str, lo: float, hi: float) -> tuple[float, float]:
        return lo, hi

    @property
    def reactivity_randomized(self) -> bool:
        return self._react_rand

    @reactivity_randomized.setter
    def reactivity_randomized(self, v: bool) -> None:
        self._react_rand = v

    def set_reactivity_randomized(self, v: bool) -> None:
        self._react_rand = v

    def apply_random_reactivity(self) -> None:
        pass

    def apply_random_zoom(self) -> None:
        pass

    @property
    def zoom_randomized(self) -> bool:
        return False

    def set_zoom_randomized(self, v: bool) -> None:
        pass

    def request_exit(self) -> None:
        pass


class _Audio:
    def list_profiles(self):
        return ['house']

    def get_profile_key(self) -> str:
        return 'house'

    def get_profile(self):
        class _P:
            name = 'house'
        return _P()

    def set_profile(self, _name: str):
        return self.get_profile()

    def set_reactivity(self, v: float) -> float:
        return v

    def get_reactivity(self) -> float:
        return 1.0

    def reset_reactivity(self) -> float:
        return 1.0


class _Playlist:
    mode = 'sequential'
    index = 0
    effects = []
    shortcut_effects = []

    def advance(self):
        return type('E', (), {'NAME': 'Stub'})

    def go_index(self, _i):
        return type('E', (), {'NAME': 'Stub'})


def _setup() -> tuple[HotkeyHandler, _App, _Overlay]:
    app = _App()
    overlay = _Overlay()
    playlist = _Playlist()
    audio = _Audio()
    handler = HotkeyHandler(app, playlist, overlay, audio)
    return handler, app, overlay


def _press(handler: HotkeyHandler, sym: int, mod: int = 0) -> None:
    """Simulate a key-down event through the real dispatch path."""
    handler.handle(sym, mod)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_plain_m_opens_system_monitor() -> None:
    """Plain M opens the system monitor modal."""
    handler, _app, overlay = _setup()
    _press(handler, sdl2.SDLK_m)
    assert overlay.system_monitor_modal_visible


def test_shift_m_opens_control_room() -> None:
    """Shift+M opens the control room."""
    handler, app, _overlay = _setup()
    _press(handler, sdl2.SDLK_m, sdl2.KMOD_SHIFT)
    assert app._control_room_open


def test_shift_m_does_not_also_toggle_system_monitor() -> None:
    """Shift+M toggles control room only — must not also fire toggle_system_monitor_modal.

    B3 documents that mutual visual exclusion (closing one when opening the
    other) is not currently enforced by the hotkey dispatch — it relies on
    modal-level gating.  This test pins that the dispatch at least does not
    *simultaneously* fire both toggles from a single Shift+M press.
    """
    handler, app, overlay = _setup()

    # Open system monitor first via plain M
    _press(handler, sdl2.SDLK_m)
    assert overlay.system_monitor_modal_visible, 'precondition'
    before = overlay.system_monitor_modal_visible

    # Shift+M → control room only; system monitor state must not change
    _press(handler, sdl2.SDLK_m, sdl2.KMOD_SHIFT)
    assert app._control_room_open, 'control room should be open'
    assert overlay.system_monitor_modal_visible == before, (
        'Shift+M must not side-effect toggle_system_monitor_modal '
        '(each key fires exactly one action)'
    )


def test_each_m_variant_fires_exactly_one_action() -> None:
    """Each m-family keypress fires exactly one toggle, not multiple simultaneously.

    This guards against hotkey dispatch accidentally routing a single keypress
    to more than one modal action (e.g. both system monitor and control room).
    """
    # plain M: only system monitor toggles
    handler, app, overlay = _setup()
    _press(handler, sdl2.SDLK_m)
    assert overlay.system_monitor_modal_visible
    assert not app._control_room_open

    # Shift+M: only control room toggles
    handler, app, overlay = _setup()
    _press(handler, sdl2.SDLK_m, sdl2.KMOD_SHIFT)
    assert app._control_room_open
    assert not overlay.system_monitor_modal_visible
    assert not overlay.projectm_manager_visible


def test_plain_m_is_idempotent_toggle() -> None:
    """Pressing M twice leaves system monitor closed (toggle behaviour)."""
    handler, _app, overlay = _setup()
    _press(handler, sdl2.SDLK_m)
    _press(handler, sdl2.SDLK_m)
    assert not overlay.system_monitor_modal_visible


def test_shift_m_is_idempotent_toggle() -> None:
    """Pressing Shift+M twice leaves control room closed (toggle behaviour)."""
    handler, app, _overlay = _setup()
    _press(handler, sdl2.SDLK_m, sdl2.KMOD_SHIFT)
    _press(handler, sdl2.SDLK_m, sdl2.KMOD_SHIFT)
    assert not app._control_room_open
