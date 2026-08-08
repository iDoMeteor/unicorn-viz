from __future__ import annotations

from pathlib import Path

from unicornviz.config import Config
from unicornviz.recording import Recorder


def _default_cfg() -> Config:
    return Config(Path('tests') / '_missing_config_for_tests.toml')


class _FakeStdin:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self) -> None:
        self.stdin = _FakeStdin()
        self.wait_calls: list[float | None] = []
        self.sent_signals: list[object] = []
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        return 0

    def send_signal(self, signal: object) -> None:
        self.sent_signals.append(signal)


class _FakeThread:
    def __init__(self) -> None:
        self.join_calls: list[float | None] = []
        self._alive = False

    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(timeout)

    def is_alive(self) -> bool:
        return self._alive


def test_stop_closes_stdin_and_releases_pending_frame() -> None:
    """stop() must never block on the writer hand-off.

    The writer is fed through a single latest-frame slot rather than a
    queue, so stopping only has to signal, join, and drop the reference —
    there is no sentinel to enqueue and nothing that can back-pressure the
    caller.
    """
    recorder = Recorder(_default_cfg(), 1920, 1080)
    process = _FakeProcess()
    writer_thread = _FakeThread()

    recorder._process = process
    recorder._current_path = Path('recordings/test.mp4')
    recorder._latest_frame = b'pending frame bytes'
    recorder._writer_thread = writer_thread
    recorder._recording_stopping = False
    recorder._capture_audio = False

    path = recorder.stop()

    assert path == Path('recordings/test.mp4')
    assert process.stdin.closed is True
    assert process.wait_calls == [10.0]
    assert process.sent_signals == []
    assert writer_thread.join_calls == [5.0]
    assert recorder._process is None
    assert recorder._current_path is None
    assert recorder._latest_frame is None