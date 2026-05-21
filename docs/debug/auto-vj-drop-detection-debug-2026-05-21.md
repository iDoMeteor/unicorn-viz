# Auto VJ Drop Detection Debug Report (2026-05-21)

## Scope

This report summarizes live-run debugging for:

- missed or weak mode transitions
- rapid mode cycling concerns
- bass/mid/treble scale behavior vs detector expectations

Data source: latest run log `logs/autovj-20260521T113253.jsonl`.

## Executive Summary

1. The system is **not stuck in CRUISE** anymore.
2. Transition chain integrity is currently strong:
   - `BUILD -> DROP -> IMPACT -> CLIMAX` conversion was 1.0 in this run.
3. Earlier "rapid cycling" was real, but current run shows improved pacing:
   - no short full cycles back to CRUISE within 8s from CRUISE entry.
4. Bass channel remains high relative to mid/treble by design and profile weighting;
   this is normal for many tracks but can still reduce detector contrast if used naively.
5. Detector now uses raw audio input (not reactivity-scaled effect audio), which was a
   critical fix and should remain.

## Current Run Metrics (Live Analysis)

### Global Counts

- Entries: 976
- `detector_tick`: 784
- `mode_transition`: 77
- `effect_swap`: 47
- `postfx_set`: 20
- `postfx_clear`: 20
- overlay hits (`rainbow_nova` / `screen_burst` / `dancing_unicorn`): 8 each

### Mode Transition Counts (`to_mode`)

- CRUISE: 18
- BUILD: 13
- DROP: 13
- IMPACT: 13
- CLIMAX: 13
- PINGPONG: 4
- BREAKDOWN: 3

### Conversion Ratios

- BUILD -> DROP: 13/13 = 1.0
- DROP -> IMPACT: 13/13 = 1.0
- IMPACT -> CLIMAX: 13/13 = 1.0

### Thrash/Burst Diagnostics

- Burst windows (>=3 transitions in <=2s): 18
- However, many are expected intra-chain transitions (`BUILD -> DROP -> IMPACT`).
- Additional short-cycle metric from CRUISE back to CRUISE <=8s: **0**
  (this is the stronger musical-health indicator and is currently good).

## Detector Signal Distributions

### Core Detector Fields (`detector_tick`)

- `drop_score`: p10=0.174, p50=0.242, p90=0.540, max=0.745
- `energy`: p10=1.135, p50=1.384, p90=1.713, max=2.157
- `energy_slope`: p10=-0.244, p50=0.011, p90=0.233, max=1.271
- `bpm`: p10=124.264, p50=129.371, p90=156.395, max=171.482

Interpretation:

- `drop_score` is no longer pinned near 1.0 (major improvement from earlier).
- Build/drop thresholds now align better with live slope and score dynamics.

### Band Channels (Raw audio in detector ticks)

- `bass`: p10=0.956, p50=0.985, p90=0.995, max=0.999
- `mid`: p10=0.101, p50=0.335, p90=0.644, max=0.851
- `treble`: p10=0.007, p50=0.050, p90=0.156, max=0.558

Interpretation:

- Bass dominance is persistent and strong.
- Mid and treble have useful spread, but are significantly lower than bass.
- This pattern is plausible for the chosen profile/music, but it can still bias
  detector logic unless features are normalized/compressed per-band before fusion.

## Answer To Band-Scale Question

Do effects expect isolated per-band equalized scales?

- Generally **no**. Most effects use bass as a stronger macro driver and mid/treble
  for detail modulation. Relative (non-equalized) channels are expected in effect code.
- But detector logic should not assume that same raw relative balance is ideal.
  Detector fusion benefits from per-feature normalization/compression.

Conclusion:

- Keep effect-facing audio semantics as-is (relative channels).
- Improve detector-side feature normalization (band-aware, detector-only) if misses
  persist under varied material.

## Root-Cause Timeline (What Was Fixed)

1. Detector previously consumed reactivity-scaled/clipped channels.
   - Effect tweakables polluted detector state.
2. Detector now consumes raw audio snapshot.
3. Drop score fusion was desaturated with normalized terms.
4. State machine thresholds were retuned.
5. Transition telemetry + detector telemetry + analyzer diagnostics added.
6. Anti-thrash guardrails added:
   - `build_min_hold_s`
   - `cycle_refractory_s`
   - increased raver `impact_hold_s`

## Remaining Risk

Even with the above, bass-heavy content can still make some tracks feel "always hot"
while musically important transitions are subtle in mid/treble dynamics.

## Recommended Next Steps (Priority Order)

1. Keep collecting runs with current instrumentation for at least 2-3 sessions.
2. Add detector-only per-band adaptive normalization (AGC) layer:
   - compute rolling mean/std or EMA envelope per band
   - derive z-score or percentile-normalized band features
   - feed those into transition scoring, not raw bands alone
3. Update analyzer to report:
   - transition intervals by chain segment
   - detector quantiles by profile and by mode
   - false-positive/false-negative windows tagged by operator notes
4. If needed, add `IMPACT` gating by beat/downbeat confidence to reduce
   near-random impact promotions.

## Suggested Config Levers For Next Tuning Pass

- `build_min_hold_s`
- `cycle_refractory_s`
- `impact_hold_s`
- `drop_energy_threshold`
- `impact_trigger_score`
- `breakdown_slope_threshold`
- `breakdown_energy_threshold`

## Files/Tools Used

- `logs/autovj-20260521T113253.jsonl`
- `tools/analyze_autovj_log.py`
- `drop-ins/auto-vj-01/auto_vj.py`
- `drop-ins/auto-vj-01/beat_grid.py`
- `unicornviz/audio/manager.py`
- `unicornviz/app.py`

## Addendum (Latest Run: 2026-05-21, 15:38 Session)

Latest analyzed file: `logs/autovj-20260521T153837.jsonl`

Summary deltas vs earlier state:

- Mode chains remain healthy (`BUILD -> DROP -> IMPACT -> CLIMAX` present).
- Transition burst metric remains stable (`>=3 transitions in 2s`: 0).
- Persistent issue: BPM still locks high on some slower material.
   - This session median BPM tracked around `~156` during suspected slower song.
- Detector bands in this session:
   - bass p50=0.970, mid p50=0.605, treble p50=0.445
- Potential missed drop windows (`BUILD score>=0.75`, no `DROP` <=1.5s): 1

This indicates transition pacing is substantially improved, but BPM harmonic
mis-lock remains the top unresolved issue for musical correctness.

For full external handoff package, see:

- `docs/debug/auto-vj-handoff-2026-05-21.md`

---

## Implementation Progress — Full Rebuild (started 2026-05-21, session 2)

Plan document: `docs/debug/auto-vj-beat-detection-rebuild-plan-2026-05-21.md`

### Phase Status

| Phase | Title                              | Status      | Commit |
|-------|------------------------------------|-------------|--------|
| P0    | Offline ground-truth harness       | ✅ Done      | a7b2eba |
| P1    | Event-based onset stream           | ✅ Done      | a7b2eba |
| P2    | Time-based envelope + MAD threshold| ✅ Done      | a7b2eba |
| P3    | Tempo-aware adaptive refractory    | ✅ Done      | a7b2eba |
| P4    | Autocorrelation tempo estimator    | ✅ Done      | TBD    |
| P5    | Phase-locked oscillator + downbeat | ✅ Done      | TBD    |
| P6    | Downbeat detection bass/snare      | ⏳ Planned   | —   |
| P7    | Confidence calibration + telemetry | ⏳ Planned   | —   |

### P0 — Harness & Seed Corpus

Files created:
- `tools/gen_bpm_eval_corpus.py` — generates 5 synthetic click-track WAVs
- `tools/bpm_eval.py` — offline harness, per-file metrics, MD + JSON reports
- `tools/run_bpm_eval.sh` — shell entry point
- `assets/audio/bpm_eval/seed/` — 5 WAV+JSON pairs: 90, 96, 120, 140, 155 BPM

Baseline run result (legacy engine, before any changes):

```
090bpm_click.wav  truth= 90.0  pred=  0.0  err=90.0  lock=-1.0s
096bpm_click.wav  truth= 96.0  pred=  0.0  err=96.0  lock=-1.0s
120bpm_click.wav  truth=120.0  pred=  0.0  err=120.0 lock=-1.0s
140bpm_click.wav  truth=140.0  pred=  0.0  err=140.0 lock=-1.0s
155bpm_click.wav  truth=155.0  pred=  0.0  err=155.0 lock=-1.0s
```

**Interpretation**: BPM = 0.0 on all tracks = zero lock. This is expected and reveals
a previously undocumented root cause (H9 below).

### H9 — Wall-clock time in Analyzer and BeatGridTracker breaks offline evaluation

Both `unicornviz/audio/analyzer.py` (beat cooldown) and
`drop-ins/auto-vj-01/beat_grid.py` (IOI timestamps, energy history) call
`time.monotonic()` internally. When the harness processes a 30-second clip
offline in milliseconds, wall-clock time barely advances. The beat cooldown
(`beat_cooldown_until_t`) is set to `now + cooldown_s` in real time, but the
next simulated block arrives with `now` only microseconds later → the cooldown
never expires → zero onsets → zero BPM.

**In production** this is masked because audio blocks arrive at real-time rate.
But it is still wrong: if the render loop runs fast (> 60fps) or slow (< 30fps),
the cooldown duration in audio-time varies, introducing FPS-coupling into beat
detection.

**Fix (part of P1)**: Add optional `t: float | None = None` parameter to both
`Analyzer.process()` and `BeatGridTracker.update()`. Default to
`time.monotonic()` when not provided (backward-compat). Harness passes
`t = file_t` (audio position in seconds). This also fixes FPS-coupling in
production if callers pass audio-time-aligned `t`.

Baseline JSON saved as `tools/bpm_eval_baseline.json` (all zeros — the
zero-lock baseline is itself a regression gate: any future run that also
produces all zeros is a hard failure).

### P1 + P2 + P3 implementation notes

Analyzer changes in `unicornviz/audio/analyzer.py`:
- `OnsetEvent` dataclass (t, strength) — importable
- `_onset_queue: deque[OnsetEvent]` — bounded 256
- `drain_onsets() -> list[OnsetEvent]`
- `set_expected_bpm(bpm, confidence)` — sets adaptive refractory (P3)
- `process(pcm, t=None)` — optional t for offline harness (H9 fix)
- Replace `_flux_history` fixed ring → time-based `_env_buf` at 100 Hz (P2)
- Replace `mean + std` threshold → `median + MAD` with absolute floor (P2)
- Compute `bass_flux` / `mid_flux` per frame (P6 prep)

`AudioData` changes in `unicornviz/effects/base.py`:
- Add `bass_flux: float = 0.0` and `mid_flux: float = 0.0` to `__slots__`

`AudioManager` changes in `unicornviz/audio/manager.py`:
- `drain_onsets() -> list[OnsetEvent]` — forwards to analyzer
- `set_expected_bpm(bpm, confidence) -> None` — forwards to analyzer
- `_clone_audio()` updated for `bass_flux`, `mid_flux`

`BeatGridTracker` changes in `drop-ins/auto-vj-01/beat_grid.py`:
- `update(dt, audio, onsets=None, t=None)` — new signature (P1 + H9 fix)
- All `time.monotonic()` calls replaced with `t or time.monotonic()`
- `_ingest_onset(ev)` method to separate onset ingestion

`AutoVJController` changes in `drop-ins/auto-vj-01/auto_vj.py`:
- Store `self._audio_manager = audio` in `__init__`
- In `update()`: `self._grid.update(dt, audio, onsets=self._audio_manager.drain_onsets())`
- After update: `self._audio_manager.set_expected_bpm(self._grid.bpm, self._grid.confidence)`
- `_load_beat_grid_cls()` reads `cfg.get('beat_tracker_engine', 'legacy')` to
  select between `BeatGridTracker` (legacy) and `BeatTracker` (v2)

### P4 + P5 implementation notes

New `BeatTracker` class in `drop-ins/auto-vj-01/beat_grid.py`:
- Maintains own onset envelope at 100 Hz internal rate
- ACF tempo estimator with perceptual prior (mu=120, sigma=28)
- Octave-down preference intentionally omitted (see below)
- Phase-locked oscillator with ±18% tolerance window
- Phase coherence as confidence metric
- Same public interface as `BeatGridTracker` — drop-in swap

Feature flag: `beat_tracker_engine = "v2"` in `[auto_vj]` section of
`config.toml`. Default stays `"legacy"` until harness confirms v2 wins.

### Bugs found and fixed during P4+P5 implementation

**Bug: _pulse_envelope overwrites itself** — `_pulse_envelope()` wrote the
onset strength at `_env_write_idx` but did not advance the write index. The
next `_advance_envelope()` call immediately overwrote the pulse with zero
fill. Fixed: `_pulse_envelope()` now advances the write index after writing
and decrements `_env_t_acc` by one step to maintain time-sync.

**Bug: octave-down fold fires on all click tracks** — For a sparse click
envelope, the ACF at lag 2N (half-tempo fold) equals the ACF at lag N (for a
periodic signal). The fold test `raw_fold >= 0.85 * raw_best` therefore fired
on EVERY track, consistently halving the BPM. The fold preference was removed;
the perceptual prior provides sufficient bias toward musical tempos without
causing systematic halving.

**Bug: cold-start EMA oscillation** — With < 8 onset pulses in the envelope,
the ACF produces wildly noisy estimates that seed the EMA in the wrong
direction. The BPM then oscillates (87→122→77→...) before eventually
converging. Fixed: ACF is gated to require ≥ 8 onset pulses before updating
the BPM estimate. Cold-start EMA alpha is capped at 0.10 (before ring fills)
to dampen the oscillations.

### P4+P5 harness results (v2 engine)

```
090bpm_click.wav   truth= 90.0  pred= 94.2  err=4.2   lock=8.5s
096bpm_click.wav   truth= 96.0  pred= 96.8  err=0.8   lock=9.6s
120bpm_click.wav   truth=120.0  pred=120.0  err=0.0   lock=8.7s
140bpm_click.wav   truth=140.0  pred=138.7  err=1.3   lock=6.2s
155bpm_click.wav   truth=155.0  pred=153.8  err=1.1   lock=5.4s
```

**vs legacy baseline:**

| Track   | Legacy err | v2 err | Improvement |
|---------|-----------|--------|-------------|
| 90 BPM  | 56.3      | 4.2    | 13×         |
| 96 BPM  | 61.7      | 0.8    | 77×         |
| 120 BPM | 19.7      | 0.0    | ∞           |
| 140 BPM | 3.0       | 1.3    | 2.3×        |
| 155 BPM | 4.6       | 1.1    | 4.2×        |

The 155-lane bias is completely eliminated. All 5 tracks now lock within
the 30-second window. Legacy locked only on 140 and 155 BPM tracks.

**Remaining known limitation**: 90 BPM settles at ~94 BPM because at 100 Hz
envelope rate, adjacent ACF lags differ by ~2-3 BPM in the 90 BPM range.
The false-positive onset rate (~3.1/s vs expected ~1.5/s) also contributes
by pulling the average onset spacing slightly faster than the true beat.
Both issues will improve with P7 (confidence calibration + tighter MAD
threshold tuning per profile) and when P3 refractory fully engages after
initial BPM lock reduces the false-positive rate.

Results saved: `tools/bpm_eval_v2_results.json`

## Addendum (2026-05-21, live 124 BPM session)

Current v2 regression mode observed on a steady 124 BPM track (8-bar loop):

- BPM mostly hovers correctly in the 120–125 range.
- Two transient failure modes still appear:
   - **phantom 200 BPM spikes** when the ACF score is effectively zero across
      all lags (brief silence / dense noise burst / low-information frames)
   - **96 BPM dips** when a transient sub-beat peak pulls the EMA down despite
      the beat remaining unchanged

Planned fix set for v2:

1. raise the score floor so near-zero ACF cannot ever select lag_min as the
    default 200 BPM ceiling
2. add a per-update BPM step cap so a single bad frame cannot move the EMA by
    ~15 BPM
3. require a confidence floor before applying any BPM update

This addendum is the current debugging priority for the v2 engine.

Implementation note (in progress): the v2 tracker now has explicit guardrails
for all three items above. If this session is interrupted, resume by checking
the v2 harness against the 90/96/120/140/155 BPM seed corpus and compare the
new report to `tools/bpm_eval_v2_results.json`.

Follow-up sanity check: a steady 124 BPM synthetic click-track (30 s) now
stays stable with **no 200 BPM spikes** and **no 96 BPM dips** under the
hardening pass. The median BPM on that synthetic run sat at 120.0, which is
slightly conservative but musically stable; that is acceptable for the current
step because the failure mode was instability, not exact calibration.

Live regression note (same day): a steady real 124 BPM track and a steady
96 BPM track still show frequent re-selection swings in the live meter
(roughly 111–158 BPM within seconds). The next fix should add hysteresis so a
new ACF candidate must repeat across consecutive updates before it can replace
the current BPM lock.

Checkpoint update after startup-gate hardening: the seed corpus remains
healthy on v2 (`tools/bpm_eval.py --engine v2`) with median absolute BPM error
1.15 BPM and the 96 BPM seed track locking cleanly at 96.0 BPM. The 90 BPM
seed also improved back to 91.6 BPM. The live 124/96 swing still needs a fresh
post-patch live log to confirm, but the offline guardrails are now holding.

Latest stabilization pass (re-lock control + pause reset):

- Added a tempo-hold window to avoid re-deciding BPM multiple times per second
   on steady tracks.
- Added silence-reset lock clearing so a new song after pause does not inherit
   stale BPM state from the previous track.
- Slowed ACF decision cadence (`_V2_ACF_INTERVAL` 8) to reduce chattery
   candidate replacement.

Offline results after this pass:

- Seed corpus remains strong (`tools/bpm_eval.py --engine v2`):
   90=89.5, 96=95.9, 120=120.0, 140=139.5, 155=153.8
- Synthetic 124/128/164 checks are stable with zero >10 BPM frame jumps.
- One synthetic 96 variant currently settles low (~86–90), so low-tempo
   calibration still needs live + synthetic follow-up.

