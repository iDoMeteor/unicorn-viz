"""Windows fullscreen is a borderless window, never SDL's fullscreen flag.

Regression for the 2026-09-09 Windows beta: with SDL_WINDOW_FULLSCREEN_DESKTOP
Windows treats the app as a fullscreen game (fullscreen optimizations, flip
presentation) and every Alt+Tab / Win key flips the display path -- the TV
drops signal and the render loop stalls for seconds. A borderless window
covering the display is composited like any other window.

2026-09-19 follow-up: that alone did not fix it. Windows' Fullscreen
Optimizations heuristic classifies any borderless window that exactly
covers a monitor as a fullscreen game, regardless of which SDL flag was
used to create it -- so the "video game mode reset" persisted on beta.152.
The only opt-out is the same one behind the exe's own Properties >
Compatibility checkbox: a per-executable-path registry value.
"""
from __future__ import annotations

import sys

import unicornviz.app as app_mod
from unicornviz.app import App

_LAYERS_KEY = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers'


class _FakeRegKey:
    """Stands in for the context manager winreg.CreateKeyEx() returns."""

    def __init__(self, subkey: str) -> None:
        self.subkey = subkey

    def __enter__(self) -> '_FakeRegKey':
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeWinreg:
    """Minimal in-memory stand-in for the winreg module.

    Only the four names app.py actually calls: HKEY_CURRENT_USER, REG_SZ,
    CreateKeyEx, QueryValueEx, SetValueEx.
    """

    HKEY_CURRENT_USER = object()
    REG_SZ = 1

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def CreateKeyEx(self, hive: object, subkey: str) -> _FakeRegKey:
        assert hive is self.HKEY_CURRENT_USER
        return _FakeRegKey(subkey)

    def QueryValueEx(self, key: _FakeRegKey, name: str) -> tuple[str, int]:
        try:
            return self.values[(key.subkey, name)], self.REG_SZ
        except KeyError:
            raise FileNotFoundError(name) from None

    def SetValueEx(self, key: _FakeRegKey, name: str, reserved: int,  # noqa: ARG002
                   type_: int, data: str) -> None:  # noqa: ARG002
        self.values[(key.subkey, name)] = data


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


def _bare_app() -> App:
    return object.__new__(App)


def test_disables_fullscreen_optimizations_for_the_running_interpreter(monkeypatch) -> None:
    monkeypatch.setattr(app_mod.sys, 'platform', 'win32')
    monkeypatch.setattr(app_mod.sys, 'executable', r'C:\UnicornViz\runtime\python\pythonw.exe')
    fake = _FakeWinreg()
    monkeypatch.setitem(sys.modules, 'winreg', fake)
    _bare_app()._disable_windows_fullscreen_optimizations()
    exe = r'C:\UnicornViz\runtime\python\pythonw.exe'
    assert fake.values[(_LAYERS_KEY, exe)] == '~ DISABLEDXMAXIMIZEDWINDOWEDMODE'


def test_merges_into_an_existing_compat_flag_rather_than_overwriting_it(monkeypatch) -> None:
    monkeypatch.setattr(app_mod.sys, 'platform', 'win32')
    exe = r'C:\UnicornViz\runtime\python\python.exe'
    monkeypatch.setattr(app_mod.sys, 'executable', exe)
    fake = _FakeWinreg()
    fake.values[(_LAYERS_KEY, exe)] = '~ HIGHDPIAWARE'
    monkeypatch.setitem(sys.modules, 'winreg', fake)
    _bare_app()._disable_windows_fullscreen_optimizations()
    assert fake.values[(_LAYERS_KEY, exe)] == '~ HIGHDPIAWARE DISABLEDXMAXIMIZEDWINDOWEDMODE'


def test_is_idempotent_once_the_flag_is_already_set(monkeypatch) -> None:
    monkeypatch.setattr(app_mod.sys, 'platform', 'win32')
    exe = r'C:\UnicornViz\runtime\python\pythonw.exe'
    monkeypatch.setattr(app_mod.sys, 'executable', exe)
    fake = _FakeWinreg()
    fake.values[(_LAYERS_KEY, exe)] = '~ DISABLEDXMAXIMIZEDWINDOWEDMODE'
    monkeypatch.setitem(sys.modules, 'winreg', fake)
    _bare_app()._disable_windows_fullscreen_optimizations()
    assert fake.values[(_LAYERS_KEY, exe)] == '~ DISABLEDXMAXIMIZEDWINDOWEDMODE'


def test_never_touches_the_registry_on_linux(monkeypatch) -> None:
    monkeypatch.setattr(app_mod.sys, 'platform', 'linux')
    monkeypatch.delitem(sys.modules, 'winreg', raising=False)
    # No winreg on the import path here; a real import attempt would raise.
    _bare_app()._disable_windows_fullscreen_optimizations()


def test_a_broken_registry_never_crashes_startup(monkeypatch) -> None:
    monkeypatch.setattr(app_mod.sys, 'platform', 'win32')
    monkeypatch.setattr(app_mod.sys, 'executable', r'C:\UnicornViz\runtime\python\python.exe')

    class _ExplodingWinreg:
        HKEY_CURRENT_USER = object()

        def CreateKeyEx(self, *_a: object, **_k: object) -> None:
            raise OSError('registry access denied')

    monkeypatch.setitem(sys.modules, 'winreg', _ExplodingWinreg())
    _bare_app()._disable_windows_fullscreen_optimizations()  # must not raise
