"""
Convert an ANSICanvas into an RGBA OpenGL texture.

Each cell is rendered as an 8×16 block using the font atlas and CGA palette.
Returns a moderngl.Texture sized (canvas.width*8, canvas.height*16).
"""
from __future__ import annotations

import numpy as np
import moderngl

from unicornviz.ansi.loader import ANSICanvas, CGA_PALETTE
from unicornviz.ansi.font import build_font_atlas, _CHAR_W, _CHAR_H


def canvas_to_texture(
    ctx: moderngl.Context,
    canvas: ANSICanvas,
    font_atlas: moderngl.Texture,
) -> moderngl.Texture:
    """
    Render canvas into a pixel buffer, return as an RGBA texture.
    The font atlas must already be created (from build_font_atlas).
    """
    W = canvas.width * _CHAR_W
    H = canvas.height * _CHAR_H

    # Pull font atlas pixels into numpy
    # atlas is a (16 × 2048) single-channel texture
    atlas_raw = np.frombuffer(font_atlas.read(), dtype=np.uint8)
    atlas = atlas_raw.reshape((_CHAR_H, 256 * _CHAR_W))

    # Output buffer: RGBA
    img = np.zeros((H, W, 4), dtype=np.uint8)

    for row_idx, row in enumerate(canvas.cells):
        y0 = row_idx * _CHAR_H
        for col_idx, cell in enumerate(row):
            x0 = col_idx * _CHAR_W

            fg_rgb = CGA_PALETTE[cell.fg & 15]
            bg_rgb = CGA_PALETTE[cell.bg & 15]

            cp = cell.codepoint & 0xFF
            glyph_col_start = cp * _CHAR_W

            # Slice the glyph from the atlas
            glyph = atlas[0:_CHAR_H, glyph_col_start: glyph_col_start + _CHAR_W]

            # Pixel is fg where glyph is set, bg otherwise
            mask = glyph > 0                        # (_CHAR_H, _CHAR_W) bool
            block = np.zeros((_CHAR_H, _CHAR_W, 4), dtype=np.uint8)
            block[~mask] = (*bg_rgb, 255)
            block[mask]  = (*fg_rgb, 255)

            img[y0: y0 + _CHAR_H, x0: x0 + _CHAR_W] = block

    tex = ctx.texture((W, H), 4, data=img.tobytes())
    tex.filter = moderngl.NEAREST, moderngl.NEAREST
    return tex
