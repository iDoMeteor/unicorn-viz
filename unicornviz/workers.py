"""Worker processes for heavy, pure batch jobs (track analysis and the like).

Why this exists
---------------
Library-wide jobs -- decoding and analysing thousands of tracks -- used to
run on a background *thread* of the main process.  A thread does not escape
the GIL: every second of numpy-and-Python analysis was taken from the
visualizer's frame budget, for the hours a big library takes.  Worker
processes take that work off the main process entirely, run in parallel on
separate cores, and at a lower scheduling priority than the app itself.

How
---
:class:`WorkerPool` wraps a ``spawn``-context ``ProcessPoolExecutor``.
Drop-in modules are loaded by file path, not importable by name, so jobs
are submitted as ``(module path, function name, *args)`` and each worker
loads (and caches) the module itself -- :func:`call_by_path`.  Job functions
must be pure: arguments and results are plain picklable data.

Usage::

    pool = WorkerPool(4, name='analysis')
    fut = pool.submit('/path/to/job.py', 'analyze_track', path, opts)
    result = fut.result()
    pool.shutdown()
"""
from __future__ import annotations

import concurrent.futures
import importlib.util
import logging
import multiprocessing
import os
import sys
from typing import Any

log = logging.getLogger(__name__)

#: Niceness added in each worker: batch work yields to rendering and audio.
WORKER_NICENESS = 10


class _Loaded:
    """Per worker process: modules loaded by path, so each loads once."""

    modules: dict[str, Any] = {}


def default_workers() -> int:
    """A quarter of the cores, 1-4: enough to go fast, never to crowd the app.

    ``UNICORNVIZ_WORKERS`` overrides it (``0`` = no worker processes: callers
    run their jobs in-thread -- what the test suites use, so monkeypatched
    code stays in the process that patched it).
    """
    env = os.environ.get('UNICORNVIZ_WORKERS')
    if env is not None and env.strip().isdigit():
        return int(env)
    return max(1, min(4, (os.cpu_count() or 4) // 4))


def _init_worker() -> None:
    try:
        os.nice(WORKER_NICENESS)
    except (AttributeError, OSError):   # Windows / not permitted: run as is
        pass
    os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')


def call_by_path(module_path: str, func_name: str, *args: Any, **kwargs: Any) -> Any:
    """Worker side: load ``module_path`` once, call ``func_name`` on it."""
    mod = _Loaded.modules.get(module_path)
    if mod is None:
        name = f'_worker_{abs(hash(module_path))}'
        spec = importlib.util.spec_from_file_location(name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(module_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        _Loaded.modules[module_path] = mod
    return getattr(mod, func_name)(*args, **kwargs)


class WorkerPool:
    """A small process pool for pure jobs from path-loaded modules.

    Thread-safe for submission (``ProcessPoolExecutor`` is).  Workers start
    lazily on the first submit.
    """

    def __init__(self, max_workers: int | None = None, name: str = 'workers') -> None:
        self.max_workers = int(max_workers or default_workers())
        self.name = name
        self._pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=self.max_workers,
            mp_context=multiprocessing.get_context('spawn'),
            initializer=_init_worker)
        log.info('%s: %d worker process(es)', name, self.max_workers)

    def submit(self, module_path: str, func_name: str, *args: Any,
               **kwargs: Any) -> concurrent.futures.Future:
        return self._pool.submit(call_by_path, os.path.abspath(module_path),
                                 func_name, *args, **kwargs)

    def shutdown(self, wait: bool = False) -> None:
        """Stop the workers; queued jobs are cancelled."""
        self._pool.shutdown(wait=wait, cancel_futures=True)
