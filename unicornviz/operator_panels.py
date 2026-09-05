"""Operator-panel descriptors: how a drop-in claims space in the Control Room.

Why this exists
---------------
Until 2026-09-04 every panel in the operator Control Room
(``drop-ins/control-room-01``) was hardcoded there per drop-in -- Spotify's
snapshot fields, Auto VJ's field names, the DROP-INS button list. An absent
drop-in left a dead panel; a new drop-in needed Control Room edits. This
module is the *contract* side of the fix (plan:
``docs/planning/control-room-panel-registry-plan-2026-09-04.md``): a drop-in
registers one of these descriptors through ``vj_api.register_operator_panel``
and the Control Room renders it generically. Core owns the descriptor and the
registry (Public Runtime Surface rule 1); control-room-01 never imports the
registering drop-in, and the drop-in never imports control-room-01.

Lifecycle
---------
Register where the API first exists (``__init__(app)`` or ``set_vj_api()``),
guarded with ``getattr(vj_api, 'register_operator_panel', None)`` so an
older core is a no-op. **Unregister in ``shutdown()``/``destroy()``** with
``vj_api.unregister_operator_panel(name)``: the host isolates a failing
``content()`` into an error box rather than a freeze, but a drop-in that
shut down mid-session would otherwise leave that error box behind.

Declarative first
-----------------
A panel's ``content`` is a zero-arg callable returning a :class:`PanelContent`
-- plain rows / buttons / meters that the Control Room draws in its own theme,
on its own render thread. That callable must be a cheap, read-only snapshot
of the drop-in's *own* state: no GL, no ``vj_api`` mutation, no blocking I/O.
It is invoked once per Control Room frame and wrapped in a ``try/except`` by
the host, so a failing panel draws an error box instead of freezing the
window. Button presses come back on the *main* thread through
``on_action(action, payload)``; whatever string it returns is flashed.

The optional ``draw`` callback (tier 2) hands the panel a :class:`PanelCanvas`
for genuinely custom rendering (the deck-sim controller mirror is the
canonical case). Prefer ``content``; use ``draw`` only when rows and buttons
cannot express the surface.

Pages
-----
Panels live on a page (``'main'`` by default). A drop-in that needs a whole
surface registers an :class:`OperatorPage` and puts its panels on it, or
supplies a page-level ``draw`` for a fully custom page. The Control Room
shows pages as header tabs, ``MAIN`` pinned first and the rest sorted by
title.

Usage (inside a drop-in, guarded so a core without the registry is fine)::

    from unicornviz.operator_panels import OperatorPanel, PanelContent, PanelRow

    def _content() -> PanelContent:
        return PanelContent(rows=(PanelRow('STATUS', 'LIVE', emphasis='success'),))

    register = getattr(vj_api, 'register_operator_panel', None)
    if callable(register):
        register(OperatorPanel(name='spotify', title='SPOTIFY', content=_content))
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

PANEL_SIZES: tuple[str, ...] = ('small', 'medium', 'large', 'full')
"""Row-height classes the Control Room packer understands, smallest first."""

MAIN_PAGE = 'main'
"""The primary Control Room page; always present, always the first tab."""

STANDARD_PAGES: tuple[tuple[str, str], ...] = (
    ('fx', 'FX'),
    ('output', 'Output'),
    ('overlays', 'Overlays'),
    ('sources', 'Sources'),
)
"""Shared ``(name, title)`` pages the Control Room registers itself on
startup so drop-ins can target them with ``page='fx'`` etc. without each
re-registering an identical :class:`OperatorPage` (three copies of one
title string across three repos is the drift the registry exists to end).
``fx``: post passes and looks; ``output``: streaming, video/audio out, OSC,
MIDI, displays; ``overlays``: banner, chat, lyrics; ``sources``: media,
mixer, Spotify transport. The operator can move any panel elsewhere from
the LAYOUT page. See docs/planning/control-room-drop-in-integration-plan-
2026-09-05.md section 3.7."""


@dataclass(frozen=True, slots=True)
class PanelRow:
    """One label/value line of panel text."""

    label: str
    value: str = ''
    emphasis: str = ''
    """``''`` | ``'accent'`` | ``'warn'`` | ``'danger'`` | ``'success'`` -- a theme
    token, never an RGB triple, so panels stay theme-consistent."""


@dataclass(frozen=True, slots=True)
class PanelButton:
    """A clickable button; the host namespaces ``action`` per panel."""

    action: str
    label: str
    tooltip: str = ''
    active: bool = False
    accent: str = ''
    """Theme token (``'accent'``, ``'accent_2'``, ``'warn'``, ...); empty = default."""
    payload: Any = None


@dataclass(frozen=True, slots=True)
class PanelMeter:
    """A horizontal 0..1 bar with a label and optional readout text."""

    label: str
    value: float
    text: str = ''


@dataclass(frozen=True, slots=True)
class PanelContent:
    """What a declarative panel shows this frame."""

    rows: tuple[PanelRow, ...] = ()
    buttons: tuple[PanelButton, ...] = ()
    meters: tuple[PanelMeter, ...] = ()
    columns: int = 1
    """Rows are split evenly across this many text columns (1 or 2)."""
    status: str = ''
    """One short word/phrase drawn at the panel's header right (e.g. ``'LIVE'``)."""


@dataclass(frozen=True, slots=True)
class PanelCanvas:
    """What a tier-2 ``draw`` callback receives.

    ``draw`` is the host's PIL ``ImageDraw`` for the current frame, ``rect``
    the panel's ``(x, y, w, h)`` in window pixels, ``theme`` / ``fonts`` the
    host's theme object and ``{'title','heading','body','small'}`` font map,
    and ``add_hotspot(action, payload, rect)`` registers a click region whose
    ``action`` comes back through the panel's ``on_action``. Runs on the
    host's render thread; read-only with respect to app state.
    """

    draw: Any
    rect: tuple[int, int, int, int]
    theme: Any
    fonts: dict[str, Any]
    add_hotspot: Callable[[str, Any, tuple[int, int, int, int]], None]


@dataclass(frozen=True, slots=True)
class OperatorPanel:
    """A drop-in's claim on Control Room space. See the module docstring."""

    name: str
    title: str
    content: Callable[[], PanelContent] | None = None
    on_action: Callable[[str, Any], str | None] | None = None
    draw: Callable[[PanelCanvas], None] | None = None
    page: str = MAIN_PAGE
    priority: int = 0
    """Default ordering within a page; lower comes first. The operator's
    runtime-store override wins over this."""
    size: str = 'medium'
    tooltips: dict[str, str] | None = None
    """Extra tooltip text keyed by un-namespaced action; ``PanelButton.tooltip``
    already covers buttons the content emits."""

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError('OperatorPanel.name is required')
        if ':' in self.name:
            raise ValueError("OperatorPanel.name must not contain ':' (used as a namespace separator)")
        if self.size not in PANEL_SIZES:
            raise ValueError(f'OperatorPanel.size must be one of {PANEL_SIZES}, got {self.size!r}')
        if self.content is None and self.draw is None:
            raise ValueError('OperatorPanel needs a content() provider or a draw() callback')


@dataclass(frozen=True, slots=True)
class OperatorPage:
    """A whole Control Room page a drop-in owns.

    Either a container for the panels registered with ``page=<name>`` or, when
    ``draw`` is given, a fully custom surface. ``available`` (optional) lets
    the tab hide itself while the owning device/subsystem is not present --
    the host keeps the tab visible while the page is *current* so an
    operator is never stranded on a page with no way back.

    ``on_action`` mirrors ``OperatorPanel.on_action``: it handles a hotspot
    click registered by this page's own ``draw`` via ``PanelCanvas.
    add_hotspot(action, payload, rect)``, runs on the host's main thread (same
    as a hotkey), and whatever string it returns is flashed. Only meaningful
    alongside ``draw`` -- a panel-hosting page (no ``draw`` of its own) has no
    hotspots to route; the host namespaces this page's hotspot actions
    (``page_action:<name>:<action>``) only when ``on_action`` is set, so an
    existing ``draw``-only page with no ``on_action`` (e.g. one dispatching
    its own raw action names directly) is unaffected.
    """

    name: str
    title: str
    owner: str = ''
    draw: Callable[[PanelCanvas], None] | None = None
    available: Callable[[], bool] | None = None
    on_action: Callable[[str, Any], str | None] | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError('OperatorPage.name is required')
        if ':' in self.name:
            raise ValueError("OperatorPage.name must not contain ':'")
        if self.name == MAIN_PAGE:
            raise ValueError(f'{MAIN_PAGE!r} is the built-in page and cannot be registered')


def sort_pages(pages: 'list[OperatorPage]') -> 'list[OperatorPage]':
    """Return ``pages`` in tab order: by title (case-insensitive), then name.

    ``main`` is not in this list -- the host pins it first itself.
    """
    return sorted(pages, key=lambda p: (p.title.casefold(), p.name))
