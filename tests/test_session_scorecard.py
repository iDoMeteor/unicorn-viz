"""Regression tests for training-kit-01's session_scorecard.py Tier 1
signal-activity rollup (docs/planning/
auto-vj-recommender-accuracy-tracking-2026-08-06.md).

Covers:
- term_activity correctly computes the fraction of eval cycles where a
  term's spread cleared the activity threshold
- lock_rate/mean_conf/mean_dconf are excluded even when present in the log
  (they are computed once per cycle, not per candidate, so their spread is
  structurally always 0 -- not a "this weight does nothing" signal)
- Older logs with no term_spread key at all degrade gracefully (no crash,
  term_activity stays empty) rather than being treated as all-zero activity
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SCORECARD_PATH = _REPO / 'drop-ins' / 'training-kit-01' / 'tools' / 'session_scorecard.py'


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # SessionScore's @dataclass needs its module registered in sys.modules
    # before exec -- dataclasses resolves field type annotations via
    # sys.modules[cls.__module__], which is None for an unregistered
    # spec_from_file_location module and raises AttributeError.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_SCORECARD = _load_module(_SCORECARD_PATH, 'test_session_scorecard_module')


def _write_log(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / 'autovj-test.jsonl'
    path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
    return path


def _tick(t: float, profile: str = 'deep_house') -> dict:
    return {
        't': t, 'action': 'detector_tick', 'audio_profile_key': profile,
        'bpm_locked': True, 'confidence': 0.8, 'downbeat_confidence': 0.7, 'bpm': 122.0,
    }


def test_term_activity_computes_fraction_above_threshold(tmp_path) -> None:
    rows = [_tick(0.0), _tick(1.0), _tick(2.0)]
    # 2 of 3 cycles have tempo_fit spread clearing the 0.05 threshold.
    for spread in (0.20, 0.20, 0.01):
        rows.append({
            't': 0.0, 'action': 'profile_recommendation', 'recommended_profile_key': 'deep_house',
            'score_margin': 0.5, 'term_spread': {'tempo_fit': spread},
        })
    log = _write_log(tmp_path, rows)

    score = _SCORECARD._score(log, focus_profile='deep_house', min_profile_share=0.5)

    assert score is not None
    assert score.term_activity['tempo_fit'] == 2 / 3


def test_non_discriminating_terms_excluded_from_activity(tmp_path) -> None:
    rows = [_tick(0.0)]
    rows.append({
        't': 0.0, 'action': 'profile_recommendation', 'recommended_profile_key': 'deep_house',
        'score_margin': 0.5,
        # lock_rate/mean_conf/mean_dconf are structurally always 0 spread
        # (computed once per cycle, not per candidate) -- must not appear.
        'term_spread': {'lock_rate': 0.0, 'mean_conf': 0.0, 'mean_dconf': 0.0, 'centroid_fit': 0.30},
    })
    log = _write_log(tmp_path, rows)

    score = _SCORECARD._score(log, focus_profile='deep_house', min_profile_share=0.5)

    assert score is not None
    assert 'lock_rate' not in score.term_activity
    assert 'mean_conf' not in score.term_activity
    assert 'mean_dconf' not in score.term_activity
    assert score.term_activity['centroid_fit'] == 1.0


def test_missing_term_spread_degrades_gracefully(tmp_path) -> None:
    rows = [_tick(0.0)]
    rows.append({
        't': 0.0, 'action': 'profile_recommendation', 'recommended_profile_key': 'deep_house',
        'score_margin': 0.5,
        # No term_spread key at all -- pre-2026-08-06 log shape.
    })
    log = _write_log(tmp_path, rows)

    score = _SCORECARD._score(log, focus_profile='deep_house', min_profile_share=0.5)

    assert score is not None
    assert score.term_activity == {}
