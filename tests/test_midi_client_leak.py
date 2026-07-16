"""Regression tests for the ALSA sequencer client leak (2026-07-16).

python-rtmidi requires an explicit ``delete()`` to free the underlying ALSA
sequencer client; on Python 3.14 garbage collection observably does not do it.
The old code created a fresh probe client on *every* port scan, so portless
``RtMidiIn Client`` entries accumulated until the kernel's ~64-user-client
table filled — port lists came back empty, new opens failed ("error creating
ALSA sequencer client object"), and controllers died mid-session while
already-open connections kept working.

These tests drive the module with a fake rtmidi that counts constructions and
``delete()`` calls: enumeration must reuse one cached probe per direction, and
every teardown path must explicitly delete the objects it drops.
"""
from __future__ import annotations

import pytest

from unicornviz import midi as m


class _FakePort:
    """Counts live instances + delete() calls, mimicking rtmidi Midi{In,Out}."""

    created = 0
    deleted = 0
    ports: list[str] = ['Fake Device MIDI 1']
    fail_get_ports = False

    def __init__(self) -> None:
        type(self).created += 1
        self._open = False

    def get_ports(self):
        if type(self).fail_get_ports:
            raise RuntimeError('scan failed')
        return list(type(self).ports)

    def open_port(self, idx) -> None:
        self._open = True

    def close_port(self) -> None:
        self._open = False

    def set_callback(self, fn, data=None) -> None:
        pass

    def ignore_types(self, **kw) -> None:
        pass

    def delete(self) -> None:
        type(self).deleted += 1


class _FakeIn(_FakePort):
    created = 0
    deleted = 0
    fail_get_ports = False


class _FakeOut(_FakePort):
    created = 0
    deleted = 0
    fail_get_ports = False


class _FakeRtmidi:
    MidiIn = _FakeIn
    MidiOut = _FakeOut


@pytest.fixture(autouse=True)
def _fake_rtmidi(monkeypatch):
    monkeypatch.setattr(m, 'rtmidi', _FakeRtmidi)
    monkeypatch.setattr(m, '_RTMIDI_OK', True)
    # Reset the cached probes + counters between tests.
    m._PortProbe._in = None
    m._PortProbe._out = None
    for cls in (_FakeIn, _FakeOut):
        cls.created = 0
        cls.deleted = 0
        cls.fail_get_ports = False
    yield
    m._PortProbe._in = None
    m._PortProbe._out = None


def test_port_scans_reuse_one_cached_probe_per_direction() -> None:
    for _ in range(25):
        assert m.list_ports() == ['Fake Device MIDI 1']
    for _ in range(25):
        assert m.list_output_ports() == ['Fake Device MIDI 1']
    # 50 scans, exactly one client per direction — this was 50 leaked clients.
    assert _FakeIn.created == 1
    assert _FakeOut.created == 1


def test_failed_scan_destroys_and_rebuilds_the_probe() -> None:
    assert m.list_ports() == ['Fake Device MIDI 1']
    _FakeIn.fail_get_ports = True
    assert m.list_ports() == []                     # failure path
    assert _FakeIn.deleted == 1                     # broken probe freed
    _FakeIn.fail_get_ports = False
    assert m.list_ports() == ['Fake Device MIDI 1']  # rebuilt on next call
    assert _FakeIn.created == 2


def test_manager_stop_deletes_its_inputs() -> None:
    mgr = m.MidiManager(device_hint='')
    mgr._midi_ins = [_FakeIn(), _FakeIn()]          # noqa: SLF001
    before = _FakeIn.deleted
    mgr.stop()
    assert _FakeIn.deleted == before + 2
    assert mgr._midi_ins == []                      # noqa: SLF001


def test_remove_input_device_deletes_the_aux_client() -> None:
    mgr = m.MidiManager(device_hint='')
    assert mgr.add_input_device('fake device') is True
    assert _FakeIn.created >= 1
    before = _FakeIn.deleted
    mgr.remove_input_device('fake device')
    assert _FakeIn.deleted == before + 1
    assert mgr.aux_devices == []


def test_midi_output_close_deletes_the_client() -> None:
    out = m.MidiOut()
    assert out.open('fake') is True
    before = _FakeOut.deleted
    out.close()
    assert _FakeOut.deleted == before + 1
    assert not out.available


def test_destroy_rtmidi_tolerates_none_and_errors() -> None:
    m.destroy_rtmidi(None)                          # no-op

    class _Angry:
        def close_port(self):
            raise RuntimeError('nope')

        def delete(self):
            raise RuntimeError('nope')

    m.destroy_rtmidi(_Angry())                      # swallowed
