"""Configuration editor modal shell (Increment 2) — regression tests.

Covers open/close + close-animation, tab selection/wrap, tab hit-testing, and
the blocking-modal / help wiring — all without a GL context (Overlays built via
``__new__`` with the handful of font/geometry attributes the layout needs).
"""
from __future__ import annotations

from unicornviz.overlays import Overlays


def _bare_overlays() -> Overlays:
    ov = Overlays.__new__(Overlays)
    ov._show_config_editor = False
    ov._config_editor_tabs = ['Effects', 'Audio', 'Visuals']
    ov._config_editor_tab = 0
    ov._config_editor_tab_hover = -1
    ov._config_editor_anim = 0.0
    ov._config_editor_fading = False
    ov._config_editor_panel_rect = None
    ov._ce_effect_row_rects = []
    ov._ce_param_row_rects = []
    ov._glyph_w = 13
    ov._glyph_h = 18
    ov._font_scale_norm = 8.0 / 18.0
    ov._width = 1920
    ov._height = 1080
    return ov


def test_toggle_opens_and_closes() -> None:
    ov = _bare_overlays()
    assert ov.config_editor_open is False
    assert ov.toggle_config_editor() is True
    assert ov.config_editor_open is True
    assert ov.config_editor_visible is True
    # Toggling closed starts the fade-out (visible, not open).
    assert ov.toggle_config_editor() is False
    assert ov.config_editor_open is False
    assert ov._config_editor_fading is True
    assert ov.config_editor_visible is True


def test_open_animation_advances_and_close_fades_out() -> None:
    ov = _bare_overlays()
    ov.toggle_config_editor()
    for _ in range(15):
        ov.tick_config_editor(1.0 / 60.0)
    assert ov._config_editor_anim == 1.0
    ov.close_config_editor()
    for _ in range(20):
        ov.tick_config_editor(1.0 / 60.0)
    assert ov._config_editor_fading is False
    assert ov.config_editor_visible is False


def test_tab_selection_and_wrap() -> None:
    ov = _bare_overlays()
    ov.toggle_config_editor()
    assert ov.config_editor_tab == 0
    assert ov.config_editor_tab_name == 'Effects'
    ov.move_config_editor_tab(1)
    assert ov.config_editor_tab_name == 'Audio'
    ov.move_config_editor_tab(-1)
    assert ov.config_editor_tab == 0
    ov.move_config_editor_tab(-1)  # wraps to last
    assert ov.config_editor_tab_name == 'Visuals'
    ov.set_config_editor_tab(1)
    assert ov.config_editor_tab_name == 'Audio'
    ov.set_config_editor_tab(99)  # clamps
    assert ov.config_editor_tab_name == 'Visuals'


def test_tab_click_switches_tab() -> None:
    ov = _bare_overlays()
    ov.toggle_config_editor()
    ov._config_editor_panel_rect = (100.0, 80.0, 1400.0, 900.0)
    boxes = ov._config_editor_tab_boxes(ov._config_editor_panel_rect)
    # Click the centre of the 'Audio' tab (index 1).
    _i, bx, by, bw, bh = boxes[1]
    assert ov.handle_config_editor_click(bx + bw / 2, by + bh / 2) is True
    assert ov.config_editor_tab_name == 'Audio'


def test_tab_click_miss_returns_false() -> None:
    ov = _bare_overlays()
    ov.toggle_config_editor()
    ov._config_editor_panel_rect = (100.0, 80.0, 1400.0, 900.0)
    # Far below the tab bar.
    assert ov.handle_config_editor_click(200.0, 900.0) is False


def test_motion_sets_tab_hover() -> None:
    ov = _bare_overlays()
    ov.toggle_config_editor()
    ov._config_editor_panel_rect = (100.0, 80.0, 1400.0, 900.0)
    boxes = ov._config_editor_tab_boxes(ov._config_editor_panel_rect)
    _i, bx, by, bw, bh = boxes[2]
    ov.handle_config_editor_motion(bx + bw / 2, by + bh / 2)
    assert ov._config_editor_tab_hover == 2


def test_config_editor_counts_as_blocking_modal() -> None:
    ov = _bare_overlays()
    # blocking_modal_open reads the full set of modal flags; give them defaults.
    for flag in (
        '_show_presets', '_show_effects_browser', '_show_projectm_manager',
        '_show_system_monitor_modal', '_show_controller_help_modal',
        '_show_webcam_editor_modal', '_show_audio', '_show_midi',
    ):
        setattr(ov, flag, False)
    assert ov.blocking_modal_open is False
    ov.toggle_config_editor()
    assert ov.blocking_modal_open is True
