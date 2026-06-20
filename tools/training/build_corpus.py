"""Build a local training corpus from audio files.

The corpus builder is intentionally offline. It consumes local audio files and
optional JSONL/JSON manifests, extracts Essentia summary features, and writes a
JSONL corpus that downstream training steps can label and fit against.
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
from typing import Any

from training_lib import (
    DEFAULT_SAMPLE_RATE,
    as_jsonable,
    collect_source_map,
    extract_audio_features,
    utc_now_iso,
    write_jsonl,
)


def _timestamped_path(path: Path) -> Path:
    """Append a UTC timestamp to the output filename before writing."""

    stamp = datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%SZ')
    suffix = path.suffix
    stem = path.name[:-len(suffix)] if suffix else path.name
    return path.with_name(f'{stem}-{stamp}{suffix}')


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'inputs',
        nargs='*',
        help='Audio files or directories to include in the corpus.',
    )
    parser.add_argument(
        '--manifest',
        type=Path,
        help='Optional JSON or JSONL manifest with audio_path/path entries.',
    )
    parser.add_argument(
        '--out',
        type=Path,
        default=Path('assets/training/corpus/latest-corpus.jsonl'),
        help='Output JSONL path for the generated corpus.',
    )
    parser.add_argument(
        '--recursive',
        action='store_true',
        help='Recursively scan input directories for audio files.',
    )
    parser.add_argument(
        '--sample-rate',
        type=int,
        default=DEFAULT_SAMPLE_RATE,
        help='Sample rate used by the Essentia loader.',
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Abort on the first audio analysis failure.',
    )
    return parser.parse_args()


def _build_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    source_map = collect_source_map(args.inputs, args.manifest, args.recursive)
    rows: list[dict[str, Any]] = []
    for audio_path in sorted(source_map):
        metadata = source_map[audio_path]
        try:
            row = extract_audio_features(audio_path, sample_rate=args.sample_rate)
        except Exception as exc:
            if args.strict:
                raise
            row = {
                'analysis_status': 'error',
                'analysis_error': str(exc),
                'audio_path': str(audio_path.resolve()),
                'sample_rate': args.sample_rate,
            }
        row.update(metadata)
        row['analysis_generated_at'] = utc_now_iso()
        rows.append(row)
    return rows


def main() -> int:
    """Entry point for the corpus builder CLI."""

    args = _parse_args()
    rows = _build_rows(args)
    output_path = _timestamped_path(args.out)
    count = write_jsonl(rows, output_path)
    summary = {
        'output': str(output_path),
        'rows': count,
        'source_inputs': list(args.inputs),
        'manifest': str(args.manifest) if args.manifest else None,
    }
    print(json.dumps(as_jsonable(summary), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())