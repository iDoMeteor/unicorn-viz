"""Hotkey integration tests for the ProjectM manager modal.

Covers Ctrl+M open/close flow and key routes while the manager is visible.
"""
from __future__ import annotations

import sdl2

from unicornviz.hotkeys import HotkeyHandler


class _ManagerEffect:
    NAME = 'ProjectM Presets'
    EXCLUDED_CATEGORY = '! Excluded'
    QUARANTINE_CATEGORY = '! Quarantined'
    DISABLED_CATEGORY = '! Disabled'

    def __init__(self) -> None:
        self.current_preset_path = '/tmp/presets/pack-a/one.milk'
        self._catalog = [
            {
                'path': '/tmp/presets/pack-a/one.milk',
                'display_name': 'one',
                'pack_name': 'pack-a',
                'category_path': ['Fractal'],
                'category_key': 'Fractal',
                'tags': ['fractal', 'one'],
                'enabled': True,
            },
            {
                'path': '/tmp/presets/pack-b/two.milk',
                'display_name': 'two',
                'pack_name': 'pack-b',
                'category_path': ['Reaction'],
                'category_key': 'Reaction',
                'tags': ['reaction', 'two'],
                'enabled': True,
            },
        ]
        self.calls: list[tuple[str, object]] = []
        self.quarantine_category_result = 3

    def preset_catalog(self):
        self.calls.append(('preset_catalog', None))
        return list(self._catalog)

    def goto_preset_path(self, path: str):
        self.calls.append(('goto_preset_path', path))
        self.current_preset_path = path
        return 'preset-loaded'

    def enable_all_presets(self):
        self.calls.append(('enable_all_presets', None))
        return 10

    def disable_all_presets(self):
        self.calls.append(('disable_all_presets', None))
        return 0

    def enable_category(self, category: str):
        self.calls.append(('enable_category', category))
        return 6

    def disable_category(self, category: str):
        self.calls.append(('disable_category', category))
        return 4

    def isolate_category(self, category: str):
        self.calls.append(('isolate_category', category))
        return 2

    def set_presets_enabled(self, preset_paths: list[str], enabled: bool):
        self.calls.append(('set_presets_enabled', (tuple(preset_paths), enabled)))
        return 5

    def delete_presets(self, preset_paths: list[str], permanent: bool = False):
        self.calls.append(('delete_presets', (tuple(preset_paths), permanent)))
        return 1

    def quarantine_preset(self, path_str: str) -> bool:
        self.calls.append(('quarantine_preset', path_str))
        return True

    def quarantine_category(self, category: str) -> int:
        self.calls.append(('quarantine_category', category))
        return self.quarantine_category_result

    def restore_from_quarantine(self, path_str: str) -> bool:
        self.calls.append(('restore_from_quarantine', path_str))
        return True

    def delete_quarantined_preset(self, path_str: str) -> bool:
        self.calls.append(('delete_quarantined_preset', path_str))
        return True

    def undo_last_bulk_state_change(self):
        self.calls.append(('undo_last_bulk_state_change', None))
        return 'disable-all (state-x.json)'

    def redo_last_bulk_state_change(self):
        self.calls.append(('redo_last_bulk_state_change', None))
        return 'redo-step (redo-x.json)'


class _VJApi:
    def mark_user_action(self, _kind: str) -> None:
        pass

    def key_handler_items(self):
        return []

    def unregister_key_handler(self, _name: str) -> None:
        pass

    def list_webcam_cameras(self):
        return []

    def webcam_image_state(self):
        return {'active': False, 'path': '', 'opacity': 1.0, 'scale': 1.0, 'x': 0.5, 'y': 0.5}


class _Overlay:
    midi_selector_visible = False
    system_monitor_modal_visible = False
    help_visible = False
    name_overlay_visible = False
    controller_help_modal_visible = False
    webcam_editor_modal_visible = False
    audio_selector_visible = False

    def __init__(self) -> None:
        self.projectm_manager_visible = False
        self.projectm_manager_focus_pane = 0
        self._category = '(all)'
        self._selected_preset: dict[str, object] | None = {
            'path': '/tmp/presets/pack-a/one.milk',
            'enabled': True,
        }
        self._search_query = ''
        self.messages: list[str] = []
        self.entries_calls: list[tuple[list[dict[str, object]], str]] = []

    @property
    def projectm_search_query(self) -> str:
        return self._search_query

    def set_projectm_search_query(self, value: str) -> None:
        self._search_query = value

    def clear_projectm_search_query(self) -> None:
        self._search_query = ''

    def flash_message(self, text: str, *_a, **_kw) -> None:
        self.messages.append(str(text))

    def flash_name(self, *_a) -> None:
        pass

    def note_help_activity(self) -> None:
        pass

    def toggle_projectm_manager(self) -> None:
        self.projectm_manager_visible = not self.projectm_manager_visible

    def set_projectm_manager_entries(self, catalog, current_path) -> None:
        self.entries_calls.append((list(catalog), str(current_path)))

    def get_projectm_selected_preset(self):
        return self._selected_preset

    def get_projectm_selected_category(self) -> str:
        return self._category

    def move_projectm_focus(self, delta: int) -> None:
        self.projectm_manager_focus_pane = (self.projectm_manager_focus_pane + delta) % 2

    def move_projectm_category_selection(self, _delta: int) -> None:
        pass

    def move_projectm_preset_selection(self, _delta: int) -> None:
        pass

    # Required by HotkeyHandler init/runtime, not directly asserted here.
    def toggle_system_monitor_modal(self) -> None:
        self.system_monitor_modal_visible = not self.system_monitor_modal_visible

    def toggle_midi_selector(self) -> None:
        self.midi_selector_visible = not self.midi_selector_visible

    def set_midi_ports(self, _ports: list, _current: str) -> None:
        pass

    def toggle_name_overlay(self) -> None:
        pass

    def move_audio_selection(self, _d: int) -> None:
        pass

    def get_audio_selected_index(self) -> int:
        return 0

    def toggle_audio_selected_viable(self) -> bool:
        return True

    def toggle_audio_selector(self) -> None:
        pass

    def set_audio_sources(self, *_a, **_kw) -> None:
        pass


class _App:
    def __init__(self, manager_effect: _ManagerEffect | None) -> None:
        self.vj_api = _VJApi()
        self.auto_vj_controller = None
        self.current_effect = None
        self.current_effect_name = '-'
        self._keystroke_logger = None
        self._midi_manager = None
        self._speed_rand = False
        self._react_rand = False
        self._manager_effect = manager_effect
        self.projectm_modal_active_calls: list[bool] = []

    def resolve_projectm_manager_effect(self):
        return self._manager_effect

    def set_projectm_manager_modal_active(self, active: bool) -> None:
        self.projectm_modal_active_calls.append(bool(active))

    def toggle_control_room(self) -> tuple[bool, str]:
        return False, 'Control Room OFF'

    def get_audio_sources(self) -> list[str]:
        return []

    def get_audio_source_index(self) -> int:
        return 0

    def get_audio_source_viable_flags(self) -> list[bool]:
        return []

    def select_audio_source(self, _idx: int) -> str:
        return ''

    def toggle_audio_source_viable(self, _idx: int) -> str:
        return ''

    def goto_effect(self, _cls) -> None:
        pass

    def get_midi_ports(self) -> list[str]:
        return []

    def select_midi_device(self, _port: str) -> str:
        return 'MIDI: none'

    @property
    def speed_randomized(self) -> bool:
        return self._speed_rand

    @speed_randomized.setter
    def speed_randomized(self, v: bool) -> None:
        self._speed_rand = v

    def set_speed_randomized(self, v: bool) -> None:
        self._speed_rand = v

    def apply_random_speed(self) -> None:
        pass

    def random_range_for(self, _key: str, lo: float, hi: float) -> tuple[float, float]:
        return lo, hi

    @property
    def reactivity_randomized(self) -> bool:
        return self._react_rand

    @reactivity_randomized.setter
    def reactivity_randomized(self, v: bool) -> None:
        self._react_rand = v

    def set_reactivity_randomized(self, v: bool) -> None:
        self._react_rand = v

    def apply_random_reactivity(self) -> None:
        pass


class _Audio:
    def list_profiles(self):
        return ['house']

    def get_profile_key(self) -> str:
        return 'house'

    def get_profile(self):
        class _P:
            name = 'house'

        return _P()

    def set_profile(self, _name: str):
        return self.get_profile()

    def set_reactivity(self, v: float) -> float:
        return v

    def get_reactivity(self) -> float:
        return 1.0

    def reset_reactivity(self) -> float:
        return 1.0


class _Playlist:
    mode = 'sequential'
    index = 0
    effects = []
    shortcut_effects = []

    def advance(self):
        return type('E', (), {'NAME': 'Stub'})

    def go_index(self, _i):
        return type('E', (), {'NAME': 'Stub'})


def _setup(manager_effect: _ManagerEffect | None) -> tuple[HotkeyHandler, _App, _Overlay]:
    app = _App(manager_effect)
    overlay = _Overlay()
    handler = HotkeyHandler(app, _Playlist(), overlay, _Audio())
    return handler, app, overlay


def test_ctrl_m_opens_projectm_manager_and_syncs_entries() -> None:
    manager = _ManagerEffect()
    handler, app, overlay = _setup(manager)

    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)

    assert overlay.projectm_manager_visible
    assert app.projectm_modal_active_calls == [True]
    assert len(overlay.entries_calls) >= 1
    assert overlay.entries_calls[-1][1] == manager.current_preset_path
    assert handler._projectm_preview_origin_path == manager.current_preset_path
    assert handler._projectm_preview_committed_path == manager.current_preset_path


def test_ctrl_m_when_unavailable_shows_message_and_does_not_open() -> None:
    handler, app, overlay = _setup(None)

    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)

    assert not overlay.projectm_manager_visible
    assert app.projectm_modal_active_calls == []
    assert any('unavailable' in msg.lower() for msg in overlay.messages)


def test_projectm_manager_ctrl_a_disable_undo_redo_routes_to_effect() -> None:
    manager = _ManagerEffect()
    handler, _app, overlay = _setup(manager)

    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)
    assert overlay.projectm_manager_visible

    handler.handle(sdl2.SDLK_a, sdl2.KMOD_CTRL)
    handler.handle(sdl2.SDLK_a, sdl2.KMOD_CTRL | sdl2.KMOD_SHIFT)
    handler.handle(sdl2.SDLK_z, sdl2.KMOD_CTRL)
    handler.handle(sdl2.SDLK_y, sdl2.KMOD_CTRL)

    names = [name for name, _payload in manager.calls]
    assert 'enable_all_presets' in names
    assert 'disable_all_presets' in names
    assert 'undo_last_bulk_state_change' in names
    assert 'redo_last_bulk_state_change' in names
    assert any('enabled all' in msg.lower() for msg in overlay.messages)
    assert any('all disabled' in msg.lower() for msg in overlay.messages)
    assert any('projectm undo:' in msg.lower() for msg in overlay.messages)
    assert any('projectm redo:' in msg.lower() for msg in overlay.messages)


def test_projectm_manager_preset_actions_toggle_delete_and_close() -> None:
    manager = _ManagerEffect()
    handler, app, overlay = _setup(manager)

    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)
    assert overlay.projectm_manager_visible

    overlay.projectm_manager_focus_pane = 1
    overlay._selected_preset = {'path': '/tmp/presets/pack-b/two.milk', 'enabled': True}

    handler.handle(sdl2.SDLK_d, 0)
    handler.handle(sdl2.SDLK_e, 0)
    handler.handle(sdl2.SDLK_DELETE, sdl2.KMOD_SHIFT)

    assert ('set_presets_enabled', (('/tmp/presets/pack-b/two.milk',), False)) in manager.calls
    assert ('set_presets_enabled', (('/tmp/presets/pack-b/two.milk',), True)) in manager.calls
    assert ('delete_presets', (('/tmp/presets/pack-b/two.milk',), True)) in manager.calls

    handler._projectm_preview_dirty = True
    handler._projectm_preview_committed_path = '/tmp/presets/pack-a/one.milk'
    handler.handle(sdl2.SDLK_ESCAPE, 0)

    assert not overlay.projectm_manager_visible
    assert app.projectm_modal_active_calls[-1] is False
    assert ('goto_preset_path', '/tmp/presets/pack-a/one.milk') in manager.calls
    assert any('reverted' in msg.lower() for msg in overlay.messages)


def test_q_quarantines_an_excluded_preset() -> None:
    manager = _ManagerEffect()
    handler, _app, overlay = _setup(manager)
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)
    overlay.projectm_manager_focus_pane = 1
    overlay._selected_preset = {'path': '/tmp/quarantine-me.milk', 'enabled': False, 'kind': 'excluded'}

    handler.handle(sdl2.SDLK_q, 0)

    assert ('quarantine_preset', '/tmp/quarantine-me.milk') in manager.calls
    assert any('quarantined' in msg.lower() for msg in overlay.messages)


def test_q_on_a_non_excluded_preset_is_a_no_op() -> None:
    manager = _ManagerEffect()
    handler, _app, overlay = _setup(manager)
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)
    overlay.projectm_manager_focus_pane = 1
    overlay._selected_preset = {'path': '/tmp/presets/pack-a/one.milk', 'enabled': True}

    handler.handle(sdl2.SDLK_q, 0)

    assert not any(name == 'quarantine_preset' for name, _ in manager.calls)
    assert any('excluded category' in msg.lower() for msg in overlay.messages)


def test_r_restores_a_quarantined_preset() -> None:
    manager = _ManagerEffect()
    handler, _app, overlay = _setup(manager)
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)
    overlay.projectm_manager_focus_pane = 1
    overlay._selected_preset = {'path': '/tmp/restore-me.milk', 'enabled': False, 'kind': 'quarantined'}

    handler.handle(sdl2.SDLK_r, 0)

    assert ('restore_from_quarantine', '/tmp/restore-me.milk') in manager.calls
    assert any('restored' in msg.lower() for msg in overlay.messages)


def test_r_on_a_non_quarantined_preset_is_a_no_op() -> None:
    manager = _ManagerEffect()
    handler, _app, overlay = _setup(manager)
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)
    overlay.projectm_manager_focus_pane = 1
    overlay._selected_preset = {'path': '/tmp/presets/pack-a/one.milk', 'enabled': True}

    handler.handle(sdl2.SDLK_r, 0)

    assert not any(name == 'restore_from_quarantine' for name, _ in manager.calls)
    assert any('quarantined category' in msg.lower() for msg in overlay.messages)


def test_delete_on_a_quarantined_preset_permanently_deletes_without_trash() -> None:
    manager = _ManagerEffect()
    handler, _app, overlay = _setup(manager)
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)
    overlay.projectm_manager_focus_pane = 1
    overlay._selected_preset = {'path': '/tmp/delete-me.milk', 'enabled': False, 'kind': 'quarantined'}

    handler.handle(sdl2.SDLK_DELETE, 0)

    assert ('delete_quarantined_preset', '/tmp/delete-me.milk') in manager.calls
    assert not any(name == 'delete_presets' for name, _ in manager.calls)
    assert any('permanently deleted' in msg.lower() for msg in overlay.messages)


def test_delete_on_a_normal_preset_still_uses_the_existing_trash_flow() -> None:
    """Quarantine's Delete override must not leak into ordinary browsing."""
    manager = _ManagerEffect()
    handler, _app, overlay = _setup(manager)
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)
    overlay.projectm_manager_focus_pane = 1
    overlay._selected_preset = {'path': '/tmp/presets/pack-b/two.milk', 'enabled': True}

    handler.handle(sdl2.SDLK_DELETE, 0)

    assert ('delete_presets', (('/tmp/presets/pack-b/two.milk',), False)) in manager.calls
    assert not any(name == 'delete_quarantined_preset' for name, _ in manager.calls)


def test_e_and_d_are_suppressed_for_excluded_and_quarantined_kinds() -> None:
    manager = _ManagerEffect()
    handler, _app, overlay = _setup(manager)
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)
    overlay.projectm_manager_focus_pane = 1
    overlay._selected_preset = {'path': '/tmp/excluded.milk', 'enabled': False, 'kind': 'excluded'}

    handler.handle(sdl2.SDLK_e, 0)
    handler.handle(sdl2.SDLK_d, 0)

    assert not any(name == 'set_presets_enabled' for name, _ in manager.calls)
    assert sum('not applicable' in msg.lower() for msg in overlay.messages) == 2


def test_shift_q_quarantines_the_whole_excluded_category() -> None:
    manager = _ManagerEffect()
    handler, _app, overlay = _setup(manager)
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)
    overlay.projectm_manager_focus_pane = 0
    overlay._category = manager.EXCLUDED_CATEGORY

    handler.handle(sdl2.SDLK_q, sdl2.KMOD_SHIFT)

    assert ('quarantine_category', manager.EXCLUDED_CATEGORY) in manager.calls
    assert any('quarantined 3' in msg.lower() for msg in overlay.messages)


def test_shift_q_quarantines_the_whole_disabled_category() -> None:
    manager = _ManagerEffect()
    handler, _app, overlay = _setup(manager)
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)
    overlay.projectm_manager_focus_pane = 0
    overlay._category = manager.DISABLED_CATEGORY

    handler.handle(sdl2.SDLK_q, sdl2.KMOD_SHIFT)

    assert ('quarantine_category', manager.DISABLED_CATEGORY) in manager.calls
    assert any('quarantined 3' in msg.lower() for msg in overlay.messages)


def test_shift_q_is_a_no_op_for_a_normal_category() -> None:
    manager = _ManagerEffect()
    handler, _app, overlay = _setup(manager)
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)
    overlay.projectm_manager_focus_pane = 0
    overlay._category = 'Fractal'

    handler.handle(sdl2.SDLK_q, sdl2.KMOD_SHIFT)

    assert not any(name == 'quarantine_category' for name, _ in manager.calls)
    assert any('only applies' in msg.lower() for msg in overlay.messages)


def test_shift_q_requires_the_categories_pane() -> None:
    manager = _ManagerEffect()
    handler, _app, overlay = _setup(manager)
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)
    overlay.projectm_manager_focus_pane = 1
    overlay._category = manager.EXCLUDED_CATEGORY

    handler.handle(sdl2.SDLK_q, sdl2.KMOD_SHIFT)

    assert not any(name == 'quarantine_category' for name, _ in manager.calls)
    assert any('categories pane' in msg.lower() for msg in overlay.messages)


def test_shift_q_reports_when_nothing_to_quarantine() -> None:
    manager = _ManagerEffect()
    manager.quarantine_category_result = 0
    handler, _app, overlay = _setup(manager)
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)
    overlay.projectm_manager_focus_pane = 0
    overlay._category = manager.EXCLUDED_CATEGORY

    handler.handle(sdl2.SDLK_q, sdl2.KMOD_SHIFT)

    assert ('quarantine_category', manager.EXCLUDED_CATEGORY) in manager.calls
    assert any('nothing to quarantine' in msg.lower() for msg in overlay.messages)


def test_plain_q_still_targets_a_single_excluded_preset_when_shift_is_not_held() -> None:
    """Shift+Q must not swallow the pre-existing single-item 'q' binding."""
    manager = _ManagerEffect()
    handler, _app, overlay = _setup(manager)
    handler.handle(sdl2.SDLK_m, sdl2.KMOD_CTRL)
    overlay.projectm_manager_focus_pane = 1
    overlay._selected_preset = {'path': '/tmp/quarantine-me.milk', 'enabled': False, 'kind': 'excluded'}

    handler.handle(sdl2.SDLK_q, 0)

    assert ('quarantine_preset', '/tmp/quarantine-me.milk') in manager.calls
    assert not any(name == 'quarantine_category' for name, _ in manager.calls)
