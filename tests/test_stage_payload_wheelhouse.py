"""Regression tests for the wheelhouse staging in ``tools/packaging/stage_payload.sh``."""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'packaging' / 'stage_payload.sh'

_LIN = 'a-1.0-cp314-cp314t-manylinux_2_28_x86_64.whl'
_WIN = 'a-1.0-cp314-cp314t-win_amd64.whl'


def _source(tmp_path: Path) -> Path:
    src = tmp_path / 'src'
    (src / 'unicornviz').mkdir(parents=True)
    (src / 'assets').mkdir()
    for f in ('config.full.example.toml', 'requirements.txt', 'pyproject.toml', 'README.md'):
        (src / f).write_text('x\n')
    return src


def _wheelhouse(tmp_path: Path, names: list[str], bad: str | None = None) -> Path:
    wh = tmp_path / 'wh'
    wh.mkdir()
    sums = []
    for n in names:
        data = n.encode()
        (wh / n).write_bytes(data)
        sums.append(f'{hashlib.sha256(b"tampered" if n == bad else data).hexdigest()}  {n}')
    (wh / 'SHA256SUMS').write_text('\n'.join(sums) + '\n')
    return wh


def _stage(tmp_path: Path, wh: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['bash', str(_SCRIPT), '--source-dir', str(_source(tmp_path)), '--dest', str(tmp_path / 'out'),
         '--wheelhouse', str(wh), *extra],
        capture_output=True, text=True, timeout=60, check=False,
        # Under a git hook GIT_DIR/GIT_INDEX_FILE point at the real repo, which
        # would make the fake source tree look like a checkout of it.
        env={k: v for k, v in os.environ.items() if not k.startswith('GIT_')},
    )


def _staged(tmp_path: Path) -> set[str]:
    return {p.name for p in (tmp_path / 'out' / 'wheelhouse').glob('*.whl')}


def test_default_stages_only_linux_wheels(tmp_path: Path) -> None:
    proc = _stage(tmp_path, _wheelhouse(tmp_path, [_LIN, _WIN]))
    assert proc.returncode == 0, proc.stderr
    assert _staged(tmp_path) == {_LIN}
    assert (tmp_path / 'out' / 'wheelhouse' / 'SHA256SUMS').read_text().count('.whl') == 1


def test_windows_platform_stages_only_windows_wheels(tmp_path: Path) -> None:
    proc = _stage(tmp_path, _wheelhouse(tmp_path, [_LIN, _WIN]), '--wheel-platform', 'windows')
    assert proc.returncode == 0, proc.stderr
    assert _staged(tmp_path) == {_WIN}


def test_all_platforms_and_bad_platform(tmp_path: Path) -> None:
    proc = _stage(tmp_path, _wheelhouse(tmp_path, [_LIN, _WIN]), '--wheel-platform', 'all')
    assert proc.returncode == 0 and _staged(tmp_path) == {_LIN, _WIN}
    (tmp_path / 'b').mkdir()
    bad = _stage(tmp_path / 'b', _wheelhouse(tmp_path / 'b', [_LIN]), '--wheel-platform', 'mac')
    assert bad.returncode != 0 and 'unknown platform' in bad.stderr


def test_a_checksum_mismatch_blocks_staging(tmp_path: Path) -> None:
    proc = _stage(tmp_path, _wheelhouse(tmp_path, [_LIN], bad=_LIN))
    assert proc.returncode != 0
    assert 'checksum mismatch' in proc.stderr


def test_source_nested_in_another_checkout_is_not_mistaken_for_one(tmp_path: Path) -> None:
    # CI unpacks the tag archive *inside* the workflow's own git checkout. The
    # parent repo tracks none of it, so `git ls-files` there would stage nothing.
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True, env=env)
    wh = _wheelhouse(tmp_path, [_LIN])
    proc = _stage(tmp_path, wh)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / 'out' / 'unicornviz').is_dir()
    assert 'Source is not a git checkout' in proc.stderr  # took the tar fallback


def test_only_the_newest_build_of_each_wheel_is_staged(tmp_path: Path) -> None:
    old = 'a-1.0-cp314-cp314t-manylinux_2_28_x86_64.whl'
    new = 'a-1.0-3-cp314-cp314t-manylinux_2_28_x86_64.whl'
    other = 'b-2.0-cp314-cp314t-manylinux_2_28_x86_64.whl'
    proc = _stage(tmp_path, _wheelhouse(tmp_path, [old, new, other]))
    assert proc.returncode == 0, proc.stderr
    assert _staged(tmp_path) == {new, other}


def test_a_broken_python_stages_every_wheel_not_none(tmp_path: Path) -> None:
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    for name in ('python3', 'python'):
        fake = bindir / name
        fake.write_text('#!/usr/bin/env bash\nexit 9\n')
        fake.chmod(0o755)
    wh = _wheelhouse(tmp_path, [_LIN, 'b-2.0-cp314-cp314t-manylinux_2_28_x86_64.whl'])
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env['PATH'] = f'{bindir}{os.pathsep}{env["PATH"]}'
    proc = subprocess.run(
        ['bash', str(_SCRIPT), '--source-dir', str(_source(tmp_path)), '--dest', str(tmp_path / 'out'),
         '--wheelhouse', str(wh)],
        capture_output=True, text=True, timeout=60, check=False, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert len(_staged(tmp_path)) == 2
