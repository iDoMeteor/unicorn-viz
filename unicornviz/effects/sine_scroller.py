"""Sine Scroller 3.1 - textless neon wave lasers with crossing squash.

This effect keeps the signature crossing-driven vertical contract/expand motion,
but drops retro glyph scrolling entirely in favor of high-energy neon ribbons,
laser sweeps, and a living starfield.
"""
from __future__ import annotations

import math

import moderngl
import numpy as np

from unicornviz.effects.base import AudioData, BaseEffect

_VERT_BG = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_FRAG_BG = """
#version 330
uniform float iTime;
uniform float iBass;
uniform float iMid;
uniform float iTreble;
uniform float iBeat;
uniform float iLaserBoost;
uniform float iSparkleBoost;
uniform float iColorSnap;
in vec2 v_uv;
out vec4 fragColor;

float hash(vec2 p) {
    p = fract(p * vec2(123.34, 345.45));
    p += dot(p, p + 34.345);
    return fract(p.x * p.y);
}

void main() {
    vec2 uv = v_uv;
    float t = iTime;

    // Deep-space gradient base.
    vec3 col = mix(vec3(0.006, 0.015, 0.040), vec3(0.000, 0.005, 0.016), uv.y);

    // Perspective cyber grid.
    float horizon = mix(0.64, 0.44, clamp(iBass, 0.0, 1.2) * 0.40);
    vec2 g = uv;
    g.y = max(0.02, g.y - horizon + 0.02);
    float persp = 0.13 / g.y;
    float gx = abs(fract((g.x - 0.5) * persp * 14.0 + 0.5) - 0.5);
    float gy = abs(fract(g.y * persp * 22.0 - t * (0.45 + iMid * 0.75)) - 0.5);
    float grid = smoothstep(0.06, 0.0, min(gx, gy));
    col += vec3(0.00, 0.44, 0.74) * grid * (0.16 + iTreble * 0.32);

    // Crossing-wave plasma bands (inverse-reactive vs foreground ribbons).
    float fg_energy = clamp(iBass * 0.55 + iMid * 0.30 + iBeat * 0.75, 0.0, 1.35);
    float bg_contrary = 1.0 - clamp(fg_energy * 0.78, 0.0, 1.0);
    float bg_lane_amp = mix(0.06, 0.12, bg_contrary);
    float bg_lane_speed = mix(3.1, 1.8, bg_contrary);
    float laneA = abs(uv.y - (0.50 + sin((uv.x * 10.0 - t * bg_lane_speed)) * bg_lane_amp));
    float laneB = abs(uv.y - (0.50 - sin((uv.x * 10.0 - t * bg_lane_speed + 1.57)) * bg_lane_amp));
    float ribbon_dist = min(laneA, laneB);
    float ribbon_core = smoothstep(0.030, 0.0, ribbon_dist);
    float ribbon_glow = smoothstep(0.085, 0.0, ribbon_dist);
    float ribbon_pulse = 0.52 + 0.48 * sin(t * (4.2 + iTreble * 7.5) + uv.x * 26.0 + uv.y * 9.0);
    vec3 ribbon_col = mix(vec3(0.44, 0.14, 0.92), vec3(0.78, 0.24, 1.00), ribbon_pulse);
    float ribbon_gain = 0.18 + bg_contrary * 0.58;

    // Sparkle glints constrained to ribbon cores so they read as energetic highlights.
    vec2 rcell = floor(vec2(uv.x * 420.0 + t * 18.0, uv.y * 220.0 - t * 7.0));
    float rseed = hash(rcell);
    float rspark = step(0.996, rseed) * smoothstep(0.032, 0.0, ribbon_dist);
    float rtwinkle = 0.40 + 0.60 * sin(t * (9.0 + rseed * 8.0) + rseed * 23.0);
    float ribbon_sparkle = rspark * rtwinkle * (0.45 + iTreble * 0.75);

    col += ribbon_col * ribbon_glow * (0.12 + ribbon_gain * 0.55);
    col += ribbon_col * ribbon_core * (0.34 + ribbon_gain * 0.95);
    col += vec3(0.96, 0.72, 1.00) * ribbon_sparkle;

    // Living starfield: clustered sparkle, drift, and twinkle pulses.
    vec2 star_uv = uv * 240.0;
    vec2 cell = floor(star_uv);
    vec2 local = fract(star_uv) - 0.5;
    float star_pick = hash(cell);
    float star = step(0.985, star_pick);
    vec2 jitter = vec2(hash(cell + 3.11), hash(cell + 9.37)) - 0.5;
    float drift = 0.12 * sin(t * 0.8 + hash(cell + 1.71) * 6.28318);
    float d = length(local - jitter * 0.38 + vec2(0.0, drift * 0.03));
    float core = smoothstep(0.030, 0.0, d);
    float halo = smoothstep(0.11, 0.0, d);
    float twinkle = 0.45 + 0.55 * sin(t * (7.0 + hash(cell + 7.13) * (9.0 + iSparkleBoost * 5.0)) + hash(cell + 5.19) * 6.28318);
    float burst = smoothstep(0.89 - iSparkleBoost * 0.03, 1.0, sin(t * (2.7 + iSparkleBoost * 0.8) + hash(cell + 2.0) * 16.0));
    float sparkle = star * (core * (1.1 + iTreble * 0.7 + iSparkleBoost * 0.55) + halo * (0.35 + iSparkleBoost * 0.15)) * (0.55 + twinkle * (0.9 + iSparkleBoost * 0.4) + burst * (0.45 + iSparkleBoost * 0.6));
    col += vec3(0.75, 0.90, 1.00) * sparkle;

    // Beat flash lift.
    col += vec3(0.24, 0.07, 0.54) * iBeat * 0.22;

    // Color snap pulse for brief chaos hits.
    vec3 snap_col = vec3(
        0.5 + 0.5 * sin(t * 13.0 + uv.y * 22.0),
        0.5 + 0.5 * sin(t * 17.0 + uv.x * 26.0 + 2.1),
        0.5 + 0.5 * sin(t * 19.0 + (uv.x + uv.y) * 16.0 + 4.2)
    );
    float snap_amt = smoothstep(0.03, 0.92, clamp(iColorSnap, 0.0, 1.0));
    col = mix(col, max(col, snap_col * (0.50 + iLaserBoost * 0.60)), snap_amt);

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""

_VERT_RIBBON = """
#version 330
in vec2 in_pos;
in float in_bri;
in float in_mix;
out float v_bri;
out float v_mix;
void main() {
    v_bri = in_bri;
    v_mix = in_mix;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

_FRAG_RIBBON = """
#version 330
uniform vec4 colorA;
uniform vec4 colorB;
in float v_bri;
in float v_mix;
out vec4 fragColor;
void main() {
    float bri = clamp(v_bri, 0.0, 2.0);
    vec4 c = mix(colorA, colorB, clamp(v_mix, 0.0, 1.0));
    vec3 rgb = c.rgb * mix(0.45, 1.9, bri * 0.7);
    float alpha = c.a * mix(0.45, 1.35, bri);
    fragColor = vec4(rgb, alpha);
}
"""


class SineScroller(BaseEffect):
    NAME = 'Sine Scroller 3.1'
    AUTHOR = 'unicorn-viz'
    TAGS = ['classic', 'audio', 'futuristic', 'neon', 'lasers']
    PING_PONG_FRIENDS = ['Copper Bars', 'Vector', 'ANSI Viewer']

    def _init(self) -> None:
        self.parameters = {
            'speed': float(self.config.get('speed', 2.25)),
            'zoom': float(self.config.get('zoom', 1.0)),
            'amplitude': float(self.config.get('amplitude', 0.24)),
            'bass_sensitivity': float(self.config.get('bass_sensitivity', 1.35)),
            'beat_intensity': float(self.config.get('beat_intensity', 1.35)),
            'reactivity': float(self.config.get('reactivity', 1.25)),
            'laser_width': float(self.config.get('laser_width', 0.05)),
            'laser_density': float(self.config.get('laser_density', 1.0)),
            'laser_boost': float(self.config.get('laser_boost', 1.0)),
            'sparkle_boost': float(self.config.get('sparkle_boost', 1.0)),
            'chaos_snap': float(self.config.get('chaos_snap', 1.0)),
            'top_lane_scale': float(self.config.get('top_lane_scale', 0.88)),
            'snap_chance': float(self.config.get('snap_chance', 0.22)),
            'snap_cooldown_s': float(self.config.get('snap_cooldown_s', 2.8)),
        }

        self._bg_prog = self._make_program(_VERT_BG, _FRAG_BG)
        self._bg_vao, self._bg_vbo = self._fullscreen_quad(self._bg_prog)

        self._ribbon_prog = self._make_program(_VERT_RIBBON, _FRAG_RIBBON)
        self._ribbon_vbo = self.ctx.buffer(reserve=2 * 1024 * 1024)
        self._ribbon_vao = self.ctx.vertex_array(
            self._ribbon_prog,
            [(self._ribbon_vbo, '2f 1f 1f', 'in_pos', 'in_bri', 'in_mix')],
        )

        self._bass = 0.0
        self._mid = 0.0
        self._treble = 0.0
        self._beat = 0.0
        self._snap = 0.0
        self._snap_cooldown = float(self.rng.uniform(0.8, 2.2))
        self._focus_mix = float(self.rng.uniform(0.0, 1.0))
        self._focus_target = self._focus_mix
        self._phase = float(self.rng.uniform(0.0, 6.28318))
        self._scroll_a = float(self.width) + float(self.rng.uniform(0.0, 220.0))
        self._scroll_b = -float(self.width) - float(self.rng.uniform(60.0, 280.0))

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        react = max(0.05, float(self.parameters['reactivity']))

        self._bass = float(audio.bass_n) * float(self.parameters['bass_sensitivity'])
        self._mid = float(audio.mid_n)
        self._treble = float(audio.treble_n)

        self._snap_cooldown = max(0.0, self._snap_cooldown - dt)

        if audio.beat > 0.5:
            self._beat = max(self._beat, float(self.parameters['beat_intensity']))
            if self._snap_cooldown <= 0.0:
                snap_chance = min(0.95, max(0.0, float(self.parameters['snap_chance'])))
                snap_gate = 0.55 + min(1.0, self._treble) * 0.35
                if self.rng.random() < snap_chance * snap_gate:
                    self._snap = max(self._snap, 1.0)
                    self._focus_target = 1.0 - self._focus_target
                    base_cd = max(0.4, float(self.parameters['snap_cooldown_s']))
                    self._snap_cooldown = float(self.rng.uniform(base_cd * 0.8, base_cd * 1.6))

        self._beat = max(0.0, self._beat - dt * (3.5 + react * 1.1))
        self._snap = max(0.0, self._snap - dt * (2.5 + react * 0.9))

        focus_lerp = min(1.0, dt * (2.2 + self._snap * 7.0))
        self._focus_mix += (self._focus_target - self._focus_mix) * focus_lerp

        speed = max(0.05, float(self.parameters['speed']))
        lane_drive = speed * (240.0 + self._bass * 95.0 + self._beat * 55.0)
        self._scroll_a -= dt * lane_drive
        self._scroll_b += dt * lane_drive * 0.96
        self._phase = (self._phase + dt * (2.1 + speed * 0.9 + self._mid * react * 1.4)) % 6.28318

        recycle = float(self.width) * 1.4
        if self._scroll_a < -recycle:
            self._scroll_a = recycle + float(self.rng.uniform(30.0, 250.0))
        if self._scroll_b > recycle:
            self._scroll_b = -recycle - float(self.rng.uniform(30.0, 250.0))

    def _lane_sample(
        self,
        x_px: float,
        wave_sign: float,
        phase_bias: float,
        width_scale: float,
    ) -> tuple[float, float, float]:
        amp = max(0.02, float(self.parameters['amplitude'])) * (1.0 + self._bass * 0.45)
        phase = self._phase + phase_bias + (x_px / max(1.0, self.width)) * 12.0
        wave = math.sin(phase)

        # Signature behavior: thin at crossing, thick at crest/trough.
        cross_contract = 0.22 + 0.78 * abs(wave)

        center_y = self.height * 0.5 + wave_sign * wave * amp * self.height
        width_px = (
            max(0.01, float(self.parameters['laser_width']))
            * self.height
            * max(0.1, float(self.parameters['zoom']))
            * cross_contract
            * max(0.05, width_scale)
            * (1.0 + self._beat * 0.12)
        )

        brightness = min(2.0, 0.42 + 0.42 * abs(wave) + self._treble * 0.46 + self._beat * 0.35)
        return center_y, width_px, brightness

    def _build_lane(
        self,
        scroll_x: float,
        wave_sign: float,
        phase_bias: float,
        mix_bias: float,
        width_scale: float,
    ) -> list[float]:
        verts: list[float] = []

        density = max(0.4, float(self.parameters['laser_density']))
        seg_px = max(6.0, 14.0 / density)
        x0 = -self.width * 0.20
        x1 = self.width * 1.20

        def px(v: float) -> float:
            return (v / self.width) * 2.0 - 1.0

        def py(v: float) -> float:
            return 1.0 - (v / self.height) * 2.0

        x = x0
        while x < x1:
            x_next = min(x1, x + seg_px)

            sx0 = x + scroll_x
            sx1 = x_next + scroll_x

            cy0, w0, b0 = self._lane_sample(sx0, wave_sign, phase_bias, width_scale)
            cy1, w1, b1 = self._lane_sample(sx1, wave_sign, phase_bias, width_scale)

            y0_top = cy0 - w0 * 0.5
            y0_bot = cy0 + w0 * 0.5
            y1_top = cy1 - w1 * 0.5
            y1_bot = cy1 + w1 * 0.5

            m0 = 0.5 + 0.5 * math.sin((sx0 * 0.012) + mix_bias + self.time * 0.9)
            m1 = 0.5 + 0.5 * math.sin((sx1 * 0.012) + mix_bias + self.time * 0.9)

            x0n, x1n = px(x), px(x_next)
            y0tn, y0bn = py(y0_top), py(y0_bot)
            y1tn, y1bn = py(y1_top), py(y1_bot)

            verts += [x0n, y0tn, b0, m0,  x1n, y1tn, b1, m1,  x0n, y0bn, b0, m0]
            verts += [x1n, y1tn, b1, m1,  x1n, y1bn, b1, m1,  x0n, y0bn, b0, m0]

            x = x_next

        return verts

    def _build_ribbons(self) -> tuple[np.ndarray, int, np.ndarray, int]:
        top_lane_scale = max(0.05, float(self.parameters['top_lane_scale']))
        top_verts = self._build_lane(
            scroll_x=self._scroll_a,
            wave_sign=1.0,
            phase_bias=0.0,
            mix_bias=0.5,
            width_scale=top_lane_scale,
        )
        bot_verts = self._build_lane(
            scroll_x=self._scroll_b,
            wave_sign=-1.0,
            phase_bias=1.57,
            mix_bias=2.4,
            width_scale=1.0,
        )

        if top_verts:
            top_arr = np.array(top_verts, dtype=np.float32)
            top_n = len(top_verts) // 4
        else:
            top_arr = np.zeros(0, dtype=np.float32)
            top_n = 0

        if bot_verts:
            bot_arr = np.array(bot_verts, dtype=np.float32)
            bot_n = len(bot_verts) // 4
        else:
            bot_arr = np.zeros(0, dtype=np.float32)
            bot_n = 0

        return top_arr, top_n, bot_arr, bot_n

    def render(self) -> None:
        self._bg_prog['iTime'].value = self.time
        self._bg_prog['iBass'].value = self._bass
        self._bg_prog['iMid'].value = self._mid
        self._bg_prog['iTreble'].value = self._treble
        self._bg_prog['iBeat'].value = self._beat
        self._bg_prog['iLaserBoost'].value = max(0.0, float(self.parameters['laser_boost']))
        self._bg_prog['iSparkleBoost'].value = max(0.0, float(self.parameters['sparkle_boost']))
        snap_gain = max(0.0, float(self.parameters['chaos_snap']))
        snap_power = min(1.0, (self._snap ** 0.7) * snap_gain * 2.2)
        self._bg_prog['iColorSnap'].value = snap_power
        self._bg_vao.render(moderngl.TRIANGLE_STRIP)

        top_data, top_n, bot_data, bot_n = self._build_ribbons()
        if top_n <= 0 and bot_n <= 0:
            return

        self.ctx.enable(moderngl.BLEND)

        # Big additive bloom pass for neon laser punch.
        hue_a = (self.time * 0.17 + self._phase * 0.08) % 1.0
        hue_b = (self.time * 0.23 + self._phase * 0.05 + 0.37) % 1.0
        a_r = 0.5 + 0.5 * math.cos(hue_a * 6.28318)
        a_g = 0.5 + 0.5 * math.cos(hue_a * 6.28318 + 2.094)
        a_b = 0.5 + 0.5 * math.cos(hue_a * 6.28318 + 4.188)
        b_r = 0.5 + 0.5 * math.cos(hue_b * 6.28318)
        b_g = 0.5 + 0.5 * math.cos(hue_b * 6.28318 + 2.094)
        b_b = 0.5 + 0.5 * math.cos(hue_b * 6.28318 + 4.188)
        laser_boost = max(0.0, float(self.parameters['laser_boost']))
        bloom_gain = 1.0 + laser_boost * 0.55
        core_gain = 1.0 + laser_boost * 0.30

        top_focus = 1.0 - self._focus_mix
        bot_focus = self._focus_mix

        def lane_strength(focus: float) -> float:
            return 0.24 + 0.92 * max(0.0, min(1.0, focus))

        top_strength = lane_strength(top_focus)
        bot_strength = lane_strength(bot_focus)

        # During snap, exaggerate foreground/background separation for stronger takeovers.
        snap_sep = 0.18 + snap_power * 0.34
        if top_strength >= bot_strength:
            top_strength = min(1.35, top_strength + snap_sep)
            bot_strength = max(0.14, bot_strength - snap_sep * 0.55)
        else:
            bot_strength = min(1.35, bot_strength + snap_sep)
            top_strength = max(0.14, top_strength - snap_sep * 0.55)

        # Draw background lane first, focused lane second so it reads as foreground.
        draw_order = [
            ('top', top_data, top_n, top_strength),
            ('bot', bot_data, bot_n, bot_strength),
        ]
        draw_order.sort(key=lambda item: item[3])

        for _name, lane_data, lane_n, strength in draw_order:
            if lane_n <= 0 or lane_data.size == 0:
                continue

            if lane_data.nbytes > self._ribbon_vbo.size:
                self._ribbon_vbo.orphan(lane_data.nbytes * 2)
            self._ribbon_vbo.write(lane_data)

            alpha_boost = 0.24 + 0.68 * strength + snap_power * 0.20
            core_alpha = 0.50 + 0.46 * strength + snap_power * 0.10
            lane_bloom = bloom_gain * (0.78 + 0.36 * strength)
            lane_core = core_gain * (0.84 + 0.30 * strength)

            self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE
            # Overdrive scales bloom and core separately so neon punch can be tuned.
            self._ribbon_prog['colorA'].value = (
                (0.08 + a_r * 0.70) * lane_bloom,
                (0.10 + a_g * 1.05) * lane_bloom,
                (0.25 + a_b * 0.95) * lane_bloom,
                min(1.0, alpha_boost),
            )
            self._ribbon_prog['colorB'].value = (
                (0.15 + b_r * 0.95) * lane_bloom,
                (0.02 + b_g * 0.65) * lane_bloom,
                (0.34 + b_b * 1.10) * lane_bloom,
                min(1.0, alpha_boost * 0.92),
            )
            self._ribbon_vao.render(moderngl.TRIANGLES, vertices=lane_n)

            # Core lane pass for edge definition.
            self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
            self._ribbon_prog['colorA'].value = (
                (0.10 + a_r * 1.00) * lane_core,
                (0.20 + a_g * 1.08) * lane_core,
                (0.40 + a_b * 0.96) * lane_core,
                min(1.0, core_alpha),
            )
            self._ribbon_prog['colorB'].value = (
                (0.20 + b_r * 1.05) * lane_core,
                (0.10 + b_g * 0.82) * lane_core,
                (0.55 + b_b * 1.00) * lane_core,
                min(1.0, core_alpha * 0.94),
            )
            self._ribbon_vao.render(moderngl.TRIANGLES, vertices=lane_n)

    def destroy(self) -> None:
        self._bg_vao.release()
        self._bg_vbo.release()
        self._bg_prog.release()
        self._ribbon_vbo.release()
        self._ribbon_vao.release()
        self._ribbon_prog.release()
