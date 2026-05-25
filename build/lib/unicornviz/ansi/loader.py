"""
ANSI / ANSi file parser.

Parses ANSI escape sequences and CP437 characters into a grid of cells.
Each cell has a foreground colour, background colour, and CP437 codepoint.

Supports:
  - ESC[...m   SGR: colour and attribute setting
  - ESC[...H   CUP: cursor position
  - ESC[...A/B/C/D  cursor movement
  - ESC[2J     erase display
  - Bare CP437 character codes
  - SAUCE record detection + stripping
  - ICEColors (blink bit → bright background)
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field


# ── CGA 16-colour palette (RGB tuples, used for texture generation) ──────────

CGA_PALETTE: list[tuple[int, int, int]] = [
    (0,   0,   0),    # 0  black
    (0,   0, 170),    # 1  blue
    (0, 170,   0),    # 2  green
    (0, 170, 170),    # 3  cyan
    (170,  0,   0),   # 4  red
    (170,  0, 170),   # 5  magenta
    (170,  85,  0),   # 6  brown
    (170, 170, 170),  # 7  light gray
    (85,  85,  85),   # 8  dark gray
    (85,  85, 255),   # 9  bright blue
    (85, 255,  85),   # 10 bright green
    (85, 255, 255),   # 11 bright cyan
    (255,  85,  85),  # 12 bright red
    (255,  85, 255),  # 13 bright magenta
    (255, 255,  85),  # 14 yellow
    (255, 255, 255),  # 15 white
]


@dataclass
class Cell:
    codepoint: int = 32       # CP437 char (0-255)
    fg: int = 7               # foreground colour 0-15
    bg: int = 0               # background colour 0-7 (or 0-15 with ICEColors)
    bold: bool = False

    @property
    def fg_rgb(self) -> tuple[int, int, int]:
        idx = (self.fg | 8) if self.bold and self.fg < 8 else self.fg
        return CGA_PALETTE[idx & 15]

    @property
    def bg_rgb(self) -> tuple[int, int, int]:
        return CGA_PALETTE[self.bg & 15]


@dataclass
class ANSICanvas:
    width: int = 80
    height: int = 25
    cells: list[list[Cell]] = field(default_factory=list)

    def get(self, row: int, col: int) -> Cell:
        if 0 <= row < len(self.cells) and 0 <= col < len(self.cells[row]):
            return self.cells[row][col]
        return Cell()


# ── SAUCE record ─────────────────────────────────────────────────────────────

def _strip_sauce(data: bytes) -> tuple[bytes, dict]:
    """Remove optional SAUCE record from end of data; return (clean_data, info)."""
    info: dict = {}
    # SAUCE is 128 bytes preceded by SUB (0x1A), total 129 bytes from end
    if len(data) >= 129 and data[-128:-123] == b"SAUCE":
        sauce_raw = data[-128:]
        info["title"]  = sauce_raw[7:42].rstrip(b"\x00 ").decode("cp437", errors="replace")
        info["author"] = sauce_raw[42:62].rstrip(b"\x00 ").decode("cp437", errors="replace")
        info["group"]  = sauce_raw[62:82].rstrip(b"\x00 ").decode("cp437", errors="replace")
        info["width"]  = struct.unpack_from("<H", sauce_raw, 96)[0]
        info["height"] = struct.unpack_from("<H", sauce_raw, 98)[0]
        # Strip SUB + SAUCE
        clean = data[: -(129)]
        if clean and clean[-1] == 0x1A:
            clean = clean[:-1]
        return clean, info
    # Also handle just SUB at end
    if data.endswith(b"\x1a"):
        return data[:-1], info
    return data, info


# ── Parser ────────────────────────────────────────────────────────────────────

class ANSIParser:
    """
    Parse raw .ANS bytes into an ANSICanvas.

    Usage:
        canvas = ANSIParser().parse(Path("file.ans").read_bytes())
    """

    def __init__(self, ice_colors: bool = True) -> None:
        self.ice_colors = ice_colors  # treat bg bit 3 as bright bg, not blink

    def parse(self, data: bytes) -> ANSICanvas:
        clean, sauce_info = _strip_sauce(data)
        width  = sauce_info.get("width",  80) or 80
        height = sauce_info.get("height", 25) or 25

        # Parse canvas dynamically (expand if art is taller than declared)
        cells: list[list[Cell]] = []

        def ensure_row(r: int) -> None:
            while len(cells) <= r:
                cells.append([Cell() for _ in range(width)])

        def ensure_col(r: int, c: int) -> None:
            ensure_row(r)
            while len(cells[r]) <= c:
                cells[r].append(Cell())

        cur_row = cur_col = 0
        fg = 7; bg = 0; bold = False

        i = 0
        n = len(clean)

        while i < n:
            byte = clean[i]

            if byte == 0x1B and i + 1 < n and clean[i + 1] == ord("["):
                # ESC [ sequence
                i += 2
                seq_start = i
                # Collect until final byte (letter or other terminator)
                while i < n and not (0x40 <= clean[i] <= 0x7E):
                    i += 1
                if i >= n:
                    break
                final = clean[i]
                params_raw = clean[seq_start:i].decode("ascii", errors="ignore")
                params = [int(p) if p.isdigit() else 0 for p in params_raw.split(";") if p != ""]
                i += 1

                if final == ord("m"):
                    # SGR — colour/attribute
                    if not params:
                        params = [0]
                    for code in params:
                        if code == 0:
                            fg = 7; bg = 0; bold = False
                        elif code == 1:
                            bold = True
                        elif code == 22:
                            bold = False
                        elif 30 <= code <= 37:
                            fg = code - 30
                        elif code == 39:
                            fg = 7
                        elif 40 <= code <= 47:
                            bg = code - 40
                        elif code == 49:
                            bg = 0
                        elif 90 <= code <= 97:
                            fg = (code - 90) + 8
                        elif 100 <= code <= 107:
                            bg = (code - 100) + 8 if self.ice_colors else (code - 100)

                elif final == ord("H") or final == ord("f"):
                    # CUP — cursor position (1-based)
                    r = (params[0] - 1) if len(params) > 0 and params[0] > 0 else 0
                    c = (params[1] - 1) if len(params) > 1 and params[1] > 0 else 0
                    cur_row = r; cur_col = c

                elif final == ord("A"):
                    cur_row = max(0, cur_row - (params[0] if params else 1))
                elif final == ord("B"):
                    cur_row += (params[0] if params else 1)
                elif final == ord("C"):
                    cur_col += (params[0] if params else 1)
                elif final == ord("D"):
                    cur_col = max(0, cur_col - (params[0] if params else 1))
                elif final == ord("J"):
                    if (params[0] if params else 0) == 2:
                        cells.clear()
                        cur_row = cur_col = 0

            elif byte == 0x0D:
                # CR
                cur_col = 0
                i += 1
            elif byte == 0x0A:
                # LF
                cur_row += 1
                i += 1
            elif byte == 0x09:
                # HT — tab stop at 8
                cur_col = (cur_col + 8) & ~7
                i += 1
            elif byte == 0x1A:
                # SUB — EOF marker
                break
            elif byte < 0x20:
                # Other control chars — skip
                i += 1
            else:
                # Printable CP437
                ensure_col(cur_row, cur_col)
                cells[cur_row][cur_col] = Cell(
                    codepoint=byte,
                    fg=fg | (8 if bold and fg < 8 else 0),
                    bg=bg,
                    bold=bold,
                )
                cur_col += 1
                if cur_col >= width:
                    cur_col = 0
                    cur_row += 1
                i += 1

        # Normalise height
        actual_height = max(height, len(cells))
        while len(cells) < actual_height:
            cells.append([Cell() for _ in range(width)])

        canvas = ANSICanvas(width=width, height=actual_height, cells=cells)
        canvas._sauce = sauce_info  # type: ignore[attr-defined]
        return canvas
