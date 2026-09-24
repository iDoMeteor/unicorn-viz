"""Run an object graph in a helper process; drive it through local shadows.

Why this exists
---------------
Python has one GIL per process.  The DJ mixer's audio loop (10.7 ms per
block), its console and the visualizer used to share one, and a real-time
thread cannot win a lock it has to wait for -- nor survive a 125 ms gen-2
garbage-collection pause that stops every thread in the process.  A
separate process fixes both, but the mixer's engine and decks are rich,
stateful objects (a ``Deck`` alone has ~110 public methods) that the
console, controllers and auto-play call directly.

How it works
------------
* **Host (helper process).**  ``python -m unicornviz.remote_objects`` loads
  a *factory* by file path, builds the real object graph, and serves it:
  a command thread executes forwarded calls and attribute writes, a small
  pool runs the declared slow ones (track loads), and a publisher thread
  streams each registered object's plain state as deltas every
  ``period_s``.  It never imports moderngl, so it can run on a
  free-threaded interpreter (``python=`` below) once its imports allow.
* **Shadows (main process).**  The main process keeps its own instances of
  the same classes and swaps them to generated *shadow* subclasses.
  Declared read-only methods (``snapshot()``, waveform views, ...) run
  locally on state synced from the host; every other public method, every
  property setter and every attribute write is forwarded.  Callers keep
  the exact objects and API they had.
* **References and arrays.**  Registered objects and their bound methods
  cross the pipe as paths (``deck.loop_toggle`` arrives as the host's real
  bound method).  Arrays of ``SHM_MIN_BYTES`` or more published by the
  host travel through ``multiprocessing.shared_memory``: the main process
  maps the same pages instead of receiving a copy.

Thread-safety: the client may be used from any number of main-process
threads.  Shadows are updated by the client's receiver thread through
``__dict__`` (the same "another thread writes, readers see it next frame"
model the objects already had with their audio thread).

Usage::

    client = RemoteHost.spawn('/path/to/factory.py', 'build', args)
    attach_shadows(client, {'engine': engine, 'deck_a': engine.deck_a},
                   policies)
    engine.start(device)          # runs in the helper process
"""
from __future__ import annotations

import importlib.util
import inspect
import io
import itertools
import logging
import os
import pickle
import secrets
import subprocess
import sys
import sysconfig
import threading
import time
import types
import weakref
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from multiprocessing import shared_memory
from multiprocessing.connection import Client, Connection, Listener
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

#: Arrays at least this large travel through shared memory, not the pipe.
SHM_MIN_BYTES = 1 << 20
_KEY_ENV = 'UNICORNVIZ_REMOTE_KEY'
_SIMPLE = (int, float, bool, str, bytes, type(None), complex)
_CONTAINERS = (list, tuple, dict, set, frozenset)
_MISSING = object()
_DERIVED = '_rc_d_'          # shadow __dict__ prefix for host-derived values


@dataclass
class _StreamChunk:
    """New ``(seq, item)`` entries of a stream attribute (see Policy.streams)."""

    items: list


class RemoteError(RuntimeError):
    """A forwarded call failed in the helper process (message carries its repr)."""


class HostGone(RemoteError):
    """The helper process exited or its pipe closed."""


@dataclass
class Policy:
    """How a class is split between host and shadow.

    ``local`` names public methods/properties that only *read* state and run
    on the shadow; ``wait`` names forwarded methods whose return value
    callers use (the call blocks for the host's answer); ``slow`` names
    forwarded methods the host runs off its command thread (loads);
    ``skip`` names instance attributes never published (DSP objects,
    locks, render-only buffers); ``derive`` names zero-argument methods or
    properties that depend on host-only resources (an open file, the audio
    stream): the host evaluates them every few ticks and the shadow returns
    the latest value without a round trip; ``hot_derive`` the same, every
    tick (a per-frame snapshot).  ``values`` names attributes holding
    picklable value objects (a frozen profile dataclass), republished when
    they compare unequal.  ``streams`` names append-only deques of
    ``(seq, item)`` with increasing ``seq``: only new items cross, and the
    shadow's deque is extended rather than replaced (an event log).
    """

    local: frozenset[str] = frozenset()
    wait: frozenset[str] = frozenset()
    slow: frozenset[str] = frozenset()
    skip: frozenset[str] = frozenset()
    derive: frozenset[str] = frozenset()
    hot_derive: frozenset[str] = frozenset()
    #: Derived values that are costly to compute (device enumeration,
    #: percentile summaries) and change rarely: evaluated about once a second.
    cold_derive: frozenset[str] = frozenset()
    values: frozenset[str] = frozenset()
    streams: frozenset[str] = frozenset()
    #: Publish scalars and object references only -- no arrays, no
    #: containers (DSP objects whose buffers are nobody else's business).
    plain_only: bool = False

    def classified(self) -> frozenset[str]:
        """Every public name this policy says something about."""
        return (self.local | self.wait | self.slow | self.derive | self.hot_derive
                | self.cold_derive)


# ---------------------------------------------------------------------------
# registry + pickling with references
# ---------------------------------------------------------------------------

class Registry:
    """Bidirectional ``path <-> object`` map for the objects that cross."""

    def __init__(self) -> None:
        self._by_path: dict[str, Any] = {}
        self._by_id: dict[int, str] = {}

    def add(self, path: str, obj: Any) -> None:
        self._by_path[path] = obj
        self._by_id[id(obj)] = path

    def path_of(self, obj: Any) -> str | None:
        path = self._by_id.get(id(obj))
        if path is not None and self._by_path.get(path) is obj:
            return path
        return None

    def resolve(self, path: str) -> Any:
        return self._by_path[path]

    def items(self) -> list[tuple[str, Any]]:
        return list(self._by_path.items())


class _RefPickler(pickle.Pickler):
    def __init__(self, f: io.BytesIO, registry: Registry,
                 share: Callable[[np.ndarray], tuple] | None) -> None:
        super().__init__(f, protocol=pickle.HIGHEST_PROTOCOL)
        self._registry = registry
        self._share = share

    def persistent_id(self, obj: Any) -> Any:
        t = type(obj)
        if t in _SIMPLE or t in _CONTAINERS:
            return None
        if t is np.ndarray:
            if self._share is not None and obj.nbytes >= SHM_MIN_BYTES:
                return ('shm', *self._share(obj))
            return None
        if t is types.MethodType:
            owner = self._registry.path_of(obj.__self__)
            return ('meth', owner, obj.__func__.__name__) if owner else None
        path = self._registry.path_of(obj)
        return ('obj', path) if path is not None else None


_UNRESOLVED: set[str] = set()


class _Unresolved:
    """Stands in for an instance whose class could not be imported here."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __setstate__(self, state: Any) -> None:
        pass


class _RefUnpickler(pickle.Unpickler):
    def __init__(self, f: io.BytesIO, registry: Registry,
                 attach: Callable[..., np.ndarray] | None) -> None:
        super().__init__(f)
        self._registry = registry
        self._attach = attach

    def find_class(self, module: str, name: str) -> Any:
        try:
            return super().find_class(module, name)
        except (ImportError, AttributeError):
            # A class the other side has under a module name we cannot
            # import: keep the rest of the message instead of losing it all.
            key = f'{module}.{name}'
            if key not in _UNRESOLVED:
                _UNRESOLVED.add(key)
                log.warning('remote: cannot resolve %s here; its values arrive as '
                            'placeholders (load that module under the same name '
                            'on both sides)', key)
            return _Unresolved

    def persistent_load(self, pid: Any) -> Any:
        kind = pid[0]
        if kind == 'obj':
            return self._registry.resolve(pid[1])
        if kind == 'meth':
            return getattr(self._registry.resolve(pid[1]), pid[2])
        if kind == 'shm' and self._attach is not None:
            return self._attach(*pid[1:])
        raise pickle.UnpicklingError(f'unknown persistent id {pid!r}')


def _dumps(obj: Any, registry: Registry, share=None) -> bytes:
    buf = io.BytesIO()
    _RefPickler(buf, registry, share).dump(obj)
    return buf.getvalue()


def _loads(data: bytes, registry: Registry, attach=None) -> Any:
    return _RefUnpickler(io.BytesIO(data), registry, attach).load()


# ---------------------------------------------------------------------------
# shared-memory arrays
# ---------------------------------------------------------------------------

class _ShmExporter:
    """Host side: copies large published arrays into named shared memory.

    One segment per array identity; a replaced array's segment is unlinked
    after a grace period (the client maps it within milliseconds, and an
    existing mapping outlives the unlink on POSIX).
    """

    GRACE_S = 10.0

    def __init__(self) -> None:
        self._live: dict[int, tuple[Any, tuple, Any]] = {}   # id -> (arr, ref, shm)
        self._retired: list[tuple[float, Any]] = []
        self._lock = threading.Lock()
        self._touched: set[int] = set()     # shared since the last retire pass

    def share(self, arr: np.ndarray) -> tuple:
        with self._lock:
            self._touched.add(id(arr))
            return self._share(arr)

    def _share(self, arr: np.ndarray) -> tuple:
        hit = self._live.get(id(arr))
        if hit is not None and hit[0] is arr:
            return hit[1]
        src = np.ascontiguousarray(arr)
        shm = shared_memory.SharedMemory(create=True, size=max(1, src.nbytes),
                                         track=False)
        np.ndarray(src.shape, src.dtype, buffer=shm.buf)[...] = src
        ref = (shm.name, src.shape, src.dtype.str)
        self._live[id(arr)] = (arr, ref, shm)
        return ref

    def retire_unused(self, in_use: set[int]) -> None:
        with self._lock:
            self._retire_unused(in_use)

    def _retire_unused(self, in_use: set[int]) -> None:
        now = time.monotonic()
        in_use = in_use | self._touched
        self._touched = set()
        for key in [k for k in self._live if k not in in_use]:
            _, _, shm = self._live.pop(key)
            self._retired.append((now + self.GRACE_S, shm))
        keep = []
        for deadline, shm in self._retired:
            if deadline <= now:
                _close_shm(shm, unlink=True)
            else:
                keep.append((deadline, shm))
        self._retired = keep

    def close(self) -> None:
        for _, _, shm in self._live.values():
            _close_shm(shm, unlink=True)
        for _, shm in self._retired:
            _close_shm(shm, unlink=True)
        self._live.clear()
        self._retired.clear()


def _close_shm(shm: Any, unlink: bool) -> None:
    try:
        shm.close()
    except Exception:          # still exported: the mapping dies with the process
        pass
    if unlink:
        try:
            shm.unlink()
        except Exception:
            pass


class _ShmImporter:
    """Client side: maps published segments as read-only numpy arrays.

    A mapping is kept alive exactly as long as some array still views it.
    """

    def __init__(self) -> None:
        self._cache: dict[str, weakref.ref] = {}

    def attach(self, name: str, shape: tuple, dtype: str) -> np.ndarray:
        ref = self._cache.get(name)
        arr = ref() if ref is not None else None
        if arr is not None:
            return arr
        shm = shared_memory.SharedMemory(name=name, track=False)
        arr = np.ndarray(tuple(shape), np.dtype(dtype), buffer=shm.buf)
        arr.flags.writeable = False
        # The finalizer holds the SharedMemory until the array (and every
        # view of it, which keeps it as .base) is gone, then unmaps it.
        weakref.finalize(arr, _close_shm, shm, False)
        self._cache[name] = weakref.ref(arr)
        return arr


# ---------------------------------------------------------------------------
# channel
# ---------------------------------------------------------------------------

class _Channel:
    """A connection with a send lock (many writer threads, one reader)."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self._lock = threading.Lock()

    def send(self, data: bytes) -> None:
        with self._lock:
            self.conn.send_bytes(data)

    def recv(self) -> bytes:
        return self.conn.recv_bytes()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# host (helper process)
# ---------------------------------------------------------------------------

class _Host:
    """Serves a built object graph over two channels (commands in, events out)."""

    def __init__(self, cmd: _Channel, evt: _Channel, roots: dict[str, Any],
                 policies: dict[type, Policy], period_s: float) -> None:
        self.cmd = cmd
        self.evt = evt
        self.registry = Registry()
        for path, obj in roots.items():
            self.registry.add(path, obj)
        self.policies = policies
        self.period_s = period_s
        self.exporter = _ShmExporter()
        self._last: dict[str, dict[str, Any]] = {p: {} for p in roots}
        self._slow = ThreadPoolExecutor(max_workers=2, thread_name_prefix='remote-slow')
        self._stop = threading.Event()
        self._evt_lock = threading.Lock()
        # Highest main-process write sequence applied so far; stamped on each
        # state message so the client can tell stale deltas from fresh ones.
        self._applied = 0
        self._publish_lock = threading.Lock()
        self._tick = 0
        self.on_exit: list[Callable[[], None]] = []
        self.registry.add('__host__', _HostControl(self))
        self.policies[_HostControl] = _HOST_CONTROL_POLICY
        self._last['__host__'] = {}

    def load_factory(self, factory_path: str, factory_name: str, args: dict,
                     namespace: str = '', module_name: str = '') -> list[str]:
        """Build another object graph into this helper; returns its paths.

        Paths are prefixed ``namespace/`` so graphs from different owners
        (core audio, the mixer) never collide.  ``module_name`` is the name
        the main process loaded the same factory module under: classes
        defined there then pickle to a name both sides can resolve.
        """
        mod_name = module_name or f'_remote_factory_{namespace or "root"}'
        mod = sys.modules.get(mod_name)
        if mod is None or os.path.abspath(getattr(mod, '__file__', '') or '') \
                != os.path.abspath(factory_path):
            spec = importlib.util.spec_from_file_location(mod_name, factory_path)
            if spec is None or spec.loader is None:
                raise ImportError(factory_path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
        built = getattr(mod, factory_name)(args or {})
        prefix = f'{namespace}/' if namespace else ''
        paths = []
        with self._publish_lock:
            self.policies.update(built.get('policies', {}))
            for path, obj in built['roots'].items():
                full = prefix + path
                self.registry.add(full, obj)
                self._last[full] = {}
                paths.append(full)
        if 'period_s' in built:
            self.period_s = min(self.period_s, float(built['period_s']))
        on_exit = built.get('on_exit')
        if callable(on_exit):
            self.on_exit.append(on_exit)
        return sorted(paths)

    def _policy(self, obj: Any) -> Policy:
        for cls in type(obj).__mro__:
            pol = self.policies.get(cls)
            if pol is not None:
                return pol
        return Policy()

    def emit(self, msg: tuple) -> None:
        data = _dumps(msg, self.registry, self.exporter.share)
        with self._evt_lock:
            self.evt.send(data)

    # -- commands --------------------------------------------------------------

    def _run(self, req: int, path: str, op: str, name: str, args: tuple,
             kwargs: dict) -> None:
        try:
            target = self.registry.resolve(path)
            if op == 'call':
                result = getattr(target, name)(*args, **kwargs)
            elif op == 'set':
                setattr(target, name, args[0])
                result = None
            else:
                raise RemoteError(f'unknown op {op!r}')
            if req:
                # State first, then the answer: a caller that reads the object
                # right after a waited call (load, then bpm) sees the result.
                # Only that object, and no derived values: some are costly
                # (device lists), and the publisher sends them on its own.
                self.publish_now(paths=[path], derived=False)
                self.emit(('reply', req, True, result))
        except Exception as exc:
            if req:
                try:
                    self.emit(('reply', req, False, f'{type(exc).__name__}: {exc}'))
                except Exception:
                    pass
            else:
                log.warning('remote: %s.%s failed: %s', path, name, exc)

    def serve_commands(self) -> None:
        while not self._stop.is_set():
            try:
                data = self.cmd.recv()
            except (EOFError, OSError):
                break                           # parent gone: shut down
            try:
                msg = _loads(data, self.registry)
            except Exception as exc:
                log.warning('remote: undecodable command: %s', exc)
                continue
            if msg[0] == 'shutdown':
                break
            _, req, path, op, name, args, kwargs, seq = msg
            target = self.registry._by_path.get(path)
            if op == 'call' and target is not None and name in self._policy(target).slow:
                self._slow.submit(self._run, req, path, op, name, args, kwargs)
            else:
                self._run(req, path, op, name, args, kwargs)
            if seq:
                self._applied = seq
        self._stop.set()

    # -- state publication -----------------------------------------------------

    def _delta(self, path: str, obj: Any, slow_tick: bool, in_use: set[int],
               cold_tick: bool = False, derived: bool = True) -> dict:
        last = self._last.setdefault(path, {})
        policy = self._policy(obj)
        skip = policy.skip | policy.streams | policy.values
        plain_only = policy.plain_only
        out: dict[str, Any] = {}
        try:
            items = list(vars(obj).items())
        except RuntimeError:                # resized mid-copy: next tick
            return out
        for key, val in items:
            if key in skip or key.startswith('_rc_'):
                continue
            t = type(val)
            if t in _SIMPLE:
                prev = last.get(key, _MISSING)
                if prev is _MISSING or type(prev) is not t or prev != val:
                    out[key] = val
                    last[key] = val
            elif plain_only and (t is np.ndarray or t in _CONTAINERS):
                continue
            elif t is np.ndarray:
                if val.nbytes >= SHM_MIN_BYTES:
                    in_use.add(id(val))
                if last.get(key, _MISSING) is not val:
                    out[key] = val
                    last[key] = val
            elif t in _CONTAINERS:
                if not slow_tick and key in last:
                    continue
                try:
                    blob = _dumps(val, self.registry, self.exporter.share)
                except Exception:
                    continue
                if last.get(key) != blob:
                    out[key] = val
                    last[key] = blob
            elif self.registry.path_of(val) is not None:
                if last.get(key, _MISSING) is not val:
                    out[key] = val
                    last[key] = val
        for name in policy.streams:
            try:
                entries = list(getattr(obj, name))
            except Exception:
                continue
            mark = name + '#'
            sent = last.get(mark, -1)
            fresh = [e for e in entries if e[0] > sent]
            if fresh:
                out[name] = _StreamChunk(fresh)
                last[mark] = fresh[-1][0]
        names: frozenset[str] = frozenset()
        if derived:
            names = policy.hot_derive
            if slow_tick:
                names = names | policy.derive
            if cold_tick:
                names = names | policy.cold_derive
        for name in names:
            try:
                val = getattr(obj, name)
                if callable(val):
                    val = val()
            except Exception:
                continue
            key = _DERIVED + name
            try:
                same = last.get(key, _MISSING) == val
            except Exception:           # e.g. arrays inside: treat as changed
                same = False
            if not same:
                out[key] = val
                last[key] = val
        if slow_tick:
            state = vars(obj)
            for name in policy.values:
                val = state.get(name, _MISSING)
                if val is _MISSING:
                    continue
                try:
                    same = last.get(name, _MISSING) == val
                except Exception:
                    same = False
                if not same:
                    out[name] = val
                    last[name] = val
        return out

    def publish_now(self, slow_tick: bool = True, paths: list[str] | None = None,
                    derived: bool = True, cold_tick: bool = False) -> None:
        """Collect and send one state delta for every registered object (or
        just ``paths``; ``derived=False`` skips derived values)."""
        with self._publish_lock:
            applied = self._applied        # read before the state it vouches for
            in_use: set[int] = set()
            deltas = {}
            items = (self.registry.items() if paths is None else
                     [(p, self.registry._by_path[p]) for p in paths
                      if p in self.registry._by_path])
            for path, obj in items:
                try:
                    d = self._delta(path, obj, slow_tick, in_use, cold_tick, derived)
                except Exception as exc:        # pragma: no cover - defensive
                    log.warning('remote: publishing %s failed: %s', path, exc)
                    continue
                if d:
                    deltas[path] = d
            if deltas:
                self.emit(('state', deltas, applied))
            if slow_tick and paths is None:
                self.exporter.retire_unused(in_use)

    def publish_forever(self) -> None:
        while not self._stop.wait(self.period_s):
            self._tick += 1
            try:
                self.publish_now(self._tick % 5 == 0, cold_tick=self._tick % 100 == 0)
            except (OSError, EOFError):
                self._stop.set()
                break
            except Exception as exc:
                log.warning('remote: state send failed: %s', exc)

    def close(self) -> None:
        self._stop.set()
        self._slow.shutdown(wait=False, cancel_futures=True)
        self.exporter.close()


class _HostControl:
    """The helper's own control surface, served at path ``__host__``."""

    def __init__(self, host: _Host) -> None:
        self._host = host

    def load_factory(self, factory_path: str, factory_name: str, args: dict,
                     namespace: str = '', module_name: str = '') -> list[str]:
        return self._host.load_factory(factory_path, factory_name, args, namespace,
                                       module_name)

    def resync(self, paths: list[str]) -> None:
        """Forget what was sent for ``paths``: the reply to this (waited) call
        is preceded by their full state.  Called when the client attaches
        shadows, since anything published before that had nowhere to land."""
        host = self._host
        with host._publish_lock:
            for path in paths:
                host._last[path] = {}


_HOST_CONTROL_POLICY = Policy(wait=frozenset({'load_factory', 'resync'}),
                              slow=frozenset({'load_factory'}),
                              skip=frozenset({'_host'}))


class _EventLogHandler(logging.Handler):
    """Forwards the host's log records to the main process's log."""

    def __init__(self, host: _Host) -> None:
        super().__init__(logging.INFO)
        self._host = host

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._host.emit(('log', record.levelno, record.name, record.getMessage()))
        except Exception:
            pass


def _gil_report() -> str:
    """Empty on a normal build; on a free-threaded one, whether the GIL is off."""
    if not sysconfig.get_config_var('Py_GIL_DISABLED'):
        return ''
    enabled = getattr(sys, '_is_gil_enabled', lambda: True)()
    return 'free-threaded, GIL ENABLED (an unready extension turned it on)' if enabled \
        else 'free-threaded, GIL disabled'


def _host_main(argv: list[str]) -> int:
    address, factory_path, factory_name = argv[:3]
    key = bytes.fromhex(os.environ.pop(_KEY_ENV, ''))
    family = 'AF_PIPE' if sys.platform == 'win32' else 'AF_UNIX'
    cmd = _Channel(Client(address, family=family, authkey=key))
    evt = _Channel(Client(address, family=family, authkey=key))
    # Trusted peer, owner-approved nosec (2026-09-24): this pipe only accepts
    # the process that spawned us -- multiprocessing.connection's HMAC
    # challenge on a fresh random 32-byte key handed over in our environment
    # (popped above) -- the same trust model multiprocessing itself pickles on.
    init = pickle.loads(cmd.recv())  # nosec B301
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s [%(name)s] %(message)s')
    host = _Host(cmd, evt, {}, {}, 0.01)
    logging.getLogger().addHandler(_EventLogHandler(host))
    paths = host.load_factory(factory_path, factory_name, init.get('args') or {},
                              init.get('namespace', ''), init.get('module_name', ''))
    gil = _gil_report()
    if gil:
        log.info('remote host interpreter: %s', gil)
    host.emit(('ready', paths, os.getpid(), gil))
    pub = threading.Thread(target=host.publish_forever, name='remote-publish', daemon=True)
    pub.start()
    try:
        host.serve_commands()
    finally:
        for on_exit in reversed(host.on_exit):
            try:
                on_exit()
            except Exception as exc:
                log.warning('remote host shutdown hook failed: %s', exc)
        host.close()
    return 0


# ---------------------------------------------------------------------------
# client (main process)
# ---------------------------------------------------------------------------

@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    ok: bool = False
    value: Any = None


class RemoteHost:
    """Main-process handle on one helper process.

    Lifecycle: :meth:`spawn` -> :func:`attach_shadows` -> use the shadows ->
    :meth:`close`.  If the helper dies, :attr:`alive` turns False, pending
    calls raise :class:`HostGone` and later forwarded calls are dropped
    (logged once) rather than raising into UI code.
    """

    def __init__(self, proc: subprocess.Popen, cmd: _Channel, evt: _Channel) -> None:
        self.proc = proc
        self.cmd = cmd
        self.evt = evt
        self.registry = Registry()
        self.importer = _ShmImporter()
        self.alive = True
        self.ready: tuple = ()
        self._ids = itertools.count(1)
        self._pending: dict[int, _Pending] = {}
        self._pending_lock = threading.Lock()
        # (path, attr) -> sequence of our latest write to it, pending until a
        # state message stamped with that sequence or later arrives.
        self._shield: dict[tuple[str, str], int] = {}
        self._write_seq = itertools.count(1)
        self._warned_dead = False
        self._ready = threading.Event()
        self._closing = False
        self.on_state: Callable[[dict], None] | None = None
        # Called (on the receiver thread) if the helper dies unasked; one per
        # owner sharing this helper (core audio, the mixer).
        self._exit_handlers: list[Callable[[], None]] = []
        self._rx = threading.Thread(target=self._receive, name='remote-rx', daemon=True)

    @classmethod
    def spawn(cls, factory_path: str, factory_name: str, args: dict | None = None,
              python: str | None = None, timeout_s: float = 20.0,
              namespace: str = '', module_name: str = '') -> RemoteHost:
        """Start a helper process running ``factory_path:factory_name(args)``.

        ``python`` selects the interpreter (default: this one) -- the hook
        for running the host free-threaded.  Blocks until the host reports
        ready or ``timeout_s`` passes (then raises and kills it).
        """
        key = secrets.token_bytes(32)
        listener = Listener(family='AF_PIPE' if sys.platform == 'win32' else 'AF_UNIX',
                            authkey=key)
        env = dict(os.environ)
        env[_KEY_ENV] = key.hex()
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env['PYTHONPATH'] = root + os.pathsep + env.get('PYTHONPATH', '')
        exe = python or sys.executable
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [exe, '-m', 'unicornviz.remote_objects', str(listener.address),
             os.path.abspath(factory_path), factory_name],
            env=env, stdin=subprocess.DEVNULL)
        conns: list[Connection] = []
        accept_err: list[BaseException] = []

        def _accept() -> None:
            try:
                conns.append(listener.accept())
                conns.append(listener.accept())
            except BaseException as exc:        # noqa: BLE001 - reported below
                accept_err.append(exc)

        acceptor = threading.Thread(target=_accept, daemon=True)
        acceptor.start()
        acceptor.join(timeout_s)
        if len(conns) < 2:
            proc.kill()
            listener.close()
            raise HostGone(f'helper did not connect ({accept_err or "timeout"})')
        listener.close()
        host = cls(proc, _Channel(conns[0]), _Channel(conns[1]))
        host.cmd.send(pickle.dumps({'args': args or {}, 'namespace': namespace,
                                    'module_name': module_name}))
        host._rx.start()
        if not host._ready.wait(timeout_s):
            host.close(kill=True)
            raise HostGone('helper did not report ready')
        return host

    # -- receiving -------------------------------------------------------------

    def _receive(self) -> None:
        while True:
            try:
                data = self.evt.recv()
            except (EOFError, OSError):
                break
            try:
                msg = _loads(data, self.registry, self.importer.attach)
            except Exception as exc:
                log.warning('remote: undecodable event: %s', exc)
                continue
            kind = msg[0]
            if kind == 'state':
                self._apply_state(msg[1], msg[2])
            elif kind == 'reply':
                with self._pending_lock:
                    pend = self._pending.pop(msg[1], None)
                if pend is not None:
                    pend.ok, pend.value = msg[2], msg[3]
                    pend.event.set()
            elif kind == 'log':
                logging.getLogger(f'remote.{msg[2]}').log(msg[1], '%s', msg[3])
            elif kind == 'ready':
                self.ready = msg[1:]
                self._ready.set()
        self.alive = False
        with self._pending_lock:
            pending, self._pending = self._pending, {}
        for pend in pending.values():
            pend.ok, pend.value = False, 'helper process exited'
            pend.event.set()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        if self._closing:
            log.info('remote: helper process stopped (code %s)', self.proc.returncode)
        else:
            log.error('remote: helper process exited unexpectedly (code %s)',
                      self.proc.returncode)
            for cb in list(self._exit_handlers):
                try:
                    cb()
                except Exception as exc:
                    log.warning('remote: exit handler failed: %s', exc)

    def _apply_state(self, deltas: dict, applied: int) -> None:
        shield = self._shield
        for path, delta in deltas.items():
            try:
                obj = self.registry.resolve(path)
            except KeyError:
                continue
            for key in [k for k, v in delta.items() if type(v) is _StreamChunk]:
                chunk = delta.pop(key)
                target = obj.__dict__.get(key)
                if target is not None:
                    target.extend(chunk.items)
            if shield:
                # A value published before the host applied our latest write
                # to that key is older than what we already show: drop it.
                for key in list(delta):
                    seq = shield.get((path, key))
                    if seq is not None:
                        if applied < seq:
                            del delta[key]
                        else:
                            shield.pop((path, key), None)
            obj.__dict__.update(delta)
        cb = self.on_state
        if cb is not None:
            cb(deltas)

    # -- sending ---------------------------------------------------------------

    def _send(self, msg: tuple) -> None:
        if not self.alive:
            if not self._warned_dead:
                self._warned_dead = True
                log.error('remote: helper process is gone; dropping %s', msg[4:5])
            return
        try:
            self.cmd.send(_dumps(msg, self.registry))
        except (OSError, EOFError):
            self.alive = False

    def call(self, path: str, name: str, args: tuple, kwargs: dict,
             wait: bool = False, timeout_s: float = 5.0) -> Any:
        """Forward ``path.name(*args, **kwargs)``; block for the result if ``wait``."""
        if not wait:
            self._send(('cmd', 0, path, 'call', name, args, kwargs, 0))
            return None
        req = next(self._ids)
        pend = _Pending()
        with self._pending_lock:
            self._pending[req] = pend
        self._send(('cmd', req, path, 'call', name, args, kwargs, 0))
        if not self.alive:
            with self._pending_lock:
                self._pending.pop(req, None)
            raise HostGone('helper process is gone')
        if not pend.event.wait(timeout_s):
            with self._pending_lock:
                self._pending.pop(req, None)
            raise RemoteError(f'{path}.{name}() timed out after {timeout_s:.1f}s')
        if not pend.ok:
            if not self.alive:
                raise HostGone(str(pend.value))
            raise RemoteError(str(pend.value))
        return pend.value

    def add_exit_handler(self, fn: Callable[[], None]) -> None:
        """Run ``fn`` (receiver thread) if the helper dies without being asked."""
        self._exit_handlers.append(fn)

    def load_factory(self, factory_path: str, factory_name: str, args: dict | None = None,
                     namespace: str = '', module_name: str = '') -> list[str]:
        """Build another object graph inside this running helper (see
        :meth:`_Host.load_factory`); returns the new objects' paths."""
        return self.call('__host__', 'load_factory',
                         (os.path.abspath(factory_path), factory_name, args or {},
                          namespace, module_name),
                         {}, wait=True, timeout_s=SLOW_TIMEOUT_S)

    def set(self, path: str, name: str, value: Any) -> None:
        """Forward ``path.name = value``; until the host has applied it, older
        published values of that key are ignored (no flick-back mid-drag)."""
        seq = next(self._write_seq)
        self._shield[(path, name)] = seq
        self._send(('cmd', 0, path, 'set', name, (value,), {}, seq))

    def close(self, kill: bool = False) -> None:
        """Ask the helper to exit (it also exits when this process dies)."""
        self._closing = True
        if self.alive and not kill:
            try:
                self.cmd.send(pickle.dumps(('shutdown',)))
            except Exception:
                pass
        self.cmd.close()
        try:
            self.proc.wait(timeout=0 if kill else 3)
        except subprocess.TimeoutExpired:
            kill = True
        if kill and self.proc.poll() is None:
            self.proc.kill()
        self.alive = False


# ---------------------------------------------------------------------------
# shadows
# ---------------------------------------------------------------------------

_LOCAL = threading.local()
_SHADOW_CLASSES: dict[tuple[type, int], type] = {}


def _in_local() -> bool:
    return getattr(_LOCAL, 'depth', 0) > 0


def _local_method(fn: Callable) -> Callable:
    def run_local(self, *args, **kwargs):
        _LOCAL.depth = getattr(_LOCAL, 'depth', 0) + 1
        try:
            return fn(self, *args, **kwargs)
        finally:
            _LOCAL.depth -= 1
    run_local.__name__ = getattr(fn, '__name__', 'local')
    run_local.__doc__ = getattr(fn, '__doc__', None)
    return run_local


#: Waited calls normally answer in well under a millisecond; declared slow
#: ones (decode + analysis of a track) get minutes.
FAST_TIMEOUT_S = 5.0
SLOW_TIMEOUT_S = 300.0


def _forwarder(name: str, wait: bool, base: Callable, slow: bool = False) -> Callable:
    timeout = SLOW_TIMEOUT_S if slow else FAST_TIMEOUT_S

    def forward(self, *args, **kwargs):
        d = self.__dict__
        host = d.get('_rc_host')
        if host is None or _in_local():
            return base(self, *args, **kwargs)
        return host.call(d['_rc_path'], name, args, kwargs, wait=wait,
                         timeout_s=timeout)
    forward.__name__ = name
    forward.__doc__ = getattr(base, '__doc__', None)
    return forward


def _forward_setter(name: str, base_fset: Callable) -> Callable:
    def fset(self, value):
        d = self.__dict__
        host = d.get('_rc_host')
        if host is None or _in_local():
            base_fset(self, value)
            return
        host.set(d['_rc_path'], name, value)
    return fset


def _derived(name: str, raw: Any) -> Any:
    """The host's latest published value; the local base until one arrives."""
    key = _DERIVED + name
    if isinstance(raw, property):
        def fget(self):
            d = self.__dict__
            return d[key] if key in d else raw.fget(self)
        return property(fget, raw.fset, raw.fdel, raw.__doc__)

    def method(self):
        d = self.__dict__
        return d[key] if key in d else raw(self)
    method.__name__ = name
    return method


def _shadow_setattr(self, name: str, value: Any) -> None:
    d = self.__dict__
    host = d.get('_rc_host')
    if (host is not None and not _in_local() and not name.startswith('_rc_')
            and not isinstance(inspect.getattr_static(type(self), name, None), property)):
        host.set(d['_rc_path'], name, value)
    object.__setattr__(self, name, value)


def shadow_class(cls: type, policy: Policy) -> type:
    """The shadow subclass of ``cls`` under ``policy`` (cached)."""
    key = (cls, id(policy))
    hit = _SHADOW_CLASSES.get(key)
    if hit is not None:
        return hit
    ns: dict[str, Any] = {'__setattr__': _shadow_setattr, '_rc_policy': policy}
    for name in dir(cls):
        if name.startswith('_'):
            continue
        raw = inspect.getattr_static(cls, name)
        if name in policy.derive or name in policy.hot_derive or name in policy.cold_derive:
            ns[name] = _derived(name, raw)
            continue
        if isinstance(raw, property):
            fset = raw.fset
            if fset is not None:
                fset = _forward_setter(name, fset)
            fget = _local_method(raw.fget) if raw.fget is not None else None
            ns[name] = property(fget, fset, raw.fdel, raw.__doc__)
            continue
        if isinstance(raw, (staticmethod, classmethod)) or not callable(raw):
            continue
        if name in policy.local:
            ns[name] = _local_method(raw)
        else:
            ns[name] = _forwarder(name, name in policy.wait, raw, name in policy.slow)
    shadow = type(f'Shadow{cls.__name__}', (cls,), ns)
    _SHADOW_CLASSES[key] = shadow
    return shadow


def attach_shadows(host: RemoteHost, roots: dict[str, Any],
                   policies: dict[type, Policy]) -> None:
    """Turn main-process ``roots`` into shadows of the host's objects.

    Each object's class is swapped for its shadow subclass in place, so
    every existing reference to it keeps working.
    """
    for path, obj in roots.items():
        pol = next((policies[c] for c in type(obj).__mro__ if c in policies), Policy())
        obj.__class__ = shadow_class(type(obj), pol)
        obj.__dict__['_rc_host'] = host
        obj.__dict__['_rc_path'] = path
        host.registry.add(path, obj)
    # Whatever the helper published for these paths before they were
    # registered here was dropped: have it send their full state again.
    if host.alive and roots:
        host.call('__host__', 'resync', (list(roots),), {}, wait=True)


def detach_shadows(host: RemoteHost, prefix: str = '') -> None:
    """Undo :func:`attach_shadows` (objects become plain local instances),
    for every object or just those whose path starts with ``prefix``."""
    for path, obj in host.registry.items():
        if prefix and not path.startswith(prefix):
            continue
        if '_rc_host' not in obj.__dict__:
            continue
        base = type(obj).__mro__[1]
        obj.__dict__.pop('_rc_host', None)
        obj.__dict__.pop('_rc_path', None)
        obj.__class__ = base


if __name__ == '__main__':
    # Run from the properly named module, not __main__: classes defined here
    # (stream chunks, placeholders) must pickle to a name the client imports.
    from unicornviz import remote_objects as _self  # noqa: PLW0406 - see above
    sys.exit(_self._host_main(sys.argv[1:]))
