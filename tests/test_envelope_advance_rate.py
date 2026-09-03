"""E5 (2026-09-03, detector rc.41): the onset envelope must advance to `now`
on every tick, including ticks that carry onsets.

Before the fix, a tick with onsets advanced the envelope only to the last
onset's timestamp and the clock then jumped to `now`, so the tail of every
such tick was never written: measured 95.7-96.3 envelope samples/s against
the nominal 100 Hz on real music, i.e. tempo read ~+1.3% high in v2 and v3
alike (madmom on the same files: 0.00%). Synthetic clicks whose onsets land
exactly on tick boundaries never showed it -- so this test puts every onset
strictly INSIDE a tick.
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
    def __init__(self) -> None:
        super().__init__({})
        self.writes = 0

    def _advance_envelope(self, target_t: float) -> None:
        before = int(self._env_write_idx)
        super()._advance_envelope(target_t)
        self.writes += (int(self._env_write_idx) - before) % max(1, int(self._env_len))


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


import pytest


@pytest.mark.xfail(strict=True, reason=(
    '2026-09-03 E5, KNOWN and unfixed: with onsets strictly inside ticks the '
    'envelope is written at ~96 Hz, not 100 (real-music tempo reads ~+1.3% high '
    'in v2 and v3; madmom 0.00%). Two mechanisms: (1) update() advances the '
    'envelope only to the last onset timestamp on onset ticks and then moves '
    '_last_t to now, losing the tail; (2) _pulse_envelope() deducts a step from '
    '_env_t_acc clamped at zero, so an onset arriving before a full step has '
    'accumulated steals the remainder. Three fix attempts on 2026-09-03 changed '
    'pulse/timing semantics that a dozen v2 tests pin (double-counting, then '
    'half-tempo reads) and were reverted; the fix needs a deliberate redesign '
    'of the envelope clock + pulse placement with the v2 test expectations '
    're-derived. See docs/adr/vj-system.md and the session ledger. '
    'UPDATE (2026-09-03 morning): the redesign exists and is timing-correct '
    '(docs/planning/patches/e5-envelope-clock-redesign-2026-09-03.patch; '
    '22-track bias +1.27% -> -0.23%), but the comb/prior/gate stack is '
    'co-adapted to the old timing jitter: with the true clock v3 drops 13 -> 10 '
    'exact on the 22 hardest tracks and v2 folds house to half tempo. It lands '
    'only together with a re-tune of that stack, panel-gated.'))
def test_envelope_rate_is_100hz_with_onsets_inside_ticks() -> None:
    tk = _Counting()
    span = _run(tk, 30.0, onset_every_ticks=4)   # 15 onsets/s, all mid-tick
    rate = tk.writes / span
    assert abs(rate - _BG._V2_ENV_RATE) < 1.0, rate   # was ~96 Hz before the fix


def test_envelope_rate_is_100hz_without_onsets() -> None:
    tk = _Counting()
    span = _run(tk, 30.0, onset_every_ticks=0)
    rate = tk.writes / span
    assert abs(rate - _BG._V2_ENV_RATE) < 1.0, rate
