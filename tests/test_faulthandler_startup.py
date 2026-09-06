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
    # resolve_path() anchors to APP_ROOT, not the cwd, so chdir alone left a
    # real logs/faulthandler_*.log behind on every run (2026-09-05 audit).
    monkeypatch.setattr(main_module, 'resolve_path', lambda rel: tmp_path / rel)
    _reset_faulthandler()
    try:
        main_module._install_faulthandler(_StubCfg(level='INFO'))
        assert faulthandler.is_enabled()
        path = Path(main_module._faulthandler_file.name)
        assert path.parent.name == 'logs' and path.parent.parent == tmp_path
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


# ---------------------------------------------------------------------------
# 2026-09-05: one zero-byte faulthandler file per launch, forever.
#
# Every run opened its own faulthandler_<stamp>.log and left it behind empty,
# so logs/ accumulated a file per start with nothing in it.  A clean exit now
# deletes the file it never wrote to; a file with a dump in it is kept.  And
# [logging] faulthandler = false never creates one at all.
# ---------------------------------------------------------------------------

class _SwitchCfg(_StubCfg):
    def __init__(self, *, enabled: bool, logs_dir: Path) -> None:
        super().__init__(level='INFO', logs_dir=logs_dir)
        self._enabled = enabled

    def get(self, *keys, default=None):
        if keys == ('logging', 'faulthandler'):
            return self._enabled
        return super().get(*keys, default=default)


def test_faulthandler_false_keeps_the_handler_but_writes_no_file(tmp_path: Path) -> None:
    _reset_faulthandler()
    try:
        main_module._install_faulthandler(_SwitchCfg(enabled=False, logs_dir=tmp_path))
        assert faulthandler.is_enabled()
        assert main_module._faulthandler_file is None
        assert list(tmp_path.iterdir()) == []
    finally:
        _reset_faulthandler()


def test_cleanup_deletes_an_empty_faulthandler_file(tmp_path: Path) -> None:
    _reset_faulthandler()
    try:
        main_module._install_faulthandler(_StubCfg(level='INFO', logs_dir=tmp_path))
        path = Path(main_module._faulthandler_file.name)
        assert path.is_file()
        main_module._cleanup_faulthandler()
        assert not path.exists()
        assert main_module._faulthandler_file is None
        assert faulthandler.is_enabled()      # still on, now pointed at stderr
    finally:
        _reset_faulthandler()


def test_cleanup_keeps_a_faulthandler_file_that_holds_a_dump(tmp_path: Path) -> None:
    _reset_faulthandler()
    try:
        main_module._install_faulthandler(_StubCfg(level='INFO', logs_dir=tmp_path))
        fh = main_module._faulthandler_file
        fh.write('Fatal Python error: Segmentation fault\n')
        fh.flush()
        path = Path(fh.name)
        main_module._cleanup_faulthandler()
        assert path.is_file()
        assert path.read_text().startswith('Fatal Python error')
    finally:
        _reset_faulthandler()


def test_cleanup_is_a_no_op_without_a_file() -> None:
    _reset_faulthandler()
    main_module._cleanup_faulthandler()          # must not raise
    assert main_module._faulthandler_file is None


def test_stall_watchdog_is_installed_on_the_app_from_config(tmp_path: Path) -> None:
    class _Cfg(_StubCfg):
        def get(self, *keys, default=None):
            if keys == ('logging', 'stall_dump_s'):
                return 2.5
            return super().get(*keys, default=default)

    class _App:
        stall_watchdog = None

    _reset_faulthandler()
    try:
        app = _App()
        wd = main_module._install_stall_watchdog(_Cfg(level='INFO', logs_dir=tmp_path), app)
        assert wd is not None and app.stall_watchdog is wd
        assert wd.timeout_s == 2.5
        main_module._cleanup_faulthandler(wd)
        assert wd.armed is False
    finally:
        _reset_faulthandler()


def test_stall_watchdog_disabled_by_zero(tmp_path: Path) -> None:
    class _Cfg(_StubCfg):
        def get(self, *keys, default=None):
            if keys == ('logging', 'stall_dump_s'):
                return 0
            return super().get(*keys, default=default)

    class _App:
        stall_watchdog = None

    app = _App()
    assert main_module._install_stall_watchdog(_Cfg(level='INFO', logs_dir=tmp_path), app) is None
    assert app.stall_watchdog is None
