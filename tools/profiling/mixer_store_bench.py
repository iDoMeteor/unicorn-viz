"""Measure the dj-mixer-01 track store's main-thread costs against real data.

Two things the mixer does per frame or per autosave scale with the library,
and both were found live on 2026-09-12 against a 10k-track store:

* ``autoplay.playlist_progress()`` walks every path after the cursor calling
  ``TrackStore.duration_for_path`` once per frame (about 25 ms warm, about
  95 ms whenever the 2 s stat cache expires).
* ``_flush_track_marks`` -> ``TrackStore.save_async`` re-serializes the whole
  store (16 MB of JSON) on a writer thread after every 30 s autosave, whether
  or not anything changed.

This tool times both against a **copy** of the live store so nothing under
``runtime/`` is touched, and reports how long the main thread was starved
while the writer ran.  Run from the repo root::

    .venv/bin/python tools/profiling/mixer_store_bench.py
    .venv/bin/python tools/profiling/mixer_store_bench.py --store runtime/dj_mixer_tracks.json --rounds 3

Nothing here is a regression test; the numbers depend on the library size
and the disk.  Compare before/after a change to the same store.
"""

from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STORE_MODULE = ROOT / 'drop-ins' / 'dj-mixer-01' / 'track_store.py'
DEFAULT_STORE = ROOT / 'runtime' / 'dj_mixer_tracks.json'


def _load_store_module() -> Any:
    """Import the drop-in's track_store.py by path (drop-in convention)."""
    spec = importlib.util.spec_from_file_location('dj_mixer_track_store', STORE_MODULE)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot load {STORE_MODULE}')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def bench_playlist_walk(store: Any, paths: list[str]) -> None:
    """Emulate ``playlist_progress()``: one ``duration_for_path`` per remaining track."""
    print('-- per-frame playlist walk (playlist_progress emulation)')
    for label in ('cold (stat cache empty)', 'warm (within 2 s cache)', 'warm again'):
        t = time.perf_counter()
        total = 0.0
        for p in paths:
            d = store.duration_for_path(p)
            if d and d > 0.0:
                total += d
        dt = time.perf_counter() - t
        print(f'   {label:26s} {len(paths):6d} paths  {dt * 1000:7.1f} ms  '
              f'({dt / max(1, len(paths)) * 1e6:.1f} us/path)')


def bench_flush(store: Any, paths: list[tuple[str, dict[str, Any]]], rounds: int) -> None:
    """Emulate ``_flush_track_marks``: remember() per loaded deck, then save_async().

    While the writer thread runs, the main thread spins doing a little Python
    work per tick and records the longest gap between ticks, which is how
    long it went without the GIL.
    """
    print('-- autosave flush (remember x2 + save_async, writer thread timed)')
    print('   round 0 re-remembers unchanged marks (a no-op merge should not dirty the '
          'store); later rounds change a bench-only key so the writer really runs')
    for rnd in range(rounds):
        t0 = time.perf_counter()
        for p, entry in paths:
            marks = dict(store.marks_for_hash(entry['hash']) or {})
            if rnd > 0:
                marks['_bench_round'] = rnd          # only ever lands in the copy
            store.remember(p, entry['hash'], marks)
        t1 = time.perf_counter()
        store.save_async()
        t2 = time.perf_counter()
        gaps: list[float] = []
        last = time.perf_counter()
        thread = store._save_thread  # noqa: SLF001 -- the store owns it; this is a bench
        while thread is not None and thread.is_alive():
            now = time.perf_counter()
            gaps.append(now - last)
            last = now
            sum(range(200))
        t3 = time.perf_counter()
        if thread is None:
            print(f'   round {rnd}: store declined the save (nothing dirty) -- '
                  'no writer thread ran')
            continue
        print(f'   round {rnd}: remember {1000 * (t1 - t0):5.1f} ms | save_async() '
              f'{1000 * (t2 - t1):5.1f} ms | writer {1000 * (t3 - t2):6.0f} ms | '
              f'longest main-thread gap {1000 * max(gaps, default=0.0):5.0f} ms')


def bench_gc_and_parse(store_path: Path) -> None:
    """Costs that hold the GIL outright: a full GC pass and a whole-file json.load."""
    print('-- GIL-holding one-shots with the store resident')
    xs = []
    for _ in range(3):
        t = time.perf_counter()
        gc.collect()
        xs.append((time.perf_counter() - t) * 1000)
    print(f'   full gc.collect(): median {statistics.median(xs):.0f} ms '
          f'({len(gc.get_objects())} tracked objects in this process)')
    t = time.perf_counter()
    with store_path.open(encoding='utf-8') as fh:
        json.load(fh)
    print(f'   json.load of the store ({store_path.stat().st_size / 1e6:.1f} MB): '
          f'{(time.perf_counter() - t) * 1000:.0f} ms')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--store', type=Path, default=DEFAULT_STORE,
                        help='live track store to copy (default runtime/dj_mixer_tracks.json)')
    parser.add_argument('--rounds', type=int, default=3, help='autosave flush rounds')
    parser.add_argument('--skip-flush', action='store_true',
                        help='only time the per-frame walk (no writes at all)')
    args = parser.parse_args(argv)
    if not args.store.is_file():
        print(f'store not found: {args.store}', file=sys.stderr)
        return 1
    mod = _load_store_module()
    with tempfile.TemporaryDirectory(prefix='uv-store-bench-') as tmp:
        copy = Path(tmp) / args.store.name
        shutil.copy2(args.store, copy)
        t = time.perf_counter()
        store = mod.TrackStore(copy)
        with copy.open(encoding='utf-8') as fh:
            raw = json.load(fh)
        path_items = list((raw.get('paths') or {}).items())
        print(f'{args.store}: {len(raw.get("tracks") or {})} tracks, {len(path_items)} paths, '
              f'loaded in {(time.perf_counter() - t) * 1000:.0f} ms (working on a copy in {tmp})')
        bench_playlist_walk(store, [p for p, _ in path_items])
        if not args.skip_flush:
            # Two "loaded decks": paths that still exist on disk, so remember()
            # takes the same route the mixer's flush takes.
            on_disk = [(p, e) for p, e in path_items if Path(p).is_file()][:2]
            if len(on_disk) < 2:
                print('-- autosave flush skipped: fewer than two store paths exist on disk')
            else:
                bench_flush(store, on_disk, args.rounds)
        bench_gc_and_parse(copy)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
