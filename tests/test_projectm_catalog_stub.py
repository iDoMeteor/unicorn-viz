"""The startup catalog prewarm must build through the throwaway stub.

2026-09-05: ``_build_catalog_cache`` creates a bare ``ProjectMEffect`` with
``object.__new__`` and never ran ``_init()``, which is where
``_excluded_presets_cache`` gets set -- so ``_load_excluded_presets()``
raised, both ``prescan`` and ``warm_up`` logged "catalog build failed", and
the first ProjectM activation walked every preset file on the main thread
mid-transition.  This test builds the catalog exactly the way the prewarm
does and asserts it lands.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from unicornviz.dropins import load_dropin_symbol

PM = load_dropin_symbol('projectm-01/projectm_effect.py', 'ProjectMEffect')
_pm_mod = sys.modules[PM.__module__]


def test_stub_catalog_build_succeeds_without_init(tmp_path: Path, caplog, monkeypatch) -> None:
    presets = tmp_path / 'presets'
    presets.mkdir()
    (presets / 'one.milk').write_text('[preset00]\n', encoding='utf-8')
    (presets / 'two.milk').write_text('[preset00]\n', encoding='utf-8')
    (presets / 'notes.txt').write_text('ignored', encoding='utf-8')
    monkeypatch.setattr(_pm_mod, '_catalog_cache', None)
    # Keep the stub's state files inside tmp so a real excluded_presets.txt
    # cannot leak into the count.
    monkeypatch.setattr(PM, '_excluded_presets_file', lambda self: tmp_path / 'excluded.txt')
    monkeypatch.setattr(PM, '_preset_state_file', lambda self: tmp_path / 'state.json')

    with caplog.at_level(logging.WARNING, logger=_pm_mod.log.name):
        PM._build_catalog_cache({'preset_dir': str(presets)}, source='test')

    assert 'catalog build failed' not in caplog.text
    cache = _pm_mod._catalog_cache
    assert cache is not None
    names = sorted(Path(item.path).name for item in cache
                   if str(item.path).startswith(str(presets)))
    assert names == ['one.milk', 'two.milk']
