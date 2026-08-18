"""Regression tests for the corpus-writer extraction (training-kit-01).

Covers:
- SequenceCorpusWriter and LiveCorpusWriter load correctly from
  drop-ins/training-kit-01/corpus_writers.py
- auto_vj.py resolves the same real classes (not the no-op stubs) when
  training-kit-01 is present
- No-op stub classes are safe to call without any corpus path configured
- bpm_eval.py _BEAT_GRID_PATH resolves to auto-vj-01/beat_grid.py after the
  move to training-kit-01/tools/
"""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Shared fixtures: load modules from drop-in paths
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parents[1]
_CW_PATH = _REPO / 'drop-ins' / 'training-kit-01' / 'corpus_writers.py'
_AUTO_VJ_PATH = _REPO / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_BPM_EVAL_PATH = _REPO / 'drop-ins' / 'training-kit-01' / 'tools' / 'bpm_eval.py'


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope='module')
def cw_mod():
    """Load corpus_writers.py from training-kit-01."""
    return _load_module(_CW_PATH, 'test_corpus_writers_mod')


@pytest.fixture(scope='module')
def auto_vj_mod():
    """Load auto_vj.py from auto-vj-01."""
    return _load_module(_AUTO_VJ_PATH, 'test_auto_vj_cw_mod')


# ---------------------------------------------------------------------------
# 1. Drop-in module loads and exports both classes
# ---------------------------------------------------------------------------

def test_corpus_writers_module_exports_sequence_writer(cw_mod) -> None:
    assert hasattr(cw_mod, 'SequenceCorpusWriter')
    assert callable(cw_mod.SequenceCorpusWriter)


def test_corpus_writers_module_exports_live_writer(cw_mod) -> None:
    assert hasattr(cw_mod, 'LiveCorpusWriter')
    assert callable(cw_mod.LiveCorpusWriter)


# ---------------------------------------------------------------------------
# 2. auto_vj.py resolves the real classes from training-kit-01
# ---------------------------------------------------------------------------

def test_auto_vj_live_corpus_writer_is_real_class(auto_vj_mod) -> None:
    """auto_vj.LiveCorpusWriter must be the real implementation, not the no-op stub.

    auto_vj.py loads corpus_writers.py via importlib into its own private
    module namespace (_corpus_writers), so we cannot use `is` identity across
    two separate loads.  Instead we verify that the resolved class has the
    internal file-management state (_rows, _dirty) that the stub never has.
    """
    avj_cls = auto_vj_mod.LiveCorpusWriter
    instance = avj_cls(None, False, 1.0)
    assert hasattr(instance, '_rows'), (
        'auto_vj.py loaded the no-op LiveCorpusWriter stub instead of the real '
        'implementation from training-kit-01; check the importlib path in auto_vj.py'
    )


def test_auto_vj_sequence_corpus_writer_is_real_class(auto_vj_mod) -> None:
    """auto_vj.SequenceCorpusWriter must be the real implementation, not the stub."""
    avj_cls = auto_vj_mod.SequenceCorpusWriter
    instance = avj_cls(None, False, 1.0)
    assert hasattr(instance, '_file'), (
        'auto_vj.py loaded the no-op SequenceCorpusWriter stub instead of the real '
        'implementation from training-kit-01'
    )


# ---------------------------------------------------------------------------
# 3. SequenceCorpusWriter behaviour
# ---------------------------------------------------------------------------

class TestSequenceCorpusWriter:
    def test_disabled_writer_writes_nothing(self, cw_mod, tmp_path: Path) -> None:
        path = tmp_path / 'seq.jsonl'
        w = cw_mod.SequenceCorpusWriter(path, enabled=False, window_s=2.0)
        assert w.enabled is False
        w.append({'x': 1}, is_keyframe=False)
        assert not path.exists()

    def test_enabled_writer_appends_row(self, cw_mod, tmp_path: Path) -> None:
        path = tmp_path / 'seq.jsonl'
        w = cw_mod.SequenceCorpusWriter(path, enabled=True, window_s=2.0)
        assert w.enabled is True
        ok = w.append({'beat': 1}, is_keyframe=False)
        assert ok is True
        lines = [ln for ln in path.read_text(encoding='utf-8').splitlines() if ln.strip()]
        assert len(lines) == 1
        assert json.loads(lines[0])['beat'] == 1

    def test_keyframe_injects_event_id(self, cw_mod, tmp_path: Path) -> None:
        path = tmp_path / 'seq.jsonl'
        w = cw_mod.SequenceCorpusWriter(path, enabled=True, window_s=2.0)
        w.append({'mode': 'DROP'}, is_keyframe=True, event_id='drop_onset')
        row = json.loads(path.read_text(encoding='utf-8').strip())
        assert row['event_id'] == 'drop_onset'
        assert row['mode'] == 'DROP'

    def test_heartbeat_without_event_id_excluded(self, cw_mod, tmp_path: Path) -> None:
        path = tmp_path / 'seq.jsonl'
        w = cw_mod.SequenceCorpusWriter(path, enabled=True, window_s=2.0)
        w.append({'mode': 'CRUISE'}, is_keyframe=False)
        row = json.loads(path.read_text(encoding='utf-8').strip())
        assert 'event_id' not in row

    def test_should_capture_heartbeat_respects_interval(self, cw_mod, tmp_path: Path) -> None:
        path = tmp_path / 'seq.jsonl'
        w = cw_mod.SequenceCorpusWriter(path, enabled=True, window_s=2.0)
        now = time.monotonic()
        # First call should always return True (last_t initialised to -1e9)
        assert w.should_capture_heartbeat(now, beat_index=0, interval_s=1.0) is True
        # Immediate second call: beat index unchanged, interval not elapsed
        assert w.should_capture_heartbeat(now, beat_index=0, interval_s=1.0) is False
        # New beat index → capture regardless of time
        assert w.should_capture_heartbeat(now, beat_index=1, interval_s=1.0) is True

    def test_set_enabled_toggles_capture(self, cw_mod, tmp_path: Path) -> None:
        path = tmp_path / 'seq.jsonl'
        w = cw_mod.SequenceCorpusWriter(path, enabled=False, window_s=2.0)
        assert w.enabled is False
        w.set_enabled(True)
        assert w.enabled is True
        w.append({'x': 99}, is_keyframe=False)
        assert path.exists()

    def test_shutdown_closes_file_gracefully(self, cw_mod, tmp_path: Path) -> None:
        path = tmp_path / 'seq.jsonl'
        w = cw_mod.SequenceCorpusWriter(path, enabled=True, window_s=2.0)
        w.append({'x': 1}, is_keyframe=False)
        w.shutdown()
        assert w._file is None
        # Second shutdown must not raise
        w.shutdown()


# ---------------------------------------------------------------------------
# 4. LiveCorpusWriter behaviour
# ---------------------------------------------------------------------------

class TestLiveCorpusWriter:
    def _row(self, track_id: str = 'spotify:track:abc123', title: str = 'Test') -> dict:
        return {'spotify_track_id': track_id, 'spotify_title': title}

    def test_enabled_writer_persists_row(self, cw_mod, tmp_path: Path) -> None:
        path = tmp_path / 'live.jsonl'
        w = cw_mod.LiveCorpusWriter(path, enabled=True, min_interval_s=0.0)
        assert w.upsert(self._row(), force_flush=True) is True
        rows = [json.loads(ln) for ln in path.read_text(encoding='utf-8').splitlines() if ln.strip()]
        assert len(rows) == 1
        assert rows[0]['spotify_track_id'] == 'spotify:track:abc123'

    def test_upsert_updates_existing_row(self, cw_mod, tmp_path: Path) -> None:
        path = tmp_path / 'live.jsonl'
        w = cw_mod.LiveCorpusWriter(path, enabled=True, min_interval_s=0.0)
        w.upsert(self._row(title='First'), force_flush=True)
        w.upsert(self._row(title='Updated'), force_flush=True)
        rows = [json.loads(ln) for ln in path.read_text(encoding='utf-8').splitlines() if ln.strip()]
        assert len(rows) == 1
        assert rows[0]['spotify_title'] == 'Updated'

    def test_multiple_tracks_keyed_separately(self, cw_mod, tmp_path: Path) -> None:
        path = tmp_path / 'live.jsonl'
        w = cw_mod.LiveCorpusWriter(path, enabled=True, min_interval_s=0.0)
        w.upsert(self._row('spotify:track:aaa', 'Track A'), force_flush=True)
        w.upsert(self._row('spotify:track:bbb', 'Track B'), force_flush=True)
        rows = [json.loads(ln) for ln in path.read_text(encoding='utf-8').splitlines() if ln.strip()]
        assert len(rows) == 2
        titles = {r['spotify_title'] for r in rows}
        assert titles == {'Track A', 'Track B'}

    def test_preloads_existing_corpus_on_init(self, cw_mod, tmp_path: Path) -> None:
        path = tmp_path / 'live.jsonl'
        seed = {'spotify_track_id': 'spotify:track:seed', 'spotify_title': 'Seed'}
        path.write_text(json.dumps(seed) + '\n', encoding='utf-8')
        w = cw_mod.LiveCorpusWriter(path, enabled=True, min_interval_s=0.0)
        assert 'spotify:track:seed' in w._rows

    def test_disabled_writer_ignores_upsert(self, cw_mod, tmp_path: Path) -> None:
        path = tmp_path / 'live.jsonl'
        w = cw_mod.LiveCorpusWriter(path, enabled=False, min_interval_s=0.0)
        assert w.upsert(self._row(), force_flush=True) is False
        assert not path.exists()

    def test_row_key_falls_back_to_title_artist(self, cw_mod) -> None:
        row = {'spotify_title': 'Moon', 'spotify_artist': 'Sun', 'spotify_album': 'Sky'}
        key = cw_mod.LiveCorpusWriter._row_key(row)
        assert key == 'moon | sun | sky'

    def test_row_key_falls_back_to_audio_source_when_metadata_empty(self, cw_mod) -> None:
        """Livestream/interactive-DJ sessions carry no track_id/title/artist/album
        at all; the key must still be non-empty so upsert() doesn't silently drop
        every row (this previously produced zero output for a whole session)."""
        row = {'audio_source': 'Loopback'}
        key = cw_mod.LiveCorpusWriter._row_key(row)
        assert key == '__live__:loopback'

    def test_row_key_never_empty_with_completely_blank_row(self, cw_mod) -> None:
        key = cw_mod.LiveCorpusWriter._row_key({})
        assert key == '__live__:unknown'

    def test_upsert_persists_row_with_no_track_metadata(self, cw_mod, tmp_path: Path) -> None:
        path = tmp_path / 'live.jsonl'
        w = cw_mod.LiveCorpusWriter(path, enabled=True, min_interval_s=0.0)
        row = {'audio_source': 'Mic', 'bpm': 128.0}
        assert w.upsert(row, force_flush=True) is True
        rows = [json.loads(ln) for ln in path.read_text(encoding='utf-8').splitlines() if ln.strip()]
        assert len(rows) == 1
        assert rows[0]['bpm'] == 128.0

    def test_shutdown_flushes_pending_rows(self, cw_mod, tmp_path: Path) -> None:
        path = tmp_path / 'live.jsonl'
        w = cw_mod.LiveCorpusWriter(path, enabled=True, min_interval_s=9999.0)
        # First upsert: key changes from '' → track_id, so should_flush=True → writes file.
        w.upsert(self._row(title='First'), force_flush=False)
        assert path.exists()
        # Second upsert: same key, interval not elapsed → dirty but not flushed.
        w.upsert(self._row(title='Updated'), force_flush=False)
        # Confirm Updated not on disk yet (interval guard applies).
        rows_before = [json.loads(ln) for ln in path.read_text(encoding='utf-8').splitlines() if ln.strip()]
        assert rows_before[0]['spotify_title'] == 'First'
        # shutdown must flush the pending update.
        w.shutdown()
        rows_after = [json.loads(ln) for ln in path.read_text(encoding='utf-8').splitlines() if ln.strip()]
        assert rows_after[0]['spotify_title'] == 'Updated'


# ---------------------------------------------------------------------------
# 5. No-op stub safety (training-kit-01 absent scenario)
# ---------------------------------------------------------------------------

class _StubSequenceCorpusWriter:
    """Inline copy of the no-op stub from auto_vj.py to test independently."""
    def __init__(self, *a, **kw) -> None:
        self._enabled = False
    @property
    def enabled(self) -> bool: return False
    def set_enabled(self, e: bool) -> bool: return False
    def should_capture_heartbeat(self, *a, **kw) -> bool: return False
    def append(self, *a, **kw) -> bool: return False
    def shutdown(self) -> None: pass


class _StubLiveCorpusWriter:
    """Inline copy of the no-op stub from auto_vj.py to test independently."""
    def __init__(self, *a, **kw) -> None:
        self._enabled = False
    @property
    def enabled(self) -> bool: return False
    def set_enabled(self, e: bool) -> bool: return False
    def upsert(self, *a, **kw) -> bool: return False
    def flush(self, **kw) -> bool: return False
    def shutdown(self) -> None: pass


class TestNoOpStubs:
    def test_stub_sequence_writer_does_not_raise(self) -> None:
        w = _StubSequenceCorpusWriter(None, False, 1.0)
        assert w.enabled is False
        assert w.set_enabled(True) is False
        assert w.should_capture_heartbeat(0.0, 0, 1.0) is False
        assert w.append({'x': 1}, is_keyframe=True, event_id='e') is False
        w.shutdown()

    def test_stub_live_writer_does_not_raise(self) -> None:
        w = _StubLiveCorpusWriter(None, False, 1.0)
        assert w.enabled is False
        assert w.set_enabled(True) is False
        assert w.upsert({'spotify_track_id': 'x'}) is False
        assert w.flush(force=True) is False
        w.shutdown()

    def test_stub_matches_real_sequence_writer_interface(self, cw_mod) -> None:
        """Stub must expose the same public interface as the real class."""
        real = cw_mod.SequenceCorpusWriter(None, False, 1.0)
        stub = _StubSequenceCorpusWriter()
        for method in ('enabled', 'set_enabled', 'should_capture_heartbeat', 'append', 'shutdown'):
            assert hasattr(stub, method), f'stub missing {method}'
            assert hasattr(real, method), f'real missing {method}'

    def test_stub_matches_real_live_writer_interface(self, cw_mod) -> None:
        real = cw_mod.LiveCorpusWriter(None, False, 1.0)
        stub = _StubLiveCorpusWriter()
        for method in ('enabled', 'set_enabled', 'upsert', 'flush', 'shutdown'):
            assert hasattr(stub, method), f'stub missing {method}'
            assert hasattr(real, method), f'real missing {method}'


# ---------------------------------------------------------------------------
# 6. bpm_eval.py _BEAT_GRID_PATH resolves correctly after move
# ---------------------------------------------------------------------------

def test_bpm_eval_beat_grid_path_points_to_auto_vj_01() -> None:
    """bpm_eval.py must load the detector from auto-vj-01/beat_grid.py (not a
    training-kit-01 copy). 2026-08-18: the load moved into
    track_replay.load_beat_grid_module() when bpm_eval.py was rebuilt on the
    replay core, so the guarded path expression lives there now."""
    track_replay_path = _BPM_EVAL_PATH.parent / 'track_replay.py'
    src = track_replay_path.read_text(encoding='utf-8')
    for i, line in enumerate(src.splitlines()):
        if 'def load_beat_grid_module' in line:
            body = '\n'.join(src.splitlines()[i:i + 6])
            assert "'auto-vj-01'" in body and "'beat_grid.py'" in body, (
                f'load_beat_grid_module() does not reference '
                f'auto-vj-01/beat_grid.py:\n{body}'
            )
            return
    pytest.fail('load_beat_grid_module() not found in track_replay.py')


def test_bpm_eval_beat_grid_file_exists() -> None:
    """The resolved beat_grid.py path must actually exist on disk."""
    expected = _REPO / 'drop-ins' / 'auto-vj-01' / 'beat_grid.py'
    assert expected.exists(), f'beat_grid.py not found at expected path: {expected}'
