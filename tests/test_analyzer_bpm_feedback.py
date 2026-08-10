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
