"""Regression tests for the sub/kick split + kick-regularity reshape
(2026-09-10, zone-map batch).

Three things landed together, all in ``AutoVJController``
(``drop-ins/auto-vj-01/auto_vj.py``):

1. The onset-time kick-band sample (previously one undifferentiated
   bands[0:12] mean) is split into a SUB slice (bands[0:_SUB_KICK_
   SPLIT_BAND]) and a KICK-PUNCH slice (bands[_SUB_KICK_SPLIT_BAND:12]).
2. A kick-TRANSIENT gate: only a kick-punch sample that notably exceeds
   the recent rolling baseline counts as a confirmed kick (vs. an onset
   -- any onset, detection is broadband -- that merely coincides with
   steady-state kick-band presence).
3. ``_compute_kick_regularity()`` reshaped from the raw kick-band
   energy's coefficient of variation to the circular-statistics mean
   resultant length of confirmed-kick beat-phases -- regularity is a
   TIMING concept (does the kick land at a consistent phase), not an
   amplitude one.

See docs/adr/vj-system.md "Sub/Kick Split + Kick-Regularity Reshape"
for the full diagnosis and the empirical crossover-band derivation.
"""
from __future__ import annotations

import importlib.util
import math
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_SPEC = importlib.util.spec_from_file_location('test_sub_kick_split_module', _AUTO_VJ_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
AutoVJController = _MOD.AutoVJController


def _bare(**overrides) -> AutoVJController:
    inst = object.__new__(AutoVJController)
    defaults = dict(
        _sub_energies=deque(maxlen=16),
        _kick_energies=deque(maxlen=16),
        _kick_phases=deque(maxlen=16),
        _kick_confirmed_count=0,
        _kick_rejected_count=0,
        _grid=SimpleNamespace(beat_phase=0.0),
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(inst, k, v)
    return inst


# ---------------------------------------------------------------------------
# _SUB_KICK_SPLIT_BAND -- the empirical crossover
# ---------------------------------------------------------------------------

def test_split_band_edge_matches_the_empirical_crossover() -> None:
    """Real corpus data (training-dubstep-01 vs. training-house-01, post
    the low-band analyzer fix) showed dubstep's sustained sub-bass
    dominating bands 0-2 and house's kick punch dominating bands 3-11 --
    the ratio flips sign exactly at band 3 (~40 Hz). Pin the Hz math so
    a future band-count/range change re-opens this deliberately, not
    silently."""
    edge = lambda i: 30.0 * (16000.0 / 30.0) ** (i / 64.0)  # noqa: E731
    n = AutoVJController._SUB_KICK_SPLIT_BAND
    assert n == 3
    assert 36.0 < edge(n) < 44.0  # the empirical crossover, ~40 Hz


# ---------------------------------------------------------------------------
# _sample_sub_kick_onset() -- split + transient gate
# ---------------------------------------------------------------------------

def test_sample_splits_sub_and_kick_bands_correctly() -> None:
    inst = _bare()
    bands = np.zeros(64, dtype=np.float32)
    bands[0:3] = 0.9   # sub
    bands[3:12] = 0.1  # kick-punch
    inst._sample_sub_kick_onset(SimpleNamespace(bands=bands))
    assert inst._sub_energies[-1] == pytest.approx(0.9, abs=1e-5)
    assert inst._kick_energies[-1] == pytest.approx(0.1, abs=1e-5)


def test_sample_ignores_non_array_or_short_bands() -> None:
    inst = _bare()
    inst._sample_sub_kick_onset(SimpleNamespace(bands=None))
    inst._sample_sub_kick_onset(SimpleNamespace(bands=np.zeros(5, dtype=np.float32)))
    assert len(inst._sub_energies) == 0
    assert len(inst._kick_energies) == 0
    assert inst._kick_confirmed_count == 0
    assert inst._kick_rejected_count == 0


def _bands_with_kick_level(level: float) -> np.ndarray:
    bands = np.zeros(64, dtype=np.float32)
    bands[3:12] = level
    return bands


def test_transient_gate_rejects_steady_state_presence() -> None:
    """A kick-band sample that just repeats the recent baseline (no real
    transient) must NOT be confirmed -- this is the exact confound the
    reshape targets: sustained sub/808 presence at every onset must not
    read as a series of confirmed kicks."""
    inst = _bare(_grid=SimpleNamespace(beat_phase=0.25))
    # Warm up the baseline with a few identical samples.
    for _ in range(5):
        inst._sample_sub_kick_onset(SimpleNamespace(bands=_bands_with_kick_level(0.5)))
    confirmed_before = inst._kick_confirmed_count
    rejected_before = inst._kick_rejected_count
    phases_before = len(inst._kick_phases)
    # One more sample at the SAME level -- no transient, must reject.
    inst._sample_sub_kick_onset(SimpleNamespace(bands=_bands_with_kick_level(0.5)))
    assert inst._kick_rejected_count == rejected_before + 1
    assert inst._kick_confirmed_count == confirmed_before
    assert len(inst._kick_phases) == phases_before


def test_transient_gate_confirms_a_real_spike() -> None:
    """A sample that clears the baseline by the gate ratio must be
    confirmed and record the current beat_phase."""
    inst = _bare(_grid=SimpleNamespace(beat_phase=0.37))
    for _ in range(5):
        inst._sample_sub_kick_onset(SimpleNamespace(bands=_bands_with_kick_level(0.5)))
    confirmed_before = inst._kick_confirmed_count
    # Comfortably above baseline * _KICK_TRANSIENT_GATE_RATIO (0.5 * 1.15 = 0.575).
    inst._sample_sub_kick_onset(SimpleNamespace(bands=_bands_with_kick_level(1.0)))
    assert inst._kick_confirmed_count == confirmed_before + 1
    assert inst._kick_phases[-1] == pytest.approx(0.37)


def test_transient_gate_never_confirms_before_a_real_baseline_exists() -> None:
    """The very first sample has no history to compare against
    (baseline starts at 0.0) -- must reject, not confirm on a vacuous
    'anything clears an empty baseline' technicality."""
    inst = _bare()
    inst._sample_sub_kick_onset(SimpleNamespace(bands=_bands_with_kick_level(0.8)))
    assert inst._kick_confirmed_count == 0
    assert inst._kick_rejected_count == 1
    assert len(inst._kick_phases) == 0


# ---------------------------------------------------------------------------
# _compute_kick_regularity() -- circular-statistics reshape
# ---------------------------------------------------------------------------

def test_kick_regularity_is_zero_with_fewer_than_four_confirmed_kicks() -> None:
    inst = _bare(_kick_phases=deque([0.1, 0.1, 0.1], maxlen=16))
    assert inst._compute_kick_regularity() == 0.0


def test_kick_regularity_is_high_for_tightly_clustered_phases() -> None:
    """A steady four-on-the-floor kick lands at roughly the same phase
    every time -- tightly clustered phases must read close to 1.0."""
    inst = _bare(_kick_phases=deque([0.10, 0.11, 0.09, 0.10, 0.10], maxlen=16))
    assert inst._compute_kick_regularity() > 0.95


def test_kick_regularity_is_low_for_uniformly_scattered_phases() -> None:
    """Phases spread evenly around the circle (no consistent pulse) must
    read close to 0.0 -- the defining case magnitude-CoV could not
    distinguish from a genuinely regular kick at a different amplitude."""
    inst = _bare(_kick_phases=deque([0.0, 0.25, 0.5, 0.75], maxlen=16))
    assert inst._compute_kick_regularity() < 0.05


def test_kick_regularity_handles_phase_wraparound_correctly() -> None:
    """Phases clustered around the 0.0/1.0 wrap boundary (e.g. 0.98,
    0.01, 0.99) are just as regular as phases clustered mid-range --
    circular statistics must not penalize wraparound the way a naive
    linear std/mean would."""
    wrapped = _bare(_kick_phases=deque([0.98, 0.01, 0.99, 0.02, 0.98], maxlen=16))
    midrange = _bare(_kick_phases=deque([0.48, 0.51, 0.49, 0.52, 0.48], maxlen=16))
    assert wrapped._compute_kick_regularity() > 0.95
    assert midrange._compute_kick_regularity() > 0.95
    assert wrapped._compute_kick_regularity() == pytest.approx(
        midrange._compute_kick_regularity(), abs=0.05
    )


def test_kick_regularity_stays_in_unit_range_for_arbitrary_phases() -> None:
    """Contract every consumer (BeatTracker._effective_tactus_ratio(),
    kick_regularity_fit) depends on: always a real number in [0, 1]."""
    rng = np.random.default_rng(0)
    for _ in range(20):
        n = rng.integers(4, 16)
        phases = deque((rng.random(n)).tolist(), maxlen=16)
        inst = _bare(_kick_phases=phases)
        r = inst._compute_kick_regularity()
        assert 0.0 <= r <= 1.0
        assert math.isfinite(r)


def test_kick_regularity_defensive_on_a_bare_stub_missing_the_deque() -> None:
    """getattr-defensive: regression tests across the suite drive
    _detector_snapshot() (which calls this) on bare object.__new__
    stubs that predate this deque -- must degrade to 0.0, not raise."""
    inst = object.__new__(AutoVJController)
    assert inst._compute_kick_regularity() == 0.0


# ---------------------------------------------------------------------------
# _compute_sub_level() -- presence/level read, not regularity
# ---------------------------------------------------------------------------

def test_sub_level_is_the_mean_of_recent_sub_samples() -> None:
    inst = _bare(_sub_energies=deque([0.2, 0.4, 0.6], maxlen=16))
    assert inst._compute_sub_level() == pytest.approx(0.4)


def test_sub_level_is_zero_with_no_samples() -> None:
    inst = _bare(_sub_energies=deque(maxlen=16))
    assert inst._compute_sub_level() == 0.0


def test_sub_level_ignores_phase_scatter_unlike_kick_regularity() -> None:
    """Presence, not regularity: a sub-band that's ALWAYS loud (even if
    the kicks riding on top of it are irregular) reads a high sub_level
    regardless of what kick_regularity says about timing."""
    inst = _bare(
        _sub_energies=deque([0.9, 0.9, 0.9, 0.9], maxlen=16),
        _kick_phases=deque([0.0, 0.25, 0.5, 0.75], maxlen=16),  # scattered -> low regularity
    )
    assert inst._compute_sub_level() > 0.85
    assert inst._compute_kick_regularity() < 0.05


def test_sub_level_defensive_on_a_bare_stub_missing_the_deque() -> None:
    inst = object.__new__(AutoVJController)
    assert inst._compute_sub_level() == 0.0
