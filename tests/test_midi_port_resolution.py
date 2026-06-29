from __future__ import annotations

import sys
from pathlib import Path

from unicornviz.midi import MidiManager

# Register drop-in presets and dual-port tokens, mirroring what app.py does at runtime.
_DROPIN = Path(__file__).parent.parent / 'drop-ins' / 'midi-controllers-01'
sys.path.insert(0, str(_DROPIN))
from controller_presets import register_all  # noqa: E402

register_all(MidiManager, None)


def test_generic_preset_selects_first_hint_match() -> None:
    ports = [
        'Launchpad X MIDI',
        'Akai MPK mini 3',
        'APC mini mk2 Notes',
    ]

    indices = MidiManager._resolve_target_indices(ports, 'akai', 'generic')  # noqa: SLF001

    assert indices == [1]


def test_apc_preset_binds_notes_and_control_from_model_hint() -> None:
    ports = [
        'APC mini mk2 Notes',
        'APC mini mk2 Control',
        'LoopMIDI Port',
    ]

    indices = MidiManager._resolve_target_indices(ports, 'apc mini mk2', 'akai_apc_mini_mk2')  # noqa: SLF001

    assert indices == [0, 1]


def test_apc_preset_binds_dual_ports_when_hint_targets_notes_only() -> None:
    ports = [
        'APC mini mk2 Notes',
        'APC mini mk2 Control',
        'LoopMIDI Port',
    ]

    indices = MidiManager._resolve_target_indices(ports, 'apc mini mk2 notes', 'akai_apc_mini_mk2')  # noqa: SLF001

    assert indices == [0, 1]


def test_apc_preset_respects_explicit_non_apc_hint() -> None:
    ports = [
        'APC mini mk2 Notes',
        'APC mini mk2 Control',
        'LoopMIDI Port',
    ]

    indices = MidiManager._resolve_target_indices(ports, 'loopmidi', 'akai_apc_mini_mk2')  # noqa: SLF001

    assert indices == [2]
