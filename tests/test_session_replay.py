"""Tests for the full-director session replay driver (v3 plan Phase C.1).

Covers ``drop-ins/training-kit-01/tools/session_replay.py``: a two-track
synthetic session must run the whole AutoVJController at accelerated
audio time, emulate a now-playing source (track changes, track_path hint
bus), and produce corpus files whose rows are stamped with audio time.
Always-on tier — synthetic clicks only, a few seconds of wall clock.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import scipy.io.wavfile as wavfile

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

_TOOLS = _REPO / 'drop-ins' / 'training-kit-01' / 'tools'


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


session_replay = _load('test_session_replay_module', _TOOLS / 'session_replay.py')
_GEN = _load('test_session_replay_gen', _TOOLS / 'gen_bpm_eval_corpus.py')


@pytest.fixture(scope='module')
def two_track_session(tmp_path_factory) -> dict:
    """One shared 2×15 s replay session (module-scoped: it costs seconds)."""
    tmp = tmp_path_factory.mktemp('session_replay')
    files = []
    for bpm, stem in ((124.0, 'clip_a'), (128.0, 'clip_b')):
        pcm, _truth = _GEN.generate_clip(bpm, duration_s=15.0, seed=3)
        path = tmp / f'{stem}.wav'
        wavfile.write(str(path), _GEN.SR, (pcm * 32767).astype(np.int16))
        files.append(path)

    out_dir = tmp / 'out'
    summary = session_replay.run_session(
        files, max_duration_s=15.0, gap_s=1.0, out_dir=out_dir, seed=11,
        # Short grace so this 32 s session can prove the startup guard
        # actually EXPIRES on the audio clock (the 2026-08-18 CRUISE-lock
        # bug left it stamped on the wall clock, never expiring).
        extra_cfg={'startup_grace_s': 5.0})
    return {'summary': summary, 'out_dir': out_dir, 'files': files}


def test_session_summary_shape(two_track_session) -> None:
    summary = two_track_session['summary']
    assert summary['tracks_played'] == ['clip_a.wav', 'clip_b.wav']
    assert summary['audio_s'] == pytest.approx(32.0, abs=0.5)  # 2×15s + 2×1s gap
    assert summary['sequence_corpus_rows'] > 0
    assert summary['live_corpus_rows'] >= 1  # one row per track change
    # Wall-clock-decoupled: even tiny sessions must beat real time.
    assert summary['speedup'] > 2.0
    assert 'AUTO VJ' in summary['final_status']
    # Startup grace (5 s here) must have expired on the AUDIO clock —
    # a WARMUP pill after 32 s of audio means the guard deadline is on
    # the wall-clock timebase again (the CRUISE-lock bug).
    assert 'WARMUP' not in summary['final_status']


def test_sequence_corpus_rows_are_audio_time_stamped(two_track_session) -> None:
    out_dir = two_track_session['out_dir']
    seq_files = sorted(out_dir.glob('sequence-replay-*.jsonl'))
    assert seq_files, 'sequence corpus file missing'
    rows = [json.loads(line) for line in
            seq_files[0].read_text(encoding='utf-8').splitlines()]
    assert rows

    times = [r['capture_time'] for r in rows if 'capture_time' in r]
    assert times, 'rows must carry capture_time'
    assert times == sorted(times)
    # Audio time, not wall time: the whole 32 s session ran in a few
    # seconds of wall clock, so timestamps beyond ~5 s can only be the
    # audio clock (via the Phase B seam).
    assert times[-1] > 20.0
    assert times[-1] < 40.0


def test_track_path_hint_bus_reaches_the_corpus(two_track_session) -> None:
    out_dir = two_track_session['out_dir']
    seq_files = sorted(out_dir.glob('sequence-replay-*.jsonl'))
    rows = [json.loads(line) for line in
            seq_files[0].read_text(encoding='utf-8').splitlines()]
    seen = {Path(r['track_path']).name for r in rows if r.get('track_path')}
    assert seen == {'clip_a.wav', 'clip_b.wav'}


def test_resolve_media_playlist(tmp_path: Path) -> None:
    real = tmp_path / 'song.wav'
    real.write_bytes(b'')
    store = {
        'playlists': {
            'Training - House 01': [
                str(real),
                str(tmp_path / 'gone.mp3'),          # missing → skipped
                {'path': str(real)},                 # dict entry tolerated
            ],
        },
    }
    store_path = tmp_path / 'media_playlists.json'
    store_path.write_text(json.dumps(store), encoding='utf-8')

    files = session_replay.resolve_media_playlist(
        'training - house 01', store_path)  # case-insensitive
    assert files == [real, real]

    with pytest.raises(SystemExit):
        session_replay.resolve_media_playlist('no such list', store_path)
    with pytest.raises(SystemExit):
        session_replay.resolve_media_playlist(
            'training - house 01', tmp_path / 'missing.json')


# ---- auto-packaging (2026-08-18) --------------------------------------


def test_replay_set_label_with_playlist() -> None:
    assert session_replay._replay_set_label('training - house 01') == 'training - house 01 replay'


def test_replay_set_label_without_playlist() -> None:
    assert session_replay._replay_set_label(None) == 'adhoc replay'


def test_run_packager_invokes_packager_with_isolated_dirs(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    class _FakeCompleted:
        returncode = 0

    def _fake_run(cmd, cwd=None):
        captured['cmd'] = cmd
        captured['cwd'] = cwd
        return _FakeCompleted()

    monkeypatch.setattr(session_replay.subprocess, 'run', _fake_run)
    out_dir = tmp_path / 'replay-out'
    out_dir.mkdir()
    summary = {'speedup': 12.3, 'tracks_played': ['a.mp3', 'b.mp3'], 'sequence_corpus_rows': 500}

    rc = session_replay._run_packager(out_dir, 'my set replay', summary)
    assert rc == 0
    cmd = captured['cmd']
    assert str(out_dir) in cmd
    assert cmd.count(str(out_dir)) == 2  # --corpus-dir AND --logs-dir both point at it
    assert '--playlist-name' in cmd
    assert 'my set replay' in cmd
    assert '--no-prompt' in cmd
    notes = cmd[cmd.index('--session-notes') + 1]
    assert '12.3x' in notes
    assert 'ideas to pursue' in notes


def test_main_skips_packaging_with_no_package_flag(tmp_path: Path, monkeypatch) -> None:
    audio = tmp_path / 'clip.wav'
    pcm, _ = _GEN.generate_clip(124.0, duration_s=2.0, seed=1)
    wavfile.write(str(audio), _GEN.SR, (pcm * 32767).astype(np.int16))

    called = {'n': 0}
    monkeypatch.setattr(session_replay, '_run_packager', lambda *a, **k: called.__setitem__('n', called['n'] + 1))

    rc = session_replay.main([
        '--tracks', str(audio), '--out-dir', str(tmp_path / 'out'),
        '--max-duration', '2', '--no-package',
    ])
    assert rc == 0
    assert called['n'] == 0


def test_main_packages_by_default(tmp_path: Path, monkeypatch) -> None:
    audio = tmp_path / 'clip.wav'
    pcm, _ = _GEN.generate_clip(124.0, duration_s=2.0, seed=1)
    wavfile.write(str(audio), _GEN.SR, (pcm * 32767).astype(np.int16))

    called = {}

    def _fake_packager(out_dir, set_label, summary):
        called['out_dir'] = out_dir
        called['set_label'] = set_label
        return 0

    monkeypatch.setattr(session_replay, '_run_packager', _fake_packager)

    rc = session_replay.main([
        '--tracks', str(audio), '--out-dir', str(tmp_path / 'out'),
        '--max-duration', '2',
    ])
    assert rc == 0
    assert called['set_label'] == 'adhoc replay'
    assert called['out_dir'] == tmp_path / 'out'


def test_director_activity_summarized(two_track_session) -> None:
    # log_decisions is deliberately OFF in replay (its JSONL would land
    # in logs/, which package_training_set.py sweeps into buckets); the
    # summary's director_calls counter is the observable activity here.
    summary = two_track_session['summary']
    assert isinstance(summary['director_calls'], dict)
