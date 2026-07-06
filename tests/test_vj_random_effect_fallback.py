"""Regression: goto_random_effect must never strand the VJ on a tag miss.

When no *enabled* effect carries any requested mood tag, the director should
fall back to any enabled effect rather than returning None (which kept the show
locked to the handful of tagged effects — the "stuck in psychedelics" bug).
"""
from __future__ import annotations

from unicornviz.vj_api import VJApi


def _fx(name: str, tags: list[str]):
    return type(name, (), {'NAME': name, 'TAGS': list(tags)})


class _RNG:
    def choice(self, seq):
        return seq[0]


class _App:
    def __init__(self) -> None:
        self._current_effect = None
        self._rng = _RNG()
        self.went: list = []

    def goto_effect(self, cls) -> None:
        self.went.append(cls)


def _vj(effects):
    vj = VJApi.__new__(VJApi)
    vj._app = _App()
    vj.enabled_effect_classes = lambda: list(effects)
    return vj


def test_fallback_when_no_tag_matches() -> None:
    vj = _vj([_fx('A', ['classic']), _fx('B', ['tech'])])
    name = vj.goto_random_effect(tags=['intense', 'drop'])  # nothing has these
    assert name in ('A', 'B')          # fell back to any enabled
    assert len(vj._app.went) == 1      # actually switched


def test_tag_match_still_filters() -> None:
    vj = _vj([_fx('Psy', ['psychedelic']), _fx('Tek', ['tech'])])
    assert vj.goto_random_effect(tags=['psychedelic']) == 'Psy'


def test_no_tags_uses_all_enabled() -> None:
    vj = _vj([_fx('A', ['x']), _fx('B', ['y'])])
    assert vj.goto_random_effect(tags=None) in ('A', 'B')


def test_empty_enabled_returns_none() -> None:
    vj = _vj([])
    assert vj.goto_random_effect(tags=['anything']) is None
    assert vj.goto_random_effect(tags=None) is None
