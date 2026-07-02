"""Configuration editor — Effects tab (Increment 3) regression tests.

Covers the App-side model/adjust logic (range inference, param rows, live
adjust) and the Overlays-side selection/focus/click logic, all without GL.
"""
from __future__ import annotations

from pathlib import Path

from unicornviz.app import App, _infer_param_range
from unicornviz.config_profiles import ConfigProfileStore
from unicornviz.overlays import Overlays


# --------------------------------------------------------------------------- #
# App: range inference + param rows + adjust
# --------------------------------------------------------------------------- #

def test_infer_param_range() -> None:
    assert _infer_param_range(0.0) == (0.0, 1.0)
    assert _infer_param_range(2.0) == (0.5, 8.0)
    lo, hi = _infer_param_range(-2.0)
    assert lo == -8.0 and hi == -0.5


class _StubCfg:
    def get(self, section, key=None, default=None):
        return default


class _Effect:
    def __init__(self, params, initial=None):
        self.parameters = dict(params)
        self._initial_parameters = dict(initial if initial is not None else params)


def _app(tmp_path: Path, current=None) -> App:
    app = object.__new__(App)
    app.cfg = _StubCfg()
    app._config_profile_store = ConfigProfileStore(tmp_path / 'cp.json')
    app._effect_config_overrides = {}
    app._current_effect = current
    return app


def test_param_rows_use_initial_for_range(tmp_path: Path) -> None:
    class _Plasma(_Effect):
        pass

    # Live value already edited to 3.0 but initial is 2.0 → range from initial.
    eff = _Plasma({'speed': 3.0}, initial={'speed': 2.0})
    app = _app(tmp_path, current=eff)
    rows = app.config_editor_param_rows('_Plasma')
    assert len(rows) == 1
    row = rows[0]
    assert row['name'] == 'speed'
    assert row['value'] == 3.0
    assert (row['min'], row['max']) == (0.5, 8.0)  # from initial 2.0


def test_adjust_applies_live_and_clamps(tmp_path: Path) -> None:
    class _Plasma(_Effect):
        pass

    eff = _Plasma({'speed': 2.0}, initial={'speed': 2.0})
    app = _app(tmp_path, current=eff)

    ov = Overlays.__new__(Overlays)
    ov._config_editor_tabs = ['Effects', 'Audio', 'Visuals']
    ov._config_editor_tab = 0
    ov._ce_effects = [{'class_name': '_Plasma', 'display_name': 'Plasma'}]
    ov._ce_effect_idx = 0
    ov._ce_params = app.config_editor_param_rows('_Plasma')
    ov._ce_param_idx = 0
    ov._ce_focus = 1
    app._overlays = ov

    # range [0.5, 8.0], step = 7.5/40 = 0.1875; +1 notch → 2.1875 live-applied.
    app._config_editor_adjust(1.0)
    assert abs(eff.parameters['speed'] - 2.1875) < 1e-6
    assert app.config_overrides_snapshot()['_Plasma']['speed'] == eff.parameters['speed']

    # Many notches up must clamp at max.
    for _ in range(100):
        app._config_editor_adjust(1.0)
    assert eff.parameters['speed'] == 8.0


# --------------------------------------------------------------------------- #
# Overlays: selection, focus, click
# --------------------------------------------------------------------------- #

def _editor() -> Overlays:
    ov = Overlays.__new__(Overlays)
    ov._show_config_editor = True
    ov._config_editor_panel_rect = (100.0, 80.0, 1400.0, 900.0)
    ov._config_editor_tabs = ['Effects', 'Audio', 'Visuals']
    ov._config_editor_tab = 0
    ov._glyph_w = 13
    ov._glyph_h = 18
    ov._font_scale_norm = 8.0 / 18.0
    ov._ce_effects = [
        {'class_name': 'Plasma', 'display_name': 'Plasma'},
        {'class_name': 'Tunnel', 'display_name': 'Tunnel'},
    ]
    ov._ce_effect_idx = 0
    ov._ce_params = [
        {'name': 'speed', 'value': 1.0, 'min': 0.25, 'max': 4.0},
        {'name': 'hue', 'value': 0.5, 'min': 0.0, 'max': 1.0},
    ]
    ov._ce_param_idx = 0
    ov._ce_focus = 0
    ov._ce_effect_row_rects = []
    ov._ce_param_row_rects = []
    ov._ce_profiles = []
    ov._ce_profile_idx = -1
    ov._ce_dirty = False
    ov._ce_name_mode = False
    ov._ce_name_text = ''
    ov._ce_pending_action = None
    ov._ce_footer_button_rects = []
    ov._ce_profile_chip_rects = []
    return ov


def test_selected_class_and_param() -> None:
    ov = _editor()
    assert ov.config_editor_selected_class() == 'Plasma'
    ov.set_config_editor_effect_index(1)
    assert ov.config_editor_selected_class() == 'Tunnel'
    assert ov.config_editor_selected_param() == 'speed'
    ov._ce_param_idx = 1
    assert ov.config_editor_selected_param() == 'hue'


def test_focus_toggle_and_row_movement_wraps() -> None:
    ov = _editor()
    assert ov.config_editor_focus == 0
    # Effect list focused: Up/Down move effect idx (wraps).
    ov.move_config_editor_row(1)
    assert ov._ce_effect_idx == 1
    ov.move_config_editor_row(1)
    assert ov._ce_effect_idx == 0  # wrapped
    # Switch focus to params.
    ov.toggle_config_editor_focus()
    assert ov.config_editor_focus == 1
    ov.move_config_editor_row(1)
    assert ov._ce_param_idx == 1


def test_click_selects_effect_and_param_rows() -> None:
    ov = _editor()
    # Simulate rendered hit-regions.
    ov._ce_effect_row_rects = [(110.0, 200.0, 300.0, 28.0, 0), (110.0, 230.0, 300.0, 28.0, 1)]
    ov._ce_param_row_rects = [(600.0, 200.0, 500.0, 36.0, 0), (600.0, 240.0, 500.0, 36.0, 1)]
    ov._config_editor_tabs = ['Effects', 'Audio', 'Visuals']

    assert ov.handle_config_editor_click(120.0, 240.0) is True  # effect row 1
    assert ov._ce_effect_idx == 1
    assert ov.config_editor_focus == 0

    assert ov.handle_config_editor_click(650.0, 250.0) is True  # param row 1
    assert ov._ce_param_idx == 1
    assert ov.config_editor_focus == 1


def test_set_effects_clamps_index() -> None:
    ov = _editor()
    ov._ce_effect_idx = 5
    ov.set_config_editor_effects([{'class_name': 'Only', 'display_name': 'Only'}])
    assert ov._ce_effect_idx == 0
    ov.set_config_editor_effects([])
    assert ov.config_editor_selected_class() == ''


def test_render_effects_tab_smoke() -> None:
    ov = _editor()
    ov._config_editor_fading = False
    ov._config_editor_anim = 1.0
    ov._config_editor_tab_hover = -1
    ov._hud_t = 0.0
    ov._hud_state = {}
    ov._width = 1920
    ov._height = 1080
    ov._begin_panel = lambda *a, **k: (100.0, 80.0, 1400.0, 900.0, 1920, 1080)
    ov._draw_rect = lambda *a, **k: None
    ov._draw_text = lambda *a, **k: None
    ov._draw_audio_reactive_border_bulbs = lambda *a, **k: None
    ov._draw_modal_frame_decor = lambda *a, **k: None
    ov._context_menu_hover_glow = lambda *a, **k: None

    ov._render_config_editor()  # must not raise

    # Hit regions were rebuilt so click selection works.
    assert len(ov._ce_effect_row_rects) >= 1
    assert len(ov._ce_param_row_rects) >= 1
