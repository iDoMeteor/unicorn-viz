"""One-off mechanism probe: for a handful of named tracks, compare the
comb-filter score at the reference tempo's bin vs. the tempo lane `stock`
actually locked onto, under both the `stock` and `odf` rows.

Tests the specific hypothesis the coordinator raised: v3's HMM observation
is a cosine match against an ideal beat-train comb profile, and a wrong
tempo-lane decision reflects the comb filter itself favoring the wrong
lag — so if the complex-domain onset function sharpens the true lag's
peak relative to the competing lane's, that should show up directly as a
higher (true-lag-score / wrong-lag-score) ratio under `odf` than under
`stock`, for tracks where `odf` actually corrected the lane.

Reads `tracker._last_acf_observation` after a full run — the tuple
`(acf_bpms, comb_score, cycle)` `beat_grid.py`'s own `_estimate_tempo_acf()`
already stores on every ACF cycle (~7.4 Hz; see that method, ~line 2614 in
`beat_grid_stock.py`/`beat_grid_e5.py`). This is a snapshot of the *last*
cycle of each track's run (steady-state), not a time series — cheap to
read (no new instrumentation, nothing added to either `beat_grid_*.py`
copy), but only tells us the converged picture, not how the decision
evolved. Good enough for a mechanism sanity check; not a full account.

Run (plain repo Python):

    python3 tools/beat-tracker-bench/onset-prototype/acf_peak_ratio.py
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

spec = importlib.util.spec_from_file_location('rb', HERE / 'run_bench.py')
rb = importlib.util.module_from_spec(spec)
sys.modules['rb'] = rb
spec.loader.exec_module(rb)


def nearest_bin(acf_bpms: np.ndarray, target_bpm: float) -> int:
    return int(np.argmin(np.abs(acf_bpms - target_bpm)))


def probe_track(path: str, npy_path: str, ref_bpm: float, stock_wrong_bpm: float) -> dict:
    pcm = np.load(npy_path).astype(np.float32)

    stock_tracker = rb.build_tracker('stock')
    rb.stream_onset_driven(pcm, stock_tracker)
    odf_tracker = rb.build_tracker('odf')
    rb.stream_odf_driven(pcm, odf_tracker)

    out = {'path': path, 'ref_bpm': ref_bpm, 'stock_wrong_bpm': stock_wrong_bpm}
    for name, tracker in (('stock', stock_tracker), ('odf', odf_tracker)):
        obs = getattr(tracker, '_last_acf_observation', None)
        if obs is None:
            out[name] = None
            continue
        acf_bpms, comb, cycle = obs
        acf_bpms = np.asarray(acf_bpms, dtype=np.float64)
        comb = np.asarray(comb, dtype=np.float64)
        true_bin = nearest_bin(acf_bpms, ref_bpm)
        wrong_bin = nearest_bin(acf_bpms, stock_wrong_bpm)
        true_score = float(comb[true_bin])
        wrong_score = float(comb[wrong_bin])
        out[name] = {
            'cycle': int(cycle),
            'true_bin_bpm': round(float(acf_bpms[true_bin]), 2),
            'true_score': round(true_score, 4),
            'wrong_bin_bpm': round(float(acf_bpms[wrong_bin]), 2),
            'wrong_score': round(wrong_score, 4),
            'true_over_wrong_ratio': round(true_score / max(1e-9, wrong_score), 3),
        }
    return out


def main() -> int:
    baseline = {r['path']: r for r in csv.DictReader(open(rb.BASELINE_CSV))}
    manifest = {m['path']: m for m in json.load(open(rb.MANIFEST_JSON))}

    # The 7 dnb tracks whose Acc1 flips False (stock) -> True (odf) in the
    # corrected 51-track run (2026-09-03) -- see results/onset_prototype.md
    # for the full per-track table. `stock_wrong_bpm` is each track's own
    # stock-row p50 (the tempo lane stock actually locked onto).
    targets: list[tuple[str, float]] = [
        ('/home/jj/Music/crates/drum-and-bass/30Hz - Eyes Wide Shut (Original Mix).mp3', 176.24),
        ('/home/jj/Music/crates/drum-and-bass/Hplus - What If (Original Mix).mp3', 138.27),
        ('/home/jj/Music/crates/drum-and-bass/Roderic H - Miss You (Original Mix).mp3', 140.20),
        ('/home/jj/Music/crates/drum-and-bass/Rodney Kamal Jackson - Turista (Original Mix).mp3', 136.37),
        ('/home/jj/Music/crates/drum-and-bass/Route 94 ft Jess Glynne - My Love (Catchfraze Remix).mp3', 118.72),
        ('/home/jj/Music/crates/drum-and-bass/Sn - Witch Turning To Myth (Original Mix).mp3', 149.23),
        ('/home/jj/Music/crates/drum-and-bass/Unsolicited Thoughts - The Day Phil Collins Stopped Caring (Original Mix).mp3', 133.56),
    ]

    results = []
    for path, stock_wrong_bpm in targets:
        base = baseline[path]
        m = manifest[path]
        r = probe_track(path, m['npy'], float(base['reference_bpm']), stock_wrong_bpm)
        results.append(r)
        print(json.dumps(r, indent=1))

    out_path = HERE / 'results_acf_peak_ratio.json'
    json.dump(results, open(out_path, 'w'), indent=1)
    print(f'done -> {out_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
