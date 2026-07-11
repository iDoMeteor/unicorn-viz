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


def test_frame_capture_snapshot_defaults_to_canvas_dimensions() -> None:
    app = App(_default_cfg())
    app._width = 1920
    app._height = 1080

    app._update_frame_capture_snapshot(b'full-frame')

    assert app.get_frame_capture() == (b'full-frame', 1920, 1080, 3)


def test_frame_capture_snapshot_records_downsampled_dimensions() -> None:
    app = App(_default_cfg())
    app._width = 3840
    app._height = 2163

    app._update_frame_capture_snapshot(b'preview-frame', 960, 541)

    assert app.get_frame_capture() == (b'preview-frame', 960, 541, 3)


def test_frame_capture_snapshot_clears_on_none() -> None:
    app = App(_default_cfg())
    app._update_frame_capture_snapshot(b'frame', 960, 540)

    app._update_frame_capture_snapshot(None)

    assert app.get_frame_capture() == (None, 0, 0, 0)