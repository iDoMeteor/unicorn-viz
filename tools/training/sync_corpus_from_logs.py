"""Auto-populate the local training corpus from Auto VJ logs.

This tool scans session logs for Spotify track ids, merges in the useful Spotify
metadata captured by the runtime, resolves each track against a local audio
catalog, and extracts Essentia features from the local audio file when a match
exists.

It is intentionally local-only. Spotify is used here as identity/metadata, not
as the audio-analysis source.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from training_lib import (
    as_jsonable,
    canonicalize_track_id,
    collect_spotify_log_metadata,
    extract_audio_features,
    load_jsonl_rows,
    load_track_catalog,
    resolve_catalog_entry,
    track_catalog_by_identity,
    utc_now_iso,
    write_jsonl,
)

_DEFAULT_LOG_DIR = Path('logs')
_DEFAULT_CORPUS = Path('assets/training/corpus/latest-corpus.jsonl')


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'logs',
        nargs='*',
        help='Auto VJ JSONL logs or directories to scan.',
    )
    parser.add_argument(
        '--latest',
        type=int,
        default=10,
        help='When no logs are provided, scan the latest N autovj logs.',
    )
    parser.add_argument(
        '--catalog',
        type=Path,
        help='Optional local audio catalog keyed by Spotify track id or metadata.',
    )
    parser.add_argument(
        '--corpus',
        type=Path,
        default=_DEFAULT_CORPUS,
        help='Output JSONL corpus to populate.',
    )
    parser.add_argument(
        '--sample-rate',
        type=int,
        default=44_100,
        help='Sample rate used by the Essentia loader.',
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Abort on the first track that cannot be resolved or analyzed.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Report what would change without writing the corpus file.',
    )
    parser.add_argument(
        '--watch',
        action='store_true',
        help='Keep polling for new log entries and sync them until interrupted.',
    )
    parser.add_argument(
        '--poll-interval',
        type=float,
        default=15.0,
        help='Seconds to wait between watch-mode sync passes.',
    )
    return parser.parse_args()


def _pick_logs(args: argparse.Namespace) -> list[Path]:
    if args.logs:
        picked: list[Path] = []
        for item in args.logs:
            path = Path(item)
            if path.is_dir():
                picked.extend(sorted(path.glob('autovj-*.jsonl')))
            else:
                picked.append(path)
        return picked
    if not _DEFAULT_LOG_DIR.exists():
        return []
    return sorted(
        _DEFAULT_LOG_DIR.glob('autovj-*.jsonl'),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[: args.latest]


def _row_key(row: dict[str, Any]) -> tuple[str, str]:
    track_id = canonicalize_track_id(
        row.get('spotify_track_id')
        or row.get('track_id')
        or row.get('raw_track_id')
        or ''
    )
    if track_id:
        return ('track', track_id)
    audio_path = str(row.get('audio_path') or row.get('path') or '').strip()
    if audio_path:
        return ('audio', str(Path(audio_path).expanduser().resolve()))
    return ('row', json.dumps(as_jsonable(row), sort_keys=True))


def _load_corpus_index(corpus_path: Path) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    rows = load_jsonl_rows(corpus_path) if corpus_path.exists() else []
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        index[_row_key(row)] = row
    return rows, index


def _sync_once(args: argparse.Namespace) -> dict[str, Any]:
    logs = _pick_logs(args)
    if not logs:
        return {
            'logs_scanned': [],
            'tracks_seen': 0,
            'tracks_synced': 0,
            'tracks_unresolved': 0,
            'unresolved_track_ids': [],
            'corpus': str(args.corpus),
            'catalog': str(args.catalog) if args.catalog else None,
            'dry_run': args.dry_run,
        }

    log_metadata = collect_spotify_log_metadata(logs)
    if not log_metadata:
        return {
            'logs_scanned': [str(path) for path in logs],
            'tracks_seen': 0,
            'tracks_synced': 0,
            'tracks_unresolved': 0,
            'unresolved_track_ids': [],
            'corpus': str(args.corpus),
            'catalog': str(args.catalog) if args.catalog else None,
            'dry_run': args.dry_run,
        }

    catalog = load_track_catalog(args.catalog) if args.catalog else {}
    catalog_by_identity = track_catalog_by_identity(catalog)
    existing_rows, corpus_index = _load_corpus_index(args.corpus)

    synced = 0
    unresolved: list[str] = []
    for track_id in sorted(log_metadata):
        log_meta = log_metadata[track_id]
        existing_row = corpus_index.get(('track', track_id))
        if existing_row is not None and existing_row.get('analysis_status') == 'ok' and existing_row.get('audio_path'):
            continue
        catalog_entry = resolve_catalog_entry(track_id, log_meta, catalog, catalog_by_identity)
        if catalog_entry is None:
            unresolved.append(track_id)
            if args.strict:
                raise FileNotFoundError(f'no catalog entry for {track_id}')
            continue
        try:
            row = _build_sync_row(track_id, log_meta, catalog_entry, args.sample_rate)
        except Exception:
            if args.strict:
                raise
            unresolved.append(track_id)
            continue
        corpus_index[_row_key(row)] = row
        synced += 1

    if not args.dry_run:
        merged_rows = list(existing_rows)
        seen_keys: set[tuple[str, str]] = set()
        for row in merged_rows:
            seen_keys.add(_row_key(row))
        for key, row in corpus_index.items():
            if key not in seen_keys:
                merged_rows.append(row)
        write_jsonl(merged_rows, args.corpus)

    return {
        'logs_scanned': [str(path) for path in logs],
        'tracks_seen': len(log_metadata),
        'tracks_synced': synced,
        'tracks_unresolved': len(unresolved),
        'unresolved_track_ids': unresolved[:20],
        'corpus': str(args.corpus),
        'catalog': str(args.catalog) if args.catalog else None,
        'dry_run': args.dry_run,
    }


def _resolve_audio_path(entry: dict[str, Any]) -> Path | None:
    audio_path = entry.get('audio_path') or entry.get('path')
    if not audio_path:
        return None
    path = Path(str(audio_path)).expanduser()
    return path if path.exists() else None


def _build_sync_row(
    track_id: str,
    log_meta: dict[str, Any],
    catalog_entry: dict[str, Any] | None,
    sample_rate: int,
) -> dict[str, Any]:
    row: dict[str, Any] = {'spotify_track_id': track_id, 'analysis_source': 'spotify+essentia'}
    row.update(log_meta)
    if catalog_entry:
        row.update(catalog_entry)
    audio_path = _resolve_audio_path(row)
    if audio_path is None:
        raise FileNotFoundError(f'no local audio_path for {track_id}')
    row['audio_path'] = str(audio_path.resolve())
    row.update(extract_audio_features(audio_path, sample_rate=sample_rate))
    row['spotify_track_id'] = track_id
    row['analysis_status'] = 'ok'
    row['analysis_generated_at'] = utc_now_iso()
    return row


def main() -> int:
    """Entry point for the log-driven corpus sync CLI."""

    args = _parse_args()
    if args.watch:
        try:
            while True:
                report = _sync_once(args)
                print(json.dumps(as_jsonable(report), sort_keys=True))
                time.sleep(max(1.0, float(args.poll_interval)))
        except KeyboardInterrupt:
            return 0

    report = _sync_once(args)
    if not report['logs_scanned']:
        print('No Auto VJ logs found.')
        return 1
    print(json.dumps(as_jsonable(report), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())