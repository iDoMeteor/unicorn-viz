"""Regression tests for BeatGridTracker (v1 — IOI-median estimator).

This is the legacy/fallback beat-detection engine (`beat_tracker_engine =
"legacy"`); BeatTracker (v2, ACF-based) is the active default and has its
own dedicated test_beat_tracker_v2.py. v1 had zero direct test coverage
before this file.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


_BEAT_GRID_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'beat_grid.py'
_SPEC = importlib.util.spec_from_file_location('test_beat_grid_tracker_v1_module', _BEAT_GRID_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
BeatGridTracker = _MOD.BeatGridTracker


class _FakeOnset:
    def __init__(self, t: float, strength: float = 1.0) -> None:
        self.t = t
        self.strength = strength


def _audio(bass: float = 0.5, mid: float = 0.3, treble: float = 0.2) -> SimpleNamespace:
    return SimpleNamespace(bass=bass, mid=mid, treble=treble)


def _run_steady_click_track(
    tracker: "BeatGridTracker",
    *,
    bpm: float,
    duration_s: float,
    start_t: float = 0.0,
    fps: float = 60.0,
) -> float:
    period = 60.0 / bpm
    dt = 1.0 / fps
    t = start_t
    next_onset = start_t
    end_t = start_t + duration_s
    audio = _audio()
    while t < end_t:
        onsets = None
        if t >= next_onset:
            onsets = [_FakeOnset(next_onset)]
            next_onset += period
        tracker.update(dt, audio, onsets=onsets, t=t)
        t += dt
    return t


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def test_default_state() -> None:
    bg = BeatGridTracker({})
    assert bg.bpm == 0.0
    assert bg.confidence == 0.0
    assert bg.is_beat is False
    assert bg.is_downbeat is False
    assert bg.beat_index == -1


# ---------------------------------------------------------------------------
# Refractory gate
# ---------------------------------------------------------------------------

def test_refractory_gate_ignores_duplicate_onset() -> None:
    bg = BeatGridTracker({})
    audio = _audio()
    bg.update(1 / 60, audio, onsets=[_FakeOnset(0.0)], t=0.0)
    bg.update(1 / 60, audio, onsets=[_FakeOnset(0.05)], t=0.05)  # inside 0.16s refractory

    assert list(bg._beat_times) == [0.0]


def test_onset_past_refractory_window_is_accepted() -> None:
    bg = BeatGridTracker({})
    audio = _audio()
    bg.update(1 / 60, audio, onsets=[_FakeOnset(0.0)], t=0.0)
    bg.update(1 / 60, audio, onsets=[_FakeOnset(0.20)], t=0.20)  # past 0.16s refractory

    assert list(bg._beat_times) == [0.0, 0.20]


# ---------------------------------------------------------------------------
# BPM lock
# ---------------------------------------------------------------------------

def test_locks_onto_steady_120_bpm_click_track() -> None:
    bg = BeatGridTracker({})
    _run_steady_click_track(bg, bpm=120.0, duration_s=8.0)

    assert bg.bpm == pytest.approx(120.0, abs=1.0)
    assert bg.confidence > 0.9


def test_locks_onto_steady_140_bpm_click_track() -> None:
    """Different tempo from the 120 case above -- the median-IOI estimator
    is not ACF-based, so it doesn't share v2's per-BPM convergence-speed
    quirks; a clean lock is expected across a wide BPM range."""
    bg = BeatGridTracker({})
    _run_steady_click_track(bg, bpm=140.0, duration_s=8.0)

    assert bg.bpm == pytest.approx(140.0, abs=1.0)


# ---------------------------------------------------------------------------
# Bar / downbeat counting
# ---------------------------------------------------------------------------

def test_is_downbeat_fires_exactly_once_per_four_beats() -> None:
    bg = BeatGridTracker({})
    period = 0.5
    dt = 1.0 / 60.0
    t = 0.0
    next_onset = 0.0
    audio = _audio()
    beat_count = 0
    downbeat_count = 0
    while t < 20.0:
        onsets = None
        if t >= next_onset:
            onsets = [_FakeOnset(next_onset)]
            next_onset += period
        bg.update(dt, audio, onsets=onsets, t=t)
        if bg.is_beat:
            beat_count += 1
        if bg.is_downbeat:
            downbeat_count += 1
        t += dt

    assert beat_count > 0
    assert downbeat_count > 0
    assert beat_count == downbeat_count * 4


def test_beat_index_increments_once_per_accepted_onset() -> None:
    bg = BeatGridTracker({})
    assert bg.beat_index == -1

    _run_steady_click_track(bg, bpm=120.0, duration_s=4.0)
    assert bg.beat_index >= 0


def test_off_grid_onset_does_not_advance_bar_count() -> None:
    """A heavily off-grid onset (>35% deviation from the expected interval,
    once locked with confidence >= 0.55) must not desync the 4-beat bar
    counter -- it's tracked as an outlier instead."""
    bg = BeatGridTracker({})
    _run_steady_click_track(bg, bpm=120.0, duration_s=8.0)
    assert bg.confidence >= 0.55, 'test premise: must be confidently locked for the outlier check to engage'
    bar_count_before = bg._bar_beat_count
    outliers_before = bg._bar_phase_outliers

    off_t = bg._last_beat_t + 0.7  # expected ~0.5s; 0.7s is a 40% deviation
    bg.update(1 / 60, _audio(), onsets=[_FakeOnset(off_t)], t=off_t)

    assert bg._bar_phase_outliers == outliers_before + 1
    assert bg._bar_beat_count == bar_count_before, 'outlier onset must not advance the bar counter'


# ---------------------------------------------------------------------------
# set_profile()
# ---------------------------------------------------------------------------

def test_set_profile_applies_prior_only() -> None:
    """set_profile() must NOT narrow _bpm_min/_bpm_max (P0-A): a genre
    profile is soft evidence via the prior, not a hard search-range clamp
    -- see docs/audits/2026-08-04-bpm-detector-audit.md."""
    bg = BeatGridTracker({})
    bpm_min_before, bpm_max_before = bg._bpm_min, bg._bpm_max
    profile = SimpleNamespace(
        bpm_prior_mu=95.0,
        bpm_prior_sigma=0.50,
        bpm_hint_min=90.0,
        bpm_hint_max=110.0,
    )
    bg.set_profile(profile)

    assert bg._prior_mu == 95.0
    assert bg._prior_sigma == 0.50
    assert bg._bpm_min == bpm_min_before
    assert bg._bpm_max == bpm_max_before


def test_set_profile_ignores_none() -> None:
    bg = BeatGridTracker({})
    mu_before = bg._prior_mu
    bg.set_profile(None)
    assert bg._prior_mu == mu_before


# ---------------------------------------------------------------------------
# prime_tempo() -- P0-B external ground-truth BPM (e.g. dj-mixer)
# ---------------------------------------------------------------------------

def test_prime_tempo_sets_bpm_and_raises_confidence() -> None:
    bg = BeatGridTracker({})
    bg._bpm = 0.0
    bg._confidence = 0.0

    bg.prime_tempo(128.0)

    assert bg._bpm == 128.0
    assert bg._confidence == pytest.approx(0.9)


def test_prime_tempo_never_lowers_existing_confidence() -> None:
    bg = BeatGridTracker({})
    bg._confidence = 0.95

    bg.prime_tempo(128.0, confidence=0.5)

    assert bg._confidence == pytest.approx(0.95)


def test_prime_tempo_ignores_non_positive_bpm() -> None:
    bg = BeatGridTracker({})
    bg._bpm = 124.0

    bg.prime_tempo(0.0)
    bg.prime_tempo(-5.0)

    assert bg._bpm == 124.0


# ---------------------------------------------------------------------------
# Downbeat callback scheduling
# ---------------------------------------------------------------------------

def test_scheduled_callback_fires_on_next_downbeat() -> None:
    bg = BeatGridTracker({})
    fired = []
    bg.schedule_for_next_downbeat(lambda: fired.append(True))

    period = 0.5
    dt = 1.0 / 60.0
    t = 0.0
    next_onset = 0.0
    audio = _audio()
    while t < 20.0 and not fired:
        onsets = None
        if t >= next_onset:
            onsets = [_FakeOnset(next_onset)]
            next_onset += period
        bg.update(dt, audio, onsets=onsets, t=t)
        t += dt

    assert fired


def test_clear_pending_discards_scheduled_callbacks() -> None:
    bg = BeatGridTracker({})
    fired = []
    bg.schedule_for_next_downbeat(lambda: fired.append(True))
    bg.clear_pending()

    _run_steady_click_track(bg, bpm=120.0, duration_s=8.0)
    assert not fired


# ---------------------------------------------------------------------------
# Energy / drop_score sanity
# ---------------------------------------------------------------------------

def test_drop_score_stays_bounded_zero_to_one() -> None:
    bg = BeatGridTracker({})
    dt = 1.0 / 60.0
    t = 0.0
    loud = SimpleNamespace(bass=1.0, mid=1.0, treble=1.0)
    while t < 5.0:
        bg.update(dt, loud, onsets=None, t=t)
        assert 0.0 <= bg.drop_score <= 1.0
        t += dt


def test_drop_score_no_longer_double_counts_treble() -> None:
    """2026-08-09: same fix as BeatTracker (v2) -- see test_beat_tracker_v2.py's
    test of the same name for the full rationale. v1 had the identical
    double-count (standalone treble_norm term + band_blend's own treble
    share)."""
    dt = 1.0 / 60.0
    bass_only = BeatGridTracker({})
    treble_only = BeatGridTracker({})
    t = 0.0
    while t < 3.0:
        bass_only.update(dt, SimpleNamespace(bass=1.0, mid=0.0, treble=0.0), onsets=None, t=t)
        treble_only.update(dt, SimpleNamespace(bass=0.0, mid=0.0, treble=1.0), onsets=None, t=t)
        t += dt

    assert bass_only.drop_score > treble_only.drop_score


def test_band_blend_rebalanced_toward_bass() -> None:
    """2026-08-09: same rebalance as BeatTracker (v2) -- band_blend split
    0.45/0.30/0.25 -> 0.7/0.2/0.1 (bass/mid/treble)."""
    dt = 1.0 / 60.0
    bass_only = BeatGridTracker({})
    mid_only = BeatGridTracker({})
    t = 0.0
    while t < 3.0:
        bass_only.update(dt, SimpleNamespace(bass=1.0, mid=0.0, treble=0.0), onsets=None, t=t)
        mid_only.update(dt, SimpleNamespace(bass=0.0, mid=1.0, treble=0.0), onsets=None, t=t)
        t += dt

    assert bass_only.drop_score > mid_only.drop_score


def test_energy_slope_is_positive_when_energy_is_rising() -> None:
    bg = BeatGridTracker({})
    dt = 1.0 / 60.0
    t = 0.0
    silent = SimpleNamespace(bass=0.0, mid=0.0, treble=0.0)
    while t < 3.0:
        bg.update(dt, silent, onsets=None, t=t)
        t += dt

    loud = SimpleNamespace(bass=1.0, mid=1.0, treble=1.0)
    while t < 3.5:
        bg.update(dt, loud, onsets=None, t=t)
        t += dt

    assert bg.energy_slope > 0.0
