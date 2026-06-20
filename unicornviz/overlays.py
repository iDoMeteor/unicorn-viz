"""
On-screen overlays rendered in immediate mode using a simple bitmap font.
Handles: effect name flash, persistent name overlay, help screen,
audio device selector, MIDI device selector, and generic flash messages.
"""
from __future__ import annotations

import datetime
import logging
import math
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import moderngl
import numpy as np

from unicornviz.paths import resolve_path

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except Exception:
    _PIL_AVAILABLE = False

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except Exception:
    _PSUTIL_AVAILABLE = False

if TYPE_CHECKING:
    from unicornviz.effects.base import BaseEffect

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedded 8×8 bitmap font (IBM PC BIOS font, ASCII 32–127)
# Each character is stored as 8 bytes, one byte per row, MSB = leftmost pixel.
# Generated from the public-domain "PC Screen Font" / Oldschool PC Font data.
# ---------------------------------------------------------------------------
_FONT_8X8 = [
    # 32 space
    0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
    # 33 !
    0x18,0x3C,0x3C,0x18,0x18,0x00,0x18,0x00,
    # 34 "
    0x36,0x36,0x00,0x00,0x00,0x00,0x00,0x00,
    # 35 #
    0x36,0x36,0x7F,0x36,0x7F,0x36,0x36,0x00,
    # 36 $
    0x0C,0x3E,0x03,0x1E,0x30,0x1F,0x0C,0x00,
    # 37 %
    0x00,0x63,0x33,0x18,0x0C,0x66,0x63,0x00,
    # 38 &
    0x1C,0x36,0x1C,0x6E,0x3B,0x33,0x6E,0x00,
    # 39 '
    0x06,0x06,0x03,0x00,0x00,0x00,0x00,0x00,
    # 40 (
    0x18,0x0C,0x06,0x06,0x06,0x0C,0x18,0x00,
    # 41 )
    0x06,0x0C,0x18,0x18,0x18,0x0C,0x06,0x00,
    # 42 *
    0x00,0x66,0x3C,0xFF,0x3C,0x66,0x00,0x00,
    # 43 +
    0x00,0x0C,0x0C,0x3F,0x0C,0x0C,0x00,0x00,
    # 44 ,
    0x00,0x00,0x00,0x00,0x00,0x0C,0x0C,0x06,
    # 45 -
    0x00,0x00,0x00,0x3F,0x00,0x00,0x00,0x00,
    # 46 .
    0x00,0x00,0x00,0x00,0x00,0x0C,0x0C,0x00,
    # 47 /
    0x60,0x30,0x18,0x0C,0x06,0x03,0x01,0x00,
    # 48 0
    0x3E,0x63,0x73,0x7B,0x6F,0x67,0x3E,0x00,
    # 49 1
    0x0C,0x0E,0x0C,0x0C,0x0C,0x0C,0x3F,0x00,
    # 50 2
    0x1E,0x33,0x30,0x1C,0x06,0x33,0x3F,0x00,
    # 51 3
    0x1E,0x33,0x30,0x1C,0x30,0x33,0x1E,0x00,
    # 52 4
    0x38,0x3C,0x36,0x33,0x7F,0x30,0x78,0x00,
    # 53 5
    0x3F,0x03,0x1F,0x30,0x30,0x33,0x1E,0x00,
    # 54 6
    0x1C,0x06,0x03,0x1F,0x33,0x33,0x1E,0x00,
    # 55 7
    0x3F,0x33,0x30,0x18,0x0C,0x0C,0x0C,0x00,
    # 56 8
    0x1E,0x33,0x33,0x1E,0x33,0x33,0x1E,0x00,
    # 57 9
    0x1E,0x33,0x33,0x3E,0x30,0x18,0x0E,0x00,
    # 58 :
    0x00,0x0C,0x0C,0x00,0x00,0x0C,0x0C,0x00,
    # 59 ;
    0x00,0x0C,0x0C,0x00,0x00,0x0C,0x0C,0x06,
    # 60 <
    0x18,0x0C,0x06,0x03,0x06,0x0C,0x18,0x00,
    # 61 =
    0x00,0x00,0x3F,0x00,0x00,0x3F,0x00,0x00,
    # 62 >
    0x06,0x0C,0x18,0x30,0x18,0x0C,0x06,0x00,
    # 63 ?
    0x1E,0x33,0x30,0x18,0x0C,0x00,0x0C,0x00,
    # 64 @
    0x3E,0x63,0x7B,0x7B,0x7B,0x03,0x1E,0x00,
    # 65 A
    0x0C,0x1E,0x33,0x33,0x3F,0x33,0x33,0x00,
    # 66 B
    0x3F,0x66,0x66,0x3E,0x66,0x66,0x3F,0x00,
    # 67 C
    0x3C,0x66,0x03,0x03,0x03,0x66,0x3C,0x00,
    # 68 D
    0x1F,0x36,0x66,0x66,0x66,0x36,0x1F,0x00,
    # 69 E
    0x7F,0x46,0x16,0x1E,0x16,0x46,0x7F,0x00,
    # 70 F
    0x7F,0x46,0x16,0x1E,0x16,0x06,0x0F,0x00,
    # 71 G
    0x3C,0x66,0x03,0x03,0x73,0x66,0x7C,0x00,
    # 72 H
    0x33,0x33,0x33,0x3F,0x33,0x33,0x33,0x00,
    # 73 I
    0x1E,0x0C,0x0C,0x0C,0x0C,0x0C,0x1E,0x00,
    # 74 J
    0x78,0x30,0x30,0x30,0x33,0x33,0x1E,0x00,
    # 75 K
    0x67,0x66,0x36,0x1E,0x36,0x66,0x67,0x00,
    # 76 L
    0x0F,0x06,0x06,0x06,0x46,0x66,0x7F,0x00,
    # 77 M
    0x63,0x77,0x7F,0x7F,0x6B,0x63,0x63,0x00,
    # 78 N
    0x63,0x67,0x6F,0x7B,0x73,0x63,0x63,0x00,
    # 79 O
    0x1C,0x36,0x63,0x63,0x63,0x36,0x1C,0x00,
    # 80 P
    0x3F,0x66,0x66,0x3E,0x06,0x06,0x0F,0x00,
    # 81 Q
    0x1E,0x33,0x33,0x33,0x3B,0x1E,0x38,0x00,
    # 82 R
    0x3F,0x66,0x66,0x3E,0x36,0x66,0x67,0x00,
    # 83 S
    0x1E,0x33,0x07,0x0E,0x38,0x33,0x1E,0x00,
    # 84 T
    0x3F,0x2D,0x0C,0x0C,0x0C,0x0C,0x1E,0x00,
    # 85 U
    0x33,0x33,0x33,0x33,0x33,0x33,0x3F,0x00,
    # 86 V
    0x33,0x33,0x33,0x33,0x33,0x1E,0x0C,0x00,
    # 87 W
    0x63,0x63,0x63,0x6B,0x7F,0x77,0x63,0x00,
    # 88 X
    0x63,0x63,0x36,0x1C,0x1C,0x36,0x63,0x00,
    # 89 Y
    0x33,0x33,0x33,0x1E,0x0C,0x0C,0x1E,0x00,
    # 90 Z
    0x7F,0x63,0x31,0x18,0x4C,0x66,0x7F,0x00,
    # 91 [
    0x1E,0x06,0x06,0x06,0x06,0x06,0x1E,0x00,
    # 92 backslash
    0x03,0x06,0x0C,0x18,0x30,0x60,0x40,0x00,
    # 93 ]
    0x1E,0x18,0x18,0x18,0x18,0x18,0x1E,0x00,
    # 94 ^
    0x08,0x1C,0x36,0x63,0x00,0x00,0x00,0x00,
    # 95 _
    0x00,0x00,0x00,0x00,0x00,0x00,0x00,0xFF,
    # 96 `
    0x0C,0x0C,0x18,0x00,0x00,0x00,0x00,0x00,
    # 97 a
    0x00,0x00,0x1E,0x30,0x3E,0x33,0x6E,0x00,
    # 98 b
    0x07,0x06,0x06,0x3E,0x66,0x66,0x3B,0x00,
    # 99 c
    0x00,0x00,0x1E,0x33,0x03,0x33,0x1E,0x00,
    # 100 d
    0x38,0x30,0x30,0x3e,0x33,0x33,0x6E,0x00,
    # 101 e
    0x00,0x00,0x1E,0x33,0x3f,0x03,0x1E,0x00,
    # 102 f
    0x1C,0x36,0x06,0x0f,0x06,0x06,0x0F,0x00,
    # 103 g
    0x00,0x00,0x6E,0x33,0x33,0x3E,0x30,0x1F,
    # 104 h
    0x07,0x06,0x36,0x6E,0x66,0x66,0x67,0x00,
    # 105 i
    0x0C,0x00,0x0E,0x0C,0x0C,0x0C,0x1E,0x00,
    # 106 j
    0x30,0x00,0x30,0x30,0x30,0x33,0x33,0x1E,
    # 107 k
    0x07,0x06,0x66,0x36,0x1E,0x36,0x67,0x00,
    # 108 l
    0x0E,0x0C,0x0C,0x0C,0x0C,0x0C,0x1E,0x00,
    # 109 m
    0x00,0x00,0x33,0x7F,0x7F,0x6B,0x63,0x00,
    # 110 n
    0x00,0x00,0x1F,0x33,0x33,0x33,0x33,0x00,
    # 111 o
    0x00,0x00,0x1E,0x33,0x33,0x33,0x1E,0x00,
    # 112 p
    0x00,0x00,0x3B,0x66,0x66,0x3E,0x06,0x0F,
    # 113 q
    0x00,0x00,0x6E,0x33,0x33,0x3E,0x30,0x78,
    # 114 r
    0x00,0x00,0x3B,0x6E,0x66,0x06,0x0F,0x00,
    # 115 s
    0x00,0x00,0x3E,0x03,0x1E,0x30,0x1F,0x00,
    # 116 t
    0x08,0x0C,0x3E,0x0C,0x0C,0x2C,0x18,0x00,
    # 117 u
    0x00,0x00,0x33,0x33,0x33,0x33,0x6E,0x00,
    # 118 v
    0x00,0x00,0x33,0x33,0x33,0x1E,0x0C,0x00,
    # 119 w
    0x00,0x00,0x63,0x6B,0x7F,0x7F,0x36,0x00,
    # 120 x
    0x00,0x00,0x63,0x36,0x1C,0x36,0x63,0x00,
    # 121 y
    0x00,0x00,0x33,0x33,0x33,0x3E,0x30,0x1F,
    # 122 z
    0x00,0x00,0x3F,0x19,0x0C,0x26,0x3F,0x00,
    # 123 {
    0x38,0x0C,0x0C,0x07,0x0C,0x0C,0x38,0x00,
    # 124 |
    0x18,0x18,0x18,0x00,0x18,0x18,0x18,0x00,
    # 125 }
    0x07,0x0C,0x0C,0x38,0x0C,0x0C,0x07,0x00,
    # 126 ~
    0x6E,0x3B,0x00,0x00,0x00,0x00,0x00,0x00,
    # 127 DEL (block)
    0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,
]  # 96 chars × 8 bytes = 768 bytes


def _build_font_texture(ctx: moderngl.Context) -> tuple[moderngl.Texture, int, int, int, int, Path | None]:
    """
    Build overlay font atlas and return (texture, glyph_w, glyph_h, atlas_w, atlas_h).

    Preferred path: render a grayscale atlas from a modern TTF font for cleaner
    readability at mixed sizes.
    Fallback path: legacy 8x8 bitmap atlas from assets/fonts/font8x8.bin or
    embedded BIOS-style font data.
    """
    if _PIL_AVAILABLE:
        font_candidates = [
            resolve_path('assets/fonts/ui-font.ttf'),
            Path('/usr/share/fonts/adobe-source-code-pro-fonts/SourceCodePro-Medium.otf'),
            Path('/usr/share/fonts/google-noto-vf/NotoSansMono[wght].ttf'),
            Path('/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf'),
        ]
        font_path = next((p for p in font_candidates if p.exists()), None)
        if font_path is not None:
            glyph_w = 13
            glyph_h = 18
            n_chars = 128
            atlas_w = glyph_w * n_chars
            atlas_h = glyph_h
            atlas = Image.new('L', (atlas_w, atlas_h), 0)
            draw = ImageDraw.Draw(atlas)
            try:
                font = ImageFont.truetype(str(font_path), size=17)
                for code in range(32, 127):
                    ch = chr(code)
                    bbox = draw.textbbox((0, 0), ch, font=font)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                    ox = code * glyph_w + max(0, (glyph_w - tw) // 2) - bbox[0]
                    oy = max(0, (glyph_h - th) // 2) - bbox[1] - 1
                    draw.text((ox, oy), ch, font=font, fill=255)

                data = np.array(atlas, dtype=np.uint8)
                tex = ctx.texture((atlas_w, atlas_h), 1, data=data.tobytes())
                # Linear sampling keeps strokes cleaner when scaled.
                tex.filter = moderngl.LINEAR, moderngl.LINEAR
                return tex, glyph_w, glyph_h, atlas_w, atlas_h, font_path
            except Exception:
                pass

    N_CHARS = 128
    data = np.zeros((8, N_CHARS * 8), dtype=np.uint8)

    font_path = resolve_path("assets/fonts/font8x8.bin")
    if font_path.exists():
        raw = font_path.read_bytes()
        for codepoint in range(min(N_CHARS, len(raw) // 8)):
            for row in range(8):
                byte = raw[codepoint * 8 + row]
                for col in range(8):
                    if byte & (0x80 >> col):
                        data[row, codepoint * 8 + col] = 255
    else:
        # Use embedded font for ASCII 32–127
        font_bytes = bytes(_FONT_8X8)
        for idx in range(96):
            codepoint = 32 + idx
            for row in range(8):
                byte = font_bytes[idx * 8 + row]
                # Embedded rows are packed with opposite horizontal bit order.
                # Reverse bits so glyphs are not mirrored.
                byte = int(f'{byte:08b}'[::-1], 2)
                for col in range(8):
                    if byte & (0x80 >> col):
                        data[row, codepoint * 8 + col] = 255

    tex = ctx.texture((N_CHARS * 8, 8), 1, data=data.tobytes())
    tex.filter = moderngl.NEAREST, moderngl.NEAREST
    return tex, 8, 8, N_CHARS * 8, 8, None


# ---------------------------------------------------------------------------
# Call-to-action (CTA) hype overlay — three cycling social messages.
# Triggered by streaming-owned CTA hotkey path (defaults to F9).
# ---------------------------------------------------------------------------
_CTA_SHOW_DURATION: float = 4.5
_CTA_SLOTS: list[tuple[str, str]] = [
    ('Push the buttons!',  '\U0001f44d'),              # 👍
    ('Do the thangs!',     '\U0001f514'),              # 🔔
    ('Share the love!',    '\u2764\ufe0f\u2009\U0001f4e4'),  # ❤️ 📤
]



class CTAOverlay:
    """Self-contained call-to-action hype animation overlay.

    Manages the GLSL blit shader, PIL texture atlas, and animation state so
    the parent Overlays class does not own any CTA-specific GL resources.
    """

    def __init__(
        self,
        font_path: 'Path | None',
        slots: list[tuple[str, str]],
        show_duration: float,
    ) -> None:
        self._font_path = font_path
        self._slots = list(slots)
        self._show_duration = float(show_duration)
        self._slot: int = -1
        self._timer: float = 0.0
        self._t: float = 0.0
        self._textures: list[moderngl.Texture] | None = None
        self._tex_w: int = 1600
        self._tex_h: int = 340
        self._blit_prog: moderngl.Program | None = None
        self._quad_vbo: moderngl.Buffer | None = None
        self._quad_vao: moderngl.VertexArray | None = None
        self._slots_key: tuple[tuple[str, str], ...] | None = None

    @property
    def is_active(self) -> bool:
        """Return True when the CTA animation is running."""
        return self._timer > 0.0

    def trigger(self) -> None:
        """Advance to the next slot and start the hype animation."""
        if not self._slots:
            return
        self._slot = (self._slot + 1) % len(self._slots)
        self._timer = self._show_duration
        self._t = 0.0

    def trigger_custom(
        self,
        text: str,
        icon: str = '',
        duration: 'float | None' = None,
    ) -> None:
        """Trigger a custom one-off CTA message."""
        msg = str(text).strip()
        if not msg:
            return
        self._slots = [(msg, str(icon or '').strip())]
        self._show_duration = (
            max(0.2, float(duration)) if duration is not None else _CTA_SHOW_DURATION
        )
        self._textures = None
        self._slots_key = None
        self._slot = 0
        self._timer = self._show_duration
        self._t = 0.0

    def render(
        self,
        dt: float,
        ctx: moderngl.Context,
        draw_rect: Callable,
        width: int,
        height: int,
    ) -> None:
        """Tick and render the CTA overlay; no-op when inactive."""
        if not self.is_active:
            return
        self._ensure_resources(ctx)
        if self._blit_prog is None or self._textures is None:
            return
        if not (0 <= self._slot < len(self._textures)):
            return

        self._timer -= dt
        self._t += dt

        elapsed = self._show_duration - self._timer
        _ENTRY = 0.45
        _EXIT_START = self._show_duration - 0.65
        _EXIT_DUR = 0.65

        if elapsed < _ENTRY:
            t_e = elapsed / _ENTRY
            spring = 1.0 - math.exp(-t_e * 6.0) * math.cos(t_e * math.pi * 2.2)
            scale_f = max(0.0, min(1.08, spring))
            alpha = min(1.0, t_e * 4.0)
        elif elapsed > _EXIT_START:
            t_x = min(1.0, (elapsed - _EXIT_START) / _EXIT_DUR)
            scale_f = 1.0 - t_x * 0.12
            alpha = max(0.0, 1.0 - t_x * t_x)
        else:
            hold_t = elapsed - _ENTRY
            scale_f = 1.0 + 0.012 * math.sin(hold_t * 3.1)
            alpha = 1.0

        if alpha <= 0.0:
            return

        tex = self._textures[self._slot]
        tw = self._tex_w * scale_f
        th = self._tex_h * scale_f
        cx = width * 0.5
        cy = height * 0.46
        tx0 = cx - tw * 0.5
        ty0 = cy - th * 0.5

        t = self._t
        cyc = 0.5 + 0.5 * math.sin(t * 2.8)
        gr = 0.9 + 0.1 * cyc
        gg = 0.05 + 0.10 * cyc
        gb = 0.85 - 0.4 * cyc

        for pad, glow_a in ((100, 0.14), (68, 0.18), (40, 0.23), (20, 0.29), (8, 0.37)):
            draw_rect(
                tx0 - pad, ty0 - pad, tw + pad * 2, th + pad * 2,
                (gr, gg, gb, glow_a * alpha),
            )

        phase = min(1.0, max(0.0, (elapsed - _ENTRY) / max(0.01, _EXIT_START - _ENTRY)))
        w_f, h_f = float(width), float(height)

        def to_ndc(px_: float, py_: float) -> tuple[float, float]:
            return (px_ / w_f) * 2.0 - 1.0, 1.0 - (py_ / h_f) * 2.0

        nx0, ny_top = to_ndc(tx0, ty0)
        nx1, ny_bot = to_ndc(tx0 + tw, ty0 + th)

        verts = np.array([
            nx0, ny_top,  0.0, 0.0,
            nx1, ny_top,  1.0, 0.0,
            nx0, ny_bot,  0.0, 1.0,
            nx1, ny_top,  1.0, 0.0,
            nx1, ny_bot,  1.0, 1.0,
            nx0, ny_bot,  0.0, 1.0,
        ], dtype=np.float32)

        self._quad_vbo.write(verts)
        self._blit_prog['iTime'].value = t
        self._blit_prog['iPhase'].value = phase
        self._blit_prog['iAlpha'].value = alpha
        tex.use(location=0)
        self._blit_prog['iChannel0'].value = 0
        ctx.enable(moderngl.BLEND)
        self._quad_vao.render(moderngl.TRIANGLES, vertices=6)

    def destroy(self) -> None:
        """Release all GL resources."""
        quad_vao = getattr(self, '_quad_vao', None)
        quad_vbo = getattr(self, '_quad_vbo', None)
        blit_prog = getattr(self, '_blit_prog', None)
        textures = getattr(self, '_textures', None)
        if quad_vao is not None:
            quad_vao.release()
        if quad_vbo is not None:
            quad_vbo.release()
        if blit_prog is not None:
            blit_prog.release()
        if textures is not None:
            for _t in textures:
                _t.release()

    def _ensure_resources(self, ctx: moderngl.Context) -> None:
        """Lazily build GLSL shader and PIL-rendered textures."""
        if self._blit_prog is None:
            vert = """
#version 330
in vec2 in_pos;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    v_uv = in_uv;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""
            frag = """
#version 330
uniform sampler2D iChannel0;
uniform float     iTime;
uniform float     iPhase;
uniform float     iAlpha;
in  vec2 v_uv;
out vec4 fragColor;
void main() {
    float ca  = mix(0.018, 0.004, clamp(iPhase * 2.5, 0.0, 1.0));
    float r   = texture(iChannel0, v_uv + vec2(-ca, 0.0)).r;
    float g   = texture(iChannel0, v_uv).g;
    float b   = texture(iChannel0, v_uv + vec2( ca, 0.0)).b;
    float a   = texture(iChannel0, v_uv).a;
    float cyc  = 0.5 + 0.5 * sin(iTime * 2.8);
    vec3  nA   = vec3(1.0,  0.12, 0.88);
    vec3  nB   = vec3(0.05, 0.95, 1.0);
    vec3  neon = mix(nA, nB, cyc);
    vec3  col  = vec3(r, g, b);
    float lum  = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(col, col * neon * 1.5, 0.45 * lum);
    col *= 0.92 + 0.08 * sin(v_uv.y * 160.0 + iTime * 18.0);
    col *= 0.90 + 0.10 * sin(iTime * 9.2);
    fragColor = vec4(col, a * iAlpha);
}
"""
            self._blit_prog = ctx.program(vertex_shader=vert, fragment_shader=frag)
            self._quad_vbo = ctx.buffer(reserve=6 * 4 * 4)
            self._quad_vao = ctx.vertex_array(
                self._blit_prog,
                [(self._quad_vbo, '2f 2f', 'in_pos', 'in_uv')],
            )

        slots_key = tuple(self._slots)
        if self._textures is not None and self._slots_key == slots_key:
            return

        if self._textures is not None:
            for _t in self._textures:
                _t.release()
        self._textures = []
        self._slots_key = slots_key
        if not _PIL_AVAILABLE:
            return

        text_font = None
        emoji_font = None
        try:
            if self._font_path is not None and self._font_path.exists():
                text_font = ImageFont.truetype(str(self._font_path), size=132)
        except Exception:
            pass
        try:
            icon_font_path = next(
                (p for p in [
                    Path('/usr/share/fonts/gdouros-symbola/Symbola.ttf'),
                    Path('/usr/share/fonts/gdouros-symbola/Symbola.otf'),
                    Path('/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf'),
                    Path('/usr/share/fonts/google-noto-emoji-fonts/NotoColorEmoji.ttf'),
                    Path('/usr/share/fonts/noto-emoji/NotoColorEmoji.ttf'),
                ] if p.exists()),
                None,
            )
            if icon_font_path is not None:
                emoji_font = ImageFont.truetype(str(icon_font_path), size=140)
        except Exception:
            pass

        TEX_W, TEX_H = self._tex_w, self._tex_h
        for text, icon in self._slots:
            try:
                img = self._build_image(text, icon, TEX_W, TEX_H, text_font, emoji_font)
            except Exception:
                log.debug('CTA image render failed for %r; using blank', text, exc_info=True)
                img = Image.new('RGBA', (TEX_W, TEX_H), (0, 0, 0, 0))
            data = np.array(img, dtype=np.uint8)
            tex = ctx.texture((TEX_W, TEX_H), 4, data=data.tobytes())
            tex.filter = moderngl.LINEAR, moderngl.LINEAR
            self._textures.append(tex)

    def _build_image(
        self,
        text: str,
        icon: str,
        width: int,
        height: int,
        text_font: 'ImageFont.FreeTypeFont | None',
        emoji_font: 'ImageFont.FreeTypeFont | None',
    ) -> 'Image.Image':
        """Render one CTA slot to a transparent RGBA PIL image."""
        img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        font = text_font or ImageFont.load_default()
        icon_font = emoji_font or font
        icon_clean = icon.replace('\ufe0f', '').strip()

        bbox_t = draw.textbbox((0, 0), text, font=font)
        tw = bbox_t[2] - bbox_t[0]
        th = bbox_t[3] - bbox_t[1]

        iw, ih = 0, 0
        bbox_i = (0, 0, 0, 0)
        if icon_clean:
            try:
                bbox_i = draw.textbbox((0, 0), icon_clean, font=icon_font)
                iw = bbox_i[2] - bbox_i[0]
                ih = bbox_i[3] - bbox_i[1]
            except Exception:
                icon_clean = ''

        gap = 36 if icon_clean else 0
        total_w = tw + gap + iw
        tx = max(0, (width - total_w) // 2)
        ty = (height - th) // 2

        draw.text((tx - bbox_t[0], ty - bbox_t[1]), text, font=font, fill=(255, 255, 255, 255))

        if icon_clean:
            ix = tx + tw + gap
            iy = ty + (th - ih) // 2
            draw.text((ix - bbox_i[0], iy - bbox_i[1]), icon_clean, font=icon_font, fill=(255, 255, 255, 255))

        return img


class Overlays:
    """Manages all HUD/overlay rendering."""

    HELP_SECTION_THEMES: dict[str, tuple[float, float, float]] = {
        'Help Usage': (0.98, 0.90, 0.62),
        'Basics': (0.18, 0.96, 0.86),
        'Unicorn Tears': (0.98, 0.78, 1.00),
        'Playback': (1.00, 0.68, 0.28),
        'Tweakables': (0.66, 0.92, 1.00),
        'Audio + Visual': (0.64, 0.86, 1.00),
        'Display Modes': (0.98, 0.94, 0.55),
        'Camera Overlay': (0.72, 1.00, 0.66),
    }
    DYNAMIC_THEME_CYCLE: list[tuple[float, float, float]] = [
        (0.88, 0.92, 1.00),
        (0.84, 1.00, 0.86),
        (1.00, 0.89, 0.84),
        (0.90, 0.85, 1.00),
        (0.98, 0.96, 0.72),
    ]

    CORE_HELP_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
        (
            'Help Usage',
            [
                ('Tab', 'Toggle section/icon focus'),
                ('Shift+-', 'Collapse all sections'),
                ('Shift+=', 'Expand all sections'),
                ('Arrow keys', 'Move section focus'),
                ('H / ?', 'Toggle help overlay'),
                ('Shift+H', 'Notifications on/off'),
                ('Enter', 'Toggle focused section'),
                ('0 - 9', 'Toggle section 1-10'),
            ],
        ),
        (
            'Basics',
            [
                ('f', 'Fullscreen'),
                ('Number', 'Jump #1-9'),
                ('Shift+Number', 'Jump #11-20'),
                ('Ctrl+Number', 'Jump #21-30'),
                ('Alt+Number', 'Jump #31-40'),
                ('n / Right', 'Next effect'),
                ('p / Left', 'Prev effect'),
                ('ESC', 'Quit'),
                ('u', 'Replay splash'),
                ('s', 'Screenshot'),
                ('TAB', 'Toggle HUD'),
                ('v', 'Toggle recording'),
            ],
        ),
        (
            'Playback',
            [
                ('; / \'', 'Advance interval -/+ 10s'),
                ('t', 'Auto-advance on/off'),
                ('Space', 'Pause / resume'),
                ('r', 'Random effects mode'),
                ('\\', 'Reset advance interval'),
            ],
        ),
        (
            'Tweakables',
            [
                ('[ / ]', 'Reactivity -/+'),
                ('{ / }', 'Reactivity MIN / MAX'),
                ('F6', 'Speed random ON / OFF'),
                ('F7', 'Reactivity random ON / OFF'),
                ('g', 'Reactivity reset'),
                (', / .', 'Res scale down / up'),
                ('Shift+, / .', 'Res scale MIN / MAX'),
                ('Ctrl+, / .', 'Reset res scale'),
                ('Ctrl+G', 'Speed reset'),
                ('Ctrl+= / Ctrl+-', 'Speed MAX / MIN'),
                ('+ / -', 'Speed up / down'),
                ('Alt+= / Alt+-', 'Speed random ON / OFF'),
                ('z / Z', 'Zoom in / out'),
                ('Alt+Z', 'Zoom random ON / OFF'),
                ('Ctrl+Z', 'Zoom reset'),
            ],
        ),
        (
            'Audio + Visual',
            [
                ('e', 'EQ / spectrum'),
                ('a / A', 'Audio source selector menu'),
                ('Ctrl+A', 'Audio source selector menu (alternate)'),
                ('Alt+A / Alt+Shift+A', 'BPM Profile next / prev'),
                ('Ctrl+Alt+1..9 / 0', 'Post FX quick-hit trigger (0 = Smoke & Bubbles)'),
                ('Ctrl+Alt+C', 'Toggle Candy Frame neon border overlay'),
                ('Ctrl+Alt+S', 'Start Spotify auth flow'),
                ('Ctrl+Alt+Shift+S', 'Logout Spotify auth (clear local token)'),
                ('Wheel Up/Down', 'Hue-shift frame (lasts 3 s idle)'),
                ('Ctrl+Wheel Up/Down', 'Rotate scene frame (lasts 3 s idle)'),
                ('Middle Click', 'Reset scroll FX (hue/rotation)'),
                ('Ctrl+Alt+F', 'Trigger Grand Finale sequence'),
                ('Ctrl+Alt+Shift+F', 'Abort Grand Finale'),
                ('m', 'System monitor modal'),
                ('Shift+M', 'Toggle Control Room'),
                ('Alt+M', 'MIDI device selector'),
                ('Ctrl+Alt+K', 'Webcam editor modal'),
                ('Ctrl+Alt+H', 'Controller help modal (APC slot map)'),
                ('i', 'Invert colors'),
            ],
        ),
    ]

    HELP_ICON_ENTRIES: list[dict[str, object]] = [
        {
            'id': 'about',
            'label': 'DJ UT',
            'image_id': 'about',
            'glyph': 'UT',
            'description': 'About / links page',
            'tooltip': 'Learn about DJ Tears & Unicorn-Viz!',
            'accent': (0.98, 0.78, 1.00),
            'action_kind': 'placeholder',
            'message': 'DJ UT info page coming soon',
        },
        {
            'id': 'contact',
            'label': 'Contact',
            'image_id': 'contact',
            'glyph': '@',
            'description': 'Send logs / VJ data / screenshots / recordings',
            'tooltip': 'Contact the DJ or Support',
            'accent': (0.10, 0.94, 1.00),
            'action_kind': 'placeholder',
            'message': 'Contact flow coming soon',
        },
        {
            'id': 'share',
            'label': 'Share',
            'image_id': 'share',
            'glyph': 'SH',
            'description': 'Open share link flow',
            'tooltip': 'Love Unicorn-Viz? Please share!!',
            'accent': (0.98, 0.96, 0.72),
            'action_kind': 'url',
            'target': 'https://unicorntears.com',
            'message': 'Opening share page',
        },
        {
            'id': 'shop',
            'label': 'Shop',
            'image_id': 'shop',
            'glyph': '$',
            'description': 'Open web store flow',
            'tooltip': 'Shop Unicorn Tears swag & software!',
            'accent': (0.98, 0.62, 0.22),
            'action_kind': 'placeholder',
            'message': 'Shop link coming soon',
        },
        {
            'id': 'dropins',
            'label': 'Drop-ins',
            'image_id': 'dropins',
            'glyph': 'DI',
            'description': 'ProjectM browser / future in-app purchases',
            'tooltip': 'Acquire & configure drop-in extensions',
            'accent': (0.66, 0.92, 1.00),
            'action_kind': 'projectm_manager',
            'message': 'Opening drop-ins browser',
        },
        {
            'id': 'settings',
            'label': 'Settings',
            'image_id': 'settings',
            'glyph': 'SET',
            'description': 'Future app settings placeholder',
            'tooltip': 'Open settings',
            'accent': (1.00, 0.68, 0.28),
            'action_kind': 'placeholder',
            'message': 'Settings panel coming soon',
        },
        # TODO(auth): Show this icon only when the operator is logged in.
        {
            'id': 'account',
            'label': 'Account',
            'image_id': 'account',
            'glyph': 'AC',
            'description': 'Future account hub placeholder',
            'tooltip': 'Your Account',
            'accent': (0.78, 0.38, 1.00),
            'action_kind': 'placeholder',
            'message': 'Account panel coming soon',
        },
        {
            'id': 'login_out',
            'label': 'Login/Out',
            'image_id_logged_out': 'login',
            'image_id_logged_in': 'logout',
            'glyph': 'IN',
            'description': 'Future auth flow placeholder',
            'tooltip_logged_out': 'Login',
            'tooltip_logged_in': 'Logout',
            'accent': (0.72, 1.00, 0.66),
            'action_kind': 'placeholder',
            'message': 'Login/Out coming soon',
        },
    ]

    # Drop-in help is now registered dynamically via HELP_ENTRIES in each drop-in
    # module and collected by discover_dropin_help_entries() at startup.
    DROPIN_HELP_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = []

    NUM_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]
    SHIFT_KEYS = ["S+1", "S+2", "S+3", "S+4", "S+5", "S+6", "S+7", "S+8", "S+9", "S+0"]
    CTRL_KEYS = ["C+1", "C+2", "C+3", "C+4", "C+5", "C+6", "C+7", "C+8", "C+9", "C+0"]
    ALT_KEYS = ["A+1", "A+2", "A+3", "A+4", "A+5", "A+6", "A+7", "A+8", "A+9", "A+0"]

    def __init__(
        self,
        ctx: moderngl.Context,
        width: int,
        height: int,
        flash_messages: bool = True,
        show_recording_indicator: bool = True,
        hud_auto_hide: bool = True,
        hud_timeout_s: float = 60.0,
        flash_router: Callable[[str, float], bool] | None = None,
        modal_gate: Callable[[], bool] | None = None,
    ) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._flash_enabled = flash_messages
        self._show_recording_indicator = show_recording_indicator
        self._hud_auto_hide = bool(hud_auto_hide)
        self._hud_timeout_s = max(0.0, float(hud_timeout_s))
        self._flash_router = flash_router
        self._modal_gate = modal_gate
        self._modal_route_debug_last: tuple[bool, str] | None = None
        self._recording_active = False
        self._recording_elapsed_seconds = 0.0

        self._show_name = False
        self._show_help = False
        self._show_audio = False
        self._show_midi = False
        self._show_system_monitor_modal = False
        self._show_controller_help_modal = False
        self._show_projectm_manager = False
        self._show_webcam_editor_modal = False
        self._audio_sources: list[str] = []
        self._audio_viable_flags: list[bool] = []
        self._audio_current_idx: int = 0
        self._audio_selected_idx: int = 0
        self._midi_ports: list[str] = []
        self._midi_current_port: str = ''
        self._midi_selected_idx: int = 0   # 0 = "None (disable)"
        self._projectm_entries: list[dict[str, object]] = []
        self._projectm_categories: list[str] = ['(all)']
        self._projectm_category_idx: int = 0
        self._projectm_preset_idx: int = 0
        self._projectm_focus_pane: int = 1
        self._projectm_current_path: str = ''
        self._projectm_search_query: str = ''
        self._webcam_editor_devices: list[dict[str, object]] = []
        self._webcam_editor_selected_idx: int = 0
        self._webcam_editor_state: dict[str, object] = {
            'brightness': 1.0,
            'contrast': 1.0,
            'flip_horizontal': True,
            'flip_vertical': False,
            'switching': False,
            'switch_hide_remaining_s': 0.0,
        }
        self._sysmon_cpu: float = 0.0
        self._sysmon_ram: float = 0.0
        self._sysmon_swap: float = 0.0
        self._sysmon_disk_mbs: float = 0.0
        self._sysmon_net_mbs: float = 0.0
        self._sysmon_sample_t: float = 0.0
        self._sysmon_prev_io_t: float | None = None
        self._sysmon_prev_disk_bytes: float | None = None
        self._sysmon_prev_net_bytes: float | None = None
        self._system_monitor_audio_provider: (
            Callable[[], dict[str, float]] | None
        ) = None
        self._system_monitor_tweakables_provider: (
            Callable[[], dict[str, float | None]] | None
        ) = None
        if _PSUTIL_AVAILABLE:
            try:
                psutil.cpu_percent(interval=None)
                disk = psutil.disk_io_counters()
                net = psutil.net_io_counters()
                self._sysmon_prev_io_t = time.monotonic()
                if disk is not None:
                    self._sysmon_prev_disk_bytes = float(disk.read_bytes + disk.write_bytes)
                if net is not None:
                    self._sysmon_prev_net_bytes = float(net.bytes_recv + net.bytes_sent)
            except Exception:
                pass
        self._help_timer: float = 0.0
        self._hud_timer: float = 0.0
        self._banner_timer: float = 0.0
        self._banner_change_counter: int = -1
        self._banner_enabled: bool = False
        self._banner_hold_s: float = 10.0
        self._banner_current_text: str = ''
        self._banner_previous_text: str = ''
        self._flash_text: str = ""
        self._flash_timer: float = 0.0
        self._name_text: str = ""
        self._hud_state: dict[str, str] = {
            'title': 'Unicorn Viz HUD',
            'effect': '-',
            'previous_effect': '-',
            'next_effect': '-',
            'transition': '-',
            'transition_t': '0%',
            'fps': '0.0',
            'frame_ms': '0.0',
            'resolution': '-',
            'render_scale': '1.00',
            'playlist': '-',
            'paused': 'NO',
            'fullscreen': 'NO',
            'auto_advance': 'ON',
            'advance_time': '0.0/20.0s',
            'reactivity': '1.0x',
            'speed': '-',
            'audio_source': '-',
            'audio_profile': 'house',
            'preset_slot_label': 'PRESET IDX',
            'preset_slot': '-/-',
            'variant_slot_label': 'VARIANT',
            'variant_slot': '-/-',
            'auto_vj_label': 'AUTO VJ',
            'auto_vj_training_badge': '',
            'recording': 'OFF',
            'streaming': 'OFF',
            'streaming_provider': '-',
            'spotify_visible': 'NO',
            'spotify_auth_visible': 'NO',
            'spotify_auth_status': 'OFF',
            'spotify_status': 'OFF',
            'spotify_track': '-',
            'spotify_artist': '-',
            'spotify_progress': '--:--/--:-- 0%',
            'postfx': 'N/A',
            'bass': '0.00',
            'mid': '0.00',
            'treble': '0.00',
            'audio_beat': '0.000',
            'display_mode': 'single',
            'display_index': '0',
            'invert': 'OFF',
            'vj_status': '',
        }
        self._num_shortcuts: list[str] = []
        self._shift_shortcuts: list[str] = []
        self._ctrl_shortcuts: list[str] = []
        self._alt_shortcuts: list[str] = []
        self._unmapped_effects: list[str] = []
        self._hud_rect: tuple[float, float, float, float] | None = None
        self._dynamic_help_sections: dict[str, list[tuple[str, str]]] = {}
        self._dynamic_help_order: list[str] = []
        self._postfx_help_entries: list[tuple[str, str]] = []
        self._help_collapsed: dict[str, bool] = {}
        self._help_focus_region: str = 'sections'
        self._help_focus_idx: int = 0
        self._help_icon_focus_idx: int = 0
        self._help_icon_hover_idx: int = -1
        self._help_icon_hover_pos: tuple[float, float] | None = None
        self._pending_help_icon_action: dict[str, str] | None = None
        self._help_pulse_t: float = 0.0
        self._hud_t: float = 0.0
        # Live PCM waveform fed each frame from the audio pipeline.
        # Used to render the Spotify progress-bar waveform visualization.
        self._live_waveform: np.ndarray | None = None
        self._spotify_beat_decay: float = 0.0
        self._help_icon_asset_dir: Path = resolve_path('assets/icons/help')
        self._help_icon_asset_bucket: str = self._help_icon_bucket_for_width(self._width)
        self._help_icon_textures: dict[str, moderngl.Texture] = {}


        self._font_tex, self._glyph_w, self._glyph_h, self._atlas_w, self._atlas_h, self._font_path = _build_font_texture(ctx)
        # Keep historical scale semantics (scale=1 roughly equals an 8 px cell).
        self._font_scale_norm = 8.0 / float(max(1, self._glyph_h))
        self._prog = self._build_program()
        self._build_vbo()
        self._build_panel_vbo()
        self._build_icon_vbo()
        self._load_help_icon_textures()
        self._cta = CTAOverlay(self._font_path, list(_CTA_SLOTS), _CTA_SHOW_DURATION)

    def _build_panel_vbo(self) -> None:
        """Build shader/VAO for simple colored overlay rectangles."""
        vert = """
#version 330
in vec2 in_vert;
void main() {
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""
        frag = """
#version 330
uniform vec4 color;
out vec4 fragColor;
void main() {
    fragColor = color;
}
"""
        self._panel_prog = self._ctx.program(vertex_shader=vert, fragment_shader=frag)
        self._panel_vbo = self._ctx.buffer(reserve=6 * 2 * 4)
        self._panel_vao = self._ctx.vertex_array(
            self._panel_prog,
            [(self._panel_vbo, "2f", "in_vert")],
        )

    def _build_icon_vbo(self) -> None:
        """Build shader/VAO for RGBA help icon textures."""
        vert = """
#version 330
in vec2 in_vert;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    gl_Position = vec4(in_vert, 0.0, 1.0);
    v_uv = in_uv;
}
"""
        frag = """
#version 330
uniform sampler2D icon_tex;
uniform float icon_alpha;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    vec4 c = texture(icon_tex, v_uv);
    fragColor = vec4(c.rgb, c.a * icon_alpha);
}
"""
        self._icon_prog = self._ctx.program(vertex_shader=vert, fragment_shader=frag)
        self._icon_vbo = self._ctx.buffer(reserve=6 * 4 * 4)
        self._icon_vao = self._ctx.vertex_array(
            self._icon_prog,
            [(self._icon_vbo, "2f 2f", "in_vert", "in_uv")],
        )

    def _help_icon_bucket_for_width(self, width: int) -> str:
        """Choose the help-icon asset bucket for the current viewport width."""
        return '152px' if int(width) >= 3840 else '76px'

    def _load_help_icon_textures(self) -> None:
        """Load icon textures from the selected assets/icons/help bucket."""
        self._help_icon_textures = {}
        if not _PIL_AVAILABLE:
            return
        asset_dir = self._help_icon_asset_dir / self._help_icon_asset_bucket
        if not asset_dir.exists():
            asset_dir = self._help_icon_asset_dir
        if not asset_dir.exists():
            return

        suffixes = ('.png', '.webp', '.jpg', '.jpeg')
        for src_path in sorted(asset_dir.iterdir()):
            if not src_path.is_file() or src_path.suffix.lower() not in suffixes:
                continue
            icon_id = src_path.stem.strip().lower()
            if not icon_id:
                continue
            try:
                img = Image.open(src_path).convert('RGBA')
                tex = self._ctx.texture(img.size, 4, img.tobytes())
                tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
                tex.repeat_x = False
                tex.repeat_y = False
                self._help_icon_textures[icon_id] = tex
            except Exception as exc:
                log.warning('Failed to load help icon texture %s: %s', src_path, exc)

    def _draw_icon_texture(
        self,
        tex: moderngl.Texture,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        alpha: float = 1.0,
    ) -> None:
        """Draw an RGBA icon texture in screen pixels."""
        def px(px_val: float) -> float:
            return (px_val / self._width) * 2.0 - 1.0

        def py(py_val: float) -> float:
            return 1.0 - (py_val / self._height) * 2.0

        x0 = px(x)
        x1 = px(x + w)
        y0 = py(y)
        y1 = py(y + h)
        verts = np.array([
            x0, y0, 0.0, 0.0,
            x1, y0, 1.0, 0.0,
            x0, y1, 0.0, 1.0,
            x1, y0, 1.0, 0.0,
            x1, y1, 1.0, 1.0,
            x0, y1, 0.0, 1.0,
        ], dtype=np.float32)
        self._icon_vbo.write(verts)
        self._icon_prog['icon_alpha'].value = float(max(0.0, min(1.0, alpha)))
        tex.use(location=0)
        self._icon_prog['icon_tex'].value = 0
        self._ctx.enable(moderngl.BLEND)
        self._icon_vao.render(moderngl.TRIANGLES, vertices=6)

    def _help_icon_image_id(self, entry: dict[str, object]) -> str:
        """Return the active image id for a help icon entry."""
        icon_id = str(entry.get('id', '') or '').strip().lower()
        if icon_id == 'login_out':
            auth_visible = str(self._hud_state.get('spotify_auth_visible', 'NO') or 'NO').strip().upper()
            auth_status = str(self._hud_state.get('spotify_auth_status', 'OFF') or 'OFF').strip().upper()
            if auth_visible == 'YES' and auth_status not in {'OFF', '-', ''}:
                return str(entry.get('image_id_logged_in', 'logout') or 'logout').strip().lower()
            return str(entry.get('image_id_logged_out', 'login') or 'login').strip().lower()
        image_id = str(entry.get('image_id', icon_id) or icon_id).strip().lower()
        return image_id or icon_id

    def _help_icon_tooltip(self, entry: dict[str, object]) -> str:
        """Return a short tooltip string for a help icon entry."""
        icon_id = str(entry.get('id', '') or '').strip().lower()
        if icon_id == 'login_out':
            auth_visible = str(self._hud_state.get('spotify_auth_visible', 'NO') or 'NO').strip().upper()
            auth_status = str(self._hud_state.get('spotify_auth_status', 'OFF') or 'OFF').strip().upper()
            if auth_visible == 'YES' and auth_status not in {'OFF', '-', ''}:
                return str(entry.get('tooltip_logged_in', 'Logout') or 'Logout').strip()
            return str(entry.get('tooltip_logged_out', 'Login') or 'Login').strip()
        tooltip = str(entry.get('tooltip', '') or '').strip()
        if tooltip:
            return tooltip
        return str(entry.get('description', entry.get('label', '')) or '').strip()

    def _help_icon_hit_test(self, x: float, y: float) -> int:
        """Return the icon index under x/y or -1 when not over an icon."""
        if not self._show_help:
            return -1
        panel_pad = 44.0
        px = panel_pad
        py = panel_pad
        pw = self._width - panel_pad * 2.0
        ph = self._height - panel_pad * 2.0
        if x < px or x > px + pw or y < py or y > py + ph:
            return -1

        res_ratio = min(self._width, self._height) / 1080.0
        help_scale = min(1.28, max(1.0, res_ratio ** 0.35))
        icon_band_y = py + 100.0
        icon_px = 152.0 if self._help_icon_asset_bucket == '152px' else 76.0
        band_h = max(icon_px + 20.0, 72.0 * help_scale)
        entries = self._help_icon_entries()
        if not entries:
            return -1

        gap = max(14.0, 16.0 * help_scale)
        cell_w = icon_px
        cell_h = icon_px
        total_w = len(entries) * cell_w + max(0, len(entries) - 1) * gap
        start_x = round(px + max(0.0, (pw - total_w) * 0.5))
        rail_y = round(icon_band_y + max(0.0, (band_h - cell_h) * 0.5) - 10.0)

        if y < icon_band_y or y > icon_band_y + band_h:
            return -1

        for idx, _entry in enumerate(entries):
            cell_x = round(start_x + idx * (cell_w + gap))
            if cell_x <= x <= cell_x + cell_w and rail_y <= y <= rail_y + cell_h:
                return idx
        return -1

    def handle_help_mouse_motion(self, x: float, y: float) -> bool:
        """Update hover state for help icon tooltips."""
        idx = self._help_icon_hit_test(x, y)
        self._help_icon_hover_idx = idx
        self._help_icon_hover_pos = (float(x), float(y)) if idx >= 0 else None
        return idx >= 0

    def _draw_rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        color: tuple[float, float, float, float],
    ) -> None:
        """Draw a solid-color rectangle in screen pixels."""
        def px(px_val: float) -> float:
            return (px_val / self._width) * 2.0 - 1.0

        def py(py_val: float) -> float:
            return 1.0 - (py_val / self._height) * 2.0

        x0 = px(x)
        x1 = px(x + w)
        y0 = py(y)
        y1 = py(y + h)
        verts = np.array([
            x0, y0,
            x1, y0,
            x0, y1,
            x1, y0,
            x1, y1,
            x0, y1,
        ], dtype=np.float32)
        self._panel_vbo.write(verts)
        self._panel_prog["color"].value = color
        self._ctx.enable(moderngl.BLEND)
        self._panel_vao.render(moderngl.TRIANGLES, vertices=6)

    def _build_program(self) -> moderngl.Program:
        vert = """
#version 330
in vec2 in_vert;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    gl_Position = vec4(in_vert, 0.0, 1.0);
    v_uv = in_uv;
}
"""
        frag = """
#version 330
uniform sampler2D font_tex;
uniform vec4 color;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    float a = texture(font_tex, v_uv).r;
    fragColor = vec4(color.rgb, color.a * a);
}
"""
        return self._ctx.program(vertex_shader=vert, fragment_shader=frag)

    def _build_vbo(self) -> None:
        # We'll generate geometry dynamically per frame; start with empty buffer.
        self._vbo = self._ctx.buffer(reserve=1024 * 4 * 4)
        self._vao = self._ctx.vertex_array(
            self._prog,
            [(self._vbo, "2f 2f", "in_vert", "in_uv")],
        )

    def _char_quads(
        self,
        text: str,
        x: float,
        y: float,
        scale: float,
        color: tuple[float, float, float, float],
    ) -> np.ndarray:
        """
        Build interleaved (pos_x, pos_y, uv_x, uv_y) vertex data for `text`.
        x, y are in screen pixels from top-left.
        scale is pixels-per-cell (8 px = 1x).
        Returns float32 array of 6 vertices per character (2 tris).
        """
        norm_scale = scale * self._font_scale_norm
        char_w = float(self._glyph_w) * norm_scale
        char_h = float(self._glyph_h) * norm_scale
        atlas_w = float(self._atlas_w)
        atlas_h = float(self._atlas_h)

        verts: list[float] = []
        cx = x
        for ch in text:
            code = ord(ch) & 0x7F
            u0 = (code * self._glyph_w) / atlas_w
            u1 = u0 + float(self._glyph_w) / atlas_w
            v0 = 0.0
            v1 = float(self._glyph_h) / atlas_h

            # NDC conversion
            def px(px_val: float) -> float:
                return (px_val / self._width) * 2.0 - 1.0

            def py(py_val: float) -> float:
                return 1.0 - (py_val / self._height) * 2.0

            x0 = px(cx)
            x1 = px(cx + char_w)
            y0 = py(y)
            y1 = py(y + char_h)

            # Two triangles (6 verts)
            verts += [x0, y0, u0, v0]
            verts += [x1, y0, u1, v0]
            verts += [x0, y1, u0, v1]
            verts += [x1, y0, u1, v0]
            verts += [x1, y1, u1, v1]
            verts += [x0, y1, u0, v1]

            cx += char_w

        return np.array(verts, dtype=np.float32) if verts else np.zeros(0, dtype=np.float32)

    def _draw_text(
        self,
        text: str,
        x: float,
        y: float,
        scale: float = 2.0,
        color: tuple[float, float, float, float] = (1.0, 1.0, 0.0, 1.0),
    ) -> None:
        data = self._char_quads(text, x, y, scale, color)
        if data.size == 0:
            return
        # Resize VBO if needed.
        needed = data.nbytes
        if needed > self._vbo.size:
            self._vbo.orphan(needed * 2)
        self._vbo.write(data)
        self._prog['color'].value = color
        self._font_tex.use(location=0)
        self._prog['font_tex'].value = 0
        self._ctx.enable(moderngl.BLEND)
        self._vao.render(moderngl.TRIANGLES, vertices=len(data) // 4)

    def _draw_modal_underlay(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        alpha: float,
        pad: float = 0.0,
    ) -> None:
        """Draw a local dim underlay sized to a modal/help panel.

        The underlay is clamped to the active overlay canvas and intentionally
        avoids full-viewport fills so modal backgrounds track panel geometry in
        multi-head viewport routing.
        """
        x0 = max(0.0, float(x) - float(pad))
        y0 = max(0.0, float(y) - float(pad))
        x1 = min(float(self._width), float(x) + float(w) + float(pad))
        y1 = min(float(self._height), float(y) + float(h) + float(pad))
        if x1 <= x0 or y1 <= y0:
            return
        self._draw_rect(x0, y0, x1 - x0, y1 - y0, (0.0, 0.0, 0.0, float(alpha)))

    def _begin_panel(
        self,
        frac_w: float,
        max_w: float,
        frac_h: float,
        max_h: float,
        underlay_alpha: float = 0.58,
        underlay_pad: float = 10.0,
    ) -> tuple[float, float, float, float, float, float]:
        """Compute centred panel geometry, draw dim underlay, return (px, py, pw, ph, W, H)."""
        W = float(self._width)
        H = float(self._height)
        pw = min(W * float(frac_w), float(max_w))
        ph = min(H * float(frac_h), float(max_h))
        px = (W - pw) * 0.5
        py = (H - ph) * 0.5
        self._draw_modal_underlay(px, py, pw, ph, alpha=underlay_alpha, pad=underlay_pad)
        return px, py, pw, ph, W, H

    def _render_controller_help_modal(self) -> None:
        """Draw a controller-focused mapping modal (APC mini mk2 first target)."""
        t = self._hud_t
        pulse = 0.55 + 0.45 * math.sin(t * 2.7)

        px, py, panel_w, panel_h, W, H = self._begin_panel(0.88, 1240.0, 0.86, 860.0, underlay_alpha=0.58, underlay_pad=10.0)

        self._draw_rect(px, py, panel_w, panel_h, (0.04, 0.05, 0.12, 0.96))
        bw = 2.0
        c_border = (0.18 * pulse, 0.55 * pulse, 1.0 * pulse, 0.92)
        self._draw_rect(px, py, panel_w, bw, c_border)
        self._draw_rect(px, py + panel_h - bw, panel_w, bw, c_border)
        self._draw_rect(px, py, bw, panel_h, c_border)
        self._draw_rect(px + panel_w - bw, py, bw, panel_h, c_border)
        bass = float(self._hud_state.get('bass', '0.0') or 0.0)
        mid = float(self._hud_state.get('mid', '0.0') or 0.0)
        treble = float(self._hud_state.get('treble', '0.0') or 0.0)
        self._draw_audio_reactive_border_bulbs(px, py, panel_w, panel_h, bass, mid, treble, t, speed_scale=0.5, size_scale=0.5)


        self._draw_text(
            'CONTROLLER HELP // APC MINI MK2',
            px + 18.0,
            py + 14.0,
            scale=3.2,
            color=(0.30 + 0.20 * pulse, 0.76, 1.0, 1.0),
        )
        self._draw_text(
            'Context slots drive side + bottom buttons and adapt by active modal.',
            px + 20.0,
            py + 46.0,
            scale=2.0,
            color=(0.66, 0.84, 0.95, 0.92),
        )

        col_gap = 14.0
        col_w = (panel_w - 40.0 - col_gap * 2.0) / 3.0
        col_x = [
            px + 14.0,
            px + 14.0 + col_w + col_gap,
            px + 14.0 + (col_w + col_gap) * 2.0,
        ]
        top_y = py + 78.0

        def _card(
            x: float,
            y: float,
            w: float,
            h: float,
            title: str,
            lines: list[str],
            accent: tuple[float, float, float],
        ) -> None:
            self._draw_rect(x, y, w, h, (0.09, 0.12, 0.19, 0.88))
            self._draw_rect(x, y, w, 2.0, (accent[0], accent[1], accent[2], 0.95))
            self._draw_text(
                title,
                x + 10.0,
                y + 8.0,
                scale=2.2,
                color=(accent[0], accent[1], accent[2], 0.98),
            )
            yy = y + 30.0
            for line in lines:
                self._draw_text(
                    line,
                    x + 10.0,
                    yy,
                    scale=1.85,
                    color=(0.80, 0.87, 0.96, 0.95),
                )
                yy += 17.0

        _card(
            col_x[0],
            top_y,
            col_w,
            248.0,
            'Performance Context (no modal)',
            [
                'Slot1 next, Slot2 prev, Slot3 random, Slot4 pause',
                'Slot5 fullscreen, Slot6 EQ/audio toggle',
                'Slot7 ANSI, Slot8 controller help modal',
                'Scene/Track small buttons mirror slots 1..8',
            ],
            (0.26 + 0.08 * pulse, 0.92, 0.80),
        )

        _card(
            col_x[1],
            top_y,
            col_w,
            248.0,
            'Selector Contexts (Audio/MIDI)',
            [
                'Slot1/2: up/down',
                'Slot3/4: left/right',
                'Slot5: apply/select',
                'Audio Slot6: toggle viable',
                'Slot7/8: back / selector shortcut',
            ],
            (0.90, 0.78, 0.30 + 0.10 * pulse),
        )

        _card(
            col_x[2],
            top_y,
            col_w,
            248.0,
            'Other Contexts',
            [
                'Help: slot nav + expand/collapse + close',
                'ProjectM: slot nav, focus, search, close',
                'System monitor: close + escape actions',
                'Controller help: slots route to close/navigation',
            ],
            (0.56, 0.73 + 0.08 * pulse, 1.0),
        )

        _card(
            col_x[0],
            top_y + 262.0,
            col_w,
            208.0,
            'APC Grid Highlights',
            [
                'Row7 transport/show globals',
                'Row6 display modes + HUD/help/screenshot',
                'Rows5-4 PostFX + finale + selector controls',
                'Rows3-0 contextual and utility anchors',
            ],
            (0.42, 0.92, 0.58 + 0.06 * pulse),
        )

        _card(
            col_x[1],
            top_y + 262.0,
            col_w,
            208.0,
            'Faders (CC 48-56)',
            [
                '48 speed, 49 intensity, 50 zoom, 51 reactivity',
                '52 glow, 53 crt, 54 volume, 55 pan',
                '56 master volume',
                'All mapped by default in APC preset',
            ],
            (0.95, 0.62 + 0.08 * pulse, 0.34),
        )

        _card(
            col_x[2],
            top_y + 262.0,
            col_w,
            208.0,
            'Operator Notes',
            [
                'Set [midi] preset = "akai_apc_mini_mk2"',
                'Use device hint "apc mini mk2" for dual-port bind',
                'Modal style intentionally matches native selectors',
                'Framework designed to host future controller pages',
            ],
            (0.66, 0.78, 0.98),
        )

        self._draw_text(
            'Ctrl+Alt+H: close    Esc: close    Context slots: side + bottom small buttons',
            px + 18.0,
            py + panel_h - 30.0,
            scale=2.0,
            color=(0.56, 0.67, 0.78, 0.82),
        )

    def _render_recording_indicator(self) -> None:
        """Draw the live-only recording indicator when the name overlay is visible."""
        if not (self._recording_active and self._show_recording_indicator):
            return
        if not (self._show_name and self._name_text):
            return
        elapsed = max(0, int(self._recording_elapsed_seconds))
        minutes, seconds = divmod(elapsed, 60)
        hours, minutes = divmod(minutes, 60)
        timer_text = f'{hours:02d}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'

        if self._hud_rect is not None:
            x, y, w, _h = self._hud_rect
            dot_x = x + w - 210.0
            dot_y = y + 10.0
            time_x = x + w - 178.0
            time_y = y + 18.0
        else:
            dot_x = self._width - 84.0
            dot_y = 0.0
            time_x = self._width - 210.0
            time_y = 24.0

        self._draw_text(
            '.',
            dot_x,
            dot_y,
            scale=10.0,
            color=(1.0, 0.12, 0.12, 0.98),
        )
        self._draw_text(
            timer_text,
            time_x,
            time_y,
            scale=2.8,
            color=(1.0, 0.16, 0.16, 0.95),
        )

    def _auto_vj_status_label(self) -> str:
        """Return the Auto VJ label decorated with the current trainer badge."""
        label = str(self._hud_state.get('auto_vj_label', 'AUTO VJ') or 'AUTO VJ').strip().upper()
        badge = str(self._hud_state.get('auto_vj_training_badge', '') or '').strip()
        if badge not in {'*', '+', '='}:
            badge = ''
        if badge:
            return f'{label} {badge}'
        return label

    def _render_hud(self) -> None:
        """Render animated LCARS-style status HUD with pulsing glows, scan lines and decorations."""
        panel_w = min(1050.0, self._width * 0.93)
        lh = 28.0
        spotify_visible = str(self._hud_state.get('spotify_visible', 'NO')).upper() == 'YES'
        row0_offset = 264.0 if spotify_visible else 188.0
        row_text_h = 8.0 * 2.05 + 4.0

        # ── animation clocks ─────────────────────────────────────────────
        t = self._hud_t
        pulse_slow  = 0.5 + 0.5 * math.sin(t * 1.1)          # ~5.7 s period
        pulse_med   = 0.5 + 0.5 * math.sin(t * 2.3)          # ~2.7 s period
        pulse_fast  = 0.5 + 0.5 * math.sin(t * 4.7)          # ~1.3 s period
        # racing scanline: 0→1 across the panel every 3 s
        scan_h      = math.fmod(t * 0.33, 1.0)
        # shimmer racing across the header left→right every 2.4 s
        shimmer_x   = math.fmod(t * 0.42, 1.0)
        # audio values (safe parse)
        def _fv(key: str) -> float:
            try: return float(self._hud_state.get(key, '0') or '0')
            except ValueError: return 0.0
        bass = min(_fv('bass'), 1.0)
        mid  = min(_fv('mid'),  1.0)
        auto_vj_label = self._auto_vj_status_label()

        postfx_val = str(self._hud_state.get('postfx', 'N/A'))
        # Tweakables sorted alphabetically; POST FX only shown when drop-in is loaded.
        tweak_lines = []
        if postfx_val not in {'N/A', '-', ''}:
            tweak_lines.append(f"POST FX     {postfx_val}")
        compose_dbg = str(self._hud_state.get('compose_debug', ''))
        if compose_dbg not in {'', 'N/A', '-'}:
            tweak_lines.append(f"COMPOSE     {compose_dbg}")
        tweak_lines += [
            f"REACTIVITY  {self._hud_state.get('reactivity', '1.0')}",
            f"SPEED       {self._hud_state.get('speed', 'N/A')}",
            f"ZOOM        {self._hud_state.get('zoom', 'N/A')}",
            f"VIZ QUAL    {self._hud_state.get('render_scale', '1.00')}",
        ]

        left_lines = [
            f"B / M / T   {self._hud_state.get('bass', '0.00')} / {self._hud_state.get('mid', '0.00')} / {self._hud_state.get('treble', '0.00')}",
            f"Bn/Mn/Tn    {self._hud_state.get('bass_n', '0.50')} / {self._hud_state.get('mid_n', '0.50')} / {self._hud_state.get('treble_n', '0.50')}",
            f"INPUT RMS   {self._hud_state.get('audio_rms', '0.0000')}",
            f"FPS         {self._hud_state.get('fps', '0.0')}",
            f"FRAME MS    {self._hud_state.get('frame_ms', '0.0')}",
            f"RES         {self._hud_state.get('resolution', '-')}",
            f"PLAYLIST    {self._hud_state.get('playlist', '-')}",
            f"AUDIO SRC   {self._hud_state.get('audio_source', '-')}",
            f"BPM PROF    {self._hud_state.get('audio_profile', 'house')}",
            f"REC PROF    {self._hud_state.get('audio_profile_reco', '-')}",
            '',
            '[ TWEAKABLES ]',
            *tweak_lines,
        ]
        right_lines = [
            f"ADV TIMER   {self._hud_state.get('advance_time', '0.0/20.0s')}",
            f"AUTO ADV    {self._hud_state.get('auto_advance', 'ON')}",
            f"DISPLAY     {self._hud_state.get('display_mode', 'single')} #{self._hud_state.get('display_index', '0')}",
            f"FULLSCREEN  {self._hud_state.get('fullscreen', 'NO')}",
            f"INVERT      {self._hud_state.get('invert', 'OFF')}",
            f"NEXT FX     {self._hud_state.get('next_effect', '-')}",
            f"PAUSED      {self._hud_state.get('paused', 'NO')}",
            f"{self._hud_state.get('preset_slot_label', 'PRESET IDX'):<11} {self._hud_state.get('preset_slot', '-/-')}",
            f"PREV FX     {self._hud_state.get('previous_effect', '-')}",
            f"RECORDING   {self._hud_state.get('recording', 'OFF')}",
            f"SPOTIFY AUTH {self._hud_state.get('spotify_auth_status', 'OFF')}",
            f"STREAM SRV  {self._hud_state.get('streaming_provider', '-')}",
            f"STREAMING   {self._hud_state.get('streaming', 'OFF')}",
            f"TRANSITION  {self._hud_state.get('transition', '-')} ({self._hud_state.get('transition_t', '0%')})",
            f"{self._hud_state.get('variant_slot_label', 'VARIANT'):<11} {self._hud_state.get('variant_slot', '-/-')}",
        ]

        rows = max(len(left_lines), len(right_lines))
        content_bottom = row0_offset + max(0, rows - 1) * lh + row_text_h
        panel_h_needed = content_bottom + 34.0
        panel_h_base = min(max(520.0, panel_h_needed), self._height * 0.88)
        panel_h_extra = max(50.0, panel_h_base * 0.05)
        panel_h = min(panel_h_base + panel_h_extra, self._height * 0.93)
        x = (self._width - panel_w) * 0.5
        y = max(36.0, (self._height - panel_h) * 0.5)
        self._hud_rect = (x, y, panel_w, panel_h)

        data_zone_y  = y + row0_offset - 8.0
        data_zone_h  = rows * lh + 16.0

        # ── layer 0: breathing outer halo ────────────────────────────────
        halo_a = 0.06 + pulse_slow * 0.10
        self._draw_rect(x - 18.0, y - 18.0, panel_w + 36.0, panel_h + 36.0, (0.08, 0.88, 1.0, halo_a * 0.5))
        self._draw_rect(x - 8.0,  y - 8.0,  panel_w + 16.0, panel_h + 16.0, (0.08, 0.88, 1.0, halo_a))

        # ── layer 1: main panel background ───────────────────────────────
        self._draw_rect(x, y, panel_w, panel_h, (0.02, 0.04, 0.08, 0.65))

        # ── layer 2: animated outer border (pulsing alpha) ───────────────
        border_a = 0.50 + pulse_slow * 0.34
        self._draw_rect(x - 1.0, y - 1.0, panel_w + 2.0, 2.0,          (0.10, 0.94, 1.0, border_a))
        self._draw_rect(x - 1.0, y + panel_h - 1.0, panel_w + 2.0, 2.0, (0.10, 0.94, 1.0, border_a))
        self._draw_rect(x - 1.0, y - 1.0, 2.0, panel_h + 2.0,          (0.10, 0.94, 1.0, border_a))
        self._draw_rect(x + panel_w - 1.0, y - 1.0, 2.0, panel_h + 2.0, (0.10, 0.94, 1.0, border_a))

        # ── sparkle sprite chasing the containment border ─────────────────
        # Position 0→1 travels: top-left → top-right → bottom-right → bottom-left → back
        # Speed: one full lap every 4 s
        sprite_t = math.fmod(t * 0.20, 1.0)
        perim    = 2.0 * (panel_w + panel_h)
        dist     = sprite_t * perim
        top_seg  = panel_w
        right_seg= panel_h
        bot_seg  = panel_w
        # left_seg = panel_h (remainder)
        if dist < top_seg:                              # top edge L→R
            sx, sy = x + dist, y - 1.0
        elif dist < top_seg + right_seg:               # right edge T→B
            sx, sy = x + panel_w - 1.0, y + (dist - top_seg)
        elif dist < top_seg + right_seg + bot_seg:     # bottom edge R→L
            sx, sy = x + panel_w - (dist - top_seg - right_seg), y + panel_h - 1.0
        else:                                           # left edge B→T
            sx, sy = x - 1.0, y + panel_h - (dist - top_seg - right_seg - bot_seg)
        # glow layers: wide soft bloom → tight mid → bright core
        sp_a = 0.72 + 0.28 * math.sin(t * 11.3)   # fast inner flicker — starts at 0.72 floor
        self._draw_rect(sx - 10.0, sy - 10.0, 22.0, 22.0, (0.10, 0.94, 1.0, sp_a * 0.22))
        self._draw_rect(sx -  7.0, sy -  7.0, 16.0, 16.0, (0.10, 0.94, 1.0, sp_a * 0.46))
        self._draw_rect(sx -  4.0, sy -  4.0, 10.0, 10.0, (0.50, 0.98, 1.0, sp_a * 0.76))
        self._draw_rect(sx -  2.0, sy -  2.0,  6.0,  6.0, (0.80, 1.00, 1.0, sp_a * 0.92))
        self._draw_rect(sx -  1.0, sy -  1.0,  4.0,  4.0, (1.00, 1.00, 1.0, min(1.0, sp_a * 1.10)))
        # trailing ghost — half-lap behind
        trail_t  = math.fmod(sprite_t + 0.5, 1.0)
        trail_d  = trail_t * perim
        if trail_d < top_seg:
            tx2, ty2 = x + trail_d, y - 1.0
        elif trail_d < top_seg + right_seg:
            tx2, ty2 = x + panel_w - 1.0, y + (trail_d - top_seg)
        elif trail_d < top_seg + right_seg + bot_seg:
            tx2, ty2 = x + panel_w - (trail_d - top_seg - right_seg), y + panel_h - 1.0
        else:
            tx2, ty2 = x - 1.0, y + panel_h - (trail_d - top_seg - right_seg - bot_seg)
        tr_a = 0.42 + 0.28 * math.sin(t * 7.1)
        self._draw_rect(tx2 - 5.0, ty2 - 5.0, 12.0, 12.0, (0.78, 0.38, 1.00, tr_a * 0.38))
        self._draw_rect(tx2 - 3.0, ty2 - 3.0,  8.0,  8.0, (0.78, 0.38, 1.00, tr_a * 0.65))
        self._draw_rect(tx2 - 1.0, ty2 - 1.0,  4.0,  4.0, (1.00, 0.70, 1.00, tr_a * 0.90))

        # ── layer 3: LCARS side decorative block stacks ───────────────────
        # Each block has its own independent phase so they flash individually.
        # Tuple: (height, base_rgb, base_alpha, phase_offset, phase_speed, strobe_speed)
        side_w   = 18.0
        block_defs = [
            (28.0, (1.00, 0.58, 0.12), 0.68, 0.00, 2.30, 0.0 ),   # orange
            (6.0,  None, 0, 0, 0, 0),
            (8.0,  (1.00, 0.58, 0.12), 0.34, 0.70, 4.10, 7.3 ),   # orange thin – fast strobe
            (6.0,  None, 0, 0, 0, 0),
            (44.0, (0.10, 0.94, 1.00), 0.68, 1.10, 1.80, 0.0 ),   # teal large
            (6.0,  None, 0, 0, 0, 0),
            (14.0, (0.78, 0.38, 1.00), 0.56, 2.20, 3.50, 0.0 ),   # violet
            (6.0,  None, 0, 0, 0, 0),
            (60.0, (1.00, 0.58, 0.12), 0.56, 0.50, 1.10, 0.0 ),   # orange long
            (6.0,  None, 0, 0, 0, 0),
            (14.0, (0.10, 0.94, 1.00), 0.48, 1.80, 5.20, 11.7),   # teal – fast strobe
            (6.0,  None, 0, 0, 0, 0),
            (28.0, (0.98, 0.96, 0.30), 0.52, 0.90, 2.70, 0.0 ),   # yellow
            (6.0,  None, 0, 0, 0, 0),
            (14.0, (0.78, 0.38, 1.00), 0.44, 3.10, 4.80, 9.1 ),   # violet – strobe
            (6.0,  None, 0, 0, 0, 0),
            (24.0, (1.00, 0.58, 0.12), 0.62, 1.60, 2.10, 0.0 ),   # orange
        ]
        side_rx = x + panel_w + 4.0
        side_lx = x - 4.0 - side_w
        by_r = y
        by_l = y
        for bdef in block_defs:
            bh = bdef[0]
            if bdef[1] is None:          # gap
                by_r += bh
                by_l += bh
                continue
            bh, rgb, base_a, phase, spd, strobe_spd = bdef
            pulse_val = 0.5 + 0.5 * math.sin(t * spd + phase)
            alpha = base_a + pulse_val * 0.28
            if strobe_spd > 0:
                # occasional fast strobe: rectified high-freq sine → sharp flash
                strobe = max(0.0, math.sin(t * strobe_spd)) ** 3
                alpha = min(1.0, alpha + strobe * 0.38)
            bc = (rgb[0], rgb[1], rgb[2], min(1.0, alpha))
            # right side
            self._draw_rect(side_rx, by_r, side_w, bh, bc)
            # edge highlight (inner thin bright line)
            hi_a = min(1.0, alpha * 0.55 + pulse_val * 0.25)
            self._draw_rect(side_rx, by_r, 2.0, bh, (1.0, 1.0, 1.0, hi_a))
            # left side (mirrored — edge highlight on right edge of block)
            self._draw_rect(side_lx, by_l, side_w, bh, bc)
            self._draw_rect(side_lx + side_w - 2.0, by_l, 2.0, bh, (1.0, 1.0, 1.0, hi_a))
            by_r += bh
            by_l += bh

        # ── layer 4: corner accent blocks + crosshair arms (pulsing orange) ───
        corner_sz = 14.0
        ca = 0.65 + pulse_fast * 0.30
        self._draw_rect(x - 1.0, y - 1.0, corner_sz, corner_sz,                                   (1.0, 0.58, 0.12, ca))
        self._draw_rect(x + panel_w - corner_sz + 1.0, y - 1.0, corner_sz, corner_sz,             (1.0, 0.58, 0.12, ca))
        self._draw_rect(x - 1.0, y + panel_h - corner_sz + 1.0, corner_sz, corner_sz,             (1.0, 0.58, 0.12, ca))
        self._draw_rect(x + panel_w - corner_sz + 1.0, y + panel_h - corner_sz + 1.0, corner_sz, corner_sz, (1.0, 0.58, 0.12, ca))
        # Inner teal corner squares
        ic = 6.0
        ica = 0.52 + pulse_slow * 0.32
        self._draw_rect(x + 2.0, y + 2.0, ic, ic, (0.10, 0.94, 1.0, ica))
        self._draw_rect(x + panel_w - ic - 2.0, y + 2.0, ic, ic, (0.10, 0.94, 1.0, ica))
        self._draw_rect(x + 2.0, y + panel_h - ic - 2.0, ic, ic, (0.10, 0.94, 1.0, ica))
        self._draw_rect(x + panel_w - ic - 2.0, y + panel_h - ic - 2.0, ic, ic, (0.10, 0.94, 1.0, ica))
        # Corner crosshair arms — thin lines extending inward from each corner
        arm_len = 40.0
        arm_a   = 0.28 + pulse_slow * 0.20
        # top-left
        self._draw_rect(x + corner_sz, y + 1.0,    arm_len, 1.0, (1.0, 0.58, 0.12, arm_a))  # horiz
        self._draw_rect(x + 1.0, y + corner_sz,    1.0, arm_len, (1.0, 0.58, 0.12, arm_a))  # vert
        # top-right
        self._draw_rect(x + panel_w - corner_sz - arm_len, y + 1.0,    arm_len, 1.0, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + panel_w - 2.0, y + corner_sz,              1.0, arm_len, (1.0, 0.58, 0.12, arm_a))
        # bottom-left
        self._draw_rect(x + corner_sz, y + panel_h - 2.0,              arm_len, 1.0, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + 1.0, y + panel_h - corner_sz - arm_len,   1.0, arm_len, (1.0, 0.58, 0.12, arm_a))
        # bottom-right
        self._draw_rect(x + panel_w - corner_sz - arm_len, y + panel_h - 2.0, arm_len, 1.0, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + panel_w - 2.0, y + panel_h - corner_sz - arm_len, 1.0, arm_len, (1.0, 0.58, 0.12, arm_a))

        # ── layer 5: header ──────────────────────────────────────────────
        self._draw_rect(x, y, panel_w, 100.0, (0.05, 0.08, 0.16, 0.80))

        # Header shimmer: bright spot racing left→right along the title bar
        shim_w = panel_w * 0.18
        shim_x = x + shimmer_x * (panel_w - shim_w)
        self._draw_rect(shim_x, y, shim_w, 100.0, (1.0, 1.0, 1.0, 0.04 + pulse_fast * 0.04))

        # Header separator — triple lines for LCARS depth
        bar_a = 0.60 + pulse_slow * 0.22
        self._draw_rect(x, y + 94.0, panel_w, 2.0, (1.0, 0.62, 0.20, bar_a * 0.5))
        self._draw_rect(x, y + 97.0, panel_w, 4.0, (1.0, 0.62, 0.20, bar_a))
        self._draw_rect(x, y + 102.0, panel_w, 1.0, (1.0, 0.62, 0.20, bar_a * 0.4))

        # Title — no background rect; text pulses inversely to where the bg was
        title = self._hud_state.get('title', 'Unicorn Viz')
        tx = x + (panel_w - len(title) * 8.0 * 3.0) * 0.5
        # Inverse of pulse_med: bright when pulse_med is low, dim when it peaks
        title_a = 0.86 + (1.0 - pulse_med) * 0.14
        self._draw_text(title, tx, y + 8.0, scale=3.0, color=(0.12, 0.98, 1.0, title_a))

        # Date/time (orange)
        now = datetime.datetime.now()
        dt_line = f"{now.strftime('%Y-%m-%d')}  {now.strftime('%H:%M:%S')}"
        dx = x + (panel_w - len(dt_line) * 8.0 * 2.2) * 0.5
        self._draw_text(dt_line, dx, y + 44.0, scale=2.2, color=(1.0, 0.64 + pulse_slow * 0.10, 0.22, 0.94))
        session_line = f"SESSION   {self._hud_state.get('session_time', '00:00')}"
        sx_session = x + (panel_w - len(session_line) * 8.0 * 2.2) * 0.5
        self._draw_text(session_line, sx_session, y + 76.0, scale=2.2, color=(0.12, 0.98, 1.0, title_a))

        # ── layer 6: Spotify sub-pane + effect banner ────────────────────
        band_x = x + 8.0
        band_y = y + 104.0
        band_w = panel_w - 16.0
        band_h = 156.0 if spotify_visible else 80.0

        # Spotify sub-pane (between title/timer header and main data panes).
        spotify_h = 72.0 if spotify_visible else 0.0
        spotify_y = band_y
        spotify_status = str(self._hud_state.get('spotify_status', 'OFF'))
        spotify_track = str(self._hud_state.get('spotify_track', '-'))
        spotify_artist = str(self._hud_state.get('spotify_artist', '-'))
        spotify_progress = str(self._hud_state.get('spotify_progress', '--:--/--:-- 0%'))

        status_l = spotify_status.lower()
        if status_l == 'playing':
            accent = (0.16, 0.95, 0.48)
        elif status_l == 'paused':
            accent = (0.78, 0.52, 1.00)
        else:
            accent = (0.46, 0.90, 0.98)

        # Effect banner lives below Spotify when visible, otherwise occupies the top band.
        effect_y = spotify_y + spotify_h + 4.0 if spotify_visible else band_y
        effect_h = 80.0
        banner_glow_a = 0.06 + bass * 0.26 + pulse_slow * 0.04
        self._draw_rect(band_x, effect_y, band_w, effect_h, (0.04, 0.60 + bass * 0.40, 0.80, banner_glow_a))
        self._draw_rect(band_x, effect_y, band_w, effect_h, (0.03, 0.07, 0.14, 0.72))
        banner_race = math.fmod(t * 0.55 + 0.5, 1.0)
        brace_w = panel_w * 0.20
        brace_x = band_x + banner_race * (band_w - brace_w)
        self._draw_rect(brace_x, effect_y, brace_w, effect_h, (1.0, 1.0, 1.0, 0.03 + pulse_fast * 0.03))
        self._draw_rect(x, effect_y, 6.0, effect_h, (1.0, 0.62, 0.20, 0.76 + pulse_med * 0.20))
        self._draw_rect(x + panel_w - 6.0, effect_y, 6.0, effect_h, (1.0, 0.62, 0.20, 0.56 + pulse_slow * 0.22))
        effect_a = 0.88 + (1.0 - pulse_slow) * 0.12
        self._draw_text(
            f"EFFECT: {self._hud_state.get('effect', '-')}",
            x + 20.0,
            effect_y + 8.0,
            scale=3.0,
            color=(0.12, 1.0, 1.0, effect_a),
        )
        self._draw_text(
            f"TRANSITION: {self._hud_state.get('transition', '-')} ({self._hud_state.get('transition_t', '0%')})",
            x + 20.0,
            effect_y + 44.0,
            scale=2.3,
            color=(1.0, 0.66 + pulse_fast * 0.12, 0.24, 0.94),
        )

        if spotify_visible:
            # Spotify pane sits above the effect banner to avoid overlap.
            self._draw_rect(band_x, spotify_y, band_w, spotify_h, (0.02, 0.14, 0.10, 0.84))
            self._draw_rect(band_x, spotify_y, band_w, 2.0, (accent[0], accent[1], accent[2], 0.62 + pulse_med * 0.20))
            self._draw_rect(band_x, spotify_y + spotify_h - 2.0, band_w, 2.0, (accent[0], accent[1], accent[2], 0.46 + pulse_slow * 0.16))
            self._draw_rect(band_x, spotify_y, 4.0, spotify_h, (accent[0], accent[1], accent[2], 0.78))

            spotify_phase = t * 0.85
            spotify_a = 0.88 + (1.0 - pulse_slow) * 0.12
            if status_l == 'paused':
                line_rgb = (
                    0.90 + 0.06 * math.sin(spotify_phase + 0.6),
                    0.72 + 0.08 * math.sin(spotify_phase + 2.0),
                    1.00,
                )
            elif status_l == 'playing':
                line_rgb = (
                    0.86 + 0.08 * math.sin(spotify_phase + 0.15),
                    1.00,
                    0.90 + 0.06 * math.sin(spotify_phase + 2.7),
                )
            else:
                line_rgb = (
                    0.84,
                    0.98,
                    1.00,
                )

            char_w_spotify = float(self._glyph_w) * self._font_scale_norm * 2.2
            center_line = f'{spotify_artist} | {spotify_track} | {spotify_progress}'
            text_w = len(center_line) * char_w_spotify
            center_x = band_x + max(8.0, (band_w - text_w) * 0.5)
            self._draw_text(center_line, center_x, spotify_y + 14.0, scale=2.2, color=(line_rgb[0], line_rgb[1], line_rgb[2], spotify_a))

            pct = 0.0
            if '%' in spotify_progress:
                try:
                    pct = float(spotify_progress.rsplit(' ', 1)[-1].replace('%', '').strip())
                except Exception:
                    pct = 0.0
            pct = max(0.0, min(100.0, pct))

            rail_pad = 12.0
            rail_x = band_x + rail_pad
            rail_y = spotify_y + 40.0
            rail_w = band_w - rail_pad * 2.0
            rail_h = 26.0
            rail_center_y = rail_y + rail_h * 0.5

            # Waveform mode: live PCM waveform fed by app.py each frame.
            # Gate: auto-vj must have live BPM and a waveform must be available.
            _wf_bpm = _fv('auto_vj_bpm')
            wf = self._live_waveform
            waveform_mode = (
                _wf_bpm > 0.0
                and wf is not None
                and len(wf) > 0
            )

            if waveform_mode:
                _beat = _fv('audio_beat')
                # Leaky-peak beat glow: snaps up on beat, decays between frames.
                self._spotify_beat_decay = max(
                    self._spotify_beat_decay * 0.80,
                    min(1.0, _beat * 1.5),
                )
                beat_g = self._spotify_beat_decay

                _N = 128
                col_w = rail_w / _N
                fill_col = min(_N - 1, int(pct / 100.0 * _N))
                wf_len = len(wf)

                # Dim full-rail background + thin center guide line so the
                # unplayed portion is visible as a faint track-length marker.
                self._draw_rect(rail_x, rail_y, rail_w, rail_h, (0.05, 0.10, 0.08, 0.55))
                self._draw_rect(rail_x, rail_center_y - 0.5, rail_w, 1.0, (0.22, 0.42, 0.30, 0.55))

                # Waveform bars for the played portion.
                # Each column samples the current live waveform at a proportional
                # index; the whole waveform is always visible, growing rightward.
                for _ci in range(fill_col + 1):
                    _wi = int(_ci / max(1, fill_col) * (wf_len - 1))
                    _sample = abs(float(wf[_wi]))  # already peak-normalised to [0, 1]
                    _bar_h = max(2.0, _sample * rail_h * 0.92)
                    _bar_y = rail_center_y - _bar_h * 0.5
                    _cx = rail_x + _ci * col_w
                    # Uniform brightness from amplitude + beat — no hue shift,
                    # so the accent color never drifts yellow.
                    _bright = 0.45 + _sample * 0.55 + beat_g * 0.12
                    _r = min(1.0, accent[0] * _bright)
                    _g = min(1.0, accent[1] * _bright)
                    _b = min(1.0, accent[2] * _bright)
                    _a = 0.80 + beat_g * 0.15
                    self._draw_rect(_cx, _bar_y, max(1.0, col_w - 0.4), _bar_h, (_r, _g, _b, _a))
            else:
                fill_w = rail_w * (pct / 100.0)
                self._draw_rect(rail_x, rail_y, rail_w, rail_h, (0.12, 0.24, 0.22, 0.85))
                self._draw_rect(rail_x, rail_y, fill_w, rail_h, (accent[0], accent[1], accent[2], 0.95))

        # ── layer 7: data zone separator ─────────────────────────────────
        self._draw_rect(x, data_zone_y - 4.0, panel_w, 1.0, (0.10, 0.94, 1.0, 0.24))
        self._draw_rect(x, data_zone_y - 2.0, panel_w, 2.0, (0.10, 0.94, 1.0, 0.44 + pulse_med * 0.16))
        # Mid-panel vertical divider
        mid_div_x = x + panel_w * 0.50
        self._draw_rect(mid_div_x - 1.0, data_zone_y, 1.0, data_zone_h, (0.10, 0.94, 1.0, 0.16))
        self._draw_rect(mid_div_x,        data_zone_y, 1.0, data_zone_h, (0.10, 0.94, 1.0, 0.32))

        # ── layer 8: vertical scan line ──────────────────────────────────
        # A bright thin bar that travels top→bottom through the data zone
        scan_y = data_zone_y + scan_h * data_zone_h
        self._draw_rect(x + 8.0, scan_y - 1.0, panel_w - 16.0, 2.0, (0.10, 0.94, 1.0, 0.06))
        self._draw_rect(x + 8.0, scan_y,        panel_w - 16.0, 1.0, (0.10, 0.94, 1.0, 0.18))

        # ── layer 9: data rows ───────────────────────────────────────────
        left_x   = x + 22.0
        right_x  = x + panel_w * 0.52
        row0     = y + row0_offset
        col_half = panel_w * 0.46

        # Left column accent stripe — runs full data zone height so it matches right column
        stripe_h = max(len(left_lines), len(right_lines)) * lh + 8.0
        stripe_a = 0.44 + pulse_med * 0.18 + bass * 0.18
        self._draw_rect(x + 6.0, row0 - 4.0, 3.0, stripe_h, (0.10, 0.96, 1.0, stripe_a))
        # Inner glow strip next to stripe
        self._draw_rect(x + 10.0, row0 - 4.0, 2.0, stripe_h, (0.10, 0.96, 1.0, stripe_a * 0.35))

        for i, ln in enumerate(left_lines):
            row_y = row0 + i * lh
            if i % 2 == 0:
                self._draw_rect(left_x - 8.0, row_y - 2.0, col_half, lh + 2.0, (0.06, 0.10, 0.16, 0.35))
            self._draw_text(ln, left_x, row_y, scale=2.05, color=(0.84, 0.98, 1.0, 0.96))

        # Right column accent stripe — orange, mid-reactive
        rstripe_a = 0.48 + pulse_slow * 0.16 + mid * 0.18
        self._draw_rect(x + panel_w - 9.0, row0 - 4.0, 3.0, len(right_lines) * lh + 8.0, (1.0, 0.62, 0.20, rstripe_a))
        self._draw_rect(x + panel_w - 12.0, row0 - 4.0, 2.0, len(right_lines) * lh + 8.0, (1.0, 0.62, 0.20, rstripe_a * 0.35))

        for i, ln in enumerate(right_lines):
            row_y = row0 + i * lh
            if i % 2 == 1:
                self._draw_rect(right_x - 8.0, row_y - 2.0, col_half, lh + 2.0, (0.16, 0.08, 0.04, 0.35))
            self._draw_text(ln, right_x, row_y, scale=2.05, color=(0.98, 0.68, 0.22, 0.96))

        # ── layer 9.5: fixed bottom Auto VJ status section ─────────────
        status_box_x = x + 8.0
        status_box_w = panel_w - 16.0
        status_box_h = 54.0
        status_box_y = y + panel_h - 76.0
        self._draw_rect(status_box_x, status_box_y, status_box_w, status_box_h, (0.03, 0.08, 0.14, 0.84))
        self._draw_rect(status_box_x, status_box_y, status_box_w, 2.0, (0.10, 0.94, 1.0, 0.40 + pulse_med * 0.14))
        self._draw_rect(status_box_x, status_box_y + status_box_h - 2.0, status_box_w, 2.0, (0.10, 0.94, 1.0, 0.28 + pulse_slow * 0.12))
        self._draw_rect(status_box_x, status_box_y, 2.0, status_box_h, (0.10, 0.94, 1.0, 0.20 + pulse_slow * 0.10))
        self._draw_rect(status_box_x + status_box_w - 2.0, status_box_y, 2.0, status_box_h, (0.10, 0.94, 1.0, 0.20 + pulse_slow * 0.10))

        mood = str(self._hud_state.get('auto_vj_mood', '-')).upper()
        scene = str(self._hud_state.get('auto_vj_scene', '-')).upper()
        genre = str(self._hud_state.get('audio_profile_name', '-'))
        if len(genre) > 18:
            genre = genre[:15] + '...'
        bpm = str(self._hud_state.get('auto_vj_bpm', '--'))
        action_in = str(self._hud_state.get('auto_vj_action_in', '--'))

        line1 = f'{auto_vj_label} | MOOD: {mood:<8} | SCENE: {scene:<10} | GENRE: {genre:<18}'
        line2 = f'BPM: {bpm:>3} | ACTION IN: {action_in:<4}'
        char_w = float(self._glyph_w) * self._font_scale_norm * 1.9
        line1_w = len(line1) * char_w
        line2_w = len(line2) * char_w
        block_w = max(line1_w, line2_w)
        block_x = status_box_x + (status_box_w - block_w) * 0.5
        line1_x = block_x + (block_w - line1_w) * 0.5
        line2_x = block_x + (block_w - line2_w) * 0.5
        # Subtle Unicorn Tears-inspired color drift for the top status line.
        tears_phase = t * 0.55
        tears_r = 0.82 + 0.10 * math.sin(tears_phase + 0.10)
        tears_g = 0.93 + 0.05 * math.sin(tears_phase + 2.05)
        tears_b = 0.90 + 0.10 * math.sin(tears_phase + 4.15)
        self._draw_text(
            line1,
            line1_x,
            status_box_y + 7.0,
            scale=1.9,
            color=(tears_r, tears_g, tears_b, 0.96),
        )
        self._draw_text(line2, line2_x, status_box_y + 30.0, scale=1.9, color=(1.0, 0.68, 0.22, 0.96))

        # ── layer 10: LCARS tick marks (right edge decoration) ───────────
        # Three evenly spaced horizontal tick marks on the right border
        tick_x = x + panel_w - 24.0
        tick_positions = [0.25, 0.5, 0.75]
        tick_colors = [
            (0.10, 0.94, 1.0, 0.52 + pulse_slow * 0.24),
            (1.00, 0.62, 0.20, 0.52 + pulse_med  * 0.24),
            (0.78, 0.38, 1.00, 0.52 + pulse_fast * 0.24),
        ]
        for tp, tc in zip(tick_positions, tick_colors):
            ty = y + tp * panel_h
            self._draw_rect(tick_x,        ty - 1.0, 18.0, 1.0, (tc[0], tc[1], tc[2], tc[3] * 0.4))
            self._draw_rect(tick_x,        ty,        18.0, 3.0, tc)
            self._draw_rect(tick_x,        ty + 3.0, 18.0, 1.0, (tc[0], tc[1], tc[2], tc[3] * 0.4))
        # Mirror on the left edge
        ltick_x = x + 6.0
        for tp, tc in zip(tick_positions, tick_colors):
            ty = y + tp * panel_h
            self._draw_rect(ltick_x, ty - 1.0, 18.0, 1.0, (tc[0], tc[1], tc[2], tc[3] * 0.4))
            self._draw_rect(ltick_x, ty,        18.0, 3.0, tc)
            self._draw_rect(ltick_x, ty + 3.0, 18.0, 1.0, (tc[0], tc[1], tc[2], tc[3] * 0.4))

        # ── layer 11: bottom accent bar — segmented blocks ───────────────
        seg_n   = 12
        seg_gap = 4.0
        seg_w   = (panel_w - (seg_n - 1) * seg_gap) / seg_n
        for s in range(seg_n):
            phase = math.sin(t * 1.8 + s * 0.52)
            seg_a = 0.30 + 0.24 * (0.5 + 0.5 * phase)
            sx = x + s * (seg_w + seg_gap)
            self._draw_rect(sx, y + panel_h - 8.0, seg_w, 8.0, (0.12, 0.96, 1.0, seg_a))
        # Solid thin line above segments
        self._draw_rect(x, y + panel_h - 10.0, panel_w, 2.0, (0.10, 0.94, 1.0, 0.44 + pulse_med * 0.18))

    def render(self, dt: float, include_recording_indicator: bool = True) -> None:
        """Call each frame after the main effect renders."""
        self._hud_t += dt
        if self._show_name and self._hud_auto_hide:
            self._hud_timer -= dt
            if self._hud_timer <= 0.0:
                self._show_name = False
                self._hud_timer = 0.0
        if self._show_help:
            self._help_timer -= dt
            if self._help_timer <= 0.0:
                self._show_help = False
                self._help_timer = 0.0
            self._help_pulse_t += dt

        if self._flash_timer > 0.0:
            self._flash_timer -= dt
            alpha = min(1.0, self._flash_timer * 2.0)
            self._draw_text(
                self._flash_text,
                20, self._height - 80,
                scale=4.0,
                color=(1.0, 0.8, 0.0, alpha),
            )

        route_modals_elsewhere = False
        gate = self._modal_gate
        if callable(gate):
            try:
                route_modals_elsewhere = bool(gate())
            except Exception:
                route_modals_elsewhere = False

        if self._show_name and self._name_text and not route_modals_elsewhere:
            self._render_hud()

        if self._banner_timer > 0.0:
            self._banner_timer = max(0.0, self._banner_timer - dt)
        if self._banner_enabled and self._banner_timer > 0.0 and not route_modals_elsewhere:
            self._render_banner()

        if include_recording_indicator:
            self._render_recording_indicator()

        if self._cta.is_active:
            self._cta.render(dt, self._ctx, self._draw_rect, self._width, self._height)

        if self._show_help and not route_modals_elsewhere:
            self._render_help()

        active_modal_type = ''
        if self._show_projectm_manager:
            active_modal_type = 'projectm_manager'
        elif self._show_system_monitor_modal:
            active_modal_type = 'system_monitor'
        elif self._show_controller_help_modal:
            active_modal_type = 'controller_help'
        elif self._show_webcam_editor_modal:
            active_modal_type = 'webcam_editor'
        elif self._show_audio:
            active_modal_type = 'audio_selector'
        elif self._show_midi:
            active_modal_type = 'midi_selector'
        elif self._show_help:
            active_modal_type = 'help_overlay'
        elif self._show_name:
            active_modal_type = 'hud_overlay'

        route_state = (route_modals_elsewhere, active_modal_type)
        if route_state != self._modal_route_debug_last:
            if active_modal_type:
                destination = 'control_room' if route_modals_elsewhere else 'audience_overlay'
                log.debug(
                    'Overlay modal route: type=%s destination=%s gate=%s',
                    active_modal_type,
                    destination,
                    route_modals_elsewhere,
                )
            self._modal_route_debug_last = route_state

        if self._show_projectm_manager and not route_modals_elsewhere:
            self._render_projectm_manager()

        if self._show_system_monitor_modal and not route_modals_elsewhere:
            self._render_system_monitor_modal()

        if self._show_controller_help_modal and not route_modals_elsewhere:
            self._render_controller_help_modal()

        if self._show_webcam_editor_modal and not route_modals_elsewhere:
            self._render_webcam_editor_modal()

        if self._show_audio and not route_modals_elsewhere:
            self._render_audio_selector()

        if self._show_midi and not route_modals_elsewhere:
            self._render_midi_selector()

    # ------------------------------------------------------------------
    # Audio source selector
    # ------------------------------------------------------------------

    def set_audio_sources(
        self,
        sources: list[str],
        current_index: int,
        viable_flags: list[bool] | None = None,
    ) -> None:
        """Populate the audio selector source list before opening the overlay."""
        self._audio_sources = list(sources)
        if viable_flags is None or len(viable_flags) != len(self._audio_sources):
            self._audio_viable_flags = [True] * len(self._audio_sources)
        else:
            self._audio_viable_flags = [bool(v) for v in viable_flags]
        total = max(1, len(self._audio_sources))
        idx = max(0, min(int(current_index), total - 1))
        self._audio_current_idx = idx
        self._audio_selected_idx = idx

    def toggle_audio_selected_viable(self) -> bool:
        """Toggle viability tag for the currently selected audio source."""
        if not self._audio_sources:
            return False
        idx = self.get_audio_selected_index()
        if idx >= len(self._audio_viable_flags):
            self._audio_viable_flags = [True] * len(self._audio_sources)
        self._audio_viable_flags[idx] = not bool(self._audio_viable_flags[idx])
        return bool(self._audio_viable_flags[idx])

    def move_audio_selection(self, delta: int) -> None:
        """Move the audio selector cursor by delta rows (wraps)."""
        total = max(1, len(self._audio_sources))
        self._audio_selected_idx = (self._audio_selected_idx + delta) % total

    def get_audio_selected_index(self) -> int:
        """Return the source index currently highlighted in selector."""
        if not self._audio_sources:
            return 0
        return max(0, min(self._audio_selected_idx, len(self._audio_sources) - 1))

    def set_audio_selected_index(self, index: int) -> int:
        """Set highlighted audio source row; returns clamped index."""
        if not self._audio_sources:
            self._audio_selected_idx = 0
            return 0
        clamped = max(0, min(int(index), len(self._audio_sources) - 1))
        self._audio_selected_idx = clamped
        return clamped

    def _render_audio_selector(self) -> None:
        """Draw the audio source selector modal."""
        t = self._hud_t
        pulse = 0.55 + 0.45 * math.sin(t * 2.8)

        W = float(self._width)
        H = float(self._height)
        row_h = 38.0
        n_rows = max(1, len(self._audio_sources))
        panel_w = min(W * 0.62, 860.0)
        panel_h = 80.0 + n_rows * row_h + 56.0
        px = (W - panel_w) * 0.5
        py = (H - panel_h) * 0.5

        self._draw_modal_underlay(px, py, panel_w, panel_h, alpha=0.55, pad=8.0)

        self._draw_rect(px, py, panel_w, panel_h, (0.04, 0.05, 0.12, 0.96))
        bw = 2.0
        c_border = (0.18 * pulse, 0.55 * pulse, 1.0 * pulse, 0.9)
        self._draw_rect(px, py, panel_w, bw, c_border)
        self._draw_rect(px, py + panel_h - bw, panel_w, bw, c_border)
        self._draw_rect(px, py, bw, panel_h, c_border)
        self._draw_rect(px + panel_w - bw, py, bw, panel_h, c_border)
        bass = float(self._hud_state.get('bass', '0.0') or 0.0)
        mid = float(self._hud_state.get('mid', '0.0') or 0.0)
        treble = float(self._hud_state.get('treble', '0.0') or 0.0)
        self._draw_audio_reactive_border_bulbs(px, py, panel_w, panel_h, bass, mid, treble, t, speed_scale=0.5, size_scale=0.5)


        self._draw_text('AUDIO SOURCE SELECT', px + 18, py + 14, scale=3.5,
                        color=(0.3 + 0.2 * pulse, 0.75, 1.0, 1.0))

        active_name = 'none'
        if self._audio_sources and 0 <= self._audio_current_idx < len(self._audio_sources):
            active_name = self._audio_sources[self._audio_current_idx]
        self._draw_text(f'Active: {active_name}', px + 18, py + 48, scale=2.2,
                        color=(0.5, 0.8, 0.5, 0.85))

        entries = self._audio_sources if self._audio_sources else ['(no sources available)']
        for i, name in enumerate(entries):
            ry = py + 80.0 + i * row_h
            is_sel = i == self._audio_selected_idx
            is_active = i == self._audio_current_idx
            is_viable = True
            if i < len(self._audio_viable_flags):
                is_viable = bool(self._audio_viable_flags[i])
            tag = '[V]' if is_viable else '[ ]'

            if is_sel:
                self._draw_rect(px + 8, ry - 2, panel_w - 16, row_h - 4,
                                (0.10, 0.25, 0.55, 0.85))
                self._draw_text(f'> {tag} {name}', px + 22, ry + 5, scale=2.8,
                                color=(1.0, 0.92, 0.2, 1.0))
            else:
                label_color = (0.3, 0.9, 0.3, 0.9) if is_active else (0.7, 0.8, 1.0, 0.75)
                self._draw_text(f'  {tag} {name}', px + 22, ry + 5, scale=2.8,
                                color=label_color)

        fy = py + panel_h - 40.0
        self._draw_text('Up/Down: navigate    T: toggle viable    Enter: apply    Esc: cancel',
                        px + 18, fy, scale=2.0, color=(0.55, 0.65, 0.75, 0.80))

    # ------------------------------------------------------------------
    # MIDI device selector
    # ------------------------------------------------------------------

    def set_midi_ports(self, ports: list[str], current_port: str) -> None:
        """Populate the MIDI selector port list before opening the overlay."""
        self._midi_ports = list(ports)
        self._midi_current_port = current_port
        # Pre-select the currently active port (offset +1 because index 0 = None)
        self._midi_selected_idx = 0
        for i, p in enumerate(self._midi_ports):
            if p == current_port:
                self._midi_selected_idx = i + 1
                break

    def move_midi_selection(self, delta: int) -> None:
        """Move the MIDI selector cursor by delta rows (wraps)."""
        total = len(self._midi_ports) + 1   # +1 for the "None" entry
        self._midi_selected_idx = (self._midi_selected_idx + delta) % total

    def get_midi_selected_port(self) -> str:
        """Return the port name currently highlighted ('' = None / disable)."""
        if self._midi_selected_idx == 0:
            return ''
        idx = self._midi_selected_idx - 1
        if idx < len(self._midi_ports):
            return self._midi_ports[idx]
        return ''

    def get_midi_selected_index(self) -> int:
        """Return highlighted MIDI selector row index."""
        total = len(self._midi_ports) + 1
        return max(0, min(self._midi_selected_idx, max(0, total - 1)))

    def set_midi_selected_index(self, index: int) -> int:
        """Set highlighted MIDI row; returns clamped index."""
        total = len(self._midi_ports) + 1
        if total <= 0:
            self._midi_selected_idx = 0
            return 0
        clamped = max(0, min(int(index), total - 1))
        self._midi_selected_idx = clamped
        return clamped

    def _render_midi_selector(self) -> None:
        """Draw the MIDI device selector modal."""
        t = self._hud_t
        pulse = 0.55 + 0.45 * math.sin(t * 2.8)

        W = float(self._width)
        H = float(self._height)
        row_h = 38.0
        n_rows = len(self._midi_ports) + 1   # +1 for None entry
        panel_w = min(W * 0.62, 780.0)
        panel_h = 80.0 + n_rows * row_h + 56.0
        px = (W - panel_w) * 0.5
        py = (H - panel_h) * 0.5

        self._draw_modal_underlay(px, py, panel_w, panel_h, alpha=0.55, pad=8.0)

        # Panel background
        self._draw_rect(px, py, panel_w, panel_h, (0.04, 0.05, 0.12, 0.96))
        # Neon border
        bw = 2.0
        c_border = (0.18 * pulse, 0.55 * pulse, 1.0 * pulse, 0.9)
        self._draw_rect(px,               py,               panel_w, bw,       c_border)
        self._draw_rect(px,               py + panel_h - bw, panel_w, bw,     c_border)
        self._draw_rect(px,               py,               bw,       panel_h, c_border)
        self._draw_rect(px + panel_w - bw, py,              bw,       panel_h, c_border)

        bass = float(self._hud_state.get('bass', '0.0') or 0.0)
        mid = float(self._hud_state.get('mid', '0.0') or 0.0)
        treble = float(self._hud_state.get('treble', '0.0') or 0.0)
        self._draw_audio_reactive_border_bulbs(px, py, panel_w, panel_h, bass, mid, treble, t, speed_scale=0.5, size_scale=0.5)

        # Title
        self._draw_text('MIDI DEVICE SELECT', px + 18, py + 14, scale=3.5,
                        color=(0.3 + 0.2 * pulse, 0.75, 1.0, 1.0))

        # Current device status line
        status = f'Active: {self._midi_current_port}' if self._midi_current_port else 'Active: none'
        self._draw_text(status, px + 18, py + 48, scale=2.2,
                        color=(0.5, 0.8, 0.5, 0.85))

        # Port rows
        entries = ['(none — disable MIDI)'] + self._midi_ports
        for i, name in enumerate(entries):
            ry = py + 80.0 + i * row_h
            is_sel = i == self._midi_selected_idx
            is_active = (i == 0 and not self._midi_current_port) or (
                i > 0 and self._midi_ports[i - 1] == self._midi_current_port
            )

            if is_sel:
                self._draw_rect(px + 8, ry - 2, panel_w - 16, row_h - 4,
                                (0.10, 0.25, 0.55, 0.85))
                self._draw_text(f'> {name}', px + 22, ry + 5, scale=2.8,
                                color=(1.0, 0.92, 0.2, 1.0))
            else:
                label_color = (0.3, 0.9, 0.3, 0.9) if is_active else (0.7, 0.8, 1.0, 0.75)
                self._draw_text(f'  {name}', px + 22, ry + 5, scale=2.8,
                                color=label_color)

        # Instructions footer
        fy = py + panel_h - 40.0
        self._draw_text('Up/Down: navigate    Enter: apply    Esc: cancel',
                        px + 18, fy, scale=2.0, color=(0.55, 0.65, 0.75, 0.80))

    # ------------------------------------------------------------------
    # Webcam editor modal
    # ------------------------------------------------------------------

    def set_webcam_editor_data(
        self,
        devices: list[dict[str, object]],
        image_state: dict[str, object],
    ) -> None:
        """Populate webcam editor modal data before opening/rendering."""
        self._webcam_editor_devices = list(devices)
        if self._webcam_editor_devices:
            selected = next(
                (i for i, dev in enumerate(self._webcam_editor_devices) if bool(dev.get('selected', False))),
                self._webcam_editor_selected_idx,
            )
            self._webcam_editor_selected_idx = max(0, min(selected, len(self._webcam_editor_devices) - 1))
        else:
            self._webcam_editor_selected_idx = 0
        merged = dict(self._webcam_editor_state)
        merged.update(dict(image_state or {}))
        self._webcam_editor_state = merged

    def move_webcam_editor_selection(self, delta: int) -> None:
        """Move webcam editor camera selection cursor by delta rows (wraps)."""
        total = len(self._webcam_editor_devices)
        if total <= 0:
            self._webcam_editor_selected_idx = 0
            return
        self._webcam_editor_selected_idx = (self._webcam_editor_selected_idx + int(delta)) % total

    def get_webcam_editor_selected_camera_id(self) -> int | None:
        """Return camera id currently highlighted in webcam editor modal."""
        if not self._webcam_editor_devices:
            return None
        idx = max(0, min(self._webcam_editor_selected_idx, len(self._webcam_editor_devices) - 1))
        try:
            return int(self._webcam_editor_devices[idx].get('id'))
        except Exception:
            return None

    def _render_webcam_editor_modal(self) -> None:
        """Draw webcam editor modal for device/image controls."""
        t = self._hud_t
        pulse = 0.55 + 0.45 * math.sin(t * 2.6)

        px, py, panel_w, panel_h, W, H = self._begin_panel(0.72, 980.0, 0.80, 760.0, underlay_alpha=0.58, underlay_pad=10.0)

        self._draw_rect(px, py, panel_w, panel_h, (0.04, 0.05, 0.12, 0.96))
        bw = 2.0
        c_border = (0.18 * pulse, 0.55 * pulse, 1.0 * pulse, 0.9)
        self._draw_rect(px, py, panel_w, bw, c_border)
        self._draw_rect(px, py + panel_h - bw, panel_w, bw, c_border)
        self._draw_rect(px, py, bw, panel_h, c_border)
        self._draw_rect(px + panel_w - bw, py, bw, panel_h, c_border)
        bass = float(self._hud_state.get('bass', '0.0') or 0.0)
        mid = float(self._hud_state.get('mid', '0.0') or 0.0)
        treble = float(self._hud_state.get('treble', '0.0') or 0.0)
        self._draw_audio_reactive_border_bulbs(px, py, panel_w, panel_h, bass, mid, treble, t, speed_scale=0.5, size_scale=0.5)


        self._draw_text('WEBCAM EDITOR', px + 18, py + 14, scale=3.5,
                        color=(0.3 + 0.2 * pulse, 0.75, 1.0, 1.0))

        s = self._webcam_editor_state
        b = float(s.get('brightness', 1.0) or 1.0)
        c = float(s.get('contrast', 1.0) or 1.0)
        fh = bool(s.get('flip_horizontal', False))
        fv = bool(s.get('flip_vertical', False))
        switching = bool(s.get('switching', False))
        rem = float(s.get('switch_hide_remaining_s', 0.0) or 0.0)

        self._draw_text(f'Brightness: {b:.2f}    Contrast: {c:.2f}', px + 18, py + 52, scale=2.2,
                        color=(0.55, 0.85, 0.62, 0.90))
        self._draw_text(f'Flip H: {"ON" if fh else "OFF"}    Flip V: {"ON" if fv else "OFF"}', px + 18, py + 76, scale=2.2,
                        color=(0.70, 0.84, 1.0, 0.90))
        if switching:
            self._draw_text(f'SWITCHING... {rem:.1f}s', px + panel_w - 240, py + 76, scale=2.1,
                            color=(1.0, 0.75, 0.22, 0.96))

        row_h = 34.0
        list_top = py + 110.0
        entries = self._webcam_editor_devices if self._webcam_editor_devices else [
            {'id': -1, 'label': '(no cameras detected)', 'enabled': False, 'selected': False},
        ]

        for i, entry in enumerate(entries[:12]):
            ry = list_top + i * row_h
            is_sel = i == self._webcam_editor_selected_idx
            is_enabled = bool(entry.get('enabled', False))
            is_active = bool(entry.get('selected', False))
            cam_id = int(entry.get('id', -1))
            label = str(entry.get('label', cam_id))
            state_tag = 'ON' if is_enabled else 'OFF'
            active_tag = '*' if is_active else ' '
            text = f'{active_tag} {label:<12} [{state_tag}]'

            if is_sel:
                self._draw_rect(px + 12, ry - 1, panel_w - 24, row_h - 4,
                                (0.10, 0.25, 0.55, 0.85))
                self._draw_text(f'> {text}', px + 24, ry + 4, scale=2.5,
                                color=(1.0, 0.92, 0.2, 1.0))
            else:
                col = (0.40, 0.92, 0.44, 0.90) if is_enabled else (0.98, 0.48, 0.48, 0.88)
                self._draw_text(f'  {text}', px + 24, ry + 4, scale=2.5,
                                color=col)

        fy = py + panel_h - 64.0
        self._draw_text('Up/Down: select camera   Enter: switch camera   E: enable/disable',
                        px + 18, fy, scale=2.0, color=(0.55, 0.65, 0.75, 0.85))
        self._draw_text('R: rediscover   [/]: brightness -/+   ;/\': contrast -/+   H/V: flip H/V   Esc/Ctrl+Alt+K: close',
                        px + 18, fy + 22, scale=2.0, color=(0.55, 0.65, 0.75, 0.85))

    def set_projectm_manager_entries(
        self,
        entries: list[dict[str, object]],
        current_path: str,
    ) -> None:
        """Populate the projectM manager browser with catalog entries."""
        self._projectm_entries = list(entries)
        self._projectm_current_path = str(current_path or '')
        categories = {'(all)'}
        for entry in self._projectm_entries:
            category_key = str(entry.get('category_key', '') or '(uncategorized)')
            categories.add(category_key)
        ordered = ['(all)'] + sorted(
            (cat for cat in categories if cat != '(all)'),
            key=lambda text: text.lower(),
        )
        self._projectm_categories = ordered
        self._projectm_category_idx = max(0, min(self._projectm_category_idx, len(self._projectm_categories) - 1))
        self._sync_projectm_preset_selection()

    def _projectm_filtered_entries(self) -> list[dict[str, object]]:
        category = self.get_projectm_selected_category()
        query = self._projectm_search_query.strip().lower()

        def _category_ok(entry: dict[str, object]) -> bool:
            if category == '(all)':
                return True
            return str(entry.get('category_key', '')) == category

        def _query_ok(entry: dict[str, object]) -> bool:
            if not query:
                return True
            haystack = ' '.join(
                [
                    str(entry.get('display_name', '')),
                    str(entry.get('pack_name', '')),
                    str(entry.get('category_key', '')),
                    ' '.join(str(t) for t in (entry.get('tags', []) or [])),
                ]
            ).lower()
            return query in haystack

        return [
            entry for entry in self._projectm_entries
            if _category_ok(entry) and _query_ok(entry)
        ]

    def set_projectm_search_query(self, query: str) -> None:
        """Set the ProjectM manager text filter and keep selection coherent."""
        self._projectm_search_query = str(query)
        self._sync_projectm_preset_selection()

    def clear_projectm_search_query(self) -> None:
        """Clear the ProjectM manager text filter."""
        self.set_projectm_search_query('')

    @property
    def projectm_search_query(self) -> str:
        """Return current ProjectM manager text filter."""
        return self._projectm_search_query

    def _projectm_category_stats(self, category: str) -> tuple[int, int]:
        entries = self._projectm_entries if category == '(all)' else [
            entry for entry in self._projectm_entries
            if str(entry.get('category_key', '')) == category
        ]
        total = len(entries)
        enabled = sum(1 for entry in entries if bool(entry.get('enabled', False)))
        return enabled, total

    def _sync_projectm_preset_selection(self) -> None:
        entries = self._projectm_filtered_entries()
        if not entries:
            self._projectm_preset_idx = 0
            return
        for idx, entry in enumerate(entries):
            if str(entry.get('path', '')) == self._projectm_current_path:
                self._projectm_preset_idx = idx
                return
        self._projectm_preset_idx = max(0, min(self._projectm_preset_idx, len(entries) - 1))

    def move_projectm_category_selection(self, delta: int) -> None:
        """Move the projectM category cursor by delta rows (wraps)."""
        total = max(1, len(self._projectm_categories))
        self._projectm_category_idx = (self._projectm_category_idx + delta) % total
        self._sync_projectm_preset_selection()

    def move_projectm_preset_selection(self, delta: int) -> None:
        """Move the projectM preset cursor by delta rows (wraps)."""
        entries = self._projectm_filtered_entries()
        total = max(1, len(entries))
        self._projectm_preset_idx = (self._projectm_preset_idx + delta) % total

    def move_projectm_focus(self, delta: int) -> None:
        """Switch projectM manager focus between category and preset panes."""
        self._projectm_focus_pane = (self._projectm_focus_pane + delta) % 2

    def set_projectm_focus_pane(self, pane: int) -> int:
        """Set active ProjectM manager pane (0=category, 1=preset)."""
        self._projectm_focus_pane = 1 if int(pane) > 0 else 0
        return self._projectm_focus_pane

    def set_projectm_category_index(self, index: int) -> int:
        """Set ProjectM category selection index and sync dependent preset index."""
        total = max(1, len(self._projectm_categories))
        self._projectm_category_idx = max(0, min(int(index), total - 1))
        self._sync_projectm_preset_selection()
        return self._projectm_category_idx

    def get_projectm_category_index(self) -> int:
        """Return current ProjectM category selection index."""
        total = max(1, len(self._projectm_categories))
        return max(0, min(self._projectm_category_idx, total - 1))

    def set_projectm_preset_index(self, index: int) -> int:
        """Set ProjectM preset selection index for current category/search filter."""
        entries = self._projectm_filtered_entries()
        total = max(1, len(entries))
        self._projectm_preset_idx = max(0, min(int(index), total - 1))
        return self._projectm_preset_idx

    def get_projectm_preset_index(self) -> int:
        """Return current ProjectM preset selection index."""
        entries = self._projectm_filtered_entries()
        total = max(1, len(entries))
        return max(0, min(self._projectm_preset_idx, total - 1))

    def projectm_categories(self) -> list[str]:
        """Return ProjectM category labels in current manager ordering."""
        return list(self._projectm_categories)

    def projectm_filtered_presets(self) -> list[dict[str, object]]:
        """Return filtered ProjectM preset rows for current category/search state."""
        return list(self._projectm_filtered_entries())

    def get_projectm_selected_category(self) -> str:
        """Return the currently highlighted category key."""
        if not self._projectm_categories:
            return '(all)'
        idx = max(0, min(self._projectm_category_idx, len(self._projectm_categories) - 1))
        return self._projectm_categories[idx]

    def get_projectm_selected_preset(self) -> dict[str, object] | None:
        """Return the currently highlighted preset entry for the active filter."""
        entries = self._projectm_filtered_entries()
        if not entries:
            return None
        idx = max(0, min(self._projectm_preset_idx, len(entries) - 1))
        return entries[idx]

    def _render_projectm_manager(self) -> None:
        """Draw the projectM preset manager modal."""
        t = self._hud_t
        pulse = 0.55 + 0.45 * math.sin(t * 2.4)

        W = float(self._width)
        H = float(self._height)
        panel_w = min(W * 0.90, 1320.0)
        panel_h = min(H * 0.86, 860.0)
        px = (W - panel_w) * 0.5
        py = (H - panel_h) * 0.5
        left_w = max(260.0, panel_w * 0.28)
        right_w = panel_w - left_w - 28.0
        left_x = px + 14.0
        right_x = left_x + left_w + 14.0
        content_y = py + 86.0
        content_h = panel_h - 164.0
        footer_y = py + panel_h - 56.0

        self._draw_rect(px, py, panel_w, panel_h, (0.03, 0.04, 0.10, 0.96))
        border = (0.18 * pulse, 0.55 * pulse, 1.0 * pulse, 0.92)
        bw = 2.0
        self._draw_rect(px, py, panel_w, bw, border)
        self._draw_rect(px, py + panel_h - bw, panel_w, bw, border)
        self._draw_rect(px, py, bw, panel_h, border)
        self._draw_rect(px + panel_w - bw, py, bw, panel_h, border)

        bass = float(self._hud_state.get('bass', '0.0') or 0.0)
        mid = float(self._hud_state.get('mid', '0.0') or 0.0)
        treble = float(self._hud_state.get('treble', '0.0') or 0.0)
        self._draw_audio_reactive_border_bulbs(px, py, panel_w, panel_h, bass, mid, treble, t, speed_scale=0.5, size_scale=0.5)

        self._draw_text(
            'PROJECTM PRESET MANAGER',
            px + 18.0,
            py + 14.0,
            scale=3.5,
            color=(0.28 + 0.20 * pulse, 0.78, 1.0, 1.0),
        )
        enabled_total, total_total = self._projectm_category_stats('(all)')
        self._draw_text(
            f'Visible catalog: {enabled_total}/{total_total} enabled',
            px + 18.0,
            py + 48.0,
            scale=2.2,
            color=(0.52, 0.85, 0.58, 0.88),
        )
        query = self._projectm_search_query
        query_display = query if query else '(none)'
        if len(query_display) > 52:
            query_display = '...' + query_display[-49:]
        self._draw_text(
            f'Search: {query_display}',
            px + 18.0,
            py + 70.0,
            scale=1.9,
            color=(0.86, 0.90, 1.0, 0.88),
        )

        self._draw_rect(left_x, content_y, left_w, content_h, (0.04, 0.08, 0.13, 0.82))
        self._draw_rect(right_x, content_y, right_w, content_h, (0.03, 0.07, 0.12, 0.82))

        left_border = (1.0, 0.62, 0.20, 0.70 if self._projectm_focus_pane == 0 else 0.32)
        right_border = (0.14, 0.90, 1.0, 0.70 if self._projectm_focus_pane == 1 else 0.32)
        self._draw_rect(left_x, content_y, left_w, 2.0, left_border)
        self._draw_rect(right_x, content_y, right_w, 2.0, right_border)

        self._draw_text('CATEGORIES', left_x + 12.0, content_y + 10.0, scale=2.4, color=(1.0, 0.88, 0.56, 0.96))
        self._draw_text('PRESETS', right_x + 12.0, content_y + 10.0, scale=2.4, color=(0.72, 0.92, 1.0, 0.96))

        row_h = 28.0
        cat_start_y = content_y + 48.0
        visible_cat_rows = max(1, int((content_h - 60.0) // row_h))
        cat_top = 0
        if self._projectm_category_idx >= visible_cat_rows:
            cat_top = self._projectm_category_idx - visible_cat_rows + 1

        for local_idx, category in enumerate(self._projectm_categories[cat_top:cat_top + visible_cat_rows]):
            idx = cat_top + local_idx
            ry = cat_start_y + local_idx * row_h
            is_sel = idx == self._projectm_category_idx
            enabled_count, total_count = self._projectm_category_stats(category)
            label = f'{category} [{enabled_count}/{total_count}]'
            if is_sel:
                self._draw_rect(left_x + 6.0, ry - 2.0, left_w - 12.0, row_h - 3.0, (0.25, 0.18, 0.06, 0.90))
                self._draw_text(f'> {label}', left_x + 16.0, ry + 4.0, scale=2.0, color=(1.0, 0.92, 0.22, 1.0))
            else:
                self._draw_text(f'  {label}', left_x + 16.0, ry + 4.0, scale=2.0, color=(0.84, 0.86, 0.94, 0.84))

        preset_entries = self._projectm_filtered_entries()
        preset_start_y = content_y + 48.0
        preset_visible_rows = max(1, int((content_h - 138.0) // row_h))
        preset_top = 0
        if self._projectm_preset_idx >= preset_visible_rows:
            preset_top = self._projectm_preset_idx - preset_visible_rows + 1

        visible_rows = preset_entries[preset_top:preset_top + preset_visible_rows]
        for local_idx, entry in enumerate(visible_rows):
            idx = preset_top + local_idx
            ry = preset_start_y + local_idx * row_h
            is_sel = idx == self._projectm_preset_idx
            path = str(entry.get('path', ''))
            is_current = path == self._projectm_current_path
            enabled = bool(entry.get('enabled', False))
            prefix = '*' if is_current else ' '
            status = 'ON ' if enabled else 'OFF'
            name = str(entry.get('display_name', ''))[:54]
            label = f'{prefix} [{status}] {name}'
            if is_sel:
                self._draw_rect(right_x + 6.0, ry - 2.0, right_w - 12.0, row_h - 3.0, (0.08, 0.24, 0.54, 0.90))
                self._draw_text(f'> {label}', right_x + 16.0, ry + 4.0, scale=2.0, color=(1.0, 0.94, 0.26, 1.0))
            else:
                color = (0.40, 0.92, 0.44, 0.90) if enabled else (0.98, 0.48, 0.48, 0.88)
                self._draw_text(f'  {label}', right_x + 16.0, ry + 4.0, scale=2.0, color=color)

        details_y = content_y + content_h - 76.0
        self._draw_rect(right_x + 8.0, details_y, right_w - 16.0, 64.0, (0.04, 0.11, 0.17, 0.86))
        selected = self.get_projectm_selected_preset()
        if selected is None:
            self._draw_text('No presets in selected category.', right_x + 18.0, details_y + 14.0, scale=2.1, color=(0.88, 0.88, 0.92, 0.88))
        else:
            pack_name = str(selected.get('pack_name', '-'))
            category_key = str(selected.get('category_key', '(uncategorized)'))
            path = str(selected.get('path', ''))
            enabled = 'ON' if bool(selected.get('enabled', False)) else 'OFF'
            self._draw_text(
                f'Pack: {pack_name}    Category: {category_key}    State: {enabled}',
                right_x + 18.0,
                details_y + 10.0,
                scale=1.85,
                color=(0.62, 0.88, 1.0, 0.92),
            )
            self._draw_text(
                path[:92],
                right_x + 18.0,
                details_y + 34.0,
                scale=1.55,
                color=(0.80, 0.84, 0.92, 0.88),
            )

        self._draw_text(
            'Tab/Left/Right: pane    Up/Down: browse + preview    Enter: confirm    /: search mode    E/D: enable-disable    I: isolate',
            px + 18.0,
            footer_y - 10.0,
            scale=1.8,
            color=(0.58, 0.68, 0.78, 0.86),
        )
        self._draw_text(
            'Ctrl+A: enable all    Ctrl+Shift+A: disable all    Ctrl+Z: undo    Ctrl+Y/Ctrl+Shift+Z: redo    Delete: trash',
            px + 18.0,
            footer_y + 12.0,
            scale=1.8,
            color=(0.58, 0.68, 0.78, 0.86),
        )
        self._draw_text(
            'Esc/Ctrl+M: close + revert unconfirmed',
            px + 18.0,
            footer_y + 32.0,
            scale=1.8,
            color=(0.58, 0.68, 0.78, 0.86),
        )

    def _render_system_monitor_modal(self) -> None:
        """Draw a neon monitor dashboard modal with an oscilloscope backdrop."""
        t = self._hud_t
        pulse = 0.55 + 0.45 * math.sin(t * 2.2)

        W = float(self._width)
        H = float(self._height)

        # Heart-monitor style background wave field.
        baseline = H * 0.5
        amp = H * (0.045 + 0.015 * math.sin(t * 1.2))
        for i in range(0, 240):
            x = (i / 239.0) * W
            s = i / 239.0
            y = baseline + math.sin(s * 28.0 - t * 3.3) * amp
            y += math.sin(s * 57.0 + t * 2.2) * amp * 0.35
            glow = 0.16 + 0.14 * (0.5 + 0.5 * math.sin(t * 5.0 + s * 17.0))
            self._draw_rect(x, y - 1.0, 6.0, 2.0, (0.06, 0.92, 0.45, glow))

        panel_w = min(W * 0.80, 1220.0)
        panel_h = min(H * 0.76, 760.0)
        px = (W - panel_w) * 0.5
        py = (H - panel_h) * 0.5

        self._sample_system_telemetry()

        # Main panel shell.
        self._draw_rect(px, py, panel_w, panel_h, (0.03, 0.05, 0.12, 0.93))
        bw = 2.0
        border = (0.16 * pulse, 0.74 * pulse, 1.00 * pulse, 0.92)
        self._draw_rect(px, py, panel_w, bw, border)
        self._draw_rect(px, py + panel_h - bw, panel_w, bw, border)
        self._draw_rect(px, py, bw, panel_h, border)
        self._draw_rect(px + panel_w - bw, py, bw, panel_h, border)

        # Modal decorators: HUD-style side stacks and tick marks.
        side_w = 14.0
        block_defs = [
            (24.0, (1.00, 0.58, 0.12), 0.66),
            (6.0, None, 0.0),
            (10.0, (0.10, 0.94, 1.00), 0.58),
            (6.0, None, 0.0),
            (34.0, (0.78, 0.38, 1.00), 0.54),
            (6.0, None, 0.0),
            (24.0, (1.00, 0.58, 0.12), 0.60),
        ]
        side_rx = px + panel_w + 4.0
        side_lx = px - side_w - 4.0
        by_r = py + 8.0
        by_l = py + 8.0
        for bh, rgb, alpha in block_defs:
            if rgb is None:
                by_r += bh
                by_l += bh
                continue
            a = alpha + 0.20 * (0.5 + 0.5 * math.sin(t * 2.4 + by_r * 0.01))
            col = (rgb[0], rgb[1], rgb[2], min(1.0, a))
            self._draw_rect(side_rx, by_r, side_w, bh, col)
            self._draw_rect(side_lx, by_l, side_w, bh, col)
            by_r += bh
            by_l += bh

        tick_positions = [0.25, 0.5, 0.75]
        tick_colors = [
            (0.10, 0.94, 1.0, 0.58 + pulse * 0.18),
            (1.00, 0.62, 0.20, 0.58 + pulse * 0.18),
            (0.78, 0.38, 1.00, 0.58 + pulse * 0.18),
        ]
        tick_x_r = px + panel_w - 24.0
        tick_x_l = px + 6.0
        for tp, tc in zip(tick_positions, tick_colors):
            ty = py + tp * panel_h
            self._draw_rect(tick_x_r, ty, 18.0, 3.0, tc)
            self._draw_rect(tick_x_l, ty, 18.0, 3.0, tc)

        self._draw_text('SYSTEM MONITOR // CONTROL SURFACE', px + 18.0, py + 16.0, scale=3.0,
                        color=(0.28 + 0.25 * pulse, 0.82, 1.0, 1.0))
        self._draw_text('M: close modal', px + panel_w - 270.0, py + 20.0, scale=1.8,
                        color=(0.68, 0.80, 0.92, 0.86))

        state = self._hud_state

        def _num(key: str, default: float = 0.0) -> float:
            text = str(state.get(key, default))
            out = ''
            dot = False
            sign = False
            for ch in text:
                if ch.isdigit():
                    out += ch
                elif ch == '.' and not dot:
                    out += ch
                    dot = True
                elif ch == '-' and not sign and not out:
                    out += ch
                    sign = True
                elif out:
                    break
            try:
                return float(out)
            except Exception:
                return float(default)

        (
            fps,
            frame_ms,
            bass,
            mid,
            treble,
            bass_bar,
            mid_bar,
            treble_bar,
        ) = self._system_monitor_audio_metrics(_num)
        react, speed, zoom = self._system_monitor_tweakables(_num)

        # Left: metrics bars.
        left_x = px + 20.0
        left_y = py + 72.0
        left_w = panel_w * 0.50
        row_h = 44.0

        def _metric_row(idx: int, label: str, value: float, max_value: float, color: tuple[float, float, float]) -> None:
            y = left_y + idx * row_h
            frac = 0.0 if max_value <= 0.0 else max(0.0, min(1.0, value / max_value))
            self._draw_text(label, left_x, y + 8.0, scale=2.1, color=(0.72, 0.84, 0.98, 0.92))
            bx = left_x + 170.0
            bwid = left_w - 190.0
            self._draw_rect(bx, y + 10.0, bwid, 18.0, (0.10, 0.16, 0.26, 0.75))
            self._draw_rect(bx, y + 10.0, bwid * frac, 18.0, (color[0], color[1], color[2], 0.90))
            self._draw_rect(bx + bwid * frac - 2.0, y + 8.0, 4.0, 22.0, (0.95, 0.98, 1.0, 0.65))
            self._draw_text(f'{value:.2f}', bx + bwid + 12.0, y + 8.0, scale=2.0, color=(0.92, 0.95, 1.0, 0.92))

        _metric_row(0, 'FPS', fps, 120.0, (0.22, 1.00, 0.58))
        _metric_row(1, 'FRAME MS', max(0.0, 33.0 - frame_ms), 33.0, (0.16, 0.86, 1.00))
        _metric_row(2, 'BASS', bass_bar, 1.2, (1.00, 0.45, 0.18))
        _metric_row(3, 'MID', mid_bar, 1.2, (0.98, 0.76, 0.22))
        _metric_row(4, 'TREBLE', treble_bar, 1.2, (0.76, 0.95, 1.00))

        # Right: control panel with faux knobs/sliders.
        right_x = px + panel_w * 0.56
        right_y = py + 82.0
        self._draw_text('LIVE CONTROLS', right_x, right_y - 34.0, scale=2.4,
                        color=(1.0, 0.88, 0.54, 0.94))

        def _slider(idx: int, label: str, value: float, max_value: float, color: tuple[float, float, float]) -> None:
            y = right_y + idx * 70.0
            frac = 0.0 if max_value <= 0.0 else max(0.0, min(1.0, value / max_value))
            self._draw_text(label, right_x, y, scale=2.0, color=(0.78, 0.88, 0.98, 0.9))
            sx = right_x + 10.0
            sy = y + 24.0
            sw = panel_w * 0.34
            sh = 16.0
            self._draw_rect(sx, sy, sw, sh, (0.09, 0.14, 0.24, 0.78))
            self._draw_rect(sx, sy, sw * frac, sh, (color[0], color[1], color[2], 0.92))
            self._draw_rect(sx + sw * frac - 3.0, sy - 3.0, 6.0, sh + 6.0, (0.98, 0.98, 1.0, 0.78))
            self._draw_text(f'{value:.2f}', sx + sw + 14.0, y + 20.0, scale=2.0,
                            color=(0.92, 0.96, 1.0, 0.92))

        _slider(0, 'REACTIVITY', react, 3.0, (0.14, 0.90, 1.00))
        _slider(1, 'SPEED', speed, 4.0, (0.40, 1.00, 0.54))
        _slider(2, 'ZOOM', zoom, 2.0, (0.98, 0.40, 1.00))

        # Simple faux knobs for visual language consistency.
        knob_y = right_y + 240.0
        knob_r = 26.0
        knob_gap = 110.0
        labels = [('GAIN', bass_bar), ('PULSE', mid_bar), ('SHINE', treble_bar)]
        for i, (label, raw) in enumerate(labels):
            cx = right_x + 30.0 + i * knob_gap
            cy = knob_y
            frac = max(0.0, min(1.0, raw / 1.2))
            # Ring segments.
            for s in range(28):
                a = (s / 28.0) * 6.28318
                x = cx + math.cos(a) * knob_r
                y = cy + math.sin(a) * knob_r
                on = s <= int(frac * 28.0)
                col = (0.14, 0.90, 1.0, 0.86) if on else (0.10, 0.20, 0.30, 0.55)
                self._draw_rect(x - 1.0, y - 1.0, 3.0, 3.0, col)
            # Pointer.
            pa = (-2.35 + frac * 4.70)
            pxp = cx + math.cos(pa) * (knob_r - 6.0)
            pyp = cy + math.sin(pa) * (knob_r - 6.0)
            self._draw_rect(cx - 2.0, cy - 2.0, 4.0, 4.0, (0.88, 0.95, 1.0, 0.9))
            self._draw_rect(pxp - 2.0, pyp - 2.0, 4.0, 4.0, (0.98, 0.84, 0.25, 0.95))
            self._draw_text(label, cx - 26.0, cy + 38.0, scale=1.8, color=(0.74, 0.84, 0.94, 0.9))

        # Bottom-half system telemetry board.
        board_x = px + 20.0
        board_y = py + panel_h * 0.56
        board_w = panel_w - 40.0
        board_h = panel_h * 0.34
        self._draw_rect(board_x, board_y, board_w, board_h, (0.03, 0.08, 0.14, 0.86))
        self._draw_rect(board_x, board_y, board_w, 2.0, (0.10, 0.94, 1.0, 0.46 + pulse * 0.16))

        def _sys_row(idx: int, label: str, value: float, max_value: float, text: str, color: tuple[float, float, float]) -> None:
            y = board_y + 14.0 + idx * 40.0
            frac = 0.0 if max_value <= 0.0 else max(0.0, min(1.0, value / max_value))
            self._draw_text(label, board_x + 10.0, y + 4.0, scale=2.0, color=(0.80, 0.90, 1.0, 0.92))
            bx = board_x + 180.0
            bwid = board_w - 300.0
            self._draw_rect(bx, y + 6.0, bwid, 16.0, (0.08, 0.14, 0.24, 0.78))
            self._draw_rect(bx, y + 6.0, bwid * frac, 16.0, (color[0], color[1], color[2], 0.92))
            self._draw_rect(bx + bwid * frac - 2.0, y + 4.0, 4.0, 20.0, (0.95, 0.98, 1.0, 0.64))
            self._draw_text(text, board_x + board_w - 102.0, y + 4.0, scale=2.0, color=(0.92, 0.96, 1.0, 0.90))

        _sys_row(0, 'CPU', self._sysmon_cpu, 1.0, f'{self._sysmon_cpu * 100.0:4.1f}%', (1.00, 0.45, 0.18))
        _sys_row(1, 'RAM', self._sysmon_ram, 1.0, f'{self._sysmon_ram * 100.0:4.1f}%', (0.72, 0.44, 1.00))
        _sys_row(2, 'SWAP', self._sysmon_swap, 1.0, f'{self._sysmon_swap * 100.0:4.1f}%', (0.46, 0.78, 1.00))
        _sys_row(3, 'DISK I/O', self._sysmon_disk_mbs, 120.0, f'{self._sysmon_disk_mbs:4.1f}M', (1.00, 0.78, 0.24))
        _sys_row(4, 'NET I/O', self._sysmon_net_mbs, 120.0, f'{self._sysmon_net_mbs:4.1f}M', (0.22, 0.96, 0.66))

        self._draw_text('TELEMETRY LINK STABLE  //  NO SIGNAL CLIP DETECTED',
                        px + 20.0, py + panel_h - 28.0, scale=1.8,
                        color=(0.56, 0.68, 0.80, 0.82))

    def _system_monitor_audio_metrics(
        self,
        num_reader: Callable[[str, float], float],
    ) -> tuple[float, float, float, float, float, float, float, float]:
        """Resolve monitor frame/BMT metrics from runtime provider with HUD fallback."""
        fps = num_reader('fps', 0.0)
        frame_ms = num_reader('frame_ms', 0.0)
        bass = num_reader('bass', 0.0)
        mid = num_reader('mid', 0.0)
        treble = num_reader('treble', 0.0)
        bass_n = num_reader('bass_n', 0.5)
        mid_n = num_reader('mid_n', 0.5)
        treble_n = num_reader('treble_n', 0.5)

        provider = self._system_monitor_audio_provider
        if not callable(provider):
            return fps, frame_ms, bass, mid, treble, bass_n, mid_n, treble_n

        try:
            values = provider()
        except Exception as exc:
            log.debug('System monitor audio provider failed: %s', exc)
            return fps, frame_ms, bass, mid, treble, bass_n, mid_n, treble_n

        if not isinstance(values, dict):
            return fps, frame_ms, bass, mid, treble, bass_n, mid_n, treble_n

        def _override(name: str, current: float) -> float:
            raw = values.get(name)
            if raw is None:
                return current
            try:
                return float(raw)
            except Exception:
                return current

        fps = _override('fps', fps)
        frame_ms = _override('frame_ms', frame_ms)
        bass = _override('bass', bass)
        mid = _override('mid', mid)
        treble = _override('treble', treble)
        bass_n = _override('bass_n', bass_n)
        mid_n = _override('mid_n', mid_n)
        treble_n = _override('treble_n', treble_n)
        return fps, frame_ms, bass, mid, treble, bass_n, mid_n, treble_n

    def _system_monitor_tweakables(
        self,
        num_reader: Callable[[str, float], float],
    ) -> tuple[float, float, float]:
        """Resolve monitor tweakables from runtime provider with HUD fallback."""
        react = num_reader('reactivity', 1.0)
        speed = num_reader('speed', 1.0)
        zoom = num_reader('zoom', 1.0)

        provider = self._system_monitor_tweakables_provider
        if not callable(provider):
            return react, speed, zoom

        try:
            values = provider()
        except Exception as exc:
            log.debug('System monitor tweakables provider failed: %s', exc)
            return react, speed, zoom

        if not isinstance(values, dict):
            return react, speed, zoom

        def _override(name: str, current: float) -> float:
            raw = values.get(name)
            if raw is None:
                return current
            try:
                return float(raw)
            except Exception:
                return current

        react = _override('reactivity', react)
        speed = _override('speed', speed)
        zoom = _override('zoom', zoom)
        return react, speed, zoom


    def _sample_system_telemetry(self) -> None:
        """Update modal telemetry metrics with lightweight cached psutil reads."""
        if not _PSUTIL_AVAILABLE:
            return
        now = time.monotonic()
        if now - self._sysmon_sample_t < 0.45:
            return
        self._sysmon_sample_t = now
        try:
            self._sysmon_cpu = max(0.0, min(1.0, psutil.cpu_percent(interval=None) / 100.0))
            self._sysmon_ram = max(0.0, min(1.0, psutil.virtual_memory().percent / 100.0))
            self._sysmon_swap = max(0.0, min(1.0, psutil.swap_memory().percent / 100.0))

            disk = psutil.disk_io_counters()
            net = psutil.net_io_counters()
            if disk is None or net is None:
                return

            io_t_prev = self._sysmon_prev_io_t
            disk_prev = self._sysmon_prev_disk_bytes
            net_prev = self._sysmon_prev_net_bytes

            disk_now = float(disk.read_bytes + disk.write_bytes)
            net_now = float(net.bytes_recv + net.bytes_sent)
            self._sysmon_prev_io_t = now
            self._sysmon_prev_disk_bytes = disk_now
            self._sysmon_prev_net_bytes = net_now

            if io_t_prev is None or disk_prev is None or net_prev is None:
                return

            dt = max(1e-6, now - io_t_prev)
            disk_rate = max(0.0, (disk_now - disk_prev) / dt)
            net_rate = max(0.0, (net_now - net_prev) / dt)
            self._sysmon_disk_mbs = disk_rate / (1024.0 * 1024.0)
            self._sysmon_net_mbs = net_rate / (1024.0 * 1024.0)
        except Exception:
            pass


    def _render_help(self) -> None:
        t  = self._hud_t
        hp = self._help_pulse_t
        pulse_slow  = 0.5 + 0.5 * math.sin(t * 1.1)
        pulse_med   = 0.5 + 0.5 * math.sin(t * 2.3)
        pulse_fast  = 0.5 + 0.5 * math.sin(t * 4.7)
        shimmer_x   = math.fmod(t * 0.38, 1.0)

        # shrunk margins so side decorations clear the screen
        panel_pad = 44.0
        x = panel_pad
        y = panel_pad
        w = self._width  - panel_pad * 2.0
        h = self._height - panel_pad * 2.0

        self._draw_modal_underlay(x, y, w, h, alpha=0.45, pad=12.0)

        # Keep help legible on high-res canvases without overpowering 1080p.
        res_ratio = min(self._width, self._height) / 1080.0
        help_scale = min(1.28, max(1.0, res_ratio ** 0.35))

        # ── outer halo (breathing) ────────────────────────────────────────
        halo_a = 0.05 + pulse_slow * 0.08
        self._draw_rect(x - 18.0, y - 18.0, w + 36.0, h + 36.0, (0.08, 0.88, 1.0, halo_a * 0.5))
        self._draw_rect(x -  8.0, y -  8.0, w + 16.0, h + 16.0, (0.08, 0.88, 1.0, halo_a))

        # ── main background ───────────────────────────────────────────────
        self._draw_rect(x, y, w, h, (0.02, 0.04, 0.09, 0.65))

        # ── border (pulsing) ─────────────────────────────────────────────
        border_a = 0.50 + pulse_slow * 0.34
        self._draw_rect(x - 1.0, y - 1.0, w + 2.0, 2.0,      (0.10, 0.94, 1.0, border_a))
        self._draw_rect(x - 1.0, y + h - 1.0, w + 2.0, 2.0,  (0.10, 0.94, 1.0, border_a))
        self._draw_rect(x - 1.0, y - 1.0, 2.0, h + 2.0,      (0.10, 0.94, 1.0, border_a))
        self._draw_rect(x + w - 1.0, y - 1.0, 2.0, h + 2.0,  (0.10, 0.94, 1.0, border_a))
        bass = float(self._hud_state.get('bass', '0.0') or 0.0)
        mid = float(self._hud_state.get('mid', '0.0') or 0.0)
        treble = float(self._hud_state.get('treble', '0.0') or 0.0)
        self._draw_audio_reactive_border_bulbs(x, y, w, h, bass, mid, treble, t, speed_scale=0.45, size_scale=0.45)


        # ── sparkle sprite chasing the help border ────────────────────────
        sprite_t = math.fmod(t * 0.176, 1.0)   # slightly slower lap than HUD
        perim    = 2.0 * (w + h)
        dist     = sprite_t * perim
        if dist < w:
            hsx, hsy = x + dist, y - 1.0
        elif dist < w + h:
            hsx, hsy = x + w - 1.0, y + (dist - w)
        elif dist < 2 * w + h:
            hsx, hsy = x + w - (dist - w - h), y + h - 1.0
        else:
            hsx, hsy = x - 1.0, y + h - (dist - 2 * w - h)
        sp_a = 0.72 + 0.28 * math.sin(t * 11.3)
        self._draw_rect(hsx - 10.0, hsy - 10.0, 22.0, 22.0, (0.10, 0.94, 1.0, sp_a * 0.22))
        self._draw_rect(hsx -  7.0, hsy -  7.0, 16.0, 16.0, (0.10, 0.94, 1.0, sp_a * 0.46))
        self._draw_rect(hsx -  4.0, hsy -  4.0, 10.0, 10.0, (0.50, 0.98, 1.0, sp_a * 0.76))
        self._draw_rect(hsx -  2.0, hsy -  2.0,  6.0,  6.0, (0.80, 1.00, 1.0, sp_a * 0.92))
        self._draw_rect(hsx -  1.0, hsy -  1.0,  4.0,  4.0, (1.00, 1.00, 1.0, min(1.0, sp_a * 1.10)))
        # ghost half-lap behind
        ghost_t = math.fmod(sprite_t + 0.5, 1.0)
        gd = ghost_t * perim
        if gd < w:
            ghx, ghy = x + gd, y - 1.0
        elif gd < w + h:
            ghx, ghy = x + w - 1.0, y + (gd - w)
        elif gd < 2 * w + h:
            ghx, ghy = x + w - (gd - w - h), y + h - 1.0
        else:
            ghx, ghy = x - 1.0, y + h - (gd - 2 * w - h)
        tr_a = 0.42 + 0.28 * math.sin(t * 7.1)
        self._draw_rect(ghx - 5.0, ghy - 5.0, 12.0, 12.0, (0.78, 0.38, 1.00, tr_a * 0.38))
        self._draw_rect(ghx - 3.0, ghy - 3.0,  8.0,  8.0, (0.78, 0.38, 1.00, tr_a * 0.65))
        self._draw_rect(ghx - 1.0, ghy - 1.0,  4.0,  4.0, (1.00, 0.70, 1.00, tr_a * 0.90))

        # ── LCARS side block stacks ───────────────────────────────────────
        side_w  = 16.0
        side_rx = x + w + 4.0
        side_lx = x - 4.0 - side_w
        block_defs = [
            (28.0, (1.00, 0.58, 0.12), 0.68, 0.00, 2.30, 0.0 ),
            (6.0,  None, 0, 0, 0, 0),
            (8.0,  (1.00, 0.58, 0.12), 0.34, 0.70, 4.10, 7.3 ),
            (6.0,  None, 0, 0, 0, 0),
            (44.0, (0.10, 0.94, 1.00), 0.68, 1.10, 1.80, 0.0 ),
            (6.0,  None, 0, 0, 0, 0),
            (14.0, (0.78, 0.38, 1.00), 0.56, 2.20, 3.50, 0.0 ),
            (6.0,  None, 0, 0, 0, 0),
            (60.0, (1.00, 0.58, 0.12), 0.56, 0.50, 1.10, 0.0 ),
            (6.0,  None, 0, 0, 0, 0),
            (14.0, (0.10, 0.94, 1.00), 0.48, 1.80, 5.20, 11.7),
            (6.0,  None, 0, 0, 0, 0),
            (28.0, (0.98, 0.96, 0.30), 0.52, 0.90, 2.70, 0.0 ),
            (6.0,  None, 0, 0, 0, 0),
            (14.0, (0.78, 0.38, 1.00), 0.44, 3.10, 4.80, 9.1 ),
            (6.0,  None, 0, 0, 0, 0),
            (24.0, (1.00, 0.58, 0.12), 0.62, 1.60, 2.10, 0.0 ),
        ]
        by_r = y;  by_l = y
        for bdef in block_defs:
            bh = bdef[0]
            if bdef[1] is None:
                by_r += bh;  by_l += bh;  continue
            bh, rgb, base_a, phase, spd, strobe_spd = bdef
            pv = 0.5 + 0.5 * math.sin(t * spd + phase)
            alpha = base_a + pv * 0.28
            if strobe_spd > 0:
                alpha = min(1.0, alpha + max(0.0, math.sin(t * strobe_spd)) ** 3 * 0.38)
            bc = (rgb[0], rgb[1], rgb[2], min(1.0, alpha))
            hi_a = min(1.0, alpha * 0.55 + pv * 0.25)
            self._draw_rect(side_rx, by_r, side_w, bh, bc)
            self._draw_rect(side_rx, by_r, 2.0, bh, (1.0, 1.0, 1.0, hi_a))
            self._draw_rect(side_lx, by_l, side_w, bh, bc)
            self._draw_rect(side_lx + side_w - 2.0, by_l, 2.0, bh, (1.0, 1.0, 1.0, hi_a))
            by_r += bh;  by_l += bh

        # ── corner accent blocks + crosshair arms ────────────────────────
        corner_sz = 14.0
        ca = 0.65 + pulse_fast * 0.30
        for cx_, cy_ in [(x-1, y-1), (x+w-corner_sz+1, y-1), (x-1, y+h-corner_sz+1), (x+w-corner_sz+1, y+h-corner_sz+1)]:
            self._draw_rect(cx_, cy_, corner_sz, corner_sz, (1.0, 0.58, 0.12, ca))
        ic = 6.0;  ica = 0.52 + pulse_slow * 0.32
        for cx_, cy_ in [(x+2, y+2), (x+w-ic-2, y+2), (x+2, y+h-ic-2), (x+w-ic-2, y+h-ic-2)]:
            self._draw_rect(cx_, cy_, ic, ic, (0.10, 0.94, 1.0, ica))
        arm_len = 40.0;  arm_a = 0.28 + pulse_slow * 0.20
        self._draw_rect(x + corner_sz,           y + 1.0,                1.0, arm_len, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + 1.0,                  y + corner_sz,          arm_len, 1.0, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + w - corner_sz - 1.0,  y + 1.0,                1.0, arm_len, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + w - arm_len - 1.0,    y + 1.0,               arm_len, 1.0, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + corner_sz,           y + h - 2.0,            arm_len, 1.0, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + 1.0,                  y + h - corner_sz - arm_len, 1.0, arm_len, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + w - corner_sz - 1.0,  y + h - 2.0,           1.0, arm_len, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + w - arm_len - 1.0,    y + h - 2.0,          arm_len, 1.0, (1.0, 0.58, 0.12, arm_a))

        # ── header ───────────────────────────────────────────────────────
        self._draw_rect(x, y, w, 86.0, (0.05, 0.08, 0.16, 0.80))
        # header shimmer
        shim_w = w * 0.18
        self._draw_rect(x + shimmer_x * (w - shim_w), y, shim_w, 86.0, (1.0, 1.0, 1.0, 0.04 + pulse_fast * 0.03))
        # triple separator bar
        bar_a = 0.60 + pulse_slow * 0.22
        self._draw_rect(x, y + 80.0, w, 2.0, (1.0, 0.62, 0.20, bar_a * 0.5))
        self._draw_rect(x, y + 83.0, w, 4.0, (1.0, 0.62, 0.20, bar_a))
        self._draw_rect(x, y + 88.0, w, 1.0, (1.0, 0.62, 0.20, bar_a * 0.4))
        # title — inverse pulse
        title_a = 0.86 + (1.0 - pulse_med) * 0.14
        title_str = 'UNICORN VIZ - HELP'
        title_scale = 2.95 * help_scale
        self._draw_text(
            title_str,
            x + (w - len(title_str) * 8.0 * title_scale) * 0.5,
            y + 10.0,
            scale=title_scale,
            color=(0.12, 0.98, 1.0, title_a),
        )
        # Centered live date/time replacing former ProjectM preset labels.
        _now = datetime.datetime.now()
        dt_str = _now.strftime('<<  %a  %d %b %Y  //  %H:%M:%S  >>')
        dt_a = 0.78 + pulse_slow * 0.18
        dt_scale = 1.72 * help_scale
        self._draw_text(
            dt_str,
            x + (w - len(dt_str) * 8.0 * dt_scale) * 0.5,
            y + 56.0,
            scale=dt_scale,
            color=(0.90, 1.0, 0.82, dt_a),
        )

        icon_band_y = y + 100.0
        icon_band_h = self._render_help_icon_rail(x, icon_band_y, w, help_scale)
        content_top_y = icon_band_y + icon_band_h + 14.0

        # ── left/right content panes ──────────────────────────────────────
        left_x = x + 14.0
        left_y = content_top_y
        left_w = w * 0.64
        left_h = (y + h) - left_y - 10.0

        right_x = left_x + left_w + 10.0
        right_y = left_y
        right_w = x + w - right_x - 14.0
        right_h = left_h

        # left pane: dark bg + left orange bar
        self._draw_rect(left_x, left_y, left_w, left_h, (0.02, 0.07, 0.11, 0.62))
        self._draw_rect(left_x, left_y, 5.0, left_h, (1.0, 0.62, 0.20, 0.68 + pulse_med * 0.18))
        # right pane: dark bg + right teal bar
        self._draw_rect(right_x, right_y, right_w, right_h, (0.02, 0.09, 0.12, 0.62))
        self._draw_rect(right_x + right_w - 5.0, right_y, 5.0, right_h, (0.10, 0.94, 1.0, 0.60 + pulse_slow * 0.18))
        # scan line across left pane
        scan_h_lp = math.fmod(t * 0.28, 1.0)
        scan_y_lp = left_y + scan_h_lp * left_h
        self._draw_rect(left_x, scan_y_lp - 1.0, left_w, 2.0, (0.10, 0.94, 1.0, 0.04))
        self._draw_rect(left_x, scan_y_lp,        left_w, 1.0, (0.10, 0.94, 1.0, 0.14))

        # ── bottom segmented bar ──────────────────────────────────────────
        seg_n = 12;  seg_gap = 4.0
        seg_w_b = (w - (seg_n - 1) * seg_gap) / seg_n
        for s in range(seg_n):
            seg_a = 0.28 + 0.22 * (0.5 + 0.5 * math.sin(t * 1.8 + s * 0.52))
            self._draw_rect(x + s * (seg_w_b + seg_gap), y + h - 8.0, seg_w_b, 8.0, (0.12, 0.96, 1.0, seg_a))
        self._draw_rect(x, y + h - 10.0, w, 2.0, (0.10, 0.94, 1.0, 0.44 + pulse_med * 0.18))

        self._draw_help_section_content(x, y, w, h, help_scale, content_top_y)
        entries = self._help_icon_entries()
        if self._help_icon_hover_idx >= 0 and self._help_icon_hover_idx < len(entries):
            hover_entry = entries[self._help_icon_hover_idx]
            tooltip = self._help_icon_tooltip(hover_entry)
            if tooltip:
                self._draw_help_icon_tooltip(tooltip, self._help_icon_hover_pos, x, y, w, icon_band_h)

    def _render_help_icon_rail(self, x: float, y: float, w: float, help_scale: float) -> float:
        """Draw the centered help icon rail and return its rendered height."""
        entries = self._help_icon_entries()
        if not entries:
            return 0.0

        icon_px = 152.0 if self._help_icon_asset_bucket == '152px' else 76.0
        band_h = max(icon_px + 20.0, 72.0 * help_scale)
        gap = max(14.0, 16.0 * help_scale)
        cell_w = icon_px
        cell_h = icon_px

        total_w = len(entries) * cell_w + max(0, len(entries) - 1) * gap
        start_x = round(x + max(0.0, (w - total_w) * 0.5))
        rail_y = round(y + max(0.0, (band_h - cell_h) * 0.5) - 10.0)

        self._draw_rect(round(x + 20.0), round(y + band_h - 4.0), round(w - 40.0), 2.0, (1.0, 0.70, 0.24, 0.42))

        for idx, entry in enumerate(entries):
            cell_x = round(start_x + idx * (cell_w + gap))
            accent = self._help_icon_accent(entry)
            is_active = self._help_focus_region == 'icons' and idx == self._help_icon_focus_idx
            pulse = 0.5 + 0.5 * math.sin(self._help_pulse_t * 4.2 + idx * 0.63)
            glow_a = 0.12 + pulse * 0.14 if is_active else 0.05 + pulse * 0.05
            border_a = 0.62 if is_active else 0.28

            self._draw_rect(cell_x - 2.0, rail_y - 2.0, cell_w + 4.0, cell_h + 4.0, (accent[0], accent[1], accent[2], glow_a))
            self._draw_rect(cell_x, rail_y, cell_w, cell_h, (0.03 + accent[0] * 0.03, 0.05 + accent[1] * 0.05, 0.09 + accent[2] * 0.04, 0.72))
            self._draw_rect(cell_x, rail_y, cell_w, 3.0, (accent[0], accent[1], accent[2], 0.82))
            self._draw_rect(cell_x, rail_y + 2.0, cell_w, 4.0, (accent[0], accent[1], accent[2], 0.34 + pulse * 0.12))
            if is_active:
                self._draw_rect(cell_x - 1.0, rail_y - 1.0, cell_w + 2.0, cell_h + 2.0, (accent[0], accent[1], accent[2], border_a))

            icon_id = self._help_icon_image_id(entry)
            icon_tex = self._help_icon_textures.get(icon_id)
            icon_x = cell_x
            icon_y = rail_y + 1.0
            icon_size = icon_px
            if icon_tex is not None:
                icon_alpha = 1.0 if is_active else 0.94
                self._draw_icon_texture(icon_tex, icon_x, icon_y, icon_size, icon_size, alpha=icon_alpha)
            else:
                glyph = str(entry.get('glyph', ''))[:3].upper()
                glyph_scale = max(1.18, min(1.68, 1.42 * help_scale))
                glyph_w = len(glyph) * 8.0 * glyph_scale
                glyph_x = cell_x + (icon_px - glyph_w) * 0.5
                glyph_y = rail_y + (icon_px - 8.0 * glyph_scale) * 0.5 + 2.0
                self._draw_text(glyph, glyph_x, glyph_y, scale=glyph_scale, color=(1.0, 1.0, 1.0, 0.98))

        return band_h

    def _draw_help_icon_tooltip(
        self,
        tooltip: str,
        hover_pos: tuple[float, float] | None,
        panel_x: float,
        panel_y: float,
        panel_w: float,
        band_h: float,
    ) -> None:
        """Draw a small tooltip bubble for a hovered help icon."""
        text = str(tooltip or '').strip()
        if not text:
            return
        tip_x = float(hover_pos[0]) + 14.0 if hover_pos is not None else panel_x + panel_w * 0.5 - 120.0
        tip_y = panel_y + band_h + 8.0
        scale = 1.48
        text_w = max(180.0, min(420.0, len(text) * 8.0 * scale + 28.0))
        box_h = 30.0
        if tip_x + text_w > panel_x + panel_w - 10.0:
            tip_x = panel_x + panel_w - text_w - 10.0
        if tip_x < panel_x + 10.0:
            tip_x = panel_x + 10.0
        self._draw_rect(tip_x, tip_y, text_w, box_h, (0.03, 0.05, 0.08, 0.92))
        self._draw_rect(tip_x, tip_y, text_w, 2.0, (0.10, 0.94, 1.0, 0.72))
        self._draw_rect(tip_x, tip_y + box_h - 2.0, text_w, 2.0, (0.78, 0.38, 1.0, 0.68))
        self._draw_text(text, tip_x + 10.0, tip_y + 7.0, scale=scale, color=(0.96, 0.98, 1.0, 0.98))

    def _draw_help_section_content(self, x: float, y: float, w: float, h: float, help_scale: float, content_top_y: float) -> None:
        """Draw section cards and shortcut map in the help panel content area."""
        t = self._hud_t
        hp = self._help_pulse_t
        pulse_med = 0.5 + 0.5 * math.sin(t * 2.3)

        left_x = x + 14.0
        left_y = content_top_y
        left_w = w * 0.64
        left_h = (y + h) - left_y - 10.0
        right_x = left_x + left_w + 10.0
        right_y = left_y
        right_w = x + w - right_x - 14.0
        right_h = left_h

        # ── section cards ─────────────────────────────────────────────────
        sections = self._iter_help_sections()
        if sections:
            self._help_focus_idx = max(0, min(self._help_focus_idx, len(sections) - 1))

        card_title_scale = 2.30 * help_scale
        item_scale = 2.10 * help_scale
        card_line_h = 8 * item_scale + 2.0
        card_pad = 8.0

        col_gap = 10.0
        col_w = (left_w - 14.0 - 3 * col_gap) / 2.0
        col_x = [left_x + 14.0 + col_gap, left_x + 14.0 + col_gap * 2 + col_w]
        col_y = [left_y + 8.0, left_y + 8.0]
        col_max_y = left_y + left_h - 10.0

        for sec_idx, (section, entries) in enumerate(sections):
            if not entries:
                continue
            accent = self._help_theme_color(section)
            collapsed = self._help_collapsed.get(section, False)
            visible_entries = [] if collapsed else entries
            section_h = card_pad * 2 + 8 * card_title_scale + 4 + len(visible_entries) * card_line_h
            if collapsed:
                section_h += card_line_h
            idx = 0 if col_y[0] <= col_y[1] else 1
            if col_y[idx] + section_h > col_max_y:
                other = 1 - idx
                if col_y[other] + section_h <= col_max_y:
                    idx = other
                else:
                    continue
            sx2 = col_x[idx]
            sy2 = col_y[idx]
            if sec_idx == self._help_focus_idx:
                pulse = 0.5 + 0.5 * math.sin(hp * 5.4)
                glow_a = 0.16 + pulse * 0.20
                edge_a = 0.34 + pulse * 0.26
                self._draw_rect(sx2 - 4.0, sy2 - 4.0, col_w + 8.0, section_h + 8.0, (accent[0], accent[1], accent[2], glow_a))
                self._draw_rect(sx2 - 2.0, sy2 - 2.0, col_w + 4.0, section_h + 4.0, (accent[0], accent[1], accent[2], edge_a))
            self._draw_rect(sx2, sy2, col_w, section_h, (0.05 + accent[0] * 0.05, 0.08 + accent[1] * 0.06, 0.14 + accent[2] * 0.05, 0.62))
            self._draw_rect(sx2, sy2, col_w, 3.0, (accent[0], accent[1], accent[2], 0.78))
            marker = '>' if (self._help_focus_region == 'sections' and sec_idx == self._help_focus_idx) else ' '
            icon = '+' if collapsed else '-'
            header = f'{marker}{sec_idx + 1}. {icon} {section.upper()} ({len(entries)})'
            self._draw_text(header, sx2 + card_pad, sy2 + card_pad, scale=card_title_scale, color=(accent[0], accent[1], accent[2], 0.98))
            yy = sy2 + card_pad + 8 * card_title_scale + 4
            if collapsed:
                self._draw_text('[collapsed]', sx2 + card_pad, yy, scale=item_scale, color=(0.78, 0.84, 0.92, 0.92))
                yy += card_line_h
            for key, desc in visible_entries:
                line = f'{key:<12} {desc}'
                self._draw_text(line, sx2 + card_pad, yy, scale=item_scale, color=(0.80 + accent[0] * 0.20, 0.82 + accent[1] * 0.18, 0.84 + accent[2] * 0.16, 0.96))
                yy += card_line_h
            col_y[idx] += section_h + 8.0

        # ── right pane: live shortcut map ─────────────────────────────────
        live_map_scale = 2.05 * help_scale
        self._draw_text(
            'LIVE SHORTCUT MAP',
            right_x + 10.0,
            right_y + 10.0,
            scale=live_map_scale,
            color=(1.0, 0.92, 0.58, 0.96),
        )
        self._draw_rect(right_x + 10.0, right_y + 30.0, right_w - 20.0, 2.0, (1.0, 0.72, 0.24, 0.60 + pulse_med * 0.20))

        rows = max(
            len(self._num_shortcuts),
            len(self._shift_shortcuts),
            len(self._ctrl_shortcuts),
            len(self._alt_shortcuts),
        )
        shortcut_title_scale = 1.85 * help_scale
        sec_scale = item_scale
        min_sec_scale = max(1.40, item_scale * 0.72)
        min_bottom_margin = 26.0

        def _shortcut_block_height(scale: float) -> float:
            line_h = 8 * scale + 2.0
            return (8 * shortcut_title_scale + 3.0) + float(min(rows, 12)) * line_h

        top = right_y + 42.0
        row_count = float(min(rows, 12))
        while sec_scale > min_sec_scale:
            sec_lh = 8 * sec_scale + 2.0
            top_block_h = (8 * shortcut_title_scale + 3.0) + row_count * sec_lh
            bottom_y = top + top_block_h + 28.0
            total_h = bottom_y + _shortcut_block_height(sec_scale)
            if total_h <= right_y + right_h - min_bottom_margin:
                break
            sec_scale -= 0.08

        sec_lh = 8 * sec_scale + 2.0

        def _draw_shortcut_block(title: str, items: list[str], bx: float, by: float, color: tuple[float, float, float, float]) -> None:
            self._draw_text(title, bx, by, scale=shortcut_title_scale, color=(0.96, 1.0, 0.70, 0.96))
            y0 = by + 8 * shortcut_title_scale + 3.0
            for i in range(min(rows, 12)):
                text = items[i] if i < len(items) else '(none)'
                self._draw_text(text, bx, y0 + i * sec_lh, scale=sec_scale, color=color)

        half = right_w * 0.48
        top_block_h = (8 * shortcut_title_scale + 3.0) + row_count * sec_lh
        bottom_y = top + top_block_h + 28.0
        _draw_shortcut_block('1-0',   self._num_shortcuts,   right_x + 10.0, top,      (0.82, 1.0,  0.9,  0.95))
        _draw_shortcut_block('SHIFT', self._shift_shortcuts, right_x + half, top,      (0.92, 0.86, 1.0,  0.95))
        _draw_shortcut_block('CTRL',  self._ctrl_shortcuts,  right_x + 10.0, bottom_y, (0.84, 0.94, 1.0,  0.95))
        _draw_shortcut_block('ALT',   self._alt_shortcuts,   right_x + half, bottom_y, (1.0,  0.92, 0.82, 0.95))

        # Dedicated Post FX block under number shortcuts, left aligned.
        if self._postfx_help_entries:
            postfx_y = bottom_y + _shortcut_block_height(sec_scale) + 18.0
            self._draw_text('POST FX', right_x + 10.0, postfx_y, scale=shortcut_title_scale, color=(0.98, 0.95, 0.72, 0.96))
            py = postfx_y + 8 * shortcut_title_scale + 3.0
            for key, desc in self._postfx_help_entries:
                self._draw_text(
                    f'{key:<16} {desc}',
                    right_x + 10.0,
                    py,
                    scale=item_scale,
                    color=(0.96, 0.88, 0.76, 0.96),
                )
                py += 8 * item_scale + 2.0

        if self._unmapped_effects:
            self._draw_text(
                f"Extra effects (no direct key): {', '.join(self._unmapped_effects)}",
                right_x + 10.0,
                right_y + right_h - 20.0,
                scale=1.16,
                color=(1.0, 0.62, 0.62, 0.94),
            )

    def _iter_help_sections(self) -> list[tuple[str, list[tuple[str, str]]]]:
        """Return merged core + dynamic help sections in render order."""
        sections: list[tuple[str, list[tuple[str, str]]]] = []
        for section, entries in self.CORE_HELP_SECTIONS:
            sections.append((section, list(entries)))

        # All drop-in sections render after system sections, alphabetized.
        dropin_sections: dict[str, list[tuple[str, str]]] = {
            section: list(entries)
            for section, entries in self.DROPIN_HELP_SECTIONS
        }
        for section in self._dynamic_help_order:
            entries = self._dynamic_help_sections.get(section, [])
            if not entries:
                continue
            bucket = dropin_sections.setdefault(section, [])
            for entry in entries:
                if entry not in bucket:
                    bucket.append(entry)

        for section in sorted(dropin_sections, key=lambda s: s.lower()):
            entries = dropin_sections.get(section, [])
            if entries:
                sections.append((section, list(entries)))
        return sections

    def _help_theme_color(self, section: str) -> tuple[float, float, float]:
        """Return accent color for a help section."""
        base = self.HELP_SECTION_THEMES.get(section)
        if base is not None:
            return base
        # Deterministic fallback for drop-in sections.
        idx = abs(hash(section)) % len(self.DYNAMIC_THEME_CYCLE)
        return self.DYNAMIC_THEME_CYCLE[idx]

    def register_help_entries(self, entries: list[tuple[str, str, str] | dict]) -> None:
        """Register help entries discovered from effects/drop-ins.

        Each entry may be:
        - (section, key, description)
        - {'section': str, 'key': str, 'description': str}
        """
        self._dynamic_help_sections = {}
        self._dynamic_help_order = []
        self._postfx_help_entries = []

        for item in entries:
            section = ''
            key = ''
            desc = ''
            if isinstance(item, dict):
                section = str(item.get('section', '')).strip()
                key = str(item.get('key', '')).strip()
                desc = str(item.get('description', item.get('desc', item.get('action', '')))).strip()
            elif isinstance(item, (tuple, list)) and len(item) >= 3:
                section = str(item[0]).strip()
                key = str(item[1]).strip()
                desc = str(item[2]).strip()

            if not (section and key and desc):
                continue

            if section.strip().lower() == 'post fx':
                entry = (key, desc)
                if entry not in self._postfx_help_entries:
                    self._postfx_help_entries.append(entry)
                continue

            bucket = self._dynamic_help_sections.setdefault(section, [])
            entry = (key, desc)
            if entry not in bucket:
                bucket.append(entry)
            if section not in self._dynamic_help_order:
                self._dynamic_help_order.append(section)

        # Keep collapse state for known sections, default to expanded.
        valid = [name for name, _entries in self._iter_help_sections()]
        default_expanded = {'Help Usage', 'Basics', 'Playback'}
        self._help_collapsed = {k: v for k, v in self._help_collapsed.items() if k in valid}
        for name in valid:
            if name not in self._help_collapsed:
                # Start with only the top three core sections expanded.
                self._help_collapsed[name] = name not in default_expanded
        if valid:
            self._help_focus_idx = max(0, min(self._help_focus_idx, len(valid) - 1))

    def _help_icon_entries(self) -> list[dict[str, object]]:
        """Return the static help icon entries."""
        return list(self.HELP_ICON_ENTRIES)

    def _help_icon_accent(self, entry: dict[str, object]) -> tuple[float, float, float]:
        accent = entry.get('accent', (0.9, 0.9, 0.9))
        if isinstance(accent, tuple) and len(accent) == 3:
            return float(accent[0]), float(accent[1]), float(accent[2])
        return (0.9, 0.9, 0.9)

    def help_focus_region(self) -> str:
        """Return the active help focus region."""
        return self._help_focus_region

    def help_icon_count(self) -> int:
        """Return the number of help icons available in the rail."""
        return len(self.HELP_ICON_ENTRIES)

    def toggle_help_focus_region(self) -> bool:
        """Toggle focus between the help section list and icon rail."""
        if not self._show_help:
            return False
        self._help_focus_region = 'icons' if self._help_focus_region == 'sections' else 'sections'
        return True

    def move_help_icon_focus(self, delta: int) -> bool:
        """Move focus within the help icon rail."""
        n = self.help_icon_count()
        if n <= 0:
            return False
        self._help_icon_focus_idx = (self._help_icon_focus_idx + delta) % n
        self._help_focus_region = 'icons'
        return True

    def move_help_focus_active(self, delta: int) -> bool:
        """Move focus in whichever help region is currently active."""
        if self._help_focus_region == 'icons':
            return self.move_help_icon_focus(delta)
        return self.move_help_focus(delta)

    def activate_help_focus_item(self) -> bool:
        """Activate the currently-focused help item.

        Phase 1 keeps icon activation local and non-networked.
        """
        if self._help_focus_region == 'icons':
            entries = self._help_icon_entries()
            if not entries:
                return False
            idx = max(0, min(self._help_icon_focus_idx, len(entries) - 1))
            entry = entries[idx]
            self._queue_help_icon_action(entry)
            return True
        return self.toggle_help_focus_section()

    def handle_help_mouse_click(self, x: float, y: float) -> bool:
        """Handle mouse clicks on the help icon rail."""
        idx = self._help_icon_hit_test(x, y)
        if idx < 0:
            return False
        entries = self._help_icon_entries()
        if not entries:
            return False
        self._help_focus_region = 'icons'
        self._help_icon_focus_idx = idx
        self._help_icon_hover_idx = idx
        self._help_icon_hover_pos = (float(x), float(y))
        self._queue_help_icon_action(entries[idx])
        return True

    def _queue_help_icon_action(self, entry: dict[str, object]) -> None:
        """Queue a normalized icon action payload for app-level dispatch."""
        self._pending_help_icon_action = {
            'id': str(entry.get('id', '') or '').strip(),
            'label': str(entry.get('label', '') or '').strip(),
            'description': str(entry.get('description', '') or '').strip(),
            'action_kind': str(entry.get('action_kind', 'placeholder') or 'placeholder').strip(),
            'target': str(entry.get('target', '') or '').strip(),
            'message': str(entry.get('message', '') or '').strip(),
        }

    def pop_help_icon_action(self) -> dict[str, str] | None:
        """Return and clear the next pending help icon action payload."""
        payload = self._pending_help_icon_action
        self._pending_help_icon_action = None
        return payload

    def note_help_activity(self) -> None:
        """Reset help auto-hide timer after keyboard interaction."""
        if self._show_help:
            self._help_timer = 60.0

    @property
    def help_visible(self) -> bool:
        return self._show_help

    @property
    def name_overlay_visible(self) -> bool:
        return self._show_name

    @property
    def audio_selector_visible(self) -> bool:
        return self._show_audio

    @property
    def midi_selector_visible(self) -> bool:
        return self._show_midi

    @property
    def system_monitor_modal_visible(self) -> bool:
        return self._show_system_monitor_modal

    @property
    def controller_help_modal_visible(self) -> bool:
        return self._show_controller_help_modal

    @property
    def projectm_manager_visible(self) -> bool:
        return self._show_projectm_manager

    @property
    def webcam_editor_modal_visible(self) -> bool:
        return self._show_webcam_editor_modal

    def modal_snapshot(self) -> dict[str, object]:
        """Return active modal state for alternate render surfaces.

        Priority mirrors render order so only one modal is active at a time.
        """
        if self._show_projectm_manager:
            selected = self.get_projectm_selected_preset()
            presets = self.projectm_filtered_presets()
            return {
                'type': 'projectm_manager',
                'title': 'PROJECTM PRESET MANAGER',
                'search_query': self._projectm_search_query,
                'category': self.get_projectm_selected_category(),
                'categories': self.projectm_categories(),
                'category_index': int(self.get_projectm_category_index()),
                'preset_index': int(self.get_projectm_preset_index()),
                'focus_pane': int(self._projectm_focus_pane),
                'entries': [
                    {
                        'display_name': str(entry.get('display_name', '')),
                        'pack_name': str(entry.get('pack_name', '')),
                        'path': str(entry.get('path', '')),
                        'enabled': bool(entry.get('enabled', False)),
                    }
                    for entry in presets
                ],
                'selected_name': str((selected or {}).get('display_name', '')),
                'selected_pack': str((selected or {}).get('pack_name', '')),
                'selected_path': str((selected or {}).get('path', '')),
            }
        if self._show_system_monitor_modal:
            return {
                'type': 'system_monitor',
                'title': 'SYSTEM MONITOR',
                'cpu': float(self._sysmon_cpu),
                'ram': float(self._sysmon_ram),
                'swap': float(self._sysmon_swap),
                'disk_mbs': float(self._sysmon_disk_mbs),
                'net_mbs': float(self._sysmon_net_mbs),
            }
        if self._show_controller_help_modal:
            return {
                'type': 'controller_help',
                'title': 'CONTROLLER HELP // APC MINI MK2',
                'device': 'akai_apc_mini_mk2',
                'context_slots': True,
            }
        if self._show_webcam_editor_modal:
            return {
                'type': 'webcam_editor',
                'title': 'WEBCAM EDITOR',
                'selected_index': int(self._webcam_editor_selected_idx),
                'devices': list(self._webcam_editor_devices),
                'image_state': dict(self._webcam_editor_state),
            }
        if self._show_audio:
            entries = self._audio_sources if self._audio_sources else ['(no sources available)']
            return {
                'type': 'audio_selector',
                'title': 'AUDIO SOURCE SELECT',
                'active_index': int(self._audio_current_idx),
                'selected_index': int(self._audio_selected_idx),
                'entries': list(entries),
                'viable_flags': list(self._audio_viable_flags),
            }
        if self._show_midi:
            entries = ['(none - disable MIDI)'] + list(self._midi_ports)
            return {
                'type': 'midi_selector',
                'title': 'MIDI DEVICE SELECT',
                'active_port': str(self._midi_current_port),
                'selected_index': int(self._midi_selected_idx),
                'entries': entries,
            }
        if self._show_help:
            sections_list = self._iter_help_sections()
            focus = max(0, min(self._help_focus_idx, len(sections_list) - 1))
            return {
                'type': 'help_overlay',
                'title': 'HELP OVERLAY',
                'section_count': len(sections_list),
                'focus_section': sections_list[focus][0] if sections_list else '-',
                'focus_idx': focus,
                'sections': [
                    {
                        'name': name,
                        'collapsed': bool(self._help_collapsed.get(name, False)),
                        'entries': [{'key': k, 'desc': d} for k, d in entries],
                    }
                    for name, entries in sections_list
                ],
            }
        if self._show_name:
            return {
                'type': 'hud_overlay',
                'title': 'HUD OVERLAY',
                'effect': str(self._hud_state.get('effect', '-') or '-'),
                'fps': str(self._hud_state.get('fps', '-') or '-'),
                'display_mode': str(self._hud_state.get('display_mode', '-') or '-'),
            }
        return {}

    @property
    def projectm_manager_focus_pane(self) -> int:
        return self._projectm_focus_pane

    @property
    def flash_messages_enabled(self) -> bool:
        return self._flash_enabled

    def help_section_count(self) -> int:
        return len(self._iter_help_sections())

    def toggle_help_section(self, index: int) -> bool:
        sections = self._iter_help_sections()
        if index < 0 or index >= len(sections):
            return False
        name, _entries = sections[index]
        self._help_collapsed[name] = not self._help_collapsed.get(name, False)
        self._help_focus_idx = index
        return True

    def set_all_help_sections_collapsed(self, collapsed: bool) -> None:
        for name, _entries in self._iter_help_sections():
            self._help_collapsed[name] = collapsed

    def move_help_focus(self, delta: int) -> bool:
        n = self.help_section_count()
        if n <= 0:
            return False
        self._help_focus_idx = (self._help_focus_idx + delta) % n
        return True

    def toggle_help_focus_section(self) -> bool:
        return self.toggle_help_section(self._help_focus_idx)

    def set_effect_shortcuts(self, effects: list[type["BaseEffect"]]) -> None:
        """Build help overlay columns for plain, shifted, ctrl, and alt shortcuts."""
        self._num_shortcuts = []
        self._shift_shortcuts = []
        self._ctrl_shortcuts = []
        self._alt_shortcuts = []
        self._unmapped_effects = []

        names = [cls.NAME for cls in effects]
        for i, key in enumerate(self.NUM_KEYS):
            if i < len(names):
                self._num_shortcuts.append(f"{key} -> {names[i]}")
            else:
                self._num_shortcuts.append(f"{key} -> (none)")

        for i, key in enumerate(self.SHIFT_KEYS):
            idx = 10 + i
            if idx < len(names):
                self._shift_shortcuts.append(f"{key} -> {names[idx]}")
            else:
                self._shift_shortcuts.append(f"{key} -> (none)")

        for i, key in enumerate(self.CTRL_KEYS):
            idx = 20 + i
            if idx < len(names):
                self._ctrl_shortcuts.append(f"{key} -> {names[idx]}")
            else:
                self._ctrl_shortcuts.append(f"{key} -> (none)")

        for i, key in enumerate(self.ALT_KEYS):
            idx = 30 + i
            if idx < len(names):
                self._alt_shortcuts.append(f"{key} -> {names[idx]}")
            else:
                self._alt_shortcuts.append(f"{key} -> (none)")

        if len(names) > 40:
            self._unmapped_effects = names[40:]

    @property
    def unmapped_effects(self) -> list[str]:
        return list(self._unmapped_effects)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def flash_name(self, name: str, duration: float = 3.0) -> None:
        if not self._flash_enabled:
            return
        self._name_text = name
        self._flash_text = f">> {name}"
        self._flash_timer = duration

    def trigger_cta(self) -> None:
        """Advance to the next CTA slot and start the hype animation."""
        self._cta.trigger()

    def trigger_cta_custom(
        self,
        text: str,
        icon: str = '',
        duration: float | None = None,
    ) -> None:
        """Trigger a custom CTA message (used by streaming drop-in ownership)."""
        self._cta.trigger_custom(text, icon, duration)

    def flash_message(self, msg: str, duration: float = 2.0) -> None:
        if not self._flash_enabled:
            return
        msg_text = str(msg)
        msg_duration = float(duration)
        router = self._flash_router
        if callable(router):
            try:
                if bool(router(msg_text, msg_duration)):
                    return
            except Exception:
                pass
        self._flash_text = msg_text
        self._flash_timer = msg_duration

    def set_overlay_banner(
        self,
        enabled: bool,
        current_text: str,
        previous_text: str,
        hold_s: float,
        change_counter: int,
    ) -> None:
        """Set banner overlay state (provider-agnostic; used by any subsystem)."""
        self._banner_enabled = bool(enabled)
        self._banner_hold_s = max(1.0, float(hold_s))
        self._banner_current_text = str(current_text).strip()
        self._banner_previous_text = str(previous_text).strip()
        counter = int(change_counter)
        if not self._banner_enabled or not self._banner_current_text:
            self._banner_timer = 0.0
            self._banner_change_counter = counter
            return
        if counter != self._banner_change_counter:
            self._banner_change_counter = counter
            self._banner_timer = self._banner_hold_s + (self._banner_slide_s() * 2.0)

    def _banner_slide_s(self) -> float:
        """Duration of banner slide animation in seconds."""
        return 0.35

    def _render_banner(self) -> None:
        """Render the generic overlay banner (provider-agnostic)."""
        slide_s = self._banner_slide_s()
        timer = max(0.0, self._banner_timer)
        if timer <= 0.0:
            return

        enter_threshold = self._banner_hold_s + slide_s
        if timer > enter_threshold:
            phase = 1.0 - ((timer - enter_threshold) / slide_s)
        elif timer > slide_s:
            phase = 1.0
        else:
            phase = timer / slide_s
        phase = max(0.0, min(1.0, phase))

        bar_x = 16.0
        bar_w = max(320.0, self._width - 32.0)
        bar_h = 54.0
        bar_y = -bar_h + phase * (bar_h + 12.0)
        bg_a = 0.85 * (0.65 + phase * 0.35)
        edge_a = 0.24 + phase * 0.52
        accent = (0.10, 0.94, 1.00)
        glow = (0.78, 0.38, 1.00)

        self._draw_rect(bar_x, bar_y, bar_w, bar_h, (0.03, 0.06, 0.10, bg_a))
        self._draw_rect(bar_x, bar_y, bar_w, 3.0, (accent[0], accent[1], accent[2], edge_a))
        self._draw_rect(bar_x, bar_y + bar_h - 3.0, bar_w, 3.0, (glow[0], glow[1], glow[2], edge_a * 0.72))
        self._draw_rect(bar_x, bar_y, 5.0, bar_h, (accent[0], accent[1], accent[2], 0.60 + phase * 0.24))
        self._draw_rect(bar_x + bar_w - 5.0, bar_y, 5.0, bar_h, (glow[0], glow[1], glow[2], 0.40 + phase * 0.22))

        title = self._banner_current_text
        previous = self._banner_previous_text
        char_w = float(self._glyph_w) * self._font_scale_norm * 1.85
        left_limit = max(24, int((bar_w * 0.60) / max(1.0, char_w)))
        right_limit = max(16, int((bar_w * 0.36) / max(1.0, char_w)))

        def _clip(text: str, limit: int) -> str:
            if len(text) <= limit:
                return text
            return text[: max(1, limit - 3)].rstrip() + '...'

        title = _clip(title, left_limit)
        previous = _clip(previous, right_limit)
        banner_a = 0.93 * (0.45 + phase * 0.55)
        banner_y = bar_y + 22.0
        self._draw_text(title, bar_x + 18.0, banner_y, scale=1.70, color=(0.14, 0.98, 0.94, banner_a))
        if previous:
            previous_w = len(previous) * char_w
            previous_x = bar_x + bar_w - 18.0 - previous_w
            self._draw_text(previous, previous_x, banner_y, scale=1.70, color=(0.96, 0.86, 1.0, banner_a * 0.96))

        bass = max(0.0, min(1.0, float(self._hud_state.get('bass', '0.00') or '0.0')))
        mid = max(0.0, min(1.0, float(self._hud_state.get('mid', '0.00') or '0.0')))
        treble = max(0.0, min(1.0, float(self._hud_state.get('treble', '0.00') or '0.0')))
        self._draw_audio_reactive_border_bulbs(
            bar_x,
            bar_y,
            bar_w,
            bar_h,
            bass,
            mid,
            treble,
            self._hud_t,
            speed_scale=0.5,
            size_scale=0.5,
        )

    def _rect_border_point(self, x: float, y: float, w: float, h: float, distance: float) -> tuple[float, float]:
        perim = 2.0 * (w + h)
        dist = distance % perim
        if dist < w:
            return x + dist, y
        dist -= w
        if dist < h:
            return x + w, y + dist
        dist -= h
        if dist < w:
            return x + w - dist, y + h
        dist -= w
        return x, y + h - dist

    def _neon_palette_rgb(self, phase: float) -> tuple[float, float, float]:
        palette = (
            (0.88, 0.30, 1.00),
            (0.14, 0.98, 1.00),
            (1.00, 0.28, 0.78),
        )
        weights = [
            max(0.0, math.sin(phase + 0.0)) ** 2,
            max(0.0, math.sin(phase + 2.09439510239)) ** 2,
            max(0.0, math.sin(phase + 4.18879020479)) ** 2,
        ]
        total = max(0.001, weights[0] + weights[1] + weights[2])
        return (
            (palette[0][0] * weights[0] + palette[1][0] * weights[1] + palette[2][0] * weights[2]) / total,
            (palette[0][1] * weights[0] + palette[1][1] * weights[1] + palette[2][1] * weights[2]) / total,
            (palette[0][2] * weights[0] + palette[1][2] * weights[1] + palette[2][2] * weights[2]) / total,
        )

    def _draw_audio_reactive_border_bulbs(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        bass: float,
        mid: float,
        treble: float,
        t: float,
        *,
        speed_scale: float = 1.0,
        size_scale: float = 1.0,
    ) -> None:
        bass = max(0.0, min(1.0, bass))
        mid = max(0.0, min(1.0, mid))
        treble = max(0.0, min(1.0, treble))
        speed_scale = max(0.05, float(speed_scale))
        size_scale = max(0.05, float(size_scale))

        wobble = 0.55 + 0.45 * math.sin(t * 3.1 * speed_scale)
        phase_a = math.fmod(t * (0.16 + treble * 0.05) * speed_scale + bass * 0.7, 1.0)
        phase_b = math.fmod(t * (0.14 + bass * 0.04) * speed_scale + 0.5 + mid * 0.4, 1.0)

        for idx, (orb_phase, orb_bias) in enumerate(((phase_a, 0.0), (phase_b, 1.3))):
            cx, cy = self._rect_border_point(x, y, w, h, orb_phase * 2.0 * (w + h))
            color = self._neon_palette_rgb(t * 1.6 * speed_scale + bass * 5.5 + orb_bias)
            radius = (7.0 + bass * 4.0 + mid * 2.0 + wobble * 1.5 + idx * 0.35) * size_scale
            outer_a = 0.10 + bass * 0.10 + wobble * 0.05
            mid_a = 0.25 + mid * 0.12 + wobble * 0.08
            core_a = 0.56 + treble * 0.18 + wobble * 0.12

            # Layered glow squares approximate a round, bulbous sprite while staying cheap.
            self._draw_rect(cx - radius * 2.0, cy - radius * 2.0, radius * 4.0, radius * 4.0, (color[0], color[1], color[2], outer_a))
            self._draw_rect(cx - radius * 1.25, cy - radius * 1.25, radius * 2.5, radius * 2.5, (color[0], color[1], color[2], mid_a))
            self._draw_rect(cx - radius * 0.70, cy - radius * 0.70, radius * 1.4, radius * 1.4, (1.0, 1.0, 1.0, core_a))

    def toggle_name_overlay(self) -> None:
        self._show_name = not self._show_name
        self._hud_timer = self._hud_timeout_s if (self._show_name and self._hud_auto_hide) else 0.0

    def set_hud_state(self, state: dict[str, str]) -> None:
        """Update the live HUD payload rendered by TAB overlay."""
        self._hud_state.update(state)

    def set_audio_waveform(self, wf: np.ndarray | None) -> None:
        """Store the current PCM waveform for the Spotify progress-bar visualization."""
        self._live_waveform = wf

    def set_system_monitor_audio_provider(
        self,
        provider: Callable[[], dict[str, float]] | None,
    ) -> None:
        """Set optional runtime provider for monitor frame/audio values."""
        self._system_monitor_audio_provider = provider

    def set_system_monitor_tweakables_provider(
        self,
        provider: Callable[[], dict[str, float | None]] | None,
    ) -> None:
        """Set optional runtime provider for monitor tweakable values."""
        self._system_monitor_tweakables_provider = provider

    def toggle_help(self) -> None:
        self._show_help = not self._show_help
        if self._show_help:
            self._help_focus_region = 'sections'
            self._help_focus_idx = 0
            self._help_icon_focus_idx = 0
            self._help_icon_hover_idx = -1
            self._help_icon_hover_pos = None
        self._help_timer = 60.0 if self._show_help else 0.0

    def toggle_flash_messages(self) -> bool:
        """Toggle flash-message notifications on/off; returns new state."""
        self._flash_enabled = not self._flash_enabled
        return self._flash_enabled

    def set_flash_messages_enabled(self, enabled: bool) -> None:
        """Set flash-message notification state explicitly."""
        self._flash_enabled = bool(enabled)

    def toggle_audio_selector(self) -> None:
        self._show_audio = not self._show_audio

    def toggle_midi_selector(self) -> None:
        self._show_midi = not self._show_midi

    def toggle_system_monitor_modal(self) -> None:
        self._show_system_monitor_modal = not self._show_system_monitor_modal

    def toggle_controller_help_modal(self) -> None:
        self._show_controller_help_modal = not self._show_controller_help_modal

    def toggle_projectm_manager(self) -> None:
        self._show_projectm_manager = not self._show_projectm_manager

    def toggle_webcam_editor_modal(self) -> None:
        self._show_webcam_editor_modal = not self._show_webcam_editor_modal

    def set_recording_state(self, active: bool, elapsed_seconds: float = 0.0) -> None:
        self._recording_active = active
        self._recording_elapsed_seconds = elapsed_seconds if active else 0.0

    def render_live_recording_indicator(self) -> None:
        """Draw only the recording indicator for live display after frame capture."""
        self._render_recording_indicator()

    def resize(self, w: int, h: int) -> None:
        self._width = w
        self._height = h
        bucket = self._help_icon_bucket_for_width(w)
        if bucket != self._help_icon_asset_bucket:
            self._help_icon_asset_bucket = bucket
            self._load_help_icon_textures()


    def destroy(self) -> None:
        """Release all GL resources."""
        icon_textures = getattr(self, '_help_icon_textures', None)
        if isinstance(icon_textures, dict):
            for tex in icon_textures.values():
                try:
                    tex.release()
                except Exception:
                    pass
            icon_textures.clear()

        icon_vao = getattr(self, '_icon_vao', None)
        icon_vbo = getattr(self, '_icon_vbo', None)
        icon_prog = getattr(self, '_icon_prog', None)
        if icon_vao is not None:
            icon_vao.release()
        if icon_vbo is not None:
            icon_vbo.release()
        if icon_prog is not None:
            icon_prog.release()

        quad_vao = getattr(self, '_quad_vao', None)
        quad_vbo = getattr(self, '_quad_vbo', None)
        blit_prog = getattr(self, '_blit_prog', None)
        textures = getattr(self, '_textures', None)
        if quad_vao is not None:
            quad_vao.release()
        if quad_vbo is not None:
            quad_vbo.release()
        if blit_prog is not None:
            blit_prog.release()
        if textures is not None:
            for _t in textures:
                _t.release()

    def _ensure_resources(self, ctx: moderngl.Context) -> None:
        """Lazily build GLSL shader and PIL-rendered textures."""
        if self._blit_prog is None:
            vert = """
#version 330
in vec2 in_pos;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    v_uv = in_uv;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""
            frag = """
#version 330
uniform sampler2D iChannel0;
uniform float     iTime;
uniform float     iPhase;
uniform float     iAlpha;
in  vec2 v_uv;
out vec4 fragColor;
void main() {
    float ca  = mix(0.018, 0.004, clamp(iPhase * 2.5, 0.0, 1.0));
    float r   = texture(iChannel0, v_uv + vec2(-ca, 0.0)).r;
    float g   = texture(iChannel0, v_uv).g;
    float b   = texture(iChannel0, v_uv + vec2( ca, 0.0)).b;
    float a   = texture(iChannel0, v_uv).a;
    float cyc  = 0.5 + 0.5 * sin(iTime * 2.8);
    vec3  nA   = vec3(1.0,  0.12, 0.88);
    vec3  nB   = vec3(0.05, 0.95, 1.0);
    vec3  neon = mix(nA, nB, cyc);
    vec3  col  = vec3(r, g, b);
    float lum  = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(col, col * neon * 1.5, 0.45 * lum);
    col *= 0.92 + 0.08 * sin(v_uv.y * 160.0 + iTime * 18.0);
    col *= 0.90 + 0.10 * sin(iTime * 9.2);
    fragColor = vec4(col, a * iAlpha);
}
"""
            self._blit_prog = ctx.program(vertex_shader=vert, fragment_shader=frag)
            self._quad_vbo = ctx.buffer(reserve=6 * 4 * 4)
            self._quad_vao = ctx.vertex_array(
                self._blit_prog,
                [(self._quad_vbo, '2f 2f', 'in_pos', 'in_uv')],
            )

        slots_key = tuple(self._slots)
        if self._textures is not None and self._slots_key == slots_key:
            return

        if self._textures is not None:
            for _t in self._textures:
                _t.release()
        self._textures = []
        self._slots_key = slots_key
        if not _PIL_AVAILABLE:
            return

        text_font = None
        emoji_font = None
        try:
            if self._font_path is not None and self._font_path.exists():
                text_font = ImageFont.truetype(str(self._font_path), size=132)
        except Exception:
            pass
        try:
            icon_font_path = next(
                (p for p in [
                    Path('/usr/share/fonts/gdouros-symbola/Symbola.ttf'),
                    Path('/usr/share/fonts/gdouros-symbola/Symbola.otf'),
                    Path('/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf'),
                    Path('/usr/share/fonts/google-noto-emoji-fonts/NotoColorEmoji.ttf'),
                    Path('/usr/share/fonts/noto-emoji/NotoColorEmoji.ttf'),
                ] if p.exists()),
                None,
            )
            if icon_font_path is not None:
                emoji_font = ImageFont.truetype(str(icon_font_path), size=140)
        except Exception:
            pass

        TEX_W, TEX_H = self._tex_w, self._tex_h
        for text, icon in self._slots:
            try:
                img = self._build_image(text, icon, TEX_W, TEX_H, text_font, emoji_font)
            except Exception:
                log.debug('CTA image render failed for %r; using blank', text, exc_info=True)
                img = Image.new('RGBA', (TEX_W, TEX_H), (0, 0, 0, 0))
            data = np.array(img, dtype=np.uint8)
            tex = ctx.texture((TEX_W, TEX_H), 4, data=data.tobytes())
            tex.filter = moderngl.LINEAR, moderngl.LINEAR
            self._textures.append(tex)

    def _build_image(
        self,
        text: str,
        icon: str,
        width: int,
        height: int,
        text_font: 'ImageFont.FreeTypeFont | None',
        emoji_font: 'ImageFont.FreeTypeFont | None',
    ) -> 'Image.Image':
        """Render one CTA slot to a transparent RGBA PIL image."""
        img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        font = text_font or ImageFont.load_default()
        icon_font = emoji_font or font
        icon_clean = icon.replace('\ufe0f', '').strip()

        bbox_t = draw.textbbox((0, 0), text, font=font)
        tw = bbox_t[2] - bbox_t[0]
        th = bbox_t[3] - bbox_t[1]

        iw, ih = 0, 0
        bbox_i = (0, 0, 0, 0)
        if icon_clean:
            try:
                bbox_i = draw.textbbox((0, 0), icon_clean, font=icon_font)
                iw = bbox_i[2] - bbox_i[0]
                ih = bbox_i[3] - bbox_i[1]
            except Exception:
                icon_clean = ''

        gap = 36 if icon_clean else 0
        total_w = tw + gap + iw
        tx = max(0, (width - total_w) // 2)
        ty = (height - th) // 2

        draw.text((tx - bbox_t[0], ty - bbox_t[1]), text, font=font, fill=(255, 255, 255, 255))

        if icon_clean:
            ix = tx + tw + gap
            iy = ty + (th - ih) // 2
            draw.text((ix - bbox_i[0], iy - bbox_i[1]), icon_clean, font=icon_font, fill=(255, 255, 255, 255))

        return img
