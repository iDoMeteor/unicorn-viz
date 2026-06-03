from __future__ import annotations

import time
from pathlib import Path

import pytest

from unicornviz.audio.manager import AudioManager
from unicornviz.config import Config


class _CaptureBase:
    active = False

    def stop(self) -> None:
        return

    def current_source_label(self) -> str:
        return 'test-source'


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


def test_start_times_out_when_capture_hangs() -> None:
    manager = _manager()
    manager._capture = _CaptureSlowStart()

    with pytest.raises(TimeoutError, match='timed out'):
        manager.start(timeout_s=0.01)


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
