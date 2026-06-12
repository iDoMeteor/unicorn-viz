"""
Vector — classic demoscene spinning wireframe polyhedra.

Renders up to three simultaneously rotating 3-D shapes (cube, octahedron,
icosahedron) as line-segments with a neon colour scheme.

Audio reactivity:
  - bass  → rotation speed + edge glow brightness
  - beat  → shape swap / colour palette burst
  - mid   → secondary tilt axis speed

All geometry is built in Python once at init; every frame only the
4×4 MVP matrix uniform is updated, keeping the render path light.
"""
from __future__ import annotations

import math
import numpy as np
import moderngl

from unicornviz.effects.base import BaseEffect, AudioData

# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _cube_edges() -> np.ndarray:
    """Return (N,6) float32 array of line segment endpoints for a unit cube."""
    v = np.array([
        [-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],
        [-1,-1, 1],[1,-1, 1],[1,1, 1],[-1,1, 1],
    ], dtype=np.float32)
    edges = [
        (0,1),(1,2),(2,3),(3,0),  # back face
        (4,5),(5,6),(6,7),(7,4),  # front face
        (0,4),(1,5),(2,6),(3,7),  # connecting edges
    ]
    return np.array([[*v[a], *v[b]] for a,b in edges], dtype=np.float32)


def _octa_edges() -> np.ndarray:
    """Unit octahedron."""
    r2 = math.sqrt(2.0)
    v = np.array([
        [0, 1, 0],[0,-1, 0],
        [1, 0, 0],[-1,0, 0],
        [0, 0, 1],[0, 0,-1],
    ], dtype=np.float32)
    edges = [
        (0,2),(0,3),(0,4),(0,5),
        (1,2),(1,3),(1,4),(1,5),
        (2,4),(4,3),(3,5),(5,2),
    ]
    return np.array([[*v[a], *v[b]] for a,b in edges], dtype=np.float32)


def _icosa_edges() -> np.ndarray:
    """Unit icosahedron (20 triangles → 30 unique edges)."""
    phi = (1.0 + math.sqrt(5.0)) / 2.0
    raw = [
        (-1, phi, 0),(1, phi, 0),(-1,-phi, 0),(1,-phi, 0),
        (0, -1, phi),(0,  1, phi),(0, -1,-phi),(0,  1,-phi),
        (phi, 0,-1),(phi, 0, 1),(-phi, 0,-1),(-phi, 0, 1),
    ]
    verts = np.array(raw, dtype=np.float32)
    # Normalize to unit sphere
    verts /= np.linalg.norm(verts[0])

    faces = [
        (0,11,5),(0,5,1),(0,1,7),(0,7,10),(0,10,11),
        (1,5,9),(5,11,4),(11,10,2),(10,7,6),(7,1,8),
        (3,9,4),(3,4,2),(3,2,6),(3,6,8),(3,8,9),
        (4,9,5),(2,4,11),(6,2,10),(8,6,7),(9,8,1),
    ]
    seen: set[tuple[int,int]] = set()
    lines = []
    for tri in faces:
        for i in range(3):
            a, b = tri[i], tri[(i+1)%3]
            key = (min(a,b), max(a,b))
            if key not in seen:
                seen.add(key)
                lines.append([*verts[a], *verts[b]])
    return np.array(lines, dtype=np.float32)


# Shapes list: each entry is (edge_array, colour_rgb, base_scale)
_SHAPES = [
    (_cube_edges,    (0.2, 0.8, 1.0), 0.85),   # cyan cube
    (_octa_edges,    (1.0, 0.3, 0.8), 1.0),    # magenta octahedron
    (_icosa_edges,   (0.3, 1.0, 0.4), 0.80),   # green icosahedron
]

# ---------------------------------------------------------------------------
# Shaders
# ---------------------------------------------------------------------------

_VERT = """
#version 330
in  vec3 in_pos;
in  float in_phase;
in  float in_edge;
uniform mat4 uMVP;
uniform float uScale;
out float v_phase;
out float v_edge;
void main() {
    gl_Position = uMVP * vec4(in_pos * uScale, 1.0);
    v_phase = in_phase;
    v_edge = in_edge;
}
"""

_FRAG = """
#version 330
uniform vec3  uColor;
uniform float uBrightness;
uniform float uTime;
uniform float uSparkle;
uniform float uRacerPos;
uniform float uRacerGlow;
in float v_phase;
in float v_edge;
out vec4 fragColor;

float hash(vec2 p) {
    p = fract(p * vec2(127.1, 311.7));
    p += dot(p, p + 19.19);
    return fract(p.x * p.y);
}

void main() {
    vec3 col = uColor * uBrightness;

    // Subtle sparkle touches: occasional pixel glints on wire edges.
    float spark = step(0.997, hash(floor(gl_FragCoord.xy * 0.35) + floor(uTime * 10.0)));
    col += vec3(1.0, 0.95, 0.85) * spark * uSparkle;

    // Edge racers: layered beads that run both directions along each wire.
    float racer_head_a = fract(uRacerPos + v_edge * 0.6180339);
    float racer_head_b = fract(1.0 - uRacerPos * 0.73 + v_edge * 0.4142136);

    float d_a = abs(v_phase - racer_head_a);
    d_a = min(d_a, 1.0 - d_a);
    float d_b = abs(v_phase - racer_head_b);
    d_b = min(d_b, 1.0 - d_b);

    float racer_a = smoothstep(0.18, 0.0, d_a);
    float racer_b = smoothstep(0.14, 0.0, d_b);
    float tail_a = smoothstep(0.40, 0.0, d_a) * 0.30;
    float tail_b = smoothstep(0.34, 0.0, d_b) * 0.22;
    vec3 racer_col_a = mix(vec3(0.96, 0.99, 1.0), uColor, 0.22);
    vec3 racer_col_b = mix(uColor, vec3(1.0, 0.85, 0.95), 0.35);
    float flicker = 0.78 + 0.22 * sin(uTime * 12.0 + v_edge * 19.0);
    col += racer_col_a * (racer_a + tail_a) * uRacerGlow * flicker;
    col += racer_col_b * (racer_b + tail_b) * (uRacerGlow * 0.72) * (1.1 - 0.2 * flicker);

    float edge_pulse = 0.12 + 0.08 * sin(uTime * 7.0 + v_edge * 13.0);
    col += uColor * edge_pulse * uRacerGlow * 0.35;

    fragColor = vec4(col, 1.0);
}
"""


def _rot_x(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[1,0,0,0],[0,c,-s,0],[0,s,c,0],[0,0,0,1]], dtype=np.float32)


def _rot_y(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c,0,s,0],[0,1,0,0],[-s,0,c,0],[0,0,0,1]], dtype=np.float32)


def _rot_z(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c,-s,0,0],[s,c,0,0],[0,0,1,0],[0,0,0,1]], dtype=np.float32)


def _perspective(fov: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(fov * 0.5)
    return np.array([
        [f/aspect, 0,  0,                         0],
        [0,        f,  0,                         0],
        [0,        0,  (far+near)/(near-far),     -1],
        [0,        0,  (2*far*near)/(near-far),    0],
    ], dtype=np.float32)


def _translate_z(z: float) -> np.ndarray:
    m = np.eye(4, dtype=np.float32)
    m[2, 3] = z
    return m


class Vector(BaseEffect):
    """Spinning wireframe polyhedra — classic demoscene vector style."""

    NAME = "Vector"
    AUTHOR = "unicorn-viz"
    TAGS = ["classic", "demoscene", "3d", "audio"]
    PING_PONG_FRIENDS = ['3D Cube']

    def _init(self) -> None:
        self.parameters = {"speed": float(self.config.get("speed", 1.0))}
        self._prog = self._make_program(_VERT, _FRAG)
        self._bass = 0.0
        self._beat = 0.0
        self._mid  = 0.0
        self._treble = 0.0
        self._shape_idx = int(self.rng.integers(0, len(_SHAPES)))
        self._rx = float(self.rng.uniform(0.0, math.tau))
        self._ry = float(self.rng.uniform(0.0, math.tau))
        self._rz = float(self.rng.uniform(0.0, math.tau))
        self._rx2 = float(self.rng.uniform(0.0, math.tau))
        self._ry2 = float(self.rng.uniform(0.0, math.tau))

        # Build one VAO per shape; they share the same program
        self._vaos: list[moderngl.VertexArray] = []
        self._vbos: list[moderngl.Buffer] = []
        self._n_lines: list[int] = []
        for (fn, col, scale) in _SHAPES:
            edges = fn()  # Nx6 float32
            n_edges = int(edges.shape[0])
            verts = np.empty((n_edges * 2, 5), dtype=np.float32)
            for i in range(n_edges):
                a = edges[i, 0:3]
                b = edges[i, 3:6]
                edge_id = float(i) / float(max(1, n_edges - 1))
                verts[i * 2 + 0, 0:3] = a
                verts[i * 2 + 0, 3] = 0.0
                verts[i * 2 + 0, 4] = edge_id
                verts[i * 2 + 1, 0:3] = b
                verts[i * 2 + 1, 3] = 1.0
                verts[i * 2 + 1, 4] = edge_id

            vbo = self.ctx.buffer(verts.tobytes())
            vao = self.ctx.vertex_array(
                self._prog, [(vbo, "3f 1f 1f", "in_pos", "in_phase", "in_edge")]
            )
            self._vaos.append(vao)
            self._vbos.append(vbo)
            self._n_lines.append(len(verts))

        aspect = self.width / max(self.height, 1)
        self._proj = _perspective(math.radians(50), aspect, 0.1, 100.0)

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)
        self._bass = audio.bass_n
        self._mid  = audio.mid_n
        self._treble = audio.treble_n
        if audio.beat > 0.5:
            self._beat = 1.0
            self._shape_idx = (self._shape_idx + 1) % len(_SHAPES)
        self._beat = max(0.0, self._beat - dt * 3.5)

        spd = self.parameters["speed"] * (1.0 + self._bass * 0.7)
        self._rx  += dt * spd * 0.7
        self._ry  += dt * spd * 1.1
        self._rz  += dt * spd * 0.4 * (1.0 + self._mid * 0.5)
        self._rx2 += dt * spd * 0.5
        self._ry2 += dt * spd * 0.85

    def render(self) -> None:
        aspect = self.width / max(self.height, 1)
        self._proj = _perspective(math.radians(50), aspect, 0.1, 100.0)

        self.ctx.clear(0.0, 0.0, 0.0, 1.0)
        # line_width > 1 requires GL_LINE_SMOOTH which many Mesa drivers ignore;
        # set it but don't rely on it for visibility
        try:
            self.ctx.line_width = max(1.0, 2.0 + self._beat * 2.0)
        except Exception:
            pass

        # Draw all three shapes simultaneously, spread across the screen
        z_positions = [-2.6, -4.2, -6.8]
        angles = [
            (self._rx,   self._ry,   self._rz),
            (self._rx2,  self._ry,   self._ry2),
            (self._rx,   self._rx2,  self._rz + self._ry2),
        ]

        for idx, ((rx, ry, rz), z_pos) in enumerate(zip(angles, z_positions)):
            _, col, scale = _SHAPES[idx]
            scale_val = scale * (0.8 + self._bass * 0.35 + (0.22 if idx == self._shape_idx else 0.0))

            rot = _rot_x(rx) @ _rot_y(ry) @ _rot_z(rz)
            trans = _translate_z(z_pos)
            mvp = self._proj @ trans @ rot

            bright = 1.0 + self._beat * 0.7 + (0.45 if idx == self._shape_idx else 0.0)
            bright *= 1.0 + self._bass * 0.4

            self._prog["uMVP"].write(mvp.tobytes())
            self._prog["uScale"].value  = scale_val
            self._prog["uColor"].value  = col
            self._prog["uBrightness"].value = bright
            self._prog["uTime"].value = self.time
            self._prog["uSparkle"].value = 0.05 + self._treble * 0.16 + self._beat * 0.12
            self._prog["uRacerPos"].value = (
                self.time * (0.26 + float(self.parameters["speed"]) * 0.24 + self._bass * 0.40)
                + idx * 0.19
            ) % 1.0
            self._prog["uRacerGlow"].value = 0.20 + self._mid * 0.40 + self._beat * 0.35
            self._vaos[idx].render(moderngl.LINES, vertices=self._n_lines[idx])

    def destroy(self) -> None:
        for vao in self._vaos:
            vao.release()
        for vbo in self._vbos:
            vbo.release()
        self._prog.release()
