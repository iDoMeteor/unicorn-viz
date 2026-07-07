"""Help overlay right-pane tabs (Effects / Post FX / Mouse) — regression tests.

The right pane used to always show "LIVE SHORTCUT MAP" (the 1-40 hotkey
map) with a "POST FX" list crammed underneath it, while the left pane
gained its own tab bar for section pagination — leaving the two panes
vertically misaligned (left pane's content starts below its tab bar; right
pane's didn't reserve any such space). Splitting the right pane into named
tabs — Effects (always present), Post FX and Mouse (only when a drop-in has
actually registered entries for them) — restores that alignment and lets
each view use the full pane instead of being stacked.

'Post FX' entries come from postfx_controller.py's HELP_ENTRIES (numbered
quick-hit triggers); 'Mouse' entries are the scroll-wheel/click controls,
registered under a 'Mouse' section so register_help_entries() routes them
separately instead of lumping them in with the numbered Post FX list.
"""
from __future__ import annotations

from unicornviz.overlays import Overlays


def _stub_overlays() -> Overlays:
    overlays = Overlays.__new__(Overlays)
    overlays._dynamic_help_sections = {}
    overlays._dynamic_help_order = []
    overlays._postfx_help_entries = []
    overlays._mouse_help_entries = []
    overlays._help_collapsed = {}
    overlays._help_item_page = {}
    overlays._help_focus_region = 'sections'
    overlays._help_focus_idx = 0
    overlays._help_tab_idx = 0
    overlays._help_tab_rects = []
    overlays._help_right_tab_idx = 0
    overlays._help_right_tab_rects = []
    overlays._help_item_page_rects = []
    overlays._iter_help_sections = lambda: []
    return overlays


# --------------------------------------------------------------------------- #
# _help_right_tabs: conditional visibility
# --------------------------------------------------------------------------- #

def test_only_effects_tab_when_no_postfx_or_mouse_entries() -> None:
    overlays = _stub_overlays()
    assert overlays._help_right_tabs() == ['Effects']


def test_postfx_tab_appears_only_when_entries_exist() -> None:
    overlays = _stub_overlays()
    overlays._postfx_help_entries = [('Ctrl+Alt+1', 'Chromatic Aberration')]
    assert overlays._help_right_tabs() == ['Effects', 'Post FX']


def test_mouse_tab_appears_only_when_entries_exist() -> None:
    overlays = _stub_overlays()
    overlays._mouse_help_entries = [('Wheel Up/Down', 'Hue-shift frame')]
    assert overlays._help_right_tabs() == ['Effects', 'Mouse']


def test_all_three_tabs_when_both_postfx_and_mouse_present() -> None:
    overlays = _stub_overlays()
    overlays._postfx_help_entries = [('Ctrl+Alt+1', 'Chromatic Aberration')]
    overlays._mouse_help_entries = [('Wheel Up/Down', 'Hue-shift frame')]
    assert overlays._help_right_tabs() == ['Effects', 'Post FX', 'Mouse']


# --------------------------------------------------------------------------- #
# Navigation: set/move/clamp
# --------------------------------------------------------------------------- #

def _three_tab_overlays() -> Overlays:
    overlays = _stub_overlays()
    overlays._postfx_help_entries = [('Ctrl+Alt+1', 'Chromatic Aberration')]
    overlays._mouse_help_entries = [('Wheel Up/Down', 'Hue-shift frame')]
    return overlays


def test_help_right_tab_count_and_index() -> None:
    overlays = _three_tab_overlays()
    assert overlays.help_right_tab_count() == 3
    assert overlays.help_right_tab_index() == 0
    assert overlays.help_right_tab_name() == 'Effects'


def test_set_help_right_tab_selects_by_index() -> None:
    overlays = _three_tab_overlays()
    assert overlays.set_help_right_tab(2) is True
    assert overlays.help_right_tab_index() == 2
    assert overlays.help_right_tab_name() == 'Mouse'


def test_set_help_right_tab_clamps_out_of_range() -> None:
    overlays = _three_tab_overlays()
    assert overlays.set_help_right_tab(99) is True
    assert overlays.help_right_tab_index() == 2
    assert overlays.set_help_right_tab(-5) is True
    assert overlays.help_right_tab_index() == 0


def test_move_help_right_tab_wraps() -> None:
    overlays = _three_tab_overlays()
    assert overlays.move_help_right_tab(1) is True
    assert overlays.help_right_tab_index() == 1
    overlays.move_help_right_tab(1)
    assert overlays.help_right_tab_index() == 2
    assert overlays.move_help_right_tab(1) is True
    assert overlays.help_right_tab_index() == 0  # wraps


def test_move_help_right_tab_is_noop_with_a_single_tab() -> None:
    overlays = _stub_overlays()  # only 'Effects'
    assert overlays.move_help_right_tab(1) is False
    assert overlays.help_right_tab_index() == 0


# --------------------------------------------------------------------------- #
# register_help_entries: 'Mouse' section is siphoned like 'Post FX' already is
# --------------------------------------------------------------------------- #

def test_register_help_entries_routes_mouse_section_separately() -> None:
    overlays = _stub_overlays()
    overlays.register_help_entries([
        ('Mouse', 'Wheel Up/Down', 'Hue-shift frame (lasts 3 s idle)'),
        ('Mouse', 'Middle Click', 'Reset scroll FX (hue/rotation)'),
        ('Post FX', 'Ctrl+Alt+1', 'Chromatic Aberration'),
        ('Webcam', 'Ctrl+Alt+K', 'Webcam editor modal'),
    ])
    assert overlays._mouse_help_entries == [
        ('Wheel Up/Down', 'Hue-shift frame (lasts 3 s idle)'),
        ('Middle Click', 'Reset scroll FX (hue/rotation)'),
    ]
    assert overlays._postfx_help_entries == [('Ctrl+Alt+1', 'Chromatic Aberration')]
    # 'Mouse' and 'Post FX' entries never become ordinary left-pane sections.
    assert 'Mouse' not in overlays._dynamic_help_order
    assert 'Post FX' not in overlays._dynamic_help_order
    assert 'Webcam' in overlays._dynamic_help_order


def test_register_help_entries_mouse_section_is_case_insensitive() -> None:
    overlays = _stub_overlays()
    overlays.register_help_entries([('mouse', 'Wheel Up/Down', 'Hue-shift frame')])
    assert overlays._mouse_help_entries == [('Wheel Up/Down', 'Hue-shift frame')]


def test_register_help_entries_clamps_right_tab_when_entries_disappear() -> None:
    overlays = _three_tab_overlays()
    overlays.set_help_right_tab(2)  # Mouse
    assert overlays.help_right_tab_index() == 2

    # Re-registering without the mouse entries should clamp back to a valid tab.
    overlays.register_help_entries([('Post FX', 'Ctrl+Alt+1', 'Chromatic Aberration')])
    assert overlays._help_right_tabs() == ['Effects', 'Post FX']
    assert overlays.help_right_tab_index() == 1


# --------------------------------------------------------------------------- #
# Mouse click switches the right-pane tab
# --------------------------------------------------------------------------- #

def test_handle_help_mouse_click_switches_right_tab() -> None:
    overlays = _three_tab_overlays()
    overlays._help_tab_rects = []
    overlays._help_right_tab_rects = [
        (0, 0.0, 0.0, 50.0, 30.0),
        (1, 60.0, 0.0, 50.0, 30.0),
        (2, 120.0, 0.0, 50.0, 30.0),
    ]
    overlays._help_icon_entries = lambda: []

    assert overlays.handle_help_mouse_click(65.0, 10.0) is True
    assert overlays.help_right_tab_index() == 1


def test_left_tab_click_is_still_checked_before_right_tab_click() -> None:
    """Left-pane tab rects and right-pane tab rects must not shadow each
    other now that both exist in the same click-handling method."""
    overlays = _three_tab_overlays()
    # More than one tab's worth of left-pane sections so set_help_tab(1)
    # lands on a real second tab instead of being clamped back to 0.
    section_count = Overlays.HELP_SECTIONS_PER_TAB + 1
    overlays._iter_help_sections = lambda: [
        (f'Sec{i}', [('k', 'd')]) for i in range(section_count)
    ]
    overlays._help_tab_rects = [(0, 0.0, 0.0, 40.0, 20.0), (1, 50.0, 0.0, 40.0, 20.0)]
    overlays._help_right_tab_rects = [(0, 500.0, 0.0, 40.0, 20.0), (1, 550.0, 0.0, 40.0, 20.0)]
    overlays._help_icon_entries = lambda: []

    assert overlays.handle_help_mouse_click(55.0, 10.0) is True
    assert overlays.help_tab_index() == 1
    assert overlays.help_right_tab_index() == 0  # untouched


# --------------------------------------------------------------------------- #
# Vertical alignment: both tab bars use the same height formula
# --------------------------------------------------------------------------- #

def test_left_and_right_tab_bars_share_the_same_height_formula() -> None:
    """The whole point of adding right-pane tabs was to match the left
    pane's tab bar height so the two panes' content starts at the same Y."""
    import inspect
    src = inspect.getsource(Overlays._draw_help_section_content)
    assert src.count('34.0 * help_scale') == 2, (
        'left and right tab bar heights must use the same literal formula '
        '(34.0 * help_scale) so the panes stay vertically aligned'
    )
