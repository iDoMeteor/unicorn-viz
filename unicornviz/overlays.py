"""
On-screen overlays rendered in immediate mode using a simple bitmap font.
Handles: effect name flash, persistent name overlay, help screen,
audio device selector, MIDI device selector, and generic flash messages.
"""
from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import moderngl
import numpy as np

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except Exception:
    _PIL_AVAILABLE = False

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


def _build_font_texture(ctx: moderngl.Context) -> tuple[moderngl.Texture, int, int, int, int]:
    """
    Build overlay font atlas and return (texture, glyph_w, glyph_h, atlas_w, atlas_h).

    Preferred path: render a grayscale atlas from a modern TTF font for cleaner
    readability at mixed sizes.
    Fallback path: legacy 8x8 bitmap atlas from assets/fonts/font8x8.bin or
    embedded BIOS-style font data.
    """
    if _PIL_AVAILABLE:
        font_candidates = [
            Path('assets/fonts/ui-font.ttf'),
            Path('/usr/share/fonts/adobe-source-code-pro-fonts/SourceCodePro-Medium.otf'),
            Path('/usr/share/fonts/google-noto-vf/NotoSansMono-VF.ttf'),
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
                return tex, glyph_w, glyph_h, atlas_w, atlas_h
            except Exception:
                pass

    N_CHARS = 128
    data = np.zeros((8, N_CHARS * 8), dtype=np.uint8)

    font_path = Path("assets/fonts/font8x8.bin")
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
    return tex, 8, 8, N_CHARS * 8, 8


class Overlays:
    """Manages all HUD/overlay rendering."""

    HELP_SECTION_THEMES: dict[str, tuple[float, float, float]] = {
        'Navigation': (0.18, 0.96, 0.86),
        'Playback': (1.00, 0.68, 0.28),
        'Audio + Visual': (0.64, 0.86, 1.00),
        'Display + Capture': (0.96, 0.72, 1.00),
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

    CORE_HELP_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
        (
            'Navigation',
            [
                ('N / Right', 'Next effect'),
                ('P / Left', 'Prev effect'),
                ('1-9', 'Jump #1-9'),
                ('Shift+1-0', 'Jump #11-20'),
                ('Ctrl+1-0', 'Jump #21-30'),
                ('Alt+1-0', 'Jump #31-40'),
                ('U', 'Unicorn Tears'),
                ('Shift+U', 'Replay splash'),
            ],
        ),
        (
            'Playback',
            [
                ('Space', 'Pause / resume'),
                ('R', 'Random mode'),
                ('T', 'Auto-advance on/off'),
                ('; / \'' , 'Advance interval -/+ 10s'),
                ('\\', 'Reset advance interval'),
                ('+ / -', 'Speed up / down'),
                ('Ctrl+=/-', 'Speed MAX / MIN'),
                ('G', 'Reset speed'),
                ('F6', 'Random speed (cfg range)'),
            ],
        ),
        (
            'Audio + Visual',
            [
                ('[ / ]', 'Reactivity -/+'),
                ('{ / }', 'Reactivity MIN / MAX'),
                ('Alt+[ / Alt+]', 'Zoom -/+ (if available)'),
                ('g', 'Reset reactivity'),
                ('F6', 'Toggle random speed'),
                ('F7', 'Toggle random reactivity'),
                ('Shift+Z', 'Toggle random zoom'),
                ('E', 'EQ / spectrum'),
                ('A', 'Audio source'),
                ('M', 'MIDI device'),
                ('I', 'Invert colors'),
            ],
        ),
        (
            'Display + Capture',
            [
                (',', 'ANSI art'),
                ('.', 'ACiD art'),
                ('TAB', 'Toggle HUD'),
                ('S', 'Screenshot'),
                ('V', 'Toggle recording'),
                ('H', 'Toggle help'),
                ('ESC', 'Quit'),
                ('F', 'Fullscreen'),
            ],
        ),
        (
            'Display Modes',
            [
                ('X', 'Mode from config'),
                ('Shift+X', 'single'),
                ('Ctrl+X', 'span_all'),
                ('Alt+X', 'mirror_all'),
            ],
        ),
        (
            'Camera Overlay',
            [
                ('KP 1-9', 'PiP position'),
                ('KP 0 / .', 'PiP fullscreen / hide'),
                ('KP / *', 'Treatment prev / next'),
                ('KP - +', 'PiP size'),
                ('KP Enter', 'Treatment auto-cycle'),
            ],
        ),
    ]

    NUM_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]
    SHIFT_KEYS = ["S+1", "S+2", "S+3", "S+4", "S+5", "S+6", "S+7", "S+8", "S+9", "S+0"]
    CTRL_KEYS = ["Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4", "Ctrl+5", "Ctrl+6", "Ctrl+7", "Ctrl+8", "Ctrl+9", "Ctrl+0"]
    ALT_KEYS = ["A+1", "A+2", "A+3", "A+4", "A+5", "A+6", "A+7", "A+8", "A+9", "A+0"]

    def __init__(
        self,
        ctx: moderngl.Context,
        width: int,
        height: int,
        flash_messages: bool = True,
        show_recording_indicator: bool = True,
    ) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._flash_enabled = flash_messages
        self._show_recording_indicator = show_recording_indicator
        self._recording_active = False
        self._recording_elapsed_seconds = 0.0

        self._show_name = False
        self._show_help = False
        self._show_audio = False
        self._show_midi = False
        self._help_timer: float = 0.0
        self._flash_text: str = ""
        self._flash_timer: float = 0.0
        self._name_text: str = ""
        self._hud_state: dict[str, str] = {
            'title': 'Unicorn Viz Legacy HUD',
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
            'preset_slot_label': 'PRESET IDX',
            'preset_slot': '-/-',
            'variant_slot_label': 'VARIANT',
            'variant_slot': '-/-',
            'recording': 'OFF',
            'streaming': 'OFF',
            'streaming_provider': '-',
            'bass': '0.00',
            'mid': '0.00',
            'treble': '0.00',
            'display_mode': 'single',
            'display_index': '0',
            'invert': 'OFF',
        }
        self._num_shortcuts: list[str] = []
        self._shift_shortcuts: list[str] = []
        self._ctrl_shortcuts: list[str] = []
        self._alt_shortcuts: list[str] = []
        self._unmapped_effects: list[str] = []
        self._hud_rect: tuple[float, float, float, float] | None = None
        self._dynamic_help_sections: dict[str, list[tuple[str, str]]] = {}
        self._dynamic_help_order: list[str] = []
        self._help_collapsed: dict[str, bool] = {}
        self._help_focus_idx: int = 0
        self._help_pulse_t: float = 0.0

        self._font_tex, self._glyph_w, self._glyph_h, self._atlas_w, self._atlas_h = _build_font_texture(ctx)
        # Keep historical scale semantics (scale=1 roughly equals an 8 px cell).
        self._font_scale_norm = 8.0 / float(max(1, self._glyph_h))
        self._prog = self._build_program()
        self._build_vbo()
        self._build_panel_vbo()

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
        # Resize VBO if needed
        needed = data.nbytes
        if needed > self._vbo.size:
            self._vbo.orphan(needed * 2)
        self._vbo.write(data)
        self._prog["color"].value = color
        self._font_tex.use(location=0)
        self._prog["font_tex"].value = 0
        self._ctx.enable(moderngl.BLEND)
        self._vao.render(moderngl.TRIANGLES, vertices=len(data) // 4)

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

    def _render_hud(self) -> None:
        """Render modern game-style status HUD panel."""
        panel_w = min(990.0, self._width * 0.86)
        lh = 28.0
        row0_offset = 188.0
        row_text_scale = 2.05
        row_text_h = 8.0 * row_text_scale + 4.0

        left_lines = [
            f"FPS         {self._hud_state.get('fps', '0.0')}",
            f"FRAME MS    {self._hud_state.get('frame_ms', '0.0')}",
            f"RES         {self._hud_state.get('resolution', '-')}",
            f"SCALE       {self._hud_state.get('render_scale', '1.00')}",
            f"PLAYLIST    {self._hud_state.get('playlist', '-')}",
            f"REACTIVITY  {self._hud_state.get('reactivity', '1.0x')}",
            f"SPEED       {self._hud_state.get('speed', '-')}",
            f"AUDIO SRC   {self._hud_state.get('audio_source', '-')}",
        ]
        right_lines = [
            f"PAUSED      {self._hud_state.get('paused', 'NO')}",
            f"FULLSCREEN  {self._hud_state.get('fullscreen', 'NO')}",
            f"AUTO ADV    {self._hud_state.get('auto_advance', 'ON')}",
            f"ADV TIMER   {self._hud_state.get('advance_time', '0.0/20.0s')}",
            f"{self._hud_state.get('preset_slot_label', 'PRESET IDX'):<11} {self._hud_state.get('preset_slot', '-/-')}",
            f"{self._hud_state.get('variant_slot_label', 'VARIANT'):<11} {self._hud_state.get('variant_slot', '-/-')}",
            f"RECORDING   {self._hud_state.get('recording', 'OFF')}",
            f"STREAMING   {self._hud_state.get('streaming', 'OFF')}",
            f"STREAM SRV  {self._hud_state.get('streaming_provider', '-')}",
            f"PREV FX     {self._hud_state.get('previous_effect', '-')}",
            f"NEXT FX     {self._hud_state.get('next_effect', '-')}",
            f"DISPLAY     {self._hud_state.get('display_mode', 'single')} #{self._hud_state.get('display_index', '0')}",
            f"INVERT      {self._hud_state.get('invert', 'OFF')}",
            f"BASS/MID/TREB {self._hud_state.get('bass', '0.00')} / {self._hud_state.get('mid', '0.00')} / {self._hud_state.get('treble', '0.00')}",
        ]

        rows = max(len(left_lines), len(right_lines))
        content_bottom = row0_offset + max(0, rows - 1) * lh + row_text_h
        panel_h_needed = content_bottom + 34.0
        panel_h = min(max(520.0, panel_h_needed), self._height * 0.92)
        x = (self._width - panel_w) * 0.5
        y = (self._height - panel_h) * 0.5
        self._hud_rect = (x, y, panel_w, panel_h)

        # Layered glass panels
        self._draw_rect(x - 2.0, y - 2.0, panel_w + 4.0, panel_h + 4.0, (0.08, 0.95, 1.0, 0.26))
        self._draw_rect(x, y, panel_w, panel_h, (0.03, 0.05, 0.10, 0.76))
        self._draw_rect(x, y, panel_w, 92.0, (0.06, 0.12, 0.22, 0.76))

        title = self._hud_state.get('title', 'Unicorn Viz Legacy HUD')
        tx = x + (panel_w - len(title) * 8.0 * 3.0) * 0.5
        self._draw_text(title, tx, y + 10.0, scale=3.0, color=(0.62, 1.0, 1.0, 0.96))
        now = datetime.datetime.now()
        dt_line = f"{now.strftime('%Y-%m-%d')}  {now.strftime('%H:%M:%S')}"
        dx = x + (panel_w - len(dt_line) * 8.0 * 2.2) * 0.5
        self._draw_text(dt_line, dx, y + 46.0, scale=2.2, color=(0.94, 0.98, 1.0, 0.90))

        # Primary strip
        self._draw_rect(x + 14.0, y + 106.0, panel_w - 28.0, 78.0, (0.08, 0.11, 0.18, 0.76))
        self._draw_text(f"EFFECT: {self._hud_state.get('effect', '-')}", x + 24.0, y + 116.0, scale=3.0, color=(0.92, 1.0, 1.0, 0.95))
        self._draw_text(f"TRANSITION: {self._hud_state.get('transition', '-')} ({self._hud_state.get('transition_t', '0%')})", x + 24.0, y + 146.0, scale=2.35, color=(0.68, 0.94, 1.0, 0.92))

        # Core stats columns
        left_x = x + 22.0
        right_x = x + panel_w * 0.51
        row0 = y + row0_offset

        for i, ln in enumerate(left_lines):
            self._draw_text(ln, left_x, row0 + i * lh, scale=2.05, color=(0.82, 0.94, 1.0, 0.95))
        for i, ln in enumerate(right_lines):
            self._draw_text(ln, right_x, row0 + i * lh, scale=2.05, color=(0.84, 1.0, 0.88, 0.95))

        # Bottom accent
        self._draw_rect(x + 14.0, y + panel_h - 24.0, panel_w - 28.0, 10.0, (0.11, 0.95, 1.0, 0.45))

    def render(self, dt: float, include_recording_indicator: bool = True) -> None:
        """Call each frame after the main effect renders."""
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

        if self._show_name and self._name_text:
            self._render_hud()

        if include_recording_indicator:
            self._render_recording_indicator()

        if self._show_help:
            # 50% black underlay for readability.
            self._draw_rect(0.0, 0.0, float(self._width), float(self._height), (0.0, 0.0, 0.0, 0.5))
            self._render_help()

    def _render_help(self) -> None:
        panel_pad = 24.0
        x = panel_pad
        y = panel_pad
        w = self._width - panel_pad * 2.0
        h = self._height - panel_pad * 2.0

        # Main glass panel with neon flare.
        self._draw_rect(x, y, w, h, (0.03, 0.05, 0.10, 0.76))
        self._draw_rect(x, y, w, 86.0, (0.07, 0.14, 0.24, 0.76))
        self._draw_rect(x + 10.0, y + 82.0, w - 20.0, 3.0, (0.12, 0.94, 1.0, 0.65))

        self._draw_text('UNICORN VIZ - HELP', x + 18.0, y + 10.0, scale=2.95, color=(0.66, 1.0, 1.0, 0.98))
        self._draw_text('Core controls, drop-ins, and live shortcuts', x + 18.0, y + 38.0, scale=1.95, color=(0.78, 0.9, 1.0, 0.92))
        self._draw_text('1-9/0 toggle sections  Up/Down + Enter focus/toggle  Shift+= expand all  Shift+- collapse all', x + 420.0, y + 38.0, scale=1.34, color=(0.84, 0.92, 1.0, 0.86))
        slot_label = self._hud_state.get('preset_slot_label', 'PRESET IDX')
        self._draw_text(f"ACTIVE {slot_label}: {self._hud_state.get('preset_slot', '-/-')}", x + 18.0, y + 58.0, scale=1.5, color=(0.90, 1.0, 0.72, 0.94))
        v_label = self._hud_state.get('variant_slot_label', 'VARIANT')
        self._draw_text(f"ACTIVE {v_label}: {self._hud_state.get('variant_slot', '-/-')}", x + 520.0, y + 58.0, scale=1.5, color=(0.82, 0.95, 1.0, 0.94))

        left_x = x + 14.0
        left_y = y + 98.0
        left_w = w * 0.64
        left_h = h - 90.0

        right_x = left_x + left_w + 10.0
        right_y = left_y
        right_w = x + w - right_x - 14.0
        right_h = left_h

        self._draw_rect(left_x, left_y, left_w, left_h, (0.02, 0.07, 0.11, 0.76))
        self._draw_rect(right_x, right_y, right_w, right_h, (0.02, 0.09, 0.12, 0.76))

        sections = self._iter_help_sections()
        if sections:
            self._help_focus_idx = max(0, min(self._help_focus_idx, len(sections) - 1))

        card_title_scale = 2.30
        item_scale = 2.10
        card_line_h = 8 * item_scale + 2.0
        card_pad = 8.0

        col_gap = 10.0
        col_w = (left_w - 3 * col_gap) / 2.0
        col_x = [left_x + col_gap, left_x + col_gap * 2 + col_w]
        col_y = [left_y + 8.0, left_y + 8.0]
        col_max_y = left_y + left_h - 10.0

        for sec_idx, (section, entries) in enumerate(sections):
            if not entries:
                continue
            accent = self._help_theme_color(section)
            collapsed = self._help_collapsed.get(section, False)
            visible_entries = [] if collapsed else entries
            section_h = card_pad * 2 + 8 * card_title_scale + 4 + len(visible_entries) * card_line_h
            if collapsed:
                section_h += card_line_h
            idx = 0 if col_y[0] <= col_y[1] else 1
            if col_y[idx] + section_h > col_max_y:
                other = 1 - idx
                if col_y[other] + section_h <= col_max_y:
                    idx = other
                else:
                    continue

            sx = col_x[idx]
            sy = col_y[idx]
            if sec_idx == self._help_focus_idx:
                pulse = 0.5 + 0.5 * np.sin(self._help_pulse_t * 5.4)
                glow_a = 0.16 + pulse * 0.20
                edge_a = 0.34 + pulse * 0.26
                self._draw_rect(sx - 4.0, sy - 4.0, col_w + 8.0, section_h + 8.0, (accent[0], accent[1], accent[2], glow_a))
                self._draw_rect(sx - 2.0, sy - 2.0, col_w + 4.0, section_h + 4.0, (accent[0], accent[1], accent[2], edge_a))
            self._draw_rect(sx, sy, col_w, section_h, (0.05 + accent[0] * 0.05, 0.08 + accent[1] * 0.06, 0.14 + accent[2] * 0.05, 0.62))
            self._draw_rect(sx, sy, col_w, 3.0, (accent[0], accent[1], accent[2], 0.78))
            marker = '>' if sec_idx == self._help_focus_idx else ' '
            icon = '+' if collapsed else '-'
            header = f'{marker}{sec_idx + 1}. {icon} {section.upper()} ({len(entries)})'
            self._draw_text(header, sx + card_pad, sy + card_pad, scale=card_title_scale, color=(accent[0], accent[1], accent[2], 0.98))

            yy = sy + card_pad + 8 * card_title_scale + 4
            if collapsed:
                self._draw_text('[collapsed]', sx + card_pad, yy, scale=item_scale, color=(0.78, 0.84, 0.92, 0.92))
                yy += card_line_h
            for key, desc in visible_entries:
                line = f'{key:<12} {desc}'
                self._draw_text(line, sx + card_pad, yy, scale=item_scale, color=(0.80 + accent[0] * 0.20, 0.82 + accent[1] * 0.18, 0.84 + accent[2] * 0.16, 0.96))
                yy += card_line_h

            col_y[idx] += section_h + 8.0

        # Right column: direct effect shortcut map.
        self._draw_text('LIVE SHORTCUT MAP', right_x + 10.0, right_y + 10.0, scale=2.05, color=(1.0, 0.92, 0.58, 0.96))
        self._draw_rect(right_x + 10.0, right_y + 30.0, right_w - 20.0, 2.0, (1.0, 0.72, 0.24, 0.65))

        rows = max(
            len(self._num_shortcuts),
            len(self._shift_shortcuts),
            len(self._ctrl_shortcuts),
            len(self._alt_shortcuts),
        )
        sec_scale = 1.82
        min_bottom_margin = 26.0

        def _shortcut_block_height(scale: float) -> float:
            line_h = 8 * scale + 2.0
            return (8 * 1.85 + 3.0) + float(min(rows, 12)) * line_h

        top = right_y + 42.0
        row_count = float(min(rows, 12))
        while sec_scale > 1.18:
            sec_lh = 8 * sec_scale + 2.0
            top_block_h = (8 * 1.85 + 3.0) + row_count * sec_lh
            bottom_y = top + top_block_h + 28.0
            total_h = bottom_y + _shortcut_block_height(sec_scale)
            if total_h <= right_y + right_h - min_bottom_margin:
                break
            sec_scale -= 0.08

        sec_lh = 8 * sec_scale + 2.0

        def _draw_shortcut_block(title: str, items: list[str], bx: float, by: float, color: tuple[float, float, float, float]) -> None:
            self._draw_text(title, bx, by, scale=1.85, color=(0.96, 1.0, 0.70, 0.96))
            y0 = by + 8 * 1.85 + 3.0
            for i in range(min(rows, 12)):
                text = items[i] if i < len(items) else '(none)'
                self._draw_text(text, bx, y0 + i * sec_lh, scale=sec_scale, color=color)

        half = right_w * 0.48
        top_block_h = (8 * 1.85 + 3.0) + row_count * sec_lh
        bottom_y = top + top_block_h + 28.0
        _draw_shortcut_block('1-0', self._num_shortcuts, right_x + 10.0, top, (0.82, 1.0, 0.9, 0.95))
        _draw_shortcut_block('SHIFT', self._shift_shortcuts, right_x + half, top, (0.92, 0.86, 1.0, 0.95))
        _draw_shortcut_block('CTRL', self._ctrl_shortcuts, right_x + 10.0, bottom_y, (0.84, 0.94, 1.0, 0.95))
        _draw_shortcut_block('ALT', self._alt_shortcuts, right_x + half, bottom_y, (1.0, 0.92, 0.82, 0.95))

        if self._unmapped_effects:
            self._draw_text(
                f"Extra effects (no direct key): {', '.join(self._unmapped_effects)}",
                right_x + 10.0,
                right_y + right_h - 20.0,
                scale=1.16,
                color=(1.0, 0.62, 0.62, 0.94),
            )

    def _iter_help_sections(self) -> list[tuple[str, list[tuple[str, str]]]]:
        """Return merged core + dynamic help sections in render order."""
        sections: list[tuple[str, list[tuple[str, str]]]] = []
        for section, entries in self.CORE_HELP_SECTIONS:
            sections.append((section, list(entries)))
        for section in self._dynamic_help_order:
            entries = self._dynamic_help_sections.get(section, [])
            if entries:
                sections.append((section, list(entries)))
        return sections

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

            bucket = self._dynamic_help_sections.setdefault(section, [])
            entry = (key, desc)
            if entry not in bucket:
                bucket.append(entry)
            if section not in self._dynamic_help_order:
                self._dynamic_help_order.append(section)

        # Keep collapse state for known sections, default to expanded.
        valid = [name for name, _entries in self._iter_help_sections()]
        self._help_collapsed = {k: v for k, v in self._help_collapsed.items() if k in valid}
        for name in valid:
            self._help_collapsed.setdefault(name, False)
        if valid:
            self._help_focus_idx = max(0, min(self._help_focus_idx, len(valid) - 1))

    @property
    def help_visible(self) -> bool:
        return self._show_help

    def help_section_count(self) -> int:
        return len(self._iter_help_sections())

    def toggle_help_section(self, index: int) -> bool:
        sections = self._iter_help_sections()
        if index < 0 or index >= len(sections):
            return False
        name, _entries = sections[index]
        self._help_collapsed[name] = not self._help_collapsed.get(name, False)
        self._help_focus_idx = index
        return True

    def set_all_help_sections_collapsed(self, collapsed: bool) -> None:
        for name, _entries in self._iter_help_sections():
            self._help_collapsed[name] = collapsed

    def move_help_focus(self, delta: int) -> bool:
        n = self.help_section_count()
        if n <= 0:
            return False
        self._help_focus_idx = (self._help_focus_idx + delta) % n
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

    def flash_message(self, msg: str, duration: float = 2.0) -> None:
        if not self._flash_enabled:
            return
        self._flash_text = msg
        self._flash_timer = duration

    def toggle_name_overlay(self) -> None:
        self._show_name = not self._show_name

    def set_hud_state(self, state: dict[str, str]) -> None:
        """Update the live HUD payload rendered by TAB overlay."""
        self._hud_state.update(state)

    def toggle_help(self) -> None:
        self._show_help = not self._show_help
        self._help_timer = 30.0 if self._show_help else 0.0

    def toggle_audio_selector(self) -> None:
        self._show_audio = not self._show_audio

    def toggle_midi_selector(self) -> None:
        self._show_midi = not self._show_midi

    def set_recording_state(self, active: bool, elapsed_seconds: float = 0.0) -> None:
        self._recording_active = active
        self._recording_elapsed_seconds = elapsed_seconds if active else 0.0

    def render_live_recording_indicator(self) -> None:
        """Draw only the recording indicator for live display after frame capture."""
        self._render_recording_indicator()

    def resize(self, w: int, h: int) -> None:
        self._width = w
        self._height = h

    def destroy(self) -> None:
        self._font_tex.release()
        self._prog.release()
        self._vbo.release()
        self._panel_prog.release()
        self._panel_vbo.release()
        self._panel_vao.release()
