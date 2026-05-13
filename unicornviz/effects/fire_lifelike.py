"""
Fire — lifelike procedural fire shader.

A fully procedural flame field with layered domain-warped noise,
upward buoyancy flow, ember flicker, and warm blackbody palette mapping.
Designed to feel more realistic than the old cellular-strip style.

Audio reactivity:
  - bass   → flame body lift/intensity
  - mid    → turbulence detail
  - beat   → brief bloom/flare pulses
  - treble → tip sparkle/flicker
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
uniform float iTreble;
uniform float iIntensity;
uniform float iSpeed;

in vec2 v_uv;
out vec4 fragColor;

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    float a = hash(i + vec2(0.0, 0.0));
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

float fbm(vec2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 6; i++) {
        v += a * noise(p);
        p = p * 2.03 + vec2(0.17, -0.11);
        a *= 0.5;
    }
    return v;
}

vec3 firePalette(float t) {
    t = clamp(t, 0.0, 1.0);
    vec3 c0 = vec3(0.02, 0.01, 0.01);
    vec3 c1 = vec3(0.35, 0.05, 0.00);
    vec3 c2 = vec3(0.95, 0.30, 0.02);
    vec3 c3 = vec3(1.00, 0.72, 0.12);
    vec3 c4 = vec3(1.00, 0.96, 0.65);
    float s = t * 4.0;
    int i = int(s);
    float f = fract(s);
    if (i == 0) return mix(c0, c1, f);
    if (i == 1) return mix(c1, c2, f);
    if (i == 2) return mix(c2, c3, f);
    return mix(c3, c4, f);
}

void main() {
    vec2 uv = v_uv;
    vec2 p = uv * 2.0 - 1.0;
    p.x *= iResolution.x / max(iResolution.y, 1.0);

    float t = iTime * (0.65 + iSpeed * 0.75);

    // Upward advection with side sway
    vec2 flow = vec2(
        0.22 * sin(t * 0.8 + p.y * 5.0) + 0.09 * sin(t * 1.9 + p.y * 9.0),
        -t * (1.5 + iBass * 0.9)
    );

    // Domain-warped turbulence
    vec2 q = p;
    q += vec2(
        0.15 * sin(p.y * 7.0 + t * 1.3),
        0.10 * sin(p.x * 5.0 - t * 1.7)
    );
    float n1 = fbm(q * 2.1 + flow);
    float n2 = fbm((q + vec2(1.7, 2.3)) * 3.4 + flow * 1.35 + iMid * 0.6);

    float flame = n1 * 0.78 + n2 * 0.42;

    // Flame body mask: wider at bottom, thinner at top
    float body = smoothstep(1.10, 0.10, uv.y);
    float taper = 1.0 - smoothstep(0.0, 1.0, abs(p.x) * (0.75 + uv.y * 1.35));
    float field = flame * body * taper;

    // Base ignition + beat bloom
    float base = smoothstep(0.45, 0.0, uv.y) * (0.45 + iIntensity * 0.65 + iBass * 0.45);
    field += base;
    field += iBeat * 0.22 * smoothstep(0.75, 0.02, uv.y);

    // Tip sparkle / treble shimmer
    float sparkle = smoothstep(0.78, 1.0, field) * (0.35 + iTreble * 0.9);
    field += sparkle * (0.08 + 0.10 * sin(t * 17.0 + p.y * 33.0));

    field = clamp(field, 0.0, 1.0);
    vec3 col = firePalette(pow(field, 0.88));

    // Soft smoke-darkening at the top
    float smoke = smoothstep(0.35, 1.0, uv.y) * (1.0 - smoothstep(0.0, 0.55, field));
    col = mix(col, col * vec3(0.55, 0.45, 0.42), smoke * 0.45);

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""


class Fire(BaseEffect):
    """Lifelike procedural fire with strong audio reactivity."""

    NAME = "Fire"
    AUTHOR = "unicorn-viz"
    TAGS = ["classic", "audio", "shader"]

    def _init(self) -> None:
        self.parameters = {
            "intensity": float(self.rng.uniform(0.70, 1.00)),
            "speed": 1.0,
        }
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()
        self._bass = 0.0
        self._mid = 0.0
        self._treble = 0.0
        self._beat = 0.0

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass
        self._mid = audio.mid
        self._treble = audio.treble
        if audio.beat > 0.5:
            self._beat = 1.0
        self._beat = max(0.0, self._beat - dt * 4.2)

    def render(self) -> None:
        self._prog["iTime"].value = self.time
        self._prog["iResolution"].value = (float(self.width), float(self.height))
        self._prog["iBass"].value = self._bass
        self._prog["iMid"].value = self._mid
        self._prog["iBeat"].value = self._beat
        self._prog["iTreble"].value = self._treble
        self._prog["iIntensity"].value = float(self.parameters["intensity"])
        self._prog["iSpeed"].value = float(self.parameters["speed"])
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
