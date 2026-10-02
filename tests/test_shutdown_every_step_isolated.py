"""G3 (rest): one failing teardown step never skips the others (audit 2026-09-30).

``_shutdown_complete`` is set before teardown starts, so an exception that
escaped one step skipped everything after it for good, including the runtime
state save and the GL/SDL teardown.  Each test makes exactly one step raise and
checks that every other step, the save and SDL still ran.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import unicornviz.app as app_mod
from unicornviz.app import App


class _Boom(RuntimeError):
    pass


class _Rec:
    """A teardown target: records its call, raises when told to."""

    def __init__(self, log: list[str], name: str, boom: set[str], method: str = 'destroy') -> None:
        self._log, self._name, self._boom = log, name, boom
        setattr(self, method, self._call)

    def _call(self, *_a, **_k) -> None:
        self._log.append(self._name)
        if self._name in self._boom:
            raise _Boom(self._name)


def _build(boom: set[str]):
    log: list[str] = []
    app = App.__new__(App)

    def rec(name: str, method: str = 'destroy') -> _Rec:
        return _Rec(log, name, boom, method)

    def fn(name: str):
        def _f(*_a, **_k):
            log.append(name)
            if name in boom:
                raise _Boom(name)
        return _f

    app._shutdown_complete = False
    app._flush_profile_autosave = fn('profile autosave')
    app._recorder = rec('recorder', 'shutdown')
    app._streamer = rec('streamer')
    app._auto_vj = rec('AutoVJController', 'shutdown')
    app._grand_finale = rec('GrandFinaleController', 'shutdown')
    app._subsystems = {'sub1': rec('sub1 subsystem', 'shutdown'), 'sub2': rec('sub2 subsystem', 'shutdown')}
    app._claimed_window_handlers = {}
    app._hotkeys = object()
    app._control_room = object()
    app._keystroke_logger = rec('keystroke logger', 'close')
    app._log_deleted_effects_summary = fn('deleted-effects summary')
    app._audio_manager = rec('audio manager', 'stop')
    app._audio_host = rec('audio process', 'close')
    app._midi_manager = rec('MIDI manager', 'stop')
    app._video_deck_layer = rec('video deck layer')
    app._persist_webcam_runtime_state = fn('webcam state')
    app._webcam_system = rec('webcam system')
    for attr in ('_candy_frame', '_postfx_controller', '_color_grade', '_beat_flash', '_video_postfx'):
        setattr(app, attr, rec(f'GL {attr}'))
    for attr in ('_current_effect', '_next_effect', '_overlays'):
        setattr(app, attr, rec(f'GL {attr}'))
    for attr in ('_invert_vao', '_invert_vbo', '_invert_prog', '_present_vao', '_present_vbo',
                 '_present_prog', '_burst_vao', '_burst_vbo', '_burst_prog'):
        setattr(app, attr, rec(f'GL {attr}', 'release'))
    app._release_readback_pbos = fn('readback buffers')
    app._runtime_state = SimpleNamespace(save=fn('runtime state save'))
    app._gl_context = object()
    app._window = object()
    return app, log


@pytest.fixture(autouse=True)
def _fake_sdl(monkeypatch):
    calls: list[str] = []
    boom: set[str] = set()

    def sdl(name: str):
        def _f(*_a, **_k):
            calls.append(name)
            if name in boom:
                raise _Boom(name)
        return _f
    monkeypatch.setattr(app_mod, 'sdl2', SimpleNamespace(
        SDL_GL_DeleteContext=sdl('GL context'), SDL_DestroyWindow=sdl('window'), SDL_Quit=sdl('SDL')))
    return calls, boom


def _expected_steps() -> list[str]:
    app, log = _build(set())
    app._shutdown_runtime()
    return list(log)


def test_a_clean_run_executes_every_step_in_order(_fake_sdl) -> None:
    steps = _expected_steps()
    assert steps[0] == 'profile autosave'
    assert 'runtime state save' in steps and steps.index('runtime state save') > steps.index('GL _burst_prog')
    assert len(steps) == len(set(steps)) > 30


def test_every_step_in_turn_can_fail_without_skipping_the_rest(_fake_sdl) -> None:
    calls, boom_sdl = _fake_sdl
    steps = _expected_steps()
    sdl_clean = list(calls)
    assert sdl_clean == ['GL context', 'window', 'SDL']
    failures = []
    for victim in steps + sdl_clean:
        calls.clear()
        boom_sdl.clear()
        boom: set[str] = {victim}
        if victim in sdl_clean:
            boom_sdl.add(victim)
            boom = set()
        app, log = _build(boom)
        app._shutdown_runtime()                      # must not raise
        if victim in steps:
            missing = [s for s in steps if s not in log]
            if missing:
                failures.append((victim, missing))
        sdl_missing = [s for s in sdl_clean if s not in calls]
        if sdl_missing:
            failures.append((victim, sdl_missing))
    assert not failures, failures


def test_a_failing_step_is_logged_with_its_name(_fake_sdl, caplog) -> None:
    import logging
    app, _ = _build({'audio manager'})
    with caplog.at_level(logging.WARNING, logger='unicornviz.app'):
        app._shutdown_runtime()
    assert any('Shutdown step audio manager failed' in r.getMessage() for r in caplog.records)


def test_the_runtime_state_save_and_sdl_run_even_when_everything_else_fails(_fake_sdl) -> None:
    calls, _ = _fake_sdl
    steps = _expected_steps()
    calls.clear()
    keep = {'runtime state save'}
    app, log = _build({s for s in steps if s not in keep})
    app._shutdown_runtime()
    assert 'runtime state save' in log
    assert calls == ['GL context', 'window', 'SDL']


def test_references_are_released_even_when_destroy_fails(_fake_sdl) -> None:
    app, _ = _build({'streamer', 'webcam system', 'GL _candy_frame'})
    app._shutdown_runtime()
    assert app._streamer is None and app._webcam_system is None and app._candy_frame is None
    assert app._gl_context is None and app._window is None


def test_a_second_call_is_a_no_op(_fake_sdl) -> None:
    app, log = _build(set())
    app._shutdown_runtime()
    n = len(log)
    app._shutdown_runtime()
    assert len(log) == n
