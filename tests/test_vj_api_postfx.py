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


def test_vj_api_active_now_playing_returns_registered_source() -> None:
    app = App(_default_cfg())
    app.vj_api.register_now_playing(
        'dj_mixer', lambda: {'available': True, 'is_playing': True, 'title': 'Test'},
        priority=30)

    result = app.vj_api.active_now_playing()

    assert result is not None
    name, snap = result
    assert name == 'dj_mixer'
    assert snap['title'] == 'Test'


def test_vj_api_active_now_playing_none_when_nothing_registered() -> None:
    app = App(_default_cfg())

    assert app.vj_api.active_now_playing() is None


def test_vj_api_publish_and_get_section() -> None:
    app = App(_default_cfg())
    payload = {'role': 'PEAK', 'tier': 'major', 'bars_in': 4.0, 'confidence': 0.9}

    app.vj_api.publish_section('dj_mixer', payload)

    assert app.vj_api.get_section() == payload
    assert app.vj_api.get_section(exclude='dj_mixer') is None


def test_vj_api_get_section_none_when_nothing_published() -> None:
    app = App(_default_cfg())

    assert app.vj_api.get_section() is None


def test_vj_api_camera_navigation_delegates_to_webcam_system() -> None:
    class _FakeWebcamSystem:
        def next_camera(self) -> str:
            return '/dev/video2'

        def prev_camera(self) -> str:
            return '/dev/video1'

    app = App(_default_cfg())
    app._webcam_system = _FakeWebcamSystem()

    assert app.vj_api.goto_next_camera() == '/dev/video2'
    assert app.vj_api.goto_prev_camera() == '/dev/video1'


def test_vj_api_set_active_camera_delegates_to_webcam_system() -> None:
    class _FakeWebcamSystem:
        def set_active_camera(self, camera_id: int) -> str | None:
            if camera_id == 4:
                return '/dev/video4'
            return None

    app = App(_default_cfg())
    app._webcam_system = _FakeWebcamSystem()

    assert app.vj_api.set_active_webcam_camera(4) == '/dev/video4'
    assert app.vj_api.set_active_webcam_camera(7) is None


def test_vj_api_camera_navigation_safe_when_webcam_unavailable() -> None:
    app = App(_default_cfg())
    app._webcam_system = None

    assert app.vj_api.goto_next_camera() is None
    assert app.vj_api.goto_prev_camera() is None
    assert app.vj_api.set_active_webcam_camera(1) is None
