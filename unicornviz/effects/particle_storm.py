"""
Particle Storm 2.0 — GPU transform-feedback particle system.

Upgrades over 1.0:
  - 150 k particles (up from 100 k)
  - Per-particle permanent hue identity (7-float layout)
  - Two-octave curl noise; mid freq drives field complexity
  - Beat shockwave pushes every particle radially from centre
  - Three drifting emitter origins; random pick per spawn
  - Prismatic palette in the render shader (life + hue + time)
  - Star-shaped sprites: radial cross arms boosted by treble
  - Additive blend for full glow stack
"""
from __future__ import annotations

import math

import numpy as np
import moderngl

from unicornviz.effects.base import BaseEffect, AudioData

_NUM_PARTICLES = 150_000

# ── Transform-feedback update shader ──────────────────────────────────────
_UPDATE_VERT = """
#version 330
in  vec2  in_pos;
in  vec2  in_vel;
in  float in_life;
in  float in_seed;
in  float in_hue;

out vec2  out_pos;
out vec2  out_vel;
out float out_life;
out float out_seed;
out float out_hue;

uniform float dt;
uniform float iTime;
uniform float iBass;
uniform float iMid;
uniform float iBeat;
uniform vec2  iOrigin0;
uniform vec2  iOrigin1;
uniform vec2  iOrigin2;

float rng(float s) {
    return fract(sin(s * 127.1 + 91.3) * 43758.5453);
}

// Two-octave curl noise; mid drives second-octave amplitude.
vec2 curl(vec2 p, float t) {
    float e = 0.012;
    // Octave 1
    float nx0 = sin(p.x * 3.4 + sin(p.y * 2.1 + t));
    float nx1 = sin((p.x+e) * 3.4 + sin(p.y * 2.1 + t));
    float ny0 = sin(p.y * 2.9 + sin(p.x * 2.5 + t * 0.8));
    float ny1 = sin((p.y+e) * 2.9 + sin(p.x * 2.5 + t * 0.8));
    vec2 c1 = vec2((ny1-ny0)/e, -(nx1-nx0)/e);

    // Octave 2 — finer detail, driven by mid
    float nx2 = sin(p.x * 7.1 + sin(p.y * 5.3 + t * 1.3));
    float nx3 = sin((p.x+e) * 7.1 + sin(p.y * 5.3 + t * 1.3));
    float ny2 = sin(p.y * 6.5 + sin(p.x * 4.9 + t * 1.1));
    float ny3 = sin((p.y+e) * 6.5 + sin(p.x * 4.9 + t * 1.1));
    vec2 c2 = vec2((ny3-ny2)/e, -(nx3-nx2)/e);

    return (c1 * 0.28 + c2 * iMid * 0.14);
}

void main() {
    float life = in_life - dt;

    if (life <= 0.0) {
        // Pick one of three drifting origins by seed
        float pick = rng(in_seed + 5.5);
        vec2 origin = pick < 0.33 ? iOrigin0
                    : pick < 0.67 ? iOrigin1
                    :               iOrigin2;

        float angle = rng(in_seed) * 6.28318;
        float spd   = rng(in_seed + 1.3) * 0.6 + 0.15 + iBass * 0.7;
        float burst  = iBeat * 2.8;
        out_pos  = origin;
        out_vel  = vec2(cos(angle), sin(angle)) * (spd + burst);
        out_life = rng(in_seed + 2.7) * 2.8 + 0.5;
        out_seed = rng(in_seed + 99.9);
        out_hue  = rng(in_seed + 7.3);   // permanent colour identity
    } else {
        vec2 force = curl(in_pos * 0.7, iTime) * (1.0 + iBass * 2.0);
        force += vec2(0.0, 0.08);      // gentle upward drift
        force -= in_vel * 0.32;        // drag

        // Beat shockwave — radial push away from centre
        if (iBeat > 0.02) {
            vec2 dir = normalize(in_pos + 0.0001);
            force += dir * iBeat * 2.2;
        }

        out_vel  = in_vel + force * dt;
        out_pos  = in_pos + out_vel * dt;
        out_life = life;
        out_seed = in_seed;
        out_hue  = in_hue;
    }
}
"""

# ── Render shader — point sprites with star glow ──────────────────────────
_RENDER_VERT = """
#version 330
in  vec2  in_pos;
in  float in_life;
in  float in_hue;

uniform vec2  iResolution;
uniform float iTreble;
uniform float iBass;
uniform float iTime;

out float v_life;
out vec3  v_col;
out float v_treble;

vec3 palette(float t) {
    vec3 a = vec3(0.5, 0.5, 0.5);
    vec3 b = vec3(0.5, 0.5, 0.5);
    vec3 c = vec3(1.0, 0.85, 0.6);
    vec3 d = vec3(0.0, 0.18, 0.38);
    return a + b * cos(6.28318 * (c * t + d));
}

void main() {
    v_life   = in_life;
    v_treble = iTreble;

    gl_Position = vec4(in_pos, 0.0, 1.0);

    // Size: life-based + bass swell + treble sparkle tip boost
    float sz = (in_life * 2.2 + iBass * 5.5 + iTreble * 1.8) * (iResolution.y / 600.0);
    gl_PointSize = clamp(sz, 0.8, 12.0);

    // Prismatic colour: permanent hue identity + slow time drift + life fade
    float t = in_hue + iTime * 0.07 + (1.0 - clamp(in_life * 0.4, 0.0, 1.0)) * 0.25;
    v_col = palette(t);
}
"""

_RENDER_FRAG = """
#version 330
in  float v_life;
in  vec3  v_col;
in  float v_treble;
out vec4  fragColor;

void main() {
    vec2  uv = gl_PointCoord * 2.0 - 1.0;
    float r  = dot(uv, uv);
    if (r > 1.0) discard;

    // Soft circular core
    float core  = 1.0 - smoothstep(0.0, 1.0, r);

    // Star cross arms (boosted by treble)
    float arms  = (1.0 - smoothstep(0.0, 0.12, abs(uv.x))) *
                  (1.0 - smoothstep(0.5, 1.0, abs(uv.y)));
    arms       += (1.0 - smoothstep(0.0, 0.12, abs(uv.y))) *
                  (1.0 - smoothstep(0.5, 1.0, abs(uv.x)));
    arms = clamp(arms, 0.0, 1.0) * (0.3 + v_treble * 0.9);

    float alpha = (core + arms) * clamp(v_life, 0.0, 1.0);
    fragColor = vec4(v_col + v_col * arms * 0.6, alpha * 0.88);
}
"""


class ParticleStorm(BaseEffect):
    """150 k-particle GPU storm: curl-noise flow, beat shockwave, prismatic sparkles."""

    NAME   = "Particle Storm"
    AUTHOR = "unicorn-viz"
    TAGS   = ["futuristic", "audio", "particles"]
    PING_PONG_FRIENDS = ['Raymarcher', 'Crystal Pyramids', 'Tunnel']

    # 7 floats per particle: pos(2) vel(2) life(1) seed(1) hue(1)
    _STRIDE = 7 * 4
    _LAYOUT = "2f 2f 1f 1f 1f"
    _ATTRS  = ["in_pos", "in_vel", "in_life", "in_seed", "in_hue"]
    _VARY   = ["out_pos", "out_vel", "out_life", "out_seed", "out_hue"]

    def _init(self) -> None:
        self.parameters = {"speed": float(self.config.get("speed", 1.0))}
        self._bass   = 0.0
        self._mid    = 0.0
        self._treble = 0.0
        self._beat   = 0.0
        # Three drifting emitter origins
        self._o0 = (0.0, 0.0)
        self._o1 = (0.3, -0.2)
        self._o2 = (-0.3, 0.25)

        rng = self.rng
        N = _NUM_PARTICLES
        pos  = rng.uniform(-1.0,  1.0, (N, 2)).astype(np.float32)
        vel  = rng.uniform(-0.2,  0.2, (N, 2)).astype(np.float32)
        life = rng.uniform( 0.0,  2.8,  N     ).astype(np.float32)
        seed = rng.uniform( 0.0,  1.0,  N     ).astype(np.float32)
        hue  = rng.uniform( 0.0,  1.0,  N     ).astype(np.float32)
        data = np.hstack([pos, vel, life[:, None], seed[:, None], hue[:, None]]).astype(np.float32)

        self._vbo_a = self.ctx.buffer(data.tobytes())
        self._vbo_b = self.ctx.buffer(data.tobytes())

        self._update_prog = self.ctx.program(
            vertex_shader=_UPDATE_VERT,
            varyings=self._VARY,
        )
        self._render_prog = self.ctx.program(
            vertex_shader=_RENDER_VERT,
            fragment_shader=_RENDER_FRAG,
        )

        def make_update_vao(src: moderngl.Buffer) -> moderngl.VertexArray:
            return self.ctx.vertex_array(
                self._update_prog,
                [(src, self._LAYOUT, *self._ATTRS)],
            )

        def make_render_vao(src: moderngl.Buffer) -> moderngl.VertexArray:
            # pos(2f) | vel skip(2f) | life(1f) | seed skip(1f) | hue(1f)
            return self.ctx.vertex_array(
                self._render_prog,
                [(src, "2f 2x4 1f 1x4 1f", "in_pos", "in_life", "in_hue")],
            )

        self._update_vao_a = make_update_vao(self._vbo_a)
        self._update_vao_b = make_update_vao(self._vbo_b)
        self._render_vao_a = make_render_vao(self._vbo_a)
        self._render_vao_b = make_render_vao(self._vbo_b)
        self._ping = True

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass   = audio.bass_n
        self._mid    = audio.mid_n
        self._treble = audio.treble_n

        if audio.beat > 0.5:
            self._beat = 1.0
            # Randomise all three emitter origins on beat
            self._o0 = (float(self.rng.uniform(-0.55, 0.55)), float(self.rng.uniform(-0.45, 0.45)))
            self._o1 = (float(self.rng.uniform(-0.55, 0.55)), float(self.rng.uniform(-0.45, 0.45)))
            self._o2 = (float(self.rng.uniform(-0.55, 0.55)), float(self.rng.uniform(-0.45, 0.45)))
        self._beat = max(0.0, self._beat - dt * 3.0)

        # Drift emitters slowly between beats
        t = self.time * 0.18
        self._o0 = (math.sin(t) * 0.45, math.cos(t * 0.7) * 0.35) if audio.beat <= 0.5 else self._o0
        self._o1 = (math.cos(t * 1.1 + 2.1) * 0.5, math.sin(t * 0.9 + 1.0) * 0.4) if audio.beat <= 0.5 else self._o1
        self._o2 = (math.sin(t * 0.8 + 4.2) * 0.3, math.cos(t * 1.2 + 3.1) * 0.45) if audio.beat <= 0.5 else self._o2

        up = self._update_prog
        up["dt"].value      = dt * float(self.parameters["speed"])
        up["iTime"].value   = self.time
        up["iBass"].value   = self._bass
        up["iMid"].value    = self._mid
        up["iBeat"].value   = self._beat
        up["iOrigin0"].value = self._o0
        up["iOrigin1"].value = self._o1
        up["iOrigin2"].value = self._o2

        src_vao = self._update_vao_a if self._ping else self._update_vao_b
        dst_vbo = self._vbo_b        if self._ping else self._vbo_a
        src_vao.transform(dst_vbo, moderngl.POINTS, vertices=_NUM_PARTICLES)
        self._ping = not self._ping

    def render(self) -> None:
        self.ctx.enable(moderngl.BLEND | moderngl.PROGRAM_POINT_SIZE)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE

        rp = self._render_prog
        rp["iResolution"].value = (float(self.width), float(self.height))
        rp["iTreble"].value     = self._treble
        rp["iBass"].value       = self._bass
        rp["iTime"].value       = self.time

        render_vao = self._render_vao_b if self._ping else self._render_vao_a
        render_vao.render(moderngl.POINTS, vertices=_NUM_PARTICLES)

        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

    def destroy(self) -> None:
        for obj in [
            self._update_vao_a, self._update_vao_b,
            self._render_vao_a, self._render_vao_b,
            self._vbo_a, self._vbo_b,
            self._update_prog, self._render_prog,
        ]:
            obj.release()

