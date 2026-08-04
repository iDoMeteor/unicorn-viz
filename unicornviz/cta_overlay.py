"""Call-to-action (CTA) hype overlay.

Self-contained animated overlay that cycles three social call-to-action
messages ("Push the buttons!", etc.), triggered by the streaming-owned CTA
hotkey path (defaults to F9).  Extracted from :mod:`unicornviz.overlays` so the
parent ``Overlays`` class does not own any CTA-specific GL resources.

The ``CTAOverlay`` symbol and the ``_CTA_SHOW_DURATION`` / ``_CTA_SLOTS`` defaults
are imported by ``unicornviz.overlays`` and wired into ``Overlays.__init__``.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Callable

import moderngl
import numpy as np

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except Exception:
    _PIL_AVAILABLE = False

log = logging.getLogger(__name__)

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
            from unicornviz.fonts import load_emoji_font
            emoji_font = load_emoji_font(140)
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
