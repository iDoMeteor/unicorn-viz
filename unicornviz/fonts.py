"""Cross-platform font resolution for PIL-rendered surfaces.

Why this module exists: every PIL text surface (second-window UIs, banner,
now-spinning card, CTA/tour big text) used to search hardcoded
``/usr/share/fonts/...`` paths and fall back to ``ImageFont.load_default()``
— PIL's ~10 px bitmap font — on any non-Linux machine. On Windows (the
primary release target) that rendered every such surface with tiny,
non-scalable text. All font lookups now go through here: the bundled
``assets/fonts/ui-font.ttf`` wins everywhere, with per-platform system
directories as fallbacks.

Usage::

    from unicornviz.fonts import load_font, load_emoji_font

    font = load_font(17)              # bundled-first monospace/UI font
    emoji = load_emoji_font(140)      # may return None (no emoji face found)

Drop-ins should import from this module instead of carrying their own
candidate lists.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from unicornviz.paths import resolve_path

log = logging.getLogger(__name__)

try:
    from PIL import ImageFont
    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover - PIL is a hard dep in practice
    _PIL_AVAILABLE = False


def _windows_fonts_dir() -> Path:
    return Path(os.environ.get('WINDIR', 'C:\\Windows')) / 'Fonts'


# Linux paths cover Fedora / Arch / Debian package layouts (the union of the
# per-module lists this module replaced).
_LINUX_TEXT = (
    '/usr/share/fonts/liberation-mono-fonts/LiberationMono-Bold.ttf',
    '/usr/share/fonts/liberation-mono/LiberationMono-Bold.ttf',
    '/usr/share/fonts/liberation/LiberationMono-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf',
    '/usr/share/fonts/adobe-source-code-pro-fonts/SourceCodePro-Medium.otf',
    '/usr/share/fonts/google-noto-vf/NotoSansMono[wght].ttf',
    '/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf',
    '/usr/share/fonts/dejavu/DejaVuSansMono.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
    '/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf',
)

_MACOS_TEXT = (
    '/System/Library/Fonts/Menlo.ttc',
    '/System/Library/Fonts/Monaco.ttf',
    '/System/Library/Fonts/Supplemental/Courier New.ttf',
)

_LINUX_EMOJI = (
    '/usr/share/fonts/gdouros-symbola/Symbola.ttf',
    '/usr/share/fonts/gdouros-symbola/Symbola.otf',
    '/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf',
    '/usr/share/fonts/google-noto-emoji-fonts/NotoColorEmoji.ttf',
    '/usr/share/fonts/noto-emoji/NotoColorEmoji.ttf',
)

_MACOS_EMOJI = ('/System/Library/Fonts/Apple Color Emoji.ttc',)


def font_candidates() -> list[Path]:
    """Ordered UI/mono font candidates: bundled first, then platform dirs."""
    candidates: list[Path] = [resolve_path('assets/fonts/ui-font.ttf')]
    if sys.platform == 'win32':
        win = _windows_fonts_dir()
        candidates += [win / 'consola.ttf', win / 'lucon.ttf',
                       win / 'cour.ttf', win / 'arial.ttf']
    elif sys.platform == 'darwin':
        candidates += [Path(p) for p in _MACOS_TEXT]
    else:
        candidates += [Path(p) for p in _LINUX_TEXT]
    return candidates


def emoji_candidates() -> list[Path]:
    """Ordered emoji/symbol font candidates for the current platform."""
    if sys.platform == 'win32':
        win = _windows_fonts_dir()
        return [win / 'seguiemj.ttf', win / 'seguisym.ttf']
    if sys.platform == 'darwin':
        return [Path(p) for p in _MACOS_EMOJI]
    return [Path(p) for p in _LINUX_EMOJI]


def find_font_path() -> Path | None:
    """First existing UI font candidate, or None."""
    return next((p for p in font_candidates() if p.exists()), None)


def load_font(size: int):
    """Load the UI font at *size*; never raises.

    Falls back to PIL's built-in bitmap font (scaled when Pillow supports
    it) only when no candidate exists — which should not happen on any
    supported platform since the first candidate ships with the app.
    """
    if _PIL_AVAILABLE:
        for path in font_candidates():
            try:
                if path.exists():
                    return ImageFont.truetype(str(path), size=size)
            except Exception:
                continue
        log.warning('No usable UI font found; falling back to PIL bitmap font')
        try:
            return ImageFont.load_default(size=size)
        except TypeError:  # Pillow < 10.1 has no size parameter
            return ImageFont.load_default()
    return None


def load_emoji_font(size: int):
    """Load an emoji/symbol-capable font at *size*, or None when absent."""
    if not _PIL_AVAILABLE:
        return None
    for path in emoji_candidates():
        try:
            if path.exists():
                return ImageFont.truetype(str(path), size=size)
        except Exception:
            continue
    return None
