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
# bpm_eval.py — harmonic-error classification
# ---------------------------------------------------------------------------

def test_nearest_harmonic_ratio_identifies_exact_double_time() -> None:
    assert _EVAL._nearest_harmonic_ratio(240.0, 120.0) == pytest.approx(2.0)


def test_nearest_harmonic_ratio_identifies_exact_half_time() -> None:
    assert _EVAL._nearest_harmonic_ratio(60.0, 120.0) == pytest.approx(0.5)


def test_nearest_harmonic_ratio_identifies_correct_lock() -> None:
    assert _EVAL._nearest_harmonic_ratio(120.0, 120.0) == pytest.approx(1.0)


def test_is_harmonic_error_true_for_double_time() -> None:
    assert _EVAL._is_harmonic_error(240.0, 120.0) is True


def test_is_harmonic_error_false_for_correct_lock() -> None:
    assert _EVAL._is_harmonic_error(120.0, 120.0) is False


def test_is_harmonic_error_false_for_a_small_correct_deviation() -> None:
    """A prediction close to truth (not close to any OTHER harmonic ratio)
    must not be flagged, even though it's not bit-exact."""
    assert _EVAL._is_harmonic_error(121.5, 120.0) is False


def test_is_harmonic_error_false_for_a_random_unrelated_bpm() -> None:
    """A prediction that isn't close to truth NOR to a harmonic multiple of
    it must not be misclassified as a harmonic error -- it's just wrong."""
    assert _EVAL._is_harmonic_error(97.3, 120.0) is False


# ---------------------------------------------------------------------------
# bpm_eval.py — _compute_metrics()
# ---------------------------------------------------------------------------

def test_compute_metrics_missing_ground_truth() -> None:
    result = _EVAL._compute_metrics([], {})
    assert 'error' in result


def test_compute_metrics_never_locked() -> None:
    track = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    result = _EVAL._compute_metrics(track, {'bpm': 120.0})

    assert result['locked_ticks'] == 0
    assert result['time_to_lock_s'] == -1.0
    assert result['bpm_error_pct'] == 100.0


def test_compute_metrics_perfect_lock() -> None:
    track = [(t, 120.0, 1.0) for t in np.arange(0.0, 5.0, 0.1)]
    result = _EVAL._compute_metrics(track, {'bpm': 120.0})

    assert result['bpm_median'] == 120.0
    assert result['bpm_error_abs'] == 0.0
    assert result['bpm_error_pct'] == 0.0
    assert result['harmonic_error_rate'] == 0.0
    assert result['time_to_lock_s'] == 0.0
    assert result['confidence_at_lock'] == 1.0


def test_compute_metrics_time_to_lock_is_the_first_tick_within_tolerance() -> None:
    track = [
        (0.0, 0.0, 0.0),
        (1.0, 80.0, 0.3),     # unlocked / wrong lane
        (2.0, 119.9, 0.9),    # within 2% of 120 -- this is the lock point
        (3.0, 120.0, 1.0),
    ]
    result = _EVAL._compute_metrics(track, {'bpm': 120.0})
    assert result['time_to_lock_s'] == 2.0
    assert result['confidence_at_lock'] == 0.9


def test_compute_metrics_flags_harmonic_error_rate() -> None:
    """Half the locked ticks at true double-time (240 for a 120 truth)."""
    track = (
        [(t, 120.0, 1.0) for t in np.arange(0.0, 2.5, 0.1)]
        + [(t, 240.0, 1.0) for t in np.arange(2.5, 5.0, 0.1)]
    )
    result = _EVAL._compute_metrics(track, {'bpm': 120.0})
    assert result['harmonic_error_rate'] == pytest.approx(0.5, abs=0.05)


def test_compute_metrics_lane_fast_pct() -> None:
    track = [(t, 150.0, 1.0) for t in np.arange(0.0, 5.0, 1.0)]
    result = _EVAL._compute_metrics(track, {'bpm': 150.0})
    assert result['lane_fast_pct'] == 100.0


# ---------------------------------------------------------------------------
# bpm_eval.py — WAV loading / resampling
# ---------------------------------------------------------------------------

def test_load_wav_mono_round_trips_int16(tmp_path: Path) -> None:
    pcm, _truth = _GEN.generate_clip(120.0, duration_s=1.0)
    path = tmp_path / 'test.wav'
    wavfile.write(str(path), _GEN.SR, (pcm * 32767).astype(np.int16))

    loaded, sr = _EVAL._load_wav_mono(path)
    assert sr == _GEN.SR
    assert loaded.dtype == np.float32
    # int16 round-trip loses precision but should stay very close.
    assert np.abs(loaded - pcm).max() < 0.001


def test_load_wav_mono_downmixes_stereo(tmp_path: Path) -> None:
    stereo = np.zeros((1000, 2), dtype=np.int16)
    stereo[:, 0] = 1000
    stereo[:, 1] = -1000  # mean should be ~0
    path = tmp_path / 'stereo.wav'
    wavfile.write(str(path), 48000, stereo)

    loaded, _sr = _EVAL._load_wav_mono(path)
    assert loaded.ndim == 1
    assert np.abs(loaded).max() < 0.01  # (1000 + -1000) / 2 / 32768 ≈ 0


def test_resample_if_needed_returns_input_unchanged_when_rate_matches() -> None:
    pcm = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    result = _EVAL._resample_if_needed(pcm, 48000, 48000)
    assert result is pcm


def test_resample_if_needed_changes_length_proportionally() -> None:
    pcm = np.zeros(48000, dtype=np.float32)
    result = _EVAL._resample_if_needed(pcm, 48000, 24000)
    assert len(result) == pytest.approx(24000, abs=1)


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

def test_write_json_round_trips_results(tmp_path: Path) -> None:
    results = {'090bpm_click': {'bpm_truth': 90.0, 'bpm_median': 91.2}}
    out = tmp_path / 'results.json'
    _EVAL._write_json(results, out)

    loaded = json.loads(out.read_text())
    assert loaded == results


def test_write_markdown_includes_every_file_and_a_summary(tmp_path: Path) -> None:
    results = {
        '090bpm_click': {
            'bpm_truth': 90.0, 'bpm_median': 90.5, 'bpm_error_abs': 0.5,
            'bpm_error_pct': 0.6, 'harmonic_error_rate': 0.0,
            'time_to_lock_s': 1.2, 'confidence_at_lock': 0.9, 'lane_fast_pct': 0.0,
        },
    }
    out = tmp_path / 'report.md'
    _EVAL._write_markdown(results, out, engine='legacy')

    text = out.read_text()
    assert '090bpm_click' in text
    assert '## Summary' in text
    assert 'legacy' in text


# ---------------------------------------------------------------------------
# run_corpus() — directory-level orchestration
# ---------------------------------------------------------------------------

def test_run_corpus_skips_wav_without_sidecar(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    pcm, _truth = _GEN.generate_clip(120.0, duration_s=1.0)
    wavfile.write(str(tmp_path / 'orphan.wav'), _GEN.SR, (pcm * 32767).astype(np.int16))

    results = _EVAL.run_corpus(tmp_path, engine='legacy')

    assert results == {}
    assert 'SKIP' in capsys.readouterr().out


def test_run_corpus_warns_on_empty_directory(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    results = _EVAL.run_corpus(tmp_path, engine='legacy')
    assert results == {}
    assert 'WARNING' in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Full integration: generate_clip() -> evaluate_file() against real
# Analyzer + BeatGridTracker, harness validating itself against a signal
# with known ground truth.
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

    metrics = _EVAL.evaluate_file(wav_path, truth, engine='legacy', profile_name=profile_name)

    assert metrics['locked_ticks'] > 0, 'harness must actually lock onto its own generated ground truth'
    assert metrics['bpm_error_pct'] < 5.0
    assert metrics['time_to_lock_s'] >= 0.0
