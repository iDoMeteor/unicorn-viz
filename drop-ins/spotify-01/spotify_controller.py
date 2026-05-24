"""Spotify runtime subsystem for unicorn-viz.

This drop-in polls Spotify metadata via playerctl (MPRIS) and exposes a
stable snapshot API for other automation controllers, especially Auto VJ.

Configuration (in [spotify]):
- enabled = true
- player = "spotify"
- poll_interval_s = 0.75
- command_timeout_s = 0.25
- features_file = "assets/audio/spotify_features.json"  # optional

The optional features file can map track ids to musical metadata:
{
  "spotify:track:2TpxZ7JUBn3uw46aR7qd6V": {
    "bpm": 128,
    "energy": 0.82,
    "danceability": 0.71,
    "valence": 0.64,
        "confidence": 0.9,
        "tags": ["house", "peak-time"],
        "genres": ["electronic", "dance"]
  }
}
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class SpotifyController:
    """Optional Spotify metadata subsystem.

    Thread-safety: this controller is updated on the app's main thread only.
    """

    def __init__(self, app: Any, cfg: dict[str, Any] | None = None) -> None:
        self._app = app
        self._cfg = dict(cfg or {})
        self.enabled = bool(self._cfg.get('enabled', False))

        self._player = str(self._cfg.get('player', 'spotify') or 'spotify').strip()
        self._poll_interval_s = max(0.15, float(self._cfg.get('poll_interval_s', 0.75) or 0.75))
        self._command_timeout_s = max(0.05, float(self._cfg.get('command_timeout_s', 0.25) or 0.25))

        self._playerctl = shutil.which('playerctl')
        if self.enabled and self._playerctl is None:
            self.enabled = False
            log.warning('SpotifyController disabled: playerctl not found in PATH')

        self._features_path = self._resolve_features_path(self._cfg.get('features_file'))
        self._features_mtime_ns: int = -1
        self._features_cache: dict[str, dict[str, Any]] = {}

        self._last_poll_t: float = -1e9
        self._available: bool = False
        self._is_playing: bool = False
        self._status: str = 'stopped'

        self._track_id: str = ''
        self._title: str = ''
        self._artist: str = ''
        self._album: str = ''

        self._duration_s: float = 0.0
        self._position_s: float = 0.0
        self._track_started_t: float = 0.0

        self._change_counter: int = 0

    def update(self, dt: float, audio: Any) -> None:  # noqa: ARG002
        """Poll Spotify state on a throttled cadence."""
        if not self.enabled:
            return
        now = time.monotonic()
        if (now - self._last_poll_t) < self._poll_interval_s:
            if self._is_playing and self._track_started_t > 0.0:
                self._position_s = max(0.0, self._position_s + max(0.0, float(dt)))
            return
        self._last_poll_t = now
        self._poll_playerctl(now)

    def shutdown(self) -> None:
        """Shutdown hook for the app subsystem manager."""
        return

    def snapshot(self) -> dict[str, Any]:
        """Return the current Spotify metadata snapshot for integrations."""
        features = self._feature_payload(self._track_id)
        duration = max(0.0, float(self._duration_s))
        position = max(0.0, float(self._position_s))
        progress = min(1.0, position / duration) if duration > 0.0 else 0.0

        return {
            'available': self._available,
            'is_playing': self._is_playing,
            'status': self._status,
            'track_id': self._track_id,
            'title': self._title,
            'artist': self._artist,
            'album': self._album,
            'duration_s': duration,
            'position_s': position,
            'progress': progress,
            'change_counter': self._change_counter,
            'bpm': float(features.get('bpm', 0.0) or 0.0),
            'energy': float(features.get('energy', 0.0) or 0.0),
            'danceability': float(features.get('danceability', 0.0) or 0.0),
            'valence': float(features.get('valence', 0.0) or 0.0),
            'feature_confidence': float(features.get('confidence', 0.0) or 0.0),
            'tags': self._normalize_tags(features.get('tags', [])),
            'genres': self._normalize_tags(features.get('genres', [])),
            'tag_confidence': float(
                features.get('tag_confidence', features.get('confidence', 0.0))
                or 0.0
            ),
            'source': 'playerctl',
        }

    def _poll_playerctl(self, now: float) -> None:
        parts = self._run_playerctl(
            'metadata',
            '--format',
            '{{status}}\t{{mpris:trackid}}\t{{xesam:title}}\t{{xesam:artist}}\t{{xesam:album}}\t{{mpris:length}}',
        )
        if parts is None or len(parts) < 6:
            if self._available:
                log.info('SpotifyController: player unavailable')
            self._available = False
            self._is_playing = False
            self._status = 'stopped'
            return

        status = str(parts[0] or '').strip().lower()
        track_id = str(parts[1] or '').strip()
        title = str(parts[2] or '').strip()
        artist = str(parts[3] or '').strip()
        album = str(parts[4] or '').strip()

        length_us = self._safe_float(parts[5])
        duration_s = max(0.0, length_us / 1_000_000.0)

        old_track_key = self._track_key(self._track_id, self._title, self._artist)
        new_track_key = self._track_key(track_id, title, artist)

        self._available = True
        self._status = status or 'stopped'
        self._is_playing = self._status == 'playing'
        self._duration_s = duration_s

        if new_track_key and new_track_key != old_track_key:
            self._track_id = track_id
            self._title = title
            self._artist = artist
            self._album = album
            self._change_counter += 1
            self._position_s = 0.0
            self._track_started_t = now
            log.info('Spotify track: %s - %s', self._artist or 'Unknown artist', self._title or 'Unknown title')
        elif track_id:
            self._track_id = track_id
            self._title = title
            self._artist = artist
            self._album = album

        pos_parts = self._run_playerctl('position')
        if pos_parts and pos_parts[0]:
            self._position_s = max(0.0, self._safe_float(pos_parts[0]))
            self._track_started_t = now
        elif self._is_playing and self._track_started_t > 0.0:
            elapsed = max(0.0, now - self._track_started_t)
            self._position_s = max(self._position_s, elapsed)

    def _run_playerctl(self, *args: str) -> list[str] | None:
        if self._playerctl is None:
            return None
        cmd = [self._playerctl, f'--player={self._player}', *args]
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._command_timeout_s,
            )
        except Exception:
            return None
        if proc.returncode != 0:
            return None
        line = (proc.stdout or '').strip()
        if not line:
            return None
        return line.split('\t')

    def _resolve_features_path(self, configured: Any) -> Path | None:
        if not configured:
            return None
        raw = str(configured).strip()
        if not raw:
            return None
        path = Path(raw)
        if path.is_absolute():
            return path
        project_root = Path(__file__).resolve().parents[2]
        return project_root / path

    def _feature_payload(self, track_id: str) -> dict[str, Any]:
        if not track_id:
            return {}
        if self._features_path is None:
            return {}
        self._refresh_features_cache()
        row = self._features_cache.get(track_id)
        if isinstance(row, dict):
            return row
        return {}

    def _refresh_features_cache(self) -> None:
        path = self._features_path
        if path is None:
            return
        try:
            stat = path.stat()
        except Exception:
            return
        mtime_ns = int(getattr(stat, 'st_mtime_ns', 0))
        if mtime_ns == self._features_mtime_ns:
            return
        self._features_mtime_ns = mtime_ns
        try:
            with path.open('r', encoding='utf-8') as f:
                payload = json.load(f)
        except Exception as exc:
            log.warning('SpotifyController failed to load features file %s: %s', path, exc)
            return
        if not isinstance(payload, dict):
            return

        rows: dict[str, dict[str, Any]] = {}
        for key, value in payload.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            rows[key] = value
        self._features_cache = rows

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except Exception:
            return 0.0

    @staticmethod
    def _track_key(track_id: str, title: str, artist: str) -> str:
        if track_id:
            return track_id.strip().lower()
        combo = f'{artist.strip()}::{title.strip()}'.strip(':')
        return combo.lower()

    @staticmethod
    def _normalize_tags(value: Any) -> list[str]:
        items: list[str] = []
        if isinstance(value, str):
            raw = [part.strip() for part in value.replace('|', ',').split(',')]
            items = [part for part in raw if part]
        elif isinstance(value, list):
            items = [str(part).strip() for part in value if str(part).strip()]
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
        return out
