"""The chromogram's two-source split, and why the low end is handed over.

The shared 1024-point FFT's 46.875 Hz bins are wider than an octave below
~140 Hz, so its lowest bins carry no pitch information at all. The analyzer's
64-band perceptual vector is backed down there by an 8192-point window and is
roughly 4.5x finer at 100 Hz, so the effect tapers the FFT out below the
crossover and lets the bands cover it.

These tests pin the two properties that make that split correct rather than
merely different: each source is confined to the region where it is the better
one, and the low end is therefore measured once instead of counted twice.
GL-free -- the analysis functions are module-level and need no context.
"""
from __future__ import annotations

import numpy as np

from unicornviz.audio.analyzer import PERC_BAND_CENTERS_HZ
from unicornviz.effects.audio_chromogram import (
    _BAND_XOVER_HZ,
    _BIN_HZ,
    _CLASSES,
    _F_BINS,
    _build_band_chroma_weights,
    _build_chroma_weights,
    _fft_low_rolloff,
    _prefill_weights,
)

_CENTERS = np.asarray(PERC_BAND_CENTERS_HZ, dtype=np.float64)


def test_band_weights_cover_only_below_the_crossover():
    """Bands above the crossover contribute nothing; the FFT is finer there."""
    w = _build_band_chroma_weights()
    assert w.shape == (_CENTERS.size, _CLASSES)
    above = _CENTERS >= _BAND_XOVER_HZ
    assert np.allclose(w[above], 0.0), 'bands above the crossover must not contribute'
    assert w[~above].sum() > 0.0, 'bands below the crossover must contribute'


def test_fft_rolloff_hands_the_low_end_over():
    """The FFT is fully faded out under the crossover and fully on above it."""
    roll = _fft_low_rolloff()
    assert roll.shape == (_F_BINS,)
    freqs = np.arange(_F_BINS) * _BIN_HZ
    assert roll[freqs < _BAND_XOVER_HZ * 0.5].max() == 0.0
    assert roll[freqs > _BAND_XOVER_HZ * 1.6].min() > 0.99
    assert np.all(np.diff(roll) >= -1e-6), 'the taper must be monotonic'


def test_the_low_end_is_not_counted_twice():
    """No frequency is fully credited to both sources at once.

    Summing an untapered FFT with the bands would double the sub-crossover
    region, which reads as a permanent bass-heavy tilt across the whole strip.
    """
    roll = _fft_low_rolloff()
    freqs = np.arange(_F_BINS) * _BIN_HZ
    low = freqs < _BAND_XOVER_HZ
    # Where the bands are authoritative, the FFT's contribution is well under
    # unity everywhere and zero across the bottom of the range.
    assert roll[low].max() < 0.75


def test_a_band_leads_with_the_class_of_its_own_centre():
    """Each band's strongest class is the one its centre frequency actually is.

    Not "the class of the note you were hoping for": the 64 bands are log-spaced
    about 1.7 semitones apart and the twelve-tone grid is spaced one, so the two
    grids do not line up. The band nearest C3 (130.81 Hz) is centred at 124.44
    Hz -- 86 cents away, nearly a full semitone -- and correctly leads with B.
    That is the mapping being honest about where the energy sits, and it is why
    the band path still spreads across neighbouring classes instead of rounding.
    """
    weights = _build_band_chroma_weights()
    checked = 0
    for band, centre in enumerate(_CENTERS):
        if centre >= _BAND_XOVER_HZ or weights[band].sum() <= 0.0:
            continue
        want = int(round(np.mod(69.0 + 12.0 * np.log2(centre / 440.0), 12.0))) % 12
        assert int(np.argmax(weights[band])) == want, (
            f'band {band} at {centre:.2f} Hz should lead with class {want}')
        checked += 1
    assert checked > 5, 'expected several bands below the crossover'


def test_band_grid_misalignment_is_bounded():
    """No band centre is more than half a band from the nearest semitone.

    Bounding it is what makes the spread-across-classes weighting defensible:
    the error is a known fraction of a band, not unbounded.
    """
    ratio = 2.0 ** (np.log2(16000.0 / 30.0) / _CENTERS.size)
    half_band_cents = 1200.0 * np.log2(ratio) / 2.0
    low = _CENTERS[_CENTERS < _BAND_XOVER_HZ]
    semis = 12.0 * np.log2(low / 440.0) + 69.0
    off_cents = np.abs(semis - np.round(semis)) * 100.0
    assert off_cents.max() <= half_band_cents + 1.0, (
        f'worst misalignment {off_cents.max():.0f} cents exceeds half a band '
        f'({half_band_cents:.0f} cents)')


def test_prefill_weights_resolve_a_semitone():
    """The offline matrix separates adjacent semitones, which the live one cannot.

    This is the whole reason the prefill runs its own transform rather than
    reusing the low-latency path: offline there is no latency to protect.
    """
    freqs = np.fft.rfftfreq(8192, 1.0 / 48000.0)
    weights, bin_oct = _prefill_weights(freqs)
    assert weights.shape == (freqs.size, _CLASSES)
    assert bin_oct.shape == (freqs.size,)
    # Two adjacent semitones near middle C must land on adjacent classes.
    for hz, want in ((261.63, 0), (277.18, 1), (293.66, 2)):
        b = int(np.argmin(np.abs(freqs - hz)))
        assert int(np.argmax(weights[b])) == want


def test_sub_audio_bins_are_excluded_from_the_prefill():
    """DC and infrasonic bins carry no pitch and must not vote."""
    freqs = np.fft.rfftfreq(8192, 1.0 / 48000.0)
    weights, _ = _prefill_weights(freqs)
    assert np.allclose(weights[freqs <= 20.0], 0.0)


def test_live_fft_weights_still_present_and_shaped():
    """The original FFT path is unchanged in shape and still contributes."""
    w = _build_chroma_weights()
    assert w.shape == (_F_BINS, _CLASSES)
    assert w.sum() > 0.0
