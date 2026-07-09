from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_AUTO_VJ_SPEC = importlib.util.spec_from_file_location('test_auto_vj_downbeat_pulse_module', _AUTO_VJ_PATH)
assert _AUTO_VJ_SPEC is not None and _AUTO_VJ_SPEC.loader is not None
_AUTO_VJ_MODULE = importlib.util.module_from_spec(_AUTO_VJ_SPEC)
_AUTO_VJ_SPEC.loader.exec_module(_AUTO_VJ_MODULE)
AutoVJController = _AUTO_VJ_MODULE.AutoVJController
_HUD_DOWNBEAT_PULSE_DECAY = _AUTO_VJ_MODULE._HUD_DOWNBEAT_PULSE_DECAY
_HUD_BEAT_PULSE_DECAY = _AUTO_VJ_MODULE._HUD_BEAT_PULSE_DECAY


def _controller(*, enabled: bool, is_downbeat: bool, is_beat: bool = False) -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._enabled = enabled
    inst._grid = SimpleNamespace(is_downbeat=is_downbeat, is_beat=is_beat)
    inst._hud_downbeat_pulse = 0.0
    inst._hud_beat_pulse = 0.0
    return inst


def test_downbeat_fire_sets_pulse_to_full() -> None:
    controller = _controller(enabled=True, is_downbeat=True)

    controller._update_hud_downbeat_pulse(dt=1 / 60)

    assert controller.hud_downbeat_pulse == 1.0


def test_pulse_decays_exponentially_between_downbeats() -> None:
    controller = _controller(enabled=True, is_downbeat=False)
    controller._hud_downbeat_pulse = 1.0
    dt = 0.1

    controller._update_hud_downbeat_pulse(dt)

    assert controller.hud_downbeat_pulse == max(0.0, 1.0 - dt * _HUD_DOWNBEAT_PULSE_DECAY)
    assert 0.0 < controller.hud_downbeat_pulse < 1.0


def test_pulse_clamps_at_zero_and_does_not_go_negative() -> None:
    controller = _controller(enabled=True, is_downbeat=False)
    controller._hud_downbeat_pulse = 0.05

    controller._update_hud_downbeat_pulse(dt=1.0)

    assert controller.hud_downbeat_pulse == 0.0


def test_pulse_reads_zero_while_auto_vj_disabled() -> None:
    """The HUD dot must go dark immediately when Auto VJ is off, regardless
    of stale internal pulse state left over from before it was disabled."""
    controller = _controller(enabled=False, is_downbeat=False)
    controller._hud_downbeat_pulse = 1.0

    assert controller.hud_downbeat_pulse == 0.0


def test_beat_fire_sets_pulse_to_full() -> None:
    controller = _controller(enabled=True, is_downbeat=False, is_beat=True)

    controller._update_hud_beat_pulse(dt=1 / 60)

    assert controller.hud_beat_pulse == 1.0


def test_beat_pulse_decays_faster_than_downbeat_pulse() -> None:
    """The per-beat pulse must decay quicker than the downbeat pulse so 4
    beats/bar read as distinct flashes rather than blending together."""
    controller = _controller(enabled=True, is_downbeat=False, is_beat=False)
    controller._hud_beat_pulse = 1.0
    controller._hud_downbeat_pulse = 1.0
    dt = 0.1

    controller._update_hud_beat_pulse(dt)
    controller._update_hud_downbeat_pulse(dt)

    assert controller.hud_beat_pulse == max(0.0, 1.0 - dt * _HUD_BEAT_PULSE_DECAY)
    assert controller.hud_beat_pulse < controller.hud_downbeat_pulse


def test_beat_pulse_clamps_at_zero_and_does_not_go_negative() -> None:
    controller = _controller(enabled=True, is_downbeat=False, is_beat=False)
    controller._hud_beat_pulse = 0.05

    controller._update_hud_beat_pulse(dt=1.0)

    assert controller.hud_beat_pulse == 0.0


def test_beat_pulse_reads_zero_while_auto_vj_disabled() -> None:
    controller = _controller(enabled=False, is_downbeat=False, is_beat=False)
    controller._hud_beat_pulse = 1.0

    assert controller.hud_beat_pulse == 0.0


def test_downbeat_fire_also_sets_beat_pulse_since_a_downbeat_is_a_beat() -> None:
    """A downbeat is beat #1 of the bar -- is_downbeat firing should not
    leave the plain beat pulse untouched, since _grid sets is_beat=True on
    the exact same frame as is_downbeat=True."""
    controller = _controller(enabled=True, is_downbeat=True, is_beat=True)

    controller._update_hud_beat_pulse(dt=1 / 60)
    controller._update_hud_downbeat_pulse(dt=1 / 60)

    assert controller.hud_beat_pulse == 1.0
    assert controller.hud_downbeat_pulse == 1.0


class _FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def mark(self, action: str, **info) -> None:
        self.calls.append((action, info))


def _event_controller(*, is_downbeat: bool, bpm: float = 128.0, downbeat_confidence: float = 0.5) -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._grid = SimpleNamespace(is_downbeat=is_downbeat, bpm=bpm, downbeat_confidence=downbeat_confidence)
    inst._downbeat_bar_count = 0
    inst._engine = _FakeEngine()
    inst._mode = 'DROP'
    inst._profile = 'house'
    return inst


def test_downbeat_fire_logs_event_and_increments_counter() -> None:
    """Every real is_downbeat firing must log its own event -- detector_tick's
    once-per-second-throttled snapshot only catches a single-frame flag by
    ~1/60 chance and cannot be used to measure the true per-bar rate."""
    controller = _event_controller(is_downbeat=True, bpm=128.0, downbeat_confidence=0.61)

    controller._maybe_log_downbeat_event()

    assert controller._downbeat_bar_count == 1
    assert len(controller._engine.calls) == 1
    action, info = controller._engine.calls[0]
    assert action == 'downbeat_fire'
    assert info['bar_count'] == 1
    assert info['mode'] == 'DROP'
    assert info['profile'] == 'house'
    assert info['bpm'] == 128.0
    assert info['downbeat_confidence'] == 0.61


def test_no_event_logged_when_is_downbeat_false() -> None:
    controller = _event_controller(is_downbeat=False)

    controller._maybe_log_downbeat_event()

    assert controller._downbeat_bar_count == 0
    assert controller._engine.calls == []


def test_downbeat_bar_count_increments_across_multiple_fires() -> None:
    controller = _event_controller(is_downbeat=True)

    for _ in range(3):
        controller._maybe_log_downbeat_event()

    assert controller._downbeat_bar_count == 3
    assert [info['bar_count'] for _, info in controller._engine.calls] == [1, 2, 3]


def test_no_grid_does_not_raise() -> None:
    controller = _event_controller(is_downbeat=True)
    controller._grid = None

    controller._maybe_log_downbeat_event()

    assert controller._downbeat_bar_count == 0
    assert controller._engine.calls == []
