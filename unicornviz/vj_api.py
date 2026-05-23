"""Public VJ automation API for unicorn-viz.

This module defines the stable automation surface exposed as ``App.vj_api``.
Phase 1 implementation is intentionally conservative: wrappers are added without
changing runtime behavior unless explicitly called by a controller.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from unicornviz.effects.registry import get_effects

if TYPE_CHECKING:
    import moderngl

    from unicornviz.app import App


VJ_API_VERSION = (1, 0, 0)

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
        if app._audio_manager is not None:  # noqa: SLF001
            reactivity = float(app._audio_manager.get_reactivity())  # noqa: SLF001

        postfx_slot = 0
        postfx_active = False
        if app._postfx_controller is not None:  # noqa: SLF001
            postfx_active = bool(app._postfx_controller.is_active())  # noqa: SLF001
            postfx_slot = int(app._postfx_controller.active_slot)  # noqa: SLF001

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

    def goto_effect(self, name: str) -> bool:
        target = name.strip().lower()
        if not target:
            return False
        for cls in get_effects():
            if cls.NAME.lower() == target or cls.__name__.lower() == target:
                self._app.goto_effect(cls)
                return True
        return False

    def goto_random_effect(self, tags: list[str] | None = None, exclude_current: bool = True) -> str | None:
        effects = list(get_effects())
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
        return [(cls.NAME, list(getattr(cls, 'TAGS', []))) for cls in get_effects()]

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

    def toggle_control_room(self) -> tuple[bool, str]:
        """Toggle the operator control-room window."""
        return self._app.toggle_control_room()

    def set_display_mode(self, mode: str | None = None, reset_to_config: bool = False) -> str:
        """Set the main audience display mode."""
        return self._app.set_display_mode(mode, reset_to_config=reset_to_config)

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
        # Everywhere else we keep continuity-correct time.
        auto_vj = getattr(self._app, '_auto_vj', None)  # noqa: SLF001
        raver_scramble = bool(
            auto_vj is not None
            and bool(getattr(auto_vj, 'enabled', False))
            and str(getattr(auto_vj, '_profile', '')).lower() == 'raver'
        )
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

    def trigger_grand_finale(self) -> bool:
        if self._app._grand_finale is None:  # noqa: SLF001
            return False
        self._app.trigger_grand_finale()
        return True

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

    def hold_postfx_slot(self, slot: int, duration_s: float) -> bool:
        # Phase 1: trigger slot immediately; timed holds land in later phases.
        _ = duration_s
        return self.set_postfx_slot(slot)

    def clear_postfx(self) -> bool:
        if self._app._postfx_controller is None:  # noqa: SLF001
            return False
        self._app._postfx_controller.clear_active_slot()  # noqa: SLF001
        return True

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
