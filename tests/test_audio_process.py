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
    # The helper is seeded with the same state as the main side's baseline, as
    # start_audio_process() does; a mismatched seed made the helper's first
    # publication look like a change and persist {} over 'viable' (b328b46).
    host = ro.RemoteHost.spawn(str(_FAKE), 'build', {'cfg': cfg, 'state': {'audio': {'viable': ['x']}}},
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
    # Wait for the value itself, not for "any write": the relay can publish an empty
    # 'audio' first and the real value a tick later (a load-dependent race that failed a
    # full-suite push at load average ~20).
    def persisted() -> bool:
        audio_process.persist_relay_state(host, store)
        return store.data.get('audio') == {'last_source': 'fake kick'}

    assert _until(persisted)
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


def test_reactivity_stays_main_side_without_a_round_trip(audio) -> None:
    """auto-vj drifts reactivity every frame; the helper never reads it."""
    host, manager, _ = audio
    helper_before = host.call(audio_process.MANAGER_PATH, '__getattribute__',
                              ('_reactivity',), {}, wait=True)
    assert manager.set_reactivity(2.5) == pytest.approx(2.5)
    assert manager.get_reactivity() == pytest.approx(2.5)
    assert host.call(audio_process.MANAGER_PATH, '__getattribute__',
                     ('_reactivity',), {}, wait=True) == helper_before
    time.sleep(0.1)                                   # publishes don't clobber it
    assert manager.get_reactivity() == pytest.approx(2.5)


def test_claimed_devices_are_pushed_only_when_they_change() -> None:
    app = _bare_app()
    pushes: list = []

    class _Mgr:
        def set_claimed_device_names(self, names):
            pushes.append(set(names))

    class _Mixer:
        names = ['DDJ-REV1']
        def owned_audio_device_names(self):
            return set(self.names)

    app._audio_manager = _Mgr()
    app._dj_mixer = _Mixer()
    for _ in range(5):
        app._refresh_claimed_audio_devices()
    assert pushes == [{'DDJ-REV1'}]
    app._dj_mixer.names = ['DDJ-REV1', 'Headphones']
    app._refresh_claimed_audio_devices()
    assert pushes[-1] == {'DDJ-REV1', 'Headphones'} and len(pushes) == 2
    app._claimed_pushed = None                        # what recovery does
    app._refresh_claimed_audio_devices()
    assert len(pushes) == 3


# --- persist_relay_state never writes an empty or stale value over a good one ---
# Review of b328b46 (2026-10-01): the `audio` fixture seeds the helper with
# {'audio': {}} but the main side with {'audio': {'viable': ['x']}}, so the
# helper's first publication (its own seed) differs from the main-side baseline
# and the fixture sees an "empty first" write.  start_audio_process() seeds both
# sides from the same dict, so production has no such window.  These tests pin
# that: the store only ever receives values the capture actually wrote.

class _Relay:
    def __init__(self, values) -> None:
        self.values = values


class _Host:
    def __init__(self, values, persisted) -> None:
        self.state_relay = _Relay(values)
        self.relay_persisted = dict(persisted)


def test_persist_writes_nothing_while_the_relay_still_holds_its_seed() -> None:
    seed = {'audio': {'viable': ['x'], 'last_source': 'mic'}}
    store = _Store(seed)
    host = _Host(dict(seed), seed)                 # before the helper publishes anything
    audio_process.persist_relay_state(host, store)
    assert store.sets == []


def test_persist_never_erases_a_key_the_relay_does_not_carry() -> None:
    """A relay with no 'audio' key (helper died before publishing, or a reset
    shadow) must not blank the store: persist only copies keys that changed."""
    store = _Store({'audio': {'last_source': 'mic'}})
    host = _Host({}, {'audio': {'last_source': 'mic'}})
    audio_process.persist_relay_state(host, store)
    assert store.sets == [] and store.data['audio'] == {'last_source': 'mic'}


def test_the_store_only_ever_receives_what_the_capture_wrote() -> None:
    """End to end with consistent seeds: no write of the seed, an empty dict or
    anything else before the capture's own value."""
    cfg = Config()
    seed = {'audio': {'viable': ['x']}}
    store = _Store(seed)
    host = ro.RemoteHost.spawn(str(_FAKE), 'build', {'cfg': cfg, 'state': seed},
                               namespace=audio_process.NAMESPACE, module_name=_spec.name)
    try:
        with patch('unicornviz.audio.manager.AudioCapture', audio_fake.FakeCapture):
            manager = AudioManager(cfg, state_store=store)
        relay = audio_process.StateRelay(dict(seed))
        ro.attach_shadows(host, {audio_process.MANAGER_PATH: manager,
                                 audio_process.STATE_PATH: relay}, audio_process.POLICIES)
        host.state_relay = relay
        host.relay_persisted = dict(seed)
        # The window itself: the helper's first publications arrive before the
        # capture writes anything.  With one shared seed they equal the baseline,
        # so nothing may reach the store (a mismatched seed wrote {} here).
        end = time.monotonic() + 0.6
        while time.monotonic() < end:
            audio_process.persist_relay_state(host, store)
            time.sleep(0.02)
        assert store.sets == []
        manager.start(timeout_s=4.0)               # the fake writes {'last_source': 'fake kick'}

        def done() -> bool:
            audio_process.persist_relay_state(host, store)
            return store.data.get('audio') == {'last_source': 'fake kick'}

        assert _until(done)
        assert [v for _, v in store.sets] == [{'last_source': 'fake kick'}]
    finally:
        host.close()


def test_start_audio_process_seeds_helper_relay_and_baseline_identically(monkeypatch) -> None:
    """The invariant behind the persist tests: one seed, three uses."""
    captured = {}

    class _FakeHost:
        ready = (None, 4242)

    def fake_spawn(factory_path, factory_name, args=None, **kw):
        captured['helper_seed'] = args['state']
        return _FakeHost()

    monkeypatch.setattr(audio_process.RemoteHost, 'spawn', staticmethod(fake_spawn))
    monkeypatch.setattr(audio_process, 'attach_shadows', lambda *a, **k: None)
    store = _Store({'audio': {'viable': ['x'], 'last_source': 'mic'}})
    host = audio_process.start_audio_process(object(), Config(), store)
    assert captured['helper_seed'] == {'audio': {'viable': ['x'], 'last_source': 'mic'}}
    assert host.state_relay.values == captured['helper_seed']
    assert host.relay_persisted == captured['helper_seed']
    audio_process.persist_relay_state(host, store)          # nothing changed yet
    assert store.sets == []
