"""Regression tests for multi-device MIDI input (primary + aux raw-only).

Exercises the core routing added for concurrent controllers (e.g. an APC on
the VJ side and a DDJ-REV1 driving the DJ mixer): auxiliary devices must reach
named (raw) listeners only — never the plain action-dispatch listener — and
must tag events with their source.  Routing is driven directly through
``MidiManager._callback`` so no hardware/rtmidi ports are required.
"""
from __future__ import annotations

from unicornviz.midi import MidiEvent, MidiManager


def _cc(num: int, val: int = 100, channel: int = 0) -> tuple[list[int], float]:
    return ([0xB0 | (channel & 0x0F), num, val], 0.0)


def test_midi_event_source_defaults_empty() -> None:
    assert MidiEvent('cc', 0, 1, 0.5).source == ''


def test_primary_events_reach_plain_and_named_listeners() -> None:
    m = MidiManager()
    plain: list[MidiEvent] = []
    named: list[MidiEvent] = []
    m.add_listener(plain.append)
    m.add_named_listener('mix', named.append)

    m._callback(_cc(20), None)  # noqa: SLF001 — primary device (data is None)

    assert len(plain) == 1
    assert len(named) == 1
    assert plain[0].source == ''


def test_aux_events_reach_named_only_and_are_tagged() -> None:
    m = MidiManager()
    plain: list[MidiEvent] = []
    named: list[MidiEvent] = []
    m.add_listener(plain.append)
    m.add_named_listener('mix', named.append)

    # Aux device: DDJ-REV1 crossfader is CC 31 on channel 7 (0xB6).
    m._callback(([0xB6, 31, 64], 0.0), 'ddj-rev1')  # noqa: SLF001

    assert plain == []              # action-dispatch path is NOT triggered
    assert len(named) == 1
    assert named[0].source == 'ddj-rev1'
    assert named[0].channel == 6
    assert named[0].number == 31


def test_add_input_device_returns_false_when_no_port_matches() -> None:
    m = MidiManager()
    # No such device present -> graceful False, no aux devices registered.
    assert m.add_input_device('nonexistent-controller-zzz') is False
    assert m.aux_devices == []


def test_remove_input_device_is_safe_when_absent() -> None:
    m = MidiManager()
    m.remove_input_device('never-opened')  # must not raise
    assert m.aux_devices == []


def test_stop_does_not_touch_aux_registry() -> None:
    # Switching the primary device (which calls stop()) must not drop aux state.
    m = MidiManager()
    m._aux_ins = [('ddj-rev1', object(), 'DDJ-REV1 MIDI 1')]  # noqa: SLF001
    m.stop()
    assert m.aux_devices == ['DDJ-REV1 MIDI 1']
