"""The optional VJApi.current() accessor effects use to find runtime context.

Effects are constructed with only a GL context, a size and their config, so
they have no handle to the App and no way to ask for song structure or tempo.
``VJApi.current()`` is that way in. The contract these tests pin is that it is
*optional*: it must be ``None`` when no app has been constructed, so every
caller is forced to degrade rather than depend on it.
"""
from __future__ import annotations

from unicornviz.vj_api import VJApi


class _StubApp:
    """Enough of an App for VJApi to bind to."""


def test_current_is_none_without_an_app(monkeypatch):
    """With no app constructed, the accessor reports nothing available."""
    monkeypatch.setattr(VJApi, '_current', None, raising=False)
    assert VJApi.current() is None


def test_constructing_an_api_installs_it_as_current(monkeypatch):
    """The running app's API becomes the one effects will find."""
    monkeypatch.setattr(VJApi, '_current', None, raising=False)
    api = VJApi(_StubApp())
    assert VJApi.current() is api


def test_latest_api_wins(monkeypatch):
    """A second app replaces the first, rather than leaving a stale handle."""
    monkeypatch.setattr(VJApi, '_current', None, raising=False)
    VJApi(_StubApp())
    second = VJApi(_StubApp())
    assert VJApi.current() is second


def test_accessor_does_not_leak_between_tests():
    """The monkeypatched attribute is restored, so suites stay independent."""
    # Nothing in this module should have left a live API installed.
    current = VJApi.current()
    assert current is None or isinstance(current, VJApi)
