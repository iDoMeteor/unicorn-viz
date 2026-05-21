"""Offline BPM evaluation harness.

Streams audio files through the production Analyzer + BeatTracker in a
deterministic offline loop and measures BPM accuracy against ground truth.

Ground truth is read from sidecar ``<stem>.bpm.json`` files placed next to
each audio file.  Schema::

    {
        "bpm": 120.0,
        "downbeat_offset_s": 0.45   # optional
    }

Usage::

    # Run against default seed corpus
    python tools/bpm_eval.py

    # Run against a custom directory
    python tools/bpm_eval.py /path/to/corpus

    # Save report alongside the corpus files
    python tools/bpm_eval.py --report tools/bpm_eval_report.md \\
                             --json   tools/bpm_eval_results.json

The harness writes:
    tools/bpm_eval_report.md    — Markdown summary table
    tools/bpm_eval_results.json — Machine-readable per-file metrics

To capture the baseline before any algorithm changes::

    python tools/bpm_eval.py
    cp tools/bpm_eval_results.json tools/bpm_eval_baseline.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import scipy.io.wavfile as wavfile

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from unicornviz.audio.analyzer import Analyzer  # noqa: E402
from unicornviz.audio.profiles import get_profile  # noqa: E402
from unicornviz.effects.base import AudioData  # noqa: E402

# ---------------------------------------------------------------------------
# Beat tracker loader — tries new BeatTracker(v2) first, falls back to legacy
# ---------------------------------------------------------------------------
_BEAT_GRID_PATH = _REPO / 'drop-ins' / 'auto-vj-01' / 'beat_grid.py'


def _load_tracker_cls(engine: str = 'legacy') -> type:
    """Load BeatGridTracker or BeatTracker from beat_grid.py."""
    spec = importlib.util.spec_from_file_location('_bpm_eval_beat_grid', str(_BEAT_GRID_PATH))
    if spec is None or spec.loader is None:
        raise ImportError(f'Cannot load {_BEAT_GRID_PATH}')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    if engine == 'v2':
        return getattr(mod, 'BeatTracker', mod.BeatGridTracker)
    return mod.BeatGridTracker


# ---------------------------------------------------------------------------
# WAV loading
# ---------------------------------------------------------------------------
_TARGET_SR = 48000


def _load_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    """Load a WAV file as a float32 mono array at its native sample rate."""
    sr, data = wavfile.read(str(path))
    if data.ndim > 1:
        data = data.mean(axis=1)
    if data.dtype == np.int16:
        data = data.astype(np.float32) / 32768.0
    elif data.dtype == np.int32:
        data = data.astype(np.float32) / 2147483648.0
    elif data.dtype != np.float32:
        data = data.astype(np.float32)
    return data, int(sr)


def _resample_if_needed(pcm: np.ndarray, src_sr: int, tgt_sr: int) -> np.ndarray:
    """Simple linear interpolation resample (only used if SR differs from 48k)."""
    if src_sr == tgt_sr:
        return pcm
    ratio = tgt_sr / src_sr
    n_out = int(len(pcm) * ratio)
    x_in = np.linspace(0, len(pcm) - 1, n_out)
    return np.interp(x_in, np.arange(len(pcm)), pcm).astype(np.float32)


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------
_HARMONIC_RATIOS = (1 / 3, 0.5, 2 / 3, 0.75, 1.0, 4 / 3, 1.5, 2.0, 3.0)


def _nearest_harmonic_ratio(pred_bpm: float, truth_bpm: float) -> float:
    """Return the harmonic ratio (pred/truth) that is closest to an integer ratio."""
    if truth_bpm <= 0:
        return 1.0
    ratio = pred_bpm / truth_bpm
    best = min(_HARMONIC_RATIOS, key=lambda r: abs(ratio - r))
    return best


def _is_harmonic_error(pred_bpm: float, truth_bpm: float, tol: float = 0.06) -> bool:
    """True if the prediction is close to truth but scaled by a non-1 harmonic ratio."""
    if truth_bpm <= 0 or pred_bpm <= 0:
        return False
    ratio = pred_bpm / truth_bpm
    nearest = _nearest_harmonic_ratio(pred_bpm, truth_bpm)
    if abs(nearest - 1.0) < 1e-6:
        return False  # 1:1 is not a harmonic error
    return abs(ratio - nearest) / nearest < tol


def _compute_metrics(
    bpm_track: list[tuple[float, float, float]],  # (time_s, bpm, confidence)
    truth: dict,
    lock_tol_pct: float = 0.02,
) -> dict:
    """Compute per-file metrics from a BPM time-series vs ground truth."""
    gt_bpm: float = float(truth.get('bpm', 0.0))
    if gt_bpm <= 0:
        return {'error': 'no ground truth bpm', 'bpm_truth': 0.0}

    # Filter to locked ticks (bpm > 0)
    locked = [(t, b, c) for t, b, c in bpm_track if b > 0]

    # Time-to-lock: first tick where bpm is within tol% of truth
    time_to_lock_s: float = -1.0
    for t, b, _ in locked:
        if abs(b - gt_bpm) / gt_bpm <= lock_tol_pct:
            time_to_lock_s = t
            break

    if not locked:
        return {
            'bpm_truth': gt_bpm,
            'bpm_median': 0.0,
            'bpm_error_abs': gt_bpm,
            'bpm_error_pct': 100.0,
            'harmonic_error_rate': 0.0,
            'time_to_lock_s': -1.0,
            'confidence_at_lock': 0.0,
            'conf_median': 0.0,
            'locked_ticks': 0,
            'lane_fast_pct': 0.0,
        }

    bpms = np.array([b for _, b, _ in locked])
    confs = np.array([c for _, _, c in locked])
    bpm_median = float(np.median(bpms))
    abs_err = float(abs(bpm_median - gt_bpm))
    pct_err = float(abs_err / gt_bpm * 100)

    harmonic_errors = sum(1 for b in bpms if _is_harmonic_error(b, gt_bpm))
    harmonic_err_rate = harmonic_errors / len(bpms)

    conf_at_lock = 0.0
    if time_to_lock_s >= 0:
        for t, b, c in locked:
            if abs(b - gt_bpm) / gt_bpm <= lock_tol_pct:
                conf_at_lock = c
                break

    return {
        'bpm_truth': gt_bpm,
        'bpm_median': round(bpm_median, 2),
        'bpm_error_abs': round(abs_err, 2),
        'bpm_error_pct': round(pct_err, 2),
        'harmonic_error_rate': round(harmonic_err_rate, 4),
        'time_to_lock_s': round(time_to_lock_s, 2),
        'confidence_at_lock': round(conf_at_lock, 4),
        'conf_median': round(float(np.median(confs)), 4),
        'locked_ticks': len(locked),
        'lane_fast_pct': round(float(np.mean(bpms >= 140)) * 100, 1),
    }


# ---------------------------------------------------------------------------
# Per-file evaluation
# ---------------------------------------------------------------------------
BLOCK_SIZE = 1024   # samples per process() call — same order as live audio


def evaluate_file(
    wav_path: Path,
    truth: dict,
    engine: str = 'legacy',
    block_size: int = BLOCK_SIZE,
    profile_name: str = 'house',
) -> dict:
    """Evaluate a single audio file and return metrics dict."""
    pcm, src_sr = _load_wav_mono(wav_path)
    if src_sr != _TARGET_SR:
        pcm = _resample_if_needed(pcm, src_sr, _TARGET_SR)

    profile = get_profile(profile_name)
    analyzer = Analyzer(fft_bands=512, profile=profile)
    TrackerCls = _load_tracker_cls(engine)
    tracker = TrackerCls({})

    dt = block_size / _TARGET_SR
    bpm_track: list[tuple[float, float, float]] = []
    file_t = 0.0

    n_blocks = (len(pcm) - block_size) // block_size

    for i in range(n_blocks):
        start = i * block_size
        block = pcm[start: start + block_size]

        # H9 fix: pass audio-time t so analyzer cooldown runs in audio-time,
        # not wall-clock time (which would be near-zero in offline mode).
        audio = analyzer.process(block, t=file_t)

        # Drain onset events (P1); fall back to None for legacy tracker
        onsets: Any = analyzer.drain_onsets() if hasattr(analyzer, 'drain_onsets') else None

        # Thread audio-time into tracker (H9 fix for BeatGridTracker.update)
        try:
            if onsets is not None:
                tracker.update(dt, audio, onsets=onsets, t=file_t)
            else:
                tracker.update(dt, audio, t=file_t)
        except TypeError:
            # Tracker predates the t= and onsets= parameters
            try:
                tracker.update(dt, audio)
            except Exception:
                pass

        # P3: feed BPM estimate back to analyzer to tune refractory
        if hasattr(analyzer, 'set_expected_bpm') and tracker.bpm > 0:
            analyzer.set_expected_bpm(tracker.bpm, tracker.confidence)

        bpm_track.append((file_t, float(tracker.bpm), float(tracker.confidence)))
        file_t += dt

    return _compute_metrics(bpm_track, truth)


# ---------------------------------------------------------------------------
# Corpus runner
# ---------------------------------------------------------------------------

def run_corpus(
    corpus_dir: Path,
    engine: str = 'legacy',
    profile: str = 'house',
) -> dict[str, dict]:
    """Evaluate all WAV+JSON pairs in corpus_dir. Return {stem: metrics}."""
    results: dict[str, dict] = {}
    wav_files = sorted(corpus_dir.glob('*.wav'))
    if not wav_files:
        print(f'WARNING: no .wav files found in {corpus_dir}', file=sys.stderr)
        return results

    for wav_path in wav_files:
        json_path = wav_path.with_suffix('.bpm.json')
        if not json_path.exists():
            print(f'  SKIP {wav_path.name} (no .bpm.json sidecar)')
            continue
        truth = json.loads(json_path.read_text(encoding='utf-8'))
        t0 = time.perf_counter()
        metrics = evaluate_file(wav_path, truth, engine=engine, profile_name=profile)
        elapsed = time.perf_counter() - t0
        metrics['eval_wall_s'] = round(elapsed, 3)
        metrics['engine'] = engine
        results[wav_path.stem] = metrics
        print(
            f'  {wav_path.name:<28} truth={metrics["bpm_truth"]:>6.1f}  '
            f'pred={metrics["bpm_median"]:>6.1f}  '
            f'err={metrics["bpm_error_abs"]:>5.1f}  '
            f'harmonic={metrics["harmonic_error_rate"]:.2f}  '
            f'lock={metrics["time_to_lock_s"]:>5.1f}s'
        )
    return results


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def _write_markdown(results: dict[str, dict], out_path: Path, engine: str) -> None:
    lines = [
        f'# BPM Evaluation Report — engine: `{engine}`',
        '',
        '| File | Truth | Predicted | AbsErr | ErrPct | HarmonicErrRate | TimeToLock | ConfAtLock | FastLane% |',
        '|------|-------|-----------|--------|--------|-----------------|------------|------------|-----------|',
    ]
    for stem, m in sorted(results.items()):
        lines.append(
            f'| {stem} '
            f'| {m["bpm_truth"]:.1f} '
            f'| {m["bpm_median"]:.1f} '
            f'| {m["bpm_error_abs"]:.2f} '
            f'| {m["bpm_error_pct"]:.1f}% '
            f'| {m["harmonic_error_rate"]:.3f} '
            f'| {m["time_to_lock_s"]:.1f}s '
            f'| {m["confidence_at_lock"]:.3f} '
            f'| {m["lane_fast_pct"]:.0f}% |'
        )

    # Summary row
    errs = [m['bpm_error_abs'] for m in results.values() if 'bpm_error_abs' in m]
    harmonic_rates = [m['harmonic_error_rate'] for m in results.values() if 'harmonic_error_rate' in m]
    lock_times = [m['time_to_lock_s'] for m in results.values() if m.get('time_to_lock_s', -1) >= 0]
    if errs:
        lines += [
            '',
            '## Summary',
            '',
            f'- Files evaluated: {len(results)}',
            f'- Median absolute BPM error: **{np.median(errs):.2f}** BPM',
            f'- Mean absolute BPM error: **{np.mean(errs):.2f}** BPM',
            f'- Mean harmonic error rate: **{np.mean(harmonic_rates):.3f}**',
            f'- Median time-to-lock: **{np.median(lock_times):.1f}s**' if lock_times else '- Time-to-lock: N/A (no track locked)',
        ]

    out_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'\nMarkdown report: {out_path}')


def _write_json(results: dict[str, dict], out_path: Path) -> None:
    out_path.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    print(f'JSON results:   {out_path}')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description='BPM evaluation harness')
    parser.add_argument(
        'corpus_dir',
        nargs='?',
        default=str(_REPO / 'assets' / 'audio' / 'bpm_eval' / 'seed'),
        help='Directory containing .wav + .bpm.json pairs',
    )
    parser.add_argument('--engine', default='legacy', choices=['legacy', 'v2'],
                        help='Beat tracker engine to evaluate')
    parser.add_argument('--profile', default='house',
                        help='Audio profile name (house, trance, chill, etc.)')
    parser.add_argument(
        '--report',
        default=str(Path(__file__).parent / 'bpm_eval_report.md'),
        help='Path for Markdown report output',
    )
    parser.add_argument(
        '--json',
        default=str(Path(__file__).parent / 'bpm_eval_results.json'),
        help='Path for JSON results output',
    )
    args = parser.parse_args(argv)

    corpus_dir = Path(args.corpus_dir)
    if not corpus_dir.exists():
        print(f'ERROR: corpus directory not found: {corpus_dir}', file=sys.stderr)
        print('Run:  python tools/gen_bpm_eval_corpus.py  to generate seed corpus')
        return 1

    print(f'Evaluating corpus: {corpus_dir}  (engine={args.engine})')
    results = run_corpus(corpus_dir, engine=args.engine, profile=args.profile)

    if not results:
        print('No results — check corpus directory.')
        return 1

    _write_markdown(results, Path(args.report), args.engine)
    _write_json(results, Path(args.json))
    return 0


if __name__ == '__main__':
    sys.exit(main())
