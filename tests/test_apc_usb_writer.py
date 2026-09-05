"""APC libusb LED output must never block the thread that pushes colors.

2026-09-05: the render thread lost 267 s of a 72-minute session to
``_LibUsbIO.drain()``, which ran ``libusb_bulk_transfer`` synchronously with
a 500 ms timeout against a controller the kernel had left in a shutdown
state.  Every transition and ping-pong recolors the pads, so the stalls
landed exactly where the owner felt them.  These tests pin the writer
thread, the backoff, the single-warning-per-outage rule, and the repaint
after recovery.  Hermetic: libusb is faked, no device is touched.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
import threading
import time
from pathlib import Path

import pytest

_APC = Path(__file__).resolve().parent.parent / 'drop-ins' / 'midi-controllers-01' / 'apc_leds.py'


@pytest.fixture(scope='module')
def apc():
    spec = importlib.util.spec_from_file_location('_test_apc_leds', _APC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['_test_apc_leds'] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeLibusb:
    """Just enough of libusb-1.0 for _LibUsbIO's writer path."""

    def __init__(self, rcs) -> None:
        self.rcs = list(rcs)          # return code per transfer, last one repeats
        self.calls: list[bytes] = []
        self.event = threading.Event()

    def libusb_bulk_transfer(self, dev, ep, buf, length, xferred, timeout_ms):
        self.calls.append(bytes(buf))
        rc = self.rcs.pop(0) if len(self.rcs) > 1 else self.rcs[0]
        self.event.set()
        return rc

    def libusb_strerror(self, rc):
        return b'Operation timed out' if rc == -7 else b'OK'

    # close() path -- no-ops for the fake device
    def libusb_release_interface(self, dev, iface): return 0
    def libusb_close(self, dev): return None
    def libusb_exit(self, ctx): return None


def _io(apc, monkeypatch, lib):
    monkeypatch.setattr(apc, '_load_libusb', lambda: lib)
    io = apc._LibUsbIO()
    io._dev = 1                       # "open" without touching hardware
    io._WRITE_PAUSE_S = 0.2           # keep the outage short for the test
    return io


def _wait_calls(lib, n, timeout=2.0):
    end = time.monotonic() + timeout
    while len(lib.calls) < n and time.monotonic() < end:
        time.sleep(0.005)
    return len(lib.calls) >= n


def test_drain_returns_immediately_even_when_the_transfer_would_time_out(apc, monkeypatch):
    lib = _FakeLibusb([-7])
    io = _io(apc, monkeypatch, lib)
    io.write(bytes([0x90, 1, 5]))
    t0 = time.perf_counter()
    io.drain()
    assert (time.perf_counter() - t0) < 0.05          # the old path took 0.5 s
    assert _wait_calls(lib, 1)
    assert threading.current_thread().name != 'apc-usb-writer'
    io.close()


def test_three_timeouts_pause_output_and_warn_once(apc, monkeypatch, caplog):
    lib = _FakeLibusb([-7])
    io = _io(apc, monkeypatch, lib)
    with caplog.at_level(logging.DEBUG, logger=apc.log.name):
        for _ in range(3):
            io.write(bytes([0x90, 1, 5]))
            io.drain()
            _wait_calls(lib, len(lib.calls) + 1)
        assert _wait_calls(lib, 3)
        time.sleep(0.02)
        assert io.paused
        # Pushes during the outage are dropped, not queued.
        io.write(bytes([0x90, 2, 5]))
        io.drain()
        time.sleep(0.05)
        assert len(lib.calls) == 3
        assert io._dropped_while_paused == 1
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert 'pausing LED output' in warnings[0].getMessage()
    io.close()


def test_recovery_after_a_pause_requests_one_full_repaint(apc, monkeypatch, caplog):
    lib = _FakeLibusb([-7, -7, -7, 0])                 # three timeouts, then it answers
    io = _io(apc, monkeypatch, lib)
    for _ in range(3):
        io.write(bytes([0x90, 1, 5]))
        io.drain()
        _wait_calls(lib, len(lib.calls) + 1)
    time.sleep(0.02)
    assert io.paused
    time.sleep(0.25)                                   # outage window elapses
    assert not io.paused
    with caplog.at_level(logging.INFO, logger=apc.log.name):
        io.write(bytes([0x90, 3, 5]))                  # the probe
        io.drain()
        assert _wait_calls(lib, 4)
        time.sleep(0.02)
    assert io.consume_repaint_request() is True
    assert io.consume_repaint_request() is False       # one-shot
    assert io._timeouts_in_a_row == 0
    assert any('accepting LED writes again' in r.getMessage() for r in caplog.records)
    io.close()


def test_packets_are_sent_in_order_and_close_flushes_the_queue(apc, monkeypatch):
    lib = _FakeLibusb([0])
    io = _io(apc, monkeypatch, lib)
    for note in (1, 2, 3):
        io.write(bytes([0x90, note, 5]))
        io.drain()
    io.close()                                         # joins the writer after the sentinel
    assert [c[2] for c in lib.calls] == [1, 2, 3]      # USB-MIDI packet: cin, status, note, vel
    assert io._writer is None


def test_led_feedback_forces_a_repaint_when_the_io_asks_for_one(apc):
    """APCLedFeedback.update() must translate the IO's recovery into force=True."""
    class _IO:
        available = True
        def __init__(self): self.flag = True
        def consume_repaint_request(self):
            f, self.flag = self.flag, False
            return f

    fb = object.__new__(apc.APCLedFeedback)
    fb._rawmidi = _IO()
    fb._last_update = 0.0
    fb._refresh_from_app_state = lambda: None
    forced: list[bool] = []
    fb._push_all = lambda force=False: forced.append(force)
    fb.update(0.016)
    fb._last_update = 0.0
    fb.update(0.016)
    assert forced == [True, False]
