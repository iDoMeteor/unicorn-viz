# Director Placement Scoring — "is he landing each scene?"

Owner: Auto VJ strategist seat
Status: active (spec; implementation by the training seat)
Last updated: 2026-09-03

## Why

The scorecard's director rating is an activity-rate proxy (mode transitions +
drop fires + impact fires per hour, 5/5 at ≥ 260). It saturates on every
v3 bucket and cannot tell "more fires" from "better fires". The corpus rows
already carry everything needed to judge each director call against the
music it was made on: per-frame `energy`, `bass`, `energy_slope`,
`drop_score`, `impact_novelty`, `beat_phase`, `bars_since_track_start`,
`bars_since_phase_entry`, `vj_mode`, and per-event rows for
`mode_transition` (`new_mode`, `reason`), `drop_fire` (`peak_tier`) and
`impact_fire` (`impact_score`). Owner (2026-09-03): "we have every bit of
data we need to post-analyze if he's landing each scene correctly every
single time, it's time to get hardcore with him."

A first cut on one house list (bucket 039 v3 vs 027 v2) already
discriminates — see "Prototype findings" below.

## Terms

- **Event**: a director call logged as a corpus row with `event_type` in
  {`mode_transition`, `drop_fire`, `impact_fire`}.
- **Pre / post window**: mean of a per-frame signal over the N bars before /
  after the event, on the same track, bars derived from the row's `bpm`
  (`bar_s = 240 / bpm`). N = 2 for drops/impacts, 4 for mode transitions.
- **Lift**: an event's post/pre ratio of a signal.
- **Chance baseline**: the same metric computed on random *on-beat* frames
  (`min(beat_phase, 1 − beat_phase) < 0.15`) of the same track, at least 8
  bars into the track, five samples per real event, fixed seed. Every
  placement rate is reported next to its chance rate; the quantity that
  matters is **lift over chance** (rate − chance), not the raw rate.
- **Phrase boundary**: distance in bars from `bars_since_track_start` to
  the nearest multiple of 8 is ≤ 1 (also reported at 16). The director's own
  boundary notion is `_phrase_bias()`'s `boundary_bonus` on
  `_bars_since_phase_entry % phrase_boundary_bar_unit`; both are reported.
- **Track-boundary suspect**: event with `bars_since_track_start < 4`
  (crossfade region in replays; intro in live sessions).

## Metrics (pre-registered)

Per bucket, per event type, each with its chance baseline and lift:

| Event | Metric | "Landed" definition |
| --- | --- | --- |
| `drop_fire` | energy lift | post/pre `energy` (2 bars) > 1.10 |
| `drop_fire` | bass lift | post/pre `bass` (2 bars) > 1.10 |
| `drop_fire` | phrase alignment | phrase boundary (8-bar, ±1) |
| `drop_fire` | beat alignment | on-beat (`beat_phase` within 0.15 of 0/1) |
| `drop_fire` | novelty | `impact_novelty` at fire ≥ its per-track 75th percentile |
| `impact_fire` | phrase alignment | phrase boundary (8-bar, ±1) |
| `impact_fire` | downbeat alignment | on-beat AND `bars_since_track_start` integer step (bar start) |
| `impact_fire` | energy lift | post/pre `energy` (2 bars) > 1.10 |
| `mode_transition` → `build` | trend consistency | post/pre `energy` (4 bars) > 1.05 |
| `mode_transition` → `breakdown` | trend consistency | post/pre `energy` (4 bars) < 0.95 |
| `mode_transition` → `climax` | peak consistency | post `energy` (2 bars) ≥ track's 80th percentile |
| any | phrase alignment | as above |
| any | track-boundary suspect | share of events in the first 4 bars |
| any | dwell sanity | `bars_since_phase_entry` at transition vs the role's expected min/max (`_PHRASE_ROLE_BARS`): share under-hold / in-window / over-hold |

Per-bucket aggregates: counts, rates, chance rates, lifts, and a
**placement rating** (proposal, to be calibrated on the batch before it
replaces the activity rating):

```
placement = mean over event types of clamp((rate − chance) / (1 − chance), 0, 1)
rating    = 5 if placement ≥ 0.40, 4 ≥ 0.25, 3 ≥ 0.12, 2 ≥ 0.04, else 1
```

The activity rating stays in the scorecard as "Director activity" so old
buckets remain comparable; the new one is "Director placement".

## Deliverables (training seat)

1. `drop-ins/training-kit-01/tools/director_placement.py` — library +
   CLI: `python director_placement.py <bucket-dir> [--json out] [--seed 7]`.
   Reads the bucket's sequence corpus (`sequence-replay-*.jsonl` or
   `sequence-corpus-*.jsonl`), writes a JSON with per-event verdicts and
   per-bucket aggregates, prints a markdown table. Pure numpy/stdlib. The
   prototype at the end of this document is the reference semantics; keep
   the definitions above exactly, so buckets scored today and later are
   comparable.
2. Packager integration: `package_training_set.py` calls it and writes a
   `## Director Placement` section (counts, rate vs chance, lift, and the
   placement rating) plus `director_placement.json` into the bucket;
   `## Ratings` gains `Director placement: n/5` next to the existing
   `Director quality` (renamed in the section to "Director activity"). LLM
   payload gains the aggregates (three-layer rule).
3. Tests: `tests/test_director_placement.py` on a synthetic corpus with
   known placements (fires exactly at energy steps and phrase boundaries
   must score 100% with chance ≈ the constructed rate; fires at random must
   score ≈ chance).
4. Batch analysis: run over every bucket from 2026-09-02/03 — bake-1 v2
   cells (house 027, trap 005, toughies 028, dnb 005, ambient-02 005,
   normie-trance 005, curveballs-03 023), bake-3 Cell C (033/009/032/009/
   009/009/027), bake-4 E/F, the 38 final-batch buckets (map in the
   ledger), and the live `assets/training/sets/favorites/004`. Deliver one
   table: bucket, engine, list, seed, per-event rates vs chance, placement
   rating; and a v2-vs-v3 summary per list.
5. ADR: `docs/adr/training-model.md` entry (scorecard metric formula
   change — required by CLAUDE.md), and a line in this doc's status.

Not in scope here: changing the director. This is the instrument; tuning
follows once the batch table exists.

## Prototype findings (house-01, 2026-09-03, seed 7)

| | v2 (027) | v3 (039) |
| --- | --- | --- |
| drop_fire energy lift > 1.10 | 27% vs chance 10% | 5% vs chance 11% |
| drop_fire bass lift > 1.10 | 30% vs chance 12% | 16% vs chance 14% |
| drop_fire phrase boundary (8, ±1) | 48% vs chance 35% | 43% vs chance 37% |
| build → energy rises (4 bars) | 37% | 39% |
| breakdown → energy falls (4 bars) | 42% | 42% |
| impact_fire phrase boundary / on-beat | 50% / 100% | 50% / 100% |

Reading: drops are beat-aligned always, phrase-aligned barely above chance,
and under v3 they stopped landing on energy rises at all on this list.
Build/breakdown calls match the following energy trend less than half the
time. Hypothesis to test on the batch: the profile-mix shift under v3
(dubstep applied on 36–44% of house rows in replays, a +1.2% replay-clock
bias artifact) changes the drop thresholds that gate fires.

## Prototype (reference semantics)

The scratchpad script `director_placement_proto.py` (copied into the
training seat's hand-off) implements the table above; its window, on-beat,
phrase and chance-baseline definitions are normative.
