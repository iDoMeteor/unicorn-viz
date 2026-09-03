"""Tests for drop-ins/training-kit-01/tools/director_placement.py.

Per docs/planning/director-placement-scoring-2026-09-03.md deliverable 3:
a synthetic corpus with events fired exactly at energy steps and phrase
boundaries must score ~100% with chance well below that; events fired at
random must score ~= chance. Loaded via the same importlib-by-path pattern
the rest of this test suite uses for training-kit-01 tools.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_TOOLS = _REPO / 'drop-ins' / 'training-kit-01' / 'tools'


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


dp = _load('test_director_placement_module', _TOOLS / 'director_placement.py')

BPM = 120.0
BAR_S = 240.0 / BPM  # 2.0s
HEARTBEAT_STEP_S = 0.25


def _heartbeat_row(track: str, t: float, energy: float, bass: float,
                    beat_phase: float, bars_since_track_start: int,
                    bars_since_phase_entry: int, vj_mode: str,
                    impact_novelty: float = 0.3) -> dict:
    return {
        'track_path': track, 'capture_time': t, 'bpm': BPM,
        'energy': energy, 'bass': bass, 'beat_phase': beat_phase,
        'bars_since_track_start': bars_since_track_start,
        'bars_since_phase_entry': bars_since_phase_entry,
        'vj_mode': vj_mode, 'impact_novelty': impact_novelty,
    }


def _event_row(track: str, t: float, event_type: str, bars_since_track_start: int,
               beat_phase: float = 0.0, **extra) -> dict:
    row = {
        'track_path': track, 'capture_time': t, 'bpm': BPM,
        'event_type': event_type, 'beat_phase': beat_phase,
        'bars_since_track_start': bars_since_track_start,
        'bars_since_phase_entry': 0,  # true on every real transition row
    }
    row.update(extra)
    return row


def _make_perfect_corpus(track: str, n_bars: int = 40,
                          event_bar_step: int = 8) -> list[dict]:
    """Heartbeats with a genuine monotonic energy staircase -- each
    event_bar_step-bar block strictly higher than the last -- and
    drop_fire events fired exactly at each block boundary, on-beat. The
    pre/post windows (2 bars either side) never cross a block boundary
    other than the one at the event itself, so post/pre exactly equals
    that block-to-block step ratio: everything a "landed" drop should
    look like, by construction, with a comfortable margin over the 1.10
    lift threshold at every step (smallest ratio ~1.2, not a hair above)."""
    rows: list[dict] = []
    total_s = n_bars * BAR_S
    t = 0.0
    event_times = {b * BAR_S for b in range(event_bar_step, n_bars, event_bar_step)}
    while t < total_s:
        bar = int(t // BAR_S)
        block = bar // event_bar_step
        energy = 0.30 + 0.15 * block  # strictly increasing, ratio >= 1.2 at every step
        bass = energy
        # beat_phase: near 0 right at bar starts, off-beat mid-bar -- so
        # the chance pool (on-beat only) samples near bar starts too, not
        # literally identical to the events, and off-beat frames (most of
        # the corpus) are correctly excluded from both the real and
        # chance measurements.
        phase_in_bar = (t % BAR_S) / BAR_S
        beat_phase = min(phase_in_bar, 1 - phase_in_bar)
        rows.append(_heartbeat_row(track, t, energy, bass, beat_phase,
                                    bar, bar % event_bar_step, 'CRUISE'))
        t += HEARTBEAT_STEP_S
    for bt in sorted(event_times):
        bar = int(bt // BAR_S)
        rows.append(_event_row(track, bt, 'drop_fire', bar, beat_phase=0.0,
                                impact_novelty=0.95, peak_tier='major'))
    rows.sort(key=lambda r: r['capture_time'])
    return rows


def _make_random_corpus(track: str, n_bars: int = 64, n_events: int = 8,
                         seed: int = 3) -> list[dict]:
    """Heartbeats with energy that wobbles with no relationship to event
    placement; drop_fire events fired at arbitrary, non-boundary,
    off-beat bar offsets. Should score ~= chance on every metric."""
    import random as _random
    rng = _random.Random(seed)
    rows: list[dict] = []
    total_s = n_bars * BAR_S
    t = 0.0
    while t < total_s:
        bar = int(t // BAR_S)
        energy = 0.4 + 0.3 * rng.random()  # noisy, no step pattern
        bass = 0.4 + 0.3 * rng.random()
        beat_phase = rng.random()
        rows.append(_heartbeat_row(track, t, energy, bass, beat_phase,
                                    bar, bar % 8, 'CRUISE',
                                    impact_novelty=rng.random()))
        t += HEARTBEAT_STEP_S
    # events at deliberately off-boundary, off-beat bar-fractional offsets
    for i in range(n_events):
        bar = 3 + i * (n_bars // n_events)  # not a multiple of 8
        bt = bar * BAR_S + 0.6 * BAR_S       # mid-bar, off-beat
        rows.append(_event_row(track, bt, 'drop_fire', bar, beat_phase=0.5,
                                impact_novelty=0.3))
    rows.sort(key=lambda r: r['capture_time'])
    return rows


def _write_corpus(tmp_path: Path, rows: list[dict]) -> Path:
    import json
    bucket = tmp_path / 'bucket'
    bucket.mkdir()
    f = bucket / 'sequence-replay-test.jsonl'
    f.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
    return bucket


def test_perfect_placement_scores_near_100_with_chance_well_below(tmp_path: Path) -> None:
    rows = _make_perfect_corpus('trackA.mp3')
    bucket = _write_corpus(tmp_path, rows)
    result = dp.analyse(bucket, seed=7)
    m = result['metrics']

    assert m['drop_fire.energy_lift']['rate_pct'] == 100.0
    assert m['drop_fire.energy_lift']['chance_pct'] < 50.0
    assert m['drop_fire.bass_lift']['rate_pct'] == 100.0
    assert m['drop_fire.phrase_alignment_8']['rate_pct'] == 100.0
    assert m['drop_fire.beat_alignment']['rate_pct'] == 100.0
    assert m['drop_fire.novelty_p75']['rate_pct'] == 100.0
    # placement score should be high given every drop metric landed
    assert result['placement_score'] >= 0.40
    assert result['placement_rating'] == 5


def test_random_placement_scores_near_chance(tmp_path: Path) -> None:
    rows = _make_random_corpus('trackB.mp3')
    bucket = _write_corpus(tmp_path, rows)
    result = dp.analyse(bucket, seed=7)
    m = result['metrics']

    # phrase alignment: events deliberately placed off any 8-bar boundary,
    # so the real rate should read 0% (never within tol=1 of a boundary)
    assert m['drop_fire.phrase_alignment_8']['rate_pct'] == 0.0
    # beat alignment: events fired at beat_phase=0.5 (as off-beat as
    # possible), so real rate must be 0, independent of chance
    assert m['drop_fire.beat_alignment']['rate_pct'] == 0.0
    # placement score should be low -- nothing "landed" by construction
    assert result['placement_score'] < 0.20


def test_placement_rating_thresholds() -> None:
    assert dp._placement_rating(0.45) == 5
    assert dp._placement_rating(0.40) == 5
    assert dp._placement_rating(0.30) == 4
    assert dp._placement_rating(0.25) == 4
    assert dp._placement_rating(0.15) == 3
    assert dp._placement_rating(0.12) == 3
    assert dp._placement_rating(0.05) == 2
    assert dp._placement_rating(0.04) == 2
    assert dp._placement_rating(0.0) == 1


def test_onbeat_matches_reference_definition() -> None:
    assert dp._onbeat({'beat_phase': 0.0}) is True
    assert dp._onbeat({'beat_phase': 0.1}) is True
    assert dp._onbeat({'beat_phase': 0.95}) is True  # wraps near 1.0
    assert dp._onbeat({'beat_phase': 0.5}) is False
    assert dp._onbeat({'beat_phase': 0.3}) is False


def test_phrase_boundary_distance_wraps_correctly() -> None:
    # exactly at a boundary
    assert dp._phrase_boundary_distance(16.0, 8.0) == 0.0
    assert dp._phrase_boundary_distance(0.0, 8.0) == 0.0
    # one bar off a boundary (7 -> distance 1 to the next multiple of 8)
    assert dp._phrase_boundary_distance(7.0, 8.0) == 1.0
    assert dp._phrase_boundary_distance(9.0, 8.0) == 1.0
    # mid-phrase, far from any boundary
    assert dp._phrase_boundary_distance(4.0, 8.0) == 4.0


def test_dwell_sanity_reads_the_outgoing_phase_not_the_incoming_one(tmp_path: Path) -> None:
    """2026-09-03: found live -- bars_since_phase_entry on a transition
    row itself is always 0 (the new phase has just begun), so reading it
    directly trivially scores 100% under-hold regardless of anything
    real. The metric must look at the heartbeat immediately BEFORE the
    transition to see how long the phase being LEFT actually dwelled."""
    track = 'trackC.mp3'
    rows = []
    # BUILD phase held for a genuinely healthy 10 bars (RISE's expected
    # window is 8-16 per PHRASE_ROLE_BARS_DEFAULT) before breaking down.
    for bar in range(10):
        t = bar * BAR_S
        rows.append(_heartbeat_row(track, t, 0.6, 0.6, 0.0, bar, bar, 'BUILD'))
    trans_t = 10 * BAR_S
    rows.append(_event_row(track, trans_t, 'mode_transition', 10, new_mode='breakdown'))
    for bar in range(11, 20):
        t = bar * BAR_S
        rows.append(_heartbeat_row(track, t, 0.3, 0.3, 0.0, bar, bar - 11, 'BREAKDOWN'))
    bucket = _write_corpus(tmp_path, rows)
    result = dp.analyse(bucket, seed=7)
    dwell = result['metrics']['any.dwell_sanity']
    assert dwell['n'] == 1
    # 10 bars is within RISE's 8-16 expected window -- must read in_window,
    # not the vacuous under_hold=100% the bug would have produced.
    assert dwell['in_window_pct'] == 100.0
    assert dwell['under_hold_pct'] == 0.0


def test_json_and_markdown_output(tmp_path: Path) -> None:
    rows = _make_perfect_corpus('trackD.mp3', n_bars=32)
    bucket = _write_corpus(tmp_path, rows)
    out_json = tmp_path / 'out.json'
    rc = dp.main([str(bucket), '--json', str(out_json), '--seed', '7'])
    assert rc == 0
    assert out_json.exists()
    import json
    data = json.loads(out_json.read_text())
    assert 'placement_score' in data
    assert 'placement_rating' in data
    assert data['metrics']


def test_missing_corpus_file_errors_cleanly(tmp_path: Path) -> None:
    empty_bucket = tmp_path / 'empty'
    empty_bucket.mkdir()
    with pytest.raises(FileNotFoundError):
        dp.analyse(empty_bucket)
    rc = dp.main([str(empty_bucket)])
    assert rc == 1
