"""
Main application — SDL2 window (Wayland-first) + moderngl context + main loop.
"""
from __future__ import annotations

import logging
import math
import os
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
from unicornviz.effects.ansi_viewer import ANSIViewer
from unicornviz.effects.base import AudioData, BaseEffect
from unicornviz.effects.registry import get_effects
from unicornviz.audio.manager import AudioManager
from unicornviz.playlist import Playlist
from unicornviz.overlays import Overlays
from unicornviz.hotkeys import HotkeyHandler
from unicornviz.midi import MidiManager
from unicornviz.recording import Recorder
from unicornviz.dropins import load_dropin_symbol, discover_dropin_help_entries
from unicornviz.vj_api import VJApi
from unicornviz.keystroke_log import KeystrokeLogger

log = logging.getLogger(__name__)

TARGET_FPS = 60
FRAME_TIME = 1.0 / TARGET_FPS
_SPLASH_TOTAL_DURATION = 7.0  # 1s static + 6s animated
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


class _NullMultiHeadController:
    """Safe fallback when the multi-head drop-in is unavailable."""

    requested_mode = 'single'

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    def log_video_displays(self, width: int, height: int) -> int:
        try:
            return max(1, int(sdl2.SDL_GetNumVideoDisplays()))
        except Exception:
            return 1

    def resolve_display_mode(self) -> str:
        return 'single'

    def resolve_display_index(self, width: int, height: int) -> int:
        return 0

    def display_bounds(self, display_index: int, width: int, height: int) -> sdl2.SDL_Rect | None:
        return None

    def all_display_bounds(self, width: int, height: int) -> tuple[int, int, int, int]:
        return 0, 0, int(width), int(height)

    def window_position_for_display(self, display_index: int, width: int, height: int) -> tuple[int, int]:
        return sdl2.SDL_WINDOWPOS_CENTERED, sdl2.SDL_WINDOWPOS_CENTERED

    def move_window_to_display(self, window, width: int, height: int) -> None:
        return

    def destroy_mirror_outputs(self) -> None:
        return

    def create_mirror_outputs(self, title: str, width: int, height: int) -> None:
        return

    def resize_mirror_textures(self, width: int, height: int) -> None:
        return

    def present_mirror_outputs(self, frame_bytes: bytes, width: int, height: int) -> None:
        return

    def is_mirror_window_id(self, window_id: int) -> bool:
        return False

    def rebuild_multihead_outputs(self, width: int, height: int, title: str, fullscreen: bool) -> int:
        return 0

    def release_readback_pbos(self) -> None:
        return

    def ensure_readback_pbos(self, ctx: moderngl.Context, size: int) -> None:
        return

    def read_shared_frame(self, ctx: moderngl.Context, width: int, height: int) -> bytes:
        return b''

    def has_mirror_outputs(self) -> bool:
        return False


class _NullScreenBurstController:
    """Safe fallback when burst controller drop-in is unavailable."""

    def __init__(self, cfg: dict | None = None) -> None:
        self._cfg = cfg or {}

    @property
    def active(self) -> bool:
        return False

    def trigger(self) -> None:
        return

    def step(self, dt: float) -> None:
        return

    def transform(self) -> tuple[float, float]:
        return 1.0, 0.0


class _NullWebcamSystem:
    """Safe fallback when webcam overlay drop-in is unavailable."""

    def __init__(self, ctx: moderngl.Context, width: int, height: int, cfg: dict | None = None) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._cfg = cfg or {}

    def start(self) -> None:
        return

    def render(self, dt: float, bass: float, treble: float) -> None:
        return

    def destroy(self) -> None:
        return

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def next_treatment(self) -> str | None:
        return None

    def prev_treatment(self) -> str | None:
        return None

    def toggle_auto_cycle(self) -> bool:
        return False

    def scale_pip(self, delta: float) -> float:
        return 0.0

    def set_layout(self, layout: str) -> None:
        return


class _NullRTMPStreamer:
    """Safe fallback when streaming drop-in is unavailable."""

    def __init__(self, cfg: dict, width: int, height: int) -> None:
        self.enabled = False
        self.auto_start = False
        self._last_error = 'Streaming subsystem unavailable'

    @property
    def is_streaming(self) -> bool:
        return False

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def destination_label(self) -> str:
        return '-'

    def start(self) -> bool:
        return False

    def write_frame(self, frame: bytes) -> bool:
        return False

    def stop(self) -> None:
        return

    def resize(self, width: int, height: int) -> None:
        return

    def set_provider(self, provider: str, restart: bool = True) -> str:
        return 'unavailable'


class _NullPostFxController:
    """Safe fallback when post-fx drop-in is unavailable."""

    enabled = False

    def __init__(self, ctx: moderngl.Context, width: int, height: int, cfg: dict | None = None) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._cfg = cfg or {}

    @property
    def is_hue_active(self) -> bool:
        return False

    @property
    def is_rotation_active(self) -> bool:
        return False

    @property
    def active_name(self) -> str:
        return 'N/A'

    def is_active(self) -> bool:
        return False

    def select_slot(self, slot: int) -> str:
        return 'Post FX: unavailable'

    def on_scroll(self, dy: int) -> None:
        return

    def on_ctrl_scroll(self, dy: int) -> None:
        return

    def on_ctrl_scroll_degrees(self, degrees: float) -> None:
        return

    def clear_hue_shift(self) -> None:
        return

    def clear_scroll_fx(self) -> None:
        return

    def apply(
        self,
        src_tex: moderngl.Texture,
        dst_fbo: moderngl.Framebuffer,
        dt: float,
        bass: float,
        mid: float,
        treble: float,
        beat: float,
    ) -> bool:
        return False

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def destroy(self) -> None:
        return


def _clamp_render_scale(value: float) -> float:
    """Clamp internal render scale to a sane range."""
    return max(0.5, min(1.0, value))


def _load_multihead_controller_class() -> type:
    """Load MultiHeadController directly from the multi-head drop-in."""
    try:
        return load_dropin_symbol('multi-head-01/multihead.py', 'MultiHeadController')
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
        return load_dropin_symbol('postfx-01/postfx_controller.py', 'PostFxController')
    except Exception as exc:
        log.warning('PostFxController not available: %s', exc)
        return _NullPostFxController


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


def _load_grand_finale_class() -> type:
    """Load GrandFinaleController from the grand-finale-01 drop-in."""
    return load_dropin_symbol(
        'grand-finale-01/grand_finale.py',
        'GrandFinaleController',
    )


def _load_control_room_controller_class() -> type:
    """Load ControlRoomController from the control-room drop-in."""
    return load_dropin_symbol(
        'control-room-01/control_room.py',
        'ControlRoomController',
    )


class App:
    def __init__(self, config_path: str | Config = "config.toml") -> None:
        self.cfg = config_path if isinstance(config_path, Config) else Config(config_path)
        self._running = False
        self._paused = False
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
        self._dancing_unicorn = None
        self._rainbow_nova = None
        self._candy_frame = None
        self._auto_vj = None
        self._grand_finale = None
        self._control_room = None
        self._control_room_startup_cfg: dict[str, Any] | None = None
        self._control_room_startup_frames_remaining: int = 0
        self._streamer = None
        self._playlist: Playlist | None = None
        self._subsystems: dict[str, Any] = {}
        self._claimed_window_handlers: dict[int, Callable[[Any], None]] = {}
        self._frame_capture_bytes: bytes | None = None
        self._frame_capture_width: int = 0
        self._frame_capture_height: int = 0
        self._frame_capture_components: int = 0
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
        self._audio_manager: AudioManager | None = None
        self._midi_manager: MidiManager | None = None
        self._overlays: Overlays | None = None
        self._recorder: Recorder | None = None
        self._audio_scratch_current = AudioData()
        self._audio_scratch_next = AudioData()
        self._splash_config: dict | None = None
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
        self._display_index = 0
        self._display_mode = 'single'
        multihead_cls = _load_multihead_controller_class()
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

    def _set_multihead_mode(self, mode: str) -> None:
        """Update drop-in internal mode fields when available."""
        if hasattr(self._multihead, '_display_mode_requested'):
            setattr(self._multihead, '_display_mode_requested', mode)
        if hasattr(self._multihead, '_display_mode'):
            setattr(self._multihead, '_display_mode', mode)

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

    def _subsystems_need_frame_capture(self) -> bool:
        """Return True when any registered subsystem wants preview-frame bytes."""
        return any(bool(getattr(subsystem, 'needs_frame_bytes', False)) for subsystem in self._subsystems.values())

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
        if self._control_room is not None and bool(getattr(self._control_room, 'is_open', False)):
            return True, 'Control Room already open'
        # Garbage-collect any orphaned controller that's pending shutdown but
        # whose update() hasn't run yet (e.g. rapid toggle while ESC-close is
        # still queued).  Otherwise we'd leak the old SDL window.
        if self._control_room is not None and getattr(self._control_room, '_pending_shutdown', False):
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
        try:
            control_room_cls = _load_control_room_controller_class()
            self._control_room = control_room_cls(self, control_room_cfg)
            self.vj_api.register_subsystem('control_room', self._control_room)
            self.rebind_main_gl_context()
            log.info('ControlRoomController loaded from drop-in')
            return True, f'Control Room open on display {getattr(self._control_room, "_display_index", "?")}'
        except Exception as exc:
            self._control_room = None
            log.warning('ControlRoomController not available: %s', exc)
            return False, f'Control Room unavailable: {exc}'

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
        self.unregister_subsystem('control_room')
        self._control_room = None
        self.rebind_main_gl_context()
        return False, 'Control Room closed'

    def toggle_control_room(self) -> tuple[bool, str]:
        """Toggle the operator control-room window on or off."""
        if self._control_room is not None and bool(getattr(self._control_room, 'is_open', False)):
            return self._destroy_control_room()
        return self._create_control_room()

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

    def _primary_display_viewport(self) -> tuple[int, int, int, int] | None:
        """Return window-local viewport for the primary display in multi-display modes."""
        if self._display_mode not in {'mirror_all', 'span_all'}:
            return None
        bounds = self._display_bounds(self._display_index)
        if bounds is not None:
            px, py, pw, ph = int(bounds.x), int(bounds.y), int(bounds.w), int(bounds.h)
        else:
            # Fallback to first active layout if display index is unavailable.
            layouts = self._multihead_layouts()
            if not layouts:
                return None
            px, py, pw, ph = layouts[0]
        # Use the actual SDL window origin rather than cached layout origins.
        # This avoids drift when compositor/window-manager placement differs.
        wx = ctypes.c_int(0)
        wy = ctypes.c_int(0)
        sdl2.SDL_GetWindowPosition(self._window, wx, wy)
        origin_x = int(wx.value)
        origin_y = int(wy.value)
        return (px - origin_x, py - origin_y, pw, ph)

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
        if self._display_mode == 'span_all':
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

    def _release_readback_pbos(self) -> None:
        self._multihead.release_readback_pbos()

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
        if self._display_mode in ('span_all', 'mirror_all') and self._fullscreen:
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
        if self._display_mode == 'span_all':
            x_pos, y_pos, self._width, self._height = self._all_display_bounds()
            self._window_width = self._width
            self._window_height = self._height
        elif self._display_mode == 'mirror_all':
            x_pos, y_pos, win_w, win_h = self._all_display_bounds()
            # Logical canvas: prefer first display's dimensions for crisp 1:1
            # blits when displays share resolution. Falls back to configured size.
            layouts = self._multihead_layouts()
            if layouts:
                logical_w = layouts[0][2]
                logical_h = layouts[0][3]
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
        win_create_w = self._window_width if self._display_mode == 'mirror_all' else self._width
        win_create_h = self._window_height if self._display_mode == 'mirror_all' else self._height
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
        if self._display_mode == 'mirror_all':
            # Window size = spanned canvas; logical _width/_height stay at
            # single-display size for effects/HUD/FBO sizing.
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
        # Candy Frame neon border overlay (optional, from candy-frame drop-in).
        try:
            candy_cls = _load_candy_frame_class()
            candy_cfg = self.cfg.get('candy_frame', default={}) or {}
            if not isinstance(candy_cfg, dict):
                candy_cfg = {}
            self._candy_frame = candy_cls(self._ctx, self._width, self._height, candy_cfg)
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
        self._webcam_system.start()
        self._webcam_cycle_interval = float(cam_cfg.get('cycle_interval', 0)) or float(
            self.cfg.get('demo', 'effect_duration', default=20)
        )
        if isinstance(self._webcam_system, _NullWebcamSystem):
            self._webcam_system = None
        else:
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
            log.info('PostFxController loaded from drop-in')

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

    def toggle_current_effect_frame_scaling(self) -> str:
        """Toggle Candy Frame inner-viewport scaling for the active effect."""
        effect = self._current_effect
        if effect is None:
            return 'No active effect'
        if bool(getattr(effect, 'candy_frame_disallow', False)):
            return f'{effect.NAME}: Candy Frame disallowed by config'

        new_value = not bool(getattr(effect, 'scale_when_framed', False))
        effect.scale_when_framed = new_value
        return (
            f'{effect.NAME}: frame scaling ON'
            if new_value
            else f'{effect.NAME}: frame scaling OFF'
        )

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

    def _cursor_should_be_visible(self) -> bool:
        """Return effective cursor visibility from default setting and Ctrl hold."""
        return self._show_cursor_default or self._ctrl_held

    def _update_ctrl_state(self, sym: int, is_keydown: bool) -> None:
        if sym in (sdl2.SDLK_LCTRL, sdl2.SDLK_RCTRL):
            self._ctrl_held = is_keydown
            self._set_cursor_visible(self._cursor_should_be_visible())

    # ------------------------------------------------------------------ #
    # Effect management                                                    #
    # ------------------------------------------------------------------ #

    def _instantiate(self, cls: Type[BaseEffect]) -> BaseEffect:
        effect_cfg = self.cfg.get("effects", cls.__name__, default={})
        if not isinstance(effect_cfg, dict):
            effect_cfg = {}
        # Inject top-level [ansi] config into ANSIViewer so it finds the art dir
        if cls.__name__ == "ANSIViewer":
            ansi_dir = self.cfg.get(
                "ansi", "ansi_dir_auto",
                default=self.cfg.get("ansi", "ansi_dir", default="assets/ansi"),
            )
            effect_cfg = {"ansi_dir": str(ansi_dir), **effect_cfg}
        return cls(self._ctx, self._width, self._height, effect_cfg)

    def _switch_effect(self, cls: Type[BaseEffect]) -> None:
        """Begin transition to a new effect."""
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
        try:
            from unicornviz.splash import Splash
            config = self._splash_config
            def _splash_bass() -> float:
                audio = config["audio_manager"].get_audio_data()
                return float(audio.bass) if audio else 0.0
            
            splash = Splash(
                self._ctx,
                self._width,
                self._height,
                image_path=config["path"],
                duration=_SPLASH_TOTAL_DURATION,
                bass_supplier=_splash_bass,
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
        audio_manager = AudioManager(self.cfg)
        audio_manager.start()
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

        # Splash screen — shown before any effect loads
        splash_path = self.cfg.get("splash", "image", default="images/unicorn-viz-01.png")
        splash_duration_audio = _SPLASH_TOTAL_DURATION
        splash_duration_silent = _SPLASH_TOTAL_DURATION
        if Path(splash_path).exists():
            from unicornviz.splash import Splash

            def _splash_bass() -> float:
                return float(audio_manager.get_audio_data().bass)

            splash = Splash(
                self._ctx,
                self._width,
                self._height,
                image_path=splash_path,
                duration=_SPLASH_TOTAL_DURATION,
                bass_supplier=_splash_bass,
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

        midi_device_hint = self.cfg.get("midi", "device", default="")
        midi_manager = MidiManager(device_hint=midi_device_hint)
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

        playlist = Playlist(effects, self.cfg)
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
        )
        self._overlays = overlays
        overlays.set_effect_shortcuts(playlist.shortcut_effects)

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
        self._keystroke_logger = KeystrokeLogger(keystroke_log_enabled)

        hotkeys = HotkeyHandler(
            app=self,
            playlist=playlist,
            overlays=overlays,
            audio_manager=audio_manager,
        )
        hotkeys.attach_midi(midi_manager)

        # Auto VJ controller (optional drop-in), Phase 2 telemetry-only.
        try:
            auto_vj_cls = _load_auto_vj_controller_class()
            auto_vj_cfg = self.cfg.get('auto_vj', default={}) or {}
            if not isinstance(auto_vj_cfg, dict):
                auto_vj_cfg = {}
            self._auto_vj = auto_vj_cls(self, audio_manager, auto_vj_cfg)
            self.vj_api.set_status_pill(getattr(self._auto_vj, 'status_text', ''))
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

        # Load first effect
        self._current_effect = self._instantiate(playlist.current())
        self._recorder = Recorder(self.cfg, self._width, self._height)
        stream_cls = _load_rtmp_streamer_class()
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
            if self._streamer.start():
                log.info('RTMP streamer auto-started: %s', self._streamer.destination_label)
            else:
                log.warning('RTMP streamer auto-start failed: %s', self._streamer.last_error)
        else:
            log.info(
                'RTMP streamer loaded (enabled=%s auto_start=%s)',
                self._streamer.enabled,
                self._streamer.auto_start,
            )
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

        while self._running:
            now = time.perf_counter()
            dt = min(now - prev_time, 0.1)  # cap at 100 ms to avoid spiral
            prev_time = now

            # Poll events
            event = sdl2.SDL_Event()
            while sdl2.SDL_PollEvent(event):
                if self._dispatch_claimed_window_event(event):
                    continue
                if event.type == sdl2.SDL_QUIT:
                    self._running = False
                elif event.type == sdl2.SDL_KEYDOWN:
                    self._update_ctrl_state(event.key.keysym.sym, True)
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
                    if dy != 0 and self._postfx_controller is not None:
                        if self._ctrl_held:
                            self._postfx_controller.on_ctrl_scroll(dy)
                        else:
                            self._postfx_controller.on_scroll(dy)
                elif event.type == sdl2.SDL_MOUSEBUTTONDOWN:
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

            # Dispatch pending MIDI events to active effect
            if hasattr(self, "_midi_manager"):
                pass   # MidiManager uses a callback thread; forward via action hooks

            # Auto-playlist advance
            if not self._paused and self._next_effect is None and self._auto_advance:
                allow_advance = True
                if isinstance(self._current_effect, ANSIViewer):
                    allow_advance = self._current_effect.reached_bottom

                self._demo_timer += dt
                if self._demo_timer >= self._effect_duration and allow_advance:
                    self._demo_timer = 0.0
                    next_cls = playlist.advance()
                    log.info("Auto-advance → %s", next_cls.NAME)
                    self._switch_effect(next_cls)

            # Update audio
            self._audio = audio_manager.get_audio_data()
            self._audio_raw = audio_manager.get_audio_data_raw()

            if self._auto_vj is not None:
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

            if self._grand_finale is not None:
                try:
                    self._grand_finale.update(dt, self._audio)
                except Exception as exc:
                    log.warning('GrandFinaleController update failed: %s', exc)

            for name, subsystem in list(self._subsystems.items()):
                updater = getattr(subsystem, 'update', None)
                if not callable(updater):
                    continue
                try:
                    updater(dt, self._audio)
                except Exception as exc:
                    log.warning('%s subsystem update failed: %s', name, exc)

            # Update effects
            if not self._paused:
                if self._current_effect:
                    audio_cur = self._audio_for_effect(
                        self._audio,
                        self._current_effect,
                        self._audio_scratch_current,
                    )
                    self._current_effect.update(dt, audio_cur)
                if self._next_effect:
                    audio_next = self._audio_for_effect(
                        self._audio,
                        self._next_effect,
                        self._audio_scratch_next,
                    )
                    self._next_effect.update(dt, audio_next)

            # Keep persistent name overlay in sync with the active effect.
            # ANSIViewer shows the current art title; all other effects show NAME.
            if self._current_effect is not None:
                if isinstance(self._current_effect, ANSIViewer):
                    overlays._name_text = self._current_effect.current_title
                else:
                    current_label = getattr(self._current_effect, 'current_label', '')
                    if isinstance(current_label, str) and current_label:
                        overlays._name_text = _smart_trim_label(f"{self._current_effect.NAME} - {current_label}")
                    else:
                        overlays._name_text = self._current_effect.NAME

            # Feed modern TAB HUD with current runtime status.
            fps_now = (1.0 / dt) if dt > 0.0 else 0.0
            transition_name = self._transition_kind if self._next_effect is not None else 'none'
            transition_pct = f"{int(max(0.0, min(1.0, self._transition_t)) * 100)}%"
            audio_src = audio_manager.get_source_label() if audio_manager is not None else 'n/a'
            # Format reactive values: no trailing 'x', space before '*'
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
            rec_state = 'OFF'
            if self._recorder is not None and self._recorder.is_recording:
                rec_state = 'ON'
            stream_state = 'OFF'
            stream_provider = '-'
            if self._streamer is not None and self._streamer.is_streaming:
                stream_state = 'LIVE'
            if self._streamer is not None:
                stream_provider = str(getattr(self._streamer, 'provider', '-')).upper()
            advance_elapsed = max(0.0, self._demo_timer)
            advance_total = max(0.1, self._effect_duration)
            advance_time = f"{advance_elapsed:.1f}/{advance_total:.1f}s"
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
                'postfx': self._postfx_controller.active_name if self._postfx_controller is not None else 'N/A',
                'postfx_debug': (
                    self._postfx_controller.debug_summary
                    if self._postfx_controller is not None else 'N/A'
                ),
                'compose_debug': str(getattr(self, '_compose_debug', '-')),
                'bass': f"{self._audio_raw.bass:.2f}" if self._audio_raw is not None else '0.00',
                'mid': f"{self._audio_raw.mid:.2f}" if self._audio_raw is not None else '0.00',
                'treble': f"{self._audio_raw.treble:.2f}" if self._audio_raw is not None else '0.00',
                'bass_n': f"{self._audio_raw.bass_n:.2f}" if self._audio_raw is not None else '0.50',
                'mid_n': f"{self._audio_raw.mid_n:.2f}" if self._audio_raw is not None else '0.50',
                'treble_n': f"{self._audio_raw.treble_n:.2f}" if self._audio_raw is not None else '0.50',
                'audio_rms': (
                    f"{self._audio_manager.get_raw_input_rms():.4f}"
                    if self._audio_manager is not None else '0.0000'
                ),
                'display_mode': self._display_mode,
                'display_index': str(self._display_index),
                'invert': 'ON' if self._invert_colors else 'OFF',
                'vj_status': self._vj_status_pill,
            })
            self._playlist_mode = playlist.mode
            self._playlist_index = playlist.index
            self._playlist_size = len(playlist.effects)

            # Render
            self._render(dt)
            mirror_mode_active = (
                self._display_mode == 'mirror_all' and bool(self._mirror_rects)
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
                        self._fbo_a.use()
                        self._ctx.viewport = (0, 0, self._render_width, self._render_height)
                        self._fbo_b.color_attachments[0].use(location=0)
                        self._present_prog['tex'].value = 0
                        self._present_vao.render(moderngl.TRIANGLE_STRIP)
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
                    self._fbo_a.use()
                    self._ctx.viewport = (0, 0, self._render_width, self._render_height)
                    self._fbo_b.color_attachments[0].use(location=0)
                    self._present_prog['tex'].value = 0
                    self._present_vao.render(moderngl.TRIANGLE_STRIP)
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
                        self._fbo_a.use()
                        self._ctx.viewport = (0, 0, self._render_width, self._render_height)
                        self._fbo_b.color_attachments[0].use(location=0)
                        self._present_prog['tex'].value = 0
                        self._present_vao.render(moderngl.TRIANGLE_STRIP)
                    else:
                        self._ctx.screen.use()
                        self._ctx.viewport = (0, 0, self._width, self._height)
                        self._candy_frame.render(self._fbo_a.color_attachments[0])
            self._sync_recording_overlay()
            primary_overlay_view = self._primary_display_viewport()
            if mirror_mode_active:
                # Compose stage finished into _fbo_a; tile-blit first.
                self._present_mirror_tiled(self._fbo_a.color_attachments[0])
            if primary_overlay_view is not None:
                vx, vy, vw, vh = primary_overlay_view
                overlays.resize(vw, vh)
                self._ctx.screen.use()
                self._ctx.viewport = (vx, vy, vw, vh)
                overlays.render(dt, include_recording_indicator=False)
            else:
                overlays.resize(self._width, self._height)
                overlays.render(dt, include_recording_indicator=False)
            stream_frame: bytes | None = None
            need_frame_for_streaming = (
                self._streamer is not None and self._streamer.is_streaming
            )
            need_frame_for_subsystems = self._subsystems_need_frame_capture()
            if need_frame_for_streaming or need_frame_for_subsystems:
                try:
                    stream_frame = self._read_streaming_frame()
                except Exception as exc:
                    log.error('Streaming frame readback failed: %s', exc)
                    stream_frame = None
            if need_frame_for_subsystems:
                self._update_frame_capture_snapshot(stream_frame)
            else:
                self._update_frame_capture_snapshot(None)
            need_frame_for_recording = (
                self._recorder is not None and self._recorder.is_recording
            )
            need_frame_for_mirror = False  # legacy path; GL-native handles mirror.
            shared_frame: bytes | None = None
            if need_frame_for_recording or need_frame_for_mirror:
                try:
                    shared_frame = self._read_shared_frame()
                except Exception as exc:
                    log.error('Frame readback failed: %s', exc)
                    shared_frame = None
            if need_frame_for_recording and shared_frame is not None:
                self._write_recording_frame(shared_frame)
            if need_frame_for_streaming and stream_frame is not None:
                if not self._streamer.write_frame(stream_frame):
                    log.warning('RTMP streamer write failed: %s', self._streamer.last_error)
            if primary_overlay_view is not None:
                vx, vy, vw, vh = primary_overlay_view
                overlays.resize(vw, vh)
                self._ctx.screen.use()
                self._ctx.viewport = (vx, vy, vw, vh)
                overlays.render_live_recording_indicator()
            else:
                overlays.resize(self._width, self._height)
                overlays.render_live_recording_indicator()
            if need_frame_for_mirror and shared_frame is not None:
                self._present_mirror_outputs(shared_frame)

            sdl2.SDL_GL_SwapWindow(self._window)

            for name, subsystem in list(self._subsystems.items()):
                presenter = getattr(subsystem, 'present', None)
                if not callable(presenter):
                    continue
                try:
                    presenter()
                except Exception as exc:
                    log.warning('%s subsystem present failed: %s', name, exc)

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
        self._control_room = None
        if self._keystroke_logger is not None:
            self._keystroke_logger.close()
            self._keystroke_logger = None
        audio_manager.stop()
        midi_manager.stop()
        if self._webcam_system is not None:
            self._webcam_system.destroy()
            self._webcam_system = None
        if self._candy_frame is not None:
            self._candy_frame.destroy()
            self._candy_frame = None
        if self._postfx_controller is not None:
            self._postfx_controller.destroy()
            self._postfx_controller = None
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

        When Candy Frame is active and the effect opts in via
        ``scale_when_framed = true``, render inside the frame content area.
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
        """Return True when effect requests inner-frame scaling."""
        if effect is None:
            return False
        if bool(getattr(effect, 'candy_frame_disallow', False)):
            return False
        return bool(getattr(effect, 'scale_when_framed', False))

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

    def _render(self, dt: float) -> None:
        ctx = self._ctx
        mirror_mode = self._display_mode == 'mirror_all' and bool(self._mirror_rects)
        burst_active = self._burst_controller.active
        nova_active = self._rainbow_nova is not None and self._rainbow_nova.is_active
        candy_active = self._candy_frame is not None and bool(self._candy_frame.active)
        finale_overlay_active = (
            self._grand_finale is not None and self._grand_finale.overlay_active
        )
        postfx_active = (
            self._postfx_controller is not None and self._postfx_controller.is_active()
        )
        # Advance burst timer
        if burst_active:
            self._burst_controller.step(dt)
        if self._next_effect is None:
            # No transition — render current effect; optionally apply invert/burst pass.
            if mirror_mode or self._invert_colors or self._render_scale < 0.999 or burst_active or postfx_active or nova_active or candy_active or finale_overlay_active:
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
                        self._fbo_a.use()
                        ctx.viewport = (0, 0, self._render_width, self._render_height)
                        ctx.clear(0.0, 0.0, 0.0, 1.0)
                        self._fbo_b.color_attachments[0].use(location=0)
                        self._present_prog['tex'].value = 0
                        self._present_vao.render(moderngl.TRIANGLE_STRIP)
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
                        self._fbo_a.use()
                        ctx.viewport = (0, 0, self._render_width, self._render_height)
                        ctx.clear(0.0, 0.0, 0.0, 1.0)
                        self._fbo_b.color_attachments[0].use(location=0)
                        self._present_prog['tex'].value = 0
                        self._present_vao.render(moderngl.TRIANGLE_STRIP)
                    if postfx_active:
                        # Post FX into fbo_b, then copy back into fbo_a.
                        audio = self._audio or AudioData()
                        self._postfx_controller.apply(
                            self._fbo_a.color_attachments[0],
                            self._fbo_b,
                            dt,
                            float(audio.bass),
                            float(audio.mid),
                            float(audio.treble),
                            float(audio.beat),
                        )
                        self._fbo_a.use()
                        ctx.viewport = (0, 0, self._render_width, self._render_height)
                        ctx.clear(0.0, 0.0, 0.0, 1.0)
                        self._fbo_b.color_attachments[0].use(location=0)
                        self._present_prog['tex'].value = 0
                        self._present_vao.render(moderngl.TRIANGLE_STRIP)
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
                        self._fbo_a.use()
                        ctx.viewport = (0, 0, self._render_width, self._render_height)
                        ctx.clear(0.0, 0.0, 0.0, 1.0)
                        self._fbo_b.color_attachments[0].use(location=0)
                        self._present_prog['tex'].value = 0
                        self._present_vao.render(moderngl.TRIANGLE_STRIP)
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
                        self._fbo_a.use()
                        ctx.viewport = (0, 0, self._render_width, self._render_height)
                        ctx.clear(0.0, 0.0, 0.0, 1.0)
                        self._fbo_b.color_attachments[0].use(location=0)
                        self._present_prog['tex'].value = 0
                        self._present_vao.render(moderngl.TRIANGLE_STRIP)
                        self._present_from_tex(self._fbo_a.color_attachments[0])
                    else:
                        self._present_burst_from_tex(self._fbo_a.color_attachments[0])
                elif postfx_active:
                    audio = self._audio or AudioData()
                    self._postfx_controller.apply(
                        self._fbo_a.color_attachments[0],
                        self._fbo_b,
                        dt,
                        float(audio.bass),
                        float(audio.mid),
                        float(audio.treble),
                        float(audio.beat),
                    )
                    self._fbo_a.use()
                    ctx.viewport = (0, 0, self._render_width, self._render_height)
                    ctx.clear(0.0, 0.0, 0.0, 1.0)
                    self._fbo_b.color_attachments[0].use(location=0)
                    self._present_prog['tex'].value = 0
                    self._present_vao.render(moderngl.TRIANGLE_STRIP)
                    self._present_from_tex(self._fbo_b.color_attachments[0])
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
                if mirror_mode or self._render_scale < 0.999 or postfx_active or nova_active or candy_active or finale_overlay_active:
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
                    elif postfx_active:
                        audio = self._audio or AudioData()
                        self._postfx_controller.apply(
                            self._fbo_a.color_attachments[0],
                            self._fbo_b,
                            dt,
                            float(audio.bass),
                            float(audio.mid),
                            float(audio.treble),
                            float(audio.beat),
                        )
                        self._fbo_a.use()
                        ctx.viewport = (0, 0, self._render_width, self._render_height)
                        ctx.clear(0.0, 0.0, 0.0, 1.0)
                        self._fbo_b.color_attachments[0].use(location=0)
                        self._present_prog['tex'].value = 0
                        self._present_vao.render(moderngl.TRIANGLE_STRIP)
                        self._present_from_tex(self._fbo_b.color_attachments[0])
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
                if mirror_mode or postfx_active:
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
                elif postfx_active:
                    audio = self._audio or AudioData()
                    self._postfx_controller.apply(
                        self._fbo_a.color_attachments[0],
                        self._fbo_b,
                        dt,
                        float(audio.bass),
                        float(audio.mid),
                        float(audio.treble),
                        float(audio.beat),
                    )
                    self._fbo_a.use()
                    ctx.viewport = (0, 0, self._render_width, self._render_height)
                    ctx.clear(0.0, 0.0, 0.0, 1.0)
                    self._fbo_b.color_attachments[0].use(location=0)
                    self._present_prog['tex'].value = 0
                    self._present_vao.render(moderngl.TRIANGLE_STRIP)
                    self._present_from_tex(self._fbo_b.color_attachments[0])

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

    def _on_resize(self, w: int, h: int) -> None:
        if self._display_mode == 'mirror_all':
            # Window grew/shrunk; logical size stays at one display worth.
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
            if self._recorder and self._recorder.is_recording:
                self._recorder.stop()
                self._sync_recording_overlay()
                log.warning('Recording stopped due to resize/fullscreen change')
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
        if self._recorder and self._recorder.is_recording:
            self._recorder.stop()
            self._sync_recording_overlay()
            log.warning('Recording stopped due to resize/fullscreen change')
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
        if self._display_mode != 'mirror_all':
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
        if self._display_mode == 'span_all':
            sdl2.SDL_SetWindowBordered(
                self._window,
                sdl2.SDL_FALSE if self._fullscreen else sdl2.SDL_TRUE,
            )
            if self._fullscreen:
                x, y, w, h = self._all_display_bounds()
            else:
                x, y = self._window_position_for_display(self._display_index)
                w = int(self.cfg.get('window', 'width', default=1920))
                h = int(self.cfg.get('window', 'height', default=1080))
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

        Modes: single, span_all, mirror_all.
        """
        if reset_to_config:
            requested = str(self.cfg.get('window', 'display_mode', default='single')).lower()
            requested_index = int(self.cfg.get('window', 'display_index', default=0))
        else:
            requested = str(mode or self._display_mode).lower()
            requested_index = self._display_index

        allowed = {'single', 'span_all', 'mirror_all'}
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
            if self._display_mode == 'span_all':
                x, y, w, h = self._all_display_bounds()
                sdl2.SDL_SetWindowFullscreen(self._window, 0)
                sdl2.SDL_SetWindowBordered(self._window, sdl2.SDL_FALSE)
                sdl2.SDL_SetWindowPosition(self._window, x, y)
                sdl2.SDL_SetWindowSize(self._window, w, h)
            elif self._display_mode == 'mirror_all':
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
            if self._display_mode == 'span_all':
                x, y, w, h = self._all_display_bounds()
                sdl2.SDL_SetWindowPosition(self._window, x, y)
                sdl2.SDL_SetWindowSize(self._window, w, h)
            elif self._display_mode == 'mirror_all':
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
        if self._display_mode == 'mirror_all':
            # Switch logical canvas to first display's resolution and rebuild
            # mirror viewport rects against the new window origin.
            layouts = self._multihead_layouts()
            if layouts:
                self._width = layouts[0][2]
                self._height = layouts[0][3]
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

    def toggle_pause(self) -> None:
        self._paused = not self._paused

    @property
    def current_effect(self) -> BaseEffect | None:
        return self._current_effect

    @property
    def current_effect_name(self) -> str:
        return self._current_effect.NAME if self._current_effect is not None else ''

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

    def request_exit(self) -> None:
        self._running = False

    def midi_action_for_note(self, number: int) -> str | None:
        if self._midi_manager is None:
            return None
        return self._midi_manager.note_to_action(number)

    def midi_param_for_cc(self, number: int) -> str | None:
        if self._midi_manager is None:
            return None
        return self._midi_manager.cc_to_param(number)

    def select_postfx_slot(self, slot: int) -> str:
        """Select active post-process slot (0 disables)."""
        if self._postfx_controller is None:
            return 'Post FX: unavailable'
        return self._postfx_controller.select_slot(slot)

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
            frame = self._ctx.screen.read(components=3, alignment=1)
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
        """Read one RGB24 frame for RTMP streaming.

        In mirror mode this returns the logical composed frame (from `_fbo_a`)
        so we stream the unmodified single canvas, not the tiled multi-head
        desktop composition.
        """
        if self._ctx is None:
            return None
        mirror_mode_active = self._display_mode == 'mirror_all' and bool(self._mirror_rects)
        if mirror_mode_active and self._fbo_a is not None:
            return self._fbo_a.read(components=3, alignment=1)
        return self._ctx.screen.read(components=3, alignment=1)

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

    def _mark_user_action(self, kind: str = 'generic') -> None:
        """Mark recent user input so automation can temporarily yield control."""
        _ = kind
        grace = float(self.cfg.get('auto_vj', 'manual_grace_s', default=8.0))
        self._user_action_deadline = time.monotonic() + max(0.0, grace)

    def goto_ansi(self, ansi_dir: str) -> None:
        """Launch ANSIViewer with an explicit art directory."""
        # Invert does not carry through transitions.
        self._invert_colors = False
        if self._current_effect is not None:
            self._previous_effect_name = self._current_effect.NAME
        if self._next_effect is not None:
            self._next_effect.destroy()
        cfg_override = {"ansi_dir": ansi_dir}
        self._next_effect = ANSIViewer(self._ctx, self._width, self._height, cfg_override)
        self._transition_t = 0.0

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
        return self._webcam_system.next_treatment()

    def goto_prev_webcam_effect(self) -> str | None:
        """Step back to previous camera treatment. Returns treatment name or None."""
        if self._webcam_system is None:
            return None
        return self._webcam_system.prev_treatment()

    def toggle_webcam_auto_cycle(self) -> bool:
        """Toggle auto-cycling camera treatments. Returns the new on/off state."""
        if self._webcam_system is None:
            return False
        return self._webcam_system.toggle_auto_cycle()

    def scale_pip(self, delta: float) -> float:
        """Adjust webcam PiP scale. Returns new value, or 0 if unavailable."""
        if self._webcam_system is None:
            return 0.0
        return self._webcam_system.scale_pip(delta)

    def set_camera_layout(self, layout: str) -> bool:
        """Set webcam PiP position. Returns True when the system is available."""
        if self._webcam_system is None:
            return False
        self._webcam_system.set_layout(layout)
        return True

    @property
    def paused(self) -> bool:
        return self._paused
