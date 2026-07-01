"""Tests for the shared effect-catalog helper (``registry.browser_entries``).

Both the effects-browser modal and the control-room effect list consume this,
so it must stay a faithful, one-per-effect view of the registry with correct
pack + canonical-category derivation.
"""
from __future__ import annotations

from unicornviz.effects.registry import BrowserEntry, browser_entries, get_effects


def test_one_entry_per_effect():
    entries = browser_entries()
    assert len(entries) == len(get_effects())
    assert len({e.name for e in entries}) == len(entries), 'duplicate names'


def test_entries_are_frozen_browser_entries():
    for e in browser_entries():
        assert isinstance(e, BrowserEntry)
        assert isinstance(e.tags, tuple)


def test_category_is_first_tag():
    for e in browser_entries():
        if e.tags:
            assert e.category == e.tags[0], f'{e.name} category != first tag'
        else:
            assert e.category == e.pack


def test_core_analyzers_are_core_pack():
    by = {e.name: e for e in browser_entries()}
    for name in ('Audio Spectrum', 'Audio Waveforms', 'Audio Sine'):
        assert by[name].pack == 'core'
        assert by[name].category == 'analyzer'


def test_pack_effects_report_their_dropin_dir():
    by = {e.name: e for e in browser_entries()}
    assert by['Tron Grid'].pack == 'tech-01'
    assert by['Cathedral of Bass'].pack == 'immersive-01'
    assert by['Plasma'].pack == 'psychedelic-01'


def test_sorted_like_get_effects():
    assert [e.name for e in browser_entries()] == [c.NAME for c in get_effects()]
