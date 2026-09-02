"""media-01 publishes the playing track's authored BPM tag on the vj_api bus.

2026-09-03 (v3 phase 4): auto-vj primes its tracker from any non-'auto_vj'
BPM hint on the bus (the P0-B lookup), the way it already does from
dj-mixer-01's analysis. media-01 now supplies that hint for tagged local
files -- read once per track (cached by path), republished every frame
while playing, nothing for untagged files. These tests exercise the publish
logic on a bare controller instance (no window, no audio) with the tag
reader stubbed, plus tags.read_bpm's range guard on a real tag reader.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

_MEDIA_DIR = Path(__file__).resolve().parents[1] / 'drop-ins' / 'media-01'


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _MEDIA_DIR / filename)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_MC = _load('test_media_tag_bpm_controller', 'media_controller.py')
_TAGS = _load('test_media_tag_bpm_tags', 'tags.py')


class _Bus:
    def __init__(self) -> None:
        self.published: list[tuple[str, float]] = []

    def publish_bpm(self, source: str, bpm: float) -> None:
        self.published.append((source, float(bpm)))


def _bare_controller(path: str, playing: bool = True, tag_bpm: float = 82.0):
    """A controller instance with only the state _publish_track_bpm reads."""
    ctl = _MC.MediaController.__new__(_MC.MediaController)
    ctl._is_playing = playing
    ctl._index = 0
    ctl.snapshot_path_at = lambda i: path
    ctl._app = SimpleNamespace(vj_api=_Bus())
    ctl._tag_bpm_path = ''
    ctl._tag_bpm = 0.0
    ctl._tags_mod = SimpleNamespace(read_bpm=lambda p: tag_bpm)
    return ctl


def test_tagged_track_publishes_its_bpm_every_frame() -> None:
    ctl = _bare_controller('/music/a.mp3', tag_bpm=82.0)
    ctl._publish_track_bpm()
    ctl._publish_track_bpm()
    assert ctl._app.vj_api.published == [('media', 82.0), ('media', 82.0)]
    assert ctl._tag_bpm_path == '/music/a.mp3' and ctl._tag_bpm == 82.0


def test_untagged_track_publishes_nothing() -> None:
    ctl = _bare_controller('/music/b.mp3', tag_bpm=0.0)
    ctl._publish_track_bpm()
    assert ctl._app.vj_api.published == []


def test_not_playing_publishes_nothing() -> None:
    ctl = _bare_controller('/music/a.mp3', playing=False)
    ctl._publish_track_bpm()
    assert ctl._app.vj_api.published == []


def test_tag_is_read_once_per_track_and_rereads_on_change() -> None:
    calls: list[str] = []

    def reader(p: str) -> float:
        calls.append(p)
        return 128.0 if p.endswith('c.mp3') else 74.0

    ctl = _bare_controller('/music/c.mp3')
    ctl._tags_mod = SimpleNamespace(read_bpm=reader)
    ctl._publish_track_bpm()
    ctl._publish_track_bpm()
    assert calls == ['/music/c.mp3']
    ctl.snapshot_path_at = lambda i: '/music/d.mp3'
    ctl._publish_track_bpm()
    assert calls == ['/music/c.mp3', '/music/d.mp3']
    assert ctl._app.vj_api.published[-1] == ('media', 74.0)


def test_read_bpm_range_guard_and_missing_file() -> None:
    assert _TAGS.read_bpm('/nonexistent/track.mp3') == 0.0
    assert _TAGS.read_bpm('/nonexistent/track.wav') == 0.0
