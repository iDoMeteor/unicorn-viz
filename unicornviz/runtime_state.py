"""Shared runtime state persistence for Unicorn Viz subsystems.

This module provides a small JSON-backed key-value store using dotted paths
for nested keys (for example, ``webcam.per_camera.0.brightness``).
State is persisted atomically so partial writes do not corrupt the file.
"""
from __future__ import annotations

import json
import logging
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from unicornviz.paths import resolve_path
from unicornviz.safe_store import quarantine

log = logging.getLogger(__name__)

_RUNTIME_STATE_SCHEMA = 'unicornviz.runtime_state'
_RUNTIME_STATE_SCHEMA_VERSION = 1


class RuntimeStateStore:
    """JSON-backed runtime state store with dotted-path accessors."""

    def __init__(self, path: str | Path = 'runtime/global_state.json') -> None:
        self._path = resolve_path(path)
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        #: True when the file failed to load and could not be moved aside: the
        #: store then never writes to that path this session.
        self._save_blocked = False
        self._save_block_logged = False
        self._load()
        if self._ensure_schema_metadata():
            self.save()

    @property
    def path(self) -> Path:
        """Return the on-disk path of this runtime state file."""
        return self._path

    def _load(self) -> None:
        """Load the file.  A file that cannot be read, parsed or is not a JSON
        object is quarantined (``.corrupt-<ts>``) and never overwritten; if it
        cannot even be moved aside, saves are blocked for the session."""
        with self._lock:
            if not self._path.exists():
                self._data = {}
                return
            try:
                payload = json.loads(self._path.read_text(encoding='utf-8'))
                if not isinstance(payload, dict):
                    raise ValueError('not a JSON object')
            except Exception as exc:
                self._data = {}
                if quarantine(self._path, str(exc), 'Runtime state') is None:
                    self._save_blocked = True
                return
            self._data = payload

    def _ensure_schema_metadata(self) -> bool:
        """Ensure payload includes the runtime-state schema header."""
        changed = False
        with self._lock:
            meta = self._data.get('_meta')
            if not isinstance(meta, dict):
                meta = {}
                self._data['_meta'] = meta
                changed = True

            if meta.get('schema') != _RUNTIME_STATE_SCHEMA:
                meta['schema'] = _RUNTIME_STATE_SCHEMA
                changed = True
            if meta.get('schema_version') != _RUNTIME_STATE_SCHEMA_VERSION:
                meta['schema_version'] = _RUNTIME_STATE_SCHEMA_VERSION
                changed = True

            if meta.get('store') != 'global':
                meta['store'] = 'global'
                changed = True
        return changed

    def save(self) -> None:
        """Persist current runtime state to disk atomically."""
        with self._lock:
            if self._save_blocked:
                if not self._save_block_logged:
                    self._save_block_logged = True
                    log.error('Runtime state: not saving to %s this session (the file '
                              'failed to load and could not be moved aside)', self._path)
                return
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = self._path.with_suffix(self._path.suffix + '.tmp')
                tmp_path.write_text(
                    json.dumps(self._data, indent=2, sort_keys=True),
                    encoding='utf-8',
                )
                tmp_path.replace(self._path)
            except Exception as exc:
                log.warning('Runtime state save failed (%s): %s', self._path, exc)

    def snapshot(self) -> dict[str, Any]:
        """Return a deep copy of the entire runtime state payload."""
        with self._lock:
            return deepcopy(self._data)

    def get(self, dotted_path: str, default: Any = None) -> Any:
        """Return a value from dotted path, or *default* when missing."""
        key = str(dotted_path).strip()
        with self._lock:
            if not key:
                return deepcopy(self._data)
            node: Any = self._data
            for part in key.split('.'):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return deepcopy(node)

    def set(self, dotted_path: str, value: Any) -> None:
        """Set a value at dotted path and persist immediately."""
        key = str(dotted_path).strip()
        if not key:
            if not isinstance(value, dict):
                raise ValueError('Root runtime state must be a dict')
            with self._lock:
                self._data = deepcopy(value)
                self._ensure_schema_metadata()
                self.save()
            return

        parts = key.split('.')
        with self._lock:
            node: dict[str, Any] = self._data
            for part in parts[:-1]:
                current = node.get(part)
                if not isinstance(current, dict):
                    current = {}
                    node[part] = current
                node = current
            node[parts[-1]] = deepcopy(value)
            self._ensure_schema_metadata()
            self.save()
