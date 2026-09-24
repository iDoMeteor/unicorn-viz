"""unicornviz.remote_objects: an object graph served from a helper process.

Spawns a real helper (``python -m unicornviz.remote_objects``) running the
toy graph in tests/fixtures/remote_toy.py and drives it through shadows,
the way dj-mixer-01's audio process is driven.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from tests.fixtures import remote_toy
from unicornviz import remote_objects as ro

_FACTORY = Path(remote_toy.__file__)


def _until(pred, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture
def pair():
    host = ro.RemoteHost.spawn(str(_FACTORY), 'build')
    a, b = remote_toy.Player(), remote_toy.Player()
    ro.attach_shadows(host, {'a': a, 'b': b}, {remote_toy.Player: remote_toy.POLICY})
    yield host, a, b
    host.close()


def test_runs_in_another_process(pair) -> None:
    host, a, _ = pair
    assert host.ready[0] == ['a', 'b']
    assert a.pid() != os.getpid()


def test_forwarded_calls_come_back_as_synced_state(pair) -> None:
    _, a, _ = pair
    assert a.play() is None                     # fire-and-forget
    assert _until(lambda: a.playing is True)
    assert a.add_cue(1.5) == 1                  # waited for the host's answer
    assert _until(lambda: a.cues == [1.5])


def test_attribute_and_property_writes_are_forwarded(pair) -> None:
    host, a, _ = pair
    a.gain = 0.5
    assert a.gain == 0.5                        # optimistic local value
    assert a.pid() and _until(lambda: host.call('a', 'describe', (), {}, wait=True)
                              .startswith('0.50'))
    a.volume = 20.0                             # property setter runs remotely
    assert _until(lambda: abs(a.gain - 0.2) < 1e-9)
    assert a.volume == pytest.approx(20.0)      # getter runs locally


def test_local_methods_read_shadow_state_without_a_round_trip(pair) -> None:
    _, a, _ = pair
    a.add_cue(2.0)
    assert _until(lambda: a.describe() == '1.00/1/4')


def test_objects_and_bound_methods_cross_as_references(pair) -> None:
    _, a, b = pair
    assert a.link(b) is True                    # arrives as the host's own b
    assert _until(lambda: a.partner is b)       # and comes back as our shadow
    assert a.run_later(b.play) is True          # a bound method of a shadow
    assert _until(lambda: b.playing is True)


def test_large_arrays_arrive_through_shared_memory(pair) -> None:
    _, a, _ = pair
    n = (ro.SHM_MIN_BYTES // 4) * 3
    assert a.load(n) == 'loaded'                # slow op, off the command thread
    assert _until(lambda: a.samples.size == n)
    assert float(a.samples[-1]) == n - 1
    assert not a.samples.flags.writeable        # a read-only mapping, not a copy


def test_slow_calls_do_not_block_fast_ones(pair) -> None:
    host, a, _ = pair
    host.call('a', 'load', (10,), {})           # 0.2 s, on the slow pool
    t0 = time.monotonic()
    assert a.add_cue(9.0) == 1
    assert time.monotonic() - t0 < 0.15


def test_errors_raise_remote_error(pair) -> None:
    host, a, _ = pair
    with pytest.raises(ro.RemoteError, match='kaboom'):
        host.call('a', 'boom', (), {}, wait=True)
    a.boom()                                    # fire-and-forget: logged only
    assert a.add_cue(1.0) == 1                  # and the host is still fine


def test_helper_death_is_reported_not_hung(pair) -> None:
    host, a, _ = pair
    a.die()
    assert _until(lambda: not host.alive)
    with pytest.raises(ro.HostGone):
        a.add_cue(1.0)
    a.play()                                    # dropped, logged once, no raise


def test_detach_restores_plain_local_objects(pair) -> None:
    host, a, _ = pair
    ro.detach_shadows(host)
    assert type(a) is remote_toy.Player
    a.play()
    assert a.playing is True                    # ran locally


def test_state_is_current_the_moment_a_waited_call_returns(pair) -> None:
    """The loader thread loads, then reads bpm straight away: no stale read."""
    _, a, _ = pair
    for n in (7, 11, 13):
        assert a.load(n) == 'loaded'
        assert a.samples.size == n               # no polling: already applied


def test_arrays_inside_containers_share_memory(pair) -> None:
    _, a, _ = pair
    n = ro.SHM_MIN_BYTES // 4 * 2
    assert a.stash(n) == 1
    assert _until(lambda: len(a.bank) == 1)
    arr = a.bank[0]
    assert arr.size == n and float(arr[0]) == 7.0
    assert not arr.flags.writeable              # mapped, not pickled inline
    time.sleep(0.3)                             # several slow ticks later...
    assert a.bank[0] is arr                     # ...still the same mapping


def test_derived_values_come_from_the_host_without_a_round_trip(pair) -> None:
    host, a, _ = pair
    assert _until(lambda: a.where() == host.ready[1])   # host pid, not ours
    assert a.where() != os.getpid()
