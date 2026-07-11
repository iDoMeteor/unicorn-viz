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
main app's GL state for the rest of the session.

Why this doesn't use moderngl
------------------------------
The first version of this module built its GL pipeline with
``moderngl.create_context()``. That works for the *first* GL context in a
process, but ``moderngl.create_context()`` caches a single global context
(``glcontext``'s ``_store.default_context``); every call after the first
falls into "detect an already-current context" mode, and on Linux that
detection path is hardcoded to X11/GLX (``glcontext.default_backend()``
always returns the x11 backend on Linux — there is no Wayland equivalent).
On a native-Wayland SDL session (no XWayland), the second context has no
GLX to detect, and ``moderngl.create_context()`` raises
``"(detect) glXGetCurrentContext: cannot detect OpenGL context"`` even
though a perfectly valid EGL context is current. This is a structural
limitation of the ``glcontext`` dependency, not a settings issue.

Instead, this module loads the small subset of OpenGL 3.3 core entry
points it actually needs (~20 functions: one texture, one shader program,
one vertex array, one draw call) via ``SDL_GL_GetProcAddress``, which SDL
itself implements portably across every video backend it supports (X11,
native Wayland, Windows, macOS) — the same mechanism SDL uses internally
for its own GL examples. This sidesteps ``glcontext``'s platform-detection
logic entirely.

Full investigation:
``docs/debug/control-room-mixer-second-window-investigation-2026-07-09.md``
and
``docs/planning/control-room-mixer-second-window-mitigation-strategies-2026-07-09.md``.

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

import sdl2

log = logging.getLogger(__name__)

# -- GL constants (OpenGL 1.1 - 3.3 core subset actually used below) -------
_GL_FALSE = 0
_GL_FLOAT = 0x1406
_GL_UNSIGNED_BYTE = 0x1401
_GL_TEXTURE_2D = 0x0DE1
_GL_RGBA = 0x1908
_GL_RGBA8 = 0x8058
_GL_TEXTURE_MIN_FILTER = 0x2801
_GL_TEXTURE_MAG_FILTER = 0x2800
_GL_LINEAR = 0x2601
_GL_TEXTURE_WRAP_S = 0x2802
_GL_TEXTURE_WRAP_T = 0x2803
_GL_CLAMP_TO_EDGE = 0x812F
_GL_ARRAY_BUFFER = 0x8892
_GL_STATIC_DRAW = 0x88E4
_GL_VERTEX_SHADER = 0x8B31
_GL_FRAGMENT_SHADER = 0x8B30
_GL_COMPILE_STATUS = 0x8B81
_GL_LINK_STATUS = 0x8B82
_GL_TRIANGLE_STRIP = 0x0005
_GL_COLOR_BUFFER_BIT = 0x00004000
_GL_TEXTURE0 = 0x84C0

# Vertex shader — maps a fullscreen quad to clip space. Explicit
# `layout(location=N)` qualifiers avoid needing glGetAttribLocation.
# uv.y=0 at the top screen vertices so texel row 0 (the first row written
# to the texture, e.g. PIL's top row) lands at the top of the window.
_VERTEX_SHADER = """
#version 330
layout(location = 0) in vec2 in_vert;
layout(location = 1) in vec2 in_uv;
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

# Triangle-strip quad: (position.xy, uv.xy) per vertex.
_QUAD_VERTICES = (ctypes.c_float * 16)(
    -1.0, -1.0, 0.0, 1.0,
    1.0, -1.0, 1.0, 1.0,
    -1.0, 1.0, 0.0, 0.0,
    1.0, 1.0, 1.0, 0.0,
)

_GL_FUNCTIONS: dict[str, tuple] = {
    # name: (restype, *argtypes)
    'glGetError': (ctypes.c_uint,),
    'glViewport': (None, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int),
    'glClearColor': (None, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float),
    'glClear': (None, ctypes.c_uint),
    'glGenTextures': (None, ctypes.c_int, ctypes.POINTER(ctypes.c_uint)),
    'glDeleteTextures': (None, ctypes.c_int, ctypes.POINTER(ctypes.c_uint)),
    'glBindTexture': (None, ctypes.c_uint, ctypes.c_uint),
    'glTexParameteri': (None, ctypes.c_uint, ctypes.c_uint, ctypes.c_int),
    'glTexImage2D': (
        None, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
    ),
    'glTexSubImage2D': (
        None, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
    ),
    'glActiveTexture': (None, ctypes.c_uint),
    'glGenBuffers': (None, ctypes.c_int, ctypes.POINTER(ctypes.c_uint)),
    'glDeleteBuffers': (None, ctypes.c_int, ctypes.POINTER(ctypes.c_uint)),
    'glBindBuffer': (None, ctypes.c_uint, ctypes.c_uint),
    'glBufferData': (None, ctypes.c_uint, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint),
    'glGenVertexArrays': (None, ctypes.c_int, ctypes.POINTER(ctypes.c_uint)),
    'glDeleteVertexArrays': (None, ctypes.c_int, ctypes.POINTER(ctypes.c_uint)),
    'glBindVertexArray': (None, ctypes.c_uint),
    'glEnableVertexAttribArray': (None, ctypes.c_uint),
    'glVertexAttribPointer': (
        None, ctypes.c_uint, ctypes.c_int, ctypes.c_uint, ctypes.c_uint8,
        ctypes.c_int, ctypes.c_void_p,
    ),
    'glCreateShader': (ctypes.c_uint, ctypes.c_uint),
    'glDeleteShader': (None, ctypes.c_uint),
    'glShaderSource': (
        None, ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p),
        ctypes.POINTER(ctypes.c_int),
    ),
    'glCompileShader': (None, ctypes.c_uint),
    'glGetShaderiv': (None, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)),
    'glGetShaderInfoLog': (
        None, ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_char_p,
    ),
    'glCreateProgram': (ctypes.c_uint,),
    'glDeleteProgram': (None, ctypes.c_uint),
    'glAttachShader': (None, ctypes.c_uint, ctypes.c_uint),
    'glLinkProgram': (None, ctypes.c_uint),
    'glGetProgramiv': (None, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)),
    'glGetProgramInfoLog': (
        None, ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_char_p,
    ),
    'glUseProgram': (None, ctypes.c_uint),
    'glGetUniformLocation': (ctypes.c_int, ctypes.c_uint, ctypes.c_char_p),
    'glUniform1i': (None, ctypes.c_int, ctypes.c_int),
    'glDrawArrays': (None, ctypes.c_uint, ctypes.c_int, ctypes.c_int),
}


class _GLBinding:
    """Thin, Pythonic wrapper around the raw GL entry points this module
    needs, loaded via ``SDL_GL_GetProcAddress`` against whatever GL context
    is current when :meth:`load` runs.

    Deliberately not a 1:1 ``glFoo``-named passthrough — each method here
    does one specific job for this module's fixed quad-blit pipeline, so
    the raw ctypes plumbing (out-parameters, string buffers, info-log
    fetches) stays in one place instead of scattered through
    :class:`SecondaryGLWindow`.
    """

    def __init__(self) -> None:
        self._fn: dict[str, Any] = {}

    def load(self) -> None:
        for name, sig in _GL_FUNCTIONS.items():
            restype, *argtypes = sig
            addr = sdl2.SDL_GL_GetProcAddress(name.encode())
            if not addr:
                raise RuntimeError(f'SDL_GL_GetProcAddress returned NULL for {name}')
            self._fn[name] = ctypes.CFUNCTYPE(restype, *argtypes)(addr)

    def gen_texture(self) -> int:
        tex_id = ctypes.c_uint(0)
        self._fn['glGenTextures'](1, ctypes.byref(tex_id))
        return int(tex_id.value)

    def delete_texture(self, tex_id: int) -> None:
        arr = (ctypes.c_uint * 1)(tex_id)
        self._fn['glDeleteTextures'](1, arr)

    def bind_texture(self, tex_id: int) -> None:
        self._fn['glBindTexture'](_GL_TEXTURE_2D, tex_id)

    def set_bound_texture_filter_linear_clamped(self) -> None:
        for pname in (_GL_TEXTURE_MIN_FILTER, _GL_TEXTURE_MAG_FILTER):
            self._fn['glTexParameteri'](_GL_TEXTURE_2D, pname, _GL_LINEAR)
        for pname in (_GL_TEXTURE_WRAP_S, _GL_TEXTURE_WRAP_T):
            self._fn['glTexParameteri'](_GL_TEXTURE_2D, pname, _GL_CLAMP_TO_EDGE)

    def tex_image_2d_rgba(self, width: int, height: int, data: bytes | None) -> None:
        ptr = ctypes.cast(data, ctypes.c_void_p) if data is not None else None
        self._fn['glTexImage2D'](
            _GL_TEXTURE_2D, 0, _GL_RGBA8, width, height, 0,
            _GL_RGBA, _GL_UNSIGNED_BYTE, ptr,
        )

    def tex_sub_image_2d_rgba(self, width: int, height: int, data: bytes) -> None:
        ptr = ctypes.cast(data, ctypes.c_void_p)
        self._fn['glTexSubImage2D'](
            _GL_TEXTURE_2D, 0, 0, 0, width, height, _GL_RGBA, _GL_UNSIGNED_BYTE, ptr,
        )

    def active_texture0(self) -> None:
        self._fn['glActiveTexture'](_GL_TEXTURE0)

    def gen_buffer(self) -> int:
        buf_id = ctypes.c_uint(0)
        self._fn['glGenBuffers'](1, ctypes.byref(buf_id))
        return int(buf_id.value)

    def delete_buffer(self, buf_id: int) -> None:
        arr = (ctypes.c_uint * 1)(buf_id)
        self._fn['glDeleteBuffers'](1, arr)

    def bind_array_buffer(self, buf_id: int) -> None:
        self._fn['glBindBuffer'](_GL_ARRAY_BUFFER, buf_id)

    def array_buffer_data_static(self, data: ctypes.Array) -> None:
        self._fn['glBufferData'](_GL_ARRAY_BUFFER, ctypes.sizeof(data), data, _GL_STATIC_DRAW)

    def gen_vertex_array(self) -> int:
        vao_id = ctypes.c_uint(0)
        self._fn['glGenVertexArrays'](1, ctypes.byref(vao_id))
        return int(vao_id.value)

    def delete_vertex_array(self, vao_id: int) -> None:
        arr = (ctypes.c_uint * 1)(vao_id)
        self._fn['glDeleteVertexArrays'](1, arr)

    def bind_vertex_array(self, vao_id: int) -> None:
        self._fn['glBindVertexArray'](vao_id)

    def setup_quad_attribs(self) -> None:
        """Enable+configure attribs 0 (2f position) and 1 (2f uv) against
        the currently bound array buffer, matching _QUAD_VERTICES' fixed
        interleaved layout (stride 16 bytes)."""
        stride = 4 * ctypes.sizeof(ctypes.c_float)
        self._fn['glEnableVertexAttribArray'](0)
        self._fn['glVertexAttribPointer'](0, 2, _GL_FLOAT, _GL_FALSE, stride, None)
        self._fn['glEnableVertexAttribArray'](1)
        offset = ctypes.c_void_p(2 * ctypes.sizeof(ctypes.c_float))
        self._fn['glVertexAttribPointer'](1, 2, _GL_FLOAT, _GL_FALSE, stride, offset)

    def compile_program(self, vertex_src: str, fragment_src: str) -> int:
        vs = self._compile_shader(_GL_VERTEX_SHADER, vertex_src)
        fs = self._compile_shader(_GL_FRAGMENT_SHADER, fragment_src)
        program = self._fn['glCreateProgram']()
        self._fn['glAttachShader'](program, vs)
        self._fn['glAttachShader'](program, fs)
        self._fn['glLinkProgram'](program)
        status = ctypes.c_int(0)
        self._fn['glGetProgramiv'](program, _GL_LINK_STATUS, ctypes.byref(status))
        if not status.value:
            log_text = self._program_info_log(program)
            self._fn['glDeleteProgram'](program)
            self._fn['glDeleteShader'](vs)
            self._fn['glDeleteShader'](fs)
            raise RuntimeError(f'GL program link failed: {log_text}')
        self._fn['glDeleteShader'](vs)
        self._fn['glDeleteShader'](fs)
        return int(program)

    def _compile_shader(self, kind: int, source: str) -> int:
        shader = self._fn['glCreateShader'](kind)
        src_bytes = source.encode()
        src_array = (ctypes.c_char_p * 1)(src_bytes)
        self._fn['glShaderSource'](shader, 1, src_array, None)
        self._fn['glCompileShader'](shader)
        status = ctypes.c_int(0)
        self._fn['glGetShaderiv'](shader, _GL_COMPILE_STATUS, ctypes.byref(status))
        if not status.value:
            log_text = self._shader_info_log(shader)
            self._fn['glDeleteShader'](shader)
            raise RuntimeError(f'GL shader compile failed: {log_text}')
        return int(shader)

    def _shader_info_log(self, shader: int) -> str:
        buf = ctypes.create_string_buffer(2048)
        length = ctypes.c_int(0)
        self._fn['glGetShaderInfoLog'](shader, 2048, ctypes.byref(length), buf)
        return buf.value.decode(errors='replace')

    def _program_info_log(self, program: int) -> str:
        buf = ctypes.create_string_buffer(2048)
        length = ctypes.c_int(0)
        self._fn['glGetProgramInfoLog'](program, 2048, ctypes.byref(length), buf)
        return buf.value.decode(errors='replace')

    def delete_program(self, program: int) -> None:
        self._fn['glDeleteProgram'](program)

    def use_program(self, program: int) -> None:
        self._fn['glUseProgram'](program)

    def get_uniform_location(self, program: int, name: str) -> int:
        return int(self._fn['glGetUniformLocation'](program, name.encode()))

    def set_uniform_1i(self, location: int, value: int) -> None:
        self._fn['glUniform1i'](location, value)

    def viewport(self, width: int, height: int) -> None:
        self._fn['glViewport'](0, 0, width, height)

    def clear_black(self) -> None:
        self._fn['glClearColor'](0.0, 0.0, 0.0, 1.0)
        self._fn['glClear'](_GL_COLOR_BUFFER_BIT)

    def draw_triangle_strip_quad(self) -> None:
        self._fn['glDrawArrays'](_GL_TRIANGLE_STRIP, 0, 4)

    def get_error(self) -> int:
        return int(self._fn['glGetError']())


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
        self._gl: _GLBinding | None = None
        self._program = 0
        self._uniform_loc = 0
        self._vbo = 0
        self._vao = 0
        self._texture = 0
        # Texture (frame) dimensions -- tracked separately from the window
        # drawable size so callers can present frames rasterized at a lower
        # resolution and have the linear-filtered quad upscale them.
        self._tex_width = 0
        self._tex_height = 0

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

            self._gl_context = sdl2.SDL_GL_CreateContext(self.window)
            if not self._gl_context:
                raise RuntimeError(f'GL context creation failed: {sdl2.SDL_GetError().decode()}')
            # Swap interval 0: an occluded/minimized second window must
            # never block eglSwapBuffers/wglSwapBuffers waiting on a
            # compositor frame callback for a window nobody is looking at.
            sdl2.SDL_GL_SetSwapInterval(0)

            # The WM may have picked a different size than requested (e.g.
            # borderless-fullscreen sizing quirks), and on HiDPI/fractional-
            # scaling displays the actual GL drawable is in *physical*
            # pixels while SDL_CreateWindow's w/h and SDL_GetWindowSize are
            # in *logical* points -- using the logical size here would size
            # the viewport/texture too small on any scaled display. Query
            # the real drawable size instead (the same call app.py's own
            # GL readback path uses for exactly this reason,
            # read_screenshot_frame()) so the GL viewport/texture -- and,
            # since callers copy these values back into their own
            # rasterization size, the PIL-rendered content too -- always
            # match the live window's true pixel dimensions.
            w_i, h_i = ctypes.c_int(0), ctypes.c_int(0)
            sdl2.SDL_GL_GetDrawableSize(self.window, ctypes.byref(w_i), ctypes.byref(h_i))
            if w_i.value > 0 and h_i.value > 0:
                self.width, self.height = int(w_i.value), int(h_i.value)

            self._gl = _GLBinding()
            self._gl.load()
            self._program = self._gl.compile_program(_VERTEX_SHADER, _FRAGMENT_SHADER)
            self._gl.use_program(self._program)
            self._uniform_loc = self._gl.get_uniform_location(self._program, 'uTexture')
            self._gl.set_uniform_1i(self._uniform_loc, 0)

            self._vbo = self._gl.gen_buffer()
            self._gl.bind_array_buffer(self._vbo)
            self._gl.array_buffer_data_static(_QUAD_VERTICES)
            self._vao = self._gl.gen_vertex_array()
            self._gl.bind_vertex_array(self._vao)
            self._gl.bind_array_buffer(self._vbo)
            self._gl.setup_quad_attribs()

            self._texture = self._gl.gen_texture()
            self._gl.bind_texture(self._texture)
            self._gl.set_bound_texture_filter_linear_clamped()
            self._gl.tex_image_2d_rgba(self.width, self.height, None)
            self._tex_width, self._tex_height = self.width, self.height
            self._gl.active_texture0()
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

        ``width``/``height`` are the *frame* dimensions and may be smaller
        than the window drawable: the frame is uploaded at its own size and
        the linear-filtered fullscreen quad upscales it to the viewport
        (how dj-mixer-01's ``ui_scale`` renders at reduced resolution).

        Returns True on success, False if the window isn't open or the
        upload/draw/swap failed (logged, not raised). Always restores
        the previously-current GL window/context before returning,
        success or failure — mirrors ``App._present_subsystems()``'s
        rebind-even-on-failure discipline, since a caller must be able to
        assume its own context is current again regardless of outcome.
        """
        if self.window is None or self._gl is None:
            return False
        prev_window = sdl2.SDL_GL_GetCurrentWindow()
        prev_context = sdl2.SDL_GL_GetCurrentContext()
        ok = False
        try:
            if sdl2.SDL_GL_MakeCurrent(self.window, self._gl_context) != 0:
                log.warning('SecondaryGLWindow: SDL_GL_MakeCurrent failed: %s', sdl2.SDL_GetError().decode())
                return False
            # The drawable can change independently of the frame size
            # (window resize while the raster thread still produces the old
            # size) -- track it separately so the viewport always covers
            # the real window.
            w_i, h_i = ctypes.c_int(0), ctypes.c_int(0)
            sdl2.SDL_GL_GetDrawableSize(self.window, ctypes.byref(w_i), ctypes.byref(h_i))
            if w_i.value > 0 and h_i.value > 0:
                self.width, self.height = int(w_i.value), int(h_i.value)
            self._gl.bind_texture(self._texture)
            if (int(width), int(height)) != (self._tex_width, self._tex_height):
                self._resize_texture(int(width), int(height))
            self._gl.tex_sub_image_2d_rgba(self._tex_width, self._tex_height, raw_rgba)
            self._gl.viewport(self.width, self.height)
            self._gl.clear_black()
            self._gl.use_program(self._program)
            self._gl.bind_vertex_array(self._vao)
            self._gl.draw_triangle_strip_quad()
            sdl2.SDL_GL_SwapWindow(self.window)
            ok = True
        except Exception as exc:
            log.warning('SecondaryGLWindow: present failed: %s', exc)
        finally:
            self._restore(prev_window, prev_context)
        return ok

    def _resize_texture(self, width: int, height: int) -> None:
        self._tex_width = max(1, width)
        self._tex_height = max(1, height)
        self._gl.tex_image_2d_rgba(self._tex_width, self._tex_height, None)

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
        gl = self._gl
        if gl is not None:
            try:
                if self._texture:
                    gl.delete_texture(self._texture)
                if self._vao:
                    gl.delete_vertex_array(self._vao)
                if self._vbo:
                    gl.delete_buffer(self._vbo)
                if self._program:
                    gl.delete_program(self._program)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning('SecondaryGLWindow: resource release failed: %s', exc)
        self._texture = self._vao = self._vbo = self._program = 0
        self._gl = None

    @staticmethod
    def _restore(window: Any, context: Any) -> None:
        if window is not None and context is not None:
            sdl2.SDL_GL_MakeCurrent(window, context)
