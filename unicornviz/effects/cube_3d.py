"""
Cube 3D — a solid neon-coloured rotating cube with Phong shading.

Each face has its own saturated colour.  The cube rotates continuously;
beats trigger a punch-zoom and temporary colour palette shift.

Audio reactivity:
  - bass  → scale pulse + specular intensity
  - beat  → punch-zoom + hue rotate
  - mid   → secondary wobble axis
"""
from __future__ import annotations

import math
import numpy as np
import moderngl

from unicornviz.effects.base import BaseEffect, AudioData

# ---------------------------------------------------------------------------
# Geometry: unit cube, per-face colours
# ---------------------------------------------------------------------------
# 6 faces × 2 tris × 3 verts each = 36 verts
# Attributes per vertex: position(3) + normal(3) + face_color(3) = 9 floats

_FACE_COLORS = [
    (0.0, 0.8, 1.0),   # +Z  cyan
    (1.0, 0.2, 0.8),   # -Z  magenta
    (0.2, 1.0, 0.3),   # +Y  green
    (1.0, 0.6, 0.0),   # -Y  orange
    (0.8, 0.1, 1.0),   # +X  purple
    (1.0, 0.9, 0.0),   # -X  yellow
]

def _build_cube() -> np.ndarray:
    """Return (36, 9) float32 vertex array: pos, normal, colour per vertex."""
    # Each face: corner vertices, outward normal, colour
    faces_data = [
        # pos1, pos2, pos3, pos4 (CCW from outside), normal, color_idx
        ([ 1,-1, 1],[ 1, 1, 1],[-1, 1, 1],[-1,-1, 1], [ 0, 0, 1], 0),  # +Z
        ([-1,-1,-1],[-1, 1,-1],[ 1, 1,-1],[ 1,-1,-1], [ 0, 0,-1], 1),  # -Z
        ([-1, 1,-1],[-1, 1, 1],[ 1, 1, 1],[ 1, 1,-1], [ 0, 1, 0], 2),  # +Y
        ([ 1,-1,-1],[ 1,-1, 1],[-1,-1, 1],[-1,-1,-1], [ 0,-1, 0], 3),  # -Y
        ([ 1,-1,-1],[ 1, 1,-1],[ 1, 1, 1],[ 1,-1, 1], [ 1, 0, 0], 4),  # +X
        ([-1,-1, 1],[-1, 1, 1],[-1, 1,-1],[-1,-1,-1], [-1, 0, 0], 5),  # -X
    ]
    verts = []
    for p0, p1, p2, p3, normal, ci in faces_data:
        col = _FACE_COLORS[ci]
        # Two triangles: (p0,p1,p2) and (p0,p2,p3)
        for p in [p0, p1, p2, p0, p2, p3]:
            verts.extend([*p, *normal, *col])
    return np.array(verts, dtype=np.float32)


_CUBE_DATA = _build_cube()

# ---------------------------------------------------------------------------
# Shaders
# ---------------------------------------------------------------------------

_VERT = """
#version 330
in  vec3 in_pos;
in  vec3 in_normal;
in  vec3 in_color;

uniform mat4 uMVP;
uniform mat4 uModel;

out vec3 v_normal;
out vec3 v_world;
out vec3 v_color;

void main() {
    vec4 world = uModel * vec4(in_pos, 1.0);
    v_world  = world.xyz;
    v_normal = mat3(uModel) * in_normal;
    v_color  = in_color;
    gl_Position = uMVP * vec4(in_pos, 1.0);
}
"""

_FRAG = """
#version 330
in  vec3 v_normal;
in  vec3 v_world;
in  vec3 v_color;

uniform vec3  uLightDir;
uniform float uSpecPow;
uniform float uBass;
uniform float uBeat;
uniform float uHueShift;

out vec4 fragColor;

vec3 hueShift(vec3 col, float shift) {
    float angle = shift * 6.28318;
    vec3  k = vec3(0.577);
    float cosA = cos(angle);
    return col * cosA + cross(k, col) * sin(angle) + k * dot(k, col) * (1.0 - cosA);
}

void main() {
    vec3 N = normalize(v_normal);
    vec3 L = normalize(uLightDir);
    vec3 V = normalize(-v_world);
    vec3 H = normalize(L + V);

    float diff = max(dot(N, L), 0.0) * 0.8 + 0.25;   // ambient + diffuse
    float spec = pow(max(dot(N, H), 0.0), uSpecPow) * (0.4 + uBass * 0.6);

    vec3 col = v_color * diff;
    col += vec3(1.0) * spec;
    col  = hueShift(col, uHueShift);
    col *= 1.0 + uBeat * 0.4;

    fragColor = vec4(clamp(col, 0.0, 1.5), 1.0);
}
"""


def _rot_x(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[1,0,0,0],[0,c,-s,0],[0,s,c,0],[0,0,0,1]], dtype=np.float32)


def _rot_y(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c,0,s,0],[0,1,0,0],[-s,0,c,0],[0,0,0,1]], dtype=np.float32)


def _perspective(fov: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(fov * 0.5)
    return np.array([
        [f/aspect, 0,  0,                      0],
        [0,        f,  0,                      0],
        [0,        0,  (far+near)/(near-far),  -1],
        [0,        0,  (2*far*near)/(near-far), 0],
    ], dtype=np.float32)


class Cube3D(BaseEffect):
    """Solid neon cube with Phong shading and audio reactivity."""

    NAME = "3D Cube"
    AUTHOR = "unicorn-viz"
    TAGS = ["classic", "3d", "audio"]
    PING_PONG_FRIENDS = ['Vector', 'Disco Ball']

    def _init(self) -> None:
        self.parameters = {"speed": float(self.config.get("speed", 1.0))}
        self._prog = self._make_program(_VERT, _FRAG)

        vbo = self.ctx.buffer(_CUBE_DATA.tobytes())
        self._vao = self.ctx.vertex_array(
            self._prog,
            [(vbo, "3f 3f 3f", "in_pos", "in_normal", "in_color")],
        )
        self._vbo = vbo

        self._rx   = float(self.rng.uniform(0.0, math.tau))
        self._ry   = float(self.rng.uniform(0.0, math.tau))
        self._bass = 0.0
        self._beat = 0.0
        self._hue  = float(self.rng.uniform(0.0, 1.0))

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass_n
        if audio.beat > 0.5:
            self._beat = 1.0
            self._hue += 0.15
        self._beat = max(0.0, self._beat - dt * 4.0)

        spd = self.parameters["speed"] * (1.0 + self._bass * 0.5)
        self._rx += dt * spd * 0.45 + dt * audio.mid_n * 0.18
        self._ry += dt * spd * 0.70

    def render(self) -> None:
        aspect = self.width / max(self.height, 1)
        proj = _perspective(math.radians(40), aspect, 0.1, 100.0)

        scale = 1.0 + self._bass * 0.25 + self._beat * 0.12
        model = _rot_x(self._rx) @ _rot_y(self._ry)
        # Apply scale into model matrix
        s = np.eye(4, dtype=np.float32)
        s[0,0] = s[1,1] = s[2,2] = scale

        # Translate into view
        t = np.eye(4, dtype=np.float32)
        t[2, 3] = -4.5  # push back a bit further so it fills 4K nicely

        model_t = t @ s @ model
        mvp = proj @ model_t

        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.clear(0.0, 0.0, 0.0, 1.0, depth=1.0)

        # Use direct row-major byte layout expected by moderngl uniform writer.
        self._prog["uMVP"].write(mvp.tobytes())
        self._prog["uModel"].write(model_t.tobytes())
        self._prog["uLightDir"].value = (0.6, 0.8, 0.5)
        self._prog["uSpecPow"].value  = 32.0
        self._prog["uBass"].value     = self._bass
        self._prog["uBeat"].value     = self._beat
        self._prog["uHueShift"].value = self._hue % 1.0

        self._vao.render(moderngl.TRIANGLES)
        self.ctx.disable(moderngl.DEPTH_TEST)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
