"""Help overlay per-section item cap — regression tests.

Sections stay grouped up to HELP_SECTIONS_PER_TAB per tab (10), but a
section with many items (e.g. 'Tweakables' has 15, 'Basics' has 14) could
still grow tall enough — especially after word-wrapping long entries — to
fail to fit either two-column slot and get silently skipped for its tab.

Rather than shrinking the whole tab, oversized sections are split into
continuation sections capped at HELP_MAX_ITEMS_PER_SECTION (7) items each:
'Name', 'Name (2)', 'Name (3)', ... Each split part is a fully independent
section for pagination/collapse/focus purposes.
"""
from __future__ import annotations

from unicornviz.overlays import Overlays

CAP = Overlays.HELP_MAX_ITEMS_PER_SECTION


def _stub_overlays() -> Overlays:
    return Overlays.__new__(Overlays)


def _items(n: int) -> list[tuple[str, str]]:
    return [(f'k{i}', f'd{i}') for i in range(n)]


# --------------------------------------------------------------------------- #
# _split_oversized_sections
# --------------------------------------------------------------------------- #

def test_section_at_or_under_cap_is_left_alone() -> None:
    overlays = _stub_overlays()
    out = overlays._split_oversized_sections([('Basics', _items(CAP))])
    assert out == [('Basics', _items(CAP))]


def test_section_one_over_cap_splits_into_two() -> None:
    overlays = _stub_overlays()
    out = overlays._split_oversized_sections([('Basics', _items(CAP + 1))])
    names = [name for name, _entries in out]
    assert names == ['Basics', 'Basics (2)']
    assert len(out[0][1]) == CAP
    assert len(out[1][1]) == 1


def test_section_exactly_two_caps_splits_evenly() -> None:
    overlays = _stub_overlays()
    out = overlays._split_oversized_sections([('Tweakables', _items(2 * CAP))])
    assert [name for name, _e in out] == ['Tweakables', 'Tweakables (2)']
    assert [len(e) for _n, e in out] == [CAP, CAP]


def test_section_needing_three_parts_numbers_them_in_order() -> None:
    overlays = _stub_overlays()
    out = overlays._split_oversized_sections([('Tweakables', _items(2 * CAP + 1))])
    assert [name for name, _e in out] == ['Tweakables', 'Tweakables (2)', 'Tweakables (3)']
    assert [len(e) for _n, e in out] == [CAP, CAP, 1]


def test_split_preserves_entry_order_and_content() -> None:
    overlays = _stub_overlays()
    items = _items(2 * CAP + 2)
    out = overlays._split_oversized_sections([('X', items)])
    reassembled = [entry for _name, entries in out for entry in entries]
    assert reassembled == items


def test_small_and_large_sections_interleave_in_original_order() -> None:
    overlays = _stub_overlays()
    out = overlays._split_oversized_sections([
        ('Small', _items(3)),
        ('Big', _items(CAP + 2)),
        ('AlsoSmall', _items(1)),
    ])
    assert [name for name, _e in out] == ['Small', 'Big', 'Big (2)', 'AlsoSmall']


def test_empty_section_list_is_unaffected() -> None:
    overlays = _stub_overlays()
    assert overlays._split_oversized_sections([]) == []


# --------------------------------------------------------------------------- #
# Integration: real CORE_HELP_SECTIONS get split by _iter_help_sections()
# --------------------------------------------------------------------------- #

def test_real_oversized_core_sections_are_split() -> None:
    """'Basics' (14) and 'Tweakables' (15) exceed the cap today; guard that
    _iter_help_sections() actually applies the split to real data, not just
    the helper in isolation."""
    overlays = _stub_overlays()
    overlays._dynamic_help_sections = {}
    overlays._dynamic_help_order = []

    sections = overlays._iter_help_sections()
    names = [name for name, _entries in sections]

    assert 'Basics (2)' in names
    assert 'Tweakables (2)' in names
    for _name, entries in sections:
        assert len(entries) <= CAP


def test_split_sections_still_paginate_correctly() -> None:
    """The split happens before tab pagination, so HELP_SECTIONS_PER_TAB
    counts split parts as their own sections toward the per-tab limit."""
    overlays = _stub_overlays()
    overlays._dynamic_help_sections = {}
    overlays._dynamic_help_order = []
    overlays._help_tab_idx = 0

    groups = overlays._help_tab_groups()
    for group in groups:
        assert len(group) <= Overlays.HELP_SECTIONS_PER_TAB
