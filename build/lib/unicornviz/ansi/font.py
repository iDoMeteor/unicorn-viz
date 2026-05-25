"""
CP437 bitmap font — generates an 8×16 font atlas texture on the GPU.

The font data is the classic IBM PC BIOS 8×16 VGA font (public domain).
We synthesise it from a hand-coded glyph table for the characters used in
ANSI art.  A real font file can be placed at assets/fonts/font8x16.bin
(256 glyphs × 16 bytes, one bit per pixel per row) to override.
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import moderngl

_CHAR_W = 8
_CHAR_H = 16
_NUM_CHARS = 256
_ATLAS_W = _NUM_CHARS * _CHAR_W   # 2048 px wide, 16 px tall


# Minimal built-in glyph data.  Keys are CP437 codepoints; values are
# 16-element lists of row bitmasks (MSB = leftmost pixel).
# We include the block-drawing chars that appear most in ANSI art.
# Everything else falls back to a generic filled rectangle.

_GLYPHS: dict[int, list[int]] = {
    # Space
    32: [0]*16,

    # Full block  █ (0xDB)
    0xDB: [0xFF]*16,
    # Upper half ▀ (0xDF)
    0xDF: [0xFF]*8 + [0x00]*8,
    # Lower half ▄ (0xDC)
    0xDC: [0x00]*8 + [0xFF]*8,
    # Left half  ▌ (0xDD)
    0xDD: [0xF0]*16,
    # Right half ▐ (0xDE)
    0xDE: [0x0F]*16,
    # Light shade ░ (0xB0)
    0xB0: [0b10001000, 0b00000000, 0b00100010, 0b00000000,
           0b10001000, 0b00000000, 0b00100010, 0b00000000,
           0b10001000, 0b00000000, 0b00100010, 0b00000000,
           0b10001000, 0b00000000, 0b00100010, 0b00000000],
    # Medium shade ▒ (0xB1)
    0xB1: [0b10101010, 0b01010101, 0b10101010, 0b01010101,
           0b10101010, 0b01010101, 0b10101010, 0b01010101,
           0b10101010, 0b01010101, 0b10101010, 0b01010101,
           0b10101010, 0b01010101, 0b10101010, 0b01010101],
    # Dark shade  ▓ (0xB2)
    0xB2: [0b11101110, 0b11111111, 0b10111011, 0b11111111,
           0b11101110, 0b11111111, 0b10111011, 0b11111111,
           0b11101110, 0b11111111, 0b10111011, 0b11111111,
           0b11101110, 0b11111111, 0b10111011, 0b11111111],

    # Box drawing — single line
    0xC4: [0]*6  + [0xFF] + [0]*9,                          # ─
    0xB3: [0x18]*16,                                         # │
    0xDA: [0]*6  + [0x1F] + [0x18]*9,                       # ┌
    0xBF: [0]*6  + [0xF8] + [0x18]*9,                       # ┐
    0xC0: [0x18]*9 + [0x1F] + [0]*6,                        # └
    0xD9: [0x18]*9 + [0xF8] + [0]*6,                        # ┘
    0xC3: [0x18]*9 + [0x1F] + [0x18]*7,                     # ├ (approximate)
    0xB4: [0x18]*9 + [0xF8] + [0x18]*7,                     # ┤

    # Box drawing — double line
    0xCD: [0]*5 + [0xFF, 0x00, 0xFF] + [0]*8,               # ═
    0xBA: [0b00100100]*16,                                   # ║
    0xC9: [0]*5 + [0b00111111, 0b00100100, 0b00111100] + [0b00100100]*8,  # ╔
    0xBB: [0]*5 + [0b11111100, 0b00100100, 0b00111100] + [0b00100100]*8,  # ╗
    0xC8: [0b00100100]*8 + [0b00111100, 0b00100100, 0b00111111] + [0]*5,  # ╚
    0xBC: [0b00100100]*8 + [0b00111100, 0b00100100, 0b11111100] + [0]*5,  # ╝
}


def _render_char_row(glyph: list[int], row: int) -> list[int]:
    """Return 8 pixel values (0 or 255) for a glyph row."""
    byte = glyph[row] if row < len(glyph) else 0
    return [255 if (byte >> (7 - col)) & 1 else 0 for col in range(8)]


def _get_glyph(cp: int) -> list[int]:
    if cp in _GLYPHS:
        return _GLYPHS[cp]
    # Generic fallback: simple 5×9 rectangle for letters
    if 32 <= cp < 128:
        glyph = [0]*3
        for _ in range(9):
            glyph.append(0b01111100)
        glyph += [0]*4
        return glyph
    return [0]*16


def build_font_atlas(ctx: moderngl.Context) -> moderngl.Texture:
    """
    Build and return a 2048×16 RGBA font atlas texture (one channel used).
    Tries to load assets/fonts/font8x16.bin first; falls back to built-in.
    """
    font_path = Path("assets/fonts/font8x16.bin")
    atlas = np.zeros((_CHAR_H, _ATLAS_W), dtype=np.uint8)

    if font_path.exists():
        raw = font_path.read_bytes()
        for cp in range(min(_NUM_CHARS, len(raw) // _CHAR_H)):
            for row in range(_CHAR_H):
                byte = raw[cp * _CHAR_H + row]
                for col in range(_CHAR_W):
                    if (byte >> (7 - col)) & 1:
                        atlas[row, cp * _CHAR_W + col] = 255
    else:
        for cp in range(_NUM_CHARS):
            glyph = _get_glyph(cp)
            for row in range(_CHAR_H):
                pixels = _render_char_row(glyph, row)
                atlas[row, cp * _CHAR_W: cp * _CHAR_W + _CHAR_W] = pixels

    tex = ctx.texture((_ATLAS_W, _CHAR_H), 1, data=atlas.tobytes())
    tex.filter = moderngl.NEAREST, moderngl.NEAREST
    return tex
