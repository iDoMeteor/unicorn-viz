"""Regression tests for tools/training_daemon.py's --source selection.

2026-08-07: the daemon gained --source {spotify,dj-mixer,media} so it can
drive dj-mixer-01/media-01 headlessly instead of only Spotify. These tests
cover the pure, subprocess-free pieces: argparse-time validation
(_validate_source_args) and command/env construction (_unicornviz_env,
_start_unicornviz's cmd list via a monkeypatched _start).
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'training-kit-01' / 'tools' / 'training_daemon.py'
_SPEC = importlib.util.spec_from_file_location('training_daemon', _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

_validate_source_args = _MOD._validate_source_args
_unicornviz_env = _MOD._unicornviz_env
_start_unicornviz = _MOD._start_unicornviz
_resolve_playlist_name = _MOD._resolve_playlist_name
_load_known_playlists = _MOD._load_known_playlists
_set_name = _MOD._set_name
_slugify = _MOD._slugify


def _args(**overrides) -> argparse.Namespace:
    base = dict(source='spotify', playlist_name='', source_dir=None)
    base.update(overrides)
    return argparse.Namespace(**base)


# ---------------------------------------------------------------------------
# _validate_source_args
# ---------------------------------------------------------------------------

def test_spotify_source_needs_neither_playlist_name_nor_source_dir() -> None:
    _validate_source_args(_args(source='spotify'))  # must not raise


def test_dj_mixer_source_requires_source_dir() -> None:
    # 2026-08-18: playlist_name presence/validity moved to
    # _resolve_playlist_name() (see its own test section below) --
    # _validate_source_args() only checks source_dir now.
    with pytest.raises(SystemExit):
        _validate_source_args(_args(source='dj-mixer', playlist_name='Set', source_dir=None))


def test_dj_mixer_source_passes_with_source_dir_regardless_of_playlist_name() -> None:
    _validate_source_args(_args(source='dj-mixer', playlist_name='Set', source_dir=Path('/music')))
    _validate_source_args(_args(source='dj-mixer', playlist_name='', source_dir=Path('/music')))


def test_media_source_requires_source_dir() -> None:
    with pytest.raises(SystemExit):
        _validate_source_args(_args(source='media', playlist_name='', source_dir=None))
    _validate_source_args(_args(source='media', playlist_name='Run', source_dir=Path('/music')))


# ---------------------------------------------------------------------------
# _unicornviz_env
# ---------------------------------------------------------------------------

def test_env_sets_pulse_sink_only_for_media_source() -> None:
    spotify_env = _unicornviz_env(':99', 'spotify', 'unicorn-training')
    dj_mixer_env = _unicornviz_env(':99', 'dj-mixer', 'unicorn-training')
    media_env = _unicornviz_env(':99', 'media', 'unicorn-training')

    assert 'PULSE_SINK' not in spotify_env
    assert 'PULSE_SINK' not in dj_mixer_env
    assert media_env['PULSE_SINK'] == 'unicorn-training'


def test_env_always_sets_display_and_software_gl() -> None:
    env = _unicornviz_env(':100', 'spotify', 'unicorn-training')
    assert env['DISPLAY'] == ':100'
    assert env['LIBGL_ALWAYS_SOFTWARE'] == '1'
    assert env['GALLIUM_DRIVER'] == 'llvmpipe'


# ---------------------------------------------------------------------------
# _start_unicornviz command construction
# ---------------------------------------------------------------------------

def _capture_start(monkeypatch):
    calls = []

    def _fake_start(args, *, env=None, cwd=None):
        calls.append({'args': args, 'env': env, 'cwd': cwd})
        return object()

    monkeypatch.setattr(_MOD, '_start', _fake_start)
    monkeypatch.setattr(_MOD, '_require', lambda cmd: cmd)
    return calls


def test_spotify_source_adds_no_extra_flags(monkeypatch) -> None:
    calls = _capture_start(monkeypatch)

    _start_unicornviz(Path('/app'), ':99', 'unicorn-training', False, 'spotify')

    cmd = calls[0]['args']
    assert '--dj-mixer-source' not in cmd
    assert '--media-source' not in cmd


def test_dj_mixer_source_passes_the_right_flags(monkeypatch) -> None:
    calls = _capture_start(monkeypatch)

    _start_unicornviz(
        Path('/app'), ':99', 'unicorn-training', False,
        'dj-mixer', 'crossfade', Path('/music/crate'),
    )

    cmd = calls[0]['args']
    assert '--dj-mixer-source' in cmd
    idx = cmd.index('--dj-mixer-autoplay-mode')
    assert cmd[idx + 1] == 'crossfade'
    idx = cmd.index('--dj-mixer-music-dir')
    assert cmd[idx + 1] == '/music/crate'
    assert '--media-source' not in cmd
    assert 'PULSE_SINK' not in calls[0]['env']


def test_media_source_passes_the_right_flags_and_pulse_sink(monkeypatch) -> None:
    calls = _capture_start(monkeypatch)

    _start_unicornviz(
        Path('/app'), ':99', 'unicorn-training', False,
        'media', 'cut', Path('/music/library'),
    )

    cmd = calls[0]['args']
    assert '--media-source' in cmd
    idx = cmd.index('--media-dir')
    assert cmd[idx + 1] == '/music/library'
    # 2026-08-14: --media-favorites always pairs with --source media --
    # boots the named 'favorites' playlist, unshuffled, no repeat, instead
    # of the shuffled full library. See media-01 0.21.0's boot_playlist.
    assert '--media-favorites' in cmd
    assert '--dj-mixer-source' not in cmd
    assert calls[0]['env']['PULSE_SINK'] == 'unicorn-training'


def test_windowed_flag_still_respected_for_all_sources(monkeypatch) -> None:
    calls = _capture_start(monkeypatch)

    _start_unicornviz(Path('/app'), ':99', 'unicorn-training', True, 'spotify')

    assert '--windowed' in calls[0]['args']


# ---------------------------------------------------------------------------
# _set_name -- no date prefix, shared (non-buggy) slugify (2026-08-18)
# ---------------------------------------------------------------------------

def test_set_name_has_no_date_prefix() -> None:
    name = _set_name('Training House 01')
    assert not name[:4].isdigit(), f'set name should not start with a date: {name!r}'
    assert name == 'training-house-01'


def test_set_name_does_not_triple_dash_a_spaced_hyphen() -> None:
    """2026-08-18: training_daemon.py's own _slugify() collapsed a literal
    hyphen surrounded by spaces into a triple dash (each surrounding
    space independently collapsing to its own '-'), producing the real
    incident directory `20260817-training---house-01`. _set_name() must
    prefer package_training_set.py's _slugify_playlist_name(), which
    doesn't have this bug."""
    assert _set_name('Training - House 01') == 'training-house-01'


def test_daemon_slugify_fallback_has_the_known_triple_dash_bug() -> None:
    """Documents the bug in the fallback _slugify() itself (kept only for
    when package_training_set.py can't be loaded at all) -- not a
    behavior to fix here, just pinned so nobody is surprised _set_name()
    deliberately avoids calling this function when it can avoid it."""
    assert _slugify('Training - House 01') == 'training---house-01'


# ---------------------------------------------------------------------------
# _resolve_playlist_name -- validate/reject/offer against real playlists
# ---------------------------------------------------------------------------

_KNOWN = [
    ('Training - House 01', 'dj-mixer'),
    ('Live Show 001', 'dj-mixer'),
    ('Favorites', 'media'),
]


def _patch_known(monkeypatch, known=_KNOWN) -> None:
    monkeypatch.setattr(_MOD, '_repo_root', lambda: Path('/fake-repo'))
    monkeypatch.setattr(_MOD, '_load_known_playlists', lambda root: known)


def test_resolve_playlist_name_spotify_bypasses_entirely(monkeypatch) -> None:
    """--source spotify never touches playlist validation -- it's optional
    and auto-discovered from session logs."""
    monkeypatch.setattr(_MOD, '_load_known_playlists', lambda root: (_ for _ in ()).throw(
        AssertionError('should not be called for --source spotify')))
    args = _args(source='spotify', playlist_name='')
    _resolve_playlist_name(args)  # must not raise
    assert args.playlist_name == ''


def test_resolve_playlist_name_accepts_case_insensitive_and_normalizes(monkeypatch) -> None:
    _patch_known(monkeypatch)
    args = _args(source='dj-mixer', playlist_name='TRAINING - house 01')
    _resolve_playlist_name(args)
    assert args.playlist_name == 'Training - House 01'  # normalized to the stored casing


def test_resolve_playlist_name_pools_media_and_dj_mixer_regardless_of_source(monkeypatch) -> None:
    """A media-01 playlist name must validate even under --source dj-mixer
    (and vice versa) -- owner: "offer a selection of valid ones
    (regardless of mixer/media player)"."""
    _patch_known(monkeypatch)
    args = _args(source='dj-mixer', playlist_name='Favorites')
    _resolve_playlist_name(args)
    assert args.playlist_name == 'Favorites'


def test_resolve_playlist_name_rejects_unknown_name(monkeypatch) -> None:
    _patch_known(monkeypatch)
    args = _args(source='media', playlist_name='Not A Real Playlist')
    with pytest.raises(SystemExit) as exc_info:
        _resolve_playlist_name(args)
    message = str(exc_info.value)
    assert 'does not match any known playlist' in message
    assert 'Training - House 01' in message
    assert 'Favorites' in message


def test_resolve_playlist_name_missing_noninteractive_exits_with_list(monkeypatch) -> None:
    _patch_known(monkeypatch)
    monkeypatch.setattr(_MOD.sys.stdin, 'isatty', lambda: False)
    args = _args(source='dj-mixer', playlist_name='')
    with pytest.raises(SystemExit) as exc_info:
        _resolve_playlist_name(args)
    message = str(exc_info.value)
    assert 'requires --playlist-name' in message
    assert 'Training - House 01' in message


def test_resolve_playlist_name_missing_interactive_picks_by_number(monkeypatch) -> None:
    _patch_known(monkeypatch)
    monkeypatch.setattr(_MOD.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda _prompt: '2')
    args = _args(source='dj-mixer', playlist_name='')
    _resolve_playlist_name(args)
    assert args.playlist_name == 'Live Show 001'


def test_resolve_playlist_name_missing_interactive_picks_by_typed_name(monkeypatch) -> None:
    _patch_known(monkeypatch)
    monkeypatch.setattr(_MOD.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda _prompt: 'favorites')
    args = _args(source='media', playlist_name='')
    _resolve_playlist_name(args)
    assert args.playlist_name == 'Favorites'


def test_resolve_playlist_name_missing_interactive_gives_up_after_bad_attempts(monkeypatch) -> None:
    _patch_known(monkeypatch)
    monkeypatch.setattr(_MOD.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda _prompt: 'nonsense')
    args = _args(source='dj-mixer', playlist_name='')
    with pytest.raises(SystemExit):
        _resolve_playlist_name(args)


def test_resolve_playlist_name_no_known_playlists_fails_clearly(monkeypatch) -> None:
    _patch_known(monkeypatch, known=[])
    args = _args(source='dj-mixer', playlist_name='')
    with pytest.raises(SystemExit) as exc_info:
        _resolve_playlist_name(args)
    assert 'no known playlists' in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# _load_known_playlists -- real dj-mixer-01/media-01 modules, synthetic
# runtime data (tmp_path), pooled regardless of source
# ---------------------------------------------------------------------------

def test_load_known_playlists_pools_both_sources(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]  # the real checkout -- real sets.py/playlists.py
    runtime_dir = tmp_path / 'runtime'
    runtime_dir.mkdir()
    (runtime_dir / 'dj_mixer_sets.json').write_text(
        '{"_meta": {"schema": "dj-mixer-01.sets", "version": 1}, '
        '"sets": {"My Crate Set": ["/x.mp3"]}, "favorites": [], "no_auto": [], "recent": []}',
        encoding='utf-8',
    )
    (runtime_dir / 'media_playlists.json').write_text(
        '{"_meta": {"schema": "media-01.playlists", "version": 1}, '
        '"playlists": {"My Media List": ["/y.mp3"]}, "excluded": [], '
        '"last_bucket": null, "prefs": {}, "favorites": [], "recent": []}',
        encoding='utf-8',
    )

    class _FakeRoot:
        def __truediv__(self, part):
            if part == 'runtime':
                return runtime_dir
            return repo_root / part

    known = _load_known_playlists(_FakeRoot())
    names_by_source = {(name, source) for name, source in known}
    assert ('My Crate Set', 'dj-mixer') in names_by_source
    assert ('My Media List', 'media') in names_by_source


def test_load_known_playlists_missing_runtime_files_yields_empty_not_error(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    class _FakeRoot:
        def __truediv__(self, part):
            if part == 'runtime':
                return tmp_path / 'nonexistent-runtime'
            return repo_root / part

    known = _load_known_playlists(_FakeRoot())
    assert known == []
