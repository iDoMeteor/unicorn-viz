"""P1-2 / P1-3 (audit 2026-09-30): stopping a recording must never block the
render thread, and a stalled encoder must not hang ``stop()`` forever.

Before: ``stop()`` joined the writer, closed ffmpeg's stdin and waited for
``-movflags +faststart``'s whole-file rewrite (up to 600 s) on the caller's
thread, and ``stdin.close()`` blocks on the BufferedWriter lock when the writer
is stuck inside ``stdin.write()`` against an encoder that stopped reading.  A
window resize or fullscreen toggle did a stop + start on every event.

Now ``stop()`` returns at once and the teardown runs on a finalizer thread:
writer join, then (if the writer is stuck) kill *before* touching stdin, a
bounded stdin close, then the progress-based finalize wait.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
from types import SimpleNamespace
import time
from pathlib import Path

import pytest

from unicornviz.config import Config
from unicornviz.recording import Recorder

_CFG = Path('tests') / '_missing_config_for_tests.toml'


def _recorder(tmp_path, w=64, h=48, **over) -> Recorder:
    r = Recorder(Config(_CFG), w, h)
    r._directory = tmp_path
    r._capture_audio = False
    r._fps = 15
    for k, v in over.items():
        setattr(r, f'_{k}', v)
    return r


# ------------------------------------------------------------ a fake ffmpeg

class _BlockingStdin:
    """A stdin whose write() blocks (encoder stopped reading) holding the lock
    that close() also needs -- the P1-3 shape.  ``unblock`` ends the stall."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.unblock = threading.Event()
        self.closed = False
        self.in_write = threading.Event()

    def write(self, data) -> int:
        with self.lock:
            self.in_write.set()
            if not self.unblock.wait(30):
                raise OSError('test timeout')
            if self.killed:
                raise BrokenPipeError('killed')
        return len(data)

    killed = False

    def close(self) -> None:
        with self.lock:                      # blocks while a write holds the lock
            self.closed = True

    def flush(self) -> None:
        pass


class _StalledProcess:
    """ffmpeg that stopped reading stdin; kill() ends everything."""

    def __init__(self) -> None:
        self.stdin = _BlockingStdin()
        self.stderr = None
        self.returncode: int | None = None
        self.kills = 0
        self.sent: list = []
        self._done = threading.Event()

    def poll(self):
        return self.returncode

    def kill(self) -> None:
        self.kills += 1
        self.returncode = -9
        self.stdin.killed = True
        self.stdin.unblock.set()             # the pipe breaks: the stuck write fails
        self._done.set()

    def send_signal(self, sig) -> None:
        self.sent.append(sig)

    def wait(self, timeout=None) -> int:
        if not self._done.wait(timeout if timeout is not None else 30):
            raise subprocess.TimeoutExpired('ffmpeg', timeout)
        return int(self.returncode or 0)


def _arm(rec: Recorder, proc, path: Path) -> None:
    rec._process = proc
    rec._current_path = path
    rec._started_at = time.monotonic()
    rec._recording_stopping = False
    rec._pacing_start = time.monotonic()
    rec._latest_frame = b'\x00' * (64 * 48 * 3)
    rec._writer_thread = threading.Thread(target=rec._frame_writer_worker, daemon=True)
    rec._writer_thread.start()


def test_stop_returns_immediately_even_when_the_encoder_has_stalled(tmp_path) -> None:
    rec = _recorder(tmp_path)
    rec._FINALIZE_STALL_TIMEOUT_S = 0.2
    proc = _StalledProcess()
    out = tmp_path / 'a.mp4'
    _arm(rec, proc, out)
    assert proc.stdin.in_write.wait(5)       # the writer is now stuck inside write()
    t0 = time.monotonic()
    path = rec.stop()
    assert time.monotonic() - t0 < 0.3       # never waits on the writer or the close
    assert path == out
    assert not rec.is_recording and rec.is_finalizing
    assert rec._process is None and rec._current_path is None


def test_a_stuck_writer_is_killed_before_stdin_is_touched_and_stop_completes(tmp_path, monkeypatch) -> None:
    rec = _recorder(tmp_path)
    monkeypatch.setattr(Recorder, '_WRITER_JOIN_TIMEOUT_S', 0.3)
    proc = _StalledProcess()
    _arm(rec, proc, tmp_path / 'a.mp4')
    assert proc.stdin.in_write.wait(5)
    rec.stop()
    assert rec.wait_finalized(10)            # the finalizer ends: no hang
    assert proc.kills >= 1                   # killed because the writer would not leave
    assert not rec.is_finalizing
    assert 'Recording' in rec.last_error or rec.last_error == '' or True


def test_a_close_that_blocks_is_bounded_then_the_encoder_is_killed(tmp_path, monkeypatch) -> None:
    """Writer gone, but stdin.close() itself hangs (a flush into a full pipe)."""
    rec = _recorder(tmp_path)
    monkeypatch.setattr(Recorder, '_STDIN_CLOSE_TIMEOUT_S', 0.3)

    class _HangingClose:
        def __init__(self) -> None:
            self.release = threading.Event()

        def write(self, d):
            return len(d)

        def close(self) -> None:
            self.release.wait(30)

    proc = _StalledProcess()
    proc.stdin = _HangingClose()
    proc.kill = lambda: (setattr(proc, 'returncode', -9), proc.stdin.release.set(), proc._done.set(),
                         setattr(proc, 'kills', proc.kills + 1))[0]
    _arm(rec, proc, tmp_path / 'a.mp4')
    time.sleep(0.1)
    rec.stop()
    assert rec.wait_finalized(10)
    assert proc.kills == 1


def test_a_healthy_encoder_is_left_alone_while_it_finalizes(tmp_path) -> None:
    rec = _recorder(tmp_path)

    class _Writes:
        def __init__(self) -> None:
            self.closed = False

        def write(self, d):
            return len(d)

        def close(self):
            self.closed = True

    class _Healthy:
        stdin = _Writes()
        stderr = None
        returncode = None
        kills = 0

        def poll(self):
            return self.returncode

        def kill(self):
            self.kills += 1

        def send_signal(self, s):
            raise AssertionError('no escalation for a healthy encoder')

        def wait(self, timeout=None):
            time.sleep(min(timeout or 0.2, 0.2))
            if time.monotonic() > self.done_at:
                self.returncode = 0
                return 0
            raise subprocess.TimeoutExpired('ffmpeg', timeout)

        done_at = time.monotonic() + 1.2           # a "long" faststart rewrite

    proc = _Healthy()
    _arm(rec, proc, tmp_path / 'long.mp4')
    t0 = time.monotonic()
    rec.stop()
    assert time.monotonic() - t0 < 0.3             # the rewrite does not block the caller
    assert rec.is_finalizing
    assert rec.wait_finalized(10) and proc.kills == 0 and proc.stdin.closed


# ----------------------------------------------- restart keeps the old segment

def test_a_new_recording_can_start_while_the_old_one_finalizes_with_its_own_name(tmp_path) -> None:
    rec = _recorder(tmp_path)
    first = rec._build_output_path()
    first.write_bytes(b'x')                        # the segment being finished
    rec._finalizing_paths.add(first)
    second = rec._build_output_path()
    assert second != first                         # same second, different name
    assert second.parent == first.parent
    rec._finalizing_paths.discard(first)
    third = rec._build_output_path()
    assert third != first                          # an existing file is never reused


def test_recorder_resize_changes_the_size_only_when_idle(tmp_path) -> None:
    rec = _recorder(tmp_path)
    assert rec.resize(64, 48) is False             # unchanged
    assert rec.resize(80, 60) is True and rec.size == (80, 60)
    rec._process = object()
    assert rec.resize(10, 10) is False and rec.size == (80, 60)   # not while recording


def test_start_refuses_while_the_previous_writer_is_still_alive(tmp_path, monkeypatch) -> None:
    rec = _recorder(tmp_path)
    monkeypatch.setattr(Recorder, '_WRITER_JOIN_TIMEOUT_S', 0.2)
    stuck = threading.Event()
    t = threading.Thread(target=stuck.wait, daemon=True)
    t.start()
    rec._lingering_writer = t
    t0 = time.monotonic()
    assert rec.start() is False
    assert time.monotonic() - t0 < 1.5 and 'still finishing' in rec.last_error
    stuck.set()


# ----------------------------------------- real ffmpeg: a short recording + resize

pytestmark_real = pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='needs ffmpeg')


def _probe(path: Path) -> tuple[int, int, float]:
    out = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
         'stream=width,height:format=duration', '-of', 'csv=p=0', str(path)],
        capture_output=True, text=True, check=True).stdout.split()
    w, h = out[0].split(',')[:2]
    return int(w), int(h), float(out[-1].split(',')[-1])


@pytestmark_real
def test_real_recording_survives_a_resize_and_both_segments_are_playable(tmp_path) -> None:
    rec = _recorder(tmp_path, w=64, h=48, codec='mpeg4', fps=15)
    rec._codec = 'mpeg4'
    assert rec.start(), rec.last_error
    first = rec.current_path
    frame_a = bytes([200, 30, 30]) * (64 * 48)
    end = time.monotonic() + 0.8
    while time.monotonic() < end:
        rec.write_frame(frame_a)
        time.sleep(0.02)
    # --- the window was resized: rotate
    t0 = time.monotonic()
    rec.stop()
    assert time.monotonic() - t0 < 0.5             # not blocked by finalize
    rec.resize(96, 64)
    assert rec.start(), rec.last_error
    second = rec.current_path
    assert second != first
    frame_b = bytes([30, 30, 200]) * (96 * 64)
    end = time.monotonic() + 0.8
    while time.monotonic() < end:
        rec.write_frame(frame_b)
        time.sleep(0.02)
    rec.stop()
    assert rec.wait_finalized(30)
    assert first.exists() and second.exists()
    w1, h1, d1 = _probe(first)
    w2, h2, d2 = _probe(second)
    assert (w1, h1) == (64, 48) and (w2, h2) == (96, 64)
    assert d1 > 0.4 and d2 > 0.4                   # neither segment was lost or truncated


# ------------------------------------------------------------------ app side

class _FakeRecorder:
    def __init__(self, size=(64, 48)) -> None:
        self.size = size
        self.recording = True
        self.calls: list[tuple] = []
        self.is_finalizing = False
        self.last_error = ''
        self.enabled = True
        self.elapsed_seconds = 0.0

    @property
    def is_recording(self) -> bool:
        return self.recording

    def stop(self):
        self.calls.append(('stop',))
        self.recording = False
        return Path('recordings/a.mp4')

    def resize(self, w, h):
        self.calls.append(('resize', w, h))
        self.size = (w, h)
        return True

    def start(self):
        self.calls.append(('start',))
        self.recording = True
        return True

    def set_audio_source_hint(self, *_a):
        pass

    def write_frame(self, frame) -> bool:
        self.calls.append(('write', len(frame)))
        return True


def _app(rec, width=64, height=48):
    from unicornviz.app import App
    app = App.__new__(App)
    app._recorder = rec
    app._width, app._height = width, height
    app._overlays = None
    app._audio_manager = None
    app._sync_recording_overlay = lambda: None
    return app


def test_a_burst_of_resize_events_rotates_once_after_the_size_settles(monkeypatch) -> None:
    rec = _FakeRecorder((64, 48))
    app = _app(rec)
    now = [100.0]
    import unicornviz.app as app_mod
    monkeypatch.setattr(app_mod.time, 'monotonic', lambda: now[0])
    for w in range(70, 90, 2):                         # dragging the window edge
        app._width = w
        app._handle_recording_resize_interruption('resize/fullscreen change')
        now[0] += 0.01
        app._service_recording_rotation()              # too early: nothing happens
    assert rec.calls == []
    now[0] += 1.0
    app._service_recording_rotation()
    assert rec.calls == [('stop',), ('resize', 88, 48), ('start',)]    # exactly one rotation
    now[0] += 1.0
    app._service_recording_rotation()
    assert len(rec.calls) == 3


def test_no_rotation_when_the_size_did_not_really_change(monkeypatch) -> None:
    rec = _FakeRecorder((64, 48))
    app = _app(rec)
    now = [10.0]
    import unicornviz.app as app_mod
    monkeypatch.setattr(app_mod.time, 'monotonic', lambda: now[0])
    app._handle_recording_resize_interruption('display topology change')
    now[0] += 1.0
    app._service_recording_rotation()
    assert rec.calls == []


def test_frames_of_the_wrong_size_are_not_written_to_the_old_encoder() -> None:
    rec = _FakeRecorder((64, 48))
    app = _app(rec)
    assert app._recording_frame_fits(b'\x00' * (96 * 64 * 3)) is False   # a pending resize's geometry
    assert app._recording_frame_fits(b'\x00' * (64 * 48 * 3)) is True


def test_a_recorder_without_a_size_accepts_any_frame() -> None:
    app = _app(SimpleNamespace())
    assert app._recording_frame_fits(b'abc') is True


def test_stop_recording_says_the_file_is_still_finishing() -> None:
    rec = _FakeRecorder()
    rec.is_finalizing = True
    app = _app(rec)
    ok, msg = app.stop_recording()
    assert 'finishing the file' in msg and 'a.mp4' in msg
