"""Tests: onset detection under duplicate-block feeding.

Validates that:
- Processing the same PCM block repeatedly does not fire additional onsets
  after the initial one (the cooldown refractory enforces this).
- The MAD-based threshold stays finite and positive even when the same
  flux value is fed identically many times (degenerate input).
- A genuine new transient after silence does register as an onset.
"""
from __future__ import annotations

import numpy as np
import pytest

from unicornviz.audio.analyzer import Analyzer, _BEAT_ABS_FLOOR, _ONSET_STRENGTH_CAP


_BANDS = 512
_RATE = 48000


def test_analyzer_defaults_to_house_profile_when_none_given() -> None:
    """2026-08-06: matches AudioManager's own default -- 'house', reverted
    from a brief 2026-08-05 'generic' default (see AudioManager.__init__'s
    field comment for why)."""
    analyzer = Analyzer(fft_bands=_BANDS)
    assert analyzer._profile.name == 'House'


def _make_sine_block(freq: float = 440.0, n: int = 1024, amp: float = 0.5) -> np.ndarray:
    t = np.arange(n, dtype=np.float32) / _RATE
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def _make_kick_block(n: int = 1024, amp: float = 0.9) -> np.ndarray:
    """Strong broadband transient to reliably trigger an onset.

    Uses high-amplitude white noise filling the whole block so it passes
    the silence gate (RMS > silence_rms_floor) and produces significant flux
    after a silence warmup where RMS was zero.
    """
    rng = np.random.default_rng(42)
    return (amp * rng.standard_normal(n)).clip(-1.0, 1.0).astype(np.float32)


def test_duplicate_block_does_not_refireOnset() -> None:
    """Feeding the same strong block twice must not produce two onsets."""
    a = Analyzer(fft_bands=_BANDS)
    kick = _make_kick_block()

    # Warm up the envelope with silence so kick stands out.
    silence = np.zeros(1024, dtype=np.float32)
    t = 0.0
    step = 1024 / _RATE
    for _ in range(60):  # ~0.6 s of silence fills the envelope ring
        a.process(silence, t=t)
        a.drain_onsets()
        t += step

    # Process the kick once — should produce an onset.
    a.process(kick, t=t)
    onsets_first = a.drain_onsets()
    t += step

    # Process the identical block again immediately — refractory must suppress.
    a.process(kick, t=t)
    onsets_second = a.drain_onsets()

    assert len(onsets_first) >= 1, 'Expected at least one onset on the initial transient'
    assert len(onsets_second) == 0, 'Refractory must suppress a duplicate-block onset'


def test_repeated_identical_blocks_threshold_stays_finite() -> None:
    """MAD threshold must not degenerate to zero or NaN under constant input."""
    a = Analyzer(fft_bands=_BANDS)
    block = _make_sine_block(amp=0.3)
    t = 0.0
    step = 1024 / _RATE
    for _ in range(120):
        a.process(block, t=t)
        a.drain_onsets()
        t += step

    threshold, mad = a._onset_threshold()
    assert np.isfinite(threshold), f'Threshold became non-finite: {threshold}'
    assert threshold > 0.0, f'Threshold collapsed to zero: {threshold}'
    assert np.isfinite(mad), f'MAD became non-finite: {mad}'


def test_genuine_transient_after_warmup_produces_onset() -> None:
    """A strong transient after an established steady-state must register."""
    a = Analyzer(fft_bands=_BANDS)
    silence = np.zeros(1024, dtype=np.float32)
    t = 0.0
    step = 1024 / _RATE
    # Warm up with silence.
    for _ in range(60):
        a.process(silence, t=t)
        a.drain_onsets()
        t += step
    # Fire kick.
    a.process(_make_kick_block(), t=t)
    onsets = a.drain_onsets()
    assert len(onsets) >= 1, 'Genuine transient must produce at least one onset'
    assert onsets[0].strength > 0.0, 'Onset strength must be positive'
    # 2026-08-17: this exact scenario (real silence -> real kick) is the
    # pathological case a live session's onset_strength_max_raw logging
    # caught -- strength hit 1,171,176,147 before the mad-floor fix + cap
    # (see _BEAT_ABS_FLOOR/_ONSET_STRENGTH_CAP's own comments). Confirmed
    # directly: this test's own kick block hits the cap exactly (50.0)
    # under the fix, so the upper-bound assertion below is not
    # theoretical -- it's the live regression case.
    assert onsets[0].strength <= _ONSET_STRENGTH_CAP


def test_silence_then_kick_mad_stays_at_or_above_the_abs_floor() -> None:
    """After all-zero (degenerate) silence, mad must floor at _BEAT_ABS_
    FLOOR, not collapse toward the old 1e-6 literal-division-by-zero
    guard -- the direct cause of the runaway-strength bug."""
    a = Analyzer(fft_bands=_BANDS)
    silence = np.zeros(1024, dtype=np.float32)
    t = 0.0
    step = 1024 / _RATE
    for _ in range(60):
        a.process(silence, t=t)
        a.drain_onsets()
        t += step
    _threshold, mad = a._onset_threshold()
    assert mad >= _BEAT_ABS_FLOOR


def test_onset_strength_never_exceeds_the_cap_across_many_kicks() -> None:
    """Defense-in-depth: even several back-to-back real transients never
    produce a strength above _ONSET_STRENGTH_CAP, regardless of how large
    the underlying flux spike is."""
    a = Analyzer(fft_bands=_BANDS)
    silence = np.zeros(1024, dtype=np.float32)
    t = 0.0
    step = 1024 / _RATE
    for _ in range(60):
        a.process(silence, t=t)
        a.drain_onsets()
        t += step
    all_onsets = []
    for seed_offset in range(5):
        rng = np.random.default_rng(100 + seed_offset)
        kick = (0.95 * rng.standard_normal(1024)).clip(-1.0, 1.0).astype(np.float32)
        a.process(kick, t=t)
        all_onsets.extend(a.drain_onsets())
        # Long gap so the refractory doesn't suppress the next kick.
        t += 2.0
        a.process(silence, t=t)
        a.drain_onsets()
    assert all_onsets, 'Expected at least one onset across the repeated-kick sweep'
    for ev in all_onsets:
        assert ev.strength <= _ONSET_STRENGTH_CAP


def _make_tone_block(hz: float, n: int = 1024, amp: float = 0.9, rate: int = _RATE) -> np.ndarray:
    """Pure sine burst concentrated at `hz`, for band_weight discrimination."""
    t = np.arange(n, dtype=np.float32) / rate
    return (amp * np.sin(2.0 * np.pi * hz * t)).astype(np.float32)


def _first_onset_after_warmup(hz: float):
    a = Analyzer(fft_bands=_BANDS)
    silence = np.zeros(1024, dtype=np.float32)
    t = 0.0
    step = 1024 / _RATE
    for _ in range(60):
        a.process(silence, t=t)
        a.drain_onsets()
        t += step
    a.process(_make_tone_block(hz), t=t)
    onsets = a.drain_onsets()
    assert len(onsets) >= 1, f'{hz} Hz tone must produce at least one onset'
    return onsets[0]


def test_onset_band_weight_is_high_for_a_bass_transient() -> None:
    """2026-08-14: band_weight feeds BeatTracker's strength/band-weighted
    phase coherence -- a kick-region transient (well inside _BASS_HZ,
    40-180 Hz) should read as strongly bass-attributed."""
    onset = _first_onset_after_warmup(80.0)

    assert onset.band_weight > 0.7, f'expected a bass-heavy onset, got band_weight={onset.band_weight}'


def test_onset_band_weight_is_low_for_a_treble_transient() -> None:
    """A treble-region transient (well inside _TREBLE_HZ, 3200-12000 Hz,
    e.g. a hi-hat) should read as weakly bass-attributed -- this is the
    signal a wrongly-timed hi-hat shouldn't be allowed to drag phase
    confidence down as hard as a wrongly-timed kick would."""
    onset = _first_onset_after_warmup(8000.0)

    assert onset.band_weight < 0.3, f'expected a treble-heavy onset, got band_weight={onset.band_weight}'


def test_onset_band_weight_defaults_to_1_when_unset() -> None:
    from unicornviz.audio.analyzer import OnsetEvent
    ev = OnsetEvent(t=1.0, strength=1.5)

    assert ev.band_weight == 1.0
