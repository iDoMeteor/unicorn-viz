"""The recipe for the PATCHED free-threaded wheels agrees with everything that records them.

The patched wheels (release ``wheelhouse-cp314t-patched-2026-10-02``) were built by the
upstream free-threading team from iDoMeteor forks, two patch files and scripts that lived
only in their working directory.  ``tools/packaging/ft-patched/recipe.json`` is the one place
those pins are written down for this repository, and it is only useful if it cannot drift:
from the patch files on disk, from the release notes that cite them, from the as-built
manifests, from the Windows build script's own pin table, and from the committed trust file
that the installers verify downloads against.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / 'tools' / 'packaging'
FT = PKG / 'ft-patched'
RECIPE = json.loads((FT / 'recipe.json').read_text())
PACKAGES = RECIPE['packages']
NOTES = (FT / 'reference' / f"release-notes-{RECIPE['release']}.md").read_text()
TRUST = (PKG / 'wheelhouse-cp314t.sha256').read_text()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _abbrev(sha: str) -> str:
    """How the release notes cite a sha256: first 8 hex, an ellipsis, last 4."""
    return f'{sha[:8]}…{sha[-4:]}'


def test_patch_files_match_their_recorded_sha256() -> None:
    for name in ('sphn', 'opencv-python-headless'):
        patch = PACKAGES[name]['patch']
        assert _sha(FT / patch['file']) == patch['sha256'], name


def test_the_opencv_patch_hash_is_the_one_the_release_notes_cite() -> None:
    """The coordinator's requirement: the recorded patch sha256 matches the release notes."""
    sha = PACKAGES['opencv-python-headless']['patch']['sha256']
    cited = re.findall(r'opencv-4\.13\.0-free-threading\.patch` \(sha256 `([0-9a-f]{8}…[0-9a-f]{4})`', NOTES)
    assert cited == [_abbrev(sha)], f'release notes cite {cited}, patch file is {_abbrev(sha)}'
    assert _sha(FT / 'patches' / 'opencv-4.13.0-free-threading.patch') == sha


@pytest.mark.parametrize('name', ['python-rtmidi', 'glcontext', 'moderngl'])
def test_fork_commits_are_the_ones_the_release_notes_cite(name: str) -> None:
    pkg = PACKAGES[name]
    assert re.fullmatch(r'[0-9a-f]{40}', pkg['commit'])
    row = next(line for line in NOTES.splitlines() if line.startswith('| ') and pkg['fork'].split('github.com/')[1] in line
               and pkg['branch'] in line)
    assert f"commit `{pkg['commit'][:12]}`" in row, row[:200]
    assert f"`{pkg['branch']}`" in row


def test_the_rtmidi_submodule_commit_is_the_one_the_release_notes_cite() -> None:
    sub = PACKAGES['python-rtmidi']['submodule']
    assert re.fullmatch(r'[0-9a-f]{40}', sub['commit'])
    assert f"commit `{sub['commit'][:12]}`" in NOTES and f"`{sub['branch']}`" in NOTES


def test_sphn_and_opencv_pins_are_the_ones_the_release_notes_cite() -> None:
    sphn = PACKAGES['sphn']
    assert f"commit `{sphn['equivalent_fork_commit']['commit'][:12]}`" in NOTES
    assert re.fullmatch(r'[0-9a-f]{64}', sphn['sdist_sha256'])
    cv = PACKAGES['opencv-python-headless']
    assert f"(commit `{cv['opencv_python']['commit']}`)" in NOTES
    assert f"(commit `{cv['opencv']['commit']}`)" in NOTES
    assert f"tag `{cv['opencv_python']['tag']}`" in NOTES


def test_recipe_matches_the_as_built_manifests() -> None:
    """The manifests are what the build scripts wrote at build time."""
    ref = FT / 'reference'
    built = {w['name']: w for w in json.loads((ref / 'patched-wheels-manifest-2.json').read_text())['wheels']}
    for name in ('python-rtmidi', 'glcontext', 'moderngl', 'sphn'):
        pkg = PACKAGES[name]
        assert (pkg['version'], pkg['build_tag']) == (built[name]['version'], built[name]['build_tag']), name
    for name in ('python-rtmidi', 'glcontext', 'moderngl'):
        assert PACKAGES[name]['commit'] == built[name]['git_commit'], name
    assert PACKAGES['python-rtmidi']['submodule']['commit'] == built['python-rtmidi']['rtmidi_submodule_commit']
    assert PACKAGES['sphn']['equivalent_fork_commit']['commit'] == built['sphn']['git_commit']
    cv = json.loads((ref / 'opencv-wheel-manifest.json').read_text())
    pkg = PACKAGES['opencv-python-headless']
    assert (pkg['version'], pkg['build_tag']) == (cv['version'], cv['build_tag'])
    assert pkg['patch']['sha256'] == cv['patch']['sha256']
    assert pkg['opencv_python']['commit'] == cv['sources']['opencv_python_commit']
    assert pkg['opencv']['commit'] == cv['sources']['opencv_commit']


def test_the_windows_script_builds_from_the_same_pins() -> None:
    """build_windows_patched_wheels.py keeps its own pin table; it must say the same."""
    sys.path.insert(0, str(FT / 'smoke'))
    spec = importlib.util.spec_from_file_location('ft_patched_windows_pins', FT / 'build_windows_patched_wheels.py')
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    for target, name in (('python-rtmidi', 'python-rtmidi'), ('glcontext', 'glcontext'), ('moderngl', 'moderngl'),
                         ('sphn', 'sphn'), ('opencv', 'opencv-python-headless')):
        win, pkg = mod.SPECS[target], PACKAGES[name]
        assert (win.version, win.build_tag) == (pkg['version'], pkg['build_tag']), name
        if 'commit' in pkg:
            assert win.git.commit == pkg['commit'] and win.git.url == pkg['fork'], name
        if 'submodule' in pkg:
            assert win.submodule[1].commit == pkg['submodule']['commit'], name
        if 'patch' in pkg:
            assert [p.sha256 for p in win.patches] == [pkg['patch']['sha256']], name
        if 'sdist_sha256' in pkg:
            assert win.sdist_sha256 == pkg['sdist_sha256'], name
    cv = PACKAGES['opencv-python-headless']
    assert mod.SPECS['opencv'].git.commit == cv['opencv_python']['commit']
    assert mod.SPECS['opencv'].submodule[1].commit == cv['opencv']['commit']


def test_every_patched_wheel_is_in_the_installers_trust_file() -> None:
    """The committed trust file is what installs verify downloads against."""
    for name, pkg in PACKAGES.items():
        stem = f"{pkg['dist']}-{pkg['version']}-{pkg['build_tag']}-cp314-cp314t-"
        for plat in ('manylinux', 'win_amd64'):
            assert re.search(rf'^[0-9a-f]{{64}}  {re.escape(stem)}\S*{plat}\S*\.whl$', TRUST, re.M), (
                f'{stem}*{plat}* is not in wheelhouse-cp314t.sha256')


def test_the_two_smoke_fixture_copies_are_identical() -> None:
    for name in ('h264.mp4', 'vp9.webm', 'SHA256SUMS'):
        assert (PKG / 'ft-fixtures' / name).read_bytes() == (FT / 'smoke' / 'ft-fixtures' / name).read_bytes(), name


def _script(name: str) -> str:
    return (PKG / name).read_text()


@pytest.mark.parametrize('script', ['build_ft_wheels.sh', 'build_ft_sphn_wheel.sh', 'build_ft_opencv_wheel.sh'])
def test_every_linux_script_has_a_patched_mode_driven_by_the_recipe(script: str) -> None:
    text = _script(script)
    assert '--patched)' in text
    assert 'ft-patched/recipe.json' in text
    assert 'ft-patched/smoke/' in text, 'the patched wheels must be verified with the enforcing smoke tests'


def test_the_patched_modes_verify_patch_hashes_before_using_them() -> None:
    for script in ('build_ft_sphn_wheel.sh', 'build_ft_opencv_wheel.sh'):
        text = _script(script)
        assert 'sha256sum -c' in text and 'PATCH_SHA' in text, script
        assert text.index('PATCH_SHA') < text.index('apply'), script


def test_a_patched_opencv_build_never_touches_the_unpatched_source_tree() -> None:
    text = _script('build_ft_opencv_wheel.sh')
    assert 'SRC="$WORK/opencv-python-patched"' in text


def test_patched_wheels_get_their_pep427_build_tags_from_the_recipe() -> None:
    assert 'wheel tags --build "$tag" --remove' in _script('build_ft_wheels.sh')
    assert 'SPHN_BUILD_TAG' in _script('build_ft_sphn_wheel.sh')
    assert 'OPENCV_BUILD_TAG' in _script('build_ft_opencv_wheel.sh')
    for name, pkg in PACKAGES.items():
        assert pkg['build_tag'].isdigit(), name


def test_the_default_patched_image_is_the_recorded_digest_not_a_moving_tag() -> None:
    text = _script('build_ft_wheels.sh')
    assert "['manylinux_image']['digest_round_2']" in text
    assert re.fullmatch(r'quay\.io/pypa/manylinux_2_28_x86_64@sha256:[0-9a-f]{64}',
                        RECIPE['manylinux_image']['digest_round_2'])
