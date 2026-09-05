"""The hardware-encoder probe runs at startup, not when record is pressed.

``_probe_hw_encoder`` encodes a test frame per candidate with a 20 s
ceiling each, and used to run lazily on the main thread from
``_resolve_encoder()`` -- i.e. the moment the operator hit record.  These
tests pin the startup prewarm and that a concurrent synchronous caller
waits for the in-flight probe instead of launching a second one.
"""
from __future__ import annotations

import threading
import time

import pytest

from unicornviz import recording as rec


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch):
    monkeypatch.setattr(rec, '_hw_encoder_cache', None)
    yield


def test_prewarm_runs_the_probe_on_a_worker_and_caches(monkeypatch):
    threads: list[str] = []

    def fake_run(cmd, **k):
        threads.append(threading.current_thread().name)
        time.sleep(0.05)
        return type('P', (), {'returncode': 0, 'stderr': b''})()
    monkeypatch.setattr(rec.subprocess, 'run', fake_run)
    monkeypatch.setattr(rec, '_render_device', lambda: '/dev/dri/renderD128')
    t = rec.prewarm_hw_encoder_probe('ffmpeg')
    t.join(timeout=2.0)
    assert threads and set(threads) == {'uv-hw-encoder-probe'}
    assert rec._hw_encoder_cache not in (None, False)
    # Record time: no new spawn, the cached answer is returned at once.
    before = len(threads)
    assert rec._probe_hw_encoder('ffmpeg') == rec._hw_encoder_cache
    assert len(threads) == before


def test_sync_probe_waits_for_the_in_flight_prewarm(monkeypatch):
    spawns = 0

    def fake_run(cmd, **k):
        nonlocal spawns
        spawns += 1
        time.sleep(0.2)
        return type('P', (), {'returncode': 0, 'stderr': b''})()
    monkeypatch.setattr(rec.subprocess, 'run', fake_run)
    monkeypatch.setattr(rec, '_render_device', lambda: '/dev/dri/renderD128')
    t = rec.prewarm_hw_encoder_probe('ffmpeg')
    time.sleep(0.05)                                   # prewarm is mid-probe
    result = rec._probe_hw_encoder('ffmpeg')           # "record pressed"
    t.join(timeout=2.0)
    assert result is not None
    assert spawns == 1                                 # one probe, shared


def test_no_hardware_encoder_caches_false_and_returns_none(monkeypatch):
    monkeypatch.setattr(rec.subprocess, 'run',
                        lambda cmd, **k: type('P', (), {'returncode': 1, 'stderr': b'no'})())
    monkeypatch.setattr(rec, '_render_device', lambda: '/dev/dri/renderD128')
    assert rec._probe_hw_encoder('ffmpeg') is None
    assert rec._hw_encoder_cache is False
