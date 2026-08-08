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
    """Implements the config-editor convention."""

    CONFIG_EDITOR_CATEGORY = 'Visuals'
    CONFIG_EDITOR_KEY = 'color_grade'

    def __init__(self):
        self.intensity = 0.85

    def config_editor_settings(self):
        return [{'name': 'intensity', 'value': self.intensity, 'min': 0.0, 'max': 1.0}]

    def set_config_setting(self, name, value):
        if name == 'intensity':
            self.intensity = max(0.0, min(1.0, float(value)))


class _AudioOut:
    """Implements the config-editor convention."""

    CONFIG_EDITOR_CATEGORY = 'Audio'
    CONFIG_EDITOR_KEY = 'audio_out'

    def __init__(self):
        self._wet = 0.45

    def config_editor_settings(self):
        return [{'name': 'reverb_wet', 'value': self._wet, 'min': 0.0, 'max': 1.0}]

    def set_config_setting(self, name, value):
        if name == 'reverb_wet':
            self._wet = max(0.0, min(1.0, float(value)))


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
    # Real App.__init__ always sets these; the Recording tab reads them when
    # the walk below visits it.
    app._recorder = None
    app._recording_sources_cache = None
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
    assert 'intensity' in names  # contributed by color-grade via convention
    # Adjust it live via the global adjust path.
    app._overlays._ce_param_idx = names.index('intensity')
    app._config_editor_adjust(-1.0)
    assert cg.intensity < 0.85  # decreased


def test_audio_out_in_audio(tmp_path: Path) -> None:
    ao = _AudioOut()
    app = _app(tmp_path, tab='Audio', audio_out=ao)
    rows = app.config_editor_global_rows('Audio')
    names = [r['name'] for r in rows]
    assert 'reverb_wet' in names  # contributed by audio-out via convention
    app._overlays._ce_param_idx = names.index('reverb_wet')
    app._config_editor_adjust(1.0)
    assert ao._wet > 0.45  # increased


def test_no_dropins_no_extra_rows(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Visuals')
    names = [r['name'] for r in app.config_editor_global_rows('Visuals')]
    assert names == ['render_scale']  # no contributor → nothing extra


def test_profile_persists_and_restores_dropin_setting(tmp_path: Path) -> None:
    cg = _ColorGrade()
    app = _app(tmp_path, tab='Visuals', color_grade=cg)
    cg.set_config_setting('intensity', 0.2)
    app.save_config_profile('Look A')

    # Fresh app + fresh controller at a different value; load must restore 0.2.
    cg2 = _ColorGrade()
    app2 = _app(tmp_path, tab='Visuals', color_grade=cg2)
    assert cg2.intensity == 0.85
    assert app2.load_config_profile('Look A') is True
    assert abs(cg2.intensity - 0.2) < 1e-6
