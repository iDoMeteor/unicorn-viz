"""Now Spinning overlay tests — card raster, text wrapping, toggle surface."""
from __future__ import annotations

from unicornviz.now_spinning import NowSpinningOverlay, _two_lines


def _card(snap):
    ov = NowSpinningOverlay.__new__(NowSpinningOverlay)   # skip GL __init__
    ov._font_b = ov._font_s = __import__('PIL.ImageFont', fromlist=['x']).load_default()
    return ov._build_card(snap)


def test_two_line_wrap_trims_at_the_same_width() -> None:
    assert _two_lines('Short', 22) == ['Short']
    lines = _two_lines('Katy Perry California Gurls Extended Club Mix', 22)
    assert len(lines) == 2
    assert all(len(li) <= 22 for li in lines)
    assert lines[1].endswith('…')
    assert _two_lines('', 22) == []


def test_card_rasterizes_with_two_line_title() -> None:
    img = _card({'title': 'California Gurls Extended Anthem Mix',
                 'artist': 'Katy Perry ft Snoop Dogg and Friends',
                 'position_s': 42.0, 'duration_s': 215.0})
    assert img.size == (360, 150)
    assert img.getbbox() is not None


def test_perimeter_point_walks_all_four_edges() -> None:
    ov = NowSpinningOverlay.__new__(NowSpinningOverlay)
    pts = [ov._perimeter_point(t / 8.0, 0, 0, 80, 40) for t in range(8)]
    xs = {int(p[0]) for p in pts}
    ys = {int(p[1]) for p in pts}
    assert 0 in ys and 40 in ys and 0 in xs and 80 in xs   # touches every edge


def test_vj_api_toggle_surface() -> None:
    from unicornviz.vj_api import VJApi

    class _App:
        now_spinning_enabled = True

    api = VJApi.__new__(VJApi)
    api._app = _App()
    assert api.now_spinning_enabled is True
    assert api.toggle_now_spinning() is False
    assert api.set_now_spinning(True) is True
