from __future__ import annotations

from pathlib import Path

from unicornviz.app import App, _NullPostFxController
from unicornviz.config import Config


def _default_cfg() -> Config:
    return Config(Path('tests') / '_missing_config_for_tests.toml')


def test_vj_api_state_safe_with_null_postfx_controller() -> None:
    app = App(_default_cfg())
    app._postfx_controller = _NullPostFxController(None, 1920, 1080, None)

    state = app.vj_api.state()

    assert state.postfx_slot == 0
    assert state.is_postfx_active is False


def test_vj_api_clear_postfx_safe_with_null_postfx_controller() -> None:
    app = App(_default_cfg())
    app._postfx_controller = _NullPostFxController(None, 1920, 1080, None)

    assert app.vj_api.clear_postfx() is True
    assert app.vj_api.set_postfx_slot(0) is True


def test_vj_api_clear_postfx_returns_false_when_method_missing() -> None:
    class _ControllerWithoutClear:
        active_slot = 0

        def is_active(self) -> bool:
            return False

    app = App(_default_cfg())
    app._postfx_controller = _ControllerWithoutClear()

    assert app.vj_api.clear_postfx() is False
