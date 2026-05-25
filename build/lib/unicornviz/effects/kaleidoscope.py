"""
Kaleidoscope — view through the eyepiece of a rotating optical kaleidoscope.

Implements the classic mirror-fold transform in the fragment shader:

  1. Convert each pixel to polar coordinates (r, θ).
  2. Rotate θ by the current object-cell rotation angle.
  3. Fold θ into a single fundamental sector via a triangle-wave remap,
     producing N-fold rotational symmetry where adjacent sectors are
     perfect mirror images of each other (as in a real 2-mirror kaleidoscope).
  4. Sample a domain-warped, multi-frequency sinusoidal source field at the
     folded Cartesian coordinate — analogous to looking at the loose coloured
     glass objects at the end of the tube.
  5. Map through a saturated jewel-glass palette (sapphire, emerald, ruby,
     amethyst, citrine).

Audio-reactive behaviour:
  bass   → zoom breathing and object-cell rotation speed kick
  mid    → palette saturation boost and hue phase drift
  treble → high-frequency sparkle shimmer on bright edges
  beat   → exponentially decaying iris brightness flash
"""
from __future__ import annotations

import math

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
/*
 * Fragment shader — kaleidoscope fold + jewel-glass source field.
 * Uniforms: iTime, iResolution, iBass, iMid, iTreble, iBeat,
 *           iSpeed, iZoom, iSegments, iRotation
 * Outputs:  fragColor in [0,1]^4
 */
uniform float iTime;
uniform vec2  iResolution;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
uniform float iBeat;
uniform float iSpeed;
uniform float iZoom;
uniform float iSegments;
uniform float iRotation;

in  vec2 v_uv;
out vec4 fragColor;

const float TAU = 6.28318530718;

// Jewel-glass palette — runs through sapphire → cyan → emerald → amber → ruby
// → amethyst → sapphire as t advances from 0 to 1.
vec3 palette(float t) {
    vec3 a = vec3(0.52, 0.50, 0.55);
    vec3 b = vec3(0.48, 0.50, 0.45);
    vec3 c = vec3(1.00, 1.00, 1.00);
    vec3 d = vec3(0.05, 0.33, 0.68);
    return a + b * cos(TAU * (c * t + d));
}

mat2 rot2(float a) {
    float c = cos(a), s = sin(a);
    return mat2(c, -s, s, c);
}

// Domain-warped multi-frequency sinusoidal field.
// Resembles the organic flow of loose coloured glass shards.
// Returns a value in approx [-1, 1].
float sourceField(vec2 p, float t) {
    float wx = sin(p.y * 1.80 + t * 0.30) + sin(p.x * 2.40 - t * 0.20);
    float wy = cos(p.x * 1.60 - t * 0.40) + cos(p.y * 2.20 + t * 0.30);
    p += vec2(wx, wy) * 0.22;
    float v  = sin(p.x * 3.10 + t * 0.70);
          v += sin(p.y * 2.70 - t * 0.55);
          v += sin((p.x + p.y) * 2.30 + t * 0.85);
          v += sin(length(p) * 4.80 - t * 1.10);
          v += sin(p.x * 1.70 - p.y * 3.10 + t * 0.60);
          v += 0.6 * sin(p.x * 5.50 + sin(p.y * 3.90 + t * 0.25) + t * 0.45);
    return v * 0.167;
}

void main() {
    // uv: aspect-corrected for geometry so circles are circular.
    vec2 uv    = v_uv;
    uv.x      *= iResolution.x / iResolution.y;

    // Bass breathes the zoom gently.
    float zoom   = clamp(iZoom * (1.0 + iBass * 0.15), 0.1, 3.0);
    vec2  p      = uv / zoom;
    float r      = length(p);
    float a      = atan(p.y, p.x) + iRotation;

    // Triangle-wave fold: maps any full-circle angle into [0, sector],
    // naturally mirroring alternate sectors — identical to 2-mirror geometry.
    float sector = TAU / max(iSegments, 2.0);
    float afold  = abs(mod(a / sector, 2.0) - 1.0) * sector;

    // Cartesian source sample point (the fundamental wedge in Cartesian space).
    vec2 src     = r * vec2(cos(afold), sin(afold));

    float t      = iTime * iSpeed;
    float v1     = sourceField(src, t);
    // Second layer at a different angle and scale for richer colour variation.
    float v2     = sourceField(src * rot2(0.61) * 1.40, t * 0.57 + 5.13);

    float hue    = v1 * 0.5 + 0.5;
    float hue2   = v2 * 0.5 + 0.5;
    vec3  col    = palette(hue + hue2 * 0.28 + iMid * 0.12);

    // Saturation boost beyond 1.0 gives the deep gem-glass vibrancy.
    float lum    = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(vec3(lum), col, 1.55 + iMid * 0.55);

    // Radial brightness: bright centre, dark rim (simulates glass depth/focus).
    col *= 0.30 + 0.90 * (1.0 - smoothstep(0.0, 1.2 / zoom, r));

    // Treble sparkle: shimmer on the high-curvature boundaries.
    col += iTreble * 0.18 * max(0.0, sin(v1 * 8.0 + t * 3.0));

    // Beat iris flash — complementary hue for visible pop.
    col += iBeat * 0.22 * palette(hue + 0.5);

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""


class Kaleidoscope(BaseEffect):
    """Classic optical kaleidoscope — N-fold mirror symmetry over a jewel-glass source field.

    Parameters
    ----------
    speed:
        Overall animation speed multiplier (0.1 – 4.0).
    segments:
        Number of mirror-image sectors visible in the full circle.
        Even values give the most symmetric results; 12 is the classic
        hexagonal star pattern (analogous to two mirrors at 30°).
    zoom:
        Zoom into the source material (0.3 – 2.0).  Lower values show
        finer detail; higher values show broader organic forms.
    """

    NAME   = 'Kaleidoscope'
    AUTHOR = 'unicorn-viz'
    TAGS   = ['classic', 'audio', 'psychedelic']
    PING_PONG_FRIENDS = ['Fractal Zoom', 'Psychedelic', 'Unicorn Tears']

    def _init(self) -> None:
        self.parameters = {
            'speed':    float(self.config.get('speed',    1.0)),
            'segments': float(self.config.get('segments', 12.0)),
            'zoom':     float(self.config.get('zoom',     0.62)),
        }
        self._rotation: float = float(self.rng.uniform(0.0, 6.28318))
        self._bass:     float = 0.0
        self._mid:      float = 0.0
        self._treble:   float = 0.0
        self._beat:     float = 0.0
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass   = audio.bass_n
        self._mid    = audio.mid_n
        self._treble = audio.treble_n

        # Beat decays exponentially between hits.
        self._beat = max(0.0, self._beat - dt * 4.0)
        if audio.beat > 0.5:
            self._beat = 1.0

        # Object cell rotates continuously; bass adds a rotational kick.
        rot_rate = self.parameters['speed'] * 0.12 + self._bass * 0.25 * self.parameters['speed']
        self._rotation = math.fmod(self._rotation + dt * rot_rate, math.tau)

    def render(self) -> None:
        p = self._prog
        p['iTime'].value       = self.time
        p['iResolution'].value = (float(self.width), float(self.height))
        p['iBass'].value       = self._bass
        p['iMid'].value        = self._mid
        p['iTreble'].value     = self._treble
        p['iBeat'].value       = self._beat
        p['iSpeed'].value      = self.parameters['speed']
        p['iZoom'].value       = self.parameters['zoom']
        p['iSegments'].value   = self.parameters['segments']
        p['iRotation'].value   = self._rotation
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
