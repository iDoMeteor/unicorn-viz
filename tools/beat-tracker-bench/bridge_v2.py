"""Read-only bridge, v2: adds smoothed churn + lock-genuineness diagnostics
on top of unicorn-viz-0e's bench_bridge.py (same repo, tools/beat-tracker-bench/).

Reads the same pre-decoded bench_pcm/*.npy + manifest.json that
bench_bridge.py reads (owned by the unicorn-viz-0e session's scratchpad;
read-only here, nothing written back into that directory). Writes its own
output under tools/beat-tracker-bench/results/ instead.

What this adds over bench_bridge.py:

* ``flips_per_min_raw``    — the original metric: >4% jumps between
  consecutive nonzero 60 Hz bpm samples. Madmom's DBN re-estimates tempo
  at every registered beat, so this can measure per-beat re-estimate
  jitter as much as real lane changes.
* ``flips_per_min_smoothed`` — >4% jumps on a 2 s rolling median of the
  same nonzero bpm stream (120-sample window at 60 Hz). If jitter
  collapses under smoothing, the raw number was noise; if it doesn't,
  it's genuine lane hopping.
* ``lane_hops_per_min`` — >20% jumps on that same smoothed stream
  (octave/triplet-class moves), separate from the 4% jitter count above
  — splits "chattering around the right tempo" from "changing its mind
  about the lane", which is the live-usability question.
* ``first_lock_bpm``, ``bpm_at_2s``, ``bpm_at_5s`` — the bpm value at
  first nonzero tick and at two fixed horizons after it, so a reader can
  judge whether the first estimate was already close to the eventual
  p50 (fast genuine convergence) or wildly different (early instability)
  without this script asserting a verdict itself.

Run with the adapter's own venv, same convention as bench_bridge.py:
  tools/beat-tracker-bench/madmom/.venv/bin/python bridge_v2.py madmom \
      [--limit N] [--sr 48000] [--max-seconds 45]

v2/v3's own smoothed-churn numbers are NOT computed here — that needs
unicorn-viz-0e's own tracker's raw tick stream, which this script has no
access to.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import statistics as st
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
SCRATCH = Path(
    '/tmp/claude-1000/-home-jj-Repos-unicorn-viz'
    '/82717ea2-2206-47c0-8084-12931b40672b/scratchpad'
)
BLOCK = 1024
FPS = 60.0
SMOOTH_WINDOW_S = 2.0


def resample(pcm: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return pcm
    n = int(round(len(pcm) * dst / src))
    x_old = np.linspace(0.0, 1.0, len(pcm), endpoint=False)
    x_new = np.linspace(0.0, 1.0, n, endpoint=False)
    return np.interp(x_new, x_old, pcm).astype(np.float32)


def flips_per_min(bpms: list[float], duration_s: float, threshold: float = 0.04) -> float:
    n = sum(1 for a, b in zip(bpms, bpms[1:]) if a > 0 and abs(b - a) / a > threshold)
    return round(n / (duration_s / 60.0), 2) if duration_s > 0 else 0.0


def time_to_move(bp_all: list[tuple[float, float]], threshold: float = 0.02) -> float | None:
    """Seconds from the first nonzero estimate until it first moves more than
    ``threshold`` fraction away from that initial value.

    Distinguishes a genuine fast lock from a tracker that reports a
    built-in prior (e.g. BTrack's 120.0 before any real evidence) or a
    default that never really engages: a track where the initial estimate
    never moves returns ``None`` (the estimate was either correct and
    stable from the start, or stuck -- ``first_lock_bpm`` vs ``p50``
    tells you which).
    """
    if not bp_all:
        return None
    first_t, first_bpm = bp_all[0]
    if first_bpm <= 0:
        return None
    for t, b in bp_all[1:]:
        if abs(b - first_bpm) / first_bpm > threshold:
            return round(t - first_t, 2)
    return None


def smoothed_series(ticks: list[tuple[float, float]], window_s: float, fps: float) -> list[float]:
    """Rolling median over nonzero bpm ticks only (window in samples at ``fps``)."""
    window = max(1, int(round(window_s * fps)))
    buf: deque[float] = deque(maxlen=window)
    out = []
    for _, bpm in ticks:
        if bpm <= 0:
            continue
        buf.append(bpm)
        out.append(st.median(buf))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('name')
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--sr', type=int, default=48000)
    ap.add_argument('--max-seconds', type=float, default=None)
    args = ap.parse_args()

    spec = importlib.util.spec_from_file_location(f'bench_{args.name}', ROOT / args.name / 'adapter.py')
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    Tracker = mod.ExternalBeatTracker

    manifest = json.load(open(SCRATCH / 'bench_pcm' / 'manifest.json'))
    if args.limit:
        manifest = manifest[: args.limit]

    out_dir = ROOT / 'results'
    out_dir.mkdir(exist_ok=True)

    results: dict[str, dict] = {}
    t_start = time.time()
    for m in manifest:
        pcm = np.load(m['npy'])
        if args.max_seconds is not None:
            pcm = pcm[: int(args.max_seconds * 48000)]
        pcm = resample(pcm, 48000, args.sr)

        tk = Tracker()
        tk.warm_up(args.sr)
        ticks: list[tuple[float, float]] = []
        next_tick = 1.0 / FPS
        n_blocks = len(pcm) // BLOCK
        for i in range(n_blocks):
            block = pcm[i * BLOCK: (i + 1) * BLOCK]
            t0 = i * BLOCK / args.sr
            tk.feed(block, t0)
            t1 = t0 + BLOCK / args.sr
            while next_tick <= t1:
                ticks.append((next_tick, float(tk.bpm or 0.0)))
                next_tick += 1.0 / FPS

        dur = len(pcm) / args.sr
        bp_all = [(t, b) for t, b in ticks if b > 0]
        bp = [b for _, b in bp_all]
        tail = [b for t, b in bp_all if t >= 0.4 * dur]
        first_t, first_bpm = (bp_all[0] if bp_all else (None, 0.0))
        bpm_at = {}
        for horizon in (2.0, 5.0):
            target = (first_t or 0.0) + horizon
            candidates = [b for t, b in bp_all if t >= target]
            bpm_at[horizon] = candidates[0] if candidates else None

        smoothed = smoothed_series(ticks, SMOOTH_WINDOW_S, FPS)

        row = {
            'p50': round(st.median(bp), 2) if bp else 0.0,
            'p50_tail': round(st.median(tail), 2) if tail else 0.0,
            'first_lock_s': round(first_t, 2) if first_t is not None else None,
            'first_lock_bpm': round(first_bpm, 2) if bp_all else None,
            'time_to_move_2pct_s': time_to_move(bp_all, threshold=0.02),
            'bpm_at_2s': round(bpm_at[2.0], 2) if bpm_at[2.0] is not None else None,
            'bpm_at_5s': round(bpm_at[5.0], 2) if bpm_at[5.0] is not None else None,
            'flips_per_min_raw': flips_per_min(bp, dur),
            'flips_per_min_smoothed': flips_per_min(smoothed, dur),
            'lane_hops_per_min': flips_per_min(smoothed, dur, threshold=0.20),
            'n_ticks': len(bp),
            'coverage': round(len(bp) / max(1, len(ticks)), 3),
            'duration_s': round(dur, 1),
        }
        results[m['path']] = row
        print(
            f'{args.name:8} {Path(m["path"]).name[:40]:40} '
            f'p50 {row["p50"]:7.2f} tail {row["p50_tail"]:7.2f} '
            f'first {row["first_lock_s"]} @{row["first_lock_bpm"]} move2% {row["time_to_move_2pct_s"]} '
            f'raw/min {row["flips_per_min_raw"]:6.1f} smoothed/min {row["flips_per_min_smoothed"]:6.1f} '
            f'lanehops/min {row["lane_hops_per_min"]:6.1f}',
            flush=True,
        )

    out_path = out_dir / f'bench_v2_results_{args.name}.json'
    json.dump(results, open(out_path, 'w'), indent=1)
    print(f'done {len(results)} tracks in {time.time() - t_start:.0f}s -> {out_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
