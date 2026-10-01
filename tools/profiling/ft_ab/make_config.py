"""Write the A/B run config: the checkout's config.toml with logging, mixer and
Auto VJ settings pinned and its own isolated runtime store.

    python tools/profiling/ft_ab/make_config.py [AB_DIR] [--loaded]    # AB_DIR default /var/tmp/uv-ab

``--loaded`` also seeds THIS checkout's ``runtime/`` (run it from a seat, never
the owner's main checkout) with a copy of the owner's mixer state so both decks
come up loaded with autoplay on: ``dj_mixer_state.json`` (master gain forced to
0, so the run is silent), ``dj_mixer_tracks.json``, ``dj_mixer_sets.json`` and
the cached stems of the two deck tracks, plus a one-track-pair set 'ab_loaded' that boot autoplay plays
(``autoplay_boot_mode``): deck A plays with stems split, as in a real set.  The owner's files are only read
(``AB_OWNER_ROOT``, default ``~/Repos/unicorn-viz``).

Never touches the checkout's config.toml or runtime/: the copy lives in AB_DIR
and ``[runtime_state] path`` points the app's menu store there, seeded with
``perf_perf_frames`` so the main loop writes ``Perf frame:`` lines.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
LOADED = '--loaded' in sys.argv[1:]
AB = Path(_ARGS[0] if _ARGS else '/var/tmp/uv-ab')
OWNER = Path(os.environ.get('AB_OWNER_ROOT', Path.home() / 'Repos' / 'unicorn-viz'))

EDITS = {
    'logging': {'level': '"debug"', 'perf_frames': 'true'},
    'dj_mixer': {'start_enabled': 'true'},       # opens the mixer window + engine
    'auto_vj': {'enabled': 'false'},             # keep the scene identical between runs
}
APPEND = {                                       # keys that may be absent from config.toml
    'ui': {'confirm_exit': 'false'},             # SIGTERM must exit, not open a dialog
}
if LOADED:
    APPEND['dj_mixer'] = {'autoplay_boot_mode': '"crossfade"', 'autoplay_boot_set': '"ab_loaded"',
                          'autoplay_boot_shuffle': 'false', 'autoplay_boot_delay_s': '3.0'}


def _sub(line: str, key: str, val: str) -> str:
    return re.sub(rf'^(\s*{key}\s*=\s*)[^#\n]*?(\s*(#.*)?)$',
                  lambda m: f'{m.group(1)}{val}{m.group(2)}', line)


def seed_mixer() -> None:
    """Copy the owner's mixer state into this checkout's runtime/ (read-only on theirs).

    Deck A starts ``AB_A_FROM_END`` seconds (default 70) before its end so
    AutoPlay's mix into deck B, the heaviest moment (two decks, stem blend),
    falls inside the measured window.  A deck whose track has cached stems
    under a different crate path is pointed at the copy that has them.
    """
    src, dst = OWNER / 'runtime', ROOT / 'runtime'
    if src.resolve() == dst.resolve():
        sys.exit('refusing to seed the owner\'s own runtime/: run from a seat checkout')
    dst.mkdir(exist_ok=True)
    state = json.loads((src / 'dj_mixer_state.json').read_text(encoding='utf-8'))
    state['master_gain'] = 0.0                       # silent: the engine still renders
    stems_by_name: dict[str, tuple[Path, str]] = {}
    for manifest in (src / 'stems').glob('*/manifest.json'):
        source = json.loads(manifest.read_text(encoding='utf-8', errors='replace')).get('source', '')
        if source:
            stems_by_name[Path(source).name] = (manifest.parent, source)
    for name, deck in state.get('decks', {}).items():
        path = deck.get('track_path')
        hit = stems_by_name.get(Path(path).name) if path else None
        if hit and Path(hit[1]).is_file():
            deck['track_path'] = hit[1]
            target = dst / 'stems' / hit[0].name
            if not target.exists():
                shutil.copytree(hit[0], target)
    tracks_file = src / 'dj_mixer_tracks.json'
    store = json.loads(tracks_file.read_text(encoding='utf-8')) if tracks_file.is_file() else {}
    deck_a = state.get('decks', {}).get('a', {})
    info = store.get('paths', {}).get(deck_a.get('track_path', ''))
    rec = store.get('tracks', {}).get(info['hash']) if info else None
    if rec and rec.get('duration_s'):
        deck_a['position'] = max(0.0, float(rec['duration_s']) - float(os.environ.get('AB_A_FROM_END', 70)))
    (dst / 'dj_mixer_state.json').write_text(json.dumps(state), encoding='utf-8')
    for name in ('dj_mixer_tracks.json', 'dj_mixer_sets.json'):
        if (src / name).is_file():
            shutil.copy2(src / name, dst / name)
    sets_file = dst / 'dj_mixer_sets.json'
    sets = json.loads(sets_file.read_text(encoding='utf-8')) if sets_file.is_file() else {'_meta': {}, 'sets': {}}
    sets.setdefault('sets', {})['ab_loaded'] = [d['track_path'] for k, d in state.get('decks', {}).items() if d.get('track_path') and k in ('a', 'b')]
    sets_file.write_text(json.dumps(sets), encoding='utf-8')
    print(f'seeded {dst}: A={deck_a.get("track_path")} @ {deck_a.get("position")} s, '
          f'B={state.get("decks", {}).get("b", {}).get("track_path")}; master_gain 0')


def main() -> None:
    if LOADED:
        seed_mixer()
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
