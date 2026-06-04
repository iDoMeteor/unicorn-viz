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
    c.maybe_fallback()

    assert opened == [2]
    assert c._candidate_index == 1
    assert c._active is True


def test_fallback_marks_inactive_when_switch_and_restore_fail(monkeypatch) -> None:
    monkeypatch.setattr(capture_mod, 'sd', _FakeSD())
    c = _make_capture()

    c._probe_source_rms = lambda _device: 0.0
    c.maybe_fallback()

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
    c.maybe_fallback()

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

    c.maybe_fallback()

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
