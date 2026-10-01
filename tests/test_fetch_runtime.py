"""Regression tests for ``tools/packaging/fetch_runtime.sh``.

Covers the W1 runtime switch (free-threaded CPython 3.14 flavor, pinned
digests) and the integrity rule that a missing checksum is fatal. All network
access is replaced by a stub ``curl`` on PATH, so these run offline.
"""
from __future__ import annotations

import hashlib
import io
import os
import stat
import subprocess
import tarfile
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'packaging' / 'fetch_runtime.sh'

_FT_LINUX = (
    'cpython-3.14.7+20260929-x86_64-unknown-linux-gnu-freethreaded-install_only.tar.gz'
)
_FT_LINUX_SHA = '730c33d387c937bea8995d69d4bc20a24084844120c7d56ed5e0b6f4bfc92641'
_FT_WIN_SHA = '00502edc9de197a4b2e0ed01f31aabaa8dd31b569d2202f471f97fdcc4424f85'


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['bash', str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=60, check=False,
        env={**os.environ, **(env or {})},
    )


def _dry(*args: str) -> dict[str, str]:
    proc = _run('--dry-run', *args)
    assert proc.returncode == 0, proc.stderr
    return dict(line.split('=', 1) for line in proc.stdout.splitlines())


def test_default_flavor_is_still_gil_311() -> None:
    out = _dry('--os', 'linux', '--arch', 'x86_64')
    assert out['asset'] == 'cpython-3.11.10+20241016-x86_64-unknown-linux-gnu-install_only.tar.gz'


def test_ft_flavor_pins_freethreaded_314_assets() -> None:
    lin = _dry('--flavor', 'ft', '--os', 'linux', '--arch', 'x86_64')
    assert lin['asset'] == _FT_LINUX
    assert lin['sha256'] == _FT_LINUX_SHA
    assert lin['url'].startswith(
        'https://github.com/astral-sh/python-build-standalone/releases/download/20260929/')
    win = _dry('--flavor', 'ft', '--os', 'windows', '--arch', 'x86_64')
    assert win['asset'].endswith('x86_64-pc-windows-msvc-freethreaded-install_only.tar.gz')
    assert win['sha256'] == _FT_WIN_SHA


def test_ft_flavor_from_environment() -> None:
    proc = _run('--dry-run', '--os', 'linux', '--arch', 'x86_64',
                env={'UV_RUNTIME_FLAVOR': 'ft'})
    assert 'freethreaded' in proc.stdout


def test_stripped_variant_is_pinned_too() -> None:
    out = _dry('--flavor', 'ft', '--variant', 'freethreaded-install_only_stripped',
               '--os', 'linux', '--arch', 'x86_64')
    assert len(out['sha256']) == 64


def test_unknown_flavor_is_rejected() -> None:
    proc = _run('--flavor', 'nogil', '--dry-run')
    assert proc.returncode != 0
    assert 'Unknown --flavor' in proc.stderr


def _stub_curl(tmp_path: Path, archive: bytes, sums: str | None) -> dict[str, str]:
    """Put a fake ``curl`` on PATH serving ``archive`` and optionally SHA256SUMS."""
    serve = tmp_path / 'serve'
    serve.mkdir()
    (serve / 'archive.bin').write_bytes(archive)
    if sums is not None:
        (serve / 'SHA256SUMS').write_text(sums)
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    curl = bindir / 'curl'
    curl.write_text(
        '#!/usr/bin/env bash\n'
        'out=""; url=""\n'
        'while [[ $# -gt 0 ]]; do case "$1" in -o) out="$2"; shift 2;;'
        ' -*) shift;; *) url="$1"; shift;; esac; done\n'
        f'case "$url" in\n'
        f'  *SHA256SUMS) [[ -f "{serve}/SHA256SUMS" ]] || exit 22; cp "{serve}/SHA256SUMS" "$out";;\n'
        f'  *.sha256) exit 22;;\n'
        f'  *.tar.gz) cp "{serve}/archive.bin" "$out";;\n'
        f'  *) exit 22;;\n'
        'esac\n'
    )
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    return {'PATH': f'{bindir}{os.pathsep}{os.environ["PATH"]}'}


def _fake_runtime_tar() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tf:
        data = b'#!/bin/sh\n'
        info = tarfile.TarInfo('python/bin/python3')
        info.size = len(data)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_missing_checksum_is_fatal(tmp_path: Path) -> None:
    # Unpinned asset (pyver override), no SHA256SUMS, no sidecar.
    env = _stub_curl(tmp_path, _fake_runtime_tar(), sums=None)
    proc = _run('--flavor', 'ft', '--pyver', '3.14.99', '--os', 'linux', '--arch', 'x86_64',
                '--dest', str(tmp_path / 'dest'), env=env)
    assert proc.returncode != 0
    assert 'unverified runtime' in proc.stderr
    assert not (tmp_path / 'dest' / 'python').exists()


def test_missing_checksum_can_be_overridden_explicitly(tmp_path: Path) -> None:
    env = _stub_curl(tmp_path, _fake_runtime_tar(), sums=None)
    env['UV_ALLOW_UNVERIFIED_RUNTIME'] = '1'
    proc = _run('--flavor', 'ft', '--pyver', '3.14.99', '--os', 'linux', '--arch', 'x86_64',
                '--dest', str(tmp_path / 'dest'), env=env)
    assert proc.returncode == 0, proc.stderr
    assert 'UNVERIFIED' in proc.stderr
    assert (tmp_path / 'dest' / 'python' / 'bin' / 'python3').exists()


def test_release_sha256sums_fallback_verifies_and_rejects(tmp_path: Path) -> None:
    archive = _fake_runtime_tar()
    asset = 'cpython-3.14.99+20260929-x86_64-unknown-linux-gnu-freethreaded-install_only.tar.gz'
    good = f'{hashlib.sha256(archive).hexdigest()}  {asset}\n'
    (tmp_path / 'good').mkdir()
    env = _stub_curl(tmp_path / 'good', archive, sums=good)
    proc = _run('--flavor', 'ft', '--pyver', '3.14.99', '--os', 'linux', '--arch', 'x86_64',
                '--dest', str(tmp_path / 'dest-good'), env=env)
    assert proc.returncode == 0, proc.stderr
    assert 'release SHA256SUMS' in proc.stderr

    bad = f'{"0" * 64}  {asset}\n'
    (tmp_path / 'bad').mkdir()
    env = _stub_curl(tmp_path / 'bad', archive, sums=bad)
    proc = _run('--flavor', 'ft', '--pyver', '3.14.99', '--os', 'linux', '--arch', 'x86_64',
                '--dest', str(tmp_path / 'dest-bad'), env=env)
    assert proc.returncode != 0
    assert 'Checksum mismatch' in proc.stderr


def test_pinned_digest_mismatch_is_fatal(tmp_path: Path) -> None:
    # A pinned asset whose served bytes differ from the pin must be rejected
    # even if the (attacker-controlled) release SHA256SUMS agrees with them.
    archive = _fake_runtime_tar()
    sums = f'{hashlib.sha256(archive).hexdigest()}  {_FT_LINUX}\n'
    env = _stub_curl(tmp_path, archive, sums=sums)
    proc = _run('--flavor', 'ft', '--os', 'linux', '--arch', 'x86_64',
                '--dest', str(tmp_path / 'dest'), env=env)
    assert proc.returncode != 0
    assert 'pinned digest' in proc.stderr
    assert 'Checksum mismatch' in proc.stderr
