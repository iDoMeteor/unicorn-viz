from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_AUTO_VJ_SPEC = importlib.util.spec_from_file_location('test_auto_vj_live_training_module', _AUTO_VJ_PATH)
assert _AUTO_VJ_SPEC is not None and _AUTO_VJ_SPEC.loader is not None
_AUTO_VJ_MODULE = importlib.util.module_from_spec(_AUTO_VJ_SPEC)
_AUTO_VJ_SPEC.loader.exec_module(_AUTO_VJ_MODULE)

_build_live_training_row = _AUTO_VJ_MODULE._build_live_training_row
LiveCorpusWriter = _AUTO_VJ_MODULE.LiveCorpusWriter


def test_build_live_training_row_pairs_spotify_and_live_audio() -> None:
    audio = SimpleNamespace(
        waveform=np.asarray([0.0, 0.5, -0.25, 0.25], dtype=np.float32),
        bass_n=0.20,
        mid_n=0.40,
        treble_n=0.60,
        bpm=123.0,
    )
    spotify = {
        'track_id': 'spotify:track:test123',
        'title': 'Moonwalk',
        'artist': 'DJ Test',
        'album': 'Test EP',
        'status': 'playing',
        'is_playing': True,
        'source': 'playerctl+webapi',
        'change_counter': 7,
        'duration_s': 180.0,
        'position_s': 90.0,
        'progress': 0.5,
        'feature_confidence': 0.87,
        'tag_confidence': 0.62,
        'bpm': 124.0,
        'energy': 0.81,
        'danceability': 0.74,
        'valence': 0.41,
        'tags': ['house', 'chillstep'],
        'genres': ['electronic'],
    }
    state = SimpleNamespace(audio_source='Spotify Monitor', playlist_mode='auto')
    audio_manager = SimpleNamespace(
        get_profile_key=lambda: 'normie',
        get_profile=lambda: SimpleNamespace(name='Normie'),
        get_profile_bpm_range=lambda: (90, 130),
    )
    grid = SimpleNamespace(bpm=125.0, confidence=0.81)

    row = _build_live_training_row(audio, spotify, state, audio_manager, grid)

    assert row['analysis_status'] == 'ok'
    assert row['analysis_source'] == 'spotify+live-audio'
    assert row['spotify_track_id'] == 'spotify:track:test123'
    assert row['spotify_title'] == 'Moonwalk'
    assert row['spotify_artist'] == 'DJ Test'
    assert row['spotify_album'] == 'Test EP'
    assert row['audio_source'] == 'Spotify Monitor'
    assert row['audio_profile_key'] == 'normie'
    assert row['audio_profile_name'] == 'Normie'
    assert row['audio_profile_bpm_range'] == '90-130'
    assert row['bpm'] == 125.0
    assert row['bpm_confidence'] == 0.81
    assert row['rms'] > 0.0
    assert row['peak_amplitude'] > 0.0
    assert row['crest_factor'] > 1.0
    assert row['duration_s'] == 180.0
    assert row['progress'] == 0.5


def test_live_corpus_writer_persists_latest_row(tmp_path: Path) -> None:
    corpus_path = tmp_path / 'live-autovj.jsonl'
    writer = LiveCorpusWriter(corpus_path, True, 1.0)

    row = {
        'analysis_status': 'ok',
        'spotify_track_id': 'spotify:track:test123',
        'spotify_title': 'Moonwalk',
        'spotify_artist': 'DJ Test',
        'analysis_generated_at': '2026-06-18T12:00:00+00:00',
    }

    assert writer.upsert(row, force_flush=True) is True
    assert corpus_path.exists()

    rows = [json.loads(line) for line in corpus_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]['spotify_track_id'] == 'spotify:track:test123'
    assert rows[0]['spotify_title'] == 'Moonwalk'
    assert rows[0]['spotify_artist'] == 'DJ Test'


def test_build_live_training_row_falls_back_when_normalized_bands_missing() -> None:
    audio = SimpleNamespace(
        waveform=np.asarray([0.0, 0.5, -0.25, 0.25], dtype=np.float32),
        bass=0.30,
        mid=0.20,
        treble=0.10,
        bpm=126.0,
    )
    spotify = {
        'track_id': 'spotify:track:test123',
        'title': 'Moonwalk',
        'artist': 'DJ Test',
        'album': 'Test EP',
        'status': 'playing',
        'is_playing': True,
        'duration_s': 180.0,
        'position_s': 90.0,
        'progress': 0.5,
    }
    state = SimpleNamespace(audio_source='Line In', playlist_mode='auto')
    audio_manager = SimpleNamespace(
        get_profile_key=lambda: 'normie',
        get_profile=lambda: SimpleNamespace(name='Normie'),
        get_profile_bpm_range=lambda: (90, 130),
    )
    grid = SimpleNamespace(bpm=126.0, confidence=0.70)

    row = _build_live_training_row(audio, spotify, state, audio_manager, grid)

    assert row['analysis_status'] == 'ok'
    assert row['bpm'] == 126.0
    assert row['bpm_confidence'] == 0.70
    assert row['danceability'] == pytest.approx(0.205)
