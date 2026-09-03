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


def decode_mono_ffmpeg(
    path: str, sample_rate: int, max_seconds: float | None,
) -> tuple[np.ndarray | None, str | None]:
    """Decode any audio file to float32 mono PCM via ffmpeg.

    Returns ``(pcm, None)`` on success or ``(None, reason)`` on failure,
    where ``reason`` names what actually happened (timeout, exit code +
    stderr, or empty stdout) rather than collapsing every failure mode
    into a bare ``None`` -- the 2026-09-03 incident (83/311 tracks
    skipped in one run, 0 in the runs before and after it, cause never
    identified because nothing here captured *why*) is why this returns
    a reason now instead of just a value.
    """
    cmd = ['ffmpeg', '-v', 'error', '-i', path]
    if max_seconds is not None:
        cmd += ['-t', str(max_seconds)]
    cmd += ['-f', 'f32le', '-ac', '1', '-ar', str(sample_rate), '-']
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None, 'timeout_120s'
    if proc.returncode != 0:
        stderr = proc.stderr.decode('utf-8', errors='replace')[:300] if proc.stderr else ''
        return None, f'exit_{proc.returncode}: {stderr}'
    if not proc.stdout:
        return None, 'empty_stdout'
    return np.frombuffer(proc.stdout, dtype=np.float32).copy(), None


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
    skipped: list[dict] = []
    t_start = time.time()

    for i, row in enumerate(rows):
        path = row['track_path']
        ref = reference_bpm(row)
        pcm, decode_reason = decode_mono_ffmpeg(path, rb.SAMPLE_RATE, args.max_seconds)
        if pcm is None or pcm.size < rb.BLOCK or ref is None:
            reason = decode_reason or ('too_short' if pcm is not None else None) or 'no_reference'
            skipped.append({'path': path, 'reason': reason})
            print(f'[{i + 1}/{len(rows)}] SKIP {Path(path).name[:50]} reason={reason}', flush=True)
            continue
        refbpm, rung = ref
        dur = len(pcm) / rb.SAMPLE_RATE

        for name in row_names:
            tracker = rb.build_tracker(name)
            ticks, fed_by = rb.stream_for_row(name, pcm, tracker)
            result = rb.score_track(ticks, refbpm, dur)
            result['list'] = row['list']
            result['reference_rung'] = rung
            result['path'] = path
            result['fed_by'] = fed_by
            all_results[name][path] = result
            print(
                f'[{i + 1}/{len(rows)}] {name:5} {row["list"]:16} {Path(path).name[:38]:38} '
                f'ref {refbpm:6.1f}({rung}) p50 {result["p50"]:7.2f} '
                f'acc1 {result["acc1"]!s:5} acc2 {result["acc2"]!s:5}',
                flush=True,
            )

    for name, results in all_results.items():
        rb.assert_fed_by(name, results)

    decode_failures = [s for s in skipped if s['reason'] != 'no_reference']
    if decode_failures:
        sample = decode_failures[:5]
        raise AssertionError(
            f'{len(decode_failures)}/{len(rows)} tracks failed to decode -- '
            f'refusing to write a partial-coverage table (the 2026-09-03 '
            f'incident this guards against: 83/311 decode failures went '
            f'unnoticed until the aggregate numbers looked wrong). '
            f'Sample reasons: {sample}. '
            f'(no_reference skips, if any, are excluded from this check -- '
            f'those are expected data-coverage gaps, not decode health.)'
        )

    out_path = Path(args.out)
    json.dump({'results': all_results, 'skipped': skipped}, open(out_path, 'w'), indent=1)
    n_scored = len(rows) - len(skipped)
    print(f'\ndone {n_scored}/{len(rows)} tracks ({len(skipped)} skipped) '
          f'in {time.time() - t_start:.0f}s -> {out_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
