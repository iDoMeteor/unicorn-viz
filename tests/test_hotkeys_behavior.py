from __future__ import annotations

import sdl2

from unicornviz.hotkeys import HotkeyHandler
from unicornviz.midi import MidiEvent


class _VJApi:
    def __init__(self) -> None:
        self.marked: list[str] = []

    def mark_user_action(self, kind: str) -> None:
        self.marked.append(kind)

    def key_handler_items(self):
        return []

    def unregister_key_handler(self, _name: str) -> None:
        return

    def list_webcam_cameras(self):
        return []

    def webcam_image_state(self):
        return {
            'active': False,
            'path': '',
            'opacity': 1.0,
            'scale': 1.0,
            'x': 0.5,
            'y': 0.5,
        }


class _Overlay:
    help_visible = False
    midi_selector_visible = False
    name_overlay_visible = False
    controller_help_modal_visible = False
    webcam_editor_modal_visible = False

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.toggled_name = 0
        self.toggled_audio = 0
        self.audio_selector_visible = False
        self.audio_sources: list[str] = []
        self.audio_viable_flags: list[bool] = []
        self.audio_selected_index = 0

    def flash_message(self, text: str, _duration: float = 0.0) -> None:
        self.messages.append(text)

    def toggle_name_overlay(self) -> None:
        self.toggled_name += 1

    def flash_name(self, _name: str) -> None:
        return

    def note_help_activity(self) -> None:
        return

    def toggle_audio_selector(self) -> None:
        self.toggled_audio += 1
        self.audio_selector_visible = not self.audio_selector_visible

    def toggle_controller_help_modal(self) -> None:
        self.controller_help_modal_visible = not self.controller_help_modal_visible

    def toggle_webcam_editor_modal(self) -> None:
        self.webcam_editor_modal_visible = not self.webcam_editor_modal_visible

    def set_audio_sources(
        self,
        sources: list[str],
        current_index: int,
        viable_flags: list[bool] | None = None,
    ) -> None:
        self.audio_sources = list(sources)
        self.audio_selected_index = current_index
        if viable_flags is None:
            self.audio_viable_flags = [True] * len(self.audio_sources)
        else:
            self.audio_viable_flags = list(viable_flags)

    def move_audio_selection(self, delta: int) -> None:
        if not self.audio_sources:
            self.audio_selected_index = 0
            return
        self.audio_selected_index = (self.audio_selected_index + delta) % len(self.audio_sources)

    def get_audio_selected_index(self) -> int:
        return self.audio_selected_index

    def toggle_audio_selected_viable(self) -> bool:
        idx = self.get_audio_selected_index()
        self.audio_viable_flags[idx] = not self.audio_viable_flags[idx]
        return self.audio_viable_flags[idx]


class _Playlist:
    mode = 'sequential'
    index = 0
    effects = []
    shortcut_effects = []

    def advance(self):
        return type('_Effect', (), {'NAME': 'StubEffect'})

    def go_index(self, _index: int):
        return type('_Effect', (), {'NAME': 'StubEffect'})


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
        self.audio_source_viable_toggled: int | None = None

    def get_audio_sources(self) -> list[str]:
        return ['device-0', 'device-1']

    def get_audio_source_index(self) -> int:
        return 0

    def get_audio_source_viable_flags(self) -> list[bool]:
        return [True, True]

    def select_audio_source(self, index: int) -> str:
        self.audio_source_selected = index
        return f'Audio source: device-{index}'

    def toggle_audio_source_viable(self, index: int) -> str:
        self.audio_source_viable_toggled = index
        return f'Viable source toggled: device-{index}'

    def goto_effect(self, _cls) -> None:
        return


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


def test_ctrl_alt_k_marks_user_action_without_legacy_scaling_toggle() -> None:
    handler, app, overlays = _handler()

    handler.handle(sdl2.SDLK_k, sdl2.KMOD_CTRL | sdl2.KMOD_ALT)

    assert app.vj_api.marked == ['key']
    assert overlays.messages == []


def test_a_opens_audio_selector() -> None:
    handler, app, overlays = _handler()

    handler.handle(sdl2.SDLK_a, 0)

    assert app.vj_api.marked == ['key']
    assert overlays.toggled_audio == 1
    assert overlays.audio_selector_visible is True
    assert overlays.audio_sources == ['device-0', 'device-1']


def test_ctrl_shift_a_no_longer_opens_audio_selector() -> None:
    handler, app, overlays = _handler()

    handler.handle(sdl2.SDLK_a, sdl2.KMOD_CTRL | sdl2.KMOD_SHIFT)

    assert app.vj_api.marked == ['key']
    assert overlays.toggled_audio == 0


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


def test_audio_selector_t_toggles_viable_tag() -> None:
    handler, app, overlays = _handler()
    overlays.audio_selector_visible = True
    overlays.audio_sources = ['device-0', 'device-1']
    overlays.audio_viable_flags = [True, True]
    overlays.audio_selected_index = 1

    handler.handle(sdl2.SDLK_t, 0)

    assert app.vj_api.marked == ['key']
    assert app.audio_source_viable_toggled == 1
    assert overlays.audio_viable_flags == [True, False]
    assert 'Viable source toggled: device-1' in overlays.messages


def test_midi_note_is_queued_until_main_thread_dispatch() -> None:
    handler, app, overlays = _handler()
    app.midi_action_for_note = lambda _note: 'ansi'

    handler._on_midi(MidiEvent('note_on', 0, 60, 1.0))

    assert overlays.toggled_audio == 0
    assert app.vj_api.marked == []

    handler.process_pending_midi()

    assert overlays.toggled_audio == 1
    assert overlays.audio_selector_visible is True
    assert app.vj_api.marked == ['key']


def test_midi_named_action_audio_selector_dispatches() -> None:
    handler, app, overlays = _handler()
    app.midi_action_for_note = lambda _note: 'audio_selector'

    handler._on_midi(MidiEvent('note_on', 0, 61, 1.0))
    handler.process_pending_midi()

    assert overlays.toggled_audio == 1
    assert overlays.audio_selector_visible is True
    assert app.vj_api.marked == ['key']


def test_midi_contextual_nav_action_dispatches() -> None:
    handler, app, overlays = _handler()
    app.midi_action_for_note = lambda _note: 'context_select'
    overlays.audio_selector_visible = True
    overlays.audio_sources = ['device-0', 'device-1']
    overlays.audio_selected_index = 1

    handler._on_midi(MidiEvent('note_on', 0, 62, 1.0))
    handler.process_pending_midi()

    assert app.audio_source_selected == 1
    assert overlays.audio_selector_visible is False


def test_midi_unmapped_named_action_noop() -> None:
    handler, app, overlays = _handler()
    app.midi_action_for_note = lambda _note: 'this_action_does_not_exist'

    handler._on_midi(MidiEvent('note_on', 0, 63, 1.0))
    handler.process_pending_midi()

    assert overlays.toggled_audio == 0
    assert app.vj_api.marked == []


def test_midi_context_slot_uses_performance_context_by_default() -> None:
    handler, app, overlays = _handler()
    app.midi_action_for_note = lambda _note: 'context_slot_1'

    handler._on_midi(MidiEvent('note_on', 0, 64, 1.0))
    handler.process_pending_midi()

    # performance slot 1 -> next effect key path
    assert app.vj_api.marked == ['key']
    assert overlays.toggled_audio == 0


def test_midi_context_slot_switches_in_audio_selector_context() -> None:
    handler, app, overlays = _handler()
    app.midi_action_for_note = lambda _note: 'context_slot_1'
    overlays.audio_selector_visible = True
    overlays.audio_sources = ['device-0', 'device-1']
    overlays.audio_selected_index = 1

    handler._on_midi(MidiEvent('note_on', 0, 65, 1.0))
    handler.process_pending_midi()

    # audio-selector slot 1 -> move selection up
    assert overlays.audio_selected_index == 0


def test_midi_context_slot_can_toggle_audio_viable_in_selector_context() -> None:
    handler, app, overlays = _handler()
    app.midi_action_for_note = lambda _note: 'context_slot_6'
    overlays.audio_selector_visible = True
    overlays.audio_sources = ['device-0', 'device-1']
    overlays.audio_viable_flags = [True, True]
    overlays.audio_selected_index = 1

    handler._on_midi(MidiEvent('note_on', 0, 66, 1.0))
    handler.process_pending_midi()

    assert app.audio_source_viable_toggled == 1
    assert overlays.audio_viable_flags == [True, False]


def test_ctrl_alt_h_toggles_controller_help_modal() -> None:
    handler, _app, overlays = _handler()

    handler.handle(sdl2.SDLK_h, sdl2.KMOD_CTRL | sdl2.KMOD_ALT)
    assert overlays.controller_help_modal_visible is True

    handler.handle(sdl2.SDLK_h, sdl2.KMOD_CTRL | sdl2.KMOD_ALT)
    assert overlays.controller_help_modal_visible is False


def test_midi_controller_help_action_toggles_modal() -> None:
    handler, app, overlays = _handler()
    app.midi_action_for_note = lambda _note: 'controller_help'

    handler._on_midi(MidiEvent('note_on', 0, 77, 1.0))
    handler.process_pending_midi()

    assert overlays.controller_help_modal_visible is True
