"""NowPlayingHub tests — registry, selection semantics, banner formatting."""
from __future__ import annotations

from unicornviz.now_playing import NowPlayingHub


def _snap(playing: bool, available: bool = True, **extra) -> dict:
    return {'is_playing': playing, 'available': available, **extra}


def test_playing_source_beats_ambient_and_priority_orders_players() -> None:
    hub = NowPlayingHub()
    hub.register('spotify', lambda: _snap(False, title='S'), priority=10,
                 ambient=True)
    hub.register('media', lambda: _snap(True, title='M'), priority=20)
    hub.register('dj_mixer', lambda: _snap(True, title='D'), priority=30)
    name, snap = hub.active()
    assert name == 'dj_mixer' and snap['title'] == 'D'
    hub.unregister('dj_mixer')
    name, _ = hub.active()
    assert name == 'media'


def test_ambient_fallback_when_nothing_is_playing() -> None:
    hub = NowPlayingHub()
    hub.register('media', lambda: _snap(False), priority=20)   # not ambient
    hub.register('spotify', lambda: _snap(False, title='amb'), priority=10,
                 ambient=True)
    name, snap = hub.active()
    assert name == 'spotify' and snap['title'] == 'amb'
    hub.unregister('spotify')
    assert hub.active() is None                # idle non-ambient never shows


def test_raising_source_is_skipped_not_fatal() -> None:
    hub = NowPlayingHub()

    def _boom() -> dict:
        raise RuntimeError('nope')

    hub.register('bad', _boom, priority=99)
    hub.register('ok', lambda: _snap(True, title='ok'), priority=1)
    name, _ = hub.active()
    assert name == 'ok'


def test_banner_args_formatting_and_gating() -> None:
    snap = {'title': 'Better Off Alone', 'artist': 'Alice DJ',
            'album': 'Who Needs Guitars', 'previous_artist': 'DJ Turtle',
            'previous_title': 'Move Your Body', 'duration_s': 215.0,
            'banner_change_counter': 7,
            'now_playing_banner_enabled': True,
            'now_playing_banner_hold_s': 12.0}
    enabled, current, previous, hold, counter = NowPlayingHub.banner_args(
        snap, True, 'PLAYING')
    assert enabled is True and hold == 12.0 and counter == 7
    assert current == ('NOW PLAYING: Alice DJ :: Who Needs Guitars :: '
                       'Better Off Alone :: 03:35')
    assert previous == 'Previous: DJ Turtle :: Move Your Body'
    # Gated off while paused / hidden / disabled.
    assert NowPlayingHub.banner_args(snap, True, 'PAUSED')[0] is False
    assert NowPlayingHub.banner_args(snap, False, 'PLAYING')[0] is False
    snap['now_playing_banner_enabled'] = False
    assert NowPlayingHub.banner_args(snap, True, 'PLAYING')[0] is False
    assert NowPlayingHub.banner_args(None, True, 'PLAYING')[1].startswith(
        'NOW PLAYING: - :: - :: -')


def test_unidentified_track_suppresses_banner_and_platter_gate() -> None:
    # A source that says it is playing but can't name the track must not
    # announce: no banner fire, and is_identified (the platter gate) is False.
    for title in ('', '   ', 'Unknown', 'unknown track', '-', None):
        snap = {'title': title, 'is_playing': True,
                'now_playing_banner_enabled': True}
        assert NowPlayingHub.is_identified(snap) is False
        assert NowPlayingHub.banner_args(snap, True, 'PLAYING')[0] is False
    assert NowPlayingHub.is_identified(None) is False
    named = {'title': 'Better Off Alone', 'is_playing': True,
             'now_playing_banner_enabled': True}
    assert NowPlayingHub.is_identified(named) is True
    assert NowPlayingHub.banner_args(named, True, 'PLAYING')[0] is True


def test_active_evaluates_sources_once_per_frame_and_copies_per_caller(monkeypatch) -> None:
    """Several consumers ask every frame; one evaluation serves them all
    for ~a frame, and nobody can mutate another caller's snapshot."""
    from unicornviz import now_playing as np_mod  # noqa: PLC0415
    hub = np_mod.NowPlayingHub()
    calls = []

    def snap():
        calls.append(1)
        return {'is_playing': True, 'title': 'T'}

    hub.register('mixer', snap, priority=30)
    clock = [100.0]
    monkeypatch.setattr(np_mod.time, 'monotonic', lambda: clock[0])
    first = hub.active()
    second = hub.active()
    assert len(calls) == 1
    assert first == second and first[1] is not second[1]
    first[1]['title'] = 'mutated'
    assert hub.active()[1]['title'] == 'T'
    clock[0] += hub.ACTIVE_TTL_S + 0.001                # next frame: fresh
    hub.active()
    assert len(calls) == 2
    hub.register('media', lambda: {'is_playing': True, 'title': 'M'}, priority=40)
    assert hub.active()[0] == 'media'                   # a new source is seen at once
