"""Phase B clock-seam regression tests (v3 plan Part 2, 2026-08-17).

The AutoVJController's 37 ``time.monotonic()`` decision sites were swept
behind ``self._now()`` so a headless replay driver can run the whole
director at audio time via ``set_clock()``. These tests pin three
things:

1. **The sweep is complete at the source level** — ``auto_vj.py``
   contains no direct ``time.monotonic()`` calls outside the two
   ``_now()`` fallback definitions.
2. **The seam works** — ``_ActionEngine`` and the controller honor an
   injected clock, and default to live ``time.monotonic`` (looked up on
   the module at call time, so existing monkeypatch-based tests keep
   working).
3. **Decisions depend only on the injected clock** — two identical
   scripted headless sessions, run with the module's ``time.monotonic``
   patched to two wildly different constants (0.0 vs 1e9), produce
   identical decision sequences. Any missed decision site that mixes
   wall clock with seam-clock timestamps would diverge between the two
   runs (elapsed = huge-vs-negative), so this is the
   wall-clock-vs-t-driven equivalence check the plan asked for.
"""
from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
_AUTO_VJ_PATH = _REPO / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_STUB_PATH = _REPO / 'drop-ins' / 'auto-vj-01' / 'tools' / 'headless_stub.py'


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_STUB = _load('test_clock_seam_stub', _STUB_PATH)
_MOD = _STUB.load_auto_vj_module()


# ---------------------------------------------------------------------------
# 1. Source-level sweep completeness
# ---------------------------------------------------------------------------

def test_no_direct_monotonic_calls_outside_the_seam() -> None:
    source = _AUTO_VJ_PATH.read_text(encoding='utf-8')
    # Exactly two allowed call sites: the _ActionEngine._now() fallback
    # and the AutoVJController._now() fallback. Comment lines don't count.
    code_hits = [
        line for line in source.splitlines()
        if 'time.monotonic()' in line and not line.lstrip().startswith('#')
    ]
    assert len(code_hits) == 2, (
        'a new time.monotonic() call site crept into auto_vj.py — route it '
        f'through self._now() so headless replay stays correct: {code_hits}')
    assert "__import__('time')" not in source


# ---------------------------------------------------------------------------
# 2. The seam itself
# ---------------------------------------------------------------------------

def test_action_engine_honors_injected_clock() -> None:
    t = [1000.0]
    engine = _MOD._ActionEngine({}, None, clock=lambda: t[0])
    engine._cooldowns['effect_swap'] = 10.0

    assert engine.ready('effect_swap')
    engine.mark('effect_swap')
    assert not engine.ready('effect_swap')
    t[0] += 9.0
    assert not engine.ready('effect_swap')
    t[0] += 1.5
    assert engine.ready('effect_swap')


def test_action_engine_defaults_to_live_monotonic(monkeypatch) -> None:
    engine = _MOD._ActionEngine({}, None)
    monkeypatch.setattr(_MOD.time, 'monotonic', lambda: 555.0)
    assert engine._now() == 555.0


def test_controller_now_defaults_and_injects(monkeypatch) -> None:
    inst = object.__new__(_MOD.AutoVJController)  # no __init__, like peers
    monkeypatch.setattr(_MOD.time, 'monotonic', lambda: 777.0)
    assert inst._now() == 777.0  # getattr-defensive fallback

    inst.set_clock(lambda: 42.0)
    assert inst._now() == 42.0
    inst.set_clock(None)
    assert inst._now() == 777.0


# ---------------------------------------------------------------------------
# 3. Wall-clock independence of a full headless session
# ---------------------------------------------------------------------------

def _scripted_audio(step: int) -> SimpleNamespace:
    """Deterministic synthetic audio: 128 BPM pulse train at 60 fps."""
    beat_period_ticks = 60.0 * 60.0 / 128.0 / 60.0  # ticks per beat at 60fps
    phase = (step / (3600.0 / 128.0)) % 1.0
    beat = 1.0 if phase < 0.1 else 0.0
    bass = 0.4 + 0.5 * beat
    _ = beat_period_ticks
    return SimpleNamespace(
        bass=bass, mid=0.3, treble=0.2, beat=beat, rms=0.3,
        bass_det=bass, mid_det=0.3, treble_det=0.2,
        spectral_flux=0.2 + 0.6 * beat, bass_flux=0.15 + 0.5 * beat,
        bands=np.full(512, 0.1, dtype=np.float32),
        fft=np.zeros(512, dtype=np.float32),
        waveform=np.zeros(1024, dtype=np.float32),
    )


def _run_session(wall_constant: float, duration_s: float = 90.0) -> list:
    """One scripted headless session; returns its decision sequence."""
    random.seed(20260817)
    np.random.seed(20260817)

    controller, app = _STUB.make_headless_controller(
        {'enabled': True, 'log_decisions': False,
         'live_training_enabled': False})
    replay_t = [5000.0]
    controller.set_clock(lambda: replay_t[0])

    real_monotonic = _MOD.time.monotonic
    _MOD.time.monotonic = lambda: wall_constant
    try:
        dt = 1.0 / 60.0
        steps = int(duration_s / dt)
        for step in range(steps):
            replay_t[0] += dt
            controller.update(dt, _scripted_audio(step))
    finally:
        _MOD.time.monotonic = real_monotonic

    # The observable decision stream: every vj_api call the director made
    # during the session (minus constructor-time registrations), plus the
    # status pill trajectory.
    decisions = [
        (name, repr(args))
        for name, args, _ in app.vj_api.calls
        if not name.startswith('register_')
    ]
    decisions.append(('final_status', controller.status_text))
    return decisions


def test_decision_sequence_is_wall_clock_independent() -> None:
    run_a = _run_session(wall_constant=0.0)
    run_b = _run_session(wall_constant=1.0e9)

    assert run_a, 'scripted session produced no observable decisions'
    assert run_a == run_b, (
        'director decisions diverged between two runs that differ ONLY in '
        'the wall clock — a decision site is still reading time.monotonic() '
        'instead of self._now()')
