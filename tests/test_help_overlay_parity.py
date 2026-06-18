"""Tests: hotkey help-overlay parity.

Validates that CORE_HELP_SECTIONS contains entries for the keys that are
known to be dispatched, with particular focus on entries added or corrected
in this audit cycle (F6, H/?, Shift+H).

These tests are intentionally light and structural: they verify that the
documented key strings appear somewhere in the help data rather than
performing exhaustive parity (which would require parsing hotkeys.py).
"""
from __future__ import annotations

import pytest

from unicornviz.overlays import Overlays


def _all_help_key_strings() -> list[str]:
    """Flatten all (key, description) pairs from CORE_HELP_SECTIONS."""
    keys = []
    for _section, entries in Overlays.CORE_HELP_SECTIONS:
        for key_str, _desc in entries:
            keys.append(key_str)
    return keys


def test_core_help_sections_not_empty() -> None:
    assert len(Overlays.CORE_HELP_SECTIONS) >= 4


def test_h_toggle_is_documented() -> None:
    """H is the primary help toggle — must appear as 'H / ?'."""
    keys = _all_help_key_strings()
    assert any('H' in k for k in keys), 'H key must be documented in CORE_HELP_SECTIONS'


def test_shift_h_notifications_is_documented() -> None:
    """Shift+H toggles notification flashes — must appear in help."""
    keys = _all_help_key_strings()
    assert any('Shift+H' in k for k in keys), 'Shift+H must be documented in CORE_HELP_SECTIONS'


def test_question_mark_alias_is_documented() -> None:
    """? is an alias for H (help toggle) — must appear in help."""
    keys = _all_help_key_strings()
    assert any('?' in k for k in keys), '? key must be documented in CORE_HELP_SECTIONS'


def test_f6_speed_random_is_documented() -> None:
    """F6 toggles speed randomization — must appear in help Tweakables section."""
    tweakables_entries = []
    for section, entries in Overlays.CORE_HELP_SECTIONS:
        if 'Tweak' in section:
            tweakables_entries.extend(k for k, _d in entries)
    assert any('F6' in k for k in tweakables_entries), \
        'F6 speed random must be documented in the Tweakables help section'


def test_f7_reactivity_random_is_documented() -> None:
    """F7 toggles reactivity randomization — regression guard."""
    tweakables_entries = []
    for section, entries in Overlays.CORE_HELP_SECTIONS:
        if 'Tweak' in section:
            tweakables_entries.extend(k for k, _d in entries)
    assert any('F7' in k for k in tweakables_entries), \
        'F7 reactivity random must be in Tweakables section (regression guard)'


def test_h_entry_description_is_help_not_notifications() -> None:
    """H must be described as toggle-help, not notifications (regression guard)."""
    for _section, entries in Overlays.CORE_HELP_SECTIONS:
        for key_str, desc in entries:
            if 'H' in key_str and 'Shift' not in key_str and '?' in key_str:
                assert 'help' in desc.lower() or 'overlay' in desc.lower(), \
                    f'H/? entry description should mention help/overlay, got: {desc!r}'
                break


def test_shift_h_description_mentions_notifications() -> None:
    """Shift+H entry must describe notifications, not help toggle."""
    for _section, entries in Overlays.CORE_HELP_SECTIONS:
        for key_str, desc in entries:
            if key_str == 'Shift+H':
                assert 'notif' in desc.lower() or 'flash' in desc.lower(), \
                    f'Shift+H description should mention notifications/flash, got: {desc!r}'
                break
