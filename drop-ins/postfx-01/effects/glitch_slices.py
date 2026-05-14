"""Glitch slices post-process effect."""
from __future__ import annotations

import logging

import moderngl

from base import FullscreenPass

log = logging.getLogger(__name__)


class GlitchSlices:
    """Quick-hit horizontal glitch slices with RGB channel offsets."""

    NAME = 'Glitch Slices'

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
in vec2 v_uv;
out vec4 fragColor;

float hash11(float p) {
    p = fract(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return fract(p);
}

void main() {
    float bands = 42.0;
    float band = floor(v_uv.y * bands);
    float seed = band * 17.0 + floor(uTime * 36.0);
    float rnd = hash11(seed);

    float trigger = step(0.52, rnd);
    float shift = (rnd - 0.5) * 0.26 * uAmount * trigger;

    vec2 uv = v_uv;
    uv.x = clamp(uv.x + shift, 0.0, 1.0);

    // RGB split for stronger glitch character.
    float r = texture(tex, clamp(vec2(uv.x + 0.020 * uAmount * trigger, uv.y), 0.0, 1.0)).r;
    float g = texture(tex, uv).g;
    float b = texture(tex, clamp(vec2(uv.x - 0.020 * uAmount * trigger, uv.y), 0.0, 1.0)).b;

    vec3 c = vec3(r, g, b);
    fragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
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
        amt = 0.30 + 0.60 * s + min(0.22, beat * 0.18 + treble * 0.12)
        self._pass.prog['uAmount'].value = amt
        self._pass.vao.render(moderngl.TRIANGLE_STRIP)
        log.info('GlitchSlices firing: strength=%.2f amount=%.3f', s, amt)

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def reset(self) -> None:
        """Reset glitch timeline on trigger."""
        self._time = 0.0

    def destroy(self) -> None:
        self._pass.release()
