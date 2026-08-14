"""Tests for the shadow-engine A/B wiring in auto_vj.py:

- _load_beat_grid_cls('v3') resolves to BeatTrackerV3.
- _detector_snapshot() includes bpm_shadow/confidence_shadow/shadow_engine
  only when a shadow tracker is configured.
- _build_live_training_row() does the same for sequence/live corpus rows.

Shadow mode never touches director/recommender behavior -- these tests only
check the reporting surface, not any decision-making change.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_AUTO_VJ_SPEC = importlib.util.spec_from_file_location('test_auto_vj_shadow_module', _AUTO_VJ_PATH)
assert _AUTO_VJ_SPEC is not None and _AUTO_VJ_SPEC.loader is not None
_AUTO_VJ_MODULE = importlib.util.module_from_spec(_AUTO_VJ_SPEC)
_AUTO_VJ_SPEC.loader.exec_module(_AUTO_VJ_MODULE)
AutoVJController = _AUTO_VJ_MODULE.AutoVJController
_load_beat_grid_cls = _AUTO_VJ_MODULE._load_beat_grid_cls
_build_live_training_row = _AUTO_VJ_MODULE._build_live_training_row


# ---- _load_beat_grid_cls('v3') ------------------------------------------


def test_load_beat_grid_cls_v3_is_a_deprecated_alias_for_v2() -> None:
    """2026-08-14, round three: BeatTrackerV3 retired -- its one override
    folded directly into BeatTracker once real session data showed zero
    live behavioral difference. 'v3' now resolves to the same class as
    'v2', kept only so existing configs don't break. See
    docs/adr/vj-system.md."""
    cls = _load_beat_grid_cls('v3')
    assert cls.__name__ == 'BeatTracker'
    assert cls.ENGINE_VERSION == '2.0.0'


def test_load_beat_grid_cls_v2_and_v3_resolve_to_equivalent_classes() -> None:
    """Each call re-execs beat_grid.py as a fresh module (see
    _load_beat_grid_cls's own implementation), so this can't assert
    identity across two separate calls -- checks the two resolve to the
    same class by name/version instead."""
    v2_cls = _load_beat_grid_cls('v2')
    v3_cls = _load_beat_grid_cls('v3')
    assert v2_cls.__name__ == v3_cls.__name__ == 'BeatTracker'
    assert v2_cls.ENGINE_VERSION == v3_cls.ENGINE_VERSION == '2.0.0'


# ---- _detector_snapshot() shadow fields ----------------------------------


def _bare_controller(grid, shadow_grid, shadow2_grid=None) -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._grid = grid
    inst._shadow_grid = shadow_grid
    inst._shadow2_grid = shadow2_grid
    inst._last_onset_count = 3
    inst._bpm_lock_active = True
    return inst


def test_detector_snapshot_omits_shadow_fields_when_disabled() -> None:
    grid = SimpleNamespace(bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
                            energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
                            ENGINE_VERSION='3.0.0')
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert 'bpm_shadow' not in snap
    assert 'confidence_shadow' not in snap
    assert 'shadow_engine' not in snap
    assert snap['engine_version'] == '3.0.0'


def test_detector_snapshot_includes_shadow_fields_when_enabled() -> None:
    grid = SimpleNamespace(bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
                            energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
                            ENGINE_VERSION='3.0.0')
    shadow = SimpleNamespace(bpm=146.3, confidence=0.58, ENGINE_VERSION='3.0.0')
    inst = _bare_controller(grid, shadow)

    snap = inst._detector_snapshot()

    assert snap['bpm_shadow'] == 146.3
    assert snap['confidence_shadow'] == 0.58
    assert snap['shadow_engine'] == '3.0.0'
    assert snap['bpm'] == 124.0    # active engine's own fields unaffected


def test_detector_snapshot_omits_shadow2_fields_when_disabled() -> None:
    grid = SimpleNamespace(bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
                            energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
                            ENGINE_VERSION='3.0.0')
    inst = _bare_controller(grid, None, None)

    snap = inst._detector_snapshot()

    assert 'bpm_shadow2' not in snap
    assert 'confidence_shadow2' not in snap
    assert 'shadow2_engine' not in snap


def test_detector_snapshot_includes_both_shadow_slots_independently() -> None:
    """2026-08-14, round three: second, independent shadow slot -- for a
    real three-way v1/v2/v3 comparison, not mutually exclusive with the
    first shadow. See
    docs/planning/auto-vj-round-three-planning-2026-08-14.md § 7."""
    grid = SimpleNamespace(bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
                            energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
                            ENGINE_VERSION='3.0.0')
    shadow = SimpleNamespace(bpm=146.3, confidence=0.58, ENGINE_VERSION='2.0.0')
    shadow2 = SimpleNamespace(bpm=73.2, confidence=0.71, ENGINE_VERSION='1.0.0')
    inst = _bare_controller(grid, shadow, shadow2)

    snap = inst._detector_snapshot()

    assert snap['bpm_shadow'] == 146.3
    assert snap['shadow_engine'] == '2.0.0'
    assert snap['bpm_shadow2'] == 73.2
    assert snap['confidence_shadow2'] == 0.71
    assert snap['shadow2_engine'] == '1.0.0'
    assert snap['bpm'] == 124.0    # active engine's own fields unaffected


# ---- _detector_snapshot() kr/dbc fields (2026-08-14) ----------------------


def test_detector_snapshot_includes_kr_dbc_fields_when_grid_has_them() -> None:
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='3.0.0',
        kick_regularity=0.72, effective_tactus_ratio=0.63,
        tactus_fold_accepted_count=4, tactus_region_reject_count=2,
        tactus_score_reject_count=11,
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['kick_regularity'] == pytest.approx(0.72)
    assert snap['effective_tactus_ratio'] == pytest.approx(0.63)
    assert snap['tactus_fold_accepted_count'] == 4
    assert snap['tactus_region_reject_count'] == 2
    assert snap['tactus_score_reject_count'] == 11


def test_detector_snapshot_kr_dbc_fields_default_when_grid_lacks_them() -> None:
    """v1 (BeatGridTracker) has no tactus mechanism at all -- must not
    raise, must default to 0.0/0 rather than omitting the keys (downstream
    corpus/decision-log consumers expect a stable schema)."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='1.0.0',
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['kick_regularity'] == 0.0
    assert snap['effective_tactus_ratio'] == 0.0
    assert snap['tactus_fold_accepted_count'] == 0
    assert snap['tactus_region_reject_count'] == 0
    assert snap['tactus_score_reject_count'] == 0


# ---- _detector_snapshot() acf_top_candidates (2026-08-14) -----------------


def test_detector_snapshot_formats_acf_top_candidates() -> None:
    """BeatTracker.top_candidates (prior-free, top-3 bpm/normalised-score
    pairs, already computed every ACF cycle for top_cand_fit scoring) was
    never logged anywhere -- added so a tempo-ambiguous session can be
    checked against what the comb filter actually saw as competing
    candidates, not just the one BPM that won."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='3.0.0',
        top_candidates=[(122.5, 0.412), (112.03, 0.355), (145.1, 0.233)],
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['acf_top_candidates'] == '122.50:0.412,112.03:0.355,145.10:0.233'


def test_detector_snapshot_acf_top_candidates_empty_when_grid_lacks_it() -> None:
    """v1 (BeatGridTracker) has no top_candidates property -- must not
    raise, must default to an empty string rather than omitting the key."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='1.0.0',
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['acf_top_candidates'] == ''


# ---- _detector_snapshot() downbeat_regularity (2026-08-14, later still) ---


def test_detector_snapshot_reads_downbeat_regularity() -> None:
    """BeatTracker.downbeat_regularity (the confidence blend's third term,
    cached from the most recent blend computation) was never logged --
    only downbeat_confidence, a different composite metric that already
    has phase/acf baked in. Added alongside the 0.6/0.2/0.2 -> 0.65/0.1/
    0.25 weight re-tune so the real term can be checked against data."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='3.0.0', downbeat_regularity=0.47,
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['downbeat_regularity'] == pytest.approx(0.47)


def test_detector_snapshot_downbeat_regularity_zero_when_grid_lacks_it() -> None:
    """v1 (BeatGridTracker) has no downbeat_regularity property -- must not
    raise, must default to 0.0 rather than omitting the key."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='1.0.0',
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['downbeat_regularity'] == 0.0


def test_detector_snapshot_reads_region_consistency_and_last_tactus_fold() -> None:
    """2026-08-14, later still again: the BPM-value accept/reject gate
    stack was entirely invisible in the training corpus -- only its
    cumulative tactus counters and the raw acf_confidence were ever
    logged. region_consistency is the large-jump gate's own check;
    last_tactus_fold is the most recent individual fold decision, not
    just a tally. Added the same night a real carry-over incident
    (garbage/k) exposed the gap."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='3.0.0', region_consistency=0.62,
        last_tactus_fold='accepted:150.00->75.00',
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['region_consistency'] == pytest.approx(0.62)
    assert snap['last_tactus_fold'] == 'accepted:150.00->75.00'


def test_detector_snapshot_region_consistency_and_tactus_fold_default_when_grid_lacks_them() -> None:
    """v1 (BeatGridTracker) has neither mechanism -- must not raise, must
    default to 0.0/'' rather than omitting the keys."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='1.0.0',
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['region_consistency'] == 0.0
    assert snap['last_tactus_fold'] == ''


def test_detector_snapshot_reads_large_jump_persistence_counters() -> None:
    """2026-08-14, later still still (round two): owner asked to track the
    long-window persistence check's own engagement so it doesn't go
    untuned and forgotten the way several other gate constants did before
    this session."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='3.0.0', large_jump_persistence_wait_count=2,
        large_jump_persistence_reject_count=24, large_jump_persistence_cleared_count=10,
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['large_jump_persistence_wait_count'] == 2
    assert snap['large_jump_persistence_reject_count'] == 24
    assert snap['large_jump_persistence_cleared_count'] == 10


def test_detector_snapshot_large_jump_persistence_counters_zero_when_grid_lacks_them() -> None:
    """v1 (BeatGridTracker) has no such mechanism -- must not raise, must
    default to 0 rather than omitting the keys."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='1.0.0',
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['large_jump_persistence_wait_count'] == 0
    assert snap['large_jump_persistence_reject_count'] == 0
    assert snap['large_jump_persistence_cleared_count'] == 0


def test_detector_snapshot_reads_long_candidate_spread_and_median() -> None:
    """2026-08-14, round three: the persistence check's own median/spread,
    previously computed and discarded every evaluation, now cached and
    logged so the 6.0 BPM spread threshold can be judged from ground
    truth instead of reconstructed from the coarser decision-tick log."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='3.0.0', long_candidate_spread=3.2, long_candidate_median=123.5,
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['long_candidate_spread'] == pytest.approx(3.2)
    assert snap['long_candidate_median'] == pytest.approx(123.5)


def test_detector_snapshot_long_candidate_spread_zero_when_grid_lacks_it() -> None:
    """v1 (BeatGridTracker) has no such mechanism -- must not raise, must
    default to 0.0 rather than omitting the keys."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='1.0.0',
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['long_candidate_spread'] == 0.0
    assert snap['long_candidate_median'] == 0.0


def test_detector_snapshot_reads_flux_fields() -> None:
    """2026-08-14, round three: found via a front-to-back sweep over every
    public BeatTracker property -- both are real, already-computed inputs
    to drop_score, but were never logged."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='3.0.0', spectral_flux_smooth=1.25, bass_flux_fast=0.87,
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['spectral_flux_smooth'] == pytest.approx(1.25)
    assert snap['bass_flux_fast'] == pytest.approx(0.87)


def test_detector_snapshot_flux_fields_zero_when_grid_lacks_them() -> None:
    """v1 (BeatGridTracker) has no such mechanism -- must not raise, must
    default to 0.0 rather than omitting the keys."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='1.0.0',
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['spectral_flux_smooth'] == 0.0
    assert snap['bass_flux_fast'] == 0.0


def test_detector_snapshot_reads_kick_evidence_fields() -> None:
    """2026-08-14, round three, the morning after (part two): the new
    sparse-evidence update gate's own signal and engagement counter."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='2.0.0', kick_evidence_smooth=0.42,
        kick_evidence_reject_count=7,
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['kick_evidence_smooth'] == pytest.approx(0.42)
    assert snap['kick_evidence_reject_count'] == 7


def test_detector_snapshot_kick_evidence_fields_default_when_grid_lacks_them() -> None:
    """v1 (BeatGridTracker) has no such mechanism -- must not raise, must
    default to 0.0/0 rather than omitting the keys."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='1.0.0',
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['kick_evidence_smooth'] == 0.0
    assert snap['kick_evidence_reject_count'] == 0


def test_detector_snapshot_reads_acf_interpolation_delta() -> None:
    """2026-08-14, round three: A/B instrumentation for the sub-lag peak
    interpolation proposal (gated off by default). Nonzero only once the
    flag is flipped on, so the two runs' logs are directly comparable on
    this field alone."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='3.0.0', acf_interpolation_delta_bpm=-0.42,
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['acf_interpolation_delta_bpm'] == pytest.approx(-0.42)


def test_detector_snapshot_acf_interpolation_delta_zero_when_grid_lacks_it() -> None:
    """v1 (BeatGridTracker) has no ACF at all -- must not raise, must
    default to 0.0 rather than omitting the key."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='1.0.0',
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['acf_interpolation_delta_bpm'] == 0.0


def test_detector_snapshot_reads_lock_band_and_candidates() -> None:
    """2026-08-14, round three: the real live lock band plus two
    candidate replacement shapes, logged only -- owner: 'code them both
    up but just log both for one session with everything else as is.'"""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='3.0.0', lock_band_bpm=4.0,
        lock_band_candidate_analytical=2.56, lock_band_candidate_empirical=3.0,
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['lock_band_bpm'] == pytest.approx(4.0)
    assert snap['lock_band_candidate_analytical'] == pytest.approx(2.56)
    assert snap['lock_band_candidate_empirical'] == pytest.approx(3.0)


def test_detector_snapshot_lock_band_fields_zero_when_grid_lacks_them() -> None:
    """v1 (BeatGridTracker) has no such mechanism -- must not raise, must
    default to 0.0 rather than omitting the keys."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='1.0.0',
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['lock_band_bpm'] == 0.0
    assert snap['lock_band_candidate_analytical'] == 0.0
    assert snap['lock_band_candidate_empirical'] == 0.0


def test_detector_snapshot_reports_bpm_lock_schmidt_trigger_floors() -> None:
    """2026-08-14, round three: owner asked to log the gain/release floor
    that bpm_locked is actually measured against, not just the resulting
    bool. Static per-class constants (not per-instance tunable), logged
    every row."""
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='3.0.0',
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['bpm_lock_gain_confidence'] == AutoVJController._BPM_LOCK_CONFIDENCE
    assert snap['bpm_lock_release_confidence'] == AutoVJController._BPM_LOCK_RELEASE_CONFIDENCE


def test_detector_snapshot_reports_bpm_lock_floors_when_grid_is_none() -> None:
    inst = _bare_controller(None, None)

    snap = inst._detector_snapshot()

    assert snap['bpm_lock_gain_confidence'] == AutoVJController._BPM_LOCK_CONFIDENCE
    assert snap['bpm_lock_release_confidence'] == AutoVJController._BPM_LOCK_RELEASE_CONFIDENCE


# ---- _build_live_training_row() shadow fields ----------------------------


def _row_args(shadow_grid):
    audio = SimpleNamespace(bass=0.5, mid=0.3, treble=0.2, bands=None, waveform=[], spectral_flux=0.1)
    spotify: dict = {}
    state = SimpleNamespace(audio_source='spotify', playlist_mode='')
    grid = SimpleNamespace(bpm=124.0, confidence=0.6, ENGINE_VERSION='2.0.0')
    return audio, spotify, state, None, grid, shadow_grid


def test_build_live_training_row_omits_shadow_fields_when_disabled() -> None:
    audio, spotify, state, mgr, grid, shadow = _row_args(None)
    row = _build_live_training_row(audio, spotify, state, mgr, grid, shadow_grid=shadow)
    assert 'bpm_shadow' not in row
    assert 'confidence_shadow' not in row
    assert 'shadow_engine' not in row
    assert row['engine_version'] == '2.0.0'


def test_build_live_training_row_includes_shadow_fields_when_enabled() -> None:
    shadow = SimpleNamespace(bpm=146.3, confidence=0.58, ENGINE_VERSION='3.0.0')
    audio, spotify, state, mgr, grid, shadow = _row_args(shadow)
    row = _build_live_training_row(audio, spotify, state, mgr, grid, shadow_grid=shadow)
    assert row['bpm_shadow'] == 146.3
    assert row['confidence_shadow'] == 0.58
    assert row['shadow_engine'] == '3.0.0'
    assert row['bpm'] == 124.0


def test_build_live_training_row_omits_shadow2_fields_when_disabled() -> None:
    audio, spotify, state, mgr, grid, _shadow = _row_args(None)
    row = _build_live_training_row(audio, spotify, state, mgr, grid)
    assert 'bpm_shadow2' not in row
    assert 'confidence_shadow2' not in row
    assert 'shadow2_engine' not in row


def test_build_live_training_row_includes_both_shadow_slots_independently() -> None:
    """2026-08-14, round three: second, independent shadow slot -- for a
    real three-way v1/v2/v3 comparison."""
    audio, spotify, state, mgr, grid, _shadow = _row_args(None)
    shadow = SimpleNamespace(bpm=146.3, confidence=0.58, ENGINE_VERSION='2.0.0')
    shadow2 = SimpleNamespace(bpm=73.2, confidence=0.71, ENGINE_VERSION='1.0.0')
    row = _build_live_training_row(audio, spotify, state, mgr, grid, shadow_grid=shadow, shadow2_grid=shadow2)
    assert row['bpm_shadow'] == 146.3
    assert row['shadow_engine'] == '2.0.0'
    assert row['bpm_shadow2'] == 73.2
    assert row['confidence_shadow2'] == 0.71
    assert row['shadow2_engine'] == '1.0.0'
    assert row['bpm'] == 124.0
    assert row['engine_version'] == '2.0.0'   # active engine, distinct from shadow_engine


# ---- _audio_profile_snapshot() analyzer_refractory_s (2026-08-14, round
# three, audit cross-check item 12.8 #1) -----------------------------------


def _bare_audio_profile_controller(manager) -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._app = SimpleNamespace(_audio_manager=manager)
    return inst


def test_audio_profile_snapshot_reads_analyzer_refractory_s() -> None:
    """New field testing a candidate root-cause mechanism (audit T4): a
    confident-but-wrong BPM can suppress every other true beat at the
    source via this refractory, entrenching the wrong lock."""
    manager = SimpleNamespace(
        get_profile_key=lambda: 'house',
        get_profile=lambda: SimpleNamespace(name='House', preferred_bpm_range=lambda: (118.0, 126.0)),
        refractory_s=0.328125,
    )
    inst = _bare_audio_profile_controller(manager)

    snap = inst._audio_profile_snapshot()

    assert snap['analyzer_refractory_s'] == pytest.approx(0.328125)


def test_audio_profile_snapshot_refractory_s_zero_when_manager_lacks_it() -> None:
    """Older core without the property -- must not raise, must default to
    0.0 rather than omitting the key."""
    manager = SimpleNamespace(
        get_profile_key=lambda: 'house',
        get_profile=lambda: SimpleNamespace(name='House', preferred_bpm_range=lambda: (118.0, 126.0)),
    )
    inst = _bare_audio_profile_controller(manager)

    snap = inst._audio_profile_snapshot()

    assert snap['analyzer_refractory_s'] == 0.0


def test_audio_profile_snapshot_omits_everything_when_manager_is_none() -> None:
    inst = _bare_audio_profile_controller(None)
    assert inst._audio_profile_snapshot() == {}


# ---- _detector_snapshot() phase_confidence_calibrated (2026-08-14, round
# three, audit cross-check item 12.8 #3) ------------------------------------


def test_detector_snapshot_reads_phase_confidence_calibrated() -> None:
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='3.0.0', phase_confidence_calibrated=0.42,
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['phase_confidence_calibrated'] == pytest.approx(0.42)


def test_detector_snapshot_phase_confidence_calibrated_zero_when_grid_lacks_it() -> None:
    grid = SimpleNamespace(
        bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
        energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1,
        ENGINE_VERSION='1.0.0',
    )
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert snap['phase_confidence_calibrated'] == 0.0
