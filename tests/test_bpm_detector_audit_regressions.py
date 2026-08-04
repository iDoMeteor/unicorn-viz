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
    psytrance = _FakeProfile(mu=145.0, sigma=0.16, hint_min=140.0, hint_max=149.0)
    tr = BeatTracker({})

    t = _run_steady_click_track(tr, bpm=124.0, duration_s=65.0)
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
        _profile_auto_reco_last_apply_t=-1e9,
        _audio_profile_candidate_key=None,
        _audio_profile_candidate_since_t=-1e9,
        _fire_dj_last_t=-1e9,
        _fire_dj_cooldown_s=1200.0,
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

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio)

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

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio)

    assert grid.prime_tempo_calls == []


def test_recommender_decider_does_not_double_apply_within_cooldown() -> None:
    stub = _make_recommender_stub()
    manager = _FakeManager('tech_house')

    _AUTO_VJ.AutoVJController._maybe_apply_recommended_audio_profile(
        stub, manager=manager, recommended_key='psytrance', score_margin=1.0, mean_confidence=1.0)
    assert manager.set_calls == ['psytrance']

    # Immediately try again (steady track keeps recommending the same
    # switch) -- must be a no-op because the cooldown window hasn't elapsed.
    _AUTO_VJ.AutoVJController._maybe_apply_recommended_audio_profile(
        stub, manager=manager, recommended_key='hardstyle', score_margin=1.0, mean_confidence=1.0)

    assert manager.set_calls == ['psytrance']
