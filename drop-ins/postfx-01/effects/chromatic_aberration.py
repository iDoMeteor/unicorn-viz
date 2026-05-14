"""Chromatic aberration post-process effect."""
from __future__ import annotations

import moderngl

from base import FullscreenPass


class ChromaticAberration:
    """Subtle RGB channel split with edge-biased falloff."""

    NAME = 'Chromatic Aberration'

    def __init__(self, ctx: moderngl.Context, width: int, height: int) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._pass = FullscreenPass.build(
            ctx,
            """
#version 330
uniform sampler2D tex;
uniform float uAmount;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    // Full-frame chroma displacement (not edge-only): each channel uses a
    // slightly different scale and offset around screen center.
    vec2 uv = v_uv - 0.5;
    vec2 bias = vec2(uAmount * 0.75, -uAmount * 0.35);
    vec2 uv_r = uv * (1.0 + uAmount * 0.75) + bias;
    vec2 uv_g = uv * (1.0 + uAmount * 0.18);
    vec2 uv_b = uv * (1.0 - uAmount * 0.75) - bias;

    uv_r += 0.5;
    uv_g += 0.5;
    uv_b += 0.5;

    float rr = texture(tex, clamp(uv_r, 0.0, 1.0)).r;
    float gg = texture(tex, clamp(uv_g, 0.0, 1.0)).g;
    float bb = texture(tex, clamp(uv_b, 0.0, 1.0)).b;
    fragColor = vec4(rr, gg, bb, 1.0);
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
        dst_fbo.use()
        self._ctx.viewport = (0, 0, dst_fbo.size[0], dst_fbo.size[1])
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        src_tex.use(location=0)
        self._pass.prog['tex'].value = 0
        s = max(0.0, min(1.0, float(strength)))
        base = 0.010 + min(0.024, (treble * 0.012 + beat * 0.010 + bass * 0.006))
        self._pass.prog['uAmount'].value = base * (0.30 + 0.70 * s)
        self._pass.vao.render(moderngl.TRIANGLE_STRIP)

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def destroy(self) -> None:
        self._pass.release()
