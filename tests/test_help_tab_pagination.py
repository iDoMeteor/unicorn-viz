"""Help overlay tab pagination — regression tests.

A fully-loaded drop-in directory registers one help section per drop-in
(plus the core sections), which used to overflow the single scrollable pane
silently: sections past what fit in the two-column layout were simply never
drawn and were unreachable by keyboard (digit toggle / arrow focus only ever
walked the merged list, not what was visible). This paginates the merged
section list into tabs of at most Overlays.HELP_SECTIONS_PER_TAB headings
each, so every section stays reachable regardless of how many drop-ins are
installed. Tests reference the cap via the constant (not hardcoded numbers)
so a future cap change doesn't require rewriting the arithmetic here too.

Tabs switch with PageUp/PageDown. Some drop-ins (webcam-01) also register a
global VJApi key handler on the same keys (camera-device switch); the help
overlay must be checked for PageUp/PageDown ahead of that drop-in-handler
loop in HotkeyHandler.handle(), or the drop-in silently wins every time.
"""
from __future__ import annotations

from pathlib import Path

import sdl2

from unicornviz.app import App
from unicornviz.hotkeys import HotkeyHandler
from unicornviz.overlays import Overlays
from unicornviz.playlist import Playlist
from unicornviz.runtime_state import RuntimeStateStore


CAP = Overlays.HELP_SECTIONS_PER_TAB


def _section(name: str) -> tuple[str, list[tuple[str, str]]]:
    return (name, [(f'{name}-key', f'{name}-desc')])


def _stub_overlays(section_count: int) -> Overlays:
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

    synthetic = [_section(f'Sec{i:02d}') for i in range(section_count)]
    overlays._iter_help_sections = lambda: synthetic
    return overlays


# --------------------------------------------------------------------------- #
# Pagination grouping
# --------------------------------------------------------------------------- #

def test_help_tab_groups_chunks_at_cap() -> None:
    overlays = _stub_overlays(3 * CAP + 2)
    groups = overlays._help_tab_groups()
    assert [len(g) for g in groups] == [CAP, CAP, CAP, 2]


def test_help_tab_count_matches_group_count() -> None:
    overlays = _stub_overlays(3 * CAP + 2)
    assert overlays.help_tab_count() == 4


def test_help_tab_groups_returns_single_empty_page_when_no_sections() -> None:
    overlays = _stub_overlays(0)
    assert overlays._help_tab_groups() == [[]]
    assert overlays.help_tab_count() == 1


def test_cap_or_fewer_sections_is_a_single_tab() -> None:
    overlays = _stub_overlays(CAP)
    assert overlays.help_tab_count() == 1
    assert len(overlays._help_tab_groups()[0]) == CAP


# --------------------------------------------------------------------------- #
# Navigation
# --------------------------------------------------------------------------- #

def test_move_help_tab_wraps_and_resets_focus() -> None:
    overlays = _stub_overlays(3 * CAP + 2)
    overlays._help_focus_idx = 5

    assert overlays.move_help_tab(1) is True
    assert overlays.help_tab_index() == 1
    assert overlays._help_focus_idx == 0

    overlays.move_help_tab(1)
    assert overlays.help_tab_index() == 2
    overlays.move_help_tab(1)
    assert overlays.help_tab_index() == 3
    # Wraps back to the first tab.
    assert overlays.move_help_tab(1) is True
    assert overlays.help_tab_index() == 0


def test_move_help_tab_backward_wraps() -> None:
    overlays = _stub_overlays(3 * CAP + 2)
    assert overlays.move_help_tab(-1) is True
    assert overlays.help_tab_index() == 3


def test_move_help_tab_is_noop_with_a_single_tab() -> None:
    overlays = _stub_overlays(4)
    assert overlays.move_help_tab(1) is False
    assert overlays.help_tab_index() == 0


def test_set_help_tab_clamps_out_of_range_index() -> None:
    overlays = _stub_overlays(3 * CAP + 2)
    assert overlays.set_help_tab(99) is True
    assert overlays.help_tab_index() == 3
    assert overlays.set_help_tab(-5) is True
    assert overlays.help_tab_index() == 0


# --------------------------------------------------------------------------- #
# Section operations are scoped to the active tab
# --------------------------------------------------------------------------- #

def test_help_section_count_is_scoped_to_active_tab() -> None:
    overlays = _stub_overlays(3 * CAP + 2)
    assert overlays.help_section_count() == CAP
    overlays.set_help_tab(3)
    assert overlays.help_section_count() == 2


def test_toggle_help_section_operates_within_active_tab() -> None:
    overlays = _stub_overlays(3 * CAP + 2)
    overlays.set_help_tab(1)

    # Index 0 on tab 2 is 'SecCAP', not the global 'Sec00'.
    assert overlays.toggle_help_section(0) is True
    assert overlays._help_collapsed.get(f'Sec{CAP:02d}') is True
    assert 'Sec00' not in overlays._help_collapsed


def test_move_help_focus_wraps_within_active_tab_only() -> None:
    overlays = _stub_overlays(3 * CAP + 2)
    overlays.set_help_tab(3)  # 2 sections on this (last) tab
    overlays._help_focus_idx = 1

    assert overlays.move_help_focus(1) is True
    assert overlays._help_focus_idx == 0  # wraps at 2, not 3*CAP+2


def test_set_all_help_sections_collapsed_affects_every_tab() -> None:
    total = 3 * CAP + 2
    overlays = _stub_overlays(total)
    overlays.set_all_help_sections_collapsed(True)
    assert all(overlays._help_collapsed.get(f'Sec{i:02d}') is True for i in range(total))


# --------------------------------------------------------------------------- #
# register_help_entries clamps stale tab/focus indices
# --------------------------------------------------------------------------- #

def test_register_help_entries_clamps_tab_idx_when_sections_shrink() -> None:
    overlays = _stub_overlays(3 * CAP + 2)
    overlays.set_help_tab(3)
    assert overlays.help_tab_index() == 3

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
# End-to-end: help overlay outranks a drop-in that also claims PageUp/PageDown
# --------------------------------------------------------------------------- #

class _Audio:
    def get_reactivity(self) -> float:
        return 1.0


class _CameraSwitcherVJApi:
    """Stands in for a drop-in (webcam-01) that claims PageUp/PageDown globally."""

    def __init__(self) -> None:
        self.camera_switch_calls = 0

    def mark_user_action(self, _kind: str) -> None:
        return

    def key_handler_items(self):
        def _handle_key(sym: int, _mod: int):
            if sym in (sdl2.SDLK_PAGEUP, sdl2.SDLK_PAGEDOWN):
                self.camera_switch_calls += 1
                return 'Camera device: 0'
            return False
        return [('webcam', _handle_key)]


class _HelpOverlay:
    help_visible = True
    midi_selector_visible = False
    name_overlay_visible = False
    controller_help_modal_visible = False
    webcam_editor_modal_visible = False
    audio_selector_visible = False
    effects_browser_visible = False
    presets_visible = False
    projectm_manager_visible = False
    context_menu_open = False
    config_editor_open = False

    def __init__(self) -> None:
        self.moves: list[int] = []

    def note_help_activity(self) -> None:
        return

    def help_focus_region(self) -> str:
        return 'sections'

    def move_help_page(self, delta: int) -> bool:
        self.moves.append(delta)
        return True

    def flash_message(self, *_a, **_kw) -> None:
        return


def _fx(name: str):
    return type(name, (), {'NAME': name, 'TAGS': [], 'parameters': {}})


class _StubCfg:
    def get(self, *_keys, default=None):
        return default


def _app_and_playlist(tmp_path: Path, vj_api) -> tuple[App, Playlist]:
    effects = [_fx('A')]
    playlist = Playlist(effects, _StubCfg())

    app = object.__new__(App)
    app._runtime_state = RuntimeStateStore(tmp_path / 'state.json')
    app._disabled_effects = set()
    app._playlist = playlist
    app._effect_lock = None
    app._overlays = None
    app._current_effect = playlist.current()
    app._auto_vj = None
    app._keystroke_logger = None
    app.vj_api = vj_api
    app.hotkey_overrides = lambda: {}
    return app, playlist


def test_help_tab_switch_wins_over_a_drop_in_claiming_the_same_keys(tmp_path: Path) -> None:
    vj_api = _CameraSwitcherVJApi()
    app, playlist = _app_and_playlist(tmp_path, vj_api)
    overlay = _HelpOverlay()
    handler = HotkeyHandler(app, playlist, overlay, _Audio())

    handler.handle(sdl2.SDLK_PAGEDOWN, 0)
    handler.handle(sdl2.SDLK_PAGEUP, 0)

    assert overlay.moves == [1, -1]
    assert vj_api.camera_switch_calls == 0  # help never falls through to the drop-in


def test_pageup_pagedown_falls_through_when_move_help_page_reports_nothing_to_page(tmp_path: Path) -> None:
    """move_help_page() returning False (nothing to page in either pane)
    must let the keypress fall through to a drop-in bound to the same keys."""
    vj_api = _CameraSwitcherVJApi()
    app, playlist = _app_and_playlist(tmp_path, vj_api)
    overlay = _HelpOverlay()
    overlay.move_help_page = lambda _delta: False
    handler = HotkeyHandler(app, playlist, overlay, _Audio())

    handler.handle(sdl2.SDLK_PAGEDOWN, 0)

    assert vj_api.camera_switch_calls == 1


def test_drop_in_still_gets_pageup_pagedown_when_help_is_closed(tmp_path: Path) -> None:
    vj_api = _CameraSwitcherVJApi()
    app, playlist = _app_and_playlist(tmp_path, vj_api)
    overlay = _HelpOverlay()
    overlay.help_visible = False
    handler = HotkeyHandler(app, playlist, overlay, _Audio())

    handler.handle(sdl2.SDLK_PAGEDOWN, 0)

    assert overlay.moves == []
    assert vj_api.camera_switch_calls == 1
