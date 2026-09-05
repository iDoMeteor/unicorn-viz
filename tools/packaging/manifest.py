#!/usr/bin/env python3
"""Write and merge the Unicorn Viz release ``manifest.json``.

The manifest is the single source of truth for "what is the latest version and
where do its artifacts live" (installer plan §0.1 / §18.4).  ``install.sh``
reads ``channels.<channel>.version`` and ``releases.<version>.artifacts.source``
from it; the website and a future in-app updater read the rest.

It is written by ``tools/packaging/release.sh`` on the build host and merged
rather than overwritten: older releases stay listed, and a release's artifact
list composes across runs (source tarball now, native packages later).

Usage::

    manifest.py update --manifest dist/manifest.json --version 1.0.0-beta.110 \
        --channel prerelease --tag v1.0.0-beta.110 --commit 8155342 \
        --base-url https://get.unicornviz.io \
        --artifact source=dist/1.0.0-beta.110/unicorn-viz-1.0.0-beta.110.tar.gz \
        --artifact rpm-x86_64=dist/1.0.0-beta.110/unicorn-viz-1.0.0~beta.110-1.x86_64.rpm \
        --sumsfile dist/1.0.0-beta.110/SHA256SUMS

    manifest.py show --manifest dist/manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
CHANNELS = ('stable', 'prerelease')


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of *path*."""
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict:
    """Load an existing manifest, or return an empty schema-1 skeleton."""
    if path.is_file():
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('schema') != SCHEMA_VERSION:
            raise SystemExit(f'{path}: unsupported manifest schema {data.get("schema")!r}')
        return data
    return {'schema': SCHEMA_VERSION, 'name': 'unicorn-viz', 'channels': {}, 'releases': {}}


def _url(base_url: str, version: str, name: str) -> str:
    """Absolute URL under *base_url*, or a manifest-relative one when it is empty."""
    return f'{base_url}/{version}/{name}' if base_url else f'{version}/{name}'


def _artifact_entry(base_url: str, version: str, path: Path) -> dict:
    return {
        'url': _url(base_url, version, path.name),
        'sha256': _sha256(path),
        'size': path.stat().st_size,
    }


def cmd_update(args: argparse.Namespace) -> int:
    """Merge one release into the manifest and point *channel* at it."""
    manifest_path = Path(args.manifest)
    data = _load(manifest_path)
    base_url = args.base_url.rstrip('/')
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    artifacts: dict[str, dict] = {}
    for spec in args.artifact:
        key, _, file_str = spec.partition('=')
        file_path = Path(file_str)
        if not key or not file_path.is_file():
            raise SystemExit(f'--artifact expects key=existing-file, got {spec!r}')
        artifacts[key] = _artifact_entry(base_url, args.version, file_path)

    signatures: dict[str, str | None] = {'sha256sums': None, 'sha256sums_asc': None}
    if args.sumsfile:
        signatures['sha256sums'] = _url(base_url, args.version, Path(args.sumsfile).name)
    if args.sumsfile_asc:
        signatures['sha256sums_asc'] = _url(base_url, args.version, Path(args.sumsfile_asc).name)

    # Merge into an existing entry so incremental runs compose: building the
    # source tarball now and the native packages later yields one release that
    # lists all of them. New artifact keys override, others are kept; the
    # original publish time survives; signatures update only when provided.
    existing = data['releases'].get(args.version, {})
    merged_artifacts = dict(existing.get('artifacts', {}))
    merged_artifacts.update(artifacts)
    merged_signatures = dict(existing.get('signatures', {'sha256sums': None, 'sha256sums_asc': None}))
    merged_signatures.update({k: v for k, v in signatures.items() if v is not None})
    data['releases'][args.version] = {
        'tag': args.tag,
        'commit': args.commit,
        'published': existing.get('published', now),
        'updated': now,
        'notes_url': args.notes_url if args.notes_url is not None else existing.get('notes_url'),
        'artifacts': merged_artifacts,
        'signatures': merged_signatures,
    }
    data['channels'][args.channel] = {'version': args.version}
    data['generated'] = now

    tmp = manifest_path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, indent=2, sort_keys=False) + '\n', encoding='utf-8')
    tmp.replace(manifest_path)
    print(manifest_path)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """Print a short human summary of the manifest."""
    data = _load(Path(args.manifest))
    for channel, info in sorted(data.get('channels', {}).items()):
        print(f'{channel:11s} -> {info.get("version")}')
    for version, rel in data.get('releases', {}).items():
        names = ', '.join(sorted(rel.get('artifacts', {})))
        print(f'{version}  ({rel.get("tag")} @ {rel.get("commit")}, {rel.get("published")}): {names}')
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='manifest.py', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)

    upd = sub.add_parser('update', help='merge one release into the manifest')
    upd.add_argument('--manifest', required=True)
    upd.add_argument('--version', required=True)
    upd.add_argument('--channel', required=True, choices=CHANNELS)
    upd.add_argument('--tag', required=True)
    upd.add_argument('--commit', required=True)
    upd.add_argument('--base-url', default='', help='public URL the manifest dir is served at; empty = manifest-relative URLs (hand-off bundles)')
    upd.add_argument('--artifact', action='append', default=[], metavar='KEY=FILE')
    upd.add_argument('--sumsfile', default=None)
    upd.add_argument('--sumsfile-asc', default=None)
    upd.add_argument('--notes-url', default=None)
    upd.set_defaults(func=cmd_update)

    show = sub.add_parser('show', help='summarize a manifest')
    show.add_argument('--manifest', required=True)
    show.set_defaults(func=cmd_show)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
