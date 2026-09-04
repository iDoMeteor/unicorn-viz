"""Regression test for routing the profile recommender's spectral fit
fields (mean_zcr/mean_centroid/onset_density) into the sequence-corpus
training feed, not just the decision log.

2026-08-07: `_update_profile_recommendation()` always wrote a
`profile_recommendation` decision-log event via `self._engine.mark(...)`,
but never called `_record_sequence_keyframe()` -- so
`package_training_set.py`'s `_build_recommender_payload`, which filters
the sequence corpus for `event_type == 'profile_recommendation'` to build
its spectral-features summary, always found zero matching rows. Confirmed
against a live 18.5MB session corpus before the fix. See
docs/adr/vj-system.md for the write-up.
"""
from __future__ import annotations

import importlib.util
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace

_REPO = Path(__file__).resolve().parents[1]
_AUTO_VJ_PATH = _REPO / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_AUTO_VJ = _load_module(_AUTO_VJ_PATH, 'test_reco_corpus_routing_auto_vj')


class _FakeVjApiNoBpm:
    def get_bpm(self, exclude: str = '') -> float:
        return 0.0


class _FakeManager:
    def __init__(self, profile_key: str) -> None:
        self._profile_key = profile_key

    def get_profile_key(self) -> str:
        return self._profile_key


class _FakeEngine:
    def __init__(self) -> None:
        self.marks: list[tuple[str, dict]] = []

    def mark(self, event: str, **kw) -> None:
        self.marks.append((event, kw))


class _RecordingKeyframeSink:
    """Captures _record_sequence_keyframe() calls in place of the real
    sequence-corpus writer, so the test can assert on exactly what would
    have been appended."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object, object, dict]] = []

    def __call__(self, event_type: str, state, audio, spotify, **extra) -> None:
        self.calls.append((event_type, state, audio, spotify, extra))


def _make_stub(*, bpm: float = 124.0, centroid: float = 2000.0, zcr: float = 0.08,
                onset_count: float = 2.0, n_samples: int = 6) -> tuple[SimpleNamespace, _RecordingKeyframeSink]:
    app = SimpleNamespace(vj_api=_FakeVjApiNoBpm(), _audio_manager=_FakeManager('house'))
    now = time.monotonic()
    samples = deque([
        {'t': now - (n_samples - i) * 0.5, 'bpm': bpm, 'conf': 0.5, 'dconf': 0.4, 'locked': True,
         'bass': 0.34, 'mid': 0.33, 'treble': 0.33, 'zcr': zcr, 'centroid': centroid,
         'onset_count': onset_count, 'bands': None, 'spectral_flux': 0.1,
         'vocal_hnr': 0.1, 'vocal_fmr': 0.2}
        for i in range(n_samples)
    ])
    sink = _RecordingKeyframeSink()
    stub = SimpleNamespace(
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
        _now_playing_telemetry_snapshot=lambda: {},
        _maybe_apply_recommended_audio_profile=lambda **kw: None,
        _sequence_corpus_writer=object(),  # non-None: a real writer would be live
        _record_sequence_keyframe=sink,
    )
    # Phase B clock seam (2026-08-18): recommender eval timestamps now read
    # self._now(); the real method's getattr-defensive fallback keeps the
    # pre-seam time.monotonic() semantics for this bare stub.
    stub._now = lambda: _AUTO_VJ.AutoVJController._now(stub)
    return stub, sink


def test_profile_recommendation_writes_a_sequence_corpus_keyframe() -> None:
    stub, sink = _make_stub()
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)
    state = SimpleNamespace(effect_name='Tron Grid')
    spotify = {'available': True}

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, state, spotify)

    assert len(sink.calls) == 1
    event_type, got_state, got_audio, got_spotify, fields = sink.calls[0]
    assert event_type == 'profile_recommendation'
    assert got_state is state
    assert got_audio is audio
    assert got_spotify is spotify


def test_sequence_corpus_keyframe_carries_the_spectral_fit_fields() -> None:
    """The whole point of the fix: mean_zcr/mean_centroid/onset_density
    must actually reach the sequence-corpus row, matching what
    package_training_set.py's _build_recommender_payload expects to find
    on a profile_recommendation-typed row."""
    stub, sink = _make_stub(centroid=2200.0, zcr=0.12, onset_count=3.0)
    # audio.waveform/fft are both None, so the call appends one fresh
    # centroid=0.0/zcr=0.0 sample to the 6 pre-seeded ones before
    # averaging -- the expected mean is diluted accordingly (7 samples,
    # not 6). That's real, correct behavior (the live sample is part of
    # the window), not a test artifact.
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    _, _, _, _, fields = sink.calls[0]
    assert fields['mean_centroid'] == round(6 * 2200.0 / 7, 1)
    assert fields['mean_zcr'] == round(6 * 0.12 / 7, 4)
    assert fields['onset_density'] > 0.0
    assert 'term_spread' in fields
    assert 'recommended_profile_key' in fields
    assert 'score_margin' in fields
    assert 'mean_confidence' in fields


def test_sequence_corpus_keyframe_matches_the_decision_log_event_fields() -> None:
    """Both destinations should agree on the core recommendation fields --
    the corpus row isn't a different, drifted view of the same cycle."""
    stub, sink = _make_stub()
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    decision_log_event, decision_log_fields = stub._engine.marks[0]
    assert decision_log_event == 'profile_recommendation'
    _, _, _, _, corpus_fields = sink.calls[0]
    assert corpus_fields['recommended_profile_key'] == decision_log_fields['recommended_profile_key']
    assert corpus_fields['mean_zcr'] == decision_log_fields['mean_zcr']
    assert corpus_fields['mean_centroid'] == decision_log_fields['mean_centroid']
    assert corpus_fields['onset_density'] == decision_log_fields['onset_density']


def test_no_keyframe_written_when_recommender_disabled() -> None:
    stub, sink = _make_stub()
    stub._profile_auto_reco_enabled = False
    audio = SimpleNamespace(waveform=None, fft=None, bands=None, bass=0.34, mid=0.33,
                             treble=0.33, spectral_flux=0.1, vocal_hnr=0.0, vocal_fmr=0.0)

    _AUTO_VJ.AutoVJController._update_profile_recommendation(stub, audio, SimpleNamespace(), {})

    assert sink.calls == []
