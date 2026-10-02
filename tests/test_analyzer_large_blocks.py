"""B P2-3 (audit 2026-09-30): larger capture blocks truncated the FFT.

``np.fft.rfft(windowed, n=bands * 2)`` cuts a longer block to its first
``2 * bands`` samples, and the Hann window was sized for the whole block, so with
the documented ``blocksize = 2048`` xrun remedy and the default ``fft_bands =
512`` the spectrum, flux, onsets and bands saw only the *older* half of every
block, through the rising half of the window: the newest audio never arrived.
The FFT now takes the most recent ``2 * bands`` samples with a window of that
length, so the spectrum of a block depends on its newest samples at any size.
"""
from __future__ import annotations

import numpy as np
import pytest

from unicornviz.audio.analyzer import Analyzer
from unicornviz.effects.base import AudioData

RATE = 48000
BANDS = 512
FFT_LEN = BANDS * 2


def _tone(n: int, hz: float = 110.0, start: int = 0) -> np.ndarray:
    t = (np.arange(n) + start) / RATE
    return (0.5 * np.sin(2.0 * np.pi * hz * t)).astype(np.float32)


def _spectrum(an: Analyzer) -> np.ndarray:
    return np.array(an._spectrum_work, copy=True)


def _newest_burst_block(n: int) -> np.ndarray:
    """A loud, steady 3 kHz tone, then a 110 Hz burst in the newest ``FFT_LEN``
    samples (a kick landing at the end of the block).  Block level stays the
    same at every size, so the silence gate does not scale the spectrum and the
    only thing that can differ between sizes is *which samples the FFT sees*."""
    block = _tone(n, hz=3000.0)
    block[-FFT_LEN:] = _tone(FFT_LEN)
    return block


@pytest.mark.parametrize('blocksize', [1024, 2048, 4096, 8192])
def test_the_newest_audio_reaches_the_spectrum_at_any_block_size(blocksize) -> None:
    reference = Analyzer(fft_bands=BANDS)
    reference.process(_tone(FFT_LEN), out=AudioData())            # exactly 2*bands: never truncated
    want = _spectrum(reference)
    assert want.max() > 0.5                   # the reference really has energy (spectrum is peak-normalized)

    an = Analyzer(fft_bands=BANDS)
    an.process(_newest_burst_block(blocksize), out=AudioData())
    got = _spectrum(an)
    np.testing.assert_allclose(got, want, rtol=1e-4, atol=1e-3,
                               err_msg=f'blocksize {blocksize}: the spectrum is not the newest audio\'s')
    peak_hz = int(np.argmax(got)) * RATE / FFT_LEN
    assert peak_hz < 200.0, f'blocksize {blocksize}: peak at {peak_hz} Hz is the OLD 3 kHz tone'


@pytest.mark.parametrize('blocksize', [2048, 4096])
def test_the_oldest_audio_does_not_leak_into_the_spectrum(blocksize) -> None:
    """Loud audio only in the OLDEST part of a long block, silence in the newest
    ``FFT_LEN`` samples: the analysis window holds silence, instead of the old
    tone being the only thing the FFT used to see."""
    block = _tone(blocksize, hz=1000.0)
    block[-FFT_LEN:] = 0.0
    an = Analyzer(fft_bands=BANDS)
    an.process(block, out=AudioData())
    assert an.last_raw_rms > 0.05                                 # the block itself is loud
    assert _spectrum(an).max() < 1e-3


def test_blocks_up_to_the_fft_length_behave_as_before() -> None:
    a, b = Analyzer(fft_bands=BANDS), Analyzer(fft_bands=BANDS)
    a.process(_tone(512), out=AudioData())                        # zero-padded, as always
    b.process(_tone(512), out=AudioData())
    np.testing.assert_array_equal(_spectrum(a), _spectrum(b))
    assert _spectrum(a).max() > 0.5
    c = Analyzer(fft_bands=BANDS)
    c.process(_tone(FFT_LEN), out=AudioData())
    assert _spectrum(c).max() > 0.5


@pytest.mark.parametrize('blocksize', [2048, 4096])
def test_a_kick_at_the_end_of_a_long_block_drives_the_flux(blocksize) -> None:
    """The onset path sees the new transient: flux from silence to a kick in the
    newest samples must be large, not zero as it was when only the old half
    (silence) was transformed."""
    an = Analyzer(fft_bands=BANDS)
    an.process(np.zeros(blocksize, dtype=np.float32), out=AudioData())
    burst = np.zeros(blocksize, dtype=np.float32)
    burst[-FFT_LEN:] = _tone(FFT_LEN)
    an.process(burst, out=AudioData())
    assert float(np.sum(an._flux_delta)) > 1.0


@pytest.mark.parametrize('blocksize', [2048, 4096])
def test_the_side_channel_uses_the_same_newest_window(blocksize) -> None:
    an = Analyzer(fft_bands=BANDS)
    block = _newest_burst_block(blocksize)
    an.process(block, out=AudioData(), side=block)
    assert _spectrum(an).max() > 0.5
    assert float(np.array(an._side_spectrum_work).max()) > 0.5
    side = np.array(an._side_spectrum_work)
    mid = _spectrum(an)
    # The side spectrum is raw magnitude, the mid one is peak-normalized: compare shapes.
    np.testing.assert_allclose(side / side.max(), mid / mid.max(), rtol=1e-3, atol=1e-3)
    assert int(np.argmax(side)) * RATE / FFT_LEN < 200.0          # the newest tone, not the old 3 kHz


def test_rms_still_covers_the_whole_block() -> None:
    """Level (the silence gate's input) is a property of the whole block."""
    an = Analyzer(fft_bands=BANDS)
    block = np.concatenate([_tone(2048), np.zeros(2048, dtype=np.float32)])
    an.process(block, out=AudioData())
    assert an.last_raw_rms > 0.05
