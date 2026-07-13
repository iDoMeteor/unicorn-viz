"""Regression tests for KeystrokeLogger (drop-ins/training-kit-01).

Uses real filesystem I/O against pytest's tmp_path fixture rather than
mocking open()/write() -- the class is a thin, self-contained JSONL
appender with no other dependencies, so exercising it for real is both
simpler and more faithful than mocking.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_KEYSTROKE_LOGGER_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'training-kit-01' / 'keystroke_logger.py'
_SPEC = importlib.util.spec_from_file_location('test_keystroke_logger_module', _KEYSTROKE_LOGGER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
KeystrokeLogger = _MOD.KeystrokeLogger


def _read_lines(logs_dir: Path) -> list[dict]:
    files = list(logs_dir.glob('keystrokes-*.log'))
    assert len(files) == 1, f'expected exactly one log file, found {files}'
    lines = files[0].read_text(encoding='utf-8').strip().splitlines()
    return [json.loads(ln) for ln in lines if ln]


# ---------------------------------------------------------------------------
# Disabled state
# ---------------------------------------------------------------------------

def test_disabled_creates_no_file(tmp_path: Path) -> None:
    KeystrokeLogger(enabled=False, logs_dir=tmp_path)
    assert list(tmp_path.glob('keystrokes-*.log')) == []


def test_disabled_log_key_is_a_silent_noop(tmp_path: Path) -> None:
    kl = KeystrokeLogger(enabled=False, logs_dir=tmp_path)
    kl.log_key('N', 'Plasma')  # must not raise
    assert list(tmp_path.glob('keystrokes-*.log')) == []


def test_disabled_log_midi_is_a_silent_noop(tmp_path: Path) -> None:
    kl = KeystrokeLogger(enabled=False, logs_dir=tmp_path)
    kl.log_midi('CC1')  # must not raise


def test_disabled_close_is_safe(tmp_path: Path) -> None:
    kl = KeystrokeLogger(enabled=False, logs_dir=tmp_path)
    kl.close()  # must not raise


# ---------------------------------------------------------------------------
# Enabled state: file creation
# ---------------------------------------------------------------------------

def test_enabled_creates_exactly_one_log_file(tmp_path: Path) -> None:
    kl = KeystrokeLogger(enabled=True, logs_dir=tmp_path)
    assert len(list(tmp_path.glob('keystrokes-*.log'))) == 1
    kl.close()


def test_directory_creation_failure_disables_gracefully(tmp_path: Path) -> None:
    """If logs_dir can't be created (e.g. a file already occupies that
    path), the logger must disable itself rather than raise."""
    blocked_path = tmp_path / 'blocked'
    blocked_path.write_text('not a directory')  # occupies the path with a file

    kl = KeystrokeLogger(enabled=True, logs_dir=blocked_path)

    assert kl._enabled is False
    kl.log_key('N', 'Plasma')  # must still be a safe no-op


# ---------------------------------------------------------------------------
# log_key()
# ---------------------------------------------------------------------------

def test_log_key_writes_minimal_required_fields(tmp_path: Path) -> None:
    kl = KeystrokeLogger(enabled=True, logs_dir=tmp_path)
    kl.log_key('N', 'Plasma')
    kl.close()

    entries = _read_lines(tmp_path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry['key'] == 'N'
    assert entry['effect'] == 'Plasma'
    assert 't' in entry
    assert 'bpm' not in entry
    assert 'beat_phase' not in entry
    assert 'energy' not in entry
    assert 'vj_mode' not in entry
    assert 'mods' not in entry


def test_log_key_includes_optional_fields_when_meaningfully_nonzero(tmp_path: Path) -> None:
    kl = KeystrokeLogger(enabled=True, logs_dir=tmp_path)
    kl.log_key(
        'N', 'Plasma',
        modifiers=['ctrl', 'shift'],
        bpm=128.456,
        beat_phase=0.4219,
        energy=0.6123,
        vj_mode='CRUISE',
    )
    kl.close()

    entry = _read_lines(tmp_path)[0]
    assert entry['mods'] == ['ctrl', 'shift']
    assert entry['bpm'] == 128.5   # rounded to 1 decimal
    assert entry['beat_phase'] == 0.422  # rounded to 3 decimals
    assert entry['energy'] == 0.612      # rounded to 3 decimals
    assert entry['vj_mode'] == 'CRUISE'


def test_log_key_omits_zero_valued_optional_fields(tmp_path: Path) -> None:
    """bpm/beat_phase/energy use a strict > 0.0 gate -- exactly 0.0 must be
    omitted, not written as a literal 0."""
    kl = KeystrokeLogger(enabled=True, logs_dir=tmp_path)
    kl.log_key('N', 'Plasma', bpm=0.0, beat_phase=0.0, energy=0.0, vj_mode='')
    kl.close()

    entry = _read_lines(tmp_path)[0]
    assert 'bpm' not in entry
    assert 'beat_phase' not in entry
    assert 'energy' not in entry
    assert 'vj_mode' not in entry


def test_log_key_omits_empty_modifiers_list(tmp_path: Path) -> None:
    kl = KeystrokeLogger(enabled=True, logs_dir=tmp_path)
    kl.log_key('N', 'Plasma', modifiers=[])
    kl.close()

    entry = _read_lines(tmp_path)[0]
    assert 'mods' not in entry


def test_multiple_log_key_calls_append_multiple_lines(tmp_path: Path) -> None:
    kl = KeystrokeLogger(enabled=True, logs_dir=tmp_path)
    kl.log_key('N', 'Plasma')
    kl.log_key('P', 'Fire')
    kl.log_key('X', 'Vortex')
    kl.close()

    entries = _read_lines(tmp_path)
    assert [e['key'] for e in entries] == ['N', 'P', 'X']


def test_log_key_after_close_is_a_silent_noop(tmp_path: Path) -> None:
    kl = KeystrokeLogger(enabled=True, logs_dir=tmp_path)
    kl.close()
    kl.log_key('N', 'Plasma')  # must not raise, must not reopen the file

    entries = _read_lines(tmp_path)
    assert entries == []


def test_write_exception_is_swallowed_silently(tmp_path: Path) -> None:
    kl = KeystrokeLogger(enabled=True, logs_dir=tmp_path)
    kl._file = MagicMock()
    kl._file.write.side_effect = OSError('disk full')

    kl.log_key('N', 'Plasma')  # must not raise despite the write failure


# ---------------------------------------------------------------------------
# log_midi()
# ---------------------------------------------------------------------------

def test_log_midi_writes_minimal_required_fields(tmp_path: Path) -> None:
    kl = KeystrokeLogger(enabled=True, logs_dir=tmp_path)
    kl.log_midi('CC1')
    kl.close()

    entry = _read_lines(tmp_path)[0]
    assert entry['ctrl'] == 'CC1'
    assert 't' in entry
    assert 'action' not in entry
    assert 'param' not in entry
    assert 'val' not in entry


def test_log_midi_includes_optional_fields_when_present(tmp_path: Path) -> None:
    kl = KeystrokeLogger(enabled=True, logs_dir=tmp_path)
    kl.log_midi(
        'CC1',
        action='set_reactivity',
        param='reactivity',
        value=0.789,
        effect_name='Plasma',
        bpm=140.0,
        beat_phase=0.5,
        energy=0.3,
        vj_mode='DROP',
    )
    kl.close()

    entry = _read_lines(tmp_path)[0]
    assert entry['action'] == 'set_reactivity'
    assert entry['param'] == 'reactivity'
    assert entry['val'] == 0.789
    assert entry['effect'] == 'Plasma'
    assert entry['bpm'] == 140.0
    assert entry['vj_mode'] == 'DROP'


def test_log_midi_includes_negative_value_unlike_the_other_zero_gated_fields(tmp_path: Path) -> None:
    """value uses `!= 0.0`, not `> 0.0` like bpm/beat_phase/energy -- a
    negative controller value (e.g. a pan/pitch knob) must still be logged,
    not silently dropped by a same-shaped-but-different gate."""
    kl = KeystrokeLogger(enabled=True, logs_dir=tmp_path)
    kl.log_midi('CC2', value=-0.5)
    kl.close()

    entry = _read_lines(tmp_path)[0]
    assert entry['val'] == -0.5


def test_log_midi_omits_zero_value(tmp_path: Path) -> None:
    kl = KeystrokeLogger(enabled=True, logs_dir=tmp_path)
    kl.log_midi('CC3', value=0.0)
    kl.close()

    entry = _read_lines(tmp_path)[0]
    assert 'val' not in entry


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------

def test_close_is_idempotent(tmp_path: Path) -> None:
    kl = KeystrokeLogger(enabled=True, logs_dir=tmp_path)
    kl.close()
    kl.close()  # must not raise on a second close


def test_close_flushes_content_to_disk(tmp_path: Path) -> None:
    kl = KeystrokeLogger(enabled=True, logs_dir=tmp_path)
    kl.log_key('N', 'Plasma')
    kl.close()

    files = list(tmp_path.glob('keystrokes-*.log'))
    assert files[0].stat().st_size > 0
