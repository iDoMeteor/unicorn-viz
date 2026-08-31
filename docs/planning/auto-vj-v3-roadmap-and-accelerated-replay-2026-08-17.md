# Auto VJ v3 Roadmap + Accelerated Local-Track Replay — Plan (2026-08-17)

Owner: unicorn-viz
Status: Part 2 LANDED (Phases A + B + C part 1, 2026-08-18 — see
  § 2.5; C part 2, mixer/media sources, remains a mixer-team
  dependency); Part 1 Threads 1/3/4/5/6 remain future work. Originally planning-only,
  consolidating the v3-scoped threads scattered through
  `auto-vj-round-three-planning-2026-08-14.md` (§ 7.4/§ 7.6/§ 8.3/
  § 9.1) into one place, plus the owner's priority item: **running
  tests with local tracks at an accelerated rate of time** (§ 9.1).
Last updated: 2026-08-18

---

## Part 1 — The v3 roadmap, summarized

v3 is not one thing; it's six threads with an explicit ground rule.

**The ground rule (§ 7.4, the v2-final-candidate checkpoint).** The
current shipped detector — as of the round-three close-out batch,
`_DETECTOR_VERSION 1.0.0-rc.33` — is the protected baseline. Any v3
candidate is designed and built *against* it, never *into* it, and must
earn its place with its own real-session validation before it can
displace the checkpoint. v2 stays deployed as the fallback/comparison
engine the way v1 does today. The `beat_tracker_engine = "v3"` config
name is already freed (the old subclass was retired) and reserved for
the real next generation.

**Thread 1 — the HMM/DBN detector architecture (§ 7.6).** The round-
three gate stack (persistence windows, jump confidence, lock bands,
dwell timer, tactus ratios) is a hand-built approximation of what the
field's standard architecture expresses as one small model: a
pure-numpy HMM over a discretized tempo lattice — states = candidate
tempos, observation likelihood = the existing comb-filter score,
transition prior = one tunable matrix replacing seven interacting
gates. Both the 2026-08-13 tempo audit (Part III item 7) and the
round-three study pass converged on this independently. Buildable
within the no-heavy-deps constraint. This is the "real v3" if that
phrase means an architecture generation.

**Thread 2 — accelerated/headless infrastructure (§ 9.1).** This
plan's Part 2. Infrastructure, not algorithm — but it is what makes
Thread 1 *testable* (an HMM candidate needs thousands of track-hours
of comparison against the checkpoint, which nobody is going to play in
real time) and what unblocks Thread 3's data problem.

**Thread 3 — T5 Option C, the real octave/harmonic-family fix
(§ 8.3).** Fold the persistence window by harmonic family before
computing spread/median, scoring 4:3 and 5:4 families alongside the
textbook 2:1/3:2 (§ 8.6's Essentia comparison; the sweep sim showed
3:2 distractors are *worse* than octave distractors). Blocked on
exactly one thing the plan itself identified: "no way exists to
backtest it against historical sessions, because raw per-cycle ACF
candidates were never logged." Accelerated replay removes that blocker
— see Part 2, "what this unblocks."

**Thread 4 — rolling rear-view windows (§ 4.1) + the phase anchor.**
Multi-window (4/8/16/32-beat) agreement as a persistence-gate
replacement and as an internal phrase-boundary detector; and the
still-missing downbeat/bar-phase anchor (bass-accent voting is the
cheap causal candidate). Both are design work that should be specified
in bars/seconds, not frames, per the audit's dt-independence finding.

**Thread 4 addendum (2026-08-20, owner-directed): the remaining
drop-score plan items land here too.** The drop-score redesign's core
shipped (trigger/sustain split, rc.97); what its plan left open is
bundled into this thread because every piece either needs or benefits
from the bar-phase anchor this thread builds:

- **`structural_cues()` causal port as a drop-confirmation signal**
  (redesign § 4a/§ 4d): the mixer's phrase-step energy-jump detector,
  shrunk to ~1 leading bar vs 8 trailing — a "sure, ~1 bar late"
  second opinion that composes with `impact_novelty`'s instantaneous
  trigger and naturally gates the fizzle floor. Blocked on bar phase
  by definition (its windows are bars); audit F5/B4 are the same gap.
- **Per-mood buildup/slope influence window** (redesign § 4a deferred
  item): `slope_window_s` per mood profile via the existing
  `_PROFILE_PRESETS` pattern — trivial once specified in bars.
- **Onset-density acceleration** (audit F3's queued build cue): onsets
  per bar rising across consecutive bars — the snare-roll speedup, the
  single most characteristic buildup cue in the production
  literature; needs "per bar", i.e. the anchor.
- **F6, the vacuous drop re-validation gate** (audit): still open,
  independent of the anchor — a small fix that should ride whichever
  batch touches `_schedule_drop()` next.
- **The T7 envelope pulse-placement jitter** (tempo audit addendum)
  stays v3-adjacent detector work, NOT this thread — listed here only
  so nobody mistakes its absence for resolution.

**Thread 5 — the maturation items parked for later phases.** The rc2
in-app models/config menu (§ 4.3); controlled genre re-priming once
recommender work resumes (§ 3.2b); dubstep's genuinely bimodal tempo
representation (the round-three close-out widened the hint band; the
prior still models one mode); the deferred `hard_techno`/`house`
centroid recalibrations; per-tick phrase-role logging if Thread 4
needs it; the § 3.2a LLM external-check column, still separately
scoped.

**Thread 6 — a persisted perf log while training is on (2026-08-18,
new).** Owner noticed a considerable render-frame-rate drop today and
had no way to go back and check it — training-corpus rows carry no
frame-rate or input-RMS signal at all, so a perf regression during a
session is invisible after the fact. Checked what already exists
before scoping this as new work, and it's a smaller lift than it
sounds:

- **Real per-frame FPS is already measured, just not logged.**
  `App._last_frame_fps`/`_last_frame_ms` (`app.py`, computed every main-
  loop iteration from actual `dt`, not the 60 fps target) already has a
  public accessor — `VJApi.system_telemetry_snapshot()['fps']` — used
  today by `control-room-01`'s HUD, never read by `auto-vj-01`.
- **A real per-frame performance profiler already exists**, gated
  behind `[logging] perf_frames` (or DEBUG level) — stage-by-stage
  timing (events/MIDI/audio/auto_vj/effects/HUD/draw/swap/present) at a
  slow-frame threshold (25ms) or every 120th frame otherwise. It only
  ever reaches `log.debug()`, never a file, never the corpus. This is
  the natural donor for a real perf log — the expensive part (timing
  every stage) is already built and already running whenever perf
  debug is on; it just needs a sink.
- **RMS is a split story, worth getting right rather than assuming.**
  `Analyzer.last_raw_rms` (pre-silence-gate input level) is tracked and
  has a public accessor (`AudioManager.get_raw_input_rms()`), HUD-only
  today, never in the corpus. Separately, every corpus row *already*
  has a field literally called `rms` (`_build_live_training_row()`) —
  but it's a different signal: post-gate, computed from the effect-
  facing waveform buffer, not the analyzer's raw input level. A perf
  log should carry the analyzer's `last_raw_rms` explicitly labeled as
  such (e.g. `input_rms_raw`) so it isn't confused with the existing
  corpus `rms` field, which stays as it is.
- **Sizing:** per-frame at 60 fps into the sequence corpus (~1 Hz
  heartbeat cadence today) would be far too fine-grained and heavy —
  this wants its own sink, a separate `perf-<timestamp>.jsonl` written
  alongside the other session logs (matching Phase A item 7's "the
  corpus is the wrong place for this, log it separately" precedent for
  per-cycle candidate data), sampled at the profiler's existing cadence
  (slow-frame threshold + every-Nth-frame), gated the same way the
  in-memory profiler already is so it costs nothing when training isn't
  running. `input_rms_raw` and `fps`/`frame_ms` land in the same row.
- **Packaging-side:** `package_training_set.py` would need to move this
  new log file into the bucket alongside the existing ones (mechanical,
  same pattern as every other log type it already archives) and
  probably a short scorecard summary line (e.g. mean/p95 frame time,
  slow-frame count) — not the full per-row detail, mirroring how the
  "Round-Three Mechanism Engagement" section summarizes rather than
  dumps.

Owner: "are we capturing frame rate & rms in the training data?? i
noticed frame rate has dropped considerably.. just noticed today, and
we probably don't have a way to track that! we should capture a perf
log when we have training on."

Sequencing logic: **Thread 2 first** — it is the only thread that
makes the others cheap to validate, it has immediate payoff for
ordinary regression testing (the owner's ask), and it requires no
detector-behavior changes at all. **Thread 6 is a strong candidate to
ride alongside Thread 2's own infrastructure work** (both are "make
training sessions observable in ways they currently aren't," and both
are small/mechanical relative to Threads 1/3/4) — sequencing between
them is the owner's call, not decided here.

**Thread 7 — track-boundary state carryover; a source-aware crossfade
suspend/reset (2026-08-20, new).** Found via the accelerated replay
harness (Thread 2), on a deliberately adversarial 11-track "toughies"
playlist built from tracks already known to be hard: `BeatTracker`
never resets on a track change — its only reset path is 15 s of
silence (`_silence_reset_s`), and neither the replay harness's default
2 s gap nor a real crossfade ever reaches that. So the entire gate
stack (locked `_bpm`, candidate history, dwell anchor, cold-start
guard, and the recommender's genre-evidence push, fed by a 16 s
*time*-windowed sample buffer that isn't track-boundary-aware) treats
the *previous* track's state as the incumbent the new track has to
out-persist. Confirmed reproducible: re-shuffling the same 11-track
playlist across 5 seeds flipped several tracks (Claviger, Kaboom Las
Vegas, Habits Stay High) between a correct lock and a confident wrong
4:3-family fold depending purely on which track played immediately
before, at 0.00 BPM variance when the seed (and thus track order) was
held identical.

Two ideas, split by cost and correctness:

- **Reset BPM + genre-evidence on a *known* track change** (any source
  that reports a real track-id/`change_counter` — media-01,
  dj-mixer-01, Spotify's web-api change counter; web streams have no
  such signal and structurally never trigger it, no special-casing
  needed). Cheap, self-contained, single call site
  (`auto_vj.py`'s existing `change_counter` branch). Already prototyped
  as an uncommitted experiment (`_reset_tempo_lock()` +
  `_reco_samples.clear()` + `set_genre_tempo_evidence(0,0,0)` at the
  change-counter branch); results on the adversarial toughies set were
  genuinely mixed (fixed Habits Stay High and Blackout Riddim in some
  conditions, made Claviger and No Pretend *more* consistently wrong in
  others) — expected, since toughies is stress-tested precisely at
  fold boundaries where a stale-but-lucky carryover can be
  accidentally helpful. Needs re-validation on normal (non-adversarial)
  playlists before it's trusted as a general improvement, not just a
  toughies-neutral one.
- **For mixer/media sources specifically: detect an active
  crossfade/transition and suspend detector commitment through it,
  firing the reset only at transition-end** (this is the real fix, not
  the quick one). A follow-up experiment mixed real overlapping audio
  at track boundaries (a genuine equal-power crossfade, not silence)
  and found it measurably *worse* than the silence-gap baseline for
  several tracks (Claviger went from ~50/50 right/wrong to wrong in
  5/5 runs) — feeding the analyzer two overlapping, different-tempo
  rhythms simultaneously doesn't just leave stale state around, it
  actively manufactures new spurious onset/beat-interference evidence
  that can seed a *more* convincing wrong lock than either silence or a
  clean cut would. A reset fired at the moment `change_counter` flips
  (which can land mid-crossfade) doesn't fix this; the detector needs
  to stop trying to commit to anything while two tracks are audible at
  once, and only re-engage once the transition is actually over. Real
  cross-drop-in work, not a quick patch: dj-mixer-01
  (`mixer_engine.py`/`deck.py`) and media-01 (`media_controller.py`)
  both clearly track crossfade/transition progress internally already,
  but neither currently publishes it on the shared `vj_api` bus (the
  closest existing thing, `publish_session`/`get_session`, is night-
  phase timing, not per-track transition state) — would need a new bus
  method, both drop-ins wired to call it, and a new detector "suspend"
  mode distinct from reset (keep sampling, commit nothing) that only
  lifts on the transition-end signal. Scope with the mixer/media owners
  before starting; not something to guess at solo.

Owner: "well... all but web streams, we pretty much know when we're
track changing, right? so we could trigger a reset of bpm & genre when
we know about that. and for mixer/media player source.. we even know
about the cross fade.. for those sources could we detect when there
are two tracks being faded/mixed...lock the detector and fire the
reset at transition end?"

**Correction (2026-08-20, same day): idea 1's unconditional reset is
ruled out, not just "needs more validation."** Re-ran the same
uncommitted patch against 2 different seeds each on `favorites` (56
tracks — the largest, most "normal" library tested), `training - house
01` (31 tracks), and `toughies` (11), with a matched no-patch baseline
run immediately after on identical seeds for a clean before/after.
Session-level aggregates (lock coverage, confidence) barely moved
either way — this only shows up per-track:

| playlist | baseline mean spread / flips (2-seed pairs) | idea-1 mean spread / flips |
| --- | --- | --- |
| favorites (56 tracks) | 2.34 / 4 | **4.89 / 6 — worse** |
| training - house 01 (31 tracks) | 2.01 / 1 | 1.60 / 1 — a wash (fixed one track, broke a different one) |
| toughies (11 tracks) | 7.69 / 2 | 3.78 / 2 — genuinely better |

The favorites result is the one that matters: idea 1 introduced *new*
large flips on tracks that were previously stable (Scenpha - Tribal
Essence: a 65 BPM swing that didn't exist in baseline; Drake - Which
One: a new 25 BPM swing). Root cause of the regression, not just an
observation: in a curated library, neighboring tracks usually sit in a
*similar* tempo range, so the "stale" carryover from the previous track
is usually a **correct warm start**, not a liability — it's only wrong
at the minority of tracks that happen to sit at a harmonic-fold
boundary relative to their neighbor. An *unconditional* reset throws
away that usually-helpful warm start every single time and forces a
cold ACF re-acquisition (gated by the higher `_V2_STARTUP_CONFIDENCE`
bar, not the already-locked `_V2_MIN_UPDATE_CONFIDENCE` one) on every
track, which is a worse bet on average across a normal library even
though it's a better bet specifically on adversarial fold-boundary
tracks. **Conclusion: "reset everything on every known track change"
is ruled out as a design — it needs to be conditional, not
unconditional.**

**Idea 2, rounded out.** The conditional framing idea 1's failure
points at turns out to decompose into two independent, separately
valuable pieces — worth tracking as two sub-items rather than one:

1. **Conditional re-acquisition on any known track change** (does
   *not* need crossfade awareness — applies to media-01, dj-mixer-01,
   and Spotify's change-counter alike). On a detected track change,
   don't touch the incumbent lock at all yet; let the ACF keep
   computing candidates as normal (already happens every cycle, so
   this is free), and only *at the moment a fresh, reasonably-confident
   candidate disagrees with the incumbent* (outside its harmonic-fold
   family, not just noisy jitter) treat that as a **known-boundary
   large-jump** — accept it immediately rather than making it wait out
   the in-track `_V2_LARGE_JUMP_PERSISTENCE_CYCLES` (25 cycles, ~3.3 s)
   gate, since that gate exists to protect against false alarms from
   *ambiguous* in-track evidence, and a real track-change signal
   removes exactly that ambiguity — we already know something happened,
   the only open question is whether the new track's tempo actually
   differs. When the fresh candidate agrees with the incumbent (the
   common case per the favorites data above), nothing changes — the
   warm start is preserved exactly where it was already correct. This
   is the more surgical version of the same idea, keeps the good half
   of idea 1 (fast, correct re-acquisition when the track genuinely
   changed) and drops the half that regressed favorites (unconditional
   disruption of the common case where it didn't need to change).
2. **Suspend-through-overlap, mixer/media only** (does need crossfade
   awareness — this is the piece that's actually about the fade, not
   about the track-change moment). While a transition is reported
   active, don't let anything — not even the conditional check above —
   commit to a new lock; keep sampling candidates internally (so one
   is ready the instant the transition ends) but treat the overlap
   window's ACF output as untrusted, since the crossfade experiment
   showed overlapping audio actively manufactures interference evidence
   that's worse than either a clean track or silence. At transition-end,
   run item 1's conditional check once, using the first clean
   post-transition audio rather than anything from inside the overlap
   window. The onset envelope ring (`_env_buf`, ~8 s) doesn't need
   explicit clearing here the way the earlier experiment tried it: once
   the transition ends and suspension lifts, clean single-track audio
   refills the rolling window within its own ~8 s regardless, and
   nothing was allowed to commit off the contaminated portion in the
   meantime.

Same bus-plumbing dependency as before for item 2 (dj-mixer-01/
media-01 don't yet publish transition state on `vj_api`) — item 1 has
no such dependency and could land first, independently, once its own
conditional-jump-acceptance logic is validated the same rigorous way
(matched baseline, real libraries, not just toughies) that ruled out
the unconditional version above.

---

## Part 2 — Accelerated local-track replay (the priority item)

### 2.1 What already exists (verified against current code, not assumed)

The project is much closer to this than § 9.1's sketch assumed:

- **`drop-ins/training-kit-01/tools/bpm_eval.py`** already streams
  audio files through the **production** Analyzer + BeatTracker in a
  deterministic offline loop, faster than real time, with per-file
  ground truth and a baseline-diff workflow (`bpm_eval_baseline.json`).
  This is Phase A's skeleton, already working. Limitations: WAV-only
  (`scipy.io.wavfile`), ground truth only from hand-authored
  `<stem>.bpm.json` sidecars, and its seed corpus is synthetic clicks
  (`gen_bpm_eval_corpus.py`). (Docstring nit: it says it lives in
  `auto-vj-01/tools/` — it lives in `training-kit-01/tools/`.)
- **The audio-time plumbing is done.** `Analyzer.process(pcm, t=...)`
  (H9), `BeatTracker.update(..., t=...)`, onset events carrying audio
  timestamps, the 100 Hz envelope being sample-clocked, and (since the
  round-three close-out) the energy-slope history being time-bounded
  rather than frame-counted. `beat_grid.py` has only 4
  `time.monotonic()` call sites, all defaulted-away when `t=` is
  passed.
- **`Analyzer.set_sample_rate()`** exists, so decoded audio at a known
  rate can be fed honestly instead of assuming 48 kHz.
- **Decode for arbitrary codecs exists in-repo**:
  `dj-mixer-01/deck.py::_decode()` (soundfile for WAV/FLAC/OGG, PyAV
  for MP3/AAC/M4A, resampled to a target rate). Both libraries are
  already project dependencies via the mixer and videos-01.
- **Ground truth for the owner's library exists**: the mixer track
  store (path → hash → analyzed BPM), already consumed read-only by
  `bpm_agreement_report.py`, which also already implements the
  Acc1/Acc2 ±4% and octave-family metrics.
- **`bpm_sweep_sim.py`** proves the speed budget: ~3 simulated hours of
  full BeatTracker operation in ~110 s wall (~100× real time) — and
  that's with synthetic onset generation; FFT on real audio will cost
  more but 20-50× real time is a safe expectation for Phase A.

### 2.2 What's missing, phased

**Phase A — detector-grade replay of real local tracks (next
iteration's deliverable).** Extend/refactor `bpm_eval.py` (or a
sibling `track_replay.py` that it and future tools share) with:

1. **Real-codec decode**: the soundfile → PyAV fallback chain, mirrored
   from `deck.py::_decode()` (mirror the ~30-line pattern or
   dynamically load it; do not import across drop-in packages),
   resampled to 48 kHz mono, `Analyzer.set_sample_rate()` set
   explicitly.
2. **Fidelity rule (from the audit's M3):** step the replay at
   live-equivalent cadences — analyzer blocks at the capture block
   size, tracker `update()` at 60 Hz-equivalent audio time — so every
   per-update EMA behaves exactly as it does live. Accelerated means
   wall-clock-decoupled, not coarser-stepped. (This is why replay
   results are trustworthy at all.)
3. **Track-store ground truth**: `--track-store` flag reusing
   `bpm_agreement_report.py`'s loader (path/basename → hash → BPM);
   sidecar JSON stays as the fallback for tracks outside the library;
   optional manifest mode for public sets (GiantSteps) later.
4. **Metrics**: adopt the agreement tool's Acc1/Acc2 ±4% + octave-
   family classification, plus time-to-first-lock, lock-toggle count,
   steady-state error, and the round-three engagement counters
   (`dwell_gated_count`, `persistence_reset_count`,
   `refractory_guard_engaged_count`, `genre_evidence_applied_count`,
   `tactus_*`, `phase_error_median/iqr`) — every new mechanism gets
   exercised by real audio for the first time, at batch scale.
5. **Baseline diffing**: keep `bpm_eval`'s baseline-json workflow —
   `--baseline old.json` prints per-track and aggregate deltas. This
   is the A/B harness every future detector change (and every v3
   candidate) gets measured with.
6. **Pytest integration (the "run tests" half of the ask):** an
   opt-in marker (`@pytest.mark.local_tracks`) gated on an env var
   (e.g. `UNICORNVIZ_TRACK_FIXTURES=/path/to/dir`), skipping cleanly
   when unset so CI and other machines are unaffected; the synthetic
   click corpus remains the always-on CI tier. Assertions pinned to
   floors, not exact values (e.g. Acc2 ≥ threshold per fixture
   manifest), so codec/library drift doesn't produce flaky reds.
   Audio files never get committed; the fixture dir is local-only.
7. **Per-cycle candidate logging** (`--log-cycles out.jsonl`): raw ACF
   candidates, comb scores, fold decisions, gate outcomes at the full
   ~7.5 Hz cycle rate. Cheap here (no live frame budget), impossible
   to reconstruct from the ~1 Hz corpus.

**Phase B — director-in-the-loop replay.** The controller is the
wall-clock holdout: **37 `time.monotonic()` call sites** in
`auto_vj.py` (mode timers, cooldowns, refractory windows, the
recommender's eval interval, the ActionEngine's `ready()` cooldowns).
The work is a clock seam — `self._now()` on `AutoVJController` (and an
injectable clock for `ActionEngine`), mechanical replacement of the 37
sites, a stub `vj_api`/app surface for headless runs — after which a
full session (modes, drops, phrase clock, recommender, corpus writers)
replays at accelerated time and can be LLM-scored without a live
night. Medium-sized, purely mechanical, zero behavior change live
(the seam defaults to `time.monotonic`). Regression-testable by
asserting a wall-clock run and a `t=`-driven run of the same fixture
produce identical decision sequences.

**Phase C — full headless training at speed.** Phase B plus real
*sources*: sequential local files first (trivial once Phase B lands —
the replay driver is the source), then dj-mixer-01 auto-mix content,
which requires the mixer's own crossfade/stem engine to accept the
same audio-time clock — a mixer-team dependency to negotiate, per the
existing "Headless Training: dj-mixer-01 and media-01 as Audio
Sources" plan. Corpus rows stamped with audio-time; training-kit
packaging/LLM scoring unchanged (they already consume logs, not
clocks).

### 2.3 What this unblocks (why it's first)

- **T5 Option C stops being unbacktestable** — Phase A item 7 produces
  exactly the per-cycle candidate streams over real music that § 8.3
  said don't exist, from the owner's own library, in minutes per
  hundred tracks.
- **The v3 HMM thread gets its yardstick** — same fixture set, same
  Acc1/Acc2/baseline-diff harness, checkpoint-vs-candidate on real
  audio at batch scale (Thread 1's validation requirement).
- **Every weight/threshold change gets a real-audio regression gate**
  — today's discipline (sim against two packaged sessions) upgrades to
  "replay the library" as a pre-ship check, without waiting a night.
- **The round-three close-out's own open questions get data fast**:
  the refractory-guard hypothesis (T4), dwell 8 vs 16 bars, the
  phase-error median/IQR discriminator — all measurable in one batch
  run instead of one live session each.

### 2.4 Prep checklist for the next iteration (ordered, all small)

1. Refactor `bpm_eval.py`'s file loop into a reusable
   `stream_track(path, analyzer, tracker, *, block_s, fps)` helper
   (Phase A's core, shared with the pytest fixtures).
2. Add the decode chain + `set_sample_rate()` (mirror
   `deck.py::_decode()`).
3. Wire `--track-store` ground truth through
   `bpm_agreement_report.py`'s loader (import it — same drop-in — or
   lift the loader into a shared `tools/_ground_truth.py`).
4. Add Acc1/Acc2/fold + engagement-counter metrics and
   `--baseline` diffing.
5. Add `--log-cycles`.
6. Add the `local_tracks` pytest marker + env-var fixture discovery +
   a tiny manifest format (`fixtures.json`: path, expected_bpm,
   optional expected_fold_tolerance).
7. Capture a first baseline JSON over the owner's library and check it
   in (numbers only, no audio) — that file becomes the standing
   regression reference.
8. (Phase B opener, when ready) the `AutoVJController._now()` seam +
   the 37-site sweep, with the identical-decision-sequence regression
   test.

Decisions deliberately left to the owner: where the harness canonically
lives (training-kit-01 owns `bpm_eval.py` today; auto-vj-01 owns the
detector it exercises — either works, pick one and cross-link);
whether Phase A extends `bpm_eval.py` in place or supersedes it;
whether the first fixture manifest is the full library or a curated
~50-track set spanning the known problem genres (chillstep, dubstep,
DnB, R&B 4:3 cases — recommendation: curated set first, full library
as a second tier).

### 2.5 Landed (2026-08-18): Phases A + B, all eight prep items

Owner: "do the prep work and knock out phase 1 & 2." Resolution of the
open decisions above: the harness stayed in training-kit-01 (new
`tools/track_replay.py` core; `bpm_eval.py` rebuilt on it in place, CLI
back-compatible), and the first checked-in baseline is the **full
library** (every track the mixer store has truth for), since the
per-track cost turned out low enough (~150 s of audio in ~3 s) that
curation wasn't buying anything; a curated problem-genre manifest
remains a good idea for the `local_tracks` pytest tier specifically.

What shipped, by prep item: (1) `stream_track()` in
`track_replay.py`; (2) soundfile→PyAV mono decode +
`set_sample_rate()`; (3) `--track-store` truth via dynamic reuse of
`bpm_agreement_report.py`'s loader (folds + store parsing stay
single-sourced); (4) Acc1/Acc2/fold + time-to-first-lock/toggles/
steady-state + engagement counters, and `--baseline` diffing;
(5) `--log-cycles` (per-ACF-cycle rows via a new logging-only
`cycle_log_hook` in `beat_grid.py` — no detector version bump, nothing
behavioral); (6) `local_tracks` marker + `UNICORNVIZ_TRACK_FIXTURES` +
`fixtures.json` manifest (`tests/test_local_track_replay.py`);
(7) first library baseline under
`drop-ins/training-kit-01/tools/baselines/`; (8) the Phase B clock
seam — `AutoVJController._now()`/`set_clock()`, `_ActionEngine(clock=)`,
all 37 sites swept (38 counting a hidden `__import__('time')` one),
plus `tools/headless_stub.py` (recording App/VJApi stand-ins; the full
controller constructs and runs headless against them) and
`tests/test_auto_vj_clock_seam.py`, whose equivalence test runs the
same scripted session under two absurd wall-clock constants and
asserts identical decision streams.

**Phase C part 1 also landed (2026-08-18, owner: "was there a phase 3
…? if not do that too"):** `tools/session_replay.py` (training-kit-01)
drives the **full AutoVJController** — mode state machine, phrase
clock, recommender, corpus writers — through sequential local files at
~25× real time, using the Phase B seam plus the recording app stub. A
now-playing source is emulated (track changes, `change_counter`,
position, and the round-three track-path hint bus, so
`bpm_agreement_report.py` can score the resulting corpus), the profile
surface is a real-Analyzer-backed AudioManager mirror (one-way-flow
rule preserved: `set_profile` touches the analyzer only, never a
tracker), and corpus rows come out stamped with **audio time**
(`capture_time`), feeding the existing packaging/LLM-scoring flow
unchanged. Replay corpora default under `logs/replay/`, deliberately
outside the `logs/` sweep `package_training_set.py` performs, and the
decision log defaults OFF for the same reason (see the cfg comment in
`run_session()`). First live check: a two-real-track session
auto-switched NORMIE→RAVER at 131 BPM and produced 409 sequence-corpus
rows. Covered by `tests/test_session_replay.py`.

**CRUISE-lock fix (2026-08-18, tuning-team report).** The first
Phase C.1 build had a timebase bug: `_startup_guard_until_t` was
stamped in `__init__` on the wall clock *before* `set_clock()` could
inject the audio clock, and since a wall-clock deadline (~1e9 s) never
expires on an audio clock (~1e2 s) — and the startup-grace check
returns out of the **entire** director action body — replayed sessions
produced healthy detector/profile/corpus output but zero director
activity (2h of house, all 16k rows CRUISE, drop_score averaging 0.669
with nothing acting on it). Fixed in auto-vj-01 rc.95 /
training-kit-01 0.25.1: the clock is now a **constructor** argument
(`AutoVJController(..., clock=)`), `set_clock()` re-stamps the guard as
a late-injection backstop, and the headless stub was made *reactive*
(it applies effect swaps and param writes back into its state — a swap
that never landed had the swap logic retrying every eligible tick) plus
three stub return-shape fixes the guard had been hiding. Post-fix
verification: the same 6-track playlist replay went from zero director
events to 21 mode transitions and 12 drop fires with
BUILD/DROP/BREAKDOWN all represented. The tuning team's detector-side
deltas (confidence/lock-coverage/churn vs. live sessions) are NOT
explained by this bug — the detector path sits above the guard — and
should be re-measured on matched track lists; note the 2 s `--gap`
does not trip the 15 s silence reset, so per-track cold starts are not
the mechanism either.

**Media-01 playlists work directly — no mixer involvement (correction,
2026-08-18).** The first close-out write-up lumped media-01 into the
Phase C part 2 dependency; the owner rightly pushed back ("media
player has its own cross-fade and isn't using the mixer's"). Correct
framing: media-01 playlists are ordered lists of local files
(`runtime/media_playlists.json`), which is exactly what the driver
plays — `session_replay.py --playlist 'training - house 01'` replays
one in playlist order today, reading the store read-only. The only
media-01 fidelity gap is its own crossfade blending (replay plays
sequential tracks with a silence gap instead of overlapping tails) —
minor for training purposes, and if it ever matters it's a media-01
question, not a mixer one. **Phase C part 2 proper** — dj-mixer-01
*auto-mix* as the source, i.e. the mixer's crossfade/stem engine
rendering the actual blended output on the audio-time clock — is the
only piece with a mixer-team dependency, and the owner is explicitly
not ready to make those mixer mods yet; it stays deferred.

**Fidelity finding worth knowing about (found while validating item
1):** the old `bpm_eval.py` loop stepped the tracker once per analyzer
block with `t` = the block start, which made onset-event times coincide
*exactly* with update times — an accidental gift to the detector's
100 Hz envelope, whose pulse placement quantizes against the update
clock. At the live 60 Hz cadence (what `stream_track()` now replicates)
pulse placement jitters by ±1–2 envelope bins exactly as it does live,
and sparse synthetic clicks score notably worse (e.g. the 120 BPM seed
click no longer locks) while real library tracks are fine (11/12
correct-fold on the first mixed dozen). Two consequences: seed-corpus
numbers re-baseline downward — that's the harness getting *honest*,
not the detector regressing — and there is a real, now-measurable live
weakness on sparse material (envelope placement could use ev_t-exact
writes rather than write-head placement; a v3-adjacent detector
candidate, do NOT fix casually — it moves every tuned ACF constant).
