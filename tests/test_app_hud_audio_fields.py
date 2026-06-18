from __future__ import annotations

from pathlib import Path

from unicornviz.config import Config
from unicornviz.app import App
from unicornviz.effects.base import AudioData


def _default_cfg() -> Config:
    return Config(Path('tests') / '_missing_config_for_tests.toml')


def test_hud_audio_state_fields_prefers_raw_audio_snapshot() -> None:
    app = App(_default_cfg())

    cooked = AudioData()
    cooked.bass = 0.11
    cooked.mid = 0.22
    cooked.treble = 0.33
    cooked.bass_n = 0.44
    cooked.mid_n = 0.55
    cooked.treble_n = 0.66

    raw = AudioData()
    raw.bass = 0.71
    raw.mid = 0.72
    raw.treble = 0.73
    raw.bass_n = 0.74
    raw.mid_n = 0.75
    raw.treble_n = 0.76

    app._audio = cooked
    app._audio_raw = raw

    fields = app._hud_audio_state_fields()

    assert fields == {
        'bass': '0.71',
        'mid': '0.72',
        'treble': '0.73',
        'bass_n': '0.74',
        'mid_n': '0.75',
        'treble_n': '0.76',
    }


def test_hud_audio_state_fields_falls_back_to_processed_audio() -> None:
    app = App(_default_cfg())

    cooked = AudioData()
    cooked.bass = 0.21
    cooked.mid = 0.31
    cooked.treble = 0.41
    cooked.bass_n = 0.51
    cooked.mid_n = 0.61
    cooked.treble_n = 0.71

    app._audio = cooked
    app._audio_raw = None

    fields = app._hud_audio_state_fields()

    assert fields == {
        'bass': '0.21',
        'mid': '0.31',
        'treble': '0.41',
        'bass_n': '0.51',
        'mid_n': '0.61',
        'treble_n': '0.71',
    }


def test_hud_audio_state_fields_defaults_when_audio_unavailable() -> None:
    app = App(_default_cfg())

    app._audio = None
    app._audio_raw = None

    fields = app._hud_audio_state_fields()

    assert fields == {
        'bass': '0.00',
        'mid': '0.00',
        'treble': '0.00',
        'bass_n': '0.50',
        'mid_n': '0.50',
        'treble_n': '0.50',
    }
