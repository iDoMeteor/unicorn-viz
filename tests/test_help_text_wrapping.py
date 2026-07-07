"""Help overlay label/description word-wrap — regression tests.

Section cards used to draw each (key, description) row as one unbroken
line (f'{key:<12} {desc}'), with no regard for the section card's column
width. A long key (e.g. 'PageUp / PageDown') or a long description (e.g.
Delete's "Disable current effect & skip (ProjectM: disable preset)")
overflowed straight past the card and the pane's right edge instead of
wrapping — visible as clipped text in the help overlay screenshot.

The fix wraps text to the available column width instead of truncating it
(no text/words are ever dropped): _wrap_plain_text for section headers,
_wrap_help_entry (hanging-indent continuation lines) for rows, both built
on the shared _wrap_words_two_budget greedy wrapper.

Column dimensions below (avail_w ~= 548px, item scale 2.1, title scale 2.3)
are reproduced from Overlays._draw_help_section_content's own formulas at
a 1920x1080 canvas (help_scale == 1.0) so the budgets match production.
"""
from __future__ import annotations

from unicornviz.overlays import Overlays

# Matches _draw_help_section_content at width=1920 (help_scale == 1.0).
REALISTIC_AVAIL_W = 548.24
TITLE_SCALE = 2.30
ITEM_SCALE = 2.10


def _stub_overlays() -> Overlays:
    overlays = Overlays.__new__(Overlays)
    overlays._glyph_w = 8
    overlays._glyph_h = 8
    overlays._font_scale_norm = 8.0 / 8.0
    return overlays


# --------------------------------------------------------------------------- #
# _help_text_max_chars
# --------------------------------------------------------------------------- #

def test_max_chars_scales_with_available_width() -> None:
    overlays = _stub_overlays()
    narrow = overlays._help_text_max_chars(80.0, 2.0)
    wide = overlays._help_text_max_chars(800.0, 2.0)
    assert wide > narrow


def test_max_chars_has_a_sane_floor_for_tiny_widths() -> None:
    overlays = _stub_overlays()
    assert overlays._help_text_max_chars(1.0, 2.0) >= 4


def test_max_chars_matches_realistic_column_budget() -> None:
    overlays = _stub_overlays()
    assert overlays._help_text_max_chars(REALISTIC_AVAIL_W, ITEM_SCALE) == 32


# --------------------------------------------------------------------------- #
# _wrap_plain_text (section headers)
# --------------------------------------------------------------------------- #

def test_plain_text_short_enough_stays_on_one_line() -> None:
    overlays = _stub_overlays()
    lines = overlays._wrap_plain_text('1. - HELP USAGE (9)', REALISTIC_AVAIL_W, TITLE_SCALE)
    assert lines == ['1. - HELP USAGE (9)']


def test_plain_text_wraps_a_long_header_instead_of_overflowing() -> None:
    overlays = _stub_overlays()
    # Narrower than the realistic budget so a normal section header header
    # is forced to wrap, without resorting to an unrealistically tiny width.
    avail_w = REALISTIC_AVAIL_W / 3.0
    text = '10. - PROJECTM PRESETS (5)'
    lines = overlays._wrap_plain_text(text, avail_w, TITLE_SCALE)
    max_chars = overlays._help_text_max_chars(avail_w, TITLE_SCALE)
    assert len(lines) > 1
    assert all(len(line) <= max_chars for line in lines)


def test_plain_text_never_drops_words() -> None:
    overlays = _stub_overlays()
    text = '10. - PROJECTM PRESETS (5)'
    lines = overlays._wrap_plain_text(text, REALISTIC_AVAIL_W / 3.0, TITLE_SCALE)
    assert ' '.join(lines).split() == text.split()


# --------------------------------------------------------------------------- #
# _wrap_help_entry (key/description rows) at realistic column widths
# --------------------------------------------------------------------------- #

def test_long_key_wraps_instead_of_overflowing() -> None:
    """Regression: 'PageUp / PageDown' (18 chars) overflowed the :<12 column."""
    overlays = _stub_overlays()
    lines = overlays._wrap_help_entry(
        'PageUp / PageDown', 'Switch help tab (page)', REALISTIC_AVAIL_W, ITEM_SCALE,
    )
    max_chars = overlays._help_text_max_chars(REALISTIC_AVAIL_W, ITEM_SCALE)
    assert all(len(line) <= max_chars for line in lines)


def test_long_description_wraps_instead_of_overflowing() -> None:
    """Regression: Delete's long ProjectM caveat ran off the Basics card."""
    overlays = _stub_overlays()
    lines = overlays._wrap_help_entry(
        'Delete',
        'Disable current effect & skip (ProjectM: disable preset)',
        REALISTIC_AVAIL_W,
        ITEM_SCALE,
    )
    max_chars = overlays._help_text_max_chars(REALISTIC_AVAIL_W, ITEM_SCALE)
    assert len(lines) > 1
    assert all(len(line) <= max_chars for line in lines)


def test_long_description_never_drops_words() -> None:
    overlays = _stub_overlays()
    key, desc = 'Delete', 'Disable current effect & skip (ProjectM: disable preset)'
    lines = overlays._wrap_help_entry(key, desc, REALISTIC_AVAIL_W, ITEM_SCALE)
    assert lines[0].strip().startswith(key)
    all_words = ' '.join(lines).split()
    assert set(desc.split()) <= set(all_words)


def test_help_entry_continuation_lines_are_hang_indented() -> None:
    overlays = _stub_overlays()
    lines = overlays._wrap_help_entry(
        'Delete',
        'Disable current effect & skip (ProjectM: disable preset)',
        REALISTIC_AVAIL_W,
        ITEM_SCALE,
    )
    assert len(lines) > 1
    for cont in lines[1:]:
        assert cont.startswith(' ')  # indented under the description column


def test_short_entry_fits_on_a_single_line() -> None:
    overlays = _stub_overlays()
    lines = overlays._wrap_help_entry('f', 'Fullscreen', REALISTIC_AVAIL_W, ITEM_SCALE)
    assert lines == ['f            Fullscreen']


# --------------------------------------------------------------------------- #
# Pathological narrow columns: bounded overflow, never a dropped word
# --------------------------------------------------------------------------- #

def test_extremely_narrow_column_still_keeps_every_word() -> None:
    """Even if the column is far too narrow for the key to fit at all, no
    word is ever dropped — the key wraps too, rather than overflowing as one
    unbroken blob (the pre-fix behavior)."""
    overlays = _stub_overlays()
    key, desc = 'PageUp / PageDown', 'Switch help tab (page)'
    lines = overlays._wrap_help_entry(key, desc, avail_w=100.0, scale=2.1)
    all_words = ' '.join(lines).split()
    assert set(key.split()) | set(desc.split()) <= set(all_words)


# --------------------------------------------------------------------------- #
# Integration: _draw_help_section_content sizes cards from wrapped line counts
# --------------------------------------------------------------------------- #

def _stub_overlays_for_render() -> Overlays:
    overlays = _stub_overlays()
    overlays._hud_t = 0.0
    overlays._help_pulse_t = 0.0
    overlays._help_focus_region = 'sections'
    overlays._help_focus_idx = 0
    overlays._help_collapsed = {}
    overlays._help_tab_idx = 0
    overlays._help_tab_rects = []
    overlays._num_shortcuts = []
    overlays._shift_shortcuts = []
    overlays._ctrl_shortcuts = []
    overlays._alt_shortcuts = []
    overlays._postfx_help_entries = []
    overlays._unmapped_effects = []
    overlays._draw_rect = lambda *a, **kw: None

    synthetic = [
        (
            'Help Usage',
            [
                ('PageUp / PageDown', 'Switch help tab (page)'),
                ('Delete', 'Disable current effect & skip (ProjectM: disable preset)'),
            ],
        ),
    ]
    overlays._iter_help_sections = lambda: synthetic
    return overlays


def test_rendered_entry_lines_never_exceed_the_column_budget() -> None:
    overlays = _stub_overlays_for_render()
    drawn: list[tuple[str, float]] = []

    def _capture_text(text: str, _x: float, _y: float, scale: float = 2.0, **_kw) -> None:
        drawn.append((text, scale))

    overlays._draw_text = _capture_text

    # width=1920 reproduces the realistic column budget the wrap unit tests
    # above assert against, so this exercises the full render integration
    # (section sizing + drawing) rather than only the wrap helpers.
    overlays._draw_help_section_content(x=0.0, y=0.0, w=1920.0 - 88.0, h=800.0, help_scale=1.0, content_top_y=100.0)

    left_w = (1920.0 - 88.0) * 0.64
    col_w = (left_w - 14.0 - 3 * 10.0) / 2.0
    avail_text_w = col_w - 16.0
    for text, scale in drawn:
        if text == 'LIVE SHORTCUT MAP':
            continue
        max_chars = overlays._help_text_max_chars(avail_text_w, scale)
        assert len(text) <= max_chars, f'{text!r} overflows its column ({len(text)} > {max_chars} chars)'
