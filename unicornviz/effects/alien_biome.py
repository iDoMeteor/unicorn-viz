"""
Alien Biome — pulsating organic landscape with bioluminescent veins.

Audio reactivity:
- bass: bloom intensity and terrain wobble
- mid: vein activity and hue drift
- beat: shockwave pulse
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
    for (int i = 0; i < 5; i++) {
        v += a * noise(p);
        p *= 2.03;
        a *= 0.5;
    }
    return v;
}

void main() {
    vec2 uv = (v_uv * 2.0 - 1.0);
    uv.x *= iResolution.x / max(iResolution.y, 1.0);

    float t = iTime * (0.35 + iSpeed * 0.9);

    // Organic height field.
    float h = fbm(uv * 2.1 + vec2(0.0, t * 0.5));
    h += 0.18 * sin(uv.x * 6.0 + t * 2.5 + iBass * 5.0);

    // Vein mask.
    float veins = abs(sin((h + uv.y * 1.6) * 22.0 + t * 6.0));
    veins = pow(1.0 - veins, 6.0);

    float ridge = smoothstep(0.25, 0.9, h + 0.12 * iBass);
    float glow = veins * (0.35 + 1.2 * iMid) + iBeat * 0.45;

    vec3 base = mix(vec3(0.02, 0.06, 0.04), vec3(0.10, 0.22, 0.08), ridge);
    vec3 bio  = mix(vec3(0.1, 0.9, 0.5), vec3(0.7, 0.1, 1.0), 0.5 + 0.5 * sin(t * 0.4));

    vec3 col = base + bio * glow;

    // Atmospheric haze.
    float fog = exp(-1.7 * max(uv.y + 0.55, 0.0));
    col = mix(vec3(0.01, 0.02, 0.03), col, fog);

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""


class AlienBiome(BaseEffect):
    NAME = "Wavey Gravy"
    AUTHOR = "unicorn-viz"
    TAGS = ["sci-fi", "audio", "shader"]
    PING_PONG_FRIENDS = ['Tunnel', 'Water', 'Psychedelic']

    def _init(self) -> None:
        self.parameters = {"speed": float(self.config.get("speed", 1.0))}
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()
        self._bass = 0.0
        self._mid = 0.0
        self._beat = 0.0

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass
        self._mid = audio.mid
        if audio.beat > 0.5:
            self._beat = 1.0
        self._beat = max(0.0, self._beat - dt * 3.0)

    def render(self) -> None:
        self._prog["iTime"].value = self.time
        self._prog["iResolution"].value = (float(self.width), float(self.height))
        self._prog["iBass"].value = self._bass
        self._prog["iMid"].value = self._mid
        self._prog["iBeat"].value = self._beat
        self._prog["iSpeed"].value = float(self.parameters["speed"])
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
