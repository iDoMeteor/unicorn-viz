# Director Placement Scoring — "is he landing each scene?"

Owner: Auto VJ strategist seat
Status: instrument + tests landed (deliverables 1-5 complete, training-kit-01
0.41.0); tuning phase (E1-E5) not started
Last updated: 2026-09-03 (deliverables 1-5 landed by the training seat)

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

## Batch findings — the head start (2026-09-03, prototype semantics, seed 7)

Every 2026-09-02/03 bucket scored: the 38 final-batch runs (18 genre lists ×
2 seeds + favorites × 2), the 7 bake-1 v2 baseline cells, and the live
favorites/004 session. Pooled per genre family, rate / chance (lift):

| Family | drop energy lift | drop bass lift | drop phrase | build → rises | breakdown → falls | impact phrase | impact energy |
| --- | --- | --- | --- | --- | --- | --- | --- |
| house family (8 lists) | 15/9 (+6) | 21/10 (+11) | 37/39 (−2) | 39/23 (+16) | 37/20 (+17) | 35/38 (−3) | 8/10 (−3) |
| trance / techno | 19/11 (+8) | 16/8 (+8) | 36/36 (0) | 46/24 (+22) | 40/19 (+20) | 39/41 (−2) | 15/11 (+4) |
| dnb / dubstep | 20/10 (+10) | 26/12 (+14) | 28/39 (−10) | 40/23 (+17) | 38/23 (+15) | 40/37 (+3) | 17/14 (+3) |
| hip-hop / trap / rnb | 38/12 (+26) | 42/17 (+25) | 41/36 (+4) | 34/22 (+12) | 31/22 (+9) | 35/42 (−7) | 43/15 (+29) |
| ambient / downtempo | 13/11 (+2) | 24/10 (+14) | 38/43 (−5) | 37/18 (+20) | 33/17 (+16) | 29/41 (−12) | 6/11 (−5) |
| curveballs | 17/11 (+5) | 21/13 (+8) | 38/37 (+1) | 42/24 (+17) | 34/21 (+12) | 40/32 (+8) | 12/9 (+3) |
| favorites (replay) | 21/12 (+9) | 27/12 (+15) | 39/41 (−1) | 44/26 (+18) | 41/24 (+18) | 38/40 (−2) | 14/10 (+5) |
| favorites LIVE | 22/14 (+8) | 14/9 (+4) | 24/43 (−18) | 56/24 (+32) | 43/20 (+22) | 29/39 (−9) | 0/7 (−7) |
| v2 baselines (7 lists) | 24/9 (+15) | 26/10 (+16) | 37/37 (0) | 42/23 (+19) | 36/22 (+15) | 38/46 (−8) | 12/9 (+3) |

Per-list table, all 53 buckets: ledger `logs/replay/EXPERIMENT-2026-08-31.md`
("DIRECTOR PLACEMENT — FULL BATCH ANALYSIS") and
`director_batch_analysis.json` in the strategist scratchpad.

### What the batch says

1. **Phrase alignment is the universal gap, and it is structural.** Drop
   fires sit at or *below* chance on phrase boundaries in every family
   (house −2, dnb/dubstep −10, live favorites −18); impact fires too (−3 to
   −12), and impacts are supposed to be *the* phrase-boundary event.
   `_fire_drop()` gates on `drop_score` (threshold / confirm) and
   `downbeat_confidence` only — there is no bar or phrase quantization
   anywhere in the drop or impact path; the `_phrase_bias()` machinery only
   touches mode transitions. So the director places fires on the *beat*
   (100% on-beat everywhere) but never on the *bar of the phrase*.
2. **Drop fires barely land on energy.** House-family drops beat chance by
   +6 (energy) / +11 (bass); v2's baseline cells did better (+15 / +16), and
   on house-01 specifically v2 landed 27% vs v3 5–10%. The one family where
   drops genuinely land is hip-hop / trap / rnb (+26 / +25) — music with
   real drops. Minor-tier drops land slightly *more* often than major-tier
   (22% vs 16%), so the tier label is not tracking musical impact. By active
   profile at fire: drum_and_bass 27%, ambient/trance 35% (few events),
   dubstep 19% (n = 732 — the profile most often active under v3 in
   replays), deep_house 14%. The house regression under v3 is consistent
   with the replay profile-mix shift (dubstep on 36–44% of house rows via
   the +1.2% replay-clock bias) putting dubstep's drop thresholds on house
   material; the live favorites session (no clock bias) shows +8, not a
   regression.
3. **Build / breakdown calls are the director's best skill, at ~40%.**
   Build transitions are followed by a rising 4-bar window 34–46% of the
   time against ~23% chance (+12 to +22); breakdowns by a falling window
   31–41% vs ~20% (+9 to +20). Live favorites builds hit 56% (+32), the best
   number in the set. Real signal, but more than half of all builds and
   breakdowns are followed by the opposite or by nothing.
4. **Impacts land nowhere in particular.** Phrase alignment at or below
   chance, energy lift at chance except hip-hop/trap (+29). Counts are small
   (1–19 per bucket).
5. **The half-time genres under-fire drops entirely.** Tracks with no drop
   fire at all: ambient 5–6 of 14, downtempo 2–6 of 14, hip-hop 4 of 18,
   trap 3–6 of 21, dubstep 2–4 of 14, vs 0–2 on house-family lists. Same
   genres as the detector's notational residue: the drop score under those
   profiles rarely clears its threshold.
6. **Seeds agree on the shape, not the digits.** Single-list rates move
   ±10 between seeds at 30–50 events; pool by family or by ≥ 4 buckets
   before reading a difference as real.
7. Track-boundary suspects are 1–8% everywhere — crossfades are not
   contaminating the picture.

### Pre-registered first experiments for the tuning phase

Each is one mechanism, one bake against the same 19 lists (both seeds),
scored on lift over chance; the prediction is written before the data.

- **E1 — phrase-quantized fires.** When a drop or impact fire is due, defer
  it up to N beats to the next bar boundary, and up to one bar to the next
  8-bar phrase boundary when `bars_since_track_start % 8 ≥ 6` (fire at the
  boundary, never earlier). Prediction: drop/impact phrase alignment from
  ~37 to ≥ 70% with energy lift unchanged or better (energy transitions in
  EDM sit on phrase boundaries); lock-churn and counts unchanged.
- **E2 — delta gate on drops.** Require the 1-bar bass window *after* the
  candidate fire to exceed the 2-bar window before by ≥ 10% before the fire
  is committed (one-bar look-ahead is affordable at replay; live, fire on
  the first beat that confirms). Prediction: drop energy/bass lift rate ×2
  on house family, drop count −30%, minor-tier drops mostly gone.
- **E3 — build/breakdown persistence.** Raise the `sustained_rise` /
  `sustained_fall` requirement (bars of monotone slope) until the 4-bar
  consistency clears 55% on house family; measure the count cost.
  Prediction: consistency +15 at −25% transitions.
- **E4 — per-profile drop threshold for the half-time profiles** (ambient,
  downtempo, hip-hop, trap, dubstep): lower `drop_trigger_threshold` until
  tracks-with-no-drop falls below 10% without the energy-lift rate falling
  below its family's current value.
- **E5 — replay-clock bias fix** in session_replay (the +1.2% both engines
  show in replays, absent live) before any recommender-side conclusion is
  drawn from replay profile mixes.

Not experiments: raising the activity rating's thresholds (it will be
replaced by the placement rating once E1–E4 have data).

## Experiment log

### E1 — phrase-quantized fires (2026-09-03): PASSED offline, panel bake running

Mechanism: `drop_phrase_snap_bars` (global `[auto_vj]` cfg tunable, 0 = off)
— when a pending drop is within that many bars of the next `phrase_snap_unit`
(8) boundary, `_schedule_drop()` chains downbeat callbacks to the boundary
instead of firing at the next bar. Impacts fire from inside `_fire_drop()`
and inherit it. Counter `drop_phrase_snap_count` (rows + payload).

Offline cells (seed 1, vs the same-order final-batch buckets):

| List | metric | baseline | snap 2 | snap 4 |
| --- | --- | --- | --- | --- |
| house-01 | drop phrase / chance | 43 / 37 | 46 / 37 | **86** / 38 |
| house-01 | impact phrase | 50 | 50 | **100** |
| dnb-01 | drop phrase / chance | 29 / 39 | 33 / 37 | **67** / 37 |
| dnb-01 | impact phrase | 36 | 31 | **78** |
| hip-hop-01 | drop phrase / chance | 41 / 31 | 72 / 31 | **84** / 32 |
| hip-hop-01 | impact phrase | 60 | 88 | **100** |

Drop counts (37/37, 51/54, 32/32), energy and bass lift, build/breakdown
consistency and lock churn unchanged within noise on all three. Snap 2
engages too rarely (6 of 37 drops). Snap 4 = defer at most half a phrase
(≤ 8 s at 125 BPM). Panel bake (19 lists × 2 seeds, snap 4) pre-registered:
drop phrase alignment ≥ 65% on every list, energy/bass lift within ±8 pt of
the family baseline, counts within ±10%, churn unchanged, placement rating up
on ≥ 15 of 19 lists.

### E4 — half-time genres under-fire drops: revised (2026-09-03)

The threshold is not the blocker. On tracks that never fire, `drop_score`
exceeds every mood trigger threshold for 43–47% of rows and downbeat
confidence clears its minimum; `drop_trigger_fired_count` never advances, so
no drop was ever *scheduled*. The gate that never clears is the split
**trigger** signal: `_trigger_raw = grid.impact_novelty`, compared against
`drop_trigger_threshold` (0.55–0.66 by mood). On never-fire tracks
`impact_novelty` p95 is 0.27–0.41 (firing tracks: 0.36–0.50). Half-time
material has softer, sparser transients, so an absolute novelty threshold is
genre-blind in the wrong way. Lowering it globally would add false fires on
house (their novelty p95 is higher).

Revised E4: a **per-track adaptive trigger** — `trigger_rel = impact_novelty /
max(floor, rolling_p90(impact_novelty, 60 s))`, gated by
`drop_trigger_rel_threshold` (0 = off; ~0.85 to test), alongside the absolute
gate (either passes). Prediction: never-fire tracks on ambient / downtempo /
hip-hop / trap / dubstep fall from 2–6 per list to ≤ 1, house drop counts
within ±15%, energy/bass lift unchanged or better (fires now land on each
track's *own* peaks). To be applied after the E1 bake lifts the freeze.
