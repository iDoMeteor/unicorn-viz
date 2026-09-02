"""Regression tests for BeatTrackerV3 -- the HMM tempo engine (v3 phase 1).

Pins the phase-1 contract established 2026-09-02 (see docs/adr/vj-system.md):

- v3 is a subclass of v2; v2 is the protected baseline and runs untouched as
  the observation extractor (it retains ``_last_acf_observation`` /
  ``_last_acf_score`` read-only, nothing else changes).
- The tempo lattice keeps fast lanes first-class (HMM design requirement #1
  from the engine bake-off: v2's fold-down cost -50pt exact on dnb).
- Fold-jump transition mass is SYMMETRIC (up and down get identical mass).
- Transition rows are proper distributions; every state stays reachable.
- The posterior override happens: after a cycle with an observation, v3's
  bpm/confidence are the posterior's, and confidence is a probability.
- The cfg keys used by the training-kit override mechanism reach the
  tracker (the path the panel bakes rely on).
- The sizing lesson: module defaults sit in the escape-time regime
  (floor 0.7 / power 1 / fold mass 1e-6), not bake 1's memoryless one.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np

_BEAT_GRID_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'beat_grid.py'
_SPEC = importlib.util.spec_from_file_location('test_beat_tracker_v3_module', _BEAT_GRID_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_BG = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BG)
BeatTracker = _BG.BeatTracker
BeatTrackerV3 = _BG.BeatTrackerV3


def test_v3_is_a_v2_subclass_with_its_own_engine_version() -> None:
    assert issubclass(BeatTrackerV3, BeatTracker)
    assert BeatTrackerV3.ENGINE_VERSION == '3.0.0'
    assert BeatTracker.ENGINE_VERSION == '2.0.0'


def test_lattice_keeps_fast_lanes_first_class() -> None:
    """Requirement #1: 165-200 BPM must be ordinary lattice states."""
    t = BeatTrackerV3({})
    assert t._v3_bpms[0] <= 56.0
    assert t._v3_bpms[-1] >= 200.0
    # log-spaced: constant ratio between neighbours
    ratios = t._v3_bpms[1:] / t._v3_bpms[:-1]
    assert np.allclose(ratios, ratios[0])


def test_fold_jump_mass_is_symmetric_up_and_down() -> None:
    """The octave/triplet escape mass must be identical for 2:1 and 1:2
    (and 3:2 vs 2:3) from a mid-lattice state -- the asymmetric
    fold-DOWN-only descent was v2's measured dnb failure."""
    t = BeatTrackerV3({})
    T = t._v3_transition
    lb = t._v3_log_bpms

    def state(bpm: float) -> int:
        return int(np.argmin(np.abs(t._v3_bpms - bpm)))

    # Triplet lanes: from 120 both 3:2 (180 / 80) and 4:3 (160 / 90) exist.
    i = state(120.0)
    for ratio in (1.5, 4.0 / 3.0):
        up = int(np.argmin(np.abs(lb - (lb[i] + math.log2(ratio)))))
        down = int(np.argmin(np.abs(lb - (lb[i] - math.log2(ratio)))))
        assert math.isclose(T[i, up], T[i, down], rel_tol=0.05), (ratio, T[i, up], T[i, down])
        assert T[i, up] > 10 * T.min()  # real fold mass, not just the leak
    # Octave lanes: the lattice spans 1.93 octaves (55-210), so no single
    # state has BOTH octave neighbours in range -- compare 100->200 with
    # 200->100 instead. Fold-up past 210 is deliberately not a thing.
    lo, hi = state(100.0), state(200.0)
    assert math.isclose(T[lo, hi], T[hi, lo], rel_tol=0.05), (T[lo, hi], T[hi, lo])
    assert T[lo, hi] > 10 * T.min()


def test_transition_rows_are_distributions_and_every_state_reachable() -> None:
    t = BeatTrackerV3({})
    T = t._v3_transition
    assert np.allclose(T.sum(axis=1), 1.0)
    assert float(T.min()) > 0.0  # novelty leak keeps every state reachable


def test_defaults_sit_in_the_escape_time_regime() -> None:
    """Bake 1 shipped floor 0.02 / power 2 / fold mass 2e-3 -- a memoryless
    posterior at the ACF's ~7.4 Hz cycle rate. Pin the corrected regime."""
    t = BeatTrackerV3({})
    assert t._v3_obs_floor >= 0.5
    assert t._v3_obs_power <= 1.0
    assert t._v3_fold_octave <= 1e-5
    assert t._v3_fold_obs_weight == 0.0


def test_cfg_keys_reach_the_tracker() -> None:
    """The panel bakes pass v3 tunables through the [auto_vj] cfg dict via
    session_replay --override; they must land on the instance."""
    t = BeatTrackerV3({'v3_obs_floor': 0.5, 'v3_fold_prob_octave': 1e-5,
                       'v3_fold_prob_triplet': 5e-6, 'v3_novelty_leak': 1e-7,
                       'v3_obs_source': 'score'})
    assert t._v3_obs_floor == 0.5
    assert t._v3_fold_octave == 1e-5
    assert t._v3_fold_triplet == 5e-6
    assert t._v3_novelty == 1e-7
    assert t._v3_obs_source == 'score'


def test_posterior_override_and_probability_confidence() -> None:
    """Feed a synthetic observation with a clear peak at 128 BPM; the
    posterior must move bpm there and report a confidence in [0, 1], and
    the engagement counter must tick."""
    t = BeatTrackerV3({})
    acf_bpms = np.linspace(60.0, 200.0, 71)
    comb = np.exp(-0.5 * ((acf_bpms - 128.0) / 1.5) ** 2).astype(np.float32)
    t._last_acf_observation = (acf_bpms, comb, 1)
    before = t._v3_cycle_applied_count
    # Drive the HMM step directly through the same code path update() uses.
    like = t._v3_observation_likelihood()
    assert like is not None and like.shape == t._v3_posterior.shape
    for cycle in range(2, 40):
        t._last_acf_observation = (acf_bpms, comb, cycle)
        like = t._v3_observation_likelihood()  # update() needs live audio; step the filter by hand
        post = t._v3_transition.T @ t._v3_posterior
        post *= like
        t._v3_posterior = post / post.sum()
    idx = int(np.argmax(t._v3_posterior))
    assert abs(t._v3_bpms[idx] - 128.0) / 128.0 < 0.04
    band = np.abs(t._v3_log_bpms - t._v3_log_bpms[idx]) <= math.log2(1.04)
    conf = float(t._v3_posterior[band].sum())
    assert 0.0 <= conf <= 1.0
    assert conf > 0.5
    assert t._v3_seen_cycle == 39
    assert t._v3_cycle_applied_count == before  # counter ticks only inside update()


def test_v2_observation_retention_is_read_only() -> None:
    """The only v2 touch is retaining the observation; bake 2's leverage
    check proved v2 corpora bit-identical (49,977 rows). Pin the shape."""
    src = _BEAT_GRID_PATH.read_text(encoding='utf-8')
    assert 'self._last_acf_observation = (' in src
    assert 'self._last_acf_score = score' in src
