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

> **Superseded the same night** — see "One-Way Flow: Recommender→Detector
> Genre Coupling Cut Entirely" below. Option (a) was tried literally (a
> fully flat ACF prior) and found unsafe; the actual fix landed was
> neither (a) nor (b) as scoped above, but removing genre priming from
> the live pipeline entirely, at any point in a track's timeline.

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

## One-Way Flow: Recommender→Detector Genre Coupling Cut Entirely (2026-08-14, later still)

Direct continuation of the cold-start-priming investigation above, same
night. Owner's response to the two options recorded there (decay the
prior back toward uniform over time, or don't prime at cold start at
all): pushed back hard on both, pointing out an apparent contradiction —
"we already fixed this" (recommender has zero influence post-lock)
immediately followed by "genre bias can still apply pre-lock." Owner's
read: **that's not two different things that happen to coexist, it's one
architectural mistake** — detector and recommender should be a strict
one-way flow, detector feeding recommender, never the reverse, full stop.
Not a decaying nudge (rejected the proposal above outright), not a
gated-but-still-real prime — a true cut.

**Agreed, and it's a materially better fix than either option this ADR
had on the table.** Both prior options preserved *some* form of genre
writing back into the detector; the owner's framing removes the entire
class of bug at the root instead of bounding its blast radius.

**Tried option (a) literally first, found it unsafe.** Made
`beat_grid.py`'s `_setup_acf_arrays()` build a fully flat (`np.ones_like`)
`_acf_prior` instead of the generic `120 BPM, σ=0.55` Gaussian it builds
today. Result, run against the existing test suite:

- A plain, unambiguous 120 BPM click track locked onto **61.22 BPM** — a
  clean half-tempo (octave) error.
- `test_locked_bpm_does_not_drift_toward_mismatched_profile` (the
  regression test validating the detector resists a wrong profile) got
  **worse**, not better: BPM drifted to `75.83` instead of holding near
  `124`.

Root cause: the *generic* (non-genre) cold-start prior was doing real
work the raw comb-filter can't do alone — resolving octave/harmonic
ambiguity, a well-known limitation of autocorrelation-based tempo
detection. Removing all bias removed that too. **Reverted** — this was
never committed; both repos were confirmed clean before moving on.

**Actual fix: keep the generic prior, cut genre-specific priming
entirely, at any point in a track's timeline.** The generic
`120 BPM, σ=0.55` prior in `_setup_acf_arrays()` is untouched — it isn't
genre-specific (not tied to any profile's `bpm_prior_mu`) and its
octave-disambiguation job is real and necessary, confirmed by the
experiment above. What's removed is the only path that ever pushed a
*genre-specific* profile into the tracker:
`AutoVJController._sync_grid_audio_profile()`, along with its two call
sites and the five now-dead bookkeeping attributes it alone used
(`_last_audio_profile_key`, `_audio_profile_candidate_key`,
`_audio_profile_candidate_since_t`, `_audio_profile_sync_hold_s`,
`_audio_profile_sync_min_confidence`). `BeatTracker.set_profile()` /
`BeatTrackerV3.set_profile()` are unchanged and still directly
unit-tested — only their live wiring from the recommender is gone. The
decider's own bookkeeping reset (`_maybe_apply_recommended_audio_
profile()`, formerly commented "Do NOT push to the BPM tracker here...")
is simplified to match: `AudioManager.set_profile()` still updates the
profile key and the analyzer's spectral-feature setup
(`Analyzer.set_profile()`, unrelated to tempo, used for
`centroid_fit`/`spectral_shape_fit` measurement) — it just never reaches
the beat tracker.

`prime_tempo()` (external ground-truth BPM, e.g. dj-mixer's own
per-track analysis) is a completely separate mechanism and untouched —
that's real, independently-measured evidence being fed in, not the
recommender's own genre guess, and stays a legitimate one-way channel
into the detector.

**Why this is strictly better than the "decay" idea floated earlier:**
the detector's floor `_MIN_PROFILE_PRIOR_SIGMA = 0.45` was validated
(2026-08-06 revert, `test_bpm_detector_audit_regressions.py`) specifically
against a scenario where a genre prior gets applied *after* real tempo
evidence already exists mid-track — exactly what a decaying post-lock
nudge would have reintroduced, reopening a risk that test was written to
close. Cutting the coupling entirely sidesteps that tension rather than
re-litigating it: with no genre-specific prior ever applied to the
detector, `_MIN_PROFILE_PRIOR_SIGMA` has no live case left to bind
against — see its own entry in `weights-and-thresholds.md` for the
"now inert" note.

**Two related recommender-side changes, same session, same reasoning
pass:**

- **`band_fit` retired.** Asked directly ("should we eliminate band
  fit?") while reviewing the composite term formulas: `band_fit` was a
  coarse 3-band (bass/mid/treble energy-weight) L1 distance against a
  profile's `bass_weight`/`mid_weight`/`treble_weight` — conceptually the
  same frequency-distribution signal `spectral_shape_fit`'s 64-band
  cosine similarity against `expected_bands` already measures at far
  higher resolution, without `band_fit`'s coarseness. Combined weight on
  one underlying signal was `1.2 + 1.2 = 2.4`, more than `tempo_fit`'s own
  `2.0` — double-counting, not two independent signals. Removed the term,
  its weight entry, and the now-unused `band_triples`/per-sample
  bass-mid-treble accumulation feeding it.
- **`centroid_fit` `0.7 → 0.5`.** Owner: "lower centroid to .5 for sure."
  Directly justified by this same night's ambient-misclassification
  term-attribution table (see the Live Session Follow-Up entry above):
  `centroid_fit` supplied `+0.84` of ambient's average `+0.99`
  wrong-answer margin, the single dominant driver, tracing to the
  still-open 2026-08-11 formula-mismatch bug (linear-FFT live measurement
  vs. log-band-derived `spectral_centroid_mu`). Not a fix of that bug —
  still open. Owner's plan going forward: monitor `centroid_fit` against
  real, non-DJ-edit web-player session data (the exact source that
  surfaced tonight's whole investigation) before tuning it further.

**Recommender tempo sigma floor unclamped: `0.08 → 0.02`.** Owner: "yes
unclamp and drop the floor to 0.02. do now." The sigma-matches-hint-band
pass earlier the same night (see that entry above) had computed each of
16 profiles' true hint-band-derived sigma, but 11 came out tighter than
the then-current `0.08` recommender floor and were rounded *up* to `0.08`
during authoring — specifically so the stored number wouldn't diverge
from what would actually bind. That rationale no longer applies at the
same strength once the detector/recommender coupling above is cut: the
floor's only remaining job is the recommender's own scoring sharpness.
Promoted the bare `0.08` literal to a named constant,
`_TEMPO_FIT_SIGMA_FLOOR = 0.02` (auto_vj.py), safely under every real
profile's true value (tightest: `dubstep` at `0.0218`), and unclamped all
11 affected profiles in `unicornviz/audio/profiles.py` back to their true
computed sigma (4-decimal precision, since several distinct genres —
e.g. `trance` `0.0446` vs. `hardstyle` `0.0481` — would otherwise collapse
onto the same 2-decimal value). See `weights-and-thresholds.md`'s profile
sigma table for the full before/after.

**Verified:** full suite green (1696 tests) after all four changes,
including a new source-text guard
(`test_recommender_never_pushes_a_profile_into_the_beat_tracker`) that
fails if `_sync_grid_audio_profile` or a `self._grid.set_profile(`/
`self._shadow_grid.set_profile(` call site reappears in `auto_vj.py`, and
an updated sigma-floor guard test for the new `0.02`/named-constant form.
`_DETECTOR_VERSION` → `1.0.0-rc.20` (the live behavioral change lives in
`auto_vj.py`, not `beat_grid.py`, but the detector subsystem's actual
behavior changed — bumped on the spirit of the versioning rule, not the
letter). `_RECOMMENDER_VERSION` → `1.0.0-rc.12`. `_VJ_WEIGHTS_DOC_VERSION`
→ `39`. `auto_vj.py` `__version__` → `1.0.0-rc.61`.

---

## Downbeat Regularity Logging + Confidence Blend Re-Tune (2026-08-14, later still again)

Owner live-tested the one-way-flow cut immediately after it landed and
reported it reads "way off" on the current run — but also, unprompted,
recognized this as the detector finally being genuinely isolated for the
first time, and reasoned through why the old two-way coupling had
existed at all: some material (their example: Daft Punk's "One More
Time," which has very little audio energy in the kick/bass region for
long stretches) plausibly needs the detector to *listen differently*, not
just get a different tempo number handed to it.

**Answered, not implemented:** that's two different kinds of "genre
influence," and only one was ever the bug. Value-bias (a profile's
`bpm_prior_mu`/`sigma` nudging the search toward a specific number) is
what got removed — it can't help, it can only mislead, since it's a
guess made with the least evidence the recommender ever has. Method
adaptation (listen differently based on what's actually audible) is a
real, separate idea — and the detector already has a version of it,
driven by *measurement* rather than a genre label: `kick_regularity` (an
observed signal, not a guess) already auto-tightens the tactus
fold-down's eagerness as measured kick regularity falls
(`_effective_tactus_ratio()`). Whether that existing mechanism is enough
for genuinely kick-sparse material, or needs to go further, is an open
question — not pursued further this session pending a concrete failure
case (right BPM but low confidence? wrong BPM entirely? bouncing?) rather
than a plausible-sounding theory, given how many theories this exact
investigation has needed to verify against real data before trusting
them.

**Key detection, separately asked:** would it help resolve the octave
(60/120/240 BPM) ambiguity discussed earlier? No — key/pitch and
tempo/rhythm are orthogonal musical dimensions. The octave-disambiguation
job is already done by the comb-filter's own harmonic-summing (fundamental
plus up to 3 harmonics, `_V2_COMB_HARMONICS`) plus the generic,
genre-agnostic cold-start prior (`120 BPM, σ=0.55`) — both purely
rhythmic mechanisms.
Key information wouldn't add anything to that specific problem.

**Real gap found while explaining the confidence-blend math: `downbeat_
regularity` (the blend's third term) was never independently logged.**
Only `downbeat_confidence` was — a *different*, composite metric that
already has phase/acf baked in (30%/15%, per `_downbeat_regularity()`'s
own docstring warning against confusing the two). Added `BeatTracker.
downbeat_regularity`, a cached property mirroring `acf_confidence`/
`phase_confidence`'s existing exposure pattern (both call sites of the
blend now stash the freshly-computed value in `self._downbeat_regularity_
value` before using it), and a matching `_detector_snapshot()` field in
`auto_vj.py`.

**Pulled real numbers immediately, from the live-running session**
(`logs/autovj-*.jsonl`, 1118 locked rows, 25 min in):

| Term | Weight (was) | Mean | stdev | Range |
| --- | --- | --- | --- | --- |
| `acf_confidence` | 0.6 | 0.63 | 0.25 | 0.12–1.00 |
| `phase_confidence` | 0.2 | 0.32 | 0.14 | 0.00–0.89 |
| `downbeat_confidence` *(proxy, not the real blend term)* | 0.2 | 0.51 | 0.11 | 0.00–0.82 |

Per-track breakdown showed no clean "improves over the session" trend
(first-half mean confidence `0.573` vs. second-half `0.533`, actually
lower) — variance tracks per-track material, not elapsed time.
`phase_confidence` sitting at `~0.32` mean, essentially unchanged from
the `~0.3-0.4` cap the 2026-08-11 investigation found, despite the
band/strength-weighted phase-coherence rework (`_V2_PHASE_STRENGTH_
SATURATION`) landing in between — that rework was supposed to be "the
real fix" for exactly this. It measurably helped (validated live at the
time: BPM/genre correct from the first song), but the underlying cap
persists.

**Working theory for the cap, not yet confirmed:** `phase_confidence` is
a weighted hit-rate — every onset's weight (`band_weight × saturating
strength`) counts fully in the denominator whether it hits or misses,
and only counts in the numerator on a hit. A strong, bass-weighted onset
that's a legitimate syncopated bass stab or subdivision (common in
house/techno-family material — this project's primary test genres, not
an edge case) drags the ratio down exactly as hard as a real lock error
would, because the metric can't distinguish "wrong lock" from "correct
lock, syncopated bassline." If true, this is a structural ceiling on the
metric itself for this material, not a bug in the weighting logic — the
weighting already correctly protects against irrelevant (treble/weak)
onsets, it just can't protect against relevant-but-legitimately-off-grid
ones. **Flagged as open, not fixed.**

**Weight re-tune, landed:** `0.6/0.2/0.2 → 0.65/0.1/0.25` (ACF/phase/
downbeat_regularity) — `phase_confidence`'s share trimmed to `0.1` to
reflect that it isn't discriminating as strongly as the other two, freed
weight split evenly onto `acf_confidence` and `downbeat_regularity`
(`+0.05` each), both of which showed real dynamic range in the same data
pull. Framed explicitly by the owner as *not* a fix for the phase cap —
"lowering the expectations for confidence" given a known structural
weakness, versus solving the weakness itself.

**Verified:** full suite green (1698 tests) after both changes,
including 2 new tests for the new `downbeat_regularity` logging field, 1
updated test for the new blend ratio (renamed from
`test_confidence_blend_is_six_two_two` to reflect the new weights), and a
new assertion that the property reads back the exact value the blend
computation used. `_DETECTOR_VERSION` → `1.0.0-rc.21`,
`_VJ_WEIGHTS_DOC_VERSION` → `40`, `auto_vj.py` `__version__` →
`1.0.0-rc.62`.

---

## BPM-Value Accept/Reject Gate Stack: Promoted, Retuned, Chicken-and-Egg Fixed (2026-08-14, later still again)

Direct continuation of the garbage/k carry-over incident. Owner asked a
precise question that reframed the whole night's confidence-tuning work:
"is there a separate place the actual bpm is being derived?" — suspecting,
correctly, that tonight's confidence-blend re-tuning had never touched
whatever actually decides the published BPM *value*.

### Where BPM value actually comes from, and why confidence-tuning never touched it

Traced in full: `_estimate_tempo_acf()` computes a fresh candidate every
cycle regardless of confidence, but a **separate, raw, per-cycle number** —
`acf_conf` (`min(1.0, acf_peak_ratio/3.0)`, cached as `self._acf_confidence`
and exposed via the `acf_confidence` property) — gates whether that
candidate is ever accepted as the new `self._bpm`. This is **not** the
published `self._confidence` blend (0.65/0.1/0.25 ACF/phase/downbeat_
regularity, tonight's earlier work). Two different numbers computed in the
same method, doing completely different jobs. The full accept/reject gate
stack a fresh candidate has to clear, every one keyed on `acf_conf`, never
`self._confidence`:

1. Startup/update floor (`acf_conf` vs. `_min_update_confidence`/
   `_startup_confidence` depending on cold vs. locked).
2. Tempo-hold window — refused outright if `acf_conf >= 0.45` while inside
   `_tempo_hold_until_t`.
3. Candidate persistence (P5 hardening) — must reappear ≥3 consecutive
   cycles, spread ≤4 BPM.
4. Large-jump guard — outside the lock band, requires
   `acf_conf >= _large_jump_confidence`.
5. Region-consistency guard (Mixxx-inspired) — see the chicken-and-egg
   fix below.
6. Low→fast lane guard — extra-strict confidence for a ≤115→≥130 jump.
7. EMA smoothing, capped at `_max_bpm_step` per accepted update.

**Answer to "is confidence-tuning why we broke this": yes, but the exact
mechanism is already gone.** Before tonight's earlier one-way-flow cut,
`AutoVJController._sync_grid_audio_profile()` gated its push into the beat
tracker on the *published* `self._confidence` (`if conf <
self._audio_profile_sync_min_confidence: return`, default `0.35`). Every
past confidence-blend increase (the 0.4/0.6 → 0.5/0.5 → 0.7/0.3 → 0.8/0.2 →
0.6/0.2/0.2 progression, spanning 2026-08-10 through tonight) made that gate
clear *more* easily/often — meaning more frequent genre-profile pushes into
the detector's ACF prior, each one a chance to corrupt BPM search via wrong-
genre bias, exactly the mechanism the one-way-flow cut removed a few hours
earlier the same night. The "obtuse feedback loop" the owner suspected was
real, named precisely, and already closed — just not connected to this
specific worry until asked directly. Confirmed: with `_sync_grid_audio_
profile()` gone, `self._confidence` no longer has *any* path back into BPM
value determination, even indirectly through the recommender (the
recommender's own `manager.set_profile()` call only reaches `Analyzer`, not
the beat tracker, as of the one-way-flow cut).

### Ten constants promoted, five retuned

All ten gate-stack thresholds were bare `cfg.get(key, LITERAL)` defaults in
`BeatTracker.__init__` — invisible to `weights-and-thresholds.md`, to
`training-kit-01`'s LLM tuning prompt, to everything. Promoted to named
`_V2_*` module constants (same pattern as `_V2_PHASE_TOL` etc.), and five
retuned per direct owner review — see `weights-and-thresholds.md`'s new
"BPM-value accept/reject gate stack" section for the full table and
per-constant rationale (`_V2_STARTUP_CONFIDENCE` `0.55→0.3`,
`_V2_LARGE_JUMP_CONFIDENCE` `0.72→0.5`, `_V2_LOW_BPM_FAST_CONFIDENCE`
`0.80→0.45`, `_V2_MAX_BPM_STEP` `3.0→5.0`,
`_V2_ANALYSIS_REGION_CONFIDENCE_MIN` `0.58→0.40`). Owner's explicit framing:
first-cut values pending real data now that the stack is actually visible —
"we're going to have to tune & inspect this whole damn thing with a
microscope."

### The region-consistency chicken-and-egg (fixed)

Gate 5 previously required **both** `acf_conf >= large_jump_confidence`
**and** region-consistency (recent beat positions must also fit the new
candidate) — AND logic. But recent beat positions are necessarily built
under the *old* tempo; a genuinely new tempo can never have history
consistent with it until it's already been accepted. This made gate 4
nearly pointless for real track-boundary jumps: no matter how strong the
ACF evidence, gate 5 would reject anyway, because "region-consistent with
a tempo that has zero history" is not a thing that can happen.

**Verified directly, not just reasoned through:** forced the pre-fix AND
logic back in (temporary monkeypatch, not committed) and ran a tracker
locked at 83 BPM through 90 seconds of clearly-different 123 BPM material —
BPM stayed **bit-exact at 83.33 the entire time**. With the fix (AND → OR:
strong direct confidence is now sufficient on its own; region-consistency
remains a valid *alternate* path for smaller, confidence-borderline drifts)
— same scenario, BPM moved substantially away from the stale lock. Real
regression test: `test_large_jump_gate_no_longer_freezes_forever_across_a_
track_change` (`tests/test_beat_tracker_v2.py`).

### Found while testing, not resolved: cold-start vs. transition asymmetry

The OR fix demonstrably breaks the permanent freeze, but the jump doesn't
cleanly land on the correct new tempo either. Controlled comparison:

- **Cold start** (fresh `BeatTracker`, no prior lock, straight onto ~123
  BPM material): converges correctly, `~124 BPM`.
- **Transition** (locked at 83 BPM, then fed the *same* ~123 BPM material):
  drifts toward a slower subdivision instead (a clean noiseless click track
  drifted to `~74-80 BPM`; the same material with light jitter reached only
  `~107 BPM` after 90s, still short of 123).

Same underlying audio, different outcome, purely a function of prior lock
state. The raw comb-filter's own top-3 candidates (now visible via
`acf_top_candidates`, tonight's earlier logging addition — this is exactly
the kind of case that addition exists for) showed a half-tempo candidate
(`~61.86 BPM`, i.e. `123/2`) consistently outscoring the true `~122-125 BPM`
candidates in the transition case, something the cold-start case never
exhibited on the same generator. Leading theory, not confirmed: an
interaction between the tactus fold-down's own region-consistency check
(`_tactus_fold_accepted()`, which is *inert* with zero beat-position
history — true at cold start — but *not* inert once the old lock's real
history exists) and the still-live old-tempo history during a transition.
**Not fixed — flagged as the next investigation**, now that
`region_consistency` and `last_tactus_fold` (below) are actually logged to
work with.

### New logging

- `BeatTracker.region_consistency` — the large-jump gate's own check,
  cached from the most recent large-jump evaluation. Deliberately
  documented as distinct from `downbeat_regularity`'s *internal* region
  term (that one checks the currently-locked tempo every confidence-blend
  cycle; this checks a large-jump *candidate*, only when one is being
  evaluated) — easy to conflate, so both docstrings cross-reference each
  other.
- `BeatTracker.last_tactus_fold` — owner: "we also need to log the fold
  decisions for the tactus stuff." The existing `tactus_fold_accepted_
  count`/`tactus_region_reject_count`/`tactus_score_reject_count` counters
  (2026-08-13/14) show *how often* each outcome happens; this compact
  string (`'accepted:150.00->75.00'` etc.) shows *which* fold each one was,
  overwritten each evaluation.
- Both new `_detector_snapshot()` fields, `0.0`/`''` for v1
  (`BeatGridTracker`), which has neither mechanism.
- `_DETECTOR_CONSTANT_DEFAULTS` in `training-kit-01`'s `package_training_
  set.py` gains all ten gate-stack constants under a new, explicitly
  distinct fourth category in the LLM prompt ("BPM-value ACCEPT/REJECT
  gating," alongside the existing tempo-VALUE-search / lock-STATE-gating /
  phase-lock-CONFIDENCE-smoothing categories) — the exact category
  distinction this whole investigation needed, now available for future
  LLM tuning recommendations to reason about correctly instead of
  guessing. `training-kit-01` `0.16.0 → 0.16.1`.

### Answered, not yet fixed: the tempo-hold gate may be actively counter-productive during a jump

Owner, precisely: "confident lane changes crawl at 3 BPM/update while
refreshing the 10s hold — same signature as the old '20 hot' bug, different
mechanism." Confirmed by re-reading the gate: it blocks re-evaluation
specifically when `acf_conf >= 0.45` — i.e. *strong* evidence gets blocked,
weak evidence is what's allowed through to the rest of the gate stack — and
`_tempo_hold_until_t` is refreshed to `now + tempo_hold_s` after **every**
accepted update, including a `_max_bpm_step`-capped partial step mid-jump.
Net effect during a genuine tempo change: confident evidence about the new
tempo repeatedly gets blocked by the very mechanism meant to protect a
*stable* lock, and progress only happens on cycles where confidence
happens to dip. Empirically consistent with the real `garbage/k` data (`acf_
confidence` visibly fluctuating 1.00 → 0.34 → 0.90 across the frozen
stretch) and with the region-consistency test needing a full 90s (not 30s)
to even reach a large-jump evaluation once. **Not implemented — owner
explicitly still deciding between two directions** (don't refresh the hold
on an out-of-band step, only once actually converged; or shorten/remove the
refresh during an in-progress jump specifically) and asked for analysis, not
a unilateral fix, given this exact code path's incident history. Recorded
in Open Questions.

### Also answered, no code change

- **Why clamp `acf_peak_ratio`?** Not "use the new score whenever it beats
  the rival" — `acf_conf = min(1.0, acf_peak_ratio/3.0)` is a continuous
  ratio-based confidence: a tied score (ratio `1.0`) gives `acf_conf ≈
  0.33`, and separation of `3×` or more all saturate to `1.0` — diminishing
  returns past a clearly-decisive margin, not a binary threshold.
- **Why does region-consistency exist at all / why was the system more
  responsive before?** Most of the gate stack is individually-reasonable
  incremental hardening (P4/P5, Mixxx-inspired guard, kr/dbc) added over
  time to stop specific *within-track* noise patterns — none were designed
  with "a track just changed and the tempo legitimately jumped 40 BPM" in
  mind, and their combined effect made a real jump nearly as hard to accept
  as a fake one. If living memory of it working better predates some of
  these landing, that would explain it directly.

**Verified:** full suite green (1713 tests) including 8 new tests across
`tests/test_beat_tracker_v2.py` (gate-constant values + instance wiring,
`region_consistency`/`last_tactus_fold` property behavior, cold-start vs.
transition convergence, the core large-jump-no-longer-frozen regression),
`tests/test_auto_vj_shadow_engine.py` (2 new `_detector_snapshot()` field
tests), and `tests/test_package_training_set.py` (1 new prompt-category
test). `_DETECTOR_VERSION` → `1.0.0-rc.22`, `_VJ_WEIGHTS_DOC_VERSION` →
`42`, `auto_vj.py` `__version__` → `1.0.0-rc.64`, `training-kit-01`
`0.16.0 → 0.16.1`.

---

## Tempo-Hold Gate Removed + Grid-Split Wobble Fixed (2026-08-14, the morning after)

Direct continuation of the previous entry's two open questions. Owner
confirmed a real, live session hit the exact "stable then collapsed to
sub-100 BPM" pattern the transition-asymmetry investigation was chasing,
and asked precisely: what `tempo_hold_s` did the simulation actually use
(10s, the default — never touched), and to check the training data for
the just-ended, not-yet-packaged session (`logs/autovj-20260813T132520.jsonl`,
the more recent of two short sessions in `logs/`).

### The transition asymmetry was the tempo-hold gate all along

Investigated the leading theory from the previous entry (beat-position-map
contamination from the old tempo biasing the tactus fold-down's
region-consistency check). Confirmed the phenomenon is real —
`region_consistency(123)` reads `0.00` for 30+ seconds after a transition
while `region_consistency(83)` stays high — but a direct A/B (manually
clearing the map at the transition boundary) changed **nothing** about the
BPM trajectory. Ruled out as the driver.

Disabled the tempo-hold gate as a diagnostic instead: with it, a synthetic
83→123 transition crawled to only `110.3 BPM` after 150 seconds; without
it, the same transition reached `122.5 BPM` within 15 seconds and settled
at `125.0`. That's the whole mystery — not a comb-filter or tactus problem,
the gate itself (see the previous entry's "answered, no code change"
section for the mechanism: it blocks *strong* evidence, not weak, and
refreshes on every accepted update including a partial jump step).

**Then tested the owner's own proposed fix** (don't refresh the hold on an
out-of-band step) rather than assuming full removal was the only answer —
it worked on the single scenario tested (`110.3 → 118.3`), a real
improvement.

### The real test: a 20-transition-pair sweep

Owner asked directly: simulate both fixes against transitions among
`{86, 112, 124, 132, 148}` BPM, every ordered pair (20 total, lock 60s then
transition 90s each).

| Variant | Converged within 90s (tol 3 BPM) | Typical convergence |
| --- | --- | --- |
| Current (gate active) | 4/20 | never, or 24-89s |
| Owner's fix (no refresh on out-of-band steps) | 4/20 | **~identical to current** |
| Gate fully disabled | **20/20** | **5-9s**, almost every pair |

The single-scenario result for the owner's fix didn't generalize — across
the full matrix it barely differs from the unfixed baseline (several rows
are numerically identical to the decimal: `112→124`, `132→124`, `148→124`,
`148→132`). Full removal is unambiguously the answer. Correction recorded
on the record rather than left standing: the earlier single-test claim
that the owner's fix "measurably works" was an overclaim from
non-representative sampling.

**Owner's response, verbatim on how they landed on that specific test
matrix:** "did i randomly out of thin air pick some good numbers or what!
that's called being connected to the aether ;)" — decision: **remove the
gate.**

### The real anomaly, and the real fix

The same 20-pair sweep surfaced a second, separate finding: every
transition landing on **124 BPM specifically** converged to `~101.65`
regardless of starting tempo, even with the gate fully disabled — a
consistent, reproducible miss the other four targets didn't share. Owner:
"make sure we have the training data required to look at comb & lag grid
(my suspicion)."

Verified the suspicion directly: `124 BPM`'s two nearest points on the
ACF's discrete lag grid are `122.449` and `125.0` — a 2.55 BPM gap, with
124.0 sitting inside it. Extending the test duration to 180s and running
10 different jitter seeds showed this isn't a hard, deterministic failure
— 6/10 seeds converged correctly, but 2/10 got stuck at a wrong value even
after a full 180 seconds. **Then found the live confirmation independently**
(before connecting the two): a real session (`logs/autovj-20260813T132520.jsonl`,
the requested unpackaged session) showed a clean, `acf_confidence=1.00`
lock at `127.33 BPM` collapsing to `91.37` over ~12 seconds with **no
track change at all** — same pattern, live, mid-track. `acf_top_candidates`
and `last_tactus_fold` (both logged since the previous entry) made the
mechanism visible directly in the corpus: the raw comb-filter argmax
itself moved to a competing 2:3-related candidate (`84.51`, against the
`127.66` lock) for several consecutive cycles — not a fold-down decision,
the raw correlator's own peak wandered.

**Fix:** `_V2_LARGE_JUMP_PERSISTENCE_CYCLES = 25` (~3.3s at the ACF's
~7.5 Hz re-estimation cadence) — a new, separate, much longer-window
version of the existing `candidate_history` persistence check
(`candidate_window`, default 5 cycles, under one second), consulted only
when a candidate is outside the lock band: requires the raw candidate to
have stayed consistent (median/spread) across the last 25 cycles before
the large-jump gate is even considered. In-band nudges are entirely
unaffected — same responsiveness as before for ordinary stable-lock
tracking.

**Verified:** the 3 seeds that previously got stuck (worst: `101.65`/
`115.99`/`106.92` instead of `~124-125`) all now converge correctly
(worst final error `22.35 BPM → 0.0`). Re-ran the full 20-pair sweep:
still `20/20` converged, worst final error `1.33 BPM`, convergence `6.5-12s`
— a few seconds slower than without the check (the 3.3s minimum wait), far
faster than the pre-hold-gate-removal baseline. Owner, live-testing the
combined fix while this was being written up: "latest build doing great @
128bpm to stream right now."

**Verified in the test suite:** full suite green (1717 tests). New:
`test_large_jump_persistence_check_prevents_the_grid_split_wobble`
(parametrized over the 3 previously-failing seeds), plus updates to the
now-removed hold-gate's own test (renamed, since the behavior it validated
no longer exists as an explicit mechanism — steady-state stability still
holds, now as an emergent property of having no different evidence to
react to) and a simplification of `region_consistency`'s own property test
(the end-to-end version became timing-dependent once the persistence check
changed exactly when that code path gets exercised; replaced with a direct
cached-value check, same pattern as `last_tactus_fold`'s own test).
`_DETECTOR_VERSION` → `1.0.0-rc.23`, `_VJ_WEIGHTS_DOC_VERSION` → `43`,
`auto_vj.py` `__version__` → `1.0.0-rc.65`.

**Still open:** why the raw comb-filter argmax wanders to a competing
candidate in the first place, on real music, for a few seconds at a time
— the persistence fix contains the *consequence* (nothing rides the
wobble to a wrong resting value anymore) without addressing why the
wobble happens. `acf_top_candidates`/`last_tactus_fold` are the tools to
keep investigating this with from real session data going forward.

### Round two, same session: tracking + a live report

Live-testing the combined fix, owner reported it's "doing pretty awesome"
but "thrashing a little bit... not in the wobble zone" — a real, milder
texture of jumpiness distinct from the collapse just fixed. Checked the
live session directly (`logs/autovj-20260813T134619.jsonl`, 20 min, 1191
rows, BPM range 81-176 matching the reported "160+ down to mid-110s"):
median tick-to-tick change is tiny (`0.09 BPM/sec`, mostly calm), but
~12% of ticks show `>1 BPM/sec` movement, up to a `15 BPM/sec` spike
(plausibly a real fast transition, given the range) — a real, quantified,
if modest, signal. That session predates the counters below, so which of
those fast moments were legitimate transitions vs. residual noise isn't
yet distinguishable; the next session will have that data.

**Idea floated, then built the same session:** a second, slower smoothing
layer purely at the point of publication, sitting on top of the existing
fast internal `self._bpm` rather than replacing it — "let it breathe"
without slowing the internal gates. Owner's own caveat, unprompted:
smoothing the *only* visible number risks hiding the exact kind of
flicker that let them catch tonight's real bugs live.

**Scope, deliberately narrow:** only `hud_bpm_label` (the primary "BPM:
nnn" HUD readout, `overlays.py:1828` via `App._hud_state['auto_vj_bpm']`)
reads the smoothed value, via a new `published_bpm` property. Everything
else that reads `self._grid.bpm` — the accept/reject gate stack,
`_timing_scale_from_bpm()` (director hold durations), ping-pong/downbeat
scheduling, `_reco_samples` (recommender `tempo_fit` scoring),
`publish_bpm()` (the cross-drop-in BPM hint bus other drop-ins consume),
`_detector_snapshot()` (training-corpus logging) — is entirely unaffected
and keeps reading the fast, raw value, exactly the recommendation from
above: full diagnostic resolution preserved in the corpus regardless of
what the HUD shows. The secondary status-pill BPM text
(`_pill()`/`self._status_text`) was deliberately left unsmoothed too, to
keep this first cut small and easy to reason about — can extend later if
wanted.

**Implementation:** `AutoVJController._update_published_bpm(bpm, dt)`,
called once per `update()` cycle. A time-constant EMA
(`alpha = 1 - exp(-dt/tau)`, not a fixed per-frame alpha) so the amount of
smoothing doesn't silently depend on frame rate. Two deliberate snap
cases, not smoothed: no-lock → locked snaps instantly (a first reading
shouldn't visibly ramp up from 0, which would look like the detector
warming up rather than a clean lock), and losing lock entirely snaps to 0
immediately (silence/reset must be reflected right away, not linger on a
stale number — smoothing is for cosmetic jitter, not for hiding a real
reset event).

**Config**, `[auto_vj]` in `config.toml`: `published_bpm_smoothing_enabled`
(bool, code default `true`) and `published_bpm_smoothing_s` (float, default
`4.0`, first-cut value not yet tuned against real data). Owner: default it
on, but set to `false` in the owner's own `config.toml` for now — "we'll
let this soak for a while" with the raw number visible during validation.

**Verified:** 8 new tests in `tests/test_auto_vj_published_bpm.py`
(disabled-smoothing exactness, first-lock snap, lock-loss snap, lag
behavior on a jump, convergence over several time constants, frame-rate
independence, `hud_bpm_label` reading the smoothed value not the raw
one). Full suite green (1729 tests).

**Tracking added so the new persistence window doesn't go stale like
several other gate constants did before this session.** Owner: "we need
to track and tune that persistence window eventually maybe.. let's not
let that hide on us like others have." New session-cumulative counters —
`large_jump_persistence_wait_count`/`_reject_count`/`_cleared_count` — plus
matching `_detector_snapshot()` fields, mirroring the existing tactus
counters' "how often does each outcome happen" role. Verified against the
83→123 large-jump test: `reject_count=24`, `cleared_count=10` before the
jump was accepted — real, useful signal, not just plumbing. Pure logging
— `_DETECTOR_VERSION`/`_VJ_WEIGHTS_DOC_VERSION` not bumped, same
exemption as `acf_top_candidates`. New tests:
`test_large_jump_persistence_counters_start_at_zero`,
`test_large_jump_persistence_counters_move_during_a_real_transition`,
plus 2 new `_detector_snapshot()` field tests. Full suite green (1721
tests). `auto_vj.py` `__version__` → `1.0.0-rc.66`.

---

## Round Three: Timing-Scale Neutral Point, a Research Correction, and Open Threads (2026-08-14, round three)

Same session, after the display-only BPM smoothing landed. Owner reported
the list still "not really very accurate... close but not close enough" —
one concrete data point: "off by 7 right now (Dreamin' (feat. Daya))" per
both their own tapping and Spotify's own display. Consistent with the
still-open "why does the raw comb-filter argmax wander" question from the
previous entry — not yet investigated further this round, recorded as a
live data point for whenever that gets picked up.

**`_timing_scale_from_bpm()` neutral point, ASAP fix.** Owner: "holy crap!
make neutral 114, asap!" `128` was a bare inline literal, never a named
constant, never tracked in `weights-and-thresholds.md` despite scaling
*every* timing-related hold duration in the director (build/breakdown/
drop/impact/climax). Promoted to `_TIMING_SCALE_NEUTRAL_BPM = 114.0`.
New test: `test_timing_scale_neutral_bpm_is_114_not_128` (asserts both the
constant's value and that the scale is exactly `1.0` at the new neutral
point, not just checking the number). `_DIRECTOR_VERSION` → `1.0.0-rc.4`
— its first move since `rc.3`. `_VJ_WEIGHTS_DOC_VERSION` → `44`,
`auto_vj.py` `__version__` → `1.0.0-rc.68`.

**Research correction: `vj_api.get_bpm()` is not comparison-only.** Owner
pushed back on an earlier research summary ("this does not sound
correct?"), specifically: "auto-vj-01... reads (excluding itself) from
this bus, but its own HUD/corpus/director logic reads `self._grid.bpm`
directly, not through `get_bpm()`." True but incomplete, and the missing
piece matters: `vj_api.get_bpm(exclude='auto_vj')` is called from **two**
places, not one:

- `_get_mixer_bpm()` (auto_vj.py:4510) — corpus-logging only, feeds the
  `mixer_bpm` field on keyframe events for post-hoc comparison against
  `self._grid.bpm`. No effect on detector state. This is the call the
  original summary was describing.
- **Directly inside `_update_profile_recommendation()`** (auto_vj.py:3866,
  the P0-B block) — when a fresh non-self hint exists on the bus (in
  practice, dj-mixer-01's own per-track analysis), calls
  `self._grid.prime_tempo(mixer_bpm)`. This **does** feed back into the
  detector's own tracked BPM.

This second call site is real, intentional, and *not* affected by the
one-way-flow cut earlier this week — that cut was specifically about the
**recommender's own genre classification** never writing back to the
detector (a guess, made with the least evidence the recommender ever
has). `prime_tempo()` from an external, independently-measured source
(dj-mixer's own analysis) is a different, deliberately-preserved channel
— already documented as such in the one-way-flow entry above, just not
connected clearly enough in the follow-up research summary that got
challenged here. No code changed; this is a documentation/accuracy
correction only.

**Open threads, recorded for the "philosophizing" days ahead, not
actioned this round:**

- **Agent delegation — corrected.** Initially misread as "auto-route
  out-of-domain requests to peer agents" and saved as such; owner
  corrected this immediately: "unsave that standing rule, that's not the
  one i wanted you to find. just check with me directly if you need
  something out of your area." The actual standing preference is to ask
  first, not to autonomously hand off — corrected in memory
  (`feedback-out-of-domain-ask-first.md`, replacing the earlier note).
- **Rolling multi-beat windows ("rear-view mirror").** Owner's idea:
  track rolling `4/8/16/32`-beat windows (not fixed-seconds windows like
  tonight's `_V2_LARGE_JUMP_PERSISTENCE_CYCLES`) for two purposes —
  (1) a beat-relative, tempo-scaled alternative/supplement to the
  persistence check (at `174` BPM, `32` beats ≈ `11s`; at `86` BPM, `32`
  beats ≈ `22s` — automatically scales instead of a fixed `~3.3s`), and
  (2) self-derived phrase/structure detection for the director, useful
  specifically for sources with no external mixer `section_role` hint
  (Spotify, media-01) where `_phrase_bias()`'s external-match terms
  currently have nothing to key off. Genuinely promising, not
  implemented — a real design candidate for the next round, not a quick
  tweak.
- **v1/v2/v3 accuracy comparison in the scoring report.** Owner: "can we
  log v1/v2/v3 bpm scores and compare them each time in scoring report,
  just each one's accuracy %." Needs a scope decision before building:
  "accuracy" requires ground truth, and this project does not fabricate
  ground truth where none exists (see "Fake Essentia Reference BPM
  Removed" above — the exact incident this note exists to avoid
  repeating). Two real options, not mutually exclusive: (a) **agreement
  %** between engines (v1/v2/v3 pairwise) — always computable, no ground
  truth needed, honest about what it measures; (b) true **accuracy %**
  against `mixer_bpm` specifically for dj-mixer-sourced sessions, where
  real independent ground truth exists. Also requires extending the
  shadow mechanism (currently exactly one shadow engine at a time,
  `beat_tracker_shadow_engine`) to run two simultaneously for a genuine
  three-way comparison. Not implemented — flagged for a scoping
  conversation before any code.
- **`_has_bpm_lock()`'s own floor — now tracked.** Owner: "we probably
  need to keep our eye on that floor we're kinda tuning." Shipped
  same-round: `_detector_snapshot()` gained `bpm_lock_gain_confidence`/
  `bpm_lock_release_confidence`, echoing the existing `_BPM_LOCK_CONFIDENCE`
  (`0.55`)/`_BPM_LOCK_RELEASE_CONFIDENCE` (`0.28`) constants on every
  corpus row. Values unchanged — pure logging. `auto_vj.py` `__version__`
  → `1.0.0-rc.69`.

**Round Three, continued: a live case study, and a full planning doc.**
Same night, a fresh session (`logs/autovj-20260813T175608.jsonl`)
collapsed to `~76` BPM on what the owner described as "a pretty easy
track," and was analyzed locally before packaging into the garbage sets.
It turned out to be an unusually clean illustration of several of the
mechanisms above acting together: a `0.32`-confidence candidate accepted
right at the `_V2_STARTUP_CONFIDENCE=0.3` cold-start floor, one cycle
later crossing `_BPM_LOCK_CONFIDENCE=0.55` via the downbeat-confidence
term and locking; from there, `large_jump_persistence_reject_count`
climbed from `0` to `137` over the session while
`large_jump_persistence_cleared_count` never once left `0` — not because
too few cycles had accumulated (the wait-count capped at `10` within the
first ~5 seconds, matching the documented cold-start-fill behavior), but
because the raw ACF kept finding candidates spanning roughly `88-166`
BPM cycle to cycle, never converging tightly enough to clear the
persistence gate's `6.0` BPM spread threshold. A genuinely new data
point for the still-open "why does the argmax wander" question, not a
resolution of it.

A new planning document,
[docs/planning/auto-vj-round-three-planning-2026-08-14.md](../planning/auto-vj-round-three-planning-2026-08-14.md),
captures the full session write-up plus every other open thread from
this round in one place: the complete `_V2_*` constant inventory with
plain-language meanings (owner: "list all the v2 specific values and
their meanings"), the "is 25 cycles too big" question (answer, from the
session data: probably not the binding constraint — the spread threshold
was), a precise `_phrase_bias()`/`_PHRASE_ROLE_BARS` writeup and the
finding that phrase-clock state is barely captured in training data
today (only at transition moments, not continuously), confirmation there
is no real downbeat-phase re-anchoring mechanism in `beat_grid.py`
("phase anchor" doesn't really exist), confirmation that `BeatTrackerV3`
really is just one overridden method versus v2 (with a proposal to fold
it in and retire the name for the real next-gen engine), a proposal to
add v1 as a cheap second shadow engine, a v1/v2/v3 agreement-table
design (internal shadow + mixer-library + LLM lookup), and a late-
breaking owner idea — scoring raw ACF candidates against the
recommender's *tempo-independent* genre-fit terms (spectral/timbral, not
`tempo_fit` itself) as a candidate-disambiguation signal, distinct from
the backward-flow bug v3 already guards against since it uses no
tempo-dependent evidence. None of these were implemented in that pass;
the planning doc is the durable place they live until the philosophizing
days produce consensus.

**Round Three, continued further: root cause found, an instrumentation
gap fixed instead of a guess, and four more capture items shipped.** Same
night, immediate follow-up on four of the planning doc's threads:

1. **"Would a spread threshold of 8/10/12/15 have converged faster?"**
   Tried to answer precisely from the 17:56 session's full log (which
   had, by then, finished recording — 64.7 minutes, 3794 ticks; the wrong
   `~76` BPM lock turned out to have persisted for **~34 minutes**, not
   the ~2.4-minute window the scorecard first captured, self-correcting
   only once a later real track change produced an internally stable new
   candidate). A rolling-window reconstruction from the logged
   `last_tactus_fold` values suggested 45-86% of short windows would
   clear thresholds from 6 to 15 — but the real gate cleared **zero**
   times in those 34 minutes. The two don't reconcile: the corpus logs at
   ~1 Hz while the real persistence check runs on ~7.5 Hz per-cycle
   candidates, so any reconstruction from the existing log necessarily
   undersamples real cycle-to-cycle diversity. No specific number can be
   responsibly recommended from this data. Fixed the actual gap instead:
   `BeatTracker.long_candidate_spread`/`long_candidate_median` now cache
   the exact values `_estimate_tempo_acf()` already computes and compares
   against `6.0` every evaluation, logged from now on — the next session
   that hits this gate has ground truth, not a reconstruction.
2. **`_V2_STARTUP_CONFIDENCE` `0.3 → 0.4`** as the interim mitigation the
   data *does* support: the 17:56 session's cold-start candidate was
   accepted at `acf_conf=0.32`, barely above the old `0.3` floor, and was
   the octave-family error that started the whole 34-minute episode.
   `0.4` sits at the midpoint between that incident's floor and the
   pre-2026-08-14 value (`0.55`) — targets how easily a wrong lock forms,
   distinct from the persistence-window question above (how hard it is
   to escape one). `_DETECTOR_VERSION` → `1.0.0-rc.24`.
3. **Wandering argmax — root cause found.** Every one of the 17:56
   session's ~10 "competing" candidates (`120`, `133.33`, ... `166.67`)
   converts back (`lag = 6000 / bpm` at `_V2_ENV_RATE=100` Hz) to
   consecutive integer lags `36-50` — the same underlying periodicity
   landing on different adjacent lag bins, not genuinely distinct tempo
   hypotheses. `d(BPM)/d(lag) = -6000/lag²` means the grid is coarse
   specifically at higher BPM (`3.75` BPM/step at `150` BPM vs. `0.94` at
   `75`) — the same phenomenon as the known 124-BPM grid-split gap, just
   structurally worse the faster the tempo. Proposed fix: standard
   parabolic sub-lag peak interpolation in `_estimate_tempo_acf()` — real
   blast radius (every BPM reading's numeric precision changes, existing
   tests likely need re-baselining), so flagged as a proposal in the
   planning doc, not shipped without sign-off.
4. **Front-to-back capture sweep, per owner request ("capture them
   all!... this time front to back").** Continuous phrase-clock logging
   (`bars_since_track_start`/`bars_since_phase_entry`/
   `phrase_neutral_bars_left`, now in every `_sequence_director_fields()`
   row, not just at an actual transition); `spectral_flux_smooth`/
   `bass_flux_fast` (drop_score's own raw inputs, found as existing but
   never-logged `BeatTracker` properties); a second, independent
   shadow-engine slot (`beat_tracker_shadow2_engine`,
   `bpm_shadow2`/`confidence_shadow2`/`shadow2_engine`) so v1
   (`BeatGridTracker`, confirmed `<0.3ms/frame`) can run alongside the
   existing v2/v3 shadow for a real three-way agreement comparison,
   per owner: "adding another one for legacy should be pretty easy?"

All four are detailed with full reasoning in
[docs/planning/auto-vj-round-three-planning-2026-08-14.md](../planning/auto-vj-round-three-planning-2026-08-14.md),
kept in sync with this entry. `auto_vj.py` `__version__` → `1.0.0-rc.70`;
training-kit-01 → `0.16.4`.

**Round Three, continued once more: the interpolation fix shipped as an
A/B flag, both shadows turned on, a scope refinement, and an rc2 idea.**
Same night, immediate follow-up:

- **Sub-lag (parabolic) peak interpolation** — the fix proposed above
  for the argmax-wandering root cause — implemented in
  `_estimate_tempo_acf()`, applied once after `peak_idx` is finally
  settled (does not change which bin wins, only refines the reported
  BPM). Shipped **disabled by default**
  (`_V2_ACF_INTERPOLATION_ENABLED = False`, config key
  `acf_peak_interpolation_enabled`) specifically so it can be A/B tested
  as two real sessions rather than depending on commit timing — owner:
  "we should test this very soon, we'll consider my next run the A for
  this and the one directly after we'll do the B w/that fix." New
  `acf_interpolation_delta_bpm` property/corpus field, `0.0` for the
  entire A run by construction. `_DETECTOR_VERSION` → `1.0.0-rc.25`.
  `config.toml` has `acf_peak_interpolation_enabled = true` ready,
  commented out, to flip on for the B run.
- **Both shadow engines turned on**, per owner request:
  `beat_tracker_shadow_engine = "v2"` (already on) plus the new
  `beat_tracker_shadow2_engine = "legacy"` (v1) — the active `v3` engine
  now runs alongside both v2 and v1 shadows simultaneously in
  `config.toml`.
- **Genre-fit-weighted candidate scoring (§ 8 of the planning doc),
  scope refined:** owner: "consult only when conf is low." Gate on
  confidence, not lock state — only consult the tempo-independent
  genre-fit terms when `acf_conf` is already low, i.e. exactly the
  ambiguous moments where a second signal is useful, and structurally
  safe against backward-flow since high-confidence readings never
  consult it at all. Not implemented; recorded as the resolved scoping
  question in the planning doc.
- **New: a full in-app config menu** for detector/shadow model
  selection, explicitly scoped for **rc2, not rc1** — added to the
  planning doc (§ 9) as a roadmap item, not started.

`auto_vj.py` `__version__` → `1.0.0-rc.71`; training-kit-01 → `0.16.5`.

**Round Three, live-session watch: the churn pattern explained, lock band
tightened, v2/v3 consolidated.** Same night, the owner watched a fresh
session (`logs/autovj-20260813T194512.jsonl`, v3 active + v2 shadow, the
interpolation flag correctly off) in real time and reported: "totally
started out right on point but collapsed quickly to sub 100 instead of
mid 120s... moved back in to proper range... collapsed again."

**Root cause found, distinct from everything fixed earlier this round.**
The large-jump gate stack only ever governs jumps *outside* the lock
band. In this session it was demonstrably active
(`large_jump_persistence_reject_count` reached `1089`,
`cleared_count` reached `284`) and doing its job on genuinely large
jumps — but the observed `122 → 88` BPM collapse happened as a sequence
of **in-band** steps: `124.73 → 105.17` in one step is `19.56` BPM, and
under the old `_V2_LOCK_BAND_PCT=0.16`, `124.73 * 0.16 = 19.96` — just
inside the band, so it cleared with zero extra scrutiny. `bpm_locked`
toggled 38 times over 11.9 minutes. Nothing in the gate stack resisted a
*sequence* of individually-legal in-band nudges compounding into a large
drift — a gap distinct from (and complementary to) the out-of-band
persistence check.

**`_V2_LOCK_BAND_PCT` `0.16 → 0.08`, shipped immediately.** Owner: "i
guess we should consider a large jump gate something more appropriate,
that's pretty huge for a one-song swing, or even a two song swing... let's
change it to 8, now please." Now roughly converges with the flat
`_V2_LOCK_BAND_MIN=10.0` floor around 125 BPM instead of nearly doubling
it. `_DETECTOR_VERSION` → `1.0.0-rc.26`.

**`v2` vs `v3`: 100% identical across the entire session (638 compared
rows, mean/median/max diff all `0.000`).** Direct empirical confirmation
of the code-reading finding from the entry above — `BeatTrackerV3`'s one
override currently has zero live effect, since its only production
trigger was removed at rc.20. Owner: "yea let's consolidate v2/v3."
`BeatTrackerV3`'s guard folded directly into `BeatTracker.set_profile()`;
the subclass retired entirely. `beat_tracker_engine = "v3"` remains a
working config value — `_load_beat_grid_cls()` now resolves it to the
same class as `"v2"`, with a deprecation log line — freeing the name for
the real next-generation engine. `_DETECTOR_VERSION` → `1.0.0-rc.27`.
Migrated `tests/test_beat_tracker_v3.py`'s still-relevant coverage into
`tests/test_beat_tracker_v2.py` and deleted the old file; updated
`_load_beat_grid_cls()`'s own tests in `test_auto_vj_shadow_engine.py`.

**Noted for later, not reopened now:** owner, same message: "blocking
genre re-priming after lock is an idea worth re-visiting when we get
back to recommender work." Saved as a standing project memory
(`genre-repriming-after-lock-revisit.md`) so it isn't lost between
sessions — the retirement above is a default removal, not a permanent
close on the underlying question.

**Minimum lock dwell time — new idea, not implemented.** Owner, same
live-session observation: "maybe we do need some kind of minimum lock
length to prevent the churn, a standard musical amount.. like 16/32
bars?" The observed ~60-100s oscillation period maps plausibly to
16-32 bars at the locked tempo — but a fixed-seconds mechanism would not
scale with tempo the way a bar-relative one would. Design sketch
recorded in the planning doc (§ 10), not implemented — real new gate
category (what it restricts, how it interacts with the existing
large-jump path), not a threshold tweak. Owner revised the test range
after the lock-band retune above: "32 bars too long... will test 8 & 16
first when we get there."

**Shadow2 (v1) confirmed absent this session** — config picked up only
on the next app restart, consistent with `_V2_ANALYSIS_DOWNBEAT_
CONFIDENCE_MIN`'s own precedent of detector config not being
hot-reloaded. Owner's next session (starting after this response) will
have it.

All of this is detailed in
[docs/planning/auto-vj-round-three-planning-2026-08-14.md](../planning/auto-vj-round-three-planning-2026-08-14.md)
§§ 7b, 10, 11. `auto_vj.py` `__version__` → `1.0.0-rc.72`;
training-kit-01 → `0.16.6`.

**Round Three, closing the loop: `library/c` packaged, LLM score
notably improved, two recommendations applied.** Owner packaged the
night's sessions into a fresh `library/c` set and asked for a check —
"llm score notably improved! i honestly didn't expect that." A clean
same-track before/after made the story concrete: "Thriller (Tim Cosmos
2025 Rework) – Michael Jackson" scored `19.6%` lock coverage in an old
`garbage/d` bucket (2026-08-11, pre-round-three) and `59.5%` on the
identical file in tonight's `library/c` — roughly 3x, on genuinely
harder material than the clean single-track reference sets (`library/a`/
`b`, `4.4/5` overall but `100%` lock coverage across the board — an easy
baseline, not a fair comparison point). `library/c`'s own overall
scores: detector `3.25/5` (lock stability `3/5`), recommender `2.75/5`,
director `2.5/5` — the director's low "Build Quality"/"Opportunity
Usage" scores matched the already-known `drop_without_recent_build=47`
lint finding, which the owner had already dismissed as expected DJ
behavior ("a lot of these dj tracks drop w/o builds, no worries").

The scoring pass's `tuning_recommendations.md` included four
suggestions; owner approved two directly, deferred two: "let's go ahead
and move the lock release conf & phase under over as recommended, after
we get into library diversity we'll re-visit all the centroid stuff."

- **Applied:** `_BPM_LOCK_RELEASE_CONFIDENCE` `0.28 → 0.3` ("frequent
  lock changes suggest slightly tightening the release confidence to
  stabilize lock states") and `phrase_under_over_hold_mult` `0.6 → 0.7`
  ("builds were rushed; slightly increasing this multiplier could smooth
  transition timing"). Both director-scoped constants (`AutoVJController`).
  `_DIRECTOR_VERSION` → `1.0.0-rc.5`.
- **Deferred, not applied:** `hard_techno`/`house` spectral-centroid
  recalibrations (`centroid_mu` `2450→3700`/`2650→4000`) and a
  `kick_regularity_fit` weight bump (`0.9→1.2`) — explicitly held for a
  later library-diversity pass per the owner's own sequencing, not
  rejected.

Consistent with the project's advisory-only LLM-tuning policy
(`tuning_recommendations.md`'s own disclaimer, and
`docs/adr/training-model.md`) — nothing here was auto-applied; each
accepted change was reviewed and approved individually. `auto_vj.py`
`__version__` → `1.0.0-rc.73`; training-kit-01 → `0.16.7`.

**Round Three, one more: `kick_regularity_fit` earns its way up.** Owner
asked for the exact equation and current weight table, then reconsidered
the deferred `kick_regularity_fit` bump on the spot: "let's bring it to
1.2, wth! i have confidence in it as well and it's one of our newer
additions, earning it's way up the ladder!" Applied —
`kick_regularity_fit` `0.9 → 1.2` in `_DEFAULT_RECO_WEIGHTS`.
`_RECOMMENDER_VERSION` → `1.0.0-rc.14`. Only the `hard_techno`/`house`
spectral-centroid recalibrations from `library/c` remain deferred to the
library-diversity pass now.

The owner also asked whether there's a "Jason" attribution comment on
`kick_regularity_fit`, recalling it as a personal contribution.
Checked directly: the codebase's only `Jason`-signed comments
(`beat_grid.py`) are on **`downbeat_regularity`** — a related but
distinct signal (the detector's own confidence-blend term, "Downbeat
regularity confidence idea & math by Jason. ;D") — not on
`kick_regularity_fit` (the recommender's term, `auto_vj.py`) or
`kick_regularity` (the underlying shared measurement,
`_compute_kick_regularity()`). Reported honestly rather than assumed or
fabricated; no attribution comment added without direct confirmation of
which specific piece the owner means.

`auto_vj.py` `__version__` → `1.0.0-rc.74`.

**Round Three, closing: the B run — interpolation A/B result, and a
standing caveat for future external references.** Owner packaged the
interpolation B run (`library/d`, session `autovj-20260813T214252.jsonl`,
47.7 min) and asked for independent analysis alongside the LLM report.

**The A/B result, on the exact metric the persistence gate checks
(`long_candidate_spread`, compared against `6.0` every large-jump
evaluation):**

| Metric | A (`library/c`, interp off) | B (`library/d`, interp on) |
|---|---:|---:|
| `long_candidate_spread` mean | `44.62` | `37.45` |
| `long_candidate_spread` median | `42.42` | `41.02` |
| fraction `<= 6.0` (gate would clear) | `8.5%` | `19.9%` |
| lock % | `68.6%` | `77.9%` |
| lock toggles/min | `4.55` | `3.00` |
| mean confidence | `0.513` | `0.547` |
| v1 (shadow2) mean disagreement | `25.6` BPM | `22.2` BPM |
| `acf_interpolation_delta_bpm` engagement | `0%` (confirmed off) | `98.0%` of cycles; mean abs delta `0.20` BPM, median `0.09`, max `2.21` |

Interpolation engaged on nearly every cycle (as expected — most peaks
aren't exactly on-grid) with small, bounded corrections, and the
fraction of large-jump evaluations tight enough to clear the persistence
gate roughly **doubled** (`8.5% → 19.9%`). Lock stability, churn, and
mean confidence all moved the same direction. LLM scores were mixed on
the surface (detector `3.25/5` unchanged, "Lock Stability" dimension
read `2/5` vs. `3/5` — but recommender `3.0/5` and director `3.0/5` both
improved from `2.75`/`2.5`) — the *direct* metric comparison above is the
more reliable signal for judging this specific mechanism. Not yet
promoted to the default (`_V2_ACF_INTERPOLATION_ENABLED` stays `False`
pending the owner's own call after the overnight "C" run, which bundles
this with every other round-three change).

**LLM scoring standing caveat.** Owner, reflecting on the same night's
measured improvement: "we also need a note for the llm scoring, that it
is *possible* that our live bpm detection is, or may become, more
accurate than other methods... we're not there yet, but we were close
once." `essentia_note` (training-kit-01's LLM prompt) extended: whenever
`external_agreement` stops being null in a future session, the LLM must
not assume the external reference beats the in-house detector by
default — treat a disagreement as open unless the session's own data
(low confidence, real candidate instability) supports the detector being
wrong.

**Next: owner starting an overnight "C" run** with every round-three
change live together (tighter lock band, consolidated engine, three
LLM-recommended weight/constant changes, interpolation on, v1 shadow2)
— the first session to combine all of it.

**Round Three, self-correction: the "C" run caught a real regression in
the same night's own work.** Partway through the overnight run, owner:
"i don't think c run is doing as well as b run... it's def not doing as
well." Checked the live session directly rather than assuming — two
findings:

1. Interpolation was already on (`94%` cycle engagement, confirmed) —
   not the cause, contrary to the owner's first suspicion.
2. `_BPM_LOCK_RELEASE_CONFIDENCE`'s `0.28 → 0.3` change (applied
   earlier this round, see above) was backwards: raising the *release*
   floor narrows the hysteresis band (gain `0.55` minus release),
   making a lock *easier* to lose, not harder — the opposite of its own
   "stabilize lock states" rationale. Confirmed directly against the
   live session: `71%` of its lock-loss events happened at a confidence
   that would have survived under the original `0.28`.

Owner: "let's try release confidence .25? .26? what's your math say?"
Backtested both candidates against the full actual lock-loss confidence
distributions of two real sessions (the "C" run in progress, 30 events;
the "B" run, 71 events) rather than guessing: `0.25` retained more locks
than `0.26` at both (C: `4/30` vs. `5/30` still release; B: `20/71` vs.
`25/71`), and `0.25` lines up exactly with `_V2_MIN_UPDATE_CONFIDENCE`
(`beat_grid.py`'s own floor for accepting any BPM update at all) — a
principled stopping point rather than an arbitrary pick between two
close numbers. Applied: `_BPM_LOCK_RELEASE_CONFIDENCE` `0.3 → 0.25`.
`_DIRECTOR_VERSION` → `1.0.0-rc.6`; `auto_vj.py` `__version__` →
`1.0.0-rc.75`.

`_BPM_LOCK_CONFIDENCE`'s own pending recommendation (`0.55 → 0.6`, from
`library/d`, the gain/acquire threshold — a different constant from the
release floor above) is deliberately **not** acted on yet — owner:
"let's just keep our eye on that over the next couple runs and see if
that recommendation changes." Watching, not applying.

Owner, separately, mid-session: "btw we're not concerned w/ recommeder
or director right now, we're focused on detector stuff still" —
recommender/director items surfaced by scoring reports (e.g. `library/d`'s
`tempo_fit`/`centroid_fit` suggestions) are flagged when they appear but
not pursued further while this phase stays detector-focused.

**Round Three, `kick_regularity_fit` pulled back; lock band tightened
again from measured data.** `library/e`'s LLM report recommended pulling
`kick_regularity_fit` back from `1.2` ("less correlated with correct
recommendations in this session"); owner-approved directly ("let's take
KRF from 1.2 to 1.0 as suggested"). Applied: `1.2 → 1.0`.
`_RECOMMENDER_VERSION` → `1.0.0-rc.15`.

Live-session verification of the `0.25` release-confidence fix (§ above)
confirmed it working — the first session running it from the start hit
the best numbers of the entire night (lock `83.1%`, `2.45` toggles/min,
mean confidence `0.559`, all better than every prior session).

**Owner's "floor" hunch, investigated with real data.** Owner noticed
`_BPM_LOCK_RELEASE_CONFIDENCE` (`0.25`) now matches
`_V2_MIN_UPDATE_CONFIDENCE` and asked whether the floor itself, or both
together, should move lower. Checked directly against the live session:
`_V2_MIN_UPDATE_CONFIDENCE` gates raw `acf_confidence` (a different
signal from the blended `confidence` the release floor gates — the
shared `0.25` is a coincidence of value, not the same quantity), and
while locked, `acf_confidence` was below `0.25` on only `3.1%` of rows —
not currently a chronic bottleneck in a healthy session. No change made;
flagged that a rockier session would be the place to re-check this.

**Lock band tightened a second time, this round from first principles
rather than a single incident.** Owner: "do you think 8% is still too
large... what about the 10.0 floor, how do you think that is
performing?" Measured real cycle-to-cycle jitter directly from a healthy
locked session (1440 samples): median `0.04` BPM, p90 `1.04`, p95 `2.3`,
p99 `11.0`. The `0.08`/`10.0` band (from the prior tightening, above)
was still letting through the top 1-2% noise tail completely ungated —
exactly the tail where real problems live, and unnecessary now that the
large-jump path is verified working well and fast for genuine
transitions. Splitting the same data by tempo also surfaced an
asymmetry: low-BPM material (chillstep/downtempo, the problem child most
of the night) has *tighter* natural jitter than high-BPM (p95 `1.60` vs.
`2.26`, consistent with the ACF lag grid being finer at low BPM — the
same mechanism behind the interpolation fix's root cause) yet the old
flat `10.0` floor gave it a *wider* relative allowance. Owner: "let's do
both, now! i'm hardcore like that." Applied: `_V2_LOCK_BAND_PCT`
`0.08 → 0.03`, `_V2_LOCK_BAND_MIN` `10.0 → 4.0`. `_DETECTOR_VERSION` →
`1.0.0-rc.28`.

**Open design question for the real next-gen engine, not implemented:**
owner, closing out the night: "we should also consider, for round
three, having them scale in a proportional way with bpm range that we
control rather than letting them swing in just a random what other math
happens to be doing way." The current `max(flat_floor, bpm * pct)` shape
is exactly that — an emergent crossover point (currently ~133 BPM)
nobody actually designed, just wherever two independently-chosen numbers
happen to intersect. Recorded as a design candidate in the planning doc
(§ 15) rather than acted on tonight: since the ACF's own lag-grid
resolution is an analytically known function of BPM
(`d(BPM)/d(lag) = -BPM²/6000`), the "expected noise floor" at a given
tempo could be derived directly from that formula instead of fit as two
arbitrary constants — a single continuous, mechanistically-justified
curve rather than a two-piece `max()`. Worth revisiting once
interpolation (which changes what "grid resolution" even means) is a
settled default, not explored in parallel with it.

**Round Three, the dual lock-band candidates shipped, then the closing
study mission.** Owner's own addition to the scaling-function idea
above: "we code them both up but just log both for one session with
everything else as is, and see what we think of each." Shipped, pure
logging: `lock_band_candidate_analytical` (`k=1.0` lag-grid steps at the
current BPM) and `lock_band_candidate_empirical` (a flat `3.0` BPM
constant from real measured jitter — an OLS regression against real data
found no clean BPM-dependence, so this candidate directly tests whether
BPM-scaling holds up at all), plus `lock_band_bpm` exposing the real
live value for a same-row three-way comparison. Neither candidate gates
anything; the actual gate is unchanged.

Also fixed a staged-but-unstaged oversight from earlier the same round
(`__version__`/`_VJ_WEIGHTS_DOC_VERSION` bumped in source but not
included in a prior commit) and, separately, twice this same night,
recovered from an *accidentally* detached HEAD in both submodules —
`git submodule update` checking out the SHA the main repo's index still
had recorded, before the pointer bump landed — via a plain `git checkout
<branch>` each time. Neither was intentional or destructive; noted here
only because CLAUDE.md's Git History Safety section treats detached HEAD
as a hard-stop condition worth a paper trail even when the recovery is
routine.

Closing the night: owner asked for a full study pass — "we had an
individual expert analysis of all our work do a full audit and plan for
official v3 as well as then evaluate our current plans for round 3...
check out their notes in your round 3 doc and 2026-08-13-bpm-tempo-
detection-audit.md... update the docs as you wish, but no deletions,"
while explicitly reserving tonight's current point as the best candidate
for a final v2 detector, distinct from whatever "official v3" design
work comes next. Full findings-by-finding cross-reference, two more
pure-logging additions the audit itself proposed as the cheap first
step toward its T2/T4 findings (`analyzer_refractory_s`,
`phase_confidence_calibrated` — new public `Analyzer.refractory_s`
property in core), an explicit v2-final-candidate checkpoint, and the
v3/HMM roadmap synthesis are all in
[docs/planning/auto-vj-round-three-planning-2026-08-14.md](../planning/auto-vj-round-three-planning-2026-08-14.md)
§ 16 — not duplicated here in full. Headline finding: tonight's
interpolation fix (§ 6) and the audit's own #1-ranked recommendation
(T1, parabolic peak interpolation) are the same fix, arrived at
independently, before this study pass ever opened either document — real
convergent validation in both directions. The one finding with zero
round-three activity in any direction is T5 (no explicit octave policy
for fast genres) — flagged plainly as the biggest remaining gap, not
guessed at, since tonight's sessions never exercised DnB/hardstyle
material. `unicornviz.__version__` → `1.0.0-beta.92`; `auto_vj.py`
`__version__` → `1.0.0-rc.79`.

**Round Three, the morning after: startup confidence raised, `library/g`
and `library/h` reviewed.** Two overnight/morning sessions packaged and
reviewed. `library/g` (444 min, the session that ran through the night)
confirmed the rc.28 lock-band tightening (`0.03`/`4.0`) was live for the
whole run, but landed before the dual lock-band candidate logging and
the two audit cross-check fields (`5deb790`/`6b4fedc`) — both committed
minutes after the session had already started, so `g` carries none of
that data. `library/h` (82 min) surfaced two real findings:

1. Owner: "raise start up lock conf." `_V2_STARTUP_CONFIDENCE` `0.4 →
   0.45`. No fresh marginal-case incident this round to justify a
   specific target — `h`'s own cold start locked at `acf_conf=1.00`,
   nowhere near either threshold — so this is a conservative further
   step past the rc.24 fix, not a data-driven retune. Confirmed by
   reading the gate site directly that this constant fires *only* on a
   session's first-ever lock (`self._bpm <= 0.0`); every later re-lock,
   including at track boundaries, is gated by `_V2_MIN_UPDATE_CONFIDENCE`
   instead — so the wide spread of per-track "first lock after a track
   change" confidences observed in `h` (0.35 to 0.90) is irrelevant to
   this constant and wasn't used to tune it.
2. Owner: "humming seems to trip the detector up? (steady man track)."
   "Steady Man (Original Mix)" alone accounted for 12 of `h`'s 45 lock
   transitions (6 gains/6 losses, 27% of the session's churn from one
   track out of 20); a second track ("La Trompeta") accounted for 6
   more — together 40% of the session's churn from 2 of 20 tracks, while
   9 of 20 tracks locked cleanly with zero transitions. Row-level
   inspection during Steady Man's hunting windows shows `kick_regularity`
   repeatedly collapsing toward `0.0` while `bass`/`energy` stay high —
   consistent with a low-transient-density passage (no lyric/vocal-content
   signal exists to confirm "humming" specifically, but the behavioral
   fingerprint fits). Cross-session comparison against the same track in
   `library/f` (older code, pre-rc.28 lock band) showed 24 transitions
   there vs. 12 in `h` — the tightening roughly halved churn on this
   specific hard track without eliminating it. Same-song comparisons
   across `library/e`/`f`/`g`/`h` more broadly showed strong before/after
   evidence for the rc.28 tightening ("What Is Love"/"Rain Over Me": 6
   transitions in `f` → 0 in `g`; "You And I": 12 in `e` → 0 in `g`;
   "Touch The Sky": 26 in `e` → 2 in `g`) alongside a handful of same-song,
   same-code (`g` vs. `h`) pairs that behaved differently between
   sessions ("Move Ya Body," "Scream & Shout," "Pull Over I I": 0
   transitions in `g`, 2-4 in `h`, with real BPM excursions down to the
   60s-90s in `h` that weren't present in `g`) — flagged as an open
   reproducibility question (session/mix context dependence, not a code
   regression, since both sessions ran identical detector code) rather
   than investigated further this round.

Also caught and fixed a real staleness gap while cross-checking commit
timestamps: `training-kit-01`'s `_DETECTOR_CONSTANT_DEFAULTS` fallback
table still had `_BPM_LOCK_RELEASE_CONFIDENCE` at the mis-tuned `0.3`
instead of the corrected `0.25` (only affects that tool's standalone
fallback path when auto-vj-01 isn't present in the checkout — no
packaged session was ever actually affected). Synced, along with the new
`_V2_STARTUP_CONFIDENCE` value. `_DETECTOR_VERSION` → `1.0.0-rc.29`;
`_VJ_WEIGHTS_DOC_VERSION` → `53`; `auto_vj.py` `__version__` →
`1.0.0-rc.80`; `training-kit-01` → `0.16.11`.

**Round Three, the morning after (part two): sparse-evidence update
gate, two `library/h` LLM recs applied, and real `external_agreement`
wired up.** Four owner requests in one message, all landed:

1. **Two `library/h` LLM tuning recommendations applied directly**
   ("let's try those now, wth"): `spectral_shape_fit` `1.2 → 1.4`
   (recommender) and `phrase_under_over_hold_mult` `0.7 → 0.8`
   (director). `_RECOMMENDER_VERSION` → `1.0.0-rc.16`,
   `_DIRECTOR_VERSION` → `1.0.0-rc.7`.
2. **New sparse-evidence update gate** (`_V2_KICK_EVIDENCE_ALPHA`
   `0.15`, `_V2_MIN_KICK_EVIDENCE` `0.12`) — the fix for the "humming"
   observation above. Already-locked BPM updates now additionally
   require an EMA of `kick_regularity` (`kick_evidence_smooth`) to clear
   a floor, holding the current lock instead of chasing an ACF candidate
   the recent audio doesn't have the rhythmic structure to support.
   Distinct lever from `_effective_tactus_ratio()`'s existing
   `kick_regularity` use (that tightens *which* candidate wins a fold;
   this suppresses accepting any update at all). Raw `kick_regularity`
   was too noisy cycle-to-cycle to gate on directly — it swung `0.0` to
   `0.8+` within a few cycles even during a correctly-locked stretch in
   real session data — hence the EMA. New `kick_evidence_smooth`/
   `kick_evidence_reject_count` properties, logged per-row, specifically
   so the two first-cut constants can be tuned from real engagement data
   rather than guessed at twice: owner, "let's do that, and be sure to
   log and monitor the relevant details so we can tune it if needed."
   Discovering this gate's existing tests never passed `kick_regularity`
   at all (it silently persists at its `0.0` default) surfaced a real
   test-fixture gap — every pre-existing tempo-change test in
   `test_beat_tracker_v2.py` and `test_bpm_detector_audit_regressions.py`
   would have frozen after first lock under the new gate; both files'
   `_run_steady_click_track()` helpers now default `kick_regularity=1.0`
   (honest for a perfectly regular synthetic click train) so existing
   coverage keeps testing what it always tested. `_DETECTOR_VERSION` →
   `1.0.0-rc.30`.
3. **New shared track-path hint bus** (`App`/`VJApi`
   `publish_track_path`/`get_track_path`, mirrors the existing
   `publish_bpm`/`get_bpm` bus exactly) so dj-mixer-01 can tell an
   offline consumer which real local file is playing. `unicornviz.
   __version__` → `1.0.0-beta.93` (also corrects a version-header gap:
   `unicornviz/__init__.py` was never bumped to `beta.92` when that
   entry landed — caught while making this bump). dj-mixer-01's
   `_exchange_bpm()` now publishes the playing deck's `track_path`
   alongside the tempo it already publishes (`0.185.0`). auto-vj-01
   captures it into every live/sequence corpus row as a new `track_path`
   column, via a new `_get_mixer_track_path()` mirroring the existing
   `_get_mixer_bpm()` exactly (`1.0.0-rc.83`). media-01 publishes on the
   same bus too (new `_publish_track_path()`, called from `update()`,
   `0.22.0`) — owner, moments later: "essentia should work on media
   player data as well, those are using the same local files as the
   mixer." Both sources publish under their own name (`dj_mixer`/
   `media`), so `get_track_path()`'s existing freshest-wins logic picks
   whichever is actually playing without either drop-in knowing about
   the other.
4. **Real `external_agreement` data, wired up at last.** Owner: "why are
   we not getting essentia data for our tracks... let's wire it up! and
   the mixer one too, each get their own column(s) in the corpii." The
   answer to the original question: it was never a DJ-pool-vs-other-
   source issue — no real Essentia data existed ANYWHERE in the pipeline
   (a prior version faked one by copying the detector's own BPM and
   mislabeling it, removed the same night it shipped — see the
   `library/g`/`h` review entry above). Separately, a genuinely real,
   working, already-installed-on-this-machine Essentia integration
   existed the whole time in `training_lib.py::extract_audio_features()`
   (`tools/training/`, used by the separate `build_corpus.py` offline
   toolchain) — just never wired to `package_training_set.py`'s
   scorecard pipeline. Now it is: each per-song entry in
   `_build_detector_payload` gains `mixer_bpm_median` (dj-mixer-01's own
   independent BPM, median over the song's rows, zero-placeholder rows
   excluded) and `essentia_bpm`/`essentia_key` (real offline analysis
   against the actual file at `track_path`, when one exists and points
   at a readable file — currently dj-mixer-01 sessions only; Spotify/
   media/streams have no local file). Neither is folded into a
   precomputed agreement score — each is its own column, and the LLM
   reasons from the raw numbers, per the owner's explicit instruction.
   The prompt's `essentia_note` is now computed per-session instead of a
   static string: honestly says how many of this session's songs have
   real reference data and to score the rest as no-data, while keeping
   the existing standing caveat that a disagreement is not automatically
   the detector's fault. `essentia` added to
   `tools/training/requirements.txt` only, per owner instruction — core
   `requirements.txt` and every other drop-in's are untouched.
   `training-kit-01` → `0.17.0`.

**Documented, deliberately deferred: an explicit track-reset signal.**
In response to the `library/g` vs. `h` boundary-carry-over finding above
(a messy outgoing track's tail can poison the incoming track's initial
lock), the natural fix would be an explicit "track changed, clear your
carried state" signal fired at the real moment of a track change, for
sources that can actually know one happened — the mixer, a media player,
`playerctl` for anything MPRIS-capable. Owner: "for the right sources...
we could send a track reset signal... but for streams etc we can't do
that unless we try to determine track changes and that seems to be that
it would introduce a whole new pandora's box that we probably shouldn't
open... i agree with your suggestion, but let's just document & defer it
for a while." The blocker is specifically stream sources (internet
radio, anything without real track-boundary metadata) — building
track-change *detection* from audio content alone (a novel, separate
subsystem, not a small add-on) to support them is explicitly out of
scope for this idea; the signal should stay simple and metadata-driven,
built only for sources that can say so directly, whenever this gets
picked back up.

**Round Three, the morning after (part three): a real 100+ second
convergence stall, diagnosed; two persistence-cycle candidates logged;
playlist self-naming fixed for mixer/media.** Owner reported a real live
session (140 BPM → an 88 BPM Shabba Ranks "Steady Man" accident in the
queue, then → a 133 BPM track), packaged as `garbage/m` and analyzed
directly against the raw decision log:

1. **`_BPM_LOCK_RELEASE_CONFIDENCE` cleared as a suspect.** Owner's own
   hypothesis ("maybe our release floor is too low now?") was checked
   against the data and ruled out: that constant only gates the
   `bpm_locked` display/state flag (visibly flickering True/False in
   the log while the BPM *value* sat completely frozen underneath it) —
   a different mechanism from what was actually observed.
2. **Root cause: the real 25-cycle large-jump-persistence gate, not
   idle, but losing a war of attrition against genuinely multi-modal
   candidates.** Both transitions froze for 100+ seconds; `large_jump_
   persistence_reject_count` climbed by ~100-150 during each stall,
   meaning fresh candidates were proposed and rejected every cycle, not
   nothing happening. `long_candidate_median` swung wildly the whole
   time — 139, 107, 92, 86, 127, 171, 82 in one stretch — real,
   harmonically-related readings (reggae/dancehall's one-drop groove is
   a classic case for this), not noise. The gate's only criterion is
   "has the recent window gotten quiet," with no notion of which
   candidate is more likely correct, so when it does eventually clear,
   it's a coin-flip which cluster won — the first transition landed
   briefly on a wrong alias (147 BPM) before gliding to the correct 88.44
   and holding ~49s, then crept back up through 93→108→115→111→108→105
   for the rest of the track; the second transition was still stuck at
   105.78 when the owner ended the session. Same underlying gap as audit
   finding T5 (no octave/harmonic-disambiguation policy), manifesting via
   the persistence gate specifically rather than a simple half/double
   error — full write-up and fix proposal in
   [docs/planning/auto-vj-round-three-planning-2026-08-14.md](../planning/auto-vj-round-three-planning-2026-08-14.md)
   § 17.
3. **Two logged-only candidates for the persistence window itself.**
   Owner: "i told you that 25 candidates was too many! test some more
   reasonable values for that." `_V2_LARGE_JUMP_PERSISTENCE_CYCLES_
   CANDIDATE_SHORT` (10) / `_MEDIUM` (15) evaluated in parallel with the
   real 25-cycle window, own `large_jump_persistence_cleared_count_
   short`/`_medium` and `..._reject_count_short`/`_medium` properties —
   gates nothing yet, pending real comparative data. `_DETECTOR_VERSION`
   → `1.0.0-rc.31`.
4. **Playlist self-naming fixed for dj-mixer-01 and media-01 sessions.**
   Separately, owner: "our training packager is supposed to be
   self-naming it's playlist when the data is available (and it should
   be from the mixer & mediaplayer) but i'm having to type it in every
   time." Root cause: `package_training_set.py`'s existing playlist-name
   inference reads `playlist_context.get('name')` from the active
   now-playing snapshot — real, working logic, but only ever populated
   by spotify-01. media-01's snapshot had a `playlist_context` key that
   was hardcoded `None` despite `self.active_playlist` already being
   real, tracked state; dj-mixer-01's snapshot didn't have the key at
   all, despite `Browser.active_set` (`sets` mode) being its own
   equivalent saved-crate/playlist concept. Both now populate the same
   `{'id', 'name', 'uri', 'total_tracks', 'owner'}` shape spotify-01
   uses, `None` when no named playlist/set is actually active (matching
   Spotify's own "not in a playlist" behavior) — media-01 `0.23.0`,
   dj-mixer-01 `0.186.0`.
5. **Live session check-in, first real data for two of tonight's
   earlier additions.** A concurrently-running "house training 01"
   session (started right at this round's first commit) showed 97.8%
   lock coverage over 30 minutes, mostly clean single-track spans — and
   the first live engagement data for the sparse-evidence gate shipped
   earlier this round: 86 `kick_evidence_reject_count` over the session,
   concentrated in two tracks with more dynamic content, nothing
   alarming.

**Round Three, the morning after (part four): the training packager was
scoring lock quality against the wrong signal all along.** Checking
`training-house-01/c`'s own LLM score (3.5/5, "moderate lock churn")
against a manual read of the same session turned up a real,
previously-invisible gap: every lock-quality computation in
`package_training_set.py` — `scorecard.md`'s rating, `_compute_local_
scores`'s detector responsiveness score, and the LLM prompt itself —
used a **stateless**, memoryless per-row check
(`bpm_confidence >= _BPM_LOCK_CONFIDENCE_FLOOR`, `0.45`) exclusively.
The live app's actual lock indicator, `bpm_locked`, is a **stateful**
Schmidt trigger with hysteresis (gain `_BPM_LOCK_CONFIDENCE` `0.55`,
release `_BPM_LOCK_RELEASE_CONFIDENCE` `0.25`) that rides straight
through an ordinary confidence wobble without ever reading as
unlocked — but that field was already being logged on every corpus row
and simply never read by the packaging/scoring code. A single noisy
heartbeat sample during a ride-through dip counted fully against the
stateless stat, meaning every past scorecard and LLM verdict was
measuring something meaningfully stricter than what the session
actually did.

New `_lock_pct_stateful()` reads the real field. Owner: "let's fix that
logging & packaging issue regarding lock state.. i want to be able to
compare what we were using vs what we *should* be using, so we can sort
of see how they compare and how our previous interpretations may have
been skewed." Landed as an addition, not a swap: `coverage_pct_stateful`
/ `lock_coverage_pct_stateful` now sit alongside the original stateless
fields everywhere (`scorecard.md`, the LLM detector payload, `_compute_
local_scores`'s `_meta`), and the rating/scoring decisions that used to
read the stateless number now read the stateful one instead. The LLM
prompt's `lock_stability`/`confidence_reliability` guidance was updated
to explain the distinction and score primarily against the stateful
figure.

Retroactive comparison across four already-packaged sessions (re-running
both checks directly against their saved sequence-corpus files, no
re-packaging needed) found a strikingly consistent gap:

| Session | Rows | Stateless % | Stateful % | Delta |
|---|---|---|---|---|
| `library/g` (overnight marathon) | 60,926 | 76.5% | 99.5% | +23.0 |
| `library/h` (morning) | 11,406 | 74.7% | 97.0% | +22.2 |
| `garbage/m` (Shabba Ranks flub) | 1,574 | 58.2% | 80.4% | +22.2 |
| `training-house-01/c` | 16,394 | 76.9% | 98.8% | +21.9 |

The gap holds at almost exactly +22 points across every session
regardless of how good or bad the session actually was — three of the
four sessions were actually running at 97-99.5% real lock quality all
night, not the mid-70s the stateless proxy reported every time. `garbage/
m`'s own stateful figure (80.4%) is real evidence the gap is not a flat
correction that would launder a genuinely bad session into looking
fine — it's still the lowest of the four, correctly reflecting that
session's real octave-ambiguity stalls (see the entry above), just from
a less pessimistic baseline than the stateless number suggested.
`training-kit-01` → `0.18.0`.

**Round Three, the morning after (part five): real Essentia was silently
dead on arrival.** Checking `favorites/l` (the "highest scores yet"
session) for a specific owner-reported data point — "Memories," where
the mixer's stored analysis said `128` and the owner's own tap said
`135+` — turned up that `essentia_bpm`/`essentia_key` had been `None`
for every song in every session since the real Essentia wiring shipped
earlier this round, despite `track_path` being populated correctly
(17,681 of 17,683 rows in this session alone). Root cause:
`_load_extract_audio_features()` loads `training_lib.py` dynamically via
`importlib.util.spec_from_file_location()` + `module_from_spec()` +
`exec_module()`, but never registered the module in `sys.modules`
before executing it. `training_lib.py` defines a frozen+slots
`@dataclass`, and `dataclasses` looks itself up via
`sys.modules[cls.__module__]` while the class body is still executing —
without registration that lookup returns `None`, `dataclass()` raises
`AttributeError`, and the surrounding `except Exception` swallowed it
silently, returning `None` from the loader every time. Every essentia
unit test shipped alongside the original wiring mocked the loader
entirely, so none of them ever exercised the real path — exactly why it
shipped broken and stayed that way through several packaged sessions
without a single error surfacing anywhere.

Fixed with the standard `sys.modules[spec.name] = mod` registration
(the same pattern `tests/test_training_optional_essentia.py` already
used correctly, for reference). Also applied proactively to
`_load_live_detector_constants()`/`_load_live_reco_weights()` — latent,
not yet triggered since `beat_grid.py`/`auto_vj.py` don't currently
define a slotted dataclass, but the same bug shape. New unmocked
regression test calls the real loader against the real
`training_lib.py` with a synthetic WAV file (works whether or not
Essentia itself is installed, since the bug was in loading the module
at all).

With the fix, real Essentia and the live detector agree closely on
"Memories" — **131.9 BPM** (Essentia, offline, against the actual file)
vs. **132.6 BPM** (live detector's own session median) — while the
mixer's stored analysis (128) and the owner's manual tap (135+) sit on
either side of that agreement cluster. Two independent methods landing
within 1 BPM of each other, both meaningfully closer to the owner's own
tap than the mixer's stored number, is exactly the kind of real,
triangulated evidence the standing `essentia_note` caveat ("it is
*possible* that our live bpm detection is, or may become, more accurate
than other methods") was written to eventually be tested against.
`training-kit-01` → `0.18.1`.

**Round Three, the morning after (part six): startup confidence raised
again, `0.45 → 0.6`.** Owner: "let's change the cold start confidence
lock score to .6 please." Same conservative-further-step pattern as the
rc.29 bump (`0.4 → 0.45`) — no fresh marginal-case incident driving this
one either, just a further deliberate tightening of how much evidence
the very first lock of a session needs before it's accepted. Still gates
only `self._bpm <= 0.0`; every later re-lock (including at track
boundaries) goes through `_V2_MIN_UPDATE_CONFIDENCE` (`0.25`) unchanged.
`_DETECTOR_VERSION` → `1.0.0-rc.32`. See
`drop-ins/auto-vj-01/docs/weights-and-thresholds.md`.

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

## Round Three Close-Out Batch — one-shot implementation (2026-08-17)

Owner: "let's see if we can knock out all of round 3 in one shot."
Every remaining open item from `docs/planning/
auto-vj-round-three-planning-2026-08-14.md` (minus the explicitly
rc2-scoped config menu, the recommender-phase re-priming revisit, the
deferred centroid recalibrations, T5 Options B/C, and the v3-scoped
HMM/rolling-window/headless items) implemented in one batch: detector
`1.0.0-rc.33`, auto-vj-01 `1.0.0-rc.90`, core `1.0.0-beta.94`, weights
doc v58. Not committed pending owner review/test — this entry records
the decisions.

**Detector (`beat_grid.py`):** interpolation default `False → True`
(the § 5.2 A/B validated it: gate-clear rate `8.5% → 19.9%`, lock
`68.6% → 77.9%`); persistence spread limits become
`max(flat, pct × window median)` (`6.0`/`0.035` long, `4.0`/`0.03`
short — flat floors preserve all validated low/mid-tempo behavior, the
pct term only loosens the fast lanes where the lag grid itself exceeds
the old flat limits; sequenced deliberately after the interpolation
default per the plan's § 6.3 coupling warning); T5 Option A (all four
candidate deques cleared on every accepted large jump); accepted large
jumps and tap-window matches **snap** to the candidate median instead
of crawling through `max_bpm_step` (interaction fix: with Option A's
freshly-cleared deques, a crawling jump would re-stall in the
persistence warm-up for ~3.3 s per step; a 25-cycle-stable median that
also cleared the confidence gate needs no further smoothing);
minimum lock dwell (8-bar default, in-band cumulative drift beyond 4%
of the lock anchor escalates into the large-jump gate stack — the
design sketch's option (c), closing the in-band erosion gap);
cold-start blend guard (first 25 cycles exclude `downbeat_regularity`
— incumbent-confirming at cold start); genre-fit-weighted candidate
scoring (bounded Gaussian reweight from tempo-independent recommender
terms, consulted only while `acf_confidence < 0.5`); tap-tempo trust
window (`tap_prime()`); ACF unbiased-length correction (`n/(n−lag)`,
removing a structural fast-lane tilt); envelope pulse-strength
log-compression; signed phase-error distribution (median/IQR) logging;
energy-slope history time-bounded at 4 s (was 240 frames — broken
above ~120 fps); `candidate_lock_disagreement` property.

**Controller (`auto_vj.py`):** refractory guard — the BPM-fed analyzer
refractory is suspended (confidence 0.0 → analyzer falls back to its
strength-scaled cooldown) while the tracker's own long-window candidate
median disagrees with the lock, closing the last self-confirmation
channel (audit T4; the plan's § 7.5 sequenced this behind confirming
data — implemented now per the owner's close-out instruction, with a
`refractory_guard_enabled` kill switch and an engagement counter so the
first real session both tests the hypothesis and bounds the risk);
mood-prime on MANUAL audio-profile changes only (plan § 4.4 — the
recommender's automatic apply path marks its own applications and is
structurally excluded; primes via `prime_tempo()` from the best raw ACF
candidate inside the new profile's hint band, never a fabricated
number; no in-band candidate → no prime, logged as
`mood_prime_skipped`); `confirm_tap_tempo()` public entry point;
genre-evidence push (tempo-independent subtotal excludes `tempo_fit`,
`top_cand_fit`, `onset_fit`, **and** `kick_regularity_fit` — the latter
two are refractory-/onset-shaped per plan § 6.5); every new mechanism's
engagement counters added to `_detector_snapshot()`.

**Core (`unicornviz/`):** Enter-while-tapper-active hotkey →
`confirm_tap_tempo()` (degrades to a flash when auto-vj-01 is absent;
HELP_TEXT updated per the drop-in hotkey rule); `Overlays.bpm_tap_value`
property; `dubstep` hint band widened `138-142 → 70-160` from
`2hr-dubstep`'s measured bimodal distribution (hints only —
`bpm_prior_mu/sigma` unchanged, the anti-halftime prior is a separate
concern pending a bimodal schema decision).

**Tools:** new `drop-ins/auto-vj-01/tools/bpm_agreement_report.py` —
the § 3.2a per-song agreement table (active vs. shadow vs. shadow2,
mixer-library reference via the track store, MIREX Acc1/Acc2 at ±4%,
octave-family classification of disagreements incl. 4:3/5:4 per
§ 8.6). The LLM column is deliberately unimplemented (separately
scoped per the design; standing policy treats LLM tempo recall as
tiebreaker-grade).

**Deliberately NOT done:** the rc2 config menu (§ 4.3); controlled
genre re-priming (recommender phase); `hard_techno`/`house` centroid
recalibrations (deferred to a library-diversity pass); T5 Options B/C;
the HMM/DBN architecture, rolling rear-view windows, and
faster-than-real-time training (all v3-scoped); per-tick phrase-role
logging (no clean scalar exists, per the plan's own finding).

**Round Three Close-Out, first correction (2026-08-17, same day): a real
regression found via a same-list before/after, and three fixes.**
Packaged `training-house-01/d` (round three) against the immediately-
prior `training-house-01/c` (same 32-track list, pre-round-three) and
found `d` running measurably lower/noisier confidence than `c` — mean
`0.504` vs. `0.593`, and `10.9%` of `d`'s rows sitting within `±0.05` of
the `0.25` lock-release threshold vs. only `2.3%` for `c` — driving a
10x increase in within-track lock toggles (`354` vs. `34`) on identical
content. The worst 5 song-level disagreements between the two sessions
skewed toward the same `4:3` harmonic family this whole investigation
keeps finding (Squabble Up, Velvet After Dark Remix, Habits Stay High).

Two immediate temp mitigations, owner's own call, explicitly
provisional pending a same-list re-run: `_V2_GENRE_EVIDENCE_MAX_BOOST`
`0.35 → 0.1` ("let's change the genre weight to 0.1, we need to do work
before we use that") and `_BPM_LOCK_RELEASE_CONFIDENCE` `0.25 → 0.3`
("let's change release threshold to 0.3 ... this is my idea for at
least a temp fix, while we investigate yours"). The release-threshold
change is *not* a re-opening of the `0.3 → 0.25` correction earlier in
this document — that one was about the gain/release hysteresis gap
being too narrow; this one is about the release threshold sitting in
the middle of a noisier confidence band this round's other changes
created. See `drop-ins/auto-vj-01/docs/weights-and-thresholds.md` for
both constants' full rows.

A third, code-level candidate was investigated directly rather than
guessed at: the ACF unbiased-length correction (`n/(n−lag)`, above)
was A/B tested against isolated in-memory copies of `beat_grid.py` on
synthetic click tracks, with and without a competing `4:3` distractor
onset train (the same ratio family behind the worst-5 song matches).
Confirmed as a real, reproducible contributor — under the distractor
stress test, the unmodified correction produced `18` lock toggles
across two tempos vs. `4` for several dampened variants tested (a
quarter-strength blend, a `sqrt` form, and a `1.10`-capped form all
tied). A clean slow-tempo check (`72` BPM, no distractor) ruled out
regressing the original fast-lane bias the correction exists to fix:
the capped variant tested as functionally reverted right at the low
end where that bias lives (its cap clips nearly all of the needed
correction at `_V2_BPM_MIN`), while the `sqrt` form still applied a
real, non-zero correction there. Owner: "go ahead and land #2" (the
`sqrt` form). `n/(n-lag)` → `(n/(n-lag)) ** 0.5` in both the base-lag
and harmonic-summing loops. See `beat_grid.py`'s own inline comment at
the change site for the full methodology.

All three changes land inside this same not-yet-committed batch —
still `_DETECTOR_VERSION 1.0.0-rc.33` / `_DIRECTOR_VERSION` unchanged
from the close-out bump above, since none of the three have been
validated yet. A same-list (`training-house-01` + `favorites`) re-run
with all three in place is planned before anything here is treated as
settled.

## Round Three Close-Out, first re-run (2026-08-17, later still): mixed results, and a mislabeled set

A session packaged as `20260817-training---house-01/d` (CLI arg named it
after the house training playlist) turned out, on inspection, to have
kept playing the favorites content the deck was already loaded with —
confirmed by comparing distinct-track sets: all 35 tracks in the new
session's corpus match `favorites/m`/`favorites/l` exactly (35/35
overlap both ways), vs. only 6/32 overlap with either
`training-house-01` bucket. Owner: "it got named after the house
training playlist because that's what i passed in from the cli but i
think it played favorites anyway." Treated as the favorites-side
re-run of the three-fix batch above (genre-evidence-boost `0.1`,
release-confidence `0.3`, `sqrt`-dampened ACF); the house-side re-run
against the same 32-track list from the c-vs-d regression is still
outstanding.

Compared to the two prior favorites sessions (`l`: pre-round-three,
`m`: round three + genre/release fixes only, mid-session when the ACF
fix landed so it does **not** carry that change):

| | `l` (pre-r3) | `m` (r3 + genre/release) | new (r3 + all three) |
|---|---|---|---|
| BPM confidence median | 0.548 | 0.514 | 0.499 |
| Lock coverage, real (`bpm_locked`) | 99.2% | 84.6% | 82.0% |
| Lock coverage, stateless proxy | 77.8% | 63.5% | 65.8% |
| Lock event churn | 9 / 8 | 217 / 215 | 187 / 187 |
| LLM detector overall | — | 4.2/5 | 3.8/5 |

Mixed: confidence and the stateless-proxy lock coverage both nudged
back toward the `l` baseline after the ACF fix landed (`m` → new), but
churn — the metric all three fixes specifically target — did not
meaningfully improve (`217/215` → `187/187`, still ~20x `l`'s `9/8`),
and real lock coverage kept falling rather than recovering. The
synthetic ACF A/B harness showed a clean win in isolation; that has not
yet shown up as a clean win on real content, though this comparison is
confounded (different track list length reached, `m`'s early portion
predates the ACF fix entirely, and round three's other structural
changes — dwell requirement, cold-start guard, tap-tempo — are present
in both `m` and new but not `l`).

Squabble Up (one of the five owner-verified-~125 tracks from the
original c-vs-d worst-5 list) is present in the new session: previously
wrong at `162.8` (r3, pre-fix), now predominantly reading `106-107`
(mode `107`, 24% of its rows; mode `104`, 19%) with only ~6% near the
correct `125-126` — a different wrong answer, not a fix. `106.1 ≈ 125 ×
6/7`, suggestive of a different harmonic-family confusion than before,
not investigated further yet.

**On the release-confidence threshold specifically** (owner's own
question: "good effect, bad effect? too much? wrong way?") — the real
data available doesn't isolate it. `_BPM_LOCK_RELEASE_CONFIDENCE` sits
at `0.3` in both `m` and the new session (only the ACF fix differs
between them), and churn is roughly flat across that pair (`217/215` →
`187/187`) rather than climbing further — nothing here suggests `0.3`
made things *worse* on top of round three's other changes. But the
`l` → `m` jump (`9/8` → `217/215`) that originally motivated calling
this a "temp mitigation... sensitive, examine after another run" can't
be attributed to the release threshold alone from this data — `l`
predates all of round three, not just the release-threshold change, so
the comparison is confounded by everything else that landed at once
(dwell requirement, cold-start guard, genre-evidence scoring,
relative-persistence spread limits). Mechanically, raising the release
floor from `0.25` toward `0.3` does exactly what the churn data shows:
releases lock sooner as confidence dips, and real content's confidence
sits close enough to that boundary (`m`/new medians `0.51/0.50`) that a
lot of frames pass through the `0.25-0.3` band where a `0.05` change
has outsized effect — consistent with the standing worry that this
threshold sits mid-noise-band rather than at a clean separation. Not
enough here to call it "wrong way," but also nothing here that clears
it as "working as intended" — an isolated synthetic A/B (mirroring the
ACF harness) would be needed to say more, and hasn't been built for
this constant.

Separately, applied both of this session's LLM tuning recommendations
that weren't already in place (`tools/package_training_set.py`'s
scoring pass on the same, misnamed set): `_BPM_LOCK_CONFIDENCE` `0.55 →
0.6` ("Increased lock confidence threshold might reduce occasional
low-confidence errors observed at stable tempos") and `tempo_fit`
`2.0 → 2.2` ("Tempo alignment appears critical in this session,
suggesting a slight upweight improving accuracy"). The report's third
recommendation, `phrase_under_over_hold_mult` `0.7 → 0.8`, was already
applied at rc.7 above — a stale duplicate suggestion, not a new change.
Owner: "let's apply all three llm recommendations." Unlike the three
temp-mitigation fixes above, these are direct LLM-recommendation
adoptions in the same pattern as rc.5/rc.14/rc.15/rc.16, so they *do*
carry version bumps: `_DIRECTOR_VERSION` → `1.0.0-rc.8`,
`_RECOMMENDER_VERSION` → `1.0.0-rc.17`, `_VJ_WEIGHTS_DOC_VERSION` →
`59`. The three-fix regression investigation above remains unsettled
and unbumped pending the still-outstanding house-list re-run.

## Manual-Override 'auto' Parity + 'tweaker' Mood (2026-08-17, later still)

Two selectors exist for controlling the VJ's automatic decisions, and
until this entry they had inconsistent, confusing manual-override
behavior:

- **VJ mood preset** (`chill`/`normie`/`raver`, `_PROFILE_PRESETS` /
  `cycle_profile()` / `self._manual_profile`) — controls reactivity/
  speed/zoom/effect-tag intensity, auto-selected from BPM range via
  `_desired_auto_profile()` (chill ≤105 BPM, raver ≥126 BPM, normie
  between; requires confidence ≥ `auto_profile_min_confidence` (0.45),
  raver's own floor relaxed to ~0.34; **8s hold** before a new candidate
  actually switches, plus a **120s cooldown** between switches regardless
  of hold). `cycle_profile()` already implemented a full `'auto'`-capable
  manual-override cycle, but it was wired to `register_midi_action_handler
  ('auto_vj_profile_cycle', ...)` only -- no keyboard binding existed at
  all, so the only way to know or change the mood was reading MIDI-pad LED
  state. Owner: "the current indicator driven method is not very
  intuitive we can kill that."
- **Genre/BPM audio profile** (`house`/`dubstep`/`trance`/etc,
  `AudioManager.set_profile()`, cycled via `Alt+A`/`Alt+Shift+A` in
  `hotkeys.py`) — had no `'auto'` concept at all. A manual pick called
  `audio_manager.set_profile()` directly with zero relationship to
  `_profile_auto_reco_decider_enabled` (the recommender's automatic-apply
  flag), so a manual correction had no persistence AND no explicit way
  back to auto -- exactly the long-standing "correction vs lock" gap (see
  memory `audio-profile-correction-vs-lock`): the recommender could
  silently reassert its own pick later with nothing tracking that a
  manual override had ever happened.

Fix, both landed together (owner: "let's have both mood & genre selectors
have an 'auto' option that releases the vj's over-ride"):

- New `AutoVJController.cycle_audio_profile(audio_manager, reverse=False)`
  -- mirrors `cycle_profile()`'s exact pattern for the genre/BPM profile:
  cycles `['auto'] + audio_manager.list_profiles()`; landing on `'auto'`
  re-enables `_profile_auto_reco_decider_enabled`; landing on a specific
  key disables it and calls `set_profile()` directly, tagged the same
  `'manual_override'` way as the mood cycle for the training pipeline.
  New `_manual_audio_profile` tracks this cycle's own state, independent
  of `_manual_profile` even though both currently share the one
  `_profile_auto_reco_decider_enabled` flag (cycling either selector's
  manual override off disables the decider; either's `'auto'` re-enables
  it -- they are not separate locks, a deliberate simplification for now).
- `hotkeys.py`'s `Alt+A`/`Alt+Shift+A` now route through
  `cycle_audio_profile()` when `auto_vj_controller` is present, falling
  back to the old raw profile-list cycle (no `'auto'` entry) when the
  drop-in is absent -- drop-in independence preserved.
- `cycle_profile()` (the mood cycle) itself is unchanged -- stays
  MIDI-pad-only. An initial version of this change also wired it to a new
  keyboard hotkey (`Alt+O`); reverted same day, owner: "i didn't ask for
  a new hotkey... we already had ctrl+j-m.. alt+0 is an effect shortcut."
  `Alt+O` also collides with the already-planned `Ctrl+Alt+O` Control Room
  toggle (`docs/planning/hotkey-cross-platform-conflict-remap-plan-
  2026-06-03.md`) -- a second, independent reason it was a poor pick even
  setting the "wasn't asked for" issue aside.

Also landed the same session, owner: "add a 'tweaker' mood that can only
be manually selected that basically turns everything all the way up :)"
-- a new `_PROFILE_PRESETS['tweaker']` entry, built from `raver` (the
prior ceiling) with every VISUAL intensity/pacing dial pushed further:
wider reactivity/speed/zoom range, faster slew, shorter effect dwell
(6-20s vs raver's 12-40s), shorter cycle refractory, higher ping-pong/
postfx/scrollfx trigger chances and rotation degrees. Deliberately left
the director state-machine's own confidence/energy GATING thresholds
(`mode_entry_min_confidence`, drop/climax entry scores, build/breakdown
energy thresholds) at raver's values unchanged -- "all the way up" means
visual output, not defeating the coherence gates that tie transitions to
real audio evidence. `tweaker` is manual-only by construction:
`_desired_auto_profile()` only ever returns `'chill'`/`'normie'`/
`'raver'` literals, so it can never be BPM-auto-selected, only reached via
`cycle_profile()`'s manual list -- verified by sweeping the full practical
BPM/confidence range in `test_tweaker_is_never_returned_by_the_auto_bpm_
selector`. Also extended the three `self._profile != 'raver'` ping-pong/
postfx gates (`_maybe_start_auto_pingpong`, `_maybe_start_preset_pingpong`,
the post-FX ping-pong auto-start) to `('raver', 'tweaker')` -- these were
deliberately raver-exclusive high-energy features, and tweaker being
"raver but more" should include them too.

`_DIRECTOR_VERSION` → `1.0.0-rc.9`, `auto_vj.py` `__version__` →
`1.0.0-rc.91`. Tests: `tests/test_auto_vj_target_labels_and_weights.py`
(`cycle_audio_profile()` cycle/decider/reverse behavior, the tweaker
preset's existence and intensity-dial comparison against raver, the
never-auto-selected sweep) and `tests/test_hotkeys_behavior.py` (`Alt+A`/
`Alt+Shift+A` routing through `AutoVJController` when present, falling
back cleanly when absent).

## Refractory Guard Band Decoupled + Onset-Strength Logging (2026-08-17, later still)

Follow-up from asking "did you analyze the other new things and see if
any of those need tweakin'" against real data from four post-round-three
sessions (`training-house-01/d`+`e`, `favorites/m`+`n`), not just the
synthetic harnesses built earlier the same day.

**Refractory guard band.** `candidate_lock_disagreement` (the guard's
detector half) was reusing the jump-gate's `_V2_LOCK_BAND_PCT`/`_MIN`
(`0.03`/`4.0`) — a band `rc.26`/`rc.28` deliberately tightened for a
different job (catching individual in-band erosion steps). Real data
showed the guard engaging ~9-11 times/sec against that tight band,
essentially continuous rather than the rare wrong-lock rescue it was
designed for: a noisy real ACF candidate falls outside a `±3%`/`4` BPM
band often even when the lock is genuinely fine. Split into its own
`_V2_REFRACTORY_GUARD_BAND_PCT`/`_MIN` (`0.16`/`10.0` — the pre-
tightening original values), config-overridable
(`refractory_guard_band_pct`/`_min`), independent of any future jump-gate
band retuning. Owner: "let's make the change you recommend to the
refractory guard." `_DETECTOR_VERSION` → `1.0.0-rc.34`.

**Onset-strength logging.** The envelope pulse-strength log-compression
(`_pulse_envelope()`, `rc.33`) had zero real-session evidence — the only
supporting data was `tools/pulse_compression_harness.py`'s synthetic A/B.
Owner, on realizing the gap: "add the additional data we're missing, we
shouldn't be missing anything! crikey lol." New `BeatTracker.
onset_strength_max_raw`/`_max_compressed` properties, backed by a
`_V2_ONSET_STRENGTH_WINDOW_S`-bounded (10s) rolling history of `(t, raw,
compressed)` per onset — same time-bounding convention as
`_V2_ENERGY_WINDOW_S`. Wired into `_detector_snapshot()` (so every
sequence-corpus row carries the window's max of each) and into
`package_training_set.py`'s "Round-Three Mechanism Engagement" scorecard
section (session-wide max, `training-kit-01` → `0.21.0`) — the same
gap-closing pattern `phase_error_median`/`_iqr` used for the phase-
alignment investigation.

Tests: `tests/test_round_three_closeout.py` (band-widening behavior with
an in-between-the-two-bands median that must NOT read as disagreement
under the new band, config overrides reach the instance, onset-strength
max-raw/max-compressed track the log-compression formula exactly, window
pruning). `auto_vj.py` `__version__` → `1.0.0-rc.92`,
`_VJ_WEIGHTS_DOC_VERSION` → `60`.

## Onset-Strength Runaway Bug: MAD Floor Fixed + Cap Added (2026-08-17, later still)

The new `onset_strength_max_raw` logging above found something the very
session it landed: a real value of `1,171,176,147`. Root cause in
`unicornviz/audio/analyzer.py` (core, not auto-vj-01):
`Analyzer._onset_threshold()`'s `mad = median(|flux - median|) + 1e-6` --
`1e-6` is a literal-division-by-zero guard, not a reasoned floor. During
a near-silent/degenerate flux stretch real MAD collapses toward zero, and
the strength computation two lines away (`(flux - threshold) / mad`)
divides by almost nothing on the next real transient.

Owner: "look into that mad floor/clamp issue.. what is the most proper?
can u sim it up and give us the best running start?" Built `tools/
onset_strength_mad_floor_harness.py` (main repo, not the drop-in --
this is core code) and swept candidate floors/formula shapes against
three synthetic scenarios: the pathological case (degenerate quiet ->
real transient), a genuinely quiet section with a weak-but-real onset
(must stay discriminable, not collapse to indistinguishable-from-noise),
and normal/loud material (a floor fix should be a true no-op once real
MAD already exceeds it). Two findings shaped the fix:

1. `max(raw_mad, floor)` beats `raw_mad + floor` (the live formula's
   shape) -- the additive form keeps inflating MAD, and dulling
   strength, even on well-populated material once the floor value grows;
   `max()` -- the same floor idiom `beat_grid.py` uses throughout --
   only engages when real MAD would actually be smaller than the floor.
2. `_BEAT_ABS_FLOOR` (`0.02`, already established for `threshold`'s own
   absolute floor) is the right floor value for `mad` too, not a fresh
   arbitrary constant -- it fully tames the pathological case (~48 vs.
   ~980K+ in simulation) while keeping real weak-vs-loud discrimination
   alive in genuinely quiet material (2.45x, vs. collapsing to 1.0x at a
   more aggressive `0.05` floor).

Landed `mad = max(raw_mad, _BEAT_ABS_FLOOR)`, plus a new
`_ONSET_STRENGTH_CAP = 50.0` hard clamp at the strength computation site
-- independent of the floor fix, a backstop for whatever the floor
doesn't anticipate, protecting every consumer of raw strength (not just
`beat_grid.py`'s own log-compression, which only protects the ACF
envelope specifically). Confirmed directly against the real `Analyzer`
(not just the synthetic harness): the exact "silence then kick" scenario
already covered by `tests/test_analyzer_onset_dedup.py` hits the cap
exactly (`50.0`) under the fix -- this is the live regression case, not
a hypothetical. Core `unicornviz.__version__` → `1.0.0-beta.98`.

## Lock Hysteresis Isolated at Last: Release Value, Not the Gap (2026-08-17, later still)

`_BPM_LOCK_RELEASE_CONFIDENCE` had walked `0.28 → 0.3 → 0.25 → 0.3 → 0.2
→ 0.35` across this whole multi-day investigation, every single move
justified by a real-session comparison that also changed something else
at the same time (round three's broader batch, the ACF fix, the
genre-evidence reweight). `0.35` landed as `training-house-01/f` and was
the worst house result yet — confirmed with a clean same-track paired
comparison against `e` (all 6 opening tracks worse, one nearly halved:
`89.9% → 46.2%` lock coverage).

Owner: "so .25 release then lock should be .55, or .3 then .6? what do
you think our optimal settings are for those two?" — then, to actually
answer it instead of guessing from another confounded comparison: "yea
let's try synth with: .30/.6, .25/.6, .20/.6, .30/.55, .25/.55, .20/.55
... and then apply the best and i'll run a long one."

Built `tools/lock_hysteresis_gap_harness.py` (`auto-vj-01`): replays the
real, already-captured confidence trace from four `training-house-01`
sessions (`c`/`d`/`e`/`f`) through the *exact* Schmidt-trigger state
machine (`AutoVJController.update()`'s own logic, ported verbatim) under
all 6 candidate `(release, gain)` pairs, holding the real audio/detector/
confidence numbers completely fixed — the one isolated test this
constant never got in its whole history.

**Result reframed the question.** It was never really about the
gain-minus-release "gap": two pairs sharing the identical `0.30` gap
(`0.30`/`0.60` vs. `0.25`/`0.55`) produced `17.55` vs. `6.48` mean
churn/1000 rows — wildly different. The **release value itself** is the
dominant lever, almost independent of gain: `release=0.30` churned high
regardless of gain (`17.55-20.52`), `release=0.25` dropped sharply to
`5.48-6.48`, `release=0.20` lowest of all (`1.87-2.00`) — gain `0.6` vs.
`0.55` only ever produced a `~15%` difference at a fixed release value.

But the harness measures hysteresis *stability*, not detector *accuracy*
— it has no ground truth for whether a held lock is actually right, only
whether it stayed held. Owner's own real-session read on `0.20`
(`training-house-01/e`, the lowest-churn setting ever tested live): "i
thought e was not very good" — despite it winning on every metric this
session was originally scored on (confidence, lock coverage, LLM score).
A sticky lock holds a stale/wrong BPM longer too; that cost doesn't show
up in a churn count.

**Landed `0.25`.** It's the one prior release-confidence value ever
validated against real backtested lock-loss data (rc.6, above — not just
a session-level comparison), it sits at the elbow between `0.30`'s
confirmed-bad churn and `0.20`'s confirmed-not-great real-session
experience, and it's a real `~3x` churn improvement over `0.30` per this
harness's own numbers. `gain` stays at `0.6` (harness confirms it's
still marginally better than `0.55` at every release value, and it was
independently validated on its own merits already). `_DIRECTOR_VERSION`
→ `1.0.0-rc.10`, `auto_vj.py` `__version__` → `1.0.0-rc.93`,
`_VJ_WEIGHTS_DOC_VERSION` → `61` (also caught and fixed: the doc header's
own `Director version` had been stale at `rc.8` since the tweaker/mood
work landed at `rc.9`).

## Drop Trigger/Sustain Split — the Drop-Score Redesign Lands (2026-08-18)

Owner green-lit the 2026-08-11 redesign plan's § 4 with the music-theory
audit's corrections folded in (F1/F2/F3/F4/F9; F8 explicitly excluded —
"super touchy, deal with in isolation"). Detector `1.0.0-rc.35`,
director `1.0.0-rc.11`, auto-vj `1.0.0-rc.97`, core `1.0.0-beta.99`,
weights doc v62. Rollout: default ON, `drop_signal_engine = 'legacy'`
as the one-line restore (owner decision).

**What.** `drop_score` was one number doing two jobs (boundary
detection and section classification — separate tasks in the
literature). Split: `impact_novelty` (trigger — bass transient ×
broadband residual activity × was-bass-suppressed × slope influence,
multiplicative coincidence) and `drop_sustain` (state —
`bass_level_norm × (0.3 + 0.7·busyness)`, a product so zero bass forces
zero: the "no bass, no drop" invariant becomes structural, ending the
margin bookkeeping the rc.7 weight swap needed). Both derive from a new
raw-path level channel (`AudioData.bass_level_raw`, read BEFORE the
per-frame max-normalization that turns band levels into shape
fractions — audit F1's root cause) via a two-timescale primitive: fast
EMA (τ 0.3 s) against a rolling p20 reference over a 90 s ring,
range-normalized by (p80−p20). The percentile form was chosen OVER the
plan's asymmetric-alpha z-score, whose stated direction was
ambiguous-to-inverted for the sustain job (audit F4) — a percentile
reference cannot renormalize during a held drop by construction.

**Director consumption.** Entry: BUILD normal = trigger OR established
sustain; fastlane = strong trigger; BREAKDOWN→DROP direct = trigger
only; timeout = relaxed sustain floor. Fizzle: relative to this drop's
own sustain peak (×0.9) with an absolute floor, reading `drop_sustain`
only, below-target held a full bar — the legacy composite renormalizes
~24 % on a held, unchanging drop and is beat-rate spiky between kicks,
so a relative check against it exits healthy drops (audit F2's exact
predicted misfire). CLIMAX/IMPACT deliberately stay on the legacy
`drop_score` ladder in v0 (their thresholds are tuned on that scale;
migrating them is a separate, data-first decision). `band_blend`
weights reverted `0.7/0.2/0.1 → 0.45/0.30/0.25` in both engines
(§ 4c, decided in the plan).

**Empirical grounding.** `_V2_MIDTREB_FLUX_NORM_C = 180` = pooled
fast-EMA median over 11 real library tracks / 72.6k accelerated-replay
ticks (the audit's "median maps to 0.5" discipline);
`drop_trigger_threshold` defaults sit at ≈ p99 of the pooled
impact_novelty distribution (triggers are rare events); sustain entry/
floor bracketed by the measured breakdown (~0.18) vs groove (~0.50)
readings. First director-in-the-loop check via `session_replay.py`
(6 real tracks): 39 mode transitions, 11 drop fires, IMPACT ×3,
CLIMAX reached, all four fizzle/entry counters engaging — vs the
legacy path's 21/12 with no IMPACT/CLIMAX on the same tracks/seed.
Numbers logged per-row (signals + 4 engagement counters in the
sequence corpus) so live sessions accumulate tuning data from day one.

## Recommender Goes Genre-Pure — tempo_fit / top_cand_fit Zeroed (2026-08-20)

Stage 1 of the genre-intelligence / candidate-matching plan
(`docs/planning/auto-vj-genre-intelligence-candidate-matching-2026-08-20.md`),
owner-directed: "remove tempo fit entirely and then rebalance the weights
to the best of our ability via best guess for the first runs and once we
get it reasonably tuned we'll work on the interoperability." Asked
whether `top_cand_fit` (the other detector-BPM-consuming term) goes too:
"remove both."

Recommender `1.0.0-rc.17 → 1.0.0-rc.18` (the bump rule's retiring-a-term
case: the composite's meaning changed from genre+tempo-agreement to a
tempo-blind, rhythm-aware genre score). Weights doc → v63; auto-vj →
rc.98. Mechanics: both terms **zeroed, not deleted** — still computed and
corpus-logged per candidate (`term_values_by_candidate`), because the
future BPM/genre matcher needs exactly that tempo-vs-genre comparison
data, and because keeping the term list stable preserves the promoted-
weights file format and every downstream telemetry consumer.

Rebalance (best-guess, first-runs, ~7.5 total weight vs 7.9 before):
`spectral_shape_fit 1.4 → 2.2` (new lead — most repeatedly validated
pure-timbre term, no open bugs), `onset_fit 1.0 → 1.5` and
`kick_regularity_fit 1.0 → 1.5` (rhythm-character terms the owner's
isolation rule explicitly keeps), `zcr_fit 0.6 → 0.9`, `centroid_fit`
**held at 0.5** (formula-mismatch bug still open — deliberately not
amplified), vocals `0.3/0.4 → 0.4/0.5` (bigger share of vocal-genre
separation absent tempo; still lightest, targets unvalidated).

**Interim risk, accepted with eyes open:** until the matcher lands the
recommender has no tempo grounding at all — the chillstep-at-130 failure
class (the reason the BPM-prefilter ADR above exists) is possible again.
Containment: detector_trust confirmation gating and decider margins are
unchanged, `mismatch_pct`/switch-rate telemetry will show degradation
within a session, and the one-way-flow rule means a wrong genre pick
cannot touch the detector's tempo. Ground-truth approach also decided
this session: Essentia is a library/models, not a harvestable dataset —
so its analysis gets logged side-by-side with ours per session and we
tune toward *our own* interpretation of correctness where they disagree
(same pattern as the existing essentia_bpm/essentia_key columns), rather
than treating it as gospel.

## F8 Fixed: the Kick Band Was Sub-Bass, Off by a Factor of Two (2026-08-31)

The audit's F8, deliberately quarantined by the owner ("super touchy,
deal with that in isolation") until today's dedicated session. Director
`rc.11 → rc.12`, recommender `rc.21 → rc.22`, weights doc → v67,
auto-vj → rc.101.

**The bug.** Every kick-regularity consumer — the director's
kick-confirmed build, kick-dropout early breakdown, IMPACT/CLIMAX
dropout override, the detector's tactus-eagerness and kick-evidence
gates (fed via ``update(kick_regularity=)``), and the recommender's
`kick_regularity_fit` — was driven by `bands[0:6].mean()`, whose
comment claimed "~31–99 Hz." On the 64 log-spaced 30 Hz→16 kHz axis,
band edge 6 = 30×(16000/30)^(6/64) ≈ **54 Hz**: the signal measured
30–54 Hz sub-bass/rumble regularity, not 50–100 Hz kick fundamentals —
working by proxy on sub-heavy material, under-reading on anything whose
kick lives higher. `exp_kick` read `expected_bands[0:6]` with the
identical offset.

**The fix.** `bands[0:12]` (edge 12 ≈ 97 Hz) at the live sampling site,
`exp_kick` (`range(12)`), and the replay-harness mirror, all together
per the audit's own instruction. The audit's stronger alternative
(sampling raw-path `bass_flux` at onsets) stays open as a future
upgrade, noted at the sampling site.

**Why no thresholds moved.** Measured before committing (16 real
library tracks, live-faithful accelerated replay, both windows computed
side by side): per-track median kick_regularity p50 `0.737 → 0.795`,
p25 `0.645 → 0.704`; the ≥0.60 kick-confirmed gate passes the same
0.81 of tracks under both windows, and <0.30 dropout medians go
`0.06 → 0.00`. The tuned 0.60/0.30 gates keep their meaning; the shift
is a modest, uniform brightening, not a recalibration event.

**Known, accepted consequence.** `exp_kick`'s genre spread compresses
(pre → post: rap_rnb `0.455 → 0.676`, hyphy `0.263 → 0.523`, chillstep
`0.325 → 0.571`, dubstep `0.938 → 0.838`) because 808/sub-bass content
occupies the honest kick window too — `kick_regularity_fit` now
separates four-on-the-floor genres less sharply than the wrong band
accidentally did. The underlying conflation ("energy in the kick band"
≠ "expects REGULAR kicks") is flagged for the Stage 1 label-driven
recalibration, which this fix un-blocks: the training session's
2026-08-31 warning — don't recalibrate kick targets against a
wrong-band input — is now satisfied.

**Validation:** 2 random-seed accelerated replay runs each over
favorites, training-house-01, and toughies, executed by the training
session against rc.101 (owner-directed split of labor).

## The Candidate Matcher's LOW Half Lands — Genre Evidence Becomes Candidate Endorsement (2026-08-20)

Recommender `rc.20 → rc.21`, weights doc → v66, auto-vj → rc.100.
Completes the genre-intelligence plan's two-regime integration (§ 5):
the HIGH half (BPM prefilter, rc.20) constrains genre by confident
tempo; this LOW half lets genre disambiguate tempo *among the
detector's own hypotheses* when the ACF is unsure.

**Mechanism.** Each recommender eval: take the detector's top-2 raw ACF
candidates (bpm, normalized comb score) and the top-3 genre candidates
by tempo-independent composite (softmax probabilities; § 6.5's
exclusions unchanged — onset/kick stay out of *evidence* even though
they stay in the genre score). Score every pair `det_score ×
genre_prob × range_fit` (range_fit: 1.0 inside the genre's hint band ±
the shared prefilter margin, linear decay beyond). The winning pair
pushes its **detector-candidate BPM** through the existing
`set_genre_tempo_evidence` channel — tight sigma (0.06 log2, config
`genre_matcher_endorse_sigma`) because it endorses one specific ACF
hypothesis, not a genre's whole range — with a margin-style weight.
The detector's low-confidence consumption gate (round three's, with
its own hysteresis) remains the LOW-regime arbiter, and the
`_V2_GENRE_EVIDENCE_MAX_BOOST` bound still caps influence.

**What it replaces.** The round-three genre-evidence push sent the
winning genre's *prior μ/σ* — weight-shaped, and capable of pulling
toward a tempo the ACF never proposed. The matcher can only ever
endorse an ACF-proposed candidate: one-way flow is now structural at
the evidence level too. Legacy push kept verbatim behind
`genre_matcher_enabled = false` as the rollback switch.

**Stage 1 measurement findings, recorded same batch (no action
taken):** live-formula measurements per BPM tempo-family over the
library found real onset-density ≈ flat (~4.0-4.6 onsets/s medians
across every family; also refractory-shaped live, so offline readings
without the BPM feedback overstate it) and real zcr both ~2-4× below
the authored μs and family-order-inverted (trance-family darkest at
~0.014 vs μ 0.08-0.09). After the centroid lesson (retiring a
miscalibrated term destabilized the composite), NO further weight or
μ changes were made — onset/zcr recalibration is explicitly blocked on
Stage 0 Essentia labels, and the matcher + prefilter bound the harm of
the miscalibration in the meantime.

## BPM Hard Pre-Filter Lands Early (2026-08-20, same day as the retirement)

The 2026-08-13 "BPM as a Hard Recommender Pre-Filter" ADR (above,
owner-approved, deferred to RC2) is now live — pulled forward the same
day centroid_fit's retirement exposed what it exists to contain: with
the accidental low-mu penalty gone and mu/sigma recalibration not yet
done, a pure-house replay's recommender scattered across 11 profiles
and the decider APPLIED drum_and_bass (463 rows) and dubstep (176).
Implementation per the original design: eligibility gate before
scoring (never a score term — the genre composite stays tempo-blind),
`bpm_hint` range ± 15% against the Schmidt-locked tempo, unfiltered
when unlocked (the future matcher's LOW half), full-exclusion falls
back to unfiltered with a `fallback` counter so a fold-error lock
can't silence the recommender. Recommender `rc.19 → rc.20`, weights
doc → v65. Counters + per-eval excluded-list telemetry from day one.
Known accepted leak: dubstep's round-three-widened 70-160 hint band
keeps it eligible at nearly any tempo — that is v3 Thread 5's
bimodal-representation problem, not this gate's. Post-fix replay
(same 6 house tracks, same seed): recommendations re-concentrated to
the house family and zero wrong-family profiles were applied.

## centroid_fit Retired — the Formula-Mismatch Bug Closes as Unfixable (2026-08-20)

Owner: "fix the centroid bug please." The sanctioned fix path (recorded
at the live formula's comment since 2026-08-11: recalibrate
`spectral_centroid_mu` against real measured data, then retry the
log-band basis) was executed — and disproven by its own first
measurement, so the resolution is retirement, per the genre-intelligence
plan's "fix-or-retire on evidence" rule. Owner confirmed retire over
recalibrate. Recommender `rc.18 → rc.19`, weights doc → v64, auto-vj →
rc.99.

**The measurement.** 57 real library tracks, tempo-family-labeled from
mixer-store BPM (the designated ground truth; families slow/midlow/
house/peak/fast by hint-range boundaries), 60 s each through the real
Analyzer. Five brightness formulations:

- Log-band centroid (`PERC_BAND_CENTERS_HZ · bands`): family medians
  200-445 Hz vs profile μs of 950-2650 — the 2026-08-11 ambient
  incident's mechanism confirmed quantitatively — and the family
  ordering INVERTED (fast=200 darkest, slow=445 brightest).
- Live linear-FFT centroid: medians 2983-3872 Hz, ~900 Hz total family
  span vs within-family p25-p75 up to ~1900 Hz; slow above peak, house
  highest. Also: every family median sits above nearly every profile μ,
  so the term has acted as a mastering-brightness penalty, not a genre
  signal, its entire life.
- Log2-frequency centroid, ≥4 kHz energy fraction, rolloff-85: same
  picture in every case (within-family spread 2-4× between-family
  separation, genre-nonsensical orderings).

**The conclusion.** Scalar brightness of a mastered full mix carries no
tempo-family genre signal in this library — it tracks production and
mastering. The genuine spectral-genre evidence lives in the full
distribution, which `spectral_shape_fit`'s 64-band cosine already
scores at full resolution: this is the `band_fit` redundancy argument
(2026-08-14) again, now with measurements instead of reasoning.

**Mechanics.** Weight `0.5 → 0.0`; the term stays computed and
corpus-logged (telemetry), profiles keep their `spectral_centroid_mu`/
`sigma` fields, and the live linear-FFT measurement (with its
sample-rate-aware Hz axis) is unchanged — so nothing downstream breaks
and the decision is one weight-line to revisit if Essentia-labeled
sub-family data (genre-intelligence plan Stage 0) later reveals a
signal the family granularity hid. `PERC_BAND_CENTERS_HZ` remains for
its other legitimate uses. The eight-move weight walk this term caused
(0.8→1.5→1.3→1.0→0.8→0.5→0.3→0.7→0.5) is over.

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
- ~~**2026-08-14, flagged not fixed:** the tempo-hold gate (`_tempo_hold_
  until_t`) blocks re-evaluation specifically when `acf_conf >= 0.45` and
  refreshes on every accepted update...~~ — **resolved 2026-08-14, the
  morning after.** Gate removed entirely — a 20-transition-pair sweep
  showed 4/20 converged with it vs. 20/20 without (almost all within
  5-9s); the owner's own alternate proposal (don't refresh the hold on an
  out-of-band step) was tested head-to-head and was 5-10× slower with no
  compensating benefit, so full removal won. See "BPM-Value Accept/Reject
  Gate Stack" and "Tempo-Hold Gate Removed + Grid-Split Wobble Fixed"
  below.
- ~~**2026-08-14, flagged not fixed:** a *transition* from an existing lock
  onto genuinely different tempo material doesn't converge as cleanly as a
  *cold-start* lock...~~ — **resolved 2026-08-14, the morning after.**
  Was the tempo-hold gate above, not a tactus-fold/region-consistency
  effect as first suspected — confirmed by a direct A/B (clearing the
  beat-position map at the transition boundary changed nothing; disabling
  the hold gate alone fixed it). Fixing the gate surfaced a *separate*
  real issue — a "grid-split wobble" near tempos that fall in a gap in
  the ACF's discrete lag grid — fixed the same session with
  `_V2_LARGE_JUMP_PERSISTENCE_CYCLES`. See "Tempo-Hold Gate Removed +
  Grid-Split Wobble Fixed" below.
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
- **2026-09-04, to be considered, not pursued now:** a true Constant-Q
  (or wavelet filter-bank) transform for the 64-band perceptual spectrum,
  as a future alternative to the dual-window fix landed the same night
  (see "Low-Band Resolution: Dual-Window Fix" below). A CQT gives each
  band its OWN analysis window sized to its own frequency (long for bass,
  short for treble) — the theoretically correct match to a log-spaced
  band scheme, rather than one uniform-window FFT bucketed into log
  bands after the fact. Not pursued now because it's a genuinely
  different architecture, not a parameter change: no shared FFT to reuse
  across `bands`/`spectral_flux`/vocal features the way `Analyzer.
  process()` does today, each band computed by its own resonant
  filter/window with its own time constant, all of which need to agree
  on a consistent energy scale for cross-band comparison to still work.
  Efficient (recursive octave-downsampling) implementations run roughly
  3-10x a single equivalent FFT's cost — real but not prohibitive — the
  actual cost is implementation/testing surface area and no precedent in
  this codebase, not CPU. Revisit only if the dual-window fix turns out
  to have real problems in practice.

## 2026-08-31 Accelerated Tuning Experiment — Consensus Landing (2026-09-01)

Owner-directed multi-hour experiment: strategist session + training
session, ~44 accelerated replay runs (20-25x) across 4 playlists with
full LLM+Essentia scoring, one-variable-at-a-time with fixed seeds
{3, 11}, hard-metric veto, per-track corpus diffs on every anomaly.
Full evidence trail in the (deliberately gitignored) experiment ledger
`logs/replay/EXPERIMENT-2026-08-31.md`; landed in auto-vj-01 `rc.102`
(detector `rc.36`, recommender `rc.23`, weights doc v68).

**Changed:**
- `_V2_DWELL_BARS` 16 → 32 (detector rc.36). Deciding curveballs pair:
  churn −32% (s11, largest churn win of the experiment), Acc1 +8 (s3),
  coverage +3.1-3.5pt; house churn −9%/inert. The earlier in-experiment
  rejection of 32 was proven margin-confounded (bit-identical toughies
  corpora across dwell/sigma/pure-margin runs).
- `profile_reco_bpm_prefilter_margin` default 0.15 → 0.10 (recommender
  rc.23). 4/4 clean sweep house+curveballs (Acc1 +8/+7, Acc2 +7/+8,
  genre-acc +5/+5). Documented tradeoff: toughies churn +22/+32%,
  coverage ~−5pt — the shared floor math evicts edge-rider genres
  (trance floor at 0.10 = 120.6 sits exactly on real house locks).
  Accepted per the owner's ruling below; the margin SPLIT (prefilter vs
  matcher) is the planned recovery.

**Validated, no change:** `_BPM_LOCK_RELEASE_CONFIDENCE` 0.2 (0.225 and
0.25 rejected monotonically; house churn +39/+45% at 0.225);
`_V2_GENRE_EVIDENCE_MAX_BOOST` 0.1 (bracketed 0.0/0.2/0.5/1.0 — the
2026-08-17 owner park is empirically optimal pre-recalibration; dose
sweep established the evidence-amplifier law: gain amplifies evidence
QUALITY — rescues hidden fold errors when right, house s3 Acc1 +10 at
1.0; captures/harasses when wrong); `genre_matcher_endorse_sigma` 0.06
(0.04 behaviorally inert); margin 0.08 rejected (curveballs s11).

**Owner rulings recorded:** (1) toughies is diagnostic-only, NOT a veto
set — optimize for average-track material ("we can totally allow
anomalies in the toughest tracks"); (2) dwell 8 was "most likely way
too low" — confirmed; (3) config overrides for dwell/ACF-interpolation
removed permanently in the same landing.

**Process lesson (cost us a double verdict-reversal):** isolate every
candidate on EVERY veto-set playlist before accepting — Iteration 2's
quartet omitted toughies and four subsequent iterations inherited the
confound until a confirmation pair exposed it via trajectory-hash
bit-identity.

Follow-up roadmap:
`docs/planning/recommender-director-excellence-plan-2026-08-31.md`.

## 2026-08-31 Accelerated Tuning Experiment — Consensus Landing (2026-09-01)

Owner-directed multi-hour experiment: strategist session + training
session, ~44 accelerated replay runs (20-25x) across 4 playlists with
full LLM+Essentia scoring, one-variable-at-a-time with fixed seeds
{3, 11}, hard-metric veto, per-track corpus diffs on every anomaly.
Full evidence trail in the (deliberately gitignored) experiment ledger
`/tmp/claude-1000/-home-jj-Repos-unicorn-viz/82717ea2-2206-47c0-8084-12931b40672b/scratchpad/EXPERIMENT-rebuild.md`; landed in auto-vj-01 `rc.102`
(detector `rc.36`, recommender `rc.23`, weights doc v68).

**Changed:**
- `_V2_DWELL_BARS` 16 → 32 (detector rc.36). Deciding curveballs pair:
  churn −32% (s11, largest churn win of the experiment), Acc1 +8 (s3),
  coverage +3.1-3.5pt; house churn −9%/inert. The earlier in-experiment
  rejection of 32 was proven margin-confounded (bit-identical toughies
  corpora across dwell/sigma/pure-margin runs).
- `profile_reco_bpm_prefilter_margin` default 0.15 → 0.10 (recommender
  rc.23). 4/4 clean sweep house+curveballs (Acc1 +8/+7, Acc2 +7/+8,
  genre-acc +5/+5). Documented tradeoff: toughies churn +22/+32%,
  coverage ~−5pt — the shared floor math evicts edge-rider genres
  (trance floor at 0.10 = 120.6 sits exactly on real house locks).
  Accepted per the owner's ruling below; the margin SPLIT (prefilter vs
  matcher) is the planned recovery.

**Validated, no change:** `_BPM_LOCK_RELEASE_CONFIDENCE` 0.2 (0.225 and
0.25 rejected monotonically; house churn +39/+45% at 0.225);
`_V2_GENRE_EVIDENCE_MAX_BOOST` 0.1 (bracketed 0.0/0.2/0.5/1.0 — the
2026-08-17 owner park is empirically optimal pre-recalibration; dose
sweep established the evidence-amplifier law: gain amplifies evidence
QUALITY — rescues hidden fold errors when right, house s3 Acc1 +10 at
1.0; captures/harasses when wrong); `genre_matcher_endorse_sigma` 0.06
(0.04 behaviorally inert); margin 0.08 rejected (curveballs s11).

**Owner rulings recorded:** (1) toughies is diagnostic-only, NOT a veto
set — optimize for average-track material ("we can totally allow
anomalies in the toughest tracks"); (2) dwell 8 was "most likely way
too low" — confirmed; (3) config overrides for dwell/ACF-interpolation
removed permanently in the same landing.

**Process lesson (cost us a double verdict-reversal):** isolate every
candidate on EVERY veto-set playlist before accepting — Iteration 2's
quartet omitted toughies and four subsequent iterations inherited the
confound until a confirmation pair exposed it via trajectory-hash
bit-identity.

Follow-up roadmap:
`docs/planning/recommender-director-excellence-plan-2026-08-31.md`.

## The Prefilter/Matcher Margin Split (2026-09-01)

`_matcher_range_fit` no longer shares `profile_reco_bpm_prefilter_margin`
with the HIGH-regime prefilter; the matcher LOW half reads its own
`genre_matcher_range_margin` (auto-vj rc.103, recommender rc.24, weights
doc v69). Default 0.10 equals the prefilter's, so the split landed
behavior-preserving; probes may now move the matcher side independently.

Why: the 2026-08-31 accelerated tuning experiment's #1 structural
recommendation. The shared knob's two-regime coupling was measured
directly: margin 0.15 -> 0.10 bought curveballs Acc1 +8/+7 through the
prefilter while costing toughies churn +22/+32% and coverage ~-5pt
through the matcher floor math (a genre floor of floor_bpm x (1 -
margin) at 0.10 puts the trance floor at 120.6 -- exactly on real house
locks -- evicting the correct profile for edge-riders). One constant
could not express "tighter eligibility, looser endorsement." Engagement
counter `_matcher_range_margin_bind_count` per the new-tunables rule;
the planned matcher-side probes (e.g. 0.15 matcher / 0.10 prefilter, the
recover-toughies-keep-curveballs configuration) ship separately with
their own evidence.

## Decider Switch-Backoff (2026-09-01, recommender rc.25)

The applied-profile decider gains memory of switch frequency: each
apply escalates a backoff level (cap `profile_auto_reco_switch_backoff_
max` = 4) that multiplies BOTH decider cooldowns (normal 20 s and
fast-override 6 s) by `profile_auto_reco_switch_backoff_mult` = 2.0
per level, decaying one level per quiet `..._decay_s` = 90 s.

Why: the Love-Spirit-class 2:3 flicker (82-91% wrong-profile row
share) survived margins, confirmation streaks, cooldowns and the trust
floor because the decider was memoryless past its base cooldown —
alternating evidence simply re-earned the same checks; the 6 s
fast-override path allowed a dozen flips per track. The 2026-08-31/09-01
experiments proved the evidence channels can't fix this (boost-cap
changes never moved flicker; the matcher-margin probe BROKE Love
Spirit's correct lock while rescuing Blackout Riddim — evidence dials
help exactly where evidence is right). Stability had to come from the
decider layer.

Deliberately stability-only: the backoff cannot know which side of an
alternation is right (Stage-1 recalibration's job). mult = 1.0 is the
exact off-switch, used for A/B probes via session_replay --override.
Engagement per the new-tunables rule: `decider_backoff_gated_count` +
`decider_backoff_level` in corpus rows and apply-event marks. Validation
A/B (mult 1.0 vs 2.0, flicker lists) queued with the training team.

## v3 Proper, Phase 1 — the HMM Engine Lands (2026-09-02, detector rc.37)

**Decision.** `BeatTrackerV3(BeatTracker)` ships in `beat_grid.py`
(`ENGINE_VERSION '3.0.0'`) and `beat_tracker_engine = "v3"` now loads it —
the 2026-08-14 alias-to-v2 is retired. v2 is the protected baseline and runs
untouched as v3's observation extractor: `super().update()` computes the raw
comb-filter score, retained read-only as `_last_acf_observation` (and the
post-prior `_last_acf_score`); v3 forward-filters a posterior over a
log-spaced tempo lattice (55–210 BPM, step 0.01 log2, 194 states) and
overrides `bpm`/`confidence` with the posterior's MAP state and the mass
within ±4% of it. Bake 2's leverage check proved the v2 touch behavior-
identical: 7/7 lists, 49,977 rows bit-identical to the pre-change v2 cells.

**Transition model (the "one matrix").** Gaussian drift in log-tempo
(`_V3_DRIFT_SIGMA_LOG2` 0.006) + SYMMETRIC fold-jump mass at 2:1, 3:2, 4:3
up AND down (`_V3_FOLD_PROB_OCTAVE` 1e-6, `_V3_FOLD_PROB_TRIPLET` 5e-7) +
uniform novelty leak (`_V3_NOVELTY_LEAK` 1e-8). Observation: comb score
resampled onto the lattice, floored at `_V3_OBS_FLOOR` 0.7, raised to
`_V3_OBS_POWER` 1.0, times a bounded profile-prior bias (never a veto).
`_V3_FOLD_OBS_WEIGHT` 0.0 (an additive fold-aware boost tried in bake 1 —
it amplified the 4/3 alias; off). Engagement counters
`v3_cycle_applied_count` / `v3_fold_jump_count` in corpus rows and the
packager payload.

**Why these values — the cycle-rate law.** Bake 1 shipped floor 0.02 /
power 2 / fold mass 2e-3 and failed the panel (toughies −18, curveballs −15,
churn 5–10×): the posterior hopped lanes every few seconds at confidence
~1.0. Probe: the ACF observation cycles at ~7.4 Hz (664 cycles / 90 s), not
~1 Hz, so every constant sized "per second" was ~7× too loose. A lane
survives N cycles of contrary evidence iff L**N · m < 1 (L = per-cycle
likelihood ratio ≈ 1/floor at power 1; m = fold escape mass). v2's dwell
(32 cycles ≈ 4.3 s) needs L < ~1.2 at m = 2e-3, or m ≈ 1e-6 at floor 0.7.
Four offline sweep rounds (17 configs, 19 panel-mover tracks) tracked this
law exactly; the diffusion hypothesis (shrink drift) was falsified in round
3; feeding v2's post-prior score instead of the raw comb (round 4) changed
nothing. Defaults = offline config "I" (steadiest).

**Bake 2 (full 7-list panel, v3 vs bit-stable v2 cells).** With these
defaults v3 matches-or-beats v2 Acc1 on 5/7 lists (house 93.3 = 93.3;
toughies 72.7 vs 45.5; curveballs 84.6 = 84.6; trap 23.8 vs 19.0; dnb 6.2 =
6.2) at LOWER churn on 5/7 (house 0.018 vs 0.353/min, toughies 0.116 vs
0.536, curveballs 0.13 vs 0.76) and coverage 97–99.8%. It loses ambient
(22.2 vs 33.3) and trance (75.0 vs 83.3). The looser config "G" (floor 0.5,
m 1e-5) proves the fast-lane thesis — dnb 25.0 vs 6.2, three tracks read at
173/174/148 where v2 folds to ~118 — at 2–8× churn.

**What phase 1 established, and what it did not.** The transition half of
"one matrix replaces seven gates" holds: the integration gates (persistence,
dwell, jump-confidence) are replaced and churn is now a derived quantity.
The disambiguation half does not: the raw comb has harmonic-alias peaks
(the 4/3 lane = 4th comb harmonic on exactly 3 beats; 5/4; 3-beat) that v2
suppresses with its tactus-descent + raw-dominance POLICY (not its prior —
round 4). Every v3 configuration lands ambient's Swan Dive / Tarvona /
4 Astral at 120–130 and Junes Daughter at ~149 identically. That is the
observation-model problem and it is phase 2's scope; the roadmap's
original phase-2 items (lock-state-aware evidence gating, fold-suspect
alarm, raised boost cap) move to phase 3.

**Owner ruling (2026-09-03):** phase 1 accepted as tested-and-tuned;
v3 stays the ACTIVE engine in the owner's config (shadow v2, v1 shadow
retired); "must improve everywhere" judged at the end of the whole
program, not per phase.

**Process findings logged.** (1) A peer seat's "zero shadow disagreements"
compared zero rows — replay corpora carry no shadow column; every null claim
now states its compared-row count. (2) The offline sweep set (panel movers)
is biased hard; the panel is the judgment. (3) Determinism let bake 2 reuse
bake 1's v2 cells as controls.

## v3 Proper, Phase 2 — the Template Observation Model (2026-09-03, detector rc.38)

**Decision.** `BeatTrackerV3`'s observation likelihood becomes a **template
match** (`_V3_OBS_SOURCE = 'template'`): for each lattice tempo *s* the comb
profile an ideal beat train at *s* would produce over the ACF grid is
precomputed once (mirroring v2's comb exactly: 100 Hz lags, `lag = 6000/bpm`,
`_V2_COMB_HARMONICS` = 4 harmonics at 1/h weight; Gaussian spikes at k·P_s
with decay 0.9^k, 12 beats, sigma 1.5 lag samples, **no half-beat spikes**);
the per-cycle likelihood is the cosine between the observed comb and each
template, normalised to its max, floored at `_V3_OBS_FLOOR` 0.7, times the
bounded per-cycle prior bias. One matvec per cycle. Transition model
unchanged from phase 1.

**Why.** Phase 1's config-invariant failures were harmonic aliases in the raw
comb (the 4/3 lane = 4th comb harmonic on exactly 3 beats; 5/4; 3-beat) that
v2 suppresses by policy (tactus descent + raw-dominance), not by its prior
(round 4 of the phase-1 sweep). Reading each comb bin at face value cannot
tell an alias from a tempo; matching the *whole profile* can, because the true
tempo's template explains its own aliases while an alias's template predicts
peaks (its own sub-harmonics) the observation lacks.

**Evidence (bake 3, 7-list panel vs bit-stable v2 cells, Cell C).** Acc1
matches-or-beats v2 on **all 7 lists**: house 93.3 = 93.3; trap 33.3 vs
19.0; toughies 63.6 vs 45.5; **dnb 56.2 vs 6.2** (eight fast-lane rescues at
164–174 BPM where v2 folds to ~115); ambient 33.3 = 33.3; trance 83.3 =
83.3; curveballs 84.6 = 84.6. Coverage 98–99.8%. Churn below v2 on
toughies/curveballs/trap, above on dnb (0.90 vs 0.41/min), ambient (0.91 vs
0.70) and trance (1.75 vs 0.48). Fold-forgiving accuracy drops on four lists
because ~6 tracks land off-lane (Ashanti / Chris Brown Nylze edits at 4/3 of
their tags, Urus 141, Tarvona 139, Swan Dive 120.4; Junes Daughter 147 is a
probable tag error, Essentia 146). That residue plus the churn on three lists
is phase 3's scope. Cell D (prior gain 0.25, floor 0.85) won bigger on trap
(+28.6) and curveballs (+7.7, Blackout Riddim rescued to 194) but lost
ambient (−5.5) at 2–3 flips/min everywhere and was rejected.

**Findings that shaped the model (four offline sweep rounds, 20 configs).**
(1) Half-beat spikes in the template are harmful: 2T's template then matches
a track with hats as well as T's own (fold-ups). (2) **Per-cycle prior
compounding**: the bounded prior bias multiplied in every cycle at 7.4 Hz is
prior**N; under a floored observation it out-ranges the evidence and pulled
7/18 ambient tracks to mu = 120.4 regardless of tag (found from the training
seat's per-track table; trance unaffected). Fix exists as `_V3_PRIOR_MODE =
'init'` / `_V3_PRIOR_GAIN`, but with the template observation the bias is
what holds the 2T lane down (gain 0.25 → Tarvona 182), and removing it is
catastrophic for the comb source (house folding to 63) — so `'percycle'` at
gain 1.0 stays and the octave decision is phase 3's problem, not a dial.
(3) Raising the floor to 0.85 to cut churn hands the set to the prior (13/22
tracks at 120.4) — the churn lever and the prior are coupled through the
same per-cycle multiplication. (4) Shape × magnitude ("hybrid") re-sharpens
the observation and loses. (5) Every shape/transition variant of the
winning structure (fold mass 1e-7, power 0.5, sigma 2.5, decay 0.75, 6
beats) was worse: it is a local optimum.

**Real-audio check.** The owner's first live v3 session (favorites, 42 min,
phase-1 defaults, v2 shadow — `assets/training/sets/favorites/004`): v3
10/11 exact vs v2-shadow 9/11, lock coverage 99.7%, 10 lock events in 41
min, LLM detector 4.4/5. v3 rescued DJ Jackpine (124.6 vs v2 135.7); missed
Careless Whisper off-lane (113.9; tag 81 / mixer 130.8 / v2 126) — the
phase-1 alias mode this phase addresses.

**Robustness fix.** Templates are cached keyed on the observation's own grid
(length, first, last BPM) rather than assumed to be a prefix of
`self._acf_bpms` — true in production by construction, but an observation on
another grid silently mis-matched (found writing the phase-2 tests).

## v3 Proper, Phase 3 — the Apply Mode Made Explicit (2026-09-03, detector rc.39)

**What phase 3 found.** A probe showed that in rc.108 the template
observation branch sat above the once-per-ACF-cycle check in
`_v3_observation_likelihood`, so on the template path the likelihood *and*
the HMM transition step ran on every 60 Hz `update()` tick with the latest
ACF observation held — about eight applications per 7.4 Hz cycle. The
phase-1 comb path deduped correctly (bakes 1–2 unaffected). Bake 3's numbers
stand as measured; its mechanism was not the per-cycle sizing law but
held-observation filtering at frame rate: per cycle, evidence ~8× sharper,
prior bias ~8× stronger, drift ×√8, escape mass ×8.

**What the once-per-cycle alternative does (bake 4).** With the observation
applied once per cycle and the floor re-tuned (0.5 / 0.3), exact accuracy
holds (floor 0.5: ≥ v2 on 6/7 lists, dnb 50.0%, trap +23.9, ambient −5.5)
but lock churn rises on every list (house 1.67/min vs v2 0.35 and bake-3's
0.37; 3–8× bake 3 throughout). Offline tick-jitter halved while panel
lock-flips tripled: lane stability (what the escape-time law governs) and
confidence stability (what the Schmidt trigger consumes) are different
quantities, and a once-per-cycle tempered observation leaves the posterior
broad enough that the ±4% band mass hovers around the 0.45/0.2 thresholds.

**Reproduction attempts (rounds 3–4).** Explicit power 8 / prior gain 8
(10/17 on the 22 hardest tracks vs 13/19 for the tick path), the
single-factor cells (gain 8 alone collapses everything to the prior's
120.4; power 8 alone folds up: Swan Dive 201, Chris Brown 210), and the full
×8 including drift and escape mass (11/17, tail 12 vs 14) all fell short:
interleaving transition and observation at a varying tick count is not a
constant-factor re-sizing.

**Decision.** Keep the validated behaviour and make it explicit:
`_V3_OBS_APPLY = 'tick'` (default; no behaviour change from rc.108, so bake
3 remains its validation — verified by an exact offline match of the
explicit mode against the rc.108 run on all 22 sweep tracks) with `'cycle'`
kept for future work. The comb/score sources always apply once per cycle.
Lane hysteresis on the reported tempo (margin 0.20/0.35: locked in wrong
early lanes, no churn reduction) and a soft comb-magnitude factor on the
template match (undid the fast-lane rescues) were tried and removed.
`_v3_fold_suspect_mass` (posterior mass on the fold-related lanes of the
MAP state) stays as telemetry. Regression tests pin the tick default, the
per-cycle comb path, and once-per-cycle behaviour in `'cycle'` mode on every
source.

**Residue after the v3 program (post-v3 work, not a dial).** Slow ambient
(74–90 BPM) folds up an octave under the template — a track with a steady
half-beat pulse matches 2T's template as well as T's own, and the
perceptual prior around 120 is symmetric in log space, so 82 vs 164 is a
coin flip for it; swung hip-hop edits land on the 4/3 lane (dotted-eighth
structure). Both need a musical decider the HMM lacks and v2 has as policy
(tactus descent, onset-density guard). The candidate is an onset-density
observation channel: v2's density guard expressed as evidence with a
likelihood, not as a gate.

**Real-audio check for the whole program.** The owner's first live v3
session (favorites, 42 min, phase-1 defaults, v2 shadow —
`assets/training/sets/favorites/004`): v3 10/11 exact vs v2-shadow 9/11,
lock coverage 99.7%, LLM detector score 4.4/5.

## v3 Proper, Phase 4 — the Octave Residue Is Not an Audio Problem (2026-09-03, detector rc.40)

**Scope.** After phase 3, six panel tracks still landed off-lane: slow ambient
(Harmonic Dust 82 → 164, Kream 74 → 150, Twaang 80 → 131, Tarvona 90 → 123)
and swung hip-hop edits on the 4/3 lane (Ashanti 114 → 152, Chris Brown 104 →
139). The owner asked for the fix.

**Three observation signals, three pre-registered leverage checks, three
negatives.** (1) Raw onset rate (v2's `density_bpm`): sits *at the alias lane*
on every failing track — hats and subdivisions are onsets — so the 164 lane
reads a normal 1.1 onsets per beat while the 82 lane reads 2.3; v2's own 1.3×
guard fires on 1 of 22 tracks. (2) Bass-weighted onset count via
`OnsetEvent.band_weight`: near zero on everything including four-on-the-floor
house (Guetta 6/min at 132 BPM) — `band_weight` is a bass *fraction*, not a
kick detector. (3) An autocorrelation comb over the continuous bass-flux
envelope, template-matched on the lattice: points at the alias or worse on all
six (Swan Dive 100 → 201, Chris Brown 104 → 208) — the bass itself pulses at
the faster rate. `kick_regularity` was also examined and is circular (it
samples kick energy at the tracker's own beats). The perceptual prior centre
was swept as the last audio-side lever (mu 110/100/90): it never rescues
ambient cleanly (Harmonic Dust 164 → 114 → 100 → 95) while folding DnB, Guetta
and Flagrant down at once — the v2 dilemma reproduced inside v3.

**Root cause.** These tags record a notated half-time feel; the sounding pulse
in every band is the faster lane. No signal extracted from the audio settles
that, and in bake 3 the recommender had applied, on every failing track, a
profile whose BPM range *contained the alias* (Harmonic Dust under dubstep
140–160, Tarvona under drum & bass, Chris Brown under peak_time) — the
recommender follows the detector, so the profile prior re-centres onto the lane
the detector already chose: the roadmap's chicken-and-egg loop, measured.

**Decision.** The octave is settled from *outside the audio*: `prime_tempo()`,
the existing one-way ground-truth channel (mixer analysis, tap tempo), is now
honoured by the HMM — a prime seeds the posterior at the primed tempo and holds
the per-cycle prior centre there (`_V3_PRIME_SIGMA` 0.20, `_V3_PRIME_HOLD_S`
20 s after the *last* prime; every re-prime refreshes; hold starts lazily at the
first update if primed before the clock runs). media-01 0.26.0 publishes the
playing track's authored BPM tag on the vj_api BPM bus (source `media`, read
once per track, republished every frame), and auto-vj's existing P0-B lookup
primes from it every recommender eval while the hint is fresh. Result: a tagged
local file is held at its tag for its duration; an untagged next track lets the
correction lapse `HOLD_S` later; streams stay evidence-only. Offline (22 hardest
tracks): tag prime held = **22/22 exact at 1.2 flips/min** (v2 1.1); a single
un-refreshed prime lapses on schedule (traced: 82 BPM at confidence 0.8–0.9 for
the hold, back to 171 within 5 s of expiry); a deliberately wrong (doubled)
prime costs only its own track. This matches the owner's stated semantics for
tempo correction (per-song, not a timer, not permanent) — see the audio-profile
correction memory.

**Onset-density channel.** Implemented as a soft likelihood on lattice tempos
faster than `FAST_RATIO ×` the onset rate (`_V3_DENSITY_*`), tested, and left
**inert at weight 0** as a documented negative: it cannot bite where the onset
rate equals the alias rate. A real bass-band onset *picker* would be the next
signal to try if the octave is ever to be settled from audio; the bass-envelope
comb result suggests it would not help on this material either.

**Bookkeeping.** Detector `rc.40`, auto-vj `rc.110`, weights doc v75, media-01
0.26.0, training-kit +0.0.1 (packager constants and the `v3_prime_count` /
`v3_density_engaged_count` counters). Tests pin the prime seed/hold/refresh/
lazy-start, the inert density channel's shape, and media-01's publish logic.

## Director Placement E1 — Phrase-Quantized Fires (2026-09-03, director rc.13)

**Decision.** `drop_phrase_snap_bars = 4` (with `phrase_snap_unit = 8`): when a
pending drop is within four bars of the next 8-bar phrase boundary,
`_schedule_drop()` chains downbeat callbacks to the boundary instead of firing
at the next bar. Impacts fire from inside `_fire_drop()` and inherit it. Read
from the global `[auto_vj]` cfg (not per mood profile) so replays can
override it whatever mood is active — `_profile_value()` honours user
overrides only when the mood is `user`. Engagement counter
`drop_phrase_snap_count`; per-row telemetry `drop_last_snap_bars` (scheduling-
time distance to the boundary, added because the panel drill could only see
the fire bar).

**Why.** The placement instrument (`docs/planning/director-placement-
scoring-2026-09-03.md`) showed drop and impact fires on-beat 100% of the time
but at or below chance on 8-bar phrase boundaries in every genre family; the
drop path already waited for the next *downbeat* and had no notion of the
*phrase*. Mode transitions carry a phrase bias; fires did not.

**Evidence.** Offline (3 lists, seed 1, same-order baselines): phrase
alignment 43 → 86 / 29 → 67 / 41 → 84 at snap 4 with counts, energy/bass lift,
build/breakdown consistency and lock churn unchanged; snap 2 engaged too
rarely. Panel (19 lists × 2 seeds, snap 4, training seat's instrument vs the
same-seed baselines, report `drop-ins/training-kit-01/tools/baselines/
director_placement_e1_batch-2026-09-03.md`): drop fires on a phrase boundary
36% → 75% (chance ~38), impacts 34% → 79%, pooled per-list alignment ≥ 65% on
19/19 (lowest tech-house 65.1), drop counts within 10% on 19/19 (worst
downtempo −9.1%), lock events identical on 19/19, placement rating up on
19/19 and down on none. Four unpooled cells fall under 65% (rnb s2, tech-
house s1, dubstep s1, deep-house s2): their misses cluster 2–3 bars from a
boundary, the uniform-null expectation for drops the snap-4 cap excludes
(5–7 bars out). Nine cells breach the ±8 pt energy/bass-lift band, six on the
two smallest lists and two in the positive direction; per-track, the deferral
sometimes changes *which* trigger fires (a relocated or added event swings a
10-event list by double digits) — event-position noise, not a systematic cost.

**What it does not do.** Energy lift is unchanged: the drops now land on the
bar the phrase turns, not necessarily where the energy jumps. That is E2's
question (a bass delta gate at the boundary), still open. The half-time genres'
missing drops are E4 (adaptive trigger), next.

## Director Placement E4 — Rescue Trigger for Half-Time Material (2026-09-03, director rc.14)

**Diagnosis.** The placement batch showed 2–6 tracks per half-time list
(ambient, downtempo, hip-hop, trap, dubstep) with no drop fire at all. It was
not the threshold: on those tracks `drop_score` sat above every mood trigger
threshold for 43–47% of rows and downbeat confidence cleared its minimum, yet
`drop_trigger_fired_count` never advanced — no drop was ever *scheduled*. The
gate that never clears is the split trigger signal, `grid.impact_novelty`,
against the absolute mood threshold (0.55–0.66): on half-time material its
95th percentile is 0.27–0.41 (firing tracks: 0.36–0.50). Softer, sparser
transients; an absolute novelty threshold is genre-blind in the wrong way.

**Decision.** A rescue-only relative trigger: `trigger_rel = impact_novelty /
max(0.15, rolling p90 over 60 s)`; when ≥ `drop_trigger_rel_threshold` (0.85)
it opens the trigger gate alongside the absolute one, but only after
`drop_trigger_rel_min_bars` (64) bars without a drop on the current track
(`_last_drop_bar`, reset per track). Global cfg tunables read in
`_apply_profile_settings()`; engagement `drop_trigger_rel_fired_count` counts
drops scheduled through the relative path.

**Evidence (4 half-time lists, seed 1, vs the E1-bake buckets, same order).**
Round 1 (no re-arm, 0.85/0.75): never-fire 6/4/4/4 → 2/2/1/1 but drop counts
+100–150% and the extra fires landed on weaker peaks (hip-hop energy lift 25 →
20, trap 32 → 25) — rejected. 32-bar re-arm: counts +30–82%, lift within ±5,
transitions −35% — better, still loose. **64-bar re-arm (landed):** never-fire
2/1/1/0, drops +30/+34/+24/+43%, energy/bass lift within ±5 of E1 (hip-hop
bass −10), phrase alignment unchanged (87/72/66/85), lock churn identical,
transitions −16 to −34% (rescued tracks now spend time in DROP, by
construction). Lowering the absolute threshold instead was not tried: house-
family novelty is higher and would gain false fires.

**Guards on the post-landing re-baseline (pre-registered).** House-family drop
counts within +15% and energy lift within ±5 of the E1 bake; half-time lists
never-fire ≤ 2. If a guard breaks, the default flips off in a follow-up and the
mechanism stays owner-selectable.

## E5 — The +1.3% Replay Tempo Bias: Diagnosed, Fix Parked (2026-09-03)

**Finding.** On real music in replay both v2 and v3 read tempo ~+1.3% high
(median p50/tag on exact tracks 1.0127; Essentia and madmom on the same files
1.0000). A synthetic 125 BPM click reads true (v2 −0.10%, v3 +0.39%), decode
length matches ffmpeg to the sample, and a fine ACF of the 60 Hz bass-flux
stream reads the tags within +0.2% — so the bias is inside the tracker's
100 Hz onset envelope. Measured write rate on real tracks: 95.7–96.3
samples/s against the nominal 100. Two mechanisms in `beat_grid.py`: (1) on
ticks that carry onsets, `update()` advances the envelope only to the last
onset's timestamp and then moves `_last_t` to `now`, losing the tail of the
tick; (2) `_pulse_envelope()` deducts a step from `_env_t_acc` clamped at zero,
so an onset arriving before a full step has accumulated steals the remainder.
Clicks land on block boundaries and show neither. Consequence: every replay
tempo sits ~1.3% high (inside the ±4% exact band, so accuracy numbers stand),
six near-misses 4–7% high in the 311-track bench become exact once fixed, and
house tracks at 127+ cross the dubstep prefilter edge in replays (the
profile-mix artifact). Live sessions show a smaller, engine-dependent bias
(v2 shadow +0.8%, v3 −0.3%).

**Why the fix is parked.** Three attempts changed the envelope's timing/pulse
semantics that a dozen v2 synthetic tests pin: an unconditional advance to
`now` double-counted the pre-onset span (v2 tests read 3% low); a dedicated
envelope clock exposed the pulse deduction (90 Hz); merging the pulse into the
next advance write made the comb read half tempo. Per the regression
discipline (tests not written by the agent, red after core changes) the tree
was reverted to rc.40-era `beat_grid.py` and the diagnosis kept as a strict
`xfail` in `tests/test_envelope_advance_rate.py`. The fix needs a deliberate
redesign of the envelope clock and pulse placement with the v2 test
expectations re-derived, validated by the synthetic click (must stay true),
the 22-track bias (must go to ~0), and the madmom bench as the unbiased
reference. Detector version unchanged; every batch to date carries the same
bias and remains comparable.

### E4 addendum — scoped to never-fired tracks (2026-09-03, director rc.15)

The post-landing re-baseline (19 lists × 2 seeds, training-kit bb666c8)
passed the half-time guard (never-fire ≤ 2 on 12/12 cells) but breached the
house-family drop-count guard on 4/8 lists (big room +27%, dance +20%, deep
house +18%, prog house +21%; energy lift within ±5 on 8/8): the 64-bar re-arm
rescued *any* track with a long gap between drops, and those lists have
legitimate ones. Placement rating slipped half a point on six lists as the
rescued drops carry lower lift over chance. Per the pre-registered rule the
default was to be flipped off; a tighter scope was tried first (pre-registered,
4 cells, seed 1): `drop_trigger_rel_first_only` — the relative gate applies only
to a track that has never fired a drop on the current track. Result: big room
+6% and prog house +11% over the E1 bake (inside the guard), ambient never-fire
2/14 and trap 0/21 kept, energy/bass lift unchanged. Landed on by default.

### E5 addendum — the redesign exists; the stack is co-adapted to the bug (2026-09-03 morning)

An absolute-index envelope clock (zero-fill to the slot covering the target
time; pulses merged by max into the slot covering their timestamp, nearest
slot; legacy timestamp-less callers fall back to the newest slot; always
advanced to `now`) writes exactly 100 Hz and removes the bias: 22-track
p50/tag median +1.27% → −0.23%, three real tracks within 0.3% of tag. It is
saved as `docs/planning/patches/e5-envelope-clock-redesign-2026-09-03.patch`
and **not applied**, because the corrected timing makes lane decisions worse
without a re-tune: v3 drops from 13 to 10 exact on the 22 hardest tracks
(Healing, Ashanti, Hplus, Swan Dive, Harmonic Dust move to alias lanes) and
v2 folds house to half tempo (Bon Jovi and Tim Cosmos at 62.5). Precise
pulse placement sharpens the comb's harmonic structure, and the old envelope's
timing noise was an accidental regularizer that the comb weights, prior and
gates were tuned against. The v2 synthetic fixtures' perfectly periodic clicks
(a documented degenerate case) were passing partly because of that noise.

**Landing path ("v3.1"):** apply the patch, re-tune the comb/prior/gate stack
under the true clock (offline 22-track set, then the 19-list panel against the
final baseline), re-derive the v2 fixtures with the jitter their own docstring
recommends, and validate against madmom (bias 0.00%) as the unbiased reference.
Owner's rule applies: tests get fixed when the fix improves the system, and the
clock fix alone does not yet.

## Director Placement E6 — Mode-Transition Quantization (2026-09-03, director rc.16)

**Decision.** Apply E1's `_schedule_drop()` deferral pattern to
`_enter_build()` / `_enter_breakdown()` / `_enter_climax()`, generalized
under E8 into a per-mode model rather than the two original global knobs:
`mode_snap_unit_<build|breakdown|climax>` (`off`/`downbeat`/`phrase`) and
`mode_phrase_within_bars_<mode>` (bars). `off` fires immediately (pre-E6
behaviour); `downbeat` always defers to the next downbeat; `phrase` defers
to the next downbeat AND chains further to the 8-bar phrase boundary
(`phrase_snap_unit`, shared with E1) when within `phrase_within_bars` of
it, never earlier than the original decision. The old globals
(`mode_snap_downbeat`, `mode_phrase_snap_bars`) stay as pure, one-direction
aliases — when the new per-mode keys aren't set explicitly, they're
derived from the old globals, so nothing that already worked needs to
change. **Shipped default: `phrase` / 2 bars on all three modes**,
reproducing the panel-tested 2-bar candidate exactly.

A deferred entry is re-validated against the SAME live trend that
justified scheduling it (not values captured at schedule time) — if the
trend has reversed by the time the deferred boundary arrives, the entry is
cancelled and counted (`mode_snap_cancelled_count`) rather than fired
stale. Build and breakdown both have two real source paths (CRUISE's own
sustained detection, and BUILD/BREAKDOWN's direct recovery/slam paths into
each other); climax's single source is DROP. E8 also adds
`mode_allowed_from_<mode>` (a per-mode set of allowed source-mode names,
checked in the `_enter_*()` wrappers before scheduling; a blocked
transition increments `mode_blocked_by_source_count` and is not a silent
no-op) and per-row `from_mode`/`snap_unit_applied` telemetry, so future
config-only experiments (e.g. the owner's variant, build only from
breakdown) live on the same code path as the shipped default rather than
a second implementation.

**A real implementation bug found before landing, not a tuning question.**
The first working version hardcoded build's revalidation to `self._mode !=
_CRUISE`; a house-01 offline cell showed 70% of scheduled builds
cancelling. Debug trace showed every cancellation reading `mode=BREAKDOWN`
at fire time — legitimate builds scheduled from BREAKDOWN's own recovery
path (`slope > build_energy_threshold * 0.75 and energy >= recover_
energy`), a second source path for `_enter_build()` mirroring breakdown's
own CRUISE/BUILD duality, that the hardcoded check rejected outright
regardless of the live trend. Parameterizing on the captured `from_mode`
(already how breakdown's own check worked) dropped cancellation to 18.7%
on the same cell. A second refinement replaced a strict re-check against
the SAME soft "give-up" thresholds the continuous CRUISE tick loop uses
(designed to tolerate brief per-tick dips and restart) with the OPPOSITE
mode's own entry bar as the cancellation threshold — a single-shot
fire-time check against a soft, continuously-re-accumulating threshold
cancels on ordinary signal wobble, not genuine reversal; asking "has this
actually become a breakdown/build candidate" is the more meaningful
question.

**Why.** The placement instrument's final-baseline read: builds/
breakdowns/climax on-beat only ~30% of the time, on an 8-bar phrase
boundary no better than chance (build 30%/39% vs 37 chance, breakdown
33%/40% vs 37, climax anti-aligned 30%/12% vs 41), while the trend-
following they DO carry (build 40% vs 23 chance, breakdown 38% vs 21)
shows the *decision* is already better than chance — only the *timing* is
not.

**Panel (19 lists × 2 seeds, shipped defaults, vs the final baseline,
`tools/baselines/director_placement_e6_panel-2026-09-03.md`).** On-beat
holds decisively: 100% on build/breakdown/climax on every list, zero
exceptions. On-phrase improves but misses the ≥ 65% target on every mode
(build 39.4 → 48.2, breakdown 38.3 → 46.4, climax 12.2 → 22.3, chance
~38–39 throughout). Climax stays anti-aligned (22.3% vs 39.2% chance,
narrowed from −25.2 pt to −16.9 pt, n = 103 — the smallest population of
any mode). Trend-following splits: breakdown flat (37.6 → 37.5, within
noise), build measurably worse (40.0 → 37.2). Drop/impact metrics and lock
churn (1700/1700, identical) hold; both E4 guards hold (half-time 12/12,
house-family drop count 8/8 inside ±15%, energy inside ±5). **Mode counts
miss the −25% ceiling badly: build −26.9%, breakdown −32.6%, climax
−59.4%** — three to four times the budget the spec attributed to E3,
with E3 shipped off. Worst mode: climax (worst on every axis). Worst list
by count cost: dubstep-01 (−45.5%). One cell regressed in rating:
downtempo-01 seed 1 (4 → 3).

**Ablation (`mode_phrase_snap_bars` ∈ {0, 1}, vs the same baseline,
`tools/baselines/director_placement_e6_ablation-2026-09-03.md`).**
Pre-registered to test whether the count/trend cost belongs to the phrase
half or to the deferral mechanism itself. Finding: `=1` is mathematically
identical to `=0` on every outcome metric — the phrase chain only
activates when `to_boundary == 1`, which resolves in exactly one downbeat
either way, so it can never produce a longer wait than downbeat-only.
Downbeat-only (`=0`) itself still costs build −23.5%, breakdown −28.0%,
climax −58.3%, cancellation 19.1%, build trend 37.0 (vs the ≥ 40
predicted) — nearly the full cost of the 2-bar candidate, for none of its
phrase-alignment gain. The downtempo-01-seed-1 regression reproduces on
all three cells (0/1/2-bar), slightly worse at 0-bar/1-bar (placement
0.227) than 2-bar (0.233) — further evidence the cost is intrinsic to
"defer one downbeat, cancel on reversal," not to the phrase chain.

**Landing rule, applied, and NOT followed on its literal fallback.** The
pre-registered rule: ship whichever cell keeps on-beat 100% with build
trend ≥ baseline and counts inside −25%, preferring more phrase gain if
two qualify; if neither qualifies, land downbeat-only. **Neither cell
qualifies** (both fail build trend ≥ 40.0; both fail counts on breakdown
and climax). The rule's literal fallback is downbeat-only — but the
ablation shows that would ship the strictly worse candidate on the actual
data: downbeat-only pays essentially the same cost as 2-bar everywhere
except phrase alignment, where 2-bar is +10 pt better on build and
breakdown. The premise behind the fallback branch (that downbeat-only is
meaningfully cheaper) is what the ablation falsified. **Decision: ship the
2-bar candidate, and record the count/trend cost as intrinsic to the
deferral-and-cancellation mechanism itself, not to the phrase half.** That
intrinsic cost is what the owner's live A/B (rc.15 behaviour vs the rc.16
default) is for. Climax's −59% count cost and persistent anti-alignment is
E7/E8 territory, not a reason to hold E6 back — see the climax-time-since-
drop finding below.

**Climax time-since-drop, on the rc.15 baseline (n = 253, input to E7).**
Median 3.11 bars, mean 4.24 (right-skewed; 70% of events fall in bars
2–4, tail to 20). Climax's escalation gate (`impact_hold_s`, a roughly
fixed real-time duration after DROP, not a bar count) lands it a fairly
tight, predictable number of bars after the drop that fired it — since
drops are phrase-boundary-aligned (E1), and climax fires ~2–4 bars later
(not near 0 or 8), it lands mid-phrase *by construction*, not because
snapping failed. This is a structural property of the escalation gate, not
a tuning miss; a future fix (E7) needs a different mechanism (e.g. climax
as "drop + N phrases"), not a smaller `phrase_within_bars`.

## Director Placement E3 — Persistence Raise: Explored, Shipped Off (2026-09-03)

**Decision.** `mode_persist_bars_rise` / `mode_persist_bars_fall` (both
default `0`, off): an additional bars-of-monotone-slope floor checked
before `_enter_build()`/`_enter_breakdown()`'s CRUISE-sourced sustained
paths are even called (on top of, not instead of, the existing
`build_sustain_s`/`breakdown_sustain_s` time gate) — bars are tempo-relative
where seconds are not. Implemented and available as a tunable; not shipped
on by default.

**Why explored.** The final baseline's own trend-following, while
above chance, still misses more than half the time (build 40% vs 23 chance,
breakdown 38% vs 21) — the original E3 bullet asked whether raising the
persistence requirement until 4-bar consistency clears 55% on house family
would close more of that gap, at some count cost.

**Why shipped off.** Every candidate tested on the house-01 offline cell (1,
2, 4 bars, `mode_snap_unit` off so E3 could be measured in isolation)
exceeded the pre-registered −25% mode-count-cost ceiling: 1 bar already cost
−35% (build) / −28% (breakdown); 2 bars cost −72% / −65%; 4 bars zeroed both
modes out entirely on this list. Trend-following did improve at the smaller
values (breakdown 47 → 64% at 1 bar, → 77% at 2 bars, vs ~25–29% chance),
so the mechanism works as intended — no tested value kept the cost inside
the predicted budget. Per the standing instruction to report a missed
prediction rather than tune toward it, E3 lands as a working, tested,
off-by-default knob rather than a shipped default; a future pass could
explore sub-1-bar (fractional) values or a persistence measure less coupled
to the existing time-sustain gate.

## Director Placement E8 rounds 1-3 — Owner Variant, Landed as Knobs Only (2026-09-03, director rc.17)

**Decision.** Three rounds of offline-cell exploration into an "owner
variant" of the director (restricting build's allowed source mode, a
CRUISE→DROP path, and a shorter climax phrase cadence) land as config
tunables now, all defaulting to reproduce rc.16 shipped behaviour exactly
(`drop_cruise_min_confidence=0.0`, `mode_phrase_unit_<mode>=phrase_snap_unit`,
`mode_source_min_confidence_build=0.0`, `mode_allowed_from_<mode>`
unrestricted). Landed ahead of Program B step 3's detector work
specifically to avoid three rounds of tested, uncommitted director code
sitting in the tree while the detector changes underneath it — a patch-
level bump (rc.16 → rc.17) since no live default changes.

**Round 1** (`director_placement_e8_offline-2026-09-03.md`, 18 cells, 6
lists × 1 seed: `control`/`core`/`core_c2`). `mode_allowed_from_build=
[BREAKDOWN]` (drop CRUISE as a build source): predicted ~−40% build-count
cost (from CRUISE's 40.3% share of builds on the earlier 19×2 panel), actual
−79.1% vs rc.16 control — the CRUISE-source gate worked exactly as
specified, but the surviving BREAKDOWN-sourced share *also* collapsed
(277→104, −62.5%) even though it was never blocked, the first sighting of
what rounds 2-3 confirm is a general compounding-cycle effect (below).
`mode_snap_unit_climax=phrase` with `mode_phrase_within_bars_climax=8`
(an unconditional wait within the *existing* 8-bar grid): predicted a
further −20-40% climax-count cost, actual **−100% in all 12 core/core_c2
cells** — verified as a real mechanism, not an artifact, via exact
`mode_snap_count = fired + cancelled` counter arithmetic on two sampled
buckets (e.g. house-01 core: fires=30, cancelled=5, snap_count=35). Every
scheduled climax entry under the unconditional 8-bar wait got cancelled at
fire-time re-evaluation before this round's fix (round 2). The new
CRUISE→DROP path (`drop_cruise_min_confidence=0.71`, this project's own p90
`downbeat_confidence`) took a 25.5% share of drops (predicted 5-15%) with
*worse* energy-lift than the overall population (15.0% vs 27.4%, predicted
comparable-or-better) — parked, not carried forward.

**Round 2** (`director_placement_e8_round2-2026-09-03.md`, 18 cells, same
six lists, reusing round 1's control buckets). Introduced `mode_phrase_
unit_<mode>`, a genuine per-mode phrase-**grid** size (bars between
boundaries) distinct from `mode_phrase_within_bars_<mode>` (the wait cap
within that grid) — round 1's "unconditional 8-bar wait" was still gated
by the shared 8-bar grid every other mode uses; this lets one mode chain to
a *shorter* grid instead. `climax-4` (`mode_phrase_unit_climax=4` +
`mode_phrase_within_bars_climax=4`, an unconditional 4-bar half-phrase
chain): recovered climax count to **77.8% of rc.16 control** (14/18, vs
round 1's total elimination) with build/breakdown completely untouched
(+0.0%/−0.5%) — the strongest climax candidate across all three rounds.
Phrase alignment on its own 4-bar grid is 100.0% (vs a 75.7% chance floor,
since a 4-bar boundary occurs twice as often by construction) while the
*same* fired events read anti-aligned on the standard 8-bar reading (21.4%
vs 40.0% chance) — expected: a half-phrase snap lands mid-phrase on the
full-phrase reading by definition, not a contradiction. `build-floor`
(`mode_source_min_confidence_build=0.71`, a confidence floor on CRUISE's
build source specifically instead of round 1's outright block): predicted
a softer −15 to −40% cost, actual **−67.8%**, nearly as expensive as the
outright block — 0.71 turned out to sit almost exactly at the p90 of the
population it gates (confirmed in round 3, below), so the "soft" gate
wasn't actually soft at that threshold. Trend-following did improve as
predicted (build_trend 40.6% vs control's 36.0%). `both` (climax-4 +
build-floor together): climax count **4** — *below* either mechanism run
alone (14, 6) — confirms **sub-additivity**: stacked director mechanisms do
not compose linearly and each combination needs its own offline cell,
never an assumed sum.

**Round 3** (`director_placement_e8_round3-2026-09-03.md`, 6 cells, one
mechanism: `build-floor-median`). Re-derived the confidence floor from the
actual population it gates instead of reusing round 2's borrowed value:
filtered round 1's control-bucket heartbeats to `vj_mode==CRUISE` and
`energy_slope > build_energy_threshold` (`_enter_build()`'s own CRUISE-
branch gate, per-row threshold by that row's `vj_profile` — 0.13 normie/
raver/tweaker, 0.22 chill), 3854 qualifying ticks pooled across six lists:
`downbeat_confidence` p25 0.408, **median 0.528**, p75 0.624, p90 0.704 —
confirming 0.71 sat almost exactly at this population's own p90, which is
why it cost as much as it did. At the median (`0.53`): build cost **−25.6%**
vs rc.16 control, squarely inside the predicted 20-40% band; build trend
37.8%, between rc.16's 36.0% and 0.71's 40.6% as predicted. Breakdown
(−18.7%) and climax (−27.8%) moved anyway even though neither mechanism's
own gate was touched — the third round running the **compounding-cycle
effect** appears (any build-count change costs breakdown/climax downstream
regardless of which mechanism did the cutting), now treated as a standing
property of the state machine rather than a per-mechanism side effect.
Qualifies as a panel candidate (`build-floor-median`) per the pre-
registered decision rule.

**What's next.** `climax-4` and `build-floor-median` (0.53) both carry to a
pending full 19×2 panel (cells: rc.16 control, climax-4 alone,
build-floor-median alone, climax-4 + build-floor-median together, per the
sub-additivity finding above) — deferred until Program B step 3's detector
work lands, so the panel runs once on the shipped detector rather than
being invalidated by a mid-panel detector change. `drop_cruise_min_
confidence` stays parked (worse-than-population energy-lift, no clear path
forward proposed). No default changes with this landing; every constant
above ships at its rc.16-reproducing no-op value.

### E5 addendum 2 — the clock gated behind a new write-path knob, not applied unconditionally (2026-09-03, Program B step 3 batch 1)

The redesign from the first addendum landed in code this batch, but NOT
as an unconditional replacement of the old clock: a new `env_source`
config (`'pulses'` default / `'dense_flux'`) selects between two complete,
separately-implemented method pairs (`_advance_envelope_legacy`/
`_pulse_envelope_legacy` vs `_advance_envelope_e5`/`_pulse_envelope_e5`),
verified bit-identical to shipped rc.40 in `'pulses'` mode on real
production tracks (per-tick BPM series equality, not just p50) —
mirroring the addendum's own finding that the fixed clock ALONE, with
sparse peak-picked pulses still driving it, is a net regression (13 → 10
exact on the 22-hardest set) until the decision stack is re-tuned.

`'dense_flux'` bundles the E5 clock together with a dense, continuously-
written onset-strength envelope (`audio.spectral_flux`, causally
normalized, log-compressed — reproducing the onset-prototype bench's
`stock-odf` row exactly, see Program B step 2's own entries above) rather
than shipping the clock fix in isolation. Batch 1's 22-hardest-track
checkpoint (decision stack completely untouched) found this combination
does not merely avoid the addendum's regression — it reverses it: 15/22
exact (vs 13/22 stock), 22/22 Acc2 (vs 20/22), churn ~4x lower, and the
two house tracks the addendum names by name (Bon Jovi, Tim Cosmos) both
stay exact under `dense_flux` on v2 where they fold to half tempo under
the old clock with sparse pulses. Full report:
`tools/baselines/program_b_step3_batch1-2026-09-03.md` (training-kit-01).

Detector version stays `rc.40` for this landing — nothing shipped
changes, `'pulses'` is the default and is bit-identical to it. `'dense_
flux'` becomes the default only after batch 2's retune (comb/prior/gate
stack re-tempered against the new observation, v2's synthetic click
fixtures re-derived with jitter, then the 19-list panel against madmom/
BTrack), at which point this lands as detector rc.41 with its own ADR
entry closing E5 properly.

## Data-Derived expected_bands — Recommender rc.27 (2026-09-03)

**Finding.** Live diagnosis (owner: "we should have all the data we need
to dial those in") of a recurring recommender artifact -- `dubstep` was
winning `_profile_score()`'s composite on almost every non-dubstep
training list (house-01, deep-house-01, tech-house-01, trance-01, even
ambient-01, confirmed on the live `favorites/004` bucket too) -- traced to
`spectral_shape_fit` (weight `2.5`, the single heaviest term in the
composite). Read `_DEFAULT_RECO_WEIGHTS` directly before assuming
anything: `tempo_fit` and `centroid_fit` are BOTH weight `0.0` (retired
2026-08-20), so the two mechanisms first proposed -- a tighter
`dubstep_bpm_prior_sigma`, a centroid term -- were structurally
impossible regardless of any real overlap between dubstep's tempo/
centroid priors and house-family material's own.

Recomputed `spectral_shape_fit` per-tick from real corpus rows (real
`bands`, real `kick_regularity`, real `vocal_hnr`/`vocal_fmr` against each
profile's own shipped `expected_bands`/`vocal_hnr_mu`/`vocal_fmr_mu`) for
`dubstep`/`deep_house`/`peak_time` on `training-house-01`, `training-
trance-01`, and live `favorites/004`: `spectral_shape_fit` alone accounts
for nearly the entire margin in every case, `kick_regularity_fit` (weight
`1.5`) is a near-wash across all four candidate profiles checked (within
~0.05 weighted), `vocal_hnr_fit`/`vocal_fmr_fit` are identical between
`dubstep` and `peak_time` (same uncalibrated 0.35/0.25 targets) and
`deep_house`/`house` get a free pass (uncalibrated → 0.0) on those two.
`zcr_fit` (weight `0.7`) and `onset_fit` (weight `1.5`) -- `2.2` of the
composite's `7.1` total weighted mass -- were not reconstructable from any
corpus row at the time this diagnosis started (see the corpus-fields
entry below).

**Root cause.** Every *measured* mean-band vector -- the arithmetic mean
of `bands` across many tracks/onsets over time, which is also exactly
what the live recommender's own `band_mean_vec` (`auto_vj.py:5583`, a
rolling-window mean) computes before comparison -- is a smooth,
monotonically decaying curve. Every *shipped* `expected_bands` was a
hand-authored, jagged, multi-peak array (several local maxima across the
64 bands, presumably modeling idealized harmonic partials rather than an
actual band-averaged spectral envelope). A smooth curve cosine-matches
another smooth curve far better than it matches a jagged one, independent
of genre. `dubstep`'s own old fingerprint happened to be the closest-to-
correct-shape in the whole roster by accident (`cos(measured, old
shipped) = 0.971`) -- not because it was better *authored* for dubstep
specifically, but because it was less badly shaped than everyone else's.
`house`'s own old fingerprint scored the *worst* self-similarity of the
entire roster (`0.671`) -- house material didn't even cosine-match
house's own profile well. This is a roster-wide shape-authoring mismatch,
not a dubstep-specific bug.

**Fix.** Replace every profile's `expected_bands` with a data-derived
fingerprint: the mean `bands` vector over that profile's own matching
training list's packaged corpus (both seeds pooled). See weights-and-
thresholds.md "Data-Derived expected_bands" for the full per-profile
source-list table, the three owner-decided coverage mappings
(`downtempo→chillstep`, `big-room→peak_time` pooled with techno-01,
`progressive-house→deep_house`, the last decided by pairwise measured-
fingerprint cosine similarity per the owner's own stated rule, with the
caveat that the three-way spread is only 0.0017 wide and progressive is
actually numerically closest to `house` by raw distance), and the six
profiles with no matching list at all (kept unchanged, nothing to derive
from) -- `psytrance`, `electronic`'s OWN copy-of-house is regenerated to
match house's new fingerprint (preserving the deliberate "identical
except vocal terms" design the dance/house split depends on -- caught by
`tests/test_audio_profile_deep_house_and_disable.py`'s own invariant test
before landing, not after), `hard_techno`, `hardstyle`, `hyphy`,
`synthwave` untouched.

**Validation before landing, decided by data not opinion per the owner's
own instruction:**

- Fit on seed 1 (both training list seeds pooled for the final fingerprint
  itself, but the validation split uses seed 1 alone as the fit set),
  evaluate on seed 2 (`spectral_shape_fit` alone, decision stack
  otherwise completely unchanged): house-01, deep-house-01, tech-house-01,
  trance-01, dubstep-01, dnb-01 all have their own correct genre win the
  held-out composite under measured fingerprints; under the OLD shipped
  fingerprints `dubstep` won every one of those six lists except
  dubstep-01 itself.
- Fit on the 01 list, evaluate on a genuinely different, independently-
  recorded session where one exists: `training-ambient-02` (a true
  numbered sibling) -- measured fingerprint beats dubstep's own shipped
  fingerprint by `+0.076`; `training-normie-trance` (a trance-adjacent
  list, explicitly NOT a literal numbered sibling, flagged as such rather
  than presented as equivalent) -- beats dubstep by `+0.141`. No sibling
  bucket exists for `house` -- reported as a real blind spot in this
  validation rather than silently substituted for.
- Live `favorites/004` (mixed-genre, no single correct answer by
  construction): `dubstep`'s margin over `deep_house` collapses from
  `0.337` (shipped) to `0.002` (measured) -- expected for a genuinely
  mixed list, not a failure of the fix.

**Caveat.** This whole validation pass used `spectral_shape_fit` alone --
the only dominant term reconstructable from already-packaged corpus rows
at diagnosis time. Whether the full composite (once `zcr`/
`onset_density_1min` corpus data accumulates) tells the same story is
untested; the direction and margin on the reconstructable 69% of the
composite's weighted mass is strong enough to land on, per the owner's
explicit "land it" on both this and the corpus fields below, but the
remaining 31% is a genuine unknown, not assumed to agree.

**Bookkeeping.** `_RECOMMENDER_VERSION` → `1.0.0-rc.27`. `_VJ_WEIGHTS_
DOC_VERSION` → `82`. `unicornviz/audio/profiles.py` changed (10 profiles'
`expected_bands` + `electronic`'s copy). No `_DEFAULT_RECO_WEIGHTS` value
changed -- this is a per-profile fingerprint replacement, not a weight
retune.

## Corpus Fields: zcr, onset_density_1min (2026-09-03, recommender rc.27)

**Why.** `zcr_fit` (weight `0.7`) and `onset_fit` (weight `1.5`) --
`2.2` of the recommender composite's `7.1` total weighted mass -- had no
reconstructable-from-corpus input at all, discovered while diagnosing the
`expected_bands` finding above: any future audit of "why did the
recommender pick X" could only ever explain `spectral_shape_fit`/
`kick_regularity_fit`/`vocal_hnr_fit`/`vocal_fmr_fit` (`4.9` of `7.1`),
never the other two terms, regardless of how good the corpus logging
otherwise is.

**What landed.** `AudioData.zcr` (`unicornviz/effects/base.py`,
`__slots__` + `copy_audio_data()`, following the exact established
pattern from the 2026-08-09 `vocal_hnr`/`vocal_fmr` copy-site bug this
project has already been bitten by twice): zero-crossing rate of the last
512-sample waveform window, computed once in `Analyzer.process()`
(`unicornviz/audio/analyzer.py`), same formula the recommender's own ad
hoc inline computation already used (that inline computation is left
unchanged -- this is a corpus-logging addition, not a live-scoring
behavior change). `AutoVJController._onset_density_1min()`: onsets/second
over a trailing 60s window (`self._onset_density_1min_history`, a plain
timestamp deque, cleared on the same toggle-off/on path
`_last_onset_count` already resets, guarding the exact "physically
impossible density after a disabled gap" failure mode that field's own
2026-08-XX comment documents), deliberately independent of the
recommender's own shorter-window live `onset_density` computation so this
addition cannot perturb live scoring. Both reach every corpus row via
`_build_live_training_row()`, the single source-of-truth row builder.

**Bookkeeping.** Additive only -- no existing field, weight, or
live-scoring computation changed. `training-kit-01` and core
(`unicornviz`) both patch-bumped for this landing (the corpus schema
changed in core; the packager/LLM-payload side is training-kit-01's).

## Vocal-Term Calibration — Recommender rc.27, Same Day (2026-09-03)

**Diagnosis, and how the original hypothesis turned out wrong.** A
follow-up to "Data-Derived expected_bands" above, from a hard owner
requirement: `house` (not `deep_house`) must win `training-house-01`'s
recommendation. The working hypothesis going in was that this was a
progressive-house pooling-decision problem -- `training-progressive-
house-01` has no profile of its own, and the expected_bands work above
had pooled it into `deep_house` on a `0.0017`-wide cosine-similarity
margin (see that section). Three different pooling configurations were
tested (progressive into `deep_house`, into `house`, and split/excluded)
to see which one let `house` win its own list. All three produced nearly
identical `deep_house`-dominates-everywhere behavior -- the pooling
choice itself was not the deciding factor, a negative result reported
plainly rather than picked-and-presented-as-fixed.

Isolating the composite with `vocal_hnr_fit`/`vocal_fmr_fit` excluded
broke the deadlock: with vocal terms out of the picture, `house` *does*
cleanly win `training-house-01` under configs A and B. The actual driver
was `deep_house` being the only one of the ten data-derived-fingerprint
profiles with `vocal_hnr_mu`/`vocal_fmr_mu` left `None` ("intentionally
left uncalibrated" per its own prior field comment, on the theory that a
fabricated target would be worse than no signal). That theory doesn't
hold given how `_profile_score()` actually treats `None`: the term
returns exactly `0.0` for a `None` mu -- not a neutral abstention, but a
free pass no calibrated profile gets, since every calibrated profile
instead pays a real (usually negative) Gaussian penalty against observed
`vocal_hnr`/`vocal_fmr`. Weighted (`0.4 + 0.5 = 0.9` combined, though the
effective near-zero-cost advantage is closer to `~0.31` once the other
profiles' typical penalties are accounted for), this was large enough to
override `deep_house`'s otherwise-correct spectral/tempo mismatch on most
lists -- the pooling question this was originally diagnosed alongside was
a red herring.

**A correction surfaced during this work, not a new finding but worth
recording:** an earlier instruction to "keep sigmas as shipped unless a
profile has none" doesn't map onto anything real in the code. No
per-profile `vocal_hnr_sigma`/`vocal_fmr_sigma` field exists anywhere
(verified by grep) -- the sigma is a flat, hardcoded constant (`0.20` for
`vocal_hnr_fit`, `0.15` for `vocal_fmr_fit`) applied identically to every
profile inside `_profile_score()`; only the `mu` (target) is per-profile.
All measurements in this entry already used these correct flat constants.

**Fix.** Every profile with a matching training list -- the same ten as
the `expected_bands` entry above -- gets `vocal_hnr_mu`/`vocal_fmr_mu`
set to the **median** `vocal_hnr`/`vocal_fmr` over its own source
list(s), using the identical pooling already established for that
profile's `expected_bands` (so a profile's spectral fingerprint and its
vocal targets are measured over the same corpus rows). Median, not mean,
matching the same reasoning as the corpus-wide medians already used
elsewhere: bounded `[0,1]` features with a long tail on sparse-vocal
lists. Four profiles gained the fields for the first time
(`deep_house`, `ambient`, `chillstep` -- all previously `None` -- plus
`rap_rnb`, which had a real prior hand-set value, `0.58`/`0.53`, updated
to the measured median rather than left as a guess once real data
existed); six replaced the generic `0.35`/`0.25` default
(`house`, `tech_house`, `peak_time`, `trance`, `drum_and_bass`,
`dubstep`). `electronic` ("dance") keeps its deliberate near-zero
`0.05`/`0.05` unchanged -- that pair's entire purpose is being
house-identical-minus-vocals, not a value this measurement pass should
touch. See `weights-and-thresholds.md`'s "Vocal-term calibration" section
for the full per-profile table and both re-score tables below.

**Gate result.** `training-house-01` winner = `house`, margin `0.032`
over `deep_house` -- the hard requirement this work was landed against.

**Caveat, reported plainly rather than smoothed over.** This is not a
clean fix. Re-scoring the full composite across all 14 lists with a
defined "correct" profile plus the live favorites mix shows 5/14
own-profile wins (unchanged in *count* from before this fix -- but
`training-house-01` moved from a loss into the win column, which is what
was asked for). The side effect: fixing `deep_house`'s free pass shifted
broad cross-list dominance onto `house` itself -- `house` now wins 8 of
the 14 non-own lists (`training-progressive-house-01`,
`training-tech-house-01`, `training-techno-01`, `training-big-room-01`,
`training-drum-and-bass-01`, `training-dubstep-01`,
`training-downtempo-01`, `training-trap-hip-hop-01`), and
`training-deep-house-01` -- `deep_house`'s own list -- now loses to
`peak_time` by a margin (`0.0014`) that reads as noise, not a real
decision. Several other "no" margins (`training-dubstep-01` at `0.0017`,
`training-downtempo-01` at `0.0011`, `training-hip-hop-01` at `0.0001`)
are similarly toss-up-sized. The likely root cause: `house`'s own
measured `expected_bands` is the smoothest, most generic-4/4-shaped
curve in the roster (see the `expected_bands` entry above), which makes
it a naturally strong runner-up cosine-match against almost any
kick-driven material regardless of genre -- closing the vocal-term gap
that previously worked *against* it was apparently enough to let that
runner-up-everywhere quality surface as outright wins on lists it has no
real claim to. This is flagged, not fixed, by this landing; it is the
owner's call whether further work here is warranted.

**A separate, deliberately-deferred owner question.** 2026-09-01 raised
whether `vocal_hnr`/`vocal_fmr` measure vocal presence at all -- a
mid/side feature is said to have superseded them. Whether to zero
`vocal_hnr_fit`/`vocal_fmr_fit` entirely (the way `tempo_fit`/
`centroid_fit` were zeroed 2026-08-20) is that question, and this landing
does **not** decide it. A "vocal terms zeroed" comparison was computed
as the data point the owner asked to see (not applied): 4/14 own-profile
wins (one fewer than the calibrated-vocal-terms result above), and
notably `training-dubstep-01` would flip its winner to `deep_house` --
dubstep's own vocal calibration turns out to be one of the things
currently keeping it winning its own list. This does not itself argue for
or against zeroing; it only shows what trade a future decision would be
making. Full tables for both re-scores in `weights-and-thresholds.md`.

**Bookkeeping.** Value-only change (median targets on existing fields) --
`_RECOMMENDER_VERSION` stays `1.0.0-rc.27` (see its own field comment in
`auto_vj.py` for the same reasoning already applied to the
`expected_bands` landing); `_VJ_WEIGHTS_DOC_VERSION` bumped 82 -> 83;
drop-in `__version__` bumped to `1.0.0-rc.117` with a combined changelog
entry covering both this and the `expected_bands`/corpus-fields landing
above, since all three land in the same commit batch. Raw per-list score
data behind both re-score tables: `training-kit-01/tools/baselines/
progressive_house_pooling_configs-2026-09-03.json` (the three pooling
configs tested) and `vocal_calibration_comparison-2026-09-03.json` (the
calibrated and vocal-zeroed re-scores).
`recommender_fingerprints.py` gained `vocal_medians_list()`/
`vocal_medians_pooled()` and a `vocal-medians` CLI subcommand, mirroring
its existing `measure`/`measure_pooled` fingerprint-derivation functions,
so this measurement is reproducible offline against any future
corpus refresh.

**A test's premise changed, not a weakening -- recorded explicitly so it
doesn't read as a silent one later.**
`tests/test_bpm_detector_audit_regressions.py::_make_trust_test_stub`
builds a hand-tuned `house`-vs-`deep_house` fixture whose whole point is a
small, deliberately non-trivial score margin, so the two sibling tests
(`test_low_detector_trust_requires_bigger_margin_to_confirm` /
`test_high_detector_trust_confirms_at_configured_margin`) can tell apart
"low detector_trust demands a bigger effective margin" from "the margin
was just too small to confirm regardless of trust." That margin was
tuned via one knob, `onset_count`, against the OLD `deep_house` (`None`
vocal mus, i.e. the free pass this ADR entry just removed) -- removing
the free pass moved `deep_house`'s score up on this fixture's fixed
`vocal_hnr=0.0`/`vocal_fmr=0.0` stub inputs (both profiles now pay a real
penalty instead of `house` paying one alone), which blew the fixture's
margin from `~0.157` up past both trust-scaled thresholds at the old
`onset_count=1.9` (weak-trust confirmed `True` where the test asserts
`False`). This is the trust-scaling MECHANISM staying correct while an
*unrelated* input (this fixture's incidental margin size) moved out from
under it -- not evidence the mechanism itself weakened. Re-tuned the same
single knob the fixture's own history already used this same way
(`onset_count` `2.25 -> 1.9` on 2026-08-10, per that constructor's own
comment) to `1.10`, landing the margin back at `~0.161` (verified
directly against the live `_update_profile_recommendation()` code path,
not guessed): weak-trust effective threshold is
`profile_auto_reco_score_margin / max(detector_trust, _TRUST_FLOOR)` =
`0.08 / max(0.129, 0.15)` = `0.08 / 0.15` = `0.533` (margin `0.161` stays
under it, so still correctly `False`); strong-trust threshold is
`0.08 / max(0.958, 0.15)` = `0.08 / 0.958` = `0.0835` (margin `0.161`
clears it, so still correctly `True`). Both tests pass with their
original assertions and original intent unchanged -- only the incidental
fixture value moved, and it moved for a fully understood, documented
reason (see the constructor's own updated docstring for the same math).

## Complex-Domain Onset Function Ported and Shipped as Live Default (2026-09-04, detector rc.41)

**Context.** `tools/beat-tracker-bench/`'s OSS comparison (see
"OSS Beat-Tracker Bench" above and `detector-scorecard.md`) found that
`env_source='dense_flux'` (landed 2026-09-03, the E5 envelope-clock fix
plus a continuous `spectral_flux` write) closed most of the gap to
madmom/BTrack, and that swapping in a hand-designed complex-domain onset
function (Bello, Duxbury, Davies & Sandler 2004) on top of that closed
the rest: 76.5%/96.7% Acc1/Acc2, the single best-graded row on the whole
scorecard, ahead of every real external competitor this project could
actually ship. That row was measured entirely inside the bench harness,
though -- the onset function itself was never wired into the live app.

**What actually needed porting, and why it turned out cheap.** The
bench's `v3_odf_tracker.py` fed a *precomputed whole-track* ODF stream
into a scratch `BeatTrackerV3` subclass for convenience; a real port
needs the function running causally inside the actual per-tick audio
pipeline. Two things made this simpler than it first looked:

1. `env_source='dense_flux'`'s own dense-write architecture already
   solves the hard part -- `beat_grid.py` already reads one raw scalar
   per tick from `AudioData`, runs it through an already-ported causal
   median/MAD normalizer, and writes the result into every envelope slot
   the tick advances through. The only thing `spectral_flux` and a
   complex-domain ODF value differ on is *which raw scalar* -- the
   write/normalize machinery is identical. Adding `'dense_complex'` as a
   third `env_source` value was a ~10-line dispatch change (`update()`
   picks `complex_onset_flux` vs `spectral_flux` by source; every other
   site just needed `== 'dense_flux'` broadened to `!= 'pulses'`).
2. `Analyzer.process()` already computes a 1024-point `rfft` every tick
   for the magnitude spectrum (`bands`/`spectral_flux`/vocal features) --
   the complex-domain function needs that same FFT's *phase*, which was
   being computed and silently discarded. Extracting `np.angle()` from
   the already-computed `fft_raw` costs nothing extra; no second FFT, no
   separate windowing/hop/buffering state the way the bench's standalone
   `ComplexOnsetDetector` class needed for its own convenience.

**What landed.**
`Analyzer._compute_complex_onset_flux()` (`unicornviz/audio/analyzer.py`)
-- a two-frame magnitude/phase history (mirrors
`complex_onset.py`'s `ComplexOnsetDetector._process_frame()` exactly:
predicted magnitude = previous frame's; predicted phase = constant-phase-
advance from the previous two frames; ODF = Euclidean distance between
predicted and observed complex spectra, summed across bins), exposed as
a new raw (un-normalized) `AudioData.complex_onset_flux` field, following
the same `__slots__`/`__init__`/`copy_audio_data()` pattern every prior
field addition this session used. `beat_grid.py` gained `'dense_complex'`
as a third `_env_source` value, reusing the `'dense_flux'` normalizer/
dense-write path unchanged, reading `complex_onset_flux` instead of
`spectral_flux`. `_DETECTOR_VERSION` bumped rc.40 -> rc.41.

**Landed as the live default, not opt-in.** Owner direction, stated
directly: for a single-user deployment, the shipped *default* should
track whatever is currently the best-tuned, accepted state -- not a
conservative fallback kept for hypothetical stability. (A genuinely
public release, the owner noted, would only ship stable/accepted
versions anyway, so this isn't in tension with that case -- it only
changes what "accepted" means for a one-user, actively-iterated
deployment.) `env_source`'s CODE default stays `'pulses'` (unaffected,
still bit-identical to rc.40); `config.toml`'s `env_source` line is set
to `'dense_complex'` explicitly, which is what the running app actually
uses -- the established config.toml-as-per-deployment-override pattern,
not a change to what a fresh install gets by default.

**Verification, and its honest limits.** Full regression suite green
(2138 passed). Mechanism-level regression tests added
(`tests/test_envelope_advance_rate.py`): the 100 Hz write-rate tests
already covering `'dense_flux'` mirrored for `'dense_complex'`, plus a
new test confirming the field-selection dispatch actually reads
`complex_onset_flux` (not silently falling through to `spectral_flux`
regardless of `env_source`, which every other test in that file would
have passed anyway since both fields are floats and the write mechanism
is identical). End-to-end smoke test: a synthetic 128 BPM click track
through the real `Analyzer` + `BeatTrackerV3` pipeline locks to 128.12
BPM at 0.998 confidence under all three `env_source` values
(`'pulses'`/`'dense_flux'`/`'dense_complex'`), confirming the port
doesn't break basic tempo lock. **What this does NOT confirm:** the
bench's own 76.5%/96.7% numbers were measured via the precomputed-
whole-track convenience path against the *bench's own* `beat_grid_e5.py`
copy, not this specific live port -- the 306-track corpus has not been
re-run against the actual shipped code. Ships with stock decision-logic
constants throughout (no re-tune -- Program B step 3 remains open). The
owner's own framing: ship the architecture change now, treat further
tuning as a live activity during the soak rather than a pre-ship gate.

**Bookkeeping.** `_DETECTOR_VERSION` rc.40 -> rc.41;
`_VJ_WEIGHTS_DOC_VERSION` 83 -> 84; `weights-and-thresholds.md`'s
`env_source` row and Changelog updated; `detector-scorecard.md`'s top
row's "Shippable" column and "How we're doing" section updated to
reflect the live port and its verification gap, not just the bench
number. No `training-kit-01` packager sync needed -- this is a detector
mechanism/field change, not a recommender weight or threshold in any of
the three `_*_CONSTANT_DEFAULTS`/`_RECO_WEIGHT_DEFAULTS` dicts that
obligation covers.

## Spectral-Shape Ribbon Redesign (2026-09-04, recommender rc.28)

**Diagnosis.** Owner: "the math is NOT mathing right, not at all." Correct
-- `expected_bands` (landed hours earlier the same night, rc.27) was the
mean `bands` vector across an ENTIRE playlist session's frames, pooling
many different tracks. Averaging that many tracks converges toward
whatever's common to all of them (a generic decaying-with-frequency
shape), erasing the track-specific texture that would actually
discriminate genres. Confirmed by computing the full pairwise cosine
matrix across all 11 data-derived fingerprints from the rc.27 landing:
every pair scored >=0.94, several >=0.99 -- `spectral_shape_fit`, the
single heaviest weight in the composite, was barely discriminating
anything. This was the actual mechanism behind the whole night's
recurring "one profile sweeps the entire roster" pattern (dubstep, then
house, then techno each took a turn as the composite's default winner):
whichever profile's fingerprint happened to have the tallest/smoothest
low-band plateau won as a generic runner-up almost everywhere, because
the term itself carried almost no real per-genre signal to begin with.

**Fix -- two changes together, not one.**

1. **Aggregate to one point PER TRACK first, not per frame.** A long-
   playing track shouldn't dominate a short one just by contributing more
   logged heartbeats. Then take **robust statistics across those
   per-track points**: median (not mean -- "toss the anomalous noise",
   same reasoning already used for the vocal-term calibration earlier
   the same night) becomes the new `expected_bands`; MAD-derived spread
   (`1.4826 * MAD`, floored at 15% of that band's own median so a small
   real sample doesn't collapse to an unrealistically confident near-zero
   sigma) becomes a new field, `AudioProfile.expected_bands_sigma`.
2. **`spectral_shape_fit`'s own formula changes**, for any profile that
   sets `expected_bands_sigma`: a per-band Gaussian log-density (`-0.5 *
   ((band - mu) / sigma) ** 2`, mean across the 64 bands, mirroring every
   other `*_fit` term's shared shape) against `expected_bands` as mu --
   not cosine similarity. A profile with `expected_bands` but no
   `expected_bands_sigma` (`psytrance`, `hard_techno`, `hardstyle`,
   `synthwave` -- no matching training list, still hand-authored) keeps
   the legacy cosine-similarity path unchanged; the redesign is
   additive/opt-in per profile, not a wholesale behavior change for
   profiles with no ribbon data.

**Bug #1, caught before it was reported as a finding.** The first
validation pass built ribbons from per-track means, then scored raw
individual FRAMES against them. A ribbon's width, calibrated on
track-level smoothness, is far tighter than real frame-to-frame variance
within a single track (a kick hit vs. a quiet passage) -- house-01
scored *worse* against its own genre's freshly-built ribbon than against
an unrelated genre's, an immediate tell that something was mismatched,
not a real result. Fixed by scoring track-means against track-means
throughout the validation, which also happens to be the fairer
comparison: the live system's own `band_mean_vec` is itself a
rolling-window mean, not a raw single frame, so track-level scoring is
what actually matches production behavior.

**Bug #2, also caught, not shipped as a "finding."** With bug #1 fixed,
`rap_rnb` (pooling `training-hip-hop-01` + `training-trap-hip-hop-01` +
`training-rnb-01`) swept nearly every list. Traced directly: `rap_rnb`'s
pool was both the most diverse (three sub-genres) and highest-count (46
tracks vs. everyone else's 11-17) of the whole roster, producing a
wider, more "generically forgiving" ribbon -- a third variant of the
same night's recurring pathology, this time via pooling breadth rather
than plateau height. Explicitly checked and ruled out as the cause: the
missing `-log(sigma)` log-normalizer term in the shared `_gaussian_fit()`
helper (a true Gaussian log-density penalizes a wide sigma via that
term, which the codebase's simplified version omits everywhere it's
used) -- added it back and re-ran the same comparison; made negligible
difference. The pooling breadth itself was the real cause.

**Resolved by an evidence-gated split, not a guess.** Owner: "trap
should def be on its own" (decided directly, not evidence-gated) --
"rnb/hh i'll let u decide based on evidence" (left open). A per-list
confusion-matrix check (own tracks scored against each of the three
lists' own ribbons, spectral_shape_fit only) found hip-hop-01 and
rnb-01 the least separable pair of the three -- consistent with, and
reaffirming, the original 2026-08-06 "genuine siblings" merge finding
for these two -- while trap-hip-hop-01 discriminates clearly from both.
Landed: `training-trap-hip-hop-01` split out into a **re-enabled**
`hyphy` ("Hyphy / Trap") profile -- disabled since 2026-08-10 for
exactly the reason this closes (no real trap/hyphy material to validate
against); `rap_rnb` keeps hip-hop + rnb pooled. `hyphy`'s
`bpm_prior_mu`/`sigma`/hint band were also fully recalibrated from
trap-hip-hop-01's own real detected-bpm distribution (median 141.2 BPM)
-- the old hand-guessed 100-118 range predates any real trap data and
turned out far off (same "produced vs. perceived pulse" pattern already
documented for `dubstep`).

**Weight-rebalancing finding, checked empirically not assumed.** Cosine
similarity, measured directly, returned ~0.93-0.99 for nearly any real
audio against nearly any profile -- despite the heaviest weight in the
composite (2.5), it functioned closer to a near-constant +2.3-ish bonus
every candidate received roughly equally than a real discriminator. The
ribbon fit actually swings (~-0.2 for a good match, -1 to -3+ for a bad
one) -- so the OLD weight instantly overpowers every other term the
moment the formula has real signal to carry. Swept empirically
(`recommender_fingerprints.py`, track-level scoring, full 12-profile
roster including the ribbon fix and the trap split): own-profile wins
peak at **8/14** across weight 0.3-1.0 and fall back to 6/14 at the old
2.5. Landed at **0.7**, the middle of the stable plateau rather than the
exact peak -- owner, explicitly declining further tuning: "don't worry
too too much about tuning those, things are going to change again after
the low band fix anyway."

**Gate result.** 8/14 own-profile wins, up from rc.27's 4/14. Remaining
losses cluster specifically within the closely-related house/techno
family (`deep_house`, `tech_house`, `techno`, `peak_time`, `hyphy` mostly
losing to `house` itself) -- a qualitatively narrower failure than
rc.27's roster-wide sweep, and one that lines up with `tempo_fit` (still
weight 0.0) being the natural remaining discriminator for exactly this
tempo-differentiated cluster.

**Tempo term, explored the same session, deliberately NOT landed.**
Owner asked to bring `tempo_fit`'s weight in alongside this. Deriving
real per-list `bpm_prior_sigma` (median + MAD in log2 space, `bpm_locked`
rows) surfaced a genuine complication, not a data bug: weak-beat genres
(`ambient`, `chillstep`) show wildly unreliable detected BPM even on
rows flagged `bpm_locked` -- `ambient`'s own "locked" median read ~139
BPM against a `bpm_prior_mu` of 100, driven by a single mostly-beatless
track ("Andrew Mcfarlane - Morning Air") the detector never had a real
periodic signal to converge on, so its nominal "lock" doesn't mean the
same thing a rhythmic genre's lock does. A fair fix needs the same
missing `-log(sigma)` log-normalizer term investigated for bug #2 above,
landed properly in the shared `_gaussian_fit()` helper (used by every
`*_fit` term in the composite, not just this one) so an honestly-wide
sigma is appropriately less rewarded rather than a free pass --
meaningfully bigger scope than a same-night weight sweep. Parked;
`tempo_fit` stays at weight `0.0`, unchanged.

**Bookkeeping.** `_RECOMMENDER_VERSION` rc.27 -> rc.28 (structural term-
computation change, not value-only -- the formula itself changed, per
the subsystem-versioning rule); `_VJ_WEIGHTS_DOC_VERSION` 84 -> 85.
`AudioProfile` gained `expected_bands_sigma`
(`unicornviz/audio/profiles.py`). `recommender_fingerprints.py`
(training-kit-01) gained `per_track_band_means()`, `band_ribbon()`,
`gaussian_ribbon_fit()`, `ribbon_for_lists()`; `_load_profiles_from_core()`
and `diagnose_list()` now read/use `expected_bands_sigma` when present;
`RECONSTRUCTABLE_WEIGHTS['spectral_shape_fit']` updated to match the new
live weight (0.7). New regression tests: `tests/test_spectral_shape_
ribbon.py` (the ribbon-vs-cosine dispatch itself, driven through
`_profile_score()` via the established stub-harness pattern) plus
updates to `tests/test_audio_profile_deep_house_and_disable.py` for
`hyphy`'s re-enable and the retired cosine-similarity invariant it used
to pin. Full suite green (2144 passed) before landing. See
`weights-and-thresholds.md`'s "Spectral-Shape Ribbon Redesign" for the
per-profile table pointer and Changelog entry.

## Low-Band Resolution: Dual-Window Fix (2026-09-04)

**Diagnosis.** The shared 64-band perceptual spectrum
(`unicornviz/audio/analyzer.py`, consumed by every effect and by
`spectral_shape_fit`'s ribbon fit above) buckets a single 1024-sample FFT
(46.875 Hz/bin at 48kHz) into 64 log-spaced bands from 30Hz-16kHz.
Verified directly: **19 of those 64 bands collapse onto a shared FFT
bin** -- bands 0 through 8 (9 of them) read the exact same number, every
frame, for every track, regardless of genre, because the log spacing
between 30-72Hz requests far more resolution than a 46.875 Hz/bin FFT
can deliver. Confirmed on 100/100 sampled real corpus rows: bands[0:8]
bit-identical every time. This is not a feature-ceiling problem (as
first framed) -- it's a measurement-resolution bug feeding fake
precision into every downstream consumer, and it's what let the
spectral-shape-fit redesign above still show ~19-25 duplicated bands
even after fixing the averaging methodology.

**Options considered.**

1. **Widen the shared short window** (e.g. 1024 → 2048 or 4096). Simple,
   but every effect reading `audio.bands` per-frame was built assuming
   that data reflects the current moment -- widening adds real latency
   to transient response (2048: +~21ms; 4096: +~64ms), and the cost is
   BPM-dependent: at 174 BPM (drum & bass) a 16th note is only 86ms, so
   a 4096-sample window's ~85ms span would smear nearly a full 16th
   note's worth of transient timing, worst exactly where transient
   response matters most. Not chosen -- would need a live smoke test to
   confirm effects still read right, and the risk falls hardest on fast,
   percussive genres.
2. **Dual window: a second, independent long-window FFT, low bands
   only.** Chosen -- see "What landed" below.
3. **True Constant-Q / wavelet transform.** Theoretically the most
   correct match to a log-spaced band scheme (each band gets its own
   window, long for bass, short for treble) but a genuinely different
   architecture, not a parameter change -- added to Open Questions above
   as a to-be-considered item, not pursued now (real implementation/
   testing surface area, no precedent in this codebase, ~3-10x a single
   FFT's cost for an efficient implementation).

**What landed.** A second, persistent rolling PCM buffer (8192 samples,
170.7ms at 48kHz -- chosen because it leaves only ~2 of 64 bands still
collapsed, near the ~30Hz floor itself, down from 19; 4096 alone still
left 7 collapsed) feeds a second Hann-windowed FFT, computed every tick
(negligible cost -- measured ~677us average total `process()` time
against a ~10.7ms real-time budget at 512-sample/48kHz blocks, i.e. the
WHOLE method, long FFT included, uses ~6% of budget). Only the bottom 25
bands (`_LOW_BAND_REPLACE_N`, matching exactly how many collapse under
the SHORT path's own window -- verified against `_recompute_band_edges()`'s
own construction, not eyeballed) get overwritten with the long-window
values; bands 25-63 (already fine at the short window) and every other
effect-facing signal (`bass`/`mid`/`treble`, flux, vocal features) are
completely untouched -- zero added latency for anything except the low
end that was never real to begin with. Scale-corrected by the ratio of
the two windows' sums (`window.sum() / low_window.sum()`) so a sustained
tone's magnitude is comparable across the differently-sized Hann
windows -- matches the existing convention (the short path itself
applies no additional normalization either) rather than inventing a new
one. Verified: fed 20k samples of white noise through the real
`Analyzer.process()` pipeline -- all 25 replaced bands read genuinely
distinct values (were previously 9-19 duplicates).

**An adjacent bug found and fixed in the same pass, not scope creep --
it was load-bearing for this fix's own correctness.** `_perc_edges`
(the short path's own bin-index mapping) was computed ONCE at
construction time from whichever `_sample_rate` happened to be set then
(the module fallback, 48000) and never recomputed.
`Analyzer.set_sample_rate()` (called by `AudioManager` once real capture
is live, and again every frame in case of a mid-session device switch)
updated `_bin_hz` but not the edge table that formula feeds -- meaning a
real device negotiating a different rate (44.1kHz being the obvious
case) silently left the ENTIRE session's band-to-Hz mapping computed for
the wrong rate. Found while making the new long-window edges rate-aware
-- fixing only the new table while leaving the old one newly
inconsistent with it would have been worse than not touching either.
Both edge tables now live in one `_recompute_band_edges()` method,
called from `__init__` and from `set_sample_rate()` on an actual rate
change.

**Open follow-up, not addressed tonight.** Every `expected_bands`/
`expected_bands_sigma` value landed in the Spectral-Shape Ribbon
Redesign above was measured from corpus data captured BEFORE this fix --
meaning the low ~25 bands of every profile's fingerprint still reflect
the old, partially-duplicated measurement. Owner, in advance: "things
are going to change again after the low band fix anyway" -- deliberately
not re-derived in the same session; the next fingerprint refresh should
account for genuinely-resolved low-band data changing those numbers
again, not treat the rc.28 ribbon values as final.

**Bookkeeping.** No `_RECOMMENDER_VERSION`/`_DETECTOR_VERSION` bump --
this is a core `unicornviz` (not `auto-vj-01`) analyzer change, shared by
effects and the recommender alike, not a detector or recommender-scoring
formula change itself. New regression tests:
`tests/test_analyzer_low_band_resolution.py` -- pre-/post-warmup
collapse behavior, the replaced-vs-untouched band boundary, silence
handling (energy-gated like every other block in `process()`), and the
adjacent `set_sample_rate()` edge-recompute fix (both `_perc_edges` and
`_low_band_edges` change on a genuine rate change, stay identical on a
same-rate no-op call). Full suite green (2149 passed) before landing.

## Evidence-Based Recommender Audit: Vocal Sigma, BPM Re-Fit, Centroid Recompute, Four Profiles Disabled (2026-09-04, recommender rc.29)

**Trigger.** Owner, after the log-normalizer fix below changed how
sigma trades off against mismatch magnitude: "we need to eliminate ALL
the hand-picked values in favor of evidence based, asap... and we need
to fix the vocals as well so they function properly." Full audit
delivered field-by-field; owner replied item-by-item ("fix the ones we
evidence for and tell me which ones we don't" / "fix the dump constant
lol, build the thing" / "would have to have amazing evidence to change
[`spectral_centroid_sigma`]" / "may as well fix [`spectral_centroid_mu`]
while we're here" / same on `zcr`/`onset_density` / the new zero-evidence
disable rule), closing with "full send tyvm!"

**What landed** (full tables and per-profile detail in
`drop-ins/auto-vj-01/docs/weights-and-thresholds.md` § "Vocal-Term Sigma
+ Evidence-Based Re-Fit (recommender rc.29)" — not duplicated here):

1. `_gaussian_fit`'s missing `-log(sigma)` normalizer restored — a wider
   sigma had been unconditionally more forgiving with no offsetting cost,
   the real mechanism behind repeated "one profile sweeps every list"
   incidents this project has hit before. Verified on real `house-01`
   BPM data (deficit vs. `chillstep` shrank `-2.69 → -0.91`) without
   flipping the winner outright, which is what motivated the rest of
   this pass — the sigma *values*, not just the formula, needed fixing.
2. Real per-profile `vocal_hnr_sigma`/`vocal_fmr_sigma` fields added to
   `AudioProfile`, replacing a flat `0.20`/`0.15` constant every profile
   shared regardless of genre — the audit's "dump constant." Mu re-fit
   alongside using the same per-track-then-robust-stat methodology as
   `expected_bands`/`expected_bands_sigma` (median per track, ≥10 rows
   required; robust median/MAD across per-track points; sigma floored at
   `0.03`), for all 12 profiles with a real training-list corpus.
3. `bpm_prior_mu`/`bpm_prior_sigma` evidence pass, same per-track/MAD
   methodology (log2 space). Three outcomes, decided per-profile rather
   than applied uniformly: sigma-only for the four house-family profiles
   (their real per-track BPM medians cluster within ~3.5 BPM of each
   other, far tighter than the deliberately non-overlapping hand-dialed
   `bpm_prior_mu` bands from the house-family consolidation ADR entry
   above — moving mu would have silently undone that owner decision, so
   only sigma moved); full mu+sigma update for `techno`/`trance`/
   `drum_and_bass`/`hyphy` (no design conflict, though `hyphy` carries the
   same fold-risk caveat as `dubstep`, flagged not resolved); held back
   entirely for `dubstep` (real evidence conflicts with that profile's
   own documented deliberate anti-fold-contamination sigma) and `rap_rnb`
   (real evidence is very likely the same 4/3-tactus-fold contamination
   an earlier session already investigated and declined to trust — see
   "Vocal-Term Calibration" above for that profile's prior history).
   **House-Family BPM Cluster Finding is flagged here as an open item**:
   the four real per-track medians (house 128.1, deep_house 126.4,
   tech_house 129.9, peak_time 129.9) sit much closer together than the
   hand-dialed bands assume — worth a dedicated look, not resolved by
   this pass.
4. Four profiles disabled under a new standing rule (owner: any profile
   with zero training-list evidence for *any* scoring field stays out of
   discovery until it has some): `psytrance`, `hard_techno`, `hardstyle`,
   `synthwave`. Disabled, not deleted — same pattern as `tech_house`/
   `techno`. `electronic` is explicitly excluded from this rule (its
   near-zero vocal mu is a deliberate house-mirror control design, not an
   unverified guess).
5. `spectral_centroid_mu` mechanically recomputed for the 13 profiles
   whose `expected_bands` moved under the same-night ribbon redesign —
   inert (`centroid_fit` stays weight `0.0`), but the result is worth
   recording: all 13 collapsed into a narrow 250-450 Hz band, reproducing
   (with real per-track data this time) the exact bass-dominant-decay
   failure mode the 2026-08-11 `centroid_fit` incident already
   documented. Flagged directly in `profiles.py`'s own field comment:
   don't re-enable this term's weight against these values without
   addressing that first.
6. `zcr_mu`/`zcr_sigma`/`onset_density_mu`/`onset_density_sigma` —
   confirmed blocked, not fixed. Both fields only started being logged
   into the corpus the same night this pass began; grepped a
   representative packaged training bucket directly and confirmed
   neither field is present in any row, and no bucket anywhere under
   `assets/training/sets/` has been packaged since. Nothing fabricated
   or reconstructed — left untouched pending real accumulated data.

**Out of scope, explicitly not part of this audit:** `spectral_centroid_sigma`
(hand-picked tiers, feeds the same dormant `centroid_fit` term — owner
declined without "amazing evidence"); `bass_weight`/`mid_weight`/
`treble_weight`, `beat_threshold`, `smoothing`, `curve`, `onset_*_emphasis`
(detector/effects-shaping constants, a different category from
recommender scoring — noted for completeness only, not claimed broken).

**Bookkeeping.** `_RECOMMENDER_VERSION` `1.0.0-rc.28 → 1.0.0-rc.29`;
`_VJ_WEIGHTS_DOC_VERSION` `85 → 86`. Full test suite green (2181 passed,
1 skipped) after each phase of this pass. Updated regression tests:
`tests/test_audio_profile_deep_house_and_disable.py` (new disabled-set
entries, `deep_house`'s re-fit vocal mu/sigma),
`tests/test_audio_profile_synthwave.py` (disabled, and the
`spectral_centroid_mu` ordering flip vs. `house` — documented as an
artifact of which profiles have real per-track data now, not a
genre-brightness claim).

## zcr / onset_density Evidence-Based Re-Fit, Correcting rc.29's Own Error (2026-09-04, recommender rc.30)

**The rc.29 entry above claimed `zcr_mu`/`onset_density_mu` were
"blocked, no historical data exists."** That was wrong — a methodology
error, caught by direct owner pushback the same night ("wtf no data for
zcr/onset density? we have 'added everything to the corpus' like a
bazillion times"; "we've had zcr... for a long long time and should
[have] copious amounts of packaged data & headless data from months of
runs"). Kept above with a strikethrough per this doc's own no-rewriting-
history rule, not deleted.

**Root cause of the error.** Two mistakes stacked. First, conflated two
different, unrelated `zcr` mechanisms: a raw per-frame `AudioData.zcr`/
`onset_density_1min` corpus-ROW field (added 2026-09-03, still
uncommitted as of rc.29's landing) — which genuinely has never appeared
in any packaged corpus row, that part of the original check was correct
— versus `mean_zcr`/`onset_density`, live scoring inputs that have
existed inline in `_update_profile_recommendation()` since 2026-06-21
(commit `45b9ed6`, the original "add spectral features" recommender
overhaul) and get logged onto every `profile_recommendation`-type
keyframe row. The rc.29 check only looked for the first. Second, even
allowing for that, it only grepped `assets/training/sets/` — the
*packaged* corpus tree — and never looked in
`assets/training/accelerated/<list>/**/`, a separate, much larger tree
(509 files repo-wide contain `mean_zcr`) that the accelerated-replay
pipeline reads from directly. Real, usable, per-track-attributable data
was sitting there the whole time.

**Fix.** Same per-track-then-robust-stat methodology as every other
evidence-based field this session (median per track, ≥3 keyframe rows
required; robust median → mu, MAD-derived sigma floored at `0.03` →
sigma, raw linear space). Applied to the same 12 profiles with a real
training-list corpus. Full table and the two flagged findings (`zcr_sigma`
landing on the floor for all 12 profiles; `ambient`/`chillstep`'s
`onset_density_mu` jumping ~6.6x/~2x from old hand-guesses) are in
`drop-ins/auto-vj-01/docs/weights-and-thresholds.md` § "zcr /
onset_density Evidence-Based Re-Fit — Correcting rc.29 (recommender
rc.30)" — not duplicated here.

**Regression fallout, understood not blindly re-pinned.**
`test_matcher_flips_fold_when_genre_flips` (`tests/test_genre_matcher.py`)
used a hardcoded `zcr=0.085` that exactly matched `drum_and_bass`'s OLD
`zcr_mu` by construction; the re-fit pulled `rap_rnb`/`drum_and_bass`'s
`zcr_mu` much closer together (0.031 spread → 0.0046) while both
`zcr_sigma` values collapsed to the same `0.03` floor, so sitting exactly
on the new mu no longer cleared the genre-match margin. Swept the input
empirically, found the crossover between 0.08 and 0.09, moved the test's
literal to `0.10` for a stable margin rather than the exact-mu boundary.
The trust-margin fixture (`_make_trust_test_stub`,
`tests/test_bpm_detector_audit_regressions.py`) needed its `onset_count`
knob retuned a fifth time (`1.50 → 2.00`, its own docstring now carries
all five retuning notes in order) — this time swept against both the
low-trust and high-trust setups together, landing in the middle of the
widest stable band found (1.9–2.1) rather than picking the first value
that happened to pass.

**Bookkeeping.** `_RECOMMENDER_VERSION` `1.0.0-rc.29 → 1.0.0-rc.30`;
`_VJ_WEIGHTS_DOC_VERSION` `86 → 87`. Full test suite green (2181 passed,
1 skipped) after landing.

## `centroid_fit` Weight-Dict Entry Removed (2026-09-04, recommender rc.31)

**Owner, same night, after asking "why is [centroid] useless" and being
pointed at the 2026-08-20 retirement entry above (57 real labeled tracks,
five brightness formulations measured, all agreeing scalar full-mix
brightness tracks mastering/loudness rather than genre — the real
spectral evidence lives in `spectral_shape_fit`'s full 64-band fit, its
actual replacement): "let's remove centroid." Scoped, by owner choice
among three options offered (full strip / stop-scoring-keep-telemetry /
just the dead weight-dict entry), to the smallest: delete the explicit
`'centroid_fit': 0.0` line from `_DEFAULT_RECO_WEIGHTS`
(`drop-ins/auto-vj-01/auto_vj.py`). Term computation, `term_values_by_
candidate` telemetry logging, and every profile's `spectral_centroid_mu`/
`spectral_centroid_sigma` fields are all unchanged — this is a weight-
dict cleanup, not a behavioral or data-model change.

**Correctness fix required alongside it.** The composite-score sum
(`composite = sum(w[name] * value for name, value in terms.items())`)
indexed `w` (the live `_reco_weights` dict) directly by name — every
computed term needs a matching weight-dict entry or this raises
`KeyError`. Changed to `w.get(name, 0.0)` so a term with no configured
weight contributes `0.0`, the same as an explicit zero would have.
Without this, removing the dict entry would have crashed
`_profile_score()` for every candidate, every cycle (silently, via the
scoring loop's own `except Exception: continue` — the same failure shape
several earlier bugs this session were caught by, here caught before
landing instead of live).

**Regression fallout.** `test_default_weights_are_genre_pure`
(`tests/test_bpm_detector_audit_regressions.py`) asserted
`w['centroid_fit'] == 0.0`; updated to `'centroid_fit' not in w`.

**Bookkeeping.** `_RECOMMENDER_VERSION` `1.0.0-rc.30 → 1.0.0-rc.31`;
`_VJ_WEIGHTS_DOC_VERSION` `87 → 88`. Full test suite green (2181 passed,
1 skipped) after landing.

## zcr_sigma Floor Was Miscalibrated (2026-09-04, same night, recommender rc.32)

**Owner, after rc.30 shipped with every `zcr_sigma` landing on the same
`0.03` floor:** "let's fix the one last problem with that zcr... figure
out how to make it useful... that seems like slim but *distinct*
margins, no?"

**Root cause.** The `0.03` floor was copy-pasted from `vocal_hnr_sigma`/
`vocal_fmr_sigma`'s own floor (a reasonable value for a `[0,1]`-scale
feature) without checking it against `zcr`'s own scale — `zcr`'s entire
genre-to-genre range across this roster is only `~0.03–0.09`, so `0.03`
is over half the whole span. It swallowed every profile's real
MAD-derived sigma (`0.0116`–`0.0217`, all real signal, none of it sample
noise) and flattened all 12 profiles to the same number.

**Fix.** Floor dropped to `0.008` (below the smallest real value measured
across the roster), so it doesn't bind for any of the 12 profiles right
now — still there as a safety net for a future profile with a much
thinner or noisier sample. Full table and methodology in
`drop-ins/auto-vj-01/docs/weights-and-thresholds.md` § "zcr_sigma Floor
Was Miscalibrated".

**The honest finding, checked rather than assumed.** Owner's framing
("slim but distinct") was exactly right: even with real sigma restored,
most ADJACENT-ranked profiles by `zcr_mu` sit within about 1 sigma of
each other (real sigmas run `0.0116`–`0.0217`, 3–10x bigger than most
adjacent gaps in the ranked list) — `zcr_fit`'s real discriminating power
lives at the tails of the roster (`chillstep`/`deep_house`/`hyphy`/
`ambient` cluster low; `trance`/`drum_and_bass`/`dubstep`/`house` cluster
high), not between most individual pairs. Fixing the floor makes the term
correctly CALIBRATED, not a suddenly-strong discriminator — that
distinction was worth stating plainly rather than letting "make it
useful" read as a bigger claim than the fix actually supports.

**Regression fallout.** Two `test_genre_matcher.py` fixtures
(`test_matcher_flips_fold_when_genre_flips`,
`test_legacy_prior_push_behind_the_rollback_flag`) needed their hardcoded
`zcr` inputs re-swept — real per-profile sigma changed which of
`rap_rnb`/`drum_and_bass` the log-normalizer's tightness bonus favors at
a given input value.

**Bookkeeping.** `_RECOMMENDER_VERSION` `1.0.0-rc.31 → 1.0.0-rc.32`;
`_VJ_WEIGHTS_DOC_VERSION` `88 → 89`. Full test suite green (2181 passed,
1 skipped) after landing.

## zcr_sigma / onset_density_sigma: Fit-vs-Live Scale Mismatch (2026-09-04, tuning session, recommender rc.33)

**Context.** Owner: "ok, now it's tuning time" -- a baseline tuning round
of six fresh `session_replay.py` accelerated-replay sessions, one real
training list per genre (ambient/house/peak-time/tech-house/deep-house/
drum-and-bass), each with its own random seed, crossfade + shuffle on,
`log_decisions=true` for full corpus capture. This was the first real
validation of the whole night's evidence-based recommender work against
fresh, unbiased data -- and it surfaced a genuine, severe defect the
earlier fixes hadn't caught.

**The finding.** `genre_report.py` against the six fresh buckets showed
`peak_time` (the `big-room-01` list's own correct profile) scoring dead
last -- rank 11 of 11 enabled candidates -- on the full weighted
composite against its OWN list, and never once recommended correctly
across a full ~1h session (`correct_reco_pct = 0.0%`). `drum_and_bass`
(6.6% correct) and `deep_house` (8.6% correct) weren't much better.
`house` (19.3%) and `ambient` (38.6%, the best of the six) were
mediocre-to-okay. Every list's *actual* top recommendation was some
other, unrelated profile -- `hyphy` won `house` and `big-room-01`
outright; `ambient` won `deep-house-01`; `house` won `drum-and-bass-01`.

**First hypothesis, tested and disproved.** `spectral_shape_fit` looked
like the obvious suspect (`ambient` topped it on every single list
regardless of genre, the same "one profile sweeps everything via the
ribbon fit" pattern already seen three times this session with
`dubstep`/`house`/`techno`). Tested directly against the real corpus data
-- rescoring every candidate's weighted composite with `spectral_shape_
fit`'s weight halved, then zeroed, using the actual `term_values_by_
candidate` already logged in the six fresh buckets (no new sessions
needed for this check). Result: **`peak_time` stayed dead last (11/11)
at every weight, including zero.** Halving/zeroing also visibly hurt
`ambient`'s already-best performance without fixing anything else.
Correctly abandoned as the driver -- this is the same "verify before
applying" discipline as the rest of the night, and it caught a plausible
but wrong fix before it landed.

**Root cause, found by checking what the term actually compares.**
`zcr_fit`/`onset_fit` compare against `mean_zcr`/`onset_density` --
values the recommender computes **fresh each evaluation cycle** (a
rolling window of live samples, see `_update_profile_recommendation()`).
But both fields' sigmas (`zcr_sigma` from rc.32, `onset_density_sigma`
from the original evidence pass) were fit using the session's own
established per-track-then-robust-stat methodology: collapse to one
MEDIAN value per TRACK first, then take MAD across those per-track
points. That's the right approach for `mu` (stops one noisy track
skewing the genre estimate) but it strips out exactly the cycle-to-cycle
variation the live scorer actually sees every time it runs -- leaving
sigma calibrated for a much smoother signal than what it's compared
against. Measured directly: `peak_time`'s fresh session showed live
`onset_density` reading with a standard deviation of `0.77` against a
stored sigma of `0.19` -- 4x tighter than reality, meaning almost any
real reading looked like a multi-sigma outlier and paid a severe
Gaussian penalty regardless of whether the genre match was actually
correct.

**Confirmed roster-wide**, not just on `peak_time`: pooled raw
per-cycle `mean_zcr`/`onset_density` values across all packaged buckets
in `assets/training/accelerated/` for the 12 real-corpus profiles
(5460-34254 rows each -- a large, solid sample):

| Profile | zcr raw stdev | rc.32 zcr_sigma | onset_density raw stdev | old onset_density_sigma |
| --- | --- | --- | --- | --- |
| house | 0.0287 | 0.0168 | 0.7521 | 0.4596 |
| deep_house | 0.0213 | 0.0193 | 0.9913 | 0.4225 |
| tech_house *(disabled)* | 0.0225 | 0.0116 | 0.7619 | 0.5486 |
| peak_time | 0.0343 | 0.0148 | 0.7200 | 0.1927 |
| techno *(disabled)* | 0.0265 | 0.0159 | 0.8668 | 0.9266 |
| trance | 0.0271 | 0.0202 | 1.0831 | 0.3855 |
| drum_and_bass | 0.0325 | 0.0164 | 0.8742 | 0.3262 |
| dubstep | 0.0220 | 0.0217 | 0.6293 | 0.1779 |
| rap_rnb | 0.0248 | 0.0200 | 0.6532 | 0.3706 |
| hyphy | 0.0251 | 0.0209 | 0.6244 | 0.2669 |
| ambient | 0.0184 | 0.0152 | 0.6706 | 0.4151 |
| chillstep | 0.0189 | 0.0188 | 0.5917 | 0.4151 |

`zcr`'s gap is real but moderate (raw stdev ~1.5-2x the per-track
value) -- consistent with `zcr` being a fairly stable, slowly-varying
texture measure. `onset_density`'s gap is severe (raw stdev 3-6x the
per-track value for every profile except `techno`, whose per-track
spread happened to already be unusually wide) -- consistent with onset
density being a genuinely bursty, moment-to-moment signal that a
per-track median smooths away almost entirely.

**Fix.** `zcr_sigma` and `onset_density_sigma` recomputed directly from
the pooled raw per-cycle values above (not re-collapsed to per-track
points). `mu` values for both fields are UNCHANGED -- the per-track
median center was correct all along; only the width was wrong. See
`drop-ins/auto-vj-01/docs/weights-and-thresholds.md` § "zcr_sigma /
onset_density_sigma: Fit-vs-Live Scale Mismatch" for the corrected
per-profile table (not duplicated here) and the post-fix composite-rank
comparison against the same six fresh sessions.

**Regression fallout, understood not blindly re-pinned.** Same two
`test_genre_matcher.py` fixtures re-swept a third time (real sigma moved
substantially -- `zcr` literal `0.07 → 0.15`). The trust-margin fixture
(`_make_trust_test_stub`) needed more than its usual `onset_count` retune
this time: with `onset_density_sigma` widened 3-6x, no `onset_count`
value (swept `-1` to `30`) could restore `house` as the winner at the
exact bpm midpoint between `house`/`deep_house` any more -- `deep_house`
won outright everywhere, `score_margin` pinned at `0.0` (a genuine
near-tie among 3+ candidates). Added a second knob: `bpm` is now biased
35% of the way from `house`'s own `bpm_prior_mu` toward `deep_house`'s
(still a realistic "ambiguous, between the two" reading, not
cherry-picked), swept together with `onset_count` this time rather than
one knob alone, landed on a confirmed-stable `bpm_frac=0.35,
onset_count=2.00` pocket. The exact 50/50 midpoint reliably favoring
`deep_house` now is the CORRECT reading of that contest post-fix, not a
bug to chase back to `house`.

**Bookkeeping.** `_RECOMMENDER_VERSION` `1.0.0-rc.32 → 1.0.0-rc.33`;
`_VJ_WEIGHTS_DOC_VERSION` `89 → 90`. Full test suite green (2183 passed,
1 skipped) after landing. Validation round (fresh seeds, same six lists)
queued next to confirm the fix actually moves `correct_reco_pct`/
composite rank in the right direction before the owner's final,
no-further-tuning favorites validation pass.

**Owner update after the validation round's mixed result:** "i am not
satisfied with that lol... you need to go further, our first class
citizens are losing badly!" — the rc.33 fix genuinely helped
`drum_and_bass`/`peak_time`/`ambient` but left `house`/`deep_house`
roughly flat, and `hyphy` still dominated every list including
`favorites`. The disproved-hypothesis writeup above (zeroing
`spectral_shape_fit`'s weight didn't fix `peak_time`) was correct as far
as it went — the ribbon term wasn't the *sole* cause of `peak_time`
scoring dead last — but continuing to dig found it WAS a real, separate,
still-unfixed bug of the exact same class. See the next entry.

## spectral_shape_fit: Per-Track vs. Live 16s-Window Aggregation Mismatch (2026-09-04, tuning session continued, recommender rc.34)

**Root cause.** `spectral_shape_fit` compares the profile's `expected_bands`/
`expected_bands_sigma` against `band_mean_vec` — a live rolling-window
mean over `self._profile_auto_reco_window_s` (default **16.0 seconds**).
But the ribbon redesign (rc.28) fit both statistics by averaging each
TRACK's bands to one point first (3-8 minutes of audio collapsed to a
single vector), then taking median/MAD ACROSS those per-track points.
Averaging over a whole track smooths away exactly the section-to-section
variation (intro/build/drop/breakdown) a 16-second window still shows in
full — the same class of fit-vs-live aggregation mismatch as the
`zcr_sigma`/`onset_density_sigma` fix immediately above, one level up
the pipeline. This is what the earlier "disproved hypothesis" entry
caught a symptom of without finding the actual mechanism: zeroing the
term's weight couldn't fix `peak_time` because the DATA feeding the term
was fit at the wrong time-scale, not because the term itself was
irrelevant.

**Verified before touching anything live**, using the real corpus
already on disk (`assets/training/accelerated/`): rebuilt ~16-second
non-overlapping window chunks per track (matching the live window
exactly), refit `mu`/`sigma` from those chunks, then rescored each
profile's own held-out windows against every candidate's OLD vs NEW
fit:

| Profile | OLD own-list rank (of 12) | NEW own-list rank (of 12) |
| --- | --- | --- |
| `house` | 7 | **1** |
| `deep_house` | 10 | 3 |
| `peak_time` | 12 (dead last) | 4 |
| `drum_and_bass` | 6 | 3 |
| `tech_house` *(disabled)* | 8 | **1** |
| `ambient` | 1 | 1 *(unchanged — already correct, not regressed)* |

**Fix.** Both `expected_bands` (mu) and `expected_bands_sigma` (sigma)
recomputed together — unlike the `zcr`/`onset_density` fix, which only
needed sigma corrected, here the aggregation UNIT itself changed
(per-track → per-16s-window), so both statistics needed refitting from
the same set of windows for internal consistency. Method: group each
profile's own training-list heartbeat rows by track, accumulate
non-overlapping ~16s chunks in track-order, mean the 64-band vector
within each chunk, then robust median (→ `mu`) / MAD-derived sigma
(→ `sigma`, floored at `0.01`) pooled across ALL chunks from ALL tracks
(not one point per track — many chunks per track now, since a chunk is
~16s not a whole track). `electronic` mirrors `house`'s new values, same
control-pair design as every other ribbon field. Applied to the same 12
real-corpus profiles (+ `electronic`) as every other evidence-based fix
this session.

**Regression check.** Full test suite green (2183 passed, 1 skipped)
with **zero fixture retuning needed** — unlike the `zcr`/`onset_density`
fix, no test hardcodes a literal against these specific 64-element
arrays or reads them live into a fixture the way `_make_trust_test_stub`
does for `bpm_prior_mu`/`zcr_mu`.

**Live validation queued.** Three fresh single-list `session_replay.py`
runs (`house`/`peak_time`/`drum_and_bass`, new seeds, crossfade+shuffle)
launched immediately after landing to confirm the offline recomputation
predicts real session behavior, per the same "verify before declaring
victory" discipline as every other fix tonight.

**Bookkeeping.** `_RECOMMENDER_VERSION` `1.0.0-rc.33 → 1.0.0-rc.34`;
`_VJ_WEIGHTS_DOC_VERSION` `90 → 91`.

## Why house/peak-time/drum-and-bass Still Read as "Competitive" — Tempo Is Completely Off (2026-09-04, tuning session continued)

**Owner, after the ribbon fix's validated wins:** house/peak-time/
drum-and-bass being "competitive" with each other is itself suspicious
given how acoustically different they are — a huge BPM gap (drum & bass
sits at ~166-174 vs. house-family's ~122-130) and a stark density
contrast ("DNB is like bass & kicks and that's it... house has a TON of
other stuff going on"). Asked what the mechanism might be.

**Finding 1: tempo is entirely excluded from genre scoring, by design.**
`tempo_fit`/`top_cand_fit` have both been weight `0.0` since the
2026-08-20 "genre-pure composite" decision — BPM plays zero role in
which profile the recommender picks right now.

**Finding 2: turning it back on doesn't help — it hurts, measured
directly against real data.** Rescored the real corpus with `tempo_fit`
swept `0.1`/`0.25`/`0.5`/`0.75`/`2.2` (the old pre-genre-pure weight): no
value is a clean win. `peak_time` climbs cleanly and monotonically
(21.8% → 37.7% correct) because its real tempo band is narrow and
accurately detected — but that gain comes directly out of `house`, which
loses its own-list win starting at just `0.25` (house/peak-time's real
BPMs sit only ~3.5 BPM apart, the already-documented house-family
cluster). `drum_and_bass` gets monotonically WORSE at every value tested,
including the smallest (`0.1`) — its BPM *input* is wrong, so any weight
on it is weight on a wrong number; the wrongness doesn't improve with a
smaller weight, only its influence does.

**Finding 3: the detector isn't reading drum & bass's real tempo.**
Detected `bpm` across all three DNB sessions run tonight (different
seeds): median 115.1–115.6, every time — `174 / 115.6 ≈ 1.5`, a
consistent **3:2 tactus fold**, not noise. Traced it to a genuine,
well-isolated mechanism: `_estimate_tempo_acf()`'s "tactus descent loop"
(the v2/base `BeatTracker`'s tempo-candidate selection) only ever tests
DOWNWARD fold factors (`0.5, 2/3, 0.75`) — no upward equivalent. Watched
it happen live in the raw corpus: first track of a fresh DNB session,
correct profile/prior already active, `176.47` scoring clearly highest
in the raw ACF (`0.181` vs. `0.135`) — and the tracker still folded down
to the second-place `88.24`. Once folded, nothing climbs back up, even
when the correct tempo keeps re-scoring competitively in later cycles
(directly observed: `166.67` scoring highest of three listed candidates
on a row where the locked `bpm` still read ~84).

**Finding 4, the correction that mattered: v3 (the actually-live engine,
`beat_tracker_engine="v3"`) does NOT simply inherit v2's bug the way it
first looked.** `BeatTrackerV3.update()` calls `super().update()` — but
the raw comb-filter observation is snapshotted BEFORE v2's decision
layer (genre evidence, prior-weighting, the biased tactus descent) ever
runs: "The comb score IS the observation; everything after this line is
v2's decision layer, which v3 replaces wholesale" (the code's own
comment). So v3 builds its own HMM posterior from unbiased raw evidence,
not from v2's folded pick — the wrong-fold behavior in the LIVE `bpm`
field is v3's OWN posterior decision, not an inherited v2 bug. Owner: "i
can't believe i let the v2 wrap slide by! i should have anticipated that
based on the way the last v3 was done" — the more careful trace showed
the anticipated coupling isn't actually there at the code level; v3 has
its own, independent problem in the same neighborhood.

**Two real gaps found in v3's own decision path, both real design gaps
rather than a copy of v2's bug:**

1. v3 already has machinery built specifically to fix octave-fold
   asymmetry — but it's DEAD in production. `_V3_FOLD_OBS_WEIGHT` (the
   weight on a symmetric up/down comb-evidence boost) defaults to `0.0`,
   AND the code implementing it lives in the `'comb'`/`'score'`
   observation-source branch of `_v3_observation_likelihood()`, while the
   live config uses `_V3_OBS_SOURCE='template'` — a different branch
   entirely, with no fold-symmetric treatment of any kind. The
   `'hybrid'` mode (magnitude-weighted template matching, the template
   system's own attempt at resolving this) was tried and found worse
   overall ("tested worse, kept for experiments" — pre-existing code
   comment), so it isn't a safe drop-in fix either. **Not touched
   tonight** — redesigning the live template path's fold-handling is a
   bigger, more careful task than "a few sims," correctly identified as
   out of scope for tonight.
2. v3's own transition matrix already treats 1.5x/4:3 (triplet) fold
   jumps SYMMETRICALLY (`_V3_FOLD_PROB_TRIPLET`, "symmetric: up AND down
   get identical mass" — the code's own comment, matching v2's bug
   directly in its own docstring: "the asymmetric fold-DOWN-only descent
   was v2's measured dnb failure"). v3 also already computes
   `_v3_fold_suspect_mass` every cycle — how much posterior mass sits on
   a fold-related lane of its own top pick — but as PURE TELEMETRY,
   never acted on and never logged to the corpus.

## v3 Genre-Evidence Consultation + Fold-Suspect Gate (2026-09-04, tuning session, detector rc.42)

**Owner's fix, sent for implementation:** "shouldn't v3 be consulting
the genre data when confidence is low? maybe we could extend that for
'fold ratio is feeling suspect'?"

**What was found before touching anything.** The genre-evidence channel
(`set_genre_tempo_evidence()`, the recommender's tempo-independent
evidence pushed every cycle, gated on `acf_confidence < 0.5`) lives
*entirely* inside `_estimate_tempo_acf()` — v2's decision layer, which
v3 discards wholesale per Finding 4 above. Confirmed by grep: v3 never
reads `_genre_evidence_mu`/`_genre_evidence_sigma`/`_genre_evidence_weight`
anywhere in its own posterior update. Since v3 became the live engine,
this entire channel has been dead weight in production — the recommender
keeps pushing real evidence every cycle and it goes nowhere.

**Fix.** New method `_v3_apply_genre_evidence()`, wired into both
branches of `_v3_observation_likelihood()` (so it applies regardless of
`_V3_OBS_SOURCE`, including the live `'template'` default). Same
multiplicative-Gaussian-boost math as v2's own gate, applied over
`self._v3_log_bpms`. Gated on EITHER of two conditions (extending, not
replacing, v2's existing one):

- `self._acf_confidence < self._genre_evidence_gate_confidence` (v2's
  original condition — reused because v2's confidence is still computed
  by the shared pipeline v3 calls via `super().update()`), OR
- `self._v3_fold_suspect_mass > _V3_FOLD_SUSPECT_GATE_MASS` (new — the
  owner's extension). `fold_suspect_mass` measures something raw
  confidence doesn't: how much posterior mass sits specifically on a
  fold-ALTERNATIVE of the current pick, not just how peaked the posterior
  is overall. That's exactly DNB's failure mode — the MAP pick can look
  locally confident while a real, substantial fold-alternative sits
  right next to it in tempo-ratio space.

`_V3_FOLD_SUSPECT_GATE_MASS = 0.2` — a first-pass value, not yet fit
from real data, because `fold_suspect_mass` had ZERO corpus logging
before this same commit (it was pure telemetry, never written to a row).
Wired into `_detector_snapshot()` (`v3_fold_suspect_mass`, plus
`genre_evidence_applied_count` for direct before/after comparison) so
real sessions from tonight onward can calibrate this properly, the same
"every scrap of data captured" discipline as the rest of the night.

**Regression check.** Full test suite green (2183 passed, 1 skipped)
before landing. Live validation (a fresh drum-and-bass session, new seed)
launched immediately after to check: does `genre_evidence_applied_count`
actually engage, does `v3_fold_suspect_mass` read in a sane range, and —
the real test — does detected `bpm` move toward the true 166-174 band.

**Explicitly deferred, not attempted tonight (owner: "let's not get to
extreme unless we sniff out a lead"):** redesigning the live
`'template'`/`'hybrid'` observation path's fold-handling (Finding 4's gap
#1 above) — the acknowledged octave-ambiguity weak spot in the shipped
default. A real, separate, bigger investigation.

**Bookkeeping.** `_DETECTOR_VERSION` `1.0.0-rc.41 → 1.0.0-rc.42`;
`_VJ_WEIGHTS_DOC_VERSION` `91 → 92`. New tunable
`_V3_FOLD_SUSPECT_GATE_MASS` added to `_DETECTOR_CONSTANT_DEFAULTS`
(`drop-ins/training-kit-01/tools/package_training_set.py`) same-commit
per the standing sync rule.

**Live validation came back inconclusive, reported honestly rather than
declared a win:** `genre_evidence_applied_count` did climb (confirming
the wiring genuinely engages), but detected `bpm` on a fresh drum & bass
session barely moved (median 116.3 vs. 115.1–115.6 before). Two real
problems found, not one: (1) `current_profile_key` was `house` more
often than `drum_and_bass` across the session (145 vs. 94 rows) — genre
evidence is pushed based on whichever profile is *currently* active, so
for a large fraction of the session the "genre evidence" reaching the
detector was centered on `house`'s tempo (~122), actively reinforcing
the fold instead of correcting it — the exact circular dependency
(wrong BPM → recommender won't confidently pick `drum_and_bass` → wrong
genre evidence gets pushed → BPM stays wrong) flagged as a hypothesis
earlier the same session, now confirmed live. (2) `v3_fold_suspect_mass`
read exactly `0.0` on all 421 rows of that session — never once
nonzero — meaning the owner's specific fold-suspect-gate idea never
actually fired; all the measured engagement came through the
pre-existing `acf_confidence` condition alone. Root cause of (2) not
found — genuine HMM-internals debugging, correctly identified as past
the "sniff out a lead, don't get extreme" line the owner drew, and left
open rather than guessed at.

## Duplicate, Not Share: BeatTrackerV3 Stops Inheriting From BeatTracker (2026-09-04, tuning session, detector rc.43)

**Owner's call, after the inconclusive validation above:** "let's take
the 'duplicate v2 code' route, because that is the *proper* solution and
drifting apart from v2 *should* occur because otherwise mod'ing what's
under the v2 hood would mean that v2 is a never-ending version that
can't ever just be flipped back 'stable working v2'! do that now and fix
the super thing and make sure it's allowed to fold up if it's getting
real evidence that it should from somewhere."

**The reasoning, made explicit for whoever reads this later:** a
shared-component extraction (the OTHER option on the table, from the
earlier "what will it take to separate v2 from v3" discussion) ties any
future v3-specific tuning to v2's own behavior — exactly what v2's
"byte-identical protected baseline" rule exists to prevent. Duplication
costs real, ongoing maintenance (two copies of ~3,000 lines of onset/
envelope/phase/comb-filter machinery that will keep drifting further
apart as each gets its own independent tuning) — but that drift is the
explicit, correct trade: v2 stays a permanent, unchanging reference
point that can always be "flipped back to," and v3 is genuinely free to
diverge, rather than v2 quietly becoming version-locked to whatever v3
currently needs.

**What landed.** New class `_BeatTrackerV3Base` (`beat_grid.py`, ~3,045
lines) — a full duplicate of `BeatTracker` (v2)'s class body, byte-for-
byte identical at the moment of duplication (confirmed: only the class
definition line itself needed renaming; the handful of other literal
`BeatTracker` occurrences in that text are all comments/docstrings, no
functional self-references, no other class inherits from it, nothing
constructs it recursively). `BeatTrackerV3` now subclasses
`_BeatTrackerV3Base` instead of `BeatTracker` directly — "fix the super
thing": `super().update()` inside `BeatTrackerV3.update()` now calls the
DUPLICATE's pipeline, so v2 (`BeatTracker`) is never touched or executed
by a v3 session at all anymore, and is free to stay genuinely
byte-identical regardless of what happens to v3's copy from here.
Module-level constants (`_V2_*`, `_TACTUS_*`, etc.) stay shared between
the two classes for now — deliberately not preemptively duplicated
alongside the class bodies, since most represent genuinely shared
physical/DSP constants rather than v2-specific decision logic; a
constant gets its own v3-private copy the moment a real need to diverge
shows up (the tactus fold-up fix below didn't need to touch any of
them).

**"make sure it's allowed to fold up":** within `_BeatTrackerV3Base`
ONLY (v2's own copy of the same method, unchanged, still descent-only),
`_estimate_tempo_acf()`'s tactus descent loop gains a symmetric ascent
loop, added strictly AFTER the existing descent loop so descent keeps
first priority (no behavior change for any genre whose real tempo sits
at or below the raw ACF pick — only adds a path for genres whose real
tempo sits above it, drum & bass being the motivating case). Reuses
`_tactus_fold_accepted()` completely unchanged — the identical score
and region-consistency bar a descent candidate must already clear — so
this cannot manufacture evidence that wasn't there; it only removes a
direction the loop was previously structurally forbidden from
considering at all. Ascent factors `(2.0, 1.5, 4/3)`, same priority
ordering as the descent factors they mirror, bounded by `self._bpm_max`
(200.0) instead of `self._bpm_min`.

**File organization, explicitly deferred:** owner, mid-implementation,
correctly flagged that duplicating another ~3,000 lines into an already
~4,800-line file compounds an existing monolithic-file problem — but
also explicitly said the actual file-split ("abstracting these systems
into their own files") is its own, larger, already-anticipated piece of
work ("the whole project's grand v2 plan starts precisely with that
issue"), not something to bundle into tonight's fix. `_BeatTrackerV3Base`
therefore still lives in `beat_grid.py` for now — see
`docs/planning/post-soak-reminders-2026-09-04.md` item 6 for the
deferred split.

**Regression check.** Three pre-existing tests asserted the OLD
inheritance relationship directly and needed updating as a real,
understood consequence of this change (not blind re-pinning):
`tests/test_auto_vj_shadow_engine.py::test_load_beat_grid_cls_v2_stays_the_protected_baseline`
(MRO assertion), `tests/test_beat_tracker_v3.py::test_v3_is_a_v2_subclass_with_its_own_engine_version`
(renamed to `test_v3_no_longer_subclasses_v2_directly`, assertion
inverted), `tests/test_drop_trigger_sustain_split.py::test_band_blend_weights_reverted_in_both_engines`
(source-level occurrence count `2 → 3`, since the pinned band-blend line
now appears in v1, v2, AND `_BeatTrackerV3Base`'s copy of v2). Full test
suite green (2183 passed, 1 skipped) after landing. Live validation (a
fresh drum & bass session plus a house regression check, run in
parallel) queued next.

**Bookkeeping.** `_DETECTOR_VERSION` `1.0.0-rc.42 → 1.0.0-rc.43`;
`_VJ_WEIGHTS_DOC_VERSION` `92 → 93`.

**Follow-up (same night): duplicated module constants cleaned up.**
While investigating a separate owner question about v3's tempo lattice,
found that the class-duplication script above had accidentally swept a
124-line block of `_V3_*` module-level constants (the block that sits
between v2's class and `class BeatTrackerV3`) into the region ahead of
`_BeatTrackerV3Base` too — a byte-for-byte duplicate, confirmed via
`diff`. Harmless in effect (Python re-executes the assignments; the
second, correctly-positioned copy right before `class BeatTrackerV3`
always won as the live binding), but genuine clutter, not a scoping
break — confirmed via direct class introspection that `_BeatTrackerV3Base`
still has all 91 expected non-dunder attributes either way. Removed the
stray first copy. Module still parses; the three most relevant test
files (89 tests) still pass.

### hyphy's `bpm_prior_mu`/`sigma`/`hint` recalibration reverted — unapproved (2026-09-04, recommender rc.35)

**What happened.** The "Vocal-Term Sigma + Evidence-Based Re-Fit
(recommender rc.29)" landing (same day, earlier) fully recalibrated
`hyphy`'s tempo fields from pooled raw *detected* BPM on
`training-trap-hip-hop-01` (`bpm_prior_mu` `109.0 → 142.2`,
`bpm_prior_sigma` `0.15 → 0.1334`, `bpm_hint_min`/`max`
`100.0–118.0 → 127.0–155.0`) in the same commit (`6799bfc`) that split
`hyphy`/`trap` back out of the pooled `rap_rnb` profile. That doc's own
text flagged, at the time, that hyphy's field comment carries "the same
'produced vs. perceived pulse' fold-risk pattern as dubstep" — and
applied the change anyway ("small... which is why it was applied, not
because the fold risk was ruled out"), while `dubstep` and `rap_rnb`
were correctly held back in the exact same pass for the identical
reason. Inconsistent, and wrong: pooling raw per-track detected BPM as
if it were ground-truth produced tempo is precisely the kind of
detector-fold-contamination risk this whole session repeatedly found to
be unsafe for genres with known octave/tactus ambiguity — trap is
exactly such a genre (commonly produced around a much faster tempo than
its perceived half-time pulse, the same pattern documented for dubstep).

**Owner correction.** "is hyphy/trap BPM range seriously set 127-155??!
that's insane. i spent FOREVER tuning that table by hand and someone
made unapproved changes.. consolidating those was approved by not that
bpm range! the bpm range for those should be what hyphy was before."
The hyphy/trap split itself (the profile-pooling change, "trap should
def be on its own") was and remains approved — only the tempo-field
recalibration riding along in the same commit was not, and should never
have shipped without separate, explicit sign-off, per the standing rule
that detector/recommender constant changes need owner review before
landing (doubly so here, since the doc entry landing it had already
flagged the exact risk that made `dubstep`/`rap_rnb` get held back).

**Fix.** Reverted `unicornviz/audio/profiles.py`'s `hyphy` entry —
`bpm_prior_mu`/`bpm_prior_sigma`/`bpm_hint_min`/`bpm_hint_max` and the
`description` string — to the values from the pre-split 2026-08-10
disable commit (`2eab76b`): `109.0`/`0.15`/`100.0`/`118.0`. Confirmed via
`git show 2eab76b^:unicornviz/audio/profiles.py` these are the owner's
own hand-tuned, hand-dialed values, not a placeholder guess.
`tests/test_audio_profile_deep_house_and_disable.py::test_hyphy_reenabled_and_recalibrated_from_trap_hip_hop_01`
updated to assert the restored values (was asserting the now-reverted
ones). All other rc.28/rc.29 hyphy changes from the same landing
(`expected_bands`/`expected_bands_sigma` ribbon, `vocal_hnr`/`vocal_fmr`
mu/sigma) are unaffected — those are real per-track fingerprint/vocal
fits, not tempo, and were not part of what the owner flagged.

**Bookkeeping.** `_RECOMMENDER_VERSION` `1.0.0-rc.34 → 1.0.0-rc.35`;
`_VJ_WEIGHTS_DOC_VERSION` `93 → 94`.

### v3 Fold-Up Fix, Take Two: the Observation Layer, Not the Discarded Decision Layer (2026-09-04, detector rc.44)

**Take one, and why it didn't work.** The "Duplicate, Not Share" entry
above added a symmetric tactus-ascent loop to `_BeatTrackerV3Base`'s own
copy of `_estimate_tempo_acf()`, believing it would give v3 the same
fold-up capability. Live validation (a fresh drum & bass session)
disproved this: BPM output didn't move, and `v3_fold_suspect_mass` read
exactly `0.0` throughout. Root cause, found by reading `BeatTrackerV3.
update()` directly: `super().update()` computes the ascent-modified
`self._bpm` via the inherited pipeline, but the very same method then
**unconditionally overwrites** `self._bpm`/`self._confidence` with its
own HMM posterior decision a few lines later, whenever `like is not
None` (nearly always true). The entire inherited computation — ascent
fix included — is computed and thrown away every cycle. Reported
transparently as a real mistake, not downplayed.

**Take two: fix the branch that's actually live.** `_v3_observation_
likelihood()` has two families: `'template'`/`'hybrid'` (the LIVE
default, `_V3_OBS_SOURCE='template'`, no config.toml override) and
`'comb'`/`'score'` (not live). The existing fold-symmetric evidence-
sharing boost (`_V3_FOLD_OBS_WEIGHT`, a symmetric up/down comb-evidence
share at the octave) only ever lived in the `'comb'`/`'score'` branch —
inert twice over: the weight itself shipped at `0.0`, AND even nonzero it
would only affect a branch v3 doesn't use. Generalized the mechanism (now
covers `1.5x`/`4:3` alongside `2.0x`, matching `_v3_build_transition()`'s
own symmetric fold-jump mass) and added it to the `'template'` branch —
the one that actually determines v3's answer — reusing the same
`_V3_FOLD_OBS_WEIGHT`. Activated it for the first time: `0.0 → 0.35`,
bake 1's own historically-tried value for this exact mechanism, a
reasoned starting point rather than a fresh guess. The `'comb'`/`'score'`
branch's version was kept in sync (same three ratios) on principle, even
though it stays inert while `_V3_OBS_SOURCE='template'` is shipped.

**Not yet independently validated** — this needs its own live session
(drum & bass, fresh seed) before being trusted, since take one already
demonstrated that "looks right" and "actually changes the output" are
different claims here. `_DETECTOR_VERSION` `1.0.0-rc.43 → 1.0.0-rc.44`.
Regression test `tests/test_beat_tracker_v3.py::test_defaults_sit_in_the_
escape_time_regime` updated to assert the new `0.35` default (was
pinning the old, inert `0.0`).

### v3 Decisive-Rival Fast Path (2026-09-04, detector rc.44)

**Trigger.** Owner: "our 'alt bpm conf is X% higher than current locked
so switch immediately' gate doesn't seem to be working anymore...
probably for at least a few days." Investigation found the same root
cause as the take-one mistake above: every plausible candidate
mechanism (the Schmidt trigger `_BPM_LOCK_CONFIDENCE`/`_BPM_LOCK_
RELEASE_CONFIDENCE`, the large-jump `_V2_LARGE_JUMP_CONFIDENCE` gate)
lives in `BeatTracker`'s decision layer, discarded every cycle by
`BeatTrackerV3.update()`'s posterior overwrite — and `config.toml` has
had `beat_tracker_engine = "v3"` since 2026-09-02, two days before this
conversation, matching the owner's own "at least a few days" estimate
almost exactly.

**Owner correction, once the exact mechanism couldn't be pinned down by
name:** "none of those are what i'm talking about... there was
distinctly a 'if alt confidence is 20% higher than current switch
immediately' gate somewhere (it may have been if current is 20% less
than) but it was something like that and it was definitely part of v2
once upon a time... either way, let's bring that in now as well, we
don't need to go looking for it." Direction: stop searching for the
exact historical implementation, build the behavior fresh. Asked what
else should gate it: "it does respect the cool-down period but that's
it" — deliberately no persistence window, no region-consistency check,
just a cooldown.

**Why it can't be a straight port.** v3's own MAP-tracking has no
hold/lock concept to escape *from* in the first place — `self._bpm`
already just *is* the MAP state every cycle, unconditionally (confirmed
reading `BeatTrackerV3.update()` directly). v2's version was an escape
hatch out of an otherwise-conservative multi-cycle persistence system;
v3 has no such system to escape from, so the mechanism had to be
rebuilt in v3's own terms rather than translated line-for-line.

**Design.** After each cycle's normal Bayesian posterior update
(`BeatTrackerV3.update()`, right after computing the MAP index/`bpm`/
`confidence` as usual): find the single highest-mass lattice bin
*outside* the MAP's own confidence band (posterior mass within
`±_V3_CONF_BAND`, the same window `confidence` is already computed
from), measure that rival's own confidence the same way, and if it
exceeds the MAP's by `_V3_ALT_CONF_MARGIN` (`0.20` — the owner's own
recalled number, `rival >= map * 1.20`) *and* the cooldown
(`_V3_ALT_SWITCH_COOLDOWN_BARS`, `16` musical bars) has elapsed since the
last snap, concentrate the posterior at the
rival immediately (a Gaussian reseed at the rival's lattice index,
`_v3_drift_sigma`-width, mirroring `prime_tempo()`'s own posterior-seed
pattern) rather than let the transition matrix's slow drift/fold-mass
diffusion get there over many cycles. No other gate, per the owner's
own framing. New engagement counter `_v3_alt_switch_count`, corpus-
logged as `v3_alt_switch_count` (0 on v1/v2, same convention as the
other v3-only counters).

Extracted into its own method, `_v3_apply_decisive_rival()`, rather than
left inline in `update()` — a plain function of its arguments plus
`self._v3_posterior`, so it can be driven directly in a test without the
full audio/onset `update()` pipeline. New regression test
`tests/test_beat_tracker_v3.py::test_decisive_rival_snaps_the_posterior_with_cooldown`
covers all three behaviors: a genuinely dominant rival (wider, slightly
lower-peaked, but more band-mass than the sharp current pick) triggers an
immediate snap; a second decisive rival arriving in the same instant is
blocked by the cooldown; the same rival fires once the cooldown has
elapsed.

**Cooldown is bar-based, not time-based.** First drafted as a flat
`2.0` s. Owner: "cool down should be 16 bars maybe, or 6s to start....
bars maybe better?" Bars won: a fixed seconds value covers wildly
different bar counts across the lattice's own 55-210 BPM span (the
whole point of v3's fast-lanes-first-class design), while a bar count is
a consistent *musical* duration regardless of tempo — matching how
every other dwell/hold window in this codebase (`_V2_DWELL_BARS`,
`bpm_lock_dwell_bars`) is already bar-based. Counted from
`self._beat_index` (real detected beat crossings, assumed 4/4) rather
than `self._bars_since_lock` — that counter only increments while
`_lock_anchor_bpm > 0.0`, a v2-decision-layer-only concept v3 never
populates, so it would silently never advance under v3. Renamed
`_V3_ALT_SWITCH_COOLDOWN_S` → `_V3_ALT_SWITCH_COOLDOWN_BARS`, value
`2.0` → `16.0`; the test's cooldown-elapsed step now advances
`t._beat_index` directly instead of `t._last_t`.

**Both constants are first-pass values**, not fit from real session
data — `_V3_ALT_CONF_MARGIN` is the owner's own recollected number
directly; `_V3_ALT_SWITCH_COOLDOWN_BARS` is the owner's own suggested
starting point. Revisit once `v3_alt_switch_count` engagement data
exists across real sessions.

**Bookkeeping.** `_DETECTOR_VERSION` `1.0.0-rc.43 → 1.0.0-rc.44` (shared
with the fold-up take-two entry above, landed in the same commit), then
`→ 1.0.0-rc.45` for the seconds-to-bars cooldown correction above (same
session, before rc.44 was ever committed or validated live);
`_VJ_WEIGHTS_DOC_VERSION` `94 → 95 → 96`.

### BPM Hard Pre-Filter No Longer Requires a Lock (2026-09-04, recommender rc.36)

**Trigger.** Owner: "the chosen genre MUST be within the bpm range
(plus it's little wiggle room) right? right! that's supposed to be
happening but maybe we were waiting till the detector work was dialed?
it's dialed now, we need to institute that immediately."

**What already existed, confirmed by reading the code, not assumed.**
The 2026-08-20 BPM hard pre-filter (rc.20, see its own entry above) is a
real eligibility gate: a candidate profile whose `bpm_hint_min/max ±
profile_reco_bpm_prefilter_margin` (`0.10`) doesn't contain the current
BPM is excluded before `_profile_score()` ever runs, with an
all-excluded fallback so a fold-error lock can't silence the
recommender entirely. This is exactly the "chosen genre MUST be within
range" guarantee the owner described — but it only ever applied while
`self._bpm_lock_active` (the Schmidt-trigger hysteresis state) was
`True`. rc.20's own original design (2026-08-13 ADR, "BPM as a Hard
Recommender Pre-Filter") explicitly chose to run "unfiltered when
unlocked," on the stated plan that a not-yet-built genre/BPM candidate
matcher would cover that regime instead once it existed.

**The gap.** That matcher was built (rc.21, "the BPM/genre candidate
MATCHER's LOW half") — but reading its own code shows it does something
different from what the original plan implied: its `det_score ×
genre_conf × range_fit` joint selection only decides what tempo
evidence to push back through `set_genre_tempo_evidence()`, a channel
the DETECTOR consults to help its own low-confidence estimate converge.
It never touches which genre gets RECOMMENDED. So for the entire time
between rc.20 and tonight, any cycle where the detector wasn't
confidently locked ran genre recommendation on the FULL, completely
BPM-unconstrained candidate set — the exact gap the owner suspected,
confirmed rather than assumed.

**Fix.** Dropped the `bpm_lock_active` condition from the pre-filter
gate in `_update_profile_recommendation()` (`auto_vj.py`) — it now
applies whenever `self._grid` reports any nonzero BPM, locked or not.
Everything else (margin, all-excluded fallback, telemetry counters) is
unchanged. The existing all-excluded fallback already protects against
the main risk this removes protection from (a badly-wrong early-track
reading locking out every genre) — it falls back to unfiltered scoring
in that case, same as it always has under lock. What changes is a
different, already-accepted risk (a plausible-but-wrong reading
mis-excluding the true genre) now also applies pre-lock instead of only
post-lock — a reasonable trade now that this session's own fold-up fix
and decisive-rival fast path have made the detector meaningfully more
trustworthy pre-lock too.

**Regression test.** `tests/test_bpm_detector_audit_regressions.py`'s
`test_bpm_prefilter_inactive_when_unlocked` (which pinned the OLD
behavior) renamed and inverted to `test_bpm_prefilter_also_active_when_
unlocked` — same scenario as `test_bpm_prefilter_excludes_out_of_
range_when_locked`, but without setting `_bpm_lock_active` at all, now
asserting the filter still excludes the out-of-range candidate.

**Bookkeeping.** `_RECOMMENDER_VERSION` `1.0.0-rc.35 → 1.0.0-rc.36`;
`_VJ_WEIGHTS_DOC_VERSION` `96 → 97`.

### Director Timing Retune (2026-09-04, director rc.18)

**Trigger.** Right after the new `director-timing.md` reference doc was
built (a full inventory of every min/max dwell/cooldown/swap-count
constant that gates how long the director holds a mode/scene/effect),
owner reviewed the current values and supplied a full replacement set
across all four mood profiles (chill/normie/raver/tweaker), plus a
direct question: "build_min_hold_s ... is this being respected?"

**Answer, confirmed by reading the code, not assumed.** Yes — genuinely
wired, not dead. `self._build_min_hold_s` (read from `_profile_value()`)
feeds `build_min_hold` (tempo-scaled via `_timing_scale_from_bpm()`,
floored at `2.0`), which becomes `effective_build_min_hold` (further
reduced by `1.0 - self._phrase_bias('RISE')`, floored at `1.0`), which
directly gates the BUILD→DROP transition at two points:
`elapsed_build >= max(1.4, effective_build_min_hold * 0.35)` (the
fastlane path, a strong-trigger shortcut) and
`elapsed_build >= effective_build_min_hold` (the normal path, also
requiring real evidence and a downbeat-confidence floor). One honest
caveat: the *raw* config value is not a literal floor in every path —
phrase-bias can reduce it, and the fastlane path uses 35% of the
already-reduced value — so the effective minimum in practice can run
shorter than the configured number, especially during a strongly
RISE-biased phrase position. Also worth knowing: the tempo-scaling
floor (`max(2.0, ...)`) means `tweaker`'s new `build_min_hold_s=2.0`
effectively becomes a hard `2.0` at faster-than-neutral tempo (`timing_
scale` bottoms out at `0.60`, so `2.0 * 0.60 = 1.2` gets floored back up
to `2.0`) — a small, likely inconsequential clamp, not a bug, just
worth knowing the number isn't infinitely fine-grained at the fast end.

**The retune.** Full owner-supplied replacement values across all 18
constants in `director-timing.md`'s tables (mode/phrase dwell, drop
cooldown, effect/postfx switch timing, scene/preset swap counts), every
one of the four mood profiles. Values are NOT required to be monotonic
chill→tweaker (several aren't — e.g. `impact_hold_s` 10/4/8/12 dips then
rises, `climax_swap_min_s` 20/8/12/20 comes back up to tweaker) —
applied verbatim as supplied, not smoothed or second-guessed. Full
before/after table: `drop-ins/auto-vj-01/docs/director-timing.md`
(updated in the same commit). 72 individual value edits across 18 keys
× 4 profiles, applied via a small one-off script (line-targeted,
verified against the exact expected old value at each line before
writing) rather than by hand, given the volume — output diffed and
spot-checked before and after. Full test suite green; no test pinned
any of these preset values, so none needed updating.

**Owner's own forward-looking note, logged not acted on:** "my honest
read is for next version of director we change ALL these to
beats/bars/phrases!" — i.e. redefine every constant in this family in
musical units (matching how the detector's own dwell windows are
already bar-based — see `_V2_DWELL_BARS`/`bpm_lock_dwell_bars` and the
brand-new `_V3_ALT_SWITCH_COOLDOWN_BARS` a few entries above) instead of
wall-clock seconds. Explicitly framed as a future version, not requested
now — logged in `docs/planning/post-soak-reminders-2026-09-04.md` so it
isn't lost, not implemented here.

**Bookkeeping.** `_DIRECTOR_VERSION` `1.0.0-rc.17 → 1.0.0-rc.18`. This
retune sits outside `_VJ_WEIGHTS_DOC_VERSION`'s own explicit trigger
list (that counter's director bullet is scoped to `_phrase_bias()`/
`_PHRASE_ROLE_BARS`/`phrase_*` keys specifically, not general mode/scene
dwell timing) — the doc's `Director version` header line was still kept
in sync with the code (enforced by
`tests/test_drop_trigger_sustain_split.py::test_weights_doc_version_in_sync`),
just without a numbered doc-version bump or Changelog entry there.

### The New-Baseline Batch Silently Ran v2, Not v3 — session_replay.py Never Set beat_tracker_engine (2026-09-04)

**How it was found.** After landing the hyphy revert, the v3 fold-up fix
take two, the decisive-rival fast path, the BPM hard pre-filter change,
and the full director timing retune, owner asked for a fresh 16-session
baseline (one run per genre list + favorites + toughies, 4 parallel) and
a full detect/select/mood/director analysis. Three analysis agents were
dispatched against the packaged corpus. The detector agent's very first
finding: `engine_version` read `'2.0.0'` in **every single row of every
single session** — never `'3.0.0'`. Every "V3 HMM Engine Engagement"
scorecard section read exactly `0`/`0.0000` across all 16 buckets:
`v3_cycle_applied_count`, `v3_fold_jump_count`, `v3_alt_switch_count`,
`v3_fold_suspect_mass` median/max, all zero.

**Root cause.** `drop-ins/training-kit-01/tools/session_replay.py`'s
`run_session()` builds its own `cfg` dict entirely from scratch (by
design — its own docstring: "Never touches config.toml") and never set
`beat_tracker_engine` anywhere in it. `AutoVJController.__init__` reads
`self._cfg.get('beat_tracker_engine', 'v2')` — a hardcoded `'v2'`
fallback that's been silently correct-by-accident for every replay
session ever run through this tool, right up until `config.toml`'s own
live default changed to `'v3'` on 2026-09-02. From that point on, the
live app and the training/replay harness silently diverged: the live
app ran v3, every accelerated-replay session (including all of this
same session's own earlier validation runs, and tonight's whole 16-list
batch) kept running v2. Confirmed directly, not inferred: grepped
`session_replay.py` for `beat_tracker_engine`, found zero references
before this fix.

**Consequence.** The 16-session batch cannot support or refute any
verdict on tonight's detector work — none of that code path executed.
The drum_and_bass fold pattern the detector agent found (15/16 tracks
locked to a tight 113-120 BPM cluster, centered almost exactly on
`166.7 x 2/3 = 111.1`, the classic dotted/2:3 fold-down) is v2's
long-documented, pre-existing behavior, not a fresh read on whether the
fold-up fix or decisive-rival fast path help. Downstream, the
recommender agent's finding that `drum_and_bass` is excluded from its
own candidate pool 92.9% of the time by the (now-unconditional) BPM
hard pre-filter is real, but its *severity* is entangled with running
against v2's known fold behavior rather than v3 — the number this
batch produced is not the number a genuine v3 baseline would produce,
in either direction.

**Fix.** Added `'beat_tracker_engine': 'v3'` to `run_session()`'s base
`cfg` dict, matching `config.toml`'s own live default, so a replay
session tests what the live app actually runs unless a caller
deliberately opts into the v2 protected baseline via `--override
beat_tracker_engine=v2`. Two new regression tests in
`tests/test_session_replay.py`: `test_default_engine_matches_config_
toml_live_default` (pins `engine_version == '3.0.0'` with no override)
and `test_beat_tracker_engine_override_still_reaches_the_controller`
(confirms the override path still reaches `'2.0.0'` on request — the
fix must not make a deliberate v2 comparison run unreachable). Full
suite green (2210 passed) after landing.

**Not yet done:** the 16-session batch needs a full rerun with the fix
applied before "the whole shebang" detect/select/mood/director analysis
the owner asked for can be trusted for anything detector- or
recommender-side. The director-side timing findings (BUILD/CLIMAX
dwell, mode-cycle churn, `climax_extend_max_factor` dominating observed
CLIMAX duration over `climax_hold_s` itself) are architecture-agnostic
and stand regardless of which detector engine ran — director logic
doesn't consult `engine_version` — but should still be sanity-rechecked
against the rerun's own numbers rather than assumed unchanged.

### fold_suspect_mass Measured the Wrong Array (2026-09-04, detector rc.46)

**Trigger.** The corrected v3 baseline batch (above) confirmed the
fold-up fix genuinely engaged this time, but also surfaced a deeper
problem: `v3_fold_suspect_mass` read exactly `0.0000` median in every
single one of 16 sessions, including drum_and_bass sessions confidently
folded on 16/16 tracks for the entire session. The field exists
specifically to catch "confidently locked, but on the wrong lane" — and
was providing zero discriminating signal for exactly that case.

**Root cause.** `fs` was computed by summing `self._v3_posterior` (the
diffused posterior, AFTER this cycle's transition-matrix spread and
multiply) inside fold-ratio-shifted windows around the MAP state. Once
locked onto any lane — correct or a fold alias — the transition
matrix's own near-zero fold-jump probabilities (`_V3_FOLD_PROB_OCTAVE`
`1e-6`, `_V3_FOLD_PROB_TRIPLET` `5e-7`) mean almost all posterior mass
concentrates at the current MAP regardless of whether the fresh
acoustic evidence still supports a fold-related rival. The posterior
"forgets" the rival even while the raw per-cycle evidence for it
persists indefinitely — a structural property of the sticky Bayesian
filter, not a numeric bug. Confirmed directly: a synthetic scenario with
a real, persistent secondary comb peak at the true tempo, converged over
400 cycles onto the wrong (folded) lane at 99.93% confidence, read
`4.96e-6` — functionally zero — under the old computation.

**First attempt, also wrong, caught before landing.** Recomputing
against `like` (this cycle's raw, un-diffused observation likelihood)
instead of the posterior is the right *direction* — but normalizing raw
`like` directly produced a NEW problem: `like` is deliberately floored
at `self._v3_obs_floor` (`0.70`) everywhere, part of the "memory dial"
design that bounds how much any single cycle's evidence can move the
posterior. That floor makes raw `like` nearly flat (0.70–1.0) regardless
of real fold evidence — a synthetic clean, single-peak track with ZERO
real fold ambiguity scored `0.291`, *higher* than a genuinely folding
scenario's `0.278`. Caught by direct synthetic testing before landing,
not assumed correct from the direction of the fix alone.

**Fix.** Subtract the floor first (`np.clip(like - self._v3_obs_floor,
0.0, None)`), normalize that excess-above-floor array, then sum the same
fold-ratio-shifted windows. Verified monotonic on a synthetic sweep:
clean track `0.0000`, weak (0.2×) secondary peak `0.0000`, moderate
(0.6×) `0.0645`, near-tie (0.99×) `0.3272`. Extracted into its own
method, `_v3_compute_fold_suspect_mass(like, idx, lb, half_band)` — a
plain function of its arguments, directly unit-testable without the
full `update()`/audio pipeline, matching this file's established
pattern (`_v3_apply_decisive_rival`).

**Live re-validation.** A real drum_and_bass session (the same list that
motivated the fold-up fix originally, still folding 16/16 tracks per the
corrected-baseline analysis) now reads: median `0.267`, mean `0.274`,
82.5% of rows nonzero, p90 `0.562`, p99 `0.867`, max `1.0`. The median
sits comfortably above `_V3_FOLD_SUSPECT_GATE_MASS` (`0.2`) for most of
the session — meaning the genre-evidence consultation this metric gates
(`_v3_apply_genre_evidence()`, see "v3 Genre-Evidence Consultation +
Fold-Suspect Gate" above) now actually engages on real fold-suspicious
material, closing a gap that's existed since that gate was introduced.
`0.2` held up against real data on this first check; not re-tuned.

**Note on coupling.** `like` already includes `_V3_FOLD_OBS_WEIGHT`'s
own fold-symmetric evidence-sharing boost (see `_v3_observation_
likelihood()`), so this metric and that boost are coupled by design —
both express the same "fold-related lanes share evidence" philosophy,
not an accidental interaction.

**Regression test.**
`tests/test_beat_tracker_v3.py::test_fold_suspect_mass_discriminates_real_fold_ambiguity`
drives `_v3_compute_fold_suspect_mass()` directly across the same
synthetic sweep (clean/weak/moderate/near-tie), asserting a clean track
reads exactly `0.0`, the sequence is monotonic, and near-tie ambiguity
clears `0.2`. Full suite green (2211 passed) after landing.

**Bookkeeping.** `_DETECTOR_VERSION` `1.0.0-rc.45 → 1.0.0-rc.46`;
`_VJ_WEIGHTS_DOC_VERSION` `97 → 98`.

### Spotify Naming Removed from the Shared Now-Playing Channel (2026-09-04, director rc.19)

**Trigger.** While investigating why harmony/key data never populated
any training corpus, found `_decode_camelot_key(str(spotify.get('key')
or ''))` in `auto_vj.py` — and traced it to a real, working channel:
`dj_mixer_controller.py`'s `now_playing_snapshot()` already feeds a real
Camelot key (from `key_detect.py`'s chromagram analysis, via
`track_store`) through `vj_api.active_now_playing()` into this exact
line. Reported this to the owner as a correction — the `spotify`-named
plumbing here isn't dead, it's the real channel harmony data would flow
through, just misleadingly named (confirmed via `_spotify_snapshot()`'s
own docstring: "Prefers `vj_api.active_now_playing()` so mixer- and
media-sourced sessions train the same as Spotify sessions"). Owner:
"keep the stuff needed for the real spotify drop in playctl & webapi
but i don't want anything named after it that is part of the vj system
so fix all that please."

**Scope, decided per call site, not a blanket removal.**

- **Renamed** (genuinely source-agnostic, was just misleadingly named):
  `_spotify_snapshot()` → `_now_playing_snapshot()`,
  `_spotify_telemetry_snapshot()` → `_now_playing_telemetry_snapshot()`,
  `_spotify_last_change_counter` → `_now_playing_last_change_counter`,
  and the `spotify: dict` parameter/local-variable name → `now_playing`
  at every one of its ~30 call sites across the file (and the matching
  test fixtures in `tests/test_auto_vj_live_training.py`,
  `tests/test_auto_vj_shadow_engine.py`, `tests/test_auto_vj_phrase_
  structure.py`, and four other test files that stub these methods).
- **Kept unchanged**: the internal `get_subsystem('spotify')` fallback
  lookup inside `_now_playing_snapshot()` — a real subsystem key
  reaching the actual Spotify controller, not VJ-system branding, and
  exactly the "stuff needed for the real spotify drop in" the owner
  said to preserve. `control-room-01`'s own `_spotify_snapshot()` /
  `_draw_spotify_panel()` also left untouched — a dedicated Spotify
  status panel, legitimately Spotify-specific UI in a different
  drop-in, out of scope for "the vj system."
- **Removed, not renamed** (genuinely Spotify-API-only, no cross-source
  equivalent): `_is_spotify_audio_source()` and the "WEB PLAYER PAUSE"
  HUD pill that depended on it (Spotify-web-player-specific UX with no
  analog for dj-mixer/media sources); and `_handle_spotify_track_change()`'s
  queue-depth/playlist-context/next-track lookahead mood-biasing (real
  Spotify Web API queue data — dj-mixer-01/media-01 don't expose an
  equivalent upcoming-track queue) — renamed to `_handle_track_change()`,
  keeping only the energy-based mood-tag logic, which is genuinely
  source-agnostic. Matches the owner's own earlier characterization,
  found live in an existing code comment: "it's stupid that data
  collection was wired up only to support spotify.. we don't really
  even train on spotify, just verify."

**Full test suite green (2211 passed)** after the rename + removal,
including two renamed dedicated test functions
(`test_now_playing_snapshot_prefers_active_now_playing_hub`,
`test_now_playing_snapshot_falls_back_to_spotify_subsystem_when_hub_empty`,
`test_now_playing_snapshot_falls_back_on_older_core_without_hub_accessor`)
that still exercise the real dj-mixer-first-then-Spotify-fallback
precedence this channel has always had.

**Bookkeeping.** `_DIRECTOR_VERSION` `1.0.0-rc.18 → 1.0.0-rc.19`.

### Real Harmony Data Wired Into Training Corpus for the First Time (2026-09-04)

**Trigger.** Same investigation that found the Spotify-naming issue
above: `now_playing.get('key')` traced to a real, working channel
(`dj_mixer_controller.py`'s `now_playing_snapshot()`, fed by
`key_detect.py`'s real chromagram + Krumhansl-Schmuckler key detector,
via `track_store`) — but `session_replay.py`'s replay harness never
emulated a now-playing source with a `key` field at all, so every
training session ever run through this tool (not just tonight's) has
had zero real key/harmony data. Owner, once this was understood:
"let's start wiring it up! i'm stoked!"

**Two separate gaps closed, not one.**

1. **`_decode_camelot_key()` (`auto_vj.py`) was silently discarding
   confidence.** Extended its signature to accept a `strength: float =
   0.0` parameter and use it for `key_strength` instead of hardcoding
   `0.0` on every call (previously true even on a successful decode —
   confirmed by reading the function directly, not assumed from the
   field name). The one call site now passes `now_playing.get
   ('key_strength', 0.0)` through.
2. **`session_replay.py` never populated a `key` (or `key_strength`) in
   its emulated `now_playing` payload.** New `_load_key_detect()`
   (dynamic-load, same optional/graceful-degradation pattern as
   `_load_headless_stub()` — training-kit-01 stays runnable without a
   dj-mixer-01 checkout) loads `key_detect.py` directly; new
   `_estimate_key()` calls its `estimate_key(samples, samplerate)` once
   per track on the already-decoded PCM (reshaped `(N,) -> (N, 1)` since
   `key_detect.py` expects a `(N, channels)` array and averages across
   channels — a `(N, 1)` reshape is a correct, cheap no-op mono
   passthrough, not a workaround) at the same point `_announce()` builds
   the rest of the `now_playing` dict, threading `key`/`key_strength`
   through exactly like a real dj-mixer-01 or Spotify source would.

**Verified live, not just by test.** A real two-track synthwave session
(`DJ Tintin - Zeppeliner`, `Madi Di - Inside His Eyes`) produced real,
distinct, plausible results end to end through the actual production
decode path: `10A` / `B minor` / confidence `0.784`, and `3A` / `A#
minor` / confidence `0.891`.

**Regression tests** (`tests/test_session_replay.py`): `test_real_key_
detection_reaches_the_corpus` stubs `_load_key_detect()` with a
deterministic fake detector and asserts the exact key/scale/is_minor/
key_strength values reach every heartbeat row; `test_key_detection_
degrades_gracefully_when_dj_mixer_absent` confirms a missing detector
(or, by the same code path, a detection failure on a given track) falls
back to the pre-existing 'unknown' key schema rather than crashing.
Full suite green (2213 passed).

**Not yet done, explicitly out of scope for tonight:** nothing consumes
this data for genre discrimination yet — that's the next step (the
tech_house-vs-peak_time harmony hypothesis from the tempo-zone pairing
discussion). Also not addressed: dj-mixer-01's own `track_store` still
never persists `key_detect.py`'s confidence for *live* (non-replay)
sessions — `key_strength` stays `0.0` for a real dj-mixer-01-sourced
live session even after this fix, since that's a separate, deeper
change to the live analyzer/track-store schema, not attempted here.

**Bookkeeping.** `auto-vj-01` `__version__` `1.0.0-rc.122 → 1.0.0-rc.124`
(rc.123 was already claimed by an earlier same-night `zcr_sigma` fix
whose README changelog entry had never been matched by a `__version__`
bump — reconciled in the same commit as this change); `training-kit-01`
`__version__` `0.41.7 → 0.42.0`.

### electronic ("Dance") Disabled Again — Control-Pair Job Done (2026-09-04, recommender rc.37)

**Trigger.** While scoping smoke-test playlists across the enabled
roster, owner: "is electronic disabled? i thought we had the generics
disabled? we prolly should."

**Why it's a real generic, not a genre pending data.** `electronic`
("Dance") was disabled 2026-08-06 (cosine-similarity audit — its
`expected_bands` were more similar to far-tempo profiles than its own
tempo neighbors), then revived 2026-08-10 as a deliberate control pair:
kept identical to `house` on every axis except `vocal_hnr`/`vocal_fmr`,
specifically to validate that the vocal-presence discriminator actually
separates candidates on vocals alone. That validation job is done — real
`vocal_hnr_sigma`/`vocal_fmr_sigma` fields landed this same session
(rc.27-29), real non-zero weights, and real accuracy data from tonight's
corrected v3 baseline confirming the discriminator works (`rap_rnb`
47-51% in-pool argmax-correct on vocal presence). Unlike `tech_house`/
`techno`/`synthwave` (disabled pending real corpus data, each with a
genuine distinct acoustic identity once fingerprinted) `electronic` has
no distinct identity by design — its own description literally reads
"otherwise identical to house." Disable-not-delete, same pattern as the
other three: `get_profile('electronic')` still resolves it directly,
only discovery (`list_profiles()`/`enabled_profiles()`) excludes it.

**Test updates.** `tests/test_audio_profile_deep_house_and_disable.py`:
`test_enabled_profiles_excludes_only_disabled_entries`,
`test_default_enabled_true_for_profiles_that_dont_set_it`, and
`test_electronic_key_now_resolves_to_the_revived_dance_profile` (the
last one now asserts `enabled is False` and exclusion from discovery,
inverted from its own name's history — left the name as-is since it
still accurately describes what the key resolves to, just not as an
enabled candidate). `test_dance_matches_house_on_everything_except_
vocal_presence` needed no change — it only asserts field values, not
`enabled`, and the disable-not-delete pattern leaves those unchanged.
Full suite green (2213 passed).

**Bookkeeping.** `_RECOMMENDER_VERSION` `1.0.0-rc.36 → 1.0.0-rc.37`.

### hyphy Disabled Again (2026-09-04, recommender rc.38)

**Trigger.** Mid smoke-test-playlist build, owner, direct: "disable
hyphy."

**Context.** `hyphy` ("Hyphy / Trap") had been re-enabled earlier the
same day, split out of `rap_rnb`'s pool once `training-trap-hip-hop-01`
supplied real material to fit its vocal/spectral/tempo fields against
(see "Spectral-Shape Ribbon Redesign" and the same-day BPM-recalibration
revert above). Building the smoke-test playlists required picking real
per-genre "easy win" tracks by scanning the library for ID3-tagged
content, and turned up zero tracks anywhere tagged Hyphy — every field
on this profile is fit entirely against trap-hip-hop-01's own corpus, so
in practice the profile has no acoustic identity distinct from a
straight trap read. That's the same shape of problem tech_house/techno/
synthwave were disabled for (a real, fitted profile with no dedicated
library content backing it), just discovered from the content side
this time instead of a fingerprint-similarity audit.

**What changed.** `unicornviz/audio/profiles.py`: `hyphy.enabled`
`True → False`. No other field touched — the vocal_hnr/vocal_fmr/
expected_bands/bpm_prior values fit from training-trap-hip-hop-01 stay
as-is; they're the best available material if hyphy is revisited later.
Disable-not-delete, same pattern as tech_house/techno/synthwave/
electronic: `get_profile('hyphy')` still resolves it directly, only
`list_profiles()`/`enabled_profiles()` exclude it.

**Test updates.** `tests/test_audio_profile_deep_house_and_disable.py`:
`test_enabled_profiles_excludes_only_disabled_entries` and
`test_hyphy_reenabled_and_recalibrated_from_trap_hip_hop_01` (now
asserts `enabled is False` and exclusion from `enabled_profiles()`).
Full suite green (2238 passed).

**Bookkeeping.** `_RECOMMENDER_VERSION` `1.0.0-rc.37 → 1.0.0-rc.38`;
`_VJ_WEIGHTS_DOC_VERSION` `98 → 99`.
