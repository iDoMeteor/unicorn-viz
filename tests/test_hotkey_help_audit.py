"""Hotkey / help-overlay parity audit.

This test ALWAYS PASSES.  It emits a ``UserWarning`` with a full delta report
showing which named hotkeys are not documented in ``CORE_HELP_SECTIONS``.
Intentionally-undocumented keys (easter eggs, dev shortcuts) will appear in
the report — that is expected and fine.  The point is to make the gap visible
on every test run so documentation drift is noticed rather than silently
accumulating.

Check the warning in ``pytest -v`` output (or ``pytest -W all``) to review
the current undocumented set.

The only hard assertion is that the set of *known-required* keys (those that
were explicitly identified as missing in the 2026-06-17 audit and have since
been fixed) does not regress.
"""
from __future__ import annotations

import re
import warnings
from pathlib import Path

import sdl2

from unicornviz.hotkeys import _MIDI_NOTE_KEY_BINDINGS as _ACTION_MAP  # type: ignore[attr-defined]
from unicornviz.overlays import Overlays


# ---------------------------------------------------------------------------
# Keys that MUST be documented — any regression here is a hard failure.
# Expand this list as audits confirm additional mandatory entries.
# ---------------------------------------------------------------------------
_MUST_BE_DOCUMENTED: set[str] = {
    'H',        # help toggle — part of 'H / ?' entry (2026-06-18 audit)
    '?',        # help toggle alias — part of 'H / ?' entry
    'Shift+H',  # notification toggle (added 2026-06-18)
    'F6',       # speed random (added 2026-06-18)
    'F7',       # reactivity random
}

# SDL keysym → human-readable label (subset; add more as needed).
_SYM_LABELS: dict[int, str] = {
    sdl2.SDLK_a: 'A', sdl2.SDLK_b: 'B', sdl2.SDLK_c: 'C',
    sdl2.SDLK_d: 'D', sdl2.SDLK_e: 'E', sdl2.SDLK_f: 'F',
    sdl2.SDLK_g: 'G', sdl2.SDLK_h: 'H', sdl2.SDLK_i: 'I',
    sdl2.SDLK_j: 'J', sdl2.SDLK_k: 'K', sdl2.SDLK_l: 'L',
    sdl2.SDLK_m: 'M', sdl2.SDLK_n: 'N', sdl2.SDLK_o: 'O',
    sdl2.SDLK_p: 'P', sdl2.SDLK_q: 'Q', sdl2.SDLK_r: 'R',
    sdl2.SDLK_s: 'S', sdl2.SDLK_t: 'T', sdl2.SDLK_u: 'U',
    sdl2.SDLK_v: 'V', sdl2.SDLK_w: 'W', sdl2.SDLK_x: 'X',
    sdl2.SDLK_y: 'Y', sdl2.SDLK_z: 'Z',
    sdl2.SDLK_SPACE: 'Space', sdl2.SDLK_TAB: 'Tab',
    sdl2.SDLK_ESCAPE: 'ESC', sdl2.SDLK_RETURN: 'Enter',
    sdl2.SDLK_UP: 'Up', sdl2.SDLK_DOWN: 'Down',
    sdl2.SDLK_LEFT: 'Left', sdl2.SDLK_RIGHT: 'Right',
    sdl2.SDLK_F1: 'F1', sdl2.SDLK_F2: 'F2', sdl2.SDLK_F3: 'F3',
    sdl2.SDLK_F4: 'F4', sdl2.SDLK_F5: 'F5', sdl2.SDLK_F6: 'F6',
    sdl2.SDLK_F7: 'F7', sdl2.SDLK_F8: 'F8', sdl2.SDLK_F9: 'F9',
    sdl2.SDLK_F10: 'F10', sdl2.SDLK_F11: 'F11', sdl2.SDLK_F12: 'F12',
    sdl2.SDLK_BACKSPACE: 'Backspace', sdl2.SDLK_DELETE: 'Delete',
    sdl2.SDLK_QUESTION: '?', sdl2.SDLK_SLASH: '/',
    sdl2.SDLK_BACKSLASH: '\\',
    sdl2.SDLK_SEMICOLON: ';', sdl2.SDLK_QUOTE: "'",
    sdl2.SDLK_COMMA: ',', sdl2.SDLK_PERIOD: '.',
    sdl2.SDLK_MINUS: '-', sdl2.SDLK_EQUALS: '=',
    sdl2.SDLK_LEFTBRACKET: '[', sdl2.SDLK_RIGHTBRACKET: ']',
}


def _sym_to_label(sym: int, mod: int) -> str:
    base = _SYM_LABELS.get(sym, f'SDLK({sym})')
    parts = []
    if mod & sdl2.KMOD_CTRL:
        parts.append('Ctrl')
    if mod & sdl2.KMOD_ALT:
        parts.append('Alt')
    if mod & sdl2.KMOD_SHIFT:
        parts.append('Shift')
    parts.append(base)
    return '+'.join(parts)


def _documented_key_strings() -> set[str]:
    """Return all key-string tokens from CORE_HELP_SECTIONS (flat, lowercased for matching)."""
    tokens: set[str] = set()
    for _section, entries in Overlays.CORE_HELP_SECTIONS:
        for key_str, _desc in entries:
            # Each comma/slash-separated part is a separate token.
            for part in re.split(r'[,/]', key_str):
                tokens.add(part.strip())
    return tokens


def test_hotkey_help_audit() -> None:
    """Audit report: emit undocumented hotkeys as a warning (never fails)."""
    documented = _documented_key_strings()

    undocumented: list[str] = []
    for name, (sym, mod) in _ACTION_MAP.items():
        label = _sym_to_label(sym, mod)
        # Check whether this label (or its base key alone) appears in help.
        base = _SYM_LABELS.get(sym, '')
        if label not in documented and base not in documented:
            undocumented.append(f'{label!r:30s}  ({name})')

    if undocumented:
        report = (
            'Hotkey/help parity audit — '
            f'{len(undocumented)} named hotkey(s) have no help entry '
            '(easter eggs and dev shortcuts are expected here):\n  '
            + '\n  '.join(sorted(undocumented))
        )
        warnings.warn(report, UserWarning, stacklevel=1)

    # Hard regression guard: keys confirmed-documented in 2026-06-18 audit
    # must still appear in the help sections.
    missing_required = _MUST_BE_DOCUMENTED - documented
    assert not missing_required, (
        f'Required help entries have gone missing (regression): {missing_required}'
    )
