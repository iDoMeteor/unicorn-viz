"""Shared hover-tooltip primitives for operator UI surfaces.

Why this exists
----------------
Three surfaces need tooltips — the main window's overlay modals,
control-room-01, and dj-mixer-01 — across two different render stacks
(moderngl immediate primitives on the main window; PIL rasterization on
background threads for the drop-in windows). This module owns the parts
they can share without coupling core to any drop-in:

- :class:`TooltipRegion` — one hoverable rect plus its text.
- :class:`TooltipHoverTracker` — a pure hover state machine (no SDL, GL,
  or PIL imports) with an injected clock, so behavior is unit-testable
  without sleeping or faking a windowing system.
- :func:`draw_tooltip_pil` — the bubble renderer for PIL-based surfaces.
  GL-based surfaces (the overlay system) draw their own bubble with their
  existing primitives and only reuse the tracker.

Design notes (see docs/planning/tooltip-system-plan-2026-07-13.md):

- Region *content* stays with each surface; core owns timing and bubble
  geometry only, preserving the drop-in independence rules.
- Regions are rebuilt by their surfaces every layout pass, so the tracker
  identifies "the same control" by rect coordinates, not object identity.
- Hotkey hints are resolved by the caller (from the help registry) before
  the text reaches this module — key names are never hardcoded here.

Usage::

    tracker = TooltipHoverTracker(delay_s=0.55)
    # on every mouse-motion event (or once per frame on a render thread):
    tracker.on_motion(x, y, regions)
    # once per rendered frame:
    tip = tracker.tick()
    if tip is not None:
        draw_tooltip_pil(draw, tip.text, tracker.anchor, bounds,
                         font=font, colors=colors)
"""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import for annotations only
    from PIL import ImageDraw, ImageFont

# How long after a tooltip was last visible that moving onto an adjacent
# control uses the short rearm delay instead of the full initial delay.
_WARM_WINDOW_S = 0.5

# Cursor offset so the bubble doesn't sit under the pointer.
_ANCHOR_OFFSET_X = 14
_ANCHOR_OFFSET_Y = 20

_PAD_X = 10
_PAD_Y = 7
_LINE_GAP = 4
_BORDER_W = 2


@dataclass(slots=True, frozen=True)
class TooltipRegion:
    """One hoverable region: a rect in surface-pixel space plus its text.

    ``hotkey_ref`` optionally names a help-registry entry; the owning
    surface resolves it to a key hint before display (never hardcode key
    names in ``text``).
    """

    rect: tuple[int, int, int, int]  # x, y, w, h
    text: str
    hotkey_ref: str = ''

    def contains(self, x: float, y: float) -> bool:
        """Return True when (x, y) falls inside this region's rect."""
        rx, ry, rw, rh = self.rect
        return rx <= x <= rx + rw and ry <= y <= ry + rh


class TooltipHoverTracker:
    """Pure hover state machine: feed mouse positions, get the active
    tooltip back.

    Lifecycle per region: the cursor must rest inside one region for
    ``delay_s`` before its tooltip arms (cursor movement beyond
    ``jitter_px`` restarts the timer; leaving the region disarms).  Once
    visible, the tooltip stays while the cursor remains inside; moving
    directly onto another region re-arms with the shorter ``rearm_s``
    ("warm" behavior).  A click hides the tooltip and suppresses it until
    the cursor leaves that region.

    Not thread-safe by itself; each surface owns one tracker and calls it
    from a single thread (main-window event/render path, or a drop-in's
    render thread).
    """

    def __init__(
        self,
        *,
        delay_s: float = 0.55,
        rearm_s: float = 0.15,
        jitter_px: int = 6,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._delay_s = max(0.0, float(delay_s))
        self._rearm_s = max(0.0, float(rearm_s))
        self._jitter_px = max(0, int(jitter_px))
        self._now = now
        self._candidate: TooltipRegion | None = None
        self._deadline = 0.0
        self._visible = False
        self._anchor: tuple[int, int] | None = None
        self._warm_until = 0.0
        self._suppressed_rect: tuple[int, int, int, int] | None = None

    @property
    def anchor(self) -> tuple[int, int] | None:
        """Cursor position captured when the current tooltip armed."""
        return self._anchor

    def on_motion(
        self,
        x: float | None,
        y: float | None,
        regions: Sequence[TooltipRegion],
    ) -> None:
        """Update hover state from a cursor position.

        Pass ``None`` coordinates when the cursor left the surface.
        Regions are searched last-to-first so that, as with draw order,
        the most recently added region wins overlaps.
        """
        if x is None or y is None:
            self.reset()
            return
        t = self._now()
        if self._suppressed_rect is not None:
            sx, sy, sw, sh = self._suppressed_rect
            if sx <= x <= sx + sw and sy <= y <= sy + sh:
                return
            self._suppressed_rect = None

        region = next(
            (r for r in reversed(regions) if r.contains(x, y)), None,
        )
        if region is None:
            if self._visible:
                self._warm_until = t + _WARM_WINDOW_S
            self._candidate = None
            self._visible = False
            self._anchor = None
            return

        if self._candidate is not None and region.rect == self._candidate.rect:
            if self._visible:
                # Keep the freshest text for this rect (dynamic labels).
                self._candidate = region
                return
            ax, ay = self._anchor if self._anchor is not None else (int(x), int(y))
            if abs(x - ax) > self._jitter_px or abs(y - ay) > self._jitter_px:
                self._anchor = (int(x), int(y))
                self._deadline = t + self._delay_s
            self._candidate = region
            return

        # Entering a new region (possibly straight from another one).
        warm = self._visible or t <= self._warm_until
        if self._visible:
            self._warm_until = t + _WARM_WINDOW_S
        self._candidate = region
        self._visible = False
        self._anchor = (int(x), int(y))
        self._deadline = t + (self._rearm_s if warm else self._delay_s)

    def tick(self) -> TooltipRegion | None:
        """Advance timing; return the region whose tooltip should show now.

        Cheap by design (comparisons only, no allocation) so main-loop
        render paths can call it every frame.
        """
        if self._candidate is None:
            return None
        if not self._visible and self._now() >= self._deadline:
            self._visible = True
        return self._candidate if self._visible else None

    def notify_click(self) -> None:
        """Hide and suppress the current tooltip until the cursor leaves
        its region (clicking a control means the label served its purpose)."""
        if self._candidate is not None:
            self._suppressed_rect = self._candidate.rect
        self._candidate = None
        self._visible = False
        self._anchor = None
        self._warm_until = 0.0

    def reset(self) -> None:
        """Forget all hover state (cursor left the surface / modal closed)."""
        self._candidate = None
        self._visible = False
        self._anchor = None
        self._warm_until = 0.0
        self._suppressed_rect = None


def wrap_tooltip_text(
    text: str,
    font: 'ImageFont.FreeTypeFont | ImageFont.ImageFont',
    max_width_px: int,
    measure: Callable[[str], float],
) -> list[str]:
    """Greedy word-wrap ``text`` to ``max_width_px`` using ``measure``.

    ``measure`` returns the pixel width of a string in ``font`` (callers
    pass ``lambda s: draw.textlength(s, font=font)``); split out so the
    wrapping is testable against a trivial measure function.

    Explicit newlines are honoured as paragraph breaks: a blank line in the
    source becomes a blank line in the output, so a tooltip can separate "what
    this does" from a caveat instead of running them together.  Text without
    newlines wraps exactly as before.
    """
    raw = str(text)
    if '\n' in raw:
        out: list[str] = []
        for i, para in enumerate(raw.split('\n\n')):
            if i:
                out.append('')                     # blank line between paras
            for chunk in para.split('\n'):
                out.extend(wrap_tooltip_text(chunk, font, max_width_px,
                                             measure))
        while out and not out[-1]:
            out.pop()
        return out
    words = raw.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f'{current} {word}'
        if measure(candidate) <= max_width_px:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def draw_tooltip_pil(
    draw: 'ImageDraw.ImageDraw',
    text: str,
    anchor_xy: tuple[int, int],
    bounds: tuple[int, int],
    *,
    font: 'ImageFont.FreeTypeFont | ImageFont.ImageFont',
    bg: tuple[int, int, int],
    border: tuple[int, int, int],
    text_color: tuple[int, int, int],
    max_width_px: int = 360,
) -> None:
    """Draw a tooltip bubble on a PIL surface.

    The bubble sits below-right of ``anchor_xy``, flips above when it
    would overflow the bottom of ``bounds`` (surface width/height), and
    clamps horizontally. Colors are RGB; the caller supplies its own
    theme so control-room and mixer keep their distinct palettes.
    """
    body = str(text or '').strip()
    if not body:
        return
    lines = wrap_tooltip_text(
        body, font, max_width_px, lambda s: draw.textlength(s, font=font),
    )
    if not lines:
        return
    ascent, descent = font.getmetrics() if hasattr(font, 'getmetrics') else (11, 3)
    line_h = ascent + descent
    text_w = max(draw.textlength(line, font=font) for line in lines)
    box_w = int(text_w) + _PAD_X * 2
    box_h = len(lines) * line_h + (len(lines) - 1) * _LINE_GAP + _PAD_Y * 2

    surface_w, surface_h = bounds
    bx = anchor_xy[0] + _ANCHOR_OFFSET_X
    by = anchor_xy[1] + _ANCHOR_OFFSET_Y
    if by + box_h > surface_h - 4:
        by = anchor_xy[1] - box_h - 8
    bx = max(4, min(bx, surface_w - box_w - 4))
    by = max(4, by)

    draw.rounded_rectangle(
        (bx, by, bx + box_w, by + box_h),
        radius=6,
        fill=bg + (242,),
        outline=border + (255,),
        width=_BORDER_W,
    )
    ty = by + _PAD_Y
    for line in lines:
        draw.text((bx + _PAD_X, ty), line, font=font, fill=text_color + (255,))
        ty += line_h + _LINE_GAP
