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
    # Minimal font/geometry state the layout math reads.
    ov._glyph_w = 13
    ov._glyph_h = 18
    ov._font_scale_norm = 8.0 / 18.0
    ov._width = 1920
    ov._height = 1080
    return ov


def _sample_entries() -> list[dict]:
    return [
        {'label': 'Open', 'header': True, 'enabled': False, 'sym': 0, 'mod': 0},
        {'label': 'Open Effects Browser', 'header': False, 'enabled': True,
         'sym': sdl2.SDLK_b, 'mod': 0, 'hotkey': 'B'},
        {'label': 'Enable Auto-Advance', 'header': False, 'enabled': True,
         'sym': sdl2.SDLK_t, 'mod': 0, 'hotkey': 'T'},
    ]


def test_open_and_close() -> None:
    ov = _bare_overlays()
    assert ov.context_menu_open is False
    ov.open_context_menu(_sample_entries(), 100.0, 200.0)
    assert ov.context_menu_open is True
    assert len(ov.context_menu_entries) == 3
    ov.close_context_menu()
    assert ov.context_menu_open is False


def test_click_selects_selectable_row() -> None:
    ov = _bare_overlays()
    ov.open_context_menu(_sample_entries(), 100.0, 200.0)
    layout = ov._context_menu_layout()
    rows = layout['rows']
    # Row index 1 is the first selectable entry (Effects Browser).
    row = rows[1]
    cx = layout['x'] + 20.0
    cy = row['y'] + row['h'] / 2.0
    assert ov.handle_context_menu_click(cx, cy) == 1


def test_click_on_header_is_noop() -> None:
    ov = _bare_overlays()
    ov.open_context_menu(_sample_entries(), 100.0, 200.0)
    layout = ov._context_menu_layout()
    header_row = layout['rows'][0]
    cx = layout['x'] + 20.0
    cy = header_row['y'] + header_row['h'] / 2.0
    assert ov.handle_context_menu_click(cx, cy) == -2


def test_click_outside_panel_closes() -> None:
    ov = _bare_overlays()
    ov.open_context_menu(_sample_entries(), 100.0, 200.0)
    layout = ov._context_menu_layout()
    far_x = layout['x'] + float(layout['w']) + 50.0
    assert ov.handle_context_menu_click(far_x, layout['y']) == -1


def test_motion_sets_hover() -> None:
    ov = _bare_overlays()
    ov.open_context_menu(_sample_entries(), 100.0, 200.0)
    layout = ov._context_menu_layout()
    row = layout['rows'][2]  # Auto-Advance
    cx = layout['x'] + 20.0
    cy = row['y'] + row['h'] / 2.0
    ov.handle_context_menu_motion(cx, cy)
    assert ov._context_menu_hover == 2


def test_layout_clamps_to_screen() -> None:
    ov = _bare_overlays()
    # Open near the far corner; panel must stay on-screen.
    ov.open_context_menu(_sample_entries(), 1900.0, 1070.0)
    layout = ov._context_menu_layout()
    assert layout['x'] + float(layout['w']) <= ov._width
    assert layout['y'] + float(layout['h']) <= ov._height


def test_dropin_help_entries_reads_dynamic_registry() -> None:
    ov = _bare_overlays()
    ov._dynamic_help_sections = {'Chat': [('Ctrl+Alt+T', 'Chat overlay on / off')]}
    ov._dynamic_help_order = ['Chat']
    assert ov.dropin_help_entries() == [('Chat', 'Ctrl+Alt+T', 'Chat overlay on / off')]
