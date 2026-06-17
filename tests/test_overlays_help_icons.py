from __future__ import annotations

from typing import Any

from unicornviz.overlays import Overlays


def _build_overlay_stub(width: int = 1920, height: int = 1080) -> Overlays:
    overlays = Overlays.__new__(Overlays)
    overlays._show_help = True
    overlays._width = width
    overlays._height = height
    overlays._help_icon_asset_bucket = '76px'
    overlays._help_focus_region = 'sections'
    overlays._help_icon_focus_idx = 0
    overlays._help_pulse_t = 0.0
    overlays._help_icon_hover_idx = -1
    overlays._help_icon_hover_pos = None
    overlays._hud_state = {
        'spotify_auth_visible': 'NO',
        'spotify_auth_status': 'OFF',
    }

    # Rendering helpers are replaced with no-op stubs for geometry-only tests.
    overlays._draw_rect = lambda *args, **kwargs: None
    overlays._draw_text = lambda *args, **kwargs: None
    return overlays


def test_help_usage_section_lists_tab_focus_toggle() -> None:
    help_usage = next(entries for name, entries in Overlays.CORE_HELP_SECTIONS if name == 'Help Usage')

    assert ('Tab', 'Toggle section/icon focus') in help_usage


def test_help_icon_order_places_settings_account_auth_rightmost() -> None:
    ids = [str(entry.get('id', '')) for entry in Overlays.HELP_ICON_ENTRIES]

    assert ids[-3:] == ['settings', 'account', 'login_out']


def test_help_icon_hit_test_matches_rendered_icon_cells() -> None:
    overlays = _build_overlay_stub()

    # Seed fake textures so the render path calls _draw_icon_texture for each icon.
    texture_ids = ['about', 'contact', 'share', 'shop', 'dropins', 'settings', 'account', 'login', 'logout']
    overlays._help_icon_textures = {icon_id: object() for icon_id in texture_ids}

    drawn_icons: list[tuple[float, float, float, float]] = []

    def _capture_icon(_tex: Any, x: float, y: float, w: float, h: float, *, alpha: float = 1.0) -> None:
        drawn_icons.append((x, y, w, h))

    overlays._draw_icon_texture = _capture_icon

    panel_x = 44.0
    icon_band_y = 44.0 + 100.0
    panel_w = overlays._width - 88.0
    res_ratio = min(overlays._width, overlays._height) / 1080.0
    help_scale = min(1.28, max(1.0, res_ratio ** 0.35))

    overlays._render_help_icon_rail(panel_x, icon_band_y, panel_w, help_scale)

    assert drawn_icons, 'expected icon draw calls to be captured'

    # Validate that hit-test resolves to the same icon index as the rendered cell.
    target_idx = 3
    x, y, w, h = drawn_icons[target_idx]
    cx = x + w * 0.5
    cy = y + h * 0.5

    assert overlays._help_icon_hit_test(cx, cy) == target_idx

    # A point above the rendered icon row should not hit any icon.
    assert overlays._help_icon_hit_test(cx, y - 6.0) == -1
