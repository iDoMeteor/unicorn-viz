"""Regression tests for the detector-internals HUD toggles (2026-09-01).

Owner decision: the detected-BPM readout in the Auto VJ status bar, the
active profile's recommender score, and the REC PROF line all default to
HIDDEN for end users, with `[overlays] hud_show_*` config keys to opt
back in (the owner's config turns all three on). Source-level tests (no
GL context) pin the defaults and the wiring so a refactor can't silently
re-expose the internals or flip a default.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_OVERLAYS = (_REPO / 'unicornviz' / 'overlays.py').read_text(encoding='utf-8')
_APP = (_REPO / 'unicornviz' / 'app.py').read_text(encoding='utf-8')

_FLAGS = ('hud_show_detector_bpm', 'hud_show_profile_score', 'hud_show_reco_profile')


def test_constructor_defaults_are_hidden() -> None:
    for flag in _FLAGS:
        assert re.search(rf'{flag}: bool = False', _OVERLAYS), (
            f'{flag} must default to False (hidden) in Overlays.__init__')


def test_app_wires_flags_from_overlays_config() -> None:
    for flag in _FLAGS:
        assert re.search(
            rf"cfg\.get\('overlays', '{flag}', default=False\)", _APP), (
            f'app.py must read {flag} from [overlays] with default=False')


def test_hud_lines_are_gated() -> None:
    assert '_hud_show_profile_score else' in _OVERLAYS
    assert '_hud_show_reco_profile else' in _OVERLAYS
    assert 'if self._hud_show_detector_bpm:' in _OVERLAYS
    # The hidden branch of the status bar keeps ACTION IN but drops BPM.
    assert "line2 = f'ACTION IN: {action_in:<4}'" in _OVERLAYS
