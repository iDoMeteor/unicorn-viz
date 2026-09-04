#!/usr/bin/env python3
"""Self-test: run the CLI against synthetic click tracks and sanity-check BPM lock-on.

No external audio file is required. For each target BPM this generates an
in-memory click track via `run.generate_synthetic_click`, streams it through
`ExternalBeatTracker` via `run.run`, and checks that the final BPM estimate
lands within roughly +/-4% of the true BPM. A result that instead locks onto
a related half/double-time tempo is reported honestly as such rather than
being treated as a hard failure, since octave errors are a known, expected
failure mode of tempo trackers rather than a wiring bug in this adapter.

madmom's RNN was trained on real music, not pure synthetic clicks, so this
is a wiring/sanity check, not a claim about madmom's accuracy on real audio.

Usage
-----
    .venv/bin/python self_test.py
"""

from __future__ import annotations

import sys

import numpy as np

from run import generate_synthetic_click, run

_TOLERANCE = 0.04
_RELATED_RATIOS = (0.5, 2.0, 1.0 / 3.0, 3.0)


def _describe_relation(true_bpm: float, observed_bpm: float) -> str | None:
    """Return a short label if `observed_bpm` matches a half/double/etc. of `true_bpm`."""
    if observed_bpm <= 0.0:
        return None
    for ratio in _RELATED_RATIOS:
        expected = true_bpm * ratio
        if abs(observed_bpm - expected) / expected <= _TOLERANCE:
            return f'{ratio:.3g}x true tempo'
    return None


def check_bpm(true_bpm: float, duration_s: float = 30.0, sample_rate: int = 44100) -> bool:
    """Run one synthetic-click case and print a PASS/FAIL/octave-error line.

    Returns True if the final BPM is within tolerance of `true_bpm` (an
    octave-related lock is printed but does not count as a pass, per the
    task's "report it honestly rather than treating it as a hard failure"
    instruction -- it is not silently accepted as a pass, but it also does
    not raise).
    """
    rng = np.random.default_rng(0)
    audio = generate_synthetic_click(true_bpm, duration_s, sample_rate, rng)
    result = run(audio, sample_rate, block_size=1024)
    final_bpm = result['final_bpm']
    error = abs(final_bpm - true_bpm) / true_bpm if true_bpm else float('inf')

    if error <= _TOLERANCE:
        print(f'PASS  true_bpm={true_bpm:6.1f}  final_bpm={final_bpm:7.2f}  error={error * 100:5.2f}%')
        return True

    relation = _describe_relation(true_bpm, final_bpm)
    if relation is not None:
        print(
            f'OCTAVE true_bpm={true_bpm:6.1f}  final_bpm={final_bpm:7.2f}  '
            f'error={error * 100:5.2f}%  (locked onto {relation})'
        )
    else:
        print(f'FAIL  true_bpm={true_bpm:6.1f}  final_bpm={final_bpm:7.2f}  error={error * 100:5.2f}%')
    return False


def main() -> int:
    """Run the self-test cases and exit non-zero only on an unrelated-tempo failure."""
    cases = (120.0, 90.0)
    results = [check_bpm(bpm) for bpm in cases]
    if all(results):
        print('self-test: all cases within tolerance')
        return 0
    print('self-test: one or more cases missed tolerance (see lines above)')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
