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
    assert weights['lock_rate'] == _AUTO_VJ_MODULE._DEFAULT_RECO_WEIGHTS['lock_rate']


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
