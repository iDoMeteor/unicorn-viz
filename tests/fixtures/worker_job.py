"""Jobs for tests/test_workers.py (loaded by path inside worker processes)."""
from __future__ import annotations

import os

LOADS = []
LOADS.append(1)            # re-executed only if the module is loaded again


def whoami() -> tuple[int, int, int]:
    return os.getpid(), os.nice(0), len(LOADS)


def add(a, b):
    return a + b
