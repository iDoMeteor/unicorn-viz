"""Delete key: disable the active effect and advance — regression tests.

Delete-key action: disables the currently active effect and immediately
switches to a different one. If the active effect is ProjectM (duck-typed:
exposes current_preset_path/set_presets_enabled/next_preset), "disable"
applies to the *current preset* and playback stays within ProjectM rather than
leaving it; any other effect is disabled from rotation (same persisted set
the effects browser's Space toggle uses) and playback advances to the next
*enabled* effect.
"""
from __future__ import annotations

from pathlib import Path

import sdl2

from unicornviz.app import App
from unicornviz.hotkeys import HotkeyHandler, default_action_binding
from unicornviz.playlist import Playlist
from unicornviz.runtime_state import RuntimeStateStore


def _fx(name: str):
    return type(name, (), {'NAME': name, 'TAGS': [], 'parameters': {}})


class _StubCfg:
    def get(self, *_keys, default=None):
        return default


def _app_with_playlist(tmp_path: Path, names: list[str], start: str | None = None):
    effects = [_fx(n) for n in names]
    playlist = Playlist(effects, _StubCfg())
    if start:
        idx = next(i for i, c in enumerate(effects) if c.NAME == start)
        playlist.go_index(idx)

    app = object.__new__(App)
    app._runtime_state = RuntimeStateStore(tmp_path / 'state.json')
    app._disabled_effects = set()
    app._playlist = playlist
    app._effect_lock = None
    app._overlays = None  # _refresh_effect_shortcuts no-ops when overlays is None
    app._current_effect = playlist.current()
    app._deleted_effects_session = []
    app._deleted_effects_log_path = None

    def _goto(cls):
        app._current_effect = cls

    app.goto_effect = _goto
    return app, playlist


# --------------------------------------------------------------------------- #
# Default binding
# --------------------------------------------------------------------------- #

def test_default_binding_is_delete_key() -> None:
    assert default_action_binding('disable_and_advance') == (sdl2.SDLK_DELETE, 0)


# --------------------------------------------------------------------------- #
# Non-ProjectM effect: disable from rotation + advance
# --------------------------------------------------------------------------- #

def test_disables_current_effect_and_advances(tmp_path: Path) -> None:
    app, playlist = _app_with_playlist(tmp_path, ['A', 'B', 'C'], start='A')
    msg = app.disable_current_effect_and_advance()
    assert 'A: disabled ->' in msg
    assert app.effect_enabled('A') is False
    assert app._current_effect.NAME != 'A'
    # The new effect is genuinely enabled (advance() skips disabled effects).
    assert app._current_effect.NAME in ('B', 'C')


def test_disabled_effect_persists(tmp_path: Path) -> None:
    app, _playlist = _app_with_playlist(tmp_path, ['A', 'B', 'C'], start='A')
    app.disable_current_effect_and_advance()
    app2 = object.__new__(App)
    app2._runtime_state = RuntimeStateStore(tmp_path / 'state.json')
    app2._disabled_effects = {
        str(n) for n in (app2._runtime_state.get('effects.disabled', []) or [])
    }
    assert 'A' in app2._disabled_effects


def test_advance_skips_a_second_already_disabled_effect(tmp_path: Path) -> None:
    app, _playlist = _app_with_playlist(tmp_path, ['A', 'B', 'C'], start='A')
    app.set_effect_enabled('B', False)  # B already disabled from a prior session
    app.disable_current_effect_and_advance()
    assert app._current_effect.NAME == 'C'  # B skipped, lands on C


def test_clears_matching_effect_lock_before_advancing(tmp_path: Path) -> None:
    app, _playlist = _app_with_playlist(tmp_path, ['A', 'B', 'C'], start='A')
    app._effect_lock = 'A'  # operator had pinned the effect being disabled
    app.disable_current_effect_and_advance()
    assert app._effect_lock is None
    assert app._current_effect.NAME != 'A'


def test_unrelated_effect_lock_is_untouched(tmp_path: Path) -> None:
    app, _playlist = _app_with_playlist(tmp_path, ['A', 'B', 'C'], start='A')
    app._effect_lock = 'SomeOtherEffect'
    app.disable_current_effect_and_advance()
    assert app._effect_lock == 'SomeOtherEffect'


def test_no_active_effect_is_a_safe_noop(tmp_path: Path) -> None:
    app, _playlist = _app_with_playlist(tmp_path, ['A', 'B'], start='A')
    app._current_effect = None
    msg = app.disable_current_effect_and_advance()
    assert msg == 'No active effect'


def test_no_playlist_still_disables(tmp_path: Path) -> None:
    app, _playlist = _app_with_playlist(tmp_path, ['A', 'B'], start='A')
    app._playlist = None
    msg = app.disable_current_effect_and_advance()
    assert msg == 'A: disabled'
    assert app.effect_enabled('A') is False


# --------------------------------------------------------------------------- #
# ProjectM (duck-typed): disable current preset, stay within ProjectM
# --------------------------------------------------------------------------- #

class _FakeProjectM:
    """Duck-types the subset of ProjectMEffect the Delete action needs."""

    NAME = 'ProjectM Presets'

    def __init__(self, presets: list[str]) -> None:
        self._presets = list(presets)
        self._idx = 0
        self.disabled: list[str] = []

    @property
    def current_preset_path(self) -> str:
        return self._presets[self._idx] if self._presets else ''

    def set_presets_enabled(self, paths: list[str], enabled: bool) -> int:
        if not enabled:
            for p in paths:
                if p in self._presets:
                    self._presets.remove(p)
                    self.disabled.append(p)
                    if self._idx >= len(self._presets) and self._presets:
                        self._idx = 0
        return len(self._presets)

    def next_preset(self) -> str | None:
        if not self._presets:
            return None
        self._idx = (self._idx + 1) % len(self._presets)
        return self._presets[self._idx]


def _app_with_projectm(tmp_path: Path, presets: list[str]):
    app = object.__new__(App)
    app._runtime_state = RuntimeStateStore(tmp_path / 'state.json')
    app._disabled_effects = set()
    app._playlist = None
    app._effect_lock = None
    app._overlays = None
    app._current_effect = _FakeProjectM(presets)
    return app


def test_projectm_disables_preset_not_the_rotation_effect(tmp_path: Path) -> None:
    app = _app_with_projectm(tmp_path, ['/a.milk', '/b.milk', '/c.milk'])
    effect = app._current_effect
    msg = app.disable_current_effect_and_advance()
    assert 'Preset disabled' in msg
    assert '/a.milk' in effect.disabled
    # The rotation-level "ProjectM Presets" effect itself was never disabled.
    assert app.effect_enabled('ProjectM Presets') is True
    # Stayed within ProjectM - current_effect is unchanged (same instance).
    assert app._current_effect is effect


def test_projectm_advances_to_a_different_preset(tmp_path: Path) -> None:
    app = _app_with_projectm(tmp_path, ['/a.milk', '/b.milk'])
    effect = app._current_effect
    app.disable_current_effect_and_advance()
    assert effect.current_preset_path == '/b.milk'


def test_projectm_no_presets_loaded(tmp_path: Path) -> None:
    app = _app_with_projectm(tmp_path, [])
    msg = app.disable_current_effect_and_advance()
    assert msg == 'ProjectM: no active preset to disable'


def test_projectm_lock_is_untouched(tmp_path: Path) -> None:
    # ProjectM-only mode locks effect_lock == 'ProjectM Presets'; disabling a
    # preset must not clear that lock (we never left ProjectM).
    app = _app_with_projectm(tmp_path, ['/a.milk', '/b.milk'])
    app._effect_lock = 'ProjectM Presets'
    app.disable_current_effect_and_advance()
    assert app._effect_lock == 'ProjectM Presets'


# --------------------------------------------------------------------------- #
# End-to-end: real HotkeyHandler.handle() dispatches Delete correctly
# --------------------------------------------------------------------------- #

class _Audio:
    def get_reactivity(self) -> float:
        return 1.0


class _Overlay:
    help_visible = False
    midi_selector_visible = False
    name_overlay_visible = False
    controller_help_modal_visible = False
    webcam_editor_modal_visible = False
    audio_selector_visible = False
    effects_browser_visible = False
    presets_visible = False
    projectm_manager_visible = False
    context_menu_open = False
    config_editor_open = False

    def flash_message(self, *_a, **_kw) -> None:
        return

    def flash_name(self, *_a, **_kw) -> None:
        return

    def note_help_activity(self) -> None:
        return


class _VJApi:
    def mark_user_action(self, _kind: str) -> None:
        return

    def key_handler_items(self):
        return []


def test_end_to_end_delete_key_dispatches(tmp_path: Path) -> None:
    app, _playlist = _app_with_playlist(tmp_path, ['A', 'B', 'C'], start='A')
    app._auto_vj = None  # backs the read-only auto_vj_controller property
    app._keystroke_logger = None
    app.vj_api = _VJApi()
    app.hotkey_overrides = lambda: {}

    handler = HotkeyHandler(app, _playlist, _Overlay(), _Audio())
    handler.handle(sdl2.SDLK_DELETE, 0)

    assert app.effect_enabled('A') is False
    assert app._current_effect.NAME != 'A'
