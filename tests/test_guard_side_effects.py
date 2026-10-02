"""Side effects of the wave-4 call guards (review of beta.193 by UV Threads).

(a) A presenting overlay (Candy Frame, Rainbow Nova, Grand Finale) that the
    guard has switched off must stop influencing how the scene is routed:
    ``_render`` routes the scene into ``_fbo_a`` while one is "active", and
    Candy Frame shrinks the effect's viewport into its frame.  A disabled step
    is treated as inactive so the scene is drawn plainly and full-screen
    instead of going small or missing while the app looks healthy.
(b) A step that raises after changing GL state (blend, depth, scissor, the
    bound framebuffer) must not leak that state into the next step, so GL
    state is normalized after any contained failure.
(c) The candy-mode getter failing is logged through the guard, not silently
    read as False.
"""
from __future__ import annotations

import inspect
import logging
from types import SimpleNamespace

import pytest

import unicornviz.app as app_mod
from unicornviz.app import App
from unicornviz.fault_guard import CallGuard


class _Overlay:
    def __init__(self, active=True, fail_on=(), log=None, name='x') -> None:
        self.active = self.is_active = self.overlay_active = active
        self.fail_on, self.log, self.name = set(fail_on), log, name

    def _call(self, what):
        if self.log is not None:
            self.log.append(f'{self.name}.{what}')
        if what in self.fail_on:
            raise RuntimeError(f'{self.name}.{what} exploded')

    def update(self, *a, **k):
        self._call('update')

    def render(self, *a, **k):
        self._call('render')

    def render_overlay(self, *a, **k):
        self._call('render_overlay')

    def set_outer_fill_needed(self, *_a):
        pass


def _app(**parts):
    app = App.__new__(App)
    app._projectm_manager_modal_active = False
    app._candy_frame = parts.get('candy')
    app._rainbow_nova = parts.get('nova')
    app._grand_finale = parts.get('finale')
    app._dancing_unicorn = parts.get('unicorn')
    app._webcam_system = parts.get('webcam')
    app._video_deck_layer = None
    app._auto_vj = None
    app._audio = None
    app._display_mode = 'single'
    app._mirror_rects = []
    app._is_mirror_mode = lambda _m: False
    app._current_effect = app._next_effect = None
    app._width, app._height = 64, 48
    app._render_width, app._render_height = 64, 48
    app._ctx = SimpleNamespace(screen=SimpleNamespace(use=lambda: None), viewport=None)
    app._fbo_a = SimpleNamespace(use=lambda: None, color_attachments=[object()])
    app._fbo_b = SimpleNamespace(use=lambda: None)
    app._blit_fbo_b_to_fbo_a = lambda *a, **k: None
    app._effect_requests_frame_scaling = lambda _e: False
    normalized: list[int] = []
    app._normalize_gl_render_state = lambda: normalized.append(1)
    app._normalized = normalized
    return app


# ------------------------------------------------------------------------ (a)

@pytest.mark.parametrize(('attr', 'guard_name', 'helper'), [
    ('candy', 'candy frame', '_candy_active'),
    ('nova', 'rainbow nova', '_nova_active'),
    ('finale', 'grand finale overlay', '_finale_overlay_active'),
])
def test_a_guard_disabled_overlay_is_treated_as_inactive(attr, guard_name, helper) -> None:
    app = _app(**{attr: _Overlay(active=True)})
    assert getattr(app, helper)() is True
    for _ in range(30):                             # the guard disables it after 30 failures
        app._call_guard.record_failure(guard_name, RuntimeError('x'))
    assert app._call_guard.disabled(guard_name)
    assert getattr(app, helper)() is False


def test_a_modal_or_missing_overlay_is_inactive_too() -> None:
    app = _app(candy=_Overlay(active=True))
    app._projectm_manager_modal_active = True
    assert app._candy_active() is False
    assert _app()._candy_active() is False and _app()._nova_active() is False


def test_candy_frame_stops_shrinking_the_effect_when_it_is_disabled() -> None:
    class _Candy(_Overlay):
        def content_viewport(self, w, h):
            return (4, 4, w - 8, h - 8)

    candy = _Candy(active=True)
    app = _app(candy=candy)
    app._effect_requests_frame_scaling = lambda _e: True
    assert app._effect_viewport_for_target(64, 48, object()) == (4, 4, 56, 40)
    for _ in range(30):
        app._call_guard.record_failure('candy frame', RuntimeError('x'))
    assert app._effect_viewport_for_target(64, 48, object()) == (0, 0, 64, 48)   # full screen again


def test_render_uses_the_effective_activity_not_the_raw_flags() -> None:
    src = inspect.getsource(App._render)
    assert 'self._candy_frame.active' not in src
    assert 'self._rainbow_nova.is_active' not in src
    assert 'self._grand_finale.overlay_active' not in src
    assert '_candy_active()' in src and '_nova_active()' in src and '_finale_overlay_active()' in src


# ------------------------------------------------------------------------ (b)

def test_gl_state_is_normalized_after_a_contained_failure() -> None:
    log: list[str] = []
    app = _app(candy=_Overlay(active=True, fail_on={'render'}, log=log, name='candy'),
               nova=_Overlay(active=False, log=log, name='nova'))
    app._frame_overlay_steps(0.016)                  # must not raise
    assert 'candy.render' in log
    assert app._normalized == [1]                    # state reset once, after the failing step


def test_gl_state_is_left_alone_when_nothing_failed() -> None:
    app = _app(candy=_Overlay(active=True, log=[], name='candy'))
    app._frame_overlay_steps(0.016)
    assert app._normalized == []


def test_a_failure_in_an_early_step_does_not_prevent_the_later_steps() -> None:
    log: list[str] = []
    app = _app(webcam=SimpleNamespace(render=lambda *a: (_ for _ in ()).throw(RuntimeError('cam'))),
               nova=_Overlay(active=True, log=log, name='nova'),
               candy=_Overlay(active=True, log=log, name='candy'))
    app._frame_overlay_steps(0.016)
    assert 'nova.update' in log and 'candy.update' in log and 'candy.render' in log
    assert app._normalized == [1]


# ------------------------------------------------------------------------ (c)

def test_a_failing_candy_getter_is_logged_through_the_guard(caplog) -> None:
    class _BadCandy:
        @property
        def active(self):
            raise RuntimeError('getter exploded')

    app = _app(candy=_BadCandy())
    with caplog.at_level(logging.WARNING, logger='unicornviz.app'):
        app._frame_overlay_steps(0.016)              # must not raise
    assert any('candy frame active failed' in r.getMessage() and 'getter exploded' in r.getMessage()
               for r in caplog.records)
