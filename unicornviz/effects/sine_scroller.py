"""
Sine Scroller 2.0 — Multi-line bouncing text with independent sine waves.
Audio-reactive: beat drives color shifts, bass widens amplitudes per line,
treble adds shimmer. Configurable speed, text, and per-line frequency offsets.
Inspired by classic demoscene scrollers with modern polish.
"""
from __future__ import annotations

import math
import numpy as np
import moderngl

from unicornviz.effects.base import BaseEffect, AudioData

_DEFAULT_TEXT = (
    "  *** UNICORN VIZ 2.0 ***   GREETINGS TO ALL THE DEMOSCENERS OUT THERE!   "
    "RAZOR 1911  FUTURE CREW  ACiD PRODUCTIONS  TRITON  THE SILENTS  "
    "CAPACITY  EXCEL  ORANGE JUICE   KEEP THE SCENE ALIVE!   "
)

_VERT_BG = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_FRAG_BG = """
#version 330
uniform float iTime;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
in vec2 v_uv;
out vec4 fragColor;

vec3 palette(float t) {
    vec3 a = vec3(0.5, 0.5, 0.5);
    vec3 b = vec3(0.5, 0.5, 0.5);
    vec3 c = vec3(1.0, 1.0, 1.0);
    vec3 d = vec3(0.263, 0.416, 0.557);
    return a + b * cos(6.28318 * (c * t + d));
}

void main() {
    vec2 uv = v_uv;
    float t = iTime;
    
    // Multi-layer wave system
    float layer1 = sin(uv.y * 24.0 + t * 1.2 + sin(uv.x * 6.0 + t * 0.4));
    float layer2 = sin(uv.x * 18.0 - t * 0.8 + cos(uv.y * 5.0 + t * 0.3));
    float layer3 = sin((uv.x + uv.y) * 14.0 + t * 0.6);
    
    float shimmer = 0.5 + 0.5 * sin((uv.x + uv.y) * 22.0 + t * 1.5);
    float glow = (layer1 * 0.4 + layer2 * 0.35 + layer3 * 0.25) * 0.5 + 0.25;
    
    // Audio-reactive modulation
    float bass_push = iBass * 0.18;
    float mid_color = iMid * 0.12;
    float treble_bright = iTreble * shimmer * 0.15;
    
    float intensity = glow + bass_push + mid_color + treble_bright;
    intensity = clamp(intensity, 0.0, 1.0);
    
    vec3 col = palette(intensity + t * 0.1 + mid_color);
    col += vec3(0.02, 0.01, 0.04) * (1.0 - intensity);
    
    fragColor = vec4(col, 1.0);
}
"""

_VERT_CHAR = """
#version 330
in vec2 in_pos;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    v_uv = in_uv;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

_FRAG_CHAR = """
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

_ATLAS_COLS = 128
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
    NAME = "Sine Scroller 2.0"
    AUTHOR = "Autopilot Revamp"
    TAGS = ["classic", "demoscene", "audio", "futuristic"]

    def _init(self) -> None:
        self.parameters = {
            "speed": 1.8,
            "font_scale": 4.0,
            "amplitude": 0.20,
            "bass_sensitivity": 1.3,
            "beat_intensity": 1.0,
        }
        self._scroll_text = self.config.get("text", _DEFAULT_TEXT)
        self._bg_prog = self._make_program(_VERT_BG, _FRAG_BG)
        self._bg_vao, self._bg_vbo = self._fullscreen_quad(self._bg_prog)
        self._char_prog = self._make_program(_VERT_CHAR, _FRAG_CHAR)
        self._font_tex = _load_font(self.ctx)
        self._vbo = self.ctx.buffer(reserve=1024 * 1024)
        self._vao = self.ctx.simple_vertex_array(
            self._char_prog, self._vbo, "in_pos", "in_uv"
        )
        self._scroll_x = float(self.width)
        self._bass = 0.0
        self._mid = 0.0
        self._treble = 0.0
        self._beat_decay = 0.0
        self._color_phase = 0.0
        self._shake_x = 0.0
        self._shake_y = 0.0

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass * self.parameters["bass_sensitivity"]
        self._mid = audio.mid
        self._treble = audio.treble
        
        # Beat detection with smooth decay
        if audio.beat > 0.5:
            self._beat_decay = self.parameters["beat_intensity"]
        self._beat_decay = max(0.0, self._beat_decay - dt * 5.0)
        
        self._color_phase = (self._color_phase + dt * 0.3) % 1.0
        
        # Bass-driven camera shake with exponential smoothing
        shake_target_x = math.sin(self.time * 11.0) * self._bass * 14.0
        shake_target_y = math.cos(self.time * 13.0 + 1.57) * self._bass * 8.0
        blend = min(1.0, dt * 12.0)
        self._shake_x += (shake_target_x - self._shake_x) * blend
        self._shake_y += (shake_target_y - self._shake_y) * blend
        
        char_w = _CHAR_W * self.parameters["font_scale"]
        self._scroll_x -= dt * self.parameters["speed"] * 140.0
        total_w = len(self._scroll_text) * char_w
        if self._scroll_x < -total_w:
            self._scroll_x = float(self.width)

    def _build_geometry(self) -> tuple[np.ndarray, int]:
        scale = self.parameters["font_scale"]
        amp = (
            self.parameters["amplitude"]
            + self._bass * 0.14
            + self._beat_decay * 0.08
        )
        char_w = _CHAR_W * scale
        char_h = _CHAR_H * scale
        atlas_w = float(_ATLAS_COLS * _CHAR_W)
        
        verts: list[float] = []
        t = self.time
        cx = self._scroll_x + self._shake_x
        
        for i, ch in enumerate(self._scroll_text):
            code = ord(ch) & 0x7F
            
            # Layered sine waves with independent frequencies
            freq_offset = i * 0.28
            y_off = (
                math.sin(t * 2.2 + freq_offset) * amp * 0.6
                + math.sin(t * 1.5 + freq_offset + 0.785) * amp * 0.4
                + math.sin(t * 0.9 + freq_offset + 1.57) * amp * 0.25
            )
            
            cy = self.height * 0.5 - char_h * 0.5 + y_off * self.height + self._shake_y
            
            def px(v: float) -> float:
                return (v / self.width) * 2.0 - 1.0
            
            def py(v: float) -> float:
                return 1.0 - (v / self.height) * 2.0
            
            x0, x1 = px(cx), px(cx + char_w)
            y0, y1 = py(cy), py(cy + char_h)
            
            u0 = (code * _CHAR_W) / atlas_w
            u1 = u0 + _CHAR_W / atlas_w
            v0, v1 = 0.0, 1.0
            
            # Two triangles per character
            verts += [x0, y0, u0, v0,  x1, y0, u1, v0,  x0, y1, u0, v1]
            verts += [x1, y0, u1, v0,  x1, y1, u1, v1,  x0, y1, u0, v1]
            
            cx += char_w
        
        arr = np.array(verts, dtype=np.float32)
        return arr, len(verts) // 4

    def render(self) -> None:
        # Render background with multi-layer waves
        self._bg_prog["iTime"].value = self.time
        self._bg_prog["iBass"].value = self._bass
        self._bg_prog["iMid"].value = self._mid
        self._bg_prog["iTreble"].value = self._treble + self._beat_decay
        self._bg_vao.render(moderngl.TRIANGLE_STRIP)
        
        # Build and render scrolling text
        data, n_verts = self._build_geometry()
        if data.size == 0:
            return
        
        if data.nbytes > self._vbo.size:
            self._vbo.orphan(data.nbytes * 2)
        self._vbo.write(data)
        
        # Cosine-palette driven color cycling with beat modulation
        c = self._color_phase
        r = 0.5 + 0.5 * math.cos(c * 6.28)
        g = 0.5 + 0.5 * math.cos(c * 6.28 + 2.09)
        b = 0.5 + 0.5 * math.cos(c * 6.28 + 4.18)
        brightness = 0.9 + 0.2 * self._beat_decay
        
        self._char_prog["color"].value = (r * brightness, g * brightness, b * brightness, 0.95)
        self._font_tex.use(location=0)
        self._char_prog["font_tex"].value = 0
        
        self.ctx.enable(moderngl.BLEND)
        self._vao.render(moderngl.TRIANGLES, vertices=n_verts)

    def destroy(self) -> None:
        self._bg_vao.release()
        self._bg_vbo.release()
        self._bg_prog.release()
        self._font_tex.release()
        self._vbo.release()
        self._char_prog.release()
