"""Audio-process test factory: a real AudioManager + Analyzer in the helper,
fed by a fake capture that synthesizes a 120 BPM kick in real time (no
audio device is ever opened).  Loaded by tests/test_audio_process.py."""
from __future__ import annotations

import threading
import time

import numpy as np

from unicornviz.audio import manager as manager_mod
from unicornviz.audio import process as audio_process

SR = 48_000
BLOCK = 1024


class FakeCapture:
    """The AudioCapture surface AudioManager uses, over a synthetic kick."""

    def __init__(self, *args, state_store=None, **kwargs) -> None:
        self.active = False
        self.closed_cleanly = True
        self.sample_rate = SR
        self.block_size = BLOCK
        self.xrun_count = 0
        self.fallback_ticks = 0
        self._state_store = state_store
        self._seq = 0
        self._block = np.zeros(BLOCK, dtype=np.float32)
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._claimed: set = set()

    def start(self) -> None:
        self.active = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if self._state_store is not None:
            self._state_store.set('audio', {'last_source': 'fake kick'})

    def _run(self) -> None:
        t = 0
        period = BLOCK / SR
        nxt = time.perf_counter()
        while not self._stop.is_set():
            idx = np.arange(t, t + BLOCK)
            phase = (idx % (SR // 2)) / SR                   # a kick every 0.5 s
            block = (0.8 * np.sin(2 * np.pi * 55 * phase) * np.exp(-phase * 30)
                     ).astype(np.float32)
            with self._cond:
                self._block = block
                self._seq += 1
                self._cond.notify_all()
            t += BLOCK
            nxt += period
            time.sleep(max(0.0, nxt - time.perf_counter()))

    def wait_for_new_block(self, timeout_s: float = 0.5) -> bool:
        with self._cond:
            return self._cond.wait(timeout_s)

    def get_block_pair_if_new(self, last_seq: int):
        with self._cond:
            if self._seq == last_seq:
                return None, None, last_seq
            return self._block.copy(), None, self._seq

    def signal_new_block(self) -> None:
        with self._cond:
            self._cond.notify_all()

    def maybe_fallback(self) -> None:
        self.fallback_ticks += 1

    def stop(self) -> None:
        self._stop.set()
        self.active = False

    def current_source_label(self) -> str:
        return 'fake kick'

    def set_claimed_device_names(self, names) -> None:
        self._claimed = set(names)

    def source_labels(self) -> list[str]:
        return ['fake kick']

    def source_is_output_flags(self) -> list[bool]:
        return [False]

    def current_source_index(self) -> int:
        return 0

    def source_viable_flags(self) -> list[bool]:
        return [True]

    def get_history(self, blocks: int) -> np.ndarray:
        return np.zeros(blocks * BLOCK, dtype=np.float32)


def build(args: dict) -> dict:
    manager_mod.AudioCapture = FakeCapture            # helper process only
    return audio_process.build(args)
