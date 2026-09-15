from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from unicornviz.audio.manager import AudioManager
from unicornviz.config import Config
from unicornviz.effects.base import AudioData


class _CaptureBase:
    active = False

    def stop(self) -> None:
        return

    def current_source_label(self) -> str:
        return 'test-source'

    def signal_new_block(self) -> None:
        return

    def maybe_fallback(self) -> None:
        return

    def wait_for_new_block(self, timeout_s: float = 0.5) -> bool:
        import time
        time.sleep(min(timeout_s, 0.05))
        return False  # always timeout so analysis worker loops quietly

    def get_block_if_new(self, last_seq: int):
        return None, last_seq


class _CaptureSlowStart(_CaptureBase):
    def start(self) -> None:
        time.sleep(0.05)


class _CaptureRaise(_CaptureBase):
    def start(self) -> None:
        raise ValueError('boom')


class _CaptureInactive(_CaptureBase):
    def start(self) -> None:
        return


class _CaptureActive(_CaptureBase):
    def __init__(self) -> None:
        self.active = False

    def start(self) -> None:
        self.active = True


def _manager() -> AudioManager:
    return AudioManager(Config(Path('tests') / '_missing_config_for_tests.toml'))


def test_default_audio_profile_is_house() -> None:
    """2026-08-06: defaults to 'house' -- reverted from a brief 2026-08-05
    default of 'generic' (a wide/uninformative prior, meant to mirror how
    the BPM detector starts with no lock rather than a seeded guess).
    'generic' is enabled=False in PROFILES on purpose: a disabled loose
    catch-all never meant to be a real starting analyzer profile, and it
    made for a noticeably weaker start to a training session."""
    manager = _manager()
    assert manager.get_profile_key() == 'house'


def test_sample_rate_delegates_to_capture() -> None:
    """2026-08-09: new public property so auto-vj-01's spectral centroid
    calc can derive Nyquist from the real capture rate instead of assuming
    a fixed 44.1kHz -- real devices/PipeWire commonly negotiate 48kHz
    (this project's own documented default), understating every centroid
    reading by ~8.8% under the old fixed assumption."""
    manager = _manager()
    manager._capture._sample_rate = 44100
    assert manager.sample_rate == 44100


def test_start_times_out_when_capture_hangs() -> None:
    manager = _manager()
    manager._capture = _CaptureSlowStart()

    with pytest.raises(TimeoutError, match='timed out'):
        manager.start(timeout_s=0.01)


class _CaptureHang(_CaptureBase):
    """start() blocks until released, like Pa_OpenStream stuck behind a busy
    PipeWire JACK shim (OBS running, 2026-09-14)."""

    def __init__(self) -> None:
        import threading
        self.release = threading.Event()
        self.closed_cleanly = True
        self.starts = 0

    def start(self) -> None:
        self.starts += 1
        self.release.wait(timeout=5.0)
        self.active = True


def test_stop_skips_pa_terminate_while_open_is_in_flight(monkeypatch) -> None:
    """2026-09-14 abort: start() timed out, the retry path called stop(),
    and Pa_Terminate ran while the start worker was still inside
    Pa_OpenStream -- PortAudio's JACK host API asserted and took the
    process down.  With the open still in flight, stop() must not
    terminate PortAudio and must drop sounddevice's atexit teardown too."""
    import atexit

    import sounddevice as sd

    calls: list[str] = []
    monkeypatch.setattr(sd, '_terminate', lambda: calls.append('terminate'))
    monkeypatch.setattr(atexit, 'unregister', lambda fn: calls.append('unregister'))
    manager = _manager()
    cap = _CaptureHang()
    manager._capture = cap
    with pytest.raises(TimeoutError, match='timed out'):
        manager.start(timeout_s=0.01)
    assert manager._start_worker is not None and manager._start_worker.is_alive()

    manager.stop()
    assert calls == ['unregister']          # no Pa_Terminate under a live open
    cap.release.set()
    manager._start_worker.join(timeout=2.0)


def test_retry_does_not_open_a_second_stream_over_a_stuck_one() -> None:
    """The retry must wait for the stuck worker, not launch a second open
    (PortAudio's open path is not reentrant)."""
    manager = _manager()
    cap = _CaptureHang()
    manager._capture = cap
    with pytest.raises(TimeoutError, match='timed out'):
        manager.start(timeout_s=0.01)
    with pytest.raises(TimeoutError, match='still in flight'):
        manager.start(timeout_s=0.01)
    assert cap.starts == 1
    # Once the stuck open finally completes, the next attempt adopts the
    # live capture instead of opening again.
    cap.release.set()
    manager.start(timeout_s=0.5)
    assert cap.starts == 1
    manager.stop()


def test_start_wraps_capture_exception() -> None:
    manager = _manager()
    manager._capture = _CaptureRaise()

    with pytest.raises(RuntimeError, match='startup failed'):
        manager.start(timeout_s=0.1)


def test_start_requires_active_capture() -> None:
    manager = _manager()
    manager._capture = _CaptureInactive()

    with pytest.raises(RuntimeError, match='did not become active'):
        manager.start(timeout_s=None)


def test_start_succeeds_for_active_capture() -> None:
    manager = _manager()
    manager._capture = _CaptureActive()

    manager.start(timeout_s=0.1)
    # Stop cleanly so the analysis thread doesn't leak into other tests.
    manager.stop()


# ---------------------------------------------------------------------------
# 2026-08-09: _copy_audio_into()'s hand-written field list silently dropped
# vocal_hnr/vocal_fmr for its entire lifetime -- they were added to
# AudioData's __slots__ after this copy function was written and never
# added here, so every consumer of get_audio_data()/get_audio_data_raw()
# read the AudioData() default (0.0) forever, even though the analyzer
# computed real nonzero values every frame. Confirmed via live execution
# against a real Analyzer() + synthetic vocal-like signal (see
# docs/adr/vj-system.md, auto-vj-01, for the recommender-side symptom this
# caused: mean_vocal_hnr/mean_vocal_fmr exactly 0.0 on 803/803 real session
# rows). This test enumerates every AudioData slot dynamically -- not just
# the two dropped here -- so a future field added to AudioData without a
# matching line in _copy_audio_into() fails loudly instead of silently
# reading a stale default forever, the same way these two did.
# ---------------------------------------------------------------------------


def test_copy_audio_into_copies_every_audiodata_slot() -> None:
    source = AudioData()
    target = AudioData()
    for i, name in enumerate(AudioData.__slots__):
        current = getattr(source, name)
        if hasattr(current, '__setitem__'):
            current[:] = np.arange(len(current), dtype=current.dtype) + i + 1
        else:
            setattr(source, name, float(i) + 1.0)

    AudioManager._copy_audio_into(source, target)

    for name in AudioData.__slots__:
        source_val = getattr(source, name)
        target_val = getattr(target, name)
        if hasattr(source_val, '__len__'):
            assert list(target_val) == list(source_val), f'{name} not copied'
        else:
            assert target_val == source_val, f'{name} not copied'


def test_copy_audio_into_copies_vocal_hnr_and_fmr() -> None:
    """Narrower, explicit regression for the specific fields that were
    dropped -- kept alongside the exhaustive test above so this exact
    symptom has a test that names it directly."""
    source = AudioData()
    target = AudioData()
    source.vocal_hnr = 0.6899
    source.vocal_fmr = 0.6804

    AudioManager._copy_audio_into(source, target)

    assert target.vocal_hnr == pytest.approx(0.6899)
    assert target.vocal_fmr == pytest.approx(0.6804)
