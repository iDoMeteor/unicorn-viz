"""
Generic catalog-browser model — the shared, input-agnostic core behind every
searchable list modal (the effects browser and, in time, the projectM preset
manager).

This module holds **only state and pure logic**: the entry list, category tabs,
the text filter, and the current selection/focus.  It performs no rendering and
touches no GL, SDL, or numpy, so it is trivially unit-testable and reusable by
both keyboard and mouse input paths.

Entries are plain dicts so any producer (effects registry, preset scanner) can
feed the model without importing it.  Recognised keys:

``display_name``  (str)   — shown in the list and searched.
``category_key``  (str)   — grouping key for the category tabs and search.
``tags``          (list)  — searched.
``pack_name``     (str)   — optional; searched.

Any other keys (an effect class, a preset path, …) are carried through untouched
on the selected entry so callers can act on the selection.
"""
from __future__ import annotations

from typing import Any

ALL_CATEGORIES = '(all)'
UNCATEGORIZED = '(uncategorized)'
# Categories whose key starts with this prefix are "system/virtual" --
# always reachable by selecting them directly, same as any other category,
# but hidden from the catch-all "(all)" view. Lets a producer feed in
# entries that duplicate (or wouldn't otherwise belong alongside) the main
# catalog -- e.g. projectM's Excluded/Quarantined/Disabled sections --
# without inflating "(all)"'s counts or list with redundant/out-of-band
# rows. Same convention this project already uses for
# _exclude_dirs()'s '! Transition' default (drop-ins/projectm-01/
# projectm_effect.py).
HIDDEN_FROM_ALL_PREFIX = '! '

# Focus panes.
PANE_CATEGORIES = 0
PANE_LIST = 1


class CatalogBrowser:
    """Filterable, selectable catalog model shared by list-browser modals.

    Lifecycle: construct once, call :meth:`set_entries` whenever the catalog
    changes, then drive it with the ``move_*`` / ``set_*`` / search methods from
    whatever input layer (keyboard or mouse) is active.  Rendering code reads
    :meth:`filtered`, :meth:`categories`, :meth:`selected_entry`, and the
    ``*_index`` / ``focus_pane`` / ``search_*`` accessors.
    """

    __slots__ = (
        '_entries',
        '_categories',
        '_category_idx',
        '_selected_idx',
        '_focus_pane',
        '_search_query',
        '_search_mode',
    )

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._categories: list[str] = [ALL_CATEGORIES]
        self._category_idx: int = 0
        self._selected_idx: int = 0
        self._focus_pane: int = PANE_LIST
        self._search_query: str = ''
        self._search_mode: bool = False

    # -- population -----------------------------------------------------------

    def set_entries(self, entries: list[dict[str, Any]]) -> None:
        """Replace the catalog and rebuild the category tabs, clamping state."""
        self._entries = list(entries)
        cats = {ALL_CATEGORIES}
        for entry in self._entries:
            cats.add(str(entry.get('category_key', '') or UNCATEGORIZED))
        self._categories = [ALL_CATEGORIES] + sorted(
            (c for c in cats if c != ALL_CATEGORIES), key=str.lower
        )
        self._category_idx = max(0, min(self._category_idx, len(self._categories) - 1))
        self._clamp_selection()

    def entries(self) -> list[dict[str, Any]]:
        """Return a shallow copy of the full, unfiltered entry list.

        Useful for consumer-specific aggregate stats (e.g. counting enabled
        presets per category) that the generic filter does not express.
        """
        return list(self._entries)

    # -- filtering ------------------------------------------------------------

    def filtered(self) -> list[dict[str, Any]]:
        """Return entries matching the current category tab and text query."""
        category = self.selected_category()
        query = self._search_query.strip().lower()

        def category_ok(entry: dict[str, Any]) -> bool:
            key = str(entry.get('category_key', '') or UNCATEGORIZED)
            if category == ALL_CATEGORIES:
                return not key.startswith(HIDDEN_FROM_ALL_PREFIX)
            return key == category

        def query_ok(entry: dict[str, Any]) -> bool:
            if not query:
                return True
            haystack = ' '.join(
                [
                    str(entry.get('display_name', '')),
                    str(entry.get('pack_name', '')),
                    str(entry.get('category_key', '')),
                    ' '.join(str(t) for t in (entry.get('tags', []) or [])),
                ]
            ).lower()
            return query in haystack

        return [e for e in self._entries if category_ok(e) and query_ok(e)]

    def category_stats(self, category: str) -> tuple[int, int]:
        """Return ``(query_matches, total)`` entry counts for ``category``."""
        total = 0
        matches = 0
        query = self._search_query.strip().lower()
        for entry in self._entries:
            key = str(entry.get('category_key', '') or UNCATEGORIZED)
            if category == ALL_CATEGORIES:
                if key.startswith(HIDDEN_FROM_ALL_PREFIX):
                    continue
            elif key != category:
                continue
            total += 1
            if not query:
                matches += 1
                continue
            haystack = ' '.join(
                [
                    str(entry.get('display_name', '')),
                    str(entry.get('pack_name', '')),
                    str(entry.get('category_key', '')),
                    ' '.join(str(t) for t in (entry.get('tags', []) or [])),
                ]
            ).lower()
            if query in haystack:
                matches += 1
        return matches, total

    # -- categories -----------------------------------------------------------

    def categories(self) -> list[str]:
        """Return the ordered category tabs (``'(all)'`` first)."""
        return list(self._categories)

    def selected_category(self) -> str:
        """Return the currently selected category tab."""
        if not self._categories:
            return ALL_CATEGORIES
        idx = max(0, min(self._category_idx, len(self._categories) - 1))
        return self._categories[idx]

    def category_index(self) -> int:
        """Return the selected category tab index."""
        return self._category_idx

    def set_category_index(self, index: int) -> int:
        """Select a category tab by index (clamped); reset list selection."""
        total = len(self._categories)
        if total == 0:
            return 0
        self._category_idx = max(0, min(int(index), total - 1))
        self._selected_idx = 0
        return self._category_idx

    def move_category(self, delta: int) -> None:
        """Cycle the selected category tab by ``delta`` (wraps)."""
        total = len(self._categories)
        if total == 0:
            return
        self._category_idx = (self._category_idx + int(delta)) % total
        self._selected_idx = 0

    # -- list selection -------------------------------------------------------

    def selected_index(self) -> int:
        """Return the selected row index within the filtered list."""
        return self._selected_idx

    def set_selected_index(self, index: int) -> int:
        """Select a filtered-list row by index (clamped)."""
        count = len(self.filtered())
        if count == 0:
            self._selected_idx = 0
            return 0
        self._selected_idx = max(0, min(int(index), count - 1))
        return self._selected_idx

    def move_selection(self, delta: int) -> None:
        """Move the list selection by ``delta`` (clamped to the filtered list)."""
        count = len(self.filtered())
        if count == 0:
            self._selected_idx = 0
            return
        self._selected_idx = max(0, min(self._selected_idx + int(delta), count - 1))

    def selected_entry(self) -> dict[str, Any] | None:
        """Return the currently selected filtered entry, or ``None`` if empty."""
        rows = self.filtered()
        if not rows:
            return None
        idx = max(0, min(self._selected_idx, len(rows) - 1))
        return rows[idx]

    def _clamp_selection(self) -> None:
        count = len(self.filtered())
        self._selected_idx = 0 if count == 0 else max(0, min(self._selected_idx, count - 1))

    # -- focus ----------------------------------------------------------------

    def focus_pane(self) -> int:
        """Return the focused pane (``PANE_CATEGORIES`` or ``PANE_LIST``)."""
        return self._focus_pane

    def set_focus_pane(self, pane: int) -> int:
        """Focus the categories pane or the list pane."""
        self._focus_pane = PANE_CATEGORIES if int(pane) == PANE_CATEGORIES else PANE_LIST
        return self._focus_pane

    def toggle_focus_pane(self) -> int:
        """Swap keyboard focus between the categories and list panes."""
        self._focus_pane = (
            PANE_LIST if self._focus_pane == PANE_CATEGORIES else PANE_CATEGORIES
        )
        return self._focus_pane

    # -- search ---------------------------------------------------------------

    @property
    def search_query(self) -> str:
        """Return the current text filter."""
        return self._search_query

    def set_search_query(self, query: str) -> None:
        """Set the text filter and keep the selection coherent."""
        self._search_query = str(query)
        self._clamp_selection()

    def clear_search_query(self) -> None:
        """Clear the text filter."""
        self.set_search_query('')

    @property
    def search_mode(self) -> bool:
        """Return whether the modal is currently capturing search keystrokes."""
        return self._search_mode

    def set_search_mode(self, active: bool) -> None:
        """Enable/disable search-capture mode."""
        self._search_mode = bool(active)
