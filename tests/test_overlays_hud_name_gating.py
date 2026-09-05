"""Overlays.flash_name() with flash messages disabled -- regression tests.

render() and _render_recording_indicator() gate on ``_name_text``, which is
only ever written by flash_name().  flash_name() used to return before
writing it when ``[overlays] flash_messages = false``, so the HUD (and the
recording indicator) could never appear in that configuration.  Bare
``Overlays`` via object.__new__ -- only the attributes flash_name touches.
"""
from __future__ import annotations

from unicornviz.overlays import Overlays


def _bare(flash_enabled: bool) -> Overlays:
    ov = Overlays.__new__(Overlays)
    ov._flash_enabled = flash_enabled
    ov._name_text = ''
    ov._flash_text = ''
    ov._flash_timer = 0.0
    return ov


def test_flash_name_records_name_text_when_flashes_are_disabled() -> None:
    ov = _bare(flash_enabled=False)
    ov.flash_name('Plasma', 3.0)
    assert ov._name_text == 'Plasma'
    # Only the transient flash is suppressed.
    assert ov._flash_text == ''
    assert ov._flash_timer == 0.0


def test_flash_name_sets_everything_when_flashes_are_enabled() -> None:
    ov = _bare(flash_enabled=True)
    ov.flash_name('Plasma', 2.5)
    assert ov._name_text == 'Plasma'
    assert ov._flash_text == '>> Plasma'
    assert ov._flash_timer == 2.5


def test_hud_gate_predicate_passes_with_flashes_disabled() -> None:
    # The exact expression render() uses to decide whether to draw the HUD.
    ov = _bare(flash_enabled=False)
    ov._show_name = True
    ov.flash_name('Plasma')
    assert bool(ov._show_name and ov._name_text)
