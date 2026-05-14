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

log = logging.getLogger(__name__)


HELP_ENTRIES = [
    ('Post FX', 'Ctrl+Alt+1', 'Temporal Feedback Trail'),
    ('Post FX', 'Ctrl+Alt+2', 'Chromatic Aberration'),
    ('Post FX', 'Ctrl+Alt+3-8', 'Reserved (coming soon)'),
    ('Post FX', 'Ctrl+Alt+0', 'Disable post-process effect'),
]


class PostFxController:
    """Runtime controller for global post-process effects."""

    SLOT_MAP: tuple[tuple[int, str, bool], ...] = (
        (1, 'Temporal Feedback Trail', True),
        (2, 'Chromatic Aberration', True),
        (3, 'Film Grain + Dither', False),
        (4, 'Lens Distortion + Vignette', False),
        (5, 'Radial Zoom Blur', False),
        (6, 'Glitch Slices', False),
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
        }
        default_slot = int(self._cfg.get('active_slot', 0) or 0)
        self._active_slot: int = 0
        self._active_effect = None
        self.select_slot(default_slot)

    def is_active(self) -> bool:
        return self.enabled and self._active_effect is not None

    @property
    def active_name(self) -> str:
        if not self.is_active():
            return 'OFF'
        for slot_key, slot_name, _implemented in self.SLOT_MAP:
            if slot_key == self._active_slot:
                return slot_name
        return 'OFF'

    def select_slot(self, slot: int) -> str:
        """Select active post-process slot.

        slot=0 disables post-process stack.
        """
        if slot <= 0:
            self._active_slot = 0
            self._active_effect = None
            return 'Post FX: OFF'

        if slot < 0 or slot > 8:
            return f'Post FX: invalid slot {slot}'

        info = next((s for s in self.SLOT_MAP if s[0] == slot), None)
        if info is None:
            return f'Post FX: invalid slot {slot}'

        _slot_key, slot_name, implemented = info

        if not implemented or slot not in self._effects:
            self._active_slot = 0
            self._active_effect = None
            return f'Post FX {slot}: {slot_name} (coming soon)'

        self._active_slot = slot
        self._active_effect = self._effects[slot]
        reset = getattr(self._active_effect, 'reset', None)
        if callable(reset):
            try:
                reset()
            except Exception as exc:
                log.warning('Post FX reset failed for %s: %s', slot_name, exc)
        return f'Post FX {slot}: {slot_name}'

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
        self._active_effect.apply(src_tex, dst_fbo, dt, bass, mid, treble, beat)
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
