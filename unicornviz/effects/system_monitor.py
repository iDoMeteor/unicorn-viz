"""Hexy Stars - reactive pulsing hex/octa starfield.

Formerly the System Monitor visual mashup, this effect now focuses on the
hex/octa star lattice plus deep-space stars. Plasma and scope modes were
removed to keep a single clear visual identity.
"""
from __future__ import annotations

import moderngl

from unicornviz.effects.base import AudioData, BaseEffect

_VERT = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_FRAG = """
#version 330
uniform float iTime;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
uniform float iSpeed;
uniform float iReactivity;
uniform float iDensity;
uniform float iPulse;
uniform float iStarGlow;
uniform float iZoom;
in vec2 v_uv;
out vec4 fragColor;

float hash21(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

vec3 palette(float t) {
    vec3 a = vec3(0.5, 0.5, 0.5);
    vec3 b = vec3(0.5, 0.5, 0.5);
    vec3 c = vec3(1.0, 1.0, 1.0);
    vec3 d = vec3(0.03, 0.14, 0.34);
    return a + b * cos(6.28318 * (c * t + d));
}

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
    vec2 id = uv - gv;
    return vec4(gv, id);
}

void main() {
    vec2 uv = (v_uv - 0.5) / max(iZoom, 0.08) + 0.5;
    float t = iTime * max(iSpeed, 0.05);
    float react = max(iReactivity, 0.05);

    float bass = clamp(iBass * react, 0.0, 2.0);
    float mid = clamp(iMid * react, 0.0, 2.0);
    float treble = clamp(iTreble * react, 0.0, 2.0);

    vec3 col = mix(vec3(0.006, 0.012, 0.030), vec3(0.016, 0.010, 0.045), length(uv - 0.5));

    float density = max(1.5, iDensity);
    float bass_hit = smoothstep(0.25, 1.20, bass);
    float swell = 1.0 - bass_hit * (0.14 + 0.10 * (0.5 + 0.5 * sin(t * 8.0)));
    vec2 huv = (uv - 0.5) * density * max(0.68, swell);
    vec4 hc = hexCoords(huv);
    vec2 gv = hc.xy;
    vec2 id = hc.zw;

    float d = hexDist(gv);
    float hex_r = 0.52 + bass_hit * 0.05;
    float edge = smoothstep(0.08, 0.0, hex_r - d);
    float core = smoothstep(0.18 + bass_hit * 0.05, 0.0, d);

    // Octa-star flare from angular spokes inside each cell.
    float angle = atan(gv.y, gv.x);
    float spokes = abs(cos(angle * 4.0 + t * (1.3 + mid * 0.4)));
    float star = pow(spokes, 10.0) * smoothstep(0.45, 0.0, d);

    float seed = hash21(id);
    float pulse = 0.50 + 0.50 * sin(t * (2.0 + seed * 2.0 + bass * 0.8) + seed * 6.28318);
    float pulse_gain = (0.30 + pulse * 0.70) * (0.65 + iPulse * 0.75);

    vec3 cell_col = palette(seed + t * 0.07 + treble * 0.10);
    col += cell_col * edge * (0.24 + pulse_gain * 0.52);
    col += mix(vec3(0.10, 0.95, 0.70), vec3(0.80, 0.25, 1.00), pulse) * star * (0.30 + treble * 0.55 + iPulse * 0.45);
    col += cell_col * core * (0.08 + bass * 0.16);

    // Multi-layer stars (kept from old vibe, now supporting cast).
    vec2 suv = uv * (180.0 + iDensity * 16.0);
    vec2 scell = floor(suv);
    vec2 local = fract(suv) - 0.5;
    float pick = hash21(scell);
    float has = step(0.992, pick);
    float tw = 0.4 + 0.6 * sin(t * (4.0 + pick * 7.0) + pick * 8.0);
    float sdist = length(local - (vec2(hash21(scell + 1.2), hash21(scell + 2.4)) - 0.5) * 0.35);
    float star_core = smoothstep(0.026, 0.0, sdist);
    float star_halo = smoothstep(0.09, 0.0, sdist);
    float star_v = has * (star_core * 1.1 + star_halo * 0.45) * tw;
    col += vec3(0.82, 0.92, 1.0) * star_v * (0.18 + iStarGlow * 0.62 + treble * 0.22);

    // Light beat flash to keep it punchy.
    col += vec3(0.18, 0.08, 0.34) * bass * 0.20;

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""


class SystemMonitor(BaseEffect):
    """Hex-focused reactive effect kept under legacy class for compatibility."""

    NAME = 'Hexy Stars'
    AUTHOR = 'Autopilot'
    TAGS = ['futuristic', 'audio', 'stars', 'hex']
    PING_PONG_FRIENDS = [
        'Hacker Terminal',
        'Cyber War',
        'Copper Bars',
        'Escher',
        'Fireworks',
        'Metaballs',
        'Particle Storm',
        'Plasma',
        'Prism Lattice',
        'Psychedelic',
        'Sine Scroller 3.1',
        'Starfield',
        'Tunnel',
        'Van Gogh',
        'Wavey Gravy',
        'Tron Grid',
        'Kaleidoscope',
        'Alien Invasion',
        'Unicorn Tears',
    ]

    def _init(self) -> None:
        self.parameters = {
            'speed': float(self.config.get('speed', 1.1)),
            'reactivity': float(self.config.get('reactivity', 1.2)),
            'density': float(self.config.get('density', 7.4)),
            'pulse': float(self.config.get('pulse', 1.15)),
            'star_glow': float(self.config.get('star_glow', 1.0)),
            'zoom': float(self.config.get('zoom', 1.0)),
        }

        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad(self._prog)

        self._bass = 0.0
        self._mid = 0.0
        self._treble = 0.0

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = float(audio.bass_n)
        self._mid = float(audio.mid_n)
        self._treble = float(audio.treble_n)

    def render(self) -> None:
        self._prog['iTime'].value = self.time
        self._prog['iBass'].value = self._bass
        self._prog['iMid'].value = self._mid
        self._prog['iTreble'].value = self._treble
        self._prog['iSpeed'].value = max(0.05, float(self.parameters['speed']))
        self._prog['iReactivity'].value = max(0.05, float(self.parameters['reactivity']))
        self._prog['iDensity'].value = max(1.5, float(self.parameters['density']))
        self._prog['iPulse'].value = max(0.0, float(self.parameters['pulse']))
        self._prog['iStarGlow'].value = max(0.0, float(self.parameters['star_glow']))
        self._prog['iZoom'].value = max(0.08, float(self.parameters['zoom']))
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
