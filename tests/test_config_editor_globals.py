"""Configuration editor — Audio/Visuals global tabs (Increment 5) tests.

Verifies the App builds global-setting rows and that adjust routes to the right
global setter based on the active tab. No GL context needed.
"""
from __future__ import annotations

from pathlib import Path

from unicornviz.app import App
from unicornviz.config_profiles import ConfigProfileStore
from unicornviz.overlays import Overlays


class _StubCfg:
    def get(self, section, key=None, default=None):
        return default


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
    app._config_profile_store = ConfigProfileStore(tmp_path / 'cp.json')
    app._effect_config_overrides = {}
    app._current_effect = None
    app._audio_manager = _AudioManager() if audio else None
    app._effect_duration = 30.0
    app._render_scale = 1.0
    app._color_grade = None
    app._audio_out = None
    ov = Overlays.__new__(Overlays)
    ov._config_editor_tabs = ['Effects', 'Audio', 'Visuals']
    ov._config_editor_tab = ['Effects', 'Audio', 'Visuals'].index(tab)
    ov._ce_param_idx = 0
    app._overlays = ov
    return app


def test_audio_global_rows(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Audio')
    rows = app.config_editor_global_rows('Audio')
    names = [r['name'] for r in rows]
    assert 'reactivity' in names
    assert 'advance_interval_s' in names
    react = next(r for r in rows if r['name'] == 'reactivity')
    assert react['value'] == 1.0
    assert (react['min'], react['max']) == (0.1, 5.0)


def test_audio_rows_without_audio_manager(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Audio', audio=False)
    names = [r['name'] for r in app.config_editor_global_rows('Audio')]
    # reactivity is omitted without an audio manager (no crash); the latency
    # selector does not need one, since it persists to runtime state and is
    # read at the next launch rather than applied live.
    assert names == [
        'advance_interval_s',
        'latency 0=low 1=med 2=high (restart)',
    ]


def test_visuals_global_rows(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Visuals')
    rows = app.config_editor_global_rows('Visuals')
    assert [r['name'] for r in rows] == [
        'render_scale',
        'fps limit 0=display/24/30/60',
    ]
    assert (rows[0]['min'], rows[0]['max']) == (0.5, 1.0)


def test_adjust_audio_reactivity_live(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Audio')
    app._overlays._ce_param_idx = 0  # reactivity
    # range [0.1, 5.0], step = 4.9/40 = 0.1225; +1 → 1.1225.
    app._config_editor_adjust(1.0)
    assert abs(app._audio_manager.get_reactivity() - 1.1225) < 1e-6


def test_adjust_audio_interval_clamps(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Audio')
    app._overlays._ce_param_idx = 1  # advance_interval_s, range [10, 120]
    for _ in range(500):
        app._config_editor_adjust(-1.0)
    assert app._effect_duration == 10.0  # clamped at min


def test_adjust_visuals_render_scale(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Visuals')
    captured = {}
    app.set_render_scale = lambda v: captured.setdefault('v', v)
    app._overlays._ce_param_idx = 0
    # range [0.5, 1.0], step = 0.5/40 = 0.0125; -1 from 1.0 → 0.9875.
    app._config_editor_adjust(-1.0)
    assert abs(captured['v'] - 0.9875) < 1e-6


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
