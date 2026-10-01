"""Regression tests for ``tools/packaging/fetch_wheelhouse.sh``.

CI fetches our cp314t wheels from a GitHub release and must accept them only
if they match the committed trust file. Downloads are served from a local
``file://`` tree, so these run offline.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'packaging' / 'fetch_wheelhouse.sh'
_COMMITTED = Path(__file__).resolve().parents[1] / 'tools' / 'packaging' / 'wheelhouse-cp314t.sha256'

_TAG = 'wheelhouse-test-1'


def _serve(tmp_path: Path, files: dict[str, bytes]) -> Path:
    root = tmp_path / 'serve'
    (root / _TAG).mkdir(parents=True)
    for name, data in files.items():
        (root / _TAG / name).write_bytes(data)
    return root


def _trust(tmp_path: Path, files: dict[str, bytes], tag: str | None = _TAG) -> Path:
    trust = tmp_path / 'trust.sha256'
    lines = ['# test trust file']
    if tag:
        lines.append(f'# release-tag: {tag}')
    lines += [f'{hashlib.sha256(d).hexdigest()}  {n}' for n, d in files.items()]
    trust.write_text('\n'.join(lines) + '\n')
    return trust


def _run(tmp_path: Path, serve: Path, trust: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['bash', str(_SCRIPT), '--dest', str(tmp_path / 'wh'), '--trust', str(trust),
         '--base-url', f'file://{serve}'],
        capture_output=True, text=True, timeout=60, check=False,
    )


_WHEELS = {'a-1.0-cp314-cp314t-linux_x86_64.whl': b'wheel-a', 'b-2.0-cp314-cp314t-linux_x86_64.whl': b'wheel-b'}


def test_fetches_and_verifies_every_listed_wheel(tmp_path: Path) -> None:
    proc = _run(tmp_path, _serve(tmp_path, _WHEELS), _trust(tmp_path, _WHEELS))
    assert proc.returncode == 0, proc.stderr
    for name, data in _WHEELS.items():
        assert (tmp_path / 'wh' / name).read_bytes() == data
    sums = (tmp_path / 'wh' / 'SHA256SUMS').read_text().splitlines()
    assert len(sums) == 2 and all(len(s.split()[0]) == 64 for s in sums)


def test_swapped_asset_fails_and_is_not_left_behind(tmp_path: Path) -> None:
    trust = _trust(tmp_path, _WHEELS)
    tampered = dict(_WHEELS, **{'b-2.0-cp314-cp314t-linux_x86_64.whl': b'evil'})
    proc = _run(tmp_path, _serve(tmp_path, tampered), trust)
    assert proc.returncode != 0
    assert 'checksum mismatch' in proc.stderr
    assert not (tmp_path / 'wh' / 'b-2.0-cp314-cp314t-linux_x86_64.whl').exists()


def test_the_release_sums_file_is_never_trusted(tmp_path: Path) -> None:
    # A release SHA256SUMS that "agrees" with a tampered asset changes nothing.
    trust = _trust(tmp_path, _WHEELS)
    tampered = dict(_WHEELS, **{'a-1.0-cp314-cp314t-linux_x86_64.whl': b'evil'})
    serve = _serve(tmp_path, tampered)
    (serve / _TAG / 'SHA256SUMS').write_text(
        ''.join(f'{hashlib.sha256(d).hexdigest()}  {n}\n' for n, d in tampered.items()))
    assert _run(tmp_path, serve, trust).returncode != 0


def test_missing_asset_and_missing_tag_fail(tmp_path: Path) -> None:
    serve = _serve(tmp_path, {})
    assert _run(tmp_path, serve, _trust(tmp_path, _WHEELS)).returncode != 0
    no_tag = _trust(tmp_path, _WHEELS, tag=None)
    proc = _run(tmp_path, serve, no_tag)
    assert proc.returncode != 0
    assert 'release-tag' in proc.stderr


def test_committed_trust_file_is_well_formed() -> None:
    lines = [ln for ln in _COMMITTED.read_text().splitlines() if ln.strip() and not ln.startswith('#')]
    assert lines, 'the committed trust file lists no wheels'
    tags = [ln for ln in _COMMITTED.read_text().splitlines() if ln.startswith('# release-tag:')]
    assert tags and not any(t.split(':', 1)[1].strip().startswith('v') for t in tags), \
        'a wheelhouse tag must not look like an app release tag (v*.*.*)'
    for ln in lines:
        sha, name = ln.split()
        assert len(sha) == 64 and name.endswith('.whl') and 'cp314t' in name
