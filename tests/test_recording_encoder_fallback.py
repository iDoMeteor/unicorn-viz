"""Recorder: probe-based software encoder and audio fallback (core item R2).

Fedora's ``ffmpeg-free`` has no libx264 (patents) and no fdk-aac; only the full
ffmpeg from RPM Fusion does.  The recorder used to fall back to libx264
unconditionally, so on a stock box with no working hardware encoder recording
simply failed.  ``codec = "auto"`` now walks libx264 -> libopenh264 -> mpeg4
with real test encodes, and the audio encoder falls back from aac the same
way.  The ffmpeg is faked: a probe "works" when its codec is in ``WORKING``.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

import unicornviz.recording as rec_mod
from unicornviz.config import Config
from unicornviz.recording import NoVideoEncoderError, Recorder

FULL = {'libx264', 'libopenh264', 'mpeg4', 'aac', 'libopus', 'libmp3lame', 'ac3'}
FFMPEG_FREE_OPENH264 = {'libopenh264', 'mpeg4', 'aac', 'libopus', 'ac3'}
FFMPEG_FREE_NO_H264 = {'mpeg4', 'aac', 'ac3'}


class _Proc:
    def __init__(self, ok: bool) -> None:
        self.returncode = 0 if ok else 1
        self.stderr = b'' if ok else b'Unknown encoder'


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    """Returns a setter for the working encoder set; counts probe launches."""
    state = {'working': set(FULL), 'runs': []}

    def fake_run(cmd, **_kw):
        codec = cmd[cmd.index('-c:v') + 1] if '-c:v' in cmd else cmd[cmd.index('-c:a') + 1]
        state['runs'].append(codec)
        return _Proc(codec in state['working'])

    monkeypatch.setattr(rec_mod.subprocess, 'run', fake_run)
    monkeypatch.setattr(rec_mod, '_sw_video_cache', {})
    monkeypatch.setattr(rec_mod, '_sw_audio_cache', {})
    monkeypatch.setattr(rec_mod, '_probe_hw_encoder', lambda _p: None)   # isolate the software chain
    return state


def _recorder(**over) -> Recorder:
    r = Recorder(Config(Path('tests') / '_missing_config_for_tests.toml'), 1280, 720)
    r._codec = 'auto'
    r._capture_audio = False
    for key, value in over.items():
        setattr(r, f'_{key}', value)
    return r


def _cmd(r: Recorder) -> list[str]:
    return r._build_command(Path('/tmp/out.mp4'))


def test_full_ffmpeg_uses_libx264_with_crf_and_preset(fake_ffmpeg) -> None:
    cmd = _cmd(_recorder())
    assert cmd[cmd.index('-c:v') + 1] == 'libx264'
    assert '-crf' in cmd and '-preset' in cmd


def test_ffmpeg_free_with_openh264_uses_a_bitrate_not_crf(fake_ffmpeg, caplog) -> None:
    fake_ffmpeg['working'] = set(FFMPEG_FREE_OPENH264)
    with caplog.at_level(logging.INFO, logger='unicornviz.recording'):
        cmd = _cmd(_recorder())
    assert cmd[cmd.index('-c:v') + 1] == 'libopenh264'
    assert '-crf' not in cmd and '-preset' not in cmd      # libx264 concepts
    assert int(cmd[cmd.index('-b:v') + 1]) > 1_000_000
    assert any('libx264 is not available' in r.getMessage() and 'libopenh264' in r.getMessage()
               and r.levelno == logging.WARNING for r in caplog.records)


def test_no_h264_encoder_falls_back_to_mpeg4_and_says_so(fake_ffmpeg, caplog) -> None:
    fake_ffmpeg['working'] = set(FFMPEG_FREE_NO_H264)
    with caplog.at_level(logging.INFO, logger='unicornviz.recording'):
        cmd = _cmd(_recorder())
    assert cmd[cmd.index('-c:v') + 1] == 'mpeg4'
    assert 1 <= int(cmd[cmd.index('-q:v') + 1]) <= 31
    assert '-crf' not in cmd and '-b:v' not in cmd
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any('no working H.264 encoder' in m and 'RPM Fusion' in m for m in msgs)


def test_nothing_usable_is_a_clear_failure_not_a_spawn_of_a_doomed_ffmpeg(
        fake_ffmpeg, monkeypatch, caplog) -> None:
    fake_ffmpeg['working'] = set()
    r = _recorder(enabled=True)
    with pytest.raises(NoVideoEncoderError):
        r._resolve_encoder()

    def no_popen(*_a, **_k):
        raise AssertionError('ffmpeg must not be spawned without an encoder')
    monkeypatch.setattr(rec_mod.subprocess, 'Popen', no_popen)
    with caplog.at_level(logging.ERROR, logger='unicornviz.recording'):
        assert r.start() is False
    assert 'no usable video encoder' in r._last_error
    assert any(rec.levelno == logging.ERROR for rec in caplog.records)


def test_the_probe_runs_once_per_ffmpeg(fake_ffmpeg) -> None:
    r = _recorder()
    _cmd(r)
    n = len(fake_ffmpeg['runs'])
    _cmd(r)
    _cmd(_recorder())
    assert len(fake_ffmpeg['runs']) == n


def test_hardware_wins_and_skips_the_software_probe(fake_ffmpeg, monkeypatch) -> None:
    monkeypatch.setattr(rec_mod, '_probe_hw_encoder',
                        lambda _p: ('h264_nvenc', [], '', '-cq'))
    cmd = _cmd(_recorder())
    assert cmd[cmd.index('-c:v') + 1] == 'h264_nvenc' and '-cq' in cmd
    assert fake_ffmpeg['runs'] == []


@pytest.mark.parametrize(('working', 'expected'), [
    (FULL, 'aac'),
    ({'libopus', 'ac3'}, 'libopus'),
    ({'libmp3lame', 'ac3'}, 'libmp3lame'),
    ({'ac3'}, 'ac3'),
])
def test_audio_falls_back_down_the_chain(fake_ffmpeg, working, expected) -> None:
    fake_ffmpeg['working'] = set(working)
    assert _recorder()._resolve_audio_codec() == expected


def test_a_configured_audio_codec_is_tried_first(fake_ffmpeg) -> None:
    assert _recorder(audio_codec='libopus')._resolve_audio_codec() == 'libopus'


def test_no_working_audio_encoder_records_video_only(fake_ffmpeg, monkeypatch) -> None:
    fake_ffmpeg['working'] = {'libx264'}
    monkeypatch.setattr(Recorder, '_resolve_audio_input', lambda self: ('pulse', 'default'))
    cmd = _cmd(_recorder(capture_audio=True))
    assert '-an' in cmd and '-c:a' not in cmd and 'pulse' not in cmd


def test_audio_codec_flows_into_the_command(fake_ffmpeg, monkeypatch) -> None:
    fake_ffmpeg['working'] = {'libx264', 'libopus'}
    monkeypatch.setattr(Recorder, '_resolve_audio_input', lambda self: ('pulse', 'default'))
    cmd = _cmd(_recorder(capture_audio=True))
    assert cmd[cmd.index('-c:a') + 1] == 'libopus'


def test_pinned_codecs_keep_their_own_quality_flag(fake_ffmpeg) -> None:
    assert _recorder(codec='libopenh264')._resolve_encoder()[3] == '-b:v'
    assert _recorder(codec='mpeg4')._resolve_encoder()[3] == '-q:v'
    assert _recorder(codec='libx264')._resolve_encoder()[3] == '-crf'
    codec, pre, filt, flag = _recorder(codec='h264_vaapi')._resolve_encoder()
    assert (codec, flag) == ('h264_vaapi', '-qp') and pre[0] == '-vaapi_device' and filt


def test_bitrate_and_qscale_mappings_are_sane() -> None:
    hi = rec_mod._bitrate_for(1920, 1080, 60, 18)
    lo = rec_mod._bitrate_for(1920, 1080, 60, 28)
    assert 8_000_000 < hi < 25_000_000 and lo < hi / 2          # ~6 CRF steps halve it
    assert rec_mod._bitrate_for(64, 48, 30, 18) == 500_000      # clamped up
    assert rec_mod._bitrate_for(7680, 4320, 120, 0) == 60_000_000   # clamped down
    assert rec_mod._qscale_for(18) == 3 and rec_mod._qscale_for(0) == 1 and rec_mod._qscale_for(99) == 16
    assert rec_mod._qscale_for(500) == 31


def test_software_retry_does_not_recurse_for_any_software_encoder(fake_ffmpeg) -> None:
    for codec in rec_mod._SW_VIDEO_CODECS:
        r = _recorder()
        r._active_codec = codec
        assert r._retry_in_software() is False
