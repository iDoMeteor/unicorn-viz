"""Unit tests for the generic ``CatalogBrowser`` model.

Pure-logic coverage of filtering, category tabs, selection clamping, focus, and
search — the shared core behind the effects browser and preset manager.
"""
from __future__ import annotations

import pytest

from unicornviz.catalog_browser import (
    ALL_CATEGORIES,
    HIDDEN_FROM_ALL_PREFIX,
    PANE_CATEGORIES,
    PANE_LIST,
    CatalogBrowser,
)


def _entry(name, category, tags=(), pack=''):
    return {
        'display_name': name,
        'category_key': category,
        'tags': list(tags),
        'pack_name': pack,
    }


@pytest.fixture
def browser():
    b = CatalogBrowser()
    b.set_entries([
        _entry('Plasma', 'psychedelic', ['classic'], 'effects-psychedelic'),
        _entry('Kaleidoscope', 'psychedelic', ['classic'], 'effects-psychedelic'),
        _entry('Tron Grid', 'tech', ['neon', 'grid'], 'effects-tech'),
        _entry('Audio Spectrum', 'analyzer', ['visualizer'], 'core'),
    ])
    return b


def test_categories_sorted_with_all_first(browser):
    assert browser.categories()[0] == ALL_CATEGORIES
    assert browser.categories() == [ALL_CATEGORIES, 'analyzer', 'psychedelic', 'tech']


def test_all_category_shows_everything(browser):
    assert len(browser.filtered()) == 4


def test_category_filter(browser):
    browser.set_category_index(browser.categories().index('psychedelic'))
    names = {e['display_name'] for e in browser.filtered()}
    assert names == {'Plasma', 'Kaleidoscope'}


def test_text_search_matches_name_and_tags(browser):
    browser.set_search_query('neon')
    assert [e['display_name'] for e in browser.filtered()] == ['Tron Grid']
    browser.set_search_query('kale')
    assert [e['display_name'] for e in browser.filtered()] == ['Kaleidoscope']


def test_search_matches_pack(browser):
    browser.set_search_query('effects-tech')
    assert [e['display_name'] for e in browser.filtered()] == ['Tron Grid']


def test_category_and_query_combine(browser):
    browser.set_category_index(browser.categories().index('psychedelic'))
    browser.set_search_query('plasma')
    assert [e['display_name'] for e in browser.filtered()] == ['Plasma']


def test_selection_moves_and_clamps(browser):
    assert browser.selected_index() == 0
    browser.move_selection(2)
    assert browser.selected_index() == 2
    browser.move_selection(99)
    assert browser.selected_index() == 3  # clamped to last
    browser.move_selection(-99)
    assert browser.selected_index() == 0


def test_selected_entry_follows_filter(browser):
    browser.set_search_query('tron')
    browser.move_selection(5)
    assert browser.selected_entry()['display_name'] == 'Tron Grid'


def test_changing_category_resets_selection(browser):
    browser.move_selection(3)
    browser.set_category_index(browser.categories().index('tech'))
    assert browser.selected_index() == 0


def test_empty_filter_has_no_selection(browser):
    browser.set_search_query('zzzz-nomatch')
    assert browser.filtered() == []
    assert browser.selected_entry() is None
    assert browser.selected_index() == 0


def test_move_category_wraps(browser):
    n = len(browser.categories())
    browser.set_category_index(n - 1)
    browser.move_category(1)
    assert browser.category_index() == 0


def test_focus_toggle(browser):
    browser.set_focus_pane(PANE_LIST)
    assert browser.toggle_focus_pane() == PANE_CATEGORIES
    assert browser.toggle_focus_pane() == PANE_LIST


def test_category_stats(browser):
    matches, total = browser.category_stats('psychedelic')
    assert (matches, total) == (2, 2)
    browser.set_search_query('plasma')
    matches, total = browser.category_stats('psychedelic')
    assert (matches, total) == (1, 2)


def test_reentrant_set_entries_clamps(browser):
    browser.move_selection(3)
    browser.set_category_index(browser.categories().index('tech'))
    browser.set_entries([_entry('Solo', 'only', [], 'x')])
    assert browser.categories() == [ALL_CATEGORIES, 'only']
    assert browser.selected_index() == 0


# ------------------------------------------------------- hidden-from-all categories

@pytest.fixture
def browser_with_special(browser):
    entries = browser.entries()
    entries.append(_entry('Ghost', f'{HIDDEN_FROM_ALL_PREFIX}Special', [], 'x'))
    browser.set_entries(entries)
    return browser


def test_special_category_still_appears_in_the_category_list(browser_with_special):
    assert f'{HIDDEN_FROM_ALL_PREFIX}Special' in browser_with_special.categories()


def test_special_category_is_reachable_by_selecting_it_directly(browser_with_special):
    idx = browser_with_special.categories().index(f'{HIDDEN_FROM_ALL_PREFIX}Special')
    browser_with_special.set_category_index(idx)
    assert [e['display_name'] for e in browser_with_special.filtered()] == ['Ghost']


def test_special_category_entry_is_excluded_from_all_view(browser_with_special):
    browser_with_special.set_category_index(browser_with_special.categories().index(ALL_CATEGORIES))
    names = {e['display_name'] for e in browser_with_special.filtered()}
    assert 'Ghost' not in names
    assert names == {'Plasma', 'Kaleidoscope', 'Tron Grid', 'Audio Spectrum'}


def test_special_category_entry_is_excluded_from_all_stats(browser_with_special):
    matches, total = browser_with_special.category_stats(ALL_CATEGORIES)
    assert total == 4   # not 5 -- the special entry doesn't inflate the catch-all count
    assert matches == 4


def test_special_category_entry_still_counts_in_its_own_stats(browser_with_special):
    matches, total = browser_with_special.category_stats(f'{HIDDEN_FROM_ALL_PREFIX}Special')
    assert (matches, total) == (1, 1)
