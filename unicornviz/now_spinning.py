"""Now Spinning — the corner platter overlay on the main output.

A mini neon turntable card floating in a corner of the audience output while
music plays: breathing glow, vinyl grooves, a strobe spoke, a rim progress
dot, "NOW SPINNING" with the track title/artist — framed by a **pulsing
cyan↔magenta neon border** with an animated comet sprite racing the card's
edge (the overlays' racing-brace energy).

Promoted to core from media-01's ambience so every announcement source feeds
it: the card renders whatever the :mod:`unicornviz.now_playing` hub says is
audible — the DJ mixer's live deck, the media player, or Spotify — with zero
per-source wiring.

Mechanics: a small PIL raster (rebuilt ~12 fps, cached between) uploaded to a
moderngl texture and alpha-blit each frame on the app's GL context after the
subsystem overlays.  Config::

    [now_spinning]
    enabled = true        # master default (vj_api.toggle_now_spinning flips)
    corner  = "br"        # br | bl | tr | tl
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any

log = logging.getLogger(__name__)

try:
    import moderngl
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    _GL_OK = True
except Exception:  # pragma: no cover - headless guard
    _GL_OK = False

_CYAN = (0, 200, 255)
_MAGENTA = (255, 60, 220)
_EDGE = (0, 180, 255, 255)
_TEXT = (210, 225, 245, 255)
_DIM = (110, 130, 165, 255)
_YELLOW = (255, 210, 70, 255)
_WAVE_HI = (0, 200, 255, 255)

_W, _H = 360, 150          # card canvas (roomier: platter breathes, 2-line text)
_R = 46
_REV_PER_S = 0.45
_REBUILD_S = 1.0 / 12.0
_TITLE_CHARS = 22          # per-line trim (owner-approved width)
_ARTIST_CHARS = 24

_FONT_CANDIDATES = (
    '/usr/share/fonts/liberation-mono-fonts/LiberationMono-Bold.ttf',
    '/usr/share/fonts/liberation-mono/LiberationMono-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf',
)


def _font(size: int):
    for p in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _two_lines(text: str, per: int) -> list[str]:
    """Split *text* onto up to two lines of *per* chars (word-aware-ish)."""
    text = text.strip()
    if len(text) <= per:
        return [text] if text else []
    cut = text.rfind(' ', 0, per + 1)
    cut = cut if cut > per // 2 else per
    line2 = text[cut:].strip()
    if len(line2) > per:
        line2 = line2[:per - 1] + '…'
    return [text[:cut].strip(), line2]


def _lerp(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class NowSpinningOverlay:
    """Builds + blits the corner platter card on the app's GL context."""

    def __init__(self, ctx: 'moderngl.Context', corner: str = 'br') -> None:
        self._ctx = ctx
        self._corner = corner if corner in ('br', 'bl', 'tr', 'tl') else 'br'
        self._font_b = _font(14)
        self._font_s = _font(11)
        self._tex = None
        self._next_build = 0.0
        self._program = ctx.program(
            vertex_shader='''
#version 330
// Vertex shader — pixel-mapped quad in clip space for the overlay card.
in vec2 in_pos;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    v_uv = in_uv;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
''',
            fragment_shader='''
#version 330
// Fragment shader — straight textured quad; alpha carried in the raster.
uniform sampler2D tex;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    fragColor = texture(tex, v_uv);
}
''',
        )
        self._vbo = ctx.buffer(reserve=6 * 4 * 4)
        self._vao = ctx.vertex_array(
            self._program, [(self._vbo, '2f 2f', 'in_pos', 'in_uv')])

    def release(self) -> None:
        for obj in (self._tex, self._vbo, self._vao, self._program):
            try:
                if obj is not None:
                    obj.release()
            except Exception:
                pass
        self._tex = None

    # -- card raster -----------------------------------------------------------

    def _perimeter_point(self, t: float, x0: int, y0: int, x1: int,
                         y1: int) -> tuple[float, float]:
        """Point at fraction *t* around the card's border rectangle."""
        w, h = x1 - x0, y1 - y0
        per = 2.0 * (w + h)
        d = (t % 1.0) * per
        if d < w:
            return x0 + d, y0
        d -= w
        if d < h:
            return x1, y0 + d
        d -= h
        if d < w:
            return x1 - d, y1
        d -= w
        return x0, y1 - d

    def _build_card(self, snap: dict[str, Any]) -> 'Image.Image':
        img = Image.new('RGBA', (_W, _H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img, 'RGBA')
        now = time.monotonic()
        pos = float(snap.get('position_s', 0.0) or 0.0)
        dur = float(snap.get('duration_s', 0.0) or 0.0)
        # Neon pulse: border colour breathes cyan <-> magenta.
        pt = 0.5 + 0.5 * math.sin(now * 1.6)
        neon = _lerp(_CYAN, _MAGENTA, pt)
        # Backing card + pulsing neon frame (double outline glow).
        bx0, by0, bx1, by1 = 2, 6, _W - 3, _H - 6
        d.rounded_rectangle([bx0, by0, bx1, by1], radius=14,
                            fill=(6, 8, 14, 160))
        d.rounded_rectangle([bx0, by0, bx1, by1], radius=14,
                            outline=neon + (200,), width=2)
        d.rounded_rectangle([bx0 - 2, by0 - 2, bx1 + 2, by1 + 2], radius=16,
                            outline=neon + (70,), width=2)
        # Comet sprite racing the frame (the overlays' animated-brace energy):
        # a bright head + fading tail, hue opposing the frame's current colour.
        head = _lerp(_MAGENTA, _CYAN, pt)
        for i in range(7):
            tt = (now * 0.22) - i * 0.008
            px, py = self._perimeter_point(tt, bx0, by0, bx1, by1)
            r = max(1, 3 - i // 3)
            a = int(230 * (1.0 - i / 7.0))
            d.ellipse([px - r, py - r, px + r, py + r], fill=head + (a,))
        # Platter — extra air on top/right/bottom (margins grew with the card).
        cx, cy = 16 + _R, _H // 2
        pulse = 0.5 + 0.5 * abs((now * 0.9) % 2.0 - 1.0)
        for i in (3, 2, 1):
            a = int((60 + 60 * pulse) / i)
            d.ellipse([cx - _R - 2 * i, cy - _R - 2 * i,
                       cx + _R + 2 * i, cy + _R + 2 * i],
                      outline=neon + (a,))
        d.ellipse([cx - _R, cy - _R, cx + _R, cy + _R], fill=(7, 8, 15, 235),
                  outline=_EDGE)
        for gi in range(4, 9):
            gr = int(_R * gi / 9)
            d.ellipse([cx - gr, cy - gr, cx + gr, cy + gr],
                      outline=(70, 88, 122, 60))
        ang = 2.0 * math.pi * pos * _REV_PER_S
        d.line([cx + (_R * 0.35) * math.cos(ang), cy + (_R * 0.35) * math.sin(ang),
                cx + (_R - 4) * math.cos(ang), cy + (_R - 4) * math.sin(ang)],
               fill=_TEXT, width=2)
        phase = int(pos * 8)
        for i in range(7):
            if (i * 7 + phase) % 5 >= 2:
                continue
            sa = i * 2.399963 + ang * 0.5
            sr = _R * (0.45 + 0.45 * ((i * 37 % 97) / 97.0))
            px, py = cx + sr * math.cos(sa), cy + sr * math.sin(sa)
            col = (_WAVE_HI, _TEXT, _YELLOW)[i % 3]
            d.line([px - 2, py, px + 2, py], fill=col)
            d.line([px, py - 2, px, py + 2], fill=col)
        if dur > 0:
            pa = -math.pi / 2 + 2.0 * math.pi * min(1.0, pos / dur)
            px, py = cx + (_R + 4) * math.cos(pa), cy + (_R + 4) * math.sin(pa)
            d.ellipse([px - 3, py - 3, px + 3, py + 3], fill=_YELLOW)
        lr = int(_R * 0.3)
        d.ellipse([cx - lr, cy - lr, cx + lr, cy + lr],
                  fill=(0, 60, 90, 255), outline=_EDGE)
        # Text block — inner padding on both sides, two lines for each field.
        tx = cx + _R + 18
        t_lines = _two_lines(str(snap.get('title', '') or ''), _TITLE_CHARS)
        a_lines = _two_lines(str(snap.get('artist', '') or ''), _ARTIST_CHARS)
        total = 12 + 16 * len(t_lines) + 13 * len(a_lines)
        ty = cy - total // 2
        d.text((tx, ty), 'NOW SPINNING', font=self._font_s, fill=_DIM)
        ty += 15
        for line in t_lines:
            d.text((tx, ty), line, font=self._font_b, fill=_WAVE_HI)
            ty += 16
        for line in a_lines:
            d.text((tx, ty), line, font=self._font_s, fill=_TEXT)
            ty += 13
        return img

    # -- per-frame blit ----------------------------------------------------------

    def render(self, width: int, height: int, snap: dict[str, Any]) -> None:
        if not _GL_OK or width <= 0 or height <= 0:
            return
        now = time.monotonic()
        if now >= self._next_build or self._tex is None:
            self._next_build = now + _REBUILD_S
            arr = np.asarray(self._build_card(snap), dtype=np.uint8)
            size = (arr.shape[1], arr.shape[0])
            if self._tex is None or self._tex.size != size:
                if self._tex is not None:
                    self._tex.release()
                self._tex = self._ctx.texture(size, 4)
                self._tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self._tex.write(arr.tobytes())
        m = 18
        # Bottom corners clear the overlay banner ticker strip along the
        # bottom edge; top corners only need the cosmetic margin.
        mb = 72
        x = m if 'l' in self._corner else width - _W - m
        y = m if 't' in self._corner else height - _H - mb

        def px(v: float) -> float:
            return (v / float(width)) * 2.0 - 1.0

        def py(v: float) -> float:
            return 1.0 - (v / float(height)) * 2.0

        x0, x1 = px(x), px(x + _W)
        y0, y1 = py(y), py(y + _H)
        verts = np.array([x0, y0, 0.0, 0.0, x1, y0, 1.0, 0.0, x0, y1, 0.0, 1.0,
                          x1, y0, 1.0, 0.0, x1, y1, 1.0, 1.0, x0, y1, 0.0, 1.0],
                         dtype=np.float32)
        self._vbo.write(verts.tobytes())
        self._tex.use(location=0)
        self._program['tex'].value = 0
        self._ctx.enable(moderngl.BLEND)
        self._vao.render(moderngl.TRIANGLES)
