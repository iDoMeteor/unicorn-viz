"""Mixer-only boot profile — regression tests.

Covers the resolution precedence and contradiction handling in
``unicornviz.boot_profile``, the ``--mixer`` CLI plumbing, the empty-playlist
safety the profile relies on, and the overlays core-help filter
(see drop-ins/dj-mixer-01/docs/mixer-only-mode-plan.md).
"""
from __future__ import annotations

from unicornviz.boot_profile import (
    PROFILE_FULL,
    PROFILE_MIXER,
    mixer_allowed_sections,
    resolve_boot_profile,
)
from unicornviz.overlays import Overlays
from unicornviz.playlist import Playlist


class _Cfg:
    """Minimal cfg.get(section, key, default=...) stub."""

    def __init__(self, values: dict[tuple[str, str], object]) -> None:
        self._values = values

    def get(self, *keys, default=None):
        return self._values.get(tuple(keys), default)


# --------------------------------------------------------------------------- #
# resolve_boot_profile
# --------------------------------------------------------------------------- #

def test_default_is_full_profile() -> None:
    profile, notes = resolve_boot_profile(_Cfg({}), True)
    assert profile == PROFILE_FULL
    assert notes == []


def test_mixer_only_resolves_to_mixer_profile() -> None:
    cfg = _Cfg({('dj_mixer', 'mixer_only'): True})
    profile, notes = resolve_boot_profile(cfg, True)
    assert profile == PROFILE_MIXER
    assert notes == []


def test_mixer_only_with_disabled_mixer_is_a_contradiction() -> None:
    cfg = _Cfg({('dj_mixer', 'mixer_only'): True, ('dj_mixer', 'enabled'): False})
    profile, notes = resolve_boot_profile(cfg, True)
    assert profile == PROFILE_FULL
    assert any('contradiction' in n for n in notes)


def test_mixer_only_without_dropin_falls_back_to_full() -> None:
    cfg = _Cfg({('dj_mixer', 'mixer_only'): True})
    profile, notes = resolve_boot_profile(cfg, False)
    assert profile == PROFILE_FULL
    assert any('drop-in' in n for n in notes)


def test_dropin_presence_accepts_a_callable() -> None:
    cfg = _Cfg({('dj_mixer', 'mixer_only'): True})
    assert resolve_boot_profile(cfg, lambda: True)[0] == PROFILE_MIXER
    assert resolve_boot_profile(cfg, lambda: False)[0] == PROFILE_FULL


def test_safe_mode_plus_mixer_boots_mixer_with_a_loud_note() -> None:
    cfg = _Cfg({
        ('dj_mixer', 'mixer_only'): True,
        ('dropins', 'safe_mode'): True,
    })
    profile, notes = resolve_boot_profile(cfg, True)
    assert profile == PROFILE_MIXER
    assert any('safe_mode' in n for n in notes)


# --------------------------------------------------------------------------- #
# mixer_allowed_sections
# --------------------------------------------------------------------------- #

def test_mixer_itself_is_always_allowed() -> None:
    assert 'dj_mixer' in mixer_allowed_sections(_Cfg({}))


def test_mixer_allow_extends_the_set() -> None:
    cfg = _Cfg({('dj_mixer', 'mixer_allow'): ['media', ' OSC ', '']})
    allowed = mixer_allowed_sections(cfg)
    assert allowed == frozenset({'dj_mixer', 'media', 'osc'})


def test_mixer_allow_ignores_non_list_values() -> None:
    cfg = _Cfg({('dj_mixer', 'mixer_allow'): 'media'})
    assert mixer_allowed_sections(cfg) == frozenset({'dj_mixer'})


# --------------------------------------------------------------------------- #
# --mixer CLI plumbing
# --------------------------------------------------------------------------- #

def test_mixer_flag_writes_the_config_override() -> None:
    from unicornviz.__main__ import _build_overrides, _build_parser

    args = _build_parser().parse_args(['--mixer'])
    overrides = _build_overrides(args)
    assert overrides['dj_mixer']['mixer_only'] is True


def test_no_mixer_flag_leaves_config_untouched() -> None:
    from unicornviz.__main__ import _build_overrides, _build_parser

    args = _build_parser().parse_args([])
    overrides = _build_overrides(args)
    assert 'mixer_only' not in overrides.get('dj_mixer', {})


# --------------------------------------------------------------------------- #
# Empty-playlist safety (the profile discovers zero effects)
# --------------------------------------------------------------------------- #

class _StubCfg:
    def get(self, *_keys, default=None):
        return default


def test_empty_playlist_navigation_is_none_safe() -> None:
    playlist = Playlist([], _StubCfg())
    assert playlist.current() is None
    assert playlist.advance() is None
    assert playlist.go_prev() is None
    assert playlist.go_index(3) is None
    assert playlist.shortcut_effects == []


def test_nonempty_playlist_navigation_is_unchanged() -> None:
    fx = [type(n, (), {'NAME': n, 'TAGS': [], 'parameters': {}}) for n in 'AB']
    playlist = Playlist(fx, _StubCfg())
    assert playlist.current() is fx[0]
    assert playlist.advance() is fx[1]
    assert playlist.go_prev() is fx[0]
    assert playlist.go_index(1) is fx[1]


# --------------------------------------------------------------------------- #
# Overlays core-help filter
# --------------------------------------------------------------------------- #

def _bare_overlays() -> Overlays:
    o = object.__new__(Overlays)
    o._dynamic_help_order = []
    o._dynamic_help_sections = {}
    return o


def test_core_help_filter_restricts_sections() -> None:
    o = _bare_overlays()
    o.set_core_help_filter(('Help Usage', 'Basics'))
    names = [name for name, _ in o._iter_help_sections()]
    assert set(names) == {'Help Usage', 'Basics'}


def test_core_help_filter_none_restores_full_set() -> None:
    o = _bare_overlays()
    o.set_core_help_filter(('Basics',))
    o.set_core_help_filter(None)
    names = [name for name, _ in o._iter_help_sections()]
    assert names == [name for name, _ in Overlays.CORE_HELP_SECTIONS]


def test_default_shows_all_core_sections() -> None:
    # The class default (no filter) must leave normal mode byte-identical.
    o = _bare_overlays()
    names = [name for name, _ in o._iter_help_sections()]
    assert names == [name for name, _ in Overlays.CORE_HELP_SECTIONS]
