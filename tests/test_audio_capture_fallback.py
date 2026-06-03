from __future__ import annotations

import time

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
    c._silent_blocks = 99999
    c._sample_rate = 48000
    c._stream_opened_time = time.time() - 10.0
    c._close_stream_safely = lambda *_args, **_kwargs: None
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
    c.maybe_fallback()

    assert opened == [2]
    assert c._candidate_index == 1
    assert c._active is True


def test_fallback_marks_inactive_when_switch_and_restore_fail(monkeypatch) -> None:
    monkeypatch.setattr(capture_mod, 'sd', _FakeSD())
    c = _make_capture()

    def _open(_device):
        raise RuntimeError('forced failure')

    c._open_stream = _open
    c.maybe_fallback()

    assert c._candidate_index == 0
    assert c._stream is None
    assert c._active is False


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
    c.maybe_fallback()

    assert calls == [2, 1]
    assert c._candidate_index == 0
    assert c._stream is not None
    assert c._active is True


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
