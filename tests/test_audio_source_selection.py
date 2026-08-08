"""Audio source selection — safety and menu structure.

Context: selecting a webcam microphone from the Alt+A menu killed the whole
process with `Fatal Python error: Aborted` — a heap-corruption abort raised
from the reader thread's numpy math, with no Python exception anywhere.  The
switch replaced the stream while the reader could still be inside
``stream.read()`` on it.

These cover both halves of the fix: the switch can no longer tear a stream
out from under its reader, and a microphone is no longer something the
cursor can wander onto and activate.
"""
from __future__ import annotations

from unicornviz.audio.capture import (
    AudioCapture,
    _is_output_source,
    _OUTPUT_NAME_HINTS,
)


# --------------------------------------------------------------------------
# Output vs input classification
# --------------------------------------------------------------------------

def test_sink_descriptions_classify_as_outputs() -> None:
    """PipeWire endpoints arrive named by description, not by role."""
    sinks = {'built-in audio analog stereo', 'ddj-rev1 analog surround 4.0'}
    assert _is_output_source('DDJ-REV1 Analog Surround 4.0', sinks) is True
    assert _is_output_source('Built-in Audio Analog Stereo', sinks) is True


def test_microphones_classify_as_inputs() -> None:
    """The exact device that took the app down must read as an input."""
    sinks = {'built-in audio analog stereo', 'ddj-rev1 analog surround 4.0'}
    assert _is_output_source('HD Webcam C615 Mono', sinks) is False
    assert _is_output_source('C922 Pro Stream Webcam Analog Stereo', sinks) is False
    # The controller's line *input* is not its output monitor.
    assert _is_output_source('DDJ-REV1 Analog Stereo', sinks) is False


def test_name_hints_work_without_pactl() -> None:
    """Windows and bare-Pulse setups have no sink table to consult."""
    for hint in _OUTPUT_NAME_HINTS:
        assert _is_output_source(f'Some Device {hint}', set()) is True
    assert _is_output_source('Microphone', set()) is False


# --------------------------------------------------------------------------
# Viability defaults
# --------------------------------------------------------------------------

def _capture_with(devices, outputs) -> AudioCapture:
    cap = AudioCapture()
    cap._candidate_devices = list(range(len(devices)))
    cap._viable_source_keys = set()
    cap._candidate_keys = lambda: [f'name:{d.lower()}' for d in devices]  # noqa: SLF001
    cap.source_is_output_flags = lambda: list(outputs)
    return cap


def test_inputs_are_not_viable_by_default() -> None:
    """A mic must never be enabled just because it was enumerated."""
    cap = _capture_with(['Speakers Monitor', 'Webcam Mic'], [True, False])
    assert cap.source_viable_flags() == [True, False]


def test_all_enabled_when_nothing_looks_like_an_output() -> None:
    """Better a usable mic than a selector with no selectable source."""
    cap = _capture_with(['Mic A', 'Mic B'], [False, False])
    assert cap.source_viable_flags() == [True, True]


def test_saved_preferences_survive_the_new_default() -> None:
    """An operator who enabled a mic on purpose keeps it enabled."""
    cap = _capture_with(['Speakers Monitor', 'Webcam Mic'], [True, False])
    cap._viable_source_keys = {'name:webcam mic'}
    assert cap.source_viable_flags() == [False, True]


# --------------------------------------------------------------------------
# Non-viable sources cannot be activated
# --------------------------------------------------------------------------

def test_select_source_refuses_a_non_viable_row() -> None:
    """Return on a disabled row used to activate it anyway."""
    cap = _capture_with(['Speakers Monitor', 'Webcam Mic'], [True, False])
    switched: list[int] = []
    cap._switch_to_candidate_index = lambda i: switched.append(i)  # noqa: SLF001
    cap.current_source_label = lambda: 'Speakers Monitor'

    assert cap.select_source(1) == 'Speakers Monitor'
    assert switched == []


def test_select_source_allows_a_viable_row() -> None:
    cap = _capture_with(['Speakers Monitor', 'Webcam Mic'], [True, False])
    switched: list[int] = []
    cap._switch_to_candidate_index = lambda i: switched.append(i) or 'ok'  # noqa: SLF001

    cap.select_source(0)
    assert switched == [0]


def test_cycle_source_steps_over_non_viable_sources() -> None:
    """Cycling is a live hotkey; it must not land the show on a mic."""
    cap = _capture_with(
        ['Speakers Monitor', 'Webcam Mic', 'Other Monitor'],
        [True, False, True],
    )
    cap._candidate_index = 0
    switched: list[int] = []
    cap._switch_to_candidate_index = lambda i: switched.append(i) or 'ok'  # noqa: SLF001
    cap.current_source_index = lambda: 0

    cap.cycle_source(1)
    assert switched == [2], 'should have skipped the mic at index 1'


# --------------------------------------------------------------------------
# Selector layout: outputs first, divider, inputs — each sorted
# --------------------------------------------------------------------------

class _Manager:
    def __init__(self, labels, outputs, viable=None, active=0) -> None:
        self._labels, self._outputs = labels, outputs
        self._viable = viable if viable is not None else list(outputs)
        self._active = active
        self.selected: list[int] = []

    def list_sources(self):
        return list(self._labels)

    def source_is_output_flags(self):
        return list(self._outputs)

    def source_viable_flags(self):
        return list(self._viable)

    def get_source_index(self):
        return self._active

    def select_source(self, index):
        self.selected.append(index)
        return self._labels[index]

    def toggle_source_viable(self, index):
        self.selected.append(index)
        return True, 'toggled'


def _app_with(manager):
    from unicornviz.app import App
    app = object.__new__(App)
    app._audio_manager = manager
    app._audio_source_rows = []
    app._audio_source_dividers = set()
    return app


def test_menu_groups_outputs_then_inputs_each_sorted() -> None:
    app = _app_with(_Manager(
        labels=['Zeta Monitor', 'beta Mic', 'Alpha Monitor', 'aardvark Mic'],
        outputs=[True, False, True, False],
    ))
    rows = app.get_audio_sources()
    assert rows == [
        'Alpha Monitor',
        'Zeta Monitor',
        app.AUDIO_SELECTOR_DIVIDER,
        'aardvark Mic',
        'beta Mic',
    ]
    assert app.get_audio_source_dividers() == {2}


def test_no_divider_when_there_are_no_inputs() -> None:
    app = _app_with(_Manager(['B Monitor', 'A Monitor'], [True, True]))
    assert app.get_audio_sources() == ['A Monitor', 'B Monitor']
    assert app.get_audio_source_dividers() == set()


def test_rows_map_back_to_the_right_candidate() -> None:
    """Reordering the menu must not repoint selection at the wrong device."""
    mgr = _Manager(
        labels=['Zeta Monitor', 'beta Mic', 'Alpha Monitor'],
        outputs=[True, False, True],
        viable=[True, True, True],
    )
    app = _app_with(mgr)
    app.get_audio_sources()          # rows: Alpha(2), Zeta(0), divider, beta(1)
    app.select_audio_source(0)
    app.select_audio_source(3)
    assert mgr.selected == [2, 1]


def test_selecting_the_divider_does_nothing() -> None:
    mgr = _Manager(['A Monitor', 'z Mic'], [True, False], viable=[True, True])
    app = _app_with(mgr)
    app.get_audio_sources()
    assert app.select_audio_source(1) == 'Audio source: (divider)'
    assert mgr.selected == []


def test_active_source_highlights_its_reordered_row() -> None:
    mgr = _Manager(
        labels=['Zeta Monitor', 'Alpha Monitor'], outputs=[True, True], active=0,
    )
    app = _app_with(mgr)
    app.get_audio_sources()
    assert app.get_audio_source_index() == 1   # Zeta sorts second


def test_viable_flags_follow_the_reorder_and_divider_is_never_viable() -> None:
    mgr = _Manager(
        labels=['Zeta Monitor', 'beta Mic'], outputs=[True, False],
        viable=[True, False],
    )
    app = _app_with(mgr)
    app.get_audio_sources()
    assert app.get_audio_source_viable_flags() == [True, False, False]


# --------------------------------------------------------------------------
# Auto-selection ranking
# --------------------------------------------------------------------------

def test_outputs_rank_ahead_of_inputs(monkeypatch) -> None:
    """Regression: the show's output ranked 7th, below five microphones.

    The Linux tiers detect a monitor from the device *name* and hostapi.
    PipeWire endpoints arriving through the JACK hostapi satisfy neither —
    they are plain descriptions — so every candidate landed in one tier and
    the order degraded to USB enumeration order.
    """
    import unicornviz.audio.capture as cap_mod

    devices = [
        {'name': 'C922 Pro Stream Webcam Analog Stereo', 'max_input_channels': 2,
         'hostapi': 0},
        {'name': 'DDJ-REV1 Analog Stereo', 'max_input_channels': 2, 'hostapi': 0},
        {'name': 'HD Webcam C615 Mono', 'max_input_channels': 1, 'hostapi': 0},
        {'name': 'DDJ-REV1 Analog Surround 4.0', 'max_input_channels': 4,
         'hostapi': 0},
        {'name': 'Built-in Audio Analog Stereo', 'max_input_channels': 2,
         'hostapi': 0},
    ]
    sinks = {'ddj-rev1 analog surround 4.0', 'built-in audio analog stereo'}

    monkeypatch.setattr(cap_mod, '_SD_AVAILABLE', True)
    monkeypatch.setattr(cap_mod, '_pulse_sink_descriptions', lambda: sinks)
    monkeypatch.setattr(cap_mod.sd, 'query_devices', lambda: devices)
    monkeypatch.setattr(
        cap_mod.sd, 'query_hostapis',
        lambda: [{'name': 'JACK Audio Connection Kit'}],
    )

    order = [d for d in cap_mod._candidate_monitor_devices('') if d is not None]
    kinds = [
        cap_mod._is_output_source(devices[i]['name'], sinks) for i in order
    ]
    assert kinds == sorted(kinds, reverse=True), (
        'every output must precede every input'
    )
    # The controller's output is now reachable before any microphone.
    assert order.index(3) < order.index(2)


def test_ranking_unchanged_when_nothing_can_be_classified(monkeypatch) -> None:
    """No pactl and no name hints: degrade to the previous order, not chaos."""
    import unicornviz.audio.capture as cap_mod

    devices = [
        {'name': 'Device A', 'max_input_channels': 2, 'hostapi': 0},
        {'name': 'Device B', 'max_input_channels': 2, 'hostapi': 0},
    ]
    monkeypatch.setattr(cap_mod, '_SD_AVAILABLE', True)
    monkeypatch.setattr(cap_mod, '_pulse_sink_descriptions', lambda: set())
    monkeypatch.setattr(cap_mod.sd, 'query_devices', lambda: devices)
    monkeypatch.setattr(
        cap_mod.sd, 'query_hostapis', lambda: [{'name': 'PulseAudio'}])

    order = [d for d in cap_mod._candidate_monitor_devices('') if d is not None]
    assert order == [0, 1]
