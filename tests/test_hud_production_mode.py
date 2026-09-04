"""[auto_vj] hud_production_mode — regression tests.

A single config override for a live show: forces every "detector
internals" HUD readout off (the Auto VJ status bar's BPM confidence, the
active profile's recommender score, and the REC PROF line) regardless of
the individual [overlays] hud_show_detector_bpm/hud_show_profile_score/
hud_show_reco_profile settings, without changing them -- see
_resolve_hud_detector_visibility() in unicornviz/app.py.
"""
from __future__ import annotations

from pathlib import Path

from unicornviz.app import App, _resolve_hud_detector_visibility
from unicornviz.config_profiles import ConfigProfileStore


class _Cfg:
    """Minimal cfg.get(section, key, default=...) stub."""

    def __init__(self, values: dict[tuple[str, str], object]) -> None:
        self._values = values

    def get(self, *keys, default=None):
        return self._values.get(tuple(keys), default)


def test_defaults_are_all_hidden() -> None:
    assert _resolve_hud_detector_visibility(_Cfg({})) == (False, False, False)


def test_individual_flags_pass_through_when_production_mode_is_off() -> None:
    cfg = _Cfg({
        ('overlays', 'hud_show_detector_bpm'): True,
        ('overlays', 'hud_show_profile_score'): True,
        ('overlays', 'hud_show_reco_profile'): True,
    })
    assert _resolve_hud_detector_visibility(cfg) == (True, True, True)


def test_individual_flags_can_differ() -> None:
    cfg = _Cfg({
        ('overlays', 'hud_show_detector_bpm'): True,
        ('overlays', 'hud_show_reco_profile'): True,
        # hud_show_profile_score left at its default (False).
    })
    assert _resolve_hud_detector_visibility(cfg) == (True, False, True)


def test_production_mode_forces_everything_off() -> None:
    # This is the whole point: the owner's live config has all three
    # hud_show_* keys set to true, and production mode must override that.
    cfg = _Cfg({
        ('auto_vj', 'hud_production_mode'): True,
        ('overlays', 'hud_show_detector_bpm'): True,
        ('overlays', 'hud_show_profile_score'): True,
        ('overlays', 'hud_show_reco_profile'): True,
    })
    assert _resolve_hud_detector_visibility(cfg) == (False, False, False)


def test_production_mode_off_restores_individual_settings() -> None:
    # Toggling production mode back off must not have mutated anything --
    # the underlying three keys are read fresh every call.
    values = {
        ('auto_vj', 'hud_production_mode'): True,
        ('overlays', 'hud_show_detector_bpm'): True,
        ('overlays', 'hud_show_profile_score'): True,
        ('overlays', 'hud_show_reco_profile'): True,
    }
    cfg = _Cfg(values)
    assert _resolve_hud_detector_visibility(cfg) == (False, False, False)
    values[('auto_vj', 'hud_production_mode')] = False
    assert _resolve_hud_detector_visibility(cfg) == (True, True, True)


def test_production_mode_default_is_off() -> None:
    cfg = _Cfg({
        ('overlays', 'hud_show_detector_bpm'): True,
        ('overlays', 'hud_show_profile_score'): True,
        ('overlays', 'hud_show_reco_profile'): True,
    })
    # No [auto_vj] hud_production_mode key at all -> defaults False -> the
    # three individually-configured values pass through untouched.
    assert _resolve_hud_detector_visibility(cfg) == (True, True, True)


# --------------------------------------------------------------------------- #
# Second surface: the Configuration Editor's "Auto VJ" info tab (C key).
#
# Missed by the first pass: config_editor_info_rows('Auto VJ') showed BPM,
# BPM confidence, Profile score, and Profile rec unconditionally -- an
# entirely separate code path from the main H-toggled HUD's bottom pane,
# never gated by hud_production_mode at all.
# --------------------------------------------------------------------------- #

class _AutoVJStub:
    hud_mood_label = 'HYPE'
    hud_scene_label = 'Tunnel'
    hud_bpm_label = '128'
    hud_bpm_confidence_label = '0.82'
    hud_action_in_label = '2 bars'
    current_profile_score_hud = '0.71'
    profile_recommendation_hud = 'raver'


def _app(tmp_path: Path, production_mode: bool) -> App:
    app = object.__new__(App)
    app.cfg = _Cfg({('auto_vj', 'hud_production_mode'): production_mode})
    app._config_profile_store = ConfigProfileStore(tmp_path / 'cp.json')
    app._auto_vj = _AutoVJStub()
    return app


def test_auto_vj_tab_shows_detector_internals_by_default(tmp_path: Path) -> None:
    rows = _app(tmp_path, production_mode=False).config_editor_info_rows('Auto VJ')
    names = {r['name'] for r in rows}
    assert {'BPM', 'BPM confidence', 'Profile score', 'Profile rec'} <= names
    # Mood/Scene/Action in are never gated -- only the detector-internal rows.
    assert {'Mood', 'Scene', 'Action in'} <= names


def test_production_mode_hides_bpm_confidence_and_profile_rows(tmp_path: Path) -> None:
    rows = _app(tmp_path, production_mode=True).config_editor_info_rows('Auto VJ')
    names = {r['name'] for r in rows}
    assert 'BPM' not in names
    assert 'BPM confidence' not in names
    assert 'Profile score' not in names
    assert 'Profile rec' not in names
    # Everything else stays -- production mode is scoped to detector internals.
    assert {'Mood', 'Scene', 'Action in'} <= names
