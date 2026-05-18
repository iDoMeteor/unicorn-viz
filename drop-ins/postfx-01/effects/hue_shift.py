"""Hue-shift post-process effect.

Full-frame HSV hue rotation driven by cumulative scroll-wheel input.
Controlled by PostFxController.on_scroll() / clear_hue_shift().
Not a numbered slot effect; applied as a persistent overlay pass
independently of the one-shot slot pipeline.
"""
from __future__ import annotations

import moderngl

from base import FullscreenPass

_FRAG = """
#version 330

// Hue-shift pass.
// Uniforms:
//   tex         — source frame texture (unit 0)
//   uHueOffset  — hue rotation in [0, 1] (1.0 = full 360° cycle)
//   uMix        — blend strength [0, 1]; fades out as idle timer expires
// Produces fragColor with hue rotated by uHueOffset, blended back against
// the original to allow a smooth fade-out.

uniform sampler2D tex;
uniform float uHueOffset;
uniform float uMix;

in vec2 v_uv;
out vec4 fragColor;

vec3 rgb2hsv(vec3 c) {
    vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

vec3 hsv2rgb(vec3 c) {
    vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

void main() {
    vec3 src = texture(tex, v_uv).rgb;
    vec3 hsv = rgb2hsv(src);
    hsv.x = fract(hsv.x + uHueOffset);
    vec3 shifted = hsv2rgb(hsv);
    float m = clamp(uMix, 0.0, 1.0);
    fragColor = vec4(mix(src, shifted, m), 1.0);
}
"""


class HueShift:
    """Full-frame hue rotation pass.

    Not a slot effect — instantiated once inside PostFxController and
    applied after any active slot pass when the hue offset is non-zero
    and the idle timer is running.  The caller sets ``hue_offset`` and
    ``blend`` before calling ``apply()``.
    """

    NAME = 'Hue Shift'

    def __init__(self, ctx: moderngl.Context, width: int, height: int) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._pass = FullscreenPass.build(ctx, _FRAG)
        self.hue_offset: float = 0.0
        self.blend: float = 1.0

    def apply(
        self,
        src_tex: moderngl.Texture,
        dst_fbo: moderngl.Framebuffer,
        dt: float,          # noqa: ARG002
        bass: float,        # noqa: ARG002
        mid: float,         # noqa: ARG002
        treble: float,      # noqa: ARG002
        beat: float,        # noqa: ARG002
        strength: float,
    ) -> None:
        """Render hue-shifted frame from src_tex into dst_fbo."""
        dst_fbo.use()
        self._ctx.viewport = (0, 0, dst_fbo.size[0], dst_fbo.size[1])
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        src_tex.use(location=0)
        self._pass.prog['tex'].value = 0
        self._pass.prog['uHueOffset'].value = float(self.hue_offset)
        self._pass.prog['uMix'].value = max(0.0, min(1.0, float(strength) * self.blend))
        self._pass.vao.render(moderngl.TRIANGLE_STRIP)

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def destroy(self) -> None:
        self._pass.release()
