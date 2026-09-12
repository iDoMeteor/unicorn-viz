"""Summarize ``Perf frame:`` lines from a unicorn-viz session log.

The main loop emits one ``Perf frame: total=..ms events=..ms ...`` line at
DEBUG for every frame over 25 ms (and every 120th frame regardless) when
``[logging] perf_frames = true`` and ``level = "debug"``.  This tool turns
those lines into a per-bucket breakdown so a slow session can be read at a
glance: which bucket dominates, how it evolves over time, and which frames
were the worst.

Run from the repo root (defaults to the newest ``logs/unicornviz_*.log``)::

    .venv/bin/python tools/profiling/perf_frames.py
    .venv/bin/python tools/profiling/perf_frames.py logs/unicornviz_20260912_153920.log
    .venv/bin/python tools/profiling/perf_frames.py --medians --top 25 --bucket-s 5

Buckets are parsed generically from ``key=value`` pairs, so new fields added
to the perf line (for example ``vj=`` / ``lyrics=`` / ``osc=``) show up
without changes here.  ``fps`` and ``mode`` are reported but never treated
as timing buckets.
"""

from __future__ import annotations

import argparse
import collections
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / 'logs'

_PERF_RE = re.compile(r'^(\d\d:\d\d:\d\d) DEBUG \[unicornviz\.app\] Perf frame: (.*)$')
_KV_RE = re.compile(r'(\w+)=([\d.]+)ms')
_NON_BUCKETS = frozenset({'total', 'fps'})


def newest_log() -> Path | None:
    """Return the most recently modified session log, or None."""
    logs = sorted(LOG_DIR.glob('unicornviz_*.log'), key=lambda p: p.stat().st_mtime)
    return logs[-1] if logs else None


def parse(path: Path) -> list[dict[str, float | str]]:
    """Parse every perf line in *path* into ``{bucket: ms, 't': 'HH:MM:SS'}``."""
    rows: list[dict[str, float | str]] = []
    with path.open(errors='replace') as fh:
        for line in fh:
            m = _PERF_RE.match(line)
            if not m:
                continue
            row: dict[str, float | str] = {k: float(v) for k, v in _KV_RE.findall(m.group(2))}
            fps = re.search(r'fps=([\d.]+)', m.group(2))
            mode = re.search(r'mode=(\S+)', m.group(2))
            row['fps'] = float(fps.group(1)) if fps else 0.0
            row['mode'] = mode.group(1) if mode else '?'
            row['t'] = m.group(1)
            rows.append(row)
    return rows


def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def bucket_names(rows: list[dict[str, float | str]]) -> list[str]:
    """Timing buckets present in *rows*, in first-seen order, ``total`` first."""
    seen: list[str] = []
    for r in rows:
        for k, v in r.items():
            if isinstance(v, float) and k not in _NON_BUCKETS and k not in seen:
                seen.append(k)
    return ['total', *seen]


def print_summary(rows: list[dict[str, float | str]]) -> None:
    """Per-bucket mean/percentiles/share plus the dominant bucket per frame."""
    names = bucket_names(rows)
    wall = sum(float(r['total']) for r in rows)
    print(f'{len(rows)} perf rows covering {wall / 1000:.0f}s of frame time; '
          f'modes={dict(collections.Counter(str(r["mode"]) for r in rows))}')
    print(f'{"bucket":15s} {"mean":>8s} {"p50":>8s} {"p90":>8s} {"p99":>8s} '
          f'{"max":>9s} {"sum_s":>7s} {"share":>6s}')
    for name in names:
        xs = [float(r.get(name, 0.0)) for r in rows]
        print(f'{name:15s} {statistics.mean(xs):8.2f} {_pct(xs, .5):8.2f} '
              f'{_pct(xs, .9):8.2f} {_pct(xs, .99):8.2f} {max(xs):9.2f} '
              f'{sum(xs) / 1000:7.1f} {100 * sum(xs) / wall:5.1f}%')
    print()
    print('dominant bucket per frame:')
    dom = collections.Counter(
        max(names[1:], key=lambda n: float(r.get(n, 0.0))) for r in rows)
    for name, count in dom.most_common():
        print(f'  {name:15s} {count:6d}  ({100 * count / len(rows):.1f}%)')


def print_timeline(rows: list[dict[str, float | str]], bucket_s: int,
                   medians: bool, columns: list[str]) -> None:
    """Per-``bucket_s`` timeline of the chosen columns (mean or median)."""
    groups: dict[str, list[dict[str, float | str]]] = collections.OrderedDict()
    for r in rows:
        h, m, s = str(r['t']).split(':')
        key = f'{h}:{m}:{(int(s) // bucket_s) * bucket_s:02d}'
        groups.setdefault(key, []).append(r)
    agg = statistics.median if medians else statistics.mean
    label = 'median' if medians else 'mean'
    print()
    print(f'per-{bucket_s}s timeline ({label} ms):  n  ' + '  '.join(f'{c:>10s}' for c in columns)
          + '   wall_s')
    for key, rs in groups.items():
        cells = '  '.join(f'{agg([float(x.get(c, 0.0)) for x in rs]):10.1f}' for c in columns)
        print(f'{key}  {len(rs):4d} {cells}  {sum(float(x["total"]) for x in rs) / 1000:6.1f}')


def print_worst(rows: list[dict[str, float | str]], top: int) -> None:
    """The *top* slowest frames with their full breakdown."""
    names = bucket_names(rows)
    print()
    print(f'top {top} worst frames:')
    for r in sorted(rows, key=lambda r: -float(r['total']))[:top]:
        parts = ' '.join(f'{n}={float(r.get(n, 0.0)):.1f}' for n in names)
        print(f'  {r["t"]} {parts}')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('log', nargs='?', type=Path,
                        help='session log (default: newest logs/unicornviz_*.log)')
    parser.add_argument('--bucket-s', type=int, default=10,
                        help='timeline bucket width in seconds (default 10)')
    parser.add_argument('--medians', action='store_true',
                        help='timeline shows medians instead of means')
    parser.add_argument('--top', type=int, default=15,
                        help='how many worst frames to list (default 15)')
    parser.add_argument('--columns', default='total,subsys_upd,effects,draw,auto_vj,swap',
                        help='comma-separated timeline columns')
    args = parser.parse_args(argv)
    path = args.log or newest_log()
    if path is None or not path.is_file():
        print('no session log found', file=sys.stderr)
        return 1
    rows = parse(path)
    if not rows:
        print(f'{path}: no "Perf frame" lines (needs [logging] perf_frames=true '
              'and level="debug")', file=sys.stderr)
        return 1
    print(f'{path}')
    print_summary(rows)
    print_timeline(rows, args.bucket_s, args.medians,
                   [c.strip() for c in args.columns.split(',') if c.strip()])
    print_worst(rows, args.top)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
