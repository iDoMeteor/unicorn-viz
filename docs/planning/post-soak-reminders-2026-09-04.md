Owner: audio/recommender
Status: active — post-soak punch list
Last updated: 2026-09-04

# Post-Soak Reminders (2026-09-04)

Deferred items from the 2026-09-04 detector-soak/spectral-shape-ribbon
session — owner: "address next week." Not urgent, not forgotten. See
[[feedback-detector-soak-freeze]] for the soak itself; this list is what
comes after it, not part of it.

## 1. Progressive Trance / Melodic Techno — a missing genre pocket

Owner: "we def run into some stuff that is pretty trancey but in high
120s/low 130s" — real material that doesn't fit the current `trance`
profile (`bpm_prior_mu=138`, hint `134-142`) or anything else in the
roster.

Two real candidate genre names, either plausible without hearing the
actual reference tracks:

- **Progressive Trance** — typically 128-132 BPM, slower and more
  house-adjacent than standard uplifting trance's 134-142. If the
  material still *feels* like trance top-to-bottom (soft kick, trance-
  style build/breakdown structure) just at a lower tempo, this is the
  more likely fit.
- **Melodic Techno** — typically 122-128 BPM, currently a very
  popular/mainstream style (Afterlife / Innervisions / Tale Of Us
  lineage) — trance-like emotional leads and breakdowns, but over a
  punchier, more techno-flavored kick than trance's softer one. If the
  low end feels more techno-hypnotic under the trance-y melodic
  elements, this is the better fit.

The real distinguishing question is kick character, not tempo alone —
worth listening for that specifically when picking real reference
material.

**Also worth checking:** `training-progressive-house-01` already exists
as a packaged training list (it came up during the same session's
spectral-shape ribbon work, provisionally pooled into `deep_house`, then
reverted — see docs/adr/vj-system.md "Data-Derived expected_bands").
Progressive house and progressive trance aren't the same genre, but
they're neighbors on the same production lineage — if a genuinely
trance-adjacent high-120s/low-130s training list gets built for this,
it's worth comparing its ribbon against both `progressive-house-01`'s
own measured fingerprint and `trance`'s, not assuming it's closer to one
or the other without checking.

**Action when picked back up:** get (or record) a real training list for
whichever genre this turns out to be, derive its ribbon (`expected_bands`/
`expected_bands_sigma`) and vocal targets the same way every other
profile in the roster was done 2026-09-03/04, and decide whether it needs
its own new profile or folds into an existing one — same evidence-based
process used for the `hyphy`/trap split, not a guess.

## 2. Ideas for the 8192-sample low-band buffer

The low-band resolution fix (2026-09-04, see docs/adr/vj-system.md
"Low-Band Resolution: Dual-Window Fix") added a persistent 8192-sample
(170.7ms at 48kHz) rolling PCM buffer + long-window FFT, currently used
only to replace the bottom 25 of the 64 perceptual bands. Owner: "we are
SO going to have to take much greater advantage of that later" — real
ideas surfaced in the same conversation, not yet scoped or built:

- **Bass note/key detection.** A note at 40 Hz has a ~25ms period — the
  short (1024-sample, 21.3ms) window can't even complete one full cycle
  of it. 170.7ms comfortably captures 6-7+ cycles even at the very
  bottom of the audible range, which is what's actually needed for
  reliable low-frequency pitch resolution. Could feed a real bass-note/
  key-detection feature that was never accurate enough to attempt on the
  short window alone.
- ~~A steadier `spectral_centroid` measurement.~~ **Superseded 2026-09-04
  (recommender rc.31) — see item 3 below.** Owner decided to remove
  `centroid_fit` outright rather than revisit it; this idea no longer
  applies.
- **A steadier input for vocal formant analysis.** `vocal_hnr`/
  `vocal_fmr` currently read the short-window spectrum; whether the
  long-window buffer's finer low-mid resolution would sharpen either
  measurement (or is irrelevant, since the vocal formant band sits well
  above where the short window already resolves fine) is an open
  question, not a known win — check before assuming.

None of these are committed work — they're flagged so the buffer's
existence doesn't get forgotten as "just the low-band fix" once the soak
ends and normal detector/recommender iteration resumes.

## 3. Full removal of all `centroid_fit` infrastructure

2026-09-04 (recommender rc.31): only the dead `_DEFAULT_RECO_WEIGHTS`
entry was removed tonight (owner picked the smallest of three offered
scopes, mid-soak). Owner, same night: "put on the list for post-soak the
full removal of all centroid stuff so it never comes back lol."

**Why it's dead, for whoever picks this up:** 2026-08-20 retirement
evidence (see docs/adr/vj-system.md) tested 57 real labeled tracks
against five different scalar brightness formulations (log-band centroid,
linear-FFT centroid, log2 centroid, ≥4kHz energy fraction, rolloff-85) —
all five agreed scalar full-mix brightness tracks mastering/loudness, not
genre. `spectral_shape_fit` (the 64-band ribbon fit) is the real
replacement — it scores the full spectral shape instead of collapsing it
to one number, and actually discriminates genre where centroid never did.

**What's left to remove, when picked back up:**
- `_profile_score()`'s `centroid_fit` computation itself
  (`drop-ins/auto-vj-01/auto_vj.py`) and its entry in the `terms` dict
  fed to `term_values_by_candidate` telemetry.
- `spectral_centroid_mu`/`spectral_centroid_sigma` fields on
  `AudioProfile` (`unicornviz/audio/profiles.py`) and every profile's
  values for them (17 profiles set these).
- The 2026-09-04 mechanical `spectral_centroid_mu` recompute note in
  profiles.py's field comment, the centroid rows in
  `weights-and-thresholds.md`'s "Audio profile centroid sigmas" table,
  and the retirement/history writeups in both that doc and
  docs/adr/vj-system.md (mark superseded, don't delete the history).
- Tests that reference `spectral_centroid_mu`/`sigma`:
  `tests/test_audio_profile_deep_house_and_disable.py`
  (`test_deep_house_is_warmer_than_house_and_tech_house`),
  `tests/test_audio_profile_synthwave.py`
  (`test_synthwave_spectral_fields_are_calibrated`), and any others a
  fresh grep turns up at the time.
- `PERC_BAND_CENTERS_HZ` (`unicornviz/audio/analyzer.py`) — check whether
  anything else still uses it before removing; as of 2026-09-04 it's only
  documented as "left in place, unused for now" infrastructure for
  centroid recalibration.

This is a real refactor with test fallout, not a one-line change —
budget accordingly when it's picked up.

## 4. Separate `BeatTrackerV3` from `BeatTracker` (v2) entirely — DONE 2026-09-04

~~Owner, after a detector-side digression during the recommender tuning
session found `BeatTrackerV3.update()` calls `super().update()`...~~

**Resolved the same night**, not deferred after all — owner chose the
duplication path explicitly: "let's take the 'duplicate v2 code' route,
because that is the *proper* solution and drifting apart from v2
*should* occur because otherwise mod'ing what's under the v2 hood would
mean that v2 is a never-ending version that can't ever just be flipped
back 'stable working v2'! do that now." New class `_BeatTrackerV3Base`
(`beat_grid.py`) is a full independent duplicate of v2's ~3,045-line
pipeline; `BeatTrackerV3` now subclasses it instead of `BeatTracker`
directly. See docs/adr/vj-system.md "Duplicate, Not Share: BeatTrackerV3
Stops Inheriting From BeatTracker" for the full landing writeup,
including the tactus fold-up fix applied to the duplicate only (v2's own
copy stays descent-only, untouched) and why the "proper extraction"
alternative was correctly rejected (it would have tied future v3 tuning
to v2's protected-baseline behavior — the exact thing duplication avoids).

**What's still open from this thread, not resolved by the duplication
itself:**
- Live validation of the fold-up fix came back inconclusive (see the ADR
  entry immediately before the "Duplicate, Not Share" one) — detected
  BPM on a fresh drum & bass session barely moved. Two confirmed causes:
  genre evidence gets pushed based on whichever profile is *currently*
  active, and `house` was active more often than `drum_and_bass` across
  that session (a circular dependency: wrong BPM → recommender won't
  confidently pick the right profile → wrong genre evidence gets pushed
  → BPM stays wrong); and `v3_fold_suspect_mass` read exactly `0.0` on
  every row of that session, meaning the fold-suspect gate specifically
  never engaged even once (unexplained — genuine HMM-internals
  debugging, not attempted, correctly identified as past "sniff out a
  lead, don't get extreme").
- Whether the tactus-ascent fix itself is actually helping on drum &
  bass hasn't been cleanly isolated yet from the genre-evidence
  confound above — the one validation run mixed both changes together.
  Worth a dedicated re-test of the ascent fix alone (e.g. with genre
  evidence force-disabled) before concluding anything about it in
  isolation.

## 5. Redesign the live template/hybrid observation path's fold-handling

Found alongside item 4, same session: v3 already has machinery built
specifically to fix octave-fold ambiguity in its observation likelihood
(`_V3_FOLD_OBS_WEIGHT`, a symmetric up/down comb-evidence boost) — but
it's dead in production. It only exists in the `'comb'`/`'score'`
observation-source branch of `_v3_observation_likelihood()`
(`beat_grid.py`), while the live config uses `_V3_OBS_SOURCE='template'`,
a completely different branch with no fold-symmetric treatment at all.
`'hybrid'` mode (magnitude-weighted template matching — the template
system's own attempt at resolving exactly this) was tried during the v3
bake-off and found worse overall ("tested worse, kept for experiments" —
existing code comment), so it isn't a safe drop-in fix either.

This is real, unresolved: the shipped default has an acknowledged weak
spot for octave (and by extension triplet/3:2) fold ambiguity, and the
one existing attempt to fix it was rejected on evidence. Needs its own
dedicated investigation, not a quick pass — see docs/adr/vj-system.md
"Why house/peak-time/drum-and-bass Still Read as 'Competitive'" (Finding
4, gap #1) for the full trace of what's been tried and why it wasn't
picked up 2026-09-04.

## 6. Split the monolithic detector file(s) into their own modules

Owner, mid-implementation of item 4 above, watching a 3,045-line class
duplication land inside an already ~4,800-line `beat_grid.py`: "we
should be abstracting these systems into their own files probably
because monolithic monster files seems to be a habit someone developed."
Confirmed as deliberately post-soak, not a redirect for item 4 itself:
"maybe post-soak... the whole project's grand v2 plan starts precisely
with that issue lol" — i.e. this is the first item of an already-known,
larger planned initiative, not a new one-off ask.

**Current state, as of the item-4 landing:** `beat_grid.py` now holds
`BeatTracker` (v1, small), `BeatTracker` (v2, ~3,000 lines),
`_BeatTrackerV3Base` (v2's duplicate, ~3,045 lines), and `BeatTrackerV3`
(the HMM decision layer on top) — all four in one file, roughly 7,850
lines combined for just the detector. `auto_vj.py` (recommender +
director) is its own large file too, not sized here.

**Scoping this properly is future work, not attempted here** — at
minimum needs: deciding where the v1/v2/v3-base/v3 split lines should
actually fall (one file per engine generation? shared base module +
one file per engine?), confirming nothing depends on all four classes
resolving from a single `beat_grid` module namespace (dynamic-load
call sites like `_load_beat_grid_cls()` in tests, `load_auto_vj_module()`-
style loaders elsewhere), and the "grand v2 plan" context the owner
referenced (not detailed here — ask before assuming scope).

## 7. Next director version: convert all dwell/cooldown/swap-count constants to beats/bars/phrases

Owner, same night, right after supplying a full retune of the
director's mode/phrase dwell, drop cooldown, effect/postfx switch
timing, and scene/preset swap-count constants (see
`drop-ins/auto-vj-01/docs/director-timing.md` and docs/adr/vj-system.md
"Director Timing Retune"): "my honest read is for next version of
director we change ALL these to beats/bars/phrases!"

Every one of those ~18 constants is currently a flat wall-clock seconds
value per mood profile (`build_min_hold_s`, `climax_hold_s`,
`drop_cooldown_s`, `min_effect_dwell_s`/`max_effect_dwell_s`,
`climax_swap_min_s`, etc.) — most already get *some* tempo compensation
at read-time via `_timing_scale_from_bpm()` (a `[0.60, 1.50]` multiplier
around a neutral BPM), but that's a post-hoc scale factor on top of a
seconds base, not the same thing as the value being natively expressed
in musical units. The owner's proposal is to redefine the whole family
directly in beats/bars/phrases, matching how the detector's own dwell
windows already work (`_V2_DWELL_BARS`, `bpm_lock_dwell_bars`, and the
brand-new `_V3_ALT_SWITCH_COOLDOWN_BARS` — see docs/adr/vj-system.md "v3
Decisive-Rival Fast Path" for why bars beat seconds there: a bar count
is a consistent musical duration regardless of tempo, while a flat
seconds value covers wildly different bar counts at different BPMs).

**Not scoped or attempted here** — explicitly framed as "next version
of director," not a request to do now. Real design work needed before
picking this up: whether every constant in the family converts 1:1 or
some (e.g. `postfx_climax_interval_s`, already inherently short/rapid)
stay time-based; how `_timing_scale_from_bpm()`'s existing multiplier
interacts with or gets retired by a native bar-based value; whether
`effective_build_min_hold`'s phrase-bias reduction and the fastlane
0.35x factor still apply the same way once the base is bars instead of
seconds; and a real regression pass against `director-timing.md`'s own
table once the new units land.

## 8. Full fingerprint re-derivation against the corrected v3 baseline — QUEUED NEXT, not deferred

Owner, right after the `session_replay.py`/`beat_tracker_engine` harness
bug was found and fixed (see docs/adr/vj-system.md "The New-Baseline
Batch Silently Ran v2, Not v3"): "after we get full and complete
accurate baseline to the present exact state, we should fully
re-examine all the fingerprints measured against that baseline." Unlike
the other items on this list, this is the **immediate next step**, not
a someday item — sequenced right after the corrected 16-session v3
rerun lands.

**Why this matters now specifically:** essentially every per-profile
fingerprint currently shipped in `unicornviz/audio/profiles.py` —
`expected_bands`/`expected_bands_sigma` (the spectral-shape ribbons),
`vocal_hnr_mu`/`_sigma`, `vocal_fmr_mu`/`_sigma`, `zcr_mu`/`_sigma`,
`onset_density_mu`/`_sigma`, and `bpm_prior_mu`/`_sigma` — was fit from
corpus data captured before tonight's detector fixes landed, and (per
the harness bug above) likely from sessions that were *also* silently
running v2 rather than v3 regardless of when they were captured. Any
profile whose real produced tempo is genre-typically fold-prone
(`drum_and_bass`, `dubstep`, `rap_rnb`, `hyphy`, `ambient`/`chillstep` —
all flagged at various points this session with fold-contamination
caveats already in their own field comments) has fingerprints that may
partly encode detector fold error, not just genuine acoustic variance —
exactly the kind of contamination the existing `bpm_prior_sigma` HELD
BACK decisions (dubstep, rap_rnb) were trying to guard against with an
incomplete detector. A working, validated v3 (real fold-up handling,
decisive-rival fast path, genre-evidence consultation) changes the
premise those held-back decisions were made under.

**Not started here** — needs the corrected baseline to actually land
first, then a real methodology decision (same per-track-median-then-
robust-stat approach used throughout this session, or something new
given v3's different confidence/lock semantics) before touching any
profile field. Revisit the specific HELD BACK decisions (dubstep,
rap_rnb `bpm_prior_sigma`) explicitly once real v3 fold-corrected data
exists, rather than assuming the old caution still applies unchanged.
