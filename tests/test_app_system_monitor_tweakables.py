from __future__ import annotations

from pathlib import Path

from unicornviz.app import App
from unicornviz.config import Config
from unicornviz.effects.base import AudioData


def _default_cfg() -> Config:
    return Config(Path('tests') / '_missing_config_for_tests.toml')


class _FakeAudioManager:
    def __init__(self, reactivity: float) -> None:
        self._reactivity = float(reactivity)

    def get_reactivity(self) -> float:
        return float(self._reactivity)


class _FakeEffect:
    def __init__(self, params: dict[str, float]) -> None:
        self.parameters = dict(params)


def test_system_monitor_tweakables_snapshot_reads_live_values() -> None:
    app = App(_default_cfg())
    app._audio_manager = _FakeAudioManager(1.8)
    app._current_effect = _FakeEffect({'speed': 2.2, 'zoom': 0.9})

    values = app._system_monitor_tweakables_snapshot()

    assert values == {
        'reactivity': 1.8,
        'speed': 2.2,
        'zoom': 0.9,
    }


def test_system_monitor_tweakables_snapshot_uses_safe_defaults() -> None:
    app = App(_default_cfg())
    app._audio_manager = None
    app._current_effect = _FakeEffect({})

    values = app._system_monitor_tweakables_snapshot()

    assert values == {
        'reactivity': 1.0,
        'speed': None,
        'zoom': None,
    }


def test_system_monitor_audio_snapshot_prefers_raw_audio_values() -> None:
    app = App(_default_cfg())
    app._last_frame_fps = 58.2
    app._last_frame_ms = 17.18

    cooked = AudioData()
    cooked.bass = 0.8
    cooked.mid = 0.8
    cooked.treble = 0.8
    cooked.bass_n = 0.8
    cooked.mid_n = 0.8
    cooked.treble_n = 0.8

    raw = AudioData()
    raw.bass = 0.1
    raw.mid = 0.2
    raw.treble = 0.3
    raw.bass_n = 0.4
    raw.mid_n = 0.5
    raw.treble_n = 0.6

    app._audio = cooked
    app._audio_raw = raw

    values = app._system_monitor_audio_snapshot()

    assert values == {
        'fps': 58.2,
        'frame_ms': 17.18,
        'bass': 0.1,
        'mid': 0.2,
        'treble': 0.3,
        'bass_n': 0.4,
        'mid_n': 0.5,
        'treble_n': 0.6,
    }


def test_system_monitor_audio_snapshot_uses_defaults_without_audio() -> None:
    app = App(_default_cfg())
    app._last_frame_fps = 60.0
    app._last_frame_ms = 16.67
    app._audio = None
    app._audio_raw = None

    values = app._system_monitor_audio_snapshot()

    assert values == {
        'fps': 60.0,
        'frame_ms': 16.67,
        'bass': 0.0,
        'mid': 0.0,
        'treble': 0.0,
        'bass_n': 0.5,
        'mid_n': 0.5,
        'treble_n': 0.5,
    }
