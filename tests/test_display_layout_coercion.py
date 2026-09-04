"""Display layouts from the multi-head drop-in must reach _width as ints.

Regression for "FireDJCelebration unavailable: int() argument must be a
string, a bytes-like object or a real number, not 'NoneType'" (2026-09-04).

That message came from three call frames away: ``VJApi.render_width`` does a
bare ``int(self._app._width)``, and ``_width`` had been assigned a raw element
of a drop-in-supplied layout tuple whose width was None -- which is what a
display that disappears mid-session can produce.  ``_width``/``_height`` are
declared ints and every consumer treats them as numbers, so core has to
enforce that at the boundary rather than trust the drop-in's shape.
"""
from __future__ import annotations

import logging
import types

import pytest

from unicornviz.app import App
from unicornviz.vj_api import VJApi


def _app_with_layouts(layouts: list, bounds=None) -> App:
    """An App stubbed down to just the multi-head layout plumbing."""
    app = object.__new__(App)
    app._width = 1920
    app._height = 1080
    app._display_index = 0
    app._multihead = types.SimpleNamespace(
        display_layouts=layouts,
        display_index=0,
        _active_display_indices=None,
        all_display_bounds=lambda w, h: bounds,
        display_bounds=lambda idx, w, h: None,
    )
    return app


# -- the coercion helper itself ---------------------------------------------

@pytest.mark.parametrize('rect,expected', [
    ((0, 0, 1920, 1080), (0, 0, 1920, 1080)),
    ((0.0, 0.0, 1920.9, 1080.9), (0, 0, 1920, 1080)),
    (['10', '20', '640', '480'], (10, 20, 640, 480)),
])
def test_as_int_rect_coerces_numeric_layouts(rect, expected) -> None:
    assert App._as_int_rect(rect) == expected


@pytest.mark.parametrize('rect', [
    (0, 0, None, None),      # the shape that caused the reported crash
    (0, 0, 1920),            # too short to unpack
    None,                    # no layout at all
    (0, 0, 'wide', 'tall'),  # non-numeric strings
])
def test_as_int_rect_rejects_malformed_layouts(rect) -> None:
    assert App._as_int_rect(rect) is None


def test_as_int_rect_logs_what_it_rejected(caplog: pytest.LogCaptureFixture) -> None:
    """The layout has to appear in the log or this is undiagnosable."""
    with caplog.at_level(logging.WARNING, logger='unicornviz.app'):
        App._as_int_rect((0, 0, None, None))
    assert 'malformed display layout' in caplog.text


# -- the paths that feed _width ---------------------------------------------

def test_primary_layout_returns_none_rather_than_a_poisoned_tuple() -> None:
    app = _app_with_layouts([(0, 0, None, None)])
    assert app._primary_active_layout() is None


def test_primary_layout_coerces_a_usable_layout() -> None:
    app = _app_with_layouts([(0, 0, 2560.0, 1440.0)])
    assert app._primary_active_layout() == (0, 0, 2560, 1440)


def test_width_survives_a_display_that_vanished() -> None:
    """A bad layout must leave the last good size in place, not overwrite it."""
    app = _app_with_layouts([(0, 0, None, None)])
    layout = app._primary_active_layout()
    if layout is not None:                      # mirrors the call sites' guard
        app._width, app._height = layout[2], layout[3]
    assert app._width == 1920
    assert int(app._width) == 1920              # what VJApi.render_width does


def test_render_width_stays_usable_after_a_coerced_layout() -> None:
    """End to end: the property that actually raised must work again."""
    app = _app_with_layouts([(0, 0, 2560.0, 1440.0)])
    layout = app._primary_active_layout()
    app._width, app._height = layout[2], layout[3]
    api = VJApi(app)
    assert api.render_width == 2560
    assert api.render_height == 1440


def test_all_display_bounds_falls_back_when_the_dropin_returns_junk() -> None:
    app = _app_with_layouts([(0, 0, 1920, 1080)], bounds=(0, 0, None, None))
    assert app._all_display_bounds() == (0, 0, 1920, 1080)


def test_all_display_bounds_coerces_a_usable_result() -> None:
    app = _app_with_layouts([(0, 0, 1920, 1080)], bounds=(0.0, 0.0, 3840.0, 1080.0))
    assert app._all_display_bounds() == (0, 0, 3840, 1080)
