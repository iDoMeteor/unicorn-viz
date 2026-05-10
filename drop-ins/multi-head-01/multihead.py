"""Multi-head display controller.

This module encapsulates monitor discovery, display-mode policy (single/span/mirror),
mirror window lifecycle, and staged shared-frame readback buffers.
"""
from __future__ import annotations

import ctypes
import logging
from typing import Any

import moderngl
import sdl2

from unicornviz.config import Config

log = logging.getLogger(__name__)


class MultiHeadController:
    """Own multi-monitor policy, mirror outputs, and shared readback buffers."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._display_index_requested = int(cfg.get('window', 'display_index', default=0))
        self._display_index = 0
        self._display_mode_requested = str(cfg.get('window', 'display_mode', default='single')).lower()
        self._display_mode = 'single'
        self._display_layouts: list[tuple[int, int, int, int]] = []
        self._mirror_outputs: list[dict[str, Any]] = []
        self._readback_pbos: list[moderngl.Buffer] = []
        self._readback_index = 0
        self._readback_primed = False
        self._readback_size = 0

    @property
    def requested_mode(self) -> str:
        return self._display_mode_requested

    @property
    def display_mode(self) -> str:
        return self._display_mode

    @property
    def display_index(self) -> int:
        return self._display_index

    @property
    def has_mirror_outputs(self) -> bool:
        return bool(self._mirror_outputs)

    def log_video_displays(self, width: int, height: int) -> int:
        """Log visible SDL displays and return detected display count."""
        count = int(sdl2.SDL_GetNumVideoDisplays())
        self._display_layouts = []
        if count <= 0:
            log.warning('SDL reported no video displays; defaulting to display 0')
            self._display_layouts = [(0, 0, width, height)]
            return 1
        for idx in range(count):
            bounds = sdl2.SDL_Rect()
            if sdl2.SDL_GetDisplayBounds(idx, bounds) == 0:
                self._display_layouts.append((bounds.x, bounds.y, bounds.w, bounds.h))
                log.info(
                    'Display %d: origin=(%d,%d) size=%dx%d',
                    idx,
                    bounds.x,
                    bounds.y,
                    bounds.w,
                    bounds.h,
                )
        return count

    def resolve_display_mode(self) -> str:
        """Resolve the configured display mode against supported values."""
        allowed = {'single', 'span_all', 'mirror_all'}
        if self._display_mode_requested not in allowed:
            log.warning(
                'Requested display_mode=%r is invalid; using single',
                self._display_mode_requested,
            )
            self._display_mode = 'single'
            return self._display_mode
        self._display_mode = self._display_mode_requested
        return self._display_mode

    def resolve_display_index(self, width: int, height: int) -> int:
        """Resolve configured display index against available SDL displays."""
        count = self.log_video_displays(width, height)
        if self._display_index_requested < 0 or self._display_index_requested >= count:
            if self._display_mode == 'span_all':
                log.debug(
                    'Requested display_index=%d is out of range in span_all mode; using display 0 for restore position',
                    self._display_index_requested,
                )
            else:
                log.warning(
                    'Requested display_index=%d is out of range; using display 0',
                    self._display_index_requested,
                )
            self._display_index = 0
            return self._display_index
        self._display_index = self._display_index_requested
        return self._display_index

    def display_bounds(self, display_index: int, width: int, height: int) -> sdl2.SDL_Rect | None:
        """Return display bounds for selected SDL display, if available."""
        if 0 <= display_index < len(self._display_layouts):
            x, y, w, h = self._display_layouts[display_index]
            bounds = sdl2.SDL_Rect()
            bounds.x = x
            bounds.y = y
            bounds.w = w
            bounds.h = h
            return bounds
        bounds = sdl2.SDL_Rect()
        if sdl2.SDL_GetDisplayBounds(display_index, bounds) != 0:
            log.warning(
                'SDL_GetDisplayBounds failed for display %d: %s',
                display_index,
                sdl2.SDL_GetError().decode(),
            )
            return None
        return bounds

    def all_display_bounds(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Return union bounds of all visible SDL displays."""
        if not self._display_layouts:
            return 0, 0, width, height
        min_x = min(layout[0] for layout in self._display_layouts)
        min_y = min(layout[1] for layout in self._display_layouts)
        max_x = max(layout[0] + layout[2] for layout in self._display_layouts)
        max_y = max(layout[1] + layout[3] for layout in self._display_layouts)
        return min_x, min_y, max_x - min_x, max_y - min_y

    def window_position_for_display(self, display_index: int, width: int, height: int) -> tuple[int, int]:
        """Compute startup window coordinates centered on selected display."""
        bounds = self.display_bounds(display_index, width, height)
        if bounds is None:
            return sdl2.SDL_WINDOWPOS_CENTERED, sdl2.SDL_WINDOWPOS_CENTERED
        x = bounds.x + max(0, (bounds.w - width) // 2)
        y = bounds.y + max(0, (bounds.h - height) // 2)
        return x, y

    def move_window_to_display(self, window, width: int, height: int) -> None:
        """Move existing SDL window according to current display mode policy."""
        if window is None:
            return
        if self._display_mode == 'span_all':
            x, y, w, h = self.all_display_bounds(width, height)
            sdl2.SDL_SetWindowPosition(window, x, y)
            sdl2.SDL_SetWindowSize(window, w, h)
            return
        x, y = self.window_position_for_display(self._display_index, width, height)
        sdl2.SDL_SetWindowPosition(window, x, y)

    def destroy_mirror_outputs(self) -> None:
        """Destroy auxiliary mirror windows and SDL renderers/textures."""
        for output in self._mirror_outputs:
            texture = output.get('texture')
            renderer = output.get('renderer')
            window = output.get('window')
            if texture is not None:
                sdl2.SDL_DestroyTexture(texture)
            if renderer is not None:
                sdl2.SDL_DestroyRenderer(renderer)
            if window is not None:
                sdl2.SDL_DestroyWindow(window)
        self._mirror_outputs.clear()

    def create_mirror_outputs(self, title: str, width: int, height: int) -> None:
        """Create lightweight SDL windows that mirror the main output."""
        self.destroy_mirror_outputs()
        if self._display_mode != 'mirror_all' or len(self._display_layouts) <= 1:
            return
        source_w = max(1, width)
        source_h = max(1, height)
        for idx, (x, y, w, h) in enumerate(self._display_layouts):
            if idx == self._display_index:
                continue
            flags = sdl2.SDL_WINDOW_BORDERLESS | sdl2.SDL_WINDOW_SHOWN
            window = sdl2.SDL_CreateWindow(
                f'{title} Mirror'.encode(),
                x,
                y,
                w,
                h,
                flags,
            )
            if not window:
                log.warning('Failed to create mirror window for display %d: %s', idx, sdl2.SDL_GetError().decode())
                continue
            renderer = sdl2.SDL_CreateRenderer(window, -1, sdl2.SDL_RENDERER_ACCELERATED)
            if not renderer:
                renderer = sdl2.SDL_CreateRenderer(window, -1, sdl2.SDL_RENDERER_SOFTWARE)
            if not renderer:
                log.warning('Failed to create mirror renderer for display %d: %s', idx, sdl2.SDL_GetError().decode())
                sdl2.SDL_DestroyWindow(window)
                continue
            texture = sdl2.SDL_CreateTexture(
                renderer,
                sdl2.SDL_PIXELFORMAT_RGB24,
                sdl2.SDL_TEXTUREACCESS_STREAMING,
                source_w,
                source_h,
            )
            if not texture:
                log.warning('Failed to create mirror texture for display %d: %s', idx, sdl2.SDL_GetError().decode())
                sdl2.SDL_DestroyRenderer(renderer)
                sdl2.SDL_DestroyWindow(window)
                continue
            self._mirror_outputs.append(
                {
                    'window': window,
                    'renderer': renderer,
                    'texture': texture,
                    'display_index': idx,
                    'window_id': int(sdl2.SDL_GetWindowID(window)),
                }
            )
        if self._mirror_outputs:
            log.info('Mirror outputs active on displays: %s', ', '.join(str(int(output['display_index'])) for output in self._mirror_outputs))

    def resize_mirror_textures(self, width: int, height: int) -> None:
        """Recreate mirror textures when the main output size changes."""
        if not self._mirror_outputs:
            return
        source_w = max(1, width)
        source_h = max(1, height)
        for output in self._mirror_outputs:
            old_texture = output.get('texture')
            renderer = output.get('renderer')
            if renderer is None:
                continue
            if old_texture is not None:
                sdl2.SDL_DestroyTexture(old_texture)
            output['texture'] = sdl2.SDL_CreateTexture(
                renderer,
                sdl2.SDL_PIXELFORMAT_RGB24,
                sdl2.SDL_TEXTUREACCESS_STREAMING,
                source_w,
                source_h,
            )

    def present_mirror_outputs(self, frame_bytes: bytes, width: int, height: int) -> None:
        """Present a copied frame to all active mirror windows."""
        if not self._mirror_outputs:
            return
        pitch = width * 3
        src_ar = width / max(height, 1)
        for output in self._mirror_outputs:
            texture = output.get('texture')
            renderer = output.get('renderer')
            if texture is None or renderer is None:
                continue
            sdl2.SDL_UpdateTexture(texture, None, frame_bytes, pitch)
            sdl2.SDL_RenderClear(renderer)
            out_w = ctypes.c_int(0)
            out_h = ctypes.c_int(0)
            sdl2.SDL_GetRendererOutputSize(renderer, out_w, out_h)
            dst_rect = None
            if out_w.value > 0 and out_h.value > 0:
                dst_ar = out_w.value / out_h.value
                if abs(dst_ar - src_ar) > 1e-3:
                    if dst_ar > src_ar:
                        h = out_h.value
                        w = int(round(h * src_ar))
                        x = (out_w.value - w) // 2
                        y = 0
                    else:
                        w = out_w.value
                        h = int(round(w / src_ar))
                        x = 0
                        y = (out_h.value - h) // 2
                    dst_rect = sdl2.SDL_Rect(x, y, max(1, w), max(1, h))
            sdl2.SDL_RenderCopyEx(
                renderer,
                texture,
                None,
                dst_rect,
                0.0,
                None,
                sdl2.SDL_FLIP_VERTICAL,
            )
            sdl2.SDL_RenderPresent(renderer)

    def is_mirror_window_id(self, window_id: int) -> bool:
        """Return True if the given SDL window id belongs to a mirror window."""
        for output in self._mirror_outputs:
            if int(output.get('window_id', -1)) == window_id:
                return True
        return False

    def rebuild_multihead_outputs(self, width: int, height: int, title: str) -> int:
        """Refresh display topology and mirror windows after SDL display events."""
        self.log_video_displays(width, height)
        if self._display_index_requested < 0 or self._display_index_requested >= len(self._display_layouts):
            self._display_index = 0
        else:
            self._display_index = self._display_index_requested
        if self._display_mode == 'mirror_all':
            self.create_mirror_outputs(title, width, height)
            self.resize_mirror_textures(width, height)
        return self._display_index

    def release_readback_pbos(self) -> None:
        """Release async readback buffers."""
        for pbo in self._readback_pbos:
            pbo.release()
        self._readback_pbos.clear()
        self._readback_index = 0
        self._readback_primed = False
        self._readback_size = 0

    def ensure_readback_pbos(self, ctx: moderngl.Context, size: int) -> None:
        """Create or resize readback buffers used for shared frame capture."""
        if len(self._readback_pbos) == 2 and self._readback_size == size:
            return
        self.release_readback_pbos()
        self._readback_pbos = [ctx.buffer(reserve=size), ctx.buffer(reserve=size)]
        self._readback_size = size

    def read_shared_frame(self, ctx: moderngl.Context, width: int, height: int) -> bytes | None:
        """Capture one shared frame for recording/mirror using staged readback."""
        size = width * height * 3
        self.ensure_readback_pbos(ctx, size)
        if len(self._readback_pbos) != 2:
            return None
        write_idx = self._readback_index
        read_idx = 1 - write_idx
        ctx.screen.read_into(self._readback_pbos[write_idx], components=3, alignment=1)
        frame: bytes | None = None
        if self._readback_primed:
            frame = self._readback_pbos[read_idx].read()
        else:
            self._readback_primed = True
        self._readback_index = read_idx
        return frame
