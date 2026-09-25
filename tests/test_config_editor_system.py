"""Configuration editor 2.0 — tabs, Performance tab, drop-in settings.

Covers the fixed tab order (Effects first, then alphabetical), the
Performance tab's row model (every core cost knob as a slider / toggle /
choice with a live setter and runtime-state persistence), the RESTART rows'
config overlay at the next launch, profile exclusion, and the guarded
audio/video drop-in settings folded into Audio/Visuals.  No GL context.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from unicornviz.app import App
from unicornviz.config_profiles import ConfigProfileStore
from unicornviz.overlays import Overlays
from unicornviz.runtime_state import RuntimeStateStore


@pytest.fixture(autouse=True)
def _no_midi_hardware(monkeypatch: pytest.MonkeyPatch) -> None:
    """The MIDI device row lists input ports; keep tests off real hardware."""
    import unicornviz.midi as midi_mod
    monkeypatch.setattr(midi_mod, 'list_ports', lambda: [])



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
        self._config_editor_tabs = ['Effects', 'Audio', 'Drop-ins', 'Hotkeys', 'Logging',
                                    'Performance', 'Recording', 'Visuals']
        self._config_editor_tab = self._config_editor_tabs.index(tab)
        self._ce_effects = []
        self._ce_effect_idx = 0
        self._ce_params = []
        self._ce_param_idx = 0
        self._ce_profiles = []
        self._ce_profile_idx = -1
        self._ce_active_profile = ''
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
    app._multihead = None
    app._display_mode = 'single'
    app._display_index = 0
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
    ov.set_config_editor_profiles = lambda names, active='': None
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
        'Effects', 'Audio', 'Drop-ins', 'Hotkeys', 'Logging', 'Performance', 'Recording',
        'Visuals']
    assert ov.config_editor_tab_name == 'Performance'     # kept by name, not position
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
    'Display mode': 'choice', 'MIDI device': 'choice', 'MIDI preset': 'choice',
    'Audio process Python': 'choice', 'System monitor sampling': 'slider',
    'Tooltips': 'toggle', 'Video deck layer': 'toggle', 'Video cache edge': 'choice',
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
                       'MIDI device', 'MIDI preset',
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

    _specs(app, 'Logging')['Per-frame perf logging']['set'](1.0)   # moved to Logging
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
    _specs(app, 'Logging')['Per-frame perf logging']['set'](1.0)   # moved to Logging
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
                         'Flash messages', 'Detector BPM', 'Profile score',
                         'Recommended profile', 'Speed min', 'Speed max',
                         'Reactivity min', 'Reactivity max', 'Zoom min', 'Zoom max',
                         'ANSI art folder'}
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


# --- profiles: always one active, write-through, boot load (2026-09-24) ---- #

def _profile(app: App, name: str) -> dict:
    payload = app._config_profile_store.get(name)
    assert payload is not None, name
    return payload


def _visuals_index(app: App, name: str) -> int:
    return [s['name'] for s in app._config_editor_settings_specs('Visuals')].index(name)


def test_first_boot_saves_the_current_settings_as_an_active_default(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app._activate_boot_profile()
    assert app.config_profile_names() == ['default']
    assert app.active_config_profile == 'default'
    assert app.get_runtime_state('config_profile_active') == 'default'
    assert 'settings' in _profile(app, 'default')


def test_boot_loads_the_remembered_active_profile(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app._effect_duration = 45.0
    app.save_config_profile('club')
    app._effect_duration = 90.0
    app.save_config_profile('chill')              # now active
    app._runtime_state.set('config_profile_active', 'club')
    fresh = _app(tmp_path)
    fresh._activate_boot_profile()
    assert fresh.active_config_profile == 'club'
    assert fresh._effect_duration == 45.0


def test_boot_falls_back_to_the_first_profile_when_the_active_one_is_gone(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.save_config_profile('alpha')
    app._runtime_state.set('config_profile_active', 'deleted-long-ago')
    fresh = _app(tmp_path)
    fresh._activate_boot_profile()
    assert fresh.active_config_profile == 'alpha'


def test_first_write_through_boot_keeps_the_running_settings_as_default(tmp_path: Path) -> None:
    """Profiles saved before write-through existed, but none remembered as
    active: boot must not pick one arbitrarily and swap the running look."""
    app = _app(tmp_path)
    app._effect_duration = 90.0
    app._write_profile('perf-tweaked')            # pre-existing, never "active"
    fresh = _app(tmp_path)
    fresh._effect_duration = 30.0                 # what config.toml gives today
    fresh._activate_boot_profile()
    assert fresh.active_config_profile == 'default'
    assert fresh._effect_duration == 30.0
    assert sorted(fresh.config_profile_names()) == ['default', 'perf-tweaked']


def test_new_rows_are_caught_up_into_the_active_profile(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app._config_profile_store.save('old', {'effects': {}, 'settings': {'audio.reactivity': 1.0}})
    app._runtime_state.set('config_profile_active', 'old')
    app._activate_boot_profile()
    saved = _profile(app, 'old')['settings']
    numeric = {s['key'] for s in app._config_editor_all_specs() if s['kind'] not in ('text', 'secret')}
    assert numeric <= set(saved)                     # text rows persist on their own, not in profiles


def test_menu_changes_write_through_to_the_active_profile(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Visuals')
    app._activate_boot_profile()
    app._config_editor_set_value(_visuals_index(app, 'Effect duration'), 75.0)
    app._flush_profile_autosave(force=True)
    saved = _profile(app, 'default')['settings']
    assert saved['audio.advance_interval_s'] == 75.0


def test_effect_parameter_edits_write_through_too(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app._activate_boot_profile()
    app.set_effect_parameter('Plasma', 'speed', 2.5)
    app._flush_profile_autosave(force=True)
    assert _profile(app, 'default')['effects'] == {'Plasma': {'speed': 2.5}}


def test_performance_tab_changes_do_not_touch_the_profile(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Performance')
    app._activate_boot_profile()
    app._config_editor_set_value(0, 0.7)          # render scale: machine, not show
    assert app._profile_autosave_due == 0.0


def test_writes_are_debounced(tmp_path: Path, monkeypatch) -> None:
    import unicornviz.app as app_mod
    now = [100.0]
    monkeypatch.setattr(app_mod.time, 'monotonic', lambda: now[0])
    app = _app(tmp_path)
    app._activate_boot_profile()
    app.set_effect_parameter('Plasma', 'speed', 3.0)
    app._flush_profile_autosave()                 # still inside the delay
    assert _profile(app, 'default')['effects'] == {}
    now[0] += 1.0
    app._flush_profile_autosave()
    assert _profile(app, 'default')['effects'] == {'Plasma': {'speed': 3.0}}


def test_save_writes_to_active_and_a_new_name_creates_and_activates(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app._activate_boot_profile()
    app._overlays.set_config_editor_name_text('')         # nothing typed
    app._overlays._ce_pending_action = 'save'
    app._effect_duration = 50.0
    app._apply_config_editor_action()
    assert app.config_profile_names() == ['default']
    assert _profile(app, 'default')['settings']['audio.advance_interval_s'] == 50.0
    app._overlays.set_config_editor_name_text('warehouse')
    app._overlays._ce_pending_action = 'save'
    app._apply_config_editor_action()
    assert sorted(app.config_profile_names()) == ['default', 'warehouse']
    assert app.active_config_profile == 'warehouse'


def test_load_activates_and_pending_changes_stay_with_the_old_profile(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app._effect_duration = 40.0
    app.save_config_profile('a')
    app._effect_duration = 80.0
    app.save_config_profile('b')                  # active: b
    app.set_effect_parameter('Plasma', 'speed', 4.0)   # pending write for b
    assert app.load_config_profile('a')
    assert app.active_config_profile == 'a'
    assert _profile(app, 'b')['effects'] == {'Plasma': {'speed': 4.0}}
    assert _profile(app, 'a')['effects'] == {}
    assert app._effect_duration == 40.0


def test_deleting_the_active_profile_loads_the_next_without_overwriting_it(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app._effect_duration = 40.0
    app.save_config_profile('a')
    app._effect_duration = 80.0
    app.save_config_profile('b')
    assert app.delete_config_profile('b')
    assert app.active_config_profile == 'a'
    assert _profile(app, 'a')['settings']['audio.advance_interval_s'] == 40.0
    assert app._effect_duration == 40.0
    assert app.delete_config_profile('a')
    assert app.config_profile_names() == ['default']
    assert app.active_config_profile == 'default'


# --- overlay: active orange, pending purple + pulsing LOAD ------------------- #

def test_selection_follows_the_active_profile_until_another_is_picked() -> None:
    ov = _Overlays('Visuals')
    ov.set_config_editor_profiles(['a', 'b', 'c'], active='b')
    assert ov.config_editor_selected_profile() == 'b'
    assert ov.config_editor_pending_profile == ''
    ov._ce_profile_idx = 2                        # operator clicks 'c'
    ov.set_config_editor_profiles(['a', 'b', 'c'], active='b')   # next frame's push
    assert ov.config_editor_pending_profile == 'c'
    ov.set_config_editor_profiles(['a', 'b', 'c'], active='c')   # after LOAD
    assert ov.config_editor_pending_profile == ''
    assert ov.config_editor_selected_profile() == 'c'


def test_pending_pulse_stays_visible_and_cyan() -> None:
    alphas = [_Overlays._ce_pending_pulse_color(t / 10)[3] for t in range(40)]
    assert min(alphas) >= 0.45 and max(alphas) <= 1.0 and max(alphas) - min(alphas) > 0.4
    r, g, b, _a = _Overlays._ce_pending_pulse_color(0.0)
    assert g > 0.9 and b > 0.9 and r < 0.5


# --- config.toml -> menu migration (owner 2026-09-24) ------------------------ #

class _FileCfg(_StubCfg):
    """_StubCfg plus the config.toml-only view migration reads."""

    def __init__(self, values: dict | None = None, file: dict | None = None) -> None:
        super().__init__(values)
        self._file = dict(file or {})

    def file_value(self, *keys, default=None):
        return self._file.get(tuple(keys), default)


class _Contributor:
    CONFIG_EDITOR_CATEGORY = 'Performance'

    def __init__(self, rows) -> None:
        self._rows = rows

    def config_editor_settings(self):
        return list(self._rows)


def test_file_set_core_values_move_into_the_menu_once(tmp_path: Path) -> None:
    cfg = _FileCfg({('audio', 'latency'): 'high'},
                   file={('audio', 'latency'): 'high', ('logging', 'perf_frames'): True})
    app = _app(tmp_path, cfg=cfg)
    app._config_editor_contributors = lambda: []
    app._migrate_config_to_menu()
    assert app.get_runtime_state('audio_latency') == 'high'          # restart row
    assert app.get_runtime_state('perf_perf_frames') is True         # live row twin
    assert app.get_runtime_state('audio_fft_bands') is None          # default only: not pinned


def test_migration_never_overwrites_a_menu_choice(tmp_path: Path) -> None:
    cfg = _FileCfg(file={('audio', 'latency'): 'high'})
    app = _app(tmp_path, cfg=cfg)
    app._config_editor_contributors = lambda: []
    app._runtime_state.set('audio_latency', 'low')
    app._migrate_config_to_menu()
    assert app.get_runtime_state('audio_latency') == 'low'


def test_dropin_rows_that_declare_their_config_line_migrate(tmp_path: Path) -> None:
    cfg = _FileCfg(file={('control_room', 'render_interval'): 0.5,
                         ('control_room', 'fullscreen'): False})
    app = _app(tmp_path, cfg=cfg)
    ctrl = _Contributor([
        {'name': 'render_fps', 'kind': 'choice', 'value': 0.0,          # index of 2 fps
         'config': 'control_room.render_interval'},
        {'name': 'fullscreen', 'kind': 'toggle', 'value': 0.0, 'restart': 'control_room',
         'config': 'control_room.fullscreen'},
        {'name': 'gpu_ui', 'kind': 'toggle', 'value': 1.0, 'restart': 'control_room',
         'config': 'control_room.gpu_ui'},                              # not in the file
    ])
    app._config_editor_contributors = lambda: [('control_room', ctrl)]
    app._migrate_config_to_menu()
    assert app.get_runtime_state('perf_dropin.control_room.render_fps') == 0.0
    assert app.get_runtime_state('config_overrides.control_room.fullscreen') is False
    assert app.get_runtime_state('config_overrides.control_room.gpu_ui') is None


def test_config_file_value_ignores_defaults_and_overrides(tmp_path: Path) -> None:
    from unicornviz.config import Config
    path = tmp_path / 'config.toml'
    path.write_text('[control_room]\nrender_interval = 0.5\n', encoding='utf-8')
    cfg = Config(path, overrides={'logging': {'level': 'DEBUG'}})
    assert cfg.file_value('control_room', 'render_interval') == 0.5
    assert cfg.file_value('logging', 'level', default='x') == 'x'     # a CLI flag, not the file
    assert cfg.file_value('ansi', 'ansi_dir_auto', default='x') == 'x'  # a built-in default


# --- Drop-ins tab, HUD detail, random look (2026-09-24 coverage batch) -------- #

def test_dropins_tab_lists_restart_switches(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Drop-ins')
    rows = _rows(app, 'Drop-ins')
    assert {'Streaming (RTMP)', 'Spotify Web API', 'Control Room', 'Keystroke log',
            'Video out on at start', 'V4L2 virtual camera'} <= set(rows)
    assert all(r['kind'] == 'toggle' and r['badge'] == 'RESTART' for r in rows.values())
    assert rows['Candy Frame']['display'] == 'ON'          # its loader's default
    assert rows['Streaming (RTMP)']['display'] == 'OFF'


def test_nested_switch_keeps_its_sibling_keys(tmp_path: Path) -> None:
    """[spotify.web_api] enabled must not replace the whole web_api table."""
    from unicornviz.config import Config
    path = tmp_path / 'config.toml'
    path.write_text('[spotify.web_api]\nclient_id = "abc"\nenabled = false\n', encoding='utf-8')
    app = _app(tmp_path, tab='Drop-ins', cfg=Config(path))
    _specs(app, 'Drop-ins')['Spotify Web API']['set'](1.0)
    assert app.get_runtime_state('config_overrides.spotify.web_api.enabled') is True
    fresh = _app(tmp_path, cfg=Config(path))
    fresh._apply_runtime_config_overrides()
    assert fresh.cfg.get('spotify', 'web_api', 'enabled') is True
    assert fresh.cfg.get('spotify', 'web_api', 'client_id') == 'abc'


def test_switches_migrate_from_the_file(tmp_path: Path) -> None:
    cfg = _FileCfg(file={('keystrokes', 'enabled'): True, ('spotify', 'web_api', 'enabled'): True})
    app = _app(tmp_path, cfg=cfg)
    app._config_editor_contributors = lambda: []
    app._migrate_config_to_menu()
    assert app.get_runtime_state('config_overrides.keystrokes.enabled') is True
    assert app.get_runtime_state('config_overrides.spotify.web_api.enabled') is True
    assert app.get_runtime_state('config_overrides.chat.enabled') is None


def test_hud_detail_rows_apply_live_and_respect_production_mode(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Visuals')
    seen: list[tuple] = []
    app._overlays.set_hud_detector_visibility = lambda *flags: seen.append(flags)
    _specs(app, 'Visuals')['Detector BPM']['set'](1.0)
    assert seen[-1] == (True, False, False)
    app.cfg.set_override('auto_vj', 'hud_production_mode', True)
    _specs(app, 'Visuals')['Profile score']['set'](1.0)
    assert seen[-1] == (False, False, False)                # production mode wins
    assert app.cfg.get('overlays', 'hud_show_profile_score') is True   # but the choice is kept


def test_random_look_rows_reach_the_hotkey_ranges(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Visuals')
    app._current_effect = None
    specs = _specs(app, 'Visuals')
    specs['Zoom min']['set'](0.8)
    specs['Zoom max']['set'](1.2)
    assert app._random_range_for('zoom', 0.30, 1.80) == (0.8, 1.2)


def test_config_set_override_nests_dotted_keys(tmp_path: Path) -> None:
    from unicornviz.config import Config
    path = tmp_path / 'config.toml'
    path.write_text('[video_out.v4l2]\ndevice = "/dev/video10"\n', encoding='utf-8')
    cfg = Config(path)
    cfg.set_override('video_out', 'v4l2.enabled', True)
    assert cfg.get('video_out', 'v4l2') == {'device': '/dev/video10', 'enabled': True}


def test_adding_a_tab_keeps_the_open_tab_by_name() -> None:
    ov = Overlays.__new__(Overlays)
    ov._config_editor_tabs = ['Effects', 'Audio', 'Hotkeys', 'Performance']
    ov._config_editor_tab = 3                                   # Performance
    ov.set_config_editor_tabs(['Effects', 'Audio', 'Drop-ins', 'Hotkeys', 'Performance'])
    assert ov.config_editor_tab_name == 'Performance'



# --- Logging tab + text/secret rows (2026-09-24) ------------------------------ #

def test_logging_tab_rows(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Logging')
    rows = _rows(app, 'Logging')
    assert list(rows) == ['Log level', 'Log folder', 'Per-frame perf logging',
                          'Crash dump file', 'Stall dump after']
    assert rows['Log level']['choices'] == ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'NONE')
    assert rows['Log folder']['kind'] == 'text' and rows['Log folder']['value'] == 'logs'
    restart = {n for n, r in rows.items() if r['badge'] == 'RESTART'}
    assert restart == {'Log level', 'Log folder', 'Crash dump file', 'Stall dump after'}


def test_logging_choices_persist_and_apply_next_launch(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Logging')
    specs = _specs(app, 'Logging')
    specs['Log level']['set'](0.0)
    specs['Log folder']['set']('/var/tmp/uv-logs')
    specs['Crash dump file']['set'](0.0)
    specs['Stall dump after']['set'](12.4)
    assert app.get_runtime_state('logging_level') == 'DEBUG'
    assert app.get_runtime_state('logging_directory') == '/var/tmp/uv-logs'
    assert app.get_runtime_state('logging_faulthandler') is False
    assert app.get_runtime_state('logging_stall_dump_s') == 12.0
    fresh = _app(tmp_path)
    fresh._apply_runtime_config_overrides()
    assert fresh.cfg.get('logging', 'level') == 'DEBUG'
    assert fresh.cfg.get('logging', 'directory') == '/var/tmp/uv-logs'


def test_main_lays_menu_logging_over_config_but_a_flag_wins(tmp_path: Path) -> None:
    import argparse

    from unicornviz import __main__ as main_mod
    from unicornviz.config import Config
    state = tmp_path / 'state.json'
    RuntimeStateStore(state).set('logging_level', 'DEBUG')
    RuntimeStateStore(state).set('logging_directory', '/var/tmp/uv-logs')
    path = tmp_path / 'config.toml'
    path.write_text(f'[runtime_state]\npath = "{state}"\n[logging]\nlevel = "INFO"\n',
                    encoding='utf-8')
    cfg = Config(path)
    main_mod._apply_menu_logging(cfg, argparse.Namespace(log_level=None))
    assert cfg.get('logging', 'level') == 'DEBUG'
    assert cfg.get('logging', 'directory') == '/var/tmp/uv-logs'
    flagged = Config(path, overrides={'logging': {'level': 'ERROR'}})
    main_mod._apply_menu_logging(flagged, argparse.Namespace(log_level='ERROR'))
    assert flagged.get('logging', 'level') == 'ERROR'


def test_logging_values_migrate_from_the_file(tmp_path: Path) -> None:
    cfg = _FileCfg(file={('logging', 'level'): 'WARNING', ('logging', 'stall_dump_s'): 8})
    app = _app(tmp_path, cfg=cfg)
    app._config_editor_contributors = lambda: []
    app._migrate_config_to_menu()
    assert app.get_runtime_state('logging_level') == 'WARNING'
    assert app.get_runtime_state('logging_stall_dump_s') == 8.0


def test_secret_values_are_masked_in_override_log_lines() -> None:
    from unicornviz.app import _loggable
    assert _loggable('endpoint', 'rtmp://x/live/KEY') == '<set>'
    assert _loggable('web_api.client_id', '') == '<empty>'
    assert _loggable('level', 'DEBUG') == 'DEBUG'


def test_text_rows_apply_committed_text_and_toggle_sdl_text_input(tmp_path: Path, monkeypatch) -> None:
    import unicornviz.app as app_mod
    calls: list[str] = []
    monkeypatch.setattr(app_mod.sdl2, 'SDL_StartTextInput', lambda: calls.append('start'))
    monkeypatch.setattr(app_mod.sdl2, 'SDL_StopTextInput', lambda: calls.append('stop'))
    app = _app(tmp_path, tab='Logging')
    app._text_input_handlers = {}
    idx = list(_specs(app, 'Logging')).index('Log folder')
    app._config_editor_set_text(idx, 'mylogs')
    assert app.get_runtime_state('logging_directory') == 'mylogs'
    app._config_editor_set_value(idx, 0.5)       # numeric paths ignore text rows
    assert app.get_runtime_state('logging_directory') == 'mylogs'
    app._sync_config_editor_text_input(True)
    assert 'config_editor_text' in app._text_input_handlers
    app._sync_config_editor_text_input(True)      # idempotent
    app._sync_config_editor_text_input(False)
    assert calls == ['start', 'stop'] and 'config_editor_text' not in app._text_input_handlers


def test_dropin_secret_row_persists_a_nested_restart_override(tmp_path: Path) -> None:
    from unicornviz.config import Config
    path = tmp_path / 'config.toml'
    path.write_text('[spotify.web_api]\nscopes = ["user-read-playback-state"]\n', encoding='utf-8')
    app = _app(tmp_path, tab='Performance', cfg=Config(path))

    class _Spotify:
        CONFIG_EDITOR_CATEGORY = 'Performance'

        def config_editor_settings(self):
            return [{'name': 'client_id', 'kind': 'secret', 'value': '', 'restart': 'spotify'}]

        def set_config_setting(self, name, value):
            return {'web_api.client_id': value}

    app._config_editor_contributors = lambda: [('spotify', _Spotify())]
    spec = _specs(app, 'Performance')['client_id']
    assert spec['kind'] == 'secret' and spec['badge'] == 'RESTART'
    spec['set']('abc123')
    fresh = _app(tmp_path, cfg=Config(path))
    fresh._apply_runtime_config_overrides()
    assert fresh.cfg.get('spotify', 'web_api', 'client_id') == 'abc123'
    assert fresh.cfg.get('spotify', 'web_api', 'scopes') == ['user-read-playback-state']


# --- overlay text editing ------------------------------------------------------ #

def _text_ov(kind: str = 'text', value: str = 'logs') -> Overlays:
    ov = _Overlays('Logging')
    ov._ce_params = [{'name': 'Log folder', 'kind': kind, 'value': value}]
    ov._ce_text_edit_idx = -1
    ov._ce_text_buffer = ''
    ov._ce_text_request = None
    ov._ce_revealed = set()
    return ov


def test_overlay_text_edit_commit_and_cancel() -> None:
    ov = _text_ov()
    ov.begin_config_editor_text(0)
    assert ov.config_editor_text_editing and ov._ce_text_buffer == 'logs'
    ov.append_config_editor_text('/x\t')             # control chars dropped
    ov.backspace_config_editor_text()
    ov.commit_config_editor_text()
    assert ov.take_config_editor_text_request() == (0, 'logs/')
    assert not ov.config_editor_text_editing
    ov.begin_config_editor_text(0)
    ov.append_config_editor_text('zzz')
    ov.cancel_config_editor_text()
    assert ov.take_config_editor_text_request() is None


def test_overlay_secret_never_seeds_the_hidden_value() -> None:
    ov = _text_ov('secret', 'rtmp://host/live/KEY')
    ov.begin_config_editor_text(0)
    assert ov._ce_text_buffer == ''                   # masked: not put on screen
    ov.commit_config_editor_text()                    # empty Enter keeps it
    assert ov.take_config_editor_text_request() is None
    ov.toggle_config_editor_reveal(0)
    ov.begin_config_editor_text(0)
    assert ov._ce_text_buffer == 'rtmp://host/live/KEY'


def test_enter_on_a_text_row_starts_editing() -> None:
    ov = _text_ov()
    ov._ce_param_idx = 0
    assert ov.activate_config_editor_row() is False
    assert ov.config_editor_text_editing



def test_live_rows_on_the_logging_tab_are_remembered_like_performance(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Logging')

    class _AutoVJ:
        CONFIG_EDITOR_CATEGORY = 'Performance'

        def __init__(self) -> None:
            self.interval = 1.0

        def config_editor_settings(self):
            return [{'name': 'detector_log_interval_s', 'value': self.interval, 'min': 0.0,
                     'max': 10.0, 'tab': 'Logging'}]

        def set_config_setting(self, name, value):
            self.interval = float(value)

    ctrl = _AutoVJ()
    app._config_editor_contributors = lambda: [('auto_vj', ctrl)]
    _specs(app, 'Logging')['detector_log_interval_s']['set'](4.0)
    assert app.get_runtime_state('perf_dropin.auto_vj.detector_log_interval_s') == 4.0



def test_dj_mixer_enabled_stays_out_of_the_menu(tmp_path: Path) -> None:
    """Owner, 2026-09-24: [dj_mixer] enabled is config.toml / boot-level only
    (the mixer's other settings live in its own SETTINGS)."""
    app = _app(tmp_path, tab='Drop-ins')
    assert 'DJ mixer' not in _rows(app, 'Drop-ins')
    assert all(section != 'dj_mixer' for section, *_rest in App._DROPIN_SWITCHES)


# --- paths, display and MIDI rows (2026-09-24, final coverage batch) --------- #

class _FakeRecorder:
    TWEAKABLES: dict = {}

    def __init__(self) -> None:
        self.folder = ''
        self._crf, self._capture_audio, self._preset = 18, True, 'veryfast'
        self.auto_record, self.show_indicator = False, True

    def set_directory(self, path: str) -> None:
        self.folder = path

    def apply_setting(self, key, value) -> None:
        pass

    def set_pulse_source_name(self, name) -> None:
        pass


def test_recording_folder_row_applies_next_rec_and_survives_a_rebuild(tmp_path: Path, monkeypatch) -> None:
    import unicornviz.app as app_mod
    monkeypatch.setattr(app_mod.Recorder, 'TWEAKABLES', {})
    app = _app(tmp_path, tab='Recording')
    app._recorder = _FakeRecorder()
    app._set_recording_directory('/var/tmp/shows')
    assert app._recorder.folder == '/var/tmp/shows'
    assert app.get_runtime_state('recording_directory') == '/var/tmp/shows'
    app._recorder = _FakeRecorder()                 # e.g. rebuilt after a resize
    app._apply_persisted_recording_settings()
    assert app._recorder.folder == '/var/tmp/shows'


def test_ansi_folder_row_persists_and_migrates(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Visuals')
    _specs(app, 'Visuals')['ANSI art folder']['set']('~/art/ansi')
    assert app.cfg.get('ansi', 'ansi_dir_auto') == '~/art/ansi'
    assert app.get_runtime_state('ansi_dir_auto') == '~/art/ansi'
    fresh = _app(tmp_path / 'b', cfg=_FileCfg(file={('ansi', 'ansi_dir_auto'): 'assets/ansi/acid'}))
    fresh._config_editor_contributors = lambda: []
    fresh._migrate_config_to_menu()
    assert fresh.get_runtime_state('ansi_dir_auto') == 'assets/ansi/acid'


class _FakeMultiHead:
    def supported_display_modes(self):
        return ('single', 'span_included', 'mirror_all')

    def all_detected_displays(self):
        return [(0, 0, 0, 1920, 1080), (2, 1920, 0, 2560, 1440)]


def test_display_rows_apply_live_and_persist(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Performance')
    app._multihead = _FakeMultiHead()
    modes_set: list[str] = []
    app.set_display_mode = lambda mode=None, reset_to_config=False: modes_set.append(mode) or mode
    rows = _rows(app, 'Performance')
    assert rows['Display mode']['choices'] == ('SINGLE', 'SPAN INCLUDED', 'MIRROR ALL')
    assert rows['Display']['choices'] == ('0: 1920x1080', '2: 2560x1440')
    specs = _specs(app, 'Performance')
    specs['Display mode']['set'](2.0)
    assert modes_set[-1] == 'mirror_all'
    assert app.get_runtime_state('window_display_mode') == 'mirror_all'
    specs['Display']['set'](1.0)
    assert app._display_index == 2
    assert app.get_runtime_state('window_display_index') == 2


def test_display_row_hidden_with_one_display(tmp_path: Path) -> None:
    app = _app(tmp_path, tab='Performance')
    assert 'Display' not in _rows(app, 'Performance')      # no multi-head, one display


def test_window_overrides_apply_early_and_alone(tmp_path: Path) -> None:
    """__init__ lays [window] choices over config before multi-head is built;
    the rest waits for run() (the audio stream isn't open yet there either)."""
    app = _app(tmp_path)
    app._runtime_state.set('window_display_mode', 'span_included')
    app._runtime_state.set('audio_latency', 'high')
    app._apply_runtime_config_overrides(sections=('window',))
    assert app.cfg.get('window', 'display_mode') == 'span_included'
    assert app.cfg.get('audio', 'latency') is None


def test_midi_rows_list_ports_and_presets_and_auto_can_override_the_file(tmp_path: Path, monkeypatch) -> None:
    import unicornviz.midi as midi_mod
    monkeypatch.setattr(midi_mod, 'list_ports', lambda: ['APC mini mk2 0', 'DDJ-REV1 1'])
    cfg = _StubCfg({('midi', 'device'): 'APC'})
    app = _app(tmp_path, tab='Performance', cfg=cfg)
    rows = _rows(app, 'Performance')
    assert rows['MIDI device']['choices'] == ('AUTO', 'APC mini mk2 0', 'DDJ-REV1 1')
    assert rows['MIDI device']['display'] == 'APC mini mk2 0'     # the hint matches a port
    assert rows['MIDI preset']['choices'][0] == 'NONE'
    _specs(app, 'Performance')['MIDI device']['set'](0.0)          # AUTO
    assert app.get_runtime_state('midi_device') == ''
    fresh = _app(tmp_path, cfg=_StubCfg({('midi', 'device'): 'APC'}))
    fresh._apply_runtime_config_overrides()
    assert fresh.cfg.get('midi', 'device') == ''                   # empty is a real choice


def test_unplugged_midi_device_stays_selectable(tmp_path: Path, monkeypatch) -> None:
    import unicornviz.midi as midi_mod
    monkeypatch.setattr(midi_mod, 'list_ports', lambda: [])
    app = _app(tmp_path, tab='Performance', cfg=_StubCfg({('midi', 'device'): 'DDJ-REV1'}))
    row = _rows(app, 'Performance')['MIDI device']
    assert row['choices'] == ('AUTO', 'DDJ-REV1') and row['display'] == 'DDJ-REV1'



# --- [effects] parameters move into the active profile (lazy, once) ---------- #

class _FakeEffect:
    def __init__(self) -> None:
        self.parameters = {'speed': 1.0, 'zoom': 1.0}


def test_effect_params_move_into_the_profile_once_and_only_real_params(tmp_path: Path) -> None:
    cfg = _FileCfg(file={('effects', 'FirstDrop'): {
        'speed': 1.4, 'zoom': 2, 'random_zoom_min': 0.5, 'preload': True}})
    app = _app(tmp_path, cfg=cfg)
    app._activate_boot_profile()
    app._migrate_effect_params('FirstDrop', _FakeEffect())
    assert app._effect_config_overrides['FirstDrop'] == {'speed': 1.4, 'zoom': 2.0}
    app._flush_profile_autosave(force=True)
    assert _profile(app, 'default')['effects']['FirstDrop'] == {'speed': 1.4, 'zoom': 2.0}
    app.clear_effect_overrides('FirstDrop')                 # operator reverts it
    app._migrate_effect_params('FirstDrop', _FakeEffect())  # built again: not re-copied
    assert 'FirstDrop' not in app._effect_config_overrides


def test_effect_param_migration_waits_for_an_active_profile(tmp_path: Path) -> None:
    cfg = _FileCfg(file={('effects', 'FirstDrop'): {'speed': 1.4}})
    app = _app(tmp_path, cfg=cfg)
    app._migrate_effect_params('FirstDrop', _FakeEffect())   # startup, no profile yet
    assert app._effect_config_overrides == {}
    assert app.get_runtime_state('effects_migrated.FirstDrop') is None
    app._activate_boot_profile()
    app._migrate_effect_params('FirstDrop', _FakeEffect())
    assert app._effect_config_overrides['FirstDrop'] == {'speed': 1.4}


def test_effect_param_migration_keeps_an_existing_override(tmp_path: Path) -> None:
    cfg = _FileCfg(file={('effects', 'FirstDrop'): {'speed': 1.4, 'zoom': 3.0}})
    app = _app(tmp_path, cfg=cfg)
    app._activate_boot_profile()
    app.set_effect_parameter('FirstDrop', 'speed', 0.8)
    app._migrate_effect_params('FirstDrop', _FakeEffect())
    assert app._effect_config_overrides['FirstDrop'] == {'speed': 0.8, 'zoom': 3.0}
