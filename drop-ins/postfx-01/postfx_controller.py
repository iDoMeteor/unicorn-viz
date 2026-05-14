"""System-level post-process stack controller drop-in.

Loads post-process effects from effects/ and applies one active effect globally.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import moderngl

_EFFECTS_DIR = Path(__file__).resolve().parent / 'effects'
if str(_EFFECTS_DIR) not in sys.path:
    sys.path.insert(0, str(_EFFECTS_DIR))

from temporal_feedback import TemporalFeedbackTrail
from chromatic_aberration import ChromaticAberration
from film_grain_dither import FilmGrainDither
from lens_distortion_vignette import LensDistortionVignette
from radial_zoom_blur import RadialZoomBlur
from glitch_slices import GlitchSlices

log = logging.getLogger(__name__)


HELP_ENTRIES = [
    ('Post FX', 'Ctrl+Alt+1', 'Temporal Feedback Trail (quick hit)'),
    ('Post FX', 'Ctrl+Alt+2', 'Chromatic Aberration (quick hit)'),
    ('Post FX', 'Ctrl+Alt+3', 'Film Grain + Dither (quick hit)'),
    ('Post FX', 'Ctrl+Alt+4', 'Lens Distortion + Vignette (quick hit)'),
    ('Post FX', 'Ctrl+Alt+5', 'Radial Zoom Blur (quick hit)'),
    ('Post FX', 'Ctrl+Alt+6', 'Glitch Slices (quick hit)'),
    ('Post FX', 'Ctrl+Alt+7-8', 'Reserved quick-hit slots (coming soon)'),
]


class PostFxController:
    """Runtime controller for global post-process effects."""

    SLOT_MAP: tuple[tuple[int, str, bool], ...] = (
        (1, 'Temporal Feedback Trail', True),
        (2, 'Chromatic Aberration', True),
        (3, 'Film Grain + Dither', True),
        (4, 'Lens Distortion + Vignette', True),
        (5, 'Radial Zoom Blur', True),
        (6, 'Glitch Slices', True),
        (7, 'Multi-pass Bloom', False),
        (8, 'Heat Haze Refraction', False),
    )

    def __init__(self, ctx: moderngl.Context, width: int, height: int, cfg: dict | None = None) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._cfg = cfg or {}
        self.enabled = bool(self._cfg.get('enabled', True))

        self._effects: dict[int, object] = {
            1: TemporalFeedbackTrail(ctx, width, height),
            2: ChromaticAberration(ctx, width, height),
            3: FilmGrainDither(ctx, width, height),
            4: LensDistortionVignette(ctx, width, height),
            5: RadialZoomBlur(ctx, width, height),
            6: GlitchSlices(ctx, width, height),
        }
        self._hit_duration = float(self._cfg.get('hit_duration', 0.9) or 0.9)
        self._slot_hit_duration: dict[int, float] = {
            1: float(self._cfg.get('slot1_duration', self._hit_duration) or self._hit_duration),
            2: float(self._cfg.get('slot2_duration', 1.15) or 1.15),
            3: float(self._cfg.get('slot3_duration', 0.95) or 0.95),
            4: float(self._cfg.get('slot4_duration', 1.05) or 1.05),
            5: float(self._cfg.get('slot5_duration', 0.95) or 0.95),
            6: float(self._cfg.get('slot6_duration', 0.90) or 0.90),
        }
        self._active_slot: int = 0
        self._active_effect = None
        self._active_t: float = 0.0

        default_slot = int(self._cfg.get('active_slot', 0) or 0)
        if default_slot > 0:
            self.trigger_slot(default_slot)

    def is_active(self) -> bool:
        return self.enabled and self._active_effect is not None and self._active_t > 0.0

    @property
    def active_name(self) -> str:
        if not self.is_active():
            return 'OFF'
        for slot_key, slot_name, _implemented in self.SLOT_MAP:
            if slot_key == self._active_slot:
                return slot_name
        return 'OFF'

    def trigger_slot(self, slot: int) -> str:
        """Trigger a one-shot post-process quick-hit by slot number."""
        if slot <= 0:
            return 'Post FX: use Ctrl+Alt+1..8'

        if slot < 0 or slot > 8:
            return f'Post FX: invalid slot {slot}'

        info = next((s for s in self.SLOT_MAP if s[0] == slot), None)
        if info is None:
            return f'Post FX: invalid slot {slot}'

        _slot_key, slot_name, implemented = info

        if not implemented or slot not in self._effects:
            return f'Post FX {slot}: {slot_name} (coming soon)'

        self._active_slot = slot
        self._active_effect = self._effects[slot]
        duration = self._slot_hit_duration.get(slot, self._hit_duration)
        self._active_t = max(0.05, duration)
        reset = getattr(self._active_effect, 'reset', None)
        if callable(reset):
            try:
                reset()
            except Exception as exc:
                log.warning('Post FX reset failed for %s: %s', slot_name, exc)
        log.info('Post FX fired: slot=%d name=%s duration=%.2fs', slot, slot_name, self._active_t)
        return f'Post FX {slot}: {slot_name}'

    # Backward compatibility with earlier API name.
    def select_slot(self, slot: int) -> str:
        return self.trigger_slot(slot)

    def apply(
        self,
        src_tex: moderngl.Texture,
        dst_fbo: moderngl.Framebuffer,
        dt: float,
        bass: float,
        mid: float,
        treble: float,
        beat: float,
    ) -> bool:
        if not self.is_active():
            return False
        duration = self._slot_hit_duration.get(self._active_slot, self._hit_duration)
        strength = max(0.0, min(1.0, self._active_t / max(1e-6, duration)))
        self._active_effect.apply(src_tex, dst_fbo, dt, bass, mid, treble, beat, strength)
        self._active_t = max(0.0, self._active_t - dt)
        if self._active_t <= 0.0:
            log.info('Post FX completed: slot=%d name=%s', self._active_slot, self.active_name)
            self._active_slot = 0
            self._active_effect = None
        return True

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height
        for effect in self._effects.values():
            try:
                effect.resize(width, height)
            except Exception as exc:
                log.warning('Post FX resize failed for %s: %s', getattr(effect, 'NAME', type(effect).__name__), exc)

    def destroy(self) -> None:
        for effect in self._effects.values():
            try:
                effect.destroy()
            except Exception as exc:
                log.warning('Post FX destroy failed for %s: %s', getattr(effect, 'NAME', type(effect).__name__), exc)
