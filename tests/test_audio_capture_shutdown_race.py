"""Audio capture shutdown race — regression tests.

stop() (and the live source-switch path) used to call
_close_stream_safely() unconditionally after joining the reader thread,
even when the join timed out and the reader thread was still alive —
almost certainly still blocked inside stream.read() on that exact stream
object. Closing/stopping a PortAudio/ALSA stream while another thread's
blocking read is still in flight on it is a real crash risk (this is what
produced "PaAlsaStreamComponent_RegisterChannels failed" /
"PaAlsaStream_SetUpBuffers failed" and occasional segfaults on quit).

_stop_reader_thread() now aborts the stream before joining and returns
whether the reader actually exited; callers only close the stream when it
did. When it didn't, the stream/thread are abandoned (the reader thread is
daemon, so it can't block process exit) instead of racing a close.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import patch

import numpy as np

from unicornviz.audio.capture import AudioCapture


def _make_capture(**kwargs) -> AudioCapture:
    return AudioCapture(**kwargs)


class _RecordingStream:
    def __init__(self) -> None:
        self.abort_called = False
        self.stop_called = False
        self.close_called = False

    def start(self) -> None:
        pass

    def abort(self) -> None:
        self.abort_called = True

    def stop(self) -> None:
        self.stop_called = True

    def close(self) -> None:
        self.close_called = True


def _fake_stream_factory(blocksize: int):
    """A stream whose read() returns immediately (reader exits promptly)."""
    class _FastStream(_RecordingStream):
        def read(self, frames: int):
            return np.zeros((frames, 1), dtype=np.float32), False
    return _FastStream()


# --------------------------------------------------------------------------- #
# _stop_reader_thread: abort-before-join, return value reflects real exit
# --------------------------------------------------------------------------- #

def test_stop_reader_thread_aborts_stream_before_joining() -> None:
    cap = _make_capture()
    stream = _RecordingStream()
    done = threading.Event()
    cap._reader_thread = threading.Thread(target=done.wait, daemon=True)
    cap._reader_thread.start()
    done.set()  # let it exit immediately

    exited = cap._stop_reader_thread(stream)

    assert stream.abort_called is True
    assert exited is True
    assert cap._reader_thread is None


def test_stop_reader_thread_returns_false_when_thread_hangs() -> None:
    cap = _make_capture()
    stream = _RecordingStream()
    never = threading.Event()  # never set — simulates a stuck blocking read()
    cap._reader_thread = threading.Thread(target=never.wait, daemon=True)
    cap._reader_thread.start()

    try:
        with patch('unicornviz.audio.capture._CLOSE_STREAM_TIMEOUT_S', 0.05):
            exited = cap._stop_reader_thread(stream)
        assert stream.abort_called is True
        assert exited is False
    finally:
        never.set()


# --------------------------------------------------------------------------- #
# stop(): only closes the stream when the reader actually exited
# --------------------------------------------------------------------------- #

def test_stop_closes_stream_when_reader_exits_cleanly() -> None:
    cap = _make_capture(block_size=256)
    stream = _fake_stream_factory(256)
    cap._stream = stream
    cap._active = True
    cap._stop_event.clear()
    done = threading.Event()
    cap._reader_thread = threading.Thread(target=done.wait, daemon=True)
    cap._reader_thread.start()
    done.set()

    cap.stop()

    deadline = time.monotonic() + 1.0
    while not stream.close_called and time.monotonic() < deadline:
        time.sleep(0.01)  # _close_stream_safely runs in its own worker thread
    assert stream.close_called is True
    assert cap._reader_thread is None


def test_stop_does_not_close_stream_when_reader_thread_hangs() -> None:
    """The exact race that used to crash on quit: must not touch the stream
    from the main thread while the reader may still be inside read()."""
    cap = _make_capture(block_size=256)
    stream = _RecordingStream()
    cap._stream = stream
    cap._active = True
    cap._stop_event.clear()
    never = threading.Event()
    cap._reader_thread = threading.Thread(target=never.wait, daemon=True)
    cap._reader_thread.start()

    try:
        with patch('unicornviz.audio.capture._CLOSE_STREAM_TIMEOUT_S', 0.05):
            cap.stop()
        # abort() is still attempted (best-effort unblock)...
        assert stream.abort_called is True
        # ...but stop()/close() must never race the still-alive reader thread.
        assert stream.stop_called is False
        assert stream.close_called is False
    finally:
        never.set()


# --------------------------------------------------------------------------- #
# _switch_to_candidate_index: same abandon-don't-race behavior on live switch
# --------------------------------------------------------------------------- #

def test_switch_candidate_does_not_close_old_stream_when_reader_hangs() -> None:
    cap = _make_capture(block_size=256)
    old_stream = _RecordingStream()
    cap._stream = old_stream
    cap._active = True
    cap._stop_event.clear()
    cap._candidate_devices = [None, 1]
    cap._candidate_index = 0
    never = threading.Event()
    cap._reader_thread = threading.Thread(target=never.wait, daemon=True)
    cap._reader_thread.start()

    new_stream = _fake_stream_factory(256)

    try:
        with patch('unicornviz.audio.capture._CLOSE_STREAM_TIMEOUT_S', 0.05), \
             patch('unicornviz.audio.capture._SD_AVAILABLE', True), \
             patch('unicornviz.audio.capture.sd') as mock_sd:
            mock_sd.InputStream.return_value = new_stream
            mock_sd.query_devices.return_value = {
                'default_samplerate': 48000,
                'max_input_channels': 1,
                'hostapi': 0,
                'name': 'test-device',
            }
            mock_sd.query_hostapis.return_value = [{'name': 'PulseAudio'}]

            cap._switch_to_candidate_index(1)

        assert old_stream.stop_called is False
        assert old_stream.close_called is False
        # The switch still proceeds onto the new device rather than wedging.
        assert cap._stream is new_stream
    finally:
        never.set()
        # _switch_to_candidate_index's _open_stream() started a REAL
        # _blocking_reader_worker thread against new_stream. Its read() has
        # no delay, so a tight while-not-stop_event loop spins a CPU core at
        # ~100% for the rest of this pytest process if left running — stop()
        # sets _stop_event and joins it (new_stream.read() returns instantly,
        # so this is fast, not a repeat of the hang under test).
        cap.stop()
