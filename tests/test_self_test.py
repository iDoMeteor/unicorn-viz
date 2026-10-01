"""Regression tests for ``unicorn-viz --self-test``, the headless install check.

Installers and the nightly smoke rely on it to catch what ``--help`` cannot:
an ``APP_ROOT`` that does not contain the assets, or core dependencies that do
not import in the bundled runtime.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from unicornviz import __main__ as cli
from unicornviz import paths


def test_self_test_passes_in_dev_tree(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli._self_test() == 0
    out = capsys.readouterr().out
    assert 'APP_ROOT' in out
    assert 'self-test: OK' in out


def test_self_test_fails_when_assets_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(paths, 'APP_ROOT', tmp_path)
    assert cli._self_test() == 1
    out = capsys.readouterr().out
    assert 'MISSING' in out
    assert 'self-test: FAILED' in out


def test_cli_flag_short_circuits_before_config(tmp_path: Path) -> None:
    # A neutral cwd with no config.toml: the flag must exit before Config is
    # loaded, which is exactly how an installed copy gets exercised.
    proc = subprocess.run(
        [sys.executable, '-m', 'unicornviz', '--self-test'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'self-test: OK' in proc.stdout


# --- cv2 is optional (plan W1, 2026-09-30) --------------------------------
# opencv-python-headless ships no wheel for free-threaded 3.14 (and Windows
# will lag), so a clean free-threaded install has no cv2.  Only the webcam and
# video-clips drop-ins use it, and both guard the import.  The install check
# reports it as a warning, never a failure.

def test_missing_cv2_is_a_warning_not_a_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, 'cv2', None)       # `import cv2` -> ImportError
    assert cli._self_test() == 0
    out = capsys.readouterr().out
    assert 'self-test: OK' in out
    cv2_line = next(line for line in out.splitlines() if 'cv2' in line)
    assert '[!!]' in cv2_line and 'optional' in cv2_line
    assert 'FAIL' not in out


def test_a_missing_required_module_still_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, 'cv2', None)
    monkeypatch.setitem(sys.modules, 'psutil', None)
    assert cli._self_test() == 1
    out = capsys.readouterr().out
    assert '[FAIL] import psutil' in out
    assert 'self-test: FAILED (1 problem(s))' in out    # cv2 is not counted


def test_core_never_imports_cv2_at_module_level() -> None:
    """Core must start without cv2: no unguarded top-level import in unicornviz/."""
    root = Path(cli.__file__).resolve().parent
    offenders: list[str] = []
    for path in root.rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in tree.body:                          # module level, not inside try/def
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n == 'cv2' or n.startswith('cv2.') for n in names):
                offenders.append(str(path.relative_to(root)))
    assert not offenders, f'unguarded cv2 import in core: {offenders}'
