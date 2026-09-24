"""Configuration editor 2.0 — tabs, Performance tab, drop-in settings.

Covers the fixed tab order (Effects first, then alphabetical), the
Performance tab's row model (every core cost knob as a slider / toggle /
choice with a live setter and runtime-state persistence), the RESTART rows'
config overlay at the next launch, profile exclusion, and the guarded
audio/video drop-in settings folded into Audio/Visuals.  No GL context.
"""
from __future__ import annotations

from pathlib import Path

from unicornviz.app import App
from unicornviz.config_profiles import ConfigProfileStore
from unicornviz.overlays import Overlays
from unicornviz.runtime_state import RuntimeStateStore


class _StubCfg:
    """cfg.get(section, key, default) + set_override, backed by a dict."""

    def __init__(self, values: dict | None = None) -> None:
        self._values: dict[tuple, object] = dict(values or {})

    def get(self, *keys, default=None):
        return self._values.get(tuple(keys), default)

    def set_override(self, section, key, value):
        self._values[(section, key)] = value


class _AudioManager:
    def __init__(self) -> None:
        self.reactivity = 1.0

    def get_reactivity(self):
        return self.reactivity

    def set_reactivity(self, v):
        self.reactivity = float(v)


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


class _Overlays(Overlays):
    """Bare overlay shell with the state the settings rows read and write."""

    def __init__(self, tab: str) -> None:  # noqa: D107 - test shell, no super()
        self._config_editor_tabs = ['Effects', 'Audio', 'Hotkeys', 'Performance',
                                    'Recording', 'Visuals']
        self._config_editor_tab = self._config_editor_tabs.index(tab)
        self._ce_effects = []
        self._ce_effect_idx = 0
        self._ce_params = []
        self._ce_param_idx = 0
        self._ce_profiles = []
        self._ce_profile_idx = -1
        self._ce_value_request = None
        self._sysmon_sample_interval = 0.45
        self._tooltips_enabled = True
        self._hud_auto_hide = True
        self._hud_timeout_s = 60.0
        self._hud_timer = 0.0
        self._show_name = False
        self._flash_enabled = True
        self.messages: list[str] = []

    def flash_message(self, text, _dur=0.0):
        self.messages.append(text)


def _app(tmp_path: Path, *, tab='Performance', color_grade=None, audio_out=None,
         audio=True, cfg=None) -> App:
    app = object.__new__(App)
    app.cfg = cfg if cfg is not None else _StubCfg()
    app._runtime_state = RuntimeStateStore(tmp_path / 'state.json')
    app._config_profile_store = ConfigProfileStore(tmp_path / 'cp.json')
    app._effect_config_overrides = {}
    app._current_effect = None
    app._audio_manager = _AudioManager() if audio else None
    app._recorder = None
    app._recording_sources_cache = None
    app._effect_duration = 30.0
    app._transition_duration = 1.0
    app._render_scale = 0.9
    app._render_scale_default = 1.0
    app._rebuild_fbos = lambda: None
    app._subsys_present_max_skips = 1
    app._subsys_skip_ms_cached = 0.0
    app._preview_capture_enabled = True
    app._preview_fps_ceiling = 0
    app._preview_max_width = 960
    app._perf_frames_enabled = False
    app._subsystems = {}
    app._color_grade = color_grade
    app._audio_out = audio_out
    app._config_editor_was_open = False
    app._overlays = _Overlays(tab)
    return app


def _rows(app: App, tab: str) -> dict[str, dict]:
    return {r['name']: r for r in app.config_editor_global_rows(tab)}


def _specs(app: App, tab: str) -> dict[str, dict]:
    return {s['name']: s for s in app._config_editor_settings_specs(tab)}


# --- tabs ----------------------------------------------------------------- #

def test_tabs_are_effects_then_alphabetical_and_info_tabs_are_gone(monkeypatch) -> None:
    import unicornviz.app as app_mod
    monkeypatch.setattr(app_mod, 'get_effects', lambda: [])
    ov = _Overlays('Performance')
    ov.set_config_editor_effects = lambda effects: None
    ov.set_config_editor_effect_index = lambda i: None
    ov.set_config_editor_params = lambda rows: None
    ov.set_config_editor_profiles = lambda names: None
    ov.set_config_editor_dirty = lambda d: None
    app = object.__new__(App)
    app._overlays = ov
    app._config_editor_was_open = True
    app._effect_config_overrides = {}
    app.current_effect_class_name = lambda: ''
    app.config_editor_global_rows = lambda tab: []
    app.config_profile_names = lambda: []
    app._push_config_editor_model()
    assert ov._config_editor_tabs == [
        'Effects', 'Audio', 'Hotkeys', 'Performance', 'Recording', 'Visuals']
    assert 'System' not in ov._config_editor_tabs
    assert 'Auto VJ' not in ov._config_editor_tabs
    assert not hasattr(app, 'config_editor_info_rows')


def test_set_tabs_clamps_index() -> None:
    ov = Overlays.__new__(Overlays)
    ov._config_editor_tabs = ['Effects', 'Audio', 'Visuals', 'System', 'Auto VJ']
    ov._config_editor_tab = 4
    ov.set_config_editor_tabs(['Effects', 'Audio', 'Visuals', 'System'])
    assert ov._config_editor_tab == 3


# --- Performance tab ------------------------------------------------------ #

_PERF_ROWS = {
    'Render scale': 'slider', 'Frame limit': 'choice', 'Present guard': 'slider',
    'Preview capture': 'toggle', 'Preview fps ceiling': 'slider',
    'Preview width': 'choice', 'Capture latency': 'choice', 'FFT bands': 'choice',
    'Capture block size': 'choice', 'Audio process': 'toggle',
    'Audio process Python': 'choice', 'System monitor sampling': 'slider',
    'Tooltips': 'toggle', 'Video deck layer': 'toggle', 'Video cache edge': 'choice',
    'Per-frame perf logging': 'toggle',
}


def test_performance_rows_cover_every_core_knob(tmp_path: Path) -> None:
    rows = _rows(_app(tmp_path), 'Performance')
    assert {n: r['kind'] for n, r in rows.items()} == _PERF_ROWS
    # Every row is self-describing: a hint for the tooltip, a section header.
    assert all(r['hint'] and r['section'] for r in rows.values())
    # Restart-only rows say so; live rows do not.
    restart = {n for n, r in rows.items() if r['badge'] == 'RESTART'}
    assert restart == {'Capture latency', 'FFT bands', 'Capture block size',
                       'Audio process', 'Audio process Python',
                       'Video deck layer', 'Video cache edge'}
    # Choices carry their labels; toggles/choices step by one.
    assert rows['Frame limit']['choices'] == ('DISPLAY', '24', '30', '60')
    assert rows['Preview width']['choices'] == ('480', '640', '960', '1280')
    assert all(rows[n]['step'] == 1.0 for n, k in _PERF_ROWS.items()
               if k in ('toggle', 'choice'))


def test_performance_live_rows_apply_and_persist(tmp_path: Path) -> None:
    app = _app(tmp_path)
    specs = _specs(app, 'Performance')
    specs['Present guard']['set'](3.0)
    assert app._subsys_present_max_skips == 3
    assert app.get_runtime_state('perf_present_guard_skips') == 3

    specs['Preview capture']['set'](0.0)
    assert app._preview_capture_enabled is False
    assert app._subsystems_need_frame_capture() is False
    assert app.get_runtime_state('perf_preview_capture') is False

    specs['Preview fps ceiling']['set'](12.0)
    assert app._preview_fps_ceiling == 12
    assert abs(app._subsystem_preview_capture_interval_s() - 1.0 / 10.0) < 1e-9  # default 10 < 12
    specs['Preview fps ceiling']['set'](4.0)
    assert abs(app._subsystem_preview_capture_interval_s() - 0.25) < 1e-9  # ceiling wins

    specs['Preview width']['set'](0.0)
    assert app._preview_max_width == 480
    assert app.get_runtime_state('perf_preview_max_width') == 480

    specs['System monitor sampling']['set'](1.25)
    assert abs(app._overlays.sysmon_sample_interval - 1.25) < 1e-9
    assert abs(app.get_runtime_state('perf_sysmon_interval_s') - 1.25) < 1e-9

    specs['Tooltips']['set'](0.0)
    assert app._overlays.tooltips_enabled is False
    assert app.get_runtime_state('perf_tooltips') is False

    specs['Per-frame perf logging']['set'](1.0)
    assert app._perf_frames_enabled is True
    assert app.get_runtime_state('perf_perf_frames') is True

    specs['Render scale']['set'](0.6)
    assert abs(app._render_scale - 0.6) < 1e-9
    assert abs(app.get_runtime_state('perf_render_scale') - 0.6) < 1e-9

    # The rows re-read the new state.
    rows = _rows(app, 'Performance')
    assert rows['Present guard']['display'] == '3 skips'
    assert rows['Preview capture']['display'] == 'OFF'
    assert rows['Preview fps ceiling']['display'] == '4 fps'
    assert rows['Preview width']['value'] == 0.0


def test_performance_restart_rows_persist_and_overlay_config(tmp_path: Path) -> None:
    app = _app(tmp_path)
    specs = _specs(app, 'Performance')
    specs['FFT bands']['set'](3.0)          # 2048
    specs['Capture block size']['set'](0.0)  # 256
    specs['Video deck layer']['set'](0.0)
    specs['Video cache edge']['set'](1.0)    # 480
    specs['Capture latency']['set'](2.0)     # high
    assert app.get_runtime_state('audio_fft_bands') == 2048
    assert app.get_runtime_state('audio_blocksize') == 256
    assert app.get_runtime_state('video_decks_enabled') is False
    assert app.get_runtime_state('video_decks_cache_long_edge') == 480
    assert app.get_runtime_state('audio_latency') == 'high'
    assert any('restart' in m for m in app._overlays.messages)
    # Same session: the rows show the pending choice.
    rows = _rows(app, 'Performance')
    assert rows['FFT bands']['display'] == '2048'
    assert rows['Capture block size']['display'] == '256'
    assert rows['Video deck layer']['display'] == 'OFF'

    # Next launch: the remembered values are laid over a fresh config.
    fresh = _app(tmp_path, cfg=_StubCfg({('audio', 'fft_bands'): 512}))
    fresh._apply_runtime_config_overrides()
    assert fresh.cfg.get('audio', 'fft_bands') == 2048
    assert fresh.cfg.get('audio', 'blocksize') == 256
    assert fresh.cfg.get('audio', 'latency') == 'high'
    assert fresh.cfg.get('video_decks', 'enabled') is False
    assert fresh.cfg.get('video_decks', 'cache_long_edge') == 480


def test_restore_performance_settings_lays_live_choices_back(tmp_path: Path) -> None:
    app = _app(tmp_path)
    specs = _specs(app, 'Performance')
    specs['Present guard']['set'](0.0)
    specs['Preview capture']['set'](0.0)
    specs['Preview fps ceiling']['set'](6.0)
    specs['Preview width']['set'](3.0)
    specs['System monitor sampling']['set'](0.8)
    specs['Tooltips']['set'](0.0)
    specs['Per-frame perf logging']['set'](1.0)
    specs['Render scale']['set'](0.75)

    fresh = _app(tmp_path)
    fresh._restore_performance_settings()
    assert fresh._subsys_present_max_skips == 0
    assert fresh._preview_capture_enabled is False
    assert fresh._preview_fps_ceiling == 6
    assert fresh._preview_max_width == 1280
    assert abs(fresh._overlays.sysmon_sample_interval - 0.8) < 1e-9
    assert fresh._overlays.tooltips_enabled is False
    assert fresh._perf_frames_enabled is True
    assert abs(fresh._render_scale - 0.75) < 1e-9


def test_restore_is_a_noop_without_remembered_state(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app._restore_performance_settings()
    assert app._subsys_present_max_skips == 1
    assert app._preview_capture_enabled is True
    assert app._preview_max_width == 960
    assert abs(app._render_scale - 0.9) < 1e-9


def test_performance_and_recording_are_not_profile_settings(tmp_path: Path) -> None:
    app = _app(tmp_path)
    keys = {s['key'] for s in app._config_editor_all_specs()}
    assert not any(k.startswith('perf.') for k in keys)
    assert not any(k.startswith('recording.') for k in keys)
    assert 'audio.reactivity' in keys


# --- adjust / set paths for the new row kinds ----------------------------- #

def test_adjust_flips_toggle_and_steps_choice(tmp_path: Path) -> None:
    app = _app(tmp_path)
    names = [r['name'] for r in app.config_editor_global_rows('Performance')]
    app._overlays._ce_param_idx = names.index('Preview capture')
    app._config_editor_adjust(-1.0)
    assert app._preview_capture_enabled is False
    app._config_editor_adjust(1.0)
    assert app._preview_capture_enabled is True

    app._overlays._ce_param_idx = names.index('Preview width')
    app._config_editor_adjust(1.0)    # 960 -> 1280
    assert app._preview_max_width == 1280
    app._config_editor_adjust(1.0)    # clamps at the end, no wrap
    assert app._preview_max_width == 1280


def test_set_value_clamps_and_snaps_to_step(tmp_path: Path) -> None:
    app = _app(tmp_path)
    names = [r['name'] for r in app.config_editor_global_rows('Performance')]
    app._config_editor_set_value(names.index('Present guard'), 2.4)
    assert app._subsys_present_max_skips == 2
    app._config_editor_set_value(names.index('Present guard'), 99.0)
    assert app._subsys_present_max_skips == 4
    app._config_editor_set_value(names.index('Render scale'), 0.1)
    assert abs(app._render_scale - 0.5) < 1e-9


def test_activate_drains_the_overlay_request(tmp_path: Path) -> None:
    app = _app(tmp_path)
    rows = app.config_editor_global_rows('Performance')
    app._overlays._ce_params = rows
    app._overlays._ce_param_idx = [r['name'] for r in rows].index('Tooltips')
    app._config_editor_activate()
    assert app._overlays.tooltips_enabled is False


# --- Visuals / Audio core rows -------------------------------------------- #

def test_visuals_rows_are_show_and_overlay_settings(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Visuals')
    rows = _rows(app, 'Visuals')
    assert set(rows) == {'Effect duration', 'Transition length', 'Now Playing banner',
                         'Now Spinning platter', 'HUD auto-hide', 'HUD timeout',
                         'Flash messages'}
    specs = _specs(app, 'Visuals')
    specs['Now Playing banner']['set'](0.0)
    assert app.now_playing_banner_enabled is False
    assert app.get_runtime_state('now_playing_banner_enabled') is False
    specs['Now Spinning platter']['set'](0.0)
    assert app.now_spinning_enabled is False
    assert app.get_runtime_state('now_spinning_enabled') is False
    assert _rows(app, 'Visuals')['Now Playing banner']['display'] == 'OFF'
    specs['Transition length']['set'](2.5)
    assert abs(app._transition_duration - 2.5) < 1e-9
    specs['HUD auto-hide']['set'](0.0)
    assert app._overlays.hud_auto_hide is False
    specs['HUD timeout']['set'](30.0)
    assert abs(app._overlays.hud_timeout_s - 30.0) < 1e-9
    specs['Flash messages']['set'](0.0)
    assert app._overlays.flash_messages_enabled is False


# --- drop-in settings folded into Audio/Visuals ---------------------------- #

def test_color_grade_in_visuals(tmp_path: Path) -> None:
    cg = _ColorGrade()
    app = _app(tmp_path, tab='Visuals', color_grade=cg)
    names = [r['name'] for r in app.config_editor_global_rows('Visuals')]
    assert 'intensity' in names  # contributed by color-grade via convention
    app._overlays._ce_param_idx = names.index('intensity')
    app._config_editor_adjust(-1.0)
    assert cg.intensity < 0.85


def test_audio_out_in_audio(tmp_path: Path) -> None:
    ao = _AudioOut()
    app = _app(tmp_path, tab='Audio', audio_out=ao)
    names = [r['name'] for r in app.config_editor_global_rows('Audio')]
    assert names[0] == 'Reactivity'
    assert 'reverb_wet' in names
    app._overlays._ce_param_idx = names.index('reverb_wet')
    app._config_editor_adjust(1.0)
    assert ao._wet > 0.45


def test_no_dropins_no_extra_rows(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Audio')
    assert [r['name'] for r in app.config_editor_global_rows('Audio')] == ['Reactivity']


def test_profile_persists_and_restores_dropin_setting(tmp_path: Path) -> None:
    cg = _ColorGrade()
    app = _app(tmp_path, tab='Visuals', color_grade=cg)
    cg.set_config_setting('intensity', 0.2)
    app.save_config_profile('Look A')

    cg2 = _ColorGrade()
    app2 = _app(tmp_path, tab='Visuals', color_grade=cg2)
    assert cg2.intensity == 0.85
    assert app2.load_config_profile('Look A') is True
    assert abs(cg2.intensity - 0.2) < 1e-6


# --- contributor convention 2.0: registry discovery, row tabs, restart rows -- #

class _PerfContrib:
    """A drop-in that puts look rows on Visuals and cost rows on Performance."""

    CONFIG_EDITOR_CATEGORY = 'Visuals'
    CONFIG_EDITOR_KEY = 'gizmo'
    CONFIG_EDITOR_TITLE = 'Gizmo'

    def __init__(self) -> None:
        self.glow = 0.5
        self.fps_cap = 2       # index into _CAPS
        self.workers = 4
        self.sparkle = True
        self.calls: list[tuple[str, float]] = []

    _CAPS = ('OFF', '10', '30', '60')

    def config_editor_settings(self):
        return [
            {'name': 'glow', 'value': self.glow, 'min': 0.0, 'max': 1.0},
            {'name': 'fps_cap', 'label': 'Preview fps cap', 'tab': 'Performance',
             'kind': 'choice', 'choices': self._CAPS, 'value': self.fps_cap,
             'hint': 'Readback ceiling'},
            {'name': 'sparkle', 'tab': 'Performance', 'kind': 'toggle',
             'value': 1.0 if self.sparkle else 0.0, 'section': 'Sparkle'},
            {'name': 'workers', 'tab': 'Performance', 'kind': 'choice',
             'choices': ('2', '4', '8'), 'value': ('2', '4', '8').index(str(self.workers)),
             'restart': 'gizmo'},
        ]

    def set_config_setting(self, name, value):
        self.calls.append((name, float(value)))
        if name == 'glow':
            self.glow = float(value)
        elif name == 'fps_cap':
            self.fps_cap = int(round(value))
        elif name == 'sparkle':
            self.sparkle = float(value) >= 0.5
        elif name == 'workers':
            self.workers = int(('2', '4', '8')[int(round(value))])
            return {'tag_workers': self.workers}


def test_contributors_are_discovered_through_the_registry(tmp_path: Path) -> None:
    app = _app(tmp_path)
    gizmo = _PerfContrib()
    app._subsystems = {'gizmo_sub': gizmo}
    assert [p for p, _c in app._config_editor_contributors()] == ['gizmo']
    # Registered twice (attribute + registry) still counts once.
    app._audio_out = gizmo
    assert [p for p, _c in app._config_editor_contributors()] == ['gizmo']


def test_rows_route_to_their_own_tab_with_presentation_passthrough(tmp_path: Path) -> None:
    app = _app(tmp_path)
    gizmo = _PerfContrib()
    app._subsystems = {'gizmo': gizmo}
    visuals = _rows(app, 'Visuals')
    assert 'glow' in visuals and 'Preview fps cap' not in visuals
    assert visuals['glow']['section'] == 'Gizmo'       # default section = title
    perf = _rows(app, 'Performance')
    cap = perf['Preview fps cap']
    assert (cap['kind'], cap['choices'], cap['min'], cap['max'], cap['step']) == (
        'choice', ('OFF', '10', '30', '60'), 0.0, 3.0, 1.0)
    assert cap['display'] == '30' and cap['hint'] == 'Readback ceiling'
    assert perf['sparkle']['display'] == 'ON' and perf['sparkle']['section'] == 'Sparkle'
    assert perf['workers']['badge'] == 'RESTART'
    # Core rows still come first; the drop-in section follows.
    names = [r['name'] for r in app.config_editor_global_rows('Performance')]
    assert names.index('Render scale') < names.index('Preview fps cap')


def test_live_performance_rows_persist_and_restore_through_the_setter(tmp_path: Path) -> None:
    app = _app(tmp_path)
    gizmo = _PerfContrib()
    app._subsystems = {'gizmo': gizmo}
    specs = _specs(app, 'Performance')
    specs['Preview fps cap']['set'](3.0)
    specs['sparkle']['set'](0.0)
    assert gizmo.fps_cap == 3 and gizmo.sparkle is False
    assert app.get_runtime_state('perf_dropin') == {'gizmo': {'fps_cap': 3.0, 'sparkle': 0.0}}
    # A fresh app + fresh controller: restore replays the remembered values.
    fresh = _app(tmp_path)
    gizmo2 = _PerfContrib()
    fresh._subsystems = {'gizmo': gizmo2}
    fresh._restore_performance_settings()
    assert gizmo2.fps_cap == 3 and gizmo2.sparkle is False
    assert ('fps_cap', 3.0) in gizmo2.calls


def test_restart_rows_overlay_config_now_and_at_the_next_launch(tmp_path: Path) -> None:
    app = _app(tmp_path)
    gizmo = _PerfContrib()
    app._subsystems = {'gizmo': gizmo}
    _specs(app, 'Performance')['workers']['set'](2.0)      # '8'
    assert app.cfg.get('gizmo', 'tag_workers') == 8         # applied in memory now
    assert app.get_runtime_state('config_overrides') == {'gizmo': {'tag_workers': 8}}
    assert 'perf_dropin' not in (app.get_runtime_state('', default={}) or {})
    fresh = _app(tmp_path)
    fresh._apply_runtime_config_overrides()
    assert fresh.cfg.get('gizmo', 'tag_workers') == 8


def test_visuals_rows_are_not_remembered_as_performance_state(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app._subsystems = {'gizmo': _PerfContrib()}
    _specs(app, 'Visuals')['glow']['set'](0.9)
    assert app.get_runtime_state('perf_dropin', default=None) is None


def test_set_override_creates_a_missing_section() -> None:
    from unicornviz.config import Config
    cfg = Config.__new__(Config)
    cfg._data = {}
    cfg.set_override('webcam', 'fps', 60)
    assert cfg.get('webcam', 'fps') == 60
    assert cfg.get('webcam', default={}) == {'fps': 60}


# --- [audio] process / process_python (beta.162 settings, menu rows) -------- #

def _fake_free_threaded_python(data_home: Path) -> str:
    py = data_home / 'unicorn-viz' / 'venv-ft' / 'bin' / 'python'
    py.parent.mkdir(parents=True)
    py.write_text('#!/bin/sh\n')
    py.chmod(0o755)
    return str(py)


def test_audio_process_rows_default_to_in_app_python(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'no-ft-here'))
    app = _app(tmp_path)
    rows = _rows(app, 'Performance')
    assert rows['Audio process']['display'] == 'ON'
    assert rows['Audio process']['badge'] == 'RESTART'
    py = rows['Audio process Python']
    assert py['badge'] == 'RESTART'
    assert py['choices'] == ('APP PYTHON',)          # nothing free-threaded installed
    assert py['display'] == 'APP PYTHON'


def test_free_threaded_is_offered_but_never_chosen_by_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    _fake_free_threaded_python(tmp_path / 'data')
    app = _app(tmp_path)
    py = _rows(app, 'Performance')['Audio process Python']
    assert py['choices'] == ('APP PYTHON', 'FREE-THREADED')
    assert py['display'] == 'APP PYTHON'
    assert app.get_runtime_state('audio_process_python') is None   # opening the menu writes nothing


def test_choosing_free_threaded_applies_on_the_next_launch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    ft = _fake_free_threaded_python(tmp_path / 'data')
    app = _app(tmp_path)
    _specs(app, 'Performance')['Audio process Python']['set'](1.0)
    assert app.get_runtime_state('audio_process_python') == ft
    assert _rows(app, 'Performance')['Audio process Python']['display'] == 'FREE-THREADED'
    assert any('restart' in m for m in app._overlays.messages)
    fresh = _app(tmp_path)
    fresh._apply_runtime_config_overrides()
    assert fresh.cfg.get('audio', 'process_python') == ft


def test_app_python_choice_overrides_a_hand_set_path(tmp_path: Path, monkeypatch) -> None:
    """An empty interpreter is a real choice (the app's own), so it must win
    over a path set by hand in config.toml at the next launch."""
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'no-ft-here'))
    hand = {('audio', 'process_python'): '/opt/py/bin/python3.14t'}
    app = _app(tmp_path, cfg=_StubCfg(dict(hand)))
    py = _rows(app, 'Performance')['Audio process Python']
    assert py['choices'] == ('APP PYTHON', 'CUSTOM')      # the hand-set path is kept visible
    assert py['display'] == 'CUSTOM'
    _specs(app, 'Performance')['Audio process Python']['set'](0.0)
    assert app.get_runtime_state('audio_process_python') == ''
    fresh = _app(tmp_path, cfg=_StubCfg(dict(hand)))
    fresh._apply_runtime_config_overrides()
    assert fresh.cfg.get('audio', 'process_python') == ''


def test_audio_process_toggle_persists_for_the_next_launch(tmp_path: Path) -> None:
    app = _app(tmp_path)
    _specs(app, 'Performance')['Audio process']['set'](0.0)
    assert app.get_runtime_state('audio_process') is False
    assert _rows(app, 'Performance')['Audio process']['display'] == 'OFF'
    fresh = _app(tmp_path)
    fresh._apply_runtime_config_overrides()
    assert fresh.cfg.get('audio', 'process') is False


def test_empty_string_still_skipped_for_other_string_overrides(tmp_path: Path) -> None:
    app = _app(tmp_path, cfg=_StubCfg({('audio', 'latency'): 'low'}))
    app._runtime_state.set('audio_latency', '')
    app._apply_runtime_config_overrides()
    assert app.cfg.get('audio', 'latency') == 'low'
