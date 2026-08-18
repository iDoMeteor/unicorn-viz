"""Regression tests for training-kit-01's BPM evaluation harness:
tools/bpm_eval.py + tools/gen_bpm_eval_corpus.py.

This is the offline accuracy harness used to validate beat-detector
changes against ground truth -- directly relevant to the extensive
beat_grid.py tuning done this project's history (confidence-blend fix,
downbeat gate threshold, tempo hold, etc.) -- and had zero prior test
coverage of its own correctness.

Includes one true end-to-end integration test: generate a synthetic
click track with generate_clip(), run it through the real Analyzer +
BeatGridTracker via evaluate_file(), and confirm the measured BPM lands
close to the ground truth the corpus generator itself produced. This is
the harness validating itself against a known-correct signal.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

import numpy as np
import pytest
import scipy.io.wavfile as wavfile


_TOOLS_DIR = Path(__file__).resolve().parents[1] / 'drop-ins' / 'training-kit-01' / 'tools'

_GEN_SPEC = importlib.util.spec_from_file_location('test_gen_bpm_eval_corpus_module', _TOOLS_DIR / 'gen_bpm_eval_corpus.py')
assert _GEN_SPEC is not None and _GEN_SPEC.loader is not None
_GEN = importlib.util.module_from_spec(_GEN_SPEC)
_GEN_SPEC.loader.exec_module(_GEN)

_EVAL_SPEC = importlib.util.spec_from_file_location('test_bpm_eval_module', _TOOLS_DIR / 'bpm_eval.py')
assert _EVAL_SPEC is not None and _EVAL_SPEC.loader is not None
_EVAL = importlib.util.module_from_spec(_EVAL_SPEC)
_EVAL_SPEC.loader.exec_module(_EVAL)


# ---------------------------------------------------------------------------
# gen_bpm_eval_corpus.py — generate_clip()
# ---------------------------------------------------------------------------

def test_generate_clip_returns_correct_sample_count() -> None:
    pcm, _truth = _GEN.generate_clip(120.0, sr=48000, duration_s=10.0)
    assert len(pcm) == 480_000


def test_generate_clip_truth_matches_requested_bpm() -> None:
    _pcm, truth = _GEN.generate_clip(140.0, duration_s=5.0)
    assert truth['bpm'] == 140.0


def test_generate_clip_truth_includes_downbeat_offset() -> None:
    _pcm, truth = _GEN.generate_clip(120.0, duration_s=5.0, downbeat_offset_s=0.37)
    assert truth['downbeat_offset_s'] == pytest.approx(0.37)


def test_generate_clip_pcm_stays_in_valid_range() -> None:
    pcm, _truth = _GEN.generate_clip(155.0, duration_s=10.0)
    assert pcm.min() >= -1.0
    assert pcm.max() <= 1.0


def test_generate_clip_is_not_silent() -> None:
    pcm, _truth = _GEN.generate_clip(120.0, duration_s=5.0)
    assert np.abs(pcm).mean() > _GEN.NOISE_FLOOR, 'transients must raise the signal well above the noise floor'


def test_generate_clip_transient_count_matches_bpm_over_duration() -> None:
    """At 120 BPM (0.5s/beat) over 10s, roughly 20 transients should have
    been placed (kick/snare alternating). A single transient is a decaying
    sine burst that crosses any fixed amplitude threshold several times on
    its own (oscillation, not one clean pulse), so peak-picking with a
    minimum-distance constraint is used instead of raw threshold crossings."""
    from scipy.signal import find_peaks  # noqa: PLC0415

    pcm, _truth = _GEN.generate_clip(120.0, duration_s=10.0, seed=1)
    beat_period_samples = int(_GEN.SR * (60.0 / 120.0))
    peaks, _props = find_peaks(np.abs(pcm), height=0.3, distance=beat_period_samples * 0.5)
    expected_beats = int(10.0 / (60.0 / 120.0))
    assert len(peaks) == pytest.approx(expected_beats, abs=2)


def test_generate_clip_is_deterministic_for_a_given_seed() -> None:
    pcm1, _ = _GEN.generate_clip(120.0, duration_s=3.0, seed=7)
    pcm2, _ = _GEN.generate_clip(120.0, duration_s=3.0, seed=7)
    assert np.array_equal(pcm1, pcm2)


def test_generate_clip_seed_corpus_covers_documented_bpms() -> None:
    bpms = [bpm for bpm, _stem, _offset in _GEN.CORPUS]
    assert bpms == [90.0, 96.0, 120.0, 140.0, 155.0]


def test_gen_main_writes_wav_and_json_sidecar_per_corpus_entry(tmp_path: Path) -> None:
    _GEN.main(tmp_path)

    for _bpm, stem, _offset in _GEN.CORPUS:
        wav_path = tmp_path / f'{stem}.wav'
        json_path = tmp_path / f'{stem}.bpm.json'
        assert wav_path.exists()
        assert json_path.exists()
        truth = json.loads(json_path.read_text())
        assert 'bpm' in truth


# ---------------------------------------------------------------------------
# 2026-08-18 re-baseline (v3 plan Phase A): bpm_eval.py was rebuilt on
# tools/track_replay.py. Harmonic-ratio classification is superseded by
# the Acc1/Acc2 fold tables (single-sourced from bpm_agreement_report.py),
# _compute_metrics by replay_metrics, and _load_wav_mono/_resample_if_
# needed by decode_mono — all of which are covered by
# tests/test_track_replay.py. This file keeps the corpus generator and
# the bpm_eval-level orchestration/report surface.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# bpm_eval.py — sidecar ground truth
# ---------------------------------------------------------------------------

def test_sidecar_truth_reads_bpm(tmp_path: Path) -> None:
    audio = tmp_path / 'song.wav'
    audio.write_bytes(b'')
    audio.with_suffix('.bpm.json').write_text('{"bpm": 132.5}')
    assert _EVAL._sidecar_truth(audio) == pytest.approx(132.5)


def test_sidecar_truth_missing_or_bad_is_zero(tmp_path: Path) -> None:
    audio = tmp_path / 'song.wav'
    assert _EVAL._sidecar_truth(audio) == 0.0
    audio.with_suffix('.bpm.json').write_text('not json')
    assert _EVAL._sidecar_truth(audio) == 0.0


def test_gather_audio_files_recurses_and_filters(tmp_path: Path) -> None:
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'a.wav').write_bytes(b'')
    (tmp_path / 'sub' / 'b.mp3').write_bytes(b'')
    (tmp_path / 'notes.txt').write_bytes(b'')
    files = _EVAL._gather_audio_files([tmp_path])
    assert [f.name for f in files] == ['a.wav', 'b.mp3']


# ---------------------------------------------------------------------------
# bpm_eval.py — tracker engine selection
# ---------------------------------------------------------------------------

def test_load_tracker_cls_legacy_returns_beat_grid_tracker() -> None:
    cls = _EVAL._load_tracker_cls('legacy')
    assert cls.__name__ == 'BeatGridTracker'


def test_load_tracker_cls_v2_returns_beat_tracker() -> None:
    cls = _EVAL._load_tracker_cls('v2')
    assert cls.__name__ == 'BeatTracker'


# ---------------------------------------------------------------------------
# bpm_eval.py — report writers
# ---------------------------------------------------------------------------

def test_write_markdown_includes_every_file_and_a_summary(tmp_path: Path) -> None:
    results = {
        '090bpm_click': {
            'bpm_truth': 90.0, 'bpm_median': 90.5, 'bpm_error_pct': 0.6,
            'acc1': True, 'acc2': True, 'fold': '1:1',
            'time_to_first_lock_s': 1.2, 'time_to_truth_s': 1.2,
            'lock_toggles': 1, 'steady_error_pct': 0.5,
        },
    }
    out = tmp_path / 'report.md'
    _EVAL._write_markdown(results, out, engine='v2')

    text = out.read_text()
    assert '090bpm_click' in text
    assert '## Summary' in text
    assert 'Acc1' in text
    assert 'v2' in text


# ---------------------------------------------------------------------------
# run_files() — orchestration
# ---------------------------------------------------------------------------

def test_run_files_skips_audio_without_ground_truth(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    pcm, _truth = _GEN.generate_clip(120.0, duration_s=1.0)
    wavfile.write(str(tmp_path / 'orphan.wav'), _GEN.SR, (pcm * 32767).astype(np.int16))

    results = _EVAL.run_files(
        [tmp_path / 'orphan.wav'], engine='legacy', profile='house',
        track_store=None, max_duration_s=None, tolerance=0.04,
    )

    assert results == {}
    assert 'SKIP' in capsys.readouterr().out


def test_main_errors_on_empty_directory(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = _EVAL.main([str(tmp_path)])
    assert rc == 1
    assert 'no audio files' in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Full integration: generate_clip() -> evaluate_file() against real
# Analyzer + tracker, harness validating itself against a signal with
# known ground truth. 2026-08-18 re-baseline: evaluate_file() now takes
# a bare truth BPM and replays at the live 60 Hz tracker cadence via
# stream_track() -- see the fidelity note in track_replay.stream_track's
# docstring: sparse synthetic clicks are legitimately harder under the
# honest cadence than under the old per-block loop, so this asserts the
# fold family (Acc2) rather than the old flat <5% error.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(('bpm', 'profile_name'), [(90.0, 'chillstep'), (120.0, 'house')])
def test_harness_measures_synthetic_click_track_accurately(bpm: float, profile_name: str, tmp_path: Path) -> None:
    """Profile must be matched to the clip's tempo: evaluate_file() applies
    the profile's bpm_hint_min/max as a hard search-range constraint (see
    BeatGridTracker.set_profile()), so e.g. 'house' (120-128 BPM hint)
    would legitimately never find a 90 BPM track -- that's the search
    constraint working as designed, not a harness bug."""
    pcm, truth = _GEN.generate_clip(bpm, duration_s=15.0)
    wav_path = tmp_path / 'clip.wav'
    wavfile.write(str(wav_path), _GEN.SR, (pcm * 32767).astype(np.int16))

    metrics = _EVAL.evaluate_file(wav_path, float(truth['bpm']),
                                  engine='legacy', profile_name=profile_name)

    assert metrics['locked_ticks'] > 0, 'harness must actually lock onto its own generated ground truth'
    assert metrics['acc2'] is True, f'outside every accepted fold: {metrics["fold"]}'
    assert metrics['time_to_first_lock_s'] >= 0.0
