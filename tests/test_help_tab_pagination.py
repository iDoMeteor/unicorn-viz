"""Help overlay tab pagination — regression tests.

A fully-loaded drop-in directory registers one help section per drop-in
(plus the core sections), which used to overflow the single scrollable pane
silently: sections past what fit in the two-column layout were simply never
drawn and were unreachable by keyboard (digit toggle / arrow focus only ever
walked the merged list, not what was visible). This paginates the merged
section list into tabs of at most Overlays.HELP_SECTIONS_PER_TAB (10)
headings each, so every section stays reachable regardless of how many
drop-ins are installed.

Tabs switch via mouse wheel (App._handle_help_wheel_scroll), not PageUp/
PageDown: webcam-01 claims those keys globally (camera switch) ahead of the
help-overlay dispatch in HotkeyHandler.handle(), so a keyboard binding here
would silently do nothing whenever the webcam drop-in is loaded (the default).
"""
from __future__ import annotations

from unicornviz.app import App
from unicornviz.overlays import Overlays


def _section(name: str) -> tuple[str, list[tuple[str, str]]]:
    return (name, [(f'{name}-key', f'{name}-desc')])


def _stub_overlays(section_count: int) -> Overlays:
    overlays = Overlays.__new__(Overlays)
    overlays._dynamic_help_sections = {}
    overlays._dynamic_help_order = []
    overlays._postfx_help_entries = []
    overlays._help_collapsed = {}
    overlays._help_focus_region = 'sections'
    overlays._help_focus_idx = 0
    overlays._help_tab_idx = 0
    overlays._help_tab_rects = []

    synthetic = [_section(f'Sec{i:02d}') for i in range(section_count)]
    overlays._iter_help_sections = lambda: synthetic
    return overlays


# --------------------------------------------------------------------------- #
# Pagination grouping
# --------------------------------------------------------------------------- #

def test_help_tab_groups_chunks_at_ten() -> None:
    overlays = _stub_overlays(23)
    groups = overlays._help_tab_groups()
    assert [len(g) for g in groups] == [10, 10, 3]


def test_help_tab_count_matches_group_count() -> None:
    overlays = _stub_overlays(23)
    assert overlays.help_tab_count() == 3


def test_help_tab_groups_returns_single_empty_page_when_no_sections() -> None:
    overlays = _stub_overlays(0)
    assert overlays._help_tab_groups() == [[]]
    assert overlays.help_tab_count() == 1


def test_ten_or_fewer_sections_is_a_single_tab() -> None:
    overlays = _stub_overlays(10)
    assert overlays.help_tab_count() == 1
    assert len(overlays._help_tab_groups()[0]) == 10


# --------------------------------------------------------------------------- #
# Navigation
# --------------------------------------------------------------------------- #

def test_move_help_tab_wraps_and_resets_focus() -> None:
    overlays = _stub_overlays(23)
    overlays._help_focus_idx = 5

    assert overlays.move_help_tab(1) is True
    assert overlays.help_tab_index() == 1
    assert overlays._help_focus_idx == 0

    overlays.move_help_tab(1)
    assert overlays.help_tab_index() == 2
    # Wraps back to the first tab.
    assert overlays.move_help_tab(1) is True
    assert overlays.help_tab_index() == 0


def test_move_help_tab_backward_wraps() -> None:
    overlays = _stub_overlays(23)
    assert overlays.move_help_tab(-1) is True
    assert overlays.help_tab_index() == 2


def test_move_help_tab_is_noop_with_a_single_tab() -> None:
    overlays = _stub_overlays(4)
    assert overlays.move_help_tab(1) is False
    assert overlays.help_tab_index() == 0


def test_set_help_tab_clamps_out_of_range_index() -> None:
    overlays = _stub_overlays(23)
    assert overlays.set_help_tab(99) is True
    assert overlays.help_tab_index() == 2
    assert overlays.set_help_tab(-5) is True
    assert overlays.help_tab_index() == 0


# --------------------------------------------------------------------------- #
# Section operations are scoped to the active tab
# --------------------------------------------------------------------------- #

def test_help_section_count_is_scoped_to_active_tab() -> None:
    overlays = _stub_overlays(23)
    assert overlays.help_section_count() == 10
    overlays.set_help_tab(2)
    assert overlays.help_section_count() == 3


def test_toggle_help_section_operates_within_active_tab() -> None:
    overlays = _stub_overlays(23)
    overlays.set_help_tab(1)

    # Index 0 on tab 2 is 'Sec10', not the global 'Sec00'.
    assert overlays.toggle_help_section(0) is True
    assert overlays._help_collapsed.get('Sec10') is True
    assert 'Sec00' not in overlays._help_collapsed


def test_move_help_focus_wraps_within_active_tab_only() -> None:
    overlays = _stub_overlays(23)
    overlays.set_help_tab(2)  # 3 sections on this tab
    overlays._help_focus_idx = 2

    assert overlays.move_help_focus(1) is True
    assert overlays._help_focus_idx == 0  # wraps at 3, not 23


def test_set_all_help_sections_collapsed_affects_every_tab() -> None:
    overlays = _stub_overlays(23)
    overlays.set_all_help_sections_collapsed(True)
    assert all(overlays._help_collapsed.get(f'Sec{i:02d}') is True for i in range(23))


# --------------------------------------------------------------------------- #
# register_help_entries clamps stale tab/focus indices
# --------------------------------------------------------------------------- #

def test_register_help_entries_clamps_tab_idx_when_sections_shrink() -> None:
    overlays = _stub_overlays(23)
    overlays.set_help_tab(2)
    assert overlays.help_tab_index() == 2

    # Rebuilding with far fewer sections should clamp back onto a valid tab.
    overlays._iter_help_sections = lambda: [_section('Only')]
    overlays.register_help_entries([('Only', 'k', 'd')])

    assert overlays.help_tab_index() == 0
    assert overlays._help_focus_idx == 0


# --------------------------------------------------------------------------- #
# Mouse click on the tab bar
# --------------------------------------------------------------------------- #

def test_handle_help_mouse_click_switches_tab() -> None:
    overlays = _stub_overlays(23)
    overlays._help_icon_entries = lambda: []
    overlays._help_tab_rects = [(0, 0.0, 0.0, 50.0, 30.0), (1, 60.0, 0.0, 50.0, 30.0)]

    assert overlays.handle_help_mouse_click(65.0, 10.0) is True
    assert overlays.help_tab_index() == 1


# --------------------------------------------------------------------------- #
# Mouse wheel drives tab switching (App._handle_help_wheel_scroll)
# --------------------------------------------------------------------------- #

class _WheelOverlay:
    def __init__(self) -> None:
        self.moves: list[int] = []

    def move_help_tab(self, delta: int) -> bool:
        self.moves.append(delta)
        return True


def _app_for_wheel() -> App:
    app = object.__new__(App)
    app._overlays = _WheelOverlay()
    return app


def test_wheel_scroll_up_moves_to_previous_tab() -> None:
    app = _app_for_wheel()
    app._handle_help_wheel_scroll(1)  # scroll up
    assert app._overlays.moves == [-1]


def test_wheel_scroll_down_moves_to_next_tab() -> None:
    app = _app_for_wheel()
    app._handle_help_wheel_scroll(-1)  # scroll down
    assert app._overlays.moves == [1]


def test_wheel_scroll_noop_is_ignored() -> None:
    app = _app_for_wheel()
    app._handle_help_wheel_scroll(0)
    assert app._overlays.moves == []
