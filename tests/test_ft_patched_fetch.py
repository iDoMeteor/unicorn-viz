"""fetch_patched_sources.py: fetch the patched wheels' sources by pinned commit.

The patched wheels were built from local clones of iDoMeteor forks on one machine.  The
fetch helper replaces that with: clone nothing, fetch exactly the pinned commit from the
fork's URL, verify it is that commit, export it, and overlay the RtMidi sub-module (a
gitlink ``git archive`` leaves empty) from its own pinned commit.  Tested here against
throwaway local repositories, no network.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

FT = Path(__file__).resolve().parents[1] / 'tools' / 'packaging' / 'ft-patched'


@pytest.fixture(scope='module')
def fetch():
    spec = importlib.util.spec_from_file_location('fetch_patched_sources', FT / 'fetch_patched_sources.py')
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _git(repo: Path, *args: str) -> str:
    env = {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
           'GIT_COMMITTER_EMAIL': 't@t', 'HOME': str(repo), 'PATH': '/usr/bin:/bin'}
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


def _repo(path: Path, files: dict[str, str]) -> tuple[Path, str]:
    path.mkdir(parents=True)
    _git(path, 'init', '-q', '-b', 'main')
    _git(path, 'config', 'uploadpack.allowAnySHA1InWant', 'true')
    for name, text in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text)
    _git(path, 'add', '-A')
    _git(path, 'commit', '-q', '-m', 'c')
    return path, _git(path, 'rev-parse', 'HEAD')


def _recipe(tmp_path: Path, *, sub_commit: str | None = None) -> tuple[dict, str, str]:
    sub, sub_sha = _repo(tmp_path / 'rtmidi-fork', {'RtMidi.cpp': 'cpp', 'RtMidi.h': 'class X { callUserCallback(); };'})
    main, _ = _repo(tmp_path / 'py-rtmidi-fork', {'setup.py': 'x', 'src/_rtmidi.pyx': 'pyx', 'src/_rtmidi.cpp': 'stale'})
    _git(main, 'update-index', '--add', '--cacheinfo', f'160000,{sub_commit or sub_sha},src/rtmidi')
    _git(main, 'commit', '-q', '-m', 'add gitlink')
    gl, gl_sha = _repo(tmp_path / 'gl-fork', {'setup.py': 'gl'})
    recipe = {'packages': {
        'python-rtmidi': {'dist': 'python_rtmidi', 'version': '1.5.8', 'build_tag': '3', 'fork': str(main),
                          'commit': _git(main, 'rev-parse', 'HEAD'),
                          'submodule': {'path': 'src/rtmidi', 'fork': str(sub), 'commit': sub_sha,
                                        'marker': {'file': 'RtMidi.h', 'contains': 'callUserCallback'}}},
        'glcontext': {'dist': 'glcontext', 'version': '3.0.0', 'build_tag': '2', 'fork': str(gl), 'commit': gl_sha},
        'sphn': {'dist': 'sphn', 'version': '0.2.1', 'build_tag': '1'},                 # not a git source
    }}
    return recipe, sub_sha, gl_sha


def test_fetches_each_git_package_at_its_pinned_commit_and_writes_the_spec(fetch, tmp_path) -> None:
    recipe, sub_sha, gl_sha = _recipe(tmp_path)
    dest = tmp_path / 'out'
    rows = fetch.fetch_all(recipe, dest)
    assert [r['name'] for r in rows] == ['python-rtmidi', 'glcontext']      # sphn is built from its sdist
    assert (dest / 'glcontext-3.0.0' / 'setup.py').read_text() == 'gl'
    rtm = dest / 'python_rtmidi-1.5.8'
    assert (rtm / 'src' / 'rtmidi' / 'RtMidi.cpp').read_text() == 'cpp'     # sub-module overlaid
    assert (dest / 'specs.tsv').read_text().splitlines() == [
        'python-rtmidi\t1.5.8\t3\tpython_rtmidi-1.5.8', 'glcontext\t3.0.0\t2\tglcontext-3.0.0']
    manifest = json.loads((dest / 'sources.json').read_text())
    assert manifest['glcontext']['commit'] == gl_sha
    assert manifest['python-rtmidi']['submodule_commit'] == sub_sha


def test_refuses_a_fork_that_no_longer_has_the_pinned_commit(fetch, tmp_path) -> None:
    recipe, _, _ = _recipe(tmp_path)
    recipe['packages']['glcontext']['commit'] = '0' * 40
    with pytest.raises(fetch.FetchError, match='glcontext'):
        fetch.fetch_all(recipe, tmp_path / 'out')


def test_refuses_when_the_gitlink_is_not_the_pinned_submodule_commit(fetch, tmp_path) -> None:
    """If the python-rtmidi commit's gitlink recorded some other RtMidi, the wheel would
    carry different C++ than the recipe says; that must be an error, not a silent build."""
    other = '1' * 40
    recipe, _, _ = _recipe(tmp_path, sub_commit=other)
    with pytest.raises(fetch.FetchError, match='gitlink'):
        fetch.fetch_all(recipe, tmp_path / 'out')


def test_refuses_an_overlay_without_the_patched_marker(fetch, tmp_path) -> None:
    recipe, _, _ = _recipe(tmp_path)
    recipe['packages']['python-rtmidi']['submodule']['marker']['contains'] = 'not in this file'
    with pytest.raises(fetch.FetchError, match='marker'):
        fetch.fetch_all(recipe, tmp_path / 'out')


def test_a_stale_pre_generated_cpp_is_not_removed_here(fetch, tmp_path) -> None:
    """Dropping the generated C++ is the container build's job (it knows Cython); the fetch
    must export the commit exactly as pinned."""
    recipe, _, _ = _recipe(tmp_path)
    fetch.fetch_all(recipe, tmp_path / 'out')
    assert (tmp_path / 'out' / 'python_rtmidi-1.5.8' / 'src' / '_rtmidi.cpp').read_text() == 'stale'


def test_the_real_recipe_describes_fetchable_packages(fetch) -> None:
    recipe = json.loads((FT / 'recipe.json').read_text())
    git_pkgs = [n for n, p in recipe['packages'].items() if 'commit' in p]
    assert git_pkgs == ['python-rtmidi', 'glcontext', 'moderngl']
    for name in git_pkgs:
        assert recipe['packages'][name]['fork'].startswith('https://github.com/iDoMeteor/')
    marker = recipe['packages']['python-rtmidi']['submodule']['marker']
    assert marker == {'file': 'RtMidi.h', 'contains': 'callUserCallback'}


def _snapshot(git_dir: Path) -> dict[str, bytes]:
    """Every file under a .git directory with its bytes (config, HEAD, hooks, worktrees, objects, ...)."""
    return {str(p.relative_to(git_dir)): p.read_bytes() for p in sorted(git_dir.rglob('*')) if p.is_file()}


@pytest.mark.parametrize('leaked', [
    ('GIT_DIR',),                                                         # what a real hook exported when this bit
    ('GIT_DIR', 'GIT_INDEX_FILE'),
    ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY'),
], ids=['git_dir', 'git_dir+index', 'all'])
def test_git_environment_leaking_in_from_a_hook_cannot_redirect_the_fetch(fetch, tmp_path, monkeypatch, leaked) -> None:
    """When pytest runs inside a git hook (pre-commit, pre-push) from a linked worktree, git exports
    GIT_DIR=<main>/.git/worktrees/<seat>, GIT_INDEX_FILE and friends.  The helper's `git init` /
    `git fetch --depth 1` in a temp directory inherited them and ran against the REAL repository, and
    left two marks on the shared repo: a `.git/shallow` file full of this suite's fake commits, and
    ``core.bare = true`` in the MAIN repo's config (which broke pulls and submodule updates for every
    seat).  The decoy is therefore a main repository with a linked worktree, and the leaked GIT_DIR is
    the worktree's gitdir (a plain repository does not reproduce the core.bare flip).  Require that
    NOTHING under the main .git changed: not the config (core.bare included), not a single byte."""
    main, _ = _repo(tmp_path / 'decoy', {'keep.txt': 'x'})
    _git(main, 'worktree', 'add', '-q', str(tmp_path / 'decoy-seat'), '-b', 'seat/x')
    common = main / '.git'
    wt_gitdir = common / 'worktrees' / 'decoy-seat'
    assert wt_gitdir.is_dir() and 'bare = false' in (common / 'config').read_text()
    before = _snapshot(common)
    values = {'GIT_DIR': str(wt_gitdir), 'GIT_WORK_TREE': str(tmp_path / 'decoy-seat'),
              'GIT_INDEX_FILE': str(wt_gitdir / 'index'), 'GIT_OBJECT_DIRECTORY': str(common / 'objects')}
    for var in leaked:
        monkeypatch.setenv(var, values[var])
    recipe, _, gl_sha = _recipe(tmp_path)
    fetch.fetch_all(recipe, tmp_path / 'out')
    assert (tmp_path / 'out' / 'glcontext-3.0.0' / 'setup.py').read_text() == 'gl'     # it still worked
    after = _snapshot(common)
    # The config first: this is the mark that broke every seat's pulls (core.bare flipped to true).
    assert 'bare = false' in (common / 'config').read_text(), 'core.bare was changed in the decoy config'
    assert after['config'] == before['config'], 'the decoy repository config was rewritten'
    assert set(after) == set(before), f'files added/removed in the decoy: {set(after) ^ set(before)}'
    changed = sorted(n for n in before if after[n] != before[n])
    assert not changed, f'the decoy repository changed: {changed}'
    assert not (common / 'shallow').exists()
    probe = subprocess.run(['git', '--git-dir', str(common), 'cat-file', '-e', gl_sha],
                           capture_output=True, text=True, env={'PATH': '/usr/bin:/bin'})
    assert probe.returncode != 0, 'the fork commit was fetched into the decoy repository'
