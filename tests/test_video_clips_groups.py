"""Tests for the Video Clips directory-group selection logic.

Covers the pure `scan_groups` helper: subdirectories become groups, all loose
videos form one shared group, empty/non-video entries are excluded. Loaded from
the drop-in file directly (the dir is hyphenated and not importable as a package).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    'video_clips_under_test',
    Path(__file__).resolve().parents[1] / 'drop-ins' / 'video-clips-01' / 'video_clips.py',
)
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
scan_groups = _MOD.scan_groups


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('x')


def test_subdirs_and_loose_grouping(tmp_path):
    _touch(tmp_path / 'setA' / 'a1.mp4')
    _touch(tmp_path / 'setA' / 'a2.mov')
    _touch(tmp_path / 'setB' / 'b1.webm')
    _touch(tmp_path / 'loose1.mp4')
    _touch(tmp_path / 'loose2.mkv')
    groups = scan_groups(tmp_path)
    names = sorted(sorted(p.name for p in g) for g in groups)
    assert names == [['a1.mp4', 'a2.mov'], ['b1.webm'], ['loose1.mp4', 'loose2.mkv']]


def test_loose_videos_are_one_shared_group(tmp_path):
    _touch(tmp_path / 'x.mp4')
    _touch(tmp_path / 'y.mp4')
    _touch(tmp_path / 'z.mp4')
    groups = scan_groups(tmp_path)
    assert len(groups) == 1
    assert sorted(p.name for p in groups[0]) == ['x.mp4', 'y.mp4', 'z.mp4']


def test_empty_and_nonvideo_excluded(tmp_path):
    (tmp_path / 'empty').mkdir()
    _touch(tmp_path / 'notes.txt')
    _touch(tmp_path / 'docsonly' / 'readme.md')
    _touch(tmp_path / 'real' / 'clip.mp4')
    groups = scan_groups(tmp_path)
    assert len(groups) == 1
    assert [p.name for p in groups[0]] == ['clip.mp4']


def test_missing_dir_returns_empty(tmp_path):
    assert scan_groups(tmp_path / 'nope') == []


@pytest.mark.parametrize('ext', ['.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'])
def test_recognized_extensions(tmp_path, ext):
    _touch(tmp_path / f'clip{ext}')
    groups = scan_groups(tmp_path)
    assert len(groups) == 1 and groups[0][0].suffix == ext
