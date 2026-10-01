"""Tests for tools/packaging/sphn_third_party_notice.py (the sphn wheel's
THIRD-PARTY notice, generated from ``cargo tree`` output and the cargo registry's
source directories)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'packaging' / 'sphn_third_party_notice.py'


@pytest.fixture(scope='module')
def gen():
    spec = importlib.util.spec_from_file_location('sphn_third_party_notice', SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod        # dataclasses look their module up here
    spec.loader.exec_module(mod)
    return mod


def _registry(tmp_path: Path) -> Path:
    reg = tmp_path / 'registry' / 'src' / 'index-1'
    for name, ver, files in (
        ('alpha', '1.0.0', {'LICENSE-MIT': 'MIT License\nCopyright (c) 2020 Alice\n',
                            'LICENSE-APACHE': 'Apache License text\n'}),
        ('beta', '2.1.0', {'LICENSE-MIT': 'MIT License\nCopyright (c) 2021 Bob\n',
                           'LICENSE-APACHE': 'Apache License text\n'}),
        ('gamma', '0.5.0', {'COPYING': 'Mozilla Public License 2.0 text\n'}),
    ):
        d = reg / f'{name}-{ver}'
        d.mkdir(parents=True)
        for fname, text in files.items():
            (d / fname).write_text(text)
    return tmp_path / 'registry'


def test_parses_cargo_tree_lines_and_merges_targets(gen, tmp_path) -> None:
    lin = tmp_path / 'lin.txt'
    win = tmp_path / 'win.txt'
    lin.write_text('sphn v0.2.1 (/src)|MIT/Apache-2.0|https://x\nalpha v1.0.0|MIT OR Apache-2.0|https://a\n'
                   'beta v2.1.0|MIT|https://b (*)\n')
    win.write_text('alpha v1.0.0|MIT OR Apache-2.0|https://a\ngamma v0.5.0|MPL-2.0|https://g\n')
    crates = gen.read_crates({'linux': lin, 'windows': win})
    names = {(c.name, c.version): c for c in crates}
    assert ('sphn', '0.2.1') not in names                       # the root crate is not third-party
    assert names[('alpha', '1.0.0')].platforms == ['linux', 'windows']
    assert names[('beta', '2.1.0')].repository == 'https://b'    # the "(*)" marker is stripped
    assert names[('gamma', '0.5.0')].platforms == ['windows']


def test_notice_dedupes_identical_license_texts_but_keeps_distinct_copyrights(gen, tmp_path) -> None:
    lin = tmp_path / 'lin.txt'
    lin.write_text('alpha v1.0.0|MIT OR Apache-2.0|https://a\nbeta v2.1.0|MIT OR Apache-2.0|https://b\n'
                   'gamma v0.5.0|MPL-2.0|https://g\n')
    crates = gen.read_crates({'linux': lin})
    text = gen.render(crates, _registry(tmp_path), lock_sha256='abc123', sdist='sphn-0.2.1')
    assert text.count('Apache License text') == 1               # identical text shown once
    assert 'Copyright (c) 2020 Alice' in text and 'Copyright (c) 2021 Bob' in text
    assert 'alpha 1.0.0' in text and 'beta 2.1.0' in text
    assert 'abc123' in text


def test_copyleft_is_called_out(gen, tmp_path) -> None:
    lin = tmp_path / 'lin.txt'
    lin.write_text('gamma v0.5.0|MPL-2.0|https://g\nalpha v1.0.0|MIT|https://a\n')
    crates = gen.read_crates({'linux': lin})
    text = gen.render(crates, _registry(tmp_path), lock_sha256='x', sdist='sphn-0.2.1')
    assert 'MPL-2.0' in text.split('## Licenses at a glance')[1].split('##')[0]
    assert 'weak copyleft' in text.lower()


def test_flags_a_crate_with_no_declared_license(gen, tmp_path) -> None:
    lin = tmp_path / 'lin.txt'
    lin.write_text('mystery v1.0.0||https://m\n')
    crates = gen.read_crates({'linux': lin})
    assert gen.problems(crates) == ['mystery 1.0.0 declares no license']


def _crate_without_license_file(tmp_path: Path, name: str, version: str, authors: str) -> Path:
    reg = tmp_path / 'registry'
    d = reg / 'src' / 'index-1' / f'{name}-{version}'
    d.mkdir(parents=True)
    (d / 'Cargo.toml').write_text(f'[package]\nname = "{name}"\nversion = "{version}"\n'
                                  f'authors = [{authors}]\n')
    return reg


def test_crate_without_a_license_file_gets_the_canonical_spdx_text_and_its_authors(gen, tmp_path) -> None:
    reg = _crate_without_license_file(tmp_path, 'delta', '0.1.0', '"Dana Developer"')
    spdx = tmp_path / 'spdx'
    spdx.mkdir()
    (spdx / 'MPL-2.0.txt').write_text('Mozilla Public License Version 2.0 canonical text\n')
    lin = tmp_path / 'lin.txt'
    lin.write_text('delta v0.1.0|MPL-2.0|https://d\n')
    crates = gen.read_crates({'linux': lin})
    assert gen.unresolved(crates, reg, spdx) == []
    text = gen.render(crates, reg, lock_sha256='x', sdist='sphn-0.2.1', spdx_dir=spdx)
    assert 'Mozilla Public License Version 2.0 canonical text' in text
    assert 'Dana Developer' in text and 'delta 0.1.0' in text


def test_unresolvable_license_text_is_reported(gen, tmp_path) -> None:
    """A notice must not claim texts it does not carry."""
    reg = _crate_without_license_file(tmp_path, 'delta', '0.1.0', '"Dana Developer"')
    lin = tmp_path / 'lin.txt'
    lin.write_text('delta v0.1.0|MPL-2.0|https://d\n')
    crates = gen.read_crates({'linux': lin})
    assert gen.unresolved(crates, reg, None) == ['delta 0.1.0 (MPL-2.0)']


def test_notice_carries_the_docs_metadata_header(gen, tmp_path) -> None:
    lin = tmp_path / 'lin.txt'
    lin.write_text('alpha v1.0.0|MIT|https://a\n')
    text = gen.render(gen.read_crates({'linux': lin}), _registry(tmp_path), lock_sha256='x', sdist='sphn-0.2.1')
    assert text.startswith('Owner: UV Threads\nStatus: generated by ')
    assert 'Last updated: ' in text.split('\n')[2]
