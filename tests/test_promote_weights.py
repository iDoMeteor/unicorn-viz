"""Tests for tools/promote_weights.py (auto-vj-01 weight promotion)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'training-kit-01' / 'tools' / 'promote_weights.py'
_SPEC = importlib.util.spec_from_file_location('promote_weights', _MOD_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

_load_and_validate = _MOD._load_and_validate
_archive_active = _MOD._archive_active
main = _MOD.main


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding='utf-8')


def test_load_and_validate_accepts_wrapped_weights(tmp_path: Path) -> None:
    fitted = tmp_path / 'fitted.json'
    _write_json(fitted, {'weights': {'tempo_fit': 2.1, 'lock_rate': 2.6}})
    assert _load_and_validate(fitted) == {'tempo_fit': 2.1, 'lock_rate': 2.6}


def test_load_and_validate_accepts_bare_mapping(tmp_path: Path) -> None:
    fitted = tmp_path / 'fitted.json'
    _write_json(fitted, {'tempo_fit': 2.1})
    assert _load_and_validate(fitted) == {'tempo_fit': 2.1}


def test_load_and_validate_rejects_non_numeric_value(tmp_path: Path) -> None:
    fitted = tmp_path / 'fitted.json'
    _write_json(fitted, {'weights': {'tempo_fit': 'not-a-number'}})
    with pytest.raises(ValueError, match='not numeric'):
        _load_and_validate(fitted)


def test_load_and_validate_rejects_non_dict_payload(tmp_path: Path) -> None:
    fitted = tmp_path / 'fitted.json'
    _write_json(fitted, [1, 2, 3])
    with pytest.raises(ValueError, match='expected a JSON object'):
        _load_and_validate(fitted)


def test_load_and_validate_rejects_empty_mapping(tmp_path: Path) -> None:
    fitted = tmp_path / 'fitted.json'
    _write_json(fitted, {'weights': {}})
    with pytest.raises(ValueError, match='no non-empty weight mapping'):
        _load_and_validate(fitted)


def test_archive_active_moves_existing_file(tmp_path: Path) -> None:
    weights_dir = tmp_path / 'weights'
    weights_dir.mkdir()
    active = weights_dir / 'recommender-weights.json'
    active.write_text('{"weights": {}}', encoding='utf-8')
    archived = _archive_active(weights_dir)
    assert archived is not None
    assert archived.parent == weights_dir / 'archive'
    assert archived.exists()
    assert not active.exists()


def test_archive_active_returns_none_when_nothing_active(tmp_path: Path) -> None:
    weights_dir = tmp_path / 'weights'
    weights_dir.mkdir()
    assert _archive_active(weights_dir) is None


def test_main_promotes_and_archives_previous(tmp_path: Path, capsys) -> None:
    weights_dir = tmp_path / 'weights'
    weights_dir.mkdir()
    active = weights_dir / 'recommender-weights.json'
    active.write_text(json.dumps({'weights': {'tempo_fit': 1.0}}), encoding='utf-8')

    fitted = tmp_path / 'fitted.json'
    _write_json(fitted, {'weights': {'tempo_fit': 2.3, 'lock_rate': 2.7}})

    rc = main([str(fitted), '--weights-dir', str(weights_dir)])
    assert rc == 0

    payload = json.loads(active.read_text(encoding='utf-8'))
    assert payload['weights'] == {'tempo_fit': 2.3, 'lock_rate': 2.7}
    assert payload['source'] == str(fitted.resolve())
    assert 'promoted_at' in payload

    archive_dir = weights_dir / 'archive'
    assert len(list(archive_dir.glob('*.json'))) == 1


def test_main_dry_run_writes_nothing(tmp_path: Path) -> None:
    weights_dir = tmp_path / 'weights'
    fitted = tmp_path / 'fitted.json'
    _write_json(fitted, {'weights': {'tempo_fit': 2.3}})

    rc = main([str(fitted), '--weights-dir', str(weights_dir), '--dry-run'])
    assert rc == 0
    assert not weights_dir.exists()


def test_main_reports_error_on_missing_file(tmp_path: Path) -> None:
    rc = main([str(tmp_path / 'nope.json'), '--weights-dir', str(tmp_path / 'weights')])
    assert rc == 1


def test_main_reports_error_on_invalid_shape(tmp_path: Path) -> None:
    fitted = tmp_path / 'fitted.json'
    _write_json(fitted, {'weights': {'tempo_fit': 'nope'}})
    rc = main([str(fitted), '--weights-dir', str(tmp_path / 'weights')])
    assert rc == 1
