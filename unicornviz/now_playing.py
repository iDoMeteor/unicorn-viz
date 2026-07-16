"""Now-playing announcement hub — one banner, many sources.

The on-screen "NOW PLAYING: artist :: album :: track" banner (rendered by
:mod:`unicornviz.overlays`) used to be fed by hard-coded references to the
media player and Spotify controllers inside ``app.py``.  This hub makes the
feed a **registry**: any subsystem (spotify-01, media-01, dj-mixer-01, future
sources) registers a named snapshot callable and the app announces whichever
source is actually audible.

Snapshot contract (the informal shape spotify-01 established and media-01
mirrors; every key optional, sensible defaults assumed)::

    {
      'available': bool,            # source is usable at all
      'is_playing': bool,
      'status': str,                # e.g. 'PLAYING' (optional)
      'title': str, 'artist': str, 'album': str,
      'previous_title': str, 'previous_artist': str,
      'duration_s': float,
      'banner_change_counter': int, # bump -> the banner (re)shows
      'now_playing_banner_enabled': bool,
      'now_playing_banner_hold_s': float,
    }

Selection: the highest-priority source that ``is_playing`` wins; with nothing
playing, the highest-priority **ambient** source that is ``available`` is shown
instead (Spotify registers ambient: its metadata pane is useful even while the
local player idles — this reproduces the old media-else-spotify behaviour).

Thread-safety: registration happens at subsystem init (main thread);
``active()`` is called from the render loop.  A plain dict + snapshot copies
under the GIL are sufficient here.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger(__name__)


class NowPlayingHub:
    """Registry of now-playing snapshot sources + active-source selection."""

    def __init__(self) -> None:
        # name -> (priority, ambient, snapshot_fn)
        self._sources: dict[str, tuple[int, bool, Callable[[], dict]]] = {}

    def register(self, name: str, snapshot_fn: Callable[[], dict],
                 priority: int = 0, ambient: bool = False) -> None:
        """Add/replace a named source.

        *priority*: higher wins when several sources are playing (suggested:
        dj mixer 30, local media player 20, spotify 10).  *ambient* sources are
        also eligible while idle (metadata-only feeds like Spotify).
        """
        if not name or not callable(snapshot_fn):
            return
        self._sources[name] = (int(priority), bool(ambient), snapshot_fn)
        log.info('now-playing: registered source %r (priority %d%s)',
                 name, priority, ', ambient' if ambient else '')

    def unregister(self, name: str) -> None:
        if self._sources.pop(name, None) is not None:
            log.info('now-playing: unregistered source %r', name)

    def names(self) -> list[str]:
        return list(self._sources.keys())

    def active(self) -> tuple[str, dict] | None:
        """Return ``(name, snapshot)`` for the source to announce, or None.

        Playing sources first (by priority), then ambient available ones.
        A source whose snapshot callable raises is skipped for this frame.
        """
        snaps: list[tuple[int, bool, str, dict]] = []
        for name, (prio, ambient, fn) in self._sources.items():
            try:
                snap = fn()
            except Exception as exc:
                log.debug('now-playing: snapshot from %r failed: %s', name, exc)
                continue
            if isinstance(snap, dict):
                snaps.append((prio, ambient, name, snap))
        snaps.sort(key=lambda t: -t[0])
        for prio, _ambient, name, snap in snaps:
            if snap.get('is_playing'):
                return name, snap
        for prio, ambient, name, snap in snaps:
            if ambient and snap.get('available'):
                return name, snap
        return None

    @staticmethod
    def banner_args(snap: dict[str, Any] | None,
                    visible: bool, status: str) -> tuple:
        """Build ``overlays.set_overlay_banner`` arguments from a snapshot."""
        snap = snap if isinstance(snap, dict) else {}
        track = str(snap.get('title', '') or '').strip() or '-'
        artist = str(snap.get('artist', '') or '').strip() or '-'
        album = str(snap.get('album', '') or '').strip() or '-'
        prev_artist = str(snap.get('previous_artist', '') or '').strip() or '-'
        prev_title = str(snap.get('previous_title', '') or '').strip() or '-'
        counter = int(snap.get('banner_change_counter', 0) or 0)
        enabled = bool(snap.get('now_playing_banner_enabled', False))
        hold_s = max(1.0, float(snap.get('now_playing_banner_hold_s', 10.0)
                                or 10.0))
        dur = max(0.0, float(snap.get('duration_s', 0.0) or 0.0))
        total = max(0, int(dur))
        mm, ss = divmod(total, 60)
        hh, mm = divmod(mm, 60)
        length = f'{hh:02d}:{mm:02d}:{ss:02d}' if hh > 0 else f'{mm:02d}:{ss:02d}'
        current = (f'NOW PLAYING: {artist} :: {album} :: {track} :: {length}')
        previous = f'Previous: {prev_artist} :: {prev_title}'
        return (enabled and visible and status == 'PLAYING',
                current, previous, hold_s, counter)
