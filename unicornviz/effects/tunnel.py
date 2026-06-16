"""
Tunnel 2.0 — fully procedural infinite tunnel, no texture dependency.

Features:
  - Three nested tunnels with independent twist/speed for parallax depth
  - Prismatic colour cycling driven by angle + depth + time
  - Glowing ring pulses that race toward the viewer on every beat
  - Chromatic aberration on tube edges driven by bass
  - Hex/diamond wall pattern etched into the tunnel surface
  - Mid controls hue rotation speed; treble brightens edge glow
  - No vignette by default
"""
from __future__ import annotations

import moderngl

from unicornviz.effects.base import BaseEffect, AudioData

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
uniform float iTime;
uniform float iSpeed;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
uniform float iBeat;
uniform float iVignette;
uniform vec2  iResolution;

in  vec2 v_uv;
out vec4 fragColor;

#define PI  3.14159265359
#define TAU 6.28318530718

vec3 palette(float t) {
    vec3 a = vec3(0.5, 0.5, 0.5);
    vec3 b = vec3(0.5, 0.5, 0.5);
    vec3 c = vec3(1.0, 0.85, 0.65);
    vec3 d = vec3(0.00, 0.15, 0.35);
    return a + b * cos(TAU * (c * t + d));
}

// Diamond/hex tile pattern for tunnel walls
float wallPattern(float angle, float depth) {
    float ua = angle * 8.0;
    float ud = depth * 12.0;
    float da = abs(fract(ua) - 0.5);
    float dd = abs(fract(ud) - 0.5);
    float line = smoothstep(0.46, 0.50, max(da, dd));
    return 1.0 - line * 0.55;
}

// One tunnel layer: returns colour contribution
vec3 tunnelLayer(vec2 p, float t, float twist_rate, float fly_speed,
                 float radius, float hue_off, float ca_amt) {
    float dist  = length(p);
    float angle = atan(p.y, p.x) / TAU;        // 0..1

    // Perspective depth from origin
    float depth = radius / (dist + 0.0001);

    float twist = t * twist_rate + iBass * 0.35;
    float fly   = t * fly_speed;

    float ua = angle + twist;
    float ud = depth - fly;

    // Chromatic-aberration sampling (R shifted, B counter-shifted)
    float dist_r = length(p * (1.0 + ca_amt));
    float dist_b = length(p * (1.0 - ca_amt));
    float depth_r = radius / (dist_r + 0.0001);
    float depth_b = radius / (dist_b + 0.0001);

    // Tunnel wall tile: use chromatic-split depths for R and B
    float wall   = wallPattern(ua, ud);
    float wall_r = wallPattern(ua + ca_amt * 0.12, depth_r - fly);
    float wall_b = wallPattern(ua - ca_amt * 0.12, depth_b - fly);

    // Prismatic colour: angle + depth + time + mid hue rotation
    float hue = fract(ua * 0.5 + ud * 0.08 + t * (0.04 + iMid * 0.12) + hue_off);
    vec3 col = palette(hue);

    // Edge glow at tunnel mouth (near centre)
    float edge = smoothstep(0.4, 0.0, dist) * (0.35 + iTreble * 0.55);
    col += palette(hue + 0.33) * edge;

    // Apply wall pattern with chromatic split
    col.r *= wall_r;
    col.g *= wall;
    col.b *= wall_b;

    // Depth fog: fade far rings
    float fog = exp(-dist * 1.4);
    col *= fog + 0.10;

    // Bass-driven brightness swell
    col *= 0.62 + iBass * 0.52;

    return col;
}

// Beat ring pulse: a bright ring expanding outward from centre
float beatRing(vec2 p, float t, float beat) {
    if (beat < 0.01) return 0.0;
    float r   = length(p);
    // Ring starts small and expands to ~1.2 as beat decays
    float ring_r = (1.0 - beat) * 1.1;
    float ring = smoothstep(0.04, 0.0, abs(r - ring_r));
    return ring * beat * 1.2;
}

void main() {
    float ar = iResolution.x / iResolution.y;
    vec2 p = v_uv * vec2(ar, 1.0);
    float t = iTime * iSpeed;

    // Three nested tunnels at different scales/speeds for parallax depth
    vec3 col  = tunnelLayer(p,         t, 0.18, 0.42, 0.28, 0.00, iBass * 0.04);
    col      += tunnelLayer(p * 1.55,  t, 0.24, 0.60, 0.28, 0.35, iBass * 0.03) * 0.65;
    col      += tunnelLayer(p * 2.4,   t, 0.31, 0.85, 0.28, 0.62, iBass * 0.02) * 0.40;

    // Beat ring flash
    float ring = beatRing(v_uv * vec2(ar, 1.0), t, iBeat);
    col += palette(fract(t * 0.15)) * ring;

    // Optional vignette (off by default)
    if (iVignette > 0.01) {
        col *= 1.0 - iVignette * smoothstep(0.5, 1.2, length(v_uv));
    }

    // Filmic tone-map + gamma
    col = col / (col + 0.6);
    col = pow(clamp(col, 0.0, 1.0), vec3(0.4545));
    // Slight default contrast boost + darker baseline.
    col = clamp((col - 0.5) * 1.08 + 0.5, 0.0, 1.0);
    col *= 0.93;

    fragColor = vec4(col, 1.0);
}
"""


class Tunnel(BaseEffect):
    """Procedural infinite tunnel with prismatic colour and beat ring pulses."""

    NAME   = "Tunnel"
    AUTHOR = "unicorn-viz"
    TAGS   = ["classic", "audio", "futuristic"]
    PING_PONG_FRIENDS = [
        'Plasma',
        'Wavey Gravy',
        'Particle Storm',
        'Copper Bars',
        'Escher',
        'Fireworks',
        'Hexy Stars',
        'Metaballs',
        'Prism Lattice',
        'Psychedelic',
        'Sine Scroller 3.1',
        'Starfield',
        'Van Gogh',
        'Tron Grid',
        'Kaleidoscope',
        'Alien Invasion',
        'Hacker Terminal',
        'Cyber War',
        'Unicorn Tears',
        'Cosmos',
    ]

    def _init(self) -> None:
        self.parameters = {"speed": float(self.config.get("speed", 1.0)), "vignette": 0.0}
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()
        self._bass   = 0.0
        self._mid    = 0.0
        self._treble = 0.0
        self._beat   = 0.0

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass   = audio.bass_n
        self._mid    = audio.mid_n
        self._treble = audio.treble_n
        if audio.beat > 0.5:
            self._beat = 1.0
        self._beat = max(0.0, self._beat - dt * 3.5)

    def render(self) -> None:
        self._prog["iTime"].value       = self.time
        self._prog["iResolution"].value = (float(self.width), float(self.height))
        self._prog["iSpeed"].value      = float(self.parameters["speed"])
        self._prog["iVignette"].value   = float(self.parameters["vignette"])
        self._prog["iBass"].value       = self._bass
        self._prog["iMid"].value        = self._mid
        self._prog["iTreble"].value     = self._treble
        self._prog["iBeat"].value       = self._beat
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
