"""Tests for the Essentia target-label tagging and recommender weight loading:

- cycle_profile() tags a manual profile switch with reason='manual_override'
  (the implicit label compute_override_target_scores() looks for).
- _load_recommender_weights() promotes a fitted weight set when present and
  falls back to _DEFAULT_RECO_WEIGHTS gracefully otherwise.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_AUTO_VJ_SPEC = importlib.util.spec_from_file_location('test_auto_vj_labels_module', _AUTO_VJ_PATH)
assert _AUTO_VJ_SPEC is not None and _AUTO_VJ_SPEC.loader is not None
_AUTO_VJ_MODULE = importlib.util.module_from_spec(_AUTO_VJ_SPEC)
_AUTO_VJ_SPEC.loader.exec_module(_AUTO_VJ_MODULE)
AutoVJController = _AUTO_VJ_MODULE.AutoVJController


# ---- cycle_profile() manual_override tagging --------------------------------


def _bare_controller() -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._manual_profile = 'auto'
    inst._explicit_profile_override_keys = set()
    inst._auto_profile_enabled = True
    inst._profile_auto_reco_decider_enabled = True
    inst._profile = 'house'
    return inst


def test_cycle_profile_manual_switch_tags_manual_override() -> None:
    inst = _bare_controller()
    calls: list[tuple[tuple, dict]] = []
    inst._set_active_profile = lambda *a, **kw: calls.append((a, kw))

    inst.cycle_profile()

    assert len(calls) == 1
    _args, kwargs = calls[0]
    assert kwargs.get('reason') == 'manual_override'
    assert kwargs.get('announce') is True


def test_cycle_profile_to_auto_does_not_call_set_active_profile() -> None:
    """Cycling back to 'auto' just re-enables the decider -- no profile_switch
    keyframe fires here, so there is nothing to tag."""
    inst = _bare_controller()
    inst._manual_profile = list(_AUTO_VJ_MODULE._PROFILE_KEYS)[-1]  # last real key
    inst._auto_profile_enabled = False
    inst._profile_auto_reco_decider_enabled = False
    calls: list[tuple[tuple, dict]] = []
    inst._set_active_profile = lambda *a, **kw: calls.append((a, kw))

    result = inst.cycle_profile()

    assert result == 'auto'
    assert calls == []
    assert inst._profile_auto_reco_decider_enabled is True


# ---- cycle_audio_profile() -- Alt+A now includes 'auto' (2026-08-17) -------


class _FakeAudioProfile:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeAudioManager:
    def __init__(self, keys: list[str]) -> None:
        self._keys = keys
        self.set_calls: list[str] = []

    def list_profiles(self) -> list[str]:
        return list(self._keys)

    def set_profile(self, key: str) -> _FakeAudioProfile:
        self.set_calls.append(key)
        return _FakeAudioProfile(key)


def _bare_controller_for_audio_cycle(manual_audio_profile: str = 'auto') -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._manual_audio_profile = manual_audio_profile
    inst._profile_auto_reco_decider_enabled = True
    return inst


def test_cycle_audio_profile_manual_pick_disables_decider_and_sets_profile() -> None:
    inst = _bare_controller_for_audio_cycle('auto')
    mgr = _FakeAudioManager(['house', 'dubstep', 'trance'])

    label = inst.cycle_audio_profile(mgr)

    assert label == 'house'
    assert inst._manual_audio_profile == 'house'
    assert inst._profile_auto_reco_decider_enabled is False
    assert mgr.set_calls == ['house']


def test_cycle_audio_profile_to_auto_reenables_decider_without_calling_set_profile() -> None:
    inst = _bare_controller_for_audio_cycle('trance')  # last key in the list below
    inst._profile_auto_reco_decider_enabled = False
    mgr = _FakeAudioManager(['house', 'dubstep', 'trance'])

    label = inst.cycle_audio_profile(mgr)

    assert label == 'auto'
    assert inst._manual_audio_profile == 'auto'
    assert inst._profile_auto_reco_decider_enabled is True
    assert mgr.set_calls == []


def test_cycle_audio_profile_reverse_wraps_to_last_real_key() -> None:
    inst = _bare_controller_for_audio_cycle('auto')
    mgr = _FakeAudioManager(['house', 'dubstep', 'trance'])

    label = inst.cycle_audio_profile(mgr, reverse=True)

    assert label == 'trance'
    assert inst._manual_audio_profile == 'trance'
    assert inst._profile_auto_reco_decider_enabled is False


def test_cycle_audio_profile_full_cycle_returns_to_auto() -> None:
    inst = _bare_controller_for_audio_cycle('auto')
    mgr = _FakeAudioManager(['house', 'dubstep'])

    seen = [inst.cycle_audio_profile(mgr) for _ in range(3)]

    assert seen == ['house', 'dubstep', 'auto']
    assert inst._profile_auto_reco_decider_enabled is True


# ---- 'tweaker' mood preset (2026-08-17, manual-only) -----------------------


def test_tweaker_preset_exists_in_profile_keys() -> None:
    assert 'tweaker' in _AUTO_VJ_MODULE._PROFILE_KEYS


def test_tweaker_preset_exceeds_raver_on_core_intensity_dials() -> None:
    raver = _AUTO_VJ_MODULE._PROFILE_PRESETS['raver']
    tweaker = _AUTO_VJ_MODULE._PROFILE_PRESETS['tweaker']
    for key in ('reactivity_max', 'speed_max', 'zoom_max', 'mode_speed_slew_per_s'):
        assert tweaker[key] > raver[key], f'{key}: tweaker {tweaker[key]} should exceed raver {raver[key]}'


def test_tweaker_is_never_returned_by_the_auto_bpm_selector() -> None:
    """'tweaker' must only be reachable via cycle_profile()'s manual list --
    _desired_auto_profile() is the sole BPM-driven auto-selector and must
    never hand it out, across the full practical BPM/confidence sweep."""
    inst = object.__new__(AutoVJController)
    inst._auto_profile_chill_max_bpm = 105.0
    inst._auto_profile_raver_min_bpm = 126.0
    inst._auto_profile_min_confidence = 0.45
    inst._auto_profile_raver_min_confidence = 0.34
    inst._auto_profile_raver_bpm_boost = 4.0
    for bpm in range(40, 220, 2):
        for confidence in (0.0, 0.2, 0.34, 0.45, 0.6, 0.8, 1.0):
            result = inst._desired_auto_profile(float(bpm), confidence)
            assert result != 'tweaker'
            assert result in (None, 'chill', 'normie', 'raver')


# ---- _load_recommender_weights() ---------------------------------------------


def test_load_recommender_weights_defaults_when_file_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(_AUTO_VJ_MODULE, '_RECO_WEIGHTS_PATH', tmp_path / 'nope.json')
    weights = _AUTO_VJ_MODULE._load_recommender_weights()
    assert weights == _AUTO_VJ_MODULE._DEFAULT_RECO_WEIGHTS
    assert weights is not _AUTO_VJ_MODULE._DEFAULT_RECO_WEIGHTS   # must be a copy


def test_load_recommender_weights_overrides_known_keys(tmp_path, monkeypatch) -> None:
    path = tmp_path / 'recommender-weights.json'
    path.write_text(json.dumps({'weights': {'tempo_fit': 3.3}}), encoding='utf-8')
    monkeypatch.setattr(_AUTO_VJ_MODULE, '_RECO_WEIGHTS_PATH', path)

    weights = _AUTO_VJ_MODULE._load_recommender_weights()

    assert weights['tempo_fit'] == 3.3
    assert weights['zcr_fit'] == _AUTO_VJ_MODULE._DEFAULT_RECO_WEIGHTS['zcr_fit']


def test_load_recommender_weights_ignores_unknown_keys(tmp_path, monkeypatch) -> None:
    path = tmp_path / 'recommender-weights.json'
    path.write_text(json.dumps({'weights': {'bogus_key': 9.9}}), encoding='utf-8')
    monkeypatch.setattr(_AUTO_VJ_MODULE, '_RECO_WEIGHTS_PATH', path)

    weights = _AUTO_VJ_MODULE._load_recommender_weights()

    assert 'bogus_key' not in weights
    assert weights == _AUTO_VJ_MODULE._DEFAULT_RECO_WEIGHTS


def test_load_recommender_weights_falls_back_on_malformed_json(tmp_path, monkeypatch) -> None:
    path = tmp_path / 'recommender-weights.json'
    path.write_text('{not valid json', encoding='utf-8')
    monkeypatch.setattr(_AUTO_VJ_MODULE, '_RECO_WEIGHTS_PATH', path)

    weights = _AUTO_VJ_MODULE._load_recommender_weights()

    assert weights == _AUTO_VJ_MODULE._DEFAULT_RECO_WEIGHTS


def test_load_recommender_weights_bare_mapping_without_wrapper(tmp_path, monkeypatch) -> None:
    path = tmp_path / 'recommender-weights.json'
    path.write_text(json.dumps({'tempo_fit': 1.5}), encoding='utf-8')
    monkeypatch.setattr(_AUTO_VJ_MODULE, '_RECO_WEIGHTS_PATH', path)

    weights = _AUTO_VJ_MODULE._load_recommender_weights()

    assert weights['tempo_fit'] == 1.5
