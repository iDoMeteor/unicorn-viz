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


# ---------------------------------------------------------------------------
# LED palette layering (apc_leds)
# ---------------------------------------------------------------------------

def _leds_module():
    return _load_dropin_module('_uv_apc_leds', 'apc_leds.py')


def _vj_state(**overrides):
    from unicornviz.vj_api import VJState

    base = dict(
        effect_name='Plasma', playlist_mode='sequential', playlist_index=0,
        playlist_size=1, auto_advance=True, paused=False, fullscreen=False,
        is_transitioning=False, advance_interval=20.0, advance_time_remaining=20.0,
        reactivity=1.0, speed=None, zoom=None, audio_source='default',
        invert=False, is_postfx_active=False, postfx_slot=0,
        is_dancing_active=False, is_nova_active=False, is_burst_active=False,
        recording_active=False, streaming_active=False, streaming_provider='',
        display_mode='single', display_index=0, user_busy=False,
        manual_grace_remaining_s=0.0, status_pill='',
        session_elapsed_s=0.0, session_remaining_s=0.0,
    )
    # Deliberately not a real display mode ('single' et al. all map to an
    # active action via _DISPLAY_MODE_TO_ACTION) -- keeps the baseline state
    # free of active actions unless a test explicitly sets one.
    base['display_mode'] = ''
    base.update(overrides)
    return VJState(**base)


class _FakeVJ:
    """Minimal VJApi stand-in for LED construction (no hardware touched)."""

    def __init__(self, state=None) -> None:
        self._state_obj = state if state is not None else _vj_state()

    def midi_inject_event(self, _raw):
        pass

    def midi_list_output_ports(self):
        return []

    def midi_send_output(self, _hint, _msg):
        return True

    def state(self):
        return self._state_obj


def _leds_instance(monkeypatch):
    leds_mod = _leds_module()
    # Never let the LED object reach real hardware during tests.
    monkeypatch.setattr(leds_mod, '_apc_libusb_io', None, raising=False)
    monkeypatch.setattr(leds_mod, '_apc_rawmidi_io', None, raising=False)
    monkeypatch.setattr(leds_mod, '_find_apc_rawmidi_hw_path', lambda: None)
    return leds_mod, leds_mod.APCLedFeedback(_FakeVJ())


def test_profile_colors_win_over_the_builtin_table(monkeypatch) -> None:
    leds_mod, leds = _leds_instance(monkeypatch)
    builtin = leds_mod._ACTION_COLORS['next']

    leds.set_profile_colors({'next': (7, 8)})

    assert leds.action_colors('next') == (7, 8)
    assert leds.action_colors('next') != builtin


def test_actions_the_profile_omits_fall_back_to_the_builtin_table(monkeypatch) -> None:
    leds_mod, leds = _leds_instance(monkeypatch)
    leds.set_profile_colors({'next': (7, 8)})

    assert leds.action_colors('pause') == leds_mod._ACTION_COLORS['pause']


def test_unknown_action_falls_back_to_the_generic_default(monkeypatch) -> None:
    leds_mod, leds = _leds_instance(monkeypatch)
    leds.set_profile_colors({'next': (7, 8)})

    assert leds.action_colors('some_dropin_action_that_does_not_exist') == (
        leds_mod._DEFAULT_IDLE, leds_mod._DEFAULT_ACTIVE,
    )


def test_switching_profiles_clears_stale_learn_color_overrides(monkeypatch) -> None:
    """Overrides were tuned against the old palette; carrying them looks wrong."""
    _leds_mod, leds = _leds_instance(monkeypatch)
    leds.set_action_idle('next', 53)
    assert leds.get_action_idle('next') == 53

    leds.set_profile_colors({'next': (7, 8)})

    assert leds.get_action_idle('next') == 7


def test_setting_profile_colors_forces_a_full_repaint(monkeypatch) -> None:
    _leds_mod, leds = _leds_instance(monkeypatch)
    leds._sent = {0: 29, 1: 45}

    leds.set_profile_colors({'next': (7, 8)})

    assert leds._sent == {}, 'stale sent-cache would suppress the repaint'


def test_all_action_colors_matches_per_action_resolution(monkeypatch) -> None:
    leds_mod, leds = _leds_instance(monkeypatch)
    leds.set_profile_colors({'next': (7, 8)})
    leds.set_action_idle('prev', 99)

    colors = leds.all_action_colors()

    # Every built-in action is covered, resolved the same way action_colors/
    # get_action_idle already resolve it individually -- this is a batch of
    # the same logic, not a second implementation of it.
    for action in leds_mod._ACTION_COLORS:
        assert colors[action] == (leds.get_action_idle(action), leds.action_colors(action)[1])
    assert colors['next'] == (7, 8)          # profile override applied
    assert colors['prev'][0] == 99           # MIDI Learn idle override applied


def test_all_action_colors_includes_profile_and_override_only_actions(monkeypatch) -> None:
    """An action bound only by a profile/override (not in the built-in table)
    must still show up -- it's the whole reason this isn't just
    dict(_ACTION_COLORS)."""
    leds_mod, leds = _leds_instance(monkeypatch)
    assert 'a_drop_in_action' not in leds_mod._ACTION_COLORS
    leds.set_profile_colors({'a_drop_in_action': (11, 12)})

    colors = leds.all_action_colors()

    assert colors['a_drop_in_action'] == (11, 12)


# ---------------------------------------------------------------------------
# active_actions() -- the extracted _compute_active_actions() live read
# ---------------------------------------------------------------------------

def test_active_actions_empty_by_default(monkeypatch) -> None:
    leds_mod, leds = _leds_instance(monkeypatch)
    assert leds.active_actions() == set()


def test_active_actions_reflects_paused_and_fullscreen(monkeypatch) -> None:
    leds_mod, _leds = _leds_instance(monkeypatch)
    leds = leds_mod.APCLedFeedback(_FakeVJ(_vj_state(paused=True, fullscreen=True)))
    assert leds.active_actions() == {'pause', 'fullscreen'}


def test_active_actions_reflects_postfx_slot(monkeypatch) -> None:
    leds_mod, _leds = _leds_instance(monkeypatch)
    leds = leds_mod.APCLedFeedback(
        _FakeVJ(_vj_state(is_postfx_active=True, postfx_slot=3)),
    )
    assert leds.active_actions() == {'postfx_3'}


def test_active_actions_ignores_postfx_slot_zero_even_if_flagged_active(monkeypatch) -> None:
    leds_mod, _leds = _leds_instance(monkeypatch)
    leds = leds_mod.APCLedFeedback(
        _FakeVJ(_vj_state(is_postfx_active=True, postfx_slot=0)),
    )
    assert leds.active_actions() == set()


def test_active_actions_reflects_display_mode(monkeypatch) -> None:
    leds_mod, _leds = _leds_instance(monkeypatch)
    leds = leds_mod.APCLedFeedback(_FakeVJ(_vj_state(display_mode='mirror_all')))
    assert leds.active_actions() == {'display_mirror_all'}


def test_active_actions_unknown_display_mode_adds_nothing(monkeypatch) -> None:
    leds_mod, _leds = _leds_instance(monkeypatch)
    leds = leds_mod.APCLedFeedback(_FakeVJ(_vj_state(display_mode='some_future_mode')))
    assert leds.active_actions() == set()


def test_active_actions_matches_what_refresh_from_app_state_actually_paints(monkeypatch) -> None:
    """The whole point of extracting this: active_actions() must never drift
    from what the real pads show. Verified directly against set_pad calls,
    not just by re-reading the same source."""
    leds_mod, _leds = _leds_instance(monkeypatch)
    state = _vj_state(paused=True, is_postfx_active=True, postfx_slot=2, display_mode='span_all')
    vj = _FakeVJ(state)
    vj.midi_note_map = lambda: {0: 'pause', 1: 'postfx_2', 2: 'display_span_all', 3: 'next'}
    leds = leds_mod.APCLedFeedback(vj)

    leds._refresh_from_app_state()

    active_set = leds.active_actions()
    for note, action in vj.midi_note_map().items():
        expected_color = leds.action_colors(action)[1 if action in active_set else 0]
        assert leds._pending[note] == expected_color, action


def test_active_actions_swallows_a_state_read_failure(monkeypatch) -> None:
    leds_mod, _leds = _leds_instance(monkeypatch)

    class _BrokenVJ(_FakeVJ):
        def state(self):
            raise RuntimeError('boom')

    leds = leds_mod.APCLedFeedback(_BrokenVJ())
    assert leds.active_actions() == set()


# ---------------------------------------------------------------------------
# Deck-sim layout (P1 of drop-ins/control-room-01/docs/deck-sim-plan.md)
# ---------------------------------------------------------------------------

def test_deck_sim_layout_matches_the_note_layout_helpers(monkeypatch) -> None:
    leds_mod, _leds = _leds_instance(monkeypatch)
    layout = leds_mod.build_deck_sim_layout()

    assert layout.device == 'apc mini mk2'
    assert layout.grid_rows == 8 and layout.grid_cols == 8
    for row in range(8):
        for col in range(8):
            assert layout.grid_note(row, col) == leds_mod._row_note(row, col)
    assert layout.scene_notes == tuple(leds_mod._scene_note(i) for i in range(8))
    assert layout.track_notes == tuple(leds_mod._track_note(i) for i in range(8))


def test_deck_sim_layout_faders_cover_cc_48_through_56(monkeypatch) -> None:
    leds_mod, _leds = _leds_instance(monkeypatch)
    layout = leds_mod.build_deck_sim_layout()

    ccs = [f.cc for f in layout.faders]
    assert ccs == list(range(48, 57))            # 48-55 track, 56 master
    assert [f.label for f in layout.faders[:8]] == [str(i) for i in range(1, 9)]
    master = layout.faders[-1]
    assert master.is_master is True
    assert master.label == 'MASTER'
    assert sum(1 for f in layout.faders if f.is_master) == 1


def test_deck_sim_layout_device_token_matches_the_stock_preset(monkeypatch) -> None:
    """This is the token active_deck_sim_layout() resolves against -- it must
    exactly match what the stock preset stamps into meta.device, or the
    deck-sim view would silently never resolve a layout at all."""
    leds_mod, _leds = _leds_instance(monkeypatch)
    layout = leds_mod.build_deck_sim_layout()
    assert layout.device == _presets_mod._APC_PRESET['meta']['device']


# ---------------------------------------------------------------------------
# Bundled alt-01 zone profile
# ---------------------------------------------------------------------------

def _alt01():
    path = _DROPIN / 'profiles' / 'apc-mini-mk2-alt-01.toml'
    return path, cprof.parse_profile(path.read_text(encoding='utf-8'), source=str(path))


def test_alt01_profile_ships_and_parses() -> None:
    path, profile = _alt01()
    assert path.is_file()
    assert profile.key == 'apc-mini-mk2-alt-01'
    for required in ('name', 'description', 'author', 'version', 'date'):
        assert profile.meta.to_dict()[required], f'meta.{required} is empty'


def test_alt01_binds_no_action_twice() -> None:
    """The whole point of the remap: no duplicate pads."""
    _path, profile = _alt01()
    actions = list(profile.note_map.values())
    assert len(actions) == len(set(actions))


def test_alt01_every_bound_action_has_a_color() -> None:
    _path, profile = _alt01()
    assert set(profile.note_map.values()) <= set(profile.colors)


def test_alt01_leaves_four_grid_pads_unlit() -> None:
    _path, profile = _alt01()
    grid = {n for n in profile.note_map if n < 64}
    assert sorted(set(range(64)) - grid) == [6, 7, 62, 63]


def test_alt01_covers_both_button_strips() -> None:
    _path, profile = _alt01()
    assert all(n in profile.note_map for n in range(112, 120))   # scene strip
    assert all(n in profile.note_map for n in range(100, 106))   # track strip
