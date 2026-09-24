"""Regression tests for the blocking-read capture thread (P0 audio fix).

Verifies:
- AudioCapture in blocking-read mode (no callback) populates the ring buffer.
- block_seq increments once per new block and is visible to the caller.
- xrun_count starts at 0 and does not go negative.
- AudioManager.get_audio_data() skips the FFT when block_seq is unchanged
  (FFT dedup / anti-double-processing fix).
- Reactivity scaling is applied exactly once per new block (not per frame).
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from unicornviz.audio.capture import AudioCapture
from unicornviz.audio.manager import AudioManager
from unicornviz.config import Config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_capture(**kwargs) -> AudioCapture:
    """Return an AudioCapture with sounddevice stubbed out."""
    return AudioCapture(**kwargs)


def _fake_stream_factory(blocksize: int, channels: int = 1):
    """Return a mock sd.InputStream whose read() delivers sine-wave blocks."""
    t = [0]

    class _FakeStream:
        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def abort(self) -> None:
            pass

        def close(self) -> None:
            pass

        @property
        def read_available(self) -> int:
            return blocksize  # always "ready" — the reader loop never polls/sleeps

        def read(self, frames: int):  # noqa: D401
            phase = np.linspace(t[0], t[0] + 0.1, frames, dtype=np.float32)
            t[0] += 0.1
            data = np.sin(phase * 6.28).reshape(-1, 1)
            return data, False  # (data, overflow)

    return _FakeStream()


# ---------------------------------------------------------------------------
# AudioCapture — blocking reader populates buffer
# ---------------------------------------------------------------------------

class TestBlockingReader:
    """AudioCapture uses blocking-read thread, not callback."""

    def test_block_seq_increments(self):
        """block_seq advances each time a new block is appended."""
        cap = _make_capture(block_size=256)
        blocksize = cap.block_size
        assert blocksize == 256

        fake_stream = _fake_stream_factory(blocksize)

        with patch('unicornviz.audio.capture._SD_AVAILABLE', True), \
             patch('unicornviz.audio.capture.sd') as mock_sd:
            mock_sd.InputStream.return_value = fake_stream
            mock_sd.query_devices.return_value = {
                'default_samplerate': 48000,
                'max_input_channels': 1,
                'hostapi': 0,
                'name': 'test-device',
            }
            mock_sd.query_hostapis.return_value = [{'name': 'PulseAudio'}]

            cap._candidate_devices = [None]
            cap._open_stream(None)

            # Give the reader thread a moment to push at least 3 blocks
            deadline = time.monotonic() + 1.0
            while cap.block_seq < 3 and time.monotonic() < deadline:
                time.sleep(0.01)

            assert cap.block_seq >= 3, 'Reader thread did not advance block_seq'
            cap.stop()

    def test_xrun_count_starts_zero(self):
        cap = _make_capture()
        assert cap.xrun_count == 0

    def test_stop_joins_reader_thread(self):
        """stop() sets the stop event and the reader thread should exit."""
        cap = _make_capture(block_size=256)
        fake_stream = _fake_stream_factory(256)

        with patch('unicornviz.audio.capture._SD_AVAILABLE', True), \
             patch('unicornviz.audio.capture.sd') as mock_sd:
            mock_sd.InputStream.return_value = fake_stream
            mock_sd.query_devices.return_value = {
                'default_samplerate': 48000,
                'max_input_channels': 1,
                'hostapi': 0,
                'name': 'test-device',
            }
            mock_sd.query_hostapis.return_value = [{'name': 'PulseAudio'}]

            cap._candidate_devices = [None]
            cap._open_stream(None)

            assert cap._reader_thread is not None
            assert cap._reader_thread.is_alive()

            cap.stop()

            # After stop, reader_thread reference should be cleared
            assert cap._reader_thread is None
            assert not cap._active

    def test_no_callback_attribute_on_inputstream(self):
        """InputStream must be opened without a callback= argument."""
        cap = _make_capture(block_size=512)
        fake_stream = _fake_stream_factory(512)
        opened_kwargs: dict = {}

        with patch('unicornviz.audio.capture._SD_AVAILABLE', True), \
             patch('unicornviz.audio.capture.sd') as mock_sd:
            def _capture_kwargs(**kwargs):
                opened_kwargs.update(kwargs)
                return fake_stream
            mock_sd.InputStream.side_effect = _capture_kwargs
            mock_sd.query_devices.return_value = {
                'default_samplerate': 48000,
                'max_input_channels': 1,
                'hostapi': 0,
                'name': 'test-device',
            }
            mock_sd.query_hostapis.return_value = [{'name': 'PulseAudio'}]

            cap._candidate_devices = [None]
            cap._open_stream(None)
            cap.stop()

        assert 'callback' not in opened_kwargs, \
            'InputStream must NOT be opened with callback= in blocking-read mode'

    def test_config_driven_blocksize(self):
        """block_size kwarg is respected and stored on the instance."""
        for bs in (512, 1024, 2048):
            cap = _make_capture(block_size=bs)
            assert cap.block_size == bs

    def test_synthetic_burst_has_zero_xruns_and_no_drops(self):
        """Synthetic no-overflow burst yields contiguous blocks with zero xruns.

        This is the audit's xrun stress-regression proof in a deterministic,
        headless form: feed a fixed-size burst through the blocking reader and
        verify every block is captured in order with no overflow flags.
        """
        cap = _make_capture(block_size=64, buffer_seconds=1.0)
        burst_blocks = 40

        class _BurstStream:
            def __init__(self) -> None:
                self.i = 0
                self.read_available = 64  # always "ready"; matches block_size above

            def read(self, frames: int):
                payload = np.full((frames, 1), float(self.i), dtype=np.float32)
                self.i += 1
                if self.i >= burst_blocks:
                    cap._stop_event.set()
                return payload, False

        cap._stream = _BurstStream()
        cap._active = True
        cap._stop_event.clear()

        cap._blocking_reader_worker()

        assert cap.xrun_count == 0
        assert cap.block_seq == burst_blocks

        captured = [int(round(float(b[0])) if len(b) else -1) for b in list(cap._buf)]
        assert captured == list(range(burst_blocks)), (
            'Synthetic burst blocks were dropped or re-ordered; '
            f'captured={captured[:5]}...{captured[-5:]}'
        )

    def test_synthetic_overflow_burst_increments_xrun_counter(self):
        """Overflow flags from stream.read() are accumulated into xrun_count."""
        cap = _make_capture(block_size=128, buffer_seconds=1.0)
        burst_blocks = 12
        overflow_at = {2, 5, 9}

        class _OverflowBurstStream:
            def __init__(self) -> None:
                self.i = 0
                self.read_available = 128  # always "ready"; matches block_size above

            def read(self, frames: int):
                payload = np.zeros((frames, 1), dtype=np.float32)
                overflow = self.i in overflow_at
                self.i += 1
                if self.i >= burst_blocks:
                    cap._stop_event.set()
                return payload, overflow

        cap._stream = _OverflowBurstStream()
        cap._active = True
        cap._stop_event.clear()

        cap._blocking_reader_worker()

        assert cap.block_seq == burst_blocks
        assert cap.xrun_count == len(overflow_at)


# ---------------------------------------------------------------------------
# AudioManager — FFT dedup
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# AudioManager — analysis thread and AudioData publishing
# ---------------------------------------------------------------------------

class TestFFTDedup:
    """Analysis thread processes blocks and publishes to main thread."""

    def _make_manager_with_mock_capture(self):
        """Return an AudioManager where AudioCapture and Analyzer are mocked."""
        cfg = Config()
        with patch('unicornviz.audio.manager.AudioCapture') as MockCapture, \
             patch('unicornviz.audio.manager.Analyzer') as MockAnalyzer:

            mock_cap = MagicMock()
            # Provide the methods the analysis thread needs.
            mock_cap.wait_for_new_block.return_value = True
            mock_cap.get_block_if_new.return_value = (
                np.zeros(1024, dtype=np.float32), 1
            )
            mock_cap.signal_new_block.return_value = None
            mock_cap.maybe_fallback.return_value = None
            mock_cap.active = True
            MockCapture.return_value = mock_cap

            from unicornviz.effects.base import AudioData
            published = AudioData()
            published.bass = 0.4
            published.mid = 0.3
            published.treble = 0.2

            def _fake_process(block, out=None):
                if out is not None:
                    out.bass = published.bass
                    out.mid = published.mid
                    out.treble = published.treble
                    out.fft[:] = 0.0
                    out.waveform[:] = 0.0
                    out.beat = 0.0
                    out.bpm = 0.0
                    out.bass_n = 0.5
                    out.mid_n = 0.4
                    out.treble_n = 0.3
                    out.bass_flux = 0.0
                    out.mid_flux = 0.0

            mock_analyzer = MagicMock()
            mock_analyzer.last_raw_rms = 0.0
            # Read by AudioManager's zero-frame probe on every get_audio_data().
            mock_analyzer.silence_rms_floor = 0.0060
            mock_analyzer.process.side_effect = _fake_process
            mock_analyzer.drain_onsets.return_value = []
            MockAnalyzer.return_value = mock_analyzer

            mgr = AudioManager(cfg)
            mgr._capture = mock_cap
            mgr._analyzer = mock_analyzer

        return mgr, mock_cap, mock_analyzer

    def test_analyzer_called_on_new_block(self):
        """Analysis thread processes blocks; get_audio_data reads from front_buf."""
        mgr, mock_cap, mock_analyzer = self._make_manager_with_mock_capture()

        # Manually publish a value to front_buf simulating what the analysis thread does.
        from unicornviz.effects.base import AudioData
        with mgr._analysis_lock:
            mgr._front_buf.bass = 0.5
            mgr._front_buf.mid = 0.3
            mgr._front_buf.treble = 0.2

        data = mgr.get_audio_data()
        assert data.bass == pytest.approx(0.5, abs=1e-5)

    def test_no_main_thread_fft(self):
        """get_audio_data() must NOT call analyzer.process() (it runs in analysis thread)."""
        mgr, mock_cap, mock_analyzer = self._make_manager_with_mock_capture()

        mgr.get_audio_data()
        mgr.get_audio_data()
        mgr.get_audio_data()

        mock_analyzer.process.assert_not_called()

    def test_reactivity_applied_once_not_twice(self):
        """Reactivity scaling on get_audio_data must not compound across frames."""
        mgr, mock_cap, mock_analyzer = self._make_manager_with_mock_capture()

        with mgr._analysis_lock:
            mgr._front_buf.bass = 0.5
            mgr._front_buf.mid = 0.3
            mgr._front_buf.treble = 0.2

        mgr.set_reactivity(2.0)

        # Frame 1
        data1 = mgr.get_audio_data()
        bass_frame1 = data1.bass  # should be min(1.0, 0.5 * 2.0) = 1.0

        # Frame 2: front_buf hasn't changed — reactivity still reads from front_buf (0.5)
        # and applies 2.0 again, giving the same result.
        data2 = mgr.get_audio_data()
        assert data2.bass == pytest.approx(bass_frame1, abs=1e-5)

    def test_drain_onsets_thread_safe(self):
        """drain_onsets returns pending onsets and clears them atomically."""
        mgr, _, _ = self._make_manager_with_mock_capture()
        from unicornviz.audio.analyzer import OnsetEvent

        # The analysis thread's publish step (an append-only (seq, event) log
        # since 2026-09-24, so it can also be streamed to another process).
        with mgr._analysis_lock:
            for ev in (OnsetEvent(t=1.0, strength=1.5), OnsetEvent(t=2.0, strength=2.0)):
                mgr._onset_total += 1
                mgr._onset_log.append((mgr._onset_total, ev))

        onsets = mgr.drain_onsets()
        assert len(onsets) == 2
        assert onsets[0].t == pytest.approx(1.0)

        # Second drain should be empty.
        onsets2 = mgr.drain_onsets()
        assert len(onsets2) == 0

    def test_drain_onsets_returns_only_new_events_and_survives_a_full_log(self):
        """The cursor hands out each event once, in order, and a consumer that
        fell further behind than the log's length gets the newest events."""
        mgr, _, _ = self._make_manager_with_mock_capture()
        from unicornviz.audio import manager as manager_mod
        from unicornviz.audio.analyzer import OnsetEvent

        def publish(n):
            with mgr._analysis_lock:
                for _ in range(n):
                    mgr._onset_total += 1
                    mgr._onset_log.append(
                        (mgr._onset_total, OnsetEvent(t=float(mgr._onset_total), strength=1.0)))

        publish(3)
        assert [e.t for e in mgr.drain_onsets()] == [1.0, 2.0, 3.0]
        publish(2)
        assert [e.t for e in mgr.drain_onsets()] == [4.0, 5.0]
        publish(manager_mod._ONSET_LOG_LEN + 10)
        got = mgr.drain_onsets()
        assert len(got) == manager_mod._ONSET_LOG_LEN
        assert got[-1].t == float(mgr._onset_total)
        assert mgr.drain_onsets() == []

    def test_the_analysis_thread_ticks_the_fallback_prober(self):
        """...and the analysis thread does, including while the source is
        silent and no blocks arrive -- the case the fallback exists for."""
        import time as _time
        mgr, mock_cap, _ = self._make_manager_with_mock_capture()

        def no_block(timeout_s=0.5):
            _time.sleep(0.005)
            return False
        mock_cap.wait_for_new_block.side_effect = no_block
        worker = threading.Thread(target=mgr._analysis_worker, daemon=True)
        worker.start()
        deadline = _time.monotonic() + 2.0
        while mock_cap.maybe_fallback.call_count < 3 and _time.monotonic() < deadline:
            _time.sleep(0.005)
        mgr._analysis_stop.set()
        worker.join(timeout=2.0)
        assert mock_cap.maybe_fallback.call_count >= 3

    def test_get_audio_data_does_not_run_the_fallback_prober(self):
        """The silence fallback ticks on the analysis thread now; the render
        thread's per-frame read must never reach device probing (the
        2026-09-22 lockup was a device open under exactly this call)."""
        mgr, _, _ = self._make_manager_with_mock_capture()
        calls = []
        mgr._capture.maybe_fallback = lambda: calls.append(1)
        mgr._started = True
        for _ in range(5):
            mgr.get_audio_data()
        assert calls == []
