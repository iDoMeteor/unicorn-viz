# ADR: VJ System — Beat Detection & Profile Architecture

Owner: unicorn-viz maintainers
Status: Active
Last updated: 2026-08-14

This document records architectural decisions for the live VJ runtime: beat
detection engine, lock state management, audio profile system, and the
interaction between the BPM detector and the VJ director.  Update it whenever
touching `drop-ins/auto-vj-01/beat_grid.py`, `unicornviz/audio/profiles.py`,
`[auto_vj]` config keys, or any Schmidt trigger / confidence threshold.

---

## Beat Detector Engine

Decision: BeatTracker v2 (ACF + phase-locked oscillator)

Selected over v1 (spectral flux IOI tracker) because ACF is robust to onset
density variation and doesn't conflate hi-hat events with kick events.

Key algorithm properties:

- 100 Hz envelope ring (800 samples, 8 s history)
- ACF run every 8 frames (~7.5 Hz updates)
- Gaussian BPM prior in log2-tempo space suppresses octave confusion
- Phase oscillator advances at bpm/60 Hz; onsets within ±`phase_tol` nudge it
- Confidence = phase coherence: fraction of last 32 onsets landing in phase window

Activate with `beat_tracker_engine = "v2"` in `[auto_vj]`.  v1 remains
available as fallback but is not tuned for current genre targets.  `v3`
(2026-07-18) is a v2 subclass that changes only `set_profile()` — see
"BeatTracker v3 — Frozen Tempo Prior" below.

---

## BeatTracker v3 — Frozen Tempo Prior + Shadow-Mode A/B (2026-07-18)

Decision: `BeatTrackerV3(BeatTracker)` overrides only `set_profile()`;
`ENGINE_VERSION` semver added to all three tracker classes; optional
shadow-mode A/B via `beat_tracker_shadow_engine`.

**Root cause investigated:** operator-reported "BPM tending toward 20 hot."
Two 2026-06 fixes for this symptom (deferred tracker-prior push;
`lock_band_pct` widening) were confirmed still in place — this was a third,
previously undocumented mechanism. Traced against real session logs
(`logs/autovj-20260708T171026.jsonl`, track "Alchemist"): the profile
recommender cycled through **four profile candidates in under 90 seconds**
on a single track (generic → peak_time → trance-candidate → psytrance).
Once `psytrance` (mu=145, sigma=0.16 — a tight, high prior) was applied via
`_sync_grid_audio_profile()` → `set_profile()`, the tracker's own `bpm`
readout drifted from a correct ~124 up through 140 → 142.9 → 146.3 over the
following ~35 seconds — with **no change in the actual audio's tempo**.
Cross-checked against "Playground (MEDUZA Remix)" (ground truth 120 BPM,
confirmed via Tunebat/SongBPM): locked at 127/135/144/146 across four
separate real sessions, never at the correct value.

The 2026-06-21 "Recommender → Tracker Profile Apply" fix deferred *when*
`set_profile()`'s prior update fires (a 12 s hold + 0.35 confidence gate on
the *sync*), but never addressed *whether* re-priming the ACF's Gaussian
prior is correct for a track whose real tempo hasn't changed — once the
deferred sync fires, v2's `set_profile()` still unconditionally overwrites
`_prior_mu`/`_prior_sigma`, and a tight high-confidence prior then drags
the comb-score argmax toward it over subsequent ACF updates. This is a
recommender-driven feedback loop, not an ACF octave/tactus error — ruled
out separately: neither a synthetic secondary percussion layer at various
gain/ratio combinations, nor a mismatched-profile-prior against a clean
click track, reproduced a "hot" drift in isolation (both tested negative
before the real-log trace pointed at the actual mechanism).

**Fix — `BeatTrackerV3`:** once confidently locked (`confidence >=
_PRIOR_FREEZE_CONFIDENCE = 0.55`, mirroring `AutoVJController.
_BPM_LOCK_CONFIDENCE`), `set_profile()` still applies the new profile's
`bpm_hint_min`/`bpm_hint_max` search-range clamp (a genuinely wrong tempo
remains correctable/boundable) but leaves `_prior_mu`/`_prior_sigma`
untouched. The prior is free to re-prime again the instant the lock is
lost — `_reset_tempo_lock()` (silence gap / new track) zeroes both `bpm`
and `confidence`, so the next `set_profile()` call after that falls
through to v2's full re-prime unchanged. Verified directly: locking
`BeatTracker`/`BeatTrackerV3` on a steady 124 BPM synthetic click track to
real lock-confidence (empirically ~65 s from cold start — phase coherence
needs wall-clock time to fill its 32-onset window), then applying a
psytrance-like profile — v2's `_prior_mu` snaps to the new profile's mu;
v3's does not move (`tests/test_beat_tracker_v3.py`).

**Engine versioning:** `ENGINE_VERSION` is now a class attribute on all
three tracker classes (`BeatGridTracker` = `'1.0.0'`, `BeatTracker` =
`'2.0.0'`, `BeatTrackerV3` = `'3.0.0'`) — MAJOR tracks the engine
generation (matches the `beat_tracker_engine` config name), MINOR/PATCH
track tuning changes within it.  Bump on any behavior-changing edit.

**Shadow-mode A/B (`beat_tracker_shadow_engine`):** an optional second
tracker instance runs on the same audio in parallel — same `update()` and
`set_profile()` calls as the active tracker — but never drives the
director/recommender; only its `bpm`/`confidence`/`ENGINE_VERSION` are
read, into `bpm_shadow`/`confidence_shadow`/`shadow_engine` fields on
decision-log (`_detector_snapshot()`) and sequence-corpus
(`_build_live_training_row()`) rows. This makes real sessions the A/B
dataset for validating a new engine before switching `beat_tracker_engine`
itself — see `docs/adr/training-model.md` "Shadow-Engine Scorecard
Comparison" for the packager-side reporting.  Ignored if set equal to the
active `beat_tracker_engine`. All shadow calls are wrapped in try/except
that only logs at debug level — a shadow-engine failure can never affect
the active engine or director.

### Addendum (2026-08-12): the freeze had no hysteresis — a real overnight regression, traced and closed

The "20 BPM hot" incident above was one *specific* trigger (a rapid
multi-profile-switch churn). A structurally related but distinct gap
survived the original fix: `set_profile()`'s freeze check
(`self._confidence >= self._PRIOR_FREEZE_CONFIDENCE`) was re-evaluated
fresh from the *instantaneous* confidence reading on every call, with no
memory of having been frozen a moment ago. Real tracks routinely dip
below `0.55` mid-track for entirely normal reasons — a breakdown, a quiet
passage — and the very next `set_profile()` call during that dip fell
through to a full re-prime, exactly as if the lock had been genuinely
lost.

**Found via a real overnight training session** (`favorites/g`,
~9.4 hours, 56 tracks, `sequence-corpus-20260812T011427Z.jsonl`). Owner,
live: "our bpm detector is really nailing it the vast majority of the
time," followed the next morning by a scorecard showing session-wide BPM
median `88.6` and `chillstep` at 83% of both recommended and active
profile — for a playlist that had locked correctly for months
(cross-checked against `favorites/b`/`c`/`d`, all pre-dating any of that
week's tuning: the same tracks, by title, consistently read `125-134
BPM`). Traced one track ("Thriller (Tim Cosmos 2025 Rework)")
chronologically through the overnight session and found the exact
mechanism:

```text
pos=0.5-169s   bpm=110.9-115.2  profile=house/peak_time  (correct-ish)
pos=189.6s     bpm=105.7        recommended flips to chillstep
pos=209.5s     bpm=102.5        profile=chillstep APPLIED; bpm keeps drifting down
...            ends that play around 99.5
[track replays -- tracker state carries over, no reset between plays]
pos=2.6s       bpm=83.9         profile=chillstep (inherits the drifted end-state)
...            drifts across the replay, ends around 84-96
[replays again]
pos=21.4s      bpm=87.7         profile=chillstep
...            ends around 83-84
```

Not a one-shot mistake — a **compounding, multi-play feedback loop**.
Once `chillstep` (`bpm_prior_mu=95`) got applied during a momentary
confidence dip, its soft prior nudged the next ACF estimate down, which
made the track look more like `chillstep` to the recommender, which
reapplied it, repeating for as many replays as the ~9-hour session gave
it time for — each replay inheriting the previous one's drifted-down
end state rather than starting fresh. `set_profile()`'s own soft-prior
design (not a hard search-range clamp, precisely to avoid this class of
risk — see P0-A, `docs/audits/2026-08-04-bpm-detector-audit.md`) reduced
the risk but didn't close it: a soft nudge sustained over many hours and
many repeats is still enough to ratchet a lock away from truth.

**Fix:** give the freeze the same acquire/release hysteresis this file
already uses for the BPM lock itself
(`AutoVJController._BPM_LOCK_CONFIDENCE`/`_BPM_LOCK_RELEASE_CONFIDENCE`,
same Schmidt-trigger shape) — new `_PRIOR_FREEZE_RELEASE_CONFIDENCE =
0.28` and a sticky `self._prior_frozen` flag (new `BeatTrackerV3.
__init__` override; the class previously inherited `BeatTracker.__init__`
unchanged). Once frozen, stays frozen through any dip down to the
release threshold, not just above the acquire one. `_reset_tempo_lock()`
still unfreezes correctly with no separate override needed — it drives
confidence to exactly `0.0`, well under `0.28`, so the hysteresis logic
naturally unfreezes on the next `set_profile()` call after a real
silence/track reset. `_DETECTOR_VERSION` → `1.0.0-rc.10`,
`_VJ_WEIGHTS_DOC_VERSION` → `28`.

**Also worth recording:** the "recommender fell off a cliff" and
"centroid_fit stuck on ambient" incidents earlier the same week (see
"Recommender `centroid_fit` Weight Cut..." below) were investigated and
fixed on their own terms, correctly, but this finding means at least
some of that week's apparent recommender instability may have had this
same root cause contributing underneath it — a drifting BPM changes
`tempo_fit` for every candidate simultaneously, which looks like
recommender noise from the recommender's side even when the recommender
itself is scoring correctly against a wrong input. Not re-litigated here;
flagged so it isn't mistaken for two unrelated coincidences.

**Verified:** `test_set_profile_stays_frozen_through_a_mid_range_
confidence_dip` and `test_set_profile_unfreezes_only_below_release_
threshold` added (`tests/test_beat_tracker_v3.py`); all 8 pre-existing
`BeatTrackerV3` tests still pass unchanged (none of them previously
exercised a partial dip, so none needed updating). Full suite green,
`ruff`/`bandit` clean.

### Addendum (2026-08-13): the freeze fix didn't stop a live-session drift the next morning — different mechanism, still open

Owner-reported, live: BPM read `70` and the profile had switched to
`chillstep` within a few songs of a fresh session start — the same
symptom as the overnight incident above, recurring on a much shorter
timescale despite the hysteresis fix from the previous night. Pulled
`logs/unicornviz_20260812_073106.log` (the session in question) and
found the timeline does **not** implicate the mechanism just fixed:

```text
07:32:27  primed peak_time  mu=130 σ=0.24
07:35:34  mood switch -> raver   (auto bpm 127)   -- correct lock
07:35:48  primed house      mu=122 σ=0.10
          ... 5 minutes, zero set_profile() calls ...
07:40:45  mood switch -> chill    (auto bpm 70)   -- self._grid.bpm itself now 70
07:40:53  recommender switches to chillstep
07:41:06  primed chillstep  mu=95 σ=0.50
```

`self._grid.bpm` (the value the mood auto-switcher reads directly, per
`AutoVJController._maybe_auto_switch_profile`) had already collapsed from
127 to 70 **before** any low-tempo profile reached `set_profile()` — the
chillstep priming at `07:41:06` is downstream of the drift, not its
cause. There is a five-minute gap with zero `set_profile()` calls in the
exact window where the number moved, and neither prior in effect during
that window (`peak_time` mu=130 or `house` mu=122, whichever the freeze
did or didn't block) sits anywhere near `70` in log2 space. This rules
out the reprime-cascade mechanism the 2026-08-12 fix closed — that fix is
doing what it was built to do, but this is a second, structurally
different failure: the tracker's own continuous per-frame ACF/candidate-
persistence walk can apparently drift a lock by nearly half over a few
minutes with **no external push at all** (no profile switch, no reprime).

**Not yet root-caused.** `log_decisions` was `false` for this session
(confirmed: `config.toml:139`), so there is no per-frame
`acf_confidence`/`candidate_history`/`drop_score` telemetry for the
window where the drift happened — the kind of data that made the
Thriller trace above traceable at all. Only three sparse INFO-level
milestone lines exist. Next step: enable `log_decisions` (or hit
Ctrl+T/Alt+T live) for the next session so a repeat can be traced
frame-by-frame instead of inferred from milestone logs. Not scoping a
fix until there's real data — same discipline as every other detector
finding in this document.

**Open design question raised in the same conversation, not yet decided
or built:** should a genre/profile ever be allowed to bias the raw tempo
estimator at all, even softly? Owner's framing: BPM sits higher in the
"truth chain" than genre — genre is partly *inferred from* BPM
(`tempo_fit` is a recommender input), so feeding a genre-driven prior
back into the tempo estimator makes truth flow in both directions
instead of one, which is the shape underlying every incident in this
section (the 2026-07-18 "20 BPM hot" investigation, the 2026-08-12
overnight compounding, and arguably this one once a root cause is
found). `BeatTracker.set_profile()`'s own docstring already half-agrees
— "a genre profile is soft evidence, not ground truth" — but still
performs a soft reweight of `_acf_prior` toward the profile's
mu/sigma; that soft nudge is the actual mechanism in both prior
incidents. A strict one-way version (recommender reads BPM; genre never
writes to the tempo estimator, soft or hard) would close this bug class
structurally, at the cost of losing genre priors as a disambiguator in
genuinely ambiguous half/double-time cases. Notably it would **not**
explain or fix this specific 2026-08-13 incident, since no
`set_profile()` call was even in the loop during the window where the
number moved — flagged here as a real, larger architecture decision to
make deliberately once the current mechanism is root-caused, not
something to fold into either fix in this section.

---

## Tempo-Hold Lock Gate Decoupled from the Confidence Blend (2026-08-13)

Same conversation as the addendum above, agreed by the owner as a
distinct, narrower fix (unrelated to the still-open drift): the
tempo-hold gate in `_estimate_tempo_acf()` —

```python
if self._bpm > 0.0 and self._last_t < self._tempo_hold_until_t and self._confidence >= 0.45:
    return
```

— decides whether this frame's ACF candidate is allowed to override the
current lock during the hold window. It was keyed to `self._confidence`,
the *published* ACF/phase blend, which is downstream of two things that
have nothing to do with this frame's ACF evidence quality: the `0.7/0.3`
ACF/phase blend ratio (an explicitly temporary stopgap — see the
Confidence blend row in `weights-and-thresholds.md`, due to be replaced
by a strength-weighted phase-coherence rework) and the
`primed_confidence` floor bump (a separate mechanism, for a separate
purpose). Every future retune of the blend ratio would silently change
how sticky this hold-gate is as a side effect, with no one having
decided lock stickiness should change.

**Fix:** gate on `acf_conf` (the already-computed raw local variable, a
few lines above) instead:

```python
if self._bpm > 0.0 and self._last_t < self._tempo_hold_until_t and acf_conf >= 0.45:
    return
```

`acf_conf` runs higher than the blended value on stable material (per
the confidence-blend note above, it "reaches 1.0 regularly" on stable
stretches, while the blend is pulled down by phase), so this makes the
hold modestly *stickier* on genuinely stable tracks, while making it
fully independent of the phase-confidence rework once that lands. No
interaction with the prior-freeze fix above — different function
(`_estimate_tempo_acf`, not `set_profile()`), different threshold,
different mechanism. Threshold value (`0.45`) carried over unchanged for
this first cut rather than re-picking it blind for a differently-shaped
input; real data will say if it needs retuning. `_DETECTOR_VERSION` →
`1.0.0-rc.11`, `_VJ_WEIGHTS_DOC_VERSION` → `29`.

---

## Genre Never Writes to an Established Tempo — `set_profile()`'s Confidence Gate Removed Entirely (2026-08-13)

Same conversation, later the same day: reviewing an offline replay of the
freeze-hysteresis fix (see below) against the two largest packaged
`favorites` corpora surfaced the sharper framing underneath every incident
in this section. Owner's own words: "since bpm is a major factor in
choosing genre, it really doesn't make sense for a genre detected outside
of the bpm to try to then shape the bpm... the bpm hasn't changed just
because genre doesn't agree 100% — that means there are other factors
out-weighing the bpm, not that the bpm is wrong."

This is correct, and it names the actual defect class more precisely than
either prior fix did. `tempo_fit` (a recommender scoring term) infers a
genre profile's fit partly *from* the tracker's own `bpm` — genre is
downstream of tempo in the dependency graph. `BeatTracker.set_profile()`
writing a profile's prior back into `_prior_mu`/`_prior_sigma` sends
information the other direction, upstream, into the very measurement the
genre inference depended on. Every incident that motivated `BeatTrackerV3`
— the 2026-07-18 "20 BPM hot" investigation, the 2026-08-12 overnight
compounding, and (per that day's addendum above) plausibly some of the
week's apparent recommender instability too — is this same backward edge
firing under different triggering conditions. The 2026-08-12 fix (acquire/
release hysteresis on the freeze) narrowed *when* the backward edge could
fire; it didn't remove the edge.

**Decision, owner call, both options offered ("remove it or nullify its
impact for now")**: nullify via a code change functionally equivalent to
removal, scoped to `BeatTrackerV3` only. `set_profile()` now primes the
prior only while `self._bpm <= 0.0` — before any tempo reading exists,
there is nothing for a rough genre-informed starting point to contradict,
so this is legitimate disambiguation, not truth-reversal. The instant a
real `self._bpm` is established, every subsequent call is a complete,
unconditional no-op — no confidence check, no acquire/release hysteresis,
no `_prior_frozen` state. All of that machinery (`_PRIOR_FREEZE_CONFIDENCE`,
`_PRIOR_FREEZE_RELEASE_CONFIDENCE`, the sticky flag, the custom
`__init__`) is deleted rather than left inert — it solved the wrong layer
of the problem and would only have been confusing dead weight going
forward. `BeatTracker`/v2 is deliberately left with the original
always-reprimes behavior, so `beat_tracker_shadow_engine = "v2"` continues
to give a live, real-session A/B between the old coupled behavior and the
new decoupled one — the same shadow mechanism that already validated the
2026-08-12 fix by showing v2 drifted just as badly with no freeze at all.
`prime_tempo()` (external ground-truth BPM, e.g. from the DJ mixer's own
per-track analysis) is unaffected — that source is genuinely authoritative
evidence, not an inference looping back from the detector's own output, so
it isn't the backward-flow case this change targets.

**Offline replay before the decision, for context:** with no way to fully
re-run the ACF/onset pipeline from archived corpus rows (no raw onset
timestamps or spectral data retained), a narrower replay was done instead
— reconstructing just the confidence-driven state machines rc.48
(freeze hysteresis) and rc.49 (hold-gate source) from recorded
`confidence`/`acf_confidence`/`profile` columns in the two largest
packaged `favorites` sets, `d` (57,736 rows, the healthiest session on
record — 100% lock coverage, median confidence `0.90`) and `g` (55,837
rows, the overnight-drift session traced in the 2026-08-12 addendum
above). Result: on `d`, zero of 67 profile-switch events would have
flipped behavior under the rc.48 hysteresis — a true no-op on healthy
data, as intended. On `g`, 9 of 46 switch events (~20%) fell inside the
exact mid-confidence dip band the hysteresis targets and would now have
been blocked — real, non-trivial confirmation the fix engaged on the
session it was built for. (The rc.49 hold-gate comparison is noted as
unreliable — no hold-window timing is recorded in the corpus, so the
"confidence vs acf_conf disagree" proxy measured across all frames, not
just frames where the real gate evaluates, overstating its apparent
impact.) This replay validated that rc.48 was working as designed; it did
not, on its own, surface the deeper one-way-coupling question — that came
from the owner's framing in the same conversation, not from the data.

**Not addressed by this change:** the still-open, not-yet-root-caused
2026-08-13 live-session drift (BPM 70/chillstep within a few songs, no
`set_profile()` call in the window where the number moved — see the
addendum above) is a different mechanism and this change would not have
prevented it, since no profile call was in the loop during that drift
either. Left as its own open item pending `log_decisions`-enabled
telemetry from a live session.

**Half/double-time disambiguation, raised in the same conversation:**
with genre no longer available as a disambiguator once locked, the
existing dedicated signals are the onset-density guard
(`_V2_DENSITY_FAST_RATIO`/`_V2_DENSITY_SCORE_RATIO`, penalizing a
candidate whose implied onset rate looks like double-time) and the
tactus fold-down bias (`tactus_preference_ratio`, biasing an ambiguous
half/double read toward the more "danceable" lane) — not the comb-filter
harmonic weighting (`acf_h / h`), which strengthens the fundamental's
overall candidate score but isn't itself a dedicated half/double
disambiguator. `kick_regularity` and `downbeat_confidence` are already
recorded per corpus row but not currently wired into disambiguation —
flagged as an unexplored signal, not scoped or built here.

**Verified:** `tests/test_beat_tracker_v3.py` rewritten for the new
model (`test_set_profile_is_noop_once_bpm_established`,
`test_set_profile_is_a_full_noop_when_bpm_established`,
`test_set_profile_stays_inert_regardless_of_confidence` replacing the
two hysteresis-specific tests that no longer apply; `test_set_profile_
fully_reprimes_when_bpm_zero`, `test_set_profile_reprimes_again_after_
unlock`, `test_set_profile_none_is_noop_like_v2`, and the v2-vs-v3 A/B
test kept with updated comments). Full suite green, `ruff`/`bandit`
clean. `_DETECTOR_VERSION` → `1.0.0-rc.12`, `_VJ_WEIGHTS_DOC_VERSION` →
`30`.

---

## BPM as a Hard Recommender Pre-Filter (2026-08-13, design agreed, deferred to RC2)

Owner's idea, prompted by watching the recommender dip into `chillstep`
(range `78-112`) during a solid high-120s/low-130s lock: instead of
`tempo_fit` being one weighted term among several that can be outvoted by
the others (exactly what happened there), gate the candidate profile set on
BPM plausibility *first*, and only score the surviving candidates on
centroid/zcr/onset/etc. Owner's framing: "bpm is our backbone... so what if
using bpm as our primary truth source at the top of the chain... we then
pick only the genres in that bpm range and THEN start with our other
intel." This is a strengthening of the genre-reads-BPM direction, not a new
coupling — it doesn't reopen anything the two entries above closed, since
genre still never writes back to the tempo estimator.

**Design decisions, owner calls:**

1. **Margin:** a flat **15% tolerance** beyond each profile's declared BPM
   range (not a literal hard cutoff at the raw hint boundary, and not a
   sigma-based Gaussian membership as this document originally floated) —
   e.g. a `118-126` range effectively gates at `~100.3-144.9`. Simpler to
   implement and reason about than a per-profile sigma computation.
2. **Coverage:** the union of all profiles' (margin-widened) BPM ranges
   should cover essentially all real-world BPMs the library contains; any
   gap found during implementation should be closed by widening the
   specific profile(s) with the gap, not by special-casing the gate logic.
3. **Empty-candidate-set fallback (should be rare once 2 is handled):**
   fall back to the profile whose range is *numerically nearest* the
   current BPM, rather than freezing on stale state or erroring.
4. **Sequencing, explicit:** not built now. `kr`/`dbc` (this document,
   section above and below) lands first and runs for a few days of real
   sessions before this is scheduled — bundled onto the RC2 punch list
   alongside the `drop_score` redesign and music-theory-audit items. See
   `docs/planning/auto-vj-drop-score-redesign-plan-2026-08-11.md` section 7.

**Expected effect once built:** directly prevents the triggering incident
(a profile whose range doesn't contain the locked BPM at all can no longer
win regardless of how well it scores on other terms) and, per the design
intent, should make the remaining weighted terms do real discriminating
work specifically *among* tempo-plausible, overlapping-range genres (e.g.
`house`/`tech_house`/`deep_house`, already documented as inseparable on
tempo alone) rather than being asked to out-vote a wrong tempo range
entirely.

---

## Tactus Fold-Down Gains a Region-Consistency Guard — kr/dbc Option A (2026-08-13)

Same conversation, first half of the kick-regularity/downbeat-confidence
disambiguation work agreed on earlier: `_estimate_tempo_acf()`'s tactus
descent loop only ever checked raw comb-filter score
(`cand_score >= best_score * tactus_preference_ratio`) when deciding
whether to fold to a candidate octave-down/2:3/3:4 lane. Score alone can't
distinguish "this candidate's period is a genuinely better musical pulse"
from "this candidate's period happens to score well but doesn't actually
land on the track's real accents" — it's a property of the ACF's own
windowed periodicity estimate, not a check against actual observed onset
timing.

**Fix:** the accept decision moved into a new method, `_tactus_fold_
accepted()` (mirrors `_acf_rival_score`'s existing pattern of a small,
directly-unit-testable helper rather than inline loop logic), which adds a
second, independent requirement: the candidate's `_analysis_region_
consistency()` (the same beat-grid self-consistency signal
`downbeat_confidence` and the large-jump guard already use) must not be
below `_TACTUS_REGION_GUARD_RATIO` (`0.70`, first-cut value) of the current
lane's own region-consistency. Inert before enough beat-position history
exists — `_analysis_region_consistency` returns `0.0` pre-lock, and the
guard is skipped whenever the current lane's own reading is `0.0`, so it
never blocks a fold during cold start, only once there's real evidence to
judge candidates against.

**Explicit design constraint, same conversation:** `tactus_preference_
ratio`/`tactus_check_bpm` must stay global constants (a single
per-session value, user-configurable via `config.toml`'s `[auto_vj]`
block) and must never become per-profile. A profile-driven fold-eagerness
value would reopen the exact truth-directionality bug the "Genre Never
Writes to an Established Tempo" entry above closed the same day: BPM →
recommender picks a profile → profile's fold-eagerness biases which
octave lane the tracker locks to → that changes BPM → feeds back into
which profile scores best. Owner's own framing when raised: "that could
trigger truth directionality problem again tho? lol" — correct, and now
written down as a hard constraint on this constant rather than left as an
open question next time someone considers making it profile-aware.

**Also validated, same conversation:** before touching anything, checked
whether the existing `tactus_preference_ratio = 0.55` value is actually
mistuned, using `runtime/dj_mixer_tracks.json` as ground truth for the
first time this session — cross-referenced 54 confidently-tracked songs
(confidence ≥ 0.55) across every packaged `favorites` corpus: `44/54`
exact match, `0` clean half-time/double-time folds, `3` borderline 2/3- or
3/4-ratio cases, all on "Edit"/"Remix"/"Mashup" titles (plausibly the
DJ-pool internal-tempo-variation case the owner flagged, not obviously a
tactus bug). No evidence the value needs retuning; left unchanged.

**Not done here:** kr/dbc option B — piping `kick_regularity` (currently
computed in `auto_vj.py`, independent of the tracker's own lock state)
down into `beat_grid.py` to modulate fold eagerness per-track from a real
acoustic measurement rather than a static constant. Owner's sequencing,
explicit: "a first...test.... then b....test/tweak/test, decide" — a
separate, larger interface change, scoped as its own follow-up.

**Verified:** four new tests in `tests/test_beat_tracker_v2.py`
(`test_tactus_fold_rejected_when_score_ratio_not_cleared`,
`test_tactus_fold_accepted_when_score_clears_and_no_beat_history_yet`,
`test_tactus_fold_rejected_when_candidate_fits_beat_spacing_much_worse`,
`test_tactus_fold_accepted_when_candidate_fits_beat_spacing_comparably`),
same monkeypatch-`_analysis_region_consistency` pattern already
established by `test_downbeat_confidence_blend_uses_documented_weights`.
Full suite green (1659 passed), `ruff`/`bandit` clean.
`_DETECTOR_VERSION` → `1.0.0-rc.13`, `_VJ_WEIGHTS_DOC_VERSION` → `31`.

---

## Kick Regularity Scales Tactus Fold Eagerness — kr/dbc Option B (2026-08-13)

Same conversation, immediately following option A above. `kick_regularity`
(`auto_vj.py`'s `_compute_kick_regularity()`) is a raw kick-band-energy
consistency reading over the last 16 raw onsets (0..1) — genre-independent,
already computed, already used elsewhere (`kick_regularity_fit` in the
recommender, Build/Drop director gating), but not wired into anything
inside `beat_grid.py`. Unlike `kick_regularity` itself, the tactus
mechanism it now feeds is entirely acoustic self-measurement, not a genre
inference — so this doesn't raise the truth-directionality question option
A's design constraint addressed; it's squarely inside the safe direction.

**Before building, a retroactive check** using the same `favorites`-corpus
data pulled for option A's ground-truth validation: the three borderline
tactus-fold cases found there ("Beat It (Nylze Edit)", "Blackout Riddim
(Clean)", "Uptown Funk (Nylze Edit Mashup)") had median `kick_regularity`
of `0.452`, `0.343`, and `0.634` respectively — all below the 56-track
library's `0.702` median-of-medians, two of them well below. This is real
evidence the hypothesis holds before any code changed: low kick regularity
correlates with the exact cases where the current tactus mechanism looks
shakiest.

**Implementation:** `BeatTracker.update()`/`BeatTrackerV3.update()` (v3
inherits `update()` unchanged) gain an optional `kick_regularity: float |
None = None` parameter, stored in `self._kick_regularity` and *persisted*
across calls that omit it (a caller doesn't have to recompute it every
frame). Defaults to `0.0` — the strictest setting — for any caller that
never supplies a reading at all, so an old test or a hand-built harness
gets conservative behavior, never silently the most permissive one.
`BeatGridTracker` (legacy/v1) also gained the parameter, accepted and
unused, purely for call-site compatibility — without it, a session
configured with `beat_tracker_engine = "legacy"` (or a legacy
`beat_tracker_shadow_engine`) would hit an uncaught `TypeError` on the
very next tick, since the shared call site in `auto_vj.py` now passes the
kwarg unconditionally.

New `_effective_tactus_ratio()` interpolates: at `kick_regularity = 1.0`
(classic four-on-the-floor) the effective ratio equals the validated
`tactus_preference_ratio` baseline, unchanged; it climbs toward
`baseline + _TACTUS_KICK_REGULARITY_SPREAD` (`0.30`, first-cut value) as
`kick_regularity` falls toward `0.0`. This is deliberately one-directional
— it can only make folding *stricter* than the already-validated baseline,
never more eager — so it can't introduce new risk on the material option
A's ground-truth check already confirmed works well; it only tightens the
mechanism specifically where the retroactive check found evidence of risk.
Applied at the `_tactus_fold_accepted()` call site via `_effective_tactus_
ratio()` in place of the raw `tactus_preference_ratio` read.

**Wiring, `auto_vj.py`:** `_compute_kick_regularity()` is called once per
tick, immediately before `self._grid.update(...)` (and passed identically
to `self._shadow_grid.update(...)` for A/B parity) — one frame stale
relative to that tick's own kick-band sample (appended later the same
tick), acceptable since kick regularity changes on a musical timescale,
not a per-frame one.

**Verified:** five new tests in `tests/test_beat_tracker_v2.py`
(`test_effective_tactus_ratio_equals_baseline_at_full_kick_regularity`,
`test_effective_tactus_ratio_defaults_to_least_eager_when_never_
supplied`, `test_effective_tactus_ratio_clamps_out_of_range_kick_
regularity`, `test_effective_tactus_ratio_climbs_as_kick_regularity_
falls`, `test_update_persists_kick_regularity_across_calls_when_
omitted`). Full suite green (1664 passed), `ruff`/`bandit` clean.
`_DETECTOR_VERSION` → `1.0.0-rc.14`, `_VJ_WEIGHTS_DOC_VERSION` → `32`.

**Not yet done:** this is a first cut per the owner's own sequencing
("a first...test.... then b....test/tweak/test, decide") — the spread
value (`0.30`) is reasoned and retroactively spot-checked against three
known cases, not validated against a real live-driven session. Next real
step is exactly what the owner asked for: let it run, then look at
whether it measurably reduces fold-related mismatches in the next
packaged corpus before considering it settled.

---

## kr/dbc Observability, Added Ahead of the First Live-Driven Session (2026-08-14)

Owner, before starting the first session with options A and B (rc.51,
rc.52) actually live: "are we logging this new data in the training kit?
if not, do that first so that we have that observability for the next
run." Correct call, and it caught a real gap: `kick_regularity` and
`downbeat_confidence` (the raw *inputs*) were already reaching the corpus
(the former via `_build_live_training_row()`, the latter via
`_detector_snapshot()`), but nothing about what the new mechanisms
*did* with them was recorded anywhere — no way to tell, after the fact,
whether the region-consistency guard or the kick-regularity scaling
actually engaged during a given session, only what the raw inputs looked
like. This is the same class of gap that made the 2026-08-13 morning
drift (see the addendum on `set_profile()`, above) untraceable — no
`log_decisions` telemetry for the mechanism in question at the moment it
mattered.

**Added, `beat_grid.py`:** two new public properties on `BeatTracker`
(inherited by `BeatTrackerV3`) — `kick_regularity` (mirrors the private
`_kick_regularity` the tracker is actually using, confirming round-trip
correctness of the rc.52 wiring, not just what `auto_vj.py` computed) and
`effective_tactus_ratio` (the live value of `_effective_tactus_ratio()`,
so its deviation from the `tactus_preference_ratio` baseline is directly
visible over a session rather than needing to be recomputed from
`kick_regularity` after the fact). Three new session-cumulative counters
— `tactus_fold_accepted_count`, `tactus_region_reject_count` (option A's
guard specifically), `tactus_score_reject_count` — incremented inside
`_tactus_fold_accepted()` itself, one per outcome, so a session's total
tells you directly whether/how often each guard actually fired, not just
whether the code path exists. Monotonically increasing, same convention
as `beat_index`/`onset_count`.

**Added, `auto_vj.py`:** all five fields wired into `_detector_snapshot()`
with `getattr(..., default)` reads, defaulting to `0.0`/`0` for `v1`
(`BeatGridTracker`, no tactus mechanism at all) rather than omitting the
keys — downstream corpus/decision-log consumers expect a stable row
schema. `_detector_snapshot()` is the single choke point that already
reaches both the decision-log (`mark()` calls) and every sequence-corpus
row (`_sequence_director_fields()`), so this one change gives full
coverage in both places without touching either logging path directly.

**Deliberately not a weights/behavior bump:** no constant changed, no
decision logic changed (the counters are a pure side effect of an
existing branch, the properties are pure reads) — `_DETECTOR_VERSION` and
`_VJ_WEIGHTS_DOC_VERSION` are unchanged, per CLAUDE.md's explicit
exemption for logging-only changes. The drop-in's own `__version__` still
bumped (`1.0.0-rc.53`), since new corpus/decision-log fields are a real,
user-facing addition to what the owner and training pipeline can see.

**Verified:** seven new tests in `tests/test_beat_tracker_v2.py`
(counter-increment behavior per outcome, counters starting at zero, both
new properties matching their underlying private state) and two in
`tests/test_auto_vj_shadow_engine.py`
(`test_detector_snapshot_includes_kr_dbc_fields_when_grid_has_them`,
`test_detector_snapshot_kr_dbc_fields_default_when_grid_lacks_them`).
Full suite green (1672 passed), `ruff`/`bandit` clean.

---

## Strength/Band-Weighted Phase Coherence — the Real Fix (2026-08-14)

The fix deferred since the 2026-08-11 confidence-blend addendum ("Real
fix (agreed, not yet built): weight phase coherence by onset strength/
band so kick/bass-region onsets count toward the hit-rate and hi-hat/
fill onsets don't count against it"), built the same day the owner
launched the first kr/dbc-driven live session and asked for it to run in
parallel.

**Root problem, restated:** `_phase_confidence` was a flat hit-rate —
every onset in the rolling `_V2_COHERENCE_WINDOW` counted equally toward
"did onsets land on-beat," regardless of whether it was a kick (expected
to land on-beat) or a hi-hat/fill (not expected to, in syncopated or
busy material). Real session data showed this structurally capped
`phase_confidence` around `~0.3-0.4` even during genuinely stable,
correctly-locked stretches — not because the lock was bad, but because
real music generates onsets a correct lock has no business explaining
away. The 2026-08-11 fix (confidence blend `0.5/0.5 → 0.7/0.3`) was an
explicit stopgap standing in for this, not a resolution.

**Fix, core (`unicornviz/audio/analyzer.py`):** `OnsetEvent` gains
`band_weight: float = 1.0` — the fraction of the onset's flux that came
from the bass band, computed at the exact moment of detection from
`data.bass_flux` (already computed for downbeat detection) relative to
total `flux`, clipped to `[0, 1]` since `flux` includes an
unattributed `rms_rise` term. Default `1.0` preserves the old "every
onset is fully diagnostic" behavior for any caller that doesn't supply
it (backward compatible — `test_audio_blocking_reader.py`'s direct
`OnsetEvent(t=..., strength=...)` construction still works unchanged).

**Fix, `beat_grid.py`:** `_absorb_onset()` (previously `_strength`,
underscore-prefixed and unused — the strength parameter existed but did
nothing) now computes `weight = band_weight * min(1.0, strength /
_V2_PHASE_STRENGTH_SATURATION)` (saturation `2.0`, "roughly one MAD unit
above threshold" reaches full weight) and uses it to feed two new
parallel deques, `_coherence_hit_weight`/`_coherence_total_weight`,
replacing the flat `_coherence_buf`. `_phase_confidence` becomes `sum(hit
weights) / sum(total weights)` — a strong, bass-heavy onset that misses
still drags confidence down hard (real evidence against the lock,
unchanged from before); a weak or treble-heavy onset barely moves it
either way, hit or miss (it was never expected to land on the beat, so
it isn't evidence against a lock when it doesn't). Left unchanged
(rather than reset toward `0.0`) when a window's total weight is
`~0`, so a stretch of nothing but weak treble onsets doesn't produce a
noisy, near-meaningless ratio.

**Confidence-blend ratio deliberately untouched:** `0.7/0.3` stays as-is
in this commit. This rework is the thing the ratio was compensating for,
but the owner's framing was explicit: evaluate `phase_confidence`
against real session data with the rework live before touching the
ratio, and if discrimination still isn't good enough, the stated
fallback is `0.8/0.2` (more ACF-weighted) — not an assumed revert toward
`0.5/0.5`.

**Verified:** three new tests in `tests/test_analyzer_onset_dedup.py`
using synthesized sine bursts at 80 Hz (bass) vs 8000 Hz (treble) to
confirm `band_weight` actually discriminates on real spectral content,
not just a formula in isolation, plus a default-value test. Six new
tests in `tests/test_beat_tracker_v2.py` covering: strong-bass-hit pushes
confidence toward `1.0`; strong-bass-miss drags it toward `0.0`;
weak-treble-miss barely dents an established high confidence; a
same-magnitude bass-miss hurts more than a treble-miss (the core
discrimination claim, tested comparatively); a zero-band-weight onset
never moves confidence and doesn't divide-by-zero; the `band_weight`
parameter defaults to `1.0` for legacy call sites. Full suite green
(1683 passed), `ruff`/`bandit` clean. `_DETECTOR_VERSION` →
`1.0.0-rc.15`, `_VJ_WEIGHTS_DOC_VERSION` → `33`.

---

## Confidence Blend `0.7/0.3` → `0.8/0.2` — Live Fallback Applied (2026-08-14)

Same day as the strength/band-weighted phase-coherence rework above,
next live session. Owner's read, first song in: BPM and genre both
"totally nailing it," but confidence still read too low even with the
rework live. Per the fallback the owner pre-stated in the rc.54 commit
message ("stated fallback if discrimination still isn't sufficient is
`0.8/0.2`, not an assumed revert toward `0.5/0.5`"), applied that
directly rather than guessing at a new value — both blend sites in
`beat_grid.py` (`_estimate_tempo_acf()` and `_absorb_onset()`) moved
from `0.7 × acf + 0.3 × phase` to `0.8 × acf + 0.2 × phase`.

**kr/dbc considered and deferred, not adopted here.** Mid-conversation,
asked directly whether `kick_regularity`/`downbeat_confidence` had been
folded into this blend — they hadn't; both remain separate gates
(`kick_regularity` scales tactus-fold eagerness via
`_effective_tactus_ratio()`; `downbeat_confidence` gates analysis-driven
downbeat acceptance via `_analysis_downbeat_confidence_min`), never
confidence-blend terms. Owner's call: `downbeat_confidence` specifically
is "an interesting addition" worth considering for the blend, but
explicitly held pending how this run performs — noted here as a
possible future tweak, not queued for implementation. If it does get
picked up, it would need its own flag-and-confirm pass per the standing
detector-change policy, same as this ratio bump got.

**Verified:** full `test_beat_tracker_v2.py` suite green (64 tests) at
the new ratio; no test asserted the literal `0.7/0.3` constant, so
nothing needed updating for the new value itself.
`_DETECTOR_VERSION` → `1.0.0-rc.16`, `_VJ_WEIGHTS_DOC_VERSION` → `34`,
`auto_vj.py` `__version__` → `1.0.0-rc.55`.

---

## `_V2_PHASE_TOL` Reverted to 0.18 + Three-Term Confidence Blend with `downbeat_regularity` (2026-08-14)

Same day, next live session after the 0.8/0.2 fallback above. Two owner
calls together: `_V2_PHASE_TOL` felt "kinda hot" at `0.14` on live
material — reverted to the original `0.18` (see the row's own 2026-08-10
history; `0.14` was never a validated value, just "sounds pretty tight
against your test" on one session). And: pick up the `downbeat_confidence`
possible-tweak noted in the entry above — fold it into the confidence
blend at `0.2`, cutting `acf` from `0.8` to `0.6` to make room (`phase`
left at `0.2`, unchanged). Sums to `1.0`.

**Caught before implementing, not after:** asked directly whether this
creates a feedback loop — does `downbeat_confidence` influence
`phase_confidence`/`acf_confidence`? Checking `_compute_downbeat_confidence()`
(the existing per-bar `_last_downbeat_confidence` producer) found the
answer is more subtle than a clean no. `dbc` never feeds back into
`phase_confidence`/`acf_confidence` (correct, no cycle in that direction),
but the reverse isn't true: `_compute_downbeat_confidence()` already
blends `30% phase_confidence + 15% acf_confidence` internally, and — the
sharper problem — when `analysis_mode_enabled` is `False` (the project
default, including the currently-running live session), it skips that
blend entirely and just `return float(self._confidence)` verbatim. Had
`_last_downbeat_confidence` been folded into `self._confidence` as
planned, that would have made confidence at bar N partly equal to
confidence at bar N-1, compounding indefinitely — a genuine echo, not
fresh evidence, and it would have been silent (no crash, no obviously
wrong number, just steadily wrong dynamics).

**Fix:** new `_downbeat_regularity(now)` method, used in the blend
instead of `_last_downbeat_confidence`. Reuses only the two
`_compute_downbeat_confidence()` terms that never read
`phase_confidence`/`acf_confidence` — beat-position region consistency
(`_analysis_region_consistency()`) and on-beat density (now factored out
into a shared `_beat_position_density()` helper so the two methods can't
drift apart) — renormalized from their original `0.45`/`0.10` weights to
sum `1.0` (`÷ 0.55`). Genuinely independent of `acf`/`phase`: verified by
a test that sets `_acf_confidence`/`_phase_confidence` to `0.0` then
`1.0` and asserts `_downbeat_regularity()`'s return value doesn't move.

**Known limitation, documented rather than hidden (superseded the same
day — see the next entry):** `_analysis_region_consistency()` itself
returned a constant `1.0` when `analysis_mode_enabled` was `False` (see
its own early-return). So with the project's default config,
`_downbeat_regularity()` was a near-constant `~0.82` floor (`0.45 × 1.0 ÷
0.55`) plus whatever on-beat density contributed on top — safe (no loop)
but not a strongly discriminating signal unless `analysis_mode` was
enabled. Flagged as worth revisiting; got revisited within the hour once
the owner asked what `analysis_mode` actually did.

**Verified:** `test_beat_tracker_v2.py` — `_V2_PHASE_TOL == 0.18`;
`_downbeat_regularity()` unaffected by `acf_confidence`/`phase_confidence`
extremes; the three-term blend formula matches `0.6*acf + 0.2*phase +
0.2*dbc` exactly for known inputs; and the specific regression this
whole investigation was about — seeding `self._confidence` (and
`_last_downbeat_confidence`) with an extreme prior value before a call
does not move the freshly recomputed confidence at all. Full
`test_beat_tracker_v2.py` suite green (68 tests). `_DETECTOR_VERSION` →
`1.0.0-rc.17`, `_VJ_WEIGHTS_DOC_VERSION` → `35`, `auto_vj.py`
`__version__` → `1.0.0-rc.56`.

---

## `analysis_mode_enabled` Removed Entirely — Always On (2026-08-14)

Same day, immediately after the entry above. Owner asked what
`analysis_mode_enabled` precisely did (prompted by the "known limitation"
note above) and separately whether Ctrl+T enables it (it doesn't — Ctrl+T
only toggles the corpus writers + decision log via `enable_trainers()`;
`analysis_mode_enabled` is a `config.toml`-only value read once at
`BeatTracker.__init__`, no runtime setter anywhere in the codebase).

Answering precisely required enumerating every branch gated on it:

1. `_append_beat_position()` — a no-op when off; `_beat_position_map`
   never fills.
2. `_analysis_region_consistency()` — hardcoded `1.0` when off instead of
   a real computed score.
3. `_compute_downbeat_confidence()` — short-circuited to
   `return self._confidence` verbatim when off, not an independent signal.
4. The large-tempo-jump guard's region-consistency cross-check — inert
   when off.
5. Downbeat firing itself — unconditional every bar when off, instead of
   gated by `analysis_downbeat_confidence_min`.

Owner's reaction: this means every install that never explicitly set
`analysis_mode_enabled = true` (the packaged default was `false`) was
running a measurably weaker detector — unconditional downbeats, no
jump-guard cross-check, fake downbeat confidence — without any way to
notice, since none of it errors or logs differently. "We don't want to
cripple our guy when we roll out and not even realize it." The owner's
own `config.toml` already had it set `true` (has, seemingly, always),
which is exactly the trap: it worked fine for the one machine that always
had it on, and would have shipped broken-by-default anywhere else.

**Decision:** don't just flip the default — remove the flag. Given the
choice between "default `true`, stays a toggle, big warning comment" and
"rip it out, hardcode always-on," owner chose the latter: no way to ever
disable it again, not even by accident.

**Change:** `_analysis_mode_enabled` field deleted from `__init__`; all
five call sites above collapsed to their always-on branch (the
conditional and the off-branch code both removed, not just short-
circuited). `analysis_mode_enabled` removed from `config.toml` (the
owner's own file — normally never touched without asking first, but
removing this exact key is what was explicitly requested) and
`config.full.example.toml`. The five tunable parameters underneath it
(`analysis_map_beats`, `analysis_region_min_beats`, `analysis_region_tol`,
`analysis_region_confidence_min`, `analysis_downbeat_confidence_min`)
are untouched and remain config-driven — only the on/off switch is gone.

**Direct consequence for the previous entry's "known limitation":**
`_downbeat_regularity()`'s region-consistency term is no longer a
`~0.82` floor under default config — it's always the real computed
signal now, since there's no more "off" state for it to degrade into.

**Test fallout, all expected and fixed in the same commit, not silently
tolerated:** two tests broke from turning gating on unconditionally.
`test_is_downbeat_fires_exactly_once_per_four_beats` had assumed
unconditional downbeat firing (true before this change, since the test
never set `analysis_mode_enabled`); with gating always active, the very
first bar can land below `analysis_downbeat_confidence_min` before
`phase_confidence`/`acf_confidence` converge, suppressing at most one
extra downbeat on top of the already-documented trailing-partial-bar
effect — widened from an exact match to a tolerance of at most 1, with
the reasoning recorded inline. And `test_confidence_blend_is_six_two_two`
(this session's own new test, added for the previous entry) had assumed
region consistency reads as a constant `1.0` on a fresh tracker — no
longer true now that it's a real computed value requiring beat-position
history; rewritten to lock onto a steady click track first and read back
the actual `acf_confidence`/`phase_confidence`/`downbeat_regularity`
values the call used rather than asserting hardcoded expectations. A new
`test_analysis_mode_enabled_config_key_is_inert` guards against a future
refactor reviving the flag: passing the old key (`True`, `False`, or
omitted) must be a complete no-op.

**Verified:** full `test_beat_tracker_v2.py` suite green (68 tests, after
the two fixes above), plus 271 tests across
`test_beat_grid_tracker_v1.py`/`test_beat_tracker_v3.py`/
`test_auto_vj_phrase_structure.py`/`test_bpm_detector_audit_regressions.py`/
`test_bpm_eval.py`/`test_corpus_writers.py`/`test_auto_vj_shadow_engine.py`/
`test_analyzer_detector_bands.py`/`test_package_training_set.py`.
`_DETECTOR_VERSION` → `1.0.0-rc.18`, `_VJ_WEIGHTS_DOC_VERSION` → `36`,
`auto_vj.py` `__version__` → `1.0.0-rc.57`.

---

## `_V2_PHASE_TOL` 0.18 Regressed v3/v2-Shadow Agreement — Reverted to 0.14 (2026-08-14)

Same day, next live session after the 0.18 + three-term-blend entry
above. Owner's read after a bit of listening: "this version seems to
suck but last run didn't."

**Found the regression with data, not just the feeling.** The shadow
engine (still on at this point — see the disable/re-enable entries
elsewhere this same day) gave a controlled-ish before/after: the
`favorites/i` bucket session ran before `0.18` landed, and the very next
live session ran right after. Comparing v3/v2-shadow BPM agreement on
the five tracks common to both:

| Track | Before (0.14) | After (0.18) |
|---|---|---|
| Take Off (Blastersboyz Remix) | 100% agree (v3=116.09, v2=115.98) | 0% agree (v3=136.27, v2=121.07) |
| Boom Clap (Ayfull Remix) | 93% agree | 0% agree |
| Rock Wit U (Nylze Edit) | 84% agree (v3=120.52, v2=119.13) | 12% agree (v3=141.91, v2=133.66) |
| Sexy Bitch (DJ Roller Club) | 100% agree | 100% agree (unaffected) |
| Madonna Hung Up (Anzo) | 100% agree | 100% agree (unaffected) |

Three of five tracks collapsed from near-perfect agreement to near-total
disagreement, and on the affected tracks v3's own BPM reading moved
meaningfully higher — "Take Off" reading 136 instead of 116 is not a
clean octave error, just wrong. The two unaffected tracks are both
straightforward four-on-the-floor material; the pattern looks specific
to syncopated/complex-rhythm content, consistent with the original
2026-08-10 concern that a wider phase tolerance "counts genuinely
off-grid onsets... as on-beat" (see `_V2_PHASE_TOL`'s own field comment).

**The only behaviorally-relevant change between the two sessions was the
single commit that bumped `_V2_PHASE_TOL` to `0.18` and switched the
confidence blend to three terms** — both landed together, so this alone
doesn't prove which one is responsible. Decision: revert `_V2_PHASE_TOL`
back to `0.14` first, in isolation, and re-evaluate before touching
`downbeat_regularity`'s weight in the blend — a two-step revert rather
than reverting both at once, so whichever step (if either alone) fixes
it is known rather than assumed.

**Noted irony, flagged rather than acted on unilaterally:** this
regression was caught by the shadow-engine A/B comparison, which had
just been scheduled for disable the same day (see the "v2 shadow
disabled pending v4" entries elsewhere). Re-enabled rather than
disabled, pending this investigation settling.

**Verified:** full `test_beat_tracker_v2.py` suite green (68 tests) —
`test_v2_phase_tol_is_018` renamed/updated to assert `0.14` again (the
only test with a hardcoded expectation on this constant).
`_DETECTOR_VERSION` → `1.0.0-rc.19`, `_VJ_WEIGHTS_DOC_VERSION` → `37`,
`auto_vj.py` `__version__` → `1.0.0-rc.58`.

---

## 2026-08-14 Session Summary — RC1-Candidate Detector Configuration

One long session, rc.53 through rc.58, closing out on a configuration
validated against ~90 minutes of real, organic (non-mixer-primed)
session data across two full training-set buckets
(`favorites/j`, `favorites/k`) plus a third in progress
(`training-house-01/a`). Recording what shipped, what was learned, and
the current settings snapshot in one place, since the individual
entries above are each scoped to a single change.

### What shipped (rc.53 → rc.58)

- **rc.53** — kr/dbc observability (`kick_regularity`,
  `effective_tactus_ratio`, three tactus-guard counters) logged ahead
  of the first live-driven session.
- **rc.54** — strength/band-weighted phase coherence: `_phase_confidence`
  weights each onset by `band_weight` (bass fraction of flux) × a
  saturating function of `strength`, instead of counting every onset
  equally. The real fix for `phase_confidence`'s structural ~0.3-0.4 cap.
- **rc.55** — confidence blend `0.7/0.3` → `0.8/0.2` ACF/phase (the
  pre-stated fallback once rc.54 alone didn't raise confidence enough).
- **rc.56** — `_V2_PHASE_TOL` `0.14` → `0.18` + blend becomes three-term
  (`0.6×acf + 0.2×phase + 0.2×downbeat_regularity`, a new,
  deliberately phase/acf-independent method — region consistency +
  on-beat density only, avoiding the feedback loop a naive
  `_last_downbeat_confidence` reuse would have caused).
- **rc.57** — `analysis_mode_enabled` removed entirely, hardcoded
  always-on. It had been an opt-in flag defaulting `false`; every
  install that never explicitly enabled it ran degenerate downbeat
  gating, a jump-guard with no region-consistency cross-check, and a
  fake `downbeat_confidence`. Discovered while explaining what the
  flag did — turned into a real fix, not just an explanation.
- **rc.58** — `_V2_PHASE_TOL` `0.18` → back to `0.14`, reverting a real,
  data-confirmed regression (v3/v2-shadow agreement 84-100% → 0-12% on
  3 of 5 tracks). See the two entries directly above.

Alongside the detector work: training-kit-01's packager fixed twice
(0.15.10 — a fabricated "Essentia BPM" that was actually always the
detector's own output, invalidating every past `external_agreement`
score; 0.15.11 — a `"meta:||"` fake per-song entry from boundary rows
with zero identifying metadata). `beat_tracker_shadow_engine` was
disabled, then re-enabled the same day once it caught the rc.56
regression live — it's the mechanism that made this whole
investigation possible, worth remembering next time disabling it looks
tempting.

### What we learned, beyond the individual fixes

- **The v3/v2 shadow comparison isn't as clean a baseline as it looks.**
  `BeatTrackerV3` only overrides `set_profile()` — `_absorb_onset()`/
  `_estimate_tempo_acf()` (and therefore the confidence blend, phase
  tolerance, everything tuned this session) are shared code. A
  v3/v2 disagreement is really "how do these formulas interact with
  v3's freeze-while-locked behavior vs. v2's constant re-priming," not
  a clean new-code-vs-old-code A/B. Keep this in mind before reading
  future shadow-comparison numbers as more isolating than they are.
- **`prime_tempo()`'s "external ground truth is always authoritative"
  assumption (P0-B, `docs/audits/2026-08-04-bpm-detector-audit.md`,
  2026-08-04) doesn't hold universally.** Found live: "Keep Moving
  (Original Mix)" — dj-mixer tagged it 77 BPM, the detector had
  independently, correctly locked 129.18 BPM at 0.82-0.85 confidence,
  and the mixer's tag won anyway, unconditionally, with no sanity
  check. Confirmed the fix by replaying the same track later in a
  media-01-only (unprimed) session: clean 125.42 BPM, v3/v2 exact
  agreement. **Flagged as an open question below, not fixed** — a
  detector-trust-model change needs its own sign-off, not a
  same-night tuning tweak.
- **Two months of historical "0.900 confidence, 100% lock coverage"
  training buckets were an artifact, not detector performance.**
  Every one of them (`garbage/e`, `library/a`/`b`, `favorites/a-d`,
  `training-house-01/a`, spanning 2026-08-09 through 2026-08-11
  ~10:14) was a continuous dj-mixer-sourced session — the same
  `prime_tempo()` confidence floor dominating for the session's
  near-entire duration, not organic audio-driven confidence. Any BPM
  tuning done by eyeballing those sessions' numbers was tuning against
  a floor, not against the detector's real behavior. Sessions from
  `favorites/e` onward (2026-08-11 ~11:13+) are real, organic,
  media-01-sourced data — that's the trustworthy baseline going
  forward for anything BPM-detector-related.
- **A LLM detector score being harsh doesn't automatically mean it's
  wrong** (contrast with the fabricated-Essentia case above, where it
  was) — `favorites/j`'s 2.75/5 explicitly cited "low shadow engine
  BPM agreement (30.4%)," which was the real rc.56 regression, not a
  hallucination. Worth reading LLM rationale for whether it's citing
  something checkable against real corpus data before dismissing or
  trusting it either way.
- **The two-to-three tracks that stayed hardest to agree on all
  night — "Take Off (Blastersboyz Remix)," "Rock Wit U (Nylze Edit),"
  "You And I (Original Mix)"** — were already imperfect before any of
  tonight's changes (`Rock Wit U` was 84% agreement even on the
  original clean baseline, never 100%). Owner's read: "those are both
  super difficult songs" — genuinely hard material, not a lingering
  bug. `favorites/k`'s full-session numbers back this up: 90.6% overall
  agreement, 14 of 16 tracks at 97-100%, only those same few tracks
  short of it.

### Current settings snapshot (2026-08-14, end of session)

```toml
[auto_vj]
beat_tracker_engine = "v3"
beat_tracker_shadow_engine = "v2"   # re-enabled; see note below
analysis_downbeat_confidence_min = 0.30
log_decisions = true
live_training_enabled = true
sequence_training_enabled = true    # separate key from live_training_enabled -- both
                                     # needed for headless runs to capture the rich
                                     # per-tick sequence corpus, not just live-corpus
```

```text
_V2_PHASE_TOL = 0.14
Confidence blend: 0.6*acf_confidence + 0.2*phase_confidence + 0.2*downbeat_regularity
analysis_mode: always on (no config key -- see rc.57 above)
_DETECTOR_VERSION = 1.0.0-rc.19
_VJ_WEIGHTS_DOC_VERSION = 37
auto_vj.py __version__ = 1.0.0-rc.58
```

### RC1-candidate status

**Validated as a strong candidate for the detector's own eventual RC1
tuning generation** — real organic session data (`favorites/j`,
`favorites/k`, `training-house-01/a` in progress), 90.6% v3/v2
agreement on a full 56-minute mixed-difficulty set, 100% agreement on
an easy house set, no fabricated telemetry in the validating data (the
`prime_tempo()`/Essentia/`meta:||` artifacts above are all excluded or
fixed). **Not** a claim that every open item is resolved — two things
explicitly remain open, tracked below rather than blocking this note:
(1) `prime_tempo()`'s unconditional external-trust model, (2)
`downbeat_regularity`'s real contribution is still not isolated from
`_V2_PHASE_TOL` by a controlled test — both flagged in Open Questions,
neither is a known-broken blocker, both are "worth a closer look
before calling the tuning fully final."

**`beat_tracker_shadow_engine` is currently re-enabled** — turn it back
off (empty/absent) once this configuration is confirmed stable across
a few more sessions, or leave it on if the owner decides the
regression-catching value outweighs the CPU cost going forward; either
is a legitimate call, not a leftover TODO.

---

## Sigma-Matches-Hint-Band Pass: 16 Profiles, Reversing the 2026-08-10 Independence Note (2026-08-14)

Same day, digging further into the hint-alignment investigation above.
Complete mu/sigma/hint table pulled for all 16 profiles; the pattern was
stark — almost every profile's authored `bpm_hint_min`/`max` sat at only
0.2-0.5σ from `bpm_prior_mu`, far tighter than a real 1σ `tempo_fit`
tolerance. Recommended fix at the time: loosen the packager's
`hint_alignment_pct` diagnostic to match the real (looser) sigma-derived
tolerance, leave the hand-authored hint bands alone.

**Owner's call: the opposite direction.** "i think that's the exact
opposite of your recommendation? :p" — correct. The owner put real time
into hand-dialing `bpm_hint_min`/`max` as the actual intended per-genre
expectation; rather than loosen the diagnostic to match an
independently-authored sigma, `bpm_prior_sigma` now **derives from** the
hint band instead — reversing the 2026-08-10 house-family consolidation's
explicit "independently authored from mu/sigma, not derived from either"
design.

**Three explicit value changes, owner-specified:**

- `electronic`: re-confirmed `enabled=True` after a brief accidental
  disable mid-conversation — this is the owner's deliberate control pair
  for validating the vocal-presence discriminator actually works (house
  has vocals, electronic doesn't, every other axis — including now
  sigma — matches exactly).
- `hardstyle`: `bpm_hint_min` 145→155. Surfaced a real inconsistency
  before implementing: `bpm_prior_mu` (150) would sit *outside* its own
  new hint range (155-165). Resolved via question to the owner: `mu`
  moves to 160 (midpoint), matching the treatment every other profile
  gets rather than leaving an asymmetric, off-center prior.
- `drum_and_bass`: `bpm_hint` 168-178 → 165-180 (mu=174 already sat
  inside both, no shift needed).

**Formula:** for each profile, `sigma = max(|log2(hint_min/mu)|,
|log2(hint_max/mu)|) * 1.05` (log2 space, matching `tempo_fit`'s own
comparison basis; small buffer so the far edge lands just past 1σ, not
exactly on it), rounded to 2 decimals.

**The floor collision, found mid-implementation, not assumed away:**
`_profile_score()`'s recommender-side tempo sigma floor (`max(0.08,
...)`) turned out to bind for **11 of 16 profiles** — their hint-derived
sigma computes below 0.08, so all 11 land on the identical floored value
regardless of how differently wide their own hint bands actually are.
Investigated the floor's own history before proceeding (owner: "revisit
the .08 floor, give me the whole story") — full account:

- Two *different* floors exist: the detector's `_MIN_PROFILE_PRIOR_SIGMA
  = 0.45` (beat_grid.py, protects live ACF search from a profile prior
  dominating real acoustic evidence) and the recommender's `0.08`
  (auto_vj.py, governs how sharply a tempo mismatch counts as scoring
  evidence against a candidate genre). Unifying them was tried (P2-E,
  2026-08-04) and reverted two days later after it silently defanged
  tempo-mismatch evidence — a real live session where the correct
  spectral fingerprint match (`deep_house`, cosine similarity 0.879 vs
  `psytrance`'s 0.776) lost the composite anyway, because at the
  unified 0.45 a 30 BPM miss only cost `tempo_fit` -0.26 raw (~-0.5
  weighted) against a ~12-term composite; reverted to 0.08, the same
  miss costs -2.02 raw (~-4.0 weighted) — enough to matter. Full account
  in the "Recommender Sigma-Floor Revert" section (2026-08-06) above.
- The floor's original design intent, stated explicitly in that same
  revert's own account: a pure safety backstop, deliberately set below
  *every* profile's real authored sigma so it would never actually bind
  — "0.08 is below every profile's value and never actually binds."
  Today's pass is the first time any profile has legitimately wanted a
  sigma tighter than that assumption held.
- Owner's answer to "why 0.08 specifically, not some other small
  number": "it was good enough at the time" — there's no derived-from-
  an-incident origin story for the exact value the way there is for 0.45
  and the revert back to 0.08; only the *direction* (low enough to not
  defang mismatch evidence) is documented.
- **Directionally, lowering the floor further is consistent with, not a
  reversal of, its own stated philosophy** ("recommender's tempo_fit
  term... where sharp discrimination is exactly what's wanted").
- **Owner's read on the one real risk (the `_GAUSSIAN_FIT_X_CLIP=6.0`
  clip capping how negative one mismatched candidate's penalty can go):
  not a concern, and clarifies why.** The clip never touches a *correct*
  candidate's score — a matching genre's diff sits near 0, nowhere near
  the 6σ clip regardless of how tight sigma gets. It only caps how hard
  an already-wrong candidate gets penalized, so it can't discourage or
  slow down genuinely fast, accurate tempo/genre tracking (a track or DJ
  set legitimately moving ambient → house → techno within one song) —
  switching itself is governed by the decider's cooldowns/margins, not
  by this clip. The real, distinct risk (not what the owner was asking
  about, worth keeping separate): ordinary per-tick measurement jitter
  around a *stable, unchanged* true tempo could start reading as
  evidence against the correct genre if sigma gets tight enough — a
  noise-sensitivity question, not a "punishing correct fast detection"
  question. No specific lower-floor number identified as safe yet.

**Decision: floor not changed in this pass.** Set aside for an isolated
A/B test (owner: "there is other pending stuff to test and i want to a/b
that in isolation... we'll hold the commit/push on that iteration until
we make a determination") — a "before" session runs against this
commit's profile values with the floor still at 0.08, then a follow-up
session runs with a candidate lower floor, compared directly. This
commit is the "before" state.

**Verified:** full profile/beat-tracker test suite green after one
expected update — `test_hyphy_disabled_and_tightened_pending_real_
library_material` had a hardcoded `bpm_prior_sigma == 0.15` assertion,
updated to `0.13` (hyphy is hint-derived, not floor-bound, so its value
genuinely changed rather than landing on the floor like most of the
roster). The psytrance/deep_house sigma-floor-revert regression test and
the mu-falls-inside-own-hint-range drift-canary test both still pass
unmodified — psytrance's own sigma moving 0.16→0.08 only sharpens the
same mismatch penalty the original test exercises, doesn't flip its
outcome. `_RECOMMENDER_VERSION` → `1.0.0-rc.11`,
`_VJ_WEIGHTS_DOC_VERSION` → `38`, `auto_vj.py` `__version__` →
`1.0.0-rc.59`.

Also, unrelated to the profile work but landed the same session:
inline comments added at the owner's request — `_V2_PHASE_TOL`'s field
comment ("Jason says do NOT change this, it's super dialed") and both
confidence-blend call sites ("Downbeat regularity confidence idea &
math by Jason").

---

## Live Session Follow-Up: Sample Rate, Cold-Start Priming, ACF Logging, Ambient Misfire (2026-08-14)

Same night, a fresh Spotify-sourced session (`playerctl+webapi`, first
time tested tonight) surfaced a real, cross-verified detector-accuracy
issue: two tracks both settling near 122 BPM while the owner's own
tap-tempo (repeated several times) and Spotify's own displayed BPM both
independently agreed on 112-114. Four follow-up items, each investigated
or shipped this session:

### 1. Sample-rate mismatch — ruled out, but a real latent bug found anyway

Investigated as the leading hypothesis (a fixed-ratio scaling error would
produce exactly this shape of symptom). Ruled out conclusively: the
session log shows exactly one audio device opened for the entire night
(`Built-in Audio Analog Stereo`, 48000 Hz), used identically across
media-01/dj-mixer/Spotify, and more fundamentally, `beat_grid.py`'s BPM
math never touches sample-rate or frame-count math at all — onset
timestamps are wall-clock (`time.monotonic()`) deltas throughout, so a
sample-rate mismatch structurally could not scale reported BPM through
this pipeline even if one existed.

Did find a real, separate, latent bug while checking:
`unicornviz/audio/analyzer.py`'s `_ASSUMED_SAMPLE_RATE = 48000` was a
hardcoded module constant, used directly for the FFT bin→Hz mapping
(spectral centroid, 64-band perceptual bucketing) and the onset/vocal
envelope `dt` terms, never reconciled with `AudioCapture`'s actual
detected device rate — despite `AudioManager.sample_rate`'s own
docstring already stating the contract this violated ("consumers... must
derive Nyquist from this rather than assuming a fixed sample rate").
Moot for tonight's specific incident (the device genuinely was 48000 Hz
all night) but a real, previously-unnoticed landmine for any session on
a 44100 Hz device.

**Fix:** `Analyzer.set_sample_rate(rate)` — updates `self._sample_rate`
(now an instance attribute, `_ASSUMED_SAMPLE_RATE` demoted to
fallback-only default) and recomputes `_bin_hz`; cheap early-return
no-op when the rate hasn't changed. `AudioManager._analysis_worker()`
calls it every frame, right before `Analyzer.process()` — not just once
at startup, so a mid-session device/fallback switch to a differently-
rated device can't leave it silently stale either. Verified: 4 new tests
in `tests/test_analyzer_sample_rate_sync.py` plus the existing
audio/analyzer/capture suites (200+ tests) green.

### 2. Cold-start profile priming — confirmed the owner's read, precisely

Owner's question, verbatim: "do we *have* to prime at start? OH! that
min prior sigma is killing all our new work is what you're saying!?"
Traced `BeatTrackerV3.set_profile()` (the active engine): per the
2026-08-13 rewrite, it's a **complete no-op the instant `self._bpm >
0.0`** — priming only ever happens once, at cold start (track load /
after a silence-reset), never again for the rest of that track. That
one-time call computes `_acf_prior` (`beat_grid.py:2000-2011`) via
`sigma = max(_MIN_PROFILE_PRIOR_SIGMA, profile.bpm_prior_sigma)` — and
`_MIN_PROFILE_PRIOR_SIGMA = 0.45` is larger than *every* profile's
post-sigma-matching-pass value (max is `chillstep`'s `0.30`), so the
floor always wins. **Confirmed: tonight's entire 16-profile sigma-
matching pass has zero effect on the detector's own cold-start prior —
it only ever uses 0.45, exactly as it did before that pass.** That part
was already known/intended (0.45 and the recommender's 0.08 are
deliberately different concerns, per the 2026-08-06 revert). What's new:
because `_acf_prior` is computed once and never recomputed again for the
rest of the track (no matter how many times the recommender's opinion
changes afterward), **whatever profile happened to be active at that one
cold-start moment exerts a fixed, unchanging multiplicative bias
(`score = comb_score * prior`) on every ACF re-estimation cycle for the
track's *entire* remaining duration** — not just the first few seconds.
A wrong or premature genre guess at track load (e.g. defaulting toward
`house`, μ=122, before real evidence accumulates) could plausibly explain
both the slow multi-minute drift observed and why it never fully reached
112-114: the raw comb-filter evidence for the true tempo has to fight a
static 0.45-wide pull toward 122 for the whole song, not just the
opening seconds.

**Not fixed this session** — this is the same code path as two prior
incidents (the 2026-08-12 freeze/hysteresis fix and the 2026-08-13
rewrite that superseded it), high enough stakes to warrant a specific
decision rather than a same-night tweak. Real options on the table,
recorded for whenever this gets picked up: (a) don't prime at cold start
at all, let the ACF search start fully unweighted; (b) keep priming but
let `_acf_prior`'s influence decay back toward uniform over some window
as real evidence accumulates, instead of staying frozen for the whole
track; (c) something else. Flagged in Open Questions below.

### 3. ACF top candidates never logged — now they are

Owner: "why aren't we capturing the acf score arrays in the training
data? let's do that!" `BeatTracker.top_candidates` (prior-free top-3
`(bpm, normalised comb-filter score)` pairs, already computed every ACF
re-estimation cycle purely for `top_cand_fit` scoring) was never exposed
to the decision log or training corpus at all — confirmed by grep, the
only `top_candidates=` logged anywhere was a same-named but *unrelated*
local in the profile-recommendation event (top-3 *genre* candidates by
composite score, not ACF tempo hypotheses — a naming collision, not the
same data).

**Fix:** new `acf_top_candidates` field in `_detector_snapshot()`
(auto_vj.py), compact `'bpm:score,bpm:score,...'` string matching the
existing `top3` formatting convention, empty string for v1
(`BeatGridTracker`, which has no such property). Pure logging addition —
`_DETECTOR_VERSION`/`_VJ_WEIGHTS_DOC_VERSION` not bumped, same exemption
already established for the kr/dbc observability commit. Verified: 2 new
tests in `tests/test_auto_vj_shadow_engine.py`. This directly enables
closing the gap the sample-rate investigation couldn't reach on its
own — the next tempo-ambiguous session can show whether 112 and 122 (or
similar) were both real, competing comb-filter candidates, confirming or
ruling out the tactus-ambiguity hypothesis from real data instead of
inference.

### 4. Ambient winning over an obvious four-on-the-floor track — root cause, with numbers

Owner, live: "right now ambient/chill is winning even tho there is def a
four on the floor regular boom kick @ this 120bpm." Pulled
`term_values_by_candidate` (already logged, per-candidate per-term
breakdown) for every `profile_recommendation` event where `ambient` won
tonight (58 events, spanning 6 tracks) and averaged each term's value for
`ambient` against whichever profile it beat, weighted by
`_DEFAULT_RECO_WEIGHTS` to see each term's actual contribution to the
margin:

| Term | Weight | Ambient − rival (raw) | Weighted contribution |
| --- | --- | --- | --- |
| `centroid_fit` | 0.7 | +1.2022 | **+0.8415** |
| `zcr_fit` | 0.6 | +0.7383 | **+0.4430** |
| `spectral_shape_fit` | 1.2 | +0.1518 | +0.1822 |
| `onset_fit` | 1.0 | +0.0885 | +0.0885 |
| `vocal_hnr_fit` | 0.3 | +0.1900 | +0.0570 |
| `vocal_fmr_fit` | 0.4 | +0.0458 | +0.0183 |
| `top_cand_fit` | 0.4 | +0.0428 | +0.0171 |
| `band_fit` | 1.2 | +0.0035 | +0.0042 |
| `kick_regularity_fit` | 0.7 | −0.2065 | −0.1445 |
| `tempo_fit` | 2.0 | −0.2571 | **−0.5142** |

Net: ambient's average winning margin was ~0.99, and `centroid_fit` alone
supplies +0.84 of it — the dominant driver by a wide margin, `zcr_fit` a
distant second. `tempo_fit` and `kick_regularity_fit` both correctly
favor the rival (as they should for a track with a real regular kick) —
ambient wins *despite* worse tempo and kick-regularity fit, purely on
centroid/ZCR. This is the same bug class as the 2026-08-11 "stuck on
ambient 94% of a session" incident (see "Ambient Bias — Root Cause &
Fix" below): `centroid_fit`'s live linear-FFT measurement and each
profile's `expected_bands`-derived `spectral_centroid_mu` are
structurally different formulas that don't compare like-for-like — a
known, still-open formula-mismatch bug, currently only mitigated by a
weight cut (`centroid_fit` at `0.7`), not fixed. Not touched this
session — recorded as hard evidence for whenever that formula-mismatch
work gets picked up, with a real reproducible case (`ambient` vs.
`house`/`deep_house` on obviously kick-driven material) rather than a
general symptom description.

**Verified:** all four items — sample-rate fix (200+ existing tests +
4 new), ACF logging (2 new tests) — green; the priming investigation and
ambient term table are pure analysis, no code changed, nothing to
regression-test. `unicornviz.__version__` → `1.0.0-beta.91`,
`auto_vj.py` `__version__` → `1.0.0-rc.60`.

---

## Recommender `centroid_fit` Weight Cut + `tech_house` Disabled (2026-08-11)

Follow-up to the `hardgroove` elimination below, same session: reviewing
`tech_house`/`peak_time`/`hard_techno` side by side surfaced that
`tech_house` and `peak_time` sit almost on top of each other on
`bpm_prior_mu` (130.5 vs. 130.0, `tech_house`'s 127–134 band fully inside
`peak_time`'s 126–136), separated mainly by `bpm_prior_sigma` (0.09 tight
vs. 0.24 wide) and a 550 Hz spectral-centroid gap (2900 vs. 2350). That
centroid gap is a weaker discriminator than it looks, because it runs
through `centroid_fit`, which carries a known, still-open formula bug (see
"House-Family Consolidation" below for the original discovery on
2026-08-10): every profile's `spectral_centroid_mu` is derived from
`expected_bands`, a 64-band **log-spaced** perceptual fingerprint (the same
one `audio_spectrum.py` draws and `spectral_shape_fit`'s cosine similarity
correctly compares against), while the live `centroid_fit` measurement
computes spectral centroid from the raw 512-bin **linear** FFT across the
full Nyquist range. The two are structurally different formulas being
compared as if they were the same quantity. A library-agnostic
bandwidth-weighting fix was attempted on 2026-08-10 and rejected — it
overshot `tech_house`'s own real measured average (3520 Hz) by more than
2x (7594 Hz), because `expected_bands` values are relative prominence
ratings, not per-Hz energy density. No clean fix exists without a
representative library to refit `spectral_centroid_mu` against, which is
exactly what's missing for `tech_house` specifically.

**Decision, both owner calls:**

1. `centroid_fit` weight `0.8 → 0.5` (`_DEFAULT_RECO_WEIGHTS` in
   `auto_vj.py`) — no compensating rebalance applied to any other term.
   Unlike `drop_score` in `beat_grid.py`, this composite is not a
   probability distribution that has to sum to 1; it's an arbitrary-scale
   weighted sum of independent Gaussian log-densities (see
   `_GAUSSIAN_FIT_X_CLIP`), so trimming one term's weight doesn't leave a
   gap another term needs to backfill — it just makes an already-flagged-
   unreliable signal count for less. `centroid_fit` is now the weakest
   non-vocal timbre/rhythm fit (below `kick_regularity_fit` at 0.7,
   roughly level with `zcr_fit` at 0.6).
2. `tech_house` disabled (`enabled=False` in `unicornviz/audio/profiles.py`,
   same disable-not-delete pattern as `hyphy` — `get_profile('tech_house')`
   still resolves it directly, `enabled_profiles()` excludes it from the
   recommender's candidate pool) pending a library with enough
   `tech_house`-specific material to recalibrate `spectral_centroid_mu`
   against a real measured average instead of the buggy `expected_bands`-
   derived value. This is a pause, not a removal — `tech_house` is a real,
   validated genre, unlike `hardgroove`; it just currently leans on the
   unreliable centroid axis harder than most profiles to separate itself
   from `peak_time`, and disabling it until that's fixed was judged safer
   than leaving a coin-flip in the roster.

The formula-mismatch bug itself remains open and unresolved by this change
— this is a symptom mitigation (de-weight the unreliable term, pause the
profile that depends on it most), not a fix. A real fix needs either a
reformulated live measurement that matches the log-band `expected_bands`
weighting, or a from-scratch `spectral_centroid_mu` refit against real
per-Hz measured data for every profile — both out of scope for this pass.

`_RECOMMENDER_VERSION` → `1.0.0-rc.7`, `_VJ_WEIGHTS_DOC_VERSION` → `21`.
`docs/audio-profile-reference.md` and
`drop-ins/auto-vj-01/docs/weights-and-thresholds.md` updated in the same
pass (centroid_fit row, tech_house rows across all three profile tables,
changelog entries).

**Verified:** `tests/test_audio_profile_deep_house_and_disable.py` extended
(`test_tech_house_disabled_pending_recalibrated_library_material`, plus
`tech_house` added to the enabled/disabled assertion sets); full relevant
suites green.

### Addendum (same day, later): the formula-mismatch bug itself fixed

Owner: "fix the centroid issue please." The mitigation above (weight cut +
`tech_house` disable) stands, but the actual bug — live centroid measured
via raw linear-FFT bins, `spectral_centroid_mu` derived via log-spaced
`expected_bands` — is now fixed, not just weighted around.

The fix: `unicornviz/audio/analyzer.py` gains a new public constant,
`PERC_BAND_CENTERS_HZ` — the geometric-mean center frequency of each of
the 64 log-spaced perceptual bands (`np.sqrt(edges[:-1] * edges[1:])` over
`np.logspace(log10(30), log10(16000), 65)`), i.e. the exact same
computation `tools/gen_spectral_fingerprints.py`'s `_centers` already
performs — verified byte-identical to that tool's own output
(`tools/spectral_fingerprints_out.py`'s `BAND_CENTERS_HZ` literal) by a
new test. `auto_vj.py`'s `_update_profile_recommendation()` now computes
the live centroid as `dot(PERC_BAND_CENTERS_HZ, audio.bands) /
sum(audio.bands)` — `audio.bands` being the same 64-band, peak-normalized,
relative-magnitude vector `spectral_shape_fit`'s cosine similarity already
compares against `expected_bands` — replacing the old `dot(freqs, fft_arr)
/ sum(fft_arr)` over a raw 512-bin linear-FFT array with a
sample-rate-derived Nyquist axis.

This is a genuine formula-level fix, not an approximation: both sides of
`centroid_fit`'s Gaussian comparison are now computed in the identical
basis by construction, so no `mu` recalibration is needed (it was already
derived via this exact formula on 2026-08-09 — see "`spectral_centroid_mu`
Recalibrated" below). It's a different repair strategy from the rejected
2026-08-10 attempt (bandwidth-weighting `expected_bands` to *approximate*
the old linear-FFT formula's absolute scale, which failed because
`expected_bands` values are relative prominence, not per-Hz density) —
this fix instead changes the *live* formula to match how `mu` was already
being derived, sidestepping the density-assumption problem entirely. Side
effect: also retires the 2026-08-09 `AudioManager.sample_rate`-dependent
Nyquist-axis fix (`beta.81`-era) — no longer applicable once frequency
positions are fixed values independent of capture rate.

**Deliberately not done in this pass, flagged as open questions:**
`centroid_fit`'s weight stays at `0.5` and `tech_house` stays disabled.
De-weighting/disabling were responses to a bug that no longer exists in
that form, but neither decision reverts automatically — raising the
weight back up is a separate philosophy call (the owner's house-family
stance already leans on `bpm_prior_mu` as primary regardless of centroid
reliability), and `tech_house` still has zero validated library examples
of its own even with a trustworthy centroid axis to lean on.

**Corpus provenance gap closed as a direct consequence:** neither the
`profile_recommendation` decision-log `mark()` nor its sequence-corpus
keyframe previously stamped which recommender formula produced a given
row's `mean_centroid` — meaning historical corpus data spanning this fix
would have been silently non-comparable (pre-fix rows on the old linear-
FFT basis, post-fix rows on the new log-band basis) with no way to tell
which is which after the fact. Both call sites now stamp
`recommender_version=_RECOMMENDER_VERSION`, mirroring the
`ANALYSIS_VERSION` discipline CLAUDE.md already requires for dj-mixer-01
track analysis, for the same reason: a stale/ambiguous reference is worse
than no reference.

`_RECOMMENDER_VERSION` → `1.0.0-rc.8`, `_VJ_WEIGHTS_DOC_VERSION` → `22`.

**Verified:** two tests that asserted the old sample-rate-dependent Nyquist
formula (`test_centroid_hz_axis_uses_audio_manager_sample_rate_when_
available`, `test_centroid_hz_axis_falls_back_to_48000_without_audio_
manager`) replaced with tests against the new formula
(`test_centroid_uses_log_band_weighted_mean_matching_fingerprint_
formula`, `test_centroid_no_longer_depends_on_sample_rate_or_audio_
manager`); new `test_perc_band_centers_hz_matches_the_fingerprint_
generator_tool` (byte-identical check against the tool's own output); new
`test_profile_recommendation_mark_stamps_recommender_version`. Full suite
green (1625 passed), `ruff`/`bandit` clean.

### Addendum (next day): reverted — the "fix" exposed a worse bug, confirmed live

**Read this before touching `centroid_fit`'s formula again.**

The log-band `audio.bands` formula above was live for about a day before
a real training session (`assets/training/corpus/sequence-corpus-
20260811T215004Z.jsonl`, a media-player run, 15 real tracks, 7961 rows)
surfaced a severe regression: the recommender picked `ambient`
**6709/7960 rows (84%)**, and the *active* profile ended up on `ambient`
for **7454/7960 rows (94%)** — for a real, varied dance session with
accurate detected BPM ranging `100.9–137.0` the entire time (owner,
watching live: "the recommender is straight up stuck on ambient even w/
the bpm accurate & mood in raver").

**Root cause, confirmed by recomputing centroid directly from the
session's own logged `bands` arrays (not assumed):** the formula fix
above was internally consistent — it made the live measurement match
*how `spectral_centroid_mu` was derived* (both sides now run
`dot(band_centers, vec)/sum(vec)` over a 64 log-band vector). What it
exposed is that **`expected_bands`' magnitude decay across bands doesn't
match real measured audio at all.** Averaged over ~2000 real high-energy
frames (`energy > 1.5`) from this session, actual band magnitude falls
steadily from `~0.65-0.71` at the low end (30-100 Hz) to `~0.05` by
11 kHz — a much steeper bass-dominant rolloff than the hand/LLM-authored
fingerprints assume. Checked directly: this holds equally for quiet
frames (`energy < 0.3`, median centroid `513 Hz`) and loud ones
(`energy > 1.5`, median centroid `529 Hz`) — not a silence-gating
artifact, a genuine property of how this formula reads real audio.

Consequence: live centroid reads `~400-800 Hz` for essentially *all* real
audio measured this way, which sits far below every profile's
`spectral_centroid_mu` (house `2650`, trance `2000`, peak_time `2350`...)
**except** `ambient`'s (`1250`, both the lowest mu among plausible
candidates and the widest sigma, `600`, of the bunch — the most forgiving
combination available). The math on the actual session data:

```text
ambient: z = (580 − 1250) / 600 = −1.12  →  centroid_fit ≈ −0.62
house:   z = (580 − 2650) / 600 = −3.45  →  centroid_fit ≈ −5.95
trance:  z = (580 − 2000) / 400 = −3.55  →  centroid_fit ≈ −6.30
```

Even at the already-reduced `0.5` weight, that's a standing multi-point
advantage for `ambient` over every genre-appropriate candidate, on
essentially every real audio frame — not an occasional miss, a
near-universal bias. This is a worse failure mode than the original
formula-mismatch bug the fix targeted (which was a systematic
*understatement*, not a *directional bias toward one specific profile*).

**Decision: revert the formula, cut the weight further.** `centroid_fit`'s
live measurement is back to the pre-fix linear-FFT formula
(`np.dot(freqs, fft_arr)/sum(fft_arr)`, sample-rate-aware Nyquist axis —
see the field's own code comment in `auto_vj.py` for the restored
history). This is a real rollback to known, previously-stable (if
formula-mismatched in its own documented way) behavior — not a new
design. `centroid_fit` weight cut `0.5 → 0.3` on top of the revert, extra
caution while neither formula's `mu` values are recalibrated against real
measured data. `PERC_BAND_CENTERS_HZ` (`unicornviz/audio/analyzer.py`) is
left in place, unused by the recommender for now — it's still correct
infrastructure (verified byte-identical to the fingerprint tool's own
output) for whenever `spectral_centroid_mu` gets a real recalibration
pass before the log-band formula is retried. `_RECOMMENDER_VERSION` →
`1.0.0-rc.9`, `_VJ_WEIGHTS_DOC_VERSION` → `25`.

**What the actual fix looks like, for whoever picks this back up:**
`spectral_centroid_mu` needs to be recalibrated per profile against real
measured centroid values (using whichever formula is live at the time),
not derived from `expected_bands`' idealized fingerprint shape. This is
exactly the "broader, more representative dataset" this section's
original entry flagged as the blocker for a real fix — the session that
surfaced this incident is one useful data point but explicitly not
sufficient on its own (single library, single session, per the same
overfitting concern raised for `deep_house`/`house` tempo elsewhere in
this document).

**Verified:** `test_centroid_uses_log_band_weighted_mean_matching_
fingerprint_formula` and `test_centroid_no_longer_depends_on_sample_
rate_or_audio_manager` removed (their premise no longer holds);
`test_centroid_hz_axis_uses_audio_manager_sample_rate_when_available` and
`test_centroid_hz_axis_falls_back_to_48000_without_audio_manager`
restored (the pre-fix formula's own tests). `test_perc_band_centers_hz_
matches_the_fingerprint_generator_tool` and `test_profile_recommendation_
mark_stamps_recommender_version` kept — both still valid (the constant
and the version-stamping are independent of which formula is active).
Full suite green, `ruff`/`bandit` clean.

### Addendum (same night): the revert alone wasn't enough — weight raised back to 0.7

Owner, ~20-25 minutes into a fresh session on the reverted formula: "we're
doing better on the recommender action but not sure we're back to as
good as it was when i wanted to lock it down last night." Checked
directly rather than guessing — compared the live post-revert session
against the last known-good overnight session (`favorites/d`, confirmed
via commit timestamps to predate every piece of that day's centroid work
entirely: it ran 2026-08-10 23:11 → 2026-08-11 06:14, the earliest
centroid commit that day landed at 08:05).

`ambient` was no longer dominant — confirmed fixed, one pulled example
showed a genuinely healthy `mean_centroid` (`2199.7 Hz`, nowhere near the
incident's ~400-800 Hz) and a plausible reason for that specific pick
(`zcr_fit` favored `ambient` decisively during a real low-ZCR, `0.036`,
quiet moment). But the composite was measurably *less stable* than the
overnight baseline:

| | `favorites/d` (last known-good) | live, post-revert |
| --- | --- | --- |
| `mismatch_pct` (recommended ≠ active) | `11.5%` | `39.8%` |
| switch rate | ~`0.16`/min | ~`0.5`/min |

Best explanation: `centroid_fit`'s weight had drifted to `0.3` (the
cumulative effect of two cuts that night — `0.8→0.5` that morning,
`0.5→0.3` alongside the revert), down from `0.8` during the overnight
baseline. Centroid was a real, moderately-weighted timbre discriminator
at `0.8`; at `0.3` it's nearly inert, leaving `zcr_fit`/`onset_fit`
proportionally more sway over close calls, which reads as noisier
switching. Caveat on the comparison itself: small sample (8 tracks, ~20
minutes, session still running when checked) and a different playlist
than the overnight baseline (that one leaned house-heavy; this one
peak_time/hard_techno/hardstyle), so not perfectly apples-to-apples —
flagged, not treated as final.

**Decision:** `centroid_fit` weight `0.3 → 0.7` — a deliberate middle
value, not a full return to `0.8`, while the owner runs a longer
(multi-hour) validation session on the reverted formula. Restoring
functional weight to a term whose *own* live-formula-vs-`mu` mismatch is
still open and unresolved (same caveat as ever, see above) is worth
being explicit about: this raises how much a known-imperfect signal
influences picks again, in exchange for the composite's overall
stability. `_RECOMMENDER_VERSION` → `1.0.0-rc.10`,
`_VJ_WEIGHTS_DOC_VERSION` → `26`.

---

## `hardgroove` Eliminated Entirely (2026-08-11)

Owner: "who tf ever says 'ya man, i listen too hardgroove all the time'."
Same shape of problem as `hyphy` (see below) but decided outright rather
than paused, since there's no plan to bring in validated hardgroove
material the way there is for trap/hyphy.

Investigated first, not just removed on the joke alone: `hardgroove`
(132-140 BPM, mu=136) overlapped `tech_house` (127-134) and `peak_time`
(126-136) on BPM simultaneously, sat within 50-150 Hz of `peak_time`
(2350) and `hard_techno` (2450) on spectral centroid (mu=2500, both
within a 250-400 Hz sigma), and its onset-density mu (3.2) was
numerically **identical** to `peak_time`'s. No axis where it was clearly
the best fit over its neighbors. Real usage across the three most recent
sessions checked (favorites/b, c, d — ~89,000 rows): zero tracks tagged
"hardgroove" or any variant, while the recommender still picked it
147/94/214 times respectively (always < 1.3% of rows) — every pick
unverifiable by construction, same as `hyphy`'s finding.

Eliminated entirely (not disabled — no dict entry survives), same pattern
as `uk_garage`/`breaks`/`generic`. `_RECOMMENDER_VERSION` →
`1.0.0-rc.6`, `_VJ_WEIGHTS_DOC_VERSION` → `20`. Live profile count: 16
(was 20 before this week's consolidation passes: `uk_garage`, `breaks`,
`generic`, `hardgroove` all eliminated; `hyphy` disabled, not eliminated,
pending real trap/hyphy library material).

`docs/audio-profile-reference.md` fully regenerated from live
`unicornviz/audio/profiles.py` values in the same pass — it had drifted
significantly stale (still describing the pre-house-family-consolidation
BPM bands, and incorrectly claiming `bpm_hint` hard-caps the ACF search
range, a claim the 2026-08-04 hard-clamp-removal fix invalidated but the
doc was never updated to reflect).

**Not fixed this pass, flagged for later:**
`drop-ins/auto-vj-01/AUDIO_PROFILE_CHEAT_SHEET.md` is far more stale than
this doc was — it still lists `breaks`/`uk_garage`/`generic`/`hardgroove`
as live picks, and also references profiles (`pop`, `rock`,
`metal_extreme`, `classical`) that do not exist anywhere in the current
`PROFILES` dict at all. This needs a comprehensive rewrite, not a spot
fix, and was out of scope for this pass -- flagged rather than silently
left for the next owner to trip over.

**Verified:** full main-repo suite green (1622 passed), `ruff` clean. New
test: `test_generic_uk_garage_breaks_hardgroove_eliminated_entirely`
(renamed from the `uk_garage`/`breaks`/`generic`-only version).

---

## Drop Score Bass-Gated Reweight (2026-08-10)

Triggered by an owner observation while watching a live session: `drop_score`
read `0.54` during a breakdown that was just piano chords and vocals — zero
drums, zero bass. That number is high enough to matter: for raver (the
largest mood-profile share of most sessions) the *main* `drop_energy_
threshold` was `0.46` at the time, meaning 0.54 could have fired a real drop
directly, not just via the timeout safety valve. Investigated, discussed,
and fixed as one coordinated change across the detector's `drop_score`
formula and every mood profile's drop/climax decision ladder, rather than
patching either in isolation — see the false-threshold-inversion problem
below for why patching just one would have made things worse, not better.

**Root cause.** `drop_score` (`BeatTracker.update()`, inherited unmodified
by `BeatTrackerV3`) was a 5-term composite: `energy_norm*0.15 +
slope_norm*0.35 + band_blend*0.15 + flux_norm*0.10 + bass_flux_norm*0.25`.
Only `band_blend` and `bass_flux_norm` require any bass presence at all
(combined weight `0.40`, a minority); the other three
(`energy_norm`/`slope_norm`/`flux_norm`) are genre-agnostic loudness/
transient signals — a swelling piano-and-vocal passage satisfies all three
just fine on its own, chord attacks and vocal dynamics are real events on
`flux_norm`'s mid+treble axis. `slope_norm` (rate of energy increase) was
the single largest term and needed no bass whatsoever to reach a high
value.

**Fix, agreed after a back-and-forth on the exact numbers (owner's final
proposal):** `energy_norm*0.15 + slope_norm*0.15 + band_blend*0.30 +
flux_norm*0.05 + bass_flux_norm*0.35`. Combined bass-aware weight rises
`0.40 -> 0.65`, a genuine majority for the first time. Consequence, checked
directly: the maximum possible `drop_score` with zero bass content is now
`energy_norm(1.0)*0.15 + slope_norm(1.0)*0.15 + flux_norm(1.0)*0.05 =
0.35` — below every rebooted mood-profile floor (lowest is raver's `0.60`,
see below), so a rhythm-free moment can no longer fire a drop via any
path, by construction rather than a conditional gate. Verified with a
synthetic-tracker regression test that warms up a real bass baseline (so
the per-band adaptive normalizer has something to actually drop *from* —
a cold-start zero-bass tracker reads its own permanent silence as neutral,
not conspicuously absent) then cuts to zero-bass, loud, transient-heavy
mid/treble content: `drop_score` settles at `~0.30`, comfortably under
every floor. `_DETECTOR_VERSION` -> `1.0.0-rc.4`. Only `BeatTracker`/v2's
formula changed; `BeatGridTracker`/v1 uses a structurally different
3-term formula (no `bass_flux_norm`/`flux_norm` at all) and was
untouched — the owner separately flagged v1 vs. v3 behavioral differences
as worth a proper A/B test, deferred to its own investigation.

**The threshold-inversion problem, and why the whole ladder moved
together.** Each mood profile (`chill`/`normie`/`raver`) explicitly
overrides five `drop_score` gates, not just the one initially in
discussion: `drop_timeout_score_floor < drop_energy_threshold <
climax_entry_score < climax_early_override_score < drop_fastlane_score`.
The owner proposed new floor values directly (`0.70`/`0.65`/`0.60`) — but
the *shipped* main thresholds at the time were `0.55`/`0.54`/`0.46`,
calibrated for the old formula's easier-to-satisfy scoring. Setting only
the floor to the new values would have put it *above* the main threshold
for all three profiles — inverting the ladder's whole purpose (a timeout
floor is supposed to be a relaxed bar below the real threshold, a
"give up waiting, take what we can get" safety valve; a floor above
threshold makes the safety valve stricter than the thing it's a fallback
for). This exact inversion had already happened once before and been
fixed — see the `2026-06-20` comments in `auto_vj.py`'s `chill`/`raver`
profile blocks ("floor was 0.56/0.52, above drop_energy_threshold... timeout
rescue should not require more score than a regular drop") — so it was
caught before landing this time, not after.

Resolved as a single reboot of the whole five-value ladder per profile,
preserving strict ordering and each rung's relative position across
profiles (chill strictest throughout, raver most permissive throughout,
same shape as before):

| Profile | Floor | Threshold | Climax entry | Climax early | Fastlane |
| --- | --- | --- | --- | --- | --- |
| `chill` | 0.50 → **0.70** | 0.55 → **0.77** | 0.64 → **0.83** | 0.72 → **0.89** | 0.78 → **0.95** |
| `normie` | 0.48 → **0.65** | 0.54 → **0.73** | 0.60 → **0.79** | 0.66 → **0.85** | 0.72 → **0.91** |
| `raver` | 0.40 → **0.60** | 0.46 → **0.69** | 0.56 → **0.75** | 0.62 → **0.81** | 0.68 → **0.87** |

Owner set the three floor values directly; thresholds were counter-
proposed to sit just below them at a ratio matching the old floor/threshold
relationship (owner: "i'm down with my floors and your thresholds!");
climax-entry/climax-early/fastlane were then rescaled by the agent to
preserve strict ordering with consistent ~`0.06` gaps above threshold,
since leaving them at their old absolute values would have reproduced the
identical inversion bug one rung higher (fastlane ending up below the new
threshold for normie/raver). `drop_confirm_score` needed no change — it's
never profile-overridden, always deriving as `drop_energy_threshold *
0.90`, so it moved automatically. `_DIRECTOR_VERSION` -> `1.0.0-rc.3`.
This whole ladder was undocumented in `weights-and-thresholds.md` before
this pass despite existing since the mood-profile system shipped — added
as a new table, a real gap this doc's own "keep it up to date" mandate
exists to prevent, not one specific to today's change.

**`onset_fit` recommender weight: `0.7` -> `1.0`.** LLM tuning
recommendation from the `favorites/b` session ("onset events strongly
correlate with genre transitions"), owner-reviewed and agreed. Onset
density (onset events/sec) is a real, measurable acoustic property that
cleanly separates e.g. tech house's dense hi-hat pattern from deep
house's sparser one, without `centroid_fit`'s known formula-mismatch
caveat (see "House-Family Consolidation" below). Flipped two existing
regression tests that had specific numeric inputs calibrated against the
old weight (`test_recommender_prefers_deep_house_over_psytrance_at_120_
bpm`'s `onset_count`, `_make_trust_test_stub`'s `onset_count` — the
latter's own literal-mu-average intent was already slightly wrong before
today, since `onset_count` isn't `onset_density` itself but accumulates
across the fixture's 6 samples over the fit's rolling window; the old
`onset_fit` weight (0.7) was too small to expose that pre-existing
mismatch, 1.0 was not). Both re-tuned empirically to restore their
original intent (tempo_fit dominance; a small non-trivial margin) under
the new weight, documented inline with the specific numbers. `_RECOMMENDER_
VERSION` -> `1.0.0-rc.5`.

**`hyphy` tightened and disabled.** Same session's real data: the
recommender picked `hyphy` for real hip-hop tracks (987x) that should
land on `rap_rnb` — the alias map already routes "Hip-Hop"/"hip hop" to
`rap_rnb` correctly, so this was a live-scoring problem, not a genre-tag
mapping one. Owner: "there is no hyphy in the library afiak. yet" — a
different kind of signal than a tag-vs-recommender disagreement (which the
owner has separately asked to defer to the recommender's judgment on, see
below): zero known validated hyphy/trap examples means every hyphy pick in
that data was very likely a false positive by construction, not a
judgment call to trust either way. `bpm_prior_sigma` 0.20 -> 0.15 and
`spectral_centroid_sigma` 600 Hz (wide tier) -> 400 Hz (medium, the
dataclass default) — not closing a BPM overlap gap (100-118 was already
adjacent to, not overlapping, `house`'s 118-126 and `rap_rnb`'s 70-100),
but sharpening discrimination within the band; the wide centroid tier was
never re-justified for hyphy the way it was for house's genuinely diverse
library content, so defaulting to medium removes it as a low-resistance
catch-all on that axis. `enabled=False` (still directly resolvable via
`get_profile('hyphy')`; `enabled_profiles()` excludes it), same disable-
not-delete pattern used for `electronic`/`generic` before `generic`'s
later full elimination. Owner: "we will be keeping the hyphy/trap genre in
the long term.. and they should remain a single named pair 'hyphy/trap'"
— a pause pending real library material, not a removal.

**Standing policy, noted the same session (not itself a code change):**
owner has decided to trust the recommender's judgment over the library's
own genre tags for now ("i think it should be pretty dialed in") and
plans to edit the library's tags to better match the system's expectations
instead of only tuning the system to match the tags — the inverse of this
whole investigation's working assumption up to this point. Any future
suggestion to modify recommender weights/profile values must flag this
policy and be carefully considered before acting on a tag-vs-recommender
confusion count alone. Saved as agent memory
(`feedback_trust_recommender_over_library_tags.md`); does not apply to
detector/director changes with their own independent evidence base (like
this entry's `drop_score` fix), which came from a direct listening
observation, not a tag-confusion count.

**Verified:** full main-repo suite green (1619 passed), `ruff`/`bandit`
clean on every touched file (two pre-existing, unrelated findings
confirmed outside the diff ranges via `git diff --unified=0`). New tests:
`test_drop_score_bass_gated_reweight_caps_a_bass_free_breakdown`
(`test_beat_tracker_v2.py`), `test_hyphy_disabled_and_tightened_pending_
real_library_material` (`test_audio_profile_deep_house_and_disable.py`);
two existing tests recalibrated for the `onset_fit` bump (see above), one
(`test_default_enabled_true_for_profiles_that_dont_set_it`) updated to
replace an already-stale `'generic'` reference (eliminated entirely in an
earlier pass, so no longer meaningful there) with `'hyphy'`.

**Not done this pass, explicitly deferred:** `_V2_COHERENCE_WINDOW`
(`32 -> 40`, an LLM tuning suggestion tied to phase-lock confidence
smoothing, not tempo-value accuracy despite being pitched that way) --
agent's assessment was skeptical of the causal link claimed; owner agreed
to hold and is considering a proper v1-vs-v3 (or v2-vs-v3) A/B test given
"I see problems," which would be a more direct way to investigate engine-
level behavioral differences than tweaking one detector constant on a
plausible-sounding but unverified LLM rationale.

### Addendum (same day): LLM tuning prompt fixed at the source

The `_V2_COHERENCE_WINDOW` miscategorization above wasn't just a one-off
bad call — training-kit-01's LLM tuning prompt had no mechanism to stop it
from happening again on a future session. Fixed there directly (training-
kit-01 0.15.4): the prompt now explicitly sorts every detector constant
into one of three categories — tempo VALUE search/accuracy
(`_MIN_PROFILE_PRIOR_SIGMA`, `_V2_PRIOR_SIGMA`, `_V2_RAW_DOMINANCE_RATIO`,
`_V2_DENSITY_FAST_RATIO`, `_V2_DENSITY_SCORE_RATIO`,
`_V2_HARMONIC_CONF_TOL`), lock STATE gating (`_BPM_LOCK_CONFIDENCE`,
`_BPM_LOCK_RELEASE_CONFIDENCE`), or phase-lock CONFIDENCE smoothing
(`_V2_PHASE_TOL`, `_V2_COHERENCE_WINDOW`) — and requires every
`detector_recommendations` rationale to name the exact payload field it
read, which must belong to the same category as the constant being
recommended. A rationale citing a tempo-value metric (`bpm_delta_median`,
`external_agreement`) to justify a confidence-smoothing constant change
(or vice versa) is now explicitly called out as invalid in the prompt
itself, regardless of how plausible it reads. New regression test:
`test_build_combined_prompt_separates_confidence_smoothing_from_tempo_
accuracy`.

Owner, on the underlying detector confidence signals this surfaced while
discussing the fix (2026-08-10): trusts the project's own BPM detector
over both Essentia comparison and LLM tempo-plausibility commentary ("i
trust our bpm detector over essentia AND over the llm, it's pretty damn
solid") — saved as agent memory
(`feedback_trust_bpm_detector_over_essentia_and_llm.md`), same standing-
caution pattern as the recommender-vs-library-tags note above.

### Addendum (same day): coherence-window experiments implemented, one reverted mid-flight

The confidence-signal questions raised above (`_V2_PHASE_TOL` width, the
`0.4/0.6` confidence blend, a possible v3 bass-hit-on-grid term) were
discussed further the same day and turned into two live experiments —
"let's get some [onset-jitter] data!" — plus one piece of new corpus
capture, rather than staying tabled:

**`_V2_PHASE_TOL`: `0.18` → `0.12`, by way of a rejected `0.08`.** First
tried `0.08` (owner: "set it to +/- 8"), matching the "is ±18% way too
wide" suspicion with an aggressive, data-generating cut. Verified directly
before committing — a mathematically perfect, zero-jitter synthetic click
track (not real audio, an idealized best case) never registered a single
phase hit in 120+ simulated seconds; `phase_confidence` stayed at exactly
`0.0` the whole time, capping overall confidence at `0.4` regardless of
how long it ran. Root cause: the phase oscillator advances at the
tracker's own *estimated* BPM (e.g. `122.4` for a true `120`), not the
true tempo, so there's always some small residual mismatch — under the
old `0.18` tolerance that residual was forgivable; at `0.08` it was
apparently enough on its own to keep phase permanently out of tolerance,
independent of any real off-grid content. This was caught and reported
*before* committing to an overnight run on it — flagged as a real risk of
burning a whole night's data collection on a config that breaks lock
convergence rather than just filtering swing/human timing as intended.
Owner chose to back off; `0.12` verified convergent by the same method
(reaches full confidence reliably), though noticeably slower than `0.18`
did — ~120s to fully stabilize in one tested scenario (124 BPM) versus
the old ~65s baseline. Two regression tests whose settle windows were
empirically timed against the old baseline needed their duration extended
to `130s` accordingly (`test_locked_bpm_does_not_drift_toward_mismatched_
profile`, `test_v2_drifts_toward_new_profile_but_v3_does_not`); a new
`test_phase_tol_012_converges_reliably_where_008_did_not` guards against a
future edit silently re-tightening past the point where this breaks.

**`_V2_COHERENCE_WINDOW`: `32` → `35`.** The LLM's own `32 → 40`
suggestion was already rejected above as reasoning about the wrong axis —
this is the owner trying a partial move toward that number anyway, as its
own independent experiment ("kinda split the difference"), not an
endorsement of the LLM's stated rationale.

**New corpus capture, so the `0.4/0.6` blend itself can eventually be
judged:** `BeatTracker.acf_confidence`/`phase_confidence` — previously
private-only, the combined `confidence` was the only thing ever exposed —
are now public properties, reaching every corpus row via
`_detector_snapshot()`. The blend ratio itself is deliberately *not*
touched this pass ("let's do that [rebalance] and make sure we're getting
the training data we can later judge by for further tweaking after we
first settle issues from point 1" — owner), sequenced behind having real
`_V2_PHASE_TOL=0.12` session data to look at first.

**What to watch in the upcoming overnight session, per the owner's own
question:** the HUD BPM confidence reading (`BPM: xxx (0.xx)`, the
blended value), lock churn (gained/lost counts in the scorecard), and
profile-switch frequency — `detector_trust` scales the score margin
required to confirm a switch, so a noisier/lower confidence signal should
show up as more conservative, less frequent switches, not just a raw
confidence-number change.

`_DETECTOR_VERSION` → `1.0.0-rc.5`, `_VJ_WEIGHTS_DOC_VERSION` → `18`.
Full write-up: `docs/planning/auto-vj-coherence-window-plan-2026-08-10.md`.

**Separately, same conversation — a concern about the drop/climax ladder
reboot above, not yet acted on:** owner observed "drop guy not doing so
well" after the bass-gated reweight + ladder reboot shipped, and reads it
as likely the *thresholds* needing help rather than the reweight itself
("i think that was the right direction that might need tweaking but
thresholds maybe could use some help"). Explicitly deferred — "we'll deal
with it tomorrow, i'll run an overnighter" — pending real data from the
same overnight session this coherence-window experiment is riding along
in. A `+4%` blanket raise across the whole ladder was requested and then
retracted mid-turn ("ignore my request to raise the thresholds.. let's
wait for more data") before any change was made.

**Verified:** full main-repo suite green (1621 passed), `ruff` clean on
every touched file.

### Addendum (same night, before the overnight run): two more calls

- **`_V2_PHASE_TOL`: `0.12` → `0.14`.** Owner: "sounds pretty tight against
  your test," referring to the ~120s convergence time measured for `0.12`.
  Still well below the original `0.18`, with more convergence headroom
  than `0.12` had.
- **ACF/phase confidence blend: `0.4/0.6` → `0.5/0.5`.** An explicit owner
  call for tonight's session specifically ("do set acf & phase confidence
  equal for tonight"), not a resolution of the "is phase over-weighted"
  question raised earlier — that's still deferred pending real
  `acf_confidence`/`phase_confidence` corpus data (now captured
  separately, per the addendum above).

One test (`test_is_downbeat_fires_exactly_once_per_four_beats`) needed
relaxing from an exact `beat_count == downbeat_count * 4` check to
`beat_count // 4 == downbeat_count` — a fixed 30s wall-clock test cutoff
stops 0-3 beats into a partial bar as often as not, and which remainder it
lands on is sensitive to exactly this kind of convergence-timing tuning;
not a real downbeat-detection bug, just a test that had been getting
lucky.

`_DETECTOR_VERSION` → `1.0.0-rc.6`, `_VJ_WEIGHTS_DOC_VERSION` → `19`. Also
caught and fixed in the same pass: the prior `_V2_PHASE_TOL=0.12`/
`_V2_COHERENCE_WINDOW=35` commit (auto-vj-01 `1.0.0-rc.37`) had shipped
without its own README changelog entry — added retroactively alongside
this one's `1.0.0-rc.38`.

**Verified:** full main-repo suite green (1621 passed), `ruff` clean.

### Addendum (2026-08-11): `dconf_pending` added, and a correction

Checking the overnight session's real data the next day surfaced a
finding that briefly looked like the drop/climax ladder was badly
miscalibrated: `drop_score` at `drop_fire` events (412 of them) averaged
`0.679`, with 266/412 (65%) reading *below* their own mood profile's main
threshold. Root cause traced to `_fire_drop()`: drops wait for the next
downbeat after being scheduled (`_schedule_drop()` →
`schedule_for_next_downbeat(self._fire_drop)`), and `drop_score` — a
volatile, fast-reacting signal especially after the bass-gated reweight —
can decay substantially in that window. The corpus captures `drop_score`
*at fire time* (post-decay), not the value that actually satisfied the
gate at *schedule time*.

**Correction, made before this was reported as a real problem:** the
corpus already had `score_pending` (the actual gating value) — an
earlier pass at this analysis missed checking for it. Re-run against
`score_pending` instead: mean `0.728`, only 2/412 below their profile's
threshold. The ladder is working as designed; zero `drop_cancelled`
events in the same session's decision log independently confirms the
re-validation gate never once rejected a scheduled drop. The apparent
"65% below threshold" was an artifact of comparing the wrong (decayed)
value, not a real calibration problem.

What *was* a real, if smaller, gap: `dconf_pending` (the downbeat-
confidence half of the same re-validation gate,
`self._drop_pending_dconf`) was tracked internally and already reached
the decision log's `drop_cancelled` mark, but never the training corpus's
`drop_fire` keyframe. Added alongside the already-present `score_pending`
so a future session can verify both halves of the gate from corpus data
alone. `auto-vj-01` → `1.0.0-rc.39`. New test:
`test_fire_drop_corpus_keyframe_includes_pending_score_and_dconf`.

Separately, the same overnight-data review found `confidence` sat at
exactly `0.90` for 99.5% of the session's heartbeat rows — not because
the ACF/phase machinery converged well (`phase_confidence` averaged only
`0.347`, genuinely weak), but because `mixer_bpm` was fresh on literally
every row, continuously re-priming the tracker's confidence to its
`_primed_confidence` floor (`0.9`, refreshed roughly every 8s by the
recommender's own eval cycle against a 10s hold). Whenever dj-mixer-01 is
the audio source with a live BPM hint, the whole night's `_V2_PHASE_TOL`/
confidence-blend tuning is largely invisible in the `confidence` value
actually used for lock gating and the HUD — it would only show up on
Spotify/media-player sessions, or when the mixer's hint goes stale. Not
acted on this pass; noted for whoever next interprets a mixer-sourced
session's confidence numbers.

**Verified:** full main-repo suite green (1622 passed), `ruff` clean.

### Addendum (2026-08-11): `energy_norm` / `band_blend` swap, and the elimination question

Follow-up owner observation, live: a real drop's `drop_score` was found
decaying purely from the passage of time under a synthetic constant-input
test (bass=1.0, mid=0.3, treble=0.2, unchanging, after a quiet 5s warmup):
`drop_score` fell from ~0.712 (t=0.05s) to a stable ~0.540 (t=7s+), a ~24%
relative drop, with `bass_flux_fast` staying rock-steady at exactly 0.300
throughout -- isolating the entire decay to `band_blend`. Root cause:
`band_blend`'s inputs (`bass_n`/`mid_n`/`treble_n`) are running z-scores
(`unicornviz/audio/analyzer.py`'s per-band adaptive normalizer) -- the
baseline "catches up" to sustained loud bass within ~5-7s, redefining it as
statistically normal and fading `band_blend` toward neutral (~0.5) even
though the true level never changed. A real, unchanging drop was being
scored *less* drop-like the longer it held.

**Simulated three fix directions against two real sessions**
(`favorites/e`: fresh, unmasked media-player session, 97 real `drop_fire`
events; `library/b`: 484 events) before touching code, replaying
`band_blend`/`energy_norm`/`slope_norm` directly from each corpus row's own
logged `bass_n`/`mid_n`/`treble_n`/`energy`/`energy_slope` (formula-
independent fields) and `flux_norm`/`bass_flux_norm` via their EMA update
rule row-by-row from logged raw `bass_flux`/`spectral_flux`:

1. **Naive swap** (`energy_norm 0.15→0.30`, `band_blend 0.30→0.15`, others
   unchanged): real drops clear the raver/normie score floors measurably
   more often (`library/b`: `380→437` of `484` at the `0.60` floor,
   `294→314` at `0.65`) -- reproduced on both sessions. Known cost: a small
   regression on a rare bass-free-loud-breakdown proxy (`band_blend<0.15`
   and `energy_norm>0.5`, `11/72198` rows in `library/b` -- zero such rows
   existed at all in the fresh `favorites/e` session) -- mean score
   `0.567→0.634`, `0/11→2/11` newly clearing the `0.70` floor.
2. **Gated swap** (same weights, but `energy_norm` scaled by
   `0.5 + 0.5*max(band_blend, bass_flux_norm)` before weighting, so pure
   loudness with zero bass evidence caps at half credit): didn't help in
   practice. `bass_flux_fast`'s slow-release EMA (0.85 retain) keeps
   `bass_flux_norm` elevated for seconds after an isolated kick, so
   `max()` almost never actually reads "no bass," even in a genuinely
   sustained bass-free stretch -- the gate was defeated by the same kind
   of lag it was meant to guard against.
3. **Strict gate** (`energy_norm` scaled by `0.3 + 0.7*band_blend` alone,
   no `bass_flux_norm`): fixed the false positive cleanly (`1/11` clearing
   `0.60`, down from naive swap's `5/11`) but overcorrected into a real
   regression on genuine drops (`293/484` clearing `0.60` on `library/b`,
   *below* the un-swapped baseline's `380/484`) -- because gating directly
   on `band_blend` re-imports its own decay problem through the gate.

**Decision: ship the naive swap** (`energy_norm 0.30` / `band_blend 0.15`,
`bass_flux_norm 0.35`/`slope_norm 0.15`/`flux_norm 0.05` unchanged) --
owner call, accepting the small known false-positive cost as the better
trade given neither gated variant improved on it without a worse
regression elsewhere. `_DETECTOR_VERSION` → `1.0.0-rc.7`,
`_VJ_WEIGHTS_DOC_VERSION` → `23`. The bass-gated invariant from the
2026-08-10 reweight (a bass-free moment can't clear any mood profile's
floor) still holds under the new weights, with a smaller margin: max
`drop_score` with zero bass content is now `energy_norm(1.0)*0.30 +
slope_norm(1.0)*0.15 + flux_norm(1.0)*0.05 = 0.50`, still below every
floor (raver's `0.60` is the lowest), down from the prior formula's
`0.35`.

**Open, not decided this pass:** the owner's read on this data is that
`band_blend` itself may be worth eliminating outright rather than further
reweighting around its decay -- and if so, what (if anything) should take
over its "is there bass" role, since `bass_flux_norm` alone is a
*transient* detector (attack-only) with no sustained-level signal, exactly
the gap `band_blend` was originally covering. Flagged for the next round,
not resolved here.

**Verified:** `test_drop_score_bass_gated_reweight_caps_a_bass_free_
breakdown` re-run against the new weights (still passes with real margin:
the scenario now reads ~0.32, not just barely under the 0.50 assertion);
full suite green (1638 passed), `ruff`/`bandit` clean.

### Addendum (same night): confidence blend `0.5/0.5` → `0.7/0.3` — the "is phase over-weighted" question, finally answered

Real data, not another owner-call-for-tonight this time: pulled
`acf_confidence`/`phase_confidence` from a live session (`sequence-
corpus-20260811T234716Z.jsonl`), restricted to stable-BPM stretches
(BPM unchanged over the last 20 rows — 69% of the session) as a proxy
for "genuinely locked, not drifting":

```text
STABLE-bpm subset (n=4895):
  acf_confidence:   median 0.40   p90 1.00   max 1.00
  phase_confidence: median 0.29   p90 0.37   max 0.60
```

`phase_confidence` structurally caps around `0.3-0.4` *even during
stable, locked stretches* — it essentially never approaches `1.0`
regardless of how correct the tempo is. `acf_confidence` reaches `1.0`
regularly on the same stretches. So the question this document has
carried open since the coherence-window work above ("is phase over-
weighted?") has an answer: yes, but not because the *ratio* was wrong —
because `phase_confidence`'s own formula (a flat hit-rate over every
onset landing within `_V2_PHASE_TOL` of the beat) can't distinguish "the
lock is bad" from "this hi-hat pattern was never going to land on the
downbeat." Real music generates plenty of legitimately off-beat onsets
even when perfectly locked; the metric counts every one of them against
confidence regardless of whether it should.

**Decision: `0.5/0.5` → `0.7/0.3` ACF/phase, explicitly temporary.** Real
fix, agreed but not built this pass: weight phase coherence by onset
strength/band (kick/bass-region onsets should count toward the hit-rate;
hi-hat/fill onsets shouldn't count against it) rather than treating
every onset as equally meaningful evidence — planned for the next
session. This ratio bump is a stopgap standing in for that, on the same
axis the coherence-window work already established
(`acf_confidence`/`phase_confidence` now public, reaching every corpus
row) — it's just now backed by real stable-lock data instead of a
same-night owner call.

**Explicit process note, on the owner's own record:** this is a
deliberate, acknowledged exception to the standing flag-and-confirm
policy for detector changes (`feedback_trust_bpm_detector_over_essentia_
and_llm` and its sibling memory) — "i'm violating my own policy but it's
due to consensus and this is just a temp fix while we work on phase
confidence." Not a precedent for skipping that discipline going forward;
recorded here specifically so it doesn't read as a silent departure from
it later. `_DETECTOR_VERSION` → `1.0.0-rc.9`, `_VJ_WEIGHTS_DOC_VERSION`
→ `27`.

**Verified:** full suite green, `ruff`/`bandit` clean — no test asserted
the specific `0.5/0.5` ratio (the perfect-click-track convergence test
reaches `~1.0` on both terms regardless of blend weight, so it's
insensitive to this change by construction).

---

## Mixer Track Meta Reaches the Training Corpus (2026-08-10)

Owner question that started this: "are we capturing all the incoming mixer
track meta into our training logs, like song sectionality, etc?" The answer
was no on two fronts. dj-mixer-01 computes a rich per-track analysis
(sections/song-structure, musical key, cue/loop points, stems -- see
`track_store.py`), but only a thin slice ever crosses the drop-in boundary:
the *currently playing* section (plus its immediate successor) via
`vj_api.publish_section()`/`get_section()`, and BPM via
`publish_bpm()`/`get_bpm()`. Musical key had no crossing mechanism at all.
And of what *did* cross, the section hint was consumed only by
`_phrase_bias()` for live decisions (see the phrase-structure plan,
2026-08-05/06) and never written to any training-corpus row -- so there was
no way to later ask "did the director's actions actually line up with the
track's real structure?"

**Musical key: exposed via the existing now-playing channel, not a new
hint-bus type.** `dj_mixer_controller.now_playing_snapshot()` already
carries `genre` (an ID3 tag, Tier 2 of the recommender-accuracy-tracking
plan) through to `_build_live_training_row()` via
`vj_api.active_now_playing()`. `key` (Camelot code, e.g. "8A", from
`track_store.key_for_path()` -- the same store `_publish_section()` already
reads) rides the same channel via a new `_current_track_key()` mirroring
`_current_track_genre()`'s cache-by-path pattern. No new `vj_api` surface
needed -- genre and key are both "the analyzer's opinion about the loaded
file," a natural fit for a channel that already exists, not a case for the
`publish_bpm`/`publish_section` pattern (those are live, per-tick values;
key is a per-track constant, same as genre).

**Camelot decode uses wheel position, not chromatic pitch class, for the
cyclical encoding.** The corpus row schema (`key`/`scale`/`key_index`/
`key_sin`/`key_cos`/`is_minor`/`key_strength`) predates this work -- it was
designed for Spotify's Audio Features key/mode/key_confidence shape, dead
since that endpoint's Nov 2024 deprecation (see the "Spotify's Get Audio
Features..." comment already in `_build_live_training_row`). Repurposing it
for Camelot: `key_index`/`key_sin`/`key_cos` encode the Camelot wheel's own
1-12 position (zero-based), not chromatic semitone distance -- adjacent
Camelot numbers are the wheel's own definition of harmonic compatibility,
so this is the more musically meaningful cyclical encoding for any future
harmonic-mixing-aware use of the corpus. `key_strength` stays 0.0
(unmeasured, not "confident zero") -- `key_detect.py` computes a detection
confidence but the track store never persists it, only the Camelot code
itself (confirmed by reading `track_store.py`; a real gap, not something
this pass fixes).

**`mixer_bpm`: the raw hint, distinct from the locally-tracked result.**
`self._grid.bpm` (the corpus's `bpm` field) may already reflect
`prime_tempo()` having adopted an external hint (see the BPM Detector Audit
entry below) -- once that happens the primed and un-primed values are
indistinguishable in the row. New `_get_mixer_bpm()` (mirrors
`_get_section_hint()`'s defensive-wrapper pattern) captures
`vj_api.get_bpm(exclude='auto_vj')` fresh into every row as `mixer_bpm`, so
a corpus consumer can compare detector output against ground truth
directly instead of only ever seeing the post-prime result.

**Section hint fields land on every corpus row, prefixed `section_*`.**
`_build_live_training_row()` gained a `section_hint` parameter; all three
call sites (`_record_live_training_row`/`_record_sequence_heartbeat`/
`_record_sequence_keyframe`) now pass `self._get_section_hint()`. This
reaches live corpus rows *and* every sequence corpus row (heartbeat and
keyframe alike) for free, since all three already funnel through the one
row builder -- no separate merge into `_sequence_director_fields()` needed
(that would have re-fetched the same hint a second time per tick).

**New `section_change` keyframe event, one per real boundary crossing.**
Previously nothing marked *when* the mixer's structure actually changed --
only the current state was available at each existing event's timestamp.
`_maybe_record_section_change()` tracks `self._last_section_signature`
(a `(role, label)` tuple) and fires a `section_change` keyframe
(`from_role`/`from_label`/`to_role`/`to_label`/`tier`/`confidence`) exactly
on a change, not once per tick spent inside a section. The very first hint
seen seeds the signature without firing, so app startup mid-song doesn't
read as a spurious transition.

**Scoring: a new `structural_sync` director dimension, nullable.**
`_extract_director_events()` now also samples `section_change` events and
carries `section_role`/`section_label`/`section_bars_left` context on every
sampled event (mode_transition/drop_fire/impact_fire alike), and
`_build_director_payload()` reports `stats.section_changes`/
`stats.section_hint_coverage_pct` so the LLM (and a human reader) can tell
"no mixer session this run" (0%) apart from "a mixer session that didn't
cross many boundaries." The new fifth dimension follows the detector's
existing `external_agreement` convention: scored null, not 0, when no
mixer hint existed that session -- a missing signal is not evidence of
poor sync. `scorecard.md` gained a non-LLM "Song Structure & Key" section
(section-change count, section-hint coverage %, key coverage %) --
descriptive completeness stats, not a heuristic score.

**A pre-existing bug found while reviewing a live session's first reports
under the new capture, unrelated to the capture work itself but fixed in
the same pass:** every `scored_at` timestamp across all four score files
read `2023-10-02T14:30:00+00:00` in a real session -- the LLM had no
reliable notion of "now" and invented a plausible-looking wrong one, and
`llm_data.setdefault('scored_at', now_iso)` only fills a *missing* key, so
the packaging script's own correct clock (`now_iso`, already computed)
never overrode it. Changed to an unconditional overwrite -- the packaging
script's own clock is always authoritative for this field.

**Cross-session collision, surfaced and left as a process note, not fixed
here:** while this work was in progress, a concurrent session sharing this
machine's working directory for `drop-ins/dj-mixer-01` committed and
pushed (`beaeeb4`, an unrelated version-renumbering commit) while this
session's uncommitted `dj_mixer_controller.py`/test changes were sitting in
that same working tree -- they were swept into that commit with no
changelog credit. Per the git-history-safety rules, the already-pushed
commit was left untouched; a small follow-up commit (`b3bcb62`) gave the
key-exposure feature its own version bump and changelog line. No process
change proposed here -- flagged for the owner's awareness since it's a
real collision risk any time two sessions edit the same drop-in's working
directory concurrently.

**Verified:** full main-repo suite green (1614 passed), dj-mixer-01's own
full suite green (1040 passed, 1 skipped), `ruff`/`bandit` clean on every
touched file. New tests: `_current_track_key`/`now_playing_snapshot` key
coverage (dj-mixer-01), Camelot decode + `mixer_bpm`/`section_*` field
presence and absence (`test_auto_vj_live_training.py`),
`_get_mixer_bpm`/`_maybe_record_section_change` boundary/no-op/seed cases
(`test_auto_vj_phrase_structure.py`), `_extract_director_events`/
`_build_director_payload` section coverage and the `scored_at` override
(`test_package_training_set.py`).

**Not done this pass, left as known gaps:** `key_detect.py`'s detection
confidence isn't persisted upstream by dj-mixer-01's analyzer, so
`key_strength` stays permanently 0.0 until that's addressed at the
analyzer level (would need an `ANALYSIS_VERSION` bump there, out of scope
for a corpus-capture pass in a different repo). No structural_sync
*formula* was computed -- the LLM judges it qualitatively from the raw
event samples, matching how every other director dimension already works;
a fitted metric is deferred until there's enough mixer-sourced session
data to validate one against.

---

## House-Family Consolidation: Adjacent BPM Bands, `dance` Revived, Centroid De-Weighted (2026-08-10)

Follow-on to the previous day's whole director/detector/recommender batch
and the same day's overnight training session (`library/b`, 9 hours, 129
tracks) and multi-session investigation with `dj-mixer-01` into the
`house`/`tech_house` centroid confusion and a `house`/`deep_house` tempo
overlap the investigation surfaced along the way. Owner's own words on the
overall approach: "we're going to have to do our best guesses at
rationality, maybe slim down our categories even more and call it 'good
enough' for now until this thing gets out in the wild... better to fit
well into a few less categories than appear straight up wrong a lot."

**House-family BPM bands moved from soft/overlapping to adjacent.**
Previously `house` (120-128) and `tech_house` (122-130) shared 6 of
`tech_house`'s 8-BPM span; `deep_house` (118-124) sat entirely inside
`house`'s old range. New bands, owner's explicit numbers:

| Profile | Old hint | New hint | `bpm_prior_mu` | `bpm_prior_sigma` |
| --- | --- | --- | --- | --- |
| `deep_house` | 118-124 | **112-118** | 121.0 -> 115.0 | 0.30 -> 0.10 |
| `house` | 120-128 | **118-126** | 124.0 -> 122.0 | 0.35 -> 0.10 |
| `tech_house` | 122-130 | **127-134** | 126.0 -> 130.5 | 0.16 -> 0.09 |

`mu` is the new band's center; `sigma` tightened as far as it can usefully
go given `auto_vj.py`'s `tempo_fit` scoring floors sigma at `0.08` (a value
below that has zero further effect on the live composite score — see
`_gaussian_fit()`'s docstring). This only sharpens the **recommender's**
genre discrimination; `beat_grid.py`'s own detector-search floor
(`_MIN_PROFILE_PRIOR_SIGMA = 0.45`) is deliberately untouched, so this
doesn't narrow what tempo the live detector searches for or locks onto —
only how confidently the recommender favors a profile once a tempo is
already found. Bands are adjacent (touching at the boundary, e.g.
`deep_house`'s 118 == `house`'s 118) rather than gapped, matching the
existing `chillstep`/`deep_house` convention elsewhere in the roster.

**`electronic` revived and renamed to `dance`.** Disabled 2026-08-06
because its `expected_bands` fingerprint was non-discriminating — ≥0.95
cosine-similar to nearly everything, including far-tempo genres. That
stops being disqualifying once the profile's whole purpose is redefined:
"the same 4-on-the-floor house-tempo material minus vocals... vocals is
enough to carry the split, otherwise basically indistinguishable" (owner).
Every field except `vocal_hnr_mu`/`vocal_fmr_mu` is now a deliberate copy
of `house`'s own values (same band, same `expected_bands`, same
weights) — the split is meant to ride entirely on `vocal_hnr_fit`/
`vocal_fmr_fit`, which is the first real use those two terms have had
since their copy-bug fix earlier the same day (`AudioManager.
_copy_audio_into()` silently dropping them — see the "Vocal-Presence Core
Bug" entry above). Dict key kept as `electronic` for backward
compatibility with any config/corpus data that references it by key; only
`name` (`"Electronic"` -> `"Dance"`) and `enabled` (`False` -> `True`)
changed.

**`rap_rnb` mu moved to an explicit owner judgment call, not fit from this
session's data.** 86.5 -> 85.0 (band center unchanged, 70-100), sigma
0.27 -> 0.20. The library's own rap/r&b sample (n=13-25) was independently
flagged twice in the same investigation: unrepresentative (mostly
accidental agent-download inclusions, not a curated test set) and
separately found to carry a real ~24%-in-one-direction 4/3 tactus-fold
contamination (see the multi-session investigation notes below) — so
last night's measured median was explicitly *not* used as the target
here, on the owner's own reasoning that using it anyway "is not a good
reason and should therefore be deferred pending training on some serious
rap/r&b/etc libraries."

**`hyphy` relabeled "Hyphy / Trap", band widened 90-110 -> 100-118.**
Dict key kept as `hyphy` for backward compatibility. Owner: "rap/rnb/trap
all should have solid deep bass lines as well.. hyphy not so much" — the
existing `bass_weight` (1.5, already the highest in the family) kept
as-is rather than lowered, since this merged profile's real-world matches
are expected to skew trap (808-driven) more than pure hyphy going
forward.

**`centroid_fit` weight: 1.0 -> 0.8. The formula bug itself stays open,
unresolved.** Root cause of the `house`/`tech_house` confusion: `expected_
bands`-derived `spectral_centroid_mu` (all 20 profiles, recalibrated the
previous day) and the live `centroid_fit` measurement are structurally
different formulas — `expected_bands` weights 64 *log-spaced* perceptual
band centers (correctly matching `audio_spectrum.py`'s visual bars, which
is what `spectral_shape_fit`'s own cosine-similarity comparison actually
needs and is untouched here), while the live measurement weights the raw
512-bin FFT *linearly* across the full Nyquist range. A library-agnostic
fix was attempted — bandwidth-weighting each log-band's contribution to
approximate what a linear formula would produce, using no real audio data
at all — and does **not** hold up empirically: tested against `tech_
house`'s own fingerprint, it overshoots the real measured average
(3520 Hz, from `library/b`) by more than 2x (7594 Hz), because `expected_
bands`' per-band values are relative prominence ratings, not a true per-Hz
energy density, and log-spaced high-frequency bins are wide enough in raw
Hz that naive bandwidth-weighting assumes far more real energy up there
than plausibly exists. No clean formula-only fix was found. Recalibrating
`mu` from any one library's real measured data was considered and
rejected for the same reason the `deep_house`/`house` tempo question was
(see below) — it would tune a shipped default to that library's sourcing
habits, not the genre. The weight cut reflects the owner's own house-
family philosophy (BPM primary, brightness a secondary tiebreaker) rather
than standing in as a fix for the still-open formula bug.

**Update, 2026-08-11:** the bug described in this section is fixed — see
"Recommender `centroid_fit` Weight Cut + `tech_house` Disabled" §
Addendum, near the top of this document. The fix that eventually worked
wasn't a library-agnostic approximation of the *old* formula (the
bandwidth-weighting attempt above); it was replacing the *live*
measurement's formula with the same log-band-weighted-mean-frequency
computation `mu` was already derived by, so no approximation or new
library data was needed after all.

**A collection-bias trap, found and corrected mid-investigation, worth
keeping in mind for any future per-profile tuning off real session data.**
The multi-session investigation (this session + `dj-mixer-01`, using the
mixer's own independently-analyzed BPM/key/structure store for 449
tracks) initially read `deep_house`'s real tempo distribution (from
`library/b`) as fully overlapping `house`'s — both centered ~125 BPM. That
overlap conclusion is real *for this library*, but the mixer session
caught an important distinction the first pass had run together: "can
tempo separate house from deep_house" (no, not in this collection) is a
different question from "is `deep_house`'s configured range wrong" (the
sample can't answer that, because it isn't a sample of the genre — ~99%
of the owner's library is Mixcloud-sourced, and that source runs
124-126 regardless of genre tag; owner confirmed independently: "for
whatever reason almost all mixcloud tracks are 124-126 and that's where
they all came from"). The shipped `deep_house` band (112-118) reflects
the owner's own genre-convention judgment, deliberately *not* fit to this
library's skewed sample — the same caution applies to any other profile
whose "real" data all comes from one collection.

**Also settled in the same investigation, not yet acted on:**
`bpm_hint_min`/`bpm_hint_max` was confirmed to have **zero live effect on
recommendation** — `tempo_fit` (weight 2.0, the recommender's single
highest-weighted term) is computed entirely from `bpm_prior_mu`/`sigma` in
log2(BPM) space; `hint_min/max` only feeds the HUD label and a scorecard
"was the detected BPM in range" metric. A proposal to derive `hint_min/
max` from `mu`/`sigma` was raised and rejected: `hint` grades the
detector, `sigma` steers it, so deriving the yardstick from the steering
knob would let widening the knob auto-improve the score with nothing
having actually gotten better — the same failure shape as the hard-clamp
bug already reverted (see "BPM Detector Audit" below), just relocated
from search into measurement. Agreed direction instead: keep the two
independently authored, and add a drift-canary test asserting `mu` always
falls inside `[hint_min, hint_max]` so a future edit to one without the
other fails loudly rather than drifting silently — implemented as `test_
bpm_prior_mu_falls_inside_its_own_hint_range()` in `tests/test_audio_
profile_deep_house_and_disable.py`, checked against every profile with a
hint range set (20 at the time this test was written; 17 after the
same-day elimination pass below).

**Deferred, not implemented this pass**: a triplet-aware extension to
`tactus_preference_ratio`. The same investigation found a real, well-
evidenced detector bug — 24 of 28 tempo folds across a 437-track join
against embedded BPM tags are 2/3 or 4/3 ratio (triplet/three-against-four
ambiguity), not the classic 2x/0.5x octave folds `tactus_preference_ratio`
already handles — concentrated specifically in R&B/Hip-Hop (24.3% fold
rate vs. 0.6% for house-family, a ~40x relative risk, binomial-significant
at n=437). Recommended as a principled extension of the existing
mechanism (not a new one) once scoped with its own test fixtures built
from the real fold examples — not bundled into this pass since it's a
detector behavior change, not a config/weight tweak, and deserves its own
review.

**Verified:** full main-repo suite green (1597 passed after fixing one
pre-existing boundary-touch assertion in `test_audio_profile_synthwave.py`
that assumed strict, non-touching separation from `house`'s old hint
range), `ruff` clean on every touched file. New tests: `test_electronic_
key_now_resolves_to_the_revived_dance_profile`, `test_dance_matches_
house_on_everything_except_vocal_presence`, `test_bpm_prior_mu_falls_
inside_its_own_hint_range` (all 20 profiles at the time), plus updated
assertions for `rap_rnb`'s new `mu` and the `electronic`/`dance`
enabled-state flip.

### Addendum (same day): `uk_garage`, `breaks`, and `generic` eliminated entirely

Immediate follow-on instruction from the owner after the consolidation
above landed: "while we're at it... let's eliminate completely the
uk_garage profile & breaks & generic." A stronger action than the
disable-and-keep pattern used for `electronic`/`generic` earlier in the
project's history (see "Fire DJ Profile Removed" and the original
2026-08-03 `generic` disable below) — these three dict entries were
deleted outright from `unicornviz/audio/profiles.py`, not just marked
`enabled=False`. `uk_garage` and `breaks` had no other load-bearing
reference in the codebase; `generic` did — it was `get_profile()`'s
hardcoded fallback for an unknown/typo'd profile key. That fallback moved
to `house`, matching the app's own already-documented default (`Audio
Manager.__init__`'s own "house" default precedent) rather than a
deliberately weak catch-all — an unknown key now degrades to a real,
well-populated profile instead of a near-inert one.

Cross-file consequences fixed in the same pass: `training-kit-01/tools/
package_training_set.py`'s `_GENRE_ALIAS_MAP`/`_GENRE_KEYWORD_MAP` had six
entries routing tags like "UK Garage," "2-Step," "breaks," and "generic"
to the now-gone keys — removed rather than left to silently miscategorize
future packaging runs; `tests/test_package_training_set.py`'s
parametrized alias-match cases for `uk_garage` swapped for still-valid
`hard_techno`/`hardstyle` cases to preserve coverage of that code path.
`drop-ins/auto-vj-01/docs/weights-and-thresholds.md`'s BPM/sigma,
centroid-sigma-tier, and zcr/onset-sigma-tier tables all had rows for the
three eliminated profiles, plus that pass's own BPM/sigma table had never
actually been updated with the house-family band changes above (it was
still showing pre-consolidation `house`/`deep_house`/`tech_house`/
`rap_rnb`/`hyphy` values) — both fixed together, `_VJ_WEIGHTS_DOC_VERSION`
-> 16, `_RECOMMENDER_VERSION` -> `1.0.0-rc.4` (retiring 3 recommender
candidates changes what the composite score is chosen among, same bump
class as retiring a scoring term).

**Verified:** full main-repo suite green (1595 passed) after replacing
the four `test_generic_*` tests in `test_audio_profile_deep_house_and_
disable.py` with `test_generic_uk_garage_breaks_eliminated_entirely()`
and `test_get_profile_unknown_key_falls_back_to_house_not_generic()`.
Live profile count: 17 (was 20 immediately before this addendum).

---

## BPM Detector Audit — Hard Clamp Removal + Mixer-BPM Hint Bus (2026-08-04)

Decision: `set_profile()` in all three tracker engines (v1/v2/v3) no longer
narrows the ACF/IOI candidate search range (`_bpm_min`/`_bpm_max`) from a
profile's `bpm_hint_min`/`bpm_hint_max` — only the soft log2-Gaussian prior
(`_prior_mu`/`_prior_sigma`) is applied. `_update_profile_recommendation()`
now reads `vj_api.get_bpm(exclude='auto_vj')` each recommender cycle and,
when a fresh `dj_mixer` hint exists, primes the tracker to it (new
`prime_tempo()` on `BeatGridTracker`/`BeatTracker`, inherited by
`BeatTrackerV3`) and adds it as a top-weighted hypothesis to the
recommender's tempo evidence. Full audit: `docs/audits/2026-08-04-bpm-detector-audit.md`.

**Root cause — this supersedes, not just extends, the 2026-07-18 v3 fix
above.** That investigation correctly identified the *prior* re-prime as a
feedback-loop mechanism and froze it in v3 while locked. It missed a second,
dominant mechanism in the *same* `set_profile()` call, present in **all
three engines since 2026-06-20** (not just v2/v3): `bpm_hint_min`/
`bpm_hint_max` hard-clamp `_bpm_min`/`_bpm_max`, which bound the ACF's
candidate array itself (`_setup_acf_arrays()`) and the v1 IOI-median
candidate filter. Once a profile narrows that range, the true tempo — if
outside it — can **never again be represented as a candidate**, so the
next estimate is forced inside the wrong window; that estimate then
"confirms" the wrong profile to the recommender, which re-applies it. v3's
2026-07-18 fix left this clamp in place (`set_profile()`'s locked branch
still applied `bpm_hint_min`/`bpm_hint_max`, per that entry's own text
above) — it fixed the prior-drift symptom while leaving the mechanism that
actually explains a hard "stuck at a wrong lane" lock unaddressed. Live
evidence: `logs/unicornviz_20260804_082732.log` showed `Generic → Psytrance
→ Generic → Psytrance` profile thrash within 80s, each Psytrance apply
priming a `[140, 149]` search window, during a session the operator
independently reported as "32 over."

**Fix — P0-A (search-range clamp removed):** `set_profile()` in
`BeatGridTracker`, `BeatTracker`, and `BeatTrackerV3` now only ever updates
`_prior_mu`/`_prior_sigma` (and, for v2/v3, recomputes `_acf_prior` over the
*existing* `_acf_bpms` array — never rebuilds it). `_bpm_min`/`_bpm_max` are
set once at construction from config and never touched again by a profile
switch, so the ACF/IOI search always covers the full configured range.
`bpm_hint_min`/`bpm_hint_max` remain on `AudioProfile` (used only by
`preferred_bpm_range()` for HUD display) but are no longer read by any
tracker. Consequence for v3 (**P1-D**): with no clamp left to apply, a
profile switch while confidently locked is now a **complete no-op** (not a
partial freeze) — and `_reset_tempo_lock()` needs no range-restoration
logic, since there is no longer a narrowed range to go stale.

**Fix — P0-B (mixer BPM as ground truth):** the shared BPM hint bus
(`app.publish_bpm()`/`get_bpm()`, 5 s TTL — see "Recommender → Tracker
Profile Apply" below for `dj_mixer`'s existing borrow-when-idle consumer)
already let `dj_mixer` borrow *our* estimate; this closes the loop the
other direction. Each `_update_profile_recommendation()` cycle (gated by
`profile_auto_reco_eval_interval_s`, default 8 s), if `get_bpm(exclude=
'auto_vj')` returns a fresh nonzero value, calls `grid.prime_tempo(bpm)` —
which sets `_bpm` directly, raises (never lowers) `_confidence` /
`_acf_confidence` / `_phase_confidence`, and refreshes `_tempo_hold_until_t`
so the ACF's own continuity guards don't immediately fight the primed
value — and appends it to `top_cand_log2s` at full weight so profile
scoring considers it directly. The deck's own per-track analysis is
authoritative when present; this is intentionally a short-circuit, not
another vote for the ACF to weigh.

**Fix — P1-C (recommender evidence unclamped from the *active* prior
too):** `top_candidates` (read by the recommender for `top_cand_fit`
multi-hypothesis scoring, across *every* candidate profile being
evaluated) was computed from the prior-weighted `score` array — meaning
even with P0-A's range fix, the top-3 hypotheses were still biased toward
whichever profile happened to be *currently* active, potentially
suppressing a tempo lane a different candidate profile would have scored
well. Now sourced from the raw, prior-free `comb_score` array (still
range-limited only by the — now never-narrowed — configured bounds); the
lock decision itself (`peak_idx`, tactus descent, EMA) is unchanged and
still uses the prior-weighted `score`.

**Fix — P2-E (profile data hygiene):** `generic`'s `bpm_hint_min`/
`bpm_hint_max` removed (it's a disabled catch-all fallback, not a genre —
see "Capability-aware disable" below — so it has no real tempo sweet spot
to display). Separately, the recommender's own `_profile_score()` sigma
floor (`max(0.08, ...)`) was six times looser than the live detector's
`_MIN_PROFILE_PRIOR_SIGMA` (0.45) — meaning several genres' raw
`bpm_prior_sigma` (0.16-0.22, tighter than what the detector itself ever
actually applies) drove sharp, brittle `tempo_fit` differentiation between
adjacent-tempo profiles during *scoring*, even though the live tracker's
own prior was always floored at 0.45. Recommender floor raised to match
(0.45) so scoring and live detection agree on how tight a genre prior is
allowed to be.

> **Reverted 2026-08-06** — this specific change was wrong; see "Recommender
> Sigma-Floor Revert" below. The two floors were never the same concern.

### Recommender Sigma-Floor Revert (2026-08-06)

Decision: the `_profile_score()` sigma floor from P2-E above is reverted
from `max(0.45, ...)` back to `max(0.08, ...)` — its pre-P2-E value.

**Root cause:** P2-E's premise — two sigma floors disagreeing is itself a
bug — was wrong. The detector's floor (`beat_grid._MIN_PROFILE_PRIOR_SIGMA
= 0.45`, unchanged, still correct) protects *live ACF search* from a
profile's prior dominating real acoustic evidence. The recommender's floor
governs something unrelated: how much a tempo mismatch counts as evidence
*against* a candidate genre while scoring which profile to recommend.
Unifying them under one constant quietly defanged the second job. Verified
live (2026-08-06 training session, ~115 min, BPM 110-135 throughout,
`recommender_score.md` unchanged at 1.75/5 across two consecutive
sessions): the session's actual 64-band spectral fingerprint correctly
favored `deep_house` over `psytrance` (cosine similarity 0.879 vs 0.776
against the real corpus data) — `spectral_shape_fit` was doing its job —
but `psytrance` (mu=145) still won the composite score, because at 0.45 a
30 BPM miss cost `tempo_fit` only about -0.26 raw (~-0.5 weighted at 2.0);
at the reverted 0.08 (i.e. each profile's own authored sigma — psytrance's
real 0.16 — since 0.08 is below every profile's value and never actually
binds), the same miss costs about -2.02 raw (~-4.0 weighted), enough to
matter against the other ~12 weighted terms.

**Verified:** new cases in `tests/test_bpm_detector_audit_regressions.py`
— a source-text guard on the exact constant, and an end-to-end
`_update_profile_recommendation()` run (candidates restricted to
`psytrance`/`deep_house` to keep it deterministic against the full
20-profile field) reproducing the live session's shape: `bpm=120`,
`centroid`/`zcr`/`onset_count` set partway toward psytrance's own targets
(bright, moderately dense — see the 2026-08-06 recalibration note directly
below for why not psytrance's exact targets). Confirmed directly against
both floor values while building the fix: `deep_house` wins at 0.08,
`psytrance` wins at 0.45 — the test fails without the revert, not just
after it.

**Verified:** `tests/test_bpm_detector_audit_regressions.py` — (1) locked
at 124 BPM, apply a Psytrance-like profile (mu=145, σ=0.16), continue
feeding steady 124 BPM audio → reported BPM stays within ±2 of 124; (2)
silence-reset after that same mismatched profile → next lock on a fresh
100 BPM click track lands within ±2 of 100; (3) the recommender decider
never double-applies within its cooldown; (4)/(5) a recommender cycle
calls `prime_tempo()` exactly when a fresh mixer hint exists, not
otherwise. Plus per-engine unit coverage in `test_beat_grid_tracker_v1.py`
/ `test_beat_tracker_v2.py` / `test_beat_tracker_v3.py` for the new
`prime_tempo()` method and the never-narrows-range contract.

### Recommender Weight Review — `centroid_fit` Raise + Sigma Tightening (2026-08-06)

Decision: following the sigma-floor revert above, the owner asked for a
full weight/term inventory across the director, detector, and recommender,
then requested two follow-on changes to the recommender:

1. **`centroid_fit` weight raised `0.8` → `1.5`** in `_DEFAULT_RECO_WEIGHTS`
   (`auto_vj.py`). With the sigma-floor bug fixed, live corpus data showed
   `spectral_shape_fit`/`centroid_fit` were already discriminating correctly
   (0.879 vs 0.776 cosine similarity, deep_house over psytrance) but were
   underweighted relative to `tempo_fit` (2.0) given how reliable they'd
   proven. Still kept below `tempo_fit`: tempo has a *per-genre* sigma
   (tight for psytrance, wide for house); `centroid_fit`'s Gaussian uses a
   **fixed 400 Hz sigma across every profile** regardless of how far apart
   their `spectral_centroid_mu` targets actually sit — a real asymmetry
   with `tempo_fit`'s per-profile mechanism, flagged but deliberately left
   alone this pass (see Open Questions).
2. **`bpm_prior_sigma` tightened for three of the four profiles flagged as
   outliers** in the weight review (`unicornviz/audio/profiles.py`):
   `breaks` `0.28` → `0.22`, `rap` `0.30` → `0.24`, `synthwave` `0.40` →
   `0.34`. `fire_dj` (`0.32`) was explicitly **not** touched — its wide
   36 BPM hint span (132-170) is intentional (it's the wide-tempo DJ-run
   catch-all profile), unlike the other three where the sigma sat wide
   relative to a comparatively narrow `bpm_hint_min`/`bpm_hint_max` span.
   Values chosen by matching each profile's sigma-to-hint-span ratio against
   comparable-span profiles already in a good place (e.g. `breaks`' new
   0.22 lines up with `hard_techno`'s 0.22 at a similar 12-13 BPM span).

**Recalibration note:** `test_recommender_prefers_deep_house_over_psytrance_at_120_bpm`
originally used psytrance's *exact* `centroid`/`zcr`/`onset_count` targets
as the adversarial input. After the `centroid_fit` raise, that exact match
alone is enough to win psytrance the composite score regardless of the
sigma floor — correctly, since a track with psytrance's literal spectral
centroid should score higher on psytrance now. The test's synthetic values
were dialed back to a still-adversarial but non-exact point (`centroid=2350`
vs psytrance's `2500` target) so it keeps isolating the sigma-floor
mechanism specifically rather than accidentally passing on the weight
change alone. Verified both directions with `__pycache__` cleared before
each run — a stale compiled `auto_vj.pyc` from mid-session sigma toggling
was independently found to be silently serving pre-edit bytecode during
manual verification, unrelated to but worth noting for anyone hand-testing
this file with direct `sed` edits.

**Terminology/weights reference:** the full glossary and per-model weight
tables (director thresholds, detector confidence-blend terms, recommender
`_DEFAULT_RECO_WEIGHTS`) referenced during this review now live in
[`drop-ins/auto-vj-01/docs/weights-and-thresholds.md`](../../drop-ins/auto-vj-01/docs/weights-and-thresholds.md),
which is versioned independently and must be kept in sync with
`_VJ_WEIGHTS_DOC_VERSION` in `auto_vj.py` — see that doc's own header and
the CLAUDE.md agent rule added alongside it.

### Per-Profile Centroid Sigma + Accuracy Tracking Tier 1 (2026-08-06)

Decision: resolves the `centroid_fit` fixed-400-Hz-sigma asymmetry flagged
above as an Open Question, and ships Tier 1 of the accuracy tracking spec
(`docs/planning/auto-vj-recommender-accuracy-tracking-2026-08-06.md`).

1. **Per-profile `spectral_centroid_sigma`.** New `AudioProfile` field
   (`unicornviz/audio/profiles.py`), default `400.0` (the old fixed
   constant). `centroid_fit`'s Gaussian now reads it per candidate instead
   of a hardcoded `400.0`, mirroring `tempo_fit`'s `bpm_prior_sigma`
   mechanism exactly. Owner explicitly chose the cheap route over a fitted
   one: three coarse tiers (`250`/`400`/`600`) assigned by genre feel —
   tight for genres with a real, consistent timbral signature (`dubstep`'s
   wobble, `psytrance`'s saw leads, `tech_house`'s stripped percussion),
   wide for broad-church catch-alls (`house`, `electronic`, `fire_dj`,
   `generic`, plus `rap`/`r&b`/`hyphy`/`ambient`/`chillstep` for their
   sub-genre variance). `house`'s wide tier mirrors its already-wide
   `bpm_prior_sigma` (`0.35`) for the same reason: the owner's library
   carries a wide house genre set (tropical, afro, progressive, etc.) with
   real spread, not a calibration gap. Full tier table in
   `weights-and-thresholds.md`. Explicitly a first pass, not a fitted
   result — the plan is to replace these three numbers with values fitted
   from Tier 2's hit/miss data once that exists, not to treat them as
   final.
2. **Accuracy tracking spec, Tier 1 (signal activity) implemented.**
   `_update_profile_recommendation()` now captures each candidate's raw
   per-term values (via `_profile_score()` returning `(composite, terms)`
   instead of just the composite) and logs `term_spread` — each term's
   `max - min` across all scored candidates that cycle — on the existing
   `profile_recommendation` decision-log event. `lock_rate`/`mean_conf`/
   `mean_dconf` are structurally excluded from spread analysis: they're
   computed once per cycle from the sample window, not per candidate, so
   every candidate gets an identical value and their spread is always
   `0` — that means "not a genre-fit term", not "this weight does
   nothing", and treating it as the latter would be a real
   misinterpretation risk. `training-kit-01/tools/session_scorecard.py`
   rolls this up into a new "Signal Activity" section: per term, the
   fraction of eval cycles across the scored sessions where its spread
   cleared a `0.05` activity threshold.
3. **Tier 2 open questions, answered by the owner (2026-08-06):**
   - Genre-tag → profile-key mapping: proceed as spec'd (many-to-one
     lookup table, explicit unmapped bucket) — the owner's training
     library is expected to stay accurately and completely tagged, so the
     mapping table is the main remaining risk, not tag data quality. Owner
     additionally asked for a **fuzzy fallback**: a tag that doesn't match
     any profile exactly (e.g. "Tropical House", "Afro House" — real
     sub-genres in the library with no dedicated profile) should fall back
     to a keyword match (e.g. ends in "house" → `house`) rather than
     landing in the unmapped bucket. Two-pass lookup — exact/alias match
     first, keyword fallback second, explicit-unmapped only if neither
     hits — captured in the spec doc; not yet built (Tier 2 as a whole is
     still unimplemented).
   - Untagged tracks: **log them** (not silently skip) — visibility into
     how much of a session's accuracy signal is actually usable matters,
     even though untagged tracks still don't count toward the hit/miss
     rate itself.
   - Rollup location: confirmed, `scorecard.md` generation.
   - Live vs. offline: owner said they're "kinda shootin' for" tag genre
     eventually becoming a live ground-truth signal, not just a
     packaging-time measurement — this is a real intended direction, not
     hypothetical, though still unscoped and not started. See the spec
     doc's updated framing.

### External Section-Hint Bias Gated by `bars_left` Proximity (2026-08-06)

Decision: `_phrase_bias()`'s external-hint-match term (added Phase 2,
2026-08-05) is gated by proximity to the mixer's own `bars_left`, instead
of firing at full `phrase_bias_max × confidence` strength the instant the
mixer's published role matched the role being evaluated.

**Root cause, found live:** on a session running current code (auto-vj-01
1.0.0-rc.14, mixer publishing real section hints), the owner observed the
director catch a build at its very start and then favor DROP almost
immediately — well before the mixer's actual analyzed drop point. Reading
`_phrase_bias()`: the match term used only `role` and `confidence`,
completely ignoring `bars_left` (published specifically for this, plan
§6 amendment 6.a). "Mixer confirms we're in BUILD" was identical evidence
at bar 1 of a 32-bar build and bar 31 -- a confident hint right as BUILD
*started* lowered the DROP threshold just as hard as one right before the
mixer's own analyzed drop. That's backwards: confirming the *current*
role early in a long phase is evidence the director is tracking the song
correctly, not evidence a transition is imminent.

**Fix:** new `phrase_external_proximity_bars` (default `8.0`). When the
hint includes `bars_left`, the match term's strength ramps
`0.0 → 1.0` as `bars_left` goes from `phrase_external_proximity_bars` down
to `1`, so it only escalates as the mixer's own analyzed phase is actually
ending. A hint with no `bars_left` (older mixer payload) falls back to the
prior flat behavior (`proximity = 1.0`) rather than going silently inert.
The mismatch term is unchanged -- a confident disagreement is real
evidence regardless of proximity, unlike a match.

**Verified:** `tests/test_auto_vj_phrase_structure.py` -- a far-from-end
hint (`bars_left=30`) sits close to the no-hint baseline where a
near-end hint (`bars_left=1`) sits close to the old full-strength value;
a hint with no `bars_left` key reproduces the exact pre-fix flat-strength
number. `_VJ_WEIGHTS_DOC_VERSION` bumped to 3; see
`weights-and-thresholds.md`'s Director section for the updated term
description.

### Fire DJ Profile Removed, Replaced by a Wide-BPM-Range Easter Egg (2026-08-06)

Decision: the dedicated `fire_dj` `AudioProfile` is removed entirely from
`PROFILES` (owner call: "let's kill the fire dj profile"). The Fire DJ
celebration effect itself is unaffected -- only its trigger condition
changed.

**Why:** `fire_dj` existed as a wide-tempo (132-170 BPM) catch-all genre
profile specifically so the recommender could match "the DJ is running a
fast, wide-tempo electronic set" and switch to it, which in turn fired the
celebration. But that's a genre-classification detour for a fact that's
directly observable: whether the DJ actually spanned a wide tempo range.
Using a *profile* for it meant the celebration only fired when the
recommender's composite score happened to prefer `fire_dj` over every
other candidate that cycle -- an indirect, competable signal, not a direct
measurement.

**New mechanism:** `_maybe_check_wide_bpm_easter_egg()`
(`auto_vj.py`, called every `update()` tick) samples locked BPM readings
(confidence >= `_BPM_LOCK_CONFIDENCE`) into a rolling window, throttled to
one sample per `wide_bpm_sample_interval_s` (default 2.0s) to keep the
window cheap at frame rate. Once the max-min span across the surviving
samples in the last `wide_bpm_window_s` (default 600s / 10 min) clears
`wide_bpm_span_threshold` (default 30 BPM, owner-selected), it fires
`_trigger_fire_dj_celebration()` -- the same celebration as before,
unchanged. Retrigger gate reuses the existing `fire_dj_cooldown_s` /
`_fire_dj_last_t` (default 1200s / 20 min) rather than adding a new
cooldown constant, since the owner's own framing ("resets after
triggering every 20mins") already matched the pre-existing celebration
cooldown exactly.

**Removal scope (owner chose "full removal" over disable-and-keep, unlike
the `generic` pattern):** the `PROFILES` entry, its expected-bands
fingerprint, and every current-state doc reference (weights-and-
thresholds.md's two sigma tables, `AUDIO_PROFILE_CHEAT_SHEET.md`,
`docs/audio-profile-reference.md`, `docs/user-guide.md`'s profile table)
are gone. Historical references are left alone, per this ADR's own
no-rewrite-history rule -- past `fire_dj` tuning entries in this document,
old README changelog lines, and the training corpus's own generated
scorecards still say what they said when they were written.

**Verified:** new `tests/test_auto_vj_wide_bpm_easter_egg.py` covering:
span below threshold does not fire; span at/above threshold fires once
and respects the cooldown; unlocked/low-confidence BPM readings are not
sampled; old samples outside the window are pruned before the span
check. Full suite green; `fire_dj` no longer appears in
`enabled_profiles()`/`PROFILES`/`get_profile()`.

### Wide-Tier Catch-All Profiles: `electronic` Disabled (2026-08-06)

Decision: `electronic` is disabled (`enabled=False`, same disable-not-delete
pattern as `generic`) after live evidence plus a cosine-similarity audit
showed it winning the recommender by being broadly tolerable rather than
being the best specific fit -- the same underlying pattern as the `fire_dj`
removal above, this time surfaced by the owner's stated preference: "i'd
rather not have any generics really."

**Live evidence:** a training session running current code (post `fire_dj`
removal) sat on `electronic` for most of ~18 minutes while the mixer's own
logs showed every track playing at a consistent 122-125 BPM -- a range
`deep_house` (mu=121) matches at least as well, yet `deep_house` won only
once, briefly, before `electronic` took over and held.

**Audit, to answer "is it catching a unique signal or just overlapping
valid sub-genres":** computed cosine similarity between `electronic`'s
`expected_bands` and every other profile's. Result: `electronic` is
**more** similar to profiles with wildly different tempos --
`trance` (0.9962, 13 BPM away), `hyphy` (0.9950, 30 BPM away),
`psytrance` (0.9871, 20 BPM away), `drum_and_bass` (0.9840, 49 BPM away)
-- than to its own close-tempo neighbors `deep_house` (0.9547) and
`house` (0.9403). A profile whose spectral fingerprint doesn't
discriminate by tempo-neighborhood isn't capturing anything specific; it
reads as a near-flat vector that resembles the whole catalog roughly
equally. Its `bpm_hint` range (118-132) was also already fully covered by
`house`/`tech_house`/`deep_house`/`peak_time` -- no tempo gap either.
Verdict: not a unique signal, not filling a gap -- a second `generic`
wearing a narrower BPM label.

**Same audit run against the other wide-tier profiles** (`rap`, `hyphy`,
`r&b`, `ambient`, `chillstep`, plus `house` as a healthy-pattern
reference), owner-requested as a "double checker" before committing to a
broader cleanup:

- `ambient` -- genuinely distinctive (0.83-0.93 similarity range, well
  below everyone else's 0.95+). Real signal. Not touched.
- `house` -- healthy pattern: its top matches are genuine close-tempo
  siblings (`peak_time` gap 6 BPM, `tech_house` gap 2, `electronic` gap
  1). High similarity concentrated among things that actually *are*
  similar, unlike `electronic`'s scattered-across-random-tempos pattern.
  Not touched -- also matches the owner's earlier, separately-justified
  reasoning for keeping `house` wide (`bpm_prior_sigma=0.35`, the widest
  BPM sigma of any profile, due to a genuinely wide house sub-genre set
  in the training library).
- `hyphy` and `chillstep` -- same red flag as `electronic`: top-5 matches
  are almost all 30-50 BPM away at 0.97-0.99 similarity, nothing from
  their own tempo neighborhood ranks near the top (`hyphy` and
  `electronic` are even each other's #1 match despite a 30 BPM gap).
  **Flagged as the same case as `electronic`, not yet acted on** --
  owner has this evidence, decision pending.
- `rap` and `r&b` -- borderline. Each other's #1 match is a genuine
  sibling relationship (`r&b`↔`rap`, 3 BPM apart -- hip-hop and R&B do
  share a sound), but further down their top-5 they also pick up
  far-tempo noise. Weaker case than `hyphy`/`chillstep`; **not
  recommended for automatic inclusion** in the same cleanup without
  separately checking whether those specific matches are musically
  justified, the way the Coolio-track trance flip below turned out to be.

**A caution baked into this decision, from the same live session:** a
`trance` flip that looked like thrashing in the logs turned out, on the
owner actually listening, to be a musically correct read of a real
trance-y section in the track -- not a bug. Flip *frequency* alone isn't
evidence of a problem without knowing whether the room agreed with each
flip. This is exactly the gap the accuracy-tracking spec's Tier 2 (tag-
genre ground truth) is aimed at closing eventually; until then, disabling
`electronic` rests on the cosine-similarity structural argument (a
fingerprint that doesn't discriminate by tempo-neighborhood), not on flip
frequency, which was independently shown to be an unreliable signal in
this same session.

**Verified:** `enabled_profiles()`/`list_profiles()` exclude `electronic`;
`get_profile('electronic')` still resolves it directly. New tests in
`tests/test_audio_profile_deep_house_and_disable.py` mirroring the
existing `generic` coverage. Full suite green.

### `rap`/`r&b` Merged; `hyphy`/`chillstep` Fingerprints Regenerated (2026-08-06)

Decision: following the double-checker audit above, `rap` and `r&b` are
merged into a single `rap_rnb` profile (owner call: "rap/r&b should be
one"), and `hyphy`/`chillstep` get freshly-generated `expected_bands`
targeting their actual acoustic differences (owner call: "hyphy/chillstep
should have distinctly different audio profiles but similar bpm").

**`rap`/`r&b` merge.** The audit above found them genuine siblings (0.9856
cosine similarity, 3 BPM apart, each other's #1 match) rather than a false
catch-all pairing -- the right fix is consolidation, not disabling either
one. `unicornviz/audio/profiles.py` field values are blended averages of
the two originals, with one deliberate correction: `rap`'s old
`spectral_centroid_mu` (1600) directly contradicted its own acoustic-notes
comment ("AcousticBrainz shows hip-hop centroids typically 800-1200 Hz");
the merge uses `1200` (honoring that documented research finding, folded
toward `r&b`'s warmer 1400) rather than perpetuating the inconsistency by
blindly averaging a known-wrong number. `spectral_centroid_sigma`
tightened `600` → `400` (wide → medium tier) now that this is a real,
intentionally-merged single genre rather than an accidental overlap.
`bpm_hint_min` takes the union floor (`70.0`, from `rap`) since both
originals agreed on the ceiling (`100.0`).

**`hyphy`/`chillstep` regeneration.** Answering "is `electronic` catching a
unique signal or overlapping valid sub-genres" (the question that started
this whole audit) surfaced a second finding: `hyphy` and `chillstep`'s
*own* acoustic_notes in `tools/gen_spectral_fingerprints.py` already
described genuinely different genres (hyphy: aggressive, bright
prominent hats 4-12 kHz; chillstep: atmospheric pads, soft recessed hats,
centroid ~900 Hz) -- but the previously-generated `expected_bands` arrays
didn't encode that difference (0.9788 cosine similarity, effectively
indistinguishable). Owner chose to regenerate properly via the LLM tool
(`tools/gen_spectral_fingerprints.py`, `gpt-4o`, real API cost) rather
than hand-tune, for consistency with how the rest of the catalog was
built.

**Method:** rather than run the full-catalog tool (which would touch
every profile and risk drift elsewhere), a scoped one-off script
(scratchpad, not committed) imported the tool module and overrode its
`_PROFILE_META` to just `hyphy`, `chillstep`, and a new `rap_rnb` entry,
then called the same `_build_prompt()`/`_call_openai()`/`_extract_json()`
pipeline. The tool's own tracked `_PROFILE_META` catalog was separately
updated (`fire_dj` entry removed, `rap`/`r&b` merged into `rap_rnb`,
`hyphy`/`chillstep` acoustic_notes sharpened to explicitly call out their
distinguishing feature) so a *future* full-catalog rerun stays accurate
without needing this ADR entry as a reminder.

**Result, honestly assessed:** `hyphy`-`chillstep` cosine similarity
improved `0.9788` → `0.9703` -- a real, measurable gain, not a full fix.
Both profiles' regenerated fingerprints still show 0.96-0.97 similarity to
several *other*, tempo-unrelated club genres (`hyphy` vs `breaks` 0.9728,
`chillstep` vs `synthwave` 0.9714). This looks like a genuine structural
ceiling on relative-magnitude cosine similarity across a cluster of
genres that share a similar broad sub-bass-to-treble envelope shape
(prominent low end, tapering through the mids, some treble presence),
not a synthesis quality problem -- pushed further with more prompt
iterations, but not chased past this point given the cost of repeated
API calls for diminishing, uncertain returns. `centroid_mu`
(`hyphy` 1800 vs `chillstep` 900, already a full octave apart) and
`zcr_mu` remain the sharper discriminators between this specific pair;
`spectral_shape_fit`/`expected_bands` is one term among ~13 weighted
ones, not the only signal carrying the distinction.

**Verified:** `rap_rnb` in `PROFILES`, `rap`/`r&b` no longer present;
`bpm_prior_mu` (86.5) correctly averages the two originals. Regression
guard on the `hyphy`/`chillstep` similarity improvement (asserts below the
old 0.9788 baseline, not a specific "good enough" target, since the
honest ceiling above means no clean target exists). New tests in
`tests/test_audio_profile_deep_house_and_disable.py`. Full suite green.
`_VJ_WEIGHTS_DOC_VERSION` bumped to 5 (see `weights-and-thresholds.md`'s
own Changelog entry).

### `centroid_fit` Weight Trimmed 1.5 → 1.3 (2026-08-06)

Decision: `centroid_fit` trimmed from `1.5` to `1.3` (owner request, part
of the same broader hand-tune pass as the `rap`/`r&b` merge and
`hyphy`/`chillstep` regeneration above — not a revert of the earlier
`0.8` → `1.5` raise, which stands on its own evidence). No new
diagnostic finding prompted this one; a plausible "the raise is causing
bad flips" theory was checked against a live session earlier the same day
and did *not* hold up (the flip in question turned out to be a musically
correct read of the track, not a bug — see the Fire DJ / `electronic`
section above for that finding). `_VJ_WEIGHTS_DOC_VERSION` bumped to 6.

### Director Arms Ahead of `next_role`; Detector's Primed-Confidence Floor (2026-08-06)

Decision: two fixes shipped together, both closing gaps the owner
identified while reviewing the same live-churn evidence used elsewhere
this day.

**Director arms ahead of `next_role`/`bars_to_next` (plan §6.b).** This
field has been on the wire since dj-mixer-01 0.145.0 (2026-08-05) but
nothing read it — the owner had assumed it already shipped ("i thought
that was done already"). `_phrase_bias()` gains a new term: while in the
current role, if the mixer's published `next_role` matches the role
being evaluated, a proximity-scaled bonus (ramped over
`phrase_arm_proximity_bars`, default `16.0` bars — wider than the
`8.0`-bar window used for the current-role-match term, since "prepare
early" should start further out than "confirmed, about to end") offsets
the ordinary current-role mismatch penalty as the transition nears. This
is the piece that most directly answers the plan's original §2 complaint
("the director jumps around trying to guess scenes... it has no
expectation of... what usually happens next") — an 8-bar build into a
known `PEAK` can now be prepared on bar 1 instead of only recognised
once `PEAK` actually arrives. Additive with the existing current-role
terms, not a replacement; independently verified via
`tests/test_auto_vj_phrase_structure.py` (arm term flips net bias
positive despite an active mismatch penalty, ramps with `bars_to_next`
proximity, only fires when `next_role` matches the evaluated role).

**Detector: `prime_tempo()`'s confidence boost now actually holds.**
Raised by the owner while discussing the beat-lock churn found in the
`garbage` bucket-h scorecard: "shouldn't it just hold for the whole
track really? ... isn't the underlying problem the detector's poor
confidence levels?" Traced directly against real corpus data
(`sequence-corpus-*.jsonl`, no `log_decisions` needed): lock-gained/
lock-lost event pairs showed the *same* BPM value (`125.0`) each time,
confidence spiking to `0.90` on gain and immediately collapsing to
`~0.20-0.28` on loss, repeating roughly every recommender eval cycle
(~8s) — not two different tempo estimates fighting for the lock slot, as
first suspected, but `prime_tempo()`'s confidence boost being purely
cosmetic. `self._confidence` gets unconditionally recomputed from the
raw `0.4 × ACF + 0.6 × phase` blend at two sites (`_absorb_onset()` and
the ACF-update path) on every single onset/tick, with no memory that a
prime had just happened — so a single onset landing outside
`phase_tol` (plausible right after a prime, since `prime_tempo()` moves
`self._bpm` without resyncing the phase oscillator) was enough to crash
it back down before the next prime arrived.

**Fix:** new `self._primed_confidence` field, set by `prime_tempo()`
alongside its existing behavior. Both `self._confidence` recomputation
sites now floor the result at `self._primed_confidence` for as long as
`self._last_t < self._tempo_hold_until_t` — i.e. for as long as the
prime stays fresh (default `tempo_hold_s = 10.0`, refreshed by each new
prime). Since the recommender re-primes roughly every 8s whenever a
fresh mixer BPM exists, this now holds confidence continuously for the
whole track in practice, matching the owner's "shouldn't it just hold"
framing directly, without needing to touch the release/acquire
thresholds themselves. Verified live-pattern reproduction in
`tests/test_beat_tracker_v2.py`: a synthetic onset forced to miss
`phase_tol` right after a prime no longer drops confidence (confirmed
the fix is load-bearing by reverting it locally and reproducing the
exact live crash, `0.90` → `0.36`, before re-applying); the floor
correctly stops applying once the hold window expires; an unprimed
tracker (`_primed_confidence` defaults to `0.0`) is unaffected.

**Scope note:** only `BeatTracker` (v2) and `BeatTrackerV3` (which
inherits `prime_tempo()`/`_absorb_onset()` unmodified) got this fix —
the legacy `BeatGridTracker` (v1, fallback-only, not the configured
default) has a simpler single-confidence model without the same failure
mode structure and was left alone. `_VJ_WEIGHTS_DOC_VERSION` bumped to 7.

### Set-Clock Hint Bus: `publish_session()`/`get_session()` (2026-08-06)

Decision: new `App`/`VjApi` bus channel, `publish_session()`/`get_session()`,
mirroring `publish_section()`/`get_section()` exactly (same 5s TTL, same
deep-copy on both sides, same degrade-to-no-op on an older core). Requested
by the dj-mixer-01 team as their last report of the day (plan §6.3): "the
mixer knows when the set ends and the director does not."

**Where this sits relative to the section bus.** `get_section()` says where
you are in a *track* (role/tier/bars_left within the current song).
`get_session()` says where you are in the *night* (phase/seconds_left
across the whole set, plus grand-finale timing). Two different questions,
same bus pattern, deliberately kept as separate channels rather than
folded into one payload — a consumer that only cares about track structure
shouldn't have to parse set-level fields it doesn't need, and vice versa.

**Payload contract** (`phase` is the required, validated field, mirroring
`role`'s job on the section bus): `phase` (`running`/`closing`/`final`/
`over`), `source` (`clock`/`last_track` — a payload field, not to be
confused with the bus's own publisher-id `source` parameter),
`seconds_left`/`minutes_left`, and — present only when `phase == 'final'`
— `track_total_s`/`track_remaining_s`/`final_peak_s`/`final_peak_in_s`.
The mixer computes `final_peak_s` from its own structure analysis (the
`major`-tier peak from §6, or the last peak of any tier if none is ahead
of the playhead) so a finale can fire *on* the track's actual biggest drop
rather than on a bare timer.

**Shipped guarded on both ends already, so this "lights up" with no
further coordination needed.** dj-mixer-01 0.152.0 was already calling
`vj_api.publish_session(...)` conditionally (only if the attribute
exists) before this landed — the exact same defensive pattern this
project's own Drop-In Independence Rules require. Consuming
`get_session()` on the auto-vj-01 side (e.g. arming the grand-finale
sequence off `final_peak_in_s` instead of a guess) is not part of this
change — the bus exists, nothing reads it yet. That is the next natural
piece, symmetric to how §6.b's `next_role`/`bars_to_next` sat unread on
the section bus until today.

**Verified:** new `tests/test_session_bus.py` (mirrors
`test_section_bus.py`'s coverage exactly: publish/get round-trip, deep-copy
isolation both directions, missing-source/non-dict/unrecognized-phase/
missing-phase all dropped silently, freshest-source-wins, stale-hint
expiry, all four canonical phases accepted) and two new `VjApi`-level
tests in `tests/test_vj_api_postfx.py`. Full suite green.

### Grand-Finale Trigger Consumes the Set-Clock Hint (2026-08-06)

Decision: `_check_timed_finale()` in `auto-vj-01` now reads
`vj_api.get_session()` (the bus above) via a new `_get_session_hint()`
helper, mirroring `_get_section_hint()`'s defensive pattern exactly
(`getattr` + `callable()` + `try/except`, degrades to `None` on an older
core, a missing/unavailable mixer, or any lookup error). This closes the
consumer side that the previous entry explicitly left open.

**Two-tier preference, falling back to the original wall-clock estimate.**
In order:

1. `final_peak_in_s` — the analysed final track's biggest drop, counted
   from now. Fires `trigger_grand_finale()` when this drops to or below
   a new `_finale_peak_lead_s` (default **43.0s**). That default is not
   arbitrary: it is grand-finale-01's own documented buildup length
   (INTRO 8s + BUILD 20s + PEAK 15s = 43s) up to its own climax, the DROP
   phase. Firing this many seconds *before* the mixer's analysed peak
   lands the finale sequence's visual climax right as the music's actual
   drop hits, instead of firing on the drop directly and lagging behind
   it by a full buildup. The constant is a locally-configured value
   copied from grand-finale-01's docstring rather than an import or
   attribute reach into that drop-in — see Drop-In Independence Rules.
2. `seconds_left` — the mixer's own best estimate of when the *set* ends
   (real playlist/clock, not a local guess). Used when peak timing isn't
   available yet (last track not reached, or not analysed), compared
   against the existing `_finale_lead_s` (default 45.0, unchanged).
3. `state.session_remaining_s` — the original wall-clock path (config
   `show_duration_min`/`show_duration_s`), unchanged, used only when no
   mixer hint exists at all (bare stream, or mixer drop-in absent).

Downbeat-quantized firing (`_grid.schedule_for_next_downbeat()` when a BPM
lock exists, else immediate) is unchanged from the pre-existing mechanism.

**Verified:** new `tests/test_auto_vj_timed_finale.py` — peak-timing fires
within/outside its lead window, peak timing takes priority over
`seconds_left` when both are present, `seconds_left` fires
within/outside its own lead window, wall-clock fallback fires/doesn't/
handles `None`, already-fired and auto-trigger-disabled are no-ops,
`trigger_grand_finale()` returning falsy still one-shots without raising,
downbeat-scheduled vs. immediate-fire branching. Full suite green (1282
passed).

### ACF Confidence Excludes Harmonically-Related Rivals (2026-08-07)

Decision: `BeatTracker._acf_rival_score()` (new, `beat_grid.py`) excludes
lags that are near-integer multiples/divisors of the winning lag (2x, 3x,
4x, or their reciprocals, within new `_V2_HARMONIC_CONF_TOL = 0.04`) when
finding the rival used for the ACF peak-ratio confidence
(`acf_peak_ratio = score[peak] / rival_score`, feeding `acf_conf` and the
0.4/0.6 ACF/phase confidence blend).

**Why.** Owner observation during a live training session: a house track
with very solid, mechanically regular kick timing scored confidence
"crazy low" the entire way through, despite the tempo lock itself being
correct throughout (confirmed by the eventual profile recommendation
also landing correctly). The old metric compared the winning lag's score
against whatever the second-highest score anywhere in the array happened
to be. The comb-filter harmonic summing above it (see "Comb-filter
harmonics" in `docs/weights-and-thresholds.md`) deliberately makes a lag
score highly when it's a harmonic multiple/divisor of a genuinely strong
periodicity -- and the *more* mechanically regular the underlying pulse
(a tight four-on-the-floor kick being close to the ideal case), the
*closer* those harmonic-lag scores sit to the fundamental's, since
there's no timing slop to separate them. The metric was therefore
systematically worst exactly when the beat was most unambiguous -- an
inverted signal, not noise.

**Fix, not a threshold nudge.** A rival is only allowed to suppress
confidence if it is *not* harmonically related to the winning lag --
i.e. it reflects an independently periodic, genuinely competing tempo
interpretation, not the comb filter agreeing with its own summed
harmonics. Verified against both directions: a synthetic peak with
strong harmonic-multiple rivals at 2x/3x/4x now reports confidence
identical to having no rival at all (`tests/test_beat_tracker_v2.py::
test_acf_rival_score_excludes_harmonic_multiples_of_the_winning_lag`); a
synthetic peak with a strong *unrelated* rival still suppresses
confidence exactly as before (`test_acf_rival_score_still_penalizes_a_
genuinely_unrelated_rival`).

**Scope.** `_estimate_tempo_acf()` and the new `_acf_rival_score()` are
defined once on `BeatTracker` (v2) and inherited unmodified by
`BeatTrackerV3` (v3 subclasses v2 rather than forking it), so this
applies to both configured engines with no separate v3 change needed.
`BeatGridTracker` (v1, legacy fallback) uses an unrelated
IOI-clustering confidence model with no equivalent peak-ratio step and
is unaffected -- consistent with how the 2026-08-06 primed-confidence
fix was also scoped to v2/v3 only.

`_VJ_WEIGHTS_DOC_VERSION` bumped to 8; see
`docs/weights-and-thresholds.md`'s Detector table and Changelog.

**Verified:** new unit coverage in `tests/test_beat_tracker_v2.py`
(`_acf_rival_score` excludes harmonic multiples, still penalizes a
genuine unrelated rival, falls back to the score floor with no rivals or
an invalid `best_bpm`) plus the existing
`test_acf_confidence_reaches_near_maximum_on_unambiguous_signal`
regression, which continues to pass. Full suite green (1286 passed).

### Profile Recommendation Now Also Reaches the Sequence Corpus (2026-08-07)

Decision: `_update_profile_recommendation()` now calls
`_record_sequence_keyframe('profile_recommendation', ...)` in addition to
its existing `self._engine.mark('profile_recommendation', ...)` decision-log
call, carrying the same fields (`recommended_profile_key`, `score_margin`,
`mean_confidence`, `mean_zcr`, `mean_centroid`, `onset_density`,
`term_spread`, etc.).

**Why.** `package_training_set.py`'s `_build_recommender_payload` filters
the *sequence corpus* (not the decision log) for `event_type ==
'profile_recommendation'` to build its spectral-features summary for the
LLM tuning prompt. That event type was never written there — only to the
decision log — so the section was always empty, silently, for every
session ever packaged. Confirmed against a live 18.5MB same-day corpus
file: zero matching rows, vs. 377 in the decision log over the same
window.

`_update_profile_recommendation()`'s signature gained `state`/`spotify`
parameters (previously just `audio`) to make the keyframe call possible;
the call site (`auto_vj.py`, the main per-frame update path) already had
both in scope.

**Verified:** new `tests/test_auto_vj_recommender_corpus_routing.py` --
a keyframe is written with `event_type == 'profile_recommendation'`,
carries the same spectral-fit fields as the decision-log event bit-for-bit,
and is a no-op when the recommender is disabled. Existing tests in
`tests/test_bpm_detector_audit_regressions.py` updated for the new
signature (stubbed `_record_sequence_keyframe` as a no-op, matching the
existing `_maybe_apply_recommended_audio_profile` stub pattern in the same
file).

### Recommender Weight Table Now Reads Live From `auto_vj.py` (2026-08-07)

Decision: `package_training_set.py`'s `_RECO_WEIGHT_DEFAULTS` (a hand-copied
snapshot of `auto_vj.py`'s `_DEFAULT_RECO_WEIGHTS`, used to render the LLM
tuning prompt's weight-distribution text) is now only a fallback. A new
`_load_live_reco_weights()` reads the real dict straight from
`auto_vj.py` at prompt-build time (mirrors `_load_profile_expected_values()`'s
existing "stop hand-copying a snapshot" fix for the profile roster, same
file, same day discovered).

**Why.** The snapshot had already drifted twice, silently: `centroid_fit`'s
0.8 → 1.3 raise (2026-08-06) was never mirrored here, and the
`vocal_hnr_fit`/`vocal_fmr_fit` terms added the same day were absent
entirely. Every LLM tuning report generated in between reasoned about the
wrong weights with no way to notice. Found during an owner-requested audit
of "everywhere the recommender's output has any downstream effect."

**Verified:** `test_load_live_reco_weights_matches_live_auto_vj_defaults`
asserts the live-loaded dict equals `auto_vj.py`'s real
`_DEFAULT_RECO_WEIGHTS` exactly (structural drift is no longer possible
once this passes); `test_load_live_reco_weights_returns_none_when_auto_vj_
absent` covers the fallback contract when the drop-in isn't present in the
checkout.

### Tier 2: Genre-Tag Ground-Truth Accuracy Tracking (2026-08-07)

Decision: implements Tier 2 of
`docs/planning/auto-vj-recommender-accuracy-tracking-2026-08-06.md` --
the ID3 `GENRE` tag becomes a real accuracy ground truth for the profile
recommender, closing the gap Tier 1 (signal-activity spread) explicitly
left open: "is this term discriminating" is not the same question as "was
the recommendation actually right."

**Data path (new).** dj-mixer-01's `now_playing_snapshot()` gains a
`genre` key, read via `tags.py`'s `read_tags()` on the loaded deck's
`_track_path` (cached by path, refreshed only on track change --
matches the existing `title`/`artist` change-detection cadence, not
read per frame). `unicornviz/now_playing.py`'s snapshot contract
documents `genre` as the newest optional key (every key in that contract
has always been optional; no other source currently populates it).
`auto_vj.py`'s `_build_live_training_row()` reads `spotify.get('genre')`
and logs it as `track_genre` on every live-corpus and sequence-corpus row
(live and sequence, heartbeat and keyframe alike, since all three paths
funnel through the same builder) -- empty string for any source that
doesn't provide it (Spotify's genre/audio-features endpoints are
deprecated and return nothing; media-01 has no tag reader).

**Mapping (new, `package_training_set.py`).** A free-text ID3 tag doesn't
map 1:1 onto the 20 `PROFILES` keys, so genre → profile-key resolution is
two-pass, per the owner's 2026-08-06 design:

1. **Exact/alias match** (`_GENRE_ALIAS_MAP`) against a curated table
   covering every profile's own name plus common ID3 spelling variants
   ("Psy-Trance" vs "Psytrance", "2-Step" vs "UK Garage").
2. **Keyword fallback** (`_GENRE_KEYWORD_MAP`), matched as a *suffix* of
   the tag's last word (not exact-word, so a compound tag like
   "Vaporwave" still catches `wave` the same as a spaced one like
   "Tropical House" catches `house`). Deliberately narrow: a keyword that
   could plausibly mean more than one profile (e.g. `step` -- dubstep and
   chillstep both end in it and are already exact-matched in pass 1) is
   left out rather than guessed.
3. **Unmapped** if neither pass hits -- counted and reported explicitly
   (`unmapped_rows` in the scorecard section), never silently dropped or
   guessed, per the owner's point 2 in the spec.

Like the recommender's own weights, this table is a first-cut meant to be
refined against real tagged-library mileage, not a closed spec.

**Rollup (new, `package_training_set.py`, `_write_scorecard`).** A new
`## Recommender Accuracy` section: tagged-row count vs. total (so a low
accuracy sample size is never mistaken for a low accuracy score, per the
owner's point 2), unmapped count, hit/miss accuracy percentage over usable
rows (tagged + mapped + a recommendation present that cycle), and the top
genre/expected/recommended confusions.

**Explicitly deferred (per the spec's own non-goals, unchanged by this
work).** Tag genre is *not* fed into the live `_profile_score()` composite
in this pass -- Tier 2 is an offline/packaging-time measurement only. The
owner has signaled a live-feedback version is a real future direction
(point 4 in the spec), but that needs its own design pass once this
offline measurement has real mileage on it.

**Verified:** `drop-ins/dj-mixer-01/tests/test_controller.py` --
`now_playing_snapshot()` reads and caches genre via the tag reader, keyed
by path, not re-read on repeat calls for the same track, empty without a
track path. `tests/test_auto_vj_live_training.py` -- `track_genre` flows
through `_build_live_training_row()`, defaults to `''` when the source
omits it. `tests/test_package_training_set.py` -- exact/alias matches,
keyword-fallback matches (including the compound-word suffix case),
unmapped returns `None`, hit/miss/unmapped counting, confusion-entry
shape, and the rendered scorecard section. Full main-repo suite green
(1327 passed); dj-mixer-01's own suite green (878 passed, 1 skipped).

### Effect Ping-Pong Hard-Cuts Between Two Pinned Instances (2026-08-07)

Decision: new core capability, `App.pin_effect_pair()` / `cut_to_pinned()`
/ `unpin_effect_pair()` (`unicornviz/app.py`), exposed via
`VjApi.pin_effect_pair()` / `cut_to_pinned_effect()` / `unpin_effect_pair()`
(`unicornviz/vj_api.py`). Effect ping-pong's `'effect'` kind (auto-vj-01,
`_enter_pingpong()`/`_run_pingpong_swap()`/`_exit_pingpong()`) now uses
this instead of `goto_effect()` for every swap.

**Why.** `_switch_effect()` (`app.py`) always pays a full instantiate +
destroy on every effect swap — correct for a normal transition between two
different effects, but ping-pong alternates between the *same two* effects
for its whole run, re-paying that cost (shader compile included) on every
single beat-threshold swap. Owner's framing: "that's the real fix... both
could stay instantiated and it could cut between them, turning a shader
compile + destroy into a pointer swap. That kills the cost entirely rather
than rationing it" — i.e. this isn't a threshold/budget tune, it's removing
the cost's root cause.

**Design.** `pin_effect_pair(cls_a, cls_b)` instantiates both once and
holds them in `App._pinned_pair` (a `{'a': ..., 'b': ...}` dict); returns
`False` (no-op) if a pair is already pinned, the ProjectM manager modal is
open, or either class fails to instantiate (in which case the other, if
already constructed, is destroyed immediately rather than leaked).
`cut_to_pinned(which)` is a pure pointer assignment — `self._current_effect
= pair[which]`, `self._next_effect = None`, no instantiate, no destroy, no
transition blend. `unpin_effect_pair()` destroys whichever pinned instance
isn't the one currently on screen; the on-screen one is left alive and
destroyed later the normal way, once a subsequent real transition
completes past it.

**Defensive unpin in `_switch_effect()`.** A pinned pair can be
interrupted by something other than auto-vj-01 itself — a manual "next
effect" hotkey mid-ping-pong-run, for instance. Without a guard, the
off-screen pinned instance would never get destroyed (only
`_exit_pingpong()` used to call `unpin_effect_pair()`), leaking its GL
resources for the rest of the session. `_switch_effect()` now checks
`self._pinned_pair` first and releases it before proceeding, so *any* path
into a normal transition cleans up a stale pin, not just the one
auto-vj-01 itself expects.

**Self-healing on the auto-vj-01 side.** Since the pin can now be released
out from under a running ping-pong loop by that same interruption,
`_run_pingpong_swap()` checks `cut_to_pinned_effect()`'s return value: a
`False` (pair gone) clears `self._pp_pinned` and falls back to
`goto_effect()` for the remainder of that run, rather than silently
freezing on whatever effect the interruption left on screen. `pinned` is
now logged on every `effect_swap` event so a session's ping-pong runs can
be told apart from a stale/degraded fallback run after the fact.

**Scope.** Only the `'effect'` kind of ping-pong is affected. The
`'preset'` kind (ProjectM preset-index alternation) was already cheap —
swapping a preset index, no GL instantiate/destroy involved — and is
untouched.

**Verified:** `tests/test_app_effect_pinning.py` (App-level mechanics:
pin/cut/unpin, refusal when already pinned or ProjectM modal is open,
partial-failure cleanup, transition-state clearing on cut),
`tests/test_vj_api_effect_pinning.py` (name/class resolution through the
`VjApi` wrapper layer), `tests/test_auto_vj_pingpong_pinning.py`
(auto-vj-01's enter/swap/exit wiring, the goto_effect fallback when
pinning fails, the preset-kind path being untouched, and the self-heal
path when a cut fails mid-run), and a new case in
`tests/test_effect_crash_isolation.py` confirming `_switch_effect()`
releases a pinned pair left behind by an external interruption. Full
suite green (1352 passed).

### Headless Training: dj-mixer-01/media-01 as Audio Sources (2026-08-07)

Decision: `tools/training_daemon.py` (training-kit-01) gains
`--source {spotify,dj-mixer,media}` so an unattended Auto VJ training
session can be driven by dj-mixer-01's real DJ engine or media-01's local
library, not only Spotify. New core CLI flags on `unicornviz/__main__.py`
(`--dj-mixer-source`, `--dj-mixer-autoplay-mode`, `--dj-mixer-music-dir`,
`--dj-mixer-output-device`, `--media-source`, `--media-dir`) force-enable
and configure the chosen subsystem for a single run via the existing
`Config(overrides=...)` mechanism (`unicornviz/config.py:376-384`) --
the same shape already used for `--record`/`--no-record` ->
`[recording] auto_record`.

**Why.** Spotify needs a human to connect from their phone and press
play, so a Spotify-sourced session isn't truly unattended at boot. It
also has no genre signal (the API is gone), so it can never feed Tier 2
of the recommender accuracy-tracking spec. dj-mixer-01 already populates
`now_playing_snapshot()`'s `genre` key (shipped the same day, from the
loaded track's ID3 tag) which auto-vj-01 logs as `track_genre` on every
corpus row -- so a dj-mixer-01-sourced session gets real Tier 2 ground
truth "for free," something Spotify structurally cannot provide.

**Design goal, per explicit owner direction: no static config.toml
pre-editing.** `--source dj-mixer`/`--source media` on the daemon must
force-enable everything needed for that run via CLI flags -- if the
subsystem "exists but isn't enabled, enable it for the run" -- without
writing to the training deploy's saved config file, so switching
`--source` between runs never requires editing it.

**dj-mixer-01** (`_maybe_boot_autoplay()`, new): arms AutoPlay
(`autoload`/`cut`/`crossfade`/`smart`) from a cold board, gated by new
`[dj_mixer] autoplay_boot_mode`/`autoplay_boot_shuffle` config keys and
distinct from `_restore_state()`'s saved-mode restore (a real DJ's last
live toggle) -- never fires if a restored session already armed a mode.
Verified directly: `Browser.mode` defaults to `'library'`
(`browser.py:80`), so `AutoPlay.set_mode()`'s own `_bind_list()` call
binds to the whole configured `music_dir` automatically -- a single
`set_mode()` call is genuinely enough to bootstrap playback from a cold
board, no separate track-load call needed. `output_device` (routed via
`--dj-mixer-output-device`, defaulting to the same value as
`--audio-device`) points PortAudio/sounddevice directly at the training
null sink.

**media-01**: new `[media] auto_play` config key; `play_pause()` already
falls through to starting track 0 of the shuffled library on a fresh
instance, so no other change was needed inside `MediaController`. New
`App._maybe_auto_play_media()` boot trigger mirrors the RTMP streamer's
existing `auto_start` pattern. VLC hardcodes `--aout=pulse` with no
per-instance output-device argument, so routing to the training null sink
needs `PULSE_SINK` set on the whole `unicorn-viz` process -- the daemon
sets it only for `--source media` (the same mechanism the daemon's own
Spotify-GUI fallback already uses on its own process).

**Daemon validation.** `--source dj-mixer`/`--source media` requires
`--playlist-name` (neither source has Spotify's playlist-detection
mechanism) and `--source-dir` (the track library), checked at
argparse-time before any infrastructure is created -- a from-scratch run
with neither would otherwise waste an entire unattended session before
failing at packaging time.

**Verified:** `tests/test_main_headless_source_overrides.py`
(`_build_overrides()` produces the right `[dj_mixer]`/`[media]` keys, the
output-device default-to-`--audio-device` fallback, absence when neither
flag is passed), `tests/test_app_media_auto_play.py`
(`_maybe_auto_play_media()` unbound against a stub), new cases in
`drop-ins/media-01/tests/test_auto_play_config.py` and
`drop-ins/dj-mixer-01/tests/test_controller.py` (`_maybe_boot_autoplay()`
arms a mode and eventually plays via a real tick loop, no-ops without a
mode configured, never stomps a restored session mode, rejects an invalid
mode, shuffle default/override), and `tests/test_training_daemon.py`
(argparse-time validation, `PULSE_SINK`/env construction, the
`--dj-mixer-source`/`--media-source` command-line pass-through) --
pure-function tests, no subprocess/pactl/Xvfb/SDL needed. Full main-repo
suite green (1376 passed); dj-mixer-01 (895 passed, 1 skipped) and
media-01 (54 passed) own suites green.

### Auto-Exit on Set End: the Grand-Finale Completion Watcher (2026-08-07)

Decision: closes `docs/planning/headless-auto-exit-plan-2026-08-07.md`'s
last section. New `VjApi.grand_finale_active` property (`vj_api.py`)
exposes `GrandFinale.is_active`'s True→False completion edge without a
caller reaching into `app._grand_finale` directly. New
`AutoVJController._maybe_exit_after_finale()` (`auto_vj.py`), ticked
alongside `_check_timed_finale()`, watches that edge and calls
`vj_api.request_exit(force=True)` once the *timed* finale trigger has
fired and the sequence it triggered has actually finished.

**Why the finale-trigger half needed no change.** dj-mixer-01 (`AutoPlay.
on_night_over`, loop now defaults `False`) and media-01 (`repeat`
defaulting `off`) both now publish `phase: 'over'`, `seconds_left: 0.0` on
the session bus when their playlist naturally ends — deliberately the
exact same shape `SessionClock` already publishes when its timer runs
out. `_check_timed_finale()` (shipped 2026-08-06) already treats
`seconds_left` below its lead-time gate as "fire now" regardless of why
it's low, so a `0.0` from either drop-in already fires the finale with
zero auto-vj-01 changes -- confirmed by tracing the existing gate logic
rather than assumed.

**The grace window.** `_maybe_exit_after_finale()` only exits immediately
on the True→False edge if it actually observed `grand_finale_active` go
`True` first. If the timed trigger fired but the finale never becomes
active within `_EXIT_AFTER_FINALE_GRACE_S` (20.0s -- covers `schedule_
for_next_downbeat()`'s worst-case wait, plus margin) -- grand-finale-01
missing, or `trigger_grand_finale()` failing -- it exits anyway. An
unattended run's entire point is ending in a packaged recording; hanging
forever waiting for a completion edge that will never arrive would defeat
that as badly as never exiting at all.

**Explicit opt-in, narrowly scoped.** `[auto_vj] auto_exit_after_finale`
defaults `false`. Even when on, the watcher only ever arms behind
`self._timed_finale_fired` -- a manual `Ctrl+Alt+F` finale during a normal
live set does not set that flag, so it can never trigger an unexpected
exit mid-show.

**Same-day follow-up: automatic for headless sources.** `_build_overrides()`
(`unicornviz/__main__.py`) now sets `auto_exit_after_finale = true`
automatically whenever `--dj-mixer-source` or `--media-source` is passed --
a headless source *is* a headless run, by definition nobody is at the
keyboard to press `Q`, so there is no scenario where an operator would want
one without the other. No separate flag or `config.toml` edit needed for
either headless CLI path; the config key still exists for anyone driving
`unicornviz` directly without a source flag (e.g. a Spotify session with a
configured `show_duration_min`).

**Verified:** `tests/test_auto_vj_exit_after_finale.py` (disabled-flag
no-op, manual-trigger no-op, the active→inactive exit edge, staying
active never exits, exits only once, the grace-window timeout path via a
monkeypatched `time.monotonic`, and becoming active before the grace
deadline cancels the timeout path) and `tests/test_vj_api_grand_finale_
active.py` (`grand_finale_active` against a real `App`: `None` drop-in,
`is_active` `True`/`False`, and a stub with no `is_active` attribute at
all degrading to `False` rather than raising). Full main-repo suite green
(1408 passed).

### `centroid_fit` Weight Trimmed 1.3 → 1.0 (2026-08-07)

Decision: `centroid_fit` trimmed again, `1.3` to `1.0` (owner: "i think
it's still pulling us off the bpm too easily"). Unlike the 1.5 → 1.3 trim
above, this one *is* prompted by a live-session finding: a confident
spectral-brightness match kept outvoting a real tempo mismatch in the
composite score. `centroid_fit` is now equal to `spectral_shape_fit`
rather than above it, still above `zcr_fit`/`onset_fit`, and stays below
`tempo_fit` (`2.0`) — tempo is the sharper, per-profile-sigma-driven
signal and should not lose ties to timbre. `_VJ_WEIGHTS_DOC_VERSION`
bumped to 9. Full weight history: `0.8` (original) → `1.5` (2026-08-06)
→ `1.3` (2026-08-06) → `1.0` (2026-08-07).

**Verified:** full main-repo suite green (1507 passed), including
`tests/test_bpm_detector_audit_regressions.py::test_recommender_prefers_
deep_house_over_psytrance_at_120_bpm` (reads `_DEFAULT_RECO_WEIGHTS`
live, so exercises the new weight directly) and `::test_centroid_fit_
uses_per_profile_sigma_not_fixed_400` (weight-agnostic by construction —
isolates `spectral_centroid_sigma` with all else held equal). `ruff
check`/`bandit` on `auto_vj.py` show only pre-existing findings outside
this diff's hunks.

### `top_cand_fit` Fixed; Per-Candidate Term Logging Added (2026-08-09)

Context: chasing the `centroid_fit` trim above, the owner asked for a real
0-100% accuracy score per recommender term computed from historical
training data. Digging into it surfaced two independent problems, both
found by reading `_profile_score()` directly rather than by guessing from
symptoms.

**`top_cand_fit` was structurally always `0.0`.** The term is meant to be
the best (least-negative) Gaussian log-density among the ACF's raw top-3
tempo candidates. It was implemented as `top_cand_fit = 0.0` then combined
via `max(top_cand_fit, -0.5*x*x)` inside the candidate loop — since every
real candidate's value is `<= 0`, the `0.0` initializer always won,
regardless of how good or bad the candidates actually were. Confirmed
empirically before touching the code: 0 nonzero values across 803 logged
`profile_recommendation` rows spanning two independent dj-mixer sessions,
and 0 nonzero in every sampled decision-log row too. Its `0.4` weight has
contributed nothing to any recommendation, ever, since it shipped. Fixed
by flooring at the worst real candidate instead of `0.0`, falling back to
`0.0` only in the genuine no-candidates-and-no-fresh-mixer-hint case.
`_VJ_WEIGHTS_DOC_VERSION` bumped to 10.

**Real per-term accuracy was structurally impossible to compute.** The
same historical-data dig found that `term_spread` (max-min across
candidates per eval cycle, added earlier for Tier 1 signal-activity
tracking) can only show a term was *discriminating* that cycle — not
whether its value favored the *correct* candidate. There was no way to
answer "did `centroid_fit` actually push toward the genre-tag-confirmed
right answer, or just toward whatever won anyway" from the data logged.
New `term_values_by_candidate` field (`{profile_key: {term: value}}` for
every enabled candidate, `lock_rate`/`mean_conf`/`mean_dconf` excluded
since they're identical for every candidate — see the entry below) on
both the decision-log and sequence-corpus `profile_recommendation` events
makes that computable once training-kit-01 cross-references it against a
genre tag.

**Separately investigated, not fixed:** `vocal_hnr_fit`/`vocal_fmr_fit`
were found to be frozen constants in every session checked (`mean_vocal_
hnr`/`mean_vocal_fmr` read exactly `0.0` on all 803 rows, so the fit terms
come out to the same number regardless of what's playing) despite
`analyzer.py`'s `_compute_vocal_hnr`/`_compute_vocal_fmr` being genuine,
non-stub implementations. A quick read of the analyzer's wiring (spectrum
slicing, gating on `energy > 1e-5`) didn't turn up an obvious cause —
this needs a live/replay debug session to pin down, not a guess. Left
alone pending that investigation.

**Verified:** full main-repo suite green (1526 passed), including four new
regression tests in `tests/test_bpm_detector_audit_regressions.py`:
`test_top_cand_fit_reflects_real_candidate_fit_not_floored_at_zero`,
`test_top_cand_fit_zero_only_when_no_candidates_at_all`,
`test_term_values_by_candidate_excludes_non_discriminating_terms`, and
`test_term_values_by_candidate_reaches_sequence_corpus_too`. `ruff
check`/`bandit` on `auto_vj.py` show only pre-existing findings outside
this diff's hunks.

**Update, same day:** the "separately investigated, not fixed" vocal_hnr/
vocal_fmr note above was resolved a few hours later — see "Vocal-Presence
Core Bug: `AudioManager._copy_audio_into()` Never Copied `vocal_hnr`/
`vocal_fmr`" below. Root cause was in core (`unicornviz/audio/manager.py`),
not in the analyzer or the recommender as originally suspected.

---

## Subsystem Versioning: Detector / Director / Recommender Get Independent Semver (2026-08-09)

Decision: `beat_grid.py` gains `_DETECTOR_VERSION`, `auto_vj.py` gains
`_DIRECTOR_VERSION` and `_RECOMMENDER_VERSION` — each subsystem's own
SemVer, independent of both `auto_vj.py`'s drop-in-wide `__version__` (a
release counter for the whole package) and `_VJ_WEIGHTS_DOC_VERSION` (a
doc-freshness counter for `weights-and-thresholds.md`, shared across all
three subsystems). A subsystem version answers a narrower question: what
behavioral state is *this specific subsystem* in, independent of what else
shipped in the same drop-in release.

**Why now.** The day's work (below) touches all three subsystems'
mechanisms unevenly — the recommender gets a structural rewire, the
detector and director get nothing this time. A single drop-in-wide version
number (`1.0.0-rc.NN`) can't express "the recommender changed meaningfully,
the detector and director didn't" — every rc bump reads as "something
changed somewhere," which is true but not useful for answering "is my
mental model of the *recommender specifically* still accurate." Owner:
"we should really be semver'ing detector/recommender/director each
independently and consistently, add agent rules for that and source
comments near their origin points."

**Why not fold into `_VJ_WEIGHTS_DOC_VERSION`.** That counter already
exists and already tracks all three subsystems, but it's a doc-freshness
signal ("has the reference doc been updated to match the code"), not a
behavioral-state signal ("what does this subsystem currently do"). Both
are useful, for different questions, so both stay. See CLAUDE.md
"Subsystem Versioning (Auto VJ: Detector / Director / Recommender)" for
the full bump discipline and `weights-and-thresholds.md`'s header (which
now echoes all four numbers) for where they surface.

**Starting values.** All three start at `0.1.0` — pre-1.0 alpha, per the
project's existing "everything starts at `0.x` until first feature-
complete, validated release" rule (CLAUDE.md "Versioning & Release
Standards"). It would be inconsistent for an internal subsystem to
leapfrog past the parent drop-in's own maturity level (`auto-vj-01` itself
is still `1.0.0-rc.27`, not yet `1.0.0`). `_RECOMMENDER_VERSION` moves
immediately to `0.2.0` in the same commit as the top-3-weights rewire
below — `0.1.0` is a baseline snapshot of "state as of rc.27," not a
release that ever shipped on its own.

**Verified:** no runtime behavior depends on these constants (documentation
and versioning-discipline only); full suite unaffected.

---

## Top-3-Weights Rewire: `detector_trust` Replaces the Dead Composite Terms (2026-08-09)

Decision: `lock_rate`/`mean_conf`/`mean_dconf` removed from
`_DEFAULT_RECO_WEIGHTS` and `_profile_score()`'s composite entirely. New
`detector_trust` (a blend of `lock_rate`/`mean_dconf`, using their old
composite weights `2.5`/`1.2` as blend ratios) scales the confirmation
margin and gates the decider. `_RECOMMENDER_VERSION` bumped to `0.2.0`.

**The problem, proven not assumed.** Digging into per-term accuracy
(triggered by the `centroid_fit` trim earlier the same day) found that
`lock_rate`/`mean_conf`/`mean_dconf` are computed once per eval cycle from
the sample window, not per candidate profile — every candidate gets the
identical value. In a weighted-sum composite, an identical constant added
to every candidate cancels out of the ranking (`argmax` is unaffected by a
uniform shift), the softmax margin (`best_prob - current_prob` — the
constant appears in both `_profile_score()` calls that feed each
probability and cancels in the subtraction), and the confirmation decision
(gated on that same margin). Verified directly in `_maybe_apply_
recommended_audio_profile`'s and `_update_profile_recommendation`'s
softmax-normalization code, not inferred from behavior. Despite this,
these three terms carried the *highest* weights in the whole table (`2.5`,
`1.8`, `1.2` — all above `tempo_fit`'s `2.0`), meaning roughly 30% of the
visible "weight budget" was doing nothing for recommendation accuracy.

**The philosophical question, and the owner's answer.** Asked directly why
a construct this inert would have been left in place, and what it was
plausibly reaching for: "it was probably intended to keep the recommender
from jumping around back when we didn't have such robust data and improved
accuracy... and to allow it to switch immediately when confidence in
another genre jumps confidently ahead of the current without
flip-flopping." That reading fits the evidence: these three terms are the
*only* ones in the composite that measure the tracker's own health
(is it locked, how confident is the lock, how confident is downbeat phase)
rather than how well a candidate genre fits the audio — a natural
instinct is "don't trust a recommendation much when the detector itself
isn't confident." The mechanism chosen to express that instinct (an
additive term in a comparative ranking) was simply the wrong shape for the
job — a uniform trust signal needs to scale a *threshold*, not get added
to every candidate's *score*.

**The mechanism that actually does the job.** `detector_trust` (defined in
`_update_profile_recommendation`, module constant `_TRUST_BLEND_WEIGHTS =
{'lock_rate': 2.5, 'mean_dconf': 1.2}` in `auto_vj.py`) now:

1. Scales the confirmation margin: `effective_margin =
   profile_auto_reco_score_margin / max(detector_trust, _TRUST_FLOOR)`.
   At `detector_trust = 1.0` this is exactly the configured threshold
   (today's behavior, unchanged). A shaky lock/downbeat-phase reading
   demands a bigger margin before confirming — implements "resist
   jumping around on weak evidence."
2. Gates both the normal and fast-override decider paths on
   `detector_trust >= _TRUST_FLOOR` (`0.15`) before either path's own
   gates run — a decisive-looking score gap is not itself evidence of
   anything if the detector barely had a lock this cycle.

`mean_conf` is deliberately *not* part of the `detector_trust` blend: it
already had a real, working role independent of the composite
(`profile_auto_reco_decider_min_confidence`, checked in the normal
decider path) — folding it into the blend too would have double-counted
it. `lock_rate`/`mean_dconf` had no such role before this change; they now
do.

**A necessary side effect: fast-override migrated to probability
thresholds.** `_maybe_apply_recommended_audio_profile`'s fast-override
path (`profile_auto_reco_decider_force_recommended_score`/`..._force_
current_score_cap`) compared raw composite scores against fixed absolute
thresholds (`2.25`/`1.80`). Removing the three terms shifts every
candidate's raw composite score down by whatever they used to contribute
— a session-dependent amount, not a fixed offset — which would have
silently broken those fixed thresholds (the fast-override path would have
gone from "rarely used, works" to "practically dead" without ever
raising an error). Migrated to the softmax probability the normal path
already uses for exactly this reason (see the softmax-normalize comment
in `_update_profile_recommendation`: "a single fixed additive threshold
mean very different things across genres" — the same argument applies
here, just discovered a day later). Renamed `..._force_recommended_prob`
(`0.55`) / `..._force_current_prob_cap` (`0.05`); confirmed no
`config.toml` in the wild set the old keys, so no migration shim was
needed.

**Verified:** full main-repo suite green, including new tests in
`tests/test_bpm_detector_audit_regressions.py`:
`test_lock_rate_mean_conf_mean_dconf_not_in_default_weights`,
`test_low_detector_trust_requires_bigger_margin_to_confirm`,
`test_high_detector_trust_confirms_at_configured_margin` (both calibrated
against a real house/deep_house contest, not a synthetic score — margin
held constant at `0.4238` while only `detector_trust` varies, confirming
the effect is attributable to the scaling formula, not incidental score
noise), `test_detector_trust_logged_on_profile_recommendation_event`,
`test_recommender_decider_blocked_when_detector_trust_below_floor`, and
updated fast-override tests (`test_fast_override_applies_despite_
unconfirmed_recommendation`, `test_fast_override_does_not_fire_when_
current_prob_not_capped`, `test_fast_override_uses_shorter_cooldown_than_
normal_path`) now exercising probability thresholds instead of raw
scores.

---

## Per-Profile `zcr_sigma`/`onset_density_sigma` (2026-08-09)

Decision: `zcr_fit`/`onset_fit` gain the same per-profile-sigma mechanism
`tempo_fit`/`centroid_fit` already had (`zcr_sigma`, `onset_density_sigma`
on `AudioProfile`, three coarse tight/medium/wide tiers: `0.015`/`0.020`/
`0.028` for zcr, `0.7`/`1.0`/`1.5` for onset). Owner: "let's do the
research and give each profile proper sigmas for each appropriate
weight."

**Research basis.** Unlike `spectral_centroid_sigma`'s original tiers
(assigned by genre feel alone, 2026-08-06), these were researched against
genre-production convention for all 20 profiles plus the one genre-tagged,
scorecard-validated training bucket available (`training-house-01`,
house-only, 674 samples) — full per-profile rationale in
`weights-and-thresholds.md`'s new zcr/onset sigma table. Directly
validated for `house`: observed onset-density stdev ≈0.197 and zcr stdev
≈0.025 from real session data, both consistent with the proposed values.
Every other profile's tier assignment is domain-knowledge/textual-
grounding based, not measured — same caveat `spectral_centroid_sigma`
already carries.

**Key finding: rhythmic regularity and timbral/tempo spread are
independent properties of a genre.** The research surfaced several
profiles where zcr and onset sigma diverge sharply from what a single
"genre is tightly/loosely defined" intuition would predict. `house` is the
clearest case: its `bpm_prior_sigma` (`0.35`) and `spectral_centroid_sigma`
(`600`) are both already the widest of any profile — deliberately, since
the owner's library spans real production diversity (tropical, afro,
progressive house). A naive "match the existing wide tiers" rule would
have given `house` a wide onset sigma too. But four-on-the-floor kick
timing is mechanically regular *regardless* of production style — a
tropical house track and a classic house track can sound completely
different (wide zcr/centroid) while both keeping essentially metronomic
kick spacing (tight onset). `house` ships with `zcr_sigma=0.028` (wide)
and `onset_density_sigma=0.7` (tight) specifically to capture this split,
and it's the one profile where real session data confirms both halves of
it independently. `trance` and `hardgroove` show smaller versions of the
same effect in the other direction (onset pulled tighter/looser than
their bpm/centroid tier alone would suggest, based on the profile's own
genre-description language about rhythmic character).

**Mechanism, mirroring `centroid_fit` exactly.** `_profile_score()`'s
`zcr_fit`/`onset_fit` now read `getattr(profile, 'zcr_sigma', 0.020)` /
`getattr(profile, 'onset_density_sigma', 1.0)` instead of the old fixed
`0.020`/`1.2` constants, floored at `0.005`/`0.1` against a misconfigured
near-zero value blowing up the Gaussian (same floor pattern as
`centroid_fit`'s `50.0` Hz floor).

**Verified:** full main-repo suite green, including new tests
`test_zcr_fit_uses_per_profile_sigma_not_fixed_020` and `test_onset_fit_
uses_per_profile_sigma_not_fixed_1_2` in `tests/test_bpm_detector_audit_
regressions.py`, mirroring `test_centroid_fit_uses_per_profile_sigma_not_
fixed_400`'s isolation methodology exactly (two variants of the same
profile, identical `mu`, only the sigma under test differs).

---

## Vocal-Presence Core Bug: `AudioManager._copy_audio_into()` Never Copied `vocal_hnr`/`vocal_fmr` (2026-08-09)

Decision: `unicornviz/audio/manager.py`'s `AudioManager._copy_audio_into()`
gains two missing lines (`target.vocal_hnr = source.vocal_hnr`;
`target.vocal_fmr = source.vocal_fmr`). Owner: "let's put those to work!"
(re: `vocal_hnr_fit`/`vocal_fmr_fit` being frozen constants, found
digging into per-term recommender accuracy earlier the same day).

**Root cause, found by live execution, not static reading.** A first pass
(same day, earlier) read `analyzer.py`'s `_compute_vocal_hnr`/
`_compute_vocal_fmr` and their call site and found nothing obviously
wrong — both are genuine, non-stub implementations. The actual bug was one
layer further out: `AudioManager._copy_audio_into()`, the hand-written
field-by-field copy that hands the analysis thread's `AudioData` snapshot
to the main thread's long-lived published buffers, was written before
`vocal_hnr`/`vocal_fmr` existed on `AudioData` (`__slots__` gained them in
a later commit, `a5b03b2`) and was never updated to include them —
confirmed via `git log -S`, `_copy_audio_into`'s field list was last
touched in an earlier commit (`aa921e2`, the P1 analysis-thread
introduction) that predates `a5b03b2`. The published `AudioData` instances
(`_last_data`/`_last_data_raw`) keep their `AudioData.__init__` default
(`0.0`) for these two fields forever, since the one function responsible
for updating them silently skips both, every frame.

Confirmed with live execution against the real `Analyzer` and
`AudioManager` classes (not a synthetic reproduction of the bug): fed a
real `Analyzer()` a synthetic singing-like signal (8-harmonic tone in the
vocal formant band, 5 Hz syllabic AM modulation) — the analyzer computed
`vocal_hnr=0.6899`, `vocal_fmr=0.6804` correctly, but after
`AudioManager._copy_audio_into()` those values read back as `0.0`,
reproduced deterministically. This is exactly the symptom the historical-
data dig found: `mean_vocal_hnr`/`mean_vocal_fmr` exactly `0.0` on all 803
real `profile_recommendation` rows across two independent dj-mixer
sessions, with `vocal_hnr_fit`/`vocal_fmr_fit` consequently coming out as
frozen constants (`4.205`/`6.2422` on every row) rather than tracking
anything about the actual audio.

**Blast radius wider than the recommender.** `AudioManager.get_audio_
data()`/`get_audio_data_raw()` are the general-purpose audio API every
effect and drop-in reads from, not an auto-vj-01-specific path — any
effect using `audio.vocal_hnr`/`audio.vocal_fmr` for visual reactivity has
been silently reading zero this whole time too, not just the recommender.
Fixed in core, not in auto-vj-01, since the bug lives in the shared
audio-manager boundary.

**Verified:** new tests in `tests/test_audio_manager_startup.py`:
`test_copy_audio_into_copies_every_audiodata_slot` (enumerates every
`AudioData.__slots__` entry dynamically, not just the two dropped here, so
a *future* field added without a matching copy line fails loudly instead
of silently reading a stale default the same way these two did) and
`test_copy_audio_into_copies_vocal_hnr_and_fmr` (narrower, explicit
regression naming the exact symptom). Full main-repo suite green.

---

## Same-Day Second Occurrence: `data.bpm` Never Assigned; a Second Hand-Written Copy List Missing the Same Two Fields (2026-08-09)

Reported by the owner, in another session, the same day as the entry
above: "both are the same family as the vocal_hnr/vocal_fmr bug your other
session just fixed... I'm reporting rather than fixing since neither is
what we're hunting." Confirmed both, then owner: "I think these are uber
critical, please address now."

**Bug 1 — `AudioData.bpm` is dead.** `Analyzer.process()` never assigned
`data.bpm` anywhere in its body. Every `AudioData` snapshot — live or
scratch-buffer — carried the constructor default (`120.0`) forever,
regardless of the real track tempo. Not caught earlier because Auto VJ
(auto-vj-01) never reads `data.bpm` at all; it runs its own independent
`BeatTracker`/`BeatGridTracker` fed directly from raw PCM/onsets, so "real
BPM reaches Auto VJ by another route" and nothing about the app's own
behavior looked wrong. The only consumers actually affected are ordinary
effects reading `audio.bpm` for tempo-synced visuals — silently locked to
120 the whole time, with no error or obviously-wrong-looking symptom to
notice it by.

Root cause, one layer removed from where it first looks: `Analyzer.
set_expected_bpm(bpm, confidence)` — the existing feedback hook Auto VJ
already calls every frame with its own locked BPM (`auto_vj.py:2712`) —
derived `self._refractory_s` from its `bpm` argument but never stored the
value itself anywhere. `process()` had nothing to read even if someone
remembered to assign `data.bpm`. Fix: `Analyzer.__init__` gains
`self._expected_bpm: float = 120.0` (same default as `AudioData.bpm`, so a
cold start / pre-Auto-VJ session is bit-for-bit unchanged from before this
fix); `set_expected_bpm()` now stores `self._expected_bpm = bpm` alongside
the existing `_refractory_s` derivation, sticky across a momentary
confidence dip (mirrors `_refractory_s`'s own existing gate: only updates
when `bpm > 0 and confidence >= 0.5`, otherwise holds); `process()` now
assigns `data.bpm = self._expected_bpm` *before* the silent-frame early
return, so a momentarily silent block doesn't blank the known tempo either
— same stickiness reasoning applied to a second axis.

**Scope note:** this wires up the feedback path that already existed; it
does not add independent BPM detection to core. When Auto VJ is disabled
(the default), nothing calls `set_expected_bpm()`, so `data.bpm` stays at
`120.0` exactly as it always has — there is still no standalone tempo
detector in `unicornviz/audio/` itself. Fixing that would be a materially
larger, separate project; out of scope for this dead-field bug.

**Bug 2 — a second, independent hand-written `AudioData` copy list, same
gap.** `App._fill_audio_scratch()` (`app.py:2490`, called whenever an
effect sets a reactivity override) turned out to have written its own
field-by-field copy — independent of `AudioManager._copy_audio_into()`
above, which had already been through the exact fix documented in the
entry directly above this one on the *same day* — and was still missing
`vocal_hnr`/`vocal_fmr`. Confirms the shape of the risk the first fix's
test comment already named: "a future field added to `AudioData` without a
matching line... fails loudly instead of silently reading a stale default"
— true of the test for `_copy_audio_into`, but there was nothing stopping
a *second*, differently-hand-written list elsewhere from having the same
gap independently, which is exactly what happened.

**Structural fix, not just a second patch.** New `unicornviz.effects.base.
copy_audio_data(source, target, *, scale=1.0)` — the single source of truth
for `AudioData`'s full field list, covering all 16 `__slots__` entries in
one place. `scale != 1.0` additionally clamps the scaled "level" fields
(`bass`/`mid`/`treble`/`fft`) to `[0, 1]`, matching `_fill_audio_scratch`'s
old reactivity-override behavior; every other field is reactivity-invariant
and copied through unscaled regardless of `scale`. Both
`AudioManager._copy_audio_into()` and `App._fill_audio_scratch()` now
delegate to it instead of maintaining their own copies of the list — one
list to keep in sync with `AudioData.__slots__` going forward, not two.

**Verified:** new tests in `tests/test_analyzer_bpm_feedback.py` (defaults
to 120 with no feedback; reflects a confident `set_expected_bpm()` call;
ignores a low-confidence call; stays sticky across a silent frame; updates
correctly on a pre-allocated `out=` buffer, matching real call sites) and
`tests/test_app_audio_scratch.py` (same "enumerate every `AudioData.
__slots__` dynamically" pattern as `test_audio_manager_startup.py`'s
existing test, plus explicit `vocal_hnr`/`vocal_fmr` and reactivity-scale-
boundary regressions). Full main-repo suite green (1590 passed), `ruff`
clean on every touched file.

---

## The Rest of the 16 `AudioData` Slots Reach the Training Corpus + LLM Scoring (2026-08-09)

Direct follow-on to the entry above, same day. Once `data.bpm` and
`vocal_hnr`/`vocal_fmr`'s copy-path bugs were fixed, the owner asked for
the full inventory of what the other 14 non-`fft`/`waveform` slots
actually are and whether they're worth tracking for training: "let's add
all to the training logs, whatever place is appropriate, that is a gold
mine! everything but fft/waveform," followed by "add to llm scoring &
reporting as well please, in/if/as appropriate."

**Corpus capture (auto-vj-01, `_build_live_training_row()`).** Before this
change, per-frame corpus coverage of `AudioData`'s 16 slots was
inconsistent across the three call sites that build a row
(`_record_live_training_row()`, `_record_sequence_heartbeat()`,
`_record_sequence_keyframe()`):

- `bass_flux`/`mid_flux`/`vocal_hnr`/`vocal_fmr` reached **no** per-frame
  corpus row at all (`vocal_hnr`/`vocal_fmr` only reached the much coarser
  `profile_recommendation` event, sampled once per recommender eval cycle
  rather than every heartbeat/keyframe).
- `bass`/`mid`/`treble`/`bass_n`/`mid_n`/`treble_n`/`beat` reached the
  *sequence* corpus only, via a second, independent field list in
  `_sequence_director_fields()` — not the *live* corpus
  (`_record_live_training_row()` never merged that function's output).

All of it now lives in `_build_live_training_row()` itself, the one
function all three call sites already funnel through, so every corpus row
— live and sequence alike — carries the same 14 fields consistently.
`_sequence_director_fields()`'s now-duplicate copy of
`bass`/`mid`/`treble`/`bass_n`/`mid_n`/`treble_n`/`beat`/`spectral_flux`/
`bands`/`kick_regularity` was removed rather than left to drift from the
base row — the same "one list, not two" lesson as `copy_audio_data()` in
the entry above, applied to a different pair of lists the same day.

**LLM scoring (training-kit-01, `package_training_set.py`).** New
`_mean_field()` (promoted from a local closure that used to live only
inside `_build_recommender_payload`, computing `mean_zcr`/`mean_centroid`)
is now the shared helper for every mean-of-a-corpus-field computation:

- `_build_detector_payload()` gains a `band_signal` block
  (`mean_bass_n`/`mean_mid_n`/`mean_treble_n`, `mean_bass_flux`/
  `mean_mid_flux`, `raw_beat_rate_pct` — the real per-frame onset-flag
  rate, distinct from `beat_lock` above which tracks BPM-lock confidence,
  and from `beat_count`/`beat_density` which are a theoretical estimate
  from `bpm x duration`, not a real count). This is the actual data behind
  `drop_score`'s `band_blend` rebalance and new `bass_flux_norm` term
  landed the same day as provisional starting points "pending marathon-
  week data" — now that data exists in every session's LLM payload.
- `_build_recommender_payload()` gains a `spectral_features.vocal` block
  (`mean_vocal_hnr`/`mean_vocal_fmr`), at the corpus's per-heartbeat
  density rather than the recommender-cycle density `profile_recommendation`
  events give the existing `spectral_features.overall` block.
- Both payloads are dumped wholesale into the LLM prompt already (no
  further wiring needed for the LLM to see the raw numbers), but the
  prompt text also gained short explanatory notes pointing at both new
  blocks and explicitly inviting a tuning opinion on `band_blend`/
  `bass_flux_norm` and `vocal_hnr_fit`/`vocal_fmr_fit` — the same "here's
  what this data means and why it matters" treatment `shadow_note` already
  gives the shadow-engine comparison block.

**Not done:** the deterministic `scorecard.md` (as opposed to the LLM-
scored reports) wasn't touched — the ask was specifically about "LLM
scoring & reporting," and the new fields already reach the LLM payloads
without it. A scorecard section could be added later if wanted.

**Verified:** new tests — `tests/test_auto_vj_live_training.py`
(`test_build_live_training_row_captures_every_audiodata_field_except_
fft_waveform`, explicit per-field assertions plus confirms `fft`/
`waveform` are absent) and `tests/test_package_training_set.py`
(`band_signal`/`spectral_features.vocal` summaries, both the populated and
empty-corpus cases, plus `_mean_field()` itself). Full main-repo suite
green (1597 passed), `ruff` clean on every touched file.

---

## Live-Session Follow-Up: Centroid Runaway, HUD Clamp, Director Audit Fixes (2026-08-09)

Decision: a batch of fixes triggered by watching the top-3-weights rewire
run live for the first time, same day it shipped. Owner ran a live
training session immediately afterward and reported the HUD pegging at
`-9.99` repeatedly, sometimes on two different candidates at once.
Digging into the actual corpus data (the new `term_values_by_candidate`
logging, added earlier the same day for exactly this kind of
investigation) found the real cause, plus surfaced three of the director
audit's findings as things to fix immediately rather than defer.

**Root cause: `centroid_fit` was structurally unbounded and swamping
every other term.** The live session's observed spectral centroid ran
`~3700-4000 Hz`; the *brightest*-calibrated profile in the roster
(`psytrance`) only goes up to `2500 Hz`. Every candidate was scoring a
catastrophic centroid mismatch, and because `-0.5*x*x` has no ceiling, the
tightest-sigma candidates (`dubstep`, `hardstyle`, `tech_house`) reached
composite scores past `-70` while `tempo_fit`/`band_fit`/`onset_fit`
stayed in the low single digits for every candidate — `centroid_fit` was
effectively the *only* term that mattered, and the recommender was
picking almost entirely by "which candidate's `spectral_centroid_sigma`
happens to be widest" (`house`/`hyphy`, both `600`) rather than genre fit.
Confirmed directly from a live corpus row before touching any code:

| Candidate | `centroid_fit` | everything else | total |
| --- | --- | --- | --- |
| `house` (won) | -8.2 | ~-1.2 | -9.0 |
| `hyphy` | -6.3 (best centroid_fit of the field) | -1.5 | -10.3 |
| `trance` | -9.3 | -1.2 | -10.1 |
| `dubstep` (worst) | -71.0 | -3.5 | -74.4 |

This also explains the director audit's own `treble` double-count finding
mattering *more* than it looked in isolation: once one term can swing 10-
50x larger than every other term combined, any smaller miscalibration
elsewhere becomes irrelevant noise by comparison -- fixing the ceiling and
the double-count together is what actually restores the composite to
meaning something.

**Fix 1 — every `*_fit` Gaussian term clipped at 6 sigma.** Not just
`centroid_fit` — the owner asked directly "are there other weights that
should be floored/capped?", and the answer is yes: `tempo_fit`,
`zcr_fit`, `onset_fit`, `vocal_hnr_fit`, `vocal_fmr_fit`, and
`top_cand_fit` are all the same `-0.5*x*x` form, all equally capable of
this failure mode given a bad enough mismatch. New shared helper
`_gaussian_fit(diff, sigma)` (nested inside `_update_profile_recommendation`,
alongside `_safe_log2`) clips `x = diff/sigma` to
`±_GAUSSIAN_FIT_X_CLIP` (`6.0`, a new module constant) before squaring —
6 sigma is far enough out that no plausible real reading is affected; it
only bites when a term is already this catastrophically miscalibrated,
which is exactly the case this exists to contain. Ceiling: `-18.0` raw per
term, versus the `-71.0` observed for `dubstep` pre-fix.

**Fix 2 — HUD score clamp removed entirely.** `profile_recommendation_hud`/
`current_profile_score_hud` used to clamp displayed scores to `±9.99`.
Owner: "clamping my live metric display values is absolutely retarded...
let's get rid of that." A clamped readout is indistinguishable from a real
score that happens to land near the old boundary — exactly the
information an operator watching live needs (a term blowing out to `-70`
looks identical to a real, close `-9` once clamped), and it was the direct
cause of "two different profiles pegged at the same number" reading as a
false signal of agreement/confidence rather than what it actually was:
both scores independently blowing past the display floor.

**Fix 3 — `drop_score`'s treble double-count, found in the same-day
director audit, fixed rather than just flagged.** Owner: "don't double
count treble! that explains that lol." Both `beat_grid.py` engines
(`BeatGridTracker`/v1 and `BeatTracker`/v2) had `treble_n` as both a
standalone weighted term *and* inside `band_blend`. Removed the standalone
term; the remaining terms' weights are renormalized proportionally
(divided by their old sum) so they still sum to `1.0` rather than
arbitrarily picking one term to inherit the freed weight. See the audit
doc (`docs/audits/2026-08-09-director-scene-detection-audit.md`) for the
full before/after weight tables.

**Fix 4 — `allow_timeout_forced_transitions` hardcoded fallback flipped
False → True**, per the audit's Recommendation #1 — see the "Subsystem
Versioning" and per-constant tables in the audit doc; not re-derived here.
Owner separately flagged real-world friction this was plausibly
contributing to: "wasn't doing well on long breakdowns/drops in the more
wandering genres w/longer songs." Per-audio-genre-profile overrides for
this (and other director thresholds generally) are explicitly **not**
in this fix — see "Deferred" below.

**Fix 5 — external mixer-hint bias weight raised `1.0` → `2.0`.** Owner:
the external hint terms "seem weak, like not doing crap." At `1.0`, the
external-hint-match/arm-ahead terms needed `confidence x proximity ==
1.0` (never actually reachable — proximity tops out just under `1.0`,
confidence is rarely exactly `1.0` either) to reach the `phrase_bias_max`
clamp on their own, so a confident external confirmation was routinely
getting outweighed by the internal bar-counting terms it was supposed to
reinforce. At `2.0`, it reaches the clamp at ~50% `confidence x
proximity`, letting a real mixer confirmation actually dominate a stale
local guess instead of just nudging it. The mismatch term stays at `0.5`
— confirmation and disagreement were never meant to be symmetric (see the
existing code comment on that asymmetry), and the owner's question was
specifically about "the 1.0s."

**Fix 6 — centroid Hz axis made dynamic.** The spectral-centroid frequency
axis assumed a fixed `22050 Hz` Nyquist (44.1kHz sample rate) regardless
of what the capture stream actually runs at — understating every reading
~8.8% against this project's own documented `48000 Hz` default (Nyquist
`24000`). Owner: "we can't say for sure what Hz will be used by our users
or streams etc." New `AudioManager.sample_rate` public property
(delegates to `AudioCapture.sample_rate`, itself already runtime-detected
from the device/PipeWire) lets `auto_vj.py` derive Nyquist live instead of
assuming it, falling back to `48000` if the audio manager is unavailable
for any reason. This is a real, independent correctness fix — worth doing
regardless of Fix 1, though it alone would not have prevented the runaway
(an 8.8% understatement doesn't explain a 4x-over-range observed value).

**Deferred, not implemented here.** The owner asked "should we have
per-genre tweaks on director, thoroughly? that is really the whole intent
of guessing the genre... to better read/predict/respond to drops &
breakdowns and energy levels" — explicitly connecting per-audio-profile
overrides for `allow_timeout_forced_transitions` (Fix 4) to the director
audit's Recommendation #4 (no per-genre scaling anywhere in `drop_score`
or the mode thresholds, unlike the recommender's `bpm_prior_sigma`/
`spectral_centroid_sigma`/`zcr_sigma`/`onset_density_sigma`). Scoped out
of this fix deliberately: building a genre-profile-override layer for
director thresholds is architecturally bigger than any single constant
(would need a new lookup layer in `_profile_value()`, currently mood-
profile-only, plus new `AudioProfile` fields, plus the same kind of
research pass `zcr_sigma`/`onset_density_sigma` got) and the owner is
about to run a multi-genre, multi-session training marathon specifically
to build a stable base first — exactly the kind of broad, repeated,
tagged data that per-genre director calibration should be researched
against, the same way `zcr_sigma`/`onset_density_sigma` leaned on
`training-house-01`. Recalibrating `spectral_centroid_mu` values upward
(the deeper fix behind Fix 1's defensive ceiling) is deferred for the same
reason: "this is just some hype dj at a club... not exactly super unique"
— the current MIR-research-derived values may need a broad recalibration
pass against real club/marathon material, not a guess.

**Verified:** full main-repo suite green, including new/updated tests
across `tests/test_bpm_detector_audit_regressions.py` (Gaussian clip,
dynamic sample rate), `tests/test_beat_tracker_v2.py` and
`tests/test_beat_grid_tracker_v1.py` (treble double-count, both engines),
`tests/test_auto_vj_profile_hud.py` (HUD clamp removal, both properties),
`tests/test_auto_vj_phrase_structure.py` (external hint weight,
`allow_timeout_forced_transitions` fallback), `tests/test_audio_manager_
startup.py` (`AudioManager.sample_rate`). `ruff`/`bandit` show only
pre-existing findings outside these diffs' hunks.

---

## `spectral_centroid_mu` Recalibrated: the Premise Was a Provenance Bug, Not a Measurement Bug (2026-08-09)

Decision: `spectral_centroid_mu` recalibrated for all 20 profiles to equal
the centroid implied by that profile's own `expected_bands` fingerprint
(same weighted-mean-frequency formula the live recommender already uses),
rounded to the nearest 50 Hz. Owner, after watching the Gaussian-clip fix
land and reviewing a packaged session: "that's crazy, didn't we research
appropriate values? this is just some hype dj at a club so it's not
exactly super unique... we need to figure out what in our premise is
wrong and re-evaluate for all genres."

**Root cause.** `spectral_centroid_mu` and `expected_bands` were
generated in two separate synthesis passes (`spectral_centroid_mu`
hand/LLM-authored ad hoc; `expected_bands` via `tools/gen_spectral_
fingerprints.py`'s dedicated 64-band LLM synthesis, 2026-08-03/06) and
never cross-checked against each other. Computing each profile's implied
centroid directly from its own `expected_bands` and comparing to the
stated `spectral_centroid_mu` found 14 of 20 profiles disagreeing
substantially — the fingerprint implying a *brighter* target than the
stated mu, by as much as `1.91x` (`chillstep`: 900 stated vs. 1718
implied) and `1.77x` (`house`: 1500 vs. 2654). The live session that
triggered this investigation had an observed median centroid of `2887 Hz`
— which looked like a wild outlier against the old `mu` values but sits
close to what most profiles' own fingerprints already implied. The
"premise" the owner asked about wasn't wrong in the sense of a bad
assumption about club music being bright — it was wrong in the sense that
two numbers meant to represent the same thing were never made to agree.

**Confirmed the diagnostic already existed and was simply never wired
up.** `gen_spectral_fingerprints.py`'s `main()` already prints a
`centroid≈` estimate per profile as a sanity-check line, computed with
the identical formula — the tool's author had this number in hand at
generation time and it was never used to set `spectral_centroid_mu`. Not
a missing capability, a missing cross-reference. Comment added at that
print site so a future profile addition copies the number directly
instead of re-authoring one independently.

**Fix: full replace, not a blend.** Owner explicitly chose deriving
`spectral_centroid_mu` fully from `expected_bands` over a blended/
averaged approach or waiting for marathon data — makes the two
brightness representations self-consistent by construction rather than
narrowing a gap. `spectral_centroid_sigma`'s tight/medium/wide tiers were
**not** touched in this pass (they weren't part of what was checked
against `expected_bands`) — a separate follow-up, since the relative
spacing between profiles shifts under the new `mu` values.

**This does not validate `expected_bands` itself, and that surfaced two
real oddities.** Two long-standing test assertions about genre brightness
ordering broke under the recalibration, both pointing at the fingerprints
disagreeing with their own genres' documented acoustic character rather
than at stale test expectations:

- `house` now implies *brighter* (`2650`) than `tech_house` (`2550`),
  even though `tech_house`'s own `acoustic_notes` explicitly say
  "pronounced hi-hat energy 8-16 kHz" against `house`'s "modest...
  moderate presence" — the genre with the *documented* brighter
  character now has the *lower* implied centroid.
- `chillstep` now implies brighter (`1718` unrounded, `1700` rounded)
  than `synthwave` (`1684`/`1700`), contradicting `synthwave`'s own test
  comment describing it as sitting "between chillstep (atmospheric-only)
  and house (percussion-driven) by design."

Both tests were updated to check what's still true (the parts of each
ordering that hold) rather than silently inverted or deleted — see
`tests/test_audio_profile_deep_house_and_disable.py` and `tests/
test_audio_profile_synthwave.py`. This is flagged as an **open question
about `expected_bands`'s own accuracy**, not resolved here: the
fingerprints were generated by LLM synthesis grounded in MIR literature
notes, same as the old `spectral_centroid_mu` values were, and may carry
their own calibration drift independent of the mu/fingerprint consistency
problem this fix closes.

**Deferred:** `spectral_centroid_sigma` tier re-examination, and a
broader `expected_bands` accuracy pass — both explicitly waiting on the
owner's upcoming multi-genre training marathon for real data to check
against, same reasoning as the deferred per-genre director tweaks above.

**Verified:** full main-repo suite green (1546 passed), including the two
updated ordering tests (now checking only the orderings that still hold,
with comments explaining what changed and why). `ruff`/`bandit` clean.

---

## Director/Detector/Recommender Refinement Batch (2026-08-09)

Implements the LHF (low-hanging-fruit) items from
`docs/planning/auto-vj-director-detector-refinement-plan-2026-08-09.md`
after two discussion rounds resolved nearly all open questions. Deferred
items (config-menu UI, PGW/PGTT, CLI A/B overrides, `INTRO`/`OUTRO` modes)
stay in the plan doc as follow-on work, not covered here.

**`DROP -> IMPACT`: confirmed final design philosophy.** The 2026-08-05
one-shot design below (`_infer_peak_tier()` decided once at `_fire_drop()`
time) is the permanent mechanism for how a drop's tier gets decided --
nothing further planned on that specific question. What changes in this
batch is downstream of it: what IMPACT *does* once a major-tier drop has
fired.

**CLIMAX decoupled from IMPACT.** Previously CLIMAX was reachable only
through IMPACT -- `_enter_climax()`'s only call site was inside the
`_mode == _IMPACT` branch, after `impact_hold_s` elapsed on a major-tier
flourish. IMPACT wasn't just "the flourish for a major drop," it was also
the *only* corridor CLIMAX could be reached through. Owner: "IMPACT is
purely related to firing of major drop... obviously IMPACT -> CLIMAX is not
appropriate anymore." Now: `climax_worthy`'s gate (unchanged verbatim --
`peak_tier == 'major'`, downbeat confidence, score-vs-threshold-plus-
progress OR early-override) is evaluated directly from the `DROP` branch,
guarded by a minimum time-since-fire floor that reuses `impact_hold_s`
rather than inventing a second timing constant. IMPACT itself is now purely
the fixed-duration entry flourish -- it always settles back into ordinary
DROP when its hold elapses, no gate check left inside it.

**`BREAKDOWN <-> DROP` added; general order loosening.** `BREAKDOWN -> DROP`
didn't exist at all -- confirmed via code inspection, not just doc gaps.
Owner: "that's like most songs in the primary target genres" (many
house/tech-house tracks breakdown straight back into the next drop with no
distinct build phase). Added, gated by the same score/downbeat-confidence
threshold BUILD's own (non-fastlane) drop trigger uses, plus a small
minimum-time-in-breakdown floor. `DROP -> BREAKDOWN` also added: a drop that
fizzles, or whose cooldown elapses while energy is already low, can now
settle straight into BREAKDOWN instead of always routing through CRUISE
first -- reuses the same low-energy evidence CRUISE itself already used to
detect a breakdown (`_post_drop_landing_mode()`), so the destination
reflects live audio evidence rather than a fixed sequence position. Per
owner direction ("we really shouldn't be discriminating about order much at
all, aside from intros, outros & major drop -> climax"), the remaining hard
constraints are: CLIMAX only follows a major-tier DROP (unchanged), and the
intro/outro concept -- which doesn't exist in the mode state machine yet and
is scoped as its own follow-on design (two new source-gated modes,
`INTRO`/`OUTRO`, applied only when dj-mixer-01/media-01 can supply section
metadata) rather than implemented in this batch.

**`drop_score` composition reworked (both `BeatGridTracker`/v1 and
`BeatTracker`/v2, `beat_grid.py`).** `band_blend`'s internal split moved
0.45/0.30/0.25 (bass/mid/treble) to 0.7/0.2/0.1 -- a drop should read
primarily off the bass band. v2 gained a new term, `bass_flux_norm`: a
dedicated bass-transient signal (the previous composite had none -- only a
smoothed bass *level* via `band_blend`, no bass *attack* detector), using
`bass_flux` (already computed per-frame in `unicornviz/audio/analyzer.py`
for downbeat detection, propagated through `AudioManager._copy_audio_into`,
previously unused by `drop_score`). Fast-attack/slower-release envelope
(not the symmetric EMA the existing flux term uses) -- owner: "one big bass
hit after next to no bass should hit like a freight train as fast as
possible." The existing `flux_norm` term is rescoped to mid+treble only
(`spectral_flux - bass_flux`, since no separate treble-only signal is
computed) to avoid double-counting bass between it and the new term -- the
same shape of bug as the treble double-count fixed earlier the same day,
just avoided proactively this time instead of found after the fact. Full
5-term reweight: `energy_norm*0.15 + slope_norm*0.35 + band_blend*0.15 +
flux_norm*0.10 + bass_flux_norm*0.25` (was `energy_norm*0.25 +
slope_norm*0.409 + band_blend*0.182 + flux_norm*0.159`). `slope_norm` stays
the clear largest single term (it drives most breakdown->build detections);
`bass_flux_norm` is the second-largest, per "make it heavy." **All of these
numbers are a first-pass starting point, not final** -- the full reweight
genuinely needs the upcoming training-marathon's data (plan section 4d).

**`_phrase_bias()`'s 9 inline literals (7 conceptual terms) extracted into
named, profile-scoped constants** (`_phrase_under_over_hold_mult`,
`_phrase_boundary_bonus_mult`, `_phrase_peak_flourish_bonus_mult`,
`_phrase_early_song_suppress_mult`, `_phrase_outro_suppress_mult`,
`_phrase_external_match_mult`, `_phrase_external_mismatch_mult`,
`_phrase_external_arm_mult`). Owner: "hidden magic is no good... let's log,
track & analyze [these], and extract them into tweakables." Two value
changes land in the same commit:

- `phrase_boundary_bonus_mult`: 0.25 -> 0.3 (LLM tuning recommendation from
  the `library/a` training session, applied as-is).
- Sectionality (`phrase_external_match_mult`/`phrase_external_arm_mult`):
  1.0 -> 2.0 (earlier today) -> **1.5** (this batch). The "raise it hard,
  treat it as quite authoritative" instruction from earlier today was
  originally misattributed to `phrase_boundary_bonus_mult` -- corrected by
  the owner to mean these sectionality terms instead. The final value isn't
  the largest defensible number, though: owner framed it as an
  explore/exploit call, not an accuracy call -- "we still want the AI to do
  *some* work... it's more important to have it learning for the next
  months or year... if we don't give it opportunity to chip in, it won't
  learn anything." At 2.0 a confident external hint could dominate the
  internal bar-counting/audio-evidence terms almost completely, starving
  the internal detector/director's own reasoning of the chance to be tested
  against real outcomes -- exactly the signal the training marathon needs.
  1.5 keeps external hints the clearly strongest single evidence category
  (above the internal terms' 0.3-0.6 range) while leaving room for internal
  reasoning to occasionally win and generate learnable signal.

Per-term logging added: `_phrase_bias()` now stashes its last call's full
term breakdown (`self._last_phrase_bias_terms`), picked up by
`_mark_mode_transition()` and included in every real transition's action-log
payload as `phrase_bias_terms` -- answers "are we not logging the external
influence data? that would tell us what and when which is correct" (owner)
directly: previously nothing recorded what `_get_section_hint()` returned or
contributed on any given tick.

**Timing constants** (`build_max_s`/`breakdown_max_s` per mood profile).
Owner-supplied values directly, not derived: chill 52->60 / 55->120, normie
36->45 / 52->90, raver 55->30 / 80->60. Raver previously had the *longest*
`build_max_s` (55.0, even longer than chill's 52.0) and by far the longest
`breakdown_max_s` (80.0) -- backwards for a mood meant to have the shortest
patience/fastest cycling. Owner's own explanation: "those timings make some
sense since most of my tuning in those days was spent in raver mode" --
raver absorbed most of the early hand-tuning attention, leaving chill/normie
comparatively under-tuned by accident. Also: `drop_timeout_score_floor`'s
code-level fallback default changed from `self._drop_threshold` (no actual
relaxation, despite being documented as a "relaxed-but-not-zero floor") to
`self._drop_threshold * 0.65` (in the family of the three shipped profiles'
own values) -- never misfired in practice since all three profiles already
override it, but the fallback should behave as documented for a future
profile that omits the key.

**Recommender weights**: `spectral_shape_fit` 1.0 -> 1.2,
`kick_regularity_fit` 0.5 -> 0.7 -- both LLM tuning recommendations from the
`library/a` session, applied as-is.
`_BPM_LOCK_RELEASE_CONFIDENCE` 0.28 -> 0.25 was also recommended by the same
session but **held back, "to watch" only** -- that session's own scorecard
shows `0 lock gained` / `0 lock lost`, zero churn, so the LLM's stated
rationale ("minor lock churn suggests release confidence is slightly too
high") doesn't match the data it came from. Revisit only if a future
session's scorecard actually shows churn.

**`tech_house.spectral_centroid_mu`** (`unicornviz/audio/profiles.py`):
2550 -> 2900, also an LLM tuning recommendation (observed 2910.5 in the same
session). Checked for overlap before applying: `house` sits at mu=2650/
sigma=600 (the exact profile behind that session's #1 confusion, `Tech
House -> house`, 1060x) -- moving tech_house's mu to 2900 *increases* its
distance from house's mu (100 -> 250), working against the observed
confusion rather than into it. `deep_house` (1250) and `peak_time` (2350)
are already far enough away that the move doesn't bring tech_house closer
to either.

**Training-set packaging** (`drop-ins/training-kit-01/tools/
package_training_set.py`): the five per-bucket report files
(`scorecard.md`, `recommender_score.md`, `detector_score.md`,
`director_score.md`, `tuning_recommendations.md`) stay fully separate
(owner instruction -- this wasn't the discoverability fix). New: a follow-up
LLM call synthesizes all five into a short console-only summary (top 3
takeaways, whether any report's recommendations conflict with another's, a
pointer to the single most actionable file) printed at the end of a
packaging run, followed by reminders of all five file paths -- addresses
"I don't see anything about the weights from the LLM report" (the
recommendations were real, just living in `tuning_recommendations.md` while
the user was checking `recommender_score.md`).

**Subsystem versioning rescheme**: `_DETECTOR_VERSION`/`_DIRECTOR_VERSION`/
`_RECOMMENDER_VERSION` moved from an `0.x.y` scheme to `1.0.0-rc.N` --
`_DETECTOR_VERSION` -> `1.0.0-rc.3`, `_RECOMMENDER_VERSION` ->
`1.0.0-rc.2`, `_DIRECTOR_VERSION` -> `1.0.0-rc.2`. See the "Subsystem
Versioning" ADR entry above for the original scheme and the plan doc
section 8a for the full resolution -- reuses `__version__`'s own existing
`-rc.N` qualifier rather than inventing a new one, and needed no `CLAUDE.md`
exception since that qualifier was already the sanctioned "approaching 1.0"
signal for this codebase.

**Verified:** [pending -- see commit for test run results]

---

## Phrase-Aware Director: Bar-Relative Bias + IMPACT Fold-In (2026-08-05)

Decision: the director gains a bar-relative phrase clock and a soft
threshold bias (docs/planning/auto-vj-phrase-structure-plan-2026-08-05.md,
Phase 1), and `IMPACT` is removed as a held state -- folded into `DROP` as
a fixed-duration entry flourish for a later drop, with `CLIMAX` demoted
from "the thing every drop tries to escalate into" to a rarer,
final-peak-only decision. This is a director/state-machine change, not a
detector change -- logged here per this doc's own header
("`[auto_vj]` config keys" is explicitly in scope) since no separate
director ADR exists.

**Root cause this addresses:** the director had zero structural model of a
song -- every transition was purely audio-reactive (energy slope,
`drop_score`) plus wall-clock/BPM-scaled timers, with a single exception
(`_current_song_progress()` gating `CLIMAX` at 50% track duration, see the
BPM Detector Audit section above). Real training data
(`2-hour-deep-house-dj-smart-list/a`, 2026-08-05 session, 179 min) showed
the concrete symptom: the LLM director score flagged "good use of build
opportunities but frequent reversals prevent fruition into drops"
(Opportunity Usage 3/5, Drop Quality 2/5) -- BUILD was being cut off before
resolving into DROP at the same rate regardless of how many bars it had
already run.

**Fix -- phrase clock (`_bars_since_track_start`/`_bars_since_phase_entry`/
`_drop_cycle_count`):** three counters driven purely by the beat tracker's
`is_downbeat` firing (`_maybe_log_downbeat_event()` → `_advance_phrase_clock()`),
so they need no track metadata and work identically for Spotify, the
mixer, media, or a raw live source. `_bars_since_phase_entry` resets inside
`_mark_mode_transition()` itself (every real transition goes through it),
so no transition site needed individual updating. `_bars_since_track_start`/
`_drop_cycle_count` reset on a `change_counter`-detected track-identity
change (`_reset_phrase_clock_for_track_change()`), which also opens a
short neutral-bias window -- a hard DJ deck-cut looks identical to a
genuinely fresh track from here, so bias is withheld rather than guessed
either way (plan section 6.1, Phase 1 mitigation; Phase 2 needs the
dj-mixer-01 section detector to resolve this properly).

**Fix -- `_phrase_bias(role)`:** a soft additive term (bounded to
`±phrase_bias_max`, default 0.15) from three components -- how
`_bars_since_phase_entry` compares to that role's expected bar range (new
per-profile `phrase_*_expected_min/max_bars` keys), a small bonus near a
`phrase_boundary_bar_unit`-bar boundary, and a `_drop_cycle_count`/
`song_progress` position term. Applied as `effective_threshold =
base_threshold - bias` at three sites: CRUISE's build-sustain requirement
(`_phrase_bias('HOLD')`), BUILD's min-hold-before-resolving-to-DROP
(`_phrase_bias('RISE')` -- the one that directly targets the training-data
finding above), and BREAKDOWN's recovery-to-BUILD energy bar
(`_phrase_bias('FALL')`, deliberately *not* touching the timeout deadline
itself, which stays locked at breakdown-entry per the existing anti-drift
design). Never a hard gate -- strong audio evidence always wins regardless
of bias sign.

**Fix -- IMPACT fold-in + `peak_tier`:** `_infer_peak_tier()` decides
`'major'`/`'minor'` once, at `_fire_drop()` time, from
`_drop_cycle_count >= phrase_peak_flourish_min_cycle` (default 2) plus a
guard against a fizzle-retry counting as real setup (prior phase must have
run at least half of `RISE`'s expected minimum). A `'major'` drop calls
`_enter_impact()` immediately (reusing its existing richer postfx/effect/
burst entry treatment) instead of DROP's own weaker entry hit; a
`'minor'` drop gets DROP's normal entry unchanged. The `IMPACT` tick
branch no longer extends indefinitely while "still hot" -- it holds for a
fixed `impact_hold_s`, then decides once whether this is also the
set-defining `CLIMAX` moment (`peak_tier == 'major'` AND downbeat
confidence AND (score clears `climax_entry_score` with song progress
favoring it, OR score alone clears the generalized
`climax_early_override_score` escape hatch)) or simply settles back into
DROP's normal groove. Superseded/removed as genuinely dead once the
mid-groove escalation check no longer exists: `impact_trigger_score`,
`impact_min_delay_s`, `impact_max_delay_s`, `impact_timeout_score_floor`,
`impact_min_downbeat_confidence`, `climax_entry_score_floor`,
`impact_extend_max_factor` -- all three profile presets and the loading
section.

**Root cause this supersedes (partially):** the 2026-06-18 archived plan
(`docs/planning/auto-vj-breakdown-impact-climax-plan.md`) introduced
`IMPACT` as a mid-groove-earned escalation gate; a 2026-06-28 follow-up
(comment-only, no doc) pushed its trigger later but kept the same
structural gap. Neither had any notion of phrase length or drop-cycle
position -- see the plan doc's §3 for the full history.

**Verified:** `tests/test_auto_vj_phrase_structure.py` -- phrase-clock
counter increment/reset behavior, `_phrase_bias()` bounds/sign/neutral-window
override, `_infer_peak_tier()`'s cycle+setup-length gating, `_fire_drop()`
routing minor-tier drops straight to DROP vs major-tier drops through
`_enter_impact()`, and the IMPACT tick branch's climax-worthy decision
across major/minor tier, known/unknown song progress, and the early-override
path. Full existing `tests/test_auto_vj_*.py` suite (auto-vj-01) and
`tests/test_auto_vj_downbeat_pulse.py` (updated for the new counters) pass
unchanged.

**Scope note:** this is Phase 1 only (self-contained in auto-vj-01, per
the plan's §9 staging) -- the dj-mixer-01 section-detector integration
(plan §6) is pending that team's review and not implemented here. The
`phrase_*_expected_*_bars` starting defaults are general dance-music
convention, not yet corpus-validated (plan §7).

### Phase 2: mixer section-hint bus (2026-08-05)

Decision: a new song-structure hint bus (`App.publish_section()`/
`get_section()`, `VjApi` wrappers), symmetric to the existing BPM bus, plus
the auto-vj-01 consumer side wired against the wire contract dj-mixer-01's
team reviewed and agreed (plan §6, amendments §6.a-6.d). dj-mixer-01's
`structure.py` (the detector itself, 661 lines, 18 tests) landed as
groundwork the same day; this entry covers the channel and consumer side,
not the detector.

**Bus (`unicornviz/app.py`/`vj_api.py`):** `_section_hints: dict[str,
tuple[dict, float]]`, `_SECTION_HINT_TTL_S = 5.0`, `_SECTION_ROLES =
('HOLD', 'RISE', 'PEAK', 'FALL', 'CLOSE')` -- line-for-line the same shape
as `_bpm_hints`/`_BPM_HINT_TTL_S`. `publish_section()` validates `role`
against the canonical set and drops anything else rather than storing a
payload a consumer would have to re-validate; both `publish_section()` and
`get_section()` deep-copy the dict so neither side can mutate the other's
state through a shared reference.

**Consumer (`drop-ins/auto-vj-01/auto_vj.py`):**

- `_get_section_hint()` wraps `vj_api.get_section(exclude='auto_vj')`
  defensively (missing method / lookup error / non-dict → `None`), same
  pattern as `_current_song_progress()`.
- `_infer_peak_tier()` (plan §6.a): a confident external `PEAK` tier
  (`confidence >= phrase_external_tier_min_confidence`, default 0.6)
  overrides local cycle-count inference outright -- the mixer knows which
  peak is genuinely biggest from the whole file; the director can only
  ever guess from how many drops it's seen so far live.
- `_phrase_bias()` (plan §6.c): a confidence-*scaled* external term, not a
  presence-gated switch -- a role match adds `phrase_bias_max * confidence`;
  a confident mismatch subtracts half that. A 0.53 hint barely nudges
  anything; a 0.95 one nearly maxes out the term. This was the amendment
  that mattered most for not overreacting to a shrug.
- `_maybe_sync_phrase_clock_from_section_hint()` (plan §6.1, "Resolved by
  amendment 6.a"): during the post-track-change neutral window opened by
  `_reset_phrase_clock_for_track_change()`, a fresh hint sets
  `_bars_since_phase_entry` from `bars_in` and `_peak_tier` from `tier`
  directly, closing the neutral window early -- this is what turns the
  hard-deck-cut *mitigation* (Phase 1: wait a few bars blind) into an
  actual *fix* (Phase 2: the mixer already knows exactly where deck B's
  playhead is). Called from `_advance_phrase_clock()` on every downbeat
  while the window is still open; the Phase 1 blind-wait behavior is the
  automatic fallback whenever no hint is available (bare stream, or the
  mixer not running).

**Not implemented:** plan §6.b ("publish the *next* role too", the
transition-arming amendment). `structure.to_wire()` does not return next-role
fields as of this commit -- the mixer team was still finishing that piece
("wrapping up... pretty much done" per the owner, 2026-08-05). Building
consumer logic against undocumented, not-yet-shipped field names was judged
worse than shipping the rest and picking this up once the wire payload
actually carries it; nothing here needs to change to add it later, since
`_get_section_hint()`/callers already read the payload via `.get()` and
silently ignore keys they don't recognize.

**Verified:** `tests/test_section_bus.py` (bus-level: publish/get,
copy-not-reference semantics, role validation, TTL expiry, all five
canonical roles) and new cases in
`tests/test_auto_vj_phrase_structure.py` (`_get_section_hint()` error
handling, the neutral-window sync, `_phrase_bias()`'s external term sign
and confidence scaling, `_infer_peak_tier()`'s confidence floor and
role-mismatch rejection) plus `test_vj_api_postfx.py` (the `VjApi`
wrappers against a real `App`).

---

## Confidence Model

Decision: phase coherence over 32-onset rolling window

`_V2_COHERENCE_WINDOW = 32` — values are multiples of 1/32 = 0.03125.

**Known structural equilibrium:** at typical dance music densities, ~12 out of
32 recent onsets land in the ±18% phase window → confidence = **0.375**.
This is the natural resting value when tempo is approximately correct.  It is
not a bug; do not interpret it as failure.

Phase tolerance: `_V2_PHASE_TOL = 0.18` (±18% of beat period).  Do not widen
above 0.25 or the oscillator stops discriminating on-beat from near-beat onsets.

ACF blend (2026-07-06 fix — see "Confidence Blend" section below for the
bug this replaced):
`self._confidence = 0.4 * self._acf_confidence + 0.6 * self._phase_confidence`,
where `_acf_confidence` and `_phase_confidence` are each persisted
independently and recomputed whenever either input signal updates — so the
blend can no longer be silently discarded by whichever signal updates last.

---

## Lock State Management

Decision: Schmidt trigger (hysteresis gate) for BPM lock events

Rationale: a single threshold caused ~1,350 lock-gained / lock-lost events per
session when confidence hovered around the boundary.  The Schmidt trigger
reduced house churn to ~55 events/session (96% reduction).

Current thresholds (mirrored in packager `_BPM_LOCK_CONFIDENCE_FLOOR`):

| Constant | Value | Meaning |
| -------- | ----- | ------- |
| `_BPM_LOCK_CONFIDENCE` | `0.55` | Confidence must reach this to **gain** lock |
| `_BPM_LOCK_RELEASE_CONFIDENCE` | `0.28` | Lock held until confidence drops **below** this |
| `_BPM_LOCK_CONFIDENCE_FLOOR` (packager) | `0.45` | Rows counted as "locked" in scorecard / LLM payload |

The hysteresis band (0.28–0.55) spans the natural equilibrium at 0.375 so the
gate is stable during steady-state cruise.

**Do not narrow the band below ~0.20 width** — the natural 0.375 equilibrium
sits inside the band by design.

---

## Tactus Preference Ratio

Decision: keep `tactus_preference_ratio` ≥ 0.50 for house/techno material

The ACF tactus descent checks fold factors `(0.5, 2/3, 0.75)`.  At ratio 0.42:

- 0.75× factor fires too easily: 120 BPM × 0.75 = **90 BPM**
- This dominated the house BPM histogram (1,488/3,107 rows at 90–99)
- Before the change, house median was 120–125; after, it dropped to 98

**The 0.75× fold factor is the trap.** The 0.5× (half-time) fold is fine; the
2/3× and 0.75× folds cause spurious results at low ratio values.

For downtempo / chillstep material: use `bpm_hint_max` from the AudioProfile
to cap the search range instead of lowering this ratio globally.

Default: 0.55 (code default, not set in `config.toml`).  Override only in
per-profile `tactus_preference_ratio` if that API is added — not globally.

---

## Tempo Hold

Decision: `tempo_hold_s = 10.0`, `silence_reset_s = 15.0`

Spotify crossfade overlaps last 5–12 s of a track with the incoming track.
During this window, the incoming track's onset pattern conflicts with the
current BPM estimate.  A 10 s hold bridges the overlap so the departing
track's tempo is maintained until the new track stabilises.

`tempo_hold_s`: **now the code default `10.0`** (`beat_grid.py`). Was `6.0` with
config.toml overriding to `10.0`; baked as the default 2026-07-13 (see the
2026-07-13 entry below).

`silence_reset_s` (2026-06-20): `_reset_tempo_lock()` fires after this many
seconds with no detected onsets, zeroing `bpm` and `confidence`.  Default 2.0 s
was shorter than a typical Spotify crossfade gap, causing 53% of peak_time
sequence rows to show `bpm=0.0` mid-session.  **Now the code default `15.0`**
(`beat_grid.py`), so the detector holds its tempo through the full crossfade
window without resetting (baked 2026-07-13).

---

## Audio Profile System

Decision: two independent profile systems — do not conflate them

### 1. Audio profiles (BPM detector)

Set with `[audio] profile = "..."` or `Alt+A` / `Alt+Shift+A` at runtime.
Configures the BeatTracker's BPM prior and (since 2026-06-20) caps the ACF
search window via `bpm_hint_min` / `bpm_hint_max`.

| Profile | BPM prior µ | σ (log2) | `bpm_hint_min` | `bpm_hint_max` |
| ------- | ----------- | -------- | -------------- | -------------- |
| `house` | 124 | 0.40 | — | — |
| `chillstep` | 90 | 0.45 | 78 | 108 |
| `trance` | 138 | 0.40 | — | — |
| `ambient` | 80 | 0.50 | — | — |
| `generic` | 120 | 0.55 | — | — |

`set_profile()` on both v1 and v2 trackers now applies `bpm_hint_min/max` and
re-runs `_setup_acf_arrays()` when the range changes.

**Note (table above is stale):** the table predates the current 20-profile roster (see
`unicornviz/audio/profiles.py` for the authoritative list) and even shows outdated σ values for
`house`/`chillstep`; not rewritten here as out of scope for this entry.

**`rap`/`hyphy`/`r&b` bpm_hint gap fixed (2026-07-08):** these three were the only profiles in the
entire roster with no `bpm_hint_min`/`bpm_hint_max` set at all — meaning their ACF search ran the
full unconstrained `60-200` BPM range (`_V2_BPM_MIN`/`_V2_BPM_MAX` in `beat_grid.py`) relying only
on the soft Gaussian prior, while every other profile hard-caps its search to an 8-40 BPM window.
Discovered while investigating a live Detroit techno (120-135 BPM) track locking the recommender
into `hyphy` despite having no vocal content — the uncapped search meant techno's tempo wasn't
rejected outright, only mildly penalized by the prior (~1.3-1.6σ off-center). Fixed by wiring each
profile's hint range to the tempo pocket already documented in its own code comment: `rap` 70-100,
`hyphy` 90-110, `r&b` 75-100. This is a search-range fix, not a fingerprint fix — it does not by
itself solve non-vocal tracks matching the vocal-forward spectral shape (see the HNR/FMR vocal-
detection work below).

### 2. VJ mood profiles (director)

Set with `Ctrl+J` → `M`.  Called **moods**: `chill`, `normie`, `raver`.
Controls director visual intensity and transition aggression.
**Has no effect on BPM prior or detection range.**

These systems are independent.  Audio profile ≠ VJ mood.

### Capability-aware disable + two new profiles (2026-08-03)

`AudioProfile` gained an `enabled: bool = True` field (mirrors unicorn-horn
ADR-0003's stem-toggle pattern: disable, don't delete). `enabled_profiles()`
in `unicornviz/audio/profiles.py` filters by it; both `list_profiles()`
(`Alt+A` cycling) and the recommender's candidate-scoring loop
(`_update_profile_recommendation` in `auto_vj.py`, previously iterating
`PROFILES.items()` directly) now go through it, so "disabled" consistently
means excluded from *both* manual cycling and automatic recommendation —
not just hidden from one. `get_profile(name)` is unaffected: direct lookup
by key still resolves a disabled profile, so existing config referencing
one by name, or `get_profile()`'s own fallback-on-unknown-key path, keep
working.

`generic` is the first (and so far only) profile disabled this way — it was
actively competing with, and getting confused with, genuinely calibrated
genre profiles once enough of the roster existed to cover real material.

Also added `deep_house` (118-124 BPM, warmer/lower-centroid than `house`,
chord-stab-driven fingerprint) — the house family previously only had two
points (`house`, `tech_house`), leaving the slower/warmer end uncovered.
Built with the same MIR-literature-grounded methodology as `synthwave`
(added earlier the same session, see `tools/gen_spectral_fingerprints.py`
and the profile's own code comment) — not yet validated against real
session data.

---

## Chill Profile — Confidence Thresholds (2026-06-20)

Decision: lowered `mode_entry_min_confidence` from 0.50 → 0.38 in the `chill` preset

Chillstep training data (mix-02, 43 min) showed the director completely dormant:
0 drops, 0 impacts, 1 mode transition.  Analysis of the autovj decision log:

- BPM confidence median: 0.406 (structural equilibrium, same as house)
- Ticks with confidence ≥ 0.50 (old gate): **16.8%**
- Ticks with confidence ≥ 0.38 (new gate): **37.7%**
- `drop_score > 0.55` moments: 328 / 2,597 ticks — energy WAS reaching threshold

The 0.50 gate meant the director could almost never enter BUILD mode even when
audio energy was high enough for a drop.  0.38 sits just above the 0.375
structural equilibrium, matching how the chillstep confidence actually behaves.

Changed in the `chill` preset simultaneously:

| Key | Old | New | Reason |
| --- | --- | --- | ------ |
| `mode_entry_min_confidence` | 0.50 | 0.38 | Primary gate blocking BUILD entry |
| `drop_min_downbeat_confidence` | 0.42 | 0.34 | Aligned with new entry threshold |
| `impact_min_downbeat_confidence` | 0.42 | 0.34 | Aligned with new entry threshold |
| `climax_min_downbeat_confidence` | 0.42 | 0.34 | Aligned with new entry threshold |
| `drop_timeout_score_floor` | 0.62 | 0.50 | Allow timeout-triggered drops at moderate score |
| `impact_timeout_score_floor` | 0.58 | 0.48 | Allow timeout-triggered impacts at moderate score |

`drop_energy_threshold` stays at 0.55 — the score reaches it ~12.6% of ticks,
which should yield ~3–8 drops per 43-minute chillstep session.

---

## Auto-Profile Raver Threshold

Decision: `auto_profile_raver_min_bpm = 126.0`

Peak_time playlist material was consistently detected at ~127.7 BPM.  With
the threshold at 128.0, every track at that BPM triggered normie instead of
raver, causing the director to run the wrong intensity profile for the entire
set.  Lowered to 126.0 (2026-06-20) to give 2 BPM headroom below typical
peak_time material while still clearly separating raver (>126) from the
normie midrange (105–126).

History: was 125.0 originally, raised to 128.0 on 2026-06-20 during initial
tuning, then immediately reverted to 126.0 when peak_time session logs showed
the raver→normie oscillation.

---

---

## Recommender → Tracker Profile Apply (no immediate push)

Decision: `_maybe_apply_recommended_audio_profile()` must **not** call
`_grid.set_profile()` directly; the BPM tracker update is deferred to
`_sync_grid_audio_profile()` with its existing 12 s hold + 0.35 confidence
gate.

Previously the apply function pushed the new AudioProfile to the tracker
immediately after the audio manager accepted it.  This caused a "20 BPM hot"
regression: switching from chillstep to house shifted the tracker's Gaussian
prior from mu≈85 to mu≈125, dragging a correctly locked 105 BPM reading up
to ~125 before any track-tempo evidence had been observed.

The audio manager profile switch still happens immediately (affects spectral
feature expectations and VJ mood logic).  Only the tracker prior update is
deferred so the tracker keeps its correct reading while accumulating evidence
that the new profile is stable.  (2026-06-21)

---

## `tempo_fit` neutral default when no BPM detected

Decision: `tempo_fit = 0.0` (not `-3.0`) when no BPM samples exist in the
scoring window.

The penalty `−3.0` made all profiles equally bad when BPM was not yet locked,
causing erratic recommender scores and keeping scores stuck near 0 in the HUD
during the warmup phase.  Neutral (0.0) skips the tempo term when there is no
evidence, letting band-fit / spectral signals drive early profile selection.
The tempo term contributes as soon as BPM evidence accumulates.  (2026-06-21)

---

## BPM Jump Guard — `lock_band_pct` (2026-06-28)

Decision: raised `lock_band_pct` default from `0.12` → `0.16`

**Problem:** The jump guard in `_estimate_tempo_acf()` computes:

```python
jump_limit = max(lock_band_min, bpm * lock_band_pct)   # lock_band_min = 10.0
if abs(best_bpm - self._bpm) > jump_limit and acf_conf < large_jump_confidence:
    return  # block the update
```

At a false-locked 148 BPM EMA, `lock_band_pct = 0.12` yields `jump_limit = max(10, 148×0.12) = 17.76`.
A 20 BPM correction (148 → 128) exceeds this limit, so the guard fires unless
`acf_conf >= large_jump_confidence (0.72)` — a very strict threshold rarely met on real-world audio.
The `candidate_history` spread guard (3 consecutive ACF frames within 4 BPM) is the correct primary
stability mechanism; `large_jump_confidence` is a secondary check that was over-constraining legitimate
corrections.

**Fix:** `lock_band_pct = 0.16` → `jump_limit = max(10, 148×0.16) = 23.7`, which covers the full
20 BPM lane-change without requiring the high-confidence gate.  The `candidate_history` guard (3
frames, spread < 4.0 BPM) remains the primary protection against single-frame ACF noise jumping the
EMA.

**Observed symptom:** Detector locked ~20 BPM hot and stayed there for multiple songs because
`max_bpm_step = 3.0` caps how fast the EMA moves per block when the update is not fully blocked —
but here the update returned early, so `self._bpm` never moved at all.

---

## Confidence Blend Bug — `_acf_confidence` / `_phase_confidence` split (2026-07-06)

Decision: split `self._confidence`'s two inputs into independently-persisted fields

**Problem:** `_absorb_onset()` set `self._confidence = sum(coherence_buf) / len(coherence_buf)`
(raw phase coherence) on **every onset**.  `_estimate_tempo_acf()` set
`self._confidence = 0.4 * acf_conf + 0.6 * self._confidence` (the documented ACF blend), but only
when a full ACF update completes — throttled to 1-in-`_V2_ACF_INTERVAL` (8) frames and further
gated by several early-return guards (ambiguous score, low update confidence, tempo-hold window,
candidate-persistence check, jump guards).  Because onsets arrive far more often than completed
ACF updates in real audio, the ACF's contribution was overwritten by the very next onset almost
immediately — the blend was real for a few milliseconds and then vanished.  Effectively:
`confidence` was pure phase coherence in practice, matching the "structural equilibrium ~0.375"
finding above; the ACF peak-ratio signal barely registered downstream.

This same root cause corrupted `_compute_downbeat_confidence()` (analysis mode): its `coh` term
(`sum(coherence_buf)/len(...)`, freshly recomputed) and `base` term (`self._confidence`) were
mathematically identical at call time in the overwhelming majority of frames, since nothing
touches `self._confidence` between the last onset absorption and the downbeat check within the
same beat interval.  The nominal `0.45 * region + 0.30 * coh + 0.15 * base + 0.10 * density`
four-way blend was actually `0.45 * region + 0.45 * (one signal, counted twice) + 0.10 * density`
— phase coherence at ~90% effective weight, region consistency at ~45%, ACF quality contributing
essentially nothing distinguishable from coherence.

**Fix:** two persisted fields, `self._phase_confidence` (refreshed every onset in `_absorb_onset`)
and `self._acf_confidence` (refreshed immediately after `acf_conf` is computed in
`_estimate_tempo_acf`, *before* any of the function's early-return guards — so it updates even on
frames where the guards ultimately reject a BPM change).  `self._confidence` is recomputed as
`0.4 * _acf_confidence + 0.6 * _phase_confidence` at both update sites, so the public property
always reflects the freshest value of both inputs instead of one silently clobbering the other.
`_compute_downbeat_confidence()` now reads `coh = self._phase_confidence` and
`base = self._acf_confidence` directly — four genuinely independent signals as originally
designed. `_reset_tempo_lock()` clears both new fields alongside `self._confidence`.

**Verification:** git-blame traced `_compute_downbeat_confidence` to its introducing commit
(`1e91f4f`, 2026-05-22) — the double-count was present from day one, not a later regression.
Confirmed post-fix with a synthetic 130 BPM onset stream: `_acf_confidence` and
`_phase_confidence` diverge (1.0 vs 0.34 in one run), where pre-fix they were provably identical
by construction.

**2026-08-07 update:** `_acf_confidence`'s own input (`acf_peak_ratio`) had a
separate, independent bug from this one — see "ACF Confidence Excludes
Harmonically-Related Rivals" above. This section is about the two signals
overwriting each other; that one is about how the ACF signal itself was
computed.

---

## Analysis Mode — enabled for supervised testing (2026-07-06)

Decision: `analysis_mode_enabled = true`, `analysis_downbeat_confidence_min` lowered `0.55 → 0.42`

Analysis mode (beat-position map, region consistency, real downbeat-confidence gating on
`is_downbeat`, and a stricter region-consistency check on large tempo-lane jumps) had never run in
production — `analysis_mode_enabled` defaulted `False` and was absent from `config.toml`.  Real
confidence percentiles from three live sessions (`logs/autovj-202607*.jsonl`, 1,832 / 6,216 /
43,434 ticks): p50 0.41–0.47, p75 0.57–0.59, p90 ~0.625.  With phase coherence carrying ~45%
effective weight in the blend (see previous section) and typical values sitting at that median,
the un-fixed formula would gate `is_downbeat` closed on roughly half of all beats at the old 0.55
threshold — since `schedule_for_next_downbeat()` is how BUILD/DROP/IMPACT/CLIMAX transitions
actually fire, that risked the director going silent, not just less precise.

**Fix order matters:** the confidence-blend fix (above) had to land first — enabling analysis mode
against the still-broken formula would have tested a blend where 90% of the "four-way" mix was one
double-counted signal, producing misleading results.  With the blend fixed, `0.42` is set as a
training-start value just below the observed real coherence median, not a validated final number —
there is still no production data on the `region` or `density` terms (analysis mode has never
logged them live).  Revisit this threshold once a supervised session's real distribution is in
hand; see `docs/audits/2026-07-06-vj-training-systems-audit.md` P1-4 / Phase 2 step 8.

---

## Downbeat Confidence Gate — 0.42 → 0.35 → 0.30 after live validation (2026-07-08)

Decision: `analysis_downbeat_confidence_min` lowered `0.42 → 0.35 → 0.30`

The `0.42` training-start value above was never validated against production `is_downbeat` firing
behavior — only against a raw confidence percentile. A new HUD element (a downbeat pulse dot next
to the BPM label, driven directly by `_grid.is_downbeat`) let the operator watch the gate live for
the first time, and it showed `is_downbeat` **not firing at all** in a real session at `0.42` — a
hard failure, not a soft near-miss.

A quantitative pass over ~22k post-fix decision-log ticks (2026-07-06 through 2026-07-08, spanning
56 sessions) confirmed it: `downbeat_confidence` median sits at 0.34–0.60 depending on profile, with
most profiles (hyphy, rap, chillstep, ambient, fire_dj, rock) spending 35–70% of signal-present
ticks in the 0.30–0.42 band — below the old gate for a majority of ticks in exactly the genres this
session's fingerprint work targeted. `0.42` was still too strict even with the blend bug fixed.

The first drop to `0.35` was reported as still producing zero fires across two more sessions. Log
inspection showed this was a false negative, not a real second failure: the first of those two
sessions started *before* the `0.35` edit landed on disk (still genuinely running `0.42`, peak
`downbeat_confidence` 0.37 — correctly below gate), and the second started after the edit but never
exceeded 0.39 (below `0.42`, but the config value is read once at `AutoVJController.__init__` and is
**not hot-reloaded** — a running process, or a subsystem-reload path that reuses an already-parsed
config object, keeps the old gate until the next full app restart). A separate, much longer
(~130 min) session that ran fully under the original `0.42` gate fired `is_downbeat` 54 times with a
healthy confidence distribution (median 0.43, max 0.76) — proof the gate mechanism itself works
given enough stable, confident playback; the two short test clips (19s, 42s) simply didn't run long
enough at the intended threshold to prove anything either way.

Moved to `0.30` regardless, both because it's a safe additional margin below the observed median
floor and because the operator explicitly requested it. **Any future test of this value must
confirm a full app restart happened after the config edit** — config.toml is not hot-reloaded for
this key, and matching an observed max-confidence value against the *previous* gate is easy to
mistake for a real gate failure.

This is a live-only regression: unit tests exercise `_compute_downbeat_confidence()` and the gate
comparison directly, so they couldn't have caught a threshold that's mathematically fine but
empirically miscalibrated against the real signal's distribution. The HUD pulse dot is the intended
detection mechanism going forward — watch it during any future threshold change instead of relying
solely on log percentiles.

---

## Per-Bar `downbeat_fire` Decision-Log Event (2026-07-08)

Decision: log every real `is_downbeat` firing as its own edge-triggered `downbeat_fire` event
(`_maybe_log_downbeat_event()` in `auto_vj.py`), in addition to the existing `detector_tick` field.

While investigating the gate-threshold changes above, a 130-minute session logged only 54
`detector_tick`-visible `is_downbeat=True` reads despite an estimated ~3,036 real bars over that
session (~93 BPM average) — a 1.78% apparent fire rate. The cause: `is_downbeat` is a true one-frame
flag (`grid.update()` resets it to `False` every frame, 60fps), but `detector_tick` is only written
once per second (`_detector_log_interval_s`). The odds of the one throttled log write per second
landing on the exact frame the flag was `True` are ~1/60 — almost exactly the 1.78% observed. Cross-
checking against `downbeat_confidence` (which *holds* its value between bar-checks rather than
blinking, so a 1-second sample is a much better proxy) showed ~53% of samples clearing the 0.42 gate
that session — meaning the real fire rate was likely ~30x higher than the log suggested.

**`detector_tick`'s `is_downbeat` field is not a usable instrument for measuring per-bar rate** and
should not be used for that going forward — use `downbeat_fire` events (one per real firing, with a
monotonic `bar_count`) instead. `detector_tick` remains fine for everything else it captures
(confidence, bpm, lock state) since those persist between samples rather than blinking.

---

## Vocal-Presence Heuristics — HNR + FMR (2026-07-08)

Decision: add `vocal_hnr` / `vocal_fmr` to `AudioData` (computed in `unicornviz/audio/analyzer.py`)
and `vocal_hnr_mu` / `vocal_fmr_mu` to `AudioProfile`, wired into the recommender's `_profile_score()`
at low weight (0.3 / 0.4, vs. 1.0+ for the established fit terms).

**Motivation:** a live Detroit techno track (120-135 BPM, no vocals) was observed locking the
recommender into `hyphy` — traced to two causes. First, `hyphy` (along with `rap`/`r&b`) had no
`bpm_hint_min/max`, so its ACF search ran the full unconstrained range (fixed separately, see the
Audio Profile System section above). Second, and more fundamentally: none of the recommender's
existing signals (spectral centroid, ZCR, onset density, or the 64-band cosine-similarity
fingerprint) measure vocal presence as a concept — they measure time-averaged energy *shape*, and a
bass-heavy instrumental track can match a "sustained vocal plateau" fingerprint just as well as an
actual voice, because nothing in that fingerprint encodes periodicity, harmonicity, or
syllable-rate modulation over time.

**What was added:**

- `vocal_hnr`: a harmonic-to-noise-ratio proxy in the vocal-formant band (300 Hz-3.4 kHz), computed
  per-frame by autocorrelating the log-compressed magnitude spectrum in that band (the standard
  cepstral-pitch trick — a harmonic comb produces a periodic ripple across frequency bins, which
  shows up as an autocorrelation peak at a nonzero lag). Cheap: reuses the FFT the analyzer already
  computes, no extra buffering.
- `vocal_fmr`: fraction of the vocal-band energy envelope's modulation concentrated in 3-8 Hz
  (syllabic/vibrato rate), tracked via a dedicated 40 Hz/2s rolling ring (mirroring the existing
  onset-envelope pattern) and recomputed every 8 frames via a small windowed FFT of that ring.

**Known limitations (validated via synthetic signal tests, not real session data):**

- Neither is a true vocal detector. `vocal_hnr` mainly separates "any pitched/harmonic content" from
  "noise-like content" in that band — it will read high for a synth lead or bassline just as readily
  as a voice. `vocal_fmr` is the stronger genre discriminator in principle (steady 4/4 kick-driven
  modulation sits at the beat rate, ~2 Hz at 120 BPM, well below the 3-8 Hz target band) but showed
  real leakage-driven noise in testing: a synthetic *unmodulated* stationary multi-harmonic tone
  scored ~0.5 (should ideally be near the ~0.25 chance baseline for this band's width), vs. ~0.68 for
  a genuinely 5 Hz-modulated tone and ~0.20-0.26 for noise/wrong-rate modulation — real separation,
  but noisier than hoped on a synthetic edge case unlikely to occur in real audio (which has much
  richer natural dynamics than a pure sum of stationary sinusoids).
- Profile `vocal_hnr_mu`/`vocal_fmr_mu` values (rap/hyphy 0.55/0.50, r&b 0.60/0.55, the 14
  instrumental-dominant profiles 0.35/0.25, `ambient`/`chillstep`/`generic` left uncalibrated) are
  first-pass estimates informed by the synthetic test results, **not validated against real session
  data** the way the spectral fingerprints were. Revisit once live sessions accumulate
  `mean_vocal_hnr`/`mean_vocal_fmr` in the `profile_recommendation` decision-log entries.
- A proper fix would use a pretrained vocal-activity-detection model — deferred as DW-005 in
  `docs/planning/deferred-work-2026-06-18.md` pending evidence this heuristic pair isn't sufficient.

---

## Profile Confusability Pass (2026-07-08)

Decision: `electronic.zcr_mu` lowered `0.065 → 0.052`; `fire_dj.bpm_prior_mu` shifted `148 → 152`.

**Methodology:** rather than eyeballing the full profile table (see
`docs/audio-profile-reference.md`) for similar-looking profiles, wrote a standalone script
(`/tmp/.../scratchpad/confusability.py`, not committed) reusing `_profile_score()`'s exact Gaussian
sigmas and composite weights (tempo/centroid/zcr/onset/spectral-shape/vocal-hnr/vocal-fmr fits;
`band_fit` and `kick_regularity_fit` omitted as they need live per-frame samples, not a static
profile spec). For each profile pair (A, B), built a "canonical track" for A from A's own mu values,
scored it against both A's and B's profile, and took the gap (`self_score_A − cross_score_B`,
averaged both directions) as a confusability metric — smaller gap means a track built exactly to A's
spec still scores nearly as well against B.

**Findings (top 3 closest pairs, before any tweak):**

1. `electronic`/`generic` (gap 0.058) — `spectral_centroid_mu` (1600), `zcr_mu` (0.065), and
   `onset_density_mu` (2.5) were all *identical* between the two, plus 98.1% `expected_bands` cosine
   similarity. `electronic` had accidentally inherited `generic`'s exact scalar targets.
2. `hard_techno`/`fire_dj` (gap 0.071) — identical `bpm_prior_mu` (148), 98.8% fingerprint
   similarity. `fire_dj` is an intentional wide multi-genre catch-all (132-170 BPM) but its center
   point exactly copied `hard_techno`'s instead of sitting at its own range's center (~151).
3. `tech_house`/`electronic` (gap 0.081) — same `zcr_mu` (0.065), close centroid/bpm, 98.5%
   similarity — a secondary symptom of the same `electronic` scalar-target issue as #1.

**Fix:** `zcr_mu` was the one dimension both of `electronic`'s neighbors (`generic` and
`tech_house`) shared at exactly 0.065 — lowering it to 0.052 separates from both simultaneously
without trading centroid/onset distance against either (tested numerically before applying).
`fire_dj.bpm_prior_mu` moved to 152, near the true center of its own declared 132-170 range.

**Result:** re-running the same gap calculation after the tweak: `electronic`/`generic` 0.058 →
0.185 (3.2x), `tech_house`/`electronic` 0.081 → 0.208 (2.6x), `hard_techno`/`fire_dj` 0.071 → 0.093
(fire_dj-mu-only fix; residual closeness here is expected — a broad catch-all profile spanning a
narrow genre's range will always sit somewhat close to it). Neither original top-2 pair got pushed
into a *new* top-3 collision after the fix — the post-tweak ranking's new #1 is still
`hard_techno`/`fire_dj`, followed by `hardgroove`/`breaks` and `hardgroove`/`uk_garage` (both
pre-existing, not introduced by this change).

This pass only touched two scalar values on two profiles; `hardgroove`/`breaks` and
`hardgroove`/`uk_garage` are the next-closest pairs and were not addressed here — flagged for a
future pass if it becomes an issue in practice.

---

## Profile Confusability Pass, Round 2 (2026-07-08)

Decision: `hardgroove.zcr_mu` raised `0.068 → 0.086`.

Follow-up to the round-1 pass above, addressing the next two closest pairs it flagged:
`hardgroove`/`breaks` (gap 0.136) and `hardgroove`/`uk_garage` (gap 0.157). Unlike round 1, there was
no single exact-duplicate value across *all* dimensions — `hardgroove` instead sits centrally
between `breaks` and `uk_garage` on bpm, centroid, and onset (each profile's value bracketing
`hardgroove`'s on both sides), meaning any move on those three dimensions trades separation from one
neighbor against the other. `zcr_mu` was the one dimension not in that three-way sandwich: it tied
`uk_garage`'s exactly (0.068) and sat close to `breaks`' (0.075).

Verified numerically (script from round 1) that lowering `zcr_mu` separates from both neighbors
faster than raising it — but raising was chosen instead: `hardgroove`'s own description ("rolling
tribal percussion... busy hats that want motion") implies *more* noise-like/percussive high-frequency
content than its neighbors, not less. `0.086` was chosen as the smallest value clearing both
neighbors on the same side (not landing symmetrically between them, which would cancel out the
separation gain against whichever neighbor it lands equidistant from).

**Result:** `hardgroove`/`breaks` 0.136 → 0.190, `hardgroove`/`uk_garage` 0.157 → 0.400. Confirmed
via a full re-ranking that neither became a new top-3 collision and no other pair regressed;
`hard_techno`/`fire_dj` (0.093, the accepted residual catch-all overlap from round 1) remains the
closest pair in the roster.

---

## First Direct beat_grid.py Test Coverage — Two Findings (2026-07-08)

Status: documented, not fixed. See `tests/test_beat_tracker_v2.py` / `tests/test_beat_grid_tracker_v1.py`.

Writing the first direct unit tests for `beat_grid.py` (previously zero coverage of either
`BeatTracker` or `BeatGridTracker` themselves — only a path-existence check in
`test_corpus_writers.py`) surfaced two real behaviors worth recording, discovered via synthetic
click-track simulation rather than live-session log analysis:

**1. Silence reset does not clear the onset envelope.** `_reset_tempo_lock()` (fired after
`silence_reset_s` of no onsets) clears `bpm`/`confidence`/`phase`/`candidate_history`/
`beat_position_map`/`tempo_hold_until_t`, but never clears `_env_buf`/`_env_write_idx`/
`_env_filled`. Since the onset envelope is an 8-second ring (`_V2_ENV_WINDOW_S`), a periodic ACF
re-estimation running shortly after the reset can still find the pre-silence onset pattern still
resident in the ring and re-lock onto it — confirmed via simulation to happen within under a
second of the reset firing, well before any new real onset has arrived. This likely undermines the
intended purpose of the silence reset (clean state for the next song) for up to ~8s after a gap
begins. Not fixed here — flagging for a decision on whether `_reset_tempo_lock()` should also clear
the envelope ring, at the cost of losing a few seconds of legitimate cross-fade audio history for a
song that resumes quickly.

**2. Phase confidence has no explicit initial sync.** On first BPM lock, the phase oscillator
(`self._phase`) starts wherever it was left (0.0 from `_reset_tempo_lock`/`__init__`), not
synchronized to the actual onset that triggered the lock. `_absorb_onset`'s phase-coherence nudge
only activates once an onset already lands within ±18% (`_V2_PHASE_TOL`) of the current phase, so
if the initial offset is larger than that, the phase can only drift into tolerance opportunistically
via the small BPM-estimate error against true tempo, not through any deliberate re-sync step.
Simulated on a perfectly steady, unambiguous 120 BPM click track: `acf_confidence` reached ~1.0
within ~4s of the first lock, but `phase_confidence` (and therefore the blended `confidence`, and
`downbeat_confidence`'s 30%-weighted `coh` term) took **30-50s** to converge to a comparable level.
This is a plausible structural contributor to the "downbeat gate sits below threshold for extended
stretches even on confidently-locked material" pattern observed in the 2026-07-08 downbeat-gate
investigation above — not the whole explanation (that investigation also found genuine per-genre
struggle concentrated in chillstep/hyphy), but a mechanism that would affect every genre equally
for the first 30-50s after any fresh lock (track start, tempo change, or post-silence re-lock).

Re-entry trigger: revisit if live sessions show downbeat scheduling feels sluggish specifically in
the first ~30-50s after a track starts or after silence, which would corroborate finding #2 as a
practical (not just theoretical) problem.

---

## Recommender Confirm/Decider Margin — softmax-normalized (2026-07-06)

Decision: `profile_auto_reco_score_margin` and `profile_auto_reco_decider_min_margin`
default `0.25 → 0.09`; margin is now a softmax probability margin, not an additive score gap

**Problem:** the confirm gate (`margin >= profile_auto_reco_score_margin`) and decider gate
compared the raw additive composite score gap between the best and current profile.  This
composite has no fixed scale — it's a weighted sum of Gaussian log-likelihood terms, cosine
similarities, and rate fractions (see the weight list in the LLM tuning prompt) whose total spread
depends entirely on how distinguishable the candidate profiles are on the current material.  Real
logged `top_candidates` scores across two sessions (5,734 samples) show best-vs-second-best
margins ranging from 0.06 (p10) to 2.17 (p90) — a single fixed `0.25` threshold means very
different things depending on how spread-out the scores happen to be on a given genre.

**Fix:** the margin used for confirm/decider gating is now `best_prob - current_prob` from a
numerically-stable softmax over the raw composite scores (`exp(s - max_s)`, normalized).  This
bounds the margin to `[0, 1]` and makes it a genuine "how much more likely is the best candidate"
quantity, comparable across sessions regardless of the raw score spread.  `score_current` /
`score_recommended` in HUD display, logging, and the LLM tuning prompt remain the raw additive
values unchanged — the LLM prompt's weight-recommendation reasoning (`tempo_fit × 2.0`, etc.)
operates on that additive scale and would break if it were softmax-transformed too.  Only the
gating margin changes representation.

**New default derivation:** rather than guess a new threshold, the old `0.25` additive default was
located at the 31.3rd percentile of the 5,734 real logged margins; the softmax-margin value at that
same percentile (computed on the same real score arrays) is `0.0915`, rounded to `0.09`.  This
preserves the system's actual historical permissiveness — operators who were happy with how often
the decider fired under `0.25` should see materially the same firing frequency under `0.09`, just
expressed in a scale-stable unit going forward.

Also fixes a related bug: `current_score = dict(candidates).get(current_key, best_score)` fell back
to `best_score` when the active profile key wasn't among the scored candidates, silently collapsing
margin to 0 and permanently blocking the decider.  Both the raw-score fallback (for display) and the
new probability fallback (for gating) now use the second-best candidate instead.

Full analysis: `docs/audits/2026-07-06-vj-training-systems-audit.md` P2-6 / P2-7.

---

## Recommender Weight Promotion + Manual-Override Label (2026-07-18)

Decision: composite-score weights (`_DEFAULT_RECO_WEIGHTS`) are now overridable
by a promoted file; manual profile overrides are tagged for offline training.

- `_load_recommender_weights()` reads `drop-ins/auto-vj-01/weights/
  recommender-weights.json` at controller init, overriding only recognized
  keys; missing/malformed → code defaults, unchanged from before this change.
- `cycle_profile()`'s manual-switch branch now passes
  `reason='manual_override'` into the `profile_switch` sequence-corpus
  keyframe — a pure additive label, no change to switching behavior itself.

Full design + the offline fit/promote workflow: `docs/adr/training-model.md`
§ "Target-Label Mechanism" and § "Recommender Weight Promotion" (this is a
training-pipeline concern; this entry exists here only because both touch
`auto_vj.py` runtime code the header above requires tracking).

---

## Superseded Decisions

| Date | Decision | Reason for reverting |
| ---- | -------- | -------------------- |
| 2026-06-20 | `tactus_preference_ratio = 0.42` (global) | 0.75× fold mapped 120 → 90 BPM for house; removed in same session |
| 2026-06-20 | `chill` preset `mode_entry_min_confidence = 0.50` | Too high for chillstep confidence distribution; lowered to 0.38 |
| 2026-06-20 | `auto_profile_raver_min_bpm = 128.0` | Peak_time material at ~127.7 BPM always triggered normie; lowered to 126.0 |
| 2026-06-20 | `_BPM_LOCK_CONFIDENCE = 0.52` | house/c churn 612/hr with conf median 0.500 — oscillating across gain threshold; raised to 0.55 |
| 2026-06-20 | house `bpm_prior_sigma = 0.20` | Too peaked; depressed confidence on tracks at 120 or 128 BPM when prior is 124; widened to 0.35 |
| 2026-06-20 | `auto_profile_switch_cooldown_s = 60.0` | Chillstep crossfade-off: 23 switches/43 min; raised to 120 s |
| 2026-06-21 | BPM hint-range clamp in `_maybe_auto_switch_profile()` | Clamping BPM to `bpm_hint_max` prevented mood from ever escaping chill when playing wrong-genre playlist (peak-time at 127 BPM clamped to 108 → stuck in chill forever); the 120 s cooldown alone is sufficient protection against crossfade-off blips |
| — | BeatTracker v1 as primary engine | v2 ACF is more robust; v1 kept as fallback only |
| 2026-05-22–2026-07-06 | `_compute_downbeat_confidence()` reading `base = self._confidence` | Identical to `coh` in practice — never an independent third signal; replaced with genuinely independent `_acf_confidence` (see Confidence Blend Bug section) |
| — | `_V2_ANALYSIS_DOWNBEAT_CONFIDENCE_MIN = 0.55` | Never validated against real data; real coherence medians run 0.41-0.47, so 0.55 would have gated `is_downbeat` closed on roughly half of all beats. Lowered to 0.42 as a training-start value (see Analysis Mode section) |
| — | `profile_auto_reco_score_margin` / `_decider_min_margin = 0.25` (additive score gap) | Unbounded scale meant different things across genres (real margins observed 0.06-2.17); replaced with a softmax probability margin, rescaled to 0.09 at the equivalent historical percentile (see Recommender Confirm/Decider Margin section) |
| 2026-07-18–2026-08-04 | `set_profile()` narrowing `_bpm_min`/`_bpm_max` from `bpm_hint_min`/`bpm_hint_max` (all engines; v3 kept applying it even while confidently locked) | The dominant "BPM tending hot" mechanism, not the prior re-prime the 2026-07-18 fix addressed — a wrongly-applied profile could permanently hide the true tempo from the search, self-confirming the wrong profile. Removed entirely (P0-A); see BPM Detector Audit section above |
| 2026-08-04–2026-08-06 | Recommender `_profile_score()` sigma floor `max(0.45, ...)` | P2-E's premise (two disagreeing sigma floors is itself a bug) was wrong -- they're different concerns. Live session showed psytrance still winning at 30 BPM off its mu despite correctly-favoring spectral-shape fit; reverted to `max(0.08, ...)` (see Recommender Sigma-Floor Revert section) |
| 2026-06-18–2026-08-05 | `IMPACT` as a held state, earned via a mid-groove score re-check after a delay (`impact_trigger_score`/`impact_min_delay_s`/`impact_max_delay_s`) | Didn't correspond to anything in real song structure — imposed a fixed DROP→IMPACT→CLIMAX staircase on every drop cycle regardless of the track. Folded into DROP as a fixed-duration entry flourish for a later drop, decided once at fire time; see Phrase-Aware Director section above |
| 2026-08-05–2026-08-09 | `CLIMAX` reachable only via `IMPACT` (the only `_enter_climax()` call site was inside the `_mode == _IMPACT` branch) | IMPACT was never meant to be a CLIMAX prerequisite, only the major-tier drop's own entry flourish — the two were structurally fused with no stated reason. `climax_worthy` (gate logic unchanged) now evaluates directly from DROP, guarded by a reused `impact_hold_s` minimum-time-since-fire floor instead of requiring IMPACT's specific state transit; see Director/Detector/Recommender Refinement Batch section above |

---

## Defaults Baked into Code from config.toml (2026-07-13)

As part of the config.toml consolidation (promote operator-tuned values to code
defaults, then strip the file to non-defaults), these `[auto_vj]` values — long
carried as config overrides — were promoted to their **code defaults** in the
`auto-vj-01` drop-in and removed from `config.toml`.  Values unchanged; only the
*source of truth* moved from config to code.

| Key | Old code default | New code default | File |
| --- | --- | --- | --- |
| `tempo_hold_s` | 6.0 | **10.0** | `beat_grid.py` |
| `silence_reset_s` | 2.0 | **15.0** | `beat_grid.py` |
| `auto_profile_enabled` | False | **True** | `auto_vj.py` |
| `auto_profile_chill_max_bpm` | 110.0 | **105.0** | `auto_vj.py` |
| `auto_profile_raver_min_bpm` | 136.0 | **126.0** | `auto_vj.py` |
| `auto_profile_switch_cooldown_s` | 20.0 | **120.0** | `auto_vj.py` |
| `auto_profile_hold_s` | 0.0 | **8.0** | `auto_vj.py` |

Rationale for the values is documented in the Tempo Hold and Auto-Profile Raver
Threshold sections above; this entry records that they are now defaults, not
overrides. `auto_vj.log_decisions` was intentionally *not* baked (kept in
config.toml).

---

## VJ Mood Profile Effect-Tag Vocabulary Fix (2026-07-13)

**Bug:** the director was reported as spending a disproportionate amount of time
on psychedelic-style effects ("stuck in the psychedelics").

**Root cause:** each mood profile's per-scene `*_effect_tags`
(`cruise`/`breakdown`/`drop`/`impact`/`climax`, resolved via `_profile_value()`
from `_PROFILE_PRESETS`) requested a tag vocabulary — `ambient`, `audio`,
`futuristic`, plus `psychedelic`/`classic`/`art`/`particles`/`neon` — that
barely overlapped with real effect `TAGS` (category/style words like `tech`,
`cosmic`, `retro`). `ambient`, `audio`, and `futuristic` matched **zero**
effects. `psychedelic` was the one tag common to nearly every drop/impact/
climax list, so `goto_random_effect`'s tag filter collapsed to the same ~5
psychedelic-tagged effects whenever a drop, impact, or climax fired.

**Fix (two parts, both landed):**

1. All 44 rotation effects were given one-or-more **mood tags** — `chill`,
   `groovy`, `energetic`, `intense`, `hard` — layered on top of their existing
   category tags. See `docs/planning/vj-mood-tag-rollout.md` for the full
   per-effect assignment (owner Q&A-confirmed, scripted apply, cross-checked
   with zero drift).
2. Each mood profile's per-scene `*_effect_tags` in `_PROFILE_PRESETS` were
   replaced with mood-vocabulary requests (owner-specified per profile):

   | Scene | chill | normie | raver |
   | --- | --- | --- | --- |
   | cruise | chill, groovy | chill, groovy, energetic | groovy, energetic |
   | breakdown | chill | chill, groovy | chill, groovy |
   | drop | groovy, energetic | energetic, intense | energetic, intense |
   | impact | intense, energetic | intense, hard | intense, hard |
   | climax | energetic, hard, intense | energetic, hard, intense | energetic, hard, intense |

3. A safety-net fallback was also added in core (`vj_api.goto_random_effect`):
   when no *enabled* effect matches the requested tags, fall back to any
   enabled effect instead of returning `None`, so a future tag gap can never
   strand the director again.

**Verified:** every scene across all three profiles now matches 16–40 of the 44
rotation effects (was ~5 for every drop/impact/climax before). Regression test:
`tests/test_effect_mood_coverage.py` (main repo) asserts full mood-tag coverage.

---

## Open Questions

- **2026-08-14, flagged not fixed:** `prime_tempo()`'s "external ground
  truth is always authoritative" assumption (P0-B,
  `docs/audits/2026-08-04-bpm-detector-audit.md`) failed on a real
  track. "Keep Moving (Original Mix)" – Jsphn, dj-mixer-sourced:
  `mixer_bpm` populated at `t=4.5s` with `77.05`, and `bpm` (v3) jumped
  to the exact same value in the same tick and stayed there at `0.90`
  confidence for the rest of the observed window (52s of corpus data).
  Meanwhile `bpm_shadow` (v2, never primed) held steady at `126.53` the
  whole time, and v3 itself had been reading `129.18` at `0.82-0.85`
  confidence for the 4.5s right before the prime hit — a perfectly
  healthy audio-driven lock, overwritten by an external tag with no
  sanity check against it. `126.53`/`77.05` isn't a clean octave
  relationship (`1.64×`, not `1.5×`/`2×`), so this doesn't look like a
  correctable half/double-time case — it looks like the mixer's own
  stored BPM tag for this track is itself wrong (plausibly its own
  half-time misread), and `prime_tempo()` has no defense against that:
  confidence is only ever raised, never lowered, and the tempo-hold
  window is explicitly designed to resist the ACF fighting back
  ("Refreshes the tempo-hold window so the ACF's own continuity guards
  don't immediately fight the primed value on the next update"). Comb
  filtering (`_V2_COMB_HARMONICS`, `_estimate_tempo_acf()`) is what
  correctly found `129.18` in the first place — it isn't a comb-filter
  failure, it's `prime_tempo()` overriding a working comb-filter result
  with a wrong external number. Worth a design conversation (e.g. some
  sanity check when the primed value is far from a currently-high-
  confidence estimate and not a harmonic multiple of it) but not touched
  here — a real detector-trust-model change, not a constant tweak, and
  the standing flag-and-confirm policy applies. **Addendum, same day:**
  replayed the same track later in an unprimed (media-01-only) session
  — clean, consistent `125.42` BPM, v3/v2 exact agreement, confirming
  the detector's own read was right both times. Recommended direction
  discussed with the owner: not a 50/50 blend (still rewards a wrong
  tag, just less) and not a blanket "is the mixer garbage" check (no
  way to know in advance) — a **gate**: keep `prime_tempo()`'s full-trust
  behavior when there's nothing to contradict it, but skip the override
  (or accept it without the confidence floor, so audio evidence can
  immediately out-vote it) when the detector already has a confident,
  converged estimate that the primed value doesn't roughly match or
  isn't a clean harmonic of. Not implemented — recorded here as the
  agreed direction for whenever this gets picked up, not a decision to
  build it now.
- **2026-08-14, flagged not fixed:** `downbeat_regularity`'s real
  contribution to the confidence blend (rc.56) is still not isolated
  from `_V2_PHASE_TOL`'s own effect by a controlled test — both changed
  in the same commit, and the live A/B evidence available (shadow vs.
  active) is confounded by both trackers sharing the same blend code
  (see the 2026-08-14 session summary above). Recommended next step if
  this gets revisited: a synthetic click-track test that isolates
  `downbeat_regularity`'s weight alone, not another round of live
  session comparison.
- Should `tactus_preference_ratio` be per-AudioProfile rather than a global config key?
- Consider widening `phase_tol` to 0.22 to nudge the natural equilibrium above 0.40 (now closer to the 0.55 gain threshold).
- ~~`centroid_fit`'s Gaussian used a fixed 400 Hz sigma for every profile~~
  — **resolved 2026-08-06**, see "Per-Profile Centroid Sigma + Accuracy
  Tracking Tier 1" above. Added `spectral_centroid_sigma` as a coarse
  tight/medium/wide tier per profile, not yet a fitted value — replacing
  the three tier numbers with fitted ones once Tier 2 accuracy data exists
  is the follow-up, still open.
- Sigma tightening in the same review only covered 3 of the 4 originally
  flagged outliers (`breaks`, `rap`, `synthwave`); `fire_dj` was
  intentionally left alone. Whether the remaining ~17 profiles' sigmas
  warrant a fuller consistency pass (beyond the ad hoc sigma-to-hint-span
  comparison used this round) is still open — no fitted/measured accuracy
  signal exists yet to validate against (see
  `docs/planning/auto-vj-recommender-accuracy-tracking-2026-08-06.md`,
  proposed but not yet implemented).
