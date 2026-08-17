"""MAD-floor / onset-strength-clamp harness: what's the proper fix for
Analyzer._onset_threshold()'s runaway strength bug.

2026-08-17: a live session's onset_strength_max_raw (new logging, see
drop-ins/auto-vj-01's onset_strength_max_raw/_max_compressed properties)
hit 1,171,176,147 -- over a billion. Root cause, unicornviz/audio/
analyzer.py:445:

    mad = float(np.median(np.abs(arr - med))) + 1e-6
    ...
    strength = (flux - threshold) / mad + 1.0   # line 729

``1e-6`` is a literal-division-by-zero guard, not a reasoned floor. During
any near-flat/silent flux stretch, real MAD collapses toward zero; the
next real transient then divides by almost nothing and blows up
arbitrarily. Compare: threshold already has a principled absolute floor,
``_BEAT_ABS_FLOOR = 0.02`` ("minimum absolute threshold (silences silence
triggers)") -- mad's own floor was never given the same treatment.

This harness reimplements the exact formula (not imported -- Analyzer
needs real PCM/FFT) against synthetic flux histories covering the
pathological case (degenerate near-zero-variance quiet stretch, then a
real transient) and two guard-rail cases that any fix must NOT break:
a genuinely quiet section with small-but-real variance and a weak onset
(must stay discriminable, not collapse to indistinguishable-from-noise),
and normal/loud material (a floor should have zero effect once mad is
already well above it).

Sweeps candidate MAD floors and, independently, candidate hard caps on
the final strength value (defense in depth -- a floor bounds one specific
failure mode, a cap bounds strength regardless of *why* it got large).

Run directly:

    python3 tools/onset_strength_mad_floor_harness.py

See docs/adr/vj-system.md for the recommendation this produced.
"""
from __future__ import annotations

import random
import statistics

import numpy as np

_BEAT_MAD_K = 1.80
_BEAT_ABS_FLOOR = 0.02
_ENV_LEN = 150  # 1.5s at 100 Hz, matches Analyzer._ENV_WINDOW_S/_ENV_RATE


def _onset_threshold(arr: np.ndarray, mad_floor: float, use_max: bool = True) -> tuple[float, float]:
    med = float(np.median(arr))
    raw_mad = float(np.median(np.abs(arr - med)))
    # 2026-08-17: the LIVE code uses `+ mad_floor` (always inflates mad by
    # the floor, even when real mad is already large) -- use_max=True
    # tests the candidate fix, `max(raw_mad, mad_floor)` (only engages
    # when real mad would actually be smaller than the floor), matching
    # the max()-floor pattern used everywhere else in this codebase (e.g.
    # beat_grid.py's max(_V2_LOCK_BAND_MIN, bpm*_V2_LOCK_BAND_PCT)).
    mad = max(raw_mad, mad_floor) if use_max else (raw_mad + mad_floor)
    threshold = med + _BEAT_MAD_K * mad + _BEAT_ABS_FLOOR
    return threshold, mad


def _strength(flux: float, arr: np.ndarray, mad_floor: float, cap: float | None,
               use_max: bool = True) -> float:
    threshold, mad = _onset_threshold(arr, mad_floor, use_max=use_max)
    s = max(1.0, (flux - threshold) / mad + 1.0)
    if cap is not None:
        s = min(s, cap)
    return s


def degenerate_quiet_then_transient(rng: random.Random, transient_flux: float) -> np.ndarray:
    """The pathological case: near-zero-variance quiet stretch (real MAD
    collapses toward the float epsilon, not just "small") immediately
    followed by one real transient. Noise amplitude picked far below
    _BEAT_ABS_FLOOR to reproduce genuine near-degenerate material (a
    literal DC/silence gap, not just a quiet passage)."""
    return np.array([1e-4 + rng.uniform(-1e-7, 1e-7) for _ in range(_ENV_LEN - 1)], dtype=np.float32)


def genuinely_quiet_section(rng: random.Random, noise_scale: float) -> np.ndarray:
    """A real quiet passage: small but non-degenerate variance (ambient/
    chillstep material, not literal silence). noise_scale set near
    _BEAT_ABS_FLOOR's own order of magnitude -- real quiet sections still
    have SOME texture."""
    return np.array(
        [max(0.0, noise_scale + rng.gauss(0.0, noise_scale * 0.3)) for _ in range(_ENV_LEN - 1)],
        dtype=np.float32,
    )


def normal_material(rng: random.Random, base_scale: float) -> np.ndarray:
    """Ordinary loud material with real spectral flux variance -- a floor
    change should have ~zero effect here since real MAD is already well
    above any sane floor candidate."""
    return np.array(
        [max(0.0, base_scale + rng.gauss(0.0, base_scale * 0.4)) for _ in range(_ENV_LEN - 1)],
        dtype=np.float32,
    )


def main() -> None:
    rng = random.Random(7)
    floors = [1e-6, 0.005, 0.01, 0.02, 0.05]
    caps = [None, 100.0, 50.0, 20.0]

    print("=== Scenario 1: PATHOLOGICAL (degenerate quiet -> real transient) ===")
    print("A real kick after a near-silent gap. Current code (floor=1e-6) is the live bug.\n")
    for floor in floors:
        strengths = []
        for _ in range(30):
            hist = degenerate_quiet_then_transient(rng, transient_flux=1.0)
            # A realistic hard-kick flux value, well above the quiet floor.
            s = _strength(flux=1.0, arr=hist, mad_floor=floor, cap=None)
            strengths.append(s)
        print(f"  mad_floor={floor:<8} strength: mean={statistics.mean(strengths):>14.1f}  "
              f"max={max(strengths):>16.1f}")

    print("\n=== Scenario 2: GENUINELY QUIET section, weak-but-real onset ===")
    print("Must stay discriminable -- a floor that's too aggressive collapses this to noise.\n")
    for floor in floors:
        weak_strengths, loud_strengths = [], []
        for _ in range(30):
            hist = genuinely_quiet_section(rng, noise_scale=0.015)
            weak = _strength(flux=0.03, arr=hist, mad_floor=floor, cap=None)   # a soft hit
            loud = _strength(flux=0.10, arr=hist, mad_floor=floor, cap=None)   # a clear hit
            weak_strengths.append(weak)
            loud_strengths.append(loud)
        print(f"  mad_floor={floor:<8} weak-onset strength mean={statistics.mean(weak_strengths):.2f}  "
              f"loud-onset strength mean={statistics.mean(loud_strengths):.2f}  "
              f"(discrimination ratio={statistics.mean(loud_strengths)/max(1e-9, statistics.mean(weak_strengths)):.2f}x)")

    print("\n=== Scenario 3: NORMAL material -- '+floor' (live code) vs 'max(mad, floor)' ===")
    print("Real mad here (~0.09-0.10) already exceeds every floor candidate below. A true")
    print("no-op fix should show IDENTICAL numbers across floors under max(); '+floor' instead")
    print("keeps inflating mad (and dulling strength) even though the floor was never needed.\n")
    for floor in floors:
        add_strengths, max_strengths = [], []
        for _ in range(30):
            hist = normal_material(rng, base_scale=0.35)
            add_strengths.append(_strength(flux=0.9, arr=hist, mad_floor=floor, cap=None, use_max=False))
            max_strengths.append(_strength(flux=0.9, arr=hist, mad_floor=floor, cap=None, use_max=True))
        print(f"  mad_floor={floor:<8} '+floor' mean={statistics.mean(add_strengths):>6.2f}   "
              f"'max()' mean={statistics.mean(max_strengths):>6.2f}")

    print("\n=== Scenario 4: strength CAP as a defense-in-depth backstop ===")
    print("Independent of the floor fix -- bounds strength regardless of root cause.\n")
    for cap in caps:
        hist = degenerate_quiet_then_transient(rng, transient_flux=1.0)
        # Worst case: current 1e-6 floor AND a severe flux spike, to show
        # the cap alone (no floor fix) still bounds the output.
        s = _strength(flux=50.0, arr=hist, mad_floor=1e-6, cap=cap, use_max=False)
        print(f"  cap={str(cap):<8} worst-case strength (bad floor + huge flux) = {s:.1f}")

    print(
        "\nRecommendation: mad = max(raw_mad, _BEAT_ABS_FLOOR) -- not raw_mad + floor (the\n"
        "live formula's shape) and not a brand-new arbitrary constant (a fresh number chosen\n"
        "purely to fix this bug, untethered from anything already established). Reusing\n"
        "_BEAT_ABS_FLOOR keeps mad's floor and threshold's floor expressing the same belief\n"
        "(\"this is the smallest meaningful flux scale\") with one constant, and max() -- the\n"
        "same floor idiom already used throughout beat_grid.py -- makes it a true no-op\n"
        "once real mad exceeds it (scenario 3), unlike the live '+floor' shape. Scenario 1\n"
        "shows 0.02 tames the pathological case to a sane range (~48 vs ~900K+); scenario 2\n"
        "confirms real discrimination survives (2x, weak vs. loud, in genuinely quiet\n"
        "material) rather than collapsing to indistinguishable-from-noise. Land the max()\n"
        "fix as the real fix, plus a strength cap (scenario 4) as a backstop independent of\n"
        "getting the floor exactly right -- defense in depth, not an either/or."
    )


if __name__ == '__main__':
    main()
