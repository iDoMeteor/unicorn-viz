"""
Main application — SDL2 window (Wayland-first) + moderngl context + main loop.
"""
from __future__ import annotations

import logging
import math
import os
import subprocess
import time
import ctypes
import sys
from pathlib import Path
from typing import Any, Callable, Type

import moderngl
import numpy as np

# Wayland-first on Linux, leave default driver selection elsewhere.
if sys.platform != 'win32' and "SDL_VIDEODRIVER" not in os.environ:
    os.environ["SDL_VIDEODRIVER"] = "wayland"

import sdl2
import sdl2.ext

from unicornviz.config import Config
from unicornviz.effects.base import AudioData, BaseEffect
from unicornviz.effects.registry import get_effects
from unicornviz.audio.manager import AudioManager
from unicornviz.playlist import Playlist
from unicornviz.overlays import Overlays
from unicornviz.hotkeys import HotkeyHandler
from unicornviz.midi import MidiManager
from unicornviz.recording import Recorder
from unicornviz._null_controllers import (
    _NullMultiHeadController,
    _NullPostFxController,
    _NullRTMPStreamer,
    _NullScreenBurstController,
    _NullWebcamSystem,
)
from unicornviz.dropins import (
    load_dropin_symbol,
    discover_dropin_help_entries,
    load_runtime_capability_class,
    register_runtime_capability,
    unregister_runtime_capability,
    BANNER_RUNTIME_CAPABILITY,
    CONTROL_ROOM_RUNTIME_CAPABILITY,
    MULTIHEAD_RUNTIME_CAPABILITY,
    POSTFX_RUNTIME_CAPABILITY,
)
from unicornviz.paths import resolve_path
from unicornviz.runtime_state import RuntimeStateStore
from unicornviz.presets import ShowPresetStore
from unicornviz.vj_api import VJApi

log = logging.getLogger(__name__)

TARGET_FPS = 60
FRAME_TIME = 1.0 / TARGET_FPS

# Effects browser live-preview thumbnail resolution (16:9).
_EB_THUMB_W = 480
_EB_THUMB_H = 270
_SPLASH_TOTAL_DURATION = 7.0  # 1s static + 6s animated
_SPLASH_REPLAY_COOLDOWN_S = 1.25
_TRANSITION_MODE_MAP = {
    'crossfade': 0,
    'smoothfade': 1,
    'scanwipe_x': 2,
    'scanwipe_y': 3,
    'dissolve': 4,
    'zoomblend': 5,
    'radialwipe': 6,
    'lumawipe': 7,
    'stripewipe': 8,
    'anglesweep': 9,
    'glitchsoft': 10,
    'prismsplit': 11,
}


def _smart_trim_label(text: str, limit: int = 56) -> str:
    """Trim long HUD labels without losing the start and end context."""
    if len(text) <= limit:
        return text
    head = max(20, int(limit * 0.58))
    tail = max(12, limit - head - 3)
    return f'{text[:head]}...{text[-tail:]}'


def _clamp_render_scale(value: float) -> float:
    """Clamp internal render scale to a sane range."""
    return max(0.5, min(1.0, value))


def _load_multihead_controller_class() -> type:
    """Load MultiHeadController directly from the multi-head drop-in."""
    try:
        return load_runtime_capability_class(MULTIHEAD_RUNTIME_CAPABILITY)
    except Exception as exc:
        log.warning('MultiHeadController unavailable (%s); falling back to single-display mode', exc)
        return _NullMultiHeadController


def _load_webcam_system_class() -> type:
    """Load WebcamSystem directly from the webcam-01 drop-in."""
    try:
        return load_dropin_symbol('webcam-01/webcam_overlay.py', 'WebcamSystem')
    except Exception as exc:
        log.warning('WebcamSystem not available: %s', exc)
        return _NullWebcamSystem


def _load_rtmp_streamer_class() -> type:
    """Load RTMPStreamer directly from the streaming-01 drop-in."""
    try:
        return load_dropin_symbol('streaming-01/rtmp_streamer.py', 'RTMPStreamer')
    except Exception as exc:
        log.warning('RTMP streamer unavailable: %s', exc)
        return _NullRTMPStreamer


def _load_postfx_controller_class() -> type:
    """Load PostFxController directly from the postfx-01 drop-in."""
    try:
        return load_runtime_capability_class(POSTFX_RUNTIME_CAPABILITY)
    except Exception as exc:
        log.warning('PostFxController not available: %s', exc)
        return _NullPostFxController


def _load_banner_controller_class() -> type:
    """Load BannerController directly from the banner-01 drop-in."""
    try:
        return load_runtime_capability_class(BANNER_RUNTIME_CAPABILITY)
    except Exception as exc:
        log.warning('BannerController not available: %s', exc)
        raise


def _load_screen_burst_controller_class() -> type:
    """Load ScreenBurstController from the unicorn-tears drop-in."""
    return load_dropin_symbol(
        'unicorn-tears-01/screen_burst_controller.py',
        'ScreenBurstController',
    )


def _load_dancing_unicorn_class() -> type:
    """Load DancingUnicornOverlay from the unicorn-tears drop-in."""
    return load_dropin_symbol(
        'unicorn-tears-01/dancing_unicorn_overlay.py',
        'DancingUnicornOverlay',
    )


def _load_rainbow_nova_class() -> type:
    """Load RainbowNova from the unicorn-tears drop-in."""
    return load_dropin_symbol(
        'unicorn-tears-01/rainbow_nova.py',
        'RainbowNova',
    )


def _load_unicorn_tears_controller_class() -> type:
    """Load UnicornTearsController from the unicorn-tears drop-in."""
    return load_dropin_symbol(
        'unicorn-tears-01/unicorn_tears.py',
        'UnicornTearsController',
    )


def _load_candy_frame_class() -> type:
    """Load CandyFrameController from the candy-frame drop-in."""
    return load_dropin_symbol(
        'candy-frame-01/candy_frame_controller.py',
        'CandyFrameController',
    )


def _load_auto_vj_controller_class() -> type:
    """Load AutoVJController from the auto-vj drop-in."""
    return load_dropin_symbol(
        'auto-vj-01/auto_vj.py',
        'AutoVJController',
    )


def _load_spotify_controller_class() -> type:
    """Load SpotifyController from the spotify drop-in."""
    return load_dropin_symbol(
        'spotify-01/spotify_controller.py',
        'SpotifyController',
    )


def _load_keystroke_logger_class() -> type:
    """Load KeystrokeLogger from the training-kit-01 drop-in."""
    return load_dropin_symbol(
        'training-kit-01/keystroke_logger.py',
        'KeystrokeLogger',
    )


def _load_media_controller_class() -> type:
    """Load MediaController from the media-01 drop-in."""
    return load_dropin_symbol(
        'media-01/media_controller.py',
        'MediaController',
    )


def _load_chat_controller_class() -> type:
    """Load ChatController from the chat-01 drop-in."""
    return load_dropin_symbol(
        'chat-01/chat_controller.py',
        'ChatController',
    )


def _load_audio_out_controller_class() -> type:
    """Load AudioOutController from the audio-out-01 drop-in."""
    return load_dropin_symbol(
        'audio-out-01/audio_out_controller.py',
        'AudioOutController',
    )


def _load_color_grade_controller_class() -> type:
    """Load ColorGradeController from the color-grade-01 drop-in."""
    return load_dropin_symbol(
        'color-grade-01/color_grade_controller.py',
        'ColorGradeController',
    )


def _load_beat_flash_controller_class() -> type:
    """Load BeatFlashController from the beat-flash-01 drop-in."""
    return load_dropin_symbol(
        'beat-flash-01/beat_flash_controller.py',
        'BeatFlashController',
    )


def _load_osc_bridge_controller_class() -> type:
    """Load OscBridgeController from the osc-bridge-01 drop-in."""
    return load_dropin_symbol(
        'osc-bridge-01/osc_bridge_controller.py',
        'OscBridgeController',
    )


def _load_lyrics_controller_class() -> type:
    """Load LyricsController from the lyrics-01 drop-in."""
    return load_dropin_symbol(
        'lyrics-01/lyrics_controller.py',
        'LyricsController',
    )


def _load_grand_finale_class() -> type:
    """Load GrandFinaleController from the grand-finale-01 drop-in."""
    return load_dropin_symbol(
        'grand-finale-01/grand_finale.py',
        'GrandFinaleController',
    )


def _load_control_room_controller_class() -> type:
    """Load ControlRoomController from the control-room drop-in."""
    return load_runtime_capability_class(CONTROL_ROOM_RUNTIME_CAPABILITY)


class App:
    def __init__(self, config_path: str | Config = "config.toml") -> None:
        self.cfg = config_path if isinstance(config_path, Config) else Config(config_path)
        self._running = False
        self._confirm_exit_enabled = bool(self.cfg.get('ui', 'confirm_exit', default=True))
        self._safe_mode = bool(self.cfg.get('dropins', 'safe_mode', default=False))
        self._paused = False
        self._projectm_manager_modal_active = False
        # Effects browser modal (keyboard + mouse, debounced thumbnail preview).
        self._effects_browser_active = False
        self._eb_last_nav_monotonic: float = 0.0
        # Live thumbnail preview: the selected effect is instantiated at a small
        # size and rendered to its own FBO — the active on-screen effect is never
        # touched. Committing (Enter/click) is what actually switches effects.
        self._eb_thumb_fbo: moderngl.Framebuffer | None = None
        self._eb_thumb_effect: BaseEffect | None = None
        self._eb_thumb_name: str = ''
        # Generic effect lock: when set to an effect's display NAME, the system
        # stays on that effect (ProjectM-only mode). Switch attempts to other
        # effects are redirected into a variation of the locked effect (e.g. a
        # ProjectM preset advance) so automation keeps the show moving.
        self._effect_lock: str | None = None
        self._auto_advance = bool(self.cfg.get('demo', 'auto_advance', default=True))  # Toggle with hotkey T
        self._ctrl_held = False
        self._ctx: moderngl.Context | None = None
        self._window = None
        self._gl_context = None
        self._current_effect: BaseEffect | None = None
        self._next_effect: BaseEffect | None = None
        self._transition_t: float = 0.0
        self._transition_kind: str = "crossfade"
        self._transition_dir: tuple[float, float] = (1.0, 0.0)
        self._transition_phase: float = 0.0
        self._previous_effect_name: str = '-'
        self._webcam_auto_cycle: bool = False
        self._webcam_cycle_timer: float = 0.0
        self._webcam_cycle_interval: float = 0.0
        self._webcam_system = None
        self._postfx_controller = None
        self._color_grade = None
        self._beat_flash = None
        self._dancing_unicorn = None
        self._rainbow_nova = None
        self._unicorn_tears: Any = None
        self._candy_frame = None
        self._auto_vj = None
        self._spotify = None
        self._media: Any = None
        self._chat: Any = None
        self._audio_out = None
        self._osc_bridge = None
        self._lyrics = None
        self._grand_finale = None
        self._control_room = None
        self._control_room_creating: bool = False
        self._control_room_startup_cfg: dict[str, Any] | None = None
        self._control_room_startup_frames_remaining: int = 0
        self._streamer = None
        self._playlist: Playlist | None = None
        self._subsystems: dict[str, Any] = {}
        self._claimed_window_handlers: dict[int, Callable[[Any], None]] = {}
        self._hotkeys: HotkeyHandler | None = None
        self._frame_capture_bytes: bytes | None = None
        self._frame_capture_width: int = 0
        self._frame_capture_height: int = 0
        self._frame_capture_components: int = 0
        # Timestamp of the last GPU readback done for subsystem preview consumers
        # (e.g. the control-room live preview).  Used to throttle the expensive
        # glReadPixels call so it fires at subsystem render rate, not at the full
        # audience output frame rate.
        self._last_subsystem_frame_capture_time: float = 0.0
        self._rng = np.random.default_rng()
        self._speed_randomized: bool = False
        self._reactivity_randomized: bool = False
        self._zoom_randomized: bool = False
        self._demo_timer: float = 0.0
        self._effect_duration: float = float(
            self.cfg.get('demo', 'effect_duration', default=20)
        )
        # Session/show timer surface for Auto VJ planning and VJ API.
        self._session_started_at: float = 0.0
        self._show_duration_s: float | None = None
        self._transition_duration: float = self.cfg.get(
            "demo", "transition_duration", default=1.0
        )
        self._audio: AudioData | None = None
        self._audio_raw: AudioData | None = None
        self._last_frame_fps: float = 0.0
        self._last_frame_ms: float = 0.0
        self._audio_manager: AudioManager | None = None
        self._midi_manager: MidiManager | None = None
        self._overlays: Overlays | None = None
        self._recorder: Recorder | None = None
        self._audio_scratch_current = AudioData()
        self._audio_scratch_next = AudioData()
        self._splash_config: dict | None = None
        self._last_splash_replay_t: float = -1e9
        self._fbo_a: moderngl.Framebuffer | None = None
        self._fbo_b: moderngl.Framebuffer | None = None
        self._blend_prog: moderngl.Program | None = None
        self._blend_vao: moderngl.VertexArray | None = None
        self._invert_prog: moderngl.Program | None = None
        self._invert_vao: moderngl.VertexArray | None = None
        self._invert_vbo: moderngl.Buffer | None = None
        self._present_prog: moderngl.Program | None = None
        self._present_vao: moderngl.VertexArray | None = None
        self._present_vbo: moderngl.Buffer | None = None
        self._burst_prog: moderngl.Program | None = None
        self._burst_vao: moderngl.VertexArray | None = None
        self._burst_vbo: moderngl.Buffer | None = None
        self._burst_controller = _NullScreenBurstController()
        self._invert_colors = False
        # Double-buffered PBOs for async streaming/recording frame readback.
        # Frame N: issue read_into(pbo_write); Frame N+1: read pbo_read (DMA done).
        self._stream_pbos: list[moderngl.Buffer] = []
        self._stream_pbo_size: int = 0
        self._stream_pbo_index: int = 0
        self._stream_pbo_primed: bool = False
        # If a driver/context cannot map PBOs reliably, permanently fall back
        # to direct read for the current session to avoid repeated map failures.
        self._stream_pbo_disabled: bool = False
        self._width = self.cfg.get("window", "width", default=1920)
        self._height = self.cfg.get("window", "height", default=1080)
        # In mirror_all the SDL window spans all displays, while effects/HUD
        # keep rendering at single-display logical size. _window_width/_height
        # describe the actual SDL window framebuffer; _width/_height describe
        # the logical canvas that effects render into.
        self._window_width = self._width
        self._window_height = self._height
        self._window_origin_x = 0
        self._window_origin_y = 0
        self._mirror_rects: list[tuple[int, int, int, int]] = []
        self._primary_overlay_view_debug_last: tuple[int, int, int, int] | None = None
        self._display_index = 0
        self._display_mode = 'single'
        multihead_cls = _NullMultiHeadController if self._safe_mode else _load_multihead_controller_class()
        self._multihead = multihead_cls(self.cfg)
        self._fullscreen_mode = str(self.cfg.get('window', 'fullscreen_mode', default='auto')).lower()
        self._render_scale = _clamp_render_scale(
            float(self.cfg.get('render', 'internal_scale', default=1.0))
        )
        self._playlist_mode: str = 'unknown'
        self._playlist_index: int = -1
        self._playlist_size: int = 0
        self._user_action_deadline: float = 0.0
        self._vj_status_pill: str = ''
        self._last_auto_vj_error_key: str = ''
        self._last_auto_vj_error_t: float = -1e9
        runtime_state_path = self.cfg.get(
            'runtime_state',
            'path',
            default='runtime/global_state.json',
        )
        self._runtime_state = RuntimeStateStore(str(runtime_state_path))
        # Effects the operator has disabled from auto-rotation (persisted).
        self._disabled_effects: set[str] = {
            str(n) for n in (self._runtime_state.get('effects.disabled', []) or [])
        }
        preset_path = self.cfg.get('presets', 'path', default='runtime/presets.json')
        self._preset_store = ShowPresetStore(str(preset_path))
        self.vj_api = VJApi(self)
        self._render_scale_default: float = self._render_scale
        self._render_width = max(1, int(round(self._width * self._render_scale)))
        self._render_height = max(1, int(round(self._height * self._render_scale)))
        self._fullscreen = self.cfg.get("window", "fullscreen", default=False)
        self._show_cursor_default = bool(self.cfg.get('window', 'show_cursor', default=False))
        self._audio = AudioData()
        self._audio_raw = AudioData()

    # ------------------------------------------------------------------ #
    # SDL2 + moderngl init                                                 #
    # ------------------------------------------------------------------ #

    def _log_video_displays(self) -> int:
        return self._multihead.log_video_displays(self._width, self._height)

    def _resolve_display_mode(self) -> str:
        self._display_mode = self._multihead.resolve_display_mode()
        return self._display_mode

    @staticmethod
    def _is_span_mode(mode: str) -> bool:
        return mode in {'span_included', 'span_all'}

    @staticmethod
    def _is_mirror_mode(mode: str) -> bool:
        return mode in {'mirror_included', 'mirror_all'}

    def _set_multihead_mode(self, mode: str) -> None:
        """Update drop-in internal mode fields when available."""
        if hasattr(self._multihead, '_display_mode_requested'):
            setattr(self._multihead, '_display_mode_requested', mode)
        if hasattr(self._multihead, '_display_mode'):
            setattr(self._multihead, '_display_mode', mode)

    def supported_display_modes(self) -> tuple[str, ...]:
        """Return runtime-supported display modes in UI-friendly order."""
        getter = getattr(self._multihead, 'supported_display_modes', None)
        if callable(getter):
            try:
                raw = getter()
            except Exception:
                raw = ()
            out = tuple(str(item).strip().lower() for item in raw if str(item).strip())
            if out:
                return out
        return ('single',)

    def register_subsystem(self, name: str, subsystem: Any) -> bool:
        """Register a runtime subsystem for per-frame update/present callbacks."""
        subsystem_name = str(name).strip()
        if not subsystem_name or subsystem is None:
            return False
        self._subsystems[subsystem_name] = subsystem
        return True

    def unregister_subsystem(self, name: str) -> None:
        """Unregister a runtime subsystem from the app loop."""
        self._subsystems.pop(str(name).strip(), None)

    def has_subsystem(self, name: str) -> bool:
        """Return True when a named runtime subsystem is registered."""
        key = str(name).strip()
        return bool(key) and key in self._subsystems

    def get_subsystem(self, name: str) -> Any | None:
        """Return a named runtime subsystem instance, or None if not registered."""
        key = str(name).strip()
        return self._subsystems.get(key) if key else None

    def list_subsystems(self) -> list[str]:
        """Return the names of all currently registered subsystems."""
        return list(self._subsystems)

    def get_runtime_state(self, dotted_path: str = '', default: Any = None) -> Any:
        """Read a value from shared runtime state using dotted-path keys."""
        return self._runtime_state.get(dotted_path, default)

    def set_runtime_state(self, dotted_path: str, value: Any) -> None:
        """Set a value in shared runtime state using dotted-path keys."""
        self._runtime_state.set(dotted_path, value)

    def _persist_webcam_runtime_state(self) -> None:
        """Persist webcam subsystem state into the shared runtime store."""
        if self._webcam_system is None:
            return
        exporter = getattr(self._webcam_system, 'get_persistence_state', None)
        if not callable(exporter):
            return
        try:
            payload = exporter()
        except Exception as exc:
            log.warning('Webcam runtime-state export failed: %s', exc)
            return
        if isinstance(payload, dict):
            self.set_runtime_state('webcam', payload)

    def claim_window_events(self, window_id: int, handler: Callable[[Any], None]) -> bool:
        """Route SDL events for a claimed window to a subsystem handler."""
        if int(window_id) <= 0 or handler is None:
            return False
        self._claimed_window_handlers[int(window_id)] = handler
        return True

    def release_window_events(self, window_id: int) -> None:
        """Release event ownership for a previously-claimed SDL window."""
        self._claimed_window_handlers.pop(int(window_id), None)

    def rebind_main_gl_context(self) -> bool:
        """Re-bind the main audience window's GL context as current.

        Called after subsystem-owned windows are created/destroyed so any GL
        binding implicitly migrated by SDL/X11 is restored.  Returns True on
        success or when there is nothing to rebind.
        """
        if self._window is None or self._gl_context is None:
            return True
        if sdl2.SDL_GL_MakeCurrent(self._window, self._gl_context) != 0:
            log.warning('SDL_GL_MakeCurrent failed: %s', sdl2.SDL_GetError().decode())
            return False
        return True

    def _event_window_id(self, event: Any) -> int | None:
        """Return the SDL window id associated with an event, when present."""
        if event.type in (sdl2.SDL_KEYDOWN, sdl2.SDL_KEYUP):
            return int(event.key.windowID)
        if event.type == sdl2.SDL_TEXTINPUT:
            return int(event.text.windowID)
        if event.type in (sdl2.SDL_MOUSEMOTION,):
            return int(event.motion.windowID)
        if event.type in (sdl2.SDL_MOUSEBUTTONDOWN, sdl2.SDL_MOUSEBUTTONUP):
            return int(event.button.windowID)
        if event.type == sdl2.SDL_MOUSEWHEEL:
            return int(event.wheel.windowID)
        if event.type == sdl2.SDL_WINDOWEVENT:
            return int(event.window.windowID)
        return None

    def _dispatch_claimed_window_event(self, event: Any) -> bool:
        """Dispatch events for subsystem-owned windows before main handling."""
        window_id = self._event_window_id(event)
        if window_id is None:
            return False
        handler = self._claimed_window_handlers.get(window_id)
        if handler is None:
            return False
        try:
            handler(event)
        except Exception as exc:
            log.warning('Claimed window event handler failed for window %d: %s', window_id, exc)
        return True

    def dispatch_subwindow_keydown(self, sym: int, mod: int, repeat: bool = False) -> None:
        """Forward a keydown from a claimed subsystem window to global hotkeys."""
        self._update_ctrl_state(int(sym), True)
        handler = self._hotkeys
        if handler is None or bool(repeat):
            return
        handler.handle(int(sym), int(mod))

    def dispatch_subwindow_keyup(self, sym: int) -> None:
        """Forward keyup modifier state from claimed subsystem windows."""
        self._update_ctrl_state(int(sym), False)

    def _subsystems_need_frame_capture(self) -> bool:
        """Return True when any registered subsystem wants preview-frame bytes."""
        return any(bool(getattr(subsystem, 'needs_frame_bytes', False)) for subsystem in self._subsystems.values())

    def _render_subsystem_overlays(self, dt: float, width: int, height: int) -> None:
        """Render optional subsystem overlay layers before HUD composition."""
        for name, subsystem in list(self._subsystems.items()):
            renderer = getattr(subsystem, 'render_overlay', None)
            if not callable(renderer):
                continue
            try:
                renderer(int(width), int(height), float(dt), self._audio)
            except TypeError:
                try:
                    renderer(int(width), int(height), float(dt))
                except Exception as exc:
                    log.warning('%s subsystem overlay render failed: %s', name, exc)
            except Exception as exc:
                log.warning('%s subsystem overlay render failed: %s', name, exc)

    def _update_frame_capture_snapshot(self, frame: bytes | None) -> None:
        """Cache the latest audience-output frame for subsystem preview use."""
        if frame is None:
            self._frame_capture_bytes = None
            self._frame_capture_width = 0
            self._frame_capture_height = 0
            self._frame_capture_components = 0
            return
        self._frame_capture_bytes = bytes(frame)
        self._frame_capture_width = int(self._width)
        self._frame_capture_height = int(self._height)
        self._frame_capture_components = 3

    def get_frame_capture(self) -> tuple[bytes | None, int, int, int]:
        """Return the last cached audience-output frame snapshot."""
        return (
            self._frame_capture_bytes,
            self._frame_capture_width,
            self._frame_capture_height,
            self._frame_capture_components,
        )

    def _create_control_room(self, cfg_override: dict[str, Any] | None = None) -> tuple[bool, str]:
        """Create and register the optional control-room subsystem."""
        if self._safe_mode:
            return False, 'Control Room unavailable in safe mode'
        if self._control_room_creating:
            return False, 'Control Room creation already in progress'
        if self._control_room is not None and bool(getattr(self._control_room, 'is_open', False)):
            return True, 'Control Room already open'
        # Garbage-collect any orphaned controller (pending-shutdown OR zombie window
        # already closed) so we never leak an old SDL window on rapid toggles.
        if self._control_room is not None:
            try:
                close_fn = getattr(self._control_room, 'close_now', None)
                if callable(close_fn):
                    close_fn()
            except Exception as exc:
                log.warning('Stale ControlRoomController cleanup failed: %s', exc)
            self._control_room = None
        control_room_cfg = cfg_override or self.cfg.get('control_room', default={}) or {}
        if not isinstance(control_room_cfg, dict):
            control_room_cfg = {}
        self._control_room_creating = True
        try:
            control_room_cls = _load_control_room_controller_class()
            self._control_room = control_room_cls(self, control_room_cfg)
            register_runtime_capability(
                self.vj_api,
                self._control_room,
                CONTROL_ROOM_RUNTIME_CAPABILITY,
            )
            self.rebind_main_gl_context()
            log.info('ControlRoomController loaded from drop-in')
            return True, f'Control Room open on display {getattr(self._control_room, "_display_index", "?")}'
        except Exception as exc:
            self._control_room = None
            log.warning('ControlRoomController not available: %s', exc)
            return False, f'Control Room unavailable: {exc}'
        finally:
            self._control_room_creating = False

    def _destroy_control_room(self) -> tuple[bool, str]:
        """Shutdown and unregister the optional control-room subsystem."""
        if self._control_room is None:
            return False, 'Control Room already off'
        closer = getattr(self._control_room, 'close_now', None)
        try:
            if callable(closer):
                closer()
            else:
                self._control_room.shutdown()
        except Exception as exc:
            log.warning('ControlRoomController shutdown failed: %s', exc)
        # close_now() / _destroy_window() already unregisters and rebinds GL.
        # The explicit calls below are defensive against older drop-ins that
        # don't implement close_now().
        unregister_runtime_capability(self.vj_api, CONTROL_ROOM_RUNTIME_CAPABILITY)
        self._control_room = None
        self.rebind_main_gl_context()
        log.info('ControlRoomController closed')
        return False, 'Control Room closed'

    def toggle_control_room(self) -> tuple[bool, str]:
        """Toggle the operator control-room window on or off."""
        if self._control_room is not None and bool(getattr(self._control_room, 'is_open', False)):
            return self._destroy_control_room()
        return self._create_control_room()

    def control_room_flash_gate_active(self) -> bool:
        """Return True when flash notifications should route to control room."""
        control_room_cfg = self.cfg.get('control_room', default={}) or {}
        if not isinstance(control_room_cfg, dict):
            control_room_cfg = {}
        if not bool(control_room_cfg.get('enabled', False)):
            return False
        return (
            self._control_room is not None
            and bool(getattr(self._control_room, 'is_open', False))
        )

    def route_flash_message(self, text: str, duration: float = 2.0) -> bool:
        """Route flash notifications to control room when gate conditions are met."""
        if not self.control_room_flash_gate_active():
            return False
        handler = getattr(self._control_room, 'push_notice', None)
        if not callable(handler):
            return False
        try:
            handler(str(text), float(duration))
            return True
        except Exception as exc:
            log.warning('Control room flash routing failed: %s', exc)
            return False

    def _multihead_layouts(self) -> list[tuple[int, int, int, int]]:
        """Return display layouts from the multi-head drop-in.

        Falls back to the controller's private `_display_layouts` attribute
        when an older drop-in submodule is loaded that lacks the public
        `display_layouts` property.
        """
        layouts = getattr(self._multihead, 'display_layouts', None)
        if layouts is None:
            layouts = getattr(self._multihead, '_display_layouts', None)
        return list(layouts) if layouts else []

    def _primary_active_layout(self) -> tuple[int, int, int, int] | None:
        """Return the active layout treated as primary for audience rendering.

        Primary follows the configured window.display_index (resolved by the
        multi-head controller) and falls back to the first active layout when
        unavailable.
        """
        layouts = self._multihead_layouts()
        if not layouts:
            return None

        primary_index = int(getattr(self._multihead, 'display_index', self._display_index))
        active_indices = getattr(self._multihead, '_active_display_indices', None)

        # Prefer SDL display bounds for the resolved display_index so layout
        # lookup stays stable regardless of active-layout ordering.
        if isinstance(active_indices, list) and active_indices and primary_index not in active_indices:
            primary_index = int(active_indices[0])
        bounds = self._display_bounds(primary_index)
        if bounds is not None:
            return (int(bounds.x), int(bounds.y), int(bounds.w), int(bounds.h))

        active_indices = getattr(self._multihead, '_active_display_indices', None)
        if isinstance(active_indices, list) and len(active_indices) == len(layouts):
            for idx, rect in zip(active_indices, layouts, strict=False):
                if int(idx) == primary_index:
                    return rect

        # Backward/compat fallback for controllers that expose only an ordered
        # active-layout list where display index maps directly by position.
        if 0 <= primary_index < len(layouts):
            return layouts[primary_index]

        return layouts[0]

    def _multihead_mirror_layout(self, origin_x: int, origin_y: int) -> list[tuple[int, int, int, int]]:
        """Return per-display rects in window-local coords, with fallback."""
        fn = getattr(self._multihead, 'mirror_layout', None)
        if callable(fn):
            return list(fn(origin_x, origin_y))
        # Fallback: derive from layouts directly.
        return [(x - origin_x, y - origin_y, w, h) for (x, y, w, h) in self._multihead_layouts()]

    def _set_multihead_index(self, index: int) -> None:
        """Update drop-in internal display index fields when available."""
        if hasattr(self._multihead, '_display_index_requested'):
            setattr(self._multihead, '_display_index_requested', int(index))
        if hasattr(self._multihead, '_display_index'):
            setattr(self._multihead, '_display_index', int(index))

    def _resolve_display_index(self) -> int:
        self._display_index = self._multihead.resolve_display_index(self._width, self._height)
        return self._display_index

    def _display_bounds(self, display_index: int) -> sdl2.SDL_Rect | None:
        return self._multihead.display_bounds(display_index, self._width, self._height)

    def _all_display_bounds(self) -> tuple[int, int, int, int]:
        return self._multihead.all_display_bounds(self._width, self._height)

    def _window_position_for_display(self, display_index: int) -> tuple[int, int]:
        return self._multihead.window_position_for_display(display_index, self._width, self._height)

    def _sync_window_origin_from_sdl(self) -> None:
        """Sync cached window origin to compositor-reported SDL coordinates."""
        if self._window is None:
            return
        wx = ctypes.c_int(0)
        wy = ctypes.c_int(0)
        sdl2.SDL_GetWindowPosition(self._window, wx, wy)
        self._window_origin_x = int(wx.value)
        self._window_origin_y = int(wy.value)

    def _primary_display_viewport(self) -> tuple[int, int, int, int] | None:
        """Return window-local viewport for the primary display in multi-display modes.

        Primary is resolved from configured display index via active layouts.
        """
        if self._display_mode not in {'mirror_included', 'mirror_all', 'span_included', 'span_all'}:
            return None
        if self._window is None:
            return None
        primary_layout = self._primary_active_layout()
        if primary_layout is not None:
            px, py, pw, ph = primary_layout
        else:
            bounds = self._display_bounds(self._display_index)
            if bounds is None:
                return None
            px, py, pw, ph = int(bounds.x), int(bounds.y), int(bounds.w), int(bounds.h)

        # Map display bounds into the same layout-space origin used to build
        # span/mirror window geometry. This avoids compositor-dependent drift
        # from SDL_GetWindowPosition that can split a modal across displays.
        bounds_x, bounds_y, _bounds_w, _bounds_h = self._all_display_bounds()
        origin_x = int(bounds_x)
        origin_y = int(bounds_y)

        # Safety fallback for transient topology changes where all-bounds may
        # be unavailable/misaligned for a frame.
        if self._window is not None and (origin_x == 0 and origin_y == 0):
            wx = ctypes.c_int(0)
            wy = ctypes.c_int(0)
            sdl2.SDL_GetWindowPosition(self._window, wx, wy)
            origin_x = int(wx.value)
            origin_y = int(wy.value)

        vx = px - origin_x
        vy_top = py - origin_y

        # Guard against transient/invalid topology states while displays are
        # connecting/disconnecting. Returning None falls back to full-canvas
        # overlay rendering for that frame.
        if pw <= 0 or ph <= 0:
            return None

        canvas_w = max(1, self._window_width if self._is_mirror_mode(self._display_mode) else self._width)
        canvas_h = max(1, self._window_height if self._is_mirror_mode(self._display_mode) else self._height)

        # Convert from top-left display layout coordinates to OpenGL viewport
        # coordinates (bottom-left origin).
        vy = canvas_h - (vy_top + ph)

        x0 = max(0, vx)
        y0 = max(0, vy)
        x1 = min(canvas_w, vx + pw)
        y1 = min(canvas_h, vy + ph)
        if x1 <= x0 or y1 <= y0:
            return None
        view = (x0, y0, x1 - x0, y1 - y0)
        if view != self._primary_overlay_view_debug_last:
            log.info(
                'Primary overlay viewport: mode=%s primary_index=%d display_rect=(%d,%d,%d,%d) origin=(%d,%d) canvas=%dx%d gl_view=%s',
                self._display_mode,
                int(getattr(self._multihead, 'display_index', self._display_index)),
                px,
                py,
                pw,
                ph,
                origin_x,
                origin_y,
                canvas_w,
                canvas_h,
                view,
            )
            self._primary_overlay_view_debug_last = view
        return view

    def _overlay_mouse_coords(
        self,
        x: float,
        y: float,
        primary_overlay_view: tuple[int, int, int, int] | None,
    ) -> tuple[float, float] | None:
        """Return overlay-local mouse coordinates for hit-testing.

        SDL mouse events are top-left-origin window coords. Overlay rendering in
        multi-display modes may target a GL viewport (`primary_overlay_view`)
        defined in bottom-left-origin coordinates, so convert before dispatch.
        """
        if primary_overlay_view is None:
            return float(x), float(y)

        vx, vy, vw, vh = primary_overlay_view
        canvas_h = (
            max(1, int(self._window_height))
            if self._is_mirror_mode(self._display_mode)
            else max(1, int(self._height))
        )
        view_top = canvas_h - (int(vy) + int(vh))
        view_left = int(vx)

        local_x = float(x) - float(view_left)
        local_y = float(y) - float(view_top)

        if local_x < 0.0 or local_y < 0.0 or local_x > float(vw) or local_y > float(vh):
            return None
        return local_x, local_y

    def _splash_render_target(self) -> tuple[int, int, tuple[int, int, int, int] | None]:
        """Return splash texture size and optional destination viewport.

        In span/mirror modes, splash renders into the primary display region so
        startup visuals and replay match the audience display anchor.
        """
        view = self._primary_display_viewport()
        if view is None:
            return self._width, self._height, None
        _, _, vw, vh = view
        return max(1, int(vw)), max(1, int(vh)), view

    def _move_window_to_display(self) -> None:
        self._multihead.move_window_to_display(self._window, self._width, self._height)

    def _prefer_borderless_fullscreen(self) -> bool:
        """Return True when fullscreen should use borderless windowing.

        MATE/Marco on X11 tends to ignore SDL fullscreen placement hints, so
        borderless fullscreen is the reliable fallback there.
        """
        if self._fullscreen_mode == 'borderless':
            return True
        if self._fullscreen_mode == 'desktop':
            return False
        session_bits = ' '.join(
            filter(None, [
                os.environ.get('XDG_CURRENT_DESKTOP', ''),
                os.environ.get('XDG_SESSION_DESKTOP', ''),
                os.environ.get('DESKTOP_SESSION', ''),
            ])
        ).upper()
        return 'MATE' in session_bits

    def _fullscreen_window_geometry(self) -> tuple[int, int, int, int]:
        """Compute the target geometry for fullscreen window creation."""
        if self._is_span_mode(self._display_mode):
            return self._all_display_bounds()
        bounds = self._display_bounds(self._display_index)
        if bounds is None:
            return 0, 0, self._width, self._height
        return bounds.x, bounds.y, bounds.w, bounds.h

    def _destroy_mirror_outputs(self) -> None:
        self._multihead.destroy_mirror_outputs()

    def _create_mirror_outputs(self) -> None:
        """No-op: legacy SDL_Renderer mirror windows replaced by GL-native tile-blit.

        See drop-ins/multi-head-01/MATE-X11-MULTIHEAD-NOTES.md for rationale and
        the legacy approach (kept in MultiHeadController for fallback testing).
        """
        return

    def _resize_mirror_textures(self) -> None:
        self._multihead.resize_mirror_textures(self._width, self._height)

    def _present_mirror_outputs(self, frame_bytes: bytes) -> None:
        self._multihead.present_mirror_outputs(frame_bytes, self._width, self._height)

    def _is_mirror_window_id(self, window_id: int) -> bool:
        return self._multihead.is_mirror_window_id(window_id)

    def _rebuild_multihead_outputs(self) -> None:
        title = self.cfg.get('window', 'title', default='Unicorn Viz')
        self._display_index = self._multihead.rebuild_multihead_outputs(
            self._width,
            self._height,
            title,
        )
        if self._window is None:
            return

        # Keep the main SDL window aligned to refreshed topology bounds.
        if self._display_mode in {'span_included', 'span_all', 'mirror_included', 'mirror_all'}:
            x, y, w, h = self._all_display_bounds()
            sdl2.SDL_SetWindowPosition(self._window, x, y)
            sdl2.SDL_SetWindowSize(self._window, w, h)
            self._window_origin_x = int(x)
            self._window_origin_y = int(y)

        wx = ctypes.c_int(0)
        wy = ctypes.c_int(0)
        sdl2.SDL_GetWindowPosition(self._window, wx, wy)
        self._window_origin_x = int(wx.value)
        self._window_origin_y = int(wy.value)

        ww = ctypes.c_int(0)
        wh = ctypes.c_int(0)
        sdl2.SDL_GetWindowSize(self._window, ww, wh)
        if ww.value > 0:
            self._window_width = int(ww.value)
        if wh.value > 0:
            self._window_height = int(wh.value)

        if self._is_span_mode(self._display_mode):
            if self._window_width != self._width or self._window_height != self._height:
                self._on_resize(self._window_width, self._window_height)
            return

        if self._is_mirror_mode(self._display_mode):
            primary_layout = self._primary_active_layout()
            logical_changed = False
            if primary_layout is not None:
                new_w = int(primary_layout[2])
                new_h = int(primary_layout[3])
                logical_changed = (new_w != self._width) or (new_h != self._height)
                self._width = new_w
                self._height = new_h
            self._mirror_rects = self._multihead_mirror_layout(
                self._window_origin_x,
                self._window_origin_y,
            )
            if logical_changed:
                self._update_render_target_size()
                self._release_readback_pbos()
                self._handle_recording_resize_interruption('display topology change')
                if self._streamer is not None:
                    self._streamer.resize(self._width, self._height)
                if self._current_effect:
                    self._current_effect.resize(self._width, self._height)
                if self._next_effect:
                    self._next_effect.resize(self._width, self._height)
                if self._webcam_system is not None:
                    self._webcam_system.resize(self._width, self._height)
                if self._candy_frame is not None:
                    self._candy_frame.resize(self._width, self._height)
                if self._postfx_controller is not None:
                    self._postfx_controller.resize(self._render_width, self._render_height)
                if self._grand_finale is not None:
                    self._grand_finale.resize(self._width, self._height)
                self._rebuild_fbos()
            log.info('Mirror topology rebuilt: origin=(%d,%d) window=%dx%d rects=%s',
                     self._window_origin_x,
                     self._window_origin_y,
                     self._window_width,
                     self._window_height,
                     self._mirror_rects)

    def _release_readback_pbos(self) -> None:
        self._multihead.release_readback_pbos()
        for pbo in self._stream_pbos:
            pbo.release()
        self._stream_pbos = []
        self._stream_pbo_size = 0
        self._stream_pbo_primed = False
        self._stream_pbo_index = 0
        self._stream_pbo_disabled = False

    def _ensure_readback_pbos(self, size: int) -> None:
        if self._ctx is None:
            return
        self._multihead.ensure_readback_pbos(self._ctx, size)

    def _read_shared_frame(self) -> bytes | None:
        if self._ctx is None:
            return None
        return self._multihead.read_shared_frame(self._ctx, self._width, self._height)

    def _init_sdl(self) -> None:
        if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO | sdl2.SDL_INIT_EVENTS) != 0:
            # Wayland may have failed — retry with x11
            os.environ["SDL_VIDEODRIVER"] = "x11"
            if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO | sdl2.SDL_INIT_EVENTS) != 0:
                raise RuntimeError(
                    f"SDL_Init failed: {sdl2.SDL_GetError().decode()}"
                )
            log.info("Wayland init failed — using x11")
        else:
            log.info(
                "SDL video driver: %s",
                sdl2.SDL_GetCurrentVideoDriver().decode(),
            )

        # Multi-head modes rely on explicit window placement; Wayland may ignore
        # this by design, so try X11 automatically if available.
        if self._multihead.requested_mode != 'single':
            current_driver = sdl2.SDL_GetCurrentVideoDriver().decode().lower()
            if current_driver == 'wayland':
                log.warning('display_mode=%s requested on Wayland; attempting X11 fallback for reliable multi-head placement', self._multihead.requested_mode)
                sdl2.SDL_Quit()
                os.environ['SDL_VIDEODRIVER'] = 'x11'
                if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO | sdl2.SDL_INIT_EVENTS) != 0:
                    log.warning('X11 fallback failed; continuing on Wayland (multi-head placement may be limited)')
                    os.environ['SDL_VIDEODRIVER'] = 'wayland'
                    if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO | sdl2.SDL_INIT_EVENTS) != 0:
                        raise RuntimeError(
                            f"SDL_Init failed after fallback attempts: {sdl2.SDL_GetError().decode()}"
                        )
                else:
                    log.info('Using x11 for display_mode=%s', self._multihead.requested_mode)

        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MAJOR_VERSION, 3)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MINOR_VERSION, 3)
        sdl2.SDL_GL_SetAttribute(
            sdl2.SDL_GL_CONTEXT_PROFILE_MASK, sdl2.SDL_GL_CONTEXT_PROFILE_CORE
        )
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_DOUBLEBUFFER, 1)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_DEPTH_SIZE, 24)

        flags = sdl2.SDL_WINDOW_OPENGL | sdl2.SDL_WINDOW_RESIZABLE
        self._display_mode = self._resolve_display_mode()
        if self._display_mode in ('span_included', 'span_all', 'mirror_included', 'mirror_all') and self._fullscreen:
            flags = sdl2.SDL_WINDOW_OPENGL | sdl2.SDL_WINDOW_BORDERLESS
        elif self._fullscreen:
            if self._prefer_borderless_fullscreen():
                flags |= sdl2.SDL_WINDOW_BORDERLESS
            else:
                flags |= sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP

        self._display_index = self._resolve_display_index()
        # In mirror_all the SDL window spans all displays so we can blit the
        # rendered frame to each display's region as a viewport. Effects keep
        # rendering at single-display logical size to preserve composition.
        logical_w, logical_h = self._width, self._height
        if self._is_span_mode(self._display_mode):
            x_pos, y_pos, self._width, self._height = self._all_display_bounds()
            self._window_width = self._width
            self._window_height = self._height
        elif self._is_mirror_mode(self._display_mode):
            x_pos, y_pos, win_w, win_h = self._all_display_bounds()
            # Logical canvas: prefer first display's dimensions for crisp 1:1
            # blits when displays share resolution. Falls back to configured size.
            primary_layout = self._primary_active_layout()
            if primary_layout is not None:
                logical_w = primary_layout[2]
                logical_h = primary_layout[3]
            self._width = logical_w
            self._height = logical_h
            self._window_width = win_w
            self._window_height = win_h
            self._window_origin_x = x_pos
            self._window_origin_y = y_pos
        elif self._fullscreen and self._prefer_borderless_fullscreen():
            x_pos, y_pos, self._width, self._height = self._fullscreen_window_geometry()
            self._window_width = self._width
            self._window_height = self._height
        else:
            x_pos, y_pos = self._window_position_for_display(self._display_index)
            self._window_width = self._width
            self._window_height = self._height

        title = self.cfg.get("window", "title", default="Unicorn Viz")
        win_create_w = self._window_width if self._is_mirror_mode(self._display_mode) else self._width
        win_create_h = self._window_height if self._is_mirror_mode(self._display_mode) else self._height
        self._window = sdl2.SDL_CreateWindow(
            title.encode(),
            x_pos,
            y_pos,
            win_create_w,
            win_create_h,
            flags,
        )
        if not self._window:
            raise RuntimeError(
                f"SDL_CreateWindow failed: {sdl2.SDL_GetError().decode()}"
            )

        self._gl_context = sdl2.SDL_GL_CreateContext(self._window)
        if not self._gl_context:
            raise RuntimeError(
                f"SDL_GL_CreateContext failed: {sdl2.SDL_GetError().decode()}"
            )
        sdl2.SDL_GL_SetSwapInterval(1)  # vsync

        self._set_cursor_visible(self._show_cursor_default)

        # After fullscreen is applied the OS may give us a different size.
        # Query the actual drawable size and update width/height.
        w_i = ctypes.c_int(0)
        h_i = ctypes.c_int(0)
        sdl2.SDL_GetWindowSize(self._window, w_i, h_i)
        if self._is_mirror_mode(self._display_mode):
            # Window size = spanned canvas; logical _width/_height stay at
            # single-display size for effects/HUD/FBO sizing.
            self._sync_window_origin_from_sdl()
            self._window_width = w_i.value or self._window_width
            self._window_height = h_i.value or self._window_height
            self._mirror_rects = self._multihead_mirror_layout(
                self._window_origin_x, self._window_origin_y
            )
            log.info(
                'Mirror (GL-native) active: window=%dx%d logical=%dx%d rects=%s',
                self._window_width,
                self._window_height,
                self._width,
                self._height,
                self._mirror_rects,
            )
        elif self._fullscreen:
            self._width  = w_i.value or self._width
            self._height = h_i.value or self._height
            self._window_width = self._width
            self._window_height = self._height
            log.info(
                'Fullscreen drawable size in %s mode: %dx%d',
                self._display_mode,
                self._width,
                self._height,
            )
        self._update_render_target_size()

    def _init_moderngl(self) -> None:
        self._ctx = moderngl.create_context()
        self._ctx.enable(moderngl.BLEND)
        self._ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        log.info("OpenGL %s", self._ctx.info["GL_VERSION"])
        self._build_present_pipeline()
        self._build_blend_pipeline()
        self._build_invert_pipeline()
        self._build_burst_pipeline()
        if not self._safe_mode:
            # Dancing unicorn overlay (optional, from unicorn-tears drop-in).
            try:
                dancing_cls = _load_dancing_unicorn_class()
                dancing_cfg = self.cfg.get('dancing_unicorn', default={}) or {}
                if not isinstance(dancing_cfg, dict):
                    dancing_cfg = {}
                self._dancing_unicorn = dancing_cls(
                    self._ctx, self._width, self._height, dancing_cfg,
                )
                log.info('DancingUnicornOverlay loaded from unicorn-tears drop-in')
            except Exception as exc:
                log.warning('DancingUnicornOverlay not available: %s', exc)
                self._dancing_unicorn = None
            # Rainbow Nova celebration overlay (optional, from unicorn-tears drop-in).
            try:
                nova_cls = _load_rainbow_nova_class()
                self._rainbow_nova = nova_cls(self._ctx, self._width, self._height)
                log.info('RainbowNova loaded from unicorn-tears drop-in')
            except Exception as exc:
                log.warning('RainbowNova not available: %s', exc)
                self._rainbow_nova = None
            # UnicornTearsController — hotkey dispatcher for all U-key variants.
            try:
                utc_cls = _load_unicorn_tears_controller_class()
                self._unicorn_tears = utc_cls(self.vj_api)
                self.vj_api.register_key_handler('unicorn_tears', self._unicorn_tears.handle_key)
                log.info('UnicornTearsController loaded from drop-in')
            except Exception as exc:
                log.warning('UnicornTearsController not available: %s', exc)
                self._unicorn_tears = None
            # Candy Frame neon border overlay (optional, from candy-frame drop-in).
            try:
                candy_cls = _load_candy_frame_class()
                candy_cfg = self.cfg.get('candy_frame', default={}) or {}
                if not isinstance(candy_cfg, dict):
                    candy_cfg = {}
                self._candy_frame = candy_cls(self._ctx, self._width, self._height, candy_cfg)
                self._candy_frame.set_vj_api(self.vj_api)
                self.vj_api.register_key_handler('candy_frame', self._candy_frame.handle_key)
                log.info('CandyFrameController loaded from candy-frame drop-in')
            except Exception as exc:
                log.warning('CandyFrameController not available: %s', exc)
                self._candy_frame = None
            # System-level webcam overlay (always-on PiP above effects, below HUD).
            webcam_cls = _load_webcam_system_class()
            cam_cfg = self.cfg.get('webcam', default={}) or {}
            if not isinstance(cam_cfg, dict):
                cam_cfg = {}
            try:
                self._webcam_system = webcam_cls(self._ctx, self._width, self._height, cam_cfg)
            except Exception as exc:
                log.warning('WebcamSystem init failed: %s', exc)
                self._webcam_system = _NullWebcamSystem(self._ctx, self._width, self._height, cam_cfg)
            if not isinstance(self._webcam_system, _NullWebcamSystem):
                try:
                    persisted_webcam = self.get_runtime_state('webcam', default={})
                    apply_state = getattr(self._webcam_system, 'apply_persistence_state', None)
                    if callable(apply_state) and isinstance(persisted_webcam, dict):
                        apply_state(persisted_webcam)
                except Exception as exc:
                    log.warning('Webcam runtime-state import failed: %s', exc)
            self._webcam_system.start()
            self._webcam_cycle_interval = float(cam_cfg.get('cycle_interval', 0)) or float(
                self.cfg.get('demo', 'effect_duration', default=20)
            )
            if isinstance(self._webcam_system, _NullWebcamSystem):
                self._webcam_system = None
            else:
                self._webcam_system.set_vj_api(self.vj_api)
                self.vj_api.register_key_handler('webcam', self._webcam_system.handle_key)
                self._persist_webcam_runtime_state()
                log.info('WebcamSystem loaded from drop-in')

            # System-level post-process stack (optional drop-in).
            postfx_cls = _load_postfx_controller_class()
            postfx_cfg = self.cfg.get('postfx', default={}) or {}
            if not isinstance(postfx_cfg, dict):
                postfx_cfg = {}
            try:
                self._postfx_controller = postfx_cls(
                    self._ctx,
                    self._render_width,
                    self._render_height,
                    postfx_cfg,
                )
            except Exception as exc:
                log.warning('PostFxController init failed: %s', exc)
                self._postfx_controller = _NullPostFxController(
                    self._ctx,
                    self._render_width,
                    self._render_height,
                    postfx_cfg,
                )
            if isinstance(self._postfx_controller, _NullPostFxController):
                self._postfx_controller = None
            else:
                self._postfx_controller.set_vj_api(self.vj_api)
                register_runtime_capability(
                    self.vj_api,
                    self._postfx_controller,
                    POSTFX_RUNTIME_CAPABILITY,
                )
                log.info('PostFxController loaded from drop-in')

            # Global colour-grade / LUT post pass (optional drop-in). Runs in the
            # global post chain after postfx; degrades to None when absent.
            color_grade_cfg = self.cfg.get('color_grade', default={}) or {}
            if not isinstance(color_grade_cfg, dict):
                color_grade_cfg = {}
            if not bool(color_grade_cfg.get('enabled', True)):
                self._color_grade = None
                log.info('ColorGradeController disabled by config')
            else:
                try:
                    color_grade_cls = _load_color_grade_controller_class()
                    self._color_grade = color_grade_cls(
                        self._ctx,
                        self._render_width,
                        self._render_height,
                        color_grade_cfg,
                    )
                    self._color_grade.set_vj_api(self.vj_api)
                    self.vj_api.register_subsystem('color_grade', self._color_grade)
                    key_handler = getattr(self._color_grade, 'handle_key', None)
                    if callable(key_handler):
                        self.vj_api.register_key_handler('color_grade', key_handler)
                    log.info('ColorGradeController loaded from drop-in')
                except Exception as exc:
                    self._color_grade = None
                    log.warning('ColorGradeController not available: %s', exc)

            # BPM-locked strobe / flash post pass with safety governor (optional).
            beat_flash_cfg = self.cfg.get('beat_flash', default={}) or {}
            if not isinstance(beat_flash_cfg, dict):
                beat_flash_cfg = {}
            if not bool(beat_flash_cfg.get('enabled', True)):
                self._beat_flash = None
                log.info('BeatFlashController disabled by config')
            else:
                try:
                    beat_flash_cls = _load_beat_flash_controller_class()
                    self._beat_flash = beat_flash_cls(
                        self._ctx,
                        self._render_width,
                        self._render_height,
                        beat_flash_cfg,
                    )
                    self._beat_flash.set_vj_api(self.vj_api)
                    self.vj_api.register_subsystem('beat_flash', self._beat_flash)
                    key_handler = getattr(self._beat_flash, 'handle_key', None)
                    if callable(key_handler):
                        self.vj_api.register_key_handler('beat_flash', key_handler)
                    log.info('BeatFlashController loaded from drop-in')
                except Exception as exc:
                    self._beat_flash = None
                    log.warning('BeatFlashController not available: %s', exc)

            # System-level screen burst timing/transform controller (optional).
            try:
                burst_cls = _load_screen_burst_controller_class()
                burst_cfg = self.cfg.get('screen_burst', default={}) or {}
                if not isinstance(burst_cfg, dict):
                    burst_cfg = {}
                self._burst_controller = burst_cls(burst_cfg)
                log.info('ScreenBurstController loaded from unicorn-tears drop-in')
            except Exception as exc:
                log.warning('ScreenBurstController not available: %s', exc)
                self._burst_controller = _NullScreenBurstController()
        else:
            log.info('Safe mode enabled: skipping optional visual drop-ins')

    def _build_present_pipeline(self) -> None:
        """Build fullscreen pass that copies a texture to screen."""
        vert = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""
        frag = """
#version 330
uniform sampler2D tex;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    fragColor = texture(tex, v_uv);
}
"""
        self._present_prog = self._ctx.program(vertex_shader=vert, fragment_shader=frag)
        verts = np.array([-1, -1, -1, 1, 1, -1, 1, 1], dtype=np.float32)
        self._present_vbo = self._ctx.buffer(verts)
        self._present_vao = self._ctx.vertex_array(
            self._present_prog, [(self._present_vbo, '2f', 'in_vert')]
        )

    def _build_burst_pipeline(self) -> None:
        """Build the screen-spin/scale post-process shader used by Ctrl+U."""
        vert = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""
        frag = """
#version 330
// Screen burst post-process — rotates and scales the frame around its centre.
// Uniforms: uAngle (radians), uScale (>1 = zoom in), tex (frame texture).
uniform sampler2D tex;
uniform float uAngle;
uniform float uScale;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    vec2 uv = v_uv - 0.5;
    float c = cos(uAngle);
    float s = sin(uAngle);
    uv = mat2(c, -s, s, c) * uv;  // rotate
    uv /= uScale;                   // scale (>1 zooms in)
    uv += 0.5;
    // Vignette for dramatic edge darkening during the burst
    vec2 vig = v_uv - 0.5;
    float vignette = 1.0 - dot(vig, vig) * 1.6;
    vignette = clamp(vignette, 0.0, 1.0);
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) {
        fragColor = vec4(0.0, 0.0, 0.0, 1.0);
    } else {
        vec4 col = texture(tex, uv);
        col.rgb *= mix(1.0, vignette, 0.30);
        fragColor = col;
    }
}
"""
        self._burst_prog = self._ctx.program(vertex_shader=vert, fragment_shader=frag)
        verts = np.array([-1, -1, -1, 1, 1, -1, 1, 1], dtype=np.float32)
        self._burst_vbo = self._ctx.buffer(verts)
        self._burst_vao = self._ctx.vertex_array(
            self._burst_prog, [(self._burst_vbo, '2f', 'in_vert')]
        )

    def trigger_burst(self) -> None:
        """Trigger the Ctrl+Alt+U screen-burst animation."""
        self._burst_controller.trigger()

    def trigger_dancing_unicorn(self) -> None:
        """Trigger the Ctrl+U dancing unicorn overlay."""
        if self._dancing_unicorn is not None:
            self._dancing_unicorn.trigger()

    def trigger_rainbow_nova(self) -> None:
        """Trigger the Alt+U Rainbow Nova celebration overlay."""
        if self._rainbow_nova is not None:
            self._rainbow_nova.trigger()

    def toggle_candy_frame(self) -> str:
        """Toggle Candy Frame overlay; returns a flash-message string."""
        if self._candy_frame is None:
            return 'Candy Frame drop-in not loaded'
        active = bool(self._candy_frame.toggle())
        if active:
            pattern = str(getattr(self._candy_frame, 'current_pattern_name', 'Pattern'))
            return f'Candy Frame ON  ({pattern})'
        return 'Candy Frame OFF'

    def trigger_grand_finale(self) -> str:
        """Trigger the grand finale sequence; returns a flash-message string."""
        if self._grand_finale is None:
            return 'Grand Finale drop-in not loaded'
        msg = self._grand_finale.trigger()
        if self._overlays is not None:
            self._overlays.flash_message(msg, 2.5)
        return msg

    def abort_grand_finale(self) -> str:
        """Abort the grand finale and restore pre-finale state."""
        if self._grand_finale is None:
            return 'Grand Finale drop-in not loaded'
        msg = self._grand_finale.abort()
        if self._overlays is not None:
            self._overlays.flash_message(msg, 2.0)
        return msg

    def toggle_auto_vj(self) -> str:
        """Toggle Auto VJ controller on/off; returns a flash-message string."""
        if self._auto_vj is None:
            return 'Auto VJ not loaded'
        enabled = self._auto_vj.toggle()
        pill = 'AUTO VJ  ON' if enabled else 'AUTO VJ  OFF'
        self.vj_api.set_status_pill(pill)
        return pill

    def _burst_transform(self) -> tuple[float, float]:
        """Return (scale, angle_radians) for current burst frame."""
        return self._burst_controller.transform()

    def _present_burst_from_tex(self, tex: moderngl.Texture) -> None:
        """Render the burst-transformed frame to screen."""
        self._compose_debug = f'burst:{self._tex_debug_name(tex)}->screen'
        scale, angle = self._burst_transform()
        self._ctx.screen.use()
        self._ctx.viewport = (0, 0, self._width, self._height)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        tex.use(location=0)
        self._burst_prog['tex'].value = 0
        self._burst_prog['uAngle'].value = angle
        self._burst_prog['uScale'].value = scale
        self._burst_vao.render(moderngl.TRIANGLE_STRIP)

    def _sync_recording_overlay(self) -> None:
        """Keep the recording indicator state in sync with the recorder."""
        if self._overlays is not None:
            elapsed_seconds = 0.0
            if self._recorder is not None:
                elapsed_seconds = self._recorder.elapsed_seconds
            self._overlays.set_recording_state(
                self._recorder is not None and self._recorder.is_recording,
                elapsed_seconds=elapsed_seconds,
            )

    def _hud_audio_state_fields(self) -> dict[str, str]:
        """Return audio meter fields for the HUD state dict.

        Prefers ``_audio_raw`` (unscaled) so the HUD always shows the true
        signal level regardless of the current reactivity multiplier.  Falls
        back to ``_audio`` (reactivity-scaled) when raw is unavailable, and
        to safe zero defaults when both are None.
        """
        src = self._audio_raw if self._audio_raw is not None else self._audio
        if src is None:
            return {
                'bass': '0.00', 'mid': '0.00', 'treble': '0.00',
                'bass_n': '0.50', 'mid_n': '0.50', 'treble_n': '0.50',
                'audio_beat': '0.000',
            }
        return {
            'bass':    f'{src.bass:.2f}',
            'mid':     f'{src.mid:.2f}',
            'treble':  f'{src.treble:.2f}',
            'bass_n':  f'{src.bass_n:.2f}',
            'mid_n':   f'{src.mid_n:.2f}',
            'treble_n': f'{src.treble_n:.2f}',
            'audio_beat': f'{src.beat:.3f}',
        }

    def _build_invert_pipeline(self) -> None:
        """Build fullscreen pass that inverts a texture's colors."""
        vert = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""
        frag = """
#version 330
uniform sampler2D tex;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    vec4 c = texture(tex, v_uv);
    fragColor = vec4(vec3(1.0) - c.rgb, c.a);
}
"""
        self._invert_prog = self._ctx.program(vertex_shader=vert, fragment_shader=frag)
        verts = np.array([-1, -1, -1, 1, 1, -1, 1, 1], dtype=np.float32)
        self._invert_vbo = self._ctx.buffer(verts)
        self._invert_vao = self._ctx.vertex_array(
            self._invert_prog, [(self._invert_vbo, "2f", "in_vert")]
        )

    def _render_inverted_from_tex(self, tex: moderngl.Texture) -> None:
        """Render a texture to screen through the invert post-process pass."""
        self._compose_debug = f'invert:{self._tex_debug_name(tex)}->screen'
        self._ctx.screen.use()
        self._ctx.viewport = (0, 0, self._width, self._height)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        tex.use(location=0)
        self._invert_prog["tex"].value = 0
        self._invert_vao.render(moderngl.TRIANGLE_STRIP)

    def _blit_fbo_b_to_fbo_a(self, w: int, h: int, *, clear: bool = True) -> None:
        """Blit fbo_b's color attachment back into fbo_a via the present shader.

        Used throughout the composite pipeline after rendering a pass into fbo_b
        so the result becomes the new fbo_a base for subsequent overlay passes.
        Pass ``clear=False`` when fbo_a's previous content must not be discarded
        (e.g. late-stage overlay composition where fbo_a may still be needed).
        """
        self._fbo_a.use()
        self._ctx.viewport = (0, 0, w, h)
        if clear:
            self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        self._fbo_b.color_attachments[0].use(location=0)
        self._present_prog['tex'].value = 0
        self._present_vao.render(moderngl.TRIANGLE_STRIP)

    def _active_post_chain(self) -> list:
        """Return the ordered list of active global post-FX controllers.

        Order is postfx → colour-grade (→ beat-flash, added by that drop-in).
        Each entry exposes the shared ``apply(src_tex, dst_fbo, dt, bass, mid,
        treble, beat)`` contract and an ``is_active()`` predicate.
        """
        chain: list = []
        pf = self._postfx_controller
        if pf is not None and pf.is_active():
            chain.append(pf)
        cg = self._color_grade
        if cg is not None and cg.is_active():
            chain.append(cg)
        bf = self._beat_flash
        if bf is not None and bf.is_active():
            chain.append(bf)
        return chain

    def _apply_post_chain(self, dt: float) -> None:
        """Run the active global post-FX chain in place over fbo_a.

        Each active pass renders fbo_a → fbo_b and is blitted back into fbo_a,
        so the chained result always ends in fbo_a regardless of pass count.
        """
        audio = self._audio or AudioData()
        bass = float(audio.bass)
        mid = float(audio.mid)
        treble = float(audio.treble)
        beat = float(audio.beat)
        for ctrl in self._active_post_chain():
            ctrl.apply(
                self._fbo_a.color_attachments[0],
                self._fbo_b,
                dt,
                bass,
                mid,
                treble,
                beat,
            )
            self._blit_fbo_b_to_fbo_a(self._render_width, self._render_height)

    def _present_from_tex(self, tex: moderngl.Texture) -> None:
        """Render a texture to screen without post-processing."""
        self._compose_debug = f'{self._tex_debug_name(tex)}->screen'
        self._ctx.screen.use()
        self._ctx.viewport = (0, 0, self._width, self._height)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        tex.use(location=0)
        self._present_prog['tex'].value = 0
        self._present_vao.render(moderngl.TRIANGLE_STRIP)

    def _present_mirror_tiled(self, tex: moderngl.Texture) -> None:
        """Blit a texture across all mirror display regions in the spanned window.

        GL viewport y is bottom-up; SDL display rects are top-down.
        """
        self._compose_debug = f'{self._tex_debug_name(tex)}->mirror_tiled'
        self._ctx.screen.use()
        self._ctx.viewport = (0, 0, self._window_width, self._window_height)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        tex.use(location=0)
        self._present_prog['tex'].value = 0
        for dx, dy, dw, dh in self._mirror_rects:
            gl_y = self._window_height - (dy + dh)
            self._ctx.viewport = (dx, gl_y, dw, dh)
            self._present_vao.render(moderngl.TRIANGLE_STRIP)
        # Restore default viewport for any subsequent overlay passes.
        self._ctx.viewport = (0, 0, self._window_width, self._window_height)

    def _tex_debug_name(self, tex: moderngl.Texture | None) -> str:
        """Return a stable short texture source label for HUD diagnostics."""
        if tex is None:
            return 'none'
        try:
            if self._fbo_a is not None and tex is self._fbo_a.color_attachments[0]:
                return 'fbo_a'
            if self._fbo_b is not None and tex is self._fbo_b.color_attachments[0]:
                return 'fbo_b'
        except Exception:
            pass
        return 'tex'

    def _effect_reactivity(self, effect: BaseEffect | None) -> float | None:
        """Return per-effect reactivity override, or None if not set."""
        if effect is None:
            return None
        cfg = getattr(effect, "config", None)
        if not isinstance(cfg, dict):
            return None
        if "reactivity" not in cfg:
            return None
        try:
            value = float(cfg.get("reactivity", 1.0))
        except Exception:
            return None
        return max(0.1, min(5.0, value))

    def _fill_audio_scratch(
        self,
        target: AudioData,
        source: AudioData,
        scale: float,
    ) -> AudioData:
        """Populate a reusable AudioData scratch buffer from a source snapshot."""
        target.bass = min(1.0, source.bass * scale)
        target.mid = min(1.0, source.mid * scale)
        target.treble = min(1.0, source.treble * scale)
        target.beat = source.beat
        target.bpm = source.bpm
        np.multiply(source.fft, scale, out=target.fft)
        np.clip(target.fft, 0.0, 1.0, out=target.fft)
        target.waveform[:] = source.waveform
        return target

    def _audio_for_effect(
        self,
        source: AudioData,
        effect: BaseEffect | None,
        target: AudioData,
    ) -> AudioData:
        """Build an effect-local audio view with optional reactivity scaling.

        Global reactivity is already applied by AudioManager. If an effect defines
        `[effects.<ClassName>].reactivity`, treat it as the absolute desired
        reactivity for that effect (not an extra multiplier).
        """
        r_override = self._effect_reactivity(effect)
        if r_override is None:
            return source

        global_r = 1.0
        if self._audio_manager is not None:
            global_r = max(0.1, self._audio_manager.get_reactivity())

        scale = r_override / global_r
        if abs(scale - 1.0) < 1e-6:
            return source

        return self._fill_audio_scratch(target, source, scale)

    def _system_monitor_audio_snapshot(self) -> dict[str, float]:
        """Return live monitor audio/frame metrics independent of HUD payload."""
        src = self._audio_raw if self._audio_raw is not None else self._audio
        if src is None:
            bass = 0.0
            mid = 0.0
            treble = 0.0
            bass_n = 0.5
            mid_n = 0.5
            treble_n = 0.5
        else:
            bass = float(src.bass)
            mid = float(src.mid)
            treble = float(src.treble)
            bass_n = float(src.bass_n)
            mid_n = float(src.mid_n)
            treble_n = float(src.treble_n)

        return {
            'fps': float(self._last_frame_fps),
            'frame_ms': float(self._last_frame_ms),
            'bass': bass,
            'mid': mid,
            'treble': treble,
            'bass_n': bass_n,
            'mid_n': mid_n,
            'treble_n': treble_n,
        }

    def build_live_corpus_sample(self) -> dict[str, Any]:
        """Return a compact merged VJ snapshot for the Spotify live corpus sink."""

        src = self._audio_raw if self._audio_raw is not None else self._audio
        effect_name = self._current_effect.NAME if self._current_effect is not None else '-'
        effect_label = getattr(self._overlays, '_name_text', effect_name) if self._overlays is not None else effect_name
        audio_source = self._audio_manager.get_source_label() if self._audio_manager is not None else 'n/a'
        audio_profile = self._audio_manager.get_profile_name() if self._audio_manager is not None else 'n/a'
        audio_snapshot = self._system_monitor_audio_snapshot()
        fft_peak = 0.0
        fft_mean = 0.0
        fft_peak_bin = -1
        waveform_peak = 0.0
        waveform_rms = 0.0
        waveform_mean_abs = 0.0
        if src is not None:
            fft = np.asarray(src.fft, dtype=np.float32)
            waveform = np.asarray(src.waveform, dtype=np.float32)
            if fft.size > 0:
                fft_peak_bin = int(np.argmax(fft))
                fft_peak = float(np.max(fft))
                fft_mean = float(np.mean(fft))
            if waveform.size > 0:
                waveform_peak = float(np.max(np.abs(waveform)))
                waveform_rms = float(np.sqrt(np.mean(np.square(waveform), dtype=np.float64)))
                waveform_mean_abs = float(np.mean(np.abs(waveform)))
        return {
            'vj_effect': effect_name,
            'vj_effect_label': effect_label,
            'vj_previous_effect': self._previous_effect_name,
            'vj_playlist_mode': self._playlist_mode,
            'vj_playlist_index': self._playlist_index,
            'vj_playlist_size': self._playlist_size,
            'vj_fps': self._last_frame_fps,
            'vj_frame_ms': self._last_frame_ms,
            'vj_audio_source': audio_source,
            'vj_audio_profile': audio_profile,
            'vj_audio_bass': audio_snapshot['bass'],
            'vj_audio_mid': audio_snapshot['mid'],
            'vj_audio_treble': audio_snapshot['treble'],
            'vj_audio_bass_n': audio_snapshot['bass_n'],
            'vj_audio_mid_n': audio_snapshot['mid_n'],
            'vj_audio_treble_n': audio_snapshot['treble_n'],
            'vj_audio_bpm': float(src.bpm) if src is not None else 120.0,
            'vj_audio_beat': float(src.beat) if src is not None else 0.0,
            'vj_audio_bass_flux': float(src.bass_flux) if src is not None else 0.0,
            'vj_audio_mid_flux': float(src.mid_flux) if src is not None else 0.0,
            'vj_audio_fft_peak': fft_peak,
            'vj_audio_fft_mean': fft_mean,
            'vj_audio_fft_peak_bin': fft_peak_bin,
            'vj_audio_waveform_peak': waveform_peak,
            'vj_audio_waveform_rms': waveform_rms,
            'vj_audio_waveform_mean_abs': waveform_mean_abs,
        }

    def get_live_audio_window(self, duration_s: float = 10.0) -> tuple[np.ndarray, int] | None:
        """Return a recent mono PCM window for live stream analysis."""

        if self._audio_manager is None:
            return None
        return self._audio_manager.get_recent_pcm_window(duration_s=duration_s)

    def _system_monitor_tweakables_snapshot(self) -> dict[str, float | None]:
        """Return live tweakable values for the system monitor modal."""
        reactivity = 1.0
        if self._audio_manager is not None:
            reactivity = float(self._audio_manager.get_reactivity())

        speed: float | None = None
        zoom: float | None = None
        effect = self._current_effect
        if effect is not None:
            try:
                if 'speed' in effect.parameters:
                    speed = float(effect.parameters['speed'])
                if 'zoom' in effect.parameters:
                    zoom = float(effect.parameters['zoom'])
            except Exception:
                # Keep monitor render path resilient if an effect mutates parameters unexpectedly.
                pass

        return {
            'reactivity': reactivity,
            'speed': speed,
            'zoom': zoom,
        }

    def _build_blend_pipeline(self) -> None:
        """FBO-pair + transition shader used for cross-effect blending."""
        self._fbo_a = self._make_fbo()
        self._fbo_b = self._make_fbo()

        vert = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""
        frag = """
#version 330
uniform sampler2D tex_a;
uniform sampler2D tex_b;
uniform float t;
uniform int mode;
    uniform vec2 dir;
    uniform float phase;
    uniform float iAudioImpact;
    uniform float iPalShift;
    uniform float iLightWrap;
in vec2 v_uv;
out vec4 fragColor;

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

void main() {
    vec2 nd = normalize(dir);
    vec2 uv_a = v_uv - nd * (1.0 - t) * (0.018 + iAudioImpact * 0.012);
    vec2 uv_b = v_uv + nd * (1.0 - t) * (0.018 + iAudioImpact * 0.012);
    vec4 a = texture(tex_a, clamp(uv_a, 0.0, 1.0));
    vec4 b = texture(tex_b, clamp(uv_b, 0.0, 1.0));
    vec4 col;

    if (mode == 0) {
        // linear crossfade
        col = mix(a, b, t);
    } else if (mode == 1) {
        // smoothstep crossfade
        float s = smoothstep(0.0, 1.0, t);
        col = mix(a, b, s);
    } else if (mode == 2) {
        // horizontal wipe
        float edge = smoothstep(t - 0.02, t + 0.02, v_uv.x + nd.x * 0.08);
        col = mix(a, b, edge);
    } else if (mode == 3) {
        // vertical wipe
        float edge = smoothstep(t - 0.02, t + 0.02, v_uv.y + nd.y * 0.08);
        col = mix(a, b, edge);
    } else if (mode == 4) {
        // dissolve noise threshold with mild temporal flow
        float n = hash(floor((v_uv + vec2(phase * 0.13, -phase * 0.11)) * vec2(1920.0, 1080.0)));
        float edge = smoothstep(t - 0.04, t + 0.04, n);
        col = mix(a, b, edge);
    } else if (mode == 5) {
        // zoom blend
        vec2 c = vec2(0.5);
        vec2 uza = c + (v_uv - c) * (1.0 + 0.12 * t + iAudioImpact * 0.05);
        vec2 uzb = c + (v_uv - c) * (1.12 - 0.12 * t - iAudioImpact * 0.05);
        vec4 az = texture(tex_a, clamp(uza, 0.0, 1.0));
        vec4 bz = texture(tex_b, clamp(uzb, 0.0, 1.0));
        col = mix(az, bz, t);
    } else if (mode == 6) {
        // radial wipe from center outward
        float r = length(v_uv - vec2(0.5));
        float edge = smoothstep(t * 0.85 - 0.03, t * 0.85 + 0.03, r);
        col = mix(b, a, edge);
    } else if (mode == 7) {
        // luma threshold reveal
        float l = dot(b.rgb, vec3(0.2126, 0.7152, 0.0722));
        float edge = smoothstep(t - 0.08, t + 0.08, l);
        col = mix(a, b, edge);
    } else if (mode == 8) {
        // stripe wipe with animated bands
        float bands = 0.5 + 0.5 * sin((v_uv.x * 24.0 + v_uv.y * 14.0) + phase * 10.0);
        float edge = smoothstep(t - 0.06, t + 0.06, bands);
        col = mix(a, b, edge);
    } else if (mode == 9) {
        // angular sweep around center
        vec2 p = v_uv - vec2(0.5);
        float a0 = atan(p.y, p.x) / 6.2831853 + 0.5;
        float edge = smoothstep(t - 0.04, t + 0.04, fract(a0 + phase * 0.2));
        col = mix(a, b, edge);
    } else if (mode == 10) {
        // soft glitch slide bands
        float n = hash(floor(v_uv * vec2(48.0, 96.0) + phase * 7.0));
        vec2 j = vec2((n - 0.5) * 0.03 * (1.0 - t), 0.0);
        vec4 ag = texture(tex_a, clamp(v_uv + j, 0.0, 1.0));
        vec4 bg = texture(tex_b, clamp(v_uv - j, 0.0, 1.0));
        col = mix(ag, bg, smoothstep(0.0, 1.0, t));
    } else {
        // prism split blend
        float s = (1.0 - t) * 0.02;
        vec3 ar = texture(tex_a, clamp(v_uv + vec2( s, 0.0), 0.0, 1.0)).rgb;
        vec3 ag = texture(tex_a, clamp(v_uv,                    0.0, 1.0)).rgb;
        vec3 ab = texture(tex_a, clamp(v_uv + vec2(-s, 0.0), 0.0, 1.0)).rgb;
        vec3 br = texture(tex_b, clamp(v_uv + vec2(-s, 0.0), 0.0, 1.0)).rgb;
        vec3 bg = texture(tex_b, clamp(v_uv,                    0.0, 1.0)).rgb;
        vec3 bb = texture(tex_b, clamp(v_uv + vec2( s, 0.0), 0.0, 1.0)).rgb;
        vec3 ca = vec3(ar.r, ag.g, ab.b);
        vec3 cb = vec3(br.r, bg.g, bb.b);
        col = vec4(mix(ca, cb, t), 1.0);
    }

    // Light-wrap from frame difference to soften hard transitions.
    vec3 wrap = abs(a.rgb - b.rgb);
    col.rgb += wrap * iLightWrap * (0.25 + 0.75 * iAudioImpact);

    // Subtle palette remap pulse for transition cohesion.
    float lum = dot(col.rgb, vec3(0.2126, 0.7152, 0.0722));
    vec3 remap = 0.6 + 0.4 * cos(6.28318 * (lum + vec3(0.0, 0.33, 0.67) + iPalShift));
    col.rgb = mix(col.rgb, col.rgb * remap, 0.08 + 0.18 * iAudioImpact);

    fragColor = vec4(clamp(col.rgb, 0.0, 1.0), 1.0);
}
"""
        self._blend_prog = self._ctx.program(
            vertex_shader=vert, fragment_shader=frag
        )
        verts = np.array([-1, -1, -1, 1, 1, -1, 1, 1], dtype=np.float32)
        vbo = self._ctx.buffer(verts)
        self._blend_vao = self._ctx.vertex_array(
            self._blend_prog, [(vbo, "2f", "in_vert")]
        )
        self._blend_vbo = vbo  # keep ref so it's not GC'd

    def _make_fbo(self) -> moderngl.Framebuffer:
        # Clamp to GL_MAX_TEXTURE_SIZE just in case the render scale or
        # display size produces an out-of-range dimension during transitions
        # (e.g. mirror_all → single while SDL is still reporting transient
        # geometry).  Without this clamp moderngl raises
        # "_moderngl.Error: cannot create texture" which previously crashed
        # the whole app.
        max_edge = 16384
        try:
            max_edge = int(self._ctx.info.get('GL_MAX_TEXTURE_SIZE', max_edge))
        except Exception:
            pass
        width = max(1, min(int(max_edge), int(self._render_width)))
        height = max(1, min(int(max_edge), int(self._render_height)))
        try:
            tex = self._ctx.texture((width, height), 4)
        except Exception as exc:
            log.warning(
                'FBO texture allocation failed at %dx%d (%s); retrying at 1280x720',
                width, height, exc,
            )
            # Fall back to a known-safe size so the app does not crash.
            # The next resize/mode change will reallocate at the right size.
            width, height = 1280, 720
            self._render_width = width
            self._render_height = height
            tex = self._ctx.texture((width, height), 4)
        tex.filter = moderngl.LINEAR, moderngl.LINEAR
        depth = self._ctx.depth_renderbuffer((width, height))
        return self._ctx.framebuffer(color_attachments=[tex], depth_attachment=depth)

    def _update_render_target_size(self) -> None:
        """Recompute scaled internal render target dimensions."""
        max_edge = 16384
        if self._ctx is not None:
            try:
                max_edge = int(self._ctx.info.get('GL_MAX_TEXTURE_SIZE', max_edge))
            except Exception:
                max_edge = 16384
        self._render_width = max(1, min(max_edge, int(round(self._width * self._render_scale))))
        self._render_height = max(1, min(max_edge, int(round(self._height * self._render_scale))))

    def _set_cursor_visible(self, visible: bool) -> None:
        """Set cursor visibility state in SDL."""
        try:
            sdl2.SDL_ShowCursor(sdl2.SDL_ENABLE if visible else sdl2.SDL_DISABLE)
        except Exception:
            pass

    def _cursor_modal_override_active(self) -> bool:
        """Return True when any overlay modal/help/selector is active."""
        overlays = getattr(self, '_overlays', None)
        if overlays is None:
            return False
        visibility_flags = (
            'help_visible',
            'audio_selector_visible',
            'midi_selector_visible',
            'system_monitor_modal_visible',
            'controller_help_modal_visible',
            'projectm_manager_visible',
            'webcam_editor_modal_visible',
            'effects_browser_visible',
        )
        for name in visibility_flags:
            if bool(getattr(overlays, name, False)):
                return True
        return False

    def _cursor_should_be_visible(self) -> bool:
        """Return effective cursor visibility from base policy + modal override."""
        return (
            self._show_cursor_default
            or self._ctrl_held
            or self._cursor_modal_override_active()
        )

    def _update_ctrl_state(self, sym: int, is_keydown: bool) -> None:
        if sym in (sdl2.SDLK_LCTRL, sdl2.SDLK_RCTRL):
            self._ctrl_held = is_keydown
            self._set_cursor_visible(self._cursor_should_be_visible())

    # ------------------------------------------------------------------ #
    # Effect management                                                    #
    # ------------------------------------------------------------------ #

    def _instantiate(
        self,
        cls: Type[BaseEffect],
        width: int | None = None,
        height: int | None = None,
    ) -> BaseEffect:
        effect_cfg = self.cfg.get("effects", cls.__name__, default={})
        if not isinstance(effect_cfg, dict):
            effect_cfg = {}
        # Inject top-level [ansi] config into ANSIViewer so it finds the art dir
        if cls.__name__ == "ANSIViewer":
            ansi_dir = self.cfg.get(
                "ansi", "ansi_dir_auto",
                default=self.cfg.get("ansi", "ansi_dir", default="assets/ansi"),
            )
            effect_cfg = {"ansi_dir": str(resolve_path(ansi_dir)), **effect_cfg}
        w = self._width if width is None else int(width)
        h = self._height if height is None else int(height)
        return cls(self._ctx, w, h, effect_cfg)

    def _switch_effect(self, cls: Type[BaseEffect]) -> None:
        """Begin transition to a new effect."""
        if self._projectm_manager_modal_active:
            log.info(
                'Effect switch blocked while ProjectM manager is open: %s',
                getattr(cls, 'NAME', getattr(cls, '__name__', str(cls))),
            )
            return
        lock = self._effect_lock
        if lock is not None and getattr(cls, 'NAME', None) != lock:
            # Locked to one effect (e.g. ProjectM-only mode): don't leave it.
            # Redirect the swap intent into a variation of the locked effect so
            # automation/auto-advance keep things fresh without switching away
            # (for ProjectM that means advancing to the next preset).
            cur = self._current_effect
            vary = getattr(cur, 'next_preset', None) if cur is not None else None
            if callable(vary):
                try:
                    vary()
                except Exception:
                    log.debug('Locked-effect variation failed', exc_info=True)
            else:
                log.debug('Effect switch blocked by lock (%s): %s', lock,
                          getattr(cls, 'NAME', cls))
            return
        # Invert does not carry through transitions.
        self._invert_colors = False
        if self._current_effect is not None:
            self._previous_effect_name = self._current_effect.NAME
        if self._next_effect is not None:
            self._next_effect.destroy()
        self._next_effect = self._instantiate(cls)

        requested = str(self.cfg.get("demo", "transition", default="crossfade")).lower()
        transition_types = [
            "crossfade",
            "smoothfade",
            "scanwipe_x",
            "scanwipe_y",
            "dissolve",
            "zoomblend",
            "radialwipe",
            "lumawipe",
            "stripewipe",
            "anglesweep",
            "glitchsoft",
            "prismsplit",
        ]
        if requested in ("random", "shuffle"):
            # Transition 2.0: choose style by effect vibe tags.
            next_tags = [t.lower() for t in getattr(cls, "TAGS", [])]
            curr_tags = [t.lower() for t in getattr(self._current_effect, "TAGS", [])] if self._current_effect else []
            tags = set(curr_tags + next_tags)

            if "psychedelic" in tags or "crystal" in tags:
                weighted = ["dissolve", "zoomblend", "prismsplit", "anglesweep", "smoothfade", "crossfade"]
            elif "classic" in tags:
                weighted = ["scanwipe_x", "scanwipe_y", "stripewipe", "crossfade", "smoothfade"]
            elif "simulation" in tags or "particles" in tags:
                weighted = ["zoomblend", "dissolve", "radialwipe", "glitchsoft", "smoothfade", "crossfade"]
            else:
                weighted = transition_types
            self._transition_kind = str(self._rng.choice(weighted))
        elif requested == "scanwipe":
            self._transition_kind = "scanwipe_y"
        elif requested == "cut":
            # Keep cut soft for performance environments.
            self._transition_kind = "smoothfade"
        elif requested == "radial":
            self._transition_kind = "radialwipe"
        elif requested in transition_types:
            self._transition_kind = requested
        else:
            self._transition_kind = "crossfade"
        log.info("Transition → %s", self._transition_kind)

        self._transition_t = 0.0
        a = float(self._rng.uniform(0.0, np.pi * 2.0))
        self._transition_dir = (float(np.cos(a)), float(np.sin(a)))
        self._transition_phase = float(self._rng.uniform(0.0, 1.0))
        self._demo_timer = 0.0

    def show_splash(self) -> None:
        """Replay the splash screen (hotkey U)."""
        if self._splash_config is None:
            return
        now = time.monotonic()
        if (now - self._last_splash_replay_t) < _SPLASH_REPLAY_COOLDOWN_S:
            log.info(
                'Splash replay ignored (cooldown %.2fs)',
                _SPLASH_REPLAY_COOLDOWN_S,
            )
            return
        self._last_splash_replay_t = now
        log.info('Splash replay requested')
        try:
            from unicornviz.splash import Splash
            config = self._splash_config

            splash_w, splash_h, splash_viewport = self._splash_render_target()

            def _splash_bass() -> float:
                audio = config["audio_manager"].get_audio_data()
                return float(audio.bass) if audio else 0.0
            
            splash = Splash(
                self._ctx,
                splash_w,
                splash_h,
                image_path=config["path"],
                duration=_SPLASH_TOTAL_DURATION,
                bass_supplier=_splash_bass,
                render_viewport=splash_viewport,
            )
            splash.run(self._window)
            splash.destroy()
        except Exception as e:
            log.error("Failed to show splash: %s", e)

    # ------------------------------------------------------------------ #
    # Main loop                                                            #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        self._init_sdl()
        self._init_moderngl()

        # Subsystems (audio starts before splash so splash can react to music)
        log.info('Startup: initializing audio subsystem')
        audio_manager = AudioManager(self.cfg, state_store=self._runtime_state)
        audio_start_timeout_s = float(self.cfg.get('audio', 'start_timeout_s', default=4.0))
        audio_start_retries = int(self.cfg.get('audio', 'start_retries', default=2))
        audio_start_backoff_s = float(
            self.cfg.get('audio', 'start_retry_backoff_s', default=0.5)
        )
        audio_require_startup = bool(
            self.cfg.get('audio', 'require_startup', default=False)
        )
        if audio_start_retries < 0:
            audio_start_retries = 0
        total_audio_attempts = audio_start_retries + 1
        audio_start_ok = False
        for attempt in range(1, total_audio_attempts + 1):
            log.info(
                'Startup: audio attempt %d/%d (timeout=%.2fs)',
                attempt,
                total_audio_attempts,
                audio_start_timeout_s,
            )
            try:
                audio_manager.start(timeout_s=audio_start_timeout_s)
                log.info('Startup: audio subsystem ready')
                audio_start_ok = True
                break
            except Exception as exc:
                log.error(
                    'Startup: audio attempt %d/%d failed: %s',
                    attempt,
                    total_audio_attempts,
                    exc,
                )
                try:
                    audio_manager.stop()
                except Exception:
                    log.debug('Startup: audio cleanup failed after attempt %d', attempt)
                if audio_start_backoff_s > 0:
                    time.sleep(audio_start_backoff_s)
        if not audio_start_ok:
            msg = f'Audio startup failed after {total_audio_attempts} attempts'
            if audio_require_startup:
                raise RuntimeError(msg)
            log.warning('%s; continuing with audio disabled/inactive', msg)
        self._audio_manager = audio_manager

        # Kick off background image decoding so disk I/O overlaps with the splash.
        # warm_cache() after the splash will find bytes already in memory and
        # only need to do fast GL uploads.
        _pre_effects = get_effects()
        for _cls in _pre_effects:
            if getattr(_cls, 'NAME', '') == 'Image Showcase' and hasattr(_cls, 'prefetch_async'):
                _img_cfg = self.cfg.get('effects', 'ImageShowcase', default={}) or {}
                if bool(_img_cfg.get('preload_images', False)):
                    _cls.prefetch_async(_img_cfg)
                break

        # Pre-bake Sim Showcase USD scenes (skinning / rigid frames) in the
        # background so the first time it activates it doesn't hitch. CPU-only;
        # the GL upload still happens lazily on activation.
        for _cls in _pre_effects:
            if getattr(_cls, 'NAME', '') == 'Sim Showcase' and hasattr(_cls, 'prewarm_async'):
                _sim_cfg = self.cfg.get('effects', 'SimShowcase', default={}) or {}
                if bool(_sim_cfg.get('preload', True)):
                    _cls.prewarm_async(_sim_cfg)
                break

        # Splash screen — shown before any effect loads
        splash_path = str(resolve_path(self.cfg.get("splash", "image", default="images/unicorn-viz-01.png")))
        splash_duration_audio = _SPLASH_TOTAL_DURATION
        splash_duration_silent = _SPLASH_TOTAL_DURATION
        log.info('Startup: entering splash setup (path=%s)', splash_path)
        if Path(splash_path).exists():
            from unicornviz.splash import Splash

            splash_w, splash_h, splash_viewport = self._splash_render_target()

            def _splash_bass() -> float:
                return float(audio_manager.get_audio_data().bass)

            splash = Splash(
                self._ctx,
                splash_w,
                splash_h,
                image_path=splash_path,
                duration=_SPLASH_TOTAL_DURATION,
                bass_supplier=_splash_bass,
                render_viewport=splash_viewport,
            )
            # Decide duration based on audio during splash run
            if splash.run(self._window):
                # User pressed Esc during splash — quit immediately
                splash.destroy()
                audio_manager.stop()
                sdl2.SDL_GL_DeleteContext(self._gl_context)
                sdl2.SDL_DestroyWindow(self._window)
                sdl2.SDL_Quit()
                return
            splash.destroy()

        # Store splash config for later replay via hotkey U
        self._splash_config = {
            "path": splash_path,
            "duration_audio": splash_duration_audio,
            "duration_silent": splash_duration_silent,
            "audio_manager": audio_manager,
        }

        # Mirror windows are created after splash so startup does not spend time
        # presenting black frames to mirror outputs.
        self._create_mirror_outputs()

        # midi-controllers-01: register device presets before MidiManager is constructed
        # so the preset lookup in MidiManager.__init__ picks them up.
        _mc_register_all = None
        try:
            _mc_register_all = load_dropin_symbol(
                'midi-controllers-01/controller_presets.py', 'register_all',
            )
            _mc_register_all(MidiManager, None)
        except Exception as _exc:
            log.debug('midi-controllers-01 preset registration skipped: %s', _exc)
            _mc_register_all = None

        midi_device_hint = self.cfg.get('midi', 'device', default='')
        midi_preset = self.cfg.get('midi', 'preset', default='')
        _raw_cc = self.cfg.get('midi', 'cc_map', default={}) or {}
        _raw_note = self.cfg.get('midi', 'note_map', default={}) or {}
        # TOML bare-key integers arrive as strings; convert to int.
        midi_cc_override = {int(k): v for k, v in _raw_cc.items()} if _raw_cc else None
        midi_note_override = {int(k): v for k, v in _raw_note.items()} if _raw_note else None
        midi_manager = MidiManager(
            device_hint=midi_device_hint,
            preset=midi_preset,
            cc_map_override=midi_cc_override,
            note_map_override=midi_note_override,
        )
        midi_manager.start()
        self._midi_manager = midi_manager

        effects = get_effects()
        if not effects:
            raise RuntimeError("No effects found — check unicornviz/effects/")

        for effect_cls in effects:
            if getattr(effect_cls, 'NAME', '') == 'Image Showcase' and hasattr(effect_cls, 'warm_cache'):
                image_cfg = self.cfg.get('effects', 'ImageShowcase', default={}) or {}
                if bool(image_cfg.get('preload_images', False)):
                    try:
                        if hasattr(effect_cls, 'prefetch_ready') and effect_cls.prefetch_ready(image_cfg):
                            effect_cls.warm_cache(self._ctx, image_cfg)
                            log.info('Image Showcase cache warmed (GL upload)')
                        else:
                            log.info('Image Showcase prefetch still running; skipping blocking warmup')
                    except Exception as exc:
                        log.warning('Image Showcase cache warmup failed: %s', exc)
                break

        for effect_cls in effects:
            if getattr(effect_cls, 'NAME', '') == 'ProjectM Presets' and hasattr(effect_cls, 'warm_up'):
                pm_cfg = self.cfg.get('effects', 'ProjectMEffect', default={}) or {}
                if bool(pm_cfg.get('enabled', True)):
                    try:
                        effect_cls.warm_up(self._ctx, self._width, self._height, pm_cfg)
                    except Exception as exc:
                        log.warning('ProjectM warm-up failed (non-fatal): %s', exc)
                break

        playlist = Playlist(effects, self.cfg)
        playlist.set_disabled(self._disabled_effects)
        self._playlist = playlist
        self._playlist_mode = playlist.mode
        self._playlist_index = playlist.index
        self._playlist_size = len(playlist.effects)

        overlays = Overlays(
            self._ctx,
            self._width,
            self._height,
            flash_messages=bool(self.cfg.get('overlays', 'flash_messages', default=True)),
            show_recording_indicator=bool(self.cfg.get('recording', 'show_indicator', default=True)),
            hud_auto_hide=bool(self.cfg.get('overlays', 'hud_auto_hide', default=True)),
            hud_timeout_s=float(self.cfg.get('overlays', 'hud_timeout_s', default=60.0)),
            flash_router=self.route_flash_message,
            modal_gate=self.control_room_flash_gate_active,
        )
        self._overlays = overlays

        # midi-controllers-01: register help-modal renderer now that Overlays is ready.
        if _mc_register_all is not None:
            try:
                _mc_register_all(None, overlays)
            except Exception as _exc:
                log.debug('midi-controllers-01 renderer registration failed: %s', _exc)

        overlays.set_effect_shortcuts(playlist.shortcut_effects)
        overlays.set_system_monitor_audio_provider(
            self._system_monitor_audio_snapshot
        )
        overlays.set_system_monitor_tweakables_provider(
            self._system_monitor_tweakables_snapshot
        )

        dynamic_help: list[tuple[str, str, str]] = []
        for effect_cls in effects:
            raw_entries = getattr(effect_cls, 'HELP_ENTRIES', None)
            if not isinstance(raw_entries, (list, tuple)):
                continue
            default_section = str(getattr(effect_cls, 'NAME', effect_cls.__name__))
            for item in raw_entries:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    key = str(item[0]).strip()
                    desc = str(item[1]).strip()
                    if key and desc:
                        dynamic_help.append((default_section, key, desc))
                elif isinstance(item, (list, tuple)) and len(item) >= 3:
                    section = str(item[0]).strip() or default_section
                    key = str(item[1]).strip()
                    desc = str(item[2]).strip()
                    if section and key and desc:
                        dynamic_help.append((section, key, desc))
                elif isinstance(item, dict):
                    section = str(item.get('section', default_section)).strip()
                    key = str(item.get('key', '')).strip()
                    desc = str(item.get('description', item.get('desc', item.get('action', '')))).strip()
                    if section and key and desc:
                        dynamic_help.append((section, key, desc))

        dynamic_help.extend(discover_dropin_help_entries())
        overlays.register_help_entries(dynamic_help)

        if overlays.unmapped_effects:
            log.warning(
                "Effects without direct shortcuts (beyond 30): %s",
                ", ".join(overlays.unmapped_effects),
            )
        ks_cfg = self.cfg.get('keystrokes', default={}) or {}
        keystroke_log_enabled = bool(ks_cfg.get('enabled', False)) if isinstance(ks_cfg, dict) else False
        self._keystroke_logger = None
        if keystroke_log_enabled:
            try:
                ks_cls = _load_keystroke_logger_class()
                self._keystroke_logger = ks_cls(True)
            except Exception as exc:
                log.warning('KeystrokeLogger not available (training-kit-01 absent?): %s', exc)

        hotkeys = HotkeyHandler(
            app=self,
            playlist=playlist,
            overlays=overlays,
            audio_manager=audio_manager,
        )
        hotkeys.attach_midi(midi_manager)
        self._hotkeys = hotkeys

        if not self._safe_mode:
            # Spotify controller (optional drop-in subsystem).
            spotify_cfg = self.cfg.get('spotify', default={}) or {}
            if not isinstance(spotify_cfg, dict):
                spotify_cfg = {}
            spotify_web_cfg = spotify_cfg.get('web_api', {}) if isinstance(spotify_cfg, dict) else {}
            if not isinstance(spotify_web_cfg, dict):
                spotify_web_cfg = {}

            if spotify_web_cfg:
                spotify_cfg = dict(spotify_cfg)
                spotify_cfg['web_api'] = spotify_web_cfg

            load_spotify = bool(spotify_cfg.get('enabled', False)) or bool(
                spotify_web_cfg.get('enabled', False)
            )
            if load_spotify:
                try:
                    spotify_cls = _load_spotify_controller_class()
                    self._spotify = spotify_cls(self, spotify_cfg)
                    if bool(getattr(self._spotify, 'enabled', False)):
                        self.vj_api.register_subsystem('spotify', self._spotify)
                        key_handler = getattr(self._spotify, 'handle_key', None)
                        if callable(key_handler):
                            self.vj_api.register_key_handler('spotify', key_handler)
                        log.info('SpotifyController loaded from drop-in')
                    else:
                        self._spotify = None
                        log.info('SpotifyController loaded but disabled by runtime checks')
                except Exception as exc:
                    self._spotify = None
                    log.warning('SpotifyController not available: %s', exc)

            # Local media player controller (optional drop-in).
            media_cfg = self.cfg.get('media', default={}) or {}
            if not isinstance(media_cfg, dict):
                media_cfg = {}
            if bool(media_cfg.get('enabled', False)):
                try:
                    media_cls = _load_media_controller_class()
                    self._media = media_cls(self, media_cfg)
                    if bool(getattr(self._media, 'enabled', False)):
                        self.vj_api.register_subsystem('media', self._media)
                        key_handler = getattr(self._media, 'handle_key', None)
                        if callable(key_handler):
                            self.vj_api.register_key_handler('media', key_handler)
                        log.info('MediaController loaded from drop-in')
                    else:
                        self._media = None
                except Exception as exc:
                    self._media = None
                    log.warning('MediaController not available: %s', exc)

            # Live chat overlay controller (optional drop-in).
            chat_cfg = self.cfg.get('chat', default={}) or {}
            if not isinstance(chat_cfg, dict):
                chat_cfg = {}
            if bool(chat_cfg.get('enabled', False)):
                try:
                    chat_cls = _load_chat_controller_class()
                    self._chat = chat_cls(self, chat_cfg)
                    if bool(getattr(self._chat, 'enabled', False)):
                        self.vj_api.register_subsystem('chat', self._chat)
                        key_handler = getattr(self._chat, 'handle_key', None)
                        if callable(key_handler):
                            self.vj_api.register_key_handler('chat', key_handler)
                        log.info('ChatController loaded from drop-in')
                    else:
                        self._chat = None
                except Exception as exc:
                    self._chat = None
                    log.warning('ChatController not available: %s', exc)

            # Audio output / SFX-injection controller (optional drop-in).
            audio_out_cfg = self.cfg.get('audio_out', default={}) or {}
            if not isinstance(audio_out_cfg, dict):
                audio_out_cfg = {}
            if bool(audio_out_cfg.get('enabled', True)):
                try:
                    audio_out_cls = _load_audio_out_controller_class()
                    self._audio_out = audio_out_cls(self, audio_out_cfg)
                    self.vj_api.register_subsystem('audio_out', self._audio_out)
                    key_handler = getattr(self._audio_out, 'handle_key', None)
                    if callable(key_handler):
                        self.vj_api.register_key_handler('audio_out', key_handler)
                    log.info('AudioOutController loaded from drop-in')
                except Exception as exc:
                    self._audio_out = None
                    log.warning('AudioOutController not available: %s', exc)

            # OSC control-surface bridge (optional drop-in).
            osc_cfg = self.cfg.get('osc', default={}) or {}
            if not isinstance(osc_cfg, dict):
                osc_cfg = {}
            if bool(osc_cfg.get('enabled', True)):
                try:
                    osc_cls = _load_osc_bridge_controller_class()
                    self._osc_bridge = osc_cls(self, osc_cfg)
                    self.vj_api.register_subsystem('osc', self._osc_bridge)
                    key_handler = getattr(self._osc_bridge, 'handle_key', None)
                    if callable(key_handler):
                        self.vj_api.register_key_handler('osc', key_handler)
                    log.info('OscBridgeController loaded from drop-in')
                except Exception as exc:
                    self._osc_bridge = None
                    log.warning('OscBridgeController not available: %s', exc)

            # Synced lyrics overlay (optional drop-in; LRCLIB-sourced).
            lyrics_cfg = self.cfg.get('lyrics', default={}) or {}
            if not isinstance(lyrics_cfg, dict):
                lyrics_cfg = {}
            if bool(lyrics_cfg.get('enabled', True)):
                try:
                    lyrics_cls = _load_lyrics_controller_class()
                    self._lyrics = lyrics_cls(self, lyrics_cfg)
                    self._lyrics.set_vj_api(self.vj_api)
                    self.vj_api.register_subsystem('lyrics', self._lyrics)
                    key_handler = getattr(self._lyrics, 'handle_key', None)
                    if callable(key_handler):
                        self.vj_api.register_key_handler('lyrics', key_handler)
                    log.info('LyricsController loaded from drop-in')
                except Exception as exc:
                    self._lyrics = None
                    log.warning('LyricsController not available: %s', exc)

            # Auto VJ controller (optional drop-in), Phase 2 telemetry-only.
            try:
                auto_vj_cls = _load_auto_vj_controller_class()
                auto_vj_cfg = self.cfg.get('auto_vj', default={}) or {}
                if not isinstance(auto_vj_cfg, dict):
                    auto_vj_cfg = {}
                self._auto_vj = auto_vj_cls(self, audio_manager, auto_vj_cfg)
                self.vj_api.set_status_pill(getattr(self._auto_vj, 'status_text', ''))
                self.vj_api.register_key_handler('auto_vj', self._auto_vj.handle_key)
                log.info('AutoVJController loaded from drop-in')
            except Exception as exc:
                self._auto_vj = None
                self.vj_api.set_status_pill(None)
                log.warning('AutoVJController not available: %s', exc)

            # Grand Finale controller (optional drop-in).
            try:
                gf_cls = _load_grand_finale_class()
                gf_cfg = self.cfg.get('grand_finale', default={}) or {}
                if not isinstance(gf_cfg, dict):
                    gf_cfg = {}
                self._grand_finale = gf_cls(self, gf_cfg)
                self.vj_api.register_key_handler('grand_finale', self._grand_finale.handle_key)
                log.info('GrandFinaleController loaded from drop-in')
            except Exception as exc:
                self._grand_finale = None
                log.warning('GrandFinaleController not available: %s', exc)

            # Control Room controller (optional drop-in subsystem).
            control_room_cfg = self.cfg.get('control_room', default={}) or {}
            if not isinstance(control_room_cfg, dict):
                control_room_cfg = {}
            if bool(control_room_cfg.get('enabled', False)):
                self._control_room_startup_cfg = dict(control_room_cfg)
                self._control_room_startup_frames_remaining = 8
                log.info('ControlRoomController scheduled for startup after %d audience frames', self._control_room_startup_frames_remaining)
        else:
            log.info('Safe mode enabled: skipping Spotify, Auto VJ, Grand Finale, and Control Room drop-ins')

        # Load first effect
        self._current_effect = self._instantiate(playlist.current())
        # Optional: start locked in ProjectM-only mode.
        _pm_cfg = self.cfg.get('effects', 'ProjectMEffect', default={}) or {}
        if isinstance(_pm_cfg, dict) and bool(_pm_cfg.get('only_mode', False)):
            _pm_cls = self.vj_api.find_effect('ProjectMEffect', 'ProjectM Presets')
            if _pm_cls is not None:
                if type(self._current_effect).__name__ != 'ProjectMEffect':
                    self._current_effect.destroy()
                    self._current_effect = self._instantiate(_pm_cls)
                self._effect_lock = 'ProjectM Presets'
                log.info('Startup: ProjectM-only mode locked via config')
        self._recorder = Recorder(self.cfg, self._width, self._height)
        stream_cls = _NullRTMPStreamer if self._safe_mode else _load_rtmp_streamer_class()
        stream_cfg = self.cfg.get('streaming', default={}) or {}
        if not isinstance(stream_cfg, dict):
            stream_cfg = {}
        try:
            self._streamer = stream_cls(stream_cfg, self._width, self._height)
        except Exception as exc:
            log.warning('RTMP streamer init failed: %s', exc)
            self._streamer = _NullRTMPStreamer(stream_cfg, self._width, self._height)
        if isinstance(self._streamer, _NullRTMPStreamer):
            self._streamer = None
        elif self._streamer.enabled and self._streamer.auto_start:
            self._streamer.set_vj_api(self.vj_api)
            self.vj_api.register_key_handler('streamer', self._streamer.handle_key)
            if self._streamer.start():
                log.info('RTMP streamer auto-started: %s', self._streamer.destination_label)
            else:
                log.warning('RTMP streamer auto-start failed: %s', self._streamer.last_error)
        else:
            self._streamer.set_vj_api(self.vj_api)
            self.vj_api.register_key_handler('streamer', self._streamer.handle_key)
            log.info(
                'RTMP streamer loaded (enabled=%s auto_start=%s)',
                self._streamer.enabled,
                self._streamer.auto_start,
            )

        if not self._safe_mode:
            banner_cfg = self.cfg.get('banner', default={}) or {}
            if not isinstance(banner_cfg, dict):
                banner_cfg = {}
            try:
                banner_cls = _load_banner_controller_class()
                banner = banner_cls(self, banner_cfg)
                register_runtime_capability(
                    self.vj_api,
                    banner,
                    BANNER_RUNTIME_CAPABILITY,
                )
                log.info('BannerController loaded from drop-in')
            except Exception as exc:
                log.warning('BannerController not available: %s', exc)
        self._sync_recording_overlay()
        if self._recorder.enabled and self._recorder.auto_record:
            started, _ = self.start_recording()
            if started:
                log.info('Auto-record enabled')
        self._running = True

        prev_time = time.perf_counter()
        self._session_started_at = time.monotonic()
        self._demo_timer = 0.0
        self._effect_duration = float(
            self.cfg.get('demo', 'effect_duration', default=20)
        )
        effect_duration = self._effect_duration
        self._webcam_cycle_interval = float(
            self.cfg.get('webcam', 'cycle_interval', default=0)
        ) or float(self._effect_duration)
        perf_debug_enabled = log.isEnabledFor(logging.DEBUG)
        perf_frame_counter = 0
        perf_sample_every = 120
        perf_slow_frame_ms = 25.0

        while self._running:
            if perf_debug_enabled:
                perf_frame_start = time.perf_counter()
            now = time.perf_counter()
            dt = min(now - prev_time, 0.1)  # cap at 100 ms to avoid spiral
            prev_time = now
            self._last_frame_fps = (1.0 / dt) if dt > 0.0 else 0.0
            self._last_frame_ms = dt * 1000.0
            manager_modal_active = self._projectm_manager_modal_active
            eb_active = self._effects_browser_active

            # Poll events
            event = sdl2.SDL_Event()
            while sdl2.SDL_PollEvent(event):
                if self._dispatch_claimed_window_event(event):
                    continue
                if event.type == sdl2.SDL_QUIT:
                    self.request_exit()
                elif event.type == sdl2.SDL_KEYDOWN:
                    self._update_ctrl_state(event.key.keysym.sym, True)
                    if not event.key.repeat:
                        hotkeys.handle(event.key.keysym.sym, event.key.keysym.mod)
                elif event.type == sdl2.SDL_KEYUP:
                    self._update_ctrl_state(event.key.keysym.sym, False)
                elif event.type == sdl2.SDL_WINDOWEVENT:
                    if self._is_mirror_window_id(int(event.window.windowID)):
                        if event.window.event in (
                            sdl2.SDL_WINDOWEVENT_CLOSE,
                        ):
                            log.warning('Mirror window event %d received; rebuilding mirror outputs', int(event.window.event))
                            self._create_mirror_outputs()
                        continue
                    if event.window.event == sdl2.SDL_WINDOWEVENT_RESIZED:
                        self._on_resize(
                            event.window.data1, event.window.data2
                        )
                    elif event.window.event == sdl2.SDL_WINDOWEVENT_FOCUS_LOST:
                        self._ctrl_held = False
                        self._set_cursor_visible(False)
                    elif event.window.event == sdl2.SDL_WINDOWEVENT_FOCUS_GAINED:
                        self._set_cursor_visible(self._cursor_should_be_visible())
                elif event.type == sdl2.SDL_MOUSEWHEEL:
                    dy = int(event.wheel.y)
                    if eb_active:
                        if dy != 0:
                            self._overlays.effects_browser.move_selection(-dy)
                            self.effects_browser_mark_nav()
                        continue
                    if manager_modal_active:
                        continue
                    if dy != 0 and self._postfx_controller is not None:
                        if self._ctrl_held:
                            self._postfx_controller.on_ctrl_scroll(dy)
                        else:
                            self._postfx_controller.on_scroll(dy)
                elif event.type == sdl2.SDL_MOUSEMOTION:
                    if eb_active:
                        try:
                            hit = self._overlay_mouse_coords(
                                float(event.motion.x),
                                float(event.motion.y),
                                self._primary_display_viewport(),
                            )
                            if hit is not None and self._overlays.handle_effects_browser_mouse_motion(hit[0], hit[1]):
                                self.effects_browser_mark_nav()
                        except Exception as exc:
                            log.warning('Effects browser hover handling failed: %s', exc)
                        continue
                    if manager_modal_active:
                        continue
                    overlays = getattr(self, '_overlays', None)
                    if overlays is not None and bool(getattr(overlays, 'help_visible', False)):
                        try:
                            hit = self._overlay_mouse_coords(
                                float(event.motion.x),
                                float(event.motion.y),
                                self._primary_display_viewport(),
                            )
                            if hit is not None:
                                overlays.handle_help_mouse_motion(hit[0], hit[1])
                            else:
                                overlays.handle_help_mouse_motion(-1.0, -1.0)
                        except Exception as exc:
                            log.warning('Help overlay hover handling failed: %s', exc)
                elif event.type == sdl2.SDL_MOUSEBUTTONDOWN:
                    if eb_active:
                        if event.button.button == sdl2.SDL_BUTTON_LEFT:
                            try:
                                hit = self._overlay_mouse_coords(
                                    float(event.button.x),
                                    float(event.button.y),
                                    self._primary_display_viewport(),
                                )
                                if hit is not None:
                                    result = self._overlays.handle_effects_browser_mouse_click(hit[0], hit[1])
                                    if result == 1:
                                        self.effects_browser_mark_nav()
                                    elif result == 2:
                                        self.effects_browser_commit()
                            except Exception as exc:
                                log.warning('Effects browser click handling failed: %s', exc)
                        continue
                    if manager_modal_active:
                        continue
                    if event.button.button == sdl2.SDL_BUTTON_LEFT:
                        overlays = getattr(self, '_overlays', None)
                        if overlays is not None and bool(getattr(overlays, 'help_visible', False)):
                            try:
                                hit = self._overlay_mouse_coords(
                                    float(event.button.x),
                                    float(event.button.y),
                                    self._primary_display_viewport(),
                                )
                                if hit is not None and bool(overlays.handle_help_mouse_click(hit[0], hit[1])):
                                    pop_action = getattr(overlays, 'pop_help_icon_action', None)
                                    action = pop_action() if callable(pop_action) else None
                                    if isinstance(action, dict):
                                        msg = self.handle_help_icon_action(action)
                                        if msg:
                                            overlays.flash_message(msg, 1.6)
                                    continue
                            except Exception as exc:
                                log.warning('Help overlay mouse handling failed: %s', exc)
                    if event.button.button == sdl2.SDL_BUTTON_MIDDLE:
                        if self._postfx_controller is not None:
                            if (self._postfx_controller.is_hue_active
                                    or self._postfx_controller.is_rotation_active):
                                self._postfx_controller.clear_scroll_fx()
                                self._overlays.flash_message('Scroll FX reset', 1.0)
                            else:
                                msg = self.toggle_auto_vj()
                                self._overlays.flash_message(msg, 2.0)
                        else:
                            msg = self.toggle_auto_vj()
                            self._overlays.flash_message(msg, 2.0)
                elif event.type == sdl2.SDL_DISPLAYEVENT:
                    if event.display.event in (
                        sdl2.SDL_DISPLAYEVENT_CONNECTED,
                        sdl2.SDL_DISPLAYEVENT_DISCONNECTED,
                    ):
                        log.info('SDL display topology change detected; rebuilding multi-head outputs')
                        self._rebuild_multihead_outputs()
            self._set_cursor_visible(self._cursor_should_be_visible())
            if perf_debug_enabled:
                perf_after_events = time.perf_counter()

            if self._midi_manager is not None:
                self._midi_manager.maintenance_update()
            hotkeys.process_pending_midi()
            if perf_debug_enabled:
                perf_after_midi = time.perf_counter()

            # Debounced live preview while the effects browser is open.
            self.tick_effects_browser_preview()

            # Auto-playlist advance (suppressed while locked to one effect)
            if (not manager_modal_active and not eb_active and not self._paused
                    and self._next_effect is None and self._auto_advance
                    and self._effect_lock is None):
                allow_advance = True
                # Duck-typed: ANSI-style effects gate auto-advance until their
                # content has scrolled to the bottom (no core import of the
                # effect class, so it can live in a drop-in pack).
                _reached = getattr(self._current_effect, 'reached_bottom', None)
                if _reached is not None:
                    allow_advance = bool(_reached)

                self._demo_timer += dt
                if self._demo_timer >= self._effect_duration and allow_advance:
                    self._demo_timer = 0.0
                    next_cls = playlist.advance()
                    log.info("Auto-advance → %s", next_cls.NAME)
                    self._switch_effect(next_cls)
            if perf_debug_enabled:
                perf_after_auto_advance = time.perf_counter()

            # Update audio
            self._audio = audio_manager.get_audio_data()
            self._audio_raw = audio_manager.get_audio_data_raw()
            if perf_debug_enabled:
                perf_after_audio = time.perf_counter()

            if self._audio_out is not None:
                try:
                    self._audio_out.update(dt, self._audio or AudioData())
                except Exception as exc:
                    log.warning('AudioOutController update failed: %s', exc)

            if self._beat_flash is not None:
                try:
                    self._beat_flash.update(dt, self._audio or AudioData())
                except Exception as exc:
                    log.warning('BeatFlashController update failed: %s', exc)

            if self._osc_bridge is not None:
                try:
                    self._osc_bridge.update(dt, self._audio or AudioData())
                except Exception as exc:
                    log.warning('OscBridgeController update failed: %s', exc)

            if self._lyrics is not None:
                try:
                    self._lyrics.update(dt, self._audio or AudioData())
                except Exception as exc:
                    log.warning('LyricsController update failed: %s', exc)

            if self._auto_vj is not None and not manager_modal_active:
                try:
                    self._auto_vj.update(dt, self._audio_raw or self._audio)
                    self.vj_api.set_status_pill(getattr(self._auto_vj, 'status_text', ''))
                except Exception as exc:
                    now = time.monotonic()
                    err_key = f'{type(exc).__name__}:{exc}'
                    repeat = (
                        err_key == self._last_auto_vj_error_key
                        and (now - self._last_auto_vj_error_t) < 2.0
                    )
                    if repeat:
                        log.debug('AutoVJController update failed (repeat): %s', exc)
                    else:
                        mode = getattr(self._auto_vj, '_mode', '?')
                        profile = getattr(self._auto_vj, '_profile', '?')
                        effect_name = '?'
                        try:
                            effect_name = str(self.vj_api.state().effect_name)
                        except Exception:
                            pass
                        log.exception(
                            'AutoVJController update failed: %s [mode=%s profile=%s effect=%s]',
                            exc, mode, profile, effect_name,
                        )
                    self._last_auto_vj_error_key = err_key
                    self._last_auto_vj_error_t = now
                    try:
                        rec = getattr(self._auto_vj, 'record_runtime_error', None)
                        if callable(rec):
                            rec(exc)
                    except Exception:
                        pass
                    self.vj_api.set_status_pill('AUTO VJ  ERROR')
            if perf_debug_enabled:
                perf_after_auto_vj = time.perf_counter()

            if self._grand_finale is not None and not manager_modal_active:
                try:
                    self._grand_finale.update(dt, self._audio)
                except Exception as exc:
                    log.warning('GrandFinaleController update failed: %s', exc)
            if perf_debug_enabled:
                perf_after_grand_finale = time.perf_counter()

            if not manager_modal_active:
                for name, subsystem in list(self._subsystems.items()):
                    updater = getattr(subsystem, 'update', None)
                    if not callable(updater):
                        continue
                    try:
                        updater(dt, self._audio)
                    except Exception as exc:
                        log.warning('%s subsystem update failed: %s', name, exc)
            if perf_debug_enabled:
                perf_after_subsystem_update = time.perf_counter()

            # Update effects
            if not self._paused:
                allow_current_effect_update = True
                allow_next_effect_update = True
                if manager_modal_active and self._next_effect is None:
                    allow_current_effect_update = (
                        self._current_effect is not None
                        and type(self._current_effect).__name__ == 'ProjectMEffect'
                    )
                    allow_next_effect_update = False
                if self._current_effect and allow_current_effect_update:
                    auto_vj_profile = ''
                    if self._auto_vj is not None:
                        auto_vj_profile = str(getattr(self._auto_vj, '_profile', '')).lower()
                    is_raver_mode = bool(self._auto_vj is not None and auto_vj_profile == 'raver')
                    setattr(self._current_effect, '_raver_mode_active', is_raver_mode)
                    setattr(self._current_effect, '_auto_vj_profile', auto_vj_profile)
                    audio_cur = self._audio_for_effect(
                        self._audio,
                        self._current_effect,
                        self._audio_scratch_current,
                    )
                    self._current_effect.update(dt, audio_cur)
                if self._next_effect and allow_next_effect_update:
                    auto_vj_profile = ''
                    if self._auto_vj is not None:
                        auto_vj_profile = str(getattr(self._auto_vj, '_profile', '')).lower()
                    is_raver_mode = bool(self._auto_vj is not None and auto_vj_profile == 'raver')
                    setattr(self._next_effect, '_raver_mode_active', is_raver_mode)
                    setattr(self._next_effect, '_auto_vj_profile', auto_vj_profile)
                    audio_next = self._audio_for_effect(
                        self._audio,
                        self._next_effect,
                        self._audio_scratch_next,
                    )
                    self._next_effect.update(dt, audio_next)
            if perf_debug_enabled:
                perf_after_effect_update = time.perf_counter()

            # Keep persistent name overlay in sync with the active effect.
            # Duck-typed: an effect exposing `current_title` (ANSI art viewer)
            # shows that; all other effects show NAME.
            if self._current_effect is not None:
                _art_title = getattr(self._current_effect, 'current_title', None)
                if _art_title is not None:
                    overlays._name_text = _art_title
                else:
                    current_label = getattr(self._current_effect, 'current_label', '')
                    if isinstance(current_label, str) and current_label:
                        overlays._name_text = _smart_trim_label(f"{self._current_effect.NAME} - {current_label}")
                    else:
                        overlays._name_text = self._current_effect.NAME

            # Feed modern TAB HUD with current runtime status.
            # ---------------------------------------------------------------
            # Gating strategy: the full HUD dict (50+ fields, Spotify string
            # formatting, session-clock call) is expensive to build every frame.
            # We split into three tiers:
            #   A) Always: trivial fps + effect name, already set above.
            #   B) Always: Spotify snapshot for banner fields + set_overlay_banner.
            #   C) HUD-visible only: all string formatting + full set_hud_state.
            # ---------------------------------------------------------------
            fps_now = (1.0 / dt) if dt > 0.0 else 0.0

            # --- Tier B: now-playing snapshot (always, needed for banner) ---
            # Source priority: media-01 when actively playing, else spotify-01.
            # Both expose the same snapshot() dict shape so no format changes below.
            _active_np_source = None
            if self._media is not None:
                _media_snap_fn = getattr(self._media, 'snapshot', None)
                if callable(_media_snap_fn):
                    try:
                        _ms = _media_snap_fn()
                        if isinstance(_ms, dict) and bool(_ms.get('is_playing', False)):
                            _active_np_source = self._media
                    except Exception:
                        pass
            if _active_np_source is None and self._spotify is not None:
                _active_np_source = self._spotify

            spotify_visible = 'YES' if _active_np_source is not None else 'NO'
            spotify_status = 'OFF'
            spotify_change_counter = 0
            spotify_length = '--:--'
            banner_enabled = False
            banner_hold_s = 10.0
            banner_track = '-'
            banner_artist = '-'
            banner_album = '-'
            banner_prev_artist = '-'
            banner_prev_title = '-'
            _spotify_snap: dict | None = None
            if _active_np_source is not None:
                snap_fn = getattr(_active_np_source, 'snapshot', None)
                if callable(snap_fn):
                    try:
                        _spotify_snap = snap_fn()
                    except Exception:
                        _spotify_snap = None
                    if isinstance(_spotify_snap, dict):
                        available = bool(_spotify_snap.get('available', False))
                        playing = bool(_spotify_snap.get('is_playing', False))
                        raw_status = str(_spotify_snap.get('status', '') or '').strip().upper()
                        if available and raw_status:
                            spotify_status = raw_status
                        elif available:
                            spotify_status = 'PLAYING' if playing else 'PAUSED'
                        banner_track = str(_spotify_snap.get('title', '') or '').strip() or '-'
                        banner_artist = str(_spotify_snap.get('artist', '') or '').strip() or '-'
                        banner_album = str(_spotify_snap.get('album', '') or '').strip() or '-'
                        banner_prev_artist = str(_spotify_snap.get('previous_artist', '') or '').strip() or '-'
                        banner_prev_title = str(_spotify_snap.get('previous_title', '') or '').strip() or '-'
                        spotify_change_counter = int(_spotify_snap.get('banner_change_counter', 0) or 0)
                        banner_enabled = bool(_spotify_snap.get('now_playing_banner_enabled', False))
                        banner_hold_s = max(1.0, float(_spotify_snap.get('now_playing_banner_hold_s', 10.0) or 10.0))
                        dur_b = max(0.0, float(_spotify_snap.get('duration_s', 0.0) or 0.0))
                        total_b = max(0, int(dur_b))
                        mm_b, ss_b = divmod(total_b, 60)
                        hh_b, mm_b = divmod(mm_b, 60)
                        spotify_length = f'{hh_b:02d}:{mm_b:02d}:{ss_b:02d}' if hh_b > 0 else f'{mm_b:02d}:{ss_b:02d}'
            current_banner = 'NOW PLAYING: {artist} :: {album} :: {track} :: {length}'.format(
                artist=banner_artist,
                album=banner_album,
                track=banner_track,
                length=spotify_length,
            )
            previous_banner = 'Previous: {artist} :: {track}'.format(
                artist=banner_prev_artist,
                track=banner_prev_title,
            )
            overlays.set_overlay_banner(
                banner_enabled and spotify_visible == 'YES' and spotify_status == 'PLAYING',
                current_banner,
                previous_banner,
                banner_hold_s,
                spotify_change_counter,
            )

            # Playlist sync (cheap, always)
            self._playlist_mode = playlist.mode
            self._playlist_index = playlist.index
            self._playlist_size = len(playlist.effects)
            audio_hud_fields = self._hud_audio_state_fields()

            # --- Tier C: Full HUD build (only while TAB HUD is visible) ---
            if overlays._show_name:
                transition_name = self._transition_kind if self._next_effect is not None else 'none'
                transition_pct = f"{int(max(0.0, min(1.0, self._transition_t)) * 100)}%"
                audio_src = audio_manager.get_source_label() if audio_manager is not None else 'n/a'
                if audio_manager is not None:
                    _rv = audio_manager.get_reactivity()
                    react_str = f"{_rv:.1f}{' *' if self._reactivity_randomized else ''}"
                else:
                    react_str = 'n/a'
                if self._current_effect is not None and 'speed' in self._current_effect.parameters:
                    _sv = self._current_effect.parameters['speed']
                    speed_str = f"{_sv:.2f}{' *' if self._speed_randomized else ''}"
                else:
                    speed_str = f"N/A{' *' if self._speed_randomized else ''}"
                if self._current_effect is not None and 'zoom' in self._current_effect.parameters:
                    _zv = self._current_effect.parameters['zoom']
                    zoom_str = f"{_zv:.2f}{' *' if self._zoom_randomized else ''}"
                else:
                    zoom_str = f"N/A{' *' if self._zoom_randomized else ''}"
                scale_str = f'{self._render_scale:.2f}'
                rec_state = 'ON' if (self._recorder is not None and self._recorder.is_recording) else 'OFF'
                stream_state = 'LIVE' if (self._streamer is not None and self._streamer.is_streaming) else 'OFF'
                stream_provider = str(getattr(self._streamer, 'provider', '-')).upper() if self._streamer is not None else '-'
                advance_elapsed = max(0.0, self._demo_timer)
                advance_total = max(0.1, self._effect_duration)
                advance_time = f"{advance_elapsed:.1f}/{advance_total:.1f}s"

                # Spotify HUD-only fields (clipped strings, progress, auth)
                spotify_auth_visible = 'NO'
                spotify_auth_status = 'OFF'
                spotify_track = '-'
                spotify_artist = '-'
                spotify_album = '-'
                spotify_prev_artist = '-'
                spotify_prev_title = '-'
                spotify_progress = '--:--/--:-- 0%'
                if isinstance(_spotify_snap, dict):
                    def _clip(text: str, limit: int) -> str:
                        txt = str(text).strip()
                        if not txt:
                            return '-'
                        return txt if len(txt) <= limit else txt[: max(1, limit - 3)].rstrip() + '...'

                    def _fmt_secs(seconds: float) -> str:
                        total = max(0, int(seconds))
                        mm, ss = divmod(total, 60)
                        hh, mm = divmod(mm, 60)
                        return f'{hh:02d}:{mm:02d}:{ss:02d}' if hh > 0 else f'{mm:02d}:{ss:02d}'

                    spotify_track = _clip(str(_spotify_snap.get('title', '') or ''), 24)
                    spotify_artist = _clip(str(_spotify_snap.get('artist', '') or ''), 24)
                    spotify_album = _clip(str(_spotify_snap.get('album', '') or ''), 24)
                    spotify_prev_artist = _clip(str(_spotify_snap.get('previous_artist', '') or ''), 24)
                    spotify_prev_title = _clip(str(_spotify_snap.get('previous_title', '') or ''), 24)
                    pos = max(0.0, float(_spotify_snap.get('position_s', 0.0) or 0.0))
                    dur = max(0.0, float(_spotify_snap.get('duration_s', 0.0) or 0.0))
                    pct = int(round(min(100.0, (pos / dur) * 100.0))) if dur > 0.0 else 0
                    spotify_progress = f'{_fmt_secs(pos)}/{_fmt_secs(dur)} {pct}%'
                    spotify_auth_visible = 'YES' if bool(_spotify_snap.get('web_api_enabled', False)) else 'NO'
                    auth_status = str(_spotify_snap.get('auth_status', '') or '').strip()
                    display_name = str(_spotify_snap.get('display_name', '') or '').strip()
                    if bool(_spotify_snap.get('auth_ready', False)):
                        label = display_name if display_name else 'authenticated'
                        spotify_auth_status = f'{label} active'
                    elif auth_status in ('needs_auth', 'not_configured', ''):
                        spotify_auth_status = 'Ctrl+Alt+S to auth'
                    else:
                        spotify_auth_status = auth_status.replace('_', ' ')

                slot_label = 'PRESET IDX'
                preset_slot = '-/-'
                variant_label = 'VARIANT'
                variant_slot = '-/-'
                if self._current_effect is not None:
                    label_text = getattr(self._current_effect, 'current_position_label', '')
                    if isinstance(label_text, str) and label_text.strip():
                        slot_label = label_text.strip().upper()
                    slot_text = getattr(self._current_effect, 'current_position_text', '')
                    if isinstance(slot_text, str) and slot_text:
                        preset_slot = slot_text
                    else:
                        cur_idx = getattr(self._current_effect, 'current_index', None)
                        cur_total = getattr(self._current_effect, 'current_total', None)
                        if isinstance(cur_idx, int) and isinstance(cur_total, int) and cur_total > 0:
                            preset_slot = f"{cur_idx + 1}/{cur_total}"
                    vlabel_text = getattr(self._current_effect, 'current_variant_label', '')
                    if isinstance(vlabel_text, str) and vlabel_text.strip():
                        variant_label = vlabel_text.strip().upper()
                    vslot_text = getattr(self._current_effect, 'current_variant_text', '')
                    if isinstance(vslot_text, str) and vslot_text.strip():
                        variant_slot = vslot_text.strip()

                auto_vj_badge = ''
                if self._auto_vj is not None:
                    badge_getter = getattr(self._auto_vj, 'training_badge', None)
                    if callable(badge_getter):
                        auto_vj_badge = str(badge_getter() or '')

                overlays.set_hud_state({
                    'title': 'Unicorn Viz HUD',
                    'session_time': self.vj_api.format_session_clock(),
                    'effect': overlays._name_text,
                    'previous_effect': self._previous_effect_name,
                    'next_effect': self._next_effect.NAME if self._next_effect is not None else '-',
                    'transition': transition_name,
                    'transition_t': transition_pct,
                    'fps': f"{fps_now:.1f}",
                    'frame_ms': f"{(dt * 1000.0):.2f}",
                'resolution': f"{self._width}x{self._height}",
                'render_scale': scale_str,
                'playlist': f"{playlist.mode.upper()} {playlist.index + 1}/{len(playlist.effects)}",
                'paused': 'YES' if self._paused else 'NO',
                'fullscreen': 'YES' if self._fullscreen else 'NO',
                'auto_advance': 'ON' if self._auto_advance else 'OFF',
                'advance_time': advance_time,
                'reactivity': react_str,
                'speed': speed_str,
                'zoom': zoom_str,
                'audio_source': audio_src,
                'audio_profile': (
                    self._audio_manager.get_profile_hud_label()
                    if self._audio_manager is not None
                    else '-'
                ),
                'audio_profile_name': (
                    self._audio_manager.get_profile().name
                    if self._audio_manager is not None
                    else '-'
                ),
                'audio_profile_reco': (
                    getattr(self._auto_vj, 'profile_recommendation_hud', '-')
                    if self._auto_vj is not None
                    else '-'
                ),
                'auto_vj_label': 'AUTO VJ',
                'auto_vj_training_badge': auto_vj_badge,
                'auto_vj_mood': (
                    getattr(self._auto_vj, 'hud_mood_label', '-')
                    if self._auto_vj is not None
                    else '-'
                ),
                'auto_vj_scene': (
                    getattr(self._auto_vj, 'hud_scene_label', '-')
                    if self._auto_vj is not None
                    else '-'
                ),
                'auto_vj_bpm': (
                    getattr(self._auto_vj, 'hud_bpm_label', '--')
                    if self._auto_vj is not None
                    else '--'
                ),
                'auto_vj_bpm_conf': (
                    getattr(self._auto_vj, 'hud_bpm_confidence_label', '--')
                    if self._auto_vj is not None
                    else '--'
                ),
                'auto_vj_action_in': (
                    getattr(self._auto_vj, 'hud_action_in_label', '--')
                    if self._auto_vj is not None
                    else '--'
                ),
                'preset_slot_label': slot_label,
                'preset_slot': preset_slot,
                'variant_slot_label': variant_label,
                'variant_slot': variant_slot,
                'recording': rec_state,
                'streaming': stream_state,
                'streaming_provider': stream_provider,
                'spotify_visible': spotify_visible,
                'spotify_auth_visible': spotify_auth_visible,
                'spotify_auth_status': spotify_auth_status,
                'spotify_status': spotify_status,
                'spotify_track': spotify_track,
                'spotify_artist': spotify_artist,
                'spotify_album': spotify_album,
                'spotify_length': spotify_length,
                'spotify_progress': spotify_progress,
                'postfx': self._postfx_controller.active_name if self._postfx_controller is not None else 'N/A',
                'postfx_debug': (
                    self._postfx_controller.debug_summary
                    if self._postfx_controller is not None else 'N/A'
                ),
                'compose_debug': str(getattr(self, '_compose_debug', '-')),
                **audio_hud_fields,
                'audio_rms': (
                    f"{self._audio_manager.get_raw_input_rms():.4f}"
                    if self._audio_manager is not None else '0.0000'
                ),
                'display_mode': self._display_mode,
                'display_index': str(self._display_index),
                'invert': 'ON' if self._invert_colors else 'OFF',
                'vj_status': self._vj_status_pill,
                'audio_xruns': (
                    str(self._audio_manager.get_xrun_count())
                    if self._audio_manager is not None else '0'
                ),
            })
            else:
                # HUD hidden — minimal update: keep fps, effect name, and live
                # audio meters current so the display is correct when re-opened.
                audio_hud = self._audio_raw if self._audio_raw is not None else self._audio
                overlays.set_hud_state({
                    'fps': f"{fps_now:.1f}",
                    'frame_ms': f"{(dt * 1000.0):.2f}",
                    'effect': overlays._name_text,
                    'bass': f"{audio_hud.bass:.2f}" if audio_hud is not None else '0.00',
                    'mid': f"{audio_hud.mid:.2f}" if audio_hud is not None else '0.00',
                    'treble': f"{audio_hud.treble:.2f}" if audio_hud is not None else '0.00',
                    'auto_vj_label': 'AUTO VJ',
                    'auto_vj_training_badge': (
                        self._auto_vj.training_badge() if self._auto_vj is not None else ''
                    ),
                })
            if perf_debug_enabled:
                perf_after_hud = time.perf_counter()

            _wf_audio = self._audio_raw if self._audio_raw is not None else self._audio
            overlays.set_audio_waveform(
                _wf_audio.waveform if _wf_audio is not None else None
            )

            # Render
            self._render(dt)
            mirror_mode_active = (
                self._is_mirror_mode(self._display_mode) and bool(self._mirror_rects)
            )
            candy_mode_active = (
                self._candy_frame is not None and bool(self._candy_frame.active)
            )
            if self._webcam_system is not None:
                audio = self._audio or AudioData()
                self._webcam_system.render(dt, audio.bass, audio.treble)
            if self._dancing_unicorn is not None:
                audio = self._audio or AudioData()
                self._dancing_unicorn.update(
                    dt,
                    float(audio.bass), float(audio.mid),
                    float(audio.treble), float(audio.beat),
                )
                if mirror_mode_active:
                    self._fbo_a.use()
                    self._ctx.viewport = (0, 0, self._render_width, self._render_height)
                    self._dancing_unicorn.render(
                        self._ctx, self._render_width, self._render_height,
                    )
                else:
                    if candy_mode_active:
                        self._fbo_a.use()
                        self._ctx.viewport = (0, 0, self._render_width, self._render_height)
                        self._dancing_unicorn.render(
                            self._ctx, self._render_width, self._render_height,
                        )
                    else:
                        self._ctx.screen.use()
                        self._ctx.viewport = (0, 0, self._width, self._height)
                        self._dancing_unicorn.render(self._ctx, self._width, self._height)
            if self._rainbow_nova is not None:
                self._rainbow_nova.update(dt)
                if self._rainbow_nova.is_active:
                    if mirror_mode_active:
                        # Composite nova from fbo_a into fbo_b, then copy back
                        # so final mirror tile-blit includes the effect.
                        self._fbo_b.use()
                        self._ctx.viewport = (0, 0, self._render_width, self._render_height)
                        self._rainbow_nova.render(self._fbo_a.color_attachments[0])
                        self._blit_fbo_b_to_fbo_a(self._render_width, self._render_height, clear=False)
                    else:
                        if candy_mode_active:
                            self._fbo_b.use()
                            self._ctx.viewport = (0, 0, self._render_width, self._render_height)
                            self._rainbow_nova.render(self._fbo_a.color_attachments[0])
                            self._blit_fbo_b_to_fbo_a(self._render_width, self._render_height, clear=False)
                        else:
                            self._ctx.screen.use()
                            self._ctx.viewport = (0, 0, self._width, self._height)
                            self._rainbow_nova.render(self._fbo_a.color_attachments[0])
            if self._grand_finale is not None and self._grand_finale.overlay_active:
                if mirror_mode_active:
                    self._fbo_b.use()
                    self._ctx.viewport = (0, 0, self._render_width, self._render_height)
                    self._grand_finale.render_overlay(
                        self._fbo_a.color_attachments[0],
                        self._fbo_b,
                        self._render_width, self._render_height,
                    )
                    self._blit_fbo_b_to_fbo_a(self._render_width, self._render_height, clear=False)
                else:
                    if candy_mode_active:
                        self._fbo_b.use()
                        self._ctx.viewport = (0, 0, self._render_width, self._render_height)
                        self._grand_finale.render_overlay(
                            self._fbo_a.color_attachments[0],
                            self._fbo_b,
                            self._render_width, self._render_height,
                        )
                        self._blit_fbo_b_to_fbo_a(self._render_width, self._render_height, clear=False)
                    else:
                        self._ctx.screen.use()
                        self._ctx.viewport = (0, 0, self._width, self._height)
                        self._grand_finale.render_overlay(
                            self._fbo_a.color_attachments[0],
                            None,
                            self._width, self._height,
                        )
            if self._candy_frame is not None:
                fill_needed = (
                    self._effect_requests_frame_scaling(self._current_effect)
                    or self._effect_requests_frame_scaling(self._next_effect)
                )
                set_needed = getattr(self._candy_frame, 'set_outer_fill_needed', None)
                if callable(set_needed):
                    set_needed(fill_needed)
                audio = self._audio or AudioData()
                self._candy_frame.update(
                    dt,
                    float(audio.bass),
                    float(audio.mid),
                    float(audio.treble),
                    float(audio.beat),
                )
                if self._candy_frame.active:
                    if mirror_mode_active:
                        self._fbo_b.use()
                        self._ctx.viewport = (0, 0, self._render_width, self._render_height)
                        self._candy_frame.render(self._fbo_a.color_attachments[0])
                        self._blit_fbo_b_to_fbo_a(self._render_width, self._render_height, clear=False)
                    else:
                        self._ctx.screen.use()
                        self._ctx.viewport = (0, 0, self._width, self._height)
                        self._candy_frame.render(self._fbo_a.color_attachments[0])
            # Fire DJ celebration overlay — on top of all other overlays, below HUD.
            _auto_vj = getattr(self, '_auto_vj', None)
            if _auto_vj is not None:
                _cel_render = getattr(_auto_vj, 'render_celebration_overlay', None)
                if callable(_cel_render):
                    self._ctx.screen.use()
                    self._ctx.viewport = (0, 0, self._width, self._height)
                    _cel_render(self._width, self._height)
            self._sync_recording_overlay()
            # Render the effects-browser live preview into its offscreen FBO
            # (restores the default framebuffer) before the overlay pass draws it.
            self.render_effects_browser_thumbnail(dt)
            primary_overlay_view = self._primary_display_viewport()
            if mirror_mode_active:
                # Compose stage finished into _fbo_a; tile-blit first.
                self._present_mirror_tiled(self._fbo_a.color_attachments[0])
            if primary_overlay_view is not None:
                vx, vy, vw, vh = primary_overlay_view
                overlays.resize(vw, vh)
                self._ctx.screen.use()
                self._ctx.viewport = (vx, vy, vw, vh)
                self._normalize_gl_render_state()
                self._render_subsystem_overlays(dt, vw, vh)
                overlays.render(dt, include_recording_indicator=False)
            else:
                overlays.resize(self._width, self._height)
                self._normalize_gl_render_state()
                self._render_subsystem_overlays(dt, self._width, self._height)
                overlays.render(dt, include_recording_indicator=False)
            if self._recorder is not None and self._recorder.is_recording:
                self._capture_recording_frame()

            stream_frame: bytes | None = None
            need_frame_for_streaming = (
                self._streamer is not None and self._streamer.is_streaming
            )
            need_frame_for_subsystems = self._subsystems_need_frame_capture()
            # Throttle the subsystem preview readback so it fires at the
            # subsystem's own render rate (≤15 fps) rather than the full
            # audience output frame rate.  Without this, a single glReadPixels
            # call on each 1080p+ frame stalls the GPU pipeline for 5–20 ms,
            # which is the primary cause of the audience-output freeze observed
            # while the control-room operator window is open.
            # Streaming readback is not throttled; it must produce one frame
            # per rendered frame to keep the RTMP muxer in sync.
            subsystem_capture_due = False
            if need_frame_for_subsystems:
                _now = time.monotonic()
                if _now - self._last_subsystem_frame_capture_time >= 0.1:
                    subsystem_capture_due = True
                    self._last_subsystem_frame_capture_time = _now
            if need_frame_for_streaming or subsystem_capture_due:
                try:
                    stream_frame = self._read_streaming_frame()
                except Exception as exc:
                    log.error('Streaming frame readback failed: %s', exc)
                    stream_frame = None
            if subsystem_capture_due:
                self._update_frame_capture_snapshot(stream_frame)
            elif not need_frame_for_subsystems:
                self._update_frame_capture_snapshot(None)
            if need_frame_for_streaming and stream_frame is not None:
                if not self._streamer.write_frame(stream_frame):
                    log.warning('RTMP streamer write failed: %s', self._streamer.last_error)
            if primary_overlay_view is not None:
                vx, vy, vw, vh = primary_overlay_view
                overlays.resize(vw, vh)
                self._ctx.screen.use()
                self._ctx.viewport = (vx, vy, vw, vh)
                self._normalize_gl_render_state()
                overlays.render_live_recording_indicator()
            else:
                overlays.resize(self._width, self._height)
                self._normalize_gl_render_state()
                overlays.render_live_recording_indicator()
            if perf_debug_enabled:
                perf_before_swap = time.perf_counter()

            sdl2.SDL_GL_SwapWindow(self._window)
            if perf_debug_enabled:
                perf_after_swap = time.perf_counter()

            for name, subsystem in list(self._subsystems.items()):
                presenter = getattr(subsystem, 'present', None)
                if not callable(presenter):
                    continue
                try:
                    presenter()
                except Exception as exc:
                    log.warning('%s subsystem present failed: %s', name, exc)
            if perf_debug_enabled:
                perf_after_subsystem_present = time.perf_counter()
                perf_frame_counter += 1
                frame_total_ms = (perf_after_subsystem_present - perf_frame_start) * 1000.0
                if (
                    frame_total_ms >= perf_slow_frame_ms
                    or (perf_frame_counter % perf_sample_every) == 0
                ):
                    log.debug(
                        (
                            'Perf frame: total=%.2fms events=%.2fms midi=%.2fms '
                            'auto=%.2fms audio=%.2fms auto_vj=%.2fms finale=%.2fms '
                            'subsys_upd=%.2fms effects=%.2fms hud=%.2fms draw=%.2fms '
                            'swap=%.2fms subsys_present=%.2fms fps=%.1f mode=%s'
                        ),
                        frame_total_ms,
                        (perf_after_events - perf_frame_start) * 1000.0,
                        (perf_after_midi - perf_after_events) * 1000.0,
                        (perf_after_auto_advance - perf_after_midi) * 1000.0,
                        (perf_after_audio - perf_after_auto_advance) * 1000.0,
                        (perf_after_auto_vj - perf_after_audio) * 1000.0,
                        (perf_after_grand_finale - perf_after_auto_vj) * 1000.0,
                        (perf_after_subsystem_update - perf_after_grand_finale) * 1000.0,
                        (perf_after_effect_update - perf_after_subsystem_update) * 1000.0,
                        (perf_after_hud - perf_after_effect_update) * 1000.0,
                        (perf_before_swap - perf_after_hud) * 1000.0,
                        (perf_after_swap - perf_before_swap) * 1000.0,
                        (perf_after_subsystem_present - perf_after_swap) * 1000.0,
                        (1.0 / dt) if dt > 0.0 else 0.0,
                        self._display_mode,
                    )

            if self._control_room_startup_cfg is not None:
                if self._control_room_startup_frames_remaining > 0:
                    self._control_room_startup_frames_remaining -= 1
                else:
                    _cfg = self._control_room_startup_cfg
                    self._control_room_startup_cfg = None
                    _active, _msg = self._create_control_room(_cfg)

        # Cleanup
        if self._recorder:
            self._recorder.stop()
        if self._streamer is not None:
            self._streamer.stop()
            self._streamer = None
        if self._auto_vj is not None:
            try:
                self._auto_vj.shutdown()
            except Exception as exc:
                log.warning('AutoVJController shutdown failed: %s', exc)
            self._auto_vj = None
        if self._grand_finale is not None:
            try:
                self._grand_finale.shutdown()
            except Exception as exc:
                log.warning('GrandFinaleController shutdown failed: %s', exc)
            self._grand_finale = None
        for name, subsystem in list(self._subsystems.items()):
            shutdown = getattr(subsystem, 'shutdown', None)
            if not callable(shutdown):
                continue
            try:
                shutdown()
            except Exception as exc:
                log.warning('%s subsystem shutdown failed: %s', name, exc)
        self._subsystems.clear()
        self._claimed_window_handlers.clear()
        self._hotkeys = None
        self._control_room = None
        if self._keystroke_logger is not None:
            self._keystroke_logger.close()
            self._keystroke_logger = None
        audio_manager.stop()
        midi_manager.stop()
        if self._webcam_system is not None:
            self._persist_webcam_runtime_state()
            self._webcam_system.destroy()
            self._webcam_system = None
        if self._candy_frame is not None:
            self._candy_frame.destroy()
            self._candy_frame = None
        if self._postfx_controller is not None:
            self._postfx_controller.destroy()
            self._postfx_controller = None
        if self._color_grade is not None:
            self._color_grade.destroy()
            self._color_grade = None
        if self._beat_flash is not None:
            self._beat_flash.destroy()
            self._beat_flash = None
        if self._current_effect:
            self._current_effect.destroy()
        if self._next_effect:
            self._next_effect.destroy()
        overlays.destroy()
        if self._invert_vao:
            self._invert_vao.release()
        if self._invert_vbo:
            self._invert_vbo.release()
        if self._invert_prog:
            self._invert_prog.release()
        if self._present_vao:
            self._present_vao.release()
        if self._present_vbo:
            self._present_vbo.release()
        if self._present_prog:
            self._present_prog.release()
        if self._burst_vao:
            self._burst_vao.release()
        if self._burst_vbo:
            self._burst_vbo.release()
        if self._burst_prog:
            self._burst_prog.release()
        self._destroy_mirror_outputs()
        self._release_readback_pbos()
        self._runtime_state.save()
        sdl2.SDL_GL_DeleteContext(self._gl_context)
        sdl2.SDL_DestroyWindow(self._window)
        sdl2.SDL_Quit()

    def _effect_viewport_for_target(
        self,
        target_width: int,
        target_height: int,
        effect: BaseEffect | None,
    ) -> tuple[int, int, int, int]:
        """Return viewport for rendering an effect into a target.

        When Candy Frame is active, render inside the frame content area.
        """
        if target_width <= 0 or target_height <= 0:
            return (0, 0, max(1, target_width), max(1, target_height))

        if self._candy_frame is None or not bool(self._candy_frame.active):
            return (0, 0, target_width, target_height)
        if not self._effect_requests_frame_scaling(effect):
            return (0, 0, target_width, target_height)

        method = getattr(self._candy_frame, 'content_viewport', None)
        if not callable(method):
            return (0, 0, target_width, target_height)

        try:
            x, y, w, h = method(target_width, target_height)
            x = int(max(0, x))
            y = int(max(0, y))
            w = int(max(1, min(target_width - x, w)))
            h = int(max(1, min(target_height - y, h)))
            return (x, y, w, h)
        except Exception as exc:
            log.debug('Candy Frame viewport fallback: %s', exc)
            return (0, 0, target_width, target_height)

    def _effect_requests_frame_scaling(self, effect: BaseEffect | None) -> bool:
        """Return True when an effect should render inside Candy Frame bounds."""
        return effect is not None

    def _render_effect_to_current_target(
        self,
        effect: BaseEffect | None,
        target_width: int,
        target_height: int,
    ) -> None:
        """Render one effect to the currently bound framebuffer target."""
        if effect is None:
            return
        viewport = self._effect_viewport_for_target(
            target_width,
            target_height,
            effect,
        )
        self._ctx.viewport = viewport

        # glClear ignores viewport; constrain legacy effect clears by scissor.
        prev_scissor = self._ctx.scissor
        use_scissor = viewport != (0, 0, target_width, target_height)
        if use_scissor:
            self._ctx.scissor = viewport
        try:
            effect.render()
        finally:
            if use_scissor:
                self._ctx.scissor = prev_scissor

    def _normalize_gl_render_state(self) -> None:
        """Restore conservative GL state before HUD/overlay draw passes."""
        ctx = self._ctx
        # Keep canonical alpha-blend parameters, but leave blending disabled
        # so next-frame effect passes start from a neutral baseline.
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        ctx.disable(moderngl.BLEND)
        # Defensive resets for effects that mutate global render state.
        ctx.disable(moderngl.PROGRAM_POINT_SIZE)
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.CULL_FACE)
        ctx.scissor = None
        try:
            ctx.color_mask = (True, True, True, True)
        except Exception:
            # Some backends may not expose writable color masks.
            pass

    def _render(self, dt: float) -> None:
        ctx = self._ctx
        mirror_mode = self._is_mirror_mode(self._display_mode) and bool(self._mirror_rects)
        manager_modal_active = self._projectm_manager_modal_active
        burst_active = self._burst_controller.active and not manager_modal_active
        nova_active = (
            self._rainbow_nova is not None
            and self._rainbow_nova.is_active
            and not manager_modal_active
        )
        candy_active = (
            self._candy_frame is not None
            and bool(self._candy_frame.active)
            and not manager_modal_active
        )
        finale_overlay_active = (
            self._grand_finale is not None
            and self._grand_finale.overlay_active
            and not manager_modal_active
        )
        # Any active global post-FX pass (postfx, colour-grade, …) routes the
        # frame through the fbo_a/fbo_b chain and is applied via _apply_post_chain.
        post_chain_active = (
            not manager_modal_active and bool(self._active_post_chain())
        )
        # Advance burst timer
        if burst_active:
            self._burst_controller.step(dt)
        if self._next_effect is None:
            # No transition — render current effect; optionally apply invert/burst pass.
            if mirror_mode or self._invert_colors or self._render_scale < 0.999 or burst_active or post_chain_active or nova_active or candy_active or finale_overlay_active:
                self._fbo_a.use()
                ctx.viewport = (0, 0, self._render_width, self._render_height)
                ctx.clear(0.0, 0.0, 0.0, 1.0)
                self._render_effect_to_current_target(
                    self._current_effect,
                    self._render_width,
                    self._render_height,
                )
                if mirror_mode:
                    if self._invert_colors:
                        # Invert into fbo_b, copy back into fbo_a so webcam/HUD
                        # land on the inverted base in the same FBO chain.
                        self._fbo_b.use()
                        ctx.viewport = (0, 0, self._render_width, self._render_height)
                        ctx.clear(0.0, 0.0, 0.0, 1.0)
                        self._fbo_a.color_attachments[0].use(location=0)
                        self._invert_prog['tex'].value = 0
                        self._invert_vao.render(moderngl.TRIANGLE_STRIP)
                        # Now blit fbo_b back into fbo_a as the compose target.
                        self._blit_fbo_b_to_fbo_a(self._render_width, self._render_height)
                    if burst_active:
                        # Burst into fbo_b, copy back into fbo_a
                        scale, angle = self._burst_transform()
                        self._fbo_b.use()
                        ctx.viewport = (0, 0, self._render_width, self._render_height)
                        ctx.clear(0.0, 0.0, 0.0, 1.0)
                        self._fbo_a.color_attachments[0].use(location=0)
                        self._burst_prog['tex'].value = 0
                        self._burst_prog['uAngle'].value = angle
                        self._burst_prog['uScale'].value = scale
                        self._burst_vao.render(moderngl.TRIANGLE_STRIP)
                        # Now blit fbo_b back into fbo_a as the compose target.
                        self._blit_fbo_b_to_fbo_a(self._render_width, self._render_height)
                    if post_chain_active:
                        # Global post chain into fbo_b, copied back into fbo_a.
                        self._apply_post_chain(dt)
                    # Leave fbo_a bound at logical viewport so webcam/HUD compose
                    # into the same target. Tile-blit happens at end of frame.
                    self._fbo_a.use()
                    ctx.viewport = (0, 0, self._render_width, self._render_height)
                elif self._invert_colors:
                    if candy_active or nova_active or finale_overlay_active:
                        # Keep invert result in fbo_a so late overlays/candy use it.
                        self._fbo_b.use()
                        ctx.viewport = (0, 0, self._render_width, self._render_height)
                        ctx.clear(0.0, 0.0, 0.0, 1.0)
                        self._fbo_a.color_attachments[0].use(location=0)
                        self._invert_prog['tex'].value = 0
                        self._invert_vao.render(moderngl.TRIANGLE_STRIP)
                        self._blit_fbo_b_to_fbo_a(self._render_width, self._render_height)
                        self._present_from_tex(self._fbo_a.color_attachments[0])
                    else:
                        self._render_inverted_from_tex(self._fbo_a.color_attachments[0])
                elif burst_active:
                    if candy_active or nova_active or finale_overlay_active:
                        # Keep burst result in fbo_a so late overlays/candy use it.
                        scale, angle = self._burst_transform()
                        self._fbo_b.use()
                        ctx.viewport = (0, 0, self._render_width, self._render_height)
                        ctx.clear(0.0, 0.0, 0.0, 1.0)
                        self._fbo_a.color_attachments[0].use(location=0)
                        self._burst_prog['tex'].value = 0
                        self._burst_prog['uAngle'].value = angle
                        self._burst_prog['uScale'].value = scale
                        self._burst_vao.render(moderngl.TRIANGLE_STRIP)
                        self._blit_fbo_b_to_fbo_a(self._render_width, self._render_height)
                        self._present_from_tex(self._fbo_a.color_attachments[0])
                    else:
                        self._present_burst_from_tex(self._fbo_a.color_attachments[0])
                elif post_chain_active:
                    self._apply_post_chain(dt)
                    self._present_from_tex(self._fbo_a.color_attachments[0])
                else:
                    self._present_from_tex(self._fbo_a.color_attachments[0])
            else:
                ctx.screen.use()
                ctx.viewport = (0, 0, self._width, self._height)
                ctx.clear(0.0, 0.0, 0.0, 1.0)
                self._render_effect_to_current_target(
                    self._current_effect,
                    self._width,
                    self._height,
                )
        else:
            # Transition in progress
            audio_impact = 0.0
            if self._audio is not None:
                audio_impact = min(
                    1.0,
                    float(self._audio.bass) * 0.45
                    + float(self._audio.mid) * 0.30
                    + float(self._audio.treble) * 0.15
                    + float(self._audio.beat) * 0.40,
                )
            self._transition_t += (
                (1.0 / self._transition_duration)
                * dt
                * (1.0 + audio_impact * 0.45)
            )
            if self._transition_t >= 1.0:
                # Finish transition
                if self._current_effect:
                    self._current_effect.destroy()
                self._current_effect = self._next_effect
                self._next_effect = None
                self._re_randomize_on_scene_change()
                if mirror_mode or self._render_scale < 0.999 or post_chain_active or nova_active or candy_active or finale_overlay_active:
                    self._fbo_a.use()
                    ctx.viewport = (0, 0, self._render_width, self._render_height)
                    ctx.clear(0.0, 0.0, 0.0, 1.0)
                    self._render_effect_to_current_target(
                        self._current_effect,
                        self._render_width,
                        self._render_height,
                    )
                    if mirror_mode:
                        # Leave fbo_a bound; tile-blit at end of frame.
                        self._fbo_a.use()
                        ctx.viewport = (0, 0, self._render_width, self._render_height)
                    elif post_chain_active:
                        self._apply_post_chain(dt)
                        self._present_from_tex(self._fbo_a.color_attachments[0])
                    else:
                        self._present_from_tex(self._fbo_a.color_attachments[0])
                else:
                    ctx.screen.use()
                    ctx.viewport = (0, 0, self._width, self._height)
                    ctx.clear(0.0, 0.0, 0.0, 1.0)
                    self._render_effect_to_current_target(
                        self._current_effect,
                        self._width,
                        self._height,
                    )
            else:
                # Render A into FBO a
                self._fbo_a.use()
                ctx.viewport = (0, 0, self._render_width, self._render_height)
                ctx.clear(0.0, 0.0, 0.0, 1.0)
                self._render_effect_to_current_target(
                    self._current_effect,
                    self._render_width,
                    self._render_height,
                )

                # Render B into FBO b
                self._fbo_b.use()
                ctx.viewport = (0, 0, self._render_width, self._render_height)
                ctx.clear(0.0, 0.0, 0.0, 1.0)
                self._render_effect_to_current_target(
                    self._next_effect,
                    self._render_width,
                    self._render_height,
                )

                # Transition composite — to mirror compose FBO if mirror,
                # fbo_a when postfx is active, else directly to screen.
                if mirror_mode or post_chain_active:
                    composite_fbo = (
                        self._make_or_get_mirror_composite_fbo()
                        if mirror_mode
                        else self._fbo_a
                    )
                    composite_fbo.use()
                    ctx.viewport = (0, 0, self._render_width, self._render_height)
                else:
                    ctx.screen.use()
                    ctx.viewport = (0, 0, self._width, self._height)
                ctx.clear(0.0, 0.0, 0.0, 1.0)
                self._fbo_a.color_attachments[0].use(location=0)
                self._fbo_b.color_attachments[0].use(location=1)
                self._blend_prog["tex_a"].value = 0
                self._blend_prog["tex_b"].value = 1
                self._blend_prog["t"].value = self._transition_t
                self._blend_prog["mode"].value = _TRANSITION_MODE_MAP.get(self._transition_kind, 0)
                self._blend_prog["dir"].value = self._transition_dir
                self._transition_phase += dt * (0.6 + audio_impact * 1.4)
                self._blend_prog["phase"].value = self._transition_phase
                self._blend_prog["iAudioImpact"].value = audio_impact
                self._blend_prog["iPalShift"].value = (self._transition_phase * 0.31) % 1.0
                self._blend_prog["iLightWrap"].value = 0.10 + audio_impact * 0.28
                self._blend_vao.render(moderngl.TRIANGLE_STRIP)
                if mirror_mode:
                    # Copy composite into fbo_a so webcam/HUD compose into it,
                    # then tile-blit at end of frame.
                    self._fbo_a.use()
                    ctx.viewport = (0, 0, self._render_width, self._render_height)
                    ctx.clear(0.0, 0.0, 0.0, 1.0)
                    self._mirror_composite_fbo.color_attachments[0].use(location=0)
                    self._present_prog['tex'].value = 0
                    self._present_vao.render(moderngl.TRIANGLE_STRIP)
                elif post_chain_active:
                    self._apply_post_chain(dt)
                    self._present_from_tex(self._fbo_a.color_attachments[0])

    def _make_or_get_mirror_composite_fbo(self) -> moderngl.Framebuffer:
        """Lazy-create a single FBO used to compose mirror transitions."""
        existing = getattr(self, '_mirror_composite_fbo', None)
        if existing is not None:
            tex = existing.color_attachments[0]
            if tex.size == (self._render_width, self._render_height):
                return existing
            existing.release()
            tex.release()
        self._mirror_composite_fbo = self._make_fbo()
        return self._mirror_composite_fbo

    def _handle_recording_resize_interruption(self, reason: str) -> None:
        """Rotate active recording when output dimensions change mid-session."""
        if self._recorder is None or not self._recorder.is_recording:
            return
        _stopped, stop_msg = self.stop_recording()
        restarted, _start_msg = self.start_recording()
        if restarted:
            msg = f'{stop_msg} | Recording restarted ({reason})'
            level = log.info
        else:
            msg = f'{stop_msg} | Recording stopped ({reason})'
            level = log.warning
        level(msg)
        if self._overlays is not None:
            self._overlays.flash_message(msg, 2.6)

    def _on_resize(self, w: int, h: int) -> None:
        if self._is_mirror_mode(self._display_mode):
            # Window grew/shrunk; logical size stays at one display worth.
            self._sync_window_origin_from_sdl()
            self._window_width = w
            self._window_height = h
            self._mirror_rects = self._multihead_mirror_layout(
                self._window_origin_x, self._window_origin_y
            )
            if self._webcam_system is not None:
                self._webcam_system.resize(self._width, self._height)
            if self._candy_frame is not None:
                self._candy_frame.resize(self._width, self._height)
            self._update_render_target_size()
            self._rebuild_fbos()
            self._release_readback_pbos()
            self._handle_recording_resize_interruption('resize/fullscreen change')
            if self._streamer is not None:
                self._streamer.resize(self._width, self._height)
            if self._current_effect:
                self._current_effect.resize(self._width, self._height)
            if self._next_effect:
                self._next_effect.resize(self._width, self._height)
            if self._postfx_controller is not None:
                self._postfx_controller.resize(self._render_width, self._render_height)
            return
        self._width = w
        self._height = h
        self._window_width = w
        self._window_height = h
        if self._webcam_system is not None:
            self._webcam_system.resize(w, h)
        if self._candy_frame is not None:
            self._candy_frame.resize(w, h)
        self._update_render_target_size()
        self._release_readback_pbos()
        self._handle_recording_resize_interruption('resize/fullscreen change')
        if self._streamer is not None:
            self._streamer.resize(w, h)
        if self._current_effect:
            self._current_effect.resize(w, h)
        if self._next_effect:
            self._next_effect.resize(w, h)
        if self._postfx_controller is not None:
            self._postfx_controller.resize(self._render_width, self._render_height)
        if self._grand_finale is not None:
            self._grand_finale.resize(w, h)
        if self._overlays is not None:
            self._overlays.resize(w, h)
        self._resize_mirror_textures()
        # When leaving mirror mode the composite FBO is no longer needed.
        # Release it before recreating fbo_a / fbo_b so its texture/depth
        # buffer don't linger in GL state during the texture re-allocations
        # below (which previously surfaced as a "cannot create texture" abort
        # when toggling mirror_all → single).
        if not self._is_mirror_mode(self._display_mode):
            composite = getattr(self, '_mirror_composite_fbo', None)
            if composite is not None:
                try:
                    composite.color_attachments[0].release()
                except Exception:
                    pass
                try:
                    composite.release()
                except Exception:
                    pass
                self._mirror_composite_fbo = None
        # Rebuild FBOs at new size
        if self._fbo_a:
            self._fbo_a.release()
        if self._fbo_b:
            self._fbo_b.release()
        self._fbo_a = self._make_fbo()
        self._fbo_b = self._make_fbo()

    # ------------------------------------------------------------------ #
    # Public API (called by hotkey handler)                                #
    # ------------------------------------------------------------------ #

    def toggle_fullscreen(self) -> None:
        self._fullscreen = not self._fullscreen
        if self._is_span_mode(self._display_mode):
            if self._fullscreen:
                x, y, w, h = self._all_display_bounds()
                sdl2.SDL_SetWindowFullscreen(self._window, 0)
                sdl2.SDL_SetWindowBordered(self._window, sdl2.SDL_FALSE)
            else:
                x, y = self._window_position_for_display(self._display_index)
                w = int(self.cfg.get('window', 'width', default=1920))
                h = int(self.cfg.get('window', 'height', default=1080))
                sdl2.SDL_SetWindowFullscreen(self._window, 0)
                sdl2.SDL_SetWindowBordered(self._window, sdl2.SDL_TRUE)
            sdl2.SDL_SetWindowPosition(self._window, x, y)
            sdl2.SDL_SetWindowSize(self._window, w, h)
        else:
            if self._fullscreen and self._prefer_borderless_fullscreen():
                x, y, w, h = self._fullscreen_window_geometry()
                sdl2.SDL_SetWindowFullscreen(self._window, 0)
                sdl2.SDL_SetWindowBordered(self._window, sdl2.SDL_FALSE)
                sdl2.SDL_SetWindowPosition(self._window, x, y)
                sdl2.SDL_SetWindowSize(self._window, w, h)
            else:
                flag = sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP if self._fullscreen else 0
                if self._fullscreen:
                    self._move_window_to_display()
                sdl2.SDL_SetWindowBordered(self._window, sdl2.SDL_TRUE)
                sdl2.SDL_SetWindowFullscreen(self._window, flag)
                if not self._fullscreen:
                    self._move_window_to_display()

    def set_display_mode(self, mode: str | None = None, reset_to_config: bool = False) -> str:
        """Switch display mode at runtime.

        Modes: single, span_included, span_all, mirror_included, mirror_all.
        """
        if reset_to_config:
            requested = str(self.cfg.get('window', 'display_mode', default='single')).lower()
            requested_index = int(self.cfg.get('window', 'display_index', default=0))
        else:
            requested = str(mode or self._display_mode).lower()
            requested_index = self._display_index

        allowed = {'single', 'span_included', 'span_all', 'mirror_included', 'mirror_all'}
        if requested not in allowed:
            requested = 'single'

        self._set_multihead_mode(requested)
        self._set_multihead_index(requested_index)
        self._display_mode = requested

        # Ensure display layout cache is fresh before geometry changes.
        self._log_video_displays()
        self._display_index = self._resolve_display_index()

        # Tear down old mirror windows before mode transition.
        self._destroy_mirror_outputs()

        if self._fullscreen:
            if self._is_span_mode(self._display_mode):
                x, y, w, h = self._all_display_bounds()
                sdl2.SDL_SetWindowFullscreen(self._window, 0)
                sdl2.SDL_SetWindowBordered(self._window, sdl2.SDL_FALSE)
                sdl2.SDL_SetWindowPosition(self._window, x, y)
                sdl2.SDL_SetWindowSize(self._window, w, h)
            elif self._is_mirror_mode(self._display_mode):
                x, y, w, h = self._all_display_bounds()
                sdl2.SDL_SetWindowFullscreen(self._window, 0)
                sdl2.SDL_SetWindowBordered(self._window, sdl2.SDL_FALSE)
                sdl2.SDL_SetWindowPosition(self._window, x, y)
                sdl2.SDL_SetWindowSize(self._window, w, h)
                self._window_origin_x = x
                self._window_origin_y = y
            elif self._prefer_borderless_fullscreen():
                x, y, w, h = self._fullscreen_window_geometry()
                sdl2.SDL_SetWindowFullscreen(self._window, 0)
                sdl2.SDL_SetWindowBordered(self._window, sdl2.SDL_FALSE)
                sdl2.SDL_SetWindowPosition(self._window, x, y)
                sdl2.SDL_SetWindowSize(self._window, w, h)
            else:
                sdl2.SDL_SetWindowBordered(self._window, sdl2.SDL_TRUE)
                self._move_window_to_display()
                sdl2.SDL_SetWindowFullscreen(self._window, sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP)
        else:
            sdl2.SDL_SetWindowFullscreen(self._window, 0)
            sdl2.SDL_SetWindowBordered(self._window, sdl2.SDL_TRUE)
            if self._is_span_mode(self._display_mode):
                x, y, w, h = self._all_display_bounds()
                sdl2.SDL_SetWindowPosition(self._window, x, y)
                sdl2.SDL_SetWindowSize(self._window, w, h)
            elif self._is_mirror_mode(self._display_mode):
                x, y, w, h = self._all_display_bounds()
                sdl2.SDL_SetWindowBordered(self._window, sdl2.SDL_FALSE)
                sdl2.SDL_SetWindowPosition(self._window, x, y)
                sdl2.SDL_SetWindowSize(self._window, w, h)
                self._window_origin_x = x
                self._window_origin_y = y
            else:
                w = int(self.cfg.get('window', 'width', default=1920))
                h = int(self.cfg.get('window', 'height', default=1080))
                sdl2.SDL_SetWindowSize(self._window, w, h)
                self._move_window_to_display()

        # Keep app render targets/effects in sync with actual window size.
        w_i = ctypes.c_int(0)
        h_i = ctypes.c_int(0)
        sdl2.SDL_GetWindowSize(self._window, w_i, h_i)
        if self._is_mirror_mode(self._display_mode):
            # Switch logical canvas to primary display's resolution and rebuild
            # mirror viewport rects against the new window origin.
            primary_layout = self._primary_active_layout()
            if primary_layout is not None:
                self._width = primary_layout[2]
                self._height = primary_layout[3]
            self._sync_window_origin_from_sdl()
            self._window_width = w_i.value or self._window_width
            self._window_height = h_i.value or self._window_height
            self._mirror_rects = self._multihead_mirror_layout(
                self._window_origin_x, self._window_origin_y
            )
            self._update_render_target_size()
            if self._current_effect:
                self._current_effect.resize(self._width, self._height)
            if self._next_effect:
                self._next_effect.resize(self._width, self._height)
            if self._webcam_system is not None:
                self._webcam_system.resize(self._width, self._height)
            if self._candy_frame is not None:
                self._candy_frame.resize(self._width, self._height)
            if self._postfx_controller is not None:
                self._postfx_controller.resize(self._render_width, self._render_height)
            if self._overlays is not None:
                self._overlays.resize(self._width, self._height)
            self._rebuild_fbos()
            log.info(
                'Mirror (GL-native) reconfigured: window=%dx%d logical=%dx%d rects=%s',
                self._window_width,
                self._window_height,
                self._width,
                self._height,
                self._mirror_rects,
            )
        else:
            self._mirror_rects = []
            self._on_resize(w_i.value or self._width, h_i.value or self._height)
            if self._overlays is not None:
                self._overlays.resize(self._width, self._height)

        return self._display_mode

    def cycle_display_mode(self) -> str:
        """Cycle through display modes in operator-friendly order."""
        order = ['single', 'span_included', 'span_all', 'mirror_included', 'mirror_all']
        current = self._display_mode if self._display_mode in order else 'single'
        next_mode = order[(order.index(current) + 1) % len(order)]
        return self.set_display_mode(next_mode)

    def toggle_pause(self) -> None:
        self._paused = not self._paused

    def set_projectm_manager_modal_active(self, active: bool) -> None:
        """Set whether the ProjectM preset manager owns runtime control."""
        new_state = bool(active)
        if self._projectm_manager_modal_active == new_state:
            return
        self._projectm_manager_modal_active = new_state
        for effect in (self._current_effect, self._next_effect):
            setter = getattr(effect, 'set_manager_preview_active', None)
            if callable(setter):
                setter(new_state)
        log.info(
            'ProjectM manager modal %s',
            'enabled' if new_state else 'disabled',
        )

    def _open_external_url(self, url: str) -> bool:
        """Open an external URL using the platform launcher without blocking."""
        target = str(url or '').strip()
        if not target:
            return False
        try:
            subprocess.Popen(
                ['xdg-open', target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as exc:
            log.warning('Failed to launch external URL %s: %s', target, exc)
            return False

    def handle_help_icon_action(self, action: dict[str, str]) -> str:
        """Dispatch a help icon action payload and return user-facing status text."""
        action_kind = str(action.get('action_kind', 'placeholder') or 'placeholder').strip().lower()
        message = str(action.get('message', '') or '').strip()
        label = str(action.get('label', 'Help icon') or 'Help icon').strip()
        target = str(action.get('target', '') or '').strip()

        if action_kind == 'url':
            if not target:
                return message or f'{label}: link unavailable'
            if self._open_external_url(target):
                return message or f'Opening {label}'
            return f'{label}: failed to open link'

        if action_kind == 'projectm_manager':
            opened = bool(self.vj_api.open_projectm_manager())
            if opened:
                self.set_projectm_manager_modal_active(True)
                return message or 'Opened drop-ins browser'
            return 'Drop-ins browser unavailable'

        return message or f'{label}: coming soon'

    @property
    def current_effect(self) -> BaseEffect | None:
        return self._current_effect

    @property
    def current_effect_name(self) -> str:
        return self._current_effect.NAME if self._current_effect is not None else ''

    def resolve_projectm_manager_effect(self) -> BaseEffect | None:
        """Return a ProjectM manager-capable effect instance, switching if needed.

        If ProjectM is already active or queued as the next transition target,
        return that instance. Otherwise, switch to ProjectM Presets and return
        the newly instantiated pending effect so the manager can open on a
        single Ctrl+M press from any current effect.
        """
        required = (
            'preset_catalog',
            'goto_preset_path',
            'enable_all_presets',
            'disable_all_presets',
            'enable_category',
            'disable_category',
            'isolate_category',
            'set_presets_enabled',
            'delete_presets',
        )

        for inst in (self._current_effect, self._next_effect):
            if inst is None:
                continue
            if type(inst).__name__ != 'ProjectMEffect':
                continue
            if all(callable(getattr(inst, name, None)) for name in required):
                return inst

        projectm_cls = self.vj_api.find_effect('ProjectMEffect', 'ProjectM Presets')
        if projectm_cls is None:
            return None

        # Opening the manager is an explicit ProjectM request: a pin/lock on a
        # non-ProjectM effect must not block the switch, or Ctrl+M would silently
        # fail while an effect is pinned.
        if self._effect_lock is not None and self._effect_lock != 'ProjectM Presets':
            self.unlock_effect()

        log.info('ProjectM manager: switching to ProjectM Presets from %s', self.current_effect_name or '(none)')
        self.goto_effect(projectm_cls)

        pending = self._next_effect
        if pending is not None and type(pending).__name__ == 'ProjectMEffect':
            if all(callable(getattr(pending, name, None)) for name in required):
                return pending
        return None

    @property
    def auto_vj_controller(self):
        return self._auto_vj

    @property
    def has_webcam_system(self) -> bool:
        return self._webcam_system is not None

    @property
    def speed_randomized(self) -> bool:
        return self._speed_randomized

    @property
    def reactivity_randomized(self) -> bool:
        return self._reactivity_randomized

    @property
    def zoom_randomized(self) -> bool:
        return self._zoom_randomized

    def set_speed_randomized(self, enabled: bool) -> None:
        self._speed_randomized = bool(enabled)

    def set_reactivity_randomized(self, enabled: bool) -> None:
        self._reactivity_randomized = bool(enabled)

    def set_zoom_randomized(self, enabled: bool) -> None:
        self._zoom_randomized = bool(enabled)

    def _confirm_exit_dialog(self) -> bool:
        """Show a modal yes/no confirmation dialog for app shutdown."""
        if self._window is None:
            return True

        buttons = (sdl2.SDL_MessageBoxButtonData * 2)()
        buttons[0] = sdl2.SDL_MessageBoxButtonData(
            flags=sdl2.SDL_MESSAGEBOX_BUTTON_ESCAPEKEY_DEFAULT,
            buttonid=0,
            text=b'No',
        )
        buttons[1] = sdl2.SDL_MessageBoxButtonData(
            flags=sdl2.SDL_MESSAGEBOX_BUTTON_RETURNKEY_DEFAULT,
            buttonid=1,
            text=b'Yes',
        )

        message_box = sdl2.SDL_MessageBoxData(
            flags=sdl2.SDL_MESSAGEBOX_WARNING,
            window=self._window,
            title=b'Quit Unicorn Viz?',
            message=b'Exit the main program now?',
            numbuttons=2,
            buttons=buttons,
            colorScheme=None,
        )
        selected = ctypes.c_int(0)
        result = sdl2.SDL_ShowMessageBox(ctypes.byref(message_box), ctypes.byref(selected))
        if result < 0:
            log.warning('Quit confirmation dialog failed: %s', sdl2.SDL_GetError().decode())
            return False
        return int(selected.value) == 1

    def request_exit(self, *, force: bool = False) -> bool:
        if not bool(force) and self._confirm_exit_enabled:
            if not self._confirm_exit_dialog():
                return False
        self._running = False
        return True

    def midi_action_for_note(self, number: int) -> str | None:
        if self._midi_manager is None:
            return None
        return self._midi_manager.note_to_action(number)

    def midi_param_for_cc(self, number: int) -> str | None:
        if self._midi_manager is None:
            return None
        return self._midi_manager.cc_to_param(number)

    def select_midi_device(self, port_name: str) -> str:
        """
        Hot-swap the active MIDI input port.

        Passes ``port_name`` as a device hint substring to ``MidiManager.reopen()``.
        An empty string closes the current port and disables MIDI.
        Returns a human-readable status string for HUD display.
        """
        from unicornviz.midi import list_ports
        if self._midi_manager is None:
            return 'MIDI: subsystem unavailable'
        ok = self._midi_manager.reopen(port_name)
        if not port_name:
            return 'MIDI: disabled'
        if ok:
            label = self._midi_manager.active_port_label or self._midi_manager.port_name
            return f'MIDI: {label}'
        ports = list_ports()
        if not ports:
            return 'MIDI: no ports found'
        return f'MIDI: port not found ({port_name!r})'

    def get_midi_ports(self) -> list[str]:
        """Return available MIDI input port names for the device selector UI."""
        from unicornviz.midi import list_ports
        return list_ports()

    def get_audio_sources(self) -> list[str]:
        """Return available audio capture sources for selector UI."""
        return self._audio_manager.list_sources()

    def get_audio_source_index(self) -> int:
        """Return currently selected audio source index for selector UI."""
        return self._audio_manager.get_source_index()

    def get_audio_source_viable_flags(self) -> list[bool]:
        """Return viability flags for audio source selector UI."""
        return self._audio_manager.source_viable_flags()

    def select_audio_source(self, index: int) -> str:
        """Select a specific audio source by index and return a HUD message."""
        label = self._audio_manager.select_source(index)
        return f'Audio source: {label}'

    def cycle_audio_source(self, delta: int) -> str:
        """Cycle active audio capture source and return a HUD message."""
        label = self._audio_manager.cycle_source(delta)
        return f'Audio source: {label}'

    def toggle_audio_source_viable(self, index: int) -> str:
        """Toggle viability tag for a source row and return a HUD message."""
        _enabled, msg = self._audio_manager.toggle_source_viable(index)
        return msg

    def select_postfx_slot(self, slot: int) -> str:
        """Select active post-process slot (0 disables)."""
        if self._postfx_controller is None:
            return 'Post FX: unavailable'
        msg = self._postfx_controller.select_slot(slot)
        log.debug('PostFX select_slot(%s) -> %s', slot, msg)
        return msg

    def start_recording(self) -> tuple[bool, str]:
        """Start recording if recording support is enabled."""
        if self._recorder is None:
            self._recorder = Recorder(self.cfg, self._width, self._height)
        if not self._recorder.enabled:
            self._sync_recording_overlay()
            return False, 'Recording disabled'
        if self._recorder.is_recording:
            self._sync_recording_overlay()
            return True, 'Recording already on'
        started = self._recorder.start()
        self._sync_recording_overlay()
        if started:
            return True, 'Recording: ON'
        return False, self._recorder.last_error or 'Recording failed'

    def stop_recording(self) -> tuple[bool, str]:
        """Stop recording and report where the file was saved."""
        if self._recorder is None or not self._recorder.is_recording:
            self._sync_recording_overlay()
            return False, 'Recording already off'
        path = self._recorder.stop()
        self._sync_recording_overlay()
        if path is not None:
            return False, f'Recording saved: {path}'
        return False, 'Recording: OFF'

    def toggle_recording(self) -> tuple[bool, str]:
        """Toggle in-app recording on or off."""
        if self._recorder is not None and self._recorder.is_recording:
            return self.stop_recording()
        return self.start_recording()

    def start_streaming(self) -> tuple[bool, str]:
        """Start RTMP streaming if subsystem is available/enabled."""
        if self._streamer is None:
            return False, 'Streaming subsystem unavailable'
        if not self._streamer.enabled:
            return False, 'Streaming disabled in config'
        if self._streamer.is_streaming:
            return True, 'Streaming already live'
        if self._streamer.start():
            return True, f'Streaming LIVE: {self._streamer.destination_label}'
        return False, self._streamer.last_error or 'Streaming start failed'

    def stop_streaming(self) -> tuple[bool, str]:
        """Stop RTMP streaming if active."""
        if self._streamer is None:
            return False, 'Streaming subsystem unavailable'
        if not self._streamer.is_streaming:
            return False, 'Streaming already off'
        self._streamer.stop()
        return False, 'Streaming OFF'

    def toggle_streaming(self) -> tuple[bool, str]:
        """Toggle RTMP streaming state."""
        if self._streamer is not None and self._streamer.is_streaming:
            return self.stop_streaming()
        return self.start_streaming()

    def set_stream_provider(self, provider: str) -> str:
        """Set stream provider preset endpoint and return active provider."""
        if self._streamer is None:
            return 'unavailable'
        return self._streamer.set_provider(provider, restart=True)

    def trigger_streaming_cta(self) -> str:
        """Trigger CTA overlay via streaming drop-in ownership with core fallback."""
        if self._overlays is None:
            return 'CTA unavailable'

        payload = None
        if self._streamer is not None:
            method = getattr(self._streamer, 'trigger_cta', None)
            if callable(method):
                try:
                    payload = method()
                except Exception as exc:
                    log.debug('Streaming CTA trigger failed: %s', exc)

        if payload is None:
            self._overlays.trigger_cta()
            return 'CTA triggered (default)'

        text, icon, duration = payload
        self._overlays.trigger_cta_custom(str(text), str(icon), float(duration))
        return 'CTA triggered'

    def trigger_streaming_song_cta(self, one_more: bool = False) -> str:
        """Trigger dedicated song CTA overlay via streaming drop-in ownership."""
        if self._overlays is None:
            return 'CTA unavailable'

        payload = None
        if self._streamer is not None:
            method = getattr(self._streamer, 'trigger_song_cta', None)
            if callable(method):
                try:
                    payload = method(bool(one_more))
                except Exception as exc:
                    log.debug('Streaming song CTA trigger failed: %s', exc)

        if payload is None:
            text = 'One more song!' if one_more else 'Last song!'
            self._overlays.trigger_cta_custom(text, '🎵', 4.5)
            return 'CTA triggered (default)'

        text, icon, duration = payload
        self._overlays.trigger_cta_custom(str(text), str(icon), float(duration))
        return 'CTA triggered'

    def _apply_random_speed(self) -> None:
        """Apply random speed using effect-local overrides when available."""
        if self._current_effect is None or 'speed' not in self._current_effect.parameters:
            return  # flag stays as-is; will apply when a supporting effect becomes active
        lo, hi = self._random_range_for('speed', 0.25, 2.50)
        value = float(self._rng.uniform(lo, hi))
        self._current_effect.parameters['speed'] = value
        self._speed_randomized = True

    def _reset_speed(self) -> float | None:
        """Reset current effect speed to its initial default if supported."""
        if self._current_effect is None or 'speed' not in self._current_effect.parameters:
            return None
        default = self._current_effect._initial_parameters.get('speed', 1.0)  # noqa: SLF001
        self._current_effect.parameters['speed'] = default
        self._speed_randomized = False
        return float(default)

    def _apply_random_reactivity(self) -> None:
        """Apply random reactivity using effect-local overrides when available."""
        if self._audio_manager is None:
            return
        lo, hi = self._random_range_for('reactivity', 0.40, 2.00)
        value = float(self._rng.uniform(lo, hi))
        self._audio_manager.set_reactivity(round(value, 2))
        self._reactivity_randomized = True

    def _apply_zoom_delta(self, delta: float) -> float:
        """Adjust zoom of current effect by delta. Returns new zoom or 0 if unavailable."""
        if self._current_effect is None or 'zoom' not in self._current_effect.parameters:
            return 0.0
        lo = float(self.cfg.get('hotkeys', 'zoom_min', default=0.1))
        hi = float(self.cfg.get('hotkeys', 'zoom_max', default=3.0))
        current = self._current_effect.parameters['zoom']
        new_val = max(lo, min(hi, current + delta))
        self._current_effect.parameters['zoom'] = new_val
        return new_val

    def _reset_zoom(self) -> float | None:
        """Reset zoom to the effect's initial default. Returns reset value or None if unavailable."""
        if self._current_effect is None or 'zoom' not in self._current_effect.parameters:
            return None
        default = self._current_effect._initial_parameters.get('zoom', 1.0)  # noqa: SLF001
        self._current_effect.parameters['zoom'] = default
        self._zoom_randomized = False
        return default

    def _apply_random_zoom(self) -> None:
        """Apply random zoom using effect-local overrides when available."""
        if self._current_effect is None or 'zoom' not in self._current_effect.parameters:
            return  # flag stays as-is; will apply when a supporting effect becomes active
        lo, hi = self._random_range_for('zoom', 0.30, 1.80)
        value = float(self._rng.uniform(lo, hi))
        self._current_effect.parameters['zoom'] = value
        self._zoom_randomized = True

    def _random_range_for(self, name: str, default_min: float, default_max: float) -> tuple[float, float]:
        """Resolve the active randomization range from effect config, then global hotkeys."""
        lo = float(self.cfg.get('hotkeys', f'random_{name}_min', default=default_min))
        hi = float(self.cfg.get('hotkeys', f'random_{name}_max', default=default_max))
        effect_cfg = getattr(self._current_effect, 'config', None)
        if isinstance(effect_cfg, dict):
            effect_lo = effect_cfg.get(f'random_{name}_min')
            effect_hi = effect_cfg.get(f'random_{name}_max')
            if effect_lo is not None:
                lo = float(effect_lo)
            if effect_hi is not None:
                hi = float(effect_hi)
        if lo > hi:
            lo, hi = hi, lo
        return lo, hi

    def _re_randomize_on_scene_change(self) -> None:
        """Re-apply random values when scene transitions complete."""
        if self._speed_randomized:
            self._apply_random_speed()
        if self._reactivity_randomized:
            self._apply_random_reactivity()
        if self._zoom_randomized:
            self._apply_random_zoom()

    def _rebuild_fbos(self) -> None:
        """Recompute render dimensions and recreate FBOs after a scale change."""
        self._update_render_target_size()
        if self._postfx_controller is not None:
            self._postfx_controller.resize(self._render_width, self._render_height)
        if self._fbo_a:
            self._fbo_a.release()
        if self._fbo_b:
            self._fbo_b.release()
        self._fbo_a = self._make_fbo()
        self._fbo_b = self._make_fbo()

    def _reset_render_scale(self) -> float:
        """Reset render scale to config default."""
        self._render_scale = self._render_scale_default
        self._rebuild_fbos()
        return self._render_scale

    def _set_render_scale(self, value: float) -> float:
        """Set render scale to an explicit value and rebuild FBOs."""
        self._render_scale = _clamp_render_scale(float(value))
        self._rebuild_fbos()
        return self._render_scale

    def _apply_render_scale_delta(self, delta: float) -> float:
        """Nudge render scale by delta and rebuild FBOs."""
        self._render_scale = _clamp_render_scale(self._render_scale + float(delta))
        self._rebuild_fbos()
        return self._render_scale

    def apply_random_speed(self) -> None:
        self._apply_random_speed()

    def reset_speed(self) -> float | None:
        return self._reset_speed()

    def apply_random_reactivity(self) -> None:
        self._apply_random_reactivity()

    def apply_zoom_delta(self, delta: float) -> float:
        return self._apply_zoom_delta(delta)

    def reset_zoom(self) -> float | None:
        return self._reset_zoom()

    def apply_random_zoom(self) -> None:
        self._apply_random_zoom()

    def random_range_for(self, name: str, default_min: float, default_max: float) -> tuple[float, float]:
        return self._random_range_for(name, default_min, default_max)

    def reset_render_scale(self) -> float:
        return self._reset_render_scale()

    def set_render_scale(self, value: float) -> float:
        return self._set_render_scale(value)

    def apply_render_scale_delta(self, delta: float) -> float:
        return self._apply_render_scale_delta(delta)

    def _capture_recording_frame(self) -> None:
        """Capture the final on-screen frame for recording."""
        if self._ctx is None or self._recorder is None or not self._recorder.is_recording:
            return
        try:
            screenshot = self.read_screenshot_frame()
            if screenshot is None:
                return
            frame, _width, _height = screenshot
            self._write_recording_frame(frame)
        except Exception as exc:
            log.error('Recording capture failed: %s', exc)
            self._recorder.stop()
            self._sync_recording_overlay()

    def _write_recording_frame(self, frame: bytes) -> None:
        """Write a pre-read RGB frame to the active recorder."""
        if self._recorder is None or not self._recorder.is_recording:
            return
        if not self._recorder.write_frame(frame):
            self._sync_recording_overlay()

    def _read_streaming_frame(self) -> bytes | None:
        """Read one RGB24 frame for RTMP streaming using double-buffered PBOs.

        Issues the current-frame readback into the write PBO immediately (the
        GPU DMA starts now), then returns the *previous* frame's bytes from the
        read PBO (whose DMA completed during the last swap + render).  The
        result is one frame of latency but zero pipeline stall on the hot path.

        Falls back to direct synchronous read if the PBO path fails.
        """
        if self._ctx is None:
            return None
        mirror_mode_active = self._is_mirror_mode(self._display_mode) and bool(self._mirror_rects)
        source = self._fbo_a if (mirror_mode_active and self._fbo_a is not None) else self._ctx.screen
        size = self._width * self._height * 3  # RGB24
        if self._stream_pbo_disabled:
            try:
                return source.read(components=3, alignment=1)
            except Exception as exc:
                log.error('Streaming direct read failed: %s', exc)
                return None

        # Ensure PBOs exist and are correctly sized.
        if len(self._stream_pbos) != 2 or self._stream_pbo_size != size:
            for pbo in self._stream_pbos:
                pbo.release()
            self._stream_pbos = [self._ctx.buffer(reserve=size), self._ctx.buffer(reserve=size)]
            self._stream_pbo_size = size
            self._stream_pbo_index = 0
            self._stream_pbo_primed = False

        write_idx = self._stream_pbo_index
        read_idx = 1 - write_idx
        try:
            source.read_into(self._stream_pbos[write_idx], components=3, alignment=1)
            frame: bytes | None = None
            if self._stream_pbo_primed:
                frame = self._stream_pbos[read_idx].read()
            else:
                self._stream_pbo_primed = True
            self._stream_pbo_index = read_idx
            return frame
        except Exception as exc:
            log.warning(
                'Streaming PBO readback failed, disabling PBO for this session: %s',
                exc,
            )
            for pbo in self._stream_pbos:
                pbo.release()
            self._stream_pbos = []
            self._stream_pbo_size = 0
            self._stream_pbo_primed = False
            self._stream_pbo_index = 0
            self._stream_pbo_disabled = True
            try:
                return source.read(components=3, alignment=1)
            except Exception as read_exc:
                log.error('Streaming direct read after PBO failure also failed: %s', read_exc)
                return None

    def read_screenshot_frame(self) -> tuple[bytes, int, int] | None:
        """Read an RGB24 screenshot frame from the current drawable surface.

        Uses SDL's drawable size so image dimensions always match readback data
        in single/span/mirror modes.
        """
        if self._ctx is None or self._window is None:
            return None
        draw_w = ctypes.c_int(0)
        draw_h = ctypes.c_int(0)
        sdl2.SDL_GL_GetDrawableSize(self._window, draw_w, draw_h)
        w = int(draw_w.value or 0)
        h = int(draw_h.value or 0)
        if w <= 0 or h <= 0:
            w = int(self._window_width or self._width)
            h = int(self._window_height or self._height)
        data = self._ctx.screen.read(viewport=(0, 0, w, h), components=3, alignment=1)
        return data, w, h

    def goto_effect(self, cls: Type[BaseEffect]) -> None:
        self._switch_effect(cls)

    @property
    def effect_lock(self) -> str | None:
        """Display NAME of the locked effect, or None when not locked."""
        return self._effect_lock

    def lock_effect(self, name: str) -> None:
        """Pin the system to the effect with display NAME *name* (generic;
        the effects browser reuses this). Does not itself switch effects."""
        self._effect_lock = str(name) if name else None

    def unlock_effect(self) -> None:
        """Clear any effect lock."""
        self._effect_lock = None

    # -- Effect enable/disable (persisted, excluded from auto-rotation) -------

    def effect_enabled(self, name: str) -> bool:
        """Return whether the effect (display or class name) is rotation-enabled."""
        return str(name) not in self._disabled_effects

    def set_effect_enabled(self, name: str, enabled: bool) -> None:
        """Enable/disable an effect for auto-rotation and persist the choice."""
        name = str(name)
        if enabled:
            self._disabled_effects.discard(name)
        else:
            self._disabled_effects.add(name)
        self._runtime_state.set('effects.disabled', sorted(self._disabled_effects))
        self._runtime_state.save()
        if self._playlist is not None:
            self._playlist.set_disabled(self._disabled_effects)

    def set_disabled_effects(self, names: 'set[str] | list[str]') -> None:
        """Replace the whole disabled set at once and persist (preset apply)."""
        self._disabled_effects = {str(n) for n in (names or [])}
        self._runtime_state.set('effects.disabled', sorted(self._disabled_effects))
        self._runtime_state.save()
        if self._playlist is not None:
            self._playlist.set_disabled(self._disabled_effects)

    # -- Show presets (named runtime-setup snapshots) ------------------------

    def capture_show_preset(self) -> dict[str, object]:
        """Snapshot the current show setup into a preset payload."""
        reactivity = 1.0
        if self._audio_manager is not None:
            try:
                reactivity = float(self._audio_manager.get_reactivity())
            except Exception:
                reactivity = 1.0
        mode = self._playlist.mode if self._playlist is not None else 'sequential'
        return {
            'version': 1,
            'disabled_effects': sorted(self._disabled_effects),
            'playlist_mode': str(mode),
            'reactivity': reactivity,
        }

    def apply_show_preset(self, payload: dict[str, object]) -> None:
        """Apply a preset payload to the running show (missing keys untouched)."""
        if not isinstance(payload, dict):
            return
        if 'disabled_effects' in payload:
            self.set_disabled_effects(payload.get('disabled_effects') or [])
        mode = payload.get('playlist_mode')
        if mode and self._playlist is not None:
            self._playlist.set_mode(str(mode))
            self._playlist_mode = self._playlist.mode
        if 'reactivity' in payload and self._audio_manager is not None:
            try:
                self._audio_manager.set_reactivity(float(payload.get('reactivity', 1.0)))
            except Exception:
                log.debug('Preset reactivity apply failed', exc_info=True)

    def list_show_presets(self) -> list[str]:
        """Return saved show-preset names."""
        return self._preset_store.names()

    def save_show_preset(self, name: str) -> str | None:
        """Save the current show setup under *name*. Returns the saved name."""
        clean = str(name).strip()
        if not clean:
            return None
        self._preset_store.save(clean, self.capture_show_preset())
        return clean

    def load_show_preset(self, name: str) -> bool:
        """Apply the named preset. Returns True if it existed."""
        payload = self._preset_store.get(name)
        if payload is None:
            return False
        self.apply_show_preset(payload)
        return True

    def delete_show_preset(self, name: str) -> bool:
        """Delete the named preset. Returns True if it existed."""
        return self._preset_store.delete(name)

    # -- Effects browser -----------------------------------------------------

    @property
    def effects_browser_active(self) -> bool:
        """Return whether the effects browser modal is open."""
        return self._effects_browser_active

    def _effects_browser_entries(self) -> list[dict[str, object]]:
        """Build browser rows from the shared registry catalog helper."""
        from unicornviz.effects.registry import browser_entries

        return [
            {
                'display_name': e.name,
                'category_key': e.category,
                'pack_name': e.pack,
                'tags': list(e.tags),
                'cls': e.cls,
                'enabled': self.effect_enabled(e.name),
            }
            for e in browser_entries()
        ]

    def open_effects_browser(self) -> None:
        """Open the effects browser and select the current effect."""
        o = self._overlays
        current = self.current_effect_name
        o.set_effects_browser_entries(self._effects_browser_entries(), current)
        b = o.effects_browser
        b.set_search_mode(False)
        b.clear_search_query()
        b.set_category_index(0)
        for i, row in enumerate(b.filtered()):
            if row.get('display_name') == current:
                b.set_selected_index(i)
                break
        o.set_effects_browser_pinned(self._effect_lock or '')
        self._eb_last_nav_monotonic = 0.0
        if not o.effects_browser_visible:
            o.toggle_effects_browser()
        self._effects_browser_active = True
        self._eb_rebuild_thumb()  # build the initial preview immediately

    def close_effects_browser(self, commit: bool) -> None:
        """Close the browser. The active effect is untouched by preview, so
        closing only tears down the thumbnail and modal state (``commit`` is
        accepted for call-site symmetry with the commit/pin actions)."""
        del commit  # preview never changed the active effect; nothing to revert
        o = self._overlays
        if o.effects_browser_visible:
            o.toggle_effects_browser()
        b = o.effects_browser
        b.set_search_mode(False)
        b.clear_search_query()
        self._effects_browser_active = False
        self._eb_last_nav_monotonic = 0.0
        self._eb_destroy_thumb_effect()
        o.set_effects_browser_thumbnail(None)

    def effects_browser_mark_nav(self) -> None:
        """(Re)arm the debounced thumbnail rebuild after any navigation."""
        self._eb_last_nav_monotonic = time.monotonic()

    def effects_browser_commit(self) -> str | None:
        """Switch to the selected effect and close. Returns its display NAME."""
        entry = self._overlays.effects_browser.selected_entry()
        if entry is None:
            self.close_effects_browser(commit=True)
            return None
        cls = entry.get('cls')
        name = str(entry.get('display_name', ''))
        if cls is not None and type(self._current_effect) is not cls:
            self._switch_effect(cls)  # type: ignore[arg-type]
        self.close_effects_browser(commit=True)
        return name

    def effects_browser_pin(self) -> str | None:
        """Toggle pinning the selected effect. Pinning switches to it and locks
        the system there; pinning the already-pinned effect unpins it. The
        browser stays open so pins can be managed while browsing."""
        entry = self._overlays.effects_browser.selected_entry()
        if entry is None:
            return None
        cls = entry.get('cls')
        name = str(entry.get('display_name', ''))
        if self._effect_lock == name:
            self.unlock_effect()
            self._overlays.set_effects_browser_pinned('')
            return f'{name}: unpinned'
        # Clear any existing lock first so the switch to the new pin target is
        # not blocked by the old lock, then switch and lock onto the new effect.
        self._effect_lock = None
        if cls is not None and type(self._current_effect) is not cls:
            self._switch_effect(cls)  # type: ignore[arg-type]
        self._effect_lock = name
        self._overlays.set_effects_browser_pinned(name)
        return f'{name}: pinned'

    def effects_browser_toggle_enabled(self) -> str | None:
        """Toggle the selected effect's rotation-enabled state and persist it."""
        entry = self._overlays.effects_browser.selected_entry()
        if entry is None:
            return None
        name = str(entry.get('display_name', ''))
        new_enabled = not bool(entry.get('enabled', True))
        entry['enabled'] = new_enabled  # live update in the shared model dict
        self.set_effect_enabled(name, new_enabled)
        return f'{name}: {"enabled" if new_enabled else "disabled"}'

    def tick_effects_browser_preview(self) -> None:
        """Debounced thumbnail rebuild: after ~250 ms idle on a new selection,
        (re)instantiate the selected effect into the preview FBO. The active
        on-screen effect is never changed."""
        if not self._effects_browser_active or self._eb_last_nav_monotonic <= 0.0:
            return
        if (time.monotonic() - self._eb_last_nav_monotonic) < 0.25:
            return
        self._eb_last_nav_monotonic = 0.0
        self._eb_rebuild_thumb()

    # -- Effects browser thumbnail preview (offscreen FBO) -------------------

    def _ensure_eb_thumb_fbo(self) -> moderngl.Framebuffer:
        """Lazily allocate the small offscreen FBO used for effect previews."""
        if self._eb_thumb_fbo is None:
            tex = self._ctx.texture((_EB_THUMB_W, _EB_THUMB_H), 4)
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self._eb_thumb_fbo = self._ctx.framebuffer(color_attachments=[tex])
        return self._eb_thumb_fbo

    def _eb_destroy_thumb_effect(self) -> None:
        """Release the current preview effect instance, if any."""
        if self._eb_thumb_effect is not None:
            try:
                self._eb_thumb_effect.destroy()
            except Exception:
                log.debug('Effects browser thumbnail destroy failed', exc_info=True)
            self._eb_thumb_effect = None
        self._eb_thumb_name = ''

    def _eb_rebuild_thumb(self) -> None:
        """Instantiate the selected effect at thumbnail size for live preview."""
        if not self._effects_browser_active:
            return
        entry = self._overlays.effects_browser.selected_entry()
        if entry is None:
            self._eb_destroy_thumb_effect()
            return
        name = str(entry.get('display_name', ''))
        if name == self._eb_thumb_name and self._eb_thumb_effect is not None:
            return
        cls = entry.get('cls')
        self._eb_destroy_thumb_effect()
        if cls is None:
            return
        try:
            self._eb_thumb_effect = self._instantiate(cls, _EB_THUMB_W, _EB_THUMB_H)  # type: ignore[arg-type]
            self._eb_thumb_name = name
        except Exception:
            log.debug('Effects browser thumbnail init failed for %s', name, exc_info=True)
            self._eb_thumb_effect = None
            self._eb_thumb_name = ''

    def render_effects_browser_thumbnail(self, dt: float) -> None:
        """Update+render the preview effect into its offscreen FBO and hand the
        texture to the overlay. Restores the default framebuffer before return
        so the overlay pass draws to the screen as usual."""
        if not self._effects_browser_active or self._eb_thumb_effect is None:
            self._overlays.set_effects_browser_thumbnail(None)
            return
        fbo = self._ensure_eb_thumb_fbo()
        audio = self._audio or AudioData()
        try:
            self._eb_thumb_effect.update(dt, audio)
            fbo.use()
            self._ctx.viewport = (0, 0, _EB_THUMB_W, _EB_THUMB_H)
            self._ctx.clear(0.02, 0.02, 0.05, 1.0)
            self._eb_thumb_effect.render()
            self._overlays.set_effects_browser_thumbnail(fbo.color_attachments[0])
        except Exception:
            log.debug('Effects browser thumbnail render failed', exc_info=True)
            self._eb_destroy_thumb_effect()
            self._overlays.set_effects_browser_thumbnail(None)
        finally:
            self._ctx.screen.use()
            self._ctx.viewport = (0, 0, int(self._width), int(self._height))

    def toggle_projectm_only(self) -> tuple[bool, str]:
        """Toggle ProjectM-only mode. On: switch to ProjectM and lock there.
        Off: unlock and advance to the next effect immediately."""
        if self._effect_lock is not None:
            self._effect_lock = None
            self._demo_timer = 0.0
            if self._playlist is not None:
                self._switch_effect(self._playlist.advance())
            return False, 'ProjectM-only OFF'
        cls = self.vj_api.find_effect('ProjectMEffect', 'ProjectM Presets')
        if cls is None:
            return False, 'ProjectM not available'
        self._switch_effect(cls)
        self._effect_lock = 'ProjectM Presets'
        return True, 'ProjectM-only ON'

    def _mark_user_action(self, kind: str = 'generic') -> None:
        """Mark recent user input so automation can temporarily yield control."""
        _ = kind
        grace = float(self.cfg.get('auto_vj', 'manual_grace_s', default=8.0))
        self._user_action_deadline = time.monotonic() + max(0.0, grace)

    def adjust_advance_interval(self, delta: float) -> float:
        """Adjust the auto-advance interval by delta seconds. Returns new value."""
        self._effect_duration = max(10.0, self._effect_duration + delta)
        return self._effect_duration

    def reset_advance_interval(self) -> float:
        """Reset the auto-advance interval to the configured value. Returns that value."""
        self._effect_duration = float(
            self.cfg.get('demo', 'effect_duration', default=20)
        )
        return self._effect_duration

    def toggle_invert(self) -> bool:
        """Toggle color inversion for the active effect frame only."""
        self._invert_colors = not self._invert_colors
        return self._invert_colors

    def goto_next_webcam_effect(self) -> str | None:
        """Advance to next camera treatment. Returns treatment name or None."""
        if self._webcam_system is None:
            return None
        result = self._webcam_system.next_treatment()
        self._persist_webcam_runtime_state()
        return result

    def goto_prev_webcam_effect(self) -> str | None:
        """Step back to previous camera treatment. Returns treatment name or None."""
        if self._webcam_system is None:
            return None
        result = self._webcam_system.prev_treatment()
        self._persist_webcam_runtime_state()
        return result

    def goto_next_camera(self) -> str | None:
        """Switch to the next camera device. Returns device label or None."""
        if self._webcam_system is None:
            return None
        result = self._webcam_system.next_camera()
        if result is not None:
            self._persist_webcam_runtime_state()
        return result

    def goto_prev_camera(self) -> str | None:
        """Switch to the previous camera device. Returns device label or None."""
        if self._webcam_system is None:
            return None
        result = self._webcam_system.prev_camera()
        if result is not None:
            self._persist_webcam_runtime_state()
        return result

    def list_webcam_cameras(self) -> list[dict[str, object]]:
        """Return detected webcam devices with enabled/selected metadata."""
        if self._webcam_system is None:
            return []
        return list(self._webcam_system.list_cameras())

    def rediscover_webcam_cameras(self) -> list[dict[str, object]]:
        """Re-scan webcam devices and return refreshed device metadata."""
        if self._webcam_system is None:
            return []
        self._webcam_system.rediscover_cameras()
        self._persist_webcam_runtime_state()
        return list(self._webcam_system.list_cameras())

    def set_webcam_camera_enabled(self, camera_id: int, enabled: bool) -> bool:
        """Enable or disable a webcam device by numeric camera index."""
        if self._webcam_system is None:
            return False
        ok = bool(self._webcam_system.set_camera_enabled(camera_id, enabled))
        if ok:
            self._persist_webcam_runtime_state()
        return ok

    def set_active_webcam_camera(self, camera_id: int) -> str | None:
        """Switch directly to a webcam device by numeric camera index."""
        if self._webcam_system is None:
            return None
        result = self._webcam_system.set_active_camera(camera_id)
        if result is not None:
            self._persist_webcam_runtime_state()
        return result

    def set_webcam_brightness(self, value: float) -> float:
        """Set webcam software brightness multiplier and return clamped value."""
        if self._webcam_system is None:
            return 0.0
        result = float(self._webcam_system.set_brightness(value))
        self._persist_webcam_runtime_state()
        return result

    def set_webcam_contrast(self, value: float) -> float:
        """Set webcam software contrast multiplier and return clamped value."""
        if self._webcam_system is None:
            return 0.0
        result = float(self._webcam_system.set_contrast(value))
        self._persist_webcam_runtime_state()
        return result

    def adjust_webcam_brightness(self, delta: float) -> float:
        """Adjust webcam software brightness by delta and return new value."""
        if self._webcam_system is None:
            return 0.0
        result = float(self._webcam_system.adjust_brightness(delta))
        self._persist_webcam_runtime_state()
        return result

    def adjust_webcam_contrast(self, delta: float) -> float:
        """Adjust webcam software contrast by delta and return new value."""
        if self._webcam_system is None:
            return 0.0
        result = float(self._webcam_system.adjust_contrast(delta))
        self._persist_webcam_runtime_state()
        return result

    def set_webcam_flip_horizontal(self, enabled: bool) -> bool:
        """Enable or disable horizontal mirror flip for webcam frames."""
        if self._webcam_system is None:
            return False
        result = bool(self._webcam_system.set_flip_horizontal(enabled))
        self._persist_webcam_runtime_state()
        return result

    def set_webcam_flip_vertical(self, enabled: bool) -> bool:
        """Enable or disable vertical flip for webcam frames."""
        if self._webcam_system is None:
            return False
        result = bool(self._webcam_system.set_flip_vertical(enabled))
        self._persist_webcam_runtime_state()
        return result

    def toggle_webcam_flip_horizontal(self) -> bool:
        """Toggle horizontal mirror flip for webcam frames."""
        if self._webcam_system is None:
            return False
        result = bool(self._webcam_system.toggle_flip_horizontal())
        self._persist_webcam_runtime_state()
        return result

    def toggle_webcam_flip_vertical(self) -> bool:
        """Toggle vertical flip for webcam frames."""
        if self._webcam_system is None:
            return False
        result = bool(self._webcam_system.toggle_flip_vertical())
        self._persist_webcam_runtime_state()
        return result

    def webcam_flip_state(self) -> dict[str, bool]:
        """Return webcam horizontal/vertical flip state."""
        if self._webcam_system is None:
            return {'horizontal': False, 'vertical': False}
        return dict(self._webcam_system.webcam_flip_state())

    def webcam_image_state(self) -> dict[str, float | bool]:
        """Return webcam image controls (brightness/contrast/flip) state."""
        if self._webcam_system is None:
            return {
                'brightness': 0.0,
                'contrast': 0.0,
                'flip_horizontal': False,
                'flip_vertical': False,
            }
        return dict(self._webcam_system.webcam_image_state())

    def toggle_webcam_auto_cycle(self) -> bool:
        """Toggle auto-cycling camera treatments. Returns the new on/off state."""
        if self._webcam_system is None:
            return False
        result = self._webcam_system.toggle_auto_cycle()
        self._persist_webcam_runtime_state()
        return result

    def scale_pip(self, delta: float) -> float:
        """Adjust webcam PiP scale. Returns new value, or 0 if unavailable."""
        if self._webcam_system is None:
            return 0.0
        result = self._webcam_system.scale_pip(delta)
        self._persist_webcam_runtime_state()
        return result

    def set_camera_layout(self, layout: str) -> bool:
        """Set webcam PiP position. Returns True when the system is available."""
        if self._webcam_system is None:
            return False
        self._webcam_system.set_layout(layout)
        self._persist_webcam_runtime_state()
        return True

    @property
    def paused(self) -> bool:
        return self._paused
