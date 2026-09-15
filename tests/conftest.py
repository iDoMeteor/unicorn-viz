"""Core test-suite fixtures.

The owner-state guard (2026-09-05 audit).  This suite runs on every commit
hook, and tests had been writing into the repository's real ``logs/`` and
``runtime/`` directories: decision-log corpora that the training packager
then swept into live-session buckets, faulthandler files, and -- in the
media drop-in -- a tag cache that replaced the owner's 10,843-track cache
with four temp paths, costing 7-14 s at nearly every launch.

Two fixtures:

* ``_redirect_autovj_logs`` points the Auto VJ decision log at a temp dir
  via ``UNICORNVIZ_AUTOVJ_LOG_DIR`` (honored by auto_vj.py), so replay and
  director tests never write ``logs/autovj-*.jsonl`` here.
* ``_owner_state_guard`` snapshots ``logs/`` and ``runtime/`` when the
  session starts and fails the session if any test left a new file in
  either.  The failure names the files; the fix is always the same --
  point the code under test at ``tmp_path``.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_GUARDED = ('logs', 'runtime')


def _snapshot() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for name in _GUARDED:
        d = _REPO / name
        out[name] = {p.name for p in d.iterdir()} if d.is_dir() else set()
    return out


@pytest.fixture(autouse=True)
def _runtime_state_in_tmp(monkeypatch, tmp_path_factory):
    """Keep every App's runtime store out of the working tree.

    ``App()`` builds a ``RuntimeStateStore`` at the configured path, which
    defaults to the relative ``runtime/global_state.json`` -- i.e. the
    owner's live state file under APP_ROOT.  Eight test modules construct
    a real App with a default Config; each one used to create that file
    (masked in the long-lived main checkout, where it already existed, and
    caught by the guard below the first time a fresh seat worktree ran the
    suite, 2026-09-14).  Relative store paths are rooted under a per-test
    tmp dir here; absolute paths a test chose itself are left alone.
    """
    import unicornviz.app as app_mod
    from unicornviz.runtime_state import RuntimeStateStore

    base = tmp_path_factory.mktemp('runtime-state')

    class _TmpRuntimeStateStore(RuntimeStateStore):
        def __init__(self, path='runtime/global_state.json') -> None:
            p = Path(path)
            super().__init__(p if p.is_absolute() else base / p)

    monkeypatch.setattr(app_mod, 'RuntimeStateStore', _TmpRuntimeStateStore)
    yield


@pytest.fixture(autouse=True)
def _redirect_autovj_logs(monkeypatch, tmp_path_factory):
    monkeypatch.setenv('UNICORNVIZ_AUTOVJ_LOG_DIR',
                       str(tmp_path_factory.mktemp('autovj-logs')))
    yield


@pytest.fixture(scope='session', autouse=True)
def _owner_state_guard():
    before = _snapshot()
    yield
    after = _snapshot()
    leaked = []
    for name in _GUARDED:
        for fn in sorted(after[name] - before[name]):
            leaked.append(f'{name}/{fn}')
    if leaked and not os.environ.get('UNICORNVIZ_ALLOW_STATE_WRITES'):
        pytest.fail(
            'Tests wrote into the repository\'s owner-state directories:\n  '
            + '\n  '.join(leaked)
            + '\nPoint the code under test at tmp_path (see tests/conftest.py). '
            'Set UNICORNVIZ_ALLOW_STATE_WRITES=1 to bypass deliberately.',
            pytrace=False,
        )
