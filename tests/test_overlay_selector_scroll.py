"""U8 (audit 2026-09-30, UI files): the audio and MIDI selector panels had no
row cap.  ``panel_h = 80 + n_rows * 38 + 56`` centred, so with many devices
(PipeWire lists more once monitors are counted; Windows lists each device once
per host API) the title, the top rows and the selected row ran off-screen.  The
panel is now clamped to the window and shows a window of rows scrolled around
the selection, with an "n/N" position in the footer.
"""
from __future__ import annotations

import pytest

from unicornviz.overlays import Overlays, selector_row_window


# ---------------------------------------------------------------- the helper

@pytest.mark.parametrize(('n', 'sel', 'cap'), [
    (5, 2, 10), (10, 9, 10), (50, 0, 8), (50, 25, 8), (50, 49, 8), (3, 1, 1), (1, 0, 5), (0, 0, 5),
])
def test_the_window_always_contains_the_selection_and_fits_the_cap(n, sel, cap) -> None:
    start, count = selector_row_window(n, sel, cap)
    assert 0 <= start and count <= max(cap, 1) and start + count <= max(n, 1)
    if n:
        assert start <= sel < start + count


def test_the_window_shows_everything_when_it_fits() -> None:
    assert selector_row_window(6, 3, 10) == (0, 6)


def test_the_window_centres_on_the_selection_in_the_middle_of_a_long_list() -> None:
    start, count = selector_row_window(100, 50, 9)
    assert count == 9 and start == 46                    # 4 above, 4 below


def test_the_window_sticks_to_the_ends() -> None:
    assert selector_row_window(100, 0, 9) == (0, 9)
    assert selector_row_window(100, 99, 9) == (91, 9)


def test_an_out_of_range_selection_is_clamped() -> None:
    assert selector_row_window(20, 500, 5) == (15, 5)
    assert selector_row_window(20, -3, 5) == (0, 5)


# --------------------------------------------------------------- the rendering

class _Rec:
    def __init__(self) -> None:
        self.rects: list[tuple] = []
        self.texts: list[tuple] = []


def _shell(width: int, height: int, sources: list[str]) -> tuple[Overlays, _Rec]:
    o = Overlays.__new__(Overlays)
    rec = _Rec()
    o._width, o._height = width, height
    o._hud_t = 0.0
    o._hud_state = {}
    o._audio_sources = list(sources)
    o._audio_viable_flags = [True] * len(sources)
    o._audio_divider_rows = set()
    o._audio_current_idx = 0
    o._audio_selected_idx = 0
    o._midi_ports = list(sources)
    o._midi_current_port = ''
    o._midi_selected_idx = 0
    o._draw_rect = lambda x, y, w, h, c: rec.rects.append((x, y, w, h))
    o._draw_text = lambda text, x, y, scale=1.0, color=None: rec.texts.append((text, x, y, scale))
    o._draw_modal_underlay = lambda *a, **k: None
    o._draw_audio_reactive_border_bulbs = lambda *a, **k: None
    o._fit_text = lambda text, scale, width: text
    o._char_width = lambda scale: 8.0 * scale
    return o, rec


SIZES = [(1920, 1080), (1280, 720), (800, 480), (640, 360)]


@pytest.mark.parametrize(('w', 'h'), SIZES)
@pytest.mark.parametrize('n', [3, 26, 60, 400])
@pytest.mark.parametrize('which', ['audio', 'midi'])
def test_the_panel_and_every_row_stay_inside_the_window(w, h, n, which) -> None:
    sources = [f'device {i}' for i in range(n)]
    for sel in sorted({0, n // 2, max(0, n - 1)}):
        o, rec = _shell(w, h, sources)
        if which == 'audio':
            o._audio_selected_idx = sel
            o._render_audio_selector()
        else:
            o._midi_selected_idx = min(sel, len(sources))
            o._render_midi_selector()
        panel = rec.rects[1] if len(rec.rects) > 1 else rec.rects[0]
        # the background rect is the first one drawn after the underlay
        px, py, pw, ph = rec.rects[0]
        assert py >= 0 and py + ph <= h + 1e-6, f'panel runs off-screen: {py}+{ph} > {h}'
        for text, x, y, scale in rec.texts:
            assert py - 1 <= y <= py + ph + 1, f'{text!r} drawn at y={y} outside the panel'
        assert panel is not None


@pytest.mark.parametrize('which', ['audio', 'midi'])
def test_the_selected_row_is_always_drawn(which) -> None:
    sources = [f'device {i}' for i in range(120)]
    for sel in (0, 17, 60, 119):
        o, rec = _shell(1280, 720, sources)
        if which == 'audio':
            o._audio_selected_idx = sel
            o._render_audio_selector()
            expected = f'device {sel}'
        else:
            o._midi_selected_idx = sel + 1                     # row 0 is the "none" entry
            o._render_midi_selector()
            expected = f'device {sel}'
        marked = [t for t, *_ in rec.texts if t.startswith('> ') and expected in t]
        assert marked, f'selected row {expected!r} not drawn for selection {sel}'


def test_a_long_list_shows_where_you_are() -> None:
    o, rec = _shell(1280, 720, [f'device {i}' for i in range(120)])
    o._audio_selected_idx = 60
    o._render_audio_selector()
    footer = ' '.join(t for t, *_ in rec.texts)
    assert '61/120' in footer


def test_a_short_list_is_unchanged_and_has_no_position_text() -> None:
    o, rec = _shell(1920, 1080, ['a', 'b', 'c'])
    o._render_audio_selector()
    px, py, pw, ph = rec.rects[0]
    assert ph == pytest.approx(80.0 + 3 * 38.0 + 56.0)         # exactly the old geometry
    assert not any('/3' in t for t, *_ in rec.texts)


def test_the_title_and_footer_are_always_visible() -> None:
    o, rec = _shell(800, 480, [f'device {i}' for i in range(300)])
    o._audio_selected_idx = 150
    o._render_audio_selector()
    texts = [t for t, *_ in rec.texts]
    assert 'AUDIO SOURCE SELECT' in texts
    assert any('Esc: cancel' in t for t in texts)
