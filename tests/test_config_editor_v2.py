"""Configuration editor 2.0 — overlay-side geometry, pointer input, rendering.

The editor is a declarative row surface: App pushes rows, Overlays owns
cursor/hover/drag and queues "set row i to v" requests that App drains.
These tests drive that contract without a GL context: draw calls are
stubbed and recorded, hit rectangles are read back from the render pass.
"""
from __future__ import annotations

from unicornviz.overlays import Overlays


def _ov(tab: str = 'Performance', params: list[dict] | None = None) -> Overlays:
    ov = Overlays.__new__(Overlays)
    ov._show_config_editor = True
    ov._config_editor_tabs = ['Effects', 'Audio', 'Hotkeys', 'Performance',
                              'Recording', 'Visuals']
    ov._config_editor_tab = ov._config_editor_tabs.index(tab)
    ov._config_editor_tab_hover = -1
    ov._config_editor_anim = 1.0
    ov._config_editor_fading = False
    ov._config_editor_panel_rect = (100.0, 80.0, 1400.0, 900.0)
    ov._ce_effects = []
    ov._ce_effect_idx = 0
    ov._ce_params = list(params or [])
    ov._ce_param_idx = 0
    ov._ce_focus = 1
    ov._ce_effect_row_rects = []
    ov._ce_param_row_rects = []
    ov._ce_footer_button_rects = []
    ov._ce_profile_chip_rects = []
    ov._ce_profiles = []
    ov._ce_profile_idx = -1
    ov._ce_dirty = False
    ov._ce_name_mode = False
    ov._ce_name_text = ''
    ov._ce_pending_action = None
    ov._ce_capture_mode = False
    ov._ce_capture_action = ''
    ov._glyph_w = 13
    ov._glyph_h = 18
    ov._font_scale_norm = 8.0 / 18.0
    ov._width = 1920
    ov._height = 1080
    ov._hud_t = 1.0
    ov._hud_state = {'bass': '0.5', 'mid': '0.2', 'treble': '0.7',
                     'fps': '58.9', 'frame_ms': '17.0'}
    ov.calls: list[tuple] = []
    ov._draw_rect = lambda *a, **k: ov.calls.append(('rect', a))
    ov._draw_text = lambda *a, **k: ov.calls.append(('text', a, k))
    ov._context_menu_hover_glow = lambda *a, **k: ov.calls.append(('glow', a))
    ov._begin_panel = lambda *a, **k: (100.0, 80.0, 1400.0, 900.0, 1920.0, 1080.0)
    ov._draw_audio_reactive_border_bulbs = lambda *a, **k: None
    ov._draw_modal_frame_decor = lambda *a, **k: None
    return ov


def _rows() -> list[dict]:
    return [
        {'name': 'Render scale', 'kind': 'slider', 'value': 0.9, 'min': 0.5, 'max': 1.0,
         'display': '0.90x', 'hint': 'Internal render resolution', 'section': 'Render'},
        {'name': 'Frame limit', 'kind': 'choice', 'value': 2.0, 'min': 0.0, 'max': 3.0,
         'choices': ('DISPLAY', '24', '30', '60'), 'hint': 'Cap', 'section': 'Render'},
        {'name': 'Preview capture', 'kind': 'toggle', 'value': 1.0, 'min': 0.0, 'max': 1.0,
         'display': 'ON', 'hint': 'Readback', 'section': 'Previews'},
        {'name': 'Capture latency', 'kind': 'choice', 'value': 0.0, 'min': 0.0, 'max': 2.0,
         'choices': ('LOW', 'MEDIUM', 'HIGH'), 'badge': 'RESTART', 'section': 'Audio'},
        {'name': 'Audio source', 'kind': 'choice', 'value': 1.0, 'min': 0.0, 'max': 2.0,
         'choices': ('auto (follow visualizer)',
                     'alsa_output.pci-0000_00_1f.3.analog-stereo.monitor',
                     'alsa_output.usb-Pioneer_DJ_Corporation_DDJ-REV1-00.analog-stereo.monitor'),
         'section': 'Audio'},
    ]


# --- tab bar wraps instead of overflowing ---------------------------------- #

def test_tab_bar_wraps_onto_a_second_row_when_it_would_overflow() -> None:
    ov = _ov()
    ov._config_editor_tabs = ['Effects', 'Audio', 'Hotkeys', 'Performance', 'Recording',
                              'Visuals', 'Streaming', 'Controllers', 'Experimental']
    boxes = ov._config_editor_tab_boxes((100.0, 80.0, 900.0, 900.0))
    xs_right = [bx + bw for _i, bx, _by, bw, _bh in boxes]
    assert max(xs_right) <= 100.0 + 900.0 - 22.0 + 1e-6, 'a tab ran off the panel'
    rows = {by for _i, _bx, by, _bw, _bh in boxes}
    assert len(rows) == 2
    assert ov._ce_tab_rows == 2
    # The body starts below the second row.
    assert ov._config_editor_body_top(80.0) > max(rows) + ov._CE_TAB_H


def test_tab_bar_stays_on_one_row_when_it_fits() -> None:
    ov = _ov()
    boxes = ov._config_editor_tab_boxes(ov._config_editor_panel_rect)
    assert len({by for _i, _bx, by, _bw, _bh in boxes}) == 1
    assert ov._ce_tab_rows == 1
    assert ov._config_editor_body_top(80.0) == 200.0  # unchanged from 1.x


# --- rendering registers one hit rect per control kind --------------------- #

def _render(ov: Overlays) -> None:
    ov._render_config_editor_param_rows(122.0, 200.0, 1356.0, 572.0, 'PERFORMANCE')


def test_render_registers_rows_sections_and_controls() -> None:
    ov = _ov(params=_rows())
    _render(ov)
    assert [i for *_r, i in ov._ce_param_row_rects] == [0, 1, 2, 3, 4]
    assert [i for *_r, i in ov._ce_slider_rects] == [0]
    assert [i for *_r, i in ov._ce_toggle_rects] == [2]
    chip_rows = sorted({i for *_r, i, _c in ov._ce_chip_rects})
    assert chip_rows == [1, 3, 4]
    # Section headers were drawn once per section change.
    headers = [a[0] for kind, a, *_ in ov.calls if kind == 'text' and a[0] in ('RENDER', 'PREVIEWS', 'AUDIO')]
    assert headers == ['RENDER', 'PREVIEWS', 'AUDIO']
    # The Performance vitals readout rides the title bar.
    assert any(kind == 'text' and a[0] == '59 FPS  17.0 MS' for kind, a, *_ in ov.calls)


def test_long_choice_labels_fall_back_to_prev_next_arrows() -> None:
    ov = _ov(params=_rows())
    _render(ov)
    audio_chips = [(c, w) for _x, _y, w, _h, i, c in ov._ce_chip_rects if i == 4]
    # Two arrow boxes targeting the neighbours, not one chip per label.
    assert sorted(c for c, _w in audio_chips) == [0, 2]
    assert all(w < 40 for _c, w in audio_chips)
    frame_chips = [c for *_r, i, c in ov._ce_chip_rects if i == 1]
    assert frame_chips == [0, 1, 2, 3]


# --- pointer input -> value requests -------------------------------------- #

def test_slider_click_sets_absolute_value_and_starts_a_drag() -> None:
    ov = _ov(params=_rows())
    _render(ov)
    sx, sy, sw, sh, _i = ov._ce_slider_rects[0]
    assert ov.handle_config_editor_click(sx + sw * 0.5, sy + sh * 0.5) is True
    idx, value = ov.take_config_editor_value_request()
    assert idx == 0
    assert abs(value - 0.75) < 1e-6           # halfway through 0.5..1.0
    assert ov.take_config_editor_value_request() is None
    assert ov._ce_drag_row == 0
    # Dragging keeps issuing requests; release ends it.
    ov.handle_config_editor_motion(sx + sw, sy)
    assert ov.take_config_editor_value_request() == (0, 1.0)
    ov.handle_config_editor_motion(sx - 50.0, sy)
    assert ov.take_config_editor_value_request() == (0, 0.5)  # clamped
    ov.handle_config_editor_release()
    assert ov._ce_drag_row == -1
    ov.handle_config_editor_motion(sx + sw * 0.25, sy)
    assert ov.take_config_editor_value_request() is None


def test_toggle_click_requests_the_flipped_value() -> None:
    ov = _ov(params=_rows())
    _render(ov)
    tx, ty, tw, th, _i = ov._ce_toggle_rects[0]
    assert ov.handle_config_editor_click(tx + tw / 2, ty + th / 2) is True
    assert ov.take_config_editor_value_request() == (2, 0.0)
    assert ov._ce_param_idx == 2
    ov._ce_params[2]['value'] = 0.0
    _render(ov)
    tx, ty, tw, th, _i = ov._ce_toggle_rects[0]
    ov.handle_config_editor_click(tx + tw / 2, ty + th / 2)
    assert ov.take_config_editor_value_request() == (2, 1.0)


def test_chip_click_requests_that_choice() -> None:
    ov = _ov(params=_rows())
    _render(ov)
    cx, cy, cw, ch, _i, choice = next(r for r in ov._ce_chip_rects if r[4] == 1 and r[5] == 3)
    assert ov.handle_config_editor_click(cx + cw / 2, cy + ch / 2) is True
    assert ov.take_config_editor_value_request() == (1, 3.0)
    assert ov._ce_param_idx == 1


def test_enter_flips_toggle_and_steps_choice_with_wrap() -> None:
    ov = _ov(params=_rows())
    ov._ce_param_idx = 2
    assert ov.activate_config_editor_row() is True
    assert ov.take_config_editor_value_request() == (2, 0.0)
    ov._ce_param_idx = 1                       # Frame limit at '30' (2)
    assert ov.activate_config_editor_row() is True
    assert ov.take_config_editor_value_request() == (1, 3.0)
    ov._ce_params[1]['value'] = 3.0
    assert ov.activate_config_editor_row() is True
    assert ov.take_config_editor_value_request() == (1, 0.0)  # wraps
    ov._ce_param_idx = 0                       # slider: Enter does nothing
    assert ov.activate_config_editor_row() is False


def test_row_click_selects_without_a_request() -> None:
    ov = _ov(params=_rows())
    _render(ov)
    rx, ry, rw, rh, _i = ov._ce_param_row_rects[3]
    assert ov.handle_config_editor_click(rx + 20.0, ry + rh / 2) is True
    assert ov._ce_param_idx == 3
    assert ov.take_config_editor_value_request() is None


def test_motion_hover_tracks_rows_chips_and_buttons() -> None:
    ov = _ov(params=_rows())
    ov._feed_modal_tooltips = lambda *a, **k: None
    _render(ov)
    rx, ry, rw, rh, _i = ov._ce_param_row_rects[3]
    ov.handle_config_editor_motion(rx + 20.0, ry + rh / 2)
    assert ov._ce_hover_row == 3
    cx, cy, cw, ch, _i, choice = next(r for r in ov._ce_chip_rects if r[4] == 1 and r[5] == 0)
    ov.handle_config_editor_motion(cx + cw / 2, cy + ch / 2)
    assert ov._ce_hover_control == 'chip:1:0'
    ov._ce_footer_button_rects = [(10.0, 10.0, 50.0, 20.0, 'save')]
    ov.handle_config_editor_motion(20.0, 20.0)
    assert ov._ce_hover_control == 'button:save'


def test_tooltip_regions_include_row_hints() -> None:
    ov = _ov(params=_rows())
    _render(ov)
    texts = {r.text for r in ov._config_editor_tooltip_regions()}
    assert 'Internal render resolution' in texts
    assert 'Edit Performance settings' in texts


# --- whole-panel render smoke --------------------------------------------- #

def test_full_render_smoke_on_every_tab() -> None:
    for tab in ('Effects', 'Audio', 'Hotkeys', 'Performance', 'Recording', 'Visuals'):
        ov = _ov(tab=tab, params=_rows() if tab != 'Hotkeys' else [
            {'name': 'Help', 'kind': 'bind', 'action': 'help', 'chord': 'H',
             'is_override': False}])
        ov._ce_effects = [{'class_name': 'Plasma', 'display_name': 'Plasma', 'active': True}]
        ov._ce_profiles = ['Look A']
        ov._render_config_editor()
        assert ov._ce_footer_button_rects, tab
        assert ov._ce_sparkles, 'sparkle anchors were not seeded'
        assert len(ov._ce_sparkles) == ov._CE_SPARKLE_COUNT
        if tab == 'Effects':
            assert ov._ce_effect_row_rects
