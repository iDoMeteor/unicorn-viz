"""Regression tests for the bash installer library (``tools/install/lib.sh``).

Covers the helpers that hand-off bundles depend on: manifest-relative URL
resolution and ``file://`` fetches, which must work with no network at all.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / 'tools' / 'install' / 'lib.sh'


def _bash(snippet: str) -> str:
    proc = subprocess.run(
        ['bash', '-c', f'source "{_LIB}"; {snippet}'],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_resolve_url_keeps_absolute_urls() -> None:
    out = _bash('uv_resolve_url "https://get.example/manifest.json" "https://cdn.example/x.tar.gz"')
    assert out == 'https://cdn.example/x.tar.gz'


def test_resolve_url_joins_relative_onto_manifest_dir() -> None:
    out = _bash('uv_resolve_url "file:///bundle/manifest.json" "1.0.0/unicorn-viz-1.0.0.tar.gz"')
    assert out == 'file:///bundle/1.0.0/unicorn-viz-1.0.0.tar.gz'
    out = _bash('uv_resolve_url "https://get.example/rel/manifest.json" "1.0.0/SHA256SUMS"')
    assert out == 'https://get.example/rel/1.0.0/SHA256SUMS'


def test_fetch_to_file_supports_file_urls(tmp_path: Path) -> None:
    src = tmp_path / 'a.txt'
    src.write_text('hello')
    dst = tmp_path / 'b.txt'
    _bash(f'uv_fetch_to_file "file://{src}" "{dst}"')
    assert dst.read_text() == 'hello'
    proc = subprocess.run(['bash', '-c', f'source "{_LIB}"; uv_fetch_to_file "file://{tmp_path}/missing" "{dst}"'],
                          capture_output=True, text=True, timeout=30, check=False)
    assert proc.returncode != 0, 'a missing file:// source must fail'
