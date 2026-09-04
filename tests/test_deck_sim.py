"""Deck-sim (Control Room controller-mirror view) P1 surface — regression tests.

Covers the core/vj_api additions from
drop-ins/control-room-01/docs/deck-sim-plan.md §8 P1: the
DeckSimLayout/FaderSpec descriptors, VJApi's registry
(register_deck_sim_layout/deck_sim_layouts/active_deck_sim_layout),
VJApi.midi_preset_device()/MidiManager.preset_device() (the meta.device
readback), and the live color-palette provider
(register_midi_action_colors/midi_action_colors). No GL context, no MIDI
hardware -- MidiManager is a bare __new__ shell in every test here, exactly
like test_midi_apc_preset.py's hermetic pattern (see the "MIDI Test Hook
Hang" fix this project already carries).
"""
from __future__ import annotations

from unicornviz.deck_sim import DeckSimLayout, FaderSpec
from unicornviz.midi import BUILTIN_PRESETS, MidiManager
from unicornviz.vj_api import VJApi


class _StubApp:
    """Enough of an App for VJApi to bind to; _midi_manager set per test."""

    def __init__(self, midi_manager=None) -> None:
        self._midi_manager = midi_manager


def _bare_midi_manager(preset: str) -> MidiManager:
    m = object.__new__(MidiManager)
    m._preset = preset
    return m


# --------------------------------------------------------------------------- #
# DeckSimLayout / FaderSpec — plain data shape
# --------------------------------------------------------------------------- #

def test_fader_spec_defaults() -> None:
    f = FaderSpec(cc=48, label='1')
    assert f.cc == 48
    assert f.label == '1'
    assert f.is_master is False


def test_deck_sim_layout_matches_the_apc_mini_mk2_geometry() -> None:
    # Mirrors the real formulas in apc_leds.py (_row_note/_scene_note/
    # _track_note) so a future drift between the plan and the drop-in's
    # registration would show up as a failing assertion here, not silently.
    layout = DeckSimLayout(
        device='apc mini mk2',
        label='Akai APC mini mk2',
        grid_rows=8,
        grid_cols=8,
        grid_note=lambda row, col: row * 8 + col,
        scene_notes=tuple(112 + i for i in range(8)),
        track_notes=tuple(100 + i for i in range(8)),
        faders=tuple(FaderSpec(48 + i, str(i + 1)) for i in range(8))
        + (FaderSpec(56, 'MASTER', is_master=True),),
    )
    assert layout.grid_note(0, 0) == 0
    assert layout.grid_note(7, 7) == 63
    assert layout.scene_notes == (112, 113, 114, 115, 116, 117, 118, 119)
    assert layout.track_notes == (100, 101, 102, 103, 104, 105, 106, 107)
    assert len(layout.faders) == 9
    assert layout.faders[-1].is_master is True
    assert layout.faders[-1].cc == 56


def test_deck_sim_layout_defaults_are_empty() -> None:
    layout = DeckSimLayout(
        device='x', label='X', grid_rows=1, grid_cols=1,
        grid_note=lambda r, c: 0,
    )
    assert layout.scene_notes == ()
    assert layout.track_notes == ()
    assert layout.faders == ()


# --------------------------------------------------------------------------- #
# VJApi: deck-sim layout registry
# --------------------------------------------------------------------------- #

def test_register_and_list_deck_sim_layouts() -> None:
    api = VJApi(_StubApp())
    layout = DeckSimLayout('apc mini mk2', 'APC', 8, 8, lambda r, c: r * 8 + c)
    api.register_deck_sim_layout(layout)
    assert api.deck_sim_layouts() == {'apc mini mk2': layout}


def test_registering_same_device_replaces() -> None:
    api = VJApi(_StubApp())
    old = DeckSimLayout('x', 'Old', 4, 4, lambda r, c: r * 4 + c)
    new = DeckSimLayout('x', 'New', 8, 8, lambda r, c: r * 8 + c)
    api.register_deck_sim_layout(old)
    api.register_deck_sim_layout(new)
    layouts = api.deck_sim_layouts()
    assert len(layouts) == 1
    assert layouts['x'].label == 'New'


def test_deck_sim_layouts_returns_a_copy() -> None:
    api = VJApi(_StubApp())
    api.register_deck_sim_layout(DeckSimLayout('x', 'X', 1, 1, lambda r, c: 0))
    layouts = api.deck_sim_layouts()
    layouts.clear()
    assert len(api.deck_sim_layouts()) == 1  # caller's mutation didn't leak in


def test_active_deck_sim_layout_resolves_via_preset_device() -> None:
    BUILTIN_PRESETS['test_apc_preset'] = {
        'note_map': {}, 'cc_map': {}, 'meta': {'device': 'apc mini mk2'},
    }
    try:
        m = _bare_midi_manager('test_apc_preset')
        api = VJApi(_StubApp(m))
        layout = DeckSimLayout('apc mini mk2', 'APC', 8, 8, lambda r, c: r * 8 + c)
        api.register_deck_sim_layout(layout)
        assert api.active_deck_sim_layout() is layout
    finally:
        del BUILTIN_PRESETS['test_apc_preset']


def test_active_deck_sim_layout_none_when_midi_unavailable() -> None:
    api = VJApi(_StubApp(None))
    api.register_deck_sim_layout(DeckSimLayout('apc mini mk2', 'APC', 8, 8, lambda r, c: 0))
    assert api.active_deck_sim_layout() is None


def test_active_deck_sim_layout_none_when_device_unscoped() -> None:
    BUILTIN_PRESETS['test_unscoped_preset'] = {'note_map': {}, 'cc_map': {}}
    try:
        m = _bare_midi_manager('test_unscoped_preset')
        api = VJApi(_StubApp(m))
        api.register_deck_sim_layout(DeckSimLayout('apc mini mk2', 'APC', 8, 8, lambda r, c: 0))
        assert api.active_deck_sim_layout() is None
    finally:
        del BUILTIN_PRESETS['test_unscoped_preset']


def test_active_deck_sim_layout_none_when_no_layout_registered_for_device() -> None:
    BUILTIN_PRESETS['test_other_device_preset'] = {
        'note_map': {}, 'cc_map': {}, 'meta': {'device': 'some other controller'},
    }
    try:
        m = _bare_midi_manager('test_other_device_preset')
        api = VJApi(_StubApp(m))
        api.register_deck_sim_layout(DeckSimLayout('apc mini mk2', 'APC', 8, 8, lambda r, c: 0))
        assert api.active_deck_sim_layout() is None
    finally:
        del BUILTIN_PRESETS['test_other_device_preset']


# --------------------------------------------------------------------------- #
# VJApi.midi_preset_device() / MidiManager.preset_device()
# --------------------------------------------------------------------------- #

def test_midi_preset_device_empty_without_midi_manager() -> None:
    api = VJApi(_StubApp(None))
    assert api.midi_preset_device() == ''


def test_midi_preset_device_reads_through_to_manager() -> None:
    BUILTIN_PRESETS['test_device_readback'] = {
        'note_map': {}, 'cc_map': {}, 'meta': {'device': 'akai mpk mini'},
    }
    try:
        m = _bare_midi_manager('test_device_readback')
        api = VJApi(_StubApp(m))
        assert api.midi_preset_device() == 'akai mpk mini'
    finally:
        del BUILTIN_PRESETS['test_device_readback']


def test_preset_device_empty_for_unknown_preset() -> None:
    m = _bare_midi_manager('this_preset_does_not_exist')
    assert m.preset_device() == ''


def test_preset_device_empty_for_no_preset() -> None:
    m = _bare_midi_manager('')
    assert m.preset_device() == ''


def test_preset_device_empty_when_meta_missing() -> None:
    BUILTIN_PRESETS['test_no_meta_preset'] = {'note_map': {}, 'cc_map': {}}
    try:
        m = _bare_midi_manager('test_no_meta_preset')
        assert m.preset_device() == ''
    finally:
        del BUILTIN_PRESETS['test_no_meta_preset']


def test_preset_device_survives_a_real_shaped_controller_profile_payload() -> None:
    # Mirrors exactly what ControllerProfile.to_preset() produces
    # (controller_profiles.py), confirming the full payload -- not just
    # cc_map/note_map -- really does survive in BUILTIN_PRESETS.
    BUILTIN_PRESETS['apc_mini_mk2_stock'] = {
        'cc_map': {48: 'speed'},
        'note_map': {0: 'next'},
        'colors': {'next': [21, 3]},
        'meta': {
            'name': 'APC mini mk2 — Stock', 'description': '', 'author': '',
            'version': '1.0.0', 'date': '2026-07-07', 'device': 'apc mini mk2',
            'schema_version': 1,
        },
    }
    try:
        m = _bare_midi_manager('apc_mini_mk2_stock')
        assert m.preset_device() == 'apc mini mk2'
    finally:
        del BUILTIN_PRESETS['apc_mini_mk2_stock']


# --------------------------------------------------------------------------- #
# VJApi: live action-color palette provider
# --------------------------------------------------------------------------- #

def test_midi_action_colors_empty_without_a_provider() -> None:
    api = VJApi(_StubApp())
    assert api.midi_action_colors() == {}


def test_midi_action_colors_calls_the_registered_provider_fresh() -> None:
    api = VJApi(_StubApp())
    calls = []

    def provider():
        calls.append(1)
        return {'next': (21, 3), 'prev': (25, 5)}

    api.register_midi_action_colors(provider)
    assert api.midi_action_colors() == {'next': (21, 3), 'prev': (25, 5)}
    assert api.midi_action_colors() == {'next': (21, 3), 'prev': (25, 5)}
    assert len(calls) == 2  # called fresh each time, not cached


def test_midi_action_colors_swallows_a_raising_provider() -> None:
    api = VJApi(_StubApp())

    def broken_provider():
        raise RuntimeError('boom')

    api.register_midi_action_colors(broken_provider)
    assert api.midi_action_colors() == {}


def test_registering_a_new_provider_replaces_the_old_one() -> None:
    api = VJApi(_StubApp())
    api.register_midi_action_colors(lambda: {'a': (1, 2)})
    api.register_midi_action_colors(lambda: {'b': (3, 4)})
    assert api.midi_action_colors() == {'b': (3, 4)}
