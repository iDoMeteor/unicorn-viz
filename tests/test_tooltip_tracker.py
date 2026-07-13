"""Unit tests for TooltipHoverTracker — the pure hover state machine.

No fakes needed: the tracker takes an injected clock, so tests advance a
plain float instead of sleeping, and regions are plain dataclasses.
"""
from __future__ import annotations

from unicornviz.tooltips import TooltipHoverTracker, TooltipRegion


class _Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def _tracker(clock: _Clock, **kwargs) -> TooltipHoverTracker:
    kwargs.setdefault('delay_s', 0.5)
    kwargs.setdefault('rearm_s', 0.1)
    kwargs.setdefault('jitter_px', 6)
    return TooltipHoverTracker(now=clock, **kwargs)


_REGION_A = TooltipRegion(rect=(0, 0, 100, 40), text='Alpha')
_REGION_B = TooltipRegion(rect=(200, 0, 100, 40), text='Beta')


def test_no_tooltip_before_the_arm_delay() -> None:
    clock = _Clock()
    tr = _tracker(clock)
    tr.on_motion(10, 10, [_REGION_A])
    assert tr.tick() is None
    clock.t += 0.49
    assert tr.tick() is None


def test_tooltip_arms_after_the_delay() -> None:
    clock = _Clock()
    tr = _tracker(clock)
    tr.on_motion(10, 10, [_REGION_A])
    clock.t += 0.5
    tip = tr.tick()
    assert tip is not None and tip.text == 'Alpha'
    assert tr.anchor == (10, 10)


def test_zero_delay_shows_immediately() -> None:
    clock = _Clock()
    tr = _tracker(clock, delay_s=0.0)
    tr.on_motion(10, 10, [_REGION_A])
    assert tr.tick() is not None


def test_movement_beyond_jitter_restarts_the_timer() -> None:
    clock = _Clock()
    tr = _tracker(clock)
    tr.on_motion(10, 10, [_REGION_A])
    clock.t += 0.4
    tr.on_motion(30, 10, [_REGION_A])  # > jitter_px away, same region
    clock.t += 0.2  # 0.6 total, but only 0.2 since re-anchor
    assert tr.tick() is None
    clock.t += 0.3
    assert tr.tick() is not None
    assert tr.anchor == (30, 10)


def test_movement_within_jitter_does_not_restart() -> None:
    clock = _Clock()
    tr = _tracker(clock)
    tr.on_motion(10, 10, [_REGION_A])
    clock.t += 0.4
    tr.on_motion(13, 12, [_REGION_A])  # within jitter
    clock.t += 0.1
    assert tr.tick() is not None


def test_leaving_the_region_disarms() -> None:
    clock = _Clock()
    tr = _tracker(clock)
    tr.on_motion(10, 10, [_REGION_A])
    clock.t += 0.5
    assert tr.tick() is not None
    tr.on_motion(150, 10, [_REGION_A])  # empty space
    assert tr.tick() is None


def test_none_position_resets_everything() -> None:
    clock = _Clock()
    tr = _tracker(clock)
    tr.on_motion(10, 10, [_REGION_A])
    clock.t += 0.5
    assert tr.tick() is not None
    tr.on_motion(None, None, [_REGION_A])
    assert tr.tick() is None
    assert tr.anchor is None


def test_warm_rearm_between_adjacent_regions() -> None:
    clock = _Clock()
    tr = _tracker(clock)
    tr.on_motion(10, 10, [_REGION_A, _REGION_B])
    clock.t += 0.5
    assert tr.tick() is not None
    # Move straight onto region B: should re-show after rearm_s, not delay_s.
    tr.on_motion(210, 10, [_REGION_A, _REGION_B])
    assert tr.tick() is None
    clock.t += 0.1
    tip = tr.tick()
    assert tip is not None and tip.text == 'Beta'


def test_warmth_expires_after_resting_in_empty_space() -> None:
    clock = _Clock()
    tr = _tracker(clock)
    tr.on_motion(10, 10, [_REGION_A, _REGION_B])
    clock.t += 0.5
    assert tr.tick() is not None
    tr.on_motion(150, 10, [_REGION_A, _REGION_B])  # empty space
    clock.t += 1.0  # warmth (0.5s window) expires
    tr.on_motion(210, 10, [_REGION_A, _REGION_B])
    clock.t += 0.1  # rearm_s would fire if still warm
    assert tr.tick() is None
    clock.t += 0.4  # full delay_s reached
    assert tr.tick() is not None


def test_click_suppresses_until_the_cursor_leaves_the_region() -> None:
    clock = _Clock()
    tr = _tracker(clock)
    tr.on_motion(10, 10, [_REGION_A])
    clock.t += 0.5
    assert tr.tick() is not None
    tr.notify_click()
    assert tr.tick() is None
    # Still inside the clicked region: stays suppressed even after delay.
    tr.on_motion(12, 12, [_REGION_A])
    clock.t += 1.0
    assert tr.tick() is None
    # Leave and re-enter: arms normally again.
    tr.on_motion(150, 10, [_REGION_A])
    tr.on_motion(10, 10, [_REGION_A])
    clock.t += 0.5
    assert tr.tick() is not None


def test_overlapping_regions_prefer_the_last_one() -> None:
    clock = _Clock()
    tr = _tracker(clock)
    over = TooltipRegion(rect=(0, 0, 100, 40), text='On top')
    tr.on_motion(10, 10, [_REGION_A, over])
    clock.t += 0.5
    tip = tr.tick()
    assert tip is not None and tip.text == 'On top'


def test_visible_tooltip_picks_up_fresh_text_for_the_same_rect() -> None:
    # Regions are rebuilt every frame; a dynamic label (e.g. PAUSE→RESUME)
    # must refresh without re-arming.
    clock = _Clock()
    tr = _tracker(clock)
    tr.on_motion(10, 10, [_REGION_A])
    clock.t += 0.5
    assert tr.tick().text == 'Alpha'
    updated = TooltipRegion(rect=_REGION_A.rect, text='Alpha v2')
    tr.on_motion(11, 11, [updated])
    assert tr.tick().text == 'Alpha v2'


def test_empty_region_list_is_harmless() -> None:
    clock = _Clock()
    tr = _tracker(clock)
    tr.on_motion(10, 10, [])
    assert tr.tick() is None
