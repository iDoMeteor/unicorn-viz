"""Cached, self-refreshing ``pactl`` queries.

``pactl`` is how the app learns which PipeWire/Pulse endpoints are outputs,
which sink is running, and what the default is.  Three places asked it
directly with ``subprocess.run`` on the main thread: the audio-source
selector (opening the menu), recording start (resolving the monitor to
capture), and capture startup.  Each call is 10-50 ms on an idle desktop and
worse when PipeWire is busy, which it is precisely when a set is playing.

This module runs each distinct query once synchronously, then keeps the
answer fresh on a background thread every ``REFRESH_S`` seconds, so a
caller normally gets a cached string at most a few seconds old and never
blocks.  ``max_age_s`` lets a caller insist on something fresher, in which
case it pays for the subprocess itself.

Platforms without ``pactl`` (Windows, macOS) are detected on the first
failed spawn; every later query returns ``None`` immediately and the
refresher never starts.

Usage::

    from unicornviz.audio.pactl import run_pactl
    out = run_pactl('list', 'short', 'sinks')   # str | None
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time

log = logging.getLogger(__name__)

#: How often the background refresher re-runs every query it has seen.
REFRESH_S = 5.0
#: A cached answer older than this is re-run synchronously by the caller.
DEFAULT_MAX_AGE_S = 12.0
#: Per-spawn timeout; pactl answers in milliseconds or not at all.
TIMEOUT_S = 5.0


class PactlCache:
    """One instance per process; see module docstring."""

    def __init__(self, *, auto_refresh: bool = True) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, ...], tuple[float, str | None]] = {}
        self._unavailable = False
        self._auto_refresh = auto_refresh
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- public ---------------------------------------------------------------

    def get(self, *args: str, max_age_s: float = DEFAULT_MAX_AGE_S) -> str | None:
        """Return stdout of ``pactl *args`` no older than *max_age_s*, or None."""
        key = tuple(args)
        if self._unavailable:
            return None
        now = time.monotonic()
        with self._lock:
            hit = self._entries.get(key)
        if hit is not None and (now - hit[0]) <= max_age_s:
            return hit[1]
        out = self._run(key)
        with self._lock:
            self._entries[key] = (time.monotonic(), out)
        if self._auto_refresh and not self._unavailable:
            self._ensure_refresher()
        return out

    @property
    def available(self) -> bool:
        return not self._unavailable

    def stop(self) -> None:
        """Stop the refresher (tests / teardown); safe to call repeatedly."""
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=1.0)
        self._thread = None

    # -- internals ------------------------------------------------------------

    def _run(self, key: tuple[str, ...]) -> str | None:
        try:
            proc = subprocess.run(
                ['pactl', *key], check=True, capture_output=True,
                text=True, timeout=TIMEOUT_S,
            )
        except FileNotFoundError:
            self._unavailable = True
            log.debug('pactl not installed; audio endpoint queries disabled')
            return None
        except Exception as exc:
            log.debug('pactl %s failed: %s', ' '.join(key), exc)
            return None
        return proc.stdout

    def _ensure_refresher(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._refresh_loop, name='uv-pactl-refresh', daemon=True,
            )
            self._thread.start()

    def _refresh_loop(self) -> None:
        while not self._stop.wait(REFRESH_S):
            with self._lock:
                keys = list(self._entries)
            for key in keys:
                if self._stop.is_set() or self._unavailable:
                    return
                out = self._run(key)
                with self._lock:
                    self._entries[key] = (time.monotonic(), out)


_cache = PactlCache()


def run_pactl(*args: str, max_age_s: float = DEFAULT_MAX_AGE_S) -> str | None:
    """Module-level accessor for the process-wide cache."""
    return _cache.get(*args, max_age_s=max_age_s)
