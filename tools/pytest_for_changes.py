"""Run the tests relevant to the files being committed.

Why this exists
---------------
pre-commit stashes unstaged changes so hooks see only what is being
committed.  ``git stash`` reverts *regular files* but does **not** revert
*submodule working-tree contents*, so in a tree where several sessions work
concurrently the hook ends up running HEAD's copy of a test file against a
newer submodule -- a pairing that exists nowhere on disk.  Tests coupled to
in-flight drop-in code then fail for reasons that have nothing to do with the
commit.

Running only the tests that cover the changed files makes that hybrid almost
never matter: a commit touching effects does not run detector tests at all.
The full suite still runs before anything leaves the machine, via the
pre-push hook (see .pre-commit-config.yaml).

Anything that can plausibly affect the whole app -- core runtime, the audio
pipeline, shared test fixtures, dependencies -- falls back to the full suite.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / 'tests'

# Touching any of these can move behaviour anywhere, so run everything.
BROAD_PREFIXES = (
    'unicornviz/app.py', 'unicornviz/config.py', 'unicornviz/hotkeys.py',
    'unicornviz/overlays.py', 'unicornviz/vj_api.py', 'unicornviz/playlist.py',
    'unicornviz/dropins.py', 'unicornviz/paths.py', 'unicornviz/midi.py',
    'unicornviz/audio/', 'unicornviz/effects/base.py',
    'unicornviz/effects/registry.py',
    'tests/conftest.py', 'requirements.txt', 'pyproject.toml',
    '.pre-commit-config.yaml',
)
# Cheap global guards worth running for any Python change.
ALWAYS = ('test_effects_consolidation.py', 'test_registry_browser_entries.py')


def _tokens(path: str) -> set[str]:
    stem = Path(path).stem.lower()
    return {t for t in stem.replace('-', '_').split('_') if len(t) >= 4}


def _distinctive(available: list[str]) -> set[str]:
    """Tokens rare enough across test filenames to be worth matching on.

    Without this, a generic word carries the match: "audio" in
    audio_bass_machine.py pulls in every test_audio_*.py, including the
    capture/device suites that have nothing to do with an effect.

    The cut is proportional, not a fixed count: a well-covered subsystem can
    legitimately own a handful of test files ("projectm" owns five), so a flat
    threshold would discard exactly the tokens worth matching on.
    """
    counts: dict[str, int] = {}
    for name in available:
        for tok in _tokens(name):
            counts[tok] = counts.get(tok, 0) + 1
    cut = max(6, len(available) // 12)
    return {tok for tok, n in counts.items() if n <= cut}


def select(changed: list[str]) -> list[str] | None:
    """Return test paths to run, or None meaning 'run everything'."""
    rel = [c.replace('\\', '/') for c in changed]
    if any(c.startswith(BROAD_PREFIXES) for c in rel):
        return None

    chosen: set[str] = set()
    for c in rel:
        if c.startswith('tests/') and Path(c).name.startswith('test_'):
            chosen.add(c)                       # a test changed: run it
    if not any(c.endswith('.py') for c in rel):
        return []                               # docs/assets only

    available = sorted(p.name for p in TESTS.glob('test_*.py'))
    useful = _distinctive(available)
    for c in rel:
        if not c.endswith('.py') or c.startswith('tests/'):
            continue
        toks = _tokens(c) & useful
        if not toks:
            continue
        for name in available:
            if toks & _tokens(name):
                chosen.add(f'tests/{name}')
    for name in ALWAYS:
        if (TESTS / name).exists():
            chosen.add(f'tests/{name}')
    return sorted(chosen)


def main(argv: list[str]) -> int:
    changed = argv[1:]
    targets = select(changed)
    if targets is None:
        print('pytest: broad change detected — running the full suite')
        cmd = [sys.executable, '-m', 'pytest', '-q']
    elif not targets:
        print('pytest: no Python changes — skipping')
        return 0
    else:
        print(f'pytest: {len(targets)} targeted file(s) for {len(changed)} changed path(s)')
        for t in targets:
            print(f'  {t}')
        cmd = [sys.executable, '-m', 'pytest', '-q', *targets]
    return subprocess.call(cmd, cwd=REPO)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
