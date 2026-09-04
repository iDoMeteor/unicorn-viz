#!/usr/bin/env python3
"""CLI runner for benchmarking madmom's online beat tracker.

Streams an audio source through `adapter.ExternalBeatTracker` in fixed-size
PCM blocks (a plain for-loop, no wall-clock pacing) and writes a JSON report
containing the full `(t, bpm, confidence)` tick series plus the final BPM
estimate.

Two mutually exclusive audio sources are supported:

- `--audio <path>`: load an existing audio file (any path, resolved at
  runtime; nothing is hardcoded or bundled).
- `--synthetic-click --bpm <N> --duration <seconds>`: generate a periodic
  click track in memory with numpy, so this tool is self-testable without
  any external audio file. See `self_test.py` in this directory for an
  automated check of that mode.

Usage
-----
    .venv/bin/python run.py --synthetic-click --bpm 120 --duration 30
    .venv/bin/python run.py --audio /path/to/track.wav --out result.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

from adapter import ExternalBeatTracker

logger = logging.getLogger(__name__)

_DEFAULT_BLOCK_SIZE = 1024
_DEFAULT_SAMPLE_RATE = 44100


def generate_synthetic_click(
    bpm: float,
    duration_s: float,
    sample_rate: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate a mono float32 click track with impulses at the beat interval.

    Each click is a short exponentially-decaying tone burst; light Gaussian
    noise is added across the whole signal so the track isn't perfectly
    silent between clicks.
    """
    interval_s = 60.0 / bpm
    n_samples = int(round(duration_s * sample_rate))
    audio = np.zeros(n_samples, dtype=np.float32)
    click_len = int(sample_rate * 0.02)
    envelope = np.exp(-np.arange(click_len) / (sample_rate * 0.004)).astype(np.float32)
    tone = np.sin(2.0 * np.pi * 1500.0 * np.arange(click_len) / sample_rate).astype(np.float32)
    click = envelope * tone
    for beat_time in np.arange(0.0, duration_s, interval_s):
        start = int(round(beat_time * sample_rate))
        if start >= n_samples:
            break
        end = min(start + click_len, n_samples)
        audio[start:end] += click[: end - start]
    audio += rng.normal(0.0, 0.001, size=n_samples).astype(np.float32)
    return audio


def load_audio_file(path: Path) -> tuple[np.ndarray, int]:
    """Load an audio file as mono float32 samples at its native sample rate.

    Reuses madmom's own `Signal` loader (already a dependency of this tool)
    instead of adding a new audio-decoding library.
    """
    from madmom.audio.signal import Signal

    signal = Signal(str(path), sample_rate=None, num_channels=1, dtype=np.float32)
    return np.asarray(signal, dtype=np.float32), int(signal.sample_rate)


def run(audio: np.ndarray, sample_rate: int, block_size: int) -> dict:
    """Stream `audio` through the adapter in fixed-size blocks and collect ticks."""
    tracker = ExternalBeatTracker()
    tracker.warm_up(sample_rate)
    ticks = []
    for start in range(0, len(audio), block_size):
        block = audio[start:start + block_size]
        block_start_s = start / sample_rate
        tracker.feed(block, block_start_s)
        ticks.append({
            't': block_start_s,
            'bpm': tracker.bpm,
            'confidence': tracker.confidence,
        })
    return {
        'engine': 'madmom',
        'sample_rate': sample_rate,
        'block_size': block_size,
        'num_samples': len(audio),
        'final_bpm': tracker.bpm,
        'ticks': ticks,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    source = parser.add_argument_group('audio source (exactly one required)')
    source.add_argument('--audio', type=Path, help='Path to an audio file to analyze.')
    source.add_argument(
        '--synthetic-click', action='store_true',
        help='Generate an in-memory synthetic click track instead of loading a file.',
    )
    parser.add_argument(
        '--bpm', type=float, default=120.0,
        help='BPM for --synthetic-click (default: 120.0).',
    )
    parser.add_argument(
        '--duration', type=float, default=30.0,
        help='Duration in seconds for --synthetic-click (default: 30.0).',
    )
    parser.add_argument(
        '--sample-rate', type=int, default=_DEFAULT_SAMPLE_RATE,
        help=f'Sample rate for --synthetic-click (default: {_DEFAULT_SAMPLE_RATE}).',
    )
    parser.add_argument(
        '--block-size', type=int, default=_DEFAULT_BLOCK_SIZE,
        help=f'PCM block size fed per feed() call (default: {_DEFAULT_BLOCK_SIZE}).',
    )
    parser.add_argument(
        '--seed', type=int, default=0,
        help='RNG seed for synthetic click noise (default: 0).',
    )
    parser.add_argument(
        '--out', type=Path, default=None,
        help='Output JSON file path (default: stdout).',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse arguments, run the benchmark, and write JSON output."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if bool(args.audio) == bool(args.synthetic_click):
        parser.error('exactly one of --audio or --synthetic-click is required')

    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

    if args.synthetic_click:
        rng = np.random.default_rng(args.seed)
        audio = generate_synthetic_click(args.bpm, args.duration, args.sample_rate, rng)
        sample_rate = args.sample_rate
        logger.info(
            'generated synthetic click track: bpm=%.1f duration=%.1fs sample_rate=%d',
            args.bpm, args.duration, sample_rate,
        )
    else:
        audio, sample_rate = load_audio_file(args.audio)
        logger.info('loaded audio file %s: %d samples at %d Hz', args.audio, len(audio), sample_rate)

    result = run(audio, sample_rate, args.block_size)
    payload = json.dumps(result, indent=2)
    if args.out is not None:
        args.out.write_text(payload)
        logger.info('wrote results to %s', args.out)
    else:
        sys.stdout.write(payload + '\n')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
