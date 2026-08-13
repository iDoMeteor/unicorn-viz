# Auto VJ: Round Three Planning — Open Threads Toward Real v3 (2026-08-14)

Owner: unicorn-viz
Status: draft — capturing open design questions for the philosophizing
  days ahead per the owner's own framing ("we're going to continue on
  philosophizing about all this the next few days, planning some
  plans... keep a round 3 planning doc and once we reach consensus we'll
  knock it out and prepare for the real v3"). Nothing in this document is
  implemented yet except where explicitly marked done.
Last updated: 2026-08-14

## Context

Round three of the BPM-detector investigation (see
`docs/adr/vj-system.md`'s "Round Three" entry) landed one ASAP fix
(`_timing_scale_from_bpm`'s neutral point) and one small pure-logging
addition (`bpm_lock_gain_confidence`/`bpm_lock_release_confidence`), both
shipped same-night. Everything else below is design work the owner
explicitly deferred to a slower, consensus-first pass rather than
same-night implementation — this doc exists so none of it gets lost
between sessions, matching the pattern already established for the
persistence-window tracking work (see `docs/adr/vj-system.md` round two).

## 1. A real live example: the 2026-08-14 17:56 session collapse

While drafting this doc, the owner reported a session collapsing to
~80 BPM on "a pretty easy track" and asked for local scoring/analysis
before packaging it into the garbage sets. `logs/autovj-20260813T175608.jsonl`
(session scorecard: `lock=60.8/100`, `reco=20.3/100`, BPM p50/p90
`75.7/75.9`) turned out to be an unusually clean real-world capture of
several of the mechanisms below acting together:

- **Premature lock on weak evidence.** The very first ACF candidate
  (`75.95` BPM, `acf_confidence=0.32` — barely above
  `_V2_STARTUP_CONFIDENCE=0.3`) was accepted at cold start, then
  `bpm_locked` flipped `True` one cycle later once `downbeat_confidence`
  climbed to `0.56` and pushed the blended `confidence` to `0.66` —
  comfortably past `_BPM_LOCK_CONFIDENCE=0.55`. See § 4 below.
- **The true tempo was findable, and never used.** Once locked, the raw
  ACF kept finding candidates well outside the lock band nearly every
  cycle — `120`, `133.33`, `139.53`, `142.86`, `146.34`, `150`,
  `153.85`, `157.89`, `162.16`, `166.67` — all roughly double the locked
  `75.95`, consistent with a genuine ~120-150 BPM four-on-the-floor
  track (`kick_regularity` held `0.75-0.88` the entire session — a real,
  mechanically regular kick, not noise). None of these were ever
  accepted.
- **The persistence gate never once cleared.** `large_jump_persistence_wait_count`
  capped at `10` within the first ~5s (cold-start deque fill, matches
  the documented behavior in `weights-and-thresholds.md`), then
  `large_jump_persistence_reject_count` climbed from `0` to `137` over
  the ~2.4-minute session — `large_jump_persistence_cleared_count`
  **never left `0`**. The reject reason every single time: the last-25
  raw candidates' spread exceeded `6.0` BPM (candidates ranged roughly
  `88-166`, a >75 BPM spread) — not that too few cycles had accumulated.
  This is real evidence bearing on § 5 below: the persistence *count*
  (25) was not the binding constraint here; the persistence *spread
  threshold* (6.0) was, and the raw candidate is genuinely too
  unstable, cycle to cycle, to ever satisfy it once mislocked.
- **The tactus-fold logic correctly refused to compound the error**
  (every `last_tactus_fold` value that session was `score_reject:` or
  `region_reject:`, e.g. `166.67->125.00`, `120.00->90.00`) — it never
  folded a good high candidate down to a second wrong value. It also
  never used those same candidates to *escape upward* back toward the
  truth; that's not what tactus-fold is for (it only evaluates whether
  to fold a raw candidate down to match something already locked), and
  is a separate mechanism from the large-jump gate above.
- **The recommender flip-flopped, not the detector.** Top active
  profiles were `chillstep` (95 ticks) and `house` (48 ticks); top
  recommendations `chillstep` (15), `deep_house` (3); reco focus share
  `0%`, low-margin-mean `83.3%` — the recommender never landed
  confidently on anything, unsurprising given `75.95` BPM sits below
  even chillstep's own hint band (`78-112`, mu `95`) and far below
  house's (`118-126`, mu `122`). Confirms the one-way-flow cut is
  holding: this flip-flopping is a symptom of the bad BPM, not a cause
  of further corruption (recommender genre guesses do not write back to
  the detector's tempo search — see `docs/adr/vj-system.md`, "One-Way
  Flow" entry).

**What this session does *not* answer:** *why* the very first raw
candidate at cold start was `75.95` rather than something near the true
tempo, and *why* the raw comb-filter argmax bounces across such a wide
range (88-166) every cycle rather than repeatedly finding the same
competing value. Both are the subject of § 5/§ 6 below — this session's
data is a good input to that investigation, not a substitute for it.
Not yet decided: whether this session gets packaged into `garbage/` as
originally planned, or held out as a labeled regression fixture given
how cleanly it demonstrates the premature-lock + gate-can't-recover
combination — owner's call.

## 2. Full `_V2_*` gate/tunable inventory (beat_grid.py)

Requested: a complete list, since several of these ("another tunable I
never heard of") were promoted from bare `cfg.get()` literals to named
constants only this week and are genuinely new surface area. Grouped by
what they govern, not declaration order. All values current as of
`_DETECTOR_VERSION = '1.0.0-rc.23'`.

**Envelope / ACF mechanics** (rarely touched, foundational):

| Constant | Value | Meaning |
|---|---:|---|
| `_V2_ENV_RATE` | 100.0 Hz | Envelope sample rate, matches `Analyzer._ENV_RATE` |
| `_V2_ENV_WINDOW_S` | 8.0 s | Envelope history length feeding the ACF |
| `_V2_ENV_LEN` | 800 samples | Derived: `ENV_RATE * ENV_WINDOW_S` |
| `_V2_BPM_MIN` / `_V2_BPM_MAX` | 60 / 200 | Search range for the ACF lag scan |
| `_V2_PRIOR_MU` / `_V2_PRIOR_SIGMA` | 120.0 / 0.55 | Perceptual-prior center/width in log2(BPM) units, before any profile reweight |
| `_V2_COMB_HARMONICS` | 4 | Harmonics summed per candidate lag (aubio-style comb filter) |
| `_V2_HARMONIC_CONF_TOL` | 0.04 | Excludes a rival lag from the confidence rival-check if it's within this tolerance of an integer ratio of the winner (harmonic/subharmonic agreement isn't competing evidence) |
| `_V2_ACF_INTERVAL` | 8 frames (~7.5 Hz) | **This is what "cycle" means everywhere else in this table** — one ACF re-estimation pass, run every 8 render frames at ~60fps, so ≈133ms per cycle |

**Confidence blend** (separate axis from BPM-value acceptance — see
`docs/adr/vj-system.md` "BPM Value Determination Is Not Confidence"):

| Constant | Value | Meaning |
|---|---:|---|
| `_V2_PHASE_TOL` | 0.14 | ±14% of beat period counts as on-beat for phase confidence. **Locked — "Jason says do NOT change this, it's super dialed."** |
| `_V2_PHASE_NUDGE` | 0.25 | Fraction of phase error corrected per beat |
| `_V2_COHERENCE_WINDOW` | 35 | Rolling-average window (in onsets) for phase coherence |
| `_V2_PHASE_STRENGTH_SATURATION` | 2.0 | Onset strength (in MAD units above threshold) needed for full phase-confidence weight |
| `_V2_ANALYSIS_DOWNBEAT_CONFIDENCE_MIN` | 0.30 | Floor for `is_downbeat` to actually fire (gates § 4's downbeat-confidence boost) |

**Short-horizon beat-map analysis:**

| Constant | Value | Meaning |
|---|---:|---|
| `_V2_ANALYSIS_MAP_BEATS` | 64 | Rolling beat-position history length |
| `_V2_ANALYSIS_REGION_MIN_BEATS` | 8 | Minimum beats needed before a region-consistency check is meaningful |
| `_V2_ANALYSIS_REGION_TOL` | 0.20 | Tolerance for "recent beat positions consistent with candidate tempo" |
| `_V2_ANALYSIS_REGION_CONFIDENCE_MIN` | 0.40 | Floor for the region-consistency check itself to count (was 0.58; lowered same night as the gate-stack retune below — this is an OR-alternative to raw `acf_conf` now, not an AND-mandatory gate, per the chicken-and-egg fix) |

**BPM-value accept/reject gate stack** (decides whether a fresh ACF
candidate becomes the published `self._bpm` at all — entirely separate
from the confidence blend above):

| Constant | Value | Meaning |
|---|---:|---|
| `_V2_MIN_UPDATE_CONFIDENCE` | 0.25 | Already-locked: floor to accept *any* update, even in-band |
| `_V2_STARTUP_CONFIDENCE` | 0.3 | Cold-start floor (`self._bpm <= 0.0` only) — this is exactly the gate the 17:56 session's `0.32` candidate barely cleared |
| `_V2_LOCK_BAND_PCT` / `_V2_LOCK_BAND_MIN` | 0.16 / 10.0 | ±16% or ±10 BPM (whichever's larger) = "normal" range; nothing below applies inside this band |
| `_V2_TEMPO_HOLD_S` | 10.0 | Now *only* feeds the `primed_confidence` floor in `prime_tempo()` — the gate that used to read this for hold-skip stickiness was removed entirely this session |
| `_V2_LOW_BPM_GUARD` / `_V2_FAST_BPM_GUARD` | 115.0 / 130.0 | "Low lane" ceiling / "fast lane" floor for the guard below |
| `_V2_LOW_BPM_FAST_CONFIDENCE` | 0.45 | Extra confidence required specifically for a low→fast lane crossing (was 0.80) |
| `_V2_LARGE_JUMP_CONFIDENCE` | 0.5 | Confidence required for *any* jump outside the lock band (was 0.72) — the primary gate a real track-boundary change has to clear |
| `_V2_MAX_BPM_STEP` | 5.0 | EMA step cap — even a fully-accepted jump arrives over multiple cycles, not instantly (was 3.0) |
| `_V2_LARGE_JUMP_PERSISTENCE_CYCLES` | 25 | See § 5 — separate, longer persistence window gating only large jumps |

**Tempo-pick hardening for sparse/slow material:**

| Constant | Value | Meaning |
|---|---:|---|
| `_V2_RAW_DOMINANCE_RATIO` | 1.18 | How much a raw (non-prior-weighted) candidate must dominate to override the prior |
| `_V2_DENSITY_FAST_RATIO` / `_V2_DENSITY_SCORE_RATIO` | 1.30 / 0.45 | Onset-density-based guards against picking an implausibly fast tempo on sparse material |

**Director-level (auto_vj.py, not beat_grid.py, but same family of "is
this floor tracked" question):**

| Constant | Value | Meaning |
|---|---:|---|
| `_BPM_LOCK_CONFIDENCE` | 0.55 | Schmidt-trigger gain — confidence must reach this to declare `bpm_locked=True` |
| `_BPM_LOCK_RELEASE_CONFIDENCE` | 0.28 | Schmidt-trigger release — lock holds until confidence drops below this |
| `_TIMING_SCALE_NEUTRAL_BPM` | 114.0 | Neutral point for director timing-scale (fixed this round, was 128) |

Now logged every row (`bpm_lock_gain_confidence`/
`bpm_lock_release_confidence`, shipped this round, see § 4) so
`bpm_locked` can always be checked against the actual threshold it was
measured against.

## 3. Is 25 cycles too big for the persistence check? Define "cycle."

**"Cycle" = one ACF re-estimation pass** — `_V2_ACF_INTERVAL = 8` render
frames at ~60fps, so a cycle happens roughly every 133ms, ≈7.5 times per
second. `_V2_LARGE_JUMP_PERSISTENCE_CYCLES = 25` therefore spans
≈3.3 seconds of *continuously appended* raw candidates (the deque fills
on every cycle, not only during large-jump evaluations, so in steady
locked operation it's already full well before any jump is even
considered).

The honest answer from § 1's real data: **the count of 25 doesn't
appear to be the binding constraint in that session** — the deque
filled in ~5 seconds (10 wait-cycles) and then every subsequent
evaluation failed on the *spread* check (`> 6.0` BPM), not on
insufficient history. Lowering 25 to, say, 15 wouldn't have changed the
outcome there, because the candidates spanned roughly 75 BPM of range,
nowhere near tight enough to satisfy `spread <= 6.0` regardless of
window length. Two real, distinct knobs exist here and the session data
only speaks to one:

1. **Window length (25 cycles)** — trades reaction speed for stability.
   Shorter reacts faster to a real transition but is more exposed to
   short wobbles (the original bug this constant fixed). Real data
   hasn't yet shown 25 being *too slow* to matter in practice (both the
   wobble fix and the 20-pair sweep converged within a few seconds
   either way) — no evidence yet that it should move.
2. **Spread threshold (6.0 BPM)** — this is what actually gated the
   17:56 session, and it's arguably working *correctly*: the raw
   candidates really were that unstable, and accepting a jump into that
   much noise would likely have been worse, not better. The real
   problem it's exposing is upstream — § 6, the comb-filter argmax
   wandering across a >75 BPM range cycle to cycle on real material.

**Recommendation, not yet acted on:** don't touch 25 (or 6.0) yet — the
17:56 session is one data point, and moving either without more sessions
risks re-introducing the wobble this gate was built to fix. Worth
re-examining once § 6's investigation gives some sense of *why* the
argmax wanders that far, since a fix there might shrink the natural
spread of legitimate candidates and make 6.0 workable again without
touching the window length at all.

## 4. `_has_bpm_lock()`'s own floor

Tracked starting this round (§ 2's director-level table, shipped
same-night): `_BPM_LOCK_CONFIDENCE` (0.55 gain) /
`_BPM_LOCK_RELEASE_CONFIDENCE` (0.28 release) now echoed in every
`_detector_snapshot()` row as `bpm_lock_gain_confidence`/
`bpm_lock_release_confidence`. Values themselves unchanged this round —
pure logging, per the owner's ask ("we probably need to keep our eye on
that floor we're kinda tuning right").

The § 1 session is a live illustration of why this floor matters: a
`0.66` blended confidence (comfortably past the `0.55` gain) triggered
`bpm_locked=True` one single cycle after the very first non-zero ACF
candidate landed — the downbeat-confidence term alone contributed `0.25
* 0.56 ≈ 0.14` of that 0.66, on a lock that turned out to be a real
octave-family error. Whether `0.55` is too permissive for a *cold-start*
lock specifically (as opposed to an already-established one regaining
confidence after a dip) is an open question worth its own investigation
once more sessions exist — not actioned this round.

## 5. Rear-view-mirror rolling windows (4/8/16/32-beat)

Owner's proposal: keep rolling comparison windows of the last 4/8/16/32
beats, both to (a) potentially replace or supplement the flat
25-cycle/spread-6.0 persistence check in § 3 with something that adapts
across multiple window lengths, and (b) help understand song phrasing
to assist the director, which "may already be using this technique
sorta."

**On (b): it doesn't, not quite.** `_phrase_bias()` (auto_vj.py,
~line 4629) is real and substantial, but it's a *bar-count expectation
model*, not phrase *detection*:

- `_PHRASE_ROLE_BARS` maps each of the four director roles (`HOLD`,
  `RISE`, `PEAK`, `FALL`) to a pair of per-profile config keys
  (`_phrase_hold_expected_min_bars`/`_max_bars`, etc.) — the expected
  bar-count range for that role, tuned per genre profile.
- `_advance_phrase_clock()` increments `_bars_since_phase_entry` /
  `_bars_since_track_start` on every real `is_downbeat` firing — pure
  counting from an internal clock, no independent signal analysis of
  the audio to detect where a phrase actually starts or ends.
- `_phrase_bias()` computes a soft additive bias (never a hard gate) on
  the transition threshold for a role, blending: under/over-hold terms
  (bars vs. expected range), a small boundary bonus near multiples of
  `_phrase_boundary_bar_unit`, a peak-flourish bonus, song-progress-based
  early/outro suppression, and — the strongest term when available — the
  **external mixer section hint** (`vj_api.get_section()`, dj-mixer-01's
  own pre-analyzed structure), scaled by its confidence and proximity
  (`bars_left`/`bars_to_next`).

So today's phrasing "detection" is really *external, from dj-mixer-01,
when present* — the internal fallback is a bar-counted expectation
prior, not a data-driven boundary detector. A rolling multi-window
energy/spectral-flux comparison could be a genuine independent detector
of section changes (bass-drop density, spectral-centroid shift, onset-
density step change over a 4-vs-32-beat comparison), which
`_phrase_bias()` could consume as another external-hint-like term even
without dj-mixer-01 present — this would be new capability, not a
duplicate of existing logic.

**On (a):** plausible replacement for the flat persistence gate — e.g.
require agreement across 2+ of the 4/8/16/32-beat windows before
accepting a large jump, rather than one flat 25-cycle/spread-6.0 check.
Real design work needed before touching code: what "agreement" means
across differently-sized windows, memory/CPU cost of maintaining four
rolling buffers instead of one, and whether this should *replace*
`_V2_LARGE_JUMP_PERSISTENCE_CYCLES` or run alongside it as an additional
signal.

**Are the phrase vars captured for training today? No, only sparsely.**
`_bars_since_phase_entry`/`_bars_since_track_start`/
`_phrase_neutral_bars_left` are **not** in the regular per-tick
`_detector_snapshot()`/corpus payload at all. `phrase_bias_terms` (the
per-term breakdown dict) is logged **only** at the moment of an actual
`_mark_mode_transition()` call — i.e. only when a transition fires, not
continuously. There is no rolling trace of the phrase clock's state
today. Any real rolling-window design work (for either use case above)
would need continuous logging of at least `bars_since_phase_entry` and
the role, not just the sparse transition-triggered snapshot that exists
now.

**What about the phase anchor?** There isn't a real one, and this is
worth flagging on its own. `beat_grid.py`'s downbeat detection
(`_advance_phase()`, ~line 2155) is: `self._bar_beat_count =
(self._bar_beat_count + 1) % 4`, incremented on every beat, firing
`is_downbeat` when it wraps to 0 (gated by
`_analysis_downbeat_confidence_min`). `_bar_beat_count` is initialized
to `0` once, at tracker construction, and **is never reset or
re-aligned afterward** — no code path corrects it against the track's
actual bar-1 position. It's an assumption of persistent 4/4 alignment
from an arbitrary starting beat, not a real anchor to the music's actual
bar structure. The one correction mechanism that exists,
`_maybe_sync_phrase_clock_from_section_hint()`, only ever adjusts
`_bars_since_phase_entry` (the *auto_vj.py* phrase-role counter, from a
fresh external mixer hint) — it does not touch `beat_grid.py`'s own
`_bar_beat_count`/downbeat-phase alignment at all. Whether this matters
in practice (four-on-the-floor material may not care much where "beat
1" nominally falls) versus material with real verse/chorus bar-1
significance is untested — flagged here, not investigated further this
round.

**d4/d5 — agreed, deferred:** this would plausibly help both the
director (phrasing) and the recommender (a section-change signal could
sharpen genre-fit timing), and it's real design work, not a
same-session integration. Parked here for the philosophizing days.

## 6. Raw comb-filter argmax wandering — next after this run

Still open, and § 1's session is a strong real-world case to start from:
the raw ACF argmax bounced across roughly 88-166 BPM cycle to cycle on
genuinely regular kick material (`kick_regularity` 0.75-0.88 throughout).
Candidates like `120`, `133.33`, `146.34`, `150`, `162.16` don't look
like a single stable competing harmonic — they look like the comb
filter's peak selection itself is unstable near this material's true
tempo, possibly because ACF lag-grid resolution coarsens at these BPMs
(short lags → fewer samples per lag bucket) the same way the known
124-BPM grid-split gap does, just wider. `acf_top_candidates` and
`last_tactus_fold` are both logged now specifically to support this
investigation. Owner: dig into this after the next run, not this round.

## 7. v1/v2/v3 BPM accuracy logging

**7a. Agreement logging (in scope for the next round, design accepted):**
Log, per song, an agreement table comparing the detector's own reading
against two independent external checks:

- **Internal agreement:** active engine vs. shadow engine (already
  running today — `bpm_shadow`/`confidence_shadow`/`shadow_engine` exist
  in every corpus row when a shadow is configured).
- **External match via mixer library:** look up the track in
  dj-mixer-01's own library/analysis JSON for its independently-analyzed
  BPM, when the track is identifiable (same identity-matching problem
  `_get_mixer_bpm()`/`prime_tempo()` already solve for priming — reuse
  that path rather than inventing a second one).
- **External match via LLM song lookup:** for tracks without a mixer
  library entry (e.g. Spotify-sourced), ask an LLM for the song's known
  tempo as a second, weaker-confidence external reference. Needs its own
  scoping: caching (don't re-query per session), and how confident to
  treat an LLM's tempo recall versus a real mixer analysis (almost
  certainly lower-weight — an LLM's BPM recall for an obscure track is
  not audio ground truth).

Per-song table shape: `song | internal (v1/v2/v3 agreement %) | mixer
match | llm match | consensus verdict`. Not yet scoped: exact schema,
where this lives (scorecard section vs. a new report), and whether
"accuracy %" for the whole run (as originally asked) is a simple
mean-agreement rollup or something that treats mixer-verified tracks as
higher-confidence ground truth than LLM-verified ones.

**7b. Is it really just one factor between v2/v3? Yes — confirmed, not
just remembered correctly.** Read `BeatTrackerV3` directly
(`beat_grid.py:2450`): it subclasses `BeatTracker` (v2) and overrides
exactly one method, `set_profile()` — v2 unconditionally re-primes the
tempo prior from genre on every call (including mid-track, letting
recommender inference flow backward into the detector); v3 only allows
that prime before `self._bpm > 0.0`, otherwise a complete no-op. Nothing
else differs. `v1` (`BeatGridTracker`, `beat_grid.py:203`) is a
genuinely separate, much simpler architecture — IOI-median based, no
ACF/comb-filter/phase-oscillator at all, `ENGINE_VERSION = '1.0.0'`,
documented cost `< 0.3ms/frame` ("lightweight," confirmed).

**Recommendation (not yet actioned — needs consensus):** fold v3's fix
directly into v2's own `set_profile()` and retire the `BeatTrackerV3`
subclass, rather than keep carrying it as a separate engine name. It's
purely additive (never worse than v2's old behavior, only prevents the
specific backward-flow case), so there's no real tradeoff being
preserved by keeping it distinct. This also frees the name "v3" for the
actual next-generation engine the owner referenced ("prepare for the
real v3 incoming very soon") instead of colliding with today's
one-method patch. If accepted: `beat_tracker_engine` config would need
`"v3"` to keep resolving (alias to the now-fixed v2, with a deprecation
log line) rather than break existing `config.toml`s outright; `_DETECTOR_VERSION`
would bump (real behavior change: v2 itself changes, not just which
class name is picked); worth a full session's worth of shadow-A/B
validation before flipping the default, mirroring how the original
v2→v3 shadow validation was done.

**7c. v1 as a second, cheap shadow — proposed, cost estimated as low:**
Today's shadow mechanism supports exactly one shadow engine
(`self._shadow_grid`) alongside the active one. Adding v1 as a *second*
simultaneous shadow (v3 active, v2 shadow as today, v1 as a new second
shadow) would need a second shadow slot mirrored from the existing
pattern (`self._shadow2_grid`, a second `beat_tracker_shadow2_engine`
config key, matching `_detector_snapshot()`/corpus fields). Given v1's
documented `<0.3ms/frame` cost, this is cheap to run for "a few training
sessions for some quick tests" as proposed — real implementation, not
yet started, parked for consensus alongside the v3-fold-into-v2
proposal above since both touch the same engine-selection code.

**7d. Priming, not overriding — already correct, confirmed against the
code, not a gap.** The distinction the owner drew ("listen to the
external sources but not trust them completely") already exists exactly
as designed: `prime_tempo()` (called from `_update_profile_recommendation()`'s
P0-B block when a fresh external, non-self BPM hint exists — e.g. from
dj-mixer-01's own independent analysis) sets the ACF's Gaussian prior
toward that value; it reweights candidates within the existing search
range, it does not clamp `_bpm_min`/`_bpm_max` or force-set `self._bpm`
directly. Strong local ACF evidence can still win against a primed
prior. This is architecturally distinct from — and unaffected by — the
one-way-flow cut, which specifically blocked the recommender's *own
genre inference* from writing back to the detector; external ground
truth like dj-mixer's analysis was never part of that cut and remains a
legitimate "listen, don't override" input.

## 8. Genre-fit-weighted candidate scoring (new idea, tempo-independent)

Owner's idea, added mid-draft: score the audio against the recommender's
*other* (non-tempo) genre-fit terms — `spectral_shape_fit`,
`centroid_fit`, `zcr_fit`, `onset_fit`, `vocal_fmr_fit`, `vocal_hnr_fit`
(all already computed every cycle for the recommender, per the session
scorecard's "Signal Activity" section) — and see whether the winning
genre there agrees with which raw ACF candidate is picked, using that
agreement as an extra weighting term on candidate selection.

**Why this is a different mechanism from what v3 already restricts, not
a re-run of the same bug:** the backward-flow problem `BeatTrackerV3`
fixes is specifically "genre inferred *from* BPM" feeding back to
correct BPM — circular, since tempo_fit (a recommender term) already
depends on the BPM reading. This idea is the opposite direction: use
**tempo-independent** timbral/spectral evidence (centroid, ZCR, onset
density, vocal formant/HNR — none of these depend on which BPM won) to
help disambiguate *between* multiple live ACF candidates at the moment
of picking, not to correct an already-decided value after the fact.
That distinction (tempo-independent evidence only) is exactly what would
need to hold for this to avoid reintroducing the same class of bug —
any term that itself depends on the current BPM reading (`tempo_fit`,
`top_cand_fit`) must be excluded from this scoring, or it's circular
again.

**Scope questions, not yet resolved:** (1) does this apply only
pre-lock (candidate disambiguation at cold start, same safe window v3
already uses for its own prime) or continuously (more powerful, but
reopens the backward-flow question this time for genuinely
tempo-independent terms — probably fine, but should be argued
explicitly, not assumed); (2) how is "agreement" scored — nearest
candidate to the winning genre's `bpm_hint_min/max` band, or a softer
distance-weighted term; (3) is this a candidate to fold into the real
next-gen v3 architecture directly (owner floated "v3 or pre-v3"), or
worth a small pre-v3 experiment first if the lift is genuinely small.
Given how much of the machinery already exists (all six fit terms are
already computed every cycle, per § 7a's scorecard data), a pre-v3 spike
restricted to the pre-lock window looks like the lower-risk way to test
whether it helps before committing it to the next architecture
generation.

## Summary of what's actually decided vs. still open

**Shipped this round:** `_timing_scale_from_bpm` neutral point fix
(128→114); `bpm_lock_gain_confidence`/`bpm_lock_release_confidence`
logging.

**Proposed, awaiting consensus before implementation:**
- Fold `BeatTrackerV3`'s fix into `BeatTracker` (v2) directly; retire the
  `v3` subclass name for reuse by the real next-gen engine (§ 7b).
- Add v1 (`BeatGridTracker`) as a second simultaneous shadow engine for
  a few test sessions (§ 7c).
- Per-song v1/v2/v3 agreement table with mixer-library + LLM external
  checks (§ 7a).
- Continuous (not just transition-triggered) phrase-clock logging, as a
  prerequisite for any rolling-window phrasing work (§ 5).

**Investigated, not yet resolved:**
- Why the raw comb-filter argmax wanders across a wide range on some
  real material (§ 6) — the 17:56 session is a strong real example to
  start from.
- Whether `_V2_LARGE_JUMP_PERSISTENCE_CYCLES`'s spread threshold (6.0,
  not the 25-cycle count) needs to move, pending § 6's outcome (§ 3).
- Whether `_BPM_LOCK_CONFIDENCE` (0.55) is too permissive specifically
  for a cold-start lock (§ 4).
- `beat_grid.py`'s lack of any real downbeat-phase re-anchoring
  mechanism (§ 5, "phase anchor").

**Rolling rear-view-mirror windows (4/8/16/32-beat):** real design work,
explicitly not for immediate integration per the owner — candidate uses
identified for both the persistence gate (§ 3) and phrase detection
(§ 5), serious enough to warrant its own follow-up planning doc once
scoped further.
