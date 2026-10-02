#!/usr/bin/env python3
"""Fetch the sources of the patched free-threaded wheels, by pinned commit.

The patched python-rtmidi, glcontext and moderngl wheels were built from branches of
iDoMeteor forks.  Their original build script read local clones on one machine; this
replaces that: for each git package in ``recipe.json`` it fetches exactly the pinned
commit from the fork's URL (nothing else is cloned), checks it is that commit, and
exports the tree.  For python-rtmidi it also checks the commit's RtMidi gitlink is the
pinned sub-module commit and overlays that commit from its own fork (``git archive``
leaves a gitlink empty), then checks the overlay is the patched RtMidi.

    python fetch_patched_sources.py --recipe recipe.json --dest DIR

Writes ``DEST/<dist>-<version>/`` trees, ``DEST/specs.tsv`` (name, version, build tag,
directory: what the container build reads) and ``DEST/sources.json`` (what was fetched).
sphn and OpenCV are not git sources of this recipe (a hash-pinned sdist and a git tag
plus a patch); their scripts handle them.  Standard library plus ``git`` and ``tar``.

Work of the upstream free-threading team (the forks and branches); this file only makes
the recipe executable on any machine.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path


class FetchError(RuntimeError):
    """A pin could not be honoured."""


def _clean_env() -> dict[str, str]:
    """The environment with every ``GIT_*`` variable removed.

    Inside a git hook (pre-commit, pre-push) git exports ``GIT_DIR``, ``GIT_INDEX_FILE``,
    ``GIT_WORK_TREE`` and others.  Inherited, they make ``git init`` / ``git fetch --depth 1``
    in a temporary directory operate on the *calling* repository instead: when the tests ran
    from a commit hook, 17 fake commits were fetched into the shared repository and its
    ``.git/shallow`` file appeared.  Every git call here must target only its own directory.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}


def _git(cwd: Path, *args: str, binary: bool = False) -> str | bytes:
    proc = subprocess.run(['git', *args], cwd=cwd, capture_output=True, check=False, env=_clean_env())
    if proc.returncode != 0:
        raise FetchError(f"git {' '.join(args)}: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout if binary else proc.stdout.decode().strip()


def fetch_commit(url: str, commit: str, dest: Path, label: str) -> None:
    """Export ``commit`` of ``url`` into ``dest`` (created), verifying the hash."""
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise FetchError(f'{label}: {commit!r} is not a full commit hash')
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git(repo, 'init', '-q')
        try:
            _git(repo, 'fetch', '-q', '--depth', '1', url, commit)
        except FetchError:
            try:   # a server that will not serve a bare commit shallowly: take the history
                _git(repo, 'fetch', '-q', url, commit)
            except FetchError as exc:
                raise FetchError(f'{label}: {url} does not have commit {commit[:12]} ({exc})') from exc
        got = _git(repo, 'rev-parse', '--verify', 'FETCH_HEAD^{commit}')
        if got != commit:
            raise FetchError(f'{label}: fetched {got}, pinned {commit}')
        archive = _git(repo, 'archive', '--format=tar', commit, binary=True)
        dest.mkdir(parents=True)
        with tarfile.open(fileobj=BytesIO(archive)) as tf:
            tf.extractall(dest, filter='data')
        # `git archive` leaves a sub-module as an empty directory; the caller overlays it.


def _gitlink(url: str, commit: str, path: str) -> str:
    """The commit the pinned tree records for sub-module ``path``."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git(repo, 'init', '-q')
        _git(repo, 'fetch', '-q', '--depth', '1', url, commit)
        line = _git(repo, 'ls-tree', commit, path)
    parts = str(line).split()
    return parts[2] if len(parts) >= 3 and parts[1] == 'commit' else ''


def fetch_all(recipe: dict, dest: Path) -> list[dict]:
    """Fetch every git package in ``recipe`` into ``dest``; returns what was fetched."""
    dest.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    specs: list[str] = []
    for name, pkg in recipe['packages'].items():
        if 'commit' not in pkg:
            continue
        label = f"{name} {pkg['version']}"
        tree = dest / f"{pkg['dist']}-{pkg['version']}"
        fetch_commit(pkg['fork'], pkg['commit'], tree, label)
        row = {'name': name, 'version': pkg['version'], 'build_tag': pkg['build_tag'],
               'fork': pkg['fork'], 'commit': pkg['commit'], 'dir': tree.name}
        sub = pkg.get('submodule')
        if sub:
            recorded = _gitlink(pkg['fork'], pkg['commit'], sub['path'])
            if recorded != sub['commit']:
                raise FetchError(f"{label}: the commit's gitlink for {sub['path']} is "
                                 f"{recorded or 'missing'}, the recipe pins {sub['commit']}")
            target = tree / sub['path']
            if target.exists():
                for child in target.iterdir():
                    raise FetchError(f'{label}: {target} is not empty before the overlay ({child.name})')
            fetch_commit(sub['fork'], sub['commit'], target.with_name(target.name + '.overlay'),
                         f'{label} sub-module')
            target.with_name(target.name + '.overlay').replace(target)
            marker = sub.get('marker')
            if marker:
                text = (target / marker['file']).read_text(errors='replace') if (target / marker['file']).is_file() else ''
                if marker['contains'] not in text:
                    raise FetchError(f"{label}: the sub-module overlay fails its marker check "
                                     f"({marker['file']} must contain {marker['contains']!r})")
            row['submodule_commit'] = sub['commit']
        rows.append(row)
        specs.append('\t'.join((name, pkg['version'], pkg['build_tag'], tree.name)))
    (dest / 'specs.tsv').write_text('\n'.join(specs) + '\n')
    (dest / 'sources.json').write_text(json.dumps({r['name']: r for r in rows}, indent=2) + '\n')
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--recipe', type=Path, default=Path(__file__).with_name('recipe.json'))
    ap.add_argument('--dest', type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        rows = fetch_all(json.loads(args.recipe.read_text()), args.dest)
    except FetchError as exc:
        print(f'fetch_patched_sources: {exc}', file=sys.stderr)
        return 1
    for r in rows:
        print(f"{r['name']} {r['version']} -{r['build_tag']}: {r['commit'][:12]}"
              + (f" + RtMidi {r['submodule_commit'][:12]}" if 'submodule_commit' in r else ''), file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
