"""Regression tests for the Xlib BadMatch/X_SetInputFocus guard (2026-09-12).

Switching display mode on the X11 driver under XWayland killed the process
with ``X Error of failed request: BadMatch ... X_SetInputFocus`` -- an SDL
race inside ``X11_SetWindowBordered``.  The guard must swallow exactly that
error and forward everything else to the handler that was there before.
"""
from __future__ import annotations

import ctypes

import pytest

from unicornviz import x11_errors


def _event(error_code: int, request_code: int, serial: int = 7) -> x11_errors.XErrorEvent:
    ev = x11_errors.XErrorEvent()
    ev.error_code = error_code
    ev.request_code = request_code
    ev.serial = serial
    ev.resourceid = 0x1234
    return ev


def test_should_swallow_only_badmatch_on_setinputfocus() -> None:
    assert x11_errors.should_swallow(x11_errors.BAD_MATCH, x11_errors.X_SET_INPUT_FOCUS)
    assert not x11_errors.should_swallow(x11_errors.BAD_MATCH, 12)         # ConfigureWindow
    assert not x11_errors.should_swallow(3, x11_errors.X_SET_INPUT_FOCUS)  # BadWindow


def test_handler_swallows_the_focus_race_and_chains_everything_else(monkeypatch) -> None:
    seen: list[tuple[int, int]] = []

    def previous(display, event_ptr):
        ev = event_ptr.contents
        seen.append((ev.error_code, ev.request_code))
        return 42

    monkeypatch.setattr(x11_errors, '_previous', x11_errors.XErrorHandlerType(previous))
    focus = _event(x11_errors.BAD_MATCH, x11_errors.X_SET_INPUT_FOCUS)
    assert x11_errors._handle(0, ctypes.pointer(focus)) == 0
    assert seen == []
    other = _event(3, 12)
    assert x11_errors._handle(0, ctypes.pointer(other)) == 42
    assert seen == [(3, 12)]


def test_handler_without_previous_returns_zero(monkeypatch) -> None:
    monkeypatch.setattr(x11_errors, '_previous', None)
    other = _event(3, 12)
    assert x11_errors._handle(0, ctypes.pointer(other)) == 0


def test_install_is_a_noop_without_libx11(monkeypatch) -> None:
    monkeypatch.setattr(x11_errors, '_guard', None)
    monkeypatch.setattr(x11_errors, '_previous', None)
    monkeypatch.setattr(x11_errors.ctypes.util, 'find_library', lambda _name: None)
    assert x11_errors.install_focus_error_guard() is False
    assert x11_errors._guard is None


def test_install_chains_the_previous_handler(monkeypatch) -> None:
    monkeypatch.setattr(x11_errors, '_guard', None)
    monkeypatch.setattr(x11_errors, '_previous', None)
    monkeypatch.setattr(x11_errors.ctypes.util, 'find_library', lambda _name: 'libX11.so.6')
    installed: list = []

    class _Lib:
        @staticmethod
        def XSetErrorHandler(handler):
            installed.append(handler)
            return x11_errors.XErrorHandlerType(lambda d, e: 99)

    monkeypatch.setattr(x11_errors.ctypes, 'CDLL', lambda _name: _Lib())
    assert x11_errors.install_focus_error_guard() is True
    assert len(installed) == 1 and x11_errors._previous is not None
    # Second call is idempotent: nothing re-installed.
    assert x11_errors.install_focus_error_guard() is True
    assert len(installed) == 1
    other = _event(3, 12)
    assert x11_errors._handle(0, ctypes.pointer(other)) == 99


@pytest.mark.skipif(ctypes.util.find_library('X11') is None, reason='libX11 not present')
def test_install_against_real_libx11(monkeypatch) -> None:
    """On a machine with libX11 the real XSetErrorHandler must accept the guard."""
    monkeypatch.setattr(x11_errors, '_guard', None)
    monkeypatch.setattr(x11_errors, '_previous', None)
    assert x11_errors.install_focus_error_guard() is True
