"""Package current training corpus and session logs into a set bucket.

Run from project root without arguments to use interactive prompts.
"""

from __future__ import annotations

import argparse
import datetime
import json
import shutil
from collections import Counter
from pathlib import Path
from statistics import median


def _prompt_yes_no(question: str) -> bool:
    while True:
        raw = input(f'{question} [y/n]: ').strip().lower()
        if raw in {'y', 'yes'}:
            return True
        if raw in {'n', 'no'}:
            return False
        print('Please answer y or n.')


def _prompt_set_name() -> str:
    while True:
        raw = input('New set directory name: ').strip()
        if not raw:
            print('Directory name cannot be empty.')
            continue
        if '/' in raw or '\\' in raw or raw in {'.', '..'}:
            print('Use a simple directory name without path separators.')
            continue
        return raw


def _prompt_optional_text(question: str) -> str:
    return input(f'{question}: ').strip()


def _latest_set_dir(sets_root: Path) -> Path | None:
    dirs = [p for p in sets_root.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime)


def _bucket_name(index: int) -> str:
    # a..z, aa..az, ba...
    chars: list[str] = []
    value = index
    while True:
        value, rem = divmod(value, 26)
        chars.append(chr(ord('a') + rem))
        if value == 0:
            break
        value -= 1
    return ''.join(reversed(chars))


def _next_bucket_dir(set_dir: Path) -> Path:
    existing = {p.name for p in set_dir.iterdir() if p.is_dir()}
    i = 0
    while True:
        candidate = _bucket_name(i)
        if candidate not in existing:
            return set_dir / candidate
        i += 1


def _pick_latest(corpus_dir: Path, patterns: list[str]) -> Path | None:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(corpus_dir.glob(pattern))
    files = [p for p in matches if p.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _move_file(src: Path, dest_dir: Path) -> Path:
    dest = dest_dir / src.name
    if dest.exists():
        raise FileExistsError(f'destination already exists: {dest}')
    shutil.move(str(src), str(dest))
    return dest


def _load_jsonl_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open('r', encoding='utf-8') as handle:
        for line in handle:
            payload = line.strip()
            if not payload:
                continue
            try:
                item = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


def _safe_median(values: list[float]) -> float | None:
    return float(median(values)) if values else None


def _parse_ts(ts: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(ts)
    except Exception:
        return None


def _score_lock_quality(beat_lock_pct: float, bpm_conf_med: float | None) -> int:
    conf = bpm_conf_med if bpm_conf_med is not None else 0.0
    if beat_lock_pct >= 70.0 and conf >= 0.60:
        return 5
    if beat_lock_pct >= 45.0 and conf >= 0.45:
        return 4
    if beat_lock_pct >= 25.0 and conf >= 0.30:
        return 3
    if beat_lock_pct >= 10.0:
        return 2
    return 1


def _score_director_quality(mode_transitions: int, drop_fires: int, impact_fires: int) -> int:
    activity = mode_transitions + drop_fires + impact_fires
    if activity >= 260:
        return 5
    if activity >= 140:
        return 4
    if activity >= 70:
        return 3
    if activity >= 25:
        return 2
    return 1


def _infer_style_tag(set_dir: Path) -> str:
    parts = set_dir.name.split('-')
    if parts and parts[0].isdigit() and len(parts[0]) == 8:
        parts = parts[1:]
    return ' '.join(parts) if parts else set_dir.name


def _append_session_log(
    training_root: Path,
    set_dir: Path,
    bucket_dir: Path,
    session_date: str,
    lock_rating: int,
    director_rating: int,
    notes: str,
) -> Path:
    session_log_path = training_root / 'SESSION_TRAINING_LOG.md'
    style_tag = _infer_style_tag(set_dir)
    note_text = notes if notes else 'auto-generated packaging entry'
    entry = (
        f'{session_date} | session={set_dir.name}/{bucket_dir.name} '
        f'| style={style_tag} | lock={lock_rating}/5 '
        f'| director={director_rating}/5 | notes={note_text}'
    )
    with session_log_path.open('a', encoding='utf-8') as handle:
        if session_log_path.stat().st_size > 0:
            handle.write('\n')
        handle.write(entry)
    return session_log_path


def _write_scorecard(bucket_dir: Path, live_path: Path, seq_path: Path) -> tuple[Path, int, int]:
    seq_rows = _load_jsonl_rows(seq_path)
    live_rows = _load_jsonl_rows(live_path)

    times = [r.get('analysis_generated_at') for r in seq_rows if isinstance(r.get('analysis_generated_at'), str)]
    start = min(times) if times else None
    end = max(times) if times else None
    duration_min: float | None = None
    if start and end:
        start_dt = _parse_ts(start)
        end_dt = _parse_ts(end)
        if start_dt and end_dt:
            duration_min = (end_dt - start_dt).total_seconds() / 60.0

    bpm_values = [float(v) for v in (r.get('bpm') for r in seq_rows) if isinstance(v, (int, float))]
    conf_values = [float(v) for v in (r.get('bpm_confidence') for r in seq_rows) if isinstance(v, (int, float))]
    beat_locked = sum(1 for r in seq_rows if isinstance(r.get('beat_index'), int) and int(r.get('beat_index')) >= 0)
    beat_lock_pct = (100.0 * beat_locked / len(seq_rows)) if seq_rows else 0.0

    events = Counter(r.get('event_type') for r in seq_rows if r.get('event_type'))
    profiles = Counter(r.get('audio_profile_key') for r in seq_rows if r.get('audio_profile_key'))

    mode_transitions = int(events.get('mode_transition', 0))
    drop_fires = int(events.get('drop_fire', 0))
    impact_fires = int(events.get('impact_fire', 0))
    lock_rating = _score_lock_quality(beat_lock_pct, _safe_median(conf_values))
    director_rating = _score_director_quality(mode_transitions, drop_fires, impact_fires)

    profile_lines = ['- `n/a`: `0`']
    if profiles:
        profile_lines = [f'- `{key}`: `{count}`' for key, count in profiles.most_common(6)]

    lines = [
        '# Auto VJ Training Scorecard',
        '',
        'Owner: auto-generated by tools/package_training_set.py',
        'Status: generated',
        f'Last updated: {datetime.date.today().isoformat()}',
        '',
        '## Session',
        '',
        f'- Set: `{bucket_dir.parent.name}`',
        f'- Bucket: `{bucket_dir.name}`',
        '',
        '## Data Snapshot',
        '',
        f'- Sequence rows: `{len(seq_rows)}`',
        f'- Live rows: `{len(live_rows)}`',
        f'- Start: `{start or "n/a"}`',
        f'- End: `{end or "n/a"}`',
        f'- Duration: `{duration_min:.2f} min`' if duration_min is not None else '- Duration: `n/a`',
        '',
        '## Detector / Rhythm',
        '',
        f'- BPM median: `{_safe_median(bpm_values):.3f}`' if _safe_median(bpm_values) is not None else '- BPM median: `n/a`',
        f'- BPM range: `{min(bpm_values):.3f} .. {max(bpm_values):.3f}`' if bpm_values else '- BPM range: `n/a`',
        f'- BPM confidence median: `{_safe_median(conf_values):.3f}`' if _safe_median(conf_values) is not None else '- BPM confidence median: `n/a`',
        f'- Beat lock index coverage (`beat_index >= 0`): `{beat_lock_pct:.1f}%`',
        f'- Lock event churn: `{int(events.get("bpm_lock_gained", 0))} lock gained`, `{int(events.get("bpm_lock_lost", 0))} lock lost`',
        '',
        '## Director Activity',
        '',
        f'- Mode transitions: `{mode_transitions}`',
        f'- Drop fires: `{drop_fires}`',
        f'- Impact fires: `{impact_fires}`',
        f'- Profile switches: `{int(events.get("profile_switch", 0))}`',
        '',
        '## Profile Mix',
        '',
        *profile_lines,
        '',
        '## Ratings',
        '',
        f'- Lock quality: `{lock_rating}/5`',
        f'- Director quality: `{director_rating}/5`',
        '',
        '## Notes',
        '',
        '- This scorecard is auto-generated for consistency checks.',
        '- Add human review notes below for style-fit and subjective quality.',
    ]
    scorecard_path = bucket_dir / 'scorecard.md'
    scorecard_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return scorecard_path, lock_rating, director_rating


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--set-name',
        help='Optional set directory name under assets/training/sets.',
    )
    parser.add_argument(
        '--no-prompt',
        action='store_true',
        help='Disable prompts; requires --set-name when no set exists.',
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    root = Path(__file__).resolve().parents[1]
    training_root = root / 'assets' / 'training'
    sets_root = training_root / 'sets'
    corpus_dir = training_root / 'corpus'
    logs_dir = root / 'logs'

    sets_root.mkdir(parents=True, exist_ok=True)

    create_new = False
    set_name = args.set_name
    if set_name:
        create_new = True
    elif not args.no_prompt:
        create_new = _prompt_yes_no('Create a new set directory?')
        if create_new:
            set_name = _prompt_set_name()

    if create_new:
        assert set_name is not None
        set_dir = sets_root / set_name
        set_dir.mkdir(parents=True, exist_ok=True)
    else:
        set_dir = _latest_set_dir(sets_root)
        if set_dir is None:
            print('No set directory exists yet. Re-run and create one first.')
            return 1

    bucket_dir = _next_bucket_dir(set_dir)
    bucket_dir.mkdir(parents=True, exist_ok=False)

    live_src = _pick_latest(corpus_dir, ['live-corpus*.jsonl', 'live-autovj*.jsonl', 'live*.jsonl'])
    seq_src = _pick_latest(corpus_dir, ['sequence-corpus*.jsonl', 'sequence*.jsonl'])
    if live_src is None or seq_src is None:
        print('Could not find both live and sequence corpus files in assets/training/corpus.')
        return 1

    moved: list[Path] = []
    moved_live = _move_file(live_src, bucket_dir)
    moved_seq = _move_file(seq_src, bucket_dir)
    moved.append(moved_live)
    moved.append(moved_seq)

    session_logs = sorted([p for p in logs_dir.rglob('*') if p.is_file()], key=lambda p: p.stat().st_mtime)
    for log_path in session_logs:
        rel = log_path.relative_to(logs_dir).as_posix()
        dest_name = rel.replace('/', '__')
        dest = bucket_dir / dest_name
        if dest.exists():
            raise FileExistsError(f'destination already exists: {dest}')
        shutil.move(str(log_path), str(dest))
        moved.append(dest)

    scorecard_path, lock_rating, director_rating = _write_scorecard(
        bucket_dir,
        moved_live,
        moved_seq,
    )
    session_date = datetime.date.today().isoformat()
    session_notes = ''
    if not args.no_prompt:
        session_notes = _prompt_optional_text('Session notes for the training log (optional)')
    session_log_path = _append_session_log(
        training_root,
        set_dir,
        bucket_dir,
        session_date,
        lock_rating,
        director_rating,
        session_notes,
    )

    print(f'Set directory: {set_dir}')
    print(f'Bucket: {bucket_dir.name}')
    print(f'Scorecard: {scorecard_path}')
    print(f'Session log: {session_log_path}')
    print('Moved files:')
    for path in moved:
        print(f'  - {path}')
    if not session_logs:
        print('No logs/autovj-*.jsonl files were found to move.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())