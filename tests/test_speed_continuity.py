"""E1 (audit 2026-09-30, effects): every speed change must keep shader phase
continuous.

34 effects compute ``t = iTime * (bias + scale * iSpeed)`` in the shader.
``vj_api.set_speed`` rescaled ``effect.time`` so that product does not jump;
the ``=`` / ``-`` / Ctrl+``=`` / Ctrl+``-`` hotkeys, random speed (F6, Alt+=,
re-armed on every scene change), the G reset, MIDI CC mapping and the config
editor wrote ``parameters['speed']`` directly, so ``effect.time`` (anywhere in
0-10000 s) times the new speed teleported the picture.  All of them now go
through ``unicornviz.effects.base.apply_speed``.
"""
from __future__ import annotations

import logging
import random
from types import SimpleNamespace

import pytest

import sdl2

from unicornviz.app import App
from unicornviz.effects.base import apply_speed
from unicornviz.hotkeys import HotkeyHandler
from unicornviz.vj_api import VJApi
from test_hotkeys_behavior import _App as _FakeApp  # noqa: E402  (tests dir is on sys.path)
from test_hotkeys_behavior import _Overlay  # noqa: E402


class _Fx:
    """An effect whose shader phase is time * (bias + scale * speed)."""

    NAME = 'fx'

    def __init__(self, speed=1.0, time=6000.0, bias=0.0, scale=1.0) -> None:
        self.parameters = {'speed': speed, 'zoom': 1.0}
        self._initial_parameters = {'speed': 1.0}
        self.time = time
        self.SPEED_TIME_BIAS, self.SPEED_TIME_SCALE = bias, scale

    @property
    def phase(self) -> float:
        return self.time * (self.SPEED_TIME_BIAS + self.SPEED_TIME_SCALE * self.parameters['speed'])


FLAVORS = [dict(), dict(bias=0.42, scale=0.70), dict(bias=0.35, scale=0.8)]


@pytest.mark.parametrize('flavor', FLAVORS)
def test_apply_speed_keeps_the_phase_continuous(flavor) -> None:
    fx = _Fx(speed=1.0, **flavor)
    before = fx.phase
    assert apply_speed(fx, 1.25) == 1.25
    assert fx.phase == pytest.approx(before, rel=1e-9)
    assert fx.parameters['speed'] == 1.25


def test_apply_speed_without_continuity_is_a_plain_write() -> None:
    fx = _Fx()
    apply_speed(fx, 2.0, continuous=False)
    assert fx.time == 6000.0 and fx.parameters['speed'] == 2.0


def test_apply_speed_never_fails_on_odd_effects() -> None:
    class Odd:
        parameters = {'speed': 1.0}
        SPEED_TIME_BIAS = 'x'           # unusable constant
    odd = Odd()
    apply_speed(odd, 2.0)               # no time attribute / bad constant: still sets the speed
    assert odd.parameters['speed'] == 2.0
    nospeed = SimpleNamespace(parameters={})
    assert apply_speed(nospeed, 3.0) is None


# ------------------------------------------------------------------ the hotkeys

class _SpeedApp(_FakeApp):
    """The hotkey tests' fake app, with the REAL speed methods of ``App`` bound
    to it, so the whole path (handler -> App method -> apply_speed) is exercised."""

    def __init__(self, fx) -> None:
        super().__init__()
        self.current_effect = self._current_effect = fx
        self._speed_randomized = False
        self._rng = random.Random(7)
        self._midi_manager = SimpleNamespace(cc_to_param=lambda n: 'speed' if n == 7 else 'zoom')
        self._reactivity_randomized = self._zoom_randomized = False
        self._effect_config_overrides = {}
        self._profile_touched = lambda: None
        for name in ('set_current_speed', 'apply_random_speed', '_apply_random_speed', '_reset_speed',
                     'reset_speed', 'set_effect_parameter', '_re_randomize_on_scene_change',
                     'set_speed_randomized', 'midi_param_for_cc'):
            setattr(self, name, getattr(App, name).__get__(self))
        self._random_range_for = lambda name, lo, hi: (lo, hi)
        self.random_range_for = self._random_range_for

    @property
    def speed_randomized(self) -> bool:
        return self._speed_randomized

    def _apply_random_reactivity(self) -> None:
        pass

    def _apply_random_zoom(self) -> None:
        pass


def _app_with(fx) -> _SpeedApp:
    return _SpeedApp(fx)


def _handler(app) -> HotkeyHandler:
    return HotkeyHandler(app, SimpleNamespace(), _Overlay(), SimpleNamespace())


@pytest.mark.parametrize('flavor', FLAVORS)
@pytest.mark.parametrize(('sym', 'mod'), [
    (sdl2.SDLK_EQUALS, 0), (sdl2.SDLK_PLUS, 0), (sdl2.SDLK_MINUS, 0),
    (sdl2.SDLK_EQUALS, sdl2.KMOD_CTRL), (sdl2.SDLK_MINUS, sdl2.KMOD_CTRL),
    (sdl2.SDLK_EQUALS, sdl2.KMOD_ALT),
])
def test_speed_hotkeys_do_not_jump_the_phase(flavor, sym, mod) -> None:
    fx = _Fx(**flavor)
    app = _app_with(fx)
    before = fx.phase
    _handler(app).handle(sym, mod)
    assert fx.parameters['speed'] != 1.0                    # it did change the speed
    assert fx.phase == pytest.approx(before, rel=1e-6)


def test_f6_random_speed_does_not_jump_the_phase() -> None:
    fx = _Fx(bias=0.35, scale=0.8)
    app = _app_with(fx)
    app.set_speed_randomized = lambda v: setattr(app, '_speed_randomized', v)
    before = fx.phase
    _handler(app).handle(sdl2.SDLK_F6, 0)
    assert app._speed_randomized and fx.parameters['speed'] != 1.0
    assert fx.phase == pytest.approx(before, rel=1e-6)


def test_g_reset_and_scene_change_rerandomize_keep_the_phase() -> None:
    fx = _Fx(speed=2.5, bias=0.42, scale=0.7)
    app = _app_with(fx)
    before = fx.phase
    assert app._reset_speed() == 1.0
    assert fx.phase == pytest.approx(before, rel=1e-6)
    before = fx.phase
    app._speed_randomized = True
    app._re_randomize_on_scene_change = App._re_randomize_on_scene_change.__get__(app)
    app._reactivity_randomized = app._zoom_randomized = False
    app._re_randomize_on_scene_change()
    assert fx.phase == pytest.approx(before, rel=1e-6)


def test_a_midi_cc_sweep_of_speed_does_not_scrub_the_picture() -> None:
    fx = _Fx(bias=0.35, scale=0.8)
    app = _app_with(fx)
    h = _handler(app)
    for value in (0.1, 0.9, 0.3, 0.7, 0.5):
        before = fx.phase
        h._dispatch_midi_event(SimpleNamespace(type='cc', number=7, value=value))
        assert fx.phase == pytest.approx(before, rel=1e-6)
    assert fx.parameters['speed'] != 1.0


def test_other_cc_parameters_are_still_plain_writes() -> None:
    fx = _Fx()
    app = _app_with(fx)
    _handler(app)._dispatch_midi_event(SimpleNamespace(type='cc', number=8, value=0.5))
    assert fx.time == 6000.0 and fx.parameters['zoom'] != 1.0


def test_the_config_editor_speed_row_keeps_the_phase() -> None:
    fx = _Fx(bias=0.35, scale=0.8)
    fx.__class__.__name__  # noqa: B018
    app = _app_with(fx)
    app._effect_config_overrides = {}
    app._profile_touched = lambda: None
    before = fx.phase
    app.set_effect_parameter(type(fx).__name__, 'speed', 2.0)
    assert fx.phase == pytest.approx(before, rel=1e-6)
    app.set_effect_parameter(type(fx).__name__, 'zoom', 2.0)       # others unchanged
    assert fx.parameters['zoom'] == 2.0


# ------------------------------------------------------------ vj_api unchanged

def _api(fx, auto_vj=None) -> VJApi:
    app = SimpleNamespace(_current_effect=fx, _auto_vj=auto_vj)
    return VJApi(app)


def test_vj_api_set_speed_is_still_continuous_and_clamped() -> None:
    fx = _Fx(bias=0.42, scale=0.7)
    before = fx.phase
    assert _api(fx).set_speed(2.0) == 2.0
    assert fx.phase == pytest.approx(before, rel=1e-6)
    assert _api(fx).set_speed(99.0) == 10.0 and _api(fx).set_speed(0.0) == 0.05


def test_the_raver_scramble_exception_still_cuts() -> None:
    auto_vj = SimpleNamespace(enabled=True, _profile='raver',
                              _grid=SimpleNamespace(bpm=150.0))
    fx = _Fx()
    before = fx.phase
    _api(fx, auto_vj).set_speed(2.0)
    assert fx.phase != pytest.approx(before)                        # intentional discontinuity
