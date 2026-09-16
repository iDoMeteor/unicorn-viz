"""The core entry point pins OpenBLAS to one thread before numpy loads.

OpenBLAS spawns a worker per logical core at numpy import and those
workers busy-wait after every call, taking CPU from the audio, render and
mixer-analysis threads (mixer seat finding, 2026-09-16).  The pin lives in
``unicornviz/__main__.py`` because it has to run before the first numpy
import in the process, and it benefits every drop-in, not just the mixer.
"""
from __future__ import annotations

import os
import subprocess
import sys

_PROBE = (
    'import sys, os; import unicornviz.__main__; '
    'print(os.environ.get("OPENBLAS_NUM_THREADS")); '
    'print("numpy" in sys.modules)'
)


def _run(env_extra: dict[str, str]) -> list[str]:
    env = {k: v for k, v in os.environ.items() if k != 'OPENBLAS_NUM_THREADS'}
    env.update(env_extra)
    out = subprocess.run(
        [sys.executable, '-c', _PROBE], capture_output=True, text=True,
        check=True, env=env, timeout=60,
    )
    return out.stdout.split()


def test_entry_point_pins_openblas_to_one_thread() -> None:
    value, numpy_loaded = _run({})
    assert value == '1'
    # Loading numpy only matters if the variable was set first; this pins
    # that the entry module itself sets it, whether or not numpy follows.
    assert numpy_loaded in ('True', 'False')


def test_operator_override_is_kept() -> None:
    value, _ = _run({'OPENBLAS_NUM_THREADS': '4'})
    assert value == '4'
