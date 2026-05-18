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

from chromatic_aberration import ChromaticAberration
from film_grain_dither import FilmGrainDither
from glitch_slices import GlitchSlices
from heat_haze_refraction import HeatHazeRefraction
from hue_shift import HueShift
from lens_distortion_vignette import LensDistortionVignette
from multi_pass_bloom import MultiPassBloom
from radial_zoom_blur import RadialZoomBlur
from temporal_feedback import TemporalFeedbackTrail

log = logging.getLogger(__name__)


HELP_ENTRIES = [
    ('Post FX', 'Ctrl+Alt+1', 'Chromatic Aberration'),
    ('Post FX', 'Ctrl+Alt+2', 'Film Grain + Dither'),
    ('Post FX', 'Ctrl+Alt+3', 'Glitch Slices'),
    ('Post FX', 'Ctrl+Alt+4', 'Heat Haze Refraction'),
    ('Post FX', 'Ctrl+Alt+5', 'Lens Distortion + Vignette'),
    ('Post FX', 'Ctrl+Alt+6', 'Multi-pass Bloom'),
    ('Post FX', 'Ctrl+Alt+7', 'Radial Zoom Blur'),
    ('Post FX', 'Ctrl+Alt+8', 'Temporal Feedback Trail'),
]


class PostFxController:
    """Runtime controller for global post-process effects."""

    SLOT_MAP: tuple[tuple[int, str, bool], ...] = (
        (1, 'Chromatic Aberration', True),
        (2, 'Film Grain + Dither', True),
        (3, 'Glitch Slices', True),
        (4, 'Heat Haze Refraction', True),
        (5, 'Lens Distortion + Vignette', True),
        (6, 'Multi-pass Bloom', True),
        (7, 'Radial Zoom Blur', True),
        (8, 'Temporal Feedback Trail', True),
    )

    def __init__(self, ctx: moderngl.Context, width: int, height: int, cfg: dict | None = None) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._cfg = cfg or {}
        self.enabled = bool(self._cfg.get('enabled', True))

        self._effects: dict[int, object] = {
            1: ChromaticAberration(ctx, width, height),
            2: FilmGrainDither(ctx, width, height),
            3: GlitchSlices(ctx, width, height),
            4: HeatHazeRefraction(ctx, width, height),
            5: LensDistortionVignette(ctx, width, height),
            6: MultiPassBloom(ctx, width, height),
            7: RadialZoomBlur(ctx, width, height),
            8: TemporalFeedbackTrail(ctx, width, height),
        }
        self._hit_duration = float(self._cfg.get('hit_duration', 0.9) or 0.9)
        self._slot_hit_duration: dict[int, float] = {
            1: float(self._cfg.get('slot1_duration', 1.15) or 1.15),
            2: float(self._cfg.get('slot2_duration', 0.95) or 0.95),
            3: float(self._cfg.get('slot3_duration', 0.90) or 0.90),
            4: float(self._cfg.get('slot4_duration', 1.30) or 1.30),
            5: float(self._cfg.get('slot5_duration', 1.05) or 1.05),
            6: float(self._cfg.get('slot6_duration', 1.20) or 1.20),
            7: float(self._cfg.get('slot7_duration', 0.95) or 0.95),
            8: float(self._cfg.get('slot8_duration', self._hit_duration) or self._hit_duration),
        }
        self._active_slot: int = 0
        self._active_effect = None
        self._active_t: float = 0.0

        # ── Hue-shift continuous pass (scroll-wheel driven) ──────────────
        self._hue_shift = HueShift(ctx, width, height)
        self._hue_offset: float = 0.0
        self._hue_active: bool = False
        self._hue_idle_t: float = 0.0
        self._hue_idle_timeout: float = float(self._cfg.get('hue_shift_timeout_s', 3.0) or 3.0)
        self._hue_step: float = float(self._cfg.get('hue_shift_step', 1.0 / 36.0) or 1.0 / 36.0)
        # Internal FBO used when slot and hue passes both need to chain.
        self._hue_fbo: moderngl.Framebuffer = ctx.framebuffer(
            color_attachments=[ctx.texture((width, height), 4)]
        )

        default_slot = int(self._cfg.get('active_slot', 0) or 0)
        if default_slot > 0:
            self.trigger_slot(default_slot)

    def is_active(self) -> bool:
        return self.enabled and (
            (self._active_effect is not None and self._active_t > 0.0)
            or self._hue_active
        )

    @property
    def is_hue_active(self) -> bool:
        """True while the scroll-wheel hue-shift pass is running."""
        return self._hue_active

    def on_scroll(self, dy: int) -> None:
        """Accumulate hue offset from a mouse-wheel event and (re)arm the idle timer.

        dy is positive for scroll-up and negative for scroll-down.
        """
        if not self.enabled:
            return
        self._hue_offset = (self._hue_offset + int(dy) * self._hue_step) % 1.0
        self._hue_idle_t = self._hue_idle_timeout
        self._hue_active = True
        log.debug('Hue shift: offset=%.3f dy=%d', self._hue_offset, dy)

    def clear_hue_shift(self) -> None:
        """Immediately deactivate the hue-shift pass and reset the offset."""
        self._hue_active = False
        self._hue_idle_t = 0.0
        self._hue_offset = 0.0
        log.info('Hue shift cleared')

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
        """Apply active post-fx passes into dst_fbo.

        Execution order when both passes are active:
          1. Slot one-shot → internal _hue_fbo
          2. Hue shift from _hue_fbo → dst_fbo
        When only one pass is active it writes directly to dst_fbo.
        """
        if not self.is_active():
            return False

        slot_running = self._active_effect is not None and self._active_t > 0.0
        hue_running = self._hue_active

        if slot_running:
            duration = self._slot_hit_duration.get(self._active_slot, self._hit_duration)
            strength = max(0.0, min(1.0, self._active_t / max(1e-6, duration)))
            slot_dst = self._hue_fbo if hue_running else dst_fbo
            self._active_effect.apply(src_tex, slot_dst, dt, bass, mid, treble, beat, strength)
            self._active_t = max(0.0, self._active_t - dt)
            if self._active_t <= 0.0:
                log.info('Post FX completed: slot=%d name=%s', self._active_slot, self.active_name)
                self._active_slot = 0
                self._active_effect = None

        if hue_running:
            hue_src = self._hue_fbo.color_attachments[0] if slot_running else src_tex
            hue_strength = max(0.0, min(1.0, self._hue_idle_t / max(1e-6, self._hue_idle_timeout)))
            self._hue_shift.hue_offset = self._hue_offset
            self._hue_shift.apply(hue_src, dst_fbo, dt, bass, mid, treble, beat, hue_strength)
            self._hue_idle_t = max(0.0, self._hue_idle_t - dt)
            if self._hue_idle_t <= 0.0:
                self._hue_active = False
                log.info('Hue shift expired (idle timeout)')

        return True

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height
        # Rebuild internal hue-chain FBO at new resolution.
        try:
            self._hue_fbo.color_attachments[0].release()
            self._hue_fbo.release()
            self._hue_fbo = self._ctx.framebuffer(
                color_attachments=[self._ctx.texture((width, height), 4)]
            )
        except Exception as exc:
            log.warning('Post FX hue FBO resize failed: %s', exc)
        self._hue_shift.resize(width, height)
        for effect in self._effects.values():
            try:
                effect.resize(width, height)
            except Exception as exc:
                log.warning('Post FX resize failed for %s: %s', getattr(effect, 'NAME', type(effect).__name__), exc)

    def destroy(self) -> None:
        try:
            self._hue_shift.destroy()
            self._hue_fbo.color_attachments[0].release()
            self._hue_fbo.release()
        except Exception as exc:
            log.warning('Post FX hue resources destroy failed: %s', exc)
        for effect in self._effects.values():
            try:
                effect.destroy()
            except Exception as exc:
                log.warning('Post FX destroy failed for %s: %s', getattr(effect, 'NAME', type(effect).__name__), exc)
