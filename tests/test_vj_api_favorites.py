"""VJApi favorites pass-through — regression tests.

Thin wrapper layer over App.favorite_effects()/favorite_slot_for()/
toggle_favorite() (see test_effects_browser_favorites.py for the underlying
mechanics), plus goto_favorite_slot() -- the resolve-and-jump convenience a
future MIDI pad handler (Akai APC mini clip-launch grid) will call directly,
per the "drop-ins go through vj_api, not app._private" rule.
"""
from __future__ import annotations

from unicornviz.vj_api import VJApi


class _StubApp:
    def __init__(self) -> None:
        self._favorites: dict[int, str] = {}

    def favorite_effects(self) -> dict[int, str]:
        return dict(self._favorites)

    def favorite_slot_for(self, name: str):
        for slot, favored in self._favorites.items():
            if favored == name:
                return slot
        return None

    def toggle_favorite(self, name: str):
        slot = self.favorite_slot_for(name)
        if slot is not None:
            del self._favorites[slot]
            return False, f'{name}: removed from favorites'
        for candidate in range(16):
            if candidate not in self._favorites:
                self._favorites[candidate] = name
                return True, f'{name}: favorited (slot {candidate + 1})'
        return False, 'Favorites full (16 max)'


def _api() -> VJApi:
    return VJApi(_StubApp())


def test_favorite_effects_reflects_app_state() -> None:
    api = _api()
    assert api.favorite_effects() == {}
    api.toggle_favorite('Plasma')
    assert api.favorite_effects() == {0: 'Plasma'}


def test_favorite_slot_for_and_is_favorite() -> None:
    api = _api()
    assert api.is_favorite('Plasma') is False
    api.toggle_favorite('Plasma')
    assert api.favorite_slot_for('Plasma') == 0
    assert api.is_favorite('Plasma') is True


def test_toggle_favorite_returns_status_and_message() -> None:
    api = _api()
    is_fav, msg = api.toggle_favorite('Plasma')
    assert is_fav is True
    assert 'favorited' in msg
    is_fav2, msg2 = api.toggle_favorite('Plasma')
    assert is_fav2 is False
    assert 'removed' in msg2


def test_favorite_surface_degrades_gracefully_on_app_error() -> None:
    class _BrokenApp:
        def favorite_effects(self):
            raise RuntimeError('boom')

        def favorite_slot_for(self, _name):
            raise RuntimeError('boom')

        def toggle_favorite(self, _name):
            raise RuntimeError('boom')

    api = VJApi(_BrokenApp())
    assert api.favorite_effects() == {}
    assert api.favorite_slot_for('Plasma') is None
    assert api.toggle_favorite('Plasma') == (False, 'Favorites unavailable')


# --------------------------------------------------------------------------- #
# goto_favorite_slot: resolve a pad index to an effect and jump
# --------------------------------------------------------------------------- #

class _GotoStubApp(_StubApp):
    def __init__(self) -> None:
        super().__init__()
        self.goto_calls: list[object] = []

    def goto_effect(self, target):
        self.goto_calls.append(target)


def test_goto_favorite_slot_resolves_and_jumps() -> None:
    stub = _GotoStubApp()
    api = VJApi(stub)
    api._resolve_effect_class = lambda target: target  # bypass real registry lookup
    api.toggle_favorite('Plasma')  # slot 0
    assert api.goto_favorite_slot(0) is True
    assert stub.goto_calls == ['Plasma']


def test_goto_favorite_slot_empty_returns_false() -> None:
    stub = _GotoStubApp()
    api = VJApi(stub)
    assert api.goto_favorite_slot(0) is False
    assert stub.goto_calls == []


def test_goto_favorite_slot_out_of_range_returns_false() -> None:
    stub = _GotoStubApp()
    api = VJApi(stub)
    api.toggle_favorite('Plasma')
    assert api.goto_favorite_slot(15) is False
