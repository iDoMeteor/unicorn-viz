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

    if detector_ticks:
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
                f"drop_score p50={statistics.median(drop_scores):.3f} p90={statistics.quantiles(drop_scores, n=10)[8]:.3f} "
                f"energy p50={statistics.median(energies):.3f} slope p50={statistics.median(slopes):.3f} "
                f"bpm_med={(statistics.median(bpms) if bpms else 0.0):.1f}"
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
