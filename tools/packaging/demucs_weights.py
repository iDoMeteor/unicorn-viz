"""Stage demucs model weights for an offline bundle.

Demucs resolves a model name by asking the HuggingFace hub first and only
then its torch-hub cache, so a pre-seeded cache is not enough to keep a
bundle offline. Passing ``--repo <dir>`` to demucs makes it read that
directory alone (``<signature>-<checksum>.th`` files plus the ``<bag>.yaml``
that lists the signatures). This script fills such a directory from the
download list the installed demucs package ships (``remote/files.txt``),
verifying each file's sha256 prefix against the checksum in its name.

Usage::

    demucs_weights.py <site-packages/demucs/remote> <cache dir> <dest dir> htdemucs[,htdemucs_ft]

Files are kept in the cache dir across builds; only missing ones download.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT_URL = 'https://dl.fbaipublicfiles.com/demucs/'


def _download_index(remote: Path) -> dict[str, str]:
    """Return signature -> filename from demucs' bundled ``files.txt``."""
    index: dict[str, str] = {}
    for line in (remote / 'files.txt').read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('root:'):
            index['__root__'] = line.split(':', 1)[1].strip()
            continue
        index[line.split('-', 1)[0]] = line
    return index


def _bag_signatures(yaml_file: Path) -> list[str]:
    """Parse ``models: ['sig', ...]`` from a demucs bag yaml without PyYAML."""
    body = yaml_file.read_text().split('[', 1)[1].split(']', 1)[0]
    return [s.strip(" '\"") for s in body.split(',') if s.strip(" '\"")]


def main(argv: list[str]) -> int:
    """Copy bag yamls and verified weight files into the destination."""
    remote, cache, dest = (Path(a) for a in argv[1:4])
    models = [m for m in argv[4].split(',') if m]
    index = _download_index(remote)
    root = index.pop('__root__', '')
    cache.mkdir(parents=True, exist_ok=True)
    dest.mkdir(parents=True, exist_ok=True)
    for bag in models:
        yaml_file = remote / f'{bag}.yaml'
        if not yaml_file.is_file():
            print(f'demucs: no bag file for model {bag!r} in {remote}', file=sys.stderr)
            return 1
        shutil.copy(yaml_file, dest / yaml_file.name)
        for sig in _bag_signatures(yaml_file):
            name = index[sig]
            src = cache / name
            if not src.is_file():
                print(f'  downloading {name}', file=sys.stderr)
                urllib.request.urlretrieve(ROOT_URL + root + name, src)
            digest = hashlib.sha256(src.read_bytes()).hexdigest()
            want = name.rsplit('-', 1)[1].split('.', 1)[0]
            if not digest.startswith(want):
                src.unlink()
                print(f'demucs weight {name}: sha256 {digest[:8]} != {want}', file=sys.stderr)
                return 1
            shutil.copy(src, dest / name)
            print(f'  {bag}: {name} ({src.stat().st_size // 1_000_000} MB, sha256 ok)', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
