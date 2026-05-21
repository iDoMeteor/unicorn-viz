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
