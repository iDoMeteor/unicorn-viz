from __future__ import annotations

import sys
from pathlib import Path

from unicornviz.midi import BUILTIN_PRESETS, MidiManager

# Register device presets from the drop-in, mirroring what app.py does at runtime.
_DROPIN = Path(__file__).parent.parent / 'drop-ins' / 'midi-controllers-01'
sys.path.insert(0, str(_DROPIN))
from controller_presets import register_all  # noqa: E402  (after sys.path manipulation)

# register_all() also claims the APC rawmidi device early (an app-startup
# optimization). That is harmless at runtime but blocks during test collection
# when the running app already holds the device -- which wedged the whole
# pytest hook. The claim is register_all's only use of load_dropin_symbol in a
# (MidiManager, None) call, so neutralize just that side effect, then restore it
# so nothing else in the session is affected.
import unicornviz.dropins as _dropins  # noqa: E402

_saved_loader = _dropins.load_dropin_symbol
_dropins.load_dropin_symbol = lambda *_a, **_k: None
try:
    register_all(MidiManager, None)
finally:
    _dropins.load_dropin_symbol = _saved_loader


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
