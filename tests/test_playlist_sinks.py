"""Handing a playlist from one drop-in to another through the core hub.

A *sink*, not a hint bus: exporting is a delivery that happens once and either
works or does not, so unlike the BPM and section channels there is nothing to
time out and nothing to poll.  The point of routing it through core is that
neither drop-in imports the other.
"""
from __future__ import annotations

from unicornviz.app import App


def _app() -> App:
    app = App.__new__(App)
    app._playlist_sinks = {}
    return app


def test_a_sink_receives_the_list_and_its_name() -> None:
    """The name travelling is the whole ask: a set called Friday Peak in the
    sender should be Friday Peak in the receiver, not Playlist 7."""
    got = {}

    def _sink(name, paths):
        got['name'] = name
        got['paths'] = list(paths)
        return len(paths)

    app = _app()
    app.register_playlist_sink('media player', _sink)
    ok, msg = app.export_playlist('media player', 'Friday Peak',
                                  ['/a.mp3', '/b.mp3'])
    assert ok is True
    assert got == {'name': 'Friday Peak', 'paths': ['/a.mp3', '/b.mp3']}
    assert '2 track(s)' in msg and 'Friday Peak' in msg


def test_an_absent_sink_is_an_outcome_not_an_error() -> None:
    """The receiving drop-in simply may not be installed; that is ordinary,
    and every caller is a UI action that must say something either way."""
    app = _app()
    ok, msg = app.export_playlist('media player', 'X', ['/a.mp3'])
    assert ok is False
    assert 'not available' in msg


def test_a_sink_that_raises_is_reported_not_propagated() -> None:
    def _sink(_name, _paths):
        raise RuntimeError('disk full')

    app = _app()
    app.register_playlist_sink('media player', _sink)
    ok, msg = app.export_playlist('media player', 'X', ['/a.mp3'])
    assert ok is False
    assert 'disk full' in msg


def test_the_reported_count_is_what_the_sink_actually_took() -> None:
    """Echoing back what was asked for would hide a receiver that deduplicated
    or refused half the list."""
    app = _app()
    app.register_playlist_sink('media player', lambda _n, _p: 1)
    ok, msg = app.export_playlist('media player', 'X', ['/a.mp3', '/b.mp3'])
    assert ok is True
    assert '1 track(s)' in msg


def test_an_empty_send_is_refused_before_it_reaches_the_sink() -> None:
    calls = []
    app = _app()
    app.register_playlist_sink('media player', lambda n, p: calls.append(n))
    ok, msg = app.export_playlist('media player', 'X', [])
    assert ok is False and 'nothing to send' in msg
    assert calls == []


def test_sinks_are_listed_for_a_menu_and_can_be_dropped() -> None:
    app = _app()
    app.register_playlist_sink('media player', lambda n, p: 0)
    app.register_playlist_sink('archive', lambda n, p: 0)
    assert app.playlist_sinks() == ['archive', 'media player']
    app.unregister_playlist_sink('archive')
    assert app.playlist_sinks() == ['media player']


def test_a_nameless_or_uncallable_sink_is_ignored() -> None:
    app = _app()
    app.register_playlist_sink('', lambda n, p: 0)
    app.register_playlist_sink('x', None)
    assert app.playlist_sinks() == []


def test_media_01_accepts_a_playlist_end_to_end(tmp_path) -> None:
    """The real receiver, through the real hub -- no mocks on either side."""
    import importlib.util  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    root = Path(__file__).resolve().parents[1] / 'drop-ins' / 'media-01'
    if not (root / 'playlists.py').is_file():
        import pytest  # noqa: PLC0415
        pytest.skip('media-01 not checked out')
    spec = importlib.util.spec_from_file_location('mp', root / 'playlists.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    store = mod.MediaPlaylists(tmp_path / 'pl.json')

    def _sink(name, paths):
        if name not in store.names():
            store.create(name)
        took = store.add(name, list(paths))
        store.save()
        return took

    app = _app()
    app.register_playlist_sink('media player', _sink)
    ok, _msg = app.export_playlist('media player', 'Friday Peak',
                                   ['/a.mp3', '/b.mp3'])
    assert ok is True
    assert store.tracks('Friday Peak') == ['/a.mp3', '/b.mp3']

    # A second send adds rather than replacing: the sender may be sending a
    # second batch, and discarding what was there is not recoverable.
    ok, _msg = app.export_playlist('media player', 'Friday Peak',
                                   ['/b.mp3', '/c.mp3'])
    assert ok is True
    assert store.tracks('Friday Peak') == ['/a.mp3', '/b.mp3', '/c.mp3']
