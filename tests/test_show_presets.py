"""Tests for the show-preset store and playlist mode setter.

Covers the persistence foundation for named show setups: save/get/list/delete
round-trips through a real JSON file, unknown-key preservation, reload, and the
playlist's set_mode used by preset apply.
"""
from __future__ import annotations

from unicornviz.playlist import Playlist
from unicornviz.presets import ShowPresetStore


def _store(tmp_path):
    return ShowPresetStore(tmp_path / 'presets.json')


def test_save_get_roundtrip(tmp_path):
    s = _store(tmp_path)
    s.save('Ambient', {'version': 1, 'disabled_effects': ['A', 'B'], 'reactivity': 1.5})
    got = s.get('Ambient')
    assert got['disabled_effects'] == ['A', 'B']
    assert got['reactivity'] == 1.5


def test_names_sorted_case_insensitive(tmp_path):
    s = _store(tmp_path)
    s.save('zeta', {})
    s.save('Alpha', {})
    s.save('mid', {})
    assert s.names() == ['Alpha', 'mid', 'zeta']


def test_overwrite_updates(tmp_path):
    s = _store(tmp_path)
    s.save('Show', {'reactivity': 1.0})
    s.save('Show', {'reactivity': 2.0})
    assert s.get('Show')['reactivity'] == 2.0
    assert s.names() == ['Show']


def test_delete(tmp_path):
    s = _store(tmp_path)
    s.save('Show', {})
    assert s.delete('Show') is True
    assert s.get('Show') is None
    assert s.delete('Show') is False  # already gone


def test_missing_get_returns_none(tmp_path):
    assert _store(tmp_path).get('nope') is None


def test_empty_name_rejected(tmp_path):
    s = _store(tmp_path)
    try:
        s.save('   ', {})
    except ValueError:
        return
    raise AssertionError('expected ValueError for blank name')


def test_persists_across_reload(tmp_path):
    s1 = _store(tmp_path)
    s1.save('Streaming', {'playlist_mode': 'random', 'extra_future_key': 42})
    s2 = ShowPresetStore(tmp_path / 'presets.json')  # fresh instance, same file
    got = s2.get('Streaming')
    assert got['playlist_mode'] == 'random'
    assert got['extra_future_key'] == 42  # unknown keys preserved


def test_get_returns_copy(tmp_path):
    s = _store(tmp_path)
    s.save('Show', {'disabled_effects': ['A']})
    got = s.get('Show')
    got['disabled_effects'].append('B')
    assert s.get('Show')['disabled_effects'] == ['A']  # store not mutated


# --- playlist set_mode (used by preset apply) --------------------------------

class _Cfg:
    def get(self, section, key, default=None):
        return default


def _fx(name):
    return type(name, (), {'NAME': name})


def test_playlist_set_mode():
    pl = Playlist([_fx('A'), _fx('B'), _fx('C')], _Cfg())
    assert pl.mode == 'sequential'
    pl.set_mode('random')
    assert pl.mode == 'random'
    pl.set_mode('sequential')
    assert pl.mode == 'sequential'
    pl.set_mode('bogus')  # anything != 'random' -> sequential
    assert pl.mode == 'sequential'
