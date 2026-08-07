"""The seam between "the set ended" and "fire the finale" (2026-08-07).

``tests/test_auto_vj_exit_after_finale.py`` covers the *second* half of the
unattended auto-exit chain by forcing ``_timed_finale_fired = True``.  This
file covers the first half, which was reasoned through rather than tested
when the watcher landed: that a **real** ``phase: 'over'`` payload -- built
by the code dj-mixer-01 and media-01 actually run -- clears
``_check_timed_finale()``'s lead-time gate and fires the finale.

That gate is the load-bearing part of the whole plan
(``docs/planning/headless-auto-exit-plan-2026-08-07.md``): if a payload ever
stopped reaching it, nothing would fail loudly.  The finale simply would not
fire, the watcher would never see its completion edge, and an overnight run
would hang until someone noticed the next morning.  The payloads are built
here from the drop-ins' own source rather than hand-written so that renaming
a key on either side breaks this test instead of the 3am run.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_DROPINS = _ROOT / 'drop-ins'


def _load(name: str, path: Path):
    """Import a drop-in module by path, or None when it isn't checked out."""
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_AUTO_VJ = _load('t_finale_seam_auto_vj', _DROPINS / 'auto-vj-01' / 'auto_vj.py')
_DJ = _load('t_finale_seam_dj', _DROPINS / 'dj-mixer-01' / 'dj_mixer_controller.py')
_MEDIA = _load('t_finale_seam_media', _DROPINS / 'media-01' / 'media_controller.py')

pytestmark = pytest.mark.skipif(_AUTO_VJ is None, reason='auto-vj-01 not present')


def _controller(hint: dict | None):
    """A bare AutoVJController with only what _check_timed_finale() touches."""
    inst = object.__new__(_AUTO_VJ.AutoVJController)
    inst._timed_finale_fired = False
    inst._finale_auto_trigger = True
    inst._finale_lead_s = 45.0
    inst._finale_peak_lead_s = 43.0
    inst._grid = None                     # fire straight away, no downbeat wait
    inst._mode = 'CRUISE'
    inst._get_session_hint = lambda: hint
    inst._engine = SimpleNamespace(mark=lambda *a, **k: None)
    inst.fired: list[bool] = []
    inst._app = SimpleNamespace(vj_api=SimpleNamespace(
        trigger_grand_finale=lambda: (inst.fired.append(True), True)[1]))
    return inst


def _tick(inst) -> None:
    # session_remaining_s None: no wall-clock fallback, so only the payload
    # under test can possibly fire the trigger.
    _AUTO_VJ.AutoVJController._check_timed_finale(
        inst, SimpleNamespace(session_remaining_s=None))


def _dj_over_payload() -> dict:
    """What dj-mixer-01 really publishes when its playlist runs out."""
    ctl = object.__new__(_DJ.DjMixerController)
    prog = {'night_over': True, 'final_track': True, 'track_remaining_s': 0.0,
            'track_position_s': 0.0, 'track_path': '/nope.mp3',
            'index': 9, 'total': 10, 'set_name': 'Night', 'endless': False}
    return _DJ.DjMixerController._session_payload(ctl, None, prog)


@pytest.mark.skipif(_DJ is None, reason='dj-mixer-01 not present')
def test_a_real_mixer_night_over_payload_fires_the_finale():
    payload = _dj_over_payload()
    assert payload['phase'] == 'over'
    inst = _controller(payload)
    _tick(inst)
    assert inst.fired == [True]
    assert inst._timed_finale_fired is True


@pytest.mark.skipif(_DJ is None, reason='dj-mixer-01 not present')
def test_night_over_carries_no_peak_hint_that_would_defer_the_finale():
    """The 'over' branch must not leave a final_peak_in_s behind.

    ``_check_timed_finale()`` prefers ``final_peak_in_s`` and *returns early*
    when it is further out than the peak lead.  A stale peak on an already-
    finished set would silently postpone the finale past the end of the music.
    """
    payload = _dj_over_payload()
    assert 'final_peak_in_s' not in payload
    assert payload['seconds_left'] == 0.0


@pytest.mark.skipif(_MEDIA is None, reason='media-01 not present')
def test_a_real_media_set_over_payload_fires_the_finale():
    """media-01 publishes the identical shape, and must fire identically."""
    sent: list[tuple[str, dict]] = []
    ctl = object.__new__(_MEDIA.MediaController)
    ctl._set_over = False
    ctl._app = SimpleNamespace(vj_api=SimpleNamespace(
        publish_session=lambda src, payload: sent.append((src, payload))))
    _MEDIA.MediaController._note_set_over(ctl)
    assert sent, 'media-01 published nothing when its list ran out'
    payload = sent[-1][1]
    assert payload['phase'] == 'over'

    inst = _controller(payload)
    _tick(inst)
    assert inst.fired == [True]


def test_a_running_set_does_not_fire_the_finale():
    """The negative case, so the two above cannot pass by firing on anything."""
    inst = _controller({'phase': 'running', 'source': 'clock',
                        'seconds_left': 600.0, 'minutes_left': 10.0})
    _tick(inst)
    assert inst.fired == []
    assert inst._timed_finale_fired is False
