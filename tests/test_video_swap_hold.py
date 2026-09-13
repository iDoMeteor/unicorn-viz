"""Music-video decks, auto-vj-01 piece (director rc.22): the swap-hold
gate, section 4 of docs/planning/music-video-decks-plan-2026-09-13.md.

While a visible video-deck layer's opacity is >= `video_swap_hold_opacity`
(0.9 default, core-owned `[video_decks] swap_hold_opacity` read first),
effect swaps and ping-pong transitions are held -- nobody can see either
happen under an opaque video, and a swap still instantiates GL resources
for nothing. The mode/phrase clock, drop/impact postfx, scroll effects,
and the recommender all keep running unchanged; a held ping-pong swap
resets its own beat counter (not deferred) so opacity dropping back below
threshold resumes normal timing instead of firing an immediate catch-up
swap.

Uses bare controller instances, mirroring test_auto_vj_pingpong_pinning.py
and test_director_bass_delta_and_rel_confidence.py's style.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

_AUTO_VJ = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_SPEC = importlib.util.spec_from_file_location('test_video_swap_hold_auto_vj', _AUTO_VJ)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules['test_video_swap_hold_auto_vj'] = _MOD
_SPEC.loader.exec_module(_MOD)
AutoVJController = _MOD.AutoVJController
_SRC = _AUTO_VJ.read_text(encoding='utf-8')


class _FakeVjApiWithVideo:
    def __init__(self, opacity: float) -> None:
        self._opacity = opacity

    def get_video_layer_opacity(self) -> float:
        return self._opacity


class _FakeVjApiRaises:
    def get_video_layer_opacity(self) -> float:
        raise RuntimeError('boom')


class _Grid:
    is_beat = False


def _bare(*, opacity_fn=None, threshold: float = 0.9,
          profile_allow_swap: bool = True, secs_since_change: float = 0.0) -> AutoVJController:
    c = object.__new__(AutoVJController)
    c._app = SimpleNamespace(vj_api=opacity_fn if opacity_fn is not None else SimpleNamespace())
    c._video_swap_hold_opacity = threshold
    c._video_swap_hold_opacity_source = 'core'
    c._profile_allow_swap = profile_allow_swap
    c._allow_swap = profile_allow_swap
    c._video_swap_held = False
    c._video_swap_hold_ticks = 0
    c._secs_since_change = secs_since_change
    return c


# ---------------------------------------------------------------------------
# _get_video_layer_opacity() -- defensive wrapper
# ---------------------------------------------------------------------------

def test_opacity_zero_when_vj_api_lacks_method() -> None:
    c = _bare()
    assert c._get_video_layer_opacity() == 0.0


def test_opacity_zero_when_vj_api_raises() -> None:
    c = _bare(opacity_fn=_FakeVjApiRaises())
    assert c._get_video_layer_opacity() == 0.0


def test_opacity_reads_real_value() -> None:
    c = _bare(opacity_fn=_FakeVjApiWithVideo(0.42))
    assert c._get_video_layer_opacity() == 0.42


# ---------------------------------------------------------------------------
# _refresh_video_swap_hold() -- the gate itself
# ---------------------------------------------------------------------------

def test_below_threshold_does_not_hold() -> None:
    c = _bare(opacity_fn=_FakeVjApiWithVideo(0.5), threshold=0.9)
    c._refresh_video_swap_hold()
    assert c._video_swap_held is False
    assert c._allow_swap is True
    assert c._video_swap_hold_ticks == 0


def test_at_or_above_threshold_holds() -> None:
    c = _bare(opacity_fn=_FakeVjApiWithVideo(0.9), threshold=0.9)
    c._refresh_video_swap_hold()
    assert c._video_swap_held is True
    assert c._allow_swap is False
    assert c._video_swap_hold_ticks == 1

    c2 = _bare(opacity_fn=_FakeVjApiWithVideo(1.0), threshold=0.9)
    c2._refresh_video_swap_hold()
    assert c2._video_swap_held is True
    assert c2._allow_swap is False


def test_held_state_does_not_override_a_profile_that_already_disallows_swap() -> None:
    """The gate ANDs with the per-mood setting, never overrides it the
    other way -- a mood with allow_effect_swap=False stays swap-off
    regardless of video opacity."""
    c = _bare(opacity_fn=_FakeVjApiWithVideo(0.0), threshold=0.9, profile_allow_swap=False)
    c._refresh_video_swap_hold()
    assert c._video_swap_held is False
    assert c._allow_swap is False


def test_suppressed_count_increments_once_per_held_tick() -> None:
    c = _bare(opacity_fn=_FakeVjApiWithVideo(0.95), threshold=0.9)
    c._refresh_video_swap_hold()
    c._refresh_video_swap_hold()
    c._refresh_video_swap_hold()
    assert c._video_swap_hold_ticks == 3


def test_resuming_below_threshold_restores_allow_swap() -> None:
    c = _bare(opacity_fn=_FakeVjApiWithVideo(0.95), threshold=0.9, profile_allow_swap=True)
    c._refresh_video_swap_hold()
    assert c._allow_swap is False

    c._app.vj_api._opacity = 0.1
    c._refresh_video_swap_hold()
    assert c._video_swap_held is False
    assert c._allow_swap is True


# ---------------------------------------------------------------------------
# Peer review catch: _run_cruise_actions()'s own swap timer
# (_secs_since_change >= _next_swap_at) is _allow_swap-gated, but
# _secs_since_change itself accumulates every tick UNCONDITIONALLY
# (near the top of update()), including while held -- so without a
# reset, releasing the hold could fire an immediate catch-up swap the
# same tick, exactly what the ticket said to avoid.
# ---------------------------------------------------------------------------

def test_secs_since_change_untouched_while_engaging_and_staying_held() -> None:
    c = _bare(opacity_fn=_FakeVjApiWithVideo(0.95), threshold=0.9, secs_since_change=1.0)
    c._refresh_video_swap_hold()  # engage
    assert c._secs_since_change == 1.0
    c._app.vj_api._opacity = 0.99
    c._refresh_video_swap_hold()  # still held
    assert c._secs_since_change == 1.0


def test_secs_since_change_resets_on_release_no_catch_up_swap() -> None:
    """held for well past a normal swap interval, then released -- the
    timer must restart from 0, not fire the instant the hold lifts."""
    c = _bare(opacity_fn=_FakeVjApiWithVideo(0.95), threshold=0.9, secs_since_change=0.0)
    c._refresh_video_swap_hold()  # engage
    c._secs_since_change = 500.0  # simulates many held ticks accumulating past _next_swap_at
    c._app.vj_api._opacity = 0.1
    c._refresh_video_swap_hold()  # release
    assert c._video_swap_held is False
    assert c._allow_swap is True
    assert c._secs_since_change == 0.0  # reset, not 500.0 -- no catch-up swap this tick


# ---------------------------------------------------------------------------
# _run_pingpong_tick() -- the second suppression path (not _allow_swap-gated)
# ---------------------------------------------------------------------------

def _bare_pingpong(*, video_swap_held: bool, pp_kind: str = 'effect') -> AutoVJController:
    c = object.__new__(AutoVJController)
    c._grid = _Grid()
    c._pp_kind = pp_kind
    c._pp_beat_count = 0
    c._pp_beats = 4
    c._preset_pp_beats = 4
    c._video_swap_held = video_swap_held
    c.swap_calls = 0
    c._run_pingpong_swap = lambda: setattr(c, 'swap_calls', c.swap_calls + 1)  # type: ignore[attr-defined]
    return c


def test_pingpong_swaps_normally_when_not_held() -> None:
    """_run_pingpong_swap is stubbed here to isolate the hold decision --
    its own beat_count reset (real code, unstubbed) is covered by
    test_auto_vj_pingpong_pinning.py; this only pins that a real swap
    call happens, not held/reset by this gate."""
    c = _bare_pingpong(video_swap_held=False)
    for _ in range(4):
        c._grid.is_beat = True
        c._run_pingpong_tick()
    assert c.swap_calls == 1


def test_pingpong_holds_and_resets_counter_instead_of_swapping() -> None:
    c = _bare_pingpong(video_swap_held=True)
    for _ in range(4):
        c._grid.is_beat = True
        c._run_pingpong_tick()
    assert c.swap_calls == 0
    assert c._pp_beat_count == 0  # reset, not left >= threshold


def test_pingpong_no_catch_up_burst_when_hold_releases() -> None:
    """A queued swap that gets held must not fire the instant opacity
    drops back below threshold -- the reset counter means a fresh full
    beat_threshold has to elapse again, same as normal ping-pong timing."""
    c = _bare_pingpong(video_swap_held=True)
    for _ in range(4):
        c._grid.is_beat = True
        c._run_pingpong_tick()
    assert c.swap_calls == 0

    c._video_swap_held = False
    c._grid.is_beat = True
    c._run_pingpong_tick()
    assert c.swap_calls == 0  # only 1 beat elapsed since the reset, not 4
    assert c._pp_beat_count == 1


# ---------------------------------------------------------------------------
# Config source: core's [video_decks] swap_hold_opacity first, own key
# as fallback -- verified as source shape, matching test_gate_config_is_
# global_cfg_read's style in test_director_bass_delta_and_rel_confidence.py.
# ---------------------------------------------------------------------------

def test_threshold_reads_core_config_first_with_own_key_fallback() -> None:
    assert "self._app.cfg.get('video_decks', 'swap_hold_opacity'" in _SRC
    assert "_cfg.get('video_swap_hold_opacity'" in _SRC
