"""Regression tests for docs/audits/2026-08-04-bpm-detector-audit.md (P2-F).

Covers the three cases the audit specifies as required regression coverage
for the P0-A (declamp) + P0-B (mixer BPM as ground truth) fixes:

1. Locked at 124 BPM with high confidence + a Psytrance-like profile (mu=145,
   sigma=0.16) applied -- reported BPM must stay within +/-2 of 124, not drift
   toward the new profile's prior the way the pre-fix hard search-range clamp
   allowed.
2. Silence reset after a mismatched profile was active -- the next lock on a
   fresh 100 BPM click track must land within +/-2 of 100, not be stuck
   inside a stale narrowed range.
3. The profile-recommender decider never applies two profile switches within
   its cooldown window, even when called back-to-back on a steady track.
"""
from __future__ import annotations

import importlib.util
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[1]
_BEAT_GRID_PATH = _REPO / 'drop-ins' / 'auto-vj-01' / 'beat_grid.py'
_AUTO_VJ_PATH = _REPO / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_BEAT_GRID = _load_module(_BEAT_GRID_PATH, 'test_bpm_audit_regressions_beat_grid')
_AUTO_VJ = _load_module(_AUTO_VJ_PATH, 'test_bpm_audit_regressions_auto_vj')

BeatTracker = _BEAT_GRID.BeatTracker


class _FakeOnset:
    def __init__(self, t: float, strength: float = 1.0) -> None:
        self.t = t
        self.strength = strength


class _FakeProfile:
    def __init__(self, mu: float, sigma: float, hint_min: float | None = None,
                 hint_max: float | None = None) -> None:
        self.bpm_prior_mu = mu
        self.bpm_prior_sigma = sigma
        self.bpm_hint_min = hint_min
        self.bpm_hint_max = hint_max


def _audio(bass: float = 0.5, mid: float = 0.3, treble: float = 0.2, flux: float = 0.1) -> SimpleNamespace:
    return SimpleNamespace(bass=bass, mid=mid, treble=treble, spectral_flux=flux)


def _run_steady_click_track(tracker, *, bpm: float, duration_s: float,
                             start_t: float = 0.0, fps: float = 60.0) -> float:
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


def _run_silence(tracker, *, duration_s: float, start_t: float, fps: float = 60.0) -> float:
    dt = 1.0 / fps
    t = start_t
    end_t = start_t + duration_s
    audio = _audio(bass=0.0, mid=0.0, treble=0.0, flux=0.0)
    while t < end_t:
        tracker.update(dt, audio, onsets=[], t=t)
        t += dt
    return t


# ---------------------------------------------------------------------------
# 1. Locked BPM must not drift toward a mismatched profile's prior
# ---------------------------------------------------------------------------

def test_locked_bpm_does_not_drift_toward_mismatched_profile() -> None:
    """2026-08-10: settle window 65s -> 130s -- _V2_PHASE_TOL 0.18 -> 0.12
    means phase_confidence converges noticeably slower (verified directly:
    ~120s to fully stabilize at 124 BPM, versus the old ~65s baseline
    under 0.18); 130s leaves real margin past that."""
    psytrance = _FakeProfile(mu=145.0, sigma=0.16, hint_min=140.0, hint_max=149.0)
    tr = BeatTracker({})

    t = _run_steady_click_track(tr, bpm=124.0, duration_s=130.0)
    assert tr.bpm > 0.0 and tr.confidence >= 0.55, (
        f'did not reach lock confidence before profile switch (bpm={tr.bpm}, confidence={tr.confidence})'
    )

    tr.set_profile(psytrance)
    # Keep feeding the same steady 124 BPM audio after the profile switch --
    # pre-fix, the clamped ACF search range (140-149) would have dragged the
    # estimate toward the new profile's lane within this window.
    _run_steady_click_track(tr, bpm=124.0, duration_s=30.0, start_t=t)

    assert tr.bpm == pytest.approx(124.0, abs=2.0)


# ---------------------------------------------------------------------------
# 2. Silence reset after a mismatched profile must not leave a stale range
# ---------------------------------------------------------------------------

def test_silence_reset_after_mismatched_profile_locks_cleanly_on_new_tempo() -> None:
    psytrance = _FakeProfile(mu=145.0, sigma=0.16, hint_min=140.0, hint_max=149.0)
    tr = BeatTracker({})

    t = _run_steady_click_track(tr, bpm=124.0, duration_s=65.0)
    tr.set_profile(psytrance)
    t = _run_steady_click_track(tr, bpm=124.0, duration_s=5.0, start_t=t)

    # Sustained silence triggers _reset_tempo_lock() internally.
    t = _run_silence(tr, duration_s=20.0, start_t=t)
    assert tr.bpm == 0.0 and tr.confidence == 0.0

    _run_steady_click_track(tr, bpm=100.0, duration_s=65.0, start_t=t)

    assert tr.bpm == pytest.approx(100.0, abs=2.0)


# ---------------------------------------------------------------------------
# 3. Recommender decider must not double-apply within its cooldown
# ---------------------------------------------------------------------------

class _FakeVjApi:
    def is_user_busy(self) -> bool:
        return False


class _FakeApp:
    def __init__(self) -> None:
        self.vj_api = _FakeVjApi()


class _FakeEngine:
    def __init__(self) -> None:
        self.marks: list[tuple[str, dict]] = []

    def mark(self, event: str, **kw) -> None:
        self.marks.append((event, kw))


class _FakeManager:
    def __init__(self, profile_key: str) -> None:
        self._profile_key = profile_key
        self.set_calls: list[str] = []

    def get_profile_key(self) -> str:
        return self._profile_key

    def set_profile(self, key: str) -> bool:
        self.set_calls.append(key)
        self._profile_key = key
        return True


def _make_recommender_stub(**overrides) -> SimpleNamespace:
    stub = SimpleNamespace(
        _app=_FakeApp(),
        _engine=_FakeEngine(),
        _profile_auto_reco_decider_enabled=True,
        _recommended_profile_confirmed=True,
        _profile_auto_reco_decider_min_margin=0.0,
        _profile_auto_reco_decider_min_confidence=0.0,
        _profile_auto_reco_decider_cooldown_s=20.0,
        _profile_auto_reco_decider_force_recommended_prob=0.55,
        _profile_auto_reco_decider_force_current_prob_cap=0.05,
        _profile_auto_reco_decider_force_cooldown_s=6.0,
        _profile_auto_reco_last_apply_t=-1e9,
        _audio_profile_candidate_key=None,
        _audio_profile_candidate_since_t=-1e9,
    )
    for k, v in overrides.items():
        setattr(stub, k, v)
    return stub


# ---------------------------------------------------------------------------
# P0-B: _update_profile_recommendation() primes the tracker from a fresh
# dj_mixer BPM hint before doing anything else that cycle.
# ---------------------------------------------------------------------------

class _FakeVjApiWithBpm:
    def __init__(self, bpm: float) -> None:
        self._bpm = bpm
        self.get_bpm_calls: list[str] = []

    def get_bpm(self, exclude: str = '') -> float:
        self.get_bpm_calls.append(exclude)
        return self._bpm


def _make_reco_stub(*, mixer_bpm: float, grid) -> SimpleNamespace:
    app = SimpleNamespace(vj_api=_FakeVjApiWithBpm(mixer_bpm), _audio_manager=None)
    return SimpleNamespace(
        _app=app,
        _grid=grid,
        _profile_auto_reco_enabled=True,
        _profile_auto_reco_eval_interval_s=0.0,
        _profile_auto_reco_window_s=60.0,
        _reco_last_eval_t=-1e9,
        _reco_samples=deque([
            {'t': time.monotonic(), 'bpm': 124.0, 'conf': 0.6, 'dconf': 0.5, 'locked': True,
             'bass': 0.1, 'mid': 0.1, 'treble': 0.1, 'zcr': 0.0, 'centroid': 0.0,
             'onset_count': 0, 'bands': None, 'spectral_flux': 0.0,
             'vocal_hnr': 0.0, 'vocal_fmr': 0.0}
            for _ in range(3)
        ]),
        _last_onset_count=0,
        _has_bpm_lock=lambda *a, **kw: True,
        _sequence_corpus_writer=None,
        _record_sequence_keyframe=lambda *a, **kw: None,
    )


def test_recommender_cycle_primes_tracker_from_fresh_mixer_bpm() -> None:
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.5,
        prime_tempo_calls=[],
    )
    grid.prime_tempo = lambda bpm, **kw: grid.prime_tempo_calls.append(bpm)
    stub = _make_reco_stub(mixer_bpm=128.0, grid=grid)
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.1, mid=0.1,
                             treble=0.1, spectral_flux=0.0, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    assert stub._app.vj_api.get_bpm_calls == ['auto_vj']
    assert grid.prime_tempo_calls == [128.0]


def test_recommender_cycle_does_not_prime_when_no_fresh_mixer_bpm() -> None:
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.5,
        prime_tempo_calls=[],
    )
    grid.prime_tempo = lambda bpm, **kw: grid.prime_tempo_calls.append(bpm)
    stub = _make_reco_stub(mixer_bpm=0.0, grid=grid)
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.1, mid=0.1,
                             treble=0.1, spectral_flux=0.0, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    assert grid.prime_tempo_calls == []


def test_recommender_decider_does_not_double_apply_within_cooldown() -> None:
    stub = _make_recommender_stub()
    manager = _FakeManager('tech_house')

    _AUTO_VJ.AutoVJController._maybe_apply_recommended_audio_profile(
        stub, manager=manager, recommended_key='psytrance', recommended_score=1.0,
        current_score=0.5, recommended_prob=0.5, current_prob=0.1,
        score_margin=1.0, mean_confidence=1.0, detector_trust=1.0)
    assert manager.set_calls == ['psytrance']

    # Immediately try again (steady track keeps recommending the same
    # switch) -- must be a no-op because the cooldown window hasn't elapsed.
    _AUTO_VJ.AutoVJController._maybe_apply_recommended_audio_profile(
        stub, manager=manager, recommended_key='hardstyle', recommended_score=1.0,
        current_score=0.5, recommended_prob=0.5, current_prob=0.1,
        score_margin=1.0, mean_confidence=1.0, detector_trust=1.0)

    assert manager.set_calls == ['psytrance']


def test_recommender_decider_blocked_when_detector_trust_below_floor() -> None:
    """2026-08-09: a decisive-looking score gap is not itself evidence of
    anything if the detector barely had a lock this cycle -- both paths
    require detector_trust >= _TRUST_FLOOR, checked before either path's
    own gates."""
    stub = _make_recommender_stub()
    manager = _FakeManager('tech_house')

    _AUTO_VJ.AutoVJController._maybe_apply_recommended_audio_profile(
        stub, manager=manager, recommended_key='psytrance', recommended_score=1.0,
        current_score=0.5, recommended_prob=0.9, current_prob=0.01,
        score_margin=1.0, mean_confidence=1.0,
        detector_trust=_AUTO_VJ._TRUST_FLOOR - 0.01)

    assert manager.set_calls == []


# ---------------------------------------------------------------------------
# Fast-override path: a strong candidate can replace an obviously weak
# current profile without waiting out the full cooldown (documented in
# config.toml since 2026-07-06, never actually implemented until now).
# 2026-08-09: migrated from raw composite-score thresholds to softmax
# probability thresholds -- removing lock_rate/mean_conf/mean_dconf from
# the composite shifts every raw score by a session-dependent amount,
# which would have silently broken a fixed absolute-score threshold.
# ---------------------------------------------------------------------------

def test_fast_override_applies_despite_unconfirmed_recommendation() -> None:
    """The fast path bypasses confirm-wins/margin/confidence -- only the
    probability gap matters -- but still applies the (shorter) force
    cooldown, and still requires detector_trust >= _TRUST_FLOOR."""
    stub = _make_recommender_stub(
        _recommended_profile_confirmed=False,
        _profile_auto_reco_decider_min_margin=0.99,
        _profile_auto_reco_decider_min_confidence=0.99,
    )
    manager = _FakeManager('generic')

    _AUTO_VJ.AutoVJController._maybe_apply_recommended_audio_profile(
        stub, manager=manager, recommended_key='deep_house', recommended_score=2.5,
        current_score=1.5, recommended_prob=0.6, current_prob=0.02,
        score_margin=0.0, mean_confidence=0.0, detector_trust=1.0)

    assert manager.set_calls == ['deep_house']


def test_fast_override_does_not_fire_when_current_prob_not_capped() -> None:
    """Recommended probability alone clearing the bar isn't enough -- current
    must also be genuinely weak, else this falls through to the normal
    path."""
    stub = _make_recommender_stub(_recommended_profile_confirmed=False)
    manager = _FakeManager('house')

    _AUTO_VJ.AutoVJController._maybe_apply_recommended_audio_profile(
        stub, manager=manager, recommended_key='deep_house', recommended_score=2.5,
        current_score=2.0, recommended_prob=0.6,
        current_prob=0.20,  # above the 0.05 cap
        score_margin=0.0, mean_confidence=0.0, detector_trust=1.0)

    assert manager.set_calls == []


def test_fast_override_uses_shorter_cooldown_than_normal_path() -> None:
    stub = _make_recommender_stub(_profile_auto_reco_last_apply_t=time.monotonic() - 10.0)
    manager = _FakeManager('generic')

    # 10s ago clears the 6s force cooldown but not the normal 20s cooldown.
    _AUTO_VJ.AutoVJController._maybe_apply_recommended_audio_profile(
        stub, manager=manager, recommended_key='deep_house', recommended_score=2.5,
        current_score=1.5, recommended_prob=0.6, current_prob=0.02,
        score_margin=1.0, mean_confidence=1.0, detector_trust=1.0)

    assert manager.set_calls == ['deep_house']


# ---------------------------------------------------------------------------
# Recommender sigma-floor revert (2026-08-06): a large tempo mismatch must
# actually cost a candidate profile real score, not be nearly free.
#
# P2-E (2026-08-04) raised the recommender's tempo_fit sigma floor from 0.08
# to 0.45 to match beat_grid._MIN_PROFILE_PRIOR_SIGMA, reasoning that two
# different sigma floors disagreeing was itself a bug. A live training
# session (2026-08-06, ~115 min, BPM 110-135 throughout) showed this was
# wrong: psytrance (mu=145) kept winning the composite score anyway --
# spectral-shape fit correctly favored deep_house (cosine similarity 0.879
# vs 0.776 against the session's actual band data) but couldn't overcome a
# tempo_fit term that a 30 BPM miss barely dented under the 0.45 floor. The
# detector's own sigma floor (kept at 0.45, unchanged) and the recommender's
# scoring sigma are different concerns that happened to share a constant --
# reverted to 0.08 here (below every profile's own authored sigma, so it
# never actually binds -- the real per-profile values, e.g. psytrance 0.16,
# are what apply).
# ---------------------------------------------------------------------------

def test_recommender_sigma_floor_source_is_0_08_not_0_45() -> None:
    """Guard against silently re-introducing the P2-E floor. Deliberately a
    source-text check, not a re-derivation of the scoring math: the point is
    to catch the exact constant regressing, the same pattern
    test_bpm_eval_beat_grid_path_points_to_auto_vj_01 uses in
    test_corpus_writers.py."""
    src = _AUTO_VJ_PATH.read_text(encoding='utf-8')
    assert "sigma = max(0.08, float(getattr(profile, 'bpm_prior_sigma'" in src


class _FakeVjApiNoBpm:
    def get_bpm(self, exclude: str = '') -> float:
        return 0.0


def _make_full_reco_stub(*, bpm: float, centroid: float, zcr: float, onset_count: float,
                          n_samples: int = 6) -> SimpleNamespace:
    app = SimpleNamespace(vj_api=_FakeVjApiNoBpm(), _audio_manager=_FakeManager('house'))
    now = time.monotonic()
    samples = deque([
        {'t': now - (n_samples - i) * 0.5, 'bpm': bpm, 'conf': 0.5, 'dconf': 0.4, 'locked': True,
         'bass': 0.34, 'mid': 0.33, 'treble': 0.33, 'zcr': zcr, 'centroid': centroid,
         'onset_count': onset_count, 'bands': None, 'spectral_flux': 0.1,
         'vocal_hnr': 0.0, 'vocal_fmr': 0.0}
        for i in range(n_samples)
    ])
    return SimpleNamespace(
        _app=app,
        _grid=SimpleNamespace(bpm=bpm, confidence=0.5, downbeat_confidence=0.4, top_candidates=[]),
        _engine=_FakeEngine(),
        _profile_auto_reco_enabled=True,
        _profile_auto_reco_eval_interval_s=0.0,
        _profile_auto_reco_window_s=60.0,
        _profile_auto_reco_confirm_wins=1,
        _profile_auto_reco_score_margin=0.0,
        _reco_last_eval_t=-1e9,
        _reco_samples=samples,
        _reco_candidate_key='',
        _reco_candidate_wins=0,
        _recommended_profile_key='',
        _recommended_profile_name='',
        _recommended_profile_range='',
        _recommended_profile_score=0.0,
        _recommended_profile_confirmed=False,
        _current_profile_score=0.0,
        _current_profile_scored=False,
        _last_onset_count=onset_count,
        _kick_energies=deque(maxlen=16),
        _reco_weights=dict(_AUTO_VJ._DEFAULT_RECO_WEIGHTS),
        _has_bpm_lock=lambda *a, **kw: True,
        _spotify_telemetry_snapshot=lambda: {},
        _maybe_apply_recommended_audio_profile=lambda **kw: None,
        _sequence_corpus_writer=None,
        _record_sequence_keyframe=lambda *a, **kw: None,
    )


def test_recommender_prefers_deep_house_over_psytrance_at_120_bpm(monkeypatch) -> None:
    """The 2026-08-06 live-session shape, reproduced directly: candidates
    restricted to just these two (a 20-profile field introduces confounds
    like tech_house/electronic also fitting the tempo reasonably well,
    which obscures the specific psytrance-vs-deep_house comparison this
    fix is about) so the test is deterministic. centroid/zcr/onset_count
    sit partway toward psytrance's own targets (bright, moderately dense --
    not psytrance's exact centroid, since 2026-08-06's centroid_fit weight
    bump to 1.5 makes an exact match win on brightness alone regardless of
    the sigma floor) while bpm=120 sits close to deep_house's 121 mu and 25
    BPM off psytrance's 145. With the old 0.45 sigma floor this combination
    scores psytrance higher despite the tempo miss (verified directly while
    diagnosing the fix, both before and after the centroid_fit reweight);
    with the reverted 0.08 floor (i.e. each profile's own authored sigma --
    0.16 for psytrance) tempo_fit's now-real penalty flips the outcome.

    2026-08-10: onset_count 1.6 -> 1.4 -- onset_fit's weight bumped 0.7 ->
    1.0 that day (owner-agreed LLM tuning recommendation) made the old
    1.6 (onset_density ~3.84, close to psytrance's onset_density_mu=4.0
    vs. deep_house's 2.0) decisive enough on its own to flip the winner
    back to psytrance regardless of tempo_fit. 1.4 keeps the same
    partway-toward-psytrance intent while leaving room for tempo_fit's
    penalty to still be the deciding term, which is what this test is
    actually about."""
    import unicornviz.audio.profiles as profiles_mod
    restricted = {k: profiles_mod.PROFILES[k] for k in ('psytrance', 'deep_house')}
    monkeypatch.setattr(profiles_mod, 'PROFILES', restricted)
    monkeypatch.setattr(profiles_mod, 'enabled_profiles', lambda: restricted)

    stub = _make_full_reco_stub(bpm=120.0, centroid=2350.0, zcr=0.085, onset_count=1.4)
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    assert stub._recommended_profile_key == 'deep_house'


def test_centroid_fit_uses_per_profile_sigma_not_fixed_400(monkeypatch) -> None:
    """2026-08-06: centroid_fit's Gaussian sigma used to be a fixed 400 Hz
    for every profile. It now reads spectral_centroid_sigma per profile
    (tight/medium/wide tiers), mirroring tempo_fit's per-profile mechanism.

    Two variants of the same profile (identical bpm_prior_mu/sigma and
    spectral_centroid_mu -- only spectral_centroid_sigma differs) isolate
    the effect: a centroid reading equally far from mu for both should
    score the *tight*-sigma variant lower, since a tight sigma penalizes
    a given mismatch harder than a wide one."""
    import dataclasses

    import unicornviz.audio.profiles as profiles_mod
    base = profiles_mod.PROFILES['psytrance']
    tight = dataclasses.replace(base, spectral_centroid_sigma=250.0)
    wide = dataclasses.replace(base, spectral_centroid_sigma=600.0)
    restricted = {'tight_test': tight, 'wide_test': wide}
    monkeypatch.setattr(profiles_mod, 'PROFILES', restricted)
    monkeypatch.setattr(profiles_mod, 'enabled_profiles', lambda: restricted)

    # Centroid measured 300 Hz off both profiles' shared mu -- a real
    # mismatch, but every other term (tempo, zcr, onset, mu) is identical
    # between the two candidates, so any score difference is attributable
    # to spectral_centroid_sigma alone.
    off_target_centroid = float(base.spectral_centroid_mu) + 300.0
    stub = _make_full_reco_stub(
        bpm=float(base.bpm_prior_mu), centroid=off_target_centroid,
        zcr=float(base.zcr_mu or 0.08), onset_count=float(base.onset_density_mu or 2.0),
    )
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    assert stub._recommended_profile_key == 'wide_test'


def test_zcr_fit_uses_per_profile_sigma_not_fixed_020(monkeypatch) -> None:
    """2026-08-09: same upgrade as centroid_fit (2026-08-06) and tempo_fit,
    applied to zcr_fit -- was a fixed 0.020 for every profile, now reads
    zcr_sigma per profile."""
    import dataclasses

    import unicornviz.audio.profiles as profiles_mod
    base = profiles_mod.PROFILES['psytrance']
    tight = dataclasses.replace(base, zcr_sigma=0.010)
    wide = dataclasses.replace(base, zcr_sigma=0.040)
    restricted = {'tight_test': tight, 'wide_test': wide}
    monkeypatch.setattr(profiles_mod, 'PROFILES', restricted)
    monkeypatch.setattr(profiles_mod, 'enabled_profiles', lambda: restricted)

    off_target_zcr = float(base.zcr_mu) + 0.03
    stub = _make_full_reco_stub(
        bpm=float(base.bpm_prior_mu), centroid=float(base.spectral_centroid_mu or 2000.0),
        zcr=off_target_zcr, onset_count=float(base.onset_density_mu or 2.0),
    )
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    assert stub._recommended_profile_key == 'wide_test'


def test_onset_fit_uses_per_profile_sigma_not_fixed_1_2(monkeypatch) -> None:
    """Same upgrade applied to onset_fit -- was a fixed 1.2 onsets/s for
    every profile, now reads onset_density_sigma per profile."""
    import dataclasses

    import unicornviz.audio.profiles as profiles_mod
    base = profiles_mod.PROFILES['psytrance']
    tight = dataclasses.replace(base, onset_density_sigma=0.5)
    wide = dataclasses.replace(base, onset_density_sigma=2.0)
    restricted = {'tight_test': tight, 'wide_test': wide}
    monkeypatch.setattr(profiles_mod, 'PROFILES', restricted)
    monkeypatch.setattr(profiles_mod, 'enabled_profiles', lambda: restricted)

    off_target_onset = float(base.onset_density_mu) + 1.5
    stub = _make_full_reco_stub(
        bpm=float(base.bpm_prior_mu), centroid=float(base.spectral_centroid_mu or 2000.0),
        zcr=float(base.zcr_mu or 0.08), onset_count=off_target_onset,
    )
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    assert stub._recommended_profile_key == 'wide_test'


# ---------------------------------------------------------------------------
# 2026-08-09: top-3-weights rewire. lock_rate/mean_conf/mean_dconf retired
# from the composite (proven mathematically inert -- identical for every
# candidate, so they cancel out of the ranking/margin/softmax regardless of
# weight). detector_trust (blend of lock_rate/mean_dconf) now scales how
# large a margin is required to confirm a recommendation.
# ---------------------------------------------------------------------------


def test_lock_rate_mean_conf_mean_dconf_not_in_default_weights() -> None:
    for name in ('lock_rate', 'mean_conf', 'mean_dconf'):
        assert name not in _AUTO_VJ._DEFAULT_RECO_WEIGHTS


def _make_trust_test_stub(*, conf: float, dconf: float, locked: bool) -> SimpleNamespace:
    """Shared setup for the two detector_trust confirmation tests below.
    Restricted to house/deep_house with bpm/centroid/zcr set to the
    midpoint between the two profiles' own mus -- close enough to produce a
    real, non-trivial margin (~0.157, calibrated empirically against the
    2026-08-09 spectral_centroid_mu recalibration -- see profiles.py's field
    comment) rather than a trivial 0.0 or 1.0 that wouldn't distinguish the
    trust-scaling effect. Current profile is 'deep_house' so the winner
    ('house') is a genuine contest against a different candidate, not itself.
    margin_cfg=0.08 leaves real headroom on both sides: low trust (~0.13)
    needs an effective margin well above ~0.157; high trust (~0.96) needs
    an effective margin comfortably below it.

    onset_count=1.9 (2026-08-10, was the literal mu average, 2.25) --
    onset_count isn't onset_density itself, it accumulates across the
    stub's 6 samples over the fit's rolling window, so the true onset
    density landing at the fit is a multiple of onset_count, not equal to
    it; the literal mu average landed the actual fit input far from
    either profile's onset_density_mu, which the 2026-08-09 onset_fit
    weight (0.7) was too small to expose but the 2026-08-10 bump to 1.0
    (owner-agreed LLM tuning recommendation) was not -- it flipped the
    winner to deep_house outright. Re-tuned empirically (not re-derived
    analytically -- the accumulation window's exact effective duration
    isn't a clean closed form worth chasing) to restore both this
    fixture's own stated intent (a small, real, non-trivial margin) and
    the original winner/confirmation behavior."""
    import unicornviz.audio.profiles as profiles_mod
    h = profiles_mod.PROFILES['house']
    dh = profiles_mod.PROFILES['deep_house']
    mid_bpm = (h.bpm_prior_mu + dh.bpm_prior_mu) / 2
    mid_centroid = (h.spectral_centroid_mu + dh.spectral_centroid_mu) / 2
    mid_zcr = (h.zcr_mu + dh.zcr_mu) / 2
    stub = _make_full_reco_stub(bpm=mid_bpm, centroid=mid_centroid, zcr=mid_zcr, onset_count=1.9)
    stub._app._audio_manager._profile_key = 'deep_house'
    stub._profile_auto_reco_score_margin = 0.08
    stub._profile_auto_reco_confirm_wins = 1
    for s in stub._reco_samples:
        s['conf'] = conf
        s['dconf'] = dconf
        s['locked'] = locked
    return stub


def test_low_detector_trust_requires_bigger_margin_to_confirm(monkeypatch) -> None:
    """A margin that would confirm at full trust must NOT confirm when
    lock_rate/mean_dconf are both weak -- the effective threshold scales up
    as 1/detector_trust."""
    import unicornviz.audio.profiles as profiles_mod
    restricted = {'house': profiles_mod.PROFILES['house'], 'deep_house': profiles_mod.PROFILES['deep_house']}
    monkeypatch.setattr(profiles_mod, 'PROFILES', restricted)
    monkeypatch.setattr(profiles_mod, 'enabled_profiles', lambda: restricted)
    # Weak lock/downbeat-phase confidence this cycle -> low detector_trust
    # (mean_conf stays high, isolating lock_rate/dconf's contribution).
    stub = _make_trust_test_stub(conf=0.9, dconf=0.05, locked=False)
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    assert stub._recommended_profile_key == 'house'
    event, kw = stub._engine.marks[0]
    assert kw['detector_trust'] < 0.2   # confirms the low-trust setup actually landed
    assert stub._recommended_profile_confirmed is False


def test_high_detector_trust_confirms_at_configured_margin(monkeypatch) -> None:
    """Same setup as above but with a solid lock/downbeat-phase reading --
    confirmation should proceed normally at the configured margin."""
    import unicornviz.audio.profiles as profiles_mod
    restricted = {'house': profiles_mod.PROFILES['house'], 'deep_house': profiles_mod.PROFILES['deep_house']}
    monkeypatch.setattr(profiles_mod, 'PROFILES', restricted)
    monkeypatch.setattr(profiles_mod, 'enabled_profiles', lambda: restricted)
    stub = _make_trust_test_stub(conf=0.9, dconf=0.95, locked=True)
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    assert stub._recommended_profile_key == 'house'
    event, kw = stub._engine.marks[0]
    assert kw['detector_trust'] > 0.9   # confirms the high-trust setup actually landed
    assert stub._recommended_profile_confirmed is True


def test_detector_trust_logged_on_profile_recommendation_event() -> None:
    stub = _make_full_reco_stub(bpm=124.0, centroid=2000.0, zcr=0.08, onset_count=2.0)
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    event, kw = stub._engine.marks[0]
    assert event == 'profile_recommendation'
    assert 'detector_trust' in kw
    assert 0.0 <= kw['detector_trust'] <= 1.0


# ---------------------------------------------------------------------------
# 2026-08-09: top_cand_fit was initialized to 0.0 and combined via max() with
# terms that are always <= 0 (Gaussian log-density), so the 0.0 floor always
# won -- the term was silently dead on every row of every session ever
# logged (confirmed against real training data: 0/803 nonzero rows). Fixed
# by flooring at the worst real candidate instead of 0.0, falling back to
# 0.0 only in the genuine no-candidates-at-all case.
# ---------------------------------------------------------------------------


def test_top_cand_fit_reflects_real_candidate_fit_not_floored_at_zero(monkeypatch) -> None:
    import unicornviz.audio.profiles as profiles_mod
    restricted = {'house': profiles_mod.PROFILES['house']}
    monkeypatch.setattr(profiles_mod, 'PROFILES', restricted)
    monkeypatch.setattr(profiles_mod, 'enabled_profiles', lambda: restricted)
    mu = float(restricted['house'].bpm_prior_mu)

    stub = _make_full_reco_stub(bpm=mu, centroid=2000.0, zcr=0.08, onset_count=2.0)
    # A single ACF top-candidate well off this profile's prior -- top_cand_fit
    # for 'house' must come out clearly negative, not floored at 0.0.
    stub._grid = SimpleNamespace(bpm=mu, confidence=0.5, downbeat_confidence=0.4,
                                  top_candidates=[(mu * 1.5, 1.0)])
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    event, kw = stub._engine.marks[0]
    assert event == 'profile_recommendation'
    assert kw['term_values_by_candidate']['house']['top_cand_fit'] < -0.01


def test_top_cand_fit_zero_only_when_no_candidates_at_all() -> None:
    stub = _make_full_reco_stub(bpm=124.0, centroid=2000.0, zcr=0.08, onset_count=2.0)
    assert stub._grid.top_candidates == []  # the stub's default -- no ACF candidates, no mixer hint

    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    event, kw = stub._engine.marks[0]
    for candidate_terms in kw['term_values_by_candidate'].values():
        assert candidate_terms['top_cand_fit'] == 0.0


# ---------------------------------------------------------------------------
# 2026-08-09: term_spread (max-min across candidates) can show a term was
# discriminating that cycle but not whether it favored the *correct*
# candidate -- real per-term accuracy needs each candidate's raw value.
# term_values_by_candidate carries that; lock_rate/mean_conf/mean_dconf are
# excluded since they're identical for every candidate (see the top-3-weight
# discussion in docs/adr/vj-system.md).
# ---------------------------------------------------------------------------


def test_term_values_by_candidate_excludes_non_discriminating_terms() -> None:
    stub = _make_full_reco_stub(bpm=124.0, centroid=2000.0, zcr=0.08, onset_count=2.0)
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    event, kw = stub._engine.marks[0]
    by_candidate = kw['term_values_by_candidate']
    assert by_candidate  # at least one enabled profile scored
    for terms in by_candidate.values():
        assert 'lock_rate' not in terms
        assert 'mean_conf' not in terms
        assert 'mean_dconf' not in terms
        assert 'tempo_fit' in terms
        assert 'centroid_fit' in terms
        assert 'vocal_hnr_fit' in terms
        assert 'vocal_fmr_fit' in terms


def test_term_values_by_candidate_reaches_sequence_corpus_too() -> None:
    """The decision log and the sequence corpus are two independent sinks --
    both must get the new field, not just whichever one a test happens to
    check first."""
    stub = _make_full_reco_stub(bpm=124.0, centroid=2000.0, zcr=0.08, onset_count=2.0)
    captured: list[dict] = []
    stub._record_sequence_keyframe = lambda *a, **kw: captured.append(kw)
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    assert len(captured) == 1
    assert 'term_values_by_candidate' in captured[0]
    assert captured[0]['term_values_by_candidate']


# ---------------------------------------------------------------------------
# 2026-08-09: found live -- a session whose observed spectral centroid ran
# ~3700-4000 Hz against every profile's spectral_centroid_mu topping out at
# 2500 Hz drove centroid_fit past -70 raw for the tightest-sigma candidates,
# completely swamping every other term (which rarely exceed a few units) and
# making the composite score effectively just "which candidate's sigma
# happens to be widest," not genre fit. Every *_fit Gaussian term is now
# clipped at _GAUSSIAN_FIT_X_CLIP (6.0) sigma before squaring.
# ---------------------------------------------------------------------------


def test_centroid_fit_is_clipped_for_an_extreme_mismatch(monkeypatch) -> None:
    import unicornviz.audio.profiles as profiles_mod
    base = profiles_mod.PROFILES['psytrance']  # spectral_centroid_sigma=250 (tight)
    restricted = {'psytrance': base}
    monkeypatch.setattr(profiles_mod, 'PROFILES', restricted)
    monkeypatch.setattr(profiles_mod, 'enabled_profiles', lambda: restricted)

    # ~16 sigma off mu at this profile's tight 250 Hz sigma -- would be
    # -0.5*16^2 = -128 raw uncapped; must land at exactly -0.5*6^2 = -18.0.
    extreme_centroid = float(base.spectral_centroid_mu) + 250.0 * 16.0
    stub = _make_full_reco_stub(
        bpm=float(base.bpm_prior_mu), centroid=extreme_centroid,
        zcr=float(base.zcr_mu or 0.08), onset_count=float(base.onset_density_mu or 2.0),
    )
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    event, kw = stub._engine.marks[0]
    centroid_fit = kw['term_values_by_candidate']['psytrance']['centroid_fit']
    assert centroid_fit == pytest.approx(-18.0, abs=1e-6)


def test_centroid_fit_clips_symmetrically_below_mu_too(monkeypatch) -> None:
    """Same clip, opposite direction -- an observed value far *below* mu
    must clip to the same -18.0 floor as far *above* (test above), not
    just one side of the Gaussian."""
    import unicornviz.audio.profiles as profiles_mod
    base = profiles_mod.PROFILES['psytrance']
    restricted = {'psytrance': base}
    monkeypatch.setattr(profiles_mod, 'PROFILES', restricted)
    monkeypatch.setattr(profiles_mod, 'enabled_profiles', lambda: restricted)

    extreme_centroid = max(1.0, float(base.spectral_centroid_mu) - 250.0 * 16.0)
    stub = _make_full_reco_stub(
        bpm=float(base.bpm_prior_mu), centroid=extreme_centroid,
        zcr=float(base.zcr_mu or 0.08), onset_count=float(base.onset_density_mu or 2.0),
    )
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    event, kw = stub._engine.marks[0]
    centroid_fit = kw['term_values_by_candidate']['psytrance']['centroid_fit']
    assert centroid_fit == pytest.approx(-18.0, abs=1e-6)


def test_perc_band_centers_hz_matches_the_fingerprint_generator_tool() -> None:
    """PERC_BAND_CENTERS_HZ (unicornviz/audio/analyzer.py) must be the exact
    same 64 values tools/gen_spectral_fingerprints.py's _centers computes
    (both: geometric mean of np.logspace(log10(30), log10(16000), 65) band
    edges) -- that tool's own output (tools/spectral_fingerprints_out.py's
    BAND_CENTERS_HZ literal) is what every profile's spectral_centroid_mu
    was seeded from. If these ever drift apart, centroid_fit's live
    measurement and mu are back to being computed in different bases --
    the exact bug this constant exists to close. See
    docs/adr/vj-system.md."""
    from unicornviz.audio.analyzer import PERC_BAND_CENTERS_HZ
    from tools.spectral_fingerprints_out import BAND_CENTERS_HZ

    assert len(PERC_BAND_CENTERS_HZ) == len(BAND_CENTERS_HZ) == 64
    for live, tool in zip(PERC_BAND_CENTERS_HZ, BAND_CENTERS_HZ):
        assert live == pytest.approx(tool, abs=0.02)


def test_centroid_hz_axis_uses_audio_manager_sample_rate_when_available() -> None:
    """2026-08-09: the centroid Hz axis used to assume a fixed 22050 Hz
    Nyquist (44.1kHz) regardless of the real capture rate -- understating
    every reading ~8.8% against this project's own documented 48kHz
    default. Now read live from AudioManager.sample_rate. All FFT energy
    concentrated in the last bin makes the resulting mean_centroid a
    direct, exact readout of the Nyquist actually used.

    2026-08-11: this is the restored pre-log-band-formula test -- the
    live centroid measurement briefly switched to a log-band audio.bands
    formula (dot(PERC_BAND_CENTERS_HZ, bands)/sum(bands)) and back within
    a day, after the log-band version was found live to bias the
    recommender toward `ambient` on essentially all real audio (see
    docs/adr/vj-system.md). Reverted to this linear-FFT formula; see the
    field comment above _update_profile_recommendation's centroid
    computation for the full incident."""
    # _make_full_reco_stub pre-populates 6 samples at centroid=0.0; this
    # tick's fresh sample (computed from audio.fft below) joins them in the
    # same rolling window, so mean_centroid is the average of all 7 --
    # divide the expected raw reading by 7 accordingly.
    stub = _make_full_reco_stub(bpm=124.0, centroid=0.0, zcr=0.08, onset_count=2.0)
    stub._audio_manager = SimpleNamespace(sample_rate=44100)
    fft = np.zeros(100, dtype=np.float32)
    fft[-1] = 1.0
    audio = SimpleNamespace(waveform=None, fft=fft, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    event, kw = stub._engine.marks[0]
    assert kw['mean_centroid'] == pytest.approx(22050.0 * 0.99 / 7.0, abs=1.0)


def test_centroid_hz_axis_falls_back_to_48000_without_audio_manager() -> None:
    """No _audio_manager (or one missing sample_rate) degrades to 48000 --
    this project's own documented capture default -- rather than raising."""
    stub = _make_full_reco_stub(bpm=124.0, centroid=0.0, zcr=0.08, onset_count=2.0)
    stub._audio_manager = None
    fft = np.zeros(100, dtype=np.float32)
    fft[-1] = 1.0
    audio = SimpleNamespace(waveform=None, fft=fft, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    event, kw = stub._engine.marks[0]
    assert kw['mean_centroid'] == pytest.approx(24000.0 * 0.99 / 7.0, abs=1.0)


def test_profile_recommendation_mark_stamps_recommender_version() -> None:
    """2026-08-11: the profile_recommendation decision-log mark() and
    sequence-corpus keyframe now both stamp recommender_version, so future
    corpus analysis can tell which formula (old raw-linear-FFT centroid vs.
    the fixed log-band-weighted one) produced a given historical
    mean_centroid without guessing from timestamps -- same rationale as
    dj-mixer-01's ANALYSIS_VERSION (see CLAUDE.md)."""
    stub = _make_full_reco_stub(bpm=124.0, centroid=2000.0, zcr=0.08, onset_count=2.0)
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    event, kw = stub._engine.marks[0]
    assert kw['recommender_version'] == _AUTO_VJ._RECOMMENDER_VERSION


def test_gaussian_fit_x_clip_constant_matches_the_documented_floor() -> None:
    """Direct check on the shared clip constant every *_fit term uses (see
    _gaussian_fit() inside _update_profile_recommendation) -- 6.0 sigma,
    -18.0 raw ceiling, matches what the two centroid_fit tests above
    observe end-to-end."""
    assert _AUTO_VJ._GAUSSIAN_FIT_X_CLIP == pytest.approx(6.0)
    x_clip = _AUTO_VJ._GAUSSIAN_FIT_X_CLIP
    assert -0.5 * x_clip * x_clip == pytest.approx(-18.0)
