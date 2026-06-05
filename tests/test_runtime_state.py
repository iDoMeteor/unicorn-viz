from __future__ import annotations

import json
from pathlib import Path

from unicornviz.app import App
from unicornviz.config import Config
from unicornviz.runtime_state import RuntimeStateStore


def _default_cfg() -> Config:
    return Config(Path('tests') / '_missing_config_for_tests.toml')


def test_runtime_state_store_set_get_persists_to_disk(tmp_path) -> None:
    state_path = tmp_path / 'runtime' / 'global_state.json'
    store = RuntimeStateStore(state_path)

    store.set('webcam.per_camera.2.brightness', 1.25)
    store.set('teams.audio.selected_source', 'default')

    reloaded = RuntimeStateStore(state_path)
    assert reloaded.get('webcam.per_camera.2.brightness') == 1.25
    assert reloaded.get('teams.audio.selected_source') == 'default'

    persisted = json.loads(state_path.read_text(encoding='utf-8'))
    assert persisted['_meta']['schema'] == 'unicornviz.runtime_state'
    assert persisted['_meta']['schema_version'] == 1
    assert persisted['_meta']['store'] == 'global'


def test_runtime_state_store_upgrades_legacy_payload(tmp_path) -> None:
    state_path = tmp_path / 'runtime' / 'global_state.json'
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text('{"webcam": {"selected_camera": 2}}', encoding='utf-8')

    store = RuntimeStateStore(state_path)
    assert store.get('webcam.selected_camera') == 2
    assert store.get('_meta.schema') == 'unicornviz.runtime_state'
    assert store.get('_meta.schema_version') == 1

    upgraded = json.loads(state_path.read_text(encoding='utf-8'))
    assert upgraded['_meta']['schema'] == 'unicornviz.runtime_state'


def test_app_webcam_mutations_persist_shared_runtime_state(tmp_path) -> None:
    class _FakeWebcamSystem:
        def __init__(self) -> None:
            self._selected = 1
            self._brightness = 1.0

        def set_active_camera(self, camera_id: int) -> str | None:
            self._selected = int(camera_id)
            return str(camera_id)

        def set_brightness(self, value: float) -> float:
            self._brightness = float(value)
            return self._brightness

        def get_persistence_state(self) -> dict[str, object]:
            return {
                'selected_camera': int(self._selected),
                'disabled_cameras': [],
                'layout': 'bottom_right',
                'pip_scale': 0.33,
                'treatment': 'neon',
                'auto_cycle': False,
                'per_camera': {
                    str(self._selected): {
                        'brightness': float(self._brightness),
                        'contrast': 1.0,
                        'flip_horizontal': True,
                        'flip_vertical': False,
                    }
                },
            }

    app = App(_default_cfg())
    runtime_path = tmp_path / 'runtime' / 'global_state.json'
    app._runtime_state = RuntimeStateStore(runtime_path)
    app._webcam_system = _FakeWebcamSystem()

    assert app.set_active_webcam_camera(4) == '4'
    assert app.set_webcam_brightness(1.4) == 1.4

    reloaded = RuntimeStateStore(runtime_path)
    assert reloaded.get('webcam.selected_camera') == 4
    assert reloaded.get('webcam.per_camera.4.brightness') == 1.4


def test_vj_api_runtime_state_helpers_round_trip(tmp_path) -> None:
    app = App(_default_cfg())
    runtime_path = tmp_path / 'runtime' / 'global_state.json'
    app._runtime_state = RuntimeStateStore(runtime_path)

    assert app.vj_api.set_runtime_state('teams.audio.leveling.mode', 'smart') is True
    assert app.vj_api.get_runtime_state('teams.audio.leveling.mode') == 'smart'
