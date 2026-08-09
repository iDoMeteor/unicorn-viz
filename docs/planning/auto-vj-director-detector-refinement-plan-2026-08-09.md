# Auto VJ: Director/Detector/Recommender Refinement Plan (2026-08-09)

Owner: unicorn-viz
Status: draft — most decisions resolved (2 discussion rounds), 5 open
  questions remain; not yet approved for implementation
Last updated: 2026-08-09

## Context

Follow-up to the 2026-08-09 a-i analysis (director state machine, `drop_score`
composition, external mixer influence, proximity, timing constants) and the
`library/a` training set's LLM tuning report. This doc turns that analysis
into a concrete, sequenced implementation plan across five areas:

1. Apply the training set's LLM recommendations (minus one held back).
2. Fix `BREAKDOWN -> DROP` (missing transition — common case, not an edge case).
3. Redesign the DROP/IMPACT/CLIMAX relationship and loosen mode ordering.
4. Rework `drop_score`'s composition (band_blend rebalance, new bass-transient
   term, flux_norm scope).
5. Add external-influence + phrase-bias logging so (e) is answerable from data
   next time, not just from design reasoning.
6. Make phrase-bias weights genuinely tunable (config-menu "weights by
   context"), and extend the per-context idea to `drop_score` and genre-scoped
   thresholds.
7. Version numbering for the three subsystems, plus CLI overrides for
   per-subsystem A/B testing during the training marathon.

Per `docs/adr/vj-system.md` / `docs/adr/training-model.md` discipline, every
constant change below gets an ADR entry in the same commit that ships it, and
every weight/threshold change gets a `weights-and-thresholds.md` sync +
`_VJ_WEIGHTS_DOC_VERSION` bump.

---

## 1. Apply LLM training recommendations (`library/a`)

| Change | Current | New | Where | Verdict |
|---|---|---|---|---|
| `kick_regularity_fit` weight | 0.5 | 0.7 | `_DEFAULT_RECO_WEIGHTS` (auto_vj.py:496) | Apply |
| `spectral_shape_fit` weight | 1.0 | 1.2 | `_DEFAULT_RECO_WEIGHTS` (auto_vj.py:495) | Apply |
| `tech_house.spectral_centroid_mu` | 2550.0 | 2900.0 | `unicornviz/audio/profiles.py:325` | Apply |
| `_BPM_LOCK_RELEASE_CONFIDENCE` | 0.28 | 0.25 | `auto_vj.py:3133` | **Hold — see below** |

**Overlap check on the centroid change (owner asked directly):** doesn't
overlap, it helps. Current neighbor values: `house` mu=2650/sigma=600,
`deep_house` mu=1250/sigma=400, `peak_time` mu=2350/sigma=400. Tech house's
own top confusion in this exact session was `Tech House -> house` (1060x,
by far the largest confusion in the set). Moving tech_house's mu from 2550 to
2900 *increases* its distance from house's mu (100 -> 250) — it separates the
two profiles further apart, working directly against the observed confusion
rather than into it. Deep house and peak-time are already far enough away
that the move doesn't bring tech_house closer to either. Green light.

**Status: to-watch, not applied** (owner, 2026-08-09: "put that on the
'to watch' list... I trust us over the LLM any day of the week"). Revisit
only if a future session's scorecard actually shows lock churn — the
rationale below is why this one specifically isn't a "someday maybe," it's
"don't touch until the symptom exists."

**Why it's held back:** the
`library/a` session that produced this recommendation shows `0 lock gained` /
`0 lock lost` — zero churn — in its own scorecard. The LLM's stated rationale
("minor lock churn during varying BPM sections suggests release confidence
is slightly too high") doesn't match the data from the same session it was
derived from; there's nothing in this corpus that shows the symptom the
recommendation is fixing. Separately, lowering the release threshold *widens*
the hysteresis band (0.55 acquire / 0.28 release is already a 0.27-wide band;
0.25 would widen it to 0.30), which makes the tracker *more* resistant to
recognizing a genuinely lost lock — the same direction as the "BPM not
pulling hard enough on track change" concern from earlier today (item i),
not the opposite. Recommend leaving this one alone until a session actually
shows churn to fix, rather than tuning against a symptom that isn't present.

**Packaging pipeline change (owner-requested, separate from the weight
changes above):** currently `scorecard.md` / `recommender_score.md` /
`detector_score.md` / `director_score.md` / `tuning_recommendations.md` are
generated independently with no cross-linking, which is why the weight
recommendations were hard to find. New behavior for
`tools/package_training_set.py`:
- Keep all five files fully separate (no merging content between them) — per
  owner instruction, this is intentional, not the discoverability fix.
- After all five are written, feed all five back to the LLM in one follow-up
  call and have it produce a consolidated **summary** (not a merge — a
  synthesis: top 3 takeaways, whether recommendations conflict with each
  other, one-line pointer to which file has the detail).
- Print that summary to console at the end of the packaging run, followed by
  the on-disk paths of all five individual report files as reminders, so the
  console output is the actual "here's what happened, here's where to read
  more" entry point instead of the current silent file-drop.
- No new file needed for the summary — console-only, per the "no new file"
  spirit of the request; if useful later it can be captured to a log, but
  that's not asked for here.

---

## 2. Fix `BREAKDOWN -> DROP`

Confirmed missing today: `_schedule_drop()` is only reachable from the
`BUILD` branch. Owner: "that's like most songs in the primary target
genres" — many house/tech-house tracks breakdown straight back into the next
drop without a distinct build phase re-triggering. This folds into the
broader state-machine loosening in section 3 below (same code path,
same commit) rather than being a standalone patch, since section 3 also adds
`DROP -> BREAKDOWN` and removes most other order restrictions — doing it
twice would mean re-touching the same transition table twice in one week.

---

## 3. DROP / IMPACT / CLIMAX redesign + general order loosening

### 3a. `DROP -> IMPACT`: confirmed final, documenting it as such

Owner: "make sure it's well noted that this IS the final design philosophy."
The 2026-08-05 one-shot design (`_infer_peak_tier()` decided once at
`_fire_drop()` time, no mid-groove escalation) stays as the DROP-entry
mechanism. Action: add an explicit "Status: final, superseded nothing further
planned" line to the ADR's "Phrase-Aware Director" entry so a future reader
doesn't wonder if this is another intermediate step in the same chain that
went 2026-06-18 -> 2026-06-28 -> 2026-08-05.

### 3b. CLIMAX: decouple from IMPACT

**How today's gate actually behaves, described plainly:** CLIMAX is *only*
reachable through IMPACT. The only call site of `_enter_climax()` is inside
the `elif self._mode == _IMPACT` branch (auto_vj.py:3011-3020) — after
`impact_hold_s` elapses on a major-tier flourish, one gate check
(`climax_worthy`) decides CLIMAX vs. settling back into ordinary DROP. So
IMPACT isn't just "the flourish for a major drop" today, it's also the
*only* corridor CLIMAX can be reached through — the two are structurally
fused into one sequential state (major DROP -> IMPACT -> [gate] -> CLIMAX or
DROP).

**What the owner wants instead:** IMPACT should be purely about the firing
of a major-tier drop (the flourish, nothing else). CLIMAX should be a
separate, later "the drop plateau I'm on is *this* good, it's leveling up"
decision — not gated behind having passed through IMPACT's fixed hold timer.
Concretely: **`DROP -> CLIMAX` becomes a direct transition** (evaluated from
ordinary DROP, not just from IMPACT), keyed on the same kind of tier/
confidence/song-progress signal `climax_worthy` already uses, but no longer
requiring the intervening IMPACT stopover. IMPACT keeps existing as the
entry flourish for major-tier drops, but stops being a prerequisite state
for CLIMAX eligibility — a track can go `DROP -> CLIMAX` on a later,
still-major-tier moment in the same drop, well after IMPACT's flourish has
already settled back into normal DROP.

**Resolved 2026-08-09** (owner: "your choice, the smart version"). Keep
`climax_worthy`'s gate logic itself verbatim (peak_tier == major, downbeat
confidence, score-vs-threshold-plus-progress OR early-override) — but add
one small guard: `climax_worthy` cannot be evaluated true until at least
`impact_hold_s` has elapsed since `_fire_drop()`, even when evaluated from
plain DROP rather than from IMPACT. Rationale: IMPACT's flourish window
already represents "how long a major-tier drop needs before its energy
level is actually legible," and CLIMAX is restricted to major-tier drops
too — reusing that same floor as a minimum time-since-fire guard (instead of
inventing a second, separate timing constant) prevents CLIMAX from firing in
the same tick as the drop itself without adding a new state-dependent gate
or reopening the "earned mid-groove" design 3a just declared final. This
keeps the guard as a pure timing floor unrelated to which state (IMPACT or
settled-DROP) is currently active — it fires the instant it's eligible,
whichever state that happens to be.

### 3c. General order loosening

Owner: "we really shouldn't be discriminating about order much at all, aside
from intros, outros & major drop -> climax." Concretely:
- Add `BREAKDOWN -> DROP` (section 2) and `DROP -> BREAKDOWN` (new — a drop
  that fizzles/the energy drops back out should be able to settle straight
  into BREAKDOWN rather than only via CRUISE).
- Remove other structural order restrictions between CRUISE/BUILD/BREAKDOWN/
  DROP where audio evidence (not phase-clock position) is what should decide
  — phrase bias keeps nudging thresholds as it does today, it just stops
  being a hard gate on which edges exist at all.
- Keep exactly two hard constraints: (1) some notion of intro/outro framing,
  (2) CLIMAX only follows a major-tier DROP (not BREAKDOWN, not directly from
  BUILD).

**Resolved 2026-08-09** (owner): there is no existing formal "intro"/"outro"
concept in the mode state machine today (the only `'intro'`/`'outro'`
matches in the codebase are a title-keyword heuristic for effect-tag
selection, unrelated to director mode transitions) — owner's answer defines
what fills that gap, source-conditionally:

- **Default (no reliable section metadata — Spotify, generic line-in, any
  source without structural section reporting):** first mode after track
  load stays CRUISE, unchanged from today. No new state needed for this
  case.
- **dj-mixer-01 / media-01 sources specifically** (the two sources capable
  of publishing section metadata via the section-hint bus, section 5): two
  **new director modes, `INTRO` and `OUTRO`**, applied only when the active
  source can supply that metadata. Rationale, owner's own words: "unless
  being hard cut into somewhere in the middle, in which case that's coming
  from the mixer and it should be able to track pretty well by the incoming
  section meta." A DJ hard-cutting into the middle of a track looks
  identical to a fresh track load from the detector's point of view (this is
  the exact hard-cut ambiguity the 2026-08-05 phrase-structure plan already
  flagged and withheld bias for) — but when the source is dj-mixer-01/
  media-01, the incoming section hint (`role`, confidence) tells the
  director what it's actually being cut into, so it doesn't have to default
  to CRUISE-first at all; it can start directly in whatever mode the
  incoming section implies. `INTRO`/`OUTRO` become the explicit "this is
  what a source-confirmed structural edge looks like" states — bookending a
  track when the source can confirm it, rather than the director having to
  infer it from bar-counting alone.

**This is bigger than "define what the constraint means" — it's two new
director modes, gated on source capability.** Out of scope to fully spec in
this doc; needs its own design pass covering at minimum: what visual/
audio-reactive treatment `INTRO`/`OUTRO` actually apply (are they closer to
CRUISE with a distinct look, or a genuinely different behavior class);
exactly which section-hint fields/confidence threshold are trusted enough to
skip the CRUISE-first default outright vs. still falling back to CRUISE when
the hint is present but low-confidence; and how `INTRO`/`OUTRO` interact
with the now much-looser general transition graph (3c above) — e.g. can
`INTRO` go anywhere `CRUISE` can, or does it have its own restricted exit
set. Flagging as a follow-on design item, sequenced after section 3's core
redesign lands (same "land the simpler piece first" reasoning as section 6's
sequencing).

### 3d. Versioning

This is the trigger for `_DIRECTOR_VERSION`'s next bump — ties into section 7.

---

## 4. `drop_score` composition changes

Current v2 formula (`beat_grid.py:818-822`):
```
drop_score = clamp(energy_norm*0.25 + slope_norm*0.409 + band_blend*0.182 + flux_norm*0.159)
band_blend = clamp(bass_n*0.45 + mid_n*0.30 + treble_n*0.25)
```

### 4a. `band_blend` rebalance toward bass

Owner: weight low end more, drop mid/treble to ~0.1-0.2. Directionally
agreed, but flagging a real interaction with 4b below before picking exact
numbers: `band_blend` is a **level** measure (smoothed per-band energy
share), while the new `bass_flux` term (4b) is a **transient** measure (rate
of change on the bass band specifically). Pushing `band_blend` hard toward
bass *and* adding a heavily-weighted bass-transient term both amplify the
same underlying signal (bass), which risks the same failure mode as the
treble double-count bug fixed earlier today — just on bass instead of
treble, and intentional-but-unmeasured instead of accidental. Not a reason
to avoid it, just a reason to land both changes together and re-tune the top
level weights (4c) as one exercise rather than two, and to watch the next
training session's corpus for whether bass ends up over-representing drop
timing (e.g. every sustained bassline verse starts reading as "a drop is
coming").

**Decided 2026-08-09** (owner: "split the diff, call it .7 to start"):
`band_blend = clamp(bass_n*0.7 + mid_n*0.2 + treble_n*0.1)`, up from
`bass_n*0.45 + mid_n*0.30 + treble_n*0.25`. "To start" — this is a starting
point for the marathon week, not locked forever; the bass-over-representation
watch item above still applies once `bass_flux_norm` (4b) is live alongside
it.

### 4b. New term: `bass_flux_norm` — bass transient detector

The real gap identified in the a-i analysis: nothing in `drop_score` today
detects "one big bass hit after near-silence" as its own signal —
`band_blend`'s bass term is a level, not an attack. The analyzer already
computes per-band raw flux for downbeat detection (`bass_flux`, currently
consumed only by the downbeat detector) — this is already-computed data,
not a new signal to derive.

Plan: add `bass_flux_norm` to `drop_score`, **heavily weighted**, using the
already-computed raw `bass_flux` value rather than deriving a new one.
Owner's framing: "one big bass hit after next to no bass should hit like a
freight train as fast as possible" — implies minimal smoothing on this
specific term (a fast-attack response), in contrast to the existing
EMA-smoothed `_flux_smooth` used for the general `flux_norm` term, which is
tuned for stability, not speed. Needs its own lightweight normalization
curve (mirroring `flux_norm = x/(x+0.10)`, tuned separately since raw
`bass_flux`'s scale differs from full-spectrum flux) rather than reusing
`flux_norm`'s constant.

### 4c. `flux_norm` — keep, but scope it away from bass

Assessment: not harmful today (low weight, 0.159, so a noisy signal has
limited blast radius), and genuinely useful as broadband confirmatory
evidence — but once `bass_flux_norm` exists as a dedicated bass-transient
term, letting `flux_norm` keep including the bass band on top of that is
redundant, the same shape of problem as the treble double-count. Plan:
narrow `flux_norm`'s input to mid+treble bands only, so it becomes
"non-bass spectral change" — complementary to `bass_flux_norm` instead of
overlapping it.

### 4d. Full reweight required

Adding a 5th term (or restructuring `band_blend` internally) means all
top-level weights (`energy_norm`, `slope_norm`, `band_blend`,
`flux_norm`/`mid_treble_flux_norm`, `bass_flux_norm`) need to be re-derived
together so they still sum to 1.0 and preserve `slope_norm`'s current
dominance (0.409 — correctly the top weight per the a-i analysis, since it's
what actually drives most breakdown->build detections and shouldn't get
crowded out by the new bass term). This is a numeric-tuning exercise best
done against real corpus data during the training marathon, not guessed at
in this doc — this section defines the *shape* of the change; the marathon
week's sessions (run against both `_DETECTOR_VERSION` variants via the new
CLI override in section 7) supply the numbers.

### 4e. Per-genre weights on `drop_score` (PGW) — owner asked for a verdict

**Verdict: valuable, not merely useful.** What a "drop" sounds like varies
enormously by genre — dubstep's drop is dominated by a wobble-bass
transient, four-on-the-floor house is kick-regularity-driven, trance builds
via arps/risers with much less bass dependence, and ambient/downtempo barely
has a "drop" in this sense at all. A single universal weight set is a real
compromise across that range.

The reason it's "valuable" rather than "expensive-but-valuable": section 6
below (config-menu weights-by-context) is about to build the exact
machinery PGW needs — named, profile-scoped, overridable constants exposed
through a context key. If that machinery exists for the director's
phrase-bias weights, extending the same pattern to `drop_score`'s weights
keyed by the *audio* profile (not VJ mood) is a much smaller marginal lift
than building a standalone per-genre system from scratch. Recommend treating
PGW as a natural extension of section 6's work rather than its own project —
sequence it after section 6 lands, not before.

---

## 5. External-influence + phrase-bias logging

Owner: "all the loggin'." Confirmed today: `dj_mixer_controller.py`
genuinely publishes section hints every cycle (`_publish_section()` ->
`vj.publish_section('dj_mixer', payload)`), and `_phrase_bias()` genuinely
consumes them (2.0x weight, bumped earlier today) — but nothing logs what
`_get_section_hint()` returned or what it contributed to the bias per tick.
Owner, directly: "are we not logging the external influence data? that
would tell us what and when which is correct, right" — yes, that's exactly
the gap, and yes, logging it is what makes "how is it performing" answerable
from data instead of design reasoning next time.

Plan: log, per director tick (or per mode-transition event, whichever
matches the existing corpus row cadence), the external-hint value(s)
consumed by `_phrase_bias()` and the resulting bias contribution —
mirroring the pattern `term_values_by_candidate` already uses for the
recommender. Lands in the same corpus rows so `package_training_set.py`
can eventually score it the same way recommender terms get scored.

---

## 6. Tunable weights: proximity bump + config-menu "weights by context"

### 6a. `_phrase_bias()`'s inline literals ("the magic numbers")

Owner asked for the full breakdown (2026-08-09). `_phrase_bias()`
(auto_vj.py:4022-4125) has 9 raw inline-literal multipliers, grouped into 7
conceptual bias terms (two are symmetric pairs sharing one concept each):

| Term | Line(s) | Value | What it does |
|---|---|---|---|
| Under-hold / over-hold | 4041 / 4044 | 0.6 (both) | Symmetric pair. Pushes bias *against* entering a phrase role too early (bars-since-entry < expected min for the current role) and *toward* leaving it once bars-since-entry exceeds the expected max — same 0.6 scale either direction, just opposite sign. |
| Phrase-boundary bonus | 4051 | 0.25 | Small positive nudge when within 1 bar of a natural phrase-unit boundary (default 8 bars) — this is `phrase_boundary_bonus_mult`, the one the LLM recommended raising. |
| PEAK flourish | 4054 | 0.3 | Flat bonus toward PEAK once the track has already cycled through `_phrase_peak_flourish_min_cycle` drops — later drops in a set get progressively favored toward peak treatment instead of every drop being scored identically. |
| Early-song suppression | 4059 | 0.4 | Discourages RISE/PEAK bias while song progress < 15% — a track that just started shouldn't be racing toward a climax read. |
| Outro suppression | 4061 | 0.5 | Once song progress crosses `_phrase_outro_song_progress`, discourages everything except HOLD — wind the set down near the end instead of chasing a fresh peak. |
| External match / mismatch ("sectionality") | 4101 / 4103 | 1.5 match / 0.5 mismatch (was 2.0/0.5 earlier today) | Asymmetric pair (by design, not an oversight — see the inline comment). A confirmed mixer-reported role match pulls bias toward that role at 1.5x, scaled by `confidence * proximity-to-boundary`. A confident *disagreement* pulls the other way, but only at 0.5x — confirmation and disagreement were deliberately never meant to be symmetric. Raised 1.0->2.0 earlier today, then dialed back to 1.5 the same day once the intent behind "raise it authoritative" turned out to be about this pair, not the boundary-bonus term (see below) — 1.5 deliberately stops short of letting external hints fully dominate the internal terms, to preserve learning signal for the internal detector/director (see the 2026-08-09 resolution below). |
| External "arm ahead" ("sectionality") | 4123 | 1.5 (was 2.0) | Same magnitude as the match term, but keyed on `next_role`/`bars_to_next` instead of the current role — lets the director prepare for a role the mixer says is coming, ramped over a wider window (`phrase_arm_proximity_bars`, default 16 bars vs. 8 for the current-role term) so "get ready" starts earlier than "confirmed, about to happen." |

**Correction, 2026-08-09:** the earlier "raise the shit outta that... should
be considered quite authoritative, especially since a real master DJ will
have his grids totally dialed in" instruction was about **sectionality** —
the external mixer-hint terms (match/mismatch/arm-ahead, already bumped
1.0->2.0) — not the internal bar-counting phrase-boundary-bonus term,
which the a-i report incorrectly conflated it with.

**Resolved 2026-08-09 — dial back to 1.5, not up to 2.0+.** Owner: "I was
kinda thinking making the externals 1.5 instead of 2.0? We still want the AI
to do *some* work... it's more important to have it learning for the next
months or year — if we don't give it opportunity to chip in, it won't learn
anything." This is an explore/exploit call, not an accuracy call: at 2.0 a
confident external hint can dominate the internal bar-counting/audio-
evidence terms almost completely, which is good for any single session's
correctness but starves the internal detector/director's own reasoning of
the chance to be tested against real outcomes — which is exactly the signal
the training marathon needs to keep tuning those internal terms over the
coming months. 1.5 keeps external hints clearly the strongest single
category of evidence (above the internal terms' 0.3-0.6 range) while still
leaving room for the internal reasoning to occasionally win out and generate
learnable signal. Both sectionality terms (match/arm-ahead, auto_vj.py:4101/
4123) move 2.0 -> 1.5; the mismatch term (4103, 0.5) is untouched — this
was never part of the asymmetry design, just the confirming-side magnitude.

**Status: committed, not deferred** (owner, 2026-08-09: "we need that
documented & tracked... hidden magic is no good... let's log, track &
analyze [these], and extract them into tweakables"). All 7 terms are now:
(1) documented in the table above, (2) get per-tick logging of each term's
individual contribution — extending section 5's external-hint logging to
cover all 7 `_phrase_bias()` terms, not just the external one, so their
real-world contribution is analyzable from corpus data the same way
recommender terms already are, and (3) get extracted into named,
profile-scoped constants (the same treatment 6b below gives
`phrase_boundary_bonus_mult`) as a committed piece of this work, not a
"maybe later" — this directly feeds 6c's config-menu exposure once the
extraction lands.

### 6b. `phrase_boundary_bonus_mult` — extract and raise

Important finding: the LLM's recommended `phrase_boundary_bonus_mult
0.25 -> 0.3` refers to a value that matches a real number in the code
(`bias += self._phrase_bias_max * 0.25 * (1.0 - boundary_dist)`,
auto_vj.py:4051, the "phrase-boundary bonus" row in 6a's table above) — but
that `0.25` is an inline literal, not a named, profile-overridable constant
like its siblings `_phrase_bias_max` / `_phrase_boundary_bar_unit`.

**Decided 2026-08-09** (owner: "that's not what I was thinking at the
time... I was thinking sectionality [see 6a's correction above]. Just raise
it to 0.3"). Plan: extract `phrase_boundary_bonus_mult` as a real named,
`_profile_value()`-backed constant (same pattern as `_phrase_bias_max`),
default `0.25`, new value `0.3` — matching the LLM's original recommendation
exactly, not the larger "raise it hard" number that turned out to belong to
the sectionality terms in 6a instead.

### 6c. Config-menu VJ tab: weights by context

New feature, owner-requested directly: "we should actually have ALL these
things tweakable in the config menu under the vj tab... the weights by
context." This is bigger than 6b alone — scope includes at minimum:
- The remaining 6 of 6a's 7 `_phrase_bias()` terms (needs the same
  extract-to-named-constant treatment as 6b before they can be exposed).
- `_DEFAULT_RECO_WEIGHTS` (`spectral_shape_fit`, `kick_regularity_fit`, and
  siblings).
- `drop_score`'s top-level weights (section 4), once finalized.
- The per-mood-profile timing constants (section 7... er, the timing table
  below) that already exist as named, profile-scoped constants today — these
  are the easy case, already following the right pattern, just need UI.

**Live-edit vs. restart, resolved 2026-08-09** (owner: "you'd be the better
judge on that, you have more view into the internals"). Judgment call: all
of the constants in scope here are plain floats read once via
`_profile_value()` at profile-apply time (`_init()` / `set_profile()`) and
cached to an instance attribute — none of them allocate GL resources or
require re-initializing anything heavier than a float. That means live-edit
doesn't need a process restart at all; it needs the config-menu write to
re-trigger the *existing* profile-apply/`set_profile()` codepath (which
already re-derives every `self._xxx = _profile_value(...)` assignment) after
an edit, the same way a mood-profile switch already does today. Recommend
exposing every constant in this section's scope as live-editable through
that mechanism — restart-required isn't a real constraint here.

**UI shape:** the constants in scope span three genuinely different scoping
levels — global (drop_score/recommender weights, no profile axis), per-mood
(the 7 `_phrase_bias()` terms + existing timing constants, 3 profiles), and
per-audio-profile (PGW/PGTT, section 4e/6d, 20 profiles, not yet designed).
Recommend one VJ config tab with three sections matching that grouping
(Detector weights / Director weights — mood-profile selector / Recommender
weights) rather than one uniform per-context selector trying to cover all
three axes at once — ship the global + mood-scoped sections first since
PGW/PGTT's per-audio-profile axis isn't designed yet and shouldn't block
them.

Still flagging as its own follow-on implementation pass, sequenced after
sections 1-5 and the 6a/6b extractions land, since those are prerequisites
for what the UI would even expose.

### 6d. Per-genre threshold tuning (PGTT) — committed, correction from the a-i report

Owner caught a real conflation in the original analysis: "wouldn't that be
more appropriate on the genre than the mood?" — correct, and the a-i
report's claim that per-genre thresholds "already exist" was wrong. The
existing `drop_fastlane_score` / `drop_confirm_score` /
`drop_timeout_score_floor` profile values are scoped to the three **mood**
profiles (chill/normie/raver — audience-preference axis), not to the twenty
**audio** profiles (genre-characteristic axis). Tuning drop thresholds by
mood answers "how does this audience want drops paced"; tuning them by
genre answers "what does a drop actually look like in this genre's own
signal" — a different, currently-unaddressed axis.

**Status: committed, not just flagged** (owner, 2026-08-09: "yeaaaa... so
let's address it"). This needs its own design (keyed off `active_profile`,
not VJ mood) — not a small correction to the existing mood-scoped system, a
genuinely separate one. Sequenced together with section 4e (PGW), after 6c's
weights-by-context machinery exists — same reasoning as PGW: building the
named/scoped-constant infrastructure once and extending it to both
`drop_score` weights (PGW) and drop thresholds (PGTT) keyed on audio profile
is a much smaller combined lift than building either standalone.

**Precedence, resolved 2026-08-09** (owner: "replace"): when a genre-scoped
value is available for the active audio profile, it replaces the mood-scoped
value for these three constants — it isn't layered/blended with mood. Mood
scoping stays as the fallback path for when genre-scoped values aren't
available or the recommender's audio-profile confidence is too low to trust
a genre-specific override — this fallback-on-low-confidence behavior needs
its own threshold when this gets designed (not specified here), same spirit
as `_phrase_external_tier_min_confidence`'s existing role gating a different
external signal in `_infer_peak_tier()`.

---

## 7. Timing constants

### 7a. Apply owner's explicit values

| Constant | chill (current -> new) | normie (current -> new) | raver (current -> new) |
|---|---|---|---|
| `build_max_s` | 52.0 -> 60.0 | 36.0 -> 45.0 | 55.0 -> 30.0 |
| `breakdown_max_s` | 55.0 -> 120.0 | 52.0 -> 90.0 | 80.0 -> 60.0 |

Owner's own read on why the old values were backwards: "those timings make
some sense since most of my tuning in those days was spent in raver mode" —
raver absorbed most of the hand-tuning attention early on and ended up with
the longest patience windows almost by accident, while chill/normie were
comparatively under-tuned. New values restore the intended direction
(raver = shortest patience/fastest cycling, chill = longest).

### 7b. `drop_timeout_score_floor` fallback fix ("the little drop floor fix")

Code-level fallback default is currently `self._profile_value(
'drop_timeout_score_floor', self._drop_threshold)` (auto_vj.py:1752-1753) —
i.e. if a profile omits the key, the fallback provides *no* relaxation at
all (identical to the normal threshold), despite every comment/doc
describing this as a "relaxed-but-not-zero floor." All three shipped mood
profiles already override it correctly (0.50/0.48/0.40), so this has never
misfired in practice — but the fallback should actually relax the threshold
so a future profile that omits the key doesn't silently get the wrong
behavior. Plan: change the code-level fallback to a fraction of
`drop_threshold` (e.g. `self._drop_threshold * 0.65`, in the same family as
the existing shipped values) instead of `self._drop_threshold` itself.
Owner: "go ahead and do the little drop floor fix" — approved, no discussion
needed, will land with the rest of this batch.

---

## 8. Versioning

### 8a. Subsystem version numbers — resolved: 1.0.0-rc.N scheme

**Resolved 2026-08-09.** Original ask ("detector 4.2, recommender 3.4,
director 3.0b") conflicted with `CLAUDE.md`'s alpha-stage "never bump MAJOR
pre-1.0" rule for these three constants (see prior draft of this section for
the full conflict writeup). Owner, on reflection: "fine... they're all
1.0 RC x... RC 3 for detector, 2 for recommender, 1 for director going on
2... they're all very mature but lack wisdom, kinda like teenagers."

This lands on resolution option 1 from the original three (informal
tuning-generation framing) but expressed through a scheme that's *already*
established in this exact codebase rather than a new one: `auto_vj.py`'s own
drop-in-wide `__version__` is already `1.0.0-rc.30` — release-candidate
pre-release tags climbing toward 1.0 are the project's existing precedent
for "mature, still earning trust before the real 1.0," which is exactly the
teenager framing above. No `CLAUDE.md` amendment needed — `-rc.N` was
already the sanctioned qualifier (`__version__` uses it), this just extends
the same qualifier to the three subsystem constants instead of introducing
a new `b`/`-beta.N` style, which resolves the "no precedent for a beta
qualifier" flag from the prior draft too.

New target values:

| Constant | Current | New |
|---|---|---|
| `_DETECTOR_VERSION` | `0.2.0` | `1.0.0-rc.3` |
| `_RECOMMENDER_VERSION` | `0.4.0` | `1.0.0-rc.2` |
| `_DIRECTOR_VERSION` | `0.2.0` | `1.0.0-rc.1` (→ `rc.2` when section 3's redesign ships) |

Not bumping any of these constants in this doc — per `CLAUDE.md`'s own
bump-rule discipline, the version moves in the same commit as the behavioral
change it describes, so `_DETECTOR_VERSION`/`_RECOMMENDER_VERSION` bump to
`rc.3`/`rc.2` when section 1/4's changes actually land, and
`_DIRECTOR_VERSION` bumps to `rc.2` when section 3's redesign lands — not
before. `weights-and-thresholds.md`'s header gets the matching update in
each of those same commits, per the existing doc-sync obligation.

### 8b. CLI overrides for per-subsystem A/B testing

New feature, owner-requested: ability to force a specific detector/director/
recommender tuning generation from the CLI, independent of each other, for
structured A/B comparison during the training marathon. This extends the
existing dual-engine shadow-tracking pattern already in the codebase (v2/v3
detector engines already run in parallel and get compared) into something
deliberately operator-controlled rather than always-on shadow mode.

Proposed shape (naming open for discussion): `--auto-vj-detector-version`,
`--auto-vj-director-version`, `--auto-vj-recommender-version` CLI flags in
`unicornviz/__main__.py`, threaded through as config overrides (same
`_build_overrides()` pattern used elsewhere), consumed by `auto_vj.py` to
pin which tuning generation of each subsystem is active for the session
regardless of what's currently the in-code default.

**Scope, resolved 2026-08-09** — owner, on the "does this need a full
registry of every past generation, selectable forever" question: "yea, it
would... we'd have to tag & save ALL edits for the rest of time. maybe
that's not a knock-it-out-real-quick item :D" — agreed, **descoping the
infinite-history registry out of this batch.** What ships instead: the
session's corpus/scorecard records which subsystem versions (8a's `rc.N`
tags) were active, satisfying the "sessions are comparable after the fact"
need without requiring old constant sets to remain selectable forever. True
A/B testing for the marathon week works via the CLI flags overriding
*config values* for that session (already how `--dj-mixer-source`-style
overrides and profile values work — no new infrastructure), i.e. comparing
this week's new tuning against next week's further tuning, not against
every historical generation ever shipped. A real "pick any past generation"
registry stays a real idea, just explicitly deferred — flagged as its own
future item, not bundled into this plan.

**Methodology, refined 2026-08-09** — owner: "for proper A/B testing it
would probably be better to pass in the values one at a time from the CLI —
run a test with existing values, properly test only one override at a time,
compare. That's probably the best strategy short/medium term, and not a
priority right this minute." This simplifies the design further: rather than
a whole-subsystem "tuning generation" selector, what's actually wanted is
**single-constant override, one variable isolated at a time** — proper
controlled A/B, not bundle-vs-bundle comparison. That falls out almost for
free once section 6's constants are extracted into named,
`_profile_value()`-backed constants (they already read from config) — a
generic override mechanism (reusing the existing config-override CLI
pattern, no bespoke per-subsystem version-selector flags needed) covers this
without new infrastructure. **Explicitly not a priority right now** — revisit
once section 6's extractions land, since there's nothing to override via CLI
until then anyway.

---

## Open questions before finalizing (discussion pass)

Three discussion rounds (2026-08-09) have now resolved versioning (8a), the
CLIMAX gate (3b), the band_blend split (4a), `phrase_boundary_bonus_mult`
(6b), config-menu live-edit scope (6c), PGTT precedence (6d), the CLI A/B
registry scope + methodology (8b), and the sectionality weight (6a, 1.5).
What's left, genuinely still open:

1. **`drop_score` full reweight (4d):** `band_blend`'s internal split is
   decided (4a, 0.7/0.2/0.1), but the new `bass_flux_norm` term's own weight
   and the resulting top-level reweight across all terms is still pending —
   this one genuinely needs marathon-week data, not a guess.
2. **`INTRO`/`OUTRO` design (3c):** two new source-gated modes are decided
   in principle; still needs — what visual/audio-reactive treatment they get
   (distinct from CRUISE or not), what section-hint confidence threshold is
   trusted enough to skip the CRUISE-first default outright, and how they
   interact with the now-loosened general transition graph (restricted exit
   set or not).
3. **PGTT low-confidence fallback threshold (6d):** "replace" is decided;
   the confidence bar below which it falls back to mood-scoping instead
   needs a number once this gets designed.
4. **CLI override mechanism naming (8b):** deferred until section 6's
   extractions land — no specific flag names committed yet.
