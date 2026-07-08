"""faulthandler startup wiring — regression tests.

A native crash (segfault in Mesa/EGL/ALSA, etc.) kills the process before
Python's ``logging`` module can run, so the app previously left zero trace
of such crashes beyond the log file stopping mid-line. ``_install_faulthandler``
enables the stdlib ``faulthandler`` so a crash still dumps a Python-level
traceback of the frame that was executing, mirroring the ``[logging] level``
convention used elsewhere: a real file under the logs directory when logging
is enabled, stderr otherwise.
"""
from __future__ import annotations

import faulthandler
from pathlib import Path

from unicornviz import __main__ as main_module


class _StubCfg:
    def __init__(self, level: str = 'INFO', logs_dir: Path | None = None) -> None:
        self._level = level
        self._logs_dir = logs_dir

    def get(self, *keys, default=None):
        if keys == ('logging', 'level'):
            return self._level
        if keys == ('logging', 'directory'):
            return str(self._logs_dir) if self._logs_dir is not None else default
        return default


def _reset_faulthandler():
    faulthandler.disable()
    main_module._faulthandler_file = None  # noqa: SLF001


def test_enables_with_a_file_under_the_logs_directory_when_logging_is_on(tmp_path: Path) -> None:
    _reset_faulthandler()
    try:
        main_module._install_faulthandler(_StubCfg(level='INFO', logs_dir=tmp_path))
        assert faulthandler.is_enabled()
        assert main_module._faulthandler_file is not None
        path = Path(main_module._faulthandler_file.name)
        assert path.parent == tmp_path
        assert path.name.startswith('faulthandler_')
        assert path.name.endswith('.log')
    finally:
        _reset_faulthandler()


def test_defaults_to_the_logs_directory_when_none_configured(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _reset_faulthandler()
    try:
        main_module._install_faulthandler(_StubCfg(level='INFO'))
        assert faulthandler.is_enabled()
        path = Path(main_module._faulthandler_file.name)
        assert path.parent.name == 'logs'
    finally:
        _reset_faulthandler()


def test_enables_without_a_file_when_logging_is_none(tmp_path: Path) -> None:
    _reset_faulthandler()
    try:
        main_module._install_faulthandler(_StubCfg(level='NONE', logs_dir=tmp_path))
        assert faulthandler.is_enabled()
        assert main_module._faulthandler_file is None
        assert list(tmp_path.iterdir()) == []  # no stray file created
    finally:
        _reset_faulthandler()


def test_enables_without_a_file_when_logging_is_none_case_insensitive(tmp_path: Path) -> None:
    _reset_faulthandler()
    try:
        main_module._install_faulthandler(_StubCfg(level='none', logs_dir=tmp_path))
        assert faulthandler.is_enabled()
        assert main_module._faulthandler_file is None
    finally:
        _reset_faulthandler()
