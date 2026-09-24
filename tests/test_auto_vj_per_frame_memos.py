"""Regression tests for Auto VJ's per-frame cost memos (auto-vj-01 rc.150).

Phase A of docs/planning/auto-vj-per-frame-cost-plan-2026-09-24.md: the
detector and director stopped recomputing values whose inputs had not
changed.  Each memo must be *exact* -- it returns what a fresh computation
returns -- and must let go the moment its input changes.  (The end-to-end
proof was a seeded replay hashing every tick's detector/director outputs,
identical before and after; these pin the pieces.)
"""

from __future__ import annotations

import importlib.util
import math
from collections import deque
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01'


def _load(name: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, _ROOT / name)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_BG = _load('beat_grid.py', 'test_per_frame_memos_beat_grid')
_AV = _load('auto_vj.py', 'test_per_frame_memos_auto_vj')
BeatTrackerV3 = _BG.BeatTrackerV3

_CFG = {'v3_obs_source': 'template', 'v3_obs_apply': 'tick'}


def _obs(peak_bpm: float, cycle: int):
    acf_bpms = np.linspace(200.0, 60.0, 71).astype(np.float32)   # ACF lags: descending bpm
    comb = sum(np.exp(-0.5 * ((acf_bpms - peak_bpm / k) / 1.5) ** 2) / k for k in (1, 2, 4))
    return (acf_bpms, comb.astype(np.float32), cycle)


def test_template_observation_memo_matches_a_fresh_tracker_every_tick() -> None:
    """Ticks reuse the memo (tick mode, one observation), and the in-place
    prior multiply never leaks into it: every tick equals a fresh tracker's
    answer for the same observation."""
    t = BeatTrackerV3(_CFG)
    t._last_acf_observation = _obs(128.0, 1)
    ticks = [t._v3_observation_likelihood() for _ in range(4)]
    fresh = BeatTrackerV3(_CFG)
    fresh._last_acf_observation = t._last_acf_observation
    expected = fresh._v3_observation_likelihood()
    for like in ticks:
        assert like is not None
        assert np.array_equal(like, expected)


def test_template_observation_memo_lets_go_on_a_new_observation() -> None:
    t = BeatTrackerV3(_CFG)
    t._last_acf_observation = _obs(128.0, 1)
    first = t._v3_observation_likelihood()
    t._last_acf_observation = _obs(174.0, 2)
    second = t._v3_observation_likelihood()
    fresh = BeatTrackerV3(_CFG)
    fresh._last_acf_observation = t._last_acf_observation
    assert not np.array_equal(first, second)
    assert np.array_equal(second, fresh._v3_observation_likelihood())


def test_template_observation_memo_follows_a_changed_setting() -> None:
    t = BeatTrackerV3(_CFG)
    t._last_acf_observation = _obs(128.0, 1)
    before = t._v3_observation_likelihood()
    t._v3_obs_power = t._v3_obs_power * 2.0
    after = t._v3_observation_likelihood()
    assert not np.array_equal(before, after)


def test_acf_comb_matches_the_unmemoized_lag_loop() -> None:
    """The per-call lag-product memo is bit-identical to computing every
    base and harmonic lag's dot product afresh (the pre-rc.150 loop)."""
    t = BeatTrackerV3({})
    rng = np.random.default_rng(3)
    n = t._acf_lag_max + 400
    env = np.zeros(n, dtype=np.float32)
    env[::47] = 1.0                                   # ~128 BPM at 100 Hz
    env += rng.random(n).astype(np.float32) * 0.05
    t._get_envelope = lambda: env
    t._estimate_tempo_acf()
    got = t._last_acf_observation[1]

    env_zm = env - env.mean()
    norm = float(np.dot(env_zm, env_zm)) + 1e-9
    lag_min = t._acf_lag_min
    lag_max = min(t._acf_lag_max, len(env) - 1)
    n_lags = lag_max - lag_min + 1
    total = len(env_zm)
    acf = np.empty(n_lags, dtype=np.float32)
    for i in range(n_lags):
        lag = lag_min + i
        acf[i] = (float(np.dot(env_zm[lag:], env_zm[:total - lag])) / norm
                  * (total / max(1, total - lag)) ** 0.5)
    comb = np.clip(acf, 0.0, None).copy()
    for h in range(2, _BG._V2_COMB_HARMONICS + 1):
        for i in range(n_lags):
            lag = (lag_min + i) * h
            if lag >= total:
                break
            acf_h = (float(np.dot(env_zm[lag:], env_zm[:total - lag])) / norm
                     * (total / max(1, total - lag)) ** 0.5)
            if acf_h > 0.0:
                comb[i] += acf_h / h
    assert np.array_equal(got, comb)


def test_fold_masks_cached_for_the_live_lattice_only() -> None:
    t = BeatTrackerV3({})
    like = np.linspace(0.7, 1.0, len(t._v3_log_bpms))
    half = math.log2(1.04)
    idx = len(like) // 2
    live = t._v3_compute_fold_suspect_mass(like, idx, t._v3_log_bpms, half)
    assert t._v3_compute_fold_suspect_mass(like, idx, t._v3_log_bpms, half) == live
    shifted = t._v3_log_bpms + 0.3                     # same length, other lattice
    other = BeatTrackerV3({})._v3_compute_fold_suspect_mass(like, idx, shifted, half)
    assert t._v3_compute_fold_suspect_mass(like, idx, shifted, half) == other


def _bare_controller():
    inst = object.__new__(_AV.AutoVJController)
    inst._kick_phases = deque(maxlen=16)
    inst._sub_energies = deque(maxlen=16)
    return inst


def _fresh_regularity(phases) -> float:
    angles = np.asarray(list(phases), dtype=np.float64) * 2.0 * np.pi
    return float(np.clip(abs(np.mean(np.exp(1j * angles))), 0.0, 1.0))


def test_kick_regularity_memo_tracks_every_new_phase() -> None:
    c = _bare_controller()
    rng = np.random.default_rng(5)
    for _ in range(40):                                # past maxlen: the window slides
        c._kick_phases.append(float(rng.random()))
        c._sub_energies.append(float(rng.random()))
        for _repeat in range(3):                       # three readers per frame
            if len(c._kick_phases) >= 4:
                assert c._compute_kick_regularity() == _fresh_regularity(c._kick_phases)
            assert c._compute_sub_level() == float(np.mean(list(c._sub_energies)))
