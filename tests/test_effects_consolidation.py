"""Regression suite for the effects-consolidation (Option B category packs).

Guards the entire reorganization: audio analyzers stay core, every other
procedural visual lives in its category pack (or stays isolated), the renames
stuck everywhere, and no PING_PONG_FRIENDS reference dangles. GL-free — uses the
registry + source-file inspection only.
"""
from __future__ import annotations

import inspect
from collections import Counter
from pathlib import Path

import pytest

from unicornviz.effects.registry import get_effects

_REPO = Path(__file__).resolve().parents[1]

# --- Expected taxonomy (the settled consolidation map) -----------------------
CORE_NAMES = {
    'Audio Spectrum', 'Audio Spectrogram', 'Audio Tracks', 'Audio Waveforms',
    'Audio Centroid', 'Audio Sine', 'Audio Chromogram', 'Audio Bass Machine',
}
PACK_NAMES = {
    'effects-psychedelic': {'Plasma', 'Kaleidoscope', 'Psychedelic'},
    'effects-games': {'Breakout', 'Neon Pac', 'Galaga', 'Joust', 'Tetris',
                 'Missile Command', 'Donkey Kong', 'Q*bert'},
    'effects-particles': {'Starfield', 'Fireworks', 'Particle Storm'},
    'effects-retro': {'Copper Bars', 'ANSI Viewer', 'Fractal Zoom', 'Escher', 'Dali', 'Van Gogh'},
    'effects-feature': {'Hexy Stars', 'Rainbow Trance', 'Metaballs'},
    'effects-vector': {'3D Cube', 'Vector', 'Disco Ball', 'Laser Tunnel'},
    'effects-cosmic': {'Cosmos', 'Black Hole Cathedral', 'Wavey Gravy', 'Alien Invasion',
                  'Sun Ship 3000'},
    'effects-tech': {'Tron Grid', 'Cyber War', 'Hacker Terminal', 'Hacker Terminal 2.0',
                'Threat Matrix', 'Reactor Breach'},
    'effects-immersive': {'Tunnel', 'Wormhole', 'Cathedral of Bass'},
    'effects-holiday': {'America 250'},
    'effects-flying': {'Warp Drive', 'Cloud Surfer', 'Canyon Run', 'Wingsuit Dive',
                  'Nebula Drift', 'Asteroid Run', 'Portal Flight'},
    'effects-rollercoast': {'First Drop', 'Corkscrew', 'Night Coaster',
                            'Mine Train', 'Coaster Cam', 'Log Flume'},
    'effects-ukiyo-e': {'Floating World', 'Onden Watermill'},
}
ISOLATED_NAMES = {
    'ProjectM Presets', 'Texture Showcase', 'Image Showcase', 'Video Clips',
    'Video Player', 'Sim Showcase', 'Unicorn Tears',
}
OLD_NAMES = {'Sine Scroller 3.1', 'Crystal Pyramids', 'Prism Lattice'}
OLD_CLASSES = {'SineScroller', 'CrystalPyramids', 'PrismStorm', 'PrismLattice',
               'SystemMonitor', 'AlienBiome'}
# Grand Finale is a system sequence, not a playlist effect, so it is an allowed
# (intentional) ping-pong-friend target that won't resolve to a discovered effect.
ALLOWED_PPF_ORPHANS = {'Grand Finale'}
EXPECTED_TOTAL = 72

# --- Tag-normalization taxonomy (2026-07-01) ---------------------------------
# Every effect carries exactly one canonical category tag as its FIRST tag:
# core analyzers -> 'analyzer'; each pack -> its theme; media showcases ->
# 'media'. Two standalones keep their own descriptors as the category:
# projectm -> 'projectm', unicorn-tears -> 'psychedelic'.
EXPECTED_CATEGORY = {
    'effects-psychedelic': 'psychedelic', 'effects-games': 'games', 'effects-particles': 'particles',
    'effects-retro': 'retro', 'effects-feature': 'feature', 'effects-vector': 'vector',
    'effects-cosmic': 'cosmic', 'effects-tech': 'tech', 'effects-immersive': 'immersive',
    'effects-holiday': 'holiday', 'effects-flying': 'flying',
    'effects-rollercoast': 'rollercoast', 'effects-ukiyo-e': 'ukiyo-e',
    'images-01': 'media', 'videos-01': 'media',
    'video-clips-01': 'media', 'textures-01': 'media', 'sims-01': 'media',
    'projectm-01': 'projectm', 'unicorn-tears-01': 'psychedelic',
}
CORE_CATEGORY = 'analyzer'
# Tags retired during normalization: redundant, structural, misspelled, or (in
# the case of 'futuristic') a vague vibe tag that contradicted 'classic'. Note
# 'classic' is deliberately kept as a demoscene-heritage descriptor.
BANNED_TAGS = {'audio', 'drop-in', 'scifi', 'space', 'futuristic'}


@pytest.fixture(scope='module')
def effects():
    return list(get_effects())


def _by_name(effects):
    return {e.NAME: e for e in effects}


def _src(cls) -> str:
    return inspect.getfile(cls)


def test_total_effect_count(effects):
    assert len(effects) == EXPECTED_TOTAL


def test_no_duplicate_names(effects):
    dups = [n for n, k in Counter(e.NAME for e in effects).items() if k > 1]
    assert not dups, f'duplicate effect NAMEs: {dups}'


def test_no_duplicate_classes(effects):
    dups = [n for n, k in Counter(e.__name__ for e in effects).items() if k > 1]
    assert not dups, f'duplicate effect class names: {dups}'


def test_all_effects_have_name(effects):
    for e in effects:
        assert isinstance(e.NAME, str) and e.NAME, f'{e.__name__} has no NAME'


def test_renamed_effects_present(effects):
    names = {e.NAME for e in effects}
    for nm in ('Audio Sine', 'Rainbow Trance', 'Wormhole', 'Hexy Stars', 'Wavey Gravy'):
        assert nm in names, f'missing renamed effect: {nm}'


def test_old_names_gone(effects):
    present = {e.NAME for e in effects} & OLD_NAMES
    assert not present, f'old display NAMEs still present: {present}'


def test_old_classes_gone(effects):
    present = {e.__name__ for e in effects} & OLD_CLASSES
    assert not present, f'old class names still present: {present}'


def test_core_contains_only_audio_analyzers(effects):
    core = {e.NAME for e in effects if '/unicornviz/effects/' in _src(e)}
    assert core == CORE_NAMES, (
        f'core composition drifted: unexpected={core - CORE_NAMES} '
        f'missing={CORE_NAMES - core}')


def test_pack_composition(effects):
    bn = _by_name(effects)
    for pack, names in PACK_NAMES.items():
        for nm in names:
            assert nm in bn, f'{nm} not discovered (expected in {pack})'
            src = _src(bn[nm])
            assert f'/drop-ins/{pack}/' in src, \
                f'{nm} expected in {pack}, found at {src}'


def test_isolated_effects_present_and_sourced(effects):
    bn = _by_name(effects)
    for nm in ISOLATED_NAMES:
        assert nm in bn, f'isolated effect missing: {nm}'
        assert '/drop-ins/' in _src(bn[nm]), f'{nm} not sourced from a drop-in'


def test_no_stale_ppf_references(effects):
    bad = {}
    for e in effects:
        stale = [f for f in (getattr(e, 'PING_PONG_FRIENDS', []) or []) if f in OLD_NAMES]
        if stale:
            bad[e.NAME] = stale
    assert not bad, f'effects still reference old PPF names: {bad}'


def test_ppf_orphans_limited(effects):
    names = {e.NAME for e in effects}
    orphans = {f for e in effects
               for f in (getattr(e, 'PING_PONG_FRIENDS', []) or []) if f not in names}
    unexpected = orphans - ALLOWED_PPF_ORPHANS
    assert not unexpected, f'unexpected ping-pong-friend orphans: {unexpected}'


def test_core_does_not_import_pack_effects():
    app = (_REPO / 'unicornviz' / 'app.py').read_text()
    for mod in ('ansi_viewer', 'plasma', 'kaleidoscope', 'tunnel', 'cube_3d',
                'vector', 'cosmos', 'black_hole_cathedral', 'system_monitor',
                'alien_biome'):
        assert f'effects.{mod} import' not in app and f'effects import {mod}' not in app, \
            f'core (app.py) still hard-imports pack effect module: {mod}'


def test_every_pack_is_a_submodule():
    gitmodules = (_REPO / '.gitmodules').read_text()
    for pack in PACK_NAMES:
        assert f'drop-ins/{pack}' in gitmodules, f'{pack} not registered as a submodule'


def test_absorbed_dropins_removed():
    gitmodules = (_REPO / '.gitmodules').read_text()
    for old in ('disco-ball-01', 'alien-invasion-01', 'tron-grid-01',
                'cyber-war-01', 'hacker-terminal-01', 'america-250-01'):
        assert f'drop-ins/{old}' not in gitmodules, \
            f'absorbed drop-in {old} should no longer be a submodule'


def test_no_banned_tags(effects):
    bad = {e.NAME: sorted(set(e.TAGS) & BANNED_TAGS)
           for e in effects if set(getattr(e, 'TAGS', []) or []) & BANNED_TAGS}
    assert not bad, f'effects still carry retired tags: {bad}'


def _pack_of(cls) -> str:
    src = _src(cls)
    if '/unicornviz/effects/' in src:
        return 'core'
    return src.split('/drop-ins/')[1].split('/')[0]


def test_every_effect_leads_with_its_category_tag(effects):
    for e in effects:
        tags = list(getattr(e, 'TAGS', []) or [])
        assert tags, f'{e.NAME} has no tags'
        pack = _pack_of(e)
        want = CORE_CATEGORY if pack == 'core' else EXPECTED_CATEGORY.get(pack)
        assert want is not None, f'no expected category mapping for pack {pack}'
        assert tags[0] == want, \
            f'{e.NAME} ({pack}) should lead with {want!r}, got {tags!r}'
