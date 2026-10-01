"""Keep full garbage collections off the frame path with ``gc.freeze()``.

Why this exists
---------------
The main process holds millions of long-lived objects: the mixer's
10k-track library and its tag caches, preset catalogs, effect registries.
Every gen-2 collection walks all of them, and in the logs those passes
took 100-200 ms -- ten frames of frozen visuals and console each time.

``gc.freeze()`` moves every object alive at that moment into a permanent
generation the collector no longer scans.  Measured on this interpreter
(3.14.6) with a 2-million-object heap: a gen-2 collection went from 124 ms
to 1 ms, and the freeze itself costs nothing.

Trade-off: a frozen object that later becomes part of a reference *cycle*
is never reclaimed.  Anything freed by reference counting -- nearly all of
it, including replaced caches -- still frees at once, so the cost is a few
leaked cycles, not the heap.

Free-threaded builds (``Py_GIL_DISABLED``)
------------------------------------------
The premise above is the *generational* collector's.  The free-threaded
collector is not generational: every automatic collection is a full pass,
and a frozen object is skipped but its pages are still walked.  Measured
on 3.14.7t (2026-10-01): freeze halves a full collection (84 -> 41 ms at
2 million objects) but the cost still scales with heap size, where the GIL
build drops to ~0 ms.  So on a free-threaded main process ``freeze_heap``
helps, it does not remove the pause; ``GcPauseMonitor`` below measures what
a live session actually pays.

Usage::

    freeze_heap('startup', collect=True)   # once, before the first frame
    freeze_heap('library prewarm')         # after a big long-lived batch
    install_gc_pause_monitor()             # after the startup freeze
"""
from __future__ import annotations

import gc
import logging
import time

log = logging.getLogger(__name__)


def freeze_heap(reason: str, collect: bool = False) -> int:
    """Move every live object out of the collector's reach; returns how many.

    ``collect`` runs one full collection first so garbage is not frozen with
    the live heap -- a pause of its own, so only do it when a pause is
    harmless (startup).  Safe from any thread.
    """
    t0 = time.perf_counter()
    if collect:
        gc.collect()
    before = gc.get_freeze_count()
    gc.freeze()
    frozen = gc.get_freeze_count()
    log.info('gc: froze %d objects (%s; %d total) in %.1f ms', frozen - before,
             reason, frozen, (time.perf_counter() - t0) * 1000.0)
    return frozen - before


# Match dj-mixer-01's own pause warning (~1.5x the audio block budget).
GC_PAUSE_WARN_MS = 15.0
GC_SUMMARY_INTERVAL_S = 60.0


class GcPauseMonitor:
    """Record every collection's generation, duration and collected count.

    Registered on ``gc.callbacks`` (process-wide, so it sees pauses caused
    by any thread or drop-in).  Cost per collection: two ``perf_counter``
    calls and a few integer updates; nothing is allocated unless a pause
    reaches ``warn_ms`` (one WARNING) or the summary interval elapses (one
    DEBUG line).  Runs inside the collector, so it must stay this small.
    """

    __slots__ = ('warn_ms', 'summary_interval_s', 'count', 'total_ms', 'max_ms',
                 'collected', '_t0', '_last_summary')

    def __init__(self, warn_ms: float = GC_PAUSE_WARN_MS,
                 summary_interval_s: float = GC_SUMMARY_INTERVAL_S) -> None:
        self.warn_ms = float(warn_ms)
        self.summary_interval_s = float(summary_interval_s)
        self.count = [0, 0, 0]              # per generation 0, 1, 2
        self.total_ms = [0.0, 0.0, 0.0]
        self.max_ms = [0.0, 0.0, 0.0]
        self.collected = 0
        self._t0 = 0.0
        self._last_summary = time.perf_counter()

    def install(self) -> None:
        """Idempotent: one registration per monitor."""
        if self._callback not in gc.callbacks:
            gc.callbacks.append(self._callback)

    def uninstall(self) -> None:
        if self._callback in gc.callbacks:
            gc.callbacks.remove(self._callback)

    def _callback(self, phase: str, info: dict) -> None:
        now = time.perf_counter()
        if phase == 'start':
            self._t0 = now
            return
        if not self._t0:
            return
        dur_ms = (now - self._t0) * 1000.0
        self._t0 = 0.0
        gen = info.get('generation', 2)
        gen = gen if 0 <= gen <= 2 else 2
        self.count[gen] += 1
        self.total_ms[gen] += dur_ms
        if dur_ms > self.max_ms[gen]:
            self.max_ms[gen] = dur_ms
        self.collected += info.get('collected', 0)
        if dur_ms >= self.warn_ms:
            log.warning('gc pause %.1f ms (gen %d, collected %d, uncollectable %d)',
                        dur_ms, gen, info.get('collected', 0), info.get('uncollectable', 0))
        if now - self._last_summary >= self.summary_interval_s:
            self._last_summary = now
            log.debug('gc summary: %s', self.summary())

    def summary(self) -> str:
        """``gen0 N/total/max ms, gen1 ..., gen2 ...`` since the monitor started."""
        return ', '.join(
            f'gen{g} {self.count[g]} runs, {self.total_ms[g]:.1f} ms total, {self.max_ms[g]:.1f} ms max'
            for g in range(3))


_monitor: GcPauseMonitor | None = None


def install_gc_pause_monitor() -> GcPauseMonitor:
    """Install the process-wide pause monitor once and return it."""
    global _monitor
    if _monitor is None:
        _monitor = GcPauseMonitor()
    _monitor.install()
    return _monitor
