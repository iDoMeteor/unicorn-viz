"""
Unicorn Tears -- prismatic iridescent teardrops falling through a deep star-field.

Each tear is a signed-distance teardrop with full-spectrum iridescent fill,
chromatic-aberration edge glow, and embedded sparkle stars.

Audio reactivity:
  - bass    -> tear size pulse and fall-speed surge
  - treble  -> sparkle density and brightness
  - mid     -> hue-rotation speed
  - beat    -> all-screen prismatic flash + shake
"""
from __future__ import annotations

import math
from pathlib import Path

import moderngl
import numpy as np
from PIL import Image

from unicornviz.effects.base import BaseEffect, AudioData

_N = 7  # number of simultaneous tears

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
#define N 7

uniform vec2  iResolution;
uniform float iTime;
uniform float iBass;
uniform float iTreble;
uniform float iMid;
uniform float iBeat;
uniform float iShakeX;
uniform float iShakeY;
uniform float iHueShift;
uniform float iAvatarMix;
uniform sampler2D avatar_tex;
uniform float tearX[N];
uniform float tearY[N];
uniform float tearR[N];
uniform float tearHue[N];

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

// Teardrop SDF: pointed tip at origin, rounded belly above.
float sdTear(vec2 p, float r) {
    p /= r;
    p.y += 1.0;
    float a = atan(p.x, p.y);
    float s = length(p);
    float boundary = 0.62 + 0.38 * cos(a);
    return (s - boundary) * r;
}

// Full-spectrum iridescent cosine palette.
vec3 iriPalette(float t) {
    vec3 a = vec3(0.5, 0.5, 0.5);
    vec3 b = vec3(0.5, 0.5, 0.5);
    vec3 c = vec3(1.0, 1.0, 1.0);
    vec3 d = vec3(0.00, 0.33, 0.67);
    return a + b * cos(6.28318 * (c * t + d));
}

// 4-pointed sparkle intensity centred on p=0.
float sparkle(vec2 p, float size) {
    float r = length(p);
    if (r > size) return 0.0;
    float a  = atan(p.y, p.x);
    float rays = abs(sin(a * 4.0)) * abs(cos(a * 4.0));
    float core = max(0.0, 1.0 - r / size);
    return core * core * (0.5 + 0.8 * rays);
}

// Deep-space background: smooth organic twinkling stars + nebula wisps.
vec3 background(vec2 uv, float t, float bass) {
    // Organic smooth star field: use continuous Voronoi-like twinkling
    float stars = 0.0;
    for (int k = 0; k < 3; k++) {
        float scale = 25.0 + float(k) * 18.0;
        vec2 grid_pos = floor(uv * scale);
        vec2 local_pos = fract(uv * scale);
        
        // Find closest Voronoi seed in neighbourhood
        float min_dist = 2.0;
        float closest_h = 0.0;
        for (int dx = -1; dx <= 1; dx++) {
            for (int dy = -1; dy <= 1; dy++) {
                vec2 nb = grid_pos + vec2(float(dx), float(dy));
                float h = hash(nb + float(k) * 13.7);
                // Star probability: roughly 6-8% density per octave
                if (h > 0.92) {
                    vec2 seed_offset = vec2(hash(nb + 41.2), hash(nb + 71.9)) - 0.5;
                    vec2 seed = nb + seed_offset + 0.5;
                    float d = length(local_pos + grid_pos - seed);
                    if (d < min_dist) {
                        min_dist = d;
                        closest_h = h;
                    }
                }
            }
        }
        // Smooth twinkle: combines continuous position-based modulation with time
        if (min_dist < 0.12) {
            float pulse_freq = 1.8 + closest_h * 2.0;  // Vary pulse speed per star
            float twinkle = 0.5 + 0.5 * sin(t * pulse_freq + closest_h * 6.28318);
            twinkle = twinkle * twinkle;  // Brightness curve for more pulsing prominence
            twinkle *= smoothstep(0.12, 0.02, min_dist);
            // Subtle color tint: each star has a slight warm/cool shift
            float color_tint = 0.5 + 0.5 * cos(closest_h * 6.28318 + t * 0.3);
            stars += twinkle * (0.6 + 0.4 * color_tint);
        }
    }
    // Nebula wisps
    float nx = sin(uv.x * 4.1 + t * 0.08) * cos(uv.y * 3.7 - t * 0.06);
    float ny = cos(uv.x * 3.3 - t * 0.07) * sin(uv.y * 4.9 + t * 0.05);
    float nebula = 0.5 + 0.5 * (nx * 0.5 + ny * 0.5);
    vec3  nb = mix(vec3(0.04, 0.01, 0.10), vec3(0.10, 0.03, 0.22), nebula);
    nb += vec3(0.03, 0.01, 0.08) * bass;
    return nb + vec3(stars);
}

void main() {
    vec2 uv = v_uv;
    float ar = iResolution.x / max(iResolution.y, 1.0);
    uv.x *= ar;
    uv.y = 1.0 - uv.y;  // Flip vertically

    uv.x += iShakeX;
    uv.y -= iShakeY;  // Invert shake for consistency

    vec2 bg_uv = v_uv;
    bg_uv.x *= ar;
    bg_uv.y = 1.0 - bg_uv.y;  // Flip background too
    vec3 col = background(bg_uv, iTime, iBass);

    vec3 tearAcc = vec3(0.0);
    float alphaAcc = 0.0;

    for (int i = 0; i < N; i++) {
        float tx  = tearX[i] * ar;
        float ty  = tearY[i];
        float tr  = tearR[i] * (1.0 + iBass * 0.22);
        float hoff = tearHue[i] + iHueShift;

        vec2 tp = uv - vec2(tx, ty);

        // Chromatic aberration: R/G/B sampled at slight offsets
        float ca = tr * 0.025;
        float dR = sdTear(tp + vec2( ca, 0.0), tr);
        float dG = sdTear(tp,                  tr);
        float dB = sdTear(tp - vec2( ca, 0.0), tr);

        float fillR = smoothstep( 0.005, -0.005, dR);
        float fillG = smoothstep( 0.005, -0.005, dG);
        float fillB = smoothstep( 0.005, -0.005, dB);

        // Iridescent hue driven by position, distance from centre, and time
        float ang  = atan(tp.y, tp.x);
        float dn   = length(tp) / max(tr, 0.001);
        float hue  = hoff + dn * 0.55 + ang / 6.28318 + iTime * (0.18 + iMid * 0.28);

        vec3 iriR = iriPalette(hue - 0.02);
        vec3 iriG = iriPalette(hue);
        vec3 iriB = iriPalette(hue + 0.02);

        float glow = max(0.0, 1.0 - dn) ;
        glow *= glow;

        vec3 tc = vec3(
            iriR.r * fillR,
            iriG.g * fillG,
            iriB.b * fillB
        ) * (0.65 + 0.35 * glow);

        // Prismatic edge rim
        float rim = smoothstep(0.06, 0.0, abs(dG));
        tc += iriPalette(hue + 0.5) * rim * 0.65;

        // Embedded sparkle stars
        float sp = 0.0;
        for (int s = 0; s < 6; s++) {
            float sh  = hash1(float(i) * 17.3 + float(s) * 5.7);
            float sh2 = hash1(float(i) * 13.1 + float(s) * 7.3 + 0.3);
            float sh3 = hash1(float(i) * 11.7 + float(s) * 3.9 + 0.6);
            vec2  sc  = vec2(sh * 2.0 - 1.0, sh2 * 2.0 - 1.0) * tr * 0.75;
            float pulse = 0.4 + 0.6 * sin(iTime * (1.5 + sh3 * 2.0) + sh * 6.28318);
            sp += sparkle(tp - sc, tr * 0.20) * pulse * fillG;
        }
        sp += sparkle(tp, tr * 0.12) * iBeat;
        tc += iriPalette(hue * 1.4 + 0.25) * sp * (0.75 + iTreble * 0.7);

        // Optional avatar cameo: occasional, subtle, and tear-masked.
        // Never rendered as a square because it is multiplied by fill/rim masks.
        if (iAvatarMix > 0.001) {
            // Per-tear random gate + slow global time gate for occasional appearances.
            float tear_gate = step(0.62, hash1(float(i) * 9.17 + floor(iTime * 0.23)));
            float time_gate = smoothstep(0.78, 0.96,
                0.5 + 0.5 * sin(iTime * 0.7 + float(i) * 1.9)
            );
            float cameo = tear_gate * time_gate * iAvatarMix;

            // Map local tear space into avatar UV and gently bend with flow.
            vec2 auv = tp / (tr * 1.65);
            auv = vec2(auv.x * 0.62, auv.y * 0.78 + 0.12);
            auv = auv * 0.5 + 0.5;
            // Randomized cameo zoom:
            // 1.0 = old size (before recent scale-down),
            // 4.0 = twice as far out as current 2.0 scale.
            float zoom_scale = mix(
                1.0,
                4.0,
                hash1(float(i) * 31.7 + floor(iTime * 0.23) * 1.91)
            );
            auv = (auv - 0.5) * zoom_scale + 0.5;
            auv += vec2(sin(iTime * 1.3 + float(i)) * 0.012, cos(iTime * 1.1 + float(i)) * 0.010);

            // Keep only valid UV and strongly clamp into tear interior.
            float in_uv = step(0.0, auv.x) * step(0.0, auv.y) * step(auv.x, 1.0) * step(auv.y, 1.0);
            float in_tear = smoothstep(0.020, -0.030, dG);

            vec3 avatar_col = texture(avatar_tex, auv).rgb;
            // Match local palette so cameo feels integrated.
            avatar_col = mix(avatar_col, iriPalette(hue + 0.18), 0.22);
            tc = mix(tc, tc + avatar_col * 0.55, cameo * in_uv * in_tear);
        }

        tearAcc  += tc;
        alphaAcc += max(0.0, fillG) + rim * 0.25;
    }

    // Blend tears over background
    float blendA = clamp(alphaAcc, 0.0, 1.0);
    col = mix(col, tearAcc, blendA);
    col += tearAcc * 0.30;   // additive glow

    // Beat prismatic flash
    if (iBeat > 0.01) {
        vec3 flashCol = iriPalette(iHueShift + v_uv.x * 0.6 + v_uv.y * 0.4);
        col = mix(col, flashCol, iBeat * 0.42);
        col += flashCol * iBeat * 0.12;
    }

    // Filmic tone-map
    col = col / (col + 0.4) * 1.4;

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""


class UnicornTears(BaseEffect):
    """Prismatic iridescent teardrops falling through a deep star-field."""

    NAME   = "Unicorn Tears"
    AUTHOR = "unicorn-viz"
    TAGS   = ["psychedelic", "audio", "futuristic"]

    def _load_avatar_texture(self) -> tuple[moderngl.Texture, float]:
        """Load optional avatar texture used for occasional tear cameos."""
        candidates = [
            Path('drop-ins/unicorn-tears-01/images/unicorn-tears-avatar-01.png'),
            Path('images/unicorn-tears-avatar-01.png'),
        ]
        for path in candidates:
            if path.exists():
                img = Image.open(path).convert('RGB')
                w, h = img.size
                tex = self.ctx.texture((w, h), 3, data=img.tobytes())
                tex.filter = moderngl.LINEAR, moderngl.LINEAR
                tex.repeat_x = False
                tex.repeat_y = False
                return tex, 1.0

        # Fallback: 1x1 black texture and disabled mix.
        tex = self.ctx.texture((1, 1), 3, data=bytes([0, 0, 0]))
        tex.filter = moderngl.LINEAR, moderngl.LINEAR
        return tex, 0.0

    def _init(self) -> None:
        self.parameters = {"speed": 1.0}
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()
        self._avatar_tex, self._avatar_mix = self._load_avatar_texture()

        # Randomise every tear at startup
        self._tx    = self.rng.uniform(0.08, 0.92, _N).astype(float)
        self._ty    = self.rng.uniform(-0.2, 1.0,  _N).astype(float)
        self._tr    = self.rng.uniform(0.055, 0.13, _N).astype(float)
        self._spd   = self.rng.uniform(0.06,  0.17, _N).astype(float)
        self._sway_phase = self.rng.uniform(0.0, 6.28318, _N).astype(float)
        self._sway_amp   = self.rng.uniform(0.012, 0.045, _N).astype(float)
        self._hue        = self.rng.uniform(0.0, 1.0, _N).astype(float)

        self._bass    = 0.0
        self._treble  = 0.0
        self._mid     = 0.0
        self._beat    = 0.0
        self._shake_x = 0.0
        self._shake_y = 0.0
        self._hue_shift = 0.0
        self._burst_timer = 0.0
        self._burst_interval = 8.5  # Random burst every ~8-12 seconds

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass   = audio.bass
        self._treble = audio.treble
        self._mid    = audio.mid

        if audio.beat > 0.5:
            self._beat    = 1.0
            self._shake_x = float(self.rng.uniform(-0.014, 0.014))
            self._shake_y = float(self.rng.uniform(-0.009, 0.009))
        self._beat    = max(0.0, self._beat    - dt * 4.0)
        self._shake_x *= max(0.0, 1.0 - dt * 14.0)
        self._shake_y *= max(0.0, 1.0 - dt * 14.0)
        self._hue_shift = (self._hue_shift + dt * (0.06 + self._mid * 0.12)) % 1.0

        # Random drop burst mechanic
        self._burst_timer += dt
        should_burst = False
        if self._burst_timer >= self._burst_interval:
            self._burst_timer = 0.0
            self._burst_interval = float(self.rng.uniform(8.0, 12.0))
            should_burst = True

        spd = float(self.parameters["speed"])
        for i in range(_N):
            # Random drops: some tears spawn at top with high velocity when burst happens
            if should_burst and float(self.rng.uniform(0.0, 1.0)) < 0.35:
                self._ty[i]  = -0.05
                self._tx[i]  = float(self.rng.uniform(0.08, 0.92))
                self._spd[i] = float(self.rng.uniform(0.35, 0.50))  # Drop fast!
                # Reset speed after burst
                self._spd[i] *= 0.6  # Slow down burst after drop
            
            fall = self._spd[i] * spd * (1.0 + self._bass * 0.55) * dt
            self._ty[i] += fall
            self._tx[i] += (
                math.sin(self.time * 1.1 + self._sway_phase[i])
                * self._sway_amp[i] * dt * 2.5
            )
            # Respawn above screen when tear exits bottom
            if self._ty[i] > 1.14:
                self._ty[i]        = float(self.rng.uniform(-0.28, -0.04))
                self._tx[i]        = float(self.rng.uniform(0.08,  0.92))
                self._tr[i]        = float(self.rng.uniform(0.055, 0.13))
                self._spd[i]       = float(self.rng.uniform(0.06,  0.17))
                self._sway_amp[i]  = float(self.rng.uniform(0.012, 0.045))
                self._hue[i]       = float(self.rng.uniform(0.0,   1.0))

    def render(self) -> None:
        self._prog["iResolution"].value = (float(self.width), float(self.height))
        self._prog["iTime"].value       = self.time
        self._prog["iBass"].value       = self._bass
        self._prog["iTreble"].value     = self._treble
        self._prog["iMid"].value        = self._mid
        self._prog["iBeat"].value       = self._beat
        self._prog["iShakeX"].value     = float(self._shake_x)
        self._prog["iShakeY"].value     = float(self._shake_y)
        self._prog["iHueShift"].value   = float(self._hue_shift)
        self._prog["iAvatarMix"].value  = float(self._avatar_mix)
        self._avatar_tex.use(location=0)
        self._prog["avatar_tex"].value  = 0
        # moderngl 5.x accepts numpy arrays directly for GLSL float arrays.
        self._prog["tearX"].value   = self._tx
        self._prog["tearY"].value   = self._ty
        self._prog["tearR"].value   = self._tr
        self._prog["tearHue"].value = self._hue
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._avatar_tex.release()
        self._prog.release()
