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


def _build_detector_payload(
    seq_rows: list[dict],
    set_id: str,
    bucket_id: str,
    set_description: str | None = None,
) -> dict:
    """Build a structured payload describing detector behaviour for LLM scoring."""
    songs: dict[str, list[dict]] = {}
    for row in seq_rows:
        key = _song_key(row)
        songs.setdefault(key, []).append(row)

    per_song = []
    for key, rows in songs.items():
        bpms = [float(r['bpm']) for r in rows if isinstance(r.get('bpm'), (int, float))]
        confs = [float(r['bpm_confidence']) for r in rows if isinstance(r.get('bpm_confidence'), (int, float))]
        locked = sum(1 for r in rows if isinstance(r.get('beat_index'), int) and r['beat_index'] >= 0)
        evts = Counter(r.get('event_type') for r in rows if r.get('event_type'))
        sample = rows[0]
        title = sample.get('spotify_title', '')
        artist = sample.get('spotify_artist', '')
        per_song.append({
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
        })

    all_bpms = sorted(float(r['bpm']) for r in seq_rows if isinstance(r.get('bpm'), (int, float)))
    all_confs = [float(r['bpm_confidence']) for r in seq_rows if isinstance(r.get('bpm_confidence'), (int, float))]
    all_locked = sum(1 for r in seq_rows if isinstance(r.get('beat_index'), int) and r.get('beat_index', -1) >= 0)
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
        'essentia_available': False,
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


def _build_scoring_prompt(payload: dict) -> str:
    """Build the LLM scoring prompt from the detector payload."""
    essentia_note = (
        'No Essentia reference data is available; score external_agreement as null and include a caveat.'
        if not payload.get('essentia_available')
        else 'Essentia reference data is included in the payload under essentia_summary.'
    )
    desc_note = ''
    if payload.get('set_description'):
        desc_note = f'\n\nSet description (operator context):\n{payload["set_description"]}\n'
    payload_copy = {k: v for k, v in payload.items() if k != 'set_description'}
    payload_json = json.dumps(payload_copy, indent=2, ensure_ascii=False)

    return f"""You are an expert in music beat detection systems evaluating BPM detector performance during a live VJ session.

Score the detector on five dimensions (0-5 integer each):

1. lock_stability: Persistence of beat lock, low churn, coherent lock behavior.
2. tempo_plausibility: BPM continuity and realistic transitions between tempos.
3. confidence_reliability: Agreement between confidence values and actual lock behavior.
4. musical_alignment: Beat grid behavior matching expected musical phrasing/structure.
5. external_agreement: Alignment with Essentia reference estimates where provided.

Scoring guide: 5=excellent, 4=good, 3=acceptable, 2=poor, 1=very poor, 0=complete failure.

{essentia_note}{desc_note}

Session data:
{payload_json}

Return ONLY a valid JSON object — no markdown, no prose — with this exact schema:
{{
  "scores": {{
    "lock_stability": <integer 0-5>,
    "tempo_plausibility": <integer 0-5>,
    "confidence_reliability": <integer 0-5>,
    "musical_alignment": <integer 0-5>,
    "external_agreement": <integer 0-5 or null>
  }},
  "overall": <float 0.0-5.0, weighted average excluding null dimensions>,
  "per_song": [
    {{
      "key": "<song key from payload>",
      "display": "<Title \\u2013 Artist>",
      "lock_coverage_pct": <float>,
      "assessment": "<2-3 sentence evaluation>"
    }}
  ],
  "rationale": {{
    "lock_stability": "<explanation>",
    "tempo_plausibility": "<explanation>",
    "confidence_reliability": "<explanation>",
    "musical_alignment": "<explanation>",
    "external_agreement": "<explanation or 'No Essentia data available'>"
  }},
  "caveats": ["<caveat strings>"],
  "scored_at": "<ISO 8601 UTC timestamp>"
}}"""


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


def _score_detector_with_llm(
    bucket_dir: Path,
    seq_rows: list[dict],
    set_id: str,
    bucket_id: str,
    set_description: str | None = None,
    skip: bool = False,
    force_regen: bool = False,
) -> Path | None:
    """Run LLM detector scoring and write detector_score.{json,md} to bucket_dir.

    Returns the path to detector_score.json on success, None on skip or failure.
    Packaging always continues regardless of outcome.
    """
    if skip:
        print('LLM detector scoring skipped (--skip-llm-scoring).')
        return None

    json_path = bucket_dir / 'detector_score.json'
    if json_path.exists() and not force_regen:
        print(f'detector_score.json already exists; use --force-regen-detector-score to overwrite.')
        return json_path

    if not seq_rows:
        _LOG.warning('LLM detector scoring skipped: sequence corpus is empty.')
        return None

    provider, api_key = _detect_llm_provider()
    if provider is None:
        _LOG.warning(
            'LLM detector scoring skipped: no OPENAI_API_KEY or ANTHROPIC_API_KEY in environment.'
        )
        return None

    print(f'Running LLM detector scoring via {provider}...')
    payload = _build_detector_payload(seq_rows, set_id, bucket_id, set_description)
    prompt = _build_scoring_prompt(payload)

    try:
        response_text = _call_llm(provider, api_key, prompt)
        score = _extract_json(response_text)
    except Exception as exc:
        _LOG.warning('LLM detector scoring failed (%s: %s). Packaging continues.', type(exc).__name__, exc)
        return None

    score.setdefault('scored_at', datetime.datetime.now(datetime.timezone.utc).isoformat())
    score['set_id'] = set_id
    score['bucket_id'] = bucket_id
    score['provider'] = provider

    json_path.write_text(json.dumps(score, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    md_path = bucket_dir / 'detector_score.md'
    md_path.write_text(_format_detector_score_md(score, set_id, bucket_id), encoding='utf-8')
    print(f'Detector score: {json_path}')
    return json_path


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
        help='Re-run LLM scoring even if detector_score.json already exists in the bucket.',
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

    set_description: str | None = None
    if args.set_description:
        desc_path = Path(args.set_description)
        if desc_path.is_file():
            set_description = desc_path.read_text(encoding='utf-8')
        else:
            print(f'Warning: --set-description file not found: {desc_path}')

    seq_rows = _load_jsonl_rows(moved_seq)
    llm_score_path = _score_detector_with_llm(
        bucket_dir,
        seq_rows,
        set_dir.name,
        bucket_dir.name,
        set_description=set_description,
        skip=args.skip_llm_scoring,
        force_regen=args.force_regen_detector_score,
    )

    detector_llm_score: float | None = None
    if llm_score_path is not None:
        try:
            llm_data = json.loads(llm_score_path.read_text(encoding='utf-8'))
            overall = llm_data.get('overall')
            if isinstance(overall, (int, float)):
                detector_llm_score = float(overall)
        except Exception:
            pass

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

    print('\n' + '-' * 60)
    print(scorecard_path.read_text(encoding='utf-8'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())