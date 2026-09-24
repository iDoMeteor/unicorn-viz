"""GPU 2D draw lists for the Pillow-style second-window UIs.

Why this exists
---------------
The DJ mixer console and the Control Room draw their UIs with Pillow on a
background thread: every frame is a full-window RGBA raster, copied with
``tobytes()`` and uploaded as a texture.  At 1920x1080 and 30 fps that is
~250 MB/s through the CPU, and the raster itself held the mixer's render
thread (and the GIL) for ~50 ms a frame in the 2026-09-24 perf pass.

This module keeps the *drawing code* exactly as it is and moves the
*pixels* to the GPU:

* :class:`DrawList` implements the subset of ``PIL.ImageDraw.ImageDraw``
  those UIs use (``rectangle``, ``rounded_rectangle``, ``ellipse``,
  ``line``, ``arc``, ``pieslice``, ``polygon``, ``text``, ``textlength``,
  ``textbbox``) plus :meth:`DrawList.image` for pasting RGBA images.  Each
  call appends one fixed-size instance (20 floats) to a flat buffer.  No
  pixels are produced on the CPU.  Safe to use from any single thread.
* :class:`TextureAtlas` holds text (one white alpha mask per
  ``(string, font)``, tinted on the GPU, so colors never multiply entries)
  and pasted images.  It packs on the recording thread and queues pixel
  patches for the GL thread.
* :class:`Batch2DRenderer` draws a finished :class:`GpuFrame` as **one
  instanced draw call** with an SDF uber-shader: anti-aliased rects,
  rounded rects, ellipses, arcs and pie slices, capsule lines, and atlas
  quads.  It uses raw GL entry points from ``SDL_GL_GetProcAddress`` (the
  same approach as :mod:`unicornviz.secondary_gl_window`, and for the same
  reason: moderngl cannot attach to a second context on native Wayland).

Geometry follows Pillow's conventions so layouts land where they did: a
box ``[x0, y0, x1, y1]`` covers pixels ``x0..x1`` inclusive, outlines grow
inward from the box edge, and arc angles are degrees clockwise from
3 o'clock.  Axis-aligned edges are pixel-exact; curves and diagonals come
out anti-aliased where Pillow's are stair-stepped.

Usage::

    atlas = TextureAtlas()
    dl = DrawList(atlas)
    dl.begin(1920, 1080, clear=(10, 12, 20, 255))
    dl.rounded_rectangle([10, 10, 200, 60], radius=6, fill=(40, 50, 80, 255))
    dl.text((20, 24), 'DECK A', font=font, fill=(230, 230, 240, 255))
    frame = dl.finish()                      # hand to the GL thread
    ...
    renderer.draw(frame, atlas.take_patches(), viewport_w, viewport_h)
"""
from __future__ import annotations

import ctypes
import logging
import math
import threading
from array import array
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageColor, ImageDraw

log = logging.getLogger(__name__)

#: Floats per instance: box/endpoints (4), fill RGBA (4), outline RGBA (4),
#: params (radius, width, kind, pillow-compat flag) (4), uv rect or arc angles (4).
FLOATS_PER_INSTANCE = 20

KIND_RECT = 0.0       # rectangle / rounded rectangle (radius in params.x)
KIND_ELLIPSE = 1.0
KIND_LINE = 2.0       # box slots hold the two endpoints; color in fill
KIND_IMAGE = 3.0      # atlas quad; fill is the tint (white = as-is)
KIND_ARC = 4.0        # ellipse outline between two angles; color in fill
KIND_PIE = 5.0        # filled wedge + its rim

ATLAS_W = 4096
ATLAS_H = 2048
_ATLAS_PAD = 1

_NO_COLOR = (0.0, 0.0, 0.0, 0.0)
_WHITE = (255.0, 255.0, 255.0, 255.0)
_ZERO4 = (0.0, 0.0, 0.0, 0.0)


_COLOR_CACHE: dict = {}


def _rgba(color: Any, cache: dict = _COLOR_CACHE) -> tuple:
    """Normalize a Pillow color (tuple, list, int or name) to RGBA 0..255.

    The tuple fast path is first: the UIs pass literal tuples for almost
    every call, and this runs a few thousand times per frame.
    """
    if color is None:
        return _NO_COLOR
    if type(color) is tuple:
        n = len(color)
        if n == 4:
            return color
        if n == 3:
            return (color[0], color[1], color[2], 255)
    try:
        return cache[color]
    except (KeyError, TypeError):
        pass
    if isinstance(color, str):
        rgb = ImageColor.getrgb(color)
        out = tuple(rgb) + (255,) if len(rgb) == 3 else tuple(rgb)
    elif isinstance(color, (int, float)):
        v = int(color)
        out = (v, v, v, 255)
    else:
        seq = tuple(color)
        out = seq + (255,) if len(seq) == 3 else seq[:4]
    try:
        cache[color] = out
    except TypeError:              # unhashable (a list): just don't memo it
        pass
    return out


def _box(xy: Any) -> tuple[float, float, float, float]:
    """Pillow box forms -> ``(x0, y0, x1, y1)`` in Pillow's inclusive sense."""
    if len(xy) == 4:
        x0, y0, x1, y1 = xy
    else:
        (x0, y0), (x1, y1) = xy
    return x0, y0, x1, y1


def _points(xy: Any) -> list[tuple[float, float]]:
    """Pillow point-list forms (flat or pairs) -> list of ``(x, y)``."""
    if not len(xy):
        return []
    first = xy[0]
    if isinstance(first, (tuple, list)):
        return [(p[0], p[1]) for p in xy]
    return [(xy[i], xy[i + 1]) for i in range(0, len(xy) - 1, 2)]


@dataclass(frozen=True)
class AtlasEntry:
    """Where one cached raster lives in the atlas, and how to place it."""

    u0: float
    v0: float
    u1: float
    v1: float
    width: int
    height: int
    offset_x: int      # add to the draw position (text bearing / bbox origin)
    offset_y: int


class TextureAtlas:
    """Shelf-packed RGBA atlas for text masks and pasted images.

    Lifecycle: the recording thread calls :meth:`text_entry` /
    :meth:`image_entry`, which pack new rasters and queue their pixels as
    patches; the GL thread calls :meth:`take_patches` before drawing a
    frame and uploads them.  When the atlas fills up it resets (every
    entry is dropped and re-added on demand) and bumps :attr:`generation`;
    a frame records the generation it was built against so the renderer
    can refuse a frame whose entries predate a reset.

    Thread-safety: packing is single-threaded (the recording thread);
    the patch queue is guarded by a lock, so one other thread may drain it.
    """

    def __init__(self, width: int = ATLAS_W, height: int = ATLAS_H) -> None:
        self.width = int(width)
        self.height = int(height)
        self.generation = 0
        self._entries: dict[Any, AtlasEntry] = {}
        self._pins: dict[Any, Any] = {}          # keeps keyed objects alive
        self._shelves: list[list[int]] = []      # [y, height, next_x]
        self._next_y = 0
        self._lock = threading.Lock()
        self._patches: list[tuple] = []
        self._measure = ImageDraw.Draw(Image.new('L', (1, 1)))
        self._warned_oversize = False
        self._invalidate_requested = False
        # Streamed rasters (stream_entry): the newest pixels per region,
        # uploaded after the ordinary patches -- a preview refreshed faster
        # than frames are presented uploads once, not once per refresh.
        self._stream_patches: dict[tuple, tuple] = {}

    # -- packing -------------------------------------------------------------

    def _alloc(self, w: int, h: int) -> tuple[int, int] | None:
        pw, ph = w + _ATLAS_PAD, h + _ATLAS_PAD
        if pw > self.width or ph > self.height:
            return None
        for shelf in self._shelves:
            y, sh, nx = shelf
            if ph <= sh <= ph + max(4, ph // 3) and nx + pw <= self.width:
                shelf[2] = nx + pw
                return nx, y
        if self._next_y + ph > self.height:
            return None
        self._shelves.append([self._next_y, ph, pw])
        self._next_y += ph
        return 0, self._next_y - ph

    def _reset(self) -> None:
        self._entries.clear()
        self._pins.clear()
        self._shelves.clear()
        self._next_y = 0
        self.generation += 1
        with self._lock:
            self._patches = [('reset', self.generation)]
            self._stream_patches = {}

    def _put(self, key: Any, rgba: bytes, w: int, h: int, ox: int, oy: int,
             pin: Any = None) -> AtlasEntry | None:
        spot = self._alloc(w, h)
        if spot is None:
            if w + _ATLAS_PAD > self.width or h + _ATLAS_PAD > self.height:
                if not self._warned_oversize:
                    self._warned_oversize = True
                    log.warning('gpu2d: %dx%d raster exceeds the %dx%d atlas; '
                                'not drawn', w, h, self.width, self.height)
                return None
            self._reset()
            spot = self._alloc(w, h)
            if spot is None:        # pragma: no cover - guarded just above
                return None
        x, y = spot
        entry = AtlasEntry(x / self.width, y / self.height,
                           (x + w) / self.width, (y + h) / self.height,
                           w, h, ox, oy)
        self._entries[key] = entry
        if pin is not None:
            self._pins[key] = pin
        with self._lock:
            self._patches.append(('put', x, y, w, h, rgba))
        return entry

    # -- public --------------------------------------------------------------

    def text_entry(self, text: str, font: Any) -> AtlasEntry | None:
        """Atlas entry for ``text`` in ``font`` (white mask, tint on draw)."""
        key = (text, id(font))
        entry = self._entries.get(key)
        if entry is not None:
            return entry
        try:
            left, top, right, bottom = self._measure.textbbox((0, 0), text, font=font)
        except Exception:
            return None
        ox, oy = min(0, int(math.floor(left))), min(0, int(math.floor(top)))
        w = max(1, int(math.ceil(right)) - ox)
        h = max(1, int(math.ceil(bottom)) - oy)
        mask = Image.new('L', (w, h), 0)
        ImageDraw.Draw(mask).text((-ox, -oy), text, font=font, fill=255)
        rgba = np.empty((h, w, 4), dtype=np.uint8)
        rgba[:, :, :3] = 255
        rgba[:, :, 3] = np.asarray(mask, dtype=np.uint8)
        return self._put(key, rgba.tobytes(), w, h, ox, oy, pin=font)

    def image_entry(self, image: Any) -> AtlasEntry | None:
        """Atlas entry for a PIL image (converted to RGBA once, then cached
        by identity -- the image is pinned so its id cannot be reused)."""
        key = ('img', id(image))
        entry = self._entries.get(key)
        if entry is not None:
            return entry
        img = image if image.mode == 'RGBA' else image.convert('RGBA')
        w, h = img.size
        return self._put(key, img.tobytes(), w, h, 0, 0, pin=image)

    def raster_entry(self, key: Any, img: Any, ox: int, oy: int) -> AtlasEntry | None:
        """Atlas entry for an RGBA raster the caller built, cached by ``key``."""
        entry = self._entries.get(key)
        if entry is not None:
            return entry
        w, h = img.size
        return self._put(key, img.tobytes(), w, h, ox, oy)

    def stream_entry(self, key: Any, image: Any) -> AtlasEntry | None:
        """A region whose pixels change every call (a live preview).

        The first call for ``key`` allocates a region; later calls with the
        same size reuse it and just queue the new pixels (only the newest
        per region is uploaded -- see :meth:`take_patches`).  A new size gets
        a new region (the old one is simply orphaned until the next reset).
        ``image`` is a PIL image (converted to RGBA) or an ``(h, w, 4)``
        uint8 array.
        """
        if isinstance(image, np.ndarray):
            h, w = int(image.shape[0]), int(image.shape[1])
            data = np.ascontiguousarray(image, dtype=np.uint8).tobytes()
        else:
            img = image if image.mode == 'RGBA' else image.convert('RGBA')
            w, h = img.size
            data = img.tobytes()
        skey = ('stream', key)
        entry = self._entries.get(skey)
        if entry is not None and (entry.width, entry.height) == (w, h):
            x = int(round(entry.u0 * self.width))
            y = int(round(entry.v0 * self.height))
            with self._lock:
                self._stream_patches[(x, y, w, h)] = ('put', x, y, w, h, data)
            return entry
        return self._put(skey, data, w, h, 0, 0)

    def invalidate(self) -> None:
        """Ask for a full reset from any thread (e.g. the GL texture was
        recreated, so nothing uploaded so far exists any more).  Applied by
        the recording thread at its next :meth:`DrawList.begin`."""
        with self._lock:
            self._invalidate_requested = True

    def _apply_invalidate(self) -> None:
        with self._lock:
            requested, self._invalidate_requested = self._invalidate_requested, False
        if requested:
            self._reset()

    def take_patches(self) -> list[tuple]:
        """Drain the queued uploads (GL thread): ``('reset', gen)`` or
        ``('put', x, y, w, h, rgba_bytes)``, in order."""
        with self._lock:
            patches, self._patches = self._patches, []
            if self._stream_patches:
                patches.extend(self._stream_patches.values())
                self._stream_patches = {}
        return patches

    def textlength(self, text: str, font: Any = None) -> float:
        return self._measure.textlength(text, font=font)

    def textbbox(self, xy: Any, text: str, font: Any = None, **kw: Any) -> tuple:
        return self._measure.textbbox(xy, text, font=font, **kw)


@dataclass(frozen=True)
class GpuFrame:
    """One finished UI frame, ready for :meth:`Batch2DRenderer.draw`."""

    instances: array            # float32, FLOATS_PER_INSTANCE per instance
    count: int
    width: int
    height: int
    clear: tuple
    atlas_generation: int

    def same_content(self, other: GpuFrame | None) -> bool:
        """True when ``other`` would draw the same pixels (skip the submit)."""
        return (other is not None and other.count == self.count
                and other.width == self.width and other.height == self.height
                and other.clear == self.clear
                and other.atlas_generation == self.atlas_generation
                and other.instances == self.instances)


class DrawList:
    """Pillow-``ImageDraw``-compatible recorder that emits GPU instances.

    Lifecycle: :meth:`begin` -> any number of draw calls -> :meth:`finish`,
    which returns an immutable :class:`GpuFrame` and starts a fresh buffer.
    Not thread-safe: one recording thread per list (and per atlas).
    """

    #: Mimics ``ImageDraw.mode`` for callers that sniff it.
    mode = 'RGBA'

    def __init__(self, atlas: TextureAtlas, pillow_rgba: bool = True) -> None:
        self.atlas = atlas
        # Pillow draws shapes onto an RGBA image by *overwriting* pixels, not
        # blending (ImageDraw only blends onto RGB images), and the second
        # windows show the RGB as-is -- so a fill of (255, 255, 255, 90)
        # has always displayed as solid white.  With this on (the default)
        # any shape color with non-zero alpha paints opaque, keeping every
        # existing UI looking exactly as it does on Pillow.  Text and pasted
        # images keep true alpha either way, as Pillow composites those.
        self._compat = 1.0 if pillow_rgba else 0.0
        self._buf = array('f')
        self._width = 1
        self._height = 1
        self._clear: tuple = (0, 0, 0, 255)
        self._gen = atlas.generation
        self.font = None           # ImageDraw attribute some callers read

    # -- frame lifecycle -----------------------------------------------------

    def begin(self, width: int, height: int, clear: Any = (0, 0, 0, 255)) -> None:
        """Start a frame of ``width`` x ``height`` pixels on ``clear``."""
        self._buf = array('f')
        self._width = max(1, int(width))
        self._height = max(1, int(height))
        self._clear = _rgba(clear)
        self.atlas._apply_invalidate()
        self._gen = self.atlas.generation

    def finish(self) -> GpuFrame | None:
        """Close the frame.  ``None`` when the atlas reset mid-frame (the
        entries recorded before the reset are gone); just record again."""
        buf, self._buf = self._buf, array('f')
        if self.atlas.generation != self._gen:
            return None
        return GpuFrame(buf, len(buf) // FLOATS_PER_INSTANCE, self._width,
                        self._height, self._clear, self._gen)

    @property
    def count(self) -> int:
        return len(self._buf) // FLOATS_PER_INSTANCE

    # -- shapes --------------------------------------------------------------

    def rectangle(self, xy: Any, fill: Any = None, outline: Any = None,
                  width: float = 1) -> None:
        x0, y0, x1, y1 = _box(xy)
        f = _rgba(fill)
        o = _rgba(outline) if outline is not None else _NO_COLOR
        self._buf.extend((x0, y0, x1 + 1, y1 + 1, *f, *o,
                          0.0, width if outline is not None else 0.0, KIND_RECT, self._compat,
                          *_ZERO4))

    def rounded_rectangle(self, xy: Any, radius: float = 0, fill: Any = None,
                          outline: Any = None, width: float = 1,
                          corners: Any = None) -> None:
        x0, y0, x1, y1 = _box(xy)
        f = _rgba(fill)
        o = _rgba(outline) if outline is not None else _NO_COLOR
        self._buf.extend((x0, y0, x1 + 1, y1 + 1, *f, *o,
                          float(radius), width if outline is not None else 0.0,
                          KIND_RECT, self._compat, *_ZERO4))

    def ellipse(self, xy: Any, fill: Any = None, outline: Any = None,
                width: float = 1) -> None:
        x0, y0, x1, y1 = _box(xy)
        f = _rgba(fill)
        o = _rgba(outline) if outline is not None else _NO_COLOR
        self._buf.extend((x0, y0, x1 + 1, y1 + 1, *f, *o,
                          0.0, width if outline is not None else 0.0,
                          KIND_ELLIPSE, self._compat, *_ZERO4))

    def arc(self, xy: Any, start: float, end: float, fill: Any = None,
            width: float = 1) -> None:
        x0, y0, x1, y1 = _box(xy)
        self._buf.extend((x0, y0, x1 + 1, y1 + 1, *_rgba(fill), *_NO_COLOR,
                          0.0, float(width), KIND_ARC, self._compat,
                          float(start), float(end), 0.0, 0.0))

    def pieslice(self, xy: Any, start: float, end: float, fill: Any = None,
                 outline: Any = None, width: float = 1) -> None:
        x0, y0, x1, y1 = _box(xy)
        o = _rgba(outline) if outline is not None else _NO_COLOR
        self._buf.extend((x0, y0, x1 + 1, y1 + 1, *_rgba(fill), *o,
                          0.0, width if outline is not None else 0.0,
                          KIND_PIE, self._compat, float(start), float(end), 0.0, 0.0))

    def line(self, xy: Any, fill: Any = None, width: float = 0,
             joint: Any = None) -> None:
        pts = _points(xy)
        if not pts:
            return
        f = _rgba(fill)
        w = float(width) if width else 1.0
        if len(pts) == 1:
            pts = pts * 2
        ext = self._buf.extend
        lo, hi = (int(w) - 1) // 2, int(w) // 2
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            if ay == by or ax == bx:
                # Axis-aligned: exactly Pillow's pixels -- endpoints included,
                # rows (or columns) from -(w-1)//2 to +w//2 -- as a rect.
                if ay == by:
                    x0, x1 = (ax, bx) if ax <= bx else (bx, ax)
                    box = (x0, ay - lo, x1 + 1, ay + hi + 1)
                else:
                    y0, y1 = (ay, by) if ay <= by else (by, ay)
                    box = (ax - lo, y0, ax + hi + 1, y1 + 1)
                ext((*box, *f, *_NO_COLOR, 0.0, 0.0, KIND_RECT, self._compat,
                     *_ZERO4))
                continue
            # Diagonal: an anti-aliased capsule between pixel centers.
            ext((ax + 0.5, ay + 0.5, bx + 0.5, by + 0.5, *f, *_NO_COLOR,
                 0.0, w, KIND_LINE, self._compat, *_ZERO4))

    def point(self, xy: Any, fill: Any = None) -> None:
        for x, y in _points(xy):
            self.rectangle([x, y, x, y], fill=fill)

    def polygon(self, xy: Any, fill: Any = None, outline: Any = None,
                width: float = 1) -> None:
        """Rare in these UIs: rasterized once by Pillow and cached."""
        pts = _points(xy)
        if len(pts) < 3:
            return
        minx = int(math.floor(min(p[0] for p in pts)))
        miny = int(math.floor(min(p[1] for p in pts)))
        maxx = int(math.ceil(max(p[0] for p in pts)))
        maxy = int(math.ceil(max(p[1] for p in pts)))
        rel = tuple((p[0] - minx, p[1] - miny) for p in pts)
        key = ('poly', rel, _rgba(fill), _rgba(outline) if outline else None, width)
        entry = self.atlas._entries.get(key)
        if entry is None:
            img = Image.new('RGBA', (maxx - minx + 2, maxy - miny + 2), (0, 0, 0, 0))
            ImageDraw.Draw(img, 'RGBA').polygon(
                list(rel), fill=fill, outline=outline, width=int(width))
            entry = self.atlas.raster_entry(key, img, 0, 0)
        if entry is not None:
            self._quad(entry, minx, miny, _WHITE)

    # -- text & images -------------------------------------------------------

    def text(self, xy: Any, text: Any = None, fill: Any = None, font: Any = None,
             *args: Any, **kw: Any) -> None:
        if text is None or text == '':
            return
        text = str(text)
        if kw or args:
            self._text_fallback(xy, text, fill, font, args, kw)
            return
        entry = self.atlas.text_entry(text, font)
        if entry is not None:
            self._quad(entry, xy[0], xy[1], _rgba(fill) if fill is not None else _WHITE)

    def _text_fallback(self, xy: Any, text: str, fill: Any, font: Any,
                       args: tuple, kw: dict) -> None:
        """Any ``text()`` option beyond ``font``/``fill`` (anchor, align,
        stroke, ...): let Pillow lay it out once into a cached raster."""
        left, top, right, bottom = self.atlas.textbbox((0, 0), text, font=font, **kw)
        ox, oy = int(math.floor(left)), int(math.floor(top))
        key = ('textkw', text, id(font), tuple(sorted(kw.items())), _rgba(fill))
        entry = self.atlas._entries.get(key)
        if entry is None:
            img = Image.new('RGBA', (max(1, int(math.ceil(right)) - ox),
                                     max(1, int(math.ceil(bottom)) - oy)), (0, 0, 0, 0))
            ImageDraw.Draw(img, 'RGBA').text((-ox, -oy), text, fill, font, *args, **kw)
            entry = self.atlas.raster_entry(key, img, ox, oy)
        if entry is not None:
            self._quad(entry, xy[0], xy[1], _WHITE)

    def image(self, image: Any, x: float, y: float) -> None:
        """Paste an RGBA image with its alpha (``Image.paste(im, xy, im)``)."""
        entry = self.atlas.image_entry(image)
        if entry is not None:
            self._quad(entry, x, y, _WHITE)

    def stream_image(self, key: Any, image: Any, x: float, y: float) -> None:
        """Draw a raster that changes every frame (a live preview) through
        one reused atlas region (:meth:`TextureAtlas.stream_entry`) instead
        of a new entry per frame."""
        entry = self.atlas.stream_entry(key, image)
        if entry is not None:
            self._quad(entry, x, y, _WHITE)

    def _quad(self, entry: AtlasEntry, x: float, y: float, tint: tuple) -> None:
        # Snap to whole pixels: atlas texels map 1:1 onto frame pixels.
        x0 = float(int(math.floor(x)) + entry.offset_x)
        y0 = float(int(math.floor(y)) + entry.offset_y)
        self._buf.extend((x0, y0, x0 + entry.width, y0 + entry.height,
                          *tint, *_NO_COLOR, 0.0, 0.0, KIND_IMAGE, 0.0,
                          entry.u0, entry.v0, entry.u1, entry.v1))

    def rects(self, x0: np.ndarray, y0: np.ndarray, x1: np.ndarray,
              y1: np.ndarray, rgba: np.ndarray) -> None:
        """Bulk-append filled rectangles (Pillow-inclusive boxes) from arrays.

        For data-driven fields such as waveform bars: one numpy pass instead
        of one Python call per bar.  ``rgba`` is ``(n, 4)`` or ``(4,)``.
        """
        n = int(np.size(x0))
        if n == 0:
            return
        out = np.zeros((n, FLOATS_PER_INSTANCE), dtype=np.float32)
        out[:, 0] = x0
        out[:, 1] = y0
        out[:, 2] = np.asarray(x1, dtype=np.float32) + 1.0
        out[:, 3] = np.asarray(y1, dtype=np.float32) + 1.0
        out[:, 4:8] = rgba
        out[:, 14] = KIND_RECT
        out[:, 15] = self._compat
        self._buf.frombytes(out.tobytes())

    # -- measurement (ImageDraw API) -------------------------------------------

    def textlength(self, text: str, font: Any = None, *args: Any, **kw: Any) -> float:
        return self.atlas._measure.textlength(text, font, *args, **kw)

    def textbbox(self, xy: Any, text: str, font: Any = None, *args: Any,
                 **kw: Any) -> tuple:
        return self.atlas._measure.textbbox(xy, text, font, *args, **kw)

    def multiline_textbbox(self, xy: Any, text: str, font: Any = None,
                           *args: Any, **kw: Any) -> tuple:
        return self.atlas._measure.multiline_textbbox(xy, text, font, *args, **kw)


# ---------------------------------------------------------------------------
# GL renderer
# ---------------------------------------------------------------------------

_VERTEX_SHADER = """
#version 330
// Vertex stage — expands one unit-quad corner per vertex into the screen
// rect (or oriented line quad) of its instance.  Instance attributes are
// DrawList's 20 floats as five vec4s; uResolution is the frame size in
// pixels.  Outputs the pixel-space position used by the SDFs below.
layout(location = 0) in vec2 in_corner;
layout(location = 1) in vec4 i_box;
layout(location = 2) in vec4 i_fill;
layout(location = 3) in vec4 i_line;
layout(location = 4) in vec4 i_param;
layout(location = 5) in vec4 i_uv;
uniform vec2 uResolution;
out vec2 v_pos;
out vec2 v_tex;
flat out vec4 v_box;
flat out vec4 v_fill;
flat out vec4 v_line;
flat out vec4 v_param;
flat out vec4 v_uv;
void main() {
    int kind = int(i_param.z + 0.5);
    vec2 pos;
    if (kind == 2) {
        vec2 d = i_box.zw - i_box.xy;
        float len = length(d);
        vec2 dir = len > 1e-4 ? d / len : vec2(1.0, 0.0);
        vec2 nrm = vec2(-dir.y, dir.x);
        float hw = max(i_param.y, 1.0) * 0.5 + 1.0;
        float along = mix(-1.5, len + 1.5, in_corner.x);
        float across = mix(-hw, hw, in_corner.y);
        pos = i_box.xy + dir * along + nrm * across;
        v_pos = vec2(along, across);
    } else if (kind == 3) {
        pos = mix(i_box.xy, i_box.zw, in_corner);
        v_pos = pos;
        v_tex = mix(i_uv.xy, i_uv.zw, in_corner);
    } else {
        pos = mix(i_box.xy - 1.0, i_box.zw + 1.0, in_corner);
        v_pos = pos;
    }
    v_box = i_box;
    v_fill = i_fill / 255.0;
    v_line = i_line / 255.0;
    if (i_param.w > 0.5 && kind != 3) {     // Pillow RGBA overwrite semantics
        v_fill.a = i_fill.a > 0.0 ? 1.0 : 0.0;
        v_line.a = i_line.a > 0.0 ? 1.0 : 0.0;
    }
    v_param = i_param;
    v_uv = i_uv;
    vec2 ndc = pos / uResolution * 2.0 - 1.0;
    gl_Position = vec4(ndc.x, -ndc.y, 0.0, 1.0);
}
"""

_FRAGMENT_SHADER = """
#version 330
// Fragment stage — per-kind signed distance in pixels, turned into
// coverage (0.5 - d gives pixel-exact axis-aligned edges and a 1px AA
// ramp on curves), then fill and inward outline bands are composited.
// Expects uAtlas (text/images, sampled for kind 3).  Writes fragColor as
// straight alpha for SRC_ALPHA / ONE_MINUS_SRC_ALPHA blending.
uniform sampler2D uAtlas;
in vec2 v_pos;
in vec2 v_tex;
flat in vec4 v_box;
flat in vec4 v_fill;
flat in vec4 v_line;
flat in vec4 v_param;
flat in vec4 v_uv;
out vec4 fragColor;

float sdRoundBox(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

float sdEllipse(vec2 p, vec2 ab) {
    float k0 = length(p / ab);
    float k1 = length(p / (ab * ab));
    return k1 > 1e-6 ? k0 * (k0 - 1.0) / k1 : -min(ab.x, ab.y);
}

bool inArc(vec2 p, float start, float end) {
    float span = end - start;
    if (span >= 360.0 || span <= -360.0) return true;
    span = mod(span, 360.0);
    float ang = degrees(atan(p.y, p.x));
    return mod(ang - start, 360.0) <= span;
}

void main() {
    int kind = int(v_param.z + 0.5);
    if (kind == 3) {
        vec4 t = texture(uAtlas, v_tex);
        fragColor = vec4(t.rgb * v_fill.rgb, t.a * v_fill.a);
        return;
    }
    float w = v_param.y;
    if (kind == 2) {
        float len = length(v_box.zw - v_box.xy);
        float d = sdRoundBox(v_pos - vec2(len * 0.5, 0.0),
                             vec2(len * 0.5 + 0.5, max(w, 1.0) * 0.5), 0.0);
        fragColor = vec4(v_fill.rgb, v_fill.a * clamp(0.5 - d, 0.0, 1.0));
        return;
    }
    vec2 center = (v_box.xy + v_box.zw) * 0.5;
    vec2 halfsz = max((v_box.zw - v_box.xy) * 0.5, vec2(0.5));
    vec2 p = v_pos - center;
    float d = (kind == 0)
        ? sdRoundBox(p, halfsz, min(v_param.x, min(halfsz.x, halfsz.y)))
        : sdEllipse(p, halfsz);
    float cov = clamp(0.5 - d, 0.0, 1.0);
    if (kind == 4) {          // arc: an outline band only, angle-limited
        if (!inArc(p, v_uv.x, v_uv.y)) discard;
        float band = cov - clamp(0.5 - (d + max(w, 1.0)), 0.0, 1.0);
        fragColor = vec4(v_fill.rgb, v_fill.a * band);
        return;
    }
    if (kind == 5 && !inArc(p, v_uv.x, v_uv.y)) discard;
    float inner = (w > 0.0 && v_line.a > 0.0)
        ? clamp(0.5 - (d + w), 0.0, 1.0) : cov;
    float band = cov - inner;
    float a = v_fill.a * inner + v_line.a * band;
    if (a <= 0.0) discard;
    vec3 rgb = (v_fill.rgb * v_fill.a * inner + v_line.rgb * v_line.a * band) / a;
    fragColor = vec4(rgb, a);
}
"""

_GL_FLOAT = 0x1406
_GL_UNSIGNED_BYTE = 0x1401
_GL_TEXTURE_2D = 0x0DE1
_GL_TEXTURE0 = 0x84C0
_GL_RGBA = 0x1908
_GL_RGBA8 = 0x8058
_GL_TEXTURE_MIN_FILTER = 0x2801
_GL_TEXTURE_MAG_FILTER = 0x2800
_GL_NEAREST = 0x2600
_GL_LINEAR = 0x2601
_GL_TEXTURE_WRAP_S = 0x2802
_GL_TEXTURE_WRAP_T = 0x2803
_GL_CLAMP_TO_EDGE = 0x812F
_GL_ARRAY_BUFFER = 0x8892
_GL_STATIC_DRAW = 0x88E4
_GL_STREAM_DRAW = 0x88E0
_GL_VERTEX_SHADER = 0x8B31
_GL_FRAGMENT_SHADER = 0x8B30
_GL_COMPILE_STATUS = 0x8B81
_GL_LINK_STATUS = 0x8B82
_GL_TRIANGLE_STRIP = 0x0005
_GL_COLOR_BUFFER_BIT = 0x00004000
_GL_BLEND = 0x0BE2
_GL_SRC_ALPHA = 0x0302
_GL_ONE_MINUS_SRC_ALPHA = 0x0303
_GL_ONE = 1
_GL_UNPACK_ALIGNMENT = 0x0CF5
_GL_PACK_ALIGNMENT = 0x0D05
_GL_SCISSOR_TEST = 0x0C11
_GL_DEPTH_TEST = 0x0B71

_c = ctypes
_GL_FUNCTIONS: dict[str, tuple] = {
    'glViewport': (None, _c.c_int, _c.c_int, _c.c_int, _c.c_int),
    'glClearColor': (None, _c.c_float, _c.c_float, _c.c_float, _c.c_float),
    'glClear': (None, _c.c_uint),
    'glEnable': (None, _c.c_uint),
    'glDisable': (None, _c.c_uint),
    'glBlendFuncSeparate': (None, _c.c_uint, _c.c_uint, _c.c_uint, _c.c_uint),
    'glPixelStorei': (None, _c.c_uint, _c.c_int),
    'glGenTextures': (None, _c.c_int, _c.POINTER(_c.c_uint)),
    'glDeleteTextures': (None, _c.c_int, _c.POINTER(_c.c_uint)),
    'glBindTexture': (None, _c.c_uint, _c.c_uint),
    'glActiveTexture': (None, _c.c_uint),
    'glTexParameteri': (None, _c.c_uint, _c.c_uint, _c.c_int),
    'glTexImage2D': (None, _c.c_uint, _c.c_int, _c.c_int, _c.c_int, _c.c_int,
                     _c.c_int, _c.c_uint, _c.c_uint, _c.c_void_p),
    'glTexSubImage2D': (None, _c.c_uint, _c.c_int, _c.c_int, _c.c_int, _c.c_int,
                        _c.c_int, _c.c_uint, _c.c_uint, _c.c_void_p),
    'glGenBuffers': (None, _c.c_int, _c.POINTER(_c.c_uint)),
    'glDeleteBuffers': (None, _c.c_int, _c.POINTER(_c.c_uint)),
    'glBindBuffer': (None, _c.c_uint, _c.c_uint),
    'glBufferData': (None, _c.c_uint, _c.c_ssize_t, _c.c_void_p, _c.c_uint),
    'glGenVertexArrays': (None, _c.c_int, _c.POINTER(_c.c_uint)),
    'glDeleteVertexArrays': (None, _c.c_int, _c.POINTER(_c.c_uint)),
    'glBindVertexArray': (None, _c.c_uint),
    'glEnableVertexAttribArray': (None, _c.c_uint),
    'glVertexAttribPointer': (None, _c.c_uint, _c.c_int, _c.c_uint, _c.c_uint8,
                              _c.c_int, _c.c_void_p),
    'glVertexAttribDivisor': (None, _c.c_uint, _c.c_uint),
    'glCreateShader': (_c.c_uint, _c.c_uint),
    'glDeleteShader': (None, _c.c_uint),
    'glShaderSource': (None, _c.c_uint, _c.c_int, _c.POINTER(_c.c_char_p),
                       _c.POINTER(_c.c_int)),
    'glCompileShader': (None, _c.c_uint),
    'glGetShaderiv': (None, _c.c_uint, _c.c_uint, _c.POINTER(_c.c_int)),
    'glGetShaderInfoLog': (None, _c.c_uint, _c.c_int, _c.POINTER(_c.c_int), _c.c_char_p),
    'glCreateProgram': (_c.c_uint,),
    'glDeleteProgram': (None, _c.c_uint),
    'glAttachShader': (None, _c.c_uint, _c.c_uint),
    'glLinkProgram': (None, _c.c_uint),
    'glGetProgramiv': (None, _c.c_uint, _c.c_uint, _c.POINTER(_c.c_int)),
    'glGetProgramInfoLog': (None, _c.c_uint, _c.c_int, _c.POINTER(_c.c_int), _c.c_char_p),
    'glUseProgram': (None, _c.c_uint),
    'glGetUniformLocation': (_c.c_int, _c.c_uint, _c.c_char_p),
    'glUniform1i': (None, _c.c_int, _c.c_int),
    'glUniform2f': (None, _c.c_int, _c.c_float, _c.c_float),
    'glDrawArraysInstanced': (None, _c.c_uint, _c.c_int, _c.c_int, _c.c_int),
    'glReadPixels': (None, _c.c_int, _c.c_int, _c.c_int, _c.c_int, _c.c_uint,
                     _c.c_uint, _c.c_void_p),
    'glFinish': (None,),
}

_UNIT_QUAD = (ctypes.c_float * 8)(0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0)


class Batch2DRenderer:
    """Draws :class:`GpuFrame` s with one instanced call, in one GL context.

    Lifecycle: :meth:`create` with the target context current, then
    :meth:`draw` per frame and :meth:`release` before the context dies --
    all on the thread that owns that context.  ``get_proc`` resolves GL
    entry points (default ``sdl2.SDL_GL_GetProcAddress``).
    """

    def __init__(self, get_proc: Callable[[bytes], int] | None = None) -> None:
        self._get_proc = get_proc
        self._fn: dict[str, Any] = {}
        self._program = 0
        self._vao = 0
        self._quad_vbo = 0
        self._inst_vbo = 0
        self._atlas_tex = 0
        self._atlas_size = (0, 0)
        self._atlas_gen = -1
        self._u_res = -1
        self._filter = 0

    @property
    def ready(self) -> bool:
        return bool(self._program)

    def create(self, atlas_width: int = ATLAS_W, atlas_height: int = ATLAS_H) -> None:
        """Compile the program and allocate buffers + the atlas texture."""
        get_proc = self._get_proc
        if get_proc is None:
            import sdl2  # noqa: PLC0415 - only needed on the real GL path
            get_proc = sdl2.SDL_GL_GetProcAddress
        for name, (restype, *argtypes) in _GL_FUNCTIONS.items():
            addr = get_proc(name.encode())
            if not addr:
                raise RuntimeError(f'gpu2d: GL entry point {name} unavailable')
            self._fn[name] = ctypes.CFUNCTYPE(restype, *argtypes)(addr)
        fn = self._fn
        self._program = self._link(_VERTEX_SHADER, _FRAGMENT_SHADER)
        fn['glUseProgram'](self._program)
        self._u_res = fn['glGetUniformLocation'](self._program, b'uResolution')
        fn['glUniform1i'](fn['glGetUniformLocation'](self._program, b'uAtlas'), 0)

        self._vao = self._gen(fn['glGenVertexArrays'])
        fn['glBindVertexArray'](self._vao)
        self._quad_vbo = self._gen(fn['glGenBuffers'])
        fn['glBindBuffer'](_GL_ARRAY_BUFFER, self._quad_vbo)
        fn['glBufferData'](_GL_ARRAY_BUFFER, ctypes.sizeof(_UNIT_QUAD),
                           ctypes.cast(_UNIT_QUAD, ctypes.c_void_p), _GL_STATIC_DRAW)
        fn['glEnableVertexAttribArray'](0)
        fn['glVertexAttribPointer'](0, 2, _GL_FLOAT, 0, 8, None)
        self._inst_vbo = self._gen(fn['glGenBuffers'])
        fn['glBindBuffer'](_GL_ARRAY_BUFFER, self._inst_vbo)
        stride = FLOATS_PER_INSTANCE * 4
        for loc in range(1, 6):
            fn['glEnableVertexAttribArray'](loc)
            fn['glVertexAttribPointer'](loc, 4, _GL_FLOAT, 0, stride,
                                        ctypes.c_void_p((loc - 1) * 16))
            fn['glVertexAttribDivisor'](loc, 1)

        self._atlas_tex = self._gen(fn['glGenTextures'])
        fn['glActiveTexture'](_GL_TEXTURE0)
        fn['glBindTexture'](_GL_TEXTURE_2D, self._atlas_tex)
        fn['glTexParameteri'](_GL_TEXTURE_2D, _GL_TEXTURE_WRAP_S, _GL_CLAMP_TO_EDGE)
        fn['glTexParameteri'](_GL_TEXTURE_2D, _GL_TEXTURE_WRAP_T, _GL_CLAMP_TO_EDGE)
        self._set_filter(_GL_NEAREST)
        fn['glTexImage2D'](_GL_TEXTURE_2D, 0, _GL_RGBA8, atlas_width, atlas_height,
                           0, _GL_RGBA, _GL_UNSIGNED_BYTE, None)
        self._atlas_size = (atlas_width, atlas_height)
        fn['glPixelStorei'](_GL_UNPACK_ALIGNMENT, 1)

    def _set_filter(self, mode: int) -> None:
        if self._filter == mode:
            return
        self._fn['glTexParameteri'](_GL_TEXTURE_2D, _GL_TEXTURE_MIN_FILTER, mode)
        self._fn['glTexParameteri'](_GL_TEXTURE_2D, _GL_TEXTURE_MAG_FILTER, mode)
        self._filter = mode

    @staticmethod
    def _gen(gen_fn: Any) -> int:
        out = ctypes.c_uint(0)
        gen_fn(1, ctypes.byref(out))
        return int(out.value)

    def _compile(self, kind: int, src: str) -> int:
        fn = self._fn
        shader = fn['glCreateShader'](kind)
        buf = ctypes.c_char_p(src.encode())
        fn['glShaderSource'](shader, 1, ctypes.byref(buf), None)
        fn['glCompileShader'](shader)
        ok = ctypes.c_int(0)
        fn['glGetShaderiv'](shader, _GL_COMPILE_STATUS, ctypes.byref(ok))
        if not ok.value:
            logbuf = ctypes.create_string_buffer(4096)
            fn['glGetShaderInfoLog'](shader, 4096, None, logbuf)
            fn['glDeleteShader'](shader)
            raise RuntimeError(f'gpu2d: shader compile failed: {logbuf.value.decode(errors="replace")}')
        return shader

    def _link(self, vs_src: str, fs_src: str) -> int:
        fn = self._fn
        vs = self._compile(_GL_VERTEX_SHADER, vs_src)
        fs = self._compile(_GL_FRAGMENT_SHADER, fs_src)
        prog = fn['glCreateProgram']()
        fn['glAttachShader'](prog, vs)
        fn['glAttachShader'](prog, fs)
        fn['glLinkProgram'](prog)
        fn['glDeleteShader'](vs)
        fn['glDeleteShader'](fs)
        ok = ctypes.c_int(0)
        fn['glGetProgramiv'](prog, _GL_LINK_STATUS, ctypes.byref(ok))
        if not ok.value:
            logbuf = ctypes.create_string_buffer(4096)
            fn['glGetProgramInfoLog'](prog, 4096, None, logbuf)
            fn['glDeleteProgram'](prog)
            raise RuntimeError(f'gpu2d: program link failed: {logbuf.value.decode(errors="replace")}')
        return prog

    def apply_patches(self, patches: list[tuple]) -> None:
        """Upload queued atlas patches (see :meth:`TextureAtlas.take_patches`)."""
        if not patches:
            return
        fn = self._fn
        fn['glActiveTexture'](_GL_TEXTURE0)
        fn['glBindTexture'](_GL_TEXTURE_2D, self._atlas_tex)
        for patch in patches:
            if patch[0] == 'reset':
                self._atlas_gen = patch[1]
                continue
            _, x, y, w, h, data = patch
            fn['glTexSubImage2D'](_GL_TEXTURE_2D, 0, x, y, w, h, _GL_RGBA,
                                  _GL_UNSIGNED_BYTE, data)

    def draw(self, frame: GpuFrame, patches: list[tuple],
             viewport_w: int, viewport_h: int) -> bool:
        """Upload ``patches`` then draw ``frame`` to the current framebuffer.

        Returns False (nothing drawn) when the frame predates the newest
        atlas reset the renderer has applied.
        """
        fn = self._fn
        if self._atlas_gen < 0:
            self._atlas_gen = frame.atlas_generation
        self.apply_patches(patches)
        if frame.atlas_generation != self._atlas_gen:
            return False
        fn['glViewport'](0, 0, int(viewport_w), int(viewport_h))
        fn['glDisable'](_GL_SCISSOR_TEST)
        fn['glDisable'](_GL_DEPTH_TEST)
        r, g, b, a = frame.clear
        fn['glClearColor'](r / 255.0, g / 255.0, b / 255.0, a / 255.0)
        fn['glClear'](_GL_COLOR_BUFFER_BIT)
        if frame.count:
            fn['glEnable'](_GL_BLEND)
            fn['glBlendFuncSeparate'](_GL_SRC_ALPHA, _GL_ONE_MINUS_SRC_ALPHA,
                                      _GL_ONE, _GL_ONE_MINUS_SRC_ALPHA)
            fn['glUseProgram'](self._program)
            fn['glUniform2f'](self._u_res, float(frame.width), float(frame.height))
            fn['glActiveTexture'](_GL_TEXTURE0)
            fn['glBindTexture'](_GL_TEXTURE_2D, self._atlas_tex)
            scaled = (int(viewport_w), int(viewport_h)) != (frame.width, frame.height)
            self._set_filter(_GL_LINEAR if scaled else _GL_NEAREST)
            fn['glBindVertexArray'](self._vao)
            fn['glBindBuffer'](_GL_ARRAY_BUFFER, self._inst_vbo)
            addr, _ = frame.instances.buffer_info()
            fn['glBufferData'](_GL_ARRAY_BUFFER, frame.count * FLOATS_PER_INSTANCE * 4,
                               ctypes.c_void_p(addr), _GL_STREAM_DRAW)
            fn['glDrawArraysInstanced'](_GL_TRIANGLE_STRIP, 0, 4, frame.count)
            fn['glDisable'](_GL_BLEND)
        return True

    def read_pixels(self, width: int, height: int) -> np.ndarray:
        """Read the framebuffer back as a top-down ``(h, w, 4)`` uint8 array
        (tests and screenshots; stalls the pipeline, never per frame)."""
        fn = self._fn
        out = np.empty((height, width, 4), dtype=np.uint8)
        fn['glPixelStorei'](_GL_PACK_ALIGNMENT, 1)
        fn['glFinish']()
        fn['glReadPixels'](0, 0, width, height, _GL_RGBA, _GL_UNSIGNED_BYTE,
                           out.ctypes.data_as(ctypes.c_void_p))
        return out[::-1].copy()

    def release(self) -> None:
        """Delete every GL object (context must be current).  Idempotent."""
        fn = self._fn
        if not fn:
            return
        try:
            for name, handle in (('glDeleteTextures', self._atlas_tex),
                                 ('glDeleteBuffers', self._inst_vbo),
                                 ('glDeleteBuffers', self._quad_vbo),
                                 ('glDeleteVertexArrays', self._vao)):
                if handle:
                    h = ctypes.c_uint(handle)
                    fn[name](1, ctypes.byref(h))
            if self._program:
                fn['glDeleteProgram'](self._program)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning('gpu2d: release failed: %s', exc)
        self._program = self._vao = self._quad_vbo = self._inst_vbo = 0
        self._atlas_tex = 0
        self._atlas_gen = -1
        self._filter = 0
        self._fn = {}
