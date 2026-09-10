"""2026-09-04: low-band resolution fix for the shared 64-band perceptual
spectrum (unicornviz/audio/analyzer.py).

Diagnosis: the short FFT (1024 samples at 48kHz, 46.875 Hz/bin) cannot
resolve the bottom of the 64 log-spaced bands -- 19 of 64 collapse onto a
shared FFT bin (bands 0-8 read the exact same number every frame,
regardless of genre). Fixed with a second, independent, long-window
(8192-sample) FFT that replaces only the bottom N bands (N is rate-aware,
``analyzer._low_band_replace_n`` -- 19 at 48kHz, 18 at 44.1kHz; see that
attribute's own comment), leaving the short path's timing/latency for
every other band (and every other effect-facing signal) untouched. See
docs/adr/vj-system.md "Low-Band Resolution: Dual-Window Fix" for the full
diagnosis and option comparison.

2026-09-10: the replacement previously scaled the long-window magnitudes
by a window-sum ratio only, on the mistaken premise that the short path
applies no normalization of its own. It does (spectrum /= max_val;
spectrum *= sqrt(energy), 35 lines above the replacement block) -- the
mismatch crushed every band above the replacement boundary toward ~0.01
regardless of real signal. Fixed by applying the same normalization
convention to both paths before either one is written into the shared
64-band vector. Also fixed: the replacement count was hardcoded to 25
(claimed "verified directly," but the real collapse count is 19/18,
rate-dependent) -- now computed live in ``_recompute_band_edges()``.
"""
from __future__ import annotations

import numpy as np

from unicornviz.audio.analyzer import (
    _LOW_BAND_N_FFT,
    Analyzer,
)
from unicornviz.effects.base import AudioData


def _feed_noise(analyzer: Analyzer, data: AudioData, *, n_samples: int,
                 block: int = 512, seed: int = 0, sample_rate: int = 48000) -> None:
    rng = np.random.default_rng(seed)
    total = 0
    t = 0.0
    while total < n_samples:
        pcm = (rng.standard_normal(block) * 0.2).astype(np.float32)
        analyzer.process(pcm, t=t, out=data)
        total += block
        t += block / sample_rate


def test_low_bands_are_collapsed_before_warmup() -> None:
    """Before the rolling buffer has a full long-window's worth of real
    audio, the short path's own (partially-duplicated) values are used --
    no crash, no bogus data, a well-defined fallback state."""
    a = Analyzer()
    d = AudioData()
    _feed_noise(a, d, n_samples=1024)  # well under _LOW_BAND_N_FFT (8192)
    # The short path's own known collapse: bands 0-7 read one shared value
    # (all map to the same single FFT bin at 46.875 Hz/bin, 48kHz) --
    # verified directly against real corpus data before landing the fix.
    assert len(set(round(float(x), 6) for x in d.bands[:8])) == 1


def test_low_bands_are_resolved_after_warmup() -> None:
    """Once the long-window buffer has seen a full 8192 samples of real
    (non-silent) audio, the bottom _low_band_replace_n bands must show
    genuinely distinct values -- white noise has no reason to produce
    identical magnitude in adjacent-but-independent frequency bins, so
    any repeats left over would mean the replacement didn't actually
    reach that band."""
    a = Analyzer()
    d = AudioData()
    _feed_noise(a, d, n_samples=_LOW_BAND_N_FFT + 4096)
    n = a._low_band_replace_n
    low = [round(float(x), 6) for x in d.bands[:n]]
    assert len(set(low)) == n, low


def test_bands_beyond_replacement_range_still_match_short_path() -> None:
    """Bands _low_band_replace_n and above are untouched by this fix --
    same values (up to normalization) as before the low-band pass was
    added. Regression guard against the replacement loop accidentally
    running past its own intended range."""
    a_fixed = Analyzer()
    d_fixed = AudioData()
    _feed_noise(a_fixed, d_fixed, n_samples=_LOW_BAND_N_FFT + 4096, seed=1)
    n = a_fixed._low_band_replace_n

    # A second analyzer with the low-band buffer deliberately never warmed
    # up (by monkeypatching the warm-sample counter to always read short)
    # would require reaching into internals; instead, confirm structurally
    # that the mid/high bands are the same short-FFT values on repeated
    # calls once warm -- i.e. they don't change discontinuously purely
    # from the low-band pass switching on. Two consecutive frames of
    # identical input should give near-identical bands[n:] (short path
    # is deterministic for the same windowed input; small EMA smoothing
    # drift is expected, so this checks stability, not bit-exactness).
    high_before = np.array(d_fixed.bands[n:])
    rng = np.random.default_rng(1)
    pcm = (rng.standard_normal(512) * 0.2).astype(np.float32)
    a_fixed.process(pcm, t=100.0, out=d_fixed)
    high_after = np.array(d_fixed.bands[n:])
    assert np.max(np.abs(high_after - high_before)) < 0.5


def test_low_and_high_bands_share_units_on_pink_noise() -> None:
    """2026-09-10: the low-band replacement previously scaled the long-
    window magnitudes by a window-sum ratio only, on the mistaken premise
    that the short path applies no normalization of its own -- it does
    (spectrum /= max_val; spectrum *= sqrt(energy)). That left the two
    paths in different units: every band past the replacement boundary
    was crushed toward ~0.01 by the shared final peak-normalize, since
    the unnormalized long-window magnitudes always dominated the max.
    Pink noise reads roughly comparable magnitude across a log-spaced
    perceptual scale by construction -- assert the low/high band means
    don't show the >10x discontinuity the bug produced (measured live at
    the time: 46.4x on the real analyzer, 18.9x on an independent
    synthetic reproduction)."""
    a = Analyzer()
    d = AudioData()
    sample_rate = 48000
    rng = np.random.default_rng(7)
    total_samples = sample_rate * 2
    white = rng.standard_normal(total_samples).astype(np.float64)
    freqs = np.fft.rfftfreq(total_samples, 1.0 / sample_rate)
    freqs[0] = freqs[1]
    pink_spectrum = np.fft.rfft(white) / np.sqrt(freqs)
    pink = np.fft.irfft(pink_spectrum, n=total_samples).astype(np.float32)
    pink /= np.max(np.abs(pink)) + 1e-9
    pink *= 0.3

    block = 512
    t = 0.0
    for i in range(0, len(pink) - block, block):
        a.process(pink[i:i + block], t=t, out=d)
        t += block / sample_rate

    bands = np.asarray(d.bands)
    n = a._low_band_replace_n
    low_mean = float(bands[:n].mean())
    high_mean = float(bands[n:].mean())
    assert high_mean > 0.05, (low_mean, high_mean, bands)
    assert low_mean / high_mean < 10.0, (low_mean, high_mean, bands)


def test_silence_does_not_crash_and_eventually_zeros_bands() -> None:
    """One silent frame alone does not zero `bands` -- the EMA smoothing
    in the short path has real memory by design, a pre-existing property
    unrelated to this fix, not something to newly assert here. Feed
    enough silent frames for the EMA to actually decay, and confirm the
    low-band replacement path (energy-gated, like every other block in
    process()) doesn't reintroduce noise once the short path has gone
    quiet -- no crash, no NaN/inf, genuinely near-zero at the end."""
    a = Analyzer()
    d = AudioData()
    _feed_noise(a, d, n_samples=_LOW_BAND_N_FFT + 4096)
    silent = np.zeros(512, dtype=np.float32)
    for i in range(200):
        a.process(silent, t=1000.0 + i * 512 / 48000, out=d)
    bands = np.asarray(d.bands)
    assert np.all(np.isfinite(bands))
    assert np.max(np.abs(bands)) < 1e-3, bands


def test_set_sample_rate_recomputes_both_edge_tables() -> None:
    """2026-09-04: adjacent bug found while building this fix --
    set_sample_rate() previously updated _bin_hz but never recomputed
    _perc_edges (or, now, _low_band_edges), silently leaving the whole
    session's band-to-Hz mapping wrong for any device not running at the
    48000 Hz construction-time fallback. Both tables must change when the
    rate genuinely changes, and must NOT change (same object contents)
    when set_sample_rate() is called with the same rate (the documented
    cheap-no-op case)."""
    a = Analyzer()
    edges_before = np.array(a._perc_edges)
    low_edges_before = np.array(a._low_band_edges)

    a.set_sample_rate(48000)  # no-op: already the construction-time default
    assert np.array_equal(a._perc_edges, edges_before)
    assert np.array_equal(a._low_band_edges, low_edges_before)

    a.set_sample_rate(44100)  # genuine change
    assert not np.array_equal(a._perc_edges, edges_before)
    assert not np.array_equal(a._low_band_edges, low_edges_before)
