"""
Main application — SDL2 window (Wayland-first) + moderngl context + main loop.
"""
from __future__ import annotations

import logging
import math
import os
import subprocess
import threading
import time
import ctypes
import sys
from datetime import datetime
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
from unicornviz.frame_tap import FrameTap
from unicornviz.audio.manager import AudioManager
from unicornviz.playlist import Playlist
from unicornviz.overlays import Overlays
from unicornviz.hotkeys import HotkeyHandler, parse_hotkey_chord
from unicornviz.midi import MidiManager, MidiOut
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
    discover_dropin_tour_slides,
    load_runtime_capability_class,
    register_runtime_capability,
    unregister_runtime_capability,
    BANNER_RUNTIME_CAPABILITY,
    CONTROL_ROOM_RUNTIME_CAPABILITY,
    MULTIHEAD_RUNTIME_CAPABILITY,
    POSTFX_RUNTIME_CAPABILITY,
)
from unicornviz.boot_profile import (
    PROFILE_MIXER,
    dropin_dir_matches_sections,
    mixer_allowed_sections,
    resolve_boot_profile,
)
from unicornviz.paths import APP_ROOT, resolve_path
from unicornviz.tour import (
    CORE_TOUR_SLIDES,
    STATE_LAST_SLIDE,
    STATE_SHOW_ON_STARTUP,
    TourSlide,
    clamp_slide_index,
    should_show_on_startup,
)
from unicornviz.runtime_state import RuntimeStateStore
from unicornviz.presets import ShowPresetStore
from unicornviz.config_profiles import ConfigProfileStore
from unicornviz.vj_api import VJApi

log = logging.getLogger(__name__)

TARGET_FPS = 60
FRAME_TIME = 1.0 / TARGET_FPS
# Budget-skip for secondary-window presents: when the previous frame ran over
# 1.5x the frame budget, skip _present_subsystems() this frame (secondary
# windows cost 15-56 ms per present on iGPUs) so the main canvas recovers
# first.  Capped so sustained overload still presents at ~TARGET_FPS/4.
_SUBSYS_PRESENT_SKIP_MS = FRAME_TIME * 1000.0 * 1.5
_SUBSYS_PRESENT_MAX_SKIPS = 3

# Effects browser live-preview thumbnail resolution (16:9).
_EB_THUMB_W = 480
_EB_THUMB_H = 270

# Maximum width of the downsampled subsystem-preview readback frame.  The
# control-room / dj-mixer preview panels render at a few hundred pixels wide,
# so reading the full canvas (24 MB at a 3840x2163 spanned canvas) just to
# shrink it again on the CPU wastes PCIe bandwidth and stalls the GL pipeline.
_PREVIEW_MAX_WIDTH = 960
# Historical default ceiling for the subsystem-preview glReadPixels throttle,
# used when no active consumer exposes its own ``preview_fps_cap``.
_DEFAULT_SUBSYSTEM_PREVIEW_FPS = 10.0
_SPLASH_TOTAL_DURATION = 3.0  # ~0.75s static + ~2.25s animated (splash.py phases)
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


class _StartupProfiler:
    """Records named startup checkpoints and logs their timings.

    One-shot, main-thread only. Used to find where boot time goes so the
    splash-overlap optimization targets measured hotspots rather than
    guesses. Each :meth:`mark` logs the delta since the previous mark and
    the total elapsed; :meth:`summary` dumps every phase sorted by cost.
    Always-on INFO — startup happens once and the volume is small.
    """

    __slots__ = ('_t0', '_last', '_marks')

    def __init__(self) -> None:
        now = time.perf_counter()
        self._t0 = now
        self._last = now
        self._marks: list[tuple[str, float]] = []

    def mark(self, label: str) -> None:
        """Record a checkpoint and log its delta + total-elapsed."""
        now = time.perf_counter()
        delta = now - self._last
        elapsed = now - self._t0
        self._last = now
        self._marks.append((label, delta))
        log.info(
            'Startup timing: %-30s +%7.1fms  (t=%6.2fs)',
            label, delta * 1000.0, elapsed,
        )

    def summary(self) -> None:
        """Log total boot time and every phase ranked by cost."""
        total = time.perf_counter() - self._t0
        ranked = sorted(self._marks, key=lambda m: m[1], reverse=True)
        log.info('Startup timing summary — total %.2fs, phases by cost:', total)
        for label, delta in ranked:
            ms = delta * 1000.0
            if ms < 1.0:
                continue
            pct = (100.0 * delta / total) if total > 0 else 0.0
            log.info('  %-30s %8.1fms  (%4.1f%%)', label, ms, pct)


def _smart_trim_label(text: str, limit: int = 56) -> str:
    """Trim long HUD labels without losing the start and end context."""
    if len(text) <= limit:
        return text
    head = max(20, int(limit * 0.58))
    tail = max(12, limit - head - 3)
    return f'{text[:head]}...{text[-tail:]}'


def _context_menu_label_from_help(desc: str) -> str:
    """Turn a drop-in help description into a concise context-menu label.

    Drops any trailing parenthetical hint (e.g. "... (lasts 3 s idle)") so the
    generated label stays short; the raw help text remains the source of truth.
    """
    text = str(desc).strip()
    if '(' in text:
        text = text.split('(', 1)[0].strip()
    return text or 'Action'


def _infer_param_range(value: float) -> tuple[float, float]:
    """Infer a sensible (min, max) slider range for a bare float parameter.

    Uses ~0.25x–4x the reference value; falls back to [0, 1] for zero.  Richer
    per-effect metadata (explicit ranges) is a planned additive follow-up.
    """
    v = float(value)
    if v == 0.0:
        return 0.0, 1.0
    lo, hi = sorted((v * 0.25, v * 4.0))
    return lo, hi


def _name_char_for_keysym(sym: int, mod: int) -> str:
    """Map an SDL keysym to a profile-name character (a-z, 0-9, space, - _)."""
    shift = bool(mod & sdl2.KMOD_SHIFT)
    if sdl2.SDLK_a <= sym <= sdl2.SDLK_z:
        ch = chr(sym)
        return ch.upper() if shift else ch
    if sdl2.SDLK_0 <= sym <= sdl2.SDLK_9 and not shift:
        return chr(sym)
    if sym == sdl2.SDLK_SPACE:
        return ' '
    if sym == sdl2.SDLK_MINUS:
        return '_' if shift else '-'
    return ''


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


def _load_video_out_controller_class() -> type:
    """Load VideoOutController directly from the video-out-01 drop-in."""
    return load_dropin_symbol(
        'video-out-01/video_out_controller.py', 'VideoOutController')


def _load_cta_controller_class() -> type:
    """Load CTAController from the cta-01 drop-in."""
    return load_dropin_symbol('cta-01/cta_controller.py', 'CTAController')


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


def _load_dj_mixer_controller_class() -> type:
    """Load DjMixerController from the dj-mixer-01 drop-in."""
    return load_dropin_symbol(
        'dj-mixer-01/dj_mixer_controller.py',
        'DjMixerController',
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


def _load_video_postfx_controller_class() -> type:
    """Load VideoPostFxController from the video-postfx-01 drop-in."""
    return load_dropin_symbol(
        'video-postfx-01/video_postfx_controller.py',
        'VideoPostFxController',
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
        # Boot profile (mixer-only mode): resolved exactly once, here — every
        # boot gate reads _boot_profile, never the raw config (see
        # unicornviz/boot_profile.py and the mixer-only plan doc).
        _dj_mixer_dropin = (
            APP_ROOT / 'drop-ins' / 'dj-mixer-01' / 'dj_mixer_controller.py'
        )
        self._boot_profile, _profile_notes = resolve_boot_profile(
            self.cfg, _dj_mixer_dropin.exists,
        )
        self._mixer_allow = mixer_allowed_sections(self.cfg)
        for _note in _profile_notes:
            log.error('Boot profile: %s', _note)
        if self._boot_profile == PROFILE_MIXER:
            log.info(
                'Boot profile: MIXER-ONLY (allowed sections: %s)',
                ', '.join(sorted(self._mixer_allow)),
            )
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
        # A pinned pair of effect instances held alive simultaneously for
        # hard-cut alternation (auto-vj-01's effect ping-pong) instead of a
        # full instantiate+destroy transition on every swap between the same
        # two effects -- see pin_effect_pair()/cut_to_pinned()/
        # unpin_effect_pair(). None when no pair is pinned.
        self._pinned_pair: dict[str, BaseEffect] | None = None
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
        self._video_postfx = None
        self._dancing_unicorn = None
        self._rainbow_nova = None
        self._unicorn_tears: Any = None
        self._candy_frame = None
        self._auto_vj = None
        self._spotify = None
        self._media: Any = None
        self._chat: Any = None
        self._audio_out = None
        self._dj_mixer: Any = None
        self._osc_bridge = None
        # Shared BPM hint bus: source -> (bpm, monotonic timestamp).  Lets
        # tempo-aware drop-ins (dj-mixer, auto-vj, ...) publish/read a tempo and
        # interact without depending on one another.
        self._bpm_hints: dict[str, tuple[float, float]] = {}
        # Shared song-structure hint bus: source -> (payload, monotonic
        # timestamp). Mirrors _bpm_hints -- lets a source that has
        # pre-analyzed a track (dj-mixer's structure.py) publish where the
        # playhead is in the song's phrase structure for phrase-aware
        # consumers (auto-vj) to read, without either depending on the
        # other. See docs/planning/auto-vj-phrase-structure-plan-2026-08-05.md
        # section 6.
        self._section_hints: dict[str, tuple[dict, float]] = {}
        # source -> (payload dict, monotonic timestamp). Mirrors
        # _section_hints exactly, one level up: sections say where you are
        # in a *track*, this says where you are in the *night* -- the set
        # clock / grand-finale timing dj-mixer-01 is the only source that
        # can know (it knows when the set ends; the director does not).
        # See docs/planning/auto-vj-phrase-structure-plan-2026-08-05.md
        # section 6.3.
        self._session_hints: dict[str, tuple[dict, float]] = {}
        # name -> callable(playlist_name, paths) -> accepted count.
        # Destinations a playlist can be handed to (see
        # register_playlist_sink); lets one drop-in send a set to
        # another without either importing the other.
        self._playlist_sinks: dict = {}
        self._lyrics = None
        self._grand_finale = None
        self._control_room = None
        self._control_room_creating: bool = False
        self._control_room_startup_cfg: dict[str, Any] | None = None
        self._control_room_startup_frames_remaining: int = 0
        self._streamer = None
        self._video_out: Any = None
        self._cta_controller = None
        self._playlist: Playlist | None = None
        self._subsystems: dict[str, Any] = {}
        self._claimed_window_handlers: dict[int, Callable[[Any], None]] = {}
        self._text_input_handlers: dict[str, Callable[[str], None]] = {}
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
            self.cfg.get('demo', 'effect_duration', default=60)
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
        # Consecutive _present_subsystems() skips under the frame-budget guard.
        self._subsys_present_skips: int = 0
        self._audio_manager: AudioManager | None = None
        self._midi_manager: MidiManager | None = None
        # Crash containment: per-class crash counts, the session quarantine
        # list, and the flag asking the main loop to advance off a crashed
        # current effect on the next frame.
        self._effect_crash_counts: dict[str, int] = {}
        self._effect_blocklist: set[str] = set()
        self._effect_crash_recover: bool = False
        self._shutdown_complete: bool = False
        self._midi_out: MidiOut | None = None
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
        # One GPU->CPU readback per frame, fanned out to recording /
        # streaming (and reused by the subsystem preview when present).
        self._frame_tap = FrameTap()
        # Most recent CPU-side output frame produced by the tap, reused by
        # screenshots so they don't pay for their own readback.
        self._last_output_frame: tuple[bytes, int, int] | None = None
        self._last_output_frame_t: float = -1e9
        self._stream_pbos: list[moderngl.Buffer] = []
        self._stream_pbo_size: int = 0
        self._stream_pbo_index: int = 0
        self._stream_pbo_primed: bool = False
        self._stream_pbo_frame_count: int = 0
        # If a driver/context cannot map PBOs reliably, permanently fall back
        # to direct read for the current session to avoid repeated map failures.
        self._stream_pbo_disabled: bool = False
        self._stream_viewport_mismatch_logged: bool = False
        # Reading self._ctx.screen directly via moderngl's Framebuffer.read()/
        # read_into() is broken: it unconditionally issues
        # glReadBuffer(GL_COLOR_ATTACHMENT0 + attachment), which is invalid
        # for the default framebuffer (framebuffer_obj == 0) per the GL spec.
        # moderngl's own context-init code carries a comment acknowledging
        # this exact issue for draw_buffers ("GL_COLOR_ATTACHMENT0 is causes
        # error: 1282") but the equivalent fix was never applied to the read
        # path. _screen_copy_fbo is a real FBO we blit the screen into via
        # copy_framebuffer() (which correctly uses the queried GL_BACK/FRONT
        # draw buffer) so reads never touch the default framebuffer directly.
        self._screen_copy_fbo: moderngl.Framebuffer | None = None
        # Small FBO the canvas is downsample-rendered into before the
        # subsystem-preview readback (see _read_preview_frame).  Capped at
        # _PREVIEW_MAX_WIDTH so the glReadPixels transfer stays tiny.
        self._preview_fbo: moderngl.Framebuffer | None = None
        self._width = self.cfg.get("window", "width", default=1920)
        self._height = self.cfg.get("window", "height", default=1080)
        # In mirror_all the SDL window spans all displays, while effects/HUD
        # keep rendering at single-display logical size. _window_width/_height
        # describe the actual SDL window framebuffer; _width/_height describe
        # the logical canvas that effects render into.
        self._window_width = self._width
        self._window_height = self._height
        self._display_refresh_last_t = 0.0
        self._window_origin_x = 0
        self._window_origin_y = 0
        self._mirror_rects: list[tuple[int, int, int, int]] = []
        self._primary_overlay_view_debug_last: tuple[int, int, int, int] | None = None
        self._display_index = 0
        self._display_mode = 'single'
        multihead_cls = (
            _NullMultiHeadController
            if self._safe_mode or not self._profile_allows('multi_head')
            else _load_multihead_controller_class()
        )
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
        # Delete-key deletions this session: (timestamp, effect name). Not
        # persisted across runs — reported as a summary at shutdown and
        # mirrored live to logs/deleted-effects_<stamp>.log when logging is on.
        self._deleted_effects_session: list[tuple[str, str]] = []
        self._deleted_effects_log_path: Path | None = self._compute_deleted_effects_log_path(self.cfg)
        # Shift+Delete undo stack for Delete-key deactivations, newest last:
        # ('effect', NAME) or ('preset', path). Session-only by design.
        self._disable_undo_stack: list[tuple[str, str]] = []
        # Numeric-hotkey slot pins: {slot_index (0-39): effect name} (persisted).
        self._hotkey_pins: dict[int, str] = {
            int(k): str(v)
            for k, v in (self._runtime_state.get('effects.hotkey_pins', {}) or {}).items()
        }
        # Rebound global-action hotkeys: {action_name: (sym, mod)} (persisted).
        # See HotkeyHandler / _ACTION_BINDINGS in hotkeys.py for the default
        # table and the translation layer that makes overrides take effect.
        self._hotkey_overrides: dict[str, tuple[int, int]] = {
            str(k): (int(v[0]), int(v[1]))
            for k, v in (self._runtime_state.get('hotkeys.overrides', {}) or {}).items()
            if isinstance(v, (list, tuple)) and len(v) == 2
        }
        preset_path = self.cfg.get('presets', 'path', default='runtime/presets.json')
        self._preset_store = ShowPresetStore(str(preset_path))
        # Configuration profiles (per-effect parameter overrides). Distinct from
        # show presets; see docs/planning/configuration-editor-plan.md.
        profile_path = self.cfg.get(
            'config_profiles', 'path', default='runtime/config_profiles.json'
        )
        self._config_profile_store = ConfigProfileStore(str(profile_path))
        # Live per-effect parameter overrides merged over config.toml at
        # instantiation: {ClassName: {param: value}}.
        self._effect_config_overrides: dict[str, dict[str, float]] = {}
        # Hosted mixer console (mixer-only profile): the texture its
        # frames are uploaded into, and the last frame id uploaded so a
        # frame the console has not redrawn is not re-sent.
        self._hosted_mixer_tex = None
        self._hosted_mixer_fid = -1
        self._config_editor_was_open = False
        # Now-playing announcement hub: sources (spotify/media/dj-mixer/...)
        # register snapshot callables; the render loop announces the audible
        # one (see unicornviz/now_playing.py).  Must exist before drop-ins load.
        from unicornviz.now_playing import NowPlayingHub
        from unicornviz.now_spinning import TrackStabilityFilter
        self.now_playing = NowPlayingHub()
        self._now_spinning = None
        self.now_spinning_enabled = bool(
            self.cfg.get('now_spinning', 'enabled', default=True))
        # Crossfade guard: the platter switches tracks only after the new
        # identity has been reported continuously for switch_hold_s.
        self._now_spinning_filter = TrackStabilityFilter(
            float(self.cfg.get('now_spinning', 'switch_hold_s', default=5.0)
                  or 0.0))
        self.vj_api = VJApi(self)
        self._render_scale_default: float = self._render_scale
        self._render_width = max(1, int(round(self._width * self._render_scale)))
        self._render_height = max(1, int(round(self._height * self._render_scale)))
        self._fullscreen = self.cfg.get("window", "fullscreen", default=True)
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

    # -- shared BPM hint bus (tempo interop between drop-ins) ----------------

    _BPM_HINT_TTL_S = 5.0

    def publish_bpm(self, source: str, bpm: float) -> None:
        """Publish a BPM estimate under *source* for other drop-ins to read."""
        try:
            value = float(bpm)
        except (TypeError, ValueError):
            return
        if value > 0.0 and str(source):
            self._bpm_hints[str(source)] = (value, time.monotonic())

    def get_bpm(self, exclude: str = '') -> float:
        """Return the freshest non-stale BPM hint from a source != *exclude*.

        Returns 0.0 when no usable hint exists.  Lets a drop-in fall back to
        another's tempo (e.g. the mixer borrowing auto-vj's) without coupling.
        """
        now = time.monotonic()
        best_bpm = 0.0
        best_t = -1.0
        for src, (bpm, ts) in self._bpm_hints.items():
            if src == exclude or (now - ts) > self._BPM_HINT_TTL_S:
                continue
            if ts > best_t:
                best_bpm, best_t = bpm, ts
        return best_bpm

    # -- shared song-structure hint bus (phrase interop between drop-ins) ----

    _SECTION_HINT_TTL_S = 5.0
    _SECTION_ROLES = ('HOLD', 'RISE', 'PEAK', 'FALL', 'CLOSE')

    def publish_section(self, source: str, payload: dict) -> None:
        """Publish a song-structure hint under *source* for other drop-ins.

        *payload* is the wire contract from
        docs/planning/auto-vj-phrase-structure-plan-2026-08-05.md section
        6.a (``structure.to_wire()`` in dj-mixer-01): at minimum ``role``
        (one of HOLD/RISE/PEAK/FALL/CLOSE), plus ``tier``/``label``/
        ``bars_in``/``bars_left``/``confidence`` when known. Malformed or
        unrecognized-role payloads are dropped rather than stored, so a
        consumer never has to re-validate what it reads back.
        """
        if not str(source) or not isinstance(payload, dict):
            return
        role = payload.get('role')
        if role not in self._SECTION_ROLES:
            return
        self._section_hints[str(source)] = (dict(payload), time.monotonic())

    def get_section(self, exclude: str = '') -> dict | None:
        """Return the freshest non-stale song-structure hint from a source
        != *exclude*, or None when no usable hint exists.

        Lets a phrase-aware consumer (auto-vj) prefer a source that has
        pre-analyzed the whole track (dj-mixer's structure detector) over
        its own live-only reasoning, without either depending on the other.
        """
        now = time.monotonic()
        best_payload: dict | None = None
        best_t = -1.0
        for src, (payload, ts) in self._section_hints.items():
            if src == exclude or (now - ts) > self._SECTION_HINT_TTL_S:
                continue
            if ts > best_t:
                best_payload, best_t = payload, ts
        return dict(best_payload) if best_payload is not None else None

    # -- shared set-clock hint bus (grand-finale interop between drop-ins) --

    _SESSION_HINT_TTL_S = 5.0
    _SESSION_PHASES = ('running', 'closing', 'final', 'over')

    def publish_session(self, source: str, payload: dict) -> None:
        """Publish a set-clock hint under *source* for other drop-ins.

        *payload* is the wire contract from
        docs/planning/auto-vj-phrase-structure-plan-2026-08-05.md section
        6.3 (dj-mixer-01's set clock): at minimum ``phase`` (one of
        running/closing/final/over), plus ``source`` (clock|last_track --
        a payload field, distinct from this method's *source* publisher-id
        parameter), ``seconds_left``/``minutes_left``, and finale-timing
        fields (``final_peak_s``/``final_peak_in_s``) when known.
        Malformed or unrecognized-phase payloads are dropped rather than
        stored, so a consumer never has to re-validate what it reads back.
        """
        if not str(source) or not isinstance(payload, dict):
            return
        phase = payload.get('phase')
        if phase not in self._SESSION_PHASES:
            return
        self._session_hints[str(source)] = (dict(payload), time.monotonic())

    def get_session(self, exclude: str = '') -> dict | None:
        """Return the freshest non-stale set-clock hint from a source !=
        *exclude*, or None when no usable hint exists.

        Lets a finale-aware consumer (auto-vj) know where it is in the
        *night* -- not just the current track -- without depending on the
        mixer directly. Same shape as get_section(); a different bus.
        """
        now = time.monotonic()
        best_payload: dict | None = None
        best_t = -1.0
        for src, (payload, ts) in self._session_hints.items():
            if src == exclude or (now - ts) > self._SESSION_HINT_TTL_S:
                continue
            if ts > best_t:
                best_payload, best_t = payload, ts
        return dict(best_payload) if best_payload is not None else None

    def register_playlist_sink(self, name: str, fn) -> None:
        """Register a destination that can receive a playlist from elsewhere.

        A *sink*, not a hint bus: exporting a playlist is a delivery that
        happens once and either works or does not, so unlike the BPM and
        section channels there is nothing to time out and nothing to poll.
        The receiver (media-01) registers here; the sender (dj-mixer-01) calls
        :meth:`export_playlist`, and neither imports the other -- which is the
        drop-in independence rule, and the reason this lives in core at all.

        *fn* takes ``(playlist_name, paths)`` and returns how many tracks it
        actually accepted, or raises.
        """
        if not str(name).strip() or not callable(fn):
            return
        self._playlist_sinks[str(name).strip()] = fn
        log.info('playlist sinks: registered %r', name)

    def unregister_playlist_sink(self, name: str) -> None:
        """Drop a sink (its drop-in went away)."""
        self._playlist_sinks.pop(str(name).strip(), None)

    def playlist_sinks(self) -> list[str]:
        """Names of every registered destination, for building a menu."""
        return sorted(self._playlist_sinks)

    def export_playlist(self, target: str, name: str, paths) -> tuple[bool, str]:
        """Send *paths* to a registered sink as a playlist called *name*.

        Returns ``(ok, message)`` rather than raising, because every caller is
        a UI action that has to say something to a person either way.  A
        missing sink is an ordinary outcome -- the receiving drop-in simply is
        not installed -- not an error worth a traceback.
        """
        fn = self._playlist_sinks.get(str(target).strip())
        if fn is None:
            return False, f'{target} is not available'
        rows = [str(p) for p in (paths or []) if p]
        if not rows:
            return False, 'nothing to send'
        try:
            took = fn(str(name), rows)
        except Exception as exc:
            log.warning('playlist sinks: %s refused %r: %s', target, name, exc)
            return False, f'{target} could not take it: {exc}'
        n = len(rows) if took is None else int(took)
        return True, f'sent {n} track(s) to {target} as "{name}"'

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

    def _profile_allows(self, section: str) -> bool:
        """Whether the boot profile permits loading a config section's drop-in.

        The full profile allows everything (each block still applies its own
        `enabled` flag); the mixer profile allows only the mixer plus the
        sections listed in `[dj_mixer] mixer_allow`.
        """
        if self._boot_profile != PROFILE_MIXER:
            return True
        return section in self._mixer_allow

    def _dropin_dir_filter(self) -> Callable[[str], bool] | None:
        """Scope for drop-in discovery scans (help entries, tour slides).

        The scans import every module they visit — the dominant mixer-boot
        cost — so the mixer profile restricts them to directories mapping to
        loadable sections. None (normal boot) scans everything.
        """
        if self._boot_profile != PROFILE_MIXER:
            return None
        allowed = self._mixer_allow
        return lambda dir_name: dropin_dir_matches_sections(dir_name, allowed)

    def claim_window_events(self, window_id: int, handler: Callable[[Any], None]) -> bool:
        """Route SDL events for a claimed window to a subsystem handler."""
        if int(window_id) <= 0 or handler is None:
            return False
        self._claimed_window_handlers[int(window_id)] = handler
        return True

    def release_window_events(self, window_id: int) -> None:
        """Release event ownership for a previously-claimed SDL window."""
        self._claimed_window_handlers.pop(int(window_id), None)

    def register_text_input_handler(self, name: str, fn: 'Callable[[str], None]') -> None:
        """Register a handler called for every SDL_TEXTINPUT event on the main window."""
        self._text_input_handlers[str(name)] = fn

    def unregister_text_input_handler(self, name: str) -> None:
        """Unregister a text-input handler registered via register_text_input_handler."""
        self._text_input_handlers.pop(str(name), None)

    def _apply_windows_dpi_hints(self) -> None:
        """Make the process per-monitor DPI-aware on Windows (no-op elsewhere).

        Without this, Windows renders the app at logical size and
        bitmap-stretches it on any display scaled above 100% — blurry
        text/icons, and window sizes reported in virtualized points (which
        also mis-picks the 76px-vs-152px help-icon bucket on scaled 4K).
        Must run before SDL_Init. The hint name is passed as a literal so
        older pysdl2 builds without the constant still work.
        """
        if sys.platform != 'win32':
            return
        try:
            sdl2.SDL_SetHint(b'SDL_WINDOWS_DPI_AWARENESS', b'permonitorv2')
        except Exception as exc:
            log.warning('Failed to set Windows DPI awareness hint: %s', exc)

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

    def _subsystem_preview_capture_interval_s(self) -> float:
        """Return the glReadPixels throttle interval for subsystem preview frames.

        A subsystem consuming frame bytes may expose ``preview_fps_cap`` (an
        int fps ceiling; omit or 0 to just take the default) alongside
        ``needs_frame_bytes``.  The fastest active request wins, so several
        simultaneous consumers all get frames at least as fresh as their own
        cap.  No subsystem opting in preserves the historical 10 fps default.
        """
        caps: list[float] = []
        for subsystem in self._subsystems.values():
            if not bool(getattr(subsystem, 'needs_frame_bytes', False)):
                continue
            cap = getattr(subsystem, 'preview_fps_cap', None)
            if isinstance(cap, (int, float)) and cap > 0:
                caps.append(float(cap))
        fps = max(caps) if caps else _DEFAULT_SUBSYSTEM_PREVIEW_FPS
        return 1.0 / max(1.0, fps)

    def _render_now_spinning(self, width: int, height: int) -> None:
        """The corner platter card (core Now Spinning overlay), fed by the
        now-playing hub — announces whichever source is audible."""
        if not self.now_spinning_enabled:
            return
        active = self.now_playing.active()
        if active is None or not active[1].get('is_playing'):
            self._now_spinning_filter.reset()
            return
        # A playing source that can't name its track yet (unknown metadata)
        # stays quiet — no platter until we know what's spinning.
        if not self.now_playing.is_identified(active[1]):
            self._now_spinning_filter.reset()
            return
        if self._ctx is None:          # GL not up yet: try again next frame
            return
        if self._now_spinning is None:
            try:
                from unicornviz.now_spinning import NowSpinningOverlay
                corner = str(self.cfg.get('now_spinning', 'corner',
                                          default='br') or 'br')
                self._now_spinning = NowSpinningOverlay(self._ctx, corner)
                log.info('Now Spinning overlay ready (%s corner)', corner)
            except Exception as exc:
                self.now_spinning_enabled = False
                log.warning('Now Spinning overlay unavailable: %s', exc)
                return
        snap = self._now_spinning_filter.update(active[0], active[1])
        try:
            self._now_spinning.render(int(width), int(height), snap)
        except Exception as exc:
            log.debug('Now Spinning render failed: %s', exc)

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
        self._render_now_spinning(width, height)

    def _present_subsystems(self) -> None:
        """Call each subsystem's own present() (e.g. control-room-01/
        dj-mixer-01 blitting to their own SDL window), then restore our GL
        context if any of them ran.

        control-room-01/dj-mixer-01's SDL_RenderPresent() on their own
        second SDL window silently calls eglMakeCurrent to their own
        internal context on Wayland and never switches back — confirmed via
        apitrace: a whole cascade of glUseProgram(GL_INVALID_VALUE)/
        glBindVertexArray(non-gen name)/etc. immediately follows in the
        trace, all valid object IDs in *our* context, invalid in whatever
        context SDL left current. Without the rebind here, every GL call
        for the rest of the session runs against the wrong context.

        Budget guard: when the previous frame overran 1.5x the frame budget,
        the present is skipped (up to _SUBSYS_PRESENT_MAX_SKIPS in a row) so
        secondary-window blits stop compounding a main-loop overload.
        """
        if (
            self._last_frame_ms > _SUBSYS_PRESENT_SKIP_MS
            and self._subsys_present_skips < _SUBSYS_PRESENT_MAX_SKIPS
        ):
            self._subsys_present_skips += 1
            return
        self._subsys_present_skips = 0
        any_attempted = False
        for name, subsystem in list(self._subsystems.items()):
            presenter = getattr(subsystem, 'present', None)
            if not callable(presenter):
                continue
            any_attempted = True
            try:
                presenter()
            except Exception as exc:
                log.warning('%s subsystem present failed: %s', name, exc)
        if any_attempted:
            # Rebind on any attempt, not just successful ones — a presenter
            # can switch the GL context internally (e.g. via SDL_RenderPresent)
            # before failing partway through, so a caught exception doesn't
            # rule out the context having already moved.
            self.rebind_main_gl_context()

    def _update_frame_capture_snapshot(
        self,
        frame: bytes | None,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        """Cache the latest audience-output frame for subsystem preview use.

        Pass ``width``/``height`` when the frame is not full-canvas sized
        (e.g. the downsampled preview readback); consumers must honour
        get_frame_capture()'s reported dimensions rather than assume the
        canvas size.
        """
        if frame is None:
            self._frame_capture_bytes = None
            self._frame_capture_width = 0
            self._frame_capture_height = 0
            self._frame_capture_components = 0
            return
        self._frame_capture_bytes = bytes(frame)
        self._frame_capture_width = int(width if width is not None else self._width)
        self._frame_capture_height = int(height if height is not None else self._height)
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

    # Min interval between event-driven display-state refreshes: MOVED spams
    # continuously during a window drag.
    _DISPLAY_REFRESH_MIN_S = 0.5

    def _refresh_display_state(self, reason: str) -> None:
        """Re-derive display index + window origin from live SDL state.

        Compositors move/restack the window without a resize event (GNOME
        workspace switches, Windows monitor drags/wake), and the cached
        origin/display index previously refreshed only on monitor hotplug —
        overlays and mirror tiling then ran against stale geometry
        (2026-07-08 audit item 5). Conservative by design: the origin is
        committed only when it lies inside a known display layout, honoring
        the original compositor-drift concern in
        _primary_display_viewport(); an implausible query keeps the cache.
        """
        if self._window is None:
            return
        now = time.monotonic()
        if (now - self._display_refresh_last_t) < self._DISPLAY_REFRESH_MIN_S:
            return
        self._display_refresh_last_t = now
        try:
            disp = int(sdl2.SDL_GetWindowDisplayIndex(self._window))
        except Exception:
            disp = -1
        if disp >= 0 and disp != self._display_index:
            log.info(
                'Display state refresh (%s): display %d -> %d',
                reason, self._display_index, disp,
            )
            self._display_index = disp
        wx = ctypes.c_int(0)
        wy = ctypes.c_int(0)
        sdl2.SDL_GetWindowPosition(self._window, wx, wy)
        ox, oy = int(wx.value), int(wy.value)
        if (ox, oy) == (self._window_origin_x, self._window_origin_y):
            return
        layouts = self._multihead_layouts()
        if layouts and not any(
            lx <= ox < lx + lw and ly <= oy < ly + lh
            for lx, ly, lw, lh in layouts
        ):
            log.debug(
                'Display state refresh (%s): origin (%d,%d) outside known '
                'layouts — keeping cached origin', reason, ox, oy,
            )
            return
        log.info(
            'Display state refresh (%s): origin (%d,%d) -> (%d,%d)',
            reason, self._window_origin_x, self._window_origin_y, ox, oy,
        )
        self._window_origin_x = ox
        self._window_origin_y = oy

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

    def _rebuild_multihead_outputs(self) -> None:
        self._display_index = self._multihead.rebuild_multihead_outputs(
            self._width,
            self._height,
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
        self._stream_pbo_frame_count = 0
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
        self._apply_windows_dpi_hints()
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
        if sys.platform == 'win32':
            # Pairs with the per-monitor-v2 hint in _apply_windows_dpi_hints():
            # with the process DPI-aware, sizes are physical pixels and this
            # flag keeps SDL from ever creating a DPI-virtualized surface.
            # Win32-only: on Wayland/macOS this flag changes drawable-vs-window
            # size semantics the rest of the pipeline doesn't expect.
            flags |= sdl2.SDL_WINDOW_ALLOW_HIGHDPI
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

        default_title = (
            "Unicorn Mix" if self._boot_profile == PROFILE_MIXER else "Unicorn Viz"
        )
        title = self.cfg.get("window", "title", default=default_title)
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
        log.info(
            "OpenGL %s (vendor=%s renderer=%s)",
            self._ctx.info["GL_VERSION"],
            self._ctx.info.get("GL_VENDOR", "?"),
            self._ctx.info.get("GL_RENDERER", "?"),
        )
        self._build_present_pipeline()
        self._build_blend_pipeline()
        self._build_invert_pipeline()
        self._build_burst_pipeline()
        # GL visual-overlay drop-ins (unicorn-tears, candy-frame, webcam,
        # postfx, color-grade, beat-flash, ...): all visual-output oriented,
        # so the mixer profile skips the whole block (safe_mode already does).
        if not self._safe_mode and self._boot_profile != PROFILE_MIXER:
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
                # Full traceback: a constructor failure here disables the
                # entire webcam subsystem for the session, and a bare
                # one-line message (e.g. an AttributeError from a
                # construction-order bug) gives no way to find the cause.
                log.warning(
                    'WebcamSystem DISABLED — constructor failed: %s. '
                    'The camera overlay will not be available this session.',
                    exc, exc_info=True,
                )
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
                self.cfg.get('demo', 'effect_duration', default=60)
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

            # Chroma-keyed video overlay stack, last in the post chain so its
            # composited clips are the final layer before the audience-facing
            # overlay stack (optional drop-in).
            video_postfx_cfg = self.cfg.get('video_postfx', default={}) or {}
            if not isinstance(video_postfx_cfg, dict):
                video_postfx_cfg = {}
            if not bool(video_postfx_cfg.get('enabled', True)):
                self._video_postfx = None
                log.info('VideoPostFxController disabled by config')
            else:
                try:
                    video_postfx_cls = _load_video_postfx_controller_class()
                    self._video_postfx = video_postfx_cls(
                        self._ctx,
                        self._render_width,
                        self._render_height,
                        video_postfx_cfg,
                    )
                    self._video_postfx.set_vj_api(self.vj_api)
                    self.vj_api.register_subsystem('video_postfx', self._video_postfx)
                    key_handler = getattr(self._video_postfx, 'handle_key', None)
                    if callable(key_handler):
                        self.vj_api.register_key_handler('video_postfx', key_handler)
                    log.info('VideoPostFxController loaded from drop-in')
                except Exception as exc:
                    self._video_postfx = None
                    log.warning('VideoPostFxController not available: %s', exc)

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

        Order is postfx → colour-grade → beat-flash → video-postfx (last, so
        its composited video layers are the final layer before the
        audience-facing overlay stack takes over). Each entry exposes the
        shared ``apply(src_tex, dst_fbo, dt, bass, mid, treble, beat)``
        contract and an ``is_active()`` predicate.
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
        vp = self._video_postfx
        if vp is not None and vp.is_active():
            chain.append(vp)
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
        # Reactivity scales only the "level" signals (bass/mid/treble/fft) above.
        # Everything else is reactivity-independent by design and must be copied
        # through faithfully — the raw perceptual `bands` in particular drive the
        # fixed-height spectrum bars, and the z-score normalised / flux fields are
        # already reactivity-invariant. (Previously these were dropped, so a
        # per-effect reactivity override fed effects a stale/zero `bands`.)
        target.bands[:] = source.bands
        target.bass_n = source.bass_n
        target.mid_n = source.mid_n
        target.treble_n = source.treble_n
        target.bass_flux = source.bass_flux
        target.mid_flux = source.mid_flux
        target.spectral_flux = source.spectral_flux
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

    def _release_fbo(self, fbo: 'moderngl.Framebuffer | None') -> None:
        """Release an FBO together with its color/depth attachments.

        No ``ctx.gc_mode`` is set anywhere, so releasing only the
        Framebuffer object leaks its color texture and depth renderbuffer
        (~16 MB per rebuild at 1080p) — render-scale scrubbing and window
        resizes previously accumulated those until VRAM exhaustion.
        """
        if fbo is None:
            return
        try:
            attachments = list(getattr(fbo, 'color_attachments', ()) or ())
        except Exception:
            attachments = []
        for tex in attachments:
            try:
                tex.release()
            except Exception:
                pass
        depth = getattr(fbo, 'depth_attachment', None)
        if depth is not None:
            try:
                depth.release()
            except Exception:
                pass
        try:
            fbo.release()
        except Exception:
            log.debug('FBO release failed', exc_info=True)

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
            'presets_visible',
            'context_menu_open',
            'config_editor_open',
            'tour_visible',
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
            or self._subsystem_window_open()
        )

    def _subsystem_window_open(self) -> bool:
        """Return True while any subsystem's own window (e.g. control-room-01
        or dj-mixer-01's operator window) is open.

        SDL_ShowCursor is a single, process-global setting — it cannot be
        scoped to one window. Subsystems used to fight this main-loop policy
        by calling SDL_ShowCursor(ENABLE) directly from their own present(),
        racing against this per-frame call and often losing (the cursor
        would flicker or stay hidden). Centralizing the check here instead
        means there is exactly one place per frame that decides cursor
        visibility.
        """
        return any(
            bool(getattr(subsystem, 'is_open', False))
            for subsystem in self._subsystems.values()
        )

    def _update_ctrl_state(self, sym: int, is_keydown: bool) -> None:
        if sym in (sdl2.SDLK_LCTRL, sdl2.SDLK_RCTRL):
            self._ctrl_held = is_keydown
            self._set_cursor_visible(self._cursor_should_be_visible())

    # ------------------------------------------------------------------ #
    # Right-click context menu                                             #
    # ------------------------------------------------------------------ #

    def _build_context_menu_model(self) -> list[dict[str, object]]:
        """Build the right-click context-menu entries.

        Core toggles/modals/actions are declared here with state-aware labels
        (toggles read live state to show what a click will do). Drop-in features
        are pulled dynamically from the registered help entries — never
        hard-coded — so any drop-in that documents a single-chord hotkey appears
        automatically. Every entry carries the (sym, mod) of its documented
        binding; selecting it replays that binding via the hotkey handler.
        """
        K = sdl2

        def item(label: str, sym: int, mod: int = 0, kind: str = 'action',
                 hotkey: str = '') -> dict[str, object]:
            return {
                'label': label, 'sym': int(sym), 'mod': int(mod),
                'kind': kind, 'hotkey': hotkey, 'header': False, 'enabled': True,
            }

        def header(title: str) -> dict[str, object]:
            return {
                'label': title, 'sym': 0, 'mod': 0, 'kind': 'header',
                'hotkey': '', 'header': True, 'enabled': False,
            }

        ov = self._overlays
        entries: list[dict[str, object]] = []

        # Modals — "Open <context>".
        entries.append(header('Open'))
        entries.append(item('Open Effects Browser', K.SDLK_b, 0, 'modal', 'B'))
        entries.append(item('Open Show Presets', K.SDLK_p, K.KMOD_CTRL | K.KMOD_SHIFT, 'modal', 'Ctrl+Shift+P'))
        entries.append(item('Open Configuration', K.SDLK_c, 0, 'modal', 'C'))
        entries.append(item('Open System Monitor', K.SDLK_m, 0, 'modal', 'M'))
        entries.append(item('Open Control Room', K.SDLK_m, K.KMOD_SHIFT, 'modal', 'Shift+M'))
        entries.append(item('Open Audio Sources', K.SDLK_a, K.KMOD_SHIFT, 'modal', 'Shift+A'))
        entries.append(item('Open MIDI Devices', K.SDLK_m, K.KMOD_ALT, 'modal', 'Alt+M'))
        entries.append(item('Open Help', K.SDLK_h, 0, 'modal', 'H'))
        entries.append(item('Open Tour', K.SDLK_F1, 0, 'modal', 'F1'))

        # Toggles — state-aware "<action> <context>".
        entries.append(header('Toggle'))
        aa = bool(self._auto_advance)
        entries.append(item(f'{"Disable" if aa else "Enable"} Auto-Advance', K.SDLK_t, 0, 'toggle', 'T'))
        paused = bool(self.paused)
        entries.append(item(f'{"Resume" if paused else "Pause"} Playback', K.SDLK_SPACE, 0, 'toggle', 'Space'))
        inv = bool(self._invert_colors)
        entries.append(item(f'{"Disable" if inv else "Enable"} Invert Colors', K.SDLK_i, 0, 'toggle', 'I'))
        fs = bool(self._fullscreen)
        entries.append(item(f'{"Exit" if fs else "Enter"} Fullscreen', K.SDLK_f, 0, 'toggle', 'F'))
        rec = bool(getattr(ov, '_recording_active', False))
        entries.append(item(f'{"Stop" if rec else "Start"} Recording', K.SDLK_v, 0, 'toggle', 'V'))
        nm = bool(getattr(ov, 'name_overlay_visible', False))
        entries.append(item(f'{"Hide" if nm else "Show"} Effect Name', K.SDLK_TAB, 0, 'toggle', 'Tab'))

        # One-shot actions.
        entries.append(header('Actions'))
        entries.append(item('Next Effect', K.SDLK_n, 0, 'action', 'N'))
        entries.append(item('Previous Effect', K.SDLK_p, 0, 'action', 'P'))
        entries.append(item('Random Effects Mode', K.SDLK_r, 0, 'action', 'R'))
        entries.append(item('Take Screenshot', K.SDLK_s, 0, 'action', 'S'))
        entries.append(item('Replay Splash', K.SDLK_u, 0, 'action', 'U'))
        entries.append(item('Disable Effect & Skip', K.SDLK_DELETE, 0, 'action', 'Delete'))

        # Drop-in features — generated from the help registry (not hard-coded).
        for section, dropin_items in self._context_menu_dropin_sections():
            entries.append(header(section))
            entries.extend(dropin_items)

        # Footer.
        entries.append(header(''))
        entries.append(item('Quit', K.SDLK_ESCAPE, 0, 'action', 'Esc'))

        return entries

    def _context_menu_dropin_sections(
        self,
    ) -> list[tuple[str, list[dict[str, object]]]]:
        """Return drop-in menu entries grouped by section, from the help registry.

        Only single-chord bindings are included; ranges / multi-key / wheel help
        lines are skipped. Duplicate bindings are de-duplicated.
        """
        getter = getattr(self._overlays, 'dropin_help_entries', None)
        if not callable(getter):
            return []
        grouped: dict[str, list[dict[str, object]]] = {}
        order: list[str] = []
        seen: set[tuple[int, int]] = set()
        for section, key, desc in getter():
            chord = parse_hotkey_chord(key)
            if chord is None:
                continue
            sym, mod = chord
            if (sym, mod) in seen:
                continue
            seen.add((sym, mod))
            entry = {
                'label': _context_menu_label_from_help(desc),
                'sym': int(sym), 'mod': int(mod), 'kind': 'dropin',
                'hotkey': str(key), 'header': False, 'enabled': True,
            }
            if section not in grouped:
                grouped[section] = []
                order.append(section)
            grouped[section].append(entry)
        return [(section, grouped[section]) for section in order]

    def _open_context_menu_at(self, x: float, y: float) -> None:
        """Build the menu model and open it at overlay coords (x, y)."""
        if self._boot_profile == PROFILE_MIXER:
            # Visual-oriented menu; suppressed in the mixer profile (§8).
            return
        entries = self._build_context_menu_model()
        self._overlays.open_context_menu(entries, x, y)
        self._set_cursor_visible(True)

    def _activate_context_menu_entry(self, index: int) -> None:
        """Replay the hotkey binding of the selected context-menu entry."""
        entries = self._overlays.context_menu_entries
        if not (0 <= index < len(entries)):
            return
        entry = entries[index]
        sym = int(entry.get('sym', 0) or 0)
        mod = int(entry.get('mod', 0) or 0)
        if sym and self._hotkeys is not None:
            self._hotkeys.handle(sym, mod)

    # ------------------------------------------------------------------ #
    # Configuration profiles (per-effect parameter overrides)              #
    # ------------------------------------------------------------------ #

    def config_profile_names(self) -> list[str]:
        """Return saved configuration-profile names."""
        return self._config_profile_store.names()

    def effect_class_names(self) -> list[str]:
        """Return class names of all registered effects (for the editor list)."""
        return [cls.__name__ for cls in get_effects()]

    def current_effect_class_name(self) -> str | None:
        """Return the active effect's class name, or None."""
        eff = self._current_effect
        return type(eff).__name__ if eff is not None else None

    def effect_parameters(self, class_name: str) -> dict[str, float]:
        """Return the tunable parameters for an effect class.

        For the active effect this reads the live instance; otherwise it merges
        the ``config.toml`` values with any active profile override.
        """
        eff = self._current_effect
        if eff is not None and type(eff).__name__ == class_name:
            return {str(k): float(v) for k, v in eff.parameters.items()}
        params: dict[str, float] = {}
        base = self.cfg.get('effects', class_name, default={})
        if isinstance(base, dict):
            for k, v in base.items():
                if isinstance(v, (int, float)):
                    params[str(k)] = float(v)
        params.update(self._effect_config_overrides.get(class_name, {}))
        return params

    def set_effect_parameter(self, class_name: str, name: str, value: float) -> None:
        """Set a per-effect parameter override, live-applying to the active effect."""
        self._effect_config_overrides.setdefault(str(class_name), {})[str(name)] = float(value)
        eff = self._current_effect
        if eff is not None and type(eff).__name__ == class_name and str(name) in eff.parameters:
            eff.parameters[str(name)] = float(value)

    def clear_effect_overrides(self, class_name: str) -> None:
        """Drop overrides for one effect and restore the active instance live."""
        self._effect_config_overrides.pop(str(class_name), None)
        eff = self._current_effect
        if eff is not None and type(eff).__name__ == class_name:
            initial = getattr(eff, '_initial_parameters', None)
            if isinstance(initial, dict):
                for k, v in initial.items():
                    if k in eff.parameters:
                        eff.parameters[k] = float(v)

    def config_overrides_snapshot(self) -> dict[str, dict[str, float]]:
        """Return a deep-ish copy of the current per-effect overrides."""
        return {k: dict(v) for k, v in self._effect_config_overrides.items()}

    def save_config_profile(self, name: str) -> None:
        """Persist effect overrides + global/drop-in settings as a named profile."""
        settings = {s['key']: float(s['value']) for s in self._config_editor_all_specs()}
        self._config_profile_store.save(name, {
            'effects': self.config_overrides_snapshot(),
            'settings': settings,
        })

    def load_config_profile(self, name: str) -> bool:
        """Load a profile: apply effect overrides + global/drop-in settings live."""
        payload = self._config_profile_store.get(name)
        if payload is None:
            return False
        effects = payload.get('effects', {}) if isinstance(payload, dict) else {}
        new_overrides: dict[str, dict[str, float]] = {}
        if isinstance(effects, dict):
            for cls_name, params in effects.items():
                if isinstance(params, dict):
                    new_overrides[str(cls_name)] = {
                        str(k): float(v)
                        for k, v in params.items()
                        if isinstance(v, (int, float))
                    }
        self._effect_config_overrides = new_overrides
        eff = self._current_effect
        if eff is not None:
            for k, v in self._effect_config_overrides.get(type(eff).__name__, {}).items():
                if k in eff.parameters:
                    eff.parameters[k] = float(v)
        # Apply persisted global + drop-in settings via their live setters.
        settings = payload.get('settings', {}) if isinstance(payload, dict) else {}
        if isinstance(settings, dict) and settings:
            by_key = {s['key']: s for s in self._config_editor_all_specs()}
            for key, value in settings.items():
                spec = by_key.get(str(key))
                if spec is not None and isinstance(value, (int, float)):
                    try:
                        spec['set'](float(value))
                    except Exception:
                        log.debug('Profile setting apply failed: %s', key, exc_info=True)
        return True

    def delete_config_profile(self, name: str) -> bool:
        """Delete a named configuration profile."""
        return self._config_profile_store.delete(name)

    def config_editor_param_rows(self, class_name: str) -> list[dict[str, float | str]]:
        """Return ``[{'name','value','min','max'}]`` for an effect's parameters.

        Ranges are inferred from the effect's *initial* value where available
        (the active effect) so they stay stable while editing.
        """
        values = self.effect_parameters(class_name)
        base = dict(values)
        eff = self._current_effect
        if eff is not None and type(eff).__name__ == class_name:
            initial = getattr(eff, '_initial_parameters', None)
            if isinstance(initial, dict):
                base = {k: float(initial.get(k, v)) for k, v in values.items()}
        rows: list[dict[str, float | str]] = []
        for name in sorted(values):
            lo, hi = _infer_param_range(base.get(name, values[name]))
            rows.append({'name': name, 'value': float(values[name]), 'min': lo, 'max': hi})
        return rows

    def _push_config_editor_model(self) -> None:
        """Feed the config editor its per-tab data each frame while open."""
        overlays = self._overlays
        tabs = ['Effects', 'Audio', 'Visuals', 'System', 'Hotkeys']
        if self._auto_vj is not None:
            tabs.append('Auto VJ')
        overlays.set_config_editor_tabs(tabs)

        effects = [
            {'class_name': cls.__name__, 'display_name': str(getattr(cls, 'NAME', cls.__name__))}
            for cls in get_effects()
        ]
        overlays.set_config_editor_effects(effects)
        if not self._config_editor_was_open:
            # Rising edge: default-select the current effect.
            current = self.current_effect_class_name()
            idx = next(
                (i for i, e in enumerate(effects) if e['class_name'] == current), 0
            )
            overlays.set_config_editor_effect_index(idx)
            self._config_editor_was_open = True

        tab = overlays.config_editor_tab_name
        if tab == 'Effects':
            cls = overlays.config_editor_selected_class()
            overlays.set_config_editor_params(
                self.config_editor_param_rows(cls) if cls else []
            )
        elif tab in ('Audio', 'Visuals'):
            overlays.set_config_editor_params(self.config_editor_global_rows(tab))
        elif tab == 'Hotkeys':
            overlays.set_config_editor_params(self.config_editor_hotkey_rows())
        else:  # System, Auto VJ — read-only info rows.
            overlays.set_config_editor_params(self.config_editor_info_rows(tab))
        overlays.set_config_editor_profiles(self.config_profile_names())
        overlays.set_config_editor_dirty(bool(self._effect_config_overrides))

    def config_editor_info_rows(self, tab: str) -> list[dict[str, str]]:
        """Return read-only info rows for the System / Auto VJ tabs."""
        def info(name: str, value: object) -> dict[str, str]:
            return {'name': name, 'kind': 'info', 'info': str(value)}

        rows: list[dict[str, str]] = []
        if tab == 'System':
            rows.append(info('FPS', f'{getattr(self, "_last_frame_fps", 0.0):.1f}'))
            rows.append(info('Frame ms', f'{getattr(self, "_last_frame_ms", 0.0):.2f}'))
            if self._audio_manager is not None:
                rows.append(info('Audio xruns', self._audio_manager.get_xrun_count()))
                rows.append(info('Audio source', self._audio_manager.get_source_label()))
                rows.append(info('BPM profile', self._audio_manager.get_profile_name()))
            rows.append(info('Render size', f'{self._render_width}x{self._render_height}'))
            rows.append(info('Window size', f'{self._width}x{self._height}'))
            rows.append(info('Resolution scale', f'{self._render_scale:.2f}'))
            rows.append(info('Display mode', self._display_mode))
            rows.append(info('Effects', len(get_effects())))
            rows.append(info('Platform', sys.platform))
            rows.append(info(
                'Python',
                f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}',
            ))
        elif tab == 'Auto VJ' and self._auto_vj is not None:
            av = self._auto_vj

            def lab(attr: str) -> str:
                value = getattr(av, attr, None)
                return str(value) if value not in (None, '') else '-'

            rows.append(info('Mood', lab('hud_mood_label')))
            rows.append(info('Scene', lab('hud_scene_label')))
            rows.append(info('BPM', lab('hud_bpm_label')))
            rows.append(info('BPM confidence', lab('hud_bpm_confidence_label')))
            rows.append(info('Action in', lab('hud_action_in_label')))
            rows.append(info('Profile score', lab('current_profile_score_hud')))
            rows.append(info('Profile rec', lab('profile_recommendation_hud')))
        return rows

    # -- Hotkeys tab (rebind global actions) ----------------------------------
    # Hand-authored labels for the rebindable actions in hotkeys.action_names()
    # (a curated, deliberately "global commands only" set - not the full help
    # registry, which also documents modal-scoped/navigation keys that make no
    # sense to rebind). Keep this in sync when a new action is added to
    # hotkeys._MIDI_NOTE_KEY_BINDINGS.
    _HOTKEY_ACTION_LABELS: dict[str, str] = {
        'next': 'Next Effect',
        'prev': 'Previous Effect',
        'random': 'Random Effects Mode',
        'pause': 'Pause / Resume',
        'fullscreen': 'Toggle Fullscreen',
        'audio_toggle': 'Audio On/Off',
        'eq': 'EQ / Spectrum',
        'ansi': 'ANSI Viewer',
        'audio_selector': 'Audio Source Selector',
        'midi_selector': 'MIDI Device Selector',
        'system_monitor': 'System Monitor',
        'control_room': 'Control Room',
        'projectm_manager': 'ProjectM Manager',
        'controller_help': 'Controller Help',
        'help': 'Help Overlay',
        'hud': 'HUD Toggle',
        'screenshot': 'Screenshot',
        'replay_splash': 'Replay Splash',
        'invert': 'Invert Colors',
        'display_single': 'Display: Single',
        'display_span_included': 'Display: Span (Included)',
        'display_span_all': 'Display: Span (All)',
        'display_mirror_included': 'Display: Mirror (Included)',
        'display_mirror_all': 'Display: Mirror (All)',
        'grand_finale': 'Trigger Grand Finale',
        'grand_finale_abort': 'Abort Grand Finale',
        'speed_random': 'Speed Random Toggle',
        'reactivity_random': 'Reactivity Random Toggle',
        'zoom_random': 'Zoom Random Toggle',
        'disable_and_advance': 'Disable Effect & Skip',
    }

    def config_editor_hotkey_rows(self) -> list[dict[str, object]]:
        """Return rebindable-action rows for the Hotkeys tab.

        Each row: {'name': label, 'kind': 'bind', 'action': action_name,
        'chord': display label, 'is_override': bool}.
        """
        from unicornviz.hotkeys import action_names, chord_label, default_action_binding

        rows: list[dict[str, object]] = []
        for action in action_names():
            override = self._hotkey_overrides.get(action)
            sym_mod = override or default_action_binding(action)
            chord = chord_label(*sym_mod) if sym_mod is not None else '-'
            rows.append({
                'name': self._HOTKEY_ACTION_LABELS.get(action, action),
                'kind': 'bind',
                'action': action,
                'chord': chord,
                'is_override': override is not None,
            })
        return rows

    def hotkey_action_for_chord(self, sym: int, mod: int, exclude_action: 'str | None' = None) -> 'str | None':
        """Return the rebindable action currently bound to (sym, mod), if any.

        Checks each action's *effective* binding (override if set, else
        default). Used for live conflict detection when capturing a new chord.
        """
        from unicornviz.hotkeys import action_names, default_action_binding

        for action in action_names():
            if action == exclude_action:
                continue
            effective = self._hotkey_overrides.get(action) or default_action_binding(action)
            if effective == (sym, mod):
                return action
        return None

    def start_hotkey_capture(self, action: str) -> None:
        """Enter capture mode: the next keypress becomes ``action``'s chord."""
        self._overlays.set_config_editor_capture(True, action)
        self._overlays.flash_message('Press a new key... (Esc to cancel)', 2.0)

    def apply_hotkey_capture(self, sym: int, mod: int) -> str:
        """Resolve a captured chord for the action currently being rebound.

        Rejects bare modifier keys and chords already bound to a *different*
        action (conflict); on success applies the rebind and exits capture
        mode. Returns a user-facing flash message either way.
        """
        from unicornviz.hotkeys import chord_label, is_modifier_keysym

        action = self._overlays.config_editor_capture_action
        if not action:
            self._overlays.set_config_editor_capture(False, '')
            return ''
        if is_modifier_keysym(sym):
            return 'Choose a non-modifier key'
        conflict = self.hotkey_action_for_chord(sym, mod, exclude_action=action)
        if conflict is not None:
            label = self._HOTKEY_ACTION_LABELS.get(conflict, conflict)
            return f'Conflicts with "{label}" - choose another key'
        self.set_hotkey_override(action, sym, mod)
        self._overlays.set_config_editor_capture(False, '')
        label = self._HOTKEY_ACTION_LABELS.get(action, action)
        return f'{label}: bound to {chord_label(sym, mod)}'

    def cancel_hotkey_capture(self) -> None:
        """Exit capture mode without changing the binding."""
        self._overlays.set_config_editor_capture(False, '')

    def reset_hotkey_to_default(self, action: str) -> str:
        """Clear an action's override, reverting it to its default chord."""
        label = self._HOTKEY_ACTION_LABELS.get(action, action)
        if action not in self._hotkey_overrides:
            return f'{label}: already default'
        self.set_hotkey_override(action, None)
        return f'{label}: reset to default'

    # App attributes that may hold a config-editor-contributing controller.
    # (Which of the app's own subsystems to poll — the *settings* still come
    # from each drop-in via the convention, so nothing drop-in-specific is
    # hard-coded here.)
    _CONFIG_CONTRIBUTOR_ATTRS = (
        '_color_grade', '_audio_out', '_beat_flash', '_postfx_controller',
        '_lyrics', '_webcam_system',
    )

    def _config_editor_settings_specs(self, tab: str) -> list[dict]:
        """Return unified setting specs for a tab.

        Each spec: ``{'key','name','value','min','max','set'}``.  Combines core
        globals with drop-in contributions gathered via the config-editor
        convention (``CONFIG_EDITOR_CATEGORY`` + ``config_editor_settings()`` +
        ``set_config_setting()``).
        """
        specs: list[dict] = []
        if tab == 'Audio':
            if self._audio_manager is not None:
                am = self._audio_manager
                specs.append({'key': 'audio.reactivity', 'name': 'reactivity',
                              'value': float(am.get_reactivity()), 'min': 0.1, 'max': 5.0,
                              'set': am.set_reactivity})
            specs.append({'key': 'audio.advance_interval_s', 'name': 'advance_interval_s',
                          'value': float(self._effect_duration), 'min': 10.0, 'max': 120.0,
                          'set': lambda v: setattr(self, '_effect_duration', max(10.0, float(v)))})
        elif tab == 'Visuals':
            specs.append({'key': 'visuals.render_scale', 'name': 'render_scale',
                          'value': float(self._render_scale), 'min': 0.5, 'max': 1.0,
                          'set': self.set_render_scale})
        specs.extend(self._config_editor_dropin_specs(tab))
        return specs

    def _config_editor_dropin_specs(self, tab: str) -> list[dict]:
        """Gather drop-in setting specs for a tab via the config-editor convention."""
        specs: list[dict] = []
        for attr in self._CONFIG_CONTRIBUTOR_ATTRS:
            ctrl = getattr(self, attr, None)
            if ctrl is None or getattr(ctrl, 'CONFIG_EDITOR_CATEGORY', None) != tab:
                continue
            getter = getattr(ctrl, 'config_editor_settings', None)
            setter = getattr(ctrl, 'set_config_setting', None)
            if not (callable(getter) and callable(setter)):
                continue
            prefix = str(getattr(ctrl, 'CONFIG_EDITOR_KEY', attr.lstrip('_')))
            try:
                rows = getter()
            except Exception:
                log.debug('config_editor_settings failed for %s', attr, exc_info=True)
                continue
            for row in rows:
                name = str(row.get('name', ''))
                if not name:
                    continue
                specs.append({
                    'key': f'dropin.{prefix}.{name}',
                    'name': name,
                    'value': float(row.get('value', 0.0)),
                    'min': float(row.get('min', 0.0)),
                    'max': float(row.get('max', 1.0)),
                    'set': (lambda v, s=setter, n=name: s(n, v)),
                })
        return specs

    def _config_editor_all_specs(self) -> list[dict]:
        """All persistable setting specs across the settings tabs."""
        specs: list[dict] = []
        for tab in ('Audio', 'Visuals'):
            specs.extend(self._config_editor_settings_specs(tab))
        return specs

    def config_editor_global_rows(self, tab: str) -> list[dict[str, float | str]]:
        """Return ``[{'name','value','min','max'}]`` for a tab's settings rows."""
        return [
            {'name': s['name'], 'value': s['value'], 'min': s['min'], 'max': s['max']}
            for s in self._config_editor_settings_specs(tab)
        ]

    def _apply_config_editor_action(self) -> None:
        """Run a pending footer action (save/load/delete/revert)."""
        overlays = self._overlays
        action = overlays.take_config_editor_action()
        if action is None:
            return
        if action == 'save':
            name = overlays.config_editor_name_text.strip()
            if name:
                self.save_config_profile(name)
                overlays.flash_message(f'Profile saved: {name}', 1.6)
            else:
                overlays.set_config_editor_name_mode(True)
        elif action == 'load':
            name = overlays.config_editor_selected_profile()
            if name and self.load_config_profile(name):
                overlays.flash_message(f'Profile loaded: {name}', 1.6)
        elif action == 'delete':
            name = overlays.config_editor_selected_profile()
            if name and self.delete_config_profile(name):
                overlays.flash_message(f'Profile deleted: {name}', 1.6)
        elif action == 'revert':
            cls = overlays.config_editor_selected_class()
            if cls:
                self.clear_effect_overrides(cls)
                overlays.flash_message(f'Reverted: {cls}', 1.4)

    def _config_editor_adjust(self, notches: float) -> None:
        """Adjust the selected parameter/setting by ``notches`` steps, live."""
        overlays = self._overlays
        i = overlays.config_editor_param_index()
        tab = overlays.config_editor_tab_name
        if tab == 'Effects':
            cls = overlays.config_editor_selected_class()
            if not cls:
                return
            rows = self.config_editor_param_rows(cls)
            if not (0 <= i < len(rows)):
                return
            row = rows[i]
            lo, hi = float(row['min']), float(row['max'])
            step = (hi - lo) / 40.0 if hi > lo else 0.01
            new_value = min(hi, max(lo, float(row['value']) + notches * step))
            self.set_effect_parameter(cls, str(row['name']), new_value)
            return
        # Audio / Visuals: apply to the setting via its setter.
        specs = self._config_editor_settings_specs(tab)
        if not (0 <= i < len(specs)):
            return
        spec = specs[i]
        lo, hi = float(spec['min']), float(spec['max'])
        step = (hi - lo) / 40.0 if hi > lo else 0.01
        spec['set'](min(hi, max(lo, float(spec['value']) + notches * step)))

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
        # Layer active configuration-profile overrides on top of config.toml so
        # operator-tuned parameters pin over the effect's randomized defaults.
        override = self._effect_config_overrides.get(cls.__name__)
        if override:
            effect_cfg = {**effect_cfg, **override}
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

    def _switch_effect(self, cls: Type[BaseEffect] | None) -> None:
        """Begin transition to a new effect."""
        if cls is None:
            # Empty playlist (mixer-only boot profile) — nothing to switch to.
            return
        if self._pinned_pair is not None:
            # A normal transition (e.g. a manual "next effect" hotkey)
            # interrupting a pinned ping-pong pair -- release it here
            # rather than relying on the caller (auto-vj-01's
            # _exit_pingpong()) to have done so first, or the
            # off-screen pinned instance would leak forever. Mirrors
            # unpin_effect_pair(): the on-screen instance is left alone,
            # since it's still self._current_effect and gets destroyed
            # the normal way once this transition completes below.
            self.unpin_effect_pair()
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
        resolved = self._resolve_unblocked_effect(cls)
        if resolved is None:
            return
        cls = resolved
        # Invert does not carry through transitions.
        self._invert_colors = False
        if self._current_effect is not None:
            self._previous_effect_name = self._current_effect.NAME
        # Instantiate the incoming effect before destroying the pending one:
        # a constructor/shader failure must not leave a destroyed instance
        # wired in as _next_effect.
        try:
            incoming = self._instantiate(cls)
        except Exception:
            log.exception(
                'Effect %s failed to instantiate — switch skipped',
                getattr(cls, 'NAME', cls.__name__),
            )
            self._register_effect_crash(cls.__name__)
            return
        if self._next_effect is not None:
            self._next_effect.destroy()
        self._next_effect = incoming

        requested = str(self.cfg.get("demo", "transition", default="shuffle")).lower()
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

    _EFFECT_CRASH_LIMIT = 2

    def _register_effect_crash(self, cls_name: str) -> bool:
        """Count a crash for an effect class; quarantine it at the limit.

        Returns True when the class is (now) quarantined for this session.
        """
        count = self._effect_crash_counts.get(cls_name, 0) + 1
        self._effect_crash_counts[cls_name] = count
        if count >= self._EFFECT_CRASH_LIMIT and cls_name not in self._effect_blocklist:
            self._effect_blocklist.add(cls_name)
            log.error(
                'Effect %s crashed %d times — quarantined for this session',
                cls_name, count,
            )
        return cls_name in self._effect_blocklist

    def _resolve_unblocked_effect(
        self, cls: Type[BaseEffect]
    ) -> Type[BaseEffect] | None:
        """Redirect a switch away from session-quarantined effect classes."""
        if cls.__name__ not in self._effect_blocklist:
            return cls
        playlist = self._playlist
        if playlist is None:
            log.warning(
                'Effect %s is quarantined and no playlist is available to '
                'pick a replacement', cls.__name__,
            )
            return None
        for _ in range(64):
            candidate = playlist.advance()
            if candidate is None:
                break
            if candidate.__name__ not in self._effect_blocklist:
                log.info(
                    'Effect %s is quarantined — advancing to %s instead',
                    cls.__name__,
                    getattr(candidate, 'NAME', candidate.__name__),
                )
                return candidate
        log.error('All playlist effects are quarantined; keeping current effect')
        return None

    def _handle_effect_crash(self, effect: BaseEffect, phase: str) -> None:
        """Contain a crashing effect instead of letting it kill the show.

        Called from an ``except`` block (``log.exception`` relies on the
        active exception). Logs, counts toward quarantine, detaches the
        instance from the render pipeline, destroys it, and — when the
        current effect died — asks the main loop to advance next frame.
        """
        cls_name = type(effect).__name__
        log.exception(
            'Effect %s crashed in %s() — containing', cls_name, phase
        )
        self._register_effect_crash(cls_name)
        if effect is self._next_effect:
            self._next_effect = None
            self._transition_t = 0.0
        if effect is self._current_effect:
            self._current_effect = None
            self._effect_crash_recover = True
        try:
            effect.destroy()
        except Exception:
            log.debug(
                'Destroy of crashed effect %s failed', cls_name, exc_info=True
            )

    # ------------------------------------------------------------------ #
    # First-run tour (v1 slide dialog)                                     #
    # Content + startup policy: unicornviz/tour.py.  Rendering + pointer  #
    # input: Overlays.  Keyboard: HotkeyHandler (F1 + in-modal branch).   #
    # Persistence lives here, in the runtime state store.                 #
    # ------------------------------------------------------------------ #

    def _tour_deck(self) -> tuple[TourSlide, ...]:
        """Core slides plus any drop-in TOUR_SLIDES contributions.

        Drop-in slides land in alphabetical drop-in order (the discovery
        scan is directory-sorted) *before* the final core slide, so the
        good-bye slide always closes the tour. Discovery must never break
        the tour (independence rules): on any failure the core deck ships
        alone. Modules are already in the drop-in loader cache from help
        discovery, so the scan is cheap.
        """
        slides = list(CORE_TOUR_SLIDES)
        try:
            extras = [
                TourSlide(section, title, body)
                for section, title, body in discover_dropin_tour_slides(
                    self._dropin_dir_filter(),
                )
            ]
            slides[-1:-1] = extras
        except Exception as exc:
            log.debug('Drop-in tour slides skipped: %s', exc)
        return tuple(slides)

    def open_tour(self) -> None:
        """Open the tour dialog at the persisted resume position."""
        overlays = self._overlays
        if overlays is None or overlays.tour_visible:
            return
        if overlays.blocking_modal_open:
            overlays.flash_message('Close the current panel first', 1.5)
            return
        deck = self._tour_deck()
        overlays.set_tour_slides(deck)
        slide = clamp_slide_index(
            self.get_runtime_state(STATE_LAST_SLIDE, 0), len(deck),
        )
        show = bool(self.get_runtime_state(STATE_SHOW_ON_STARTUP, True))
        overlays.open_tour(slide, show)

    def close_tour(self) -> None:
        """Close the tour and persist its resume position + startup toggle."""
        overlays = self._overlays
        if overlays is None or not overlays.tour_visible:
            return
        slide, show = overlays.close_tour()
        self.save_tour_state(slide=slide, show=show)

    def toggle_tour(self) -> None:
        """Open or close the tour dialog (hotkey / context menu entry)."""
        overlays = self._overlays
        if overlays is not None and overlays.tour_visible:
            self.close_tour()
        else:
            self.open_tour()

    def tour_advance(self) -> None:
        """NEXT: advance a slide, or finish + close on the last one."""
        overlays = self._overlays
        if overlays is None or not overlays.tour_visible:
            return
        if overlays.tour_next():
            self.close_tour()   # tour_next reset the resume position to 0
        else:
            self.save_tour_state()

    def save_tour_state(self, slide: int | None = None, show: bool | None = None) -> None:
        """Persist the tour's resume slide + show-on-startup toggle."""
        overlays = self._overlays
        if slide is None or show is None:
            if overlays is None:
                return
            current_slide, current_show = overlays.tour_state()
            slide = current_slide if slide is None else slide
            show = current_show if show is None else show
        self.set_runtime_state(STATE_LAST_SLIDE, int(slide))
        self.set_runtime_state(STATE_SHOW_ON_STARTUP, bool(show))

    def _maybe_open_tour_on_startup(self) -> None:
        """Offer the tour at startup: first run, or the toggle left on."""
        overlays = self._overlays
        if overlays is None:
            return
        try:
            if should_show_on_startup(self.get_runtime_state) \
                    and not overlays.blocking_modal_open:
                self.open_tour()
        except Exception as exc:
            log.debug('Tour startup offer skipped: %s', exc)

    def _maybe_auto_play_media(self) -> None:
        """Boot-time auto-play for media-01 (mirrors the RTMP streamer's
        auto_start / the recorder's auto_record pattern). No-op unless
        media-01 loaded successfully and ``[media] auto_play`` is set --
        e.g. training-daemon's ``--media-source``. Failures are swallowed
        so a media-01 bug can never block the rest of boot (drop-in
        independence rule).
        """
        media = self._media
        if media is None or not bool(getattr(media, 'enabled', False)):
            return
        if not bool(getattr(media, 'auto_play', False)):
            return
        try:
            result = media.play_pause()
            log.info('media-01: auto-play at boot: %s', result)
        except Exception as exc:
            log.warning('media-01: auto-play at boot failed: %s', exc)

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

    def _load_dj_mixer_subsystem(self) -> None:
        """Load the two-deck DJ mixer drop-in (window + DDJ-REV1 input).

        Loaded (and REV1 MIDI wired) when enabled; the window and audio
        output stream stay idle until the operator opens it (Shift+D). The
        mixer boot profile implies ``start_enabled`` so the console opens
        immediately at boot.
        """
        dj_mixer_cfg = self.cfg.get('dj_mixer', default={}) or {}
        if not isinstance(dj_mixer_cfg, dict):
            dj_mixer_cfg = {}
        if not bool(dj_mixer_cfg.get('enabled', True)):
            return
        if self._boot_profile == PROFILE_MIXER:
            dj_mixer_cfg = dict(dj_mixer_cfg)
            dj_mixer_cfg['start_enabled'] = True
            # Hosted: no second window.  The console renders into *this*
            # window (plan §3-§4) and claims this window's events.
            dj_mixer_cfg['hosted'] = True
        try:
            dj_mixer_cls = _load_dj_mixer_controller_class()
            self._dj_mixer = dj_mixer_cls(self, dj_mixer_cfg)
            self.vj_api.register_subsystem('dj_mixer', self._dj_mixer)
            key_handler = getattr(self._dj_mixer, 'handle_key', None)
            if callable(key_handler):
                self.vj_api.register_key_handler('dj_mixer', key_handler)
            log.info('DjMixerController loaded from drop-in')
        except Exception as exc:
            self._dj_mixer = None
            log.warning('DjMixerController not available: %s', exc)

    def run(self) -> None:
        boot = _StartupProfiler()
        self._init_sdl()
        boot.mark('init_sdl')
        self._init_moderngl()
        boot.mark('init_moderngl')

        # Subsystems (audio starts before splash so splash can react to music)
        log.info('Startup: initializing audio subsystem')
        audio_manager = AudioManager(self.cfg, state_store=self._runtime_state)
        mixer_profile = self._boot_profile == PROFILE_MIXER
        if mixer_profile:
            # Mixer profile: capture is never started — the mixer owns its own
            # audio; get_audio_data() on the unstarted manager returns silent
            # buffers and skips the fallback prober. No input device claimed.
            log.info('Mixer profile: audio capture skipped')
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
        audio_attempt_count = 0 if mixer_profile else total_audio_attempts
        audio_start_ok = mixer_profile   # skipped counts as "not a failure"
        for attempt in range(1, audio_attempt_count + 1):
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
        boot.mark('audio_start')

        # Kick off background image decoding so disk I/O overlaps with the splash.
        # warm_cache() after the splash will find bytes already in memory and
        # only need to do fast GL uploads.
        # Mixer profile: no effect discovery (skips every effect-module import)
        # and therefore no prescans — this is most of the ~1s boot target.
        _pre_effects = [] if mixer_profile else get_effects()
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

        # Background the ProjectM preset-catalog scan (the ~10k-file disk walk,
        # the non-GL half of warm_up) so it overlaps the splash; warm_up after
        # the splash finds the catalog cached and only builds the GL bridge.
        for _cls in _pre_effects:
            if getattr(_cls, 'NAME', '') == 'ProjectM Presets' and hasattr(_cls, 'prescan_catalog_async'):
                _pm_cfg = self.cfg.get('effects', 'ProjectMEffect', default={}) or {}
                if bool(_pm_cfg.get('enabled', True)) and self._projectm_operator_enabled():
                    try:
                        _cls.prescan_catalog_async(_pm_cfg)
                    except Exception as _exc:
                        log.debug('ProjectM prescan skipped: %s', _exc)
                break

        # Background the Media library walk + tag reads (the controller's
        # dominant construction cost) so it overlaps the splash instead of
        # stalling boot after it; the controller (built after the splash)
        # consumes the cached scan.
        _media_cfg = self.cfg.get('media', default={}) or {}
        if (isinstance(_media_cfg, dict) and bool(_media_cfg.get('enabled', False))
                and self._profile_allows('media')):
            try:
                _media_cls = _load_media_controller_class()
                if hasattr(_media_cls, 'prescan_async'):
                    _media_cls.prescan_async(_media_cfg)
            except Exception as _exc:
                log.debug('Media prescan skipped: %s', _exc)

        boot.mark('pre_splash_async_kickoff')

        # Splash screen — shown before any effect loads. `[splash] enabled`
        # is a standalone gate; the mixer profile forces it off.
        splash_path = str(resolve_path(self.cfg.get("splash", "image", default="images/unicorn-viz-01.png")))
        splash_enabled = (
            bool(self.cfg.get('splash', 'enabled', default=True))
            and not mixer_profile
        )
        splash_duration_audio = _SPLASH_TOTAL_DURATION
        splash_duration_silent = _SPLASH_TOTAL_DURATION
        log.info('Startup: entering splash setup (path=%s enabled=%s)',
                 splash_path, splash_enabled)
        if splash_enabled and Path(splash_path).exists():
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

        boot.mark('splash (blocking)')

        # Store splash config for later replay via hotkey U
        self._splash_config = {
            "path": splash_path,
            "duration_audio": splash_duration_audio,
            "duration_silent": splash_duration_silent,
            "audio_manager": audio_manager,
        }

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
        boot.mark('midi')

        effects = [] if mixer_profile else get_effects()
        if not effects and not mixer_profile:
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
        boot.mark('effects_scan + image_warm(GL)')

        for effect_cls in effects:
            if getattr(effect_cls, 'NAME', '') == 'ProjectM Presets' and hasattr(effect_cls, 'warm_up'):
                pm_cfg = self.cfg.get('effects', 'ProjectMEffect', default={}) or {}
                if bool(pm_cfg.get('enabled', True)) and self._projectm_operator_enabled():
                    try:
                        effect_cls.warm_up(self._ctx, self._width, self._height, pm_cfg)
                    except Exception as exc:
                        log.warning('ProjectM warm-up failed (non-fatal): %s', exc)
                break
        boot.mark('projectm_warmup')

        playlist = Playlist(effects, self.cfg)
        playlist.set_disabled(self._disabled_effects)
        playlist.set_hotkey_pins(self._hotkey_pins)
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
            tooltips_enabled=bool(self.cfg.get('tooltips', 'enabled', default=True)),
            tooltip_delay_s=float(self.cfg.get('tooltips', 'delay_s', default=0.55)),
        )
        self._overlays = overlays
        if mixer_profile:
            # Effect/visual hotkeys act on nothing in this profile — advertise
            # only the sections that still mean something (mixer-only plan §8).
            overlays.set_core_help_filter(('Help Usage', 'Basics'))

        # midi-controllers-01: register help-modal renderer now that Overlays is ready.
        if _mc_register_all is not None:
            try:
                _mc_register_all(None, overlays)
            except Exception as _exc:
                log.debug('midi-controllers-01 renderer registration failed: %s', _exc)

        # midi-controllers-01: init MidiControllerManager now that vj_api is live.
        if _mc_register_all is not None:
            try:
                _mc_register_all(None, None, self.vj_api)
            except Exception as _exc:
                log.debug('midi-controllers-01 controller init skipped: %s', _exc)

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

        dynamic_help.extend(discover_dropin_help_entries(self._dropin_dir_filter()))
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
        boot.mark('playlist + overlays + hotkeys')

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
            if load_spotify and self._profile_allows('spotify'):
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
            boot.mark('subsystem: spotify')

            # Local media player controller (optional drop-in).
            media_cfg = self.cfg.get('media', default={}) or {}
            if not isinstance(media_cfg, dict):
                media_cfg = {}
            if bool(media_cfg.get('enabled', False)) and self._profile_allows('media'):
                try:
                    media_cls = _load_media_controller_class()
                    self._media = media_cls(self, media_cfg)
                    if bool(getattr(self._media, 'enabled', False)):
                        self.vj_api.register_subsystem('media', self._media)
                        key_handler = getattr(self._media, 'handle_key', None)
                        if callable(key_handler):
                            self.vj_api.register_key_handler('media', key_handler)
                        log.info('MediaController loaded from drop-in')
                        self._maybe_auto_play_media()
                    else:
                        self._media = None
                except Exception as exc:
                    self._media = None
                    log.warning('MediaController not available: %s', exc)
            boot.mark('subsystem: media (library scan)')

            # Live chat overlay controller (optional drop-in).
            chat_cfg = self.cfg.get('chat', default={}) or {}
            if not isinstance(chat_cfg, dict):
                chat_cfg = {}
            if bool(chat_cfg.get('enabled', False)) and self._profile_allows('chat'):
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
            if bool(audio_out_cfg.get('enabled', True)) and self._profile_allows('audio_out'):
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

            self._load_dj_mixer_subsystem()
            boot.mark('subsystem: dj_mixer')

            # OSC control-surface bridge (optional drop-in).
            osc_cfg = self.cfg.get('osc', default={}) or {}
            if not isinstance(osc_cfg, dict):
                osc_cfg = {}
            if bool(osc_cfg.get('enabled', True)) and self._profile_allows('osc'):
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
            if bool(lyrics_cfg.get('enabled', True)) and self._profile_allows('lyrics'):
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
            if self._profile_allows('auto_vj'):
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
            if self._profile_allows('grand_finale'):
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
            if bool(control_room_cfg.get('enabled', False)) and self._profile_allows('control_room'):
                self._control_room_startup_cfg = dict(control_room_cfg)
                self._control_room_startup_frames_remaining = 8
                log.info('ControlRoomController scheduled for startup after %d audience frames', self._control_room_startup_frames_remaining)
        else:
            log.info('Safe mode enabled: skipping Spotify, Auto VJ, Grand Finale, and Control Room drop-ins')
            if self._boot_profile == PROFILE_MIXER:
                # safe_mode + mixer profile: the profile wins for the mixer
                # itself (§6 of the mixer-only plan) — everything else above
                # stayed skipped.
                self._load_dj_mixer_subsystem()
                boot.mark('subsystem: dj_mixer (safe-mode carve-out)')

        # Load first effect (mixer profile: no effects — the window stays
        # black behind overlays until hosted mode (P2) presents the console).
        _first_cls = playlist.current()
        self._current_effect = (
            self._instantiate(_first_cls) if _first_cls is not None else None
        )
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
        # Video output interop (v4l2loopback / future PipeWire, NDI).
        # Guarded per the drop-in independence rules: absent drop-in, absent
        # config, or a constructor failure all degrade to None and the app
        # simply publishes nothing. Loads by default like any other
        # drop-in (enabled=True); actually publishing at boot is a
        # separate, opt-in start_enabled flag the controller reads itself
        # (this subsystem opens a device/connection and runs a writer
        # thread, so "loaded" and "actively running" are kept distinct).
        self._video_out = None
        if not self._safe_mode:
            _vo_cfg = self.cfg.get('video_out', default={}) or {}
            if isinstance(_vo_cfg, dict) and bool(_vo_cfg.get('enabled', True)):
                try:
                    self._video_out = _load_video_out_controller_class()(self, _vo_cfg)
                    self.register_subsystem('video_out', self._video_out)
                    key_handler = getattr(self._video_out, 'handle_key', None)
                    if callable(key_handler):
                        self.vj_api.register_key_handler('video_out', key_handler)
                except Exception as exc:
                    log.warning('Video output interop unavailable: %s', exc)
                    self._video_out = None
        stream_cls = (
            _NullRTMPStreamer
            if self._safe_mode or not self._profile_allows('streaming')
            else _load_rtmp_streamer_class()
        )
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

        if not self._safe_mode and self._profile_allows('cta'):
            cta_cfg = self.cfg.get('cta', default={}) or {}
            if not isinstance(cta_cfg, dict):
                cta_cfg = {}
            try:
                cta_cls = _load_cta_controller_class()
                self._cta_controller = cta_cls(cta_cfg)
                self._cta_controller.set_vj_api(self.vj_api)
                self.vj_api.register_key_handler('cta', self._cta_controller.handle_key)
                self.vj_api.register_subsystem('cta', self._cta_controller)
                log.info('CTAController loaded from drop-in')
            except Exception as exc:
                log.warning('CTAController not available: %s', exc)

        if not self._safe_mode and self._profile_allows('banner'):
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
        boot.mark('subsystems: remainder')
        self._sync_recording_overlay()
        if self._recorder.enabled and self._recorder.auto_record:
            started, _ = self.start_recording()
            if started:
                log.info('Auto-record enabled')
        boot.mark('finalize (recording/overlay sync)')
        boot.summary()
        self._running = True
        # First-run tour: offered on the first-ever launch (missing state key)
        # and on every startup until its show-on-startup toggle is unchecked.
        self._maybe_open_tour_on_startup()

        prev_time = time.perf_counter()
        self._session_started_at = time.monotonic()
        # Mixer profile: closing the console means quitting — there is
        # nothing to fall back to (mixer-only plan §4). Tracked as
        # open-then-closed so a slow first open doesn't quit instantly.
        mixer_console_was_open = False
        self._demo_timer = 0.0
        self._effect_duration = float(
            self.cfg.get('demo', 'effect_duration', default=60)
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
            presets_active = bool(getattr(self._overlays, 'presets_visible', False))

            # Poll events
            event = sdl2.SDL_Event()
            while sdl2.SDL_PollEvent(event):
                if self._dispatch_claimed_window_event(event):
                    continue
                if event.type == sdl2.SDL_QUIT:
                    self.request_exit()
                elif event.type == sdl2.SDL_KEYDOWN:
                    if self._overlays.context_menu_open:
                        # Any key dismisses the context menu (swallowed).
                        self._update_ctrl_state(event.key.keysym.sym, True)
                        self._overlays.close_context_menu()
                        continue
                    if self._overlays.config_editor_open:
                        # Editor captures navigation/close; other keys swallowed.
                        self._update_ctrl_state(event.key.keysym.sym, True)
                        _sym = event.key.keysym.sym
                        if self._overlays.config_editor_name_mode:
                            # Profile-name text entry captures typing.
                            if _sym == sdl2.SDLK_ESCAPE:
                                self._overlays.set_config_editor_name_mode(False)
                            elif _sym in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
                                _name = self._overlays.config_editor_name_text.strip()
                                self._overlays.set_config_editor_name_mode(False)
                                if _name:
                                    self.save_config_profile(_name)
                                    self._overlays.flash_message(f'Profile saved: {_name}', 1.6)
                            elif _sym == sdl2.SDLK_BACKSPACE:
                                self._overlays.set_config_editor_name_text(
                                    self._overlays.config_editor_name_text[:-1]
                                )
                            else:
                                _ch = _name_char_for_keysym(_sym, event.key.keysym.mod)
                                if _ch:
                                    self._overlays.set_config_editor_name_text(
                                        self._overlays.config_editor_name_text + _ch
                                    )
                            continue
                        if self._overlays.config_editor_capture_mode:
                            # Hotkeys tab: the very next keydown becomes the
                            # candidate chord for the action being rebound.
                            if not event.key.repeat:
                                if _sym == sdl2.SDLK_ESCAPE:
                                    self.cancel_hotkey_capture()
                                    self._overlays.flash_message('Rebind cancelled', 1.2)
                                else:
                                    _msg = self.apply_hotkey_capture(_sym, event.key.keysym.mod)
                                    if _msg:
                                        self._overlays.flash_message(_msg, 1.8)
                            continue
                        if _sym in (sdl2.SDLK_ESCAPE, sdl2.SDLK_c):
                            if not event.key.repeat:
                                self._overlays.close_config_editor()
                        elif _sym == sdl2.SDLK_LEFT:
                            if not event.key.repeat:
                                self._overlays.move_config_editor_tab(-1)
                        elif _sym == sdl2.SDLK_RIGHT:
                            if not event.key.repeat:
                                self._overlays.move_config_editor_tab(1)
                        elif _sym == sdl2.SDLK_TAB:
                            if not event.key.repeat:
                                self._overlays.toggle_config_editor_focus()
                        elif _sym == sdl2.SDLK_UP:
                            self._overlays.move_config_editor_row(-1)
                        elif _sym == sdl2.SDLK_DOWN:
                            self._overlays.move_config_editor_row(1)
                        elif _sym in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
                            if not event.key.repeat and self._overlays.config_editor_tab_name == 'Hotkeys':
                                _row = self._overlays.config_editor_selected_row()
                                if _row is not None and _row.get('kind') == 'bind':
                                    self.start_hotkey_capture(str(_row.get('action', '')))
                        elif _sym == sdl2.SDLK_BACKSPACE:
                            if self._overlays.config_editor_tab_name == 'Hotkeys':
                                _row = self._overlays.config_editor_selected_row()
                                if _row is not None and _row.get('kind') == 'bind':
                                    _msg = self.reset_hotkey_to_default(str(_row.get('action', '')))
                                    if _msg:
                                        self._overlays.flash_message(_msg, 1.4)
                        elif _sym == sdl2.SDLK_LEFTBRACKET:
                            self._config_editor_adjust(-1.0)
                        elif _sym == sdl2.SDLK_RIGHTBRACKET:
                            self._config_editor_adjust(1.0)
                        continue
                    self._update_ctrl_state(event.key.keysym.sym, True)
                    if not event.key.repeat:
                        try:
                            hotkeys.handle(event.key.keysym.sym, event.key.keysym.mod)
                        except Exception:
                            log.exception(
                                'Hotkey handler crashed (sym=%d mod=%d) — '
                                'keypress dropped',
                                event.key.keysym.sym, event.key.keysym.mod,
                            )
                elif event.type == sdl2.SDL_KEYUP:
                    self._update_ctrl_state(event.key.keysym.sym, False)
                elif event.type == sdl2.SDL_TEXTINPUT and self._text_input_handlers:
                    try:
                        _text = bytes(event.text.text).partition(b'\x00')[0].decode('utf-8', errors='replace')
                    except Exception:
                        _text = ''
                    if _text:
                        for _ti_handler in list(self._text_input_handlers.values()):
                            try:
                                _ti_handler(_text)
                            except Exception:
                                log.warning('Text input handler raised: %s', _ti_handler)
                elif event.type == sdl2.SDL_WINDOWEVENT:
                    if event.window.event == sdl2.SDL_WINDOWEVENT_RESIZED:
                        self._on_resize(
                            event.window.data1, event.window.data2
                        )
                    elif event.window.event == sdl2.SDL_WINDOWEVENT_FOCUS_LOST:
                        self._ctrl_held = False
                        self._set_cursor_visible(False)
                    elif event.window.event == sdl2.SDL_WINDOWEVENT_FOCUS_GAINED:
                        self._set_cursor_visible(self._cursor_should_be_visible())
                        self._refresh_display_state('focus gained')
                    elif event.window.event in (
                        getattr(sdl2, 'SDL_WINDOWEVENT_MOVED', -1),
                        getattr(sdl2, 'SDL_WINDOWEVENT_DISPLAY_CHANGED', -1),
                    ):
                        self._refresh_display_state('window moved')
                elif event.type == sdl2.SDL_MOUSEWHEEL:
                    dy = int(event.wheel.y)
                    if self._overlays.config_editor_open:
                        if dy != 0:
                            self._config_editor_adjust(float(dy))
                        continue
                    if presets_active:
                        if dy != 0:
                            self._overlays.presets_browser.move_selection(-dy)
                        continue
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
                    if self._overlays.context_menu_open:
                        try:
                            hit = self._overlay_mouse_coords(
                                float(event.motion.x), float(event.motion.y),
                                self._primary_display_viewport(),
                            )
                            if hit is not None:
                                self._overlays.handle_context_menu_motion(hit[0], hit[1])
                        except Exception as exc:
                            log.warning('Context menu hover handling failed: %s', exc)
                        continue
                    if self._overlays.tour_visible:
                        try:
                            hit = self._overlay_mouse_coords(
                                float(event.motion.x), float(event.motion.y),
                                self._primary_display_viewport(),
                            )
                            if hit is not None:
                                self._overlays.handle_tour_motion(hit[0], hit[1])
                        except Exception as exc:
                            log.warning('Tour hover handling failed: %s', exc)
                        continue
                    if self._overlays.config_editor_open:
                        try:
                            hit = self._overlay_mouse_coords(
                                float(event.motion.x), float(event.motion.y),
                                self._primary_display_viewport(),
                            )
                            if hit is not None:
                                self._overlays.handle_config_editor_motion(hit[0], hit[1])
                        except Exception as exc:
                            log.warning('Config editor hover handling failed: %s', exc)
                        continue
                    if presets_active:
                        try:
                            hit = self._overlay_mouse_coords(
                                float(event.motion.x), float(event.motion.y),
                                self._primary_display_viewport(),
                            )
                            if hit is not None:
                                self._overlays.handle_presets_mouse_motion(hit[0], hit[1])
                        except Exception as exc:
                            log.warning('Presets hover handling failed: %s', exc)
                        continue
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
                    if self._overlays.context_menu_open:
                        # Menu takes priority: dispatch selection or dismiss.
                        try:
                            hit = self._overlay_mouse_coords(
                                float(event.button.x), float(event.button.y),
                                self._primary_display_viewport(),
                            )
                        except Exception:
                            hit = None
                        if event.button.button == sdl2.SDL_BUTTON_LEFT and hit is not None:
                            idx = self._overlays.handle_context_menu_click(hit[0], hit[1])
                            if idx >= 0:
                                self._overlays.close_context_menu()
                                self._activate_context_menu_entry(idx)
                            elif idx == -1:
                                self._overlays.close_context_menu()
                            # idx == -2: click landed on a header/gap; keep open.
                        else:
                            # Right/middle click, or a click outside the canvas.
                            self._overlays.close_context_menu()
                        continue
                    if self._overlays.tour_visible:
                        if event.button.button == sdl2.SDL_BUTTON_LEFT:
                            try:
                                hit = self._overlay_mouse_coords(
                                    float(event.button.x), float(event.button.y),
                                    self._primary_display_viewport(),
                                )
                            except Exception:
                                hit = None
                            if hit is not None:
                                action = self._overlays.handle_tour_click(hit[0], hit[1])
                                if action == 'prev':
                                    self._overlays.tour_prev()
                                    self.save_tour_state()
                                elif action == 'next':
                                    self.tour_advance()
                                elif action == 'close':
                                    self.close_tour()
                                elif action == 'startup':
                                    self._overlays.tour_toggle_startup()
                                    self.save_tour_state()
                        continue
                    if self._overlays.config_editor_open:
                        if event.button.button == sdl2.SDL_BUTTON_LEFT:
                            try:
                                hit = self._overlay_mouse_coords(
                                    float(event.button.x), float(event.button.y),
                                    self._primary_display_viewport(),
                                )
                                if hit is not None:
                                    self._overlays.handle_config_editor_click(hit[0], hit[1])
                                    self._apply_config_editor_action()
                            except Exception as exc:
                                log.warning('Config editor click handling failed: %s', exc)
                        continue
                    if (event.button.button == sdl2.SDL_BUTTON_RIGHT
                            and not (presets_active or eb_active or manager_modal_active)
                            and not self._overlays.blocking_modal_open):
                        try:
                            hit = self._overlay_mouse_coords(
                                float(event.button.x), float(event.button.y),
                                self._primary_display_viewport(),
                            )
                            if hit is None:
                                # Span/mirror: the click can map outside the
                                # primary-display sub-viewport. Open the menu at
                                # the overlay-canvas centre so right-click always
                                # works instead of silently doing nothing.
                                ow = float(getattr(self._overlays, '_width', self._width) or self._width)
                                oh = float(getattr(self._overlays, '_height', self._height) or self._height)
                                hit = (ow * 0.5, oh * 0.5)
                            self._open_context_menu_at(hit[0], hit[1])
                        except Exception as exc:
                            log.warning('Context menu open failed: %s', exc)
                        continue
                    if presets_active:
                        if event.button.button == sdl2.SDL_BUTTON_LEFT:
                            try:
                                hit = self._overlay_mouse_coords(
                                    float(event.button.x), float(event.button.y),
                                    self._primary_display_viewport(),
                                )
                                if hit is not None and self._overlays.handle_presets_mouse_click(hit[0], hit[1]):
                                    name = self.presets_load_selected()
                                    if name:
                                        self._overlays.flash_message(f'Preset loaded: {name}', 1.6)
                            except Exception as exc:
                                log.warning('Presets click handling failed: %s', exc)
                        continue
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

            # Recover from a crashed current effect: advance to the next
            # non-quarantined effect instead of holding a black frame.
            if self._effect_crash_recover:
                self._effect_crash_recover = False
                if self._current_effect is None and self._next_effect is None:
                    self._demo_timer = 0.0
                    self._switch_effect(playlist.advance())

            # Auto-playlist advance (suppressed while locked to one effect)
            if (not manager_modal_active and not eb_active and not presets_active
                    and not self._paused
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
                    if next_cls is not None:
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
                    try:
                        self._current_effect.update(dt, audio_cur)
                    except Exception:
                        self._handle_effect_crash(self._current_effect, 'update')
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
                    try:
                        self._next_effect.update(dt, audio_next)
                    except Exception:
                        self._handle_effect_crash(self._next_effect, 'update')
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
            # Announcement sources come from the now-playing hub; older
            # spotify-01/media-01 builds that don't self-register are added
            # here so mixed versions keep working.
            _hub = self.now_playing
            if self._media is not None and 'media' not in _hub.names():
                _snap_fn = getattr(self._media, 'snapshot', None)
                if callable(_snap_fn):
                    _hub.register('media', _snap_fn, priority=20)
            if self._spotify is not None and 'spotify' not in _hub.names():
                _snap_fn = getattr(self._spotify, 'snapshot', None)
                if callable(_snap_fn):
                    _hub.register('spotify', _snap_fn, priority=10, ambient=True)
            _np_active = _hub.active()

            now_playing_visible = 'YES' if _np_active is not None else 'NO'
            now_playing_status = 'OFF'
            now_playing_length = '--:--'
            _now_playing_snap: dict | None = None
            if _np_active is not None:
                _now_playing_snap = _np_active[1]
                if True:
                    if isinstance(_now_playing_snap, dict):
                        available = bool(_now_playing_snap.get('available', False))
                        playing = bool(_now_playing_snap.get('is_playing', False))
                        raw_status = str(_now_playing_snap.get('status', '') or '').strip().upper()
                        if available and raw_status:
                            now_playing_status = raw_status
                        elif available:
                            now_playing_status = 'PLAYING' if playing else 'PAUSED'
                        dur_b = max(0.0, float(_now_playing_snap.get('duration_s', 0.0) or 0.0))
                        total_b = max(0, int(dur_b))
                        mm_b, ss_b = divmod(total_b, 60)
                        hh_b, mm_b = divmod(mm_b, 60)
                        now_playing_length = f'{hh_b:02d}:{mm_b:02d}:{ss_b:02d}' if hh_b > 0 else f'{mm_b:02d}:{ss_b:02d}'
            overlays.set_overlay_banner(*_hub.banner_args(
                _now_playing_snap, now_playing_visible == 'YES',
                now_playing_status))

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

                # Now-playing HUD-only fields (clipped strings, progress).
                # spotify_auth_* stay Spotify-specific -- media-01 (local
                # playback) has no auth/OAuth concept, so a generic name
                # would be misleading for these two.
                spotify_auth_visible = 'NO'
                spotify_auth_status = 'OFF'
                now_playing_track = '-'
                now_playing_artist = '-'
                now_playing_album = '-'
                now_playing_prev_artist = '-'
                now_playing_prev_title = '-'
                now_playing_progress = '--:--/--:-- 0%'
                if isinstance(_now_playing_snap, dict):
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

                    now_playing_track = _clip(str(_now_playing_snap.get('title', '') or ''), 24)
                    now_playing_artist = _clip(str(_now_playing_snap.get('artist', '') or ''), 24)
                    now_playing_album = _clip(str(_now_playing_snap.get('album', '') or ''), 24)
                    now_playing_prev_artist = _clip(str(_now_playing_snap.get('previous_artist', '') or ''), 24)
                    now_playing_prev_title = _clip(str(_now_playing_snap.get('previous_title', '') or ''), 24)
                    pos = max(0.0, float(_now_playing_snap.get('position_s', 0.0) or 0.0))
                    dur = max(0.0, float(_now_playing_snap.get('duration_s', 0.0) or 0.0))
                    pct = int(round(min(100.0, (pos / dur) * 100.0))) if dur > 0.0 else 0
                    now_playing_progress = f'{_fmt_secs(pos)}/{_fmt_secs(dur)} {pct}%'
                    spotify_auth_visible = 'YES' if bool(_now_playing_snap.get('web_api_enabled', False)) else 'NO'
                    auth_status = str(_now_playing_snap.get('auth_status', '') or '').strip()
                    display_name = str(_now_playing_snap.get('display_name', '') or '').strip()
                    if bool(_now_playing_snap.get('auth_ready', False)):
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
                'audio_profile_score': (
                    getattr(self._auto_vj, 'current_profile_score_hud', '')
                    if self._auto_vj is not None
                    else ''
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
                'auto_vj_downbeat_pulse': (
                    getattr(self._auto_vj, 'hud_downbeat_pulse', 0.0)
                    if self._auto_vj is not None
                    else 0.0
                ),
                'auto_vj_beat_pulse': (
                    getattr(self._auto_vj, 'hud_beat_pulse', 0.0)
                    if self._auto_vj is not None
                    else 0.0
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
                'now_playing_visible': now_playing_visible,
                'spotify_auth_visible': spotify_auth_visible,
                'spotify_auth_status': spotify_auth_status,
                'now_playing_status': now_playing_status,
                'now_playing_track': now_playing_track,
                'now_playing_artist': now_playing_artist,
                'now_playing_album': now_playing_album,
                'now_playing_length': now_playing_length,
                'now_playing_progress': now_playing_progress,
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

            # Feed the configuration editor its live data while open.
            if overlays.config_editor_open:
                self._push_config_editor_model()
            else:
                self._config_editor_was_open = False

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
            self._present_hosted_mixer()
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
            need_frame_for_recording = False
            if self._recorder is not None:
                _rec_failure = self._recorder.consume_failure()
                if _rec_failure:
                    overlays.flash_message(
                        f'RECORDING FAILED — {_rec_failure}', 6.0
                    )
                    self._recorder.stop()
                    self._sync_recording_overlay()
                else:
                    need_frame_for_recording = bool(self._recorder.is_recording)

            need_frame_for_streaming = (
                self._streamer is not None and self._streamer.is_streaming
            )
            need_frame_for_subsystems = self._subsystems_need_frame_capture()
            # Throttle the subsystem preview readback so it fires at the
            # fastest active consumer's requested cap (see
            # _subsystem_preview_capture_interval_s; defaults to 10 fps when
            # no consumer opts into a faster/slower ceiling) rather than the
            # full audience output frame rate.  Streaming readback is not
            # throttled; it must produce one frame per rendered frame to keep
            # the RTMP muxer in sync.
            #
            # The subsystem preview no longer rides the full-resolution
            # streaming readback: it now uses _read_preview_frame(), which
            # downsamples the canvas on the GPU first so the glReadPixels
            # transfer is a couple of MB at most instead of 24 MB on a
            # spanned canvas.  Full-res frames are still reused for the
            # preview when streaming already produced one this frame.
            #
            # Frame tap: recording and streaming both want the identical
            # full-resolution picture. They used to read it back
            # independently — two GPU->CPU transfers of the same frame every
            # frame with both live, one of them synchronous. The tap decides
            # who is due, we read **once**, and everyone due shares it.
            # See unicornviz/frame_tap.py.
            _tap_now = time.monotonic()
            self._frame_tap.sync('recording', need_frame_for_recording)
            self._frame_tap.sync('streaming', need_frame_for_streaming)
            _vo = self._video_out
            _vo_wants = False
            if _vo is not None:
                try:
                    _vo_wants = bool(_vo.wants_frame())
                except Exception:
                    _vo_wants = False
            self._frame_tap.sync(
                'video_out', _vo_wants,
                max_fps=(_vo.frame_fps_cap() if _vo_wants else 0.0),
            )
            due = self._frame_tap.begin_frame(_tap_now)
            stream_frame: bytes | None = None
            if due:
                try:
                    stream_frame = self._read_streaming_frame()
                except Exception as exc:
                    log.error('Output frame readback failed: %s', exc)
                    stream_frame = None
                if stream_frame is not None:
                    self._frame_tap.commit(due, _tap_now)
            if stream_frame is not None:
                # Keep the frame for same-frame reuse (screenshots): it is
                # already on the CPU, so a screenshot taken while recording
                # or streaming costs no extra readback at all.
                self._last_output_frame = (stream_frame, self._width, self._height)
                self._last_output_frame_t = _tap_now
            if 'recording' in due and stream_frame is not None:
                self._write_recording_frame(stream_frame)
            if 'video_out' in due and stream_frame is not None and _vo is not None:
                try:
                    _vo.submit_frame(stream_frame, self._width, self._height)
                except Exception as exc:
                    log.warning('Video output publish failed: %s', exc)
            # Zero-copy publish (PipeWire/DMA-BUF): hand over the GL
            # framebuffer name and let the backend blit on the GPU. This
            # deliberately does NOT go through the frame tap — the whole
            # point is that no frame is ever read back to the CPU.
            if _vo is not None:
                try:
                    if _vo.wants_texture():
                        _src = (
                            self._fbo_a
                            if (self._is_mirror_mode(self._display_mode)
                                and bool(self._mirror_rects)
                                and self._fbo_a is not None)
                            else self._ensure_screen_copy_fbo()
                        )
                        if _src is not self._fbo_a:
                            self._ctx.copy_framebuffer(_src, self._ctx.screen)
                        _vo.submit_texture(
                            int(_src.glo), self._width, self._height)
                except Exception as exc:
                    log.warning('Video output texture publish failed: %s', exc)

            subsystem_capture_due = False
            if need_frame_for_subsystems:
                _now = time.monotonic()
                if _now - self._last_subsystem_frame_capture_time >= self._subsystem_preview_capture_interval_s():
                    subsystem_capture_due = True
                    self._last_subsystem_frame_capture_time = _now
            if subsystem_capture_due:
                if stream_frame is not None:
                    self._update_frame_capture_snapshot(stream_frame)
                else:
                    try:
                        preview = self._read_preview_frame()
                    except Exception as exc:
                        log.error('Preview frame readback failed: %s', exc)
                        preview = None
                    if preview is not None:
                        pframe, pw, ph = preview
                        self._update_frame_capture_snapshot(pframe, pw, ph)
                    else:
                        self._update_frame_capture_snapshot(None)
            elif not need_frame_for_subsystems:
                self._update_frame_capture_snapshot(None)
            if 'streaming' in due and stream_frame is not None:
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

            self._present_subsystems()
            if mixer_profile and self._dj_mixer is not None:
                if bool(getattr(self._dj_mixer, 'is_open', False)):
                    mixer_console_was_open = True
                elif mixer_console_was_open:
                    log.info('Mixer profile: console closed — quitting')
                    self.request_exit()
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

        # Cleanup (also reachable via ensure_shutdown() if run() raises)
        self._shutdown_runtime()

    def ensure_shutdown(self) -> None:
        """Idempotent runtime teardown for abnormal exits.

        ``run()`` calls ``_shutdown_runtime()`` on its normal path; callers
        (``__main__``) invoke this in a ``finally`` so audio/MIDI/recorder
        threads and SDL are torn down even when ``run()`` raises.
        """
        if not self._shutdown_complete:
            self._shutdown_runtime()

    def _shutdown_runtime(self) -> None:
        """Tear down subsystems, GL resources, and SDL. Runs at most once."""
        if self._shutdown_complete:
            return
        self._shutdown_complete = True
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
        self._log_deleted_effects_summary()
        if self._audio_manager is not None:
            self._audio_manager.stop()
        if self._midi_manager is not None:
            self._midi_manager.stop()
        if self._webcam_system is not None:
            self._persist_webcam_runtime_state()
            self._webcam_system.destroy()
            self._webcam_system = None
        # GL teardown can fail when shutting down after a crash (dead
        # context); contain it so SDL teardown below still runs.
        try:
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
            if self._video_postfx is not None:
                self._video_postfx.destroy()
                self._video_postfx = None
            if self._current_effect:
                self._current_effect.destroy()
            if self._next_effect:
                self._next_effect.destroy()
            overlays = getattr(self, '_overlays', None)
            if overlays is not None:
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
            self._release_readback_pbos()
        except Exception:
            log.warning('GL teardown failed during shutdown', exc_info=True)
        try:
            self._runtime_state.save()
        except Exception:
            log.warning('Runtime state save failed during shutdown', exc_info=True)
        if self._gl_context:
            sdl2.SDL_GL_DeleteContext(self._gl_context)
            self._gl_context = None
        if self._window:
            sdl2.SDL_DestroyWindow(self._window)
            self._window = None
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
        except Exception:
            self._handle_effect_crash(effect, 'render')
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
            self._release_fbo(existing)
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
        self._release_fbo(self._fbo_a)
        self._release_fbo(self._fbo_b)
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

    def midi_send_output(self, port_hint: str, message: list[int]) -> bool:
        """Send a raw MIDI message to the first output port matching *port_hint*.

        Lazily opens and caches a MidiOut; subsequent calls with the same hint
        reuse the open port.  If the hint changes the port is reopened.
        Returns True on success.
        """
        if not port_hint:
            return False
        if self._midi_out is None:
            self._midi_out = MidiOut()
        if not self._midi_out.available or self._midi_out.hint != port_hint:
            self._midi_out.open(port_hint)
        return self._midi_out.send(list(message))

    def fire_midi_action(self, action: str) -> bool:
        """Invoke a drop-in registered MIDI action handler.

        Called by the MIDI dispatch chain after built-in action lookup fails.
        Returns True if a handler was found and called.
        """
        return self.vj_api.fire_midi_action(action)

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
        self._release_fbo(self._fbo_a)
        self._release_fbo(self._fbo_b)
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

    def _ensure_preview_fbo(self, width: int, height: int) -> moderngl.Framebuffer:
        """Lazily (re)allocate the small FBO used for downsampled preview reads."""
        w = max(1, int(width))
        h = max(1, int(height))
        if self._preview_fbo is None or (self._preview_fbo.width, self._preview_fbo.height) != (w, h):
            self._release_fbo(self._preview_fbo)
            tex = self._ctx.texture((w, h), 4)
            self._preview_fbo = self._ctx.framebuffer(color_attachments=[tex])
        return self._preview_fbo

    def _read_preview_frame(self) -> tuple[bytes, int, int] | None:
        """Read a downsampled RGB24 frame for subsystem preview panels.

        Renders the canvas texture through the present shader into a small
        FBO capped at _PREVIEW_MAX_WIDTH wide (aspect preserved), then reads
        that.  The GPU does the shrink, so the readback moves ~1.5 MB instead
        of the full canvas (24 MB on a 3840x2163 spanned canvas) — the
        full-size synchronous read was the dominant GL-pipeline stall while a
        control-room / dj-mixer preview was open.  moderngl's
        copy_framebuffer() cannot scale (it blits min(src, dst) 1:1), hence
        the textured-quad pass.

        Returns ``(rgb_bytes, width, height)`` or ``None``.
        """
        if self._ctx is None or self._present_vao is None:
            return None
        # Stage the canvas into an exactly canvas-sized FBO first so the
        # quad pass samples only real content (fbo_a / the SDL drawable can
        # be larger than the logical canvas).  copy_framebuffer copies the
        # overlapping region 1:1 from the origin, which is the canvas.
        staging = self._ensure_screen_copy_fbo()
        mirror_mode_active = self._is_mirror_mode(self._display_mode) and bool(self._mirror_rects)
        if mirror_mode_active and self._fbo_a is not None:
            self._ctx.copy_framebuffer(staging, self._fbo_a)
        else:
            # Never read/sample self._ctx.screen directly — see the comment
            # on self._screen_copy_fbo's declaration.
            self._ctx.copy_framebuffer(staging, self._ctx.screen)
        pw = min(int(self._width), _PREVIEW_MAX_WIDTH)
        ph = max(1, round(int(self._height) * pw / max(1, int(self._width))))
        fbo = self._ensure_preview_fbo(pw, ph)
        fbo.use()
        self._ctx.viewport = (0, 0, pw, ph)
        staging.color_attachments[0].use(location=0)
        self._present_prog['tex'].value = 0
        self._present_vao.render(moderngl.TRIANGLE_STRIP)
        frame = fbo.read(viewport=(0, 0, pw, ph), components=3, alignment=1)
        # Restore the state the post-readback overlay pass expects — the
        # non-mirror branch does not rebind the screen itself.
        self._ctx.screen.use()
        self._ctx.viewport = (0, 0, self._width, self._height)
        return frame, pw, ph

    def _present_hosted_mixer(self) -> None:
        """Draw the hosted mixer console into the main window.

        The mixer-only profile has no effects, so without this the window is
        black.  The console is produced on the mixer's own render thread as a
        raw RGBA buffer -- exactly the buffer it used to upload to its second
        window -- so this uploads and draws it, and the overlay pass that runs
        straight after lands on top of it just as it would on an effect.

        A no-op in every other profile, and whenever the mixer has not
        produced a frame yet, so the normal boot path is untouched.
        """
        mixer = self._dj_mixer
        if mixer is None or self._boot_profile != PROFILE_MIXER:
            return
        frame_fn = getattr(mixer, 'hosted_frame', None)
        if not callable(frame_fn):
            return                       # older drop-in: nothing to present
        got = frame_fn()
        if not got:
            return
        raw, (fw, fh), fid = got
        if fw <= 0 or fh <= 0 or not raw:
            return
        try:
            tex = self._hosted_mixer_tex
            if tex is None or tex.size != (fw, fh):
                if tex is not None:
                    tex.release()
                tex = self._ctx.texture((fw, fh), 4)
                tex.repeat_x = tex.repeat_y = False
                self._hosted_mixer_tex = tex
                self._hosted_mixer_fid = -1
            if fid != self._hosted_mixer_fid:
                # Skip the upload when the console has not redrawn: it runs on
                # its own throttled thread, typically well under the visual
                # frame rate, so most frames re-use the last texture.
                tex.write(raw)
                self._hosted_mixer_fid = fid
            self._ctx.screen.use()
            self._ctx.viewport = (0, 0, self._width, self._height)
            self._normalize_gl_render_state()
            tex.use(location=0)
            self._present_prog['tex'].value = 0
            self._present_vao.render(moderngl.TRIANGLE_STRIP)
        except Exception as exc:
            log.warning('Hosted mixer present failed: %s', exc)

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
        if mirror_mode_active and self._fbo_a is not None:
            source = self._fbo_a
        else:
            # Never read self._ctx.screen (the default framebuffer) directly
            # — see the comment on self._screen_copy_fbo's declaration for
            # why moderngl's Framebuffer.read()/read_into() are broken for
            # framebuffer_obj == 0. Blit it into a real FBO first;
            # copy_framebuffer() uses the correctly-queried draw buffer
            # instead of a hardcoded attachment enum, so it doesn't hit the
            # same bug.
            source = self._ensure_screen_copy_fbo()
            self._ctx.copy_framebuffer(source, self._ctx.screen)
        source.use()
        # Framebuffer.read()/read_into() default to a viewport of the
        # framebuffer's OWN reported (width, height) — for self._ctx.screen
        # that tracks the real SDL/GL drawable size, which is not
        # guaranteed to equal our own tracked self._width/self._height
        # (e.g. under mixed-DPI multi-monitor scaling). A mismatch there
        # means the PBOs are sized for one canvas but read_into() writes a
        # different amount of data into them, which can surface later as a
        # GL_INVALID_VALUE on the *next* frame's buffer.read() rather than
        # on the write itself. Pin the viewport explicitly so the PBO size
        # and the actual read region can never disagree.
        viewport = (0, 0, self._width, self._height)
        if (
            not self._stream_viewport_mismatch_logged
            and (int(source.width), int(source.height)) != (self._width, self._height)
        ):
            self._stream_viewport_mismatch_logged = True
            log.warning(
                'Streaming source framebuffer size (%dx%d) does not match '
                'the tracked canvas size (%dx%d) — pinning the read '
                'viewport explicitly to avoid a PBO size mismatch.',
                source.width, source.height, self._width, self._height,
            )
        size = self._width * self._height * 3  # RGB24
        if self._stream_pbo_disabled:
            try:
                return source.read(viewport=viewport, components=3, alignment=1)
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
            self._stream_pbo_frame_count = 0

        write_idx = self._stream_pbo_index
        read_idx = 1 - write_idx
        try:
            source.read_into(self._stream_pbos[write_idx], viewport=viewport, components=3, alignment=1)
        except Exception as exc:
            self._disable_stream_pbo('write (read_into)', exc, size, mirror_mode_active)
            try:
                return source.read(viewport=viewport, components=3, alignment=1)
            except Exception as read_exc:
                log.error('Streaming direct read after PBO failure also failed: %s', read_exc)
                return None

        frame: bytes | None = None
        if self._stream_pbo_primed:
            try:
                frame = self._stream_pbos[read_idx].read()
            except Exception as exc:
                self._disable_stream_pbo('read (buffer.read)', exc, size, mirror_mode_active)
                try:
                    return source.read(viewport=viewport, components=3, alignment=1)
                except Exception as read_exc:
                    log.error('Streaming direct read after PBO failure also failed: %s', read_exc)
                    return None
        else:
            self._stream_pbo_primed = True
        self._stream_pbo_index = read_idx
        self._stream_pbo_frame_count += 1
        return frame

    def _disable_stream_pbo(
        self, stage: str, exc: Exception, size: int, mirror_mode_active: bool,
    ) -> None:
        """Tear down the streaming PBOs and fall back to synchronous reads.

        Logs which specific GL call failed (write vs. read), the raw
        ``glGetError()`` code, and buffer/canvas context — moderngl's own
        exception message alone (e.g. "cannot map the buffer") isn't enough
        to diagnose *why* on a given driver; see
        docs/audits/2026-07-08-render-pipeline-platform-audit.md §8 item 9.
        """
        gl_error = None
        if self._ctx is not None:
            try:
                gl_error = self._ctx.error
            except Exception:
                gl_error = None
        log.warning(
            'Streaming PBO %s failed after %d prior successful frame(s), '
            'disabling PBO for this session: %s '
            '(gl_error=%s buffer_bytes=%d canvas=%dx%d mirror_mode=%s)',
            stage, self._stream_pbo_frame_count, exc,
            gl_error, size, self._width, self._height, mirror_mode_active,
        )
        for pbo in self._stream_pbos:
            pbo.release()
        self._stream_pbos = []
        self._stream_pbo_size = 0
        self._stream_pbo_primed = False
        self._stream_pbo_index = 0
        self._stream_pbo_frame_count = 0
        self._stream_pbo_disabled = True

    _SCREENSHOT_FRAME_MAX_AGE_S = 0.25

    def save_screenshot(self) -> 'Path | None':
        """Capture a screenshot without stalling the show.

        Two costs used to land on the render thread: a synchronous
        full-resolution readback, and — the dominant one — PIL's PNG encode
        plus the disk write, which on a large or spanned canvas is easily
        a few hundred milliseconds of frozen visuals.

        Now: pixels come from the frame tap when recording/streaming already
        produced this frame (free), otherwise from one readback via the
        correct FBO path (never ``ctx.screen.read()``, which moderngl gets
        wrong for the default framebuffer). The flip, encode and write then
        happen on a daemon thread, so the loop keeps rendering.

        Returns the path the image *will* be written to, or None if the
        pixels could not be captured. The write itself is asynchronous.
        """
        from pathlib import Path  # noqa: PLC0415

        frame: tuple[bytes, int, int] | None = None
        cached = self._last_output_frame
        if (
            cached is not None
            and (time.monotonic() - self._last_output_frame_t)
            <= self._SCREENSHOT_FRAME_MAX_AGE_S
        ):
            frame = cached
        if frame is None:
            try:
                frame = self.read_screenshot_frame()
            except Exception as exc:
                log.error('Screenshot readback failed: %s', exc)
                return None
        if frame is None:
            return None
        data, w, h = frame
        expected = max(1, int(w)) * max(1, int(h)) * 3
        if len(data) < expected:
            log.error(
                'Screenshot readback short: got=%d expected=%d size=%dx%d',
                len(data), expected, w, h,
            )
            return None
        if len(data) > expected:
            data = data[:expected]

        out_dir = resolve_path('screenshots')
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.error('Screenshot directory unavailable: %s', exc)
            return None
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = out_dir / f'unicornviz_{ts}.png'

        def _encode_and_save() -> None:
            try:
                from PIL import Image  # noqa: PLC0415
                img = Image.frombytes('RGB', (w, h), data)
                img = img.transpose(Image.FLIP_TOP_BOTTOM)
                img.save(path)
                log.info('Screenshot saved: %s', path)
            except Exception as exc:
                log.error('Screenshot save failed: %s', exc)

        threading.Thread(
            target=_encode_and_save, name='uv-screenshot', daemon=True,
        ).start()
        return Path(path)

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
        # Never read self._ctx.screen directly — see _ensure_screen_copy_fbo's
        # docstring for why moderngl's Framebuffer.read() is broken for the
        # default framebuffer.
        copy_fbo = self._ensure_screen_copy_fbo(w, h)
        self._ctx.copy_framebuffer(copy_fbo, self._ctx.screen)
        data = copy_fbo.read(viewport=(0, 0, w, h), components=3, alignment=1)
        return data, w, h

    def goto_effect(self, cls: Type[BaseEffect]) -> None:
        self._switch_effect(cls)

    def pin_effect_pair(self, cls_a: Type[BaseEffect], cls_b: Type[BaseEffect]) -> bool:
        """Instantiate two effects and hold both alive for hard-cut alternation.

        For a consumer that repeatedly alternates between the same two
        effects (auto-vj-01's effect ping-pong), the normal transition path
        (`_switch_effect` -> `goto_effect`) pays a full instantiate + destroy
        on every single swap, even though both effects are about to be
        needed again a few beats later. Pinning both once and cutting
        between them with `cut_to_pinned()` turns each swap into a pointer
        assignment. Returns False (no-op) if a pair is already pinned, the
        ProjectM manager modal is open, or either class fails to
        instantiate -- callers should fall back to normal `goto_effect()`.
        """
        if self._pinned_pair is not None or self._projectm_manager_modal_active:
            return False
        try:
            a = self._instantiate(cls_a)
        except Exception:
            log.exception('Effect pin failed for %s', cls_a.__name__)
            return False
        try:
            b = self._instantiate(cls_b)
        except Exception:
            log.exception('Effect pin failed for %s', cls_b.__name__)
            a.destroy()
            return False
        self._pinned_pair = {'a': a, 'b': b}
        return True

    def cut_to_pinned(self, which: str) -> bool:
        """Hard-cut the render target to the pinned 'a' or 'b' effect.

        A pointer swap between two already-instantiated effects: no
        instantiate, no destroy, no transition blend. Returns False if no
        pair is pinned or `which` isn't 'a'/'b'.
        """
        pair = self._pinned_pair
        if pair is None or which not in pair:
            return False
        self._invert_colors = False
        self._current_effect = pair[which]
        self._next_effect = None
        self._transition_t = 0.0
        return True

    def unpin_effect_pair(self) -> None:
        """Release the pinned pair, destroying whichever isn't on screen.

        The instance still assigned to `_current_effect` is left alive and
        rendering -- it is destroyed the normal way, the next time
        `_switch_effect()` completes a transition away from it. Does not
        itself pick a replacement effect; the caller (e.g. the director
        exiting ping-pong mode) is responsible for that. A no-op when no
        pair is pinned.
        """
        pair = self._pinned_pair
        self._pinned_pair = None
        if pair is None:
            return
        for effect in pair.values():
            if effect is not self._current_effect:
                effect.destroy()

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

    def disable_current_effect_and_advance(self) -> str:
        """Delete-key action: disable the active effect and jump to a new one.

        If the active effect is ProjectM (duck-typed: exposes
        current_preset_path/set_presets_enabled/next_preset), "disable"
        applies to the *current preset* and playback advances to the next
        preset - staying within ProjectM rather than leaving it. Any other
        effect is disabled from rotation (same persisted set the effects
        browser's Space toggle uses) and playback advances to the next
        *enabled* effect. Clears an effect lock first if it points at the
        effect being disabled, so the lock-redirect in _switch_effect can't
        immediately bounce back to the effect we just left.
        """
        effect = self._current_effect
        if effect is None:
            return 'No active effect'

        if (hasattr(effect, 'current_preset_path')
                and hasattr(effect, 'set_presets_enabled')
                and hasattr(effect, 'next_preset')):
            current_path = str(getattr(effect, 'current_preset_path', '') or '')
            if not current_path:
                return 'ProjectM: no active preset to disable'
            effect.set_presets_enabled([current_path], False)
            self._disable_undo_stack.append(('preset', current_path))
            label = effect.next_preset()
            return f'Preset disabled -> {label}' if label else 'Preset disabled (none remaining)'

        name = str(getattr(effect, 'NAME', effect.__class__.__name__))
        if self._effect_lock == name:
            self.unlock_effect()
        self.set_effect_enabled(name, False)
        self._disable_undo_stack.append(('effect', name))
        self._record_deleted_effect(name)
        playlist = self._playlist
        if playlist is None:
            return f'{name}: disabled'
        cls = playlist.advance()  # skips disabled effects in both modes
        self.goto_effect(cls)
        return f'{name}: disabled -> {cls.NAME}'

    def reactivate_last_disabled_effect(self) -> str:
        """Shift+Delete action: undo the most recent Delete-key deactivation.

        Session-only by design — the undo stack is never persisted, so a
        restart forgets it (the effects browser remains the way to re-enable
        things from prior sessions). Restoring a rotation effect re-enables
        it and jumps straight back to it; restoring a ProjectM preset
        re-enables the preset, which is only possible while a ProjectM-style
        effect is still active (presets belong to it), so the entry is kept
        for a later retry if ProjectM was left in the meantime. Entries whose
        effect was already re-enabled elsewhere (e.g. the effects browser)
        are skipped rather than treated as the undo target.
        """
        stack = self._disable_undo_stack
        while stack:
            kind, name = stack[-1]
            if kind == 'preset':
                effect = self._current_effect
                if not (hasattr(effect, 'set_presets_enabled')
                        and hasattr(effect, 'current_preset_path')):
                    return 'ProjectM not active - preset not restored'
                stack.pop()
                effect.set_presets_enabled([name], True)
                return f'Preset re-enabled: {Path(name).name}'
            stack.pop()
            if self.effect_enabled(name):
                continue  # re-enabled some other way since; not an undo target
            self.set_effect_enabled(name, True)
            playlist = self._playlist
            cls = playlist.find_by_name(name) if playlist is not None else None
            if cls is not None:
                self.goto_effect(cls)
                return f'{name}: re-enabled -> back on'
            return f'{name}: re-enabled'
        return 'Nothing to re-activate'

    @staticmethod
    def _compute_deleted_effects_log_path(cfg: Config) -> Path | None:
        """Return the stamped deleted-effects log path, or None when logging
        is disabled (``[logging] level = "NONE"``)."""
        if str(cfg.get('logging', 'level', default='INFO')).upper() == 'NONE':
            return None
        try:
            logs_dir = resolve_path(cfg.get('logging', 'directory', default='logs'))
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            return logs_dir / f'deleted-effects_{stamp}.log'
        except Exception as exc:
            log.warning('Could not prepare deleted-effects log path: %s', exc)
            return None

    def _record_deleted_effect(self, name: str) -> None:
        """Log + track a Delete-key effect deletion for the session summary.

        Appends to the in-memory session list (reported at shutdown) and, if
        logging is enabled, live-appends the same line to
        logs/deleted-effects_<stamp>.log so the record survives a crash.
        """
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log.info('Effect deleted (Delete key): %s', name)
        self._deleted_effects_session.append((stamp, name))
        if self._deleted_effects_log_path is None:
            return
        try:
            with open(self._deleted_effects_log_path, 'a', encoding='utf-8') as f:
                f.write(f'{stamp}  {name}\n')
        except Exception as exc:
            log.warning('Could not write deleted-effects log: %s', exc)

    def _log_deleted_effects_summary(self) -> None:
        """Log the session's Delete-key deletions to console/main log and
        append the same summary to logs/deleted-effects_<stamp>.log."""
        if not self._deleted_effects_session:
            return
        lines = [f'{stamp}  {name}' for stamp, name in self._deleted_effects_session]
        log.info(
            'Session summary: %d effect(s) deleted via Delete key:\n%s',
            len(lines), '\n'.join(lines),
        )
        if self._deleted_effects_log_path is None:
            return
        try:
            with open(self._deleted_effects_log_path, 'a', encoding='utf-8') as f:
                f.write('--- session summary ---\n')
                f.write('\n'.join(lines) + '\n')
        except Exception as exc:
            log.warning('Could not write deleted-effects summary: %s', exc)

    # -- Effect enable/disable (persisted, excluded from auto-rotation) -------

    def effect_enabled(self, name: str) -> bool:
        """Return whether the effect (display or class name) is rotation-enabled."""
        return str(name) not in self._disabled_effects

    def _projectm_operator_enabled(self) -> bool:
        """True unless the operator disabled ProjectM in the effects browser.

        Gates the boot-time preset prescan and GL bridge warm-up.  Both are
        expensive (a ~10k-file disk walk and a native projectM instance), and
        a drop-in the operator has switched off should not be paying either.
        """
        return (self.effect_enabled('ProjectM Presets')
                and self.effect_enabled('ProjectMEffect'))

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
        self._refresh_effect_shortcuts()

    def set_disabled_effects(self, names: 'set[str] | list[str]') -> None:
        """Replace the whole disabled set at once and persist (preset apply)."""
        self._disabled_effects = {str(n) for n in (names or [])}
        self._runtime_state.set('effects.disabled', sorted(self._disabled_effects))
        self._runtime_state.save()
        if self._playlist is not None:
            self._playlist.set_disabled(self._disabled_effects)
        self._refresh_effect_shortcuts()

    # -- Numeric-hotkey slot pins (persisted) ---------------------------------

    def hotkey_pins(self) -> dict[int, str]:
        """Return the current numeric-hotkey slot pins ({slot: effect name})."""
        return dict(self._hotkey_pins)

    def hotkey_pin_slot_for(self, name: str) -> int | None:
        """Return the slot index an effect is pinned to, or None."""
        name = str(name)
        for slot, pinned in self._hotkey_pins.items():
            if pinned == name:
                return slot
        return None

    def set_hotkey_pin(self, slot: int, name: 'str | None') -> None:
        """Pin an effect to a numeric-hotkey slot, or clear it (name=None).

        An effect may only occupy one slot at a time; pinning it to a new slot
        drops any previous pin it held.
        """
        slot = int(slot)
        if name:
            clean = str(name)
            self._hotkey_pins = {k: v for k, v in self._hotkey_pins.items() if v != clean}
            self._hotkey_pins[slot] = clean
        else:
            self._hotkey_pins.pop(slot, None)
        self._persist_hotkey_pins()

    def toggle_hotkey_pin(self, slot: int, name: str) -> bool:
        """Toggle a slot pin for ``name``. Returns True if now pinned."""
        slot = int(slot)
        if self._hotkey_pins.get(slot) == str(name):
            self.set_hotkey_pin(slot, None)
            return False
        self.set_hotkey_pin(slot, name)
        return True

    def _persist_hotkey_pins(self) -> None:
        self._runtime_state.set(
            'effects.hotkey_pins', {str(k): v for k, v in self._hotkey_pins.items()}
        )
        self._runtime_state.save()
        if self._playlist is not None:
            self._playlist.set_hotkey_pins(self._hotkey_pins)
        self._refresh_effect_shortcuts()

    def _refresh_effect_shortcuts(self) -> None:
        """Push the current numeric-hotkey slot mapping to the help overlay."""
        if self._playlist is not None and self._overlays is not None:
            self._overlays.set_effect_shortcuts(self._playlist.shortcut_effects)

    # -- Global-action hotkey rebinding (persisted) ---------------------------
    # The "enabler" for a future in-app hotkey editor: named global actions
    # (next/prev/fullscreen/help/... - see hotkeys._ACTION_BINDINGS) can be
    # rebound to a different key chord. HotkeyHandler translates an incoming
    # override chord back to the action's default chord before the existing,
    # unmodified dispatch chain runs, so no dispatch logic needed to change.

    def hotkey_overrides(self) -> dict[str, tuple[int, int]]:
        """Return the current rebound-action overrides ({action: (sym, mod)})."""
        return dict(self._hotkey_overrides)

    def set_hotkey_override(self, action: str, sym: 'int | None', mod: int = 0) -> None:
        """Rebind a global action to a new chord, or clear it (sym=None)."""
        action = str(action)
        if sym is None:
            self._hotkey_overrides.pop(action, None)
        else:
            self._hotkey_overrides[action] = (int(sym), int(mod))
        self._runtime_state.set(
            'hotkeys.overrides',
            {k: list(v) for k, v in self._hotkey_overrides.items()},
        )
        self._runtime_state.save()

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

    # -- Presets modal -------------------------------------------------------

    @property
    def presets_modal_active(self) -> bool:
        """Return whether the presets modal is open."""
        return self._overlays.presets_visible

    def _refresh_presets_entries(self) -> None:
        self._overlays.set_presets_entries(self.list_show_presets())

    def open_presets(self) -> None:
        """Open the show-presets modal."""
        o = self._overlays
        self._refresh_presets_entries()
        o.set_presets_name_mode(False)
        if not o.presets_visible:
            o.toggle_presets()

    def close_presets(self) -> None:
        """Close the show-presets modal."""
        o = self._overlays
        o.set_presets_name_mode(False)
        if o.presets_visible:
            o.toggle_presets()

    def presets_load_selected(self) -> str | None:
        """Load the highlighted preset. Returns its name."""
        entry = self._overlays.presets_browser.selected_entry()
        if entry is None:
            return None
        name = str(entry.get('display_name', ''))
        if self.load_show_preset(name):
            self.close_presets()
            return name
        return None

    def presets_delete_selected(self) -> str | None:
        """Delete the highlighted preset and refresh the list. Returns its name."""
        entry = self._overlays.presets_browser.selected_entry()
        if entry is None:
            return None
        name = str(entry.get('display_name', ''))
        if self.delete_show_preset(name):
            self._refresh_presets_entries()
            return name
        return None

    def presets_save_named(self, name: str) -> str | None:
        """Save the current setup under *name* and refresh the list."""
        saved = self.save_show_preset(name)
        if saved is not None:
            self._refresh_presets_entries()
        return saved

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
                'hotkey_slot': self.hotkey_pin_slot_for(e.name),
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

    def effects_browser_toggle_pin_slot(self, slot: int) -> str | None:
        """Toggle a numeric-hotkey slot pin for the selected browser entry.

        Reuses the same key chord that would jump to ``slot`` outside the
        browser, so pinning shares muscle memory with jumping. Pinning the
        already-pinned effect on the same slot clears the pin; pinning a
        different effect there reassigns the slot (and drops that effect's
        previous pin, if any).
        """
        entry = self._overlays.effects_browser.selected_entry()
        if entry is None:
            return None
        name = str(entry.get('display_name', ''))
        now_pinned = self.toggle_hotkey_pin(slot, name)
        # Live-refresh the pin indicator on every visible row (a reassigned
        # slot may have just unpinned a different effect).
        for e in self._overlays.effects_browser.entries():
            e['hotkey_slot'] = self.hotkey_pin_slot_for(str(e.get('display_name', '')))
        digit = (slot % 10) + 1 if slot % 10 != 9 else 0
        return f'{name}: pinned to key {digit}' if now_pinned else f'{name}: unpinned'

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

    def _ensure_screen_copy_fbo(self, width: int | None = None, height: int | None = None) -> moderngl.Framebuffer:
        """Lazily (re)allocate the real FBO used to work around moderngl's
        broken glReadBuffer(GL_COLOR_ATTACHMENT0) on the default framebuffer
        (see the comment on self._screen_copy_fbo's declaration). Sized to
        (width, height) if given, else the logical canvas (self._width,
        self._height) — callers reading the raw SDL drawable size (which can
        exceed the logical canvas, e.g. mirror mode) should pass it explicitly."""
        w = max(1, int(width if width is not None else self._width))
        h = max(1, int(height if height is not None else self._height))
        if self._screen_copy_fbo is None or (self._screen_copy_fbo.width, self._screen_copy_fbo.height) != (w, h):
            self._release_fbo(self._screen_copy_fbo)
            tex = self._ctx.texture((w, h), 4)
            # copy_framebuffer()/glBlitFramebuffer always blits
            # GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT (moderngl does not
            # expose a color-only blit) — a depth attachment is required or
            # the blit hits GL_INVALID_FRAMEBUFFER_OPERATION (incomplete
            # draw/read buffers), same as _make_fbo()'s pattern.
            depth = self._ctx.depth_renderbuffer((w, h))
            self._screen_copy_fbo = self._ctx.framebuffer(color_attachments=[tex], depth_attachment=depth)
        return self._screen_copy_fbo

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
            self.cfg.get('demo', 'effect_duration', default=60)
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
