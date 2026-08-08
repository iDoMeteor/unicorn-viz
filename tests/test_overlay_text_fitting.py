"""Selector label fitting — trim the middle, never the tail.

Audio device names differ at *both* ends: 'DDJ-REV1 Analog Stereo' vs
'DDJ-REV1 Analog Surround 4.0'.  Tail-truncating them renders two distinct
devices as the same row, and the trailing digits are often the only thing
distinguishing several instances of one device.
"""
from __future__ import annotations

from unicornviz.overlays import Overlays


class _Ov:
    """Overlays instance without GL: only the metrics matter here."""
    _glyph_w = 8
    _font_scale_norm = 1.0
    _char_width = Overlays._char_width
    _fit_text = Overlays._fit_text


def _ov() -> _Ov:
    return _Ov()


def test_short_text_is_untouched() -> None:
    o = _ov()
    assert o._fit_text('DDJ-REV1', 1.0, 800.0) == 'DDJ-REV1'


def test_long_text_keeps_head_and_tail() -> None:
    o = _ov()
    # 20 glyphs of room at 8px/glyph.
    out = o._fit_text('USB-A-C To Dual HDMI 4K Graphic Adapter', 1.0, 160.0)
    assert len(out) <= 20
    assert out.startswith('USB-A-C')
    assert out.endswith('ter')
    assert '..' in out


def test_the_distinguishing_tail_survives() -> None:
    """The whole point: '4.0' must not be what gets cut."""
    o = _ov()
    a = o._fit_text('DDJ-REV1 Analog Surround 4.0', 1.0, 120.0)
    b = o._fit_text('DDJ-REV1 Analog Stereo', 1.0, 120.0)
    assert a.endswith('4.0')
    assert a != b, 'two different devices must not render identically'


def test_keep_tail_is_configurable() -> None:
    o = _ov()
    out = o._fit_text('abcdefghijklmnopqrstuvwxyz', 1.0, 80.0, keep_tail=5)
    assert out.endswith('vwxyz')


def test_absurdly_narrow_space_favours_the_tail() -> None:
    o = _ov()
    out = o._fit_text('abcdefghijklmnop', 1.0, 32.0)
    assert len(out) <= 4
    assert out.endswith('nop')


def test_zero_width_degrades_to_a_no_op() -> None:
    """A degenerate panel width must not blank the row or raise.

    Returning the untouched label is the safer failure: an unreadably wide
    row still says which device it is, an empty one says nothing.
    """
    o = _ov()
    assert o._fit_text('anything', 1.0, 0.0) == 'anything'
