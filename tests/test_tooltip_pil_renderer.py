"""Tests for the PIL tooltip bubble renderer and word-wrap helper.

PIL is a hard dependency of the project, so these run against a real
image and assert on drawn pixels rather than faking ImageDraw.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from unicornviz.tooltips import draw_tooltip_pil, wrap_tooltip_text

_BG = (10, 10, 10)
_BUBBLE = (40, 60, 90)
_BORDER = (0, 200, 255)
_TEXT = (240, 240, 240)


def _canvas(w: int = 400, h: int = 300) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new('RGBA', (w, h), _BG + (255,))
    return img, ImageDraw.Draw(img, 'RGBA')


def _font():
    return ImageFont.load_default()


def _bubble_pixels(img: Image.Image) -> list[tuple[int, int]]:
    px = img.load()
    hits = []
    for yy in range(img.height):
        for xx in range(img.width):
            if px[xx, yy][:3] != _BG:
                hits.append((xx, yy))
    return hits


def test_wrap_keeps_short_text_on_one_line() -> None:
    lines = wrap_tooltip_text('short text', _font(), 360, lambda s: len(s) * 8)
    assert lines == ['short text']


def test_wrap_splits_on_word_boundaries() -> None:
    lines = wrap_tooltip_text(
        'alpha beta gamma delta', _font(), 100, lambda s: len(s) * 10,
    )
    assert lines == ['alpha beta', 'gamma', 'delta']
    assert all(len(line) * 10 <= 100 for line in lines)


def test_wrap_empty_text_yields_no_lines() -> None:
    assert wrap_tooltip_text('   ', _font(), 100, lambda s: len(s)) == []


def test_draws_below_right_of_anchor() -> None:
    img, draw = _canvas()
    draw_tooltip_pil(
        draw, 'Hello', (50, 50), (400, 300),
        font=_font(), bg=_BUBBLE, border=_BORDER, text_color=_TEXT,
    )
    hits = _bubble_pixels(img)
    assert hits, 'nothing was drawn'
    min_x = min(x for x, _ in hits)
    min_y = min(y for _, y in hits)
    assert min_x >= 50 and min_y >= 50


def test_flips_above_anchor_near_the_bottom_edge() -> None:
    img, draw = _canvas()
    draw_tooltip_pil(
        draw, 'Hello', (50, 290), (400, 300),
        font=_font(), bg=_BUBBLE, border=_BORDER, text_color=_TEXT,
    )
    hits = _bubble_pixels(img)
    assert hits
    max_y = max(y for _, y in hits)
    assert max_y <= 290, 'bubble must flip above the anchor near the bottom'


def test_clamps_inside_the_right_edge() -> None:
    img, draw = _canvas()
    draw_tooltip_pil(
        draw, 'A reasonably long tooltip line', (395, 50), (400, 300),
        font=_font(), bg=_BUBBLE, border=_BORDER, text_color=_TEXT,
    )
    hits = _bubble_pixels(img)
    assert hits
    assert max(x for x, _ in hits) <= 399


def test_empty_text_draws_nothing() -> None:
    img, draw = _canvas()
    draw_tooltip_pil(
        draw, '   ', (50, 50), (400, 300),
        font=_font(), bg=_BUBBLE, border=_BORDER, text_color=_TEXT,
    )
    assert _bubble_pixels(img) == []


def test_long_text_wraps_to_multiple_lines() -> None:
    img, draw = _canvas(400, 300)
    long_text = 'word ' * 30
    draw_tooltip_pil(
        draw, long_text, (10, 10), (400, 300),
        font=_font(), bg=_BUBBLE, border=_BORDER, text_color=_TEXT,
        max_width_px=120,
    )
    hits = _bubble_pixels(img)
    assert hits
    height = max(y for _, y in hits) - min(y for _, y in hits)
    assert height > 40, 'expected a multi-line bubble'
    assert max(x for x, _ in hits) - min(x for x, _ in hits) <= 160
