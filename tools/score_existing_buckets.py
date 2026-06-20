"""Retroactive LLM detector scoring backfill for pre-existing training buckets.

Temp script — run from the project root after pulling the latest tools/.
Processes the six buckets that predate the LLM scoring feature.

Usage:
    python tools/score_existing_buckets.py
    python tools/score_existing_buckets.py --force-regen
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')

# ---------------------------------------------------------------------------
# Bootstrap: load packager functions without adding to sys.modules
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parents[1]
_PKG_PATH = _ROOT / 'tools' / 'package_training_set.py'
_spec = importlib.util.spec_from_file_location('_pkg', _PKG_PATH)
assert _spec is not None and _spec.loader is not None
_pkg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pkg)  # type: ignore[union-attr]

_load_jsonl_rows = _pkg._load_jsonl_rows
_score_detector_with_llm = _pkg._score_detector_with_llm
_pick_latest = _pkg._pick_latest

# ---------------------------------------------------------------------------
# Hardcoded buckets: all classic-house sessions (a–e) plus chillstep/a.
# chillstep/b is currently running — exclude it.
# ---------------------------------------------------------------------------
_SETS_ROOT = _ROOT / 'assets' / 'training' / 'sets'

_BUCKETS: list[tuple[str, str]] = [
    ('20260619-classic-house-2025-2026', 'a'),
    ('20260619-classic-house-2025-2026', 'b'),
    ('20260619-classic-house-2025-2026', 'c'),
    ('20260619-classic-house-2025-2026', 'd'),
    ('20260619-classic-house-2025-2026', 'e'),
    ('20260620-45-minute-chillstep-mix', 'a'),
]


def _load_set_description(set_dir: Path) -> str | None:
    p = set_dir / 'TRAINING_SET_DESCRIPTION.md'
    return p.read_text(encoding='utf-8') if p.is_file() else None


def main() -> int:
    force_regen = '--force-regen' in sys.argv
    if force_regen:
        print('Force-regen mode: overwriting any existing detector_score.json files.')

    outcomes: list[tuple[str, str]] = []

    for set_name, bucket_name in _BUCKETS:
        label = f'{set_name}/{bucket_name}'
        set_dir = _SETS_ROOT / set_name
        bucket_dir = set_dir / bucket_name

        if not bucket_dir.is_dir():
            print(f'[SKIP]  {label}: directory not found')
            outcomes.append((label, 'not found'))
            continue

        seq_path = _pick_latest(bucket_dir, ['sequence-corpus*.jsonl', 'sequence*.jsonl'])
        if seq_path is None:
            print(f'[SKIP]  {label}: no sequence corpus file found')
            outcomes.append((label, 'no corpus'))
            continue

        seq_rows = _load_jsonl_rows(seq_path)
        set_description = _load_set_description(set_dir)

        print(f'[SCORE] {label}: {len(seq_rows)} sequence rows ...', flush=True)
        result = _score_detector_with_llm(
            bucket_dir=bucket_dir,
            seq_rows=seq_rows,
            set_id=set_name,
            bucket_id=bucket_name,
            set_description=set_description,
            skip=False,
            force_regen=force_regen,
        )

        if result is not None:
            print(f'        -> {result}')
            outcomes.append((label, 'scored'))
        else:
            print(f'        -> skipped or failed (see warnings above)')
            outcomes.append((label, 'skipped/failed'))

    print()
    print('=' * 60)
    print('Summary')
    print('=' * 60)
    for label, outcome in outcomes:
        status = 'OK ' if outcome == 'scored' else '-- '
        print(f'  {status} {label}: {outcome}')

    scored = sum(1 for _, o in outcomes if o == 'scored')
    print(f'\n{scored}/{len(outcomes)} buckets scored.')
    return 0 if scored == len(outcomes) else 1


if __name__ == '__main__':
    raise SystemExit(main())
