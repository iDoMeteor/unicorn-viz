"""Deck-state bus and video-layer opacity on the runtime surface.

Music-video decks (docs/planning/music-video-decks-plan-2026-09-13.md,
section 3): dj-mixer-01 publishes per-deck transport state every frame,
the core video-deck layer and auto-vj read it, and auto-vj asks how much
of the picture is video.  Same shape as the section/session buses; a
one-second TTL because a frame-rate feed that stops is stale at once.
"""
from __future__ import annotations

import time

from unicornviz.app import App
from unicornviz.vj_api import VJApi


def _app() -> App:
    app = object.__new__(App)
    app._deck_state_hints = {}
    app._video_deck_layer = None
    return app


def _payload(**decks) -> dict:
    return {'decks': decks, 'crossfader': 0.5}


def test_publish_then_get_round_trips_a_copy() -> None:
    app = _app()
    p = _payload(a={'deck': 'a', 'path': '/x.mp4', 'has_video': True,
                    'position_s': 3.0, 'rate': 1.0, 'playing': True, 'audibility': 0.7})
    app.publish_deck_state('dj_mixer', p)
    got = app.get_deck_state()
    assert got == p and got is not p                       # a copy, not the caller's dict


def test_exclude_skips_the_readers_own_source() -> None:
    app = _app()
    app.publish_deck_state('dj_mixer', _payload(a={'deck': 'a'}))
    assert app.get_deck_state(exclude='dj_mixer') is None
    assert app.get_deck_state(exclude='auto_vj') is not None


def test_stale_state_is_not_returned(monkeypatch) -> None:
    app = _app()
    app.publish_deck_state('dj_mixer', _payload())
    t0 = time.monotonic()
    monkeypatch.setattr(time, 'monotonic', lambda: t0 + App._DECK_STATE_TTL_S + 0.1)
    assert app.get_deck_state() is None


def test_malformed_payloads_are_dropped() -> None:
    app = _app()
    app.publish_deck_state('dj_mixer', 'not a dict')      # type: ignore[arg-type]
    app.publish_deck_state('', _payload())
    assert app.get_deck_state() is None


def test_freshest_source_wins() -> None:
    app = _app()
    app.publish_deck_state('old', _payload(a={'deck': 'a', 'audibility': 0.1}))
    app.publish_deck_state('new', _payload(a={'deck': 'a', 'audibility': 0.9}))
    assert app.get_deck_state()['decks']['a']['audibility'] == 0.9


def test_video_layer_opacity_is_zero_without_a_layer() -> None:
    app = _app()
    assert app.get_video_layer_opacity() == 0.0


def test_video_layer_opacity_reads_the_layer() -> None:
    app = _app()
    app._video_deck_layer = type('L', (), {'layer_opacity': 0.82})()
    assert abs(app.get_video_layer_opacity() - 0.82) < 1e-9


# -- VJApi passthroughs -------------------------------------------------------

def test_vj_api_passthroughs() -> None:
    app = _app()
    api = VJApi(app)
    api.publish_deck_state('dj_mixer', _payload(b={'deck': 'b', 'audibility': 0.4}))
    assert api.get_deck_state()['decks']['b']['audibility'] == 0.4
    assert api.get_deck_state(exclude='dj_mixer') is None
    assert api.get_video_layer_opacity() == 0.0
    app._video_deck_layer = type('L', (), {'layer_opacity': 1.7})()
    assert api.get_video_layer_opacity() == 1.0             # clamped


def test_vj_api_degrades_on_an_older_core() -> None:
    class _OldApp:
        pass
    api = VJApi(_OldApp())
    api.publish_deck_state('dj_mixer', _payload())          # no-op, no raise
    assert api.get_deck_state() is None
    assert api.get_video_layer_opacity() == 0.0
