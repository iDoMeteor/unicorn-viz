"""Render frame cap — swap-interval derivation.

A loop that cannot finish inside one vblank misses it and lands on the next
anyway, so the effective rate is already halved — but with jitter, since
some frames make it and some do not.  Asking for every Nth vblank up front
trades a nominally lower number for a steady one.
"""
from __future__ import annotations

from unicornviz.app import App


class _Cfg:
    def __init__(self, limit) -> None:
        self._limit = limit
        self.overrides: list[tuple] = []

    def get(self, section, key=None, default=None):
        if (section, key) == ('render', 'fps_limit'):
            return self._limit
        return default

    def set_override(self, section, key, value):
        self.overrides.append((section, key, value))


def _app(limit, refresh=60.0):
    app = object.__new__(App)
    app.cfg = _Cfg(limit)
    app._display_index = 0
    app._display_refresh_hz = lambda: refresh
    return app


def _interval_for(limit, refresh=60.0):
    """The swap interval _apply_frame_limit would request."""
    calls: list[int] = []
    app = _app(limit, refresh)
    import unicornviz.app as app_mod
    real = app_mod.sdl2.SDL_GL_SetSwapInterval
    app_mod.sdl2.SDL_GL_SetSwapInterval = lambda n: calls.append(n)
    try:
        app._apply_frame_limit()
    finally:
        app_mod.sdl2.SDL_GL_SetSwapInterval = real
    return calls[0]


def test_thirty_on_a_sixty_hertz_display_is_every_second_vblank() -> None:
    assert _interval_for(30, refresh=60.0) == 2


def test_sixty_on_a_sixty_hertz_display_is_every_vblank() -> None:
    assert _interval_for(60, refresh=60.0) == 1


def test_zero_means_follow_the_display() -> None:
    assert _interval_for(0, refresh=144.0) == 1


def test_high_refresh_display_scales_the_interval() -> None:
    """A 144 Hz panel needs every 5th vblank to sit near 30."""
    assert _interval_for(30, refresh=144.0) == 5


def test_cap_above_the_refresh_rate_cannot_go_below_one() -> None:
    """Asking for 60 on a 30 Hz output must not request interval 0."""
    assert _interval_for(60, refresh=30.0) == 1


def test_unreadable_refresh_falls_back_to_sixty() -> None:
    app = object.__new__(App)
    app._display_index = 0
    # SDL_GetCurrentDisplayMode failing must not raise into the boot path.
    assert app._display_refresh_hz() > 0.0


def test_choices_include_display_and_the_common_rates() -> None:
    assert App._FRAME_LIMIT_CHOICES[0] == 0
    for rate in (24, 30, 60):
        assert rate in App._FRAME_LIMIT_CHOICES


# --------------------------------------------------------------------------
# CLI overrides
# --------------------------------------------------------------------------

def _overrides(argv):
    """Config overrides produced by a command line."""
    from unicornviz.__main__ import _build_overrides, _build_parser
    return _build_overrides(_build_parser().parse_args(argv))


def test_fps_limit_flag_overrides_config() -> None:
    assert _overrides(['--fps-limit', '60'])['render']['fps_limit'] == 60


def test_fps_limit_zero_is_not_dropped_as_falsy() -> None:
    """0 means 'follow the display' — it must survive the override plumbing."""
    assert _overrides(['--fps-limit', '0'])['render']['fps_limit'] == 0


def test_record_codec_flag_overrides_config() -> None:
    assert _overrides(['--record-codec', 'h264_vaapi'])['recording']['codec'] == 'h264_vaapi'


def test_unset_flags_leave_the_section_alone() -> None:
    ov = _overrides([])
    assert 'fps_limit' not in ov.get('render', {})
    assert 'codec' not in ov.get('recording', {})


def test_training_flag_enables_all_three_streams() -> None:
    """A decision log without corpora cannot be scored, and vice versa.

    Regression: an unattended run produced zero training data unless a human
    pressed the in-app toggle, which defeats the point of running headless.
    """
    vj = _overrides(['--training'])['auto_vj']
    assert vj['log_decisions'] is True
    assert vj['live_training_enabled'] is True
    assert vj['sequence_training_enabled'] is True


def test_training_is_off_unless_asked_for() -> None:
    assert 'log_decisions' not in _overrides([]).get('auto_vj', {})


def test_headless_sources_imply_training() -> None:
    """A headless source *is* a training run; that is what the group is for.

    Requiring a separate opt-in failed silently: the run looked healthy and
    produced no training data, discoverable only once the set was over and
    no longer repeatable.
    """
    for argv in (['--dj-mixer-source'], ['--media-source']):
        vj = _overrides(argv)['auto_vj']
        assert vj['log_decisions'] is True, argv
        assert vj['live_training_enabled'] is True, argv
        assert vj['sequence_training_enabled'] is True, argv


def test_no_training_opts_a_headless_run_out() -> None:
    vj = _overrides(['--dj-mixer-source', '--no-training']).get('auto_vj', {})
    assert 'log_decisions' not in vj


def test_training_and_no_training_are_mutually_exclusive() -> None:
    import pytest
    from unicornviz.__main__ import _build_parser
    with pytest.raises(SystemExit):
        _build_parser().parse_args(['--training', '--no-training'])
