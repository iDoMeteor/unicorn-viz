"""Heat haze refraction post-process effect."""
from __future__ import annotations

import logging

import moderngl

from base import FullscreenPass

log = logging.getLogger(__name__)


class HeatHazeRefraction:
    """Animated turbulence UV warp simulating rising hot air / heat shimmer."""

    NAME = 'Heat Haze Refraction'

    def __init__(self, ctx: moderngl.Context, width: int, height: int) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._time = 0.0
        self._pass = FullscreenPass.build(
            ctx,
            """
#version 330
uniform sampler2D tex;
uniform float uTime;
uniform float uAmount;
uniform float uSpeed;
in vec2 v_uv;
out vec4 fragColor;

// 2-octave value noise for heat shimmer turbulence.
vec2 hash22(vec2 p) {
    p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)));
    return -1.0 + 2.0 * fract(sin(p) * 43758.5453123);
}

float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(
        mix(dot(hash22(i + vec2(0,0)), f - vec2(0,0)),
            dot(hash22(i + vec2(1,0)), f - vec2(1,0)), u.x),
        mix(dot(hash22(i + vec2(0,1)), f - vec2(0,1)),
            dot(hash22(i + vec2(1,1)), f - vec2(1,1)), u.x),
        u.y
    );
}

void main() {
    float t = uTime * uSpeed;

    // Heat rises: stronger warp near bottom of screen.
    float heatBias = 1.0 - v_uv.y;
    heatBias = heatBias * heatBias;

    // Two-layer turbulence with different frequencies and drift speeds.
    vec2 coord = v_uv * vec2(6.0, 3.5);
    float n1 = noise(coord + vec2(t * 0.7, t * 1.1));
    float n2 = noise(coord * 2.2 + vec2(-t * 1.3, t * 0.8));

    vec2 warp = vec2(n1 + n2 * 0.5, n2 + n1 * 0.4) * uAmount * heatBias;
    vec2 uv = clamp(v_uv + warp, 0.001, 0.999);

    // Subtle chromatic split along the warp direction for heat-lens feel.
    float split = length(warp) * 0.5;
    float r = texture(tex, clamp(uv + warp * split, 0.001, 0.999)).r;
    float g = texture(tex, uv).g;
    float b = texture(tex, clamp(uv - warp * split, 0.001, 0.999)).b;

    fragColor = vec4(clamp(vec3(r, g, b), 0.0, 1.0), 1.0);
}
""",
        )

    def apply(
        self,
        src_tex: moderngl.Texture,
        dst_fbo: moderngl.Framebuffer,
        dt: float,
        bass: float,
        mid: float,
        treble: float,
        beat: float,
        strength: float,
    ) -> None:
        self._time += dt
        dst_fbo.use()
        self._ctx.viewport = (0, 0, dst_fbo.size[0], dst_fbo.size[1])
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        src_tex.use(location=0)
        self._pass.prog['tex'].value = 0
        self._pass.prog['uTime'].value = self._time

        s = max(0.0, min(1.0, float(strength)))
        amount = (0.012 + 0.028 * s + bass * 0.010 + beat * 0.014) * 3.8
        speed = 0.9 + mid * 0.6 + s * 0.5

        self._pass.prog['uAmount'].value = amount
        self._pass.prog['uSpeed'].value = speed
        self._pass.vao.render(moderngl.TRIANGLE_STRIP)
        log.info('HeatHazeRefraction firing: strength=%.2f amount=%.4f speed=%.3f', s, amount, speed)

    def reset(self) -> None:
        """Keep time running; reset has no visible benefit for continuous noise."""
        pass

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def destroy(self) -> None:
        self._pass.release()
