"""Tests for the accelerated local-track replay core (v3 plan Phase A).

Covers ``drop-ins/training-kit-01/tools/track_replay.py``: the fidelity
streaming loop, metrics (Acc1/Acc2/fold via the agreement-report reuse),
track-store ground truth, the per-cycle log hook, and the decode chain.
Always-on tier — synthetic/committed audio only; real-library coverage
lives in ``test_local_track_replay.py`` behind the ``local_tracks``
marker.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

_TR_PATH = _REPO / 'drop-ins' / 'training-kit-01' / 'tools' / 'track_replay.py'
_SPEC = importlib.util.spec_from_file_location('test_track_replay_module', _TR_PATH)
assert _SPEC is not None and _SPEC.loader is not None
track_replay = importlib.util.module_from_spec(_SPEC)
sys.modules['test_track_replay_module'] = track_replay  # dataclasses need this
_SPEC.loader.exec_module(track_replay)

from unicornviz.audio.analyzer import Analyzer  # noqa: E402
from unicornviz.audio.profiles import get_profile  # noqa: E402

_SEED_WAV = _REPO / 'assets' / 'audio' / 'bpm_eval' / 'seed' / '090bpm_click.wav'


def _fresh_pair(profile_name: str = 'house'):
    profile = get_profile(profile_name)
    analyzer = Analyzer(fft_bands=512, profile=profile)
    tracker = track_replay.load_beat_grid_module().BeatTracker({})
    tracker.set_profile(profile)
    return analyzer, tracker


# ---------------------------------------------------------------------------
# stream_track — the fidelity loop
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _SEED_WAV.exists(), reason='seed corpus not present')
def test_stream_track_locks_committed_click_wav() -> None:
    analyzer, tracker = _fresh_pair()
    result = track_replay.stream_track(_SEED_WAV, analyzer, tracker)
    metrics = track_replay.replay_metrics(result, 90.0)

    assert metrics['locked_ticks'] > 0
    assert metrics['acc2'] is True
    assert metrics['fold'] == '1:1'
    assert abs(metrics['bpm_median'] - 90.0) / 90.0 < 0.04
    # Wall-clock-decoupled: must beat real time by a wide margin.
    assert result.speedup > 5.0


def test_stream_track_tick_cadence_and_counters() -> None:
    # 10 s of silence-ish noise: the loop must still tick at 60 Hz audio
    # time and report the engagement-counter surface.
    rng = np.random.default_rng(42)
    pcm = (rng.standard_normal(10 * track_replay.TARGET_SR) * 0.001).astype(np.float32)
    analyzer, tracker = _fresh_pair()
    result = track_replay.stream_track(pcm, analyzer, tracker)

    assert result.duration_s == pytest.approx(10.0, abs=0.1)
    # ~60 ticks per audio second (first tick at 1/60, last within the file)
    assert len(result.ticks) == pytest.approx(600, abs=5)
    tick_times = [t for t, _, _ in result.ticks]
    assert tick_times == sorted(tick_times)
    for key in ('acf_cycle_count', 'dwell_gated_count',
                'persistence_reset_count', 'phase_error_median'):
        assert key in result.counters


def test_stream_track_max_duration_truncates() -> None:
    pcm = np.zeros(30 * track_replay.TARGET_SR, dtype=np.float32)
    analyzer, tracker = _fresh_pair()
    result = track_replay.stream_track(pcm, analyzer, tracker, max_duration_s=5.0)
    assert result.duration_s <= 5.0 + 0.1


@pytest.mark.skipif(not _SEED_WAV.exists(), reason='seed corpus not present')
def test_cycle_log_hook_emits_rows() -> None:
    analyzer, tracker = _fresh_pair()
    rows: list[dict] = []
    track_replay.stream_track(_SEED_WAV, analyzer, tracker,
                              max_duration_s=15.0, cycle_log=rows.append)

    assert rows, 'expected per-ACF-cycle rows'
    first = rows[0]
    for key in ('t', 'cycle', 'bpm', 'confidence', 'acf_confidence',
                'top_candidates', 'dwell_gated_count',
                'persistence_reset_count', 'candidate_lock_disagreement'):
        assert key in first
    cycles = [r['cycle'] for r in rows]
    assert cycles == sorted(cycles)
    assert cycles[-1] == tracker.acf_cycle_count
    # Cycles run at the ACF interval (~7.5 Hz), well below tick rate.
    assert 15 * 5 < len(rows) < 15 * 12


# ---------------------------------------------------------------------------
# replay_metrics
# ---------------------------------------------------------------------------

def _result_with_bpms(bpms: list[float], dt: float = 1.0) -> object:
    result = track_replay.ReplayResult()
    result.ticks = [(i * dt, b, 0.5 if b > 0 else 0.0)
                    for i, b in enumerate(bpms)]
    result.duration_s = len(bpms) * dt
    result.wall_s = 0.01
    return result


def test_replay_metrics_never_locked() -> None:
    metrics = track_replay.replay_metrics(_result_with_bpms([0.0] * 60), 120.0)
    assert metrics['acc1'] is False
    assert metrics['acc2'] is False
    assert metrics['fold'] == 'no-data'
    assert metrics['time_to_first_lock_s'] == -1.0
    assert metrics['lock_toggles'] == 0


def test_replay_metrics_octave_fold_is_acc2_not_acc1() -> None:
    metrics = track_replay.replay_metrics(
        _result_with_bpms([0.0] * 5 + [180.0] * 55), 90.0)
    assert metrics['acc1'] is False
    assert metrics['acc2'] is True
    assert metrics['fold'] == '2:1'
    assert metrics['time_to_first_lock_s'] == pytest.approx(5.0)


def test_replay_metrics_exact_lock_and_toggles() -> None:
    bpms = [0.0] * 4 + [120.5] * 20 + [0.0] * 3 + [119.8] * 33
    metrics = track_replay.replay_metrics(_result_with_bpms(bpms), 120.0)
    assert metrics['acc1'] is True
    assert metrics['fold'] == '1:1'
    assert metrics['lock_toggles'] == 3  # lock, drop, re-lock
    assert metrics['time_to_truth_s'] == pytest.approx(4.0)
    assert metrics['steady_error_pct'] < 1.0


# ---------------------------------------------------------------------------
# Ground truth — track store
# ---------------------------------------------------------------------------

def test_track_store_truth_exact_and_basename_fallback(tmp_path: Path) -> None:
    store = {
        'tracks': {'abc123': {'bpm': 127.5}},
        'paths': {'/mnt/music/song.mp3': {'hash': 'abc123'}},
    }
    store_path = tmp_path / 'store.json'
    store_path.write_text(json.dumps(store), encoding='utf-8')

    paths_map, tracks_map = track_replay.load_track_store(store_path)
    assert track_replay.truth_bpm_for(
        '/mnt/music/song.mp3', paths_map, tracks_map) == pytest.approx(127.5)
    # Basename fallback — same file seen through a different mount point.
    assert track_replay.truth_bpm_for(
        '/other/mount/song.mp3', paths_map, tracks_map) == pytest.approx(127.5)
    assert track_replay.truth_bpm_for(
        '/nope/unknown.mp3', paths_map, tracks_map) == 0.0


def test_track_store_missing_file_returns_empty_maps(tmp_path: Path) -> None:
    paths_map, tracks_map = track_replay.load_track_store(tmp_path / 'nope.json')
    assert paths_map == {} and tracks_map == {}


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------

def test_decode_mono_wav_resamples_and_downmixes(tmp_path: Path) -> None:
    import scipy.io.wavfile as wavfile

    sr = 44_100
    t = np.arange(sr, dtype=np.float32) / sr
    stereo = np.stack([np.sin(2 * np.pi * 220 * t),
                       np.sin(2 * np.pi * 440 * t)], axis=1).astype(np.float32)
    path = tmp_path / 'tone.wav'
    wavfile.write(str(path), sr, stereo)

    mono = track_replay.decode_mono(path, track_replay.TARGET_SR)
    assert mono.ndim == 1
    assert mono.dtype == np.float32
    assert len(mono) == pytest.approx(track_replay.TARGET_SR, abs=10)


# ---------------------------------------------------------------------------
# bpm_eval CLI (end to end on one committed file)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _SEED_WAV.exists(), reason='seed corpus not present')
def test_bpm_eval_cli_end_to_end(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        'test_track_replay_bpm_eval_cli',
        _REPO / 'drop-ins' / 'training-kit-01' / 'tools' / 'bpm_eval.py')
    assert spec is not None and spec.loader is not None
    bpm_eval = importlib.util.module_from_spec(spec)
    sys.modules['test_track_replay_bpm_eval_cli'] = bpm_eval
    spec.loader.exec_module(bpm_eval)

    corpus = tmp_path / 'corpus'
    corpus.mkdir()
    (corpus / '090bpm_click.wav').write_bytes(_SEED_WAV.read_bytes())
    (corpus / '090bpm_click.bpm.json').write_text('{"bpm": 90.0}',
                                                  encoding='utf-8')
    report = tmp_path / 'report.md'
    results_json = tmp_path / 'results.json'
    cycles = tmp_path / 'cycles.jsonl'

    rc = bpm_eval.main([
        str(corpus), '--report', str(report), '--json', str(results_json),
        '--log-cycles', str(cycles),
    ])
    assert rc == 0

    results = json.loads(results_json.read_text(encoding='utf-8'))
    assert '090bpm_click' in results
    m = results['090bpm_click']
    assert m['bpm_truth'] == 90.0
    assert m['acc2'] is True
    assert m['truth_source'] == 'sidecar'
    assert 'Acc1' in report.read_text(encoding='utf-8')
    rows = [json.loads(line) for line in
            cycles.read_text(encoding='utf-8').splitlines()]
    assert rows and rows[0]['track'] == '090bpm_click'

    # Baseline diff against itself: no per-track changes reported.
    rc = bpm_eval.main([
        str(corpus), '--report', str(report), '--json', str(results_json),
        '--baseline', str(results_json),
    ])
    assert rc == 0
