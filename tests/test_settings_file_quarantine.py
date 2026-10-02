"""Unreadable settings files are quarantined, never overwritten (audit P1-6).

``global_state.json`` (every menu setting), ``config_profiles.json`` and
``presets.json`` each turned a load failure into an empty store and saved over
the file on the next change.  Now the unloadable file is renamed to
``<name>.corrupt-<ts>`` with its bytes intact, an ERROR is logged, and the
store starts from defaults.  If the file cannot even be moved aside, saves to
that path are blocked for the session.
"""
from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from unicornviz.config_profiles import ConfigProfileStore
from unicornviz.presets import ShowPresetStore
from unicornviz.runtime_state import RuntimeStateStore

GOOD_STATE = json.dumps({'_meta': {'schema': 'unicornviz.runtime_state', 'schema_version': 1,
                                   'store': 'global'}, 'perf': {'fps_cap': 60}, 'ui_scale': 1.8})
GOOD_PROFILES = json.dumps({'_meta': {}, 'profiles': {'Club': {'effects': {'Plasma': {'speed': 2.0}}}}})
GOOD_PRESETS = json.dumps({'_meta': {}, 'presets': {'Night': {'enabled': ['Plasma']}}})

STORES = [
    ('state', RuntimeStateStore, GOOD_STATE, lambda s: s.set('x.y', 1)),
    ('profiles', ConfigProfileStore, GOOD_PROFILES, lambda s: s.save('New', {'a': 1})),
    ('presets', ShowPresetStore, GOOD_PRESETS, lambda s: s.save('New', {'a': 1})),
]
IDS = [s[0] for s in STORES]


def _bad_variants(good: str) -> dict[str, bytes]:
    return {
        'garbage': b'{ this is not json \xff\xfe',
        'truncated': good.encode()[: len(good) // 2],
        'empty': b'',
        'not_an_object': b'[1, 2, 3]',
        'wrong_shape': b'{"hello": "world"}' if good is not GOOD_STATE else b'"just a string"',
    }


def _quarantined(path: Path) -> list[Path]:
    return sorted(path.parent.glob(path.name + '.corrupt-*'))


@pytest.mark.parametrize('name,cls,good,mutate', STORES, ids=IDS)
@pytest.mark.parametrize('variant', ['garbage', 'truncated', 'empty', 'not_an_object', 'wrong_shape'])
def test_a_bad_file_is_quarantined_with_its_bytes_and_never_overwritten(
        tmp_path, caplog, name, cls, good, mutate, variant) -> None:
    path = tmp_path / 'runtime' / 'file.json'
    path.parent.mkdir()
    raw = _bad_variants(good)[variant]
    path.write_bytes(raw)

    with caplog.at_level(logging.ERROR):
        store = cls(path)                           # must not raise

    moved = _quarantined(path)
    assert len(moved) == 1 and moved[0].read_bytes() == raw      # every byte kept
    assert any(r.levelno == logging.ERROR and '.corrupt-' in r.getMessage()
               for r in caplog.records)
    mutate(store)                                   # later saves go to the original path
    assert moved[0].read_bytes() == raw             # the quarantined copy is never touched
    assert path.exists() and json.loads(path.read_text(encoding='utf-8'))


@pytest.mark.parametrize('name,cls,good,mutate', STORES, ids=IDS)
def test_a_good_file_is_untouched_and_not_quarantined(tmp_path, name, cls, good, mutate) -> None:
    path = tmp_path / 'file.json'
    path.write_text(good, encoding='utf-8')
    cls(path)
    assert _quarantined(path) == []
    assert json.loads(path.read_text(encoding='utf-8')) == json.loads(good) or name == 'state'


def test_a_state_file_with_a_good_payload_keeps_every_setting(tmp_path) -> None:
    path = tmp_path / 'global_state.json'
    path.write_text(GOOD_STATE, encoding='utf-8')
    s = RuntimeStateStore(path)
    assert s.get('perf.fps_cap') == 60 and s.get('ui_scale') == 1.8


@pytest.mark.skipif(os.geteuid() == 0, reason='root ignores file permissions')
@pytest.mark.parametrize('name,cls,good,mutate', STORES, ids=IDS)
def test_an_unreadable_file_keeps_its_bytes(tmp_path, name, cls, good, mutate) -> None:
    path = tmp_path / 'file.json'
    path.write_text(good, encoding='utf-8')
    path.chmod(0)                                   # exists, cannot be read
    try:
        store = cls(path)
        mutate(store)
        moved = _quarantined(path)
        # Either the unreadable file was moved aside intact, or it is still the
        # original and was never written to.  Either way the bytes exist.
        holders = moved or [path]
        for h in holders:
            h.chmod(stat.S_IRUSR | stat.S_IWUSR)
        assert any(h.read_text(encoding='utf-8') == good for h in holders)
    finally:
        for p in tmp_path.iterdir():
            p.chmod(stat.S_IRUSR | stat.S_IWUSR)


@pytest.mark.parametrize('name,cls,good,mutate', STORES, ids=IDS)
def test_saves_are_blocked_when_the_file_cannot_be_moved_aside(
        tmp_path, monkeypatch, caplog, name, cls, good, mutate) -> None:
    import unicornviz.safe_store as ss

    path = tmp_path / 'file.json'
    raw = b'{ truncated'
    path.write_bytes(raw)

    def refuse(*_a, **_k):
        raise PermissionError('read-only directory')
    # Patch the helper module's own names: ``ss.os`` is the real os module, and
    # Path.replace (used by the stores' atomic save) goes through os.replace.
    monkeypatch.setattr(ss, 'os', SimpleNamespace(replace=refuse))
    monkeypatch.setattr(ss, 'shutil', SimpleNamespace(copy2=refuse))
    with caplog.at_level(logging.ERROR):
        store = cls(path)
    mutate(store)
    mutate(store)                                   # still nothing written
    assert path.read_bytes() == raw
    assert _quarantined(path) == []
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any('NOT saving' in m or 'not saving' in m for m in errors)
    assert sum('not saving to' in m for m in errors) <= 1       # logged once, not per save


def test_a_copy_fallback_still_preserves_the_bytes(tmp_path, monkeypatch) -> None:
    """Rename refused but copy allowed: the copy holds the bytes, saving is then safe."""
    import unicornviz.safe_store as ss

    path = tmp_path / 'file.json'
    path.write_bytes(b'{ truncated')
    def no_rename(*_a, **_k):
        raise OSError('rename refused')
    monkeypatch.setattr(ss, 'os', SimpleNamespace(replace=no_rename))
    store = RuntimeStateStore(path)
    moved = _quarantined(path)
    assert len(moved) == 1 and moved[0].read_bytes() == b'{ truncated'
    store.set('a', 1)
    assert json.loads(path.read_text(encoding='utf-8'))['a'] == 1
    assert moved[0].read_bytes() == b'{ truncated'


def test_two_quarantines_in_one_second_do_not_collide(tmp_path) -> None:
    path = tmp_path / 'file.json'
    for n in range(3):
        path.write_bytes(b'bad %d' % n)
        RuntimeStateStore(path)
        path.unlink(missing_ok=True)
    assert sorted(p.read_bytes() for p in _quarantined(path)) == [b'bad 0', b'bad 1', b'bad 2']


def test_dropped_entries_are_kept_in_a_copy(tmp_path) -> None:
    path = tmp_path / 'cp.json'
    raw = json.dumps({'profiles': {'ok': {'a': 1}, 'broken': 'oops'}})
    path.write_text(raw, encoding='utf-8')
    store = ConfigProfileStore(path)
    assert store.names() == ['ok']
    copies = _quarantined(path)
    assert len(copies) == 1 and copies[0].read_text(encoding='utf-8') == raw
    assert path.read_text(encoding='utf-8') == raw          # the original itself is untouched
