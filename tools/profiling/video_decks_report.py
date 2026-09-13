"""Part-B report for the music-video decks layer: cost, upload, A/V, scratch.

Reads one session log (level = "debug") and, optionally, the per-frame
trace written when ``UNICORNVIZ_VIDEO_DECKS_TRACE=<file>`` was set, and
prints the table the strategist asked for:

* ``video_decks`` stage mean / p95 per phase -- idle (no video deck
  visible), single (one deck), dual (two decks, i.e. mid-crossfade) --
  classified from the layer's once-a-second DEBUG line;
* texture upload time, separately, from the trace (per-frame) and from
  the DEBUG line's running average;
* A/V mapping from the trace: for the clapper video's flash frames, the
  deck position at which each flash frame was *chosen* minus the flash pts
  (0 = the frame is picked for the instant the click is written; the ear
  hears it ``latency_s`` later unless the publisher supplies it);
* scratch: ring hit rate over the window where the deck's rate changes
  sign, from the DEBUG line's hit/miss counters.

Usage::

    python tools/profiling/video_decks_report.py logs/unicornviz_<stamp>.log \\
        [--trace /var/tmp/uv-video-decks/trace.jsonl] [--flashes 2,4,6,...]
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

_PERF = re.compile(r'^(\d\d:\d\d:\d\d) DEBUG \[unicornviz\.app\] Perf frame: (.*)$')
_KV = re.compile(r'(\w+)=([\d.]+)ms')
_LAYER = re.compile(r'^(\d\d:\d\d:\d\d) DEBUG \[unicornviz\.video_deck_layer\] Video decks: (.*?) \| update=([\d.]+)ms draw=([\d.]+)ms(?: upload_avg=([\d.]+)ms \(n=(\d+)\))?')
_DECK = re.compile(r'([A-D]) op=([\d.]+) pts=(\S+) hit=(\d+) miss=(\d+) seek=(\d+)')


def _p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))]


def _fmt(xs: list[float]) -> str:
    return f'{statistics.mean(xs):6.2f} / {_p95(xs):6.2f}  (n={len(xs)})' if xs else '   -        -'


def parse_log(path: Path):
    perf: list[tuple[str, dict]] = []
    layer: dict[str, dict] = {}          # second -> {'visible': n, 'decks': {...}, 'upload_avg':..}
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        m = _PERF.match(line)
        if m:
            perf.append((m.group(1), {k: float(v) for k, v in _KV.findall(m.group(2))}))
            continue
        m = _LAYER.match(line)
        if m:
            decks = {}
            for d, op, pts, hit, miss, seek in _DECK.findall(m.group(2)):
                decks[d] = {'op': float(op), 'pts': None if pts == '-' else float(pts),
                            'hit': int(hit), 'miss': int(miss), 'seek': int(seek)}
            layer[m.group(1)] = {
                'visible': sum(1 for v in decks.values() if v['op'] >= 0.005),
                'decks': decks,
                'update': float(m.group(3)), 'draw': float(m.group(4)),
                'upload_avg': float(m.group(5)) if m.group(5) else None,
                'upload_n': int(m.group(6)) if m.group(6) else 0,
            }
    return perf, layer


def phase_table(perf, layer) -> str:
    buckets: dict[str, dict[str, list[float]]] = {
        'idle (no video deck)': {'video_decks': [], 'total': []},
        'single deck visible': {'video_decks': [], 'total': []},
        'two decks (crossfade)': {'video_decks': [], 'total': []},
    }
    for ts, kv in perf:
        info = layer.get(ts)
        n = info['visible'] if info else 0
        key = ('idle (no video deck)' if n == 0 else 'single deck visible' if n == 1
               else 'two decks (crossfade)')
        buckets[key]['video_decks'].append(kv.get('video_decks', 0.0))
        buckets[key]['total'].append(kv.get('total', 0.0))
    out = ['phase                     video_decks mean/p95 ms       frame total mean/p95 ms']
    for k, b in buckets.items():
        out.append(f'{k:<25} {_fmt(b["video_decks"]):<30} {_fmt(b["total"])}')
    return '\n'.join(out)


def upload_table(layer, trace_rows) -> str:
    per_frame = [r['upload_ms'] for r in trace_rows if r.get('upload_ms', 0.0) > 0.0]
    avgs = [v['upload_avg'] for v in layer.values() if v.get('upload_avg')]
    lines = ['texture upload (ms):']
    lines.append(f'  per uploaded frame, from trace   mean/p95 {_fmt(per_frame)}')
    lines.append(f'  running average, from DEBUG line  last {avgs[-1]:.3f} ms' if avgs else '  (no DEBUG upload_avg seen)')
    return '\n'.join(lines)


def av_table(trace_rows, flashes: list[float], tol: float) -> str:
    lines = ['A/V mapping (deck position when the flash frame was chosen - flash pts):']
    for f in flashes:
        picks = [r for r in trace_rows if r.get('pts') is not None and abs(r['pts'] - f) <= tol]
        if not picks:
            lines.append(f'  flash {f:5.1f}s: not shown')
            continue
        first = min(picks, key=lambda r: r['t'])
        lines.append(f'  flash {f:5.1f}s: chosen at position {first["position_s"]:.3f}s  '
                     f'offset {(first["position_s"] - f) * 1000.0:+.0f} ms  '
                     f'(held {len(picks)} frames)')
    return '\n'.join(lines)


def scratch_table(layer) -> str:
    """Hit rate over the seconds where a deck's rate is negative or the
    position moves against the clock -- approximated as consecutive DEBUG
    lines whose pts went backwards."""
    secs = sorted(layer)
    lines = ['scratch (ring hit rate over seconds where pts moved backwards):']
    for d in 'ABCD':
        prev = None
        hits = misses = 0
        for s in secs:
            cur = layer[s]['decks'].get(d)
            if cur is None or prev is None:
                prev = cur
                continue
            if cur['pts'] is not None and prev['pts'] is not None and cur['pts'] < prev['pts']:
                hits += cur['hit'] - prev['hit']
                misses += cur['miss'] - prev['miss']
            prev = cur
        if hits + misses:
            lines.append(f'  deck {d}: hits {hits}  misses {misses}  '
                         f'hit rate {100.0 * hits / (hits + misses):.1f}%')
    if len(lines) == 1:
        lines.append('  (no backwards motion seen)')
    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('log', type=Path)
    ap.add_argument('--trace', type=Path)
    ap.add_argument('--flashes', default='2,4,6,8,10,12,14,16,18',
                    help='flash-frame times (s) in the clapper video')
    ap.add_argument('--tol', type=float, default=1.0 / 60.0)
    args = ap.parse_args()
    perf, layer = parse_log(args.log)
    rows = []
    if args.trace and args.trace.exists():
        rows = [json.loads(line) for line in args.trace.read_text().splitlines() if line.strip()]
    print(f'log: {args.log.name}  perf lines: {len(perf)}  layer lines: {len(layer)}  trace rows: {len(rows)}\n')
    print(phase_table(perf, layer)); print()
    print(upload_table(layer, rows)); print()
    if rows:
        print(av_table(rows, [float(x) for x in args.flashes.split(',') if x], args.tol)); print()
    print(scratch_table(layer))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
