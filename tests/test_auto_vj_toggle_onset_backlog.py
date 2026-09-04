from __future__ import annotations

import importlib.util
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest


_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_AUTO_VJ_SPEC = importlib.util.spec_from_file_location('test_auto_vj_toggle_module', _AUTO_VJ_PATH)
assert _AUTO_VJ_SPEC is not None and _AUTO_VJ_SPEC.loader is not None
_AUTO_VJ_MODULE = importlib.util.module_from_spec(_AUTO_VJ_SPEC)
_AUTO_VJ_SPEC.loader.exec_module(_AUTO_VJ_MODULE)
AutoVJController = _AUTO_VJ_MODULE.AutoVJController


class _AudioManager:
    """Stub whose drain_onsets() simulates a backlog accumulated while disabled."""

    def __init__(self, backlog_size: int) -> None:
        self._backlog_size = backlog_size
        self.drain_calls = 0

    def drain_onsets(self) -> list[object]:
        self.drain_calls += 1
        # Only the first drain call returns the backlog; subsequent calls
        # (real per-frame draining) return an empty list, matching how the
        # real analyzer's deque empties out after one drain.
        if self.drain_calls == 1:
            return [object()] * self._backlog_size
        return []


def _controller(*, enabled: bool, audio_manager) -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._enabled = enabled
    inst._app = SimpleNamespace(vj_api=SimpleNamespace(
        set_reactivity=lambda *_a, **_k: None,
        clear_postfx=lambda *_a, **_k: None,
    ))
    inst._grid = None
    inst._mode = 'CRUISE'
    inst._drop_pending = False
    inst._status_text = ''
    inst._profile_label = lambda: 'normie'
    inst._startup_grace_s = 0.0
    inst._startup_guard_until_t = 0.0
    inst._startup_was_guarded = False
    inst._audio_manager = audio_manager
    inst._last_onset_count = 999  # deliberately stale, should be reset on enable
    inst._onset_density_1min_history = deque([1.0, 2.0, 3.0])  # deliberately stale, should be cleared on enable
    return inst


def test_toggle_on_discards_onset_backlog_from_disabled_period() -> None:
    """Re-enabling must flush the analyzer's onset queue, not process it as one burst.

    Regression for a real session bug: the onset queue (capped at 256, see
    unicornviz/audio/analyzer.py) is only ever drained by Auto VJ. After being
    disabled for a while, it fills to the cap; without a discard on resume,
    the first real tick would report all 256 queued onsets as a single
    sample, spiking onset_density into the hundreds and blowing up the
    recommender's onset_fit score term by thousands (confirmed against a
    real session log).
    """
    audio_manager = _AudioManager(backlog_size=256)
    controller = _controller(enabled=False, audio_manager=audio_manager)

    new_state = controller.toggle()

    assert new_state is True
    assert audio_manager.drain_calls == 1, 'toggle-on must drain the backlog exactly once'
    assert controller._last_onset_count == 0, 'stale onset count must be reset on enable'
    assert len(controller._onset_density_1min_history) == 0, 'stale onset-density history must be cleared on enable'


def test_toggle_off_does_not_touch_onset_queue() -> None:
    """Disabling shouldn't drain onsets -- only the enable path needs to flush."""
    audio_manager = _AudioManager(backlog_size=256)
    controller = _controller(enabled=True, audio_manager=audio_manager)

    new_state = controller.toggle()

    assert new_state is False
    assert audio_manager.drain_calls == 0


def _bare_density() -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._onset_density_1min_history = deque()
    inst._clock = None
    return inst


def test_onset_density_1min_zero_with_no_history() -> None:
    inst = _bare_density()
    assert inst._onset_density_1min() == 0.0


def test_onset_density_1min_uses_actual_elapsed_span() -> None:
    """Divides by the window's own real span, not a hardcoded 60.0 -- a
    session only 10s old with 5 onsets reads 0.5/s, not 5/60."""
    inst = _bare_density()
    t = [100.0]
    inst._clock = lambda: t[0]
    for i in range(5):
        inst._onset_density_1min_history.append(90.0 + i)  # onsets at t=90..94
    t[0] = 100.0  # "now" -- oldest onset is 10s behind

    density = inst._onset_density_1min()

    assert density == pytest.approx(5.0 / 10.0)


def test_onset_density_1min_below_half_second_span_reads_zero() -> None:
    """Guards the exact failure mode toggle()'s own onset-backlog comment
    describes: a burst of onsets landing in one near-instantaneous tick
    must not read as a physically-impossible rate."""
    inst = _bare_density()
    t = [10.0]
    inst._clock = lambda: t[0]
    for _ in range(50):
        inst._onset_density_1min_history.append(10.0)

    assert inst._onset_density_1min() == 0.0


def test_toggle_on_without_audio_manager_does_not_raise() -> None:
    """Auto VJ must stay functional when the audio manager is unavailable."""
    controller = _controller(enabled=False, audio_manager=None)

    new_state = controller.toggle()

    assert new_state is True
    assert controller._last_onset_count == 0
