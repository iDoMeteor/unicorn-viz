# OSS beat-tracker comparison — summary

Dev-only benchmarking, `tools/beat-tracker-bench/`. Reference ladder and
scoring convention (Acc1 = within ±4% of reference; Acc2 = ±4% of a
fold-related tempo — 2×, ½×, 3/2×, 2/3×, 4/3×, 3/4×) per unicorn-viz-0e's
methodology. Full per-track tables linked inline; this file is the
narrative.

**`time_to_move_2pct_s`** replaces the earlier `first_lock_s` metric
throughout this doc: seconds from a tracker's first nonzero tempo
estimate until that estimate first moves more than 2% away from its own
initial value. `first_lock_s` measured "time until one hop of audio was
processed," which two models (BTrack's built-in 120.0 BPM prior,
Essentia's rebuild-cadence floor) turned into a misleadingly fast,
uninformative number rather than a real detection latency — see each
model's section for what that artifact looked like before the fix.

## Madmom (`DBNBeatTrackingProcessor(online=True)`) — the headline result

Two runs, same reference ladder and metric set, consistent result on both:

| Set | n | Acc1 | Acc2 | v3 Acc1 | v3 Acc2 | v2 Acc1 | v2 Acc2 |
|---|---|---|---|---|---|---|---|
| 51-track hard-set + house-01 + dnb-01 | 51 | 76.5% | 96.1% | 64.7% | 84.3% | 52.9% | 92.2% |
| Full 19-list / 311-track set | 306 (5 dup paths collapsed, see note below) | 76.1% | 96.1% | 66.0% | 88.9% | 36.5% (n=52, partial coverage) | 90.4% |

Full tables: `madmom_table.csv` (51-track), `batch_311_madmom_table.csv`
(311-track, one row per list in the `list` column).

**The 4/3-lane finding (the single most actionable result of the whole
bench):** cutting the 311-track run by genre and reading the house-family
gap specifically (unicorn-viz-0e's cut of the raw JSON), the shortfall is
almost entirely one specific tempo lane. Nine house-family tracks at
100-126 BPM tag that v3 reads at 4/3× (133-169 BPM) — madmom reads every
one of them exact. Independently verified against this run's own raw JSON
before repeating it: Papa Genius (117→madmom 117.65 / v3 157.7), Booker
Forte (115→115.38 / 152.4), Bridgman (100→100.00 / 133.6), Chillz Cagney
(115→115.38 / 154.5), Alex4beats (123→122.45 / 164.4), Sander Wilder
(124→125.00 / 166.7), Ma3sc3ol (102→101.69 / 137.3), Vakhtang
(126→125.00 / 169.1) — all confirmed, plus six more near-misses where v3
sits 4-7% high. On the tracks where madmom reads exact, its median
p50/reference ratio is 1.0000; v3's is 1.0127 — madmom shows no
systematic tempo bias on this set, v3 reads +1.27% high on real music in
replay. This +1.27% is a separate, already-diagnosed issue from the
4/3-lane finding above, not a symptom of it: it's a timing bug in the
shared v2/v3 onset envelope (onset ticks lose their tail and the pulse
writer steals part of a 10ms step, so the envelope is written at ~96Hz
against a nominal 100Hz), diagnosed overnight and recorded as ADR entry
E5 (`docs/adr/vj-system.md`, commit `32b7fb9`), fix parked behind a
strict-xfail regression test. It's upstream of both v2 and v3, not a
tempo-lane decision, and independent of the 4/3-lane finding above. Per
unicorn-viz-0e: the 4/3-lane gap itself points at the *observation*
function (the learned beat-activation model) as the source of the gap, not the
tempo-lane/tactus logic — the two engines agree closely on the tracks
where the observation signal is clean (house/tech-house/trance), and
diverge specifically where v3's spectral-flux onset envelope is
structurally weaker (confirmed elsewhere as not being able to resolve
this particular ambiguity from the onset envelope alone, in either
direction).

**Where madmom is weaker, and why it's not really weaker:** the
lowest-Acc1 genres (dubstep 29%, trap-hip-hop 38%, ambient 43%,
downtempo 50%) are exactly the half-time-tagged genres, where most
"misses" are folds, not errors — Acc2 recovers nearly all of them
(dubstep 93%, trap-hip-hop 90%, downtempo 86%, ambient 71%). On these
specific hard genres madmom and v3 track closely together (dubstep tied
exactly at 29% each); the real accuracy gap is concentrated on the clean
4-on-the-floor genres where the observation function has the least
ambiguity to resolve (deep-house +18pt, prog-house +23pt, tech-house
+18pt over v3).

**Churn:** smoothing over a 2s rolling median collapses raw per-beat DBN
re-estimate jitter into numbers close to v3's own baseline (~2-7/min) —
median flips_smoothed/min = 2.4 (311-set) / 2.5 (51-set), median
lane_hops/min (>20% jumps on the smoothed stream — genuine lane changes,
not jitter) = 0.8 (311-set) / 1.0 (51-set). The raw, unsmoothed number
(median ~22-25/min) looked alarming in isolation but is mostly jitter,
not real octave/lane hopping.

**Lock genuineness:** median `time_to_move_2pct_s` = 0.50s (51-track,
n=51, no track ever failed to move) — madmom's first estimate is a real,
varying-per-track detection (DBNBeatTrackingProcessor's state space is a
roughly uniform grid over 55-215 BPM, not a peaked default toward one
"typical" tempo, unlike BTrack below), but the value at that first instant
is only Acc2-correct ~33% of the time — it's an early, frequently-wrong
guess that needs ~2s of smoothing before it's trustworthy, then moves on
from there (hence a ~0.5s median time before it moves again by >2%).

**Data-hygiene note:** 5 of the 311 CSV rows point at tracks that also
appear in `favorites` (Careless Whisper Nylze Remix, Say My Name DJ R./
Robert Miles, Scenpha Tribal Essence, Kaboom Blackout Riddim, Moli
Almeria Push That Pedal) — since results are keyed by file path, the
second occurrence overwrote the first. No analysis was lost (deterministic
result either way), but each only counts under one list in the per-list
breakdown rather than both.

## BTrack (custom pybind11 streaming bindings, causal C++ core)

Adam Stark's BTrack (GPL-3.0) had no streaming API bound to Python
upstream at all — custom bindings were written for this project exposing
its real causal `processAudioFrame`/`getCurrentTempoEstimate` API. Also
run on both sets, same reference ladder and metric set as madmom.

| Set | n | Acc1 | Acc2 | v3 Acc1 | v3 Acc2 | v2 Acc1 | v2 Acc2 |
|---|---|---|---|---|---|---|---|
| 51-track hard-set + house-01 + dnb-01 | 51 | 64.7% | 94.1% | 64.7% | 84.3% | 52.9% | 92.2% |
| Full 19-list / 311-track set | 306 (same 5 dup paths as madmom) | 76.1% | 96.4% | 66.0% | 88.9% | 36.5% (n=52) | 90.4% |

Full tables: `btrack_51_table.csv`, `batch_311_btrack_table.csv`.

**The headline this result adds:** BTrack ties madmom exactly on the
311-track Acc1 (76.1% each) and edges it on Acc2 (96.4% vs 96.1%), while
essentially never lane-hopping (median lane_hops/min = 0.0 vs madmom's
0.8). This is a classic hand-designed comb-filter/autocorrelation tracker
with a phase-aware complex-spectral-difference onset function (Bello et
al.) and zero learned/trained component, landing at the *same* accuracy
ceiling as a modern RNN-observation DBN tracker, while beating it on
stability. Two tracker classes with nothing in common except "causal,
real-time" converging on ~76% says the ceiling on this corpus is set by
the observation signal itself, not by which tracker architecture consumes
it — and that BTrack reaches it with a hand-designed onset function (no
training data, no learned activation) suggests a cheaper first lever than
a trained model, if this project ever wants to close the gap with v3:
improving the onset/observation function itself, not swapping tracker
architectures.

**One sharp, specific weakness — not a general one.** dnb-01 is
BTrack's worst genre by far: 31% Acc1 (5/16), but 100% Acc2 (16/16) — a
clean, consistent half-time fold on fast material, not noise, and it
matches a 174 BPM synthetic click track locking half-time in this
adapter's own self-test. Verified against BTrack's actual source: it
hardcodes an 80-160 BPM search range internally (a fixed 41×41 tempo
transition matrix, Gaussian-initialized, with bin-index math tied
directly to the literal `80`/`160` bounds throughout `BTrack.cpp`) — not
exposed as a parameter anywhere, upstream or in this project's bindings.

**Tempo-range-widening experiment: configuration ceiling, partially
confirmed, not a free fix.** Widened the lattice to 55-211 BPM (79 bins,
kept the original 2 BPM/bin step and 10 BPM transition-width rather than
rescaling it) and reran dnb-01: Acc1 31.25% → 56.25% (5/16 → 9/16), four
tracks fixed in the 160-174 BPM band the widening targeted — the
hypothesis was partly right. But a full synthetic sweep found a real
regression the original range didn't have: 155-170 BPM now intermittently
folds to half-time mid-track (a per-tick trace showed 160 BPM locking
correctly, then flipping at t=2.62s and never recovering), which a
side-by-side run against a fresh unmodified clone on identical seeds
confirmed was not present before. Root cause: in the original 41-bin
lattice, 160 BPM sat at the very edge with nowhere to drift *up* into —
some of the old range's apparent robustness at its ceiling was edge-
pinning, not genuine stability (worth remembering when reading any
tracker's robustness near its own range's edge, including this project's
own — v3's 55-210 lattice has no pinning there, consistent with v3
reading dnb at 50% without a fold). Because the change regressed a
previously-solid range, it was reverted; the live BTrack build here is
the original, unmodified 80-160 BPM version. A narrower variant (widen
only the upper bound, leave 80 as the floor) was not attempted. Full
sweep tables and the per-track dnb before/after are in
`btrack/README.md`.

**Lock genuineness — same class of artifact as Essentia's constant
2.00s, caught the same way before it was reported as a real number:**
`first_lock_bpm` is exactly `120.0` on all 51/51 tracks (BTrack's own
built-in tempo prior, returned before any real evidence is processed —
confirmed in the adapter build) — the old `first_lock_s` metric (median
0.02s) was measuring "time until one hop was processed," not "time until
a genuine estimate appeared." Corrected: median `time_to_move_2pct_s` =
0.48s (51-track, n=51, no track ever failed to move) — almost identical
to madmom's 0.50s. Once the built-in-prior artifact is corrected for,
these two structurally unrelated trackers reach a genuine estimate at
essentially the same real-world speed.

**License:** GPL-3.0 — cannot be vendored or bundled into the shipped
app under any circumstances. The onset function itself (Bello et al.'s
complex spectral difference) is a published algorithm, not
BTrack-specific code — reimplementable from the paper if this approach
is ever wanted inside the actual product, independent of BTrack's own
GPL code.

## Essentia (`RhythmExtractor2013(method='degara')`, buffer-rerun adapter)

51-track hard-set + house-01 + dnb-01 only (not run against the full 311 —
its ~70-80s-per-30s-of-audio pace made that impractical overnight even
capped).

| n | Acc1 | Acc2 |
|---|---|---|
| 51 | 58.8% | 94.1% |

Between v2 (52.9%) and v3 (64.7%) on Acc1, close to both on Acc2 (v2
92.2%, v3 84.3%). Reasonable accuracy for an offline dev-tool signal.

**`first_lock_s` is not a real per-track number for this model — confirmed,
not just suspected.** All 51/51 tracks report exactly `2.00s`, zero
variation. This is the floor of the adapter's rebuild-every-~1s cadence
(it needs roughly two rebuild cycles' worth of buffered audio before its
first nonzero output), not a genuine onset-driven detection latency.
Don't use Essentia's first-lock number in any live-usability comparison.

Full table: `essentia_51_table.csv`.

## BeatNet — deferred

Killed for the night on owner instruction after failing to complete even
a single 120s clip at a usable rate; not restarted. Its buffer-rerun
approach (re-running the online algorithm over the whole buffer-so-far
every 0.5s) scales badly with clip length. Per the original scoping
call: "needs >3x realtime, not a live candidate" regardless of accuracy —
not picked back up unless there's a specific reason to.

## BTrack — blocked

Core C++ library builds cleanly (confirmed after the owner cleared the
`libsamplerate-devel` system dependency). The official Python bindings
module has one further, unrelated, trivial compile bug (`std::copy_n`
used without `#include <algorithm>`, a GCC-version portability issue) —
not yet patched. Deeper problem, independent of that bug: the official
bindings only expose batch functions; the underlying C++ class's real
streaming API (`processAudioFrame`/`getCurrentTempoEstimate`) was never
bound to Python at all. Getting a streaming adapter would mean writing
custom pybind11 bindings — separate, not-yet-approved scope. Not
benchmarked.

## Shippability

See `shippability_matrix.md` for the full per-model license/
streaming-capability/ship-verdict table. One-line version: madmom's
architecture (BSD) is shippable, its current pretrained weights (CC
BY-NC-SA 4.0) are not; the other three are all blocked on copyleft
(BTrack GPL-3.0, Essentia AGPL-3.0) or atypical terms (BeatNet CC BY 4.0)
regardless of accuracy.
