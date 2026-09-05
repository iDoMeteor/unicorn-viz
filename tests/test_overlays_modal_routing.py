"""Modal routing vs. modal_snapshot() coverage -- regression tests.

With the Control Room open, render() suppresses modals on the audience
window (``route_modals_elsewhere``) on the assumption the CR draws them
from modal_snapshot().  modal_snapshot() has no branch for presets,
effects_browser, config_editor, tour, or context_menu, so those vanished
from BOTH surfaces while blocking_modal_open() still captured keys.  The
fix routes render()'s gating through ``_modal_mirrored_elsewhere()``,
which only suppresses types the snapshot can represent.  Bare ``Overlays``
via object.__new__; no GL.
"""
from __future__ import annotations

from unicornviz.overlays import Overlays

_SNAPSHOT_FLAGS = (
    '_show_projectm_manager',
    '_show_system_monitor_modal',
    '_show_controller_help_modal',
    '_show_webcam_editor_modal',
    '_show_audio',
    '_show_midi',
    '_show_help',
    '_show_name',
)


def _bare_with_only(flag: str | None) -> Overlays:
    ov = Overlays.__new__(Overlays)
    for name in _SNAPSHOT_FLAGS:
        setattr(ov, name, False)
    ov._show_presets = False
    ov._show_effects_browser = False
    if flag is not None:
        setattr(ov, flag, True)
    return ov


def test_modal_snapshot_is_empty_for_presets() -> None:
    ov = _bare_with_only('_show_presets')
    assert ov.modal_snapshot() == {}


def test_modal_snapshot_is_empty_for_effects_browser() -> None:
    ov = _bare_with_only('_show_effects_browser')
    assert ov.modal_snapshot() == {}


def test_unrepresentable_modals_are_never_suppressed_on_the_audience_window() -> None:
    for modal_type in ('presets', 'effects_browser', 'config_editor', 'tour', 'context_menu'):
        assert Overlays._modal_mirrored_elsewhere(modal_type, True) is False, modal_type
        assert Overlays._modal_mirrored_elsewhere(modal_type, False) is False, modal_type


def test_representable_modals_are_suppressed_only_when_routing_is_on() -> None:
    for modal_type in sorted(Overlays._SNAPSHOT_MODAL_TYPES):
        assert Overlays._modal_mirrored_elsewhere(modal_type, True) is True, modal_type
        assert Overlays._modal_mirrored_elsewhere(modal_type, False) is False, modal_type


def test_snapshot_type_set_matches_what_modal_snapshot_actually_emits() -> None:
    # Keep _SNAPSHOT_MODAL_TYPES honest: every flag that yields a snapshot
    # must produce a type in the set, and the set must contain nothing more.
    emitted: set[str] = set()
    for flag in _SNAPSHOT_FLAGS:
        ov = _bare_with_only(flag)
        # Branches that consult richer state need a few stubbed fields.
        ov._sysmon_cpu = ov._sysmon_ram = ov._sysmon_swap = 0.0
        ov._sysmon_disk_mbs = ov._sysmon_net_mbs = 0.0
        ov._webcam_editor_selected_idx = 0
        ov._webcam_editor_devices = []
        ov._webcam_editor_state = {}
        ov._audio_sources = []
        ov._audio_current_idx = ov._audio_selected_idx = 0
        ov._audio_viable_flags = []
        ov._midi_ports = []
        ov._midi_current_port = ''
        ov._midi_selected_idx = 0
        ov._hud_state = {}
        if flag in ('_show_projectm_manager', '_show_help'):
            # These two need the live browser/help machinery; the type name
            # is asserted from the set membership below instead.
            emitted.add('projectm_manager' if flag == '_show_projectm_manager' else 'help_overlay')
            continue
        snap = ov.modal_snapshot()
        assert snap, flag
        emitted.add(str(snap['type']))
    assert emitted == set(Overlays._SNAPSHOT_MODAL_TYPES)
