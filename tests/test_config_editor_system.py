"""Configuration editor — System / Auto VJ tabs + drop-in settings (Increment 6).

Covers dynamic tab list (Auto VJ conditional), System/Auto-VJ read-only info
rows, and the guarded audio/video drop-in settings folded into Audio/Visuals.
No GL context needed.
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
    def get_reactivity(self):
        return 1.0

    def set_reactivity(self, v):
        return v

    def get_xrun_count(self):
        return 3

    def get_source_label(self):
        return 'PipeWire Monitor'

    def get_profile_name(self):
        return 'Raver'


class _ColorGrade:
    def __init__(self):
        self.intensity = 0.85

    def set_intensity(self, v):
        self.intensity = max(0.0, min(1.0, float(v)))
        return self.intensity


class _AudioOut:
    def __init__(self):
        self._wet = 0.45

    def snapshot(self):
        return {'params': {'reverb_wet': self._wet}}

    def set_filter(self, name, value):
        if name == 'reverb_wet':
            self._wet = max(0.0, min(1.0, float(value)))
        return self._wet


class _AutoVJ:
    hud_mood_label = 'HYPE'
    hud_scene_label = 'Tunnel'
    hud_bpm_label = '128'
    hud_bpm_confidence_label = '0.82'
    hud_action_in_label = '2 bars'
    profile_recommendation_hud = 'raver'


def _app(tmp_path: Path, *, tab='System', auto_vj=None, color_grade=None,
         audio_out=None, audio=True) -> App:
    app = object.__new__(App)
    app.cfg = _StubCfg()
    app._config_profile_store = ConfigProfileStore(tmp_path / 'cp.json')
    app._effect_config_overrides = {}
    app._current_effect = None
    app._audio_manager = _AudioManager() if audio else None
    app._effect_duration = 30.0
    app._render_scale = 0.9
    app._render_width = 1728
    app._render_height = 972
    app._width = 1920
    app._height = 1080
    app._display_mode = 'single'
    app._last_frame_fps = 59.9
    app._last_frame_ms = 16.7
    app._auto_vj = auto_vj
    app._color_grade = color_grade
    app._audio_out = audio_out
    app._config_editor_was_open = False
    ov = Overlays.__new__(Overlays)
    ov._config_editor_tabs = ['Effects', 'Audio', 'Visuals', 'System']
    ov._config_editor_tab = ov._config_editor_tabs.index(tab) if tab in ov._config_editor_tabs else 0
    ov._ce_effects = []
    ov._ce_effect_idx = 0
    ov._ce_params = []
    ov._ce_param_idx = 0
    ov._ce_profiles = []
    ov._ce_profile_idx = -1
    app._overlays = ov
    return app


# --- dynamic tabs ---------------------------------------------------------- #

def test_auto_vj_tab_only_when_enabled(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app._push_config_editor_model()
    assert 'System' in app._overlays._config_editor_tabs
    assert 'Auto VJ' not in app._overlays._config_editor_tabs

    app2 = _app(tmp_path, auto_vj=_AutoVJ())
    app2._push_config_editor_model()
    assert 'Auto VJ' in app2._overlays._config_editor_tabs


def test_set_tabs_clamps_index() -> None:
    ov = Overlays.__new__(Overlays)
    ov._config_editor_tabs = ['Effects', 'Audio', 'Visuals', 'System', 'Auto VJ']
    ov._config_editor_tab = 4  # Auto VJ
    ov.set_config_editor_tabs(['Effects', 'Audio', 'Visuals', 'System'])  # auto-vj gone
    assert ov._config_editor_tab == 3  # clamped


# --- info rows ------------------------------------------------------------- #

def test_system_info_rows(tmp_path: Path) -> None:
    rows = _app(tmp_path).config_editor_info_rows('System')
    names = {r['name'] for r in rows}
    assert {'FPS', 'Frame ms', 'Render size', 'Display mode', 'Effects', 'Platform'} <= names
    assert all(r.get('kind') == 'info' for r in rows)
    render_size = next(r for r in rows if r['name'] == 'Render size')
    assert render_size['info'] == '1728x972'


def test_auto_vj_info_rows(tmp_path: Path) -> None:
    rows = _app(tmp_path, auto_vj=_AutoVJ()).config_editor_info_rows('Auto VJ')
    by = {r['name']: r['info'] for r in rows}
    assert by['Mood'] == 'HYPE'
    assert by['BPM'] == '128'
    assert by['Scene'] == 'Tunnel'


def test_auto_vj_info_rows_empty_without_controller(tmp_path: Path) -> None:
    assert _app(tmp_path).config_editor_info_rows('Auto VJ') == []


# --- drop-in settings folded into Audio/Visuals ---------------------------- #

def test_color_grade_in_visuals(tmp_path: Path) -> None:
    cg = _ColorGrade()
    app = _app(tmp_path, tab='Visuals', color_grade=cg)
    rows = app.config_editor_global_rows('Visuals')
    names = [r['name'] for r in rows]
    assert 'render_scale' in names
    assert 'color_grade_intensity' in names
    # Adjust it live via the global adjust path.
    app._overlays._ce_param_idx = names.index('color_grade_intensity')
    app._config_editor_adjust(-1.0)
    assert cg.intensity < 0.85  # decreased


def test_audio_out_in_audio(tmp_path: Path) -> None:
    ao = _AudioOut()
    app = _app(tmp_path, tab='Audio', audio_out=ao)
    rows = app.config_editor_global_rows('Audio')
    names = [r['name'] for r in rows]
    assert 'audio_out_reverb' in names
    app._overlays._ce_param_idx = names.index('audio_out_reverb')
    app._config_editor_adjust(1.0)
    assert ao._wet > 0.45  # increased


def test_no_dropins_no_extra_rows(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Visuals')
    names = [r['name'] for r in app.config_editor_global_rows('Visuals')]
    assert names == ['render_scale']  # color-grade absent → not added
