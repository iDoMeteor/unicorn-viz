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

Usage::

    freeze_heap('startup', collect=True)   # once, before the first frame
    freeze_heap('library prewarm')         # after a big long-lived batch
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
