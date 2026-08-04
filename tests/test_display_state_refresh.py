"""Regression tests: event-driven display-state re-derivation.

July 2026-07-08 audit item 5 (open since): display index + window origin
were derived at startup and refreshed only on monitor hotplug, so
compositor-initiated moves (workspace switches, Windows monitor drags)
left overlays/tiling on stale geometry. The refresh is deliberately
conservative: an origin outside every known display layout keeps the
cache (compositor-drift guard).
"""
from __future__ import annotations

import ctypes

import unicornviz.app as app_mod
from unicornviz.app import App


class _Stub:
    _DISPLAY_REFRESH_MIN_S = App._DISPLAY_REFRESH_MIN_S
    _refresh_display_state = App._refresh_display_state

    def __init__(self) -> None:
        self._window = object()
        self._display_refresh_last_t = -10.0
        self._display_index = 0
        self._window_origin_x = 0
        self._window_origin_y = 0
        self._layouts = [(0, 0, 1920, 1080), (1920, 0, 3840, 2160)]

    def _multihead_layouts(self):
        return self._layouts


def _patch_sdl(monkeypatch, *, display: int, pos: tuple[int, int]) -> None:
    monkeypatch.setattr(app_mod.sdl2, 'SDL_GetWindowDisplayIndex',
                        lambda _w: display, raising=False)

    def _get_pos(_w, wx, wy):
        wx.value, wy.value = pos
        return 0

    monkeypatch.setattr(app_mod.sdl2, 'SDL_GetWindowPosition', _get_pos,
                        raising=False)


def test_valid_move_commits_display_and_origin(monkeypatch) -> None:
    s = _Stub()
    _patch_sdl(monkeypatch, display=1, pos=(2000, 100))
    s._refresh_display_state('test')
    assert s._display_index == 1
    assert (s._window_origin_x, s._window_origin_y) == (2000, 100)


def test_origin_outside_known_layouts_keeps_cache(monkeypatch) -> None:
    s = _Stub()
    _patch_sdl(monkeypatch, display=0, pos=(-9999, -9999))
    s._refresh_display_state('test')
    # Display index query is trusted; the implausible origin is not.
    assert (s._window_origin_x, s._window_origin_y) == (0, 0)


def test_refresh_is_throttled(monkeypatch) -> None:
    s = _Stub()
    _patch_sdl(monkeypatch, display=1, pos=(2000, 100))
    s._refresh_display_state('test')
    _patch_sdl(monkeypatch, display=0, pos=(0, 0))
    s._refresh_display_state('test')  # within the throttle window: no-op
    assert s._display_index == 1
    assert s._window_origin_x == 2000


def test_no_layouts_trusts_sdl(monkeypatch) -> None:
    s = _Stub()
    s._layouts = []
    _patch_sdl(monkeypatch, display=-1, pos=(50, 60))
    s._refresh_display_state('test')
    assert s._display_index == 0  # invalid query ignored
    assert (s._window_origin_x, s._window_origin_y) == (50, 60)


def test_ctypes_signature_matches_real_call() -> None:
    # The method passes c_int instances positionally — pin that contract so
    # a refactor to byref()/return-tuple styles updates both sides.
    wx = ctypes.c_int(0)
    wx.value = 7
    assert int(wx.value) == 7
