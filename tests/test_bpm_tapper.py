"""KP-0 BPM tapper — regression tests.

Tap math, gap reset, the rolling window, and the visibility hold live in
``Overlays`` (bare ``__new__`` shells, no GL — the standard overlay test
pattern). Timestamps are injected so nothing sleeps.
"""
from __future__ import annotations

import sdl2

from unicornviz.overlays import Overlays


def _bare_overlays() -> Overlays:
    return object.__new__(Overlays)


def _tap_steady(o: Overlays, count: int, interval: float, start: float = 0.0) -> float:
    bpm = 0.0
    for i in range(count):
        bpm = o.bpm_tap(now=start + i * interval)
    return bpm


def test_first_tap_reports_nothing_yet() -> None:
    o = _bare_overlays()
    assert o.bpm_tap(now=0.0) == 0.0


def test_steady_taps_report_the_tempo() -> None:
    o = _bare_overlays()
    assert _tap_steady(o, 5, 0.5) == 120.0     # 0.5s intervals = 120 BPM
    o2 = _bare_overlays()
    assert abs(_tap_steady(o2, 9, 60.0 / 174.0) - 174.0) < 0.01


def test_gap_beyond_reset_starts_a_fresh_measurement() -> None:
    o = _bare_overlays()
    _tap_steady(o, 4, 0.5)                     # 120 BPM measured
    bpm = o.bpm_tap(now=1.5 + Overlays.BPM_TAP_RESET_S + 0.1)
    assert bpm == 0.0                          # fresh: first tap of a new run
    assert o.bpm_tap(now=1.5 + Overlays.BPM_TAP_RESET_S + 0.6) == 120.0


def test_window_keeps_only_recent_intervals() -> None:
    o = _bare_overlays()
    # 4 slow taps (60 BPM) then 12 fast (150 BPM): the rolling window sheds
    # the slow ones entirely, so the readout converges on the fast tempo.
    t = 0.0
    for _ in range(4):
        o.bpm_tap(now=t)
        t += 1.0
    for _ in range(12):
        bpm = o.bpm_tap(now=t)
        t += 0.4
    assert abs(bpm - 150.0) < 0.01
    assert len(o._bpm_tap_times) == Overlays.BPM_TAP_MAX_TAPS


def test_readout_visible_only_within_the_hold_window() -> None:
    o = _bare_overlays()
    assert o.bpm_tapper_active(now=0.0) is False   # never tapped
    o.bpm_tap(now=10.0)
    assert o.bpm_tapper_active(now=10.1) is True
    assert o.bpm_tapper_active(now=10.0 + Overlays.BPM_TAP_HOLD_S + 0.1) is False


def test_kp0_is_bound_in_help() -> None:
    # Single source of truth: the KP 0 entry exists in CORE_HELP_SECTIONS.
    entries = [
        (key, desc)
        for _, section_entries in Overlays.CORE_HELP_SECTIONS
        for key, desc in section_entries
    ]
    assert any(key == 'KP 0' and 'BPM tapper' in desc for key, desc in entries)


def test_kp0_keysym_matches_the_hotkey_branch() -> None:
    # Guard against the binding drifting: the branch dispatches SDLK_KP_0.
    import inspect

    from unicornviz import hotkeys

    src = inspect.getsource(hotkeys.HotkeyHandler.handle)
    assert 'SDLK_KP_0' in src and 'bpm_tap' in src
    assert sdl2.SDLK_KP_0  # symbol exists in this SDL build
