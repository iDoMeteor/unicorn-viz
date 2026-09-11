"""2026-09-04 (recommender rc.28): spectral_shape_fit's "ribbon" redesign.
2026-09-11 (recommender rc.47): "shared-sigma" fix, superseding rc.28's
per-profile dispatch entirely.

`_profile_score()` (drop-ins/auto-vj-01/auto_vj.py) scores every
candidate's `spectral_shape_fit` via a per-band Gaussian log-density
against its OWN `expected_bands` as mu, but against ONE roster-wide
`SPECTRAL_SHAPE_SHARED_SIGMA` (unicornviz/audio/profiles.py) for every
candidate -- never each profile's own `expected_bands_sigma`, which is
telemetry only now. rc.28's two-path dispatch (a profile with its own
`expected_bands_sigma` used the ribbon Gaussian; a profile without one
fell back to legacy cosine similarity) is gone: every profile with
`expected_bands` set now scores via the same shared-sigma ribbon path,
whether or not it carries its own sigma. See docs/adr/vj-system.md
"Shared Per-Band Sigma for spectral_shape_fit" for the full diagnosis
(comparing per-candidate log-densities with different sigmas is a
model-selection problem under misspecification -- the broadest sigma
wins by default regardless of shape) and methodology this replaces.

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
        _compute_kick_regularity=lambda: 0.0,
        _reco_weights=weights,
        _has_bpm_lock=lambda *a, **kw: True,
        _now_playing_telemetry_snapshot=lambda: {},
        _maybe_apply_recommended_audio_profile=lambda **kw: None,
        _sequence_corpus_writer=None,
        _record_sequence_keyframe=lambda *a, **kw: None,
    ))


def _make_profiles(monkeypatch, *, with_own_sigma: list[float] | None, other_mu: float = 0.5):
    """Two synthetic profiles restricted into PROFILES: 'sigma_profile'
    (mu=0.5 everywhere, own expected_bands_sigma = `with_own_sigma`, which
    rc.47 no longer reads for scoring -- only kept to prove it's ignored)
    and 'other_profile' (a different mu, no expected_bands_sigma of its
    own at all -- the hand-authored-profile case). Both must score via
    the SAME shared sigma regardless of what they carry themselves."""
    import unicornviz.audio.profiles as profiles_mod
    base = profiles_mod.PROFILES['house']
    sigma_profile = profiles_mod.AudioProfile(
        name='Sigma', description='', bass_min=base.bass_min, bass_max=base.bass_max,
        mid_min=base.mid_min, mid_max=base.mid_max, treble_min=base.treble_min,
        treble_max=base.treble_max, expected_bands=[0.5] * 64,
        expected_bands_sigma=with_own_sigma,
    )
    other_profile = profiles_mod.AudioProfile(
        name='Other', description='', bass_min=base.bass_min, bass_max=base.bass_max,
        mid_min=base.mid_min, mid_max=base.mid_max, treble_min=base.treble_min,
        treble_max=base.treble_max, expected_bands=[other_mu] * 64,
        expected_bands_sigma=None,
    )
    restricted = {'sigma_profile': sigma_profile, 'other_profile': other_profile}
    monkeypatch.setattr(profiles_mod, 'PROFILES', restricted)
    monkeypatch.setattr(profiles_mod, 'enabled_profiles', lambda: restricted)
    return restricted


def test_own_expected_bands_sigma_no_longer_affects_scoring(monkeypatch) -> None:
    """Two profiles with the IDENTICAL mu but wildly different OWN
    expected_bands_sigma (one tight, one wide, one None) must score
    IDENTICALLY -- rc.47's whole point is that per-profile sigma no
    longer feeds spectral_shape_fit at all, only the shared roster
    vector does."""
    import unicornviz.audio.profiles as profiles_mod
    base = profiles_mod.PROFILES['house']
    far_bands = np.array([0.1] * 64, dtype=np.float64)

    def _score_with(sigma):
        p = profiles_mod.AudioProfile(
            name='P', description='', bass_min=base.bass_min, bass_max=base.bass_max,
            mid_min=base.mid_min, mid_max=base.mid_max, treble_min=base.treble_min,
            treble_max=base.treble_max, expected_bands=[0.5] * 64, expected_bands_sigma=sigma,
        )
        restricted = {'sigma_profile': p}
        monkeypatch.setattr(profiles_mod, 'PROFILES', restricted)
        monkeypatch.setattr(profiles_mod, 'enabled_profiles', lambda: restricted)
        stub = _stub_with_bands(far_bands)
        audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                                 treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)
        _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})
        event, kw = stub._engine.marks[0]
        return kw['term_values_by_candidate']['sigma_profile']['spectral_shape_fit']

    tight = _score_with([0.02] * 64)
    wide = _score_with([0.9] * 64)
    none_ = _score_with(None)
    assert tight == wide == none_, (tight, wide, none_)


def test_far_mismatch_scores_lower_than_close_match(monkeypatch) -> None:
    """Sanity check the shared-sigma ribbon path still discriminates fit
    quality: a band vector far from mu scores well below one close to
    mu, both against the same shared sigma."""
    _make_profiles(monkeypatch, with_own_sigma=None)
    close_bands = np.array([0.505] * 64, dtype=np.float64)
    far_bands = np.array([0.05] * 64, dtype=np.float64)

    def _score(bands):
        stub = _stub_with_bands(bands)
        audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                                 treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)
        _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})
        event, kw = stub._engine.marks[0]
        return kw['term_values_by_candidate']['sigma_profile']['spectral_shape_fit']

    close_val = _score(close_bands)
    far_val = _score(far_bands)
    assert far_val < close_val, (far_val, close_val)
    assert close_val > -0.1, close_val  # x is small, -0.5*x*x near 0


def test_profile_without_own_sigma_still_uses_the_ribbon_path(monkeypatch) -> None:
    """A profile with expected_bands but no expected_bands_sigma of its
    own (every hand-authored profile: psytrance, hard_techno, hardstyle,
    synthwave) must score via the shared-sigma ribbon path now, not the
    old legacy cosine fallback -- rc.47 removed that dispatch entirely.
    A cosine value is bounded to roughly [-2, 0] ((sim-0.5)*2 for
    sim in [-1,1]); the ribbon path's -0.5*x*x is unbounded below that
    for a large enough mismatch relative to the shared sigma, which is
    the discriminator this test checks for."""
    _make_profiles(monkeypatch, with_own_sigma=None, other_mu=0.9)
    far_bands = np.array([0.02] * 64, dtype=np.float64)
    stub = _stub_with_bands(far_bands)
    stub._app._audio_manager = _FakeManager('other_profile')
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    event, kw = stub._engine.marks[0]
    other_val = kw['term_values_by_candidate']['other_profile']['spectral_shape_fit']
    assert other_val < -2.0, other_val  # past the old cosine path's floor of ~-2.0
