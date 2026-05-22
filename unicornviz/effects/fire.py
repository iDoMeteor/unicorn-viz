"""
Curtains — GPU ping-pong flowing light curtains.

Two off-screen FBOs alternate each frame. A simulation shader evolves
an energy field with upward flow and diffusion; a display shader maps
the field to vivid curtain-like bands. The previous hard ignition strip
is replaced by a soft, distributed source to avoid a visible bar.

Audio reactivity:
  - bass   → source intensity and flow lift
  - beat   → temporary energy spike
  - treble → shimmer/flicker at the curtain edges
"""
from __future__ import annotations

import numpy as np
import moderngl

from unicornviz.effects.base import BaseEffect, AudioData

# Simulation runs at this resolution; displayed fullscreen via bilinear up-scale
_SIM_W = 480
_SIM_H = 270

# ---------------------------------------------------------------------------
# Shaders
# ---------------------------------------------------------------------------

_VERT = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv        = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

# Simulation step: read previous heat field, diffuse + advect + cool
_SIM_FRAG = """
#version 330
uniform sampler2D prev;
uniform vec2      iResolution;   // sim resolution
uniform float     iBass;
uniform float     iBeat;
uniform float     iTreble;
uniform float     iTime;
uniform float     iIntensity;
uniform float     iSourcePhase;
uniform float     iSourceDrift;
uniform float     iFlowWarp;
// Simple hash for noise
float hash(vec2 p) {
    p = fract(p * vec2(127.1, 311.7));
    p += dot(p, p + 19.19);
    return fract(p.x * p.y);
}
out vec4 fragColor;
in  vec2 v_uv;

void main() {
    vec2 px = 1.0 / iResolution;

    // Sample neighbourhood with upward advection + slow warp drift.
    float lift = px.y * (1.35 + iBass * 0.9 + iFlowWarp * 0.35);
    float c  = texture(prev, v_uv).r;
    float sway = sin(v_uv.y * 8.0 + iTime * 0.35 + iSourcePhase) * px.x * (1.0 + iFlowWarp * 2.0);
    float u  = texture(prev, v_uv + vec2( sway,  lift)).r;
    float ul = texture(prev, v_uv + vec2(-px.x + sway, lift)).r;
    float ur = texture(prev, v_uv + vec2( px.x + sway, lift)).r;
    float l  = texture(prev, v_uv + vec2(-px.x, 0.0 )).r;
    float r  = texture(prev, v_uv + vec2( px.x, 0.0 )).r;

    // Weighted diffuse + advect
    float heat = (u * 1.8 + ul * 0.8 + ur * 0.8 + l * 0.3 + r * 0.3 + c * 0.8) / 4.8;

    // Cooling
    float cool = 0.006 + iTreble * 0.004;
    heat = max(0.0, heat - cool);

    // Soft distributed source near the lower region (no hard bar).
    float src = smoothstep(0.40, 0.02, v_uv.y);
    float driftX = v_uv.x + sin(iTime * 0.22 + iSourcePhase) * iSourceDrift;
    float n = hash(vec2(driftX * 73.1 + iSourcePhase * 11.0, iTime * 0.3));
    float n2 = hash(vec2(driftX * 17.9 + iSourcePhase * 5.0, iTime * 0.17 + 5.3));
    float base = iIntensity + iBass * 0.55 + iBeat * 0.75 + iFlowWarp * 0.12;
    float source = clamp(base * (0.55 + 0.45 * n), 0.0, 1.0);
    heat = mix(heat, source, src * (0.35 + 0.35 * n2));

    fragColor = vec4(heat, 0.0, 0.0, 1.0);
}
"""

# Display: map heat → vivid multi-stop palette
_DISPLAY_FRAG = """
#version 330
uniform sampler2D heat_tex;
uniform float     iBass;
uniform float     iBeat;
uniform float     iTime;
uniform float     iZoom;
uniform float     iPaletteShift;
uniform float     iSatBoost;

in  vec2 v_uv;
out vec4 fragColor;

vec3 palette(float t) {
    // 6-stop: black → deep violet → red → orange → yellow → white
    t = clamp(t, 0.0, 1.0);
    vec3 stops[6];
    stops[0] = vec3(0.00, 0.00, 0.00);
    stops[1] = vec3(0.20, 0.00, 0.30);
    stops[2] = vec3(0.85, 0.05, 0.00);
    stops[3] = vec3(1.00, 0.45, 0.00);
    stops[4] = vec3(1.00, 0.95, 0.10);
    stops[5] = vec3(1.00, 1.00, 1.00);
    float s = t * 5.0;
    int i   = int(s);
    float f = fract(s);
    if (i >= 5) return stops[5];
    return mix(stops[i], stops[i+1], f);
}

void main() {
    // Flip Y for display (heat sims bottom ignition)
    vec2 uv = vec2(v_uv.x, 1.0 - v_uv.y);
    uv = (uv - vec2(0.5)) * iZoom + vec2(0.5);
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) {
        fragColor = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }
    float heat = texture(heat_tex, uv).r;

    // Chromatic embellishment: slight hue warp on bass
    float hShift = iBass * 0.08 * sin(uv.x * 12.0 + iTime * 2.0);
    heat = clamp(heat + hShift, 0.0, 1.0);

    vec3 col = palette(fract(heat + iPaletteShift));

    // Gentle saturation/value modulation over long durations.
    float luma = dot(col, vec3(0.2126, 0.7152, 0.0722));
    col = mix(vec3(luma), col, 1.0 + iSatBoost * 0.35);
    col *= 0.95 + iSatBoost * 0.12;

    // Beat bloom: briefly brighten
    col += iBeat * 0.25 * vec3(1.0, 0.6, 0.3);

    fragColor = vec4(clamp(col, 0.0, 1.5), 1.0);
}
"""


class Curtains(BaseEffect):
    """GPU ping-pong flowing curtains with vivid palette and audio reactivity."""

    NAME = "Curtains"
    AUTHOR = "unicorn-viz"
    TAGS = ["classic", "audio", "gpu"]
    PING_PONG_FRIENDS = ['Fire', 'Water', 'Plasma']

    def _init(self) -> None:
        self.parameters = {"intensity": 0.82, "speed": float(self.config.get("speed", 1.0)), "zoom": float(self.config.get("zoom", 1.0))}

        self._sim_prog  = self._make_program(_VERT, _SIM_FRAG)
        self._disp_prog = self._make_program(_VERT, _DISPLAY_FRAG)

        self._sim_vao, self._vbo = self._fullscreen_quad(self._sim_prog)
        self._disp_vao = self.ctx.vertex_array(
            self._disp_prog,
            [(self._vbo, "2f", "in_vert")],
        )

        # Two ping-pong FBOs at sim resolution
        def _make_sim_fbo() -> tuple[moderngl.Framebuffer, moderngl.Texture]:
            tex = self.ctx.texture((_SIM_W, _SIM_H), 4, dtype="f4")
            tex.filter = moderngl.LINEAR, moderngl.LINEAR
            tex.repeat_x = False
            tex.repeat_y = False
            fbo = self.ctx.framebuffer(color_attachments=[tex])
            # Seed with randomized low heat so startup state is never identical.
            seed = np.zeros((_SIM_H, _SIM_W, 4), dtype=np.float32)
            x_noise = self.rng.uniform(0.0, 1.0, (_SIM_H, _SIM_W)).astype(np.float32)
            y = np.linspace(1.0, 0.0, _SIM_H, dtype=np.float32)[:, None]
            seed[..., 0] = np.clip((0.06 + 0.08 * x_noise) * (y ** 2.2), 0.0, 1.0)
            seed[..., 3] = 1.0
            tex.write(seed.tobytes())
            return fbo, tex

        self._fbo_a, self._tex_a = _make_sim_fbo()
        self._fbo_b, self._tex_b = _make_sim_fbo()
        self._ping = True   # True = read B write A; False = read A write B

        self._bass   = 0.0
        self._beat   = 0.0
        self._treble = 0.0
        self._source_phase = float(self.rng.uniform(0.0, 1000.0))
        self._source_drift = float(self.rng.uniform(0.02, 0.10))
        self._flow_warp = float(self.rng.uniform(0.0, 0.6))
        self._palette_shift = float(self.rng.uniform(0.0, 1.0))
        self._sat_boost = float(self.rng.uniform(0.0, 0.8))
        self._var_timer = 0.0
        self._var_next = float(self.rng.uniform(10.0, 18.0))
        self._target_source_drift = self._source_drift
        self._target_flow_warp = self._flow_warp
        self._target_sat_boost = self._sat_boost

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass   = audio.bass_n
        self._treble = audio.treble_n
        if audio.beat > 0.5:
            self._beat = 1.0
        self._beat = max(0.0, self._beat - dt * 5.0)

        # Slow evolving variation to avoid static long-run behavior.
        self._source_phase += dt * 0.22
        self._palette_shift = (self._palette_shift + dt * (0.01 + self._bass * 0.01)) % 1.0
        self._var_timer += dt
        if self._var_timer >= self._var_next:
            self._var_timer = 0.0
            self._var_next = float(self.rng.uniform(10.0, 18.0))
            self._target_source_drift = float(self.rng.uniform(0.02, 0.18))
            self._target_flow_warp = float(self.rng.uniform(0.0, 0.9))
            self._target_sat_boost = float(self.rng.uniform(0.0, 1.0))

        blend = min(1.0, dt * 0.45)
        self._source_drift += (self._target_source_drift - self._source_drift) * blend
        self._flow_warp += (self._target_flow_warp - self._flow_warp) * blend
        self._sat_boost += (self._target_sat_boost - self._sat_boost) * blend

    def render(self) -> None:
        ctx = self.ctx
        spd  = self.parameters["speed"]
        target_fbo = ctx.fbo

        # --- Simulation step(s) ---
        # Multiple sub-steps per frame gives taller, fuller flames.
        steps = max(2, int(4 * spd))
        for _ in range(steps):
            if self._ping:
                read_tex, write_fbo = self._tex_b, self._fbo_a
            else:
                read_tex, write_fbo = self._tex_a, self._fbo_b
            self._ping = not self._ping

            write_fbo.use()
            ctx.viewport = (0, 0, _SIM_W, _SIM_H)
            read_tex.use(location=0)
            self._sim_prog["prev"].value       = 0
            self._sim_prog["iResolution"].value = (float(_SIM_W), float(_SIM_H))
            self._sim_prog["iBass"].value      = self._bass * spd
            self._sim_prog["iBeat"].value      = self._beat
            self._sim_prog["iTreble"].value    = self._treble
            self._sim_prog["iTime"].value      = self.time
            self._sim_prog["iIntensity"].value = float(self.parameters["intensity"])
            self._sim_prog["iSourcePhase"].value = float(self._source_phase)
            self._sim_prog["iSourceDrift"].value = float(self._source_drift)
            self._sim_prog["iFlowWarp"].value = float(self._flow_warp)
            self._sim_vao.render(moderngl.TRIANGLE_STRIP)

        # --- Display ---
        # Render to whichever target app.py currently has bound (screen or transition FBO).
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
        # The texture we just wrote into is the current heat field
        if self._ping:
            self._tex_b.use(location=0)
        else:
            self._tex_a.use(location=0)
        self._disp_prog["heat_tex"].value = 0
        self._disp_prog["iBass"].value    = self._bass
        self._disp_prog["iBeat"].value    = self._beat
        self._disp_prog["iTime"].value    = self.time
        self._disp_prog["iZoom"].value    = float(self.parameters["zoom"])
        self._disp_prog["iPaletteShift"].value = float(self._palette_shift)
        self._disp_prog["iSatBoost"].value = float(self._sat_boost)
        self._disp_vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._sim_vao.release()
        self._disp_vao.release()
        self._vbo.release()
        self._sim_prog.release()
        self._disp_prog.release()
        self._fbo_a.release()
        self._fbo_b.release()
        self._tex_a.release()
        self._tex_b.release()
