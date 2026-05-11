"""
Main application — SDL2 window (Wayland-first) + moderngl context + main loop.
"""
from __future__ import annotations

import logging
import os
import time
import ctypes
import sys
from pathlib import Path
from typing import Type

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
from unicornviz.dropins import load_dropin_symbol

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


def _clamp_render_scale(value: float) -> float:
    """Clamp internal render scale to a sane range."""
    return max(0.5, min(1.0, value))


def _load_multihead_controller_class() -> type:
    """Load MultiHeadController directly from the multi-head drop-in."""
    return load_dropin_symbol('multi-head-01/multihead.py', 'MultiHeadController')


class App:
    def __init__(self, config_path: str | Config = "config.toml") -> None:
        self.cfg = config_path if isinstance(config_path, Config) else Config(config_path)
        self._running = False
        self._paused = False
        self._auto_advance = True  # Toggle with hotkey T
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
        self._rng = np.random.default_rng()
        self._demo_timer: float = 0.0
        self._transition_duration: float = self.cfg.get(
            "demo", "transition_duration", default=1.0
        )
        self._audio: AudioData | None = None
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
        self._invert_colors = False
        self._width = self.cfg.get("window", "width", default=1920)
        self._height = self.cfg.get("window", "height", default=1080)
        self._display_index = 0
        self._display_mode = 'single'
        multihead_cls = _load_multihead_controller_class()
        self._multihead = multihead_cls(self.cfg)
        self._render_scale = _clamp_render_scale(
            float(self.cfg.get('render', 'internal_scale', default=1.0))
        )
        self._render_width = max(1, int(round(self._width * self._render_scale)))
        self._render_height = max(1, int(round(self._height * self._render_scale)))
        self._fullscreen = self.cfg.get("window", "fullscreen", default=False)
        self._audio = AudioData()

    # ------------------------------------------------------------------ #
    # SDL2 + moderngl init                                                 #
    # ------------------------------------------------------------------ #

    def _log_video_displays(self) -> int:
        return self._multihead.log_video_displays(self._width, self._height)

    def _resolve_display_mode(self) -> str:
        self._display_mode = self._multihead.resolve_display_mode()
        return self._display_mode

    def _resolve_display_index(self) -> int:
        self._display_index = self._multihead.resolve_display_index(self._width, self._height)
        return self._display_index

    def _display_bounds(self, display_index: int) -> sdl2.SDL_Rect | None:
        return self._multihead.display_bounds(display_index, self._width, self._height)

    def _all_display_bounds(self) -> tuple[int, int, int, int]:
        return self._multihead.all_display_bounds(self._width, self._height)

    def _window_position_for_display(self, display_index: int) -> tuple[int, int]:
        return self._multihead.window_position_for_display(display_index, self._width, self._height)

    def _move_window_to_display(self) -> None:
        self._multihead.move_window_to_display(self._window, self._width, self._height)

    def _destroy_mirror_outputs(self) -> None:
        self._multihead.destroy_mirror_outputs()

    def _create_mirror_outputs(self) -> None:
        title = self.cfg.get('window', 'title', default='Unicorn Viz')
        self._multihead.create_mirror_outputs(title, self._width, self._height)

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
        if self._display_mode == 'span_all' and self._fullscreen:
            flags = sdl2.SDL_WINDOW_OPENGL | sdl2.SDL_WINDOW_BORDERLESS
        elif self._fullscreen:
            flags |= sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP

        self._display_index = self._resolve_display_index()
        if self._display_mode == 'span_all':
            x_pos, y_pos, self._width, self._height = self._all_display_bounds()
        else:
            x_pos, y_pos = self._window_position_for_display(self._display_index)

        title = self.cfg.get("window", "title", default="Unicorn Viz")
        self._window = sdl2.SDL_CreateWindow(
            title.encode(),
            x_pos,
            y_pos,
            self._width,
            self._height,
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
        self._set_cursor_visible(False)

        # After fullscreen is applied the OS may give us a different size.
        # Query the actual drawable size and update width/height.
        w_i = ctypes.c_int(0)
        h_i = ctypes.c_int(0)
        sdl2.SDL_GetWindowSize(self._window, w_i, h_i)
        if self._fullscreen:
            self._width  = w_i.value or self._width
            self._height = h_i.value or self._height
            log.info(
                'Fullscreen drawable size in %s mode: %dx%d',
                self._display_mode,
                self._width,
                self._height,
            )
        self._update_render_target_size()
        self._create_mirror_outputs()

    def _init_moderngl(self) -> None:
        self._ctx = moderngl.create_context()
        self._ctx.enable(moderngl.BLEND)
        self._ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        log.info("OpenGL %s", self._ctx.info["GL_VERSION"])
        self._build_present_pipeline()
        self._build_blend_pipeline()
        self._build_invert_pipeline()

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
        self._ctx.screen.use()
        self._ctx.viewport = (0, 0, self._width, self._height)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        tex.use(location=0)
        self._invert_prog["tex"].value = 0
        self._invert_vao.render(moderngl.TRIANGLE_STRIP)

    def _present_from_tex(self, tex: moderngl.Texture) -> None:
        """Render a texture to screen without post-processing."""
        self._ctx.screen.use()
        self._ctx.viewport = (0, 0, self._width, self._height)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        tex.use(location=0)
        self._present_prog['tex'].value = 0
        self._present_vao.render(moderngl.TRIANGLE_STRIP)

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
        tex = self._ctx.texture((self._render_width, self._render_height), 4)
        tex.filter = moderngl.LINEAR, moderngl.LINEAR
        depth = self._ctx.depth_renderbuffer((self._render_width, self._render_height))
        return self._ctx.framebuffer(color_attachments=[tex], depth_attachment=depth)

    def _update_render_target_size(self) -> None:
        """Recompute scaled internal render target dimensions."""
        self._render_width = max(1, int(round(self._width * self._render_scale)))
        self._render_height = max(1, int(round(self._height * self._render_scale)))

    def _set_cursor_visible(self, visible: bool) -> None:
        """Show cursor only when Ctrl is held; otherwise keep it hidden."""
        try:
            sdl2.SDL_ShowCursor(sdl2.SDL_ENABLE if visible else sdl2.SDL_DISABLE)
        except Exception:
            pass

    def _update_ctrl_state(self, sym: int, is_keydown: bool) -> None:
        if sym in (sdl2.SDLK_LCTRL, sdl2.SDLK_RCTRL):
            self._ctrl_held = is_keydown
            self._set_cursor_visible(self._ctrl_held)

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

        midi_device_hint = self.cfg.get("midi", "device", default="")
        midi_manager = MidiManager(device_hint=midi_device_hint)
        midi_manager.start()
        self._midi_manager = midi_manager

        effects = get_effects()
        if not effects:
            raise RuntimeError("No effects found — check unicornviz/effects/")

        playlist = Playlist(effects, self.cfg)
        overlays = Overlays(
            self._ctx,
            self._width,
            self._height,
            flash_messages=bool(self.cfg.get('overlays', 'flash_messages', default=True)),
            show_recording_indicator=bool(self.cfg.get('recording', 'show_indicator', default=True)),
        )
        self._overlays = overlays
        overlays.set_effect_shortcuts(playlist.shortcut_effects)
        if overlays.unmapped_effects:
            log.warning(
                "Effects without direct shortcuts (beyond 30): %s",
                ", ".join(overlays.unmapped_effects),
            )
        hotkeys = HotkeyHandler(
            app=self,
            playlist=playlist,
            overlays=overlays,
            audio_manager=audio_manager,
        )
        hotkeys.attach_midi(midi_manager)

        # Load first effect
        self._current_effect = self._instantiate(playlist.current())
        self._recorder = Recorder(self.cfg, self._width, self._height)
        self._sync_recording_overlay()
        if self._recorder.enabled and self._recorder.auto_record:
            started, _ = self.start_recording()
            if started:
                log.info('Auto-record enabled')
        self._running = True

        prev_time = time.perf_counter()
        self._demo_timer = 0.0
        effect_duration = self.cfg.get("demo", "effect_duration", default=20)

        while self._running:
            now = time.perf_counter()
            dt = min(now - prev_time, 0.1)  # cap at 100 ms to avoid spiral
            prev_time = now

            # Poll events
            event = sdl2.SDL_Event()
            while sdl2.SDL_PollEvent(event):
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
                            sdl2.SDL_WINDOWEVENT_HIDDEN,
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
                        self._set_cursor_visible(self._ctrl_held)
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
                if self._demo_timer >= effect_duration and allow_advance:
                    self._demo_timer = 0.0
                    next_cls = playlist.advance()
                    log.info("Auto-advance → %s", next_cls.NAME)
                    self._switch_effect(next_cls)

            # Update audio
            self._audio = audio_manager.get_audio_data()

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
                    overlays._name_text = self._current_effect.NAME

            # Feed modern TAB HUD with current runtime status.
            fps_now = (1.0 / dt) if dt > 0.0 else 0.0
            transition_name = self._transition_kind if self._next_effect is not None else 'none'
            transition_pct = f"{int(max(0.0, min(1.0, self._transition_t)) * 100)}%"
            audio_src = audio_manager.get_source_label() if audio_manager is not None else 'n/a'
            effect_speed = '-'
            if self._current_effect is not None and 'speed' in self._current_effect.parameters:
                effect_speed = f"{self._current_effect.parameters['speed']:.2f}x"
            rec_state = 'OFF'
            if self._recorder is not None and self._recorder.is_recording:
                rec_state = 'ON'
            overlays.set_hud_state({
                'title': 'Unicorn Viz HUD',
                'effect': overlays._name_text,
                'next_effect': self._next_effect.NAME if self._next_effect is not None else '-',
                'transition': transition_name,
                'transition_t': transition_pct,
                'fps': f"{fps_now:.1f}",
                'frame_ms': f"{(dt * 1000.0):.2f}",
                'resolution': f"{self._width}x{self._height}",
                'render_scale': f"{self._render_scale:.2f}",
                'playlist': f"{p.mode.upper()} {p.index + 1}/{len(p.effects)}",
                'paused': 'YES' if self._paused else 'NO',
                'fullscreen': 'YES' if self._fullscreen else 'NO',
                'auto_advance': 'ON' if self._auto_advance else 'OFF',
                'reactivity': f"{audio_manager.get_reactivity():.1f}x" if audio_manager is not None else 'n/a',
                'speed': effect_speed,
                'audio_source': audio_src,
                'recording': rec_state,
                'bass': f"{self._audio.bass:.2f}" if self._audio is not None else '0.00',
                'mid': f"{self._audio.mid:.2f}" if self._audio is not None else '0.00',
                'treble': f"{self._audio.treble:.2f}" if self._audio is not None else '0.00',
                'display_mode': self._display_mode,
                'display_index': str(self._display_index),
                'invert': 'ON' if self._invert_colors else 'OFF',
            })

            # Render
            self._render(dt)
            self._sync_recording_overlay()
            overlays.render(dt, include_recording_indicator=False)
            need_frame_for_recording = (
                self._recorder is not None and self._recorder.is_recording
            )
            need_frame_for_mirror = self._multihead.has_mirror_outputs
            shared_frame: bytes | None = None
            if need_frame_for_recording or need_frame_for_mirror:
                try:
                    shared_frame = self._read_shared_frame()
                except Exception as exc:
                    log.error('Frame readback failed: %s', exc)
                    shared_frame = None
            if need_frame_for_recording and shared_frame is not None:
                self._write_recording_frame(shared_frame)
            overlays.render_live_recording_indicator()
            if need_frame_for_mirror and shared_frame is not None:
                self._present_mirror_outputs(shared_frame)

            sdl2.SDL_GL_SwapWindow(self._window)

        # Cleanup
        if self._recorder:
            self._recorder.stop()
        audio_manager.stop()
        midi_manager.stop()
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
        self._destroy_mirror_outputs()
        self._release_readback_pbos()
        sdl2.SDL_GL_DeleteContext(self._gl_context)
        sdl2.SDL_DestroyWindow(self._window)
        sdl2.SDL_Quit()

    def _render(self, dt: float) -> None:
        ctx = self._ctx

        if self._next_effect is None:
            # No transition — render current effect; optionally apply invert pass.
            if self._invert_colors or self._render_scale < 0.999:
                self._fbo_a.use()
                ctx.viewport = (0, 0, self._render_width, self._render_height)
                ctx.clear(0.0, 0.0, 0.0, 1.0)
                if self._current_effect:
                    self._current_effect.render()
                if self._invert_colors:
                    self._render_inverted_from_tex(self._fbo_a.color_attachments[0])
                else:
                    self._present_from_tex(self._fbo_a.color_attachments[0])
            else:
                ctx.screen.use()
                ctx.viewport = (0, 0, self._width, self._height)
                ctx.clear(0.0, 0.0, 0.0, 1.0)
                if self._current_effect:
                    self._current_effect.render()
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
                if self._render_scale < 0.999:
                    self._fbo_a.use()
                    ctx.viewport = (0, 0, self._render_width, self._render_height)
                    ctx.clear(0.0, 0.0, 0.0, 1.0)
                    if self._current_effect:
                        self._current_effect.render()
                    self._present_from_tex(self._fbo_a.color_attachments[0])
                else:
                    ctx.screen.use()
                    ctx.viewport = (0, 0, self._width, self._height)
                    ctx.clear(0.0, 0.0, 0.0, 1.0)
                    if self._current_effect:
                        self._current_effect.render()
            else:
                # Render A into FBO a
                self._fbo_a.use()
                ctx.viewport = (0, 0, self._render_width, self._render_height)
                ctx.clear(0.0, 0.0, 0.0, 1.0)
                self._current_effect.render()

                # Render B into FBO b
                self._fbo_b.use()
                ctx.viewport = (0, 0, self._render_width, self._render_height)
                ctx.clear(0.0, 0.0, 0.0, 1.0)
                self._next_effect.render()

                # Transition composite to screen
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

    def _on_resize(self, w: int, h: int) -> None:
        self._width = w
        self._height = h
        self._update_render_target_size()
        self._release_readback_pbos()
        if self._recorder and self._recorder.is_recording:
            self._recorder.stop()
            self._sync_recording_overlay()
            log.warning('Recording stopped due to resize/fullscreen change')
        if self._current_effect:
            self._current_effect.resize(w, h)
        if self._next_effect:
            self._next_effect.resize(w, h)
        self._resize_mirror_textures()
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
            flag = sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP if self._fullscreen else 0
            if self._fullscreen:
                self._move_window_to_display()
            sdl2.SDL_SetWindowFullscreen(self._window, flag)
            if not self._fullscreen:
                self._move_window_to_display()

    def toggle_pause(self) -> None:
        self._paused = not self._paused

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

    def goto_effect(self, cls: Type[BaseEffect]) -> None:
        self._switch_effect(cls)

    def goto_ansi(self, ansi_dir: str) -> None:
        """Launch ANSIViewer with an explicit art directory."""
        # Invert does not carry through transitions.
        self._invert_colors = False
        if self._next_effect is not None:
            self._next_effect.destroy()
        cfg_override = {"ansi_dir": ansi_dir}
        self._next_effect = ANSIViewer(self._ctx, self._width, self._height, cfg_override)
        self._transition_t = 0.0

    def toggle_invert(self) -> bool:
        """Toggle color inversion for the active effect frame only."""
        self._invert_colors = not self._invert_colors
        return self._invert_colors

    @property
    def paused(self) -> bool:
        return self._paused
