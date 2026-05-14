"""Radial zoom blur post-process effect."""
from __future__ import annotations

import logging

import moderngl

from base import FullscreenPass

log = logging.getLogger(__name__)


class RadialZoomBlur:
    """Quick-hit radial blur that pulls toward the center."""

    NAME = 'Radial Zoom Blur'

    def __init__(self, ctx: moderngl.Context, width: int, height: int) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._phase = 0.0
        self._pass = FullscreenPass.build(
            ctx,
            """
#version 330
uniform sampler2D tex;
uniform float uStrength;
in vec2 v_uv;
out vec4 fragColor;

void main() {
    vec2 center = vec2(0.5, 0.5);
    vec2 dir = center - v_uv;

    // 9-tap radial blur toward center.
    vec3 col = texture(tex, v_uv).rgb * 0.24;
    col += texture(tex, v_uv + dir * (0.06 * uStrength)).rgb * 0.18;
    col += texture(tex, v_uv + dir * (0.12 * uStrength)).rgb * 0.14;
    col += texture(tex, v_uv + dir * (0.18 * uStrength)).rgb * 0.11;
    col += texture(tex, v_uv + dir * (0.24 * uStrength)).rgb * 0.09;
    col += texture(tex, v_uv + dir * (0.30 * uStrength)).rgb * 0.08;
    col += texture(tex, v_uv + dir * (0.36 * uStrength)).rgb * 0.06;
    col += texture(tex, v_uv + dir * (0.42 * uStrength)).rgb * 0.06;
    col += texture(tex, v_uv + dir * (0.48 * uStrength)).rgb * 0.04;

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
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
        self._phase += dt
        dst_fbo.use()
        self._ctx.viewport = (0, 0, dst_fbo.size[0], dst_fbo.size[1])
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        src_tex.use(location=0)
        self._pass.prog['tex'].value = 0
        s = max(0.0, min(1.0, float(strength)))
        zoom_strength = 0.20 + 0.65 * s + min(0.18, beat * 0.22 + bass * 0.14)
        self._pass.prog['uStrength'].value = zoom_strength
        self._pass.vao.render(moderngl.TRIANGLE_STRIP)
        log.info('RadialZoomBlur firing: strength=%.2f zoom=%.3f', s, zoom_strength)

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def reset(self) -> None:
        """Reset phase on trigger."""
        self._phase = 0.0

    def destroy(self) -> None:
        self._pass.release()
