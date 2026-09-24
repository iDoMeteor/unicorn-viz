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


def test_a_frozen_heap_makes_full_collections_cheap() -> None:
    import time  # noqa: PLC0415
    heap = [{'k': [i]} for i in range(200_000)]
    t = time.perf_counter(); gc.collect(2); before = time.perf_counter() - t
    freeze_heap('bench')
    t = time.perf_counter(); gc.collect(2); after = time.perf_counter() - t
    assert heap and after < before / 5
