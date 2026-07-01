"""All-overlays-on render smoke test (audit B3 follow-up).

Runs `Overlays.render()` in a headless `__new__`-constructed instance with every
overlay/modal flag enabled and no-op drawing hooks. The test asserts:

- the render path does not raise;
- each overlay render branch is reached in a single frame;
- modal render order remains stable (projectm -> system monitor ->
  controller help -> webcam editor -> audio selector -> midi selector).
"""
from __future__ import annotations

from unicornviz.overlays import Overlays


class _CtaStub:
    is_active = True

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def render(self, _dt, _ctx, _draw_rect, _width, _height) -> None:
        self._calls.append('cta')


def _build_overlays_all_on() -> tuple[Overlays, list[str]]:
    calls: list[str] = []
    o = Overlays.__new__(Overlays)

    # Core frame-state fields referenced by render().
    o._hud_t = 0.0
    o._show_name = True
    o._hud_auto_hide = True
    o._hud_timer = 2.0
    o._show_help = True
    o._help_timer = 2.0
    o._help_pulse_t = 0.0
    o._flash_timer = 0.4
    o._flash_text = 'smoke'
    o._height = 1080
    o._width = 1920
    o._name_text = 'effect'

    # Route modals to audience overlay for this smoke pass.
    o._modal_gate = lambda: False
    o._modal_route_debug_last = (None, None)

    # Banner and recording indicator paths.
    o._banner_timer = 1.0
    o._banner_enabled = True

    # Enable all modal overlays at once.
    o._show_presets = True
    o._show_effects_browser = True
    o._show_projectm_manager = True
    o._show_system_monitor_modal = True
    o._show_controller_help_modal = True
    o._show_webcam_editor_modal = True
    o._show_audio = True
    o._show_midi = True

    # Context menu (floats above the modal stack).
    o._context_menu_open = True
    o._context_menu_entries = [{'label': 'Quit', 'header': False, 'enabled': True}]
    o._context_menu_hover = -1
    o._context_menu_expanded = set()
    o._context_menu_x = 100.0
    o._context_menu_y = 100.0

    # Drawing / render hooks replaced by call-capture no-ops.
    o._draw_text = lambda *_a, **_kw: calls.append('draw_text')
    o._draw_rect = lambda *_a, **_kw: calls.append('draw_rect')
    o._render_hud = lambda: calls.append('hud')
    o._render_banner = lambda: calls.append('banner')
    o._render_recording_indicator = lambda: calls.append('recording')
    o._render_help = lambda: calls.append('help')
    o._render_presets = lambda: calls.append('presets')
    o._render_effects_browser = lambda: calls.append('effects_browser')
    o._render_projectm_manager = lambda: calls.append('projectm_manager')
    o._render_system_monitor_modal = lambda: calls.append('system_monitor')
    o._render_controller_help_modal = lambda: calls.append('controller_help')
    o._render_webcam_editor_modal = lambda: calls.append('webcam_editor')
    o._render_audio_selector = lambda: calls.append('audio_selector')
    o._render_midi_selector = lambda: calls.append('midi_selector')
    o._render_context_menu = lambda: calls.append('context_menu')

    o._ctx = object()
    o._cta = _CtaStub(calls)

    return o, calls


def test_render_all_overlays_enabled_smoke() -> None:
    overlays, calls = _build_overlays_all_on()

    # Should not raise with all overlays active.
    overlays.render(1.0 / 60.0, include_recording_indicator=True)

    expected = {
        'hud',
        'banner',
        'recording',
        'cta',
        'help',
        'presets',
        'effects_browser',
        'projectm_manager',
        'system_monitor',
        'controller_help',
        'webcam_editor',
        'audio_selector',
        'midi_selector',
        'context_menu',
    }
    missing = expected - set(calls)
    assert not missing, f'Missing render branches with all overlays enabled: {sorted(missing)}'

    # Render order contract for modal stack (stable for compositing expectations).
    modal_order = [
        'presets',
        'effects_browser',
        'projectm_manager',
        'system_monitor',
        'controller_help',
        'webcam_editor',
        'audio_selector',
        'midi_selector',
    ]
    seen = [name for name in calls if name in modal_order]
    assert seen == modal_order, f'Unexpected modal render order: {seen}'
