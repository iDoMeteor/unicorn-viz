"""
Effect base classes and shared data types.

Every visual effect is a subclass of ``BaseEffect``.  The registry
(``effects/registry.py``) discovers all subclasses automatically at import
time, so adding a new effect is as simple as creating a new ``.py`` file in
the ``effects/`` directory.

Implementing a new effect
--------------------------
1. Create ``unicornviz/effects/my_effect.py``.
2. Subclass ``BaseEffect`` and set the ``NAME`` class attribute.
3. Override ``_init()`` to allocate GL resources (shaders, VBOs, textures).
4. Override ``render()`` to draw to the currently bound FBO.
5. Optionally override ``update(dt, audio)`` for per-frame state updates.
6. Optionally override ``destroy()`` to release GL resources on teardown.

Example::

    class MyEffect(BaseEffect):
        NAME   = "My Effect"
        AUTHOR = "your handle"
        TAGS   = ["audio", "futuristic"]

        def _init(self) -> None:
            self._prog = self._make_program(VERT_SRC, FRAG_SRC)
            self._vao, self._vbo = self._fullscreen_quad()

        def update(self, dt: float, audio: AudioData) -> None:
            super().update(dt, audio)          # ticks self.time
            self._bass = audio.bass

        def render(self) -> None:
            self._prog["iTime"].value = self.time
            self._prog["iBass"].value = self._bass
            self._vao.render(moderngl.TRIANGLE_STRIP)

        def destroy(self) -> None:
            self._vao.release()
            self._vbo.release()
            self._prog.release()

Helper methods provided by BaseEffect
--------------------------------------
``_fullscreen_quad()``        Returns ``(VAO, VBO)`` covering ``[-1, 1]²``.
                               Requires ``self._prog`` to be set first.
``_make_program(vert, frag)``  Compiles and links a GLSL program.

AudioData slots
---------------
``fft``       np.float32[512]  Smoothed FFT magnitude spectrum (0–1 each band)
``waveform``  np.float32[512]  Normalised PCM waveform snapshot
``bass``      float            Averaged low-band energy  (0–1, may exceed 1)
``mid``       float            Averaged mid-band energy
``treble``    float            Averaged high-band energy
``beat``      float            1.0 when a beat onset is detected, else 0.0
``bpm``       float            Estimated BPM (not yet implemented: fixed 120)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import moderngl


class AudioData:
    """Snapshot of audio state passed to effects each frame."""

    __slots__ = ("fft", "waveform", "bass", "mid", "treble", "beat", "bpm",
                 "bass_flux", "mid_flux")

    def __init__(self) -> None:
        self.fft: np.ndarray = np.zeros(512, dtype=np.float32)
        self.waveform: np.ndarray = np.zeros(512, dtype=np.float32)
        self.bass: float = 0.0
        self.mid: float = 0.0
        self.treble: float = 0.0
        self.beat: float = 0.0
        self.bpm: float = 120.0
        self.bass_flux: float = 0.0
        self.mid_flux: float = 0.0


class BaseEffect(ABC):
    """
    All effects subclass this.

    Lifecycle:
        __init__(ctx, width, height, config)  — called once at startup
        resize(width, height)                 — called on window resize
        update(dt, audio)                     — called every frame before render
        render()                              — draw to currently bound FBO
        destroy()                             — release GL resources

    Metadata class attributes:
        NAME    — display name shown in overlay
        AUTHOR  — optional author credit
        TAGS    — list of strings: 'classic', 'audio', 'ansi', 'futuristic', etc.
    """

    NAME: str = "Effect"
    AUTHOR: str = ""
    TAGS: list[str] = []

    def __init__(
        self,
        ctx: "moderngl.Context",
        width: int,
        height: int,
        config: dict,
    ) -> None:
        self.ctx = ctx
        self.width = width
        self.height = height
        self.config = config
        self.seed: int = int(np.random.SeedSequence().entropy)
        self.rng = np.random.default_rng(self.seed)
        # Start each effect at a different simulation phase so runs are less predictable.
        self.time: float = float(self.rng.uniform(0.0, 10_000.0))
        # Per-effect tweakable parameters (exposed to MIDI mapping)
        self.parameters: dict[str, float] = {}
        self._init()
        # Snapshot defaults so G can reset speed (and others) to initial values.
        self._initial_parameters: dict[str, float] = dict(self.parameters)

    # ------------------------------------------------------------------ #
    # Subclass interface                                                   #
    # ------------------------------------------------------------------ #

    def _init(self) -> None:
        """Override to set up GL resources instead of overriding __init__."""

    @abstractmethod
    def render(self) -> None:
        """Draw the effect to the currently bound FBO."""

    def update(self, dt: float, audio: AudioData) -> None:
        """Advance internal state. Default: tick self.time."""
        self.time += dt

    def resize(self, width: int, height: int) -> None:
        """Handle window resize."""
        self.width = width
        self.height = height

    def destroy(self) -> None:
        """Release any moderngl resources. Override if needed."""

    def on_midi(self, event: "MidiEvent") -> None:  # noqa: F821
        """
        Handle a MIDI event.  Default: map CC numbers to self.parameters
        using the cc_to_param lookup from MidiManager.
        Effects may override to handle additional mappings.
        """
        if event.type == "cc":
            # Try to find a matching parameter by name from the app-injected map
            param_name = getattr(self, "_midi_cc_map", {}).get(event.number)
            if param_name and param_name in self.parameters:
                lo, hi = 0.0, 4.0
                self.parameters[param_name] = lo + event.value * (hi - lo)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _fullscreen_quad(
        self, prog: "moderngl.Program | None" = None
    ) -> tuple["moderngl.VertexArray", "moderngl.Buffer"]:
        """Return a VAO covering [-1,1]² for fullscreen quad rendering.

        If *prog* is None, falls back to ``self._prog`` (single-program effects).
        """
        p = prog if prog is not None else self._prog  # type: ignore[attr-defined]
        vertices = np.array(
            [-1, -1, -1, 1, 1, -1, 1, 1],
            dtype=np.float32,
        )
        vbo = self.ctx.buffer(vertices)
        vao = self.ctx.vertex_array(p, [(vbo, "2f", "in_vert")])
        return vao, vbo

    def _make_program(self, vert_src: str, frag_src: str) -> "moderngl.Program":
        return self.ctx.program(vertex_shader=vert_src, fragment_shader=frag_src)
