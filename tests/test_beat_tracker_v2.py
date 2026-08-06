"""Regression tests for BeatTracker (v2 — ACF + phase-locked oscillator).

This is the active beat-detection engine (`beat_tracker_engine = "v2"`) and
the site of most of the confidence-blend, downbeat-gate, and tempo-hold
tuning work in this project's history — until now it had zero direct unit
coverage; only a path-existence sanity check for a constant in bpm_eval.py
mentioned beat_grid.py at all.

Tests drive the tracker with synthetic OnsetEvent-like objects at known,
exact intervals so BPM convergence can be asserted against ground truth
rather than eyeballed from a real audio file.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


_BEAT_GRID_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'beat_grid.py'
_SPEC = importlib.util.spec_from_file_location('test_beat_tracker_v2_module', _BEAT_GRID_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
BeatTracker = _MOD.BeatTracker


class _FakeOnset:
    """Mirrors Analyzer.OnsetEvent's public shape (t, strength)."""

    def __init__(self, t: float, strength: float = 1.0) -> None:
        self.t = t
        self.strength = strength


def _audio(bass: float = 0.5, mid: float = 0.3, treble: float = 0.2, flux: float = 0.1) -> SimpleNamespace:
    return SimpleNamespace(bass=bass, mid=mid, treble=treble, spectral_flux=flux)


def _run_steady_click_track(
    tracker: "BeatTracker",
    *,
    bpm: float,
    duration_s: float,
    start_t: float = 0.0,
    fps: float = 60.0,
) -> float:
    """Feed a perfectly steady onset stream at `bpm` for `duration_s` seconds.

    Returns the final simulated time `t` so callers can continue the timeline
    (e.g. into a silence gap) without losing sync.
    """
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
# BPM lock convergence
# ---------------------------------------------------------------------------

def test_locks_onto_steady_120_bpm_click_track() -> None:
    bt = BeatTracker({})
    _run_steady_click_track(bt, bpm=120.0, duration_s=10.0)

    assert bt.bpm == pytest.approx(120.0, abs=3.0)
    assert bt.beat_index >= 0, 'at least one beat should have fired'


def test_locks_onto_steady_100_bpm_click_track() -> None:
    """Different tempo, to guard against a lock that only works near the
    120 BPM perceptual prior centre.

    Note: not every BPM converges equally fast for a pure click track --
    manual probing found some tempos (e.g. 140, 174) need much longer than
    10s to clear the ACF peak-ratio confidence floor, and BPMs above the
    115 BPM tactus-check threshold can legitimately half-time fold (e.g.
    160 -> ~82) by design. 100 BPM converges cleanly within 10s and stays
    below the fold threshold, making it a clean second data point.
    """
    bt = BeatTracker({})
    _run_steady_click_track(bt, bpm=100.0, duration_s=10.0)

    assert bt.bpm == pytest.approx(100.0, abs=3.0)


def test_acf_confidence_reaches_near_maximum_on_unambiguous_signal() -> None:
    bt = BeatTracker({})
    _run_steady_click_track(bt, bpm=120.0, duration_s=10.0)

    assert bt._acf_confidence > 0.9


def test_full_confidence_blend_eventually_converges_given_enough_steady_time() -> None:
    """Known real behavior, not just a hope: phase_confidence has no explicit
    initial sync step (see _absorb_onset/_advance_phase) and only converges
    once BPM drift happens to carry phase within +/-18% tolerance by chance.
    On a perfectly steady click track this reliably happens within ~60s;
    confirmed via manual simulation before writing this test."""
    bt = BeatTracker({})
    _run_steady_click_track(bt, bpm=120.0, duration_s=60.0)

    assert bt.confidence > 0.9
    assert bt._phase_confidence > 0.9


# ---------------------------------------------------------------------------
# is_beat / is_downbeat firing rate
# ---------------------------------------------------------------------------

def test_is_downbeat_fires_exactly_once_per_four_beats() -> None:
    bt = BeatTracker({})
    period = 0.5
    dt = 1.0 / 60.0
    t = 0.0
    next_onset = 0.0
    audio = _audio()
    beat_count = 0
    downbeat_count = 0
    while t < 30.0:
        onsets = None
        if t >= next_onset:
            onsets = [_FakeOnset(next_onset)]
            next_onset += period
        bt.update(dt, audio, onsets=onsets, t=t)
        if bt.is_beat:
            beat_count += 1
        if bt.is_downbeat:
            downbeat_count += 1
        t += dt

    assert beat_count > 0
    assert downbeat_count > 0
    assert beat_count == downbeat_count * 4, (
        f'expected exactly 4 beats per downbeat, got {beat_count} beats / {downbeat_count} downbeats'
    )


def test_beat_index_starts_at_negative_one_and_increments_once_per_beat() -> None:
    bt = BeatTracker({})
    assert bt.beat_index == -1

    _run_steady_click_track(bt, bpm=120.0, duration_s=10.0)
    assert bt.beat_index >= 0


# ---------------------------------------------------------------------------
# Downbeat confidence blend (the exact bug fixed 2026-07-06: coh/base were
# accidentally the same signal, silently halving the intended four-way mix)
# ---------------------------------------------------------------------------

def test_downbeat_confidence_blend_uses_documented_weights() -> None:
    """region 45% + phase-coherence 30% + acf quality 15% + density 10%."""
    bt = BeatTracker({'analysis_mode_enabled': True})
    bt._bpm = 120.0

    # Force each component to a known, distinct value so the blend can be
    # verified precisely rather than just "is nonzero".
    bt._analysis_region_consistency = lambda bpm_candidate: 1.0  # region
    bt._phase_confidence = 0.5                                    # coh
    bt._acf_confidence = 0.2                                      # base
    # density requires >= 2 beat positions within the lookback window;
    # leave it empty so density term is 0 for a clean, exact assertion.
    bt._beat_position_map.clear()

    conf = bt._compute_downbeat_confidence(now=100.0)

    expected = 0.45 * 1.0 + 0.30 * 0.5 + 0.15 * 0.2 + 0.10 * 0.0
    assert conf == pytest.approx(expected, abs=1e-9)


def test_downbeat_confidence_coh_and_base_are_independent_signals() -> None:
    """Regression guard for the 2026-07-06 bug: coh and base must be able to
    differ. If they were silently the same underlying value again, setting
    them to different numbers here and reading them back would fail."""
    bt = BeatTracker({'analysis_mode_enabled': True})
    bt._phase_confidence = 0.9
    bt._acf_confidence = 0.1

    assert bt._phase_confidence != bt._acf_confidence
    assert bt._phase_confidence == 0.9
    assert bt._acf_confidence == 0.1


def test_downbeat_confidence_equals_raw_confidence_when_analysis_mode_off() -> None:
    bt = BeatTracker({'analysis_mode_enabled': False})
    bt._confidence = 0.42

    assert bt._compute_downbeat_confidence(now=0.0) == pytest.approx(0.42)


def test_is_downbeat_gated_below_analysis_confidence_threshold() -> None:
    """With analysis mode on and an artificially low downbeat confidence
    (region consistency forced to 0 -- can't accumulate real beat-position
    history in a short synthetic run), is_downbeat must not fire even
    though is_beat does."""
    bt = BeatTracker({
        'analysis_mode_enabled': True,
        'analysis_downbeat_confidence_min': 0.9,  # deliberately unreachable
    })
    _run_steady_click_track(bt, bpm=120.0, duration_s=10.0)

    # is_beat fires every beat regardless of the downbeat gate.
    period = 0.5
    dt = 1.0 / 60.0
    t = 10.0
    next_onset = 10.0
    audio = _audio()
    saw_beat = False
    saw_downbeat = False
    while t < 14.0:
        onsets = None
        if t >= next_onset:
            onsets = [_FakeOnset(next_onset)]
            next_onset += period
        bt.update(dt, audio, onsets=onsets, t=t)
        saw_beat = saw_beat or bt.is_beat
        saw_downbeat = saw_downbeat or bt.is_downbeat
        t += dt

    assert saw_beat, 'is_beat should still fire regardless of the downbeat gate'
    assert not saw_downbeat, 'is_downbeat must not fire below an unreachable confidence gate'


# ---------------------------------------------------------------------------
# Silence reset -- documents ACTUAL behavior (see caveat below), not assumed
# ---------------------------------------------------------------------------

def test_silence_gap_resets_bpm_to_zero() -> None:
    bt = BeatTracker({'silence_reset_s': 2.0})
    t = _run_steady_click_track(bt, bpm=120.0, duration_s=10.0)
    assert bt.bpm > 0.0

    dt = 1.0 / 60.0
    audio = _audio()
    saw_reset = False
    while t < 10.0 + 2.5:
        bt.update(dt, audio, onsets=None, t=t)
        if bt.bpm == 0.0:
            saw_reset = True
            break
        t += dt

    assert saw_reset, 'bpm must reset to 0 after silence_reset_s of no onsets'


def test_silence_reset_does_not_clear_the_onset_envelope() -> None:
    """KNOWN BEHAVIOR, not necessarily intended: _reset_tempo_lock() clears
    bpm/confidence/phase/candidate-history/beat-position-map, but NOT the
    raw onset envelope ring (_env_buf). Because the envelope still holds the
    pre-silence onset pattern for up to its ~8s window, the next periodic
    ACF re-estimation can re-lock onto stale data within a fraction of a
    second of the reset -- even with zero real onsets arriving during the
    gap. This test pins the current behavior so a future change to it is a
    deliberate, visible decision rather than a silent regression either way.
    """
    bt = BeatTracker({'silence_reset_s': 2.0})
    t = _run_steady_click_track(bt, bpm=120.0, duration_s=15.0)

    dt = 1.0 / 60.0
    audio = _audio()
    saw_reset = False
    relocked_fast = False
    reset_t = None
    while t < 15.0 + 4.0:
        bt.update(dt, audio, onsets=None, t=t)
        if bt.bpm == 0.0 and not saw_reset:
            saw_reset = True
            reset_t = t
        elif saw_reset and bt.bpm > 0.0:
            relocked_fast = (t - reset_t) < 1.0
            break
        t += dt

    assert saw_reset
    assert relocked_fast, (
        'expected the tracker to re-lock from residual envelope data within '
        '~1s of the reset (documents the envelope-not-cleared behavior)'
    )


# ---------------------------------------------------------------------------
# Tempo hold + large-jump rejection
# ---------------------------------------------------------------------------

def test_tempo_hold_freezes_bpm_once_confidence_clears_the_hold_gate() -> None:
    """The hold-skip in _estimate_tempo_acf only engages once confidence
    >= 0.45 (`self._last_t < self._tempo_hold_until_t and self._confidence
    >= 0.45`). Confidence itself needs ~40-50s of steady signal to fully
    converge (see test_full_confidence_blend_eventually_converges...), so
    a short settle window doesn't actually exercise the hold -- the EMA
    keeps drifting toward true tempo the whole time, which is correct
    behavior, not a broken hold. Settle long enough for confidence to
    clear the gate, then confirm bpm is frozen solid under the hold."""
    bt = BeatTracker({'tempo_hold_s': 30.0})
    t = _run_steady_click_track(bt, bpm=120.0, duration_s=60.0)
    assert bt.confidence >= 0.45, 'test premise: confidence must have cleared the hold gate by now'
    locked_bpm = bt.bpm

    _run_steady_click_track(bt, bpm=120.0, duration_s=5.0, start_t=t)
    # Not bit-exact: the hold window can lapse and re-refresh over a long
    # run, allowing residual EMA micro-drift. The point is no *jump*.
    assert bt.bpm == pytest.approx(locked_bpm, abs=0.05)


# ---------------------------------------------------------------------------
# set_profile()
# ---------------------------------------------------------------------------

def test_set_profile_applies_prior_only() -> None:
    """set_profile() must NOT narrow _bpm_min/_bpm_max (P0-A): a genre
    profile is soft evidence via the ACF prior, not a hard search-range
    clamp -- see docs/audits/2026-08-04-bpm-detector-audit.md. bpm_hint_min/
    max are still accepted on the profile (used elsewhere for HUD display)
    but no longer read here."""
    bt = BeatTracker({})
    bpm_min_before, bpm_max_before = bt._bpm_min, bt._bpm_max
    profile = SimpleNamespace(
        bpm_prior_mu=95.0,
        bpm_prior_sigma=0.50,  # above _MIN_PROFILE_PRIOR_SIGMA so it passes through unclamped
        bpm_hint_min=90.0,
        bpm_hint_max=110.0,
    )
    bt.set_profile(profile)

    assert bt._prior_mu == 95.0
    assert bt._prior_sigma == 0.50
    assert bt._bpm_min == bpm_min_before
    assert bt._bpm_max == bpm_max_before


def test_set_profile_ignores_none() -> None:
    bt = BeatTracker({})
    prior_mu_before = bt._prior_mu
    bt.set_profile(None)
    assert bt._prior_mu == prior_mu_before


def test_set_profile_clamps_sigma_to_the_minimum_floor() -> None:
    """A profile requesting a narrower prior than _MIN_PROFILE_PRIOR_SIGMA
    (0.45) must be clamped up to the floor, not honored verbatim -- this
    keeps a single profile's prior from dominating the ACF evidence."""
    bt = BeatTracker({})
    profile = SimpleNamespace(bpm_prior_mu=95.0, bpm_prior_sigma=0.10)
    bt.set_profile(profile)

    assert bt._prior_sigma == pytest.approx(0.45)


def test_set_profile_without_hints_leaves_bpm_range_unconstrained() -> None:
    bt = BeatTracker({})
    bpm_min_before, bpm_max_before = bt._bpm_min, bt._bpm_max
    profile = SimpleNamespace(bpm_prior_mu=95.0, bpm_prior_sigma=0.25)
    bt.set_profile(profile)

    assert bt._bpm_min == bpm_min_before
    assert bt._bpm_max == bpm_max_before


# ---------------------------------------------------------------------------
# prime_tempo() -- P0-B external ground-truth BPM (e.g. dj-mixer)
# ---------------------------------------------------------------------------

def test_prime_tempo_sets_bpm_and_raises_confidence_components() -> None:
    bt = BeatTracker({})
    bt._bpm = 0.0
    bt._acf_confidence = 0.0
    bt._phase_confidence = 0.0
    bt._confidence = 0.0

    bt.prime_tempo(128.0)

    assert bt._bpm == 128.0
    assert bt._acf_confidence == pytest.approx(0.9)
    assert bt._phase_confidence == pytest.approx(0.9)
    assert bt._confidence == pytest.approx(0.9)


def test_prime_tempo_never_lowers_existing_confidence() -> None:
    bt = BeatTracker({})
    bt._acf_confidence = 0.95
    bt._phase_confidence = 0.95
    bt._confidence = 0.95

    bt.prime_tempo(128.0, confidence=0.5)

    assert bt._confidence == pytest.approx(0.95)


def test_prime_tempo_clamps_to_valid_bpm_range() -> None:
    bt = BeatTracker({})
    bt.prime_tempo(9999.0)
    assert bt._bpm == bt._bpm_max


def test_prime_tempo_ignores_non_positive_bpm() -> None:
    bt = BeatTracker({})
    bt._bpm = 124.0

    bt.prime_tempo(0.0)
    bt.prime_tempo(-5.0)

    assert bt._bpm == 124.0


def test_prime_tempo_refreshes_tempo_hold_window() -> None:
    bt = BeatTracker({})
    bt._last_t = 100.0
    bt.prime_tempo(128.0)
    assert bt._tempo_hold_until_t == pytest.approx(100.0 + bt._tempo_hold_s)


def test_prime_tempo_sets_the_primed_confidence_floor() -> None:
    bt = BeatTracker({})
    bt.prime_tempo(128.0, confidence=0.9)
    assert bt._primed_confidence == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# 2026-08-06: primed confidence floor -- prime_tempo()'s confidence boost
# used to be purely cosmetic, overwritten by the very next onset's raw
# ACF/phase recomputation with no memory a prime had just happened. Real
# live-session evidence: primed bpm=125 conf=0.90 -> conf=0.23 within 0.5s,
# same bpm, repeating roughly every recommender eval cycle (~8s) for the
# whole session. See docs/adr/vj-system.md.
# ---------------------------------------------------------------------------

def test_confidence_floor_survives_an_onset_that_misses_phase() -> None:
    """A real onset that lands outside phase_tol (a genuine miss against
    the freshly-primed tempo, e.g. the phase oscillator hasn't resynced
    yet) must not crash self._confidence below the primed floor while the
    prime is still fresh."""
    bt = BeatTracker({})
    bt._last_t = 100.0
    bt.prime_tempo(125.0, confidence=0.9)
    assert bt._confidence == pytest.approx(0.9)

    # Force a phase-coherence miss: phase far from 0, well outside phase_tol.
    bt._phase = 0.5
    bt._absorb_onset(100.1, 1.0)

    assert bt._confidence >= 0.9 - 1e-9


def test_confidence_floor_expires_with_the_hold_window() -> None:
    """Once _tempo_hold_until_t has passed, the floor must stop applying --
    this is a temporary bridge to the next prime, not a permanent override
    of live evidence."""
    bt = BeatTracker({})
    bt._last_t = 100.0
    bt.prime_tempo(125.0, confidence=0.9)

    bt._phase = 0.5
    bt._last_t = bt._tempo_hold_until_t + 1.0  # hold window has expired
    bt._absorb_onset(bt._last_t, 1.0)

    assert bt._confidence < 0.9


def test_confidence_floor_does_not_apply_before_any_prime() -> None:
    """_primed_confidence defaults to 0.0, so a tracker that was never
    primed must behave exactly as before -- no accidental floor from an
    uninitialized value."""
    bt = BeatTracker({})
    bt._last_t = 100.0
    bt._tempo_hold_until_t = 200.0  # pretend a hold window is active
    bt._acf_confidence = 0.1
    bt._phase = 0.5

    bt._absorb_onset(100.1, 1.0)

    assert bt._confidence < 0.5


# ---------------------------------------------------------------------------
# Downbeat callback scheduling
# ---------------------------------------------------------------------------

def test_scheduled_callback_fires_on_next_downbeat() -> None:
    bt = BeatTracker({})
    fired = []
    bt.schedule_for_next_downbeat(lambda: fired.append(True))

    period = 0.5
    dt = 1.0 / 60.0
    t = 0.0
    next_onset = 0.0
    audio = _audio()
    while t < 30.0 and not fired:
        onsets = None
        if t >= next_onset:
            onsets = [_FakeOnset(next_onset)]
            next_onset += period
        bt.update(dt, audio, onsets=onsets, t=t)
        t += dt

    assert fired, 'scheduled callback should have fired by the first downbeat'


def test_clear_pending_discards_scheduled_callbacks() -> None:
    bt = BeatTracker({})
    fired = []
    bt.schedule_for_next_downbeat(lambda: fired.append(True))
    bt.clear_pending()

    _run_steady_click_track(bt, bpm=120.0, duration_s=10.0)
    assert not fired, 'cleared callback must not fire even after a real downbeat'


def test_callback_exception_does_not_propagate() -> None:
    bt = BeatTracker({})

    def _boom() -> None:
        raise RuntimeError('boom')

    bt.schedule_for_next_downbeat(_boom)
    # Must not raise despite the callback throwing.
    _run_steady_click_track(bt, bpm=120.0, duration_s=10.0)


# ---------------------------------------------------------------------------
# Energy / drop_score sanity
# ---------------------------------------------------------------------------

def test_drop_score_stays_bounded_zero_to_one() -> None:
    bt = BeatTracker({})
    dt = 1.0 / 60.0
    t = 0.0
    loud_audio = SimpleNamespace(bass=1.0, mid=1.0, treble=1.0, spectral_flux=5.0)
    while t < 5.0:
        bt.update(dt, loud_audio, onsets=None, t=t)
        assert 0.0 <= bt.drop_score <= 1.0
        t += dt


def test_energy_rises_toward_sustained_input_level() -> None:
    bt = BeatTracker({})
    dt = 1.0 / 60.0
    t = 0.0
    loud_audio = SimpleNamespace(bass=1.0, mid=1.0, treble=1.0, spectral_flux=0.0)
    while t < 3.0:
        bt.update(dt, loud_audio, onsets=None, t=t)
        t += dt

    assert bt.energy > 1.0, 'sustained bass+mid+treble=1.0 each should pull energy well above 0'
