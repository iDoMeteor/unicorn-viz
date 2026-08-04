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


def test_build_live_training_row_pairs_now_playing_and_live_audio() -> None:
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
    }
    # Device name identifies the audio source as Spotify -- the corpus must
    # not surface that; it should be masked to the generic 'web player' label.
    state = SimpleNamespace(audio_source='Spotify Monitor', playlist_mode='auto')
    audio_manager = SimpleNamespace(
        get_profile_key=lambda: 'normie',
        get_profile=lambda: SimpleNamespace(name='Normie'),
        get_profile_bpm_range=lambda: (90, 130),
    )
    grid = SimpleNamespace(bpm=125.0, confidence=0.81)

    row = _build_live_training_row(audio, spotify, state, audio_manager, grid)

    assert row['analysis_status'] == 'ok'
    assert row['analysis_source'] == 'web-player+live-audio'
    assert row['track_id'] == 'spotify:track:test123'
    assert row['track_title'] == 'Moonwalk'
    assert row['track_artist'] == 'DJ Test'
    assert row['track_album'] == 'Test EP'
    assert row['track_status'] == 'playing'
    assert row['is_playing'] is True
    assert row['metadata_source'] == 'playerctl+webapi'
    assert row['change_counter'] == 7
    assert row['position_s'] == 90.0
    assert row['audio_source'] == 'web player'
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
    assert 'spotify_track_id' not in row
    assert 'spotify_title' not in row
    assert 'spotify_artist' not in row
    assert 'spotify_album' not in row
    assert 'bpm_confidence' in row and 'feature_confidence' not in row
    assert 'spotify_bpm' not in row
    assert 'spotify_energy' not in row
    assert 'spotify_danceability' not in row
    assert 'spotify_valence' not in row


def test_build_live_training_row_passes_through_non_spotify_source() -> None:
    """A source label that doesn't mention Spotify is left untouched."""
    audio = SimpleNamespace(
        waveform=np.asarray([0.0, 0.5, -0.25, 0.25], dtype=np.float32),
        bass_n=0.20, mid_n=0.40, treble_n=0.60, bpm=123.0,
    )
    spotify: dict = {}
    state = SimpleNamespace(audio_source='Line In', playlist_mode='auto')
    audio_manager = None
    grid = SimpleNamespace(bpm=125.0, confidence=0.81)

    row = _build_live_training_row(audio, spotify, state, audio_manager, grid)

    assert row['audio_source'] == 'Line In'


def test_live_corpus_writer_persists_latest_row(tmp_path: Path) -> None:
    corpus_path = tmp_path / 'live-autovj.jsonl'
    writer = LiveCorpusWriter(corpus_path, True, 1.0)

    row = {
        'analysis_status': 'ok',
        'track_id': 'spotify:track:test123',
        'track_title': 'Moonwalk',
        'track_artist': 'DJ Test',
        'analysis_generated_at': '2026-06-18T12:00:00+00:00',
    }

    assert writer.upsert(row, force_flush=True) is True
    assert corpus_path.exists()

    rows = [json.loads(line) for line in corpus_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]['track_id'] == 'spotify:track:test123'
    assert rows[0]['track_title'] == 'Moonwalk'
    assert rows[0]['track_artist'] == 'DJ Test'


def test_spotify_snapshot_prefers_active_now_playing_hub() -> None:
    """_spotify_snapshot() must read the aggregated now-playing hub first, so
    a dj-mixer or media session trains the same as a Spotify one."""
    class FakeVjApi:
        def active_now_playing(self):
            return ('dj_mixer', {'title': 'Test Track', 'source': 'dj_mixer'})

        def get_subsystem(self, name):
            raise AssertionError('must not fall back when the hub has an active source')

    stub = SimpleNamespace(_app=SimpleNamespace(vj_api=FakeVjApi()))
    snap = _AUTO_VJ_MODULE.AutoVJController._spotify_snapshot(stub)
    assert snap == {'title': 'Test Track', 'source': 'dj_mixer'}


def test_spotify_snapshot_falls_back_to_spotify_subsystem_when_hub_empty() -> None:
    class FakeSpotifySubsystem:
        def snapshot(self):
            return {'title': 'Fallback', 'source': 'spotify'}

    class FakeVjApi:
        def active_now_playing(self):
            return None

        def get_subsystem(self, name):
            assert name == 'spotify'
            return FakeSpotifySubsystem()

    stub = SimpleNamespace(_app=SimpleNamespace(vj_api=FakeVjApi()))
    snap = _AUTO_VJ_MODULE.AutoVJController._spotify_snapshot(stub)
    assert snap == {'title': 'Fallback', 'source': 'spotify'}


def test_spotify_snapshot_falls_back_on_older_core_without_hub_accessor() -> None:
    """Degrades gracefully when vj_api has no active_now_playing() (older core)."""
    class FakeSpotifySubsystem:
        def snapshot(self):
            return {'title': 'Old Core'}

    class FakeVjApiNoHub:
        def get_subsystem(self, name):
            return FakeSpotifySubsystem()

    stub = SimpleNamespace(_app=SimpleNamespace(vj_api=FakeVjApiNoHub()))
    snap = _AUTO_VJ_MODULE.AutoVJController._spotify_snapshot(stub)
    assert snap == {'title': 'Old Core'}


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
