"""Regression tests: recording audio capture and stop must work on Windows.

Pins the Windows-release contract: the Linux 'pulse' default is remapped to
DirectShow with loopback discovery (video-only degrade when none exists,
never a failed ffmpeg spawn), and the graceful-stop path never calls
send_signal(SIGINT) on win32 (unsupported → ValueError → orphaned ffmpeg
with an unfinalized MP4).
"""
from __future__ import annotations

import signal
import sys

import unicornviz.recording as recording


class _Cfg:
    def __init__(self, values: dict | None = None) -> None:
        self._values = values or {}

    def get(self, section: str, key: str, default=None):
        return self._values.get(f'{section}.{key}', default)


def _recorder(**cfg_values) -> recording.Recorder:
    return recording.Recorder(_Cfg(cfg_values), 64, 64)


def test_pulse_default_remaps_to_dshow_on_windows(monkeypatch) -> None:
    rec = _recorder()
    monkeypatch.setattr(recording.sys, 'platform', 'win32')
    monkeypatch.setattr(
        rec, '_resolve_windows_dshow_device', lambda: 'Stereo Mix (Realtek)'
    )
    assert rec._resolve_audio_input() == ('dshow', 'audio=Stereo Mix (Realtek)')


def test_no_loopback_device_degrades_to_video_only(monkeypatch) -> None:
    rec = _recorder()
    monkeypatch.setattr(recording.sys, 'platform', 'win32')
    monkeypatch.setattr(rec, '_resolve_windows_dshow_device', lambda: None)
    assert rec._resolve_audio_input() is None
    # And the built command must carry no audio input at all.
    cmd = rec._build_command(rec._build_output_path())
    assert 'dshow' not in cmd
    assert '-an' in cmd


def test_configured_device_is_prefixed_for_dshow(monkeypatch) -> None:
    rec = _recorder(**{'recording.audio_input_device': 'CABLE Output (VB-Audio)'})
    monkeypatch.setattr(recording.sys, 'platform', 'win32')
    assert rec._resolve_audio_input() == ('dshow', 'audio=CABLE Output (VB-Audio)')


def test_linux_pulse_path_unchanged(monkeypatch) -> None:
    rec = _recorder()
    monkeypatch.setattr(recording.sys, 'platform', 'linux')
    monkeypatch.setattr(rec, '_resolve_pulse_source', lambda: 'sink.monitor')
    assert rec._resolve_audio_input() == ('pulse', 'sink.monitor')


def test_graceful_stop_uses_ctrl_break_on_windows(monkeypatch) -> None:
    sent: list = []

    class _Proc:
        def send_signal(self, sig) -> None:
            sent.append(sig)

    monkeypatch.setattr(recording.sys, 'platform', 'win32')
    # CTRL_BREAK_EVENT only exists on Windows' signal module.
    monkeypatch.setattr(signal, 'CTRL_BREAK_EVENT', 21, raising=False)
    recording._send_graceful_stop(_Proc())
    assert sent == [21]

    sent.clear()
    monkeypatch.setattr(recording.sys, 'platform', 'linux')
    recording._send_graceful_stop(_Proc())
    assert sent == [signal.SIGINT]


def test_dshow_device_listing_parser(monkeypatch) -> None:
    listing = (
        '[dshow @ 0x1] "Integrated Webcam" (video)\n'
        '[dshow @ 0x1] "Microphone Array (Intel)" (audio)\n'
        '[dshow @ 0x1] "Stereo Mix (Realtek(R) Audio)" (audio)\n'
    )

    class _Result:
        stderr = listing
        stdout = ''

    rec = _recorder()
    monkeypatch.setattr(recording.subprocess, 'run', lambda *a, **kw: _Result())
    # Must pick the loopback-class device, never the microphone.
    assert rec._resolve_windows_dshow_device() == 'Stereo Mix (Realtek(R) Audio)'

    class _NoLoopback:
        stderr = '[dshow @ 0x1] "Microphone Array (Intel)" (audio)\n'
        stdout = ''

    monkeypatch.setattr(recording.subprocess, 'run', lambda *a, **kw: _NoLoopback())
    assert rec._resolve_windows_dshow_device() is None
