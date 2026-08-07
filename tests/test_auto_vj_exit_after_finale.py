"""Regression tests for _maybe_exit_after_finale() (2026-08-07).

Closes the loop for unattended headless runs (see
docs/planning/headless-auto-exit-plan-2026-08-07.md): once the timed grand
finale (_check_timed_finale()) has fired and the sequence it triggered has
actually finished (VjApi.grand_finale_active goes True then False), the
controller requests App exit (force=True) so training_daemon.py's automatic
packaging -- which just waits for the process to exit -- can run unattended.
Gated by auto_exit_after_finale (default off) and only ever armed by the
*timed* trigger, never a manual one.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_SPEC = importlib.util.spec_from_file_location('test_auto_vj_exit_after_finale_module', _AUTO_VJ_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
AutoVJController = _MOD.AutoVJController


class _FakeVjApi:
    def __init__(self, *, grand_finale_active: bool = False) -> None:
        self.grand_finale_active = grand_finale_active
        self.request_exit_calls: list[bool] = []

    def request_exit(self, *, force: bool = False) -> bool:
        self.request_exit_calls.append(force)
        return True


class _FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def monotonic(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _controller(*, auto_exit: bool = True, timed_finale_fired: bool = True,
                grand_finale_active: bool = False, monkeypatch=None,
                clock: _FakeClock | None = None,
                **overrides) -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._auto_exit_after_finale = auto_exit
    inst._timed_finale_fired = timed_finale_fired
    inst._exit_after_finale_seen_active = False
    inst._exit_after_finale_done = False
    inst._exit_after_finale_deadline_t = 0.0
    inst._app = SimpleNamespace(vj_api=_FakeVjApi(grand_finale_active=grand_finale_active))
    for k, v in overrides.items():
        setattr(inst, k, v)
    if clock is not None:
        assert monkeypatch is not None, 'pass the monkeypatch fixture when using a fake clock'
        monkeypatch.setattr(_MOD.time, 'monotonic', clock.monotonic)
    return inst


def test_noop_when_auto_exit_disabled() -> None:
    inst = _controller(auto_exit=False, grand_finale_active=False)
    inst._maybe_exit_after_finale()
    inst._app.vj_api.grand_finale_active = True
    inst._maybe_exit_after_finale()
    inst._app.vj_api.grand_finale_active = False
    inst._maybe_exit_after_finale()

    assert inst._app.vj_api.request_exit_calls == []


def test_noop_when_timed_finale_never_fired() -> None:
    """A manual (hotkey-triggered) finale must never cause an exit."""
    inst = _controller(timed_finale_fired=False, grand_finale_active=True)
    inst._maybe_exit_after_finale()
    inst._app.vj_api.grand_finale_active = False
    inst._maybe_exit_after_finale()

    assert inst._app.vj_api.request_exit_calls == []


def test_exits_after_finale_becomes_active_then_inactive() -> None:
    inst = _controller(grand_finale_active=True)
    inst._maybe_exit_after_finale()
    assert inst._exit_after_finale_seen_active is True
    assert inst._app.vj_api.request_exit_calls == []

    inst._app.vj_api.grand_finale_active = False
    inst._maybe_exit_after_finale()

    assert inst._app.vj_api.request_exit_calls == [True]
    assert inst._exit_after_finale_done is True


def test_does_not_exit_while_finale_still_active() -> None:
    inst = _controller(grand_finale_active=True)
    for _ in range(5):
        inst._maybe_exit_after_finale()

    assert inst._app.vj_api.request_exit_calls == []


def test_exits_only_once() -> None:
    inst = _controller(grand_finale_active=True)
    inst._maybe_exit_after_finale()
    inst._app.vj_api.grand_finale_active = False
    inst._maybe_exit_after_finale()
    inst._maybe_exit_after_finale()
    inst._maybe_exit_after_finale()

    assert inst._app.vj_api.request_exit_calls == [True]


def test_grace_period_exits_when_finale_never_becomes_active(monkeypatch) -> None:
    """grand-finale-01 missing/trigger failed: must not hang forever."""
    clock = _FakeClock()
    inst = _controller(grand_finale_active=False, clock=clock, monkeypatch=monkeypatch)

    inst._maybe_exit_after_finale()  # arms the grace deadline
    assert inst._app.vj_api.request_exit_calls == []

    clock.advance(_MOD.AutoVJController._EXIT_AFTER_FINALE_GRACE_S - 1.0)
    inst._maybe_exit_after_finale()
    assert inst._app.vj_api.request_exit_calls == []  # not yet

    clock.advance(2.0)
    inst._maybe_exit_after_finale()
    assert inst._app.vj_api.request_exit_calls == [True]


def test_becoming_active_before_grace_expires_cancels_the_grace_exit(monkeypatch) -> None:
    clock = _FakeClock()
    inst = _controller(grand_finale_active=False, clock=clock, monkeypatch=monkeypatch)
    inst._maybe_exit_after_finale()  # arms the grace deadline

    clock.advance(5.0)
    inst._app.vj_api.grand_finale_active = True
    inst._maybe_exit_after_finale()
    assert inst._exit_after_finale_seen_active is True
    assert inst._exit_after_finale_deadline_t == 0.0

    clock.advance(_MOD.AutoVJController._EXIT_AFTER_FINALE_GRACE_S + 10.0)
    inst._maybe_exit_after_finale()  # still active -- no grace exit
    assert inst._app.vj_api.request_exit_calls == []

    inst._app.vj_api.grand_finale_active = False
    inst._maybe_exit_after_finale()
    assert inst._app.vj_api.request_exit_calls == [True]
