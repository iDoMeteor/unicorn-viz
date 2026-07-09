"""Tests for the shared BPM hint bus on App / VJApi.

The bus lets tempo-aware drop-ins (dj-mixer, auto-vj) publish and read a BPM so
they interoperate without depending on one another.
"""
from __future__ import annotations

import time

from unicornviz.app import App


def _bus() -> App:
    a = App.__new__(App)          # bypass heavy __init__; exercise the bus only
    a._bpm_hints = {}
    return a


def test_publish_and_get() -> None:
    a = _bus()
    a.publish_bpm('dj_mixer', 128.0)
    assert a.get_bpm() == 128.0
    assert a.get_bpm(exclude='dj_mixer') == 0.0   # only source excluded


def test_nonpositive_and_bad_values_ignored() -> None:
    a = _bus()
    a.publish_bpm('x', 0.0)
    a.publish_bpm('y', -12.0)
    a.publish_bpm('z', 'nope')  # type: ignore[arg-type]
    assert a.get_bpm() == 0.0


def test_freshest_source_wins() -> None:
    a = _bus()
    a.publish_bpm('auto_vj', 120.0)
    a.publish_bpm('dj_mixer', 126.0)
    assert a.get_bpm() == 126.0


def test_stale_hints_expire() -> None:
    a = _bus()
    a._bpm_hints['old'] = (120.0, time.monotonic() - (App._BPM_HINT_TTL_S + 10))
    assert a.get_bpm() == 0.0
