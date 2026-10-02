"""B P2-4 (audit 2026-09-30): transitions hid under Candy Frame, Rainbow Nova
and the Grand Finale overlay.

During a transition ``_render`` blended A and B straight to the screen unless
mirror mode, a post chain or video decks were active.  The late overlays then
draw from ``fbo_a``, which at that point held only the OUTGOING effect; Candy
Frame composites with ``ONE, ZERO`` and replaces the whole picture, so with it
(or Nova, or the finale overlay) on and no post-FX every transition showed the
old effect until it snapped to the new one.  The no-transition branch already
routed through ``fbo_a`` for those three; the transition branch did not.

These tests run the real ``_render`` / ``_frame_overlay_steps`` against a
recording fake GL: each framebuffer carries a content label, and what an
overlay samples is checked at the moment it draws.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from unicornviz.app import App


class _Tex:
    def __init__(self, owner, ctx) -> None:
        self.owner, self.ctx = owner, ctx

    def use(self, location: int = 0) -> None:
        self.ctx.slots[location] = self.owner


class _Fbo:
    def __init__(self, name, ctx) -> None:
        self.name, self.ctx, self.content = name, ctx, None
        self.color_attachments = [_Tex(self, ctx)]

    def use(self) -> None:
        self.ctx.bound = self


class _Ctx:
    def __init__(self) -> None:
        self.slots: dict[int, _Fbo] = {}
        self.screen = _Fbo('screen', self)
        self.bound = self.screen
        self.viewport = None
        self.scissor = None
        self.cleared: list[str] = []

    def clear(self, *_a, **_k) -> None:
        self.bound.content = None
        self.cleared.append(self.bound.name)


class _Prog(dict):
    """A shader program: any uniform name yields an object with a settable .value."""

    def __missing__(self, key):
        self[key] = SimpleNamespace(value=None)
        return self[key]


def _app(candy=False, nova=False, finale=False):
    ctx = _Ctx()
    app = App.__new__(App)
    app._ctx = ctx
    app._fbo_a, app._fbo_b = _Fbo('fbo_a', ctx), _Fbo('fbo_b', ctx)
    composite = _Fbo('composite', ctx)
    app._make_or_get_mirror_composite_fbo = lambda: composite
    app._composite = composite
    app._display_mode, app._mirror_rects = 'single', []
    app._projectm_manager_modal_active = False
    app._burst_controller = SimpleNamespace(active=False, step=lambda dt: None)
    app._invert_colors, app._render_scale = False, 1.0
    app._width = app._render_width = 64
    app._height = app._render_height = 48
    app._window_width, app._window_height = 64, 48
    app._active_post_chain = lambda: []
    app._video_deck_layer = None
    app._audio = None
    app._webcam_system = app._dancing_unicorn = app._auto_vj = None
    app._current_effect, app._next_effect = 'A', 'B'
    app._transition_t, app._transition_duration = 0.30, 1.0
    app._transition_kind, app._transition_dir, app._transition_phase = 'fade', 0, 0.0
    app._blend_prog, app._present_prog = _Prog(), _Prog()
    seen = {'blend_target': None, 'blend_inputs': None, 'overlay_saw': {}}

    def blend_render(_mode):
        seen['blend_target'] = ctx.bound
        seen['blend_inputs'] = (ctx.slots.get(0), ctx.slots.get(1))
        ctx.bound.content = 'blend'

    def present_render(_mode):
        src = ctx.slots.get(0)
        ctx.bound.content = src.content if src is not None else None

    app._blend_vao = SimpleNamespace(render=blend_render)
    app._present_vao = SimpleNamespace(render=present_render)

    def render_effect(effect, _w, _h):
        ctx.bound.content = effect                       # 'A' into fbo_a, 'B' into fbo_b

    app._render_effect_to_current_target = render_effect

    def present_from_tex(tex):
        ctx.screen.content = tex.owner.content
    app._present_from_tex = present_from_tex
    app._blit_fbo_b_to_fbo_a = lambda *a, **k: None
    app._normalize_gl_render_state = lambda: None
    app._effect_requests_frame_scaling = lambda _e: False
    app._re_randomize_on_scene_change = lambda: None

    def overlay(name, active):
        o = SimpleNamespace(active=active, is_active=active, overlay_active=active)

        def draw(tex, *a, **k):
            seen['overlay_saw'][name] = tex.owner.content        # what it samples, right now
            ctx.screen.content = f'{name}({tex.owner.content})'  # replaces the screen, like Candy Frame
        o.update = lambda *a, **k: None
        o.set_outer_fill_needed = lambda *_a: None
        o.render = draw
        o.render_overlay = lambda tex, fbo, w, h: draw(tex)
        return o

    app._candy_frame = overlay('candy', True) if candy else None
    app._rainbow_nova = overlay('nova', True) if nova else None
    app._grand_finale = overlay('finale', True) if finale else None
    app._seen = seen
    return app, ctx


def _frame(app) -> None:
    app._render(0.016)
    app._frame_overlay_steps(0.016)


@pytest.mark.parametrize('which', ['candy', 'nova', 'finale'])
def test_the_overlay_draws_the_blend_not_the_outgoing_effect(which) -> None:
    app, ctx = _app(**{which: True})
    _frame(app)
    saw = app._seen['overlay_saw'][which]
    assert saw == 'blend', f'{which} sampled {saw!r}: the transition is hidden under the outgoing effect'
    assert ctx.screen.content.startswith(f'{which}(blend')


def test_all_three_overlays_together_see_the_blend() -> None:
    app, ctx = _app(candy=True, nova=True, finale=True)
    _frame(app)
    assert set(app._seen['overlay_saw'].values()) == {'blend'}


@pytest.mark.parametrize('which', ['candy', 'nova', 'finale'])
def test_the_blend_is_not_drawn_into_a_texture_it_is_reading(which) -> None:
    """Compositing into fbo_a while sampling fbo_a's texture as an input is a
    read/write feedback loop (undefined in GL)."""
    app, ctx = _app(**{which: True})
    _frame(app)
    inputs = app._seen['blend_inputs']
    assert app._seen['blend_target'] not in inputs


def test_without_overlays_the_blend_still_goes_straight_to_the_screen() -> None:
    app, ctx = _app()
    _frame(app)
    assert app._seen['blend_target'] is ctx.screen
    assert ctx.screen.content == 'blend'


def test_the_last_frame_of_a_transition_is_unaffected() -> None:
    app, ctx = _app(candy=True)
    app._transition_t = 0.99999                              # finishes this frame
    app._current_effect = SimpleNamespace(destroy=lambda: None)
    _frame(app)
    assert app._next_effect is None
    assert app._seen['overlay_saw']['candy'] == app._current_effect
