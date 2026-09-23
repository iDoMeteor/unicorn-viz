"""App._refresh_claimed_audio_devices() -- gathers owned_audio_device_names()
from every contributor and pushes the union to the audio manager, by
convention (no core import of any drop-in).

Regression coverage for the 2026-09-22 lockup: the automatic silence
fallback in audio/capture.py runs maybe_fallback() every frame, and that
path only refuses to switch onto a device if _device_is_claimed() has
something to check against. Before this fix, the claimed-device list was
only ever pushed from get_audio_sources() (the manual selector UI) -- an
entire session with the selector never opened left it permanently empty,
so the fallback happily switched onto hardware the DJ mixer already held
open at real-time priority, and the native stream-open call hung the main
thread. App.run() now calls _refresh_claimed_audio_devices() every frame
(see the comment at its call site, just above get_audio_data()); this file
covers the gathering method itself, not that per-frame wiring (run() is a
giant blocking method with real SDL/GL dependencies -- not practical to
unit test directly, matching this codebase's existing convention for other
per-frame calls).

Hermetic: object.__new__(App) with only _audio_manager and whichever
_CONFIG_CONTRIBUTOR_ATTRS/_dj_mixer/_mixer attributes each test needs.
"""
from __future__ import annotations

from unicornviz.app import App


class _FakeAudioManager:
    def __init__(self) -> None:
        self.claimed_calls: list[set[str]] = []

    def set_claimed_device_names(self, names: set[str]) -> None:
        self.claimed_calls.append(set(names))


def _app(audio_manager=None, **contributors) -> App:
    app = object.__new__(App)
    app._audio_manager = audio_manager
    for attr in App._CONFIG_CONTRIBUTOR_ATTRS + ('_dj_mixer', '_mixer'):
        setattr(app, attr, contributors.get(attr))
    return app


class _Owner:
    def __init__(self, names) -> None:
        self._names = names

    def owned_audio_device_names(self):
        return set(self._names)


class _RaisingOwner:
    def owned_audio_device_names(self):
        raise RuntimeError('device query failed')


def test_gathers_names_from_the_dj_mixer() -> None:
    am = _FakeAudioManager()
    app = _app(audio_manager=am, _dj_mixer=_Owner({'DDJ-REV1: USB Audio'}))
    app._refresh_claimed_audio_devices()
    assert am.claimed_calls == [{'DDJ-REV1: USB Audio'}]


def test_unions_names_from_multiple_contributors() -> None:
    am = _FakeAudioManager()
    app = _app(
        audio_manager=am,
        _dj_mixer=_Owner({'DDJ-REV1: USB Audio'}),
        _control_room=_Owner({'Control Room Loopback'}),
    )
    app._refresh_claimed_audio_devices()
    assert am.claimed_calls == [{'DDJ-REV1: USB Audio', 'Control Room Loopback'}]


def test_contributor_without_the_hook_is_skipped() -> None:
    am = _FakeAudioManager()
    app = _app(audio_manager=am, _dj_mixer=object())
    app._refresh_claimed_audio_devices()
    assert am.claimed_calls == [set()]


def test_a_raising_getter_is_swallowed() -> None:
    am = _FakeAudioManager()
    app = _app(
        audio_manager=am,
        _dj_mixer=_RaisingOwner(),
        _control_room=_Owner({'Control Room Loopback'}),
    )
    app._refresh_claimed_audio_devices()  # must not raise
    assert am.claimed_calls == [{'Control Room Loopback'}]


def test_no_audio_manager_is_a_no_op() -> None:
    app = _app(audio_manager=None, _dj_mixer=_Owner({'DDJ-REV1: USB Audio'}))
    app._refresh_claimed_audio_devices()  # must not raise


def test_a_raising_set_claimed_device_names_is_swallowed() -> None:
    class _BoomManager:
        def set_claimed_device_names(self, names):
            raise RuntimeError('nope')

    app = _app(audio_manager=_BoomManager(), _dj_mixer=_Owner({'DDJ-REV1: USB Audio'}))
    app._refresh_claimed_audio_devices()  # must not raise


def test_falsy_names_are_dropped() -> None:
    am = _FakeAudioManager()
    app = _app(audio_manager=am, _dj_mixer=_Owner({'DDJ-REV1: USB Audio', '', None}))
    app._refresh_claimed_audio_devices()
    assert am.claimed_calls == [{'DDJ-REV1: USB Audio'}]
