"""Temporal feedback trail post-process effect."""
from __future__ import annotations

import math

import moderngl

from base import FullscreenPass


class TemporalFeedbackTrail:
    """Blend current frame with decayed previous frame for trailing echoes."""

    NAME = 'Temporal Feedback Trail'

    def __init__(self, ctx: moderngl.Context, width: int, height: int) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._feedback_fbo: moderngl.Framebuffer | None = None
        self._copy_pass = FullscreenPass.build(
            ctx,
            """
#version 330
uniform sampler2D tex;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    fragColor = texture(tex, v_uv);
}
""",
        )
        self._blend_pass = FullscreenPass.build(
            ctx,
            """
#version 330
uniform sampler2D tex_current;
uniform sampler2D tex_history;
uniform float uDecay;
uniform float uBeatBoost;
uniform vec2 uHistoryOffset;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    vec3 cur = texture(tex_current, v_uv).rgb;
    vec3 hist = texture(tex_history, clamp(v_uv - uHistoryOffset, 0.0, 1.0)).rgb;
    float decay = clamp(uDecay - uBeatBoost, 0.45, 0.95);
    vec3 outc = mix(cur, hist, decay);
    // Mild highlight push to keep trails vibrant.
    outc += max(vec3(0.0), hist - cur) * 0.22;
    fragColor = vec4(clamp(outc, 0.0, 1.0), 1.0);
}
""",
        )
        self._history_valid = False
        self._phase = 0.0
        self._ensure_feedback_fbo(width, height)

    def _ensure_feedback_fbo(self, width: int, height: int) -> None:
        if self._feedback_fbo is not None:
            tex = self._feedback_fbo.color_attachments[0]
            if tex.size == (width, height):
                return
            self._feedback_fbo.release()
            tex.release()
        tex = self._ctx.texture((width, height), 4)
        tex.filter = moderngl.LINEAR, moderngl.LINEAR
        self._feedback_fbo = self._ctx.framebuffer(color_attachments=[tex])
        self._feedback_fbo.use()
        self._ctx.viewport = (0, 0, width, height)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)

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
        width, height = dst_fbo.size
        self._ensure_feedback_fbo(width, height)
        self._phase += dt

        # Prime history from the first frame after reset/resize to avoid
        # flashing stale texture content from a previous scene/effect.
        if not self._history_valid:
            dst_fbo.use()
            self._ctx.viewport = (0, 0, width, height)
            self._ctx.clear(0.0, 0.0, 0.0, 1.0)
            src_tex.use(location=0)
            self._copy_pass.prog['tex'].value = 0
            self._copy_pass.vao.render(moderngl.TRIANGLE_STRIP)

            self._feedback_fbo.use()
            self._ctx.viewport = (0, 0, width, height)
            self._ctx.clear(0.0, 0.0, 0.0, 1.0)
            dst_fbo.color_attachments[0].use(location=0)
            self._copy_pass.prog['tex'].value = 0
            self._copy_pass.vao.render(moderngl.TRIANGLE_STRIP)
            self._history_valid = True
            return

        # Blend current + history into dst
        dst_fbo.use()
        self._ctx.viewport = (0, 0, width, height)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        src_tex.use(location=0)
        self._feedback_fbo.color_attachments[0].use(location=1)
        self._blend_pass.prog['tex_current'].value = 0
        self._blend_pass.prog['tex_history'].value = 1
        s = max(0.0, min(1.0, float(strength)))
        decay = 0.70 + 0.23 * s + min(0.08, bass * 0.06 + mid * 0.04)
        self._blend_pass.prog['uDecay'].value = max(0.45, min(0.96, decay))
        self._blend_pass.prog['uBeatBoost'].value = min(0.30, beat * (0.22 + 0.20 * s))
        self._blend_pass.prog['uHistoryOffset'].value = (
            0.004 * s * (0.6 + 0.4 * abs(math.sin(self._phase * 2.2))),
            0.003 * s * (0.6 + 0.4 * abs(math.cos(self._phase * 1.7))),
        )
        self._blend_pass.vao.render(moderngl.TRIANGLE_STRIP)

        # Copy output to feedback buffer for next frame.
        self._feedback_fbo.use()
        self._ctx.viewport = (0, 0, width, height)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        dst_fbo.color_attachments[0].use(location=0)
        self._copy_pass.prog['tex'].value = 0
        self._copy_pass.vao.render(moderngl.TRIANGLE_STRIP)

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height
        self._ensure_feedback_fbo(width, height)
        self._history_valid = False

    def reset(self) -> None:
        """Reset temporal history (used when switching slots/effects)."""
        self._history_valid = False
        if self._feedback_fbo is not None:
            self._feedback_fbo.use()
            self._ctx.viewport = (0, 0, self._width, self._height)
            self._ctx.clear(0.0, 0.0, 0.0, 1.0)

    def destroy(self) -> None:
        if self._feedback_fbo is not None:
            tex = self._feedback_fbo.color_attachments[0]
            self._feedback_fbo.release()
            tex.release()
            self._feedback_fbo = None
        self._copy_pass.release()
        self._blend_pass.release()
