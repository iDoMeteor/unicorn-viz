"""Regression tests for tools/package_training_set.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

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
_score_lock_quality = _MOD._score_lock_quality
_BPM_LOCK_CONFIDENCE_FLOOR = _MOD._BPM_LOCK_CONFIDENCE_FLOOR
_cleanup_stale_empty_corpus_files = _MOD._cleanup_stale_empty_corpus_files
_load_profile_expected_values = _MOD._load_profile_expected_values
_format_profile_expected_values_block = _MOD._format_profile_expected_values_block
_build_combined_prompt = _MOD._build_combined_prompt
_format_reco_weights_line = _MOD._format_reco_weights_line
_RECO_WEIGHT_DEFAULTS = _MOD._RECO_WEIGHT_DEFAULTS

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
    }
    if event_type:
        row['event_type'] = event_type
    return row


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


def test_build_detector_payload_lock_coverage() -> None:
    locked_rows = [_make_seq_row(confidence=0.72) for _ in range(5)]
    unlocked_rows = [_make_seq_row(confidence=0.20) for _ in range(5)]
    payload = _build_detector_payload(locked_rows + unlocked_rows, 'set-a', 'a')
    assert payload['beat_lock']['coverage_pct'] == pytest.approx(50.0)


def test_build_detector_payload_empty_rows() -> None:
    payload = _build_detector_payload([], 'set-a', 'a')
    assert payload['total_rows'] == 0
    assert payload['song_count'] == 0
    assert payload['beat_lock']['coverage_pct'] == 0.0


def test_build_detector_payload_set_description_included() -> None:
    rows = [_make_seq_row()]
    payload = _build_detector_payload(rows, 'set-a', 'a', set_description='House night baseline run.')
    assert payload['set_description'] == 'House night baseline run.'


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


def test_run_llm_scoring_skips_gracefully_with_no_api_key(tmp_path: Path) -> None:
    rows = [_make_seq_row()]
    with patch.dict('os.environ', {'OPENAI_API_KEY': '', 'ANTHROPIC_API_KEY': ''}, clear=False):
        result = _run_llm_scoring(tmp_path, rows, 'set-a', 'a')
    assert result is None
    assert not (tmp_path / 'session_score.json').exists()


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


def test_reco_weights_line_used_consistently_in_both_prompt_spots() -> None:
    """The two weight mentions in the prompt used to be separate hand-typed
    lists that could silently drift from each other; both must now come from
    the same _RECO_WEIGHT_DEFAULTS dict via _format_reco_weights_line()."""
    detector_payload = {'essentia_available': False}
    prompt = _build_combined_prompt(detector_payload, {}, None)
    line = _format_reco_weights_line(_RECO_WEIGHT_DEFAULTS)
    assert prompt.count(line) == 2


def test_build_combined_prompt_uses_live_profile_values_not_stale_names() -> None:
    """No hardcoded/removed profile name (e.g. 'lofi', 'jazz', 'metal') should ever appear."""
    detector_payload = {'essentia_available': False}
    director_payload = {}
    prompt = _build_combined_prompt(detector_payload, director_payload, None)
    for stale_name in ('lofi:', 'jazz:', 'classical:', 'deep_house:', 'metal:', 'industrial:', 'reggae:'):
        assert stale_name not in prompt, f'stale profile {stale_name!r} leaked into prompt'
    assert 'house:' in prompt
