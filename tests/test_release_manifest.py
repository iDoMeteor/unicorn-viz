"""Regression tests for ``tools/packaging/manifest.py`` (release manifest writer).

The installer resolves versions and artifact URLs from this manifest, so its
merge semantics must hold: incremental runs compose one release, channel
pointers move, and checksums are real.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / 'tools' / 'packaging' / 'manifest.py'
_spec = importlib.util.spec_from_file_location('release_manifest', _MODULE_PATH)
manifest = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(manifest)


def _write(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    return path


def test_update_merges_artifacts_across_runs_and_moves_channel(tmp_path: Path) -> None:
    out = tmp_path / '1.0.0-beta.110'
    out.mkdir()
    src = _write(out / 'unicorn-viz-1.0.0-beta.110.tar.gz', b'source-bytes')
    rpm = _write(out / 'unicorn-viz-1.0.0~beta.110-1.x86_64.rpm', b'rpm-bytes')
    mpath = tmp_path / 'manifest.json'
    base = ['--manifest', str(mpath), '--version', '1.0.0-beta.110', '--channel', 'prerelease',
            '--tag', 'v1.0.0-beta.110', '--commit', 'abc1234', '--base-url', 'https://get.example/']

    assert manifest.main(['update', *base, '--artifact', f'source={src}']) == 0
    assert manifest.main(['update', *base, '--artifact', f'rpm-x86_64={rpm}']) == 0

    data = json.loads(mpath.read_text())
    rel = data['releases']['1.0.0-beta.110']
    assert set(rel['artifacts']) == {'source', 'rpm-x86_64'}, 'second run must not drop the first artifact'
    assert rel['artifacts']['source']['url'] == 'https://get.example/1.0.0-beta.110/unicorn-viz-1.0.0-beta.110.tar.gz'
    assert rel['artifacts']['source']['sha256'] == hashlib.sha256(b'source-bytes').hexdigest()
    assert rel['artifacts']['rpm-x86_64']['size'] == len(b'rpm-bytes')
    assert data['channels']['prerelease']['version'] == '1.0.0-beta.110'
    assert data['schema'] == manifest.SCHEMA_VERSION


def test_stable_channel_pointer_and_older_release_retained(tmp_path: Path) -> None:
    mpath = tmp_path / 'manifest.json'
    for version, channel in (('0.9.0', 'stable'), ('1.0.0', 'stable')):
        out = tmp_path / version
        out.mkdir()
        art = _write(out / f'unicorn-viz-{version}.tar.gz', version.encode())
        assert manifest.main(['update', '--manifest', str(mpath), '--version', version, '--channel', channel,
                              '--tag', f'v{version}', '--commit', 'deadbee', '--base-url', 'https://get.example',
                              '--artifact', f'source={art}']) == 0
    data = json.loads(mpath.read_text())
    assert data['channels']['stable']['version'] == '1.0.0'
    assert '0.9.0' in data['releases'], 'older releases stay listed'
