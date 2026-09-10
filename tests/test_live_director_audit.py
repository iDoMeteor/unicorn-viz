"""live_director_audit: a synthetic line-input corpus with mode transitions placed
exactly on energy steps must score them as landed and on-beat; the same corpus
with transitions placed at random must score near chance."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_TOOL = Path(__file__).resolve().parents[1] / 'drop-ins' / 'training-kit-01' / 'tools' / 'live_director_audit.py'
_SPEC = importlib.util.spec_from_file_location('test_live_director_audit_tool', _TOOL)
assert _SPEC is not None and _SPEC.loader is not None
_LDA = importlib.util.module_from_spec(_SPEC)
sys.modules['test_live_director_audit_tool'] = _LDA
_SPEC.loader.exec_module(_LDA)


def _corpus(tmp_path: Path, bpm: float = 120.0, seconds: int = 600) -> tuple[Path, list[dict]]:
    """One pseudo-track: energy steps up at 200 s (a build) and down at 400 s (a breakdown)."""
    rows = []
    dt = 0.5
    n = int(seconds / dt)
    beat_s = 60.0 / bpm
    for i in range(n):
        t = i * dt
        energy = 1.0 + (0.5 if 200 <= t < 400 else 0.0)
        mode = 'CRUISE'
        if 200 <= t < 400:
            mode = 'BUILD'
        elif t >= 400:
            mode = 'BREAKDOWN'
        rows.append({'capture_time': 1000.0 + t, 'bpm': bpm, 'energy': energy, 'bass': energy,
                     'beat_phase': (t / beat_s) % 1.0, 'vj_mode': mode})
    path = tmp_path / 'sequence-corpus-test.jsonl'
    path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
    return path, rows


def test_transitions_on_energy_steps_land(tmp_path: Path) -> None:
    path, _ = _corpus(tmp_path)
    rows = _LDA.load_heartbeats(path)
    result = _LDA.audit_rows(rows, seed=7)
    totals = result['totals']
    assert totals['BUILD']['n'] == 1 and totals['BUILD']['landed'] == 1
    assert totals['BREAKDOWN']['n'] == 1 and totals['BREAKDOWN']['landed'] == 1
    # chance on a mostly-flat track is well below the real rate
    assert totals['BUILD']['chance'] / totals['BUILD']['chance_n'] < 0.5


def test_random_transitions_score_near_chance(tmp_path: Path) -> None:
    path, rows = _corpus(tmp_path)
    # scramble the modes so transitions fall at arbitrary times
    import random
    rng = random.Random(3)
    for r in rows:
        r['vj_mode'] = rng.choice(['CRUISE', 'BUILD', 'BREAKDOWN', 'DROP'])
    path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
    result = _LDA.audit_rows(_LDA.load_heartbeats(path), seed=7)
    build = result['totals']['BUILD']
    rate = build['landed'] / build['n']
    chance = build['chance'] / build['chance_n']
    assert abs(rate - chance) < 0.15


def test_skips_event_rows_and_bad_lines(tmp_path: Path) -> None:
    path, rows = _corpus(tmp_path, seconds=120)
    with open(path, 'a', encoding='utf-8') as fh:
        fh.write('not json\n')
        fh.write(json.dumps({'event_type': 'drop_fire', 'capture_time': 1500.0}) + '\n')
    assert len(_LDA.load_heartbeats(path)) == len(rows)
