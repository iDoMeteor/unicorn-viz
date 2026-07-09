"""Streaming-PBO failure diagnostics and viewport pinning — regression tests.

``_disable_stream_pbo`` is the shared teardown path _read_streaming_frame()
calls when either the async write (read_into) or read (buffer.read) side of
the double-buffered PBO fails. Historically this only logged moderngl's
generic wrapper message ("cannot map the buffer"); it now also logs which
specific call failed, the raw glGetError() code, and buffer/canvas context,
since that's what's needed to diagnose *why* a given driver fails (see
docs/audits/2026-07-08-render-pipeline-platform-audit.md §8 item 9).

_read_streaming_frame() now also pins an explicit viewport to
(self._width, self._height) rather than letting Framebuffer.read/read_into
default to the source framebuffer's own reported size — a mismatch there
(e.g. under mixed-DPI multi-monitor scaling) would size the PBOs for one
canvas while read_into() writes a different amount of data into them,
which live debugging traced to a GL_INVALID_VALUE surfacing on the
*following* frame's buffer.read() rather than on the write itself.
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
# _read_streaming_frame: explicit viewport pinning
# --------------------------------------------------------------------------- #


class _FakeStreamBuffer:
    def __init__(self, reserve: int) -> None:
        self.reserve = reserve
        self.released = False

    def read(self, size: int = -1, offset: int = 0) -> bytes:  # noqa: ARG002
        return b'\x00' * self.reserve

    def release(self) -> None:
        self.released = True


class _FakeStreamCtx:
    def __init__(self) -> None:
        self.error = 'GL_NO_ERROR'

    def buffer(self, reserve: int) -> _FakeStreamBuffer:
        return _FakeStreamBuffer(reserve)


class _FakeSource:
    """Framebuffer-like fake whose reported (width, height) can diverge from
    the App's own tracked (self._width, self._height) — the exact scenario
    that produced GL_INVALID_VALUE in the field."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.read_into_calls: list[dict] = []
        self.read_calls: list[dict] = []

    def read_into(self, buffer, viewport=None, components=3, alignment=1, **kwargs) -> None:  # noqa: ARG002
        self.read_into_calls.append({'viewport': viewport})

    def read(self, viewport=None, components=3, alignment=1, **kwargs) -> bytes:  # noqa: ARG002
        self.read_calls.append({'viewport': viewport})
        return b'\x00' * 3


def _stream_frame_app(*, tracked_size: tuple[int, int], source_size: tuple[int, int]) -> tuple[App, _FakeSource]:
    app = object.__new__(App)
    app._ctx = _FakeStreamCtx()
    app._width, app._height = tracked_size
    app._display_mode = 'single'
    app._mirror_rects = []
    app._fbo_a = None
    app._stream_pbos = []
    app._stream_pbo_size = 0
    app._stream_pbo_index = 0
    app._stream_pbo_primed = False
    app._stream_pbo_frame_count = 0
    app._stream_pbo_disabled = False
    app._stream_viewport_mismatch_logged = False
    source = _FakeSource(*source_size)
    app._ctx.screen = source
    return app, source


def test_viewport_pinned_to_tracked_size_even_when_source_reports_larger() -> None:
    app, source = _stream_frame_app(tracked_size=(1920, 1080), source_size=(3840, 2160))
    app._read_streaming_frame()
    assert source.read_into_calls[-1]['viewport'] == (0, 0, 1920, 1080)


def test_logs_mismatch_warning_exactly_once(caplog) -> None:
    app, _source = _stream_frame_app(tracked_size=(1920, 1080), source_size=(3840, 2160))
    with caplog.at_level(logging.WARNING, logger='unicornviz.app'):
        app._read_streaming_frame()
        app._read_streaming_frame()
    mismatch_records = [r for r in caplog.records if 'does not match' in r.message]
    assert len(mismatch_records) == 1
    assert app._stream_viewport_mismatch_logged is True


def test_no_mismatch_warning_when_sizes_agree(caplog) -> None:
    app, _source = _stream_frame_app(tracked_size=(1920, 1080), source_size=(1920, 1080))
    with caplog.at_level(logging.WARNING, logger='unicornviz.app'):
        app._read_streaming_frame()
    assert not [r for r in caplog.records if 'does not match' in r.message]
