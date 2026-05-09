"""
Sine Scroller — classic bouncing text on multiple sine waves,
with a retro bitmap font and trailing colour fade.
Audio-reactive: beat snaps colour, bass widens the sine amplitude.
"""
from __future__ import annotations

import math
import numpy as np
import moderngl

from unicornviz.effects.base import BaseEffect, AudioData

# Default scroll text — overridable in config
_DEFAULT_TEXT = (
    "  *** UNICORN VIZ ***   GREETINGS TO ALL THE DEMOSCENERS OUT THERE!   "
    "RAZOR 1911  FUTURE CREW  ACiD PRODUCTIONS  TRITON  THE SILENTS  "
    "KEEP THE SCENE ALIVE!   "
)

_VERT = """
#version 330
in vec2 in_pos;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    v_uv = in_uv;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

_FRAG = """
#version 330
uniform sampler2D font_tex;
uniform vec4 color;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    float alpha = texture(font_tex, v_uv).r;
    fragColor = vec4(color.rgb, alpha * color.a);
}
"""

_BG_VERT = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_BG_FRAG = """
#version 330
uniform float iTime;
uniform float iBass;
uniform float iMid;
in vec2 v_uv;
out vec4 fragColor;

void main() {
    vec2 uv = v_uv;
    float t = iTime;

    // Keep this subtle so text remains the focus.
    float wave_a = sin(uv.y * 22.0 + t * 0.8 + sin(uv.x * 5.0 + t * 0.3));
    float wave_b = sin(uv.x * 16.0 - t * 0.55 + cos(uv.y * 4.0 + t * 0.2));
    float shimmer = 0.5 + 0.5 * sin((uv.x + uv.y) * 18.0 + t * 0.9);
    float field = 0.5 + 0.5 * (wave_a * 0.55 + wave_b * 0.45);

    vec3 base = vec3(0.02, 0.01, 0.05);
    vec3 accent = mix(vec3(0.04, 0.08, 0.14), vec3(0.12, 0.06, 0.18), shimmer);
    float motion = field * 0.14 + iMid * 0.06 + iBass * 0.07;
    vec3 col = mix(base, accent, clamp(motion, 0.0, 1.0));

    fragColor = vec4(col, 1.0);
}
"""

# 8×8 font atlas: 128 chars wide × 8 rows, same layout as overlays.py
_ATLAS_COLS = 128
_ATLAS_ROWS = 1
_CHAR_W = 8
_CHAR_H = 8


def _load_font(ctx: moderngl.Context) -> moderngl.Texture:
    from pathlib import Path
    atlas_w = _ATLAS_COLS * _CHAR_W
    data = np.zeros((_CHAR_H, atlas_w), dtype=np.uint8)
    font_path = Path("assets/fonts/font8x8.bin")
    if font_path.exists():
        raw = font_path.read_bytes()
        for cp in range(min(128, len(raw) // 8)):
            for row in range(8):
                byte = raw[cp * 8 + row]
                for col in range(8):
                    if byte & (0x80 >> col):
                        data[row, cp * 8 + col] = 255
    else:
        for cp in range(32, 128):
            for row in range(8):
                for col in range(8):
                    if (row + col) % 2 == 0:
                        data[row, cp * 8 + col] = 160
    tex = ctx.texture((atlas_w, _CHAR_H), 1, data=data.tobytes())
    tex.filter = moderngl.NEAREST, moderngl.NEAREST
    return tex


class SineScroller(BaseEffect):
    NAME = "Sine Scroller"
    AUTHOR = "unicorn-viz"
    TAGS = ["classic", "demoscene", "audio"]

    def _init(self) -> None:
        self.parameters = {"speed": 1.5, "amplitude": 0.18, "font_scale": 4.0}
        self._scroll_text = self.config.get("text", _DEFAULT_TEXT)
        self._bg_prog = self._make_program(_BG_VERT, _BG_FRAG)
        self._bg_vao, self._bg_vbo = self._fullscreen_quad(self._bg_prog)
        self._prog = self._make_program(_VERT, _FRAG)
        self._font_tex = _load_font(self.ctx)
        self._vbo = self.ctx.buffer(reserve=1024 * 1024)
        self._vao = self.ctx.simple_vertex_array(
            self._prog, self._vbo, "in_pos", "in_uv"
        )
        self._scroll_x = float(self.width)
        self._bass = 0.0
        self._mid = 0.0
        self._beat_flash = 0.0
        self._color_phase = 0.0
        self._shake_x = 0.0
        self._shake_y = 0.0

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass
        self._mid = audio.mid
        if audio.beat > 0.5:
            self._beat_flash = 1.0
        self._beat_flash = max(0.0, self._beat_flash - dt * 3.0)
        self._color_phase = (self._color_phase + dt * 0.5) % 1.0

        # Bass-driven camera shake with smoothing to avoid jitter.
        shake_target_x = math.sin(self.time * 13.0) * self._bass * 18.0
        shake_target_y = math.cos(self.time * 17.0 + 1.2) * self._bass * 10.0
        blend = min(1.0, dt * 10.0)
        self._shake_x += (shake_target_x - self._shake_x) * blend
        self._shake_y += (shake_target_y - self._shake_y) * blend

        char_w = _CHAR_W * self.parameters["font_scale"]
        self._scroll_x -= dt * self.parameters["speed"] * 120.0
        # Wrap when last character has scrolled off left
        total_w = len(self._scroll_text) * char_w
        if self._scroll_x < -total_w:
            self._scroll_x = float(self.width)

    def _build_geometry(self) -> tuple[np.ndarray, int]:
        scale = self.parameters["font_scale"]
        amp = self.parameters["amplitude"] + self._bass * 0.1
        char_w = _CHAR_W * scale
        char_h = _CHAR_H * scale
        atlas_w = float(_ATLAS_COLS * _CHAR_W)

        verts: list[float] = []
        t = self.time
        cx = self._scroll_x + self._shake_x

        for i, ch in enumerate(self._scroll_text):
            code = ord(ch) & 0x7F
            # Sine Y offset — two overlapping sines for organic feel
            y_off = (
                math.sin(t * 2.0 + i * 0.35) * amp
                + math.sin(t * 1.3 + i * 0.22) * amp * 0.4
            )
            # Centre of screen + offset
            cy = self.height * 0.5 - char_h * 0.5 + y_off * self.height + self._shake_y

            # NDC conversion
            def px(v: float) -> float:
                return (v / self.width) * 2.0 - 1.0

            def py(v: float) -> float:
                return 1.0 - (v / self.height) * 2.0

            x0 = px(cx)
            x1 = px(cx + char_w)
            y0 = py(cy)
            y1 = py(cy + char_h)

            u0 = (code * _CHAR_W) / atlas_w
            u1 = u0 + _CHAR_W / atlas_w
            v0, v1 = 0.0, 1.0

            verts += [x0, y0, u0, v0,  x1, y0, u1, v0,  x0, y1, u0, v1]
            verts += [x1, y0, u1, v0,  x1, y1, u1, v1,  x0, y1, u0, v1]

            cx += char_w

        arr = np.array(verts, dtype=np.float32)
        return arr, len(verts) // (2 + 2)  # 4 floats per vertex

    def render(self) -> None:
        self._bg_prog["iTime"].value = self.time
        self._bg_prog["iBass"].value = self._bass
        self._bg_prog["iMid"].value = self._mid
        self._bg_vao.render(moderngl.TRIANGLE_STRIP)

        data, n_verts = self._build_geometry()
        if data.size == 0:
            return
        if data.nbytes > self._vbo.size:
            self._vbo.orphan(data.nbytes * 2)
        self._vbo.write(data)

        # Rainbow colour cycling
        c = self._color_phase
        r = 0.5 + 0.5 * math.sin(c * 6.28)
        g = 0.5 + 0.5 * math.sin(c * 6.28 + 2.09)
        b = 0.5 + 0.5 * math.sin(c * 6.28 + 4.18)
        br = 0.85 + 0.15 * self._beat_flash

        self._prog["color"].value = (r * br, g * br, b * br, 1.0)
        self._font_tex.use(location=0)
        self._prog["font_tex"].value = 0
        self.ctx.enable(moderngl.BLEND)
        self._vao.render(moderngl.TRIANGLES, vertices=n_verts)

    def destroy(self) -> None:
        self._bg_vao.release()
        self._bg_vbo.release()
        self._bg_prog.release()
        self._font_tex.release()
        self._vbo.release()
        self._prog.release()
