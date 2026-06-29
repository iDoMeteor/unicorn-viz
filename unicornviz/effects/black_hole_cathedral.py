"""
Black Hole Cathedral — a gothic mega-structure orbiting an accretion lens.

A screen-space gravitational-lens shader: an event horizon crushes light to
black at the centre, a swirling Doppler-beamed accretion disk rings it, a bright
photon ring traces the lensed edge, and a folded-angle rose-window tracery forms
a cathedral around it that "breathes" with the bass like a choir swell.

Audio-reactive:
  - bass   → gravity/mass swell (lens strength, horizon size, window glow pulse)
  - mid    → disk + tracery rotation and turbulence
  - treble → starfield twinkle
  - beat   → one-shot violet bloom

Per-instance randomisation (hue, petal count, spin direction, time phase) keeps
every run visually distinct from frame 0.
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
// Black Hole Cathedral — gravitational-lens + rose-window fragment shader.
// Uniforms (Shadertoy-style 'i' prefix); produces fragColor.
uniform float iTime;
uniform vec2  iResolution;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
uniform float iBeat;
uniform float iHue;     // palette offset [0,1]
uniform float iPetals;  // rose-window fold count
uniform float iSpin;    // +1 / -1 rotation direction
uniform float iSpeed;
in  vec2 v_uv;
out vec4 fragColor;

float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

vec3 hsv2rgb(vec3 c) {
    vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

void main() {
    vec2 uv = v_uv;
    uv.x *= iResolution.x / iResolution.y;
    float t = iTime * 0.2 * iSpeed * iSpin;
    float grav = 0.6 + iBass * 0.55;            // mass / choir swell

    float r = length(uv);
    vec2 dir = uv / max(r, 1e-4);

    // Gravitational lensing: pull samples toward the centre, strongest near it.
    float lens = grav * 0.15 / (r * r + 0.05);
    vec2 luv = uv - dir * lens;
    float lr = length(luv);
    float la = atan(luv.y, luv.x);

    vec3 col = vec3(0.0);

    // Lensed starfield.
    vec2 sg = floor(luv * 120.0);
    float star = pow(hash21(sg), 62.0);
    star *= 0.5 + 0.9 * iTreble * (0.5 + 0.5 * sin(iTime * 9.0 + hash21(sg) * 40.0));
    col += vec3(0.8, 0.85, 1.0) * star;

    // Accretion disk: swirling, turbulent, Doppler-beamed hot band.
    float ringR = 0.42;
    float band = smoothstep(0.17, 0.0, abs(lr - ringR));
    float swirl = 0.5 + 0.5 * sin(la - lr * 11.0 + t * 6.0 + iMid * 4.0);
    float turb = 0.5 + 0.5 * sin(la * 8.0 + t * 9.0 + sin(la * 3.0 + t * 4.0));
    float doppler = 0.55 + 0.45 * cos(la - t * 2.0);    // one side beamed brighter
    float disk = band * swirl * turb * doppler;
    float heat = clamp(disk * 1.7 + (ringR - lr) * 0.6, 0.0, 1.0);
    vec3 hot = mix(vec3(1.0, 0.96, 0.72), vec3(1.0, 0.36, 0.06), heat);
    hot = mix(hot, vec3(0.65, 0.12, 0.55), smoothstep(0.55, 1.0, heat));
    col += hot * disk * (1.5 + iBass * 1.2);

    // Photon ring — thin bright lensed circle at the horizon edge.
    float photon = smoothstep(0.018, 0.0, abs(r - 0.205 * grav));
    col += vec3(1.0, 0.92, 0.82) * photon * 1.6;

    // Gothic rose-window tracery: folded angular symmetry forms petals/arches.
    float a = atan(uv.y, uv.x) + t * 0.5;
    float fa = abs(fract(a / 6.28318 * iPetals) * 2.0 - 1.0);
    float arch = smoothstep(0.03, 0.0,
                            abs(fa - 0.5) - 0.18 * sin(r * 15.0 - t * 3.0 + iMid * 3.0));
    float ribs = smoothstep(0.03, 0.0, fa);
    float window = (arch * 0.6 + ribs * 0.4)
                   * smoothstep(1.05, 0.28, r)
                   * smoothstep(0.24 * grav, 0.32, r);
    vec3 glass = hsv2rgb(vec3(iHue + fa * 0.28 + r * 0.18, 0.72, 1.0));
    col += glass * window * (0.5 + iBass * 0.9);

    // Event horizon: crush to black at the centre.
    col *= 1.0 - smoothstep(0.21 * grav, 0.19 * grav, r);

    // Beat bloom + soft vignette.
    col += vec3(1.0, 0.8, 1.0) * iBeat * 0.16 * smoothstep(0.6, 0.0, r);
    col *= 1.0 - 0.42 * smoothstep(0.7, 1.45, length(v_uv));

    // Tonemap.
    col = col / (1.0 + col);
    col = pow(col, vec3(0.85));
    fragColor = vec4(col, 1.0);
}
"""


class BlackHoleCathedral(BaseEffect):
    NAME = "Black Hole Cathedral"
    AUTHOR = "unicorn-viz"
    TAGS = ["cosmic", "shader", "audio", "cathedral"]
    PING_PONG_FRIENDS = [
        'Cosmos',
        'Starfield',
        'Tunnel',
        'Psychedelic',
        'Kaleidoscope',
        'Plasma',
        'Unicorn Tears',
    ]

    def _init(self) -> None:
        self.parameters = {
            "speed": float(self.config.get("speed", 1.0)),
            # Startup randomisation so two runs look distinct from frame 0.
            "hue": float(self.rng.uniform(0.0, 1.0)),
            "petals": float(self.rng.choice([8.0, 10.0, 12.0, 16.0, 20.0])),
            "spin": float(self.rng.choice([-1.0, 1.0])),
        }
        self._bass = 0.0
        self._mid = 0.0
        self._treble = 0.0
        self._beat = 0.0
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass_n
        self._mid = audio.mid_n
        self._treble = audio.treble_n
        # Exponential-decay beat envelope for a clean one-shot bloom.
        self._beat = max(0.0, self._beat - dt * 4.0)
        if audio.beat:
            self._beat = 1.0
        # Slow hue drift so the cathedral's stained glass evolves over a set.
        self.parameters["hue"] = (
            self.parameters["hue"] + dt * 0.02 * self.parameters["speed"]
        ) % 1.0

    def render(self) -> None:
        p = self._prog
        p["iTime"].value = self.time
        p["iResolution"].value = (float(self.width), float(self.height))
        p["iBass"].value = self._bass
        p["iMid"].value = self._mid
        p["iTreble"].value = self._treble
        p["iBeat"].value = self._beat
        p["iHue"].value = self.parameters["hue"]
        p["iPetals"].value = self.parameters["petals"]
        p["iSpin"].value = self.parameters["spin"]
        p["iSpeed"].value = self.parameters["speed"]
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
