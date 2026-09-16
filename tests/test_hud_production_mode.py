"""[auto_vj] hud_production_mode — regression tests.

A single config override for a live show: forces every "detector
internals" HUD readout off (the Auto VJ status bar's BPM confidence, the
active profile's recommender score, and the REC PROF line) regardless of
the individual [overlays] hud_show_detector_bpm/hud_show_profile_score/
hud_show_reco_profile settings, without changing them -- see
_resolve_hud_detector_visibility() in unicornviz/app.py.
"""
from __future__ import annotations

from unicornviz.app import _resolve_hud_detector_visibility


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
