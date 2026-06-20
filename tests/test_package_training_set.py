"""Regression tests for tools/package_training_set.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'tools' / 'package_training_set.py'
_SPEC = importlib.util.spec_from_file_location('package_training_set', _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

_build_detector_payload = _MOD._build_detector_payload
_song_key = _MOD._song_key
_score_detector_with_llm = _MOD._score_detector_with_llm
_detect_llm_provider = _MOD._detect_llm_provider


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


# ---- _score_detector_with_llm skip / idempotent paths ----------------------


def test_score_detector_skip_flag(tmp_path: Path) -> None:
    result = _score_detector_with_llm(
        tmp_path, [], 'set-a', 'a', skip=True
    )
    assert result is None
    assert not (tmp_path / 'detector_score.json').exists()


def test_score_detector_returns_existing_without_api_call(tmp_path: Path) -> None:
    existing = tmp_path / 'detector_score.json'
    existing.write_text('{}', encoding='utf-8')
    with patch.object(_MOD, '_call_llm', side_effect=AssertionError('should not be called')):
        result = _score_detector_with_llm(
            tmp_path, [], 'set-a', 'a', force_regen=False
        )
    assert result == existing


def test_score_detector_skips_gracefully_with_no_api_key(tmp_path: Path) -> None:
    rows = [_make_seq_row()]
    with patch.dict('os.environ', {'OPENAI_API_KEY': '', 'ANTHROPIC_API_KEY': ''}, clear=False):
        result = _score_detector_with_llm(tmp_path, rows, 'set-a', 'a')
    assert result is None
    assert not (tmp_path / 'detector_score.json').exists()
