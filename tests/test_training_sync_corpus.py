from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np


def _write_tone(path: Path, sample_rate: int = 44_100, duration_s: float = 1.0) -> None:
    t = np.arange(int(sample_rate * duration_s), dtype=np.float32) / sample_rate
    samples = (0.2 * np.sin(2.0 * math.pi * 440.0 * t)).astype(np.float32)
    pcm = (samples * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def test_sync_corpus_from_logs_populates_rows_with_spotify_metadata() -> None:
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        audio_path = tmp / 'moonwalk.wav'
        log_path = tmp / 'autovj-20260618T999999.jsonl'
        catalog_path = tmp / 'catalog.json'
        corpus_path = tmp / 'corpus.jsonl'

        _write_tone(audio_path)

        log_rows = [
            {
                't': 1.0,
                'action': 'detector_tick',
                'spotify_track_id': 'spotify:track:test123',
                'spotify_title': 'Moonwalk',
                'spotify_artist': 'DJ Test',
                'spotify_album': 'Test EP',
                'spotify_source': 'playerctl+webapi',
                'spotify_status': 'playing',
                'spotify_is_playing': True,
                'spotify_tags': ['house', 'peak-time'],
            },
            {
                't': 2.0,
                'action': 'effect_swap',
                'track_id': 'spotify:track:test123',
                'track_title': 'Moonwalk',
                'track_artist': 'DJ Test',
            },
        ]
        log_path.write_text('\n'.join(json.dumps(row) for row in log_rows) + '\n', encoding='utf-8')

        catalog_payload = {
            'spotify:track:test123': {
                'audio_path': str(audio_path),
                'track_title': 'Moonwalk',
                'track_artist': 'DJ Test',
                'track_album': 'Test EP',
            }
        }
        catalog_path.write_text(json.dumps(catalog_payload, indent=2) + '\n', encoding='utf-8')

        result = subprocess.run(
            [
                sys.executable,
                'drop-ins/training-kit-01/tools/training/sync_corpus_from_logs.py',
                str(log_path),
                '--catalog',
                str(catalog_path),
                '--corpus',
                str(corpus_path),
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )

        report = json.loads(result.stdout.strip())
        assert report['tracks_seen'] == 1
        assert report['tracks_synced'] == 1
        assert report['tracks_unresolved'] == 0

        actual_corpus = Path(report['corpus'])
        rows = [json.loads(line) for line in actual_corpus.read_text(encoding='utf-8').splitlines() if line.strip()]
        assert len(rows) == 1
        row = rows[0]
        assert row['spotify_track_id'] == 'spotify:track:test123'
        assert row['spotify_title'] == 'Moonwalk'
        assert row['spotify_artist'] == 'DJ Test'
        assert row['spotify_album'] == 'Test EP'
        assert row['analysis_status'] == 'ok'
        assert row['audio_path'] == str(audio_path.resolve())
        assert row['track_title'] == 'Moonwalk'
        assert row['track_artist'] == 'DJ Test'
