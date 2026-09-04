"""Batch runner: one adapter over the full 311-track / 19-list reference set.

Reads unicorn-viz-0e's bench_reference_19lists.csv (read-only; owned by that
session's scratchpad) and decodes each track itself — no import from
drop-ins/training-kit-01, self-contained per this tool's isolation rules.
Decoding goes through ffmpeg directly (no soundfile/av dependency needed in
each adapter's venv): resample to 48 kHz mono float32, capped at
``--max-seconds`` per track (default 150 s, matching training-kit-01's own
bpm_eval.py --max-duration convention).

Reference priority per row, matching unicorn-viz-0e's ladder: owner
arbitration > tag > Essentia cache (columns owner_resolution_bpm / tag_bpm /
essentia_bpm in the CSV; first non-empty wins).

Run with the target adapter's own venv, capped per the owner's CPU-budget
instruction:

    taskset -c 0-7 nice -n 10 \\
        tools/beat-tracker-bench/madmom/.venv/bin/python batch_311.py madmom \\
        [--limit N] [--max-seconds 150]

with OMP_NUM_THREADS=OPENBLAS_NUM_THREADS=MKL_NUM_THREADS=8 set in the
environment so numpy/BLAS doesn't oversubscribe the pinned cores.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import statistics as st
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
SCRATCH = Path(
    '/tmp/claude-1000/-home-jj-Repos-unicorn-viz'
    '/82717ea2-2206-47c0-8084-12931b40672b/scratchpad'
)
REFERENCE_CSV = SCRATCH / 'bench_reference_19lists.csv'
BLOCK = 1024
FPS = 60.0
SMOOTH_WINDOW_S = 2.0


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def decode_mono_ffmpeg(path: str, sample_rate: int, max_seconds: float | None) -> np.ndarray | None:
    """Decode any audio file to float32 mono PCM via ffmpeg. None on failure."""
    cmd = ['ffmpeg', '-v', 'error', '-i', path]
    if max_seconds is not None:
        cmd += ['-t', str(max_seconds)]
    cmd += ['-f', 'f32le', '-ac', '1', '-ar', str(sample_rate), '-']
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def reference_bpm(row: dict) -> tuple[float, str] | None:
    for key, rung in (('owner_resolution_bpm', 'owner'), ('tag_bpm', 'tag'), ('essentia_bpm', 'essentia')):
        v = row.get(key, '').strip()
        if v:
            return float(v), rung
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('name')
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--sr', type=int, default=48000)
    ap.add_argument('--max-seconds', type=float, default=150.0)
    args = ap.parse_args()

    bv2 = _load('bridge_v2', ROOT / 'bridge_v2.py')
    tracker_mod = _load(f'{args.name}_adapter', ROOT / args.name / 'adapter.py')
    Tracker = tracker_mod.ExternalBeatTracker

    rows = list(csv.DictReader(open(REFERENCE_CSV)))
    if args.limit:
        rows = rows[: args.limit]

    out_dir = ROOT / 'results'
    out_dir.mkdir(exist_ok=True)

    results: dict[str, dict] = {}
    skipped: list[str] = []
    t_start = time.time()
    for i, row in enumerate(rows):
        path = row['track_path']
        ref = reference_bpm(row)
        pcm = decode_mono_ffmpeg(path, args.sr, args.max_seconds)
        if pcm is None or pcm.size < BLOCK or ref is None:
            skipped.append(path)
            print(f'[{i + 1}/{len(rows)}] SKIP {Path(path).name[:50]} (decode_failed={pcm is None} no_ref={ref is None})', flush=True)
            continue
        refbpm, rung = ref

        tk = Tracker()
        tk.warm_up(args.sr)
        ticks: list[tuple[float, float]] = []
        next_tick = 1.0 / FPS
        n_blocks = len(pcm) // BLOCK
        for b in range(n_blocks):
            block = pcm[b * BLOCK: (b + 1) * BLOCK]
            t0 = b * BLOCK / args.sr
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
        smoothed = bv2.smoothed_series(ticks, SMOOTH_WINDOW_S, FPS)

        row_out = {
            'list': row['list'],
            'reference_bpm': refbpm,
            'reference_rung': rung,
            'v3_p50_seed1': float(row['v3_p50_seed1']) if row.get('v3_p50_seed1') else None,
            'v3_p50_seed2': float(row['v3_p50_seed2']) if row.get('v3_p50_seed2') else None,
            'v2_p50': float(row['v2_p50']) if row.get('v2_p50') else None,
            'p50': round(st.median(bp), 2) if bp else 0.0,
            'p50_tail': round(st.median(tail), 2) if tail else 0.0,
            'first_lock_s': round(first_t, 2) if first_t is not None else None,
            'time_to_move_2pct_s': bv2.time_to_move(bp_all, threshold=0.02),
            'first_lock_bpm': round(first_bpm, 2) if bp_all else None,
            'flips_per_min_raw': bv2.flips_per_min(bp, dur),
            'flips_per_min_smoothed': bv2.flips_per_min(smoothed, dur),
            'lane_hops_per_min': bv2.flips_per_min(smoothed, dur, threshold=0.20),
            'n_ticks': len(bp),
            'coverage': round(len(bp) / max(1, len(ticks)), 3),
            'duration_s': round(dur, 1),
        }
        results[path] = row_out
        print(
            f'[{i + 1}/{len(rows)}] {args.name:8} {row["list"]:14} {Path(path).name[:40]:40} '
            f'ref {refbpm:6.1f}({rung}) p50 {row_out["p50"]:7.2f} '
            f'lanehops/min {row_out["lane_hops_per_min"]:5.1f}',
            flush=True,
        )

    out_path = out_dir / f'batch_311_{args.name}.json'
    json.dump({'results': results, 'skipped': skipped}, open(out_path, 'w'), indent=1)
    print(f'\ndone {len(results)}/{len(rows)} tracks ({len(skipped)} skipped) in {time.time() - t_start:.0f}s -> {out_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
