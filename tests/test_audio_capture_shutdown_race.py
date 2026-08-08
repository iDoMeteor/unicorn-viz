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
did. On shutdown, a stream whose reader is still alive is abandoned (the
reader thread is daemon, so it can't block process exit) instead of racing
a close.

The live source-switch path goes further and **refuses the switch**
outright in that case.  Abandoning the old stream and opening a new one
anyway looked survivable but was not: the reader may still be inside
stream.read(), and replacing the stream underneath it corrupts the heap.
That lands as `Fatal Python error: Aborted` at the next allocation, with
no exception to catch and no clue where it came from.
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
        self.read_available = 1 << 30  # always "ready" for any real reader loop

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
# _blocking_reader_worker: polls read_available instead of blocking in read()
#
# This is the actual root cause behind the original bug: stream.abort() does
# not reliably unblock an in-flight blocking stream.read() on this ALSA
# hostapi, so the old "while not stop: stream.read(blocksize)" loop could get
# stuck inside PortAudio for an unbounded time after shutdown asked it to
# stop. sounddevice only blocks inside read() when fewer frames than
# requested are currently available, so polling read_available first (and
# only calling read() once a full block is ready) bounds the reader's
# unresponsive window to _READER_POLL_INTERVAL_S regardless of whether the
# audio source ever produces data.
# --------------------------------------------------------------------------- #

def test_reader_never_calls_read_when_data_is_not_available() -> None:
    cap = _make_capture(block_size=256)

    class _NeverReadyStream(_RecordingStream):
        def __init__(self) -> None:
            super().__init__()
            self.read_available = 0  # never enough frames
            self.read_call_count = 0

        def read(self, frames: int):
            self.read_call_count += 1
            return np.zeros((frames, 1), dtype=np.float32), False

    stream = _NeverReadyStream()
    cap._stream = stream
    cap._active = True
    cap._stop_event.clear()

    t = threading.Thread(target=cap._blocking_reader_worker, daemon=True)
    t.start()
    time.sleep(0.05)  # several poll intervals' worth of time
    cap._stop_event.set()
    t.join(timeout=1.0)

    assert not t.is_alive()
    assert stream.read_call_count == 0  # polled read_available, never blocked in read()


def test_reader_exits_promptly_even_when_stream_never_has_data() -> None:
    """The exact scenario behind the original bug: a stream that never
    produces data used to leave the reader thread blocked in stream.read()
    indefinitely. It must now exit within a small bounded time instead."""
    cap = _make_capture(block_size=256)

    class _NeverReadyStream(_RecordingStream):
        def __init__(self) -> None:
            super().__init__()
            self.read_available = 0

        def read(self, frames: int):
            raise AssertionError('read() must not be called when data is unavailable')

    cap._stream = _NeverReadyStream()
    cap._active = True
    cap._stop_event.clear()

    t = threading.Thread(target=cap._blocking_reader_worker, daemon=True)
    t.start()
    time.sleep(0.02)
    cap._stop_event.set()

    start = time.monotonic()
    t.join(timeout=1.0)
    elapsed = time.monotonic() - start

    assert not t.is_alive()
    assert elapsed < 0.5, f'reader took {elapsed:.2f}s to exit — should be near-instant'


def test_reader_reads_once_enough_frames_are_available() -> None:
    """Once read_available reports a full block, the reader still reads and
    publishes it normally (the polling change doesn't break normal capture)."""
    cap = _make_capture(block_size=256)

    class _EventuallyReadyStream(_RecordingStream):
        def __init__(self) -> None:
            super().__init__()
            self.read_available = 0

        def read(self, frames: int):
            return np.full((frames, 1), 0.5, dtype=np.float32), False

    stream = _EventuallyReadyStream()
    cap._stream = stream
    cap._active = True
    cap._stop_event.clear()

    t = threading.Thread(target=cap._blocking_reader_worker, daemon=True)
    t.start()
    time.sleep(0.03)  # let it poll a few times while not ready
    stream.read_available = 256  # now a full block is available
    deadline = time.monotonic() + 1.0
    while cap.block_seq < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    cap._stop_event.set()
    t.join(timeout=1.0)

    assert cap.block_seq >= 1
    assert not t.is_alive()


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

def test_switch_candidate_refused_when_reader_hangs() -> None:
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
        # The switch is REFUSED and the old stream stays in place.
        #
        # This previously proceeded onto the new device on the reasoning
        # that wedging was worse.  It is not: _stop_reader_thread's contract
        # says the reader may still be inside stream.read(), and replacing
        # the stream underneath it corrupts the heap.  That surfaces as
        # `Fatal Python error: Aborted` from whatever allocates next — no
        # exception, no traceback, the whole app gone mid-set.  Keeping the
        # current source is strictly better than losing the process.
        assert cap._stream is old_stream
    finally:
        never.set()
        cap.stop()
