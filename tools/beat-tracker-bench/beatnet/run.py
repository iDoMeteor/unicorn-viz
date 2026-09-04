"""CLI runner for the BeatNet benchmarking adapter.

Streams either a real audio file or an in-memory synthetic click track
through :class:`adapter.ExternalBeatTracker` in fixed-size blocks and
writes a JSON report with the full ``(t, bpm, confidence)`` tick series
plus a final BPM estimate.

This is dev-only tooling; see README.md for install/setup and the
license terms found for BeatNet itself.

Examples
--------
Synthetic self-test (no external audio file needed)::

    .venv/bin/python run.py --synthetic-click --bpm 120 --duration 30 --out out.json

Real audio file::

    .venv/bin/python run.py --audio /path/to/track.wav --out out.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from adapter import ExternalBeatTracker

_DEFAULT_BLOCK_SIZE = 1024
_DEFAULT_SYNTHETIC_SAMPLE_RATE = 44100
_CLICK_DURATION_S = 0.015
_CLICK_FREQUENCY_HZ = 1800.0
_CLICK_NOISE_AMPLITUDE = 0.02


def generate_synthetic_click_track(
    bpm: float,
    duration_s: float,
    sample_rate: int = _DEFAULT_SYNTHETIC_SAMPLE_RATE,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Generate an in-memory periodic click track at ``bpm``.

    Each beat is a short exponentially decaying tone burst at
    ``_CLICK_FREQUENCY_HZ``, placed at every beat interval (``60 / bpm``
    seconds). A small amount of Gaussian noise is mixed in across the
    whole track so the signal is not perfectly silent between clicks.
    Returns mono float32 samples in roughly [-1, 1].
    """
    if rng is None:
        rng = np.random.default_rng()

    num_samples = int(round(duration_s * sample_rate))
    audio = (
        rng.normal(0.0, _CLICK_NOISE_AMPLITUDE, num_samples).astype(np.float32)
        if _CLICK_NOISE_AMPLITUDE > 0
        else np.zeros(num_samples, dtype=np.float32)
    )

    beat_interval_s = 60.0 / bpm
    click_len = int(round(_CLICK_DURATION_S * sample_rate))
    t_click = np.arange(click_len) / sample_rate
    envelope = np.exp(-t_click / (_CLICK_DURATION_S / 4.0))
    click_waveform = (
        np.sin(2.0 * np.pi * _CLICK_FREQUENCY_HZ * t_click) * envelope
    ).astype(np.float32)

    beat_time = 0.0
    while beat_time < duration_s:
        start = int(round(beat_time * sample_rate))
        end = min(start + click_len, num_samples)
        if end > start:
            audio[start:end] += click_waveform[: end - start]
        beat_time += beat_interval_s

    peak = float(np.max(np.abs(audio))) or 1.0
    audio = (audio / peak * 0.9).astype(np.float32)
    return audio


def load_audio_file(path: Path) -> tuple[np.ndarray, int]:
    """Load a real audio file as mono float32 samples at its native rate."""
    import librosa

    audio, sample_rate = librosa.load(str(path), sr=None, mono=True)
    return audio.astype(np.float32), int(sample_rate)


def run_benchmark(
    audio: np.ndarray,
    sample_rate: int,
    block_size: int,
    tracker: ExternalBeatTracker,
) -> dict:
    """Stream ``audio`` through ``tracker`` in fixed-size blocks.

    Returns a JSON-serializable dict with the full tick series, the final
    BPM/confidence, and basic run metadata. No wall-clock pacing is done
    between blocks; this iterates as fast as the adapter can process.
    """
    tracker.warm_up(sample_rate)

    ticks: list[dict[str, float]] = []
    start_wall = time.monotonic()
    num_samples = audio.shape[0]
    for block_start_sample in range(0, num_samples, block_size):
        block = audio[block_start_sample : block_start_sample + block_size]
        block_start_s = block_start_sample / sample_rate
        tracker.feed(block, block_start_s)
        ticks.append(
            {
                "t": block_start_s,
                "bpm": tracker.bpm,
                "confidence": tracker.confidence,
            }
        )
    elapsed_wall_s = time.monotonic() - start_wall

    return {
        "ticks": ticks,
        "final_bpm": tracker.bpm,
        "final_confidence": tracker.confidence,
        "elapsed_wall_s": elapsed_wall_s,
        "num_ticks": len(ticks),
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stream audio through the BeatNet benchmarking adapter and "
            "report a running BPM estimate as JSON."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--audio", type=Path, help="Path to a real audio file to analyze."
    )
    source.add_argument(
        "--synthetic-click",
        action="store_true",
        help="Generate an in-memory synthetic click track instead of using a file.",
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
        "--block-size",
        type=int,
        default=_DEFAULT_BLOCK_SIZE,
        help=f"PCM block size in samples (default: {_DEFAULT_BLOCK_SIZE}).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON path (default: stdout).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional RNG seed for --synthetic-click noise generation.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args, run the benchmark, write the JSON report."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.synthetic_click:
        rng = np.random.default_rng(args.seed)
        audio = generate_synthetic_click_track(
            bpm=args.bpm,
            duration_s=args.duration,
            sample_rate=_DEFAULT_SYNTHETIC_SAMPLE_RATE,
            rng=rng,
        )
        sample_rate = _DEFAULT_SYNTHETIC_SAMPLE_RATE
        source_meta = {
            "type": "synthetic_click",
            "bpm": args.bpm,
            "duration_s": args.duration,
            "sample_rate": sample_rate,
        }
    else:
        audio, sample_rate = load_audio_file(args.audio)
        source_meta = {
            "type": "audio_file",
            "path": str(args.audio),
            "duration_s": audio.shape[0] / sample_rate,
            "sample_rate": sample_rate,
        }

    tracker = ExternalBeatTracker()
    result = run_benchmark(
        audio=audio,
        sample_rate=sample_rate,
        block_size=args.block_size,
        tracker=tracker,
    )
    result["source"] = source_meta
    result["adapter"] = {"name": "BeatNet", "block_size": args.block_size}

    payload = json.dumps(result, indent=2)
    if args.out is not None:
        args.out.write_text(payload)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
