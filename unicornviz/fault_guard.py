"""Containing failures in code that must never take the app down.

The main loop and the audio analysis thread call into drop-ins, overlays and
analyzers every frame.  One exception in any of them used to end the thread or
the whole app (audit 2026-09-30, P1-4 / P1-5).  Two small tools:

* :class:`FailureThrottle` -- "log this error once, then at most every
  ``interval_s`` with a count of how many were suppressed", keyed by the
  error's identity, so a persistent failure at 60 Hz writes a handful of lines
  an hour instead of 60 a second.
* :class:`CallGuard` -- run a call, contain and throttle-log its exceptions,
  and *disable* that call site after ``max_consecutive`` failures in a row
  (a drop-in that fails every frame is doing more harm than good).  A success
  resets the streak.  Disabling is per name and for the session unless
  :meth:`CallGuard.reset` is called.

Both are cheap on the success path: ``CallGuard.call`` is one dict lookup, a
try block and an assignment.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

_log = logging.getLogger(__name__)


def error_key(exc: BaseException) -> str:
    """Identity of an error for throttling: its type and the first 80 chars of its text."""
    return f'{type(exc).__name__}: {str(exc)[:80]}'


class FailureThrottle:
    """``should_log(key)`` -> ``(log_now, suppressed_since_last_line)``."""

    __slots__ = ('interval_s', '_seen')

    def __init__(self, interval_s: float = 30.0) -> None:
        self.interval_s = float(interval_s)
        self._seen: dict[str, list[float]] = {}     # key -> [last_logged_t, suppressed]

    def should_log(self, key: str, now: float | None = None) -> tuple[bool, int]:
        now = time.monotonic() if now is None else now
        entry = self._seen.get(key)
        if entry is None:
            if len(self._seen) >= 256:               # a runaway of distinct messages stays bounded
                self._seen.clear()
            self._seen[key] = [now, 0]
            return True, 0
        if now - entry[0] >= self.interval_s:
            suppressed = int(entry[1])
            entry[0], entry[1] = now, 0
            return True, suppressed
        entry[1] += 1
        return False, 0


class CallGuard:
    """Run calls, contain their exceptions, disable call sites that keep failing."""

    def __init__(self, logger: logging.Logger | None = None, *, max_consecutive: int = 30,
                 log_interval_s: float = 30.0) -> None:
        self._log = logger or _log
        self.max_consecutive = int(max_consecutive)
        self._throttle = FailureThrottle(log_interval_s)
        self._streak: dict[str, int] = {}
        self._disabled: set[str] = set()
        self.failures = 0                             # total contained failures

    def disabled(self, name: str) -> bool:
        return name in self._disabled

    def reset(self, name: str | None = None) -> None:
        """Re-enable one call site (or all of them)."""
        if name is None:
            self._disabled.clear()
            self._streak.clear()
        else:
            self._disabled.discard(name)
            self._streak.pop(name, None)

    def call(self, name: str, fn: Callable[..., Any], *args: Any,
             default: Any = None, **kwargs: Any) -> Any:
        """``fn(*args, **kwargs)``, or ``default`` if it raised or ``name`` is disabled."""
        if name in self._disabled:
            return default
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:                      # noqa: BLE001 - the whole point
            self.record_failure(name, exc)
            return default
        if self._streak.get(name):
            self._streak[name] = 0
        return result

    def record_failure(self, name: str, exc: BaseException) -> None:
        self.failures += 1
        streak = self._streak.get(name, 0) + 1
        self._streak[name] = streak
        log_now, suppressed = self._throttle.should_log(f'{name}|{error_key(exc)}')
        if log_now:
            extra = f' ({suppressed} more suppressed)' if suppressed else ''
            self._log.warning('%s failed: %s%s', name, exc, extra, exc_info=exc if not suppressed else None)
        if streak >= self.max_consecutive and name not in self._disabled:
            self._disabled.add(name)
            self._log.error('%s failed %d times in a row; disabled for the rest of this session '
                            '(last error: %s)', name, streak, exc)
