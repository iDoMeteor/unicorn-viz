# Onset prototype — Program B step 2

Dev-only benchmarking, `tools/beat-tracker-bench/onset-prototype/`. Tests
whether v3's accuracy ceiling (documented in `SUMMARY.md`: madmom and
BTrack both land at ~76% Acc1 against v3's ~66% on the same 306-track
corpus) is set by the *observation* function rather than the tracker's
decision logic — and, if so, how much of the gap a hand-designed,
untrained onset function can close.

## Row definitions

Four rows on the 51-track set (22-track hard-set + house-01 + dnb-01),
two rows carried to the full 311-track / 19-list set. Every row uses this
project's own **unmodified `BeatTrackerV3` decision logic** — no `_V2_*`/
`_V3_*` constant was retuned at any point. What changes between rows is
only how the 100 Hz envelope ring gets written.

- **stock** — production `BeatTrackerV3`, unmodified: the analyzer's
  spectral-flux value is peak-picked into discrete `OnsetEvent`s (adaptive
  threshold + band weighting), and only those sparse events get written
  into the ring via `_pulse_envelope()`; everything else zero-fills via
  `_advance_envelope()`. Includes the E5 clock bug (accumulator-based
  advance).
- **e5** — identical to stock, but built from a local copy of
  `beat_grid.py` with `docs/planning/patches/e5-envelope-clock-redesign-
  2026-09-03.patch` applied (absolute-index envelope advance instead of
  the accumulator; see ADR E5 in `docs/adr/vj-system.md`). Isolates the
  clock fix alone, still sparse peak-picked pulses.
- **odf** — the E5-patched tracker, but the ring is written by a
  **complex-domain onset function** (Bello, Duxbury, Davies & Sandler,
  "On the Use of Phase and Energy for Musical Onset Detection in the
  Complex Domain," IEEE Signal Processing Letters, 2004 — reimplemented
  from the paper's description, `complex_onset.py`; **no BTrack source
  was read or copied for this** — BTrack is GPL-3.0 and the algorithm is
  a published, independent-of-BTrack technique). This value is produced
  **densely** — every STFT frame, zero-order-held onto the fixed 100 Hz
  tick grid — and written **directly** into the envelope ring
  (`v3_odf_tracker.py`, a scratch `BeatTrackerV3` subclass that bypasses
  the discrete-event path entirely), not through `_pulse_envelope()`.
  Sample rate is a parameter throughout (`hop = round(rate / 100)`, exact
  at both 48000 Hz and 44100 Hz); all measurements here ran at 48000 Hz,
  matching `track_replay.py`'s own `TARGET_SR` and the rest of this
  bench's convention — not hardcoded, and not the 22050 Hz originally
  (incorrectly) suggested.
- **stock-odf** — the control row. Same E5-patched tracker and same
  direct-ring-write path as **odf**, but the value written is **this
  project's own existing `spectral_flux`** (`unicornviz/audio/
  analyzer.py`'s per-block value, read *before* its own peak-picking/
  adaptive-threshold step) — zero-order-held onto the 100 Hz grid the
  same way (`stock_flux_odf.py`), normalized on the same scale as the
  complex-domain value (`causal_norm.py`) so the two ODF sources are
  comparable. This isolates **write path** (dense continuous vs. sparse
  discrete pulses) from **onset function** (complex-domain vs. this
  project's existing spectral flux) — the two things the odf row changes
  at once relative to stock.

### Drivers and `fed_by`

Two driver scripts: `run_bench.py` (51-track set, `results_51track.json`)
and `run_bench_311.py` (311-track set, `results_311track*.json`). Both
route every row through the single shared dispatcher `run_bench.py`'s own
`stream_for_row()`, which stamps a `fed_by` field onto every per-track
result — `'discrete_events'` for stock/e5, `'direct_ring'` for odf/
stock-odf — and both drivers call `assert_fed_by()` on every row before
writing any output file, raising loudly on any mismatch rather than
producing a silently-wrong table.

**This hardening exists because of a real incident, on the record rather
than left for someone to rediscover from the JSON later:** the first
311-track `stock-odf` run (2026-09-03) had its own inline copy of this
dispatch logic in `run_bench_311.py` that only special-cased `'odf'`,
falling through to `stream_onset_driven` (the discrete-event path) for
every other row name — including `'stock-odf'`, whose tracker class
expects the direct-write path and was never actually fed it. That run
produced Acc1=65.0%/Acc2=88.6%, close to stock and *worse than stock* on
Acc2 — a result that looked like a dramatic reversal of the 51-track
finding and contradicted a written-in-advance prediction, which is
exactly the kind of clean-but-wrong number this project's standing
discipline treats as suspect until checked. It was checked before being
reported anywhere, found to be a dispatch bug, and discarded — not used
in any table in this document. `run_bench_311.py` was fixed to call the
shared `stream_for_row()` instead of reimplementing it, and both drivers
now assert `fed_by` on every row as a standing safeguard against this
exact class of bug recurring silently.

The 51-track `stock-odf` row (below) predates the `fed_by` field, so it
carries no literal tag in its JSON — confirmed instead by reading
`run_bench.py`'s actual `run_row()`, which has always called the shared
`stream_for_row()` (never had its own separate dispatch copy, unlike
`run_bench_311.py`), plus the per-track evidence already gathered before
this incident: 7/51 tracks show p50 values genuinely different from the
`odf` row's (e.g. Tarvona — A Love Without Clockwork: odf=121.21,
stock-odf=179.94) rather than falling back to stock/e5-like behavior,
consistent with an independently-computed direct-write signal, not a
silent fallback to the discrete-event path.

## Results — 51-track set

| Row | Acc1 | Acc2 | Acc1 (22 hard-set) | Acc2 (22 hard-set) | churn raw (mean) | churn smoothed (mean) | lane-hops/min (mean) |
|---|---|---|---|---|---|---|---|
| stock | 60.8% (31/51) | 90.2% (46/51) | 59.1% (13/22) | 90.9% (20/22) | 5.53 | 8.50 | 0.75 |
| e5 | 58.8% (30/51) | 88.2% (45/51) | 45.5% (10/22) | 77.3% (17/22) | 5.26 | 7.74 | 0.67 |
| odf | 70.6% (36/51) | 98.0% (50/51) | 68.2% (15/22) | 100.0% (22/22) | 1.56 | 2.35 | 0.72 |
| stock-odf | 70.6% (36/51) | **100.0%** (51/51) | 68.2% (15/22) | 100.0% (22/22) | **1.39** | **1.92** | **0.40** |

## Results — 311-track / 19-list set

| Row | n | Acc1 | Acc2 | churn raw (mean) | churn smoothed (mean) | lane-hops/min (mean) |
|---|---|---|---|---|---|---|
| stock | 306 | 65.4% (200/306) | 91.2% (279/306) | 5.59 | 8.37 | 0.52 |
| odf | 306 | **76.5%** (234/306) | **96.7%** (296/306) | 1.83 | 2.38 | 0.42 |
| stock-odf | 306 | 75.8% (232/306) | 95.8% (293/306) | 1.44 | **2.03** | **0.31** |

(`stock-odf`'s first two 311-track attempts were both discarded — a
dispatch bug, then a transient decode-failure window — see "Drivers and
`fed_by`" below; this is the third, clean, `fed_by`-verified run, n=306
with the same 5 duplicate-path collapses as every other row here.)

For reference (from `SUMMARY.md`, same 306-track corpus, same reference
ladder): madmom 76.1%/96.1%, BTrack 76.1%/96.4%. **odf-enhanced v3 ties
or edges out both external trackers on this corpus** — the best Acc1/Acc2
combination of anything measured in this whole comparison, on this
project's own tracker. stock-odf is close behind (75.8%/95.8%) and is
actually the *most stable* row measured anywhere in this comparison
(churn smoothed 2.03, lane-hops 0.31) — lower than odf's own churn.

## The headline finding: it's the write path, not (mainly) the onset function

**stock-odf lands on odf, not on e5.** On the 51-track set, stock-odf
(this project's own existing onset function, just written densely and
directly) matches odf's Acc1 exactly (36/51 both) and *beats* it on Acc2
(100.0% vs 98.0%) and both churn measures (1.39/1.92 vs 1.56/2.35).
Verified this isn't a duplicate-data artifact: per-track p50 between odf
and stock-odf is identical on 44/51 tracks and genuinely different on the
other 7 (e.g. Tarvona — A Love Without Clockwork: odf=121.21,
stock-odf=179.94) — independent computations that happen to land at the
same aggregate accuracy.

The E5 row (clock fix alone, still sparse discrete pulses) is *worse*
than stock on both Acc1 and the 22-hard-set (45.5% vs 59.1%) — a known
co-adaptation effect, predicted in advance and confirmed almost exactly
(predicted 2-3 fewer exact matches on the hard set; actual is 3 fewer,
13→10). Only once the ring stops being driven by sparse peak-picked
events — regardless of which function produces the continuous value —
does the big gain appear. So: **a dense, continuously-written onset-
strength envelope beats sparse peak-picked pulses, whichever function
produces the density.** The complex-domain onset function is a measured,
real, non-negative contribution but it is **not the load-bearing
change**; the direct dense-write path is.

**At full 311-track scale, the picture sharpens slightly rather than
staying an exact tie.** stock-odf (75.8%/95.8%) and odf (76.5%/96.7%) are
close but no longer identical the way they were on the 51-track sample —
odf is ahead by 0.7pp on Acc1 and 0.9pp on Acc2, while stock-odf is
*more* stable (churn smoothed 2.03 vs 2.38, lane-hops 0.31 vs 0.42). Read
together: the 51-track sample understated a small real edge from the
complex-domain function (visible directly in the 4/3-lane table below —
stock-odf resolves 8/9 exact, odf resolves 9/9) while overstating how
much stock-odf's stability advantage would hold up (it's real at both
scales, and grows slightly at 311). Both readings from the 51-track
result stand at 311-track scale, just with real numbers attached instead
of an exact tie: **the write path is still overwhelmingly the dominant
effect** (stock: 65.4%→75.8% from the write-path change alone, +10.4pp;
odf over stock-odf adds another +0.7pp on top), and the complex-domain
function is a small, genuine, second-order contributor — worth having,
not worth mistaking for the main event.

## Per-list breakdown (311-track set, Acc1)

| List | stock | stock-odf | odf |
|---|---|---|---|
| ambient-01 | 29% (4/14) | 43% (6/14) | 43% (6/14) |
| big-room-01 | 64% (7/11) | 64% (7/11) | 64% (7/11) |
| curveballs-01 | 100% (8/8) | 100% (8/8) | 100% (8/8) |
| dance-01 | 75% (12/16) | 88% (14/16) | 88% (14/16) |
| deep-house-01 | 73% (8/11) | 91% (10/11) | **100%** (11/11) |
| dnb-01 | 19% (3/16) | **56%** (9/16) | 50% (8/16) |
| downtempo-01 | 43% (6/14) | 57% (8/14) | 57% (8/14) |
| dubstep-01 | 29% (4/14) | 29% (4/14) | 29% (4/14) — **flat across all three, see below** |
| favorites | 88% (49/56) | 95% (53/56) | 95% (53/56) |
| future-house-01 | 88% (14/16) | 88% (14/16) | 94% (15/16) |
| hip-hop-01 | 33% (6/18) | 56% (10/18) | 50% (9/18) |
| house-01 | 93% (14/15) | 93% (14/15) | 93% (14/15) |
| nu-disco-01 | 79% (11/14) | 86% (12/14) | 86% (12/14) |
| prog-house-01 | 77% (10/13) | 92% (12/13) | 92% (12/13) |
| rnb-01 | 14% (1/7) | 43% (3/7) | 57% (4/7) |
| tech-house-01 | 82% (14/17) | 94% (16/17) | 94% (16/17) |
| techno-01 | 79% (11/14) | 79% (11/14) | 86% (12/14) |
| trance-01 | 100% (11/11) | 100% (11/11) | 100% (11/11) |
| trap-hip-hop-01 | 33% (7/21) | 48% (10/21) | 48% (10/21) |

## The ten 4/3-lane house tracks — clean sweep

Identified in `SUMMARY.md`'s madmom analysis (v3 reads 4/3× where madmom
reads exact). **Correction: "Countless" is real and belongs in this
table** — it was reported dropped earlier in this task as a supposed
naming error, which was wrong. The actual file is stylized
`C0UNTLE$$ - Commercial (Original Mix).mp3` (leetspeak, zero-for-O,
dollar-for-S) and a naive case-insensitive substring search for
"countless" against the reference CSV doesn't match that spelling, which
is what produced the false "doesn't exist" finding. Found while
diagnosing the decode-failure incident above (this file showed up in a
skip list under its real name). Confirmed against
`bench_reference_19lists.csv` directly: tag_bpm=100.0,
v3_p50_seed1=132.6 — matches the original claim exactly
("Countless 100→132.6"). Apologies to unicorn-viz-0e for the bad
correction; the original name was right, the search that "verified" it
away was not.

| Track | ref | stock | stock-odf | odf |
|---|---|---|---|---|
| C0UNTLE$$ – Commercial | 100.0 | 125.48 (5:4) | **99.83 (1:1)** | **99.83 (1:1)** |
| Papa Genius – Iron Man | 117.0 | 157.74 (4:3) | **117.08 (1:1)** | **117.08 (1:1)** |
| Booker Forte ft Angelique – Hip Hop Wsdays | 115.0 | 153.42 (4:3) | 121.21 (unrelated) | **115.47 (1:1)** |
| Nicholas Bridgman – What You Think | 100.0 | 134.49 (4:3) | **99.83 (1:1)** | **99.83 (1:1)** |
| Chillz Cagney – Jus Show Love | 115.0 | 117.90 (1:1, near-miss) | **114.67 (1:1)** | **115.47 (1:1)** |
| Alex4beats – Lies | 123.0 | 158.83 (4:3) | **122.90 (1:1)** | **122.90 (1:1)** |
| Sander Wilder – A Part Of Me | 124.0 | 166.73 (4:3) | **123.76 (1:1)** | **123.76 (1:1)** |
| Ma3sc3ol – Angels Tears | 128.0 | 129.91 (1:1, near-miss) | **128.12 (1:1)** | **128.12 (1:1)** |
| Ma3sc3ol – Noite Na Favela | 102.0 | 136.37 (4:3) | **102.63 (1:1)** | **102.63 (1:1)** |
| Vakhtang Iluridze – Filth | 126.0 | 129.91 (1:1, near-miss) | **126.36 (1:1)** | **126.36 (1:1)** |

All ten land exact under **odf**. Under **stock-odf**, nine of ten land
exact — only Booker Forte doesn't fully resolve (121.21 vs 115, an
"unrelated" fold, though notably less wrong than stock's own 4:3 read at
153.42). This is the clearest single piece of evidence that the
complex-domain onset function carries real, if modest, incremental value
over the dense-write path alone: one track in this specific set needed
it to fully resolve.

## dnb-01 — real net gain, but not a clean mechanism

Working hypothesis going in (unicorn-viz-0e): v3's observation is scored
against an ideal beat-train comb, and dnb's fast transients get smeared
by band-weighted spectral flux, weakening the fundamental ACF peak
relative to its half-time subharmonic; a function that preserves
transients should sharpen that peak and flip the half-time preference —
predicted as tracks moving `~` (already Acc2-correct, folded) → `=`
(exact), not `X` → `=`.

51-track set, stock→odf Acc1: 31.2% (5/16) → 50.0% (8/16). 311-track set:
19% (3/16) → 50% (8/16) — consistent between samples.

Per-track grade transitions (51-track set), stock → odf:

| Track | Transition |
|---|---|
| Circuit Haze – William Byron | X → ~ |
| Hplus – Me Feel | **= → ~ (regression)** |
| Hplus – What If | ~ → = |
| Roderic H – Miss You | ~ → = |
| Rodney Kamal Jackson – Turista | ~ → = |
| Route 94 ft Jess Glynne – My Love | ~ → = |
| Sn – No10 Get The Fuck Out | **= → X (regression)** |
| Sn – Witch Turning To Myth | X → = |
| Unsolicited Thoughts – The Day Phil Collins Stopped Caring | X → = |
| d – Kennys Sister | **= → ~ (regression)** |

The hypothesis partly holds — four `~`/`X` → `=` transitions match the
predicted direction — but two of those are `X → =`, not the predicted
`~ → =`, and there are three genuine regressions (`= → ~` or `= → X`) the
hypothesis doesn't predict at all. Net effect is real and reproducible
across both sample sizes, but "the fundamental peak sharpens and the
half-time preference flips" is not the complete mechanism — something
else is moving three tracks the wrong way. An ACF peak-ratio probe (true
lag vs. half lag) for the four fixed dnb tracks was considered but not
built — not cheap given the existing harness, and the per-track table
already answers the question this benchmark can answer; a real mechanism
study would need new instrumentation.

## dubstep-01 — flat, and it's a genre-shape issue, not a miss

Acc1 unchanged, 29% (4/14) across all three rows — stock, odf, **and**
stock-odf. Per-track (311-track set, stock vs odf shown; stock-odf lands
on the same grade as odf for all 14):

| Track | ref | stock | odf |
|---|---|---|---|
| Black Majestic – We In The Know | 125.0 | 127.24 (=, 1:1) | 124.62 (=, 1:1) |
| Cosme De La Cruz – Clash | 97.0 | 129.91 (~, 4:3) | 121.21 (~, 5:4) |
| Cosme De La Cruz – Now | 75.0 | 121.21 (X, unrelated) | 150.26 (~, 2:1) |
| DJ Ouijah – Ouijah Says | 91.0 | 122.05 (~, 4:3) | 122.90 (~, 4:3) |
| Daniel Brink – Midmix | 83.0 | 166.73 (~, 2:1) | 165.58 (~, 2:1) |
| Dmstry ft Temwani Daka – Soar | 143.0 | 141.18 (=, 1:1) | 140.20 (=, 1:1) |
| Hvrcrft – X Layne Tadesse Champion | 150.0 | 149.23 (=, 1:1) | 150.26 (=, 1:1) |
| Kingston Ray – Street Dance Choko | 97.0 | 130.81 (~, 4:3) | 129.01 (~, 4:3) |
| Kuhlosul – Nocturnal | 70.0 | 142.16 (~, 2:1) | 140.20 (~, 2:1) |
| Rico21 – Silence | 70.0 | 139.23 (~, 2:1) | 140.20 (~, 2:1) |
| Rory David – Take Me To Hell | 71.0 | 141.18 (~, 2:1) | 140.20 (~, 2:1) |
| S1ms – U | 72.0 | 145.15 (~, 2:1) | 144.14 (~, 2:1) |
| Tatiana Kurtukova – Matushka | 94.0 | 127.24 (~, 4:3) | 125.48 (~, 4:3) |
| Xygnomus – Time | 140.0 | 141.18 (=, 1:1) | 140.20 (=, 1:1) |

13 of 14 "misses" are clean 2:1 or 4:3 (one 5:4) folds — tag BPM sits at
the half-time feel while both trackers converge on the same double-time
pulse, consistently, in both rows. This is the expected bimodal-genre
pattern this project's own audio profiles already carry a widened hint
band for, not a detector failure either row can fix — both stock and odf
agree on which metrical level they're reading, they just disagree with
the tag. One track (Cosme De La Cruz – Now) moved from a genuinely
unrelated fold (X) to a valid fold family (~) under odf — a real if
minor improvement that doesn't cross into Acc1.

## Churn — fewer wobbles, not fewer lane changes

51-track set: lane_hops/min barely moved (stock 0.75 → odf 0.72) while
both churn measures dropped ~3.5×: raw 5.53 → 1.56, smoothed 8.50 → 2.35.
Since lane-hops (>20% jumps — genuine tempo-family changes) stayed
essentially flat while the smaller-threshold churn metrics collapsed,
**the tracker isn't deciding on a different tempo family less often — it
re-estimates within whichever family it's already on far less.** This
matters for what a live director actually perceives: fewer real lane
changes was never the mechanism here, tighter within-lane stability was.

## Limitations

- **No `_V2_*`/`_V3_*` constant was retuned** at any point in this
  measurement — every row uses stock v3 decision logic (transition
  weights, lock/release thresholds, tactus preference) unchanged. A
  proper re-tune, informed by this data, is explicitly Program B step 3,
  not part of this measurement.
- **Replay clock, not live audio.** All runs go through this bench's
  accelerated-replay harness (ffmpeg-decoded files, fixed-size blocks fed
  in a loop), not live PipeWire capture — consistent with every other
  measurement in this comparison, but real-time jitter/dropout behavior
  isn't exercised here.
- **dubstep-01 is flat** — this swap doesn't help genuinely bimodal
  material where both trackers already agree on which metrical level
  they're reading.
- **dnb-01's mechanism isn't fully explained** — real net gain, but three
  per-track regressions the leading hypothesis doesn't predict; treat the
  aggregate number as solid and the "why" as still open.
- **The complex-domain onset function turned out non-load-bearing** for
  the *headline* gain (write path dominates), though it's not zero —
  stock-odf and odf differ per-track in both directions even where their
  aggregates coincide. Whether the specific function matters more once a
  real re-tune is in place (rather than stock decision logic held fixed)
  is untested here.

## License

BTrack's C++ source was not read or copied for the onset function in
this task — the complex-domain algorithm (Bello et al. 2004) is a
published, independent technique; `complex_onset.py` was reimplemented
from the paper's own description. It turned out to be non-load-bearing
for this measurement's headline result anyway (the dense-write path
dominates), so this task doesn't create any GPL-adjacency question for
`beat_grid.py` either way. Everything under `tools/beat-tracker-bench/
onset-prototype/` is dev-only benchmarking, same as the rest of this
comparison — never imported by the shipped app or `drop-ins/auto-vj-01/`.
