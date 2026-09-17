"""AudioData.fft must always match the configured [audio] fft_bands.

2026-09-17 bug: AudioData.fft was a bare ``np.zeros(512, ...)`` literal,
completely independent of the Analyzer's own fft_bands-sized arrays. Any
fft_bands choice other than the default 512 (256, 1024 and 2048 are all
offered in the config editor) crashed the whole audio-analysis thread on the
very first frame, at ``Analyzer.process``'s ``data.fft[:] = self._smoothed``
(shapes disagree) -- confirmed live via a user-reported traceback.

The fix makes AudioData.fft's length a class-level setting
(``AudioData.configure_fft_bins`` / ``AudioData.fft_bins()``), set from the
real config value before any AudioData is constructed (AudioManager.__init__
and App.__init__ each do this from the same [audio] fft_bands read), so every
construction site -- the live manager's buffers, the app's scratch buffers,
and every ad hoc ``AudioData()`` fallback -- agrees on one size.

Fixing AudioData alone was not enough: audio_centroid.py, audio_chromogram.py
and audio_spectrogram.py each independently hardcoded a 512-sized GL texture
or weight matrix of their own "matching AudioData.fft's length" by comment
only, so they would have simply moved the same crash into the render thread.
These tests also cover their derivation functions at non-default band counts.

A second, live-caught bug in the same fix: App.__init__ built
_audio_scratch_current/_audio_scratch_next before a RESTART-badged fft_bands
choice persisted from a previous session gets laid over self.cfg (that
override only applies in run(), well after __init__), so those two scratch
buffers could still be built at the stale on-disk value. Unlike
self._audio/self._audio_raw (replaced wholesale every frame from
AudioManager's own buffers), the scratch pair is only ever written into in
place, so the stale size survived to crash copy_audio_data() on the first
real frame -- shapes (256,) () (512,) -- exactly mirroring the original bug
report, just one layer further out. App._configure_audio_data_fft_bins()
fixes it by being called again in run(), right after the override is
applied; these tests cover that method directly.
"""
from __future__ import annotations

import numpy as np
import pytest

from unicornviz.app import App
from unicornviz.audio.analyzer import Analyzer
from unicornviz.audio.manager import AudioManager
from unicornviz.config import Config
from unicornviz.effects.audio_chromogram import _build_chroma_weights, _fft_low_rolloff
from unicornviz.effects.audio_spectrogram import _build_log_lut
from unicornviz.effects.base import AudioData, copy_audio_data


class _StubCfg:
    """cfg.get(section, key, default) + set_override, backed by a dict."""

    def __init__(self, values: dict | None = None) -> None:
        self._values: dict[tuple, object] = dict(values or {})

    def get(self, *keys, default=None):
        return self._values.get(tuple(keys), default)

    def set_override(self, section, key, value):
        self._values[(section, key)] = value

_RATE = 48000
# The three landmines named for the user: every _FFT_BANDS_CHOICES value in
# app.py other than the working default (512).
_LANDMINES = (256, 1024, 2048)


def _block(n: int = 4096) -> np.ndarray:
    t = np.arange(n, dtype=np.float32) / _RATE
    return (0.5 * np.sin(2.0 * np.pi * 110.0 * t)).astype(np.float32)


@pytest.fixture(autouse=True)
def _reset_fft_bins():
    """AudioData._fft_bins is process-global (see its docstring) -- restore
    the default after every test so this file cannot leak state into tests
    that assume the shipped default of 512."""
    yield
    AudioData.configure_fft_bins(512)


def test_default_matches_the_shipped_default():
    assert AudioData.fft_bins() == 512
    assert AudioData().fft.shape == (512,)


@pytest.mark.parametrize('bands', (512, *_LANDMINES))
def test_configure_fft_bins_resizes_new_instances(bands):
    AudioData.configure_fft_bins(bands)
    assert AudioData.fft_bins() == bands
    assert AudioData().fft.shape == (bands,)


@pytest.mark.parametrize('bands', _LANDMINES)
def test_analyzer_no_longer_crashes_at_each_landmine_value(bands):
    """Reproduces the exact reported crash: could not broadcast (bands,) into (512,)."""
    AudioData.configure_fft_bins(bands)
    out = AudioData()
    analyzer = Analyzer(fft_bands=bands)
    analyzer.process(_block(), out=out)  # used to raise ValueError here
    assert out.fft.shape == (bands,)


def test_analyzer_still_works_at_the_shipped_default():
    AudioData.configure_fft_bins(512)
    out = AudioData()
    Analyzer(fft_bands=512).process(_block(), out=out)
    assert out.fft.shape == (512,)


@pytest.mark.parametrize('bands', (512, *_LANDMINES))
def test_audio_manager_configures_audio_data_from_its_own_fft_bands(tmp_path, bands):
    """AudioManager.__init__ must set the class attribute before it builds
    its own AudioData buffers, from the exact same config value it read."""
    cfg_path = tmp_path / 'config.toml'
    cfg_path.write_text(f'[audio]\nfft_bands = {bands}\n')
    mgr = AudioManager(Config(cfg_path))
    assert AudioData.fft_bins() == bands
    assert mgr._last_data.fft.shape == (bands,)
    assert mgr._front_buf.fft.shape == (bands,)


@pytest.mark.parametrize('bands', (512, *_LANDMINES))
def test_spectrogram_lut_tracks_the_configured_band_count(bands):
    """audio_spectrogram._build_log_lut must stay in range for any fft_bands."""
    lut = _build_log_lut(256, bands)
    assert lut.shape == (256,)
    assert lut.min() >= 0
    assert lut.max() < bands


@pytest.mark.parametrize('bands', (512, *_LANDMINES))
def test_chromogram_weight_matrices_track_the_configured_band_count(bands):
    """audio_chromogram's weight/rolloff builders must size to any fft_bands,
    not just the 512 they used to read from a frozen module constant."""
    bin_hz = 48000.0 / (bands * 2.0)
    weights = _build_chroma_weights(bands, bin_hz)
    assert weights.shape == (bands, 12)
    rolloff = _fft_low_rolloff(bands, bin_hz)
    assert rolloff.shape == (bands,)


def _app_with_stub_cfg(fft_bands: int) -> App:
    app = object.__new__(App)
    app.cfg = _StubCfg({('audio', 'fft_bands'): fft_bands})
    return app


def test_configure_audio_data_fft_bins_sizes_the_scratch_buffers():
    app = _app_with_stub_cfg(256)
    app._configure_audio_data_fft_bins()
    assert AudioData.fft_bins() == 256
    assert app._audio_scratch_current.fft.shape == (256,)
    assert app._audio_scratch_next.fft.shape == (256,)


@pytest.mark.parametrize('bands', _LANDMINES)
def test_a_restart_override_applied_after_init_rebuilds_the_scratch_buffers(bands):
    """Reproduces the live-caught second bug: __init__ builds the scratch
    pair from the on-disk config (512), a RESTART override changes the
    effective fft_bands afterward (as _apply_runtime_config_overrides()
    does in run(), before AudioManager is built) -- the buffers must be
    rebuilt, not left at the stale size from the first call."""
    app = _app_with_stub_cfg(512)
    app._configure_audio_data_fft_bins()  # mirrors App.__init__
    assert app._audio_scratch_current.fft.shape == (512,)

    app.cfg.set_override('audio', 'fft_bands', bands)  # mirrors the restart override
    app._configure_audio_data_fft_bins()  # mirrors the call added in run()
    assert app._audio_scratch_current.fft.shape == (bands,)
    assert app._audio_scratch_next.fft.shape == (bands,)

    # A manager-sourced AudioData (built after the same override, so already
    # at the true final size) must copy into the rebuilt scratch buffer
    # cleanly -- this is the exact call that raised "shapes (N,) () (512,)"
    # live before the fix.
    source = AudioData()
    assert source.fft.shape == (bands,)
    copy_audio_data(source, app._audio_scratch_next)
