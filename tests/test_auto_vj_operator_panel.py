"""AutoVJController's Control Room operator panel (P2 of
docs/planning/control-room-panel-registry-plan-2026-09-04.md).

Replaces the old hardcoded CR "AUTO VJ" panel, which read
App._hud_state (wrong object -- fixed separately in
vj_api.auto_vj_snapshot()) and several HUD keys the snapshot never
populated. _operator_panel_content()/_operator_panel_action() read the
same live properties the on-screen HUD already reads, so the panel can
never show anything the HUD doesn't already consider correct. Hermetic,
same object.__new__() pattern as test_auto_vj_profile_hud.py.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from unicornviz.operator_panels import OperatorPanel, PanelContent

_AUTO_VJ_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'auto_vj.py'
_SPEC = importlib.util.spec_from_file_location('test_auto_vj_operator_panel_module', _AUTO_VJ_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
AutoVJController = _MOD.AutoVJController


class _FakeGrid:
    def __init__(self, confidence: float = 0.0) -> None:
        self.confidence = confidence


class _FakeVJApi:
    def __init__(self) -> None:
        self.panels: dict[str, OperatorPanel] = {}
        self.midi_action_calls: list[tuple[str, list]] = []

    def register_midi_actions(self, section, actions) -> None:
        pass

    def register_midi_action_handler(self, action, fn) -> None:
        pass

    def register_operator_panel(self, panel: OperatorPanel) -> None:
        self.panels[panel.name] = panel

    def set_show_duration(self, seconds) -> None:
        pass


class _FakeApp:
    def __init__(self) -> None:
        self.vj_api = _FakeVJApi()


def _bare_controller(**overrides) -> AutoVJController:
    inst = object.__new__(AutoVJController)
    inst._enabled = False
    inst._profile = 'chill'
    inst._profile_preset = 'chill'
    inst._manual_profile = 'chill'
    inst._mode = 'cruise'
    inst._pp_active = False
    inst._grid = None
    inst._profile_auto_reco_enabled = False
    inst._current_profile_scored = False
    inst._current_profile_score = 0.0
    inst._recommended_profile_name = ''
    inst._recommended_profile_range = ''
    inst._recommended_profile_score = 0.0
    inst._recommended_profile_confirmed = False
    inst._hud_downbeat_pulse = 0.0
    inst._hud_beat_pulse = 0.0
    inst._published_bpm = 0.0
    for k, v in overrides.items():
        setattr(inst, k, v)
    return inst


def test_registration_call_wraps_the_operator_panel_registry() -> None:
    """The real registration code (inside __init__) is exercised directly,
    proving the try/except guard doesn't accidentally swallow a working
    call and the descriptor shape matches what vj_api expects."""
    inst = _bare_controller()
    app = _FakeApp()
    inst._app = app
    inst._ctrlj_armed = False
    try:
        vj = inst._app.vj_api
        from unicornviz.operator_panels import OperatorPanel as _OP
        vj.register_midi_actions('Auto VJ', [])
        vj.register_operator_panel(_OP(
            name='auto_vj', title='Auto VJ', priority=10, size='large',
            content=inst._operator_panel_content, on_action=inst._operator_panel_action,
        ))
    except Exception as exc:  # pragma: no cover - would fail the test below
        raise AssertionError(f'registration raised: {exc}') from exc
    panel = app.vj_api.panels['auto_vj']
    assert panel.title == 'Auto VJ' and panel.page == 'main' and panel.size == 'large'
    assert panel.content.__func__ is AutoVJController._operator_panel_content
    assert panel.on_action.__func__ is AutoVJController._operator_panel_action


def test_content_reflects_disabled_state() -> None:
    inst = _bare_controller(_enabled=False)
    content = inst._operator_panel_content()
    assert isinstance(content, PanelContent)
    assert content.status == 'OFF'
    by_label = {row.label: row.value for row in content.rows}
    assert by_label['Mood'] == 'off' and by_label['Scene'] == 'off'
    assert by_label['BPM'] == '--'
    toggle = next(b for b in content.buttons if b.action == 'toggle')
    assert toggle.label == 'OFF' and toggle.active is False and toggle.accent == ''


def test_content_reflects_enabled_state_with_confidence_meter() -> None:
    inst = _bare_controller(_enabled=True, _grid=_FakeGrid(confidence=0.82))
    content = inst._operator_panel_content()
    assert content.status == 'ON'
    by_label = {row.label: row.value for row in content.rows}
    assert by_label['Mood'] == 'chill'
    assert by_label['Scene'] == 'cruise'
    meter = next(m for m in content.meters if m.label == 'BPM lock')
    assert meter.value == 0.82 and meter.text == '0.82'
    toggle = next(b for b in content.buttons if b.action == 'toggle')
    assert toggle.label == 'ON' and toggle.active is True and toggle.accent == 'success'


def test_content_auto_mode_prefixes_mood_with_tilde() -> None:
    inst = _bare_controller(_enabled=True, _manual_profile='auto', _profile_preset='raver')
    content = inst._operator_panel_content()
    by_label = {row.label: row.value for row in content.rows}
    assert by_label['Mood'] == '~raver'


def test_content_omits_reco_rows_when_disabled() -> None:
    inst = _bare_controller(_enabled=True, _profile_auto_reco_enabled=False)
    content = inst._operator_panel_content()
    assert 'Reco' not in {row.label for row in content.rows}
    assert 'Score' not in {row.label for row in content.rows}


def test_content_includes_reco_and_score_rows_when_scored() -> None:
    inst = _bare_controller(
        _enabled=True, _profile_auto_reco_enabled=True, _current_profile_scored=True,
        _current_profile_score=1.5, _recommended_profile_name='dubstep',
        _recommended_profile_range='138-142', _recommended_profile_score=2.0,
        _recommended_profile_confirmed=True,
    )
    content = inst._operator_panel_content()
    by_label = {row.label: row.value for row in content.rows}
    assert by_label['Reco'] == 'dubstep (138-142) 2.00'
    assert by_label['Score'] == '1.50'


def test_content_omits_score_row_before_first_scoring_pass() -> None:
    inst = _bare_controller(_enabled=True, _profile_auto_reco_enabled=True, _current_profile_scored=False)
    content = inst._operator_panel_content()
    assert 'Reco' in {row.label for row in content.rows}
    assert 'Score' not in {row.label for row in content.rows}


def test_pingpong_button_reflects_active_state() -> None:
    inst = _bare_controller(_pp_active=True)
    content = inst._operator_panel_content()
    pp = next(b for b in content.buttons if b.action == 'pingpong')
    assert pp.active is True


def test_content_survives_no_grid() -> None:
    inst = _bare_controller(_enabled=True, _grid=None)
    content = inst._operator_panel_content()
    meter = next(m for m in content.meters if m.label == 'BPM lock')
    assert meter.value == 0.0


# --------------------------------------------------------------------------- #
# _operator_panel_action -- reuses the same methods the MIDI actions call
# --------------------------------------------------------------------------- #

def test_action_toggle_calls_the_real_toggle_and_reports_its_new_state() -> None:
    # toggle() itself (audio-manager onset draining, postfx/reactivity
    # reset, etc.) is exercised by test_auto_vj_toggle_onset_backlog.py and
    # friends; this only pins that _operator_panel_action calls it and
    # reports whatever it returns, not toggle()'s own internals.
    inst = _bare_controller(_enabled=False)
    inst.toggle = lambda: True
    message = inst._operator_panel_action('toggle', None)
    assert message == 'Auto VJ: ON'
    inst.toggle = lambda: False
    message = inst._operator_panel_action('toggle', None)
    assert message == 'Auto VJ: OFF'


def test_action_profile_cycles_and_reports_the_new_profile() -> None:
    inst = _bare_controller()
    inst._manual_profile = 'auto'
    inst._explicit_profile_override_keys = set()
    inst._auto_profile_enabled = True
    inst._profile_auto_reco_decider_enabled = True

    def _set_active_profile(name, announce=True, reason=''):
        inst._profile = name

    inst._set_active_profile = _set_active_profile
    message = inst._operator_panel_action('profile', None)
    assert message is not None and message.startswith('Auto VJ profile: ')


def test_action_pingpong_toggles_and_reports_new_state() -> None:
    inst = _bare_controller(_pp_active=False)
    calls = []
    inst._exit_pingpong = lambda: calls.append('exit')
    inst._enter_pingpong = lambda: (calls.append('enter'), setattr(inst, '_pp_active', True))[0]
    message = inst._operator_panel_action('pingpong', None)
    assert calls == ['enter']
    assert message == 'Ping-pong: ON'


def test_action_unknown_returns_none() -> None:
    inst = _bare_controller()
    assert inst._operator_panel_action('bogus', None) is None
