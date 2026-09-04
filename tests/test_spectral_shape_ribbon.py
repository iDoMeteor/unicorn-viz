"""2026-09-04 (recommender rc.28): spectral_shape_fit's "ribbon" redesign.

`_profile_score()` (drop-ins/auto-vj-01/auto_vj.py) now takes two paths for
this term: a profile with `expected_bands_sigma` set scores via a per-band
Gaussian log-density against `expected_bands` as mu (mean across 64 bands,
mirroring every other `*_fit` term's `-0.5*x*x` shape); a profile with only
`expected_bands` (no sigma) keeps the legacy cosine-similarity path
unchanged. See docs/adr/vj-system.md "Spectral-Shape Ribbon Redesign" for
the full diagnosis and methodology this replaces.

Reuses the `_make_full_reco_stub`/`_bind_now` harness pattern already
established in test_bpm_detector_audit_regressions.py.
"""
from __future__ import annotations

import importlib.util
import time
from collections import deque
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


_AUTO_VJ = _load_module(_AUTO_VJ_PATH, 'test_spectral_shape_ribbon_auto_vj')


class _FakeVjApiNoBpm:
    def is_user_busy(self) -> bool:
        return False

    def get_bpm(self):
        return None

    def get_section(self):
        return None

    def get_track_path(self):
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


def _bind_now(stub: SimpleNamespace) -> SimpleNamespace:
    stub._now = lambda: _AUTO_VJ.AutoVJController._now(stub)
    return stub


def _stub_with_bands(band_vec: np.ndarray, n_samples: int = 6) -> SimpleNamespace:
    app = SimpleNamespace(vj_api=_FakeVjApiNoBpm(), _audio_manager=_FakeManager('sigma_profile'))
    now = time.monotonic()
    samples = deque([
        {'t': now - (n_samples - i) * 0.5, 'bpm': 0.0, 'conf': 0.5, 'dconf': 0.4, 'locked': True,
         'bass': 0.34, 'mid': 0.33, 'treble': 0.33, 'zcr': 0.0, 'centroid': 0.0,
         'onset_count': 0.0, 'bands': band_vec.astype(np.float32), 'spectral_flux': 0.1,
         'vocal_hnr': 0.0, 'vocal_fmr': 0.0}
        for i in range(n_samples)
    ])
    weights = dict(_AUTO_VJ._DEFAULT_RECO_WEIGHTS)
    weights['spectral_shape_fit'] = 1.0  # isolate this term's own raw value
    return _bind_now(SimpleNamespace(
        _app=app,
        _grid=SimpleNamespace(bpm=0.0, confidence=0.5, downbeat_confidence=0.4, top_candidates=[]),
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
        _last_onset_count=0.0,
        _kick_energies=deque(maxlen=16),
        _reco_weights=weights,
        _has_bpm_lock=lambda *a, **kw: True,
        _now_playing_telemetry_snapshot=lambda: {},
        _maybe_apply_recommended_audio_profile=lambda **kw: None,
        _sequence_corpus_writer=None,
        _record_sequence_keyframe=lambda *a, **kw: None,
    ))


def _make_profiles(monkeypatch, sigma_profile_sigma):
    """Two synthetic profiles restricted into PROFILES: 'sigma_profile' (has
    expected_bands_sigma -- ribbon path) and 'cosine_profile' (expected_bands
    only -- legacy cosine path). Both share the SAME expected_bands (mu) so
    any difference in scoring behavior is attributable to the path taken,
    not to a different target."""
    import unicornviz.audio.profiles as profiles_mod
    base = profiles_mod.PROFILES['house']
    mu = [0.5] * 64
    sigma_profile = profiles_mod.AudioProfile(
        name='Sigma', description='', bass_min=base.bass_min, bass_max=base.bass_max,
        mid_min=base.mid_min, mid_max=base.mid_max, treble_min=base.treble_min,
        treble_max=base.treble_max, expected_bands=list(mu),
        expected_bands_sigma=sigma_profile_sigma,
    )
    cosine_profile = profiles_mod.AudioProfile(
        name='Cosine', description='', bass_min=base.bass_min, bass_max=base.bass_max,
        mid_min=base.mid_min, mid_max=base.mid_max, treble_min=base.treble_min,
        treble_max=base.treble_max, expected_bands=list(mu),
        expected_bands_sigma=None,
    )
    restricted = {'sigma_profile': sigma_profile, 'cosine_profile': cosine_profile}
    monkeypatch.setattr(profiles_mod, 'PROFILES', restricted)
    monkeypatch.setattr(profiles_mod, 'enabled_profiles', lambda: restricted)
    return restricted


def test_ribbon_path_scores_below_cosine_floor_for_a_far_mismatch(monkeypatch) -> None:
    """A band vector far from mu (0.5 everywhere) should score very
    differently under the two paths: cosine similarity is bounded to
    [-1, 1] before weighting (`(sim - 0.5) * 2.0` where sim in [-1,1] --
    if sim is near 0, this reads ~-1.0), so the profile using it can never
    score below roughly -1.0 raw. The ribbon path's per-band Gaussian
    log-density has no such floor -- a large deviation relative to a tight
    sigma can push it far more negative, since it is exactly the -0.5*x*x
    shape every other *_fit term already uses, unbounded except by the
    shared 6-sigma clip. Confirms the two profiles' terms come out
    genuinely different (not just relabeled), which is the whole point of
    the dispatch added in _profile_score()."""
    tight_sigma = [0.05] * 64
    _make_profiles(monkeypatch, tight_sigma)
    far_bands = np.array([0.05] * 64, dtype=np.float64)  # far from mu=0.5 everywhere
    stub = _stub_with_bands(far_bands)
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    event, kw = stub._engine.marks[0]
    terms = kw['term_values_by_candidate']
    sigma_val = terms['sigma_profile']['spectral_shape_fit']
    cosine_val = terms['cosine_profile']['spectral_shape_fit']
    assert cosine_val >= -1.0 - 1e-9, cosine_val   # cosine path's own floor
    assert sigma_val < cosine_val, (sigma_val, cosine_val)   # ribbon path punishes harder
    assert sigma_val < -1.0, sigma_val   # actually breaks past cosine's floor


def test_ribbon_path_scores_near_zero_for_a_close_match(monkeypatch) -> None:
    """A band vector very close to mu should score near 0.0 under the
    ribbon path (small x in -0.5*x*x) -- confirms the path isn't just
    "always more negative than cosine," it genuinely reflects fit quality."""
    tight_sigma = [0.05] * 64
    _make_profiles(monkeypatch, tight_sigma)
    close_bands = np.array([0.505] * 64, dtype=np.float64)  # 0.1 sigma off
    stub = _stub_with_bands(close_bands)
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    event, kw = stub._engine.marks[0]
    terms = kw['term_values_by_candidate']
    sigma_val = terms['sigma_profile']['spectral_shape_fit']
    assert sigma_val > -0.02, sigma_val   # x = 0.1, -0.5*0.1^2 = -0.005


def test_profile_without_sigma_falls_back_to_cosine(monkeypatch) -> None:
    """A profile with expected_bands but no expected_bands_sigma (every
    hand-authored profile this redesign hasn't reached: psytrance,
    hard_techno, hardstyle, synthwave) must keep scoring via cosine
    similarity, bounded to the pre-redesign [-1, 1] range before
    weighting -- this redesign is additive/opt-in per profile, not a
    behavior change for profiles with no ribbon data."""
    _make_profiles(monkeypatch, [0.05] * 64)
    bands = np.array([0.1] * 64, dtype=np.float64)
    stub = _stub_with_bands(bands)
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    event, kw = stub._engine.marks[0]
    cosine_val = kw['term_values_by_candidate']['cosine_profile']['spectral_shape_fit']
    assert -1.0 - 1e-9 <= cosine_val <= 1.0 + 1e-9, cosine_val
