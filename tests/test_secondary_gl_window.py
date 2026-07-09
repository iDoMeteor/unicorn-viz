"""Regression tests for SecondaryGLWindow — the explicit-GL replacement for
control-room-01/dj-mixer-01's second-window presentation path.

Two Linux-specific bugs were found and worked around by this module (see
its docstring for the full mechanism):

1. SDL2 silently creates a second, GL-backed renderer behind any
   SDL_RENDERER_SOFTWARE window on Linux.
2. moderngl.create_context() cannot attach to that second window's own,
   independently-created GL context on native Wayland — its "detect an
   existing context" fallback is hardcoded to X11/GLX (glcontext has no
   Wayland equivalent), so this module loads its own minimal GL bindings
   via SDL_GL_GetProcAddress instead of using moderngl at all.

These tests exercise SecondaryGLWindow's own bracketing discipline —
create()/present()/destroy() must each restore whatever GL window/context
was current before they ran, regardless of success or failure — using
fakes for both ``sdl2`` and the internal ``_GLBinding`` GL wrapper, since
SDL's ``dummy`` video driver (used elsewhere in this repo for headless SDL
tests) does not support real GL context creation, and real GL calls can't
be faked below the ctypes boundary without a real context.
"""
from __future__ import annotations

import pytest

from unicornviz import secondary_gl_window as sgw


class _FakeError:
    def __init__(self, message: str = 'boom') -> None:
        self._message = message

    def decode(self) -> str:
        return self._message


class _FakeWindow:
    def __init__(self, window_id: int) -> None:
        self.window_id = window_id
        self.destroyed = False


class _FakeGLContext:
    def __init__(self, ctx_id: int) -> None:
        self.ctx_id = ctx_id
        self.deleted = False


class _FakeSDL2:
    """Fakes just enough of the sdl2 module surface for SecondaryGLWindow."""

    SDL_WINDOW_OPENGL = 1
    SDL_WINDOW_SHOWN = 2
    SDL_WINDOW_BORDERLESS = 4
    SDL_WINDOW_RESIZABLE = 8

    def __init__(self) -> None:
        self.fail_create_window = False
        self.fail_create_context = False
        self.fail_make_current = False
        self._next_window_id = 1
        self._next_ctx_id = 1
        self.current_window: _FakeWindow | None = None
        self.current_context: _FakeGLContext | None = None
        self.swap_calls: list[_FakeWindow] = []
        self.swap_interval_calls: list[int] = []
        self.deleted_contexts: list[_FakeGLContext] = []
        self.destroyed_windows: list[_FakeWindow] = []
        self.make_current_calls: list[tuple] = []

    def SDL_CreateWindow(self, title, x, y, w, h, flags):  # noqa: ARG002
        if self.fail_create_window:
            return None
        win = _FakeWindow(self._next_window_id)
        self._next_window_id += 1
        return win

    def SDL_GetWindowID(self, window: _FakeWindow) -> int:
        return window.window_id

    def SDL_GL_GetDrawableSize(self, window, w_ref, h_ref) -> None:  # noqa: ARG002
        # Real SDL writes the actual drawable pixel size back through the
        # pointers; the fake leaves them at their ctypes default (0) so
        # callers keep whatever size they already have.
        pass

    def SDL_GL_CreateContext(self, window: _FakeWindow):
        if self.fail_create_context:
            return None
        ctx = _FakeGLContext(self._next_ctx_id)
        self._next_ctx_id += 1
        # Real SDL makes the new context current as a side effect.
        self.current_window = window
        self.current_context = ctx
        return ctx

    def SDL_GL_SetSwapInterval(self, interval: int) -> int:
        self.swap_interval_calls.append(interval)
        return 0

    def SDL_GL_MakeCurrent(self, window, context) -> int:
        self.make_current_calls.append((window, context))
        if self.fail_make_current:
            return -1
        self.current_window = window
        self.current_context = context
        return 0

    def SDL_GL_SwapWindow(self, window: _FakeWindow) -> None:
        self.swap_calls.append(window)

    def SDL_GL_GetCurrentWindow(self):
        return self.current_window

    def SDL_GL_GetCurrentContext(self):
        return self.current_context

    def SDL_GL_DeleteContext(self, context: _FakeGLContext) -> None:
        context.deleted = True
        self.deleted_contexts.append(context)

    def SDL_DestroyWindow(self, window: _FakeWindow) -> None:
        window.destroyed = True
        self.destroyed_windows.append(window)

    def SDL_GetError(self) -> _FakeError:
        return _FakeError()


class _FakeGLBinding:
    """Stands in for the real _GLBinding — no ctypes/real GL calls."""

    fail_load = False
    fail_compile = False

    def __init__(self) -> None:
        self.loaded = False
        self._next_id = 1
        self.textures: dict[int, tuple[int, int]] = {}
        self.deleted_textures: list[int] = []
        self.deleted_buffers: list[int] = []
        self.deleted_vaos: list[int] = []
        self.deleted_programs: list[int] = []
        self.tex_sub_image_calls: list[tuple] = []
        self.tex_image_calls: list[tuple] = []
        self.draw_calls = 0
        self.swap_program_calls = 0
        self.bound_texture: int | None = None
        self.bound_vao: int | None = None

    def _alloc(self) -> int:
        val = self._next_id
        self._next_id += 1
        return val

    def load(self) -> None:
        if type(self).fail_load:
            raise RuntimeError('SDL_GL_GetProcAddress returned NULL for glCreateShader')
        self.loaded = True

    def compile_program(self, vertex_src, fragment_src) -> int:  # noqa: ARG002
        if type(self).fail_compile:
            raise RuntimeError('GL program link failed: fake failure')
        return self._alloc()

    def use_program(self, program: int) -> None:
        self.swap_program_calls += 1

    def get_uniform_location(self, program, name) -> int:  # noqa: ARG002
        return 0

    def set_uniform_1i(self, location, value) -> None:
        pass

    def gen_buffer(self) -> int:
        return self._alloc()

    def bind_array_buffer(self, buf_id: int) -> None:
        pass

    def array_buffer_data_static(self, data) -> None:
        pass

    def gen_vertex_array(self) -> int:
        return self._alloc()

    def bind_vertex_array(self, vao_id: int) -> None:
        self.bound_vao = vao_id

    def setup_quad_attribs(self) -> None:
        pass

    def gen_texture(self) -> int:
        return self._alloc()

    def bind_texture(self, tex_id: int) -> None:
        self.bound_texture = tex_id

    def set_bound_texture_filter_linear_clamped(self) -> None:
        pass

    def tex_image_2d_rgba(self, width: int, height: int, data) -> None:
        self.tex_image_calls.append((width, height, data))
        self.textures[self.bound_texture] = (width, height)

    def tex_sub_image_2d_rgba(self, width: int, height: int, data: bytes) -> None:
        self.tex_sub_image_calls.append((width, height, data))

    def active_texture0(self) -> None:
        pass

    def viewport(self, width: int, height: int) -> None:
        pass

    def clear_black(self) -> None:
        pass

    def draw_triangle_strip_quad(self) -> None:
        self.draw_calls += 1

    def delete_texture(self, tex_id: int) -> None:
        self.deleted_textures.append(tex_id)

    def delete_buffer(self, buf_id: int) -> None:
        self.deleted_buffers.append(buf_id)

    def delete_vertex_array(self, vao_id: int) -> None:
        self.deleted_vaos.append(vao_id)

    def delete_program(self, program: int) -> None:
        self.deleted_programs.append(program)

    def get_error(self) -> int:
        return 0


@pytest.fixture
def fakes(monkeypatch):
    fake_sdl2 = _FakeSDL2()
    _FakeGLBinding.fail_load = False
    _FakeGLBinding.fail_compile = False
    monkeypatch.setattr(sgw, 'sdl2', fake_sdl2)
    monkeypatch.setattr(sgw, '_GLBinding', _FakeGLBinding)
    return fake_sdl2


def _make() -> sgw.SecondaryGLWindow:
    return sgw.SecondaryGLWindow(b'Test Window', 0, 0, 640, 480)


def test_create_builds_window_context_and_pipeline(fakes) -> None:
    fake_sdl2 = fakes
    win = _make()
    win.create()
    assert win.is_open
    assert win.window_id == 1
    assert win._gl_context is not None  # noqa: SLF001
    assert win._gl.loaded is True  # noqa: SLF001
    assert fake_sdl2.swap_interval_calls == [0]


def test_create_restores_previously_current_context(fakes) -> None:
    fake_sdl2 = fakes
    outer_window = _FakeWindow(99)
    outer_ctx = _FakeGLContext(99)
    fake_sdl2.current_window = outer_window
    fake_sdl2.current_context = outer_ctx

    win = _make()
    win.create()

    assert fake_sdl2.current_window is outer_window
    assert fake_sdl2.current_context is outer_ctx


def test_create_raises_and_cleans_up_on_window_creation_failure(fakes) -> None:
    fake_sdl2 = fakes
    fake_sdl2.fail_create_window = True
    win = _make()
    with pytest.raises(RuntimeError):
        win.create()
    assert win.window is None
    assert win.is_open is False


def test_create_raises_and_cleans_up_on_context_creation_failure(fakes) -> None:
    fake_sdl2 = fakes
    fake_sdl2.fail_create_context = True
    win = _make()
    with pytest.raises(RuntimeError):
        win.create()
    # The window that was created before the context failed must be torn
    # down too, not leaked.
    assert win.window is None
    assert len(fake_sdl2.destroyed_windows) == 1


def test_create_raises_and_cleans_up_when_gl_functions_fail_to_load(fakes) -> None:
    fake_sdl2 = fakes
    _FakeGLBinding.fail_load = True
    win = _make()
    with pytest.raises(RuntimeError):
        win.create()
    assert win.window is None
    assert len(fake_sdl2.destroyed_windows) == 1
    assert len(fake_sdl2.deleted_contexts) == 1


def test_create_raises_and_cleans_up_when_shader_compile_fails(fakes) -> None:
    fake_sdl2 = fakes
    _FakeGLBinding.fail_compile = True
    win = _make()
    with pytest.raises(RuntimeError):
        win.create()
    assert win.window is None
    assert len(fake_sdl2.destroyed_windows) == 1
    assert len(fake_sdl2.deleted_contexts) == 1


def test_present_uploads_draws_and_swaps(fakes) -> None:
    fake_sdl2 = fakes
    win = _make()
    win.create()
    raw = b'\x00' * (640 * 480 * 4)
    ok = win.present(raw, 640, 480)
    assert ok is True
    assert win._gl.tex_sub_image_calls == [(640, 480, raw)]  # noqa: SLF001
    assert win._gl.draw_calls == 1  # noqa: SLF001
    assert fake_sdl2.swap_calls == [win.window]


def test_present_returns_false_when_never_created(fakes) -> None:
    win = _make()
    assert win.present(b'\x00', 640, 480) is False


def test_present_restores_previous_context_on_success(fakes) -> None:
    fake_sdl2 = fakes
    win = _make()
    win.create()
    outer_window = _FakeWindow(42)
    outer_ctx = _FakeGLContext(42)
    fake_sdl2.current_window = outer_window
    fake_sdl2.current_context = outer_ctx

    win.present(b'\x00' * (640 * 480 * 4), 640, 480)

    assert fake_sdl2.current_window is outer_window
    assert fake_sdl2.current_context is outer_ctx


def test_present_restores_previous_context_when_make_current_fails(fakes) -> None:
    fake_sdl2 = fakes
    win = _make()
    win.create()
    outer_window = _FakeWindow(42)
    outer_ctx = _FakeGLContext(42)
    fake_sdl2.current_window = outer_window
    fake_sdl2.current_context = outer_ctx

    fake_sdl2.fail_make_current = True
    ok = win.present(b'\x00' * (640 * 480 * 4), 640, 480)

    assert ok is False
    assert fake_sdl2.current_window is outer_window
    assert fake_sdl2.current_context is outer_ctx


def test_present_restores_context_when_draw_raises(fakes, monkeypatch) -> None:
    fake_sdl2 = fakes
    win = _make()
    win.create()
    outer_window = _FakeWindow(7)
    outer_ctx = _FakeGLContext(7)
    fake_sdl2.current_window = outer_window
    fake_sdl2.current_context = outer_ctx

    def _boom(*_a, **_k):
        raise RuntimeError('draw exploded')

    monkeypatch.setattr(win._gl, 'draw_triangle_strip_quad', _boom)  # noqa: SLF001
    ok = win.present(b'\x00' * (640 * 480 * 4), 640, 480)

    assert ok is False
    assert fake_sdl2.current_window is outer_window
    assert fake_sdl2.current_context is outer_ctx


def test_present_resizes_texture_only_when_size_changes(fakes) -> None:
    win = _make()
    win.create()
    gl = win._gl  # noqa: SLF001
    assert len(gl.tex_image_calls) == 1  # initial allocation in create()

    win.present(b'\x00' * (640 * 480 * 4), 640, 480)
    assert len(gl.tex_image_calls) == 1  # unchanged size: no reallocation

    win.present(b'\x00' * (800 * 600 * 4), 800, 600)
    assert len(gl.tex_image_calls) == 2  # resized: reallocated
    assert win.width == 800 and win.height == 600


def test_destroy_releases_gl_resources_and_window(fakes) -> None:
    win = _make()
    win.create()
    gl = win._gl  # noqa: SLF001
    gl_context = win._gl_context  # noqa: SLF001
    window_obj = win.window
    texture_id = win._texture  # noqa: SLF001
    vao_id = win._vao  # noqa: SLF001
    vbo_id = win._vbo  # noqa: SLF001
    program_id = win._program  # noqa: SLF001

    win.destroy()

    assert win.is_open is False
    assert win.window is None
    assert window_obj.destroyed is True
    assert gl_context.deleted is True
    assert gl.deleted_textures == [texture_id]
    assert gl.deleted_vaos == [vao_id]
    assert gl.deleted_buffers == [vbo_id]
    assert gl.deleted_programs == [program_id]


def test_destroy_is_idempotent(fakes) -> None:
    win = _make()
    win.create()
    win.destroy()
    win.destroy()  # must not raise


def test_destroy_restores_previously_current_context(fakes) -> None:
    fake_sdl2 = fakes
    win = _make()
    win.create()
    outer_window = _FakeWindow(11)
    outer_ctx = _FakeGLContext(11)
    fake_sdl2.current_window = outer_window
    fake_sdl2.current_context = outer_ctx

    win.destroy()

    assert fake_sdl2.current_window is outer_window
    assert fake_sdl2.current_context is outer_ctx
