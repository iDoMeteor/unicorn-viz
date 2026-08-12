"""Regression tests for BeatTrackerV3 (v2 + frozen tempo prior while locked).

Root cause this engine fixes (see docs/adr/vj-system.md "Recommender Weight
Promotion + Manual-Override Label"): v2's set_profile() unconditionally
re-primes the ACF's Gaussian tempo prior on every call, including when the
profile recommender auto-applies a new genre profile mid-track -- dragging an
already-locked BPM toward the new profile's prior even though the track's
real tempo never changed. v3 only inherits set_profile() differently; every
other method (update(), the ACF/phase-lock machinery) is unchanged from v2.

As of P0-A/P1-D (docs/audits/2026-08-04-bpm-detector-audit.md), v2's
set_profile() no longer narrows the ACF search range at all -- only the
Gaussian prior. So v3's own set_profile() override is now a complete no-op
while confidently locked (freezing "nothing" was previously "freeze the
prior but still apply the range clamp"; now there is no clamp to apply).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

_BEAT_GRID_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'beat_grid.py'
_SPEC = importlib.util.spec_from_file_location('test_beat_tracker_v3_module', _BEAT_GRID_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
BeatTracker = _MOD.BeatTracker
BeatTrackerV3 = _MOD.BeatTrackerV3
BeatGridTracker = _MOD.BeatGridTracker


class _FakeOnset:
    def __init__(self, t: float, strength: float = 1.0) -> None:
        self.t = t
        self.strength = strength


class _FakeProfile:
    def __init__(self, mu: float, sigma: float, hint_min: float | None = None, hint_max: float | None = None) -> None:
        self.bpm_prior_mu = mu
        self.bpm_prior_sigma = sigma
        self.bpm_hint_min = hint_min
        self.bpm_hint_max = hint_max


def _audio(bass: float = 0.5, mid: float = 0.3, treble: float = 0.2, flux: float = 0.1) -> SimpleNamespace:
    return SimpleNamespace(bass=bass, mid=mid, treble=treble, spectral_flux=flux)


def _run_steady_click_track(tracker, *, bpm: float, duration_s: float, start_t: float = 0.0, fps: float = 60.0) -> float:
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


# ---- ENGINE_VERSION -----------------------------------------------------


def test_engine_versions_are_distinct_and_present() -> None:
    assert BeatGridTracker.ENGINE_VERSION == '1.0.0'
    assert BeatTracker.ENGINE_VERSION == '2.0.0'
    assert BeatTrackerV3.ENGINE_VERSION == '3.0.0'


# ---- set_profile(): frozen while confidently locked ----------------------


def test_set_profile_freezes_prior_when_confidently_locked() -> None:
    tr = BeatTrackerV3({})
    tr._bpm = 124.0
    tr._confidence = 0.65   # >= _PRIOR_FREEZE_CONFIDENCE (0.55)
    before_mu = tr._prior_mu

    tr.set_profile(_FakeProfile(mu=145.0, sigma=0.16, hint_min=140.0, hint_max=149.0))

    assert tr._prior_mu == before_mu   # untouched
    assert tr._bpm == 124.0            # bpm itself never touched by set_profile


def test_set_profile_is_a_full_noop_when_locked() -> None:
    """P1-D: once v2's set_profile() no longer narrows the search range at
    all (P0-A), there is nothing left for a locked v3 switch to apply --
    set_profile() is a complete no-op while confidently locked, not just a
    partial prior freeze. See docs/audits/2026-08-04-bpm-detector-audit.md."""
    tr = BeatTrackerV3({})
    tr._bpm = 124.0
    tr._confidence = 0.65
    bpm_min_before, bpm_max_before = tr._bpm_min, tr._bpm_max

    tr.set_profile(_FakeProfile(mu=145.0, sigma=0.16, hint_min=140.0, hint_max=149.0))

    assert tr._bpm_min == bpm_min_before
    assert tr._bpm_max == bpm_max_before


def test_set_profile_fully_reprimes_when_not_locked_low_confidence() -> None:
    tr = BeatTrackerV3({})
    tr._bpm = 124.0
    tr._confidence = 0.30   # below freeze threshold

    tr.set_profile(_FakeProfile(mu=145.0, sigma=0.16))

    assert tr._prior_mu == 145.0


def test_set_profile_fully_reprimes_when_bpm_zero() -> None:
    tr = BeatTrackerV3({})
    tr._bpm = 0.0
    tr._confidence = 0.9    # confidence alone isn't enough without bpm > 0

    tr.set_profile(_FakeProfile(mu=145.0, sigma=0.16))

    assert tr._prior_mu == 145.0


def test_set_profile_reprimes_again_after_unlock() -> None:
    tr = BeatTrackerV3({})
    tr._bpm = 124.0
    tr._confidence = 0.65
    tr.set_profile(_FakeProfile(mu=145.0, sigma=0.16))
    assert tr._prior_mu != 145.0   # frozen the first time

    tr._reset_tempo_lock()
    tr.set_profile(_FakeProfile(mu=145.0, sigma=0.16))

    assert tr._prior_mu == 145.0   # re-primed after the lock was lost


def test_set_profile_stays_frozen_through_a_mid_range_confidence_dip() -> None:
    """2026-08-12: the actual incident this hysteresis closes. A real track
    dipping to e.g. 0.40 mid-track (well above the release threshold, 0.28,
    but below the acquire one, 0.55) is completely normal -- a breakdown, a
    quiet passage -- and must not reopen re-priming. Before this fix, the
    freeze was re-evaluated fresh from the instantaneous confidence on every
    call, so this exact dip fell through to a full re-prime and (per a real
    overnight session) compounded into a multi-hour BPM drift. See the
    BeatTrackerV3 class docstring's 2026-08-12 addendum."""
    tr = BeatTrackerV3({})
    tr._bpm = 124.0
    tr._confidence = 0.65
    tr.set_profile(_FakeProfile(mu=95.0, sigma=0.50))  # freezes
    before_mu = tr._prior_mu
    assert before_mu != 95.0

    tr._confidence = 0.40   # dips below acquire (0.55) but above release (0.28)
    tr.set_profile(_FakeProfile(mu=95.0, sigma=0.50))

    assert tr._prior_mu == before_mu, (
        'a mid-range confidence dip must not unfreeze the prior -- this is '
        'exactly the gap that let a recommender-applied profile drag a '
        'correctly-locked BPM over a real overnight session'
    )


def test_set_profile_unfreezes_only_below_release_threshold() -> None:
    """The other half of the hysteresis pair: a dip that actually clears the
    release threshold (0.28) is a real signal the lock may be gone, and
    should still re-open re-priming -- the fix adds a dead zone, it doesn't
    remove the unfreeze path entirely."""
    tr = BeatTrackerV3({})
    tr._bpm = 124.0
    tr._confidence = 0.65
    tr.set_profile(_FakeProfile(mu=95.0, sigma=0.50))  # freezes
    assert tr._prior_mu != 145.0

    tr._confidence = 0.20   # below release threshold (0.28)
    tr.set_profile(_FakeProfile(mu=145.0, sigma=0.16))

    assert tr._prior_mu == 145.0, 'a dip below the release threshold must unfreeze'


def test_set_profile_none_is_noop_like_v2() -> None:
    tr = BeatTrackerV3({})
    tr._bpm = 124.0
    tr._confidence = 0.65
    before_mu = tr._prior_mu
    tr.set_profile(None)
    assert tr._prior_mu == before_mu


# ---- v2 vs v3 side-by-side: the actual regression this engine fixes ------


def test_v2_drifts_toward_new_profile_but_v3_does_not() -> None:
    """Direct A/B: lock both engines on a steady 124 BPM stream, then apply a
    mismatched high-tempo profile mid-track (mirrors the real 'Alchemist'
    session trace in the 2026-07-18 investigation) and continue the same
    steady 124 BPM audio. v2's prior drags toward the new profile; v3's does
    not move at all."""
    psytrance = _FakeProfile(mu=145.0, sigma=0.16, hint_min=140.0, hint_max=149.0)

    # Phase coherence (35-onset rolling window) needs real wall-clock time to
    # fill from a cold start -- 130s of a steady 124 BPM stream is what it
    # actually takes to cross the 0.55 lock-confidence threshold in practice
    # (verified directly against BeatTracker.update(), not assumed). 2026-08-10:
    # was 65s under the old _V2_COHERENCE_WINDOW=32/_V2_PHASE_TOL=0.18 --
    # _V2_PHASE_TOL 0.18 -> 0.12 converges noticeably slower (~120s to fully
    # stabilize at this tempo), 130s leaves real margin past that.
    for cls in (BeatTracker, BeatTrackerV3):
        tr = cls({})
        _run_steady_click_track(tr, bpm=124.0, duration_s=130.0)
        assert tr._bpm > 0.0 and tr._confidence >= 0.55, (
            f'{cls.__name__} did not reach lock confidence before profile switch '
            f'(bpm={tr._bpm}, confidence={tr._confidence})'
        )
        mu_before = tr._prior_mu

        tr.set_profile(psytrance)

        if cls is BeatTracker:
            assert tr._prior_mu == 145.0, 'v2 should re-prime toward the new profile'
        else:
            assert tr._prior_mu == mu_before, 'v3 should freeze the prior while locked'
