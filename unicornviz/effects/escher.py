"""
Escher — impossible-style tiling corridor illusion.

Audio reactivity:
- bass: depth pulse
- mid: tile morphing
- beat: inversion flashes
"""
from __future__ import annotations

import moderngl

from unicornviz.effects.base import BaseEffect, AudioData

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
uniform vec2  iResolution;
uniform float iBass;
uniform float iMid;
uniform float iBeat;
uniform float iSpeed;
uniform float iVignette;

in vec2 v_uv;
out vec4 fragColor;

mat2 rot(float a) {
    float c = cos(a), s = sin(a);
    return mat2(c, -s, s, c);
}

float box(vec2 p, vec2 b) {
    vec2 d = abs(p) - b;
    return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0);
}

void main() {
    vec2 uv = v_uv * 2.0 - 1.0;
    uv.x *= iResolution.x / max(iResolution.y, 1.0);

    float t = iTime * (0.35 + iSpeed * 0.8);

    // Pseudo-perspective grid warp for impossible corridor feel.
    float depth = 1.0 / (1.0 + abs(uv.y) * (1.4 + iBass * 1.2));
    vec2 p = uv * depth;
    p = rot(0.25 * sin(t * 0.7)) * p;

    vec2 g = p * (9.0 + iMid * 6.0);
    vec2 id = floor(g);
    vec2 fp = fract(g) - 0.5;

    float tile = step(0.5, fract(id.x * 0.5 + id.y * 0.5));
    float edge = smoothstep(0.08, 0.02, abs(box(fp, vec2(0.42, 0.42))));

    // Slow palette drift so the checkerboard breathes over longer runs.
    float pal = 0.5 + 0.5 * sin(t * 0.22 + (id.x + id.y) * 0.03 + iMid * 2.0);
    vec3 cA = mix(vec3(0.95, 0.95, 0.90), vec3(0.86, 0.90, 1.00), pal);
    vec3 cB = mix(vec3(0.05, 0.05, 0.08), vec3(0.10, 0.04, 0.12), pal);
    vec3 col = mix(cA, cB, tile);

    // Outline network
    col = mix(col, vec3(0.2, 0.8, 1.0), edge * 0.6);

    // Impossible inversion bands
    float bands = smoothstep(0.4, 0.0, abs(sin((p.x + p.y) * 5.0 + t * 1.4)));
    col = mix(col, 1.0 - col, bands * (0.18 + iBeat * 0.35));

    // Foreground shadow/accent lines with dynamic color/brightness/opacity.
    float stripe = abs(fract((p.x * 0.58 - p.y * 0.36) * 10.0 + t * 0.75) - 0.5);
    float lineMask = smoothstep(0.085, 0.0, stripe);
    float linePulse = 0.5 + 0.5 * sin(t * 2.0 + p.x * 3.2 + p.y * 2.4);
    vec3 lineCol = mix(vec3(0.05, 0.55, 1.0), vec3(1.0, 0.25, 0.75), linePulse);
    float lineAlpha = (0.12 + 0.26 * linePulse + iMid * 0.15) * (0.45 + 0.55 * depth);
    vec3 lineTarget = clamp(col + lineCol * (0.35 + iBass * 0.22), 0.0, 1.0);
    col = mix(col, lineTarget, clamp(lineMask * lineAlpha, 0.0, 0.85));

    // Depth vignette (disabled by default unless iVignette > 0)
    float vig = smoothstep(1.6, 0.25, length(uv));
    col *= mix(1.0, vig, clamp(iVignette, 0.0, 1.0));

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""


class Escher(BaseEffect):
    NAME = "Escher"
    AUTHOR = "unicorn-viz"
    TAGS = ["art", "optical", "audio"]
    SPEED_TIME_BIAS = 0.35
    SPEED_TIME_SCALE = 0.8
    PING_PONG_FRIENDS = [
        'Van Gogh',
        'Hexy Stars',
        'Particle Storm',
        'Prism Lattice',
        'Psychedelic',
        'Audio Sine',
        'Tunnel',
        'Wavey Gravy',
        'Tron Grid',
        'Kaleidoscope',
        'Hacker Terminal',
    ]

    def _init(self) -> None:
        self.scale_when_framed = bool(self.config.get('scale_when_framed', True))
        self.parameters = {
            "speed": float(self.config.get("speed", 1.0)),
            "vignette": 0.0,
        }
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()
        self._bass = 0.0
        self._mid = 0.0
        self._beat = 0.0

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass_n
        self._mid = audio.mid
        if audio.beat > 0.5:
            self._beat = 1.0
        self._beat = max(0.0, self._beat - dt * 4.0)

    def render(self) -> None:
        self._prog["iTime"].value = self.time
        self._prog["iResolution"].value = (float(self.width), float(self.height))
        self._prog["iBass"].value = self._bass
        self._prog["iMid"].value = self._mid
        self._prog["iBeat"].value = self._beat
        self._prog["iSpeed"].value = float(self.parameters["speed"])
        self._prog["iVignette"].value = float(self.parameters.get("vignette", 0.0))
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
