"""GIL-status line, both processes (plan W1 / free-threaded-python doc §6).

``remote_objects.gil_status()`` says which interpreter build this is and,
on a free-threaded one, whether an extension turned the GIL back on, and
``watch_gil_warnings()`` records *which* one (CPython only announces that as
a RuntimeWarning at import time).  The main process logs the result after
its startup imports -- INFO for the known set (moderngl, glcontext,
python-rtmidi), WARNING for any other module; the audio helper, which
imports none of them, logs WARNING if its GIL is on.  Without the line a
silent fallback to the GIL is invisible.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sysconfig
import warnings
from pathlib import Path

import pytest

from unicornviz import __main__ as entry
from unicornviz import remote_objects as ro

# A free-threaded interpreter that can import the app's requirements: set
# UV_FT_PYTHON, or install the one the Performance tab picks up.  The real-
# interpreter test is skipped without one (CI boxes, plain-GIL dev venvs).
_FT = os.environ.get('UV_FT_PYTHON') or os.path.join(
    os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share'),
    'unicorn-viz', 'venv-ft', 'bin', 'python')
_ROOT = str(Path(__file__).resolve().parents[1])


def test_gil_build_is_named_as_such() -> None:
    if sysconfig.get_config_var('Py_GIL_DISABLED'):
        pytest.skip('test interpreter is itself free-threaded')
    assert ro.gil_status().endswith('GIL build')
    assert ro.gil_enabled() is None


def test_free_threaded_states(monkeypatch) -> None:
    monkeypatch.setattr(ro.sysconfig, 'get_config_var', lambda name: 1)
    monkeypatch.setattr(ro.sys, '_is_gil_enabled', lambda: False, raising=False)
    assert ro.gil_status().endswith('free-threaded, GIL disabled')
    monkeypatch.setattr(ro.sys, '_is_gil_enabled', lambda: True, raising=False)
    line = ro.gil_status(['moderngl.mgl', 'rtmidi._rtmidi'])
    assert 'GIL ENABLED' in line and 'moderngl.mgl, rtmidi._rtmidi' in line
    assert 'without free-threading support' in ro.gil_status()


def test_missing_gil_probe_reads_as_gil_on(monkeypatch) -> None:
    """``sys._is_gil_enabled`` does not exist before 3.13."""
    monkeypatch.setattr(ro.sysconfig, 'get_config_var', lambda name: 1)
    monkeypatch.delattr(ro.sys, '_is_gil_enabled', raising=False)
    assert ro.gil_enabled() is True


def test_gil_warning_names_the_module() -> None:
    sink: list[str] = []
    with warnings.catch_warnings():             # restores filters and showwarning
        warnings.showwarning = lambda *a, **k: None   # keep pytest's report quiet
        ro.watch_gil_warnings(sink)
        warnings.showwarning(
            RuntimeWarning("The global interpreter lock (GIL) has been enabled to load "
                           "module 'fake_ext', which has not declared that it can run "
                           "safely without the GIL."),
            RuntimeWarning, 'fake.py', 1)
        warnings.showwarning(UserWarning('unrelated'), UserWarning, 'fake.py', 2)
    assert sink == ['fake_ext']


def test_main_process_logs_the_known_set_at_info(monkeypatch, caplog) -> None:
    monkeypatch.setattr(entry, '_GIL_FORCED_BY', ['moderngl.mgl', 'rtmidi._rtmidi'])
    with caplog.at_level(logging.INFO, logger='unicornviz.startup'):
        entry._log_interpreter_status()
    rec = [r for r in caplog.records if r.name == 'unicornviz.startup']
    assert [r.levelno for r in rec] == [logging.INFO]
    assert rec[0].getMessage().startswith('Interpreter: ')


def test_main_process_warns_for_a_module_outside_the_known_set(monkeypatch, caplog) -> None:
    monkeypatch.setattr(entry, '_GIL_FORCED_BY', ['moderngl.mgl', 'cv2.cv2'])
    with caplog.at_level(logging.INFO, logger='unicornviz.startup'):
        entry._log_interpreter_status()
    rec = [r for r in caplog.records if r.name == 'unicornviz.startup']
    assert [r.levelno for r in rec] == [logging.WARNING]
    assert 'cv2.cv2' in rec[0].getMessage() and 'known set' in rec[0].getMessage()


@pytest.mark.skipif(not os.path.exists(_FT), reason='no free-threaded interpreter (set UV_FT_PYTHON)')
@pytest.mark.parametrize(('xopt', 'expect'), [('gil=0', 'GIL disabled'), ('gil=1', 'GIL ENABLED')])
def test_real_free_threaded_interpreter(xopt: str, expect: str) -> None:
    out = subprocess.run(
        [_FT, '-X', xopt, '-c', 'from unicornviz.remote_objects import gil_status; print(gil_status())'],
        capture_output=True, text=True, timeout=60, check=True,
        env={**os.environ, 'PYTHONPATH': _ROOT},
    )
    assert expect in out.stdout
