"""Regression guard for operator defaults promoted into the code (2026-07).

These settings were baked into ``Config._DEFAULTS`` and removed from
``config.toml``; this pins their effective startup defaults so a future edit
(or a stray revert to config-only values) can't silently regress them.  Loading
``Config`` with a nonexistent path yields the built-in defaults only.
"""
from __future__ import annotations

from pathlib import Path

from unicornviz.config import Config


def _cfg() -> Config:
    return Config(Path('tests') / '_missing_config_for_tests.toml')


def test_demo_defaults_promoted() -> None:
    cfg = _cfg()
    assert int(cfg.get('demo', 'effect_duration')) == 60
    assert cfg.get('demo', 'transition') == 'shuffle'


def test_window_fullscreen_default_true() -> None:
    assert bool(_cfg().get('window', 'fullscreen')) is True


def test_recording_capture_audio_default_true() -> None:
    assert bool(_cfg().get('recording', 'capture_audio')) is True


def test_playlist_start_effect_default() -> None:
    assert _cfg().get('playlist', 'start_effect') == 'Audio Spectrum'


def test_promoted_defaults_survive_deep_merge_with_partial_user_config() -> None:
    # A user config that overrides *other* demo keys must not resurrect the old
    # effect_duration/transition defaults via the merge.
    cfg = Config(
        Path('tests') / '_missing_config_for_tests.toml',
        overrides={'demo': {'auto_advance': False}},
    )
    assert int(cfg.get('demo', 'effect_duration')) == 60
    assert cfg.get('demo', 'transition') == 'shuffle'
    assert bool(cfg.get('demo', 'auto_advance')) is False
