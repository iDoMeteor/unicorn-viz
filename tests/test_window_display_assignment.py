"""App-level monitor assignment for the two operator windows (2026-09-22
multi-head Control Room surface consensus, item B: "MOVE MIXER HERE" /
"MOVE CONTROL ROOM HERE" on multi-head-01's Displays page).

Control Room and the mixer have different window lifecycles (see
control_room.py / dj_mixer_controller.py docstrings), so App owns the two
paths differently:
- set_control_room_display() persists then, if open, destroys and recreates
  the whole ControlRoomController the same way toggle_control_room() already
  does (see test_modal_mutual_exclusion.py for that path's own coverage).
- set_mixer_display() just delegates to DjMixerController.set_display_index(),
  which owns its own open/close lifecycle.

Hermetic: object.__new__(App) with only the attributes each method under
test actually touches, and _create_control_room/_destroy_control_room
replaced with instance-level fakes rather than exercising the real
drop-in-loading implementation (unchanged by this work, covered elsewhere).
"""
from __future__ import annotations

from types import SimpleNamespace

from unicornviz.app import App


def _app(control_room=None, dj_mixer=None) -> App:
    app = object.__new__(App)
    app._control_room = control_room
    app._dj_mixer = dj_mixer
    app._runtime_state_calls: list[tuple[str, object]] = []
    app.set_runtime_state = lambda path, value: app._runtime_state_calls.append((path, value))
    return app


# --------------------------------------------------------------------------- #
# set_control_room_display / control_room_display_index
# --------------------------------------------------------------------------- #

def test_set_control_room_display_when_closed_only_persists() -> None:
    app = _app(control_room=None)
    ok, message = app.set_control_room_display(2)
    assert ok is True
    assert message == 'Control Room will open on display 2'
    assert app._runtime_state_calls == [('control_room.display_index', 2)]


def test_set_control_room_display_when_open_closes_and_reopens() -> None:
    app = _app(control_room=SimpleNamespace(is_open=True))
    destroy_calls: list[bool] = []
    create_calls: list[bool] = []

    def _destroy():
        destroy_calls.append(True)
        app._control_room = None
        return True, 'closed'

    def _create():
        create_calls.append(True)
        app._control_room = SimpleNamespace(is_open=True, display_index=2)
        return True, 'opened'

    app._destroy_control_room = _destroy
    app._create_control_room = _create
    ok, message = app.set_control_room_display(2)
    assert destroy_calls == [True]
    assert create_calls == [True]
    assert ok is True
    assert message == 'Control Room moved to display 2'


def test_set_control_room_display_reports_a_reopen_failure() -> None:
    app = _app(control_room=SimpleNamespace(is_open=True))
    app._destroy_control_room = lambda: setattr(app, '_control_room', None)
    app._create_control_room = lambda: (False, 'Control Room failed to reopen')
    ok, message = app.set_control_room_display(3)
    assert ok is False
    assert message == 'Control Room failed to reopen'


def test_set_control_room_display_clamps_negative_index() -> None:
    app = _app(control_room=None)
    ok, message = app.set_control_room_display(-5)
    assert ok is True
    assert message == 'Control Room will open on display 0'
    assert app._runtime_state_calls == [('control_room.display_index', 0)]


def test_control_room_display_index_none_when_closed() -> None:
    assert _app(control_room=None).control_room_display_index() is None
    assert _app(control_room=SimpleNamespace(is_open=False)).control_room_display_index() is None


def test_control_room_display_index_reads_through_when_open() -> None:
    app = _app(control_room=SimpleNamespace(is_open=True, display_index=2))
    assert app.control_room_display_index() == 2


# --------------------------------------------------------------------------- #
# set_mixer_display / mixer_display_index
# --------------------------------------------------------------------------- #

def test_set_mixer_display_delegates_to_the_mixer_controller() -> None:
    calls: list[int] = []

    def _setter(index: int):
        calls.append(index)
        return True, 'Mixer moved to display 2'

    app = _app(dj_mixer=SimpleNamespace(set_display_index=_setter))
    ok, message = app.set_mixer_display(2)
    assert ok is True
    assert message == 'Mixer moved to display 2'
    assert calls == [2]


def test_set_mixer_display_without_dj_mixer_reports_unavailable() -> None:
    app = _app(dj_mixer=None)
    ok, message = app.set_mixer_display(1)
    assert ok is False
    assert message == 'Mixer unavailable'


def test_set_mixer_display_without_setter_reports_unavailable() -> None:
    app = _app(dj_mixer=SimpleNamespace())
    ok, message = app.set_mixer_display(1)
    assert ok is False
    assert message == 'Mixer unavailable'


def test_mixer_display_index_none_without_dj_mixer() -> None:
    assert _app(dj_mixer=None).mixer_display_index() is None


def test_mixer_display_index_reads_through() -> None:
    app = _app(dj_mixer=SimpleNamespace(display_index=1))
    assert app.mixer_display_index() == 1
