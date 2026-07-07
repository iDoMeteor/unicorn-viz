"""move_help_page(): unified left+right tab paging — regression tests.

PageUp/PageDown page through ONE combined sequence — left-pane section
pages, then the right pane's Effects/Post FX/Mouse tabs — rather than
moving both panes independently on every keypress (the previous behavior,
which the owner found "a little weird for normal people").

PageDown: left tab 1 -> ... -> left tab N -> right tab 1 -> ... -> right
tab M -> wraps back to left tab 1. PageUp is the exact reverse. Only one
pane's displayed tab changes per keypress; the other pane stays wherever
it was left.
"""
from __future__ import annotations

from unicornviz.overlays import Overlays


def _stub_overlays(left_sections: int, right_tabs: int) -> Overlays:
    """Build a stub with a controllable left-pane page count (via synthetic
    sections, HELP_SECTIONS_PER_TAB per page) and right-pane tab count (via
    postfx/mouse entries: 1 = Effects only, 2 = + Post FX, 3 = + Mouse)."""
    overlays = Overlays.__new__(Overlays)
    overlays._dynamic_help_sections = {}
    overlays._dynamic_help_order = []
    overlays._help_collapsed = {}
    overlays._help_item_page = {}
    overlays._help_focus_region = 'sections'
    overlays._help_focus_idx = 0
    overlays._help_tab_idx = 0
    overlays._help_tab_rects = []
    overlays._help_right_tab_idx = 0
    overlays._help_right_tab_rects = []
    overlays._help_active_pane = 'left'

    per_page = Overlays.HELP_SECTIONS_PER_TAB
    synthetic = [
        (f'Sec{i:02d}', [('k', 'd')]) for i in range(left_sections * per_page)
    ]
    overlays._iter_help_sections = lambda: synthetic

    overlays._postfx_help_entries = [('Ctrl+Alt+1', 'Chromatic Aberration')] if right_tabs >= 2 else []
    overlays._mouse_help_entries = [('Wheel Up/Down', 'Hue-shift frame')] if right_tabs >= 3 else []
    return overlays


# --------------------------------------------------------------------------- #
# Nothing to page
# --------------------------------------------------------------------------- #

def test_returns_false_when_neither_pane_has_multiple_tabs() -> None:
    overlays = _stub_overlays(left_sections=1, right_tabs=1)
    assert overlays.help_tab_count() == 1
    assert overlays.help_right_tab_count() == 1
    assert overlays.move_help_page(1) is False
    assert overlays.move_help_page(-1) is False


# --------------------------------------------------------------------------- #
# Forward (PageDown): left tabs, then cross into right tabs, then wrap
# --------------------------------------------------------------------------- #

def test_forward_steps_through_left_tabs_first() -> None:
    overlays = _stub_overlays(left_sections=3, right_tabs=1)
    assert overlays.move_help_page(1) is True
    assert (overlays.help_tab_index(), overlays.help_right_tab_index()) == (1, 0)
    overlays.move_help_page(1)
    assert overlays.help_tab_index() == 2


def test_forward_crosses_from_last_left_tab_to_first_right_tab() -> None:
    overlays = _stub_overlays(left_sections=2, right_tabs=3)
    overlays._help_tab_idx = 1  # already on the last left tab

    assert overlays.move_help_page(1) is True
    assert overlays.help_tab_index() == 1  # left pane stays put
    assert overlays.help_right_tab_index() == 0  # jumped to right's first tab


def test_forward_continues_through_right_tabs() -> None:
    overlays = _stub_overlays(left_sections=1, right_tabs=3)
    overlays._help_active_pane = 'right'
    overlays._help_right_tab_idx = 0

    assert overlays.move_help_page(1) is True
    assert overlays.help_right_tab_index() == 1
    overlays.move_help_page(1)
    assert overlays.help_right_tab_index() == 2


def test_forward_wraps_from_last_right_tab_to_first_left_tab() -> None:
    overlays = _stub_overlays(left_sections=2, right_tabs=3)
    overlays._help_active_pane = 'right'
    overlays._help_right_tab_idx = 2  # last right tab (Mouse)
    overlays._help_tab_idx = 1  # wherever the left pane was left

    assert overlays.move_help_page(1) is True
    assert overlays.help_tab_index() == 0  # wrapped to left's first tab
    assert overlays.help_right_tab_index() == 2  # right pane untouched


# --------------------------------------------------------------------------- #
# Backward (PageUp): the exact reverse
# --------------------------------------------------------------------------- #

def test_backward_steps_through_right_tabs_first_when_active() -> None:
    overlays = _stub_overlays(left_sections=1, right_tabs=3)
    overlays._help_active_pane = 'right'
    overlays._help_right_tab_idx = 2

    assert overlays.move_help_page(-1) is True
    assert overlays.help_right_tab_index() == 1


def test_backward_crosses_from_first_left_tab_to_last_right_tab() -> None:
    overlays = _stub_overlays(left_sections=2, right_tabs=3)
    overlays._help_tab_idx = 0  # already on the first left tab

    assert overlays.move_help_page(-1) is True
    assert overlays.help_tab_index() == 0  # left pane stays put
    assert overlays.help_right_tab_index() == 2  # jumped to right's LAST tab


def test_backward_wraps_from_first_right_tab_to_last_left_tab() -> None:
    overlays = _stub_overlays(left_sections=2, right_tabs=3)
    overlays._help_active_pane = 'right'
    overlays._help_right_tab_idx = 0  # first right tab (Effects)

    assert overlays.move_help_page(-1) is True
    assert overlays.help_tab_index() == 1  # wrapped to left's LAST tab


def test_forward_then_backward_returns_to_the_start() -> None:
    overlays = _stub_overlays(left_sections=2, right_tabs=2)
    start = (overlays.help_tab_index(), overlays.help_right_tab_index(), overlays._help_active_pane)

    for _ in range(4):  # left0->left1->right0->right1->(wrap)left0
        overlays.move_help_page(1)
    for _ in range(4):
        overlays.move_help_page(-1)

    end = (overlays.help_tab_index(), overlays.help_right_tab_index(), overlays._help_active_pane)
    assert end == start


# --------------------------------------------------------------------------- #
# Edge cases: one pane trivial (single tab), the other not
# --------------------------------------------------------------------------- #

def test_single_left_tab_passes_straight_through_to_right_pane() -> None:
    overlays = _stub_overlays(left_sections=1, right_tabs=3)
    assert overlays.move_help_page(1) is True
    assert overlays.help_right_tab_index() == 0
    assert overlays.help_tab_index() == 0  # only one left tab; stays at 0


def test_single_right_tab_is_a_pass_through_checkpoint() -> None:
    """With only 'Effects' on the right, crossing into the right pane
    immediately wraps back to the left pane on the next press instead of
    getting stuck."""
    overlays = _stub_overlays(left_sections=2, right_tabs=1)
    overlays._help_tab_idx = 1  # last left tab

    overlays.move_help_page(1)  # -> right tab 0 (only option)
    assert overlays.help_right_tab_index() == 0
    overlays.move_help_page(1)  # right tab 0 is also the last -> wraps
    assert overlays.help_tab_index() == 0


# --------------------------------------------------------------------------- #
# _help_focus_idx only resets when the left pane's displayed page changes
# --------------------------------------------------------------------------- #

def test_focus_idx_resets_when_left_tab_changes() -> None:
    overlays = _stub_overlays(left_sections=3, right_tabs=1)
    overlays._help_focus_idx = 5
    overlays.move_help_page(1)
    assert overlays._help_focus_idx == 0


def test_focus_idx_untouched_when_only_right_tab_changes() -> None:
    overlays = _stub_overlays(left_sections=1, right_tabs=3)
    overlays._help_active_pane = 'right'
    overlays._help_right_tab_idx = 0
    overlays._help_focus_idx = 5

    overlays.move_help_page(1)
    assert overlays.help_right_tab_index() == 1
    assert overlays._help_focus_idx == 5  # left pane didn't change
