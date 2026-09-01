"""Regression tests for the prefilter/matcher margin split (2026-09-01).

The 2026-08-31 experiment's #1 structural recommendation: one shared
margin provably could not serve the HIGH-regime prefilter and the
matcher LOW half at once. The split must be behavior-preserving at
defaults (both 0.10) and the matcher site must read its own constant.
"""
from __future__ import annotations

import re
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01'
        / 'auto_vj.py').read_text(encoding='utf-8')


def test_split_defaults_are_equal_and_behavior_preserving() -> None:
    pre = re.search(r"'profile_reco_bpm_prefilter_margin', (0\.\d+)\)", _SRC)
    mat = re.search(r"'genre_matcher_range_margin', (0\.\d+)\)", _SRC)
    assert pre and mat, 'both margin config reads must exist'
    assert pre.group(1) == mat.group(1) == '0.10', (
        'split defaults must stay equal (behavior-preserving) until a '
        'probe verdict deliberately moves the matcher side')


def test_matcher_site_uses_its_own_margin() -> None:
    assert "_genre_matcher_range_margin', 0.10" in _SRC
    # the matcher block must not read the prefilter margin any more
    matcher_zone = _SRC[_SRC.index('matcher-side margin'):][:1200]
    assert '_profile_reco_bpm_prefilter_margin' not in matcher_zone


def test_engagement_counter_exists() -> None:
    assert '_matcher_range_margin_bind_count' in _SRC
