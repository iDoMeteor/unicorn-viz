"""Tests for effect enable/disable exclusion in the playlist rotation.

Disabled effects are skipped by advance/prev/random, but a manual go_index()
jump can still reach them. Falls back gracefully when everything is disabled.
"""
from __future__ import annotations

from unicornviz.playlist import Playlist


class _Cfg:
    def __init__(self, mode: str = 'sequential') -> None:
        self._mode = mode

    def get(self, section: str, key: str, default=None):
        if section == 'demo' and key == 'mode':
            return self._mode
        return default


def _fx(name: str):
    return type(name, (), {'NAME': name})


def _playlist(names, mode='sequential'):
    return Playlist([_fx(n) for n in names], _Cfg(mode))


def test_advance_skips_disabled_sequential():
    pl = _playlist(['A', 'B', 'C', 'D'])
    pl.set_disabled({'B', 'C'})
    assert pl.current().NAME == 'A'
    assert pl.advance().NAME == 'D'   # B, C skipped
    assert pl.advance().NAME == 'A'   # wraps past D


def test_go_prev_skips_disabled():
    pl = _playlist(['A', 'B', 'C', 'D'])
    pl.set_disabled({'B', 'C'})
    assert pl.go_prev().NAME == 'D'   # from A backward, skip C, B -> D


def test_go_index_still_reaches_disabled():
    pl = _playlist(['A', 'B', 'C', 'D'])
    pl.set_disabled({'B'})
    assert pl.go_index(1).NAME == 'B'  # manual jump is always allowed


def test_all_disabled_stays_put():
    pl = _playlist(['A', 'B', 'C'])
    pl.set_disabled({'A', 'B', 'C'})
    assert pl.advance().NAME == 'A'    # no enabled target -> current stays


def test_random_advance_never_hits_disabled():
    pl = _playlist(['A', 'B', 'C', 'D', 'E'], mode='random')
    pl.set_disabled({'B', 'D'})
    seen = {pl.advance().NAME for _ in range(60)}
    assert 'B' not in seen and 'D' not in seen
    assert seen  # something was chosen


def test_reenable_restores_rotation():
    pl = _playlist(['A', 'B', 'C'])
    pl.set_disabled({'B', 'C'})
    assert pl.advance().NAME == 'A'    # only A enabled -> stays
    pl.set_disabled(set())             # re-enable all
    assert pl.advance().NAME == 'B'
