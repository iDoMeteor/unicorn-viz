from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


_PROJECTM_EFFECT_PATH = (
    Path(__file__).resolve().parents[1] / 'drop-ins' / 'projectm-01' / 'projectm_effect.py'
)


def _load_projectm_effect_module():
    module_name = 'test_projectm_effect_module'
    spec = importlib.util.spec_from_file_location(
        module_name, _PROJECTM_EFFECT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _make_state_only_effect(module, runtime_state: Path, legacy_state: Path):
    effect = object.__new__(module.ProjectMEffect)
    effect._disabled_presets = set()
    effect._deleted_presets = set()
    effect._runtime_preset_state_file = lambda: runtime_state
    effect._legacy_preset_state_file = lambda: legacy_state
    return effect


def test_projectm_state_migrates_and_persists_across_reload(tmp_path) -> None:
    module = _load_projectm_effect_module()

    runtime_state = tmp_path / 'runtime' / 'projectm' / 'preset_manager_state.json'
    legacy_state = tmp_path / 'drop-ins' / 'projectm-01' / 'preset_manager_state.json'
    legacy_state.parent.mkdir(parents=True, exist_ok=True)
    legacy_payload = {
        'version': 1,
        'disabled_presets': ['/tmp/presets/legacy-off.milk'],
        'deleted_presets': ['/tmp/presets/legacy-del.milk'],
    }
    legacy_state.write_text(json.dumps(legacy_payload), encoding='utf-8')

    effect = _make_state_only_effect(module, runtime_state, legacy_state)
    effect._load_preset_state()

    assert '/tmp/presets/legacy-off.milk' in effect._disabled_presets
    assert '/tmp/presets/legacy-del.milk' in effect._deleted_presets
    assert runtime_state.exists()

    effect._disabled_presets.add('/tmp/presets/new-disabled.milk')
    effect._deleted_presets.add('/tmp/presets/new-deleted.milk')
    effect._save_preset_state()

    reloaded = _make_state_only_effect(module, runtime_state, legacy_state)
    reloaded._load_preset_state()

    assert '/tmp/presets/new-disabled.milk' in reloaded._disabled_presets
    assert '/tmp/presets/new-deleted.milk' in reloaded._deleted_presets

    payload = json.loads(runtime_state.read_text(encoding='utf-8'))
    assert '/tmp/presets/new-disabled.milk' in payload['disabled_presets']
    assert '/tmp/presets/new-deleted.milk' in payload['deleted_presets']
