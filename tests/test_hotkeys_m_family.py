"""Tests: m-family hotkey dispatch (m, Shift+M, Alt+M, Ctrl+M).

Validates that each m-family key combination routes to exactly the right
overlay/app action and does not silently no-op or misroute.  Mutual-
exclusion between overlays is not currently enforced by the hotkey layer
(it is delegated to each modal's own open/close logic), but dispatch
correctness is a hard contract.
"""
from __future__ import annotations

import sdl2

from unicornviz.hotkeys import HotkeyHandler


# ---------------------------------------------------------------------------
# Minimal stubs
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
    system_monitor_modal_visible = False
    help_visible = False
    name_overlay_visible = False
    controller_help_modal_visible = False
    webcam_editor_modal_visible = False
    projectm_manager_visible = False
    audio_selector_visible = False

    def __init__(self) -> None:
        self.calls: list[str] = []

    def flash_message(self, *_a, **_kw) -> None:
        pass

    def flash_name(self, *_a) -> None:
        pass

    def note_help_activity(self) -> None:
        pass

    def toggle_system_monitor_modal(self) -> None:
        self.calls.append('toggle_system_monitor_modal')
        self.system_monitor_modal_visible = not self.system_monitor_modal_visible

    def toggle_midi_selector(self) -> None:
        self.calls.append('toggle_midi_selector')
        self.midi_selector_visible = not self.midi_selector_visible

    def set_midi_ports(self, _ports: list, _current: str) -> None:
        pass

    # The following are required by HotkeyHandler but not under test here.
    def toggle_name_overlay(self) -> None:
        pass

    def move_audio_selection(self, _d: int) -> None:
        pass

    def get_audio_selected_index(self) -> int:
        return 0

    def toggle_audio_selected_viable(self) -> bool:
        return True

    def toggle_audio_selector(self) -> None:
        pass

    def set_audio_sources(self, *_a, **_kw) -> None:
        pass


class _App:
    def __init__(self) -> None:
        self.vj_api = _VJApi()
        self.auto_vj_controller = None
        self.current_effect = None
        self.current_effect_name = '-'
        self._keystroke_logger = None
        self.speed_randomized = False
        self.reactivity_randomized = False
        self._midi_manager = None
        self._control_room_toggled: list[bool] = []

    def toggle_control_room(self) -> tuple[bool, str]:
        active = not bool(self._control_room_toggled and self._control_room_toggled[-1])
        self._control_room_toggled.append(active)
        return active, 'Control Room ON' if active else 'Control Room OFF'

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

    def random_range_for(self, _key: str, _lo: float, _hi: float) -> tuple[float, float]:
        return _lo, _hi

    @property
    def reactivity_randomized(self) -> bool:
        return self._react_rand

    @reactivity_randomized.setter
    def reactivity_randomized(self, v: bool) -> None:
        self._react_rand = v

    def set_reactivity_randomized(self, v: bool) -> None:
        self._react_rand = v


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
    app._speed_rand = False
    app._react_rand = False
    overlay = _Overlay()
    handler = HotkeyHandler(app, _Playlist(), overlay, _Audio())
    return handler, app, overlay


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_plain_m_opens_system_monitor() -> None:
    handler, _app, overlay = _setup()
    handler.handle(sdl2.SDLK_m, 0)
    assert 'toggle_system_monitor_modal' in overlay.calls
    assert overlay.system_monitor_modal_visible


def test_shift_m_toggles_control_room() -> None:
    handler, app, _overlay = _setup()
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_SHIFT)
    assert len(app._control_room_toggled) == 1
    assert app._control_room_toggled[0] is True


def test_alt_m_opens_midi_selector() -> None:
    handler, _app, overlay = _setup()
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_ALT)
    assert 'toggle_midi_selector' in overlay.calls
    assert overlay.midi_selector_visible


def test_plain_m_does_not_toggle_control_room() -> None:
    handler, app, _overlay = _setup()
    handler.handle(sdl2.SDLK_m, 0)
    assert app._control_room_toggled == []


def test_shift_m_does_not_open_system_monitor() -> None:
    handler, _app, overlay = _setup()
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_SHIFT)
    assert 'toggle_system_monitor_modal' not in overlay.calls
    assert not overlay.system_monitor_modal_visible


def test_alt_m_does_not_open_system_monitor() -> None:
    handler, _app, overlay = _setup()
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_ALT)
    assert 'toggle_system_monitor_modal' not in overlay.calls
