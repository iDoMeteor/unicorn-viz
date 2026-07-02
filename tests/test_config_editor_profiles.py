"""Configuration editor — profile footer (Increment 4) regression tests.

Covers the Overlays footer interactions (name entry, profile chips, pending
action relay) and the App action handler (save/load/delete/revert), plus the
name-char keymap and live revert. No GL context needed.
"""
from __future__ import annotations

from pathlib import Path

import sdl2

from unicornviz.app import App, _name_char_for_keysym
from unicornviz.config_profiles import ConfigProfileStore
from unicornviz.overlays import Overlays


# --------------------------------------------------------------------------- #
# _name_char_for_keysym
# --------------------------------------------------------------------------- #

def test_name_char_keymap() -> None:
    assert _name_char_for_keysym(sdl2.SDLK_a, 0) == 'a'
    assert _name_char_for_keysym(sdl2.SDLK_a, sdl2.KMOD_SHIFT) == 'A'
    assert _name_char_for_keysym(sdl2.SDLK_5, 0) == '5'
    assert _name_char_for_keysym(sdl2.SDLK_SPACE, 0) == ' '
    assert _name_char_for_keysym(sdl2.SDLK_MINUS, 0) == '-'
    assert _name_char_for_keysym(sdl2.SDLK_MINUS, sdl2.KMOD_SHIFT) == '_'
    assert _name_char_for_keysym(sdl2.SDLK_RETURN, 0) == ''


# --------------------------------------------------------------------------- #
# Overlays footer
# --------------------------------------------------------------------------- #

def _editor() -> Overlays:
    ov = Overlays.__new__(Overlays)
    ov._show_config_editor = True
    ov._config_editor_panel_rect = (100.0, 80.0, 1400.0, 900.0)
    ov._config_editor_tabs = ['Effects', 'Audio', 'Visuals']
    ov._config_editor_tab = 0
    ov._glyph_w = 13
    ov._glyph_h = 18
    ov._font_scale_norm = 8.0 / 18.0
    ov._ce_effects = []
    ov._ce_effect_idx = 0
    ov._ce_params = []
    ov._ce_param_idx = 0
    ov._ce_focus = 0
    ov._ce_effect_row_rects = []
    ov._ce_param_row_rects = []
    ov._ce_profiles = ['Set A', 'Set B']
    ov._ce_profile_idx = -1
    ov._ce_dirty = False
    ov._ce_name_mode = False
    ov._ce_name_text = ''
    ov._ce_pending_action = None
    ov._ce_footer_button_rects = []
    ov._ce_profile_chip_rects = []
    return ov


def test_name_entry_setters() -> None:
    ov = _editor()
    assert ov.config_editor_name_mode is False
    ov.set_config_editor_name_mode(True)
    assert ov.config_editor_name_mode is True
    ov.set_config_editor_name_text('Neon')
    assert ov.config_editor_name_text == 'Neon'


def test_footer_button_click_sets_pending_action() -> None:
    ov = _editor()
    ov._ce_footer_button_rects = [
        (1000.0, 700.0, 90.0, 32.0, 'save'),
        (900.0, 700.0, 90.0, 32.0, 'load'),
    ]
    assert ov.handle_config_editor_click(1040.0, 715.0) is True
    assert ov.take_config_editor_action() == 'save'
    # Action is consumed (pops once).
    assert ov.take_config_editor_action() is None


def test_profile_chip_click_selects_and_fills_name() -> None:
    ov = _editor()
    ov._ce_profile_chip_rects = [
        (150.0, 640.0, 120.0, 28.0, 0),
        (280.0, 640.0, 120.0, 28.0, 1),
    ]
    assert ov.handle_config_editor_click(300.0, 652.0) is True
    assert ov._ce_profile_idx == 1
    assert ov.config_editor_name_text == 'Set B'
    assert ov.config_editor_selected_profile() == 'Set B'


def test_selected_profile_falls_back_to_name_text() -> None:
    ov = _editor()
    ov.set_config_editor_name_text('Typed Name')
    assert ov.config_editor_selected_profile() == 'Typed Name'


# --------------------------------------------------------------------------- #
# App action handler
# --------------------------------------------------------------------------- #

class _StubCfg:
    def get(self, section, key=None, default=None):
        return default


class _Effect:
    def __init__(self, params, initial=None):
        self.parameters = dict(params)
        self._initial_parameters = dict(initial if initial is not None else params)


class _RecordingOverlay:
    """Minimal overlay stand-in for the App action handler."""

    def __init__(self, name_text='', selected_profile='', selected_class='',
                 action=None) -> None:
        self._name_text = name_text
        self._selected_profile = selected_profile
        self._selected_class = selected_class
        self._action = action
        self.name_mode = False
        self.messages: list[str] = []

    def take_config_editor_action(self):
        a, self._action = self._action, None
        return a

    @property
    def config_editor_name_text(self):
        return self._name_text

    def set_config_editor_name_mode(self, active):
        self.name_mode = bool(active)

    def config_editor_selected_profile(self):
        return self._selected_profile

    def config_editor_selected_class(self):
        return self._selected_class

    def flash_message(self, text, _dur=0.0):
        self.messages.append(text)


def _app(tmp_path: Path, overlay, current=None) -> App:
    app = object.__new__(App)
    app.cfg = _StubCfg()
    app._config_profile_store = ConfigProfileStore(tmp_path / 'cp.json')
    app._effect_config_overrides = {}
    app._current_effect = current
    app._overlays = overlay
    # Settings-spec aggregation (save/load) reads these.
    app._audio_manager = None
    app._effect_duration = 30.0
    app._render_scale = 1.0
    app._color_grade = None
    app._audio_out = None
    return app


def test_action_save_with_name(tmp_path: Path) -> None:
    ov = _RecordingOverlay(name_text='My Set', action='save')
    app = _app(tmp_path, ov)
    app.set_effect_parameter('Plasma', 'speed', 1.5)
    app._apply_config_editor_action()
    assert 'My Set' in app.config_profile_names()
    assert any('saved' in m.lower() for m in ov.messages)


def test_action_save_without_name_enters_name_mode(tmp_path: Path) -> None:
    ov = _RecordingOverlay(name_text='   ', action='save')
    app = _app(tmp_path, ov)
    app._apply_config_editor_action()
    assert ov.name_mode is True
    assert app.config_profile_names() == []


def test_action_load_and_delete(tmp_path: Path) -> None:
    # Seed a profile on disk.
    store = ConfigProfileStore(tmp_path / 'cp.json')
    store.save('Set A', {'effects': {'Plasma': {'speed': 2.0}}})

    ov = _RecordingOverlay(selected_profile='Set A', action='load')
    app = _app(tmp_path, ov)
    app._apply_config_editor_action()
    assert app.config_overrides_snapshot() == {'Plasma': {'speed': 2.0}}

    ov._action = 'delete'
    app._apply_config_editor_action()
    assert 'Set A' not in app.config_profile_names()


def test_action_revert_restores_initial_live(tmp_path: Path) -> None:
    class _Plasma(_Effect):
        pass

    eff = _Plasma({'speed': 4.0}, initial={'speed': 1.0})
    ov = _RecordingOverlay(selected_class='_Plasma', action='revert')
    app = _app(tmp_path, ov, current=eff)
    app.set_effect_parameter('_Plasma', 'speed', 4.0)
    assert eff.parameters['speed'] == 4.0

    app._apply_config_editor_action()
    assert app.config_overrides_snapshot() == {}
    assert eff.parameters['speed'] == 1.0  # restored to initial, live
