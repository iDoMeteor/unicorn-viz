from __future__ import annotations

import time
from pathlib import Path

import unicornviz.audio.capture as capture_mod
from unicornviz.audio.capture import AudioCapture


class _FakeSD:
    @staticmethod
    def query_devices(device=None, kind=None):
        if kind == 'input':
            return {'name': 'default-input'}
        return {'name': f'device-{device}'}


def _make_capture() -> AudioCapture:
    c = AudioCapture(
        auto_fallback_enabled=True,
        fallback_silence_seconds=0.1,
        fallback_cooldown_seconds=0.0,
    )
    c._active = True
    c._stream = object()
    c._candidate_devices = [1, 2]
    c._candidate_index = 0
    c._viable_source_keys = {
        c._source_key_for_device(1),
        c._source_key_for_device(2),
    }
    c._state_path = Path('/tmp/unicornviz-test-audio-source-state.json')
    c._silent_blocks = 99999
    c._sample_rate = 48000
    c._stream_opened_time = time.time() - 10.0
    c._close_stream_safely = lambda *_args, **_kwargs: None
    c._save_source_state = lambda: None
    return c


def _run_fallback(c) -> None:
    """Drive a full fallback cycle.

    The probe spawns a subprocess (numpy + sounddevice + opening a device), so
    it runs on a worker thread and its result is acted on by a later call --
    the audio manager calls this every frame.  Two calls plus a join is what
    two frames look like.
    """
    c.maybe_fallback()                      # frame 1: starts the probe
    t = c._probe_thread
    if t is not None:
        t.join(timeout=5.0)
    c._last_fallback_time = 0.0             # the cooldown is not under test
    c.maybe_fallback()                      # frame 2: acts on the result


def test_fallback_moves_to_next_candidate_on_success(monkeypatch) -> None:
    monkeypatch.setattr(capture_mod, 'sd', _FakeSD())
    c = _make_capture()

    opened: list[int | None] = []

    def _open(device):
        opened.append(device)
        c._stream = object()
        c._active = True

    c._open_stream = _open
    c._probe_source_rms = lambda _device: 0.05
    _run_fallback(c)

    assert opened == [2]
    assert c._candidate_index == 1
    assert c._active is True


def test_fallback_marks_inactive_when_switch_and_restore_fail(monkeypatch) -> None:
    monkeypatch.setattr(capture_mod, 'sd', _FakeSD())
    c = _make_capture()

    c._probe_source_rms = lambda _device: 0.0
    _run_fallback(c)

    assert c._candidate_index == 0
    assert c._stream is not None
    assert c._active is True


def test_fallback_restores_previous_source_when_reopen_fails(monkeypatch) -> None:
    monkeypatch.setattr(capture_mod, 'sd', _FakeSD())
    c = _make_capture()

    calls: list[int | None] = []

    def _open(device):
        calls.append(device)
        if device == 2:
            raise RuntimeError('next failed')
        c._stream = object()
        c._active = True

    c._open_stream = _open
    c._probe_source_rms = lambda _device: 0.05
    _run_fallback(c)

    assert calls == [2, 1]
    assert c._candidate_index == 0
    assert c._stream is not None
    assert c._active is True


def test_fallback_ignores_untagged_targets(monkeypatch) -> None:
    monkeypatch.setattr(capture_mod, 'sd', _FakeSD())
    c = _make_capture()
    c._candidate_devices = [1, 2, 3]
    c._candidate_index = 0
    c._viable_source_keys = {
        c._source_key_for_device(1),
        c._source_key_for_device(3),
    }

    opened: list[int | None] = []

    def _open(device):
        opened.append(device)
        c._stream = object()
        c._active = True

    c._open_stream = _open
    c._probe_source_rms = lambda _device: 0.05

    _run_fallback(c)

    assert opened == [3]
    assert c._candidate_index == 2


def test_cycle_source_moves_to_next_candidate(monkeypatch) -> None:
    monkeypatch.setattr(capture_mod, 'sd', _FakeSD())
    c = _make_capture()

    opened: list[int | None] = []

    def _open(device):
        opened.append(device)
        c._stream = object()
        c._active = True

    c._open_stream = _open
    label = c.cycle_source(1)

    assert opened == [2]
    assert c._candidate_index == 1
    assert label == 'device-2'


def test_cycle_source_restores_previous_when_target_fails(monkeypatch) -> None:
    monkeypatch.setattr(capture_mod, 'sd', _FakeSD())
    c = _make_capture()

    calls: list[int | None] = []

    def _open(device):
        calls.append(device)
        if device == 2:
            raise RuntimeError('next failed')
        c._stream = object()
        c._active = True

    c._open_stream = _open
    label = c.cycle_source(1)

    assert calls == [2, 1]
    assert c._candidate_index == 0
    assert label == 'device-1'


def test_candidate_order_prefers_default_input_first(monkeypatch) -> None:
    class _CandidateSD:
        @staticmethod
        def query_devices(device=None, kind=None):
            if kind == 'input':
                return {'name': 'default-input'}
            if device is not None:
                return {
                    'name': f'device-{device}',
                    'max_input_channels': 2,
                    'hostapi': 0,
                }
            return [
                {'name': 'PipeWire monitor', 'max_input_channels': 2, 'hostapi': 0},
                {'name': 'USB webcam mic', 'max_input_channels': 1, 'hostapi': 0},
            ]

        @staticmethod
        def query_hostapis():
            return [{'name': 'PipeWire'}]

    monkeypatch.setattr(capture_mod, 'sd', _CandidateSD())
    monkeypatch.setattr(capture_mod, '_SD_AVAILABLE', True)

    candidates = capture_mod._candidate_monitor_devices('', prefer_default_input=True)

    assert candidates[0] is None


def test_a_silent_source_does_not_probe_every_frame(monkeypatch) -> None:
    """The framerate collapse.

    maybe_fallback() runs from the audio manager's per-frame update, and the
    probe behind it spawns a Python subprocess (numpy + sounddevice + opening
    a device, ~200-800 ms).  The cooldown was stamped only after a *successful
    switch*, so when every candidate was silent -- the exact case this code
    exists for -- the gate never closed and a probe ran on every frame, inline,
    on the render thread.
    """
    monkeypatch.setattr(capture_mod, 'sd', _FakeSD())
    c = _make_capture()
    c._fallback_cooldown_seconds = 8.0
    c._last_fallback_time = 0.0
    probes: list = []

    def _probe(device):
        probes.append(device)
        return 0.0                      # every candidate is silent too

    c._probe_source_rms = _probe
    for _ in range(120):                # two seconds of frames
        c.maybe_fallback()
        t = c._probe_thread
        if t is not None:
            t.join(timeout=5.0)
    assert len(probes) == 1, f'probed {len(probes)} times in 120 frames'
    assert c._candidate_index == 0      # nothing to switch to, so no switch


def test_the_probe_never_runs_on_the_calling_thread(monkeypatch) -> None:
    """It must not block the render thread even once."""
    import threading as _th
    monkeypatch.setattr(capture_mod, 'sd', _FakeSD())
    c = _make_capture()
    caller = _th.current_thread()
    ran_on: list = []

    def _probe(device):
        ran_on.append(_th.current_thread())
        return 0.05

    c._probe_source_rms = _probe
    c._open_stream = lambda device: None
    c.maybe_fallback()
    t = c._probe_thread
    assert t is not None
    t.join(timeout=5.0)
    assert ran_on and ran_on[0] is not caller
