from __future__ import annotations

import importlib.util
from pathlib import Path


_SPOTIFY_CONTROLLER_PATH = (
    Path(__file__).resolve().parents[1] / 'drop-ins' / 'spotify-01' / 'spotify_controller.py'
)


def _load_spotify_controller_module():
    spec = importlib.util.spec_from_file_location('test_spotify_controller_module', _SPOTIFY_CONTROLLER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_spotify_snapshot_exposes_previous_track_and_banner_defaults() -> None:
    module = _load_spotify_controller_module()
    controller = module.SpotifyController(object(), {'enabled': False})

    controller._track_id = 'spotify:track:current'
    controller._title = 'Current Track'
    controller._artist = 'Current Artist'
    controller._album = 'Current Album'
    controller._previous_track_id = 'spotify:track:previous'
    controller._previous_title = 'Previous Track'
    controller._previous_artist = 'Previous Artist'
    controller._previous_album = 'Previous Album'
    controller._duration_s = 123.0
    controller._position_s = 12.0
    controller._change_counter = 7

    snapshot = controller.snapshot()

    assert snapshot['title'] == 'Current Track'
    assert snapshot['previous_title'] == 'Previous Track'
    assert snapshot['previous_artist'] == 'Previous Artist'
    assert snapshot['change_counter'] == 7
    assert snapshot['now_playing_banner_enabled'] is True
    assert snapshot['now_playing_banner_hold_s'] == 10.0
