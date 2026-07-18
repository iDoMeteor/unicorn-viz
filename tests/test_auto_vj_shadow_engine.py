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

_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_AUTO_VJ_SPEC = importlib.util.spec_from_file_location('test_auto_vj_shadow_module', _AUTO_VJ_PATH)
assert _AUTO_VJ_SPEC is not None and _AUTO_VJ_SPEC.loader is not None
_AUTO_VJ_MODULE = importlib.util.module_from_spec(_AUTO_VJ_SPEC)
_AUTO_VJ_SPEC.loader.exec_module(_AUTO_VJ_MODULE)
AutoVJController = _AUTO_VJ_MODULE.AutoVJController
_load_beat_grid_cls = _AUTO_VJ_MODULE._load_beat_grid_cls
_build_live_training_row = _AUTO_VJ_MODULE._build_live_training_row


# ---- _load_beat_grid_cls('v3') ------------------------------------------


def test_load_beat_grid_cls_v3_resolves_to_beat_tracker_v3() -> None:
    cls = _load_beat_grid_cls('v3')
    assert cls.__name__ == 'BeatTrackerV3'
    assert cls.ENGINE_VERSION == '3.0.0'


def test_load_beat_grid_cls_v2_unaffected_by_v3_addition() -> None:
    cls = _load_beat_grid_cls('v2')
    assert cls.__name__ == 'BeatTracker'
    assert cls.ENGINE_VERSION == '2.0.0'


# ---- _detector_snapshot() shadow fields ----------------------------------


def _bare_controller(grid, shadow_grid) -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._grid = grid
    inst._shadow_grid = shadow_grid
    inst._last_onset_count = 3
    inst._bpm_lock_active = True
    return inst


def test_detector_snapshot_omits_shadow_fields_when_disabled() -> None:
    grid = SimpleNamespace(bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
                            energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1)
    inst = _bare_controller(grid, None)

    snap = inst._detector_snapshot()

    assert 'bpm_shadow' not in snap
    assert 'confidence_shadow' not in snap
    assert 'shadow_engine' not in snap


def test_detector_snapshot_includes_shadow_fields_when_enabled() -> None:
    grid = SimpleNamespace(bpm=124.0, confidence=0.6, downbeat_confidence=0.3,
                            energy=0.5, energy_slope=0.1, drop_score=0.2, beat_phase=0.1)
    shadow = SimpleNamespace(bpm=146.3, confidence=0.58, ENGINE_VERSION='3.0.0')
    inst = _bare_controller(grid, shadow)

    snap = inst._detector_snapshot()

    assert snap['bpm_shadow'] == 146.3
    assert snap['confidence_shadow'] == 0.58
    assert snap['shadow_engine'] == '3.0.0'
    assert snap['bpm'] == 124.0    # active engine's own fields unaffected


# ---- _build_live_training_row() shadow fields ----------------------------


def _row_args(shadow_grid):
    audio = SimpleNamespace(bass=0.5, mid=0.3, treble=0.2, bands=None, waveform=[], spectral_flux=0.1)
    spotify: dict = {}
    state = SimpleNamespace(audio_source='spotify', playlist_mode='')
    grid = SimpleNamespace(bpm=124.0, confidence=0.6)
    return audio, spotify, state, None, grid, shadow_grid


def test_build_live_training_row_omits_shadow_fields_when_disabled() -> None:
    audio, spotify, state, mgr, grid, shadow = _row_args(None)
    row = _build_live_training_row(audio, spotify, state, mgr, grid, shadow_grid=shadow)
    assert 'bpm_shadow' not in row
    assert 'confidence_shadow' not in row
    assert 'shadow_engine' not in row


def test_build_live_training_row_includes_shadow_fields_when_enabled() -> None:
    shadow = SimpleNamespace(bpm=146.3, confidence=0.58, ENGINE_VERSION='3.0.0')
    audio, spotify, state, mgr, grid, shadow = _row_args(shadow)
    row = _build_live_training_row(audio, spotify, state, mgr, grid, shadow_grid=shadow)
    assert row['bpm_shadow'] == 146.3
    assert row['confidence_shadow'] == 0.58
    assert row['shadow_engine'] == '3.0.0'
    assert row['bpm'] == 124.0
