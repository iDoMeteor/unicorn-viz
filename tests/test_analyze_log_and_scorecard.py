"""Regression tests for training-kit-01's session analysis/reporting tools:
tools/analyze_autovj_log.py + tools/session_scorecard.py.

Both are offline JSONL log summarizers with zero prior test coverage.
"""
from __future__ import annotations

import importlib.util
import json
import statistics
import sys
from pathlib import Path

import pytest


_TOOLS_DIR = Path(__file__).resolve().parents[1] / 'drop-ins' / 'training-kit-01' / 'tools'

_ANALYZE_SPEC = importlib.util.spec_from_file_location('test_analyze_autovj_log_module', _TOOLS_DIR / 'analyze_autovj_log.py')
assert _ANALYZE_SPEC is not None and _ANALYZE_SPEC.loader is not None
_ANALYZE = importlib.util.module_from_spec(_ANALYZE_SPEC)
_ANALYZE_SPEC.loader.exec_module(_ANALYZE)

_SCORECARD_SPEC = importlib.util.spec_from_file_location('test_session_scorecard_module', _TOOLS_DIR / 'session_scorecard.py')
assert _SCORECARD_SPEC is not None and _SCORECARD_SPEC.loader is not None
_SCORECARD = importlib.util.module_from_spec(_SCORECARD_SPEC)
# session_scorecard.py uses @dataclass, which needs its module registered in
# sys.modules to resolve type annotations -- must be set before exec_module().
sys.modules[_SCORECARD_SPEC.name] = _SCORECARD
_SCORECARD_SPEC.loader.exec_module(_SCORECARD)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')


# ===========================================================================
# analyze_autovj_log.py
# ===========================================================================

def test_load_entries_skips_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / 'log.jsonl'
    path.write_text('{"a": 1}\nbroken\n{"a": 2}\n', encoding='utf-8')
    assert _ANALYZE._load_entries(path) == [{'a': 1}, {'a': 2}]


def test_pick_path_uses_explicit_argv() -> None:
    path = _ANALYZE._pick_path(['prog', '/some/explicit/path.jsonl'])
    assert path == Path('/some/explicit/path.jsonl')


def test_pick_path_finds_latest_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_ANALYZE, '_APP_ROOT', tmp_path)
    logs_dir = tmp_path / 'logs'
    logs_dir.mkdir()
    older = logs_dir / 'autovj-20260101T000000.jsonl'
    newer = logs_dir / 'autovj-20260102T000000.jsonl'
    older.write_text('{}\n')
    newer.write_text('{}\n')
    import os
    import time
    os.utime(older, (time.time() - 100, time.time() - 100))

    picked = _ANALYZE._pick_path(['prog'])
    assert picked == newer


def test_pick_path_raises_when_no_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_ANALYZE, '_APP_ROOT', tmp_path)
    (tmp_path / 'logs').mkdir()
    with pytest.raises(FileNotFoundError):
        _ANALYZE._pick_path(['prog'])


def test_main_raises_for_missing_explicit_log(tmp_path: Path) -> None:
    """Known behavior: unlike _pick_path()'s own no-logs-found case (which
    main() catches and turns into a return code 1), an explicit but
    nonexistent path argument is not guarded anywhere -- it propagates a
    raw FileNotFoundError out of _load_entries()'s read_text() call."""
    with pytest.raises(FileNotFoundError):
        _ANALYZE.main(['prog', str(tmp_path / 'nope.jsonl')])


def test_main_returns_1_for_empty_parseable_file(tmp_path: Path) -> None:
    path = tmp_path / 'empty.jsonl'
    path.write_text('not json at all\n', encoding='utf-8')
    assert _ANALYZE.main(['prog', str(path)]) == 1


def test_main_prints_action_breakdown(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = tmp_path / 'log.jsonl'
    _write_jsonl(path, [
        {'action': 'detector_tick', 't': 0.0, 'mode': 'CRUISE'},
        {'action': 'detector_tick', 't': 1.0, 'mode': 'CRUISE'},
        {'action': 'mode_transition', 't': 2.0, 'to_mode': 'BUILD'},
    ])

    rc = _ANALYZE.main(['prog', str(path)])

    out = capsys.readouterr().out
    assert rc == 0
    assert 'Entries: 3' in out
    assert 'detector_tick: 2' in out
    assert 'mode_transition: 1' in out
    assert 'BUILD: 1' in out


def test_main_detects_transition_burst(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = tmp_path / 'log.jsonl'
    _write_jsonl(path, [
        {'action': 'mode_transition', 't': 0.0, 'to_mode': 'BUILD'},
        {'action': 'mode_transition', 't': 0.5, 'to_mode': 'BREAKDOWN'},
        {'action': 'mode_transition', 't': 1.0, 'to_mode': 'BUILD'},
    ])

    _ANALYZE.main(['prog', str(path)])
    out = capsys.readouterr().out
    assert 'Transition bursts (>=3 transitions within 2s windows): 1' in out


def test_main_reports_detector_snapshots_by_mode(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = tmp_path / 'log.jsonl'
    _write_jsonl(path, [
        {'action': 'detector_tick', 't': 0.0, 'mode': 'BUILD', 'drop_score': 0.5, 'energy': 0.4, 'energy_slope': 0.1, 'bpm': 120.0, 'bass': 0.5, 'mid': 0.3, 'treble': 0.2},
        {'action': 'detector_tick', 't': 1.0, 'mode': 'BUILD', 'drop_score': 0.7, 'energy': 0.6, 'energy_slope': 0.2, 'bpm': 122.0, 'bass': 0.6, 'mid': 0.4, 'treble': 0.3},
    ])

    _ANALYZE.main(['prog', str(path)])
    out = capsys.readouterr().out
    assert 'BUILD: n=2' in out
    assert 'bpm_med=121.0' in out


def test_main_flags_missed_drop_window(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """A high drop_score BUILD tick with no DROP transition within 1.5s
    counts as a potential missed drop window."""
    path = tmp_path / 'log.jsonl'
    _write_jsonl(path, [
        {'action': 'detector_tick', 't': 0.0, 'mode': 'BUILD', 'drop_score': 0.90},
        {'action': 'mode_transition', 't': 10.0, 'to_mode': 'DROP'},  # far too late
    ])

    _ANALYZE.main(['prog', str(path)])
    out = capsys.readouterr().out
    assert 'Potential missed drop windows (BUILD drop_score>=0.75, no DROP within 1.5s): 1' in out


def test_main_does_not_flag_a_drop_that_followed_promptly(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = tmp_path / 'log.jsonl'
    _write_jsonl(path, [
        {'action': 'detector_tick', 't': 0.0, 'mode': 'BUILD', 'drop_score': 0.90},
        {'action': 'mode_transition', 't': 0.5, 'to_mode': 'DROP'},
    ])

    _ANALYZE.main(['prog', str(path)])
    out = capsys.readouterr().out
    assert 'Potential missed drop windows (BUILD drop_score>=0.75, no DROP within 1.5s): 0' in out


# ===========================================================================
# session_scorecard.py
# ===========================================================================

def _make_session(
    path: Path,
    *,
    n_ticks: int = 10,
    focus_profile: str = 'ambient',
    focus_ratio: float = 1.0,
    locked_ratio: float = 0.5,
) -> None:
    rows: list[dict] = []
    n_focus = int(n_ticks * focus_ratio)
    n_locked = int(n_ticks * locked_ratio)
    for i in range(n_ticks):
        rows.append({
            'action': 'detector_tick',
            't': float(i),
            'audio_profile_key': focus_profile if i < n_focus else 'house',
            'bpm_locked': i < n_locked,
            'confidence': 0.8,
            'downbeat_confidence': 0.5,
            'bpm': 100.0 + i,
        })
    rows.append({'action': 'profile_recommendation', 't': 5.0, 'recommended_profile_key': focus_profile, 'score_margin': 0.5})
    rows.append({'action': 'mode_transition', 't': 3.0, 'to_mode': 'BUILD'})
    _write_jsonl(path, rows)


def test_score_returns_none_below_min_profile_share(tmp_path: Path) -> None:
    path = tmp_path / 'log.jsonl'
    _make_session(path, focus_profile='ambient', focus_ratio=0.2)

    result = _SCORECARD._score(path, 'ambient', min_profile_share=0.70)
    assert result is None


def test_score_returns_none_with_no_detector_ticks(tmp_path: Path) -> None:
    path = tmp_path / 'log.jsonl'
    _write_jsonl(path, [{'action': 'mode_transition', 't': 0.0, 'to_mode': 'BUILD'}])

    result = _SCORECARD._score(path, 'ambient', min_profile_share=0.70)
    assert result is None


def test_score_computes_focus_share_and_lock_pct(tmp_path: Path) -> None:
    path = tmp_path / 'log.jsonl'
    _make_session(path, n_ticks=10, focus_profile='ambient', focus_ratio=1.0, locked_ratio=0.5)

    result = _SCORECARD._score(path, 'ambient', min_profile_share=0.70)
    assert result is not None
    assert result.focus_profile_share == pytest.approx(1.0)
    assert result.lock_pct == pytest.approx(0.5)
    assert result.ticks == 10


def test_score_computes_bpm_percentiles(tmp_path: Path) -> None:
    path = tmp_path / 'log.jsonl'
    _make_session(path, n_ticks=10)

    result = _SCORECARD._score(path, 'ambient', min_profile_share=0.70)
    bpms = [100.0 + i for i in range(10)]
    assert result.bpm_p50 == pytest.approx(statistics.median(bpms))


def test_score_lock_score_matches_documented_weights(tmp_path: Path) -> None:
    """lock_score = 100 * (0.55*lock_pct + 0.30*mean_conf + 0.15*mean_dconf)."""
    path = tmp_path / 'log.jsonl'
    _make_session(path, n_ticks=10, locked_ratio=0.5)

    result = _SCORECARD._score(path, 'ambient', min_profile_share=0.70)
    expected = 100.0 * (0.55 * result.lock_pct + 0.30 * result.mean_conf + 0.15 * result.mean_dconf)
    assert result.lock_score == pytest.approx(expected)


def test_score_reco_score_matches_documented_weights(tmp_path: Path) -> None:
    path = tmp_path / 'log.jsonl'
    _make_session(path, n_ticks=10)

    result = _SCORECARD._score(path, 'ambient', min_profile_share=0.70)
    expected = 100.0 * (
        0.70 * result.reco_focus_share
        + 0.20 * (1.0 - min(1.0, result.reco_churn_per_min / 6.0))
        + 0.10 * (1.0 - result.reco_low_margin_rate)
    )
    assert result.reco_score == pytest.approx(expected)


def test_score_reco_churn_counts_consecutive_key_changes(tmp_path: Path) -> None:
    path = tmp_path / 'log.jsonl'
    rows = [
        {'action': 'detector_tick', 't': 0.0, 'audio_profile_key': 'ambient', 'bpm_locked': True, 'confidence': 0.8, 'downbeat_confidence': 0.5, 'bpm': 100.0},
        {'action': 'detector_tick', 't': 60.0, 'audio_profile_key': 'ambient', 'bpm_locked': True, 'confidence': 0.8, 'downbeat_confidence': 0.5, 'bpm': 100.0},
        {'action': 'profile_recommendation', 't': 10.0, 'recommended_profile_key': 'ambient', 'score_margin': 0.5},
        {'action': 'profile_recommendation', 't': 20.0, 'recommended_profile_key': 'chillstep', 'score_margin': 0.5},
        {'action': 'profile_recommendation', 't': 30.0, 'recommended_profile_key': 'ambient', 'score_margin': 0.5},
    ]
    _write_jsonl(path, rows)

    result = _SCORECARD._score(path, 'ambient', min_profile_share=0.70)
    # duration_min = (60-0)/60 = 1.0; 2 changes (ambient->chillstep->ambient) / 1.0 min
    assert result.reco_churn_per_min == pytest.approx(2.0)


def test_safe_p90_empty() -> None:
    assert _SCORECARD._safe_p90([]) == 0.0


def test_safe_p90_single_value() -> None:
    assert _SCORECARD._safe_p90([42.0]) == 42.0


def test_write_markdown_includes_header_and_aggregate(tmp_path: Path) -> None:
    path = tmp_path / 'log.jsonl'
    _make_session(path, n_ticks=10)
    score = _SCORECARD._score(path, 'ambient', min_profile_share=0.70)
    assert score is not None

    out_path = tmp_path / 'scorecard.md'
    _SCORECARD._write_markdown([score], 'ambient', out_path, [path])

    text = out_path.read_text()
    assert '# Auto VJ Session Scorecard (ambient)' in text
    assert '## Aggregate' in text
    assert '## Session Detail' in text
    assert path.name in text


def test_write_markdown_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / 'log.jsonl'
    _make_session(path, n_ticks=10)
    score = _SCORECARD._score(path, 'ambient', min_profile_share=0.70)

    out_path = tmp_path / 'nested' / 'dir' / 'scorecard.md'
    _SCORECARD._write_markdown([score], 'ambient', out_path, [path])

    assert out_path.exists()


def test_main_writes_scorecard_and_reports_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    log_path = tmp_path / 'session.jsonl'
    _make_session(log_path, n_ticks=10)
    out_path = tmp_path / 'out.md'

    monkeypatch.setattr(sys, 'argv', ['session_scorecard.py', str(log_path), '--focus-profile', 'ambient', '--out', str(out_path)])

    rc = _SCORECARD.main()

    assert rc == 0
    assert out_path.exists()
    assert 'Wrote markdown scorecard' in capsys.readouterr().out


def test_main_returns_1_when_no_sessions_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    log_path = tmp_path / 'session.jsonl'
    _make_session(log_path, n_ticks=10, focus_profile='ambient', focus_ratio=0.1)  # below default 0.70 share

    monkeypatch.setattr(sys, 'argv', ['session_scorecard.py', str(log_path), '--focus-profile', 'ambient'])

    rc = _SCORECARD.main()

    assert rc == 1
    assert 'No matching sessions found' in capsys.readouterr().out


def test_main_writes_json_output_when_requested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / 'session.jsonl'
    _make_session(log_path, n_ticks=10)
    out_path = tmp_path / 'out.md'
    json_path = tmp_path / 'out.json'

    monkeypatch.setattr(sys, 'argv', [
        'session_scorecard.py', str(log_path),
        '--focus-profile', 'ambient', '--out', str(out_path), '--json-out', str(json_path),
    ])

    _SCORECARD.main()

    data = json.loads(json_path.read_text())
    assert len(data) == 1
    assert data[0]['file'] == log_path.name
