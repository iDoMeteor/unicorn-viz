"""VJApi pass-through for operator-window monitor assignment (2026-09-22
multi-head Control Room surface consensus, item B) -- thin delegation to
App.set_control_room_display()/control_room_display_index()/
set_mixer_display()/mixer_display_index(), tested at test_app.py's own
level in test_window_display_assignment.py. Mirrors the stub-app pattern
already used for favorites in test_vj_api_favorites.py.
"""
from __future__ import annotations

from unicornviz.vj_api import VJApi


class _StubApp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.control_room_index: int | None = None
        self.mixer_index: int | None = None

    def set_control_room_display(self, index: int) -> tuple[bool, str]:
        self.calls.append(('set_control_room_display', index))
        return True, f'Control Room moved to display {index}'

    def control_room_display_index(self):
        return self.control_room_index

    def set_mixer_display(self, index: int) -> tuple[bool, str]:
        self.calls.append(('set_mixer_display', index))
        return True, f'Mixer moved to display {index}'

    def mixer_display_index(self):
        return self.mixer_index


def _api() -> tuple[VJApi, _StubApp]:
    app = _StubApp()
    return VJApi(app), app


def test_set_control_room_display_delegates_and_coerces_to_int() -> None:
    api, app = _api()
    ok, message = api.set_control_room_display('2')
    assert ok is True
    assert message == 'Control Room moved to display 2'
    assert app.calls == [('set_control_room_display', 2)]


def test_control_room_display_index_reads_through() -> None:
    api, app = _api()
    assert api.control_room_display_index() is None
    app.control_room_index = 2
    assert api.control_room_display_index() == 2


def test_set_mixer_display_delegates_and_coerces_to_int() -> None:
    api, app = _api()
    ok, message = api.set_mixer_display('1')
    assert ok is True
    assert message == 'Mixer moved to display 1'
    assert app.calls == [('set_mixer_display', 1)]


def test_mixer_display_index_reads_through() -> None:
    api, app = _api()
    assert api.mixer_display_index() is None
    app.mixer_index = 1
    assert api.mixer_display_index() == 1
