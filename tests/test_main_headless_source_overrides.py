"""Regression tests for --dj-mixer-source/--media-source CLI overrides.

2026-08-07: unicornviz/__main__.py gains CLI flags that force-enable
dj-mixer-01/media-01 and configure them for an unattended run (headless
training daemon), via the existing Config(overrides=...) mechanism
(config.py:376-384) -- the same shape already used for --record/--no-record
-> [recording] auto_record (see _build_overrides, __main__.py:146-149).
"""
from __future__ import annotations

from unicornviz import __main__ as main_module

_build_parser = main_module._build_parser
_build_overrides = main_module._build_overrides


def _parse(argv: list[str]):
    return _build_parser().parse_args(argv)


def test_dj_mixer_source_enables_and_arms_autoplay() -> None:
    args = _parse(['--dj-mixer-source', '--audio-device', 'unicorn-training'])

    overrides = _build_overrides(args)

    assert overrides['dj_mixer']['enabled'] is True
    assert overrides['dj_mixer']['start_enabled'] is True
    assert overrides['dj_mixer']['autoplay_boot_mode'] == 'cut'
    assert overrides['dj_mixer']['output_device'] == 'unicorn-training'


def test_dj_mixer_output_device_overrides_audio_device_default() -> None:
    args = _parse([
        '--dj-mixer-source', '--audio-device', 'unicorn-training',
        '--dj-mixer-output-device', 'DDJ-REV1',
    ])

    overrides = _build_overrides(args)

    assert overrides['dj_mixer']['output_device'] == 'DDJ-REV1'


def test_dj_mixer_autoplay_mode_is_configurable() -> None:
    args = _parse(['--dj-mixer-source', '--dj-mixer-autoplay-mode', 'crossfade'])

    overrides = _build_overrides(args)

    assert overrides['dj_mixer']['autoplay_boot_mode'] == 'crossfade'


def test_dj_mixer_music_dir_passes_through() -> None:
    args = _parse(['--dj-mixer-source', '--dj-mixer-music-dir', '/music/crate'])

    overrides = _build_overrides(args)

    assert overrides['dj_mixer']['music_dir'] == '/music/crate'


def test_dj_mixer_source_absent_produces_no_dj_mixer_overrides() -> None:
    args = _parse([])

    overrides = _build_overrides(args)

    assert 'dj_mixer' not in overrides


def test_media_source_enables_and_auto_plays() -> None:
    args = _parse(['--media-source', '--media-dir', '/music/library'])

    overrides = _build_overrides(args)

    assert overrides['media']['enabled'] is True
    assert overrides['media']['auto_play'] is True
    assert overrides['media']['media_dir'] == '/music/library'


def test_media_source_absent_produces_no_media_overrides() -> None:
    args = _parse([])

    overrides = _build_overrides(args)

    assert 'media' not in overrides


def test_both_sources_can_be_forced_independently() -> None:
    """Not a realistic training-daemon invocation (only one --source is ever
    selected), but the CLI itself doesn't forbid it -- confirms the two
    override blocks don't interfere with each other."""
    args = _parse(['--dj-mixer-source', '--media-source'])

    overrides = _build_overrides(args)

    assert overrides['dj_mixer']['enabled'] is True
    assert overrides['media']['enabled'] is True
