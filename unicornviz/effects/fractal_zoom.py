"""
Fractal Zoom 2.0 — non-black Mandelbrot voyage with nebula interior shading.

Fixes and upgrades:
  - No hard-black trap: inside-set pixels render as animated dark-nebula detail
  - Orbit-trap based colouring for richer structures during deep zoom
  - Safer precision lifecycle: reset before precision collapse
  - Slow camera drift + target jitter for long-run non-repeating motion
  - Beat pulses zoom and palette, but settles quickly
"""
from __future__ import annotations

import math

import moderngl

from unicornviz.effects.base import AudioData, BaseEffect

_VERT = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv = in_vert;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_FRAG = """
#version 330
uniform vec2  iResolution;
uniform float iCenterX;
uniform float iCenterY;
uniform float iZoom;
uniform float iPalShift;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
uniform float iBeat;
uniform float iRotation;
uniform float iVariant;
uniform float iWarpX;
uniform float iWarpY;
uniform float iOrbitScale;
uniform float iTrapBias;
uniform float iSceneSeed;
uniform int   iMaxIter;

in  vec2 v_uv;
out vec4 fragColor;

vec3 palette(float t) {
    vec3 a = vec3(0.5, 0.5, 0.5);
    vec3 b = vec3(0.5, 0.5, 0.5);
    vec3 c = vec3(1.0, 0.9, 0.7);
    vec3 d = mix(vec3(0.03, 0.12, 0.28), vec3(0.11, 0.24, 0.43), iVariant);
    return a + b * cos(6.28318 * (c * t + d));
}

float hash(vec2 p) {
    p = fract(p * vec2(127.1, 311.7));
    p += dot(p, p + 19.19);
    return fract(p.x * p.y);
}

void main() {
    vec2 uv = v_uv * vec2(iResolution.x / iResolution.y, 1.0);
    uv += vec2(iWarpX, iWarpY) * 0.12;

    // Camera rotation
    float c = cos(iRotation);
    float s = sin(iRotation);
    uv = vec2(c * uv.x - s * uv.y, s * uv.x + c * uv.y);

    vec2 center = vec2(iCenterX, iCenterY);
    vec2 cplx = center + (uv * iOrbitScale) / iZoom;

    vec2 z = vec2(0.0);
    float orbit = 1e9;
    float trap = 1e9;
    int i;
    float m2 = 0.0;

    for (i = 0; i < iMaxIter; i++) {
        z = vec2(z.x * z.x - z.y * z.y, 2.0 * z.x * z.y) + cplx;
        m2 = dot(z, z);
        orbit = min(orbit, abs(length(z) - 0.5));
        trap = min(trap, abs(z.x) + abs(z.y) + iTrapBias * 0.02);
        if (m2 > 256.0) {
            break;
        }
    }

    vec3 col;
    if (i < iMaxIter) {
        // Escaped points: smooth iterations + orbit trap detail
        float smooth_i = float(i) - log2(log2(m2));
        float t = smooth_i / float(iMaxIter);
        float trap_mod = exp(-(11.0 + iTrapBias * 2.0) * orbit);
        float hue = t + iPalShift + iBass * 0.06 + trap_mod * (0.15 + iTrapBias * 0.08);
        hue += 0.08 * sin((z.x + z.y) * (0.55 + iSceneSeed * 0.3) + iVariant * 9.0);
        col = palette(hue);
        col += palette(hue + 0.23 + iSceneSeed * 0.17) * trap_mod * (0.30 + iTreble * 0.35);
    } else {
        // Inside set: never black; render dark nebula texture with subtle life.
        float n = hash(floor((uv + vec2(3.0, 1.7)) * (96.0 + iTrapBias * 48.0) + iPalShift * 30.0 + iSceneSeed * 90.0));
        float swirl = 0.5 + 0.5 * sin(uv.x * (20.0 + iVariant * 10.0) + uv.y * (17.0 + iSceneSeed * 6.0) + iPalShift * 10.0);
        float glow = exp(-5.0 * trap);
        vec3 deep = vec3(0.015, 0.012, 0.028);
        vec3 neb = vec3(0.06, 0.035, 0.11);
        col = mix(deep, neb, n * 0.45 + swirl * 0.35);
        col += vec3(0.08, 0.05, 0.14) * glow * (0.45 + iMid * 0.4 + iTrapBias * 0.05);
    }

    // Beat flash (small)
    col += iBeat * 0.06 * vec3(0.6, 0.4, 1.0);

    // Filmic tone map + gamma
    col = col / (col + 0.7);
    col = pow(clamp(col, 0.0, 1.0), vec3(0.4545));

    fragColor = vec4(col, 1.0);
}
"""

_TARGETS = [
    (-0.7269, 0.1889),
    (-0.5251993, 0.5260),
    (-0.74543, 0.11301),
    (-1.2561, 0.3820),
    (0.2806, 0.5338),
    (-0.8614678, 0.2325938),
]


class FractalZoom(BaseEffect):
    NAME = 'Fractal Zoom'
    AUTHOR = 'unicorn-viz'
    TAGS = ['futuristic', 'audio', 'psychedelic']
    PING_PONG_FRIENDS = [
        'Kaleidoscope',
        'Psychedelic',
        'Unicorn Tears',
        'Copper Bars',
        'Hexy Stars',
        'Plasma',
        'Prism Lattice',
        'Audio Sine',
        'Tunnel',
        'Tron Grid',
        'Hacker Terminal',
    ]

    def _init(self) -> None:
        self.parameters = {'speed': float(self.config.get('speed', 1.0)), 'max_iter': 220}
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()
        self._choose_next_target(initial=True)

        self._bass = 0.0
        self._mid = 0.0
        self._treble = 0.0
        self._beat = 0.0
        self._beat_zoom = 1.0

        # Long-run drift target to avoid repetitive framing.
        self._drift_x = 0.0
        self._drift_y = 0.0
        self._retarget_t = 0.0
        self._retarget_interval = float(self.rng.uniform(6.0, 11.0))

    def _choose_next_target(self, initial: bool = False) -> None:
        self._zoom = float(self.rng.uniform(0.50, 0.96))
        next_idx = int(self.rng.integers(0, len(_TARGETS)))
        if not initial and next_idx == getattr(self, '_target_idx', next_idx):
            next_idx = (next_idx + 1) % len(_TARGETS)
        self._target_idx = next_idx
        base_x, base_y = _TARGETS[self._target_idx]
        scene_span = 0.004 if self._zoom > 0.8 else 0.018
        self._cx = base_x + float(self.rng.uniform(-scene_span, scene_span))
        self._cy = base_y + float(self.rng.uniform(-scene_span, scene_span))
        self._rotation = float(self.rng.uniform(-math.pi, math.pi))
        self._pal_shift = float(self.rng.uniform(0.0, 1.0))
        self._variant = float(self.rng.uniform(0.0, 1.0))
        self._zoom_ceiling = float(self.rng.uniform(8.0e5, 3.2e6))
        self._warp_x = float(self.rng.uniform(-0.14, 0.14))
        self._warp_y = float(self.rng.uniform(-0.14, 0.14))
        self._orbit_scale = float(self.rng.uniform(0.90, 1.14))
        self._trap_bias = float(self.rng.uniform(0.0, 1.0))
        self._scene_seed = float(self.rng.uniform(0.0, 1.0))
        self._target_drift_x = float(self.rng.uniform(-0.018, 0.018))
        self._target_drift_y = float(self.rng.uniform(-0.018, 0.018))
        self._drift_x = 0.0
        self._drift_y = 0.0

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass_n
        self._mid = audio.mid_n
        self._treble = audio.treble_n

        if audio.beat > 0.5:
            self._beat = 1.0
            self._beat_zoom = 2.2
        self._beat = max(0.0, self._beat - dt * 4.0)
        self._beat_zoom = max(1.0, self._beat_zoom - dt * 2.8)

        speed = float(self.parameters['speed'])
        zoom_rate = 0.12 * speed * self._beat_zoom
        self._zoom *= math.exp(dt * zoom_rate)
        self._rotation += dt * (0.08 + self._bass * 0.06) * speed
        self._pal_shift = (self._pal_shift + dt * (0.032 + self._mid * 0.04) * speed) % 1.0
        self._scene_seed = (self._scene_seed + dt * 0.013 * speed) % 1.0

        # Retarget drift every few seconds.
        self._retarget_t += dt
        if self._retarget_t >= self._retarget_interval:
            self._retarget_t = 0.0
            self._retarget_interval = float(self.rng.uniform(6.0, 11.0))
            drift_span = 0.024 if self._zoom < 140.0 else 0.010
            self._target_drift_x = float(self.rng.uniform(-drift_span, drift_span))
            self._target_drift_y = float(self.rng.uniform(-drift_span, drift_span))

        blend = min(1.0, dt * 0.35)
        self._drift_x += (self._target_drift_x - self._drift_x) * blend
        self._drift_y += (self._target_drift_y - self._drift_y) * blend
        drift_mag = math.hypot(self._drift_x, self._drift_y)
        max_drift = 0.032 if self._zoom < 120.0 else 0.014
        if drift_mag > max_drift:
            scale = max_drift / max(drift_mag, 1e-6)
            self._drift_x *= scale
            self._drift_y *= scale

        # Reset well before precision trouble to avoid black traps.
        if self._zoom > self._zoom_ceiling:
            self._choose_next_target()

    def render(self) -> None:
        self._prog['iResolution'].value = (float(self.width), float(self.height))
        self._prog['iCenterX'].value = float(self._cx + self._drift_x / max(self._zoom, 1.0))
        self._prog['iCenterY'].value = float(self._cy + self._drift_y / max(self._zoom, 1.0))
        self._prog['iZoom'].value = float(self._zoom)
        self._prog['iPalShift'].value = float(self._pal_shift)
        self._prog['iBass'].value = float(self._bass)
        self._prog['iMid'].value = float(self._mid)
        self._prog['iTreble'].value = float(self._treble)
        self._prog['iBeat'].value = float(self._beat)
        self._prog['iRotation'].value = float(self._rotation)
        self._prog['iVariant'].value = float(self._variant)
        self._prog['iWarpX'].value = float(self._warp_x)
        self._prog['iWarpY'].value = float(self._warp_y)
        self._prog['iOrbitScale'].value = float(self._orbit_scale)
        self._prog['iTrapBias'].value = float(self._trap_bias)
        self._prog['iSceneSeed'].value = float(self._scene_seed)
        self._prog['iMaxIter'].value = int(self.parameters['max_iter'] + self._bass * 26.0)
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
