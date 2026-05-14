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
    vec2 center = v_uv - 0.5;
    float r = length(center);
    vec2 dir = normalize(center + vec2(1e-6, 0.0));
    float edge = 0.35 + 0.65 * smoothstep(0.02, 0.85, r);
    vec2 shift = dir * uAmount * edge;

    float rr = texture(tex, v_uv + shift).r;
    float gg = texture(tex, v_uv).g;
    float bb = texture(tex, v_uv - shift).b;
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
        self._pass.prog['uAmount'].value = (0.006 + min(0.018, (treble * 0.010 + beat * 0.009))) * (0.25 + 0.75 * s)
        self._pass.vao.render(moderngl.TRIANGLE_STRIP)

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def destroy(self) -> None:
        self._pass.release()
