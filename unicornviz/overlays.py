"""
On-screen overlays rendered in immediate mode using a simple bitmap font.
Handles: effect name flash, persistent name overlay, help screen,
audio device selector, MIDI device selector, and generic flash messages.
"""
from __future__ import annotations

import datetime
import logging
import math
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import moderngl
import numpy as np

from unicornviz.catalog_browser import CatalogBrowser, PANE_CATEGORIES, PANE_LIST
from unicornviz.cta_overlay import CTAOverlay, _CTA_SHOW_DURATION, _CTA_SLOTS
from unicornviz.paths import resolve_path
from unicornviz.tooltips import TooltipHoverTracker, TooltipRegion, wrap_tooltip_text
from unicornviz.tour import resolve_slide_body as _tour_resolve

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except Exception:
    _PIL_AVAILABLE = False

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except Exception:
    _PSUTIL_AVAILABLE = False

if TYPE_CHECKING:
    from unicornviz.effects.base import BaseEffect

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedded 8×8 bitmap font (IBM PC BIOS font, ASCII 32–127)
# Each character is stored as 8 bytes, one byte per row, MSB = leftmost pixel.
# Generated from the public-domain "PC Screen Font" / Oldschool PC Font data.
# ---------------------------------------------------------------------------
_FONT_8X8 = [
    # 32 space
    0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
    # 33 !
    0x18,0x3C,0x3C,0x18,0x18,0x00,0x18,0x00,
    # 34 "
    0x36,0x36,0x00,0x00,0x00,0x00,0x00,0x00,
    # 35 #
    0x36,0x36,0x7F,0x36,0x7F,0x36,0x36,0x00,
    # 36 $
    0x0C,0x3E,0x03,0x1E,0x30,0x1F,0x0C,0x00,
    # 37 %
    0x00,0x63,0x33,0x18,0x0C,0x66,0x63,0x00,
    # 38 &
    0x1C,0x36,0x1C,0x6E,0x3B,0x33,0x6E,0x00,
    # 39 '
    0x06,0x06,0x03,0x00,0x00,0x00,0x00,0x00,
    # 40 (
    0x18,0x0C,0x06,0x06,0x06,0x0C,0x18,0x00,
    # 41 )
    0x06,0x0C,0x18,0x18,0x18,0x0C,0x06,0x00,
    # 42 *
    0x00,0x66,0x3C,0xFF,0x3C,0x66,0x00,0x00,
    # 43 +
    0x00,0x0C,0x0C,0x3F,0x0C,0x0C,0x00,0x00,
    # 44 ,
    0x00,0x00,0x00,0x00,0x00,0x0C,0x0C,0x06,
    # 45 -
    0x00,0x00,0x00,0x3F,0x00,0x00,0x00,0x00,
    # 46 .
    0x00,0x00,0x00,0x00,0x00,0x0C,0x0C,0x00,
    # 47 /
    0x60,0x30,0x18,0x0C,0x06,0x03,0x01,0x00,
    # 48 0
    0x3E,0x63,0x73,0x7B,0x6F,0x67,0x3E,0x00,
    # 49 1
    0x0C,0x0E,0x0C,0x0C,0x0C,0x0C,0x3F,0x00,
    # 50 2
    0x1E,0x33,0x30,0x1C,0x06,0x33,0x3F,0x00,
    # 51 3
    0x1E,0x33,0x30,0x1C,0x30,0x33,0x1E,0x00,
    # 52 4
    0x38,0x3C,0x36,0x33,0x7F,0x30,0x78,0x00,
    # 53 5
    0x3F,0x03,0x1F,0x30,0x30,0x33,0x1E,0x00,
    # 54 6
    0x1C,0x06,0x03,0x1F,0x33,0x33,0x1E,0x00,
    # 55 7
    0x3F,0x33,0x30,0x18,0x0C,0x0C,0x0C,0x00,
    # 56 8
    0x1E,0x33,0x33,0x1E,0x33,0x33,0x1E,0x00,
    # 57 9
    0x1E,0x33,0x33,0x3E,0x30,0x18,0x0E,0x00,
    # 58 :
    0x00,0x0C,0x0C,0x00,0x00,0x0C,0x0C,0x00,
    # 59 ;
    0x00,0x0C,0x0C,0x00,0x00,0x0C,0x0C,0x06,
    # 60 <
    0x18,0x0C,0x06,0x03,0x06,0x0C,0x18,0x00,
    # 61 =
    0x00,0x00,0x3F,0x00,0x00,0x3F,0x00,0x00,
    # 62 >
    0x06,0x0C,0x18,0x30,0x18,0x0C,0x06,0x00,
    # 63 ?
    0x1E,0x33,0x30,0x18,0x0C,0x00,0x0C,0x00,
    # 64 @
    0x3E,0x63,0x7B,0x7B,0x7B,0x03,0x1E,0x00,
    # 65 A
    0x0C,0x1E,0x33,0x33,0x3F,0x33,0x33,0x00,
    # 66 B
    0x3F,0x66,0x66,0x3E,0x66,0x66,0x3F,0x00,
    # 67 C
    0x3C,0x66,0x03,0x03,0x03,0x66,0x3C,0x00,
    # 68 D
    0x1F,0x36,0x66,0x66,0x66,0x36,0x1F,0x00,
    # 69 E
    0x7F,0x46,0x16,0x1E,0x16,0x46,0x7F,0x00,
    # 70 F
    0x7F,0x46,0x16,0x1E,0x16,0x06,0x0F,0x00,
    # 71 G
    0x3C,0x66,0x03,0x03,0x73,0x66,0x7C,0x00,
    # 72 H
    0x33,0x33,0x33,0x3F,0x33,0x33,0x33,0x00,
    # 73 I
    0x1E,0x0C,0x0C,0x0C,0x0C,0x0C,0x1E,0x00,
    # 74 J
    0x78,0x30,0x30,0x30,0x33,0x33,0x1E,0x00,
    # 75 K
    0x67,0x66,0x36,0x1E,0x36,0x66,0x67,0x00,
    # 76 L
    0x0F,0x06,0x06,0x06,0x46,0x66,0x7F,0x00,
    # 77 M
    0x63,0x77,0x7F,0x7F,0x6B,0x63,0x63,0x00,
    # 78 N
    0x63,0x67,0x6F,0x7B,0x73,0x63,0x63,0x00,
    # 79 O
    0x1C,0x36,0x63,0x63,0x63,0x36,0x1C,0x00,
    # 80 P
    0x3F,0x66,0x66,0x3E,0x06,0x06,0x0F,0x00,
    # 81 Q
    0x1E,0x33,0x33,0x33,0x3B,0x1E,0x38,0x00,
    # 82 R
    0x3F,0x66,0x66,0x3E,0x36,0x66,0x67,0x00,
    # 83 S
    0x1E,0x33,0x07,0x0E,0x38,0x33,0x1E,0x00,
    # 84 T
    0x3F,0x2D,0x0C,0x0C,0x0C,0x0C,0x1E,0x00,
    # 85 U
    0x33,0x33,0x33,0x33,0x33,0x33,0x3F,0x00,
    # 86 V
    0x33,0x33,0x33,0x33,0x33,0x1E,0x0C,0x00,
    # 87 W
    0x63,0x63,0x63,0x6B,0x7F,0x77,0x63,0x00,
    # 88 X
    0x63,0x63,0x36,0x1C,0x1C,0x36,0x63,0x00,
    # 89 Y
    0x33,0x33,0x33,0x1E,0x0C,0x0C,0x1E,0x00,
    # 90 Z
    0x7F,0x63,0x31,0x18,0x4C,0x66,0x7F,0x00,
    # 91 [
    0x1E,0x06,0x06,0x06,0x06,0x06,0x1E,0x00,
    # 92 backslash
    0x03,0x06,0x0C,0x18,0x30,0x60,0x40,0x00,
    # 93 ]
    0x1E,0x18,0x18,0x18,0x18,0x18,0x1E,0x00,
    # 94 ^
    0x08,0x1C,0x36,0x63,0x00,0x00,0x00,0x00,
    # 95 _
    0x00,0x00,0x00,0x00,0x00,0x00,0x00,0xFF,
    # 96 `
    0x0C,0x0C,0x18,0x00,0x00,0x00,0x00,0x00,
    # 97 a
    0x00,0x00,0x1E,0x30,0x3E,0x33,0x6E,0x00,
    # 98 b
    0x07,0x06,0x06,0x3E,0x66,0x66,0x3B,0x00,
    # 99 c
    0x00,0x00,0x1E,0x33,0x03,0x33,0x1E,0x00,
    # 100 d
    0x38,0x30,0x30,0x3e,0x33,0x33,0x6E,0x00,
    # 101 e
    0x00,0x00,0x1E,0x33,0x3f,0x03,0x1E,0x00,
    # 102 f
    0x1C,0x36,0x06,0x0f,0x06,0x06,0x0F,0x00,
    # 103 g
    0x00,0x00,0x6E,0x33,0x33,0x3E,0x30,0x1F,
    # 104 h
    0x07,0x06,0x36,0x6E,0x66,0x66,0x67,0x00,
    # 105 i
    0x0C,0x00,0x0E,0x0C,0x0C,0x0C,0x1E,0x00,
    # 106 j
    0x30,0x00,0x30,0x30,0x30,0x33,0x33,0x1E,
    # 107 k
    0x07,0x06,0x66,0x36,0x1E,0x36,0x67,0x00,
    # 108 l
    0x0E,0x0C,0x0C,0x0C,0x0C,0x0C,0x1E,0x00,
    # 109 m
    0x00,0x00,0x33,0x7F,0x7F,0x6B,0x63,0x00,
    # 110 n
    0x00,0x00,0x1F,0x33,0x33,0x33,0x33,0x00,
    # 111 o
    0x00,0x00,0x1E,0x33,0x33,0x33,0x1E,0x00,
    # 112 p
    0x00,0x00,0x3B,0x66,0x66,0x3E,0x06,0x0F,
    # 113 q
    0x00,0x00,0x6E,0x33,0x33,0x3E,0x30,0x78,
    # 114 r
    0x00,0x00,0x3B,0x6E,0x66,0x06,0x0F,0x00,
    # 115 s
    0x00,0x00,0x3E,0x03,0x1E,0x30,0x1F,0x00,
    # 116 t
    0x08,0x0C,0x3E,0x0C,0x0C,0x2C,0x18,0x00,
    # 117 u
    0x00,0x00,0x33,0x33,0x33,0x33,0x6E,0x00,
    # 118 v
    0x00,0x00,0x33,0x33,0x33,0x1E,0x0C,0x00,
    # 119 w
    0x00,0x00,0x63,0x6B,0x7F,0x7F,0x36,0x00,
    # 120 x
    0x00,0x00,0x63,0x36,0x1C,0x36,0x63,0x00,
    # 121 y
    0x00,0x00,0x33,0x33,0x33,0x3E,0x30,0x1F,
    # 122 z
    0x00,0x00,0x3F,0x19,0x0C,0x26,0x3F,0x00,
    # 123 {
    0x38,0x0C,0x0C,0x07,0x0C,0x0C,0x38,0x00,
    # 124 |
    0x18,0x18,0x18,0x00,0x18,0x18,0x18,0x00,
    # 125 }
    0x07,0x0C,0x0C,0x38,0x0C,0x0C,0x07,0x00,
    # 126 ~
    0x6E,0x3B,0x00,0x00,0x00,0x00,0x00,0x00,
    # 127 DEL (block)
    0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,
]  # 96 chars × 8 bytes = 768 bytes


def _build_font_texture(ctx: moderngl.Context) -> tuple[moderngl.Texture, int, int, int, int, Path | None]:
    """
    Build overlay font atlas and return (texture, glyph_w, glyph_h, atlas_w, atlas_h).

    Preferred path: render a grayscale atlas from a modern TTF font for cleaner
    readability at mixed sizes.
    Fallback path: legacy 8x8 bitmap atlas from assets/fonts/font8x8.bin or
    embedded BIOS-style font data.
    """
    if _PIL_AVAILABLE:
        font_candidates = [
            resolve_path('assets/fonts/ui-font.ttf'),
            Path('/usr/share/fonts/adobe-source-code-pro-fonts/SourceCodePro-Medium.otf'),
            Path('/usr/share/fonts/google-noto-vf/NotoSansMono[wght].ttf'),
            Path('/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf'),
        ]
        font_path = next((p for p in font_candidates if p.exists()), None)
        if font_path is not None:
            glyph_w = 13
            glyph_h = 18
            n_chars = 128
            atlas_w = glyph_w * n_chars
            atlas_h = glyph_h
            atlas = Image.new('L', (atlas_w, atlas_h), 0)
            draw = ImageDraw.Draw(atlas)
            try:
                font = ImageFont.truetype(str(font_path), size=17)
                for code in range(32, 127):
                    ch = chr(code)
                    bbox = draw.textbbox((0, 0), ch, font=font)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                    ox = code * glyph_w + max(0, (glyph_w - tw) // 2) - bbox[0]
                    oy = max(0, (glyph_h - th) // 2) - bbox[1] - 1
                    draw.text((ox, oy), ch, font=font, fill=255)

                data = np.array(atlas, dtype=np.uint8)
                tex = ctx.texture((atlas_w, atlas_h), 1, data=data.tobytes())
                # Linear sampling keeps strokes cleaner when scaled.
                tex.filter = moderngl.LINEAR, moderngl.LINEAR
                return tex, glyph_w, glyph_h, atlas_w, atlas_h, font_path
            except Exception:
                pass

    N_CHARS = 128
    data = np.zeros((8, N_CHARS * 8), dtype=np.uint8)

    font_path = resolve_path("assets/fonts/font8x8.bin")
    if font_path.exists():
        raw = font_path.read_bytes()
        for codepoint in range(min(N_CHARS, len(raw) // 8)):
            for row in range(8):
                byte = raw[codepoint * 8 + row]
                for col in range(8):
                    if byte & (0x80 >> col):
                        data[row, codepoint * 8 + col] = 255
    else:
        # Use embedded font for ASCII 32–127
        font_bytes = bytes(_FONT_8X8)
        for idx in range(96):
            codepoint = 32 + idx
            for row in range(8):
                byte = font_bytes[idx * 8 + row]
                # Embedded rows are packed with opposite horizontal bit order.
                # Reverse bits so glyphs are not mirrored.
                byte = int(f'{byte:08b}'[::-1], 2)
                for col in range(8):
                    if byte & (0x80 >> col):
                        data[row, codepoint * 8 + col] = 255

    tex = ctx.texture((N_CHARS * 8, 8), 1, data=data.tobytes())
    tex.filter = moderngl.NEAREST, moderngl.NEAREST
    return tex, 8, 8, N_CHARS * 8, 8, None


class Overlays:
    """Manages all HUD/overlay rendering."""

    HELP_SECTION_THEMES: dict[str, tuple[float, float, float]] = {
        'Help Usage': (0.98, 0.90, 0.62),
        'Basics': (0.18, 0.96, 0.86),
        'Unicorn Tears': (0.98, 0.78, 1.00),
        'Playback': (1.00, 0.68, 0.28),
        'Tweakables': (0.66, 0.92, 1.00),
        'Audio + Visual': (0.64, 0.86, 1.00),
        'Display Modes': (0.98, 0.94, 0.55),
        'Camera Overlay': (0.72, 1.00, 0.66),
    }
    DYNAMIC_THEME_CYCLE: list[tuple[float, float, float]] = [
        (0.88, 0.92, 1.00),
        (0.84, 1.00, 0.86),
        (1.00, 0.89, 0.84),
        (0.90, 0.85, 1.00),
        (0.98, 0.96, 0.72),
    ]

    # A fully-loaded drop-in directory registers a section per drop-in; capping
    # each help-overlay tab at this many headings keeps every section reachable
    # (previously excess sections silently fell off the bottom of the columns).
    HELP_SECTIONS_PER_TAB = 10

    # A section with more entries than this pages them into an inner
    # accordion (see _help_section_body_rows) instead of showing all of them
    # at once — only one page's items are expanded at a time, so no single
    # card grows tall enough to fail to fit either two-column slot.
    HELP_MAX_ITEMS_PER_SECTION = 7

    # Tooltip state — class-level defaults (tooltips off, no trackers) so the
    # lightweight ``Overlays.__new__``-style shells used across the test
    # suite behave sanely without running __init__, which replaces these
    # with real per-instance values.
    _tooltips_enabled = False
    _tooltip_tracker: TooltipHoverTracker | None = None
    _rail_tooltip_tracker: TooltipHoverTracker | None = None
    _tooltip_surface = ''

    # First-run tour modal — class-level defaults for the same shell reason.
    _show_tour = False
    _tour_slides: tuple = ()
    _tour_slide = 0
    _tour_show_on_startup = True
    _tour_hover = ''
    _tour_button_rects: tuple = ()

    CORE_HELP_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
        (
            'Help Usage',
            [
                ('Tab', 'Toggle section/icon focus'),
                ('PageUp / PageDown', 'Switch help tab (page)'),
                ('Shift+-', 'Collapse all sections (all tabs)'),
                ('Shift+=', 'Expand all sections (all tabs)'),
                ('Arrow keys', 'Move section focus (this tab)'),
                ('H / ?', 'Toggle help overlay'),
                ('F1', 'Take the tour'),
                ('Shift+H', 'Notifications on/off'),
                ('Enter', 'Expand/collapse focused section; cycles item-pages if already open'),
                ('0 - 9', 'Same, for section 1-10 (this tab)'),
            ],
        ),
        (
            'Basics',
            [
                ('f', 'Fullscreen'),
                ('Number', 'Jump #1-9'),
                ('Shift+Number', 'Jump #11-20'),
                ('Ctrl+Number', 'Jump #21-30'),
                ('Alt+Number', 'Jump #31-40'),
                ('n / Right', 'Next effect'),
                ('p / Left', 'Prev effect'),
                ('Delete', 'Disable current effect & skip (ProjectM: disable preset)'),
                ('Right Click', 'Open context menu'),
                ('ESC', 'Quit'),
                ('u', 'Replay splash'),
                ('s', 'Screenshot'),
                ('TAB', 'Toggle HUD'),
                ('v', 'Toggle recording'),
            ],
        ),
        (
            'Playback',
            [
                ('; / \'', 'Advance interval -/+ 10s'),
                ('t', 'Auto-advance on/off'),
                ('Space', 'Pause / resume'),
                ('r', 'Random effects mode'),
                ('\\', 'Reset advance interval'),
            ],
        ),
        (
            'Tweakables',
            [
                ('[ / ]', 'Reactivity -/+'),
                ('{ / }', 'Reactivity MIN / MAX'),
                ('F6', 'Speed random ON / OFF'),
                ('F7', 'Reactivity random ON / OFF'),
                ('g', 'Reactivity reset'),
                (', / .', 'Res scale down / up'),
                ('Shift+, / .', 'Res scale MIN / MAX'),
                ('Ctrl+, / .', 'Reset res scale'),
                ('Ctrl+G', 'Speed reset'),
                ('Ctrl+= / Ctrl+-', 'Speed MAX / MIN'),
                ('+ / -', 'Speed up / down'),
                ('Alt+= / Alt+-', 'Speed random ON / OFF'),
                ('z / Z', 'Zoom in / out'),
                ('Alt+Z', 'Zoom random ON / OFF'),
                ('Ctrl+Z', 'Zoom reset'),
            ],
        ),
        (
            'Audio + Visual',
            [
                ('e', 'EQ / spectrum'),
                ('a / A', 'Audio source selector menu'),
                ('Ctrl+A', 'Audio source selector menu (alternate)'),
                ('Alt+A / Alt+Shift+A', 'BPM Profile next / prev'),
                ('m', 'System monitor modal'),
                ('Alt+M', 'MIDI device selector'),
                ('B', 'Effects browser (search/filter/preview/pin all effects)'),
                ('c', 'Configuration editor (tabbed settings + profiles)'),
                ('Ctrl+Shift+P', 'Show presets (save/load setup: enabled effects, mode, reactivity)'),
                ('Ctrl+L', 'Toggle ProjectM-only mode (lock to ProjectM)'),
                ('i', 'Invert colors'),
                ('w', 'Now Spinning platter overlay'),
            ],
        ),
    ]

    HELP_ICON_ENTRIES: list[dict[str, object]] = [
        {
            'id': 'about',
            'label': 'DJ UT',
            'image_id': 'about',
            'glyph': 'UT',
            'description': 'About / links page',
            'tooltip': 'Learn about DJ Tears & Unicorn-Viz!',
            'accent': (0.98, 0.78, 1.00),
            'action_kind': 'placeholder',
            'message': 'DJ UT info page coming soon',
        },
        {
            'id': 'contact',
            'label': 'Contact',
            'image_id': 'contact',
            'glyph': '@',
            'description': 'Send logs / VJ data / screenshots / recordings',
            'tooltip': 'Contact the DJ or Support',
            'accent': (0.10, 0.94, 1.00),
            'action_kind': 'placeholder',
            'message': 'Contact flow coming soon',
        },
        {
            'id': 'share',
            'label': 'Share',
            'image_id': 'share',
            'glyph': 'SH',
            'description': 'Open share link flow',
            'tooltip': 'Love Unicorn-Viz? Please share!!',
            'accent': (0.98, 0.96, 0.72),
            'action_kind': 'url',
            'target': 'https://unicorntears.com',
            'message': 'Opening share page',
        },
        {
            'id': 'shop',
            'label': 'Shop',
            'image_id': 'shop',
            'glyph': '$',
            'description': 'Open web store flow',
            'tooltip': 'Shop Unicorn Tears swag & software!',
            'accent': (0.98, 0.62, 0.22),
            'action_kind': 'placeholder',
            'message': 'Shop link coming soon',
        },
        {
            'id': 'dropins',
            'label': 'Drop-ins',
            'image_id': 'dropins',
            'glyph': 'DI',
            'description': 'ProjectM browser / future in-app purchases',
            'tooltip': 'Acquire & configure drop-in extensions',
            'accent': (0.66, 0.92, 1.00),
            'action_kind': 'projectm_manager',
            'message': 'Opening drop-ins browser',
        },
        {
            'id': 'settings',
            'label': 'Settings',
            'image_id': 'settings',
            'glyph': 'SET',
            'description': 'Future app settings placeholder',
            'tooltip': 'Open settings',
            'accent': (1.00, 0.68, 0.28),
            'action_kind': 'placeholder',
            'message': 'Settings panel coming soon',
        },
        # TODO(auth): Show this icon only when the operator is logged in.
        {
            'id': 'account',
            'label': 'Account',
            'image_id': 'account',
            'glyph': 'AC',
            'description': 'Future account hub placeholder',
            'tooltip': 'Your Account',
            'accent': (0.78, 0.38, 1.00),
            'action_kind': 'placeholder',
            'message': 'Account panel coming soon',
        },
        {
            'id': 'login_out',
            'label': 'Login/Out',
            'image_id_logged_out': 'login',
            'image_id_logged_in': 'logout',
            'glyph': 'IN',
            'description': 'Future auth flow placeholder',
            'tooltip_logged_out': 'Login',
            'tooltip_logged_in': 'Logout',
            'accent': (0.72, 1.00, 0.66),
            'action_kind': 'placeholder',
            'message': 'Login/Out coming soon',
        },
    ]

    # Drop-in help is now registered dynamically via HELP_ENTRIES in each drop-in
    # module and collected by discover_dropin_help_entries() at startup.
    DROPIN_HELP_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = []

    NUM_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]
    SHIFT_KEYS = ["S+1", "S+2", "S+3", "S+4", "S+5", "S+6", "S+7", "S+8", "S+9", "S+0"]
    CTRL_KEYS = ["C+1", "C+2", "C+3", "C+4", "C+5", "C+6", "C+7", "C+8", "C+9", "C+0"]
    ALT_KEYS = ["A+1", "A+2", "A+3", "A+4", "A+5", "A+6", "A+7", "A+8", "A+9", "A+0"]

    def __init__(
        self,
        ctx: moderngl.Context,
        width: int,
        height: int,
        flash_messages: bool = True,
        show_recording_indicator: bool = True,
        hud_auto_hide: bool = True,
        hud_timeout_s: float = 60.0,
        flash_router: Callable[[str, float], bool] | None = None,
        modal_gate: Callable[[], bool] | None = None,
        tooltips_enabled: bool = True,
        tooltip_delay_s: float = 0.55,
    ) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._tooltips_enabled = bool(tooltips_enabled)
        # Modal surfaces (browsers, config editor) use the configured hover
        # delay; the help-icon rail stays instant by owner decision (see
        # docs/planning/tooltip-system-plan-2026-07-13.md §9.1).
        self._tooltip_tracker = TooltipHoverTracker(delay_s=float(tooltip_delay_s))
        self._rail_tooltip_tracker = TooltipHoverTracker(delay_s=0.0)
        self._tooltip_surface = ''
        self._flash_enabled = flash_messages
        self._show_recording_indicator = show_recording_indicator
        self._hud_auto_hide = bool(hud_auto_hide)
        self._hud_timeout_s = max(0.0, float(hud_timeout_s))
        self._flash_router = flash_router
        self._modal_gate = modal_gate
        self._modal_route_debug_last: tuple[bool, str] | None = None
        self._recording_active = False
        self._recording_elapsed_seconds = 0.0

        self._show_name = False
        self._show_help = False
        self._show_audio = False
        self._show_midi = False
        self._show_system_monitor_modal = False
        self._show_controller_help_modal = False
        self._controller_help_renderer: 'Callable[[Overlays], None] | None' = None
        self._show_projectm_manager = False
        self._show_webcam_editor_modal = False
        self._audio_sources: list[str] = []
        self._audio_viable_flags: list[bool] = []
        self._audio_current_idx: int = 0
        self._audio_selected_idx: int = 0
        self._midi_ports: list[str] = []
        self._midi_current_port: str = ''
        self._midi_selected_idx: int = 0   # 0 = "None (disable)"
        self._projectm_browser = CatalogBrowser()
        self._projectm_browser.set_focus_pane(PANE_LIST)
        self._projectm_current_path: str = ''
        # Effects browser (keyboard + mouse) — driven by the shared model.
        self._show_effects_browser = False
        self._effects_browser = CatalogBrowser()
        self._effects_browser_current: str = ''
        self._effects_browser_pinned: str = ''
        self._eb_thumb_tex: 'moderngl.Texture | None' = None
        # Right-click context menu (entries are built by App from the help
        # registry; Overlays only renders + hit-tests them).
        self._context_menu_open = False
        self._context_menu_entries: list[dict[str, object]] = []
        self._context_menu_x = 0.0
        self._context_menu_y = 0.0
        self._context_menu_hover = -1
        self._context_menu_expanded: set[int] = set()
        self._context_menu_anim = 0.0  # 0 = hidden, 1 = fully open (unroll ease)
        self._context_menu_fading = False  # animating closed
        self._context_menu_row_rects: list[tuple[float, float, float, float, int]] = []
        # Configuration editor (tabbed modal). Increment 2: shell + tab nav.
        self._show_config_editor = False
        self._config_editor_tabs = ['Effects', 'Audio', 'Visuals']
        self._config_editor_tab = 0
        self._config_editor_tab_hover = -1
        self._config_editor_anim = 0.0
        self._config_editor_fading = False
        self._config_editor_panel_rect: tuple[float, float, float, float] | None = None
        # Effects tab: pushed by App each frame; Overlays owns selection/focus.
        self._ce_effects: list[dict[str, str]] = []
        self._ce_effect_idx = 0
        self._ce_params: list[dict[str, float | str]] = []
        self._ce_param_idx = 0
        self._ce_focus = 0  # 0 = effect list, 1 = parameters
        self._ce_effect_row_rects: list[tuple[float, float, float, float, int]] = []
        self._ce_param_row_rects: list[tuple[float, float, float, float, int]] = []
        # Profile footer (Increment 4): save/load/delete/revert + name entry.
        self._ce_profiles: list[str] = []
        self._ce_profile_idx = -1
        self._ce_dirty = False
        self._ce_name_mode = False
        self._ce_name_text = ''
        self._ce_pending_action: str | None = None
        self._ce_footer_button_rects: list[tuple[float, float, float, float, str]] = []
        self._ce_profile_chip_rects: list[tuple[float, float, float, float, int]] = []
        # Hotkeys tab: "press new key" capture mode for the selected action row.
        self._ce_capture_mode = False
        self._ce_capture_action: str = ''
        # Show-presets modal (single-pane list + inline name entry).
        self._show_presets = False
        self._presets_browser = CatalogBrowser()
        self._presets_name_mode = False
        self._presets_name_text = ''
        self._presets_row_rects: list[tuple[float, float, float, float, int]] = []
        # Mouse hit-regions rebuilt each render: (x, y, w, h, index).
        self._eb_cat_rects: list[tuple[float, float, float, float, int]] = []
        self._eb_row_rects: list[tuple[float, float, float, float, int]] = []
        self._webcam_editor_devices: list[dict[str, object]] = []
        self._webcam_editor_selected_idx: int = 0
        self._webcam_editor_state: dict[str, object] = {
            'brightness': 1.0,
            'contrast': 1.0,
            'flip_horizontal': True,
            'flip_vertical': False,
            'switching': False,
            'switch_hide_remaining_s': 0.0,
        }
        self._sysmon_cpu: float = 0.0
        self._sysmon_ram: float = 0.0
        self._sysmon_swap: float = 0.0
        self._sysmon_disk_mbs: float = 0.0
        self._sysmon_net_mbs: float = 0.0
        self._sysmon_sample_t: float = 0.0
        self._sysmon_prev_io_t: float | None = None
        self._sysmon_prev_disk_bytes: float | None = None
        self._sysmon_prev_net_bytes: float | None = None
        self._system_monitor_audio_provider: (
            Callable[[], dict[str, float]] | None
        ) = None
        self._system_monitor_tweakables_provider: (
            Callable[[], dict[str, float | None]] | None
        ) = None
        if _PSUTIL_AVAILABLE:
            try:
                psutil.cpu_percent(interval=None)
                disk = psutil.disk_io_counters()
                net = psutil.net_io_counters()
                self._sysmon_prev_io_t = time.monotonic()
                if disk is not None:
                    self._sysmon_prev_disk_bytes = float(disk.read_bytes + disk.write_bytes)
                if net is not None:
                    self._sysmon_prev_net_bytes = float(net.bytes_recv + net.bytes_sent)
            except Exception:
                pass
        self._help_timer: float = 0.0
        self._hud_timer: float = 0.0
        self._banner_timer: float = 0.0
        self._banner_change_counter: int = -1
        self._banner_enabled: bool = False
        self._banner_hold_s: float = 10.0
        self._banner_current_text: str = ''
        self._banner_previous_text: str = ''
        self._flash_text: str = ""
        self._flash_timer: float = 0.0
        self._name_text: str = ""
        self._hud_state: dict[str, str] = {
            'title': 'Unicorn Viz HUD',
            'effect': '-',
            'previous_effect': '-',
            'next_effect': '-',
            'transition': '-',
            'transition_t': '0%',
            'fps': '0.0',
            'frame_ms': '0.0',
            'resolution': '-',
            'render_scale': '1.00',
            'playlist': '-',
            'paused': 'NO',
            'fullscreen': 'NO',
            'auto_advance': 'ON',
            'advance_time': '0.0/20.0s',
            'reactivity': '1.0x',
            'speed': '-',
            'audio_source': '-',
            'audio_profile': 'house',
            'preset_slot_label': 'PRESET IDX',
            'preset_slot': '-/-',
            'variant_slot_label': 'VARIANT',
            'variant_slot': '-/-',
            'auto_vj_label': 'AUTO VJ',
            'auto_vj_training_badge': '',
            'recording': 'OFF',
            'streaming': 'OFF',
            'streaming_provider': '-',
            'now_playing_visible': 'NO',
            'spotify_auth_visible': 'NO',
            'spotify_auth_status': 'Ctrl+Alt+S to auth',
            'now_playing_status': 'OFF',
            'now_playing_track': '-',
            'now_playing_artist': '-',
            'now_playing_progress': '--:--/--:-- 0%',
            'postfx': 'N/A',
            'bass': '0.00',
            'mid': '0.00',
            'treble': '0.00',
            'audio_beat': '0.000',
            'display_mode': 'single',
            'display_index': '0',
            'invert': 'OFF',
            'vj_status': '',
        }
        self._num_shortcuts: list[str] = []
        self._shift_shortcuts: list[str] = []
        self._ctrl_shortcuts: list[str] = []
        self._alt_shortcuts: list[str] = []
        self._unmapped_effects: list[str] = []
        self._hud_rect: tuple[float, float, float, float] | None = None
        self._dynamic_help_sections: dict[str, list[tuple[str, str]]] = {}
        self._dynamic_help_order: list[str] = []
        self._postfx_help_entries: list[tuple[str, str]] = []
        self._mouse_help_entries: list[tuple[str, str]] = []
        self._help_collapsed: dict[str, bool] = {}
        # Which item-page (of HELP_MAX_ITEMS_PER_SECTION each) is open per
        # section, for sections with more entries than the cap.
        self._help_item_page: dict[str, int] = {}
        self._help_item_page_rects: list[tuple[str, int, float, float, float, float]] = []
        self._help_focus_region: str = 'sections'
        self._help_focus_idx: int = 0
        self._help_tab_idx: int = 0
        self._help_tab_rects: list[tuple[int, float, float, float, float]] = []
        self._help_right_tab_idx: int = 0
        self._help_right_tab_rects: list[tuple[int, float, float, float, float]] = []
        # Which pane PageUp/PageDown currently advances; see move_help_page().
        self._help_active_pane: str = 'left'
        self._help_icon_focus_idx: int = 0
        self._pending_help_icon_action: dict[str, str] | None = None
        self._help_pulse_t: float = 0.0
        self._hud_t: float = 0.0
        # Live PCM waveform fed each frame from the audio pipeline.
        # Used to render the now-playing progress-bar waveform visualization.
        self._live_waveform: np.ndarray | None = None
        self._now_playing_beat_decay: float = 0.0
        self._help_icon_asset_dir: Path = resolve_path('assets/icons/help')
        self._help_icon_asset_bucket: str = self._help_icon_bucket_for_width(self._width)
        self._help_icon_textures: dict[str, moderngl.Texture] = {}


        self._font_tex, self._glyph_w, self._glyph_h, self._atlas_w, self._atlas_h, self._font_path = _build_font_texture(ctx)
        # Keep historical scale semantics (scale=1 roughly equals an 8 px cell).
        self._font_scale_norm = 8.0 / float(max(1, self._glyph_h))
        self._prog = self._build_program()
        self._build_vbo()
        self._build_panel_vbo()
        self._build_icon_vbo()
        self._load_help_icon_textures()
        self._cta = CTAOverlay(self._font_path, list(_CTA_SLOTS), _CTA_SHOW_DURATION)

    def _build_panel_vbo(self) -> None:
        """Build shader/VAO for simple colored overlay rectangles."""
        vert = """
#version 330
in vec2 in_vert;
void main() {
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""
        frag = """
#version 330
uniform vec4 color;
out vec4 fragColor;
void main() {
    fragColor = color;
}
"""
        self._panel_prog = self._ctx.program(vertex_shader=vert, fragment_shader=frag)
        self._panel_vbo = self._ctx.buffer(reserve=6 * 2 * 4)
        self._panel_vao = self._ctx.vertex_array(
            self._panel_prog,
            [(self._panel_vbo, "2f", "in_vert")],
        )

    def _build_icon_vbo(self) -> None:
        """Build shader/VAO for RGBA help icon textures."""
        vert = """
#version 330
in vec2 in_vert;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    gl_Position = vec4(in_vert, 0.0, 1.0);
    v_uv = in_uv;
}
"""
        frag = """
#version 330
uniform sampler2D icon_tex;
uniform float icon_alpha;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    vec4 c = texture(icon_tex, v_uv);
    fragColor = vec4(c.rgb, c.a * icon_alpha);
}
"""
        self._icon_prog = self._ctx.program(vertex_shader=vert, fragment_shader=frag)
        self._icon_vbo = self._ctx.buffer(reserve=6 * 4 * 4)
        self._icon_vao = self._ctx.vertex_array(
            self._icon_prog,
            [(self._icon_vbo, "2f 2f", "in_vert", "in_uv")],
        )

    def _help_icon_bucket_for_width(self, width: int) -> str:
        """Choose the help-icon asset bucket for the current viewport width."""
        return '152px' if int(width) >= 3840 else '76px'

    def _load_help_icon_textures(self) -> None:
        """Load icon textures from the selected assets/icons/help bucket."""
        self._help_icon_textures = {}
        if not _PIL_AVAILABLE:
            return
        asset_dir = self._help_icon_asset_dir / self._help_icon_asset_bucket
        if not asset_dir.exists():
            asset_dir = self._help_icon_asset_dir
        if not asset_dir.exists():
            return

        suffixes = ('.png', '.webp', '.jpg', '.jpeg')
        for src_path in sorted(asset_dir.iterdir()):
            if not src_path.is_file() or src_path.suffix.lower() not in suffixes:
                continue
            icon_id = src_path.stem.strip().lower()
            if not icon_id:
                continue
            try:
                img = Image.open(src_path).convert('RGBA')
                tex = self._ctx.texture(img.size, 4, img.tobytes())
                tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
                tex.repeat_x = False
                tex.repeat_y = False
                self._help_icon_textures[icon_id] = tex
            except Exception as exc:
                log.warning('Failed to load help icon texture %s: %s', src_path, exc)

    def _draw_icon_texture(
        self,
        tex: moderngl.Texture,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        alpha: float = 1.0,
        flip_v: bool = False,
    ) -> None:
        """Draw an RGBA texture in screen pixels.

        Set ``flip_v`` for bottom-up sources such as FBO colour attachments so
        the image is not drawn upside down.
        """
        def px(px_val: float) -> float:
            return (px_val / self._width) * 2.0 - 1.0

        def py(py_val: float) -> float:
            return 1.0 - (py_val / self._height) * 2.0

        x0 = px(x)
        x1 = px(x + w)
        y0 = py(y)
        y1 = py(y + h)
        vt, vb = (1.0, 0.0) if flip_v else (0.0, 1.0)
        verts = np.array([
            x0, y0, 0.0, vt,
            x1, y0, 1.0, vt,
            x0, y1, 0.0, vb,
            x1, y0, 1.0, vt,
            x1, y1, 1.0, vb,
            x0, y1, 0.0, vb,
        ], dtype=np.float32)
        self._icon_vbo.write(verts)
        self._icon_prog['icon_alpha'].value = float(max(0.0, min(1.0, alpha)))
        tex.use(location=0)
        self._icon_prog['icon_tex'].value = 0
        self._ctx.enable(moderngl.BLEND)
        self._icon_vao.render(moderngl.TRIANGLES, vertices=6)

    def _help_icon_image_id(self, entry: dict[str, object]) -> str:
        """Return the active image id for a help icon entry."""
        icon_id = str(entry.get('id', '') or '').strip().lower()
        if icon_id == 'login_out':
            auth_visible = str(self._hud_state.get('spotify_auth_visible', 'NO') or 'NO').strip().upper()
            auth_status = str(self._hud_state.get('spotify_auth_status', 'OFF') or 'OFF').strip().upper()
            if auth_visible == 'YES' and auth_status not in {'OFF', '-', ''}:
                return str(entry.get('image_id_logged_in', 'logout') or 'logout').strip().lower()
            return str(entry.get('image_id_logged_out', 'login') or 'login').strip().lower()
        image_id = str(entry.get('image_id', icon_id) or icon_id).strip().lower()
        return image_id or icon_id

    def _help_icon_tooltip(self, entry: dict[str, object]) -> str:
        """Return a short tooltip string for a help icon entry."""
        icon_id = str(entry.get('id', '') or '').strip().lower()
        if icon_id == 'login_out':
            auth_visible = str(self._hud_state.get('spotify_auth_visible', 'NO') or 'NO').strip().upper()
            auth_status = str(self._hud_state.get('spotify_auth_status', 'OFF') or 'OFF').strip().upper()
            if auth_visible == 'YES' and auth_status not in {'OFF', '-', ''}:
                return str(entry.get('tooltip_logged_in', 'Logout') or 'Logout').strip()
            return str(entry.get('tooltip_logged_out', 'Login') or 'Login').strip()
        tooltip = str(entry.get('tooltip', '') or '').strip()
        if tooltip:
            return tooltip
        return str(entry.get('description', entry.get('label', '')) or '').strip()

    def _help_icon_cells(self) -> list[tuple[float, float, float, float]]:
        """Return each rail icon's cell rect (x, y, w, h), one per entry.

        Derived from the same panel math the help renderer uses; the single
        geometry source for both click hit-testing and tooltip regions.
        Empty when the help overlay is hidden.
        """
        if not self._show_help:
            return []
        entries = self._help_icon_entries()
        if not entries:
            return []
        panel_pad = 44.0
        px = panel_pad
        py = panel_pad
        pw = self._width - panel_pad * 2.0
        res_ratio = min(self._width, self._height) / 1080.0
        help_scale = min(1.28, max(1.0, res_ratio ** 0.35))
        icon_band_y = py + 100.0
        icon_px = 152.0 if self._help_icon_asset_bucket == '152px' else 76.0
        band_h = max(icon_px + 20.0, 72.0 * help_scale)
        gap = max(14.0, 16.0 * help_scale)
        total_w = len(entries) * icon_px + max(0, len(entries) - 1) * gap
        start_x = round(px + max(0.0, (pw - total_w) * 0.5))
        rail_y = round(icon_band_y + max(0.0, (band_h - icon_px) * 0.5) - 10.0)
        return [
            (float(round(start_x + idx * (icon_px + gap))), float(rail_y), icon_px, icon_px)
            for idx in range(len(entries))
        ]

    def _help_icon_hit_test(self, x: float, y: float) -> int:
        """Return the icon index under x/y or -1 when not over an icon."""
        for idx, (cx, cy, cw, ch) in enumerate(self._help_icon_cells()):
            if cx <= x <= cx + cw and cy <= y <= cy + ch:
                return idx
        return -1

    def _help_icon_tooltip_regions(self) -> list[TooltipRegion]:
        """Build tooltip regions for the rail icons from the shared cells."""
        entries = self._help_icon_entries()
        return [
            TooltipRegion(
                rect=(int(cx), int(cy), int(cw), int(ch)),
                text=self._help_icon_tooltip(entries[idx]),
            )
            for idx, (cx, cy, cw, ch) in enumerate(self._help_icon_cells())
            if idx < len(entries)
        ]

    def handle_help_mouse_motion(self, x: float, y: float) -> bool:
        """Update hover state for help icon tooltips."""
        regions = self._help_icon_tooltip_regions()
        if self._rail_tooltip_tracker is not None:
            self._rail_tooltip_tracker.on_motion(x, y, regions)
        return any(region.contains(x, y) for region in regions)

    def _draw_rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        color: tuple[float, float, float, float],
    ) -> None:
        """Draw a solid-color rectangle in screen pixels."""
        def px(px_val: float) -> float:
            return (px_val / self._width) * 2.0 - 1.0

        def py(py_val: float) -> float:
            return 1.0 - (py_val / self._height) * 2.0

        x0 = px(x)
        x1 = px(x + w)
        y0 = py(y)
        y1 = py(y + h)
        verts = np.array([
            x0, y0,
            x1, y0,
            x0, y1,
            x1, y0,
            x1, y1,
            x0, y1,
        ], dtype=np.float32)
        self._panel_vbo.write(verts)
        self._panel_prog["color"].value = color
        self._ctx.enable(moderngl.BLEND)
        self._panel_vao.render(moderngl.TRIANGLES, vertices=6)

    def _build_program(self) -> moderngl.Program:
        vert = """
#version 330
in vec2 in_vert;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    gl_Position = vec4(in_vert, 0.0, 1.0);
    v_uv = in_uv;
}
"""
        frag = """
#version 330
uniform sampler2D font_tex;
uniform vec4 color;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    float a = texture(font_tex, v_uv).r;
    fragColor = vec4(color.rgb, color.a * a);
}
"""
        return self._ctx.program(vertex_shader=vert, fragment_shader=frag)

    def _build_vbo(self) -> None:
        # We'll generate geometry dynamically per frame; start with empty buffer.
        self._vbo = self._ctx.buffer(reserve=1024 * 4 * 4)
        self._vao = self._ctx.vertex_array(
            self._prog,
            [(self._vbo, "2f 2f", "in_vert", "in_uv")],
        )

    def _char_quads(
        self,
        text: str,
        x: float,
        y: float,
        scale: float,
        color: tuple[float, float, float, float],
    ) -> np.ndarray:
        """
        Build interleaved (pos_x, pos_y, uv_x, uv_y) vertex data for `text`.
        x, y are in screen pixels from top-left.
        scale is pixels-per-cell (8 px = 1x).
        Returns float32 array of 6 vertices per character (2 tris).
        """
        norm_scale = scale * self._font_scale_norm
        char_w = float(self._glyph_w) * norm_scale
        char_h = float(self._glyph_h) * norm_scale
        atlas_w = float(self._atlas_w)
        atlas_h = float(self._atlas_h)

        verts: list[float] = []
        cx = x
        for ch in text:
            code = ord(ch) & 0x7F
            u0 = (code * self._glyph_w) / atlas_w
            u1 = u0 + float(self._glyph_w) / atlas_w
            v0 = 0.0
            v1 = float(self._glyph_h) / atlas_h

            # NDC conversion
            def px(px_val: float) -> float:
                return (px_val / self._width) * 2.0 - 1.0

            def py(py_val: float) -> float:
                return 1.0 - (py_val / self._height) * 2.0

            x0 = px(cx)
            x1 = px(cx + char_w)
            y0 = py(y)
            y1 = py(y + char_h)

            # Two triangles (6 verts)
            verts += [x0, y0, u0, v0]
            verts += [x1, y0, u1, v0]
            verts += [x0, y1, u0, v1]
            verts += [x1, y0, u1, v0]
            verts += [x1, y1, u1, v1]
            verts += [x0, y1, u0, v1]

            cx += char_w

        return np.array(verts, dtype=np.float32) if verts else np.zeros(0, dtype=np.float32)

    def _draw_text(
        self,
        text: str,
        x: float,
        y: float,
        scale: float = 2.0,
        color: tuple[float, float, float, float] = (1.0, 1.0, 0.0, 1.0),
    ) -> None:
        data = self._char_quads(text, x, y, scale, color)
        if data.size == 0:
            return
        # Resize VBO if needed.
        needed = data.nbytes
        if needed > self._vbo.size:
            self._vbo.orphan(needed * 2)
        self._vbo.write(data)
        self._prog['color'].value = color
        self._font_tex.use(location=0)
        self._prog['font_tex'].value = 0
        self._ctx.enable(moderngl.BLEND)
        self._vao.render(moderngl.TRIANGLES, vertices=len(data) // 4)

    def _draw_modal_underlay(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        alpha: float,
        pad: float = 0.0,
    ) -> None:
        """Draw a local dim underlay sized to a modal/help panel.

        The underlay is clamped to the active overlay canvas and intentionally
        avoids full-viewport fills so modal backgrounds track panel geometry in
        multi-head viewport routing.
        """
        x0 = max(0.0, float(x) - float(pad))
        y0 = max(0.0, float(y) - float(pad))
        x1 = min(float(self._width), float(x) + float(w) + float(pad))
        y1 = min(float(self._height), float(y) + float(h) + float(pad))
        if x1 <= x0 or y1 <= y0:
            return
        self._draw_rect(x0, y0, x1 - x0, y1 - y0, (0.0, 0.0, 0.0, float(alpha)))

    def _begin_panel(
        self,
        frac_w: float,
        max_w: float,
        frac_h: float,
        max_h: float,
        underlay_alpha: float = 0.58,
        underlay_pad: float = 10.0,
    ) -> tuple[float, float, float, float, float, float]:
        """Compute centred panel geometry, draw dim underlay, return (px, py, pw, ph, W, H)."""
        W = float(self._width)
        H = float(self._height)
        pw = min(W * float(frac_w), float(max_w))
        ph = min(H * float(frac_h), float(max_h))
        px = (W - pw) * 0.5
        py = (H - ph) * 0.5
        self._draw_modal_underlay(px, py, pw, ph, alpha=underlay_alpha, pad=underlay_pad)
        return px, py, pw, ph, W, H

    def _render_controller_help_modal(self) -> None:
        """Draw the controller help modal via the registered renderer (if any).

        Core owns no controller layout of its own: whichever drop-in supplies the
        connected surface registers its renderer through
        :meth:`register_controller_help_renderer`.  With no drop-in present the
        modal simply draws nothing.
        """
        if self._controller_help_renderer is None:
            return
        self._controller_help_renderer(self)

    def _render_recording_indicator(self) -> None:
        """Draw the live-only recording indicator when the name overlay is visible."""
        if not (self._recording_active and self._show_recording_indicator):
            return
        if not (self._show_name and self._name_text):
            return
        elapsed = max(0, int(self._recording_elapsed_seconds))
        minutes, seconds = divmod(elapsed, 60)
        hours, minutes = divmod(minutes, 60)
        timer_text = f'{hours:02d}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'

        if self._hud_rect is not None:
            x, y, w, _h = self._hud_rect
            dot_x = x + w - 210.0
            dot_y = y + 10.0
            time_x = x + w - 178.0
            time_y = y + 18.0
        else:
            dot_x = self._width - 84.0
            dot_y = 0.0
            time_x = self._width - 210.0
            time_y = 24.0

        self._draw_text(
            '.',
            dot_x,
            dot_y,
            scale=10.0,
            color=(1.0, 0.12, 0.12, 0.98),
        )
        self._draw_text(
            timer_text,
            time_x,
            time_y,
            scale=2.8,
            color=(1.0, 0.16, 0.16, 0.95),
        )

    def _auto_vj_status_label(self) -> str:
        """Return the Auto VJ label decorated with the current trainer badge."""
        label = str(self._hud_state.get('auto_vj_label', 'AUTO VJ') or 'AUTO VJ').strip().upper()
        badge = str(self._hud_state.get('auto_vj_training_badge', '') or '').strip()
        if badge not in {'*', '+', '='}:
            badge = ''
        if badge:
            return f'{label} {badge}'
        return label

    def _render_hud(self) -> None:
        """Render animated LCARS-style status HUD with pulsing glows, scan lines and decorations."""
        panel_w = min(1050.0, self._width * 0.93)
        lh = 28.0
        now_playing_visible = str(self._hud_state.get('now_playing_visible', 'NO')).upper() == 'YES'
        row0_offset = 264.0 if now_playing_visible else 188.0
        row_text_h = 8.0 * 2.05 + 4.0

        # ── animation clocks ─────────────────────────────────────────────
        t = self._hud_t
        pulse_slow  = 0.5 + 0.5 * math.sin(t * 1.1)          # ~5.7 s period
        pulse_med   = 0.5 + 0.5 * math.sin(t * 2.3)          # ~2.7 s period
        pulse_fast  = 0.5 + 0.5 * math.sin(t * 4.7)          # ~1.3 s period
        # racing scanline: 0→1 across the panel every 3 s
        scan_h      = math.fmod(t * 0.33, 1.0)
        # shimmer racing across the header left→right every 2.4 s
        shimmer_x   = math.fmod(t * 0.42, 1.0)
        # audio values (safe parse)
        def _fv(key: str) -> float:
            try: return float(self._hud_state.get(key, '0') or '0')
            except ValueError: return 0.0
        bass = min(_fv('bass'), 1.0)
        mid  = min(_fv('mid'),  1.0)
        auto_vj_label = self._auto_vj_status_label()

        postfx_val = str(self._hud_state.get('postfx', 'N/A'))
        # Tweakables sorted alphabetically; POST FX only shown when drop-in is loaded.
        tweak_lines = []
        if postfx_val not in {'N/A', '-', ''}:
            tweak_lines.append(f"POST FX     {postfx_val}")
        compose_dbg = str(self._hud_state.get('compose_debug', ''))
        if compose_dbg not in {'', 'N/A', '-'}:
            tweak_lines.append(f"COMPOSE     {compose_dbg}")
        tweak_lines += [
            f"REACTIVITY  {self._hud_state.get('reactivity', '1.0')}",
            f"SPEED       {self._hud_state.get('speed', 'N/A')}",
            f"ZOOM        {self._hud_state.get('zoom', 'N/A')}",
            f"VIZ QUAL    {self._hud_state.get('render_scale', '1.00')}",
        ]

        left_lines = [
            f"B / M / T   {self._hud_state.get('bass', '0.00')} / {self._hud_state.get('mid', '0.00')} / {self._hud_state.get('treble', '0.00')}",
            f"Bn/Mn/Tn    {self._hud_state.get('bass_n', '0.50')} / {self._hud_state.get('mid_n', '0.50')} / {self._hud_state.get('treble_n', '0.50')}",
            f"INPUT RMS   {self._hud_state.get('audio_rms', '0.0000')}",
            f"FPS         {self._hud_state.get('fps', '0.0')}",
            f"FRAME MS    {self._hud_state.get('frame_ms', '0.0')}",
            f"RES         {self._hud_state.get('resolution', '-')}",
            f"PLAYLIST    {self._hud_state.get('playlist', '-')}",
            f"AUDIO SRC   {self._hud_state.get('audio_source', '-')}",
            f"BPM PROF    {self._hud_state.get('audio_profile', 'house')}",
            f"REC PROF    {self._hud_state.get('audio_profile_reco', '-')}",
            '',
            '[ TWEAKABLES ]',
            *tweak_lines,
        ]
        right_lines = [
            f"ADV TIMER   {self._hud_state.get('advance_time', '0.0/20.0s')}",
            f"AUTO ADV    {self._hud_state.get('auto_advance', 'ON')}",
            f"DISPLAY     {self._hud_state.get('display_mode', 'single')} #{self._hud_state.get('display_index', '0')}",
            f"FULLSCREEN  {self._hud_state.get('fullscreen', 'NO')}",
            f"INVERT      {self._hud_state.get('invert', 'OFF')}",
            f"NEXT FX     {self._hud_state.get('next_effect', '-')}",
            f"PAUSED      {self._hud_state.get('paused', 'NO')}",
            f"{self._hud_state.get('preset_slot_label', 'PRESET IDX'):<11} {self._hud_state.get('preset_slot', '-/-')}",
            f"PREV FX     {self._hud_state.get('previous_effect', '-')}",
            f"RECORDING   {self._hud_state.get('recording', 'OFF')}",
            f"SPOTIFY     {self._hud_state.get('spotify_auth_status', 'Sh+M to auth')}",
            f"STREAM SRV  {self._hud_state.get('streaming_provider', '-')}",
            f"STREAMING   {self._hud_state.get('streaming', 'OFF')}",
            f"TRANSITION  {self._hud_state.get('transition', '-')} ({self._hud_state.get('transition_t', '0%')})",
            f"{self._hud_state.get('variant_slot_label', 'VARIANT'):<11} {self._hud_state.get('variant_slot', '-/-')}",
        ]

        rows = max(len(left_lines), len(right_lines))
        content_bottom = row0_offset + max(0, rows - 1) * lh + row_text_h
        panel_h_needed = content_bottom + 34.0
        panel_h_base = min(max(520.0, panel_h_needed), self._height * 0.88)
        panel_h_extra = max(50.0, panel_h_base * 0.05)
        panel_h = min(panel_h_base + panel_h_extra, self._height * 0.93)
        x = (self._width - panel_w) * 0.5
        y = max(36.0, (self._height - panel_h) * 0.5)
        self._hud_rect = (x, y, panel_w, panel_h)

        data_zone_y  = y + row0_offset - 8.0
        data_zone_h  = rows * lh + 16.0

        # ── layer 0: breathing outer halo ────────────────────────────────
        halo_a = 0.06 + pulse_slow * 0.10
        self._draw_rect(x - 18.0, y - 18.0, panel_w + 36.0, panel_h + 36.0, (0.08, 0.88, 1.0, halo_a * 0.5))
        self._draw_rect(x - 8.0,  y - 8.0,  panel_w + 16.0, panel_h + 16.0, (0.08, 0.88, 1.0, halo_a))

        # ── layer 1: main panel background ───────────────────────────────
        self._draw_rect(x, y, panel_w, panel_h, (0.02, 0.04, 0.08, 0.65))

        # ── layer 2: animated outer border (pulsing alpha) ───────────────
        border_a = 0.50 + pulse_slow * 0.34
        self._draw_rect(x - 1.0, y - 1.0, panel_w + 2.0, 2.0,          (0.10, 0.94, 1.0, border_a))
        self._draw_rect(x - 1.0, y + panel_h - 1.0, panel_w + 2.0, 2.0, (0.10, 0.94, 1.0, border_a))
        self._draw_rect(x - 1.0, y - 1.0, 2.0, panel_h + 2.0,          (0.10, 0.94, 1.0, border_a))
        self._draw_rect(x + panel_w - 1.0, y - 1.0, 2.0, panel_h + 2.0, (0.10, 0.94, 1.0, border_a))

        # ── sparkle sprite chasing the containment border ─────────────────
        # Position 0→1 travels: top-left → top-right → bottom-right → bottom-left → back
        # Speed: one full lap every 4 s
        sprite_t = math.fmod(t * 0.20, 1.0)
        perim    = 2.0 * (panel_w + panel_h)
        dist     = sprite_t * perim
        top_seg  = panel_w
        right_seg= panel_h
        bot_seg  = panel_w
        # left_seg = panel_h (remainder)
        if dist < top_seg:                              # top edge L→R
            sx, sy = x + dist, y - 1.0
        elif dist < top_seg + right_seg:               # right edge T→B
            sx, sy = x + panel_w - 1.0, y + (dist - top_seg)
        elif dist < top_seg + right_seg + bot_seg:     # bottom edge R→L
            sx, sy = x + panel_w - (dist - top_seg - right_seg), y + panel_h - 1.0
        else:                                           # left edge B→T
            sx, sy = x - 1.0, y + panel_h - (dist - top_seg - right_seg - bot_seg)
        # glow layers: wide soft bloom → tight mid → bright core
        sp_a = 0.72 + 0.28 * math.sin(t * 11.3)   # fast inner flicker — starts at 0.72 floor
        self._draw_rect(sx - 10.0, sy - 10.0, 22.0, 22.0, (0.10, 0.94, 1.0, sp_a * 0.22))
        self._draw_rect(sx -  7.0, sy -  7.0, 16.0, 16.0, (0.10, 0.94, 1.0, sp_a * 0.46))
        self._draw_rect(sx -  4.0, sy -  4.0, 10.0, 10.0, (0.50, 0.98, 1.0, sp_a * 0.76))
        self._draw_rect(sx -  2.0, sy -  2.0,  6.0,  6.0, (0.80, 1.00, 1.0, sp_a * 0.92))
        self._draw_rect(sx -  1.0, sy -  1.0,  4.0,  4.0, (1.00, 1.00, 1.0, min(1.0, sp_a * 1.10)))
        # trailing ghost — half-lap behind
        trail_t  = math.fmod(sprite_t + 0.5, 1.0)
        trail_d  = trail_t * perim
        if trail_d < top_seg:
            tx2, ty2 = x + trail_d, y - 1.0
        elif trail_d < top_seg + right_seg:
            tx2, ty2 = x + panel_w - 1.0, y + (trail_d - top_seg)
        elif trail_d < top_seg + right_seg + bot_seg:
            tx2, ty2 = x + panel_w - (trail_d - top_seg - right_seg), y + panel_h - 1.0
        else:
            tx2, ty2 = x - 1.0, y + panel_h - (trail_d - top_seg - right_seg - bot_seg)
        tr_a = 0.42 + 0.28 * math.sin(t * 7.1)
        self._draw_rect(tx2 - 5.0, ty2 - 5.0, 12.0, 12.0, (0.78, 0.38, 1.00, tr_a * 0.38))
        self._draw_rect(tx2 - 3.0, ty2 - 3.0,  8.0,  8.0, (0.78, 0.38, 1.00, tr_a * 0.65))
        self._draw_rect(tx2 - 1.0, ty2 - 1.0,  4.0,  4.0, (1.00, 0.70, 1.00, tr_a * 0.90))

        # ── layer 3: LCARS side decorative block stacks ───────────────────
        # Each block has its own independent phase so they flash individually.
        # Tuple: (height, base_rgb, base_alpha, phase_offset, phase_speed, strobe_speed)
        side_w   = 18.0
        block_defs = [
            (28.0, (1.00, 0.58, 0.12), 0.68, 0.00, 2.30, 0.0 ),   # orange
            (6.0,  None, 0, 0, 0, 0),
            (8.0,  (1.00, 0.58, 0.12), 0.34, 0.70, 4.10, 7.3 ),   # orange thin – fast strobe
            (6.0,  None, 0, 0, 0, 0),
            (44.0, (0.10, 0.94, 1.00), 0.68, 1.10, 1.80, 0.0 ),   # teal large
            (6.0,  None, 0, 0, 0, 0),
            (14.0, (0.78, 0.38, 1.00), 0.56, 2.20, 3.50, 0.0 ),   # violet
            (6.0,  None, 0, 0, 0, 0),
            (60.0, (1.00, 0.58, 0.12), 0.56, 0.50, 1.10, 0.0 ),   # orange long
            (6.0,  None, 0, 0, 0, 0),
            (14.0, (0.10, 0.94, 1.00), 0.48, 1.80, 5.20, 11.7),   # teal – fast strobe
            (6.0,  None, 0, 0, 0, 0),
            (28.0, (0.98, 0.96, 0.30), 0.52, 0.90, 2.70, 0.0 ),   # yellow
            (6.0,  None, 0, 0, 0, 0),
            (14.0, (0.78, 0.38, 1.00), 0.44, 3.10, 4.80, 9.1 ),   # violet – strobe
            (6.0,  None, 0, 0, 0, 0),
            (24.0, (1.00, 0.58, 0.12), 0.62, 1.60, 2.10, 0.0 ),   # orange
        ]
        side_rx = x + panel_w + 4.0
        side_lx = x - 4.0 - side_w
        by_r = y
        by_l = y
        for bdef in block_defs:
            bh = bdef[0]
            if bdef[1] is None:          # gap
                by_r += bh
                by_l += bh
                continue
            bh, rgb, base_a, phase, spd, strobe_spd = bdef
            pulse_val = 0.5 + 0.5 * math.sin(t * spd + phase)
            alpha = base_a + pulse_val * 0.28
            if strobe_spd > 0:
                # occasional fast strobe: rectified high-freq sine → sharp flash
                strobe = max(0.0, math.sin(t * strobe_spd)) ** 3
                alpha = min(1.0, alpha + strobe * 0.38)
            bc = (rgb[0], rgb[1], rgb[2], min(1.0, alpha))
            # right side
            self._draw_rect(side_rx, by_r, side_w, bh, bc)
            # edge highlight (inner thin bright line)
            hi_a = min(1.0, alpha * 0.55 + pulse_val * 0.25)
            self._draw_rect(side_rx, by_r, 2.0, bh, (1.0, 1.0, 1.0, hi_a))
            # left side (mirrored — edge highlight on right edge of block)
            self._draw_rect(side_lx, by_l, side_w, bh, bc)
            self._draw_rect(side_lx + side_w - 2.0, by_l, 2.0, bh, (1.0, 1.0, 1.0, hi_a))
            by_r += bh
            by_l += bh

        # ── layer 4: corner accent blocks + crosshair arms (pulsing orange) ───
        corner_sz = 14.0
        ca = 0.65 + pulse_fast * 0.30
        self._draw_rect(x - 1.0, y - 1.0, corner_sz, corner_sz,                                   (1.0, 0.58, 0.12, ca))
        self._draw_rect(x + panel_w - corner_sz + 1.0, y - 1.0, corner_sz, corner_sz,             (1.0, 0.58, 0.12, ca))
        self._draw_rect(x - 1.0, y + panel_h - corner_sz + 1.0, corner_sz, corner_sz,             (1.0, 0.58, 0.12, ca))
        self._draw_rect(x + panel_w - corner_sz + 1.0, y + panel_h - corner_sz + 1.0, corner_sz, corner_sz, (1.0, 0.58, 0.12, ca))
        # Inner teal corner squares
        ic = 6.0
        ica = 0.52 + pulse_slow * 0.32
        self._draw_rect(x + 2.0, y + 2.0, ic, ic, (0.10, 0.94, 1.0, ica))
        self._draw_rect(x + panel_w - ic - 2.0, y + 2.0, ic, ic, (0.10, 0.94, 1.0, ica))
        self._draw_rect(x + 2.0, y + panel_h - ic - 2.0, ic, ic, (0.10, 0.94, 1.0, ica))
        self._draw_rect(x + panel_w - ic - 2.0, y + panel_h - ic - 2.0, ic, ic, (0.10, 0.94, 1.0, ica))
        # Corner crosshair arms — thin lines extending inward from each corner
        arm_len = 40.0
        arm_a   = 0.28 + pulse_slow * 0.20
        # top-left
        self._draw_rect(x + corner_sz, y + 1.0,    arm_len, 1.0, (1.0, 0.58, 0.12, arm_a))  # horiz
        self._draw_rect(x + 1.0, y + corner_sz,    1.0, arm_len, (1.0, 0.58, 0.12, arm_a))  # vert
        # top-right
        self._draw_rect(x + panel_w - corner_sz - arm_len, y + 1.0,    arm_len, 1.0, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + panel_w - 2.0, y + corner_sz,              1.0, arm_len, (1.0, 0.58, 0.12, arm_a))
        # bottom-left
        self._draw_rect(x + corner_sz, y + panel_h - 2.0,              arm_len, 1.0, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + 1.0, y + panel_h - corner_sz - arm_len,   1.0, arm_len, (1.0, 0.58, 0.12, arm_a))
        # bottom-right
        self._draw_rect(x + panel_w - corner_sz - arm_len, y + panel_h - 2.0, arm_len, 1.0, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + panel_w - 2.0, y + panel_h - corner_sz - arm_len, 1.0, arm_len, (1.0, 0.58, 0.12, arm_a))

        # ── layer 5: header ──────────────────────────────────────────────
        self._draw_rect(x, y, panel_w, 100.0, (0.05, 0.08, 0.16, 0.80))

        # Header shimmer: bright spot racing left→right along the title bar
        shim_w = panel_w * 0.18
        shim_x = x + shimmer_x * (panel_w - shim_w)
        self._draw_rect(shim_x, y, shim_w, 100.0, (1.0, 1.0, 1.0, 0.04 + pulse_fast * 0.04))

        # Header separator — triple lines for LCARS depth
        bar_a = 0.60 + pulse_slow * 0.22
        self._draw_rect(x, y + 94.0, panel_w, 2.0, (1.0, 0.62, 0.20, bar_a * 0.5))
        self._draw_rect(x, y + 97.0, panel_w, 4.0, (1.0, 0.62, 0.20, bar_a))
        self._draw_rect(x, y + 102.0, panel_w, 1.0, (1.0, 0.62, 0.20, bar_a * 0.4))

        # Title — no background rect; text pulses inversely to where the bg was
        title = self._hud_state.get('title', 'Unicorn Viz')
        tx = x + (panel_w - len(title) * 8.0 * 3.0) * 0.5
        # Inverse of pulse_med: bright when pulse_med is low, dim when it peaks
        title_a = 0.86 + (1.0 - pulse_med) * 0.14
        self._draw_text(title, tx, y + 8.0, scale=3.0, color=(0.12, 0.98, 1.0, title_a))

        # Date/time (orange)
        now = datetime.datetime.now()
        dt_line = f"{now.strftime('%Y-%m-%d')}  {now.strftime('%H:%M:%S')}"
        dx = x + (panel_w - len(dt_line) * 8.0 * 2.2) * 0.5
        self._draw_text(dt_line, dx, y + 44.0, scale=2.2, color=(1.0, 0.64 + pulse_slow * 0.10, 0.22, 0.94))
        session_line = f"SESSION   {self._hud_state.get('session_time', '00:00')}"
        sx_session = x + (panel_w - len(session_line) * 8.0 * 2.2) * 0.5
        self._draw_text(session_line, sx_session, y + 76.0, scale=2.2, color=(0.12, 0.98, 1.0, title_a))

        # ── layer 6: now-playing sub-pane + effect banner ────────────────
        band_x = x + 8.0
        band_y = y + 104.0
        band_w = panel_w - 16.0
        band_h = 156.0 if now_playing_visible else 80.0

        # Now-playing sub-pane (between title/timer header and main data panes).
        now_playing_h = 72.0 if now_playing_visible else 0.0
        now_playing_y = band_y
        now_playing_status = str(self._hud_state.get('now_playing_status', 'OFF'))
        now_playing_track = str(self._hud_state.get('now_playing_track', '-'))
        now_playing_artist = str(self._hud_state.get('now_playing_artist', '-'))
        now_playing_progress = str(self._hud_state.get('now_playing_progress', '--:--/--:-- 0%'))

        status_l = now_playing_status.lower()
        if status_l == 'playing':
            accent = (0.16, 0.95, 0.48)
        elif status_l == 'paused':
            accent = (0.78, 0.52, 1.00)
        else:
            accent = (0.46, 0.90, 0.98)

        # Effect banner lives below the now-playing pane when visible, otherwise occupies the top band.
        effect_y = now_playing_y + now_playing_h + 4.0 if now_playing_visible else band_y
        effect_h = 80.0
        banner_glow_a = 0.06 + bass * 0.26 + pulse_slow * 0.04
        self._draw_rect(band_x, effect_y, band_w, effect_h, (0.04, 0.60 + bass * 0.40, 0.80, banner_glow_a))
        self._draw_rect(band_x, effect_y, band_w, effect_h, (0.03, 0.07, 0.14, 0.72))
        banner_race = math.fmod(t * 0.55 + 0.5, 1.0)
        brace_w = panel_w * 0.20
        brace_x = band_x + banner_race * (band_w - brace_w)
        self._draw_rect(brace_x, effect_y, brace_w, effect_h, (1.0, 1.0, 1.0, 0.03 + pulse_fast * 0.03))
        self._draw_rect(x, effect_y, 6.0, effect_h, (1.0, 0.62, 0.20, 0.76 + pulse_med * 0.20))
        self._draw_rect(x + panel_w - 6.0, effect_y, 6.0, effect_h, (1.0, 0.62, 0.20, 0.56 + pulse_slow * 0.22))
        effect_a = 0.88 + (1.0 - pulse_slow) * 0.12
        self._draw_text(
            f"EFFECT: {self._hud_state.get('effect', '-')}",
            x + 20.0,
            effect_y + 8.0,
            scale=3.0,
            color=(0.12, 1.0, 1.0, effect_a),
        )
        self._draw_text(
            f"TRANSITION: {self._hud_state.get('transition', '-')} ({self._hud_state.get('transition_t', '0%')})",
            x + 20.0,
            effect_y + 44.0,
            scale=2.3,
            color=(1.0, 0.66 + pulse_fast * 0.12, 0.24, 0.94),
        )

        if now_playing_visible:
            # Now-playing pane sits above the effect banner to avoid overlap.
            self._draw_rect(band_x, now_playing_y, band_w, now_playing_h, (0.02, 0.14, 0.10, 0.84))
            self._draw_rect(band_x, now_playing_y, band_w, 2.0, (accent[0], accent[1], accent[2], 0.62 + pulse_med * 0.20))
            self._draw_rect(band_x, now_playing_y + now_playing_h - 2.0, band_w, 2.0, (accent[0], accent[1], accent[2], 0.46 + pulse_slow * 0.16))
            self._draw_rect(band_x, now_playing_y, 4.0, now_playing_h, (accent[0], accent[1], accent[2], 0.78))

            now_playing_phase = t * 0.85
            now_playing_a = 0.88 + (1.0 - pulse_slow) * 0.12
            if status_l == 'paused':
                line_rgb = (
                    0.90 + 0.06 * math.sin(now_playing_phase + 0.6),
                    0.72 + 0.08 * math.sin(now_playing_phase + 2.0),
                    1.00,
                )
            elif status_l == 'playing':
                line_rgb = (
                    0.86 + 0.08 * math.sin(now_playing_phase + 0.15),
                    1.00,
                    0.90 + 0.06 * math.sin(now_playing_phase + 2.7),
                )
            else:
                line_rgb = (
                    0.84,
                    0.98,
                    1.00,
                )

            char_w_now_playing = float(self._glyph_w) * self._font_scale_norm * 2.2
            center_line = f'{now_playing_artist} | {now_playing_track} | {now_playing_progress}'
            text_w = len(center_line) * char_w_now_playing
            center_x = band_x + max(8.0, (band_w - text_w) * 0.5)
            self._draw_text(center_line, center_x, now_playing_y + 14.0, scale=2.2, color=(line_rgb[0], line_rgb[1], line_rgb[2], now_playing_a))

            pct = 0.0
            if '%' in now_playing_progress:
                try:
                    pct = float(now_playing_progress.rsplit(' ', 1)[-1].replace('%', '').strip())
                except Exception:
                    pct = 0.0
            pct = max(0.0, min(100.0, pct))

            rail_pad = 12.0
            rail_x = band_x + rail_pad
            rail_y = now_playing_y + 40.0
            rail_w = band_w - rail_pad * 2.0
            rail_h = 26.0
            rail_center_y = rail_y + rail_h * 0.5

            # Waveform mode: live PCM waveform fed by app.py each frame.
            # Gate: auto-vj must have live BPM and a waveform must be available.
            _wf_bpm = _fv('auto_vj_bpm')
            wf = self._live_waveform
            waveform_mode = (
                _wf_bpm > 0.0
                and wf is not None
                and len(wf) > 0
            )

            if waveform_mode:
                _beat = _fv('audio_beat')
                # Leaky-peak beat glow: snaps up on beat, decays between frames.
                self._now_playing_beat_decay = max(
                    self._now_playing_beat_decay * 0.80,
                    min(1.0, _beat * 1.5),
                )
                beat_g = self._now_playing_beat_decay

                _N = 128
                col_w = rail_w / _N
                fill_col = min(_N - 1, int(pct / 100.0 * _N))
                wf_len = len(wf)

                # Dim full-rail background + thin center guide line so the
                # unplayed portion is visible as a faint track-length marker.
                self._draw_rect(rail_x, rail_y, rail_w, rail_h, (0.05, 0.10, 0.08, 0.55))
                self._draw_rect(rail_x, rail_center_y - 0.5, rail_w, 1.0, (0.22, 0.42, 0.30, 0.55))

                # Waveform bars for the played portion.
                # Each column samples the current live waveform at a proportional
                # index; the whole waveform is always visible, growing rightward.
                for _ci in range(fill_col + 1):
                    _wi = int(_ci / max(1, fill_col) * (wf_len - 1))
                    _sample = abs(float(wf[_wi]))  # already peak-normalised to [0, 1]
                    _bar_h = max(2.0, _sample * rail_h * 0.92)
                    _bar_y = rail_center_y - _bar_h * 0.5
                    _cx = rail_x + _ci * col_w
                    # Uniform brightness from amplitude + beat — no hue shift,
                    # so the accent color never drifts yellow.
                    _bright = 0.45 + _sample * 0.55 + beat_g * 0.12
                    _r = min(1.0, accent[0] * _bright)
                    _g = min(1.0, accent[1] * _bright)
                    _b = min(1.0, accent[2] * _bright)
                    _a = 0.80 + beat_g * 0.15
                    self._draw_rect(_cx, _bar_y, max(1.0, col_w - 0.4), _bar_h, (_r, _g, _b, _a))
            else:
                fill_w = rail_w * (pct / 100.0)
                self._draw_rect(rail_x, rail_y, rail_w, rail_h, (0.12, 0.24, 0.22, 0.85))
                self._draw_rect(rail_x, rail_y, fill_w, rail_h, (accent[0], accent[1], accent[2], 0.95))

        # ── layer 7: data zone separator ─────────────────────────────────
        self._draw_rect(x, data_zone_y - 4.0, panel_w, 1.0, (0.10, 0.94, 1.0, 0.24))
        self._draw_rect(x, data_zone_y - 2.0, panel_w, 2.0, (0.10, 0.94, 1.0, 0.44 + pulse_med * 0.16))
        # Mid-panel vertical divider
        mid_div_x = x + panel_w * 0.50
        self._draw_rect(mid_div_x - 1.0, data_zone_y, 1.0, data_zone_h, (0.10, 0.94, 1.0, 0.16))
        self._draw_rect(mid_div_x,        data_zone_y, 1.0, data_zone_h, (0.10, 0.94, 1.0, 0.32))

        # ── layer 8: vertical scan line ──────────────────────────────────
        # A bright thin bar that travels top→bottom through the data zone
        scan_y = data_zone_y + scan_h * data_zone_h
        self._draw_rect(x + 8.0, scan_y - 1.0, panel_w - 16.0, 2.0, (0.10, 0.94, 1.0, 0.06))
        self._draw_rect(x + 8.0, scan_y,        panel_w - 16.0, 1.0, (0.10, 0.94, 1.0, 0.18))

        # ── layer 9: data rows ───────────────────────────────────────────
        left_x   = x + 22.0
        right_x  = x + panel_w * 0.52
        row0     = y + row0_offset
        col_half = panel_w * 0.46

        # Left column accent stripe — runs full data zone height so it matches right column
        stripe_h = max(len(left_lines), len(right_lines)) * lh + 8.0
        stripe_a = 0.44 + pulse_med * 0.18 + bass * 0.18
        self._draw_rect(x + 6.0, row0 - 4.0, 3.0, stripe_h, (0.10, 0.96, 1.0, stripe_a))
        # Inner glow strip next to stripe
        self._draw_rect(x + 10.0, row0 - 4.0, 2.0, stripe_h, (0.10, 0.96, 1.0, stripe_a * 0.35))

        for i, ln in enumerate(left_lines):
            row_y = row0 + i * lh
            if i % 2 == 0:
                self._draw_rect(left_x - 8.0, row_y - 2.0, col_half, lh + 2.0, (0.06, 0.10, 0.16, 0.35))
            self._draw_text(ln, left_x, row_y, scale=2.05, color=(0.84, 0.98, 1.0, 0.96))

        # Right column accent stripe — orange, mid-reactive
        rstripe_a = 0.48 + pulse_slow * 0.16 + mid * 0.18
        self._draw_rect(x + panel_w - 9.0, row0 - 4.0, 3.0, len(right_lines) * lh + 8.0, (1.0, 0.62, 0.20, rstripe_a))
        self._draw_rect(x + panel_w - 12.0, row0 - 4.0, 2.0, len(right_lines) * lh + 8.0, (1.0, 0.62, 0.20, rstripe_a * 0.35))

        for i, ln in enumerate(right_lines):
            row_y = row0 + i * lh
            if i % 2 == 1:
                self._draw_rect(right_x - 8.0, row_y - 2.0, col_half, lh + 2.0, (0.16, 0.08, 0.04, 0.35))
            self._draw_text(ln, right_x, row_y, scale=2.05, color=(0.98, 0.68, 0.22, 0.96))

        # ── layer 9.5: fixed bottom Auto VJ status section ─────────────
        status_box_x = x + 8.0
        status_box_w = panel_w - 16.0
        status_box_h = 54.0
        status_box_y = y + panel_h - 76.0
        self._draw_rect(status_box_x, status_box_y, status_box_w, status_box_h, (0.03, 0.08, 0.14, 0.84))
        self._draw_rect(status_box_x, status_box_y, status_box_w, 2.0, (0.10, 0.94, 1.0, 0.40 + pulse_med * 0.14))
        self._draw_rect(status_box_x, status_box_y + status_box_h - 2.0, status_box_w, 2.0, (0.10, 0.94, 1.0, 0.28 + pulse_slow * 0.12))
        self._draw_rect(status_box_x, status_box_y, 2.0, status_box_h, (0.10, 0.94, 1.0, 0.20 + pulse_slow * 0.10))
        self._draw_rect(status_box_x + status_box_w - 2.0, status_box_y, 2.0, status_box_h, (0.10, 0.94, 1.0, 0.20 + pulse_slow * 0.10))

        mood = str(self._hud_state.get('auto_vj_mood', '-')).upper()
        scene = str(self._hud_state.get('auto_vj_scene', '-')).upper()
        genre = str(self._hud_state.get('audio_profile_name', '-'))
        if len(genre) > 18:
            genre = genre[:15] + '...'
        bpm = str(self._hud_state.get('auto_vj_bpm', '--'))
        bpm_conf = str(self._hud_state.get('auto_vj_bpm_conf', '--'))
        action_in = str(self._hud_state.get('auto_vj_action_in', '--'))

        line1 = f'{auto_vj_label} | MOOD: {mood:<8} | SCENE: {scene:<10} | GENRE: {genre:<18}'
        line2 = f'BPM: {bpm:>3} ({bpm_conf}) | ACTION IN: {action_in:<4}'
        char_w = float(self._glyph_w) * self._font_scale_norm * 1.9
        line1_w = len(line1) * char_w
        line2_w = len(line2) * char_w
        block_w = max(line1_w, line2_w)
        block_x = status_box_x + (status_box_w - block_w) * 0.5
        line1_x = block_x + (block_w - line1_w) * 0.5
        line2_x = block_x + (block_w - line2_w) * 0.5
        # Subtle Unicorn Tears-inspired color drift for the top status line.
        tears_phase = t * 0.55
        tears_r = 0.82 + 0.10 * math.sin(tears_phase + 0.10)
        tears_g = 0.93 + 0.05 * math.sin(tears_phase + 2.05)
        tears_b = 0.90 + 0.10 * math.sin(tears_phase + 4.15)
        self._draw_text(
            line1,
            line1_x,
            status_box_y + 7.0,
            scale=1.9,
            color=(tears_r, tears_g, tears_b, 0.96),
        )
        self._draw_text(line2, line2_x, status_box_y + 30.0, scale=1.9, color=(1.0, 0.68, 0.22, 0.96))

        # Beat/downbeat pulse dot -- pulses cyan on every beat (_hud_beat_pulse,
        # fast ~1/8s decay) and flashes magenta on downbeats (_hud_downbeat_pulse,
        # slower ~1/3s decay so the flash reads as a distinct event rather than
        # blending into the very next beat). Lets an operator see at a glance
        # whether beats/downbeats are actually firing on-tempo or stalled.
        beat_pulse = min(1.0, max(0.0, _fv('auto_vj_beat_pulse')))
        downbeat_pulse = min(1.0, max(0.0, _fv('auto_vj_downbeat_pulse')))
        combined_pulse = max(beat_pulse, downbeat_pulse)
        char_h_line2 = float(self._glyph_h) * self._font_scale_norm * 1.9
        # Downbeats are a superset trigger of beats (every 4th beat is also a
        # downbeat), so both pulses spike together on that frame -- the extra
        # downbeat_pulse term makes that flash visibly bigger than a plain beat.
        dot_h = 8.0 + beat_pulse * 6.0 + downbeat_pulse * 10.0
        dot_gap = 10.0
        dot_x = line2_x - dot_gap - dot_h
        dot_y = status_box_y + 30.0 + (char_h_line2 - dot_h) * 0.5
        _pulse_cyan = (0.10, 0.94, 1.0)
        _pulse_magenta = (1.0, 0.10, 0.90)
        mix = downbeat_pulse
        dot_r = _pulse_cyan[0] + (_pulse_magenta[0] - _pulse_cyan[0]) * mix
        dot_g = _pulse_cyan[1] + (_pulse_magenta[1] - _pulse_cyan[1]) * mix
        dot_b = _pulse_cyan[2] + (_pulse_magenta[2] - _pulse_cyan[2]) * mix
        if combined_pulse > 0.05:
            glow_pad = 3.0 + combined_pulse * 4.0
            self._draw_rect(
                dot_x - glow_pad * 0.5, dot_y - glow_pad * 0.5,
                dot_h + glow_pad, dot_h + glow_pad,
                (dot_r, dot_g, dot_b, combined_pulse * 0.25),
            )
        dot_alpha = 0.30 + combined_pulse * 0.70
        self._draw_rect(
            dot_x, dot_y, dot_h, dot_h,
            (dot_r, dot_g, dot_b, dot_alpha),
        )

        # ── layer 10: LCARS tick marks (right edge decoration) ───────────
        # Three evenly spaced horizontal tick marks on the right border
        tick_x = x + panel_w - 24.0
        tick_positions = [0.25, 0.5, 0.75]
        tick_colors = [
            (0.10, 0.94, 1.0, 0.52 + pulse_slow * 0.24),
            (1.00, 0.62, 0.20, 0.52 + pulse_med  * 0.24),
            (0.78, 0.38, 1.00, 0.52 + pulse_fast * 0.24),
        ]
        for tp, tc in zip(tick_positions, tick_colors):
            ty = y + tp * panel_h
            self._draw_rect(tick_x,        ty - 1.0, 18.0, 1.0, (tc[0], tc[1], tc[2], tc[3] * 0.4))
            self._draw_rect(tick_x,        ty,        18.0, 3.0, tc)
            self._draw_rect(tick_x,        ty + 3.0, 18.0, 1.0, (tc[0], tc[1], tc[2], tc[3] * 0.4))
        # Mirror on the left edge
        ltick_x = x + 6.0
        for tp, tc in zip(tick_positions, tick_colors):
            ty = y + tp * panel_h
            self._draw_rect(ltick_x, ty - 1.0, 18.0, 1.0, (tc[0], tc[1], tc[2], tc[3] * 0.4))
            self._draw_rect(ltick_x, ty,        18.0, 3.0, tc)
            self._draw_rect(ltick_x, ty + 3.0, 18.0, 1.0, (tc[0], tc[1], tc[2], tc[3] * 0.4))

        # ── layer 11: bottom accent bar — segmented blocks ───────────────
        seg_n   = 12
        seg_gap = 4.0
        seg_w   = (panel_w - (seg_n - 1) * seg_gap) / seg_n
        for s in range(seg_n):
            phase = math.sin(t * 1.8 + s * 0.52)
            seg_a = 0.30 + 0.24 * (0.5 + 0.5 * phase)
            sx = x + s * (seg_w + seg_gap)
            self._draw_rect(sx, y + panel_h - 8.0, seg_w, 8.0, (0.12, 0.96, 1.0, seg_a))
        # Solid thin line above segments
        self._draw_rect(x, y + panel_h - 10.0, panel_w, 2.0, (0.10, 0.94, 1.0, 0.44 + pulse_med * 0.18))

    # ------------------------------------------------------------------
    # Right-click context menu
    # ------------------------------------------------------------------

    @property
    def context_menu_open(self) -> bool:
        """Return True while the right-click context menu is showing."""
        return self._context_menu_open

    @property
    def context_menu_entries(self) -> list[dict[str, object]]:
        """Return the current context-menu entry dicts (as built by App)."""
        return self._context_menu_entries

    @property
    def blocking_modal_open(self) -> bool:
        """Return True if a full-screen selector/browser/manager modal is open.

        Used to suppress opening the context menu on top of another modal.
        """
        return bool(
            self._show_presets
            or self._show_effects_browser
            or self._show_projectm_manager
            or self._show_system_monitor_modal
            or self._show_controller_help_modal
            or self._show_webcam_editor_modal
            or self._show_audio
            or self._show_midi
            or self._show_config_editor
            or self._show_tour
        )

    def dropin_help_entries(self) -> list[tuple[str, str, str]]:
        """Return registered drop-in help entries as ``(section, key, desc)``.

        Sourced from the dynamically-registered drop-in HELP_ENTRIES so callers
        (e.g. the context menu) never hard-code drop-in features.
        """
        out: list[tuple[str, str, str]] = []
        sections = getattr(self, '_dynamic_help_sections', {}) or {}
        order = getattr(self, '_dynamic_help_order', None) or list(sections.keys())
        for section in order:
            for key, desc in sections.get(section, []):
                out.append((str(section), str(key), str(desc)))
        return out

    def open_context_menu(
        self, entries: list[dict[str, object]], x: float, y: float
    ) -> None:
        """Open the context menu at ``(x, y)`` with App-built entry dicts.

        Sections start collapsed (accordion); clicking a section header expands
        its items inline.  Non-collapsible sections (empty-title separators, e.g.
        the footer) are always shown.
        """
        self._context_menu_entries = list(entries)
        self._context_menu_x = float(x)
        self._context_menu_y = float(y)
        self._context_menu_hover = -1
        self._context_menu_expanded = set()
        self._context_menu_anim = 0.0
        self._context_menu_fading = False
        self._context_menu_open = bool(self._context_menu_entries)

    def close_context_menu(self) -> None:
        """Dismiss the context menu (animates closed, then stops rendering)."""
        if self._context_menu_open:
            self._context_menu_fading = True  # keep rendering while it rolls up
        self._context_menu_open = False
        self._context_menu_hover = -1

    def tick_context_menu(self, dt: float) -> None:
        """Advance the open/close unroll animation toward its target."""
        if not (self._context_menu_open or self._context_menu_fading):
            return
        target = 1.0 if self._context_menu_open else 0.0
        rate = float(dt) / 0.13  # ~130 ms open/close
        if self._context_menu_anim < target:
            self._context_menu_anim = min(target, self._context_menu_anim + rate)
        elif self._context_menu_anim > target:
            self._context_menu_anim = max(target, self._context_menu_anim - rate)
        if self._context_menu_fading and self._context_menu_anim <= 0.001:
            self._context_menu_fading = False

    @property
    def context_menu_visible(self) -> bool:
        """True while the menu should render (open or animating closed)."""
        return self._context_menu_open or self._context_menu_fading

    _CONTEXT_MENU_ROW_SCALE = 2.1
    _CONTEXT_MENU_HINT_SCALE = 1.7

    def _context_menu_is_collapsible(self, entry: dict[str, object]) -> bool:
        """A header with a non-empty title is a collapsible section header."""
        return bool(entry.get('header')) and bool(str(entry.get('label', '')).strip())

    def _context_menu_layout(self) -> dict[str, object]:
        """Compute panel + per-row geometry for the currently-visible rows.

        Section items are only laid out when their header is expanded.  Panel
        width is derived from *all* entries so it stays stable as sections open
        and close; only the height changes.
        """
        entries = self._context_menu_entries
        expanded = self._context_menu_expanded
        scale = self._CONTEXT_MENU_ROW_SCALE
        char_w = float(self._glyph_w) * self._font_scale_norm * scale
        row_h = 8.0 * scale + 14.0
        header_h = 8.0 * scale + 10.0
        pad_x = 16.0
        arrow_w = char_w * 2.0
        gap = 34.0

        label_w = max(
            (len(str(e.get('label', ''))) * char_w for e in entries), default=80.0
        )
        hint_w = max(
            (len(str(e.get('hotkey', '') or '')) * char_w for e in entries), default=0.0
        )
        panel_w = pad_x * 2 + arrow_w + label_w + (gap + hint_w if hint_w > 0.0 else 0.0)
        panel_w = max(220.0, min(panel_w, self._width * 0.6))

        # Pass 1: determine which rows are visible under the current expansion.
        visible: list[tuple[int, bool, float]] = []  # (entry_index, is_header, height)
        section_open = True
        for i, e in enumerate(entries):
            if bool(e.get('header')):
                collapsible = self._context_menu_is_collapsible(e)
                section_open = (not collapsible) or (i in expanded)
                visible.append((i, True, header_h))
            elif section_open:
                visible.append((i, False, row_h))

        total_h = 12.0 + sum(h for _, _, h in visible)

        x0 = max(4.0, min(self._context_menu_x, max(4.0, self._width - panel_w - 4.0)))
        y0 = max(4.0, min(self._context_menu_y, max(4.0, self._height - total_h - 4.0)))

        rows: list[dict[str, object]] = []
        ry = y0 + 6.0
        for entry_index, is_header, rh in visible:
            entry = entries[entry_index]
            collapsible = is_header and self._context_menu_is_collapsible(entry)
            rows.append({
                'index': entry_index,
                'y': ry,
                'h': rh,
                'header': is_header,
                'collapsible': collapsible,
                'expanded': entry_index in expanded,
                'selectable': (not is_header) and bool(entry.get('enabled', True)),
                'hoverable': collapsible or ((not is_header) and bool(entry.get('enabled', True))),
            })
            ry += rh

        return {'x': x0, 'y': y0, 'w': panel_w, 'h': total_h, 'rows': rows}

    def handle_context_menu_motion(self, x: float, y: float) -> None:
        """Update the hovered row (headers and selectable items) from cursor."""
        if not self._context_menu_open:
            return
        layout = self._context_menu_layout()
        x0 = float(layout['x'])
        w = float(layout['w'])
        self._context_menu_hover = -1
        if not (x0 <= x <= x0 + w):
            return
        for row in layout['rows']:  # type: ignore[union-attr]
            if row['hoverable'] and row['y'] <= y < row['y'] + row['h']:
                self._context_menu_hover = int(row['index'])
                return

    def handle_context_menu_click(self, x: float, y: float) -> int:
        """Resolve a click.

        Returns the selected item index (caller dispatches + closes), ``-1`` to
        close (click outside the panel), or ``-2`` for an in-panel no-op.  A
        click on a collapsible header toggles that section in place and returns
        ``-2`` so the menu stays open.
        """
        if not self._context_menu_open:
            return -1
        layout = self._context_menu_layout()
        x0, y0 = float(layout['x']), float(layout['y'])
        w, h = float(layout['w']), float(layout['h'])
        if not (x0 <= x <= x0 + w and y0 <= y <= y0 + h):
            return -1
        for row in layout['rows']:  # type: ignore[union-attr]
            if not (row['y'] <= y < row['y'] + row['h']):
                continue
            if row['collapsible']:
                idx = int(row['index'])
                if idx in self._context_menu_expanded:
                    self._context_menu_expanded.discard(idx)
                else:
                    self._context_menu_expanded.add(idx)
                return -2
            if row['selectable']:
                return int(row['index'])
            return -2
        return -2

    def _context_menu_hover_glow(self, x: float, y: float, w: float, h: float, t: float) -> None:
        """Draw a pulsing glossy glow highlight behind a hovered menu row."""
        gp = 0.6 + 0.4 * math.sin(t * 5.0)
        self._draw_rect(x + 3.0, y, w - 6.0, h, (0.10, 0.28, 0.60, 0.55))
        self._draw_rect(x + 3.0, y, w - 6.0, h, (0.18, 0.45, 0.90, 0.22 * gp))
        # glossy top-edge highlight + bright left accent bar
        self._draw_rect(x + 3.0, y, w - 6.0, max(1.0, h * 0.28), (0.35, 0.7, 1.0, 0.18 * gp))
        self._draw_rect(x + 3.0, y, 3.0, h, (0.45, 0.95, 1.0, 0.72 + 0.28 * gp))

    def _render_context_menu(self) -> None:
        """Draw the accordion context menu with open/close unroll + hover glow."""
        if not self.context_menu_visible or not self._context_menu_entries:
            return
        layout = self._context_menu_layout()
        x0, y0 = float(layout['x']), float(layout['y'])
        w, full_h = float(layout['w']), float(layout['h'])
        t = self._hud_t
        pulse = 0.55 + 0.45 * math.sin(t * 2.6)

        # Open/close "unroll": the panel grows/shrinks vertically (smoothstep).
        a = max(0.0, min(1.0, self._context_menu_anim))
        ease = a * a * (3.0 - 2.0 * a)
        vis_h = max(4.0, full_h * ease)
        reveal_bottom = y0 + vis_h

        self._draw_rect(x0, y0, w, vis_h, (0.04, 0.05, 0.12, 0.97))
        bw = 2.0
        c_border = (0.18 * pulse, 0.55 * pulse, 1.0 * pulse, 0.9)
        self._draw_rect(x0, y0, w, bw, c_border)
        self._draw_rect(x0, reveal_bottom - bw, w, bw, c_border)
        self._draw_rect(x0, y0, bw, vis_h, c_border)
        self._draw_rect(x0 + w - bw, y0, bw, vis_h, c_border)

        # Audio-reactive "sprite" bulbs chasing the (animating) border.
        def _fv(key: str) -> float:
            try:
                return float(self._hud_state.get(key, '0.0') or 0.0)
            except (ValueError, TypeError):
                return 0.0

        self._draw_audio_reactive_border_bulbs(
            x0, y0, w, vis_h, _fv('bass'), _fv('mid'), _fv('treble'), t,
            speed_scale=0.5, size_scale=0.5,
        )

        scale = self._CONTEXT_MENU_ROW_SCALE
        hint_scale = self._CONTEXT_MENU_HINT_SCALE
        hint_char_w = float(self._glyph_w) * self._font_scale_norm * hint_scale

        for row in layout['rows']:  # type: ignore[union-attr]
            ry = float(row['y'])
            rh = float(row['h'])
            # Only draw rows already revealed by the unroll.
            if ry + rh > reveal_bottom + 1.0:
                continue
            entry = self._context_menu_entries[int(row['index'])]
            label = str(entry.get('label', ''))
            hovered = self._context_menu_hover == int(row['index'])

            if row['header']:
                if not row['collapsible']:
                    # Separator: a faint horizontal rule.
                    self._draw_rect(x0 + 10, ry + rh * 0.5, w - 20, 1.0, (0.3, 0.4, 0.6, 0.5))
                    continue
                if hovered:
                    self._context_menu_hover_glow(x0, ry, w, rh, t)
                # ASCII disclosure marker ('v' open / '>' collapsed) — the font
                # atlas is ASCII-only, so no unicode arrows.
                marker = 'v' if row['expanded'] else '>'
                hcol = (0.9, 0.98, 1.0, 1.0) if hovered else (0.55, 0.75, 1.0, 0.9)
                self._draw_text(f'{marker} {label.upper()}', x0 + 12, ry + 5, scale=hint_scale, color=hcol)
                continue

            selectable = bool(row['selectable'])
            if hovered and selectable:
                self._context_menu_hover_glow(x0, ry, w, rh, t)
            if hovered and selectable:
                tcol = (1.0, 0.97, 0.55, 1.0)
            elif selectable:
                tcol = (0.78, 0.86, 1.0, 0.92)
            else:
                tcol = (0.5, 0.5, 0.6, 0.55)
            self._draw_text(label, x0 + 30, ry + 6, scale=scale, color=tcol)
            hint = str(entry.get('hotkey', '') or '')
            if hint:
                hint_w = len(hint) * hint_char_w
                self._draw_text(
                    hint, x0 + w - 14 - hint_w, ry + 8, scale=hint_scale,
                    color=(0.5, 0.6, 0.8, 0.7),
                )

    # ------------------------------------------------------------------
    # Configuration editor (tabbed modal)
    # ------------------------------------------------------------------

    @property
    def config_editor_open(self) -> bool:
        """True while the configuration editor is open (interactive)."""
        return self._show_config_editor

    @property
    def config_editor_visible(self) -> bool:
        """True while it should render (open or animating closed)."""
        return self._show_config_editor or self._config_editor_fading

    @property
    def config_editor_tab(self) -> int:
        """Index of the active tab."""
        return self._config_editor_tab

    @property
    def config_editor_tab_name(self) -> str:
        """Name of the active tab."""
        tabs = self._config_editor_tabs
        return tabs[self._config_editor_tab] if tabs else ''

    def toggle_config_editor(self) -> bool:
        """Open/close the configuration editor. Returns the new open state."""
        if self._show_config_editor:
            self.close_config_editor()
            return False
        self._show_config_editor = True
        self._config_editor_anim = 0.0
        self._config_editor_fading = False
        self._config_editor_tab_hover = -1
        return True

    def close_config_editor(self) -> None:
        """Close the editor (animates closed, then stops rendering)."""
        if self._show_config_editor:
            self._config_editor_fading = True
        self._show_config_editor = False
        self._config_editor_tab_hover = -1

    def set_config_editor_tabs(self, names: list[str]) -> None:
        """Set the tab list (App-driven so tabs like 'Auto VJ' can be conditional)."""
        names = [str(n) for n in names] or ['Effects']
        if names != self._config_editor_tabs:
            self._config_editor_tabs = names
        if self._config_editor_tab >= len(self._config_editor_tabs):
            self._config_editor_tab = len(self._config_editor_tabs) - 1

    def set_config_editor_tab(self, index: int) -> None:
        """Select a tab by index (clamped)."""
        n = len(self._config_editor_tabs)
        if n:
            self._config_editor_tab = max(0, min(int(index), n - 1))

    def move_config_editor_tab(self, delta: int) -> None:
        """Move the active tab by delta (wraps)."""
        n = len(self._config_editor_tabs)
        if n:
            self._config_editor_tab = (self._config_editor_tab + int(delta)) % n

    def tick_config_editor(self, dt: float) -> None:
        """Advance the open/close animation toward its target."""
        if not (self._show_config_editor or self._config_editor_fading):
            return
        target = 1.0 if self._show_config_editor else 0.0
        rate = float(dt) / 0.16
        if self._config_editor_anim < target:
            self._config_editor_anim = min(target, self._config_editor_anim + rate)
        elif self._config_editor_anim > target:
            self._config_editor_anim = max(target, self._config_editor_anim - rate)
        if self._config_editor_fading and self._config_editor_anim <= 0.001:
            self._config_editor_fading = False

    def _config_editor_tab_boxes(
        self, panel_rect: tuple[float, float, float, float]
    ) -> list[tuple[int, float, float, float, float]]:
        """Return clickable tab boxes ``(index, x, y, w, h)`` for the tab bar."""
        px, py, _pw, _ph = panel_rect
        scale = 2.4
        char_w = float(self._glyph_w) * self._font_scale_norm * scale
        tab_h = 44.0
        tab_y = py + 64.0
        gap = 10.0
        boxes: list[tuple[int, float, float, float, float]] = []
        x = px + 22.0
        for i, name in enumerate(self._config_editor_tabs):
            w = len(name) * char_w + 34.0
            boxes.append((i, x, tab_y, w, tab_h))
            x += w + gap
        return boxes

    def handle_config_editor_motion(self, x: float, y: float) -> None:
        """Update the hovered tab from cursor position."""
        self._config_editor_tab_hover = -1
        if not self._show_config_editor or self._config_editor_panel_rect is None:
            return
        self._feed_modal_tooltips(
            'config_editor', x, y, self._config_editor_tooltip_regions(),
        )
        for i, bx, by, bw, bh in self._config_editor_tab_boxes(self._config_editor_panel_rect):
            if bx <= x <= bx + bw and by <= y <= by + bh:
                self._config_editor_tab_hover = i
                return

    def _config_editor_tooltip_regions(self) -> list[TooltipRegion]:
        """Build tooltip regions for the config editor's tab bar."""
        if self._config_editor_panel_rect is None:
            return []
        regions: list[TooltipRegion] = []
        for i, bx, by, bw, bh in self._config_editor_tab_boxes(self._config_editor_panel_rect):
            if 0 <= i < len(self._config_editor_tabs):
                regions.append(TooltipRegion(
                    rect=(int(bx), int(by), int(bw), int(bh)),
                    text=f'Edit {self._config_editor_tabs[i]} settings',
                ))
        return regions

    def handle_config_editor_click(self, x: float, y: float) -> bool:
        """Handle a click; switch tab or select an effect/parameter row.

        Returns True if the click was consumed.
        """
        if not self._show_config_editor or self._config_editor_panel_rect is None:
            return False
        if self._tooltip_tracker is not None:
            self._tooltip_tracker.notify_click()
        for i, bx, by, bw, bh in self._config_editor_tab_boxes(self._config_editor_panel_rect):
            if bx <= x <= bx + bw and by <= y <= by + bh:
                self.set_config_editor_tab(i)
                return True
        # Footer buttons (save/load/delete/revert).
        for rx, ry, rw, rh, action in self._ce_footer_button_rects:
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                self._ce_pending_action = action
                return True
        # Profile chips — select one (populates the name field too).
        for rx, ry, rw, rh, idx in self._ce_profile_chip_rects:
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                self._ce_profile_idx = idx
                if 0 <= idx < len(self._ce_profiles):
                    self._ce_name_text = self._ce_profiles[idx]
                return True
        # Effect / parameter rows (Effects tab).
        for rx, ry, rw, rh, idx in self._ce_effect_row_rects:
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                self._ce_effect_idx = idx
                self._ce_focus = 0
                return True
        for rx, ry, rw, rh, idx in self._ce_param_row_rects:
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                self._ce_param_idx = idx
                self._ce_focus = 1
                return True
        return False

    # -- Effects tab data + selection (App pushes data; Overlays owns cursor) --

    def set_config_editor_effects(self, effects: list[dict[str, str]]) -> None:
        """Set the effect list ``[{'class_name', 'display_name'}, ...]``."""
        self._ce_effects = list(effects)
        if self._ce_effects:
            self._ce_effect_idx = max(0, min(self._ce_effect_idx, len(self._ce_effects) - 1))
        else:
            self._ce_effect_idx = 0

    def set_config_editor_effect_index(self, index: int) -> None:
        """Select an effect by index (clamped)."""
        if self._ce_effects:
            self._ce_effect_idx = max(0, min(int(index), len(self._ce_effects) - 1))

    def set_config_editor_params(self, params: list[dict[str, float | str]]) -> None:
        """Set the selected effect's parameter rows ``[{'name','value','min','max'}]``."""
        self._ce_params = list(params)
        if self._ce_params:
            self._ce_param_idx = max(0, min(self._ce_param_idx, len(self._ce_params) - 1))
        else:
            self._ce_param_idx = 0

    def config_editor_selected_class(self) -> str:
        """Return the class name of the selected effect, or ''."""
        if 0 <= self._ce_effect_idx < len(self._ce_effects):
            return str(self._ce_effects[self._ce_effect_idx].get('class_name', ''))
        return ''

    def config_editor_param_index(self) -> int:
        """Return the selected parameter row index."""
        return self._ce_param_idx

    def config_editor_selected_param(self) -> str | None:
        """Return the selected parameter name, or None."""
        if 0 <= self._ce_param_idx < len(self._ce_params):
            return str(self._ce_params[self._ce_param_idx].get('name', '')) or None
        return None

    @property
    def config_editor_focus(self) -> int:
        """0 = effect list focused, 1 = parameters focused."""
        return self._ce_focus

    def toggle_config_editor_focus(self) -> None:
        """Switch focus between the effect list and the parameter list."""
        self._ce_focus ^= 1

    def move_config_editor_row(self, delta: int) -> None:
        """Move the cursor within the focused pane (wraps).

        On non-Effects tabs there is no effect list, so movement always targets
        the settings rows.
        """
        effects_tab = self.config_editor_tab_name == 'Effects'
        if effects_tab and self._ce_focus == 0:
            n = len(self._ce_effects)
            if n:
                self._ce_effect_idx = (self._ce_effect_idx + int(delta)) % n
        else:
            n = len(self._ce_params)
            if n:
                self._ce_param_idx = (self._ce_param_idx + int(delta)) % n

    # -- Profile footer (save/load/delete/revert + name entry) ----------------

    def set_config_editor_profiles(self, names: list[str]) -> None:
        """Set the saved-profile name list."""
        self._ce_profiles = list(names)
        if self._ce_profile_idx >= len(self._ce_profiles):
            self._ce_profile_idx = -1

    def set_config_editor_dirty(self, dirty: bool) -> None:
        """Mark whether there are unsaved parameter overrides."""
        self._ce_dirty = bool(dirty)

    @property
    def config_editor_name_mode(self) -> bool:
        """True while the profile-name entry field is capturing typing."""
        return self._ce_name_mode

    def set_config_editor_name_mode(self, active: bool) -> None:
        """Enter/leave profile-name entry mode."""
        self._ce_name_mode = bool(active)

    @property
    def config_editor_name_text(self) -> str:
        """Current profile-name entry buffer."""
        return self._ce_name_text

    def set_config_editor_name_text(self, text: str) -> None:
        """Replace the profile-name entry buffer."""
        self._ce_name_text = str(text)

    def config_editor_selected_profile(self) -> str:
        """Return the profile to load/delete: the selected chip, else the name text."""
        if 0 <= self._ce_profile_idx < len(self._ce_profiles):
            return self._ce_profiles[self._ce_profile_idx]
        return self._ce_name_text.strip()

    def take_config_editor_action(self) -> str | None:
        """Pop the pending footer action ('save'/'load'/'delete'/'revert')."""
        action = self._ce_pending_action
        self._ce_pending_action = None
        return action

    @property
    def config_editor_capture_mode(self) -> bool:
        """True while waiting for the next keypress to rebind an action."""
        return self._ce_capture_mode

    @property
    def config_editor_capture_action(self) -> str:
        """The action name currently being rebound, or ''."""
        return self._ce_capture_action

    def set_config_editor_capture(self, active: bool, action: str = '') -> None:
        """Enter/leave "press new key" capture mode for a hotkey-tab row."""
        self._ce_capture_mode = bool(active)
        self._ce_capture_action = str(action) if active else ''

    def config_editor_selected_row(self) -> dict[str, object] | None:
        """Return the currently-selected row dict on the active tab, if any."""
        if 0 <= self._ce_param_idx < len(self._ce_params):
            return self._ce_params[self._ce_param_idx]
        return None

    def _render_config_editor(self) -> None:
        """Draw the tabbed configuration editor (shell + tab bar + placeholder body)."""
        if not self.config_editor_visible:
            return
        px, py, pw, ph, _W, _H = self._begin_panel(
            0.84, 1400.0, 0.86, 900.0, underlay_alpha=0.6, underlay_pad=12.0
        )
        self._config_editor_panel_rect = (px, py, pw, ph)
        t = self._hud_t
        pulse = 0.55 + 0.45 * math.sin(t * 2.6)

        # Open/close animation: expand vertically from the centre.
        a = max(0.0, min(1.0, self._config_editor_anim))
        ease = a * a * (3.0 - 2.0 * a)
        vis_h = max(6.0, ph * ease)
        vy = py + (ph - vis_h) * 0.5

        self._draw_rect(px, vy, pw, vis_h, (0.03, 0.05, 0.11, 0.97))
        bw = 2.0
        c_border = (0.18 * pulse, 0.55 * pulse, 1.0 * pulse, 0.9)
        self._draw_rect(px, vy, pw, bw, c_border)
        self._draw_rect(px, vy + vis_h - bw, pw, bw, c_border)
        self._draw_rect(px, vy, bw, vis_h, c_border)
        self._draw_rect(px + pw - bw, vy, bw, vis_h, c_border)

        def _fv(key: str) -> float:
            try:
                return float(self._hud_state.get(key, '0.0') or 0.0)
            except (ValueError, TypeError):
                return 0.0

        self._draw_audio_reactive_border_bulbs(
            px, vy, pw, vis_h, _fv('bass'), _fv('mid'), _fv('treble'), t,
            speed_scale=0.5, size_scale=0.6,
        )
        # HUD-style frame decorators (corner accents + crosshair arms + ticks).
        self._draw_modal_frame_decor(px, vy, pw, vis_h, pulse)

        # Content appears once the panel is mostly open.
        if ease < 0.82:
            return

        self._draw_text('CONFIGURATION', px + 22, py + 16, scale=3.6,
                        color=(0.4 + 0.2 * pulse, 0.8, 1.0, 1.0))

        # Tab bar.
        for i, bx, by, bw2, bh in self._config_editor_tab_boxes((px, py, pw, ph)):
            name = self._config_editor_tabs[i]
            active = i == self._config_editor_tab
            hovered = i == self._config_editor_tab_hover
            if active:
                self._draw_rect(bx, by, bw2, bh, (0.12, 0.30, 0.62, 0.9))
                self._draw_rect(bx, by + bh - 3.0, bw2, 3.0, (0.4, 0.95, 1.0, 0.95))
            elif hovered:
                self._context_menu_hover_glow(bx, by, bw2, bh, t)
            else:
                self._draw_rect(bx, by, bw2, bh, (0.06, 0.10, 0.22, 0.7))
            tcol = (1.0, 0.97, 0.6, 1.0) if active else (0.75, 0.85, 1.0, 0.9)
            self._draw_text(name, bx + 17, by + 11, scale=2.4, color=tcol)

        # Two-pane body (list | detail).
        body_y = py + 120.0
        footer_h = 128.0
        body_h = ph - (body_y - py) - footer_h
        left_w = pw * 0.32
        left_x = px + 22.0
        right_x = px + 22.0 + left_w
        right_w = pw - left_w - 44.0
        self._draw_rect(left_x, body_y, left_w - 12, body_h, (0.05, 0.08, 0.16, 0.85))
        self._draw_rect(right_x, body_y, right_w, body_h, (0.05, 0.08, 0.16, 0.85))

        tab_name = self.config_editor_tab_name
        if tab_name == 'Effects':
            self._render_config_editor_effects(
                left_x, right_x, body_y, left_w, right_w, body_h
            )
        else:
            # Audio / Visuals: global settings as parameter rows (no effect list).
            self._ce_effect_row_rects = []
            self._draw_text(tab_name.upper(), left_x + 14, body_y + 12, scale=1.8,
                            color=(0.55, 0.75, 1.0, 0.85))
            self._draw_text('Global', left_x + 16, body_y + 44, scale=1.9,
                            color=(0.75, 0.83, 0.98, 0.9))
            self._render_config_editor_param_rows(
                right_x, body_y, right_w, body_h, f'{tab_name.upper()} SETTINGS'
            )

        self._render_config_editor_footer(px, py, pw, ph, t)

    def _render_config_editor_footer(
        self, px: float, py: float, pw: float, ph: float, t: float
    ) -> None:
        """Render the profile footer: chips + name field + Save/Load/Delete/Revert."""
        self._ce_footer_button_rects = []
        self._ce_profile_chip_rects = []
        scale = 2.0
        char_w = float(self._glyph_w) * self._font_scale_norm * scale
        footer_h = 128.0
        fy = py + ph - footer_h + 10.0

        # Saved-profile chips (single row; overflow is clipped for v1).
        self._draw_text('PROFILES', px + 22, fy, scale=1.7, color=(0.55, 0.75, 1.0, 0.85))
        chip_y = fy + 24.0
        chip_h = 28.0
        cx = px + 22.0
        for i, name in enumerate(self._ce_profiles):
            w = len(name) * char_w + 20.0
            if cx + w > px + pw - 22.0:
                break
            selected = i == self._ce_profile_idx
            self._draw_rect(cx, chip_y, w, chip_h,
                            (0.12, 0.30, 0.62, 0.9) if selected else (0.06, 0.10, 0.22, 0.75))
            self._draw_text(name, cx + 10, chip_y + 6, scale=1.7,
                            color=(1.0, 0.95, 0.55, 1.0) if selected else (0.75, 0.85, 1.0, 0.9))
            self._ce_profile_chip_rects.append((cx, chip_y, w, chip_h, i))
            cx += w + 8.0
        if not self._ce_profiles:
            self._draw_text('(none saved yet)', px + 140, fy, scale=1.7,
                            color=(0.55, 0.6, 0.7, 0.7))

        # Name field + dirty indicator.
        name_y = chip_y + chip_h + 14.0
        caret = '_' if (self._ce_name_mode and int(t * 2.0) % 2 == 0) else ''
        field_col = (0.10, 0.18, 0.34, 0.9) if self._ce_name_mode else (0.06, 0.10, 0.20, 0.8)
        self._draw_rect(px + 22, name_y, 360.0, 32.0, field_col)
        self._draw_text(f'NAME: {self._ce_name_text}{caret}', px + 30, name_y + 7,
                        scale=2.0, color=(0.9, 0.95, 1.0, 0.95))
        if self._ce_dirty:
            self._draw_rect(px + 392, name_y + 9, 14.0, 14.0, (1.0, 0.58, 0.12, 0.9))
            self._draw_text('unsaved', px + 414, name_y + 7, scale=1.7,
                            color=(1.0, 0.7, 0.3, 0.85))

        # Buttons (right-to-left so Save is rightmost).
        bx = px + pw - 22.0
        for label, action in (('Revert', 'revert'), ('Delete', 'delete'),
                              ('Load', 'load'), ('Save', 'save')):
            w = len(label) * char_w + 26.0
            bxx = bx - w
            self._draw_rect(bxx, name_y, w, 32.0, (0.10, 0.24, 0.50, 0.85))
            self._draw_rect(bxx, name_y + 29.0, w, 2.0, (0.4, 0.9, 1.0, 0.8))
            self._draw_text(label, bxx + 13, name_y + 7, scale=2.0, color=(0.9, 0.96, 1.0, 0.95))
            self._ce_footer_button_rects.append((bxx, name_y, w, 32.0, action))
            bx = bxx - 10.0

    def _render_config_editor_effects(
        self, left_x: float, right_x: float, body_y: float,
        left_w: float, right_w: float, body_h: float,
    ) -> None:
        """Render the Effects tab: effect list (left) + parameter rows (right)."""
        self._ce_effect_row_rects = []
        self._ce_param_row_rects = []

        # Left pane — effect list.
        self._draw_text('EFFECTS', left_x + 14, body_y + 12, scale=1.8,
                        color=(0.55, 0.75, 1.0, 0.85))
        list_top = body_y + 42.0
        row_h = 30.0
        max_rows = max(1, int((body_h - 52.0) / row_h))
        n_eff = len(self._ce_effects)
        start = max(0, min(self._ce_effect_idx - max_rows // 2, max(0, n_eff - max_rows)))
        for vis, i in enumerate(range(start, min(n_eff, start + max_rows))):
            ry = list_top + vis * row_h
            eff = self._ce_effects[i]
            name = str(eff.get('display_name') or eff.get('class_name') or '')
            selected = i == self._ce_effect_idx
            if selected:
                col = (0.10, 0.25, 0.55, 0.9) if self._ce_focus == 0 else (0.08, 0.16, 0.34, 0.8)
                self._draw_rect(left_x + 6, ry - 2, left_w - 24, row_h - 2, col)
            tcol = (1.0, 0.95, 0.5, 1.0) if selected else (0.75, 0.83, 0.98, 0.9)
            self._draw_text(name[:24], left_x + 16, ry + 4, scale=1.9, color=tcol)
            self._ce_effect_row_rects.append((left_x + 6, ry - 2, left_w - 24, row_h - 2, i))

        # Right pane — parameters of the selected effect.
        cls = self.config_editor_selected_class()
        self._render_config_editor_param_rows(
            right_x, body_y, right_w, body_h, f'{cls} PARAMETERS'
        )
        # Make the randomization behaviour obvious to the operator.
        self._draw_text('Adjusting a value pins it (skips its per-run randomization).',
                        right_x + 16, body_y + body_h - 44.0, scale=1.7,
                        color=(1.0, 0.72, 0.3, 0.85))

    def _render_config_editor_param_rows(
        self, right_x: float, body_y: float, right_w: float, body_h: float, title: str,
    ) -> None:
        """Render the ``_ce_params`` rows (name + value bar + value) in a pane.

        Shared by the Effects tab (per-effect params) and the Audio/Visuals tabs
        (global settings).
        """
        self._ce_param_row_rects = []
        self._draw_text(title[:40], right_x + 16, body_y + 12, scale=1.9,
                        color=(0.6, 0.8, 1.0, 0.9))
        if not self._ce_params:
            self._draw_text('No tunable settings.', right_x + 18, body_y + 52, scale=2.0,
                            color=(0.6, 0.65, 0.75, 0.8))
            return
        p_top = body_y + 48.0
        prow_h = 40.0
        max_prows = max(1, int((body_h - 64.0) / prow_h))
        n_p = len(self._ce_params)
        pstart = max(0, min(self._ce_param_idx - max_prows // 2, max(0, n_p - max_prows)))
        any_adjustable = False
        any_bindable = False
        for vis, i in enumerate(range(pstart, min(n_p, pstart + max_prows))):
            ry = p_top + vis * prow_h
            p = self._ce_params[i]
            name = str(p.get('name', ''))
            if p.get('kind') == 'info':
                # Read-only diagnostic/status row: name + right-aligned value.
                self._draw_text(name[:26], right_x + 16, ry + 2, scale=1.9,
                                color=(0.72, 0.8, 0.95, 0.9))
                info = str(p.get('info', ''))
                iw = len(info) * float(self._glyph_w) * self._font_scale_norm * 1.9
                self._draw_text(info[:28], right_x + right_w - 18 - iw, ry + 2, scale=1.9,
                                color=(0.85, 0.95, 0.7, 0.95))
                continue
            if p.get('kind') == 'bind':
                any_bindable = True
                selected = i == self._ce_param_idx
                capturing = selected and self._ce_capture_mode
                if selected:
                    self._context_menu_hover_glow(right_x + 6, ry - 2, right_w - 12, prow_h - 4, self._hud_t)
                tcol = (1.0, 0.95, 0.5, 1.0) if selected else (0.78, 0.86, 1.0, 0.92)
                self._draw_text(name[:30], right_x + 16, ry + 2, scale=1.9, color=tcol)
                if capturing:
                    pulse = 0.5 + 0.5 * math.sin(self._hud_t * 6.0)
                    chord_text = 'Press a key...'
                    ccol = (1.0, 0.55 + 0.35 * pulse, 0.2, 1.0)
                else:
                    chord_text = str(p.get('chord', '-'))
                    is_override = bool(p.get('is_override', False))
                    ccol = (0.4, 0.95, 1.0, 0.95) if is_override else (0.75, 0.80, 0.88, 0.85)
                cw = len(chord_text) * float(self._glyph_w) * self._font_scale_norm * 1.9
                self._draw_text(chord_text, right_x + right_w - 18 - cw, ry + 2, scale=1.9, color=ccol)
                self._ce_param_row_rects.append((right_x + 6, ry - 2, right_w - 12, prow_h - 4, i))
                continue
            any_adjustable = True
            val = float(p.get('value', 0.0))
            pmin = float(p.get('min', 0.0))
            pmax = float(p.get('max', 1.0))
            selected = i == self._ce_param_idx
            if selected:
                col = (0.10, 0.25, 0.55, 0.9) if self._ce_focus == 1 else (0.08, 0.16, 0.34, 0.8)
                self._draw_rect(right_x + 6, ry - 2, right_w - 12, prow_h - 4, col)
            tcol = (1.0, 0.95, 0.5, 1.0) if selected else (0.78, 0.86, 1.0, 0.92)
            self._draw_text(name[:22], right_x + 16, ry + 2, scale=1.9, color=tcol)
            # Value bar.
            bar_x = right_x + 16.0
            bar_w = right_w - 150.0
            bar_y = ry + 24.0
            self._draw_rect(bar_x, bar_y, bar_w, 8.0, (0.15, 0.2, 0.3, 0.8))
            frac = 0.0 if pmax <= pmin else max(0.0, min(1.0, (val - pmin) / (pmax - pmin)))
            self._draw_rect(bar_x, bar_y, bar_w * frac, 8.0, (0.3, 0.85, 1.0, 0.9))
            self._draw_text(f'{val:.3f}', right_x + right_w - 118, ry + 2, scale=1.9,
                            color=(0.85, 0.95, 0.7, 0.95))
            self._ce_param_row_rects.append((right_x + 6, ry - 2, right_w - 12, prow_h - 4, i))

        if any_adjustable:
            self._draw_text('Up/Down: select   [ / ]: adjust',
                            right_x + 16, body_y + body_h - 22.0, scale=1.7,
                            color=(0.5, 0.6, 0.72, 0.75))
        elif any_bindable:
            self._draw_text('Up/Down: select   Enter: rebind   Backspace: reset to default',
                            right_x + 16, body_y + body_h - 22.0, scale=1.7,
                            color=(0.5, 0.6, 0.72, 0.75))

    # ------------------------------------------------------------------
    # First-run tour modal (v1 slide dialog)
    # See docs/planning/first-run-tour-plan-2026-07-18.md. Content and
    # startup policy live in unicornviz/tour.py; this section owns only
    # rendering and pointer input. Keyboard input is dispatched by
    # HotkeyHandler (the in-modal branch), mirroring the other modals.
    # ------------------------------------------------------------------

    @property
    def tour_visible(self) -> bool:
        """Return whether the tour dialog is open."""
        return self._show_tour

    def set_tour_slides(self, slides) -> None:
        """Install the slide deck (core + later drop-in contributions)."""
        self._tour_slides = tuple(slides or ())
        self._tour_slide = min(self._tour_slide, max(0, len(self._tour_slides) - 1))

    def open_tour(self, slide: int = 0, show_on_startup: bool = True) -> None:
        """Open the dialog at ``slide`` with the checkbox preset."""
        if not self._tour_slides:
            return
        self._tour_slide = max(0, min(len(self._tour_slides) - 1, int(slide)))
        self._tour_show_on_startup = bool(show_on_startup)
        self._tour_hover = ''
        self._show_tour = True

    def close_tour(self) -> tuple[int, bool]:
        """Close the dialog; return ``(slide, show_on_startup)`` to persist."""
        self._show_tour = False
        return self._tour_slide, self._tour_show_on_startup

    def tour_state(self) -> tuple[int, bool]:
        """Return ``(slide, show_on_startup)`` without closing."""
        return self._tour_slide, self._tour_show_on_startup

    def tour_next(self) -> bool:
        """Advance one slide; return True when DONE (past the last slide)."""
        if self._tour_slide >= len(self._tour_slides) - 1:
            self._tour_slide = 0  # completion resets the resume position
            return True
        self._tour_slide += 1
        return False

    def tour_prev(self) -> None:
        """Go back one slide (clamped at the first)."""
        self._tour_slide = max(0, self._tour_slide - 1)

    def tour_toggle_startup(self) -> bool:
        """Flip the show-on-startup checkbox; return the new state."""
        self._tour_show_on_startup = not self._tour_show_on_startup
        return self._tour_show_on_startup

    def _tour_layout(self) -> dict[str, tuple[float, float, float, float]]:
        """Pure geometry for the tour panel and its controls.

        Split from rendering so input handling and tests share exact rects
        without a GL context (the config-editor tab-box pattern). Keys:
        ``panel``, ``prev``, ``next``, ``close``, ``startup`` (checkbox +
        label hit area).
        """
        pw = min(880.0, self._width * 0.9)
        ph = min(560.0, self._height * 0.9)
        px = (self._width - pw) * 0.5
        py = (self._height - ph) * 0.5
        btn_w, btn_h = 118.0, 42.0
        gap = 12.0
        by = py + ph - btn_h - 18.0
        close_x = px + pw - btn_w - 18.0
        next_x = close_x - btn_w - gap
        prev_x = next_x - btn_w - gap
        box = 20.0
        sx = px + 18.0
        sy = by + (btn_h - box) * 0.5
        label_w = len('Show on startup') * 8.0 * 1.48 + 12.0
        return {
            'panel': (px, py, pw, ph),
            'prev': (prev_x, by, btn_w, btn_h),
            'next': (next_x, by, btn_w, btn_h),
            'close': (close_x, by, btn_w, btn_h),
            'startup': (sx, sy, box + label_w, box),
        }

    def handle_tour_motion(self, x: float, y: float) -> bool:
        """Update hover state; return True while the dialog is open."""
        if not self._show_tour:
            return False
        self._tour_hover = ''
        layout = self._tour_layout()
        for kind in ('prev', 'next', 'close', 'startup'):
            bx, by, bw, bh = layout[kind]
            if bx <= x <= bx + bw and by <= y <= by + bh:
                self._tour_hover = kind
                break
        return True

    def handle_tour_click(self, x: float, y: float) -> str:
        """Return the control under a click: ``prev|next|close|startup|''``.

        The caller (App) applies the action so persistence stays app-side.
        """
        if not self._show_tour:
            return ''
        layout = self._tour_layout()
        for kind in ('prev', 'next', 'close', 'startup'):
            bx, by, bw, bh = layout[kind]
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return kind
        return ''

    def _render_tour(self) -> None:
        """Draw the slide dialog: fixed-size centered panel, identical every
        slide (footer: startup checkbox left, PREV / NEXT / CLOSE right)."""
        if not self._tour_slides:
            return
        layout = self._tour_layout()
        px, py, pw, ph = layout['panel']
        self._draw_modal_underlay(px, py, pw, ph, 0.55, pad=60.0)
        self._draw_rect(px, py, pw, ph, (0.03, 0.05, 0.09, 0.96))
        self._draw_rect(px, py, pw, 3.0, (0.10, 0.94, 1.0, 0.85))
        self._draw_rect(px, py + ph - 3.0, pw, 3.0, (0.78, 0.38, 1.0, 0.75))
        self._draw_modal_frame_decor(px, py, pw, ph, 0.5)

        idx = self._tour_slide
        slide = self._tour_slides[idx]
        total = len(self._tour_slides)
        pad = 34.0

        eyebrow = f'{slide.section}  ·  {idx + 1} / {total}'
        self._draw_text(eyebrow, px + pad, py + 26.0, scale=1.48,
                        color=(0.10, 0.94, 1.0, 0.85))
        self._draw_text(slide.title, px + pad, py + 56.0, scale=3.0,
                        color=(0.98, 0.98, 1.0, 0.98))

        body = slide.body
        if callable(getattr(self, 'lookup_help_key', None)):
            body = _tour_resolve(body, self.lookup_help_key)
        body_scale = 1.72
        char_w = 8.0 * body_scale
        wrap_w = int(pw - pad * 2.0)
        lines = wrap_tooltip_text(body, None, wrap_w, lambda s: len(s) * char_w)
        line_h = 8.0 * body_scale + 9.0
        ty = py + 116.0
        for line in lines:
            if ty + line_h > py + ph - 84.0:
                break  # content test keeps decks inside the panel; belt+braces
            self._draw_text(line, px + pad, ty, scale=body_scale,
                            color=(0.88, 0.92, 0.97, 0.96))
            ty += line_h

        hint = 'Arrows: navigate    Enter: next    S: startup toggle    Esc: close'
        self._draw_text(hint, px + pad, py + ph - 76.0, scale=1.24,
                        color=(0.55, 0.62, 0.72, 0.85))

        # Footer controls.
        for kind, label in (('prev', 'PREV'),
                            ('next', 'DONE' if idx >= total - 1 else 'NEXT'),
                            ('close', 'CLOSE')):
            bx, by, bw, bh = layout[kind]
            hovered = self._tour_hover == kind
            disabled = kind == 'prev' and idx == 0
            base = (0.10, 0.94, 1.0) if kind != 'close' else (0.78, 0.38, 1.0)
            alpha = 0.30 if disabled else (0.85 if hovered else 0.55)
            self._draw_rect(bx, by, bw, bh, (base[0] * 0.2, base[1] * 0.2, base[2] * 0.2, 0.85))
            self._draw_rect(bx, by, bw, 2.0, (base[0], base[1], base[2], alpha))
            self._draw_rect(bx, by + bh - 2.0, bw, 2.0, (base[0], base[1], base[2], alpha))
            tw = len(label) * 8.0 * 1.72
            self._draw_text(label, bx + (bw - tw) * 0.5, by + 13.0, scale=1.72,
                            color=(0.95, 0.97, 1.0, 0.45 if disabled else 0.96))

        sx, sy, sw, sh = layout['startup']
        box = sh
        checked = self._tour_show_on_startup
        hover = self._tour_hover == 'startup'
        self._draw_rect(sx, sy, box, box, (0.10, 0.94, 1.0, 0.85 if hover else 0.55))
        self._draw_rect(sx + 2, sy + 2, box - 4, box - 4, (0.03, 0.05, 0.09, 1.0))
        if checked:
            self._draw_rect(sx + 5, sy + 5, box - 10, box - 10, (0.10, 0.94, 1.0, 0.95))
        self._draw_text('Show on startup', sx + box + 10.0, sy + 3.0, scale=1.48,
                        color=(0.88, 0.92, 0.97, 0.92))

    def render(self, dt: float, include_recording_indicator: bool = True) -> None:
        """Call each frame after the main effect renders."""
        self._hud_t += dt
        if self._show_name and self._hud_auto_hide:
            self._hud_timer -= dt
            if self._hud_timer <= 0.0:
                self._show_name = False
                self._hud_timer = 0.0
        if self._show_help:
            self._help_timer -= dt
            if self._help_timer <= 0.0:
                self._show_help = False
                self._help_timer = 0.0
            self._help_pulse_t += dt

        if self._flash_timer > 0.0:
            self._flash_timer -= dt
            alpha = min(1.0, self._flash_timer * 2.0)
            self._draw_text(
                self._flash_text,
                20, self._height - 80,
                scale=4.0,
                color=(1.0, 0.8, 0.0, alpha),
            )

        route_modals_elsewhere = False
        gate = self._modal_gate
        if callable(gate):
            try:
                route_modals_elsewhere = bool(gate())
            except Exception:
                route_modals_elsewhere = False

        if self._show_name and self._name_text and not route_modals_elsewhere:
            self._render_hud()

        if self._banner_timer > 0.0:
            self._banner_timer = max(0.0, self._banner_timer - dt)
        if self._banner_enabled and self._banner_timer > 0.0 and not route_modals_elsewhere:
            self._render_banner()

        if include_recording_indicator:
            self._render_recording_indicator()

        if self._cta.is_active:
            self._cta.render(dt, self._ctx, self._draw_rect, self._width, self._height)

        if self._show_help and not route_modals_elsewhere:
            self._render_help()

        active_modal_type = ''
        if self._show_presets:
            active_modal_type = 'presets'
        elif self._show_effects_browser:
            active_modal_type = 'effects_browser'
        elif self._show_projectm_manager:
            active_modal_type = 'projectm_manager'
        elif self._show_system_monitor_modal:
            active_modal_type = 'system_monitor'
        elif self._show_controller_help_modal:
            active_modal_type = 'controller_help'
        elif self._show_webcam_editor_modal:
            active_modal_type = 'webcam_editor'
        elif self._show_audio:
            active_modal_type = 'audio_selector'
        elif self._show_midi:
            active_modal_type = 'midi_selector'
        elif self._show_help:
            active_modal_type = 'help_overlay'
        elif self._show_name:
            active_modal_type = 'hud_overlay'

        route_state = (route_modals_elsewhere, active_modal_type)
        if route_state != self._modal_route_debug_last:
            if active_modal_type:
                destination = 'control_room' if route_modals_elsewhere else 'audience_overlay'
                log.debug(
                    'Overlay modal route: type=%s destination=%s gate=%s',
                    active_modal_type,
                    destination,
                    route_modals_elsewhere,
                )
            self._modal_route_debug_last = route_state

        if self._show_presets and not route_modals_elsewhere:
            self._render_presets()

        if self._show_effects_browser and not route_modals_elsewhere:
            self._render_effects_browser()

        if self._show_projectm_manager and not route_modals_elsewhere:
            self._render_projectm_manager()

        if self._show_system_monitor_modal and not route_modals_elsewhere:
            self._render_system_monitor_modal()

        if self._show_controller_help_modal and not route_modals_elsewhere:
            self._render_controller_help_modal()

        if self._show_webcam_editor_modal and not route_modals_elsewhere:
            self._render_webcam_editor_modal()

        if self._show_audio and not route_modals_elsewhere:
            self._render_audio_selector()

        if self._show_midi and not route_modals_elsewhere:
            self._render_midi_selector()

        # Configuration editor (full modal, under the context menu).
        self.tick_config_editor(dt)
        if self.config_editor_visible and not route_modals_elsewhere:
            self._render_config_editor()

        # First-run tour dialog — above the other modals, below the context
        # menu. Deliberately NOT gated on route_modals_elsewhere in P1: the
        # tour always renders on the main window (CR mirroring is P3).
        if self._show_tour:
            self._render_tour()

        # Context menu floats above everything else (with open/close unroll).
        self.tick_context_menu(dt)
        if self.context_menu_visible and not route_modals_elsewhere:
            self._render_context_menu()

        # Hover tooltip for the modal surfaces, above every modal layer.
        self._render_active_tooltip(route_modals_elsewhere)

    # ------------------------------------------------------------------
    # Audio source selector
    # ------------------------------------------------------------------

    def set_audio_sources(
        self,
        sources: list[str],
        current_index: int,
        viable_flags: list[bool] | None = None,
    ) -> None:
        """Populate the audio selector source list before opening the overlay."""
        self._audio_sources = list(sources)
        if viable_flags is None or len(viable_flags) != len(self._audio_sources):
            self._audio_viable_flags = [True] * len(self._audio_sources)
        else:
            self._audio_viable_flags = [bool(v) for v in viable_flags]
        total = max(1, len(self._audio_sources))
        idx = max(0, min(int(current_index), total - 1))
        self._audio_current_idx = idx
        self._audio_selected_idx = idx

    def toggle_audio_selected_viable(self) -> bool:
        """Toggle viability tag for the currently selected audio source."""
        if not self._audio_sources:
            return False
        idx = self.get_audio_selected_index()
        if idx >= len(self._audio_viable_flags):
            self._audio_viable_flags = [True] * len(self._audio_sources)
        self._audio_viable_flags[idx] = not bool(self._audio_viable_flags[idx])
        return bool(self._audio_viable_flags[idx])

    def move_audio_selection(self, delta: int) -> None:
        """Move the audio selector cursor by delta rows (wraps)."""
        total = max(1, len(self._audio_sources))
        self._audio_selected_idx = (self._audio_selected_idx + delta) % total

    def get_audio_selected_index(self) -> int:
        """Return the source index currently highlighted in selector."""
        if not self._audio_sources:
            return 0
        return max(0, min(self._audio_selected_idx, len(self._audio_sources) - 1))

    def set_audio_selected_index(self, index: int) -> int:
        """Set highlighted audio source row; returns clamped index."""
        if not self._audio_sources:
            self._audio_selected_idx = 0
            return 0
        clamped = max(0, min(int(index), len(self._audio_sources) - 1))
        self._audio_selected_idx = clamped
        return clamped

    def _render_audio_selector(self) -> None:
        """Draw the audio source selector modal."""
        t = self._hud_t
        pulse = 0.55 + 0.45 * math.sin(t * 2.8)

        W = float(self._width)
        H = float(self._height)
        row_h = 38.0
        n_rows = max(1, len(self._audio_sources))
        panel_w = min(W * 0.62, 860.0)
        panel_h = 80.0 + n_rows * row_h + 56.0
        px = (W - panel_w) * 0.5
        py = (H - panel_h) * 0.5

        self._draw_modal_underlay(px, py, panel_w, panel_h, alpha=0.55, pad=8.0)

        self._draw_rect(px, py, panel_w, panel_h, (0.04, 0.05, 0.12, 0.96))
        bw = 2.0
        c_border = (0.18 * pulse, 0.55 * pulse, 1.0 * pulse, 0.9)
        self._draw_rect(px, py, panel_w, bw, c_border)
        self._draw_rect(px, py + panel_h - bw, panel_w, bw, c_border)
        self._draw_rect(px, py, bw, panel_h, c_border)
        self._draw_rect(px + panel_w - bw, py, bw, panel_h, c_border)
        bass = float(self._hud_state.get('bass', '0.0') or 0.0)
        mid = float(self._hud_state.get('mid', '0.0') or 0.0)
        treble = float(self._hud_state.get('treble', '0.0') or 0.0)
        self._draw_audio_reactive_border_bulbs(px, py, panel_w, panel_h, bass, mid, treble, t, speed_scale=0.5, size_scale=0.5)


        self._draw_text('AUDIO SOURCE SELECT', px + 18, py + 14, scale=3.5,
                        color=(0.3 + 0.2 * pulse, 0.75, 1.0, 1.0))

        active_name = 'none'
        if self._audio_sources and 0 <= self._audio_current_idx < len(self._audio_sources):
            active_name = self._audio_sources[self._audio_current_idx]
        self._draw_text(f'Active: {active_name}', px + 18, py + 48, scale=2.2,
                        color=(0.5, 0.8, 0.5, 0.85))

        entries = self._audio_sources if self._audio_sources else ['(no sources available)']
        for i, name in enumerate(entries):
            ry = py + 80.0 + i * row_h
            is_sel = i == self._audio_selected_idx
            is_active = i == self._audio_current_idx
            is_viable = True
            if i < len(self._audio_viable_flags):
                is_viable = bool(self._audio_viable_flags[i])
            tag = '[V]' if is_viable else '[ ]'

            if is_sel:
                self._draw_rect(px + 8, ry - 2, panel_w - 16, row_h - 4,
                                (0.10, 0.25, 0.55, 0.85))
                self._draw_text(f'> {tag} {name}', px + 22, ry + 5, scale=2.8,
                                color=(1.0, 0.92, 0.2, 1.0))
            else:
                label_color = (0.3, 0.9, 0.3, 0.9) if is_active else (0.7, 0.8, 1.0, 0.75)
                self._draw_text(f'  {tag} {name}', px + 22, ry + 5, scale=2.8,
                                color=label_color)

        fy = py + panel_h - 40.0
        self._draw_text('Up/Down: navigate    T: toggle viable    Enter: apply    Esc: cancel',
                        px + 18, fy, scale=2.0, color=(0.55, 0.65, 0.75, 0.80))

    # ------------------------------------------------------------------
    # MIDI device selector
    # ------------------------------------------------------------------

    def set_midi_ports(self, ports: list[str], current_port: str) -> None:
        """Populate the MIDI selector port list before opening the overlay."""
        self._midi_ports = list(ports)
        self._midi_current_port = current_port
        # Pre-select the currently active port (offset +1 because index 0 = None)
        self._midi_selected_idx = 0
        for i, p in enumerate(self._midi_ports):
            if p == current_port:
                self._midi_selected_idx = i + 1
                break

    def move_midi_selection(self, delta: int) -> None:
        """Move the MIDI selector cursor by delta rows (wraps)."""
        total = len(self._midi_ports) + 1   # +1 for the "None" entry
        self._midi_selected_idx = (self._midi_selected_idx + delta) % total

    def get_midi_selected_port(self) -> str:
        """Return the port name currently highlighted ('' = None / disable)."""
        if self._midi_selected_idx == 0:
            return ''
        idx = self._midi_selected_idx - 1
        if idx < len(self._midi_ports):
            return self._midi_ports[idx]
        return ''

    def get_midi_selected_index(self) -> int:
        """Return highlighted MIDI selector row index."""
        total = len(self._midi_ports) + 1
        return max(0, min(self._midi_selected_idx, max(0, total - 1)))

    def set_midi_selected_index(self, index: int) -> int:
        """Set highlighted MIDI row; returns clamped index."""
        total = len(self._midi_ports) + 1
        if total <= 0:
            self._midi_selected_idx = 0
            return 0
        clamped = max(0, min(int(index), total - 1))
        self._midi_selected_idx = clamped
        return clamped

    def _render_midi_selector(self) -> None:
        """Draw the MIDI device selector modal."""
        t = self._hud_t
        pulse = 0.55 + 0.45 * math.sin(t * 2.8)

        W = float(self._width)
        H = float(self._height)
        row_h = 38.0
        n_rows = len(self._midi_ports) + 1   # +1 for None entry
        panel_w = min(W * 0.62, 780.0)
        panel_h = 80.0 + n_rows * row_h + 56.0
        px = (W - panel_w) * 0.5
        py = (H - panel_h) * 0.5

        self._draw_modal_underlay(px, py, panel_w, panel_h, alpha=0.55, pad=8.0)

        # Panel background
        self._draw_rect(px, py, panel_w, panel_h, (0.04, 0.05, 0.12, 0.96))
        # Neon border
        bw = 2.0
        c_border = (0.18 * pulse, 0.55 * pulse, 1.0 * pulse, 0.9)
        self._draw_rect(px,               py,               panel_w, bw,       c_border)
        self._draw_rect(px,               py + panel_h - bw, panel_w, bw,     c_border)
        self._draw_rect(px,               py,               bw,       panel_h, c_border)
        self._draw_rect(px + panel_w - bw, py,              bw,       panel_h, c_border)

        bass = float(self._hud_state.get('bass', '0.0') or 0.0)
        mid = float(self._hud_state.get('mid', '0.0') or 0.0)
        treble = float(self._hud_state.get('treble', '0.0') or 0.0)
        self._draw_audio_reactive_border_bulbs(px, py, panel_w, panel_h, bass, mid, treble, t, speed_scale=0.5, size_scale=0.5)

        # Title
        self._draw_text('MIDI DEVICE SELECT', px + 18, py + 14, scale=3.5,
                        color=(0.3 + 0.2 * pulse, 0.75, 1.0, 1.0))

        # Current device status line
        status = f'Active: {self._midi_current_port}' if self._midi_current_port else 'Active: none'
        self._draw_text(status, px + 18, py + 48, scale=2.2,
                        color=(0.5, 0.8, 0.5, 0.85))

        # Port rows
        entries = ['(none — disable MIDI)'] + self._midi_ports
        for i, name in enumerate(entries):
            ry = py + 80.0 + i * row_h
            is_sel = i == self._midi_selected_idx
            is_active = (i == 0 and not self._midi_current_port) or (
                i > 0 and self._midi_ports[i - 1] == self._midi_current_port
            )

            if is_sel:
                self._draw_rect(px + 8, ry - 2, panel_w - 16, row_h - 4,
                                (0.10, 0.25, 0.55, 0.85))
                self._draw_text(f'> {name}', px + 22, ry + 5, scale=2.8,
                                color=(1.0, 0.92, 0.2, 1.0))
            else:
                label_color = (0.3, 0.9, 0.3, 0.9) if is_active else (0.7, 0.8, 1.0, 0.75)
                self._draw_text(f'  {name}', px + 22, ry + 5, scale=2.8,
                                color=label_color)

        # Instructions footer
        fy = py + panel_h - 40.0
        self._draw_text('Up/Down: navigate    Enter: apply    Esc: cancel',
                        px + 18, fy, scale=2.0, color=(0.55, 0.65, 0.75, 0.80))

    # ------------------------------------------------------------------
    # Webcam editor modal
    # ------------------------------------------------------------------

    def set_webcam_editor_data(
        self,
        devices: list[dict[str, object]],
        image_state: dict[str, object],
    ) -> None:
        """Populate webcam editor modal data before opening/rendering."""
        self._webcam_editor_devices = list(devices)
        if self._webcam_editor_devices:
            selected = next(
                (i for i, dev in enumerate(self._webcam_editor_devices) if bool(dev.get('selected', False))),
                self._webcam_editor_selected_idx,
            )
            self._webcam_editor_selected_idx = max(0, min(selected, len(self._webcam_editor_devices) - 1))
        else:
            self._webcam_editor_selected_idx = 0
        merged = dict(self._webcam_editor_state)
        merged.update(dict(image_state or {}))
        self._webcam_editor_state = merged

    def move_webcam_editor_selection(self, delta: int) -> None:
        """Move webcam editor camera selection cursor by delta rows (wraps)."""
        total = len(self._webcam_editor_devices)
        if total <= 0:
            self._webcam_editor_selected_idx = 0
            return
        self._webcam_editor_selected_idx = (self._webcam_editor_selected_idx + int(delta)) % total

    def get_webcam_editor_selected_camera_id(self) -> int | None:
        """Return camera id currently highlighted in webcam editor modal."""
        if not self._webcam_editor_devices:
            return None
        idx = max(0, min(self._webcam_editor_selected_idx, len(self._webcam_editor_devices) - 1))
        try:
            return int(self._webcam_editor_devices[idx].get('id'))
        except Exception:
            return None

    def _render_webcam_editor_modal(self) -> None:
        """Draw webcam editor modal for device/image controls."""
        t = self._hud_t
        pulse = 0.55 + 0.45 * math.sin(t * 2.6)

        px, py, panel_w, panel_h, W, H = self._begin_panel(0.72, 980.0, 0.80, 760.0, underlay_alpha=0.58, underlay_pad=10.0)

        self._draw_rect(px, py, panel_w, panel_h, (0.04, 0.05, 0.12, 0.96))
        bw = 2.0
        c_border = (0.18 * pulse, 0.55 * pulse, 1.0 * pulse, 0.9)
        self._draw_rect(px, py, panel_w, bw, c_border)
        self._draw_rect(px, py + panel_h - bw, panel_w, bw, c_border)
        self._draw_rect(px, py, bw, panel_h, c_border)
        self._draw_rect(px + panel_w - bw, py, bw, panel_h, c_border)
        bass = float(self._hud_state.get('bass', '0.0') or 0.0)
        mid = float(self._hud_state.get('mid', '0.0') or 0.0)
        treble = float(self._hud_state.get('treble', '0.0') or 0.0)
        self._draw_audio_reactive_border_bulbs(px, py, panel_w, panel_h, bass, mid, treble, t, speed_scale=0.5, size_scale=0.5)


        self._draw_text('WEBCAM EDITOR', px + 18, py + 14, scale=3.5,
                        color=(0.3 + 0.2 * pulse, 0.75, 1.0, 1.0))

        s = self._webcam_editor_state
        b = float(s.get('brightness', 1.0) or 1.0)
        c = float(s.get('contrast', 1.0) or 1.0)
        fh = bool(s.get('flip_horizontal', False))
        fv = bool(s.get('flip_vertical', False))
        switching = bool(s.get('switching', False))
        rem = float(s.get('switch_hide_remaining_s', 0.0) or 0.0)

        self._draw_text(f'Brightness: {b:.2f}    Contrast: {c:.2f}', px + 18, py + 52, scale=2.2,
                        color=(0.55, 0.85, 0.62, 0.90))
        self._draw_text(f'Flip H: {"ON" if fh else "OFF"}    Flip V: {"ON" if fv else "OFF"}', px + 18, py + 76, scale=2.2,
                        color=(0.70, 0.84, 1.0, 0.90))
        if switching:
            self._draw_text(f'SWITCHING... {rem:.1f}s', px + panel_w - 240, py + 76, scale=2.1,
                            color=(1.0, 0.75, 0.22, 0.96))

        row_h = 34.0
        list_top = py + 110.0
        entries = self._webcam_editor_devices if self._webcam_editor_devices else [
            {'id': -1, 'label': '(no cameras detected)', 'enabled': False, 'selected': False},
        ]

        for i, entry in enumerate(entries[:12]):
            ry = list_top + i * row_h
            is_sel = i == self._webcam_editor_selected_idx
            is_enabled = bool(entry.get('enabled', False))
            is_active = bool(entry.get('selected', False))
            cam_id = int(entry.get('id', -1))
            label = str(entry.get('label', cam_id))
            state_tag = 'ON' if is_enabled else 'OFF'
            active_tag = '*' if is_active else ' '
            text = f'{active_tag} {label:<12} [{state_tag}]'

            if is_sel:
                self._draw_rect(px + 12, ry - 1, panel_w - 24, row_h - 4,
                                (0.10, 0.25, 0.55, 0.85))
                self._draw_text(f'> {text}', px + 24, ry + 4, scale=2.5,
                                color=(1.0, 0.92, 0.2, 1.0))
            else:
                col = (0.40, 0.92, 0.44, 0.90) if is_enabled else (0.98, 0.48, 0.48, 0.88)
                self._draw_text(f'  {text}', px + 24, ry + 4, scale=2.5,
                                color=col)

        fy = py + panel_h - 64.0
        self._draw_text('Up/Down: select camera   Enter: switch camera   E: enable/disable',
                        px + 18, fy, scale=2.0, color=(0.55, 0.65, 0.75, 0.85))
        self._draw_text('R: rediscover   [/]: brightness -/+   ;/\': contrast -/+   H/V: flip H/V   Esc/Ctrl+Alt+K: close',
                        px + 18, fy + 22, scale=2.0, color=(0.55, 0.65, 0.75, 0.85))

    def set_projectm_manager_entries(
        self,
        entries: list[dict[str, object]],
        current_path: str,
    ) -> None:
        """Populate the projectM manager browser with catalog entries."""
        self._projectm_browser.set_entries(entries)
        self._projectm_current_path = str(current_path or '')
        self._sync_projectm_preset_selection()

    def _projectm_filtered_entries(self) -> list[dict[str, object]]:
        return self._projectm_browser.filtered()

    def set_projectm_search_query(self, query: str) -> None:
        """Set the ProjectM manager text filter and keep selection coherent."""
        self._projectm_browser.set_search_query(query)
        self._sync_projectm_preset_selection()

    def clear_projectm_search_query(self) -> None:
        """Clear the ProjectM manager text filter."""
        self.set_projectm_search_query('')

    @property
    def projectm_search_query(self) -> str:
        """Return current ProjectM manager text filter."""
        return self._projectm_browser.search_query

    def _projectm_category_stats(self, category: str) -> tuple[int, int]:
        # ProjectM-specific: count *enabled* presets, not generic query matches.
        total = 0
        enabled = 0
        for entry in self._projectm_browser.entries():
            key = str(entry.get('category_key', '') or '(uncategorized)')
            if category != '(all)' and key != category:
                continue
            total += 1
            if bool(entry.get('enabled', False)):
                enabled += 1
        return enabled, total

    def _sync_projectm_preset_selection(self) -> None:
        rows = self._projectm_browser.filtered()
        for idx, entry in enumerate(rows):
            if str(entry.get('path', '')) == self._projectm_current_path:
                self._projectm_browser.set_selected_index(idx)
                return
        # No current-path match: re-clamp the existing selection to the filter.
        self._projectm_browser.set_selected_index(self._projectm_browser.selected_index())

    def move_projectm_category_selection(self, delta: int) -> None:
        """Move the projectM category cursor by delta rows (wraps)."""
        self._projectm_browser.move_category(delta)
        self._sync_projectm_preset_selection()

    def move_projectm_preset_selection(self, delta: int) -> None:
        """Move the projectM preset cursor by delta rows."""
        self._projectm_browser.move_selection(delta)

    def move_projectm_focus(self, delta: int) -> None:
        """Switch projectM manager focus between category and preset panes."""
        if int(delta) % 2 != 0:
            self._projectm_browser.toggle_focus_pane()

    def set_projectm_focus_pane(self, pane: int) -> int:
        """Set active ProjectM manager pane (0=category, 1=preset)."""
        return self._projectm_browser.set_focus_pane(pane)

    def set_projectm_category_index(self, index: int) -> int:
        """Set ProjectM category selection index and sync dependent preset index."""
        result = self._projectm_browser.set_category_index(index)
        self._sync_projectm_preset_selection()
        return result

    def get_projectm_category_index(self) -> int:
        """Return current ProjectM category selection index."""
        return self._projectm_browser.category_index()

    def set_projectm_preset_index(self, index: int) -> int:
        """Set ProjectM preset selection index for current category/search filter."""
        return self._projectm_browser.set_selected_index(index)

    def get_projectm_preset_index(self) -> int:
        """Return current ProjectM preset selection index."""
        return self._projectm_browser.selected_index()

    def projectm_categories(self) -> list[str]:
        """Return ProjectM category labels in current manager ordering."""
        return self._projectm_browser.categories()

    def projectm_filtered_presets(self) -> list[dict[str, object]]:
        """Return filtered ProjectM preset rows for current category/search state."""
        return list(self._projectm_browser.filtered())

    def get_projectm_selected_category(self) -> str:
        """Return the currently highlighted category key."""
        return self._projectm_browser.selected_category()

    def get_projectm_selected_preset(self) -> dict[str, object] | None:
        """Return the currently highlighted preset entry for the active filter."""
        return self._projectm_browser.selected_entry()

    # -- Effects browser (shared CatalogBrowser model) --------------------

    @property
    def effects_browser(self) -> CatalogBrowser:
        """Return the shared browser model that drives the effects modal."""
        return self._effects_browser

    @property
    def effects_browser_visible(self) -> bool:
        """Return whether the effects browser modal is open."""
        return self._show_effects_browser

    def toggle_effects_browser(self) -> None:
        """Toggle the effects browser modal."""
        self._show_effects_browser = not self._show_effects_browser

    def set_effects_browser_entries(
        self,
        entries: list[dict[str, object]],
        current_name: str,
    ) -> None:
        """Populate the effects browser catalog and mark the current effect."""
        self._effects_browser.set_entries(entries)
        self._effects_browser_current = str(current_name or '')

    def set_effects_browser_thumbnail(self, tex: 'moderngl.Texture | None') -> None:
        """Set the live-preview texture drawn in the effects browser (or None)."""
        self._eb_thumb_tex = tex

    def set_effects_browser_pinned(self, name: str) -> None:
        """Set the display NAME of the currently pinned effect ('' for none)."""
        self._effects_browser_pinned = str(name or '')

    @staticmethod
    def _eb_hit(
        rects: list[tuple[float, float, float, float, int]],
        x: float,
        y: float,
    ) -> int | None:
        for rx, ry, rw, rh, idx in rects:
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                return idx
        return None

    def handle_effects_browser_mouse_motion(self, x: float, y: float) -> bool:
        """Hover-highlight the row under the cursor. Returns True if over a row."""
        if not self._show_effects_browser:
            return False
        self._feed_modal_tooltips(
            'effects_browser', x, y, self._effects_browser_tooltip_regions(),
        )
        idx = self._eb_hit(self._eb_row_rects, x, y)
        if idx is not None:
            self._effects_browser.set_focus_pane(PANE_LIST)
            self._effects_browser.set_selected_index(idx)
            return True
        return False

    def handle_effects_browser_mouse_click(self, x: float, y: float) -> int:
        """Route a click. Returns 0 miss, 1 category selected, 2 row chosen."""
        if not self._show_effects_browser:
            return 0
        if self._tooltip_tracker is not None:
            self._tooltip_tracker.notify_click()
        cidx = self._eb_hit(self._eb_cat_rects, x, y)
        if cidx is not None:
            self._effects_browser.set_focus_pane(PANE_CATEGORIES)
            self._effects_browser.set_category_index(cidx)
            return 1
        ridx = self._eb_hit(self._eb_row_rects, x, y)
        if ridx is not None:
            self._effects_browser.set_focus_pane(PANE_LIST)
            self._effects_browser.set_selected_index(ridx)
            return 2
        return 0

    def _effects_browser_tooltip_regions(self) -> list[TooltipRegion]:
        """Build tooltip regions from the browser's cached row/category rects."""
        regions: list[TooltipRegion] = []
        categories = self._effects_browser.categories()
        for rx, ry, rw, rh, idx in self._eb_cat_rects:
            if 0 <= idx < len(categories):
                regions.append(TooltipRegion(
                    rect=(int(rx), int(ry), int(rw), int(rh)),
                    text=f"Filter to the '{categories[idx]}' category",
                ))
        rows = self._effects_browser.filtered()
        for rx, ry, rw, rh, idx in self._eb_row_rects:
            if 0 <= idx < len(rows):
                name = str(rows[idx].get('display_name', '') or '')
                regions.append(TooltipRegion(
                    rect=(int(rx), int(ry), int(rw), int(rh)),
                    text=f"Switch the audience output to '{name}'",
                ))
        return regions

    def _feed_modal_tooltips(
        self, surface: str, x: float, y: float, regions: list[TooltipRegion],
    ) -> None:
        """Feed a modal surface's cursor position into the shared tracker."""
        if not self._tooltips_enabled:
            return
        self._tooltip_surface = surface
        self._tooltip_tracker.on_motion(x, y, regions)

    def lookup_help_key(self, description: str) -> str:
        """Return the key combo whose help entry matches ``description``.

        Keeps tooltip key hints sourced from the help registry — the single
        source of truth for bindings — instead of hardcoding key names.
        Empty string when no entry matches.
        """
        needle = str(description or '').strip().lower()
        if not needle:
            return ''
        for _section, entries in self._iter_help_sections():
            for key, desc in entries:
                if str(desc).strip().lower() == needle:
                    return str(key)
        return ''

    def _render_active_tooltip(self, route_modals_elsewhere: bool) -> None:
        """Draw the active modal tooltip, last, above every modal layer."""
        if not self._tooltips_enabled or route_modals_elsewhere:
            return
        surface_visible = {
            'effects_browser': self._show_effects_browser,
            'presets': self._show_presets,
            'config_editor': self._show_config_editor,
        }
        if self._tooltip_surface and not surface_visible.get(self._tooltip_surface, False):
            self._tooltip_tracker.reset()
            self._tooltip_surface = ''
            return
        tip = self._tooltip_tracker.tick()
        anchor = self._tooltip_tracker.anchor
        if tip is None or anchor is None:
            return
        text = tip.text
        if tip.hotkey_ref:
            key = self.lookup_help_key(tip.hotkey_ref)
            if key:
                text = f'{text} — key: {key}'
        self._draw_tooltip_bubble(text, anchor)

    def _draw_modal_frame_decor(
        self, x: float, y: float, w: float, h: float, pulse: float
    ) -> None:
        """Draw HUD-style corner accents, crosshair arms, and side tick marks
        around a modal panel — the same decorator language as the status HUD."""
        orange = (1.0, 0.58, 0.12)
        teal = (0.10, 0.94, 1.0)
        violet = (0.78, 0.38, 1.0)
        # Corner accent blocks (orange).
        csz = 14.0
        ca = 0.65 + pulse * 0.30
        for cx, cy in (
            (x - 1.0, y - 1.0),
            (x + w - csz + 1.0, y - 1.0),
            (x - 1.0, y + h - csz + 1.0),
            (x + w - csz + 1.0, y + h - csz + 1.0),
        ):
            self._draw_rect(cx, cy, csz, csz, (*orange, ca))
        # Inner teal corner squares.
        ic = 6.0
        ica = 0.52 + pulse * 0.32
        for cx, cy in (
            (x + 2.0, y + 2.0),
            (x + w - ic - 2.0, y + 2.0),
            (x + 2.0, y + h - ic - 2.0),
            (x + w - ic - 2.0, y + h - ic - 2.0),
        ):
            self._draw_rect(cx, cy, ic, ic, (*teal, ica))
        # Crosshair arms extending inward from each corner.
        arm_len = 40.0
        arm = (*orange, 0.28 + pulse * 0.20)
        self._draw_rect(x + csz, y + 1.0, arm_len, 1.0, arm)
        self._draw_rect(x + 1.0, y + csz, 1.0, arm_len, arm)
        self._draw_rect(x + w - csz - arm_len, y + 1.0, arm_len, 1.0, arm)
        self._draw_rect(x + w - 2.0, y + csz, 1.0, arm_len, arm)
        self._draw_rect(x + csz, y + h - 2.0, arm_len, 1.0, arm)
        self._draw_rect(x + 1.0, y + h - csz - arm_len, 1.0, arm_len, arm)
        self._draw_rect(x + w - csz - arm_len, y + h - 2.0, arm_len, 1.0, arm)
        self._draw_rect(x + w - 2.0, y + h - csz - arm_len, 1.0, arm_len, arm)
        # Side tick marks (3 per edge; inner halves are covered by content panes).
        tick_colors = (
            (*teal, 0.52 + pulse * 0.24),
            (*orange, 0.52 + pulse * 0.24),
            (*violet, 0.52 + pulse * 0.24),
        )
        for edge_x in (x + 6.0, x + w - 24.0):
            for tp, tc in zip((0.28, 0.5, 0.72), tick_colors):
                ty = y + tp * h
                faint = (tc[0], tc[1], tc[2], tc[3] * 0.4)
                self._draw_rect(edge_x, ty - 1.0, 18.0, 1.0, faint)
                self._draw_rect(edge_x, ty, 18.0, 3.0, tc)
                self._draw_rect(edge_x, ty + 3.0, 18.0, 1.0, faint)

    # -- Show presets modal ---------------------------------------------------

    @property
    def presets_browser(self) -> CatalogBrowser:
        """Return the model backing the presets list."""
        return self._presets_browser

    @property
    def presets_visible(self) -> bool:
        """Return whether the presets modal is open."""
        return self._show_presets

    def toggle_presets(self) -> None:
        """Toggle the presets modal."""
        self._show_presets = not self._show_presets

    def set_presets_entries(self, names: list[str]) -> None:
        """Populate the presets list from saved preset names."""
        self._presets_browser.set_entries(
            [{'display_name': str(n), 'category_key': 'preset', 'tags': []} for n in names]
        )

    @property
    def presets_name_mode(self) -> bool:
        """Return whether the presets modal is capturing a new preset name."""
        return self._presets_name_mode

    def set_presets_name_mode(self, active: bool) -> None:
        """Enter/leave name-entry mode; clears the buffer on leave."""
        self._presets_name_mode = bool(active)
        if not self._presets_name_mode:
            self._presets_name_text = ''

    @property
    def presets_name_text(self) -> str:
        """Return the in-progress new-preset name."""
        return self._presets_name_text

    def set_presets_name_text(self, text: str) -> None:
        """Set the in-progress new-preset name buffer."""
        self._presets_name_text = str(text)

    def handle_presets_mouse_motion(self, x: float, y: float) -> bool:
        """Hover-highlight a preset row. Returns True if over a row."""
        if not self._show_presets:
            return False
        self._feed_modal_tooltips('presets', x, y, self._presets_tooltip_regions())
        idx = self._eb_hit(self._presets_row_rects, x, y)
        if idx is not None:
            self._presets_browser.set_selected_index(idx)
            return True
        return False

    def handle_presets_mouse_click(self, x: float, y: float) -> bool:
        """Select the clicked preset row. Returns True if a row was chosen."""
        if not self._show_presets:
            return False
        if self._tooltip_tracker is not None:
            self._tooltip_tracker.notify_click()
        idx = self._eb_hit(self._presets_row_rects, x, y)
        if idx is not None:
            self._presets_browser.set_selected_index(idx)
            return True
        return False

    def _presets_tooltip_regions(self) -> list[TooltipRegion]:
        """Build tooltip regions from the presets browser's cached row rects."""
        regions: list[TooltipRegion] = []
        rows = self._presets_browser.filtered()
        for rx, ry, rw, rh, idx in self._presets_row_rects:
            if 0 <= idx < len(rows):
                name = str(rows[idx].get('display_name', '') or '')
                regions.append(TooltipRegion(
                    rect=(int(rx), int(ry), int(rw), int(rh)),
                    text=f"Load preset '{name}'",
                ))
        return regions

    def _render_presets(self) -> None:
        """Draw the show-presets modal (list + inline name entry)."""
        b = self._presets_browser
        t = self._hud_t
        pulse = 0.55 + 0.45 * math.sin(t * 2.4)
        self._presets_row_rects = []

        W = float(self._width)
        H = float(self._height)
        panel_w = min(W * 0.62, 900.0)
        panel_h = min(H * 0.78, 720.0)
        px = (W - panel_w) * 0.5
        py = (H - panel_h) * 0.5
        content_y = py + 96.0
        content_h = panel_h - 168.0
        list_x = px + 14.0
        list_w = panel_w - 28.0
        footer_y = py + panel_h - 52.0

        self._draw_rect(px, py, panel_w, panel_h, (0.04, 0.05, 0.10, 0.96))
        border = (0.30 * pulse, 0.85 * pulse, 0.70 * pulse, 0.92)
        bw = 2.0
        self._draw_rect(px, py, panel_w, bw, border)
        self._draw_rect(px, py + panel_h - bw, panel_w, bw, border)
        self._draw_rect(px, py, bw, panel_h, border)
        self._draw_rect(px + panel_w - bw, py, bw, panel_h, border)

        bass = float(self._hud_state.get('bass', '0.0') or 0.0)
        mid = float(self._hud_state.get('mid', '0.0') or 0.0)
        treble = float(self._hud_state.get('treble', '0.0') or 0.0)
        self._draw_audio_reactive_border_bulbs(
            px, py, panel_w, panel_h, bass, mid, treble, t, speed_scale=0.5, size_scale=0.5
        )

        self._draw_text(
            'SHOW PRESETS', px + 18.0, py + 14.0, scale=3.5,
            color=(0.40, 0.92 + 0.05 * pulse, 0.78, 1.0),
        )
        if self._presets_name_mode:
            caret = '_' if (int(t * 2.0) % 2 == 0) else ' '
            self._draw_text(
                f'Save as: {self._presets_name_text}{caret}', px + 18.0, py + 54.0,
                scale=2.2, color=(1.0, 0.92, 0.35, 0.95),
            )
        else:
            self._draw_text(
                f'{len(b.filtered())} saved', px + 18.0, py + 54.0,
                scale=2.1, color=(0.62, 0.85, 0.72, 0.88),
            )

        self._draw_modal_frame_decor(px, py, panel_w, panel_h, pulse)
        self._draw_rect(list_x, content_y, list_w, content_h, (0.05, 0.09, 0.11, 0.82))

        rows = b.filtered()
        sel_idx = b.selected_index()
        row_h = 30.0
        start_y = content_y + 12.0
        visible = max(1, int((content_h - 20.0) // row_h))
        top = max(0, sel_idx - visible + 1) if sel_idx >= visible else 0
        if not rows:
            self._draw_text(
                'No presets yet — press S to save the current setup.',
                list_x + 16.0, start_y + 6.0, scale=2.0, color=(0.86, 0.88, 0.92, 0.86),
            )
        for local_idx, entry in enumerate(rows[top:top + visible]):
            idx = top + local_idx
            ry = start_y + local_idx * row_h
            name = str(entry.get('display_name', ''))
            if idx == sel_idx:
                self._draw_rect(list_x + 6.0, ry - 2.0, list_w - 12.0, row_h - 4.0, (0.08, 0.30, 0.24, 0.90))
                self._draw_text(f'> {name}', list_x + 16.0, ry + 4.0, scale=2.1, color=(0.75, 1.0, 0.90, 1.0))
            else:
                self._draw_text(f'  {name}', list_x + 16.0, ry + 4.0, scale=2.1, color=(0.86, 0.90, 0.94, 0.90))
            self._presets_row_rects.append((list_x + 6.0, ry - 2.0, list_w - 12.0, row_h - 4.0, idx))

        if self._presets_name_mode:
            hint = 'Type a name    Enter: save    Esc: cancel'
        else:
            hint = 'Up/Down: browse    Enter/Click: load    S: save current    D: delete    Esc: close'
        self._draw_text(hint, px + 18.0, footer_y + 6.0, scale=1.8, color=(0.58, 0.72, 0.68, 0.86))

    def _render_effects_browser(self) -> None:
        """Draw the effects browser modal (categories + searchable effect list)."""
        b = self._effects_browser
        t = self._hud_t
        pulse = 0.55 + 0.45 * math.sin(t * 2.4)
        self._eb_cat_rects = []
        self._eb_row_rects = []

        W = float(self._width)
        H = float(self._height)
        panel_w = min(W * 0.90, 1320.0)
        panel_h = min(H * 0.86, 860.0)
        px = (W - panel_w) * 0.5
        py = (H - panel_h) * 0.5
        left_w = max(260.0, panel_w * 0.28)
        right_w = panel_w - left_w - 42.0
        left_x = px + 14.0
        right_x = left_x + left_w + 14.0
        content_y = py + 86.0
        content_h = panel_h - 164.0
        footer_y = py + panel_h - 56.0

        self._draw_rect(px, py, panel_w, panel_h, (0.05, 0.03, 0.10, 0.96))
        border = (0.85 * pulse, 0.30 * pulse, 1.0 * pulse, 0.92)
        bw = 2.0
        self._draw_rect(px, py, panel_w, bw, border)
        self._draw_rect(px, py + panel_h - bw, panel_w, bw, border)
        self._draw_rect(px, py, bw, panel_h, border)
        self._draw_rect(px + panel_w - bw, py, bw, panel_h, border)

        bass = float(self._hud_state.get('bass', '0.0') or 0.0)
        mid = float(self._hud_state.get('mid', '0.0') or 0.0)
        treble = float(self._hud_state.get('treble', '0.0') or 0.0)
        self._draw_audio_reactive_border_bulbs(
            px, py, panel_w, panel_h, bass, mid, treble, t, speed_scale=0.5, size_scale=0.5
        )

        self._draw_text(
            'EFFECTS BROWSER', px + 18.0, py + 14.0, scale=3.5,
            color=(0.86, 0.52 + 0.20 * pulse, 1.0, 1.0),
        )
        _, total_total = b.category_stats('(all)')
        shown = len(b.filtered())
        self._draw_text(
            f'Showing {shown}/{total_total} effects', px + 18.0, py + 48.0,
            scale=2.2, color=(0.62, 0.85, 1.0, 0.88),
        )
        query = b.search_query
        query_display = query if query else '(none)'
        if len(query_display) > 52:
            query_display = '...' + query_display[-49:]
        search_col = (1.0, 0.92, 0.35, 0.95) if b.search_mode else (0.86, 0.90, 1.0, 0.88)
        self._draw_text(
            f'Search: {query_display}', px + 18.0, py + 70.0, scale=1.9, color=search_col
        )

        # HUD-style frame decorators (corner accents + arms + side ticks). Drawn
        # before the content panes so their inner halves are cleanly overdrawn.
        self._draw_modal_frame_decor(px, py, panel_w, panel_h, pulse)

        self._draw_rect(left_x, content_y, left_w, content_h, (0.08, 0.04, 0.13, 0.82))
        self._draw_rect(right_x, content_y, right_w, content_h, (0.07, 0.03, 0.12, 0.82))
        left_border = (1.0, 0.62, 0.20, 0.70 if b.focus_pane() == PANE_CATEGORIES else 0.32)
        right_border = (0.72, 0.30, 1.0, 0.70 if b.focus_pane() == PANE_LIST else 0.32)
        self._draw_rect(left_x, content_y, left_w, 2.0, left_border)
        self._draw_rect(right_x, content_y, right_w, 2.0, right_border)
        self._draw_text('CATEGORIES', left_x + 12.0, content_y + 10.0, scale=2.4, color=(1.0, 0.88, 0.56, 0.96))
        self._draw_text('EFFECTS', right_x + 12.0, content_y + 10.0, scale=2.4, color=(0.88, 0.80, 1.0, 0.96))

        row_h = 28.0
        cats = b.categories()
        cat_idx = b.category_index()
        cat_start_y = content_y + 48.0
        visible_cat_rows = max(1, int((content_h - 60.0) // row_h))
        cat_top = max(0, cat_idx - visible_cat_rows + 1) if cat_idx >= visible_cat_rows else 0
        for local_idx, category in enumerate(cats[cat_top:cat_top + visible_cat_rows]):
            idx = cat_top + local_idx
            ry = cat_start_y + local_idx * row_h
            matches, _ = b.category_stats(category)
            label = f'{category} [{matches}]'
            if idx == cat_idx:
                self._draw_rect(left_x + 6.0, ry - 2.0, left_w - 12.0, row_h - 3.0, (0.25, 0.18, 0.06, 0.90))
                self._draw_text(f'> {label}', left_x + 16.0, ry + 4.0, scale=2.0, color=(1.0, 0.92, 0.22, 1.0))
            else:
                self._draw_text(f'  {label}', left_x + 16.0, ry + 4.0, scale=2.0, color=(0.84, 0.86, 0.94, 0.84))
            self._eb_cat_rects.append((left_x + 6.0, ry - 2.0, left_w - 12.0, row_h - 3.0, idx))

        rows = b.filtered()
        sel_idx = b.selected_index()
        row_start_y = content_y + 48.0
        visible_rows = max(1, int((content_h - 138.0) // row_h))
        row_top = max(0, sel_idx - visible_rows + 1) if sel_idx >= visible_rows else 0
        for local_idx, entry in enumerate(rows[row_top:row_top + visible_rows]):
            idx = row_top + local_idx
            ry = row_start_y + local_idx * row_h
            name = str(entry.get('display_name', ''))
            enabled = bool(entry.get('enabled', True))
            is_current = name == self._effects_browser_current
            is_pinned = name != '' and name == self._effects_browser_pinned
            prefix = '*' if is_current else ' '
            suffix = ''
            if is_pinned:
                suffix += '  [pin]'
            hotkey_slot = entry.get('hotkey_slot')
            if isinstance(hotkey_slot, int) and 0 <= hotkey_slot < 40:
                all_key_labels = self.NUM_KEYS + self.SHIFT_KEYS + self.CTRL_KEYS + self.ALT_KEYS
                suffix += f'  [key {all_key_labels[hotkey_slot]}]'
            if not enabled:
                suffix += '  [off]'
            label = f'{prefix} {name[:38]}{suffix}'
            if idx == sel_idx:
                self._draw_rect(right_x + 6.0, ry - 2.0, right_w - 12.0, row_h - 3.0, (0.20, 0.08, 0.42, 0.90))
                sel_color = (1.0, 0.94, 0.40, 1.0) if enabled else (0.96, 0.62, 0.56, 1.0)
                self._draw_text(f'> {label}', right_x + 16.0, ry + 4.0, scale=2.0, color=sel_color)
            else:
                if not enabled:
                    color = (0.60, 0.44, 0.50, 0.66)
                elif is_current:
                    color = (0.66, 0.90, 1.0, 0.95)
                else:
                    color = (0.86, 0.86, 0.94, 0.88)
                self._draw_text(f'  {label}', right_x + 16.0, ry + 4.0, scale=2.0, color=color)
            tags = list(entry.get('tags', []) or [])[1:4]  # skip the category tag
            if tags:
                tag_text = ' '.join(f'#{tg}' for tg in tags)
                self._draw_text(
                    tag_text, right_x + right_w - 14.0 - 8.4 * len(tag_text), ry + 5.0,
                    scale=1.5, color=(0.55, 0.62, 0.78, 0.80),
                )
            self._eb_row_rects.append((right_x + 6.0, ry - 2.0, right_w - 12.0, row_h - 3.0, idx))

        details_y = content_y + content_h - 76.0
        self._draw_rect(right_x + 8.0, details_y, right_w - 16.0, 64.0, (0.10, 0.05, 0.18, 0.86))
        selected = b.selected_entry()

        # Live preview thumbnail (rendered offscreen by the app into an FBO).
        tile_h = 60.0
        tile_w = tile_h * 16.0 / 9.0
        tile_x = right_x + 14.0
        tile_y = details_y + 2.0
        if self._eb_thumb_tex is not None and selected is not None:
            self._draw_rect(tile_x - 1.0, tile_y - 1.0, tile_w + 2.0, tile_h + 2.0, (0.72, 0.30, 1.0, 0.65))
            self._draw_icon_texture(self._eb_thumb_tex, tile_x, tile_y, tile_w, tile_h, flip_v=True)
        else:
            self._draw_rect(tile_x, tile_y, tile_w, tile_h, (0.03, 0.02, 0.06, 0.9))
        text_x = tile_x + tile_w + 14.0

        if selected is None:
            self._draw_text('No effects match the current filter.', text_x, details_y + 14.0, scale=2.0, color=(0.88, 0.88, 0.92, 0.88))
        else:
            pack_name = str(selected.get('pack_name', '-'))
            category_key = str(selected.get('category_key', '(uncategorized)'))
            tag_str = ', '.join(str(x) for x in (selected.get('tags', []) or []))
            enabled = bool(selected.get('enabled', True))
            state_col = (0.52, 0.92, 0.60, 0.95) if enabled else (0.96, 0.58, 0.52, 0.95)
            self._draw_text(
                f'Pack: {pack_name}   Cat: {category_key}', text_x,
                details_y + 10.0, scale=1.7, color=(0.72, 0.80, 1.0, 0.92),
            )
            self._draw_text(
                f'[{"ENABLED" if enabled else "DISABLED"}]', text_x + right_w - 260.0,
                details_y + 10.0, scale=1.7, color=state_col,
            )
            self._draw_text(
                f'Tags: {tag_str[:64]}', text_x, details_y + 34.0,
                scale=1.5, color=(0.80, 0.84, 0.92, 0.88),
            )

        self._draw_text(
            'Left/Right: pane   Up/Down: browse   Enter/Click: go   Space: on/off   '
            'P: pin/unpin   /: search   Esc: close',
            px + 18.0, footer_y + 6.0, scale=1.8, color=(0.60, 0.66, 0.80, 0.86),
        )
        self._draw_text(
            '1-9,0 (+Shift/Ctrl/Alt): pin/unpin selected effect to that numeric hotkey slot',
            px + 18.0, footer_y + 26.0, scale=1.8, color=(0.60, 0.66, 0.80, 0.86),
        )

    def _render_projectm_manager(self) -> None:
        """Draw the projectM preset manager modal."""
        t = self._hud_t
        pulse = 0.55 + 0.45 * math.sin(t * 2.4)

        W = float(self._width)
        H = float(self._height)
        panel_w = min(W * 0.90, 1320.0)
        panel_h = min(H * 0.86, 860.0)
        px = (W - panel_w) * 0.5
        py = (H - panel_h) * 0.5
        left_w = max(260.0, panel_w * 0.28)
        right_w = panel_w - left_w - 42.0
        left_x = px + 14.0
        right_x = left_x + left_w + 14.0
        content_y = py + 86.0
        content_h = panel_h - 164.0
        footer_y = py + panel_h - 56.0

        self._draw_rect(px, py, panel_w, panel_h, (0.03, 0.04, 0.10, 0.96))
        border = (0.18 * pulse, 0.55 * pulse, 1.0 * pulse, 0.92)
        bw = 2.0
        self._draw_rect(px, py, panel_w, bw, border)
        self._draw_rect(px, py + panel_h - bw, panel_w, bw, border)
        self._draw_rect(px, py, bw, panel_h, border)
        self._draw_rect(px + panel_w - bw, py, bw, panel_h, border)

        bass = float(self._hud_state.get('bass', '0.0') or 0.0)
        mid = float(self._hud_state.get('mid', '0.0') or 0.0)
        treble = float(self._hud_state.get('treble', '0.0') or 0.0)
        self._draw_audio_reactive_border_bulbs(px, py, panel_w, panel_h, bass, mid, treble, t, speed_scale=0.5, size_scale=0.5)

        self._draw_text(
            'PROJECTM PRESET MANAGER',
            px + 18.0,
            py + 14.0,
            scale=3.5,
            color=(0.28 + 0.20 * pulse, 0.78, 1.0, 1.0),
        )
        enabled_total, total_total = self._projectm_category_stats('(all)')
        self._draw_text(
            f'Visible catalog: {enabled_total}/{total_total} enabled',
            px + 18.0,
            py + 48.0,
            scale=2.2,
            color=(0.52, 0.85, 0.58, 0.88),
        )
        query = self._projectm_browser.search_query
        query_display = query if query else '(none)'
        if len(query_display) > 52:
            query_display = '...' + query_display[-49:]
        self._draw_text(
            f'Search: {query_display}',
            px + 18.0,
            py + 70.0,
            scale=1.9,
            color=(0.86, 0.90, 1.0, 0.88),
        )

        self._draw_rect(left_x, content_y, left_w, content_h, (0.04, 0.08, 0.13, 0.82))
        self._draw_rect(right_x, content_y, right_w, content_h, (0.03, 0.07, 0.12, 0.82))

        focus_pane = self._projectm_browser.focus_pane()
        categories = self._projectm_browser.categories()
        cat_idx = self._projectm_browser.category_index()
        preset_idx = self._projectm_browser.selected_index()

        left_border = (1.0, 0.62, 0.20, 0.70 if focus_pane == 0 else 0.32)
        right_border = (0.14, 0.90, 1.0, 0.70 if focus_pane == 1 else 0.32)
        self._draw_rect(left_x, content_y, left_w, 2.0, left_border)
        self._draw_rect(right_x, content_y, right_w, 2.0, right_border)

        self._draw_text('CATEGORIES', left_x + 12.0, content_y + 10.0, scale=2.4, color=(1.0, 0.88, 0.56, 0.96))
        self._draw_text('PRESETS', right_x + 12.0, content_y + 10.0, scale=2.4, color=(0.72, 0.92, 1.0, 0.96))

        row_h = 28.0
        cat_start_y = content_y + 48.0
        visible_cat_rows = max(1, int((content_h - 60.0) // row_h))
        cat_top = 0
        if cat_idx >= visible_cat_rows:
            cat_top = cat_idx - visible_cat_rows + 1

        for local_idx, category in enumerate(categories[cat_top:cat_top + visible_cat_rows]):
            idx = cat_top + local_idx
            ry = cat_start_y + local_idx * row_h
            is_sel = idx == cat_idx
            enabled_count, total_count = self._projectm_category_stats(category)
            label = f'{category} [{enabled_count}/{total_count}]'
            if is_sel:
                self._draw_rect(left_x + 6.0, ry - 2.0, left_w - 12.0, row_h - 3.0, (0.25, 0.18, 0.06, 0.90))
                self._draw_text(f'> {label}', left_x + 16.0, ry + 4.0, scale=2.0, color=(1.0, 0.92, 0.22, 1.0))
            else:
                self._draw_text(f'  {label}', left_x + 16.0, ry + 4.0, scale=2.0, color=(0.84, 0.86, 0.94, 0.84))

        preset_entries = self._projectm_filtered_entries()
        preset_start_y = content_y + 48.0
        preset_visible_rows = max(1, int((content_h - 138.0) // row_h))
        preset_top = 0
        if preset_idx >= preset_visible_rows:
            preset_top = preset_idx - preset_visible_rows + 1

        visible_rows = preset_entries[preset_top:preset_top + preset_visible_rows]
        for local_idx, entry in enumerate(visible_rows):
            idx = preset_top + local_idx
            ry = preset_start_y + local_idx * row_h
            is_sel = idx == preset_idx
            path = str(entry.get('path', ''))
            is_current = path == self._projectm_current_path
            enabled = bool(entry.get('enabled', False))
            prefix = '*' if is_current else ' '
            status = 'ON ' if enabled else 'OFF'
            name = str(entry.get('display_name', ''))[:54]
            label = f'{prefix} [{status}] {name}'
            if is_sel:
                self._draw_rect(right_x + 6.0, ry - 2.0, right_w - 12.0, row_h - 3.0, (0.08, 0.24, 0.54, 0.90))
                self._draw_text(f'> {label}', right_x + 16.0, ry + 4.0, scale=2.0, color=(1.0, 0.94, 0.26, 1.0))
            else:
                color = (0.40, 0.92, 0.44, 0.90) if enabled else (0.98, 0.48, 0.48, 0.88)
                self._draw_text(f'  {label}', right_x + 16.0, ry + 4.0, scale=2.0, color=color)

        details_y = content_y + content_h - 76.0
        self._draw_rect(right_x + 8.0, details_y, right_w - 16.0, 64.0, (0.04, 0.11, 0.17, 0.86))
        selected = self.get_projectm_selected_preset()
        if selected is None:
            self._draw_text('No presets in selected category.', right_x + 18.0, details_y + 14.0, scale=2.1, color=(0.88, 0.88, 0.92, 0.88))
        else:
            pack_name = str(selected.get('pack_name', '-'))
            category_key = str(selected.get('category_key', '(uncategorized)'))
            path = str(selected.get('path', ''))
            enabled = 'ON' if bool(selected.get('enabled', False)) else 'OFF'
            self._draw_text(
                f'Pack: {pack_name}    Category: {category_key}    State: {enabled}',
                right_x + 18.0,
                details_y + 10.0,
                scale=1.85,
                color=(0.62, 0.88, 1.0, 0.92),
            )
            self._draw_text(
                path[:92],
                right_x + 18.0,
                details_y + 34.0,
                scale=1.55,
                color=(0.80, 0.84, 0.92, 0.88),
            )

        self._draw_text(
            'Tab/Left/Right: pane    Up/Down: browse + preview    Enter: confirm    /: search mode    E/D: enable-disable    I: isolate',
            px + 18.0,
            footer_y - 10.0,
            scale=1.8,
            color=(0.58, 0.68, 0.78, 0.86),
        )
        self._draw_text(
            'Ctrl+A: enable all    Ctrl+Shift+A: disable all    Ctrl+Z: undo    Ctrl+Y/Ctrl+Shift+Z: redo    Delete: trash',
            px + 18.0,
            footer_y + 12.0,
            scale=1.8,
            color=(0.58, 0.68, 0.78, 0.86),
        )
        self._draw_text(
            'Esc/Ctrl+M: close + revert unconfirmed',
            px + 18.0,
            footer_y + 32.0,
            scale=1.8,
            color=(0.58, 0.68, 0.78, 0.86),
        )

    def _render_system_monitor_modal(self) -> None:
        """Draw a neon monitor dashboard modal with an oscilloscope backdrop."""
        t = self._hud_t
        pulse = 0.55 + 0.45 * math.sin(t * 2.2)

        W = float(self._width)
        H = float(self._height)

        # Heart-monitor style background wave field.
        baseline = H * 0.5
        amp = H * (0.045 + 0.015 * math.sin(t * 1.2))
        for i in range(0, 240):
            x = (i / 239.0) * W
            s = i / 239.0
            y = baseline + math.sin(s * 28.0 - t * 3.3) * amp
            y += math.sin(s * 57.0 + t * 2.2) * amp * 0.35
            glow = 0.16 + 0.14 * (0.5 + 0.5 * math.sin(t * 5.0 + s * 17.0))
            self._draw_rect(x, y - 1.0, 6.0, 2.0, (0.06, 0.92, 0.45, glow))

        panel_w = min(W * 0.80, 1220.0)
        panel_h = min(H * 0.76, 760.0)
        px = (W - panel_w) * 0.5
        py = (H - panel_h) * 0.5

        self._sample_system_telemetry()

        # Main panel shell.
        self._draw_rect(px, py, panel_w, panel_h, (0.03, 0.05, 0.12, 0.93))
        bw = 2.0
        border = (0.16 * pulse, 0.74 * pulse, 1.00 * pulse, 0.92)
        self._draw_rect(px, py, panel_w, bw, border)
        self._draw_rect(px, py + panel_h - bw, panel_w, bw, border)
        self._draw_rect(px, py, bw, panel_h, border)
        self._draw_rect(px + panel_w - bw, py, bw, panel_h, border)

        # Modal decorators: HUD-style side stacks and tick marks.
        side_w = 14.0
        block_defs = [
            (24.0, (1.00, 0.58, 0.12), 0.66),
            (6.0, None, 0.0),
            (10.0, (0.10, 0.94, 1.00), 0.58),
            (6.0, None, 0.0),
            (34.0, (0.78, 0.38, 1.00), 0.54),
            (6.0, None, 0.0),
            (24.0, (1.00, 0.58, 0.12), 0.60),
        ]
        side_rx = px + panel_w + 4.0
        side_lx = px - side_w - 4.0
        by_r = py + 8.0
        by_l = py + 8.0
        for bh, rgb, alpha in block_defs:
            if rgb is None:
                by_r += bh
                by_l += bh
                continue
            a = alpha + 0.20 * (0.5 + 0.5 * math.sin(t * 2.4 + by_r * 0.01))
            col = (rgb[0], rgb[1], rgb[2], min(1.0, a))
            self._draw_rect(side_rx, by_r, side_w, bh, col)
            self._draw_rect(side_lx, by_l, side_w, bh, col)
            by_r += bh
            by_l += bh

        tick_positions = [0.25, 0.5, 0.75]
        tick_colors = [
            (0.10, 0.94, 1.0, 0.58 + pulse * 0.18),
            (1.00, 0.62, 0.20, 0.58 + pulse * 0.18),
            (0.78, 0.38, 1.00, 0.58 + pulse * 0.18),
        ]
        tick_x_r = px + panel_w - 24.0
        tick_x_l = px + 6.0
        for tp, tc in zip(tick_positions, tick_colors):
            ty = py + tp * panel_h
            self._draw_rect(tick_x_r, ty, 18.0, 3.0, tc)
            self._draw_rect(tick_x_l, ty, 18.0, 3.0, tc)

        self._draw_text('SYSTEM MONITOR // CONTROL SURFACE', px + 18.0, py + 16.0, scale=3.0,
                        color=(0.28 + 0.25 * pulse, 0.82, 1.0, 1.0))
        self._draw_text('M: close modal', px + panel_w - 270.0, py + 20.0, scale=1.8,
                        color=(0.68, 0.80, 0.92, 0.86))

        state = self._hud_state

        def _num(key: str, default: float = 0.0) -> float:
            text = str(state.get(key, default))
            out = ''
            dot = False
            sign = False
            for ch in text:
                if ch.isdigit():
                    out += ch
                elif ch == '.' and not dot:
                    out += ch
                    dot = True
                elif ch == '-' and not sign and not out:
                    out += ch
                    sign = True
                elif out:
                    break
            try:
                return float(out)
            except Exception:
                return float(default)

        (
            fps,
            frame_ms,
            bass,
            mid,
            treble,
            bass_bar,
            mid_bar,
            treble_bar,
        ) = self._system_monitor_audio_metrics(_num)
        react, speed, zoom = self._system_monitor_tweakables(_num)

        # Left: metrics bars.
        left_x = px + 20.0
        left_y = py + 72.0
        left_w = panel_w * 0.50
        row_h = 44.0

        def _metric_row(idx: int, label: str, value: float, max_value: float, color: tuple[float, float, float]) -> None:
            y = left_y + idx * row_h
            frac = 0.0 if max_value <= 0.0 else max(0.0, min(1.0, value / max_value))
            self._draw_text(label, left_x, y + 8.0, scale=2.1, color=(0.72, 0.84, 0.98, 0.92))
            bx = left_x + 170.0
            bwid = left_w - 190.0
            self._draw_rect(bx, y + 10.0, bwid, 18.0, (0.10, 0.16, 0.26, 0.75))
            self._draw_rect(bx, y + 10.0, bwid * frac, 18.0, (color[0], color[1], color[2], 0.90))
            self._draw_rect(bx + bwid * frac - 2.0, y + 8.0, 4.0, 22.0, (0.95, 0.98, 1.0, 0.65))
            self._draw_text(f'{value:.2f}', bx + bwid + 12.0, y + 8.0, scale=2.0, color=(0.92, 0.95, 1.0, 0.92))

        _metric_row(0, 'FPS', fps, 120.0, (0.22, 1.00, 0.58))
        _metric_row(1, 'FRAME MS', max(0.0, 33.0 - frame_ms), 33.0, (0.16, 0.86, 1.00))
        _metric_row(2, 'BASS', bass_bar, 1.2, (1.00, 0.45, 0.18))
        _metric_row(3, 'MID', mid_bar, 1.2, (0.98, 0.76, 0.22))
        _metric_row(4, 'TREBLE', treble_bar, 1.2, (0.76, 0.95, 1.00))

        # Right: control panel with faux knobs/sliders.
        right_x = px + panel_w * 0.56
        right_y = py + 82.0
        self._draw_text('LIVE CONTROLS', right_x, right_y - 34.0, scale=2.4,
                        color=(1.0, 0.88, 0.54, 0.94))

        def _slider(idx: int, label: str, value: float, max_value: float, color: tuple[float, float, float]) -> None:
            y = right_y + idx * 70.0
            frac = 0.0 if max_value <= 0.0 else max(0.0, min(1.0, value / max_value))
            self._draw_text(label, right_x, y, scale=2.0, color=(0.78, 0.88, 0.98, 0.9))
            sx = right_x + 10.0
            sy = y + 24.0
            sw = panel_w * 0.34
            sh = 16.0
            self._draw_rect(sx, sy, sw, sh, (0.09, 0.14, 0.24, 0.78))
            self._draw_rect(sx, sy, sw * frac, sh, (color[0], color[1], color[2], 0.92))
            self._draw_rect(sx + sw * frac - 3.0, sy - 3.0, 6.0, sh + 6.0, (0.98, 0.98, 1.0, 0.78))
            self._draw_text(f'{value:.2f}', sx + sw + 14.0, y + 20.0, scale=2.0,
                            color=(0.92, 0.96, 1.0, 0.92))

        _slider(0, 'REACTIVITY', react, 3.0, (0.14, 0.90, 1.00))
        _slider(1, 'SPEED', speed, 4.0, (0.40, 1.00, 0.54))
        _slider(2, 'ZOOM', zoom, 2.0, (0.98, 0.40, 1.00))

        # Simple faux knobs for visual language consistency.
        knob_y = right_y + 240.0
        knob_r = 26.0
        knob_gap = 110.0
        labels = [('GAIN', bass_bar), ('PULSE', mid_bar), ('SHINE', treble_bar)]
        for i, (label, raw) in enumerate(labels):
            cx = right_x + 30.0 + i * knob_gap
            cy = knob_y
            frac = max(0.0, min(1.0, raw / 1.2))
            # Ring segments.
            for s in range(28):
                a = (s / 28.0) * 6.28318
                x = cx + math.cos(a) * knob_r
                y = cy + math.sin(a) * knob_r
                on = s <= int(frac * 28.0)
                col = (0.14, 0.90, 1.0, 0.86) if on else (0.10, 0.20, 0.30, 0.55)
                self._draw_rect(x - 1.0, y - 1.0, 3.0, 3.0, col)
            # Pointer.
            pa = (-2.35 + frac * 4.70)
            pxp = cx + math.cos(pa) * (knob_r - 6.0)
            pyp = cy + math.sin(pa) * (knob_r - 6.0)
            self._draw_rect(cx - 2.0, cy - 2.0, 4.0, 4.0, (0.88, 0.95, 1.0, 0.9))
            self._draw_rect(pxp - 2.0, pyp - 2.0, 4.0, 4.0, (0.98, 0.84, 0.25, 0.95))
            self._draw_text(label, cx - 26.0, cy + 38.0, scale=1.8, color=(0.74, 0.84, 0.94, 0.9))

        # Bottom-half system telemetry board.
        board_x = px + 20.0
        board_y = py + panel_h * 0.56
        board_w = panel_w - 40.0
        board_h = panel_h * 0.34
        self._draw_rect(board_x, board_y, board_w, board_h, (0.03, 0.08, 0.14, 0.86))
        self._draw_rect(board_x, board_y, board_w, 2.0, (0.10, 0.94, 1.0, 0.46 + pulse * 0.16))

        def _sys_row(idx: int, label: str, value: float, max_value: float, text: str, color: tuple[float, float, float]) -> None:
            y = board_y + 14.0 + idx * 40.0
            frac = 0.0 if max_value <= 0.0 else max(0.0, min(1.0, value / max_value))
            self._draw_text(label, board_x + 10.0, y + 4.0, scale=2.0, color=(0.80, 0.90, 1.0, 0.92))
            bx = board_x + 180.0
            bwid = board_w - 300.0
            self._draw_rect(bx, y + 6.0, bwid, 16.0, (0.08, 0.14, 0.24, 0.78))
            self._draw_rect(bx, y + 6.0, bwid * frac, 16.0, (color[0], color[1], color[2], 0.92))
            self._draw_rect(bx + bwid * frac - 2.0, y + 4.0, 4.0, 20.0, (0.95, 0.98, 1.0, 0.64))
            self._draw_text(text, board_x + board_w - 102.0, y + 4.0, scale=2.0, color=(0.92, 0.96, 1.0, 0.90))

        _sys_row(0, 'CPU', self._sysmon_cpu, 1.0, f'{self._sysmon_cpu * 100.0:4.1f}%', (1.00, 0.45, 0.18))
        _sys_row(1, 'RAM', self._sysmon_ram, 1.0, f'{self._sysmon_ram * 100.0:4.1f}%', (0.72, 0.44, 1.00))
        _sys_row(2, 'SWAP', self._sysmon_swap, 1.0, f'{self._sysmon_swap * 100.0:4.1f}%', (0.46, 0.78, 1.00))
        _sys_row(3, 'DISK I/O', self._sysmon_disk_mbs, 120.0, f'{self._sysmon_disk_mbs:4.1f}M', (1.00, 0.78, 0.24))
        _sys_row(4, 'NET I/O', self._sysmon_net_mbs, 120.0, f'{self._sysmon_net_mbs:4.1f}M', (0.22, 0.96, 0.66))

        self._draw_text('TELEMETRY LINK STABLE  //  NO SIGNAL CLIP DETECTED',
                        px + 20.0, py + panel_h - 28.0, scale=1.8,
                        color=(0.56, 0.68, 0.80, 0.82))

    def _system_monitor_audio_metrics(
        self,
        num_reader: Callable[[str, float], float],
    ) -> tuple[float, float, float, float, float, float, float, float]:
        """Resolve monitor frame/BMT metrics from runtime provider with HUD fallback."""
        fps = num_reader('fps', 0.0)
        frame_ms = num_reader('frame_ms', 0.0)
        bass = num_reader('bass', 0.0)
        mid = num_reader('mid', 0.0)
        treble = num_reader('treble', 0.0)
        bass_n = num_reader('bass_n', 0.5)
        mid_n = num_reader('mid_n', 0.5)
        treble_n = num_reader('treble_n', 0.5)

        provider = self._system_monitor_audio_provider
        if not callable(provider):
            return fps, frame_ms, bass, mid, treble, bass_n, mid_n, treble_n

        try:
            values = provider()
        except Exception as exc:
            log.debug('System monitor audio provider failed: %s', exc)
            return fps, frame_ms, bass, mid, treble, bass_n, mid_n, treble_n

        if not isinstance(values, dict):
            return fps, frame_ms, bass, mid, treble, bass_n, mid_n, treble_n

        def _override(name: str, current: float) -> float:
            raw = values.get(name)
            if raw is None:
                return current
            try:
                return float(raw)
            except Exception:
                return current

        fps = _override('fps', fps)
        frame_ms = _override('frame_ms', frame_ms)
        bass = _override('bass', bass)
        mid = _override('mid', mid)
        treble = _override('treble', treble)
        bass_n = _override('bass_n', bass_n)
        mid_n = _override('mid_n', mid_n)
        treble_n = _override('treble_n', treble_n)
        return fps, frame_ms, bass, mid, treble, bass_n, mid_n, treble_n

    def _system_monitor_tweakables(
        self,
        num_reader: Callable[[str, float], float],
    ) -> tuple[float, float, float]:
        """Resolve monitor tweakables from runtime provider with HUD fallback."""
        react = num_reader('reactivity', 1.0)
        speed = num_reader('speed', 1.0)
        zoom = num_reader('zoom', 1.0)

        provider = self._system_monitor_tweakables_provider
        if not callable(provider):
            return react, speed, zoom

        try:
            values = provider()
        except Exception as exc:
            log.debug('System monitor tweakables provider failed: %s', exc)
            return react, speed, zoom

        if not isinstance(values, dict):
            return react, speed, zoom

        def _override(name: str, current: float) -> float:
            raw = values.get(name)
            if raw is None:
                return current
            try:
                return float(raw)
            except Exception:
                return current

        react = _override('reactivity', react)
        speed = _override('speed', speed)
        zoom = _override('zoom', zoom)
        return react, speed, zoom


    def _sample_system_telemetry(self) -> None:
        """Update modal telemetry metrics with lightweight cached psutil reads."""
        if not _PSUTIL_AVAILABLE:
            return
        now = time.monotonic()
        if now - self._sysmon_sample_t < 0.45:
            return
        self._sysmon_sample_t = now
        try:
            self._sysmon_cpu = max(0.0, min(1.0, psutil.cpu_percent(interval=None) / 100.0))
            self._sysmon_ram = max(0.0, min(1.0, psutil.virtual_memory().percent / 100.0))
            self._sysmon_swap = max(0.0, min(1.0, psutil.swap_memory().percent / 100.0))

            disk = psutil.disk_io_counters()
            net = psutil.net_io_counters()
            if disk is None or net is None:
                return

            io_t_prev = self._sysmon_prev_io_t
            disk_prev = self._sysmon_prev_disk_bytes
            net_prev = self._sysmon_prev_net_bytes

            disk_now = float(disk.read_bytes + disk.write_bytes)
            net_now = float(net.bytes_recv + net.bytes_sent)
            self._sysmon_prev_io_t = now
            self._sysmon_prev_disk_bytes = disk_now
            self._sysmon_prev_net_bytes = net_now

            if io_t_prev is None or disk_prev is None or net_prev is None:
                return

            dt = max(1e-6, now - io_t_prev)
            disk_rate = max(0.0, (disk_now - disk_prev) / dt)
            net_rate = max(0.0, (net_now - net_prev) / dt)
            self._sysmon_disk_mbs = disk_rate / (1024.0 * 1024.0)
            self._sysmon_net_mbs = net_rate / (1024.0 * 1024.0)
        except Exception:
            pass


    def _render_help(self) -> None:
        t  = self._hud_t
        hp = self._help_pulse_t
        pulse_slow  = 0.5 + 0.5 * math.sin(t * 1.1)
        pulse_med   = 0.5 + 0.5 * math.sin(t * 2.3)
        pulse_fast  = 0.5 + 0.5 * math.sin(t * 4.7)
        shimmer_x   = math.fmod(t * 0.38, 1.0)

        # shrunk margins so side decorations clear the screen
        panel_pad = 44.0
        x = panel_pad
        y = panel_pad
        w = self._width  - panel_pad * 2.0
        h = self._height - panel_pad * 2.0

        self._draw_modal_underlay(x, y, w, h, alpha=0.45, pad=12.0)

        # Keep help legible on high-res canvases without overpowering 1080p.
        res_ratio = min(self._width, self._height) / 1080.0
        help_scale = min(1.28, max(1.0, res_ratio ** 0.35))

        # ── outer halo (breathing) ────────────────────────────────────────
        halo_a = 0.05 + pulse_slow * 0.08
        self._draw_rect(x - 18.0, y - 18.0, w + 36.0, h + 36.0, (0.08, 0.88, 1.0, halo_a * 0.5))
        self._draw_rect(x -  8.0, y -  8.0, w + 16.0, h + 16.0, (0.08, 0.88, 1.0, halo_a))

        # ── main background ───────────────────────────────────────────────
        self._draw_rect(x, y, w, h, (0.02, 0.04, 0.09, 0.65))

        # ── border (pulsing) ─────────────────────────────────────────────
        border_a = 0.50 + pulse_slow * 0.34
        self._draw_rect(x - 1.0, y - 1.0, w + 2.0, 2.0,      (0.10, 0.94, 1.0, border_a))
        self._draw_rect(x - 1.0, y + h - 1.0, w + 2.0, 2.0,  (0.10, 0.94, 1.0, border_a))
        self._draw_rect(x - 1.0, y - 1.0, 2.0, h + 2.0,      (0.10, 0.94, 1.0, border_a))
        self._draw_rect(x + w - 1.0, y - 1.0, 2.0, h + 2.0,  (0.10, 0.94, 1.0, border_a))
        bass = float(self._hud_state.get('bass', '0.0') or 0.0)
        mid = float(self._hud_state.get('mid', '0.0') or 0.0)
        treble = float(self._hud_state.get('treble', '0.0') or 0.0)
        self._draw_audio_reactive_border_bulbs(x, y, w, h, bass, mid, treble, t, speed_scale=0.45, size_scale=0.45)


        # ── sparkle sprite chasing the help border ────────────────────────
        sprite_t = math.fmod(t * 0.176, 1.0)   # slightly slower lap than HUD
        perim    = 2.0 * (w + h)
        dist     = sprite_t * perim
        if dist < w:
            hsx, hsy = x + dist, y - 1.0
        elif dist < w + h:
            hsx, hsy = x + w - 1.0, y + (dist - w)
        elif dist < 2 * w + h:
            hsx, hsy = x + w - (dist - w - h), y + h - 1.0
        else:
            hsx, hsy = x - 1.0, y + h - (dist - 2 * w - h)
        sp_a = 0.72 + 0.28 * math.sin(t * 11.3)
        self._draw_rect(hsx - 10.0, hsy - 10.0, 22.0, 22.0, (0.10, 0.94, 1.0, sp_a * 0.22))
        self._draw_rect(hsx -  7.0, hsy -  7.0, 16.0, 16.0, (0.10, 0.94, 1.0, sp_a * 0.46))
        self._draw_rect(hsx -  4.0, hsy -  4.0, 10.0, 10.0, (0.50, 0.98, 1.0, sp_a * 0.76))
        self._draw_rect(hsx -  2.0, hsy -  2.0,  6.0,  6.0, (0.80, 1.00, 1.0, sp_a * 0.92))
        self._draw_rect(hsx -  1.0, hsy -  1.0,  4.0,  4.0, (1.00, 1.00, 1.0, min(1.0, sp_a * 1.10)))
        # ghost half-lap behind
        ghost_t = math.fmod(sprite_t + 0.5, 1.0)
        gd = ghost_t * perim
        if gd < w:
            ghx, ghy = x + gd, y - 1.0
        elif gd < w + h:
            ghx, ghy = x + w - 1.0, y + (gd - w)
        elif gd < 2 * w + h:
            ghx, ghy = x + w - (gd - w - h), y + h - 1.0
        else:
            ghx, ghy = x - 1.0, y + h - (gd - 2 * w - h)
        tr_a = 0.42 + 0.28 * math.sin(t * 7.1)
        self._draw_rect(ghx - 5.0, ghy - 5.0, 12.0, 12.0, (0.78, 0.38, 1.00, tr_a * 0.38))
        self._draw_rect(ghx - 3.0, ghy - 3.0,  8.0,  8.0, (0.78, 0.38, 1.00, tr_a * 0.65))
        self._draw_rect(ghx - 1.0, ghy - 1.0,  4.0,  4.0, (1.00, 0.70, 1.00, tr_a * 0.90))

        # ── LCARS side block stacks ───────────────────────────────────────
        side_w  = 16.0
        side_rx = x + w + 4.0
        side_lx = x - 4.0 - side_w
        block_defs = [
            (28.0, (1.00, 0.58, 0.12), 0.68, 0.00, 2.30, 0.0 ),
            (6.0,  None, 0, 0, 0, 0),
            (8.0,  (1.00, 0.58, 0.12), 0.34, 0.70, 4.10, 7.3 ),
            (6.0,  None, 0, 0, 0, 0),
            (44.0, (0.10, 0.94, 1.00), 0.68, 1.10, 1.80, 0.0 ),
            (6.0,  None, 0, 0, 0, 0),
            (14.0, (0.78, 0.38, 1.00), 0.56, 2.20, 3.50, 0.0 ),
            (6.0,  None, 0, 0, 0, 0),
            (60.0, (1.00, 0.58, 0.12), 0.56, 0.50, 1.10, 0.0 ),
            (6.0,  None, 0, 0, 0, 0),
            (14.0, (0.10, 0.94, 1.00), 0.48, 1.80, 5.20, 11.7),
            (6.0,  None, 0, 0, 0, 0),
            (28.0, (0.98, 0.96, 0.30), 0.52, 0.90, 2.70, 0.0 ),
            (6.0,  None, 0, 0, 0, 0),
            (14.0, (0.78, 0.38, 1.00), 0.44, 3.10, 4.80, 9.1 ),
            (6.0,  None, 0, 0, 0, 0),
            (24.0, (1.00, 0.58, 0.12), 0.62, 1.60, 2.10, 0.0 ),
        ]
        by_r = y;  by_l = y
        for bdef in block_defs:
            bh = bdef[0]
            if bdef[1] is None:
                by_r += bh;  by_l += bh;  continue
            bh, rgb, base_a, phase, spd, strobe_spd = bdef
            pv = 0.5 + 0.5 * math.sin(t * spd + phase)
            alpha = base_a + pv * 0.28
            if strobe_spd > 0:
                alpha = min(1.0, alpha + max(0.0, math.sin(t * strobe_spd)) ** 3 * 0.38)
            bc = (rgb[0], rgb[1], rgb[2], min(1.0, alpha))
            hi_a = min(1.0, alpha * 0.55 + pv * 0.25)
            self._draw_rect(side_rx, by_r, side_w, bh, bc)
            self._draw_rect(side_rx, by_r, 2.0, bh, (1.0, 1.0, 1.0, hi_a))
            self._draw_rect(side_lx, by_l, side_w, bh, bc)
            self._draw_rect(side_lx + side_w - 2.0, by_l, 2.0, bh, (1.0, 1.0, 1.0, hi_a))
            by_r += bh;  by_l += bh

        # ── corner accent blocks + crosshair arms ────────────────────────
        corner_sz = 14.0
        ca = 0.65 + pulse_fast * 0.30
        for cx_, cy_ in [(x-1, y-1), (x+w-corner_sz+1, y-1), (x-1, y+h-corner_sz+1), (x+w-corner_sz+1, y+h-corner_sz+1)]:
            self._draw_rect(cx_, cy_, corner_sz, corner_sz, (1.0, 0.58, 0.12, ca))
        ic = 6.0;  ica = 0.52 + pulse_slow * 0.32
        for cx_, cy_ in [(x+2, y+2), (x+w-ic-2, y+2), (x+2, y+h-ic-2), (x+w-ic-2, y+h-ic-2)]:
            self._draw_rect(cx_, cy_, ic, ic, (0.10, 0.94, 1.0, ica))
        arm_len = 40.0;  arm_a = 0.28 + pulse_slow * 0.20
        self._draw_rect(x + corner_sz,           y + 1.0,                1.0, arm_len, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + 1.0,                  y + corner_sz,          arm_len, 1.0, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + w - corner_sz - 1.0,  y + 1.0,                1.0, arm_len, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + w - arm_len - 1.0,    y + 1.0,               arm_len, 1.0, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + corner_sz,           y + h - 2.0,            arm_len, 1.0, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + 1.0,                  y + h - corner_sz - arm_len, 1.0, arm_len, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + w - corner_sz - 1.0,  y + h - 2.0,           1.0, arm_len, (1.0, 0.58, 0.12, arm_a))
        self._draw_rect(x + w - arm_len - 1.0,    y + h - 2.0,          arm_len, 1.0, (1.0, 0.58, 0.12, arm_a))

        # ── header ───────────────────────────────────────────────────────
        self._draw_rect(x, y, w, 86.0, (0.05, 0.08, 0.16, 0.80))
        # header shimmer
        shim_w = w * 0.18
        self._draw_rect(x + shimmer_x * (w - shim_w), y, shim_w, 86.0, (1.0, 1.0, 1.0, 0.04 + pulse_fast * 0.03))
        # triple separator bar
        bar_a = 0.60 + pulse_slow * 0.22
        self._draw_rect(x, y + 80.0, w, 2.0, (1.0, 0.62, 0.20, bar_a * 0.5))
        self._draw_rect(x, y + 83.0, w, 4.0, (1.0, 0.62, 0.20, bar_a))
        self._draw_rect(x, y + 88.0, w, 1.0, (1.0, 0.62, 0.20, bar_a * 0.4))
        # title — inverse pulse
        title_a = 0.86 + (1.0 - pulse_med) * 0.14
        title_str = 'UNICORN VIZ - HELP'
        title_scale = 2.95 * help_scale
        self._draw_text(
            title_str,
            x + (w - len(title_str) * 8.0 * title_scale) * 0.5,
            y + 10.0,
            scale=title_scale,
            color=(0.12, 0.98, 1.0, title_a),
        )
        # Centered live date/time replacing former ProjectM preset labels.
        _now = datetime.datetime.now()
        dt_str = _now.strftime('<<  %a  %d %b %Y  //  %H:%M:%S  >>')
        dt_a = 0.78 + pulse_slow * 0.18
        dt_scale = 1.72 * help_scale
        self._draw_text(
            dt_str,
            x + (w - len(dt_str) * 8.0 * dt_scale) * 0.5,
            y + 56.0,
            scale=dt_scale,
            color=(0.90, 1.0, 0.82, dt_a),
        )

        icon_band_y = y + 100.0
        icon_band_h = self._render_help_icon_rail(x, icon_band_y, w, help_scale)
        content_top_y = icon_band_y + icon_band_h + 14.0

        # ── left/right content panes ──────────────────────────────────────
        left_x = x + 14.0
        left_y = content_top_y
        left_w = w * 0.64
        left_h = (y + h) - left_y - 10.0

        right_x = left_x + left_w + 10.0
        right_y = left_y
        right_w = x + w - right_x - 14.0
        right_h = left_h

        # left pane: dark bg + left orange bar
        self._draw_rect(left_x, left_y, left_w, left_h, (0.02, 0.07, 0.11, 0.62))
        self._draw_rect(left_x, left_y, 5.0, left_h, (1.0, 0.62, 0.20, 0.68 + pulse_med * 0.18))
        # right pane: dark bg + right teal bar
        self._draw_rect(right_x, right_y, right_w, right_h, (0.02, 0.09, 0.12, 0.62))
        self._draw_rect(right_x + right_w - 5.0, right_y, 5.0, right_h, (0.10, 0.94, 1.0, 0.60 + pulse_slow * 0.18))
        # scan line across left pane
        scan_h_lp = math.fmod(t * 0.28, 1.0)
        scan_y_lp = left_y + scan_h_lp * left_h
        self._draw_rect(left_x, scan_y_lp - 1.0, left_w, 2.0, (0.10, 0.94, 1.0, 0.04))
        self._draw_rect(left_x, scan_y_lp,        left_w, 1.0, (0.10, 0.94, 1.0, 0.14))

        # ── bottom segmented bar ──────────────────────────────────────────
        seg_n = 12;  seg_gap = 4.0
        seg_w_b = (w - (seg_n - 1) * seg_gap) / seg_n
        for s in range(seg_n):
            seg_a = 0.28 + 0.22 * (0.5 + 0.5 * math.sin(t * 1.8 + s * 0.52))
            self._draw_rect(x + s * (seg_w_b + seg_gap), y + h - 8.0, seg_w_b, 8.0, (0.12, 0.96, 1.0, seg_a))
        self._draw_rect(x, y + h - 10.0, w, 2.0, (0.10, 0.94, 1.0, 0.44 + pulse_med * 0.18))

        self._draw_help_section_content(x, y, w, h, help_scale, content_top_y)
        if self._tooltips_enabled and self._rail_tooltip_tracker is not None:
            tip = self._rail_tooltip_tracker.tick()
            anchor = self._rail_tooltip_tracker.anchor
            if tip is not None and anchor is not None:
                self._draw_tooltip_bubble(tip.text, anchor)

    def _render_help_icon_rail(self, x: float, y: float, w: float, help_scale: float) -> float:
        """Draw the centered help icon rail and return its rendered height."""
        entries = self._help_icon_entries()
        if not entries:
            return 0.0

        icon_px = 152.0 if self._help_icon_asset_bucket == '152px' else 76.0
        band_h = max(icon_px + 20.0, 72.0 * help_scale)
        gap = max(14.0, 16.0 * help_scale)
        cell_w = icon_px
        cell_h = icon_px

        total_w = len(entries) * cell_w + max(0, len(entries) - 1) * gap
        start_x = round(x + max(0.0, (w - total_w) * 0.5))
        rail_y = round(y + max(0.0, (band_h - cell_h) * 0.5) - 10.0)

        self._draw_rect(round(x + 20.0), round(y + band_h - 4.0), round(w - 40.0), 2.0, (1.0, 0.70, 0.24, 0.42))

        for idx, entry in enumerate(entries):
            cell_x = round(start_x + idx * (cell_w + gap))
            accent = self._help_icon_accent(entry)
            is_active = self._help_focus_region == 'icons' and idx == self._help_icon_focus_idx
            pulse = 0.5 + 0.5 * math.sin(self._help_pulse_t * 4.2 + idx * 0.63)
            glow_a = 0.12 + pulse * 0.14 if is_active else 0.05 + pulse * 0.05
            border_a = 0.62 if is_active else 0.28

            self._draw_rect(cell_x - 2.0, rail_y - 2.0, cell_w + 4.0, cell_h + 4.0, (accent[0], accent[1], accent[2], glow_a))
            self._draw_rect(cell_x, rail_y, cell_w, cell_h, (0.03 + accent[0] * 0.03, 0.05 + accent[1] * 0.05, 0.09 + accent[2] * 0.04, 0.72))
            self._draw_rect(cell_x, rail_y, cell_w, 3.0, (accent[0], accent[1], accent[2], 0.82))
            self._draw_rect(cell_x, rail_y + 2.0, cell_w, 4.0, (accent[0], accent[1], accent[2], 0.34 + pulse * 0.12))
            if is_active:
                self._draw_rect(cell_x - 1.0, rail_y - 1.0, cell_w + 2.0, cell_h + 2.0, (accent[0], accent[1], accent[2], border_a))

            icon_id = self._help_icon_image_id(entry)
            icon_tex = self._help_icon_textures.get(icon_id)
            icon_x = cell_x
            icon_y = rail_y + 1.0
            icon_size = icon_px
            if icon_tex is not None:
                icon_alpha = 1.0 if is_active else 0.94
                self._draw_icon_texture(icon_tex, icon_x, icon_y, icon_size, icon_size, alpha=icon_alpha)
            else:
                glyph = str(entry.get('glyph', ''))[:3].upper()
                glyph_scale = max(1.18, min(1.68, 1.42 * help_scale))
                glyph_w = len(glyph) * 8.0 * glyph_scale
                glyph_x = cell_x + (icon_px - glyph_w) * 0.5
                glyph_y = rail_y + (icon_px - 8.0 * glyph_scale) * 0.5 + 2.0
                self._draw_text(glyph, glyph_x, glyph_y, scale=glyph_scale, color=(1.0, 1.0, 1.0, 0.98))

        return band_h

    def _draw_tooltip_bubble(self, text: str, anchor: tuple[float, float]) -> None:
        """Draw the shared tooltip bubble at a cursor anchor, on-screen clamped.

        Same visual language as the original help-icon bubble (dark panel,
        teal top edge, violet bottom edge), generalized to any anchor and
        wrapped up to a few lines for longer modal texts.
        """
        body = str(text or '').strip()
        if not body:
            return
        scale = 1.48
        char_w = 8.0 * scale
        lines = wrap_tooltip_text(body, None, 420, lambda s: len(s) * char_w)
        if not lines:
            return
        line_h = 8.0 * scale + 6.0
        box_w = max(len(line) for line in lines) * char_w + 20.0
        box_h = len(lines) * line_h + 12.0
        tip_x = float(anchor[0]) + 14.0
        tip_y = float(anchor[1]) + 20.0
        if tip_y + box_h > self._height - 8.0:
            tip_y = float(anchor[1]) - box_h - 10.0
        tip_x = max(8.0, min(tip_x, self._width - box_w - 8.0))
        tip_y = max(8.0, tip_y)
        self._draw_rect(tip_x, tip_y, box_w, box_h, (0.03, 0.05, 0.08, 0.92))
        self._draw_rect(tip_x, tip_y, box_w, 2.0, (0.10, 0.94, 1.0, 0.72))
        self._draw_rect(tip_x, tip_y + box_h - 2.0, box_w, 2.0, (0.78, 0.38, 1.0, 0.68))
        for i, line in enumerate(lines):
            self._draw_text(line, tip_x + 10.0, tip_y + 8.0 + i * line_h, scale=scale, color=(0.96, 0.98, 1.0, 0.98))

    def _draw_help_section_content(self, x: float, y: float, w: float, h: float, help_scale: float, content_top_y: float) -> None:
        """Draw section cards and shortcut map in the help panel content area."""
        hp = self._help_pulse_t

        left_x = x + 14.0
        left_y = content_top_y
        left_w = w * 0.64
        left_h = (y + h) - left_y - 10.0
        right_x = left_x + left_w + 10.0
        right_y = left_y
        right_w = x + w - right_x - 14.0
        right_h = left_h

        # ── tab bar (paginates sections so a fully-loaded drop-in dir stays
        # navigable instead of overflowing silently off the bottom) ─────────
        groups = self._help_tab_groups()
        self._help_tab_idx = max(0, min(self._help_tab_idx, len(groups) - 1))
        if len(groups) > 1:
            tab_bar_h = 34.0 * help_scale
            self._draw_help_tab_bar(left_x, left_y, left_w, tab_bar_h, groups, help_scale)
            left_y += tab_bar_h + 6.0
            left_h -= tab_bar_h + 6.0
        else:
            self._help_tab_rects = []

        # ── section cards ─────────────────────────────────────────────────
        sections = groups[self._help_tab_idx] if groups else []
        if sections:
            self._help_focus_idx = max(0, min(self._help_focus_idx, len(sections) - 1))

        card_title_scale = 2.30 * help_scale
        item_scale = 2.10 * help_scale
        card_line_h = 8 * item_scale + 2.0
        card_pad = 8.0

        col_gap = 10.0
        col_w = (left_w - 14.0 - 3 * col_gap) / 2.0
        col_x = [left_x + 14.0 + col_gap, left_x + 14.0 + col_gap * 2 + col_w]
        col_y = [left_y + 8.0, left_y + 8.0]
        col_max_y = left_y + left_h - 10.0

        avail_text_w = col_w - card_pad * 2
        title_line_h = 8 * card_title_scale + 2.0
        self._help_item_page_rects = []

        for sec_idx, (section, entries) in enumerate(sections):
            if not entries:
                continue
            accent = self._help_theme_color(section)
            collapsed = self._help_collapsed.get(section, False)
            marker = '>' if (self._help_focus_region == 'sections' and sec_idx == self._help_focus_idx) else ' '
            icon = '+' if collapsed else '-'
            header_text = f'{marker}{sec_idx + 1}. {icon} {section.upper()} ({len(entries)})'
            header_lines = self._wrap_plain_text(header_text, avail_text_w, card_title_scale)

            body_rows = self._help_section_body_rows(section, entries, collapsed, avail_text_w, item_scale)

            section_h = (
                card_pad * 2
                + len(header_lines) * title_line_h
                + 4
                + len(body_rows) * card_line_h
            )
            idx = 0 if col_y[0] <= col_y[1] else 1
            if col_y[idx] + section_h > col_max_y:
                other = 1 - idx
                if col_y[other] + section_h <= col_max_y:
                    idx = other
                else:
                    continue
            sx2 = col_x[idx]
            sy2 = col_y[idx]
            if sec_idx == self._help_focus_idx:
                pulse = 0.5 + 0.5 * math.sin(hp * 5.4)
                glow_a = 0.16 + pulse * 0.20
                edge_a = 0.34 + pulse * 0.26
                self._draw_rect(sx2 - 4.0, sy2 - 4.0, col_w + 8.0, section_h + 8.0, (accent[0], accent[1], accent[2], glow_a))
                self._draw_rect(sx2 - 2.0, sy2 - 2.0, col_w + 4.0, section_h + 4.0, (accent[0], accent[1], accent[2], edge_a))
            self._draw_rect(sx2, sy2, col_w, section_h, (0.05 + accent[0] * 0.05, 0.08 + accent[1] * 0.06, 0.14 + accent[2] * 0.05, 0.62))
            self._draw_rect(sx2, sy2, col_w, 3.0, (accent[0], accent[1], accent[2], 0.78))
            yy = sy2 + card_pad
            for hline in header_lines:
                self._draw_text(hline, sx2 + card_pad, yy, scale=card_title_scale, color=(accent[0], accent[1], accent[2], 0.98))
                yy += title_line_h
            yy += 4
            entry_color = (0.78, 0.84, 0.92, 0.92) if collapsed else (
                0.80 + accent[0] * 0.20, 0.82 + accent[1] * 0.18, 0.84 + accent[2] * 0.16, 0.96
            )
            page_header_color = (1.0, 0.92, 0.58, 0.96)
            hint_color = (0.62, 0.72, 0.88, 0.78)
            for row in body_rows:
                if row['kind'] == 'page_header':
                    self._draw_text(row['text'], sx2 + card_pad, yy, scale=item_scale, color=page_header_color)
                    self._help_item_page_rects.append(
                        (section, row['page_index'], sx2 + card_pad, yy - 2.0, col_w - 2 * card_pad, card_line_h)
                    )
                elif row['kind'] == 'hint':
                    self._draw_text(row['text'], sx2 + card_pad, yy, scale=item_scale * 0.82, color=hint_color)
                else:
                    self._draw_text(row['text'], sx2 + card_pad, yy, scale=item_scale, color=entry_color)
                yy += card_line_h
            col_y[idx] += section_h + 8.0

        # ── right pane: tabbed (Effects / Post FX / Mouse) ──────────────────
        right_tabs = self._help_right_tabs()
        self._help_right_tab_idx = max(0, min(self._help_right_tab_idx, len(right_tabs) - 1))
        if len(right_tabs) > 1:
            right_tab_bar_h = 34.0 * help_scale
            self._draw_help_right_tab_bar(right_x, right_y, right_w, right_tab_bar_h, right_tabs, help_scale)
            right_y += right_tab_bar_h + 6.0
            right_h -= right_tab_bar_h + 6.0
        else:
            self._help_right_tab_rects = []

        active_right_tab = right_tabs[self._help_right_tab_idx] if right_tabs else 'Effects'

        if active_right_tab == 'Effects':
            rows = max(
                len(self._num_shortcuts),
                len(self._shift_shortcuts),
                len(self._ctrl_shortcuts),
                len(self._alt_shortcuts),
            )
            shortcut_title_scale = 1.85 * help_scale
            sec_scale = item_scale
            min_sec_scale = max(1.40, item_scale * 0.72)
            min_bottom_margin = 26.0

            half = right_w * 0.48
            # Columns are row-aligned in pairs ("1-0"+"SHIFT", then "CTRL"+"ALT"),
            # so a long effect name that wraps to 2 lines must push every row
            # below it down in *both* columns of its pair, not just its own cell.
            col1_avail = max(60.0, half - 20.0)
            col2_avail = max(60.0, right_w - half - 20.0)
            row_n = min(rows, 12)

            def _row_group(items_a: list[str], items_b: list[str], scale: float) -> tuple[list[list[str]], list[list[str]], list[int]]:
                wrapped_a = [
                    self._wrap_plain_text(items_a[i] if i < len(items_a) else '(none)', col1_avail, scale)
                    for i in range(row_n)
                ]
                wrapped_b = [
                    self._wrap_plain_text(items_b[i] if i < len(items_b) else '(none)', col2_avail, scale)
                    for i in range(row_n)
                ]
                counts = [max(len(wrapped_a[i]), len(wrapped_b[i])) for i in range(row_n)]
                return wrapped_a, wrapped_b, counts

            top = right_y + 10.0
            while sec_scale > min_sec_scale:
                sec_lh = 8 * sec_scale + 2.0
                _, _, top_counts = _row_group(self._num_shortcuts, self._shift_shortcuts, sec_scale)
                _, _, bottom_counts = _row_group(self._ctrl_shortcuts, self._alt_shortcuts, sec_scale)
                top_block_h = (8 * shortcut_title_scale + 3.0) + sum(top_counts) * sec_lh
                bottom_y = top + top_block_h + 28.0
                bottom_block_h = (8 * shortcut_title_scale + 3.0) + sum(bottom_counts) * sec_lh
                total_h = bottom_y + bottom_block_h
                if total_h <= right_y + right_h - min_bottom_margin:
                    break
                sec_scale -= 0.08

            sec_lh = 8 * sec_scale + 2.0
            num_lines, shift_lines, top_counts = _row_group(self._num_shortcuts, self._shift_shortcuts, sec_scale)
            ctrl_lines, alt_lines, bottom_counts = _row_group(self._ctrl_shortcuts, self._alt_shortcuts, sec_scale)

            def _row_offsets(counts: list[int]) -> list[float]:
                offsets: list[float] = []
                acc = 0
                for c in counts:
                    offsets.append(float(acc))
                    acc += c
                return offsets

            top_offsets = _row_offsets(top_counts)
            bottom_offsets = _row_offsets(bottom_counts)

            def _draw_shortcut_block(
                title: str, wrapped_items: list[list[str]], bx: float, by: float,
                offsets: list[float], color: tuple[float, float, float, float],
            ) -> None:
                self._draw_text(title, bx, by, scale=shortcut_title_scale, color=(0.96, 1.0, 0.70, 0.96))
                y0 = by + 8 * shortcut_title_scale + 3.0
                for i, lines in enumerate(wrapped_items):
                    yy = y0 + offsets[i] * sec_lh
                    for line in lines:
                        self._draw_text(line, bx, yy, scale=sec_scale, color=color)
                        yy += sec_lh

            top_block_h = (8 * shortcut_title_scale + 3.0) + sum(top_counts) * sec_lh
            bottom_y = top + top_block_h + 28.0
            _draw_shortcut_block('1-0',   num_lines,   right_x + 10.0, top,      top_offsets,    (0.82, 1.0,  0.9,  0.95))
            _draw_shortcut_block('SHIFT', shift_lines, right_x + half, top,      top_offsets,    (0.92, 0.86, 1.0,  0.95))
            _draw_shortcut_block('CTRL',  ctrl_lines,  right_x + 10.0, bottom_y, bottom_offsets, (0.84, 0.94, 1.0,  0.95))
            _draw_shortcut_block('ALT',   alt_lines,   right_x + half, bottom_y, bottom_offsets, (1.0,  0.92, 0.82, 0.95))

            if self._unmapped_effects:
                self._draw_text(
                    f"Extra effects (no direct key): {', '.join(self._unmapped_effects)}",
                    right_x + 10.0,
                    right_y + right_h - 20.0,
                    scale=1.16,
                    color=(1.0, 0.62, 0.62, 0.94),
                )

        elif active_right_tab in ('Post FX', 'Mouse'):
            entries = self._postfx_help_entries if active_right_tab == 'Post FX' else self._mouse_help_entries
            title_scale = 1.85 * help_scale
            title_color = (0.98, 0.95, 0.72, 0.96) if active_right_tab == 'Post FX' else (0.72, 0.98, 0.95, 0.96)
            entry_color = (0.96, 0.88, 0.76, 0.96) if active_right_tab == 'Post FX' else (0.80, 0.96, 0.94, 0.96)
            self._draw_text(active_right_tab.upper(), right_x + 10.0, right_y + 10.0, scale=title_scale, color=title_color)
            py = right_y + 10.0 + 8 * title_scale + 8.0
            avail = max(60.0, right_w - 20.0)
            for key, desc in entries:
                for line in self._wrap_help_entry(key, desc, avail, item_scale, key_width=16):
                    self._draw_text(line, right_x + 10.0, py, scale=item_scale, color=entry_color)
                    py += 8 * item_scale + 2.0

    def _draw_help_tab_bar(
        self,
        left_x: float,
        left_y: float,
        left_w: float,
        bar_h: float,
        groups: list[list[tuple[str, list[tuple[str, str]]]]],
        help_scale: float,
    ) -> None:
        """Draw the help-section tab strip; one tab per page of sections."""
        self._help_tab_rects = []
        n = len(groups)
        gap = 6.0
        tab_w = min(64.0 * help_scale, (left_w - (n - 1) * gap) / n)
        tab_scale = 1.7 * help_scale
        active = self._help_tab_idx
        tx = left_x
        for i in range(n):
            accent = self.DYNAMIC_THEME_CYCLE[i % len(self.DYNAMIC_THEME_CYCLE)]
            is_active = i == active
            if is_active:
                bg = (accent[0] * 0.30, accent[1] * 0.30, accent[2] * 0.30, 0.90)
            else:
                bg = (0.06, 0.10, 0.18, 0.68)
            self._draw_rect(tx, left_y, tab_w, bar_h, bg)
            if is_active:
                self._draw_rect(tx, left_y + bar_h - 3.0, tab_w, 3.0, (accent[0], accent[1], accent[2], 0.95))
            label = str(i + 1)
            tcol = (1.0, 0.96, 0.68, 1.0) if is_active else (0.72, 0.82, 0.94, 0.85)
            self._draw_text(
                label,
                tx + (tab_w - len(label) * 8.0 * tab_scale) * 0.5,
                left_y + (bar_h - 8 * tab_scale) * 0.5,
                scale=tab_scale,
                color=tcol,
            )
            self._help_tab_rects.append((i, tx, left_y, tab_w, bar_h))
            tx += tab_w + gap

        hint = f'Page {active + 1}/{n} — PageUp/PageDown'
        hint_scale = 1.5 * help_scale
        self._draw_text(
            hint,
            tx + 10.0,
            left_y + (bar_h - 8 * hint_scale) * 0.5,
            scale=hint_scale,
            color=(0.70, 0.86, 1.0, 0.82),
        )

    def _draw_help_right_tab_bar(
        self,
        x: float,
        y: float,
        w: float,
        bar_h: float,
        tabs: list[str],
        help_scale: float,
    ) -> None:
        """Draw the right pane's Effects / Post FX / Mouse tab strip (click to switch)."""
        self._help_right_tab_rects = []
        n = len(tabs)
        gap = 6.0
        tab_w = min(140.0 * help_scale, (w - (n - 1) * gap) / n)
        tab_scale = 1.7 * help_scale
        active = self.help_right_tab_index()
        tx = x
        for i, label in enumerate(tabs):
            accent = self.DYNAMIC_THEME_CYCLE[i % len(self.DYNAMIC_THEME_CYCLE)]
            is_active = i == active
            if is_active:
                bg = (accent[0] * 0.30, accent[1] * 0.30, accent[2] * 0.30, 0.90)
            else:
                bg = (0.06, 0.10, 0.18, 0.68)
            self._draw_rect(tx, y, tab_w, bar_h, bg)
            if is_active:
                self._draw_rect(tx, y + bar_h - 3.0, tab_w, 3.0, (accent[0], accent[1], accent[2], 0.95))
            display = label.upper()
            tcol = (1.0, 0.96, 0.68, 1.0) if is_active else (0.72, 0.82, 0.94, 0.85)
            self._draw_text(
                display,
                tx + (tab_w - len(display) * 8.0 * tab_scale) * 0.5,
                y + (bar_h - 8 * tab_scale) * 0.5,
                scale=tab_scale,
                color=tcol,
            )
            self._help_right_tab_rects.append((i, tx, y, tab_w, bar_h))
            tx += tab_w + gap

    def _iter_help_sections(self) -> list[tuple[str, list[tuple[str, str]]]]:
        """Return merged core + dynamic help sections in render order."""
        sections: list[tuple[str, list[tuple[str, str]]]] = []
        for section, entries in self.CORE_HELP_SECTIONS:
            sections.append((section, list(entries)))

        # All drop-in sections render after system sections, alphabetized.
        dropin_sections: dict[str, list[tuple[str, str]]] = {
            section: list(entries)
            for section, entries in self.DROPIN_HELP_SECTIONS
        }
        for section in self._dynamic_help_order:
            entries = self._dynamic_help_sections.get(section, [])
            if not entries:
                continue
            bucket = dropin_sections.setdefault(section, [])
            for entry in entries:
                if entry not in bucket:
                    bucket.append(entry)

        for section in sorted(dropin_sections, key=lambda s: s.lower()):
            entries = dropin_sections.get(section, [])
            if entries:
                sections.append((section, list(entries)))
        return sections

    def _help_item_pages(self, entries: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
        """Chunk a section's entries into pages of <= HELP_MAX_ITEMS_PER_SECTION.

        A section stays a single card/heading either way; when it has more
        entries than the cap, the *items* are paged into an inner accordion
        (see _help_section_body_rows) instead of splitting into separate
        top-level sections.
        """
        cap = self.HELP_MAX_ITEMS_PER_SECTION
        if not entries:
            return [[]]
        return [entries[i:i + cap] for i in range(0, len(entries), cap)]

    def _help_item_page_count(self, entries: list[tuple[str, str]]) -> int:
        """Return how many item-pages a section's entries chunk into (>= 1)."""
        return len(self._help_item_pages(entries)) if entries else 1

    def _help_section_body_rows(
        self,
        section: str,
        entries: list[tuple[str, str]],
        collapsed: bool,
        avail_text_w: float,
        item_scale: float,
    ) -> list[dict]:
        """Return the drawable rows for a section's body (below its header).

        Each row is ``{'kind': 'text', 'text': str}``, a smaller-scale
        ``{'kind': 'hint', 'text': str}`` row (shown once, right under the
        header, only for multi-page sections), or a clickable page-header
        row ``{'kind': 'page_header', 'text': str, 'page_index': int}`` (see
        handle_help_mouse_click) — only one page's items are expanded at a
        time (accordion: opening one collapses whichever other page was open).
        """
        if collapsed:
            return [{'kind': 'text', 'text': '[collapsed]'}]

        pages = self._help_item_pages(entries)
        if len(pages) <= 1:
            rows: list[dict] = []
            for key, desc in entries:
                for line in self._wrap_help_entry(key, desc, avail_text_w, item_scale):
                    rows.append({'kind': 'text', 'text': line})
            return rows

        cap = self.HELP_MAX_ITEMS_PER_SECTION
        open_idx = max(0, min(self._help_item_page.get(section, 0), len(pages) - 1))
        hint_scale = item_scale * 0.82
        rows = [
            {'kind': 'hint', 'text': line}
            for line in self._wrap_plain_text('Press Enter to see more items', avail_text_w, hint_scale)
        ]
        for i, page in enumerate(pages):
            start = i * cap + 1
            end = start + len(page) - 1
            is_open = i == open_idx
            icon = '-' if is_open else '+'
            rows.append({
                'kind': 'page_header',
                'text': f'  {icon} Items {start}-{end}',
                'page_index': i,
            })
            if is_open:
                for key, desc in page:
                    for line in self._wrap_help_entry(key, desc, avail_text_w - 2.0, item_scale):
                        rows.append({'kind': 'text', 'text': '  ' + line})
        return rows

    def set_help_item_page(self, section: str, page_index: int) -> bool:
        """Open a specific item-page within ``section`` (closes any other)."""
        self._help_item_page[section] = max(0, int(page_index))
        return True

    def _help_tab_groups(self) -> list[list[tuple[str, list[tuple[str, str]]]]]:
        """Paginate merged help sections into tabs of <= HELP_SECTIONS_PER_TAB."""
        sections = self._iter_help_sections()
        if not sections:
            return [[]]
        size = self.HELP_SECTIONS_PER_TAB
        return [sections[i:i + size] for i in range(0, len(sections), size)]

    def _current_help_sections(self) -> list[tuple[str, list[tuple[str, str]]]]:
        """Return the section list for the active help tab."""
        groups = self._help_tab_groups()
        idx = max(0, min(self._help_tab_idx, len(groups) - 1))
        return groups[idx]

    def help_tab_count(self) -> int:
        """Return the number of help tabs (pages of <= HELP_SECTIONS_PER_TAB sections)."""
        return len(self._help_tab_groups())

    def help_tab_index(self) -> int:
        """Return the active help tab index, clamped to the current tab count."""
        return max(0, min(self._help_tab_idx, self.help_tab_count() - 1))

    def set_help_tab(self, index: int) -> bool:
        """Select a help tab by index (clamped); resets section focus to the top."""
        n = self.help_tab_count()
        if n <= 0:
            return False
        self._help_tab_idx = max(0, min(int(index), n - 1))
        self._help_focus_idx = 0
        return True

    def move_help_tab(self, delta: int) -> bool:
        """Move the active help tab by delta (wraps); resets section focus to the top."""
        n = self.help_tab_count()
        if n <= 1:
            return False
        self._help_tab_idx = (self._help_tab_idx + int(delta)) % n
        self._help_focus_idx = 0
        return True

    def _help_right_tabs(self) -> list[str]:
        """Return the right-pane tab names.

        'Effects' (the live 1-40 hotkey shortcut map) is always present.
        'Post FX' and 'Mouse' only appear when a drop-in has actually
        registered entries for them (e.g. no postfx-01 drop-in installed
        means neither tab exists at all, rather than showing an empty page).
        """
        tabs = ['Effects']
        if self._postfx_help_entries:
            tabs.append('Post FX')
        if self._mouse_help_entries:
            tabs.append('Mouse')
        return tabs

    def help_right_tab_count(self) -> int:
        """Return the number of right-pane tabs (always >= 1)."""
        return len(self._help_right_tabs())

    def help_right_tab_index(self) -> int:
        """Return the active right-pane tab index, clamped to the current count."""
        return max(0, min(self._help_right_tab_idx, self.help_right_tab_count() - 1))

    def help_right_tab_name(self) -> str:
        """Return the active right-pane tab's name."""
        tabs = self._help_right_tabs()
        return tabs[self.help_right_tab_index()] if tabs else 'Effects'

    def set_help_right_tab(self, index: int) -> bool:
        """Select a right-pane tab by index (clamped)."""
        n = self.help_right_tab_count()
        if n <= 0:
            return False
        self._help_right_tab_idx = max(0, min(int(index), n - 1))
        return True

    def move_help_right_tab(self, delta: int) -> bool:
        """Move the active right-pane tab by delta (wraps)."""
        n = self.help_right_tab_count()
        if n <= 1:
            return False
        self._help_right_tab_idx = (self._help_right_tab_idx + int(delta)) % n
        return True

    def move_help_page(self, delta: int) -> bool:
        """Move PageUp/PageDown through a single combined left+right tab
        sequence instead of both panes independently.

        PageDown: left tab 1 -> ... -> left tab N -> right tab 1 -> ... ->
        right tab M -> wraps back to left tab 1. PageUp is the exact
        reverse (left tab 1 -> right tab M -> ... -> right tab 1 -> left
        tab N -> ...). Only one pane's displayed tab changes per keypress;
        the other pane stays exactly where it was left.

        Returns False only when neither pane has more than one tab (nothing
        to page through at all), so the keypress can fall through to a
        drop-in bound to the same keys.
        """
        n = self.help_tab_count()
        m = self.help_right_tab_count()
        if n <= 1 and m <= 1:
            return False

        forward = delta > 0
        left_changed = False
        if forward:
            if self._help_active_pane == 'left':
                if self._help_tab_idx < n - 1:
                    self._help_tab_idx += 1
                    left_changed = True
                else:
                    self._help_active_pane = 'right'
                    self._help_right_tab_idx = 0
            else:
                if self._help_right_tab_idx < m - 1:
                    self._help_right_tab_idx += 1
                else:
                    self._help_active_pane = 'left'
                    self._help_tab_idx = 0
                    left_changed = True
        else:
            if self._help_active_pane == 'left':
                if self._help_tab_idx > 0:
                    self._help_tab_idx -= 1
                    left_changed = True
                else:
                    self._help_active_pane = 'right'
                    self._help_right_tab_idx = m - 1
            else:
                if self._help_right_tab_idx > 0:
                    self._help_right_tab_idx -= 1
                else:
                    self._help_active_pane = 'left'
                    self._help_tab_idx = n - 1
                    left_changed = True

        if left_changed:
            self._help_focus_idx = 0
        return True

    def _help_text_max_chars(self, avail_w: float, scale: float) -> int:
        """Return how many glyphs at ``scale`` fit within ``avail_w``."""
        char_w = float(self._glyph_w) * self._font_scale_norm * scale
        if char_w <= 0:
            return 999
        return max(4, int(avail_w / char_w))

    @staticmethod
    def _wrap_words_two_budget(words: list[str], first_avail: int, cont_avail: int) -> list[str]:
        """Greedy-wrap ``words`` into lines; line 1 uses ``first_avail`` chars,
        later lines ``cont_avail``. Words are never split or dropped — a
        single word still longer than its line's budget is kept whole on its
        own line (a bounded overflow, not a truncation)."""
        if not words:
            return ['']
        lines: list[str] = []
        cur = ''
        avail = first_avail
        for word in words:
            candidate = f'{cur} {word}'.strip()
            if cur and len(candidate) > avail:
                lines.append(cur)
                cur = word
                avail = cont_avail
            else:
                cur = candidate
        lines.append(cur)
        return lines

    def _wrap_plain_text(self, text: str, avail_w: float, scale: float) -> list[str]:
        """Word-wrap ``text`` to fit ``avail_w``; never truncates — long single
        words that still overflow are placed on their own line as-is rather
        than cut off."""
        max_chars = self._help_text_max_chars(avail_w, scale)
        return self._wrap_words_two_budget(text.split(), max_chars, max_chars)

    def _wrap_help_entry(
        self, key: str, desc: str, avail_w: float, scale: float, key_width: int = 12,
    ) -> list[str]:
        """Word-wrap a help (key, description) row to fit ``avail_w``.

        The key starts the first line (padded to ``key_width`` chars);
        continuation lines hang-indent under the description so a long
        description reads as a wrapped paragraph instead of overflowing the
        section card or restarting at the key column. If the key itself is
        too wide for the column at this scale (very narrow columns only),
        it is wrapped too rather than left to overflow.
        """
        max_chars = self._help_text_max_chars(avail_w, scale)
        key_col = key_width + 1
        indent_w = min(key_col, max(0, max_chars - 1))
        indent = ' ' * indent_w

        if len(key) + 1 > max_chars:
            key_lines = self._wrap_words_two_budget(key.split() or [key], max_chars, max_chars)
            desc_avail = max(4, max_chars - indent_w)
            desc_lines = self._wrap_words_two_budget(desc.split() or [''], desc_avail, desc_avail)
            return key_lines + [indent + line for line in desc_lines]

        key_padded = f'{key:<{key_width}}' if len(key) < key_width else key
        prefix = f'{key_padded} '
        first_avail = max(4, max_chars - len(prefix))
        cont_avail = max(4, max_chars - indent_w)
        body = self._wrap_words_two_budget(desc.split() or [''], first_avail, cont_avail)
        return [prefix + body[0]] + [indent + line for line in body[1:]]

    def _help_theme_color(self, section: str) -> tuple[float, float, float]:
        """Return accent color for a help section."""
        base = self.HELP_SECTION_THEMES.get(section)
        if base is not None:
            return base
        # Deterministic fallback for drop-in sections.
        idx = abs(hash(section)) % len(self.DYNAMIC_THEME_CYCLE)
        return self.DYNAMIC_THEME_CYCLE[idx]

    def register_help_entries(self, entries: list[tuple[str, str, str] | dict]) -> None:
        """Register help entries discovered from effects/drop-ins.

        Each entry may be:
        - (section, key, description)
        - {'section': str, 'key': str, 'description': str}
        """
        self._dynamic_help_sections = {}
        self._dynamic_help_order = []
        self._postfx_help_entries = []
        self._mouse_help_entries = []

        for item in entries:
            section = ''
            key = ''
            desc = ''
            if isinstance(item, dict):
                section = str(item.get('section', '')).strip()
                key = str(item.get('key', '')).strip()
                desc = str(item.get('description', item.get('desc', item.get('action', '')))).strip()
            elif isinstance(item, (tuple, list)) and len(item) >= 3:
                section = str(item[0]).strip()
                key = str(item[1]).strip()
                desc = str(item[2]).strip()

            if not (section and key and desc):
                continue

            section_lower = section.strip().lower()
            if section_lower == 'post fx':
                entry = (key, desc)
                if entry not in self._postfx_help_entries:
                    self._postfx_help_entries.append(entry)
                continue
            if section_lower == 'mouse':
                entry = (key, desc)
                if entry not in self._mouse_help_entries:
                    self._mouse_help_entries.append(entry)
                continue

            bucket = self._dynamic_help_sections.setdefault(section, [])
            entry = (key, desc)
            if entry not in bucket:
                bucket.append(entry)
            if section not in self._dynamic_help_order:
                self._dynamic_help_order.append(section)

        # Keep collapse state for known sections, default to expanded.
        valid = [name for name, _entries in self._iter_help_sections()]
        default_expanded = {'Help Usage', 'Basics', 'Playback'}
        self._help_collapsed = {k: v for k, v in self._help_collapsed.items() if k in valid}
        for name in valid:
            if name not in self._help_collapsed:
                # Start with only the top three core sections expanded.
                self._help_collapsed[name] = name not in default_expanded
        self._help_item_page = {k: v for k, v in self._help_item_page.items() if k in valid}

        n_tabs = self.help_tab_count()
        if n_tabs:
            self._help_tab_idx = max(0, min(self._help_tab_idx, n_tabs - 1))
        cur = self._current_help_sections()
        self._help_focus_idx = max(0, min(self._help_focus_idx, len(cur) - 1)) if cur else 0

        right_tabs = self._help_right_tabs()
        self._help_right_tab_idx = max(0, min(self._help_right_tab_idx, len(right_tabs) - 1))

    def _help_icon_entries(self) -> list[dict[str, object]]:
        """Return the static help icon entries."""
        return list(self.HELP_ICON_ENTRIES)

    def _help_icon_accent(self, entry: dict[str, object]) -> tuple[float, float, float]:
        accent = entry.get('accent', (0.9, 0.9, 0.9))
        if isinstance(accent, tuple) and len(accent) == 3:
            return float(accent[0]), float(accent[1]), float(accent[2])
        return (0.9, 0.9, 0.9)

    def help_focus_region(self) -> str:
        """Return the active help focus region."""
        return self._help_focus_region

    def help_icon_count(self) -> int:
        """Return the number of help icons available in the rail."""
        return len(self.HELP_ICON_ENTRIES)

    def toggle_help_focus_region(self) -> bool:
        """Toggle focus between the help section list and icon rail."""
        if not self._show_help:
            return False
        self._help_focus_region = 'icons' if self._help_focus_region == 'sections' else 'sections'
        return True

    def move_help_icon_focus(self, delta: int) -> bool:
        """Move focus within the help icon rail."""
        n = self.help_icon_count()
        if n <= 0:
            return False
        self._help_icon_focus_idx = (self._help_icon_focus_idx + delta) % n
        self._help_focus_region = 'icons'
        return True

    def move_help_focus_active(self, delta: int) -> bool:
        """Move focus in whichever help region is currently active."""
        if self._help_focus_region == 'icons':
            return self.move_help_icon_focus(delta)
        return self.move_help_focus(delta)

    def activate_help_focus_item(self) -> bool:
        """Activate the currently-focused help item.

        Phase 1 keeps icon activation local and non-networked.
        """
        if self._help_focus_region == 'icons':
            entries = self._help_icon_entries()
            if not entries:
                return False
            idx = max(0, min(self._help_icon_focus_idx, len(entries) - 1))
            entry = entries[idx]
            self._queue_help_icon_action(entry)
            return True
        return self.toggle_help_focus_section()

    def handle_help_mouse_click(self, x: float, y: float) -> bool:
        """Handle mouse clicks on the help tab bars, item-page accordion rows, or icon rail."""
        for i, bx, by, bw, bh in self._help_tab_rects:
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return self.set_help_tab(i)
        for section, page_idx, bx, by, bw, bh in self._help_item_page_rects:
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return self.set_help_item_page(section, page_idx)
        for i, bx, by, bw, bh in self._help_right_tab_rects:
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return self.set_help_right_tab(i)
        idx = self._help_icon_hit_test(x, y)
        if idx < 0:
            return False
        entries = self._help_icon_entries()
        if not entries:
            return False
        self._help_focus_region = 'icons'
        self._help_icon_focus_idx = idx
        if self._rail_tooltip_tracker is not None:
            self._rail_tooltip_tracker.notify_click()
        self._queue_help_icon_action(entries[idx])
        return True

    def _queue_help_icon_action(self, entry: dict[str, object]) -> None:
        """Queue a normalized icon action payload for app-level dispatch."""
        self._pending_help_icon_action = {
            'id': str(entry.get('id', '') or '').strip(),
            'label': str(entry.get('label', '') or '').strip(),
            'description': str(entry.get('description', '') or '').strip(),
            'action_kind': str(entry.get('action_kind', 'placeholder') or 'placeholder').strip(),
            'target': str(entry.get('target', '') or '').strip(),
            'message': str(entry.get('message', '') or '').strip(),
        }

    def pop_help_icon_action(self) -> dict[str, str] | None:
        """Return and clear the next pending help icon action payload."""
        payload = self._pending_help_icon_action
        self._pending_help_icon_action = None
        return payload

    def note_help_activity(self) -> None:
        """Reset help auto-hide timer after keyboard interaction."""
        if self._show_help:
            self._help_timer = 60.0

    @property
    def help_visible(self) -> bool:
        return self._show_help

    @property
    def name_overlay_visible(self) -> bool:
        return self._show_name

    @property
    def audio_selector_visible(self) -> bool:
        return self._show_audio

    @property
    def midi_selector_visible(self) -> bool:
        return self._show_midi

    @property
    def system_monitor_modal_visible(self) -> bool:
        return self._show_system_monitor_modal

    @property
    def controller_help_modal_visible(self) -> bool:
        return self._show_controller_help_modal

    @property
    def projectm_manager_visible(self) -> bool:
        return self._show_projectm_manager

    @property
    def webcam_editor_modal_visible(self) -> bool:
        return self._show_webcam_editor_modal

    def modal_snapshot(self) -> dict[str, object]:
        """Return active modal state for alternate render surfaces.

        Priority mirrors render order so only one modal is active at a time.
        """
        if self._show_projectm_manager:
            selected = self.get_projectm_selected_preset()
            presets = self.projectm_filtered_presets()
            return {
                'type': 'projectm_manager',
                'title': 'PROJECTM PRESET MANAGER',
                'search_query': self._projectm_browser.search_query,
                'category': self.get_projectm_selected_category(),
                'categories': self.projectm_categories(),
                'category_index': int(self.get_projectm_category_index()),
                'preset_index': int(self.get_projectm_preset_index()),
                'focus_pane': int(self._projectm_browser.focus_pane()),
                'entries': [
                    {
                        'display_name': str(entry.get('display_name', '')),
                        'pack_name': str(entry.get('pack_name', '')),
                        'path': str(entry.get('path', '')),
                        'enabled': bool(entry.get('enabled', False)),
                    }
                    for entry in presets
                ],
                'selected_name': str((selected or {}).get('display_name', '')),
                'selected_pack': str((selected or {}).get('pack_name', '')),
                'selected_path': str((selected or {}).get('path', '')),
            }
        if self._show_system_monitor_modal:
            return {
                'type': 'system_monitor',
                'title': 'SYSTEM MONITOR',
                'cpu': float(self._sysmon_cpu),
                'ram': float(self._sysmon_ram),
                'swap': float(self._sysmon_swap),
                'disk_mbs': float(self._sysmon_disk_mbs),
                'net_mbs': float(self._sysmon_net_mbs),
            }
        if self._show_controller_help_modal:
            return {
                'type': 'controller_help',
                'title': 'CONTROLLER HELP // APC MINI MK2',
                'device': 'akai_apc_mini_mk2',
                'context_slots': True,
            }
        if self._show_webcam_editor_modal:
            return {
                'type': 'webcam_editor',
                'title': 'WEBCAM EDITOR',
                'selected_index': int(self._webcam_editor_selected_idx),
                'devices': list(self._webcam_editor_devices),
                'image_state': dict(self._webcam_editor_state),
            }
        if self._show_audio:
            entries = self._audio_sources if self._audio_sources else ['(no sources available)']
            return {
                'type': 'audio_selector',
                'title': 'AUDIO SOURCE SELECT',
                'active_index': int(self._audio_current_idx),
                'selected_index': int(self._audio_selected_idx),
                'entries': list(entries),
                'viable_flags': list(self._audio_viable_flags),
            }
        if self._show_midi:
            entries = ['(none - disable MIDI)'] + list(self._midi_ports)
            return {
                'type': 'midi_selector',
                'title': 'MIDI DEVICE SELECT',
                'active_port': str(self._midi_current_port),
                'selected_index': int(self._midi_selected_idx),
                'entries': entries,
            }
        if self._show_help:
            sections_list = self._current_help_sections()
            focus = max(0, min(self._help_focus_idx, len(sections_list) - 1))
            return {
                'type': 'help_overlay',
                'title': 'HELP OVERLAY',
                'tab_index': self.help_tab_index(),
                'tab_count': self.help_tab_count(),
                'right_tab_index': self.help_right_tab_index(),
                'right_tab_name': self.help_right_tab_name(),
                'right_tabs': self._help_right_tabs(),
                'section_count': len(sections_list),
                'focus_section': sections_list[focus][0] if sections_list else '-',
                'focus_idx': focus,
                'sections': [
                    {
                        'name': name,
                        'collapsed': bool(self._help_collapsed.get(name, False)),
                        'entries': [{'key': k, 'desc': d} for k, d in entries],
                    }
                    for name, entries in sections_list
                ],
            }
        if self._show_name:
            return {
                'type': 'hud_overlay',
                'title': 'HUD OVERLAY',
                'effect': str(self._hud_state.get('effect', '-') or '-'),
                'fps': str(self._hud_state.get('fps', '-') or '-'),
                'display_mode': str(self._hud_state.get('display_mode', '-') or '-'),
            }
        return {}

    @property
    def projectm_manager_focus_pane(self) -> int:
        return self._projectm_browser.focus_pane()

    @property
    def flash_messages_enabled(self) -> bool:
        return self._flash_enabled

    def help_section_count(self) -> int:
        """Return the section count for the active help tab (not the full list)."""
        return len(self._current_help_sections())

    def _auto_close_multipage_section_if_leaving(self, new_index: int) -> None:
        """Collapse the currently-focused section when focus is about to
        move to a different one — but only if it's a multi-page (item-page
        accordion) section and currently expanded. Sections with <=
        HELP_MAX_ITEMS_PER_SECTION entries keep their independent
        expand/collapse state regardless of focus, same as before the
        accordion existed.
        """
        old_index = self._help_focus_idx
        if old_index == new_index:
            return
        sections = self._current_help_sections()
        if old_index < 0 or old_index >= len(sections):
            return
        name, entries = sections[old_index]
        if self._help_collapsed.get(name, False):
            return
        if self._help_item_page_count(entries) > 1:
            self._help_collapsed[name] = True

    def toggle_help_section(self, index: int) -> bool:
        """Toggle/advance the section at ``index`` (digit keys, Enter).

        - Collapsed -> expanded (opens its first item-page).
        - Expanded, multiple item-pages -> cycles to the next item-page
          (accordion; does not collapse the section).
        - Expanded, single item-page (<= HELP_MAX_ITEMS_PER_SECTION entries)
          -> collapsed, same as before this accordion existed.
        """
        sections = self._current_help_sections()
        if index < 0 or index >= len(sections):
            return False
        self._auto_close_multipage_section_if_leaving(index)
        name, entries = sections[index]
        self._help_focus_idx = index
        collapsed = self._help_collapsed.get(name, False)
        if collapsed:
            self._help_collapsed[name] = False
            self._help_item_page[name] = 0
            return True
        n_pages = self._help_item_page_count(entries)
        if n_pages > 1:
            current = self._help_item_page.get(name, 0)
            self._help_item_page[name] = (current + 1) % n_pages
            return True
        self._help_collapsed[name] = True
        return True

    def set_all_help_sections_collapsed(self, collapsed: bool) -> None:
        """Collapse/expand every section across every help tab."""
        for name, _entries in self._iter_help_sections():
            self._help_collapsed[name] = collapsed

    def move_help_focus(self, delta: int) -> bool:
        n = self.help_section_count()
        if n <= 0:
            return False
        new_idx = (self._help_focus_idx + delta) % n
        self._auto_close_multipage_section_if_leaving(new_idx)
        self._help_focus_idx = new_idx
        return True

    def toggle_help_focus_section(self) -> bool:
        return self.toggle_help_section(self._help_focus_idx)

    def set_effect_shortcuts(self, effects: list[type["BaseEffect"]]) -> None:
        """Build help overlay columns for plain, shifted, ctrl, and alt shortcuts."""
        self._num_shortcuts = []
        self._shift_shortcuts = []
        self._ctrl_shortcuts = []
        self._alt_shortcuts = []
        self._unmapped_effects = []

        names = [cls.NAME for cls in effects]
        for i, key in enumerate(self.NUM_KEYS):
            if i < len(names):
                self._num_shortcuts.append(f"{key} -> {names[i]}")
            else:
                self._num_shortcuts.append(f"{key} -> (none)")

        for i, key in enumerate(self.SHIFT_KEYS):
            idx = 10 + i
            if idx < len(names):
                self._shift_shortcuts.append(f"{key} -> {names[idx]}")
            else:
                self._shift_shortcuts.append(f"{key} -> (none)")

        for i, key in enumerate(self.CTRL_KEYS):
            idx = 20 + i
            if idx < len(names):
                self._ctrl_shortcuts.append(f"{key} -> {names[idx]}")
            else:
                self._ctrl_shortcuts.append(f"{key} -> (none)")

        for i, key in enumerate(self.ALT_KEYS):
            idx = 30 + i
            if idx < len(names):
                self._alt_shortcuts.append(f"{key} -> {names[idx]}")
            else:
                self._alt_shortcuts.append(f"{key} -> (none)")

        if len(names) > 40:
            self._unmapped_effects = names[40:]

    @property
    def unmapped_effects(self) -> list[str]:
        return list(self._unmapped_effects)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def flash_name(self, name: str, duration: float = 3.0) -> None:
        if not self._flash_enabled:
            return
        self._name_text = name
        self._flash_text = f">> {name}"
        self._flash_timer = duration

    def trigger_cta(self) -> None:
        """Advance to the next CTA slot and start the hype animation."""
        self._cta.trigger()

    def trigger_cta_custom(
        self,
        text: str,
        icon: str = '',
        duration: float | None = None,
    ) -> None:
        """Trigger a custom CTA message (used by streaming drop-in ownership)."""
        self._cta.trigger_custom(text, icon, duration)

    def flash_message(self, msg: str, duration: float = 2.0) -> None:
        if not self._flash_enabled:
            return
        msg_text = str(msg)
        msg_duration = float(duration)
        router = self._flash_router
        if callable(router):
            try:
                if bool(router(msg_text, msg_duration)):
                    return
            except Exception:
                pass
        self._flash_text = msg_text
        self._flash_timer = msg_duration

    def set_overlay_banner(
        self,
        enabled: bool,
        current_text: str,
        previous_text: str,
        hold_s: float,
        change_counter: int,
    ) -> None:
        """Set banner overlay state (provider-agnostic; used by any subsystem)."""
        self._banner_enabled = bool(enabled)
        self._banner_hold_s = max(1.0, float(hold_s))
        self._banner_current_text = str(current_text).strip()
        self._banner_previous_text = str(previous_text).strip()
        counter = int(change_counter)
        if not self._banner_enabled or not self._banner_current_text:
            self._banner_timer = 0.0
            self._banner_change_counter = counter
            return
        if counter != self._banner_change_counter:
            self._banner_change_counter = counter
            self._banner_timer = self._banner_hold_s + (self._banner_slide_s() * 2.0)

    def _banner_slide_s(self) -> float:
        """Duration of banner slide animation in seconds."""
        return 0.35

    def _render_banner(self) -> None:
        """Render the generic overlay banner (provider-agnostic)."""
        slide_s = self._banner_slide_s()
        timer = max(0.0, self._banner_timer)
        if timer <= 0.0:
            return

        enter_threshold = self._banner_hold_s + slide_s
        if timer > enter_threshold:
            phase = 1.0 - ((timer - enter_threshold) / slide_s)
        elif timer > slide_s:
            phase = 1.0
        else:
            phase = timer / slide_s
        phase = max(0.0, min(1.0, phase))

        bar_x = 16.0
        bar_w = max(320.0, self._width - 32.0)
        bar_h = 54.0
        top_offset = self._height * 0.05  # clear GNOME panels that don't auto-hide
        bar_y = -bar_h + phase * (bar_h + 12.0 + top_offset)
        bg_a = 0.85 * (0.65 + phase * 0.35)
        edge_a = 0.24 + phase * 0.52
        accent = (0.10, 0.94, 1.00)
        glow = (0.78, 0.38, 1.00)

        self._draw_rect(bar_x, bar_y, bar_w, bar_h, (0.03, 0.06, 0.10, bg_a))
        self._draw_rect(bar_x, bar_y, bar_w, 3.0, (accent[0], accent[1], accent[2], edge_a))
        self._draw_rect(bar_x, bar_y + bar_h - 3.0, bar_w, 3.0, (glow[0], glow[1], glow[2], edge_a * 0.72))
        self._draw_rect(bar_x, bar_y, 5.0, bar_h, (accent[0], accent[1], accent[2], 0.60 + phase * 0.24))
        self._draw_rect(bar_x + bar_w - 5.0, bar_y, 5.0, bar_h, (glow[0], glow[1], glow[2], 0.40 + phase * 0.22))

        title = self._banner_current_text
        previous = self._banner_previous_text
        char_w = float(self._glyph_w) * self._font_scale_norm * 1.85
        left_limit = max(24, int((bar_w * 0.60) / max(1.0, char_w)))
        right_limit = max(16, int((bar_w * 0.36) / max(1.0, char_w)))

        def _clip(text: str, limit: int) -> str:
            if len(text) <= limit:
                return text
            return text[: max(1, limit - 3)].rstrip() + '...'

        title = _clip(title, left_limit)
        previous = _clip(previous, right_limit)
        banner_a = 0.93 * (0.45 + phase * 0.55)
        banner_y = bar_y + 22.0
        self._draw_text(title, bar_x + 18.0, banner_y, scale=1.70, color=(0.14, 0.98, 0.94, banner_a))
        if previous:
            previous_w = len(previous) * char_w
            previous_x = bar_x + bar_w - 18.0 - previous_w
            self._draw_text(previous, previous_x, banner_y, scale=1.70, color=(0.96, 0.86, 1.0, banner_a * 0.96))

        bass = max(0.0, min(1.0, float(self._hud_state.get('bass', '0.00') or '0.0')))
        mid = max(0.0, min(1.0, float(self._hud_state.get('mid', '0.00') or '0.0')))
        treble = max(0.0, min(1.0, float(self._hud_state.get('treble', '0.00') or '0.0')))
        self._draw_audio_reactive_border_bulbs(
            bar_x,
            bar_y,
            bar_w,
            bar_h,
            bass,
            mid,
            treble,
            self._hud_t,
            speed_scale=0.5,
            size_scale=0.5,
        )

    def _rect_border_point(self, x: float, y: float, w: float, h: float, distance: float) -> tuple[float, float]:
        perim = 2.0 * (w + h)
        dist = distance % perim
        if dist < w:
            return x + dist, y
        dist -= w
        if dist < h:
            return x + w, y + dist
        dist -= h
        if dist < w:
            return x + w - dist, y + h
        dist -= w
        return x, y + h - dist

    def _neon_palette_rgb(self, phase: float) -> tuple[float, float, float]:
        palette = (
            (0.88, 0.30, 1.00),
            (0.14, 0.98, 1.00),
            (1.00, 0.28, 0.78),
        )
        weights = [
            max(0.0, math.sin(phase + 0.0)) ** 2,
            max(0.0, math.sin(phase + 2.09439510239)) ** 2,
            max(0.0, math.sin(phase + 4.18879020479)) ** 2,
        ]
        total = max(0.001, weights[0] + weights[1] + weights[2])
        return (
            (palette[0][0] * weights[0] + palette[1][0] * weights[1] + palette[2][0] * weights[2]) / total,
            (palette[0][1] * weights[0] + palette[1][1] * weights[1] + palette[2][1] * weights[2]) / total,
            (palette[0][2] * weights[0] + palette[1][2] * weights[1] + palette[2][2] * weights[2]) / total,
        )

    def _draw_audio_reactive_border_bulbs(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        bass: float,
        mid: float,
        treble: float,
        t: float,
        *,
        speed_scale: float = 1.0,
        size_scale: float = 1.0,
    ) -> None:
        bass = max(0.0, min(1.0, bass))
        mid = max(0.0, min(1.0, mid))
        treble = max(0.0, min(1.0, treble))
        speed_scale = max(0.05, float(speed_scale))
        size_scale = max(0.05, float(size_scale))

        wobble = 0.55 + 0.45 * math.sin(t * 3.1 * speed_scale)
        phase_a = math.fmod(t * (0.16 + treble * 0.05) * speed_scale + bass * 0.7, 1.0)
        phase_b = math.fmod(t * (0.14 + bass * 0.04) * speed_scale + 0.5 + mid * 0.4, 1.0)

        for idx, (orb_phase, orb_bias) in enumerate(((phase_a, 0.0), (phase_b, 1.3))):
            cx, cy = self._rect_border_point(x, y, w, h, orb_phase * 2.0 * (w + h))
            color = self._neon_palette_rgb(t * 1.6 * speed_scale + bass * 5.5 + orb_bias)
            radius = (7.0 + bass * 4.0 + mid * 2.0 + wobble * 1.5 + idx * 0.35) * size_scale
            outer_a = 0.10 + bass * 0.10 + wobble * 0.05
            mid_a = 0.25 + mid * 0.12 + wobble * 0.08
            core_a = 0.56 + treble * 0.18 + wobble * 0.12

            # Layered glow squares approximate a round, bulbous sprite while staying cheap.
            self._draw_rect(cx - radius * 2.0, cy - radius * 2.0, radius * 4.0, radius * 4.0, (color[0], color[1], color[2], outer_a))
            self._draw_rect(cx - radius * 1.25, cy - radius * 1.25, radius * 2.5, radius * 2.5, (color[0], color[1], color[2], mid_a))
            self._draw_rect(cx - radius * 0.70, cy - radius * 0.70, radius * 1.4, radius * 1.4, (1.0, 1.0, 1.0, core_a))

    def toggle_name_overlay(self) -> None:
        self._show_name = not self._show_name
        self._hud_timer = self._hud_timeout_s if (self._show_name and self._hud_auto_hide) else 0.0

    def set_hud_state(self, state: dict[str, str]) -> None:
        """Update the live HUD payload rendered by TAB overlay."""
        self._hud_state.update(state)

    def set_audio_waveform(self, wf: np.ndarray | None) -> None:
        """Store the current PCM waveform for the Spotify progress-bar visualization."""
        self._live_waveform = wf

    def set_system_monitor_audio_provider(
        self,
        provider: Callable[[], dict[str, float]] | None,
    ) -> None:
        """Set optional runtime provider for monitor frame/audio values."""
        self._system_monitor_audio_provider = provider

    def set_system_monitor_tweakables_provider(
        self,
        provider: Callable[[], dict[str, float | None]] | None,
    ) -> None:
        """Set optional runtime provider for monitor tweakable values."""
        self._system_monitor_tweakables_provider = provider

    def toggle_help(self) -> None:
        self._show_help = not self._show_help
        if self._show_help:
            self._help_focus_region = 'sections'
            self._help_focus_idx = 0
            self._help_icon_focus_idx = 0
        if self._rail_tooltip_tracker is not None:
            self._rail_tooltip_tracker.reset()
        self._help_timer = 60.0 if self._show_help else 0.0

    def toggle_flash_messages(self) -> bool:
        """Toggle flash-message notifications on/off; returns new state."""
        self._flash_enabled = not self._flash_enabled
        return self._flash_enabled

    def set_flash_messages_enabled(self, enabled: bool) -> None:
        """Set flash-message notification state explicitly."""
        self._flash_enabled = bool(enabled)

    def toggle_audio_selector(self) -> None:
        self._show_audio = not self._show_audio

    def toggle_midi_selector(self) -> None:
        self._show_midi = not self._show_midi

    def toggle_system_monitor_modal(self) -> None:
        self._show_system_monitor_modal = not self._show_system_monitor_modal

    def toggle_controller_help_modal(self) -> None:
        self._show_controller_help_modal = not self._show_controller_help_modal

    def register_controller_help_renderer(
        self, fn: 'Callable[[Overlays], None] | None',
    ) -> None:
        """Register a callable that draws the controller help modal.

        The callable receives this ``Overlays`` instance and must use the
        public ``draw_*`` / ``begin_panel`` methods to render its content.
        Pass ``None`` to remove a previously registered renderer.
        """
        self._controller_help_renderer = fn

    # ------------------------------------------------------------------
    # Public drawing API — for use by drop-in renderers
    # ------------------------------------------------------------------

    def draw_rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        color: tuple[float, float, float, float],
    ) -> None:
        """Draw a solid-color axis-aligned rectangle in screen pixels."""
        self._draw_rect(x, y, w, h, color)

    def draw_text(
        self,
        text: str,
        x: float,
        y: float,
        scale: float = 2.0,
        color: tuple[float, float, float, float] = (1.0, 1.0, 0.0, 1.0),
    ) -> None:
        """Draw CP437 bitmap text at ``(x, y)`` in screen pixels."""
        self._draw_text(text, x, y, scale, color)

    def draw_modal_underlay(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        alpha: float,
        pad: float = 0.0,
    ) -> None:
        """Draw a semi-transparent black underlay behind a panel region."""
        self._draw_modal_underlay(x, y, w, h, alpha, pad)

    def begin_panel(
        self,
        frac_w: float,
        max_w: float,
        frac_h: float,
        max_h: float,
        underlay_alpha: float = 0.58,
        underlay_pad: float = 10.0,
    ) -> tuple[float, float, float, float, float, float]:
        """Compute centred panel geometry, draw underlay, return (px, py, pw, ph, W, H)."""
        return self._begin_panel(frac_w, max_w, frac_h, max_h, underlay_alpha, underlay_pad)

    def draw_audio_reactive_border_bulbs(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        bass: float,
        mid: float,
        treble: float,
        t: float,
        *,
        speed_scale: float = 1.0,
        size_scale: float = 1.0,
    ) -> None:
        """Draw two animated neon orbs that travel the perimeter of a rect."""
        self._draw_audio_reactive_border_bulbs(x, y, w, h, bass, mid, treble, t, speed_scale=speed_scale, size_scale=size_scale)

    @property
    def hud_t(self) -> float:
        """Current HUD animation clock in seconds."""
        return self._hud_t

    @property
    def hud_audio_state(self) -> dict[str, str]:
        """Latest HUD audio payload (bass, mid, treble, bpm …)."""
        return self._hud_state

    def toggle_projectm_manager(self) -> None:
        self._show_projectm_manager = not self._show_projectm_manager

    def toggle_webcam_editor_modal(self) -> None:
        self._show_webcam_editor_modal = not self._show_webcam_editor_modal

    def set_recording_state(self, active: bool, elapsed_seconds: float = 0.0) -> None:
        self._recording_active = active
        self._recording_elapsed_seconds = elapsed_seconds if active else 0.0

    def render_live_recording_indicator(self) -> None:
        """Draw only the recording indicator for live display after frame capture."""
        self._render_recording_indicator()

    def resize(self, w: int, h: int) -> None:
        self._width = w
        self._height = h
        bucket = self._help_icon_bucket_for_width(w)
        if bucket != self._help_icon_asset_bucket:
            self._help_icon_asset_bucket = bucket
            self._load_help_icon_textures()


    def destroy(self) -> None:
        """Release all GL resources."""
        icon_textures = getattr(self, '_help_icon_textures', None)
        if isinstance(icon_textures, dict):
            for tex in icon_textures.values():
                try:
                    tex.release()
                except Exception:
                    pass
            icon_textures.clear()

        icon_vao = getattr(self, '_icon_vao', None)
        icon_vbo = getattr(self, '_icon_vbo', None)
        icon_prog = getattr(self, '_icon_prog', None)
        if icon_vao is not None:
            icon_vao.release()
        if icon_vbo is not None:
            icon_vbo.release()
        if icon_prog is not None:
            icon_prog.release()

        quad_vao = getattr(self, '_quad_vao', None)
        quad_vbo = getattr(self, '_quad_vbo', None)
        blit_prog = getattr(self, '_blit_prog', None)
        textures = getattr(self, '_textures', None)
        if quad_vao is not None:
            quad_vao.release()
        if quad_vbo is not None:
            quad_vbo.release()
        if blit_prog is not None:
            blit_prog.release()
        if textures is not None:
            for _t in textures:
                _t.release()

    def _ensure_resources(self, ctx: moderngl.Context) -> None:
        """Lazily build GLSL shader and PIL-rendered textures."""
        if self._blit_prog is None:
            vert = """
#version 330
in vec2 in_pos;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    v_uv = in_uv;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""
            frag = """
#version 330
uniform sampler2D iChannel0;
uniform float     iTime;
uniform float     iPhase;
uniform float     iAlpha;
in  vec2 v_uv;
out vec4 fragColor;
void main() {
    float ca  = mix(0.018, 0.004, clamp(iPhase * 2.5, 0.0, 1.0));
    float r   = texture(iChannel0, v_uv + vec2(-ca, 0.0)).r;
    float g   = texture(iChannel0, v_uv).g;
    float b   = texture(iChannel0, v_uv + vec2( ca, 0.0)).b;
    float a   = texture(iChannel0, v_uv).a;
    float cyc  = 0.5 + 0.5 * sin(iTime * 2.8);
    vec3  nA   = vec3(1.0,  0.12, 0.88);
    vec3  nB   = vec3(0.05, 0.95, 1.0);
    vec3  neon = mix(nA, nB, cyc);
    vec3  col  = vec3(r, g, b);
    float lum  = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(col, col * neon * 1.5, 0.45 * lum);
    col *= 0.92 + 0.08 * sin(v_uv.y * 160.0 + iTime * 18.0);
    col *= 0.90 + 0.10 * sin(iTime * 9.2);
    fragColor = vec4(col, a * iAlpha);
}
"""
            self._blit_prog = ctx.program(vertex_shader=vert, fragment_shader=frag)
            self._quad_vbo = ctx.buffer(reserve=6 * 4 * 4)
            self._quad_vao = ctx.vertex_array(
                self._blit_prog,
                [(self._quad_vbo, '2f 2f', 'in_pos', 'in_uv')],
            )

        slots_key = tuple(self._slots)
        if self._textures is not None and self._slots_key == slots_key:
            return

        if self._textures is not None:
            for _t in self._textures:
                _t.release()
        self._textures = []
        self._slots_key = slots_key
        if not _PIL_AVAILABLE:
            return

        text_font = None
        emoji_font = None
        try:
            if self._font_path is not None and self._font_path.exists():
                text_font = ImageFont.truetype(str(self._font_path), size=132)
        except Exception:
            pass
        try:
            icon_font_path = next(
                (p for p in [
                    Path('/usr/share/fonts/gdouros-symbola/Symbola.ttf'),
                    Path('/usr/share/fonts/gdouros-symbola/Symbola.otf'),
                    Path('/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf'),
                    Path('/usr/share/fonts/google-noto-emoji-fonts/NotoColorEmoji.ttf'),
                    Path('/usr/share/fonts/noto-emoji/NotoColorEmoji.ttf'),
                ] if p.exists()),
                None,
            )
            if icon_font_path is not None:
                emoji_font = ImageFont.truetype(str(icon_font_path), size=140)
        except Exception:
            pass

        TEX_W, TEX_H = self._tex_w, self._tex_h
        for text, icon in self._slots:
            try:
                img = self._build_image(text, icon, TEX_W, TEX_H, text_font, emoji_font)
            except Exception:
                log.debug('CTA image render failed for %r; using blank', text, exc_info=True)
                img = Image.new('RGBA', (TEX_W, TEX_H), (0, 0, 0, 0))
            data = np.array(img, dtype=np.uint8)
            tex = ctx.texture((TEX_W, TEX_H), 4, data=data.tobytes())
            tex.filter = moderngl.LINEAR, moderngl.LINEAR
            self._textures.append(tex)

    def _build_image(
        self,
        text: str,
        icon: str,
        width: int,
        height: int,
        text_font: 'ImageFont.FreeTypeFont | None',
        emoji_font: 'ImageFont.FreeTypeFont | None',
    ) -> 'Image.Image':
        """Render one CTA slot to a transparent RGBA PIL image."""
        img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        font = text_font or ImageFont.load_default()
        icon_font = emoji_font or font
        icon_clean = icon.replace('\ufe0f', '').strip()

        bbox_t = draw.textbbox((0, 0), text, font=font)
        tw = bbox_t[2] - bbox_t[0]
        th = bbox_t[3] - bbox_t[1]

        iw, ih = 0, 0
        bbox_i = (0, 0, 0, 0)
        if icon_clean:
            try:
                bbox_i = draw.textbbox((0, 0), icon_clean, font=icon_font)
                iw = bbox_i[2] - bbox_i[0]
                ih = bbox_i[3] - bbox_i[1]
            except Exception:
                icon_clean = ''

        gap = 36 if icon_clean else 0
        total_w = tw + gap + iw
        tx = max(0, (width - total_w) // 2)
        ty = (height - th) // 2

        draw.text((tx - bbox_t[0], ty - bbox_t[1]), text, font=font, fill=(255, 255, 255, 255))

        if icon_clean:
            ix = tx + tw + gap
            iy = ty + (th - ih) // 2
            draw.text((ix - bbox_i[0], iy - bbox_i[1]), icon_clean, font=icon_font, fill=(255, 255, 255, 255))

        return img
