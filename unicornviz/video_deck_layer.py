"""Music-video decks: the composite layer that draws a DJ deck's video.

Part of the music-video-decks feature
(docs/planning/music-video-decks-plan-2026-09-13.md, section 3).  The
DJ mixer publishes per-deck state on the ``vj_api`` deck-state bus at
frame rate; the videos-01 drop-in supplies ``DeckVideoSource``, a
deck-clocked frame cache for one file.  This layer sits between them and
owns exactly three jobs:

1. **Source lifecycle** -- one ``DeckVideoSource`` per deck that has a
   video path, opened on first sight and closed when the deck's path
   changes or clears.  At most two are open at once.
2. **Frame delivery** -- every frame, tell each source where the deck's
   playhead is (``set_target``), take the nearest cached frame
   (``frame_for``), and upload it to that deck's RGB texture *only when
   the frame's pts changed*.  An identical frame is never re-uploaded.
3. **Compositing** -- draw each visible deck as a letterboxed fullscreen
   quad at opacity = the deck's audibility, decks in a/b/c/d order.
   Below ``_MIN_OPACITY`` the draw is skipped entirely.

The visualizer keeps rendering underneath at every opacity (owner
decision 3: measure, don't optimize yet), and the layer reports its own
per-frame cost so the frame profiler can show it as ``video_decks``.

The frame-source class is **injected**, so the layer is unit-tested with
a fake source and a fake GL context; when the class is ``None`` (videos-01
absent) every method is a no-op and the layer costs nothing.

Threading: ``update()`` and ``draw()`` run on the GL thread.  The source
decodes on its own worker; ``frame_for`` is documented never to block.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable

import numpy as np

log = logging.getLogger(__name__)

#: Deck order for drawing and reporting.
DECK_ORDER: tuple[str, ...] = ('a', 'b', 'c', 'd')
#: Below this audibility a deck's quad is not drawn at all.
_MIN_OPACITY = 0.005
#: How many decks may hold an open video source at once.
_MAX_SOURCES = 2
#: Set to a file path to append one JSON line per frame per visible deck
#: (deck, position_s, rate, playing, pts shown, upload_ms, opacity).  Part-B
#: measurement only: A/V mapping and upload cost.  Off unless set.
_TRACE_ENV = 'UNICORNVIZ_VIDEO_DECKS_TRACE'

_VERT = """
#version 330
// Vertex shader -- letterboxed quad.  uScale is the quad's half-extent in
// NDC (1,1 = fullscreen); v_uv is flipped so a top-down rgb24 frame
// uploaded row-0-first reads the right way up.
in vec2 in_vert;
uniform vec2 uScale;
out vec2 v_uv;
void main() {
    v_uv = vec2(in_vert.x * 0.5 + 0.5, 0.5 - in_vert.y * 0.5);
    gl_Position = vec4(in_vert * uScale, 0.0, 1.0);
}
"""

_FRAG = """
#version 330
// Fragment shader -- the deck's frame at uOpacity (blended over whatever
// the visualizer already drew into the target).
uniform sampler2D tex;
uniform float uOpacity;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    fragColor = vec4(texture(tex, v_uv).rgb, uOpacity);
}
"""


class _DeckSlot:
    """Per-deck state the layer keeps between frames."""

    __slots__ = ('path', 'source', 'texture', 'tex_size', 'last_pts',
                 'opacity', 'has_frame', 'stats')

    def __init__(self) -> None:
        self.path: str = ''
        self.source: Any = None
        self.texture: Any = None
        self.tex_size: tuple[int, int] = (0, 0)
        self.last_pts: float | None = None
        self.opacity: float = 0.0
        self.has_frame: bool = False
        self.stats: dict = {}


class VideoDeckLayer:
    """Draw the DJ decks' videos as a composite layer.  See module docstring."""

    def __init__(
        self,
        ctx: Any,
        source_cls: Callable[..., Any] | None,
        *,
        enabled: bool = True,
        postfx_over_video: bool = True,
        cache_window_s: float = 4.0,
        cache_long_edge: int = 720,
        log_interval_s: float = 1.0,
    ) -> None:
        self._ctx = ctx
        self._source_cls = source_cls
        self.enabled = bool(enabled) and source_cls is not None and ctx is not None
        self._postfx_over_video = bool(postfx_over_video)
        self._cache_window_s = float(cache_window_s)
        self._cache_long_edge = int(cache_long_edge)
        self._log_interval_s = max(0.2, float(log_interval_s))
        self._slots: dict[str, _DeckSlot] = {k: _DeckSlot() for k in DECK_ORDER}
        self._prog: Any = None
        self._vbo: Any = None
        self._vao: Any = None
        self._last_update_ms = 0.0
        self._last_draw_ms = 0.0
        self._next_log_t = 0.0
        self._cap_warned = False
        self._last_upload_ms = 0.0          # this frame's texture uploads, summed
        self._upload_ms_total = 0.0
        self._upload_count = 0
        trace = os.environ.get(_TRACE_ENV, '').strip()
        self._trace = open(trace, 'a', encoding='utf-8') if trace else None  # noqa: SIM115
        if self._source_cls is None:
            log.info('Video decks: DeckVideoSource unavailable (videos-01 absent); layer disabled')
        if self.enabled:
            # Compile now, not on the first frame a video becomes visible:
            # a shader compile mid-show is a hitch on the first fade-in.
            t0 = time.perf_counter()
            try:
                self._ensure_program()
                log.info('Video decks: layer program ready (%.1f ms)', (time.perf_counter() - t0) * 1000.0)
            except Exception as exc:
                log.warning('Video decks: shader build failed, layer disabled: %s', exc)
                self.enabled = False

    # -- properties read by the app / vj_api ---------------------------------

    @property
    def postfx_over_video(self) -> bool:
        """True when the layer draws *before* the post-FX chain (default)."""
        return self._postfx_over_video

    @postfx_over_video.setter
    def postfx_over_video(self, value: bool) -> None:
        self._postfx_over_video = bool(value)

    @property
    def active(self) -> bool:
        """True when at least one deck would actually be drawn this frame."""
        return any(self._visible(s) for s in self._slots.values())

    @property
    def layer_opacity(self) -> float:
        """Max audibility over the decks that would be drawn; 0.0 otherwise."""
        vis = [s.opacity for s in self._slots.values() if self._visible(s)]
        return max(vis) if vis else 0.0

    @property
    def last_upload_ms(self) -> float:
        """Texture upload time this frame (all decks), separate from draw."""
        return self._last_upload_ms

    @property
    def last_frame_ms(self) -> float:
        """Cost of this frame's update + draw, for the ``video_decks`` profiler stage."""
        return self._last_update_ms + self._last_draw_ms

    def status_pill(self) -> str | None:
        """``VIDEO A 82%`` (``VIDEO A 82% B 31%`` with two) while any deck is visible."""
        parts = [f'{k.upper()} {int(round(s.opacity * 100.0))}%'
                 for k, s in self._slots.items() if self._visible(s)]
        return 'VIDEO ' + '  '.join(parts) if parts else None

    # -- per-frame ------------------------------------------------------------

    def update(self, deck_state: dict | None) -> None:
        """Reconcile sources with the published deck state and fetch frames.

        *deck_state* is what ``get_deck_state()`` returned (or None).  The
        per-deck records are accepted in any of the shapes a publisher may
        reasonably use -- ``{'decks': {'a': {...}}}``, ``{'decks': [{'deck':
        'a', ...}]}`` or deck letters at the top level -- so the layer does
        not have to change when the mixer's wire format settles.
        """
        if not self.enabled:
            return
        if deck_state is None and not any(sl.source is not None for sl in self._slots.values()):
            # Audio-only night: no publisher, nothing open -- a null check and out.
            self._last_update_ms = 0.0
            return
        t0 = time.perf_counter()
        self._last_upload_ms = 0.0
        decks = self._normalize(deck_state)
        for key in DECK_ORDER:
            self._reconcile(key, decks.get(key))
            if self._trace is not None:
                self._trace_frame(key, decks.get(key))
        self._last_update_ms = (time.perf_counter() - t0) * 1000.0
        self._maybe_log()

    def draw(self, width: int, height: int) -> None:
        """Draw every visible deck into the currently bound target.

        Caller binds the framebuffer and sets the viewport; this only
        draws.  Decks go in a/b/c/d order so a later deck composites over
        an earlier one, the same order the mixer sums audio.
        """
        if not self.enabled or width <= 0 or height <= 0:
            self._last_draw_ms = 0.0
            return
        t0 = time.perf_counter()
        drawn = 0
        for key in DECK_ORDER:
            slot = self._slots[key]
            if not self._visible(slot):
                continue
            if drawn == 0:
                self._ensure_program()
                # GL state contract with the composite chain: the app's
                # _normalize_gl_render_state() baseline is BLEND *off* with
                # SRC_ALPHA/ONE_MINUS_SRC_ALPHA, effects are expected to
                # leave it that way, and the post passes write opaque quads
                # that do not depend on BLEND.  So enabling here and disabling
                # at the end returns the chain to its own baseline; moderngl
                # exposes no getter for the enable flags to "restore" from.
                self._ctx.enable(self._blend_flag())
                self._ctx.blend_func = self._blend_func()
            tw, th = slot.tex_size
            scale = min(width / float(tw), height / float(th))
            self._prog['uScale'].value = (tw * scale / width, th * scale / height)
            self._prog['uOpacity'].value = float(slot.opacity)
            slot.texture.use(location=0)
            self._prog['tex'].value = 0
            self._vao.render(self._triangle_strip())
            drawn += 1
        if drawn:
            self._ctx.disable(self._blend_flag())
        self._last_draw_ms = (time.perf_counter() - t0) * 1000.0

    def _trace_frame(self, key: str, rec: dict | None) -> None:
        slot = self._slots[key]
        if rec is None or slot.source is None:
            return
        try:
            self._trace.write(json.dumps({
                't': time.monotonic(), 'deck': key,
                'position_s': float(rec.get('position_s', 0.0) or 0.0),
                'rate': float(rec.get('rate', 1.0) or 0.0),
                'playing': bool(rec.get('playing', False)),
                'pts': slot.last_pts, 'opacity': slot.opacity,
                'latency_s': float(rec.get('latency_s', 0.0) or 0.0),
                'upload_ms': self._last_upload_ms,
            }) + '\n')
        except Exception:
            pass

    def destroy(self) -> None:
        """Close every source and release GL objects.  Idempotent."""
        if self._trace is not None:
            try:
                self._trace.close()
            except Exception:
                pass
            self._trace = None
        for key, slot in self._slots.items():
            self._close_slot(key, slot, reason='shutdown')
        for obj in (self._vao, self._vbo, self._prog):
            if obj is not None:
                try:
                    obj.release()
                except Exception:
                    pass
        self._vao = self._vbo = self._prog = None

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _visible(slot: _DeckSlot) -> bool:
        return slot.has_frame and slot.texture is not None and slot.opacity >= _MIN_OPACITY

    @staticmethod
    def _normalize(deck_state: dict | None) -> dict[str, dict]:
        if not isinstance(deck_state, dict):
            return {}
        decks = deck_state.get('decks', deck_state)
        out: dict[str, dict] = {}
        if isinstance(decks, dict):
            for k, v in decks.items():
                if isinstance(v, dict) and str(k).lower() in DECK_ORDER:
                    out[str(k).lower()] = v
        elif isinstance(decks, (list, tuple)):
            for v in decks:
                if isinstance(v, dict):
                    k = str(v.get('deck', '')).lower()
                    if k in DECK_ORDER:
                        out[k] = v
        return out

    def _reconcile(self, key: str, rec: dict | None) -> None:
        slot = self._slots[key]
        path = ''
        if rec is not None and bool(rec.get('has_video', False)):
            path = str(rec.get('path') or '')
        if path != slot.path:
            if slot.source is not None:
                self._close_slot(key, slot, reason='path changed' if path else 'deck cleared')
            slot.path = path
            if path and not self._open_slot(key, slot, path):
                # Refused at the source cap: leave the path unrecorded so the
                # deck is retried next frame and picks a source up as soon as
                # another deck lets one go (a failed *open* keeps the path;
                # see the open_error branch below).
                slot.path = ''
        if slot.source is None or rec is None:
            slot.opacity = 0.0
            return
        # videos-01 0.8.2: the constructor returns at once and a file that
        # cannot be opened reports through ``open_error`` instead of raising.
        # Close it and keep the path recorded, so the deck reads as no-video
        # until its path changes -- not a silent black quad, and not a retry
        # every frame.
        err = getattr(slot.source, 'open_error', None)
        if err:
            log.warning('Video decks: deck %s could not open %s: %s', key.upper(), slot.path, err)
            self._close_slot(key, slot, reason='open failed')
            return
        position = float(rec.get('position_s', 0.0) or 0.0)
        # A/V alignment.  The mixer's position is its *write* cursor; what is
        # audible is that minus the output stream's latency (its
        # prebuffer).  When the publisher includes it as ``latency_s`` the
        # frame is chosen for the audible instant, not the written one --
        # otherwise the picture leads the sound by the whole buffer.
        try:
            position -= max(0.0, float(rec.get('latency_s', 0.0) or 0.0))
        except (TypeError, ValueError):
            pass
        rate = float(rec.get('rate', 1.0) if rec.get('rate') is not None else 1.0)
        playing = bool(rec.get('playing', False))
        slot.opacity = max(0.0, min(1.0, float(rec.get('audibility', 0.0) or 0.0)))
        try:
            slot.source.set_target(position, rate, playing)
            got = slot.source.frame_for(position)
        except Exception as exc:
            log.warning('Video decks: source for deck %s failed (%s); closing it', key.upper(), exc)
            self._close_slot(key, slot, reason='source error')   # path kept: no reopen until it changes
            return
        if got is None:
            return
        pts, frame = got
        if slot.last_pts is not None and pts == slot.last_pts:
            return                       # same frame: no re-upload
        self._upload(slot, frame)
        slot.last_pts = float(pts)
        if not slot.has_frame:
            # The open is non-blocking, so this is the first moment the real
            # (post-downscale) frame size is known.
            log.info('Video decks: deck %s first frame %dx%d from %s',
                     key.upper(), slot.tex_size[0], slot.tex_size[1], slot.path)
        slot.has_frame = True

    def _open_slot(self, key: str, slot: _DeckSlot, path: str) -> bool:
        """Open a source for *path*; False only when refused at the cap."""
        open_count = sum(1 for s in self._slots.values() if s.source is not None)
        if open_count >= _MAX_SOURCES:
            if not self._cap_warned:
                self._cap_warned = True
                log.info('Video decks: %d sources already open; deck %s (%s) waits for one',
                         _MAX_SOURCES, key.upper(), path)
            return False
        self._cap_warned = False        # below the cap again: a later refusal logs again
        try:
            slot.source = self._source_cls(
                path,
                cache_window_s=self._cache_window_s,
                cache_long_edge=self._cache_long_edge,
            )
        except Exception as exc:
            log.warning('Video decks: could not open %s for deck %s: %s', path, key.upper(), exc)
            slot.source = None
            return True                 # opened-and-failed, not refused: keep the path
        # (5) no size here: the open is non-blocking and the size is not known
        # until the worker publishes it; the first upload logs "first frame WxH".
        log.info('Video decks: deck %s opened %s', key.upper(), path)
        slot.last_pts = None
        slot.has_frame = False
        return True

    def _close_slot(self, key: str, slot: _DeckSlot, *, reason: str) -> None:
        src = slot.source
        if src is not None:
            try:
                src.close()
            except Exception as exc:
                log.debug('Video decks: close for deck %s raised: %s', key.upper(), exc)
            size = getattr(src, 'size', (0, 0))
            log.info('Video decks: deck %s closed %s (%dx%d): %s',
                     key.upper(), slot.path, size[0], size[1], reason)
        slot.source = None
        slot.has_frame = False
        slot.last_pts = None
        slot.opacity = 0.0
        slot.stats = {}
        if slot.texture is not None:
            try:
                slot.texture.release()
            except Exception:
                pass
            slot.texture = None
            slot.tex_size = (0, 0)

    def _upload(self, slot: _DeckSlot, frame: np.ndarray) -> None:
        h, w = int(frame.shape[0]), int(frame.shape[1])
        if slot.texture is None or slot.tex_size != (w, h):
            if slot.texture is not None:
                try:
                    slot.texture.release()
                except Exception:
                    pass
            slot.texture = self._ctx.texture((w, h), 3)
            try:
                slot.texture.filter = (self._linear(), self._linear())
            except Exception:
                pass
            slot.tex_size = (w, h)
        data = frame if frame.flags['C_CONTIGUOUS'] else np.ascontiguousarray(frame)
        t0 = time.perf_counter()
        slot.texture.write(data)
        ms = (time.perf_counter() - t0) * 1000.0
        self._last_upload_ms += ms
        self._upload_ms_total += ms
        self._upload_count += 1

    def _ensure_program(self) -> None:
        if self._prog is not None:
            return
        self._prog = self._ctx.program(vertex_shader=_VERT, fragment_shader=_FRAG)
        verts = np.array([-1, -1, -1, 1, 1, -1, 1, 1], dtype=np.float32)
        self._vbo = self._ctx.buffer(verts)
        self._vao = self._ctx.vertex_array(self._prog, [(self._vbo, '2f', 'in_vert')])

    def _maybe_log(self) -> None:
        if not log.isEnabledFor(logging.DEBUG):
            return
        now = time.monotonic()
        if now < self._next_log_t:
            return
        self._next_log_t = now + self._log_interval_s
        parts = []
        for key, slot in self._slots.items():
            if slot.source is None:
                continue
            stats_fn = getattr(slot.source, 'stats', None)
            stats = stats_fn() if callable(stats_fn) else {}
            slot.stats = stats if isinstance(stats, dict) else {}
            parts.append(
                f'{key.upper()} op={slot.opacity:.2f} pts='
                f'{"-" if slot.last_pts is None else f"{slot.last_pts:.3f}"} '
                f'hit={slot.stats.get("hits", 0)} miss={slot.stats.get("misses", 0)} '
                f'seek={slot.stats.get("seeks", 0)}'
            )
        if parts:
            log.debug('Video decks: %s | update=%.2fms draw=%.2fms upload_avg=%.3fms (n=%d)',
                      ' '.join(parts), self._last_update_ms, self._last_draw_ms,
                      (self._upload_ms_total / self._upload_count) if self._upload_count else 0.0,
                      self._upload_count)

    # moderngl constants, resolved lazily so the module imports without GL.
    @staticmethod
    def _blend_flag() -> int:
        import moderngl  # noqa: PLC0415
        return moderngl.BLEND

    @staticmethod
    def _blend_func() -> tuple[int, int]:
        import moderngl  # noqa: PLC0415
        return moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

    @staticmethod
    def _triangle_strip() -> int:
        import moderngl  # noqa: PLC0415
        return moderngl.TRIANGLE_STRIP

    @staticmethod
    def _linear() -> int:
        import moderngl  # noqa: PLC0415
        return moderngl.LINEAR
