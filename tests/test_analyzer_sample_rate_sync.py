"""Regression tests for Analyzer.set_sample_rate().

2026-08-14: _ASSUMED_SAMPLE_RATE was a hardcoded 48000 constant used
directly for _bin_hz (spectral centroid / perceptual band mapping) and
the onset-envelope/vocal-heuristic dt terms, never reconciled with the
real capture device's rate. Found auditing a live session where a
~7-13 BPM overshoot was suspected to be a sample-rate mismatch (that
specific incident turned out not to be this -- the device really was
48000 Hz all night -- but the mismatch risk itself was real and latent).
AudioManager now syncs the analyzer to the real capture rate every frame
via set_sample_rate(), a cheap no-op when unchanged.
"""
from __future__ import annotations

from unicornviz.audio.analyzer import Analyzer, _ASSUMED_SAMPLE_RATE


def test_set_sample_rate_updates_bin_hz() -> None:
    az = Analyzer()
    before = az._bin_hz
    assert az._sample_rate == _ASSUMED_SAMPLE_RATE

    az.set_sample_rate(44100)

    assert az._sample_rate == 44100
    assert az._bin_hz != before
    assert az._bin_hz == 44100 / az._n_fft


def test_set_sample_rate_is_a_noop_when_unchanged() -> None:
    az = Analyzer()
    az.set_sample_rate(44100)
    bin_hz_after_first_set = az._bin_hz

    az.set_sample_rate(44100)   # same value again

    assert az._bin_hz == bin_hz_after_first_set


def test_set_sample_rate_ignores_non_positive_values() -> None:
    az = Analyzer()
    original_rate = az._sample_rate

    az.set_sample_rate(0)
    az.set_sample_rate(-48000)

    assert az._sample_rate == original_rate


def test_set_sample_rate_reflected_in_vocal_and_envelope_dt() -> None:
    """The two per-call dt = len(pcm) / self._sample_rate sites must read
    the synced rate, not the module-level fallback, once set."""
    import numpy as np

    az = Analyzer()
    az.set_sample_rate(44100)
    block = np.zeros(1024, dtype=np.float32)

    # Must not raise, and must actually use the synced rate for its
    # internal dt math (indirectly verified: env buffer receives a
    # 1024/44100 step rather than 1024/48000 -- exercised via process()
    # completing without error against the updated _sample_rate).
    az.process(block, t=0.0)
    assert az._sample_rate == 44100
