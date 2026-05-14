"""Multi-pass bloom post-process effect."""
from __future__ import annotations

import logging

import moderngl
import numpy as np

from base import FullscreenPass

log = logging.getLogger(__name__)

_BRIGHT_EXTRACT_FRAG = """
#version 330
uniform sampler2D tex;
uniform float uThreshold;
uniform float uSoftKnee;
in vec2 v_uv;
out vec4 fragColor;

void main() {
    vec3 c = texture(tex, v_uv).rgb;
    // Soft-knee threshold: smoothly extract bright regions.
    float luma = dot(c, vec3(0.2126, 0.7152, 0.0722));
    float rq = clamp(luma - uThreshold + uSoftKnee, 0.0, 2.0 * uSoftKnee);
    float weight = (rq * rq) / (4.0 * uSoftKnee * max(uSoftKnee, 0.0001));
    float contrib = max(weight, luma - uThreshold) / max(luma, 0.001);
    fragColor = vec4(c * contrib, 1.0);
}
"""

_BLUR_H_FRAG = """
#version 330
uniform sampler2D tex;
uniform vec2 uTexelSize;
uniform float uRadius;
in vec2 v_uv;
out vec4 fragColor;

void main() {
    // 13-tap separable Gaussian, horizontal.
    vec2 d = vec2(uTexelSize.x * uRadius, 0.0);
    vec3 col = vec3(0.0);
    col += texture(tex, v_uv + d * -6.0).rgb * 0.007;
    col += texture(tex, v_uv + d * -5.0).rgb * 0.022;
    col += texture(tex, v_uv + d * -4.0).rgb * 0.054;
    col += texture(tex, v_uv + d * -3.0).rgb * 0.096;
    col += texture(tex, v_uv + d * -2.0).rgb * 0.127;
    col += texture(tex, v_uv + d * -1.0).rgb * 0.148;
    col += texture(tex, v_uv           ).rgb * 0.154;
    col += texture(tex, v_uv + d *  1.0).rgb * 0.148;
    col += texture(tex, v_uv + d *  2.0).rgb * 0.127;
    col += texture(tex, v_uv + d *  3.0).rgb * 0.096;
    col += texture(tex, v_uv + d *  4.0).rgb * 0.054;
    col += texture(tex, v_uv + d *  5.0).rgb * 0.022;
    col += texture(tex, v_uv + d *  6.0).rgb * 0.007;
    fragColor = vec4(col, 1.0);
}
"""

_BLUR_V_FRAG = """
#version 330
uniform sampler2D tex;
uniform vec2 uTexelSize;
uniform float uRadius;
in vec2 v_uv;
out vec4 fragColor;

void main() {
    // 13-tap separable Gaussian, vertical.
    vec2 d = vec2(0.0, uTexelSize.y * uRadius);
    vec3 col = vec3(0.0);
    col += texture(tex, v_uv + d * -6.0).rgb * 0.007;
    col += texture(tex, v_uv + d * -5.0).rgb * 0.022;
    col += texture(tex, v_uv + d * -4.0).rgb * 0.054;
    col += texture(tex, v_uv + d * -3.0).rgb * 0.096;
    col += texture(tex, v_uv + d * -2.0).rgb * 0.127;
    col += texture(tex, v_uv + d * -1.0).rgb * 0.148;
    col += texture(tex, v_uv           ).rgb * 0.154;
    col += texture(tex, v_uv + d *  1.0).rgb * 0.148;
    col += texture(tex, v_uv + d *  2.0).rgb * 0.127;
    col += texture(tex, v_uv + d *  3.0).rgb * 0.096;
    col += texture(tex, v_uv + d *  4.0).rgb * 0.054;
    col += texture(tex, v_uv + d *  5.0).rgb * 0.022;
    col += texture(tex, v_uv + d *  6.0).rgb * 0.007;
    fragColor = vec4(col, 1.0);
}
"""

_COMPOSITE_FRAG = """
#version 330
uniform sampler2D uScene;
uniform sampler2D uBloom;
uniform float uIntensity;
in vec2 v_uv;
out vec4 fragColor;

void main() {
    vec3 scene = texture(uScene, v_uv).rgb;
    vec3 bloom = texture(uBloom, v_uv).rgb;
    // Additive bloom composite.
    vec3 result = scene + bloom * uIntensity;
    // Mild tone-map to prevent harsh clipping.
    result = result / (result + 0.55);
    fragColor = vec4(clamp(result * 1.55, 0.0, 1.0), 1.0);
}
"""


class MultiPassBloom:
    """Bright-extract → H-blur → V-blur → additive composite bloom."""

    NAME = 'Multi-pass Bloom'

    def __init__(self, ctx: moderngl.Context, width: int, height: int) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height

        self._pass_bright = FullscreenPass.build(ctx, _BRIGHT_EXTRACT_FRAG)
        self._pass_blur_h = FullscreenPass.build(ctx, _BLUR_H_FRAG)
        self._pass_blur_v = FullscreenPass.build(ctx, _BLUR_V_FRAG)
        self._pass_comp   = FullscreenPass.build(ctx, _COMPOSITE_FRAG)

        self._bright_fbo: moderngl.Framebuffer | None = None
        self._blur_h_fbo: moderngl.Framebuffer | None = None
        self._blur_v_fbo: moderngl.Framebuffer | None = None
        self._bloom_tex: moderngl.Texture | None = None
        self._bright_tex: moderngl.Texture | None = None
        self._blur_h_tex: moderngl.Texture | None = None
        self._allocate_fbos(width, height)

    def _allocate_fbos(self, width: int, height: int) -> None:
        """Create quarter-resolution bloom FBOs."""
        self._release_fbos()
        bw = max(1, width // 4)
        bh = max(1, height // 4)

        self._bright_tex = self._ctx.texture((bw, bh), 3, dtype='f2')
        self._bright_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._bright_fbo = self._ctx.framebuffer(color_attachments=[self._bright_tex])

        self._blur_h_tex = self._ctx.texture((bw, bh), 3, dtype='f2')
        self._blur_h_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._blur_h_fbo = self._ctx.framebuffer(color_attachments=[self._blur_h_tex])

        self._bloom_tex = self._ctx.texture((bw, bh), 3, dtype='f2')
        self._bloom_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._blur_v_fbo = self._ctx.framebuffer(color_attachments=[self._bloom_tex])

    def _release_fbos(self) -> None:
        for attr in ('_bright_fbo', '_blur_h_fbo', '_blur_v_fbo',
                     '_bright_tex', '_blur_h_tex', '_bloom_tex'):
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    obj.release()
                except Exception:
                    pass
            setattr(self, attr, None)

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
        s = max(0.0, min(1.0, float(strength)))
        threshold = max(0.05, 0.42 - s * 0.25 - beat * 0.10)
        soft_knee = 0.12
        blur_radius = 1.5 + s * 1.2
        intensity = 1.8 + s * 3.5 + bass * 1.6 + beat * 1.2
        bw, bh = self._bright_fbo.size

        log.info(
            'MultiPassBloom firing: strength=%.2f threshold=%.3f intensity=%.3f',
            s, threshold, intensity,
        )

        # Pass 1: bright extract at quarter resolution.
        self._bright_fbo.use()
        self._ctx.viewport = (0, 0, bw, bh)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        src_tex.use(location=0)
        self._pass_bright.prog['tex'].value = 0
        self._pass_bright.prog['uThreshold'].value = threshold
        self._pass_bright.prog['uSoftKnee'].value = soft_knee
        self._pass_bright.vao.render(moderngl.TRIANGLE_STRIP)

        # Pass 2: horizontal Gaussian blur.
        self._blur_h_fbo.use()
        self._ctx.viewport = (0, 0, bw, bh)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        self._bright_tex.use(location=0)
        self._pass_blur_h.prog['tex'].value = 0
        self._pass_blur_h.prog['uTexelSize'].value = (1.0 / bw, 1.0 / bh)
        self._pass_blur_h.prog['uRadius'].value = blur_radius
        self._pass_blur_h.vao.render(moderngl.TRIANGLE_STRIP)

        # Pass 3: vertical Gaussian blur → bloom texture.
        self._blur_v_fbo.use()
        self._ctx.viewport = (0, 0, bw, bh)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        self._blur_h_tex.use(location=0)
        self._pass_blur_v.prog['tex'].value = 0
        self._pass_blur_v.prog['uTexelSize'].value = (1.0 / bw, 1.0 / bh)
        self._pass_blur_v.prog['uRadius'].value = blur_radius
        self._pass_blur_v.vao.render(moderngl.TRIANGLE_STRIP)

        # Pass 4: composite scene + bloom → destination.
        dst_fbo.use()
        w, h = dst_fbo.size
        self._ctx.viewport = (0, 0, w, h)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        src_tex.use(location=0)
        self._bloom_tex.use(location=1)
        self._pass_comp.prog['uScene'].value = 0
        self._pass_comp.prog['uBloom'].value = 1
        self._pass_comp.prog['uIntensity'].value = intensity
        self._pass_comp.vao.render(moderngl.TRIANGLE_STRIP)

    def reset(self) -> None:
        """Clear bloom buffers on trigger to avoid stale glow on first frame."""
        for fbo in (self._bright_fbo, self._blur_h_fbo, self._blur_v_fbo):
            if fbo is not None:
                try:
                    fbo.use()
                    self._ctx.clear(0.0, 0.0, 0.0, 1.0)
                except Exception:
                    pass

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height
        self._allocate_fbos(width, height)

    def destroy(self) -> None:
        self._release_fbos()
        for p in (self._pass_bright, self._pass_blur_h, self._pass_blur_v, self._pass_comp):
            try:
                p.release()
            except Exception:
                pass
