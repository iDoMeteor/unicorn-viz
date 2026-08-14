"""Regression tests: Analyzer.process() assigning data.bpm.

2026-08-09: set_expected_bpm(bpm, confidence) -- the BeatTracker's feedback
hook into the Analyzer -- derived self._refractory_s from its bpm argument
but never stored the value itself, and process() never assigned data.bpm at
all. Every effect reading audio.bpm silently saw AudioData's constructor
default (120.0) forever, regardless of the real track tempo, because Auto
VJ's own beat tracker reaches its consumers by a completely separate route
and never reads data.bpm back out -- nothing about the app looked broken.
"""

from __future__ import annotations

import numpy as np
import pytest

from unicornviz.audio.analyzer import Analyzer


def test_data_bpm_defaults_to_120_before_any_feedback() -> None:
    analyzer = Analyzer()
    data = analyzer.process(None, t=0.0)
    assert data.bpm == pytest.approx(120.0)


def test_data_bpm_reflects_confident_expected_bpm_feedback() -> None:
    analyzer = Analyzer()
    analyzer.set_expected_bpm(128.0, confidence=0.9)

    data = analyzer.process(None, t=0.0)

    assert data.bpm == pytest.approx(128.0)


def test_data_bpm_ignores_low_confidence_feedback() -> None:
    analyzer = Analyzer()
    analyzer.set_expected_bpm(128.0, confidence=0.9)
    analyzer.set_expected_bpm(200.0, confidence=0.1)  # should not overwrite

    data = analyzer.process(None, t=0.0)

    assert data.bpm == pytest.approx(128.0)


def test_data_bpm_stays_sticky_across_frames_once_set() -> None:
    """A momentary confidence dip shouldn't blank data.bpm back to the
    default for every effect reading it that frame."""
    analyzer = Analyzer()
    analyzer.set_expected_bpm(140.0, confidence=0.9)
    analyzer.process(None, t=0.0)

    analyzer.set_expected_bpm(0.0, confidence=0.0)
    data = analyzer.process(None, t=1.0)

    assert data.bpm == pytest.approx(140.0)


def test_data_bpm_updates_on_a_pre_allocated_out_buffer() -> None:
    """Matches real call sites: process(..., out=reused_buffer)."""
    from unicornviz.effects.base import AudioData

    analyzer = Analyzer()
    analyzer.set_expected_bpm(126.0, confidence=0.9)
    buf = AudioData()

    result = analyzer.process(None, t=0.0, out=buf)

    assert result is buf
    assert buf.bpm == pytest.approx(126.0)


# ---------------------------------------------------------------------------
# Analyzer.refractory_s (2026-08-14, round three, audit cross-check item
# 12.8 #1) -- public accessor for the BPM-fed onset refractory, added to
# test a candidate root-cause mechanism (docs/audits/2026-08-13-bpm-tempo-
# detection-audit.md finding T4): a confident-but-wrong BPM can suppress
# every other true beat at the source, entrenching the wrong lock.
# ---------------------------------------------------------------------------

def test_refractory_s_is_zero_before_any_confident_feedback() -> None:
    analyzer = Analyzer()
    assert analyzer.refractory_s == 0.0


def test_refractory_s_reflects_confident_expected_bpm() -> None:
    """0.70 * 60/bpm, clamped [0.18, 0.50] -- see set_expected_bpm()'s
    own docstring. 128 BPM: 0.70*60/128 = 0.328125."""
    analyzer = Analyzer()
    analyzer.set_expected_bpm(128.0, confidence=0.9)
    assert analyzer.refractory_s == pytest.approx(0.328125)


def test_refractory_s_clamps_low_at_high_bpm() -> None:
    analyzer = Analyzer()
    analyzer.set_expected_bpm(300.0, confidence=0.9)
    assert analyzer.refractory_s == pytest.approx(0.18)


def test_refractory_s_clamps_high_at_low_bpm() -> None:
    """A low-BPM lock (e.g. the 75.95 BPM 17:56 session incident) clamps
    to the 0.50s ceiling -- longer than the true beat period of the
    120-150 BPM track it was actually half-locked onto, which is exactly
    the mechanism T4/12.2 flags."""
    analyzer = Analyzer()
    analyzer.set_expected_bpm(75.95, confidence=0.9)
    assert analyzer.refractory_s == pytest.approx(0.50)


def test_refractory_s_returns_to_zero_on_low_confidence() -> None:
    analyzer = Analyzer()
    analyzer.set_expected_bpm(128.0, confidence=0.9)
    analyzer.set_expected_bpm(128.0, confidence=0.1)
    assert analyzer.refractory_s == 0.0
