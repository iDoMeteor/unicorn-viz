"""Help overlay per-section item accordion — regression tests.

Sections stay grouped up to HELP_SECTIONS_PER_TAB per tab (10) AND stay a
single card/heading each — a section with many items (e.g. 'Tweakables' has
15, 'Basics' has 14) is not split into separate top-level sections (that
was tried and reverted: it disrupted the section list/pagination for
something that should stay a per-section concern).

Instead, a section with more than HELP_MAX_ITEMS_PER_SECTION (7) entries
pages its *items* into an inner accordion: "Items 1-7", "8-14", "15-21", ...
Only one page is expanded at a time — opening one (via click, or Enter/digit
cycling through toggle_help_section while the section is already expanded)
closes whichever other page was open.
"""
from __future__ import annotations

from unicornviz.overlays import Overlays

CAP = Overlays.HELP_MAX_ITEMS_PER_SECTION


def _stub_overlays() -> Overlays:
    overlays = Overlays.__new__(Overlays)
    overlays._help_item_page = {}
    overlays._help_collapsed = {}
    overlays._glyph_w = 8
    overlays._glyph_h = 8
    overlays._font_scale_norm = 8.0 / 8.0
    return overlays


def _items(n: int) -> list[tuple[str, str]]:
    return [(f'k{i}', f'd{i}') for i in range(n)]


# --------------------------------------------------------------------------- #
# _help_item_pages / _help_item_page_count
# --------------------------------------------------------------------------- #

def test_section_at_or_under_cap_is_a_single_page() -> None:
    overlays = _stub_overlays()
    assert overlays._help_item_pages(_items(CAP)) == [_items(CAP)]
    assert overlays._help_item_page_count(_items(CAP)) == 1


def test_section_one_over_cap_is_two_pages() -> None:
    overlays = _stub_overlays()
    pages = overlays._help_item_pages(_items(CAP + 1))
    assert [len(p) for p in pages] == [CAP, 1]
    assert overlays._help_item_page_count(_items(CAP + 1)) == 2


def test_section_needing_three_pages() -> None:
    overlays = _stub_overlays()
    pages = overlays._help_item_pages(_items(2 * CAP + 1))
    assert [len(p) for p in pages] == [CAP, CAP, 1]


def test_pages_preserve_entry_order_and_content() -> None:
    overlays = _stub_overlays()
    items = _items(2 * CAP + 2)
    pages = overlays._help_item_pages(items)
    reassembled = [entry for page in pages for entry in page]
    assert reassembled == items


def test_empty_entries_is_a_single_empty_page() -> None:
    overlays = _stub_overlays()
    assert overlays._help_item_pages([]) == [[]]
    assert overlays._help_item_page_count([]) == 1


# --------------------------------------------------------------------------- #
# Sections are NOT split into separate top-level sections
# --------------------------------------------------------------------------- #

def test_iter_help_sections_does_not_split_oversized_sections() -> None:
    """'Basics' (14) and 'Tweakables' (15) exceed the cap today, but must
    stay single sections — pagination happens inside the card, not by
    creating 'Basics (2)' as its own top-level section."""
    overlays = _stub_overlays()
    overlays._dynamic_help_sections = {}
    overlays._dynamic_help_order = []

    sections = overlays._iter_help_sections()
    names = [name for name, _entries in sections]

    assert names.count('Basics') == 1
    assert 'Basics (2)' not in names
    assert 'Tweakables (2)' not in names
    basics_entries = next(e for n, e in sections if n == 'Basics')
    assert len(basics_entries) == 14  # still whole, not truncated to CAP


# --------------------------------------------------------------------------- #
# _help_section_body_rows: the accordion itself
# --------------------------------------------------------------------------- #

def test_small_section_has_no_page_header_rows() -> None:
    overlays = _stub_overlays()
    rows = overlays._help_section_body_rows('Basics', _items(3), False, 500.0, 2.0)
    assert all(r['kind'] == 'text' for r in rows)


def test_collapsed_section_shows_only_collapsed_marker() -> None:
    overlays = _stub_overlays()
    rows = overlays._help_section_body_rows('Basics', _items(CAP + 5), True, 500.0, 2.0)
    assert rows == [{'kind': 'text', 'text': '[collapsed]'}]


def test_oversized_section_shows_one_page_header_per_page() -> None:
    overlays = _stub_overlays()
    entries = _items(2 * CAP + 1)  # 3 pages
    rows = overlays._help_section_body_rows('Tweakables', entries, False, 500.0, 2.0)
    page_headers = [r for r in rows if r['kind'] == 'page_header']
    assert len(page_headers) == 3
    assert [r['page_index'] for r in page_headers] == [0, 1, 2]


def test_only_the_open_page_shows_its_items() -> None:
    overlays = _stub_overlays()
    entries = _items(2 * CAP)  # 2 pages, 'Tweakables' page 0 open by default
    rows = overlays._help_section_body_rows('Tweakables', entries, False, 500.0, 2.0)
    # First page's items (k0..k(CAP-1)) should appear; second page's (kCAP..) should not.
    text_blob = ' '.join(r['text'] for r in rows if r['kind'] == 'text')
    assert 'k0' in text_blob
    assert f'k{CAP}' not in text_blob


def test_opening_a_different_page_closes_the_previous_one() -> None:
    overlays = _stub_overlays()
    entries = _items(2 * CAP)
    overlays._help_item_page['Tweakables'] = 1  # open the second page instead
    rows = overlays._help_section_body_rows('Tweakables', entries, False, 500.0, 2.0)
    text_blob = ' '.join(r['text'] for r in rows if r['kind'] == 'text')
    assert 'k0' not in text_blob
    assert f'k{CAP}' in text_blob


def test_page_header_label_shows_the_correct_item_range() -> None:
    overlays = _stub_overlays()
    entries = _items(2 * CAP + 1)
    rows = overlays._help_section_body_rows('Tweakables', entries, False, 500.0, 2.0)
    headers = [r['text'] for r in rows if r['kind'] == 'page_header']
    assert f'Items 1-{CAP}' in headers[0]
    assert f'Items {CAP + 1}-{2 * CAP}' in headers[1]
    assert f'Items {2 * CAP + 1}-{2 * CAP + 1}' in headers[2]


# --------------------------------------------------------------------------- #
# set_help_item_page
# --------------------------------------------------------------------------- #

def test_set_help_item_page_opens_the_requested_page() -> None:
    overlays = _stub_overlays()
    assert overlays.set_help_item_page('Tweakables', 1) is True
    assert overlays._help_item_page['Tweakables'] == 1


def test_set_help_item_page_clamps_negative() -> None:
    overlays = _stub_overlays()
    overlays.set_help_item_page('Tweakables', -3)
    assert overlays._help_item_page['Tweakables'] == 0


# --------------------------------------------------------------------------- #
# toggle_help_section: context-sensitive Enter/digit-key behavior
# --------------------------------------------------------------------------- #

def _sections_stub(entries: list[tuple[str, str]]) -> Overlays:
    overlays = _stub_overlays()
    overlays._help_focus_idx = 0
    synthetic = [('Tweakables', entries)]
    overlays._current_help_sections = lambda: synthetic
    return overlays


def test_toggle_collapsed_section_expands_to_first_page() -> None:
    overlays = _sections_stub(_items(2 * CAP))
    overlays._help_collapsed['Tweakables'] = True
    overlays._help_item_page['Tweakables'] = 1  # stale from a previous visit

    assert overlays.toggle_help_section(0) is True
    assert overlays._help_collapsed['Tweakables'] is False
    assert overlays._help_item_page['Tweakables'] == 0


def test_toggle_expanded_multipage_section_cycles_pages_not_collapse() -> None:
    overlays = _sections_stub(_items(2 * CAP))  # 2 pages
    overlays._help_collapsed['Tweakables'] = False
    overlays._help_item_page['Tweakables'] = 0

    assert overlays.toggle_help_section(0) is True
    assert overlays._help_collapsed['Tweakables'] is False  # still expanded
    assert overlays._help_item_page['Tweakables'] == 1

    overlays.toggle_help_section(0)
    assert overlays._help_item_page['Tweakables'] == 0  # wrapped back


def test_toggle_expanded_single_page_section_collapses() -> None:
    """A section with <= CAP items has no accordion, so Enter/digit still
    just collapses it — unchanged from before the accordion existed."""
    overlays = _sections_stub(_items(3))
    overlays._help_collapsed['Tweakables'] = False

    assert overlays.toggle_help_section(0) is True
    assert overlays._help_collapsed['Tweakables'] is True


# --------------------------------------------------------------------------- #
# register_help_entries clears stale item-page state for sections that
# no longer exist (mirrors the existing _help_collapsed cleanup)
# --------------------------------------------------------------------------- #

def test_register_help_entries_drops_stale_item_page_state() -> None:
    overlays = Overlays.__new__(Overlays)
    overlays._dynamic_help_sections = {}
    overlays._dynamic_help_order = []
    overlays._postfx_help_entries = []
    overlays._mouse_help_entries = []
    overlays._help_collapsed = {}
    overlays._help_item_page = {'Ghost Section': 2}
    overlays._help_tab_idx = 0
    overlays._help_right_tab_idx = 0
    overlays._help_focus_idx = 0

    overlays.register_help_entries([])

    assert 'Ghost Section' not in overlays._help_item_page
