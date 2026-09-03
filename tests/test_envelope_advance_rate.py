"""E5 (2026-09-03, detector rc.41): the onset envelope must advance to `now`
on every tick, including ticks that carry onsets.

Before the fix, a tick with onsets advanced the envelope only to the last
onset's timestamp and the clock then jumped to `now`, so the tail of every
such tick was never written: measured 95.7-96.3 envelope samples/s against
the nominal 100 Hz on real music, i.e. tempo read ~+1.3% high in v2 and v3
alike (madmom on the same files: 0.00%). Synthetic clicks whose onsets land
exactly on tick boundaries never showed it -- so this test puts every onset
strictly INSIDE a tick.

Fixed by `docs/planning/patches/e5-envelope-clock-redesign-2026-09-03.patch`
(landed 2026-09-03, Program B step 3 batch 1): an absolute-index envelope
clock where `_advance_envelope_e5()` (the zero-fill path) and
`_pulse_envelope_e5()` (the onset-pulse path) both funnel through one shared
primitive, `_advance_env_to_index()`, so a slot gets written exactly once
regardless of which path reaches it first. This test's own write-counting
technique needed to move with that redesign: the original `_Counting`
subclass hooked only `_advance_envelope()`, which was a correct proxy for
total writes under the OLD design (pulses wrote through a separate,
uncounted path with its own bug) but became a systematic UNDER-count under
the NEW one -- an onset tick now writes its own slot directly via
`_pulse_envelope_e5()`'s call into `_advance_env_to_index()`, bypassing
`_advance_envelope()` entirely, so the old hook's delta was short by
roughly one slot per onset (observed ~80 Hz at 15 onsets/s, not the ~96 Hz
the pre-E5 bug produced -- a different, new number, not the same bug
persisting). Hooking `_advance_env_to_index()` directly -- the actual
single source of truth for "a slot was written", mirroring how the
onset-prototype bench's own `v3_odf_tracker.py` overrides this exact
primitive for its own instrumentation -- reads 99.97 Hz.

Gated behind `_V2_ENV_SOURCE='dense_flux'` (2026-09-03, same landing,
peer instruction after batch 1): the shipped default stays `'pulses'`,
bit-identical to rc.40 including this exact bias -- see
`test_envelope_rate_stays_biased_under_default_pulses_source` below and
`_advance_envelope_legacy`'s own docstring. These two tests construct the
tracker with `env_source='dense_flux'` explicitly to exercise the fixed
clock; they say nothing about the shipped default.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

_BEAT_GRID = Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01' / 'beat_grid.py'
_SPEC = importlib.util.spec_from_file_location('test_env_rate_beat_grid', _BEAT_GRID)
assert _SPEC is not None and _SPEC.loader is not None
_BG = importlib.util.module_from_spec(_SPEC)
sys.modules['test_env_rate_beat_grid'] = _BG
_SPEC.loader.exec_module(_BG)


class _Counting(_BG.BeatTracker):
    def __init__(self, env_source: str = 'dense_flux') -> None:
        super().__init__({'env_source': env_source})
        self.writes = 0

    def _advance_env_to_index(self, want: int) -> None:
        before = int(self._env_next_idx)
        super()._advance_env_to_index(want)
        self.writes += int(self._env_next_idx) - before


def _silent_audio() -> SimpleNamespace:
    return SimpleNamespace(bass=0.0, mid=0.0, treble=0.0, bass_flux=0.0, mid_flux=0.0, treble_flux=0.0,
                           spectral_flux=0.0, waveform=None, fft=None, beat=False, bpm=0.0, energy=0.0)


def _run(tracker: _Counting, seconds: float, onset_every_ticks: int) -> float:
    dt = 1.0 / 60.0
    t = 0.0
    n = int(seconds / dt)
    for i in range(n):
        t += dt
        onsets = []
        if onset_every_ticks and i % onset_every_ticks == 0:
            # strictly inside the tick, never on its boundary
            onsets = [SimpleNamespace(t=t - 0.4 * dt, strength=1.5, band_weight=0.8)]
        tracker.update(dt, _silent_audio(), onsets=onsets, t=t)
    return t


def test_envelope_rate_is_100hz_with_onsets_inside_ticks_dense_flux() -> None:
    tk = _Counting(env_source='dense_flux')
    span = _run(tk, 30.0, onset_every_ticks=4)   # 15 onsets/s, all mid-tick
    rate = tk.writes / span
    assert abs(rate - _BG._V2_ENV_RATE) < 1.0, rate   # was ~96 Hz before the fix


def test_envelope_rate_is_100hz_without_onsets_dense_flux() -> None:
    tk = _Counting(env_source='dense_flux')
    span = _run(tk, 30.0, onset_every_ticks=0)
    rate = tk.writes / span
    assert abs(rate - _BG._V2_ENV_RATE) < 1.0, rate


def test_envelope_rate_stays_biased_under_default_pulses_source() -> None:
    """The shipped default (`env_source` unset, i.e. `'pulses'`) must NOT
    pick up the E5 fix -- bit-identical to rc.40 including its own known
    +1.3% bias, until `'dense_flux'` becomes the default in a later batch.
    `_Counting` here can't hook `_advance_env_to_index()` (the legacy path
    never calls it) -- hooks `_advance_envelope`/`_pulse_envelope`
    directly instead, the old (correct, for this path) counting technique."""

    class _CountingLegacy(_BG.BeatTracker):
        """Hooks BOTH `_advance_envelope`/`_pulse_envelope` -- the legacy
        path has no single shared write primitive the way the E5 path's
        `_advance_env_to_index()` does; `_pulse_envelope_legacy` advances
        `_env_write_idx` on its own, uncounted if only `_advance_envelope`
        is hooked (the same class of undercount `test_envelope_advance_
        rate.py`'s own history already found once, on the E5 side)."""

        def __init__(self) -> None:
            super().__init__({})  # env_source defaults to 'pulses'
            self.writes = 0

        def _advance_envelope(self, target_t: float) -> None:
            before = int(self._env_write_idx)
            super()._advance_envelope(target_t)
            self.writes += (int(self._env_write_idx) - before) % max(1, int(self._env_len))

        def _pulse_envelope(self, strength: float, t: float = 0.0) -> None:
            before = int(self._env_write_idx)
            super()._pulse_envelope(strength, t)
            self.writes += (int(self._env_write_idx) - before) % max(1, int(self._env_len))

    tk = _CountingLegacy()
    assert tk._env_source == 'pulses'
    span = _run(tk, 30.0, onset_every_ticks=4)
    rate = tk.writes / span
    # Biased low, same direction and rough scale as the ADR's own real-music
    # reading (95.7-96.3 Hz) -- not asserting that exact figure, since this
    # is a synthetic 15 onsets/s stream, not real music; the point under
    # test is that the shipped default is NOT the fixed ~100 Hz clock.
    assert 90.0 < rate < 99.0, rate
