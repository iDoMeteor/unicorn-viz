"""Tests for the BPM/genre candidate matcher's LOW half (recommender rc.21).

The genre-intelligence plan § 5: when the detector's ACF is unsure, the
winning (detector-candidate × genre) pair endorses that DETECTOR
candidate's BPM through the genre-evidence channel — genre disambiguates
the fold among hypotheses the ACF itself proposed, and can never
generate a tempo of its own. Supersedes the round-three genre-prior
push, which stays available behind ``genre_matcher_enabled = false``.
"""
from __future__ import annotations

import importlib.util
import sys
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_AV = _load('test_genre_matcher_auto_vj', _REPO / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py')


# ---------------------------------------------------------------------------
# _matcher_range_fit
# ---------------------------------------------------------------------------

def test_range_fit_inside_widened_band_is_one() -> None:
    assert _AV._matcher_range_fit(120.0, 118.0, 126.0, 0.15) == 1.0
    assert _AV._matcher_range_fit(101.0, 118.0, 126.0, 0.15) == 1.0  # 118*0.85=100.3
    assert _AV._matcher_range_fit(144.0, 118.0, 126.0, 0.15) == 1.0  # 126*1.15=144.9


def test_range_fit_decays_then_zeroes_outside() -> None:
    near = _AV._matcher_range_fit(150.0, 118.0, 126.0, 0.15)   # just past the edge
    far = _AV._matcher_range_fit(174.0, 118.0, 126.0, 0.15)    # a fold away
    assert 0.0 < near < 1.0
    assert far == 0.0
    assert _AV._matcher_range_fit(87.0, 165.0, 180.0, 0.15) == 0.0  # dnb band vs 87


def test_range_fit_degenerate_inputs() -> None:
    assert _AV._matcher_range_fit(0.0, 118.0, 126.0, 0.15) == 0.0
    assert _AV._matcher_range_fit(120.0, 0.0, 0.0, 0.15) == 0.0


# ---------------------------------------------------------------------------
# Endorsement through _update_profile_recommendation
# ---------------------------------------------------------------------------

class _FakeVjApiNoBpm:
    def is_user_busy(self) -> bool:
        return False

    def get_bpm(self, exclude: str = '') -> float:
        return 0.0

    def get_track_path(self, *a, **kw) -> str:
        return ''


class _FakeEngine:
    def __init__(self) -> None:
        self.marks: list[tuple[str, dict]] = []

    def mark(self, event: str, **kw) -> None:
        self.marks.append((event, kw))


class _FakeManager:
    def __init__(self, key: str) -> None:
        self._profile_key = key

    def get_profile_key(self) -> str:
        return self._profile_key

    def set_profile(self, key: str) -> bool:
        self._profile_key = key
        return True


class _PushRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[float, float, float]] = []

    def __call__(self, mu: float, sigma: float, weight: float) -> None:
        self.calls.append((float(mu), float(sigma), float(weight)))


def _matcher_stub(*, zcr: float, top_candidates: list[tuple[float, float]],
                  matcher_enabled: bool = True) -> tuple[SimpleNamespace, _PushRecorder]:
    """Full recommender stub: ambiguous detector (unlocked), genre decided
    by zcr (the only weighted timbre term the fixture feeds)."""
    import time as _t
    push = _PushRecorder()
    now = _t.monotonic()
    # 48 samples: _update_profile_recommendation appends one live sample
    # from the (silent) fixture audio before evaluating, which dilutes
    # the window means — enough history makes that negligible.
    samples = deque([
        {'t': now - (48 - i) * 0.5, 'bpm': 0.0, 'conf': 0.2, 'dconf': 0.2,
         'locked': False, 'bass': 0.34, 'mid': 0.33, 'treble': 0.33,
         'zcr': zcr, 'centroid': 2000.0, 'onset_count': 2.0, 'bands': None,
         'spectral_flux': 0.1, 'vocal_hnr': 0.0, 'vocal_fmr': 0.0}
        for i in range(48)
    ])
    grid = SimpleNamespace(bpm=0.0, confidence=0.2, downbeat_confidence=0.2,
                           top_candidates=top_candidates,
                           set_genre_tempo_evidence=push)
    stub = SimpleNamespace(
        _app=SimpleNamespace(vj_api=_FakeVjApiNoBpm(), _audio_manager=_FakeManager('rap_rnb')),
        _grid=grid,
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
        _last_onset_count=2.0,
        _kick_energies=deque(maxlen=16),
        # zcr is the fixture's ONLY tempo-independent discriminator:
        # vocal weights zeroed (the fixture feeds hnr/fmr = 0, which the
        # vocal-expecting rap_rnb profile would otherwise be penalized
        # for more than drum_and_bass, swamping the zcr signal).
        _reco_weights={**_AV._DEFAULT_RECO_WEIGHTS,
                       'vocal_hnr_fit': 0.0, 'vocal_fmr_fit': 0.0},
        _has_bpm_lock=lambda *a, **kw: False,
        _spotify_telemetry_snapshot=lambda: {},
        _maybe_apply_recommended_audio_profile=lambda **kw: None,
        _sequence_corpus_writer=None,
        _record_sequence_keyframe=lambda *a, **kw: None,
        _genre_matcher_enabled=matcher_enabled,
        _genre_matcher_endorse_sigma=0.06,
        _genre_matcher_endorse_count=0,
        _profile_reco_bpm_prefilter_margin=0.15,
    )
    stub._now = lambda: _AV.AutoVJController._now(stub)
    return stub, push


_FOLD_CANDS = [(87.0, 0.5), (174.0, 0.45)]  # the R&B-vs-DnB fold, ACF-proposed


def _restrict(monkeypatch, keys: tuple[str, ...]) -> None:
    import unicornviz.audio.profiles as profiles_mod
    restricted = {k: profiles_mod.PROFILES[k] for k in keys}
    monkeypatch.setattr(profiles_mod, 'PROFILES', restricted)
    monkeypatch.setattr(profiles_mod, 'enabled_profiles', lambda: restricted)


_AUDIO = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                         treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)


def test_matcher_endorses_the_genre_consistent_fold(monkeypatch) -> None:
    """The core promise: same two ACF candidates, genre decides the fold.
    zcr near rap_rnb's mu -> the 87 BPM candidate gets endorsed."""
    _restrict(monkeypatch, ('rap_rnb', 'drum_and_bass'))
    stub, push = _matcher_stub(zcr=0.054, top_candidates=list(_FOLD_CANDS))

    _AV.AutoVJController._update_profile_recommendation(stub, _AUDIO, SimpleNamespace(), {})

    assert len(push.calls) == 1
    mu, sigma, weight = push.calls[0]
    assert mu == pytest.approx(87.0)
    assert sigma == pytest.approx(0.06)
    assert weight > 0.0
    assert stub._genre_matcher_endorse_count == 1
    _event, kw = stub._engine.marks[0]
    assert kw['matcher_endorsed_bpm'] == pytest.approx(87.0)
    assert kw['matcher_endorsed_genre'] == 'rap_rnb'


def test_matcher_flips_fold_when_genre_flips(monkeypatch) -> None:
    """Identical detector candidates, zcr clearly on drum_and_bass's side ->
    the 174 BPM candidate gets endorsed instead.

    2026-09-04 (recommender rc.30): zcr updated (0.085 -> 0.10) after
    zcr_mu/zcr_sigma's evidence-based re-fit. The old 0.085 was an exact
    copy of drum_and_bass's own old hand-picked zcr_mu; after the re-fit,
    rap_rnb (0.0563) and drum_and_bass (0.0609) sit much closer together
    (both zcr_sigma landed on the new 0.03 floor -- see zcr_sigma's own
    field comment in profiles.py) than the old 0.054/0.085 pair did, so
    sitting exactly at drum_and_bass's new mu no longer clears the margin
    (started resolving to rap_rnb's 87.0 fold instead of drum_and_bass's
    174.0 -- confirmed by sweeping zcr from 0.06-0.15: the crossover now
    sits between 0.08 and 0.09). 0.10 gives a comfortable, stable margin
    past that crossover rather than sitting right on it."""
    _restrict(monkeypatch, ('rap_rnb', 'drum_and_bass'))
    stub, push = _matcher_stub(zcr=0.10, top_candidates=list(_FOLD_CANDS))

    _AV.AutoVJController._update_profile_recommendation(stub, _AUDIO, SimpleNamespace(), {})

    assert len(push.calls) == 1
    assert push.calls[0][0] == pytest.approx(174.0)
    _event, kw = stub._engine.marks[0]
    assert kw['matcher_endorsed_genre'] == 'drum_and_bass'


def test_matcher_never_endorses_outside_detector_candidates(monkeypatch) -> None:
    """One-way flow, structural: with no ACF candidates there is nothing
    to endorse — no push, regardless of how confident genre is."""
    _restrict(monkeypatch, ('rap_rnb', 'drum_and_bass'))
    stub, push = _matcher_stub(zcr=0.054, top_candidates=[])

    _AV.AutoVJController._update_profile_recommendation(stub, _AUDIO, SimpleNamespace(), {})

    assert push.calls == []
    assert stub._genre_matcher_endorse_count == 0
    _event, kw = stub._engine.marks[0]
    assert kw['matcher_endorsed_bpm'] == 0.0


def test_legacy_prior_push_behind_the_rollback_flag(monkeypatch) -> None:
    """genre_matcher_enabled = false restores the round-three behavior:
    the winning genre's PRIOR mu/sigma is pushed, not a candidate BPM."""
    _restrict(monkeypatch, ('rap_rnb', 'drum_and_bass'))
    stub, push = _matcher_stub(zcr=0.054, top_candidates=list(_FOLD_CANDS),
                               matcher_enabled=False)

    _AV.AutoVJController._update_profile_recommendation(stub, _AUDIO, SimpleNamespace(), {})

    assert len(push.calls) == 1
    mu, sigma, _weight = push.calls[0]
    import unicornviz.audio.profiles as profiles_mod
    rnb = profiles_mod.PROFILES['rap_rnb']
    assert mu == pytest.approx(float(rnb.bpm_prior_mu))
    assert sigma == pytest.approx(float(rnb.bpm_prior_sigma))
    assert stub._genre_matcher_endorse_count == 0
