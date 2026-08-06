"""Regression tests for _ActionEngine's runtime-toggleable decision log
(2026-08-06, wired to Ctrl+T/Alt+T -- see test_auto_vj_training_controls.py
for the controller-level wiring). Previously log_decisions was
config.toml-only, decided once at startup with no way to turn it on
mid-session.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_SPEC = importlib.util.spec_from_file_location('test_action_engine_log_decisions_module', _AUTO_VJ_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
_ActionEngine = _MOD._ActionEngine


def test_disabled_by_default_with_no_config_key(tmp_path) -> None:
    engine = _ActionEngine({}, tmp_path)
    assert engine.log_decisions_enabled is False


def test_config_log_decisions_true_opens_immediately(tmp_path) -> None:
    engine = _ActionEngine({'log_decisions': True}, tmp_path)
    assert engine.log_decisions_enabled is True
    assert len(list(tmp_path.glob('autovj-*.jsonl'))) == 1


def test_set_log_decisions_true_opens_a_file_and_mark_writes_to_it(tmp_path) -> None:
    engine = _ActionEngine({}, tmp_path)
    assert engine.set_log_decisions(True) is True

    engine.mark('test_action', foo='bar')

    files = list(tmp_path.glob('autovj-*.jsonl'))
    assert len(files) == 1
    rows = [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]
    assert rows[0]['action'] == 'test_action'
    assert rows[0]['foo'] == 'bar'


def test_set_log_decisions_false_closes_and_stops_further_writes(tmp_path) -> None:
    engine = _ActionEngine({'log_decisions': True}, tmp_path)
    engine.mark('before_disable')

    assert engine.set_log_decisions(False) is False
    engine.mark('after_disable')

    files = list(tmp_path.glob('autovj-*.jsonl'))
    assert len(files) == 1
    rows = [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]
    assert [r['action'] for r in rows] == ['before_disable']


def test_set_log_decisions_true_is_a_noop_when_already_enabled(tmp_path) -> None:
    """Re-enabling while already enabled must not silently drop the
    handle to an already-open file (e.g. via a stray re-open)."""
    engine = _ActionEngine({'log_decisions': True}, tmp_path)
    engine.mark('one')
    assert engine.set_log_decisions(True) is True
    engine.mark('two')

    files = list(tmp_path.glob('autovj-*.jsonl'))
    assert len(files) == 1  # still just the one file from construction
    rows = [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]
    assert [r['action'] for r in rows] == ['one', 'two']


def test_set_log_decisions_true_with_no_log_dir_stays_disabled() -> None:
    engine = _ActionEngine({}, log_dir=None)
    assert engine.set_log_decisions(True) is False
    assert engine.log_decisions_enabled is False
