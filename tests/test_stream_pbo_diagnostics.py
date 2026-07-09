"""Streaming-PBO failure diagnostics and default-framebuffer-read workaround
— regression tests.

``_disable_stream_pbo`` is the shared teardown path _read_streaming_frame()
calls when either the async write (read_into) or read (buffer.read) side of
the double-buffered PBO fails. Historically this only logged moderngl's
generic wrapper message ("cannot map the buffer"); it now also logs which
specific call failed, the raw glGetError() code, and buffer/canvas context,
since that's what's needed to diagnose *why* a given driver fails.

The real root cause (confirmed via live MESA_DEBUG capture: 0 GL errors in
a session with control-room/mixer never opened vs. ~408k in an otherwise
identical session with them open) is a moderngl bug: Framebuffer.read()/
read_into() unconditionally issue glReadBuffer(GL_COLOR_ATTACHMENT0 +
attachment), which is invalid for the default framebuffer (framebuffer_obj
== 0) per the GL spec. moderngl's own context-init code carries a comment
acknowledging this exact issue for draw_buffers ("GL_COLOR_ATTACHMENT0 is
causes error: 1282") but the equivalent fix was never applied to the read
path. _read_streaming_frame() and read_screenshot_frame() now never call
.read()/.read_into() on self._ctx.screen directly — they blit it into a
real FBO via copy_framebuffer() first (which correctly uses the queried
GL_BACK/FRONT draw buffer, not a hardcoded attachment enum) and read from
that instead. See docs/audits/2026-07-08-render-pipeline-platform-audit.md
§8 item 11.
"""
from __future__ import annotations

import logging

from unicornviz.app import App


class _FakePbo:
    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


class _FakeCtx:
    def __init__(self, error: str = 'GL_INVALID_OPERATION') -> None:
        self.error = error


def _stub_app(*, gl_error: str | None = 'GL_INVALID_OPERATION') -> App:
    app = object.__new__(App)
    app._ctx = _FakeCtx(gl_error) if gl_error is not None else None
    app._stream_pbos = [_FakePbo(), _FakePbo()]
    app._stream_pbo_size = 12345
    app._stream_pbo_primed = True
    app._stream_pbo_index = 1
    app._stream_pbo_frame_count = 7
    app._stream_pbo_disabled = False
    app._width = 3840
    app._height = 2160
    return app


def test_logs_which_call_failed_and_gl_error(caplog) -> None:
    app = _stub_app(gl_error='GL_OUT_OF_MEMORY')
    with caplog.at_level(logging.WARNING, logger='unicornviz.app'):
        app._disable_stream_pbo('read (buffer.read)', RuntimeError('cannot map the buffer'), 99, True)
    msg = caplog.records[-1].message
    assert 'read (buffer.read)' in msg
    assert 'GL_OUT_OF_MEMORY' in msg
    assert 'cannot map the buffer' in msg


def test_logs_frame_count_buffer_size_and_canvas(caplog) -> None:
    app = _stub_app()
    with caplog.at_level(logging.WARNING, logger='unicornviz.app'):
        app._disable_stream_pbo('write (read_into)', RuntimeError('boom'), 99, False)
    msg = caplog.records[-1].message
    assert '7 prior successful frame' in msg
    assert 'buffer_bytes=99' in msg
    assert 'canvas=3840x2160' in msg
    assert 'mirror_mode=False' in msg


def test_survives_a_missing_gl_context(caplog) -> None:
    app = _stub_app(gl_error=None)
    with caplog.at_level(logging.WARNING, logger='unicornviz.app'):
        app._disable_stream_pbo('write (read_into)', RuntimeError('boom'), 99, False)
    assert 'gl_error=None' in caplog.records[-1].message


def test_releases_pbos_and_resets_state() -> None:
    app = _stub_app()
    pbos = list(app._stream_pbos)
    app._disable_stream_pbo('write (read_into)', RuntimeError('boom'), 99, False)
    assert all(pbo.released for pbo in pbos)
    assert app._stream_pbos == []
    assert app._stream_pbo_size == 0
    assert app._stream_pbo_primed is False
    assert app._stream_pbo_index == 0
    assert app._stream_pbo_frame_count == 0
    assert app._stream_pbo_disabled is True


# --------------------------------------------------------------------------- #
# _read_streaming_frame / read_screenshot_frame: never read ctx.screen
# directly — always blit into a real FBO first (_ensure_screen_copy_fbo)
# --------------------------------------------------------------------------- #


class _FakeStreamBuffer:
    def __init__(self, reserve: int) -> None:
        self.reserve = reserve
        self.released = False

    def read(self, size: int = -1, offset: int = 0) -> bytes:  # noqa: ARG002
        return b'\x00' * self.reserve

    def release(self) -> None:
        self.released = True


class _FakeScreen:
    """Fake for ctx.screen — the default framebuffer. Deliberately has NO
    read()/read_into() methods: if application code ever calls them on this
    object directly again (the historical bug), the test fails with an
    AttributeError instead of silently passing."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height


class _FakeTexture:
    def __init__(self, size: tuple[int, int], components: int) -> None:
        self.size = size
        self.components = components


class _FakeFbo:
    """Fake for a real FBO (self._fbo_a or the new _screen_copy_fbo)."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.released = False
        self.use_calls = 0
        self.read_into_calls: list[dict] = []
        self.read_calls: list[dict] = []

    def use(self) -> None:
        self.use_calls += 1

    def read_into(self, buffer, viewport=None, components=3, alignment=1, **kwargs) -> None:  # noqa: ARG002
        self.read_into_calls.append({'viewport': viewport})

    def read(self, viewport=None, components=3, alignment=1, **kwargs) -> bytes:  # noqa: ARG002
        self.read_calls.append({'viewport': viewport})
        return b'\x00' * 3

    def release(self) -> None:
        self.released = True


class _FakeStreamCtx:
    def __init__(self, screen: _FakeScreen) -> None:
        self.error = 'GL_NO_ERROR'
        self.screen = screen
        self.copy_framebuffer_calls: list[dict] = []
        self.texture_calls: list[dict] = []
        self.framebuffer_calls = 0

    def buffer(self, reserve: int) -> _FakeStreamBuffer:
        return _FakeStreamBuffer(reserve)

    def texture(self, size: tuple[int, int], components: int) -> _FakeTexture:
        self.texture_calls.append({'size': size, 'components': components})
        return _FakeTexture(size, components)

    def framebuffer(self, color_attachments: list[_FakeTexture], depth_attachment=None) -> _FakeFbo:
        self.framebuffer_calls += 1
        w, h = color_attachments[0].size
        fbo = _FakeFbo(w, h)
        fbo.depth_attachment = depth_attachment
        return fbo

    def depth_renderbuffer(self, size: tuple[int, int]):
        return ('depth_renderbuffer', size)

    def copy_framebuffer(self, dst, src) -> None:
        self.copy_framebuffer_calls.append({'dst': dst, 'src': src})


def _stream_frame_app(*, tracked_size: tuple[int, int], screen_size: tuple[int, int]) -> tuple[App, _FakeScreen]:
    app = object.__new__(App)
    screen = _FakeScreen(*screen_size)
    app._ctx = _FakeStreamCtx(screen)
    app._width, app._height = tracked_size
    app._display_mode = 'single'
    app._mirror_rects = []
    app._fbo_a = None
    app._screen_copy_fbo = None
    app._stream_pbos = []
    app._stream_pbo_size = 0
    app._stream_pbo_index = 0
    app._stream_pbo_primed = False
    app._stream_pbo_frame_count = 0
    app._stream_pbo_disabled = False
    app._stream_viewport_mismatch_logged = False
    return app, screen


def test_ctx_screen_is_never_read_directly() -> None:
    # _FakeScreen has no read()/read_into() — this would AttributeError if
    # the code regressed to reading ctx.screen directly.
    app, _screen = _stream_frame_app(tracked_size=(1920, 1080), screen_size=(1920, 1080))
    app._read_streaming_frame()


def test_screen_is_blitted_into_the_copy_fbo() -> None:
    app, screen = _stream_frame_app(tracked_size=(1920, 1080), screen_size=(1920, 1080))
    app._read_streaming_frame()
    assert len(app._ctx.copy_framebuffer_calls) == 1
    call = app._ctx.copy_framebuffer_calls[0]
    assert call['src'] is screen
    assert call['dst'] is app._screen_copy_fbo


def test_copy_fbo_has_a_depth_attachment() -> None:
    # Regression: copy_framebuffer()/glBlitFramebuffer always blits
    # GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT (moderngl has no color-only
    # blit) — a color-only destination FBO hits GL_INVALID_FRAMEBUFFER_
    # OPERATION (incomplete draw/read buffers) on the blit.
    app, _screen = _stream_frame_app(tracked_size=(1920, 1080), screen_size=(1920, 1080))
    app._read_streaming_frame()
    assert app._screen_copy_fbo.depth_attachment is not None


def test_copy_fbo_sized_to_tracked_canvas_not_screen_size() -> None:
    app, _screen = _stream_frame_app(tracked_size=(1920, 1080), screen_size=(3840, 2160))
    app._read_streaming_frame()
    assert (app._screen_copy_fbo.width, app._screen_copy_fbo.height) == (1920, 1080)


def test_copy_fbo_reused_across_calls_when_size_unchanged() -> None:
    app, _screen = _stream_frame_app(tracked_size=(1920, 1080), screen_size=(1920, 1080))
    app._read_streaming_frame()
    first_fbo = app._screen_copy_fbo
    app._read_streaming_frame()
    assert app._screen_copy_fbo is first_fbo
    assert app._ctx.framebuffer_calls == 1


def test_copy_fbo_recreated_when_tracked_canvas_size_changes() -> None:
    app, _screen = _stream_frame_app(tracked_size=(1920, 1080), screen_size=(1920, 1080))
    app._read_streaming_frame()
    first_fbo = app._screen_copy_fbo
    app._width, app._height = 1280, 720
    app._read_streaming_frame()
    assert app._screen_copy_fbo is not first_fbo
    assert first_fbo.released is True
    assert (app._screen_copy_fbo.width, app._screen_copy_fbo.height) == (1280, 720)


def test_viewport_pinned_to_tracked_canvas_size() -> None:
    app, _screen = _stream_frame_app(tracked_size=(1920, 1080), screen_size=(3840, 2160))
    app._read_streaming_frame()
    assert app._screen_copy_fbo.read_into_calls[-1]['viewport'] == (0, 0, 1920, 1080)


def test_copy_fbo_is_rebound_before_reading() -> None:
    app, _screen = _stream_frame_app(tracked_size=(1920, 1080), screen_size=(1920, 1080))
    app._read_streaming_frame()
    assert app._screen_copy_fbo.use_calls >= 1


def test_no_mismatch_warning_since_copy_fbo_always_matches_tracked_size(caplog) -> None:
    # The copy FBO is always allocated at (self._width, self._height), so
    # the mismatch-detection warning should never fire for the screen path
    # regardless of what size ctx.screen itself reports.
    app, _screen = _stream_frame_app(tracked_size=(1920, 1080), screen_size=(3840, 2160))
    with caplog.at_level(logging.WARNING, logger='unicornviz.app'):
        app._read_streaming_frame()
    assert not [r for r in caplog.records if 'does not match' in r.message]


# --------------------------------------------------------------------------- #
# read_screenshot_frame: same fix applied to the S-key screenshot path
# --------------------------------------------------------------------------- #


def test_screenshot_never_reads_ctx_screen_directly(monkeypatch) -> None:
    import unicornviz.app as app_module

    app = object.__new__(App)
    screen = _FakeScreen(1920, 1080)
    app._ctx = _FakeStreamCtx(screen)
    app._window = object()  # just needs to be truthy
    app._width, app._height = 1920, 1080
    app._window_width, app._window_height = 1920, 1080
    app._screen_copy_fbo = None

    def _fake_get_drawable_size(_window, w_ref, h_ref) -> None:
        w_ref.value = 1920
        h_ref.value = 1080

    monkeypatch.setattr(app_module.sdl2, 'SDL_GL_GetDrawableSize', _fake_get_drawable_size)

    data, w, h = app.read_screenshot_frame()
    assert (w, h) == (1920, 1080)
    assert len(app._ctx.copy_framebuffer_calls) == 1
    assert app._ctx.copy_framebuffer_calls[0]['src'] is screen
    assert app._screen_copy_fbo.read_calls  # read() was called on the copy, not the screen
