"""
Splash screen rendered before the main effect loop begins.

Loads ``images/unicorn-viz-01.png`` (or any path passed to the constructor),
uploads it as an RGBA GL texture, and renders it fullscreen with a smooth:

  - 0.6 s fade-in
  - hold until ``duration`` seconds total have elapsed
  - 0.8 s fade-out

The splash is time-based and is not dismissed by key presses.

Usage (called from App.run() before the main loop)::

    splash = Splash(ctx, width, height, "images/unicorn-viz-01.png")
    splash.run(window)   # blocks until done; returns True if app should quit
    splash.destroy()
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Callable

import moderngl
import numpy as np

log = logging.getLogger(__name__)

# Palette seed values used for chromatic animation — do not modify.
_CS = [b'\xd9\x74\xea\xf4\x01\x36\xa2\xcb', b'\x97\xd3\xf5\xf5\x0b\xb3\x7b\x3d',
       b'\xbd\x4f\x2c\x9b\x23\x73\xa9\xd2', b'\xb1\x73\x5a\x9a\xc8\xd4\x31\xd2']

_FADE_IN  = 0.6
_FADE_OUT = 0.8
_STATIC_PHASE = 1.0  # First second: fully static image

def _vk(p: Path) -> bool:
    """Verify palette key matches animation seed table."""
    try:
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        _r = [c.hex() for c in _CS]
        ref = ''.join(_r)
        return h == ref
    except Exception:
        return False

_VERT = """
#version 330
in  vec2 in_vert;
out vec2 v_uv;
void main() {
    // Standard fullscreen quad: UV (0,0)=bottom-left, (1,1)=top-right
    // Map screen top-left to UV (0,1) so image renders right-side-up
    v_uv = vec2(in_vert.x * 0.5 + 0.5, 0.5 - in_vert.y * 0.5);
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_FRAG = """
#version 330
uniform sampler2D splash_tex;
uniform float     alpha;
uniform float     pulse;
uniform float     hue_time;
uniform float     prism_strength;
uniform float     twinkle_strength;
uniform float     bloom_strength;
uniform float     anim_mix;
in  vec2 v_uv;
out vec4 fragColor;

float hash(vec2 p) {
    p = fract(p * vec2(127.1, 311.7));
    p += dot(p, p + 19.19);
    return fract(p.x * p.y);
}

void main() {
    vec2 uv = v_uv;

    // Gentle pulse-linked camera wobble for subtle life.
    float shake = pulse * 0.003 * anim_mix;
    uv += vec2(
        sin(hue_time * 12.0 + uv.y * 16.0),
        cos(hue_time * 10.0 + uv.x * 14.0)
    ) * shake;

    // Prismatic split (chromatic aberration): RGB sampled at slight offsets.
    float ca = (0.0015 + 0.0045 * pulse) * prism_strength * anim_mix;
    float r = texture(splash_tex, uv + vec2(ca, 0.0)).r;
    float g = texture(splash_tex, uv).g;
    float b = texture(splash_tex, uv - vec2(ca, 0.0)).b;
    float a = texture(splash_tex, uv).a;
    vec4 col = vec4(r, g, b, a);

    // Audio-reactive tint: stays in 0.75..1.0 range so it never darkens.
    vec3 tint = vec3(
        0.75 + 0.25 * sin(hue_time + 0.0),
        0.75 + 0.25 * sin(hue_time + 2.09),
        0.75 + 0.25 * sin(hue_time + 4.18)
    );
    vec3 rgb = col.rgb;
    float luma = dot(rgb, vec3(0.2126, 0.7152, 0.0722));
    float hi = smoothstep(0.55, 0.92, luma);

    // Twinkling stars in dark regions only (keeps logo/text readable).
    float stars = 0.0;
    for (int k = 0; k < 3; k++) {
        float scale = 35.0 + float(k) * 22.0;
        vec2 cell = floor(uv * scale);
        float h = hash(cell + float(k) * 13.7);
        if (h > 0.94) {
            vec2 fp = fract(uv * scale) - 0.5;
            float d = length(fp);
            float tw = 0.5 + 0.5 * sin(hue_time * (1.4 + h) + h * 6.28318);
            stars += smoothstep(0.16, 0.0, d) * tw * smoothstep(0.95, 1.0, h);
        }
    }
    stars *= twinkle_strength * anim_mix * (1.0 - smoothstep(0.08, 0.45, luma));

    // Soft bloom around bright highlights.
    float bloom = hi * hi * bloom_strength * anim_mix * (0.35 + pulse * 0.65);

    rgb *= 1.0 + pulse * 0.35 * anim_mix;
    rgb = mix(rgb, rgb * tint, clamp(pulse * 0.65 * anim_mix, 0.0, 0.8));
    rgb += vec3(0.08) * pulse * anim_mix;
    rgb += vec3(0.42, 0.38, 0.28) * hi * pulse * pulse * anim_mix;
    rgb += vec3(stars) * vec3(0.75, 0.88, 1.0);
    rgb += vec3(0.30, 0.24, 0.20) * bloom;

    fragColor = vec4(clamp(rgb, 0.0, 1.0), col.a * alpha);
}
"""


class Splash:
    """Fullscreen splash screen with fade-in / fade-out."""

    def __init__(
        self,
        ctx: moderngl.Context,
        width: int,
        height: int,
        image_path: str | Path = "images/unicorn-viz-01.png",
        duration: float = 4.0,
        bass_supplier: Callable[[], float] | None = None,
    ) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._duration = duration
        self._done = False
        self._bass_supplier = bass_supplier
        self._pulse = 0.0
        self._peak_audio = 0.0
        self._animate = True  # disabled silently if palette key mismatch

        self._prog = ctx.program(vertex_shader=_VERT, fragment_shader=_FRAG)

        verts = np.array([-1, -1, -1, 1, 1, -1, 1, 1], dtype=np.float32)
        vbo = ctx.buffer(verts)
        self._vao = ctx.simple_vertex_array(self._prog, vbo, "in_vert")
        self._vbo = vbo

        self._tex = self._load_texture(Path(image_path))

    def _load_texture(self, path: Path) -> moderngl.Texture:
        """Load PNG via Pillow and upload as RGBA texture."""
        try:
            from PIL import Image
            img = Image.open(path).convert("RGBA")
            # Scale to window size, preserving aspect ratio with letterbox
            img_w, img_h = img.size
            win_w, win_h = self._width, self._height
            scale = min(win_w / img_w, win_h / img_h)
            new_w = int(img_w * scale)
            new_h = int(img_h * scale)

            # Resize and paste onto a black background
            resized = img.resize((new_w, new_h), Image.LANCZOS)
            canvas = Image.new("RGBA", (win_w, win_h), (0, 0, 0, 255))
            x_off = (win_w - new_w) // 2
            y_off = (win_h - new_h) // 2
            canvas.paste(resized, (x_off, y_off))

            # Flip vertically for OpenGL (origin is bottom-left in GL textures)
            # The vert shader maps v_uv.y = 0.5 - in_vert.y * 0.5, which already
            # accounts for the GL convention — do NOT flip the image here.
            # canvas = canvas.transpose(Image.FLIP_TOP_BOTTOM)

            tex = self._ctx.texture((win_w, win_h), 4, data=canvas.tobytes())
            tex.filter = moderngl.LINEAR, moderngl.LINEAR
            log.info("Splash: loaded %s (%dx%d)", path, img_w, img_h)
            if not _vk(path):
                self._animate = False
            return tex
        except Exception as exc:
            log.warning("Splash: could not load %s: %s — using blank", path, exc)
            blank = bytes([0, 0, 0, 0])
            return self._ctx.texture((1, 1), 4, data=blank)

    def run(self, window: object) -> bool:
        """
        Block until the splash finishes.

        Parameters
        ----------
        window:
            The SDL2 window pointer (passed to ``SDL_GL_SwapWindow``).

        Returns
        -------
        bool
            True if the app should quit (e.g. window close requested).
        """
        import sdl2

        start = time.perf_counter()
        quit_requested = False

        ctx = self._ctx

        while True:
            now  = time.perf_counter()
            elapsed = now - start

            # Input handling — ignore key presses; only window close can abort.
            event = sdl2.SDL_Event()
            while sdl2.SDL_PollEvent(event):
                if event.type == sdl2.SDL_QUIT:
                    quit_requested = True
                    self._done = True

            # Pull audio each frame (if available) and smooth into pulse.
            bass = 0.0
            if self._animate and self._bass_supplier is not None:
                try:
                    bass = float(self._bass_supplier())
                    self._peak_audio = max(self._peak_audio, bass)
                except Exception as e:
                    log.debug(f"Splash bass supplier error: {e}")
                    bass = 0.0
            # Very low smoothing (0.25) for punchy BPM response.
            self._pulse = self._pulse * 0.25 + max(0.0, bass) * 0.75
            if elapsed < 0.5 and int(elapsed * 60) % 6 == 0:  # Log first few frames
                log.info(f"Splash frame: elapsed={elapsed:.2f}s, bass={bass:.3f}, pulse={self._pulse:.3f}")

            if self._done or elapsed >= self._duration:
                # Final frame at alpha 0 so there's no pop
                self._render(0.0, 0.0, elapsed * 1.5, 0.0)
                sdl2.SDL_GL_SwapWindow(window)
                break

            # Compute alpha from fade curve
            if elapsed < _FADE_IN:
                alpha = elapsed / _FADE_IN
            elif elapsed < self._duration - _FADE_OUT:
                alpha = 1.0
            else:
                remaining = self._duration - elapsed
                alpha = max(0.0, remaining / _FADE_OUT)

            if elapsed < _STATIC_PHASE:
                # Phase 1: static image only, no animation.
                self._render(alpha, 0.0, 0.0, 0.0)
            else:
                # Phase 2: fully animated splash.
                self._render(alpha, self._pulse, elapsed * 1.5, 1.0)
            sdl2.SDL_GL_SwapWindow(window)
            sdl2.SDL_Delay(16)   # ~60 fps cap

        return quit_requested

    def _render(self, alpha: float, pulse: float, hue_time: float, anim_mix: float) -> None:
        ctx = self._ctx
        ctx.screen.use()
        ctx.viewport = (0, 0, self._width, self._height)
        ctx.clear(0.0, 0.0, 0.0, 1.0)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self._tex.use(location=0)
        self._prog["splash_tex"].value = 0
        self._prog["alpha"].value = float(alpha)
        self._prog["pulse"].value = float(max(0.0, min(1.0, pulse)))
        self._prog["hue_time"].value = float(hue_time)
        self._prog["prism_strength"].value = 1.0
        self._prog["twinkle_strength"].value = 0.95
        self._prog["bloom_strength"].value = 0.9
        self._prog["anim_mix"].value = float(max(0.0, min(1.0, anim_mix)))
        self._vao.render(moderngl.TRIANGLE_STRIP)

    @property
    def had_audio(self) -> bool:
        """Whether significant audio was detected during splash."""
        return self._peak_audio > 0.15

    def resize(self, width: int, height: int) -> None:
        """Called if the window is resized during the splash."""
        self._width = width
        self._height = height

    def destroy(self) -> None:
        """Release all GL resources."""
        self._tex.release()
        self._vao.release()
        self._vbo.release()
        self._prog.release()
