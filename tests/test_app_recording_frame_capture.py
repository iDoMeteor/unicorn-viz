from __future__ import annotations

from pathlib import Path

from unicornviz.app import App
from unicornviz.config import Config


def _default_cfg() -> Config:
    return Config(Path('tests') / '_missing_config_for_tests.toml')


class _FakeRecorder:
    def __init__(self) -> None:
        self.is_recording = True
        self.frames: list[bytes] = []

    def write_frame(self, frame: bytes) -> bool:
        self.frames.append(frame)
        return True

    def stop(self) -> None:
        return None


def test_capture_recording_frame_uses_screenshot_frame() -> None:
    app = App(_default_cfg())
    recorder = _FakeRecorder()
    app._recorder = recorder
    app._ctx = object()
    app.read_screenshot_frame = lambda: (b'frame-bytes', 640, 360)  # type: ignore[method-assign]

    app._capture_recording_frame()

    assert recorder.frames == [b'frame-bytes']


def test_capture_recording_frame_skips_when_screenshot_unavailable() -> None:
    app = App(_default_cfg())
    recorder = _FakeRecorder()
    app._recorder = recorder
    app._ctx = object()
    app.read_screenshot_frame = lambda: None  # type: ignore[method-assign]

    app._capture_recording_frame()

    assert recorder.frames == []