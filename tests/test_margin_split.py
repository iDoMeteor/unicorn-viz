"""Regression tests for the prefilter/matcher margin split (2026-09-01).

The 2026-08-31 experiment's #1 structural recommendation: one shared
margin provably could not serve the HIGH-regime prefilter and the
matcher LOW half at once. The split was behavior-preserving at its own
defaults (both 0.10) until the prefilter half's own unit changed.

2026-09-10 (zone-map batch, recommender rc.39): the prefilter half
retired its relative-fraction margin for a hard, flat BPM allowance
(owner: "10% is too much... let's make the allowance a hard +/-4bpm") --
see profile_reco_bpm_prefilter_margin_bpm's own comment in auto_vj.py.
The two margins are no longer the same unit (BPM vs. a 0-1 fraction), so
they're no longer expected to share a numeric default -- each is checked
against its own current value instead.
"""
from __future__ import annotations

import re
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01'
        / 'auto_vj.py').read_text(encoding='utf-8')


def test_prefilter_margin_is_a_hard_bpm_allowance() -> None:
    pre = re.search(r"'profile_reco_bpm_prefilter_margin_bpm', (\d+\.\d+)\)", _SRC)
    assert pre, 'the renamed, hard-BPM-allowance config read must exist'
    assert pre.group(1) == '4.0'
    # the old, fractional key must be fully retired from the live read site,
    # not just shadowed
    assert "'profile_reco_bpm_prefilter_margin'," not in _SRC


def test_matcher_margin_default_unchanged_by_the_prefilter_side_s_unit_change() -> None:
    mat = re.search(r"'genre_matcher_range_margin', (0\.\d+)\)", _SRC)
    assert mat, 'the matcher-side margin config read must exist'
    assert mat.group(1) == '0.10'


def test_matcher_site_uses_its_own_margin() -> None:
    assert "_genre_matcher_range_margin', 0.10" in _SRC
    # the matcher block must not read the prefilter margin any more
    matcher_zone = _SRC[_SRC.index('matcher-side margin'):][:1200]
    assert '_profile_reco_bpm_prefilter_margin' not in matcher_zone


def test_engagement_counter_exists() -> None:
    assert '_matcher_range_margin_bind_count' in _SRC
