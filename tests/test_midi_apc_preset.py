from __future__ import annotations

from unicornviz.midi import BUILTIN_PRESETS


def test_apc_preset_maps_entire_grid() -> None:
    note_map = BUILTIN_PRESETS['akai_apc_mini_mk2']['note_map']

    for note in range(0, 64):
        assert note in note_map


def test_apc_preset_maps_track_and_scene_buttons() -> None:
    note_map = BUILTIN_PRESETS['akai_apc_mini_mk2']['note_map']

    for note in range(100, 108):
        assert note in note_map
    for note in range(112, 120):
        assert note in note_map


def test_apc_preset_maps_all_faders_including_master() -> None:
    cc_map = BUILTIN_PRESETS['akai_apc_mini_mk2']['cc_map']

    for cc in range(48, 57):
        assert cc in cc_map
