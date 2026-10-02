"""Tests for ``tools/packaging/wheel_select.py`` (newest build of each wheel)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / 'tools' / 'packaging' / 'wheel_select.py'
_spec = importlib.util.spec_from_file_location('wheel_select', _PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
select = _mod.select


def test_highest_build_tag_wins_per_platform() -> None:
    names = [
        'x-1.0-cp314-cp314t-manylinux_2_28_x86_64.whl',
        'x-1.0-2-cp314-cp314t-manylinux_2_28_x86_64.whl',
        'x-1.0-10-cp314-cp314t-manylinux_2_28_x86_64.whl',
        'x-1.0-1-cp314-cp314t-win_amd64.whl',
    ]
    assert select(names) == [names[2], names[3]]


def test_higher_version_beats_a_higher_build_tag() -> None:
    names = ['x-1.0-9-cp314-cp314t-win_amd64.whl', 'x-1.1-cp314-cp314t-win_amd64.whl']
    assert select(names) == [names[1]]


def test_unparseable_names_are_kept() -> None:
    assert select(['weird.whl']) == ['weird.whl']
