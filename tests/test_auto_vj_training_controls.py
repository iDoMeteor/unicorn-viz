from __future__ import annotations

import importlib.util
from pathlib import Path

import sdl2

from unicornviz.overlays import Overlays


_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_AUTO_VJ_SPEC = importlib.util.spec_from_file_location('test_auto_vj_training_controls_module', _AUTO_VJ_PATH)
assert _AUTO_VJ_SPEC is not None and _AUTO_VJ_SPEC.loader is not None
_AUTO_VJ_MODULE = importlib.util.module_from_spec(_AUTO_VJ_SPEC)
_AUTO_VJ_SPEC.loader.exec_module(_AUTO_VJ_MODULE)
AutoVJController = _AUTO_VJ_MODULE.AutoVJController


class _Writer:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.calls: list[bool] = []

    def set_enabled(self, enabled: bool) -> bool:
        self.calls.append(enabled)
        self.enabled = enabled
        return self.enabled


def _controller(live_enabled: bool = False, sequence_enabled: bool = False) -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._live_corpus_writer = _Writer(live_enabled)
    inst._sequence_corpus_writer = _Writer(sequence_enabled)
    return inst


def test_training_help_entries_include_new_shortcuts() -> None:
    entries = set(AutoVJController.HELP_ENTRIES)

    assert ('Auto VJ', 'Ctrl+T', 'Turn both trainers on') in entries
    assert ('Auto VJ', 'Alt+T', 'Turn both trainers off') in entries
    assert ('Auto VJ', 'Ctrl+Shift+T', 'Toggle live training') in entries
    assert ('Auto VJ', 'Alt+Shift+T', 'Toggle sequence training') in entries


def test_ctrl_t_enables_both_trainers() -> None:
    controller = _controller()

    assert controller.handle_key(sdl2.SDLK_t, sdl2.KMOD_CTRL) == 'TRAINERS * ON'
    assert controller.training_badge() == '*'
    assert controller._live_corpus_writer.calls == [True]
    assert controller._sequence_corpus_writer.calls == [True]


def test_alt_t_disables_both_trainers() -> None:
    controller = _controller(True, True)

    assert controller.handle_key(sdl2.SDLK_t, sdl2.KMOD_ALT) == 'TRAINERS OFF'
    assert controller.training_badge() == ''
    assert controller._live_corpus_writer.calls == [False]
    assert controller._sequence_corpus_writer.calls == [False]


def test_ctrl_shift_t_toggles_live_training() -> None:
    controller = _controller(True, True)

    assert controller.handle_key(sdl2.SDLK_t, sdl2.KMOD_CTRL | sdl2.KMOD_SHIFT) == 'SEQUENCE TRAINING ON'
    assert controller.training_badge() == '='
    assert controller._live_corpus_writer.calls == [False]
    assert controller._sequence_corpus_writer.calls == []


def test_alt_shift_t_toggles_sequence_training() -> None:
    controller = _controller(True, True)

    assert controller.handle_key(sdl2.SDLK_t, sdl2.KMOD_ALT | sdl2.KMOD_SHIFT) == 'LIVE TRAINING ON'
    assert controller.training_badge() == '+'
    assert controller._live_corpus_writer.calls == []
    assert controller._sequence_corpus_writer.calls == [False]


def test_auto_vj_status_label_includes_trainer_badge() -> None:
    overlays = Overlays.__new__(Overlays)
    overlays._hud_state = {
        'auto_vj_label': 'AUTO VJ',
        'auto_vj_training_badge': '*',
    }

    assert overlays._auto_vj_status_label() == 'AUTO VJ *'