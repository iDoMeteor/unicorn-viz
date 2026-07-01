"""Right-click context menu — regression tests.

Covers the three pillars of the feature:

* ``parse_hotkey_chord`` — turns help-style key labels into ``(sym, mod)`` and
  rejects non-chord forms (ranges, multi-key, wheel gestures).
* ``App._build_context_menu_model`` — core modals/toggles/actions with
  state-aware toggle labels, plus drop-in entries pulled **dynamically** from
  the help registry (never hard-coded).
* ``Overlays`` context-menu open/close, layout hit-testing, and hover.

None of these require a GL context; the Overlays instance is built with
``__new__`` and given the handful of font/geometry attributes the layout math
needs.
"""
from __future__ import annotations

import sdl2

from unicornviz.app import App
from unicornviz.hotkeys import parse_hotkey_chord
from unicornviz.overlays import Overlays


# --------------------------------------------------------------------------- #
# parse_hotkey_chord
# --------------------------------------------------------------------------- #

def test_parse_chord_single_key() -> None:
    assert parse_hotkey_chord('B') == (sdl2.SDLK_b, 0)


def test_parse_chord_with_modifiers() -> None:
    sym, mod = parse_hotkey_chord('Ctrl+Shift+P')
    assert sym == sdl2.SDLK_p
    assert mod & sdl2.KMOD_CTRL
    assert mod & sdl2.KMOD_SHIFT
    assert not (mod & sdl2.KMOD_ALT)


def test_parse_chord_function_and_symbol_keys() -> None:
    assert parse_hotkey_chord('F9') == (sdl2.SDLK_F9, 0)
    sym, mod = parse_hotkey_chord('Ctrl+Alt+[')
    assert sym == sdl2.SDLK_LEFTBRACKET
    assert mod & sdl2.KMOD_CTRL and mod & sdl2.KMOD_ALT


def test_parse_chord_alias_esc() -> None:
    assert parse_hotkey_chord('ESC') == (sdl2.SDLK_ESCAPE, 0)


def test_parse_chord_rejects_non_chords() -> None:
    for bad in ('n / Right', '0 - 9', 'Wheel Up/Down', 'Number', 'Middle Click', '', '   '):
        assert parse_hotkey_chord(bad) is None


# --------------------------------------------------------------------------- #
# App._build_context_menu_model
# --------------------------------------------------------------------------- #

class _StubOverlays:
    def __init__(self, dropin_entries: list[tuple[str, str, str]]) -> None:
        self._dropin_entries = dropin_entries
        self._recording_active = False
        self.name_overlay_visible = False

    def dropin_help_entries(self) -> list[tuple[str, str, str]]:
        return list(self._dropin_entries)


def _app_with(dropin_entries=None, *, auto_advance=True, paused=False,
              invert=False, fullscreen=False) -> App:
    app = object.__new__(App)
    app._overlays = _StubOverlays(dropin_entries or [])
    app._auto_advance = auto_advance
    app._paused = paused
    app._invert_colors = invert
    app._fullscreen = fullscreen
    app._hotkeys = None
    return app


def _labels(entries: list[dict]) -> list[str]:
    return [str(e['label']) for e in entries]


def test_model_has_core_modals_with_open_prefix() -> None:
    entries = _app_with()._build_context_menu_model()
    labels = _labels(entries)
    assert 'Open Effects Browser' in labels
    assert 'Open System Monitor' in labels
    assert 'Open Show Presets' in labels
    # Every modal-kind entry uses the "Open <context>" convention.
    for e in entries:
        if e.get('kind') == 'modal':
            assert str(e['label']).startswith('Open ')


def test_toggle_labels_are_state_aware() -> None:
    off = _app_with(auto_advance=False, paused=False, invert=False, fullscreen=False)
    on = _app_with(auto_advance=True, paused=True, invert=True, fullscreen=True)
    off_labels = _labels(off._build_context_menu_model())
    on_labels = _labels(on._build_context_menu_model())

    assert 'Enable Auto-Advance' in off_labels
    assert 'Disable Auto-Advance' in on_labels
    assert 'Pause Playback' in off_labels
    assert 'Resume Playback' in on_labels
    assert 'Enable Invert Colors' in off_labels
    assert 'Disable Invert Colors' in on_labels
    assert 'Enter Fullscreen' in off_labels
    assert 'Exit Fullscreen' in on_labels


def test_toggle_entries_carry_correct_binding() -> None:
    entries = _app_with(auto_advance=False)._build_context_menu_model()
    aa = next(e for e in entries if 'Auto-Advance' in str(e['label']))
    assert aa['sym'] == sdl2.SDLK_t
    assert aa['mod'] == 0


def test_dropin_entries_are_generated_not_hardcoded() -> None:
    # A drop-in the core knows nothing about, exposed only via help entries.
    dropin = [
        ('Chat', 'Ctrl+Alt+T', 'Chat overlay on / off'),
        ('Chat', 'Ctrl+Alt+[', 'Chat position cycle forward (lasts 3 s idle)'),
        ('Media', 'Ctrl+Alt+M', 'Local media play / pause'),
        # Non-chord help line must be skipped.
        ('Media', 'Wheel Up/Down', 'Volume'),
    ]
    entries = _app_with(dropin)._build_context_menu_model()
    labels = _labels(entries)

    # Section headers + generated entries present.
    assert 'Chat' in labels  # header
    assert 'Chat overlay on / off' in labels
    assert 'Local media play / pause' in labels
    # Parenthetical hint trimmed from the label.
    assert 'Chat position cycle forward' in labels
    # Non-chord line skipped.
    assert 'Volume' not in labels

    # The dynamic chat toggle carries the parsed binding.
    chat = next(e for e in entries if e['label'] == 'Chat overlay on / off')
    assert chat['kind'] == 'dropin'
    assert chat['sym'] == sdl2.SDLK_t
    assert chat['mod'] & sdl2.KMOD_CTRL and chat['mod'] & sdl2.KMOD_ALT


def test_model_without_dropins_still_valid() -> None:
    entries = _app_with([])._build_context_menu_model()
    labels = _labels(entries)
    assert 'Quit' in labels
    assert 'Next Effect' in labels


# --------------------------------------------------------------------------- #
# Overlays context-menu state + hit-testing (no GL)
# --------------------------------------------------------------------------- #

def _bare_overlays() -> Overlays:
    ov = Overlays.__new__(Overlays)
    ov._context_menu_open = False
    ov._context_menu_entries = []
    ov._context_menu_x = 0.0
    ov._context_menu_y = 0.0
    ov._context_menu_hover = -1
    ov._context_menu_expanded = set()
    # Minimal font/geometry state the layout math reads.
    ov._glyph_w = 13
    ov._glyph_h = 18
    ov._font_scale_norm = 8.0 / 18.0
    ov._width = 1920
    ov._height = 1080
    return ov


def _sample_entries() -> list[dict]:
    # Index 0 is a collapsible section header; 1 and 2 are its items.
    return [
        {'label': 'Open', 'header': True, 'enabled': False, 'sym': 0, 'mod': 0},
        {'label': 'Open Effects Browser', 'header': False, 'enabled': True,
         'sym': sdl2.SDLK_b, 'mod': 0, 'hotkey': 'B'},
        {'label': 'Enable Auto-Advance', 'header': False, 'enabled': True,
         'sym': sdl2.SDLK_t, 'mod': 0, 'hotkey': 'T'},
    ]


def _row_for(layout: dict, entry_index: int) -> dict | None:
    return next((r for r in layout['rows'] if r['index'] == entry_index), None)


def _click_center(ov: Overlays, layout: dict, row: dict) -> int:
    cx = layout['x'] + 20.0
    cy = row['y'] + row['h'] / 2.0
    return ov.handle_context_menu_click(cx, cy)


def test_open_and_close() -> None:
    ov = _bare_overlays()
    assert ov.context_menu_open is False
    ov.open_context_menu(_sample_entries(), 100.0, 200.0)
    assert ov.context_menu_open is True
    assert len(ov.context_menu_entries) == 3
    ov.close_context_menu()
    assert ov.context_menu_open is False


def test_sections_collapsed_by_default() -> None:
    ov = _bare_overlays()
    ov.open_context_menu(_sample_entries(), 100.0, 200.0)
    layout = ov._context_menu_layout()
    # Only the header row is visible; its items are hidden until expanded.
    assert _row_for(layout, 0) is not None
    assert _row_for(layout, 1) is None
    assert _row_for(layout, 2) is None


def test_clicking_header_expands_and_collapses() -> None:
    ov = _bare_overlays()
    ov.open_context_menu(_sample_entries(), 100.0, 200.0)
    layout = ov._context_menu_layout()
    header_row = _row_for(layout, 0)
    assert header_row is not None and header_row['collapsible']

    # First click expands the section (no-op return, menu stays open).
    assert _click_center(ov, layout, header_row) == -2
    assert 0 in ov._context_menu_expanded
    layout2 = ov._context_menu_layout()
    assert _row_for(layout2, 1) is not None  # items now visible

    # Clicking the header again collapses it.
    assert _click_center(ov, layout2, _row_for(layout2, 0)) == -2
    assert 0 not in ov._context_menu_expanded


def test_click_selects_item_once_expanded() -> None:
    ov = _bare_overlays()
    ov.open_context_menu(_sample_entries(), 100.0, 200.0)
    ov._context_menu_expanded.add(0)  # expand 'Open'
    layout = ov._context_menu_layout()
    row = _row_for(layout, 1)  # Effects Browser item
    assert row is not None
    assert _click_center(ov, layout, row) == 1


def test_click_outside_panel_closes() -> None:
    ov = _bare_overlays()
    ov.open_context_menu(_sample_entries(), 100.0, 200.0)
    layout = ov._context_menu_layout()
    far_x = layout['x'] + float(layout['w']) + 50.0
    assert ov.handle_context_menu_click(far_x, layout['y']) == -1


def test_motion_sets_hover_on_expanded_item() -> None:
    ov = _bare_overlays()
    ov.open_context_menu(_sample_entries(), 100.0, 200.0)
    ov._context_menu_expanded.add(0)
    layout = ov._context_menu_layout()
    row = _row_for(layout, 2)  # Auto-Advance
    assert row is not None
    ov.handle_context_menu_motion(layout['x'] + 20.0, row['y'] + row['h'] / 2.0)
    assert ov._context_menu_hover == 2


def test_non_collapsible_footer_always_visible() -> None:
    entries = _sample_entries() + [
        {'label': '', 'header': True, 'enabled': False, 'sym': 0, 'mod': 0},
        {'label': 'Quit', 'header': False, 'enabled': True,
         'sym': sdl2.SDLK_ESCAPE, 'mod': 0, 'hotkey': 'Esc'},
    ]
    ov = _bare_overlays()
    ov.open_context_menu(entries, 100.0, 200.0)
    layout = ov._context_menu_layout()
    # Quit (index 4) is under an empty-title separator header → always shown.
    quit_row = _row_for(layout, 4)
    assert quit_row is not None and quit_row['selectable']
    assert _click_center(ov, layout, quit_row) == 4


def test_layout_clamps_to_screen_when_expanded() -> None:
    ov = _bare_overlays()
    ov.open_context_menu(_sample_entries(), 1900.0, 1070.0)
    ov._context_menu_expanded.add(0)
    layout = ov._context_menu_layout()
    assert layout['x'] + float(layout['w']) <= ov._width
    assert layout['y'] + float(layout['h']) <= ov._height


def test_dropin_help_entries_reads_dynamic_registry() -> None:
    ov = _bare_overlays()
    ov._dynamic_help_sections = {'Chat': [('Ctrl+Alt+T', 'Chat overlay on / off')]}
    ov._dynamic_help_order = ['Chat']
    assert ov.dropin_help_entries() == [('Chat', 'Ctrl+Alt+T', 'Chat overlay on / off')]
