"""Delete-key effect deletions: per-deletion log, session summary, stamped
log file — regression tests.

Every effect the Delete key disables should: (1) emit an INFO log line
immediately, (2) be tracked in-memory for an end-of-session summary logged
to console/main log at shutdown, and (3) be mirrored live to a stamped
logs/deleted-effects_<stamp>.log file when logging is enabled
([logging] level != "NONE").
"""
from __future__ import annotations

import logging
from pathlib import Path

from unicornviz.app import App
from unicornviz.config import Config


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


def _stub_app() -> App:
    app = object.__new__(App)
    app._deleted_effects_session = []
    app._deleted_effects_log_path = None
    return app


# --------------------------------------------------------------------------- #
# _compute_deleted_effects_log_path
# --------------------------------------------------------------------------- #

def test_log_path_is_none_when_logging_level_is_none() -> None:
    assert App._compute_deleted_effects_log_path(_StubCfg(level='NONE')) is None


def test_log_path_is_none_when_logging_level_is_none_case_insensitive() -> None:
    assert App._compute_deleted_effects_log_path(_StubCfg(level='none')) is None


def test_log_path_is_set_for_normal_logging_levels(tmp_path: Path) -> None:
    path = App._compute_deleted_effects_log_path(_StubCfg(level='INFO', logs_dir=tmp_path))
    assert path is not None
    assert path.parent == tmp_path
    assert path.name.startswith('deleted-effects_')
    assert path.name.endswith('.log')


def test_log_path_defaults_to_logs_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    path = App._compute_deleted_effects_log_path(_StubCfg(level='INFO'))
    assert path is not None
    assert path.parent.name == 'logs'


# --------------------------------------------------------------------------- #
# _record_deleted_effect: immediate log + session tracking + live file write
# --------------------------------------------------------------------------- #

def test_record_deleted_effect_emits_an_info_log(caplog) -> None:
    app = _stub_app()
    with caplog.at_level(logging.INFO, logger='unicornviz.app'):
        app._record_deleted_effect('Fire')
    assert any('Fire' in r.message and 'deleted' in r.message.lower() for r in caplog.records)


def test_record_deleted_effect_tracks_session_list() -> None:
    app = _stub_app()
    app._record_deleted_effect('Fire')
    app._record_deleted_effect('Plasma')
    names = [name for _stamp, name in app._deleted_effects_session]
    assert names == ['Fire', 'Plasma']


def test_record_deleted_effect_writes_a_live_line_when_logging_enabled(tmp_path: Path) -> None:
    app = _stub_app()
    app._deleted_effects_log_path = tmp_path / 'deleted-effects_20260101_000000.log'
    app._record_deleted_effect('Fire')
    content = app._deleted_effects_log_path.read_text(encoding='utf-8')
    assert 'Fire' in content


def test_record_deleted_effect_writes_nothing_when_logging_disabled(tmp_path: Path) -> None:
    app = _stub_app()
    app._deleted_effects_log_path = None  # logging disabled ([logging] level = NONE)
    app._record_deleted_effect('Fire')
    assert list(tmp_path.iterdir()) == []  # no stray file created anywhere


# --------------------------------------------------------------------------- #
# _log_deleted_effects_summary: shutdown summary to console/main log + file
# --------------------------------------------------------------------------- #

def test_summary_lists_every_deleted_effect(caplog) -> None:
    app = _stub_app()
    app._record_deleted_effect('Fire')
    app._record_deleted_effect('Plasma')
    with caplog.at_level(logging.INFO, logger='unicornviz.app'):
        app._log_deleted_effects_summary()
    summary = next(r.message for r in caplog.records if 'Session summary' in r.message)
    assert 'Fire' in summary
    assert 'Plasma' in summary
    assert '2' in summary  # count of deleted effects


def test_summary_is_a_noop_when_nothing_was_deleted(caplog) -> None:
    app = _stub_app()
    with caplog.at_level(logging.INFO, logger='unicornviz.app'):
        app._log_deleted_effects_summary()
    assert not any('Session summary' in r.message for r in caplog.records)


def test_summary_is_appended_to_the_stamped_log_file(tmp_path: Path) -> None:
    app = _stub_app()
    app._deleted_effects_log_path = tmp_path / 'deleted-effects_20260101_000000.log'
    app._record_deleted_effect('Fire')
    app._log_deleted_effects_summary()
    content = app._deleted_effects_log_path.read_text(encoding='utf-8')
    assert 'Fire' in content
    assert 'session summary' in content.lower()


# --------------------------------------------------------------------------- #
# Config integration: real Config object resolves the logging level correctly
# --------------------------------------------------------------------------- #

def test_log_path_none_via_real_config(tmp_path: Path) -> None:
    config_path = tmp_path / 'config.toml'
    config_path.write_text('[logging]\nlevel = "NONE"\n', encoding='utf-8')
    cfg = Config(str(config_path))
    assert App._compute_deleted_effects_log_path(cfg) is None


def test_log_path_set_via_real_config_default_level(tmp_path: Path) -> None:
    config_path = tmp_path / 'config.toml'
    config_path.write_text('', encoding='utf-8')
    cfg = Config(str(config_path))
    path = App._compute_deleted_effects_log_path(cfg)
    assert path is not None
    assert path.name.startswith('deleted-effects_')
