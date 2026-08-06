"""Tests for the shared set-clock hint bus on App / VJApi.

Mirrors test_section_bus.py / test_bpm_bus.py -- the bus lets a source that
knows when the set ends (dj-mixer-01's set clock) publish set-level phase/
timing for a finale-aware consumer (auto-vj) to read, without either
depending on the other. Where the section bus says where you are in a
*track*, this says where you are in the *night*. See
docs/planning/auto-vj-phrase-structure-plan-2026-08-05.md section 6.3.
"""
from __future__ import annotations

import time

from unicornviz.app import App


def _bus() -> App:
    a = App.__new__(App)          # bypass heavy __init__; exercise the bus only
    a._session_hints = {}
    return a


def test_publish_and_get() -> None:
    a = _bus()
    payload = {'phase': 'final', 'source': 'last_track', 'seconds_left': 240.0}
    a.publish_session('dj_mixer', payload)
    assert a.get_session() == payload
    assert a.get_session(exclude='dj_mixer') is None   # only source excluded


def test_publish_returns_a_copy_not_the_original_dict() -> None:
    """Caller mutating their own dict after publishing must not corrupt
    what's stored, and the caller must not be able to mutate the bus's
    copy back through what get_session() returns either."""
    a = _bus()
    payload = {'phase': 'running'}
    a.publish_session('dj_mixer', payload)
    payload['phase'] = 'closing'
    assert a.get_session()['phase'] == 'running'

    got = a.get_session()
    got['phase'] = 'over'
    assert a.get_session()['phase'] == 'running'


def test_missing_source_or_non_dict_payload_ignored() -> None:
    a = _bus()
    a.publish_session('', {'phase': 'running'})
    a.publish_session('dj_mixer', 'not a dict')  # type: ignore[arg-type]
    assert a.get_session() is None


def test_unrecognized_phase_ignored() -> None:
    a = _bus()
    a.publish_session('dj_mixer', {'phase': 'intermission'})  # not canonical
    assert a.get_session() is None


def test_missing_phase_ignored() -> None:
    a = _bus()
    a.publish_session('dj_mixer', {'seconds_left': 60.0})
    assert a.get_session() is None


def test_freshest_source_wins() -> None:
    a = _bus()
    a.publish_session('auto_vj', {'phase': 'running'})
    a.publish_session('dj_mixer', {'phase': 'final'})
    assert a.get_session()['phase'] == 'final'


def test_stale_hints_expire() -> None:
    a = _bus()
    a._session_hints['old'] = ({'phase': 'final'}, time.monotonic() - (App._SESSION_HINT_TTL_S + 10))
    assert a.get_session() is None


def test_all_four_canonical_phases_accepted() -> None:
    for phase in ('running', 'closing', 'final', 'over'):
        a = _bus()
        a.publish_session('dj_mixer', {'phase': phase})
        assert a.get_session()['phase'] == phase
