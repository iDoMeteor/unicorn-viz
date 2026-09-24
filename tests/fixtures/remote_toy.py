"""Toy object graph for tests/test_remote_objects.py (loaded by file path in
the helper process, and imported normally by the test for its shadows)."""
from __future__ import annotations

import os
import threading
import time

import numpy as np

from unicornviz.remote_objects import Policy


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

    def where(self) -> int:
        """Host-only fact (derived): which process this object lives in."""
        return os.getpid()

    def describe(self) -> str:
        """Read-only: runs on the shadow."""
        return f'{self.gain:.2f}/{len(self.cues)}/{self.samples.size}'


POLICY = Policy(local=frozenset({'describe'}),
                wait=frozenset({'add_cue', 'load', 'link', 'run_later', 'pid', 'stash'}),
                slow=frozenset({'load'}),
                skip=frozenset({'_lock'}),
                derive=frozenset({'where'}))


def build(args: dict) -> dict:
    a, b = Player(), Player()
    return {'roots': {'a': a, 'b': b}, 'policies': {Player: POLICY},
            'period_s': 0.005}
