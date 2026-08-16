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
        'genre': 'Deep House',
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
    assert row['track_genre'] == 'Deep House'
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


def test_build_live_training_row_genre_defaults_empty_when_source_omits_it() -> None:
    """Most now-playing sources (Spotify, media-01) never populate 'genre'
    -- only dj-mixer-01 does, from the loaded track's ID3 tag. Must default
    to '' rather than raise, same as every other optional now-playing key."""
    audio = SimpleNamespace(
        waveform=np.asarray([0.0, 0.5, -0.25, 0.25], dtype=np.float32),
        bass_n=0.20, mid_n=0.40, treble_n=0.60, bpm=123.0,
    )
    spotify = {'track_id': 'spotify:track:test123', 'title': 'Moonwalk'}
    state = SimpleNamespace(audio_source='Spotify Monitor', playlist_mode='auto')
    audio_manager = None
    grid = SimpleNamespace(bpm=125.0, confidence=0.81)

    row = _build_live_training_row(audio, spotify, state, audio_manager, grid)

    assert row['track_genre'] == ''


def test_build_live_training_row_decodes_camelot_key_from_now_playing() -> None:
    """2026-08-10: 'key' (Camelot code, e.g. dj-mixer-01's analyzer output)
    is decoded into the corpus row's key/scale/key_index/key_sin/key_cos/
    is_minor schema instead of staying a permanent 'unknown' placeholder."""
    audio = SimpleNamespace(
        waveform=np.asarray([0.0, 0.5, -0.25, 0.25], dtype=np.float32),
        bass_n=0.20, mid_n=0.40, treble_n=0.60, bpm=123.0,
    )
    spotify = {'track_id': 'dj_mixer:test', 'title': 'Moonwalk', 'key': '8A'}
    state = SimpleNamespace(audio_source='dj_mixer', playlist_mode='auto')
    audio_manager = None
    grid = SimpleNamespace(bpm=125.0, confidence=0.81)

    row = _build_live_training_row(audio, spotify, state, audio_manager, grid)

    assert row['key'] == 'A minor'
    assert row['key_camelot'] == '8A'
    assert row['scale'] == 'minor'
    assert row['is_minor'] == 1
    assert row['key_index'] == 7
    assert row['key_sin'] == pytest.approx(np.sin(2 * np.pi * 7 / 12), abs=1e-5)
    assert row['key_cos'] == pytest.approx(np.cos(2 * np.pi * 7 / 12), abs=1e-5)


def test_build_live_training_row_key_placeholder_when_absent_or_unrecognized() -> None:
    """No 'key' in now-playing (most sources), or a code the Camelot table
    doesn't recognize, both fall back to the same 'unknown' placeholder --
    never raises."""
    audio = SimpleNamespace(
        waveform=np.asarray([0.0, 0.5, -0.25, 0.25], dtype=np.float32),
        bass_n=0.20, mid_n=0.40, treble_n=0.60, bpm=123.0,
    )
    state = SimpleNamespace(audio_source='Line In', playlist_mode='auto')
    grid = SimpleNamespace(bpm=125.0, confidence=0.81)

    row = _build_live_training_row(audio, {}, state, None, grid)
    assert row['key'] == 'unknown'
    assert row['key_camelot'] == ''
    assert row['scale'] == 'unknown'
    assert row['key_index'] == -1
    assert row['is_minor'] == 0

    row = _build_live_training_row(audio, {'key': 'not-a-real-code'}, state, None, grid)
    assert row['key'] == 'unknown'


def test_build_live_training_row_captures_mixer_bpm_and_section_hint() -> None:
    """2026-08-10: the mixer's raw BPM hint and its song-structure hint
    (previously read only for live phrase-bias decisions, never written to
    any corpus row -- see docs/adr/vj-system.md) now reach every corpus row
    this function builds, prefixed section_* to avoid collisions."""
    audio = SimpleNamespace(
        waveform=np.asarray([0.0, 0.5, -0.25, 0.25], dtype=np.float32),
        bass_n=0.20, mid_n=0.40, treble_n=0.60, bpm=123.0,
    )
    state = SimpleNamespace(audio_source='dj_mixer', playlist_mode='auto')
    grid = SimpleNamespace(bpm=125.0, confidence=0.81)
    section_hint = {
        'role': 'PEAK', 'tier': 'major', 'label': 'drop',
        'bars_in': 2.0, 'bars_left': 6.0, 'confidence': 0.9,
        'next_role': 'FALL', 'next_label': 'breakdown', 'bars_to_next': 6.0,
    }

    row = _build_live_training_row(
        audio, {}, state, None, grid,
        mixer_bpm=128.5, section_hint=section_hint,
        track_path='/music/crates/track.mp3',
    )

    assert row['mixer_bpm'] == 128.5
    assert row['track_path'] == '/music/crates/track.mp3'
    assert row['section_role'] == 'PEAK'
    assert row['section_tier'] == 'major'
    assert row['section_label'] == 'drop'
    assert row['section_bars_in'] == 2.0
    assert row['section_bars_left'] == 6.0
    assert row['section_confidence'] == 0.9
    assert row['section_next_role'] == 'FALL'
    assert row['section_next_label'] == 'breakdown'
    assert row['section_bars_to_next'] == 6.0
    # next_tier wasn't in the hint dict -- not fabricated as a key.
    assert 'section_next_tier' not in row


def test_build_live_training_row_mixer_bpm_and_section_default_when_absent() -> None:
    audio = SimpleNamespace(
        waveform=np.asarray([0.0, 0.5, -0.25, 0.25], dtype=np.float32),
        bass_n=0.20, mid_n=0.40, treble_n=0.60, bpm=123.0,
    )
    state = SimpleNamespace(audio_source='Line In', playlist_mode='auto')
    grid = SimpleNamespace(bpm=125.0, confidence=0.81)

    row = _build_live_training_row(audio, {}, state, None, grid)

    assert row['mixer_bpm'] == 0.0
    assert row['track_path'] == ''
    assert 'section_role' not in row


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


class _FakeSequenceCorpusWriter:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def should_capture_heartbeat(self, now, beat_index, interval_s) -> bool:
        return True

    def append(self, row: dict, *, is_keyframe: bool, event_id: str = '') -> bool:
        self.rows.append(row)
        return True


def _make_sequence_heartbeat_stub(*, writer=None):
    """Minimal AutoVJController-like stub for _record_sequence_heartbeat().

    self._grid stays None -- _detector_snapshot() already has a graceful
    all-defaults path for that case, which keeps this stub focused on the
    version-stamping logic under test rather than every detector field.
    _sequence_director_fields/_detector_snapshot are wired to the real
    unbound methods (not re-implemented here) since _record_sequence_
    heartbeat() calls them as self.<method>(...), which a plain
    SimpleNamespace won't resolve without an explicit attribute.
    """
    stub = SimpleNamespace(
        _sequence_corpus_writer=writer if writer is not None else _FakeSequenceCorpusWriter(),
        _grid=None,
        _audio_manager=None,
        _shadow_grid=None,
        _shadow2_grid=None,
        _sequence_training_heartbeat_interval_s=1.0,
        _version_stamped_this_session=False,
        _mode='CRUISE',
        _profile='chill',
        _bars_since_track_start=0,
        _bars_since_phase_entry=0,
        _phrase_neutral_bars_left=0,
        _recommended_profile_key='',
        _compute_kick_regularity=lambda: 0.5,
        _get_mixer_bpm=lambda: 0.0,
        _get_mixer_track_path=lambda: '',
        _get_section_hint=lambda: None,
        # Class attributes on the real AutoVJController -- a plain
        # SimpleNamespace doesn't inherit them, so _detector_snapshot()
        # (which reads self._BPM_LOCK_CONFIDENCE/_RELEASE_CONFIDENCE)
        # needs them stubbed explicitly. Values match the real defaults.
        _BPM_LOCK_CONFIDENCE=0.55,
        _BPM_LOCK_RELEASE_CONFIDENCE=0.28,
    )
    stub._detector_snapshot = lambda: _AUTO_VJ_MODULE.AutoVJController._detector_snapshot(stub)
    stub._sequence_director_fields = (
        lambda audio, state: _AUTO_VJ_MODULE.AutoVJController._sequence_director_fields(stub, audio, state)
    )
    return stub


def test_record_sequence_heartbeat_stamps_versions_on_first_row_only() -> None:
    """2026-08-15: detector/director/recommender versions don't change
    mid-session, so only the first captured row needs them -- every row
    would just be redundant bytes at scale. Owner: "add the detector
    version to something in the training logs... doesn't have to be every
    row by any means tho since it won't change during a single session."""
    stub = _make_sequence_heartbeat_stub()
    audio = SimpleNamespace(
        waveform=np.asarray([0.0, 0.5, -0.25, 0.25], dtype=np.float32),
        bass_n=0.2, mid_n=0.4, treble_n=0.6, bpm=125.0,
    )
    state = SimpleNamespace(audio_source='Line In', playlist_mode='auto', effect_name='')
    spotify = {'available': True, 'is_playing': True}

    _AUTO_VJ_MODULE.AutoVJController._record_sequence_heartbeat(stub, state, audio, spotify)
    _AUTO_VJ_MODULE.AutoVJController._record_sequence_heartbeat(stub, state, audio, spotify)

    rows = stub._sequence_corpus_writer.rows
    assert len(rows) == 2
    assert 'detector_version' in rows[0]
    assert rows[0]['director_version'] == _AUTO_VJ_MODULE._DIRECTOR_VERSION
    assert rows[0]['recommender_version'] == _AUTO_VJ_MODULE._RECOMMENDER_VERSION
    assert 'detector_version' not in rows[1]
    assert 'director_version' not in rows[1]
    assert 'recommender_version' not in rows[1]
    assert stub._version_stamped_this_session is True


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


class _FakeLiveCorpusWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, bool]] = []

    def upsert(self, row: dict, *, force_flush: bool = False) -> bool:
        self.calls.append((row, force_flush))
        return True


def _make_record_live_training_row_stub(*, writer=None, bpm: float = 125.0):
    """Minimal AutoVJController-like stub for _record_live_training_row()."""
    return SimpleNamespace(
        _live_corpus_writer=writer if writer is not None else _FakeLiveCorpusWriter(),
        _grid=SimpleNamespace(bpm=bpm, confidence=0.8),
        _audio_manager=None,
        _shadow_grid=None,
        _shadow2_grid=None,
        _live_training_last_change_counter=-1,
        _live_training_last_track_id='',
        _compute_kick_regularity=lambda: 0.5,
        _get_mixer_bpm=lambda: 0.0,
        _get_mixer_track_path=lambda: '',
        _get_section_hint=lambda: None,
    )


def test_record_live_training_row_writes_without_now_playing_availability() -> None:
    """2026-08-15: no longer requires spotify.available/is_playing -- a
    session where the now-playing source never resolves a track identity
    (this bug's real trigger case) must still capture live-corpus rows as
    long as the detector has a real BPM."""
    stub = _make_record_live_training_row_stub()
    audio = SimpleNamespace(
        waveform=np.asarray([0.0, 0.5, -0.25, 0.25], dtype=np.float32),
        bass_n=0.2, mid_n=0.4, treble_n=0.6, bpm=125.0,
    )
    state = SimpleNamespace(audio_source='Line In', playlist_mode='auto')
    spotify = {'available': False, 'is_playing': False}  # no identity ever resolved

    _AUTO_VJ_MODULE.AutoVJController._record_live_training_row(stub, state, audio, spotify)

    assert len(stub._live_corpus_writer.calls) == 1


def test_record_live_training_row_skips_when_no_real_bpm() -> None:
    """The BPM check is the real, source-independent gate now -- still enforced."""
    stub = _make_record_live_training_row_stub(bpm=0.0)
    audio = SimpleNamespace(
        waveform=np.asarray([0.0, 0.5, -0.25, 0.25], dtype=np.float32),
        bass_n=0.2, mid_n=0.4, treble_n=0.6, bpm=0.0,
    )
    state = SimpleNamespace(audio_source='Line In', playlist_mode='auto')

    _AUTO_VJ_MODULE.AutoVJController._record_live_training_row(stub, state, audio, {})

    assert stub._live_corpus_writer.calls == []


def test_record_live_training_row_change_counter_zero_force_flushes() -> None:
    """2026-08-15: `spotify.get('change_counter', -1) or -1` collapsed a
    legitimate change_counter of 0 into -1 (falsy-0 triggers `or`), which
    then failed the `change_counter >= 0` check and could never
    force-flush. change_counter=0, differing from the fresh session's
    initial -1 sentinel, must now be recognized as a real change."""
    stub = _make_record_live_training_row_stub()
    audio = SimpleNamespace(
        waveform=np.asarray([0.0, 0.5, -0.25, 0.25], dtype=np.float32),
        bass_n=0.2, mid_n=0.4, treble_n=0.6, bpm=125.0,
    )
    state = SimpleNamespace(audio_source='Line In', playlist_mode='auto')
    spotify = {'change_counter': 0}

    _AUTO_VJ_MODULE.AutoVJController._record_live_training_row(stub, state, audio, spotify)

    assert len(stub._live_corpus_writer.calls) == 1
    _row, force_flush = stub._live_corpus_writer.calls[0]
    assert force_flush is True
    assert stub._live_training_last_change_counter == 0


def test_record_live_training_row_logs_a_warning_on_capture_failure(caplog: pytest.LogCaptureFixture) -> None:
    """2026-08-15: this exact silent-swallow shape (a real failure invisible
    without DEBUG-level logging) is what made the zero-live-corpus-rows
    session that found this bug so hard to diagnose after the fact."""
    class _RaisingWriter:
        def upsert(self, row: dict, *, force_flush: bool = False) -> bool:
            raise RuntimeError('disk full')

    stub = _make_record_live_training_row_stub(writer=_RaisingWriter())
    audio = SimpleNamespace(
        waveform=np.asarray([0.0, 0.5, -0.25, 0.25], dtype=np.float32),
        bass_n=0.2, mid_n=0.4, treble_n=0.6, bpm=125.0,
    )
    state = SimpleNamespace(audio_source='Line In', playlist_mode='auto')

    with caplog.at_level('WARNING'):
        _AUTO_VJ_MODULE.AutoVJController._record_live_training_row(stub, state, audio, {})

    assert 'disk full' in caplog.text


def test_build_live_training_row_captures_every_audiodata_field_except_fft_waveform() -> None:
    """2026-08-09: bass/mid/treble/bass_n/mid_n/treble_n/beat/bass_flux/
    mid_flux/vocal_hnr/vocal_fmr now reach every corpus row this function
    feeds (live corpus + both sequence corpus paths) -- previously
    bass_flux/mid_flux/vocal_hnr/vocal_fmr weren't captured in any per-frame
    row at all, and the rest only reached the sequence corpus via a
    separate, now-removed duplicate list in _sequence_director_fields().
    Owner: "let's add all to the training logs... that is a gold mine!"
    """
    audio = SimpleNamespace(
        waveform=np.asarray([0.0, 0.5, -0.25, 0.25], dtype=np.float32),
        bass=0.11, mid=0.22, treble=0.33,
        bass_n=0.44, mid_n=0.55, treble_n=0.66,
        beat=1.0,
        bpm=126.0,
        bass_flux=1.23, mid_flux=4.56,
        spectral_flux=7.89,
        vocal_hnr=0.71, vocal_fmr=0.62,
    )
    spotify = {
        'track_id': 'spotify:track:test123', 'title': 'Moonwalk',
        'status': 'playing', 'is_playing': True,
        'duration_s': 180.0, 'position_s': 90.0, 'progress': 0.5,
    }
    state = SimpleNamespace(audio_source='Line In', playlist_mode='auto')
    audio_manager = SimpleNamespace(
        get_profile_key=lambda: 'normie',
        get_profile=lambda: SimpleNamespace(name='Normie'),
        get_profile_bpm_range=lambda: (90, 130),
    )
    grid = SimpleNamespace(bpm=126.0, confidence=0.70)

    row = _build_live_training_row(audio, spotify, state, audio_manager, grid)

    assert row['bass'] == pytest.approx(0.11)
    assert row['mid'] == pytest.approx(0.22)
    assert row['treble'] == pytest.approx(0.33)
    assert row['bass_n'] == pytest.approx(0.44)
    assert row['mid_n'] == pytest.approx(0.55)
    assert row['treble_n'] == pytest.approx(0.66)
    assert row['beat'] == pytest.approx(1.0)
    assert row['bass_flux'] == pytest.approx(1.23)
    assert row['mid_flux'] == pytest.approx(4.56)
    assert row['vocal_hnr'] == pytest.approx(0.71)
    assert row['vocal_fmr'] == pytest.approx(0.62)
    assert 'fft' not in row
    assert 'waveform' not in row
