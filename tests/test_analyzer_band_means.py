"""The 64-band perceptual means are running-sum reads, same values as a loop.

2026-09-24: ``Analyzer.process()`` used to take ~80 tiny ``.mean()`` calls
per block (64 perceptual bands plus the low-band replacements) -- ~46% of the
analysis thread, all under the GIL.  They are now two running-sum reads.
These tests pin the definition the loop encoded: band *i* is the mean of bins
``[edges[i], edges[i + 1]]`` inclusive, or bin ``edges[i]`` alone when the
edges collapse, for both edge tables and at both common sample rates.
"""
from __future__ import annotations

import numpy as np
import pytest

from unicornviz.audio.analyzer import Analyzer


def _loop_means(values: np.ndarray, edges: np.ndarray, n: int) -> np.ndarray:
    out = np.zeros(n, dtype=np.float64)
    for i in range(n):
        lo, hi = int(edges[i]), int(edges[i + 1])
        out[i] = values[lo:hi + 1].mean() if hi > lo else values[lo]
    return out


def _table_means(values, lo, hi1, cnt) -> np.ndarray:
    cs = np.concatenate(([0.0], np.cumsum(values, dtype=np.float64)))
    return (cs[hi1] - cs[lo]) / cnt


@pytest.mark.parametrize('rate', [48000, 44100])
def test_perceptual_band_tables_match_the_per_band_mean(rate: int) -> None:
    an = Analyzer()
    an.set_sample_rate(rate)
    values = np.random.default_rng(rate).random(an._bands).astype(np.float32)
    expected = _loop_means(values, an._perc_edges, len(an._perc_lo))
    got = _table_means(values, an._perc_lo, an._perc_hi1, an._perc_cnt)
    np.testing.assert_allclose(got, expected, rtol=1e-6, atol=1e-7)
    # Collapsed bands read their single bin exactly, not a near-miss mean.
    collapsed = an._perc_edges[1:] <= an._perc_edges[:-1]
    assert collapsed.any()
    assert np.array_equal(got[collapsed], values[an._perc_lo[collapsed]])


@pytest.mark.parametrize('rate', [48000, 44100])
def test_low_band_tables_cover_exactly_the_replaced_bands(rate: int) -> None:
    an = Analyzer()
    an.set_sample_rate(rate)
    n = an._low_band_replace_n
    assert len(an._low_lo) == len(an._low_hi1) == len(an._low_cnt) == n > 0
    size = an._low_csum.size - 1
    values = np.random.default_rng(n).random(size).astype(np.float32)
    expected = _loop_means(values, an._low_band_edges, n)
    got = _table_means(values, an._low_lo, an._low_hi1, an._low_cnt)
    np.testing.assert_allclose(got, expected, rtol=1e-6, atol=1e-7)


def test_process_fills_bands_from_the_tables() -> None:
    """End to end: a real block through process() lands the table result."""
    an = Analyzer()
    sr, blk = 48000, 1024
    t = np.arange(blk) / sr
    for i in range(40):
        x = (0.4 * np.sin(2 * np.pi * 55 * (t + i * blk / sr))).astype(np.float32)
        an.process(x, t=i * blk / sr)
    expected = _loop_means(an._smoothed, an._perc_edges, len(an._perc_lo))
    # _perc_work also carries the low-band replacement and peak normalize;
    # compare the untouched upper bands, re-normalized the same way.
    n = an._low_band_replace_n
    got = an._perc_work[n:]
    ref = expected[n:]
    peak = max(float(an._perc_work.max()), 1e-12)
    assert peak == pytest.approx(1.0, abs=1e-6)
    ratio = got[ref > 1e-6] / ref[ref > 1e-6]
    assert np.allclose(ratio, ratio[0], rtol=1e-5)
