"""Generate a standardized training set description document.

This tool reads a packaged training bucket under:
assets/training/sets/<set>/<bucket>/

It builds a deterministic context payload from the sequence/live corpus files,
optionally enriches each track with lightweight metadata from the iTunes Search
API, and can either:

1) render a local deterministic markdown description, or
2) ask a ChatGPT model to draft the final markdown from the same template.

Usage examples:

  python3 tools/generate_training_set_description.py \
      --set-name 20260619-classic-house-2025-2026 \
      --bucket c

  OPENAI_API_KEY=... python3 tools/generate_training_set_description.py \
      --set-name 20260619-classic-house-2025-2026 \
      --bucket c \
      --use-llm \
      --model gpt-5.3-codex
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TEMPLATE_VERSION = 'v1'
DEFAULT_MODEL = 'gpt-5.3-codex'


PROMPT_TEMPLATE = """# Training Set Description Template (v1)

Use this exact section order and headings.

# Training Set Description

- Set: <set_name>
- Bucket: <bucket_name>
- Session Date (UTC): <date>
- Duration: <duration_min>
- Source Playlist Context: <context>

## Set Summary

<2-4 paragraphs describing music selection, mood arc, energy curve, and flow>

## Snapshot Metrics

- Sequence rows: <int>
- Live rows: <int>
- Profile mix: <profile breakdown>
- BPM median/range: <median and range>
- Director activity: <mode transitions, drop fires, impact fires>
- Session notes: <operator notes if present>

## Track Flow (Chronological)

|#|Start (UTC)|Artist|Title|Profile|Avg BPM|BPM Conf|Genre|Release|
|---|---|---|---|---|---:|---:|---|---|
|...|

## Per-Track Notes

### <index>. <Artist> - <Title>
- Data: profile=<profile>, avg_bpm=<value>, bpm_conf=<value>, loudness=<value>, danceability=<value>
- Lookup: release=<date>, genre=<genre>, catalog_artist=<lookup artist>, catalog_track=<lookup title>
- Description: <2-4 sentences about sonic character and function in set flow>

## Automation Notes

- Template version: v1
- Confidence and caveats about metadata matching.
- Suggested follow-up prompts for next run comparison.
"""


SYSTEM_PROMPT = """You are generating a machine-parseable training set description
for an Auto VJ workflow.

Requirements:
- Follow the provided markdown template exactly.
- Keep output factual and grounded in provided JSON context.
- Use measured wording when metadata confidence is uncertain.
- Do not invent tracks that are not in the input.
- Mention flow and mood with concise DJ-oriented language.
- Keep per-track note to max 4 sentences.
"""


@dataclass(slots=True)
class TrackFact:
    index: int
    track_id: str
    artist: str
    title: str
    album: str
    start_utc: str
    end_utc: str
    seq_rows: int
    avg_bpm: float
    avg_bpm_conf: float
    avg_rms: float
    avg_loudness: float
    avg_danceability: float
    dominant_profile: str
    metadata: dict[str, Any]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--set-name', help='Set directory under assets/training/sets')
    parser.add_argument('--bucket', help='Bucket directory inside the set (for example: a, b, c)')
    parser.add_argument('--use-llm', action='store_true', help='Use ChatGPT API to draft markdown')
    parser.add_argument('--model', default=DEFAULT_MODEL, help=f'LLM model name (default: {DEFAULT_MODEL})')
    parser.add_argument(
        '--output',
        default='TRAINING_SET_DESCRIPTION.md',
        help='Output file name inside the selected bucket',
    )
    parser.add_argument(
        '--output-path',
        help='Optional explicit output path. If omitted, writes to <bucket>/<output>.',
    )
    parser.add_argument(
        '--playlist-context',
        default='',
        help='Short playlist/context label. Derived from the set name when not provided.',
    )
    parser.add_argument(
        '--no-itunes-lookup',
        action='store_true',
        help='Skip iTunes metadata enrichment and keep only corpus fields',
    )
    return parser.parse_args()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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


def _pick_latest_dir(parent: Path) -> Path | None:
    dirs = [p for p in parent.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime)


def _pick_bucket(training_sets_root: Path, set_name: str | None, bucket: str | None) -> Path:
    if set_name:
        set_dir = training_sets_root / set_name
    else:
        set_dir = _pick_latest_dir(training_sets_root)
        if set_dir is None:
            raise FileNotFoundError('No training set directory found.')

    if not set_dir.exists() or not set_dir.is_dir():
        raise FileNotFoundError(f'Set directory not found: {set_dir}')

    if bucket:
        bucket_dir = set_dir / bucket
    else:
        latest = _pick_latest_dir(set_dir)
        if latest is None:
            raise FileNotFoundError(f'No bucket directories found in {set_dir}')
        bucket_dir = latest

    if not bucket_dir.exists() or not bucket_dir.is_dir():
        raise FileNotFoundError(f'Bucket directory not found: {bucket_dir}')
    return bucket_dir


def _find_corpus_file(bucket_dir: Path, patterns: list[str]) -> Path:
    files: list[Path] = []
    for pattern in patterns:
        files.extend(bucket_dir.glob(pattern))
    files = [p for p in files if p.is_file()]
    if not files:
        raise FileNotFoundError(f'No matching corpus files in {bucket_dir} for {patterns}')
    return max(files, key=lambda p: p.stat().st_mtime)


def _to_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _itunes_lookup(artist: str, title: str, timeout_s: float = 10.0) -> dict[str, Any]:
    query = urllib.parse.quote(f'{artist} {title}')
    url = f'https://itunes.apple.com/search?term={query}&entity=song&limit=5'
    request = urllib.request.Request(url, headers={'User-Agent': 'unicorn-viz-training/1.0'})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except Exception:
        return {}

    results = payload.get('results') if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results:
        return {}

    def _norm(text: Any) -> str:
        return str(text or '').strip().lower()

    artist_norm = _norm(artist)
    title_norm = _norm(title)

    exact = [
        r
        for r in results
        if _norm(r.get('artistName')) == artist_norm and _norm(r.get('trackName')) == title_norm
    ]
    if exact:
        return exact[0]

    artist_only = [r for r in results if _norm(r.get('artistName')) == artist_norm]
    if artist_only:
        return artist_only[0]

    return results[0]


def _build_track_facts(sequence_rows: list[dict[str, Any]], use_itunes: bool) -> list[TrackFact]:
    by_track: dict[str, dict[str, Any]] = {}

    for row in sequence_rows:
        track_id = str(row.get('track_id') or row.get('spotify_track_id') or '').strip()
        if not track_id:
            continue

        state = by_track.setdefault(
            track_id,
            {
                'track_id': track_id,
                'artist': str(row.get('track_artist') or row.get('spotify_artist') or 'unknown').strip(),
                'title': str(row.get('track_title') or row.get('spotify_title') or 'unknown').strip(),
                'album': str(row.get('track_album') or row.get('spotify_album') or 'unknown').strip(),
                'start_utc': str(row.get('analysis_generated_at') or ''),
                'end_utc': str(row.get('analysis_generated_at') or ''),
                'rows': 0,
                'bpm': [],
                'bpm_conf': [],
                'rms': [],
                'loudness': [],
                'dance': [],
                'profile_counter': Counter(),
            },
        )

        ts = str(row.get('analysis_generated_at') or '')
        if ts and (not state['start_utc'] or ts < state['start_utc']):
            state['start_utc'] = ts
        if ts and (not state['end_utc'] or ts > state['end_utc']):
            state['end_utc'] = ts

        state['rows'] += 1
        state['bpm'].append(_to_float(row.get('bpm')))
        state['bpm_conf'].append(_to_float(row.get('bpm_confidence')))
        state['rms'].append(_to_float(row.get('rms')))
        state['loudness'].append(_to_float(row.get('loudness')))
        state['dance'].append(_to_float(row.get('danceability')))
        profile = str(row.get('audio_profile_key') or row.get('profile') or 'unknown').strip()
        state['profile_counter'][profile] += 1

    ordered = sorted(by_track.values(), key=lambda item: item['start_utc'])
    tracks: list[TrackFact] = []
    for i, item in enumerate(ordered, start=1):
        metadata = _itunes_lookup(item['artist'], item['title']) if use_itunes else {}
        tracks.append(
            TrackFact(
                index=i,
                track_id=item['track_id'],
                artist=item['artist'],
                title=item['title'],
                album=item['album'],
                start_utc=item['start_utc'],
                end_utc=item['end_utc'],
                seq_rows=int(item['rows']),
                avg_bpm=statistics.fmean(item['bpm']) if item['bpm'] else 0.0,
                avg_bpm_conf=statistics.fmean(item['bpm_conf']) if item['bpm_conf'] else 0.0,
                avg_rms=statistics.fmean(item['rms']) if item['rms'] else 0.0,
                avg_loudness=statistics.fmean(item['loudness']) if item['loudness'] else 0.0,
                avg_danceability=statistics.fmean(item['dance']) if item['dance'] else 0.0,
                dominant_profile=item['profile_counter'].most_common(1)[0][0]
                if item['profile_counter']
                else 'unknown',
                metadata=metadata,
            )
        )
    return tracks


def _parse_scorecard(scorecard_path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not scorecard_path.exists():
        return data

    for line in scorecard_path.read_text(encoding='utf-8').splitlines():
        if line.startswith('- Sequence rows:'):
            data['sequence_rows'] = line.split('`')[1] if '`' in line else line.split(':', 1)[1].strip()
        elif line.startswith('- Live rows:'):
            data['live_rows'] = line.split('`')[1] if '`' in line else line.split(':', 1)[1].strip()
        elif line.startswith('- Duration:'):
            data['duration'] = line.split('`')[1] if '`' in line else line.split(':', 1)[1].strip()
        elif line.startswith('- BPM median:'):
            data['bpm_median'] = line.split('`')[1] if '`' in line else line.split(':', 1)[1].strip()
        elif line.startswith('- BPM range:'):
            data['bpm_range'] = line.split('`')[1] if '`' in line else line.split(':', 1)[1].strip()
        elif line.startswith('- Mode transitions:'):
            data['mode_transitions'] = line.split('`')[1] if '`' in line else line.split(':', 1)[1].strip()
        elif line.startswith('- Drop fires:'):
            data['drop_fires'] = line.split('`')[1] if '`' in line else line.split(':', 1)[1].strip()
        elif line.startswith('- Impact fires:'):
            data['impact_fires'] = line.split('`')[1] if '`' in line else line.split(':', 1)[1].strip()

    return data


def _extract_session_note(training_root: Path, set_name: str, bucket_name: str) -> str:
    session_log = training_root / 'SESSION_TRAINING_LOG.md'
    if not session_log.exists():
        return ''
    needle = f'session={set_name}/{bucket_name}'
    lines = session_log.read_text(encoding='utf-8').splitlines()
    for line in reversed(lines):
        if needle in line:
            return line.strip()
    return ''


def _profile_mix(sequence_rows: list[dict[str, Any]]) -> list[tuple[str, int]]:
    counter = Counter(str(r.get('audio_profile_key') or r.get('profile') or 'unknown') for r in sequence_rows)
    return counter.most_common()


def _local_set_summary(
    playlist_context: str,
    profile_mix: list[tuple[str, int]],
    tracks: list[TrackFact],
) -> str:
    """Build a data-driven Set Summary paragraph for local (non-LLM) mode."""
    track_count = len(tracks)
    bpms = [t.avg_bpm for t in tracks if t.avg_bpm > 0]
    bpm_mean = statistics.fmean(bpms) if bpms else 0.0
    bpm_lo = min(bpms) if bpms else 0.0
    bpm_hi = max(bpms) if bpms else 0.0

    genre_counter: Counter[str] = Counter(
        str(t.metadata.get('primaryGenreName'))
        for t in tracks
        if t.metadata.get('primaryGenreName')
    )
    top_genres = ', '.join(g for g, _ in genre_counter.most_common(4)) or 'n/a'
    top_profiles = ', '.join(p for p, _ in profile_mix[:3]) if profile_mix else 'n/a'

    return (
        f'This session contained {track_count} track{"s" if track_count != 1 else ""} '
        f'under the context "{playlist_context}". '
        f'BPM ranged from {bpm_lo:.0f} to {bpm_hi:.0f} (mean {bpm_mean:.0f}). '
        f'Catalog genres: {top_genres}. '
        f'Dominant VJ profiles: {top_profiles}.\n\n'
        f'This is a local auto-generated summary. Re-run with --use-llm for a '
        f'full musicological description of the set arc and track flow.'
    )


def _render_local_markdown(
    set_name: str,
    bucket_name: str,
    playlist_context: str,
    scorecard: dict[str, str],
    session_note: str,
    profile_mix: list[tuple[str, int]],
    tracks: list[TrackFact],
) -> str:
    date_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    profile_text = ', '.join(f'{k}={v}' for k, v in profile_mix[:6]) if profile_mix else 'n/a'

    lines: list[str] = []
    lines.append('# Training Set Description')
    lines.append('')
    lines.append(f'- Set: {set_name}')
    lines.append(f'- Bucket: {bucket_name}')
    lines.append(f'- Session Date (UTC): {date_utc}')
    lines.append(f"- Duration: {scorecard.get('duration', 'n/a')}")
    lines.append(f'- Source Playlist Context: {playlist_context}')
    lines.append('')
    lines.append('## Set Summary')
    lines.append('')
    lines.append(_local_set_summary(playlist_context, profile_mix, tracks))
    lines.append('')
    lines.append('## Snapshot Metrics')
    lines.append('')
    lines.append(f"- Sequence rows: {scorecard.get('sequence_rows', 'n/a')}")
    lines.append(f"- Live rows: {scorecard.get('live_rows', 'n/a')}")
    lines.append(f'- Profile mix: {profile_text}')
    lines.append(
        f"- BPM median/range: {scorecard.get('bpm_median', 'n/a')} / "
        f"{scorecard.get('bpm_range', 'n/a')}"
    )
    lines.append(
        f"- Director activity: modes={scorecard.get('mode_transitions', 'n/a')}, "
        f"drops={scorecard.get('drop_fires', 'n/a')}, impacts={scorecard.get('impact_fires', 'n/a')}"
    )
    lines.append(f'- Session notes: {session_note or "n/a"}')
    lines.append('')
    lines.append('## Track Flow (Chronological)')
    lines.append('')
    lines.append('|#|Start (UTC)|Artist|Title|Profile|Avg BPM|BPM Conf|Genre|Release|')
    lines.append('|---|---|---|---|---|---:|---:|---|---|')
    for t in tracks:
        release = str(t.metadata.get('releaseDate') or 'n/a')
        genre = str(t.metadata.get('primaryGenreName') or 'n/a')
        lines.append(
            f'|{t.index}|{t.start_utc}|{t.artist}|{t.title}|{t.dominant_profile}|'
            f'{t.avg_bpm:.3f}|{t.avg_bpm_conf:.3f}|{genre}|{release}|'
        )
    lines.append('')
    lines.append('## Per-Track Notes')
    lines.append('')
    for t in tracks:
        release = str(t.metadata.get('releaseDate') or 'n/a')
        genre = str(t.metadata.get('primaryGenreName') or 'n/a')
        lookup_artist = str(t.metadata.get('artistName') or 'n/a')
        lookup_track = str(t.metadata.get('trackName') or 'n/a')
        lines.append(f'### {t.index}. {t.artist} - {t.title}')
        lines.append(
            f'- Data: profile={t.dominant_profile}, avg_bpm={t.avg_bpm:.3f}, '
            f'bpm_conf={t.avg_bpm_conf:.3f}, loudness={t.avg_loudness:.3f}, '
            f'danceability={t.avg_danceability:.3f}, rows={t.seq_rows}'
        )
        lines.append(
            f'- Lookup: release={release}, genre={genre}, '
            f'catalog_artist={lookup_artist}, catalog_track={lookup_track}'
        )
        lines.append(
            '- Description: Rhythmic house-oriented selection used as a transition or '
            'anchor point within the set arc. Keep this note as a baseline and let the '
            'LLM expansion version add stronger musicological language when needed.'
        )
        lines.append('')
    lines.append('## Automation Notes')
    lines.append('')
    lines.append(f'- Template version: {TEMPLATE_VERSION}')
    lines.append('- Metadata source: iTunes Search API (best-match heuristic)')
    lines.append('- Confidence caveat: release/genre values are lookup-based and may map to remixes.')
    lines.append('- Follow-up prompt: compare this bucket against previous bucket and summarize delta.')
    lines.append('')

    return '\n'.join(lines)


def _extract_output_text(payload: dict[str, Any]) -> str:
    output_text = payload.get('output_text')
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = payload.get('output')
    if not isinstance(output, list):
        return ''

    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get('content')
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get('text')
            if isinstance(text, str):
                chunks.append(text)
    return '\n'.join(chunks).strip()


def _generate_with_llm(model: str, prompt_payload: dict[str, Any]) -> str:
    api_key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY is not set. Export it and rerun with --use-llm.')

    body = {
        'model': model,
        'input': [
            {'role': 'system', 'content': [{'type': 'input_text', 'text': SYSTEM_PROMPT}]},
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'input_text',
                        'text': (
                            'Generate markdown using the exact template below.\n\n'
                            f'Template:\n{PROMPT_TEMPLATE}\n\n'
                            f'Context JSON:\n{json.dumps(prompt_payload, indent=2)}'
                        ),
                    }
                ],
            },
        ],
        'temperature': 0.3,
    }

    request = urllib.request.Request(
        'https://api.openai.com/v1/responses',
        data=json.dumps(body).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )

    with urllib.request.urlopen(request, timeout=120.0) as response:
        payload = json.loads(response.read().decode('utf-8'))

    text = _extract_output_text(payload)
    if not text:
        raise RuntimeError('LLM response did not contain output text.')
    return text


def main() -> int:
    args = _parse_args()
    root = Path(__file__).resolve().parents[1]
    training_root = root / 'assets' / 'training'
    sets_root = training_root / 'sets'
    bucket_dir = _pick_bucket(sets_root, args.set_name, args.bucket)

    set_name = bucket_dir.parent.name
    bucket_name = bucket_dir.name

    # Derive playlist context from set name when not explicitly provided.
    playlist_context = args.playlist_context
    if not playlist_context:
        parts = set_name.split('-')
        if parts and parts[0].isdigit() and len(parts[0]) == 8:
            parts = parts[1:]
        playlist_context = ' '.join(parts) if parts else set_name

    sequence_path = _find_corpus_file(bucket_dir, ['sequence-corpus*.jsonl', 'sequence*.jsonl'])
    live_path = _find_corpus_file(bucket_dir, ['live-corpus*.jsonl', 'live-autovj*.jsonl', 'live*.jsonl'])
    scorecard_path = bucket_dir / 'scorecard.md'

    sequence_rows = _read_jsonl(sequence_path)
    live_rows = _read_jsonl(live_path)
    tracks = _build_track_facts(sequence_rows, use_itunes=not args.no_itunes_lookup)
    mix = _profile_mix(sequence_rows)
    scorecard = _parse_scorecard(scorecard_path)
    session_note = _extract_session_note(training_root, set_name, bucket_name)

    prompt_payload = {
        'template_version': TEMPLATE_VERSION,
        'set_name': set_name,
        'bucket_name': bucket_name,
        'playlist_context': playlist_context,
        'files': {
            'sequence_corpus': sequence_path.name,
            'live_corpus': live_path.name,
            'scorecard': scorecard_path.name if scorecard_path.exists() else None,
        },
        'snapshot': {
            'sequence_rows': len(sequence_rows),
            'live_rows': len(live_rows),
            'profile_mix': [{'profile': p, 'count': c} for p, c in mix],
            'scorecard': scorecard,
            'session_note': session_note,
        },
        'tracks': [
            {
                'index': t.index,
                'track_id': t.track_id,
                'artist': t.artist,
                'title': t.title,
                'album': t.album,
                'start_utc': t.start_utc,
                'end_utc': t.end_utc,
                'seq_rows': t.seq_rows,
                'avg_bpm': round(t.avg_bpm, 3),
                'avg_bpm_conf': round(t.avg_bpm_conf, 3),
                'avg_rms': round(t.avg_rms, 3),
                'avg_loudness': round(t.avg_loudness, 3),
                'avg_danceability': round(t.avg_danceability, 3),
                'dominant_profile': t.dominant_profile,
                'metadata': {
                    'releaseDate': t.metadata.get('releaseDate'),
                    'primaryGenreName': t.metadata.get('primaryGenreName'),
                    'artistName': t.metadata.get('artistName'),
                    'trackName': t.metadata.get('trackName'),
                    'collectionName': t.metadata.get('collectionName'),
                },
            }
            for t in tracks
        ],
    }

    context_path = bucket_dir / 'TRAINING_SET_DESCRIPTION_INPUT.json'
    context_path.write_text(json.dumps(prompt_payload, indent=2), encoding='utf-8')

    if args.use_llm:
        markdown = _generate_with_llm(args.model, prompt_payload)
    else:
        markdown = _render_local_markdown(
            set_name=set_name,
            bucket_name=bucket_name,
            playlist_context=playlist_context,
            scorecard=scorecard,
            session_note=session_note,
            profile_mix=mix,
            tracks=tracks,
        )

    if args.output_path:
        output_path = Path(args.output_path)
        if not output_path.is_absolute():
            output_path = (root / output_path).resolve()
    else:
        output_path = bucket_dir / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown.strip() + '\n', encoding='utf-8')

    print(f'Set: {set_name}')
    print(f'Bucket: {bucket_name}')
    print(f'Context JSON: {context_path}')
    print(f'Description: {output_path}')
    print(f'Mode: {"llm" if args.use_llm else "local"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
