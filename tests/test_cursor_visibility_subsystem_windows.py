"""Regression tests: the OS cursor must become visible whenever a
subsystem's own window (control-room-01, dj-mixer-01) is open.

SDL_ShowCursor is a single, process-global setting -- it can't be scoped
to one window. control-room-01 used to call SDL_ShowCursor(ENABLE)
directly from its own present(), racing every frame against the main
loop's own SDL_ShowCursor(DISABLE) policy call (App._set_cursor_visible
via _cursor_should_be_visible(), which runs earlier in the frame) and
often losing -- reported as the operator's mouse cursor being invisible
or flickery over control-room/mixer windows. Centralizing the check in
App._cursor_should_be_visible() via App._subsystem_window_open() means
there is exactly one place per frame that decides cursor visibility.
"""
from __future__ import annotations

from unicornviz.app import App


class _StubSubsystemOpen:
    is_open = True


class _StubSubsystemClosed:
    is_open = False


class _StubSubsystemWithoutIsOpen:
    """Represents a subsystem with no is_open attribute (most of them)."""


def _stub_app(*, subsystems: dict, show_cursor_default: bool = False,
              ctrl_held: bool = False) -> App:
    app = object.__new__(App)
    app._subsystems = subsystems
    app._show_cursor_default = show_cursor_default
    app._ctrl_held = ctrl_held
    app._overlays = None
    return app


def test_subsystem_window_open_true_when_any_subsystem_is_open() -> None:
    app = _stub_app(subsystems={'control_room': _StubSubsystemOpen()})
    assert app._subsystem_window_open() is True


def test_subsystem_window_open_false_when_no_subsystem_is_open() -> None:
    app = _stub_app(subsystems={
        'control_room': _StubSubsystemClosed(),
        'webcam': _StubSubsystemWithoutIsOpen(),
    })
    assert app._subsystem_window_open() is False


def test_subsystem_window_open_false_with_no_subsystems() -> None:
    app = _stub_app(subsystems={})
    assert app._subsystem_window_open() is False


def test_subsystem_window_open_ignores_subsystems_without_is_open() -> None:
    app = _stub_app(subsystems={'webcam': _StubSubsystemWithoutIsOpen()})
    assert app._subsystem_window_open() is False


def test_cursor_should_be_visible_true_when_a_subsystem_window_is_open() -> None:
    app = _stub_app(subsystems={'dj_mixer': _StubSubsystemOpen()})
    assert app._cursor_should_be_visible() is True


def test_cursor_should_be_visible_false_by_default_with_no_open_windows() -> None:
    app = _stub_app(subsystems={'dj_mixer': _StubSubsystemClosed()})
    assert app._cursor_should_be_visible() is False


def test_cursor_should_be_visible_still_honors_show_cursor_default() -> None:
    app = _stub_app(subsystems={}, show_cursor_default=True)
    assert app._cursor_should_be_visible() is True


def test_cursor_should_be_visible_still_honors_ctrl_held() -> None:
    app = _stub_app(subsystems={}, ctrl_held=True)
    assert app._cursor_should_be_visible() is True
