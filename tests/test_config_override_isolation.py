"""B P2-1 (audit 2026-09-30): ``Config.set_override()`` wrote into shared state.

``self._data = dict(_DEFAULTS)`` and ``_deep_merge`` were shallow, so a section
the TOML did not mention *was* the module-level ``_DEFAULTS[section]`` dict, and
a section present only in the TOML *was* ``self._file_data[section]``.  An
in-place override therefore changed every later ``Config`` (and what
``validate()`` type-checks against) and broke ``file_value()``'s contract of
returning only what config.toml itself sets, which the config-to-menu
migration relies on.
"""
from __future__ import annotations

import copy
from pathlib import Path

from unicornviz import config as config_mod
from unicornviz.config import Config

_MISSING = Path('tests') / '_missing_config_for_tests.toml'


def test_an_override_does_not_change_the_module_defaults_or_later_configs() -> None:
    before = copy.deepcopy(config_mod._DEFAULTS)
    c = Config(_MISSING)
    c.set_override('audio', 'latency', 'high')
    assert c.get('audio', 'latency') == 'high'                 # the override works on this instance
    assert config_mod._DEFAULTS == before                      # but the shared defaults are untouched
    fresh = Config(_MISSING)
    assert fresh.get('audio', 'latency') == before['audio']['latency']
    fresh.validate()                                           # validated against the real default


def test_nested_overrides_do_not_leak_either() -> None:
    before = copy.deepcopy(config_mod._DEFAULTS)
    c = Config(_MISSING)
    c.set_override('window', 'new.deeply.nested', 1)
    c.set_override('demo', 'transition', 'cut')
    assert config_mod._DEFAULTS == before


def test_two_configs_are_independent() -> None:
    a, b = Config(_MISSING), Config(_MISSING)
    a.set_override('audio', 'latency', 'high')
    assert b.get('audio', 'latency') != 'high'


def test_file_value_still_means_what_the_toml_set(tmp_path) -> None:
    toml = tmp_path / 'config.toml'
    toml.write_text('[spotify.web_api]\nenabled = false\n[mydropin]\nflag = 1\n', encoding='utf-8')
    c = Config(toml)
    c.set_override('spotify', 'web_api.enabled', True)
    c.set_override('mydropin', 'flag', 99)
    assert c.get('spotify', 'web_api', 'enabled') is True       # the effective value changed
    assert c.get('mydropin', 'flag') == 99
    assert c.file_value('spotify', 'web_api', 'enabled') is False    # what the FILE says did not
    assert c.file_value('mydropin', 'flag') == 1


def test_a_cli_overrides_dict_is_not_mutated_by_later_set_override() -> None:
    overrides = {'demo': {'mode': 'random'}, 'custom': {'a': {'b': 1}}}
    snapshot = copy.deepcopy(overrides)
    c = Config(_MISSING, overrides=overrides)
    c.set_override('custom', 'a.b', 2)
    c.set_override('demo', 'mode', 'sequential')
    assert overrides == snapshot


def test_the_parsed_toml_is_isolated_from_the_effective_data(tmp_path) -> None:
    toml = tmp_path / 'config.toml'
    toml.write_text('[audio]\nlatency = "low"\n', encoding='utf-8')
    c = Config(toml)
    c.set_override('audio', 'latency', 'high')
    assert c.file_value('audio', 'latency') == 'low'
    assert c.get('audio', 'latency') == 'high'


def test_a_missing_file_with_overrides_still_merges_over_defaults() -> None:
    c = Config(_MISSING, overrides={'audio': {'latency': 'high'}})
    assert c.get('audio', 'latency') == 'high'
    assert c.get('audio', 'device') == config_mod._DEFAULTS['audio']['device']   # siblings kept
