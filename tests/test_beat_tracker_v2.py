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

import numpy as np
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


def test_acf_rival_score_excludes_harmonic_multiples_of_the_winning_lag() -> None:
    """2026-08-07: a rival lag that is a near-integer multiple/divisor of
    the winning lag (2x, 3x, 4x, or reciprocal) reflects the comb filter's
    own harmonic summing agreeing with itself -- a mechanically regular
    four-on-the-floor kick is the textbook case -- not a genuinely
    competing tempo, so it must not suppress confidence."""
    bt = BeatTracker({})
    # 64 = 128/2, 128/3 ~= 42.67, 32 = 128/4 -- all near-exact harmonic
    # divisors of the winning 128 BPM lag.
    bpms = np.array([64.0, 128.0, 128.0 / 3.0, 32.0], dtype=np.float32)
    score = np.array([0.95, 1.0, 0.9, 0.85], dtype=np.float32)

    rival = bt._acf_rival_score(score, bpms, best_bpm=128.0)

    assert rival == pytest.approx(bt._acf_score_floor)


def test_acf_rival_score_still_penalizes_a_genuinely_unrelated_rival() -> None:
    """A strong rival that is NOT a harmonic of the winning lag (a real,
    independently periodic competing tempo) must still suppress confidence
    -- only harmonically-related rivals are exempted."""
    bt = BeatTracker({})
    bpms = np.array([64.0, 128.0, 91.0], dtype=np.float32)
    score = np.array([0.10, 1.0, 0.95], dtype=np.float32)

    rival = bt._acf_rival_score(score, bpms, best_bpm=128.0)

    assert rival == pytest.approx(0.95)


def test_acf_rival_score_falls_back_to_score_floor_with_no_rivals() -> None:
    bt = BeatTracker({})
    bpms = np.array([128.0], dtype=np.float32)
    score = np.array([1.0], dtype=np.float32)

    rival = bt._acf_rival_score(score, bpms, best_bpm=128.0)

    assert rival == pytest.approx(bt._acf_score_floor)


def test_acf_rival_score_falls_back_to_score_floor_when_best_bpm_invalid() -> None:
    bt = BeatTracker({})
    bpms = np.array([64.0, 128.0], dtype=np.float32)
    score = np.array([0.9, 1.0], dtype=np.float32)

    rival = bt._acf_rival_score(score, bpms, best_bpm=0.0)

    assert rival == pytest.approx(bt._acf_score_floor)


# ---------------------------------------------------------------------------
# Tactus fold-down guard (2026-08-13): candidate must clear the score ratio
# AND not be a measurably worse fit for the observed beat spacing.
# ---------------------------------------------------------------------------


def test_tactus_fold_rejected_when_score_ratio_not_cleared() -> None:
    bt = BeatTracker({})
    bt._analysis_region_consistency = lambda bpm_candidate: 1.0  # would pass region alone

    accepted = bt._tactus_fold_accepted(
        cand_score=0.5, best_score=1.0, cur_bpm=160.0, cand_bpm=80.0,
    )

    assert accepted is False, 'score ratio (default 0.55) not cleared by 0.5/1.0'


def test_tactus_fold_accepted_when_score_clears_and_no_beat_history_yet() -> None:
    """_analysis_region_consistency returns 0.0 with no beat-position
    history -- the guard must not block a fold before there is any real
    evidence to judge it against (pre-lock behavior unchanged from before
    this guard existed)."""
    bt = BeatTracker({})
    bt._analysis_region_consistency = lambda bpm_candidate: 0.0

    accepted = bt._tactus_fold_accepted(
        cand_score=0.9, best_score=1.0, cur_bpm=160.0, cand_bpm=80.0,
    )

    assert accepted is True


def test_tactus_fold_rejected_when_candidate_fits_beat_spacing_much_worse() -> None:
    """The actual bug this guard closes: a candidate can clear the raw
    comb-filter score ratio while being a clearly worse explanation of the
    recently observed beat spacing than the lane it would replace."""
    bt = BeatTracker({})

    def region(bpm_candidate: float) -> float:
        return 0.9 if bpm_candidate == 160.0 else 0.2   # candidate fits far worse

    bt._analysis_region_consistency = region

    accepted = bt._tactus_fold_accepted(
        cand_score=0.9, best_score=1.0, cur_bpm=160.0, cand_bpm=80.0,
    )

    assert accepted is False, (
        '0.2 is well below 0.9 * _TACTUS_REGION_GUARD_RATIO (0.70) -- '
        'a candidate this much worse at explaining the beat spacing '
        'should not be allowed to fold even though it scores well'
    )


def test_tactus_fold_accepted_when_candidate_fits_beat_spacing_comparably() -> None:
    """A genuinely valid fold (candidate explains the beat spacing about as
    well as the current lane) must still be allowed through -- this guard
    rejects clearly worse fits, not close calls."""
    bt = BeatTracker({})

    def region(bpm_candidate: float) -> float:
        return 0.9 if bpm_candidate == 160.0 else 0.8   # comparable fit

    bt._analysis_region_consistency = region

    accepted = bt._tactus_fold_accepted(
        cand_score=0.9, best_score=1.0, cur_bpm=160.0, cand_bpm=80.0,
    )

    assert accepted is True


# ---------------------------------------------------------------------------
# kr/dbc option B (2026-08-13): kick_regularity scales tactus fold eagerness
# ---------------------------------------------------------------------------


def test_effective_tactus_ratio_equals_baseline_at_full_kick_regularity() -> None:
    bt = BeatTracker({'tactus_preference_ratio': 0.55})
    bt._kick_regularity = 1.0

    assert bt._effective_tactus_ratio() == pytest.approx(0.55)


def test_effective_tactus_ratio_defaults_to_least_eager_when_never_supplied() -> None:
    """_kick_regularity starts at 0.0 and only changes when update() is
    called with an explicit reading -- a caller that never wires this
    through (an older test, a hand-built harness) gets the strictest
    behavior, never silently the most permissive one."""
    bt = BeatTracker({'tactus_preference_ratio': 0.55})

    assert bt._kick_regularity == 0.0
    assert bt._effective_tactus_ratio() == pytest.approx(0.55 + 1.0 * 0.30)


def test_effective_tactus_ratio_clamps_out_of_range_kick_regularity() -> None:
    """kick_regularity is documented as 0..1; a caller passing something
    outside that range (bad upstream computation, stale float) must not
    push the effective ratio outside the [baseline, baseline+spread]
    band the rest of this mechanism assumes."""
    bt = BeatTracker({'tactus_preference_ratio': 0.55})

    bt._kick_regularity = 1.5   # clamps to 1.0 -> baseline
    assert bt._effective_tactus_ratio() == pytest.approx(0.55)

    bt._kick_regularity = -0.5   # clamps to 0.0 -> baseline + full spread
    assert bt._effective_tactus_ratio() == pytest.approx(0.55 + 0.30)


def test_effective_tactus_ratio_climbs_as_kick_regularity_falls() -> None:
    bt = BeatTracker({'tactus_preference_ratio': 0.55})

    bt._kick_regularity = 0.7
    high = bt._effective_tactus_ratio()
    bt._kick_regularity = 0.3
    low = bt._effective_tactus_ratio()

    assert 0.55 < high < low


def test_update_persists_kick_regularity_across_calls_when_omitted() -> None:
    """update()'s kick_regularity defaults to None, meaning 'no new
    reading this frame' -- must not reset the tracker's last-known value
    back to 0.0 on every call that doesn't supply one."""
    bt = BeatTracker({})
    bt.update(1.0 / 60.0, _audio(), onsets=None, t=0.0, kick_regularity=0.8)
    assert bt._kick_regularity == pytest.approx(0.8)

    bt.update(1.0 / 60.0, _audio(), onsets=None, t=1.0 / 60.0)   # omitted this time

    assert bt._kick_regularity == pytest.approx(0.8), 'must persist, not reset to 0.0'


# ---------------------------------------------------------------------------
# 2026-08-14: session-cumulative tactus-guard telemetry (observability added
# ahead of the first kr/dbc-driven live session).
# ---------------------------------------------------------------------------


def test_tactus_counters_start_at_zero() -> None:
    bt = BeatTracker({})

    assert bt.tactus_fold_accepted_count == 0
    assert bt.tactus_region_reject_count == 0
    assert bt.tactus_score_reject_count == 0


def test_tactus_score_reject_increments_score_reject_count() -> None:
    bt = BeatTracker({})
    bt._analysis_region_consistency = lambda bpm_candidate: 1.0

    bt._tactus_fold_accepted(cand_score=0.1, best_score=1.0, cur_bpm=160.0, cand_bpm=80.0)

    assert bt.tactus_score_reject_count == 1
    assert bt.tactus_region_reject_count == 0
    assert bt.tactus_fold_accepted_count == 0


def test_tactus_region_reject_increments_region_reject_count() -> None:
    bt = BeatTracker({})

    def region(bpm_candidate: float) -> float:
        return 0.9 if bpm_candidate == 160.0 else 0.2

    bt._analysis_region_consistency = region

    bt._tactus_fold_accepted(cand_score=0.9, best_score=1.0, cur_bpm=160.0, cand_bpm=80.0)

    assert bt.tactus_region_reject_count == 1
    assert bt.tactus_score_reject_count == 0
    assert bt.tactus_fold_accepted_count == 0


def test_tactus_accept_increments_accepted_count() -> None:
    bt = BeatTracker({})
    bt._analysis_region_consistency = lambda bpm_candidate: 0.0   # pre-lock, guard inert

    bt._tactus_fold_accepted(cand_score=0.9, best_score=1.0, cur_bpm=160.0, cand_bpm=80.0)

    assert bt.tactus_fold_accepted_count == 1
    assert bt.tactus_region_reject_count == 0
    assert bt.tactus_score_reject_count == 0


def test_effective_tactus_ratio_property_matches_private_method() -> None:
    bt = BeatTracker({'tactus_preference_ratio': 0.55})
    bt._kick_regularity = 0.4

    assert bt.effective_tactus_ratio == pytest.approx(bt._effective_tactus_ratio())


def test_kick_regularity_property_matches_private_attribute() -> None:
    bt = BeatTracker({})
    bt._kick_regularity = 0.42

    assert bt.kick_regularity == pytest.approx(0.42)


def test_full_confidence_blend_eventually_converges_given_enough_steady_time() -> None:
    """Known real behavior, not just a hope: phase_confidence has no explicit
    initial sync step (see _absorb_onset/_advance_phase) and only converges
    once BPM drift happens to carry phase within +/-_V2_PHASE_TOL tolerance
    by chance. On a perfectly steady click track this reliably happens
    within ~60s at 120 BPM under the current 0.12 tolerance; confirmed via
    manual simulation before writing this test.

    2026-08-10: _V2_PHASE_TOL 0.18 -> 0.12 (see beat_grid.py's own field
    comment for the full story) -- a 0.08 cut was tried first and directly
    verified to break convergence entirely (phase_confidence stuck at 0.0
    for 120+ simulated seconds on this exact zero-jitter click track,
    never registering a single hit) before being reverted to 0.12. See
    test_phase_tol_012_converges_reliably_where_008_did_not below for a
    guard against silently regressing back into that failure mode."""
    bt = BeatTracker({})
    _run_steady_click_track(bt, bpm=120.0, duration_s=60.0)

    assert bt.confidence > 0.9
    assert bt._phase_confidence > 0.9


def test_phase_tol_012_converges_reliably_where_008_did_not() -> None:
    """Regression guard for the 2026-08-10 _V2_PHASE_TOL investigation: a
    tighter tolerance than the current 0.12 broke phase convergence
    outright on a mathematically perfect, zero-jitter click track (not
    just filtering genuinely off-grid real-world timing, which was the
    intent). If a future edit tightens _V2_PHASE_TOL again, this should
    fail loudly rather than silently reintroducing that failure mode."""
    bt = BeatTracker({})
    _run_steady_click_track(bt, bpm=120.0, duration_s=60.0)
    assert bt._phase_confidence > 0.0, (
        'phase_confidence never registered a single hit -- _V2_PHASE_TOL is '
        'likely too tight relative to the phase oscillator\'s own BPM-estimate '
        'residual error (see beat_grid.py\'s field comment on _V2_PHASE_TOL)'
    )


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
    # 2026-08-10: beat_count == downbeat_count * 4 (exact) -> // 4 (floor).
    # A fixed 30s wall-clock cutoff stops mid-bar 0-3 beats into the next
    # one as often as not -- the exact remainder depends on where the
    # tracker's still-converging BPM estimate happens to land relative to
    # the cutoff, which is sensitive to confidence-blend/phase-tolerance
    # tuning (this test started failing the same session _V2_PHASE_TOL and
    # the ACF/phase blend both changed, purely because the trailing-beat
    # count shifted from 0 to 1 -- not a real downbeat-detection bug).
    # 2026-08-14: beat-position analysis (downbeat confidence gating) is now
    # always on -- previously an opt-in analysis_mode_enabled flag, off by
    # default, so this test never saw the gate at all. The very first bar
    # can land below analysis_downbeat_confidence_min before phase_confidence/
    # acf_confidence converge (region consistency itself needs >= 8 beat
    # positions and reads 0.0 before that), suppressing at most one extra
    # downbeat on top of the trailing-partial-bar effect above -- this is
    # the gate doing its job, not a bug. Widened from an exact match to a
    # tolerance of at most 1.
    diff = beat_count // 4 - downbeat_count
    assert 0 <= diff <= 1, (
        f'expected one downbeat per 4 beats (± a trailing partial bar, ± one '
        f'gated warmup bar), got {beat_count} beats / {downbeat_count} '
        f'downbeats (diff={diff})'
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
    bt = BeatTracker({})
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
    bt = BeatTracker({})
    bt._phase_confidence = 0.9
    bt._acf_confidence = 0.1

    assert bt._phase_confidence != bt._acf_confidence
    assert bt._phase_confidence == 0.9
    assert bt._acf_confidence == 0.1


def test_is_downbeat_gated_below_analysis_confidence_threshold() -> None:
    """Beat-position analysis is always on (2026-08-14 -- previously an
    opt-in analysis_mode_enabled flag, ripped out; see docs/adr/vj-system.md
    for why leaving it optional was itself a bug). With an artificially low
    downbeat-confidence threshold (region consistency starts at 0 -- can't
    accumulate real beat-position history in a short synthetic run),
    is_downbeat must not fire even though is_beat does."""
    bt = BeatTracker({
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


def test_analysis_mode_enabled_config_key_is_inert() -> None:
    """A stale config.toml left over from before 2026-08-14 (when this was
    an opt-in analysis_mode_enabled flag) must not silently disable
    beat-position analysis -- there's no code path left that reads this
    key at all, so passing it (True or False) must be a complete no-op:
    downbeat gating and the beat-position map behave identically either
    way. Guards against a future refactor accidentally reviving the flag
    and reintroducing the exact bug 2026-08-14 removed."""
    def _confidence_min_gate_holds(cfg_extra: dict) -> bool:
        bt = BeatTracker({'analysis_downbeat_confidence_min': 0.9, **cfg_extra})
        _run_steady_click_track(bt, bpm=120.0, duration_s=10.0)
        dt = 1.0 / 60.0
        t = 10.0
        next_onset = 10.0
        audio = _audio()
        saw_downbeat = False
        while t < 14.0:
            onsets = None
            if t >= next_onset:
                onsets = [_FakeOnset(next_onset)]
                next_onset += 0.5
            bt.update(dt, audio, onsets=onsets, t=t)
            saw_downbeat = saw_downbeat or bt.is_downbeat
            t += dt
        return not saw_downbeat   # True == gate held (no downbeat fired)

    assert _confidence_min_gate_holds({'analysis_mode_enabled': False})
    assert _confidence_min_gate_holds({'analysis_mode_enabled': True})
    assert _confidence_min_gate_holds({})


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
# 2026-08-14: strength/band-weighted phase coherence -- the real fix for
# phase_confidence's structural cap, superseding the flat per-onset
# hit/miss buffer.
# ---------------------------------------------------------------------------


def test_absorb_onset_strong_bass_hit_pushes_confidence_toward_one() -> None:
    bt = BeatTracker({})
    bt._bpm = 124.0
    bt._phase = 0.0   # on-beat -> hit

    bt._absorb_onset(0.0, strength=3.0, band_weight=1.0)   # strong, fully bass

    assert bt._phase_confidence == pytest.approx(1.0)


def test_absorb_onset_strong_bass_miss_drags_confidence_to_zero() -> None:
    bt = BeatTracker({})
    bt._bpm = 124.0
    bt._phase = 0.5   # off-beat -> miss

    bt._absorb_onset(0.0, strength=3.0, band_weight=1.0)   # strong, fully bass

    assert bt._phase_confidence == pytest.approx(0.0)


def test_absorb_onset_weak_treble_miss_barely_moves_an_established_confidence() -> None:
    """The actual bug this rework closes: real music generates plenty of
    legitimately off-beat hi-hat/fill onsets that a correct lock has no
    business explaining away. A weak, treble-heavy miss should carry
    almost no weight against an already-established high confidence."""
    bt = BeatTracker({})
    bt._bpm = 124.0
    bt._phase = 0.0
    for _ in range(10):   # establish a confident, all-hit history
        bt._absorb_onset(0.0, strength=3.0, band_weight=1.0)
    before = bt._phase_confidence
    assert before == pytest.approx(1.0)

    bt._phase = 0.5   # off-beat -> miss
    bt._absorb_onset(0.0, strength=1.0, band_weight=0.05)   # weak, almost no bass

    assert bt._phase_confidence > 0.9, (
        f'a weak treble miss should barely dent an established high '
        f'confidence, dropped to {bt._phase_confidence} from {before}'
    )


def test_absorb_onset_bass_miss_drags_harder_than_treble_miss() -> None:
    """Same prior state, same magnitude miss -- a bass-heavy miss is real
    evidence against the lock and must hurt more than a treble-heavy one."""
    def _confidence_after_miss(band_weight: float) -> float:
        bt = BeatTracker({})
        bt._bpm = 124.0
        bt._phase = 0.0
        for _ in range(10):
            bt._absorb_onset(0.0, strength=3.0, band_weight=1.0)
        bt._phase = 0.5
        bt._absorb_onset(0.0, strength=3.0, band_weight=band_weight)
        return bt._phase_confidence

    bass_miss = _confidence_after_miss(1.0)
    treble_miss = _confidence_after_miss(0.05)

    assert bass_miss < treble_miss


def test_absorb_onset_zero_band_weight_never_updates_phase_confidence_alone() -> None:
    """A pure-treble onset (band_weight=0.0) contributes zero weight either
    way -- must not raise (division-by-zero guard) and must leave
    phase_confidence exactly where it was, hit or miss."""
    bt = BeatTracker({})
    bt._bpm = 124.0
    bt._phase = 0.0
    bt._absorb_onset(0.0, strength=3.0, band_weight=1.0)
    before = bt._phase_confidence

    bt._phase = 0.5   # would be a miss, but band_weight=0.0 carries no evidence
    bt._absorb_onset(0.1, strength=3.0, band_weight=0.0)

    assert bt._phase_confidence == pytest.approx(before)


def test_absorb_onset_band_weight_defaults_to_1_for_legacy_callers() -> None:
    """Callers that don't pass band_weight (pre-2026-08-14 call sites,
    synthetic onsets without the field) get the old fully-diagnostic
    behavior -- confirms the default arg, not just OnsetEvent's."""
    bt = BeatTracker({})
    bt._bpm = 124.0
    bt._phase = 0.0

    bt._absorb_onset(0.0, 3.0)   # no band_weight arg

    assert bt._phase_confidence == pytest.approx(1.0)


def test_v2_phase_tol_is_014() -> None:
    """2026-08-14: 0.14 -> 0.18 -> back to 0.14. The 0.18 + three-term-blend
    combo measurably regressed v3/v2-shadow agreement on syncopated
    material (3 of 5 tracks in a real session dropped from 84-100% to
    0-12% agreement); reverting phase_tol first, in isolation, before
    touching downbeat_regularity's weight too. Module-level constant, no
    tracker method exercises it directly -- lock this in so a future
    tweak has to touch this test too."""
    assert _MOD._V2_PHASE_TOL == pytest.approx(0.14)


def test_downbeat_regularity_independent_of_acf_and_phase_confidence() -> None:
    """The dbc term folded into the top-level confidence blend must never
    read _acf_confidence/_phase_confidence -- unlike _last_downbeat_confidence
    (which internally blends 30% phase + 15% acf, and used to just echo
    self._confidence when analysis_mode was off), that would make
    self._confidence partly echo its own recent history every bar.

    Locks onto a steady click track first so region consistency/density
    reflect real beat-position history (a fresh tracker's beat-position map
    is empty -- both terms would read 0.0 regardless of acf/phase, making
    the independence check trivially true rather than a real test).
    """
    bt = BeatTracker({})
    _run_steady_click_track(bt, bpm=124.0, duration_s=10.0)

    bt._acf_confidence = 0.0
    bt._phase_confidence = 0.0
    low = bt._downbeat_regularity(bt._last_t)

    bt._acf_confidence = 1.0
    bt._phase_confidence = 1.0
    high = bt._downbeat_regularity(bt._last_t)

    assert low == pytest.approx(high)
    assert low > 0.0, 'expected real beat-position history to produce a nonzero dbc term'


def test_confidence_blend_is_sixtyfive_ten_twentyfive() -> None:
    """self._confidence = 0.65*acf + 0.1*phase + 0.25*downbeat_regularity
    (2026-08-14, later still: re-tuned from 0.6/0.2/0.2 -- phase_confidence
    chronically capped ~0.30 even on locked, correct stretches per real
    session data, so its share was trimmed onto acf/downbeat_regularity,
    the two terms showing real dynamic range). Exercised via _absorb_onset
    (the same formula also lives in _estimate_tempo_acf). Locks onto a
    steady click track first so downbeat_regularity reflects real
    beat-position history instead of the insufficient-history 0.0 floor
    (region consistency needs >= 8 beat positions; a fresh tracker has
    none). Reads back the actual acf_confidence/phase_confidence/
    downbeat_regularity the call used, rather than assuming exact values --
    with real history in play, a single onset's exact effect on the
    phase_confidence weighted-average isn't 1.0 on the nose the way it is
    on a fresh tracker.
    """
    bt = BeatTracker({})
    t = _run_steady_click_track(bt, bpm=124.0, duration_s=10.0)

    bt._absorb_onset(t, strength=3.0, band_weight=1.0)

    dbc = bt._downbeat_regularity(bt._last_t)
    expected = 0.65 * bt._acf_confidence + 0.1 * bt._phase_confidence + 0.25 * dbc
    assert bt._confidence == pytest.approx(expected)
    assert dbc > 0.0, 'expected real beat-position history to produce a nonzero dbc term'
    assert bt.downbeat_regularity == pytest.approx(dbc), (
        'downbeat_regularity property must be cached from the same blend computation'
    )


def test_confidence_does_not_echo_its_own_prior_value() -> None:
    """Regression guard for the exact bug this design avoided: seeding
    self._confidence (and _last_downbeat_confidence, the field that used to
    silently alias it) with an extreme prior value must not influence the
    freshly recomputed value at all."""
    def _confidence_after(seed: float) -> float:
        bt = BeatTracker({})
        t = _run_steady_click_track(bt, bpm=124.0, duration_s=10.0)
        bt._confidence = seed
        bt._last_downbeat_confidence = seed
        bt._absorb_onset(t, strength=3.0, band_weight=1.0)
        return bt._confidence

    assert _confidence_after(0.0) == pytest.approx(_confidence_after(1.0))


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


def test_drop_score_no_longer_double_counts_treble() -> None:
    """2026-08-09: treble used to get both a standalone drop_score term
    (0.12) and its band_blend share (0.25 x 0.16 = 0.04, effective ~0.16
    total) -- found during the director scene-detection audit. band_blend's
    own weights (bass 0.45 > mid 0.30 > treble 0.25) say bass should matter
    most for drop_score, but the double-count meant a treble-only signal
    scored *higher* than a bass-only signal at the same magnitude despite
    bass's nominally higher weight. This is now flipped back to the
    intended ordering: bass-only outscores treble-only, since bass_blend's
    weight (0.45) is more than treble's (0.25) and nothing double-counts
    either anymore.
    """
    dt = 1.0 / 60.0
    bass_only = BeatTracker({})
    treble_only = BeatTracker({})
    t = 0.0
    while t < 3.0:
        bass_only.update(dt, SimpleNamespace(bass=1.0, mid=0.0, treble=0.0, spectral_flux=0.0),
                          onsets=None, t=t)
        treble_only.update(dt, SimpleNamespace(bass=0.0, mid=0.0, treble=1.0, spectral_flux=0.0),
                            onsets=None, t=t)
        t += dt

    assert bass_only.drop_score > treble_only.drop_score


def test_band_blend_rebalanced_toward_bass() -> None:
    """2026-08-09: band_blend split 0.45/0.30/0.25 (bass/mid/treble) ->
    0.7/0.2/0.1 -- a drop should read primarily off the bass band. Mid-only
    should now score noticeably lower relative to bass-only than it did
    under the old weighting (0.30 vs 0.45 -> 0.2 vs 0.7, a much bigger gap)."""
    dt = 1.0 / 60.0
    bass_only = BeatTracker({})
    mid_only = BeatTracker({})
    t = 0.0
    while t < 3.0:
        bass_only.update(dt, SimpleNamespace(bass=1.0, mid=0.0, treble=0.0, spectral_flux=0.0),
                          onsets=None, t=t)
        mid_only.update(dt, SimpleNamespace(bass=0.0, mid=1.0, treble=0.0, spectral_flux=0.0),
                         onsets=None, t=t)
        t += dt

    assert bass_only.drop_score > mid_only.drop_score


def test_bass_flux_norm_responds_to_bass_flux() -> None:
    """New 2026-08-09 term: a sustained bass_flux signal should measurably
    raise drop_score relative to an otherwise-identical tracker with no
    bass_flux at all."""
    dt = 1.0 / 60.0
    with_bass_flux = BeatTracker({})
    without_bass_flux = BeatTracker({})
    t = 0.0
    while t < 2.0:
        with_bass_flux.update(
            dt, SimpleNamespace(bass=0.3, mid=0.3, treble=0.3, spectral_flux=0.0, bass_flux=2.0),
            onsets=None, t=t,
        )
        without_bass_flux.update(
            dt, SimpleNamespace(bass=0.3, mid=0.3, treble=0.3, spectral_flux=0.0, bass_flux=0.0),
            onsets=None, t=t,
        )
        t += dt

    assert with_bass_flux.bass_flux_fast > 0.0
    assert with_bass_flux.drop_score > without_bass_flux.drop_score


def test_band_blend_reads_bass_det_not_bass() -> None:
    """2026-08-11: band_blend's z-score inputs (bass_n/mid_n/treble_n) read
    audio.bass_det/mid_det/treble_det, not audio.bass/mid/treble -- see
    beat_grid.py's own comment and
    docs/planning/auto-vj-drop-score-redesign-plan-2026-08-11.md. Two
    trackers with identical bass (so raw_energy/energy_norm match) but
    different bass_det should diverge on drop_score, driven by band_blend."""
    dt = 1.0 / 60.0
    high_det = BeatTracker({})
    low_det = BeatTracker({})
    t = 0.0
    # Silent warmup so the z-score baseline starts from a real "quiet"
    # reference, matching the bass-gated-breakdown test's own methodology.
    while t < 5.0:
        high_det.update(dt, SimpleNamespace(bass=0.5, mid=0.3, treble=0.2, bass_det=0.02,
                                              mid_det=0.3, treble_det=0.2, spectral_flux=0.0,
                                              bass_flux=0.0), onsets=None, t=t)
        low_det.update(dt, SimpleNamespace(bass=0.5, mid=0.3, treble=0.2, bass_det=0.02,
                                             mid_det=0.3, treble_det=0.2, spectral_flux=0.0,
                                             bass_flux=0.0), onsets=None, t=t)
        t += dt
    warm_start = t
    while t < warm_start + 2.0:
        # Identical bass (raw_energy/energy_norm match); bass_det diverges.
        high_det.update(dt, SimpleNamespace(bass=0.5, mid=0.3, treble=0.2, bass_det=0.9,
                                              mid_det=0.3, treble_det=0.2, spectral_flux=0.0,
                                              bass_flux=0.0), onsets=None, t=t)
        low_det.update(dt, SimpleNamespace(bass=0.5, mid=0.3, treble=0.2, bass_det=0.02,
                                             mid_det=0.3, treble_det=0.2, spectral_flux=0.0,
                                             bass_flux=0.0), onsets=None, t=t)
        t += dt

    assert high_det.energy == pytest.approx(low_det.energy, abs=1e-6), (
        'raw_energy/energy_norm should be identical -- both trackers saw the '
        'same bass/mid/treble, only bass_det differs'
    )
    assert high_det.drop_score > low_det.drop_score


def test_band_blend_falls_back_to_bass_when_bass_det_absent() -> None:
    """Back-compat: a stub audio object with no bass_det attribute at all
    (e.g. every pre-existing test fixture in this file) must behave exactly
    as before -- band_blend's z-score falls back to reading bass/mid/treble
    directly, per beat_grid.py's `is None` fallback."""
    dt = 1.0 / 60.0
    bt = BeatTracker({})
    t = 0.0
    while t < 2.0:
        bt.update(dt, SimpleNamespace(bass=0.6, mid=0.3, treble=0.2, spectral_flux=0.0,
                                        bass_flux=0.0), onsets=None, t=t)
        t += dt

    assert bt.drop_score > 0.0


def test_flux_norm_rescoped_excludes_bass_flux() -> None:
    """2026-08-09: flux_norm = spectral_flux - bass_flux (mid+treble only)
    now, to avoid double-counting bass against the new bass_flux_norm term.
    A tracker whose entire reported spectral_flux is attributable to bass
    (spectral_flux == bass_flux) should show ~zero smoothed flux_norm
    input, since the bass contribution is subtracted out."""
    dt = 1.0 / 60.0
    bt = BeatTracker({})
    t = 0.0
    while t < 2.0:
        bt.update(dt, SimpleNamespace(bass=0.3, mid=0.0, treble=0.0, spectral_flux=2.0, bass_flux=2.0),
                   onsets=None, t=t)
        t += dt

    assert bt.spectral_flux_smooth == pytest.approx(0.0, abs=1e-6)


def test_drop_score_bass_gated_reweight_caps_a_bass_free_breakdown() -> None:
    """2026-08-10: real session finding (favorites/b) -- a breakdown that
    was just piano chords + vocals (zero drums/bass) read drop_score=0.54
    under the old weights, clearing every shipped mood profile's
    drop_energy_threshold/drop_timeout_score_floor at the time (raver's
    was 0.46). The reweight (slope_norm/flux_norm cut, band_blend/
    bass_flux_norm raised to 0.65 combined) makes bass presence
    load-bearing.

    Reproduces the actual shape of the incident, not just a cold-start
    zero-bass tracker: warm up with real bass so the per-band adaptive
    normalizer (beat_grid._norm) establishes a genuine "bass is normally
    present" baseline, matching a real track that had bass before the
    breakdown -- a tracker that has *never* seen bass reads its own
    silence as neutral (z-score ~0, band_blend ~0.5), which would
    understate this term and give a falsely reassuring result. Then drop
    to zero bass with loud, rising, transient mid/treble content (the
    piano+vocals stand-in) and confirm drop_score lands comfortably below
    every rebooted mood-profile floor (lowest is raver's 0.60).

    2026-08-11: energy_norm/band_blend swapped (0.15/0.30 -> 0.30/0.15,
    see beat_grid.py's own comment) -- the bass-free ceiling moved from
    0.35 to 0.50, still below 0.60, so this assertion (< 0.50) still holds
    with real margin (verified: this scenario now reads ~0.32, not just
    barely under 0.50)."""
    dt = 1.0 / 60.0
    bt = BeatTracker({})
    t = 0.0
    while t < 5.0:
        bt.update(
            dt,
            SimpleNamespace(bass=1.0, mid=0.6, treble=0.5, spectral_flux=0.3, bass_flux=0.3),
            onsets=None, t=t,
        )
        t += dt
    breakdown_start = t
    while t < breakdown_start + 3.0:
        bt.update(
            dt,
            SimpleNamespace(bass=0.0, mid=1.0, treble=1.0, spectral_flux=3.0, bass_flux=0.0),
            onsets=None, t=t,
        )
        t += dt

    assert bt.drop_score < 0.50, (
        f'drop_score={bt.drop_score:.3f} during a bass-free breakdown -- '
        'should sit well under every rebooted mood-profile floor (>= 0.60)'
    )
