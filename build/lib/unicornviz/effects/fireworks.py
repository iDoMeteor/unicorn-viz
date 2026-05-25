"""Fireworks — cinematic night-sky pyrotechnic display.

Visually distinct from Particle Storm / curl-noise effects:
  - Physics-only simulation: gravity + air drag, no flow field.
  - Six authentic burst patterns selected randomly per shell:
      0 chrysanthemum  — dense uniform sphere, single colour
      1 peony          — mixed white core + colour, softer
      2 willow         — upward-biased, heavy gravity droop trails
      3 ring           — equatorial flat ring with latitude spread
      4 crossette      — four compass-direction sub-bursts
      5 sparkle        — sparse, slow, oversized glitter stars
  - Ping-pong 16-bit half-float accumulation FBO for persistent
    glowing comet trails that fade naturally over ~30 frames.
  - Night-sky backdrop: vertical gradient, twinkling stars, warm
    city-glow horizon that pulses with bass.
  - Distinct phases per shell: rise (comet trail) → detonation
    (radial burst + screen flash) → arc-fall under gravity.
  - Beat drives detonation salvos; bass swells sizes and brightness.
"""
from __future__ import annotations

import math

import moderngl
import numpy as np

from unicornviz.effects.base import AudioData, BaseEffect

_N_SHELLS = 10
_N_SPARKS = 5_000
_N_TOTAL  = _N_SHELLS + _N_SPARKS
_N_BURST  = 6

# Particle vertex layout: x  y  life  hue  bright  size  kind
_STRIDE = 7
# ── Night sky background ────────────────────────────────────────────────────

_SKY_VERT = """
#version 330
in  vec2 in_vert;
out vec2 v_pos;
void main() {
    v_pos       = in_vert;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_SKY_FRAG = """
#version 330
uniform float iTime;
uniform float iBass;
uniform float iFlash;
in  vec2 v_pos;
out vec4 fragColor;

float hash(vec2 p) {
    p = fract(p * vec2(127.1, 311.7));
    p += dot(p, p + 19.19);
    return fract(p.x * p.y);
}

void main() {
    float y = v_pos.y * 0.5 + 0.5;
    vec3 sky = mix(vec3(0.0), vec3(0.005, 0.007, 0.028), y * y);

    // Warm city / crowd glow near the horizon
    float hz = exp(-max(0.0, v_pos.y + 0.90) * 6.5);
    sky += vec3(0.55, 0.18, 0.04) * hz * (0.30 + iBass * 0.22);

    // Twinkling stars
    vec2  scell  = floor(v_pos * 170.0);
    vec2  slocal = fract(v_pos * 170.0) - 0.5;
    float sh     = hash(scell);
    if (sh > 0.968) {
        vec2  soff = (vec2(hash(scell + 7.3), hash(scell + 13.1)) - 0.5) * 0.55;
        float sd   = length(slocal - soff);
        float sb   = smoothstep(0.07, 0.0, sd);
        float tw   = 0.55 + 0.45 * sin(iTime * (1.4 + sh * 2.5) + sh * 6.28318);
        sky += vec3(0.70, 0.80, 1.00) * sb * tw * smoothstep(0.0, 0.55, y) * 0.20;
    }

    // Detonation flash
    sky += vec3(0.65, 0.55, 0.38) * iFlash * smoothstep(0.0, 0.35, y);

    fragColor = vec4(sky, 1.0);
}
"""

# ── Persistence fade (ping-pong accumulation) ───────────────────────────────

_COPY_VERT = """
#version 330
in  vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv        = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_FADE_FRAG = """
#version 330
uniform sampler2D uTex;
uniform float     uFade;
in  vec2 v_uv;
out vec4 fragColor;
void main() {
    vec4 c    = texture(uTex, v_uv);
    fragColor = vec4(c.rgb * uFade, c.a * uFade);
}
"""

# ── Spark point sprites ──────────────────────────────────────────────────────

_SPARK_VERT = """
#version 330
in vec2  in_pos;
in float in_life;
in float in_hue;
in float in_bright;
in float in_size;
in float in_kind;

uniform vec2  iResolution;
uniform float iBass;
uniform float iTreble;

out float v_life;
out vec3  v_col;
out float v_kind;

// Full-saturation hue → RGB (S=1, V=1)
vec3 hue2rgb(float h) {
    vec3 p = abs(fract(h + vec3(0.0, 2.0/3.0, 1.0/3.0)) * 6.0 - 3.0);
    return clamp(p - 1.0, 0.0, 1.0);
}

void main() {
    if (in_life < 0.001) {
        gl_Position  = vec4(9.0, 9.0, 0.0, 1.0);
        gl_PointSize = 0.0;
        v_life = 0.0; v_col = vec3(0.0); v_kind = in_kind;
        return;
    }

    v_life = clamp(in_life, 0.0, 1.0);
    v_kind = in_kind;

    vec3 hcol = hue2rgb(in_hue) * in_bright;
    if (in_kind < 0.5) {
        // Rising shell only: brief warm glow at peak brightness, quickly colours.
        float sat = clamp((1.0 - v_life) * 3.5, 0.0, 1.0);
        v_col = mix(vec3(in_bright * 0.70), hcol, sat);
    } else {
        // Burst sparks: born at full hue, no white flare.
        v_col = hcol;
    }
    v_col *= (1.0 + iTreble * 0.12);

    gl_Position  = vec4(in_pos, 0.0, 1.0);
    float sz     = in_size * (iResolution.y / 900.0) * (0.72 + iBass * 0.55);
    gl_PointSize = clamp(sz, 0.5, 64.0);
}
"""

_SPARK_FRAG = """
#version 330
in  float v_life;
in  vec3  v_col;
in  float v_kind;
out vec4  fragColor;

void main() {
    vec2  uv   = gl_PointCoord * 2.0 - 1.0;
    float r    = dot(uv, uv);
    if (r > 1.0) discard;

    float life = v_life;
    float core = exp(-r * 2.6);
    float rim  = 1.0 - smoothstep(0.0, 1.0, r);
    vec3  col;
    float alpha;

    if (v_kind < 0.5) {
        // Rising shell — white-hot core, coloured rim.
        float body = core * 0.92 + rim * 0.25;
        col   = mix(v_col, vec3(1.12, 1.06, 0.96), core * 0.28);
        alpha = body * (0.35 + life * 0.65);
    } else {
        // Burst spark — vivid with cross-sparkle arms.
        float arms  = 0.0;
        arms += (1.0 - smoothstep(0.0, 0.07, abs(uv.x)))
              * (1.0 - smoothstep(0.0, 0.70, abs(uv.y)));
        arms += (1.0 - smoothstep(0.0, 0.07, abs(uv.y)))
              * (1.0 - smoothstep(0.0, 0.70, abs(uv.x)));
        arms  = clamp(arms, 0.0, 1.0);
        float body  = core * 0.70 + rim * 0.25 + arms * 0.65;
        col   = v_col;
        alpha = body * life;
    }

    // Slight HDR overbright for glow bloom in the accumulation FBO.
    fragColor = vec4(col, alpha);
}
"""


class Fireworks(BaseEffect):
    """Cinematic fireworks with persistence trails and six burst patterns.

    Rendering pipeline each frame:
      1. Fade-copy previous accumulation FBO → write FBO (comet trails).
      2. Additively render new particles → write FBO.
      3. Restore caller FBO; draw night-sky background.
      4. Additively composite write FBO (sparks) over background.
    """

    NAME   = "Fireworks"
    AUTHOR = "unicorn-viz"
    TAGS   = ["classic", "audio", "particles", "celebration"]
    PING_PONG_FRIENDS = ['Starfield', 'Cosmos', 'Plasma']

    def _init(self) -> None:
        self.candy_frame_disallow = bool(self.config.get('candy_frame_disallow', True))
        self.scale_when_framed = bool(self.config.get('scale_when_framed', False))
        self.parameters = {
            'speed':      float(self.config.get('speed', 1.0)),
            'burst_rate': float(self.rng.uniform(0.85, 1.35)),
            'trail_fade': 0.87,
        }

        # ── GL programs ──────────────────────────────────────────────────────
        self._sky_prog   = self._make_program(_SKY_VERT,   _SKY_FRAG)
        self._fade_prog  = self._make_program(_COPY_VERT,  _FADE_FRAG)
        self._spark_prog = self._make_program(_SPARK_VERT, _SPARK_FRAG)

        # Shared fullscreen quad VBO — reused by all three quad programs.
        verts = np.array([-1, -1, -1, 1, 1, -1, 1, 1], dtype=np.float32)
        self._quad_vbo = self.ctx.buffer(verts)
        self._sky_vao  = self.ctx.vertex_array(
            self._sky_prog,  [(self._quad_vbo, '2f', 'in_vert')])
        self._fade_vao = self.ctx.vertex_array(
            self._fade_prog, [(self._quad_vbo, '2f', 'in_vert')])

        # Particle VBO/VAO  (7 floats: x y life hue bright size kind)
        self._render_buf = np.zeros((_N_TOTAL, _STRIDE), dtype=np.float32)
        self._spark_vbo  = self.ctx.buffer(self._render_buf)
        self._spark_vao  = self.ctx.vertex_array(
            self._spark_prog,
            [(self._spark_vbo, '2f 1f 1f 1f 1f 1f',
              'in_pos', 'in_life', 'in_hue', 'in_bright', 'in_size', 'in_kind')],
        )

        # Ping-pong 16-bit half-float accumulation FBOs for persistent trails.
        self._fbo_a, self._tex_a = self._make_acc(self.width, self.height)
        self._fbo_b, self._tex_b = self._make_acc(self.width, self.height)
        self._ping = True   # True → read A write B

        # ── Shell simulation ─────────────────────────────────────────────────
        rng = self.rng
        self._sh_pos    = np.zeros((_N_SHELLS, 2), dtype=np.float32)
        self._sh_vel    = np.zeros((_N_SHELLS, 2), dtype=np.float32)
        self._sh_life   = np.zeros(_N_SHELLS, dtype=np.float32)
        self._sh_hue    = rng.uniform(0.0, 1.0, _N_SHELLS).astype(np.float32)
        self._sh_hue2   = ((self._sh_hue + rng.uniform(0.15, 0.45, _N_SHELLS)) % 1.0).astype(np.float32)
        self._sh_size   = rng.uniform(12.0, 22.0, _N_SHELLS).astype(np.float32)
        self._sh_active = np.zeros(_N_SHELLS, dtype=bool)
        self._sh_delay  = rng.uniform(0.0, 2.5, _N_SHELLS).astype(np.float32)
        self._sh_x      = rng.uniform(-0.82, 0.82, _N_SHELLS).astype(np.float32)
        self._sh_spd    = rng.uniform(2.2, 3.6, _N_SHELLS).astype(np.float32)
        self._sh_wind   = rng.uniform(-0.12, 0.12, _N_SHELLS).astype(np.float32)
        self._sh_peak_y = rng.uniform(0.05, 0.70, _N_SHELLS).astype(np.float32)
        self._sh_burst  = rng.integers(0, _N_BURST, _N_SHELLS)

        # ── Spark pool ───────────────────────────────────────────────────────
        self._sp_pos    = np.zeros((_N_SPARKS, 2), dtype=np.float32)
        self._sp_vel    = np.zeros((_N_SPARKS, 2), dtype=np.float32)
        self._sp_life   = np.zeros(_N_SPARKS,      dtype=np.float32)
        self._sp_hue    = np.zeros(_N_SPARKS,      dtype=np.float32)
        self._sp_bright = np.zeros(_N_SPARKS,      dtype=np.float32)
        self._sp_size   = np.zeros(_N_SPARKS,      dtype=np.float32)
        self._sp_active = np.zeros(_N_SPARKS,      dtype=bool)
        self._sp_cursor = 0

        # ── Audio / state ────────────────────────────────────────────────────
        self._bass    = 0.0
        self._treble  = 0.0
        self._beat    = 0.0
        self._flash    = 0.0
        self._flash_cd = 0.0   # seconds until next sky-flash is allowed
        self._pal_off  = float(rng.uniform(0.0, 1.0))
        self._salvo_t  = float(rng.uniform(0.4, 1.6))

    # ── GL helpers ────────────────────────────────────────────────────────────

    def _make_acc(self, w: int, h: int) -> tuple[moderngl.Framebuffer, moderngl.Texture]:
        tex = self.ctx.texture((w, h), 4, dtype='f2')
        tex.filter = moderngl.LINEAR, moderngl.LINEAR
        fbo = self.ctx.framebuffer(color_attachments=[tex])
        fbo.clear(0.0, 0.0, 0.0, 0.0)
        return fbo, tex

    # ── Shell helpers ─────────────────────────────────────────────────────────

    def _launch(self, i: int) -> None:
        rng = self.rng
        self._sh_active[i] = True
        self._sh_pos[i]    = [self._sh_x[i], -1.05]
        spd = self._sh_spd[i] * (1.0 + self._bass * 0.20 + self._beat * 0.10)
        self._sh_vel[i]    = [
            self._sh_wind[i] * 0.25 + float(rng.uniform(-0.06, 0.06)),
            spd,
        ]
        self._sh_life[i]   = float(rng.uniform(0.80, 1.30))
        self._sh_hue[i]    = float(rng.uniform(0.0, 1.0))
        self._sh_hue2[i]   = float((self._sh_hue[i] + rng.uniform(0.12, 0.45)) % 1.0)
        self._sh_size[i]   = float(rng.uniform(12.0, 22.0))
        self._sh_peak_y[i] = float(rng.uniform(0.05, 0.72))
        self._sh_burst[i]  = int(rng.integers(0, _N_BURST))

    def _detonate(self, i: int) -> None:
        center = self._sh_pos[i].copy()
        power  = 0.55 + self._bass * 0.55 + self._beat * 0.40
        self._burst(center, float(self._sh_hue[i]), float(self._sh_hue2[i]),
                    int(self._sh_burst[i]), power)
        self._sh_active[i] = False
        self._sh_delay[i]  = float(
            self.rng.uniform(0.4, 2.2) / max(0.4, float(self.parameters['burst_rate']))
        )
        # Flash fires only if the cooldown has expired and a rare rng roll passes
        # (≈15% per detonation, minimum ~10 s gap) so flares are occasional, not constant.
        if self._flash_cd <= 0.0 and float(self.rng.uniform()) < 0.15:
            self._flash    = min(1.0, self._flash + 0.75)
            self._flash_cd = float(self.rng.uniform(10.0, 20.0))

    # ── Burst factory ─────────────────────────────────────────────────────────

    def _burst(self, center: np.ndarray, hue: float, hue2: float,
               btype: int, power: float) -> None:
        rng = self.rng
        p   = power

        if btype == 0:
            # Chrysanthemum — dense uniform sphere, single hue.
            n   = int(280 + p * 90)
            ang = rng.uniform(0.0, math.tau, n)
            spd = (np.abs(rng.normal(1.6, 0.30, n)) * (0.75 + p * 0.55)).astype(np.float32)
            h   = np.full(n, hue, dtype=np.float32)
            sz  = rng.uniform(6.0, 13.0, n).astype(np.float32)
            br  = rng.uniform(0.65, 0.95, n).astype(np.float32)
            vel = (np.column_stack((np.cos(ang), np.sin(ang))) * spd[:, None]).astype(np.float32)

        elif btype == 1:
            # Peony — mixed white-core + colour.
            n   = int(240 + p * 70)
            ang = rng.uniform(0.0, math.tau, n)
            spd = (np.abs(rng.normal(1.3, 0.35, n)) * (0.75 + p * 0.55)).astype(np.float32)
            h   = np.where(rng.uniform(size=n) < 0.25, 0.0, np.full(n, hue)).astype(np.float32)
            sz  = rng.uniform(6.0, 14.0, n).astype(np.float32)
            br  = rng.uniform(0.70, 1.00, n).astype(np.float32)
            vel = (np.column_stack((np.cos(ang), np.sin(ang))) * spd[:, None]).astype(np.float32)

        elif btype == 2:
            # Willow — upward-biased, droop under heavy gravity.
            n   = int(200 + p * 60)
            ang = rng.uniform(0.0, math.tau, n)
            spd = (np.abs(rng.normal(1.2, 0.40, n)) * (0.70 + p * 0.50)).astype(np.float32)
            base = np.column_stack((np.cos(ang), np.sin(ang))).astype(np.float32)
            base[:, 1] += 0.65
            h   = ((np.full(n, hue) + rng.uniform(-0.04, 0.04, n)) % 1.0).astype(np.float32)
            sz  = rng.uniform(5.0, 11.0, n).astype(np.float32)
            br  = rng.uniform(0.60, 0.90, n).astype(np.float32)
            self._emit(center, h, sz, br, (base * spd[:, None]).astype(np.float32))
            return

        elif btype == 3:
            # Ring — flat equatorial band.
            n   = int(160 + p * 50)
            ra  = np.linspace(0.0, math.tau, n, endpoint=False, dtype=np.float32)
            sp  = rng.normal(0.0, 0.12, n).astype(np.float32)
            spd = rng.uniform(1.5, 2.1, n).astype(np.float32) * (0.75 + p * 0.50)
            vel = (np.column_stack((np.cos(ra + sp), np.sin(ra + sp))) * spd[:, None]).astype(np.float32)
            h   = np.full(n, hue, dtype=np.float32)
            sz  = rng.uniform(5.0, 10.0, n).astype(np.float32)
            br  = rng.uniform(0.65, 0.90, n).astype(np.float32)
            self._emit(center, h, sz, br, vel)
            return

        elif btype == 4:
            # Crossette — four compass-direction sub-bursts.
            for da in (0.0, math.pi * 0.5, math.pi, math.pi * 1.5):
                sn  = int(65 + p * 22)
                a   = da + rng.uniform(-0.50, 0.50, sn)
                spd = rng.uniform(1.0, 2.2, sn).astype(np.float32) * (0.70 + p * 0.45)
                vel = (np.column_stack((np.cos(a), np.sin(a))) * spd[:, None]).astype(np.float32)
                h   = np.full(sn, hue2, dtype=np.float32)
                sz  = rng.uniform(4.5, 9.0, sn).astype(np.float32)
                br  = rng.uniform(0.65, 0.90, sn).astype(np.float32)
                self._emit(center, h, sz, br, vel)
            return

        else:
            # Sparkle — sparse, slow, oversized two-tone glitter.
            n   = int(90 + p * 35)
            ang = rng.uniform(0.0, math.tau, n)
            spd = rng.uniform(0.35, 1.05, n).astype(np.float32) * (0.60 + p * 0.50)
            h   = np.where(rng.uniform(size=n) < 0.5,
                           np.full(n, hue), np.full(n, hue2)).astype(np.float32)
            sz  = rng.uniform(10.0, 22.0, n).astype(np.float32)
            br  = rng.uniform(0.80, 1.10, n).astype(np.float32)
            vel = (np.column_stack((np.cos(ang), np.sin(ang))) * spd[:, None]).astype(np.float32)

        self._emit(center, h, sz, br, vel)

    def _emit(self, center: np.ndarray, hues: np.ndarray, sizes: np.ndarray,
              brights: np.ndarray, vel: np.ndarray) -> None:
        n = min(len(hues), _N_SPARKS)
        for i in range(n):
            idx = (self._sp_cursor + i) % _N_SPARKS
            self._sp_active[idx] = True
            self._sp_pos[idx]    = center
            self._sp_vel[idx]    = vel[i]
            self._sp_life[idx]   = 1.0
            self._sp_hue[idx]    = float(hues[i])
            self._sp_bright[idx] = float(brights[i])
            self._sp_size[idx]   = float(sizes[i])
        self._sp_cursor = (self._sp_cursor + n) % _N_SPARKS

    # ── Simulation update ─────────────────────────────────────────────────────

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        spd  = float(self.parameters['speed'])
        rate = max(0.3, float(self.parameters['burst_rate']))
        self._bass   = float(audio.bass_n)
        self._treble = float(audio.treble_n)

        if audio.beat > 0.5:
            self._beat  = 1.0
            # Beat flash: 35% chance, same cooldown gate as detonation flashes.
            if self._flash_cd <= 0.0 and float(self.rng.uniform()) < 0.35:
                self._flash    = min(1.0, self._flash + 0.70)
                self._flash_cd = float(self.rng.uniform(10.0, 20.0))
            choices = self.rng.choice(_N_SHELLS, size=min(4, _N_SHELLS), replace=False)
            for idx in np.atleast_1d(choices):
                self._sh_delay[int(idx)] = 0.0
        self._beat = max(0.0, self._beat - dt * 3.5)

        # Ambient cadence.
        self._salvo_t -= dt * spd * (0.65 + self._bass * 0.35 + rate * 0.20)
        if self._salvo_t <= 0.0:
            self._salvo_t = float(self.rng.uniform(0.7, 2.0) / rate)
            n_fire = int(self.rng.integers(1, 4))
            choices = self.rng.choice(_N_SHELLS, size=min(n_fire, _N_SHELLS), replace=False)
            for idx in np.atleast_1d(choices):
                self._sh_delay[int(idx)] = 0.0

        # Shells.
        gravity = 2.4 + self._bass * 0.45
        for i in range(_N_SHELLS):
            if not self._sh_active[i]:
                self._sh_delay[i] -= dt * spd
                if self._sh_delay[i] <= 0.0:
                    self._launch(i)
                continue
            self._sh_pos[i]    += self._sh_vel[i] * (dt * spd)
            self._sh_vel[i, 1] -= gravity * dt
            self._sh_life[i]   -= dt * spd
            if (
                self._sh_life[i] <= 0.0
                or self._sh_pos[i, 1] >= self._sh_peak_y[i]
                or self._sh_vel[i, 1] < 0.0
            ):
                self._detonate(i)

        # Sparks — vectorised physics.
        active = self._sp_active & (self._sp_life > 0.0)
        if np.any(active):
            self._sp_pos[active]    += self._sp_vel[active] * (dt * spd)
            self._sp_vel[active, 1] -= (1.65 + self._bass * 0.35) * dt
            self._sp_vel[active]    *= max(0.0, 1.0 - 0.06 * dt)
            self._sp_life[active]   -= dt * spd * 0.34
            self._sp_active &= self._sp_life > 0.0

        self._flash    = max(0.0, self._flash - dt * 2.0)
        self._flash_cd = max(0.0, self._flash_cd - dt)
        self._pal_off  = (self._pal_off + dt * 0.04) % 1.0
        self._pack()

    def _pack(self) -> None:
        buf = self._render_buf
        buf.fill(0.0)
        for i in range(_N_SHELLS):
            if self._sh_active[i]:
                buf[i, 0:2] = self._sh_pos[i]
                buf[i, 2]   = max(0.0, min(1.0, self._sh_life[i]))
                buf[i, 3]   = self._sh_hue[i]
                buf[i, 4]   = 0.85
                buf[i, 5]   = self._sh_size[i]
                buf[i, 6]   = 0.0   # kind = shell
        base = _N_SHELLS
        buf[base:, 0:2] = self._sp_pos
        buf[base:, 2]   = np.clip(self._sp_life, 0.0, 1.0)
        buf[base:, 3]   = (self._sp_hue + self._pal_off) % 1.0
        buf[base:, 4]   = self._sp_bright
        buf[base:, 5]   = self._sp_size
        buf[base:, 6]   = 1.0   # kind = spark
        buf[base:, 2][~self._sp_active] = 0.0  # dead sparks → off-screen via vert shader

    # ── Render ────────────────────────────────────────────────────────────────

    def render(self) -> None:
        caller_fbo = self.ctx.fbo   # save app's FBO to restore after internal passes
        w, h  = self.width, self.height
        fade  = float(self.parameters['trail_fade'])

        read_fbo,  read_tex  = (self._fbo_a, self._tex_a) if self._ping else (self._fbo_b, self._tex_b)
        write_fbo, write_tex = (self._fbo_b, self._tex_b) if self._ping else (self._fbo_a, self._tex_a)
        self._ping = not self._ping

        # 1. Fade-copy prev accumulation → write_fbo (comet trail persistence).
        write_fbo.use()
        self.ctx.viewport = (0, 0, w, h)
        self.ctx.clear(0.0, 0.0, 0.0, 0.0)
        read_tex.use(location=0)
        self._fade_prog['uTex'].value  = 0
        self._fade_prog['uFade'].value = fade
        self._fade_vao.render(moderngl.TRIANGLE_STRIP)

        # 2. Additively render new particles into write_fbo.
        self.ctx.enable(moderngl.BLEND | moderngl.PROGRAM_POINT_SIZE)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE
        self._spark_prog['iResolution'].value = (float(w), float(h))
        self._spark_prog['iBass'].value        = self._bass
        self._spark_prog['iTreble'].value      = self._treble
        self._spark_vbo.write(self._render_buf)
        self._spark_vao.render(moderngl.POINTS, vertices=_N_TOTAL)
        self.ctx.disable(moderngl.BLEND)
        self.ctx.disable(moderngl.PROGRAM_POINT_SIZE)

        # 3. Restore app FBO; draw night-sky background.
        caller_fbo.use()
        self.ctx.viewport = (0, 0, w, h)
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)
        self._sky_prog['iTime'].value  = self.time
        self._sky_prog['iBass'].value  = self._bass
        self._sky_prog['iFlash'].value = self._flash
        self._sky_vao.render(moderngl.TRIANGLE_STRIP)

        # 4. Additively composite spark accumulation over the sky.
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = moderngl.ONE, moderngl.ONE
        write_tex.use(location=0)
        self._fade_prog['uTex'].value  = 0
        self._fade_prog['uFade'].value = 1.0
        self._fade_vao.render(moderngl.TRIANGLE_STRIP)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.ctx.disable(moderngl.BLEND)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)
        for fbo, tex in [(self._fbo_a, self._tex_a), (self._fbo_b, self._tex_b)]:
            fbo.release()
            tex.release()
        self._fbo_a, self._tex_a = self._make_acc(width, height)
        self._fbo_b, self._tex_b = self._make_acc(width, height)

    def destroy(self) -> None:
        for obj in [
            self._sky_vao, self._fade_vao,
            self._spark_vao, self._spark_vbo,
            self._quad_vbo,
            self._fbo_a, self._tex_a,
            self._fbo_b, self._tex_b,
            self._sky_prog, self._fade_prog, self._spark_prog,
        ]:
            obj.release()

