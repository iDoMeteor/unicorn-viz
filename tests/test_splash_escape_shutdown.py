"""P2-5 (audit 2026-09-30): Esc during the splash tore SDL/GL down twice.

The Esc branch stopped audio, deleted the GL context, destroyed the window and
called SDL_Quit by hand, then returned with ``_gl_context``/``_window`` still
set and ``_shutdown_complete`` false.  ``__main__``'s ``finally`` then ran
``ensure_shutdown()``, which released GL objects on the deleted context, deleted
the context and destroyed the window again through freed handles, stopped audio
a second time (``sd._terminate()`` twice) and saved state.  The splash exit now
goes through ``_shutdown_runtime`` exactly once.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import unicornviz.app as app_mod
from test_shutdown_every_step_isolated import _build  # noqa: E402  (tests dir is on sys.path)


@pytest.fixture
def sdl(monkeypatch):
    calls: list[str] = []

    def f(name):
        return lambda *_a, **_k: calls.append(name)
    monkeypatch.setattr(app_mod, 'sdl2', SimpleNamespace(
        SDL_GL_DeleteContext=f('GL context'), SDL_DestroyWindow=f('window'), SDL_Quit=f('SDL')))
    return calls


class _Splash:
    def __init__(self, log, boom=False):
        self.log, self.boom = log, boom

    def destroy(self):
        self.log.append('splash')
        if self.boom:
            raise RuntimeError('splash destroy failed')


def test_escape_during_the_splash_tears_down_exactly_once(sdl) -> None:
    app, log = _build(set())
    app._quit_during_startup(_Splash(log))
    app.ensure_shutdown()                       # __main__'s finally
    assert sdl == ['GL context', 'window', 'SDL']                  # not twice
    assert log.count('audio manager') == 1 and log.count('runtime state save') == 1
    assert log[0] == 'splash'                   # the splash goes first, before its GL context
    assert app._gl_context is None and app._window is None


def test_a_failing_splash_destroy_does_not_stop_the_teardown(sdl) -> None:
    app, log = _build(set())
    app._quit_during_startup(_Splash(log, boom=True))
    assert sdl == ['GL context', 'window', 'SDL'] and 'runtime state save' in log


def test_quitting_before_the_splash_exists_works(sdl) -> None:
    app, log = _build(set())
    app._quit_during_startup(None)
    assert sdl == ['GL context', 'window', 'SDL']
