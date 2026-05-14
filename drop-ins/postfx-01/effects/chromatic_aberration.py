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
uniform float uMix;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    // Full-frame chroma displacement so the effect reads even in low-sat scenes.
    vec3 src = texture(tex, v_uv).rgb;
    vec2 uv = v_uv - 0.5;
    vec2 bias = vec2(uAmount * 1.10, -uAmount * 0.65);
    vec2 uv_r = uv * (1.0 + uAmount * 1.05) + bias;
    vec2 uv_g = uv * (1.0 + uAmount * 0.30) + vec2(-bias.y * 0.35, bias.x * 0.25);
    vec2 uv_b = uv * (1.0 - uAmount * 1.05) - bias;

    uv_r += 0.5;
    uv_g += 0.5;
    uv_b += 0.5;

    float rr = texture(tex, clamp(uv_r, 0.0, 1.0)).r;
    float gg = texture(tex, clamp(uv_g, 0.0, 1.0)).g;
    float bb = texture(tex, clamp(uv_b, 0.0, 1.0)).b;
    vec3 ab = vec3(rr, gg, bb);
    vec3 outc = mix(src, ab, clamp(uMix, 0.0, 1.0));
    fragColor = vec4(clamp(outc, 0.0, 1.0), 1.0);
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
        base = 0.018 + min(0.030, (treble * 0.013 + beat * 0.012 + bass * 0.008))
        self._pass.prog['uAmount'].value = base * (0.55 + 0.45 * s)
        self._pass.prog['uMix'].value = 0.45 + 0.45 * s
        self._pass.vao.render(moderngl.TRIANGLE_STRIP)

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def destroy(self) -> None:
        self._pass.release()
