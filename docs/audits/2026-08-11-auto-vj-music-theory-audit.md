# Auto VJ Music-Theory & Algorithms Audit (2026-08-11)

Owner: unicorn-viz
Status: complete — findings awaiting owner review; no code changed by this audit
Last updated: 2026-08-11

Scope: `drop-ins/auto-vj-01/` (detector `beat_grid.py`, director + recommender
`auto_vj.py`), the shared analyzer path they consume
(`unicornviz/audio/analyzer.py`, `unicornviz/audio/profiles.py`), and — as the
requested priority — the drop-score redesign plan
(`docs/planning/auto-vj-drop-score-redesign-plan-2026-08-11.md`). Focus is
music-theory and DSP/algorithm accuracy and the methodology used to tune and
validate them, not code style. Versions audited: detector `1.0.0-rc.7`,
director `1.0.0-rc.3`, recommender `1.0.0-rc.8`, weights doc v23 (verified in
sync with all three constants).

External references were checked live for this audit (all verified to exist
and to say what the plan says they say):

- Foote (2000), *Automatic audio segmentation using a measure of audio
  novelty* — checkerboard-kernel novelty on a self-similarity matrix; the
  foundational boundary-vs-state distinction.
- TISMIR, *A Basic Tutorial on Novelty and Activation Functions for Music
  Signal Processing* — novelty (change) vs activation (state) as distinct
  function families.
- EDMFormer (arXiv 2603.08759) — EDM-specific structure segmentation;
  drop = peak-energy *state* with "main rhythm motifs and basslines,"
  buildup = rising *trend*, boundary detection scored separately.
- **Yadati, Larson, Liem & Hanjalic (ISMIR 2014), "Detecting Drops in
  Electronic Dance Music"** — not cited in the plan, and it is the closest
  prior art to this exact problem. Key takeaways below.
- Moelants / van Noorden — preferred-tempo resonance peaking ~120-128 BPM
  (grounds the detector's 120 BPM perceptual prior).
- Butler (2006), *Unlocking the Groove* (via Yadati's definition) — the
  musicological reference for build → drop → bassline-reintroduction form.

The Yadati paper matters enough to summarize: they define the drop as **"the
point where the buildup ends and the bassline is re-introduced"** (expert
ground truth was hand-labeled at exactly that point), detect it two-stage
(structure segmentation first, then classify which boundaries are drops using
spectrogram/MFCC/rhythm features around the boundary), and score with a
tolerance window. Their best average F1 is **0.71 with a ±15s window, ~0.61 at
±3-5s — offline, with a trained classifier**. Two implications for this
project: (1) the plan's trigger/sustain split and bassline-reintroduction
framing match the strongest published definition of the task; (2) a causal,
no-lookahead detector should expect meaningful error rates even after the
redesign — the right response is the plan's existing sim-first discipline,
with better metrics (see M2).

---

## Verdict up front

The redesign plan's core moves are **correct and well-grounded**: the
trigger/sustain split matches how the literature separates boundary detection
from section classification; the bass-suppression → slam-back trigger matches
both production convention and the mixer's own proven offline feature family;
the weight-revert and separation-of-concerns decisions are sound. The plan's
citations check out. Nothing in it is directionally wrong.

The audit found one root-cause issue the plan stops short of (F1: the level
signal is destroyed *before* `_shape()` ever runs), one piece of the plan that
would misfire as written (F2: the relative fizzle check against the current
composite), one proposal whose stated mechanism is ambiguous-to-inverted (F4:
the asymmetric-alpha direction), and several pre-existing defects in the
director/detector worth fixing while this area is open (F5-F8).

---

## What is solid (verified, no action needed)

- **Tempo estimation architecture** (v2/v3): ACF of a 100 Hz onset envelope
  with an aubio/Scheirer-style harmonic comb (summing 2x/3x/4x lags at 1/h
  weight), a log2-Gaussian perceptual prior centered at 120 BPM
  (octave-symmetric — the correct space for tempo priors; the linear-space
  under-weighting bug this replaced is documented at
  `beat_grid.py:_setup_acf_arrays`), tactus fold-down toward the 100-130
  danceable-pulse range, and harmonic-rival exclusion in the confidence
  peak-ratio (`_acf_rival_score` — musically correct: a clean 4/4 pulse's
  harmonics agreeing with itself is confirmation, not competition).
- **Genre BPM priors** (`profiles.py`): house 122, deep house 115, tech house
  130.5, peak-time 130, trance 138, psytrance 145, hard techno 148, hardstyle
  150, DnB 174, dubstep 140, rap/R&B 85 — all within genre convention.
  (Tech house 130.5 sits at the top of the usual 125-130 window; fine as a
  prior, worth a glance if tech-house sessions ever read fast.)
- **Onset detection** (`analyzer.py`): half-wave-rectified spectral flux on
  the **raw, pre-normalization** spectrum (with the reason documented in
  place), median + k·MAD adaptive threshold (robust where mean+std collapses
  on steady material), local-max gating, BPM-adaptive refractory at 0.7 of
  the beat period. This is textbook-good causal onset detection.
- **Phase-locked oscillator** (Large & Kolen lineage): bounded per-beat nudge,
  tolerance-gated coherence confidence, off-grid onsets structurally unable to
  corrupt tempo. The `_V2_PHASE_TOL` 0.08-revert story (estimated-BPM residual
  keeping a perfect click track outside tolerance forever) is a correctly
  diagnosed and correctly documented failure.
- **Phrase clock**: 8/16/32-bar expectations and the 8-bar boundary bonus
  match EDM phrase convention (Butler); external-hint bias scaled by
  confidence × proximity, mismatch at half weight, neutral window after track
  changes — musically sensible, and every term is corpus-logged.
- **Recommender structure**: per-term Gaussian log-density fits summed under
  weights is a legitimate naive-Bayes-shaped composite; softmax margin for the
  confirm decision is the right fix for cross-session comparability; the
  6-sigma clip, the sigma-floor split from the detector's floor, and the
  dead-`top_cand_fit` fix are all correctly reasoned. The 2026-08-11 centroid
  basis fix (live centroid now computed in the same 64-log-band basis as
  `spectral_centroid_mu`) closes a real apples-to-oranges bug correctly.
- **Methodology**: the sim-first discipline (replay against `favorites/e` /
  `library/b`, ship only on measurable improvement on both real-drop coverage
  and the false-positive proxy) is the right process, and the
  V3/V4/V5/V6 negative results being written down is exactly how this should
  work. Caveats in M1-M3.

Plan line-reference spot-checks: `auto_vj.py:3332-3336` (fizzle gate) ✓,
`beat_grid.py:221`/`:896` (both `0.7/0.2/0.1` blends) ✓, `analyzer.py:534`
(`mid_flux` computed, never consumed by drop_score) ✓, no `treble_flux`
anywhere ✓, six named `bass_n`-consuming effects ✓, `_drop_peak_score` running
max at `auto_vj.py:3305` ✓.

---

## Findings

Ranked by how much they should shape the redesign.

### F1 — The level signal is destroyed before `_shape()` runs: per-frame peak normalization is the deeper root cause

Plan section 1 diagnoses `_shape()`'s saturating gain as the reason `bass`
has no dynamic range, and proposes an unshaped or gently-shaped detector
channel built from `bass_weighted`. But `bass_weighted` is derived from
`self._smoothed`, and `_smoothed` is built from the spectrum **after** it is
divided by its own per-frame maximum (`analyzer.py:556-559`, `spectrum /=
max_val`) and multiplied by `sqrt(energy)` — where `energy` is the silence
gate `clip((rms - 0.006) / 0.045)`, which saturates at 1.0 for any signal
louder than rms ≈ 0.05, i.e. for essentially all music. So the "band level"
entering `_shape()` is a **spectral-shape fraction** ("how much of this
frame's loudest bin's magnitude does the bass band average"), not a level.
Absolute level information is gone before the gain curve ever touches it.

Two consequences:

- Inverting the plan's own reported medians through `_shape()` (gain 6.6):
  BREAKDOWN 0.967 → raw 0.517; peak modes 0.983 → raw 0.617. The unshaped
  channel therefore *does* discriminate (≈19% relative spread vs 1.6%
  shaped) — the plan's direction helps — but its ceiling is set by the
  normalization, not the exponential. Don't expect breakdown/drop separation
  much better than that from any reshaping of this input.
- The codebase already learned this exact lesson once: flux is deliberately
  computed from the raw spectrum, with a comment explaining that per-frame
  normalization erases the kick transient because the *shape* barely changes
  when the *magnitude* does (`analyzer.py:512-518`). The band levels never
  got the same fix.

**Recommendation:** build the detector's new channel from the
pre-normalization magnitudes — the same raw path `flux`/`bass_flux` already
read. Concretely: per-frame `bass_level_raw = log1p(mean(raw_spectrum
[bass_slice]))` (log compression for perceptual scaling and headroom, no
per-frame max division), optionally profile-weighted, EMA-smoothed. The
loudness-invariance job the per-frame normalization was doing for effects
("a quiet master still looks alive") gets done instead by the normalization
layer the redesign already plans on top (asymmetric baseline / percentile —
see F4), which adapts over minutes, not per frame. This is the same design
the mixer's offline analyzer uses (`structure.py`: per-bar RMS,
**rank-normalized over the track**, never per-frame).

If a shaped channel is still wanted for continuity: from the plan's own
numbers, the empirical gain that centers the current median at 0.5 is
`ln(2)/0.556 ≈ 1.25` — the plan's suggested 0.5-1.0 range is slightly low,
and at gains that small the curve is near-linear over the operating range
anyway, which is the argument for skipping the curve entirely and letting
the normalization layer do the work.

### F2 — The relative fizzle check (`peak * 0.9`) will misfire on healthy drops unless it reads the *new sustain signal*, and only that

Two pieces of the project's own recorded evidence:

- The 2026-08-11 ADR addendum's synthetic constant-input test: a held,
  *unchanging* drop decays ~24% (0.712 → 0.540) under the current composite
  from `band_blend` renormalization alone. A −10%-from-peak exit on this
  signal exits a perfectly healthy drop in seconds.
- The same addendum's corpus finding: `drop_score` at fire time averaged
  0.679 with 65% of fires below their own threshold, purely from
  schedule→downbeat decay — the composite routinely moves >10% on the
  timescale of a bar.

Additionally, the composite is beat-rate spiky by construction:
`bass_flux_fast`'s release retains 0.85/frame, which across a single
inter-kick gap at 120 BPM / 60 fps is 0.85³⁰ ≈ 0.008 — the term is
effectively per-kick impulses, partially masked by the `x/(x+0.05)`
compression. "More than 10% below this drop's own peak" is a condition the
current drop_score satisfies transiently between kicks of a full-power drop.

**Recommendation:** the relative fizzle is sound *only* as a consumer of the
redesigned sustain signal (slow, level-based, non-renormalizing). Sequence it
accordingly: it cannot land in the "decided, could land independently"
bucket (plan section 6) while `_drop_fizzle_score`'s input is today's
composite — it depends on 4c's primitive. Additionally:

- Keep an absolute floor (`max(peak * 0.9, floor)`) as the plan already
  flags, to preserve the weak-drop early exit.
- Express the fizzle grace period in **bars** (via the grid), not only
  seconds, so the check is musically synchronized across tempi — the
  existing `_timing_scale_from_bpm()` is the precedent.
- Consider requiring the below-threshold condition to hold for N consecutive
  evaluations (or a 1-2 bar EMA) rather than a single frame, regardless of
  which signal feeds it.

### F3 — Trigger draft (4a): the multiplication is less brittle than the plan fears, but the new term needs a normalization and the mid+treble definition is not what the code computes today

On the plan's open question "is `bass_flux_norm * midtreb_activity_fast` too
strict / does it need a coincidence window": **the asymmetric EMAs already
are the coincidence window.** `bass_flux_norm`'s slow release holds a bass
hit's value for several frames; `midtreb_activity_fast`'s slow release does
the same for the riser/roll activity. A lead/lag of a frame or two in either
direction survives the product. A same-instant requirement would only exist
if both were raw per-frame fluxes. No separate window mechanism is needed in
v0; evaluate the product a few frames after the bass onset (which the
scheduling path already effectively does) and the pre-drop silence gap
(1-2 beats of near-silence before the impact, common in modern production)
is also covered — the fast attack re-raises `midtreb_activity_fast` within a
frame or two of the drop's own broadband hit.

Two genuine gaps in the draft as written:

1. **`midtreb_activity_fast` has no normalization specified.** `bass_flux_norm`
   is bounded by `x/(x+0.05)`; the draft's `fast_attack_slow_release_ema(
   mid_flux + treble_flux)` is unbounded, so the product's scale (and any
   threshold on it) becomes material- and gain-dependent. Give it its own
   `x/(x+c)` with `c` derived from corpus percentiles (e.g. `c` = session
   median of the EMA, so the median maps to 0.5) — the same empirical
   grounding discipline the rest of this session used.
2. **`mid_flux + treble_flux` ≠ the "mid+treble" the composite uses today.**
   The current broadband term is the residual `flux − bass_flux`, which
   includes the 180-700 Hz low-mids (in no band slice), the 12 kHz+ air, and
   the `rms_rise * 0.25 * bands` bonus added into `flux`
   (`analyzer.py:524`) — none of which will be in a literal
   `mid_flux + treble_flux`. Either definition is defensible; pick one
   deliberately and note the magnitude change, since any threshold tuned on
   one will not transfer to the other. When adding `treble_flux`, mirror the
   `_flux_weights` weighting the way `bass_flux`/`mid_flux` already do.

On the other open question ("is instability ≈ novelty fully captured?"):
short-window variance of flux is a reasonable causal proxy for Foote
novelty and is genuinely distinct from the coincidence product (it measures
unpredictability, not level) — fine to defer. One cheap, build-specific
signal worth queueing behind it: **onset density acceleration** (onsets per
bar rising across consecutive bars) — the snare-roll speedup is the single
most characteristic buildup cue in the production literature, and the onset
stream to compute it already exists.

Also endorse the deferred per-mood slope window, with one caution kept from
the sources the plan itself cites: buildups frequently *lose* RMS energy
near the end (high-passed, bass removed) even as tension peaks, so energy
slope can be flat or negative at the moment of a real drop. The draft's
`(0.8 + 0.4·slope_norm)` influence-not-gate treatment is correct — nothing
in the redesign should ever re-promote slope to a gate. A later refinement
that matches the actual production cue better than broadband slope: rising
spectral centroid / treble-band slope over the last 2-8 bars (the filter
sweep itself).

### F4 — The asymmetric-alpha z-score's stated direction is ambiguous and, read literally, inverted for the sustain job

Plan 4c: "adapt quickly when bass is newly rising (so a real new section is
recognized promptly), adapt slowly to 'forget' while bass is already
elevated." For a **level/sustain** signal, fast mean-adaptation on rise is
the existing bug: the baseline catches up, z collapses, the held drop reads
as neutral. What the sustain signal needs is the opposite asymmetry on the
baseline: **slow to rise** (long memory of the quiet reference, so bass
stays above baseline for the whole 30-60s drop) and **fast to fall** (so
after the section ends, a breakdown reads low promptly). If the intended
meaning was "the *output* responds quickly on rise" — that's the fast-attack
half of the output EMA, not the z-score's mean-adaptation rate; the plan
conflates the two rates in one sentence. Before building, restate which
timescale applies to which state variable.

Cleaner primitives that avoid the trap entirely (both operating on the F1
raw-path level channel):

- **Two-timescale comparison:** fast EMA (τ ≈ 0.25-0.5 s) minus a slow
  reference (τ ≈ 60-120 s EMA, or better a rolling low percentile — p10-p25
  over 60-120 s of the level ring). A percentile reference does not
  renormalize during a 60 s drop by construction, and a small ring with a
  partial sort every N frames is cheap. `bass_was_suppressed` for the
  trigger then falls out of the same ring for free (`1 − recent_max` over
  the window).
- If the z-shape is kept: apply the slow alpha to the mean whenever
  `x > mean` and the fast alpha when `x < mean` — that is the asymmetry
  that actually produces "held drop stays hot, breakdown resets fast."

Also for the trigger's `bass_was_suppressed` window: ~3 s is 1.6 bars at
128 BPM, and many buildups keep the four-on-the-floor kick until the final
1-2 bars — a 3 s `recent_max` will then read "bass never left" and halve
the trigger on real drops. Express the window in **bars** (4-8 bars
default), per-mood tunable exactly like the deferred slope window, with a
short secondary window (~1 bar) OR'd in to catch the pre-drop gap.

### F5 — There is no downbeat *estimation* anywhere in the live path: "fire on next downbeat" quantizes to an arbitrary 4-beat phase

Both engines count beats mod 4 from whenever lock happened
(`_advance_phase`: `_bar_beat_count = (_bar_beat_count + 1) % 4`; v1
equivalent in `_ingest_onset`). `downbeat_confidence` measures grid
*consistency*, not bar-phase correctness — nothing anywhere estimates which
of the four beats is the musical "one." So `_schedule_drop()` →
`schedule_for_next_downbeat()` lands the most timing-critical visual event
the director owns on a 4-beat grid with **arbitrary phase** — up to 2 beats
(±1 s at 128 BPM) off the actual downbeat, consistently for a whole session,
because the phase error is fixed at lock time. The phrase clock inherits the
same arbitrary phase (it advances on these downbeats), so all the bar-count
expectations in `_phrase_bias()` carry the same offset.

Options, cheapest first:

1. **Bar-phase voting from bass-onset strength** (Klapuri/Davies-style accent
   evidence, radically simplified): accumulate `bass_flux` (or onset
   strength) into 4 phase bins keyed by `_bar_beat_count` at each beat;
   every few bars, rotate the counter so the argmax bin is beat 0. Kick on
   1 (and 3) vs snare on 2/4 makes bass-band accent a workable beat-1
   discriminator in the four-on-the-floor genres this targets.
2. **Sync bar phase from the mixer hint when live** — currently only the
   *phrase clock* syncs from `section_hint` (`_maybe_sync_phrase_clock_
   from_section_hint`), not beat-in-bar; the mixer knows the real grid.
3. **For the drop specifically, fire on the trigger signal itself.** The
   trigger/sustain split enables this: the impact is *in the audio* at the
   moment `impact_novelty` spikes — quantizing the visual response to a
   possibly-wrong grid point adds latency (measured in the ADR: score decays
   while waiting) for alignment that isn't guaranteed to be right. Use the
   grid to pre-arm; use the trigger to fire. This directly answers plan
   4a's open question "what should this signal actually drive."

### F6 — The drop re-validation score gate is vacuous on every non-timeout path, and the timeout path can schedule/cancel-loop

`_fire_drop()`: `score_ok = score_now >= confirm OR pending >= threshold`.
Every entry into `_schedule_drop()` except BUILD's timeout rescue required
`score >= threshold` (or fastlane, which is higher) *at schedule time* — so
`pending >= threshold` is true by construction and the score half of the
gate never rejects anything on those paths. Only `dconf` is genuinely
re-validated. The overnight session's "zero `drop_cancelled` events"
(2026-08-11 ADR addendum) is consistent with this being structural, not
evidence of calibration health. If the gate is meant to catch
schedule→downbeat decay, compare `score_now` against a fraction of
`pending` (e.g. `score_now >= pending * 0.85`); if it isn't, simplify it to
the dconf check so the next reader doesn't infer protection that isn't
there. (Under the F2/F5 recommendations this gate gets rethought anyway —
a trigger-fired drop doesn't wait, so there is nothing to re-validate.)

The one path where the score gate *does* bite can loop: BUILD's timeout
rescue fires with `score >= drop_timeout_score_floor` (0.60-0.70), but
`_fire_drop` needs `score_now >= confirm` (0.9 × threshold ≈ 0.62-0.69).
On cancellation the mode stays BUILD, `elapsed >= build_max` remains true,
and the next tick re-schedules — a schedule → cancel cycle every downbeat,
spamming the decision log until score drifts up or a breakdown rescues the
mode. Add a cancel refractory, or after N consecutive cancels abort the
build to CRUISE.

Related latent state bug: `_schedule_drop()` registers the downbeat callback
and sets `_drop_pending = True`; if the tracker then loses lock (silence
reset on track change), `_reset_tempo_lock()` does not clear
`_pending_callbacks`, the oscillator stops (bpm = 0), the callback never
fires, and `_drop_pending` stays latched — blocking all future drop
scheduling until the next re-lock finally fires the *stale* callback, which
can then fire an inherited DROP on the first downbeat of a different track
(re-validation gates it on current score/dconf, so it's usually but not
always benign). Clear pending callbacks and `_drop_pending` in the silence
reset path.

### F7 — Every smoothing constant is per-frame: detector time constants silently depend on render FPS, and the slope window breaks outright above ~120 fps

`_energy_history` is `deque(maxlen=240)` *frames* with a `>= 2.0 s` age
check. At 60 fps that's the documented ~4 s window. At 144 fps the deque
holds 1.67 s, the age check never passes, `energy_slope` is permanently 0,
`slope_norm` is dead, and BUILD entry (slope-thresholded) never triggers —
the director sits in CRUISE forever. Every EMA in the detector
(`_energy_alpha` 0.08, `_band_alpha` 0.08, flux 0.75/0.25, bass-flux
0.4/0.6 and 0.85/0.15) likewise shifts its time constant with frame rate.
Today the app is effectively vsync-locked at 60; an uncapped or
high-refresh session changes detector behavior wholesale, and none of the
tuning transfers.

**Recommendation:** convert to dt-based smoothing (`alpha = 1 −
exp(−dt/τ)`) with τ documented in seconds, and make the history ring
time-bounded rather than count-bounded. Do it *as part of* the redesign
rather than after: the new primitives (F4's τ ≈ 0.25 s / 60-120 s, the
suppressed-window in bars) are all naturally specified in time/musical
units, and building them frame-based would just recreate this debt. This
also makes the offline simulator's frame cadence irrelevant to fidelity.

### F8 — Kick-regularity samples sub-bass, not kick: the band comment is wrong by a factor of two

`auto_vj.py:2927-2931` samples `bands[0:6]` with the comment "~31-99 Hz."
The 64 log-spaced bands run 30 Hz → 16 kHz, so band edge 6 is
30 × (16000/30)^(6/64) ≈ **54 Hz** — bands 0-5 span 30-54 Hz (31-99 Hz
would be bands 0-11). Kick fundamentals sit mostly 50-100 Hz, so
`kick_regularity` (used by the director's kick-confirmed-build,
kick-dropout, and breakdown-onset logic, and by the recommender's
`kick_regularity_fit`) is measuring sub-bass/rumble regularity. On material
with strong sub content (modern techno, dubstep) it works by proxy; on
material whose kick lives higher (older house, rock-adjacent) it
under-reads, and the CV computation is additionally polluted by each
sample being normalized to a *different* frame max. Fix: widen to
`bands[0:12]` (30-97 Hz) to match the comment's evident intent — or better,
sample `bass_flux` at onsets, which is raw-path and already
kick-transient-shaped. Note `kick_regularity_fit`'s `exp_kick` reads
`expected_bands[0:6]` with the same offset, so change both together.

### F9 — Sustain combination shape (plan 4c open question): make bass load-bearing by construction, not by weight accounting

Endorsing the plan's instinct with a concrete form: prefer a product with a
soft floor over both `min()` and any weighted sum —

    sustain = bass_level_norm * (0.3 + 0.7 * midtreb_busyness_norm)

Bass at zero forces sustain to zero (the AND the owner asked for, exact by
construction); busyness modulates rather than gates (differentiable, no
`min()` plateau). This also makes the 2026-08-10 "no bass, no drop"
invariant *structural* instead of arithmetic: the rc.7 swap shrank that
invariant's margin from 0.25 to 0.10 and left a comment warning to re-check
it whenever floors move — under a product, the invariant can't erode by
reweighting at all, and that whole class of margin bookkeeping disappears.
EDMFormer's drop definition ("main rhythm motifs AND basslines") and the
mixer's `structure.py` (energy percentile AND bass presence as co-occurring
conditions) both back the AND shape.

---

## Methodology notes (M)

**M1 — Ground-truth circularity in the drop corpus.** `drop_fire` keyframes
are events the *current* detector chose to fire — "real-drop coverage"
measured against them scores the new formula's agreement with the old
formula's hits, not with the music. It cannot count drops the current
detector *missed* (false negatives are invisible), and the false-positive
proxy (11 hand-identified rows out of 72k) is a very thin negative class.
For the redesign sims, add ground truth that doesn't come from the system
under test: (a) for mixer-analyzed tracks, `structure.py`'s PEAK boundaries
are pre-known section starts (the mixer store is already the established
independent check for BPM/key per this project's own practice); (b) for a
subset of `favorites/e`, hand-label actual drop moments — Yadati labeled
100 tracks in ~6 hours, so ~30-50 drops across two sessions is an
afternoon; the plan's proposals are exactly the kind of change whose value
shows up in the events the old detector missed.

**M2 — Score the trigger with tolerance-window F1, not floor-clearing
rates.** "Events clearing the raver floor" measures the *sustain* question
(is the score high) — the right metric for the sustain signal, kept as-is.
The *trigger* is an event-in-time and should be scored the way the
literature scores it: hit within ±N seconds (or better, ±bars) of a labeled
drop, F1 over hits/false-alarms/misses at a couple of window sizes
(Yadati's ±3/5/15 s ladder is a ready template, and their 0.61-0.71 offline
F1 is the humility benchmark for what a causal detector can expect).

**M3 — Simulate at the frame cadence the live system actually runs** — or
land F7 first, after which this note is moot. Offline replay that steps the
detector at a different effective rate than 60 fps currently changes every
EMA's behavior relative to live (see F7), which quietly biases any
simulated comparison of smoothing-sensitive candidates (both halves of the
redesign are smoothing-sensitive).

---

## Priority map onto the plan's own buckets

Plan section 6 bucket | Audit adjustment
--- | ---
"Revert band_blend weights — could land independently" | Agreed, land freely. Consider F9's product form at the same time or immediately after — it makes the weight question mostly moot.
"Fizzle → relative-to-peak — could land independently" | **Reclassify: depends on 4c's sustain primitive** (F2). As an interim, `max(peak*0.9, floor)` against a 1-2-bar-smoothed score with N-consecutive-evals hysteresis is acceptable; against the raw current composite it will exit healthy drops.
"Detector gets its own band channel" | Agreed, but source it from **pre-normalization** magnitudes (F1), not from `bass_weighted`; otherwise the channel inherits the shape-fraction ceiling. Empirical-gain option: ≈1.25, not 0.5-1.0 — or no curve at all.
"Trigger/sustain split — build + simulate" | Agreed. Add: normalization constant for the mid/treble term + explicit flux definition (F3); trigger should *fire* the drop, grid pre-arms (F5); score with tolerance-window F1 against non-circular labels (M1/M2).
"Asymmetric-alpha bass level" | Direction as stated is inverted/ambiguous for the sustain job (F4) — specify slow-rise/fast-fall on the baseline, or use the two-timescale/percentile form instead.
Not in the plan | F5 (bar-phase estimation), F6 (vacuous re-validation + cancel loop + stale-callback latch), F7 (dt-independence — do it as part of this work), F8 (kick band off by 2x).

Per the standing rules: this audit changes no code, so no subsystem versions,
weights-doc version, or ANALYSIS_VERSION move. Every finding above that turns
into a code change will trip the documented triggers (`_DETECTOR_VERSION`,
`_DIRECTOR_VERSION`, `weights-and-thresholds.md`, the ADRs) when it lands.

Sources consulted:
- https://transactions.ismir.net/articles/10.5334/tismir.202
- https://arxiv.org/html/2603.08759v1
- https://archives.ismir.net/ismir2014/paper/000297.pdf (Yadati et al., ISMIR 2014)
- https://www.audiolabs-erlangen.de/resources/MIR/FMP/C4/C4S4_NoveltySegmentation.html
- https://www.semanticscholar.org/paper/Preferred-tempo-reconsidered.-Moelants/b0db06a5a8b2c1942afff5c317c5f6da55a7dcf7
- https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2018.00349/full
