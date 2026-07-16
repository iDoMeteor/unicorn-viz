"""Audit + Visual bloat cleanup — regression tests.

CORE_HELP_SECTIONS['Audio + Visual'] had grown to 30 entries, many of which
did not belong there:

- Pure duplicates of what a drop-in already documents in its own
  HELP_ENTRIES (Candy Frame, Post FX quick-hit trigger, Grand Finale,
  Control Room) — shown twice in the help overlay for no reason.
- Hotkeys owned by drop-ins that had never registered HELP_ENTRIES at all
  (Spotify auth, local media, chat overlay), hand-documented in core instead
  of their own drop-in, violating the "single source of truth" rule.
- Hotkeys core dispatches on behalf of a drop-in's own UI (webcam editor
  modal, MIDI controller help modal), which read better grouped with that
  drop-in's other entries than buried in a generic core bucket.

This guards that those specific entries stay out of CORE_HELP_SECTIONS and
that each drop-in now documents its own keys.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from unicornviz.overlays import Overlays

_DROPINS_ROOT = Path(__file__).resolve().parents[1] / 'drop-ins'


def _load_dropin_module(dropin_dir: str, filename: str):
    path = _DROPINS_ROOT / dropin_dir / filename
    module_name = 'test_dedup_' + dropin_dir.replace('-', '_') + '_' + filename[:-3]
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module  # dataclasses need this during exec_module
    spec.loader.exec_module(module)
    return module


def _audio_visual_entries() -> list[tuple[str, str]]:
    return next(entries for name, entries in Overlays.CORE_HELP_SECTIONS if name == 'Audio + Visual')


def _core_entry_keys() -> set[str]:
    keys: set[str] = set()
    for _section, entries in Overlays.CORE_HELP_SECTIONS:
        keys |= {key for key, _desc in entries}
    return keys


# --------------------------------------------------------------------------- #
# The pure duplicates and relocated entries must not reappear in core
# --------------------------------------------------------------------------- #

_REMOVED_FROM_CORE = [
    'Ctrl+Alt+1..9 / 0',   # Post FX quick-hit — postfx-01 already documents it
    'Ctrl+Alt+C',          # Candy Frame — candy-frame-01 already documents it
    'Ctrl+Alt+S',          # Spotify auth — now spotify-01's own HELP_ENTRIES
    'Ctrl+Alt+Shift+S',
    'Ctrl+Alt+M',          # Local media — now media-01's own HELP_ENTRIES
    'Ctrl+Alt+N',
    'Ctrl+Alt+B',
    'Ctrl+Alt+Shift+M',
    'Ctrl+Alt+T',          # Chat overlay — now chat-01's own HELP_ENTRIES
    'Ctrl+Alt+[',
    'Ctrl+Alt+]',
    'Wheel Up/Down',       # Scroll FX — now postfx-01's own HELP_ENTRIES
    'Ctrl+Wheel Up/Down',
    'Middle Click',
    'Ctrl+Alt+F',          # Grand Finale — grand-finale-01 already documents it
    'Ctrl+Alt+Shift+F',
    'Shift+M',             # Control Room — control-room-01 already documents it
    'Ctrl+Alt+K',          # Webcam editor modal — now webcam-01's own HELP_ENTRIES
    'Ctrl+Alt+H',          # Controller help modal — now midi-controllers-01's
]


def test_removed_entries_are_gone_from_core_help_sections() -> None:
    keys = _core_entry_keys()
    still_present = [k for k in _REMOVED_FROM_CORE if k in keys]
    assert not still_present, f'These belong to a drop-in, not core: {still_present}'


def test_audio_visual_section_shrank_to_genuinely_core_entries() -> None:
    entries = _audio_visual_entries()
    assert len(entries) <= 12, (
        f'Audio + Visual has {len(entries)} entries — check for drop-in '
        'hotkeys that should live in their own drop-in HELP_ENTRIES instead'
    )


def test_audio_visual_only_contains_genuinely_core_keys() -> None:
    expected = {
        'e', 'a / A', 'Ctrl+A', 'Alt+A / Alt+Shift+A', 'm', 'Alt+M',
        'B', 'c', 'Ctrl+Shift+P', 'Ctrl+L', 'i', 'w',
    }
    actual = {key for key, _desc in _audio_visual_entries()}
    assert actual == expected


# --------------------------------------------------------------------------- #
# Each relocated drop-in now documents its own keys
# --------------------------------------------------------------------------- #

def test_spotify_declares_its_own_help_entries() -> None:
    module = _load_dropin_module('spotify-01', 'spotify_controller.py')
    keys = {k for _s, k, _d in module.HELP_ENTRIES}
    assert {'Ctrl+Alt+S', 'Ctrl+Alt+Shift+S'} <= keys


def test_media_declares_its_own_help_entries() -> None:
    module = _load_dropin_module('media-01', 'media_controller.py')
    keys = {k for _s, k, _d in module.HELP_ENTRIES}
    assert {'Ctrl+Alt+M', 'Ctrl+Alt+N', 'Ctrl+Alt+B', 'Ctrl+Alt+Shift+M'} <= keys


def test_chat_declares_its_own_help_entries() -> None:
    module = _load_dropin_module('chat-01', 'chat_controller.py')
    keys = {k for _s, k, _d in module.HELP_ENTRIES}
    assert 'C' in keys and 'Ctrl+C' in keys


def test_postfx_declares_scroll_fx_help_entries() -> None:
    module = _load_dropin_module('postfx-01', 'postfx_controller.py')
    keys = {k for _s, k, _d in module.HELP_ENTRIES}
    assert {'Wheel Up/Down', 'Ctrl+Wheel Up/Down', 'Middle Click'} <= keys


def test_webcam_declares_editor_modal_help_entry() -> None:
    module = _load_dropin_module('webcam-01', 'webcam_overlay.py')
    keys = {k for _s, k, _d in module.WebcamSystem.HELP_ENTRIES}
    assert 'Ctrl+Alt+K' in keys


def test_midi_controllers_declares_help_modal_entry() -> None:
    module = _load_dropin_module('midi-controllers-01', 'controller_presets.py')
    keys = {k for _s, k, _d in module.HELP_ENTRIES}
    assert 'Ctrl+Alt+H' in keys
