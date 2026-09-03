"""Follow-up driver: row 3 (and row 1, for a same-conditions comparison)
over the full 311-track / 19-list reference set.

Only runs if `run_bench.py`'s 51-track result shows row 3 (odf) beating
row 1 (stock) specifically on the 22 hard-set tracks — see this
directory's own results doc (`../results/onset_prototype.md`) for whether
that gate was met and why this script did or didn't run.

Reads `bench_reference_19lists.csv` (read-only; owned by the
unicorn-viz-0e session's scratchpad, same file `batch_311.py` uses) and
decodes each track itself via ffmpeg — mirrors `batch_311.py`'s decode
approach (read for the pattern, not imported: `batch_311.py` lives beside
this directory, not in a drop-in, but this prototype's own files stay
self-contained per its isolation rules) rather than importing from
`drop-ins/training-kit-01/`.

Run (plain repo Python; no adapter venv needed):

    python3 tools/beat-tracker-bench/onset-prototype/run_bench_311.py \\
        [--limit N] [--max-seconds 150] [--rows stock,odf]
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

sys.path.insert(0, str(HERE))
import run_bench as rb  # noqa: E402 -- sibling module, dynamic-load-by-path convention kept for the beat_grid/complex_onset pieces; plain import is fine for this same-directory helper.

SCRATCH = rb.SCRATCH
REFERENCE_CSV = SCRATCH / 'bench_reference_19lists.csv'


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
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--max-seconds', type=float, default=150.0)
    ap.add_argument('--rows', default='stock,odf')
    ap.add_argument('--out', default=str(HERE / 'results_311track.json'))
    args = ap.parse_args()

    rows = list(csv.DictReader(open(REFERENCE_CSV)))
    if args.limit:
        rows = rows[: args.limit]

    row_names = [r.strip() for r in args.rows.split(',')]
    all_results: dict[str, dict[str, dict]] = {name: {} for name in row_names}
    skipped: list[str] = []
    t_start = time.time()

    for i, row in enumerate(rows):
        path = row['track_path']
        ref = reference_bpm(row)
        pcm = decode_mono_ffmpeg(path, rb.SAMPLE_RATE, args.max_seconds)
        if pcm is None or pcm.size < rb.BLOCK or ref is None:
            skipped.append(path)
            print(f'[{i + 1}/{len(rows)}] SKIP {Path(path).name[:50]} '
                  f'(decode_failed={pcm is None} no_ref={ref is None})', flush=True)
            continue
        refbpm, rung = ref
        dur = len(pcm) / rb.SAMPLE_RATE

        for name in row_names:
            tracker = rb.build_tracker(name)
            if name == 'odf':
                ticks = rb.stream_odf_driven(pcm, tracker)
            else:
                ticks = rb.stream_onset_driven(pcm, tracker)
            result = rb.score_track(ticks, refbpm, dur)
            result['list'] = row['list']
            result['reference_rung'] = rung
            result['path'] = path
            all_results[name][path] = result
            print(
                f'[{i + 1}/{len(rows)}] {name:5} {row["list"]:16} {Path(path).name[:38]:38} '
                f'ref {refbpm:6.1f}({rung}) p50 {result["p50"]:7.2f} '
                f'acc1 {result["acc1"]!s:5} acc2 {result["acc2"]!s:5}',
                flush=True,
            )

    out_path = Path(args.out)
    json.dump({'results': all_results, 'skipped': skipped}, open(out_path, 'w'), indent=1)
    n_scored = len(rows) - len(skipped)
    print(f'\ndone {n_scored}/{len(rows)} tracks ({len(skipped)} skipped) '
          f'in {time.time() - t_start:.0f}s -> {out_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
