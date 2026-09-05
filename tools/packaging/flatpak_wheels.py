#!/usr/bin/env python3
"""Generate a wheels-only Flatpak pip module from a directory of downloaded wheels.

Why not ``flatpak-pip-generator``?  It pins *sdists* for any package with
compiled code (Flathub's build-from-source default), which for this app means
building numpy, scipy and OpenCV inside the sandbox — a toolchain project of its
own.  Flathub accepts manylinux wheels for such stacks.  This tool takes the
wheel set that ``pip download --only-binary=:all:`` resolved **inside the target
SDK** (so the tags match its Python exactly), looks each wheel up on PyPI for its
canonical URL and sha256, verifies the local file against that digest, and
writes one flatpak-builder module that installs them offline.

Usage::

    flatpak run --share=network --filesystem=/var/tmp --command=sh \\
        org.freedesktop.Sdk//25.08 -c 'python3 -m pip download --only-binary=:all: \\
        --dest /var/tmp/wheels -r requirements-flatpak.txt'
    tools/packaging/flatpak_wheels.py --wheel-dir /var/tmp/wheels \\
        --output packaging/flatpak/python3-requirements.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

_WHEEL_RE = re.compile(r'^(?P<name>[^-]+)-(?P<version>[^-]+)-.+\.whl$')
_SDIST_RE = re.compile(r'^(?P<name>.+)-(?P<version>[0-9][^-]*)\.tar\.gz$')


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _pypi_file(name: str, version: str, filename: str) -> dict:
    """Return PyPI's record (url + digests) for one released file."""
    url = f'https://pypi.org/pypi/{name}/{version}/json'
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - fixed https host
        data = json.load(resp)
    for entry in data.get('urls', []):
        if entry.get('filename') == filename:
            return entry
    raise SystemExit(f'{filename}: not found among PyPI files for {name} {version}')


def _verified_source(path: Path, pkg: str, version: str) -> dict:
    record = _pypi_file(pkg, version, path.name)
    expected = record['digests']['sha256']
    actual = _sha256(path)
    if actual != expected:
        raise SystemExit(f'{path.name}: local sha256 {actual} != PyPI {expected}')
    print(f'  {path.name}  {expected[:12]}', file=sys.stderr)
    return {'type': 'file', 'url': record['url'], 'sha256': expected}


def build_module(wheel_dir: Path, name: str) -> dict:
    """Assemble the flatpak-builder module for every wheel and sdist in *wheel_dir*.

    Wheels install first, offline, in one command.  Any sdist (a package with no
    wheel for the SDK's Python — e.g. python-rtmidi on 3.13) installs afterwards
    with ``--no-build-isolation`` so its build backend comes from the wheels that
    were just installed (meson-python, Cython, ...) instead of the network.
    """
    wheels = sorted(p for p in wheel_dir.iterdir() if p.suffix == '.whl')
    sdists = sorted(p for p in wheel_dir.iterdir() if p.name.endswith('.tar.gz'))
    if not wheels:
        raise SystemExit(f'no wheels in {wheel_dir}')
    sources: list[dict] = []
    wheel_pins: list[str] = []
    sdist_pins: list[str] = []
    for wheel in wheels:
        match = _WHEEL_RE.match(wheel.name)
        if not match:
            raise SystemExit(f'unparseable wheel name: {wheel.name}')
        sources.append(_verified_source(wheel, match['name'], match['version']))
        wheel_pins.append(f'{match["name"].replace("_", "-")}=={match["version"]}')
    for sdist in sdists:
        match = _SDIST_RE.match(sdist.name)
        if not match:
            raise SystemExit(f'unparseable sdist name: {sdist.name}')
        sources.append(_verified_source(sdist, match['name'], match['version']))
        sdist_pins.append(f'{match["name"].replace("_", "-")}=={match["version"]}')
    # --ignore-installed: the SDK already carries some of these distributions
    # (meson, ninja, packaging) under read-only /usr; without it pip tries to
    # uninstall them and fails. Everything installs into /app instead.
    common = 'pip3 install --no-index --ignore-installed --find-links="file://${PWD}" --prefix=${FLATPAK_DEST} '
    commands = [common + ' '.join(f'"{pin}"' for pin in wheel_pins)]
    for pin in sdist_pins:
        commands.append(common + f'--no-build-isolation "{pin}"')
    return {
        'name': name,
        'buildsystem': 'simple',
        'build-commands': commands,
        'sources': sources,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--wheel-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--name', default='python3-requirements')
    args = parser.parse_args(argv)
    module = build_module(args.wheel_dir, args.name)
    args.output.write_text(json.dumps(module, indent=2) + '\n', encoding='utf-8')
    print(f'{args.output}: {len(module["sources"])} wheels', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
