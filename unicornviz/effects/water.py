"""
Water — GPU ping-pong 2D wave equation simulation.

Two height-field buffers alternate each frame.  A "simulate" shader
solves the discrete wave equation (with damping); a "render" shader
computes screen-space normals → Phong + fake refraction + caustics.

Audio reactivity:
  - bass   → wave amplitude (big splashes from bottom)
  - beat   → point-source raindrop at a random position
  - mid    → continuous surface ripple turbulence
  - treble → extra shimmer in the specular highlight
"""
from __future__ import annotations

import math
import random
import numpy as np
import moderngl

from unicornviz.effects.base import BaseEffect, AudioData

_SIM_W = 480
_SIM_H = 270

# ---------------------------------------------------------------------------
# Shaders
# ---------------------------------------------------------------------------

_VERT = """
#version 330
in  vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv        = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

# Wave equation step shader
# prev  = height[t-1], curr = height[t]  →  next = height[t+1]
_SIM_FRAG = """
#version 330
uniform sampler2D prev;
uniform sampler2D curr;
uniform vec2      iResolution;
uniform float     iBass;
uniform float     iMid;
uniform float     iTime;
uniform float     iEnergy;
// Raindrop
uniform vec2  iDrop;     // UV position; (−1,−1) = no drop this frame
uniform float iDropAmt;

out vec4 fragColor;
in  vec2 v_uv;

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

void main() {
    vec2 px = 1.0 / iResolution;

    float c  = texture(curr, v_uv).r;
    float p  = texture(prev, v_uv).r;
    float n  = texture(curr, v_uv + vec2(0.0,  px.y)).r;
    float s  = texture(curr, v_uv + vec2(0.0, -px.y)).r;
    float e  = texture(curr, v_uv + vec2( px.x, 0.0)).r;
    float w  = texture(curr, v_uv + vec2(-px.x, 0.0)).r;

    // Wave equation with damping
    float speed   = 0.49 + iBass * 0.04 + iEnergy * 0.03;
    float damping = 0.992 - iMid * 0.004 - iEnergy * 0.003;
    float next = ((n + s + e + w) * speed - p) * damping;

    // Continuous turbulence driven by mid/bass
    float noise = hash(v_uv * 73.1 + iTime * 0.7) - 0.5;
    next += noise * iMid * 0.012;

    // Raindrop injection
    if (iDrop.x >= 0.0) {
        float d = length(v_uv - iDrop) * min(iResolution.x, iResolution.y);
        if (d < 4.0) {
            next += iDropAmt * (1.0 - d / 4.0);
        }
    }

    // High-energy density injection: synthetic micro-drops during intense parts.
    if (iEnergy > 0.35) {
        float min_res = min(iResolution.x, iResolution.y);
        for (int k = 0; k < 3; k++) {
            float fk = float(k);
            vec2 rp = vec2(
                hash(vec2(iTime * (0.73 + fk * 0.21), fk + 11.3)),
                hash(vec2(iTime * (0.59 + fk * 0.17), fk + 23.7))
            );
            float d = length(v_uv - rp) * min_res;
            float r = mix(2.0, 5.5, iEnergy);
            next += smoothstep(r, 0.0, d) * iEnergy * 0.10;
        }
    }

    fragColor = vec4(clamp(next, -1.0, 1.0), 0.0, 0.0, 1.0);
}
"""

# Display: height-field → normal → Phong + caustics
_DISPLAY_FRAG = """
#version 330
uniform sampler2D height;
uniform float     iBass;
uniform float     iBeat;
uniform float     iTreble;
uniform float     iTime;

in  vec2 v_uv;
out vec4 fragColor;

// Deep ocean colour palette
vec3 waterColor(float h, float spec) {
    // Base: dark blue-green → teal → sky at peaks
    vec3 deep    = vec3(0.02, 0.08, 0.25);
    vec3 mid_col = vec3(0.04, 0.32, 0.55);
    vec3 shallow = vec3(0.10, 0.72, 0.85);
    vec3 foam    = vec3(0.85, 0.95, 1.00);

    float t = clamp(h * 3.0 + 0.5, 0.0, 1.0);
    vec3 base;
    if (t < 0.33)      base = mix(deep,    mid_col, t * 3.0);
    else if (t < 0.67) base = mix(mid_col, shallow, (t - 0.33) * 3.0);
    else               base = mix(shallow, foam,    (t - 0.67) * 3.0);

    return base + spec * vec3(0.9, 0.97, 1.0) * (0.7 + iTreble * 0.5);
}

void main() {
    vec2 px = vec2(1.0 / 480.0, 1.0 / 270.0);

    float hC = texture(height, v_uv).r;
    float hR = texture(height, v_uv + vec2(px.x, 0.0)).r;
    float hU = texture(height, v_uv + vec2(0.0, px.y)).r;

    // Reconstruct normal from height gradient
    vec3 N = normalize(vec3(hC - hR, hC - hU, 0.02));

    // View and light direction (static sky light from upper-right)
    vec3 L = normalize(vec3(0.5, 0.7, 1.0));
    vec3 V = vec3(0.0, 0.0, 1.0);
    vec3 H = normalize(L + V);

    float diff = max(dot(N, L), 0.0);
    float spec = pow(max(dot(N, H), 0.0), 64.0 + iTreble * 32.0);

    vec3 col = waterColor(hC, spec);
    col *= (0.6 + 0.4 * diff);

    // Fake caustic shimmer
    float caus = abs(sin(hC * 18.0 + iTime * 1.5)) * 0.12 * (iBass + 0.3);
    col += vec3(0.2, 0.7, 1.0) * caus;

    col += iBeat * 0.2 * vec3(0.4, 0.8, 1.0);

    fragColor = vec4(clamp(col, 0.0, 1.5), 1.0);
}
"""


class Water(BaseEffect):
    """GPU ping-pong wave equation — rippling ocean with caustics."""

    NAME = "Water"
    AUTHOR = "unicorn-viz"
    TAGS = ["simulation", "audio", "gpu"]
    PING_PONG_FRIENDS = ['Fire', 'Wavey Gravy', 'Metaballs']

    def _init(self) -> None:
        self.parameters = {"amplitude": 1.0, "speed": float(self.config.get("speed", 1.0))}

        self._sim_prog  = self._make_program(_VERT, _SIM_FRAG)
        self._disp_prog = self._make_program(_VERT, _DISPLAY_FRAG)
        self._sim_vao, self._vbo = self._fullscreen_quad(self._sim_prog)
        self._disp_vao = self.ctx.vertex_array(
            self._disp_prog,
            [(self._vbo, "2f", "in_vert")],
        )

        def _make_fbo() -> tuple[moderngl.Framebuffer, moderngl.Texture]:
            tex = self.ctx.texture((_SIM_W, _SIM_H), 4, dtype="f4")
            tex.filter = moderngl.LINEAR, moderngl.LINEAR
            tex.repeat_x = True
            tex.repeat_y = True
            fbo = self.ctx.framebuffer(color_attachments=[tex])
            fbo.clear(0.0, 0.0, 0.0, 1.0)
            return fbo, tex

        self._fbos = [_make_fbo() for _ in range(3)]
        self._step_idx = 0   # which FBO is "next" to write into

        self._bass   = 0.0
        self._mid    = 0.0
        self._treble = 0.0
        self._beat   = 0.0
        self._drop   = (-1.0, -1.0)
        self._drop_amt = 0.0
        self._energy = 0.0

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        amp = float(self.parameters["amplitude"])
        self._bass   = audio.bass   * amp
        self._mid    = audio.mid    * amp
        self._treble = audio.treble * amp
        self._energy = min(1.0, 0.55 * self._bass + 0.35 * self._mid + 0.20 * self._treble)

        if audio.beat > 0.5:
            self._beat = 1.0
            self._drop = (random.random(), random.random())
            self._drop_amt = 0.45 + self._bass * 0.70
        else:
            self._drop = (-1.0, -1.0)
        self._beat = max(0.0, self._beat - dt * 4.0)

        # Mid-driven continuous ripple points
        if self._mid > 0.3 and random.random() < self._mid * 0.4:
            self._drop = (random.random(), random.random())
            self._drop_amt = self._mid * 0.18

        # Intense sections: denser random impacts for a heavier storm feel.
        if self._energy > 0.55 and random.random() < self._energy * 0.95:
            self._drop = (random.random(), random.random())
            self._drop_amt = max(self._drop_amt, 0.14 + self._energy * 0.26)

    def render(self) -> None:
        ctx = self.ctx
        target_fbo = ctx.fbo

        # Indices: prev=step-2, curr=step-1, next=step (write target)
        i_prev = (self._step_idx - 2) % 3
        i_curr = (self._step_idx - 1) % 3
        i_next =  self._step_idx      % 3

        write_fbo, _    = self._fbos[i_next]
        _, prev_tex     = self._fbos[i_prev]
        _, curr_tex     = self._fbos[i_curr]

        if not (hasattr(write_fbo, "use") and hasattr(prev_tex, "use") and hasattr(curr_tex, "use")):
            return

        write_fbo.use()
        ctx.viewport = (0, 0, _SIM_W, _SIM_H)
        prev_tex.use(location=0)
        curr_tex.use(location=1)
        self._sim_prog["prev"].value       = 0
        self._sim_prog["curr"].value       = 1
        self._sim_prog["iResolution"].value = (float(_SIM_W), float(_SIM_H))
        self._sim_prog["iBass"].value      = self._bass
        self._sim_prog["iMid"].value       = self._mid
        self._sim_prog["iTime"].value      = self.time
        self._sim_prog["iEnergy"].value    = self._energy
        self._sim_prog["iDrop"].value      = self._drop
        self._sim_prog["iDropAmt"].value   = self._drop_amt
        self._sim_vao.render(moderngl.TRIANGLE_STRIP)

        self._step_idx = (self._step_idx + 1) % 3

        # Display to currently bound target (app may be rendering into transition FBO)
        target_bound = False
        if target_fbo is not None and hasattr(target_fbo, "use"):
            try:
                target_fbo.use()
                target_bound = True
            except Exception:
                target_bound = False
        if not target_bound and ctx.screen is not None and hasattr(ctx.screen, "use"):
            try:
                ctx.screen.use()
            except Exception:
                pass
        ctx.viewport = (0, 0, self.width, self.height)
        ctx.clear(0.0, 0.0, 0.0, 1.0)
        _, disp_tex = self._fbos[(self._step_idx - 1) % 3]
        if not hasattr(disp_tex, "use"):
            return
        disp_tex.use(location=0)
        self._disp_prog["height"].value  = 0
        self._disp_prog["iBass"].value   = self._bass
        self._disp_prog["iBeat"].value   = self._beat
        self._disp_prog["iTreble"].value = self._treble
        self._disp_prog["iTime"].value   = self.time
        self._disp_vao.render(moderngl.TRIANGLE_STRIP)

        # Reset drop so it only injects for one frame
        self._drop = (-1.0, -1.0)
        self._drop_amt = 0.0

    def destroy(self) -> None:
        self._sim_vao.release()
        self._disp_vao.release()
        self._vbo.release()
        self._sim_prog.release()
        self._disp_prog.release()
        for fbo, tex in self._fbos:
            fbo.release()
            tex.release()
