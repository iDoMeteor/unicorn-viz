"""Null/fallback controller classes for optional drop-in subsystems.

These classes provide fully-functional no-op implementations used when the
corresponding drop-in submodule is absent or fails to load.  They keep the core
app running cleanly with the feature disabled, per the drop-in independence rules
in CLAUDE.md (a missing drop-in must degrade gracefully, never crash at startup).

Each null class mirrors the public method/attribute surface that ``app.py`` and
``vj_api.py`` call on the corresponding live controller.  The conformance of
these surfaces is pinned by ``tests/test_null_controller_contracts.py``.

These symbols are re-exported from :mod:`unicornviz.app` for backwards
compatibility; existing call sites and tests importing them from
``unicornviz.app`` continue to work unchanged.
"""
from __future__ import annotations

import moderngl
import sdl2

from unicornviz.config import Config


class _NullMultiHeadController:
    """Safe fallback when the multi-head drop-in is unavailable."""

    requested_mode = 'single'

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    def log_video_displays(self, width: int, height: int) -> int:
        try:
            return max(1, int(sdl2.SDL_GetNumVideoDisplays()))
        except Exception:
            return 1

    def resolve_display_mode(self) -> str:
        return 'single'

    def supported_display_modes(self) -> tuple[str, ...]:
        return ('single',)

    def resolve_display_index(self, width: int, height: int) -> int:
        return 0

    def display_bounds(self, display_index: int, width: int, height: int) -> sdl2.SDL_Rect | None:
        return None

    def all_display_bounds(self, width: int, height: int) -> tuple[int, int, int, int]:
        return 0, 0, int(width), int(height)

    def window_position_for_display(self, display_index: int, width: int, height: int) -> tuple[int, int]:
        return sdl2.SDL_WINDOWPOS_CENTERED, sdl2.SDL_WINDOWPOS_CENTERED

    def move_window_to_display(self, window, width: int, height: int) -> None:
        return

    def destroy_mirror_outputs(self) -> None:
        return

    def create_mirror_outputs(self, title: str, width: int, height: int) -> None:
        return

    def resize_mirror_textures(self, width: int, height: int) -> None:
        return

    def present_mirror_outputs(self, frame_bytes: bytes, width: int, height: int) -> None:
        return

    def is_mirror_window_id(self, window_id: int) -> bool:
        return False

    def rebuild_multihead_outputs(self, width: int, height: int, title: str, fullscreen: bool) -> int:
        return 0

    def release_readback_pbos(self) -> None:
        return

    def ensure_readback_pbos(self, ctx: moderngl.Context, size: int) -> None:
        return

    def read_shared_frame(self, ctx: moderngl.Context, width: int, height: int) -> bytes:
        return ctx.screen.read(components=4, alignment=1)

    def has_mirror_outputs(self) -> bool:
        return False


class _NullScreenBurstController:
    """Safe fallback when burst controller drop-in is unavailable."""

    def __init__(self, cfg: dict | None = None) -> None:
        self._cfg = cfg or {}

    @property
    def active(self) -> bool:
        return False

    def trigger(self) -> None:
        return

    def step(self, dt: float) -> None:
        return

    def transform(self) -> tuple[float, float]:
        return 1.0, 0.0


class _NullWebcamSystem:
    """Safe fallback when webcam overlay drop-in is unavailable."""

    def __init__(self, ctx: moderngl.Context, width: int, height: int, cfg: dict | None = None) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._cfg = cfg or {}

    def start(self) -> None:
        return

    def render(self, dt: float, bass: float, treble: float) -> None:
        return

    def destroy(self) -> None:
        return

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def next_treatment(self) -> str | None:
        return None

    def prev_treatment(self) -> str | None:
        return None

    def toggle_auto_cycle(self) -> bool:
        return False

    def scale_pip(self, delta: float) -> float:
        return 0.0

    def set_layout(self, layout: str) -> None:
        return


class _NullRTMPStreamer:
    """Safe fallback when streaming drop-in is unavailable."""

    def __init__(self, cfg: dict, width: int, height: int) -> None:
        self.enabled = False
        self.auto_start = False
        self._last_error = 'Streaming subsystem unavailable'

    @property
    def is_streaming(self) -> bool:
        return False

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def destination_label(self) -> str:
        return '-'

    def start(self) -> bool:
        return False

    def write_frame(self, frame: bytes) -> bool:
        return False

    def stop(self) -> None:
        return

    def resize(self, width: int, height: int) -> None:
        return

    def set_provider(self, provider: str, restart: bool = True) -> str:
        return 'unavailable'


class _NullPostFxController:
    """Safe fallback when post-fx drop-in is unavailable."""

    enabled = False
    active_slot = 0

    def __init__(self, ctx: moderngl.Context, width: int, height: int, cfg: dict | None = None) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._cfg = cfg or {}
        self._slot_hit_duration: dict[int, float] = {}

    @property
    def is_hue_active(self) -> bool:
        return False

    @property
    def is_rotation_active(self) -> bool:
        return False

    @property
    def active_name(self) -> str:
        return 'N/A'

    def is_active(self) -> bool:
        return False

    def select_slot(self, slot: int) -> str:
        return 'Post FX: unavailable'

    def on_scroll(self, dy: int) -> None:
        return

    def on_ctrl_scroll(self, dy: int) -> None:
        return

    def on_ctrl_scroll_degrees(self, degrees: float) -> None:
        return

    def clear_hue_shift(self) -> None:
        return

    def clear_scroll_fx(self) -> None:
        return

    def clear_active_slot(self) -> None:
        return

    def friend_pairs(self) -> list[tuple[int, int]]:
        return []

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
        return False

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def destroy(self) -> None:
        return
