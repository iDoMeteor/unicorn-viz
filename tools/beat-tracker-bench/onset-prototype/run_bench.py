"""Driver + scorer for the onset-prototype bench (auto-vj-v3 roadmap Part 0,
Program B): four `BeatTrackerV3` rows on the same 51-track bench set,
holding everything fixed except which onset/envelope-clock/write-path
combination feeds the tracker.

  Row 1 (stock)     — `beat_grid_stock.py`'s unmodified `BeatTrackerV3`,
                       driven by this project's own production onset
                       detector (`unicornviz/audio/analyzer.py`'s
                       `Analyzer`) exactly as production drives it.
  Row 2 (e5)        — `beat_grid_e5.py`'s E5-patched `BeatTrackerV3` (the
                       true envelope clock), same production onset detector.
  Row 3 (odf)       — the same E5-patched `BeatTrackerV3`, subclassed by
                       `v3_odf_tracker.build_odf_tracker_class()` to bypass
                       the onset-event path and write the envelope ring
                       directly from `complex_onset.ComplexOnsetDetector`'s
                       100 Hz ODF stream instead.
  Row 4 (stock-odf) — a control: the SAME direct-write path as row 3, but
                       fed by this project's own spectral-flux onset value
                       (`stock_flux_odf.StockFluxOnsetSource`) instead of
                       the complex-domain one. Isolates whether row 3's
                       gain over row 1 comes from the onset function or
                       from bypassing the discrete pulse-placement path —
                       see `stock_flux_odf.py`'s module docstring.

No `_V2_*`/`_V3_*` tunable is touched in any row — this measures what the
observation swap alone buys, per the roadmap doc's Program B item 2.
Both direct-write rows (3 and 4) run on the E5-patched tracker class — row
4 exists to separate the onset-function effect from the write-path
effect, not to reintroduce the stock envelope clock as a variable.

Reads (read-only) the same pre-decoded `bench_pcm/*.npy` +
`bench_53_baseline.csv` this bench's other tools already use (owned by the
unicorn-viz-0e session's scratchpad; nothing is written back there).
Reuses `bridge_v2.py`'s `flips_per_min` / `time_to_move` / `smoothed_series`
helpers (dynamically loaded, same convention `batch_311.py` already uses)
rather than reimplementing them; the Acc1/Acc2 fold-classification ladder
is small enough, and specific enough to this comparison's tolerance, to
reimplement directly here instead of importing it from a drop-in.

Run (plain repo Python; no adapter venv needed — only numpy + this
project's own `unicornviz` package):

    python3 tools/beat-tracker-bench/onset-prototype/run_bench.py \\
        [--limit N] [--rows stock,e5,odf,stock-odf]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import statistics as st
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BENCH_ROOT = HERE.parent
REPO_ROOT = BENCH_ROOT.parent.parent

SCRATCH = Path(
    '/tmp/claude-1000/-home-jj-Repos-unicorn-viz'
    '/82717ea2-2206-47c0-8084-12931b40672b/scratchpad'
)
BASELINE_CSV = SCRATCH / 'bench_53_baseline.csv'
MANIFEST_JSON = SCRATCH / 'bench_pcm' / 'manifest.json'

BLOCK = 1024
FPS = 60.0
SAMPLE_RATE = 48000  # this bench's standard rate -- see complex_onset.py's
# module docstring for why 48000 specifically (matches track_replay.py's
# TARGET_SR and the rest of this bench, not a hardcoded assumption baked
# into any of the onset-prototype modules themselves).

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from unicornviz.audio.analyzer import Analyzer  # noqa: E402


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bv2 = _load('_onset_proto_bridge_v2', BENCH_ROOT / 'bridge_v2.py')
bg_stock = _load('_onset_proto_bg_stock', HERE / 'beat_grid_stock.py')
bg_e5 = _load('_onset_proto_bg_e5', HERE / 'beat_grid_e5.py')
complex_onset = _load('_onset_proto_complex_onset', HERE / 'complex_onset.py')
stock_flux_odf = _load('_onset_proto_stock_flux_odf', HERE / 'stock_flux_odf.py')
odf_tracker_mod = _load('_onset_proto_odf_tracker', HERE / 'v3_odf_tracker.py')

ODF_TRACKER_CLS = odf_tracker_mod.build_odf_tracker_class(bg_e5.BeatTrackerV3)

# Same fold table as drop-ins/auto-vj-01/tools/bpm_agreement_report.py's
# _FOLDS -- reimplemented locally (not imported) per this directory's
# isolation rules; it is a fixed, well-known set of metrical ratios, not
# project-specific logic that risks drifting from the source of truth.
_FOLDS: tuple[tuple[float, str], ...] = (
    (1.0, '1:1'),
    (2.0, '2:1'), (0.5, '1:2'),
    (3.0, '3:1'), (1.0 / 3.0, '1:3'),
    (1.5, '3:2'), (2.0 / 3.0, '2:3'),
    (4.0 / 3.0, '4:3'), (0.75, '3:4'),
    (1.25, '5:4'), (0.8, '4:5'),
)


def fold_classify(detected: float, reference: float, tol: float = 0.04) -> tuple[str, bool, bool]:
    """(fold_label_or_'unrelated', acc1, acc2) for one detected/reference pair."""
    if detected <= 0.0 or reference <= 0.0:
        return 'no-data', False, False
    for ratio, label in _FOLDS:
        target = reference * ratio
        if abs(detected - target) / target <= tol:
            return label, label == '1:1', True
    return 'unrelated', False, False


def _kick_regularity_state():
    """Fresh 16-deep kick-band-energy deque + its regularity() reader.

    Mirrors `AutoVJController._compute_kick_regularity()` /
    `drop-ins/training-kit-01/tools/track_replay.py`'s matching helper
    (read there for the pattern only, not imported — this prototype never
    imports from training-kit-01): kick-band energy (perceptual bands
    0:12, ~31-99 Hz) sampled on onset ticks, regularity = 1 - std/mean,
    read one tick stale.
    """
    energies: deque[float] = deque(maxlen=16)

    def regularity() -> float:
        if len(energies) < 4:
            return 0.0
        ke = np.array(energies, dtype=np.float32)
        m = float(ke.mean())
        if m < 1e-6:
            return 0.0
        return float(1.0 - min(1.0, ke.std() / m))

    return energies, regularity


def _feedback_confidence(tracker) -> float:
    """Confidence to report to Analyzer.set_expected_bpm(), zeroed under
    the same live refractory guard track_replay.py uses (auto_vj.py's T4
    guard, candidate_lock_disagreement)."""
    conf = float(tracker.confidence)
    if bool(getattr(tracker, 'candidate_lock_disagreement', False)):
        return 0.0
    return conf


def stream_onset_driven(pcm: np.ndarray, tracker) -> list[tuple[float, float, float]]:
    """Rows 1/2: production-faithful replay via Analyzer's own onset detector.

    Mirrors `track_replay.py`'s `stream_track()` fidelity contract (read
    for the pattern, not imported): `Analyzer.process()` fed `BLOCK`-sample
    blocks stamped with audio time, `tracker.update()` on a separate 60 Hz
    tick clock fed the drained onset queue, BPM feedback into the analyzer
    every tick with the live refractory guard.
    """
    analyzer = Analyzer()
    analyzer.set_sample_rate(SAMPLE_RATE)
    kick_energies, kick_regularity = _kick_regularity_state()

    ticks: list[tuple[float, float, float]] = []
    tick_dt = 1.0 / FPS
    next_tick = tick_dt
    n_blocks = len(pcm) // BLOCK
    for i in range(n_blocks):
        block = pcm[i * BLOCK:(i + 1) * BLOCK]
        t0 = i * BLOCK / SAMPLE_RATE
        audio = analyzer.process(block, t=t0)
        t1 = t0 + BLOCK / SAMPLE_RATE
        while next_tick <= t1:
            onsets = analyzer.drain_onsets()
            kr = kick_regularity()
            tracker.update(tick_dt, audio, onsets=onsets, t=next_tick, kick_regularity=kr)
            if onsets:
                bands = audio.bands
                if isinstance(bands, np.ndarray) and len(bands) >= 12:
                    kick_energies.append(float(bands[0:12].mean()))
            if tracker.bpm > 0:
                analyzer.set_expected_bpm(tracker.bpm, _feedback_confidence(tracker))
            ticks.append((next_tick, float(tracker.bpm), float(tracker.confidence)))
            next_tick += tick_dt
    return ticks


def _stream_direct_write(
    pcm: np.ndarray, tracker, odf_ticks: list[tuple[float, float]],
) -> list[tuple[float, float, float]]:
    """Shared second half of rows 3/4: drive `tracker` from a precomputed
    `(t, odf_z)` stream via the direct-write path.

    Analyzer still runs normally (bands/energy features `update()` needs,
    and its own onset detector for `kick_regularity` sampling only — held
    identical to rows 1/2 so the only thing that changes between rows is
    which stream produced `odf_ticks`). `tracker.update()` is always
    called with ``onsets=None`` so the base class's onset-event path
    never fires; see `v3_odf_tracker.py`'s module docstring for how the
    bypass works.
    """
    analyzer = Analyzer()
    analyzer.set_sample_rate(SAMPLE_RATE)
    kick_energies, kick_regularity = _kick_regularity_state()

    if odf_ticks:
        times = np.fromiter((t for t, _ in odf_ticks), dtype=np.float64, count=len(odf_ticks))
        values = np.fromiter((v for _, v in odf_ticks), dtype=np.float64, count=len(odf_ticks))
    else:
        times = np.zeros(0, dtype=np.float64)
        values = np.zeros(0, dtype=np.float64)
    tracker.set_odf_stream(times, values)

    ticks: list[tuple[float, float, float]] = []
    tick_dt = 1.0 / FPS
    next_tick = tick_dt
    n_blocks = len(pcm) // BLOCK
    for i in range(n_blocks):
        block = pcm[i * BLOCK:(i + 1) * BLOCK]
        t0 = i * BLOCK / SAMPLE_RATE
        audio = analyzer.process(block, t=t0)
        t1 = t0 + BLOCK / SAMPLE_RATE
        while next_tick <= t1:
            onsets = analyzer.drain_onsets()  # kick_regularity timing only; discarded otherwise
            kr = kick_regularity()
            tracker.update(tick_dt, audio, onsets=None, t=next_tick, kick_regularity=kr)
            if onsets:
                bands = audio.bands
                if isinstance(bands, np.ndarray) and len(bands) >= 12:
                    kick_energies.append(float(bands[0:12].mean()))
            if tracker.bpm > 0:
                analyzer.set_expected_bpm(tracker.bpm, _feedback_confidence(tracker))
            ticks.append((next_tick, float(tracker.bpm), float(tracker.confidence)))
            next_tick += tick_dt
    return ticks


def stream_odf_driven(pcm: np.ndarray, tracker) -> list[tuple[float, float, float]]:
    """Row 3: envelope ring written directly from the complex-domain ODF.

    `ComplexOnsetDetector` runs over the whole track to build its
    `(t, odf_z)` stream up front — a driver-loop convenience; the detector
    itself is still strictly causal per its own docstring. See
    `_stream_direct_write()` for the shared driving loop.
    """
    detector = complex_onset.ComplexOnsetDetector()
    detector.warm_up(SAMPLE_RATE)
    odf_ticks: list[tuple[float, float]] = []
    n_blocks = len(pcm) // BLOCK
    for i in range(n_blocks):
        block = pcm[i * BLOCK:(i + 1) * BLOCK]
        odf_ticks.extend(detector.feed(block, i * BLOCK / SAMPLE_RATE))
    return _stream_direct_write(pcm, tracker, odf_ticks)


def stream_stock_odf_driven(pcm: np.ndarray, tracker) -> list[tuple[float, float, float]]:
    """Row 4 (control): envelope ring written directly from this project's
    OWN spectral-flux onset value (not the complex-domain one), through
    the exact same direct-write path row 3 uses. See `stock_flux_odf.py`'s
    module docstring for why this control exists.

    Runs its own throwaway `Analyzer` instance to extract `spectral_flux`
    per block (a second full pass over the PCM, separate from the "real"
    Analyzer `_stream_direct_write()` drives) — mirrors row 3's own two-
    pass shape (one pass to build the ODF stream, one to drive the
    tracker), so both rows have the same structure and only the ODF
    source differs.
    """
    flux_analyzer = Analyzer()
    flux_analyzer.set_sample_rate(SAMPLE_RATE)
    flux_source = stock_flux_odf.StockFluxOnsetSource()
    flux_source.warm_up(SAMPLE_RATE)
    odf_ticks: list[tuple[float, float]] = []
    n_blocks = len(pcm) // BLOCK
    for i in range(n_blocks):
        block = pcm[i * BLOCK:(i + 1) * BLOCK]
        t0 = i * BLOCK / SAMPLE_RATE
        audio = flux_analyzer.process(block, t=t0)
        t1 = t0 + BLOCK / SAMPLE_RATE
        odf_ticks.extend(flux_source.feed_flux(audio.spectral_flux, t0, t1))
    return _stream_direct_write(pcm, tracker, odf_ticks)


def score_track(ticks: list[tuple[float, float, float]], ref_bpm: float, dur: float) -> dict:
    """One track's row: bridge_v2's churn/lock-latency metrics + Acc1/Acc2."""
    bp_all = [(t, b) for t, b, _ in ticks]
    bp = [b for _, b in bp_all if b > 0]
    tail = [b for t, b in bp_all if b > 0 and t >= 0.4 * dur]
    p50 = float(st.median(bp)) if bp else 0.0
    p50_tail = float(st.median(tail)) if tail else 0.0
    fold, acc1, acc2 = fold_classify(p50, ref_bpm)
    fold_tail, acc1_tail, acc2_tail = fold_classify(p50_tail, ref_bpm)
    smoothed = bv2.smoothed_series([(t, b) for t, b, _ in ticks], bv2.SMOOTH_WINDOW_S, FPS)
    nonzero_bp = [(t, b) for t, b, _ in ticks if b > 0]
    return {
        'p50': round(p50, 2),
        'p50_tail': round(p50_tail, 2),
        'reference_bpm': ref_bpm,
        'fold': fold, 'acc1': acc1, 'acc2': acc2,
        'fold_tail': fold_tail, 'acc1_tail': acc1_tail, 'acc2_tail': acc2_tail,
        'bpm_error_pct': round(abs(p50 - ref_bpm) / ref_bpm * 100.0, 2) if ref_bpm > 0 else -1.0,
        'time_to_move_2pct_s': bv2.time_to_move(nonzero_bp, threshold=0.02),
        'flips_per_min_raw': bv2.flips_per_min(bp, dur),
        'flips_per_min_smoothed': bv2.flips_per_min(smoothed, dur),
        'lane_hops_per_min': bv2.flips_per_min(smoothed, dur, threshold=0.20),
        'n_ticks': len(bp),
        'coverage': round(len(bp) / max(1, len(ticks)), 3),
        'duration_s': round(dur, 1),
    }


def build_tracker(row: str):
    if row == 'stock':
        return bg_stock.BeatTrackerV3({})
    if row == 'e5':
        return bg_e5.BeatTrackerV3({})
    if row in ('odf', 'stock-odf'):
        return ODF_TRACKER_CLS({})
    raise ValueError(f'unknown row {row!r}')


def stream_for_row(row: str, pcm: np.ndarray, tracker) -> list[tuple[float, float, float]]:
    if row == 'odf':
        return stream_odf_driven(pcm, tracker)
    if row == 'stock-odf':
        return stream_stock_odf_driven(pcm, tracker)
    return stream_onset_driven(pcm, tracker)


def run_row(row: str, manifest: list[dict], baseline: dict[str, dict], limit: int | None) -> dict:
    rows = manifest if limit is None else manifest[:limit]
    results: dict[str, dict] = {}
    t_start = time.time()
    for m in rows:
        path = m['path']
        base = baseline.get(path)
        if base is None:
            continue
        ref_bpm = float(base['reference_bpm'])
        pcm = np.load(m['npy']).astype(np.float32)
        tracker = build_tracker(row)
        ticks = stream_for_row(row, pcm, tracker)
        dur = len(pcm) / SAMPLE_RATE
        row_result = score_track(ticks, ref_bpm, dur)
        row_result['note'] = base['note']
        row_result['path'] = path
        results[path] = row_result
        print(
            f'{row:10} {Path(path).name[:44]:44} ref {ref_bpm:6.1f} '
            f'p50 {row_result["p50"]:7.2f} acc1 {row_result["acc1"]!s:5} '
            f'acc2 {row_result["acc2"]!s:5} fold {row_result["fold"]:8} '
            f'lanehops/min {row_result["lane_hops_per_min"]:5.1f}',
            flush=True,
        )
    print(f'-- {row}: {len(results)} tracks in {time.time() - t_start:.0f}s', flush=True)
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--rows', default='stock,e5,odf,stock-odf')
    ap.add_argument('--out', default=str(HERE / 'results_51track.json'))
    args = ap.parse_args()

    manifest = json.load(open(MANIFEST_JSON))
    baseline = {r['path']: r for r in csv.DictReader(open(BASELINE_CSV))}

    all_results: dict[str, dict[str, dict]] = {}
    for row in args.rows.split(','):
        row = row.strip()
        all_results[row] = run_row(row, manifest, baseline, args.limit)

    out_path = Path(args.out)
    json.dump(all_results, open(out_path, 'w'), indent=1)
    print(f'done -> {out_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
