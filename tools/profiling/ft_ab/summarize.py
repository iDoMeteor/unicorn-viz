"""Summarize the GIL-vs-free-threaded A/B: CPU, main-loop frames, mixer UI, audio engine.

    python tools/profiling/ft_ab/summarize.py [AB_DIR]

``slow_frames_per_min`` counts main-loop frames over 25 ms (the perf line is
only written for those and every 120th frame, so p95 is of that sample).
Mixer UI and audio-engine columns are the per-interval render ms the mixer logs.
"""
from __future__ import annotations

import re
import statistics
import sys
from pathlib import Path

D = Path(sys.argv[1] if len(sys.argv) > 1 else '/var/tmp/uv-ab')
win = {l.split()[0]: l.split()[1:] for l in (D / 'window.txt').read_text().splitlines()}
cpu = {}
for l in (D / 'cpu.txt').read_text().splitlines():
    k = l.split()[0]; cpu[k] = dict(p.split('=') for p in l.split()[1:] if '=' in p)
def sec(h): a, b, c = map(int, h.split(':')); return a * 3600 + b * 60 + c
PERF = re.compile(r'^(\d\d:\d\d:\d\d) DEBUG \[unicornviz\.app\] Perf frame: total=([\d.]+)ms')
UI = re.compile(r'^(\d\d:\d\d:\d\d) .*dj-mixer: ui (\d+) frame\(s\): render ([\d.]+)/([\d.]+)/([\d.]+)ms')
GCW = re.compile(r'^(\d\d:\d\d:\d\d) WARNING \[unicornviz\.gc_tuning\] gc pause ([\d.]+) ms')
GCS = re.compile(r'gc summary: .*gen2 (\d+) runs, ([\d.]+) ms total, ([\d.]+) ms max')
AU = re.compile(r'^(\d\d:\d\d:\d\d) .*dj-mixer-01: audio (\d+) block\(s\): render ([\d.]+)/([\d.]+)/([\d.]+)ms')
def p(x, q):
    x = sorted(x); return x[int(q * (len(x) - 1))] if x else float('nan')
rows = {}
for label, (w0, w1) in win.items():
    a, b = sec(w0), sec(w1); tot, ui, au, gcw = [], [], [], []
    gcs = None
    for line in (D / f'{label}.session.log').read_text(errors='replace').splitlines():
        mg = GCS.search(line)
        if mg: gcs = [float(x) for x in mg.groups()]
        for rx, acc in ((PERF, tot), (UI, ui), (AU, au), (GCW, gcw)):
            m = rx.match(line)
            if m and a <= sec(m.group(1)) <= b: acc.append([float(g) for g in m.groups()[1:]])
    t = [x[0] for x in tot]
    c = cpu.get(label, {})   # missing when the helper died mid-window
    rows[label] = dict(main_cpu=float(c.get('main_cpu_pct', 'nan')), helper_cpu=float(c.get('helper_cpu_pct', 'nan')),
        slow_frames_per_min=sum(1 for v in t if v > 25.0) / ((b - a) / 60.0),
        perf_mean=statistics.fmean(t) if t else float('nan'), perf_p95=p(t, 0.95),
        ui_mean=statistics.fmean(x[1] for x in ui) if ui else float('nan'), ui_p95=max((x[2] for x in ui), default=float('nan')),
        au_mean=statistics.fmean(x[1] for x in au) if au else float('nan'), au_p95=max((x[2] for x in au), default=float('nan')),
        gc_pauses=len(gcw), gc_max_ms=max((x[0] for x in gcw), default=0.0),
        gc2_runs=gcs[0] if gcs else float('nan'), gc2_max_ms=gcs[2] if gcs else float('nan'))
cols = ['main_cpu', 'helper_cpu', 'slow_frames_per_min', 'perf_mean', 'perf_p95', 'ui_mean', 'ui_p95', 'au_mean', 'au_p95', 'gc_pauses', 'gc_max_ms', 'gc2_runs', 'gc2_max_ms']
print('%-6s' % 'run' + ''.join('%20s' % c for c in cols))
for l, r in rows.items(): print('%-6s' % l + ''.join('%20.2f' % r[c] for c in cols))
def avg(prefix): 
    xs = [r for l, r in rows.items() if l.startswith(prefix)]
    return {c: statistics.fmean([r[c] for r in xs if r[c] == r[c]] or [float('nan')]) for c in cols} if xs else None
g, f = avg('gil'), avg('ft')
if g and f:
    print('\nfree-threaded vs GIL (mean of rounds; + = free-threaded is higher/slower):')
    for c in cols: print('  %-20s GIL %8.2f  FT %8.2f  diff %+7.1f%%' % (c, g[c], f[c], 100 * (f[c] - g[c]) / g[c] if g[c] else float('nan')))
