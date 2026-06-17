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


# ---------------------------------------------------------------------------
# AudioManager — FFT dedup
# ---------------------------------------------------------------------------

class TestFFTDedup:
    """get_audio_data() skips the analyzer when block_seq is unchanged."""

    def _manager_with_mock_capture(self, initial_seq: int = 0):
        cfg = Config()
        with patch('unicornviz.audio.manager.AudioCapture') as MockCapture, \
             patch('unicornviz.audio.manager.Analyzer') as MockAnalyzer:
            mock_cap_instance = MagicMock()
            type(mock_cap_instance).block_seq = PropertyMock(return_value=initial_seq)
            mock_cap_instance.get_block.return_value = np.zeros(1024, dtype=np.float32)
            MockCapture.return_value = mock_cap_instance

            mock_analyzer = MagicMock()
            mock_analyzer.last_raw_rms = 0.0
            MockAnalyzer.return_value = mock_analyzer

            mgr = AudioManager(cfg)
            mgr._capture = mock_cap_instance
            mgr._analyzer = mock_analyzer
        return mgr, mock_cap_instance, mock_analyzer

    def test_analyzer_called_on_new_block(self):
        mgr, mock_cap, mock_analyzer = self._manager_with_mock_capture(initial_seq=0)
        type(mock_cap).block_seq = PropertyMock(return_value=1)
        mgr.get_audio_data()
        mock_analyzer.process.assert_called_once()

    def test_analyzer_skipped_on_same_block(self):
        mgr, mock_cap, mock_analyzer = self._manager_with_mock_capture(initial_seq=0)
        # First call — new block (seq was -1, now 0)
        mgr.get_audio_data()
        call_count_after_first = mock_analyzer.process.call_count

        # Second call — same seq (0 again) → should NOT call analyzer
        mgr.get_audio_data()
        assert mock_analyzer.process.call_count == call_count_after_first, \
            'Analyzer must not be called on duplicate blocks'

    def test_reactivity_applied_once_not_twice(self):
        """Reactivity scaling must not compound across duplicate-block frames."""
        cfg = Config()
        with patch('unicornviz.audio.manager.AudioCapture') as MockCapture, \
             patch('unicornviz.audio.manager.Analyzer') as MockAnalyzer:
            mock_cap = MagicMock()
            seq = [0]
            type(mock_cap).block_seq = PropertyMock(side_effect=lambda: seq[0])
            mock_cap.get_block.return_value = np.zeros(1024, dtype=np.float32)
            MockCapture.return_value = mock_cap

            from unicornviz.effects.base import AudioData
            raw_data = AudioData()
            raw_data.bass = 0.5
            raw_data.mid = 0.4
            raw_data.treble = 0.3

            mock_analyzer = MagicMock()
            mock_analyzer.last_raw_rms = 0.0

            def _fake_process(block, out=None):
                if out is not None:
                    out.bass = raw_data.bass
                    out.mid = raw_data.mid
                    out.treble = raw_data.treble
                    out.fft[:] = 0.0
                    out.waveform[:] = 0.0
                    out.beat = 0.0
                    out.bpm = 0.0
                    out.bass_n = 0.5
                    out.mid_n = 0.4
                    out.treble_n = 0.3
                    out.bass_flux = 0.0
                    out.mid_flux = 0.0

            mock_analyzer.process.side_effect = _fake_process
            MockAnalyzer.return_value = mock_analyzer

            mgr = AudioManager(cfg)
            mgr._capture = mock_cap
            mgr._analyzer = mock_analyzer
            mgr.set_reactivity(2.0)

            # Frame 1: new block (seq 0 → seq 0, _last_analyzed_block_seq is -1)
            data1 = mgr.get_audio_data()
            bass_after_frame1 = data1.bass  # should be 0.5 * 2.0 = 1.0 (clamped)

            # Frame 2: same block seq — reactivity must NOT be re-applied
            data2 = mgr.get_audio_data()
            assert data2.bass == bass_after_frame1, \
                f'bass changed on duplicate frame: {bass_after_frame1} -> {data2.bass}'
