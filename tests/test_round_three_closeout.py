"""Regression tests for the round-three close-out batch (2026-08-17).

Covers detector `1.0.0-rc.33` / auto-vj `1.0.0-rc.90`'s new mechanisms
(see `docs/adr/vj-system.md` "Round Three Close-Out Batch" and
`docs/planning/auto-vj-round-three-planning-2026-08-14.md`'s close-out
section): relative persistence spread limits, T5 Option A +
snap-on-accepted-jump, the minimum lock dwell gate, the cold-start
confidence-blend guard, genre-fit-weighted candidate scoring, the
tap-tempo trust window, the envelope pulse-strength clamp, the
time-bounded energy history, `candidate_lock_disagreement` (the
refractory guard's detector half), the controller-side mood-prime /
tap-confirm entry points, and the `bpm_agreement_report` tool.
"""
from __future__ import annotations

import importlib.util
import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[1]
_BEAT_GRID_PATH = _REPO / 'drop-ins' / 'auto-vj-01' / 'beat_grid.py'
_AUTO_VJ_PATH = _REPO / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_AGREEMENT_TOOL_PATH = _REPO / 'drop-ins' / 'auto-vj-01' / 'tools' / 'bpm_agreement_report.py'


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_BEAT_GRID = _load_module(_BEAT_GRID_PATH, 'test_round3_beat_grid')
_AUTO_VJ = _load_module(_AUTO_VJ_PATH, 'test_round3_auto_vj')
_TOOL = _load_module(_AGREEMENT_TOOL_PATH, 'test_round3_agreement_tool')

BeatTracker = _BEAT_GRID.BeatTracker
BeatGridTracker = _BEAT_GRID.BeatGridTracker


class _FakeOnset:
    def __init__(self, t: float, strength: float = 1.0) -> None:
        self.t = t
        self.strength = strength


def _run_clicks(tracker, *, bpm: float, duration_s: float, start_t: float = 0.0,
                fps: float = 60.0, jitter_s: float = 0.0, seed: int = 1,
                bass: float = 0.8) -> float:
    """Minimal click-track harness (same shape as test_beat_tracker_v2's)."""
    rng = random.Random(seed) if jitter_s else None
    period = 60.0 / bpm
    dt = 1.0 / fps
    audio = SimpleNamespace(bass=bass, mid=0.3, treble=0.2, spectral_flux=0.0,
                            bass_flux=0.0, beat=0.0)
    t = start_t
    next_onset = start_t
    end = start_t + duration_s
    while t < end:
        onsets = []
        while next_onset <= t:
            jt = next_onset + (rng.uniform(-jitter_s, jitter_s) if rng else 0.0)
            onsets.append(_FakeOnset(jt, 3.0))
            next_onset += period
        tracker.update(dt, audio, onsets=onsets, t=t, kick_regularity=1.0)
        t += dt
    return t


# --------------------------------------------------------------------------
# Relative persistence spread limits
# --------------------------------------------------------------------------

def test_persistence_spread_limit_is_flat_floor_at_low_tempo() -> None:
    bt = BeatTracker({})
    assert bt._persistence_spread_bpm == pytest.approx(6.0)
    assert bt._persistence_spread_pct == pytest.approx(0.035)
    # max(6.0, 0.035 * 120) = 6.0 -- flat floor binds below the crossover.
    assert max(bt._persistence_spread_bpm,
               bt._persistence_spread_pct * 120.0) == pytest.approx(6.0)


def test_persistence_spread_limit_loosens_at_fast_tempo() -> None:
    bt = BeatTracker({})
    # max(6.0, 0.035 * 175) = 6.125 -- the pct term binds in the fast lane.
    assert max(bt._persistence_spread_bpm,
               bt._persistence_spread_pct * 175.0) == pytest.approx(6.125)


def test_spread_pct_config_overrides_reach_the_instance() -> None:
    bt = BeatTracker({'persistence_spread_pct': 0.05, 'candidate_spread_pct': 0.0})
    assert bt._persistence_spread_pct == pytest.approx(0.05)
    assert bt._candidate_spread_pct == pytest.approx(0.0)


# --------------------------------------------------------------------------
# T5 Option A + snap on accepted large jump
# --------------------------------------------------------------------------

def test_accepted_large_jump_snaps_resets_deques_and_anchors() -> None:
    bt = BeatTracker({})
    _run_clicks(bt, bpm=83.0, duration_s=60.0)
    assert bt.bpm == pytest.approx(83.0, abs=2.0)
    _run_clicks(bt, bpm=123.0, duration_s=20.0, start_t=60.0, jitter_s=0.01)
    # Converged (snap, not a 5-BPM/cycle crawl), with at least one
    # Option A reset recorded, and the anchor moved to the new lane.
    assert bt.bpm == pytest.approx(123.0, abs=3.0)
    assert bt.persistence_reset_count >= 1
    assert bt._lock_anchor_bpm == pytest.approx(bt.bpm, abs=5.0)


def test_option_a_reset_only_removes_evidence_never_counters() -> None:
    bt = BeatTracker({})
    _run_clicks(bt, bpm=83.0, duration_s=60.0)
    rejects_before = bt._large_jump_persistence_reject_count
    _run_clicks(bt, bpm=123.0, duration_s=20.0, start_t=60.0, jitter_s=0.01)
    # Cumulative counters are monotonically non-decreasing across the reset.
    assert bt._large_jump_persistence_reject_count >= rejects_before
    assert bt._large_jump_persistence_cleared_count >= 1


# --------------------------------------------------------------------------
# Minimum lock dwell
# --------------------------------------------------------------------------

def test_dwell_gate_escalates_in_band_drift_from_anchor() -> None:
    # Tight dwell budget (1%) so a small, genuinely in-band tempo shift
    # (124 -> 121, always |Δ| < 4 from the current estimate, so the
    # large-jump path never engages on its own) exceeds the cumulative
    # anchor budget and must be escalated. The escalated candidate is
    # allowed to pass the large-jump gates and be accepted -- the gate's
    # contract is scrutiny, not blocking -- the counter records that the
    # scrutiny happened.
    bt = BeatTracker({'bpm_lock_dwell_drift_pct': 0.01})
    _run_clicks(bt, bpm=124.0, duration_s=40.0)
    assert bt.bpm == pytest.approx(124.0, abs=2.5)
    bt._lock_anchor_bpm = bt.bpm
    bt._bars_since_lock = 0
    before = bt.dwell_gated_count
    _run_clicks(bt, bpm=121.0, duration_s=8.0, start_t=40.0)
    assert bt.dwell_gated_count > before


def test_dwell_gate_inactive_after_window_elapses() -> None:
    bt = BeatTracker({'bpm_lock_dwell_drift_pct': 0.01})
    _run_clicks(bt, bpm=124.0, duration_s=40.0)
    bt._lock_anchor_bpm = bt.bpm
    bt._bars_since_lock = 99  # window long elapsed
    before = bt.dwell_gated_count
    _run_clicks(bt, bpm=121.0, duration_s=8.0, start_t=40.0)
    assert bt.dwell_gated_count == before


def test_dwell_zero_bars_disables_the_gate() -> None:
    bt = BeatTracker({'bpm_lock_dwell_bars': 0.0})
    assert bt._dwell_bars == 0.0


# --------------------------------------------------------------------------
# Cold-start confidence-blend guard
# --------------------------------------------------------------------------

def test_cold_start_guard_engages_then_expires() -> None:
    bt = BeatTracker({})
    assert bt.cold_start_guard_active is False
    _run_clicks(bt, bpm=120.0, duration_s=4.0)
    assert bt.bpm > 0.0, 'test premise: a lock formed'
    # 25 ACF cycles at ~7.5 Hz is ~3.3s; well within 30s the guard is over.
    _run_clicks(bt, bpm=120.0, duration_s=30.0, start_t=4.0)
    assert bt.cold_start_guard_active is False


def test_cold_start_guard_is_active_immediately_after_lock() -> None:
    bt = BeatTracker({})
    # Stop almost immediately after the first possible lock.
    t = 0.0
    while bt.bpm <= 0.0 and t < 20.0:
        t = _run_clicks(bt, bpm=120.0, duration_s=0.5, start_t=t)
    assert bt.bpm > 0.0, 'test premise: a lock formed within 20s'
    assert bt.cold_start_guard_active is True


# --------------------------------------------------------------------------
# Genre-fit-weighted candidate scoring
# --------------------------------------------------------------------------

def test_genre_evidence_stores_expires_and_clears() -> None:
    bt = BeatTracker({})
    _run_clicks(bt, bpm=120.0, duration_s=2.0)
    bt.set_genre_tempo_evidence(128.0, 0.1, 0.8)
    assert bt.genre_evidence_weight == pytest.approx(0.8)
    # Sigma floored so a tight profile can't spike one lane.
    assert bt._genre_evidence_sigma >= 0.25
    bt.set_genre_tempo_evidence(0.0, 0.1, 0.0)   # weight<=0 clears
    assert bt.genre_evidence_weight == 0.0
    bt.set_genre_tempo_evidence(128.0, 0.3, 0.5)
    # Expires after the staleness window with no refresh.
    _run_clicks(bt, bpm=120.0, duration_s=25.0, start_t=2.0)
    assert bt.genre_evidence_weight == 0.0


def test_genre_evidence_applies_only_below_the_confidence_gate() -> None:
    # Gate forced impossibly high -> always consult (engagement counter moves).
    bt = BeatTracker({'genre_candidate_gate_confidence': 2.0})
    _run_clicks(bt, bpm=120.0, duration_s=2.0)
    bt.set_genre_tempo_evidence(120.0, 0.3, 1.0)
    _run_clicks(bt, bpm=120.0, duration_s=5.0, start_t=2.0)
    assert bt.genre_evidence_applied_count > 0

    # Gate at 0 -> never consult (acf_conf is never below 0).
    bt2 = BeatTracker({'genre_candidate_gate_confidence': 0.0})
    _run_clicks(bt2, bpm=120.0, duration_s=2.0)
    bt2.set_genre_tempo_evidence(120.0, 0.3, 1.0)
    _run_clicks(bt2, bpm=120.0, duration_s=5.0, start_t=2.0)
    assert bt2.genre_evidence_applied_count == 0


def test_genre_evidence_disabled_by_config() -> None:
    bt = BeatTracker({'genre_candidate_scoring_enabled': False,
                      'genre_candidate_gate_confidence': 2.0})
    _run_clicks(bt, bpm=120.0, duration_s=2.0)
    bt.set_genre_tempo_evidence(120.0, 0.3, 1.0)
    _run_clicks(bt, bpm=120.0, duration_s=5.0, start_t=2.0)
    assert bt.genre_evidence_applied_count == 0


# --------------------------------------------------------------------------
# Tap-tempo trust window
# --------------------------------------------------------------------------

def test_tap_prime_rejects_implausible_values() -> None:
    bt = BeatTracker({})
    assert bt.tap_prime(20.0) is False
    assert bt.tap_prime(500.0) is False
    assert bt.tap_prime_active is False


def test_tap_prime_opens_window_and_restores_prior_on_expiry() -> None:
    bt = BeatTracker({})
    _run_clicks(bt, bpm=120.0, duration_s=2.0)
    saved_mu, saved_sigma = bt._prior_mu, bt._prior_sigma
    assert bt.tap_prime(140.0) is True
    assert bt.tap_prime_active is True
    assert bt._prior_mu == pytest.approx(140.0)
    assert bt._prior_sigma == pytest.approx(0.10)
    # Ride out the 30s window; the saved prior must come back exactly.
    _run_clicks(bt, bpm=120.0, duration_s=35.0, start_t=2.0)
    assert bt.tap_prime_active is False
    assert bt._prior_mu == pytest.approx(saved_mu)
    assert bt._prior_sigma == pytest.approx(saved_sigma)


def test_tap_fast_path_relocks_a_wrong_lock_quickly() -> None:
    bt = BeatTracker({})
    _run_clicks(bt, bpm=83.0, duration_s=60.0)
    assert bt.bpm == pytest.approx(83.0, abs=2.0)
    # Operator taps the real tempo; the audio has actually been ~123 all
    # along (wrong-lock scenario). Feed 123 clicks inside the window.
    assert bt.tap_prime(123.0) is True
    _run_clicks(bt, bpm=123.0, duration_s=12.0, start_t=60.0, jitter_s=0.01)
    # Within the 30s window the fast path must have re-locked into the
    # tap's ±6% band (the mixed 8s ACF envelope drags the exact reading
    # slightly low right after the boundary; the band is the contract).
    assert bt.tap_prime_accept_count >= 1
    assert abs(bt.bpm - 123.0) <= 0.06 * 123.0 + 0.5


def test_silence_reset_ends_tap_window_and_restores_prior() -> None:
    bt = BeatTracker({})
    _run_clicks(bt, bpm=120.0, duration_s=2.0)
    saved_mu = bt._prior_mu
    bt.tap_prime(140.0)
    bt._reset_tempo_lock()
    assert bt.tap_prime_active is False
    assert bt._prior_mu == pytest.approx(saved_mu)


# --------------------------------------------------------------------------
# Pulse-strength clamp / phase-error distribution / energy history
# --------------------------------------------------------------------------

def test_pulse_strength_is_log_compressed() -> None:
    import numpy as np
    bt = BeatTracker({})
    bt._advance_envelope(0.0)
    bt._pulse_envelope(100.0)
    written = float(np.max(bt._env_buf))
    assert written == pytest.approx(1.0 + np.log1p(99.0), abs=1e-6)
    assert written < 7.0   # a freak transient can no longer dominate the window


def test_phase_error_distribution_populates() -> None:
    bt = BeatTracker({})
    _run_clicks(bt, bpm=120.0, duration_s=20.0)
    # The distribution must populate with bounded signed values. (No
    # near-zero-median assertion on purpose: with interpolation making
    # the BPM estimate accurate, residual phase drift is so slow that
    # capture into the nudge window can legitimately take longer than
    # this fixture runs -- which is exactly the kind of mechanical story
    # this logging exists to expose on real sessions.)
    assert len(bt._phase_err_buf) >= 4
    assert -0.5 <= bt.phase_error_median <= 0.5
    assert 0.0 <= bt.phase_error_iqr <= 1.0


def test_energy_history_is_time_bounded_not_frame_bounded() -> None:
    # 240 fps for 10 s: under the old 240-frame deque this held only 1 s of
    # history and the >=2 s slope reference could never resolve.
    bt = BeatTracker({})
    audio = SimpleNamespace(bass=0.8, mid=0.3, treble=0.2, spectral_flux=0.0,
                            bass_flux=0.0, beat=0.0)
    t = 0.0
    for _ in range(2400):
        bt.update(1.0 / 240.0, audio, onsets=[], t=t)
        t += 1.0 / 240.0
    oldest_age = t - bt._energy_history[0][0]
    assert oldest_age >= 2.0, 'slope reference must be able to resolve'
    assert oldest_age <= 4.5, 'window must stay ~4s, not grow unbounded'


def test_v1_energy_history_also_time_bounded() -> None:
    bt = BeatGridTracker({})
    audio = SimpleNamespace(bass=0.8, mid=0.3, treble=0.2, beat=0.0)
    t = 0.0
    for _ in range(2400):
        bt.update(1.0 / 240.0, audio, t=t)
        t += 1.0 / 240.0
    oldest_age = t - bt._energy_history[0][0]
    assert 2.0 <= oldest_age <= 4.5


# --------------------------------------------------------------------------
# candidate_lock_disagreement (refractory guard's detector half)
# --------------------------------------------------------------------------

def test_candidate_lock_disagreement_requires_fresh_out_of_band_median() -> None:
    bt = BeatTracker({})
    _run_clicks(bt, bpm=120.0, duration_s=10.0)
    assert bt.candidate_lock_disagreement is False
    # Fresh, far-off median -> disagreement.
    bt._long_candidate_median = 80.0
    bt._long_candidate_eval_t = bt._last_t
    assert bt.candidate_lock_disagreement is True
    # Stale evidence must not read as live disagreement.
    bt._long_candidate_eval_t = bt._last_t - 60.0
    assert bt.candidate_lock_disagreement is False


def test_candidate_lock_disagreement_uses_its_own_wider_band_not_the_jump_gate_band() -> None:
    """2026-08-17, later still: real session data showed the guard firing
    ~9-11 times/sec against the jump-gate's tight band (0.03/4.0) -- split
    into its own, wider default (0.16/10.0) so routine candidate noise
    inside the OLD tight band no longer reads as disagreement, while a
    genuinely large split still does."""
    bt = BeatTracker({})
    _run_clicks(bt, bpm=120.0, duration_s=10.0)
    assert bt._refractory_guard_band_pct == pytest.approx(0.16)
    assert bt._refractory_guard_band_min == pytest.approx(10.0)
    # A median that WOULD trip the tight jump-gate band (120 * 0.03 = 3.6,
    # floored at 4.0 -- an 8 BPM gap clears it) but sits well inside the
    # wider refractory-guard band (120 * 0.16 = 19.2) must NOT read as
    # disagreement.
    bt._long_candidate_median = 128.0
    bt._long_candidate_eval_t = bt._last_t
    assert abs(bt._long_candidate_median - bt._bpm) > max(bt._lock_band_min, bt._bpm * bt._lock_band_pct)
    assert bt.candidate_lock_disagreement is False
    # A median outside even the wider band still reads as real disagreement.
    bt._long_candidate_median = 90.0
    bt._long_candidate_eval_t = bt._last_t
    assert bt.candidate_lock_disagreement is True


def test_refractory_guard_band_config_overrides_reach_the_instance() -> None:
    bt = BeatTracker({'refractory_guard_band_pct': 0.05, 'refractory_guard_band_min': 6.0})
    assert bt._refractory_guard_band_pct == pytest.approx(0.05)
    assert bt._refractory_guard_band_min == pytest.approx(6.0)


# --------------------------------------------------------------------------
# onset_strength_max_raw / _max_compressed (real-session evidence for the
# pulse-strength log-compression -- previously synthetic-harness-only)
# --------------------------------------------------------------------------

def test_onset_strength_max_properties_are_zero_with_no_onsets() -> None:
    bt = BeatTracker({})
    assert bt.onset_strength_max_raw == 0.0
    assert bt.onset_strength_max_compressed == 0.0


def test_onset_strength_max_raw_and_compressed_track_the_log_compression() -> None:
    import math

    bt = BeatTracker({})
    audio = SimpleNamespace(bass=0.8, mid=0.3, treble=0.2, spectral_flux=0.0,
                            bass_flux=0.0, beat=0.0)
    onset = _FakeOnset(0.0, 10.0)  # a severe outlier strength
    bt.update(1.0 / 60.0, audio, onsets=[onset], t=0.0, kick_regularity=1.0)

    expected_compressed = 1.0 + math.log1p(10.0 - 1.0)
    assert bt.onset_strength_max_raw == pytest.approx(10.0)
    assert bt.onset_strength_max_compressed == pytest.approx(expected_compressed)
    assert bt.onset_strength_max_compressed < bt.onset_strength_max_raw


def test_onset_strength_history_prunes_outside_its_window() -> None:
    bt = BeatTracker({})
    audio = SimpleNamespace(bass=0.8, mid=0.3, treble=0.2, spectral_flux=0.0,
                            bass_flux=0.0, beat=0.0)
    bt.update(1.0 / 60.0, audio, onsets=[_FakeOnset(0.0, 5.0)], t=0.0, kick_regularity=1.0)
    assert bt.onset_strength_max_raw == pytest.approx(5.0)

    # Well past _V2_ONSET_STRENGTH_WINDOW_S (10.0s) later, a fresh, much
    # smaller onset should have fully evicted the old one from the window.
    later_t = 30.0
    bt.update(1.0 / 60.0, audio, onsets=[_FakeOnset(later_t, 1.5)], t=later_t, kick_regularity=1.0)
    assert bt.onset_strength_max_raw == pytest.approx(1.5)


# --------------------------------------------------------------------------
# Controller-side: mood-prime + tap confirm (bound-method stubs, same
# pattern as test_bpm_detector_audit_regressions)
# --------------------------------------------------------------------------

class _MarkEngine:
    def __init__(self) -> None:
        self.marks: list[tuple[str, dict]] = []

    def mark(self, action: str, **info) -> None:
        self.marks.append((action, info))


def _mood_prime_stub(grid, manager) -> SimpleNamespace:
    ns = SimpleNamespace(
        _mood_prime_enabled=True,
        _mood_prime_confidence=0.7,
        _mood_prime_last_profile_key=None,
        _mood_prime_expected_key='',
        _mood_prime_count=0,
        _grid=grid,
        _audio_manager=manager,
        _engine=_MarkEngine(),
    )
    ns._maybe_mood_prime_on_manual_profile_change = (
        _AUTO_VJ.AutoVJController._maybe_mood_prime_on_manual_profile_change.__get__(ns)
    )
    return ns


class _FakeManager:
    def __init__(self, key: str, profile) -> None:
        self._key = key
        self._profile = profile

    def get_profile_key(self) -> str:
        return self._key

    def get_profile(self):
        return self._profile


class _FakeProfile:
    def __init__(self, hint_min: float, hint_max: float) -> None:
        self.bpm_hint_min = hint_min
        self.bpm_hint_max = hint_max


class _PrimeRecorder:
    def __init__(self, candidates) -> None:
        self.top_candidates = candidates
        self.primed: list[tuple[float, float]] = []

    def prime_tempo(self, bpm: float, *, confidence: float = 0.9) -> None:
        self.primed.append((bpm, confidence))


def test_mood_prime_fires_on_manual_change_with_in_band_candidate() -> None:
    grid = _PrimeRecorder([(120.0, 0.5), (174.0, 0.3)])
    manager = _FakeManager('house', _FakeProfile(118.0, 126.0))
    ns = _mood_prime_stub(grid, manager)
    ns._maybe_mood_prime_on_manual_profile_change()   # seeds, no prime
    assert grid.primed == []
    manager._key = 'drum_and_bass'
    manager._profile = _FakeProfile(165.0, 180.0)
    ns._maybe_mood_prime_on_manual_profile_change()
    assert grid.primed == [(174.0, 0.7)]
    assert ns._mood_prime_count == 1


def test_mood_prime_skips_recommender_initiated_changes() -> None:
    grid = _PrimeRecorder([(120.0, 0.5)])
    manager = _FakeManager('house', _FakeProfile(118.0, 126.0))
    ns = _mood_prime_stub(grid, manager)
    ns._maybe_mood_prime_on_manual_profile_change()   # seed
    ns._mood_prime_expected_key = 'techno'            # recommender applied it
    manager._key = 'techno'
    ns._maybe_mood_prime_on_manual_profile_change()
    assert grid.primed == []
    assert ns._mood_prime_expected_key == ''          # marker consumed


def test_mood_prime_never_fabricates_without_in_band_candidate() -> None:
    grid = _PrimeRecorder([(120.0, 0.5)])
    manager = _FakeManager('house', _FakeProfile(118.0, 126.0))
    ns = _mood_prime_stub(grid, manager)
    ns._maybe_mood_prime_on_manual_profile_change()   # seed
    manager._key = 'drum_and_bass'
    manager._profile = _FakeProfile(165.0, 180.0)     # no candidate in band
    ns._maybe_mood_prime_on_manual_profile_change()
    assert grid.primed == []
    assert any(a == 'mood_prime_skipped' for a, _ in ns._engine.marks)


def test_confirm_tap_tempo_routes_to_tap_prime() -> None:
    grid = BeatTracker({})
    _run_clicks(grid, bpm=120.0, duration_s=2.0)
    ns = SimpleNamespace(_grid=grid, _engine=_MarkEngine())
    ns.confirm_tap_tempo = _AUTO_VJ.AutoVJController.confirm_tap_tempo.__get__(ns)
    assert ns.confirm_tap_tempo(128.0) is True
    assert grid.tap_prime_active is True
    assert any(a == 'tap_prime' for a, _ in ns._engine.marks)
    assert ns.confirm_tap_tempo(500.0) is False


# --------------------------------------------------------------------------
# bpm_agreement_report tool
# --------------------------------------------------------------------------

def test_agreement_report_scores_acc1_acc2_and_folds(tmp_path: Path) -> None:
    session = tmp_path / 'session.jsonl'
    store = tmp_path / 'track_store.json'
    rows = []
    for i in range(12):
        rows.append({'track_path': '/music/a.mp3', 'track': 'A', 'track_artist': 'X',
                     'bpm': 128.0 + 0.1 * (i % 3), 'bpm_shadow': 128.0})
    for i in range(12):
        # Detected at the 4:3 fold of the reference 100 -> ~133.3.
        rows.append({'track_path': '/music/b.mp3', 'track': 'B', 'track_artist': 'Y',
                     'bpm': 133.3, 'bpm_shadow': 133.3})
    session.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
    store.write_text(json.dumps({
        'tracks': {'h1': {'bpm': 128.0}, 'h2': {'bpm': 100.0}},
        'paths': {'/music/a.mp3': {'hash': 'h1'}, '/music/b.mp3': {'hash': 'h2'}},
    }), encoding='utf-8')
    report = _TOOL.build_report(session, store, 0.04, 8)
    assert 'Acc1: 50%' in report
    assert 'Acc2: 100%' in report
    assert '4:3' in report
    assert 'octave-family (4:3)' in report


def test_agreement_report_handles_missing_store(tmp_path: Path) -> None:
    session = tmp_path / 'session.jsonl'
    session.write_text('\n'.join(
        json.dumps({'track': 'A', 'track_artist': 'X', 'bpm': 120.0})
        for _ in range(10)), encoding='utf-8')
    report = _TOOL.build_report(session, None, 0.04, 8)
    assert 'no reference' in report
