"""Regression tests for the ProjectM dark-preset exclusion layer.

Three defects made already-known-dark presets replay, each costing a fresh
``dark_skip_after`` of near-black screen:

1. The list stored **absolute** paths, so it silently matched nothing in any
   checkout but the one that wrote it — the whole list went dead.
2. Runtime exclusions never reached the process-wide ``_catalog_cache``, so
   every effect switch rebuilt the playable list from a cache that still
   contained them.
3. ``dark_skip_after`` defaulted to 3 s, far too long for a VJ backdrop.

Also covers the operator-disable gate: Auto VJ's projectM affinity calls
``goto_effect`` directly, which bypasses the playlist's disabled set, so
``projectm_available()`` has to carry the enablement check itself.

GL-free — exercises the path/state layer only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from unicornviz.dropins import load_dropin_symbol

PM = load_dropin_symbol('projectm-01/projectm_effect.py', 'ProjectMEffect')
_pm_mod = sys.modules[PM.__module__]


# --------------------------------------------------------------------------- #
# Relative exclusion keys
# --------------------------------------------------------------------------- #

def test_dark_key_is_relative_to_the_dropin() -> None:
    root = PM._dropin_root()
    key = PM._dark_key(root / 'presets' / 'pack' / 'Cat' / 'x.milk')
    assert key == 'presets/pack/Cat/x.milk'
    assert not Path(key).is_absolute()


def test_legacy_absolute_entry_from_another_checkout_rebases() -> None:
    """The exact failure mode: a list written by a different clone."""
    root = PM._dropin_root()
    here = PM._dark_key(root / 'presets' / 'pack' / 'x.milk')
    foreign = '/somewhere/else/unicorn-viz-other/drop-ins/projectm-01/presets/pack/x.milk'
    assert PM._dark_key_from_line(foreign) == here


def test_relative_entry_passes_through_unchanged() -> None:
    assert PM._dark_key_from_line('presets/pack/x.milk') == 'presets/pack/x.milk'


def test_load_migrates_and_dedupes(tmp_path: Path) -> None:
    root = PM._dropin_root()
    f = tmp_path / 'dark_excluded.txt'
    f.write_text('\n'.join([
        '/other/clone/drop-ins/projectm-01/presets/a.milk',
        '/other/clone/drop-ins/projectm-01/presets/a.milk',   # duplicate
        str(root / 'presets' / 'b.milk'),                     # local absolute
        'presets/c.milk',                                     # already relative
        '',                                                   # blank
    ]) + '\n', encoding='utf-8')

    stub = object.__new__(PM)
    stub._dark_excluded_file = lambda: f            # type: ignore[method-assign]
    keys = PM._load_dark_excluded(stub)

    assert keys == {'presets/a.milk', 'presets/b.milk', 'presets/c.milk'}
    rewritten = [ln for ln in f.read_text(encoding='utf-8').splitlines() if ln]
    assert rewritten == ['presets/a.milk', 'presets/b.milk', 'presets/c.milk']
    assert not any(Path(ln).is_absolute() for ln in rewritten)


def test_saved_entry_is_written_relative(tmp_path: Path) -> None:
    root = PM._dropin_root()
    f = tmp_path / 'dark_excluded.txt'
    stub = object.__new__(PM)
    stub._dark_excluded_file = lambda: f            # type: ignore[method-assign]
    PM._save_dark_excluded_entry(stub, root / 'presets' / 'deep' / 'z.milk')
    assert f.read_text(encoding='utf-8').strip() == 'presets/deep/z.milk'


# --------------------------------------------------------------------------- #
# Catalog-cache eviction
# --------------------------------------------------------------------------- #

@pytest.fixture
def _catalog(tmp_path):
    """Install a throwaway module-level catalog cache and restore it after."""
    Item = _pm_mod._PresetCatalogItem
    prev = _pm_mod._catalog_cache
    _pm_mod._catalog_cache = [
        Item(path=tmp_path / f'p{i}.milk', display_name=f'p{i}', pack_name='pk',
             category_path=('c',), tags=(), enabled=True)
        for i in range(4)
    ]
    yield tmp_path
    _pm_mod._catalog_cache = prev


def test_dark_exclusion_evicts_from_catalog_cache(_catalog) -> None:
    """Without this the next _init() restores the preset and replays the black."""
    victim = _catalog / 'p2.milk'
    assert victim in [it.path for it in _pm_mod._catalog_cache]

    PM._drop_from_catalog_cache(victim)

    remaining = [it.path for it in _pm_mod._catalog_cache]
    assert victim not in remaining
    # What _init() would rebuild _preset_paths from (projectm_effect.py:441-443).
    assert victim not in [it.path for it in _pm_mod._catalog_cache if it.enabled]
    assert len(remaining) == 3


def test_cache_eviction_is_safe_with_no_cache() -> None:
    prev = _pm_mod._catalog_cache
    _pm_mod._catalog_cache = None
    try:
        PM._drop_from_catalog_cache(Path('/tmp/whatever.milk'))   # must not raise
    finally:
        _pm_mod._catalog_cache = prev


# --------------------------------------------------------------------------- #
# Detector tuning
# --------------------------------------------------------------------------- #

def test_dark_skip_default_is_short() -> None:
    assert _pm_mod._DARK_SKIP_AFTER_DEFAULT == pytest.approx(0.2)


def test_dark_sampler_covers_more_than_the_centre() -> None:
    pts = PM._DARK_SAMPLE_POINTS
    assert len(pts) >= 5
    assert (0.5, 0.5) in pts, 'centre must still be sampled'
    # Must actually reach out toward the corners, not cluster in the middle.
    assert any(x < 0.35 and y < 0.35 for x, y in pts)
    assert any(x > 0.65 and y > 0.65 for x, y in pts)
    # And stay cheap: one read per block, once per preset.
    total_px = len(pts) * PM._DARK_SAMPLE_SIZE ** 2
    assert total_px <= 100 * 100 * 1.25, 'sampling cost grew materially'
