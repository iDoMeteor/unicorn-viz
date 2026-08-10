"""Zero-frame probe classification (AudioManager).

Guards the diagnostic added 2026-08-09 after a live session drew flat
spectrum bars while the beat tracker still reported a plausible BPM.  The
probe's only job is to answer one question from a running session: when a
published audio snapshot is all zero, was it the silence gate doing that on
purpose, or did a loud block get published as zeros anyway?

These tests pin the three buckets it sorts frames into, because a probe that
mislabels its evidence is worse than no probe.
"""
from __future__ import annotations

import logging

from unicornviz.audio.analyzer import Analyzer
from unicornviz.audio.manager import AudioManager
from unicornviz.effects.base import AudioData

_FLOOR = 0.0060


def _make_manager() -> AudioManager:
    """Build an AudioManager with only the fields the probe touches.

    Avoids AudioManager.__init__ so no capture device is opened.
    """
    mgr = object.__new__(AudioManager)
    mgr._analyzer = Analyzer(fft_bands=512, silence_rms_floor=_FLOOR)
    mgr._last_data_raw = AudioData()
    mgr._publish_seq = 0
    mgr._publish_block_seq = -1
    mgr._publish_rms = 0.0
    mgr._zero_probe_last_publish = -1
    mgr._zero_frames = 0
    mgr._zero_gated = 0
    mgr._zero_anomalous = 0
    mgr._zero_repeat = 0
    mgr._zero_rms_peak = 0.0
    mgr._frames_read = 0
    mgr._zero_probe_next_report_t = 0.0
    mgr._zero_probe_first_anomaly_logged = False
    return mgr


def _silence(data: AudioData) -> None:
    data.bass = 0.0
    data.mid = 0.0
    data.treble = 0.0


def _signal(data: AudioData) -> None:
    data.bass = 0.31
    data.mid = 0.22
    data.treble = 0.14


def test_healthy_frame_is_not_counted_as_zero() -> None:
    mgr = _make_manager()
    _signal(mgr._last_data_raw)
    mgr._observe_zero_frame(publish_seq=1, publish_block_seq=1, publish_rms=0.09)
    assert mgr._frames_read == 1
    assert mgr._zero_frames == 0


def test_quiet_block_is_attributed_to_the_silence_gate() -> None:
    """RMS at or below the floor: the analyzer zeroed it deliberately."""
    mgr = _make_manager()
    _silence(mgr._last_data_raw)
    mgr._observe_zero_frame(publish_seq=1, publish_block_seq=1, publish_rms=_FLOOR / 2.0)
    assert (mgr._zero_gated, mgr._zero_anomalous, mgr._zero_repeat) == (1, 0, 0)


def test_loud_block_published_as_zeros_is_an_anomaly() -> None:
    """The discriminator: fresh snapshot, loud input, zero output."""
    mgr = _make_manager()
    _silence(mgr._last_data_raw)
    mgr._observe_zero_frame(publish_seq=1, publish_block_seq=1, publish_rms=0.0625)
    assert (mgr._zero_gated, mgr._zero_anomalous, mgr._zero_repeat) == (0, 1, 0)
    assert mgr._zero_rms_peak == 0.0625


def test_rereading_the_same_snapshot_is_not_a_new_fault() -> None:
    """60 fps reading ~47 blocks/s re-reads snapshots; that is not a defect."""
    mgr = _make_manager()
    _silence(mgr._last_data_raw)
    for _ in range(3):
        mgr._observe_zero_frame(publish_seq=7, publish_block_seq=7, publish_rms=0.0625)
    # Only the first read of publish 7 is fresh; the rest are repeats.
    assert (mgr._zero_anomalous, mgr._zero_repeat) == (1, 2)


def test_first_anomaly_is_logged_immediately_and_only_once(
    caplog: logging.LogCaptureFixture,
) -> None:
    """The periodic summary can be 30s away; the first anomaly must not wait."""
    mgr = _make_manager()
    _silence(mgr._last_data_raw)
    with caplog.at_level(logging.WARNING, logger='unicornviz.audio.manager'):
        mgr._observe_zero_frame(publish_seq=1, publish_block_seq=1, publish_rms=0.0625)
        mgr._observe_zero_frame(publish_seq=2, publish_block_seq=2, publish_rms=0.0625)
    anomaly_lines = [r for r in caplog.records if 'ANOMALY' in r.message]
    assert len(anomaly_lines) == 1
    assert mgr._zero_anomalous == 2


def test_summary_verdict_names_the_publish_defect_when_any_anomaly_seen(
    caplog: logging.LogCaptureFixture,
) -> None:
    """One anomaly outranks any number of legitimately gated frames."""
    mgr = _make_manager()
    _silence(mgr._last_data_raw)
    mgr._observe_zero_frame(publish_seq=1, publish_block_seq=1, publish_rms=0.001)
    mgr._observe_zero_frame(publish_seq=2, publish_block_seq=2, publish_rms=0.0625)
    with caplog.at_level(logging.WARNING, logger='unicornviz.audio.manager'):
        mgr.log_zero_frame_summary()
    assert 'PUBLISH DEFECT' in caplog.text


def test_summary_verdict_names_the_gate_when_every_zero_was_quiet(
    caplog: logging.LogCaptureFixture,
) -> None:
    mgr = _make_manager()
    _silence(mgr._last_data_raw)
    mgr._observe_zero_frame(publish_seq=1, publish_block_seq=1, publish_rms=0.001)
    with caplog.at_level(logging.WARNING, logger='unicornviz.audio.manager'):
        mgr.log_zero_frame_summary()
    assert 'SILENCE GATE' in caplog.text


def test_summary_is_silent_when_no_zero_frames_occurred(
    caplog: logging.LogCaptureFixture,
) -> None:
    """A healthy session must not emit a probe line at all."""
    mgr = _make_manager()
    _signal(mgr._last_data_raw)
    mgr._observe_zero_frame(publish_seq=1, publish_block_seq=1, publish_rms=0.09)
    with caplog.at_level(logging.WARNING, logger='unicornviz.audio.manager'):
        mgr.log_zero_frame_summary()
    assert caplog.text == ''
