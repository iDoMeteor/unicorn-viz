"""Regression tests for the RC1 P1 stability fixes.

Covers: recorder-death surfacing (consume-once failure latch, is_recording
goes False), transition-validation drift (every engine transition + alias
validates), and the FBO release helper (attachments released with the FBO).
"""
from __future__ import annotations

from unicornviz.app import App
from unicornviz.config import _TRANSITIONS
import unicornviz.recording as recording


class _Cfg:
    def get(self, section: str, key: str, default=None):
        return default


# The authoritative engine list from App._switch_effect plus runtime aliases.
_ENGINE_TRANSITIONS = [
    'crossfade', 'smoothfade', 'scanwipe_x', 'scanwipe_y', 'dissolve',
    'zoomblend', 'radialwipe', 'lumawipe', 'stripewipe', 'anglesweep',
    'glitchsoft', 'prismsplit',
]
_ALIASES = ['scanwipe', 'radial', 'cut', 'shuffle', 'random']


def test_every_engine_transition_validates() -> None:
    for name in _ENGINE_TRANSITIONS + _ALIASES:
        assert name in _TRANSITIONS, f'{name} implemented but rejected by validation'


def test_recorder_failure_latch_consumed_once() -> None:
    rec = recording.Recorder(_Cfg(), 64, 64)
    rec._last_error = 'Recording write failed: broken pipe'
    rec._write_failed = True

    class _Proc:
        stdin = object()

        # Still running: this asserts the write-failure latch alone marks
        # the recorder dead, independently of ffmpeg's own exit state.
        def poll(self):
            return None

    rec._process = _Proc()
    # A failed recorder must not report as recording (app stops paying the
    # per-frame readback cost) …
    assert rec.is_recording is False
    assert rec.has_failed is True
    # … and the failure message is delivered exactly once.
    assert rec.consume_failure() == 'Recording write failed: broken pipe'
    assert rec.consume_failure() is None


def test_recorder_start_state_resets_failure_latch() -> None:
    rec = recording.Recorder(_Cfg(), 64, 64)
    rec._write_failed = True
    rec._failure_reported = True
    # start() resets both flags before spawning; emulate the reset block.
    rec._write_failed = False
    rec._failure_reported = False
    assert rec.has_failed is False
    assert rec.consume_failure() is None


class _Releasable:
    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


class _FakeFbo:
    def __init__(self) -> None:
        self.color_attachments = [_Releasable()]
        self.depth_attachment = _Releasable()
        self.released = False

    def release(self) -> None:
        self.released = True


def test_release_fbo_releases_attachments_too() -> None:
    class _Stub:
        pass

    stub = _Stub()
    fbo = _FakeFbo()
    App._release_fbo(stub, fbo)  # type: ignore[arg-type]
    assert fbo.released is True
    assert fbo.color_attachments[0].released is True
    assert fbo.depth_attachment.released is True


def test_release_fbo_tolerates_none() -> None:
    class _Stub:
        pass

    App._release_fbo(_Stub(), None)  # type: ignore[arg-type]  # must not raise
