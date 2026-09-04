# Detector scorecard — unicorn-viz vs. the field

Owner: dev tooling, `tools/beat-tracker-bench/`. Status: living document —
update when a new run changes a number, don't let it go stale. Last
updated: 2026-09-03, after Program B step 2 (the onset-prototype).

This is the one-page answer to "how are we doing against everyone else."
Full methodology, per-genre breakdowns, and per-track tables live in
`SUMMARY.md` and `onset_prototype.md` — this doc is the scorecard, not
the write-up.

## Scope and methodology

All accuracy numbers below are the **306-track / 19-genre corpus**
(`bench_reference_19lists.csv`, 311 CSV rows, 5 duplicate paths collapse
to 306 unique tracks — every model here is scored against the exact same
tracks, same reference ladder, same fold/tolerance rules) unless a row's
notes say otherwise. Acc1 = within ±4% of reference; Acc2 = ±4% of a
fold-related tempo (2×, ½×, 3/2×, 2/3×, 4/3×, 3/4×). Churn = mean
`flips_per_min_smoothed` (>4% jumps on a 2s rolling median of the bpm
stream) — lower is better, this is re-estimate jitter, not accuracy.

**v3's rows here are measured through this bench's own replay harness**
(`onset-prototype/run_bench_311.py`), not unicorn-viz-0e's own production
seed-run numbers cited elsewhere in `SUMMARY.md` (66.0%/88.9%, close but
not identical — different harness, same tracker). Using this bench's own
measurement for every row, v3 included, keeps the whole table apples-to-
apples: one scoring pipeline, one set of fold rules, no cross-harness
mixing.

## The scorecard

| Detector | Real-time capable? | Acc1 | Acc2 | Churn (mean) | License | Shippable in unicorn-viz | **Grade** |
|---|---|---|---|---|---|---|---|
| **v3 + dense envelope, complex-domain onset** *(prototype)* | Yes — native | 76.5% | 96.7% | 2.38 | ours | Pending re-tune (Program B step 3) | **A** |
| **BTrack** (custom streaming bindings, this project's own) | Yes — true causal | 76.1% | 96.4% | 2.03 | GPL-3.0 | No — copyleft | **A** |
| **v3 + dense envelope, stock onset** *(prototype, control row)* | Yes — native | 75.8% | 95.8% | 2.03 | ours | Pending re-tune (Program B step 3) | **A-** |
| **madmom** (`DBNBeatTrackingProcessor`) | Yes — true causal | 76.1% | 96.1% | 4.56 | BSD code / CC BY-NC-SA weights | No — weights non-commercial | **A-** |
| **v3 (stock)** — *currently shipped* | Yes — native | 65.4% | 91.2% | 8.37 | ours | Yes — already shipped | **B-** |
| **Essentia** (`RhythmExtractor2013`) | No — buffer-rerun, not true streaming | 58.8%¹ | 94.1%¹ | n/a¹ | AGPL-3.0 | No — copyleft + not real-time | **C** |
| **v2** — *legacy, superseded* | Yes — native | 36.5%² | 90.4%² | n/a | ours | Superseded by v3 | **D** |
| **BeatNet** | No — couldn't complete even one clip at a usable rate | — | — | — | CC BY 4.0 (atypical) | No — not real-time, unclear terms | **Incomplete** |

¹ Essentia only ever completed the 51-track set (its own pace — ~415s/
track — ruled out the full 306-track run as impractical even capped).
Numbers shown are from that 51-track run, not directly comparable to
every other row's 306-track figure.
² v2's 306-track number has only n=52 coverage (partial — v2 numbers
weren't collected for every track in this corpus), read with that
caveat; its 51-track number (52.9%/92.2%, full coverage) is more
trustworthy and is what `SUMMARY.md`'s madmom/BTrack tables cite.

## Grading rubric

Grade = accuracy tier + stability tier, real-time capability as a hard
gate (a detector that can't run causally can't be a live candidate for
this project regardless of its offline accuracy, so it's capped
regardless of score).

- **Accuracy tier** (Acc1 on the 306-track set): ≥75% → A, 65–74% → B,
  50–64% → C, <50% → D.
- **Stability tier** (mean churn, smoothed): ≤3 → A, 3–6 → B, 6–10 → C,
  >10 → D.
- **Gate**: not real-time-capable → capped at C regardless of the above.
- Grade shown is the two tiers combined (roughly averaged, judgment call
  at the boundary) — this is a rough ranking aid, not a precise formula;
  read the actual numbers, not just the letter, before acting on this.

Shippability (license + real-time capability) is tracked separately and
does **not** factor into the grade above — a GPL-licensed detector can
still earn an A on technical merit while being a hard no for this
project. Don't let a good grade read as "we could ship this."

## How we're doing

**The honest read: currently-shipped v3 is solid mid-pack (B-), and the
Program B prototype — architecture change only, zero tuning-constant
retuning — already ties for the top grade in this whole comparison,
ahead of madmom, on par with a custom-built BTrack integration neither
of which this project can actually ship (license).** That's the real
headline: the prototype isn't "catching up to state of the art," it's
already there, using this project's own decision logic unchanged.

- **v3 (stock) → v3 (prototype)** is the single biggest jump in this
  table: +10.1 to +11.1pp Acc1, +4.6 to +5.5pp Acc2, and churn dropping
  from "worst in the field" (8.37) to "best or tied-best" (2.03–2.38) —
  see `onset_prototype.md` for why (it's mostly the write path, not the
  onset function specifically, though the function does carry a small
  real increment — see the 4/3-lane track table there).
- **Against the two real external competitors that are actually
  real-time-capable** (madmom, BTrack) — this project's prototype ties
  or edges both out on every measured axis. Neither of them can be
  shipped here regardless (GPL-3.0, non-commercial weights), so this
  isn't "we should use their code" — it's "our own architecture, once
  the envelope-writing bug is fixed, performs at the same level as the
  field's best openly-available options."
- **Essentia and BeatNet are not real competition for this project's use
  case** — neither is genuinely real-time, and BeatNet couldn't complete
  the benchmark at a usable pace at all. Their grades reflect that; don't
  read Essentia's 58.8% as "worse than v3 stock" without the real-time
  caveat attached — it's not in the same category of tool.
- **What's not yet true**: the prototype rows are stock-constants
  measurements of an architecture change, not a shipped result. Program B
  step 3 (the actual re-tune, routed to the training seat) is what turns
  this row from "look what's possible" into "what we ship." Until then,
  the honest grade for what a user actually runs today is v3 (stock)'s
  B-, not the prototype's A.

## Update log

- **2026-09-03**: initial scorecard, built from the overnight OSS
  comparison (madmom, BTrack, Essentia, BeatNet) plus Program B step 2
  (the onset-function prototype). All 306-track numbers recomputed
  directly from each model's own results JSON for this table, using one
  consistent scoring pass — see `SUMMARY.md`/`onset_prototype.md` for the
  original per-model write-ups this consolidates.
