"""Regression tests for banner-01's 0.9.0 rewrite: multi-line fade cycling
in place of horizontal scroll, and a per-line character cap enforced while
typing.

GL-dependent (BannerController owns real moderngl program/buffer/vao/texture
objects) -- uses a headless standalone context, same pattern as
drop-ins/beat-flash-01/tests/test_controller.py, and skips cleanly where no
GPU/driver is available.
"""
from __future__ import annotations

import types

import pytest

from unicornviz.dropins import load_dropin_symbol

BannerController = load_dropin_symbol('banner-01/banner_controller.py', 'BannerController')


class _FakeVJApi:
    """Just enough VJApi surface for BannerController's __init__ and use."""

    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self._state: dict[str, object] = {}
        self._text_handlers: dict[str, object] = {}

    def register_midi_actions(self, section, actions) -> None:
        pass

    def register_midi_action_handler(self, action, fn) -> None:
        pass

    def get_runtime_state(self, dotted_path: str = '', default=None):
        return self._state.get(dotted_path, default)

    def set_runtime_state(self, dotted_path: str, value) -> bool:
        self._state[dotted_path] = value
        return True

    def register_text_input_handler(self, name, fn) -> None:
        self._text_handlers[name] = fn

    def unregister_text_input_handler(self, name) -> None:
        self._text_handlers.pop(name, None)

    def start_text_input(self) -> None:
        pass

    def stop_text_input(self) -> None:
        pass


class _FakeApp:
    def __init__(self, ctx) -> None:
        self.vj_api = _FakeVJApi(ctx)


@pytest.fixture
def ctx():
    moderngl = pytest.importorskip('moderngl')
    try:
        c = moderngl.create_standalone_context()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f'no headless GL context: {exc}')
    yield c
    c.release()


def _banner(ctx, cfg=None) -> 'BannerController':
    return BannerController(_FakeApp(ctx), cfg or {})


def _audio(bass=0.0, mid=0.0, treble=0.0, beat=0.0):
    return types.SimpleNamespace(bass_n=bass, mid_n=mid, treble_n=treble, beat=beat)


# --------------------------------------------------------------- default text

def test_default_text_reflows_to_default_max_line_chars(ctx) -> None:
    b = _banner(ctx)
    try:
        lines = b._text.split('\n')
        assert lines, 'default text produced no lines'
        assert all(len(ln) <= 100 for ln in lines)
        assert any(ln.strip() for ln in lines)
    finally:
        b.shutdown()


def test_default_text_reflows_to_a_custom_max_line_chars(ctx) -> None:
    b = _banner(ctx, {'max_line_chars': 40})
    try:
        lines = b._text.split('\n')
        assert lines
        assert all(len(ln) <= 40 for ln in lines)
    finally:
        b.shutdown()


def test_max_line_chars_clamped_to_valid_range(ctx) -> None:
    b = _banner(ctx, {'max_line_chars': 5})
    try:
        assert b._max_line_chars == 20  # _MIN_LINE_CHARS
    finally:
        b.shutdown()
    b2 = _banner(ctx, {'max_line_chars': 9999})
    try:
        assert b2._max_line_chars == 200  # _MAX_LINE_CHARS
    finally:
        b2.shutdown()


# ------------------------------------------------------------- typing cap

def test_typed_line_is_hard_capped_at_max_line_chars(ctx) -> None:
    b = _banner(ctx, {'max_line_chars': 20, 'text': 'x'})
    try:
        b._cursor = len(b._text)
        b._tf_insert('a' * 30)
        lines = b._text.split('\n')
        assert all(len(ln) <= 20 for ln in lines)
        # 'x' plus as many 'a's as fit in the 20-char cap.
        assert lines[0] == 'x' + 'a' * 19
    finally:
        b.shutdown()


def test_newline_starts_a_fresh_capped_line(ctx) -> None:
    b = _banner(ctx, {'max_line_chars': 20, 'text': ''})
    try:
        b._text = ''
        b._cursor = 0
        b._tf_insert('a' * 25 + 'XX' + '\n' + 'b' * 25 + 'YY')
        lines = b._text.split('\n')
        assert len(lines) == 2
        assert lines[0] == 'a' * 20   # extra a's and 'XX' dropped, line at cap
        assert lines[1] == 'b' * 20   # extra b's and 'YY' dropped on the new line too
    finally:
        b.shutdown()


def test_inserting_mid_line_respects_existing_suffix_length(ctx) -> None:
    """Cap accounts for text already sitting after the cursor, not just
    the prefix -- otherwise inserting mid-line could blow past the cap."""
    b = _banner(ctx, {'max_line_chars': 20, 'text': ''})
    try:
        b._text = 'a' * 18   # 18 chars, cursor at start
        b._cursor = 0
        b._tf_insert('XY')  # would make 20 chars total -- exactly at cap
        assert b._text == 'XY' + 'a' * 18
        b._cursor = 0
        b._tf_insert('Z')  # now at 21 -- must be dropped, cap already hit
        assert b._text == 'XY' + 'a' * 18
    finally:
        b.shutdown()


# --------------------------------------------------------- max_line_chars set

def test_lowering_max_line_chars_reflows_existing_text(ctx) -> None:
    b = _banner(ctx, {'max_line_chars': 100, 'text': 'a' * 80})
    try:
        assert b._text == 'a' * 80
        b._set_max_line_chars(20)
        lines = b._text.split('\n')
        assert all(len(ln) <= 20 for ln in lines)
        assert ''.join(lines) == 'a' * 80   # content preserved, just reflowed
    finally:
        b.shutdown()


# ------------------------------------------------------------------ reset

def test_ctrl_r_reset_rebuilds_default_text_at_current_cap(ctx) -> None:
    import sdl2

    b = _banner(ctx, {'max_line_chars': 30})
    try:
        b._show_config = True
        b._text = 'whatever was typed'
        result = b.handle_key(sdl2.SDLK_r, sdl2.KMOD_CTRL)
        assert result == 'Banner text reset'
        lines = b._text.split('\n')
        assert all(len(ln) <= 30 for ln in lines)
    finally:
        b.shutdown()


# --------------------------------------------------------------- fade cycle

def test_current_line_fade_is_zero_with_no_displayable_lines(ctx) -> None:
    b = _banner(ctx)
    try:
        b._text = '   \n   '
        line, frac = b._current_line_fade()
        assert line == ''
        assert frac == 0.0
    finally:
        b.shutdown()


def test_display_lines_skips_blank_lines(ctx) -> None:
    b = _banner(ctx)
    try:
        b._text = 'first\n\n   \nsecond'
        assert b._display_lines() == ['first', 'second']
    finally:
        b.shutdown()


def test_line_fade_ramps_up_then_down_over_the_cycle(ctx) -> None:
    b = _banner(ctx)
    try:
        b._text = 'one\ntwo'
        b._enabled = True

        _, frac_start = b._current_line_fade()
        assert frac_start == pytest.approx(0.0, abs=1e-6)

        b.update(0.5, _audio())  # halfway through the 1s fade-in
        _, frac_mid_in = b._current_line_fade()
        assert 0.0 < frac_mid_in < 1.0

        b.update(1.0, _audio())  # now well into the hold
        _, frac_hold = b._current_line_fade()
        assert frac_hold == pytest.approx(1.0, abs=1e-6)

        b.update(2.2, _audio())  # past hold (ends at t=3.6), into fade-out
        _, frac_out = b._current_line_fade()
        assert 0.0 <= frac_out < 1.0
    finally:
        b.shutdown()


def test_line_index_advances_after_a_full_cycle(ctx) -> None:
    b = _banner(ctx)
    try:
        b._text = 'one\ntwo\nthree'
        b._enabled = True
        assert b._line_idx == 0

        cycle_len = 2.0 * 1.0 + 2.6  # _FADE_S*2 + _LINE_HOLD_S
        b.update(cycle_len + 0.01, _audio())
        assert b._line_idx == 1
    finally:
        b.shutdown()


# ------------------------------------------------------------- persistence

def test_persist_runtime_state_includes_max_line_chars_not_scroll_speed(ctx) -> None:
    b = _banner(ctx, {'max_line_chars': 55})
    try:
        b._persist_runtime_state()
        payload = b._vj_api._state['banner']
        assert payload['max_line_chars'] == 55
        assert 'scroll_speed' not in payload
    finally:
        b.shutdown()


def test_apply_state_payload_restores_and_clamps_max_line_chars(ctx) -> None:
    b = _banner(ctx)
    try:
        b._apply_state_payload({'max_line_chars': 9999, 'text': 'hi'})
        assert b._max_line_chars == 200
    finally:
        b.shutdown()


# --------------------------------------------------------------- hotkeys

def test_left_right_in_config_modal_adjust_max_line_chars(ctx) -> None:
    import sdl2

    b = _banner(ctx, {'max_line_chars': 100})
    try:
        b._show_config = True
        result = b.handle_key(sdl2.SDLK_LEFT, 0)
        assert b._max_line_chars == 90
        assert result == 'Banner max line: 90ch'

        result = b.handle_key(sdl2.SDLK_RIGHT, 0)
        assert b._max_line_chars == 100
        assert result == 'Banner max line: 100ch'
    finally:
        b.shutdown()


def test_scroll_speed_attribute_no_longer_exists(ctx) -> None:
    b = _banner(ctx)
    try:
        assert not hasattr(b, '_scroll_speed')
        assert not hasattr(b, '_offset_px')
    finally:
        b.shutdown()
