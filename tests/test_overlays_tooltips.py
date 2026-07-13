"""Tests for the overlay system's tooltip integration.

Uses bare Overlays instances (object.__new__) with only the attributes
each code path needs — the same lightweight approach as the other
overlay-adjacent tests — so no moderngl context is required.
"""
from __future__ import annotations

from unicornviz.catalog_browser import CatalogBrowser
from unicornviz.overlays import Overlays
from unicornviz.tooltips import TooltipHoverTracker


def _bare_overlays() -> Overlays:
    o = object.__new__(Overlays)
    o._tooltips_enabled = True
    o._tooltip_tracker = TooltipHoverTracker(delay_s=0.0)
    o._rail_tooltip_tracker = TooltipHoverTracker(delay_s=0.0)
    o._tooltip_surface = ''
    o._dynamic_help_order = []
    o._dynamic_help_sections = {}
    return o


def test_lookup_help_key_finds_a_core_entry() -> None:
    o = _bare_overlays()
    section, entries = Overlays.CORE_HELP_SECTIONS[0]
    key, description = entries[0]
    assert o.lookup_help_key(description) == key
    assert o.lookup_help_key(description.upper()) == key  # case-insensitive


def test_lookup_help_key_returns_empty_for_unknown_description() -> None:
    o = _bare_overlays()
    assert o.lookup_help_key('definitely not a real help entry') == ''
    assert o.lookup_help_key('') == ''


def test_effects_browser_regions_carry_row_and_category_texts() -> None:
    o = _bare_overlays()
    browser = CatalogBrowser()
    browser.set_entries([
        {'display_name': 'Plasma', 'category_key': 'classic', 'tags': []},
        {'display_name': 'Fire', 'category_key': 'classic', 'tags': []},
    ])
    o._effects_browser = browser
    categories = browser.categories()
    o._eb_cat_rects = [(10.0, 10.0, 100.0, 20.0, i) for i in range(len(categories))]
    o._eb_row_rects = [
        (150.0, 10.0, 200.0, 20.0, 0),
        (150.0, 34.0, 200.0, 20.0, 1),
    ]

    regions = o._effects_browser_tooltip_regions()

    row_texts = [r.text for r in regions if r.rect[0] == 150]
    assert "Switch the audience output to 'Plasma'" in row_texts
    assert "Switch the audience output to 'Fire'" in row_texts
    cat_texts = [r.text for r in regions if r.rect[0] == 10]
    assert len(cat_texts) == len(categories)
    assert all(text.startswith('Filter to the ') for text in cat_texts)


def test_effects_browser_regions_skip_out_of_range_indices() -> None:
    o = _bare_overlays()
    o._effects_browser = CatalogBrowser()
    o._eb_cat_rects = [(10.0, 10.0, 100.0, 20.0, 5)]
    o._eb_row_rects = [(150.0, 10.0, 200.0, 20.0, 9)]
    assert o._effects_browser_tooltip_regions() == []


def test_presets_regions_use_preset_names() -> None:
    o = _bare_overlays()
    browser = CatalogBrowser()
    browser.set_entries([
        {'display_name': 'warmup', 'category_key': 'preset', 'tags': []},
    ])
    o._presets_browser = browser
    o._presets_row_rects = [(10.0, 10.0, 200.0, 20.0, 0)]
    regions = o._presets_tooltip_regions()
    assert [r.text for r in regions] == ["Load preset 'warmup'"]


def test_config_editor_regions_name_each_tab() -> None:
    o = _bare_overlays()
    o._config_editor_panel_rect = (0.0, 0.0, 800.0, 600.0)
    o._config_editor_tabs = ['Window', 'Audio']
    o._glyph_w = 8
    o._font_scale_norm = 1.0
    regions = o._config_editor_tooltip_regions()
    assert [r.text for r in regions] == [
        'Edit Window settings', 'Edit Audio settings',
    ]
    # Boxes must lay out left-to-right without overlap.
    assert regions[0].rect[0] < regions[1].rect[0]


def test_rail_regions_match_the_hit_test_geometry() -> None:
    o = _bare_overlays()
    o._show_help = True
    o._width = 1920
    o._height = 1080
    o._help_icon_asset_bucket = '76px'
    entries = [
        {'id': 'about', 'tooltip': 'About Unicorn Viz'},
        {'id': 'share', 'tooltip': 'Share this show'},
    ]
    o._help_icon_entries = lambda: entries
    o._hud_state = {}

    regions = o._help_icon_tooltip_regions()
    assert len(regions) == 2
    assert regions[0].text == 'About Unicorn Viz'
    for idx, region in enumerate(regions):
        rx, ry, rw, rh = region.rect
        cx = rx + rw / 2
        cy = ry + rh / 2
        assert o._help_icon_hit_test(cx, cy) == idx


def test_rail_regions_empty_when_help_hidden() -> None:
    o = _bare_overlays()
    o._show_help = False
    o._help_icon_entries = lambda: [{'id': 'about', 'tooltip': 'About'}]
    assert o._help_icon_tooltip_regions() == []
    assert o._help_icon_hit_test(100.0, 100.0) == -1


def test_render_active_tooltip_resets_when_the_surface_closes() -> None:
    o = _bare_overlays()
    o._show_effects_browser = False
    o._show_presets = False
    o._show_config_editor = False
    o._tooltip_surface = 'effects_browser'
    drawn: list[str] = []
    o._draw_tooltip_bubble = lambda text, anchor: drawn.append(text)

    from unicornviz.tooltips import TooltipRegion
    o._tooltip_tracker.on_motion(10, 10, [TooltipRegion((0, 0, 50, 50), 'Stale')])
    o._render_active_tooltip(route_modals_elsewhere=False)

    assert drawn == []
    assert o._tooltip_surface == ''
    assert o._tooltip_tracker.tick() is None


def test_render_active_tooltip_draws_for_a_visible_surface() -> None:
    o = _bare_overlays()
    o._show_effects_browser = True
    o._show_presets = False
    o._show_config_editor = False
    drawn: list[str] = []
    o._draw_tooltip_bubble = lambda text, anchor: drawn.append(text)

    from unicornviz.tooltips import TooltipRegion
    o._feed_modal_tooltips(
        'effects_browser', 10, 10, [TooltipRegion((0, 0, 50, 50), 'Live')],
    )
    o._render_active_tooltip(route_modals_elsewhere=False)
    assert drawn == ['Live']


def test_render_active_tooltip_suppressed_when_modals_routed_elsewhere() -> None:
    o = _bare_overlays()
    o._show_effects_browser = True
    drawn: list[str] = []
    o._draw_tooltip_bubble = lambda text, anchor: drawn.append(text)

    from unicornviz.tooltips import TooltipRegion
    o._feed_modal_tooltips(
        'effects_browser', 10, 10, [TooltipRegion((0, 0, 50, 50), 'Live')],
    )
    o._render_active_tooltip(route_modals_elsewhere=True)
    assert drawn == []
