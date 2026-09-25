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
    c._cfg = {}
    c._enabled = False
    c._manual_profile_base = 'normie'
    c._published_bpm_smoothing_enabled = True
    c._published_bpm_smoothing_s = 4.0
    c._mode_snap_unit_build = 'downbeat'
    c._mode_snap_unit_breakdown = 'off'
    c._mode_snap_unit_climax = 'phrase'
    c._mode_phrase_within_bars_breakdown = 0
    c._mode_phrase_within_bars_climax = 2
    c._mode_phrase_unit_climax = 4
    c._explicit_profile_override_keys = set()
    c._use_user_profile_overrides = False
    c._apply_profile_settings = lambda: None
    for key, value in overrides.items():
        setattr(c, key, value)
    return c


def test_row_names_and_shapes() -> None:
    c = _ctrl()
    rows = {r['name']: r for r in c.config_editor_settings()}
    assert list(rows) == [
        'enabled',
        'beat_tracker_engine',
        'env_source',
        'published_bpm_smoothing_enabled',
        'published_bpm_smoothing_s',
        'mode_snap_unit_build',
        'mode_snap_unit_breakdown',
        'mode_snap_unit_climax',
        'mode_phrase_within_bars_breakdown',
        'mode_phrase_within_bars_climax',
        'mode_phrase_unit_climax',
        'drop_trigger_threshold',
        'drop_trigger_fastlane',
        'drop_sustain_entry',
        'drop_sustain_fizzle_floor',
        'postfx_cruise_slots',
        'shadow_engine',
        'genre_matcher_enabled',
        'genre_candidate_scoring_enabled',
        'live_training_enabled',
        'sequence_training_enabled',
        'profile_auto_reco_eval_interval_s',
        'detector_log_interval_s',
        'log_decisions',
        'log_dir',
        'live_training_corpus_path',
        'sequence_training_corpus_path',
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



def test_logging_rows_sit_on_the_logging_tab_and_name_their_config_lines() -> None:
    c = _ctrl(_cfg={'log_decisions': True, 'log_dir': '/var/tmp/avj'})
    rows = {r['name']: r for r in c.config_editor_settings()}
    logging_rows = ('live_training_enabled', 'sequence_training_enabled', 'detector_log_interval_s',
                    'log_decisions', 'log_dir', 'live_training_corpus_path',
                    'sequence_training_corpus_path')
    for name in logging_rows:
        assert rows[name]['tab'] == 'Logging', name
        assert rows[name]['config'] == f'auto_vj.{name}', name
    assert rows['log_decisions']['value'] == 1.0 and rows['log_decisions']['restart'] == 'auto_vj'
    assert rows['log_dir']['kind'] == 'text' and rows['log_dir']['value'] == '/var/tmp/avj'
    assert 'tab' not in rows['wide_bpm_sample_interval_s']        # a performance knob stays put


def test_logging_restart_rows_return_overrides() -> None:
    c = _ctrl()
    assert c.set_config_setting('log_decisions', 0.0) == {'log_decisions': False}
    assert c.set_config_setting('log_dir', ' /tmp/x ') == {'log_dir': '/tmp/x'}
    assert c.set_config_setting('live_training_corpus_path', 'a.jsonl') == {
        'live_training_corpus_path': 'a.jsonl'}


# --- remaining [auto_vj] keys (rc.154; hooks landed in rc.153) -------------- #

_PRESETS = _AUTO_VJ_MODULE._PROFILE_PRESETS


def _rows(c: AutoVJController) -> dict[str, dict]:
    return {r['name']: r for r in c.config_editor_settings()}


def test_every_new_row_names_its_config_line_and_uses_ascii_sections() -> None:
    rows = _rows(_ctrl())
    new = list(rows)[:16]
    assert all(rows[n]['config'] == f'auto_vj.{n}' for n in new)
    assert all(str(r.get('section', '')).isascii() for r in rows.values())


def test_restart_choice_rows_read_the_config_and_round_trip() -> None:
    c = _ctrl(_cfg={'beat_tracker_engine': 'legacy', 'env_source': 'dense_complex'})
    rows = _rows(c)
    assert rows['beat_tracker_engine']['restart'] == 'auto_vj'
    assert rows['beat_tracker_engine']['choices'][int(rows['beat_tracker_engine']['value'])] == 'v1'
    assert rows['env_source']['value'] == 2.0
    assert c.set_config_setting('env_source', rows['env_source']['value']) == {
        'env_source': 'dense_complex'}


def test_hud_smoothing_rows_sit_on_visuals() -> None:
    rows = _rows(_ctrl())
    assert rows['published_bpm_smoothing_enabled']['tab'] == 'Visuals'
    assert rows['published_bpm_smoothing_s']['value'] == 4.0
    assert rows['published_bpm_smoothing_s']['step'] == 0.5


def test_director_rows_show_the_resolved_state_and_round_trip() -> None:
    c = _ctrl()
    rows = _rows(c)
    snap = rows['mode_snap_unit_climax']
    assert snap['choices'][int(snap['value'])] == 'phrase'
    assert rows['mode_phrase_unit_climax']['value'] == 4.0
    c.set_config_setting('mode_snap_unit_build', rows['mode_snap_unit_build']['value'])
    assert c._cfg['mode_snap_unit_build'] == 'downbeat'


def test_user_mood_rows_fall_back_to_the_base_preset() -> None:
    c = _ctrl(_cfg={'drop_trigger_threshold': 0.42})
    rows = _rows(c)
    assert rows['drop_trigger_threshold']['value'] == 0.42
    assert rows['drop_sustain_entry']['value'] == float(_PRESETS['normie']['drop_sustain_entry'])
    assert rows['postfx_cruise_slots']['value'] == ','.join(
        str(x) for x in _PRESETS['normie']['postfx_cruise_slots'])
    assert rows['postfx_cruise_slots']['kind'] == 'text'
