"""Explicit-GL presentation helper for drop-in "second window" UIs.

Why this exists
----------------
control-room-01 and dj-mixer-01 each open a second SDL window in the same
process as the main audience window and used to present it with
``SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE)`` +
``SDL_RenderPresent``, intending a pure-CPU path with no GL involvement.

That assumption was wrong. SDL2's window-surface layer defaults to a
hidden, GL-accelerated "texture framebuffer" renderer on Linux (both X11
and Wayland) the first time any window surface is requested in the
process — confirmed directly in SDL2 source
(``SDL_video.c::ShouldAttemptTextureFramebuffer`` /
``SDL_CreateWindowTexture``). That hidden renderer creates its own GL
context and, on Wayland, was observed (via a live apitrace capture)
calling ``eglMakeCurrent`` to switch to it with no restore, corrupting the
main app's GL state for the rest of the session. Full writeup:
``docs/debug/control-room-mixer-second-window-investigation-2026-07-09.md``
and ``docs/planning/control-room-mixer-second-window-mitigation-strategies-2026-07-09.md``
(this module implements that document's "M3" option).

This module gives a drop-in an explicit, first-class GL context for its
second window instead, so there is exactly one context per window, under
our control, and every entry point restores whatever GL window/context was
current before it ran — a caller never needs to guess whether presenting
moved the current context out from under it.

Usage
-----
::

    win = SecondaryGLWindow(b'My Window', x, y, width, height,
                             extra_flags=sdl2.SDL_WINDOW_RESIZABLE)
    win.create()
    ...
    win.present(raw_rgba_bytes, frame_width, frame_height)
    ...
    win.destroy()

The window is independent from the main audience context by design (no
``SDL_GL_SHARE_WITH_CURRENT_CONTEXT``) — the whole point of the second
window is to avoid sharing GL objects between drop-in UI code and the
audience-facing renderer.
"""
from __future__ import annotations

import ctypes
import logging
from typing import Any

import moderngl
import numpy as np
import sdl2

log = logging.getLogger(__name__)

# Vertex shader — maps a fullscreen quad to clip space and carries an
# explicit UV attribute (not derived from position) so the fragment shader
# samples row 0 of the uploaded texture (a top-down raster, e.g. PIL's
# native row order) at the top of the screen.
_VERTEX_SHADER = """
#version 330
in vec2 in_vert;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    v_uv = in_uv;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

# Fragment shader — samples the streaming RGBA texture uploaded by
# present() and outputs it unmodified.
_FRAGMENT_SHADER = """
#version 330
uniform sampler2D uTexture;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    fragColor = texture(uTexture, v_uv);
}
"""

# Triangle-strip quad: (position.xy, uv.xy) per vertex. uv.y=0 at the top
# screen vertices so texel row 0 (the first row written to the texture)
# lands at the top of the window -- see the vertex shader comment above.
_QUAD_VERTICES = np.array([
    -1.0, -1.0, 0.0, 1.0,
    1.0, -1.0, 1.0, 1.0,
    -1.0, 1.0, 0.0, 0.0,
    1.0, 1.0, 1.0, 0.0,
], dtype='f4')


class SecondaryGLWindow:
    """Owns a second SDL window with its own explicit OpenGL context.

    Not thread-safe: ``create()``/``present()``/``destroy()`` must all be
    called from the same thread that owns the main app's GL context
    (mirrors the existing drop-in convention where a background thread only
    rasterizes into a plain byte buffer and the main thread does all SDL/GL
    work).
    """

    def __init__(
        self,
        title: bytes,
        x: int,
        y: int,
        width: int,
        height: int,
        *,
        extra_flags: int = 0,
    ) -> None:
        self._title = title
        self._x = int(x)
        self._y = int(y)
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self._extra_flags = int(extra_flags)
        self.window: Any = None
        self._window_id = 0
        self._gl_context: Any = None
        self._mgl_ctx: moderngl.Context | None = None
        self._program: Any = None
        self._vbo: Any = None
        self._vao: Any = None
        self._texture: Any = None

    @property
    def window_id(self) -> int:
        return self._window_id

    @property
    def is_open(self) -> bool:
        return self.window is not None

    def create(self) -> None:
        """Create the window, its own GL context, and the blit pipeline.

        Raises RuntimeError on failure, cleaning up any partially-created
        state first. Always restores the previously-current GL window/
        context before returning (context creation makes the new context
        current as a side effect).
        """
        prev_window = sdl2.SDL_GL_GetCurrentWindow()
        prev_context = sdl2.SDL_GL_GetCurrentContext()
        try:
            flags = sdl2.SDL_WINDOW_OPENGL | sdl2.SDL_WINDOW_SHOWN | self._extra_flags
            self.window = sdl2.SDL_CreateWindow(
                self._title, self._x, self._y, self.width, self.height, flags,
            )
            if not self.window:
                raise RuntimeError(f'window creation failed: {sdl2.SDL_GetError().decode()}')
            self._window_id = int(sdl2.SDL_GetWindowID(self.window))

            # The WM may have picked a different size than requested (e.g.
            # borderless-fullscreen sizing quirks) — query the actual size
            # so the GL viewport/texture match the live window exactly.
            w_i, h_i = ctypes.c_int(0), ctypes.c_int(0)
            sdl2.SDL_GetWindowSize(self.window, ctypes.byref(w_i), ctypes.byref(h_i))
            if w_i.value > 0 and h_i.value > 0:
                self.width, self.height = int(w_i.value), int(h_i.value)

            self._gl_context = sdl2.SDL_GL_CreateContext(self.window)
            if not self._gl_context:
                raise RuntimeError(f'GL context creation failed: {sdl2.SDL_GetError().decode()}')
            # Swap interval 0: an occluded/minimized second window must
            # never block eglSwapBuffers/wglSwapBuffers waiting on a
            # compositor frame callback for a window nobody is looking at.
            sdl2.SDL_GL_SetSwapInterval(0)

            self._mgl_ctx = moderngl.create_context()
            self._program = self._mgl_ctx.program(
                vertex_shader=_VERTEX_SHADER, fragment_shader=_FRAGMENT_SHADER,
            )
            self._program['uTexture'] = 0
            self._vbo = self._mgl_ctx.buffer(_QUAD_VERTICES.tobytes())
            self._vao = self._mgl_ctx.vertex_array(
                self._program, [(self._vbo, '2f 2f', 'in_vert', 'in_uv')],
            )
            self._texture = self._mgl_ctx.texture((self.width, self.height), 4)
            self._texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        except Exception:
            self._release_gl_resources()
            if self._gl_context is not None:
                sdl2.SDL_GL_DeleteContext(self._gl_context)
                self._gl_context = None
            if self.window is not None:
                sdl2.SDL_DestroyWindow(self.window)
                self.window = None
            self._window_id = 0
            raise
        finally:
            self._restore(prev_window, prev_context)

    def present(self, raw_rgba: bytes, width: int, height: int) -> bool:
        """Upload ``raw_rgba`` (top-down, RGBA8) and present it.

        Returns True on success, False if the window isn't open or the
        upload/draw/swap failed (logged, not raised). Always restores
        the previously-current GL window/context before returning,
        success or failure — mirrors ``App._present_subsystems()``'s
        rebind-even-on-failure discipline, since a caller must be able to
        assume its own context is current again regardless of outcome.
        """
        if self.window is None or self._mgl_ctx is None:
            return False
        prev_window = sdl2.SDL_GL_GetCurrentWindow()
        prev_context = sdl2.SDL_GL_GetCurrentContext()
        ok = False
        try:
            if sdl2.SDL_GL_MakeCurrent(self.window, self._gl_context) != 0:
                log.warning('SecondaryGLWindow: SDL_GL_MakeCurrent failed: %s', sdl2.SDL_GetError().decode())
                return False
            if (int(width), int(height)) != (self.width, self.height):
                self._resize(int(width), int(height))
            self._texture.write(raw_rgba)
            self._mgl_ctx.screen.use()
            self._mgl_ctx.viewport = (0, 0, self.width, self.height)
            self._mgl_ctx.screen.clear(0.0, 0.0, 0.0, 1.0)
            self._texture.use(location=0)
            self._vao.render(moderngl.TRIANGLE_STRIP)
            sdl2.SDL_GL_SwapWindow(self.window)
            ok = True
        except Exception as exc:
            log.warning('SecondaryGLWindow: present failed: %s', exc)
        finally:
            self._restore(prev_window, prev_context)
        return ok

    def _resize(self, width: int, height: int) -> None:
        self.width = max(1, width)
        self.height = max(1, height)
        if self._texture is not None:
            self._texture.release()
        self._texture = self._mgl_ctx.texture((self.width, self.height), 4)
        self._texture.filter = (moderngl.LINEAR, moderngl.LINEAR)

    def destroy(self) -> None:
        """Release all GL resources and destroy the window/context.

        Safe to call more than once (a no-op once already closed). Always
        restores the previously-current GL window/context before
        returning.
        """
        if self.window is None:
            return
        prev_window = sdl2.SDL_GL_GetCurrentWindow()
        prev_context = sdl2.SDL_GL_GetCurrentContext()
        try:
            if self._gl_context is not None:
                sdl2.SDL_GL_MakeCurrent(self.window, self._gl_context)
            self._release_gl_resources()
            if self._gl_context is not None:
                sdl2.SDL_GL_DeleteContext(self._gl_context)
                self._gl_context = None
        finally:
            sdl2.SDL_DestroyWindow(self.window)
            self.window = None
            self._window_id = 0
            self._restore(prev_window, prev_context)

    def _release_gl_resources(self) -> None:
        for obj in (self._vao, self._vbo, self._texture, self._program):
            if obj is not None:
                try:
                    obj.release()
                except Exception as exc:  # pragma: no cover - defensive
                    log.warning('SecondaryGLWindow: resource release failed: %s', exc)
        self._vao = self._vbo = self._texture = self._program = None
        self._mgl_ctx = None

    @staticmethod
    def _restore(window: Any, context: Any) -> None:
        if window is not None and context is not None:
            sdl2.SDL_GL_MakeCurrent(window, context)
