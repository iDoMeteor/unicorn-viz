"""Regression tests for ``unicorn-viz --self-test``, the headless install check.

Installers and the nightly smoke rely on it to catch what ``--help`` cannot:
an ``APP_ROOT`` that does not contain the assets, or core dependencies that do
not import in the bundled runtime.
"""
from __future__ import annotations

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
