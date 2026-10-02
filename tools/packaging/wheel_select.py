#!/usr/bin/env python3
"""Pick the newest build of each wheel from a list of wheel file names.

Our wheelhouse is append-only, so it holds every build we ever published:
``glcontext-3.0.0-cp314-...whl``, then ``glcontext-3.0.0-2-cp314-...whl`` once it
was patched. pip would choose the highest build tag on its own, but staging both
into a payload doubles the size for nothing (OpenCV is 44 MB). This keeps one
wheel per (distribution, platform): the highest version, then the highest build
tag (PEP 427: the optional third field, a number optionally followed by letters;
no tag counts as 0).

Reads file names (one per line) on stdin and prints the ones to keep, in input
order.  Standard library only; used by stage_payload.sh and fetch_wheelhouse.sh.
"""
from __future__ import annotations

import re
import sys


def _key(name: str) -> tuple[str, str, tuple[int, ...], int] | None:
    parts = name.removesuffix('.whl').split('-')
    if len(parts) == 5:
        dist, version, _py, _abi, plat = parts
        build = ''
    elif len(parts) == 6:
        dist, version, build, _py, _abi, plat = parts
    else:
        return None
    platform = 'windows' if 'win' in plat else 'linux' if 'linux' in plat else plat
    ver = tuple(int(x) for x in re.findall(r'\d+', version))
    m = re.match(r'\d+', build)
    return dist.lower().replace('_', '-'), platform, ver, int(m.group()) if m else 0


def select(names: list[str]) -> list[str]:
    best: dict[tuple[str, str], tuple[tuple[int, ...], int, str]] = {}
    for name in names:
        k = _key(name)
        if k is None:
            continue
        dist, platform, ver, build = k
        cur = best.get((dist, platform))
        if cur is None or (ver, build) > (cur[0], cur[1]):
            best[(dist, platform)] = (ver, build, name)
    keep = {v[2] for v in best.values()}
    return [n for n in names if n in keep or _key(n) is None]


if __name__ == '__main__':
    for kept in select([ln.strip() for ln in sys.stdin if ln.strip()]):
        print(kept)
