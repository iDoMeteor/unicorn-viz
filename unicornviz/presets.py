"""
Show-preset store — named snapshots of runtime show configuration.

A *show preset* captures the operator-facing setup (which effects are enabled
for rotation, the playlist mode, global reactivity, …) under a name, so a whole
show configuration can be saved and recalled in one action.  Backed by a single
JSON file (``runtime/presets.json``) so presets survive restarts and are
inspectable/editable by hand.

This is the persistence foundation the forthcoming configuration editor builds
on.  The schema is versioned; unknown keys in a preset payload are preserved on
round-trip so newer fields do not break older readers.
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

_SCHEMA = 'unicornviz-show-presets'
_SCHEMA_VERSION = 1


class ShowPresetStore:
    """JSON-backed store of named show presets.

    Thread-safe for the light concurrency the app needs (render thread may read
    while the hotkey/main thread writes).  Preset payloads are opaque dicts; the
    caller owns their schema.
    """

    __slots__ = ('_path', '_lock', '_presets')

    def __init__(self, path: str | Path = 'runtime/presets.json') -> None:
        self._path = resolve_path(path)
        self._lock = threading.RLock()
        self._presets: dict[str, dict[str, Any]] = {}
        self._load()

    @property
    def path(self) -> Path:
        """Return the on-disk path of the preset file."""
        return self._path

    def _load(self) -> None:
        with self._lock:
            if not self._path.exists():
                self._presets = {}
                return
            try:
                payload = json.loads(self._path.read_text(encoding='utf-8'))
            except Exception as exc:
                log.warning('Preset load failed (%s): %s', self._path, exc)
                self._presets = {}
                return
            presets = payload.get('presets') if isinstance(payload, dict) else None
            if isinstance(presets, dict):
                self._presets = {
                    str(k): deepcopy(v) for k, v in presets.items() if isinstance(v, dict)
                }
            else:
                self._presets = {}

    def _save(self) -> None:
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    '_meta': {'schema': _SCHEMA, 'schema_version': _SCHEMA_VERSION},
                    'presets': self._presets,
                }
                tmp = self._path.with_suffix(self._path.suffix + '.tmp')
                tmp.write_text(
                    json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8'
                )
                tmp.replace(self._path)
            except Exception as exc:
                log.warning('Preset save failed (%s): %s', self._path, exc)

    def names(self) -> list[str]:
        """Return saved preset names, sorted case-insensitively."""
        with self._lock:
            return sorted(self._presets.keys(), key=str.lower)

    def get(self, name: str) -> dict[str, Any] | None:
        """Return a copy of the named preset payload, or None if absent."""
        with self._lock:
            payload = self._presets.get(str(name))
            return deepcopy(payload) if payload is not None else None

    def save(self, name: str, payload: dict[str, Any]) -> None:
        """Create or overwrite a named preset and persist to disk."""
        clean = str(name).strip()
        if not clean:
            raise ValueError('Preset name must be non-empty')
        with self._lock:
            self._presets[clean] = deepcopy(payload)
            self._save()

    def delete(self, name: str) -> bool:
        """Delete a named preset. Returns True if it existed."""
        with self._lock:
            existed = str(name) in self._presets
            if existed:
                self._presets.pop(str(name), None)
                self._save()
            return existed

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return str(name) in self._presets
