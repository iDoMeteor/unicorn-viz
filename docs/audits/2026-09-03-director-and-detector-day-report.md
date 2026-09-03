# Director Placement and Detector Observation — Full Report, 2026-09-03

Owner: Auto VJ strategist seat
Status: complete for the day's work; two items still in flight (detector
step 3, the owner's live A/B)
Last updated: 2026-09-03 (night)

This is the thorough analysis the owner asked for after the E6 panel. It
covers everything that ran on 2026-09-03: the E6 director panel and its
ablation, the owner's variant (E8) across three offline rounds, the OSS
beat-tracker bench, and the dense-envelope detector prototype. Every number
here comes from the seat reports listed in the appendix; nothing is
re-derived from memory.

## 0. How to read every number in this report

- **Lift over chance is the quantity.** Every director placement rate is
  reported next to a *chance* rate: the same metric computed on random
  on-beat frames of the same track, at least 8 bars in, five samples per
  real event, fixed seed. A rate of 48% with chance 38% is a +10 point
  lift. A rate of 22% with chance 39% is anti-aligned: worse than random.
- **n is the compared-row count** behind a rate. Under about 15, read the
  rate as noise. Climax is the rarest mode everywhere and is always the
  noisiest read.
- **On-beat** = the transition fired within 0.15 of a beat phase boundary.
  **On-phrase (8)** = within ±1 bar of a multiple of 8 bars since track
  start. **Trend-following** = for a build, energy over the 4 bars after
  the transition exceeds the 4 bars before by more than 5%; for a
  breakdown, falls by more than 5%.
- **Counts** are total transitions across the whole panel (19 lists × 2
  seeds ≈ 38 one-hour sessions), so 5071 builds ≈ 133 per hour ≈ one every
  27 seconds.
- **Predictions were written before every run** and are scored as written,
  held or missed, with the number. A miss is data, not a failure of the
  run.

## 1. Where the director stands

| version | what it does | status |
| --- | --- | --- |
| rc.15 (morning baseline) | E1 phrase-quantized drops/impacts; E4 rescue trigger scoped to never-fired tracks | the reference every panel is compared to |
| rc.16 | E6: build/breakdown/climax defer to the next downbeat, and to the 8-bar phrase boundary when within 2 bars of it; a transition whose trend reverses before the boundary is cancelled | **shipped** (landed 2026-09-03 evening) |
| rc.17 | E8 mechanisms (owner variant) available as tunables; every default reproduces rc.16 exactly | **shipped**, behavior unchanged |

Both the owner's live A/B arms and the offline cells below are pure
config on the rc.17 code path.

## 2. The E6 panel (19 lists × 2 seeds, rc.16 candidate vs rc.15)

### 2.1 What held, every list, no exceptions

| metric | rc.15 | rc.16 candidate |
| --- | --- | --- |
| build on-beat | 30.5% (n=5071) | **100.0%** (n=3705) |
| breakdown on-beat | 32.0% (n=4592) | **100.0%** (n=3097) |
| climax on-beat | 32.3% (n=254) | **100.0%** (n=103) |
| drop on-phrase (8) | 74.3% (chance 38) | 77.1% (chance 39) |
| impact on-phrase (8) | 79.4% (chance 38) | 85.0% (chance 37) |
| drop energy lift | 19.0% (chance 10) | 17.0% (chance 10) |
| lock churn events | 1700 | 1700 (identical: E6 never touches the detector) |
| E4 half-time guard (never-fire ≤ 2) | 12/12 | 12/12 |
| E4 house-family guard (drop count ±15%, lift ±5) | 8/8 | 8/8 |
| placement rating, mean of 38 cells | 3.58 | 3.84 (11 up, 26 flat, 1 down) |

The owner's stated requirement, "every mode in director hitting on time",
is met in full: every build, breakdown and climax now fires on a beat, on
every list, on both seeds.

### 2.2 What missed, all on one axis

| metric | rc.15 | rc.16 candidate | pre-registered target |
| --- | --- | --- | --- |
| build on-phrase (8) | 39.4% (chance 38) | 48.2% (chance 38) | ≥ 65% |
| breakdown on-phrase (8) | 38.3% (chance 38) | 46.4% (chance 38) | ≥ 65% |
| climax on-phrase (8) | 12.2% (chance 37) | 22.3% (chance 39) | above chance |
| build trend-following | 40.0% (chance 23) | 37.2% (chance 23) | no worse |
| breakdown trend-following | 37.6% (chance 21) | 37.5% (chance 22) | no worse (held) |
| build count | 5071 | 3705 (−26.9%) | inside −25% |
| breakdown count | 4592 | 3097 (−32.6%) | inside −25% |
| climax count | 254 | 103 (−59.4%) | inside −25% |

Engagement: 8707 transitions deferred, 1897 chained to a phrase boundary,
1798 cancelled (20.7%) because the trend reversed before the boundary.

### 2.3 Per-list build trend-following, rc.15 → rc.16 candidate (delta in points)

| list | rc.15 | delta | list | rc.15 | delta |
| --- | --- | --- | --- | --- | --- |
| favorites | 42.8 | −1.7 | house | 39.8 | −5.7 |
| ambient | 34.9 | −4.5 | nu-disco | 44.7 | −5.0 |
| big-room | 31.2 | −5.7 | progressive-house | 40.8 | −0.2 |
| curveballs | 43.8 | −6.4 | rnb | 33.3 | **+4.8** |
| dance | 44.7 | −8.8 | tech-house | 47.1 | −7.2 |
| deep-house | 39.8 | **+3.0** | techno | 46.5 | −3.1 |
| downtempo | 34.2 | −4.9 | **trance** | 45.6 | **−10.6** (worst) |
| drum-and-bass | 41.0 | −6.0 | trap-hip-hop | 31.6 | **+7.4** |
| dubstep | 38.5 | **+4.3** | hip-hop | 38.9 | −2.5 |
| future-house | 38.6 | −5.7 | | | |

Six of nineteen lists *improve* on build trend under deferral (deep-house,
dubstep, rnb, trap-hip-hop, and near-zero on favorites and progressive
house). The aggregate −2.8 point miss is not uniform; the four-on-the-floor
lists with fast, regular energy cycles (trance, dance, tech-house) pay
most, the half-time and syncopated lists pay nothing or gain.

### 2.4 Worst list, worst mode, one regressed cell

- **Worst mode: climax**, on every axis. Largest count cost (−59%), the
  only mode still below chance on phrase alignment after the change (22 vs
  39), and the smallest population (n=103 across 38 hours).
- **Worst list by count cost: dubstep-01** (build + breakdown −45.5%).
- **Worst list by trend decline: trance-01** (−10.6 points).
- **Only cell whose rating fell: downtempo-01 seed 1** (4 → 3, placement
  score 0.287 → 0.233). The ablation later showed it regresses on every
  deferral variant, so it is intrinsic to deferral on that session, not to
  the phrase window.

### 2.5 Why the misses happen: the deferral arithmetic

Two cheap analyses from the same data settled the mechanism:

- **Deferral is short.** Transitions that fired were deferred 1.10 bars
  (build), 1.11 (breakdown), 1.06 (climax) on average. Only ~20% of fired
  events were phrase-chained at all (8.7% for climax). So the phrase window
  cannot be carrying most of the cost.
- **Cancellation is the other lever.** About one in five deferred
  transitions is cancelled because its trend reversed within the bar it
  waited. Those were transitions the old code would have made on evidence
  that did not survive one bar.
- **Cycles compound.** A build that fires a bar later has a bar less of its
  rise left to follow (trend down ~3 points). Every cycle of
  cruise → build → drop → breakdown takes longer, so fewer cycles fit in an
  hour, and climax, downstream of build and drop both, loses most.
- **Climax is structural, not a snapping failure.** On rc.15, climax fires
  a median 3.1 bars after the drop (70% in bars 2–4, tail to 20). It
  escalates from a phrase-aligned drop after a roughly fixed hold, so it
  lands mid-phrase by construction. Snapping it to the 8-bar boundary means
  holding it up to 7 bars, which round 1 of E8 showed kills it outright.

### 2.6 The 5-count question the panel cannot answer

Fewer, later, on-beat transitions are not obviously worse. rc.15 fired a
build every 27 seconds and a breakdown every 30; rc.16 fires them every 37
and 44 seconds. Whether a director that changes scene a third less often
but always on the beat *looks* better is a judgment about the show, and it
is exactly what the owner's live A/B is for. The instrument can say the
timing is now perfect and the decisions are slightly staler; it cannot say
which the audience prefers.

## 3. The E6 ablation (why rc.16 ships the 2-bar window)

Two more cells on the same 19 × 2 panel: phrase window 0 bars (downbeat
only) and 1 bar.

| | rc.15 | 0-bar | 1-bar | 2-bar (shipped) |
| --- | --- | --- | --- | --- |
| build on-phrase (8) | 39.4 | 38.1 | 38.1 | **48.2** |
| breakdown on-phrase (8) | 38.3 | 36.7 | 36.7 | **46.4** |
| build trend | 40.0 | 37.0 | 37.0 | 37.2 |
| build / breakdown / climax count | — | −23.5 / −28.0 / −58.3% | identical | −26.9 / −32.6 / −59.4% |
| cancelled | — | 19.1% | 19.1% | 20.7% |
| placement rating | 3.58 | 3.68 | 3.68 | **3.84** |

**Findings.**

1. **The 1-bar cell is the 0-bar cell**, byte-identical on every count
   across all 38 cells. Chaining to a boundary that is already the next
   downbeat is a no-op on timing. Values below 2 mean downbeat-only; the
   key's comment now says so.
2. **Downbeat-only carries essentially the whole cost.** Trend, counts and
   cancellations are within 3–4 points of the 2-bar cell. The 2-bar window
   adds +10 points of phrase alignment on builds and breakdowns for that
   3–4 points of extra count loss.
3. **The pre-registered landing rule's premise was falsified.** The rule
   assumed the phrase half was the cost and said "if neither cell qualifies,
   ship downbeat-only". Neither qualified (trend below baseline in both),
   and the fallback would have shipped the strictly worse candidate. The
   rule was not followed; the choice was made between two pre-registered
   cells on their measured numbers, and the departure is recorded in the
   planning doc and the ADR. Predictions on the ablation: 2 of 6 held, 4
   missed, all four misses about how much the downbeat deferral itself
   costs.

**Decision:** rc.16 ships downbeat snap on all three modes with a 2-bar
phrase window and the persistence raise (E3) off. E3 at 1, 2 and 4 bars
blew its own −25% budget in every offline cell (4 bars zeroed both modes)
and stays a knob.

## 4. The owner's variant (E8), three offline rounds

Owner's rule: "build detect on a downbeat from within a breakdown phrase,
drop detect on downbeat of either, climax only on phrase within drop (no
build required); we can probably drop from cruise but only on very high
conf." Implemented as per-mode config (snap unit, phrase grid, phrase
window, allowed source modes, a cruise-drop confidence floor) so that the
consensus default and the variant are two config sets on one code path.
Six medium-to-high-energy lists (house, tech-house, big-room, techno,
trance, drum-and-bass), one seed, rc.16 as the control.

### 4.1 Round 1: the variant as specified

| mode | rc.15 | rc.16 control | variant | vs control | vs rc.15 |
| --- | --- | --- | --- | --- | --- |
| build | 609 | 497 | 104 | **−79.1%** | −82.9% |
| breakdown | 534 | 407 | 197 | −51.6% | −63.1% |
| climax | 38 | 18 | **0** | **−100%** | −100% |

All four predictions missed.

- **Builds only from breakdown** removed all 220 cruise-sourced builds as
  designed, but breakdown-sourced builds *also* fell 277 → 104 though never
  blocked. Fewer full cycles complete when a chunk of transitions is
  blocked outright, so fewer breakdown-sourced opportunities ever arise.
- **Climax on the 8-bar boundary** produced zero climaxes in all twelve
  cells. Verified by counter arithmetic (fires + cancelled = scheduled,
  exact on two sampled buckets): every scheduled climax was cancelled at
  its fire-time re-check, because a hold of up to 7 bars outlasts the
  drop's energy peak every time.
- **Cruise-to-drop** (confidence ≥ 0.71 and major tier) fired 40 of 157
  drops (25.5%, predicted 5–15%) with an energy-lift rate of 15% against
  27% for the population. The gates select for confidence, not for
  landing on a rise. **Parked**, not abandoned.
- Note the quality side: the few transitions that survive are *better*.
  Core's drop energy lift 30.8% vs control 19.1%; breakdown trend 50.8% vs
  41.8%; build trend 43.3% vs 36.0%. Restricting sources filters noise
  along with signal.

### 4.2 Round 2: half-phrase climax, confidence-gated builds

| cell | build count vs rc.16 | build trend | climax count | climax on 4-bar grid | climax on 8-bar grid |
| --- | --- | --- | --- | --- | --- |
| rc.16 control | — | 36.0% | 18 | — | 27.8% (chance 48) |
| **climax-4** (4-bar half-phrase grid) | +0.0% | 36.0% | **14 (78% of control)** | **100% (chance 76)** | 21.4% (chance 40) |
| build-floor 0.71 | **−67.8%** | **40.6%** | 6 | — | 0% |
| both | −67.8% | 40.6% | **4** | 100% | 0% |

- **Climax on a 4-bar grid is the first real win from the variant.**
  Climax count recovers to 78% of rc.16 instead of vanishing, builds and
  breakdowns are untouched, and climax lands on its own 4-bar grid 100% of
  the time against a 76% chance floor. On the 8-bar reading it stays
  anti-aligned, which is what a half-phrase snap means by construction;
  the prediction that it would sit "about chance at 8" was wrong.
- **Gating cruise builds at 0.71 costs nearly as much as blocking them**
  (−68% vs −79%), because 0.71 turned out to be that population's 90th
  percentile. The survivors follow the trend better (40.6 vs 36.0).
- **Stacking is sub-additive.** Both together gave 4 climaxes, fewer than
  either alone. The build cut starves the cycles climax needs.

### 4.3 Round 3: the build floor re-derived from its own population

The distribution the floor actually gates (cruise ticks with build
evidence, 3854 pooled): p25 0.41, median 0.53, p75 0.62, p90 0.70.

| | rc.16 control | build-floor at the median (0.53) | vs control |
| --- | --- | --- | --- |
| build count | 497 | 370 | **−25.6%** (predicted 20–40%: held) |
| build trend | 36.0% | 37.8% | between 36.0 and 40.6: held |
| breakdown count | 407 | 331 | −18.7% ("untouched": missed) |
| climax count | 18 | 13 | −27.8% ("untouched": missed) |
| drop energy lift | 19.1% | 20.3% | unchanged |

Qualifies as a panel candidate. The miss on breakdown and climax is the
third round in a row showing the same thing.

### 4.4 Two standing rules learned from E8

1. **Compounding cycles.** Any change that cuts build count costs breakdown
   and climax downstream, whatever mechanism did the cutting. Every future
   build-affecting cell is reported that way, never assumed away.
2. **Sub-additivity.** Director mechanisms interact through the shared
   state machine and do not compose linearly. Every combination gets its
   own cell.

### 4.5 What goes to the full panel

Candidates: climax-4 (`mode_phrase_unit_climax = 4`), build-floor-median
(`mode_source_min_confidence_build = 0.53`), and their combination as its
own cell, against the rc.16 control, on the full 19 × 2 panel with the
same landing rule. It runs **once, after detector rc.41 lands**, so the
director is judged on the tracker that will ship. The owner's live A/B
sessions are packaged with the same instrument and reported beside it as a
sanity check (small n per session).

## 5. The detector: bench, prototype, and what ships next

### 5.1 The OSS bench (bench seat; 311 tracks, 306 unique; reference ladder owner > tag > Essentia)

| model | Acc1 exact (±4%) | Acc2 within a fold | lane hops/min | genuine lock | licence |
| --- | --- | --- | --- | --- | --- |
| madmom (RNN + online DBN) | 76.1% | 96.1% | 0.8 | 0.50 s | BSD code, CC BY-NC-SA weights: not shippable |
| BTrack (comb + complex spectral difference) | 76.1% | 96.4% | 0.0 | 0.48 s | GPL: reimplement, never vendor |
| Essentia (51 tracks, offline re-run) | 58.8% | 94.1% | — | artifact | AGPL |
| BeatNet | deferred (>3× realtime) | | | | CC BY 4.0 |
| **v3 stock** | 65.4% | 91.2% | 0.52 | — | ours |

Lane hop = a jump to a different harmonic family (2:1, 1:2, 3:2, 2:3, 4:3,
3:4). Churn = any flip of the reported value. BTrack's one weak genre
(drum-and-bass 31%) is mostly its fixed 80–160 BPM range; widening it
recovered dnb to 56% but introduced a half-time drift at 155–170 that the
old range had hidden by edge-pinning, so it was reverted. Lesson kept: a
tracker's apparent stability at the edge of its range is not stability.

**The strategic reading.** Two tracker classes with no learned model in
common land on the same 76% ceiling, and BTrack gets there with a
hand-designed onset function and zero training. The ceiling is the
observation, not the tracker, and the cheap lever is the onset signal.

### 5.2 The dense-envelope prototype (bench seat; v3 with stock constants, no re-tune)

| row (306 tracks, feed path verified) | Acc1 | Acc2 | raw churn | smoothed churn | lane hops/min |
| --- | --- | --- | --- | --- | --- |
| stock v3 (sparse peak-picked pulses) | 65.4% | 91.2% | 5.59 | 8.37 | 0.52 |
| true clock only, still pulsed (E5 patch) | worse (51-track: 10/22 hardest vs 13) | | | | |
| **dense envelope, our own spectral flux** | **75.8%** | **95.8%** | **1.44** | **2.03** | **0.31** |
| dense envelope, complex-domain onset | 76.5% | 96.7% | 1.83 | 2.38 | 0.42 |

- **The write path is the win.** Writing the analyzer's raw per-block
  spectral flux densely into the envelope ring, every 10 ms slot, by
  absolute time, instead of sparse pulses at peak-picked onset events,
  gains +10.4 points exact with stock constants. The complex-domain onset
  function adds +0.7 on top at slightly more churn and is not part of what
  ships.
- **The clock bug alone made things worse**: the comb, prior and gate stack
  was co-adapted to the old timing jitter. The dense path subsumes the E5
  clock fix and wins anyway.
- **The house-family gap is closed.** All ten named 4/3-lane house tracks
  (100–126 BPM read at 133–169 by stock) resolve exact under the dense
  rows. That was the whole gap against madmom on clean house lists.
- **Churn fell 3.5×** with lane hops unchanged: fewer within-lane wobbles,
  which is what the director sees.
- **Drum-and-bass** 19% → 50% exact (unpredicted; three tracks regress
  inside that gain, the first re-tune targets). **Dubstep flat at 29%** on
  every row; it is genuinely bimodal and this change does not touch that.
- Two runs were discarded before the clean one: a driver bug that routed
  the flux row through the wrong path (caught because the result
  contradicted the 51-track finding), and a run with 83 uncaptured decode
  failures. The harness now stamps the feed path on every row, asserts it
  before writing a table, records every decode failure's reason, and
  refuses to write a table on any skip.

### 5.3 What ships next: Program B step 3 (training seat, in flight)

Pre-registered batch 1: apply the clock patch; add an envelope-source
tunable (`pulses` = today, `dense_flux` = the bench mechanism, matching the
bench code's normalizer and log compression exactly); flip the two-test
xfail; re-derive the 35 zero-jitter v2 fixtures with the jitter their own
docstring describes; then a 22-hardest checkpoint on stock / clock-only /
dense for v3 and v2 with churn columns. Stop condition: if dense does not
recover past clock-only, nothing proceeds until it is understood. Batch 2
(re-tune only if a guard fails, fixture verification at scale, the 19-list
panel against rc.40 and against madmom/BTrack as unbiased references)
lands as detector rc.41.

## 6. The composite picture

| subsystem | this morning | tonight |
| --- | --- | --- |
| director timing | modes on-beat ~30% | modes on-beat 100% (rc.16 shipped) |
| director phrase alignment (build/breakdown) | at chance | +10 over chance |
| director cost | — | a third fewer transitions, trend −3 points; owner's A/B decides |
| owner variant | an idea | two tuned pieces qualified for the panel, one parked, two structural rules learned |
| detector accuracy | 65.4% exact, 9 points behind the references | 75.8% in prototype, level with the references, pending rc.41 |
| detector churn | 8.4 flips/min | 2.0 in prototype |
| bench | four models to compare | done, licences recorded, summary written |

**Order of what remains:** detector rc.41 → the winner-vs-variant director
panel (once) → the owner's acceptance session (one random cross-faded run
per one-hour list plus favorites and toughies, four in parallel, full
per-list report and composite) → the whole-library shuffle run.

## Appendix: source reports

- E6 panel: `drop-ins/training-kit-01/tools/baselines/director_placement_e6_panel-2026-09-03.md`
- E6 ablation: `.../director_placement_e6_ablation-2026-09-03.md`
- E8 rounds 1–3: `.../director_placement_e8_offline-2026-09-03.md`,
  `.../director_placement_e8_round2-2026-09-03.md`,
  `.../director_placement_e8_round3-2026-09-03.md`
- rc.15 final baseline: `.../director_placement_final-baseline-2026-09-03.md`
- Bench: `tools/beat-tracker-bench/results/SUMMARY.md`,
  `.../onset_prototype.md`, `.../onset_prototype_pertrack.md`
- Plans: `docs/planning/director-placement-scoring-2026-09-03.md`,
  `docs/planning/auto-vj-v3-roadmap-and-accelerated-replay-2026-08-17.md` (Part 0)
- ADR entries: `docs/adr/vj-system.md` ("Director Placement E6", "E3",
  "E8 rounds 1–3"; "v3 phases 1–4"; "E5" and addendum)
