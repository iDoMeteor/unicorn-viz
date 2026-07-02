"""Configuration-profile store + App effect-override layer — regression tests.

Foundation (Increment 1) for the configuration editor. Covers:

* ``ConfigProfileStore`` round-trip / list / delete / atomic-file behaviour.
* ``App`` effect-parameter override layer: set/live-apply, snapshot, save, load,
  clear, and the ``_instantiate`` merge that pins overrides over config.toml.

The App is exercised via ``__new__`` with a tiny stub effect + config so no GL
context is needed.
"""
from __future__ import annotations

from pathlib import Path

from unicornviz.app import App
from unicornviz.config_profiles import ConfigProfileStore


# --------------------------------------------------------------------------- #
# ConfigProfileStore
# --------------------------------------------------------------------------- #

def test_store_roundtrip_and_persistence(tmp_path: Path) -> None:
    p = tmp_path / 'config_profiles.json'
    store = ConfigProfileStore(p)
    assert store.names() == []
    store.save('Neon Night', {'effects': {'Plasma': {'speed': 1.4}}})
    assert store.names() == ['Neon Night']
    assert store.get('Neon Night') == {'effects': {'Plasma': {'speed': 1.4}}}
    assert 'Neon Night' in store

    # Reloaded from disk by a fresh store instance.
    store2 = ConfigProfileStore(p)
    assert store2.get('Neon Night') == {'effects': {'Plasma': {'speed': 1.4}}}


def test_store_overwrite_and_delete(tmp_path: Path) -> None:
    store = ConfigProfileStore(tmp_path / 'cp.json')
    store.save('A', {'effects': {}})
    store.save('A', {'effects': {'Tunnel': {'zoom': 2.0}}})
    assert store.get('A') == {'effects': {'Tunnel': {'zoom': 2.0}}}
    assert store.delete('A') is True
    assert store.delete('A') is False
    assert store.names() == []


def test_store_rejects_blank_name(tmp_path: Path) -> None:
    store = ConfigProfileStore(tmp_path / 'cp.json')
    for bad in ('', '   '):
        try:
            store.save(bad, {})
        except ValueError:
            continue
        raise AssertionError('blank profile name should raise ValueError')


def test_store_get_returns_copy(tmp_path: Path) -> None:
    store = ConfigProfileStore(tmp_path / 'cp.json')
    store.save('X', {'effects': {'Plasma': {'speed': 1.0}}})
    got = store.get('X')
    got['effects']['Plasma']['speed'] = 99.0  # mutate the copy
    assert store.get('X')['effects']['Plasma']['speed'] == 1.0


def test_store_survives_corrupt_file(tmp_path: Path) -> None:
    p = tmp_path / 'cp.json'
    p.write_text('{ this is not json', encoding='utf-8')
    store = ConfigProfileStore(p)  # must not raise
    assert store.names() == []


# --------------------------------------------------------------------------- #
# App effect-override layer
# --------------------------------------------------------------------------- #

class _StubEffect:
    def __init__(self, params: dict[str, float]) -> None:
        self.parameters = dict(params)


class _StubCfg:
    def __init__(self, effects: dict) -> None:
        self._effects = effects

    def get(self, section, key=None, default=None):
        if section == 'effects' and key is not None:
            return self._effects.get(key, default)
        return default


def _app(tmp_path: Path, effects_cfg=None, current=None) -> App:
    app = object.__new__(App)
    app.cfg = _StubCfg(effects_cfg or {})
    app._config_profile_store = ConfigProfileStore(tmp_path / 'cp.json')
    app._effect_config_overrides = {}
    app._current_effect = current
    # Profile save/load aggregates all setting specs, which read these.
    app._audio_manager = None
    app._effect_duration = 30.0
    app._render_scale = 1.0
    app._color_grade = None
    app._audio_out = None
    return app


def test_set_effect_parameter_records_override(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.set_effect_parameter('Plasma', 'speed', 1.5)
    assert app.config_overrides_snapshot() == {'Plasma': {'speed': 1.5}}


def test_set_effect_parameter_live_applies_to_active_effect(tmp_path: Path) -> None:
    eff = _StubEffect({'speed': 1.0, 'hue': 0.2})

    class _Plasma(_StubEffect):
        pass

    eff = _Plasma({'speed': 1.0, 'hue': 0.2})
    app = _app(tmp_path, current=eff)
    # Active class name must match the override target.
    app.set_effect_parameter('_Plasma', 'speed', 2.5)
    assert eff.parameters['speed'] == 2.5  # applied live
    # A parameter the effect doesn't have is recorded but not injected.
    app.set_effect_parameter('_Plasma', 'ghost', 9.0)
    assert 'ghost' not in eff.parameters
    assert app.config_overrides_snapshot()['_Plasma']['ghost'] == 9.0


def test_effect_parameters_reads_config_and_override(tmp_path: Path) -> None:
    app = _app(tmp_path, effects_cfg={'Tunnel': {'zoom': 1.0, 'twist': 0.5}})
    assert app.effect_parameters('Tunnel') == {'zoom': 1.0, 'twist': 0.5}
    app.set_effect_parameter('Tunnel', 'zoom', 3.0)
    assert app.effect_parameters('Tunnel')['zoom'] == 3.0  # override wins


def test_save_and_load_config_profile(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.set_effect_parameter('Plasma', 'speed', 1.4)
    app.set_effect_parameter('Tunnel', 'zoom', 2.0)
    app.save_config_profile('Set A')
    assert 'Set A' in app.config_profile_names()

    # New app instance, same store dir → load repopulates overrides.
    app2 = _app(tmp_path)
    assert app2.config_overrides_snapshot() == {}
    assert app2.load_config_profile('Set A') is True
    assert app2.config_overrides_snapshot() == {
        'Plasma': {'speed': 1.4}, 'Tunnel': {'zoom': 2.0}
    }
    assert app2.load_config_profile('nope') is False


def test_clear_effect_overrides(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.set_effect_parameter('Plasma', 'speed', 1.4)
    app.clear_effect_overrides('Plasma')
    assert app.config_overrides_snapshot() == {}


def test_instantiate_merges_override_over_config(tmp_path: Path) -> None:
    # Verify the _instantiate merge order: override pins over config.toml.
    captured: dict = {}

    class _FakeEffect:
        NAME = 'Fake'

        def __init__(self, ctx, w, h, cfg):
            captured.update(cfg)

    app = _app(tmp_path, effects_cfg={'_FakeEffect': {'speed': 1.0, 'hue': 0.5}})
    app._ctx = object()
    app._width = 100
    app._height = 100
    app.set_effect_parameter('_FakeEffect', 'speed', 9.9)
    app._instantiate(_FakeEffect)
    assert captured == {'speed': 9.9, 'hue': 0.5}  # override wins on 'speed'
