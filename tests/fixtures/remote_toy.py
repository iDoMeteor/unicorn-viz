"""Toy object graph for tests/test_remote_objects.py (loaded by file path in
the helper process, and imported normally by the test for its shadows)."""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from unicornviz.remote_objects import Policy


@dataclass(frozen=True)
class Mood:
    """A value object (like an AudioProfile)."""

    name: str
    energy: float


class Player:
    """A stand-in for a deck: state, a render-ish thread, mutators, readers."""

    def __init__(self) -> None:
        self.gain = 1.0
        self.playing = False
        self.position = 0.0
        self.cues: list[float] = []
        self.samples = np.zeros(4, dtype=np.float32)
        self.partner: Player | None = None
        self.bank: list = []                      # sampler-style list of arrays
        self.events: deque = deque(maxlen=64)     # (seq, item) event stream
        self.event_total = 0
        self.mood = Mood('calm', 0.1)
        self.ticks = 0
        self._lock = threading.Lock()

    @property
    def volume(self) -> float:
        return self.gain * 100.0

    @volume.setter
    def volume(self, value: float) -> None:
        self.gain = value / 100.0

    def play(self) -> None:
        self.playing = True

    def add_cue(self, t: float) -> int:
        self.cues.append(t)
        return len(self.cues)

    def load(self, n: int) -> str:
        time.sleep(0.2)                           # a slow, off-thread load
        self.samples = np.arange(n, dtype=np.float32)
        return 'loaded'

    def stash(self, n: int) -> int:
        self.bank = self.bank + [np.full(n, 7.0, dtype=np.float32)]
        return len(self.bank)

    def link(self, other: Player) -> bool:
        self.partner = other
        return other is not self

    def run_later(self, action) -> bool:
        action()
        return True

    def pid(self) -> int:
        return os.getpid()

    def boom(self) -> None:
        raise ValueError('kaboom')

    def die(self) -> None:
        os._exit(3)

    def emit_events(self, n: int) -> int:
        for _ in range(n):
            self.event_total += 1
            self.events.append((self.event_total, f'onset{self.event_total}'))
        return self.event_total

    def set_mood(self, name: str, energy: float) -> None:
        self.mood = Mood(name, energy)

    def snap(self) -> tuple:
        """Hot derived: a per-tick snapshot only the host can take."""
        self.ticks += 1
        return (self.ticks, os.getpid())

    def where(self) -> int:
        """Host-only fact (derived): which process this object lives in."""
        return os.getpid()

    def describe(self) -> str:
        """Read-only: runs on the shadow."""
        return f'{self.gain:.2f}/{len(self.cues)}/{self.samples.size}'


POLICY = Policy(local=frozenset({'describe'}),
                wait=frozenset({'add_cue', 'load', 'link', 'run_later', 'pid', 'stash',
                                'emit_events'}),
                slow=frozenset({'load'}),
                skip=frozenset({'_lock', 'ticks'}),
                derive=frozenset({'where'}),
                hot_derive=frozenset({'snap'}),
                values=frozenset({'mood'}),
                streams=frozenset({'events'}))


def build(args: dict) -> dict:
    a, b = Player(), Player()
    return {'roots': {'a': a, 'b': b}, 'policies': {Player: POLICY},
            'period_s': 0.005}


def build_more(args: dict) -> dict:
    """A second graph, loaded into an already-running helper."""
    extra = Player()
    extra.gain = float(args.get('gain', 0.7))
    return {'roots': {'extra': extra}, 'policies': {Player: POLICY}}
