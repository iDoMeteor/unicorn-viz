from __future__ import annotations

import sdl2

from unicornviz.hotkeys import HotkeyHandler


class _VJApi:
    def __init__(self) -> None:
        self.marked: list[str] = []

    def mark_user_action(self, kind: str) -> None:
        self.marked.append(kind)

    def key_handler_items(self):
        return []

    def unregister_key_handler(self, _name: str) -> None:
        return


class _Overlay:
    help_visible = False
    midi_selector_visible = False
    name_overlay_visible = False

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.toggled_name = 0
        self.toggled_audio = 0
        self.audio_selector_visible = False
        self.audio_sources: list[str] = []
        self.audio_selected_index = 0

    def flash_message(self, text: str, _duration: float = 0.0) -> None:
        self.messages.append(text)

    def toggle_name_overlay(self) -> None:
        self.toggled_name += 1

    def note_help_activity(self) -> None:
        return

    def toggle_audio_selector(self) -> None:
        self.toggled_audio += 1
        self.audio_selector_visible = not self.audio_selector_visible

    def set_audio_sources(self, sources: list[str], current_index: int) -> None:
        self.audio_sources = list(sources)
        self.audio_selected_index = current_index

    def move_audio_selection(self, delta: int) -> None:
        if not self.audio_sources:
            self.audio_selected_index = 0
            return
        self.audio_selected_index = (self.audio_selected_index + delta) % len(self.audio_sources)

    def get_audio_selected_index(self) -> int:
        return self.audio_selected_index


class _Playlist:
    mode = 'sequential'
    index = 0
    effects = []
    shortcut_effects = []


class _Audio:
    def list_profiles(self):
        return ['house']

    def get_profile_key(self) -> str:
        return 'house'

    def get_profile(self):
        class _Profile:
            name = 'house'

        return _Profile()

    def set_profile(self, _name: str):
        return self.get_profile()

    def set_reactivity(self, value: float) -> float:
        return value

    def get_reactivity(self) -> float:
        return 1.0

    def reset_reactivity(self) -> float:
        return 1.0


class _App:
    def __init__(self) -> None:
        self.vj_api = _VJApi()
        self.auto_vj_controller = None
        self.current_effect = None
        self.current_effect_name = '-'
        self._keystroke_logger = None
        self.audio_source_selected: int | None = None

    def toggle_current_effect_frame_scaling(self) -> str:
        return 'frame scaling toggled'

    def get_audio_sources(self) -> list[str]:
        return ['device-0', 'device-1']

    def get_audio_source_index(self) -> int:
        return 0

    def select_audio_source(self, index: int) -> str:
        self.audio_source_selected = index
        return f'Audio source: device-{index}'


def _handler() -> tuple[HotkeyHandler, _App, _Overlay]:
    app = _App()
    overlays = _Overlay()
    handler = HotkeyHandler(app, _Playlist(), overlays, _Audio())
    return handler, app, overlays


def test_tab_is_passive_and_does_not_mark_user_action() -> None:
    handler, app, overlays = _handler()

    handler.handle(sdl2.SDLK_TAB, 0)

    assert app.vj_api.marked == []
    assert overlays.toggled_name == 1


def test_system_combo_alt_tab_does_not_mark_user_action() -> None:
    handler, app, _overlays = _handler()

    handler.handle(sdl2.SDLK_TAB, sdl2.KMOD_ALT)

    assert app.vj_api.marked == []


def test_ctrl_alt_k_marks_user_action_and_dispatches_chord() -> None:
    handler, app, overlays = _handler()

    handler.handle(sdl2.SDLK_k, sdl2.KMOD_CTRL | sdl2.KMOD_ALT)

    assert app.vj_api.marked == ['key']
    assert 'frame scaling toggled' in overlays.messages


def test_a_opens_audio_selector() -> None:
    handler, app, overlays = _handler()

    handler.handle(sdl2.SDLK_a, 0)

    assert app.vj_api.marked == ['key']
    assert overlays.toggled_audio == 1
    assert overlays.audio_selector_visible is True
    assert overlays.audio_sources == ['device-0', 'device-1']


def test_ctrl_shift_a_still_opens_audio_selector() -> None:
    handler, app, overlays = _handler()

    handler.handle(sdl2.SDLK_a, sdl2.KMOD_CTRL | sdl2.KMOD_SHIFT)

    assert app.vj_api.marked == ['key']
    assert overlays.toggled_audio == 1


def test_shift_a_opens_audio_selector() -> None:
    handler, app, overlays = _handler()

    handler.handle(sdl2.SDLK_a, sdl2.KMOD_SHIFT)

    assert app.vj_api.marked == ['key']
    assert overlays.toggled_audio == 1
    assert overlays.audio_selector_visible is True


def test_audio_selector_enter_applies_selected_source() -> None:
    handler, app, overlays = _handler()
    overlays.audio_selector_visible = True
    overlays.audio_sources = ['device-0', 'device-1']
    overlays.audio_selected_index = 1

    handler.handle(sdl2.SDLK_RETURN, 0)

    assert app.vj_api.marked == ['key']
    assert app.audio_source_selected == 1
    assert overlays.audio_selector_visible is False
    assert 'Audio source: device-1' in overlays.messages
