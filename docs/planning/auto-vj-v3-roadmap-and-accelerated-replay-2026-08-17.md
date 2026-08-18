# Auto VJ v3 Roadmap + Accelerated Local-Track Replay — Plan (2026-08-17)

Owner: unicorn-viz
Status: planning only — no code; prepared while other VJ work is in
  flight, for the next iteration. Consolidates the v3-scoped threads
  scattered through `auto-vj-round-three-planning-2026-08-14.md`
  (§ 7.4/§ 7.6/§ 8.3/§ 9.1) into one place, and scopes the owner's
  priority item: **running tests with local tracks at an accelerated
  rate of time** (§ 9.1).
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
