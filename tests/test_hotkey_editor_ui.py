"""Config editor "Hotkeys" tab — regression tests.

The in-app hotkey editor: browse rebindable global actions, press Enter to
capture a new chord, live conflict detection, Backspace to reset to default.
Built on the translation-layer enabler (test_hotkey_rebinding.py).
"""
from __future__ import annotations

from pathlib import Path

import sdl2

from unicornviz.app import App
from unicornviz.hotkeys import action_names, default_action_binding
from unicornviz.overlays import Overlays
from unicornviz.runtime_state import RuntimeStateStore


def _app(tmp_path: Path) -> App:
    app = object.__new__(App)
    app._runtime_state = RuntimeStateStore(tmp_path / 'state.json')
    app._hotkey_overrides = {
        str(k): (int(v[0]), int(v[1]))
        for k, v in (app._runtime_state.get('hotkeys.overrides', {}) or {}).items()
        if isinstance(v, (list, tuple)) and len(v) == 2
    }
    ov = Overlays.__new__(Overlays)
    ov._ce_capture_mode = False
    ov._ce_capture_action = ''
    ov.flash_message = lambda *_a, **_kw: None  # avoid full HUD/flash init
    app._overlays = ov
    return app


# --------------------------------------------------------------------------- #
# App: row model
# --------------------------------------------------------------------------- #

def test_hotkey_rows_cover_all_actions(tmp_path: Path) -> None:
    app = _app(tmp_path)
    rows = app.config_editor_hotkey_rows()
    assert len(rows) == len(action_names())
    assert all(r['kind'] == 'bind' for r in rows)
    assert all(r['name'] for r in rows)  # every action has a label


def test_hotkey_row_shows_default_chord_when_unbound(tmp_path: Path) -> None:
    app = _app(tmp_path)
    rows = app.config_editor_hotkey_rows()
    fullscreen = next(r for r in rows if r['action'] == 'fullscreen')
    assert fullscreen['chord'] == 'F'
    assert fullscreen['is_override'] is False


def test_hotkey_row_shows_override_chord(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.set_hotkey_override('fullscreen', sdl2.SDLK_j, 0)
    rows = app.config_editor_hotkey_rows()
    fullscreen = next(r for r in rows if r['action'] == 'fullscreen')
    assert fullscreen['chord'] == 'J'
    assert fullscreen['is_override'] is True


# --------------------------------------------------------------------------- #
# App: conflict detection
# --------------------------------------------------------------------------- #

def test_conflict_detects_default_binding(tmp_path: Path) -> None:
    app = _app(tmp_path)
    # 'help' defaults to H; asking "who owns H" (excluding 'help' itself) finds it.
    hit = app.hotkey_action_for_chord(sdl2.SDLK_h, 0)
    assert hit == 'help'


def test_conflict_excludes_self(tmp_path: Path) -> None:
    app = _app(tmp_path)
    assert app.hotkey_action_for_chord(sdl2.SDLK_h, 0, exclude_action='help') is None


def test_conflict_detects_another_override(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.set_hotkey_override('screenshot', sdl2.SDLK_j, 0)
    assert app.hotkey_action_for_chord(sdl2.SDLK_j, 0) == 'screenshot'


def test_no_conflict_for_free_chord(tmp_path: Path) -> None:
    app = _app(tmp_path)
    assert app.hotkey_action_for_chord(99999, 0) is None


# --------------------------------------------------------------------------- #
# App: capture flow (start / apply / cancel)
# --------------------------------------------------------------------------- #

def test_start_capture_sets_overlay_state(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.start_hotkey_capture('fullscreen')
    assert app._overlays.config_editor_capture_mode is True
    assert app._overlays.config_editor_capture_action == 'fullscreen'


def test_apply_capture_success_binds_and_exits_capture(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.start_hotkey_capture('fullscreen')
    msg = app.apply_hotkey_capture(sdl2.SDLK_j, 0)
    assert 'bound to J' in msg
    assert app.hotkey_overrides() == {'fullscreen': (sdl2.SDLK_j, 0)}
    assert app._overlays.config_editor_capture_mode is False


def test_apply_capture_rejects_modifier_only_key(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.start_hotkey_capture('fullscreen')
    msg = app.apply_hotkey_capture(sdl2.SDLK_LSHIFT, 0)
    assert 'non-modifier' in msg
    assert app.hotkey_overrides() == {}
    # Capture mode stays open so the operator can try again.
    assert app._overlays.config_editor_capture_mode is True


def test_apply_capture_rejects_conflict_and_stays_open(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.start_hotkey_capture('fullscreen')
    msg = app.apply_hotkey_capture(sdl2.SDLK_h, 0)  # 'help' owns H by default
    assert 'Conflicts with "Help Overlay"' in msg
    assert app.hotkey_overrides() == {}
    assert app._overlays.config_editor_capture_mode is True


def test_apply_capture_allows_rebinding_to_own_current_key(tmp_path: Path) -> None:
    # Rebinding an action to the key it already effectively owns is not a
    # "conflict with someone else" - it's a no-op-ish confirm.
    app = _app(tmp_path)
    app.start_hotkey_capture('fullscreen')
    msg = app.apply_hotkey_capture(sdl2.SDLK_f, 0)
    assert 'bound to F' in msg
    assert app.hotkey_overrides() == {'fullscreen': (sdl2.SDLK_f, 0)}


def test_cancel_capture_leaves_binding_unchanged(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.start_hotkey_capture('fullscreen')
    app.cancel_hotkey_capture()
    assert app._overlays.config_editor_capture_mode is False
    assert app.hotkey_overrides() == {}


# --------------------------------------------------------------------------- #
# App: reset to default
# --------------------------------------------------------------------------- #

def test_reset_to_default_clears_override(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.set_hotkey_override('fullscreen', sdl2.SDLK_j, 0)
    msg = app.reset_hotkey_to_default('fullscreen')
    assert 'reset to default' in msg
    assert app.hotkey_overrides() == {}


def test_reset_when_already_default_is_a_noop_message(tmp_path: Path) -> None:
    app = _app(tmp_path)
    msg = app.reset_hotkey_to_default('fullscreen')
    assert 'already default' in msg


# --------------------------------------------------------------------------- #
# Overlays: capture-mode state + row rendering (no GL)
# --------------------------------------------------------------------------- #

def _bare_overlays() -> Overlays:
    ov = Overlays.__new__(Overlays)
    ov._ce_params = []
    ov._ce_param_idx = 0
    ov._ce_focus = 1
    ov._ce_param_row_rects = []
    ov._ce_capture_mode = False
    ov._ce_capture_action = ''
    ov._glyph_w = 13
    ov._glyph_h = 18
    ov._font_scale_norm = 8.0 / 18.0
    ov._hud_t = 0.0
    return ov


def test_config_editor_capture_accessors() -> None:
    ov = _bare_overlays()
    assert ov.config_editor_capture_mode is False
    ov.set_config_editor_capture(True, 'fullscreen')
    assert ov.config_editor_capture_mode is True
    assert ov.config_editor_capture_action == 'fullscreen'
    ov.set_config_editor_capture(False)
    assert ov.config_editor_capture_mode is False
    assert ov.config_editor_capture_action == ''


def test_config_editor_selected_row() -> None:
    ov = _bare_overlays()
    assert ov.config_editor_selected_row() is None
    ov._ce_params = [{'name': 'A', 'kind': 'bind'}, {'name': 'B', 'kind': 'bind'}]
    ov._ce_param_idx = 1
    assert ov.config_editor_selected_row() == {'name': 'B', 'kind': 'bind'}


def test_render_hotkeys_tab_smoke() -> None:
    ov = _bare_overlays()
    ov._ce_params = [
        {'name': 'Toggle Fullscreen', 'kind': 'bind', 'action': 'fullscreen',
         'chord': 'F', 'is_override': False},
        {'name': 'Help Overlay', 'kind': 'bind', 'action': 'help',
         'chord': 'Ctrl+J', 'is_override': True},
    ]
    ov._draw_rect = lambda *a, **k: None
    ov._draw_text = lambda *a, **k: None
    ov._context_menu_hover_glow = lambda *a, **k: None

    ov._render_config_editor_param_rows(100.0, 80.0, 700.0, 500.0, 'HOTKEYS')
    assert len(ov._ce_param_row_rects) == 2


def test_render_hotkeys_tab_capture_prompt_smoke() -> None:
    ov = _bare_overlays()
    ov._ce_params = [
        {'name': 'Toggle Fullscreen', 'kind': 'bind', 'action': 'fullscreen',
         'chord': 'F', 'is_override': False},
    ]
    ov._ce_capture_mode = True
    ov._ce_capture_action = 'fullscreen'
    ov._draw_rect = lambda *a, **k: None
    ov._draw_text = lambda *a, **k: None
    ov._context_menu_hover_glow = lambda *a, **k: None

    ov._render_config_editor_param_rows(100.0, 80.0, 700.0, 500.0, 'HOTKEYS')  # must not raise


# --------------------------------------------------------------------------- #
# hotkeys.py: default_action_binding cross-check for a few actions used above
# --------------------------------------------------------------------------- #

def test_default_action_binding_matches_expected() -> None:
    assert default_action_binding('fullscreen') == (sdl2.SDLK_f, 0)
    assert default_action_binding('help') == (sdl2.SDLK_h, 0)
