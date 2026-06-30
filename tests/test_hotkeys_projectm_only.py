"""Tests: Ctrl+L routes to the ProjectM-only toggle, and the effect-lock
redirect turns a blocked switch into a locked-effect variation (preset advance).
"""
from __future__ import annotations

import sdl2

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
    projectm_manager_visible = False
    audio_selector_visible = False

    def __init__(self) -> None:
        self.messages: list[str] = []

    def flash_message(self, msg, *_a, **_kw) -> None:
        self.messages.append(str(msg))

    def flash_name(self, *_a) -> None:
        pass

    def note_help_activity(self) -> None:
        pass


class _App:
    def __init__(self) -> None:
        self.vj_api = _VJApi()
        self.auto_vj_controller = None
        self.current_effect = None
        self.current_effect_name = '-'
        self._keystroke_logger = None
        self._midi_manager = None
        self.toggle_calls = 0

    def toggle_projectm_only(self) -> tuple[bool, str]:
        self.toggle_calls += 1
        on = self.toggle_calls % 2 == 1
        return on, 'ProjectM-only ON' if on else 'ProjectM-only OFF'


class _Playlist:
    mode = 'sequential'
    index = 0
    effects: list = []
    shortcut_effects: list = []

    def advance(self):
        return type('E', (), {'NAME': 'Stub'})


def test_ctrl_l_toggles_projectm_only() -> None:
    app = _App()
    handler = HotkeyHandler(app, _Playlist(), _Overlay(), None)
    handler.handle(sdl2.SDLK_l, sdl2.KMOD_CTRL)
    assert app.toggle_calls == 1


def test_plain_l_does_not_toggle() -> None:
    app = _App()
    handler = HotkeyHandler(app, _Playlist(), _Overlay(), None)
    handler.handle(sdl2.SDLK_l, 0)
    assert app.toggle_calls == 0


# ----- effect-lock redirect logic (extracted, GL-free) ----------------------

class _Effect:
    NAME = 'ProjectM Presets'

    def __init__(self) -> None:
        self.presets_advanced = 0

    def next_preset(self) -> None:
        self.presets_advanced += 1


def _redirect(lock: str | None, target_name: str, current) -> bool:
    """Mirror App._switch_effect's lock guard: returns True if the switch was
    redirected/blocked (i.e. NOT performed)."""
    if lock is not None and target_name != lock:
        vary = getattr(current, 'next_preset', None)
        if callable(vary):
            vary()
        return True
    return False


def test_locked_switch_redirects_to_preset_advance() -> None:
    eff = _Effect()
    # Auto VJ asks to switch to some other effect while locked to ProjectM.
    redirected = _redirect('ProjectM Presets', 'Plasma', eff)
    assert redirected is True
    assert eff.presets_advanced == 1


def test_switch_to_locked_effect_is_allowed() -> None:
    eff = _Effect()
    redirected = _redirect('ProjectM Presets', 'ProjectM Presets', eff)
    assert redirected is False
    assert eff.presets_advanced == 0


def test_no_lock_allows_switch() -> None:
    eff = _Effect()
    assert _redirect(None, 'Plasma', eff) is False
