"""Config-editor rows: auto-vj-01's Tier A performance knobs.

Covers the eight rows from docs/planning/
auto-vj-config-editor-performance-rows-2026-09-16.md: shadow engine
(RESTART -- construction only happens in __init__, so a live toggle can't
actually swap it, and this is the v3 soak instrument besides), the two
matcher toggles, the two training-log toggles (live -- LiveCorpusWriter /
SequenceCorpusWriter already support set_enabled() for the existing
Ctrl+Shift+T / Alt+Shift+T hotkeys), and the three cadence sliders.

No weight, threshold or prior is in scope here -- those stay under the
ADR / weights-doc discipline.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_AUTO_VJ_SPEC = importlib.util.spec_from_file_location('test_auto_vj_ce_rows_module', _AUTO_VJ_PATH)
assert _AUTO_VJ_SPEC is not None and _AUTO_VJ_SPEC.loader is not None
_AUTO_VJ_MODULE = importlib.util.module_from_spec(_AUTO_VJ_SPEC)
_AUTO_VJ_SPEC.loader.exec_module(_AUTO_VJ_MODULE)
AutoVJController = _AUTO_VJ_MODULE.AutoVJController


class _FakeWriter:
    """Same enabled/set_enabled shape as LiveCorpusWriter/SequenceCorpusWriter,
    without the file-open behavior (path=None there always ends up disabled,
    which would make a fixture unable to ever reach the 'on' state)."""

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> bool:
        self._enabled = bool(enabled)
        return self._enabled


def _ctrl(**overrides) -> AutoVJController:
    c = object.__new__(AutoVJController)
    c._shadow_engine_name = ''
    c._genre_matcher_enabled = True
    c._genre_candidate_scoring_enabled = True
    c._live_corpus_writer = _FakeWriter(False)
    c._sequence_corpus_writer = _FakeWriter(False)
    c._profile_auto_reco_eval_interval_s = 8.0
    c._detector_log_interval_s = 1.0
    c._wide_bpm_sample_interval_s = 2.0
    for key, value in overrides.items():
        setattr(c, key, value)
    return c


def test_row_names_and_shapes() -> None:
    c = _ctrl()
    rows = {r['name']: r for r in c.config_editor_settings()}
    assert list(rows) == [
        'shadow_engine',
        'genre_matcher_enabled',
        'genre_candidate_scoring_enabled',
        'live_training_enabled',
        'sequence_training_enabled',
        'profile_auto_reco_eval_interval_s',
        'detector_log_interval_s',
        'wide_bpm_sample_interval_s',
    ]
    assert all(r.get('hint') for r in rows.values())
    assert rows['shadow_engine']['kind'] == 'toggle'
    assert rows['shadow_engine']['restart'] == 'auto_vj'
    assert rows['genre_matcher_enabled']['kind'] == 'toggle'
    assert 'restart' not in rows['genre_matcher_enabled']
    assert rows['profile_auto_reco_eval_interval_s']['display'] == '8.0 s'


def test_shadow_engine_row_reflects_current_state_but_is_restart_only() -> None:
    off = _ctrl(_shadow_engine_name='')
    on = _ctrl(_shadow_engine_name='v2')
    rows_off = {r['name']: r for r in off.config_editor_settings()}
    rows_on = {r['name']: r for r in on.config_editor_settings()}
    assert rows_off['shadow_engine']['value'] == 0.0
    assert rows_on['shadow_engine']['value'] == 1.0
    # The setter never mutates the live instance -- construction only
    # happens in __init__, so applying live would just lie in telemetry
    # until an actual restart. It returns the override for core to persist.
    result_on = off.set_config_setting('shadow_engine', 1.0)
    assert result_on == {'beat_tracker_shadow_engine': 'v2'}
    assert off._shadow_engine_name == ''
    result_off = on.set_config_setting('shadow_engine', 0.0)
    assert result_off == {'beat_tracker_shadow_engine': ''}
    assert on._shadow_engine_name == 'v2'


def test_matcher_toggles_apply_live() -> None:
    c = _ctrl(_genre_matcher_enabled=True, _genre_candidate_scoring_enabled=True)
    assert c.set_config_setting('genre_matcher_enabled', 0.0) is None
    assert c._genre_matcher_enabled is False
    assert c.set_config_setting('genre_candidate_scoring_enabled', 0.0) is None
    assert c._genre_candidate_scoring_enabled is False
    c.set_config_setting('genre_matcher_enabled', 1.0)
    assert c._genre_matcher_enabled is True


def test_training_log_toggles_drive_the_real_corpus_writer_api() -> None:
    c = _ctrl()
    assert c._live_corpus_writer.enabled is False
    assert c.set_config_setting('live_training_enabled', 1.0) is None
    assert c._live_corpus_writer.enabled is True
    rows = {r['name']: r for r in c.config_editor_settings()}
    assert rows['live_training_enabled']['value'] == 1.0

    assert c.set_config_setting('sequence_training_enabled', 1.0) is None
    assert c._sequence_corpus_writer.enabled is True
    c.set_config_setting('sequence_training_enabled', 0.0)
    assert c._sequence_corpus_writer.enabled is False


def test_cadence_sliders_clamp() -> None:
    c = _ctrl()
    c.set_config_setting('profile_auto_reco_eval_interval_s', 0.0)
    assert c._profile_auto_reco_eval_interval_s == 1.0
    c.set_config_setting('profile_auto_reco_eval_interval_s', 999.0)
    assert c._profile_auto_reco_eval_interval_s == 30.0
    c.set_config_setting('detector_log_interval_s', -5.0)
    assert c._detector_log_interval_s == 0.0
    c.set_config_setting('wide_bpm_sample_interval_s', 0.0)
    assert c._wide_bpm_sample_interval_s == 0.5


def test_unknown_setting_is_ignored() -> None:
    c = _ctrl()
    assert c.set_config_setting('not_a_real_row', 1.0) is None
