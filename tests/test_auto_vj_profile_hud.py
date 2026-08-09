"""Regression tests for the current-profile HUD score
(AutoVJController.current_profile_score_hud), added 2026-08-05 alongside
the existing profile_recommendation_hud so an operator can see both sides
of the genre-profile comparison at a glance, not just the alternate.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_SPEC = importlib.util.spec_from_file_location('test_auto_vj_profile_hud_module', _AUTO_VJ_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
AutoVJController = _MOD.AutoVJController


def _bare_controller(**overrides):
    inst = object.__new__(AutoVJController)
    inst._profile_auto_reco_enabled = True
    inst._current_profile_scored = False
    inst._current_profile_score = 0.0
    inst._recommended_profile_name = ''
    inst._recommended_profile_range = ''
    inst._recommended_profile_score = 0.0
    inst._recommended_profile_confirmed = False
    for k, v in overrides.items():
        setattr(inst, k, v)
    return inst


def test_current_profile_score_hud_empty_when_reco_disabled() -> None:
    inst = _bare_controller(_profile_auto_reco_enabled=False, _current_profile_scored=True, _current_profile_score=1.5)
    assert inst.current_profile_score_hud == ''


def test_current_profile_score_hud_empty_before_first_eval_cycle() -> None:
    inst = _bare_controller(_current_profile_scored=False)
    assert inst.current_profile_score_hud == ''


def test_current_profile_score_hud_formats_the_score() -> None:
    inst = _bare_controller(_current_profile_scored=True, _current_profile_score=2.345)
    assert inst.current_profile_score_hud == '2.35'


def test_current_profile_score_hud_handles_negative_scores() -> None:
    inst = _bare_controller(_current_profile_scored=True, _current_profile_score=-1.2)
    assert inst.current_profile_score_hud == '-1.20'


def test_current_profile_score_hud_does_not_clamp_extreme_values() -> None:
    """2026-08-09: the +-9.99 display clamp was removed -- a clamped
    readout is indistinguishable from a real score that happens to land
    near the old boundary, which is exactly the information an operator
    watching the HUD live needs (e.g. a term blowing out to -70 vs. a
    real, close -9). Owner: "clamping my live metric display values is
    absolutely retarded... let's get rid of that.\""""
    inst = _bare_controller(_current_profile_scored=True, _current_profile_score=1234.5)
    assert inst.current_profile_score_hud == '1234.50'

    inst_negative = _bare_controller(_current_profile_scored=True, _current_profile_score=-74.359)
    assert inst_negative.current_profile_score_hud == '-74.36'


def test_profile_recommendation_hud_does_not_clamp_extreme_values() -> None:
    """Sibling of current_profile_score_hud above -- same 2026-08-09 fix,
    same rationale, same live incident (a session where centroid_fit alone
    drove several candidates' scores past -70)."""
    inst = _bare_controller(
        _recommended_profile_name='dubstep', _recommended_profile_range='138-142',
        _recommended_profile_score=-74.359, _recommended_profile_confirmed=False,
    )
    assert inst.profile_recommendation_hud == '~dubstep (138-142) -74.36'
