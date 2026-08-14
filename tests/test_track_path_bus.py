"""Tests for the shared track-path hint bus on App / VJApi.

2026-08-14, round three: mirrors the BPM hint bus (test_bpm_bus.py) exactly
-- a source that knows a real local file for what's currently playing
(dj-mixer-01) publishes it so an offline consumer (training-kit-01's
packaging step) can run independent analysis (Essentia) against the
actual file, without either side depending on the other.
"""
from __future__ import annotations

import time

from unicornviz.app import App


def _bus() -> App:
    a = App.__new__(App)          # bypass heavy __init__; exercise the bus only
    a._track_path_hints = {}
    return a


def test_publish_and_get() -> None:
    a = _bus()
    a.publish_track_path('dj_mixer', '/music/crates/track.mp3')
    assert a.get_track_path() == '/music/crates/track.mp3'
    assert a.get_track_path(exclude='dj_mixer') == ''   # only source excluded


def test_empty_and_whitespace_paths_ignored() -> None:
    a = _bus()
    a.publish_track_path('x', '')
    a.publish_track_path('y', '   ')
    assert a.get_track_path() == ''


def test_freshest_source_wins() -> None:
    a = _bus()
    a.publish_track_path('auto_vj', '/a.mp3')
    a.publish_track_path('dj_mixer', '/b.mp3')
    assert a.get_track_path() == '/b.mp3'


def test_stale_hints_expire() -> None:
    a = _bus()
    a._track_path_hints['old'] = ('/stale.mp3', time.monotonic() - (App._TRACK_PATH_HINT_TTL_S + 10))
    assert a.get_track_path() == ''
