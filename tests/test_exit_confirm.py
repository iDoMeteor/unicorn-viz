"""Quit confirmation is an in-app two-press prompt, never a native modal.

Regression for the 2026-09-09 Windows beta: the SDL message box blocked the
render loop under a borderless-fullscreen window (frozen/black screen, TV
signal drops) and sat where a tester with a hidden cursor could not answer it.
"""
from __future__ import annotations

import time

from unicornviz.app import App


class _Overlays:
    def __init__(self) -> None:
        self.flashed: list[tuple[str, float]] = []

    def flash_message(self, msg: str, duration: float = 2.0) -> None:
        self.flashed.append((msg, duration))


def _app(confirm: bool) -> App:
    app = App.__new__(App)
    app._confirm_exit_enabled = confirm
    app._exit_armed_until = 0.0
    app._overlays = _Overlays()
    app._running = True
    return app


def test_second_press_inside_the_window_exits() -> None:
    app = _app(confirm=True)
    assert app.request_exit() is False           # armed, not exited
    assert app._running is True
    assert app._overlays.flashed and 'press again' in app._overlays.flashed[0][0]
    assert app.request_exit() is True
    assert app._running is False


def test_armed_press_expires() -> None:
    app = _app(confirm=True)
    app.request_exit()
    app._exit_armed_until = time.monotonic() - 1.0    # the window has lapsed
    assert app.request_exit() is False                 # re-armed, no exit
    assert app._running is True
    assert len(app._overlays.flashed) == 2


def test_force_and_disabled_confirm_exit_at_once() -> None:
    app = _app(confirm=True)
    assert app.request_exit(force=True) is True and app._running is False
    app = _app(confirm=False)
    assert app.request_exit() is True and app._running is False


def test_no_native_message_box_left_in_core() -> None:
    import inspect
    import unicornviz.app as mod
    assert 'SDL_ShowMessageBox' not in inspect.getsource(mod)
