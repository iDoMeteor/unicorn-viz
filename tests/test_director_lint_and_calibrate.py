"""Regression tests for training-kit-01's offline director analysis tools:
tools/director_lint.py + tools/director_calibrate.py.

Both are offline-only JSONL log readers with zero prior test coverage.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


_TOOLS_DIR = Path(__file__).resolve().parents[1] / 'drop-ins' / 'training-kit-01' / 'tools'

_LINT_SPEC = importlib.util.spec_from_file_location('test_director_lint_module', _TOOLS_DIR / 'director_lint.py')
assert _LINT_SPEC is not None and _LINT_SPEC.loader is not None
_LINT = importlib.util.module_from_spec(_LINT_SPEC)
_LINT_SPEC.loader.exec_module(_LINT)

_CAL_SPEC = importlib.util.spec_from_file_location('test_director_calibrate_module', _TOOLS_DIR / 'director_calibrate.py')
assert _CAL_SPEC is not None and _CAL_SPEC.loader is not None
_CAL = importlib.util.module_from_spec(_CAL_SPEC)
_CAL_SPEC.loader.exec_module(_CAL)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')


# ---------------------------------------------------------------------------
# director_lint.py — _load_jsonl()
# ---------------------------------------------------------------------------

def test_load_jsonl_skips_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / 'log.jsonl'
    path.write_text('{"a": 1}\nnot json\n{"a": 2}\n\n', encoding='utf-8')

    rows = _LINT._load_jsonl(path)
    assert rows == [{'a': 1}, {'a': 2}]


# ---------------------------------------------------------------------------
# director_lint.py — lint_log()
# ---------------------------------------------------------------------------

def test_lint_log_clean_session_has_no_issues(tmp_path: Path) -> None:
    rows = [
        {'action': 'mode_transition', 't': 0.0, 'to_mode': 'BUILD', 'reason': 'sustained_rise'},
        {'action': 'mode_transition', 't': 10.0, 'to_mode': 'DROP', 'reason': 'drop_scheduled', 'drop_score': 0.85},
        {'action': 'mode_transition', 't': 20.0, 'to_mode': 'IMPACT', 'reason': 'impact_trigger', 'impact_score': 0.90},
        {'action': 'mode_transition', 't': 25.0, 'to_mode': 'CLIMAX', 'reason': 'impact_to_climax'},
    ]
    path = tmp_path / 'clean.jsonl'
    _write_jsonl(path, rows)

    report = _LINT.lint_log(path)
    assert report['transitions'] == 4
    assert report['issue_total'] == 0


def test_lint_log_flags_timeout_transitions(tmp_path: Path) -> None:
    rows = [{'action': 'mode_transition', 't': 0.0, 'to_mode': 'CRUISE', 'reason': 'build_timeout'}]
    path = tmp_path / 'log.jsonl'
    _write_jsonl(path, rows)

    report = _LINT.lint_log(path)
    assert report['issues']['timeout_transitions'] == 1


def test_lint_log_flags_weak_drop_schedule_below_threshold(tmp_path: Path) -> None:
    rows = [{'action': 'mode_transition', 't': 0.0, 'to_mode': 'DROP', 'reason': 'drop_scheduled', 'drop_score': 0.20}]
    path = tmp_path / 'log.jsonl'
    _write_jsonl(path, rows)

    report = _LINT.lint_log(path)
    assert report['issues']['weak_drop_schedule'] == 1


def test_lint_log_does_not_flag_strong_drop_schedule(tmp_path: Path) -> None:
    rows = [{'action': 'mode_transition', 't': 0.0, 'to_mode': 'DROP', 'reason': 'drop_scheduled', 'drop_score': 0.80}]
    path = tmp_path / 'log.jsonl'
    _write_jsonl(path, rows)

    report = _LINT.lint_log(path)
    assert 'weak_drop_schedule' not in report['issues']


def test_lint_log_flags_weak_impact_trigger(tmp_path: Path) -> None:
    rows = [{'action': 'mode_transition', 't': 0.0, 'to_mode': 'IMPACT', 'reason': 'impact_trigger', 'impact_score': 0.10}]
    path = tmp_path / 'log.jsonl'
    _write_jsonl(path, rows)

    report = _LINT.lint_log(path)
    assert report['issues']['weak_impact_trigger'] == 1


def test_lint_log_flags_drop_without_recent_build(tmp_path: Path) -> None:
    rows = [{'action': 'mode_transition', 't': 0.0, 'to_mode': 'DROP', 'reason': 'drop_scheduled', 'drop_score': 0.9}]
    path = tmp_path / 'log.jsonl'
    _write_jsonl(path, rows)

    report = _LINT.lint_log(path)
    assert report['issues']['drop_without_recent_build'] == 1


def test_lint_log_does_not_flag_drop_with_recent_build(tmp_path: Path) -> None:
    rows = [
        {'action': 'mode_transition', 't': 0.0, 'to_mode': 'BUILD', 'reason': 'sustained_rise'},
        {'action': 'mode_transition', 't': 10.0, 'to_mode': 'DROP', 'reason': 'drop_scheduled', 'drop_score': 0.9},
    ]
    path = tmp_path / 'log.jsonl'
    _write_jsonl(path, rows)

    report = _LINT.lint_log(path)
    assert 'drop_without_recent_build' not in report['issues']


def test_lint_log_build_older_than_20s_does_not_count_as_recent(tmp_path: Path) -> None:
    rows = [
        {'action': 'mode_transition', 't': 0.0, 'to_mode': 'BUILD', 'reason': 'sustained_rise'},
        {'action': 'mode_transition', 't': 25.0, 'to_mode': 'DROP', 'reason': 'drop_scheduled', 'drop_score': 0.9},
    ]
    path = tmp_path / 'log.jsonl'
    _write_jsonl(path, rows)

    report = _LINT.lint_log(path)
    assert report['issues']['drop_without_recent_build'] == 1


def test_lint_log_flags_climax_without_recent_impact(tmp_path: Path) -> None:
    rows = [{'action': 'mode_transition', 't': 0.0, 'to_mode': 'CLIMAX', 'reason': 'impact_to_climax'}]
    path = tmp_path / 'log.jsonl'
    _write_jsonl(path, rows)

    report = _LINT.lint_log(path)
    assert report['issues']['climax_without_recent_impact'] == 1


def test_lint_log_flags_transition_bursts(tmp_path: Path) -> None:
    """3+ transitions within a 2s window counts as one burst."""
    rows = [
        {'action': 'mode_transition', 't': 0.0, 'to_mode': 'BUILD', 'reason': 'sustained_rise'},
        {'action': 'mode_transition', 't': 0.5, 'to_mode': 'BREAKDOWN', 'reason': 'sustained_fall'},
        {'action': 'mode_transition', 't': 1.0, 'to_mode': 'BUILD', 'reason': 'sustained_rise'},
    ]
    path = tmp_path / 'log.jsonl'
    _write_jsonl(path, rows)

    report = _LINT.lint_log(path)
    assert report['issues']['transition_bursts'] == 1


def test_lint_log_ignores_non_mode_transition_rows(tmp_path: Path) -> None:
    rows = [
        {'action': 'detector_tick', 't': 0.0, 'bpm': 128.0},
        {'action': 'profile_recommendation', 't': 1.0},
    ]
    path = tmp_path / 'log.jsonl'
    _write_jsonl(path, rows)

    report = _LINT.lint_log(path)
    assert report['transitions'] == 0
    assert report['issue_total'] == 0


def test_lint_log_file_name_included_in_report(tmp_path: Path) -> None:
    path = tmp_path / 'my_session.jsonl'
    _write_jsonl(path, [])
    report = _LINT.lint_log(path)
    assert report['file'] == 'my_session.jsonl'


# ---------------------------------------------------------------------------
# director_calibrate.py — _iter_rows() / _q()
# ---------------------------------------------------------------------------

def test_iter_rows_skips_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / 'log.jsonl'
    path.write_text('{"a": 1}\nbroken\n{"a": 2}\n', encoding='utf-8')
    assert _CAL._iter_rows(path) == [{'a': 1}, {'a': 2}]


def test_q_returns_zero_for_empty_list() -> None:
    assert _CAL._q([], 0.5) == 0.0


def test_q_returns_the_single_value_for_a_singleton_list() -> None:
    assert _CAL._q([42.0], 0.9) == 42.0


def test_q_p10_p50_p90_of_ten_values() -> None:
    vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert _CAL._q(vals, 0.10) == 1.0
    assert _CAL._q(vals, 0.50) == 5.0
    assert _CAL._q(vals, 0.90) == 9.0


def test_q_sorts_unsorted_input() -> None:
    assert _CAL._q([5.0, 1.0, 3.0], 0.5) == 3.0


# ---------------------------------------------------------------------------
# director_calibrate.py — main() end-to-end
# ---------------------------------------------------------------------------

def _make_calibration_log(path: Path, *, n_ticks: int) -> None:
    """One session: n_ticks detector_tick rows with known, distinct energy/
    slope/drop/confidence values, plus one mode_transition per tracked
    reason, each timed to land right after a specific known tick."""
    rows: list[dict] = []
    for i in range(n_ticks):
        rows.append({
            'action': 'detector_tick', 't': float(i),
            'energy_slope': float(i) * 0.01,
            'drop_score': float(i) * 0.01,
            'energy': float(i) * 0.02,
            'confidence': min(1.0, float(i) * 0.02),
        })
    # Transition at t=50.5 -> prior tick is t=50 (i=50, if n_ticks > 50).
    rows.append({'action': 'mode_transition', 't': 50.5, 'to_mode': 'BUILD', 'reason': 'sustained_rise'})
    _write_jsonl(path, rows)


def test_main_reports_sessions_used_and_ignores_short_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    logs_dir = tmp_path / 'logs'
    logs_dir.mkdir()
    _make_calibration_log(logs_dir / 'autovj-long.jsonl', n_ticks=150)
    _make_calibration_log(logs_dir / 'autovj-short.jsonl', n_ticks=5)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['director_calibrate.py'])

    _CAL.main()

    out = capsys.readouterr().out
    assert 'sessions_used=1' in out, 'the 5-tick session must be excluded by the default --min-ticks=100'


def test_main_computes_quantiles_for_a_tracked_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    logs_dir = tmp_path / 'logs'
    logs_dir.mkdir()
    _make_calibration_log(logs_dir / 'autovj-a.jsonl', n_ticks=150)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['director_calibrate.py'])

    _CAL.main()

    out = capsys.readouterr().out
    assert 'sustained_rise n=1' in out
    # Prior tick for t=50.5 is i=50: energy_slope = 0.50.
    assert 'slope' in out and '0.500' in out


def test_main_returns_error_when_no_logs_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / 'logs').mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['director_calibrate.py'])

    assert _CAL.main() == 1


def test_main_prints_suggested_starting_points(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    logs_dir = tmp_path / 'logs'
    logs_dir.mkdir()
    _make_calibration_log(logs_dir / 'autovj-a.jsonl', n_ticks=150)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['director_calibrate.py'])

    _CAL.main()

    out = capsys.readouterr().out
    assert 'Suggested starting points' in out
    assert 'build_energy_threshold' in out
