#!/usr/bin/env python3
from __future__ import annotations

"""Audit ping-pong friend registrations for all discovered effects.

Prints a summary and Markdown tables for core and drop-in effects.
Rows include friend-group size classification, eligibility for Auto VJ
ping-pong selection, and any invalid friend references.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from unicornviz.effects.registry import get_effects


@dataclass(slots=True)
class EffectRow:
    effect: str
    module: str
    valid_friends: list[str]
    invalid_friends: list[str]
    group: str
    eligible: str


def _group_label(valid_count: int) -> str:
    if valid_count <= 0:
        return 'none'
    if valid_count == 1:
        return 'pair'
    return 'trio+'


def _build_rows() -> tuple[list[EffectRow], list[EffectRow]]:
    classes = sorted(get_effects(), key=lambda cls: cls.NAME.lower())
    by_name = {cls.NAME: cls for cls in classes}
    core: list[EffectRow] = []
    dropins: list[EffectRow] = []

    for cls in classes:
        raw_friends = [
            str(name)
            for name in (getattr(cls, 'PING_PONG_FRIENDS', []) or [])
            if isinstance(name, str)
        ]
        valid_friends = [
            name for name in raw_friends if name in by_name and name != cls.NAME
        ]
        invalid_friends = [
            name for name in raw_friends if name not in by_name or name == cls.NAME
        ]
        row = EffectRow(
            effect=cls.NAME,
            module=cls.__module__,
            valid_friends=valid_friends,
            invalid_friends=invalid_friends,
            group=_group_label(len(valid_friends)),
            eligible='yes' if valid_friends else 'no',
        )
        if cls.__module__.startswith('unicornviz_dropins_'):
            dropins.append(row)
        else:
            core.append(row)

    return core, dropins


def _print_table(title: str, rows: list[EffectRow]) -> None:
    print(title)
    print('| Effect | Pair/Trio | Eligible | Valid friends | Invalid refs |')
    print('|---|---|---|---|---|')
    for row in rows:
        valid = ', '.join(row.valid_friends) if row.valid_friends else '-'
        invalid = ', '.join(row.invalid_friends) if row.invalid_friends else '-'
        print(f'| {row.effect} | {row.group} | {row.eligible} | {valid} | {invalid} |')
    print('')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--only',
        choices=('core', 'dropins', 'all'),
        default='all',
        help='Limit output to core effects, drop-ins, or all (default).',
    )
    args = parser.parse_args()

    core_rows, dropin_rows = _build_rows()
    all_rows = core_rows + dropin_rows

    print(
        'Summary: '
        f'total={len(all_rows)} core={len(core_rows)} '
        f'dropins={len(dropin_rows)} '
        f'eligible={sum(1 for row in all_rows if row.eligible == "yes")}'
    )
    print('')

    if args.only in ('all', 'core'):
        _print_table('Core Effects', core_rows)
    if args.only in ('all', 'dropins'):
        _print_table('Drop-in Effects', dropin_rows)

    invalid_rows = [row for row in all_rows if row.invalid_friends]
    print('Invalid Friend References')
    if not invalid_rows:
        print('- none')
    else:
        for row in invalid_rows:
            print(f'- {row.effect}: {", ".join(row.invalid_friends)}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
