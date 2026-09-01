"""Tests for the decider switch-backoff (2026-09-01, recommender rc.25).

The Love-Spirit-flicker stability item: applied-profile switches must
escalate both decider cooldowns exponentially, decay with quiet time,
and count backoff-only blocks as engagement. Bound onto a bare stub the
way the other decider tests do — no GL, no audio.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'test_decider_backoff_av', _REPO / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py')
assert spec is not None and spec.loader is not None
_AV = importlib.util.module_from_spec(spec)
sys.modules['test_decider_backoff_av'] = _AV
spec.loader.exec_module(_AV)


class _Manager:
    def __init__(self) -> None:
        self.key = 'house'
        self.sets: list[str] = []

    def get_profile_key(self) -> str:
        return self.key

    def set_profile(self, key: str) -> None:
        self.sets.append(key)
        self.key = key


class _VjApi:
    @staticmethod
    def is_user_busy() -> bool:
        return False


class _App:
    vj_api = _VjApi()


class _Engine:
    @staticmethod
    def mark(*_a, **_k) -> None:
        return None


def _make(now: float = 1000.0):
    c = object.__new__(_AV.AutoVJController)
    c._profile_auto_reco_decider_enabled = True
    c._app = _App()
    c._recommended_profile_confirmed = True
    c._profile_auto_reco_decider_min_margin = 0.0
    c._profile_auto_reco_decider_min_confidence = 0.0
    c._profile_auto_reco_decider_cooldown_s = 20.0
    c._profile_auto_reco_decider_force_cooldown_s = 6.0
    c._profile_auto_reco_decider_force_recommended_prob = 2.0  # fast path off
    c._profile_auto_reco_decider_force_current_prob_cap = -1.0
    c._profile_auto_reco_switch_backoff_mult = 2.0
    c._profile_auto_reco_switch_backoff_decay_s = 90.0
    c._profile_auto_reco_switch_backoff_max = 4
    c._decider_backoff_level = 0
    c._decider_backoff_gated_count = 0
    c._profile_auto_reco_last_apply_t = 0.0
    c._mood_prime_expected_key = ''
    c._engine = _Engine()
    c._clock = [now]
    c._now = lambda: c._clock[0]
    return c


def _try_apply(c, key: str = 'trance') -> None:
    c._maybe_apply_recommended_audio_profile(
        manager=c._mgr, recommended_key=key, recommended_score=1.0,
        current_score=0.5, recommended_prob=0.9, current_prob=0.1,
        score_margin=0.5, mean_confidence=0.9, detector_trust=1.0)


def test_each_switch_escalates_and_backoff_blocks() -> None:
    c = _make()
    c._mgr = _Manager()
    _try_apply(c, 'trance')                      # level 0 -> applies
    assert c._mgr.sets == ['trance']
    assert c._decider_backoff_level == 1
    c._clock[0] += 25.0                          # past base 20s, inside 40s (20*2^1)
    _try_apply(c, 'house')
    assert c._mgr.sets == ['trance'], 'backoff must block what base cooldown allows'
    assert c._decider_backoff_gated_count == 1
    c._clock[0] += 20.0                          # 45s elapsed >= 40s eff cooldown
    _try_apply(c, 'house')
    assert c._mgr.sets == ['trance', 'house']
    assert c._decider_backoff_level == 2


def test_quiet_time_decays_level() -> None:
    c = _make()
    c._mgr = _Manager()
    _try_apply(c, 'trance')
    assert c._decider_backoff_level == 1
    c._clock[0] += 20.0 + 2 * 90.0 + 1.0         # base cooldown + 2 decay steps
    _try_apply(c, 'house')
    # level decayed to 0 before the apply, then escalated to 1 by it
    assert c._mgr.sets == ['trance', 'house']
    assert c._decider_backoff_level == 1


def test_level_caps_at_max() -> None:
    c = _make()
    c._mgr = _Manager()
    keys = ['a', 'b'] * 6
    for k in keys:
        c._clock[0] += 20.0 * (2.0 ** c._profile_auto_reco_switch_backoff_max) + 1
        _try_apply(c, k)
    assert c._decider_backoff_level <= 4
