"""Now Spinning overlay tests — card raster, text wrapping, toggle surface,
and the crossfade track-identity debounce."""
from __future__ import annotations

from unicornviz.now_spinning import (
    NowSpinningOverlay,
    TrackStabilityFilter,
    _two_lines,
)


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


# --------------------------------------------------------------------------- #
# TrackStabilityFilter — crossfade flicker guard
# --------------------------------------------------------------------------- #

_A = {'title': 'Track A', 'artist': 'DJ One', 'position_s': 10.0}
_B = {'title': 'Track B', 'artist': 'DJ Two', 'position_s': 3.0}


def test_filter_first_track_shows_instantly() -> None:
    f = TrackStabilityFilter(hold_s=5.0)
    assert f.update('mixer', _A, now=0.0) is _A


def test_filter_same_track_updates_flow_through() -> None:
    f = TrackStabilityFilter(hold_s=5.0)
    f.update('mixer', _A, now=0.0)
    fresher = dict(_A, position_s=11.0)
    assert f.update('mixer', fresher, now=0.5) is fresher


def test_filter_crossfade_flapping_never_commits() -> None:
    f = TrackStabilityFilter(hold_s=5.0)
    f.update('mixer', _A, now=0.0)
    # 20 s of A/B dominance flapping every 2 s: B never lasts hold_s
    # continuously, so the card shows A the whole way through.
    t = 0.0
    for i in range(10):
        t += 2.0
        snap = _B if i % 2 == 0 else _A
        shown = f.update('mixer', snap, now=t)
        assert shown.get('title') == 'Track A', f't={t}'


def test_filter_commits_after_continuous_hold() -> None:
    f = TrackStabilityFilter(hold_s=5.0)
    f.update('mixer', _A, now=0.0)
    assert f.update('mixer', _B, now=1.0).get('title') == 'Track A'
    assert f.update('mixer', _B, now=4.0).get('title') == 'Track A'
    assert f.update('mixer', _B, now=6.0).get('title') == 'Track B'
    # ...and stays committed.
    assert f.update('mixer', _B, now=6.5).get('title') == 'Track B'


def test_filter_bounce_back_restarts_the_challenger_clock() -> None:
    f = TrackStabilityFilter(hold_s=5.0)
    f.update('mixer', _A, now=0.0)
    f.update('mixer', _B, now=1.0)   # B challenges at t=1
    f.update('mixer', _A, now=4.0)   # A returns: challenge cancelled
    # B again at t=5; 5s of continuous B now needed from here.
    assert f.update('mixer', _B, now=5.0).get('title') == 'Track A'
    assert f.update('mixer', _B, now=9.0).get('title') == 'Track A'
    assert f.update('mixer', _B, now=10.5).get('title') == 'Track B'


def test_filter_source_change_is_an_identity_change() -> None:
    f = TrackStabilityFilter(hold_s=5.0)
    f.update('mixer', _A, now=0.0)
    same_track_other_source = dict(_A)
    assert f.update('spotify', same_track_other_source, now=1.0) is not \
        same_track_other_source  # debounced like any other switch


def test_filter_reset_forgets_and_shows_next_instantly() -> None:
    f = TrackStabilityFilter(hold_s=5.0)
    f.update('mixer', _A, now=0.0)
    f.reset()  # playback stopped, card hidden
    assert f.update('mixer', _B, now=100.0) is _B


def test_filter_zero_hold_disables_the_debounce() -> None:
    f = TrackStabilityFilter(hold_s=0.0)
    f.update('mixer', _A, now=0.0)
    assert f.update('mixer', _B, now=0.1) is _B


def test_vj_api_toggle_surface() -> None:
    from unicornviz.vj_api import VJApi

    class _App:
        now_spinning_enabled = True

    api = VJApi.__new__(VJApi)
    api._app = _App()
    assert api.now_spinning_enabled is True
    assert api.toggle_now_spinning() is False
    assert api.set_now_spinning(True) is True
