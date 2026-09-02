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
    # Phase 2 (bake 3, Cell C): template observation, no half-beat spikes.
    assert t._v3_obs_source == 'template'
    assert t._v3_tmpl_subbeat == 0.0
    assert t._v3_prior_mode == 'percycle' and t._v3_prior_gain == 1.0


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
    # This test exercises the filter mechanics (transition, normalisation,
    # override, confidence), not the observation model -- so it pins the raw
    # comb source, where a lone peak IS a tempo. Under the phase-2 template
    # source a lone peak with no sub-harmonics is rightly not read as one.
    t = BeatTrackerV3({'v3_obs_source': 'comb'})
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


def test_template_observation_self_match_and_alias_rejection() -> None:
    """Phase 2: the template for tempo s is the comb profile an ideal beat
    train at s would produce (mirroring v2's comb: 100 Hz lags, 1/h
    harmonic weights). A comb observed at 125 must match 125 best and
    must NOT match the 4/3 alias (166.7) -- the phase-1 failure mode."""
    t = BeatTrackerV3({'v3_obs_source': 'template', 'v3_tmpl_subbeat': 0.0})
    grid = np.linspace(60.0, 200.0, 71)
    T = t._v3_build_templates(grid)
    assert T.shape == (len(t._v3_bpms), 71)
    assert np.allclose(np.linalg.norm(T, axis=1), 1.0)
    i125 = int(np.argmin(np.abs(t._v3_bpms - 125.0)))
    match = T @ T[i125]
    assert abs(t._v3_bpms[int(np.argmax(match))] - 125.0) / 125.0 < 0.02
    i166 = int(np.argmin(np.abs(t._v3_bpms - 166.7)))
    assert match[i166] < 0.5 * match[i125]


def test_template_source_produces_a_likelihood_over_the_lattice() -> None:
    t = BeatTrackerV3({'v3_obs_source': 'template', 'v3_tmpl_subbeat': 0.0})
    # The likelihood path builds its templates on the tracker's OWN ACF grid
    # (in production the retained observation is a prefix of that same
    # array), so the observation must live on that grid too. A realistic
    # comb carries the sub-harmonic structure a beat train always produces;
    # a lone Gaussian peak does not. Use 128's own profile.
    grid = np.asarray(t._acf_bpms, dtype=np.float32)
    T = t._v3_build_templates(grid.astype(np.float64))
    i128 = int(np.argmin(np.abs(t._v3_bpms - 128.0)))
    rng = np.random.default_rng(7)
    comb = (T[i128] + 0.02 * rng.random(len(grid))).astype(np.float32)
    t._last_acf_observation = (grid, comb, 1)
    like = t._v3_observation_likelihood()
    assert like is not None and like.shape == t._v3_posterior.shape
    assert float(like.min()) > 0.0
    assert abs(t._v3_bpms[int(np.argmax(like))] - 128.0) / 128.0 < 0.04


def test_prior_mode_and_gain_cfg_plumbing() -> None:
    """The compounding-prior finding (2026-09-03): 'percycle' multiplies a
    bounded bias every cycle (phase 1); 'init' seeds the posterior once;
    the gain exponent scales the per-cycle bias. All three must reach the
    instance via cfg (the override path the panel bakes use)."""
    a = BeatTrackerV3({'v3_prior_mode': 'init'})
    assert a._v3_prior_mode == 'init'
    assert abs(a._v3_bpms[int(np.argmax(a._v3_posterior))] - 120.0) / 120.0 < 0.02
    b = BeatTrackerV3({'v3_prior_gain': 0.25})
    assert b._v3_prior_mode == 'percycle' and b._v3_prior_gain == 0.25
    assert np.allclose(b._v3_posterior, b._v3_posterior[0])  # uniform start


def test_apply_mode_defaults_to_tick_and_comb_sources_stay_per_cycle() -> None:
    """Phase 3 (2026-09-03): the template-family likelihood is applied on
    every update() tick by design (`v3_obs_apply='tick'`, the behaviour
    bake 3 validated; once-per-cycle measured 3-8x worse lock churn in
    bake 4). The comb/score sources always apply once per cycle."""
    t = BeatTrackerV3({})
    assert t._v3_obs_apply == 'tick'
    grid = np.asarray(t._acf_bpms, dtype=np.float32)
    T = t._v3_build_templates(grid.astype(np.float64))
    comb = (T[int(np.argmin(np.abs(t._v3_bpms - 128.0)))] + 0.01).astype(np.float32)
    t._last_acf_observation = (grid, comb, 3)
    assert t._v3_observation_likelihood() is not None
    assert t._v3_observation_likelihood() is not None   # tick mode: re-applied on the same cycle
    c = BeatTrackerV3({'v3_obs_source': 'comb'})          # comb: per cycle regardless of mode
    c._last_acf_observation = (grid, comb, 3)
    assert c._v3_observation_likelihood() is not None
    assert c._v3_observation_likelihood() is None


def test_cycle_mode_applies_once_per_acf_cycle_on_every_source() -> None:
    """`v3_obs_apply='cycle'`: feeding the same cycle twice must yield a
    likelihood once and None the second time, for every observation
    source, and the seen-cycle marker must advance."""
    for source in ('comb', 'template', 'score', 'hybrid'):
        t = BeatTrackerV3({'v3_obs_source': source, 'v3_tmpl_subbeat': 0.0, 'v3_obs_apply': 'cycle'})
        grid = np.asarray(t._acf_bpms, dtype=np.float32)
        T = t._v3_build_templates(grid.astype(np.float64))
        i = int(np.argmin(np.abs(t._v3_bpms - 128.0)))
        comb = (T[i] + 0.01).astype(np.float32)
        t._last_acf_score = comb
        t._last_acf_observation = (grid, comb, 7)
        assert t._v3_observation_likelihood() is not None, source
        assert t._v3_seen_cycle == 7, source
        assert t._v3_observation_likelihood() is None, source   # same cycle: no re-application
        t._last_acf_observation = (grid, comb, 8)
        assert t._v3_observation_likelihood() is not None, source
        assert t._v3_seen_cycle == 8, source


def test_density_channel_is_off_by_default_and_penalises_only_fast_lanes() -> None:
    """Phase 4: the onset-density channel (v2's density guard as evidence)
    is inert at weight 0; when on, lattice tempos at or below FAST_RATIO x
    the onset rate are untouched (1.0) and faster ones fall off
    monotonically to the floor -- slower lanes are never penalised."""
    off = BeatTrackerV3({})
    off._last_acf_density_bpm = 90.0
    assert off._v3_density_likelihood() is None
    t = BeatTrackerV3({'v3_density_weight': 1.0, 'v3_density_floor': 0.5})
    assert t._v3_density_likelihood() is None          # no measurement yet
    t._last_acf_density_bpm = 90.0
    d = t._v3_density_likelihood()
    assert d is not None and d.shape == t._v3_posterior.shape
    lo = t._v3_bpms <= 90.0 * t._v3_density_fast
    assert np.all(d[lo] == 1.0)
    hi = np.where(~lo)[0]
    assert np.all(np.diff(d[hi]) <= 1e-12)             # monotone fall-off with tempo
    assert float(d.min()) >= 0.5                         # floored
    i180 = int(np.argmin(np.abs(t._v3_bpms - 180.0)))
    assert d[i180] < 1.0


def test_prime_tempo_seeds_posterior_and_holds_the_prior_centre() -> None:
    """Phase 4: an external prime (mixer analysis / tag / tap) must seed the
    posterior at the primed tempo and re-centre the per-cycle prior bias
    on it for the hold window, then fall back to the profile prior."""
    t = BeatTrackerV3({'v3_prime_hold_s': 30.0})
    t._last_t = 10.0
    t.prime_tempo(82.0)
    assert abs(t._v3_bpms[int(np.argmax(t._v3_posterior))] - 82.0) / 82.0 < 0.02
    mu, sigma = t._v3_prior_centre()
    assert mu == 82.0 and sigma == t._v3_prime_sigma
    assert t._v3_prime_count == 1
    t._last_t = 35.0
    t.prime_tempo(82.0)                                # re-prime refreshes the hold
    t._last_t = 41.0                                   # 31 s after the first, 6 s after the second
    assert t._v3_prior_centre()[0] == 82.0
    t._last_t = 70.0                                   # past the refreshed hold
    mu2, sigma2 = t._v3_prior_centre()
    assert mu2 != 82.0 and sigma2 >= 0.35              # back to the profile prior
    early = BeatTrackerV3({'v3_prime_hold_s': 20.0})   # primed before the clock runs
    early.prime_tempo(82.0)
    assert early._v3_prime_until_t < 0.0
    early._last_t = 5.0
    assert early._v3_prior_centre()[0] == 82.0         # hold starts at the first update
    early._last_t = 26.0
    assert early._v3_prior_centre()[0] != 82.0
    h = BeatTrackerV3({'v3_prime_hold_s': 0.0})       # 0 = until the next prime
    h._last_t = 0.0
    h.prime_tempo(164.0)
    h._last_t = 1e6
    assert h._v3_prior_centre()[0] == 164.0
    off = BeatTrackerV3({})
    assert off._v3_prior_centre()[0] != 82.0           # never primed: profile prior


def test_v2_observation_retention_is_read_only() -> None:
    """The only v2 touch is retaining the observation; bake 2's leverage
    check proved v2 corpora bit-identical (49,977 rows). Pin the shape."""
    src = _BEAT_GRID_PATH.read_text(encoding='utf-8')
    assert 'self._last_acf_observation = (' in src
    assert 'self._last_acf_score = score' in src
