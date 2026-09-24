"""The audio process: capture + analysis (and the DJ mixer's engine) off the GL process.

Why: the visualizer's process owns GL and stays on the GIL.  Everything
audio -- capture, the analyzer, and (when dj-mixer-01 is loaded) the mixer
engine -- runs in one helper process started through
:mod:`unicornviz.remote_objects`, where it competes only with its own few
threads and never with a frame, a Pillow raster or a gen-2 collection of
the main heap.  The helper never imports moderngl, so it can run on a
free-threaded interpreter (``[audio] process_python``).

How: the helper builds a real :class:`AudioManager`; the main process keeps
its own and turns it into a shadow.  Per frame, ``get_audio_data()`` runs
locally on the snapshot the helper publishes every 10 ms (reactivity and
the zero-frame probe stay main-side); onsets arrive as a stream the main
side drains with its own cursor; device operations (start, source
selection) run in the helper.  Capture persists its source state through a
:class:`StateRelay` that the main process copies into the real runtime
state store, so there is still exactly one writer of that file.

Other owners join the same helper: ``vj_api.audio_process_host()`` hands
out the :class:`RemoteHost`, and dj-mixer-01 loads its engine into it.

Usage (App.run does this)::

    host = start_audio_process(manager, cfg, runtime_state)   # raises -> in-process
    ...per frame: persist_relay_state(host, runtime_state)
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

from unicornviz.audio.manager import AudioManager
from unicornviz.remote_objects import Policy, RemoteHost, attach_shadows

log = logging.getLogger(__name__)

NAMESPACE = 'audio'
MANAGER_PATH = f'{NAMESPACE}/manager'
STATE_PATH = f'{NAMESPACE}/state'


class StateRelay:
    """The slice of the runtime state store the capture layer uses.

    Lives in the helper as the capture's ``state_store``; its ``values`` and
    ``version`` are published back, and the main process writes changed
    values into the real store (see :func:`persist_relay_state`).
    """

    def __init__(self, values: dict | None = None) -> None:
        self.values: dict[str, Any] = dict(values or {})
        self.version = 0

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.values = {**self.values, key: value}     # new dict: republished
        self.version += 1


_ZERO_PROBE = frozenset({
    '_zero_probe_last_publish', '_zero_frames', '_zero_gated', '_zero_anomalous',
    '_zero_repeat', '_zero_rms_peak', '_zero_gate_rms_peak', '_frames_read',
    '_zero_probe_next_report_t', '_zero_probe_first_anomaly_logged',
    '_zero_probe_reported_anomalies',
})

# local: runs on the shadow.  derive / hot_derive: helper-only facts, published.
# wait: forwarded, answer used.  slow: off the helper's command thread.
# fire: forwarded, answer unused (listed for the drift test).
# Reactivity is applied main-side only (get_audio_data scales the helper's
# frame), so setting it is local: auto-vj drifts it every frame, and a round
# trip per frame for a value the helper never reads was pure waste.
MANAGER_LOCAL = frozenset({
    'set_reactivity', 'reset_reactivity',
    'get_audio_data', 'get_audio_data_raw', 'get_reactivity', 'get_profile_name',
    'get_profile_key', 'get_audio_time', 'log_zero_frame_summary',
    'drain_onsets', 'list_profiles', 'get_profile_bpm_range',
    'get_profile_hud_label', 'get_profile',
})
MANAGER_DERIVE = frozenset({
    'get_source_label', 'sample_rate', 'get_source_index', 'get_raw_input_rms',
    'get_xrun_count',
})
# Device enumeration (sounddevice queries, PulseAudio sink descriptions):
# refreshed about once a second, not twenty times.
MANAGER_COLD = frozenset({'source_is_output_flags', 'list_sources',
                          'source_viable_flags'})
MANAGER_HOT = frozenset({'audio_snapshot'})
MANAGER_WAIT = frozenset({
    'start', 'stop', 'set_profile',
    'select_source', 'cycle_source', 'toggle_source_viable',
    'get_recent_pcm_window',
})
MANAGER_SLOW = frozenset({'start', 'stop', 'select_source', 'cycle_source',
                          'get_recent_pcm_window'})
MANAGER_FIRE = frozenset({'set_claimed_device_names', 'set_expected_bpm'})
MANAGER_SKIP = frozenset({
    '_capture', '_analyzer', '_front_buf', '_back_buf', '_snap_buf',
    '_analysis_lock', '_analysis_stop', '_analysis_thread', '_start_worker',
    '_last_data', '_last_data_raw', '_onset_cursor',
    '_reactivity',              # main-side state (see MANAGER_LOCAL)
}) | _ZERO_PROBE

MANAGER_POLICY = Policy(local=MANAGER_LOCAL, wait=MANAGER_WAIT, slow=MANAGER_SLOW,
                        skip=MANAGER_SKIP, derive=MANAGER_DERIVE,
                        cold_derive=MANAGER_COLD,
                        hot_derive=MANAGER_HOT, values=frozenset({'_profile'}),
                        streams=frozenset({'_onset_log'}))
RELAY_POLICY = Policy(local=frozenset({'get'}), wait=frozenset({'set'}))

#: Every public AudioManager name, classified (drift test).
MANAGER_CLASSIFIED = (MANAGER_LOCAL | MANAGER_DERIVE | MANAGER_HOT | MANAGER_WAIT
                      | MANAGER_FIRE | MANAGER_COLD)
POLICIES: dict[type, Policy] = {AudioManager: MANAGER_POLICY, StateRelay: RELAY_POLICY}


def build(args: dict) -> dict:
    """Helper-side factory: a real AudioManager over a state relay."""
    relay = StateRelay(args.get('state'))
    manager = AudioManager(args['cfg'], state_store=relay)

    def _on_exit() -> None:
        if getattr(manager, '_started', False):
            manager.stop()

    return {'roots': {'manager': manager, 'state': relay}, 'policies': POLICIES,
            'on_exit': _on_exit}


def start_audio_process(manager: AudioManager, cfg: Any, state_store: Any = None,
                        python: str | None = None) -> RemoteHost:
    """Start the audio helper and turn ``manager`` into its shadow.

    Raises on any failure; the caller then keeps ``manager`` in-process.
    ``cfg`` is the live (override-applied) config, sent as-is.
    """
    state = {}
    if state_store is not None:
        try:
            state = {'audio': state_store.get('audio', default={})}
        except Exception as exc:
            log.debug('audio process: no seed state: %s', exc)
    pickle.dumps(cfg)                       # fail here, not inside the helper
    host = RemoteHost.spawn(str(Path(__file__)), 'build', {'cfg': cfg, 'state': state},
                            python=python, namespace=NAMESPACE,
                            module_name=__name__)
    relay = StateRelay(state)
    attach_shadows(host, {MANAGER_PATH: manager, STATE_PATH: relay}, POLICIES)
    host.state_relay = relay
    host.relay_persisted = dict(state)      # what the store already holds
    gil = host.ready[2] if len(host.ready) > 2 else ''
    log.info('Audio process running (pid %s%s): capture and analysis are off '
             'the render process', host.ready[1], f', {gil}' if gil else '')
    return host


def persist_relay_state(host: RemoteHost, state_store: Any) -> None:
    """Copy capture state the helper changed into the real runtime store.

    Main thread, once per frame: compares by content (the relay's values
    reach this process on the helper's slow tick, so a counter could run
    ahead of them); cheap -- one small dict.
    """
    relay = getattr(host, 'state_relay', None)
    if relay is None or state_store is None:
        return
    values = relay.values
    if values == host.relay_persisted:
        return
    for key, value in values.items():
        if host.relay_persisted.get(key) == value:
            continue
        try:
            state_store.set(key, value)
        except Exception as exc:
            log.warning('audio process: could not persist %s: %s', key, exc)
    host.relay_persisted = dict(values)
