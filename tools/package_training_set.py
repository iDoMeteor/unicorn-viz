"""Package current training corpus and session logs into a set bucket.

Run from project root without arguments to use interactive prompts.

LLM detector scoring runs automatically when OPENAI_API_KEY or
ANTHROPIC_API_KEY is set in the environment.  Use --skip-llm-scoring to
disable it or --force-regen-detector-score to overwrite an existing score.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import shutil
from collections import Counter
from pathlib import Path
from statistics import median

_LOG = logging.getLogger('package_training_set')

# Mirrors AutoVJController._BPM_LOCK_CONFIDENCE in auto_vj.py.
# A sequence row is considered "beat-locked" when bpm_confidence >= this floor.
_BPM_LOCK_CONFIDENCE_FLOOR = 0.45


def _prompt_yes_no(question: str) -> bool:
    while True:
        raw = input(f'{question} [y/n]: ').strip().lower()
        if raw in {'y', 'yes'}:
            return True
        if raw in {'n', 'no'}:
            return False
        print('Please answer y or n.')


def _slugify_playlist_name(name: str) -> str:
    """Convert a human-readable playlist name to a filesystem-safe slug.

    "45 Minute Chillstep Mix" → "45-minute-chillstep-mix"
    """
    import re
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    return slug.strip('-')


def _prompt_playlist_name() -> str:
    """Prompt for a playlist name and return a slugified directory name."""
    while True:
        raw = input('Playlist name: ').strip()
        if not raw:
            print('Playlist name cannot be empty.')
            continue
        slug = _slugify_playlist_name(raw)
        if not slug:
            print('Could not derive a valid directory name from that input.')
            continue
        print(f'  → set directory: {slug}')
        return slug


def _infer_playlist_name_from_logs(logs_dir: Path) -> str | None:
    """Return a slugified set name inferred from autovj decision logs.

    Scans JSONL files under logs_dir for entries written by the engine when
    a Spotify playlist context is first resolved (action == 'playlist_context').
    Returns the most common playlist name found, slugified.  Returns None if
    no playlist_context entries are present.
    """
    counts: dict[str, int] = {}
    for log_path in sorted(logs_dir.rglob('*.jsonl')):
        try:
            with log_path.open('r', encoding='utf-8') as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    if entry.get('action') == 'playlist_context':
                        name = entry.get('name', '')
                        if name and isinstance(name, str):
                            name = name.strip()
                            if name:
                                counts[name] = counts.get(name, 0) + 1
        except Exception:
            continue
    if not counts:
        return None
    best = max(counts, key=lambda k: counts[k])
    return _slugify_playlist_name(best)


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
    detector_llm_score: float | None = None,
) -> Path:
    session_log_path = training_root / 'SESSION_TRAINING_LOG.md'
    style_tag = _infer_style_tag(set_dir)
    note_text = notes if notes else 'auto-generated packaging entry'
    llm_field = f' | detector_llm={detector_llm_score:.1f}/5' if detector_llm_score is not None else ''
    entry = (
        f'{session_date} | session={set_dir.name}/{bucket_dir.name} '
        f'| style={style_tag} | lock={lock_rating}/5 '
        f'| director={director_rating}/5{llm_field} | notes={note_text}'
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
    beat_locked = sum(
        1 for r in seq_rows
        if float(r.get('bpm_confidence', 0.0) or 0.0) >= _BPM_LOCK_CONFIDENCE_FLOOR
    )
    beat_lock_pct = (100.0 * beat_locked / len(seq_rows)) if seq_rows else 0.0

    events = Counter(r.get('event_type') for r in seq_rows if r.get('event_type'))
    audio_profiles = Counter(r.get('audio_profile_key') for r in seq_rows if r.get('audio_profile_key'))
    vj_profiles = Counter(r.get('vj_profile') for r in seq_rows if r.get('vj_profile'))

    mode_transitions = int(events.get('mode_transition', 0))
    drop_fires = int(events.get('drop_fire', 0))
    impact_fires = int(events.get('impact_fire', 0))
    lock_rating = _score_lock_quality(beat_lock_pct, _safe_median(conf_values))
    director_rating = _score_director_quality(mode_transitions, drop_fires, impact_fires)

    audio_profile_lines = ['- `n/a`: `0`']
    if audio_profiles:
        audio_profile_lines = [f'- `{key}`: `{count}`' for key, count in audio_profiles.most_common(6)]

    vj_profile_lines = ['- `n/a`: `0`']
    if vj_profiles:
        vj_profile_lines = [f'- `{key}`: `{count}`' for key, count in vj_profiles.most_common()]

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
        f'- Beat lock coverage (confidence ≥ {_BPM_LOCK_CONFIDENCE_FLOOR}): `{beat_lock_pct:.1f}%`',
        f'- Lock event churn: `{int(events.get("bpm_lock_gained", 0))} lock gained`, `{int(events.get("bpm_lock_lost", 0))} lock lost`',
        '',
        '## Director Activity',
        '',
        f'- Mode transitions: `{mode_transitions}`',
        f'- Drop fires: `{drop_fires}`',
        f'- Impact fires: `{impact_fires}`',
        f'- VJ profile switches: `{int(events.get("profile_switch", 0))}`',
        '',
        '## Audio Profile Mix',
        '',
        *audio_profile_lines,
        '',
        '## VJ Mood Profile Mix',
        '',
        *vj_profile_lines,
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


def _song_key(row: dict) -> str:
    tid = row.get('spotify_track_id')
    if tid:
        return f'id:{tid}'
    title = row.get('spotify_title', '')
    artist = row.get('spotify_artist', '')
    album = row.get('spotify_album', '')
    return f'meta:{title}|{artist}|{album}'


def _percentile(sorted_values: list[float], p: float) -> float | None:
    """Return the p-th percentile (0-100) of a pre-sorted list."""
    if not sorted_values:
        return None
    idx = p / 100.0 * (len(sorted_values) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _build_essentia_summary(per_song: list[dict]) -> dict | None:
    """Summarise Essentia reference BPMs across all songs with data."""
    deltas = [s['essentia_bpm_delta'] for s in per_song
              if s.get('essentia_bpm_delta') is not None]
    if not deltas:
        return None
    abs_deltas = [abs(d) for d in deltas]
    return {
        'songs_with_data': len(deltas),
        'mean_abs_delta_bpm': round(sum(abs_deltas) / len(abs_deltas), 3),
        'max_abs_delta_bpm': round(max(abs_deltas), 3),
        'within_2bpm_pct': round(100.0 * sum(1 for d in abs_deltas if d < 2.0) / len(abs_deltas), 1),
        'within_5bpm_pct': round(100.0 * sum(1 for d in abs_deltas if d < 5.0) / len(abs_deltas), 1),
    }


def _compute_duration_min(seq_rows: list[dict]) -> float | None:
    """Derive session duration in minutes from sequence corpus timestamps."""
    times = [
        r.get('analysis_generated_at')
        for r in seq_rows
        if isinstance(r.get('analysis_generated_at'), str)
    ]
    if len(times) < 2:
        return None
    start_dt = _parse_ts(min(times))
    end_dt = _parse_ts(max(times))
    if not start_dt or not end_dt:
        return None
    return (end_dt - start_dt).total_seconds() / 60.0


def _score_1_to_5(value: float, thresholds: list[float], *, higher_is_better: bool = True) -> int:
    """Map a metric to a 1-5 score against ordered thresholds (5 = best).

    Pass thresholds in any order; they are sorted internally by direction.
    """
    ordered = sorted(thresholds, reverse=higher_is_better)
    for score, threshold in zip(range(5, 0, -1), ordered):
        if higher_is_better and value >= threshold:
            return score
        if not higher_is_better and value <= threshold:
            return score
    return 1


def _extract_director_events(seq_rows: list[dict], max_events: int = 50) -> list[dict]:
    """Return a uniformly-sampled list of director keyframe events for LLM scoring."""
    wanted = {'mode_transition', 'drop_fire', 'impact_fire'}
    all_events = [r for r in seq_rows if r.get('event_type') in wanted]
    if len(all_events) > max_events:
        step = len(all_events) / max_events
        all_events = [all_events[int(i * step)] for i in range(max_events)]
    compact = []
    for r in all_events:
        evt = r.get('event_type', '')
        entry: dict = {
            'event_type': evt,
            't': r.get('analysis_generated_at', ''),
            'bpm_confidence': round(float(r['bpm_confidence']), 3)
            if isinstance(r.get('bpm_confidence'), (int, float)) else None,
            'danceability': round(float(r['danceability']), 3)
            if isinstance(r.get('danceability'), (int, float)) else None,
            'crest_factor': round(float(r['crest_factor']), 2)
            if isinstance(r.get('crest_factor'), (int, float)) else None,
            'rms': round(float(r['rms']), 4)
            if isinstance(r.get('rms'), (int, float)) else None,
        }
        if evt == 'mode_transition':
            entry['from_mode'] = r.get('mode', '')
            entry['to_mode'] = r.get('new_mode', r.get('vj_mode', ''))
            entry['reason'] = r.get('reason', '')
        else:
            entry['in_mode'] = r.get('mode', r.get('vj_mode', ''))
        # Strip falsy values for compactness
        entry = {k: v for k, v in entry.items() if v is not None and v != ''}
        compact.append(entry)
    return compact


def _build_director_payload(
    seq_rows: list[dict],
    duration_min: float | None,
    set_id: str,
    bucket_id: str,
) -> dict:
    """Build compact director scoring payload for the LLM."""
    all_events: Counter = Counter(r.get('event_type') for r in seq_rows if r.get('event_type'))
    hb_rows = [r for r in seq_rows if not r.get('event_type')]
    total_hb = len(hb_rows) or 1

    mode_counter: Counter = Counter()
    prof_counter: Counter = Counter()
    for r in hb_rows:
        mode = r.get('vj_mode') or r.get('mode', '')
        if mode:
            mode_counter[mode] += 1
        profile = r.get('vj_profile') or r.get('profile', '')
        if profile:
            prof_counter[profile] += 1

    mode_dist = {k: round(100.0 * v / total_hb, 1) for k, v in mode_counter.most_common()}
    return {
        'set_id': set_id,
        'bucket_id': bucket_id,
        'duration_min': round(duration_min, 1) if duration_min is not None else None,
        'stats': {
            'mode_transitions': int(all_events.get('mode_transition', 0)),
            'drop_fires': int(all_events.get('drop_fire', 0)),
            'impact_fires': int(all_events.get('impact_fire', 0)),
            'profile_switches': int(all_events.get('profile_switch', 0)),
            'mode_distribution_pct': mode_dist,
            'profile_distribution': dict(prof_counter.most_common()),
        },
        'events': _extract_director_events(seq_rows),
    }


def _compute_local_scores(seq_rows: list[dict], duration_min: float) -> dict:
    """Formula-based 1-5 scores for detector, recommender, and director subsystems.

    Quality dimensions for detector and director are left as None — filled by LLM.
    """
    duration_hr = max(duration_min / 60.0, 1.0 / 60.0)
    all_events: Counter = Counter(r.get('event_type') for r in seq_rows if r.get('event_type'))
    hb_rows = [r for r in seq_rows if not r.get('event_type')]
    total_hb = len(hb_rows) or 1

    # ── Detector ──────────────────────────────────────────────────────────────
    locked = sum(
        1 for r in hb_rows
        if float(r.get('bpm_confidence', 0.0) or 0.0) >= _BPM_LOCK_CONFIDENCE_FLOOR
    )
    lock_coverage_pct = 100.0 * locked / total_hb
    churn = int(all_events.get('bpm_lock_gained', 0)) + int(all_events.get('bpm_lock_lost', 0))
    churn_per_hr = churn / duration_hr

    # Thresholds calibrated from observed real-world sessions (2026-06-20):
    # best session ~130/hr, typical good 250-350/hr, typical house 600-850/hr,
    # pre-fix era 3000+/hr.
    det_stability = _score_1_to_5(churn_per_hr, [150, 350, 650, 1000], higher_is_better=False)
    det_responsiveness = _score_1_to_5(lock_coverage_pct, [70, 50, 35, 20])

    # ── Recommender ───────────────────────────────────────────────────────────
    profile_switches = int(all_events.get('profile_switch', 0))
    switches_per_hr = profile_switches / duration_hr

    switch_rows = [r for r in seq_rows if r.get('event_type') == 'profile_switch']
    # Profile after each switch — field name varies between corpus versions
    switch_profs = [
        r.get('to') or r.get('new_mode') or r.get('vj_profile') or r.get('profile', '')
        for r in switch_rows
    ]
    reversals = sum(1 for i in range(2, len(switch_profs)) if switch_profs[i] == switch_profs[i - 2])
    reversal_rate = reversals / max(len(switch_profs), 1)

    reco_coverage = (
        100.0 * sum(1 for r in hb_rows if r.get('recommended_profile_key')) / total_hb
    )

    rec_stability = _score_1_to_5(switches_per_hr, [5, 15, 30, 60], higher_is_better=False)
    rec_quality = _score_1_to_5(1.0 - reversal_rate, [0.9, 0.7, 0.5, 0.3])
    rec_responsiveness = _score_1_to_5(reco_coverage, [80, 60, 40, 20])

    # ── Director ──────────────────────────────────────────────────────────────
    mode_counter: Counter = Counter()
    for r in hb_rows:
        mode = r.get('vj_mode') or r.get('mode', '')
        if mode:
            mode_counter[mode] += 1
    passive_count = (
        mode_counter.get('CRUISE', 0)
        + mode_counter.get('CRUISE_SPOTIFY', 0)
        + mode_counter.get('sequential', 0)
    )
    cruise_frac = passive_count / total_hb
    mode_diversity = len([k for k, v in mode_counter.items() if v > 0])

    drops = int(all_events.get('drop_fire', 0))
    impacts = int(all_events.get('impact_fire', 0))
    drop_rate_per_10min = (drops + impacts) / max(duration_min, 1.0) * 10.0

    mode_transitions = int(all_events.get('mode_transition', 0))
    transition_rate_per_min = mode_transitions / max(duration_min, 1.0)

    dir_stability = _score_1_to_5(transition_rate_per_min, [0.5, 1.0, 2.0, 4.0], higher_is_better=False)
    dir_responsiveness = _score_1_to_5(drop_rate_per_10min, [3.0, 1.5, 0.5, 0.1])

    return {
        'detector': {
            'stability': det_stability,
            'responsiveness': det_responsiveness,
            'quality': None,
            '_meta': {
                'churn_per_hr': round(churn_per_hr, 1),
                'lock_coverage_pct': round(lock_coverage_pct, 1),
            },
        },
        'recommender': {
            'stability': rec_stability,
            'responsiveness': rec_responsiveness,
            'quality': rec_quality,
            '_meta': {
                'switches_per_hr': round(switches_per_hr, 1),
                'reversal_rate_pct': round(100.0 * reversal_rate, 1),
                'reco_coverage_pct': round(reco_coverage, 1),
            },
        },
        'director': {
            'stability': dir_stability,
            'responsiveness': dir_responsiveness,
            'quality': None,
            '_meta': {
                'transition_rate_per_min': round(transition_rate_per_min, 2),
                'drop_rate_per_10min': round(drop_rate_per_10min, 2),
                'cruise_frac_pct': round(100.0 * cruise_frac, 1),
                'mode_diversity': mode_diversity,
            },
        },
    }


def _build_detector_payload(
    seq_rows: list[dict],
    set_id: str,
    bucket_id: str,
    set_description: str | None = None,
    live_rows: list[dict] | None = None,
) -> dict:
    """Build a structured payload describing detector behaviour for LLM scoring."""
    # Build lookup from per-song key → live corpus row (contains Essentia BPM).
    # Live corpus keys track_id / spotify_track_id use the bare URI; sequence
    # corpus _song_key() prefixes it with "id:", so we normalise to match.
    live_by_key: dict[str, dict] = {}
    for row in (live_rows or []):
        tid = row.get('track_id', '') or row.get('spotify_track_id', '')
        if tid:
            live_by_key[f'id:{tid}'] = row

    songs: dict[str, list[dict]] = {}
    for row in seq_rows:
        key = _song_key(row)
        songs.setdefault(key, []).append(row)

    per_song = []
    for key, rows in songs.items():
        bpms = [float(r['bpm']) for r in rows if isinstance(r.get('bpm'), (int, float))]
        confs = [float(r['bpm_confidence']) for r in rows if isinstance(r.get('bpm_confidence'), (int, float))]
        locked = sum(1 for r in rows if float(r.get('bpm_confidence', 0.0) or 0.0) >= _BPM_LOCK_CONFIDENCE_FLOOR)
        evts = Counter(r.get('event_type') for r in rows if r.get('event_type'))
        sample = rows[0]
        title = sample.get('spotify_title', '')
        artist = sample.get('spotify_artist', '')

        entry: dict = {
            'key': key,
            'display': f'{title} – {artist}' if (title or artist) else key,
            'row_count': len(rows),
            'bpm_median': _safe_median(bpms),
            'bpm_min': round(min(bpms), 3) if bpms else None,
            'bpm_max': round(max(bpms), 3) if bpms else None,
            'confidence_median': _safe_median(confs),
            'lock_coverage_pct': round(100.0 * locked / len(rows), 1),
            'lock_gained': int(evts.get('bpm_lock_gained', 0)),
            'lock_lost': int(evts.get('bpm_lock_lost', 0)),
        }

        live = live_by_key.get(key, {})
        essentia_bpm = float(live.get('bpm', 0.0) or 0.0)
        if essentia_bpm > 0.0:
            det_bpm = entry['bpm_median']
            entry['essentia_bpm'] = round(essentia_bpm, 3)
            entry['essentia_bpm_confidence'] = round(float(live.get('bpm_confidence', 0.0) or 0.0), 4)
            entry['essentia_bpm_delta'] = round(det_bpm - essentia_bpm, 3) if det_bpm is not None else None

        per_song.append(entry)

    all_bpms = sorted(float(r['bpm']) for r in seq_rows if isinstance(r.get('bpm'), (int, float)))
    all_confs = [float(r['bpm_confidence']) for r in seq_rows if isinstance(r.get('bpm_confidence'), (int, float))]
    all_locked = sum(1 for r in seq_rows if float(r.get('bpm_confidence', 0.0) or 0.0) >= _BPM_LOCK_CONFIDENCE_FLOOR)
    all_events = Counter(r.get('event_type') for r in seq_rows if r.get('event_type'))

    conf_low = sum(1 for c in all_confs if c < 0.3)
    conf_mid = sum(1 for c in all_confs if 0.3 <= c < 0.6)
    conf_high = sum(1 for c in all_confs if c >= 0.6)
    total_confs = len(all_confs) or 1

    times = [r.get('analysis_generated_at') for r in seq_rows if isinstance(r.get('analysis_generated_at'), str)]
    start = min(times) if times else None
    end = max(times) if times else None

    lock_by_window: list[dict] = []
    if start and end:
        start_dt = _parse_ts(start)
        end_dt = _parse_ts(end)
        if start_dt and end_dt:
            total_s = (end_dt - start_dt).total_seconds()
            num_windows = max(1, int(total_s / 300) + 1)
            windows: list[dict] = [{'gained': 0, 'lost': 0} for _ in range(num_windows)]
            for r in seq_rows:
                ts_str = r.get('analysis_generated_at')
                evt = r.get('event_type')
                if not ts_str or evt not in ('bpm_lock_gained', 'bpm_lock_lost'):
                    continue
                ts = _parse_ts(ts_str)
                if not ts:
                    continue
                w = min(int((ts - start_dt).total_seconds() / 300), num_windows - 1)
                windows[w]['gained' if evt == 'bpm_lock_gained' else 'lost'] += 1
            lock_by_window = [
                {'window_start_min': round(i * 5, 1), 'lock_gained': w['gained'], 'lock_lost': w['lost']}
                for i, w in enumerate(windows)
                if w['gained'] or w['lost']
            ]

    return {
        'set_id': set_id,
        'bucket_id': bucket_id,
        'set_description': set_description,
        'total_rows': len(seq_rows),
        'song_count': len(songs),
        'time_range': {'start': start, 'end': end},
        'bpm': {
            'median': _safe_median(list(all_bpms)),
            'p10': _percentile(all_bpms, 10),
            'p25': _percentile(all_bpms, 25),
            'p75': _percentile(all_bpms, 75),
            'p90': _percentile(all_bpms, 90),
            'min': round(all_bpms[0], 3) if all_bpms else None,
            'max': round(all_bpms[-1], 3) if all_bpms else None,
        },
        'confidence': {
            'median': _safe_median(all_confs),
            'band_low_pct': round(100.0 * conf_low / total_confs, 1),
            'band_mid_pct': round(100.0 * conf_mid / total_confs, 1),
            'band_high_pct': round(100.0 * conf_high / total_confs, 1),
        },
        'beat_lock': {
            'coverage_pct': round(100.0 * all_locked / len(seq_rows), 1) if seq_rows else 0.0,
            'lock_gained_total': int(all_events.get('bpm_lock_gained', 0)),
            'lock_lost_total': int(all_events.get('bpm_lock_lost', 0)),
            'transitions_by_5min_window': lock_by_window,
        },
        'essentia_available': any(s.get('essentia_bpm', 0.0) > 0.0 for s in per_song),
        'essentia_summary': _build_essentia_summary(per_song),
        'per_song': per_song,
    }


def _detect_llm_provider() -> tuple[str | None, str | None]:
    """Return (provider, api_key) for the first available LLM API key."""
    openai_key = os.environ.get('OPENAI_API_KEY', '').strip()
    if openai_key:
        return 'openai', openai_key
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if anthropic_key:
        return 'anthropic', anthropic_key
    return None, None


def _build_combined_prompt(detector_payload: dict, director_payload: dict) -> str:
    """Build a single LLM prompt that scores the BPM detector and VJ director together."""
    essentia_note = (
        'No Essentia reference BPM data is available; score external_agreement as null.'
        if not detector_payload.get('essentia_available')
        else 'Essentia reference BPM data is included in the detector payload.'
    )
    desc_note = ''
    if detector_payload.get('set_description'):
        desc_note = f'\n\nSet description (operator context):\n{detector_payload["set_description"]}\n'
    det_copy = {k: v for k, v in detector_payload.items() if k != 'set_description'}
    det_json = json.dumps(det_copy, indent=2, ensure_ascii=False)
    dir_json = json.dumps(director_payload, indent=2, ensure_ascii=False)

    return f"""You are evaluating an automated live VJ system built on a real-time BPM detector and \
a rule-based VJ director. Score both subsystems from the session data below.{desc_note}

━━━━━━━━━━━━━━━━━ PART 1 — BPM DETECTOR ━━━━━━━━━━━━━━━━━

Score on five dimensions (0-5 integer each):
1. lock_stability: Persistence of beat lock, low churn, coherent behavior.
2. tempo_plausibility: BPM continuity and realistic transitions.
3. confidence_reliability: Agreement between confidence values and actual lock behavior.
4. musical_alignment: Beat grid behavior matching musical phrasing/structure.
5. external_agreement: Alignment with Essentia reference estimates where provided.

Scoring guide: 5=excellent, 4=good, 3=acceptable, 2=poor, 1=very poor, 0=failure.
{essentia_note}

Detector data:
{det_json}

━━━━━━━━━━━━━━━━━ PART 2 — VJ DIRECTOR ━━━━━━━━━━━━━━━━━━

The director watches audio energy and the BPM detector to trigger visual transitions
(build → drop → impact). The events list shows audio signals at each director action.

Key fields per event:
- bpm_confidence: how solidly the detector was locked when the action fired
- danceability: Essentia danceability [0-1], good proxy for beat strength
- crest_factor: peak/RMS ratio; high values indicate transient-heavy moments (drops)
- reason (mode_transition): sustained_rise or sustained_fall (energy going up or down)

Score on four dimensions (0-5 integer each):
1. build_quality: Are build entries (sustained_rise) triggered at genuinely rising energy \
(improving danceability/crest_factor)? Or do they reverse quickly to breakdown?
2. drop_quality: Are drops/impacts fired at appropriately high-energy moments \
(high crest_factor/danceability), not just any random moment?
3. energy_coherence: Do the audio signals at each transition justify that director action overall?
4. opportunity_usage: Does the director act on high-energy windows, or are there many \
sustained_rise→sustained_fall reversals without ever reaching a drop?

Director data:
{dir_json}

━━━━━━━━━━━━━━━━━━━ RESPONSE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Return ONLY valid JSON — no markdown, no prose — matching this schema exactly:
{{
  "detector": {{
    "scores": {{
      "lock_stability": <int 0-5>,
      "tempo_plausibility": <int 0-5>,
      "confidence_reliability": <int 0-5>,
      "musical_alignment": <int 0-5>,
      "external_agreement": <int 0-5 or null>
    }},
    "overall": <float, weighted average excluding null dimensions>,
    "per_song": [
      {{
        "key": "<song key from detector payload>",
        "display": "<Title – Artist>",
        "lock_coverage_pct": <float>,
        "assessment": "<2-sentence evaluation>"
      }}
    ],
    "rationale": {{
      "lock_stability": "<explanation>",
      "tempo_plausibility": "<explanation>",
      "confidence_reliability": "<explanation>",
      "musical_alignment": "<explanation>",
      "external_agreement": "<explanation or No Essentia data>"
    }},
    "caveats": ["<caveat strings>"]
  }},
  "director": {{
    "scores": {{
      "build_quality": <int 0-5>,
      "drop_quality": <int 0-5>,
      "energy_coherence": <int 0-5>,
      "opportunity_usage": <int 0-5>
    }},
    "overall": <float, average of the four dimensions>,
    "rationale": {{
      "build_quality": "<explanation>",
      "drop_quality": "<explanation>",
      "energy_coherence": "<explanation>",
      "opportunity_usage": "<explanation>"
    }}
  }},
  "scored_at": "<ISO 8601 UTC timestamp>"
}}\
"""


def _extract_json(text: str) -> dict:
    """Extract the first JSON object from an LLM response string."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError('No JSON object found in LLM response')


def _call_llm(provider: str, api_key: str, prompt: str) -> str:
    """Call the LLM provider and return response text."""
    if provider == 'openai':
        try:
            from openai import OpenAI  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError('openai package not installed; run: pip install openai') from exc
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model='gpt-4o',
            response_format={'type': 'json_object'},
            messages=[{'role': 'user', 'content': prompt}],
            timeout=90,
        )
        return response.choices[0].message.content or ''
    if provider == 'anthropic':
        try:
            import anthropic  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError('anthropic package not installed; run: pip install anthropic') from exc
        client = anthropic.Anthropic(api_key=api_key)
        with client.messages.stream(
            model='claude-opus-4-8',
            max_tokens=4096,
            thinking={'type': 'adaptive'},
            messages=[{'role': 'user', 'content': prompt}],
        ) as stream:
            msg = stream.get_final_message()
        return '\n'.join(b.text for b in msg.content if hasattr(b, 'text') and b.type == 'text')
    raise ValueError(f'Unknown LLM provider: {provider}')


def _print_combined_score_table(
    local_scores: dict,
    llm_data: dict | None,
    set_id: str,
    bucket_id: str,
) -> None:
    """Print the combined 3-column scoring table (detector / recommender / director)."""
    W = 72
    sep = '━' * W

    llm_det = (llm_data or {}).get('detector', {})
    llm_dir = (llm_data or {}).get('director', {})
    llm_det_scores = llm_det.get('scores', {})
    llm_dir_scores = llm_dir.get('scores', {})

    def _avg_dims(scores: dict, keys: list[str]) -> float | None:
        vals = [float(scores[k]) for k in keys if isinstance(scores.get(k), (int, float))]
        return round(sum(vals) / len(vals), 1) if vals else None

    # Quality: musical judgement dims only (stability/responsiveness are handled locally)
    det_quality = _avg_dims(llm_det_scores, ['tempo_plausibility', 'musical_alignment'])
    dir_quality = _avg_dims(
        llm_dir_scores, ['build_quality', 'drop_quality', 'energy_coherence', 'opportunity_usage']
    )

    ld = local_scores.get('detector', {})
    lr = local_scores.get('recommender', {})
    li = local_scores.get('director', {})

    def _fmt(v: int | float | None) -> str:
        return f'{int(round(v)):1d}/5' if isinstance(v, (int, float)) else ' n/a'

    def _row(label: str, det: object, rec: object, drv: object) -> str:
        return f'  {label:<24}{_fmt(det):>7}   {_fmt(rec):>11}   {_fmt(drv):>8}'

    def _col_avg(*vals: int | float | None) -> float | None:
        present = [v for v in vals if v is not None]
        return round(sum(present) / len(present), 1) if present else None

    det_overall = _col_avg(ld.get('stability'), ld.get('responsiveness'), det_quality)
    rec_overall = _col_avg(lr.get('stability'), lr.get('responsiveness'), lr.get('quality'))
    dir_overall = _col_avg(li.get('stability'), li.get('responsiveness'), dir_quality)
    grand_vals = [v for v in (det_overall, rec_overall, dir_overall) if v is not None]
    grand_total = round(sum(grand_vals) / len(grand_vals), 1) if grand_vals else None

    provider = (llm_data or {}).get('provider', '')
    llm_tag = f' (llm: {provider})' if provider else ' (local only)'

    print(sep)
    print(f'Auto VJ Session Score — {set_id} / {bucket_id}')
    print(sep)
    print()
    print(f'  {"":24}{"DETECTOR":>7}   {"RECOMMENDER":>11}   {"DIRECTOR":>8}')
    print()
    print(_row('Stability  (local)', ld.get('stability'), lr.get('stability'), li.get('stability')))
    print(_row('Responsiveness (local)', ld.get('responsiveness'), lr.get('responsiveness'), li.get('responsiveness')))
    q_label = f'Quality{llm_tag[:18]}'
    print(_row(q_label, det_quality, lr.get('quality'), dir_quality))
    print()
    print(f'  {"─" * (W - 2)}')
    print(_row('Overall', det_overall, rec_overall, dir_overall))
    if grand_total is not None:
        print(f'\n  Grand total  {grand_total:.1f} / 5.0')
    print()
    print(sep)
    print()

    # LLM dimension breakdowns
    if llm_data:
        if llm_det_scores:
            print('  Detector (LLM):')
            for dim in ['lock_stability', 'tempo_plausibility', 'confidence_reliability',
                        'musical_alignment', 'external_agreement']:
                val = llm_det_scores.get(dim)
                note = (llm_det.get('rationale') or {}).get(dim, '')[:68]
                print(f'    {dim:<30} {str(val) if val is not None else "n/a":>3}   {note}')
            print()

        if llm_dir_scores:
            print('  Director (LLM):')
            for dim in ['build_quality', 'drop_quality', 'energy_coherence', 'opportunity_usage']:
                val = llm_dir_scores.get(dim)
                note = (llm_dir.get('rationale') or {}).get(dim, '')[:68]
                print(f'    {dim:<30} {str(val) if val is not None else "n/a":>3}   {note}')
            print()

    # Local metadata
    print('  Local metrics:')
    for label, meta_key in [('Detector', 'detector'), ('Recommender', 'recommender'), ('Director', 'director')]:
        meta = local_scores.get(meta_key, {}).get('_meta', {})
        parts = ', '.join(f'{k}={v}' for k, v in meta.items())
        print(f'    {label:<12} {parts}')
    print()

    # Per-song lock coverage from detector
    per_song = llm_det.get('per_song', [])
    if per_song:
        has_essentia = any(s.get('essentia_bpm') for s in per_song)
        header = '  Per-song lock coverage' + ('  [essentia delta]' if has_essentia else '') + ':'
        print(header)
        for song in per_song:
            cov = song.get('lock_coverage_pct')
            display = song.get('display', song.get('key', '?'))
            cov_str = f'{cov:5.1f}%' if isinstance(cov, (int, float)) else '   n/a'
            delta = song.get('essentia_bpm_delta')
            delta_str = f'  Δ{delta:+.1f} BPM' if delta is not None else ''
            print(f'    {cov_str}{delta_str}  {display}')
        print()


def _format_detector_score_md(score: dict, set_id: str, bucket_id: str) -> str:
    """Render detector_score.md from a parsed score dict."""
    scores = score.get('scores', {})
    overall = score.get('overall', 'n/a')
    rationale = score.get('rationale', {})
    per_song = score.get('per_song', [])
    caveats = score.get('caveats', [])
    provider = score.get('provider', 'llm')
    scored_at = score.get('scored_at', 'n/a')

    def _s(v: object) -> str:
        return 'n/a' if v is None else str(v)

    lines: list[str] = [
        '# Auto VJ Detector Score',
        '',
        f'Owner: auto-generated by tools/package_training_set.py ({provider})',
        'Status: generated',
        f'Last updated: {datetime.date.today().isoformat()}',
        '',
        f'- Set: `{set_id}`',
        f'- Bucket: `{bucket_id}`',
        f'- Scored at: `{scored_at}`',
        f'- Provider: `{provider}`',
        '',
        '## Dimension Scores',
        '',
        '| Dimension | Score |',
        '|---|---|',
        f'| Lock Stability | {_s(scores.get("lock_stability"))} / 5 |',
        f'| Tempo Plausibility | {_s(scores.get("tempo_plausibility"))} / 5 |',
        f'| Confidence Reliability | {_s(scores.get("confidence_reliability"))} / 5 |',
        f'| Musical Alignment | {_s(scores.get("musical_alignment"))} / 5 |',
        f'| External Agreement | {_s(scores.get("external_agreement"))} / 5 |',
        f'| **Overall** | **{_s(overall)} / 5** |',
        '',
        '## Rationale',
        '',
    ]
    for key, label in [
        ('lock_stability', 'Lock Stability'),
        ('tempo_plausibility', 'Tempo Plausibility'),
        ('confidence_reliability', 'Confidence Reliability'),
        ('musical_alignment', 'Musical Alignment'),
        ('external_agreement', 'External Agreement'),
    ]:
        lines.extend([f'### {label}', '', _s(rationale.get(key)), ''])

    if per_song:
        lines.extend(['## Per-Song Assessment', ''])
        for song in per_song:
            display = song.get('display') or song.get('key', 'unknown')
            lines.extend([
                f'### {display}',
                '',
                f'- Lock coverage: `{_s(song.get("lock_coverage_pct"))}%`',
                f'- {song.get("assessment", "")}',
                '',
            ])

    if caveats:
        lines.extend(['## Caveats', ''])
        lines.extend(f'- {c}' for c in caveats)
        lines.append('')

    return '\n'.join(lines) + '\n'


def _format_director_score_md(score: dict, set_id: str, bucket_id: str) -> str:
    """Render director_score.md from a parsed director score dict."""
    scores = score.get('scores', {})
    overall = score.get('overall', 'n/a')
    rationale = score.get('rationale', {})
    provider = score.get('provider', 'llm')
    scored_at = score.get('scored_at', 'n/a')

    def _s(v: object) -> str:
        return 'n/a' if v is None else str(v)

    lines: list[str] = [
        '# Auto VJ Director Score',
        '',
        f'Owner: auto-generated by tools/package_training_set.py ({provider})',
        'Status: generated',
        f'Last updated: {datetime.date.today().isoformat()}',
        '',
        f'- Set: `{set_id}`',
        f'- Bucket: `{bucket_id}`',
        f'- Scored at: `{scored_at}`',
        f'- Provider: `{provider}`',
        '',
        '## Dimension Scores',
        '',
        '| Dimension | Score |',
        '|---|---|',
        f'| Build Quality | {_s(scores.get("build_quality"))} / 5 |',
        f'| Drop Quality | {_s(scores.get("drop_quality"))} / 5 |',
        f'| Energy Coherence | {_s(scores.get("energy_coherence"))} / 5 |',
        f'| Opportunity Usage | {_s(scores.get("opportunity_usage"))} / 5 |',
        f'| **Overall** | **{_s(overall)} / 5** |',
        '',
        '## Rationale',
        '',
    ]
    for key, label in [
        ('build_quality', 'Build Quality'),
        ('drop_quality', 'Drop Quality'),
        ('energy_coherence', 'Energy Coherence'),
        ('opportunity_usage', 'Opportunity Usage'),
    ]:
        lines.extend([f'### {label}', '', _s(rationale.get(key)), ''])

    return '\n'.join(lines) + '\n'


def _generate_set_description_once(root: Path, set_dir: Path, bucket_dir: Path) -> tuple[str, Path, str]:
    """Generate one set-level TRAINING_SET_DESCRIPTION.md, skipping if it already exists."""
    import subprocess
    import sys

    description_path = set_dir / 'TRAINING_SET_DESCRIPTION.md'
    if description_path.exists():
        return 'skipped', description_path, 'already exists'

    script_path = root / 'tools' / 'generate_training_set_description.py'
    if not script_path.exists():
        return 'skipped', description_path, f'generator not found: {script_path}'

    style_tag = _infer_style_tag(set_dir)
    cmd = [
        sys.executable,
        str(script_path),
        '--set-name', set_dir.name,
        '--bucket', bucket_dir.name,
        '--output-path', str(description_path),
        '--playlist-context', style_tag,
    ]
    mode = 'local'
    if os.environ.get('OPENAI_API_KEY', '').strip():
        cmd.append('--use-llm')
        mode = 'llm'

    try:
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or '').strip()
        return 'failed', description_path, detail or 'generator command failed'

    return 'generated', description_path, f'mode={mode}\n{(completed.stdout or "").strip()}'


def _run_llm_scoring(
    bucket_dir: Path,
    seq_rows: list[dict],
    set_id: str,
    bucket_id: str,
    duration_min: float | None = None,
    set_description: str | None = None,
    live_rows: list[dict] | None = None,
    skip: bool = False,
    force_regen: bool = False,
) -> dict | None:
    """Run combined LLM scoring for detector + director; write all score files.

    Writes session_score.json (combined), detector_score.{json,md}, and
    director_score.{json,md} to bucket_dir.  Returns the parsed LLM response
    dict on success, None on skip or failure.  Packaging always continues.
    """
    if skip:
        print('LLM scoring skipped (--skip-llm-scoring).')
        return None

    session_json_path = bucket_dir / 'session_score.json'
    if session_json_path.exists() and not force_regen:
        print('session_score.json already exists; use --force-regen-detector-score to overwrite.')
        try:
            return json.loads(session_json_path.read_text(encoding='utf-8'))
        except Exception:
            return None

    if not seq_rows:
        _LOG.warning('LLM scoring skipped: sequence corpus is empty.')
        return None

    provider, api_key = _detect_llm_provider()
    if provider is None:
        _LOG.warning('LLM scoring skipped: no OPENAI_API_KEY or ANTHROPIC_API_KEY in environment.')
        return None

    print(f'Running combined LLM scoring via {provider}...')
    detector_payload = _build_detector_payload(
        seq_rows, set_id, bucket_id, set_description, live_rows=live_rows
    )
    director_payload = _build_director_payload(seq_rows, duration_min, set_id, bucket_id)
    prompt = _build_combined_prompt(detector_payload, director_payload)

    try:
        response_text = _call_llm(provider, api_key, prompt)
        llm_data = _extract_json(response_text)
    except Exception as exc:
        _LOG.warning('LLM scoring failed (%s: %s). Packaging continues.', type(exc).__name__, exc)
        return None

    # Restore display names — LLMs occasionally corrupt non-ASCII separators.
    _key_to_display = {s['key']: s['display'] for s in detector_payload.get('per_song', [])}
    for entry in llm_data.get('detector', {}).get('per_song', []):
        key = entry.get('key', '')
        if key in _key_to_display:
            entry['display'] = _key_to_display[key]

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    llm_data.setdefault('scored_at', now_iso)
    llm_data['set_id'] = set_id
    llm_data['bucket_id'] = bucket_id
    llm_data['provider'] = provider

    # ── Write session_score.json (combined) ───────────────────────────────────
    session_json_path.write_text(json.dumps(llm_data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    # ── Write detector_score.{json,md} (backwards-compat format) ─────────────
    det_score = dict(llm_data.get('detector', {}))
    det_score.update({'set_id': set_id, 'bucket_id': bucket_id, 'provider': provider,
                      'scored_at': llm_data.get('scored_at', now_iso)})
    det_json_path = bucket_dir / 'detector_score.json'
    det_json_path.write_text(json.dumps(det_score, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (bucket_dir / 'detector_score.md').write_text(
        _format_detector_score_md(det_score, set_id, bucket_id), encoding='utf-8'
    )

    # ── Write director_score.{json,md} ────────────────────────────────────────
    dir_score = dict(llm_data.get('director', {}))
    dir_score.update({'set_id': set_id, 'bucket_id': bucket_id, 'provider': provider,
                      'scored_at': llm_data.get('scored_at', now_iso)})
    dir_json_path = bucket_dir / 'director_score.json'
    dir_json_path.write_text(json.dumps(dir_score, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (bucket_dir / 'director_score.md').write_text(
        _format_director_score_md(dir_score, set_id, bucket_id), encoding='utf-8'
    )

    print(f'Session score: {session_json_path}')
    return llm_data


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--playlist-name',
        metavar='NAME',
        help='Playlist name (human-readable); auto-slugified into the set directory name. '
             'Creates the directory if it does not exist, otherwise appends the next bucket.',
    )
    parser.add_argument(
        '--set-name',
        help='Set directory name under assets/training/sets (exact slug; overrides --playlist-name).',
    )
    parser.add_argument(
        '--no-prompt',
        action='store_true',
        help='Disable prompts; requires --playlist-name or --set-name when no set exists.',
    )
    parser.add_argument(
        '--skip-llm-scoring',
        action='store_true',
        help='Skip the LLM detector scoring step.',
    )
    parser.add_argument(
        '--set-description',
        metavar='PATH',
        help='Path to a .md or .txt file describing the set (passed to the LLM scorer).',
    )
    parser.add_argument(
        '--force-regen-detector-score',
        action='store_true',
        help='Re-run LLM scoring even if session_score.json / detector_score.json already exist.',
    )
    parser.add_argument(
        '--session-notes',
        default='',
        metavar='TEXT',
        help='Session notes to record (skips interactive prompt; use with --no-prompt).',
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
    args = _parse_args()
    root = Path(__file__).resolve().parents[1]
    training_root = root / 'assets' / 'training'
    sets_root = training_root / 'sets'
    corpus_dir = training_root / 'corpus'
    logs_dir = root / 'logs'

    sets_root.mkdir(parents=True, exist_ok=True)

    live_src = _pick_latest(corpus_dir, ['live-corpus*.jsonl', 'live-autovj*.jsonl', 'live*.jsonl'])
    seq_src = _pick_latest(corpus_dir, ['sequence-corpus*.jsonl', 'sequence*.jsonl'])
    if live_src is None or seq_src is None:
        print('Could not find both live and sequence corpus files in assets/training/corpus.')
        return 1

    # Resolve set directory: --set-name wins, then --playlist-name (auto-slugified),
    # then auto-inferred from spotify_playlist_name in corpus, then interactive
    # prompt, then fall back to most-recently-modified set.
    set_name: str | None = args.set_name
    if not set_name and args.playlist_name:
        set_name = _slugify_playlist_name(args.playlist_name)
    if not set_name:
        inferred = _infer_playlist_name_from_logs(logs_dir)
        if inferred:
            set_name = inferred
            print(f'Playlist name inferred from session log: {set_name}')
    if not set_name and not args.no_prompt:
        set_name = _prompt_playlist_name()

    if set_name:
        set_dir = sets_root / set_name
        set_dir.mkdir(parents=True, exist_ok=True)
    else:
        set_dir = _latest_set_dir(sets_root)
        if set_dir is None:
            print('No set directory exists yet. Pass --playlist-name to create one.')
            return 1

    bucket_dir = _next_bucket_dir(set_dir)
    bucket_dir.mkdir(parents=True, exist_ok=False)

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

    # Move screenshots and recordings into named subdirectories of the bucket.
    for src_dir_name in ('screenshots', 'recordings'):
        src_dir = root / src_dir_name
        if not src_dir.is_dir():
            continue
        media_files = sorted(
            [p for p in src_dir.rglob('*') if p.is_file()],
            key=lambda p: p.stat().st_mtime,
        )
        if not media_files:
            continue
        dest_subdir = bucket_dir / src_dir_name
        dest_subdir.mkdir(exist_ok=True)
        for media_path in media_files:
            dest = dest_subdir / media_path.name
            if dest.exists():
                raise FileExistsError(f'destination already exists: {dest}')
            shutil.move(str(media_path), str(dest))
            moved.append(dest)

    scorecard_path, lock_rating, director_rating = _write_scorecard(
        bucket_dir,
        moved_live,
        moved_seq,
    )
    session_date = datetime.date.today().isoformat()
    session_notes = args.session_notes or ''
    if not args.no_prompt and not session_notes:
        session_notes = _prompt_optional_text('Session notes for the training log (optional)')

    set_description: str | None = None
    if args.set_description:
        desc_path = Path(args.set_description)
        if desc_path.is_file():
            set_description = desc_path.read_text(encoding='utf-8')
        else:
            print(f'Warning: --set-description file not found: {desc_path}')

    seq_rows = _load_jsonl_rows(moved_seq)
    live_rows_for_scoring = _load_jsonl_rows(moved_live) if moved_live else []
    duration_min = _compute_duration_min(seq_rows)
    local_scores = _compute_local_scores(seq_rows, duration_min or 1.0)

    llm_data = _run_llm_scoring(
        bucket_dir,
        seq_rows,
        set_dir.name,
        bucket_dir.name,
        duration_min=duration_min,
        set_description=set_description,
        live_rows=live_rows_for_scoring,
        skip=args.skip_llm_scoring,
        force_regen=args.force_regen_detector_score,
    )

    detector_llm_score: float | None = None
    if llm_data is not None:
        det_overall = llm_data.get('detector', {}).get('overall')
        if isinstance(det_overall, (int, float)):
            detector_llm_score = float(det_overall)

    session_log_path = _append_session_log(
        training_root,
        set_dir,
        bucket_dir,
        session_date,
        lock_rating,
        director_rating,
        session_notes,
        detector_llm_score=detector_llm_score,
    )

    desc_status, desc_path_out, desc_detail = _generate_set_description_once(root, set_dir, bucket_dir)

    print(f'Set directory: {set_dir}')
    print(f'Bucket: {bucket_dir.name}')
    print(f'Scorecard: {scorecard_path}')
    print(f'Session log: {session_log_path}')
    if desc_status == 'generated':
        print(f'Set description: {desc_path_out} (generated)')
    elif desc_status == 'skipped':
        print(f'Set description: {desc_path_out} (skipped — {desc_detail})')
    else:
        print(f'Set description: failed — {desc_detail}')
    print('Moved files:')
    for path in moved:
        print(f'  - {path}')
    if not session_logs:
        print('No log files were found to move.')
    for src_dir_name in ('screenshots', 'recordings'):
        count = sum(1 for p in moved if p.parent.name == src_dir_name)
        if count:
            print(f'{count} {src_dir_name} moved to {bucket_dir / src_dir_name}')

    print('\n' + '-' * 60)
    print(scorecard_path.read_text(encoding='utf-8'))

    _print_combined_score_table(local_scores, llm_data, set_dir.name, bucket_dir.name)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())