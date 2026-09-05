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


# ---------------------------------------------------------------------------
# 2026-09-05: the local playerctl poll runs on a worker, not the render thread.
# ---------------------------------------------------------------------------

def test_local_poll_runs_off_thread_and_commits_a_consistent_snapshot():
    import threading
    import time

    module = _load_spotify_controller_module()
    controller = module.SpotifyController(object(), {'enabled': True})
    controller._playerctl = 'playerctl'            # pretend the binary exists
    seen_threads: list[str] = []

    def fake_run(*args):
        seen_threads.append(threading.current_thread().name)
        time.sleep(0.05)                           # a real spawn takes this long
        if args[0] == 'position':
            return ['12.5']
        return ['Playing', 'spotify:track:1', 'Title X', 'Artist Y', 'Album Z', '180000000']
    controller._run_playerctl = fake_run
    controller._last_poll_t = -1e9                 # a poll is due

    t0 = time.perf_counter()
    controller._update_local(0.016)
    assert (time.perf_counter() - t0) < 0.02       # returned before the spawn finished
    controller._local_poll_thread.join(timeout=2.0)
    assert set(seen_threads) == {'spotify-playerctl'}
    snap = controller.snapshot()
    assert snap['title'] == 'Title X' and snap['artist'] == 'Artist Y'
    assert snap['is_playing'] is True
    assert abs(snap['position_s'] - 12.5) < 1e-6


def test_a_poll_in_flight_is_not_doubled_up():
    import threading
    import time

    module = _load_spotify_controller_module()
    controller = module.SpotifyController(object(), {'enabled': True})
    controller._playerctl = 'playerctl'
    calls = 0
    gate = threading.Event()

    def slow_run(*args):
        nonlocal calls
        calls += 1
        gate.wait(1.0)
        return None
    controller._run_playerctl = slow_run
    controller._last_poll_t = -1e9
    controller._update_local(0.016)
    controller._last_poll_t = -1e9                 # "another interval elapsed"
    controller._update_local(0.016)                # worker still busy: no second thread
    gate.set()
    controller._local_poll_thread.join(timeout=2.0)
    assert calls == 1
