"""unicornviz.gc_tuning: freeze long-lived objects out of the cyclic GC.

Gen-2 passes over the app's multi-million-object heap cost 100-200 ms of
frozen frames; after gc.freeze() the same pass walks only what is new.
"""
from __future__ import annotations

import gc

import pytest

from unicornviz.gc_tuning import freeze_heap


@pytest.fixture(autouse=True)
def _unfreeze():
    yield
    gc.unfreeze()


def test_freeze_moves_live_objects_out_of_the_collectors_reach() -> None:
    keep = [{'i': i} for i in range(5000)]
    frozen = freeze_heap('test')
    assert frozen >= 5000
    assert gc.get_freeze_count() >= frozen
    assert keep                                   # still alive, just frozen


def test_collect_first_leaves_existing_garbage_out_of_the_freeze() -> None:
    gc.unfreeze()
    class Node:                                   # noqa: D401 - tiny cycle maker
        pass
    for _ in range(200):
        a, b = Node(), Node()
        a.other, b.other = b, a                   # cyclic garbage
    del a, b
    with_collect = freeze_heap('collect first', collect=True)
    assert not any(type(o).__name__ == 'Node' for o in gc.get_objects())
    assert with_collect >= 0


def _full_collection_ms() -> float:
    import time  # noqa: PLC0415
    t = time.perf_counter()
    gc.collect(2)
    return (time.perf_counter() - t) * 1000.0


def test_a_frozen_heap_makes_full_collections_cheap() -> None:
    """The contract differs by collector, so the build decides the assertion.

    GIL build (generational): after the freeze a full collection walks only
    new objects: ~0 ms at any heap size (measured 2026-10-01 on 3.14.6: 18 /
    87 / 175 ms before and 0.0 ms after at 200k / 1M / 2M objects).

    Free-threaded build: the collector is not generational and still walks
    the frozen heap's pages, so the freeze halves the pass but it keeps
    scaling with heap size (3.14.7t: 8.7 / 42 / 84 ms before, 4.3 / 21 /
    41 ms after).  There it must be at least ~1.5x cheaper and never slower.
    Branch on the build, not on ``sys._is_gil_enabled()``: the main process
    re-enables the GIL at runtime but the collector stays the free-threaded one.
    """
    import sysconfig  # noqa: PLC0415
    heap = [{'k': [i]} for i in range(200_000)]
    before = sorted(_full_collection_ms() for _ in range(3))[1]
    freeze_heap('bench')
    after = sorted(_full_collection_ms() for _ in range(3))[1]
    assert heap
    if sysconfig.get_config_var('Py_GIL_DISABLED'):
        assert after < before / 1.5, f'freeze gained <1.5x on free-threaded: {before:.1f} -> {after:.1f} ms'
    else:
        assert after < before / 5


# --- GcPauseMonitor -------------------------------------------------------

def _monitor(**kw):
    from unicornviz.gc_tuning import GcPauseMonitor  # noqa: PLC0415
    m = GcPauseMonitor(**kw)
    m.install()
    return m


def test_monitor_is_installed_once_and_removable() -> None:
    from unicornviz.gc_tuning import GcPauseMonitor, install_gc_pause_monitor  # noqa: PLC0415
    m = GcPauseMonitor()
    m.install()
    m.install()
    assert gc.callbacks.count(m._callback) == 1
    m.uninstall()
    assert m._callback not in gc.callbacks
    shared = install_gc_pause_monitor()
    assert install_gc_pause_monitor() is shared
    assert gc.callbacks.count(shared._callback) == 1
    shared.uninstall()


def test_a_forced_collection_is_recorded() -> None:
    m = _monitor(warn_ms=10_000.0)
    try:
        gc.collect(2)
        assert m.count[2] >= 1
        assert m.max_ms[2] > 0.0 and m.total_ms[2] >= m.max_ms[2]
        assert 'gen2' in m.summary()
    finally:
        m.uninstall()


def test_a_pause_over_the_threshold_warns_and_a_short_one_does_not(caplog) -> None:
    import logging  # noqa: PLC0415
    loud = _monitor(warn_ms=0.0)
    try:
        with caplog.at_level(logging.WARNING, logger='unicornviz.gc_tuning'):
            gc.collect(2)
    finally:
        loud.uninstall()
    assert any('gc pause' in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)
    caplog.clear()
    quiet = _monitor(warn_ms=10_000.0)
    try:
        with caplog.at_level(logging.WARNING, logger='unicornviz.gc_tuning'):
            gc.collect(2)
    finally:
        quiet.uninstall()
    assert not [r for r in caplog.records if 'gc pause' in r.getMessage()]


def test_the_periodic_summary_goes_to_debug(caplog) -> None:
    import logging  # noqa: PLC0415
    m = _monitor(warn_ms=10_000.0, summary_interval_s=0.0)
    try:
        with caplog.at_level(logging.DEBUG, logger='unicornviz.gc_tuning'):
            gc.collect(2)
    finally:
        m.uninstall()
    rec = [r for r in caplog.records if r.getMessage().startswith('gc summary:')]
    assert rec and rec[0].levelno == logging.DEBUG
