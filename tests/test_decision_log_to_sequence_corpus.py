"""Tests for the decision-log -> sequence-corpus converter."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    'test_decision_log_to_sequence_corpus_module',
    _REPO / 'drop-ins' / 'training-kit-01' / 'tools' / 'decision_log_to_sequence_corpus.py')
assert spec is not None and spec.loader is not None
_mod = importlib.util.module_from_spec(spec)
sys.modules['test_decision_log_to_sequence_corpus_module'] = _mod
spec.loader.exec_module(_mod)


def test_convert_row_renames_and_duplicates_fields() -> None:
    row = {
        'action': 'detector_tick', 't': 123.4, 'confidence': 0.82,
        'effect': 'Audio Spectrum', 'mode': 'CRUISE', 'profile': 'normie',
        'bpm': 128.0, 'bpm_locked': True, 'track_id': 'media:Song.mp3',
    }
    out = _mod.convert_row(row, {'Song.mp3': '/library/Song.mp3'})

    assert out['capture_time'] == 123.4
    assert out['bpm_confidence'] == 0.82
    assert out['effect_name'] == 'Audio Spectrum'
    assert out['mode'] == 'CRUISE' and out['vj_mode'] == 'CRUISE'
    assert out['profile'] == 'normie' and out['vj_profile'] == 'normie'
    assert out['track_path'] == '/library/Song.mp3'
    # untouched passthrough fields survive unchanged
    assert out['bpm'] == 128.0 and out['bpm_locked'] is True
    # renamed/consumed source keys and the discriminator don't leak through
    assert 't' not in out and 'confidence' not in out and 'effect' not in out
    assert 'action' not in out


def test_convert_row_handles_missing_track_id() -> None:
    row = {'action': 'detector_tick', 't': 1.0, 'confidence': 0.5, 'bpm': 100.0}
    out = _mod.convert_row(row, {})
    assert 'track_path' not in out or out['track_path'] == ''


def test_resolve_track_path_matches_by_filename() -> None:
    index = {'A - B (Original Mix).mp3': '/crates/house/A - B (Original Mix).mp3'}
    assert (_mod.resolve_track_path('media:A - B (Original Mix).mp3', index)
            == '/crates/house/A - B (Original Mix).mp3')
    assert _mod.resolve_track_path('media:Missing.mp3', index) == ''
    assert _mod.resolve_track_path('', index) == ''
    assert _mod.resolve_track_path('spotify:track:abc123', index) == ''


def test_convert_files_filters_to_detector_tick_and_sorts_by_time(tmp_path: Path) -> None:
    p = tmp_path / 'autovj-1.jsonl'
    lines = [
        json.dumps({'action': 'detector_tick', 't': 5.0, 'confidence': 0.9, 'bpm': 120.0}),
        json.dumps({'action': 'mode_transition', 't': 2.0, 'mode': 'BUILD'}),
        json.dumps({'action': 'detector_tick', 't': 1.0, 'confidence': 0.1, 'bpm': 60.0}),
        '',            # blank line must be skipped
        'not json',    # malformed line must be skipped, not crash the batch
    ]
    p.write_text('\n'.join(lines), encoding='utf-8')

    rows = _mod.convert_files([p], tmp_path)

    assert len(rows) == 2
    assert [r['capture_time'] for r in rows] == [1.0, 5.0]  # sorted


def test_build_filename_index_scans_recursively(tmp_path: Path) -> None:
    (tmp_path / 'house').mkdir()
    (tmp_path / 'house' / 'Track.mp3').write_bytes(b'x')
    (tmp_path / 'trance').mkdir()
    (tmp_path / 'trance' / 'Other.mp3').write_bytes(b'x')

    index = _mod.build_filename_index(tmp_path)

    assert set(index) == {'Track.mp3', 'Other.mp3'}
    assert index['Track.mp3'] == str((tmp_path / 'house' / 'Track.mp3').resolve())


def test_main_writes_jsonl_and_reports_resolution_rate(tmp_path: Path, capsys) -> None:
    music_root = tmp_path / 'music'
    (music_root).mkdir()
    (music_root / 'Known.mp3').write_bytes(b'x')

    autovj = tmp_path / 'autovj-1.jsonl'
    autovj.write_text('\n'.join(json.dumps(r) for r in [
        {'action': 'detector_tick', 't': 1.0, 'confidence': 0.5, 'bpm': 120.0,
         'track_id': 'media:Known.mp3'},
        {'action': 'detector_tick', 't': 2.0, 'confidence': 0.6, 'bpm': 121.0,
         'track_id': 'media:Unknown.mp3'},
    ]), encoding='utf-8')
    out_path = tmp_path / 'out' / 'sequence-corpus-converted.jsonl'

    rc = _mod.main(['--music-root', str(music_root), '--out', str(out_path), str(autovj)])

    assert rc == 0
    lines = out_path.read_text(encoding='utf-8').strip().splitlines()
    assert len(lines) == 2
    rows = [json.loads(line) for line in lines]
    assert rows[0]['track_path'].endswith('Known.mp3')
    assert 'track_path' not in rows[1] or rows[1]['track_path'] == ''
    captured = capsys.readouterr()
    assert '1/2' in captured.out or '50.0%' in captured.out


def test_main_errors_when_no_detector_tick_rows(tmp_path: Path) -> None:
    autovj = tmp_path / 'autovj-1.jsonl'
    autovj.write_text(json.dumps({'action': 'mode_transition', 't': 1.0}) + '\n', encoding='utf-8')

    rc = _mod.main(['--music-root', str(tmp_path), '--out', str(tmp_path / 'out.jsonl'),
                    str(autovj)])

    assert rc == 1
