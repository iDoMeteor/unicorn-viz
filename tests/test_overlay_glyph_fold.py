"""U2 (audit 2026-09-30, UI files): non-ASCII text drew as the wrong glyphs.

``_char_quads`` indexed the 128-cell ASCII atlas with ``ord(ch) & 0x7F``, which
folds every code point above 127 onto an unrelated ASCII cell: the tour's ``·``
drew as ``7``, ``—`` and ``→`` (cells 0x14 and 0x92 & 0x7F = 0x12, both
control cells) were blank, "Beyoncé" read "Beyonci" and "Ólafur" read "Slafur",
on the audience output too.  Text is now folded to the atlas's ASCII before
indexing: punctuation by a table, accented letters to their base letter, the
rest to ``?`` -- always one cell per character, so measured widths still match.
"""
from __future__ import annotations

import numpy as np
import pytest

from unicornviz.overlays import Overlays, fold_to_atlas_ascii


@pytest.mark.parametrize(('src', 'expected'), [
    ('Beyoncé', 'Beyonce'),
    ('Ólafur Arnalds', 'Olafur Arnalds'),
    ('Mötley Crüe', 'Motley Crue'),
    ('señor ñandú', 'senor nandu'),
    ('Sigur Rós', 'Sigur Ros'),
    ('Łódź', 'Lodz'),
    ('Straße', 'Strase'),
    ('Ærø', 'Aro'),                            # one cell per character: Æ -> A, ø -> o
    ('café au lait', 'cafe au lait'),
])
def test_accented_letters_fold_to_their_base_letter(src, expected) -> None:
    out = fold_to_atlas_ascii(src)
    assert out == expected
    assert len(out) == len(src)                # one cell per character, always


@pytest.mark.parametrize(('src', 'expected'), [
    ('·', '.'), ('—', '-'), ('–', '-'), ('→', '>'), ('←', '<'), ('…', '.'),
    ('•', '*'), ('“hi”', '"hi"'), ("it’s", "it's"), ('×', 'x'), ('°', 'o'),
    (' ', ' '),                                          # no-break space
])
def test_punctuation_has_a_readable_ascii_stand_in(src, expected) -> None:
    assert fold_to_atlas_ascii(src) == expected


def test_ascii_passes_through_unchanged_and_fast() -> None:
    s = 'Now playing: Daft Punk - One More Time (Extended) [128 BPM] 100%!'
    assert fold_to_atlas_ascii(s) is s or fold_to_atlas_ascii(s) == s
    assert fold_to_atlas_ascii('') == ''


@pytest.mark.parametrize('src', ['日本語', '😀', '\ud800', 'Привет', '\x00\x1f'])
def test_what_the_atlas_cannot_draw_becomes_a_question_mark_or_blank(src) -> None:
    out = fold_to_atlas_ascii(src)
    assert len(out) == len(src)
    assert all(ord(c) < 128 for c in out)
    if src != '\x00\x1f':
        assert set(out) == {'?'}


def test_the_tour_and_hud_strings_from_the_audit_read_correctly() -> None:
    assert fold_to_atlas_ascii('(none — disable MIDI)') == '(none - disable MIDI)'
    assert fold_to_atlas_ascii('BPM → Auto VJ') == 'BPM > Auto VJ'
    assert fold_to_atlas_ascii('Page 1/3 — PageUp/PageDown') == 'Page 1/3 - PageUp/PageDown'


# -- the quads really use the folded cell ----------------------------------

def _shell() -> Overlays:
    o = Overlays.__new__(Overlays)
    o._glyph_w, o._glyph_h = 8, 16
    o._atlas_w, o._atlas_h = 8 * 128, 16
    o._font_scale_norm = 1.0
    o._width, o._height = 640, 360
    return o


def _u_of(o: Overlays, ch: str) -> float:
    verts = o._char_quads(ch, 0.0, 0.0, 1.0, (1, 1, 1, 1)).reshape(-1, 4)
    return float(verts[0][2])


@pytest.mark.parametrize(('ch', 'as_ascii'), [('é', 'e'), ('Ó', 'O'), ('·', '.'), ('—', '-'),
                                              ('→', '>'), ('日', '?')])
def test_char_quads_index_the_folded_cell(ch, as_ascii) -> None:
    o = _shell()
    assert _u_of(o, ch) == pytest.approx(_u_of(o, as_ascii))
    assert _u_of(o, ch) == pytest.approx(ord(as_ascii) * 8 / (8 * 128))


def test_char_quads_never_index_outside_the_atlas() -> None:
    o = _shell()
    for ch in 'aé·—→日😀\x00\x7fÿ→':
        verts = np.asarray(o._char_quads(ch, 0.0, 0.0, 1.0, (1, 1, 1, 1))).reshape(-1, 4)
        assert 0.0 <= verts[:, 2].min() and verts[:, 2].max() <= 1.0


def test_the_quad_count_still_matches_the_character_count() -> None:
    o = _shell()
    text = 'Beyoncé — Halo · 128 →'
    verts = np.asarray(o._char_quads(text, 0.0, 0.0, 1.0, (1, 1, 1, 1))).reshape(-1, 4)
    assert len(verts) == 6 * len(text)
