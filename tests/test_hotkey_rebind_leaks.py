"""B P2-7 (audit 2026-09-30): rebinds leaked the old key and missed conflicts.

A rebind only mapped the *new* chord onto the action's default chord before the
unchanged dispatch chain ran, so the default chord still matched: after moving
``disable_and_advance`` off Delete, Delete still disabled the current effect.
And conflict detection only looked at the ~30 named actions, so binding an
action to a chord ``handle()`` or a drop-in already uses (V, recording) passed
silently and shadowed it.  Now an overridden action's old default chord is
swallowed unless another action is bound to it, and conflicts are checked
against the named actions plus every chord documented in the help (core and
drop-in HELP_ENTRIES).
"""
from __future__ import annotations

import sdl2

import unicornviz.hotkeys as hotkeys_mod
from unicornviz.app import App
from unicornviz.hotkeys import (
    UNBOUND_CHORD,
    HotkeyHandler,
    parse_help_chords,
    reserved_chords,
    translate_override_chord,
)

F = (sdl2.SDLK_f, 0)
J = (sdl2.SDLK_j, 0)


# ---------------------------------------------------------------- translate

def test_a_rebound_actions_old_default_chord_is_freed() -> None:
    overrides = {'fullscreen': J}
    assert translate_override_chord(*J, overrides) == F          # the new chord works
    assert translate_override_chord(*F, overrides) == UNBOUND_CHORD   # the old one is dead


def test_the_old_chord_stays_when_another_action_is_still_bound_to_it(monkeypatch) -> None:
    # Two actions sharing a default chord: moving one must not kill the other.
    e = (sdl2.SDLK_e, 0)
    monkeypatch.setitem(hotkeys_mod._MIDI_NOTE_KEY_BINDINGS, 'twin_of_eq', e)
    overrides = {'twin_of_eq': J}
    assert translate_override_chord(*e, overrides) == e


def test_the_old_chord_goes_to_the_action_it_was_rebound_to() -> None:
    overrides = {'fullscreen': J, 'help': F}                        # help took fullscreen's old key
    assert translate_override_chord(*F, overrides) == (sdl2.SDLK_h, 0)


def test_an_override_equal_to_the_default_frees_nothing() -> None:
    overrides = {'fullscreen': F}
    assert translate_override_chord(*F, overrides) == F


def test_unrelated_chords_and_empty_overrides_pass_through() -> None:
    assert translate_override_chord(sdl2.SDLK_q, 0, {'fullscreen': J}) == (sdl2.SDLK_q, 0)
    assert translate_override_chord(*F, {}) == F


def test_modifiers_are_part_of_the_chord() -> None:
    ctrl_f = (sdl2.SDLK_f, sdl2.KMOD_CTRL)
    overrides = {'fullscreen': J}
    assert translate_override_chord(*ctrl_f, overrides) == ctrl_f   # a different chord is untouched


# ------------------------------------------------------------ end to end

class _Playlist:
    mode = 'sequential'
    index = 0
    effects: list = []
    shortcut_effects: list = []


class _Audio:
    def get_reactivity(self) -> float:
        return 1.0


class _Overlay:
    help_visible = midi_selector_visible = name_overlay_visible = False
    controller_help_modal_visible = webcam_editor_modal_visible = False
    audio_selector_visible = effects_browser_visible = presets_visible = False
    projectm_manager_visible = context_menu_open = config_editor_open = False

    def flash_message(self, *_a, **_k) -> None:
        pass

    def flash_name(self, *_a, **_k) -> None:
        pass

    def note_help_activity(self) -> None:
        pass


class _VJApi:
    def mark_user_action(self, _k: str) -> None:
        pass

    def key_handler_items(self):
        return []


class _App:
    auto_vj_controller = None
    current_effect = None
    _keystroke_logger = None

    def __init__(self, overrides: dict) -> None:
        self._o = dict(overrides)
        self.fullscreen_toggled = 0
        self.vj_api = _VJApi()

    def hotkey_overrides(self) -> dict:
        return dict(self._o)

    def toggle_fullscreen(self) -> None:
        self.fullscreen_toggled += 1


def test_the_old_key_really_stops_working_end_to_end() -> None:
    app = _App({'fullscreen': J})
    h = HotkeyHandler(app, _Playlist(), _Overlay(), _Audio())
    h.handle(sdl2.SDLK_f, 0)                                        # the old default
    assert app.fullscreen_toggled == 0
    h.handle(sdl2.SDLK_j, 0)                                        # the new binding
    assert app.fullscreen_toggled == 1


# ----------------------------------------------------- conflict detection

def test_help_labels_parse_into_chords() -> None:
    assert (sdl2.SDLK_v, 0) in parse_help_chords('v')
    assert (sdl2.SDLK_v, 0) in parse_help_chords('V')
    assert (sdl2.SDLK_f, sdl2.KMOD_CTRL | sdl2.KMOD_ALT) in parse_help_chords('Ctrl+Alt+F')
    assert (sdl2.SDLK_h, 0) in parse_help_chords('H / ?') and (sdl2.SDLK_h, 0) in parse_help_chords('H')
    assert (sdl2.SDLK_n, 0) in parse_help_chords('n / Right') and (sdl2.SDLK_RIGHT, 0) in parse_help_chords('n / Right')
    assert (sdl2.SDLK_F6, 0) in parse_help_chords('F6')
    assert (sdl2.SDLK_ESCAPE, 0) in parse_help_chords('ESC')
    assert (sdl2.SDLK_MINUS, sdl2.KMOD_SHIFT) in parse_help_chords('Shift+-')
    assert (sdl2.SDLK_DELETE, sdl2.KMOD_SHIFT) in parse_help_chords('Shift+Delete')


def test_descriptive_labels_are_not_chords() -> None:
    for label in ('Right Click', 'Number', 'Shift+Number', 'Arrow keys', '0 - 9', 'Mouse wheel', ''):
        assert parse_help_chords(label) == set(), label


def test_the_reserved_set_covers_documented_core_keys() -> None:
    reserved = reserved_chords()
    assert (sdl2.SDLK_f, 0) in reserved and (sdl2.SDLK_ESCAPE, 0) in reserved
    assert all(isinstance(desc, str) and desc for desc in reserved.values())


def _app(overrides=None) -> App:
    app = App.__new__(App)
    app._hotkey_overrides = dict(overrides or {})
    return app


def test_binding_an_action_to_a_documented_key_is_a_conflict() -> None:
    app = _app()
    # 'V' is not one of the ~30 named actions; the help documents it (recording).
    conflict = app.hotkey_conflict_for_chord(sdl2.SDLK_v, 0, exclude_action='next')
    assert conflict is not None and conflict != ''


def test_named_action_conflicts_are_still_reported_by_their_label() -> None:
    app = _app()
    assert app.hotkey_conflict_for_chord(sdl2.SDLK_f, 0, exclude_action='next') == 'Toggle Fullscreen'


def test_an_actions_own_default_is_not_a_conflict() -> None:
    assert _app().hotkey_conflict_for_chord(sdl2.SDLK_f, 0, exclude_action='fullscreen') is None


def test_a_freed_default_can_be_taken_by_another_action() -> None:
    app = _app({'fullscreen': J})
    # F is documented ("Fullscreen") but fullscreen no longer lives there.
    assert app.hotkey_conflict_for_chord(sdl2.SDLK_f, 0, exclude_action='next') is None


def test_a_free_unused_key_is_not_a_conflict() -> None:
    reserved = reserved_chords()
    free = next((s for s in (sdl2.SDLK_F12, sdl2.SDLK_BACKQUOTE, sdl2.SDLK_INSERT)
                 if (s, sdl2.KMOD_CTRL | sdl2.KMOD_ALT | sdl2.KMOD_SHIFT) not in reserved), None)
    assert free is not None
    assert _app().hotkey_conflict_for_chord(free, sdl2.KMOD_CTRL | sdl2.KMOD_ALT | sdl2.KMOD_SHIFT,
                                            exclude_action='next') is None
