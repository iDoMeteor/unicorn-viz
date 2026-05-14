"""Film grain + dither post-process effect."""
from __future__ import annotations

import logging

import moderngl

from base import FullscreenPass

log = logging.getLogger(__name__)


class FilmGrainDither:
    """Apply animated grain and subtle ordered dithering."""

    NAME = 'Film Grain + Dither'

    def __init__(self, ctx: moderngl.Context, width: int, height: int) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._t = 0.0
        self._pass = FullscreenPass.build(
            ctx,
            """
#version 330
uniform sampler2D tex;
uniform vec2 uResolution;
uniform float uTime;
uniform float uGrain;
uniform float uDither;
in vec2 v_uv;
out vec4 fragColor;

float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

float bayer4(vec2 p) {
    ivec2 ip = ivec2(mod(p, 4.0));
    int x = ip.x;
    int y = ip.y;
    int idx = x + y * 4;
    float tbl[16] = float[16](
        0.0, 8.0, 2.0, 10.0,
        12.0, 4.0, 14.0, 6.0,
        3.0, 11.0, 1.0, 9.0,
        15.0, 7.0, 13.0, 5.0
    );
    return (tbl[idx] / 16.0) - 0.5;
}

void main() {
    vec3 c = texture(tex, v_uv).rgb;
    vec2 px = v_uv * uResolution;

    // Create blocky grain by scaling pixel coordinates down (block size ~6-8 pixels).
    // Divide by 6.5 to create larger, retro-style grain blocks.
    vec2 grain_px = floor(px / 6.5);
    
    // Apply grain with strong amplification (4.8x) for retro impact.
    float n = hash12(grain_px + vec2(uTime * 91.7, uTime * 37.1)) - 0.5;
    c += n * uGrain * 4.8;

    // Re-introduce blocky ordered dither so uDither remains active and
    // contributes to the retro look.
    float d = bayer4(grain_px);
    c += d * uDither * 2.8;

    // Boost contrast for punchier, more vibrant grain.
    // Apply mild S-curve to enhance mid-tones while preserving blacks/whites.
    vec3 contracted = c * c * (3.0 - 2.0 * c);
    c = mix(c, contracted, 0.25);

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
        self._t += dt
        dst_fbo.use()
        w, h = dst_fbo.size
        self._ctx.viewport = (0, 0, w, h)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        src_tex.use(location=0)
        self._pass.prog['tex'].value = 0
        self._pass.prog['uResolution'].value = (float(w), float(h))
        self._pass.prog['uTime'].value = self._t
        s = max(0.0, min(1.0, float(strength)))
        grain_val = (0.065 + beat * 0.035 + treble * 0.025) * (0.50 + 0.50 * s)
        dither_val = (0.028 + treble * 0.014) * (0.50 + 0.50 * s)
        log.info('FilmGrainDither firing: strength=%.2f grain=%.4f dither=%.4f', s, grain_val, dither_val)
        self._pass.prog['uGrain'].value = grain_val
        self._pass.prog['uDither'].value = dither_val
        self._pass.vao.render(moderngl.TRIANGLE_STRIP)

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def reset(self) -> None:
        """Reset grain animation on effect trigger."""
        self._t = 0.0

    def destroy(self) -> None:
        self._pass.release()
