"""
ANSI Viewer — loads .ANS files from assets/ansi/, renders them with a
CRT/phosphor glow post-processing shader.  Scrolls through files on the
playlist and supports slow auto-scroll within tall art.

Audio-reactive:
  - beat flashes the phosphor glow
  - bass slightly warps the CRT curvature
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import moderngl

from unicornviz.effects.base import BaseEffect, AudioData
from unicornviz.ansi.loader import ANSIParser
from unicornviz.ansi.font import build_font_atlas
from unicornviz.ansi.renderer import canvas_to_texture

log = logging.getLogger(__name__)

# Baseline UV scroll rate for ANSI art auto-scroll.
# Increased by 20% so default ANSI playback moves a bit faster.
_BASE_SCROLL_RATE = 0.0144

# ── Vertex / fragment shaders ─────────────────────────────────────────────────

_VERT = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    // Flip Y so row 0 of the texture (top of art) appears at the screen top
    v_uv = vec2(in_vert.x * 0.5 + 0.5, 0.5 - in_vert.y * 0.5);
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_FRAG = """
#version 330
uniform sampler2D ansi_tex;
uniform float     iTime;
uniform float     iScrollUV;  // UV-space top of viewport (0..1-iWindowH)
uniform float     iWindowH;   // fraction of texture height that fits on screen
uniform float     iBass;
uniform float     iBeat;
uniform float     iGlow;
uniform float     iCRT;
uniform vec2      iResolution;

in  vec2 v_uv;
out vec4 fragColor;

vec2 crt_uv(vec2 uv) {
    vec2 cc = uv * 2.0 - 1.0;
    float dist = dot(cc, cc);
    float warp = iCRT * (1.0 + iBass * 0.05);
    cc *= 1.0 + dist * warp * 0.1;
    return cc * 0.5 + 0.5;
}

void main() {
    // Map screen UV into the scrolling window of the texture
    vec2 uv = v_uv;
    uv.y = iScrollUV + uv.y * iWindowH;

    // CRT barrel warp
    vec2 cuv = crt_uv(uv);

    if (cuv.x < 0.0 || cuv.x > 1.0 || cuv.y < 0.0 || cuv.y > 1.0) {
        fragColor = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }

    vec3 col = texture(ansi_tex, cuv).rgb;

    // Scanlines
    float scan = 1.0 - 0.18 * sin(cuv.y * iResolution.y * 3.14159 * 2.0);
    col *= scan;

    // Phosphor glow
    if (iGlow > 0.01) {
        vec2 px = vec2(1.0) / iResolution;
        vec3 glow =
            texture(ansi_tex, cuv + vec2( px.x * 2.0, 0.0)).rgb * 0.15 +
            texture(ansi_tex, cuv + vec2(-px.x * 2.0, 0.0)).rgb * 0.15 +
            texture(ansi_tex, cuv + vec2(0.0,  px.y * 2.0)).rgb * 0.10 +
            texture(ansi_tex, cuv + vec2(0.0, -px.y * 2.0)).rgb * 0.10;
        col += glow * iGlow * (1.0 + iBeat * 0.8);
    }

    // Vignette
    vec2 vc = cuv * 2.0 - 1.0;
    float vig = 1.0 - dot(vc, vc) * 0.25;
    col *= vig;

    col.g = mix(col.g, col.g * 1.05, iCRT * 0.3);

    float flicker = 0.97 + 0.03 * fract(sin(iTime * 7.3 + 1.5) * 4375.5);
    col *= flicker;

    col *= 1.0 + iBeat * 0.15;

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""


class ANSIViewer(BaseEffect):
    NAME = "ANSI Viewer"
    AUTHOR = "unicorn-viz"
    TAGS = ["ansi", "classic", "audio"]

    def _init(self) -> None:
        self.parameters = {
            "speed":     1.0,   # scroll speed multiplier
            "glow":      0.6,   # phosphor glow intensity
            "crt":       0.7,   # CRT barrel distortion
            "slide_time": 15.0, # seconds per file
            "cycle_files": 0.0, # 0 = stay on current file, 1 = cycle files
        }

        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()

        self._font_atlas = build_font_atlas(self.ctx)
        self._parser = ANSIParser()

        # Load all .ANS files from configured directory/directories
        raw_dir = self.config.get("ansi_dir", "assets/ansi")
        dirs = [d.strip() for d in str(raw_dir).split(",")]
        self._files: list[Path] = []
        for d in dirs:
            p = Path(d)
            self._files += sorted(p.glob("*.ans")) + sorted(p.glob("*.ANS"))
        if not self._files:
            log.warning("No .ANS files found in %s", raw_dir)
        else:
            import random as _random
            _random.shuffle(self._files)

        self._file_idx = 0
        self._ansi_tex: moderngl.Texture | None = None
        self._scroll = 0.0
        self._slide_timer = 0.0
        self._bass = 0.0
        self._beat = 0.0
        self._title = ""
        self._window_h_uv = 1.0

        self._load_current()

    def _load_current(self) -> None:
        if not self._files:
            self._ansi_tex = self._make_fallback_tex()
            self._title = "No .ANS files found"
            return

        path = self._files[self._file_idx % len(self._files)]
        try:
            raw = path.read_bytes()
            canvas = self._parser.parse(raw)
            if self._ansi_tex is not None:
                self._ansi_tex.release()
            self._ansi_tex = canvas_to_texture(self.ctx, canvas, self._font_atlas)
            info = getattr(canvas, "_sauce", {})
            title = info.get("title", "") or path.stem
            self._title = title
            log.info("ANSI Viewer loaded: %s (%dx%d)", path.name, canvas.width, canvas.height)
        except Exception as exc:
            log.warning("Failed to load %s: %s", path, exc)
            self._ansi_tex = self._make_fallback_tex()
            self._title = f"Error: {path.name}"
        self._scroll = 0.0

    def _make_fallback_tex(self) -> moderngl.Texture:
        """1×1 black texture as placeholder."""
        tex = self.ctx.texture((1, 1), 4, data=bytes([0, 0, 0, 255]))
        return tex

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass
        if audio.beat > 0.5:
            self._beat = 1.0
        self._beat = max(0.0, self._beat - dt * 4.0)

        # Scroll within current file
        self._scroll += dt * _BASE_SCROLL_RATE * self.parameters["speed"]
        self._scroll %= 1.0

        # Optional internal file cycling (disabled by default).
        if float(self.parameters.get("cycle_files", 0.0)) > 0.5:
            self._slide_timer += dt
            if self._slide_timer >= self.parameters["slide_time"] and self._files:
                self._slide_timer = 0.0
                self._file_idx = (self._file_idx + 1) % len(self._files)
                self._load_current()

    def render(self) -> None:
        if self._ansi_tex is None:
            return
        # Compute UV window height: scale art to fill screen width, then
        # the visible portion of the texture height is screen_h / (screen_w / tex_w)
        tex_w, tex_h = self._ansi_tex.size
        scale = self.width / tex_w if tex_w > 0 else 1.0
        visible_h = self.height / scale
        window_h = min(1.0, visible_h / tex_h) if tex_h > 0 else 1.0
        self._window_h_uv = window_h
        scroll_uv = self._scroll * max(0.0, 1.0 - window_h)

        self._prog["iTime"].value = self.time
        self._prog["iScrollUV"].value = scroll_uv
        self._prog["iWindowH"].value = window_h
        self._prog["iBass"].value = self._bass
        self._prog["iBeat"].value = self._beat
        self._prog["iGlow"].value = self.parameters["glow"]
        self._prog["iCRT"].value  = self.parameters["crt"]
        self._prog["iResolution"].value = (float(self.width), float(self.height))
        self._ansi_tex.use(location=0)
        self._prog["ansi_tex"].value = 0
        self._vao.render(moderngl.TRIANGLE_STRIP)

    @property
    def current_title(self) -> str:
        return self._title

    @property
    def reached_bottom(self) -> bool:
        # If art fits in viewport, it's effectively already complete.
        if self._window_h_uv >= 0.999:
            return True
        return self._scroll >= 0.995

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
        self._font_atlas.release()
        if self._ansi_tex is not None:
            self._ansi_tex.release()
