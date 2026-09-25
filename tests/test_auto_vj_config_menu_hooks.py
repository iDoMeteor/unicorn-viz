"""Apply hooks for the remaining [auto_vj] config-menu rows (rc.153).

The rows themselves are built by the config-menu seat; these tests cover
set_config_setting() for each key in the 2026-09-24 coverage audit §3:
restart choices return overrides, live keys change the running controller,
per-mood keys only take effect in USER mood (the documented auto-mood
behavior), and director snap keys re-resolve through the real resolvers.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_AUTO_VJ_SPEC = importlib.util.spec_from_file_location('test_auto_vj_ce_hooks_module', _AUTO_VJ_PATH)
assert _AUTO_VJ_SPEC is not None and _AUTO_VJ_SPEC.loader is not None
_AUTO_VJ_MODULE = importlib.util.module_from_spec(_AUTO_VJ_SPEC)
_AUTO_VJ_SPEC.loader.exec_module(_AUTO_VJ_MODULE)
AutoVJController = _AUTO_VJ_MODULE.AutoVJController
_PROFILE_PRESETS = _AUTO_VJ_MODULE._PROFILE_PRESETS


def _ctrl(*, user_mood: bool = False, enabled: bool = True) -> AutoVJController:
    c = object.__new__(AutoVJController)
    c._cfg = {}
    c._enabled = enabled
    c._explicit_profile_override_keys = set()
    c._use_user_profile_overrides = user_mood
    c._profile_defaults = _PROFILE_PRESETS['normie']
    c._published_bpm_smoothing_enabled = True
    c._published_bpm_smoothing_s = 4.0
    c.applied = 0
    c.toggles = 0

    def _apply() -> None:
        c.applied += 1

    def _toggle() -> bool:
        c.toggles += 1
        c._enabled = not c._enabled
        return c._enabled

    c._apply_profile_settings = _apply
    c.toggle = _toggle
    return c


def test_restart_choices_return_overrides_by_index_or_name() -> None:
    c = _ctrl()
    assert c.set_config_setting('beat_tracker_engine', 2.0) == {'beat_tracker_engine': 'v3'}
    assert c.set_config_setting('beat_tracker_engine', 0.0) == {'beat_tracker_engine': 'v1'}
    assert c.set_config_setting('beat_tracker_engine', 9.0) == {'beat_tracker_engine': 'v3'}
    assert c.set_config_setting('env_source', 2.0) == {'env_source': 'dense_complex'}
    assert c.set_config_setting('env_source', 'dense_flux') == {'env_source': 'dense_flux'}
    assert c._cfg == {}


def test_enabled_toggles_only_on_change() -> None:
    c = _ctrl(enabled=True)
    c.set_config_setting('enabled', 1.0)
    assert c.toggles == 0
    c.set_config_setting('enabled', 0.0)
    assert c.toggles == 1 and c._enabled is False
    c.set_config_setting('enabled', 0.0)
    assert c.toggles == 1


def test_published_bpm_smoothing_is_live_and_clamped() -> None:
    c = _ctrl()
    c.set_config_setting('published_bpm_smoothing_enabled', 0.0)
    assert c._published_bpm_smoothing_enabled is False
    c.set_config_setting('published_bpm_smoothing_s', 99.0)
    assert c._published_bpm_smoothing_s == 15.0
    c.set_config_setting('published_bpm_smoothing_s', 0.0)
    assert c._published_bpm_smoothing_s == 0.5


def test_user_mood_override_is_ignored_outside_user_mood() -> None:
    c = _ctrl(user_mood=False)
    c.set_config_setting('drop_trigger_threshold', 0.50)
    assert c._cfg['drop_trigger_threshold'] == 0.50
    assert 'drop_trigger_threshold' in c._explicit_profile_override_keys
    assert c.applied == 0
    assert c._profile_value('drop_trigger_threshold', 0.60) == _PROFILE_PRESETS['normie']['drop_trigger_threshold']


def test_user_mood_override_applies_in_user_mood_and_clamps() -> None:
    c = _ctrl(user_mood=True)
    c.set_config_setting('drop_sustain_fizzle_floor', 0.25)
    assert c.applied == 1
    assert c._profile_value('drop_sustain_fizzle_floor', 0.35) == 0.25
    c.set_config_setting('drop_trigger_fastlane', 3.0)
    assert c._cfg['drop_trigger_fastlane'] == 1.0


def test_postfx_cruise_slots_parse_and_clear() -> None:
    c = _ctrl(user_mood=True)
    c.set_config_setting('postfx_cruise_slots', '6, 1,2 3,9,x,4,5')
    assert c._cfg['postfx_cruise_slots'] == [1, 2, 3, 4, 5, 6]
    assert c._profile_value('postfx_cruise_slots', [1]) == [1, 2, 3, 4, 5, 6]
    c.set_config_setting('postfx_cruise_slots', '')
    assert 'postfx_cruise_slots' not in c._cfg
    assert 'postfx_cruise_slots' not in c._explicit_profile_override_keys
    assert c.applied == 2


def test_mode_snap_hooks_feed_the_real_resolvers() -> None:
    c = _ctrl()
    c.set_config_setting('mode_snap_unit_climax', 1.0)
    assert c._resolve_mode_snap_unit(c._cfg, 'climax') == 'downbeat'
    c.set_config_setting('mode_phrase_unit_climax', 4.0)
    assert c._resolve_mode_phrase_unit(c._cfg, 'climax') == 4
    c.set_config_setting('mode_phrase_unit_climax', 0.0)
    assert c._resolve_mode_phrase_unit(c._cfg, 'climax') == 1
    c.set_config_setting('mode_phrase_within_bars_breakdown', 40.0)
    assert c._resolve_mode_phrase_within_bars(c._cfg, 'breakdown', 'phrase') == 16.0
    assert c.applied == 4
