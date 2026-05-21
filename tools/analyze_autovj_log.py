#!/usr/bin/env python3
"""Summarize Auto VJ JSONL logs for mode/detector analysis.

Usage:
  python tools/analyze_autovj_log.py                # latest log
  python tools/analyze_autovj_log.py path/to/log    # specific log
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


def _load_entries(path: Path) -> list[dict]:
    entries: list[dict] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _pick_path(argv: list[str]) -> Path:
    if len(argv) > 1:
        return Path(argv[1])
    logs = sorted(Path('logs').glob('autovj-*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        raise FileNotFoundError('No logs/autovj-*.jsonl files found')
    return logs[0]


def main(argv: list[str]) -> int:
    try:
        path = _pick_path(argv)
    except FileNotFoundError as exc:
        print(str(exc))
        return 1

    entries = _load_entries(path)
    if not entries:
        print(f'No parseable JSONL entries in {path}')
        return 1

    by_action = Counter(e.get('action', '?') for e in entries)
    mode_transitions = [e for e in entries if e.get('action') == 'mode_transition']
    detector_ticks = [e for e in entries if e.get('action') == 'detector_tick']

    print(f'Log: {path}')
    print(f'Entries: {len(entries)}')
    print('Actions:')
    for action, n in by_action.most_common():
        print(f'  {action}: {n}')

    if mode_transitions:
        to_mode = Counter(e.get('to_mode', '?') for e in mode_transitions)
        print('Mode transitions (to_mode):')
        for mode, n in to_mode.most_common():
            print(f'  {mode}: {n}')

        sorted_mt = sorted(mode_transitions, key=lambda e: float(e.get('t', 0.0) or 0.0))
        bursts = 0
        for i, row in enumerate(sorted_mt):
            t0 = float(row.get('t', 0.0) or 0.0)
            j = i + 1
            while j < len(sorted_mt) and float(sorted_mt[j].get('t', 0.0) or 0.0) - t0 <= 2.0:
                j += 1
            if j - i >= 3:
                bursts += 1
        print(f'Transition bursts (>=3 transitions within 2s windows): {bursts}')

    if detector_ticks:
        def p90(vals: list[float]) -> float:
            if not vals:
                return 0.0
            if len(vals) < 2:
                return float(vals[0])
            return float(statistics.quantiles(vals, n=10)[8])

        by_mode = defaultdict(list)
        for e in detector_ticks:
            by_mode[str(e.get('mode', '?'))].append(e)

        print('Detector snapshots by mode:')
        for mode, rows in sorted(by_mode.items(), key=lambda kv: len(kv[1]), reverse=True):
            drop_scores = [float(r.get('drop_score', 0.0) or 0.0) for r in rows]
            slopes = [float(r.get('energy_slope', 0.0) or 0.0) for r in rows]
            energies = [float(r.get('energy', 0.0) or 0.0) for r in rows]
            bpms = [float(r.get('bpm', 0.0) or 0.0) for r in rows if float(r.get('bpm', 0.0) or 0.0) > 0.0]
            print(
                f"  {mode}: n={len(rows)} "
                f"drop_score p50={statistics.median(drop_scores):.3f} p90={p90(drop_scores):.3f} "
                f"energy p50={statistics.median(energies):.3f} slope p50={statistics.median(slopes):.3f} "
                f"bpm_med={(statistics.median(bpms) if bpms else 0.0):.1f}"
            )

        bass = [float(r.get('bass', 0.0) or 0.0) for r in detector_ticks]
        mid = [float(r.get('mid', 0.0) or 0.0) for r in detector_ticks]
        treble = [float(r.get('treble', 0.0) or 0.0) for r in detector_ticks]
        if bass and mid and treble:
            q90_b = p90(bass)
            q90_m = p90(mid)
            q90_t = p90(treble)
            print('Band distribution (all detector ticks):')
            print(
                f"  bass p50={statistics.median(bass):.3f} p90={q90_b:.3f} | "
                f"mid p50={statistics.median(mid):.3f} p90={q90_m:.3f} | "
                f"treble p50={statistics.median(treble):.3f} p90={q90_t:.3f}"
            )

    # Quick misses: high drop score in BUILD without DROP transition soon after.
    if detector_ticks and mode_transitions:
        trans_times = [float(e.get('t', 0.0) or 0.0) for e in mode_transitions if e.get('to_mode') == 'DROP']
        miss = 0
        for e in detector_ticks:
            if e.get('mode') != 'BUILD':
                continue
            t = float(e.get('t', 0.0) or 0.0)
            score = float(e.get('drop_score', 0.0) or 0.0)
            if score < 0.75:
                continue
            if not any(0.0 <= tt - t <= 1.5 for tt in trans_times):
                miss += 1
        print(f'Potential missed drop windows (BUILD score>=0.75, no DROP within 1.5s): {miss}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
