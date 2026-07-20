"""First-run tour: slide deck content and startup/persistence policy.

The v1 tour is a centered slide dialog rendered by the overlay system
(``Overlays._render_tour``) and offered automatically on the app's
first-ever run — see ``docs/planning/first-run-tour-plan-2026-07-18.md``.
This module owns everything that is *not* rendering or input:

- :class:`TourSlide` and the core slide deck (:data:`CORE_TOUR_SLIDES`).
- Hotkey-placeholder resolution (:func:`resolve_slide_body`) so slide copy
  never hardcodes key names — ``{key:<help description>}`` tokens are
  resolved against the help registry at display time, preserving the
  single-source-of-truth rule for bindings.
- The startup policy (:func:`should_show_on_startup`) backed by the
  persisted runtime state store: a missing key means "first run", which
  is exactly the case that should be offered the tour.

Drop-in slide contribution (``TOUR_SLIDES`` discovery, mirroring
``HELP_ENTRIES``) is phase 2 and intentionally absent here.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

# Runtime-state keys (persisted across sessions via the app's runtime
# state store — deliberately NOT config.toml, which is operator-edited).
STATE_SHOW_ON_STARTUP = 'tour.show_on_startup'
STATE_LAST_SLIDE = 'tour.last_slide'

_KEY_TOKEN = re.compile(r'\{key:([^}]+)\}')


@dataclass(slots=True, frozen=True)
class TourSlide:
    """One slide: a section eyebrow, a title, and a short wrapped body.

    ``body`` may contain ``{key:<help description>}`` tokens, resolved by
    :func:`resolve_slide_body` against the help registry — never write
    literal key chords into slide copy.
    """

    section: str
    title: str
    body: str


def resolve_slide_body(body: str, lookup: Callable[[str], str]) -> str:
    """Replace ``{key:<description>}`` tokens with looked-up key labels.

    ``lookup`` is ``Overlays.lookup_help_key`` (description -> key chord,
    '' when unknown). Unresolvable tokens degrade to the description text
    itself so copy still reads sensibly if a binding is renamed.
    """

    def _sub(match: re.Match[str]) -> str:
        desc = match.group(1).strip()
        key = lookup(desc)
        return key if key else desc

    return _KEY_TOKEN.sub(_sub, str(body or ''))


def should_show_on_startup(get_state: Callable[[str, object], object]) -> bool:
    """Return True when the tour should auto-open at startup.

    ``get_state(key, default)`` is the runtime-state getter. A missing
    key (first-ever run) defaults to True — the first run *is* the offer;
    the dialog's own checkbox controls every run after that.
    """
    return bool(get_state(STATE_SHOW_ON_STARTUP, True))


def clamp_slide_index(index: object, deck_size: int) -> int:
    """Clamp a persisted slide index into the current deck's bounds."""
    if deck_size <= 0:
        return 0
    try:
        value = int(index)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(deck_size - 1, value))


# ---------------------------------------------------------------------------
# The core deck (P1). Sections for control-room-01 / dj-mixer-01 arrive in
# P2 via drop-in TOUR_SLIDES discovery; until then the closing slide points
# at them generically. Keep bodies short — the dialog is a fixed-size panel
# and copy must fit at the smallest supported window.
# ---------------------------------------------------------------------------

_CORE = 'Unicorn Viz'

CORE_TOUR_SLIDES: tuple[TourSlide, ...] = (
    TourSlide(
        _CORE,
        'Welcome',
        'Unicorn Viz is a live audio-reactive visualizer with a real DJ '
        'mixer and an operator control room built in. This quick tour '
        'takes about a minute — use the buttons below or the arrow keys. '
        'The checkbox controls whether the tour opens at startup.',
    ),
    TourSlide(
        _CORE,
        'The audience window',
        'This window is the show: effects render here fullscreen and '
        'react to live audio. Everything else (operator panels, the '
        'mixer) lives in its own window and never draws over the show.',
    ),
    TourSlide(
        _CORE,
        'Switching effects',
        'Move through effects with {key:Next effect} and '
        '{key:Prev effect}, or jump anywhere with the effects browser '
        '({key:Effects browser (search/filter/preview/pin all effects)}). '
        'Auto-advance ({key:Auto-advance on/off}) rotates the playlist on '
        'a timer; pause any time with {key:Pause / resume}.',
    ),
    TourSlide(
        _CORE,
        'Audio in',
        'Visuals follow whatever audio source is selected — open the '
        'source selector with {key:Audio source selector menu} and pick '
        'a capture device or a monitor of your player. Sources that '
        'failed a probe are flagged; you can show or hide them there.',
    ),
    TourSlide(
        _CORE,
        'Help lives on one key',
        'Press {key:Toggle help overlay} for the full help overlay: '
        'every hotkey, grouped by feature, plus the icon rail for '
        'app-level actions. Drop-ins document their own keys there too — '
        'it is the single source of truth for bindings.',
    ),
    TourSlide(
        _CORE,
        'Multi-display',
        'The output can run single-display, spanned, or mirrored across '
        'monitors — and the mixer and control room can each own a screen '
        'of their own. Display modes live in the control room and on '
        'hotkeys listed in help.',
    ),
    TourSlide(
        _CORE,
        'The right-click menu',
        'Almost everything has a mouse path: right-click the window for '
        'a context menu of panels, toggles, and actions — including '
        'reopening this tour.',
    ),
    TourSlide(
        _CORE,
        'Where to go next',
        'Open the DJ mixer and the operator control room from the '
        'context menu or their hotkeys (see help). The configuration '
        'editor tunes effects live; docs/ has the deep dives. Re-run '
        'this tour any time from the right-click menu. Have a great '
        'show!',
    ),
)
