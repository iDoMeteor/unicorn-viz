"""Main-loop stall watchdog: dump every thread's stack when a frame hangs.

Why this exists
---------------
``faulthandler`` already catches native crashes (segfaults, aborts) and
writes a full per-thread traceback to ``logs/faulthandler_*.log``.  It does
nothing for the other way a session dies: the main loop stops advancing, the
window freezes, and the owner force-quits.  SIGKILL cannot be handled, so
that path leaves a zero-byte faulthandler file and a log that just stops --
which is exactly what the 2026-09-05 mixer-search hang left behind.

``faulthandler.dump_traceback_later()`` is the missing half.  Armed with a
timeout and re-armed every frame, it fires only if the main loop fails to
come back around in time, and then writes the same all-thread dump a crash
would have -- while the process is still hung, before anyone reaches for the
kill button.

Cost
----
Each arm cancels the previous watchdog thread and starts a new one, so this
class re-arms at most once per ``rearm_s`` (default 1 s) rather than every
frame.  A stall is therefore reported between ``timeout_s`` and
``timeout_s + rearm_s`` after the last completed frame.  The per-frame
``tick()`` is one ``monotonic()`` call and a compare.

Usage::

    wd = StallWatchdog(file=fh, timeout_s=5.0)
    while running:
        wd.tick()          # top of every frame
        ...
    wd.stop()
"""
from __future__ import annotations

import faulthandler
import time
from typing import IO


class StallWatchdog:
    """Re-armable ``faulthandler.dump_traceback_later`` for the render loop.

    Not thread-safe by design: ``tick()`` belongs to the main thread, the one
    whose liveness it measures.  ``stop()`` may be called from anywhere.
    """

    __slots__ = ('_file', '_timeout_s', '_rearm_s', '_last_arm', '_armed')

    def __init__(self, file: IO[str] | None, timeout_s: float, rearm_s: float = 1.0) -> None:
        self._file = file
        self._timeout_s = max(0.1, float(timeout_s))
        self._rearm_s = max(0.05, float(rearm_s))
        self._last_arm = 0.0
        self._armed = False

    @property
    def timeout_s(self) -> float:
        """Seconds the main loop may go without a frame before a dump."""
        return self._timeout_s

    @property
    def armed(self) -> bool:
        """True after the first tick and until ``stop()``."""
        return self._armed

    def tick(self, now: float | None = None) -> bool:
        """Mark the main loop alive; re-arm the dump timer if it is due.

        Returns True when the timer was (re)armed on this call.
        """
        t = time.monotonic() if now is None else float(now)
        if self._armed and (t - self._last_arm) < self._rearm_s:
            return False
        kwargs = {'repeat': False, 'exit': False}
        if self._file is not None:
            kwargs['file'] = self._file
        faulthandler.dump_traceback_later(self._timeout_s, **kwargs)
        self._last_arm = t
        self._armed = True
        return True

    def stop(self) -> None:
        """Cancel the pending dump; safe to call repeatedly."""
        if self._armed:
            faulthandler.cancel_dump_traceback_later()
            self._armed = False
