"""P2-10 (audit 2026-09-30): two threads could switch capture streams at once.

Operator ``select_source`` / ``cycle_source`` (main thread, or the helper's
command thread) and the silence auto-fallback (the analysis thread since
2026-09-22) both ran stop-reader -> close -> open on ``_stream``,
``_reader_thread`` and ``_candidate_index`` with no lock, which can double-open
PortAudio (the code's own comments tie that to heap-corruption aborts).  The
whole switch, ``start()`` and ``stop()`` now serialize on one re-entrant lock.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from unicornviz.audio import capture as capture_mod
from unicornviz.audio.capture import AudioCapture


class _Tracker:
    """Counts how many open/close sequences overlap in time."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.inside = 0
        self.max_inside = 0
        self.opens: list[int | None] = []

    def enter(self) -> None:
        with self.lock:
            self.inside += 1
            self.max_inside = max(self.max_inside, self.inside)

    def leave(self) -> None:
        with self.lock:
            self.inside -= 1


@pytest.fixture
def cap(monkeypatch):
    monkeypatch.setattr(capture_mod, '_SD_AVAILABLE', True)
    c = AudioCapture(auto_fallback_enabled=True, fallback_silence_seconds=0.1,
                     fallback_cooldown_seconds=0.0)
    tracker = _Tracker()
    c.tracker = tracker
    c._active = True
    c._stream = object()
    c._candidate_devices = [1, 2, 3]
    c._candidate_index = 0
    c._viable_source_keys = {c._source_key_for_device(d) for d in (1, 2, 3)}
    c._state_path = Path('/tmp/unicornviz-test-audio-source-state.json')
    c._sample_rate = 48000
    c._save_source_state = lambda: None
    c._device_is_claimed = lambda _d: False
    c._stop_reader_thread = lambda _s=None: True

    def slow_close(_stream, context=''):
        tracker.enter()
        time.sleep(0.05)
        tracker.leave()

    def slow_open(device):
        tracker.enter()
        time.sleep(0.05)
        c._stream = object()
        tracker.opens.append(device)
        tracker.leave()

    c._close_stream_safely = slow_close
    c._open_stream = slow_open
    return c


def test_two_concurrent_switches_never_overlap(cap) -> None:
    barrier = threading.Barrier(2)

    def operator():
        barrier.wait()
        cap._switch_to_candidate_index(1)

    def fallback():
        barrier.wait()
        cap._switch_to_candidate_index(2)

    threads = [threading.Thread(target=operator), threading.Thread(target=fallback)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert cap.tracker.max_inside == 1                       # one open/close at a time
    assert len(cap.tracker.opens) == 2                       # and both ran, in turn
    assert cap._candidate_index in (1, 2) and cap._stream is not None


def test_select_cycle_and_stop_are_serialized_too(cap) -> None:
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(cap.select_source(1))),
        threading.Thread(target=lambda: results.append(cap.cycle_source(1))),
        threading.Thread(target=lambda: results.append(cap._switch_to_candidate_index(2))),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert cap.tracker.max_inside == 1


def test_stop_waits_for_a_switch_in_progress(cap) -> None:
    started = threading.Event()
    real_open = cap._open_stream

    def open_and_signal(device):
        started.set()
        real_open(device)

    cap._open_stream = open_and_signal
    t = threading.Thread(target=lambda: cap._switch_to_candidate_index(1))
    t.start()
    assert started.wait(5)
    cap.stop()                                               # must not interleave with the open
    t.join(10)
    assert cap.tracker.max_inside == 1
    assert cap._active is False


def test_the_lock_is_reentrant_so_a_switch_can_call_stop_paths(cap) -> None:
    assert isinstance(cap._switch_lock, type(threading.RLock()))
    with cap._switch_lock:
        with cap._switch_lock:
            pass


def test_stop_does_not_hang_behind_a_stuck_open(cap, monkeypatch) -> None:
    """A PortAudio open can hang while holding the lock (OBS + PipeWire JACK
    shim, 2026-09-14); quitting must go ahead after a bounded wait."""
    monkeypatch.setattr(AudioCapture, '_STOP_LOCK_TIMEOUT_S', 0.3)
    release = threading.Event()
    held = threading.Event()

    def hung_open(device):
        held.set()
        release.wait(10)

    cap._open_stream = hung_open
    t = threading.Thread(target=lambda: cap._switch_to_candidate_index(1))
    t.start()
    assert held.wait(5)
    t0 = time.monotonic()
    cap.stop()
    assert time.monotonic() - t0 < 2.0 and cap._active is False
    release.set()
    t.join(10)
