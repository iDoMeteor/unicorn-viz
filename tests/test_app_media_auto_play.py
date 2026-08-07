"""Regression tests for media-01's boot-time auto-play trigger.

2026-08-07: [media] auto_play (unicornviz/app.py's App._maybe_auto_play_media)
mirrors the RTMP streamer's existing auto_start pattern -- built for
unattended/headless use (training-daemon --media-source). The real App
method is exercised unbound against a minimal stub, matching
test_app_effect_pinning.py's pattern -- no SDL/GL context is created.
"""
from __future__ import annotations

from typing import Any

from unicornviz.app import App


class _MediaStub:
    def __init__(self, *, enabled: bool = True, auto_play: bool = True,
                 raises: bool = False) -> None:
        self.enabled = enabled
        self.auto_play = auto_play
        self._raises = raises
        self.calls = 0

    def play_pause(self) -> str:
        self.calls += 1
        if self._raises:
            raise RuntimeError('boom')
        return 'Media: playing track'


class _AppStub:
    def __init__(self, media: Any) -> None:
        self._media = media

    _maybe_auto_play_media = App._maybe_auto_play_media


def test_auto_play_calls_play_pause_when_enabled_and_configured() -> None:
    stub = _MediaStub()
    app = _AppStub(stub)

    app._maybe_auto_play_media()

    assert stub.calls == 1


def test_auto_play_noop_when_flag_off() -> None:
    stub = _MediaStub(auto_play=False)
    app = _AppStub(stub)

    app._maybe_auto_play_media()

    assert stub.calls == 0


def test_auto_play_noop_when_media_disabled() -> None:
    stub = _MediaStub(enabled=False)
    app = _AppStub(stub)

    app._maybe_auto_play_media()

    assert stub.calls == 0


def test_auto_play_noop_when_media_is_none() -> None:
    app = _AppStub(None)

    app._maybe_auto_play_media()  # must not raise


def test_auto_play_swallows_play_pause_exception() -> None:
    stub = _MediaStub(raises=True)
    app = _AppStub(stub)

    app._maybe_auto_play_media()  # must not raise

    assert stub.calls == 1
