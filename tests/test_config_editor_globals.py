"""Configuration editor — Audio / Visuals / Performance global rows.

Verifies the App builds the core global-setting rows for each tab and that
adjust routes to the right setter based on the active tab. No GL context.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from unicornviz.app import App
from unicornviz.config_profiles import ConfigProfileStore
from unicornviz.overlays import Overlays

_TABS = ['Effects', 'Audio', 'Hotkeys', 'Performance', 'Recording', 'Visuals']


@pytest.fixture(autouse=True)
def _no_midi_hardware(monkeypatch: pytest.MonkeyPatch) -> None:
    """The MIDI device row lists input ports; keep tests off real hardware."""
    import unicornviz.midi as midi_mod
    monkeypatch.setattr(midi_mod, 'list_ports', lambda: [])



class _StubCfg:
    def get(self, section, key=None, default=None):
        return default

    def set_override(self, section, key, value):
        pass


class _AudioManager:
    def __init__(self, reactivity=1.0):
        self._r = reactivity

    def get_reactivity(self):
        return self._r

    def set_reactivity(self, v):
        self._r = max(0.1, min(5.0, float(v)))
        return self._r


def _app(tmp_path: Path, tab='Audio', audio=True) -> App:
    app = object.__new__(App)
    app.cfg = _StubCfg()
    app._multihead = None
    app._display_mode = 'single'
    app._display_index = 0
    app._config_profile_store = ConfigProfileStore(tmp_path / 'cp.json')
    app._effect_config_overrides = {}
    app._current_effect = None
    app._audio_manager = _AudioManager() if audio else None
    app._effect_duration = 30.0
    app._transition_duration = 1.0
    app._render_scale = 1.0
    app._color_grade = None
    app._audio_out = None
    ov = Overlays.__new__(Overlays)
    ov._config_editor_tabs = list(_TABS)
    ov._config_editor_tab = _TABS.index(tab)
    ov._ce_param_idx = 0
    app._overlays = ov
    return app


def test_audio_global_rows(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Audio')
    rows = app.config_editor_global_rows('Audio')
    assert [r['name'] for r in rows] == ['Reactivity']
    react = rows[0]
    assert react['value'] == 1.0
    assert (react['min'], react['max']) == (0.1, 5.0)
    assert react['kind'] == 'slider'
    assert react['display'] == '1.00x'


def test_audio_rows_without_audio_manager(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Audio', audio=False)
    # Reactivity is omitted without an audio manager (no crash); latency
    # lives on the Performance tab now and does not need one.
    assert app.config_editor_global_rows('Audio') == []


def test_visuals_global_rows(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Visuals')
    rows = app.config_editor_global_rows('Visuals')
    assert [r['name'] for r in rows] == [
        'Effect duration', 'Transition length', 'Now Playing banner',
        'Now Spinning platter', 'HUD auto-hide', 'HUD timeout', 'Flash messages',
        'Detector BPM', 'Profile score', 'Recommended profile',
        'Speed min', 'Speed max', 'Reactivity min', 'Reactivity max', 'Zoom min', 'Zoom max',
        'ANSI art folder',
    ]
    assert (rows[0]['min'], rows[0]['max']) == (10.0, 120.0)
    assert [r['kind'] for r in rows] == [
        'slider', 'slider', 'toggle', 'toggle', 'toggle', 'slider', 'toggle',
        'toggle', 'toggle', 'toggle'] + ['slider'] * 6 + ['text']


def test_performance_rows_hold_the_render_knobs(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Performance')
    rows = {r['name']: r for r in app.config_editor_global_rows('Performance')}
    assert (rows['Render scale']['min'], rows['Render scale']['max']) == (0.5, 1.0)
    assert rows['Frame limit']['choices'] == ('DISPLAY', '24', '30', '60')
    assert rows['Frame limit']['value'] == 0.0  # config default: follow vsync
    assert rows['Capture latency']['badge'] == 'RESTART'


def test_adjust_audio_reactivity_live(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Audio')
    app._overlays._ce_param_idx = 0  # reactivity
    # range [0.1, 5.0], step = 4.9/40 = 0.1225; +1 -> 1.1225.
    app._config_editor_adjust(1.0)
    assert abs(app._audio_manager.get_reactivity() - 1.1225) < 1e-6


def test_adjust_effect_duration_clamps(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Visuals')
    app._overlays._ce_param_idx = 0  # Effect duration, range [10, 120]
    for _ in range(500):
        app._config_editor_adjust(-1.0)
    assert app._effect_duration == 10.0  # clamped at min


def test_adjust_performance_render_scale(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Performance')
    captured = {}
    app.set_render_scale = lambda v: captured.setdefault('v', v)
    app._overlays._ce_param_idx = 0  # Render scale
    # range [0.5, 1.0], step = 0.5/40 = 0.0125; -1 from 1.0 -> 0.9875.
    app._config_editor_adjust(-1.0)
    assert abs(captured['v'] - 0.9875) < 1e-6


def test_adjust_choice_steps_without_wrapping(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Performance')
    picked = []
    app._set_frame_limit_index = lambda v: picked.append(v)
    names = [r['name'] for r in app.config_editor_global_rows('Performance')]
    app._overlays._ce_param_idx = names.index('Frame limit')
    app._config_editor_adjust(1.0)   # DISPLAY (config default, index 0) -> 24
    assert picked == [1.0]
    # The stub never writes back, so this re-reads the same unmoved default
    # (index 0) and steps -1 from it -- the lower bound, which must clamp to
    # 0 rather than wrap to the last choice (60, index 3).
    app._config_editor_adjust(-1.0)
    assert picked == [1.0, 0.0]


class _ToggleDropin:
    """Quantizing 0/1 setter — the webcam-01 selfie-seg row shape."""

    CONFIG_EDITOR_CATEGORY = 'Visuals'
    CONFIG_EDITOR_KEY = 'webcam'

    def __init__(self):
        self.enabled = False

    def config_editor_settings(self):
        return [{'name': 'cam0_selfie_seg', 'value': 1.0 if self.enabled else 0.0,
                 'min': 0.0, 'max': 1.0, 'step': 1.0}]

    def set_config_setting(self, name, value):
        self.enabled = float(value) >= 0.5


def test_adjust_honors_per_row_step_for_quantized_toggles(tmp_path: Path) -> None:
    # Without an explicit step, (max-min)/40 nudges 0.0 -> 0.025 and a
    # >= 0.5 quantizing setter floors it straight back: unreachable toggle.
    app = _app(tmp_path, tab='Visuals')
    toggle = _ToggleDropin()
    app._webcam_system = toggle
    row_index = next(
        i for i, r in enumerate(app.config_editor_global_rows('Visuals'))
        if r['name'] == 'cam0_selfie_seg'
    )
    app._overlays._ce_param_idx = row_index
    app._config_editor_adjust(1.0)
    assert toggle.enabled is True    # one notch flips it on
    app._config_editor_adjust(-1.0)
    assert toggle.enabled is False   # and one notch flips it back
