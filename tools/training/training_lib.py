"""Shared helpers for the local offline training toolchain.

The training scaffold keeps the live runtime separate from offline corpus
building and weight fitting. This module owns the shared mechanics for that
pipeline: discovering audio inputs, extracting audio features when available,
serializing rows, and fitting a small ridge-regression weight set from
labeled examples.

Essentia is optional. When present, the offline corpus builders can extract
richer tempo, beat, and key metadata from local files. When absent, the
helpers fall back to lightweight numpy-derived summary fields so training data
contributors do not need the extra dependency.
"""

from __future__ import annotations

import json
import math
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

DEFAULT_SAMPLE_RATE = 44_100
DEFAULT_AUDIO_EXTENSIONS = {
    '.aac',
    '.aif',
    '.aiff',
    '.flac',
    '.m4a',
    '.mp3',
    '.ogg',
    '.wav',
    '.wma',
}
DEFAULT_FEATURE_COLUMNS = [
    'duration_s',
    'rms',
    'peak_amplitude',
    'crest_factor',
    'loudness',
    'bpm',
    'bpm_confidence',
    'beat_count',
    'beat_density',
    'danceability',
    'key_sin',
    'key_cos',
    'is_minor',
    'key_strength',
]
_KEY_TO_INDEX = {
    'C': 0,
    'C#': 1,
    'DB': 1,
    'D': 2,
    'D#': 3,
    'EB': 3,
    'E': 4,
    'F': 5,
    'F#': 6,
    'GB': 6,
    'G': 7,
    'G#': 8,
    'AB': 8,
    'A': 9,
    'A#': 10,
    'BB': 10,
    'B': 11,
}
_TRACK_ID_KEYS = ('spotify_track_id', 'track_id', 'trackId', 'raw_track_id')
_SPOTIFY_LOG_FIELDS = (
    'spotify_title',
    'spotify_artist',
    'spotify_album',
    'spotify_source',
    'spotify_status',
    'spotify_is_playing',
    'spotify_duration_s',
    'spotify_position_s',
    'spotify_change_counter',
    'spotify_bpm_hint',
    'spotify_bpm_hint_confidence',
    'spotify_tag_hint_confidence',
    'spotify_tags',
    'track_title',
    'track_artist',
    'track_album',
    'track_source',
    'audio_profile_key',
    'audio_profile_name',
    'audio_profile_bpm_range',
    'audio_profile_bpm_min',
    'audio_profile_bpm_max',
    'profile',
    'mode',
)


@dataclass(frozen=True, slots=True)
class RidgeFitResult:
    """Container for the fitted regression weights and summary metrics."""

    feature_columns: list[str]
    feature_means: dict[str, float]
    feature_stds: dict[str, float]
    weights: dict[str, float]
    bias: float
    metrics: dict[str, float]


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def as_jsonable(value: Any) -> Any:
    """Recursively convert numpy and pathlib objects into JSON-safe values."""

    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return [as_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): as_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [as_jsonable(item) for item in value]
    return value


def canonicalize_track_id(track_id: str) -> str:
    """Normalize Spotify track identifiers into a single canonical form."""

    raw = str(track_id or '').strip()
    if not raw:
        return ''
    lowered = raw.lower()
    if lowered.startswith('spotify:track:'):
        return lowered
    if lowered.startswith('/com/spotify/track/'):
        suffix = lowered.rsplit('/', 1)[-1]
        return f'spotify:track:{suffix}' if suffix else lowered
    if lowered.startswith('https://open.spotify.com/track/'):
        tail = lowered.split('/track/', 1)[-1].split('?', 1)[0].split('/', 1)[0]
        return f'spotify:track:{tail}' if tail else lowered
    return lowered


def _normalize_text(value: Any) -> str:
    text = str(value or '').strip().lower()
    return ' '.join(text.split())


def _load_json_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding='utf-8').strip()
    if not text:
        return []
    if text.startswith('[') or text.startswith('{'):
        payload = json.loads(text)
        if isinstance(payload, list):
            return [dict(item) for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            rows: list[dict[str, Any]] = []
            for key, value in payload.items():
                if isinstance(value, dict):
                    row = dict(value)
                    row.setdefault('spotify_track_id', key)
                    rows.append(row)
            return rows
        return []
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if isinstance(payload, dict):
            rows.append(dict(payload))
    return rows


def load_track_catalog(catalog_path: Path) -> dict[str, dict[str, Any]]:
    """Load a local audio catalog keyed by Spotify track id and metadata."""

    catalog: dict[str, dict[str, Any]] = {}
    for entry in _load_json_records(catalog_path):
        track_id = canonicalize_track_id(
            entry.get('spotify_track_id')
            or entry.get('track_id')
            or entry.get('trackId')
            or entry.get('raw_track_id')
            or ''
        )
        if not track_id:
            continue
        payload = dict(entry)
        payload['spotify_track_id'] = track_id
        audio_path = payload.pop('audio_path', payload.pop('path', None))
        if audio_path is not None:
            payload['audio_path'] = str(Path(audio_path).expanduser())
        catalog[track_id] = payload
    return catalog


def collect_spotify_log_metadata(log_paths: Sequence[Path]) -> dict[str, dict[str, Any]]:
    """Collect useful Spotify metadata from Auto VJ logs keyed by track id."""

    track_map: dict[str, dict[str, Any]] = {}
    for path in log_paths:
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except Exception:
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except Exception:
                continue
            track_id = ''
            for key in _TRACK_ID_KEYS:
                candidate = canonicalize_track_id(str(row.get(key, '') or '').strip())
                if candidate.startswith('spotify:track:'):
                    track_id = candidate
                    break
            if not track_id:
                continue
            payload = track_map.setdefault(track_id, {'spotify_track_id': track_id})
            payload.setdefault('log_actions', [])
            action = str(row.get('action') or '').strip()
            if action and action not in payload['log_actions']:
                payload['log_actions'].append(action)
            for field in _SPOTIFY_LOG_FIELDS:
                value = row.get(field)
                if value in (None, '', [], {}):
                    continue
                if field in {'spotify_duration_s', 'spotify_position_s', 'spotify_change_counter', 'spotify_bpm_hint', 'spotify_bpm_hint_confidence', 'spotify_tag_hint_confidence', 'audio_profile_bpm_min', 'audio_profile_bpm_max'}:
                    try:
                        payload[field] = float(value)
                    except (TypeError, ValueError):
                        continue
                    continue
                if field == 'spotify_is_playing':
                    payload[field] = bool(value)
                    continue
                if field == 'spotify_tags':
                    if isinstance(value, list):
                        payload[field] = [str(item) for item in value if str(item).strip()]
                    elif isinstance(value, str):
                        payload[field] = [part.strip() for part in value.split(',') if part.strip()]
                    continue
                payload[field] = value
            track_title = str(row.get('track_title') or row.get('spotify_title') or '').strip()
            track_artist = str(row.get('track_artist') or row.get('spotify_artist') or '').strip()
            track_album = str(row.get('track_album') or row.get('spotify_album') or '').strip()
            if track_title and 'track_title' not in payload:
                payload['track_title'] = track_title
            if track_artist and 'track_artist' not in payload:
                payload['track_artist'] = track_artist
            if track_album and 'track_album' not in payload:
                payload['track_album'] = track_album
            if 't' in row and 'first_seen_t' not in payload:
                try:
                    payload['first_seen_t'] = float(row['t'])
                except (TypeError, ValueError):
                    pass
    return track_map


def track_catalog_by_identity(catalog: Mapping[str, dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Build a metadata lookup for catalog fallback resolution."""

    identity_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    for entry in catalog.values():
        key = (
            _normalize_text(entry.get('track_title') or entry.get('spotify_title')),
            _normalize_text(entry.get('track_artist') or entry.get('spotify_artist')),
            _normalize_text(entry.get('track_album') or entry.get('spotify_album')),
        )
        if key[0] and key[1]:
            identity_map[key] = entry
    return identity_map


def resolve_catalog_entry(
    track_id: str,
    track_meta: Mapping[str, Any],
    catalog: Mapping[str, dict[str, Any]],
    identity_catalog: Mapping[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    """Resolve a log track to a catalog entry via id or Spotify metadata."""

    canonical = canonicalize_track_id(track_id)
    if canonical and canonical in catalog:
        return dict(catalog[canonical])
    identity_key = (
        _normalize_text(track_meta.get('track_title') or track_meta.get('spotify_title')),
        _normalize_text(track_meta.get('track_artist') or track_meta.get('spotify_artist')),
        _normalize_text(track_meta.get('track_album') or track_meta.get('spotify_album')),
    )
    if identity_key[0] and identity_key[1]:
        entry = identity_catalog.get(identity_key)
        if entry is not None:
            return dict(entry)
    return None


def iter_audio_files(paths: Sequence[Path], recursive: bool) -> list[Path]:
    """Return the unique audio files discovered under the provided paths."""

    audio_files: dict[str, Path] = {}
    for path in paths:
        if path.is_dir():
            pattern = '**/*' if recursive else '*'
            for child in path.glob(pattern):
                if child.is_file() and child.suffix.lower() in DEFAULT_AUDIO_EXTENSIONS:
                    audio_files[str(child.resolve())] = child.resolve()
            continue
        if path.is_file() and path.suffix.lower() in DEFAULT_AUDIO_EXTENSIONS:
            audio_files[str(path.resolve())] = path.resolve()
    return [audio_files[key] for key in sorted(audio_files)]


def load_manifest_entries(manifest_path: Path) -> list[dict[str, Any]]:
    """Load manifest entries from JSON or JSONL."""

    if not manifest_path.exists():
        raise FileNotFoundError(f'manifest not found: {manifest_path}')
    text = manifest_path.read_text(encoding='utf-8').strip()
    if not text:
        return []
    if text.startswith('['):
        payload = json.loads(text)
        if not isinstance(payload, list):
            raise ValueError('manifest JSON must be a list of records')
        return [dict(item) for item in payload]
    entries: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError('manifest JSONL rows must be objects')
        entries.append(dict(payload))
    return entries


def collect_source_map(
    inputs: Sequence[str],
    manifest_path: Path | None,
    recursive: bool,
) -> dict[Path, dict[str, Any]]:
    """Collect audio paths and any per-item metadata into a source map."""

    source_map: dict[Path, dict[str, Any]] = {}

    def _merge(path_value: Path, metadata: Mapping[str, Any]) -> None:
        resolved = path_value.resolve()
        existing = source_map.setdefault(resolved, {})
        for key, value in metadata.items():
            if key in {'audio_path', 'path'}:
                continue
            existing[key] = value

    if manifest_path is not None:
        manifest_base = manifest_path.resolve().parent
        for entry in load_manifest_entries(manifest_path):
            raw_path = entry.get('audio_path', entry.get('path'))
            if raw_path is None:
                raise ValueError('manifest rows must include audio_path or path')
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = manifest_base / candidate
            _merge(candidate, entry)

    input_paths = [Path(item) for item in inputs]
    for audio_path in iter_audio_files(input_paths, recursive=recursive):
        _merge(audio_path, {})

    return source_map


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _key_to_features(key_name: str, scale_name: str) -> tuple[int, float, float, int]:
    key_index = _KEY_TO_INDEX.get(key_name.strip().upper(), -1)
    angle = (2.0 * math.pi * key_index / 12.0) if key_index >= 0 else 0.0
    is_minor = 1 if scale_name.strip().lower().startswith('minor') else 0
    return key_index, math.sin(angle), math.cos(angle), is_minor


def extract_audio_features(audio_path: Path, sample_rate: int = DEFAULT_SAMPLE_RATE) -> dict[str, Any]:
    """Extract summary features from a single audio file.

    Uses Essentia when available and falls back to lightweight numpy-derived
    summary stats when the optional dependency is missing.
    """

    try:
        import essentia.standard as es
    except Exception:
        es = None

    if es is not None:
        loader = es.MonoLoader(filename=str(audio_path), sampleRate=sample_rate)
        audio = np.asarray(loader(), dtype=np.float32)
        if audio.size == 0:
            raise ValueError('audio file produced no samples')
    else:
        try:
            with wave.open(str(audio_path), 'rb') as handle:
                sample_rate = int(handle.getframerate()) or sample_rate
                channels = max(1, int(handle.getnchannels()))
                sampwidth = int(handle.getsampwidth())
                frame_count = int(handle.getnframes())
                raw_audio = handle.readframes(frame_count)
        except Exception as exc:
            raise RuntimeError(
                'Essentia is unavailable and the stdlib WAV fallback could not read the file'
            ) from exc
        if sampwidth != 2:
            raise RuntimeError(
                'Essentia is unavailable and the WAV fallback only supports 16-bit PCM input'
            )
        audio = np.frombuffer(raw_audio, dtype='<i2').astype(np.float32)
        if channels > 1:
            audio = audio.reshape(-1, channels).mean(axis=1)
        audio /= 32768.0
        if audio.size == 0:
            raise ValueError('audio file produced no samples')

    rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
    peak = float(np.max(np.abs(audio)))
    crest_factor = float(peak / rms) if rms > 0.0 else 0.0
    duration_s = float(audio.size / sample_rate)
    beat_count = 0
    beat_density = 0.0
    bpm = 0.0
    bpm_confidence = 0.0
    danceability = 0.0
    loudness = 0.0
    key_name = 'unknown'
    scale_name = 'unknown'
    key_strength = 0.0

    if es is not None:
        try:
            bpm, beats, bpm_confidence, _, _ = es.RhythmExtractor2013()(audio)
            beat_count = int(len(beats))
            beat_density = float(beat_count / duration_s) if duration_s > 0.0 else 0.0
        except Exception:
            beats = np.zeros(0, dtype=np.float32)

        try:
            danceability, _ = es.Danceability()(audio)
        except Exception:
            danceability = 0.0

        try:
            loudness = float(es.Loudness()(audio))
        except Exception:
            loudness = 0.0

        try:
            key_name, scale_name, key_strength = es.KeyExtractor()(audio)
        except Exception:
            key_name = 'unknown'
            scale_name = 'unknown'
            key_strength = 0.0
    else:
        beat_count = 0
        beat_density = 0.0
        bpm = 0.0
        bpm_confidence = 0.0
        danceability = float(min(1.0, rms * 3.0))
        loudness = float(20.0 * np.log10(max(rms, 1e-6)))
        key_name = 'unknown'
        scale_name = 'unknown'
        key_strength = 0.0

    key_index, key_sin, key_cos, is_minor = _key_to_features(key_name, scale_name)

    return {
        'analysis_status': 'ok',
        'audio_path': str(audio_path.resolve()),
        'sample_rate': sample_rate,
        'duration_s': duration_s,
        'rms': rms,
        'peak_amplitude': peak,
        'crest_factor': crest_factor,
        'loudness': loudness,
        'bpm': _safe_float(bpm),
        'bpm_confidence': _safe_float(bpm_confidence),
        'beat_count': beat_count,
        'beat_density': beat_density,
        'danceability': _safe_float(danceability),
        'key': key_name,
        'scale': scale_name,
        'key_index': key_index,
        'key_sin': key_sin,
        'key_cos': key_cos,
        'is_minor': is_minor,
        'key_strength': _safe_float(key_strength),
    }


def write_jsonl(rows: Iterable[Mapping[str, Any]], output_path: Path) -> int:
    """Write an iterable of mappings to a JSONL file and return the row count."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open('w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(as_jsonable(dict(row)), sort_keys=True))
            handle.write('\n')
            count += 1
    return count


def load_jsonl_rows(corpus_path: Path) -> list[dict[str, Any]]:
    """Load corpus rows from a JSONL file."""

    if not corpus_path.exists():
        raise FileNotFoundError(f'corpus not found: {corpus_path}')
    rows: list[dict[str, Any]] = []
    for line in corpus_path.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError('corpus rows must be JSON objects')
        rows.append(payload)
    return rows


def fit_ridge_weights(
    rows: Sequence[Mapping[str, Any]],
    target_column: str,
    feature_columns: Sequence[str],
    ridge: float,
) -> RidgeFitResult:
    """Fit a ridge-regression model over the requested corpus rows."""

    feature_rows: list[list[float]] = []
    target_values: list[float] = []
    for row in rows:
        if row.get('analysis_status') not in (None, 'ok'):
            continue
        if target_column not in row:
            continue
        try:
            target_value = float(row[target_column])
        except (TypeError, ValueError):
            continue
        try:
            features = [float(row[column]) for column in feature_columns]
        except (TypeError, ValueError, KeyError):
            continue
        feature_rows.append(features)
        target_values.append(target_value)

    if not feature_rows:
        raise ValueError(
            f'no labeled rows available for target column {target_column!r}'
        )

    matrix = np.asarray(feature_rows, dtype=np.float64)
    target = np.asarray(target_values, dtype=np.float64)
    feature_means = matrix.mean(axis=0)
    feature_stds = matrix.std(axis=0)
    feature_stds = np.where(feature_stds < 1e-8, 1.0, feature_stds)
    normalized = (matrix - feature_means) / feature_stds
    design = np.column_stack([np.ones(normalized.shape[0], dtype=np.float64), normalized])
    regularizer = np.eye(design.shape[1], dtype=np.float64) * float(ridge)
    regularizer[0, 0] = 0.0
    coefficients = np.linalg.solve(design.T @ design + regularizer, design.T @ target)
    bias = float(coefficients[0])
    weights = coefficients[1:]
    predictions = design @ coefficients
    residual = target - predictions
    rmse = float(np.sqrt(np.mean(np.square(residual))))
    mae = float(np.mean(np.abs(residual)))
    target_variance = float(np.var(target))
    r2 = 1.0 - float(np.var(residual) / target_variance) if target_variance > 1e-12 else 0.0

    return RidgeFitResult(
        feature_columns=list(feature_columns),
        feature_means={column: float(mean) for column, mean in zip(feature_columns, feature_means)},
        feature_stds={column: float(std) for column, std in zip(feature_columns, feature_stds)},
        weights={column: float(weight) for column, weight in zip(feature_columns, weights)},
        bias=bias,
        metrics={
            'row_count': float(len(feature_rows)),
            'rmse': rmse,
            'mae': mae,
            'r2': r2,
            'ridge': float(ridge),
        },
    )