"""Lens distortion + vignette post-process effect."""
from __future__ import annotations

import moderngl

from base import FullscreenPass


class LensDistortionVignette:
    """Apply barrel distortion and cinematic vignette."""

    NAME = 'Lens Distortion + Vignette'

    def __init__(self, ctx: moderngl.Context, width: int, height: int) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._pass = FullscreenPass.build(
            ctx,
            """
#version 330
uniform sampler2D tex;
uniform float uDistort;
uniform float uVignette;
in vec2 v_uv;
out vec4 fragColor;

void main() {
    vec2 uv = v_uv - 0.5;
    float r2 = dot(uv, uv);
    vec2 warped = uv * (1.0 + uDistort * r2);
    vec2 suv = warped + 0.5;

    vec3 c = texture(tex, clamp(suv, 0.0, 1.0)).rgb;

    float vig = smoothstep(1.06, 0.18, dot(uv, uv));
    c *= mix(1.0, vig, uVignette);

    // slight edge contrast lift for punch
    c = mix(c, pow(c, vec3(0.92)), 0.18);

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
        dst_fbo.use()
        self._ctx.viewport = (0, 0, dst_fbo.size[0], dst_fbo.size[1])
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        src_tex.use(location=0)
        self._pass.prog['tex'].value = 0
        s = max(0.0, min(1.0, float(strength)))
        self._pass.prog['uDistort'].value = 0.22 * (0.30 + 0.70 * s) + beat * 0.08
        self._pass.prog['uVignette'].value = 0.55 * (0.35 + 0.65 * s) + bass * 0.10
        self._pass.vao.render(moderngl.TRIANGLE_STRIP)

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def destroy(self) -> None:
        self._pass.release()
