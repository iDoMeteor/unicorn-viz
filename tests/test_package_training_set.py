"""Regression tests for tools/package_training_set.py."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'training-kit-01' / 'tools' / 'package_training_set.py'
_SPEC = importlib.util.spec_from_file_location('package_training_set', _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

_build_detector_payload = _MOD._build_detector_payload
_song_key = _MOD._song_key
_run_llm_scoring = _MOD._run_llm_scoring
_detect_llm_provider = _MOD._detect_llm_provider
_load_dotenv_fallback = _MOD._load_dotenv_fallback
_score_lock_quality = _MOD._score_lock_quality
_BPM_LOCK_CONFIDENCE_FLOOR = _MOD._BPM_LOCK_CONFIDENCE_FLOOR
_cleanup_stale_empty_corpus_files = _MOD._cleanup_stale_empty_corpus_files
_load_profile_expected_values = _MOD._load_profile_expected_values
_format_profile_expected_values_block = _MOD._format_profile_expected_values_block
_build_combined_prompt = _MOD._build_combined_prompt
_build_recommender_payload = _MOD._build_recommender_payload
_mean_field = _MOD._mean_field
_format_reco_weights_line = _MOD._format_reco_weights_line
_RECO_WEIGHT_DEFAULTS = _MOD._RECO_WEIGHT_DEFAULTS
_load_live_reco_weights = _MOD._load_live_reco_weights
_map_genre_tag_to_profile_key = _MOD._map_genre_tag_to_profile_key
_build_recommender_accuracy = _MOD._build_recommender_accuracy
_format_recommender_accuracy_block = _MOD._format_recommender_accuracy_block
_build_shadow_comparison = _MOD._build_shadow_comparison
_summarize_engine_versions = _MOD._summarize_engine_versions
_load_live_detector_constants = _MOD._load_live_detector_constants
_load_live_director_constants = _MOD._load_live_director_constants
_DETECTOR_CONSTANT_DEFAULTS = _MOD._DETECTOR_CONSTANT_DEFAULTS
_DIRECTOR_CONSTANT_DEFAULTS = _MOD._DIRECTOR_CONSTANT_DEFAULTS
_format_constants_line = _MOD._format_constants_line
_format_tuning_recommendations_md = _MOD._format_tuning_recommendations_md
_build_director_payload = _MOD._build_director_payload
_extract_director_events = _MOD._extract_director_events
_write_scorecard = _MOD._write_scorecard
_write_mixer_crossref_report = _MOD._write_mixer_crossref_report
_parse_args = _MOD._parse_args
_append_session_log = _MOD._append_session_log
_mixer_bpm_for_path = _MOD._mixer_bpm_for_path
_MIXER_CROSSREF_SOURCES = _MOD._MIXER_CROSSREF_SOURCES

_CORPUS_PATTERNS = [
    'live-corpus*.jsonl', 'live-autovj*.jsonl', 'live*.jsonl',
    'sequence-corpus*.jsonl', 'sequence*.jsonl',
]


def _make_seq_row(
    track_id: str = 'track_001',
    title: str = 'Test Track',
    artist: str = 'Test Artist',
    bpm: float = 124.0,
    confidence: float = 0.72,
    beat_index: int = 4,
    event_type: str | None = None,
    ts: str = '2026-06-20T10:00:00',
    mixer_bpm: float | None = None,
    track_path: str = '',
    is_playing: bool = True,
    bpm_locked: bool | None = None,
) -> dict:
    row: dict = {
        'spotify_track_id': track_id,
        'spotify_title': title,
        'spotify_artist': artist,
        'spotify_album': 'Test Album',
        'bpm': bpm,
        'bpm_confidence': confidence,
        'beat_index': beat_index,
        'analysis_generated_at': ts,
        'is_playing': is_playing,
        # 2026-08-14, round three: bpm_locked (the real Schmidt-trigger
        # state) defaults to mirroring the stateless confidence-floor
        # check when not given explicitly, so existing tests that vary
        # `confidence` to simulate locked/unlocked rows keep behaving as
        # they always did -- see _lock_pct_stateful() in the module.
        'bpm_locked': bpm_locked if bpm_locked is not None else confidence >= _BPM_LOCK_CONFIDENCE_FLOOR,
    }
    if event_type:
        row['event_type'] = event_type
    if mixer_bpm is not None:
        row['mixer_bpm'] = mixer_bpm
    if track_path:
        row['track_path'] = track_path
    return row


_trim_idle_bookends = _MOD._trim_idle_bookends
_lock_pct_stateful = _MOD._lock_pct_stateful
_warn_if_essentia_unavailable = _MOD._warn_if_essentia_unavailable
_essentia_required_but_missing = _MOD._essentia_required_but_missing


# ---- _trim_idle_bookends (2026-08-14, round three; 2026-08-16: is_playing -> bpm > 0) --


def test_trim_idle_bookends_drops_leading_and_trailing_idle_rows() -> None:
    rows = (
        [_make_seq_row(bpm=0.0) for _ in range(3)]
        + [_make_seq_row(bpm=124.0) for _ in range(5)]
        + [_make_seq_row(bpm=0.0) for _ in range(4)]
    )
    trimmed = _trim_idle_bookends(rows)
    assert len(trimmed) == 5
    assert all(r['bpm'] > 0.0 for r in trimmed)


def test_trim_idle_bookends_preserves_a_real_mid_session_gap() -> None:
    """A genuine pause between tracks mid-session is real content (or at
    least not pre-roll/post-roll padding) -- must not be trimmed, only
    contiguous idle runs touching the very start/end."""
    rows = (
        [_make_seq_row(bpm=124.0) for _ in range(3)]
        + [_make_seq_row(bpm=0.0) for _ in range(2)]
        + [_make_seq_row(bpm=124.0) for _ in range(3)]
    )
    trimmed = _trim_idle_bookends(rows)
    assert len(trimmed) == 8
    assert trimmed == rows


def test_trim_idle_bookends_all_idle_returns_empty() -> None:
    rows = [_make_seq_row(bpm=0.0) for _ in range(4)]
    assert _trim_idle_bookends(rows) == []


def test_trim_idle_bookends_empty_input() -> None:
    assert _trim_idle_bookends([]) == []


def test_trim_idle_bookends_no_idle_rows_is_a_no_op() -> None:
    rows = [_make_seq_row(bpm=124.0) for _ in range(4)]
    assert _trim_idle_bookends(rows) == rows


def test_trim_idle_bookends_ignores_is_playing_now_that_bpm_gates_it() -> None:
    """2026-08-16: is_playing reflects whichever now-playing source is
    active (dj mixer/media/Spotify) and is unreliable when the real audio
    isn't coming from that source at all -- e.g. a web stream playing
    while an unused Spotify window sits open, paused. Real bpm > 0 is the
    source-independent signal now; is_playing=False must no longer trim a
    row that has a genuine detected tempo. Owner: "it's stupid that data
    collection was wired up only to support spotify.. we don't really
    even train on spotify, just verify." """
    rows = [_make_seq_row(bpm=124.0, is_playing=False) for _ in range(4)]
    assert _trim_idle_bookends(rows) == rows


def test_write_scorecard_excludes_idle_bookends_from_lock_coverage(tmp_path: Path) -> None:
    """Owner: 'fix the zero energy rows from the beginning & ends.' A
    session left idle (app open, nothing playing) before/after the real
    set must not count against beat_lock coverage -- confirmed via a
    scorecard built from rows that would score very differently with vs.
    without the idle padding."""
    rows = (
        [_make_seq_row(bpm=0.0, confidence=0.0) for _ in range(20)]
        + [_make_seq_row(bpm=124.0, confidence=0.9) for _ in range(5)]
        + [_make_seq_row(bpm=0.0, confidence=0.0) for _ in range(20)]
    )
    seq_path = tmp_path / 'sequence-corpus.jsonl'
    seq_path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
    live_path = tmp_path / 'live-corpus.jsonl'
    live_path.write_text('', encoding='utf-8')
    bucket_dir = tmp_path / 'set-a' / 'a'
    bucket_dir.mkdir(parents=True)

    scorecard_path, _lock, _director = _write_scorecard(bucket_dir, live_path, seq_path)

    content = scorecard_path.read_text(encoding='utf-8')
    assert 'Sequence rows: `5`' in content
    assert 'stateless proxy' in content and '`100.0%`' in content


# ---- _lock_pct_stateful (2026-08-14, round three) -----------------------------
# Owner: "let's fix that logging & packaging issue regarding lock state.. i want
# to be able to compare what we were using vs what we *should* be using."


def test_lock_pct_stateful_basic() -> None:
    rows = (
        [_make_seq_row(bpm_locked=True) for _ in range(3)]
        + [_make_seq_row(bpm_locked=False) for _ in range(1)]
    )
    assert _lock_pct_stateful(rows) == pytest.approx(75.0)


def test_lock_pct_stateful_empty_is_zero() -> None:
    assert _lock_pct_stateful([]) == 0.0


def test_lock_pct_stateful_diverges_from_the_stateless_proxy() -> None:
    """The whole point: a row can read as 'locked' under the stateless
    confidence-floor check while the real Schmidt-trigger state (with
    hysteresis) says otherwise, and vice versa -- these are genuinely
    different signals, not two ways of writing the same number."""
    rows = [
        _make_seq_row(confidence=0.9, bpm_locked=False),   # high confidence, but state says unlocked
        _make_seq_row(confidence=0.1, bpm_locked=True),    # low confidence, but hysteresis held the lock
    ]
    stateless = round(100.0 * sum(1 for r in rows if r['bpm_confidence'] >= 0.45) / len(rows), 1)
    stateful = round(_lock_pct_stateful(rows), 1)
    assert stateless == 50.0
    assert stateful == 50.0
    # Same aggregate by coincidence in this 2-row case, but which specific
    # rows count differs entirely -- confirm the two checks disagree on
    # individual rows, not just happen to share a coincidental average.
    stateless_per_row = [r['bpm_confidence'] >= 0.45 for r in rows]
    stateful_per_row = [bool(r['bpm_locked']) for r in rows]
    assert stateless_per_row != stateful_per_row


def test_write_scorecard_lock_rating_scores_against_stateful_not_stateless(tmp_path: Path) -> None:
    """A session with decent stateless confidence coverage but a real
    Schmidt-trigger state that was mostly unlocked must score LOW --
    "what we should be using," not the stateless proxy."""
    rows = [_make_seq_row(confidence=0.5, bpm_locked=False) for _ in range(20)]
    seq_path = tmp_path / 'sequence-corpus.jsonl'
    seq_path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
    live_path = tmp_path / 'live-corpus.jsonl'
    live_path.write_text('', encoding='utf-8')
    bucket_dir = tmp_path / 'set-a' / 'a'
    bucket_dir.mkdir(parents=True)

    _scorecard_path, lock_rating, _director = _write_scorecard(bucket_dir, live_path, seq_path)

    # confidence=0.5 clears the stateless 0.45 floor (would score well on
    # the old metric) but bpm_locked=False the whole session -- the
    # rating must reflect the real, mostly-unlocked state.
    assert lock_rating <= 2


# ---- _build_detector_payload ------------------------------------------------


def test_build_detector_payload_required_keys() -> None:
    rows = [_make_seq_row() for _ in range(10)]
    payload = _build_detector_payload(rows, 'set-a', 'a')
    for key in ('set_id', 'bucket_id', 'total_rows', 'song_count', 'time_range',
                 'bpm', 'confidence', 'beat_lock', 'per_song'):
        assert key in payload, f'missing key: {key}'
    assert payload['total_rows'] == 10
    assert payload['song_count'] == 1


def test_build_detector_payload_per_song_grouping_by_track_id() -> None:
    rows = (
        [_make_seq_row(track_id='aaa', title='Song A') for _ in range(5)]
        + [_make_seq_row(track_id='bbb', title='Song B') for _ in range(3)]
    )
    payload = _build_detector_payload(rows, 'set-a', 'a')
    assert payload['song_count'] == 2
    keys = {s['key'] for s in payload['per_song']}
    assert 'id:aaa' in keys
    assert 'id:bbb' in keys


def test_build_detector_payload_fallback_key_when_no_track_id() -> None:
    row = _make_seq_row()
    del row['spotify_track_id']
    payload = _build_detector_payload([row], 'set-a', 'a')
    assert payload['song_count'] == 1
    assert payload['per_song'][0]['key'].startswith('meta:')


def test_build_detector_payload_skips_fully_unidentified_rows() -> None:
    """A boundary/transition row with no track_id AND no title/artist (e.g.
    one captured right at a track change, before now-playing metadata
    populates) used to fall back to the literal key 'meta:||' and get
    reported as its own fake "song" -- caught live when it showed up as
    '### meta:||' in a real detector_score.md. Must be excluded from
    per_song and song_count, and counted in skipped_unidentified_rows."""
    real_row = _make_seq_row(track_id='aaa', title='Song A')
    stray_row = _make_seq_row()
    del stray_row['spotify_track_id']
    stray_row['spotify_title'] = ''
    stray_row['spotify_artist'] = ''

    payload = _build_detector_payload([real_row, stray_row], 'set-a', 'a')

    keys = {s['key'] for s in payload['per_song']}
    assert 'meta:||' not in keys
    assert payload['song_count'] == len(payload['per_song']) == 1
    assert payload['skipped_unidentified_rows'] == 1


def test_build_detector_payload_lock_coverage() -> None:
    locked_rows = [_make_seq_row(confidence=0.72) for _ in range(5)]
    unlocked_rows = [_make_seq_row(confidence=0.20) for _ in range(5)]
    payload = _build_detector_payload(locked_rows + unlocked_rows, 'set-a', 'a')
    assert payload['beat_lock']['coverage_pct'] == pytest.approx(50.0)


def test_build_detector_payload_lock_coverage_stateful_diverges_from_stateless() -> None:
    """2026-08-14, round three: coverage_pct_stateful (real bpm_locked
    state) and coverage_pct (stateless confidence-floor proxy) are
    genuinely different signals -- confirmed with an aggregate divergence,
    not just individual rows disagreeing while averaging out the same."""
    rows = (
        # Clears the stateless floor but the real hysteresis state says
        # unlocked for most of these (e.g. a brief, noisy confidence spike
        # that never actually flipped the Schmidt trigger).
        [_make_seq_row(confidence=0.9, bpm_locked=False) for _ in range(6)]
        + [_make_seq_row(confidence=0.9, bpm_locked=True) for _ in range(2)]
        # Below the stateless floor but the hysteresis held the lock from
        # before the dip.
        + [_make_seq_row(confidence=0.1, bpm_locked=True) for _ in range(2)]
    )
    payload = _build_detector_payload(rows, 'set-a', 'a')
    assert payload['beat_lock']['coverage_pct'] == pytest.approx(80.0)          # 8/10 clear the floor
    assert payload['beat_lock']['coverage_pct_stateful'] == pytest.approx(40.0)  # only 4/10 actually locked
    assert payload['per_song'][0]['lock_coverage_pct'] == pytest.approx(80.0)
    assert payload['per_song'][0]['lock_coverage_pct_stateful'] == pytest.approx(40.0)


def test_build_detector_payload_empty_rows() -> None:
    payload = _build_detector_payload([], 'set-a', 'a')
    assert payload['total_rows'] == 0
    assert payload['song_count'] == 0
    assert payload['beat_lock']['coverage_pct'] == 0.0


def test_build_detector_payload_set_description_included() -> None:
    rows = [_make_seq_row()]
    payload = _build_detector_payload(rows, 'set-a', 'a', set_description='House night baseline run.')
    assert payload['set_description'] == 'House night baseline run.'


# ---- _build_live_corpus_snapshot / detector payload wiring (2026-08-17) -----


def test_build_detector_payload_live_corpus_snapshot_defaults_empty() -> None:
    """No live_rows passed (or none available) -- empty list, not missing/None,
    so downstream JSON serialization and the prompt-note gate both behave
    predictably."""
    payload = _build_detector_payload([_make_seq_row()], 'set-a', 'a')
    assert payload['live_corpus_snapshot'] == []


def test_build_live_corpus_snapshot_skips_unidentified_and_idle_rows() -> None:
    """Owner: 'send the live corpus to llm as well, i thought we were sending
    *just* that to keep the package small.' Skips the no-identity
    __live__:<source> fallback row and the stopped/idle teardown snapshot
    LiveCorpusWriter leaves at session end -- neither says anything about a
    specific track."""
    live_rows = [
        {'track_title': '', 'track_artist': '', 'bpm': 125.0, 'is_playing': False, 'track_status': 'stopped'},
        {'track_title': 'Real Track', 'track_artist': 'Real Artist', 'bpm': 124.0,
         'bpm_confidence': 0.8, 'is_playing': True, 'track_status': 'PLAYING',
         'track_genre': 'House', 'profile': 'house'},
    ]
    snapshot = _MOD._build_live_corpus_snapshot(live_rows)
    assert len(snapshot) == 1
    assert snapshot[0]['title'] == 'Real Track'
    assert snapshot[0]['artist'] == 'Real Artist'
    assert snapshot[0]['bpm'] == 124.0
    assert snapshot[0]['bpm_confidence'] == 0.8
    assert snapshot[0]['track_genre'] == 'House'
    assert snapshot[0]['profile'] == 'house'


def test_build_detector_payload_includes_live_corpus_snapshot_when_provided() -> None:
    live_rows = [
        {'track_title': 'Live Track', 'track_artist': 'Live Artist', 'bpm': 128.0,
         'bpm_confidence': 0.9, 'is_playing': True, 'track_status': 'PLAYING'},
    ]
    payload = _build_detector_payload([_make_seq_row()], 'set-a', 'a', live_rows=live_rows)
    assert payload['live_corpus_snapshot'] == [{
        'title': 'Live Track', 'artist': 'Live Artist', 'bpm': 128.0,
        'bpm_confidence': 0.9, 'track_genre': None, 'profile': None,
    }]


def test_build_detector_payload_band_signal_summary() -> None:
    """2026-08-09: band_signal surfaces bass_n/mid_n/treble_n/bass_flux/
    mid_flux means and the real per-frame beat-onset rate -- data behind
    drop_score's band_blend rebalance and new bass_flux_norm term, both
    landed the same day as provisional starting points."""
    rows = []
    for i in range(4):
        row = _make_seq_row(track_id=f'track_{i}')
        row['bass_n'] = 0.8
        row['mid_n'] = 0.4
        row['treble_n'] = 0.2
        row['bass_flux'] = 2.0
        row['mid_flux'] = 1.0
        row['beat'] = 1.0 if i % 2 == 0 else 0.0
        rows.append(row)

    payload = _build_detector_payload(rows, 'set-a', 'a')

    assert payload['band_signal']['mean_bass_n'] == pytest.approx(0.8)
    assert payload['band_signal']['mean_mid_n'] == pytest.approx(0.4)
    assert payload['band_signal']['mean_treble_n'] == pytest.approx(0.2)
    assert payload['band_signal']['mean_bass_flux'] == pytest.approx(2.0)
    assert payload['band_signal']['mean_mid_flux'] == pytest.approx(1.0)
    assert payload['band_signal']['raw_beat_rate_pct'] == pytest.approx(50.0)


def test_build_detector_payload_band_signal_none_on_empty_rows() -> None:
    payload = _build_detector_payload([], 'set-a', 'a')
    assert payload['band_signal']['mean_bass_n'] is None


# ---- _build_detector_payload: mixer_bpm_median / essentia (2026-08-14, round three) --------


def test_build_detector_payload_mixer_bpm_median() -> None:
    rows = [
        _make_seq_row(bpm=124.0, mixer_bpm=125.0),
        _make_seq_row(bpm=124.2, mixer_bpm=125.5),
        _make_seq_row(bpm=124.1, mixer_bpm=125.0),
    ]
    payload = _build_detector_payload(rows, 'set-a', 'a')
    assert payload['per_song'][0]['mixer_bpm_median'] == pytest.approx(125.0)


def test_build_detector_payload_mixer_bpm_median_none_when_absent() -> None:
    rows = [_make_seq_row() for _ in range(3)]
    payload = _build_detector_payload(rows, 'set-a', 'a')
    assert payload['per_song'][0]['mixer_bpm_median'] is None


def test_build_detector_payload_mixer_bpm_median_ignores_zero_placeholder() -> None:
    """mixer_bpm defaults to 0.0 (see _build_live_training_row) when no
    external hint was available for a given row -- must not be counted as
    a real reading of 0 BPM."""
    rows = [
        _make_seq_row(mixer_bpm=0.0),
        _make_seq_row(mixer_bpm=0.0),
        _make_seq_row(mixer_bpm=126.0),
    ]
    payload = _build_detector_payload(rows, 'set-a', 'a')
    assert payload['per_song'][0]['mixer_bpm_median'] == pytest.approx(126.0)


def test_build_detector_payload_mixer_bpm_median_falls_back_to_track_store(monkeypatch) -> None:
    """2026-08-19: media-01/replay sessions never populate the live
    mixer_bpm field (no live broadcast to read) -- when a track_path is
    present, fall back to the same offline dj_mixer_tracks.json lookup
    _write_mixer_crossref_report() uses, so external_agreement isn't left
    with nothing at all just because the session wasn't dj-mixer-01."""
    monkeypatch.setattr(
        _MOD, '_load_mixer_track_store',
        lambda repo_root: ({'/music/track.mp3': {'hash': 'h1'}}, {'h1': {'bpm': 128.4}}),
    )
    rows = [_make_seq_row(track_path='/music/track.mp3') for _ in range(3)]
    payload = _build_detector_payload(rows, 'set-a', 'a')
    assert payload['per_song'][0]['mixer_bpm_median'] == pytest.approx(128.4)


def test_build_detector_payload_mixer_bpm_median_live_field_wins_over_store(monkeypatch) -> None:
    """A real dj-mixer-01 session already has the live mixer_bpm field --
    the store lookup must never override an already-populated value."""
    monkeypatch.setattr(
        _MOD, '_load_mixer_track_store',
        lambda repo_root: ({'/music/track.mp3': {'hash': 'h1'}}, {'h1': {'bpm': 999.0}}),
    )
    rows = [_make_seq_row(track_path='/music/track.mp3', mixer_bpm=125.0) for _ in range(3)]
    payload = _build_detector_payload(rows, 'set-a', 'a')
    assert payload['per_song'][0]['mixer_bpm_median'] == pytest.approx(125.0)


def test_build_detector_payload_mixer_bpm_median_none_when_store_has_no_entry(monkeypatch) -> None:
    monkeypatch.setattr(_MOD, '_load_mixer_track_store', lambda repo_root: ({}, {}))
    rows = [_make_seq_row(track_path='/music/unknown.mp3') for _ in range(3)]
    payload = _build_detector_payload(rows, 'set-a', 'a')
    assert payload['per_song'][0]['mixer_bpm_median'] is None


def test_build_detector_payload_essentia_fields_default_none_without_track_path() -> None:
    rows = [_make_seq_row() for _ in range(3)]
    payload = _build_detector_payload(rows, 'set-a', 'a')
    assert payload['per_song'][0]['essentia_bpm'] is None
    assert payload['per_song'][0]['essentia_key'] is None


def test_load_extract_audio_features_real_loader_returns_a_working_function(tmp_path: Path) -> None:
    """2026-08-14, round three, caught live: every other essentia test in
    this file mocks _load_extract_audio_features() entirely, so none of
    them ever exercised the real module-loading path -- which was
    silently broken the whole time real Essentia wiring was "live."
    training_lib.py defines a frozen+slots @dataclass; dataclasses looks
    itself up via sys.modules[cls.__module__] while the class body is
    still executing, and raises AttributeError on None if the loaded
    module was never registered in sys.modules first. Real-world
    evidence: a live session's essentia_bpm/essentia_key were None for
    every single song despite track_path being populated for nearly all
    17,683 rows. This test calls the REAL loader, unmocked, against the
    REAL training_lib.py -- a regression here means external_agreement
    goes silently dark again. Uses a synthetic WAV (the stdlib fallback
    path) so it passes whether or not Essentia itself is installed --
    the bug was in loading the module at all, not in Essentia specifically.
    """
    extract = _MOD._load_extract_audio_features()
    assert extract is not None, (
        'the real training_lib.py failed to load -- see the module-registration '
        'comment on _load_extract_audio_features()'
    )

    audio_path = tmp_path / 'tone.wav'
    sample_rate = 44_100
    t = np.arange(sample_rate, dtype=np.float32) / sample_rate
    samples = (0.2 * np.sin(2.0 * math.pi * 440.0 * t)).astype(np.float32)
    pcm = (samples * 32767).astype('<i2')
    with wave.open(str(audio_path), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())

    result = extract(audio_path)
    assert result['analysis_status'] == 'ok'
    assert result['duration_s'] > 0.0


def test_build_detector_payload_essentia_fields_default_none_when_file_missing(tmp_path: Path) -> None:
    """A track_path is present but the file doesn't actually exist on this
    machine (e.g. a corpus captured on a different machine/crate layout)
    -- must not raise, must leave essentia fields None."""
    rows = [_make_seq_row(track_path=str(tmp_path / 'does-not-exist.mp3'))]
    payload = _build_detector_payload(rows, 'set-a', 'a')
    assert payload['per_song'][0]['essentia_bpm'] is None
    assert payload['per_song'][0]['essentia_key'] is None


def test_build_detector_payload_essentia_fields_populated_when_extractor_available(
    tmp_path: Path, monkeypatch,
) -> None:
    """Mocks the extractor (same style as _load_live_detector_constants'
    own tests) -- real Essentia is a heavy optional dependency, not a unit
    test concern."""
    audio_file = tmp_path / 'track.mp3'
    audio_file.write_bytes(b'fake')

    def _fake_extract(path):
        assert Path(path) == audio_file
        return {'analysis_status': 'ok', 'bpm': 127.4, 'key': 'A', 'scale': 'minor'}

    monkeypatch.setattr(_MOD, '_load_extract_audio_features', lambda: _fake_extract)

    rows = [_make_seq_row(track_path=str(audio_file))]
    payload = _build_detector_payload(rows, 'set-a', 'a')
    assert payload['per_song'][0]['essentia_bpm'] == pytest.approx(127.4)
    assert payload['per_song'][0]['essentia_key'] == 'A minor'


def test_build_detector_payload_essentia_fields_none_when_extraction_fails(
    tmp_path: Path, monkeypatch,
) -> None:
    audio_file = tmp_path / 'track.mp3'
    audio_file.write_bytes(b'fake')

    def _raising_extract(path):
        raise RuntimeError('boom')

    monkeypatch.setattr(_MOD, '_load_extract_audio_features', lambda: _raising_extract)

    rows = [_make_seq_row(track_path=str(audio_file))]
    payload = _build_detector_payload(rows, 'set-a', 'a')
    assert payload['per_song'][0]['essentia_bpm'] is None
    assert payload['per_song'][0]['essentia_key'] is None


def test_build_detector_payload_essentia_fields_none_when_extractor_reports_failure(
    tmp_path: Path, monkeypatch,
) -> None:
    """analysis_status != 'ok' (e.g. corrupt/unreadable file) -- must not
    report a bogus bpm=0.0 as if it were a real reading."""
    audio_file = tmp_path / 'track.mp3'
    audio_file.write_bytes(b'fake')

    def _fake_extract(path):
        return {'analysis_status': 'error', 'bpm': 0.0, 'key': 'unknown', 'scale': 'unknown'}

    monkeypatch.setattr(_MOD, '_load_extract_audio_features', lambda: _fake_extract)

    rows = [_make_seq_row(track_path=str(audio_file))]
    payload = _build_detector_payload(rows, 'set-a', 'a')
    assert payload['per_song'][0]['essentia_bpm'] is None


# ---- _warn_if_essentia_unavailable (2026-08-14, round three) ------------------
# Owner: "why didn't essentia run?" -- root cause was packaging running under a
# Python without essentia installed, silently swallowed by extract_audio_
# features()'s own broad except. Owner: "yes please" (make it loud).


def _reset_essentia_warned_flag(monkeypatch) -> None:
    monkeypatch.setattr(_MOD, '_ESSENTIA_WARNED_THIS_PROCESS', False)


def test_warn_if_essentia_unavailable_no_op_without_track_path(monkeypatch, caplog) -> None:
    _reset_essentia_warned_flag(monkeypatch)
    monkeypatch.setattr('importlib.util.find_spec', lambda name: None)
    rows = [_make_seq_row()]  # no track_path
    with caplog.at_level('WARNING'):
        _warn_if_essentia_unavailable(rows)
    assert caplog.text == ''


def test_warn_if_essentia_unavailable_no_op_when_essentia_is_installed(monkeypatch, caplog) -> None:
    _reset_essentia_warned_flag(monkeypatch)
    monkeypatch.setattr('importlib.util.find_spec', lambda name: object())  # "found"
    rows = [_make_seq_row(track_path='/some/real/path.mp3')]
    with caplog.at_level('WARNING'):
        _warn_if_essentia_unavailable(rows)
    assert caplog.text == ''


def test_warn_if_essentia_unavailable_warns_once(monkeypatch, caplog) -> None:
    _reset_essentia_warned_flag(monkeypatch)
    monkeypatch.setattr('importlib.util.find_spec', lambda name: None)
    rows = [_make_seq_row(track_path='/some/real/path.mp3')]

    with caplog.at_level('WARNING'):
        _warn_if_essentia_unavailable(rows)
        _warn_if_essentia_unavailable(rows)  # second call: must not repeat

    warnings = [r for r in caplog.records if r.levelname == 'WARNING']
    assert len(warnings) == 1
    assert 'essentia' in warnings[0].message.lower()
    assert '.venv' in warnings[0].message


# ---- _essentia_required_but_missing (2026-08-19) -----------------------------


def test_essentia_required_but_missing_false_without_track_path(monkeypatch) -> None:
    monkeypatch.setattr('importlib.util.find_spec', lambda name: None)
    assert _essentia_required_but_missing([_make_seq_row()]) is False


def test_essentia_required_but_missing_false_when_essentia_installed(monkeypatch) -> None:
    monkeypatch.setattr('importlib.util.find_spec', lambda name: object())
    rows = [_make_seq_row(track_path='/some/real/path.mp3')]
    assert _essentia_required_but_missing(rows) is False


def test_essentia_required_but_missing_true_when_needed_and_absent(monkeypatch) -> None:
    monkeypatch.setattr('importlib.util.find_spec', lambda name: None)
    rows = [_make_seq_row(track_path='/some/real/path.mp3')]
    assert _essentia_required_but_missing(rows) is True


# ---- main() essentia pre-flight hard exit (2026-08-19) -----------------------
# Owner: "let's turn this from a warning into an exit please, i keep forgetting"
# -- a missing-venv session used to package fully with a silent warning
# (easy to scroll past); now it's a pre-flight hard exit, before set_dir/
# bucket_dir exist or anything is moved, so nothing needs undoing.


def _write_corpus_pair(corpus_dir: Path, *, with_track_path: bool) -> None:
    corpus_dir.mkdir(parents=True, exist_ok=True)
    live_row = {**_make_seq_row(), 'analysis_generated_at': '2026-08-19T10:00:00'}
    seq_row = _make_seq_row(track_path='/library/track.mp3' if with_track_path else '')
    (corpus_dir / 'live-corpus-20260819T100000.jsonl').write_text(
        json.dumps(live_row) + '\n', encoding='utf-8')
    (corpus_dir / 'sequence-corpus-20260819T100000.jsonl').write_text(
        json.dumps(seq_row) + '\n', encoding='utf-8')


def test_main_exits_before_touching_anything_when_essentia_missing(tmp_path: Path, monkeypatch) -> None:
    corpus_dir = tmp_path / 'corpus'
    logs_dir = tmp_path / 'logs'
    sets_root = tmp_path / 'sets'
    training_root = tmp_path / 'training'
    _write_corpus_pair(corpus_dir, with_track_path=True)

    monkeypatch.setattr(_MOD, '_detect_llm_provider', lambda: ('openai', 'fake-key'))
    monkeypatch.setattr(_MOD, '_essentia_required_but_missing', lambda rows: True)
    monkeypatch.setattr('sys.argv', [
        'package_training_set.py', '--no-prompt', '--playlist-name', 'p',
        '--corpus-dir', str(corpus_dir), '--logs-dir', str(logs_dir),
        '--sets-root', str(sets_root), '--training-root', str(training_root),
    ])

    rc = _MOD.main()

    assert rc == 1
    assert (corpus_dir / 'live-corpus-20260819T100000.jsonl').exists()
    assert (corpus_dir / 'sequence-corpus-20260819T100000.jsonl').exists()
    assert not sets_root.exists() or not any(sets_root.iterdir())


def test_main_skips_essentia_gate_with_skip_llm_scoring(tmp_path: Path, monkeypatch) -> None:
    """--skip-llm-scoring means essentia is never invoked either way --
    the pre-flight gate must not block a session that doesn't need it."""
    corpus_dir = tmp_path / 'corpus'
    logs_dir = tmp_path / 'logs'
    sets_root = tmp_path / 'sets'
    training_root = tmp_path / 'training'
    _write_corpus_pair(corpus_dir, with_track_path=True)

    monkeypatch.setattr(_MOD, '_essentia_required_but_missing',
                        lambda rows: (_ for _ in ()).throw(AssertionError('must not be called')))
    monkeypatch.setattr('sys.argv', [
        'package_training_set.py', '--no-prompt', '--playlist-name', 'p', '--skip-llm-scoring',
        '--corpus-dir', str(corpus_dir), '--logs-dir', str(logs_dir),
        '--sets-root', str(sets_root), '--training-root', str(training_root),
    ])

    rc = _MOD.main()

    assert rc == 0
    assert not (corpus_dir / 'live-corpus-20260819T100000.jsonl').exists()  # moved out
    moved = list(sets_root.glob('p/*/live-corpus-20260819T100000.jsonl'))
    assert len(moved) == 1


def test_main_skips_essentia_gate_without_api_key(tmp_path: Path, monkeypatch) -> None:
    """No LLM provider configured -- scoring (and essentia) never runs
    either way, so the gate must not block on that basis."""
    corpus_dir = tmp_path / 'corpus'
    logs_dir = tmp_path / 'logs'
    sets_root = tmp_path / 'sets'
    training_root = tmp_path / 'training'
    _write_corpus_pair(corpus_dir, with_track_path=True)

    monkeypatch.setattr(_MOD, '_detect_llm_provider', lambda: (None, None))
    monkeypatch.setattr(_MOD, '_essentia_required_but_missing',
                        lambda rows: (_ for _ in ()).throw(AssertionError('must not be called')))
    monkeypatch.setattr('sys.argv', [
        'package_training_set.py', '--no-prompt', '--playlist-name', 'p',
        '--corpus-dir', str(corpus_dir), '--logs-dir', str(logs_dir),
        '--sets-root', str(sets_root), '--training-root', str(training_root),
    ])

    rc = _MOD.main()

    assert rc == 0
    moved = list(sets_root.glob('p/*/live-corpus-20260819T100000.jsonl'))
    assert len(moved) == 1


# ---- main() logs-dir sweep excludes cross-session-shared paths (2026-09-01) ---
# Caught live: --logs-dir defaults to the whole repo logs/ tree, and the
# session-log sweep used to move (not copy) every file under it
# unconditionally -- including logs/replay/EXPERIMENT-2026-08-31.md, a
# concurrent session's gitignored working ledger with nothing to do with
# this packaging run, deleting it from its real location.

def test_main_logs_sweep_excludes_replay_subdir(tmp_path: Path, monkeypatch) -> None:
    corpus_dir = tmp_path / 'corpus'
    logs_dir = tmp_path / 'logs'
    sets_root = tmp_path / 'sets'
    training_root = tmp_path / 'training'
    _write_corpus_pair(corpus_dir, with_track_path=False)

    (logs_dir / 'replay').mkdir(parents=True)
    ledger = logs_dir / 'replay' / 'EXPERIMENT-2026-08-31.md'
    ledger.write_text('shared ledger content', encoding='utf-8')
    own_log = logs_dir / 'unicornviz_20260819_100000.log'
    own_log.write_text('session log content', encoding='utf-8')

    monkeypatch.setattr('sys.argv', [
        'package_training_set.py', '--no-prompt', '--playlist-name', 'p', '--skip-llm-scoring',
        '--corpus-dir', str(corpus_dir), '--logs-dir', str(logs_dir),
        '--sets-root', str(sets_root), '--training-root', str(training_root),
    ])

    rc = _MOD.main()

    assert rc == 0
    assert ledger.exists()                                  # untouched, not moved
    assert ledger.read_text(encoding='utf-8') == 'shared ledger content'
    assert not own_log.exists()                              # this session's own log still moved
    moved_own_log = list(sets_root.glob('p/*/unicornviz_20260819_100000.log'))
    assert len(moved_own_log) == 1


# ---- _build_recommender_payload ---------------------------------------------


def test_build_recommender_payload_vocal_summary() -> None:
    """2026-08-09: vocal_hnr/vocal_fmr now reach every sequence corpus row
    (previously only the coarser profile_recommendation events) -- feeds
    vocal_hnr_fit/vocal_fmr_fit, surfaced here at the denser granularity."""
    rows = []
    for i in range(3):
        row = _make_seq_row(track_id=f'track_{i}')
        row['vocal_hnr'] = 0.6
        row['vocal_fmr'] = 0.5
        rows.append(row)

    payload = _build_recommender_payload(rows, duration_min=10.0, set_id='set-a', bucket_id='a')

    assert payload['spectral_features']['vocal']['mean_vocal_hnr'] == pytest.approx(0.6)
    assert payload['spectral_features']['vocal']['mean_vocal_fmr'] == pytest.approx(0.5)
    assert payload['spectral_features']['vocal']['n_rows'] == 3


def test_build_recommender_payload_vocal_summary_absent_with_no_rows() -> None:
    payload = _build_recommender_payload([], duration_min=None, set_id='set-a', bucket_id='a')
    assert 'vocal' not in payload.get('spectral_summary', {})


# ---- _build_recommender_payload: matcher/prefilter engagement (2026-08-31) --
# hint_integration's real scoring basis post-genre-pure-rebalance -- see the
# prompt section's own comment for why raw hint_alignment_pct isn't it.


def test_build_recommender_payload_matcher_engagement_counters() -> None:
    rows = [
        {**_make_seq_row(track_id='a'), 'genre_matcher_endorse_count': 5,
         'reco_bpm_prefilter_excluded_count': 12, 'reco_bpm_prefilter_fallback_count': 0},
        {**_make_seq_row(track_id='a'), 'genre_matcher_endorse_count': 9,
         'reco_bpm_prefilter_excluded_count': 20, 'reco_bpm_prefilter_fallback_count': 1},
    ]
    payload = _build_recommender_payload(rows, duration_min=10.0, set_id='set-a', bucket_id='a')
    assert payload['stats']['genre_matcher_endorse_count'] == 9
    assert payload['stats']['reco_bpm_prefilter_excluded_count'] == 20
    assert payload['stats']['reco_bpm_prefilter_fallback_count'] == 1


def test_build_recommender_payload_matcher_engagement_counters_default_zero() -> None:
    rows = [_make_seq_row(track_id='a')]  # no matcher fields at all
    payload = _build_recommender_payload(rows, duration_min=10.0, set_id='set-a', bucket_id='a')
    assert payload['stats']['genre_matcher_endorse_count'] == 0
    assert payload['stats']['reco_bpm_prefilter_excluded_count'] == 0
    assert payload['stats']['reco_bpm_prefilter_fallback_count'] == 0


# ---- _build_director_payload / _extract_director_events ---------------------
# Mixer song-structure hint capture (2026-08-10) -- see docs/adr/vj-system.md.


def test_extract_director_events_includes_section_change_events() -> None:
    rows = [_make_seq_row(event_type='section_change')]
    rows[0].update({
        'from_role': 'RISE', 'from_label': 'build',
        'to_role': 'PEAK', 'to_label': 'drop',
        'section_role': 'PEAK', 'section_label': 'drop', 'section_bars_left': 6.0,
    })

    events = _extract_director_events(rows)

    assert len(events) == 1
    entry = events[0]
    assert entry['event_type'] == 'section_change'
    assert entry['from_role'] == 'RISE'
    assert entry['from_label'] == 'build'
    assert entry['to_role'] == 'PEAK'
    assert entry['to_label'] == 'drop'
    assert entry['section_role'] == 'PEAK'
    assert entry['section_bars_left'] == 6.0


def test_extract_director_events_carries_section_context_on_other_event_types() -> None:
    """A drop_fire (or any existing event type) also picks up the mixer's
    section hint when present -- lets structural_sync be judged from the
    same event samples the other four director dimensions already use."""
    rows = [_make_seq_row(event_type='drop_fire')]
    rows[0].update({'section_role': 'PEAK', 'section_label': 'drop', 'section_bars_left': 2.0})

    events = _extract_director_events(rows)

    assert events[0]['section_role'] == 'PEAK'
    assert events[0]['section_label'] == 'drop'
    assert events[0]['section_bars_left'] == 2.0


def test_extract_director_events_omits_section_fields_when_absent() -> None:
    """No mixer session hint that tick -- section_* keys must not appear at
    all (not as empty-string placeholders), same falsy-stripping already
    applied to every other optional field here."""
    rows = [_make_seq_row(event_type='drop_fire')]

    events = _extract_director_events(rows)

    assert 'section_role' not in events[0]
    assert 'section_label' not in events[0]
    assert 'section_bars_left' not in events[0]


def test_build_director_payload_stats_include_section_changes_and_coverage() -> None:
    hb_with_hint = [
        {**_make_seq_row(track_id=f'hb{i}'), 'section_role': 'HOLD'} for i in range(2)
    ]
    hb_without_hint = [_make_seq_row(track_id='hb_no_hint')]
    section_change = _make_seq_row(event_type='section_change')

    payload = _build_director_payload(
        hb_with_hint + hb_without_hint + [section_change],
        duration_min=10.0, set_id='set-a', bucket_id='a',
    )

    assert payload['stats']['section_changes'] == 1
    # 2 of 3 heartbeat rows carried a section hint.
    assert payload['stats']['section_hint_coverage_pct'] == pytest.approx(66.7, abs=0.1)


def test_build_director_payload_zero_section_coverage_when_no_mixer_session() -> None:
    rows = [_make_seq_row(track_id=f'hb{i}') for i in range(3)]

    payload = _build_director_payload(rows, duration_min=10.0, set_id='set-a', bucket_id='a')

    assert payload['stats']['section_changes'] == 0
    assert payload['stats']['section_hint_coverage_pct'] == 0.0


def test_write_scorecard_includes_song_structure_and_key_section(tmp_path: Path) -> None:
    seq_path = tmp_path / 'sequence-corpus.jsonl'
    rows = [
        {**_make_seq_row(track_id='a'), 'section_role': 'HOLD', 'key': 'A minor'},
        {**_make_seq_row(track_id='b'), 'key': 'unknown'},
        {**_make_seq_row(event_type='section_change')},
    ]
    seq_path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
    live_path = tmp_path / 'live-corpus.jsonl'
    live_path.write_text('', encoding='utf-8')
    bucket_dir = tmp_path / 'set-a' / 'a'
    bucket_dir.mkdir(parents=True)

    scorecard_path, _lock, _director = _write_scorecard(bucket_dir, live_path, seq_path)

    content = scorecard_path.read_text(encoding='utf-8')
    assert '## Song Structure & Key' in content
    assert 'Section-change events: `1`' in content
    assert 'Key coverage: `33.3%`' in content


# ---- _mean_field --------------------------------------------------------------


def test_mean_field_ignores_missing_and_non_numeric() -> None:
    rows = [{'x': 1.0}, {'x': 'nope'}, {}, {'x': 3.0}]
    assert _mean_field(rows, 'x') == pytest.approx(2.0)


def test_mean_field_none_on_no_valid_values() -> None:
    assert _mean_field([{'x': 'nope'}], 'x') is None


# ---- _run_llm_scoring skip / idempotent paths -------------------------------


def test_run_llm_scoring_skip_flag(tmp_path: Path) -> None:
    result = _run_llm_scoring(tmp_path, [], 'set-a', 'a', skip=True)
    assert result is None
    assert not (tmp_path / 'session_score.json').exists()


def test_run_llm_scoring_returns_existing_without_api_call(tmp_path: Path) -> None:
    existing = tmp_path / 'session_score.json'
    existing.write_text('{"detector": {}, "director": {}}', encoding='utf-8')
    with patch.object(_MOD, '_call_llm', side_effect=AssertionError('should not be called')):
        result = _run_llm_scoring(tmp_path, [], 'set-a', 'a', force_regen=False)
    assert result == {'detector': {}, 'director': {}}


def test_run_llm_scoring_overrides_a_hallucinated_scored_at(tmp_path: Path) -> None:
    """2026-08-10: an LLM has no reliable notion of 'now' and will happily
    invent a plausible-looking but wrong scored_at (observed live: every
    report in a session stamped identically with a hallucinated 2023 date)
    rather than leaving the field blank. The packaging script's own clock
    must always win, not just fill in a missing key."""
    rows = [_make_seq_row()]
    fake_response = json.dumps({
        'detector': {'scores': {}}, 'director': {'scores': {}},
        'recommender': {'scores': {}}, 'tuning': {},
        'scored_at': '2023-10-02T14:30:00+00:00',
    })
    with patch.dict('os.environ', {'OPENAI_API_KEY': 'sk-fake'}, clear=False), \
         patch.object(_MOD, '_call_llm', return_value=fake_response):
        result = _run_llm_scoring(tmp_path, rows, 'set-a', 'a')

    assert result is not None
    assert result['scored_at'] != '2023-10-02T14:30:00+00:00'
    assert result['scored_at'].startswith('20')  # a real, current-era ISO timestamp
    session_data = json.loads((tmp_path / 'session_score.json').read_text(encoding='utf-8'))
    assert session_data['scored_at'] == result['scored_at']
    det_data = json.loads((tmp_path / 'detector_score.json').read_text(encoding='utf-8'))
    assert det_data['scored_at'] == result['scored_at']


def test_run_llm_scoring_call_failure_writes_marker_and_loud_banner(
        tmp_path: Path, caplog, capsys) -> None:
    """2026-09-02: a real OpenAI quota exhaustion failed 11 of 14 buckets'
    LLM step in one batch with only a WARNING-level log line to show for
    it -- easy to miss in a long unattended run's scrollback, and nothing
    on disk afterward revealed which buckets were affected. Two checks:
    a marker file survives in the bucket for post-hoc inspection, and the
    console output is loud enough (not just logging.warning) to catch live."""
    rows = [_make_seq_row()]
    quota_exc = Exception("Error code: 429 - {'error': {'code': 'insufficient_quota'}}")
    with patch.dict('os.environ', {'OPENAI_API_KEY': 'sk-fake'}, clear=False), \
         patch.object(_MOD, '_call_llm', side_effect=quota_exc), \
         caplog.at_level('WARNING'):
        result = _run_llm_scoring(tmp_path, rows, 'set-a', 'a')

    assert result is None
    assert not (tmp_path / 'session_score.json').exists()

    marker = tmp_path / 'LLM_SCORING_FAILED.txt'
    assert marker.exists()
    marker_text = marker.read_text(encoding='utf-8')
    assert 'insufficient_quota' in marker_text
    assert 'openai' in marker_text

    out = capsys.readouterr().out
    assert 'LLM SCORING FAILED' in out
    assert 'BILLING/QUOTA ERROR' in out
    assert 'set-a/a' in out


def test_run_llm_scoring_non_quota_failure_marker_omits_billing_callout(tmp_path: Path) -> None:
    """A generic failure (e.g. a network timeout) still gets the marker and
    banner, but must not be mislabeled as a billing issue -- that would send
    someone to check credits for a problem credits can't fix."""
    rows = [_make_seq_row()]
    with patch.dict('os.environ', {'OPENAI_API_KEY': 'sk-fake'}, clear=False), \
         patch.object(_MOD, '_call_llm', side_effect=TimeoutError('connection timed out')):
        result = _run_llm_scoring(tmp_path, rows, 'set-a', 'a')

    assert result is None
    marker = (tmp_path / 'LLM_SCORING_FAILED.txt').read_text(encoding='utf-8')
    assert 'connection timed out' in marker
    assert 'quota' not in marker.lower()
    assert 'insufficient' not in marker.lower()


def test_run_llm_scoring_skips_gracefully_with_no_api_key(tmp_path: Path, caplog) -> None:
    rows = [_make_seq_row()]
    with patch.dict('os.environ', {'OPENAI_API_KEY': '', 'ANTHROPIC_API_KEY': ''}, clear=False), \
         caplog.at_level('WARNING'):
        result = _run_llm_scoring(tmp_path, rows, 'set-a', 'a')
    assert result is None
    assert not (tmp_path / 'session_score.json').exists()
    # 2026-08-15: the warning must call out that this is a shell/environment
    # issue, not a venv issue -- owner mistook a missing key for venv fallout
    # after activating .venv in a shell that never had the key exported.
    assert 'venv' in caplog.text
    assert 'echo $OPENAI_API_KEY' in caplog.text


# ---- _load_dotenv_fallback ---------------------------------------------------


def test_load_dotenv_fallback_no_op_without_env_file(tmp_path: Path) -> None:
    with patch.dict('os.environ', {}, clear=False):
        _load_dotenv_fallback(tmp_path)  # no .env present -- must not raise


def test_load_dotenv_fallback_sets_missing_keys(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / '.env').write_text(
        '# comment\n\nOPENAI_API_KEY=sk-from-dotenv\nANTHROPIC_API_KEY="sk-ant-quoted"\n',
        encoding='utf-8',
    )
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    _load_dotenv_fallback(tmp_path)
    assert os.environ['OPENAI_API_KEY'] == 'sk-from-dotenv'
    assert os.environ['ANTHROPIC_API_KEY'] == 'sk-ant-quoted'  # surrounding quotes stripped


def test_load_dotenv_fallback_never_overrides_real_shell_value(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / '.env').write_text('OPENAI_API_KEY=sk-from-dotenv\n', encoding='utf-8')
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-real-shell-value')
    _load_dotenv_fallback(tmp_path)
    assert os.environ['OPENAI_API_KEY'] == 'sk-real-shell-value'


# ---- _run_llm_summary (2026-08-09: consolidated console summary) -----------

_run_llm_summary = _MOD._run_llm_summary
_build_summary_prompt = _MOD._build_summary_prompt


def test_run_llm_summary_none_when_no_llm_data(tmp_path: Path) -> None:
    scorecard_path = tmp_path / 'scorecard.md'
    scorecard_path.write_text('# scorecard', encoding='utf-8')
    with patch.object(_MOD, '_call_llm', side_effect=AssertionError('should not be called')):
        result = _run_llm_summary(tmp_path, scorecard_path, None, 'openai', 'sk-fake')
    assert result is None


def test_run_llm_summary_none_when_no_provider(tmp_path: Path) -> None:
    scorecard_path = tmp_path / 'scorecard.md'
    scorecard_path.write_text('# scorecard', encoding='utf-8')
    result = _run_llm_summary(tmp_path, scorecard_path, {'detector': {}}, None, None)
    assert result is None


def test_run_llm_summary_returns_summary_text(tmp_path: Path) -> None:
    scorecard_path = tmp_path / 'scorecard.md'
    scorecard_path.write_text('# scorecard', encoding='utf-8')
    (tmp_path / 'recommender_score.md').write_text('x', encoding='utf-8')
    (tmp_path / 'detector_score.md').write_text('x', encoding='utf-8')
    (tmp_path / 'director_score.md').write_text('x', encoding='utf-8')
    with patch.object(_MOD, '_call_llm', return_value='{"summary": "Top takeaway here."}'):
        result = _run_llm_summary(tmp_path, scorecard_path, {'detector': {}}, 'openai', 'sk-fake')
    assert result == 'Top takeaway here.'


def test_run_llm_summary_none_on_call_failure(tmp_path: Path) -> None:
    scorecard_path = tmp_path / 'scorecard.md'
    scorecard_path.write_text('# scorecard', encoding='utf-8')
    with patch.object(_MOD, '_call_llm', side_effect=RuntimeError('boom')):
        result = _run_llm_summary(tmp_path, scorecard_path, {'detector': {}}, 'openai', 'sk-fake')
    assert result is None


def test_build_summary_prompt_does_not_ask_to_restate_reports() -> None:
    """Owner instruction: reports stay fully separate on disk -- the
    summary is a synthesis pass, not a merge. Loosely checks the prompt
    doesn't ask the LLM to reproduce report content verbatim."""
    prompt = _build_summary_prompt('scorecard text', {'detector': {}}, {'scorecard': Path('scorecard.md')})
    assert 'summary' in prompt.lower()
    assert 'scorecard text' in prompt
    assert 'top 3' in prompt.lower() or 'top three' in prompt.lower()


# ---- _score_lock_quality ----------------------------------------------------


def test_score_lock_quality_uses_confidence_not_beat_index() -> None:
    """Lock quality must be driven by bpm_confidence, not the broken beat_index field."""
    # Rows where beat_index is -1 (always) but confidence is >= floor → should get real rating.
    rows_high_conf = [_make_seq_row(confidence=0.72, beat_index=-1) for _ in range(10)]
    rows_low_conf = [_make_seq_row(confidence=0.20, beat_index=-1) for _ in range(10)]
    payload_high = _build_detector_payload(rows_high_conf, 'set-a', 'a')
    payload_low = _build_detector_payload(rows_low_conf, 'set-a', 'a')
    assert payload_high['beat_lock']['coverage_pct'] == pytest.approx(100.0)
    assert payload_low['beat_lock']['coverage_pct'] == pytest.approx(0.0)


def test_score_lock_quality_rating_scale() -> None:
    assert _score_lock_quality(75.0, 0.65) == 5
    assert _score_lock_quality(50.0, 0.50) == 4
    assert _score_lock_quality(30.0, 0.35) == 3
    assert _score_lock_quality(12.0, 0.20) == 2
    assert _score_lock_quality(0.0, 0.50) == 1


# ---- _cleanup_stale_empty_corpus_files ---------------------------------------


def test_cleanup_removes_zero_byte_matching_files(tmp_path: Path) -> None:
    empty = tmp_path / 'live-corpus.jsonl'
    empty.write_text('')

    removed = _cleanup_stale_empty_corpus_files(tmp_path, _CORPUS_PATTERNS)

    assert removed == [empty]
    assert not empty.exists()


def test_cleanup_does_not_touch_non_empty_matching_files(tmp_path: Path) -> None:
    real = tmp_path / 'live-corpus-20260101T000000Z.jsonl'
    real.write_text('{"row": 1}\n')

    removed = _cleanup_stale_empty_corpus_files(tmp_path, _CORPUS_PATTERNS)

    assert removed == []
    assert real.exists()


def test_cleanup_ignores_non_matching_files(tmp_path: Path) -> None:
    unrelated = tmp_path / 'notes.txt'
    unrelated.write_text('')

    removed = _cleanup_stale_empty_corpus_files(tmp_path, _CORPUS_PATTERNS)

    assert removed == []
    assert unrelated.exists()


def test_cleanup_handles_both_live_and_sequence_empty_placeholders(tmp_path: Path) -> None:
    live_empty = tmp_path / 'live-corpus.jsonl'
    seq_empty = tmp_path / 'sequence-corpus.jsonl'
    live_empty.write_text('')
    seq_empty.write_text('')
    real_live = tmp_path / 'live-corpus-20260622T015156Z.jsonl'
    real_live.write_text('{"row": 1}\n')

    removed = _cleanup_stale_empty_corpus_files(tmp_path, _CORPUS_PATTERNS)

    assert set(removed) == {live_empty, seq_empty}
    assert real_live.exists()


def test_cleanup_on_empty_directory_returns_empty_list(tmp_path: Path) -> None:
    assert _cleanup_stale_empty_corpus_files(tmp_path, _CORPUS_PATTERNS) == []


# ---- profile-expected-values prompt block (stays in sync with PROFILES) -----


def test_load_profile_expected_values_matches_live_roster() -> None:
    """The LLM prompt's profile table must never drift from the real roster.

    This used to be a hand-copied snapshot that silently went stale (it still
    listed profiles like 'lofi'/'jazz'/'metal' long after they were removed
    from unicornviz.audio.profiles). Reading PROFILES directly at prompt-build
    time makes that drift structurally impossible -- this test just confirms
    the live import path actually resolves and covers the full roster.
    """
    from unicornviz.audio.profiles import PROFILES

    values = _load_profile_expected_values()
    assert set(values.keys()) == set(PROFILES.keys())
    for key, profile in PROFILES.items():
        assert values[key]['centroid'] == pytest.approx(profile.spectral_centroid_mu)
        assert values[key]['zcr'] == pytest.approx(profile.zcr_mu)
        assert values[key]['onset'] == pytest.approx(profile.onset_density_mu)


def test_load_profile_expected_values_includes_bpm_fields() -> None:
    """2026-08-14: the LLM prompt never told the model what BPM each profile
    actually expects -- hint_integration scoring had no ground truth to check
    against. bpm_hint_min/max/bpm_mu/bpm_sigma now ride alongside the
    spectral fields for every profile that defines them."""
    from unicornviz.audio.profiles import PROFILES

    values = _load_profile_expected_values()
    for key, profile in PROFILES.items():
        assert values[key]['bpm_mu'] == pytest.approx(profile.bpm_prior_mu)
        assert values[key]['bpm_sigma'] == pytest.approx(profile.bpm_prior_sigma)
        if profile.bpm_hint_min is not None:
            assert values[key]['bpm_hint_min'] == pytest.approx(profile.bpm_hint_min)
        if profile.bpm_hint_max is not None:
            assert values[key]['bpm_hint_max'] == pytest.approx(profile.bpm_hint_max)


def test_format_profile_expected_values_block_empty() -> None:
    assert 'unable to load' in _format_profile_expected_values_block({})


def test_format_profile_expected_values_block_renders_all_entries() -> None:
    values = {
        'house': {'centroid': 1500.0, 'zcr': 0.06, 'onset': 2.5},
        'ambient': {'centroid': 800.0, 'zcr': 0.03, 'onset': 0.4},
    }
    block = _format_profile_expected_values_block(values)
    assert 'ambient:' in block
    assert 'house:' in block
    assert 'centroid=1500 Hz' in block
    assert 'zcr=0.060' in block
    assert 'onset=2.5/s' in block


def test_format_profile_expected_values_block_renders_bpm_fields_when_present() -> None:
    values = {
        'house': {
            'centroid': 1500.0, 'zcr': 0.06, 'onset': 2.5,
            'bpm_hint_min': 118.0, 'bpm_hint_max': 126.0,
            'bpm_mu': 122.0, 'bpm_sigma': 0.0505,
        },
    }
    block = _format_profile_expected_values_block(values)
    assert 'bpm_hint=118-126' in block
    assert 'bpm_mu=122.0' in block
    assert 'σ=0.051' in block


def test_format_profile_expected_values_block_omits_bpm_fields_when_absent() -> None:
    values = {'house': {'centroid': 1500.0, 'zcr': 0.06, 'onset': 2.5}}
    block = _format_profile_expected_values_block(values)
    assert 'bpm_hint=' not in block
    assert 'bpm_mu=' not in block


def test_reco_weights_line_used_consistently_in_both_prompt_spots() -> None:
    """The two weight mentions in the prompt used to be separate hand-typed
    lists that could silently drift from each other; both must now come from
    the same resolved weight dict (live auto-vj-01 read, or the static
    fallback) via _format_reco_weights_line()."""
    detector_payload = {'essentia_available': False}
    prompt = _build_combined_prompt(detector_payload, {}, None)
    line = _format_reco_weights_line(_load_live_reco_weights() or _RECO_WEIGHT_DEFAULTS)
    assert prompt.count(line) == 2


def test_load_live_reco_weights_matches_live_auto_vj_defaults() -> None:
    """2026-08-07: _RECO_WEIGHT_DEFAULTS used to be the sole source for the
    LLM prompt and silently drifted from auto_vj.py's real weights twice
    (a centroid_fit reweight, and two new vocal-fit terms never mirrored
    here). _load_live_reco_weights() reads the live dict directly, so this
    test just confirms that path actually resolves and matches exactly --
    structural drift is no longer possible once it does."""
    import importlib.util as _ilu
    auto_vj_path = (
        Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
    )
    spec = _ilu.spec_from_file_location('test_pts_live_auto_vj', auto_vj_path)
    assert spec is not None and spec.loader is not None
    auto_vj_mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(auto_vj_mod)

    live = _load_live_reco_weights()
    assert live is not None
    assert live == auto_vj_mod._DEFAULT_RECO_WEIGHTS
    assert 'vocal_hnr_fit' in live
    assert 'vocal_fmr_fit' in live


def test_load_live_reco_weights_returns_none_when_auto_vj_absent(tmp_path: Path, monkeypatch) -> None:
    """A checkout without the auto-vj-01 drop-in must fall back cleanly,
    not raise -- same contract as _load_profile_expected_values()."""
    (tmp_path / 'pyproject.toml').write_text('', encoding='utf-8')
    (tmp_path / 'unicornviz').mkdir()
    monkeypatch.setattr(_MOD, '_find_repo_root', lambda start: tmp_path)

    assert _load_live_reco_weights() is None


def test_build_shadow_comparison_none_when_no_shadow_data() -> None:
    rows = [_make_seq_row() for _ in range(3)]
    assert _build_shadow_comparison(rows) is None


def test_build_shadow_comparison_summarizes_agreement() -> None:
    rows = [
        {**_make_seq_row(bpm=124.0, confidence=0.6), 'bpm_shadow': 124.5, 'confidence_shadow': 0.58},
        {**_make_seq_row(bpm=124.0, confidence=0.6), 'bpm_shadow': 146.3, 'confidence_shadow': 0.5},
        {**_make_seq_row(bpm=124.0, confidence=0.6), 'bpm_shadow': 124.2, 'confidence_shadow': 0.62},
    ]
    for r in rows:
        r['shadow_engine'] = '3.0.0'

    summary = _build_shadow_comparison(rows)

    assert summary is not None
    assert summary['shadow_engine'] == '3.0.0'
    assert summary['compared_rows'] == 3
    assert summary['bpm_agreement_pct'] == pytest.approx(200.0 / 3, abs=0.1)   # 2 of 3 within 2 BPM
    assert summary['active_confidence_median'] == pytest.approx(0.6)


def test_build_detector_payload_includes_shadow_comparison_when_present() -> None:
    rows = [
        {**_make_seq_row(bpm=124.0, confidence=0.6), 'bpm_shadow': 124.2,
         'confidence_shadow': 0.6, 'shadow_engine': '3.0.0'}
        for _ in range(3)
    ]
    payload = _build_detector_payload(rows, 'set-a', 'a')
    assert payload['shadow_engine_comparison'] is not None
    assert payload['shadow_engine_comparison']['shadow_engine'] == '3.0.0'


def test_build_detector_payload_shadow_comparison_absent_without_shadow_data() -> None:
    rows = [_make_seq_row() for _ in range(3)]
    payload = _build_detector_payload(rows, 'set-a', 'a')
    assert payload['shadow_engine_comparison'] is None


def test_summarize_engine_versions_none_for_older_corpus_without_the_field() -> None:
    rows = [_make_seq_row() for _ in range(3)]   # no engine_version key at all
    assert _summarize_engine_versions(rows) is None


def test_summarize_engine_versions_single_engine() -> None:
    rows = [{**_make_seq_row(), 'engine_version': '3.0.0'} for _ in range(4)]
    summary = _summarize_engine_versions(rows)
    assert summary is not None
    assert summary['primary'] == '3.0.0'
    assert summary['versions'] == {'3.0.0': 4}
    assert summary['coverage_pct'] == pytest.approx(100.0)


def test_summarize_engine_versions_mixed_engines_within_one_session() -> None:
    rows = (
        [{**_make_seq_row(), 'engine_version': '2.0.0'} for _ in range(3)]
        + [{**_make_seq_row(), 'engine_version': '3.0.0'} for _ in range(1)]
    )
    summary = _summarize_engine_versions(rows)
    assert summary['primary'] == '2.0.0'
    assert summary['versions'] == {'2.0.0': 3, '3.0.0': 1}
    assert summary['coverage_pct'] == pytest.approx(100.0)


def test_build_detector_payload_includes_engine_versions_key() -> None:
    rows = [{**_make_seq_row(), 'engine_version': '3.0.0'} for _ in range(3)]
    payload = _build_detector_payload(rows, 'set-a', 'a')
    assert payload['engine_versions']['primary'] == '3.0.0'


def test_build_combined_prompt_uses_live_profile_values_not_stale_names() -> None:
    """No hardcoded/removed profile name (e.g. 'lofi', 'jazz', 'metal') should ever appear."""
    detector_payload = {'essentia_available': False}
    director_payload = {}
    prompt = _build_combined_prompt(detector_payload, director_payload, None)
    for stale_name in ('lofi:', 'jazz:', 'classical:', 'minimal:', 'metal:', 'industrial:', 'reggae:'):
        assert stale_name not in prompt, f'stale profile {stale_name!r} leaked into prompt'
    assert 'house:' in prompt


def test_build_combined_prompt_essentia_note_no_data() -> None:
    detector_payload = {'essentia_available': False, 'per_song': [
        {'key': 'id:aaa', 'mixer_bpm_median': None, 'essentia_bpm': None},
    ]}
    prompt = _build_combined_prompt(detector_payload, {}, None)
    assert 'score external_agreement as null' in prompt
    assert 'Real external reference data is available' not in prompt


def test_build_combined_prompt_essentia_note_with_real_reference_data() -> None:
    """2026-08-14, round three: mixer_bpm_median/essentia_bpm wired up for
    real -- the note must say so and point the LLM at per-song data
    instead of claiming no reference exists."""
    detector_payload = {'essentia_available': False, 'per_song': [
        {'key': 'id:aaa', 'mixer_bpm_median': 125.0, 'essentia_bpm': None},
        {'key': 'id:bbb', 'mixer_bpm_median': None, 'essentia_bpm': 127.4},
        {'key': 'id:ccc', 'mixer_bpm_median': None, 'essentia_bpm': None},
    ]}
    prompt = _build_combined_prompt(detector_payload, {}, None)
    assert 'Real external reference data is available for 2 of 3 songs' in prompt
    assert 'score external_agreement as null' not in prompt


def test_build_combined_prompt_live_corpus_note_only_when_snapshot_present() -> None:
    detector_payload_with = {'essentia_available': False, 'per_song': [], 'live_corpus_snapshot': [
        {'title': 'A', 'artist': 'B', 'bpm': 124.0, 'bpm_confidence': 0.8, 'track_genre': None, 'profile': None},
    ]}
    prompt_with = _build_combined_prompt(detector_payload_with, {}, None)
    assert 'live_corpus_snapshot is a compact' in prompt_with

    detector_payload_without = {'essentia_available': False, 'per_song': [], 'live_corpus_snapshot': []}
    prompt_without = _build_combined_prompt(detector_payload_without, {}, None)
    assert 'live_corpus_snapshot is a compact' not in prompt_without


def test_build_combined_prompt_includes_dynamic_set_flexibility_guidance() -> None:
    """2026-08-14: the LLM used to have no way to distinguish a standard
    single-tempo track from a DJ mix/mashup/blend where tempo and genre
    changes mid-track are the correct, intended content -- risking penalizing
    tempo_plausibility/hint_integration/etc for real musical shifts. The
    guidance must appear once, up front, and be referenced from both the
    detector's tempo_plausibility and the recommender's dimension list."""
    detector_payload = {'essentia_available': False}
    director_payload = {}
    prompt = _build_combined_prompt(detector_payload, director_payload, None)
    assert 'Mashup' in prompt
    assert 'do NOT penalize tempo_plausibility' in prompt
    assert 'dynamic-set note above' in prompt


# ---- Tier 2: genre-tag ground-truth accuracy --------------------------------


@pytest.mark.parametrize('tag,expected', [
    ('House', 'house'),
    ('Deep House', 'deep_house'),
    ('Psy-Trance', 'psytrance'),
    ('psytrance', 'psytrance'),
    ('Hard Techno', 'hard_techno'),
    ('Hardstyle', 'hardstyle'),
    ('Drum & Bass', 'drum_and_bass'),
    ('DnB', 'drum_and_bass'),
    ('Rap / R&B', 'rap_rnb'),
    ('Hip-Hop', 'rap_rnb'),
    ('Ambient / Chillout', 'ambient'),
    ('Synthwave / Retrowave', 'synthwave'),
])
def test_map_genre_tag_exact_alias_matches(tag: str, expected: str) -> None:
    assert _map_genre_tag_to_profile_key(tag) == expected


@pytest.mark.parametrize('tag,expected', [
    ('Tropical House', 'house'),
    ('Afro House', 'house'),
    ('Progressive House', 'house'),
    ('Progressive Trance', 'trance'),
    ('Vaporwave', 'synthwave'),
    ('Melodic Techno', 'electronic'),
])
def test_map_genre_tag_keyword_fallback_matches(tag: str, expected: str) -> None:
    """Real sub-genres with no dedicated profile route through pass 2 on
    their last/most-generic word rather than landing unmapped."""
    assert _map_genre_tag_to_profile_key(tag) == expected


def test_map_genre_tag_unmapped_returns_none() -> None:
    assert _map_genre_tag_to_profile_key('Bossa Nova') is None
    assert _map_genre_tag_to_profile_key('') is None
    assert _map_genre_tag_to_profile_key(None) is None


def _make_reco_row(genre: str, recommended: str) -> dict:
    return {'track_genre': genre, 'recommended_profile_key': recommended}


def test_recommender_accuracy_counts_hits_and_misses() -> None:
    rows = [
        _make_reco_row('Deep House', 'deep_house'),   # hit
        _make_reco_row('Deep House', 'deep_house'),   # hit
        _make_reco_row('Psy-Trance', 'deep_house'),   # miss
        _make_reco_row('', 'house'),                   # untagged -- excluded
        _make_reco_row('House', ''),                   # no recommendation yet -- excluded
        _make_reco_row('Bossa Nova', 'house'),          # unmapped
    ]
    stats = _build_recommender_accuracy(rows)

    assert stats['total_rows'] == 6
    assert stats['tagged_rows'] == 4          # every row with both genre+recommendation
    assert stats['unmapped_rows'] == 1
    assert stats['usable_rows'] == 3
    assert stats['hits'] == 2
    assert stats['misses'] == 1
    assert stats['accuracy_pct'] == pytest.approx(200.0 / 3.0)


def test_recommender_accuracy_confusion_entries_are_genre_expected_recommended() -> None:
    rows = [_make_reco_row('Psy-Trance', 'deep_house')]
    stats = _build_recommender_accuracy(rows)
    assert stats['top_confusions'] == [(('Psy-Trance', 'psytrance', 'deep_house'), 1)]


def test_recommender_accuracy_no_tagged_rows() -> None:
    rows = [_make_reco_row('', 'house'), {'recommended_profile_key': 'house'}]
    stats = _build_recommender_accuracy(rows)
    assert stats['tagged_rows'] == 0
    assert stats['accuracy_pct'] is None


def test_format_recommender_accuracy_block_no_tagged_rows() -> None:
    stats = _build_recommender_accuracy([])
    block = _format_recommender_accuracy_block(stats)
    assert any('No tagged rows' in line for line in block)


def test_format_recommender_accuracy_block_always_includes_tag_reliability_caveat() -> None:
    """2026-08-11: owner request -- readers of this block (human or a future
    LLM summarizing scorecards) should never see an accuracy_pct without the
    caveat that track_genre is an uncurated ID3 tag, not a professionally
    tagged ground truth, and has zero live influence on the recommender.
    Present whether or not any rows are tagged."""
    empty_block = _format_recommender_accuracy_block(_build_recommender_accuracy([]))
    assert any('uncurated ID3 tag' in line for line in empty_block)

    tagged_stats = _build_recommender_accuracy([_make_reco_row('Deep House', 'deep_house')])
    tagged_block = _format_recommender_accuracy_block(tagged_stats)
    assert any('uncurated ID3 tag' in line for line in tagged_block)


def test_format_recommender_accuracy_block_renders_accuracy_and_confusions() -> None:
    rows = [
        _make_reco_row('Deep House', 'deep_house'),
        _make_reco_row('Psy-Trance', 'deep_house'),
    ]
    stats = _build_recommender_accuracy(rows)
    block = _format_recommender_accuracy_block(stats)
    joined = '\n'.join(block)
    assert 'Accuracy:' in joined
    assert '50.0%' in joined
    assert 'Psy-Trance' in joined


def test_write_scorecard_includes_recommender_accuracy_section(tmp_path: Path) -> None:
    seq_path = tmp_path / 'sequence-corpus.jsonl'
    rows = [
        {**_make_seq_row(), 'track_genre': 'Deep House', 'recommended_profile_key': 'deep_house'},
        {**_make_seq_row(), 'track_genre': 'Psy-Trance', 'recommended_profile_key': 'deep_house'},
    ]
    seq_path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
    live_path = tmp_path / 'live-corpus.jsonl'
    live_path.write_text('', encoding='utf-8')
    bucket_dir = tmp_path / 'set-a' / 'a'
    bucket_dir.mkdir(parents=True)

    scorecard_path, _lock, _director = _MOD._write_scorecard(bucket_dir, live_path, seq_path)

    content = scorecard_path.read_text(encoding='utf-8')
    assert '## Recommender Accuracy' in content
    assert 'Accuracy:' in content


# ---- Detector/director constants fed to the LLM tuning prompt --------------


def test_load_live_detector_constants_matches_live_beat_grid_and_auto_vj() -> None:
    """Mirrors test_load_live_reco_weights_matches_live_auto_vj_defaults --
    confirms the live-read path for detector thresholds actually resolves
    and matches the real source (beat_grid.py module constants +
    AutoVJController's _BPM_LOCK_* class attributes), not just the fallback
    snapshot."""
    import importlib.util as _ilu
    repo_root = Path(__file__).resolve().parents[1]
    bg_spec = _ilu.spec_from_file_location(
        'test_pts_live_beat_grid', repo_root / 'drop-ins' / 'auto-vj-01' / 'beat_grid.py')
    assert bg_spec is not None and bg_spec.loader is not None
    bg_mod = _ilu.module_from_spec(bg_spec)
    bg_spec.loader.exec_module(bg_mod)
    av_spec = _ilu.spec_from_file_location(
        'test_pts_live_auto_vj_2', repo_root / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py')
    assert av_spec is not None and av_spec.loader is not None
    av_mod = _ilu.module_from_spec(av_spec)
    av_spec.loader.exec_module(av_mod)

    live = _load_live_detector_constants()
    assert live is not None
    for name in _DETECTOR_CONSTANT_DEFAULTS:
        if name == 'env_source':
            # A per-instance cfg default, not a bare module attribute --
            # see _load_live_detector_constants()'s own special case.
            assert live[name] == bg_mod.BeatTracker({})._env_source
        elif name.startswith('_BPM_LOCK'):
            assert live[name] == getattr(av_mod.AutoVJController, name)
        else:
            assert live[name] == getattr(bg_mod, name)


def test_load_live_detector_constants_returns_none_when_auto_vj_absent(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / 'pyproject.toml').write_text('', encoding='utf-8')
    (tmp_path / 'unicornviz').mkdir()
    monkeypatch.setattr(_MOD, '_find_repo_root', lambda start: tmp_path)

    assert _load_live_detector_constants() is None


def test_all_detector_constant_defaults_keys_are_live_readable() -> None:
    """Every key in _DETECTOR_CONSTANT_DEFAULTS must actually resolve via
    the live loader -- catches the specific failure mode found 2026-08-17:
    a new beat_grid.py constant landing in code without ever being added
    here, which silently means _load_live_detector_constants()'s own loop
    (`for name in _DETECTOR_CONSTANT_DEFAULTS`) can never pick it up
    either, live-read or not -- a constant has to be listed in the
    fallback dict FIRST, with any value, before the live loader will ever
    look for it. This doesn't catch a constant missing from the dict
    entirely (nothing to iterate over) -- it catches every key that IS
    listed actually resolving against real, loadable auto-vj-01 code."""
    live = _load_live_detector_constants()
    assert live is not None
    missing = set(_DETECTOR_CONSTANT_DEFAULTS) - set(live)
    assert not missing, f'Keys in _DETECTOR_CONSTANT_DEFAULTS did not resolve live: {missing}'


def test_load_live_director_constants_matches_live_auto_vj_defaults() -> None:
    """2026-08-17: closes the one gap _load_live_reco_weights()/
    _load_live_detector_constants() didn't cover -- phrase_under_over_
    hold_mult's _DIRECTOR_CONSTANT_DEFAULTS entry went stale (said 0.7,
    shipped code was 0.8 since rc.7) and the LLM recommended "raising"
    it to a value it already had. Confirms the live-read path actually
    resolves and matches real AutoVJController._apply_profile_settings()
    output, not just the fallback snapshot."""
    import importlib.util as _ilu
    repo_root = Path(__file__).resolve().parents[1]
    av_spec = _ilu.spec_from_file_location(
        'test_pts_live_director_auto_vj', repo_root / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py')
    assert av_spec is not None and av_spec.loader is not None
    av_mod = _ilu.module_from_spec(av_spec)
    av_spec.loader.exec_module(av_mod)

    inst = object.__new__(av_mod.AutoVJController)
    inst._cfg = {}
    inst._use_user_profile_overrides = False
    inst._explicit_profile_override_keys = set()
    inst._profile_defaults = av_mod._PROFILE_PRESETS[av_mod._DEFAULT_PROFILE]
    inst._apply_profile_settings()

    live = _load_live_director_constants()
    assert live is not None
    for name in _DIRECTOR_CONSTANT_DEFAULTS:
        if name.startswith('_'):
            assert live[name] == getattr(av_mod, name)
        else:
            assert live[name] == getattr(inst, f'_{name}')


def test_load_live_director_constants_returns_none_when_auto_vj_absent(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / 'pyproject.toml').write_text('', encoding='utf-8')
    (tmp_path / 'unicornviz').mkdir()
    monkeypatch.setattr(_MOD, '_find_repo_root', lambda start: tmp_path)

    assert _load_live_director_constants() is None


def test_phrase_under_over_hold_mult_fallback_matches_shipped_code() -> None:
    """Direct regression test for the exact stale-value incident: the
    fallback (used only when auto-vj-01 is absent, but still meant to
    "stay plausible" per its own module comment) must not silently
    regress back to the old 0.7."""
    assert _DIRECTOR_CONSTANT_DEFAULTS['phrase_under_over_hold_mult'] == 0.8


def test_format_constants_line_uses_equals_not_multiply() -> None:
    """Distinct notation from _format_reco_weights_line()'s '×' -- these are
    independent thresholds, not composite-score multipliers."""
    line = _format_constants_line({'a': 1.5, 'b': 2})
    assert line == 'a = 1.5, b = 2'


def test_build_combined_prompt_includes_detector_and_director_constants() -> None:
    detector_payload = {'essentia_available': False}
    prompt = _build_combined_prompt(detector_payload, {}, None)
    live_detector = _load_live_detector_constants() or _DETECTOR_CONSTANT_DEFAULTS
    live_director = _load_live_director_constants() or _DIRECTOR_CONSTANT_DEFAULTS
    assert _format_constants_line(live_detector) in prompt
    assert _format_constants_line(live_director) in prompt


def test_build_combined_prompt_weight_enum_includes_vocal_fit_terms() -> None:
    """Regression: the weight_recommendations schema enum used to omit
    vocal_hnr_fit/vocal_fmr_fit entirely, so the LLM could never be asked
    to recommend a change to either -- silent coverage gap, not a crash."""
    detector_payload = {'essentia_available': False}
    prompt = _build_combined_prompt(detector_payload, {}, None)
    assert 'vocal_hnr_fit' in prompt
    assert 'vocal_fmr_fit' in prompt


def test_build_combined_prompt_flags_non_discriminating_terms() -> None:
    """2026-08-09: lock_rate/mean_conf/mean_dconf were retired from the
    composite entirely (they were session-global, not per-candidate, so
    structurally inert as weighted terms) and now scale detector_trust /
    the confirmation gate instead -- the prompt must not ask the LLM to
    recommend re-weighting them (there is no weight to recommend), and
    must explain where they actually matter now."""
    detector_payload = {'essentia_available': False}
    prompt = _build_combined_prompt(detector_payload, {}, None)
    assert 'not in this weight list' in prompt
    assert 'detector_trust' in prompt
    reco_weights_line = _format_reco_weights_line(_load_live_reco_weights() or _RECO_WEIGHT_DEFAULTS)
    assert 'lock_rate' not in reco_weights_line
    assert 'mean_conf' not in reco_weights_line
    assert 'mean_dconf' not in reco_weights_line


def test_build_combined_prompt_separates_confidence_smoothing_from_tempo_accuracy() -> None:
    """2026-08-10: a real session's LLM tuning recommendation suggested
    widening _V2_COHERENCE_WINDOW to fix a 'tempo plausibility' issue --
    a weak causal link (that constant governs phase-lock confidence
    smoothing, not which BPM value gets picked). The prompt must now
    explicitly separate tempo-value-search constants from confidence-
    smoothing ones and require a rationale to cite a same-category
    payload field, so the LLM can't repeat that exact mistake."""
    detector_payload = {'essentia_available': False}
    prompt = _build_combined_prompt(detector_payload, {}, None)
    assert '_V2_COHERENCE_WINDOW' in prompt
    assert '_V2_PHASE_TOL' in prompt
    assert 'Phase-lock CONFIDENCE smoothing' in prompt
    assert 'Tempo VALUE search/accuracy' in prompt
    assert 'must name the' in prompt and 'exact payload field' in prompt


def test_build_combined_prompt_includes_bpm_value_accept_reject_gate_category() -> None:
    """2026-08-14, later still again: a fourth constant category, distinct
    from the three above -- the gate stack deciding whether a freshly
    computed ACF candidate is actually ACCEPTED as the new published BPM
    at all, gated on raw acf_confidence, never the published confidence
    blend. Directly implicated in a real carry-over incident (BPM frozen
    across a track change) the same night."""
    detector_payload = {'essentia_available': False}
    prompt = _build_combined_prompt(detector_payload, {}, None)
    assert 'BPM-value ACCEPT/REJECT gating' in prompt
    assert '_V2_LARGE_JUMP_CONFIDENCE' in prompt
    assert '_V2_MAX_BPM_STEP' in prompt
    assert '_V2_ANALYSIS_REGION_CONFIDENCE_MIN' in prompt


def test_format_tuning_recommendations_md_renders_detector_and_director_sections() -> None:
    tuning = {
        'overall_assessment': 'Solid session overall.',
        'weight_recommendations': [
            {'weight': 'centroid_fit', 'current_coefficient': 1.0,
             'recommended_coefficient': 0.8, 'rationale': 'Test rationale.'},
        ],
        'detector_recommendations': [
            {'constant': '_BPM_LOCK_RELEASE_CONFIDENCE', 'current_value': 0.28,
             'recommended_value': 0.22, 'rationale': 'Lock churn observed.'},
        ],
        'director_recommendations': [
            {'constant': 'phrase_bias_max', 'current_value': 0.15,
             'recommended_value': 0.18, 'rationale': 'Builds rushed.'},
        ],
    }
    md = _format_tuning_recommendations_md(tuning, 'set-a', 'a', '2026-08-09T00:00:00Z', 'anthropic')
    assert '## Recommender Weight Recommendations' in md
    assert '## Detector Constant Recommendations' in md
    assert '## Director Constant Recommendations' in md
    assert '_BPM_LOCK_RELEASE_CONFIDENCE' in md
    assert 'phrase_bias_max' in md
    assert '## Advisory Only' in md


def test_format_tuning_recommendations_md_omits_empty_sections() -> None:
    tuning = {'overall_assessment': 'n/a'}
    md = _format_tuning_recommendations_md(tuning, 'set-a', 'a', '2026-08-09T00:00:00Z', 'anthropic')
    assert '## Recommender Weight Recommendations' not in md
    assert '## Detector Constant Recommendations' not in md
    assert '## Director Constant Recommendations' not in md
    assert '## Advisory Only' in md


# ---- bucket naming: letters -> 0-padded 3-digit numbers (2026-08-18) ------


def test_bucket_name_is_zero_padded_three_digit_and_one_based() -> None:
    assert _MOD._bucket_name(0) == '001'
    assert _MOD._bucket_name(1) == '002'
    assert _MOD._bucket_name(8) == '009'
    assert _MOD._bucket_name(9) == '010'
    assert _MOD._bucket_name(98) == '099'
    assert _MOD._bucket_name(99) == '100'


def test_bucket_name_grows_past_three_digits_without_truncation() -> None:
    assert _MOD._bucket_name(998) == '999'
    assert _MOD._bucket_name(999) == '1000'


def test_next_bucket_dir_fills_first_unused_numeric_slot(tmp_path: Path) -> None:
    set_dir = tmp_path / 'my-set'
    set_dir.mkdir()
    (set_dir / '001').mkdir()
    (set_dir / '003').mkdir()  # a gap at 002
    assert _MOD._next_bucket_dir(set_dir).name == '002'


def test_next_bucket_dir_does_not_collide_with_existing_letter_buckets(tmp_path: Path) -> None:
    """2026-08-18: existing letter-named buckets (from before this change)
    must not be renamed or treated as occupying a numeric slot -- '001'
    never equals 'a', so a set with a/b/c already in it just starts fresh
    at '001' for its next bucket rather than continuing the letters."""
    set_dir = tmp_path / 'old-set'
    set_dir.mkdir()
    (set_dir / 'a').mkdir()
    (set_dir / 'b').mkdir()
    (set_dir / 'c').mkdir()
    next_dir = _MOD._next_bucket_dir(set_dir)
    assert next_dir.name == '001'
    # The pre-existing letter buckets are untouched.
    assert (set_dir / 'a').is_dir()
    assert (set_dir / 'b').is_dir()
    assert (set_dir / 'c').is_dir()


# ---- _write_mixer_crossref_report / _mixer_bpm_for_path (2026-08-18) --------


def test_mixer_crossref_sources_are_media_and_replay_only() -> None:
    assert _MIXER_CROSSREF_SOURCES == {'media-01', 'replay'}


def test_mixer_bpm_for_path_direct_hit() -> None:
    paths_map = {'/music/a.mp3': {'hash': 'h1'}}
    tracks_map = {'h1': {'bpm': 127.4}}
    assert _mixer_bpm_for_path('/music/a.mp3', paths_map, tracks_map) == pytest.approx(127.4)


def test_mixer_bpm_for_path_basename_fallback_for_mount_mismatch() -> None:
    """Same file, different mount point (e.g. the log was captured under
    a different mount than the one packaging runs under) -- falls back to
    matching by filename, mirroring bpm_agreement_report.py's own helper."""
    paths_map = {'/mnt/old/library/track.mp3': {'hash': 'h1'}}
    tracks_map = {'h1': {'bpm': 140.0}}
    assert _mixer_bpm_for_path('/home/me/Music/track.mp3', paths_map, tracks_map) == pytest.approx(140.0)


def test_mixer_bpm_for_path_no_entry_returns_zero() -> None:
    assert _mixer_bpm_for_path('/music/unknown.mp3', {}, {}) == 0.0


def test_mixer_bpm_for_path_empty_path_returns_zero() -> None:
    assert _mixer_bpm_for_path('', {'/music/a.mp3': {'hash': 'h1'}}, {'h1': {'bpm': 120.0}}) == 0.0


def test_write_mixer_crossref_report_none_when_no_qualifying_source(tmp_path: Path) -> None:
    """A real dj-mixer-01 session (or Spotify/stream) already has mixer_bpm
    and track_genre on the live bus -- no report needed, and none written."""
    rows = [{**_make_seq_row(), 'metadata_source': 'dj-mixer-01'}]
    assert _write_mixer_crossref_report(tmp_path, rows) is None
    assert not (tmp_path / 'mixer_crossref.md').exists()


def test_write_mixer_crossref_report_none_when_source_field_absent(tmp_path: Path) -> None:
    rows = [_make_seq_row()]
    assert _write_mixer_crossref_report(tmp_path, rows) is None


def test_write_mixer_crossref_report_writes_table_for_media_source(tmp_path: Path, monkeypatch) -> None:
    audio_file = tmp_path / 'track.mp3'
    audio_file.write_bytes(b'fake')

    monkeypatch.setattr(
        _MOD, '_load_mixer_track_store',
        lambda repo_root: ({str(audio_file): {'hash': 'h1'}}, {'h1': {'bpm': 128.0}}),
    )
    monkeypatch.setattr(_MOD, '_load_read_tags', lambda: lambda p: {'genre': 'House'})

    rows = [
        {
            **_make_seq_row(bpm=127.5, track_path=str(audio_file), title='My Track', artist='My Artist'),
            'track_title': 'My Track',
            'track_artist': 'My Artist',
            'metadata_source': 'media-01',
            'recommended_profile_key': 'house',
        },
    ]
    report_path = _write_mixer_crossref_report(tmp_path, rows)
    assert report_path == tmp_path / 'mixer_crossref.md'
    text = report_path.read_text(encoding='utf-8')
    assert 'My Artist | My Track | 127.5 | 128.0 | house | House' in text


def test_write_mixer_crossref_report_applies_to_replay_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(_MOD, '_load_mixer_track_store', lambda repo_root: ({}, {}))
    monkeypatch.setattr(_MOD, '_load_read_tags', lambda: None)
    rows = [{**_make_seq_row(), 'metadata_source': 'replay'}]
    report_path = _write_mixer_crossref_report(tmp_path, rows)
    assert report_path is not None
    assert report_path.exists()


def test_write_mixer_crossref_report_flags_unanalyzed_tracks(tmp_path: Path, monkeypatch) -> None:
    """No mixer-store entry for this track -- reported by name in a
    dedicated section rather than silently showing '--' with no
    explanation, per the owner's "we should check" ask."""
    monkeypatch.setattr(_MOD, '_load_mixer_track_store', lambda repo_root: ({}, {}))
    monkeypatch.setattr(_MOD, '_load_read_tags', lambda: None)
    rows = [{**_make_seq_row(title='Unscanned Track'), 'track_title': 'Unscanned Track',
             'metadata_source': 'media-01'}]
    report_path = _write_mixer_crossref_report(tmp_path, rows)
    text = report_path.read_text(encoding='utf-8')
    assert '1 of 1 track(s) have no mixer-store BPM entry' in text
    assert 'Unscanned Track' in text


def test_write_mixer_crossref_report_missing_file_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    """track_path present in the row but the file no longer exists on this
    machine -- must not raise attempting the tag read."""
    monkeypatch.setattr(_MOD, '_load_mixer_track_store', lambda repo_root: ({}, {}))
    called = {'n': 0}

    def _fake_read_tags(p):
        called['n'] += 1
        return {'genre': 'should-not-be-called'}

    monkeypatch.setattr(_MOD, '_load_read_tags', lambda: _fake_read_tags)
    rows = [{**_make_seq_row(track_path=str(tmp_path / 'gone.mp3')), 'metadata_source': 'media-01'}]
    report_path = _write_mixer_crossref_report(tmp_path, rows)
    assert report_path is not None
    assert called['n'] == 0
    assert 'should-not-be-called' not in report_path.read_text(encoding='utf-8')


# ---- --corpus-dir / --logs-dir (2026-08-18, session_replay.py auto-package) --


def test_parse_args_corpus_dir_and_logs_dir_default_none(monkeypatch) -> None:
    monkeypatch.setattr('sys.argv', ['package_training_set.py'])
    args = _parse_args()
    assert args.corpus_dir is None
    assert args.logs_dir is None


def test_parse_args_corpus_dir_and_logs_dir_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('sys.argv', [
        'package_training_set.py',
        '--corpus-dir', str(tmp_path / 'corpus'),
        '--logs-dir', str(tmp_path / 'logs'),
    ])
    args = _parse_args()
    assert args.corpus_dir == tmp_path / 'corpus'
    assert args.logs_dir == tmp_path / 'logs'


def test_parse_args_sets_root_default_none(monkeypatch) -> None:
    monkeypatch.setattr('sys.argv', ['package_training_set.py'])
    assert _parse_args().sets_root is None


def test_parse_args_sets_root_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('sys.argv', [
        'package_training_set.py', '--sets-root', str(tmp_path / 'accelerated'),
    ])
    assert _parse_args().sets_root == tmp_path / 'accelerated'


def test_parse_args_training_root_default_none(monkeypatch) -> None:
    monkeypatch.setattr('sys.argv', ['package_training_set.py'])
    assert _parse_args().training_root is None


def test_parse_args_training_root_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('sys.argv', [
        'package_training_set.py', '--training-root', str(tmp_path / 'training'),
    ])
    assert _parse_args().training_root == tmp_path / 'training'


# ---- _append_session_log sets_root disambiguation (2026-08-19) --------


def test_append_session_log_default_sets_root_omits_prefix(tmp_path: Path) -> None:
    training_root = tmp_path / 'training'
    training_root.mkdir()
    sets_root = training_root / 'sets'
    set_dir = sets_root / 'my-playlist'
    bucket_dir = set_dir / '001'
    path = _append_session_log(training_root, sets_root, set_dir, bucket_dir,
                                '2026-08-19', 4, 5, '')
    text = path.read_text(encoding='utf-8')
    assert 'session=my-playlist/001 ' in text
    assert 'accelerated' not in text


def test_append_session_log_nondefault_sets_root_gets_prefixed(tmp_path: Path) -> None:
    training_root = tmp_path / 'training'
    training_root.mkdir()
    sets_root = training_root / 'accelerated'
    set_dir = sets_root / 'my-playlist'
    bucket_dir = set_dir / '001'
    path = _append_session_log(training_root, sets_root, set_dir, bucket_dir,
                                '2026-08-19', 4, 5, '')
    text = path.read_text(encoding='utf-8')
    assert 'session=accelerated/my-playlist/001 ' in text
