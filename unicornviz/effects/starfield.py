"""
Starfield 2.0 — cinematic multi-layer star field with warp-speed mode.

Layers:
  - Deep nebula/aurora background drifting slowly over time
  - Three parallax star layers with organic twinkling and subtle color
  - Beat-triggered warp: chromatic-aberration streak trails radiating from centre
  - Bass drives star brightness swell; treble brightens sparkle tips;
    mid shifts nebula hue; beat fires the warp burst and fades over ~2s
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
uniform vec2  iResolution;
uniform float iWarp;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
uniform float iSpeed;
uniform vec2  iDrift;
uniform float iRoll;
uniform float iFlow;
uniform float iMicroBurst;

in  vec2 v_uv;
out vec4 fragColor;

float hash(vec2 p) {
    p = fract(p * vec2(127.1, 311.7));
    p += dot(p, p + 19.19);
    return fract(p.x * p.y);
}

float hash1(float v) {
    return fract(sin(v * 127.1 + 91.3) * 43758.5453);
}

// ── Nebula aurora background ───────────────────────────────────────────────
vec3 nebula(vec2 uv, float t) {
    float mid = iMid;
    float s1 = sin(uv.x * 2.1 + t * 0.07 + mid * 0.4) * cos(uv.y * 1.8 - t * 0.05);
    float s2 = cos(uv.x * 3.3 - t * 0.09) * sin(uv.y * 2.6 + t * 0.06 + mid * 0.3);
    float s3 = sin((uv.x + uv.y) * 2.4 + t * 0.04);
    float n = s1 * 0.45 + s2 * 0.35 + s3 * 0.20;
    n = n * 0.5 + 0.5;

    // Cool-to-warm hue shift driven by mid
    vec3 cold = vec3(0.03, 0.04, 0.14);
    vec3 warm = vec3(0.10, 0.03, 0.18);
    vec3 accent = vec3(0.04, 0.09, 0.20);
    vec3 col = mix(cold, warm, n + mid * 0.25);
    col = mix(col, accent, smoothstep(0.5, 0.85, n) * 0.55);
    return col * (0.8 + iBass * 0.35);
}

// ── Single parallax star layer ─────────────────────────────────────────────
vec3 starLayer(vec2 uv, float t, float scale, float speed, float density) {
    vec2 cell = floor(uv * scale);
    vec2 local = fract(uv * scale) - 0.5;

    float h = hash(cell);
    if (h > density) return vec3(0.0);

    // Jitter star within cell
    vec2 off = vec2(hash(cell + 7.3), hash(cell + 13.7)) - 0.5;
    off *= 0.65;
    vec2 sp = local - off;

    float r = length(sp);
    float sz = 0.008 + h * 0.012;

    // Organic twinkle: two sine frequencies per star
    float tw1 = sin(t * (1.4 + h * 1.8) + h * 6.28318);
    float tw2 = sin(t * (2.6 + h * 1.2) + h * 12.5664);
    float twinkle = 0.55 + 0.28 * tw1 + 0.17 * tw2;
    twinkle = max(0.0, twinkle);

    float core = smoothstep(sz, 0.0, r);
    float halo = smoothstep(sz * 3.5, sz * 0.8, r) * 0.18;
    float brightness = (core + halo) * twinkle * (0.7 + iBass * 0.45);

    // Subtle per-star colour from hash
    float hue = h;
    vec3 tint = 0.6 + 0.4 * cos(6.28318 * (vec3(hue, hue + 0.33, hue + 0.67)));
    tint = mix(vec3(0.85, 0.90, 1.0), tint, 0.28 + iTreble * 0.22);

    // Sparkle cross arms for large/bright stars
    float cross_arm = max(abs(sp.x), abs(sp.y));
    float cross_h   = smoothstep(sz * 2.2, 0.0, cross_arm) * (h > density * 0.85 ? 0.5 : 0.0);
    brightness += cross_h * twinkle * iTreble * 0.6;

    return tint * brightness;
}

// ── Warp streaks (beat-triggered) ─────────────────────────────────────────
vec3 warpStreaks(vec2 uv, float t, float warp) {
    if (warp < 0.01) return vec3(0.0);
    float angle = atan(uv.y, uv.x);
    float radius = length(uv);
    vec3 col = vec3(0.0);

    for (int i = 0; i < 180; i++) {
        float fi = float(i) / 180.0;
        float a = fi * 6.28318;
        float ha = hash(vec2(fi, 0.3));
        if (ha > 0.35) continue;   // sparse streaks

        float da = abs(mod(angle - a + 3.14159, 6.28318) - 3.14159);
        if (da > 0.018) continue;

        float len = 0.25 + ha * 0.55;
        float streak = smoothstep(len, 0.0, radius) * smoothstep(0.018, 0.002, da);

        // Chromatic split per streak
        float hb = hash(vec2(fi, 0.7));
        vec3 strkCol = 0.55 + 0.45 * cos(6.28318 * vec3(hb, hb + 0.33, hb + 0.67));
        col += strkCol * streak * warp * (0.6 + iBass * 0.55);
    }
    return col;
}

void main() {
    float ar = iResolution.x / iResolution.y;
    vec2 uv = v_uv * vec2(ar, 1.0);
    float t = iTime * iSpeed;

    // Starfield 2.5: long-run evolving camera drift + subtle roll.
    uv += iDrift;
    float c = cos(iRoll);
    float s = sin(iRoll);
    uv = vec2(c * uv.x - s * uv.y, s * uv.x + c * uv.y);

    // Flow modulation adds breathing dynamics over time.
    float flow = iFlow + iMicroBurst * 0.25;

    // Nebula background
    vec3 col = nebula(uv * (0.5 + flow * 0.08), t + flow * 0.7);

    // Three parallax star layers: deep / mid / near
    col += starLayer(uv + vec2(flow * 0.10, -flow * 0.06), t * (1.0 + flow * 0.12), 42.0, 0.12, 0.91 - flow * 0.02);
    col += starLayer(uv + vec2(0.17 - flow * 0.07, 0.09 + flow * 0.05), t * (1.4 + flow * 0.16), 72.0, 0.22, 0.88 - flow * 0.03);
    col += starLayer(uv + vec2(0.41 + flow * 0.04, -0.12 - flow * 0.06), t * (2.1 + flow * 0.20), 110.0, 0.38, 0.84 - flow * 0.04);

    // Warp streaks from beat
    col += warpStreaks(v_uv + iDrift * 0.5, t + flow * 0.4, iWarp + iMicroBurst * 0.2);

    // Warp centre flash
    if (iWarp > 0.01) {
        float cf = exp(-length(uv) * 2.2) * iWarp * 0.55;
        col += vec3(0.8, 0.7, 1.0) * cf;
    }

    // Subtle vignette
    col *= 1.0 - 0.18 * dot(v_uv, v_uv);

    // Filmic tone-map + gamma
    col = col / (col + 0.5);
    col = pow(clamp(col, 0.0, 1.0), vec3(0.4545));

    fragColor = vec4(col, 1.0);
}
"""


class Starfield(BaseEffect):
    """Cinematic multi-layer starfield with aurora nebula and beat-warp mode."""

    NAME   = "Starfield"
    AUTHOR = "unicorn-viz"
    TAGS   = ["classic", "audio", "futuristic"]

    def _init(self) -> None:
        self.parameters = {"speed": 0.5, "warp": 0.0}
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()
        self._bass    = 0.0
        self._mid     = 0.0
        self._treble  = 0.0
        self._beat_decay = 0.0
        self._micro_burst = 0.0

        # 2.5 dynamics: slow camera drift/roll and evolving flow targets.
        self._drift_x = float(self.rng.uniform(-0.04, 0.04))
        self._drift_y = float(self.rng.uniform(-0.03, 0.03))
        self._roll = float(self.rng.uniform(-0.04, 0.04))
        self._flow = float(self.rng.uniform(0.0, 1.0))

        self._target_drift_x = self._drift_x
        self._target_drift_y = self._drift_y
        self._target_roll = self._roll
        self._target_flow = self._flow
        self._retarget_timer = 0.0
        self._retarget_interval = float(self.rng.uniform(5.0, 10.0))

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass   = audio.bass
        self._mid    = audio.mid
        self._treble = audio.treble
        if audio.beat > 0.5:
            self._beat_decay = 1.0
            self._micro_burst = 1.0
        self._beat_decay = max(0.0, self._beat_decay - dt * 1.8)
        self._micro_burst = max(0.0, self._micro_burst - dt * 3.2)
        self.parameters["warp"] = self._beat_decay

        # Retarget dynamics every few seconds to avoid long static feel.
        self._retarget_timer += dt
        if self._retarget_timer >= self._retarget_interval:
            self._retarget_timer = 0.0
            self._retarget_interval = float(self.rng.uniform(5.0, 10.0))
            self._target_drift_x = float(self.rng.uniform(-0.09, 0.09))
            self._target_drift_y = float(self.rng.uniform(-0.07, 0.07))
            self._target_roll = float(self.rng.uniform(-0.14, 0.14))
            self._target_flow = float(self.rng.uniform(0.0, 1.0))

        # Smoothly approach targets.
        blend = min(1.0, dt * 0.35)
        self._drift_x += (self._target_drift_x - self._drift_x) * blend
        self._drift_y += (self._target_drift_y - self._drift_y) * blend
        self._roll += (self._target_roll - self._roll) * blend
        self._flow += (self._target_flow - self._flow) * blend

    def render(self) -> None:
        self._prog["iTime"].value       = self.time
        self._prog["iResolution"].value = (float(self.width), float(self.height))
        self._prog["iWarp"].value       = float(self.parameters["warp"])
        self._prog["iBass"].value       = self._bass
        self._prog["iMid"].value        = self._mid
        self._prog["iTreble"].value     = self._treble
        self._prog["iSpeed"].value      = float(self.parameters["speed"])
        self._prog["iDrift"].value      = (self._drift_x, self._drift_y)
        self._prog["iRoll"].value       = self._roll
        self._prog["iFlow"].value       = self._flow
        self._prog["iMicroBurst"].value = self._micro_burst
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
