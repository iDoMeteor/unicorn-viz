"""2026-09-11 (recommender rc.48): "one scoring function" refactor.

`score_profile_candidates()` (drop-ins/auto-vj-01/auto_vj.py, module
level, near `_matcher_range_fit`) is the ONE implementation of the
per-candidate composite/term math -- both `_update_profile_recommendation()`
(the live recommender) and the offline own-wins instrument call it now,
where before the offline instrument could only ever re-implement the
math by reading the source (a `_profile_score()` nested closure reading
`self._reco_weights` directly). That re-implementation had silently
drifted: diagnosing why the offline instrument agreed with the live
recommender's own per-tick decision only 41% of the time on the same
corpus rows found `kick_regularity_fit`'s validity gate
(`kick_regularity_valid`, >= 4 recent kick-transient phases) was simply
missing from the offline reimplementation, which always computed a
value from whatever `kick_regularity` a corpus row carried -- even in
windows where live would have suppressed the term to a neutral 0.0.
Since `kick_regularity_fit` carries a weight of 1.5 (tied for the
composite's highest), this term-level divergence alone could plausibly
decide a close composite. See docs/adr/vj-system.md "One Scoring
Function" for the full diagnosis and the pre-refactor/post-refactor
golden-test methodology used to land this refactor with zero behavior
change (proven, not assumed): every one of 135 term values across 6
real-data scenarios and 14 profiles came back byte-identical before and
after.

This file pins: (1) `score_profile_candidates` is directly callable as
a pure function (no controller state) with a known, worked-through
composite for a simple synthetic case: any future change to its math
must update this test deliberately, not by accident. (2) The
`kick_regularity_valid` gate specifically, since that's the exact term
the offline/live divergence turned on. (3) `_serialize_reco_features()`
(rc.142) round-trips through JSON into an identical composite --
reconstruction attempts having already failed three times is the whole
reason this exists (see docs/adr/vj-system.md "One Scoring Function").

Reuses the `_make_full_reco_stub`/`_bind_now` harness pattern already
established in test_bpm_detector_audit_regressions.py.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
_AUTO_VJ_PATH = _REPO / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_AUTO_VJ = _load_module(_AUTO_VJ_PATH, 'test_score_profile_candidates_auto_vj')


def _empty_features(**overrides) -> dict:
    base = {
        'log2_bpms': [],
        'mean_zcr': 0.0,
        'onset_density': 0.0,
        'mean_vocal_hnr': 0.0,
        'mean_vocal_fmr': 0.0,
        'mean_contrast': 0.0,
        'top_cand_log2s': [],
        'band_mean_vec': None,
        'raw_kick_regularity': 0.0,
        'kick_regularity_valid': False,
    }
    base.update(overrides)
    return base


def _make_profile(**kwargs):
    import unicornviz.audio.profiles as profiles_mod
    base = profiles_mod.PROFILES['house']
    defaults = dict(
        name='Synthetic', description='', bass_min=base.bass_min, bass_max=base.bass_max,
        mid_min=base.mid_min, mid_max=base.mid_max, treble_min=base.treble_min,
        treble_max=base.treble_max,
    )
    defaults.update(kwargs)
    return profiles_mod.AudioProfile(**defaults)


def test_pure_function_no_controller_state_required() -> None:
    """score_profile_candidates() takes only its four documented
    arguments -- no `self`, no controller attribute reads. Calling it
    with plain dicts/profiles (no AutoVJController instance anywhere)
    must work, which is the whole point of the refactor: the offline
    instrument can call this without constructing a fake controller."""
    profile = _make_profile(zcr_mu=0.08, zcr_sigma=0.02)
    profiles = {'synthetic': profile}
    weights = {'zcr_fit': 1.0}
    features = _empty_features(mean_zcr=0.08)
    result = _AUTO_VJ.score_profile_candidates(features, profiles, weights, [0.1] * 64)
    assert 'synthetic' in result
    composite, terms = result['synthetic']
    # zcr matches mu exactly -> x=0 -> zcr_fit = -log(sigma) - 0 = -log(0.02)
    assert terms['zcr_fit'] == -math.log(0.02)
    assert composite == terms['zcr_fit']  # only zcr_fit weighted nonzero


def test_kick_regularity_valid_gate_zeros_the_term() -> None:
    """The exact divergence found while diagnosing the offline
    instrument's 41% mismatch: kick_regularity_fit must read 0.0 when
    kick_regularity_valid is False, REGARDLESS of what raw_kick_
    regularity holds -- the pre-refactor offline reimplementation had
    no equivalent gate and always computed a value from whatever
    kick_regularity a corpus row carried."""
    profile = _make_profile(expected_bands=[0.9] * 64)  # exp_kick (bands 0-11) = 0.9
    profiles = {'synthetic': profile}
    weights = {'kick_regularity_fit': 1.5}

    invalid_features = _empty_features(raw_kick_regularity=0.9, kick_regularity_valid=False)
    _, invalid_terms = _AUTO_VJ.score_profile_candidates(
        invalid_features, profiles, weights, [0.1] * 64)['synthetic']
    assert invalid_terms['kick_regularity_fit'] == 0.0

    valid_features = _empty_features(raw_kick_regularity=0.9, kick_regularity_valid=True)
    _, valid_terms = _AUTO_VJ.score_profile_candidates(
        valid_features, profiles, weights, [0.1] * 64)['synthetic']
    # (0.9-0.5)*(0.9-0.5)*4.0 = 0.64
    assert valid_terms['kick_regularity_fit'] == (0.9 - 0.5) * (0.9 - 0.5) * 4.0
    assert valid_terms['kick_regularity_fit'] != invalid_terms['kick_regularity_fit']


def test_one_bad_profile_does_not_take_down_the_others() -> None:
    """Matches the pre-refactor per-candidate try/except at the call
    site (now inside score_profile_candidates itself): a profile whose
    attribute access raises must be skipped, not abort every other
    candidate's scoring."""
    good = _make_profile(zcr_mu=0.08, zcr_sigma=0.02)
    # A plain object()'s missing attributes still succeed via getattr()'s
    # own default argument, so it wouldn't actually raise -- force a
    # genuine exception via a property that raises instead.

    class _Bomb:
        @property
        def bpm_prior_mu(self):
            raise RuntimeError('boom')

    profiles = {'good': good, 'bad': _Bomb()}
    weights = {'zcr_fit': 1.0}
    features = _empty_features(mean_zcr=0.08)
    result = _AUTO_VJ.score_profile_candidates(features, profiles, weights, [0.1] * 64)
    assert 'good' in result
    assert 'bad' not in result


class _FakeVjApiNoBpm:
    def is_user_busy(self) -> bool:
        return False

    def get_bpm(self):
        return None

    def get_section(self):
        return None

    def get_track_path(self) -> str:
        return ''


class _FakeManager:
    def __init__(self, key: str) -> None:
        self._key = key

    def get_profile_key(self) -> str:
        return self._key

    def get_profile(self):
        import unicornviz.audio.profiles as profiles_mod
        return profiles_mod.PROFILES[self._key]

    def get_profile_bpm_range(self):
        return (100, 140)


class _FakeEngine:
    def __init__(self) -> None:
        self.marks: list[tuple] = []

    def mark(self, event, **kw) -> None:
        self.marks.append((event, kw))


def test_update_profile_recommendation_wires_through_the_shared_function(monkeypatch) -> None:
    """End-to-end wiring check: _update_profile_recommendation() must
    actually CALL score_profile_candidates() (not a stray leftover
    private copy of the math) and use its return value unchanged for
    term_values_by_candidate -- proving the live method is wired to the
    one shared implementation, via a spy wrapper rather than hand-
    duplicating the aggregate math (window_dur/mean_zcr/etc. depend on
    exactly which sample the method itself appends from `audio`, which
    this test should not need to reproduce to prove wiring)."""
    import unicornviz.audio.profiles as profiles_mod
    restricted = {'house': profiles_mod.PROFILES['house']}
    monkeypatch.setattr(profiles_mod, 'PROFILES', restricted)
    monkeypatch.setattr(profiles_mod, 'enabled_profiles', lambda: restricted)

    calls: list[dict] = []
    real_score_fn = _AUTO_VJ.score_profile_candidates

    def _spy(features, profiles, weights, shared_sigma):
        calls.append(features)
        return real_score_fn(features, profiles, weights, shared_sigma)

    monkeypatch.setattr(_AUTO_VJ, 'score_profile_candidates', _spy)

    from collections import deque
    now = 100000.0
    samples = deque([
        {'t': now - (6 - i) * 0.5, 'bpm': 124.0, 'conf': 0.5, 'dconf': 0.4, 'locked': True,
         'bass': 0.34, 'mid': 0.33, 'treble': 0.33, 'zcr': 0.08, 'centroid': 0.0,
         'onset_count': 1.0, 'bands': None, 'spectral_flux': 0.1,
         'vocal_hnr': 0.0, 'vocal_fmr': 0.0}
        for i in range(6)
    ])
    app = SimpleNamespace(vj_api=_FakeVjApiNoBpm(), _audio_manager=_FakeManager('house'))
    stub = SimpleNamespace(
        _now=lambda: now,
        _app=app,
        _grid=SimpleNamespace(bpm=124.0, confidence=0.5, downbeat_confidence=0.4, top_candidates=[]),
        _engine=_FakeEngine(),
        _profile_auto_reco_enabled=True,
        _profile_auto_reco_eval_interval_s=0.0,
        _profile_auto_reco_window_s=60.0,
        _profile_auto_reco_confirm_wins=1,
        _profile_auto_reco_score_margin=0.0,
        _reco_last_eval_t=-1e9,
        _reco_samples=samples,
        _reco_candidate_key='', _reco_candidate_wins=0,
        _recommended_profile_key='', _recommended_profile_name='', _recommended_profile_range='',
        _recommended_profile_score=0.0, _recommended_profile_confirmed=False,
        _current_profile_score=0.0, _current_profile_scored=False,
        _last_onset_count=1.0,
        _kick_energies=deque(maxlen=16),
        _compute_kick_regularity=lambda: 0.0,
        _reco_weights=dict(_AUTO_VJ._DEFAULT_RECO_WEIGHTS),
        _has_bpm_lock=lambda *a, **kw: True,
        _now_playing_telemetry_snapshot=lambda: {},
        _maybe_apply_recommended_audio_profile=lambda **kw: None,
        _sequence_corpus_writer=None,
        _record_sequence_keyframe=lambda *a, **kw: None,
    )
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33, treble=0.33,
                             spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)
    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})
    event, kw = stub._engine.marks[0]
    live_terms = kw['term_values_by_candidate']['house']

    # The spy proves the call actually happened, with the documented
    # features keys, and that its real return value (computed with
    # whatever aggregates _update_profile_recommendation built,
    # including the sample it appends from `audio` -- not reproduced by
    # hand here) is exactly what reached term_values_by_candidate.
    assert len(calls) == 1
    assert set(calls[0].keys()) == {
        'log2_bpms', 'mean_zcr', 'onset_density', 'mean_vocal_hnr',
        'mean_vocal_fmr', 'mean_contrast', 'top_cand_log2s', 'band_mean_vec',
        'raw_kick_regularity', 'kick_regularity_valid',
    }
    _, real_terms = real_score_fn(
        calls[0], restricted, stub._reco_weights, profiles_mod.SPECTRAL_SHAPE_SHARED_SIGMA,
    )['house']
    for name, value in real_terms.items():
        assert live_terms[name] == round(float(value), 4), name


def test_serialize_reco_features_round_trips_through_score_profile_candidates() -> None:
    """2026-09-11 (auto-vj-01 rc.142): `_serialize_reco_features()`'s
    whole purpose is to let the offline own-wins instrument re-score a
    LOGGED eval's exact input instead of reconstructing it from raw
    corpus rows -- three reconstruction attempts (disjoint 16s chunks,
    a naive sliding window, a crossfade-guarded sliding window) topped
    out at 41%/34%/30.5% agreement against the live recommender's own
    decision on the same rows. This pins the round trip: serialize a
    features dict, rebuild it exactly as the offline instrument would
    (JSON round trip included, since that's the real path), and confirm
    score_profile_candidates() returns the identical winner and
    composite as scoring the ORIGINAL (unserialized) features."""
    import json as _json
    import numpy as _np

    profile = _make_profile(
        expected_bands=[0.5] * 64, expected_bands_sigma=[0.1] * 64,
        zcr_mu=0.08, zcr_sigma=0.02,
    )
    profiles = {'synthetic': profile}
    weights = {'zcr_fit': 1.0, 'spectral_shape_fit': 0.7}
    band_vec = _np.array([0.5] * 64, dtype=_np.float32)
    features = _empty_features(mean_zcr=0.08, band_mean_vec=band_vec)

    serialized = _AUTO_VJ._serialize_reco_features(features, profiles)
    # The real path: this dict is written to JSONL and read back later.
    round_tripped = _json.loads(_json.dumps(serialized))

    rebuilt_features = {
        'log2_bpms': [tuple(x) for x in round_tripped['log2_bpms']],
        'mean_zcr': round_tripped['mean_zcr'],
        'onset_density': round_tripped['onset_density'],
        'mean_vocal_hnr': round_tripped['mean_vocal_hnr'],
        'mean_vocal_fmr': round_tripped['mean_vocal_fmr'],
        'mean_contrast': round_tripped['mean_contrast'],
        'top_cand_log2s': [tuple(x) for x in round_tripped['top_cand_log2s']],
        'band_mean_vec': _np.array(round_tripped['band_mean_vec']) if round_tripped['band_mean_vec'] else None,
        'raw_kick_regularity': round_tripped['raw_kick_regularity'],
        'kick_regularity_valid': round_tripped['kick_regularity_valid'],
    }
    # Only one profile ('synthetic') was in the eligible set passed to
    # _serialize_reco_features above, so eligible_profiles round-trips
    # to exactly that one key; map it back to the same profile object.
    assert round_tripped['eligible_profiles'] == ['synthetic']
    rebuilt_profiles = {'synthetic': profile}

    original_composite, _ = _AUTO_VJ.score_profile_candidates(
        features, profiles, weights, [0.1] * 64)['synthetic']
    rebuilt_composite, _ = _AUTO_VJ.score_profile_candidates(
        rebuilt_features, rebuilt_profiles, weights, [0.1] * 64)['synthetic']
    assert original_composite == rebuilt_composite
