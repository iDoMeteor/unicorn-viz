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
- **E6 — mode-transition quantization (added 2026-09-03, after the final
  baseline).** Apply E1's mechanism to build / breakdown / climax entry:
  defer the transition to the next downbeat, and to the 8-bar phrase
  boundary when within `mode_phrase_snap_bars` (default 2) of it; never
  earlier. Paired with E3's persistence raise in the same bake, as two
  cfg tunables so each can be zeroed independently. Measured on the final
  baseline (rc.15): build on-beat 30% / phrase 39% vs 37 chance, breakdown
  33% / 40%, climax 30% / 12% vs 41 chance. Prediction: all three modes
  on-beat ≥ 95%, on-phrase ≥ 65% (drops reached ~75% under E1), climax
  anti-alignment gone; trend-following (build 40 vs 23 chance, breakdown
  38 vs 21) unchanged or better because a later, boundary-aligned
  transition sees one more bar of evidence; mode counts within −25%
  (E3's cost), drop/impact metrics and lock churn unchanged. Executed by
  the training seat as director rc.16.

Not experiments: raising the activity rating's thresholds (it will be
replaced by the placement rating once E1–E4 have data).

## Experiment log

### E6 — mode-transition quantization (2026-09-03): panel read, NOT landed yet

Panel 19×2 (shipped candidate: downbeat snap on, phrase snap within 2 bars,
E3 off), full report
`drop-ins/training-kit-01/tools/baselines/director_placement_e6_panel-2026-09-03.md`.
Held: on-beat 30% → 100% on build/breakdown/climax, every list; drop/impact
metrics stable; lock churn identical; both E4 guards. Missed: on-phrase
48/46/22% (target ≥ 65); climax still below chance (22 vs 39); build
trend-following 40.0 → 37.2; mode counts −27/−33/−59% with E3 off (ceiling
was −25). Placement rating 3.58 → 3.84 (11 up, 26 flat, 1 down:
downtempo seed 1). E3 at 1/2/4 bars blew its own budget in every offline
cell; stays off, kept as a knob.

**Reading.** The timing win the owner asked for is the downbeat half and
it is total. The three misses share one axis, and all three are what a
deferral of up to 2 bars past the decision would produce: a build declared
later has less of its rise left to follow (trend down), some decisions
reverse before the boundary (20.7% cancelled), and every cycle takes longer
so fewer fit (counts down, compounding into climax). Whether fewer, later,
on-beat transitions are *worse* is not settled by counts alone — the
baseline's one-build-every-27-s cadence was frantic — but a −10 pt trend
loss on trance and a −59% climax count are not free. Climax's anti-
alignment is structural, not a snapping problem: it escalates from a
phrase-aligned drop after a fixed hold, so it lands mid-phrase by
construction; snapping it to a boundary means holding it up to a phrase.
That wants a different mechanism (climax as "drop + N phrases"), logged as
an E7 candidate, not more E6.

**Pre-registered ablation before landing (two cells, same 19×2 panel):**
`mode_phrase_snap_bars = 0` (downbeat only) and `= 1`. Predictions, written
before the data: downbeat-only keeps on-beat 100%, phrase alignment returns
to ~chance (39–40), build trend recovers to ≥ 40, cancellations fall to
~10% and mode counts land within −15% of baseline; the 1-bar cell sits
between, keeping ≥ 60% of the 2-bar phrase gain at ≤ half its count/trend
cost. Landing rule: ship as rc.16 default whichever cell keeps on-beat
100% with build trend ≥ baseline and counts inside −25%, preferring the
one with more phrase gain if two qualify; phrase snap stays a knob either
way. If neither qualifies, land downbeat-only and record the phrase half
as a measured cost.

**Owner variant (2026-09-03, pre-registered as E8, tested after the
ablation picks the consensus E6 default).** Owner: "build detect on a
downbeat from within a breakdown phrase, drop detect on downbeat of
either, and climax only on phrase within drop (no build required)". Read
as a per-mode quantization table plus allowed source modes:

| transition | snap unit | allowed from |
| --- | --- | --- |
| → build | downbeat | breakdown (the decision is taken inside a breakdown phrase) |
| → drop | downbeat (E1's phrase chain already fires on a downbeat; whether the 4-bar phrase snap stays on top is the owner's call, default: keep E1 as landed) | build or breakdown |
| → climax | 8-bar phrase boundary | drop, no prior build required |

Implementation rule: express as cfg (`mode_snap_unit_<mode>` ∈ downbeat /
phrase, `mode_allowed_from_<mode>`), so the consensus E6 default and the
owner variant are two config sets on the same code path and the same
instrument scores both. Same panel, same landing rule, plus a per-mode
transition-source breakdown so "climax without build" is countable.

**Live A/B (owner-run).** The owner runs a couple of short live sessions
per arm; the packager's placement section scores them with the same
chance baselines. Live arms are the same cfg keys, so an A/B is two
`config.toml` values, not a build. Live counts will be small (n under 15
per mode per session reads as noisy) — treat the live pair as a sanity
check on the replay panel, not as the decider.

**Analysis asks from existing panel data (no new runs):** cancellation
split by step (downbeat vs phrase chain) and mean deferral length in
beats per mode; climax time-since-drop distribution in bars on the rc.15
baseline (input to E7). *Answered:* fired events were deferred ~1.1 bars
on average and only ~20% were phrase-chained (so the phrase half cannot
carry most of the count cost — the downbeat-only prediction above may
miss; score it as written). Climax fires a median 3.1 bars after the drop,
70% in bars 2–4: structural, confirmed.

**Ablation result (2026-09-03 evening; report
`drop-ins/training-kit-01/tools/baselines/director_placement_e6_ablation-2026-09-03.md`).**
The 1-bar cell is byte-identical to the 0-bar cell on every count
(chaining to a boundary that is already the next downbeat is a no-op on
timing; values below 2 mean downbeat-only, documented on the key).
Downbeat-only carries essentially the whole cost — build trend 37.0 (base
40.0), counts −23.5/−28.0/−58.3, cancellations 19.1% — while the 2-bar
candidate adds +10 pt build phrase alignment (48 vs 38, chance 38) for
3–4 pt more count loss and the same trend. Predictions: 2/6 held (on-beat
100%, phrase back to chance), 4/6 missed (trend recovery, ~10%
cancellations, counts within −15%, "1-bar sits between"). Guards clean on
both cells; trance is the worst trend list on both (−6.6 / −10.6);
downtempo seed 1 regresses 4→3 on every cell. **The landing rule's
premise ("the phrase half is the cost") was falsified and its fallback
branch was not followed:** neither cell meets the rule, and shipping
downbeat-only would ship the strictly worse candidate on the measured
numbers. **Decision: rc.16 ships the 2-bar candidate** (per-mode keys,
downbeat snap on all three modes, 2-bar phrase window, E3 off), and the
intrinsic cost of "defer one downbeat, cancel on reversal" — fewer, later
transitions — is the question the owner's live A/B answers. Climax's
−59% is E7/E8 territory.

### E8 — owner variant: per-mode snap unit + allowed source (2026-09-03)

Owner: "build detect on a downbeat from within a breakdown phrase, drop
detect on downbeat of either, and climax only on phrase within drop (no
build required)"; later: "we can probably drop from cruise but only on
very high conf." Read as a per-mode quantization table plus allowed
source modes:

| transition | snap unit | allowed from |
| --- | --- | --- |
| → build | downbeat | breakdown (decided inside a breakdown phrase) |
| → drop | downbeat (E1's phrase chain already fires on a downbeat; E1 stays as landed) | build or breakdown freely; **cruise only above a high drop-confidence floor** — note rc.16 has *no* cruise→drop path at all (cruise only ever enters build/breakdown), so the owner's rule adds a new path, built and pre-registered in the E8 phase with the floor defaulting to disabled |
| → climax | 8-bar phrase boundary | drop, no prior build required |

**Config model (training seat design, approved):** `mode_snap_unit_<mode>`
∈ off / downbeat / phrase; `mode_phrase_within_bars_<mode>` (chain to the
boundary only when within N bars; default = full phrase = always chain; 2
reproduces the E6 candidate, 1 the 1-bar cell); `mode_allowed_from_<mode>`
(list, today's real source paths as defaults, so the consensus E6 default
is "no restriction"); blocked transitions counted, not silent; corpus rows
carry `from_mode` and `snap_unit_applied`; drops gain a cruise-only
confidence floor key. The old `mode_snap_downbeat` /
`mode_phrase_snap_bars` derive the new keys one way and are otherwise
retired. Consensus E6 and E8 are two config sets on one code path; the
same instrument scores both, plus a transition-source breakdown so
"climax without build" is countable.

**Sequence (owner, 2026-09-03):**
1. Ablation reads → consensus E6 default lands as rc.16 (landing rule
   above).
2. Owner A/Bs the present scenario live (a couple of short sessions per
   arm; packaged with the placement section; small n, sanity check only).
3. Strategist + training seat **tune E8 first** on a few medium-to-high-
   energy lists (house, tech-house, big-room, techno, trance; dnb as the
   fast control) — snap units, the cruise confidence floor, the build-
   from-breakdown restriction's count cost — before it meets the winner.
4. `[winner] vs E8` on the full 19×2 panel, same report format, same
   landing rule; owner's live sessions reported next to it.

### E8 — offline cells, pre-registration (2026-09-03)

**Mechanism.** `mode_allowed_from_build = ['BREAKDOWN']` (drop the CRUISE
source; breakdown recovery is the only remaining path). `mode_snap_unit_
climax = 'phrase'` with `mode_phrase_within_bars_climax = 8` (the full
`phrase_snap_unit`, i.e. always chain to the boundary regardless of
distance — `to_boundary` is always in [0, 7], so `snap=8` unconditionally
satisfies `0 < to_boundary <= snap`). Cell 2 additionally enables
`drop_cruise_min_confidence = 0.71`, a new CRUISE → DROP path (off by
default, `_schedule_drop()` called from inside the CRUISE branch, gated on
the same score/trigger evidence BUILD/BREAKDOWN's normal entry uses plus
this confidence floor, `has_lock`, **and a major-tier proxy** — a
cruise-sourced drop has no build evidence behind it (owner), so it must
clear both a confidence axis and a strength axis, not just one. The tier
proxy reuses `_climax_entry_score` (`drop_threshold + 0.08`) rather than
calling `_infer_peak_tier()` itself: that function's cycle-count/
phase-dwell logic is designed around a prior BUILD/BREAKDOWN phase and
would read CRUISE's own (usually long) dwell time instead, trivially
passing almost always — a raw score bar against an existing "elevated
tier" constant is the meaningful check here. Blocks are counted per axis
(`drop_cruise_blocked_confidence_count` / `drop_cruise_blocked_tier_count`,
not mutually exclusive) so a report can tell which axis is actually
binding. Confirmed via reading every `_schedule_drop()` call site that no
CRUISE→DROP path exists in rc.16 shipped code; this is new. All three
cells run `beat_tracker_engine=v3`, otherwise rc.16 defaults, one seed (1),
on house, tech-house, big-room, techno, trance, dnb.

**`drop_cruise_min_confidence` proposal: 0.71.** The rc.15 baseline's
`downbeat_confidence` distribution across 345,938 corpus rows: p50 0.531,
p75 0.630, **p90 0.711**, p95 0.762, p99 0.869. The `drop_fire` event
population specifically reads almost identically (p90 0.709), so drops
aren't already biased toward higher-confidence ticks. 0.71 sits well above
every mood profile's existing `drop_min_downbeat_confidence` (0.28–0.34) —
roughly 2–2.5x the bar every other drop path clears today, matching "very
high confidence."

**Predictions, per mode per cell, written before the run:**

1. **Build count cost of the breakdown-only restriction.** Counted from
   the rc.16 panel's `from_mode`, reconstructed via the preceding-
   heartbeat's `vj_mode` (the panel predates the `from_mode` corpus field
   added in this same landing): of 3699 real build entries across all 19
   lists × 2 seeds, **59.7% came from BREAKDOWN, 40.3% from CRUISE**.
   Contrary to "cruise→build is the common path today" — BREAKDOWN is
   already the majority source. Prediction: build count drops **~40%**
   (losing the CRUISE-sourced share), not near-total loss. Confirmed
   directionally in a pre-registration smoke test on rnb-01 seed 1
   (7 tracks): 5/5 build entries fired, all from BREAKDOWN, 971
   CRUISE-sourced build attempts blocked in that one short session.
2. **Climax phrase alignment.** Currently 22.3% vs ~39% chance (below
   chance) on the rc.16 panel, with only 8.7% of fired climax events even
   phrase-chained under `snap=2`. With `snap=8` (unconditional), every
   surviving climax entry chains to the boundary by construction.
   Prediction: **phrase alignment jumps to ~95–100%**, mirroring E1's own
   unconditional-chain drops.
3. **Climax count.** Already the most-cancelled, lowest-count mode under
   rc.16 (−59.4% vs the rc.15 baseline, n=103 pooled). An 8-bar
   unconditional wait is up to 4x longer than the 2-bar window that
   already only phrase-chained 8.7% of the time. Prediction: **count drops
   further**, plausibly another 20–40% relative to the already-reduced
   rc.16 climax count on these six lists — direction and relative-largest-
   cost confident, exact magnitude not.
4. **Cruise-drop count and energy-lift rate (cell 2 only).** Smoke test on
   rnb-01 seed 1 (re-run with the tier gate added): of 9 total drop_fire
   events, 2 were CRUISE-sourced (new `drop_source` field, captured at
   `_fire_drop()`'s own entry before `self._mode` is reassigned), 6
   breakdown, 1 build; 170 blocked on the confidence axis, 83 on the tier
   axis (not mutually exclusive) — both gates are doing real, distinguishable
   work, not one dominating the other. Prediction: cruise-drops are a
   **small but non-zero share** of total drops (order 5–15% on a full-list
   session, likely toward the low end now with two gates instead of one);
   energy-lift rate on the cruise subset **no worse than** the overall
   `drop_fire.energy_lift` rate — the gates select for detector certainty
   and score strength, not for any particular point in the energy
   trajectory, so no directional claim beyond "not worse."

**New corpus fields, verified via a live smoke test before this
pre-registration:** `from_mode` (already landed in rc.16, confirmed
correct on build/breakdown/climax rows); `drop_source` (new, this cell) on
every `drop_fire` row; `mode_blocked_by_source_count`,
`drop_cruise_blocked_confidence_count`, `drop_cruise_blocked_tier_count`,
`drop_cruise_fired_count` (new counters, all nonzero and mutually
consistent on the smoke test).

**Report format:** same as the rc.16 panel/ablation — per-list, per-mode
table with compared-row (n) counts and chance baselines, pooled table
across the six lists, held/missed verdicts against the four predictions
above, plus a dedicated **from_mode source-breakdown table** (build/
breakdown/climax × source mode, all three cells side by side) so the
count-cost story is traceable to exactly which source is gained or lost,
not just a net delta. Build and climax counts reported **relative to both
the rc.16 control cell and the rc.15 final baseline** — the costs stack
(E8's own predicted −40% build on top of rc.16's already-measured −27% vs
rc.15 works out to roughly −56% vs rc.15, not −40%), and the owner will
want the cumulative number, not just the E8-over-rc.16 delta.

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
