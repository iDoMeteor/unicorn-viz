"""Tests for the shared song-structure hint bus on App / VJApi.

Mirrors test_bpm_bus.py -- the bus lets a source that has pre-analyzed a
track (dj-mixer's structure.py) publish where the playhead is in the
song's phrase structure for a phrase-aware consumer (auto-vj) to read,
without either depending on the other. See
docs/planning/auto-vj-phrase-structure-plan-2026-08-05.md section 6.
"""
from __future__ import annotations

import time

from unicornviz.app import App


def _bus() -> App:
    a = App.__new__(App)          # bypass heavy __init__; exercise the bus only
    a._section_hints = {}
    return a


def test_publish_and_get() -> None:
    a = _bus()
    payload = {'role': 'PEAK', 'tier': 'major', 'bars_in': 4.0, 'confidence': 0.9}
    a.publish_section('dj_mixer', payload)
    assert a.get_section() == payload
    assert a.get_section(exclude='dj_mixer') is None   # only source excluded


def test_publish_returns_a_copy_not_the_original_dict() -> None:
    """Caller mutating their own dict after publishing must not corrupt
    what's stored, and the caller must not be able to mutate the bus's
    copy back through what get_section() returns either."""
    a = _bus()
    payload = {'role': 'PEAK'}
    a.publish_section('dj_mixer', payload)
    payload['role'] = 'FALL'
    assert a.get_section()['role'] == 'PEAK'

    got = a.get_section()
    got['role'] = 'CLOSE'
    assert a.get_section()['role'] == 'PEAK'


def test_missing_source_or_non_dict_payload_ignored() -> None:
    a = _bus()
    a.publish_section('', {'role': 'PEAK'})
    a.publish_section('dj_mixer', 'not a dict')  # type: ignore[arg-type]
    assert a.get_section() is None


def test_unrecognized_role_ignored() -> None:
    a = _bus()
    a.publish_section('dj_mixer', {'role': 'CHORUS'})  # not a canonical role
    assert a.get_section() is None


def test_missing_role_ignored() -> None:
    a = _bus()
    a.publish_section('dj_mixer', {'tier': 'major'})
    assert a.get_section() is None


def test_freshest_source_wins() -> None:
    a = _bus()
    a.publish_section('auto_vj', {'role': 'HOLD'})
    a.publish_section('dj_mixer', {'role': 'PEAK'})
    assert a.get_section()['role'] == 'PEAK'


def test_stale_hints_expire() -> None:
    a = _bus()
    a._section_hints['old'] = ({'role': 'PEAK'}, time.monotonic() - (App._SECTION_HINT_TTL_S + 10))
    assert a.get_section() is None


def test_all_five_canonical_roles_accepted() -> None:
    a = _bus()
    for role in ('HOLD', 'RISE', 'PEAK', 'FALL', 'CLOSE'):
        a = _bus()
        a.publish_section('dj_mixer', {'role': role})
        assert a.get_section()['role'] == role
