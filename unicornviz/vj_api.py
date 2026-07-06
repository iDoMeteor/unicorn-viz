"""Public VJ automation API for unicorn-viz.

This module defines the stable automation surface exposed as ``App.vj_api``.
Phase 1 implementation is intentionally conservative: wrappers are added without
changing runtime behavior unless explicitly called by a controller.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from unicornviz.effects.registry import get_effects

if TYPE_CHECKING:
    import moderngl

    from unicornviz.app import App


VJ_API_VERSION = (1, 0, 0)

log = logging.getLogger(__name__)

__all__ = ['VJ_API_VERSION', 'VJState', 'VJApi']


@dataclass(slots=True)
class VJState:
    """Serializable snapshot of app state for automation logic."""

    effect_name: str
    playlist_mode: str
    playlist_index: int
    playlist_size: int
    auto_advance: bool
    paused: bool
    fullscreen: bool
    is_transitioning: bool
    advance_interval: float
    advance_time_remaining: float
    reactivity: float
    speed: float | None
    zoom: float | None
    audio_source: str
    invert: bool
    is_postfx_active: bool
    postfx_slot: int
    is_dancing_active: bool
    is_nova_active: bool
    is_burst_active: bool
    recording_active: bool
    streaming_active: bool
    streaming_provider: str
    display_mode: str
    display_index: int
    user_busy: bool
    manual_grace_remaining_s: float
    status_pill: str
    session_elapsed_s: float
    session_remaining_s: float | None


class VJApi:
    """Stable, public automation surface for system-driven control."""

    VERSION = VJ_API_VERSION

    def __init__(self, app: App) -> None:
        self._app = app
        self._key_handlers: dict[str, Callable[[int, int], 'str | None | bool']] = {}

    @property
    def ctx(self) -> moderngl.Context | None:
        """Return the active moderngl context, or ``None`` before init."""
        return self._app._ctx  # noqa: SLF001

    @property
    def render_width(self) -> int:
        """Return the app's logical render width."""
        return int(self._app._width)  # noqa: SLF001

    @property
    def render_height(self) -> int:
        """Return the app's logical render height."""
        return int(self._app._height)  # noqa: SLF001

    def has_postfx(self) -> bool:
        """Return True when the post-FX controller is available."""
        return self._app._postfx_controller is not None  # noqa: SLF001

    def register_subsystem(self, name: str, subsystem: object) -> bool:
        """Register a runtime subsystem with the main app loop."""
        return self._app.register_subsystem(name, subsystem)

    def unregister_subsystem(self, name: str) -> None:
        """Unregister a runtime subsystem previously added via ``register_subsystem``."""
        self._app.unregister_subsystem(name)

    def has_subsystem(self, name: str) -> bool:
        """Return True when a named runtime subsystem is registered."""
        return self._app.has_subsystem(name)

    def get_subsystem(self, name: str) -> object | None:
        """Return a named runtime subsystem instance when registered."""
        return self._app.get_subsystem(name)

    def list_subsystems(self) -> list[str]:
        """Return the names of all currently registered runtime subsystems.

        Useful for drop-ins that need to coordinate with other subsystems at
        runtime (e.g. an automation controller checking whether streaming or
        the control room is active).
        """
        return self._app.list_subsystems()

    def get_runtime_state(self, dotted_path: str = '', default: object | None = None) -> object:
        """Read a value from shared runtime state using dotted-path keys."""
        return self._app.get_runtime_state(str(dotted_path), default)

    def set_runtime_state(self, dotted_path: str, value: object) -> bool:
        """Set a value in shared runtime state using dotted-path keys."""
        key = str(dotted_path).strip()
        if not key:
            return False
        self._app.set_runtime_state(key, value)
        return True

    def claim_window_events(self, window_id: int, handler) -> bool:
        """Claim SDL events for a subsystem-owned window id."""
        return self._app.claim_window_events(window_id, handler)

    def release_window_events(self, window_id: int) -> None:
        """Release SDL event ownership for a subsystem window."""
        self._app.release_window_events(window_id)

    def rebind_main_gl_context(self) -> bool:
        """Re-bind the main audience window's GL context as current.

        Subsystems that create or destroy secondary SDL windows should call this
        afterwards so any GL state implicitly migrated by the windowing system is
        restored to the audience window.  Returns True on success.
        """
        return self._app.rebind_main_gl_context()

    def get_frame_bytes(self) -> bytes | None:
        """Return the latest cached audience-output frame bytes, if available."""
        frame, _width, _height, _components = self._app.get_frame_capture()
        return frame

    def get_frame_size(self) -> tuple[int, int, int]:
        """Return (width, height, components) for the cached frame snapshot."""
        _frame, width, height, components = self._app.get_frame_capture()
        return width, height, components

    def state(self) -> VJState:
        app = self._app
        effect_name = '-'
        speed = None
        zoom = None
        if app._current_effect is not None:  # noqa: SLF001
            effect_name = app._current_effect.NAME  # noqa: SLF001
            if 'speed' in app._current_effect.parameters:  # noqa: SLF001
                speed = float(app._current_effect.parameters['speed'])  # noqa: SLF001
            if 'zoom' in app._current_effect.parameters:  # noqa: SLF001
                zoom = float(app._current_effect.parameters['zoom'])  # noqa: SLF001

        reactivity = 1.0
        audio_source = '-'
        if app._audio_manager is not None:  # noqa: SLF001
            reactivity = float(app._audio_manager.get_reactivity())  # noqa: SLF001
            audio_source = str(app._audio_manager.get_source_label())  # noqa: SLF001

        postfx_slot = 0
        postfx_active = False
        if app._postfx_controller is not None:  # noqa: SLF001
            postfx_active = bool(app._postfx_controller.is_active())  # noqa: SLF001
            postfx_slot = int(getattr(app._postfx_controller, 'active_slot', 0))  # noqa: SLF001

        dancing_active = False
        if app._dancing_unicorn is not None:  # noqa: SLF001
            dancing_active = bool(getattr(app._dancing_unicorn, '_active', False))  # noqa: SLF001

        nova_active = False
        if app._rainbow_nova is not None:  # noqa: SLF001
            nova_active = bool(app._rainbow_nova.is_active)  # noqa: SLF001

        burst_active = bool(app._burst_controller.active)  # noqa: SLF001
        recording_active = bool(app._recorder is not None and app._recorder.is_recording)  # noqa: SLF001
        streaming_active = bool(app._streamer is not None and app._streamer.is_streaming)  # noqa: SLF001
        streaming_provider = '-'
        if app._streamer is not None:  # noqa: SLF001
            streaming_provider = str(getattr(app._streamer, 'provider', '-'))  # noqa: SLF001

        return VJState(
            effect_name=effect_name,
            playlist_mode=str(getattr(app, '_playlist_mode', 'unknown')),  # noqa: SLF001
            playlist_index=int(getattr(app, '_playlist_index', -1)),  # noqa: SLF001
            playlist_size=int(getattr(app, '_playlist_size', 0)),  # noqa: SLF001
            auto_advance=bool(app._auto_advance),  # noqa: SLF001
            paused=bool(app._paused),  # noqa: SLF001
            fullscreen=bool(app._fullscreen),  # noqa: SLF001
            is_transitioning=bool(app._next_effect is not None),  # noqa: SLF001
            advance_interval=float(app._effect_duration),  # noqa: SLF001
            advance_time_remaining=max(0.0, float(app._effect_duration - app._demo_timer)),  # noqa: SLF001
            reactivity=reactivity,
            speed=speed,
            zoom=zoom,
            audio_source=audio_source,
            invert=bool(app._invert_colors),  # noqa: SLF001
            is_postfx_active=postfx_active,
            postfx_slot=postfx_slot,
            is_dancing_active=dancing_active,
            is_nova_active=nova_active,
            is_burst_active=burst_active,
            recording_active=recording_active,
            streaming_active=streaming_active,
            streaming_provider=streaming_provider,
            display_mode=str(getattr(app, '_display_mode', 'single')),  # noqa: SLF001
            display_index=int(getattr(app, '_display_index', 0)),  # noqa: SLF001
            user_busy=self.is_user_busy(),
            manual_grace_remaining_s=max(0.0, float(app._user_action_deadline - time.monotonic())),  # noqa: SLF001
            status_pill=str(getattr(app, '_vj_status_pill', '')),  # noqa: SLF001
            session_elapsed_s=float(self.get_elapsed_time()),
            session_remaining_s=self.get_time_remaining(),
        )

    def goto_effect(self, target: 'str | type') -> bool:
        """Navigate to a named or class-referenced effect.

        ``target`` may be a display-name/class-name string or a class object.
        """
        if isinstance(target, type):
            self._app.goto_effect(target)
            return True
        name = str(target).strip().lower()
        if not name:
            return False
        for cls in get_effects():
            if cls.NAME.lower() == name or cls.__name__.lower() == name:
                self._app.goto_effect(cls)
                return True
        return False

    def lock_effect(self, name: str) -> None:
        """Pin the system to the effect with display NAME *name* (ProjectM-only
        mode / future effects-browser 'pin'). Does not itself switch effects."""
        self._app.lock_effect(name)

    def unlock_effect(self) -> None:
        """Clear any effect lock so normal rotation resumes."""
        self._app.unlock_effect()

    @property
    def effect_lock(self) -> 'str | None':
        """Display NAME of the locked effect, or None when not locked."""
        return self._app.effect_lock

    def toggle_projectm_only(self) -> tuple[bool, str]:
        """Toggle ProjectM-only mode; returns (is_on, status message)."""
        return self._app.toggle_projectm_only()

    def find_effect(self, class_name: str, display_name: str | None = None) -> type | None:
        """Return the effect class matching *class_name* or (optionally) *display_name*.

        Returns ``None`` when no matching effect is registered.
        """
        for cls in get_effects():
            if cls.__name__ == class_name or (display_name and cls.NAME == display_name):
                return cls
        return None

    def show_splash(self) -> None:
        """Replay the startup splash sequence."""
        self._app.show_splash()  # noqa: SLF001

    def projectm_available(self) -> bool:
        """Return True when a ProjectMEffect class is registered as a discoverable effect."""
        return self.find_effect('ProjectMEffect', 'ProjectM Presets') is not None

    def projectm_active(self) -> bool:
        """Return True when ProjectMEffect is the currently displayed effect."""
        try:
            inst = self._app._current_effect  # noqa: SLF001
            return inst is not None and type(inst).__name__ == 'ProjectMEffect'
        except Exception:
            return False

    def projectm_preset_count(self) -> int:
        """Return the number of loaded projectM presets (0 when not active or unavailable)."""
        try:
            inst = self._app._current_effect  # noqa: SLF001
            if inst is None or type(inst).__name__ != 'ProjectMEffect':
                return 0
            return int(getattr(inst, 'preset_count', 0) or 0)
        except Exception:
            return 0

    def projectm_next_preset(self) -> str | None:
        """Advance to the next projectM preset; returns label or None."""
        try:
            inst = self._app._current_effect  # noqa: SLF001
            if inst is None or type(inst).__name__ != 'ProjectMEffect':
                return None
            return inst.next_preset()  # type: ignore[union-attr]
        except Exception:
            return None

    def projectm_prev_preset(self) -> str | None:
        """Step to the previous projectM preset; returns label or None."""
        try:
            inst = self._app._current_effect  # noqa: SLF001
            if inst is None or type(inst).__name__ != 'ProjectMEffect':
                return None
            return inst.prev_preset()  # type: ignore[union-attr]
        except Exception:
            return None

    def projectm_random_preset(self) -> str | None:
        """Jump to a random projectM preset; returns label or None."""
        try:
            inst = self._app._current_effect  # noqa: SLF001
            if inst is None or type(inst).__name__ != 'ProjectMEffect':
                return None
            return inst.random_preset()  # type: ignore[union-attr]
        except Exception:
            return None

    def projectm_goto_preset(self, index: int) -> str | None:
        """Go to a specific preset by index; returns label or None."""
        try:
            inst = self._app._current_effect  # noqa: SLF001
            if inst is None or type(inst).__name__ != 'ProjectMEffect':
                return None
            return inst.goto_preset(int(index))  # type: ignore[union-attr]
        except Exception:
            return None

    def is_effect_enabled(self, name: str) -> bool:
        """Return whether an effect (by display or class name) is rotation-enabled."""
        return self._app.effect_enabled(name)

    def enabled_effect_classes(self) -> list[type]:
        """Return effect classes the operator has not disabled from rotation."""
        return [cls for cls in get_effects() if self._app.effect_enabled(cls.NAME)]

    def goto_random_effect(self, tags: list[str] | None = None, exclude_current: bool = True) -> str | None:
        # Only auto-select effects the operator has left enabled.
        effects = self.enabled_effect_classes()
        if exclude_current and self._app._current_effect is not None:  # noqa: SLF001
            cur_name = self._app._current_effect.__class__.__name__  # noqa: SLF001
            effects = [cls for cls in effects if cls.__name__ != cur_name]
        if tags:
            tag_set = {t.lower() for t in tags}
            filtered: list[type] = []
            for cls in effects:
                cls_tags = {str(t).lower() for t in getattr(cls, 'TAGS', [])}
                if cls_tags & tag_set:
                    filtered.append(cls)
            effects = filtered
        if not effects:
            return None
        cls = self._app._rng.choice(effects)  # noqa: SLF001
        self._app.goto_effect(cls)
        return cls.NAME

    def list_effects(self) -> list[tuple[str, list[str]]]:
        # Sourced from the shared catalog helper so the control-room list and the
        # effects browser modal stay in lockstep (same order, same tags).
        from unicornviz.effects.registry import browser_entries
        return [(e.name, list(e.tags)) for e in browser_entries()]

    def get_audio_sources(self) -> list[str]:
        """Return available audio capture source labels."""
        try:
            return self._app.get_audio_sources()
        except Exception:
            return []

    def get_audio_source_index(self) -> int:
        """Return the currently active audio source index."""
        try:
            return int(self._app.get_audio_source_index())
        except Exception:
            return 0

    def get_audio_source_viable_flags(self) -> list[bool]:
        """Return current per-source viability flags for audio selector UIs."""
        try:
            return [bool(v) for v in self._app.get_audio_source_viable_flags()]
        except Exception:
            return []

    def select_audio_source(self, index: int) -> str:
        """Select a specific audio source index and return status text."""
        try:
            return str(self._app.select_audio_source(int(index)))
        except Exception:
            return 'Audio source selection failed'

    def toggle_audio_source_viable(self, index: int) -> str:
        """Toggle viability for an audio source row and return status text."""
        try:
            return str(self._app.toggle_audio_source_viable(int(index)))
        except Exception:
            return 'Audio source viability update failed'

    def sync_audio_selector(self) -> None:
        """Refresh overlay audio-selector rows from current runtime source state."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            overlays.set_audio_sources(
                self._app.get_audio_sources(),
                self._app.get_audio_source_index(),
                self._app.get_audio_source_viable_flags(),
            )
        except Exception:
            return

    def close_audio_selector(self) -> None:
        """Close the audio selector overlay when currently open."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if bool(getattr(overlays, 'audio_selector_visible', False)):
                overlays.toggle_audio_selector()
        except Exception:
            return

    def open_audio_selector(self) -> bool:
        """Open the audio selector overlay and sync its row state."""
        try:
            self.sync_audio_selector()
            overlays = self._app._overlays  # noqa: SLF001
            if not bool(getattr(overlays, 'audio_selector_visible', False)):
                overlays.toggle_audio_selector()
            return True
        except Exception:
            return False

    def set_audio_selector_index(self, index: int) -> int:
        """Set highlighted audio selector row and return clamped index."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            setter = getattr(overlays, 'set_audio_selected_index', None)
            if callable(setter):
                return int(setter(int(index)))
        except Exception:
            pass
        return 0

    def get_audio_selector_index(self) -> int:
        """Return highlighted audio selector row index."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            getter = getattr(overlays, 'get_audio_selected_index', None)
            if callable(getter):
                return int(getter())
        except Exception:
            pass
        return 0

    def sync_midi_selector(self) -> None:
        """Refresh overlay MIDI-selector rows from current runtime port state."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            current = ''
            manager = getattr(self._app, '_midi_manager', None)  # noqa: SLF001
            if manager is not None:
                current = str(getattr(manager, 'port_name', '') or '')
            overlays.set_midi_ports(self._app.get_midi_ports(), current)
        except Exception:
            return

    def close_midi_selector(self) -> None:
        """Close the MIDI selector overlay when currently open."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if bool(getattr(overlays, 'midi_selector_visible', False)):
                overlays.toggle_midi_selector()
        except Exception:
            return

    def open_midi_selector(self) -> bool:
        """Open the MIDI selector overlay and sync its row state."""
        try:
            self.sync_midi_selector()
            overlays = self._app._overlays  # noqa: SLF001
            if not bool(getattr(overlays, 'midi_selector_visible', False)):
                overlays.toggle_midi_selector()
            return True
        except Exception:
            return False

    def set_midi_selector_index(self, index: int) -> int:
        """Set highlighted MIDI selector row and return clamped index."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            setter = getattr(overlays, 'set_midi_selected_index', None)
            if callable(setter):
                return int(setter(int(index)))
        except Exception:
            pass
        return 0

    def get_midi_selector_index(self) -> int:
        """Return highlighted MIDI selector row index."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            getter = getattr(overlays, 'get_midi_selected_index', None)
            if callable(getter):
                return int(getter())
        except Exception:
            pass
        return 0

    def select_midi_device(self, port_name: str) -> str:
        """Select a MIDI input device by name (empty string disables MIDI)."""
        try:
            return str(self._app.select_midi_device(str(port_name)))
        except Exception:
            return 'MIDI selection failed'

    def close_webcam_editor_modal(self) -> None:
        """Close the webcam editor overlay modal when currently open."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if bool(getattr(overlays, 'webcam_editor_modal_visible', False)):
                overlays.toggle_webcam_editor_modal()
        except Exception:
            return

    def open_webcam_editor_modal(self) -> bool:
        """Open the webcam editor overlay modal."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if not bool(getattr(overlays, 'webcam_editor_modal_visible', False)):
                overlays.toggle_webcam_editor_modal()
            return True
        except Exception:
            return False

    def close_system_monitor_modal(self) -> None:
        """Close system monitor overlay modal when currently open."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if bool(getattr(overlays, 'system_monitor_modal_visible', False)):
                overlays.toggle_system_monitor_modal()
        except Exception:
            return

    def open_system_monitor_modal(self) -> bool:
        """Open system monitor overlay modal."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if not bool(getattr(overlays, 'system_monitor_modal_visible', False)):
                overlays.toggle_system_monitor_modal()
            return True
        except Exception:
            return False

    def close_controller_help_modal(self) -> None:
        """Close controller help overlay modal when currently open."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if bool(getattr(overlays, 'controller_help_modal_visible', False)):
                overlays.toggle_controller_help_modal()
        except Exception:
            return

    def open_controller_help_modal(self) -> bool:
        """Open controller help overlay modal."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if not bool(getattr(overlays, 'controller_help_modal_visible', False)):
                overlays.toggle_controller_help_modal()
            return True
        except Exception:
            return False

    def close_projectm_manager(self) -> None:
        """Close the ProjectM manager overlay modal when currently open."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if bool(getattr(overlays, 'projectm_manager_visible', False)):
                overlays.toggle_projectm_manager()
        except Exception:
            return

    def open_projectm_manager(self) -> bool:
        """Open the ProjectM manager overlay modal and sync manager catalog."""
        try:
            self.sync_projectm_manager()
            overlays = self._app._overlays  # noqa: SLF001
            if not bool(getattr(overlays, 'projectm_manager_visible', False)):
                overlays.toggle_projectm_manager()
            return True
        except Exception:
            return False

    def open_effects_browser(self) -> bool:
        """Open the effects browser modal (keyboard + mouse, live preview)."""
        try:
            self._app.open_effects_browser()
            return True
        except Exception:
            return False

    def effects_browser_active(self) -> bool:
        """Return whether the effects browser modal is open."""
        return bool(getattr(self._app, 'effects_browser_active', False))

    def open_presets(self) -> bool:
        """Open the show-presets modal."""
        try:
            self._app.open_presets()
            return True
        except Exception:
            return False

    def presets_active(self) -> bool:
        """Return whether the show-presets modal is open."""
        try:
            return bool(self._app.presets_modal_active)
        except Exception:
            return False

    def toggle_help_overlay(self) -> bool:
        """Toggle help overlay visibility; returns new visible state when known."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            overlays.toggle_help()
            return bool(getattr(overlays, 'help_visible', False))
        except Exception:
            return False

    def toggle_hud_overlay(self) -> bool:
        """Toggle HUD/name overlay visibility; returns new visible state when known."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            overlays.toggle_name_overlay()
            return bool(getattr(overlays, 'name_overlay_visible', False))
        except Exception:
            return False

    def close_help_overlay(self) -> None:
        """Close help overlay when currently visible."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if bool(getattr(overlays, 'help_visible', False)):
                overlays.toggle_help()
        except Exception:
            return

    def help_move_focus(self, delta: int) -> bool:
        """Move help section focus by delta; returns True if overlays support it."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            return bool(overlays.move_help_focus(int(delta)))
        except Exception:
            return False

    def help_set_focus(self, index: int) -> bool:
        """Set help section focus to a specific index."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            n = int(getattr(overlays, 'help_section_count', lambda: 0)())
            if 0 <= index < n:
                overlays.move_help_focus(index - overlays._help_focus_idx)  # noqa: SLF001
                return True
            return False
        except Exception:
            return False

    def close_hud_overlay(self) -> None:
        """Close HUD/name overlay when currently visible."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            if bool(getattr(overlays, 'name_overlay_visible', False)):
                overlays.toggle_name_overlay()
        except Exception:
            return

    def system_telemetry_snapshot(self) -> dict[str, float]:
        """Return current system telemetry for operator surfaces."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            sample = getattr(overlays, '_sample_system_telemetry', None)
            if callable(sample):
                sample()
            return {
                'cpu': float(getattr(overlays, '_sysmon_cpu', 0.0) or 0.0),
                'ram': float(getattr(overlays, '_sysmon_ram', 0.0) or 0.0),
                'swap': float(getattr(overlays, '_sysmon_swap', 0.0) or 0.0),
                'disk_mbs': float(getattr(overlays, '_sysmon_disk_mbs', 0.0) or 0.0),
                'net_mbs': float(getattr(overlays, '_sysmon_net_mbs', 0.0) or 0.0),
            }
        except Exception:
            return {
                'cpu': 0.0,
                'ram': 0.0,
                'swap': 0.0,
                'disk_mbs': 0.0,
                'net_mbs': 0.0,
            }

    def auto_vj_snapshot(self) -> dict[str, object]:
        """Return Auto VJ runtime state for operator/control-room surfaces."""
        try:
            auto_vj = getattr(self._app, '_auto_vj', None)  # noqa: SLF001
            hud = getattr(self._app, '_hud_state', {})  # noqa: SLF001
            if not isinstance(hud, dict):
                hud = {}
            available = auto_vj is not None
            return {
                'available': bool(available),
                'enabled': bool(getattr(auto_vj, 'enabled', False)) if available else False,
                'status': str(getattr(auto_vj, 'status_text', 'AUTO VJ OFF')) if available else 'AUTO VJ UNAVAILABLE',
                'profile': str(getattr(auto_vj, '_profile', '-')) if available else '-',  # noqa: SLF001
                'mode': str(getattr(auto_vj, '_mode', '-')) if available else '-',  # noqa: SLF001
                'mood': str(hud.get('auto_vj_mood', '-') or '-'),
                'scene': str(hud.get('auto_vj_scene', '-') or '-'),
                'bpm': str(hud.get('auto_vj_bpm', '--') or '--'),
                'action_in': str(hud.get('auto_vj_action_in', '--') or '--'),
                'audio_profile': str(hud.get('audio_profile', '-') or '-'),
                'audio_profile_reco': str(hud.get('audio_profile_reco', '-') or '-'),
            }
        except Exception:
            return {
                'available': False,
                'enabled': False,
                'status': 'AUTO VJ UNAVAILABLE',
                'profile': '-',
                'mode': '-',
                'mood': '-',
                'scene': '-',
                'bpm': '--',
                'action_in': '--',
                'audio_profile': '-',
                'audio_profile_reco': '-',
            }

    def sync_projectm_manager(self) -> bool:
        """Refresh ProjectM manager entries from the active effect and return success."""
        try:
            manager_effect = self._app.resolve_projectm_manager_effect()
            if manager_effect is None:
                return False
            catalog_getter = getattr(manager_effect, 'preset_catalog', None)
            if not callable(catalog_getter):
                return False
            overlays = self._app._overlays  # noqa: SLF001
            current_path = str(getattr(manager_effect, 'current_preset_path', '') or '')
            overlays.set_projectm_manager_entries(catalog_getter(), current_path)
            return True
        except Exception:
            return False

    def set_projectm_focus_pane(self, pane: int) -> int:
        """Set ProjectM manager focus pane (0=category, 1=preset)."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            setter = getattr(overlays, 'set_projectm_focus_pane', None)
            if callable(setter):
                return int(setter(int(pane)))
        except Exception:
            pass
        return 1 if int(pane) > 0 else 0

    def set_projectm_category_index(self, index: int) -> int:
        """Set ProjectM manager category row index and return clamped value."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            setter = getattr(overlays, 'set_projectm_category_index', None)
            if callable(setter):
                return int(setter(int(index)))
        except Exception:
            pass
        return 0

    def set_projectm_preset_index(self, index: int) -> int:
        """Set ProjectM manager preset row index and return clamped value."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            setter = getattr(overlays, 'set_projectm_preset_index', None)
            if callable(setter):
                return int(setter(int(index)))
        except Exception:
            pass
        return 0

    def apply_selected_projectm_preset(self) -> str | None:
        """Apply currently selected ProjectM manager preset and return active label."""
        try:
            manager_effect = self._app.resolve_projectm_manager_effect()
            if manager_effect is None:
                return None
            goto = getattr(manager_effect, 'goto_preset_path', None)
            if not callable(goto):
                return None
            overlays = self._app._overlays  # noqa: SLF001
            selected_getter = getattr(overlays, 'get_projectm_selected_preset', None)
            if not callable(selected_getter):
                return None
            selected = selected_getter()
            if not isinstance(selected, dict):
                return None
            if not bool(selected.get('enabled', False)):
                return None
            path = str(selected.get('path', '') or '')
            if not path:
                return None
            result = goto(path)
            self.sync_projectm_manager()
            return str(result) if result else None
        except Exception:
            return None

    def projectm_enable_selected_category(self) -> tuple[str, int] | None:
        """Enable all presets in selected ProjectM category; returns category and enabled count."""
        try:
            manager_effect = self._app.resolve_projectm_manager_effect()
            if manager_effect is None:
                return None
            overlays = self._app._overlays  # noqa: SLF001
            get_category = getattr(overlays, 'get_projectm_selected_category', None)
            if not callable(get_category):
                return None
            category = str(get_category() or '(all)')
            if category == '(all)':
                remaining = int(manager_effect.enable_all_presets())
            else:
                remaining = int(manager_effect.enable_category(category))
            self.sync_projectm_manager()
            return (category, remaining)
        except Exception:
            return None

    def projectm_disable_selected_category(self) -> tuple[str, int] | None:
        """Disable all presets in selected ProjectM category; returns category and enabled count."""
        try:
            manager_effect = self._app.resolve_projectm_manager_effect()
            if manager_effect is None:
                return None
            overlays = self._app._overlays  # noqa: SLF001
            get_category = getattr(overlays, 'get_projectm_selected_category', None)
            if not callable(get_category):
                return None
            category = str(get_category() or '(all)')
            if category == '(all)':
                remaining = int(manager_effect.disable_all_presets())
            else:
                remaining = int(manager_effect.disable_category(category))
            self.sync_projectm_manager()
            return (category, remaining)
        except Exception:
            return None

    def projectm_isolate_selected_category(self) -> tuple[str, int] | None:
        """Enable only selected ProjectM category; returns category and enabled count."""
        try:
            manager_effect = self._app.resolve_projectm_manager_effect()
            if manager_effect is None:
                return None
            overlays = self._app._overlays  # noqa: SLF001
            get_category = getattr(overlays, 'get_projectm_selected_category', None)
            if not callable(get_category):
                return None
            category = str(get_category() or '(all)')
            if category == '(all)':
                remaining = int(manager_effect.enable_all_presets())
            else:
                remaining = int(manager_effect.isolate_category(category))
            self.sync_projectm_manager()
            return (category, remaining)
        except Exception:
            return None

    def projectm_set_selected_preset_enabled(self, enabled: bool) -> int | None:
        """Set selected ProjectM preset enabled state; returns enabled preset count."""
        try:
            manager_effect = self._app.resolve_projectm_manager_effect()
            if manager_effect is None:
                return None
            overlays = self._app._overlays  # noqa: SLF001
            get_selected = getattr(overlays, 'get_projectm_selected_preset', None)
            if not callable(get_selected):
                return None
            selected = get_selected()
            if not isinstance(selected, dict):
                return None
            path = str(selected.get('path', '') or '')
            if not path:
                return None
            remaining = int(manager_effect.set_presets_enabled([path], bool(enabled)))
            self.sync_projectm_manager()
            return remaining
        except Exception:
            return None

    def projectm_undo_last_bulk_state_change(self) -> str | None:
        """Undo last ProjectM bulk state snapshot and return restored preset label."""
        try:
            manager_effect = self._app.resolve_projectm_manager_effect()
            if manager_effect is None:
                return None
            undo = getattr(manager_effect, 'undo_last_bulk_state_change', None)
            if not callable(undo):
                return None
            restored = undo()
            self.sync_projectm_manager()
            return str(restored) if restored else None
        except Exception:
            return None

    def projectm_redo_last_bulk_state_change(self) -> str | None:
        """Redo last ProjectM bulk state snapshot and return restored preset label."""
        try:
            manager_effect = self._app.resolve_projectm_manager_effect()
            if manager_effect is None:
                return None
            redo = getattr(manager_effect, 'redo_last_bulk_state_change', None)
            if not callable(redo):
                return None
            restored = redo()
            self.sync_projectm_manager()
            return str(restored) if restored else None
        except Exception:
            return None

    def set_auto_advance(self, enabled: bool) -> None:
        self._app._auto_advance = bool(enabled)  # noqa: SLF001

    def toggle_pause(self) -> bool:
        """Toggle playback pause and return the new paused state."""
        self._app.toggle_pause()
        return bool(self._app.paused)

    def toggle_recording(self) -> tuple[bool, str]:
        """Toggle recording on or off."""
        return self._app.toggle_recording()

    def toggle_streaming(self) -> tuple[bool, str]:
        """Toggle RTMP streaming on or off."""
        return self._app.toggle_streaming()

    def trigger_cta_custom(
        self,
        text: str,
        icon: str = '',
        duration: 'float | None' = None,
    ) -> None:
        """Trigger a custom CTA message on the main overlay."""
        overlays = getattr(self._app, '_overlays', None)
        if overlays is not None:
            overlays.trigger_cta_custom(str(text), str(icon), duration)

    def toggle_control_room(self) -> tuple[bool, str]:
        """Toggle the operator control-room window."""
        return self._app.toggle_control_room()

    def set_display_mode(self, mode: str | None = None, reset_to_config: bool = False) -> str:
        """Set the main audience display mode."""
        return self._app.set_display_mode(mode, reset_to_config=reset_to_config)

    def supported_display_modes(self) -> tuple[str, ...]:
        """Return display modes currently supported by the runtime."""
        getter = getattr(self._app, 'supported_display_modes', None)
        if not callable(getter):
            return ('single',)
        try:
            modes = getter()
        except Exception:
            return ('single',)
        out = tuple(str(mode).strip().lower() for mode in modes if str(mode).strip())
        return out or ('single',)

    def set_advance_interval(self, seconds: float) -> float:
        self._app._effect_duration = max(10.0, float(seconds))  # noqa: SLF001
        return float(self._app._effect_duration)  # noqa: SLF001

    def reset_advance_interval(self) -> float:
        return float(self._app.reset_advance_interval())

    def set_show_duration(self, seconds: float | None) -> None:
        """Set optional session/show duration in seconds.

        ``None`` (or non-positive value) disables countdown mode.
        """
        if seconds is None:
            self._app._show_duration_s = None  # noqa: SLF001
            return
        val = float(seconds)
        self._app._show_duration_s = val if val > 0.0 else None  # noqa: SLF001

    def get_elapsed_time(self) -> float:
        """Return session elapsed seconds since app run-loop start."""
        started = float(getattr(self._app, '_session_started_at', 0.0))  # noqa: SLF001
        if started <= 0.0:
            return 0.0
        return max(0.0, float(time.monotonic() - started))

    def get_time_remaining(self) -> float | None:
        """Return remaining seconds to configured show end, or ``None`` if unlimited."""
        duration = getattr(self._app, '_show_duration_s', None)  # noqa: SLF001
        if duration is None:
            return None
        return max(0.0, float(duration) - self.get_elapsed_time())

    def format_session_clock(self) -> str:
        """Return elapsed session time as ``MM:SS`` or ``HH:MM:SS``.

        This is a public helper for UI surfaces (HUD/overlays/log views)
        that need a stable, human-readable runtime clock.
        """
        elapsed = max(0, int(self.get_elapsed_time()))
        minutes, seconds = divmod(elapsed, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f'{hours:02d}:{minutes:02d}:{seconds:02d}'
        return f'{minutes:02d}:{seconds:02d}'

    def set_reactivity(self, value: float) -> float:
        if self._app._audio_manager is None:  # noqa: SLF001
            return 1.0
        return float(self._app._audio_manager.set_reactivity(value))  # noqa: SLF001

    def set_speed(self, value: float) -> float | None:
        effect = self._app._current_effect  # noqa: SLF001
        if effect is None or 'speed' not in effect.parameters:
            return None
        prev_speed = float(effect.parameters['speed'])
        new_speed = max(0.05, min(10.0, float(value)))
        # Intentional exception: when Auto VJ is actively running in the
        # raver profile, preserve the old discontinuous slew look on purpose.
        # Lower-third raver BPM (126-138: prog house, early trance) gets the
        # scramble only 1-in-3 calls — enough chaos without overwhelming slower
        # material.  Mid (138-155) and fast (155+) raver run it every time.
        auto_vj = getattr(self._app, '_auto_vj', None)  # noqa: SLF001
        raver_scramble = False
        if (
            auto_vj is not None
            and bool(getattr(auto_vj, 'enabled', False))
            and str(getattr(auto_vj, '_profile', '')).lower() == 'raver'
        ):
            import random
            _grid = getattr(auto_vj, '_grid', None)
            _bpm = float(getattr(_grid, 'bpm', 0.0) or 0.0) if _grid is not None else 0.0
            if _bpm >= 138.0:
                raver_scramble = True
            else:
                raver_scramble = random.random() < (1.0 / 3.0)
        # Keep shader phase continuous for effects that use
        # t = iTime * (bias + scale * iSpeed).
        # Defaults match the common t = iTime * iSpeed case.
        if (not raver_scramble) and abs(new_speed - prev_speed) > 1e-9 and hasattr(effect, 'time'):
            try:
                t = float(getattr(effect, 'time'))
                bias = float(getattr(effect, 'SPEED_TIME_BIAS', 0.0))
                scale = float(getattr(effect, 'SPEED_TIME_SCALE', 1.0))
                prev_factor = bias + scale * prev_speed
                next_factor = bias + scale * new_speed
                if abs(prev_factor) > 1e-9 and abs(next_factor) > 1e-9:
                    setattr(effect, 'time', (t * prev_factor) / next_factor)
            except Exception:
                # Never fail speed changes due to continuity bookkeeping.
                pass
        effect.parameters['speed'] = new_speed
        return float(effect.parameters['speed'])

    def set_zoom(self, value: float) -> float | None:
        effect = self._app._current_effect  # noqa: SLF001
        if effect is None or 'zoom' not in effect.parameters:
            return None
        lo = float(self._app.cfg.get('hotkeys', 'zoom_min', default=0.1))  # noqa: SLF001
        hi = float(self._app.cfg.get('hotkeys', 'zoom_max', default=3.0))  # noqa: SLF001
        effect.parameters['zoom'] = max(lo, min(hi, float(value)))
        return float(effect.parameters['zoom'])

    def get_effect_parameters(self) -> dict[str, float]:
        """Return a copy of the current effect's tweakable parameters.

        Public surface for control surfaces (OSC bridge, control room) to
        enumerate live parameters without reaching into the current effect.
        """
        effect = self._app._current_effect  # noqa: SLF001
        if effect is None:
            return {}
        params = getattr(effect, 'parameters', None)
        return dict(params) if isinstance(params, dict) else {}

    def set_effect_parameter(self, name: str, value: float) -> float | None:
        """Set a named tweakable parameter on the current effect.

        Returns the new value, or ``None`` when the effect has no such
        parameter.  ``speed`` and ``zoom`` route through their dedicated setters
        to preserve phase-continuity / configured clamping; all other named
        parameters are assigned directly.
        """
        effect = self._app._current_effect  # noqa: SLF001
        if effect is None:
            return None
        params = getattr(effect, 'parameters', None)
        if not isinstance(params, dict) or name not in params:
            return None
        if name == 'speed':
            return self.set_speed(value)
        if name == 'zoom':
            return self.set_zoom(value)
        params[name] = float(value)
        return float(params[name])

    def set_invert(self, enabled: bool) -> bool:
        enabled = bool(enabled)
        if bool(self._app._invert_colors) != enabled:  # noqa: SLF001
            self._app.toggle_invert()
        return bool(self._app._invert_colors)  # noqa: SLF001

    def trigger_rainbow_nova(self) -> bool:
        if self._app._rainbow_nova is None:  # noqa: SLF001
            return False
        self._app.trigger_rainbow_nova()
        return True

    def trigger_screen_burst(self) -> bool:
        self._app.trigger_burst()
        return bool(self._app._burst_controller.active)  # noqa: SLF001

    def trigger_dancing_unicorn(self) -> bool:
        if self._app._dancing_unicorn is None:  # noqa: SLF001
            return False
        self._app.trigger_dancing_unicorn()
        return True

    def trigger_grand_finale(self) -> str:
        """Trigger the grand finale sequence; returns a flash-message string."""
        if self._app._grand_finale is None:  # noqa: SLF001
            return 'Grand Finale drop-in not loaded'
        return str(self._app.trigger_grand_finale())

    def abort_grand_finale(self) -> str:
        """Abort the grand finale and restore pre-finale state."""
        return str(self._app.abort_grand_finale())

    def toggle_auto_vj(self) -> str:
        """Toggle Auto VJ controller on/off; returns a flash-message string."""
        return str(self._app.toggle_auto_vj())

    def toggle_candy_frame(self) -> str:
        """Toggle the Candy Frame neon border on/off."""
        return str(self._app.toggle_candy_frame())

    def candy_frame_active(self) -> bool:
        """Return whether the Candy Frame overlay is currently active."""
        candy_frame = getattr(self._app, '_candy_frame', None)  # noqa: SLF001
        return bool(candy_frame is not None and bool(getattr(candy_frame, 'active', False)))

    def select_postfx_slot(self, slot: int) -> str:
        """Activate post-FX slot *slot* (1–10); returns a flash-message string."""
        return str(self._app.select_postfx_slot(int(slot)))

    def set_stream_provider(self, provider: str) -> str:
        """Switch the RTMP stream provider preset; returns provider name string."""
        return str(self._app.set_stream_provider(str(provider)))

    def set_camera_layout(self, token: str) -> bool:
        """Set the webcam PiP layout token ('0', '.', '1'–'9')."""
        return bool(self._app.set_camera_layout(str(token)))

    def scale_pip(self, delta: float) -> float:
        """Scale the webcam PiP overlay by *delta* fraction (+/- 0.05)."""
        return float(self._app.scale_pip(float(delta)))

    def goto_prev_webcam_effect(self) -> str | None:
        """Step to the previous webcam treatment; returns name or None."""
        return self._app.goto_prev_webcam_effect()

    def goto_next_webcam_effect(self) -> str | None:
        """Step to the next webcam treatment; returns name or None."""
        return self._app.goto_next_webcam_effect()

    def toggle_webcam_auto_cycle(self) -> bool:
        """Toggle the webcam treatment auto-cycle; returns new active state."""
        return bool(self._app.toggle_webcam_auto_cycle())

    def goto_prev_camera(self) -> str | None:
        """Switch to the previous camera device; returns device label or None."""
        return self._app.goto_prev_camera()

    def goto_next_camera(self) -> str | None:
        """Switch to the next camera device; returns device label or None."""
        return self._app.goto_next_camera()

    def list_webcam_cameras(self) -> list[dict[str, object]]:
        """Return detected webcam devices with enabled/selected metadata."""
        return self._app.list_webcam_cameras()

    def rediscover_webcam_cameras(self) -> list[dict[str, object]]:
        """Re-scan webcam devices and return refreshed camera metadata."""
        return self._app.rediscover_webcam_cameras()

    def set_webcam_camera_enabled(self, camera_id: int, enabled: bool) -> bool:
        """Enable or disable a webcam device by camera index."""
        return bool(self._app.set_webcam_camera_enabled(int(camera_id), bool(enabled)))

    def set_active_webcam_camera(self, camera_id: int) -> str | None:
        """Switch directly to a webcam device by camera index."""
        return self._app.set_active_webcam_camera(int(camera_id))

    def set_webcam_brightness(self, value: float) -> float:
        """Set webcam brightness multiplier and return clamped value."""
        return float(self._app.set_webcam_brightness(float(value)))

    def set_webcam_contrast(self, value: float) -> float:
        """Set webcam contrast multiplier and return clamped value."""
        return float(self._app.set_webcam_contrast(float(value)))

    def adjust_webcam_brightness(self, delta: float) -> float:
        """Adjust webcam brightness by delta and return new value."""
        return float(self._app.adjust_webcam_brightness(float(delta)))

    def adjust_webcam_contrast(self, delta: float) -> float:
        """Adjust webcam contrast by delta and return new value."""
        return float(self._app.adjust_webcam_contrast(float(delta)))

    def set_webcam_flip_horizontal(self, enabled: bool) -> bool:
        """Enable or disable horizontal mirror flip for webcam frames."""
        return bool(self._app.set_webcam_flip_horizontal(bool(enabled)))

    def set_webcam_flip_vertical(self, enabled: bool) -> bool:
        """Enable or disable vertical flip for webcam frames."""
        return bool(self._app.set_webcam_flip_vertical(bool(enabled)))

    def toggle_webcam_flip_horizontal(self) -> bool:
        """Toggle horizontal mirror flip for webcam frames."""
        return bool(self._app.toggle_webcam_flip_horizontal())

    def toggle_webcam_flip_vertical(self) -> bool:
        """Toggle vertical flip for webcam frames."""
        return bool(self._app.toggle_webcam_flip_vertical())

    def webcam_flip_state(self) -> dict[str, bool]:
        """Return webcam horizontal/vertical flip state."""
        return self._app.webcam_flip_state()

    def webcam_image_state(self) -> dict[str, float | bool]:
        """Return webcam image controls (brightness/contrast/flip) state."""
        return self._app.webcam_image_state()

    def trigger_burst(self) -> bool:
        """Trigger a screen-burst effect (alias for trigger_screen_burst)."""
        return self.trigger_screen_burst()

    def set_postfx_slot(self, slot: int) -> bool:
        if int(slot) == 0:
            return self.clear_postfx()
        msg = self._app.select_postfx_slot(int(slot))
        lower = msg.lower()
        if 'unavailable' in lower:
            return False
        if 'invalid slot' in lower:
            return False
        if 'use ctrl+alt+1..9' in lower:
            return False
        if 'coming soon' in lower:
            return False
        return True

    def postfx_slots(self) -> list[tuple[int, str, bool]]:
        """Return available post-FX slot definitions as (slot, label, enabled)."""
        pc = self._app._postfx_controller  # noqa: SLF001
        if pc is None:
            return []
        slot_map = getattr(pc, 'SLOT_MAP', ())
        out: list[tuple[int, str, bool]] = []
        for item in slot_map:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            slot = int(item[0])
            label = str(item[1])
            enabled = bool(item[2]) if len(item) > 2 else True
            out.append((slot, label, enabled))
        return out

    def hold_postfx_slot(self, slot: int, duration_s: float) -> bool:
        # Phase 1: trigger slot immediately; timed holds land in later phases.
        _ = duration_s
        return self.set_postfx_slot(slot)

    def clear_postfx(self) -> bool:
        if self._app._postfx_controller is None:  # noqa: SLF001
            return False
        clear_slot = getattr(self._app._postfx_controller, 'clear_active_slot', None)  # noqa: SLF001
        if not callable(clear_slot):
            return False
        clear_slot()
        return True

    def postfx_slot_duration(self, slot: int) -> float:
        """Return the configured display duration (seconds) for a post-FX slot.

        Returns 1.0 when the post-FX controller is unavailable or the slot is
        not found.
        """
        try:
            pc = self._app._postfx_controller  # noqa: SLF001
            if pc is not None:
                return float(pc._slot_hit_duration.get(int(slot), 1.0))  # noqa: SLF001
        except Exception:
            pass
        return 1.0

    def postfx_friend_pairs(self) -> list[tuple[int, int]]:
        """Return post-FX friend pairs for ping-pong use.

        Returns a list of ``(slot_a, slot_b)`` tuples where each pair represents
        a curated pairing.  Returns an empty list when no Post-FX controller is
        available.
        """
        try:
            pc = self._app._postfx_controller  # noqa: SLF001
            if pc is None:
                return []
            return pc.friend_pairs()
        except Exception:
            return []

    def postfx_friend_groups(self) -> list[tuple[int, ...]]:
        """Return post-FX friend groups (pairs and trios) for ping-pong use.

        Returns a list of tuples where each tuple is a curated group of 2 or 3
        slot indices.  Trios are derived from entries in ``POSTFX_FRIENDS`` that
        have two partners.  Returns an empty list when no Post-FX controller is
        available.
        """
        try:
            pc = self._app._postfx_controller  # noqa: SLF001
            if pc is None:
                return []
            return pc.friend_groups()
        except Exception:
            return []

    def is_user_busy(self) -> bool:
        return bool(time.monotonic() < self._app._user_action_deadline)  # noqa: SLF001

    def mark_user_action(self, kind: str = 'generic') -> None:
        self._app._mark_user_action(kind)  # noqa: SLF001

    def set_status_pill(self, text: str | None) -> None:
        self._app._vj_status_pill = '' if text is None else str(text)  # noqa: SLF001

    # ── Overlay helpers ────────────────────────────────────────────────────

    def flash_message(self, text: str, duration: float = 2.0) -> None:
        """Push a timed flash message to the HUD overlay."""
        try:
            self._app._overlays.flash_message(str(text), float(duration))  # noqa: SLF001
        except Exception:
            pass

    def overlay_modal_snapshot(self) -> dict[str, object]:
        """Return active overlay modal payload for alternate operator surfaces."""
        try:
            overlays = self._app._overlays  # noqa: SLF001
            snap = getattr(overlays, 'modal_snapshot', None)
            if callable(snap):
                payload = snap()
                if isinstance(payload, dict):
                    return payload
        except Exception:
            pass
        return {}

    def hue_scroll(self, dy: int) -> None:
        """Accumulate scroll-wheel hue shift by dy steps (+up / -down)."""
        try:
            pc = self._app._postfx_controller  # noqa: SLF001
            if pc is not None:
                pc.on_scroll(int(dy))
        except Exception:
            pass

    def rotate_scroll(self, dy: int) -> bool:
        """Accumulate Ctrl+scroll rotation by dy steps (+up / -down)."""
        pc = self._app._postfx_controller  # noqa: SLF001
        if pc is None:
            return False
        pc.on_ctrl_scroll(int(dy))
        return True

    def trigger_scroll_fx(self, dy: int, *, rotate: bool = False) -> bool:
        """Trigger postfx scroll behavior through the active controller.

        ``rotate=False`` routes to hue-shift (wheel).
        ``rotate=True`` routes to rotation (Ctrl+wheel).
        Returns True when a controller is present and the event was sent.
        """
        pc = self._app._postfx_controller  # noqa: SLF001
        if pc is None:
            return False
        if rotate:
            pc.on_ctrl_scroll(int(dy))
        else:
            pc.on_scroll(int(dy))
        return True

    def clear_hue_shift(self) -> None:
        """Immediately clear the scroll-wheel hue-shift pass."""
        try:
            pc = self._app._postfx_controller  # noqa: SLF001
            if pc is not None:
                pc.clear_hue_shift()
        except Exception:
            pass

    def rotate_scroll_degrees(self, degrees: float) -> bool:
        """Accumulate ctrl+scroll scene rotation by explicit degrees.

        Returns True when a postfx controller is present.
        """
        pc = self._app._postfx_controller  # noqa: SLF001
        if pc is None:
            return False
        if hasattr(pc, 'on_ctrl_scroll_degrees'):
            pc.on_ctrl_scroll_degrees(float(degrees))
        else:
            # Backward-compatible fallback for older postfx controllers.
            step = float(getattr(pc, '_rot_step_rad', 0.07) or 0.07)
            dy = int(round((float(degrees) * 0.017453292519943295) / max(1e-6, step)))
            if dy != 0:
                pc.on_ctrl_scroll(dy)
        return True

    def clear_scroll_fx(self) -> None:
        """Clear both scroll-driven post-fx states (hue + rotation)."""
        try:
            pc = self._app._postfx_controller  # noqa: SLF001
            if pc is not None:
                pc.clear_scroll_fx()
        except Exception:
            pass

    def set_hue_offset(self, value: float) -> bool:
        """Set scroll-driven hue offset directly in normalized [0, 1] space."""
        pc = self._app._postfx_controller  # noqa: SLF001
        if pc is None:
            return False
        try:
            pc._hue_offset = max(0.0, min(1.0, float(value)))  # noqa: SLF001
            pc._hue_idle_t = float(getattr(pc, '_hue_idle_timeout', 3.0) or 3.0)  # noqa: SLF001
            pc._hue_active = True  # noqa: SLF001
            return True
        except Exception:
            return False

    def set_rotation_degrees(self, degrees: float) -> bool:
        """Set scroll-driven scene rotation directly in degrees."""
        pc = self._app._postfx_controller  # noqa: SLF001
        if pc is None:
            return False
        try:
            pc._rot_angle = float(degrees) * 0.017453292519943295  # noqa: SLF001
            pc._rot_idle_t = float(getattr(pc, '_rot_idle_timeout', 3.0) or 3.0)  # noqa: SLF001
            pc._rot_active = True  # noqa: SLF001
            return True
        except Exception:
            return False

    def scroll_fx_state(self) -> dict[str, float | bool]:
        """Return scroll-driven post-fx state for operator surfaces."""
        pc = self._app._postfx_controller  # noqa: SLF001
        if pc is None:
            return {
                'available': False,
                'hue_active': False,
                'rotation_active': False,
                'hue_offset': 0.0,
                'rotation_degrees': 0.0,
            }

        hue_offset = 0.0
        rot_angle = 0.0
        try:
            hue_offset = float(getattr(pc, '_hue_offset', 0.0) or 0.0)
        except Exception:
            hue_offset = 0.0
        try:
            rot_angle = float(getattr(pc, '_rot_angle', 0.0) or 0.0)
        except Exception:
            rot_angle = 0.0

        return {
            'available': True,
            'hue_active': bool(getattr(pc, 'is_hue_active', False)),
            'rotation_active': bool(getattr(pc, 'is_rotation_active', False)),
            'hue_offset': hue_offset,
            'rotation_degrees': rot_angle * 57.29577951308232,
        }

    def effect_param_range(self, name: str) -> tuple[float | None, float | None]:
        """Return the active effect's config overrides for ``random_<name>_min/max``.

        Returns ``(None, None)`` when the current effect has no config or has
        not declared overrides for *name*.  Used by automation subsystems (e.g.
        Auto VJ) to honour per-effect tweakable bounds when drifting parameters.

        *name* should be one of ``"speed"``, ``"zoom"``, or ``"reactivity"``.
        """
        effect = self._app._current_effect  # noqa: SLF001
        cfg = getattr(effect, 'config', None) if effect is not None else None
        if not isinstance(cfg, dict):
            return (None, None)
        lo_raw = cfg.get(f'random_{name}_min')
        hi_raw = cfg.get(f'random_{name}_max')
        return (
            float(lo_raw) if lo_raw is not None else None,
            float(hi_raw) if hi_raw is not None else None,
        )

    # ── Drop-in key handler registry ──────────────────────────────────────

    def register_key_handler(
        self,
        name: str,
        handler: Callable[[int, int], 'str | None | bool'],
    ) -> None:
        """Register a drop-in key handler.

        *handler(sym, mod)* is called for every SDL KEYDOWN event before core
        key bindings.  It must return:

        - ``str``   — handled; the string is shown as a flash message
        - ``None``  — handled silently; no flash
        - ``False`` — not handled; pass through to the next handler / core
        """
        self._key_handlers[str(name)] = handler
        log.debug('Key handler registered: %s', name)

    def unregister_key_handler(self, name: str) -> None:
        """Remove a previously registered handler (e.g. on drop-in teardown)."""
        self._key_handlers.pop(str(name), None)

    @property
    def key_handlers(self) -> list[Callable[[int, int], 'str | None | bool']]:
        """Current list of registered handlers in insertion order."""
        return list(self._key_handlers.values())

    def key_handler_items(self) -> list[tuple[str, Callable[[int, int], 'str | None | bool']]]:
        """Registered (name, handler) pairs in insertion order."""
        return list(self._key_handlers.items())
