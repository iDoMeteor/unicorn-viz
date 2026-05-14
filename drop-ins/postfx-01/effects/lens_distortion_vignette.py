"""Lens distortion + vignette post-process effect."""
from __future__ import annotations

import logging

import moderngl

from base import FullscreenPass

log = logging.getLogger(__name__)


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

    // Vignette: strong at edges (high r2), fade to center (low r2).
    float vig = smoothstep(0.12, 0.95, dot(uv, uv));
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
        distort_val = 0.38 * (0.40 + 0.60 * s) + beat * 0.12
        vignette_val = 0.75 * (0.45 + 0.55 * s) + bass * 0.15
        log.info('LensDistortionVignette firing: strength=%.2f distort=%.4f vignette=%.4f', s, distort_val, vignette_val)
        self._pass.prog['uDistort'].value = distort_val
        self._pass.prog['uVignette'].value = vignette_val
        self._pass.vao.render(moderngl.TRIANGLE_STRIP)

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def reset(self) -> None:
        """Reset state on effect trigger."""
        pass

    def destroy(self) -> None:
        self._pass.release()
