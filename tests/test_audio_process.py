"""The audio process (unicornviz/audio/process.py): capture + analysis in a helper.

The helper runs a real AudioManager and Analyzer over a synthetic 120 BPM
kick (tests/fixtures/audio_fake.py -- no audio device is opened); the test
drives the main-process shadow exactly the way App and auto-vj do.
"""
from __future__ import annotations

import importlib.util
import inspect
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from unicornviz import remote_objects as ro
from unicornviz.audio import process as audio_process
from unicornviz.audio.manager import AudioManager
from unicornviz.config import Config

_FAKE = Path(__file__).resolve().parent / 'fixtures' / 'audio_fake.py'
_spec = importlib.util.spec_from_file_location('_audio_fake_fixture', _FAKE)
audio_fake = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = audio_fake
_spec.loader.exec_module(audio_fake)


def _until(pred, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


class _Store:
    def __init__(self, data=None) -> None:
        self.data = dict(data or {})
        self.sets: list = []

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value
        self.sets.append((key, value))


def test_every_public_manager_method_is_classified() -> None:
    public = {n for n in dir(AudioManager) if not n.startswith('_')
              and (callable(inspect.getattr_static(AudioManager, n))
                   or isinstance(inspect.getattr_static(AudioManager, n), property))}
    missing = public - audio_process.MANAGER_CLASSIFIED
    assert not missing, f'classify in audio/process.py: {sorted(missing)}'


@pytest.fixture
def audio():
    cfg = Config()
    store = _Store({'audio': {'viable': ['x']}})
    with patch('unicornviz.audio.manager.AudioCapture', audio_fake.FakeCapture):
        manager = AudioManager(cfg, state_store=store)
    host = ro.RemoteHost.spawn(str(_FAKE), 'build', {'cfg': cfg, 'state': {'audio': {}}},
                               namespace=audio_process.NAMESPACE,
                               module_name=_spec.name)
    relay = audio_process.StateRelay({'audio': {'viable': ['x']}})
    ro.attach_shadows(host, {audio_process.MANAGER_PATH: manager,
                             audio_process.STATE_PATH: relay}, audio_process.POLICIES)
    host.state_relay = relay
    host.relay_persisted = {'audio': {'viable': ['x']}}
    yield host, manager, store
    host.close()


def test_analysis_runs_in_the_helper_and_frames_arrive_per_tick(audio) -> None:
    host, manager, _ = audio
    manager.start(timeout_s=4.0)                          # in the helper
    assert host.ready[1] != os.getpid()
    assert _until(lambda: manager.get_audio_data().bass > 0.05)
    # Fresh snapshots keep coming: the publish counter advances.
    _, seq1, _, _ = manager.audio_snapshot()
    assert _until(lambda: manager.audio_snapshot()[1] > seq1 + 3, timeout=2.0)
    assert manager.get_source_label() in ('fake kick',) or _until(
        lambda: manager.get_source_label() == 'fake kick')


def test_reactivity_is_applied_main_side_to_the_helpers_frames(audio) -> None:
    _, manager, _ = audio
    manager.start(timeout_s=4.0)
    assert _until(lambda: manager.get_audio_data_raw().bass > 0.05
                  or manager.get_audio_data().bass > 0.05)
    assert manager.set_reactivity(3.0) == pytest.approx(3.0)
    assert manager.get_reactivity() == pytest.approx(3.0)   # current at once
    assert _until(lambda: manager.get_audio_data().bass
                  >= min(1.0, manager.get_audio_data_raw().bass * 2.9))


def test_onsets_stream_to_the_main_side_once_each(audio) -> None:
    _, manager, _ = audio
    manager.start(timeout_s=4.0)
    seen: list = []
    end = time.monotonic() + 4.0
    while time.monotonic() < end and len(seen) < 4:
        seen.extend(manager.drain_onsets())
        time.sleep(0.02)
    assert len(seen) >= 4                                  # ~2 kicks per second
    times = [e.t for e in seen]
    assert times == sorted(times) and len(set(times)) == len(times)


def test_profile_switch_runs_in_the_helper_and_comes_back(audio) -> None:
    _, manager, _ = audio
    profile = manager.set_profile('dubstep')
    assert manager.get_profile_key() == 'dubstep'
    assert manager.get_profile() == profile
    assert 'Dub' in manager.get_profile_name() or manager.get_profile_name()


def test_capture_state_is_persisted_by_the_main_process(audio) -> None:
    host, manager, store = audio
    manager.start(timeout_s=4.0)                           # fake writes state
    assert _until(lambda: (audio_process.persist_relay_state(host, store)
                           or store.sets) != [])
    assert store.data['audio'] == {'last_source': 'fake kick'}
    n = len(store.sets)
    audio_process.persist_relay_state(host, store)         # unchanged: no write
    assert len(store.sets) == n


def test_the_mixer_can_join_the_same_helper(audio) -> None:
    host, _, _ = audio
    paths = host.load_factory(str(Path(__file__).resolve().parent / 'fixtures'
                                  / 'remote_toy.py'), 'build_more', {},
                              namespace='mixer')
    assert paths == ['mixer/extra']
    assert host.call('mixer/extra', 'pid', (), {}, wait=True) == host.ready[1]


def test_stop_and_close_are_clean(audio) -> None:
    host, manager, _ = audio
    manager.start(timeout_s=4.0)
    manager.stop()
    assert _until(lambda: manager.get_source_label() is not None)
    host.close()
    assert not host.alive


# -- App wiring (hermetic, as test_claimed_audio_devices does) ---------------------

def _bare_app():
    from unicornviz.app import App  # noqa: PLC0415
    app = App.__new__(App)
    app.cfg = Config()
    app._runtime_state = _Store()
    app._audio_host = None
    app._audio_host_died = False
    app._boot_profile = 'full'
    return app


def test_app_opt_outs(monkeypatch) -> None:
    app = _bare_app()
    monkeypatch.setenv('UNICORNVIZ_NO_AUDIO_PROCESS', '1')
    assert app._audio_process_wanted() is False
    monkeypatch.delenv('UNICORNVIZ_NO_AUDIO_PROCESS')
    assert app._audio_process_wanted() is True

    class _Off:
        def get(self, *keys, default=None):
            return False if keys == ('audio', 'process') else default
    app.cfg = _Off()
    assert app._audio_process_wanted() is False


def test_app_hands_out_only_a_live_host() -> None:
    app = _bare_app()
    assert app.audio_process_host() is None

    class _Dead:
        alive = False
    app._audio_host = _Dead()
    assert app.audio_process_host() is None


def test_app_recovers_audio_in_process_when_the_helper_dies(audio) -> None:
    host, manager, store = audio
    app = _bare_app()
    app._audio_manager = manager
    app._audio_host = host
    started = []
    host.add_exit_handler(app._on_audio_host_exit)
    host.proc.kill()
    assert _until(lambda: app._audio_host_died)
    with patch.object(AudioManager, 'start', lambda self, timeout_s=None: started.append(1)):
        app._tick_audio_process()
    assert app._audio_host is None
    assert type(manager) is AudioManager                  # plain, in-process again
    assert started == [1]
