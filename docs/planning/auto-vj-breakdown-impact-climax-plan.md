# Auto VJ Breakdown / Impact / Climax Plan + Report

Owner: Studio Documentation
Status: archive
Last updated: 2026-06-18


## Objective

Improve Auto VJ musical intelligence so it can reliably detect and react to:

- breakdowns (energy collapse / restraint)
- build-ups (rising tension)
- drop-to-impact release moments (the "explosion")
- short climax windows before recovery to cruise

while keeping behavior profile-aware (`chill`, `normie`, `raver`) and predictable
for live operation.

## Where We Were

Before this pass, the director state machine was:

- `CRUISE -> BUILD -> DROP -> CRUISE`

Detection signals available:

- BPM + confidence (`BeatGridTracker`)
- smoothed energy
- 2-second energy slope
- composite `drop_score`

Behavior gaps observed in live testing:

- weak/rare `BUILD` entry in some tracks
- `DROP` often felt soft and quickly fell back to `CRUISE`
- no explicit `BREAKDOWN` behavior
- no explicit `IMPACT` mode after drop release
- no explicit `CLIMAX` hold window

## What Is Implemented In This Pass

### New Director Modes

Added three explicit states:

- `BREAKDOWN`
- `IMPACT`
- `CLIMAX`

Current high-level flow now supports:

- `CRUISE -> BREAKDOWN -> BUILD -> DROP -> IMPACT -> CLIMAX -> CRUISE`
- plus existing ping-pong overlays and user/manual interruption handling

### Detection / Transition Logic

`CRUISE`:

- build-up onset from sustained positive slope
- breakdown onset from sustained low energy + negative slope

`BREAKDOWN`:

- exits to `BUILD` on recovery (slope + energy rebound)
- times out back to `CRUISE` when breakdown window expires

`BUILD`:

- schedules `DROP` when drop score threshold is crossed
- fallback schedule to `DROP` after max build duration

`DROP`:

- transitions to `IMPACT` on either:
  - sufficient drop score after a small minimum delay, or
  - hard maximum delay timeout

`IMPACT`:

- short high-intensity hold
- then automatically enters `CLIMAX`

`CLIMAX`:

- short high-intensity sustain
- then auto-recovers to `CRUISE`

### Action Layer Changes

`IMPACT` now hits harder immediately:

- pushes reactivity to profile max
- strong post-fx slot trigger from impact slots
- immediate random effect reinforcement swap (drop tags)
- stacked overlay hit attempts (`screen_burst`, `rainbow_nova`, `dancing_unicorn`)

`BREAKDOWN` now behaves conservatively:

- slower swap cadence
- tagged content preference for calmer texture
- post-fx de-emphasis (clears on entry)

`CLIMAX` now sustains pressure:

- faster swap cadence than cruise/build
- dedicated climax post-fx cadence + slot pool

### Profile-Tuned Intelligence Parameters

Added per-profile tuning keys:

- `breakdown_energy_threshold`
- `breakdown_slope_threshold`
- `breakdown_sustain_s`
- `breakdown_max_s`
- `breakdown_recover_energy`
- `impact_trigger_score`
- `impact_min_delay_s`
- `impact_max_delay_s`
- `impact_hold_s`
- `climax_hold_s`
- `postfx_impact_slots`
- `postfx_climax_slots`
- `postfx_climax_interval_s`
- `breakdown_effect_tags`
- `climax_effect_tags`

These are now in all three profile presets (`chill`, `normie`, `raver`) with
profile-appropriate defaults.

### Operator Visibility

Status pill now surfaces the new modes:

- `BREAKDOWN`, `IMPACT`, `CLIMAX`

This is critical for real-time trust during tuning.

## Detection Model Summary

Signals currently used:

- `energy` (EMA of bass+mid+treble)
- `energy_slope` (energy delta over ~2s)
- `drop_score` (energy amplitude + positive slope + treble contribution)
- beat/downbeat timing and BPM confidence

Current philosophy:

- use slope+energy for tension/release staging
- use drop_score + beat scheduling for release timing
- use profile thresholds to map musical style to visual intensity

## Tuning Strategy (Live Iteration)

### 1. Breakdown Stability

If false positives (too many breakdowns):

- lower sensitivity by moving `breakdown_slope_threshold` more negative
- lower `breakdown_energy_threshold`
- increase `breakdown_sustain_s`

If breakdowns are missed:

- raise `breakdown_slope_threshold` toward zero
- raise `breakdown_energy_threshold`
- reduce `breakdown_sustain_s`

### 2. Impact Punch

If impact still feels weak:

- lower `impact_trigger_score`
- shorten `impact_min_delay_s`
- increase `postfx_drop_duration_s`
- bias `postfx_impact_slots` toward stronger slots

If impact fires too often / too noisy:

- raise `impact_trigger_score`
- increase `impact_min_delay_s`
- reduce `impact_hold_s`

### 3. Climax Shape

If climax feels too short:

- increase `climax_hold_s`
- reduce `postfx_climax_interval_s`

If climax overstays:

- decrease `climax_hold_s`
- increase cooldowns for swap/postfx in profile

## Data Collection & Reporting Plan

Use existing Auto VJ JSONL decision logs (`logs/autovj-*.jsonl`) and session notes.

Track per show:

- count of each mode entry (`BREAKDOWN`, `BUILD`, `DROP`, `IMPACT`, `CLIMAX`)
- median dwell per mode
- `% DROP -> IMPACT` conversion rate
- `% IMPACT -> CLIMAX` conversion rate
- operator-rated quality for each impact/climax (subjective 1-5)
- false-trigger notes with track timestamps

Recommended quick KPI targets:

- `DROP -> IMPACT` conversion >= 80%
- `IMPACT` perceived punch >= 4/5 in `normie` and `raver`
- breakdown false positives < 1 per 10 minutes

## Near-Term Next Steps

1. Run at least 2 sessions per profile (`chill`, `normie`, `raver`) with logs on.
2. Compile per-profile false positives and weak-impact timestamps.
3. Tune only profile thresholds first (no code changes) to lock baseline.
4. If needed, add secondary release metrics (onset density delta, bass return ratio).
5. Optionally add a `RECOVERY` micro-state if transitions from `CLIMAX` to
   `CRUISE` feel abrupt in slower sets.

## Notes

- This plan intentionally prioritizes deterministic state transitions over
  opaque ML-style guessing so operators can trust behavior live.
- The architecture now supports richer musical semantics without changing the
  external control surface.
