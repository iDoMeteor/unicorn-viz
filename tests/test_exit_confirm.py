"""Quit confirmation is a native yes/no dialog (owner decision, 2026-09-12).

The in-app "press again" prompt of beta.121 is gone; the dialog's answer
decides, `force=True` and a disabled confirmation skip it.
"""
from __future__ import annotations

from unicornviz.app import App


def _app(confirm: bool, answer: bool) -> App:
    app = App.__new__(App)
    app._confirm_exit_enabled = confirm
    app._running = True
    app.asked = 0

    def _dialog() -> bool:
        app.asked += 1
        return answer

    app._confirm_exit_dialog = _dialog
    return app


def test_yes_exits_and_no_keeps_running() -> None:
    app = _app(confirm=True, answer=True)
    assert app.request_exit() is True and app._running is False and app.asked == 1
    app = _app(confirm=True, answer=False)
    assert app.request_exit() is False and app._running is True and app.asked == 1


def test_force_and_disabled_confirm_skip_the_dialog() -> None:
    app = _app(confirm=True, answer=False)
    assert app.request_exit(force=True) is True and app._running is False and app.asked == 0
    app = _app(confirm=False, answer=False)
    assert app.request_exit() is True and app._running is False and app.asked == 0


def test_no_window_means_no_dialog() -> None:
    app = App.__new__(App)
    app._window = None
    assert app._confirm_exit_dialog() is True
