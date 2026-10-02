"""Wave 4 crash isolation, P1-4 (audit 2026-09-30): no drop-in call can take
down the main loop.

Config-editor keys, MIDI dispatch, render-phase drop-in calls, the transition
completion's ``destroy()`` and first-effect construction were unguarded inside
``run()``: any exception propagated out and ``__main__``'s ``finally`` shut the
app down.  They now contain the failure; per-frame calls are also switched off
after 30 consecutive failures.
"""
from __future__ import annotations

import inspect
import logging
import re
from types import SimpleNamespace

import pytest

import unicornviz.app as app_mod
from unicornviz.app import App
from unicornviz.fault_guard import CallGuard, FailureThrottle
from unicornviz.hotkeys import HotkeyHandler


# ---------------------------------------------------------------- fault_guard

def test_throttle_logs_once_then_every_interval_with_a_count() -> None:
    t = FailureThrottle(30.0)
    assert t.should_log('k', now=0.0) == (True, 0)
    assert [t.should_log('k', now=n)[0] for n in range(1, 29)] == [False] * 28
    assert t.should_log('k', now=31.0) == (True, 28)
    assert t.should_log('other', now=31.5) == (True, 0)         # distinct errors are separate


def test_throttle_stays_bounded() -> None:
    t = FailureThrottle(30.0)
    for i in range(1000):
        t.should_log(f'k{i}', now=0.0)
    assert len(t._seen) <= 256


def test_guard_contains_logs_and_returns_the_default(caplog) -> None:
    g = CallGuard(logging.getLogger('t'), max_consecutive=5)
    with caplog.at_level(logging.WARNING, logger='t'):
        assert g.call('x', lambda: 1 / 0, default='d') == 'd'
    assert g.failures == 1 and any('x failed' in r.getMessage() for r in caplog.records)
    assert g.call('ok', lambda a, b=2: a + b, 1, b=4) == 5


def test_guard_disables_a_call_site_after_n_consecutive_failures(caplog) -> None:
    g = CallGuard(logging.getLogger('t'), max_consecutive=3)
    calls = []

    def bad():
        calls.append(1)
        raise RuntimeError('boom')

    with caplog.at_level(logging.WARNING, logger='t'):
        for _ in range(10):
            g.call('site', bad)
    assert len(calls) == 3 and g.disabled('site')                # not called any more
    assert sum('disabled for the rest of this session' in r.getMessage() for r in caplog.records) == 1
    assert len([r for r in caplog.records if 'site failed' in r.getMessage() and r.levelno == logging.WARNING]) == 1   # throttled
    g.reset('site')
    assert not g.disabled('site')


def test_a_success_resets_the_streak() -> None:
    g = CallGuard(logging.getLogger('t'), max_consecutive=3)
    state = {'n': 0}

    def flaky():
        state['n'] += 1
        if state['n'] % 3:
            raise RuntimeError('x')

    for _ in range(30):
        g.call('flaky', flaky)
    assert not g.disabled('flaky')                                # never 3 in a row


# ---------------------------------------------------------------------- MIDI

class _Ev:
    def __init__(self, number: int) -> None:
        self.type, self.number = 'note_on', number


def _handler() -> HotkeyHandler:
    return HotkeyHandler(SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), SimpleNamespace())


def test_a_raising_midi_action_does_not_end_the_batch(caplog) -> None:
    h = _handler()
    seen = []

    def dispatch(ev):
        seen.append(ev.number)
        if ev.number == 2:
            raise RuntimeError('bad action')

    h._dispatch_midi_event = dispatch
    h._pending_midi_events.extend(_Ev(n) for n in (1, 2, 3, 4))
    with caplog.at_level(logging.WARNING, logger='unicornviz.hotkeys'):
        h.process_pending_midi()                                  # must not raise
    assert seen == [1, 2, 3, 4]                                   # the rest of the batch ran
    assert any('bad action' in r.getMessage() for r in caplog.records)


def test_a_midi_failure_storm_logs_once(caplog) -> None:
    h = _handler()
    h._dispatch_midi_event = lambda ev: (_ for _ in ()).throw(RuntimeError('same'))
    with caplog.at_level(logging.WARNING, logger='unicornviz.hotkeys'):
        for _ in range(50):
            h._pending_midi_events.append(_Ev(7))
            h.process_pending_midi()
    assert len([r for r in caplog.records if 'same' in r.getMessage()]) == 1


# ------------------------------------------------------------- config editor

def _editor_app(spec, tab='Visuals'):
    app = App.__new__(App)
    app._overlays = SimpleNamespace(
        config_editor_param_index=lambda: 0, config_editor_tab_name=tab,
        activate_config_editor_row=lambda: True,
        take_config_editor_value_request=lambda: (0, 1.0))
    app._config_editor_settings_specs = lambda _tab: [spec]
    app._profile_touched = lambda: None
    return app


def _spec(setter, kind='slider'):
    return {'key': 'k', 'name': 'n', 'kind': kind, 'value': 0.5, 'min': 0.0, 'max': 1.0, 'set': setter}


def _boom(_v):
    raise RuntimeError('drop-in setter exploded')


@pytest.mark.parametrize('kind', ['slider', 'toggle', 'choice'])
def test_keyboard_adjust_survives_a_raising_setter(kind, caplog) -> None:
    app = _editor_app(_spec(_boom, kind))
    with caplog.at_level(logging.WARNING, logger='unicornviz.app'):
        app._config_editor_adjust(1.0)                            # must not raise
        app._config_editor_adjust(-1.0)
    assert any('drop-in setter exploded' in r.getMessage() for r in caplog.records)


def test_enter_and_text_commit_survive_a_raising_setter() -> None:
    app = _editor_app(_spec(_boom, 'toggle'))
    app._config_editor_activate()
    app._config_editor_set_value(0, 1.0)
    app = _editor_app(dict(_spec(_boom), kind='text'))
    app._config_editor_set_text(0, 'x')


def test_a_row_with_a_bad_value_is_skipped_not_fatal(caplog) -> None:
    class Ctrl:
        CONFIG_EDITOR_CATEGORY = 'Visuals'

        def config_editor_settings(self):
            return [{'name': 'bad', 'kind': 'slider', 'value': None},      # float(None) raised
                    {'name': 'good', 'kind': 'slider', 'value': 0.5}]

        def set_config_setting(self, name, value):
            return None

    app = App.__new__(App)
    app._config_editor_contributors = lambda: [('c', Ctrl())]
    app._remember_runtime = lambda *a, **k: None
    with caplog.at_level(logging.WARNING, logger='unicornviz.app'):
        specs = app._config_editor_dropin_specs('Visuals')
    assert [s['name'] for s in specs] == ['good']


# ------------------------------------------------------ render-phase drop-ins

_RENDER_ATTRS = ('_video_deck_layer.update', '_webcam_system.render', '_dancing_unicorn.update',
                 '_dancing_unicorn.render', '_rainbow_nova.update', '_rainbow_nova.render',
                 '_grand_finale.render_overlay', '_candy_frame.update', '_candy_frame.render',
                 'render_celebration_overlay', '_streamer.write_frame')


def test_run_makes_no_bare_render_phase_dropin_calls() -> None:
    """Regression scan: in run()/_render() these calls only appear inside the
    guarded ``_frame_*`` methods or through the call guard."""
    src = inspect.getsource(App.run)
    offenders = [a for a in _RENDER_ATTRS if re.search(r'self\.' + re.escape(a) + r'\(', src)
                 and 'guard' not in src.split(a)[0][-200:]]
    assert not offenders, offenders
    assert not re.search(r'^\s+self\._current_effect\.destroy\(\)', inspect.getsource(App._render), re.M)
    assert 'self._instantiate(_first_cls)' not in src


class _Failing:
    def __getattr__(self, name):
        def fail(*_a, **_k):
            raise RuntimeError(f'{name} exploded')
        return fail


def test_each_frame_step_is_contained_and_disabled_after_30_failures() -> None:
    app = App.__new__(App)
    app._webcam_system = _Failing()
    app._audio = None
    calls = {'n': 0}

    class W:
        def render(self, *a):
            calls['n'] += 1
            raise RuntimeError('webcam render failed')
    app._webcam_system = W()
    for _ in range(100):
        app._call_guard.call('webcam render', app._frame_webcam, 0.016)
    assert calls['n'] == 30 and app._call_guard.disabled('webcam render')


# --------------------------------------------------------------- first effect

class _Cls:
    def __init__(self, name: str) -> None:
        self.__name__ = self.NAME = name


class _Playlist:
    def __init__(self, classes) -> None:
        self._it = iter(classes)

    def advance(self):
        return next(self._it, None)


def _first_app(failing: set[str]):
    app = App.__new__(App)
    app._effect_blocklist = set()

    def inst(cls):
        if cls.__name__ in failing:
            raise RuntimeError(f'{cls.__name__} shader failed to compile')
        return f'effect:{cls.__name__}'

    app._instantiate = inst
    return app


def test_a_first_effect_that_fails_to_build_falls_back_to_the_next() -> None:
    bad, good = _Cls('Bad'), _Cls('Good')
    app = _first_app({'Bad'})
    assert app._instantiate_first_effect(_Playlist([good]), bad) == 'effect:Good'
    assert 'Bad' in app._effect_blocklist


def test_a_failing_first_effect_skips_blocklisted_candidates() -> None:
    a, b, c = _Cls('A'), _Cls('B'), _Cls('C')
    app = _first_app({'A', 'B'})
    assert app._instantiate_first_effect(_Playlist([b, c]), a) == 'effect:C'


def test_when_no_effect_builds_the_app_still_starts(caplog) -> None:
    a, b = _Cls('A'), _Cls('B')
    app = _first_app({'A', 'B'})
    with caplog.at_level(logging.ERROR, logger='unicornviz.app'):
        assert app._instantiate_first_effect(_Playlist([b]), a) is None
    assert any('No effect could be started' in r.getMessage() for r in caplog.records)


def test_no_playlist_effect_is_not_an_error() -> None:
    assert _first_app(set())._instantiate_first_effect(_Playlist([]), None) is None
