"""Regression tests for SecondaryGLWindow — the explicit-GL replacement for
control-room-01/dj-mixer-01's second-window presentation path.

SDL2's window-surface software renderer was found to silently create a
second, GL-backed renderer on Linux (see the module docstring in
unicornviz/secondary_gl_window.py and
docs/planning/control-room-mixer-second-window-mitigation-strategies-2026-07-09.md
for the full investigation). These tests exercise SecondaryGLWindow's own
GL bracketing discipline — create()/present()/destroy() must each restore
whatever GL window/context was current before they ran, regardless of
success or failure — using fakes for both sdl2 and moderngl, since SDL's
``dummy`` video driver (used elsewhere in this repo for headless SDL
tests) does not support real GL context creation.
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

    def SDL_GetWindowSize(self, window, w_ref, h_ref) -> None:  # noqa: ARG002
        # Real SDL writes the actual window size back through the pointers;
        # the fake leaves them at their ctypes default (0) so callers keep
        # whatever size they already have — none of these tests exercise a
        # WM overriding the requested size.
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


class _FakeGLObject:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.released = False
        self.filter = None

    def release(self) -> None:
        self.released = True


class _FakeProgram(_FakeGLObject):
    def __init__(self) -> None:
        super().__init__('program')
        self.uniforms: dict[str, object] = {}

    def __setitem__(self, key, value) -> None:
        self.uniforms[key] = value


class _FakeVAO(_FakeGLObject):
    def __init__(self) -> None:
        super().__init__('vao')
        self.render_calls: list[object] = []

    def render(self, mode) -> None:
        self.render_calls.append(mode)


class _FakeTexture(_FakeGLObject):
    def __init__(self, size, components) -> None:
        super().__init__('texture')
        self.size = size
        self.components = components
        self.writes: list[bytes] = []
        self.use_calls: list[int] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def use(self, location: int = 0) -> None:
        self.use_calls.append(location)


class _FakeScreen:
    def __init__(self) -> None:
        self.use_calls = 0
        self.clear_calls: list[tuple] = []
        self.viewport = None

    def use(self) -> None:
        self.use_calls += 1

    def clear(self, r, g, b, a) -> None:
        self.clear_calls.append((r, g, b, a))


class _FakeMglCtx:
    def __init__(self) -> None:
        self.screen = _FakeScreen()
        self.programs: list[_FakeProgram] = []
        self.textures: list[_FakeTexture] = []

    def program(self, vertex_shader, fragment_shader):  # noqa: ARG002
        prog = _FakeProgram()
        self.programs.append(prog)
        return prog

    def buffer(self, data):  # noqa: ARG002
        return _FakeGLObject('buffer')

    def vertex_array(self, program, bindings):  # noqa: ARG002
        return _FakeVAO()

    def texture(self, size, components):
        tex = _FakeTexture(size, components)
        self.textures.append(tex)
        return tex


class _FakeModerngl:
    LINEAR = 'LINEAR'
    TRIANGLE_STRIP = 'TRIANGLE_STRIP'

    def __init__(self) -> None:
        self.created_contexts: list[_FakeMglCtx] = []

    def create_context(self) -> _FakeMglCtx:
        ctx = _FakeMglCtx()
        self.created_contexts.append(ctx)
        return ctx


@pytest.fixture
def fakes(monkeypatch):
    fake_sdl2 = _FakeSDL2()
    fake_mgl = _FakeModerngl()
    monkeypatch.setattr(sgw, 'sdl2', fake_sdl2)
    monkeypatch.setattr(sgw, 'moderngl', fake_mgl)
    return fake_sdl2, fake_mgl


def _make(fakes) -> sgw.SecondaryGLWindow:
    return sgw.SecondaryGLWindow(b'Test Window', 0, 0, 640, 480)


def test_create_builds_window_context_and_pipeline(fakes) -> None:
    fake_sdl2, fake_mgl = fakes
    win = _make(fakes)
    win.create()
    assert win.is_open
    assert win.window_id == 1
    assert win._gl_context is not None  # noqa: SLF001
    assert len(fake_mgl.created_contexts) == 1
    assert fake_sdl2.swap_interval_calls == [0]


def test_create_restores_previously_current_context(fakes) -> None:
    fake_sdl2, _ = fakes
    outer_window = _FakeWindow(99)
    outer_ctx = _FakeGLContext(99)
    fake_sdl2.current_window = outer_window
    fake_sdl2.current_context = outer_ctx

    win = _make(fakes)
    win.create()

    assert fake_sdl2.current_window is outer_window
    assert fake_sdl2.current_context is outer_ctx


def test_create_raises_and_cleans_up_on_window_creation_failure(fakes) -> None:
    fake_sdl2, _ = fakes
    fake_sdl2.fail_create_window = True
    win = _make(fakes)
    with pytest.raises(RuntimeError):
        win.create()
    assert win.window is None
    assert win.is_open is False


def test_create_raises_and_cleans_up_on_context_creation_failure(fakes) -> None:
    fake_sdl2, _ = fakes
    fake_sdl2.fail_create_context = True
    win = _make(fakes)
    with pytest.raises(RuntimeError):
        win.create()
    # The window that was created before the context failed must be torn
    # down too, not leaked.
    assert win.window is None
    assert len(fake_sdl2.destroyed_windows) == 1


def test_present_uploads_draws_and_swaps(fakes) -> None:
    fake_sdl2, fake_mgl = fakes
    win = _make(fakes)
    win.create()
    raw = b'\x00' * (640 * 480 * 4)
    ok = win.present(raw, 640, 480)
    assert ok is True
    ctx = fake_mgl.created_contexts[0]
    assert ctx.textures[-1].writes == [raw]
    assert ctx.screen.use_calls == 1
    assert ctx.screen.clear_calls == [(0.0, 0.0, 0.0, 1.0)]
    assert fake_sdl2.swap_calls == [win.window]


def test_present_returns_false_when_never_created(fakes) -> None:
    win = _make(fakes)
    assert win.present(b'\x00', 640, 480) is False


def test_present_restores_previous_context_on_success(fakes) -> None:
    fake_sdl2, _ = fakes
    win = _make(fakes)
    win.create()
    outer_window = _FakeWindow(42)
    outer_ctx = _FakeGLContext(42)
    fake_sdl2.current_window = outer_window
    fake_sdl2.current_context = outer_ctx

    win.present(b'\x00' * (640 * 480 * 4), 640, 480)

    assert fake_sdl2.current_window is outer_window
    assert fake_sdl2.current_context is outer_ctx


def test_present_restores_previous_context_when_make_current_fails(fakes) -> None:
    fake_sdl2, _ = fakes
    win = _make(fakes)
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
    fake_sdl2, fake_mgl = fakes
    win = _make(fakes)
    win.create()
    outer_window = _FakeWindow(7)
    outer_ctx = _FakeGLContext(7)
    fake_sdl2.current_window = outer_window
    fake_sdl2.current_context = outer_ctx

    def _boom(*_a, **_k):
        raise RuntimeError('draw exploded')

    monkeypatch.setattr(win._vao, 'render', _boom)  # noqa: SLF001
    ok = win.present(b'\x00' * (640 * 480 * 4), 640, 480)

    assert ok is False
    assert fake_sdl2.current_window is outer_window
    assert fake_sdl2.current_context is outer_ctx


def test_present_resizes_texture_only_when_size_changes(fakes) -> None:
    _, fake_mgl = fakes
    win = _make(fakes)
    win.create()
    ctx = fake_mgl.created_contexts[0]
    assert len(ctx.textures) == 1

    win.present(b'\x00' * (640 * 480 * 4), 640, 480)
    assert len(ctx.textures) == 1  # unchanged size: no new texture

    win.present(b'\x00' * (800 * 600 * 4), 800, 600)
    assert len(ctx.textures) == 2  # resized: new texture allocated
    assert ctx.textures[0].released is True
    assert win.width == 800 and win.height == 600


def test_destroy_releases_gl_resources_and_window(fakes) -> None:
    fake_sdl2, fake_mgl = fakes
    win = _make(fakes)
    win.create()
    ctx = fake_mgl.created_contexts[0]
    gl_context = win._gl_context  # noqa: SLF001
    window_obj = win.window

    win.destroy()

    assert win.is_open is False
    assert win.window is None
    assert window_obj.destroyed is True
    assert gl_context.deleted is True
    for prog in ctx.programs:
        assert prog.released is True
    for tex in ctx.textures:
        assert tex.released is True


def test_destroy_is_idempotent(fakes) -> None:
    win = _make(fakes)
    win.create()
    win.destroy()
    win.destroy()  # must not raise


def test_destroy_restores_previously_current_context(fakes) -> None:
    fake_sdl2, _ = fakes
    win = _make(fakes)
    win.create()
    outer_window = _FakeWindow(11)
    outer_ctx = _FakeGLContext(11)
    fake_sdl2.current_window = outer_window
    fake_sdl2.current_context = outer_ctx

    win.destroy()

    assert fake_sdl2.current_window is outer_window
    assert fake_sdl2.current_context is outer_ctx
