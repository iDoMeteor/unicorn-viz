#!/usr/bin/env python3
"""CLI runner for the Essentia beat-tracker benchmarking adapter.

Streams an audio source through :class:`adapter.ExternalBeatTracker`
in fixed-size blocks and writes a JSON report of the (t, bpm, confidence)
tick series plus a final BPM estimate. Dev-only tool; see ``README.md`` in
this directory. Must be run from this directory's isolated venv
(``tools/beat-tracker-bench/essentia/.venv``).

Examples::

    .venv/bin/python run.py --synthetic-click --bpm 120 --duration 30
    .venv/bin/python run.py --audio /path/to/track.wav --out result.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from adapter import ExternalBeatTracker

_SAMPLE_RATE = 44100
_DEFAULT_BLOCK_MS = 100.0


def _make_synthetic_click(bpm: float, duration_s: float, noise: float = 0.01) -> np.ndarray:
    """Generate a periodic click track as mono float32 PCM at 44100 Hz.

    Emits a short impulse at every beat interval (``60 / bpm`` seconds)
    over a low-level noise floor, so the tool is self-testable with no
    external audio file.
    """
    rng = np.random.default_rng(0)
    n_samples = int(round(duration_s * _SAMPLE_RATE))
    audio = (rng.standard_normal(n_samples).astype(np.float32) * noise)
    interval_samples = _SAMPLE_RATE * 60.0 / bpm
    click_len = 6
    t = 0.0
    while t < n_samples:
        idx = int(round(t))
        end = min(idx + click_len, n_samples)
        if idx < n_samples:
            audio[idx:end] += 1.0
        t += interval_samples
    return audio.astype(np.float32)


def _load_audio_file(path: Path) -> np.ndarray:
    """Load ``path`` as mono float32 PCM at 44100 Hz via Essentia's MonoLoader.

    MonoLoader decodes and resamples internally, so the returned array is
    always at 44100 Hz regardless of the source file's native rate/format.
    """
    import essentia.standard as std

    loader = std.MonoLoader(filename=str(path), sampleRate=_SAMPLE_RATE)
    return loader()


def _iter_blocks(audio: np.ndarray, block_size: int):
    """Yield (block_start_s, block) pairs covering ``audio`` in order."""
    n = audio.size
    for start in range(0, n, block_size):
        block = audio[start : start + block_size]
        yield start / _SAMPLE_RATE, block


def _run(audio: np.ndarray, block_ms: float) -> dict:
    """Feed ``audio`` through the adapter block by block and collect the tick series."""
    tracker = ExternalBeatTracker()
    tracker.warm_up(_SAMPLE_RATE)

    block_size = max(1, int(round(block_ms / 1000.0 * _SAMPLE_RATE)))
    ticks = []
    for block_start_s, block in _iter_blocks(audio, block_size):
        tracker.feed(block, block_start_s)
        ticks.append(
            {
                "t": round(block_start_s, 4),
                "bpm": tracker.bpm,
                "confidence": tracker.confidence,
            }
        )

    return {
        "sample_rate": _SAMPLE_RATE,
        "block_ms": block_ms,
        "duration_s": round(audio.size / _SAMPLE_RATE, 4),
        "final_bpm": tracker.bpm,
        "final_confidence": tracker.confidence,
        "ticks": ticks,
    }


def main() -> int:
    """Parse arguments, run the benchmark, and write the JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--audio", type=Path, help="Path to an audio file to analyze.")
    source.add_argument(
        "--synthetic-click",
        action="store_true",
        help="Generate an in-memory synthetic click track instead of loading a file.",
    )
    parser.add_argument(
        "--bpm",
        type=float,
        default=120.0,
        help="Target BPM for --synthetic-click (default: 120).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Duration in seconds for --synthetic-click (default: 30).",
    )
    parser.add_argument(
        "--block-ms",
        type=float,
        default=_DEFAULT_BLOCK_MS,
        help="PCM block size in milliseconds, simulating live-cadence feed (default: 100).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Path to write the JSON report to. Defaults to stdout.",
    )
    args = parser.parse_args()

    if args.synthetic_click:
        audio = _make_synthetic_click(args.bpm, args.duration)
    else:
        if not args.audio.is_file():
            parser.error(f"--audio path does not exist: {args.audio}")
        audio = _load_audio_file(args.audio)

    report = _run(audio, args.block_ms)
    output_text = json.dumps(report, indent=2)

    if args.out is not None:
        args.out.write_text(output_text)
    else:
        print(output_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
