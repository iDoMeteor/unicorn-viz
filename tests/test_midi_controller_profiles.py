"""Tests for file-backed controller profiles (midi-controllers-01).

Covers the profile schema and its required metadata, TOML round-tripping,
validation of malformed/hostile input, two-tier discovery, and the core
``MidiManager.apply_preset`` switch that profiles are registered for.

The drop-in module is loaded the same way the app loads it (registered in
``sys.modules`` before exec) so dataclass field resolution behaves identically
to runtime.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from unicornviz.midi import BUILTIN_PRESETS, MidiManager

_DROPIN = Path(__file__).parent.parent / 'drop-ins' / 'midi-controllers-01'


def _load_dropin_module(name: str, filename: str):
    """Import a drop-in module the way the app does.

    Registering in ``sys.modules`` before ``exec_module`` matters: dataclass
    field resolution looks the defining module up by name, and the app's own
    loader does the same (see ``dropins._load_module_from_file``).
    """
    spec = importlib.util.spec_from_file_location(name, _DROPIN / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cprof = _load_dropin_module('_uv_controller_profiles', 'controller_profiles.py')

# Register the bundled presets into BUILTIN_PRESETS so this module stands on its
# own rather than depending on another test file having run first.
#
# register_all() also claims the APC hardware early and discovers file-backed
# profiles, both via load_dropin_symbol. Neutralizing that loader suppresses
# exactly those two side effects -- the hardware claim would block during
# collection when the app holds the device, and profile discovery would make
# these tests depend on the developer's runtime/ directory.
import unicornviz.dropins as _dropins  # noqa: E402

_presets_mod = _load_dropin_module('_uv_controller_presets', 'controller_presets.py')
_saved_loader = _dropins.load_dropin_symbol
_dropins.load_dropin_symbol = lambda *_a, **_k: None
try:
    _presets_mod.register_all(MidiManager, None)
finally:
    _dropins.load_dropin_symbol = _saved_loader


def _profile(name='Test Layout', **kw):
    meta = cprof.ProfileMeta(
        name=name,
        description=kw.pop('description', 'A test layout'),
        author=kw.pop('author', 'Tester'),
        version=kw.pop('version', '1.2.3'),
        date=kw.pop('date', '2026-07-25'),
        device=kw.pop('device', 'apc mini mk2'),
    )
    return cprof.ControllerProfile(
        meta=meta,
        note_map=kw.pop('note_map', {0: 'next', 1: 'prev'}),
        cc_map=kw.pop('cc_map', {48: 'speed'}),
        colors=kw.pop('colors', {'next': (29, 1)}),
    )


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def test_profile_carries_all_required_metadata_fields() -> None:
    meta = _profile().meta.to_dict()
    for required in ('name', 'description', 'author', 'version', 'date'):
        assert required in meta, f'{required} missing from profile metadata'
    assert meta['name'] == 'Test Layout'
    assert meta['version'] == '1.2.3'
    assert meta['date'] == '2026-07-25'
    assert meta['author'] == 'Tester'


def test_bundled_presets_all_declare_metadata() -> None:
    """Every shipped preset must carry the same metadata block as a profile."""
    for attr in ('_APC_PRESET', '_MPK_PRESET', '_NOVATION_PRESET'):
        meta = getattr(_presets_mod, attr).get('meta')
        assert meta is not None, f'{attr} has no meta block'
        for required in ('name', 'description', 'author', 'version', 'date'):
            assert meta.get(required), f'{attr}.meta.{required} is missing/empty'


# ---------------------------------------------------------------------------
# TOML round-trip
# ---------------------------------------------------------------------------

def test_toml_round_trip_preserves_everything() -> None:
    original = _profile()
    parsed = cprof.parse_profile(original.to_toml(), source='<test>')
    assert parsed.note_map == original.note_map
    assert parsed.cc_map == original.cc_map
    assert parsed.colors == original.colors
    assert parsed.meta.to_dict() == original.meta.to_dict()


def test_round_trip_survives_quotes_and_newlines_in_metadata() -> None:
    original = _profile(description='He said "hi"\nthen left\\')
    parsed = cprof.parse_profile(original.to_toml(), source='<test>')
    assert parsed.meta.description == 'He said "hi"\nthen left\\'


def test_bundled_stock_profile_parses() -> None:
    path = _DROPIN / 'profiles' / 'apc-mini-mk2-stock.toml'
    assert path.is_file(), 'stock profile should ship with the drop-in'
    profile = cprof.parse_profile(path.read_text(encoding='utf-8'), source=str(path))
    assert profile.meta.name
    assert len(profile.note_map) == 80
    assert len(profile.cc_map) == 9


def test_stock_profile_matches_the_registered_builtin_preset() -> None:
    """The shipped profile must be the live layout, not a drifted copy."""
    path = _DROPIN / 'profiles' / 'apc-mini-mk2-stock.toml'
    profile = cprof.parse_profile(path.read_text(encoding='utf-8'), source=str(path))
    builtin = BUILTIN_PRESETS['akai_apc_mini_mk2']
    assert profile.note_map == builtin['note_map']
    assert profile.cc_map == builtin['cc_map']


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ('text', 'reason'),
    [
        ('', 'missing [meta]'),
        ('[meta]\nname = ""\n[note_map]\n0 = "next"\n', 'empty name'),
        ('[meta]\nname = "X"\n', 'binds nothing'),
        ('[meta]\nname = "X"\n[note_map]\nnope = "next"\n', 'non-numeric note key'),
        ('[meta]\nname = "X"\n[note_map]\n999 = "next"\n', 'note out of MIDI range'),
        ('[meta]\nname = "X"\n[note_map]\n0 = ""\n', 'empty action name'),
        ('[meta]\nname = "X"\n[note_map]\n0 = "n"\n[colors]\nn = [1]\n', 'bad color pair'),
        ('[meta]\nname = "X"\n[note_map]\n0 = "n"\n[colors]\nn = [1, 999]\n', 'color range'),
        ('[meta]\nname = "X"\nschema_version = 99\n[note_map]\n0 = "n"\n', 'future schema'),
        ('[meta\nname = "X"\n', 'invalid TOML'),
    ],
)
def test_malformed_profiles_are_rejected(text: str, reason: str) -> None:
    with pytest.raises(cprof.ProfileError):
        cprof.parse_profile(text, source='<test>')


def test_profile_error_names_the_source_file() -> None:
    with pytest.raises(cprof.ProfileError, match='naughty.toml'):
        cprof.parse_profile('[meta]\nname = "X"\n', source='naughty.toml')


# ---------------------------------------------------------------------------
# Slug safety — profiles are shared, so a name must never become a path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('hostile', [
    '../../../etc/passwd',
    '..\\..\\windows\\system32',
    '/absolute/path',
    'C:\\drive\\path',
    '....//....//escape',
    '',
    '///',
])
def test_slugify_cannot_escape_the_profiles_directory(hostile: str) -> None:
    slug = cprof.slugify(hostile)
    assert '/' not in slug and '\\' not in slug
    assert '..' not in slug
    assert not Path(slug).is_absolute()
    assert slug, 'slug must never be empty'


def test_hostile_profile_name_saves_inside_the_user_dir(tmp_path) -> None:
    store = cprof.ControllerProfileStore(
        bundled_dir=tmp_path / 'bundled', user_dir=tmp_path / 'user',
    )
    written = store.save(_profile(name='../../escape me'))
    assert (tmp_path / 'user') in written.parents


# ---------------------------------------------------------------------------
# Store discovery
# ---------------------------------------------------------------------------

def test_discover_reads_both_tiers(tmp_path) -> None:
    bundled, user = tmp_path / 'bundled', tmp_path / 'user'
    bundled.mkdir()
    user.mkdir()
    (bundled / 'a.toml').write_text(_profile(name='Alpha').to_toml(), encoding='utf-8')
    (user / 'b.toml').write_text(_profile(name='Beta').to_toml(), encoding='utf-8')

    store = cprof.ControllerProfileStore(bundled_dir=bundled, user_dir=user)
    names = [p.meta.name for p in store.discover()]
    assert names == ['Alpha', 'Beta']


def test_user_profile_wins_a_name_collision(tmp_path) -> None:
    bundled, user = tmp_path / 'bundled', tmp_path / 'user'
    bundled.mkdir()
    user.mkdir()
    (bundled / 'x.toml').write_text(
        _profile(name='Same', author='Bundled').to_toml(), encoding='utf-8')
    (user / 'x.toml').write_text(
        _profile(name='Same', author='User').to_toml(), encoding='utf-8')

    store = cprof.ControllerProfileStore(bundled_dir=bundled, user_dir=user)
    store.discover()
    assert store.get('Same').meta.author == 'User'


def test_one_malformed_profile_does_not_stop_the_others(tmp_path) -> None:
    """A single bad shared file must never take the app down."""
    user = tmp_path / 'user'
    user.mkdir()
    (user / 'good.toml').write_text(_profile(name='Good').to_toml(), encoding='utf-8')
    (user / 'bad.toml').write_text('[meta\nbroken', encoding='utf-8')

    store = cprof.ControllerProfileStore(bundled_dir=tmp_path / 'nope', user_dir=user)
    assert [p.meta.name for p in store.discover()] == ['Good']


def test_missing_directories_are_not_an_error(tmp_path) -> None:
    store = cprof.ControllerProfileStore(
        bundled_dir=tmp_path / 'absent', user_dir=tmp_path / 'also-absent',
    )
    assert store.discover() == []


def test_save_then_discover_finds_the_saved_profile(tmp_path) -> None:
    store = cprof.ControllerProfileStore(
        bundled_dir=tmp_path / 'bundled', user_dir=tmp_path / 'user',
    )
    store.save(_profile(name='Round Trip'))

    fresh = cprof.ControllerProfileStore(
        bundled_dir=tmp_path / 'bundled', user_dir=tmp_path / 'user',
    )
    fresh.discover()
    assert fresh.get('Round Trip') is not None
    assert fresh.get('round-trip') is not None      # lookup accepts the slug


def test_delete_removes_a_user_profile(tmp_path) -> None:
    store = cprof.ControllerProfileStore(
        bundled_dir=tmp_path / 'bundled', user_dir=tmp_path / 'user',
    )
    store.save(_profile(name='Doomed'))
    assert store.delete('Doomed') is True
    assert store.delete('Doomed') is False
    assert store.get('Doomed') is None


# ---------------------------------------------------------------------------
# Registration + core apply_preset
# ---------------------------------------------------------------------------

def test_register_profiles_registers_under_slug(tmp_path) -> None:
    user = tmp_path / 'user'
    user.mkdir()
    (user / 'z.toml').write_text(
        _profile(name='Zone Layout').to_toml(), encoding='utf-8')
    store = cprof.ControllerProfileStore(bundled_dir=tmp_path / 'b', user_dir=user)

    try:
        registered = cprof.register_profiles(MidiManager, store)
        assert [p.key for p in registered] == ['zone-layout']
        assert 'zone-layout' in BUILTIN_PRESETS
        assert BUILTIN_PRESETS['zone-layout']['note_map'] == {0: 'next', 1: 'prev'}
        assert BUILTIN_PRESETS['zone-layout']['meta']['author'] == 'Tester'
    finally:
        BUILTIN_PRESETS.pop('zone-layout', None)
        MidiManager._dual_port_registry.pop('zone-layout', None)


def test_apply_preset_switches_the_live_maps() -> None:
    mgr = MidiManager(preset='akai_apc_mini_mk2')
    assert mgr.note_to_action(56) == 'next'

    BUILTIN_PRESETS['_test_switch'] = {
        'cc_map': {48: 'glow'}, 'note_map': {56: 'pause'},
    }
    try:
        assert mgr.apply_preset('_test_switch') is True
        assert mgr.note_to_action(56) == 'pause'
        assert mgr.cc_to_param(48) == 'glow'
        assert mgr.preset == '_test_switch'
    finally:
        BUILTIN_PRESETS.pop('_test_switch', None)


def test_apply_preset_reapplies_config_overrides() -> None:
    """A switch must not silently drop the operator's [midi.note_map] entries."""
    mgr = MidiManager(
        preset='akai_apc_mini_mk2',
        note_map_override={56: 'screenshot'},
        cc_map_override={48: 'crt'},
    )
    assert mgr.note_to_action(56) == 'screenshot'

    BUILTIN_PRESETS['_test_switch2'] = {
        'cc_map': {48: 'glow'}, 'note_map': {56: 'pause'},
    }
    try:
        mgr.apply_preset('_test_switch2')
        assert mgr.note_to_action(56) == 'screenshot'   # override still wins
        assert mgr.cc_to_param(48) == 'crt'
    finally:
        BUILTIN_PRESETS.pop('_test_switch2', None)


def test_apply_preset_rejects_unknown_and_keeps_current_maps() -> None:
    mgr = MidiManager(preset='akai_apc_mini_mk2')
    before = mgr.note_map

    assert mgr.apply_preset('no_such_preset_exists') is False
    assert mgr.note_map == before
    assert mgr.preset == 'akai_apc_mini_mk2'


def test_apply_preset_discards_runtime_learn_bindings() -> None:
    """Learn edits are scratch on top of a preset; a switch starts clean."""
    mgr = MidiManager(preset='akai_apc_mini_mk2')
    mgr.set_note_binding(7, 'grand_finale')
    assert mgr.note_to_action(7) == 'grand_finale'

    mgr.apply_preset('akai_apc_mini_mk2')
    assert mgr.note_to_action(7) == 'postfx_10'         # back to the preset value
