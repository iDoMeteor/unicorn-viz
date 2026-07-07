"""Grouping-logic regression for the media drop-ins (images/textures/sims).

Each got the same directory-group treatment as the videos: subdirectories form
groups, all loose files form one shared group, empties/non-media excluded. Loads
each drop-in's `scan_groups` directly (hyphenated dirs aren't importable).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

_CASES = {
    'images': ('images-01/image_showcase.py', ['a.png', 'b.jpg'], 'c.webp',
               ['loose1.png', 'loose2.jpg']),
    'textures': ('textures-01/texture_showcase.py', ['a.png', 'b.jpg'], 'c.webp',
                 ['loose1.png', 'loose2.jpg']),
}


def _load(rel: str):
    spec = importlib.util.spec_from_file_location(
        'mod_' + rel.replace('/', '_').replace('.', '_'),
        _ROOT / 'drop-ins' / rel,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.scan_groups


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('x')


@pytest.mark.parametrize('name', sorted(_CASES))
def test_media_scan_groups(name, tmp_path):
    rel, subA, subB, loose = _CASES[name]
    scan_groups = _load(rel)
    _touch(tmp_path / 'setA' / subA[0])
    _touch(tmp_path / 'setA' / subA[1])
    _touch(tmp_path / 'setB' / subB)
    for f in loose:
        _touch(tmp_path / f)
    (tmp_path / 'empty').mkdir()
    _touch(tmp_path / 'notes.txt')

    groups = scan_groups(tmp_path)
    names = sorted(sorted(p.name for p in g) for g in groups)
    assert names == [sorted(subA), [subB], sorted(loose)]
    # loose files are one shared group, empty/non-media excluded
    assert any(sorted(p.name for p in g) == sorted(loose) for g in groups)
    assert scan_groups(tmp_path / 'missing') == []


# sims-01 groups loaded USD scenes by source subdir at runtime
# (SimShowcase._select_scene_group) rather than via a dir-scanning helper —
# its USD Props/motion-variant discovery means the scanned files don't map 1:1
# to loaded scenes, so it has no standalone scan_groups to unit-test here.
