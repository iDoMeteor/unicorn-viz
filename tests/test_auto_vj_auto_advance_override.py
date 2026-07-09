from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_AUTO_VJ_SPEC = importlib.util.spec_from_file_location('test_auto_vj_auto_advance_override_module', _AUTO_VJ_PATH)
assert _AUTO_VJ_SPEC is not None and _AUTO_VJ_SPEC.loader is not None
_AUTO_VJ_MODULE = importlib.util.module_from_spec(_AUTO_VJ_SPEC)
_AUTO_VJ_SPEC.loader.exec_module(_AUTO_VJ_MODULE)
AutoVJController = _AUTO_VJ_MODULE.AutoVJController


class _FakeVJApi:
    """Stub whose state()/set_auto_advance() mirror the real VJApi surface."""

    def __init__(self, *, auto_advance: bool) -> None:
        self._auto_advance = auto_advance
        self.set_auto_advance_calls: list[bool] = []

    def state(self) -> SimpleNamespace:
        return SimpleNamespace(auto_advance=self._auto_advance)

    def set_auto_advance(self, enabled: bool) -> None:
        self.set_auto_advance_calls.append(bool(enabled))
        self._auto_advance = bool(enabled)


def _controller(*, enabled: bool, saved: bool | None, vj_api: _FakeVJApi) -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._enabled = enabled
    inst._saved_auto_advance = saved
    inst._app = SimpleNamespace(vj_api=vj_api)
    return inst


def test_enabling_captures_and_disables_auto_advance() -> None:
    vj_api = _FakeVJApi(auto_advance=True)
    controller = _controller(enabled=True, saved=None, vj_api=vj_api)

    controller._sync_auto_advance_override()

    assert controller._saved_auto_advance is True
    assert vj_api.set_auto_advance_calls == [False]


def test_enabling_preserves_already_off_value_for_later_restore() -> None:
    """If the user had auto-advance off before enabling Auto VJ, disabling
    Auto VJ later must restore it to off, not flip it on."""
    vj_api = _FakeVJApi(auto_advance=False)
    controller = _controller(enabled=True, saved=None, vj_api=vj_api)

    controller._sync_auto_advance_override()

    assert controller._saved_auto_advance is False


def test_capture_only_happens_once_per_enable_cycle() -> None:
    """Repeated per-frame calls while still enabled must not re-trigger the
    capture/suppress (that would clobber the saved value with False, i.e.
    whatever set_auto_advance(False) forced it to)."""
    vj_api = _FakeVJApi(auto_advance=True)
    controller = _controller(enabled=True, saved=None, vj_api=vj_api)

    controller._sync_auto_advance_override()
    controller._sync_auto_advance_override()
    controller._sync_auto_advance_override()

    assert controller._saved_auto_advance is True
    assert vj_api.set_auto_advance_calls == [False]


def test_disabling_restores_saved_value() -> None:
    vj_api = _FakeVJApi(auto_advance=False)  # currently suppressed
    controller = _controller(enabled=False, saved=True, vj_api=vj_api)

    controller._sync_auto_advance_override()

    assert vj_api.set_auto_advance_calls == [True]
    assert controller._saved_auto_advance is None


def test_disabling_restores_saved_off_value() -> None:
    vj_api = _FakeVJApi(auto_advance=False)
    controller = _controller(enabled=False, saved=False, vj_api=vj_api)

    controller._sync_auto_advance_override()

    assert vj_api.set_auto_advance_calls == [False]
    assert controller._saved_auto_advance is None


def test_disabling_with_nothing_saved_is_a_noop() -> None:
    """Disabled with no active override (e.g. Auto VJ never ran this
    session) must not touch auto-advance at all."""
    vj_api = _FakeVJApi(auto_advance=True)
    controller = _controller(enabled=False, saved=None, vj_api=vj_api)

    controller._sync_auto_advance_override()

    assert vj_api.set_auto_advance_calls == []
    assert controller._saved_auto_advance is None


def test_full_enable_disable_cycle_round_trips() -> None:
    vj_api = _FakeVJApi(auto_advance=True)
    controller = _controller(enabled=True, saved=None, vj_api=vj_api)

    controller._sync_auto_advance_override()  # enable: capture True, force False
    controller._enabled = False
    controller._sync_auto_advance_override()  # disable: restore True

    assert vj_api.set_auto_advance_calls == [False, True]
    assert controller._saved_auto_advance is None


def test_state_exception_falls_back_to_true_without_raising() -> None:
    class _BrokenVJApi:
        def state(self):
            raise RuntimeError('boom')

        def set_auto_advance(self, enabled: bool) -> None:
            pass

    controller = _controller(enabled=True, saved=None, vj_api=_BrokenVJApi())

    controller._sync_auto_advance_override()

    assert controller._saved_auto_advance is True
