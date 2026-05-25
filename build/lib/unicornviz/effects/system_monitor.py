"""
System Monitor — Fullscreen diagnostic visualizer.

Displays real-time FPS, frame time, CPU, RAM, audio source, and active
transition on top of an ever-changing demoscene-style animated background
that itself reacts to system load.  The background cycles through several
distinct visual modes (plasma, grid, scope, starmap) so the screen never
looks static even when metrics are calm.

Requires ``psutil`` (listed in requirements.txt).
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque

import numpy as np
import moderngl

try:
    import psutil
    _PSUTIL = True
except ImportError:  # pragma: no cover
    _PSUTIL = False

from unicornviz.effects.base import BaseEffect, AudioData

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# GLSL sources                                                         #
# ------------------------------------------------------------------ #

_VERT = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_FRAG_BG = """
#version 330
// Animated background that cycles through 4 visual modes driven by
// iMode (0=plasma, 1=hex-grid, 2=oscilloscope-field, 3=starmap).
// System load (iCpuLoad, iRamLoad) tints and distorts the scene.
uniform float iTime;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
uniform float iCpuLoad;   // 0..1
uniform float iRamLoad;   // 0..1
uniform float iFps;       // raw FPS for subtle colour shift
uniform int   iMode;
in vec2 v_uv;
out vec4 fragColor;

// ---- helpers ----
vec3 palette(float t) {
    vec3 a = vec3(0.5);
    vec3 b = vec3(0.5);
    vec3 c = vec3(1.0);
    vec3 d = vec3(0.00, 0.10, 0.20);
    return a + b * cos(6.28318 * (c * t + d));
}

float hash21(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

// ---- mode 0: plasma ----
vec3 mode_plasma(vec2 uv, float t) {
    float v = sin(uv.x * 10.0 + t)
            + sin(uv.y * 10.0 + t * 1.3)
            + sin((uv.x + uv.y) * 7.0 + t * 0.7)
            + sin(length(uv - 0.5) * 14.0 - t * 2.0);
    float load = iCpuLoad * 0.3 + iRamLoad * 0.1;
    return palette(v * 0.25 + 0.5 + load + iTreble * 0.15);
}

// ---- mode 1: hex grid (load-coloured) ----
float hexDist(vec2 p) {
    p = abs(p);
    return max(dot(p, normalize(vec2(1.0, 1.732))), p.x);
}
vec4 hexCoords(vec2 uv) {
    vec2 r = vec2(1.0, 1.732);
    vec2 h = r * 0.5;
    vec2 a = mod(uv, r) - h;
    vec2 b = mod(uv - h, r) - h;
    vec2 gv = dot(a, a) < dot(b, b) ? a : b;
    float x = atan(gv.y, gv.x);
    float y = 0.5 - hexDist(gv);
    vec2 id = uv - gv;
    return vec4(x, y, id);
}
vec3 mode_hex(vec2 uv, float t) {
    uv = (uv - 0.5) * 6.0;
    vec4 hc = hexCoords(uv);
    float edge = smoothstep(0.0, 0.07, hc.y);
    float pulse = 0.5 + 0.5 * sin(t * 2.0 + hash21(hc.zw) * 6.28);
    vec3 cellCol = palette(hash21(hc.zw) + t * 0.05 + iCpuLoad * 0.4);
    return mix(vec3(0.02, 0.04, 0.06), cellCol * pulse, edge);
}

// ---- mode 2: oscilloscope field ----
vec3 mode_scope(vec2 uv, float t) {
    float bass_amp = 0.08 + iBass * 0.18;
    float y_wave = sin(uv.x * 20.0 + t * 3.0) * bass_amp
                 + sin(uv.x * 13.0 - t * 2.1) * bass_amp * 0.5;
    float dist = abs(uv.y - 0.5 - y_wave);
    float line = exp(-dist * dist * 600.0);
    float grid_x = smoothstep(0.02, 0.0, abs(fract(uv.x * 10.0) - 0.5)) * 0.06;
    float grid_y = smoothstep(0.02, 0.0, abs(fract(uv.y * 6.0) - 0.5)) * 0.06;
    vec3 col = vec3(0.02, 0.06, 0.04) + (grid_x + grid_y);
    col += vec3(0.2, 1.0, 0.5) * line * (0.6 + iTreble * 0.6);
    return col;
}

// ---- mode 3: starmap / deep space ----
float star(vec2 uv, float seed) {
    float n = hash21(floor(uv * 40.0) + seed);
    float tw = 0.5 + 0.5 * sin(iTime * (1.0 + n * 4.0) + n * 6.28);
    return smoothstep(0.96, 1.0, n) * tw;
}
vec3 mode_starmap(vec2 uv, float t) {
    vec3 col = mix(vec3(0.01, 0.01, 0.03), vec3(0.04, 0.01, 0.07),
                   length(uv - 0.5));
    // Three star layers at different scales
    col += vec3(star(uv, 0.0), star(uv, 1.0), star(uv, 2.0)) * 0.9;
    // Nebula streak
    float nb = exp(-pow(abs(uv.y - 0.5 + sin(uv.x * 3.0 + t * 0.2) * 0.1), 2.0) * 80.0);
    col += palette(t * 0.04 + uv.x * 0.3) * nb * 0.4;
    return col;
}

void main() {
    vec2 uv = v_uv;
    vec3 col;
    if      (iMode == 0) col = mode_plasma(uv, iTime);
    else if (iMode == 1) col = mode_hex(uv, iTime);
    else if (iMode == 2) col = mode_scope(uv, iTime);
    else                 col = mode_starmap(uv, iTime);

    // Subtle CPU danger tint: push towards red when CPU is pegged
    col = mix(col, col * vec3(1.4, 0.6, 0.5), iCpuLoad * iCpuLoad * 0.5);

    // Bass flash overlay
    col += vec3(0.08, 0.04, 0.12) * iBass * 0.7;

    fragColor = vec4(col, 1.0);
}
"""

_FRAG_BAR = """
#version 330
// Renders a single horizontal gauge bar.
// x range [0,1] maps to bar extent; uFill is the filled fraction.
uniform vec4  uColor;
uniform float uFill;
uniform float uTime;
in vec2 v_uv;
out vec4 fragColor;

void main() {
    float x = v_uv.x;
    float filled = step(x, uFill);
    // animated shimmer on filled part
    float shimmer = 0.85 + 0.15 * sin(uTime * 6.0 + x * 30.0);
    // danger flash when > 90 %
    float danger = step(0.90, uFill) * (0.5 + 0.5 * sin(uTime * 12.0));
    vec3 col = uColor.rgb * shimmer;
    col = mix(col, vec3(1.0, 0.2, 0.2), danger * 0.6);
    float alpha = mix(0.12, uColor.a, filled);
    fragColor = vec4(col, alpha);
}
"""

# ------------------------------------------------------------------ #
# Background worker for system metrics (avoids blocking render path)  #
# ------------------------------------------------------------------ #

class _MetricsWorker(threading.Thread):
    """Collects CPU/RAM metrics on a background thread every 500 ms."""

    def __init__(self) -> None:
        super().__init__(daemon=True, name="metrics-worker")
        self._cpu: float = 0.0
        self._ram: float = 0.0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def run(self) -> None:
        if not _PSUTIL:
            return
        psutil.cpu_percent()  # warm-up call
        while not self._stop_event.is_set():
            cpu = psutil.cpu_percent(interval=None) / 100.0
            ram = psutil.virtual_memory().percent / 100.0
            with self._lock:
                self._cpu = cpu
                self._ram = ram
            time.sleep(0.5)

    def snapshot(self) -> tuple[float, float]:
        """Return (cpu_0_to_1, ram_0_to_1) without blocking."""
        with self._lock:
            return self._cpu, self._ram

    def stop(self) -> None:
        self._stop_event.set()


# ------------------------------------------------------------------ #
# Effect                                                               #
# ------------------------------------------------------------------ #

class SystemMonitor(BaseEffect):
    """
    Fullscreen system-diagnostics effect.

    Renders live FPS, frame time, CPU%, RAM%, audio source, and active
    transition on top of a cycling animated background.  The background
    auto-advances through four visual modes every 12 seconds so the
    display stays diverse over long sessions.

    System metrics are polled on a dedicated background thread so the
    render path never blocks.
    """

    NAME = "System Monitor"
    AUTHOR = "Autopilot"
    TAGS = ["diagnostic", "hud", "system", "demoscene"]
    PING_PONG_FRIENDS = ['Audio Spectrum', 'Hacker Terminal', 'Cyber War']

    # Background visual modes — change every _MODE_DURATION seconds
    _MODE_DURATION: float = 12.0
    _MODE_COUNT: int = 4

    def _init(self) -> None:
        self.parameters = {
            "speed": float(self.config.get("speed", 1.0)),
            "bar_height": 0.028,
            "mode_lock": -1.0,   # -1 = auto-cycle, 0-3 = locked mode
        }

        # GL resources
        self._bg_prog = self._make_program(_VERT, _FRAG_BG)
        self._bg_vao, self._bg_vbo = self._fullscreen_quad(self._bg_prog)
        self._bar_prog = self._make_program(_VERT, _FRAG_BAR)

        # Pre-allocate bar VAOs (up to 6 bars: fps, frame-time, cpu, ram,
        # bass, treble)
        self._bar_vaos: list[tuple[moderngl.VertexArray, moderngl.Buffer]] = []
        for _ in range(6):
            vao, vbo = self._fullscreen_quad(self._bar_prog)
            self._bar_vaos.append((vao, vbo))

        # Metrics
        self._worker = _MetricsWorker()
        self._worker.start()

        # Rolling frame-time history for sparkline (pre-allocate)
        self._ft_history: deque[float] = deque([0.0] * 60, maxlen=60)
        self._fps: float = 60.0
        self._frame_time_ms: float = 16.7
        self._cpu: float = 0.0
        self._ram: float = 0.0

        # Audio state
        self._bass: float = 0.0
        self._mid: float = 0.0
        self._treble: float = 0.0

        # Background mode cycling
        self._mode: int = 0
        self._mode_timer: float = 0.0

        # Smoothed bar fills (avoid jitter)
        self._smooth_cpu: float = 0.0
        self._smooth_ram: float = 0.0
        self._smooth_fps_norm: float = 1.0

        log.debug("SystemMonitor._init: psutil available=%s", _PSUTIL)

    # ---------------------------------------------------------------- #

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        speed = self.parameters["speed"]
        self._mode_timer += dt * speed

        # Advance background mode
        lock = self.parameters["mode_lock"]
        if lock >= 0.0:
            self._mode = int(lock) % self._MODE_COUNT
        elif self._mode_timer >= self._MODE_DURATION:
            self._mode = (self._mode + 1) % self._MODE_COUNT
            self._mode_timer = 0.0

        # Audio
        self._bass = audio.bass
        self._mid = audio.mid
        self._treble = audio.treble

        # Frame metrics
        self._frame_time_ms = dt * 1000.0
        self._ft_history.append(self._frame_time_ms)
        if dt > 0.0:
            self._fps = 1.0 / dt

        # System metrics (from background thread — never blocks)
        self._cpu, self._ram = self._worker.snapshot()

        # Smoothed values for bars
        alpha = min(1.0, dt * 3.0)
        self._smooth_cpu += (self._cpu - self._smooth_cpu) * alpha
        self._smooth_ram += (self._ram - self._smooth_ram) * alpha
        fps_norm = min(1.0, self._fps / 60.0)
        self._smooth_fps_norm += (fps_norm - self._smooth_fps_norm) * alpha

    # ---------------------------------------------------------------- #

    def _draw_bar(
        self,
        idx: int,
        y_ndc: float,
        h_ndc: float,
        fill: float,
        color: tuple[float, float, float, float],
    ) -> None:
        """Draw a single horizontal gauge bar via full-screen quad + scissor."""
        vao, vbo = self._bar_vaos[idx]
        h_px = max(1, int(h_ndc * self.height))
        y_px = int((1.0 - y_ndc - h_ndc) * self.height)
        self.ctx.scissor = (0, y_px, self.width, h_px)
        self._bar_prog["uColor"].value = color
        self._bar_prog["uFill"].value = max(0.0, min(1.0, fill))
        self._bar_prog["uTime"].value = self.time
        vao.render(moderngl.TRIANGLE_STRIP)

    def _set_bg_uniform(self, name: str, value: float | int) -> None:
        """Set background shader uniform only if it exists in the compiled program."""
        try:
            self._bg_prog[name].value = value
        except KeyError:
            # Some uniforms may be optimized out by GLSL if not referenced.
            pass

    def render(self) -> None:
        t = self.time

        # ---- background ----
        self._set_bg_uniform("iTime", t)
        self._set_bg_uniform("iBass", self._bass)
        self._set_bg_uniform("iMid", self._mid)
        self._set_bg_uniform("iTreble", self._treble)
        self._set_bg_uniform("iCpuLoad", self._smooth_cpu)
        self._set_bg_uniform("iRamLoad", self._smooth_ram)
        self._set_bg_uniform("iFps", float(self._fps))
        self._set_bg_uniform("iMode", self._mode)
        self.ctx.scissor = None
        self._bg_vao.render(moderngl.TRIANGLE_STRIP)

        # ---- gauge bars ----
        bh = self.parameters["bar_height"]
        margin = bh * 0.25
        # Layout: stack bars near bottom of screen (NDC y grows upward)
        # 0 = FPS, 1 = frame-time, 2 = CPU, 3 = RAM, 4 = bass, 5 = treble
        base_y = 0.05

        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

        # FPS bar (green, fill = fps/60 capped at 1)
        fps_fill = self._smooth_fps_norm
        fps_color = (0.2, 1.0, 0.4, 0.85)
        self._draw_bar(0, base_y, bh, fps_fill, fps_color)

        # Frame-time bar (cyan, fill = 1 - ft/33ms, so lower is better = fuller)
        ft_fill = max(0.0, 1.0 - (self._frame_time_ms / 33.3))
        self._draw_bar(1, base_y + (bh + margin), bh, ft_fill, (0.2, 0.85, 1.0, 0.85))

        # CPU bar (orange→red under load)
        cpu_r = 0.4 + self._smooth_cpu * 0.6
        cpu_g = 0.8 - self._smooth_cpu * 0.6
        self._draw_bar(2, base_y + 2 * (bh + margin), bh,
                       self._smooth_cpu, (cpu_r, cpu_g, 0.2, 0.85))

        # RAM bar (purple)
        self._draw_bar(3, base_y + 3 * (bh + margin), bh,
                       self._smooth_ram, (0.7, 0.3, 1.0, 0.85))

        # Bass bar (red-orange, thin)
        self._draw_bar(4, base_y + 4 * (bh + margin), bh * 0.6,
                       self._bass, (1.0, 0.35, 0.1, 0.75))

        # Treble bar (white-cyan, thin)
        self._draw_bar(5, base_y + 4 * (bh + margin) + bh * 0.6 + margin * 0.5,
                       bh * 0.6, self._treble, (0.8, 1.0, 1.0, 0.75))

        self.ctx.scissor = None
        self.ctx.disable(moderngl.BLEND)

    # ---------------------------------------------------------------- #

    def destroy(self) -> None:
        self._worker.stop()
        self._bg_vao.release()
        self._bg_vbo.release()
        self._bg_prog.release()
        for vao, vbo in self._bar_vaos:
            vao.release()
            vbo.release()
        self._bar_prog.release()
