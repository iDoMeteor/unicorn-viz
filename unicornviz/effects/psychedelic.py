"""Psychedelic — animated palette-sine neon field.

Full-screen shader that blends overlapping sine waves into a continuously
shifting colour palette, crossed with a subtle neon grid.  Audio-reactive:
bass pumps the palette offset and treble shifts colour temperature.

Originally the background layer of the webcam-01 drop-in; promoted to a
first-class playlist effect.
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
// Psychedelic — palette-sine neon field.
// Uniforms: iTime, iBass, iMid, iTreble, iSpeed, iZoom.
// Outputs: fragColor (RGBA).
uniform float iTime;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
uniform float iSpeed;
uniform float iZoom;
uniform float iZoomPulse;
in  vec2 v_uv;
out vec4 fragColor;

vec3 palette(float t) {
    vec3 a = vec3(0.5);
    vec3 b = vec3(0.5);
    vec3 c = vec3(1.0);
    vec3 d = vec3(0.02, 0.15, 0.35);
    return a + b * cos(6.28318 * (c * t + d));
}

void main() {
    vec2 uv = (v_uv - 0.5) / max(iZoom * iZoomPulse, 0.08) + 0.5;
    float t = iTime * iSpeed;
    float f = 0.0;
    f += sin(uv.x * 16.0 + t * 1.2) * 0.25;
    f += sin(uv.y * 13.0 - t * 1.1) * 0.22;
    f += sin((uv.x + uv.y) * 8.0 + t * 0.7) * 0.18;
    f += sin((uv.x - uv.y) * 11.0 + t * 0.9) * 0.14;
    f += iMid * 0.12;

    float beat = iBass * 0.35 + iTreble * 0.15;
    vec3 col = palette(f + t * 0.05 + beat);
    col = mix(col, vec3(0.04, 0.05, 0.09), 0.30);

    // Subtle neon grid overlay.
    float grid = smoothstep(0.025, 0.0, abs(fract(uv.x * 12.0) - 0.5))
               + smoothstep(0.025, 0.0, abs(fract(uv.y *  7.0) - 0.5));
    col += vec3(0.08, 0.18, 0.28) * grid * (0.22 + iTreble * 0.18);

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""


class Psychedelic(BaseEffect):
    """Animated palette-sine neon field effect.

    Combines overlapping sine waves with a continuously shifting colour
    palette and a subtle neon grid.  All three audio bands drive the
    animation.
    """

    NAME   = 'Psychedelic'
    AUTHOR = 'unicorn-viz'
    TAGS   = ['psychedelic', 'audio', 'shader']
    PING_PONG_FRIENDS = [
        'Fractal Zoom',
        'Kaleidoscope',
        'Unicorn Tears',
        'Copper Bars',
        'Escher',
        'Hexy Stars',
        'Metaballs',
        'Plasma',
        'Prism Lattice',
        'Tunnel',
        'Wavey Gravy',
        'Tron Grid',
        'Alien Invasion',
        'Hacker Terminal',
        'Cyber War',
    ]

    def _init(self) -> None:
        self.parameters = {
            'speed': float(self.config.get('speed', 1.0)),
            'zoom': float(self.config.get('zoom', 1.0)),
        }
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad(self._prog)
        self._bass   = 0.0
        self._mid    = 0.0
        self._treble = 0.0
        self._beat   = 0.0
        self._zoom_pulse = 1.0

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass   = audio.bass_n
        self._mid    = audio.mid_n
        self._treble = audio.treble_n
        if audio.beat > 0.5:
            self._beat = 1.0
        self._beat = max(0.0, self._beat - dt * 3.8)
        target_pulse = 1.0 + self._bass * 0.06 + self._beat * 0.10
        self._zoom_pulse += (target_pulse - self._zoom_pulse) * min(1.0, dt * 7.0)

    def render(self) -> None:
        def _set(name: str, value) -> None:
            try:
                self._prog[name].value = value
            except KeyError:
                pass

        _set('iTime',   self.time)
        _set('iBass',   self._bass)
        _set('iMid',    self._mid)
        _set('iTreble', self._treble)
        _set('iSpeed',  float(self.parameters['speed']))
        _set('iZoom',   max(0.08, float(self.parameters['zoom'])))
        _set('iZoomPulse', float(self._zoom_pulse))
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
