"""Windows fullscreen is a borderless window, never SDL's fullscreen flag.

Regression for the 2026-09-09 Windows beta: with SDL_WINDOW_FULLSCREEN_DESKTOP
Windows treats the app as a fullscreen game (fullscreen optimizations, flip
presentation) and every Alt+Tab / Win key flips the display path -- the TV
drops signal and the render loop stalls for seconds. A borderless window
covering the display is composited like any other window.
"""
from __future__ import annotations

import unicornviz.app as app_mod
from unicornviz.app import App


def _app(mode: str) -> App:
    app = object.__new__(App)
    app._fullscreen_mode = mode
    return app


def test_windows_auto_prefers_borderless(monkeypatch) -> None:
    monkeypatch.setattr(app_mod.sys, 'platform', 'win32')
    assert _app('auto')._prefer_borderless_fullscreen() is True


def test_windows_explicit_desktop_still_opts_in(monkeypatch) -> None:
    monkeypatch.setattr(app_mod.sys, 'platform', 'win32')
    assert _app('desktop')._prefer_borderless_fullscreen() is False
    assert _app('borderless')._prefer_borderless_fullscreen() is True


def test_linux_auto_is_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(app_mod.sys, 'platform', 'linux')
    for var in ('XDG_CURRENT_DESKTOP', 'XDG_SESSION_DESKTOP', 'DESKTOP_SESSION'):
        monkeypatch.setenv(var, 'GNOME')
    assert _app('auto')._prefer_borderless_fullscreen() is False
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'MATE')
    assert _app('auto')._prefer_borderless_fullscreen() is True
