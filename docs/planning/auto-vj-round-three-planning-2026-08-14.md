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
  test in progress, see § 3.1), `_V2_LOCK_BAND_PCT` `0.16 → 0.08` (§ 1.2),
  `BeatTrackerV3` retired/consolidated into `BeatTracker` (§ 3.2b), and
  three `library/c` LLM tuning recommendations applied:
  `_BPM_LOCK_RELEASE_CONFIDENCE` `0.28 → 0.3`,
  `phrase_under_over_hold_mult` `0.6 → 0.7`, and `kick_regularity_fit`
  `0.9 → 1.2` (§ 5.1). Everything else is still
  proposal-stage, marked as such inline.
Last updated: 2026-08-17 — round-three close-out batch implemented in
  one shot per the owner's instruction; see the "Round-three close-out
  (2026-08-17)" section immediately before the Summary for the item-by-
  item status. (2026-08-15: reorganized into nine phases — was mostly
  chronological, with a duplicate `§ 12` and a duplicate `§ 17.1`; folded
  in the 2026-08-15 live-chillstep tactus-fold finding (§ 8.7). No content
  was removed — see "How this document is organized" below and the
  verification note at the very end.)

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

## How this document is organized

Reorganized 2026-08-15 from its original mostly-chronological structure
into nine numbered phases, grouped by what kind of work each section
represents rather than strictly when it was written. Every section keeps
its original substance; only headings, numbering, and physical ordering
changed, plus one new section (§ 8.7) folding in a live finding from
tonight. Two pre-existing numbering collisions are fixed as part of this
pass, both purely cosmetic — no content affected:

- Two unrelated sections were both numbered `§ 12` (a `library/c`
  write-up and a separately-appended "audit cross-check" write-up). They
  now live at **§ 5.1** and **Phase 6** respectively.
- Two unrelated subsections were both numbered `§ 17.1` (the original
  "what changed since § 16.7" and a later-appended "synthetic sweep
  evidence" update). They now live at **§ 8.1** and **§ 8.5** respectively.

Every other old `§ N` cross-reference in the body text below has been
translated to the new numbering (old section → new phase.section); the
translation is mechanical and doesn't change what any reference actually
points to. One pre-existing loose end was left exactly as it was rather
than guessed at: two spots (§ 8.2's own heading, § 8.3's Option B
paragraph) contained an unfilled `(§ above` placeholder in the original
document with no section number ever supplied — preserved as-is rather
than invented, since fabricating a target would be a real content change,
not a formatting one.

Phase map:

- **Phase 1 — Live-Session Incidents & Findings**: real sessions that
  surfaced a problem, in the order they happened.
- **Phase 2 — Detector Gate & Tunable Reference**: the `_V2_*` constant
  inventory and the persistence-check/lock-floor deep dives.
- **Phase 3 — Shipped Fixes This Round**: the argmax-wandering root
  cause + interpolation A/B, and the v1/v2/v3 engine work.
- **Phase 4 — Proposals Awaiting Consensus**: ideas written up but not
  implemented (rolling windows, genre-fit scoring, models config menu).
- **Phase 5 — Library Packaging & LLM Scoring Runs**: `library/c` and
  `library/d`, and the LLM-tuning recommendations that came out of them.
- **Phase 6 — Audit Cross-Check Pass**: the point-by-point comparison
  against both formal audits.
- **Phase 7 — Study Pass Synthesis & v2-Final-Candidate Checkpoint**:
  the full audit-vs-reality reconciliation and the explicit "this is the
  v2 baseline" checkpoint.
- **Phase 8 — T5: Octave/Harmonic-Family Ambiguity**: the one audit
  finding with its own long arc — proposal, synthetic evidence, real
  142-track evidence, and tonight's live tactus-fold finding.
- **Phase 9 — v3 Roadmap**: items explicitly parked for the next
  architecture generation.
- **Summary**: rollup of shipped/proposed/open/investigated, kept at the
  very end and extended to cover Phases 7-9.

---

## Phase 1 — Live-Session Incidents & Findings

### 1.1 A real live example: the 2026-08-14 17:56 session collapse

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
  comfortably past `_BPM_LOCK_CONFIDENCE=0.55`. See § 2.3 below.
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
  This is real evidence bearing on § 4.1 below: the persistence *count*
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
  is a separate mechanism from the large-jump gate above. (See § 8.7 for
  a different, later session where this same mechanism stayed correct —
  its leniency dial doesn't explain that session's problem either, once
  checked properly — but where the raw comb-filter evidence at the true
  tempo turned out to be too weak even for the loosest setting of this
  gate to rescue.)
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
stuck period recurring. This matters for § 2.2 below: it means the
persistence gate *can* recover on its own given a genuinely stable new
candidate — the 17:56 track's raw candidates just never were stable
enough to qualify for ~34 minutes straight.

**What this session does *not* answer:** *why* the very first raw
candidate at cold start was `75.95` rather than something near the true
tempo, and *why* the raw comb-filter argmax bounces across such a wide
range (88-166) every cycle rather than repeatedly finding the same
competing value. § 3.1 below now has a concrete answer to the second
question; § 6.2 (audit cross-check) offers a testable candidate
mechanism for *both*. Not yet decided: whether this session gets packaged into
`garbage/` as originally planned, or held out as a labeled regression
fixture given how cleanly it demonstrates the premature-lock +
gate-can't-recover combination — owner's call.

### 1.2 Minimum lock dwell time — new idea, grounded in a live session

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
(§ 2.1's "Full `_V2_*` gate/tunable inventory" has the updated table) —
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
  (§ 4.1) — bars-since-lock, not seconds-since-lock, so it scales with
  tempo automatically the way the owner's original rolling-window idea
  (§ 4.1) also wanted.
- What it should actually restrict: candidates here (a) block ALL
  updates until the dwell elapses (too blunt — would also block a real
  fast track change for the same window); (b) block only **downward-
  drifting in-band updates** specifically, since the failure mode here is
  directional erosion, not noise in general; (c) require the SAME new
  direction to be confirmed by K consecutive dwell-checks before
  accepting the cumulative move, similar in spirit to the large-jump
  persistence check (§ 2.2) but applied to the in-band case that check
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
tweak — belongs in the same "propose, don't silently ship" bucket as
§ 3.1's interpolation fix. Recorded here for the next design pass.

### 1.3 Live session check-in: v1/v2/v3, new captures, config status (2026-08-14, 19:45 session)

**Shadow2 (v1) is NOT present in this session.** Only `bpm_shadow`/
`confidence_shadow`/`shadow_engine` (v2) appear in every row;
`bpm_shadow2` never appears at all. `beat_tracker_shadow2_engine`
selection is read at `AutoVJController.__init__` time like the rest of
`self._cfg`, so it only takes effect on the next app restart — this
session was launched before that config change was picked up. **Next
restart will pick it up** and give the real three-way comparison.

**v2 vs v3: 100% identical across the entire session (638 compared
rows, mean/median/max diff all `0.000`).** Strong empirical confirmation
of § 3.2b's code-reading finding: `BeatTrackerV3` differs from `BeatTracker`
by exactly one overridden method (`set_profile()`), and the only
production call site that would ever exercise that difference (genre-
driven re-priming mid-track) was removed entirely at `_DETECTOR_VERSION`
rc.20 (the one-way-flow cut). With that call site gone, v3's guard is
currently pure defense-in-depth — verified now with real data, not just
by reading the code. Strengthens the case for folding v3's fix into v2
directly and retiring the subclass name for the real next-gen engine, as
proposed in § 3.2b.

**Interpolation flag confirmed correctly off:** `acf_interpolation_delta_bpm`
read exactly `0.0` on every single row — this session is a clean "A"
baseline. `config.toml` still has `acf_peak_interpolation_enabled`
commented out, ready to flip for the "B" run whenever the owner is ready
(§ 3.1).

**Everything else from this round's capture sweep is present and
populated:** `bpm_lock_gain_confidence`/`bpm_lock_release_confidence`,
`long_candidate_spread`/`long_candidate_median`,
`spectral_flux_smooth`/`bass_flux_fast` all appear on every row with
real (non-placeholder) values.

### 1.4 Self-correction, mid-"C"-run: `_BPM_LOCK_RELEASE_CONFIDENCE` was backwards

Owner, partway through the overnight run: "i don't think c run is doing
as well as b run... it's def not doing as well." Checked live rather
than assuming: interpolation was already on (`94%` engagement, not the
cause). The actual cause — `_BPM_LOCK_RELEASE_CONFIDENCE`'s `0.28 → 0.3`
change from § 5.1 was backwards: raising the *release* floor narrows the
hysteresis band, making a lock easier to lose, contradicting its own
"stabilize" rationale. Confirmed against the live session: `71%` of its
lock-loss events happened at a confidence that would have survived
under the original `0.28`.

Owner: "let's try release confidence .25? .26? what's your math say?"
Backtested both against two real sessions' full lock-loss confidence
distributions (C: 30 events, B: 71 events) — `0.25` won both, and
matches `_V2_MIN_UPDATE_CONFIDENCE` exactly. Applied:
`_BPM_LOCK_RELEASE_CONFIDENCE` `0.3 → 0.25`. `_DIRECTOR_VERSION` →
`1.0.0-rc.6`.

`_BPM_LOCK_CONFIDENCE`'s own pending `library/d` recommendation
(`0.55 → 0.6`, the gain/acquire threshold, a different constant) stays
unapplied — owner: "let's just keep our eye on that over the next
couple runs and see if that recommendation changes." Watching only.

**Scope reminder, same message thread:** "we're not concerned w/
recommeder or director right now, we're focused on detector stuff
still" — recommender/director items from scoring reports get flagged,
not chased, while this phase stays detector-focused.

### 1.5 Lock band tightened from measured jitter; a real-scaling-function idea for the next architecture

`kick_regularity_fit` pulled back `1.2 → 1.0` per `library/e`'s LLM
report ("less correlated... in this session"), owner-approved directly.
The `0.25` release-confidence fix was verified live: the first full
session running it from the start hit the best numbers of the night
(lock `83.1%`, `2.45` toggles/min, `0.559` mean confidence).

**The "floor" hunch — investigated, not acted on.** Owner noticed
`_BPM_LOCK_RELEASE_CONFIDENCE` now equals `_V2_MIN_UPDATE_CONFIDENCE`
and wondered if the floor itself should drop too. Checked directly:
they gate different signals (blended `confidence` vs. raw
`acf_confidence` — the shared value is coincidence, not identity), and
in a healthy session `acf_confidence` was below `0.25` on only `3.1%` of
locked rows. Not a chronic bottleneck right now — flagged for re-check
on a rockier session rather than changed blind.

**Lock band tightened a second time, this time from first-principles
measurement rather than a single incident.** Owner: "do you think 8% is
still too large... what about the 10.0 floor, how do you think that is
performing?" Measured real cycle-to-cycle jitter directly (1440 samples,
healthy locked session): median `0.04` BPM, p90 `1.04`, p95 `2.3`, p99
`11.0`. The prior `0.08`/`10.0` band was still letting the top 1-2%
noise tail through completely ungated. Tempo-split the same data and
found the asymmetry the owner suspected: low-BPM material (chillstep,
this project's problem child) has *tighter* jitter (p95 `1.60`) than
high-BPM (`2.26`) yet the old flat floor gave it *more* relative slack.
Shipped: `_V2_LOCK_BAND_PCT` `0.08 → 0.03`, `_V2_LOCK_BAND_MIN`
`10.0 → 4.0`. `_DETECTOR_VERSION` → `1.0.0-rc.28`.

**Open design question for the real v3, not implemented tonight.**
Owner's closing question: "we should also consider, for round three,
having them scale in a proportional way with bpm range that we control
rather than letting them swing in just a random what other math happens
to be doing way." Exactly right about the current shape — `max(flat,
bpm*pct)` produces an emergent crossover (currently `133` BPM,
`4.0/0.03`) that nobody designed, it's just wherever two independently-
tuned numbers happen to intersect. Two design directions worth
comparing when this gets picked up for real:

1. **Derive it analytically from the ACF's own resolution.** The lag
   grid's BPM-per-step is `d(BPM)/d(lag) = -BPM²/6000` (at
   `_V2_ENV_RATE=100` Hz) — a known, closed-form function of BPM, not
   something that needs fitting. A band like `k * BPM² / 6000` (single
   constant `k` to tune) would be a genuinely continuous,
   mechanistically-justified curve instead of a two-piece `max()`.
2. **Fit a curve directly to real jitter-vs-BPM data** (this round's own
   measurement, extended across more sessions/tempo buckets) rather than
   assuming the analytical grid-resolution model is the whole story —
   real jitter includes onset-timing noise and material-dependent
   variance the pure grid-quantization model doesn't capture.

Either approach replaces two independently-chosen constants with one
deliberately-shaped function. Worth revisiting once interpolation (which
changes what "grid resolution" even means for the detector) is a settled
default rather than still being A/B tested in parallel — the two
questions are coupled, not independent.

**Shipped same night, logging only.** Owner's own addition: "we code
them both up but just log both for one session with everything else as
is, and see what we think of each." Both candidates now compute and log
every cycle a tempo is established — `lock_band_candidate_analytical`
(`k=1.0` lag-grid steps at the current BPM) and
`lock_band_candidate_empirical` (`3.0` BPM flat, from real jitter — an
OLS regression against tonight's own data found no clean BPM-dependence,
so this candidate directly tests whether the whole "scale with BPM" idea
even holds up empirically). `lock_band_bpm` also added, exposing the
real live value so all three sit on the same row for direct comparison.
**Neither candidate gates anything — the actual accept/reject gate is
unchanged**, still reading only `_V2_LOCK_BAND_MIN`/`_V2_LOCK_BAND_PCT`.
Data to review once the next overnight session (with everything else
from tonight also live) is packaged in the morning.

### 1.6 See also

The next live-session finding in chronological order — a 2026-08-15
chillstep session where `kick_regularity` turned out to make the
tactus-fold mechanism *less* willing to correct a doubled BPM, not
more — is mechanistically tied to the T5 octave/harmonic-ambiguity work
rather than to anything else in this phase, so it's written up at
§ 8.7 instead of duplicated here.

---

## Phase 2 — Detector Gate & Tunable Reference

### 2.1 Full `_V2_*` gate/tunable inventory (beat_grid.py)

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
| `_V2_ANALYSIS_DOWNBEAT_CONFIDENCE_MIN` | 0.30 | Floor for `is_downbeat` to actually fire (gates § 2.3's downbeat-confidence boost) |

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
| `_V2_STARTUP_CONFIDENCE` | 0.4 *(was 0.3, then 0.55 originally — see § 2.2)* | Cold-start floor (`self._bpm <= 0.0` only) — raised after a real session locked at `0.32` (barely above the old `0.3`) on a lower-octave error that took ~34 minutes to self-correct |
| `_V2_LOCK_BAND_PCT` / `_V2_LOCK_BAND_MIN` | 0.08 / 10.0 *(pct was 0.16 — see § 1.2)* | `max(10, bpm*8%)` = "normal" range; nothing below applies inside this band. Tightened after a live session showed a single in-band step (19.56 BPM at ~125 BPM) sliding through the old 16% ungated and driving a repeated collapse/recover pattern |
| `_V2_TEMPO_HOLD_S` | 10.0 | Now *only* feeds the `primed_confidence` floor in `prime_tempo()` — the gate that used to read this for hold-skip stickiness was removed entirely this session |
| `_V2_LOW_BPM_GUARD` / `_V2_FAST_BPM_GUARD` | 115.0 / 130.0 | "Low lane" ceiling / "fast lane" floor for the guard below |
| `_V2_LOW_BPM_FAST_CONFIDENCE` | 0.45 | Extra confidence required specifically for a low→fast lane crossing (was 0.80) |
| `_V2_LARGE_JUMP_CONFIDENCE` | 0.5 | Confidence required for *any* jump outside the lock band (was 0.72) — the primary gate a real track-boundary change has to clear |
| `_V2_MAX_BPM_STEP` | 5.0 | EMA step cap — even a fully-accepted jump arrives over multiple cycles, not instantly (was 3.0) |
| `_V2_LARGE_JUMP_PERSISTENCE_CYCLES` | 25 | See § 4.1 — separate, longer persistence window gating only large jumps |
| `_V2_ACF_INTERPOLATION_ENABLED` | `True` in this session's `config.toml` *(code default `False`)* | Sub-lag parabolic peak interpolation — see § 3.1. Refines the reported BPM to sub-grid precision after `peak_idx` is chosen; doesn't change which grid point wins. Root-caused a real wandering-argmax bug (10 "different" candidates that were actually 10 consecutive integer lags for the same periodicity) to ACF lag-grid coarseness at high BPM. A/B tested: the fraction of large-jump evaluations tight enough to clear the `6.0` spread threshold roughly doubled with it on (`8.5% → 19.9%`) |

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
`bpm_lock_release_confidence`, shipped this round, see § 2.3) so
`bpm_locked` can always be checked against the actual threshold it was
measured against.

### 2.2 Is 25 cycles too big for the persistence check? Define "cycle."

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
from. (§ 6.3: the spread threshold and § 3.1's interpolation flag are
coupled — sequence the decision after the B run, and see the
relative-threshold argument there before retuning `6.0` at all.)

### 2.3 `_has_bpm_lock()`'s own floor

Tracked starting this round (§ 2.1's director-level table, shipped
same-night): `_BPM_LOCK_CONFIDENCE` (0.55 gain) /
`_BPM_LOCK_RELEASE_CONFIDENCE` (0.28 release) now echoed in every
`_detector_snapshot()` row as `bpm_lock_gain_confidence`/
`bpm_lock_release_confidence`. Values themselves unchanged this round —
pure logging, per the owner's ask ("we probably need to keep our eye on
that floor we're kinda tuning right").

The § 1.1 session is a live illustration of why this floor matters: a
`0.66` blended confidence (comfortably past the `0.55` gain) triggered
`bpm_locked=True` one single cycle after the very first non-zero ACF
candidate landed — the downbeat-confidence term alone contributed `0.25
* 0.56 ≈ 0.14` of that 0.66, on a lock that turned out to be a real
octave-family error. Whether `0.55` is too permissive for a *cold-start*
lock specifically (as opposed to an already-established one regaining
confidence after a dip) is an open question worth its own investigation
once more sessions exist — not actioned this round.

---

## Phase 3 — Shipped Fixes This Round

### 3.1 Raw comb-filter argmax wandering — root cause found, fix shipped behind an A/B flag

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
high BPM specifically, which is exactly where § 2.2's `6.0` threshold
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

**A run complete, B run starting.** `logs/autovj-20260813T202616.jsonl`
(60.3 min, flag confirmed off the whole way — `acf_interpolation_delta_bpm`
read `0.0` on every row) is the A baseline, run on the same code as the
`_V2_LOCK_BAND_PCT` retune and `BeatTrackerV3` consolidation (both
shipped the same round, so A already reflects those two fixes, not
pre-round-three behavior): lock `68.6%` (up from `41.6%` on the
pre-retune baseline), mean confidence `0.513`, `57` single-cycle jumps
`>10` BPM correctly routed through the large-jump gate (`4492` rejects
vs. `1231` clears), v1 shadow2 data collected for the first time (huge
disagreement vs. v2/v3, `25.6` BPM mean diff — expected, v1 is the
deliberately simple engine). `config.toml` now has
`acf_peak_interpolation_enabled = true` (owner: "oh man, i thought that
interp flag was on.. turn it on and i'll start a new run") — the next
session is the real B run. Existing `acf_top_candidates`,
`long_candidate_spread`/`long_candidate_median` (§ 2.2), and the new
`acf_interpolation_delta_bpm` together should be enough to judge it:
whether the wandering candidates in a similar situation tighten up, and
by how much, against the A run's numbers above as the baseline.

**Known open risk, not yet resolved:** this changes the numeric value of
every BPM reading, not just the wandering cases — all of today's tuned
gate-stack constants (lock-band %, persistence spread, jump-confidence
thresholds) were tuned against the current grid-quantized behavior.
(§ 6.3 verifies the interpolated value does reach both persistence
deques — so the B run can genuinely move `long_candidate_spread` — and
proposes what to watch, split by BPM lane.)
`tests/test_beat_tracker_v2.py`'s existing convergence tests all still
pass with the flag off (the default they run under); a full test pass
with the flag forced on has not been done and may need re-baselining
before this could ever become the *default* behavior, even if the A/B
result looks good.

### 3.2 v1/v2/v3 BPM accuracy logging

**3.2a. Agreement logging (in scope for the next round, design accepted):**
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

**3.2b. Is it really just one factor between v2/v3? Yes — confirmed, not
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
from § 1.3's live session: "yea let's consolidate v2/v3." `BeatTrackerV3`'s
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

**3.2c. v1 as a second, cheap shadow — shipped this round.** Today's shadow
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
Still parked for consensus: the v3-fold-into-v2 proposal above (3.2b),
which is a behavioral change, unlike this pure-capability addition.

**3.2d. Priming, not overriding — already correct, confirmed against the
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

---

## Phase 4 — Proposals Awaiting Consensus

### 4.1 Rear-view-mirror rolling windows (4/8/16/32-beat)

Owner's proposal: keep rolling comparison windows of the last 4/8/16/32
beats, both to (a) potentially replace or supplement the flat
25-cycle/spread-6.0 persistence check in § 2.2 with something that adapts
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

### 4.2 Genre-fit-weighted candidate scoring (new idea, tempo-independent)

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
again. (§ 6.5 argues `onset_fit` belongs on the excluded list too —
onset density is refractory-shaped, and the refractory is BPM-fed.)

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
fit terms are already computed every cycle, per § 3.2a's scorecard data),
a pre-v3 spike restricted to low-confidence moments looks like the
lower-risk way to test whether it helps before committing it to the next
architecture generation.

### 4.3 Full models config menu (deferred to rc2, not rc1)

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

### 4.4 "Cheater mode" #1: manual mood-selector nudge as a production stopgap (2026-08-15)

Owner: "another cheat... when the vj changes the mood to <x>, the bpm
detector will heavily favor choosing bpms in that range, as a way to
solve that problem for production stream usage until we have enough
data to dial it in, get r3/v3 done, etc? i think we were moving in that
direction once, and kinda halfway there on the mood selector side."

**Where this actually stands today — further along than "halfway," in a
specific way.** `BeatTracker.set_profile()` (would reprime the tempo
search from a genre's `bpm_prior_mu`/`sigma`) still exists, fully coded
and still unit-tested directly — but its only production call site,
`AutoVJController._sync_grid_audio_profile()`, was **removed entirely**
as part of the one-way-flow cut (`weights-and-thresholds.md`'s
`_MIN_PROFILE_PRIOR_SIGMA` row: "effectively inert in production...
only its live wiring from the recommender is gone"). So right now,
genre/mood selection — manual *or* automatic — has **zero** live effect
on the BPM detector. Not gated, disconnected.

**Why it was disconnected, worth restating plainly since a new proposal
here needs to not reopen it.** Two real incidents (2026-07-18,
2026-08-12) where the *recommender's own automatic* genre guess fed
back into the tempo prior — genre inference partly depends on the
current BPM reading (`tempo_fit`), so that's circular: a wrong guess
could drag an already-correct lock toward the wrong genre's range over
minutes to hours. A hard `bpm_hint_min`/`max` search-range clamp was
also tried earlier and reverted, because a wrongly-applied profile
could permanently hide the true tempo from the search entirely (see
`set_profile()`'s own docstring, § 3.2b).

**Why a manual mood-selector trigger is architecturally different, not
the same bug in a new coat.** Both incidents share one root cause: the
trigger was an *inference*, not a genuine external decision. A human
explicitly picking a mood off the selector is categorically different
— it's not something the detector itself produced, it's real outside
information, the same category `prime_tempo()` already trusts for
dj-mixer's own per-track analysis (§ 3.2d — that path was never touched
by either incident or the cut). The safety property that matters is
narrow and enforceable: **the trigger must be a genuine manual action,
never the recommender's automatic profile switch.**

**Proposed design, not implemented:**

1. Re-wire *only* the manual hotkey path (`unicornviz/hotkeys.py`'s
   profile cycling, `AudioManager.set_profile()`) to feed the new mood
   into the detector. The recommender's automatic path
   (`auto_vj.py:4682`, `manager.set_profile(recommended_key)`) stays
   cut exactly as it is today — no exceptions, this is the one hard
   line the design can't blur.
2. Route it through **`prime_tempo()`**, not a revived
   `set_profile()` call — already-proven, already-safe machinery:
   confidence only ever raised not lowered, refreshes the tempo-hold
   window so the ACF's own continuity guards don't immediately fight
   it. `set_profile()`'s soft prior-reweight also still no-ops once
   `self._bpm > 0.0` (§ 3.2b), so it wouldn't even fire post-lock —
   exactly the situation where a live operator would want to intervene
   on an already-wrong lock. Feed `prime_tempo()` the best real raw ACF
   candidate (from `acf_top_candidates`, already computed every cycle —
   see § 8.7's evidence section for what this data looks like) that
   falls inside the newly-selected mood's `bpm_hint_min`/`max`, rather
   than blindly forcing the profile's central `bpm_prior_mu` — an
   audio-grounded correction, not a fabricated number.
3. No hard search-range clamp — same lesson as the reverted
   `bpm_hint_min`/`max` clamp attempt. This nudges, it doesn't cage.

**A concrete complication found while researching this, not yet
resolved:** `dubstep`'s own profile currently hard-codes a narrow
`bpm_hint_min=138`/`bpm_hint_max=142` band (comment: "keeps the ACF
locked to the produced tempo instead of folding down to the perceived
half-time pulse"), modeling only the "140 produced, 70 perceived"
half-time story. Owner, after actually listening through a full
dubstep set for the first time from a genre-analysis point of view
(§ Phase 5's `2hr-dubstep` entry, once packaged): "dub step *is* legit
70-100 AND 130-160 lol" — real, separately-produced tempo bands, not
just one produced tempo and its perceptual half-time illusion. The
`2hr-dubstep` session's own BPM distribution backs this up: 19.0% of
readings in 70-100, 50.9% in 130-160, both real mass, not noise (see
Phase 5). If mood-selector nudging is built against dubstep's *current*
hint band, it would actively fight roughly half of genuinely correct
dubstep readings. Worth widening `bpm_hint_min`/`max` (or moving to a
genuinely bimodal representation, if the profile schema can support
one) before this cheat mode would work well for dubstep specifically —
flagged here, not changed yet, pending the owner's review of the full
`2hr-dubstep` analysis.

**Status: proposed, awaiting owner input.** Not implemented. Owner:
"write it up... i'll have more input about it later."

### 4.5 "Cheater mode" #2: tap-tempo as a 30-second high-trust seed (2026-08-15)

Owner: "we recently built in a bpm tapper... so let's put it to work,
vj taps out a beat w/0 key.. and then hits enter while the tempo tapped
is displayed, we send that to the detector and have him highly weight
that signal and look for best match for next 30s while it tries to
lock in on what's going on."

**What already exists.** `Overlays.bpm_tap()` (`unicornviz/overlays.py`,
bound to KP 0 in `hotkeys.py`) is a real, working feature today — but a
pure HUD readout. It tracks tap timestamps, computes a BPM from the
retained consecutive intervals, and renders a top-right "TAP nnn.n BPM"
readout while `bpm_tapper_active()` is true (within `BPM_TAP_HOLD_S` of
the last tap). It has **no existing connection to the detector at
all** — the tapped value is currently display-only, thrown away the
moment the readout times out.

**Proposed design, not implemented:**

1. New binding: `Enter`/`KP Enter`, scoped to fire *only* while
   `bpm_tapper_active()` is true (so it doesn't collide with the many
   existing context-specific `SDLK_RETURN`/`SDLK_KP_ENTER` menu-confirm
   bindings elsewhere in `hotkeys.py` — those are all gated to their own
   menu/overlay modes already; this needs the same discipline, checked
   before those handlers claim the key).
2. On confirm, send the tapped BPM to the detector as an explicit,
   maximally-authoritative external hint — arguably *more* authoritative
   than the mood-selector nudge in § 4.4, since it's a literal real-time
   human tapping the actual beat, not a genre label. Same safety
   property as § 4.4 applies for the same reason: a human's real-time
   tap is genuine external ground truth, not the detector's own
   inference, so it doesn't reopen the backward-flow class of bug either.
3. **Genuinely new engineering, not a `prime_tempo()` reuse this
   time.** `prime_tempo()` is a one-shot nudge to the search prior for
   the *next* re-estimation cycle, then the tracker behaves exactly as
   it normally would from there. "Look for best match for next 30s
   while it tries to lock in" is a sustained, time-bounded *elevated
   trust window* — a different shape of mechanism. Needs a new
   `_tap_prime_until_t` (or similarly-named) timestamp field: for the
   30s after confirm, pin the Gaussian prior's mu tightly to the tapped
   value (much tighter sigma than any profile's, since this is a
   real-time human measurement, not a genre-level guess) and relax the
   normal gate stack's persistence/confidence requirements specifically
   for candidates near the tapped value, so a real lock can form fast
   without fighting the standard large-jump-persistence machinery built
   for the opposite problem (resisting spurious jumps). After the
   window expires (or once a stable lock forms within it, whichever the
   design favors), revert cleanly to normal profile-driven behavior —
   no permanent state change, no lingering bias past the window.
4. Same non-negotiable as § 4.4: this is manual-trigger-only by
   construction (there's no automatic path to a keyboard tap), so the
   circularity concern doesn't apply here at all — worth stating
   explicitly since it's the cleanest of the two proposals on that
   front.

**Status: proposed, awaiting owner input.** Not implemented. Owner:
"write it up... i'll have more input about it later."

---

## Phase 5 — Library Packaging & LLM Scoring Runs

### 5.1 `library/c` packaged: LLM score notably improved, two recommendations applied

Owner packaged the night's sessions into a fresh `library/c` set and
asked for a check: "llm score notably improved! i honestly didn't expect
that." Confirmed with a clean same-track before/after: "Thriller (Tim
Cosmos 2025 Rework) – Michael Jackson" scored `19.6%` lock coverage in
an old `garbage/d` bucket (2026-08-11, well before any of this round's
fixes) and `59.5%` on the identical file in `library/c` tonight —
roughly 3x, on genuinely harder material (18 tracks of mashups, extended
mixes, bootlegs, reworks) than the clean single-track reference sets
(`library/a`/`b`, `4.4/5` overall but `100%` lock coverage across every
track — an easy baseline, not a fair comparison point). `library/c`'s
own overall scores: detector `3.25/5` (lock stability `3/5`, up from
`garbage/d`'s `1/5` on comparable material), recommender `2.75/5`,
director `2.5/5`. The director's low "Build Quality"/"Opportunity
Usage" scores matched the already-known `drop_without_recent_build=47`
lint finding from § 1.3 — owner: "a lot of these dj tracks drop w/o
builds, no worries," so not treated as a real issue.

**Three of the scoring pass's four tuning recommendations now applied,
all owner-approved directly.** First pass: "let's go ahead and move the
lock release conf & phase under over as recommended, after we get into
library diversity we'll re-visit all the centroid stuff."

- `_BPM_LOCK_RELEASE_CONFIDENCE` `0.28 → 0.3` — LLM: "frequent lock
  changes suggest slightly tightening the release confidence to
  stabilize lock states." Director-scoped (`AutoVJController`).
- `phrase_under_over_hold_mult` `0.6 → 0.7` — LLM: "builds were rushed;
  slightly increasing this multiplier could smooth transition timing."
  Director-scoped. `_DIRECTOR_VERSION` → `1.0.0-rc.5`.

**Then, after being asked for the exact equation and current weight
table, reconsidered on the spot:** "let's bring it to 1.2, wth! i have
confidence in it as well and it's one of our newer additions, earning
it's way up the ladder!"

- `kick_regularity_fit` `0.9 → 1.2` in `_DEFAULT_RECO_WEIGHTS` —
  recommender-scoped. `_RECOMMENDER_VERSION` → `1.0.0-rc.14`.

**Deferred, not applied — explicitly for a later library-diversity
pass:** only the `hard_techno`/`house` spectral-centroid recalibrations
now remain (`centroid_mu` `2450→3700`/`2650→4000`). Not rejected, just
sequenced for later per the owner's own framing.

**Side note on attribution:** owner recalled `kick_regularity` as a
personal contribution and asked whether there's a "Jason" comment on it.
Checked directly — the codebase's only `Jason`-signed comments
(`beat_grid.py`) are on `downbeat_regularity` (a related but distinct
detector confidence-blend term), not on `kick_regularity_fit` (this
recommender term) or the shared `kick_regularity` measurement itself
(`_compute_kick_regularity()`). Reported as found, no comment added
without confirming which specific piece is meant.

Consistent with the project's advisory-only LLM-tuning policy — nothing
here was auto-applied by packaging; each accepted change was reviewed
and approved individually, same as every other constant change this
round.

### 5.2 `library/d` (the B run): interpolation A/B result, and a standing LLM-scoring caveat

Owner packaged the interpolation B run (`library/d`, session
`autovj-20260813T214252.jsonl`, 47.7 min) and asked for independent
analysis alongside the LLM report.

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

Interpolation engaged on nearly every cycle with small, bounded
corrections, and the fraction of large-jump evaluations tight enough to
clear the persistence gate roughly **doubled** (`8.5% → 19.9%`). Lock
stability, churn, and mean confidence all moved the same direction. LLM
scores were more mixed on the surface — detector `3.25/5` unchanged
("Lock Stability" dimension actually read `2/5` vs. `3/5`), but
recommender `3.0/5` and director `3.0/5` both improved from `2.75`/`2.5`
— the direct metric comparison above is the more reliable read on this
specific mechanism. `_V2_ACF_INTERPOLATION_ENABLED` stays `False` by
default pending the owner's own call, folded into the overnight "C" run
decision below rather than flipped on its own.

**LLM scoring standing caveat, added this round.** Owner: "we also need
a note for the llm scoring, that it is *possible* that our live bpm
detection is, or may become, more accurate than other methods... we're
not there yet, but we were close once." `essentia_note`
(training-kit-01's LLM prompt) extended: whenever `external_agreement`
stops being null in a future session (a real independent reference gets
wired in), the LLM must not assume the external reference beats the
in-house detector by default — treat a disagreement as an open question
unless the session's own data supports the detector being wrong.

**`library/d`'s own new tuning recommendations** (not yet reviewed/
applied — flagged for the owner): `tempo_fit` `2.0→2.2`, `centroid_fit`
`0.5→0.4`, `_BPM_LOCK_CONFIDENCE` `0.55→0.6`, plus two spectral
recalibrations (`house` `mean_zcr`, `chillstep` `mean_centroid_hz`).

**Next: an overnight "C" run**, owner's own framing — the first session
to combine every round-three change live together (tighter lock band,
consolidated engine, three applied LLM-recommended weight/constant
changes, interpolation on, v1 shadow2 all at once). (Its results are
covered in § 1.4/§ 1.5.)

### 5.3 `2hr-dubstep` packaged — first real dedicated-genre run since the two 2026-08-15 fixes, and dubstep's own hint band is too narrow

Owner deliberately chose dubstep for a dedicated 2-3 session run
following the `chillstep/a` investigation (§ 8.7) — the genre with the
strongest, most widely-known real-world octave-ambiguity reputation
(the "140 produced / 70 perceived" convention). First real validation
that both of the same day's production fixes actually work end to end:
`live-corpus-20260815T171241Z.jsonl` has 34 real rows (the `.env`
LLM-key fix and the live-corpus availability-gate fix, § "auto-vj-01"
`1.0.0-rc.86`, both landed *before* this session started), and a full
LLM report generated (`detector_score.md` etc. all present — the
missing-API-key bug from `chillstep/a` did not recur).

**Overall: healthy, unremarkable in a good way.** 144.25 min, 21,072
sequence rows. LLM: **4.0/5 overall** (Lock Stability, Tempo
Plausibility, Confidence Reliability, Musical Alignment all `4/5`).
Lock `86.3%`, tactus-fold reject `93.6%` — squarely inside the
94-99%-band established as the universal baseline in § 8.7's
cross-session table, not an outlier like `chillstep/a`. `kick_regularity`
mean/median `0.682`/`0.760` — also normal-range, not elevated the way
`chillstep/a`'s was. v1/v2 (shadow2) disagreement mean `21.94`, median
`16.56` — higher than the healthiest sessions in § 8.7's table but not
dramatically so, consistent with a genre known for real tempo ambiguity
without being a stuck-lock incident.

**The BPM distribution independently confirms the owner's own listening
call.** Owner, after listening through a full set from a genre-analysis
point of view for the first time: "dub step *is* legit 70-100 AND
130-160 lol." Real numbers back it up — **19.0%** of readings in
70-100, **50.9%** in 130-160, both substantial, genuine mass, not one
dominant band with noise around it (`105-125`, the gap between the two
real bands, is only `25.2%`, consistent with genuine transitional/
mixed content rather than the "everything piles into one wrong band"
shape `chillstep/a` showed).

**A concrete, actionable side-finding: `dubstep`'s own `AudioProfile`
can't see half of what real dubstep actually is.** `unicornviz/audio/
profiles.py`'s `dubstep` entry hard-codes `bpm_prior_mu=140.0`,
`bpm_hint_min=138.0`, `bpm_hint_max=142.0` — the tightest sigma
(`0.0218`) of the entire profile roster, deliberately narrow by design
("keeps the ACF locked to the produced tempo instead of folding down to
the perceived half-time pulse" — modeling only the "one produced tempo,
one perceptual illusion" story). Real session data says that's an
incomplete model of the genre: most of `2hr-dubstep`'s real BPM mass
falls well outside `138-142` in *both* directions. This plausibly
explains why the recommender almost never actually selects the
`dubstep` profile even on a dedicated dubstep set (`140` ticks out of
`21,072`, `0.7%` — `peak_time` and `chillstep` dominate instead,
`67.4%` and `25.4%`): `tempo_fit` for a profile whose hint band only
covers a sliver of the genre's real tempo range will usually score
poorly even on genuine dubstep audio. Directly relevant to § 4.4's
mood-selector cheat mode, which would inherit this same blind spot if
built against the profile's current values. **Not changed yet** —
flagged for the owner's review, consistent with validating a weight
against real data before touching it rather than assuming it was
tuned correctly (same discipline as everywhere else in this document).

### 5.4 `90m-hyphy` packaged — best-scoring session yet, and "Shake That Monkey" locked correctly for the first time

Owner: "hyphy set is packaged!... it wasn't actually all hyphy, it was
by hyphy artists but def dipped into just straight old school rap/r&b
stuff... but overall seemed pretty good." Tracklist confirms it — E-40,
Too $hort, Mac Dre, 8Ball & MJG, Keak Da Sneak: Bay Area hyphy plus some
Memphis-school rap, exactly as described, not a data problem.

**Best LLM score of any session analyzed this round: 4.75/5** (Tempo
Plausibility, Confidence Reliability, Musical Alignment all `5/5`).
Lock `98.4%` over 79.75 min, only 14 gain/14 loss events — very stable.
BPM median `102`, mostly `80-109` (14.5%/23.7%/32.3% across those three
buckets) — genuine old-school-rap/hyphy tempo territory. Tactus-fold
reject rate `89.4%` — a touch lower than the 94-99% baseline elsewhere
in this document (§ 8.7's table), meaning slightly more accepts than
usual; `kick_regularity` normal (`0.664`/`0.696`, not elevated the way
`chillstep/a`'s was). Both of the day's earlier production fixes held
up again here: 20 real live-corpus rows, full LLM report generated.

**"Shake That Monkey" locked correctly this time — the same track that
was confirmed wrong twice before.** This is the recurring character
from § 8.6 (`library/i`: session-median `133.0` vs. true `100`, a clean
4:3 fold, three-way-triangulated as wrong by ear/mixer/Essentia) and
`garbage/n` (reproducibility check, wrong again at `133.9`). This
session: **v2 (active) median `103.8` BPM, range `100.3-105.7`, locked
`509/509` rows** — correct, and tight. **v1 (shadow2, the simpler
engine) landed on `132.9`** — almost exactly the same wrong value v2
itself got stuck on twice before. Read together: the active engine is
not deterministically broken on this track (it can and did find the
right answer under the right conditions), while the simpler engine
independently discovered the *same* wrong alias — evidence the ~133
reading is a real, recurring feature of this specific track's audio
(the fast overlapping vocal cadence, per the owner's own § 8.6
description) that more than one algorithm can fall into, not an
implementation quirk unique to v2. Softens "reproducible failure" to
something more precise: a real coin-flip between two competing
periodicities that landed right this time. **Not yet folded into
§ 8.6** — owner wants to confirm the three sessions ran the same
`_DETECTOR_VERSION` first (the corpus didn't carry that field until
this session — see auto-vj-01 `1.0.0-rc.87`, shipped same day)
before treating this as a genuine same-code reproducibility data point
rather than an old-code-vs-fixed-code artifact.

---

## Phase 6 — Audit Cross-Check Pass (2026-08-14)

Added at the owner's request, cross-checking this doc against the two
audits (`docs/audits/2026-08-11-auto-vj-music-theory-audit.md`,
`docs/audits/2026-08-13-bpm-tempo-detection-audit.md`). Everything here
is the audit agent's own analysis, re-verified against `beat_grid.py` at
`_DETECTOR_VERSION 1.0.0-rc.27` (not against the older rc.8 the tempo
audit originally read) — the audit finding numbers (T1, T2, T4...) refer
to the 2026-08-13 doc. Comments only; nothing here is shipped.

### 6.1 Overall read

This round independently converged on, or directly implemented, several
of the audits' recommendations: § 3.1's interpolation *is* audit T1/R1
(and the A/B-flag discipline is better process than the audit asked
for); the strength/band-weighted phase coherence is T2's third
recommendation; the hold-skip gate removal and guard loosening address
T3's "confident lane changes crawl" finding — the 20-pair simulation
(4/20 → 20/20 converging) is exactly the plateau mechanism T3 predicted,
now measured. The v2/v3 consolidation and the instrumentation-first
stance on § 2.2's spread threshold are both sound. No objection to
anything shipped this round; the comments below are about what's still
open.

### 6.2 § 1.1's two unanswered questions — a testable candidate mechanism: the BPM-fed refractory (audit T4)

The analyzer's onset refractory is set from the tracker's own estimate:
`clip(0.70 * 60/bpm, 0.18, 0.50)` (`analyzer.py:392`), fed every frame
with the blended confidence, active whenever `confidence >= 0.5`. At the
17:56 session's `75.95` lock that clamps to **0.50 s — longer than the
true beat period of a ~120-150 BPM track (0.40-0.50 s)**. During every
high-confidence stretch, the analyzer was therefore suppressing roughly
every other true beat *at the source*. That one mechanism would explain
all three open observations at once:

- **Entrenchment** — the surviving, half-rate onset stream genuinely
  supports ~76 BPM; the evidence itself was being filtered into
  agreement with the wrong lock (same self-confirmation shape as the
  P0-A clamp removed in the 2026-08-04 round, one layer down).
- **Raw-candidate instability** — an irregularly-thinned pulse stream
  (which beats survive depends on onset timing jitter vs. the cooldown
  boundary) scatters comb energy across the harmonic family instead of
  concentrating it at one lag; the observed 88-166 wandering is that
  family. § 3.1's grid-coarseness finding is real and compounds it, but
  grid quantization alone predicts hopping between *adjacent* lags —
  the refractory thinning is a candidate for why the *whole family* lit
  up.
- **Why escape needed a track change** — only a silence gap or a new,
  stable periodicity could out-compete an onset stream being actively
  reshaped to fit the incumbent.

Honesty caveat: the feedback only engages at `confidence >= 0.5` and
falls back to the strength-scaled cooldown below it, so the starvation
was intermittent, not constant — this is a *candidate* mechanism,
not a confirmed root cause. It is cheaply checkable, though, twice
over: (a) offline, against the existing 17:56 log — during stuck
high-confidence stretches the per-row `onset_count` rate should ceiling
at ≈ 1/0.50 s = 2.0 onsets/s, an unmistakable signature; (b) live,
by logging the analyzer's active `_refractory_s` into
`_detector_snapshot()` (pure logging, same pattern as everything else
shipped this round).

**The targeted fix, if confirmed** (flag+confirm per standing policy):
suspend the BPM-fed refractory whenever the tracker's own candidate
evidence disagrees with the lock — e.g. while
`abs(long_candidate_median − self._bpm) > jump_limit` — falling back to
the strength-scaled cooldown. The state needed for that condition
exists precisely because of this round's `long_candidate_median`
logging work; the change is a few lines in the `set_expected_bpm()`
call path, and it closes the last self-confirmation loop the
2026-08-04 fixes left open.

**Bearing on § 1.2 (in-band downward erosion):** the refractory also
predicts the *directionality*. Every accepted downward in-band step
lengthens the refractory (`60/bpm` grows), which thins more true
onsets, which strengthens slower candidates — a positive-feedback
ratchet that only works downhill. That fits the observed pattern
(repeated collapses, always downward, never upward drift). The dwell
timer treats the symptom and is still worth having; the refractory
guard treats a cause. Recommend evaluating them together.

### 6.3 § 2.2 and § 3.1 are coupled: don't retune the spread threshold before the interpolation decision, then make it relative (audit T1)

The adjacent-lag BPM gap exceeds 4 BPM above ~155 BPM (5.04 at 174) —
so with interpolation off, grid jitter *alone* can hold
`long_candidate_spread` above thresholds in fast lanes, and the flat
`6.0` is also *relatively* stricter exactly where the grid is noisier
(6.0 BPM ≈ 8% at 75 BPM but 4% at 150). Two consequences:

1. **Sequencing:** any spread-threshold decision made from a session
   with the flag off will be invalidated by turning it on. Decide the
   interpolation default first; § 2.2's question second.
2. **Shape:** once interpolation settles, make both persistence
   thresholds **relative** (a % of the window median — ~3% is the
   starting candidate) rather than absolute BPM: the short window's
   `4.0` and the long window's `6.0` both currently encode a
   tempo-dependent strictness nobody chose.

Verified against rc.27 for the B run's sake: the interpolated value is
applied to `best_bpm` *before* both `_candidate_history` and
`_long_candidate_history` appends, so the B run can genuinely move the
spread numbers. What to watch: `long_candidate_spread` p50 split by BPM
lane (above/below ~140) — the interpolation should collapse the fast
lane's spread specifically; if it doesn't move there, something is off.

### 6.4 The phase-confidence "chronic ~0.30 cap" has a mathematical floor at 0.28 (audit T2)

With `_V2_PHASE_TOL = 0.14` (locked, not proposing a change), a
*completely random* onset-to-phase relationship lands in the ±14%
window `2 × 0.14 = 28%` of the time. Strength weighting doesn't move
that expectation (weights apply to hits and misses alike in a random
stream). So the observed ~0.30 cap on correct, locked stretches is
statistically indistinguishable from **zero usable phase information as
currently measured** — which is implausible for a genuinely locked
four-on-the-floor stretch, and turns the "separate, still-open
investigation" flagged at the blend re-tune into a sharper question:
either the strength-weighted on-beat fraction really is near-chance
(the off-beat-onsets hypothesis), or something mechanical is
mismeasuring phase error. One cheap discriminator: log the **signed
phase-error distribution** (median + IQR over the coherence window).
Median ≈ 0 with wide IQR → genuinely off-beat onset mix → the fix is
expectation-setting per genre. Median displaced from 0 → mechanical
(oscillator/onset timestamp skew) → fixable directly.

Two follow-ons, both cheap:

- Report phase confidence **chance-corrected**:
  `max(0, (hit_rate − 0.28) / 0.72)` — the number becomes a true 0-to-1
  quantity, and future `_V2_PHASE_TOL` changes stop silently moving the
  scale (each historical retune 0.18 → 0.12 → 0.14 moved the chance
  floor 0.36 → 0.24 → 0.28, contaminating before/after comparisons).
- `_BPM_LOCK_RELEASE_CONFIDENCE = 0.28`: under the old 0.5/0.5 blend
  this sat exactly on the phase chance floor; under the new
  0.65/0.1/0.25 blend the phase share is small, so the coincidence
  matters less — but restating both Schmidt constants in
  chance-corrected terms would make § 2.3's floor question well-posed
  instead of scale-dependent.

On § 2.3's cold-start half specifically: `downbeat_regularity` (0.25 of
the blend) measures self-consistency of the *just-established* grid —
at cold start it is incumbent-confirming by construction (a wrong lock
beats regularly against its own wrong grid). Candidate: exclude the
regularity term (or require the ACF term alone to clear the gain
threshold) for the first N cycles after a cold start, which is exactly
the 17:56 failure window without touching established-lock behavior.

### 6.5 § 4.2: exclude `onset_fit` from the "tempo-independent" term set

`onset_density` is shaped by the BPM-fed refractory (6.2) — while any
lock exists, onset density is *not* tempo-independent; a wrong slow
lock thins the onset stream toward slow-genre onset-density
expectations. The 17:56 session is consistent with this: the active
profile during the stuck period was chillstep. If § 4.2's
low-confidence-gated consultation includes `onset_fit`, a wrong lock
can recruit exactly the corroboration § 4.2 is designed to seek. Exclude
it alongside `tempo_fit`/`top_cand_fit` (or land 6.2's refractory
guard first, which weakens the contamination at its source).
`centroid_fit`/`zcr_fit`/`spectral_shape_fit`/`vocal_*_fit` are
genuinely tempo-independent and fine. Otherwise § 4.2's
confidence-gated design is well-scoped — the gate answers the
backward-flow concern structurally, as the doc argues.

### 6.6 § 4.1/§ 1.2: bar-relative counters, the missing anchor, and frame-rate coupling

The dwell timer (bars-since-lock) and the 4/8/16/32-beat windows both
count in bars — counting is phase-agnostic, so the missing downbeat
anchor (§ 4.1) doesn't block them. But any *phrase-aligned* use of the
same windows will need the anchor, and the audits' cheap causal option
fits this codebase: accumulate bass-band onset strength into the 4
`_bar_beat_count` phase bins and periodically rotate the counter so the
argmax bin is beat 1 (kick-on-the-one accent voting), with the mixer's
section hint syncing bar phase — not just the phrase clock — when
present. The offline half (auto `beat_offset`, item E in
`drop-ins/dj-mixer-01/docs/offline-analysis-accuracy-plan.md`) upgrades
the hint side of that for free.

Also, from audit F7, worth honoring while designing the new windows:
every existing smoothing constant is per-frame (the energy-history
deque is 240 *frames* with a `>= 2 s` age check — above ~120 fps the
check never passes and slope detection dies), so time constants shift
with render fps. New rolling windows should be specified in
bars/seconds and stepped on time, not frames — and the energy-history
deque itself is a small, self-contained fix in the same spirit.

### 6.7 § 3.2a: adopt the field's metric conventions for the agreement table

Recommend the per-song table report **Acc1/Acc2** (the MIREX
convention: within ±4% = Acc1; also counting 1/2×, 2×, 1/3×, 3× = Acc2)
and classify each disagreement as *octave-family* (ratio ≈ 2, 1/2, 3/2,
3/4, 4/3 — the 17:56 class) vs. *unrelated*. That split makes octave
errors a first-class number instead of folded into generic
disagreement, matches how every published tempo estimator is scored
(so the detector becomes comparable to the literature), and costs
nothing beyond the arithmetic. The GiantSteps EDM tempo set (public,
Beatport-derived; see the 2026-08-13 audit's Part I.4) is the
ready-made offline complement to the owner's own library. On the LLM
column: the planned lower weighting is consistent with standing owner
policy (LLM tempo recall is not audio ground truth); suggest recording
it as a *tiebreaker only*, never sufficient alone to mark a track
"verified."

### 6.8 Low-hanging fruit menu for round 3 (from the audits, smallest first)

Each line: what, size, which finding it discharges. Items marked ⚑
touch detector behavior and get flag+confirm per standing policy;
unmarked items are logging/reporting only.

1. **Log the analyzer's active `_refractory_s`** per snapshot row +
   run the onset-rate check against the existing 17:56 log — pure
   logging + one offline analysis; confirms or kills 6.2 before any
   behavior change.
2. **Signed phase-error distribution logging** (median/IQR per
   coherence window) — discriminates 6.4's two hypotheses; feeds the
   already-open phase-confidence investigation.
3. **Chance-corrected phase-confidence readout** — one formula in the
   reporting path (6.4); keeps future tol changes from moving the
   scale.
4. ⚑ **Refractory guard** — suspend BPM-fed refractory while
   `long_candidate_median` disagrees with the lock out-of-band (6.2);
   a few lines, closes the last self-confirmation loop.
5. ⚑ **ACF overlap normalization** — divide each `acf[i]` by
   `(n − lag)` (audit T6); one line, removes a structural few-percent
   tilt toward faster lanes present in every estimate.
6. ⚑ **Envelope pulse-strength clamp** — `log1p` or percentile-cap
   onset strengths at pulse-write time (audit T6); one line, stops a
   single freak transient from dominating the 8 s ACF window.
7. ⚑ **Relative persistence thresholds** — after the interpolation A/B
   decides (6.3); two one-line changes.
8. ⚑ **Cold-start blend guard** — ACF-only (or regularity-excluded)
   confidence for the first N cycles (6.4); directly targets § 2.3's
   open question.
9. **Acc1/Acc2 + octave-family classification in the § 3.2a table** —
   scorecard-side only (6.7).
10. **Time-bound the energy history** (240-frame deque → time-based)
    — small, prevents silent breakage on high-refresh displays (6.6);
    full dt-based smoothing can wait for the real v3.

Bigger, explicitly *not* round-3-sized, parked for the real v3 design:
bar-phase accent voting (6.6); and the observation that this round's
gate stack — persistence windows, jump confidence, dwell timers — is
converging, piece by hand-tuned piece, on what the literature's
standard architecture (madmom-style DBN: tempo states, one transition
prior, comb-score observations) expresses as a single small explicit
model. A pure-numpy HMM over quantized tempo lanes is buildable within
the no-dependency constraint and would replace seven interacting gates
with one tunable matrix; the 2026-08-13 audit's Part III item 7 sketches
it. If "real v3" means an architecture generation, that is the
strongest candidate frame for it.

---

## Phase 7 — Study Pass Synthesis & v2-Final-Candidate Checkpoint

Owner's closing request: study `docs/audits/2026-08-13-bpm-tempo-detection-audit.md`
and this doc's own Phase 6 audit cross-check, "do research if you want,"
update the docs, no deletions — while explicitly protecting tonight's
current point as the best candidate for a final v2 detector, distinct
from whatever "official v3" planning comes next. This section is that
study pass: read both documents in full, re-verified every finding
against the actual code at its current state (`_DETECTOR_VERSION
1.0.0-rc.28`, past both the lock-band tightening and the dual
candidate-logging work in §§ 1.2/1.5), tested one hypothesis directly
against real historical data where the data allowed it, shipped two
small logging additions the audit specifically proposed as the cheap
first step toward two of its findings, and did not touch anything
`_DETECTOR_VERSION`-affecting without confirmation — consistent with
the standing policy both documents already point back to.

### 7.1 The headline: independent convergence, both times

Both the interpolation fix (§ 3.1) and the "code both, log only" scaling
comparison (§ 1.5) were built *before* this study pass opened either
document — pure convergent engineering from tonight's own live-session
evidence, arriving at the same diagnosis (integer-lag quantization) and
the same fix (parabolic peak interpolation) as the audit's own T1/
Part III recommendation #1, ranked *first* by leverage-per-effort out of
seven. That's real, independent validation in both directions: the
audit's literature grounding (Percival & Tzanetakis interpolate; so does
Essentia) confirms tonight's fix was the standard move, not a one-off
guess, and tonight's own A/B data (persistence-gate clear rate roughly
doubling, `8.5% → 19.9%`) is a second, independent confirmation the
audit didn't have access to when it was written. Worth trusting this
alignment as a signal about the overall direction of tonight's work, not
just about this one fix.

### 7.2 Finding-by-finding status, re-verified against the current code

| Finding | Audit's read (rc.8) | Status now (rc.28) |
|---|---|---|
| **T1** — integer-lag quantization, spread-limit deadlock above ~155 BPM | Steady-state bias + structural deadlock at DnB/hardstyle tempos | **Addressed.** Interpolation (§ 3.1) fixes the bias directly; the persistence spread limit (§ 2.2/§ 1.2) is a separate absolute-BPM threshold the audit's own § 6.3 flags as needing to become *relative* once interpolation settles — genuinely still open, see § 7.3. |
| **T2** — phase-confidence 0.28 chance floor | `_BPM_LOCK_RELEASE_CONFIDENCE=0.28` sat exactly on it under the old 0.5/0.5 blend | **Severity reduced as a side effect, root cause still open.** The blend re-tune to 0.65/0.1/0.25 (done independently, for unrelated reasons, before this study pass) shrank phase's share of the composite from 50% to 10% — the coincidence "matters less" per § 6.4's own re-check. `_BPM_LOCK_RELEASE_CONFIDENCE` is now `0.25`, chosen empirically tonight by backtesting real lock-loss data (§ 1.4), not by reasoning about the raw number's meaning — which sidesteps the calibration problem rather than solving it. The raw signal itself is still uncalibrated; `phase_confidence_calibrated` (shipped this pass, § 6.4/6.8 #3) is the reporting-only fix, not a behavior change. Signed phase-error logging (6.8 #2, the sharper discriminator between "genuinely off-beat onsets" vs. "mechanical mismeasurement") is not yet built. |
| **T3** — incumbent-bias stack, confident lane changes crawl | Seven guards, two emergent behaviors (crawl + no-silence-transition weak case) | **Substantially addressed by different means than proposed.** The tempo-hold gate (one of the seven) was removed entirely earlier tonight — independently, before either document was read this pass — and the 20-pair sweep (4/20 → 20/20 converging) is exactly the plateau mechanism T3 predicted, now measured, per § 6.1. `_V2_MAX_BPM_STEP` also moved `3.0 → 5.0`. The audit's *specific* proposed mechanism (recommendation #4: bypass `max_bpm_step` entirely and snap straight to the candidate median when confidence is high and persistence holds) was **not** implemented — real transitions are demonstrably fast now anyway (a live ~25+ BPM drop into a slow track "handled smooth as butter" tonight), which lowers the urgency without closing the recommendation. Left open, lower priority. |
| **T4** — BPM-fed refractory self-confirmation loop | Candidate mechanism for lock entrenchment; not confirmed, cheaply checkable | **Logging shipped this pass** (`analyzer_refractory_s`, § 6.2/6.8 #1). Tried to test it directly against the original 17:56 stuck session's existing log and hit a real limit: the historical `onset_count` field is a single-frame instantaneous snapshot at the ~1 Hz corpus-tick rate, not an aggregatable rate — there isn't enough resolution in old data to confirm or refute the hypothesis retroactively, exactly why the audit proposed adding the logging rather than trying to force a read from what already exists. The next session that hits a stuck stretch will have real data. The targeted fix (suspend the BPM-fed refractory when `long_candidate_median` disagrees with the lock out-of-band) is un-implemented and correctly flagged ⚑ (touches live detector behavior) — hypothesis first, fix only if confirmed. |
| **T5** — no explicit octave policy, profile-mediated circularity for fast genres | 174 BPM's *default* prior actually favors the half-time fold (0.701 vs. 0.622); only the dnb profile being active saves it | **Fully open, not touched this round at all.** No code, no logging, no written policy. Worth flagging plainly: this is the one finding with zero round-three activity in any direction, and it's specifically about fast genres (DnB/hardstyle) that this whole night's work — heavily chillstep/house/mid-tempo-DJ-set-driven — never exercised. The mixer-store-ground-truth convention the audit recommends following (kick-level tactus, 174 for DnB) already exists as this project's designated ground truth elsewhere; writing it down for the tactus-fold path specifically is cheap and still pending. *(See Phase 8 — T5 got its own dedicated arc starting immediately below this study pass, including real evidence that arrived later.)* |
| **T6** — ACF overlap-length bias, unbounded pulse-strength leverage, EMA-alpha-near-floor, clock-epoch fragility | Four minor, independent findings | **All four still open.** None touched this round. Cheapest items on the whole menu (each audit-estimated at "one line") — see § 7.4 for sequencing. |

### 7.3 One thing the audit's own re-check (§ 6.3) says tonight may have gotten slightly out of order

Read carefully, § 6.3 makes a sequencing point worth restating plainly:
the persistence spread threshold (`6.0` BPM, § 2.2) and the interpolation
default (§ 3.1) are coupled, and **the interpolation decision should come
first**. § 1.2's lock-band tightening (`_V2_LOCK_BAND_PCT`/`_V2_LOCK_BAND_MIN`,
now `0.03`/`4.0`) was done from *measured jitter data* — which is sound
methodology on its own — but that measurement was taken from a session
running interpolation *on*. That's actually the right order for the
lock-band question specifically (interpolation was already decided as
"on for this session" by the time the jitter was measured). The
still-open piece is § 2.2's *persistence spread* threshold (`6.0`,
distinct from the lock band) — that one has not yet been revisited
post-interpolation at all, and per audit T1's own table, the
grid-quantization gap without interpolation exceeds `6.0` BPM above
~155 BPM (`155→153.85`/`160→157.89` adjacent-lag gaps are `4.05`/`4.27`,
compounding across a few cycles), which is exactly the kind of thing
that could still bind in a fast-tempo session. With interpolation on
this is far less likely to matter, but it hasn't been explicitly
re-checked. Recommend folding this into whatever review happens once
the interpolation A/B result itself is judged (§ 3.1) — same sequencing
principle, same open thread, not a new one.

### 7.4 v2-final-candidate checkpoint (protecting tonight's work from v3 planning)

Explicit checkpoint, per the owner's own instruction to reserve this
point as the best candidate for a final v2 detector: as of this entry,
`_DETECTOR_VERSION 1.0.0-rc.28`, `_DIRECTOR_VERSION 1.0.0-rc.6`,
`_RECOMMENDER_VERSION 1.0.0-rc.15`, `auto_vj.py __version__ 1.0.0-rc.79`.
Everything in Phases 1-5 of this document is validated, live-tested, and
shipped against real session data across an entire night's continuous
operation — this is not a proposal state, it's the current running
system. Nothing in this Phase 7 changes that baseline; every item in
§ 7.2's "still open" column and § 7.5's menu below is either pure
logging (already shipped, gates nothing) or explicitly flagged ⚑ and
unshipped pending confirmation. **Any future "official v3" design work
should branch conceptually from this checkpoint, not replace it** —
the HMM/DBN architecture direction (§ 7.6) is a genuinely different
generation, evaluated and built separately, with this checkpoint
remaining the deployed fallback/comparison baseline (the same role v1
plays today) until a v3 candidate has *its own* real-session validation
to match what's behind this one.

### 7.5 Remaining menu, re-prioritized after tonight's actual progress

§ 6.8's original 10-item menu, re-ordered by what's actually
still open after this pass (done items removed from the list entirely
per "no deletions" not applying to a *menu* — the original numbered
list stays intact in § 6.8 above; this is a fresh prioritization, not
an edit to it):

**Shipped this pass (pure logging):** #1 `analyzer_refractory_s`, #3
`phase_confidence_calibrated`.

**Still open, pure logging (safe, no confirmation needed):**
- #2 Signed phase-error distribution (median/IQR) — the sharper T2
  discriminator; natural next step once a session with real
  `phase_confidence_calibrated` data exists to look at.
- #9 Acc1/Acc2 + octave-family classification in the § 3.2a agreement
  table design.
- #10 Time-bound the energy-history deque (240-*frame* → time-based) —
  small, independent of everything else, prevents silent breakage on
  high-refresh displays.

**Still open, ⚑ flag+confirm required (touches live detector/director
behavior, not shipped, not asking for it here):**
- #4 Refractory guard (suspend BPM-fed refractory under disagreement) —
  gated on #1's data actually confirming T4 first, per the audit's own
  sequencing.
- #5 ACF overlap normalization (divide by `n-lag`) — one line, audit
  says "removes a structural few-percent tilt," cheap to simulate
  against corpus replays before shipping.
- #6 Envelope pulse-strength clamp (`log1p` or percentile cap) — one
  line, same cheap-to-simulate profile as #5.
- #7 Relative persistence thresholds — sequenced behind the
  interpolation A/B decision per § 6.3/7.3 above.
- #8 Cold-start blend guard (exclude `downbeat_regularity` for the
  first N cycles after cold start) — directly targets § 2.3's open
  question about `_BPM_LOCK_CONFIDENCE`'s own floor.

**Fully unaddressed, no logging or code either way:** T5's octave
policy (§ 7.2) — the single largest gap in tonight's coverage, simply
because tonight's sessions never exercised fast genres. Worth a
dedicated pass whenever DnB/hardstyle material is back in a training
run. *(Picked up starting in Phase 8, below.)*

### 7.6 The v3 roadmap question, synthesized

Both documents converge on the same answer independently: this
project's own dense gate stack (persistence windows, jump-confidence
thresholds, dwell timers, lock bands, tactus-fold ratios) is a
hand-built approximation of what the field's standard modern
architecture — a Dynamic Bayesian Network over quantized tempo states,
one explicit transition-cost prior, comb-filter score as the
observation likelihood (madmom's architecture; Ellis 2007's DP tracker
is the same idea one generation simpler) — expresses as a single small,
tunable model. The audit's Part III item 7 and this doc's own § 6.8
closing paragraph both name it as the strongest frame for "real v3" if
that phrase means an architecture generation rather than another tuning
pass. Concretely: a pure-numpy HMM over a discretized BPM lattice
(states = candidate tempos, transition cost = a hand-set or
data-fit matrix replacing today's seven interacting gates,
observation = the existing comb-filter score) is buildable within the
project's own no-heavy-dependency constraint (`beat_grid.py`'s own
docstring: "No librosa, no aubio"). This is **not proposed for
implementation now** — it's a genuine architecture-generation decision,
correctly scoped by both documents as bigger than a round-three tuning
pass, and it's exactly the kind of thing that should be designed against
the § 7.4 checkpoint as a known-good baseline to beat, not built in a
vacuum. Two smaller, real precedents already exist in this exact
direction inside tonight's own work if a smaller first step is wanted
before committing to the full HMM: `_V2_LARGE_JUMP_PERSISTENCE_CYCLES`
is already a discrete-state persistence rule in miniature, and the
dual-candidate lock-band logging (§ 1.5) already treats "what should this
threshold be, as a function of tempo" as a designed question rather than
an emergent one — both are small existing footholds toward the same
underlying idea. *(See also Phase 9 for the other v3-scoped roadmap item
from tonight, faster-than-real-time headless training — a separate,
infrastructure-side v3 thread, not an architecture question like this
one.)*

### 7.7 What I did *not* do, and why

No `_DETECTOR_VERSION`-affecting change shipped in this section — every
code change in this pass (`analyzer_refractory_s`,
`phase_confidence_calibrated`) is additive, reporting-only
instrumentation, following the same pure-logging exemption used all
night. Every ⚑-flagged recommendation from both documents is presented
as a menu item with its own rationale, not implemented — consistent
with the standing "flag + confirm before detector changes" policy both
documents independently point back to, and with the explicit request to
protect the current point as the v2-final candidate rather than risk it
chasing every open finding in one sitting. T5 (octave policy) in
particular was deliberately left completely alone rather than guessed
at — it needs real fast-genre session data this project doesn't have
from tonight, and guessing at a policy without that data would be
exactly the kind of unvalidated tuning this whole night's methodology
has been arguing against.

---

## Phase 8 — T5: Octave/Harmonic-Family Ambiguity

### 8.1 What changed since § 7.7

§ 7.7 above left T5 (no octave/harmonic-disambiguation policy)
deliberately untouched: "it needs real fast-genre session data this
project doesn't have from tonight, and guessing at a policy without
that data would be exactly the kind of unvalidated tuning this whole
night's methodology has been arguing against." That data has now
arrived — not from DnB/hardstyle as originally envisioned, but from a
different genre in the same failure category: reggae/dancehall's
one-drop groove, via an accidental 140 → 88 BPM (Shabba Ranks, "Steady
Man") transition in `garbage/m`. See the ADR's "Round Three, the
morning after (part three)" entry for the full diagnostic trace. The
short version: two real track-boundary transitions each froze the
published BPM for 100+ seconds, not from inactivity but from the
large-jump-persistence gate rejecting dozens of genuinely multi-modal
candidates every cycle — real, harmonically-related readings the raw
ACF kept finding, with no mechanism to prefer the true fundamental over
an alias.

### 8.2 What the persistence-cycles candidates (§ above) do and don't fix

Tonight's `_V2_LARGE_JUMP_PERSISTENCE_CYCLES_CANDIDATE_SHORT`/`_MEDIUM`
logging (10/15 cycles vs. the real 25) tests a *different* lever: how
often the window gets *evaluated*, not what it does with a genuinely
multi-modal candidate stream. A shorter window checks more often, which
should shorten the average wait for a "lucky" quiet stretch even under
the same ambiguity — but it doesn't change the fact that when a real
one-drop-style track offers 2-3 competing readings, *any* window size
is picking among them essentially by chance. It's a complementary,
already-shipped, zero-risk lever, not a substitute for the fix below.

### 8.3 Proposed fixes, ranked by scope

**Option A — reset the persistence window on acceptance (small, safe,
recommended as the first landing).** Currently, once the persistence
gate finally accepts a jump, `_long_candidate_history` (and now the two
candidate deques) keep whatever mix of old/new readings they already
had — a `deque(maxlen=N)` only replaces entries FIFO, so a freshly
accepted 88.44 still has to "outvote" leftover contamination for the
next `N` cycles. This is very likely why the *second* half of the
observed failure happened at all: after correctly landing on 88.44 and
holding it ~49s, the value crept back up through the same alias family
(93→108→115→...) rather than staying put. Clearing all three deques
(and their cleared/reject counters' *history*, not the cumulative
counters themselves) the moment a large jump is actually accepted would
give the newly-locked tempo a clean slate instead of an already-half-
contaminated window. Self-contained, no new signal needed, directly
testable with the exact logging infrastructure already shipped tonight
(compare reject-rate-after-acceptance before/after). This is the piece
I'd fold into round three now, pending the owner's go-ahead — it's a
few lines, mechanically obvious, and low-risk because it can only
*remove* stale evidence, never fabricate new evidence to accept a wrong
jump faster.

**Option B — track-boundary reset via the deferred track-reset
signal.** Directly addresses the "outgoing track's tail poisons the
incoming track" mechanism identified earlier this round (§ above, "an
explicit track-reset signal" — already discussed and *deliberately
deferred* by the owner this same session). Would compose naturally with
Option A (both clear the same deques, just on different triggers) but
depends on infrastructure the owner explicitly asked to hold off on.
**Not proposed for this round** — noting the connection so it isn't
re-discovered as a surprise whenever the reset-signal idea gets picked
back up.

**Option C — octave-fold the persistence window itself (large,
real T5 fix, NOT proposed for this round).** The architecturally
"correct" fix: before computing the window's spread/median, fold each
raw candidate toward the window's own dominant harmonic family (reusing
the comb-filter/tactus-fold machinery `_effective_tactus_ratio()`/
`_tactus_fold_accepted()` already use for single-candidate fold
decisions, but applied to clustering a whole window rather than one
candidate against the current lock). This is genuine new engineering,
not a constant retune: it needs a clustering step that doesn't exist
yet, and — critically — no way exists to backtest it against historical
sessions, because raw per-cycle ACF candidates were never logged (only
the coarse ~1s decision-tick snapshots survive). Any version of this
would need to ship as pure logging first (log what the fold *would*
have decided, same "compare before committing" discipline as
everything else this round) before ever gating on it, and would benefit
from a synthetic multi-modal-candidate test harness (the same style
already used to validate the tempo-hold-gate removal's 20-pair sweep)
rather than relying on real sessions alone. **Note added 2026-08-15,
corrected 2026-08-15 (later the same day — see § 8.7's own correction):**
§ 8.7 below turned out, after checking the actual code and the real
logged values rather than trusting a live read, to be a *confirming*
data point for Option C rather than a bug report against the reused
tactus-fold machinery itself — `_effective_tactus_ratio()`'s
`kick_regularity` dial worked exactly as designed and still couldn't
rescue the session, which is stronger evidence for Option C's premise
(the raw comb-filter score itself lacks strong evidence at the true
tempo) than a dial-calibration bug would have been. Worth reading
alongside this option regardless — just not for the reason originally
written here.

### 8.4 Recommendation: fold Option A now, hold B and C

T5 is real and large enough to matter — it just cost a real session two
multi-minute stalls in one set — but it is **not** large enough, as a
*whole*, to knock out in the final stretch of an already-long night
without proper testing infrastructure for the parts that need it
(Option C specifically). The right split: **Option A is small, safe,
and testable with what already exists — propose landing it this round,
pending explicit go-ahead** (per the standing "flag + confirm before
detector changes" policy). **Option B stays deferred** with the
track-reset-signal idea it depends on. **Option C is real-v3-adjacent
work** — it deserves its own dedicated session with a synthetic
multi-modal-candidate harness (extending the existing 20-pair
transition sweep pattern to cover *competing* candidates, not just a
single clean tempo change), not a rushed implementation against one
incident. This keeps the v2-final-candidate checkpoint (§ 7.4)
protected while still making forward progress on a finding that's now
backed by two real incidents in one session rather than a purely
theoretical audit flag.

### 8.5 Update: synthetic sweep evidence (2026-08-14, later still)

Owner: "run us a sim test across most of the bpm spectrum... expand the
test w/the distractors and run again." Built `drop-ins/auto-vj-01/tools/
bpm_sweep_sim.py` (saved for reuse, not a one-off) — a few simulated
hours of tempo changes across 72-182 BPM run through a real `BeatTracker`
in a tight dt-stepped loop, real time under two minutes. `--distractors`
adds a second, weaker onset train at 2x/0.5x/1.5x the target, the closest
a pure-synthetic harness can get to the real harmonic-ambiguity failures
found the same night.

Two results worth folding into the record:

1. **§ 8.2's persistence-cycles question, answered directly.** 10 vs.
   15 vs. 25 cycles are statistically indistinguishable across every
   metric tested (convergence rate, time-to-converge, final accuracy),
   with or without distractors. Real, controlled evidence — not just
   the real-session logging still accumulating — that the window size
   was never the lever for the `garbage/m` stalls; it only ever
   promised a modest, low-risk convergence-speed edge, exactly as
   flagged in the original write-up.
2. **The 3:2 (triplet) distractor is worse than either octave
   distractor**, not a lesser cousin of the octave case: 33.3% of
   segments never converged within their hold window at all (vs.
   ~9-12% for a 2x distractor, a 0.5x distractor, or no distractor).
   Octave errors are the textbook, well-studied case in the beat-
   tracking literature; this result says triplet/shuffle-feel ambiguity
   deserves at least equal billing in whatever Option C ends up scoring
   candidates against — a plain "check 2x and 0.5x" fold would miss the
   harder of the two failure modes this project has actually hit.

Caveat unchanged from § 8.3's own framing: a synthetic click train is
*more* harmonically ambiguous than real music (zero timbral distinction
between the true beat and its alias), so these failure rates are an
upper bound, not a real-world estimate — real sessions tonight showed
roughly 2-3 problem tracks per 20-30 track set, not 1 in 3.

### 8.6 Update: 142-track real Essentia comparison (2026-08-15) — the harmonic-family problem is broader than 2:1/3:2

Owner: "run essetia against the over-night run if you can please, and
report." Ran the (now-fixed, see the `training-kit-01` essentia-loader
entries in `docs/adr/vj-system.md`) real extractor against every track
in `library/i` (10.1 hours, 142 unique tracks, 100% real local file
paths via media-01). 100% extraction success.

**Aggregate:** median disagreement between our detector's session BPM
median and Essentia's offline read is a tight **1.75 BPM** — most of the
library agrees closely. Mean is **5.18 BPM**, pulled up by a real
minority tail, not spread evenly. 51.4% agree within 2 BPM outright.

**The surprise:** correcting for the octave/triplet ratios (2:1, 1.5:1)
this whole document has focused on moved the "within 2 BPM" figure by
*zero* tracks (73/142 both ways). The real disagreement tail isn't
mostly octave/triplet confusion. Manually checking the worst
disagreements found several clustering near **5:4 (1.25×)** and a clean
**4:3 (1.33×)** instead — ratio families this write-up hadn't been
watching for at all. Whatever Option C ends up scoring candidates
against needs to cover this wider family, not just powers of 2 and 3:2.

**A confirmed, three-way-agreed ground-truth miss.** Two tracks —
"Shake That Monkey (Nylze Edit)" and "Doo Wop That Thing (Nylze Edit)"
— are a clean case, not an ambiguous one. Owner, from direct listening
and dj-mixer-01's own independent stored analysis: both are genuinely
**100 BPM** ("mixer agrees w/us, def 100bpm"). Essentia read 99.8 and
100.0 — dead on. Our live detector's *session median* landed at 133.0
and 133.3 — almost exactly **4:3** of the true tempo, on both tracks,
from the same editor. Owner's own diagnosis of the mechanism: both have
"complex overlapping vocals [that] are much faster than the beat" with
bass hits concentrated at the very beginning and end of each track —
long stretches with no strong bass-region anchor at all, just a fast
vocal cadence for the comb filter to latch onto instead. (Aside from the
owner, independently: "messes up some of the projectM visualizers too"
— this track's audio characteristics confuse more than one downstream
analysis.) This is the single most confidently-wrong result found all
night — not a genuinely ambiguous track like "Endlessly," a real miss
with three independent sources (ear, mixer, Essentia) agreeing against
the live detector's own session-median reading. Confirmed reproducible,
too: the same track locked onto the identical wrong ~133 BPM value in a
second, completely separate isolated re-test packaged into `garbage/n`
the following day — not a one-off.

**The rest of the worst-disagreement list turned out to be mostly real
musical complexity, not detector failure** — owner's own close-listening
notes on each:
- **"Ring My Bell" (152.8 vs. Essentia 123.9):** genuinely complex —
  comes in via a 125 transition into a congo/bongo-heavy percussion
  section that pushes the *owner's own tapped tempo* up to ~130 during
  that section (raw detector read as high as 140 there), before the
  track settles into a bass/synth section "w/o so much congo/bongo" at
  low-mid 120s — right where Essentia's 123.9 sits. Real, first-ever
  confirmed evidence for the "bongos/congos messing us up" hypothesis
  from earlier the same night — not a joke, an actual measured effect,
  though notably it pushed the owner's *own ear* around too, not just
  the algorithm.
- **"Fluid" (150.8 vs. Essentia 122.1):** owner describes a "solid
  120-123" track with a breakdown dipping to 113 (recovers slowly, and
  "seems stuck there" the second time it's played — an inconsistency
  matching the reproducibility question flagged earlier this round) plus
  a "complex secondary 128 bpm overlap" in the second half. Essentia's
  122.1 matches the described steady-state well; the live detector's
  150.8 doesn't correspond to anything the owner describes hearing at
  all — this one reads as a genuine miss, not explained by musical
  complexity the way "Ring My Bell" was.
- **"Take My Pain Away" (151.8 vs. Essentia 124.0):** owner describes
  "solid bass intro around 120" into "vocal driven mid 120s," then
  "mostly solid 120" for the rest, despite "complex vocals most of the
  song." Essentia's 124.0 matches closely; 151.8 again doesn't match
  anything described — another likely genuine miss.
- **"Last Night X I Want It That Way" (mashup, 128.0 vs. Essentia
  102.0):** the owner's most detailed note describes a track that
  genuinely has three real tempo layers — a "distinct 100 bass kick,"
  a "sub-beat overlay around 120" in places, and a "mids driven 130bpm"
  outro after a complex non-bassy climax and a separate bassy breakdown.
  Essentia locked onto the clearest layer (the distinct 100 kick); the
  live detector locked onto a different, also-real layer (the ~120/130
  region). Owner: "doing pretty good this run right now... not sure
  about last night" — this is the "Endlessly" pattern again: a track
  that doesn't have one correct answer, not a failure on either side.

**Methodological note the owner flagged separately, worth recording:**
last night's session ran with crossfade off entirely — hard cuts between
every track, "the first time in a long time.. if ever" — so none of this
comparison is contaminated by the auto-mix/crossfade-bleed confound
found in `90m-house-deep-classic-peak/b` earlier tonight. `library/i`'s
142-track comparison is about as clean a per-track accuracy read as this
project has produced so far.

**Net effect on the T5 proposal (§ 8.3):** Option C (comb-filter
harmonic-family scoring for the persistence window) now has a much
richer, real target — not just 2:1/1.5:1, but 4:3 and 5:4 too — and one
confirmed, triangulated example (Shake That Monkey / Doo Wop That Thing)
of exactly the failure shape it would need to catch: a long vocal-heavy,
bass-sparse stretch where the comb filter has nothing strong at the true
tempo to anchor to. Still not proposed for implementation this round —
this sharpens the target, it doesn't change the recommendation to build
it as its own dedicated session with a synthetic multi-modal-candidate
harness (now including 4:3/5:4 distractors alongside 2:1/1.5:1 in
`tools/bpm_sweep_sim.py`) rather than rushed against one incident.

### 8.7 Update: live chillstep session, corrected — `kick_regularity`'s dial was working as designed; the real story is a comb-filter evidence gap, not a leniency bug (2026-08-15)

Owner, live: "i'm playing chillstep right now, very low solid bpm...
not overly complex, seems we're running just about double most of this
whole run & previous unpackaged short run as well..i restarted to turn
on my published bpm smoothing.. didn't help ;)" — a doubled-BPM read on
genuinely simple, low-tempo material, and a config change that
(correctly, since it only smooths what's already published) didn't
touch the underlying wrong value.

**Correction, same day, after checking the actual code and the real
logged numbers instead of trusting the live read.** The version of
this entry first written during the live session (see git history)
described `kick_regularity` as making the tactus-fold threshold
*stricter* the more regular the kick read, backwards for this content.
That got the mechanism's direction wrong. Reading `_effective_tactus_
ratio()` directly:

```python
def _effective_tactus_ratio(self) -> float:
    kr = max(0.0, min(1.0, self._kick_regularity))
    return min(1.0, self._tactus_preference_ratio + (1.0 - kr) * _TACTUS_KICK_REGULARITY_SPREAD)
```

with `_tactus_preference_ratio` (baseline) `= 0.55` and
`_TACTUS_KICK_REGULARITY_SPREAD = 0.30`: at `kick_regularity == 1.0`
the ratio sits at its most *lenient* value, `0.55` (the docstring's own
words: "Never makes folding *more* eager than the baseline" — baseline
**is** the eager end). At `kick_regularity == 0.0` it rises to the
*strictest* value, `0.85`. High regularity makes folding **easier**,
not harder — the opposite of what the live entry claimed.

**Verified empirically against `chillstep/a`'s own corpus, not just
re-read from code.** `effective_tactus_ratio` and `kick_regularity`
correlate at **exactly −1.000** across all 1024 rows — the formula
behaving precisely as coded, no surprises. `chillstep/a`'s median
`effective_tactus_ratio` was **0.585** — the *most lenient* of every
session checked (see the cross-session table below) — precisely
because its `kick_regularity` was the *highest* of the sample. The
tactus-fold threshold was as forgiving as it ever gets, and it still
rejected 94.7% of fold attempts. That can only mean one thing: the raw
comb-filter score for the true (lower) tempo was persistently and
substantially weaker than the score for the locked (doubled) tempo —
even a permissive 55-58% bar couldn't clear it. This is a comb-filter
*evidence* gap, not a threshold-calibration bug.

**Cross-session comparison, requested by the owner ("investigate the
tactus fold rejection rate from the last few sessions").** Pulled
`last_tactus_fold`/`kick_regularity`/`bpm_locked` from every recent
packaged session with a real corpus:

| Session | rows | reject % | `kick_regularity` mean/median | lock % | bpm median |
|---|---:|---:|---|---:|---:|
| `45m-chillstep/a` | 5,342 | 94.1% | 0.642 / 0.703 | 95.3% | 116.6 |
| `90m-house-deep-classic-peak/b` | 12,608 | 98.9% | 0.660 / 0.732 | 99.9% | 125.8 |
| `60m-hard-techno-hard-style-and-dnb/a` | 17,384 | 93.9% | 0.670 / 0.760 | 98.9% | 145.1 |
| `garbage/n` | 3,324 | 96.1% | 0.566 / 0.606 | 99.7% | 122.3 |
| `chillstep/a` (this session) | 1,024 | 94.7% | **0.777 / 0.884** | **84.5%** | 123.1 |
| `library/i` | 83,483 | 95.9% | 0.652 / 0.715 | 98.8% | 127.1 |
| `library/h` | 11,406 | 95.8% | 0.681 / 0.754 | 97.0% | 129.7 |
| `library/g` | 60,926 | 96.5% | 0.664 / 0.716 | 99.5% | 128.1 |

**The headline: a ~94-99% tactus-fold rejection rate is the universal
baseline, not a chillstep-specific symptom.** Every session sampled —
house, hard-techno/DnB, mixed libraries, and even the *other* chillstep
session (`45m-chillstep/a`, which locked fine at a plausible-looking
116.6 BPM, 95.3% lock) — sits in the same 94-99% band. Treating the raw
reject-rate number alone as evidence of a chillstep problem, which the
original live read implicitly did, doesn't survive a same-metric
comparison against sessions that behaved normally.

**What actually is distinctive about this session:** it has both the
*highest* `kick_regularity` (0.777/0.884 vs. ~0.57-0.68 mean elsewhere)
and the *lowest* lock stability (84.5% vs. 95-99.9% everywhere else) of
the whole sample — and, per the corrected mechanism above, high
`kick_regularity` should have made this session's fold-acceptance the
*easiest* of the eight, not the hardest. It's the most likely candidate
to have self-corrected on threshold grounds and didn't. That combination
— maximally lenient gate, still stuck — is a cleaner, harder data point
for T5's underlying claim than a calibration bug would have been: some
tracks give the comb filter nothing strong to anchor to at the true
tempo, so no threshold setting (however permissive) recovers it. Likely
mechanism, unchanged from the original live read and still just a
hypothesis: chillstep's half-time-feel snare/clap layer produces a
loud, regular onset pulse that dominates the comb filter's evidence,
while the true sub-bass pulse — felt more than sharply hit — contributes
comparatively weak periodicity energy. High `kick_regularity` in this
case is a *symptom* of being locked onto that louder, cleaner (wrong)
layer, not an independent cause of anything.

**Owner's response, still apt under the corrected reading:** "kick
regularity is *regular* just not fast ;)" — the kick genuinely is
regular, just regular at the wrong (doubled) rate. What's revised is
*why that mattered*: not because regularity made the gate stricter, but
because it made the gate as loose as it gets, and the true tempo's raw
evidence still couldn't clear even that low bar.

**Reclassified: this is now evidence for Option C (§ 8.3), not a
tactus-fold-dial bug report.** Joins "Shake That Monkey"/"Doo Wop That
Thing" (§ 8.6) as a second, independently-sourced example of the exact
failure shape Option C would need to catch — a track where the comb
filter has nothing strong at the true tempo to anchor to. No new fix is
proposed here: the previously-floated idea (retune or redesign the
`kick_regularity` leniency dial) is **retracted** — the dial isn't the
bottleneck, so there's nothing there to fix. This strengthens the
existing recommendation (§ 8.4) to build Option C as its own dedicated
session with a synthetic multi-modal-candidate harness, rather than
opening a new, narrower proposal.

**Follow-up question, answered with real numbers: would raising raw
ACF's weight help?** Owner: "are you sorta saying we should raise the
weight of the raw acf as a consideration?" — a reasonable read of
"even the most lenient threshold couldn't rescue it," but checking the
actual `acf_top_candidates` field (explicitly the **raw, prior-free**
comb-filter score — see its own comment in `beat_grid.py`, "Deliberately
sourced from the RAW comb_score (no prior applied)... P1-C in
`docs/audits/2026-08-04-bpm-detector-audit.md`") for `chillstep/a`'s
stuck stretch shows the opposite is true:

```text
bpm=124.99  candidates: 127.66:0.524, 63.16:0.157, 98.36:0.104   (3.3x)
bpm=127.51  candidates: 127.66:0.282, 122.45:0.120, 61.86:0.099  (2.8x)
bpm=127.62  candidates: 127.66:0.263, 61.86:0.128, 122.45:0.118  (2.1x)
```

No prior involved anywhere in these numbers — the doubled candidate's
**raw** comb score beats the half-tempo candidate's by 2.1-3.3x on its
own. `_V2_RAW_DOMINANCE_RATIO` (§ 2.1) is literally "let raw evidence
override the prior when raw evidence is clearly stronger" — the
existing mechanism this idea would tune — but here the raw evidence
already agrees with the wrong answer, decisively. Raising raw ACF's
influence would make this specific failure shape *more* confident, not
less: the prior isn't suppressing a correct raw signal, the raw signal
itself is already wrong. This is a clean, numeric confirmation of the
working hypothesis above (a loud, clean percussive layer at the doubled
rate dominates the autocorrelation on its own fundamental-lag strength,
independent of harmonic bookkeeping) and reinforces — rather than
opens — the case for Option C specifically: the fix has to *recognize*
that a strong peak is harmonically explainable as 2x of a plausible
weaker peak and prefer the sub-multiple, which a raw-score weight
knob structurally cannot do.

**Status: corrected and closed as a standalone item.** No code changed
either before or after the correction. Nothing here is flagged for
implementation — it folds into Option C's already-deferred scope.

### 8.8 A conceptual capstone: some tracks don't have a single correct BPM, and no amount of better signal processing fixes that (2026-08-15)

Owner, walking through the `2hr-dubstep` set and the `90m-hyphy` results
right after: rhythm perception is personal, not absolute — different
people (and different musical roles: a drummer's read on a track's
pulse, a guitarist's, a *dancer's* — the operationally relevant one for
a club/dance-music VJ system specifically, since the target audience is
dancing to it) genuinely lock onto different rhythmic layers within the
same piece of music as "the beat," when a track has more than one real,
internally-coherent periodicity happening at once. The image that
crystallized it, and the one to keep using: at a dubstep show, one
group of people is slow-walking to the true half-time bass pulse in one
corner while ravers are bouncing off the walls to the doubled layer
right next to them — *to the same track, at the same moment* — and both
groups are correctly on-beat. Neither reading is wrong. The track
itself is playing two legitimate, harmonically-locked rhythms
simultaneously (the faster one hits exactly twice for every one of the
slower one's downbeats, always in phase), and which one a given
listener's brain foregrounds as "the beat" isn't a fact about the audio
that better analysis could uncover — it's closer to an individual,
subjective anchor point, the same way "beauty" doesn't reduce to a
single objectively-correct answer.

**Why this reframes the T5 investigation, not just adds an anecdote to
it.** Everything this document has called "octave/harmonic-family
ambiguity" up to this point has implicitly assumed one true tempo exists
and the job is finding it despite noisy or misleading evidence. That
framing is exactly right for some of the tracks already documented here
— **"Shake That Monkey"** (§ 8.6) has three *independent* sources
converging on the same single answer (the owner's own ear, dj-mixer-01's
stored analysis, and Essentia all landing on 100 BPM) and `90m-hyphy`'s
own v1/v2 split (§ 5.4: v2 correct at 103.8, v1 wrong at 132.9 — the
*same* wrong value v2 itself landed on in two earlier sessions) reads as
one real answer that's just hard for any given algorithm to consistently
find, not two equally-valid answers. That's still squarely Option C's
target: real ground truth, obscured by
weak comb-filter evidence at the true tempo.

But **"Endlessly"** (from the `45m-chillstep` session, referenced in
§ 8.6 — owner tapped 60, 70, *and* 120 on the same song, Spotify said
202) and **"Last Night X I Want It That
Way"** (§ 8.6 — already independently written up as "doesn't have one
correct answer, not a failure on either side" before this framing had a
name) don't fit that shape at all. Neither does the `2hr-dubstep`
session's own BPM distribution (§ 5.3): 19.0% of readings genuinely in
70-100, 50.9% genuinely in 130-160, both real substantial mass, not one
dominant band with noise scattered around it. For tracks like these,
there may be no single answer for Option C's harmonic-family scoring to
converge on *even in principle* — both candidates are real, both are
"correct" by some listener's reasonable anchor, and picking one over the
other via better signal processing alone is solving the wrong kind of
problem.

**The practical implication: two different classes of "ambiguous"
track, needing two different kinds of fix.**

- **Class A — one true tempo, obscured by weak/misleading raw
  evidence.** Fixable by better signal processing. This is what Option C
  (§ 8.3) is actually for, and what most of Phase 8's evidence base
  (`chillstep/a`'s § 8.7 correction, the 142-track Essentia comparison's
  confirmed misses in § 8.6) supports building it against.
- **Class B — two (or more) genuinely co-existing, harmonically-locked
  rhythms, no single ground truth to converge on.** Not fixable by
  better signal processing, *by construction* — there's nothing wrong
  with the detector's evidence-weighing on these tracks, because there
  is no single right weighing to find. This is exactly the situation
  where external context earns its keep instead of being a stopgap:
  § 4.4's manual mood-selector nudge and § 4.5's tap-tempo seed aren't
  just production workarounds for Class B tracks — they may be the
  *actual correct* long-term mechanism for them, since genre/operator
  intent is a legitimate tiebreaker exactly where the audio itself
  doesn't have one to offer.

**Not yet actionable, and not meant to be — this doesn't change
anything about what's already proposed.** No new work item comes out of
this beyond what §§ 4.4/4.5/8.3 already carry. What it does change: how
to *read* future ambiguous-track findings before reaching for Option C
by default. A track worth checking against multiple independent sources
first (like "Shake That Monkey" was) is a Class A candidate; a track
where the owner's own ear finds several different, all-plausible taps
(like "Endlessly") is more likely Class B, and no amount of comb-filter
harmonic-family scoring should be expected to "solve" it down to one
number.

---

## Phase 9 — v3 Roadmap

### 9.1 Faster-than-real-time headless training

Owner: "can we run headless training sessions w/local tracks @ faster
than real-time speed?? that would be awesome!" ... "put it on the plan
for v3."

Currently real-time-locked because the Analyzer captures from an actual
audio device and everything downstream (envelope decay, phase
advancement, hold durations) runs off wall-clock time. The way around
it: decode a file directly (soundfile/PyAV, already used elsewhere in
the project) instead of capturing from a device, and feed the decoded
PCM into the Analyzer/BeatTracker pipeline with simulated timestamps
advancing by samples-processed rather than `time.monotonic()` — the
same technique `tools/bpm_sweep_sim.py` (§ 8.5) already uses for
synthetic onsets, just with real decoded audio. FFT/onset detection
should run well faster than 1x realtime on real hardware for offline
batch work.

Real scope, not a flag flip: needs a genuine headless-batch code path
that skips rendering, skips the mixer's real audio-output device, and
doesn't lock to wall-clock anywhere in the chain — including dj-mixer-
01's own crossfade/stem engine if auto-mix content (not just plain
sequential files) is wanted. Natural extension of the existing headless-
training plan (dj-mixer-01/media-01 as sources — see the "Headless
Training: dj-mixer-01 and media-01 as Audio Sources" plan doc) rather
than a separate effort. Not scoped further than this for now — v3-
adjacent infrastructure work, tracked here so it isn't lost.
**(Scoped 2026-08-17:** now fully phased in
`docs/planning/auto-vj-v3-roadmap-and-accelerated-replay-2026-08-17.md`
— key find: `training-kit-01/tools/bpm_eval.py` already runs the
production Analyzer+BeatTracker offline at accelerated time, so Phase A
is an extension of existing tooling, not a new build.) (See § 7.6
for the *other* v3-scoped roadmap item from tonight, the HMM/DBN
detector-architecture direction — a separate, algorithmic thread, not
infrastructure like this one.)

---

## Round-three close-out (2026-08-17): the one-shot implementation

Owner: "let's see if we can knock out all of round 3 in one shot."
Implemented in a single batch (detector `1.0.0-rc.33`, auto-vj
`1.0.0-rc.90`, core `1.0.0-beta.94`, weights doc v58 — full decision
record in `docs/adr/vj-system.md`'s "Round Three Close-Out Batch"
entry; not committed pending owner review/test). Status of every item
that was open above:

- **Interpolation default** (§ 3.1/§ 5.2) — ON
  (`_V2_ACF_INTERPOLATION_ENABLED = True`), per the B run's
  across-the-board win.
- **Relative persistence thresholds** (§ 2.2/§ 6.3) — shipped as
  `max(flat, pct × median)` immediately behind the interpolation
  default, honoring § 6.3's sequencing; flat floors keep every
  validated session's behavior unchanged below the fast-lane crossover.
- **T5 Option A** (§ 8.3/§ 8.4) — shipped, plus the interaction fix it
  forced into the open: accepted large jumps now snap to the
  25-cycle-validated median instead of crawling through
  `max_bpm_step` (a crawl would re-stall in Option A's freshly-cleared
  persistence window every cycle).
- **Minimum lock dwell** (§ 1.2) — shipped as sketch option (c):
  8-bar default window (`bpm_lock_dwell_bars`; 16 is one config edit
  away for the owner's planned comparison), 4% cumulative in-band
  drift budget from the lock anchor; excess drift is escalated into
  the large-jump gate stack, not blocked.
- **Genre-fit-weighted candidate scoring** (§ 4.2) — shipped,
  confidence-gated at `acf_conf < 0.5`, tempo-independent terms only
  (§ 6.5 honored: `onset_fit` AND `kick_regularity_fit` excluded along
  with the two BPM-derived terms).
- **Cheater mode #1** (§ 4.4) — shipped: manual audio-profile changes
  prime via `prime_tempo()` from the best in-band raw ACF candidate;
  the recommender's automatic path is structurally excluded (it marks
  its own applications); no in-band candidate → no prime. The dubstep
  hint band it depends on is widened (§ 5.3): `138-142 → 70-160`,
  hints only, prior untouched.
- **Cheater mode #2** (§ 4.5) — shipped: Enter while the KP-0 tapper
  readout is live opens a 30 s trust window (`tap_prime()`: tight
  prior around the tap, ±6% fast path through the gate stack, saved
  prior restored exactly on expiry). HELP_TEXT updated.
- **Refractory guard** (§ 6.2/§ 6.8 #4) — shipped ON with a
  `refractory_guard_enabled` kill switch. Note: § 7.5 sequenced this
  behind confirming data; implemented now per the close-out
  instruction, and the engagement counter + `analyzer_refractory_s`
  logging mean the first real session simultaneously tests the T4
  hypothesis and bounds the risk.
- **Remaining § 6.8 menu** — #2 (signed phase-error median/IQR), #5
  (ACF `n/(n−lag)` correction), #6 (pulse-strength log-compression),
  #8 (cold-start blend guard), #9 (Acc1/Acc2 + octave families, in the
  new tool), #10 (time-bounded energy history) — all shipped.
- **§ 3.2a agreement table** — shipped as
  `tools/bpm_agreement_report.py` (per-song active/shadow/shadow2
  agreement, mixer-library reference, Acc1/Acc2 ±4%, octave-family
  classification incl. § 8.6's 4:3/5:4). The **LLM column is
  deliberately not implemented** — it needs its own scoping pass per
  the original design, and standing policy treats LLM tempo recall as
  tiebreaker-grade.
- **Not touched, per their own scoping:** § 4.3 config menu (rc2),
  § 3.2b controlled re-priming (recommender phase), § 5.1's deferred
  centroid recalibrations, T5 Options B/C, § 7.6 HMM/DBN, § 4.1
  rolling windows, § 9.1 headless training, per-tick phrase-role
  logging.

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
by 100% live-session agreement first); three `library/c` LLM tuning
recommendations, owner-approved directly:
`_BPM_LOCK_RELEASE_CONFIDENCE` `0.28 → 0.3`,
`phrase_under_over_hold_mult` `0.6 → 0.7`, and `kick_regularity_fit`
`0.9 → 1.2` (§ 5.1). `_DETECTOR_VERSION` → `1.0.0-rc.27`;
`_DIRECTOR_VERSION` → `1.0.0-rc.5`; `_RECOMMENDER_VERSION` →
`1.0.0-rc.14`. Later the same round: `_BPM_LOCK_RELEASE_CONFIDENCE`
corrected `0.3 → 0.25` (§ 1.4); `kick_regularity_fit` pulled back
`1.2 → 1.0` (§ 1.5); `_V2_LOCK_BAND_PCT` `0.08 → 0.03` and
`_V2_LOCK_BAND_MIN` `10.0 → 4.0` from measured jitter (§ 1.5).
`_DETECTOR_VERSION` → `1.0.0-rc.28`; `_DIRECTOR_VERSION` → `1.0.0-rc.6`.
Also this round, pure logging only: `analyzer_refractory_s` and
`phase_confidence_calibrated` (§ 7.5/§ 7.7). Separately, in
`training-kit-01`: the Essentia dynamic-loader `sys.modules`
registration fix and the loud `_warn_if_essentia_unavailable()` warning
(see `docs/adr/vj-system.md`'s "Round Three, the morning after" entries)
— not a detector change, but what made § 8.6's real Essentia comparison
possible at all.

**Proposed, awaiting consensus before implementation:**
- Minimum lock dwell time — new gate category for the in-band drift gap
  `_V2_LOCK_BAND_PCT` alone doesn't fully close; candidates revised to
  **8 and 16 bars** (owner: "32 bars too long"), design sketch only (§ 1.2).
- Per-song v1/v2/v3 agreement table with mixer-library + LLM external
  checks (§ 3.2a) — the shadow2 slot needed for this now exists; the
  actual agreement-table logic doesn't yet.
- Genre-fit-weighted candidate scoring, confidence-gated (only consulted
  when `acf_conf` is already low — owner's refinement this round) using
  tempo-independent terms (§ 4.2).
- A full in-app config menu for detector/shadow model selection —
  explicitly scoped for rc2, not rc1 (§ 4.3).
- **"Cheater mode" #1** — manual mood-selector change re-primes the
  detector via `prime_tempo()`, scoped to manual triggers only, never
  the recommender's automatic path; production stopgap, not a
  replacement for T5/Option C. Design proposed, not implemented,
  awaiting owner input (§ 4.4).
- **"Cheater mode" #2** — tap-tempo (existing `Overlays.bpm_tap()`
  HUD feature, currently display-only) wired to a new 30-second
  elevated-trust window on `Enter` confirm; genuinely new engineering,
  not a `prime_tempo()` reuse. Design proposed, not implemented,
  awaiting owner input (§ 4.5).
- `dubstep`'s own `bpm_hint_min`/`max` (currently `138-142`, far
  narrower than the genre's real bimodal 70-100/130-160 range per
  `2hr-dubstep`'s own data) — flagged, not changed, since § 4.4 would
  inherit the same blind spot if built against the current values
  (§ 5.3).
- Controlled genre-driven re-priming after lock — explicitly the
  behavior just retired above, but owner asked it be noted as worth
  revisiting once recommender work resumes, not closed off permanently
  (§ 3.2b).
- `hard_techno`/`house` spectral-centroid recalibrations from
  `library/c`'s LLM scoring pass — explicitly deferred to a later
  library-diversity pass, not rejected (§ 5.1). (`kick_regularity_fit`'s
  weight bump, the other recommendation in this batch, was applied on
  reconsideration and later partly walked back — see "Shipped this
  round" above.)
- T5 Option A (reset the persistence window on acceptance) — small,
  safe, recommended as the first landing, pending explicit go-ahead
  (§ 8.3/§ 8.4). Options B and C stay deferred, C now with a richer,
  real target (4:3/5:4, not just 2:1/1.5:1 — § 8.6) and a live bug
  report against its proposed reused machinery to account for in its
  design (§ 8.7).

**Investigated and answered this round:**
- *Why does the raw comb-filter argmax wander?* Root cause found (§ 3.1):
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
  instrumentation gap instead of guessing (§ 2.2).
- *Is v3 actually behaviorally different from v2 in production today?*
  No — confirmed empirically, not just by reading code: `100%` exact
  agreement across a full live session (§ 1.3), because the one call site
  that would exercise `BeatTrackerV3`'s guard was already removed at
  `_DETECTOR_VERSION` rc.20.
- *Why did a live session collapse from correct (~122 BPM) to sub-100 and
  back, repeatedly?* Root cause found (§ 1.2): in-band steps (inside
  `_V2_LOCK_BAND_PCT`) accumulate drift with zero gating — the large-jump
  gate stack only ever governs jumps *outside* the lock band.
  `_V2_LOCK_BAND_PCT` tightened same round (see "Shipped" above); a
  minimum lock dwell time remains a distinct, not-yet-implemented idea
  for the residual gap (§ 1.2).
- *Does interpolation actually move the persistence-gate clear rate?*
  Yes, real A/B data (§ 5.2): `long_candidate_spread` clearing `6.0`
  roughly doubled (`8.5% → 19.9%`), lock stability and mean confidence
  both improved. Still off by default pending the owner's own call.
- *Was the octave/harmonic-family problem (T5) confined to fast genres
  as originally assumed?* No — real evidence from reggae/dancehall
  (`garbage/m`, § 8.1) and, later, from vocal-heavy R&B remixes with
  sparse bass anchoring (`library/i`'s 142-track Essentia comparison,
  § 8.6) shows it's broader, both in genre and in ratio family (4:3,
  5:4, not just 2:1/3:2) than the original DnB/hardstyle framing
  expected.
- *Does the study pass's convergence with the two formal audits hold up
  under direct re-verification?* Yes (§ 7.1/§ 7.2) — independently-built
  fixes this round matched the audits' own top-ranked recommendations in
  both mechanism and, where testable, real measured effect.

**Still open:**
- **Minimum lock dwell time** — new gate category (§ 1.2), design sketch
  only, test candidates 8/16 bars, needs its own scoping pass before
  implementation.
- **The interpolation A/B result itself, as a default** — real A/B data
  now exists and favors turning it on (§ 5.2), but `_V2_ACF_INTERPOLATION_ENABLED`
  stays `False` by default pending the owner's own call, and § 6.3
  flags that the persistence spread threshold should be revisited only
  after that default is actually decided.
- Whether `_V2_LARGE_JUMP_PERSISTENCE_CYCLES`'s spread threshold (6.0,
  not the 25-cycle count) needs to move, and whether it should become
  relative rather than absolute (§ 2.2/§ 6.3/§ 7.3) — now answerable
  from real data once a session captures the `long_candidate_spread`
  logging with interpolation settled as a default.
- Whether `_BPM_LOCK_CONFIDENCE` (0.55) is too permissive specifically
  for a cold-start lock, distinct from the startup-confidence floor
  already raised this round (§ 2.3/§ 6.4).
- `beat_grid.py`'s lack of any real downbeat-phase re-anchoring
  mechanism (§ 4.1/§ 6.6, "phase anchor").
- Which phrase *role* (HOLD/RISE/PEAK/FALL) was queried at a given tick
  — not logged, since `_phrase_bias(role)` has no single persistent
  "current role" field to read (§ 4.1).
- The confidence-gate threshold for § 4.2's genre-fit consultation
  (candidate: reuse `_V2_STARTUP_CONFIDENCE`, or a separate value), and
  whether `onset_fit` needs excluding from it (§ 6.5).
- The remaining Phase 6 low-hanging-fruit menu items not yet shipped:
  the BPM-fed refractory guard (§ 6.2/§ 6.8 #4, hypothesis-only until a
  stuck session provides the confirming data), ACF overlap normalization
  and pulse-strength clamp (§ 6.8 #5/#6), relative persistence
  thresholds (§ 6.8 #7, sequenced behind the interpolation default),
  the cold-start blend guard (§ 6.8 #8), and the two pure-logging items
  (§ 6.8 #9/#10).
- **T5's Option A** (§ 8.3/§ 8.4) — proposed, not yet landed, pending
  explicit go-ahead. **Option C**'s design (comb-filter harmonic-family
  window scoring) — real-v3-adjacent, needs its own session with a
  synthetic multi-modal-candidate harness. § 8.7's cross-session data
  (a ~94-99% tactus-fold rejection rate is universal baseline, not
  chillstep-specific, and `chillstep/a`'s own gate was the *most*
  lenient of the sample yet still couldn't self-correct) is a second,
  independently-sourced confirming data point for what Option C needs
  to catch, alongside § 8.6's Shake That Monkey/Doo Wop That Thing case
  — not a new blocker on Option C's design, and not a separate proposal
  of its own.
- **`kick_regularity`'s leniency-dial hypothesis from the original live
  read of § 8.7 — retracted, not open.** Checking the actual code and
  the real logged `effective_tactus_ratio` values (correlation with
  `kick_regularity`: exactly −1.000, as coded) showed the dial runs the
  opposite direction from what the live read claimed, and was already at
  its most permissive setting during the stuck session. Nothing to fix
  here; no follow-up investigation needed on this specific mechanism.
- The HMM/DBN architecture direction (§ 7.6) and faster-than-real-time
  headless training (§ 9.1) — both explicitly v3-scoped, not round-three
  work, tracked so neither gets lost.

**Rolling rear-view-mirror windows (4/8/16/32-beat):** real design work,
explicitly not for immediate integration per the owner — candidate uses
identified for both the persistence gate (§ 2.2) and phrase detection
(§ 4.1), serious enough to warrant its own follow-up planning doc once
scoped further.

---

## Verification note (2026-08-15 reorganization)

Every section from the pre-reorganization document (§§ 1-15, the old
duplicate `§ 12` audit cross-check with its 12.1-12.8 subsections, § 16
with its 16.1-16.7 subsections, § 17 with its 17.1-17.4 subsections plus
both "Update" appendices, and § 18) is present above in full, under its
new Phase.Section heading, with body text preserved and only internal
`§ N` cross-references translated to the new numbering. Nothing was
shortened, summarized, or cut. One new subsection was added (§ 8.7, the
live chillstep tactus-fold/`kick_regularity` finding), and a small
number of connective sentences were appended — clearly marked inline
("Note added 2026-08-15", "(See...)") — to cross-link § 8.7 against
§ 8.3's Option C and to note § 8.6's `garbage/n` reproducibility
follow-up; none of these replace or remove any original sentence. The
stale mid-document "Summary" (which previously covered only through the
old § 15 and the audit cross-check) has been moved to the end of the
document and extended with new paragraphs covering Phases 7, 8, and 9,
which it did not previously mention.
