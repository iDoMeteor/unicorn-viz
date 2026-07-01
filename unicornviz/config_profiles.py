"""
Configuration-profile store — named snapshots of tunable runtime *settings*.

A *configuration profile* captures exact settings (per-effect tweakable
parameters now; audio/visual globals and drop-in settings later) under a name,
so a whole tuning can be saved and recalled.  It is deliberately **separate**
from show presets (``ShowPresetStore``): show presets manage which effects are
enabled for rotation, whereas configuration profiles never touch enable/disable
— they only carry settings.

Backed by a single JSON file (``runtime/config_profiles.json``) so profiles
survive restarts and are inspectable/editable by hand.  Payloads are opaque,
schema-versioned dicts; unknown keys round-trip untouched so newer fields do not
break older readers.  This store never writes ``config.toml`` (owner-owned).
"""
from __future__ import annotations

import json
import logging
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from unicornviz.paths import resolve_path

log = logging.getLogger(__name__)

_SCHEMA = 'unicornviz-config-profiles'
_SCHEMA_VERSION = 1


class ConfigProfileStore:
    """JSON-backed store of named configuration profiles.

    Thread-safe for the light concurrency the app needs (render thread may read
    while the main/hotkey thread writes).  Profile payloads are opaque dicts; the
    caller owns their schema (see ``docs/planning/configuration-editor-plan.md``).
    """

    __slots__ = ('_path', '_lock', '_profiles')

    def __init__(self, path: str | Path = 'runtime/config_profiles.json') -> None:
        self._path = resolve_path(path)
        self._lock = threading.RLock()
        self._profiles: dict[str, dict[str, Any]] = {}
        self._load()

    @property
    def path(self) -> Path:
        """Return the on-disk path of the profile file."""
        return self._path

    def _load(self) -> None:
        with self._lock:
            if not self._path.exists():
                self._profiles = {}
                return
            try:
                payload = json.loads(self._path.read_text(encoding='utf-8'))
            except Exception as exc:
                log.warning('Config profile load failed (%s): %s', self._path, exc)
                self._profiles = {}
                return
            profiles = payload.get('profiles') if isinstance(payload, dict) else None
            if isinstance(profiles, dict):
                self._profiles = {
                    str(k): deepcopy(v) for k, v in profiles.items() if isinstance(v, dict)
                }
            else:
                self._profiles = {}

    def _save(self) -> None:
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    '_meta': {'schema': _SCHEMA, 'schema_version': _SCHEMA_VERSION},
                    'profiles': self._profiles,
                }
                tmp = self._path.with_suffix(self._path.suffix + '.tmp')
                tmp.write_text(
                    json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8'
                )
                tmp.replace(self._path)
            except Exception as exc:
                log.warning('Config profile save failed (%s): %s', self._path, exc)

    def names(self) -> list[str]:
        """Return saved profile names, sorted case-insensitively."""
        with self._lock:
            return sorted(self._profiles.keys(), key=str.lower)

    def get(self, name: str) -> dict[str, Any] | None:
        """Return a copy of the named profile payload, or None if absent."""
        with self._lock:
            payload = self._profiles.get(str(name))
            return deepcopy(payload) if payload is not None else None

    def save(self, name: str, payload: dict[str, Any]) -> None:
        """Create or overwrite a named profile and persist to disk."""
        clean = str(name).strip()
        if not clean:
            raise ValueError('Profile name must be non-empty')
        with self._lock:
            self._profiles[clean] = deepcopy(payload)
            self._save()

    def delete(self, name: str) -> bool:
        """Delete a named profile. Returns True if it existed."""
        with self._lock:
            existed = str(name) in self._profiles
            if existed:
                self._profiles.pop(str(name), None)
                self._save()
            return existed

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return str(name) in self._profiles
