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


def test_vaapi_is_never_probed_on_windows_or_macos(monkeypatch):
    """VA-API is a Linux API; on the 2026-09-09 Windows beta its probe alone
    held the visualizer at ~1 fps for 17 s before failing."""
    monkeypatch.setattr(rec.sys, 'platform', 'win32')
    assert [c[0] for c in rec._hw_encoder_candidates()] == ['h264_nvenc', 'h264_qsv']
    assert rec._probe_timeout_s() == 6.0          # a hung QSV probe is cut short
    monkeypatch.setattr(rec.sys, 'platform', 'darwin')
    assert 'h264_vaapi' not in [c[0] for c in rec._hw_encoder_candidates()]
    monkeypatch.setattr(rec.sys, 'platform', 'linux')
    assert [c[0] for c in rec._hw_encoder_candidates()] == [c[0] for c in rec._HW_ENCODERS]
    assert rec._probe_timeout_s() == 20.0


def test_startup_prewarm_is_gated_on_auto_record():
    """The boot-time probe competes with the visualizer for the GPU, so it
    only runs when a recording is going to start by itself."""
    import inspect
    import unicornviz.app as app_mod
    src = inspect.getsource(app_mod)
    call = src.index('prewarm_hw_encoder_probe(str(self.cfg')
    gate = src[call - 600:call]
    assert "'auto_record'" in gate
