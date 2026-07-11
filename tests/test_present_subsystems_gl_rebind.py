"""Subsystem present + GL context rebind — regression tests.

Root cause confirmed via apitrace on a live Fedora/GNOME/Wayland session:
control-room-01/dj-mixer-01's SDL_RenderPresent() on their own second SDL
window silently calls eglMakeCurrent to their own internal EGL context and
never switches back. Every subsequent GL call in the main render loop then
runs against the wrong context — none of our app's program/VAO/buffer IDs
exist there — producing a massive glUseProgram(GL_INVALID_VALUE)/
glBindVertexArray(non-gen name)/glUniform(...) cascade for the rest of the
session. _present_subsystems() now rebinds the main GL context after
calling each subsystem's present(), but only when at least one subsystem
actually has a callable present() (control-room/mixer open) — this must
not run on every frame regardless, since rebind_main_gl_context() is a real
SDL_GL_MakeCurrent call and unnecessary work in the hot path when no
subsystem needs it.
"""
from __future__ import annotations

import logging

from unicornviz.app import App


class _StubSubsystemWithPresent:
    def __init__(self, raises: Exception | None = None) -> None:
        self.present_calls = 0
        self._raises = raises

    def present(self) -> None:
        self.present_calls += 1
        if self._raises is not None:
            raise self._raises


class _StubSubsystemWithoutPresent:
    """Represents a subsystem with no present() hook (most of them)."""


def _stub_app(*, subsystems: dict) -> App:
    app = object.__new__(App)
    app._subsystems = subsystems
    app._rebind_calls = 0
    app._last_frame_ms = 0.0
    app._subsys_present_skips = 0

    def _rebind() -> bool:
        app._rebind_calls += 1
        return True

    app.rebind_main_gl_context = _rebind
    return app


def test_rebinds_when_a_subsystem_presents() -> None:
    control_room = _StubSubsystemWithPresent()
    app = _stub_app(subsystems={'control_room': control_room})
    app._present_subsystems()
    assert control_room.present_calls == 1
    assert app._rebind_calls == 1


def test_rebinds_once_even_with_multiple_presenting_subsystems() -> None:
    control_room = _StubSubsystemWithPresent()
    dj_mixer = _StubSubsystemWithPresent()
    app = _stub_app(subsystems={'control_room': control_room, 'dj_mixer': dj_mixer})
    app._present_subsystems()
    assert control_room.present_calls == 1
    assert dj_mixer.present_calls == 1
    assert app._rebind_calls == 1


def test_does_not_rebind_when_no_subsystem_has_present() -> None:
    app = _stub_app(subsystems={'webcam': _StubSubsystemWithoutPresent()})
    app._present_subsystems()
    assert app._rebind_calls == 0


def test_does_not_rebind_when_there_are_no_subsystems() -> None:
    app = _stub_app(subsystems={})
    app._present_subsystems()
    assert app._rebind_calls == 0


def test_still_rebinds_when_present_raises(caplog) -> None:
    # A subsystem attempted to present (and may have already switched the
    # GL context before failing) -- still rebind defensively.
    control_room = _StubSubsystemWithPresent(raises=RuntimeError('boom'))
    app = _stub_app(subsystems={'control_room': control_room})
    with caplog.at_level(logging.WARNING, logger='unicornviz.app'):
        app._present_subsystems()
    assert app._rebind_calls == 1
    assert any('control_room subsystem present failed' in r.message for r in caplog.records)


def test_logs_and_continues_past_a_failing_presenter() -> None:
    control_room = _StubSubsystemWithPresent(raises=RuntimeError('boom'))
    dj_mixer = _StubSubsystemWithPresent()
    app = _stub_app(subsystems={'control_room': control_room, 'dj_mixer': dj_mixer})
    app._present_subsystems()
    assert dj_mixer.present_calls == 1
    assert app._rebind_calls == 1


def test_skips_present_when_previous_frame_overbudget() -> None:
    from unicornviz.app import _SUBSYS_PRESENT_SKIP_MS

    mixer = _StubSubsystemWithPresent()
    app = _stub_app(subsystems={'dj_mixer': mixer})
    app._last_frame_ms = _SUBSYS_PRESENT_SKIP_MS + 1.0
    app._present_subsystems()
    assert mixer.present_calls == 0
    assert app._rebind_calls == 0
    assert app._subsys_present_skips == 1


def test_presents_at_or_under_budget_threshold() -> None:
    from unicornviz.app import _SUBSYS_PRESENT_SKIP_MS

    mixer = _StubSubsystemWithPresent()
    app = _stub_app(subsystems={'dj_mixer': mixer})
    app._last_frame_ms = _SUBSYS_PRESENT_SKIP_MS  # not strictly over
    app._present_subsystems()
    assert mixer.present_calls == 1
    assert app._subsys_present_skips == 0


def test_consecutive_skips_are_capped_under_sustained_overload() -> None:
    from unicornviz.app import _SUBSYS_PRESENT_MAX_SKIPS, _SUBSYS_PRESENT_SKIP_MS

    mixer = _StubSubsystemWithPresent()
    app = _stub_app(subsystems={'dj_mixer': mixer})
    app._last_frame_ms = _SUBSYS_PRESENT_SKIP_MS * 4.0
    for _ in range(_SUBSYS_PRESENT_MAX_SKIPS + 1):
        app._present_subsystems()
    # Skipped MAX times, then presented anyway so the window cannot freeze.
    assert mixer.present_calls == 1
    assert app._subsys_present_skips == 0


def test_good_frame_resets_skip_counter() -> None:
    from unicornviz.app import _SUBSYS_PRESENT_SKIP_MS

    mixer = _StubSubsystemWithPresent()
    app = _stub_app(subsystems={'dj_mixer': mixer})
    app._last_frame_ms = _SUBSYS_PRESENT_SKIP_MS + 1.0
    app._present_subsystems()
    assert app._subsys_present_skips == 1
    app._last_frame_ms = 5.0
    app._present_subsystems()
    assert mixer.present_calls == 1
    assert app._subsys_present_skips == 0
