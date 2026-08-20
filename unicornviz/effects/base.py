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
``bass_det``  float            Detector-facing bass level -- same pre-curve input as
                               ``bass`` but a gain tuned for dynamic range, not visual
                               saturation. Not consumed by effects.
``mid_det``   float            Detector-facing mid level (currently same gain as ``mid``)
``treble_det`` float           Detector-facing treble level (currently same gain as ``treble``)
``bass_n``    float            Bass  energy, independently z-score normalised to 0–1
``mid_n``     float            Mid   energy, independently z-score normalised to 0–1
``treble_n``  float            Treble energy, independently z-score normalised to 0–1
``beat``      float            1.0 when a beat onset is detected, else 0.0
``bpm``       float            Estimated BPM (not yet implemented: fixed 120)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import moderngl


__all__ = ['BaseEffect', 'AudioData']


class AudioData:
    """Snapshot of audio state passed to effects each frame."""

    __slots__ = ("fft", "waveform", "bass", "mid", "treble",
                 "bass_det", "mid_det", "treble_det",
                 "bass_n", "mid_n", "treble_n",
                 "beat", "bpm", "bass_flux", "mid_flux",
                 "bass_level_raw",
                 "bands", "spectral_flux",
                 "vocal_hnr", "vocal_fmr")

    def __init__(self) -> None:
        self.fft: np.ndarray = np.zeros(512, dtype=np.float32)
        self.waveform: np.ndarray = np.zeros(512, dtype=np.float32)
        self.bass: float = 0.0
        self.mid: float = 0.0
        self.treble: float = 0.0
        # 2026-08-11: detector-facing counterparts of bass/mid/treble --
        # same pre-curve (profile-weighted) input, run through
        # unicornviz.audio.analyzer._shape() with a gain chosen for
        # dynamic range rather than visual saturation. Added because
        # bass/mid/treble's gains (6.6/5.8/7.2) are tuned for effects
        # (which want to read as "alive" even when quiet) and, verified
        # against real session data, leave *bass* specifically pegged near
        # ceiling almost always (median 0.97-0.98 across every director
        # mode, including BREAKDOWN) -- a signal the detector's z-score
        # normalizer was silently compensating for. mid/treble's existing
        # gains were checked the same way and found already well-tuned
        # (best achievable cross-mode separation *is* their current gain),
        # so bass_det uses a new, lower gain while mid_det/treble_det
        # currently just mirror mid/treble's existing gains -- kept as
        # separate fields anyway so either can be retuned independently
        # later without another round of plumbing. Effects do not consume
        # these; only drop-ins/auto-vj-01/beat_grid.py's z-score inputs do.
        # See docs/planning/auto-vj-drop-score-redesign-plan-2026-08-11.md.
        self.bass_det: float = 0.0
        self.mid_det: float = 0.0
        self.treble_det: float = 0.0
        # Per-band running z-score normalised values.  Each band is normalised
        # independently against its own recent mean/variance so the signal
        # always spans 0–1 regardless of absolute loudness.  Useful for effects
        # and beat detection that want "is this band MORE active than usual".
        self.bass_n: float = 0.5
        self.mid_n: float = 0.5
        self.treble_n: float = 0.5
        self.beat: float = 0.0
        self.bpm: float = 120.0
        self.bass_flux: float = 0.0
        self.mid_flux: float = 0.0
        # 2026-08-18 (drop-score redesign, audit F1): raw-path bass LEVEL.
        # bass/bass_det/bass_n are all derived from the spectrum AFTER it
        # is divided by its own per-frame maximum, which turns them into
        # spectral-shape fractions — absolute level information is gone
        # before any gain curve touches them (the same lesson flux learned:
        # see the analyzer's "raw spectrum, BEFORE per-frame normalization"
        # comment). This field is log1p of the profile-weighted raw bass-band
        # mean, no per-frame normalization and no _shape() curve, so a held
        # drop reads loud for its whole duration and a breakdown genuinely
        # reads quiet. Unbounded (log-magnitude units, not 0..1); consumers
        # normalize against their own slow reference (see BeatTracker's
        # drop-sustain primitive in drop-ins/auto-vj-01/beat_grid.py).
        # Effects should keep reading bass/bass_n; this is detector-facing.
        self.bass_level_raw: float = 0.0
        # 64 log-spaced perceptual bands (30 Hz – 16 kHz, raw, no visual gain).
        # Computed once per frame in the Analyzer; shared by effects and auto-VJ.
        self.bands: np.ndarray = np.zeros(64, dtype=np.float32)
        # Overall gated spectral flux scalar from the Analyzer (same value used
        # for onset detection, exposed here for recommender / corpus logging).
        self.spectral_flux: float = 0.0
        # Vocal-presence heuristics (Auto VJ profile recommender only; not
        # audio-reactive parameters for effects). Neither is a true vocal
        # detector -- they measure acoustic properties real singing/rapping
        # tends to have, and can false-positive on any harmonically pitched,
        # syllabically-modulated source (e.g. a synth lead with vibrato).
        # vocal_hnr: 0-1 harmonic-to-noise-ratio proxy in the vocal-formant
        #   band (300 Hz-3.4 kHz) -- how strongly periodic/harmonic that
        #   band's spectral shape is this frame. High for voice or any
        #   pitched tone; low for noise-like/percussive content.
        self.vocal_hnr: float = 0.0
        # vocal_fmr: 0-1 formant modulation rate -- fraction of the vocal
        #   band's energy envelope modulation concentrated in 3-8 Hz
        #   (syllabic/vibrato rate), tracked over a ~2s rolling window and
        #   updated periodically (not every frame). High for sung/spoken
        #   delivery; low for a sustained pad or a one-shot hit.
        self.vocal_fmr: float = 0.0


def copy_audio_data(source: AudioData, target: AudioData, *, scale: float = 1.0) -> None:
    """Copy every ``AudioData`` field from *source* into *target* in-place.

    No allocation -- array fields are copied via ``[:] =``, scalars via
    plain assignment. This is the single source of truth for ``AudioData``'s
    full field list; every call site that used to hand-write its own copy of
    this list (``AudioManager._copy_audio_into``, ``App._fill_audio_scratch``)
    now delegates here instead, after the same "new field silently dropped
    at one of two copy sites" bug (``vocal_hnr``/``vocal_fmr``, then
    ``data.bpm`` never even being *produced* in the first place) showed up
    twice in one day -- see docs/adr/vj-system.md (auto-vj-01) "Vocal-
    Presence Core Bug" and the follow-up entry for the second occurrence.

    ``scale`` != ``1.0`` additionally clamps the scaled "level" fields
    (``bass``/``mid``/``treble``/``fft``) to ``[0, 1]`` -- matches the old
    ``_fill_audio_scratch`` reactivity-override behavior. Every other field
    is reactivity-invariant by design and copied through unscaled regardless
    of ``scale``.
    """
    if scale == 1.0:
        target.bass = source.bass
        target.mid = source.mid
        target.treble = source.treble
        target.fft[:] = source.fft
    else:
        target.bass = min(1.0, source.bass * scale)
        target.mid = min(1.0, source.mid * scale)
        target.treble = min(1.0, source.treble * scale)
        np.multiply(source.fft, scale, out=target.fft)
        np.clip(target.fft, 0.0, 1.0, out=target.fft)
    target.bass_det = source.bass_det
    target.mid_det = source.mid_det
    target.treble_det = source.treble_det
    target.bass_n = source.bass_n
    target.mid_n = source.mid_n
    target.treble_n = source.treble_n
    target.beat = source.beat
    target.bpm = source.bpm
    target.bass_flux = source.bass_flux
    target.mid_flux = source.mid_flux
    target.bass_level_raw = source.bass_level_raw
    target.spectral_flux = source.spectral_flux
    target.vocal_hnr = source.vocal_hnr
    target.vocal_fmr = source.vocal_fmr
    target.waveform[:] = source.waveform
    target.bands[:] = source.bands


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
    # When False, the effect is excluded from all auto-rotation (playlist
    # advance/random, Auto VJ, ping-pong) — it is reached only by manual
    # activation (effects browser, numeric pin, direct jump). Default True.
    AUTO_ROTATE: bool = True

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
        # Candy Frame integration flags (read from per-effect config).
        # scale_when_framed defaults to True so framed rendering scales effects by default.
        # candy_frame_disallow is retained for compatibility with older effect configs.
        self.scale_when_framed: bool = bool(self.config.get('scale_when_framed', True))
        self.candy_frame_disallow: bool = bool(self.config.get('candy_frame_disallow', False))
        self._init()
        # Snapshot defaults so G can reset speed (and others) to initial values.
        self._initial_parameters: dict[str, float] = dict(self.parameters)

    # ------------------------------------------------------------------ #
    # Subclass interface                                                   #
    # ------------------------------------------------------------------ #

    #: True while this effect is part of a running scene crossfade.
    #:
    #: Set by the app on both the outgoing and incoming effect for the
    #: duration of the blend.  During a crossfade two effects render every
    #: frame, so it is the worst possible moment for an effect to do
    #: something expensive and deferrable — notably a shader compile.
    #: Effects that have such work can check this and postpone it; most
    #: effects can ignore it entirely.
    transition_active: bool = False

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

        Not currently reached: nothing in the runtime calls this hook, and no
        caller populates the ``_midi_cc_map`` it reads.  Live CC handling runs
        through ``HotkeyHandler._dispatch_midi_event`` instead.  The hook is kept
        for effect authors, and shares ``CC_PARAM_RANGE`` with that path so an
        override behaves identically if it is ever wired up.
        """
        if event.type == "cc":
            # Try to find a matching parameter by name from the app-injected map
            param_name = getattr(self, "_midi_cc_map", {}).get(event.number)
            if param_name and param_name in self.parameters:
                # Imported here, not at module scope: a module-level import would
                # pull rtmidi into every effect import for a hook that only runs
                # when an effect author wires it up.
                from unicornviz.midi import CC_PARAM_RANGE  # noqa: PLC0415
                lo, hi = CC_PARAM_RANGE
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
