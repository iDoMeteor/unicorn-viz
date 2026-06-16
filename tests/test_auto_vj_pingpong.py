from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_AUTO_VJ_SPEC = importlib.util.spec_from_file_location('test_auto_vj_module', _AUTO_VJ_PATH)
assert _AUTO_VJ_SPEC is not None and _AUTO_VJ_SPEC.loader is not None
_AUTO_VJ_MODULE = importlib.util.module_from_spec(_AUTO_VJ_SPEC)
_AUTO_VJ_SPEC.loader.exec_module(_AUTO_VJ_MODULE)
AutoVJController = _AUTO_VJ_MODULE.AutoVJController


class _Rng:
    def __init__(self) -> None:
        self.calls: list[list[object]] = []

    def choice(self, seq):
        values = list(seq)
        self.calls.append(values)
        return values[0]


class _Friendless:
    NAME = 'Friendless'


class _InvalidOnly:
    NAME = 'InvalidOnly'
    PING_PONG_FRIENDS = ['Missing', 'InvalidOnly']


class _Pair:
    NAME = 'Pair'
    PING_PONG_FRIENDS = ['Partner']


class _Partner:
    NAME = 'Partner'


class _Trio:
    NAME = 'Trio'
    PING_PONG_FRIENDS = ['PartnerA', 'PartnerB']


class _PartnerA:
    NAME = 'PartnerA'


class _PartnerB:
    NAME = 'PartnerB'


@pytest.fixture()
def controller() -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._rng = _Rng()
    return inst


def test_random_pingpong_pair_ignores_friendless_effects(monkeypatch, controller: AutoVJController) -> None:
    monkeypatch.setattr(
        'unicornviz.effects.registry.get_effects',
        lambda: [_Friendless, _InvalidOnly, _Pair, _Partner, _Trio, _PartnerA, _PartnerB],
    )

    pair = controller.random_pingpong_pair()

    assert pair == ('Pair', 'Partner')
    assert len(controller._rng.calls) == 2
    candidate_names = [name for name, _friends in controller._rng.calls[0]]
    assert candidate_names == ['Pair', 'Trio']
