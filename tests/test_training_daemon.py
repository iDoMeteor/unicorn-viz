"""Regression tests for tools/training_daemon.py's --source selection.

2026-08-07: the daemon gained --source {spotify,dj-mixer,media} so it can
drive dj-mixer-01/media-01 headlessly instead of only Spotify. These tests
cover the pure, subprocess-free pieces: argparse-time validation
(_validate_source_args) and command/env construction (_unicornviz_env,
_start_unicornviz's cmd list via a monkeypatched _start).
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'training-kit-01' / 'tools' / 'training_daemon.py'
_SPEC = importlib.util.spec_from_file_location('training_daemon', _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

_validate_source_args = _MOD._validate_source_args
_unicornviz_env = _MOD._unicornviz_env
_start_unicornviz = _MOD._start_unicornviz


def _args(**overrides) -> argparse.Namespace:
    base = dict(source='spotify', playlist_name='', source_dir=None)
    base.update(overrides)
    return argparse.Namespace(**base)


# ---------------------------------------------------------------------------
# _validate_source_args
# ---------------------------------------------------------------------------

def test_spotify_source_needs_neither_playlist_name_nor_source_dir() -> None:
    _validate_source_args(_args(source='spotify'))  # must not raise


def test_dj_mixer_source_requires_playlist_name() -> None:
    with pytest.raises(SystemExit):
        _validate_source_args(_args(source='dj-mixer', playlist_name='', source_dir=Path('/music')))


def test_dj_mixer_source_requires_source_dir() -> None:
    with pytest.raises(SystemExit):
        _validate_source_args(_args(source='dj-mixer', playlist_name='Set', source_dir=None))


def test_dj_mixer_source_passes_with_both() -> None:
    _validate_source_args(_args(source='dj-mixer', playlist_name='Set', source_dir=Path('/music')))


def test_media_source_requires_playlist_name_and_source_dir() -> None:
    with pytest.raises(SystemExit):
        _validate_source_args(_args(source='media', playlist_name='', source_dir=None))
    _validate_source_args(_args(source='media', playlist_name='Run', source_dir=Path('/music')))


# ---------------------------------------------------------------------------
# _unicornviz_env
# ---------------------------------------------------------------------------

def test_env_sets_pulse_sink_only_for_media_source() -> None:
    spotify_env = _unicornviz_env(':99', 'spotify', 'unicorn-training')
    dj_mixer_env = _unicornviz_env(':99', 'dj-mixer', 'unicorn-training')
    media_env = _unicornviz_env(':99', 'media', 'unicorn-training')

    assert 'PULSE_SINK' not in spotify_env
    assert 'PULSE_SINK' not in dj_mixer_env
    assert media_env['PULSE_SINK'] == 'unicorn-training'


def test_env_always_sets_display_and_software_gl() -> None:
    env = _unicornviz_env(':100', 'spotify', 'unicorn-training')
    assert env['DISPLAY'] == ':100'
    assert env['LIBGL_ALWAYS_SOFTWARE'] == '1'
    assert env['GALLIUM_DRIVER'] == 'llvmpipe'


# ---------------------------------------------------------------------------
# _start_unicornviz command construction
# ---------------------------------------------------------------------------

def _capture_start(monkeypatch):
    calls = []

    def _fake_start(args, *, env=None, cwd=None):
        calls.append({'args': args, 'env': env, 'cwd': cwd})
        return object()

    monkeypatch.setattr(_MOD, '_start', _fake_start)
    monkeypatch.setattr(_MOD, '_require', lambda cmd: cmd)
    return calls


def test_spotify_source_adds_no_extra_flags(monkeypatch) -> None:
    calls = _capture_start(monkeypatch)

    _start_unicornviz(Path('/app'), ':99', 'unicorn-training', False, 'spotify')

    cmd = calls[0]['args']
    assert '--dj-mixer-source' not in cmd
    assert '--media-source' not in cmd


def test_dj_mixer_source_passes_the_right_flags(monkeypatch) -> None:
    calls = _capture_start(monkeypatch)

    _start_unicornviz(
        Path('/app'), ':99', 'unicorn-training', False,
        'dj-mixer', 'crossfade', Path('/music/crate'),
    )

    cmd = calls[0]['args']
    assert '--dj-mixer-source' in cmd
    idx = cmd.index('--dj-mixer-autoplay-mode')
    assert cmd[idx + 1] == 'crossfade'
    idx = cmd.index('--dj-mixer-music-dir')
    assert cmd[idx + 1] == '/music/crate'
    assert '--media-source' not in cmd
    assert 'PULSE_SINK' not in calls[0]['env']


def test_media_source_passes_the_right_flags_and_pulse_sink(monkeypatch) -> None:
    calls = _capture_start(monkeypatch)

    _start_unicornviz(
        Path('/app'), ':99', 'unicorn-training', False,
        'media', 'cut', Path('/music/library'),
    )

    cmd = calls[0]['args']
    assert '--media-source' in cmd
    idx = cmd.index('--media-dir')
    assert cmd[idx + 1] == '/music/library'
    assert '--dj-mixer-source' not in cmd
    assert calls[0]['env']['PULSE_SINK'] == 'unicorn-training'


def test_windowed_flag_still_respected_for_all_sources(monkeypatch) -> None:
    calls = _capture_start(monkeypatch)

    _start_unicornviz(Path('/app'), ':99', 'unicorn-training', True, 'spotify')

    assert '--windowed' in calls[0]['args']
    assert '--fullscreen' not in calls[0]['args']
