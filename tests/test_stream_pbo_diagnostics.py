"""Streaming-PBO failure diagnostics — regression tests.

``_disable_stream_pbo`` is the shared teardown path _read_streaming_frame()
calls when either the async write (read_into) or read (buffer.read) side of
the double-buffered PBO fails. Historically this only logged moderngl's
generic wrapper message ("cannot map the buffer"); it now also logs which
specific call failed, the raw glGetError() code, and buffer/canvas context,
since that's what's needed to diagnose *why* a given driver fails (see
docs/audits/2026-07-08-render-pipeline-platform-audit.md §8 item 9).
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
