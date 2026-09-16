"""Runtime-capability discovery, loaded-only mode (wires the dormant helper).

``discover_runtime_capabilities(loaded_only=True)`` inspects only modules the
app already imported (the drop-in module cache) so an operator surface can
ask "what is loaded?" without importing anything new.
"""
from __future__ import annotations

from pathlib import Path
from types import ModuleType

from unicornviz import dropins
from unicornviz.vj_api import VJApi


def _fake_module(name: str, payload) -> ModuleType:
    mod = ModuleType(name)
    mod.DROPIN_CAPABILITIES = payload
    return mod


def test_loaded_only_reads_the_module_cache_and_imports_nothing(monkeypatch, tmp_path: Path) -> None:
    cache = {
        tmp_path / 'banner-01' / 'banner_controller.py': _fake_module(
            'banner', {'name': 'banner', 'subsystem_name': 'banner'}),
        tmp_path / 'osc-bridge-01' / 'osc.py': _fake_module(
            'osc', [{'name': 'osc', 'subsystem_name': 'osc'}, 'not a dict']),
        tmp_path / 'plain-01' / 'plain.py': ModuleType('plain'),
    }
    monkeypatch.setattr(dropins, '_MODULE_CACHE', cache)

    def _never(*_a, **_k):
        raise AssertionError('loaded_only must not import')
    monkeypatch.setattr(dropins, '_load_module_from_file', _never)
    found = dropins.discover_runtime_capabilities(loaded_only=True)
    assert sorted(c['name'] for c in found) == ['banner', 'osc']
    banner = next(c for c in found if c['name'] == 'banner')
    assert banner['dropin'] == 'banner-01' and banner['file'] == 'banner_controller.py'
    assert banner['subsystem_name'] == 'banner'


def test_vj_api_exposes_loaded_capabilities_and_subsystem_names(monkeypatch, tmp_path: Path) -> None:
    class _App:
        _subsystems = {'banner': object(), 'control_room': object()}

    api = VJApi.__new__(VJApi)
    api._app = _App()
    assert api.subsystem_names() == ['banner', 'control_room']
    monkeypatch.setattr(dropins, '_MODULE_CACHE', {
        tmp_path / 'banner-01' / 'banner_controller.py': _fake_module(
            'banner', {'name': 'banner', 'subsystem_name': 'banner'}),
    })
    assert [c['name'] for c in api.dropin_capabilities()] == ['banner']
