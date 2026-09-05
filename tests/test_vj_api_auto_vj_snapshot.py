"""VJApi.auto_vj_snapshot() -- HUD-state source regression tests.

The snapshot used to read ``app._hud_state``, but the HUD dict lives on
``Overlays`` (App only writes it through ``overlays.set_hud_state``), so
mood/scene/bpm always came back as their '-' placeholders on the Control
Room's Auto VJ panel.  Hermetic: a stub App with a stub overlays object,
no GL, no Auto VJ drop-in.
"""
from __future__ import annotations

from unicornviz.vj_api import VJApi


class _StubOverlays:
    def __init__(self, hud: dict[str, str]) -> None:
        self._hud_state = hud


class _StubAutoVJ:
    enabled = True
    status_text = 'AUTO VJ ON'
    _profile = 'hard'
    _mode = 'auto'


class _StubApp:
    def __init__(self, overlays, auto_vj=None) -> None:
        self._overlays = overlays
        self._auto_vj = auto_vj


_HUD = {
    'auto_vj_mood': 'peak',
    'auto_vj_scene': 'drop',
    'auto_vj_bpm': '128.0',
    'auto_vj_action_in': '3.2s',
    'audio_profile': 'techno',
    'audio_profile_reco': 'house',
    'audio_profile_score': '0.81',
}


def test_snapshot_reads_hud_fields_from_overlays() -> None:
    api = VJApi(_StubApp(_StubOverlays(dict(_HUD)), _StubAutoVJ()))
    snap = api.auto_vj_snapshot()
    assert snap['available'] is True
    assert snap['enabled'] is True
    assert snap['profile'] == 'hard'
    assert snap['mode'] == 'auto'
    assert snap['mood'] == 'peak'
    assert snap['scene'] == 'drop'
    assert snap['bpm'] == '128.0'
    assert snap['action_in'] == '3.2s'
    assert snap['audio_profile'] == 'techno'
    assert snap['audio_profile_reco'] == 'house'
    assert snap['audio_profile_score'] == '0.81'


def test_snapshot_hud_fields_come_through_without_auto_vj_loaded() -> None:
    # The audio-profile fields are core HUD state; they must not depend on
    # the auto-vj drop-in being present.
    api = VJApi(_StubApp(_StubOverlays(dict(_HUD)), auto_vj=None))
    snap = api.auto_vj_snapshot()
    assert snap['available'] is False
    assert snap['status'] == 'AUTO VJ UNAVAILABLE'
    assert snap['mood'] == 'peak'
    assert snap['audio_profile'] == 'techno'


def test_snapshot_degrades_to_placeholders_when_overlays_is_none() -> None:
    api = VJApi(_StubApp(overlays=None, auto_vj=_StubAutoVJ()))
    snap = api.auto_vj_snapshot()
    assert snap['available'] is True
    assert snap['mood'] == '-'
    assert snap['scene'] == '-'
    assert snap['bpm'] == '--'
    assert snap['action_in'] == '--'


def test_snapshot_ignores_a_stale_app_side_hud_state() -> None:
    # Guard against the old read path creeping back: an App-level
    # _hud_state must not be what the snapshot reports.
    app = _StubApp(_StubOverlays({'auto_vj_mood': 'from-overlays'}), _StubAutoVJ())
    app._hud_state = {'auto_vj_mood': 'from-app'}
    snap = VJApi(app).auto_vj_snapshot()
    assert snap['mood'] == 'from-overlays'
