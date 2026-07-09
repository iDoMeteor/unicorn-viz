"""Regression tests: VJApi.dispatch_subwindow_keydown/keyup must pass
through to the underlying App methods of the same name.

Subsystem-owned windows (control-room-01, dj-mixer-01) only have access to
app.vj_api, not the raw App instance, so this pass-through is what lets
their own SDL event handlers forward keyboard events (including modifier
state like Ctrl, and hotkeys like Shift+D to close the mixer) to the main
app's hotkey dispatch while their own window has OS input focus.
"""
from __future__ import annotations

from unicornviz.vj_api import VJApi


class _FakeApp:
    def __init__(self) -> None:
        self.keydown_calls: list[tuple] = []
        self.keyup_calls: list[int] = []

    def dispatch_subwindow_keydown(self, sym: int, mod: int, repeat: bool = False) -> None:
        self.keydown_calls.append((sym, mod, repeat))

    def dispatch_subwindow_keyup(self, sym: int) -> None:
        self.keyup_calls.append(sym)


def test_dispatch_subwindow_keydown_passes_through() -> None:
    app = _FakeApp()
    vj = VJApi(app)
    vj.dispatch_subwindow_keydown(100, 0x1000, True)
    assert app.keydown_calls == [(100, 0x1000, True)]


def test_dispatch_subwindow_keydown_defaults_repeat_to_false() -> None:
    app = _FakeApp()
    vj = VJApi(app)
    vj.dispatch_subwindow_keydown(100, 0x1000)
    assert app.keydown_calls == [(100, 0x1000, False)]


def test_dispatch_subwindow_keyup_passes_through() -> None:
    app = _FakeApp()
    vj = VJApi(app)
    vj.dispatch_subwindow_keyup(100)
    assert app.keyup_calls == [100]
