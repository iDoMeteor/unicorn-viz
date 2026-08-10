"""Regression tests for App._fill_audio_scratch().

2026-08-09: _fill_audio_scratch() hand-wrote its own copy of AudioData's
field list -- independently of AudioManager._copy_audio_into()'s list,
which had already been bitten once by the same disease (vocal_hnr/vocal_fmr
silently dropped, see docs/adr/vj-system.md, auto-vj-01, "Vocal-Presence
Core Bug"). This second list was found missing the exact same two fields
the same day. Both now delegate to the single shared
unicornviz.effects.base.copy_audio_data(); these tests enumerate every
AudioData slot dynamically so a future field added without updating that
one shared list fails loudly instead of silently reading a stale default.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from unicornviz.config import Config
from unicornviz.app import App
from unicornviz.effects.base import AudioData


def _default_cfg() -> Config:
    return Config(Path('tests') / '_missing_config_for_tests.toml')


def test_fill_audio_scratch_copies_every_audiodata_slot_at_unity_scale() -> None:
    app = App(_default_cfg())
    source = AudioData()
    target = AudioData()
    for i, name in enumerate(AudioData.__slots__):
        current = getattr(source, name)
        if hasattr(current, '__setitem__'):
            current[:] = np.arange(len(current), dtype=current.dtype) + i + 1
        else:
            setattr(source, name, float(i) + 1.0)

    app._fill_audio_scratch(target, source, 1.0)

    for name in AudioData.__slots__:
        source_val = getattr(source, name)
        target_val = getattr(target, name)
        if hasattr(source_val, '__len__'):
            assert list(target_val) == list(source_val), f'{name} not copied'
        else:
            assert target_val == source_val, f'{name} not copied'


def test_fill_audio_scratch_copies_vocal_hnr_and_fmr() -> None:
    """Narrower, explicit regression for the specific fields that were
    dropped -- kept alongside the exhaustive test above so this exact
    symptom has a test that names it directly."""
    app = App(_default_cfg())
    source = AudioData()
    target = AudioData()
    source.vocal_hnr = 0.6899
    source.vocal_fmr = 0.6804

    app._fill_audio_scratch(target, source, 1.0)

    assert target.vocal_hnr == pytest.approx(0.6899)
    assert target.vocal_fmr == pytest.approx(0.6804)


def test_fill_audio_scratch_scales_only_level_fields() -> None:
    """Reactivity scale must affect bass/mid/treble/fft only -- everything
    else (including vocal_hnr/vocal_fmr) is reactivity-invariant by design."""
    app = App(_default_cfg())
    source = AudioData()
    target = AudioData()
    source.bass = 0.3
    source.mid = 0.3
    source.treble = 0.3
    source.vocal_hnr = 0.5
    source.bass_n = 0.5

    app._fill_audio_scratch(target, source, 2.0)

    assert target.bass == pytest.approx(0.6)
    assert target.mid == pytest.approx(0.6)
    assert target.treble == pytest.approx(0.6)
    assert target.vocal_hnr == pytest.approx(0.5)  # unscaled
    assert target.bass_n == pytest.approx(0.5)      # unscaled


def test_fill_audio_scratch_clamps_scaled_level_fields_to_one() -> None:
    app = App(_default_cfg())
    source = AudioData()
    target = AudioData()
    source.bass = 0.9

    app._fill_audio_scratch(target, source, 3.0)

    assert target.bass == pytest.approx(1.0)
