"""The optional PCM look-back an effect uses to arrive with history already on.

Effects are handed an :class:`AudioData` snapshot of the current frame and
nothing older, so a scrolling display has to start blank and fill in over
several seconds. ``VJApi.get_recent_pcm_window()`` exposes the capture's
rolling ring so an effect can analyse what already happened, once, at
activation.

The contract pinned here is that it is *optional in every direction*: no app,
no audio manager, an older core without the method, or a raising
implementation must all degrade to ``None`` rather than propagate, because the
caller is a visual effect and must never be able to take the renderer down.
"""
from __future__ import annotations

import numpy as np

from unicornviz.vj_api import VJApi


class _Mgr:
    """Stand-in audio manager with a controllable window response."""

    def __init__(self, result=None, boom: bool = False) -> None:
        self._result = result
        self._boom = boom
        self.asked_for: float | None = None

    def get_recent_pcm_window(self, duration_s):
        self.asked_for = duration_s
        if self._boom:
            raise RuntimeError('device went away mid-read')
        return self._result


class _App:
    def __init__(self, mgr=None) -> None:
        self._audio_manager = mgr


def test_returns_the_window_the_manager_provides():
    """The happy path hands back the PCM and its sample rate unchanged."""
    pcm = np.zeros(2048, dtype=np.float32)
    api = VJApi(_App(_Mgr(result=(pcm, 48000))))
    got = api.get_recent_pcm_window(2.0)
    assert got is not None
    block, rate = got
    assert block is pcm
    assert rate == 48000


def test_duration_is_passed_through():
    """The caller's requested look-back reaches the manager."""
    mgr = _Mgr(result=(np.zeros(8, dtype=np.float32), 44100))
    VJApi(_App(mgr)).get_recent_pcm_window(7.5)
    assert mgr.asked_for == 7.5


def test_none_without_an_audio_manager():
    """Headless or pre-init: no manager, no window, no exception."""
    assert VJApi(_App(None)).get_recent_pcm_window() is None


def test_none_when_the_manager_lacks_the_method():
    """An older core simply has nothing to offer here."""
    class _Old:
        pass
    assert VJApi(_App(_Old())).get_recent_pcm_window() is None


def test_none_when_the_manager_raises():
    """A failing capture must not propagate into an effect's _init()."""
    assert VJApi(_App(_Mgr(boom=True))).get_recent_pcm_window() is None


def test_none_result_passes_through_as_none():
    """An empty ring reports nothing rather than an empty array."""
    assert VJApi(_App(_Mgr(result=None))).get_recent_pcm_window() is None
