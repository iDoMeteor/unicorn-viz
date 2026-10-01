"""Stress: retiring adopted shared-memory arrays while a thread still reads them.

Regression for the audio-helper segfault (exit -11) seen on 2026-09-26,
2026-09-27 (the owner's sessions, a track load each time, the engine fell back
in-process) and twice on 2026-10-01 in the loaded A/B.  A worker thread was in
numpy's fancy-index copy while another thread unmapped the segment under it.

It runs in a subprocess so that, if the bug returns, the failure is an exit
code of -11 (or a data mismatch) reported by the assertion, not a segfault of
pytest itself.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])

_SCRIPT = r'''
import gc, sys, threading, time
import numpy as np
from unicornviz.remote_objects import _ShmExporter

ex = _ShmExporter()
ex.GRACE_S = 0.0                      # retire and unmap on the very next pass
N = 1_000_000                         # 4 MB float32 per array
arrs = [ex.adopt(np.full(N, float(i), np.float32)) for i in range(8)]
bad: list[str] = []

def reader(arr, expect, stop):
    idx = np.arange(0, arr.size, 997)  # a fancy-index read, as in the crash
    while not stop.is_set():
        got = arr[idx]
        if got[0] != expect or got[-1] != expect:
            bad.append(f"array {expect}: read {got[0]}/{got[-1]}")
            return

for i in range(len(arrs)):
    stop = threading.Event()
    t = threading.Thread(target=reader, args=(arrs[i], float(i), stop))
    t.start()
    arrs[i] = None                    # the reader's thread is now the only owner
    ex.retire_unused(set())           # first pass: not retired before its first publish
    ex.retire_unused(set())           # retired, grace over: old code unmapped it here
    time.sleep(0.05)                  # the reader keeps reading for 50 ms
    stop.set()
    t.join()
gc.collect()
ex.retire_unused(set())               # all readers gone: now they may be unmapped
if bad:
    print("MISMATCH", bad[0]); sys.exit(2)
if ex._retired:
    print("LEAK", len(ex._retired)); sys.exit(3)
print("ok")
'''


def test_retiring_adopted_arrays_under_a_reading_thread_does_not_crash() -> None:
    proc = subprocess.run(
        [sys.executable, '-c', _SCRIPT], capture_output=True, text=True,
        timeout=120, check=False, env={**os.environ, 'PYTHONPATH': _ROOT},
    )
    assert proc.returncode == 0, (
        f'exit {proc.returncode} (-11 = SIGSEGV, 2 = read freed/reused memory, '
        f'3 = segments never released): {proc.stdout.strip()} {proc.stderr[-400:]}')
    assert proc.stdout.strip() == 'ok'
