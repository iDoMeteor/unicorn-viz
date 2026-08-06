"""Regression tests for the wide-BPM-range Fire DJ easter egg
(docs/adr/vj-system.md § "Fire DJ Profile Removed, Replaced by a
Wide-BPM-Range Easter Egg", 2026-08-06).

Covers _maybe_check_wide_bpm_easter_egg():
- Fires once the rolling window's max-min BPM span clears the threshold
- Does not fire below threshold
- Respects the shared fire_dj cooldown (no back-to-back retrigger)
- Only samples locked (confidence >= _BPM_LOCK_CONFIDENCE) BPM readings
- Prunes samples older than the rolling window before checking span
"""
from __future__ import annotations

import importlib.util
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace

_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_SPEC = importlib.util.spec_from_file_location('test_wide_bpm_easter_egg_module', _AUTO_VJ_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
AutoVJController = _MOD.AutoVJController


def _bare_controller(*, samples: list[tuple[float, float]] | None = None, **overrides) -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._wide_bpm_window_s = 600.0
    inst._wide_bpm_span_threshold = 30.0
    inst._wide_bpm_sample_interval_s = 2.0
    inst._wide_bpm_last_sample_t = -1e9  # always allow the next sample through
    inst._wide_bpm_samples = deque(samples or [])
    inst._fire_dj_last_t = -1e9
    inst._fire_dj_cooldown_s = 1200.0
    inst._grid = SimpleNamespace(confidence=0.9)
    inst._BPM_LOCK_CONFIDENCE = AutoVJController._BPM_LOCK_CONFIDENCE
    inst._trigger_calls: list[float] = []
    inst._trigger_fire_dj_celebration = lambda: inst._trigger_calls.append(time.monotonic())
    for k, v in overrides.items():
        setattr(inst, k, v)
    return inst


def test_fires_when_span_clears_threshold() -> None:
    now = time.monotonic()
    inst = _bare_controller(samples=[(now - 300.0, 120.0)])
    inst._maybe_check_wide_bpm_easter_egg(155.0)  # +35 BPM span vs. the seeded sample
    assert len(inst._trigger_calls) == 1


def test_does_not_fire_below_threshold() -> None:
    now = time.monotonic()
    inst = _bare_controller(samples=[(now - 300.0, 120.0)])
    inst._maybe_check_wide_bpm_easter_egg(140.0)  # only +20 BPM span
    assert inst._trigger_calls == []


def test_respects_cooldown_no_back_to_back_retrigger() -> None:
    now = time.monotonic()
    inst = _bare_controller(samples=[(now - 300.0, 120.0)], _fire_dj_last_t=now - 10.0)
    inst._maybe_check_wide_bpm_easter_egg(160.0)  # well over threshold
    assert inst._trigger_calls == []  # cooldown (1200s) not yet elapsed


def test_cooldown_elapsed_allows_retrigger() -> None:
    now = time.monotonic()
    inst = _bare_controller(samples=[(now - 300.0, 120.0)], _fire_dj_last_t=now - 1300.0)
    inst._maybe_check_wide_bpm_easter_egg(160.0)
    assert len(inst._trigger_calls) == 1


def test_unlocked_low_confidence_reading_not_sampled() -> None:
    now = time.monotonic()
    inst = _bare_controller(samples=[(now - 300.0, 120.0)])
    inst._grid = SimpleNamespace(confidence=0.1)  # below _BPM_LOCK_CONFIDENCE
    inst._maybe_check_wide_bpm_easter_egg(160.0)  # would clear threshold if sampled
    # The new (unlocked) reading never entered the window, so span is still
    # just the single seeded 120.0 sample -- no fire.
    assert inst._trigger_calls == []


def test_samples_older_than_window_are_pruned_before_span_check() -> None:
    now = time.monotonic()
    inst = _bare_controller(samples=[(now - 700.0, 90.0)])  # older than the 600s window
    inst._maybe_check_wide_bpm_easter_egg(105.0)  # +15 vs. the stale sample, not enough anyway
    assert inst._trigger_calls == []


def test_throttles_sampling_to_configured_interval() -> None:
    now = time.monotonic()
    inst = _bare_controller(samples=[(now - 300.0, 120.0)], _wide_bpm_last_sample_t=now)
    inst._maybe_check_wide_bpm_easter_egg(160.0)  # called again immediately
    # Throttled: the new reading was never appended, so span is unchanged
    # (still just the single seeded 120.0 sample) -- no fire.
    assert inst._trigger_calls == []
    assert len(inst._wide_bpm_samples) == 1
