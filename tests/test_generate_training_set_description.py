"""Regression tests for training-kit-01's
tools/generate_training_set_description.py.

Zero prior coverage. main() is not exercised end-to-end here: it hardcodes
`Path(__file__).resolve().parents[3] / 'assets' / 'training' / 'sets'` with
no override, so a real invocation would need to read/write inside this
project's actual assets/training/sets/ directory -- not something a test
should touch. Every function main() calls is tested directly instead,
which covers the real decision-making logic; main() itself is thin I/O
orchestration around them.

Network calls (_itunes_lookup, _generate_with_llm) are mocked -- tests
must not depend on internet access or real API keys.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_TOOLS_DIR = Path(__file__).resolve().parents[1] / 'drop-ins' / 'training-kit-01' / 'tools'
_SPEC = importlib.util.spec_from_file_location(
    'test_generate_training_set_description_module', _TOOLS_DIR / 'generate_training_set_description.py',
)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
# Uses @dataclass (TrackFact) -- must be registered in sys.modules before
# exec_module() so type-annotation resolution doesn't fail (see the same
# fix in test_analyze_log_and_scorecard.py for session_scorecard.py).
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')


# ---------------------------------------------------------------------------
# _read_jsonl()
# ---------------------------------------------------------------------------

def test_read_jsonl_skips_malformed_and_non_dict_lines(tmp_path: Path) -> None:
    path = tmp_path / 'x.jsonl'
    path.write_text('{"a": 1}\nnot json\n[1, 2, 3]\n{"a": 2}\n\n', encoding='utf-8')
    assert _MOD._read_jsonl(path) == [{'a': 1}, {'a': 2}]


# ---------------------------------------------------------------------------
# _to_float()
# ---------------------------------------------------------------------------

def test_to_float_passes_through_numbers() -> None:
    assert _MOD._to_float(3.5) == 3.5
    assert _MOD._to_float(3) == 3.0


def test_to_float_returns_default_for_non_numeric() -> None:
    assert _MOD._to_float('not a number') == 0.0
    assert _MOD._to_float(None, default=1.5) == 1.5


# ---------------------------------------------------------------------------
# _pick_latest_dir() / _pick_bucket()
# ---------------------------------------------------------------------------

def test_pick_latest_dir_returns_none_for_empty_parent(tmp_path: Path) -> None:
    assert _MOD._pick_latest_dir(tmp_path) is None


def test_pick_latest_dir_returns_most_recently_modified(tmp_path: Path) -> None:
    import os
    import time

    older = tmp_path / 'a'
    newer = tmp_path / 'b'
    older.mkdir()
    newer.mkdir()
    os.utime(older, (time.time() - 100, time.time() - 100))

    assert _MOD._pick_latest_dir(tmp_path) == newer


def test_pick_bucket_with_explicit_set_and_bucket(tmp_path: Path) -> None:
    bucket_dir = tmp_path / 'my-set' / 'a'
    bucket_dir.mkdir(parents=True)

    result = _MOD._pick_bucket(tmp_path, 'my-set', 'a')
    assert result == bucket_dir


def test_pick_bucket_falls_back_to_latest_set_and_bucket(tmp_path: Path) -> None:
    bucket_dir = tmp_path / 'only-set' / 'only-bucket'
    bucket_dir.mkdir(parents=True)

    result = _MOD._pick_bucket(tmp_path, None, None)
    assert result == bucket_dir


def test_pick_bucket_raises_when_no_sets_exist(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _MOD._pick_bucket(tmp_path, None, None)


def test_pick_bucket_raises_when_named_set_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _MOD._pick_bucket(tmp_path, 'nonexistent-set', 'a')


def test_pick_bucket_raises_when_named_bucket_missing(tmp_path: Path) -> None:
    (tmp_path / 'my-set').mkdir()
    with pytest.raises(FileNotFoundError):
        _MOD._pick_bucket(tmp_path, 'my-set', 'nonexistent-bucket')


# ---------------------------------------------------------------------------
# _find_corpus_file()
# ---------------------------------------------------------------------------

def test_find_corpus_file_matches_pattern(tmp_path: Path) -> None:
    (tmp_path / 'sequence-corpus-20260101.jsonl').write_text('{}\n')
    result = _MOD._find_corpus_file(tmp_path, ['sequence-corpus*.jsonl'])
    assert result.name == 'sequence-corpus-20260101.jsonl'


def test_find_corpus_file_picks_most_recent_when_multiple_match(tmp_path: Path) -> None:
    import os
    import time

    older = tmp_path / 'sequence-corpus-a.jsonl'
    newer = tmp_path / 'sequence-corpus-b.jsonl'
    older.write_text('{}\n')
    newer.write_text('{}\n')
    os.utime(older, (time.time() - 100, time.time() - 100))

    result = _MOD._find_corpus_file(tmp_path, ['sequence-corpus*.jsonl'])
    assert result == newer


def test_find_corpus_file_raises_when_nothing_matches(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _MOD._find_corpus_file(tmp_path, ['sequence-corpus*.jsonl'])


# ---------------------------------------------------------------------------
# _itunes_lookup() — network mocked
# ---------------------------------------------------------------------------

def _mock_urlopen_response(payload: dict) -> MagicMock:
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps(payload).encode('utf-8')
    return cm


def test_itunes_lookup_prefers_exact_artist_and_title_match() -> None:
    payload = {
        'results': [
            {'artistName': 'Wrong Artist', 'trackName': 'Some Song'},
            {'artistName': 'Real Artist', 'trackName': 'Real Song'},
        ]
    }
    with patch('urllib.request.urlopen', return_value=_mock_urlopen_response(payload)):
        result = _MOD._itunes_lookup('Real Artist', 'Real Song')
    assert result['artistName'] == 'Real Artist'


def test_itunes_lookup_falls_back_to_artist_only_match() -> None:
    payload = {
        'results': [
            {'artistName': 'Real Artist', 'trackName': 'A Different Song'},
        ]
    }
    with patch('urllib.request.urlopen', return_value=_mock_urlopen_response(payload)):
        result = _MOD._itunes_lookup('Real Artist', 'Real Song')
    assert result['artistName'] == 'Real Artist'


def test_itunes_lookup_falls_back_to_first_result() -> None:
    payload = {'results': [{'artistName': 'Someone Else', 'trackName': 'Unrelated'}]}
    with patch('urllib.request.urlopen', return_value=_mock_urlopen_response(payload)):
        result = _MOD._itunes_lookup('Real Artist', 'Real Song')
    assert result['artistName'] == 'Someone Else'


def test_itunes_lookup_returns_empty_dict_for_no_results() -> None:
    payload = {'results': []}
    with patch('urllib.request.urlopen', return_value=_mock_urlopen_response(payload)):
        result = _MOD._itunes_lookup('Artist', 'Title')
    assert result == {}


def test_itunes_lookup_returns_empty_dict_on_network_exception() -> None:
    with patch('urllib.request.urlopen', side_effect=OSError('network down')):
        result = _MOD._itunes_lookup('Artist', 'Title')
    assert result == {}


# ---------------------------------------------------------------------------
# _build_track_facts()
# ---------------------------------------------------------------------------

def test_build_track_facts_groups_rows_by_track_id() -> None:
    rows = [
        {'track_id': 't1', 'track_artist': 'Artist A', 'track_title': 'Song A', 'bpm': 120.0, 'audio_profile_key': 'house', 'analysis_generated_at': '2026-01-01T00:00:00Z'},
        {'track_id': 't1', 'track_artist': 'Artist A', 'track_title': 'Song A', 'bpm': 122.0, 'audio_profile_key': 'house', 'analysis_generated_at': '2026-01-01T00:01:00Z'},
        {'track_id': 't2', 'track_artist': 'Artist B', 'track_title': 'Song B', 'bpm': 128.0, 'audio_profile_key': 'tech_house', 'analysis_generated_at': '2026-01-01T00:02:00Z'},
    ]
    tracks = _MOD._build_track_facts(rows, use_itunes=False)

    assert len(tracks) == 2
    t1 = next(t for t in tracks if t.track_id == 't1')
    assert t1.seq_rows == 2
    assert t1.avg_bpm == pytest.approx(121.0)
    assert t1.dominant_profile == 'house'


def test_build_track_facts_skips_rows_without_track_id() -> None:
    rows = [{'track_artist': 'No ID'}]
    tracks = _MOD._build_track_facts(rows, use_itunes=False)
    assert tracks == []


def test_build_track_facts_falls_back_to_legacy_spotify_prefixed_fields() -> None:
    """Backward compat for corpus rows predating the generic-field rename."""
    rows = [{'spotify_track_id': 't1', 'spotify_artist': 'Legacy Artist', 'spotify_title': 'Legacy Song', 'bpm': 100.0}]
    tracks = _MOD._build_track_facts(rows, use_itunes=False)
    assert len(tracks) == 1
    assert tracks[0].artist == 'Legacy Artist'
    assert tracks[0].title == 'Legacy Song'


def test_build_track_facts_orders_by_start_time() -> None:
    rows = [
        {'track_id': 't2', 'track_artist': 'B', 'track_title': 'B', 'analysis_generated_at': '2026-01-01T00:02:00Z'},
        {'track_id': 't1', 'track_artist': 'A', 'track_title': 'A', 'analysis_generated_at': '2026-01-01T00:01:00Z'},
    ]
    tracks = _MOD._build_track_facts(rows, use_itunes=False)
    assert [t.track_id for t in tracks] == ['t1', 't2']
    assert [t.index for t in tracks] == [1, 2]


def test_build_track_facts_dominant_profile_is_most_common() -> None:
    rows = [
        {'track_id': 't1', 'track_artist': 'A', 'track_title': 'A', 'audio_profile_key': 'house'},
        {'track_id': 't1', 'track_artist': 'A', 'track_title': 'A', 'audio_profile_key': 'house'},
        {'track_id': 't1', 'track_artist': 'A', 'track_title': 'A', 'audio_profile_key': 'chillstep'},
    ]
    tracks = _MOD._build_track_facts(rows, use_itunes=False)
    assert tracks[0].dominant_profile == 'house'


def test_build_track_facts_does_not_call_itunes_when_disabled() -> None:
    rows = [{'track_id': 't1', 'track_artist': 'A', 'track_title': 'A'}]
    with patch.object(_MOD, '_itunes_lookup') as mock_lookup:
        _MOD._build_track_facts(rows, use_itunes=False)
    mock_lookup.assert_not_called()


# ---------------------------------------------------------------------------
# _parse_scorecard()
# ---------------------------------------------------------------------------

def test_parse_scorecard_missing_file_returns_empty_dict(tmp_path: Path) -> None:
    assert _MOD._parse_scorecard(tmp_path / 'nope.md') == {}


def test_parse_scorecard_extracts_backtick_values(tmp_path: Path) -> None:
    path = tmp_path / 'scorecard.md'
    path.write_text('- Sequence rows: `1234`\n- BPM median: `124.5`\n', encoding='utf-8')
    result = _MOD._parse_scorecard(path)
    assert result['sequence_rows'] == '1234'
    assert result['bpm_median'] == '124.5'


def test_parse_scorecard_extracts_plain_colon_values(tmp_path: Path) -> None:
    path = tmp_path / 'scorecard.md'
    path.write_text('- Live rows: 500\n- Duration: 45 min\n', encoding='utf-8')
    result = _MOD._parse_scorecard(path)
    assert result['live_rows'] == '500'
    assert result['duration'] == '45 min'


def test_parse_scorecard_extracts_all_documented_fields(tmp_path: Path) -> None:
    path = tmp_path / 'scorecard.md'
    path.write_text(
        '\n'.join([
            '- Sequence rows: 1',
            '- Live rows: 2',
            '- Duration: 3',
            '- BPM median: 4',
            '- BPM range: 5',
            '- Mode transitions: 6',
            '- Drop fires: 7',
            '- Impact fires: 8',
        ]),
        encoding='utf-8',
    )
    result = _MOD._parse_scorecard(path)
    assert set(result.keys()) == {
        'sequence_rows', 'live_rows', 'duration', 'bpm_median',
        'bpm_range', 'mode_transitions', 'drop_fires', 'impact_fires',
    }


# ---------------------------------------------------------------------------
# _extract_session_note()
# ---------------------------------------------------------------------------

def test_extract_session_note_missing_log_returns_empty(tmp_path: Path) -> None:
    assert _MOD._extract_session_note(tmp_path, 'my-set', 'a') == ''


def test_extract_session_note_finds_matching_line(tmp_path: Path) -> None:
    log = tmp_path / 'SESSION_TRAINING_LOG.md'
    log.write_text(
        'unrelated line\n'
        'session=my-set/a notes here\n'
        'session=other-set/b other notes\n',
        encoding='utf-8',
    )
    result = _MOD._extract_session_note(tmp_path, 'my-set', 'a')
    assert 'session=my-set/a' in result


def test_extract_session_note_returns_most_recent_match(tmp_path: Path) -> None:
    """Searches in reverse -- the LAST matching line wins."""
    log = tmp_path / 'SESSION_TRAINING_LOG.md'
    log.write_text(
        'session=my-set/a first note\n'
        'session=my-set/a second note\n',
        encoding='utf-8',
    )
    result = _MOD._extract_session_note(tmp_path, 'my-set', 'a')
    assert 'second note' in result


# ---------------------------------------------------------------------------
# _profile_mix()
# ---------------------------------------------------------------------------

def test_profile_mix_counts_and_sorts_descending() -> None:
    rows = [
        {'audio_profile_key': 'house'},
        {'audio_profile_key': 'house'},
        {'audio_profile_key': 'chillstep'},
    ]
    result = _MOD._profile_mix(rows)
    assert result[0] == ('house', 2)
    assert result[1] == ('chillstep', 1)


def test_profile_mix_defaults_to_unknown() -> None:
    result = _MOD._profile_mix([{}])
    assert result == [('unknown', 1)]


# ---------------------------------------------------------------------------
# _local_set_summary() / _render_local_markdown()
# ---------------------------------------------------------------------------

def _fake_track(index: int = 1, avg_bpm: float = 120.0, profile: str = 'house', metadata: dict | None = None) -> "_MOD.TrackFact":
    return _MOD.TrackFact(
        index=index, track_id=f't{index}', artist='Artist', title='Title', album='Album',
        start_utc='2026-01-01T00:00:00Z', end_utc='2026-01-01T00:05:00Z',
        seq_rows=10, avg_bpm=avg_bpm, avg_bpm_conf=0.9, avg_rms=0.5,
        avg_loudness=-8.0, avg_danceability=0.7, dominant_profile=profile,
        metadata=metadata or {},
    )


def test_local_set_summary_mentions_track_count_and_bpm_range() -> None:
    tracks = [_fake_track(1, avg_bpm=118.0), _fake_track(2, avg_bpm=130.0)]
    summary = _MOD._local_set_summary('test context', [('house', 2)], tracks)
    assert '2 tracks' in summary
    assert '118' in summary
    assert '130' in summary


def test_local_set_summary_singular_for_one_track() -> None:
    summary = _MOD._local_set_summary('ctx', [], [_fake_track(1)])
    assert '1 track ' in summary


def test_render_local_markdown_includes_all_documented_sections() -> None:
    tracks = [_fake_track(1, metadata={'releaseDate': '2020', 'primaryGenreName': 'House'})]
    markdown = _MOD._render_local_markdown(
        set_name='my-set', bucket_name='a', playlist_context='ctx',
        scorecard={'duration': '30 min'}, session_note='a note',
        profile_mix=[('house', 1)], tracks=tracks,
    )

    assert '# Training Set Description' in markdown
    assert '## Set Summary' in markdown
    assert '## Snapshot Metrics' in markdown
    assert '## Track Flow (Chronological)' in markdown
    assert '## Per-Track Notes' in markdown
    assert '## Automation Notes' in markdown
    assert 'my-set' in markdown
    assert 'a note' in markdown


# ---------------------------------------------------------------------------
# _extract_output_text()
# ---------------------------------------------------------------------------

def test_extract_output_text_prefers_output_text_field() -> None:
    assert _MOD._extract_output_text({'output_text': '  hello  '}) == 'hello'


def test_extract_output_text_falls_back_to_output_content_blocks() -> None:
    payload = {
        'output': [
            {'content': [{'text': 'part one'}, {'text': 'part two'}]},
        ]
    }
    assert _MOD._extract_output_text(payload) == 'part one\npart two'


def test_extract_output_text_returns_empty_for_unrecognized_shape() -> None:
    assert _MOD._extract_output_text({'something_else': True}) == ''


# ---------------------------------------------------------------------------
# _generate_with_llm() — network mocked
# ---------------------------------------------------------------------------

def test_generate_with_llm_raises_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    with pytest.raises(RuntimeError, match='OPENAI_API_KEY'):
        _MOD._generate_with_llm('gpt-5.3-codex', {})


def test_generate_with_llm_returns_extracted_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    response_payload = {'output_text': 'Generated markdown content'}
    with patch('urllib.request.urlopen', return_value=_mock_urlopen_response(response_payload)):
        result = _MOD._generate_with_llm('gpt-5.3-codex', {'set_name': 'x'})
    assert result == 'Generated markdown content'


def test_generate_with_llm_raises_when_response_has_no_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    with patch('urllib.request.urlopen', return_value=_mock_urlopen_response({})):
        with pytest.raises(RuntimeError, match='did not contain output text'):
            _MOD._generate_with_llm('gpt-5.3-codex', {})


# ---------------------------------------------------------------------------
# _load_dotenv_fallback() — mirrors package_training_set.py's loader of the
# same name; this script is also directly runnable standalone, so it needs
# its own copy rather than relying on packaging having already loaded .env.
# ---------------------------------------------------------------------------

def test_load_dotenv_fallback_sets_missing_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / '.env').write_text('OPENAI_API_KEY=sk-from-dotenv\n', encoding='utf-8')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    _MOD._load_dotenv_fallback(tmp_path)
    assert os.environ['OPENAI_API_KEY'] == 'sk-from-dotenv'


def test_load_dotenv_fallback_never_overrides_real_shell_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / '.env').write_text('OPENAI_API_KEY=sk-from-dotenv\n', encoding='utf-8')
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-real-shell-value')
    _MOD._load_dotenv_fallback(tmp_path)
    assert os.environ['OPENAI_API_KEY'] == 'sk-real-shell-value'
