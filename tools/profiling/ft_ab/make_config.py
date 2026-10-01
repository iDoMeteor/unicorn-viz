"""Write the A/B run config: the checkout's config.toml with logging, mixer and
Auto VJ settings pinned and its own isolated runtime store.

    python tools/profiling/ft_ab/make_config.py [AB_DIR]    # default /var/tmp/uv-ab

Never touches the checkout's config.toml or runtime/: the copy lives in AB_DIR
and ``[runtime_state] path`` points the app's menu store there, seeded with
``perf_perf_frames`` so the main loop writes ``Perf frame:`` lines.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AB = Path(sys.argv[1] if len(sys.argv) > 1 else '/var/tmp/uv-ab')

EDITS = {
    'logging': {'level': '"debug"', 'perf_frames': 'true'},
    'dj_mixer': {'start_enabled': 'true'},       # opens the mixer window + engine
    'auto_vj': {'enabled': 'false'},             # keep the scene identical between runs
}
APPEND = {                                       # keys that may be absent from config.toml
    'ui': {'confirm_exit': 'false'},             # SIGTERM must exit, not open a dialog
}


def _sub(line: str, key: str, val: str) -> str:
    return re.sub(rf'^(\s*{key}\s*=\s*)[^#\n]*?(\s*(#.*)?)$',
                  lambda m: f'{m.group(1)}{val}{m.group(2)}', line)


def main() -> None:
    lines = (ROOT / 'config.toml').read_text(encoding='utf-8').split('\n')
    out: list[str] = []
    section = ''
    seen: dict[str, set[str]] = {}
    for line in lines:
        m = re.match(r'^\[([^\]]+)\]', line)
        if m:
            section = m.group(1)
        for key, val in {**EDITS.get(section, {}), **APPEND.get(section, {})}.items():
            new = _sub(line, key, val)
            if new != line or re.match(rf'^\s*{key}\s*=', line):
                seen.setdefault(section, set()).add(key)
                line = new
        out.append(line)
    text = '\n'.join(out)
    for section, keys in APPEND.items():
        missing = {k: v for k, v in keys.items() if k not in seen.get(section, set())}
        if not missing:
            continue
        body = ''.join(f'{k} = {v}\n' for k, v in missing.items())
        if re.search(rf'^\[{section}\]', text, re.M):
            text = re.sub(rf'^(\[{section}\]\n)', lambda m: m.group(1) + body, text, count=1, flags=re.M)
        else:
            text += f'\n[{section}]\n{body}'
    text = re.sub(r'^\[runtime_state\][^\[]*', '', text, flags=re.M)
    text += f'\n[runtime_state]\npath = "{AB}/state/global_state.json"\n'
    AB.mkdir(parents=True, exist_ok=True)
    (AB / 'state').mkdir(exist_ok=True)
    (AB / 'state' / 'global_state.json').write_text('{"perf_perf_frames": true}\n')
    (AB / 'config.toml').write_text(text, encoding='utf-8')
    print(f'wrote {AB}/config.toml')


main()
