"""Base helpers for post-process drop-in effects."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import moderngl
import numpy as np


class PostFxEffect(Protocol):
    """Protocol for drop-in post-process effects."""

    NAME: str

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
        ...

    def resize(self, width: int, height: int) -> None:
        ...

    def destroy(self) -> None:
        ...


@dataclass(slots=True)
class FullscreenPass:
    """Reusable fullscreen quad shader pass."""

    prog: moderngl.Program
    vao: moderngl.VertexArray
    vbo: moderngl.Buffer

    @classmethod
    def build(cls, ctx: moderngl.Context, fragment_shader: str) -> FullscreenPass:
        vert = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() {
    v_uv = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""
        prog = ctx.program(vertex_shader=vert, fragment_shader=fragment_shader)
        verts = np.array([-1, -1, -1, 1, 1, -1, 1, 1], dtype=np.float32)
        vbo = ctx.buffer(verts)
        vao = ctx.vertex_array(prog, [(vbo, '2f', 'in_vert')])
        return cls(prog=prog, vao=vao, vbo=vbo)

    def release(self) -> None:
        self.vao.release()
        self.vbo.release()
        self.prog.release()
