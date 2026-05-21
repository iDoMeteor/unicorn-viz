"""
Dali — surreal melting forms and mirage-like distortions.

Audio reactivity:
- bass: melt deformation amplitude
- mid: chroma drift
- beat: temporal stretch pulses + occasional counter-rotations
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
uniform float iRotBg;
uniform float iRotFg;

in vec2 v_uv;
out vec4 fragColor;

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(21.7, 91.3))) * 48372.3);
}

float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

float sdBlob(vec2 p, vec2 c, float r, float wob, float t) {
    vec2 q = p - c;
    float a = atan(q.y, q.x);
    float rr = r + wob * sin(a * 5.0 + t);
    return length(q) - rr;
}

vec2 rot2d(vec2 p, float a) {
    float c = cos(a);
    float s = sin(a);
    return vec2(c * p.x - s * p.y, s * p.x + c * p.y);
}

void main() {
    vec2 uv0 = v_uv * 2.0 - 1.0;
    uv0.x *= iResolution.x / max(iResolution.y, 1.0);

    // Background and foreground can rotate independently
    vec2 uv_bg = rot2d(uv0, iRotBg);
    vec2 uv = rot2d(uv0, iRotFg);

    float t = iTime * (0.35 + iSpeed * 0.75);

    // Heat-haze style world distortion.
    float melt = 0.10 + iBass * 0.24;
    uv.x += melt * sin(uv.y * 9.0 + t * 2.2);
    uv.y += melt * 0.5 * sin(uv.x * 7.0 - t * 1.8);

    // Surreal dripping blobs.
    float d1 = sdBlob(uv, vec2(-0.45, 0.05 + 0.15 * sin(t * 0.4)), 0.28, 0.06 + iBass * 0.05, t);
    float d2 = sdBlob(uv, vec2( 0.10, 0.15 + 0.12 * sin(t * 0.3 + 1.0)), 0.24, 0.05 + iBass * 0.04, t * 1.2);
    float d3 = sdBlob(uv, vec2( 0.55, -0.05 + 0.10 * sin(t * 0.5 + 2.0)), 0.20, 0.04 + iBass * 0.03, t * 1.4);

    float blobs = smoothstep(0.03, -0.03, min(min(d1, d2), d3));

    float bgN = noise(uv_bg * 3.0 + vec2(t * 0.12, -t * 0.07));
    vec3 bgA = vec3(0.18, 0.12, 0.08);
    vec3 bgB = vec3(0.45, 0.28, 0.15);
    vec3 bg = mix(bgA, bgB, bgN);

    // Slow color variation over time
    vec3 blobA = mix(vec3(0.82, 0.67, 0.38), vec3(0.88, 0.62, 0.32), 0.5 + 0.5 * sin(t * 0.22));
    vec3 blobB = mix(vec3(0.65, 0.16, 0.22), vec3(0.72, 0.12, 0.28), 0.5 + 0.5 * sin(t * 0.18));
    vec3 blobC = mix(vec3(0.90, 0.75, 0.50), vec3(0.85, 0.80, 0.45), 0.5 + 0.5 * sin(t * 0.15));
    float hueShift = 0.5 + 0.5 * sin(t * 0.6 + iMid * 3.0);
    vec3 blobCol = mix(blobA, blobB, hueShift);
    blobCol = mix(blobCol, blobC, iBeat * 0.5);

    vec3 col = mix(bg, blobCol, blobs);

    // Drip streaks
    float streak = smoothstep(0.95, 1.0, noise(vec2(uv.x * 15.0, uv.y * 2.0 + t * 0.8)));
    col += vec3(0.25, 0.1, 0.02) * streak * blobs * (0.5 + iBass * 0.8);

    // Beat pulse bloom
    col += vec3(0.18, 0.12, 0.08) * iBeat;

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""


class Dali(BaseEffect):
    NAME = "Dali"
    AUTHOR = "unicorn-viz"
    TAGS = ["art", "surreal", "audio"]
    SPEED_TIME_BIAS = 0.35
    SPEED_TIME_SCALE = 0.75
    PING_PONG_FRIENDS = ['Escher', 'Van Gogh', 'Psychedelic']

    def _init(self) -> None:
        self.parameters = {"speed": float(self.config.get("speed", 1.0))}
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()
        self._bass = 0.0
        self._mid = 0.0
        self._beat = 0.0
        self._rot_event_t = 0.0
        self._rot_event_dur = 0.0
        self._rot_bg_amp = 0.0
        self._rot_fg_amp = 0.0

    def _trigger_beat_rotation(self) -> None:
        """Trigger a rotation event on beat with randomized amplitude/duration."""
        primary_bg = bool(self.rng.integers(0, 2))  # Random: background or foreground leads
        amp = float(self.rng.uniform(0.10, 0.26))
        sign = -1.0 if bool(self.rng.integers(0, 2)) else 1.0
        if primary_bg:
            self._rot_bg_amp = sign * amp
            self._rot_fg_amp = -sign * amp * 0.9  # Counter-rotate foreground
        else:
            self._rot_fg_amp = sign * amp
            self._rot_bg_amp = -sign * amp * 0.9  # Counter-rotate background
        self._rot_event_t = 0.0
        self._rot_event_dur = float(self.rng.uniform(2.4, 3.8))

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass
        self._mid = audio.mid
        if audio.beat > 0.5:
            self._beat = 1.0
            # Beat occasionally triggers a rotation event (not every beat, just some)
            if float(self.rng.uniform(0.0, 1.0)) < 0.35:  # 35% chance per beat
                self._trigger_beat_rotation()
        self._beat = max(0.0, self._beat - dt * 2.8)

        # Advance rotation event if active
        if self._rot_event_t < self._rot_event_dur:
            self._rot_event_t += dt

    def _rotation_values(self) -> tuple[float, float]:
        if self._rot_event_t >= self._rot_event_dur:
            return 0.0, 0.0
        phase = self._rot_event_t / max(self._rot_event_dur, 1e-6)
        envelope = math.sin(phase * math.pi)
        return self._rot_bg_amp * envelope, self._rot_fg_amp * envelope

    def render(self) -> None:
        rot_bg, rot_fg = self._rotation_values()
        self._prog["iTime"].value = self.time
        self._prog["iResolution"].value = (float(self.width), float(self.height))
        self._prog["iBass"].value = self._bass
        self._prog["iMid"].value = self._mid
        self._prog["iBeat"].value = self._beat
        self._prog["iSpeed"].value = float(self.parameters["speed"])
        self._prog["iRotBg"].value = rot_bg
        self._prog["iRotFg"].value = rot_fg
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
