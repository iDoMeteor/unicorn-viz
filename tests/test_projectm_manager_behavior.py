from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_PROJECTM_EFFECT_PATH = (
    Path(__file__).resolve().parents[1] / 'drop-ins' / 'projectm-01' / 'projectm_effect.py'
)


def _load_projectm_effect_module():
    module_name = 'test_projectm_manager_behavior_module'
    spec = importlib.util.spec_from_file_location(module_name, _PROJECTM_EFFECT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _write_preset(root: Path, relative_path: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('preset', encoding='utf-8')
    return path


def _make_effect(module, roots: list[Path], tmp_path: Path):
    effect = object.__new__(module.ProjectMEffect)
    effect._disabled_presets = set()
    effect._deleted_presets = set()
    effect._preset_catalog = []
    effect._preset_paths = []
    effect._preset_index = 0
    effect._active_label = ''
    effect._bridge = None
    effect.failed_presets = {}
    effect.config = {}
    effect._preset_dirs = lambda: list(roots)
    effect._exclude_dirs = lambda: frozenset()
    effect._load_dark_excluded = lambda: set()
    effect._runtime_preset_state_file = lambda: tmp_path / 'runtime' / 'projectm' / 'preset_manager_state.json'
    effect._legacy_preset_state_file = lambda: tmp_path / 'drop-ins' / 'projectm-01' / 'preset_manager_state.json'
    effect._preset_trash_dir = lambda: tmp_path / 'preset-trash'
    effect._preset_states_dir = lambda: tmp_path / 'states'
    return effect


class _DummyBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def load_preset(self, preset_path: str, smooth: bool) -> None:
        self.calls.append((preset_path, smooth))


def test_projectm_catalog_infers_categories_and_tags(tmp_path) -> None:
    module = _load_projectm_effect_module()

    presets_root = tmp_path / 'presets'
    alpha = presets_root / 'pack-alpha'
    beta = presets_root / 'pack-beta'

    glow = _write_preset(alpha, 'Fractal/glow-loop.milk')
    spiral = _write_preset(alpha, 'Fractal/spiral-beat.prjm')
    reaction = _write_preset(beta, 'Reaction/beat-spark.milk')
    uncategorized = _write_preset(beta, 'root-level.milk')

    effect = _make_effect(module, [presets_root], tmp_path)
    effect._disabled_presets = {str(reaction.resolve())}
    effect.refresh_preset_catalog(preserve_current=False)

    catalog = {entry['path']: entry for entry in effect.preset_catalog()}

    assert effect.preset_count == 3
    assert effect.list_preset_categories() == {
        '(uncategorized)': 1,
        'Fractal': 2,
        'Reaction': 1,
    }
    assert catalog[str(glow.resolve())]['pack_name'] == 'pack-alpha'
    assert catalog[str(glow.resolve())]['category_key'] == 'Fractal'
    assert catalog[str(glow.resolve())]['enabled'] is True
    assert catalog[str(glow.resolve())]['tags'] == ['fractal', 'glow', 'loop']
    assert catalog[str(spiral.resolve())]['tags'] == ['beat', 'fractal', 'spiral']
    assert catalog[str(reaction.resolve())]['enabled'] is False
    assert catalog[str(uncategorized.resolve())]['category_key'] == '(uncategorized)'
    assert catalog[str(uncategorized.resolve())]['tags'] == ['level', 'root']


def test_projectm_selected_and_category_state_changes(tmp_path) -> None:
    module = _load_projectm_effect_module()

    presets_root = tmp_path / 'presets'
    alpha = presets_root / 'pack-alpha'
    beta = presets_root / 'pack-beta'

    fractal_one = _write_preset(alpha, 'Fractal/glow-loop.milk')
    fractal_two = _write_preset(alpha, 'Fractal/spiral-beat.prjm')
    reaction = _write_preset(beta, 'Reaction/beat-spark.milk')

    effect = _make_effect(module, [presets_root], tmp_path)
    effect.refresh_preset_catalog(preserve_current=False)

    enabled_count = effect.set_presets_enabled([str(reaction.resolve())], False)
    assert enabled_count == 2
    assert str(reaction.resolve()) in effect._disabled_presets

    enabled_count = effect.enable_category('Reaction')
    assert enabled_count == 3
    assert str(reaction.resolve()) not in effect._disabled_presets

    enabled_count = effect.disable_category('Fractal')
    assert enabled_count == 1
    assert effect._disabled_presets == {
        str(fractal_one.resolve()),
        str(fractal_two.resolve()),
    }

    enabled_count = effect.isolate_category('Reaction')
    assert enabled_count == 1
    assert effect._disabled_presets == {
        str(fractal_one.resolve()),
        str(fractal_two.resolve()),
    }
    assert effect.preset_count == 1
    assert effect.current_preset_path == str(reaction.resolve())


def test_projectm_bulk_state_history_undo_redo_and_enable_all(tmp_path) -> None:
    module = _load_projectm_effect_module()

    presets_root = tmp_path / 'presets'
    alpha = presets_root / 'pack-alpha'
    beta = presets_root / 'pack-beta'

    _write_preset(alpha, 'Fractal/glow-loop.milk')
    _write_preset(alpha, 'Fractal/spiral-beat.prjm')
    _write_preset(beta, 'Reaction/beat-spark.milk')

    effect = _make_effect(module, [presets_root], tmp_path)
    effect.refresh_preset_catalog(preserve_current=False)

    enabled_count = effect.disable_category('Reaction')
    assert enabled_count == 2
    assert len(list(effect._preset_states_dir().glob('state-*.json'))) == 1

    enabled_count = effect.disable_all_presets()
    assert enabled_count == 0
    assert len(list(effect._preset_states_dir().glob('state-*.json'))) == 2

    restored = effect.undo_last_bulk_state_change()
    assert restored is not None and restored.startswith('disable-all (')
    assert effect.preset_count == 2
    assert effect._disabled_presets == {
        str((beta / 'Reaction/beat-spark.milk').resolve()),
    }

    redone = effect.redo_last_bulk_state_change()
    assert redone is not None and redone.startswith('redo-step (')
    assert effect.preset_count == 0
    assert effect._disabled_presets == {
        str((alpha / 'Fractal/glow-loop.milk').resolve()),
        str((alpha / 'Fractal/spiral-beat.prjm').resolve()),
        str((beta / 'Reaction/beat-spark.milk').resolve()),
    }

    enabled_count = effect.enable_all_presets()
    assert enabled_count == 3
    assert effect._disabled_presets == set()
    assert effect.preset_count == 3
    assert effect._preset_states_dir().exists()


def test_projectm_delete_preset_moves_to_trash_and_reloads_current(tmp_path) -> None:
    module = _load_projectm_effect_module()

    presets_root = tmp_path / 'presets'
    alpha = presets_root / 'pack-alpha'

    first = _write_preset(alpha, 'Fractal/glow-loop.milk')
    second = _write_preset(alpha, 'Fractal/spiral-beat.prjm')
    third = _write_preset(alpha, 'Reaction/beat-spark.milk')

    effect = _make_effect(module, [presets_root], tmp_path)
    effect.refresh_preset_catalog(preserve_current=False)
    effect._bridge = _DummyBridge()
    effect._preset_index = 1

    deleted = effect.delete_preset(index=1, permanent=False)

    assert deleted == second.stem
    assert not second.exists()
    trash_dir = effect._preset_trash_dir()
    trashed = list(trash_dir.glob('spiral-beat*.prjm'))
    assert trashed
    assert str(second.resolve()) in effect._deleted_presets
    assert str(second.resolve()) not in effect._disabled_presets
    assert effect._bridge.calls
    assert effect._bridge.calls[-1][1] is False
    assert effect._bridge.calls[-1][0] in {str(first.resolve()), str(third.resolve())}
    assert effect.preset_count == 2


def test_projectm_delete_presets_can_delete_multiple_files_permanently(tmp_path) -> None:
    module = _load_projectm_effect_module()

    presets_root = tmp_path / 'presets'
    alpha = presets_root / 'pack-alpha'

    first = _write_preset(alpha, 'Fractal/glow-loop.milk')
    second = _write_preset(alpha, 'Fractal/spiral-beat.prjm')
    third = _write_preset(alpha, 'Reaction/beat-spark.milk')

    effect = _make_effect(module, [presets_root], tmp_path)
    effect.refresh_preset_catalog(preserve_current=False)

    deleted_count = effect.delete_presets([str(first.resolve()), str(third.resolve())], permanent=True)

    assert deleted_count == 2
    assert not first.exists()
    assert not third.exists()
    assert second.exists()
    assert str(first.resolve()) in effect._deleted_presets
    assert str(third.resolve()) in effect._deleted_presets
    assert effect.preset_count == 1
    assert effect.preset_catalog()[0]['path'] == str(second.resolve())