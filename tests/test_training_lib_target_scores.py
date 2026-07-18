"""Unit tests for training_lib.compute_override_target_scores()."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'training-kit-01' / 'tools' / 'training' / 'training_lib.py'
_SPEC = importlib.util.spec_from_file_location('training_lib', _MOD_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD    # @dataclass needs this registered before exec (Py3.14)
_SPEC.loader.exec_module(_MOD)

compute_override_target_scores = _MOD.compute_override_target_scores


def _write_seq(path: Path, rows: list[dict]) -> None:
    path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')


def test_no_override_scores_perfect(tmp_path: Path) -> None:
    seq = tmp_path / 'sequence-corpus-a.jsonl'
    _write_seq(seq, [
        {'spotify_track_id': 'spotify:track:aaa', 'event_type': 'bpm_lock_gained'},
        {'spotify_track_id': 'spotify:track:aaa', 'event_type': 'bpm_lock_gained'},
    ])
    scores = compute_override_target_scores([seq])
    assert scores == {'spotify:track:aaa': 1.0}


def test_single_override_applies_default_penalty(tmp_path: Path) -> None:
    seq = tmp_path / 'sequence-corpus-a.jsonl'
    _write_seq(seq, [
        {'spotify_track_id': 'spotify:track:aaa', 'event_type': 'profile_switch',
         'reason': 'manual_override'},
    ])
    scores = compute_override_target_scores([seq])
    assert scores['spotify:track:aaa'] == 0.6


def test_multiple_overrides_stack_and_floor_at_zero(tmp_path: Path) -> None:
    seq = tmp_path / 'sequence-corpus-a.jsonl'
    _write_seq(seq, [
        {'spotify_track_id': 'spotify:track:aaa', 'event_type': 'profile_switch',
         'reason': 'manual_override'}
        for _ in range(5)
    ])
    scores = compute_override_target_scores([seq])
    assert scores['spotify:track:aaa'] == 0.0    # 1.0 - 0.4*5 floored, not negative


def test_non_override_profile_switch_is_not_penalized(tmp_path: Path) -> None:
    seq = tmp_path / 'sequence-corpus-a.jsonl'
    _write_seq(seq, [
        {'spotify_track_id': 'spotify:track:aaa', 'event_type': 'profile_switch',
         'reason': 'auto bpm 124'},
    ])
    scores = compute_override_target_scores([seq])
    assert scores['spotify:track:aaa'] == 1.0


def test_custom_penalty_per_override(tmp_path: Path) -> None:
    seq = tmp_path / 'sequence-corpus-a.jsonl'
    _write_seq(seq, [
        {'spotify_track_id': 'spotify:track:aaa', 'event_type': 'profile_switch',
         'reason': 'manual_override'},
    ])
    scores = compute_override_target_scores([seq], penalty_per_override=0.25)
    assert scores['spotify:track:aaa'] == 0.75


def test_missing_file_and_empty_input_produce_no_scores(tmp_path: Path) -> None:
    assert compute_override_target_scores([]) == {}
    assert compute_override_target_scores([tmp_path / 'does-not-exist.jsonl']) == {}


def test_matches_real_track_id_field_not_just_spotify_track_id(tmp_path: Path) -> None:
    """_build_live_training_row() (auto_vj.py) writes the sequence-corpus
    track key as 'track_id', not 'spotify_track_id' -- this must still match."""
    seq = tmp_path / 'sequence-corpus-a.jsonl'
    _write_seq(seq, [
        {'track_id': 'spotify:track:aaa', 'event_type': 'profile_switch',
         'reason': 'manual_override'},
    ])
    scores = compute_override_target_scores([seq])
    assert scores == {'spotify:track:aaa': 0.6}
