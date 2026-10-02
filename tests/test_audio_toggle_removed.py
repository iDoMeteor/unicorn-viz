"""The ``audio_toggle`` action is gone (owner decision 2026-10-02).

It came from the 2026-06-03 MIDI scaffolding and was identical to ``eq`` (both
replayed the E key).  Core no longer defines it.  Anything saved that still
names it (a ``[midi.note_map]`` in config.toml, a user-taught MIDI Learn
binding, a drop-in profile, a persisted hotkey override) is mapped to ``eq``
with a one-time log line and never raises.
"""
from __future__ import annotations

import logging

import pytest

from unicornviz import midi as midi_mod
from unicornviz.app import App
from unicornviz.hotkeys import action_names, default_action_binding
from unicornviz.midi import MidiManager, canonical_action


@pytest.fixture(autouse=True)
def _fresh_alias_log(monkeypatch):
    monkeypatch.setattr(midi_mod, '_ALIAS_LOGGED', set())


def test_the_action_no_longer_exists_in_core() -> None:
    assert 'audio_toggle' not in action_names()
    assert default_action_binding('audio_toggle') is None
    assert 'audio_toggle' not in App._HOTKEY_ACTION_LABELS
    assert 'audio_toggle' not in midi_mod._NOTE_MAP_DEFAULT.values()
    assert 'eq' in action_names()


def test_the_generic_default_note_that_was_audio_toggle_is_not_dead() -> None:
    assert midi_mod._NOTE_MAP_DEFAULT[64] == 'eq'


def test_canonical_action_maps_the_legacy_name_and_logs_once(caplog) -> None:
    with caplog.at_level(logging.INFO, logger='unicornviz.midi'):
        assert canonical_action('audio_toggle') == 'eq'
        assert canonical_action('audio_toggle') == 'eq'
        assert canonical_action('next') == 'next'
    lines = [r for r in caplog.records if 'audio_toggle' in r.getMessage()]
    assert len(lines) == 1 and 'eq' in lines[0].getMessage()


def test_a_config_note_map_naming_it_is_mapped_without_error(caplog) -> None:
    with caplog.at_level(logging.INFO, logger='unicornviz.midi'):
        m = MidiManager(device_hint='', note_map_override={70: 'audio_toggle', 71: 'next'})
    assert m.note_to_action(70) == 'eq' and m.note_to_action(71) == 'next'
    assert 'audio_toggle' not in m.note_map.values()
    assert any('audio_toggle' in r.getMessage() for r in caplog.records)


def test_midi_learn_assignment_of_the_legacy_name_is_mapped() -> None:
    m = MidiManager(device_hint='')
    m.set_note_binding(72, 'audio_toggle')
    assert m.note_to_action(72) == 'eq'


def test_a_preset_that_still_names_it_is_mapped(monkeypatch) -> None:
    monkeypatch.setitem(midi_mod.BUILTIN_PRESETS, 'legacy_test',
                        {'note_map': {10: 'audio_toggle', 11: 'pause'}, 'cc_map': {}})
    cc, note = MidiManager._build_maps('legacy_test', None, None)
    assert note[10] == 'eq' and note[11] == 'pause'


def _app_with_state(state: dict) -> App:
    app = App.__new__(App)
    app._runtime_state = type('S', (), {
        'get': lambda self, k, d=None: state.get(k, d),
        'set': lambda self, k, v: state.__setitem__(k, v),
        'save': lambda self: None})()
    return app


def test_a_persisted_hotkey_override_for_it_moves_to_eq(caplog) -> None:
    state = {'hotkeys.overrides': {'audio_toggle': [106, 0], 'next': [107, 0]}}
    app = _app_with_state(state)
    with caplog.at_level(logging.INFO):
        overrides = app._load_hotkey_overrides()
    assert overrides == {'eq': (106, 0), 'next': (107, 0)}
    assert 'audio_toggle' not in state['hotkeys.overrides']       # rewritten, so the log is one-time
    assert state['hotkeys.overrides']['eq'] == [106, 0]


def test_an_existing_eq_override_wins_over_the_legacy_one() -> None:
    state = {'hotkeys.overrides': {'audio_toggle': [106, 0], 'eq': [108, 0]}}
    overrides = _app_with_state(state)._load_hotkey_overrides()
    assert overrides == {'eq': (108, 0)}
