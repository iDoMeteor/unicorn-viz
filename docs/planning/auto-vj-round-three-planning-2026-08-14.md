# Auto VJ: Round Three Planning — Open Threads Toward Real v3 (2026-08-14)

Owner: unicorn-viz
Status: draft — capturing open design questions for the philosophizing
  days ahead per the owner's own framing ("we're going to continue on
  philosophizing about all this the next few days, planning some
  plans... keep a round 3 planning doc and once we reach consensus we'll
  knock it out and prepare for the real v3"). Shipped so far this round:
  `_timing_scale_from_bpm` neutral-point fix, `_V2_STARTUP_CONFIDENCE`
  `0.3 → 0.4`, `bpm_lock_gain_confidence`/`bpm_lock_release_confidence`
  logging, `long_candidate_spread`/`long_candidate_median` logging,
  continuous phrase-clock logging, `spectral_flux_smooth`/`bass_flux_fast`
  logging, a second shadow-engine slot (turned on in `config.toml`:
  `beat_tracker_shadow2_engine = "legacy"`), sub-lag peak interpolation
  gated behind `acf_peak_interpolation_enabled` (off by default — an A/B
  test in progress, see § 6), `_V2_LOCK_BAND_PCT` `0.16 → 0.08` (§ 10),
  and `BeatTrackerV3` retired/consolidated into `BeatTracker` (§ 7b).
  Everything else is still
  proposal-stage, marked as such inline.
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

**Correction once the full session was in hand.** The session was still
recording when the analysis above was written (the log kept growing
mid-draft). The complete session — 64.7 minutes, 3794 detector ticks —
shows the wrong `~76` BPM lock persisted for roughly **34 minutes**
(`t=38432` to `t=40508`), not the ~2.4-minute window the scorecard
happened to capture first. It self-corrected on its own, without any code
change, once a later real track change produced a new, internally
*stable* candidate that could actually clear the persistence gate (BPM
climbed `85.08 → 91.17 → 97.74` in three consecutive cycles right at
`t=40508.4` — a clean multi-cycle escape, not a gradual drift). The rest
of that 65-minute session (81 `mode_transition` events total) shows the
detector tracking a wide, plausible range of tempos afterward (roughly
100-155 BPM across several more tracks) without any comparable long
stuck period recurring. This matters for § 3 below: it means the
persistence gate *can* recover on its own given a genuinely stable new
candidate — the 17:56 track's raw candidates just never were stable
enough to qualify for ~34 minutes straight.

**What this session does *not* answer:** *why* the very first raw
candidate at cold start was `75.95` rather than something near the true
tempo, and *why* the raw comb-filter argmax bounces across such a wide
range (88-166) every cycle rather than repeatedly finding the same
competing value. § 6 below now has a concrete answer to the second
question. Not yet decided: whether this session gets packaged into
`garbage/` as originally planned, or held out as a labeled regression
fixture given how cleanly it demonstrates the premature-lock +
gate-can't-recover combination — owner's call.

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

**Tried to answer precisely from the real session log — hit a real
instrumentation limit.** The corpus logs at a coarse ~1 Hz decision-tick
rate; the real persistence check runs on raw per-ACF-cycle candidates at
~7.5 Hz. That means each corpus row is one sample of roughly 7-8 real
cycles that happened silently in between, so *reconstructing* the exact
25-cycle/3.3s window from the existing log necessarily undercounts real
cycle-to-cycle diversity — a rolling-window analysis over the logged
`last_tactus_fold` values (proxy for the raw candidate) showed 45-86% of
short (~3-6s) windows *would* have cleared spread thresholds from 6 up to
15 in the 17:56 session's stuck period, yet the real gate cleared **zero
times** in ~34 minutes. The two don't reconcile — the true per-cycle
picture is noisier than the coarse log can show, so no specific number
(8? 10? 15?) can be responsibly recommended from this data alone.

**Fixed properly instead of guessing at a threshold:** rather than widen
6.0 on a hunch, `BeatTracker.long_candidate_spread`/`long_candidate_median`
now cache the exact values `_estimate_tempo_acf()` already computes and
compares against `6.0` every evaluation — logged in `_detector_snapshot()`
starting this round (`_DETECTOR_VERSION` → `1.0.0-rc.24`). The next
session that hits this gate will have ground truth instead of a
reconstruction, and the threshold question can be answered for real
rather than approximated.

**Startup confidence raised as the interim mitigation.**
`_V2_STARTUP_CONFIDENCE` `0.3 → 0.4` (owner, this round) — the 17:56
session's cold-start candidate was accepted at `acf_conf=0.32`, barely
above the old `0.3` floor, and turned out to be the octave-family error
that started the whole 34-minute episode. `0.4` sits at the midpoint
between that incident's floor and the pre-2026-08-14 value (`0.55`) —
asks for slightly stronger first evidence before locking at all, without
fully reverting the original reasoning for lowering it (cheap early
self-correction). This doesn't touch the persistence window itself; it
targets the *other* real lever in this incident — how easily a wrong
lock forms in the first place, not just how hard it is to escape one.

**Two distinct knobs, only one touched this round:**

1. **Window length (25 cycles)** — trades reaction speed for stability.
   No evidence yet that it's too slow to matter in practice (the wobble
   fix and the 20-pair sweep both converged within a few seconds) — not
   touched.
2. **Spread threshold (6.0 BPM)** — not touched either, pending real
   per-cycle data from the new logging above. The 17:56 session's
   candidates spanned roughly 75+ BPM at the coarse sampling rate — likely
   still too wide to clear even a generous threshold — but per the
   instrumentation-limit finding above, that can't be stated with
   confidence from the existing log.

Both knobs stay where they are until a session with the new
`long_candidate_spread` logging gives real per-cycle numbers to reason
from.

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

**Are the phrase vars captured for training today? They are now — shipped
this round.** Was: only `phrase_bias_terms` (the per-term breakdown dict),
logged **only** at the moment of an actual `_mark_mode_transition()` call
— i.e. only when a transition fires, not continuously; `_bars_since_
phase_entry`/`_bars_since_track_start`/`_phrase_neutral_bars_left`
weren't in the regular per-tick corpus payload at all. Owner: "capture
them all!" as the opening move of a front-to-back pass over the whole
intelligence system. All three are now in `_sequence_director_fields()`
(`bars_since_track_start`/`bars_since_phase_entry`/
`phrase_neutral_bars_left`), continuous on every sequence-corpus row, not
just at transitions — a real prerequisite for any rolling-window
phrasing work is now in place. Not yet captured: which *role*
(HOLD/RISE/PEAK/FALL) was actually queried at a given tick — `_phrase_
bias(role)` is called inline at each decision site with an explicit role
argument, not read from a single persistent "current role" field, so
there isn't a clean scalar to log there without inventing one; left as a
follow-up if the rolling-window work needs it.

**Same front-to-back pass also found two unrelated logging gaps,
fixed the same way:** `BeatTracker.spectral_flux_smooth`/`bass_flux_fast`
(the two raw inputs `drop_score` is built from) existed as public
properties but were never logged — now in `_detector_snapshot()`
alongside everything else. Neither changes any decision logic; pure
observability, same as the phrase-clock fields above.

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

## 6. Raw comb-filter argmax wandering — root cause found, fix shipped behind an A/B flag

**The finding.** Every one of the 17:56 session's wandering candidates
(`120`, `133.33`, `139.53`, `142.86`, `146.34`, `150`, `153.85`,
`157.89`, `162.16`, `166.67`...) turns out to sit on a **consecutive
integer lag**, one sample apart, at the ACF's native `_V2_ENV_RATE=100`
Hz envelope resolution. Converting each back with `lag = 6000 / bpm`:
`50, 45, 43, 42, 41, 40, 39, 38, 37, 36` — ten values, all but one
literally adjacent integers. This isn't several genuinely distinct
competing tempo hypotheses; it's the *same* underlying periodicity
landing on different neighboring lag bins from cycle to cycle, because
at this material's true tempo the lag grid itself is coarse.

**Why it's coarse specifically in this range.** `BPM = 6000 / lag`, so
`d(BPM)/d(lag) = -6000 / lag²` — the BPM-per-lag-step granularity gets
*worse* the shorter the lag (the faster the tempo). At `lag=40` (~150
BPM), one lag step is **3.75 BPM**. At `lag=80` (~75 BPM, where this
session's wrong lock actually sat), one lag step is only **0.94 BPM** —
4x finer. This is the same phenomenon as the already-known 124-BPM
grid-split gap (`122.45`/`125.0`, a 2.55 BPM gap), just structurally
worse the faster the true tempo is, and it explains why the wrong lock
itself stayed comparatively stable (`75.95 → 73.63 → 74.41 → 72.95`, a
few-BPM drift consistent with 1-lag-step jitter at the *finer*
resolution down there) while the real, faster tempo it should have found
kept hopping across a wide BPM range at the *coarser* resolution up
there.

**Proposed fix: sub-lag (parabolic) peak interpolation.** A standard,
well-established DSP technique — after `_estimate_tempo_acf()` picks the
integer-lag `peak_idx`, fit a parabola through `score[peak_idx-1]`,
`score[peak_idx]`, `score[peak_idx+1]` and solve for the true (fractional)
peak location:

```text
delta = 0.5 * (score[i-1] - score[i+1]) / (score[i-1] - 2*score[i] + score[i+1])
refined_lag = lag[i] + delta        # delta typically in [-0.5, 0.5]
```

This recovers sub-sample precision from the *existing* comb-filter score
array — no new signal processing, no additional CPU cost worth
mentioning (three extra array reads and a division per cycle). It
wouldn't necessarily stop the argmax from jumping between genuinely
distinct integer lags when several are close in score, but it would make
each cycle's *reading* far more numerically continuous — two adjacent
lags that both represent essentially the same real periodicity (this
session's actual failure mode) would interpolate to nearly the same
refined BPM instead of jumping the full 3-4 BPM grid step between them.
That should tighten the persistence check's natural candidate spread at
high BPM specifically, which is exactly where § 3's `6.0` threshold
question is hardest to reason about today.

**Shipped, gated off by default, for a sequential A/B test.** Owner:
"we should test this very soon, we'll consider my next run the A for
this and the one directly after we'll do the B w/that fix." Implemented
in `_estimate_tempo_acf()`, applied once after every `peak_idx`
reassignment (raw-dominance override, tactus fold, density guard) has
already settled — refines the *reported* BPM without changing *which*
bin wins, so none of the existing accept/reject gate decisions change,
only the numeric precision of the value that clears them. Gated behind
`_V2_ACF_INTERPOLATION_ENABLED` (config key
`acf_peak_interpolation_enabled`), **default `False`** specifically so
run A (baseline) and run B (fixed) are two real, comparable sessions
rather than depending on commit timing. New
`acf_interpolation_delta_bpm` property/corpus field logs exactly how
much interpolation moved a given cycle's reading — `0.0` for the entire
A run (proof the flag was off), nonzero during B wherever it engages.
`_DETECTOR_VERSION` → `1.0.0-rc.25`.

**Flip it on for the B run:** `config.toml`'s `[auto_vj]` block has
`# acf_peak_interpolation_enabled = true` commented out, ready to
uncomment. Existing `acf_top_candidates`,
`long_candidate_spread`/`long_candidate_median` (§ 3), and the new
`acf_interpolation_delta_bpm` together should be enough to judge the B
run: whether the wandering candidates in a similar situation tighten up,
and by how much.

**Known open risk, not yet resolved:** this changes the numeric value of
every BPM reading, not just the wandering cases — all of today's tuned
gate-stack constants (lock-band %, persistence spread, jump-confidence
thresholds) were tuned against the current grid-quantized behavior.
`tests/test_beat_tracker_v2.py`'s existing convergence tests all still
pass with the flag off (the default they run under); a full test pass
with the flag forced on has not been done and may need re-baselining
before this could ever become the *default* behavior, even if the A/B
result looks good.

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

**Shipped this round.** Owner, after seeing the 100% agreement result
from § 11's live session: "yea let's consolidate v2/v3." `BeatTrackerV3`'s
guard folded directly into `BeatTracker.set_profile()`; the subclass
retired entirely. `beat_tracker_engine = "v3"` remains a working config
value — `_load_beat_grid_cls()` now resolves it to the same `BeatTracker`
class as `"v2"`, with a deprecation log line — so existing configs don't
break, and the name is free for the real next-generation engine. Pure
gain, no tradeoff given up: the behavior was purely additive to begin
with (never worse than v2's old always-reprime behavior, only prevents
the specific backward-flow case), and the A/B validation this
recommendation asked for had already effectively happened live.
`_DETECTOR_VERSION` → `1.0.0-rc.27`.

**Noted for later, not reopened now:** owner, same message: "blocking
genre re-priming after lock is an idea worth re-visiting when we get
back to recommender work." The behavior being retired here (a genre
profile freely re-priming the tempo prior even after a lock is
established) was removed as a *default* because it caused real
incidents when driven by the recommender's own inference — but the
underlying question of whether *some* controlled genre-driven re-priming
belongs back in the picture once the recommender itself is more mature
is explicitly left open, not closed off, for that future work.

**7c. v1 as a second, cheap shadow — shipped this round.** Today's shadow
mechanism previously supported exactly one shadow engine
(`self._shadow_grid`) alongside the active one. Added a second,
independent shadow slot (`self._shadow2_grid`, config key
`beat_tracker_shadow2_engine`, defaults empty/off) mirroring the existing
pattern exactly — its own `bpm_shadow2`/`confidence_shadow2`/
`shadow2_engine` fields in both `_detector_snapshot()` and
`_build_live_training_row()`, updated every frame alongside the first
shadow, independently configurable (e.g. `active=v3, shadow=v2,
shadow2=legacy` runs all three simultaneously). Given v1's documented
`<0.3ms/frame` cost, cheap to run for "a few training sessions for some
quick tests" as proposed. Not yet done: actually turning it on for a
training run and reading the results — that's the owner's call on when.
Still parked for consensus: the v3-fold-into-v2 proposal above (7b),
which is a behavioral change, unlike this pure-capability addition.

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

**Scope refinement (owner, this round): consult only when confidence is
already low.** Resolves scope question (1) below with a third option,
better than either original one: gate on **confidence, not lock state**
— only consult the tempo-independent genre-fit terms when `acf_conf` (or
the blended `confidence`) is already below some threshold, i.e. exactly
the situations where the primary evidence is ambiguous and a second,
independent signal is actually useful. This is a good fit for two
reasons: (a) it naturally minimizes backward-flow risk without having to
argue the continuous case is safe — when confidence is already high, the
genre-fit terms are never consulted at all, so they structurally can't
override good direct evidence; (b) it's a direct match for the 17:56
incident itself — the cold-start candidate that started the whole
34-minute episode was accepted at `acf_conf=0.32`, exactly the kind of
low-confidence moment this would apply to. Still open: the specific
threshold (candidate: reuse `_V2_STARTUP_CONFIDENCE`'s own value, so it
applies exactly at the moments evidence is already being treated as
marginal — or a separate, purpose-tuned threshold).

**Other scope questions, not yet resolved:** (1) whether this needs its
own lock-state restriction on top of the confidence gate above, or
whether confidence alone is a sufficient guard; (2) how "agreement" is
scored — nearest candidate to the winning genre's `bpm_hint_min/max`
band, or a softer distance-weighted term; (3) is this a candidate to
fold into the real next-gen v3 architecture directly (owner floated "v3
or pre-v3"), or worth a small pre-v3 experiment first if the lift is
genuinely small. Given how much of the machinery already exists (all six
fit terms are already computed every cycle, per § 7a's scorecard data),
a pre-v3 spike restricted to low-confidence moments looks like the
lower-risk way to test whether it helps before committing it to the next
architecture generation.

## 9. Full models config menu (deferred to rc2, not rc1)

Owner: add a real in-app config menu covering the full set of
selectable/tunable models — detector engine (`beat_tracker_engine`),
both shadow slots (`beat_tracker_shadow_engine`/
`beat_tracker_shadow2_engine`), and whatever the recommender/director
model selection looks like once it has more than one option — instead of
hand-editing `config.toml` for every engine/model change, which is where
all of this round's config changes (shadow2, the interpolation A/B flag)
currently live. **Explicitly scoped for rc2, not rc1** — this is a UI/
config-surface feature, not a detector-behavior fix, and shouldn't
compete with rc1 stabilization work. Not designed yet: where it lives in
the overlay/hotkey system, what "model" needs to mean generically enough
to cover detector engines today and whatever the recommender/director
gain later, and whether it's read-only (observability: "what's active
right now") or read-write (can actually flip an engine live without an
app restart — note `_V2_ANALYSIS_DOWNBEAT_CONFIDENCE_MIN`'s own field
comment: at least one existing detector constant is explicitly "not
hot-reloaded," so live-switching may not be uniformly possible across
every candidate setting without further work).

## 10. Minimum lock dwell time — new idea, grounded in a live session

Owner, watching a live 2026-08-14 19:45 session (`logs/autovj-20260813T194512.jsonl`,
v3 active + v2 shadow, interpolation flag correctly off — see below):
"totally started out right on point but collapsed quickly to sub 100
instead of mid 120s... moved back in to proper range... collapsed
again. maybe we do need some kind of minimum lock length to prevent the
churn, a standard musical amount.. like 16/32 bars?"

**The pattern, confirmed in the log.** In the session's first ~226
seconds (before any clear track-change silence gap), on what looks like
one track: BPM correctly reads `122.4` by `t=14`, climbs to `124.7` by
`t=26`, then drifts down to `100.3` by `t=34`, bottoms near `88.3` by
`t=59`, partially recovers to `112-117` by `t=110`, fully recovers to
`120.4` by `t=195`, then drifts back down to `105.3` by `t=228`. `bpm_locked`
toggled **38 times over the session's 11.9 minutes** (~1 flip every
19s). Session scorecard: lock `42.0%`, mean confidence `0.408`, reco
churn `1.95/min`, low-margin `60.7%` of recommender decisions — all
consistent with the owner's description, not an isolated glitch.

**Root cause is different from — and complements — everything fixed so
far.** The large-jump gate stack (persistence check, confidence
thresholds, `_V2_MAX_BPM_STEP`) only ever governs jumps **outside** the
lock band. It was actively engaging in this session
(`large_jump_persistence_reject_count` reached `1089`, `cleared_count`
reached `284` by session end — real, frequent evaluation, unlike the
17:56 session where it never cleared once) and doing its job on
genuinely large jumps. But the `122→88` collapse happened as a sequence
of **in-band steps**: e.g. `124.73 → 105.17` in one step is a `19.56`
BPM move, and under the *old* `_V2_LOCK_BAND_PCT=0.16`,
`124.73 * 0.16 = 19.96` — just barely *inside* the lock band, so it
cleared with **zero** extra scrutiny, no persistence check, no
confidence floor beyond the ordinary per-cycle minimum
(`_V2_MIN_UPDATE_CONFIDENCE=0.25`). Nothing in the gate stack resisted a
*sequence* of such individually-legal nudges accumulating into a large
net drift over tens of seconds.

**Partially addressed already, same round.** Owner: "let's change it to
8, now please." `_V2_LOCK_BAND_PCT` `0.16 → 0.08` shipped immediately
(§ "Full `_V2_*` gate/tunable inventory" above has the updated table) —
roughly halves the in-band allowance (now converging with the flat
`_V2_LOCK_BAND_MIN=10.0` floor around 125 BPM instead of nearly doubling
it), so more of what used to slip through ungated now has to clear the
large-jump gate stack instead. This directly shrinks the size of any
single in-band step, but does **not** by itself add a dwell-time/
persistence mechanism for the in-band case specifically — a sequence of
several now-smaller in-band nudges could still in principle accumulate
into a large drift. Minimum lock dwell time (below) remains a distinct,
not-yet-implemented idea for closing that residual gap, and gives the
16/32-bar question below a materially different (smaller, slower-moving)
starting point to test against than the pre-retune numbers.

**16/32 bars → revised to 8/16.** Owner: "32 bars too long... will test
8 & 16 first when we get there." Original 16/32 estimate was fit to the
*pre-retune* oscillation period (60-100s at the old, wider `16%` in-band
allowance); with `_V2_LOCK_BAND_PCT` now tighter, the natural drift rate
this mechanism would need to resist is already reduced, making a shorter
dwell window plausible. 8 bars (100-124 BPM) spans roughly `15-19s`; 16
bars spans `31-38s`. Test candidates when this gets implemented: **8 and
16**, not 32.

**Design sketch, not implemented — needs its own scoping pass, distinct
from a simple constant retune:**
- A bar-relative (not fixed-seconds) counter, most naturally hung off the
  same downbeat-firing mechanism `_advance_phrase_clock()` already uses
  (§ 5) — bars-since-lock, not seconds-since-lock, so it scales with
  tempo automatically the way the owner's original rolling-window idea
  (§ 5) also wanted.
- What it should actually restrict: candidates here (a) block ALL
  updates until the dwell elapses (too blunt — would also block a real
  fast track change for the same window); (b) block only **downward-
  drifting in-band updates** specifically, since the failure mode here is
  directional erosion, not noise in general; (c) require the SAME new
  direction to be confirmed by K consecutive dwell-checks before
  accepting the cumulative move, similar in spirit to the large-jump
  persistence check (§ 3) but applied to the in-band case that check
  doesn't cover at all today.
- Interaction with the large-jump gate needs to be explicit: a genuine
  track change is usually a jump big enough to clear the *existing*
  large-jump path already (which has its own, separate persistence
  logic) — a dwell timer should not add friction there. The risk is
  specifically making the *existing* lock too sticky to respond to a
  real large-but-just-inside-lock-band tempo change (e.g. a DJ's pitch-
  bent transition that lands within 16% of the outgoing track).

**Not implemented this round.** Real, well-grounded proposal (both the
mechanism gap and the 16/32-bar magnitude are supported by this
session's own data), but it's a new gate category, not a threshold
tweak — belongs in the same "propose, don't silently ship" bucket as § 6's
interpolation fix. Recorded here for the next design pass.

## 11. Live session check-in: v1/v2/v3, new captures, config status (2026-08-14, 19:45 session)

**Shadow2 (v1) is NOT present in this session.** Only `bpm_shadow`/
`confidence_shadow`/`shadow_engine` (v2) appear in every row;
`bpm_shadow2` never appears at all. `beat_tracker_shadow2_engine`
selection is read at `AutoVJController.__init__` time like the rest of
`self._cfg`, so it only takes effect on the next app restart — this
session was launched before that config change was picked up. **Next
restart will pick it up** and give the real three-way comparison.

**v2 vs v3: 100% identical across the entire session (638 compared
rows, mean/median/max diff all `0.000`).** Strong empirical confirmation
of § 7b's code-reading finding: `BeatTrackerV3` differs from `BeatTracker`
by exactly one overridden method (`set_profile()`), and the only
production call site that would ever exercise that difference (genre-
driven re-priming mid-track) was removed entirely at `_DETECTOR_VERSION`
rc.20 (the one-way-flow cut). With that call site gone, v3's guard is
currently pure defense-in-depth — verified now with real data, not just
by reading the code. Strengthens the case for folding v3's fix into v2
directly and retiring the subclass name for the real next-gen engine, as
proposed in § 7b.

**Interpolation flag confirmed correctly off:** `acf_interpolation_delta_bpm`
read exactly `0.0` on every single row — this session is a clean "A"
baseline. `config.toml` still has `acf_peak_interpolation_enabled`
commented out, ready to flip for the "B" run whenever the owner is ready
(§ 6).

**Everything else from this round's capture sweep is present and
populated:** `bpm_lock_gain_confidence`/`bpm_lock_release_confidence`,
`long_candidate_spread`/`long_candidate_median`,
`spectral_flux_smooth`/`bass_flux_fast` all appear on every row with
real (non-placeholder) values.

## Summary of what's actually decided vs. still open

**Shipped this round:** `_timing_scale_from_bpm` neutral point fix
(128→114); `_V2_STARTUP_CONFIDENCE` `0.3 → 0.4`; `bpm_lock_gain_confidence`/
`bpm_lock_release_confidence` logging; `long_candidate_spread`/
`long_candidate_median` logging (the persistence check's own median/
spread, previously computed and discarded); continuous phrase-clock
logging (`bars_since_track_start`/`bars_since_phase_entry`/
`phrase_neutral_bars_left`, every row, not just at transitions);
`spectral_flux_smooth`/`bass_flux_fast` logging; a second, independent
shadow-engine slot (`beat_tracker_shadow2_engine`, now turned on in
`config.toml` as `"legacy"` alongside the existing `"v2"` shadow);
sub-lag peak interpolation (`acf_interpolation_delta_bpm` logging),
shipped disabled by default behind `acf_peak_interpolation_enabled` for
a sequential A/B test; `_V2_LOCK_BAND_PCT` `0.16 → 0.08` (in-band step
size that was letting a ~20 BPM single-cycle drift through ungated);
`BeatTrackerV3` retired and consolidated into `BeatTracker` (confirmed
by 100% live-session agreement first). `_DETECTOR_VERSION` →
`1.0.0-rc.27`.

**Proposed, awaiting consensus before implementation:**
- Minimum lock dwell time — new gate category for the in-band drift gap
  `_V2_LOCK_BAND_PCT` alone doesn't fully close; candidates revised to
  **8 and 16 bars** (owner: "32 bars too long"), design sketch only (§ 10).
- Per-song v1/v2/v3 agreement table with mixer-library + LLM external
  checks (§ 7a) — the shadow2 slot needed for this now exists; the
  actual agreement-table logic doesn't yet.
- Genre-fit-weighted candidate scoring, confidence-gated (only consulted
  when `acf_conf` is already low — owner's refinement this round) using
  tempo-independent terms (§ 8).
- A full in-app config menu for detector/shadow model selection —
  explicitly scoped for rc2, not rc1 (§ 9).
- Controlled genre-driven re-priming after lock — explicitly the
  behavior just retired above, but owner asked it be noted as worth
  revisiting once recommender work resumes, not closed off permanently
  (§ 7b).

**Investigated and answered this round:**
- *Why does the raw comb-filter argmax wander?* Root cause found (§ 6):
  ACF lag-grid resolution coarsens sharply at higher BPM (`3.75` BPM per
  lag step at `150` BPM vs. `0.94` at `75` BPM) — the 17:56 session's
  "10 different candidates" were 10 consecutive integer lags, not 10
  competing tempos. Fix shipped behind an A/B flag, not yet the default
  (see above) — the A/B result itself is the next open question.
- *Would a specific spread threshold (8/10/12/15) have converged faster?*
  Answer: can't be determined responsibly from the existing ~1 Hz
  decision-tick log — it undersamples the real ~7.5 Hz per-cycle
  candidates enough that a coarse reconstruction and the real gate's
  actual behavior (zero clears in 34 minutes) don't reconcile. Fixed the
  instrumentation gap instead of guessing (§ 3).
- *Is v3 actually behaviorally different from v2 in production today?*
  No — confirmed empirically, not just by reading code: `100%` exact
  agreement across a full live session (§ 11), because the one call site
  that would exercise `BeatTrackerV3`'s guard was already removed at
  `_DETECTOR_VERSION` rc.20.
- *Why did a live session collapse from correct (~122 BPM) to sub-100 and
  back, repeatedly?* Root cause found (§ 10): in-band steps (inside
  `_V2_LOCK_BAND_PCT`) accumulate drift with zero gating — the large-jump
  gate stack only ever governs jumps *outside* the lock band.
  `_V2_LOCK_BAND_PCT` tightened same round (see "Shipped" above); a
  minimum lock dwell time remains a distinct, not-yet-implemented idea
  for the residual gap (§ 10).

**Still open:**
- **Minimum lock dwell time** — new gate category (§ 10), design sketch
  only, test candidates 8/16 bars, needs its own scoping pass before
  implementation.
- **The interpolation A/B result itself** — owner's next session is the
  A (baseline) run, the one after is B (flag flipped on via the
  commented-out `config.toml` line). Compare `acf_interpolation_delta_bpm`,
  `long_candidate_spread`, and `acf_top_candidates` between the two (§ 6).
- Whether `_V2_LARGE_JUMP_PERSISTENCE_CYCLES`'s spread threshold (6.0,
  not the 25-cycle count) needs to move — now answerable from real data
  once a session captures the new `long_candidate_spread` logging (§ 3).
- Whether `_BPM_LOCK_CONFIDENCE` (0.55) is too permissive specifically
  for a cold-start lock, distinct from the startup-confidence floor
  already raised this round (§ 4).
- `beat_grid.py`'s lack of any real downbeat-phase re-anchoring
  mechanism (§ 5, "phase anchor").
- Which phrase *role* (HOLD/RISE/PEAK/FALL) was queried at a given tick
  — not logged, since `_phrase_bias(role)` has no single persistent
  "current role" field to read (§ 5).
- The confidence-gate threshold for § 8's genre-fit consultation
  (candidate: reuse `_V2_STARTUP_CONFIDENCE`, or a separate value).

**Rolling rear-view-mirror windows (4/8/16/32-beat):** real design work,
explicitly not for immediate integration per the owner — candidate uses
identified for both the persistence gate (§ 3) and phrase detection
(§ 5), serious enough to warrant its own follow-up planning doc once
scoped further.
