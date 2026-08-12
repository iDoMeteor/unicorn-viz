# Auto VJ: Drop-Score Redesign — Trigger/Sustain Split (2026-08-11)

Owner: unicorn-viz
Status: **draft — pending external audio-nerd review before implementation.**
Nothing in this document is shipped. It captures decisions already made in
discussion, open questions still to be resolved, and a first-draft formula
for the one piece nobody has designed yet (the trigger/novelty signal).
Last updated: 2026-08-11

## Context

Same night as the `energy_norm`/`band_blend` weight swap
(`docs/adr/vj-system.md` § "Recommender centroid_fit Weight Cut..."
addendum, `_DETECTOR_VERSION` → `1.0.0-rc.7`), simulating a follow-up fix
(a non-adaptive bass-level EMA meant to replace `band_blend` outright)
against two real sessions showed it losing badly — real-drop coverage
looked great, but it inflated every bass-free false-positive proxy row to
100% clearing the raver floor, because raw `bass` is saturated near
ceiling in every director mode including BREAKDOWN (median 0.967-0.983
across modes, a 1.6% spread). That failure, and the diagnosis behind it,
turned into a much bigger conversation: `drop_score` is being asked to do
two structurally different jobs with one number, and the swap plus every
gating variant tried so far was rearranging weights within that flawed
frame rather than fixing it.

This doc is that conversation, written up for review before anything
ships. Section order follows how it came up.

---

## 1. The per-profile gain/curve situation

**Diagnosis (confirmed against real corpus data, not assumed):**
`unicornviz/audio/analyzer.py`'s `_shape(x, gain) = 1 - exp(-x·gain)`
(`bass` gain 6.6, `mid` 5.8, `treble` 7.2) is an exponential saturating
curve applied to every profile-weighted band mean before it becomes
`AudioData.bass`/`mid`/`treble` — the values everything downstream reads,
including the detector. It climbs fast and flattens hard. Real numbers
from `favorites/e` (a fresh session): raw `bass` sits at **median
0.97-0.98 in every single director mode**, BREAKDOWN included (0.967) —
essentially no dynamic range between "nothing happening" and "full send."

**Why it's there, and why it's not simply wrong:** effects want a band
level that reads as "alive" without requiring a loud track — that's a
legitimate visual-reactivity goal, and six effects currently depend on it
(`audio_spectrogram.py`, `audio_waveforms.py`, `audio_sine.py`,
`audio_chromogram.py`, `audio_centroid.py`, `audio_tracks.py`, all reading
`audio.bass_n`/`mid_n`/`treble_n` — see item 2). The mistake was never the
curve's existence, it's that the **detector has been sharing it** with
effects that need the opposite property (compression) from what a
level-discriminating score needs (spread).

**Decision (agreed):** separate the two concerns. Effects keep
`_shape()`'s current curve unchanged — six consumers rely on its current
behavior, don't touch it. Give the detector its own channel: unshaped (or
differently, much more gently shaped) band data, computed once alongside
the existing profile-weighted values, consumed only by
`drop-ins/auto-vj-01/beat_grid.py`.

**Shipped (2026-08-11, same day, ahead of the rest of this plan) — owner
asked for this specific piece "asap."** `AudioData.bass_det`/`mid_det`/
`treble_det` (`unicornviz/effects/base.py`), computed in
`unicornviz/audio/analyzer.py` from the same pre-curve
(`bass_weighted`/`mid_weighted`/`treble_weighted`) input as `bass`/`mid`/
`treble`, through the same `_shape()` function with a separately-tuned
gain. Grounded empirically rather than picked by feel: inverted real
`favorites/e` `bass`/`mid`/`treble` values back to their pre-`_shape()`
input, swept candidate gains, kept whichever maximized cross-director-mode
median separation. Result was asymmetric across bands, worth knowing:
**`bass`'s effects gain (`6.6`) was genuinely mistuned** for this purpose
(only `1.7pp` separation; `2.0` empirically best on this data, `6.8pp`,
~4x better) — but **`mid` (`5.8`) and `treble` (`7.2`) were already
optimal**, every lower gain tested gave *less* separation, not more. So
only `bass_det`'s gain differs from its effects counterpart;
`mid_det`/`treble_det` currently mirror `mid`/`treble` exactly (kept as
separate fields anyway so either can move independently later).
`drop-ins/auto-vj-01/beat_grid.py`'s `band_blend` z-score inputs
(`bass_n`/`mid_n`/`treble_n`, both v1 and v2/v3) now read this new
channel instead of `bass`/`mid`/`treble`; `raw_energy`/`energy_norm`
deliberately left untouched (checked separately, already well-calibrated
— see section 4b/4c, this is a different problem from that one).
Effects, HUD, and live-corpus telemetry are unaffected — they still read
the original `bass`/`mid`/`treble`, unchanged gains.

**Verified end-to-end**, not just at the raw `_shape()` step: replayed the
full z-score pipeline (same `_norm()` formula/alpha) on the new channel
against real `favorites/e` data. Real `bass_n` cross-director-mode median
separation: `2.4pp → 9.0pp`. New tests:
`tests/test_analyzer_detector_bands.py` (four tests on the new channel
itself), `test_band_blend_reads_bass_det_not_bass`/
`test_band_blend_falls_back_to_bass_when_bass_det_absent`
(`tests/test_beat_tracker_v2.py`). Full suite green (1644 passed),
`ruff`/`bandit` clean. `_DETECTOR_VERSION` → `1.0.0-rc.8`,
`_VJ_WEIGHTS_DOC_VERSION` → `24`, core → `1.0.0-beta.85`, auto-vj-01 →
`1.0.0-rc.44`.

**Independent cross-validation (reviewer re-evaluation, next day):** the
gain sweep's criterion — maximize real cross-mode median separation — was
checked against a completely different analytical method (inverting the
plan's own reported medians algebraically through `_shape()`) and the two
land on the same ballpark (`2.0` empirically vs. `~1.25` from
median-centering), which is the reassuring part. The more telling part:
the *measured* result — `1.7pp → 6.8pp` — sits almost exactly where the
independent inversion analysis predicts the ceiling should be (`~10pp` raw
spread). That's not a coincidence, it's the same limitation stated a
different way: `bass_det` still reads `bass_weighted`, i.e. the spectrum
*after* it's divided by its own per-frame maximum
(`analyzer.py:556-559`) — so what feeds `_shape()` is a **spectral-shape
fraction** ("how much of this frame's loudest bin is bass"), not an
absolute level. `bass_det` recovers most of what the saturating gain was
destroying, but it cannot exceed the ceiling that per-frame
normalization itself imposes. **The real fix is a raw-magnitude channel**
— built from the pre-normalization spectrum, the same path
`flux`/`bass_flux` already correctly use (`analyzer.py:512-518`'s own
comment already explains why per-frame normalization erases a transient,
the level fix is the same lesson applied to the band levels) — and this
sweep's own separation metric (real cross-mode median pp) is the
ready-made yardstick to judge that raw-magnitude candidate against
`bass_det` once it's built. Not built this pass; `bass_det` stands as a
well-grounded interim, not a dead end.

**Note on the "30%" question this shipped in response to:** worth being
precise about what target is and isn't achievable on this curve family.
A *cross-mode median* gap anywhere near 30 percentage points isn't
reachable by any gain choice on `1-exp(-x·gain)` — the sweep found the
*peak* achievable for bass at `~6-7pp`, regardless of gain, because every
director mode mixes loud and quiet moments internally (a "DROP" isn't
loud on literally every frame; kicks land periodically). That cap is a
property of the music's own moment-to-moment texture, not a shaping
failure — no curve fixes it, because the z-score downstream is what's
supposed to recover mode-level discrimination from moment-level noise,
not the curve. What the curve fix *does* achieve, and what "30%" is likely
closer to in spirit: the raw *within-signal* percentile spread (a genuinely
quiet moment vs. a genuinely loud one) is now large again instead of
compressed near ceiling — that's the actual "pegging even when nearly
empty" complaint, and it's fixed.

## 2. Where `bass_n`/`mid_n`/`treble_n` (the z-score) actually gets used

Answer to "where are those values being used aside from the HUD" — traced
directly, not from memory: **six visual effects** read `audio.bass_n`/
`mid_n`/`treble_n` directly for their own reactivity
(`audio_spectrogram.py`, `audio_waveforms.py`, `audio_sine.py`,
`audio_chromogram.py`, `audio_centroid.py`, `audio_tracks.py`), plus the
HUD debug overlay and `app.py`'s `build_live_corpus_sample()` (the
live-corpus telemetry sink — a different file from the sequence corpus
this session's simulations have been reading).

**Important correction to the mental model:** none of those six effects,
the HUD, or the live-corpus telemetry share their z-score state with the
detector. `unicornviz/audio/analyzer.py`'s `_norm_band()` is one
independent z-score tracker (own mean/var); `drop-ins/auto-vj-01/
beat_grid.py` runs **two more**, completely independent (own mean/var
each) — one in `BeatGridTracker` (v1), one in `BeatTracker`/`BeatTrackerV3`
(v2/v3, the active engine). All three run the identical formula on the
identical input (`data.bass`/`mid`/`treble`, the post-`_shape()` values)
but never share state. A note cross-referencing this was added directly to
`_norm_band()`'s docstring this session (`unicornviz/audio/analyzer.py`,
commit `a9fc978`) so this doesn't have to get re-discovered later.

**Direct answer to "is the z-score involved in drop_score at all, is it
obtusely?"** — yes, directly, not obtusely: `band_blend` (currently
weighted `0.15` of the composite, post-swap) is built entirely from
`beat_grid.py`'s own internal z-scored `bass_n`/`mid_n`/`treble_n` (its own
copy, not the HUD/effects one). The z-score *is* `band_blend`'s entire
input. It just isn't the *only* z-score instance in the codebase, which is
presumably what made it feel indirect.

## 3. What the research actually says (with sources)

Web search was available for this pass (it wasn't for the deep-dive
earlier in the session). Two findings, both landing squarely on your
existing intuition:

**Boundary detection and section classification are separate tasks in
the literature, not one signal doing both.** The foundational reference is
Foote's 2000 novelty-curve work; a 2026 paper specifically on EDM
structure (EDMFormer) cites prior work finding "energy novelty, drum onset
counts, and timbral features" as the strongest cues for *structural
transitions* (change, not level) — while *section classification*
(is-this-frame-currently-drop) is scored on different, state-based
features. EDMFormer's own section definitions: drops are "peak energy
section, featuring main rhythm motifs and basslines" (state), buildups are
"gradually increasing energy and tension, often with rising drum patterns
or risers" (trend), breakdowns are "reduced energy sections, often
melodic or atmospheric." That's the trigger/sustain split, arrived at
independently in the literature.

**The production-technique piece — confirmed, and independently already
proven inside this codebase.** EDM production convention: buildups
commonly run a high-pass filter sweep that removes bass (~100-150Hz
upward), under a snare roll/riser that increases in speed and frequency,
then the drop is "a powerful restatement of the main rhythm" — bass
slams back in, everything hitting at once. **This is not just a web
source — `drop-ins/dj-mixer-01/structure.py` (the mixer's own offline
song-structure analyzer) already encodes exactly this as one of its three
feature families**: "Band balance — low/mid/high fractions. Bass *leaving*
is what makes a breakdown a breakdown and what distinguishes a build
(filtered, no bottom, rising highs) from the drop it resolves into." The
mixer has been doing this correctly, offline, this whole time. The VJ's
live detector has never had a causal (real-time, no-lookahead) equivalent.

**Answer to "are we detecting boundary & sections separately — probably
in the mixer but not in the VJ?"** — confirmed exactly right.
`dj-mixer-01/structure.py` does real offline whole-track analysis (its own
docstring: "we run offline against the complete file... that turns
prediction into lookup") producing genuine pre-known section boundaries
and roles (`HOLD`/`RISE`/`PEAK`/`FALL`/`CLOSE`), which reach the VJ only
as an *external hint* (`_phrase_bias()`'s `section_hint` consumption) —
and only when dj-mixer-01 is the audio source with an analyzed file. For
every other source (Spotify, media player, an unanalyzed mixer track —
which per this session's own scorecards is most of the operating time),
the VJ's only structural awareness is its own live `drop_score` threshold
crossings. There is no internal boundary/novelty detector distinct from
the level-based composite today.

Sources:
- [A Basic Tutorial on Novelty and Activation Functions for Music Signal Processing](https://transactions.ismir.net/articles/10.5334/tismir.202)
- [EDMFormer: Genre-Specific Self-Supervised Learning for Music Structure Segmentation](https://arxiv.org/html/2603.08759v1)
- [How To Make an Unforgettable EDM Drop](https://blog.samplefocus.com/blog/how-to-make-an-unforgettable-edm-drop/)
- [Before The Drop: How To Make EDM Buildups & Risers](https://blog.waproduction.com/before-the-drop-how-to-make-edm-buildups-risers)

## 4. The two-problem split

**Decided: separate trigger and sustain into two independently-computed
signals**, not one composite reused for both. Confirmed in the actual
code that they're currently conflated: `_fire_drop()`'s re-validation gate
and DROP mode's exit ("fizzle") check both read the *same* `drop_score`
against related thresholds (`auto_vj.py:3332-3336` — `_drop_fizzle_score`
defaults to `self._drop_threshold`, the identical value used to fire).

### 4a. Trigger / impact signal — first draft, for review

Design goal, from your bullets: a big bass hit **and** broadband
mid/treble activity, coming out of a **suppressed** prior state — the
filter-sweep-then-slam-back-in pattern confirmed in sections 2-3 above —
with rising energy as influence, not a gate, since buildups run much
longer than any fixed short window.

Building blocks, what exists vs. what's new:

| Signal | Status |
| --- | --- |
| `bass_flux_norm` | Exists, keep as-is — proven fast-attack/slow-release bass transient. |
| `mid_flux` | **Already computed every frame** (`analyzer.py:534`, per-band raw sub-flux, mid slice only) and already logged to the corpus — just never consumed by `drop_score`. |
| `treble_flux` | **Does not exist yet.** `mid_flux`/`bass_flux` are already split out per-band; treble isn't. Proposing a third field, same pattern, same file — small, well-precedented addition. |
| "was bass suppressed recently" | **Does not exist.** Needs a genuine bass-*level* memory over the last few seconds — the same open primitive the sustain signal needs (see 4c). This is the load-bearing dependency between the two halves of this redesign: fix that one primitive, both signals become buildable. |

First-draft formula (name TBD, `impact_novelty` here):

```
midtreb_activity_fast = fast_attack_slow_release_ema(mid_flux + treble_flux)
                         # same asymmetric shape bass_flux_fast already uses
                         # (0.4/0.6 rising, 0.85/0.15 falling) -- "is the
                         # riser/snare-roll/hat pattern busy right now"

bass_was_suppressed = 1.0 - recent_max(bass_level_signal, window=~3s)
                       # needs the fixed bass-level primitive from 4c;
                       # near 1.0 when bass has genuinely been near-absent,
                       # near 0.0 if bass never really left (so a random
                       # kick mid-drop doesn't re-trigger this every bar)

impact_novelty = bass_flux_norm * midtreb_activity_fast
                 * (0.5 + 0.5 * bass_was_suppressed)
                 * (0.8 + 0.4 * slope_norm)   # influence, not gate
```

Multiplicative, not summed — the three factors are meant to co-occur
(coincidence detection), not substitute for each other, matching the "AND
not weighted sum" instinct that came up for the sustain side too (4c).
This is a v0 for reviewers to push on, not a final answer — open
questions below.

**Composes with `deck.py`'s `structural_cues()` (4d) rather than being
replaced by it — correction from the audit's re-evaluation.** Originally
flagged `structural_cues()` (a phrase-step RMS-jump detector) as possibly
a stronger foundation than this draft. On closer read it's not a
substitute: as written it uses **8 bars of *lookahead***
(`mean(e[b:b+8]) − mean(e[b-8:b])` at boundary `b`), which is what makes
its `0.30`/`0.12` gates so clean — a causal live port has to shrink that
to roughly 1 bar of leading window against 8 trailing, which is noisier
and adds a ~1-bar latency floor. That makes it a strong **confirmation /
sustain-onset check** (fires ~1 bar into a real drop, once there's
actually a trailing window to compare) rather than an instantaneous
trigger — a natural gate for the fizzle floor (4c), and a second opinion
`impact_novelty` above can be checked against a beat later, not a
replacement for the immediate coincidence trigger. The two compose: step
detector for *sure*, `impact_novelty` for *now*.

**Explicitly deferred, per your note:** the buildup-influence window
being genre/mood-tunable (not a fixed 2s) rather than universal. Mechanism
already exists to hang this off — `_PROFILE_PRESETS` already carries many
per-mood tunables (thresholds, hold times); a `slope_window_s` per mood
profile would follow the identical pattern. Not designed further here,
flagged so it isn't lost.

**Open questions for review:**

- Is `bass_flux_norm * midtreb_activity_fast` (both required, multiplied)
  too strict? A real impact might have one lead the other by a frame or
  two depending on production style — may need a short coincidence
  window rather than same-instant multiplication.
- Is "instability ≈ novelty" (your framing) fully captured by the
  broadband-coincidence idea above, or is there a distinct "things are
  moving unpredictably" signal (e.g. variance of `flux` itself over a
  short window) worth adding separately? Left as one open question rather
  than assumed folded in.
- What should this signal actually *drive*? Presumably replaces (or
  augments) the current BUILD→DROP entry conditions
  (`self._schedule_drop()`'s gate at `auto_vj.py` ~3280-3292) — not
  designed here, since that's downstream of agreeing the signal itself is
  right.

### 4b. Is `bass_flux_norm` already "real sustained bass level"?

**No — and this is worth being precise about, since it's the crux of why
V6 failed and why 4c's fix has to be a new thing, not a re-use.**
`bass_flux_fast`/`bass_flux_norm` is fundamentally a *transient* tracker:
it's built from `bass_flux` (the per-frame *change* in the bass band's raw
spectrum — a flux/onset measure), run through a fast-attack/slow-release
asymmetric EMA. The slow-release half (0.85 retain) gives it some
persistence after a hit, but it decays toward zero for a bass line that's
genuinely *holding* at one level with no new attacks — which is exactly
what a sustained, unchanging drop looks like between individual kicks.
Adding it into the sustain signal, or replacing anything with it, doesn't
solve the "is bass currently present as a level" question — it answers
"was there recently a bass attack," a related but different question.
The sustain signal needs a real level primitive, which is what 4c is for.

### 4c. Sustain / drop-section signal

**Decided: revert `band_blend`'s band weights to what they were before
the 2026-08-09 rebalance** (`bass_n*0.45 + mid_n*0.30 + treble_n*0.25`,
back from the current `bass_n*0.7 + mid_n*0.2 + treble_n*0.1`) — both in
`BeatGridTracker` (v1) and `BeatTracker`/`BeatTrackerV3` (v2/v3), same
line pattern in both (`beat_grid.py:221` and `:896`, both currently
`0.7/0.2/0.1`). Per your account: the rebalance toward bass was made
before the terms were fully understood, trying to solve a real problem
(wanting bass to matter more) by tweaking the wrong lever — this redesign
is meant to actually fix that problem (via the trigger/sustain split and
the level-vs-transient distinction above) rather than lean on a blend
ratio to compensate for it. Reverting is a clean, mechanical change,
independent of everything else in this doc — could land on its own before
the rest lands, if that's useful for staging.

**Still open, separate from the weight revert:** the "requires heavy low
end *and* busy treb/mid" framing you gave reads as an AND, not a weighted
sum — a linear blend (any ratio) still lets a strong treble reading
partially compensate for near-zero bass, mathematically. Whether to also
change `band_blend`'s *combination* (e.g. `min()` or a product of a
bass-presence term and a mid/treble-busyness term, instead of a weighted
sum) is a separate decision from which weights to use in the reverted
blend, not resolved here — flagged for review alongside the weight
revert, not bundled into it.

**The actual open primitive both halves of this redesign need:** a bass
*level* signal that (a) has real dynamic range despite `_shape()`'s
saturation (ruling out V6's plain raw EMA, proven dead in section 0/this
session's earlier sim), and (b) doesn't fully re-normalize toward
"neutral" within 5-7s of sustained loud bass the way the current symmetric
z-score does (the original decay bug). Direction proposed, not yet built
or simulated: an **asymmetric-alpha z-score** — same `_norm()` shape
`beat_grid.py` already runs, but with two different `a` values depending
on whether the *baseline* is being pulled up or down (mirroring
`bass_flux_fast`'s existing fast-attack/slow-release pattern, applied to
the z-score's mean-adaptation rate instead of a raw EMA): adapt quickly
when bass is newly rising (so a real new section is recognized promptly),
adapt slowly to "forget" while bass is already elevated (so a held drop
doesn't get renormalized into "boring" the way it currently does).

This needs to be its **own, new, independent tracker state** — not a
change to the shared `_norm()`/`_norm_band()` used elsewhere (per section
1's separation-of-concerns principle: don't retune infrastructure other
consumers depend on for their current behavior).

**Fizzle/exit — decided:** replace the current `_drop_fizzle_score`
(a fixed profile constant, defaulting to the same value used for entry)
with a relative, decay-from-own-peak check: exit only once the live score
has fallen more than ~10% below *this drop's own* peak
(`score < self._drop_peak_score * 0.9`), rather than compared against a
fixed absolute bar every drop is held to regardless of how big it actually
was. `self._drop_peak_score` already exists and is already tracked as a
running max during DROP mode (`auto_vj.py:3305`) — this is a formula
change to the comparison, not new state.

**Open question flagged, not resolved:** the current fizzle check's
*other* job — letting a drop that never really took off exit quickly
rather than sitting through the full `drop_cooldown_s` (30s default) — a
pure relative check loses that, since any peak, however weak, now just
needs to not decay by more than 10% to hold. Worth considering a floor
alongside the relative check (e.g. `max(self._drop_peak_score * 0.9,
some_absolute_min)`) so a genuinely weak drop can still exit early. Not
decided here — exactly the kind of trade-off this doc exists to surface
for review, not resolve unilaterally.

### 4d. What dj-mixer-01's offline analysis has that's worth stealing

Full pass through `drop-ins/dj-mixer-01`'s offline analysis code
(`structure.py`, `key_detect.py`, `bpm.py`, `deck.py`, `stems.py`, `dsp.py`)
looking specifically for anything cheap enough for a real-time, causal
(no-lookahead) detector inside the 16.67ms/frame budget. Full findings
kept out of this doc for length; summary here, by real-time feasibility:

**Directly portable, no redesign needed:**

- **`dsp.py`'s `_StatefulBiquad`/`ThreeBandEQ`** (the mixer's own live
  3-band EQ) is the *same Butterworth filter family* `structure.py`'s
  offline band-balance feature uses, already running per-sample in
  real-time production code today. Worth knowing for any future revisit
  of how `unicornviz/audio/analyzer.py` computes band energy — there's a
  proven-real-time streaming band-splitter sitting in this codebase
  already, not something that would need inventing.
- **`bpm.py`'s log2-symmetric Gaussian tempo prior** (centered on a
  canonical BPM, used to resolve half/double-time ambiguity in its
  offline autocorrelation) is architecturally the same idea auto-vj-01's
  own `bpm_prior_mu`/`bpm_prior_sigma` already implements live —
  independent convergent validation that this is the right approach to
  the octave-fold problem, not a new technique to adopt (see the earlier
  "Squabble Up" live tactus-fold discussion this session, which is
  exactly this failure mode).

**Best new candidate for the trigger signal (4a) — stronger than what's
drafted there:** `deck.py`'s `structural_cues()` (a phrase-boundary
step-detector, separate from and simpler than `structure.py`'s full
segmenter) compares mean RMS energy of a trailing ~8-bar window against
the ~8-bar window before it, and flags a boundary when the step exceeds a
fixed magnitude gate (`> 0.30` peak-normalized for a strong jump, `>
0.12` for "real, not drift"; symmetric `< -0.12` gate for a breakdown
step down). **This needs only ~16 bars of trailing history and zero
future lookahead** — closer to genuinely causal than anything else
reviewed in that codebase, and a simpler, more directly measurable idea
than section 4a's multiplicative coincidence draft. Worth evaluating as
an alternative or complement to 4a's `impact_novelty` formula: a
"phrase-step energy jump" test might catch real impacts more robustly
than a coincidence-of-three-factors test, or the two could combine (step
detector for *when*, coincidence factors for *how confident*).

**Adaptable with a rolling-window substitute, not free:**

- `structure.py`'s core energy normalizer is a **rank transform over the
  whole track** (`argsort(argsort(bar_energies))`), which is what makes
  its PEAK/FALL thresholds (`>= 0.66`, `<= 0.40` rank) meaningful — a live
  version needs a causal proxy (trailing-window percentile, or an online
  quantile estimator like the P² algorithm) instead of true whole-track
  rank. Relevant beyond just this feature: this session's `bass_det` gain
  fix (section 1) used a *fixed* gain empirically tuned against one
  session's distribution; an online-percentile approach would adapt
  per-track/per-set automatically instead of relying on one grounded-but-
  static constant. Not proposed as an immediate change, flagged as a
  fancier alternative worth knowing about.
- Chroma extraction (pitch-class FFT folding, `structure.py`/
  `key_detect.py`) is cheap per-block, but chroma **self-similarity**
  ("this section repeats, therefore it's a chorus") is whole-track by
  construction — a live analog could self-match against a growing buffer
  of *past* chroma only, but can never do the forward-looking "this is
  the last chorus" trick. The mixer's own code says as much
  (`structure.py`'s docstring: "it can notice a drop only after the
  drop... never know that *this* chorus is the last one").

**Offline-only, no real-time path exists:**

- **Stem separation** (`stems.py`, shells out to Demucs — a neural net,
  whole-file, disk-cached) has no cheap live equivalent. Confirms the
  existing design choice: `vocal_hnr`/`vocal_fmr` (spectral heuristics,
  not real stem access) exist specifically *because* stems aren't
  available live — this isn't a gap to close, it's already the right
  trade-off.
- `structure.py`'s merge-short-runs and intro/outro positional passes are
  whole-sequence operations; the positional pass's own docstring states
  outright that final-chorus/outro labeling is offline-only by
  construction — nothing about a track's audio distinguishes "the last
  chorus" from an earlier one without knowing where the track ends.

---

## 5. What's simulated so far, for context

All of this is offline replay against real sequence-corpus rows
(`favorites/e`: fresh, unmasked media-player session, 97 real `drop_fire`
events; `library/b`: 484 events) — see `docs/adr/vj-system.md`'s
`drop_score` addendum for the full methodology and numbers.

| Variant | Result |
| --- | --- |
| V1 baseline (pre-swap) | Reference point. |
| V2 naive swap (`energy_norm`↔`band_blend`, **shipped**, `1.0.0-rc.43`) | Real drops clear score floors more often; small known false-positive cost on a rare bass-free-loud-breakdown proxy. |
| V3/V4 gated swap (`max(band_blend, bass_flux_norm)` gate on `energy_norm`) | Didn't help — `bass_flux_norm`'s slow-release EMA defeats the gate. |
| V5 strict gate (`band_blend` alone gates `energy_norm`) | Fixed the false positive, but overcorrected into a real regression on genuine drops (re-imports `band_blend`'s own decay bug through the gate). |
| **V6 bass-level EMA "replaces `band_blend`"** | **Died on the vine** — raw `bass` is too saturated to discriminate (breakdown false-positive bucket went from 5/11 to 11/11 clearing the raver floor). Diagnosed the saturation root cause (section 1), which is what this whole document grew out of. |

This document's proposals (trigger/sustain split, asymmetric-alpha bass
level, reverted `band_blend` weights, relative fizzle) are the next
candidate to actually simulate — nothing here has been run against real
data yet. Per the standing process this whole session has followed: build
it, simulate it against `favorites/e` and `library/b` (or fresher
sessions if available by then) using V2 (currently shipped) as baseline,
and only ship if it measurably beats V2 on both real-drop coverage and
the false-positive proxy. If it doesn't, the fallback is a fuller
from-scratch redesign — that decision point isn't reached yet.

---

## 6. Summary for reviewers

**Decided, low-risk, could land independently of the rest:**

- Revert `band_blend` weights to `0.45/0.30/0.25` (both v1 and v2/v3
  copies) — mechanical, well-documented history, no new design needed.
  **Not yet implemented** — next up.
- Fizzle/exit check becomes relative to the drop's own peak
  (`peak * 0.9`) instead of a fixed absolute bar. **Not yet implemented.**
- ~~Detector gets its own unshaped/gently-shaped band channel, separate
  from the effects-tuned `_shape()` curve.~~ **Shipped** (section 1,
  `_DETECTOR_VERSION` `1.0.0-rc.8`).

**Decided in principle, needs building + simulating before shipping:**

- Split `drop_score` into two independently-computed signals: a
  novelty/coincidence-based trigger and a state-based sustain score.
- Sustain score needs a genuinely non-decaying-the-wrong-way bass-level
  primitive (asymmetric-alpha z-score, new independent tracker state) —
  this primitive is also what the trigger signal's "was bass suppressed"
  factor needs, so it's the one piece both halves depend on.

**Genuinely open, wants your (and reviewers') judgment:**

- ~~Exact shape/gain for the detector's own band channel (section 1).~~
  Shipped — see section 1.
- Whether `band_blend`'s combination should become AND-like (`min()`/
  product) rather than staying a weighted sum, independent of which
  weights it uses (section 4c).
- The trigger formula draft in 4a — multiplicative coincidence window,
  whether "instability" needs its own separate term, **and whether
  `deck.py`'s `structural_cues()` phrase-step detector (section 4d) is a
  simpler, stronger foundation than the coincidence draft.**
- Whether the fizzle check needs an absolute floor alongside the new
  relative check (section 4c).
- Per-mood/genre slope-influence window (explicitly deferred, not
  designed here).

## 7. Also on the RC2 plate (added 2026-08-13, not part of drop_score itself)

Recorded here per owner instruction to bundle everything deferred to RC2 in
one punch list, even though this item is recommender-side, not drop_score.
See `docs/adr/vj-system.md` "BPM as a Hard Recommender Pre-Filter" for the
full writeup and design decisions (owner-approved, not yet built):

- Gate recommender candidates on BPM plausibility *before* scoring the
  other terms (centroid/zcr/onset/etc.) — reject profiles whose declared
  BPM range doesn't (± a 15% margin) contain the currently-locked tempo,
  rather than letting `tempo_fit` be outvoted by other weighted terms the
  way it was when `chillstep` won a session with BPM solidly locked in the
  high 120s/low 130s. Owner-approved design, explicitly deferred: land
  `kr`/`dbc` first, let it run a few days, then put this on the RC2 plate
  alongside the drop_score work above.
