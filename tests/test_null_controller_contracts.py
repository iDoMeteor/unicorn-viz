"""Tests: null-controller contract conformance (B4).

Every null/fallback controller in app.py must implement the complete set of
methods and properties that app.py calls on it.  A missing method on a null
controller causes an AttributeError at runtime, not a clean degraded state.

This test statically verifies each null class has the full required surface.
No GL context is needed since it only inspects method/attribute presence and
calls methods with dummy arguments to confirm they don't raise.
"""
from __future__ import annotations

import pytest

# Import the null classes directly from app.py
from unicornviz.app import (
    _NullWebcamSystem,
    _NullRTMPStreamer,
    _NullPostFxController,
)


# ---------------------------------------------------------------------------
# Required method/attribute surfaces extracted from app.py call sites
# ---------------------------------------------------------------------------

_WEBCAM_REQUIRED = [
    'start',
    'render',
    'destroy',
    'resize',
    'scale_pip',
    'set_layout',
    'next_treatment',
    'prev_treatment',
    'toggle_auto_cycle',
]

_STREAMER_REQUIRED = [
    'is_streaming',  # property
    'last_error',    # property
    'destination_label',  # property
    'enabled',       # attribute
    'auto_start',    # attribute
    'start',
    'stop',
    'write_frame',
    'resize',
    'set_provider',
]

_POSTFX_REQUIRED = [
    'is_active',
    'apply',
    'resize',
    'destroy',
    'on_scroll',
    'on_ctrl_scroll',
    'on_ctrl_scroll_degrees',
    'clear_hue_shift',
    'clear_scroll_fx',
    'clear_active_slot',
    'select_slot',
    'friend_pairs',
    'active_slot',   # attribute
    'is_hue_active', # property
    'is_rotation_active',  # property
    'active_name',   # property
]


# ---------------------------------------------------------------------------
# Presence tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('attr', _WEBCAM_REQUIRED)
def test_null_webcam_has_required_attr(attr: str) -> None:
    """_NullWebcamSystem must expose every attribute/method app.py calls."""
    assert hasattr(_NullWebcamSystem, attr) or hasattr(_NullWebcamSystem(None, 1, 1), attr), \
        f'_NullWebcamSystem is missing required attribute: {attr!r}'


@pytest.mark.parametrize('attr', _STREAMER_REQUIRED)
def test_null_streamer_has_required_attr(attr: str) -> None:
    """_NullRTMPStreamer must expose every attribute/method app.py calls."""
    instance = _NullRTMPStreamer({}, 1920, 1080)
    assert hasattr(instance, attr), \
        f'_NullRTMPStreamer is missing required attribute: {attr!r}'


@pytest.mark.parametrize('attr', _POSTFX_REQUIRED)
def test_null_postfx_has_required_attr(attr: str) -> None:
    """_NullPostFxController must expose every attribute/method app.py calls."""
    instance = _NullPostFxController(None, 1920, 1080)
    assert hasattr(instance, attr), \
        f'_NullPostFxController is missing required attribute: {attr!r}'


# ---------------------------------------------------------------------------
# Call-without-raise smoke tests
# ---------------------------------------------------------------------------

def test_null_webcam_methods_do_not_raise() -> None:
    c = _NullWebcamSystem(None, 640, 480)
    c.start()
    c.render(0.016, 0.5, 0.3)
    c.resize(1280, 720)
    c.scale_pip(0.1)
    c.set_layout('single')
    c.next_treatment()
    c.prev_treatment()
    c.toggle_auto_cycle()
    c.destroy()


def test_null_streamer_methods_do_not_raise() -> None:
    c = _NullRTMPStreamer({}, 1920, 1080)
    _ = c.is_streaming
    _ = c.last_error
    _ = c.destination_label
    _ = c.enabled
    _ = c.auto_start
    c.start()
    c.write_frame(b'\x00' * 6)
    c.stop()
    c.resize(1280, 720)
    c.set_provider('rtmp://localhost/test')


def test_null_postfx_methods_do_not_raise() -> None:
    c = _NullPostFxController(None, 1920, 1080)
    c.is_active()
    c.on_scroll(1)
    c.on_ctrl_scroll(1)
    c.on_ctrl_scroll_degrees(15.0)
    c.clear_hue_shift()
    c.clear_scroll_fx()
    c.clear_active_slot()
    c.select_slot(0)
    c.friend_pairs()
    c.resize(1280, 720)
    c.destroy()
    _ = c.active_slot
    _ = c.is_hue_active
    _ = c.is_rotation_active
    _ = c.active_name
