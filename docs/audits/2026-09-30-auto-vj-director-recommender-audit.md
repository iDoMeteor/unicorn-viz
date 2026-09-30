# Auto VJ director + recommender bug audit (2026-09-30)

Owner: DJ Unicorn Tears
Status: complete — all findings open; nothing fixed in this pass
Last updated: 2026-09-30

Companion to [2026-09-30-bug-audit.md](2026-09-30-bug-audit.md), which
covered core and every drop-in at a higher level.  This pass is a full,
line-by-line read of `drop-ins/auto-vj-01/auto_vj.py` (9,982 lines):
- the director state machine;
- mode scheduling and phrase snapping;
- drops, ping-pong, drift and the finale;
- the recommender's scoring, prefilter, matcher and decider;
- mood presets and the telemetry both subsystems write.

The detector (`beat_grid.py`) was read only at the interfaces the
director depends on: downbeat callbacks, `clear_pending`, and the signals
it exposes.

Versions audited:
- auto-vj-01 `1.0.0-rc.155`;
- `_DIRECTOR_VERSION` `1.0.0-rc.22`;
- `_RECOMMENDER_VERSION` `1.0.0-rc.50`;
- `_VJ_WEIGHTS_DOC_VERSION` 114.

No promoted `weights/recommender-weights.json` exists, so the code
defaults are live.

**Method.**
- Full read of both subsystems.
- Mechanical checks over the mood presets: inverted min/max pairs,
  zero values swallowed by `x or default` reads, and preset keys missing
  from `_PROFILE_SETTING_KEYS`.
- A per-profile scoring-offset check against the live weights.
- Harness reproductions using the same bare-controller style as the
  existing tests (`tests/test_director_phrase_snap.py`,
  `tests/test_genre_matcher.py`), driving the real methods.
- Findings marked **VERIFIED** were reproduced.  The rest are from reading
  the code and name the exact lines.  The repro scripts are in the audit
  seat under `/var/tmp/uv-bug-audit/` (`reco_stuck_full.py`,
  `mode_snap_stuck.py`).

**Baseline.** Every Auto VJ test in the core suite passes (84 files,
2,771 core tests green).  The two P1s below are not covered by any of
them.

**Fix-time obligations** (CLAUDE.md): most fixes here change live
director or recommender behaviour, so they bump `_DIRECTOR_VERSION` /
`_RECOMMENDER_VERSION` and `_VJ_WEIGHTS_DOC_VERSION`, update
`weights-and-thresholds.md` and add an ADR line in `docs/adr/vj-system.md`
in the same commit.

---

## Summary

| ID | Sev | Subsystem | One line |
|---|---|---|---|
| AV-1 | P1 | recommender | An active audio profile outside the BPM prefilter is compared against the runner-up (or against the winner itself), so the decider can never leave it — **VERIFIED**: a DnB set at 174 BPM never switches to `drum_and_bass` |
| AV-2 | P1 | director | Toggling Auto VJ off while a mode snap is pending blocks every later BUILD / BREAKDOWN / CLIMAX for the session — **VERIFIED** |
| AV-3 | P2 | director | A scheduled drop is never cancelled: it fires during a USER hold, mid-ping-pong, and into the next track |
| AV-4 | P2 | director | The phrase-snap grid is counted from when a track change was *detected*; the mixer section sync fixes the wrong counter |
| AV-5 | P2 | director | `impact_speed_factor` is never applied (target computed, never assigned) |
| AV-6 | P2 | director | USER mood never auto-starts any ping-pong, even on a raver base; core raver mode excludes tweaker |
| AV-7 | P2 | director | The timed finale can be lost for good (flag set before a downbeat-scheduled fire) |
| AV-8 | P2 | telemetry | `analyzer_refractory_s` has always logged 0.0: the audit-T4 instrument never worked |
| AV-9 | P2 | both | The mood and genre selectors share one decider flag, so each silently releases the other's lock |
| AV-10…AV-18 | P3 | both | See the P3 table |

---

## P1

### AV-1. The decider cannot leave an out-of-range audio profile — VERIFIED

**Where:**
- `_update_profile_recommendation`, `auto_vj.py:7447-7484`.
- `_maybe_apply_recommended_audio_profile`, `auto_vj.py:7667-7680`.

**What happens:**
- The BPM hard prefilter (rc.20, unconditional since rc.36) drops every
  profile whose hint band ±4 BPM doesn't contain the detector's tempo.
  The active profile is usually one of those dropped when the music
  changes genre.
- If the active key isn't among the scored candidates,
  `current_score`/`current_prob` fall back to the **runner-up**, or to
  the **winner itself** when only one candidate is eligible
  (`candidates[1] if len(candidates) > 1 else best`).
- With a single eligible candidate: margin = `best_prob − best_prob` = 0,
  so the normal path never confirms.  The fast path needs
  `current_prob ≤ 0.05`, but `current_prob` is the winner's 1.0.
  Nothing can fire.
- With several eligible candidates: the margin is measured against the
  runner-up instead of against a profile with probability 0.  A close
  race between two in-range genres therefore holds an ineligible profile
  in place.
- This is exactly the case the prefilter was added for (owner, 2026-09-04:
  "the chosen genre MUST be within the bpm range").

**Where it bites:** with the shipped profiles and margin, exactly one
profile is eligible at 143–150 BPM (`dubstep`) and at 165–179 BPM
(`drum_and_bass`).  Arriving at either tempo range from any other
profile, the recommender *names* the right genre on the HUD and never
applies it.

**Evidence:** the real `_update_profile_recommendation` and decider, all
enabled profiles, shipped decider defaults, detector locked at 174 BPM,
20 evals.  Starting from `house`, `techno` or `dubstep`: `drum_and_bass`
is recommended every eval, and the active profile never changes (0
`set_profile` calls).  In the three-profile fixture at 124 BPM, the same
thing happens with `house` as the only eligible profile.

**Fix direction:**
- When the active key was excluded by the prefilter, treat
  `current_prob = 0` and `current_score = −inf` for gating (keep a
  display value separately).
- Arguably, apply the in-range winner through the fast path directly.
- Test all three shapes: single eligible, close race, and fallback-to-all.

### AV-2. One off/on toggle can end all mode changes for the session — VERIFIED

**Where:**
- `toggle()`, `auto_vj.py:5286-5326`.
- `_schedule_mode_transition()`, `auto_vj.py:8337-8374`.

**What happens:**
- Build, breakdown and climax entries are deferred (E6/E8; shipped unit
  `phrase`).  `_schedule_mode_transition()` sets `_mode_snap_pending =
  True` and queues a downbeat callback.
- Only that callback's `_fire()` clears the flag.
- `toggle()` (off) calls `self._grid.clear_pending()`, discarding the
  callback, and resets `_drop_pending`, but not `_mode_snap_pending`.
- After re-enabling, every `_schedule_mode_transition()` returns at its
  first line.  The director is stuck in whatever mode it is in (CRUISE
  after a toggle) for the rest of the session.
- Middle-click, `Ctrl+Alt+J`, the Control Room button and the config row
  all toggle.  A snap is pending for 1–3 bars after every scheduled entry.

**Evidence:** the harness schedules a build, calls the real `toggle()`
twice, then feeds 16 bars of valid build evidence and downbeats: 0 mode
entries, flag still `True`, 0 queued callbacks.

**Fix direction:**
- Reset `_mode_snap_pending` alongside `_drop_pending` in `toggle()`.
- Better: give both flags one "cancel all deferred director actions"
  helper, used by toggle, track change (AV-3) and ping-pong entry.

---

## P2

### AV-3. A scheduled drop is never cancelled

**Where:**
- `update()`: downbeat callbacks run inside `self._grid.update()` at
  `auto_vj.py:5431`, **before** the `user_busy` / `paused` / warmup early
  returns at 5540-5553.
- `_schedule_drop` / `_fire_drop`: `auto_vj.py:8576-8699`.
- `_reset_phrase_clock_for_track_change`: `auto_vj.py:8131-8144`.

**What happens:** with the shipped phrase snap (4 bars) and bass gate
(up to 4 retries), a drop can fire ~8 bars (~15 s at 128 BPM) after it
was scheduled.  `_fire_drop()` checks neither mode nor state, and nothing
but `toggle()` cancels it.  So:
- **USER hold:** the operator picks an effect by hand, and within the
  3 s grace a pending drop swaps it out and fires post-FX and overlays.
- **Ping-pong:** entering ping-pong doesn't cancel the drop.  It fires
  mid-run, logs a phantom PINGPONG→DROP transition (which
  `_exit_pingpong` later overwrites), and its effect swap goes through
  `goto_effect`, which unpins the pair in core.
- **Track change:** bar counters reset, but the pending drop survives.
  It fires into the next track's intro and still passes re-validation,
  because `_drop_pending_score` was captured on the old track.  It also
  sets `_last_drop_bar`, which uses up the new track's first-drop
  bass-gate exemption and disables its E4'' rescue.
- A phrase walk still in progress also counts bars against the old
  track's grid.

**Fix direction:**
- Cancel pending drop and mode snaps on track change and on ping-pong
  entry.
- In `_fire_drop`, bail when `vj_api.is_user_busy()`, the mode isn't a
  drop source, or the track id changed since scheduling (stamp it at
  schedule time).

### AV-4. The phrase grid is counted from track-change detection, not the track's bar 0

**Where:**
- `_bars_since_track_start` is used for every snap (`auto_vj.py:8346`,
  `8588`) and reset on track change (`8141`).
- `_maybe_sync_phrase_clock_from_section_hint`: `auto_vj.py:8102-8125`.

**What happens:**
- Every drop and mode snap computes
  `to_boundary = unit − bars_since_track_start % unit`, counting bars
  from the first downbeat after the change was detected.
- After a hard deck cut, the app starting mid-track, or detection lagging
  the real start, that grid is offset from the music's real 8-bar grid by
  an arbitrary amount.
- The mixer-hint sync exists for exactly this case.  It corrects
  `_bars_since_phase_entry` from the mixer's `bars_in`, but never
  `_bars_since_track_start`, the counter the snaps actually use.
- The shipped E1/E6 alignment gains were measured on replays that start
  at bar 0, so they don't show this.

**Fix direction:** when a confident section hint arrives, also set
`_bars_since_track_start` from the mixer's absolute bar position.  The
mixer would need to publish one (`bar_index`), or it could be derived
from `bars_in` plus the section start.

### AV-5. `impact_speed_factor` is never applied

**Where:** `_run_param_drift`, `auto_vj.py:9565-9572`.

**What happens:**
- The DROP and CLIMAX branches compute `forced_speed` and assign
  `_param_target_speed`.
- The IMPACT branch computes `forced_speed` and stops there.
- Speed is mode-locked in IMPACT (`speed_mode_locked`), so no new target
  is drawn either.  Speed stays wherever BUILD or CRUISE left it.
- Major-tier drops go straight to IMPACT (`_fire_drop` → `_enter_impact`),
  so the tuned 1.5× surge (`impact_speed_factor`) never happens.

**Fix direction:** assign the clamped target as the other two branches
do.  This is a live-behaviour change, so it's a director version bump.

### AV-6. USER mood never auto-starts ping-pong; tweaker isn't "raver mode"

**Where:**
- `auto_vj.py:9117`, `9141`, `9296`.
- Core `app.py:7299`, `7315`.

**What happens:**
- The three auto-start gates test
  `self._profile in ('raver', 'tweaker')`.  In USER mood `_profile` is
  `'user'` whatever the base preset (`_profile_preset`), so a USER mood
  built on raver or tweaker never auto-starts effect, preset or post-FX
  ping-pong, even though the enable flags were read from that base.
- Core sets `_raver_mode_active` only for exactly `'raver'`, so tweaker
  ("raver with everything pushed further") and USER:raver don't get it.
  Metaballs is the only reader today.

**Fix direction:** key both on `_profile_preset`, not `_profile`.

### AV-7. The timed finale can be lost for good

**Where:** `_check_timed_finale`, `auto_vj.py:9906-9918`.

**What happens:** `_timed_finale_fired = True` is set, then the actual
trigger waits for the next downbeat.  The trigger is lost, and never
retried, if:
- Auto VJ is toggled off in between (`clear_pending()`), or
- no downbeat arrives, e.g. the music has already stopped.  That is the
  likely state when the mixer publishes `seconds_left = 0` at set end, or
  in an unattended run where `auto_exit_after_finale` then exits after
  the 20 s grace with no finale.

**Fix direction:**
- Set the flag inside `_fire`.
- Fall back to firing immediately if no downbeat arrives within about a
  bar.

### AV-8. `analyzer_refractory_s` has always logged 0.0

**Where:** `_audio_profile_snapshot`, `auto_vj.py:6742-6745`.

**What happens:**
- The field reads `getattr(manager, 'refractory_s', 0.0)` on the
  **AudioManager**.  Only `Analyzer` has `refractory_s`
  (`unicornviz/audio/analyzer.py:516`), so the value is the getattr
  default on every row since it was added (2026-08-14).
- This was the instrument for the audit-T4 hypothesis: a wrong lock
  entrenching itself by thinning the onset stream through the refractory.
- Any analysis reading "the refractory never engaged" from the corpus is
  a false null.  This is the pattern the null-results rule warns about.
- It also reaches into `app._audio_manager` (a private field) where a
  `vj_api` surface would be the rule.

**Fix direction:**
- Expose `refractory_s` on AudioManager, forwarded from the analyzer
  (and published in the audio-process shadow).
- Add a test asserting the field is non-zero with a confident BPM fed in.

### AV-9. The mood and genre selectors release each other's locks

**Where:** `cycle_profile` / `cycle_audio_profile`,
`auto_vj.py:4606-4680`.

**What happens:** both selectors drive the single
`_profile_auto_reco_decider_enabled` flag.
- Choosing a manual *mood* (chill/normie/…) silently switches off genre
  auto-recommendation.
- Cycling mood back to `auto` silently releases a manual *genre* lock,
  while `_manual_audio_profile` still shows the old pick, so the next
  `Alt+A` continues from a state that no longer holds.
- The docstring owns the coupling, but the operator sees two independent
  selectors.
- Also: the MIDI action labelled "Cycle audio profile" is bound to
  `cycle_profile` (the mood cycle).

**Fix direction:** two flags, one per selector; the genre decider runs
only when the genre selector is on `auto`.  Relates to the open
"correction vs lock" item.

---

## P3

| ID | Where | Finding | Fix direction |
|---|---|---|---|
| AV-10 | `auto_vj.py:5972-6034` | BUILD has no exit on an energy plateau.  It ends only via a drop, a breakdown, or a timeout-drop that itself needs `sustain ≥ 0.65 × entry`.  A long mid-energy section can hold BUILD indefinitely, and the HUD reads "Action in 0s". | A non-drop timeout back to CRUISE after `build_max × k`. |
| AV-11 | `auto_vj.py:9167` vs `8987` | Preset ping-pong's `projectm_preset_pingpong_min/max_swaps` are dead: `_maybe_start_preset_pingpong` sets the budget, then `_enter_pingpong(auto_started=True)` overwrites it with the effect ping-pong budget. | Pass the budget into `_enter_pingpong`. |
| AV-12 | `auto_vj.py:9395-9400`, `9440-9445`, `9379`, `9465` | "Chance" knobs roll **every frame** behind a cooldown: projectM preset changes in BUILD/CLIMAX land on a ~12 s beat, and raver post-FX ping-pong starts the moment each 45 s cooldown ends.  `projectm_preset_on_event_chance` and `postfx_pingpong_trigger_chance` barely matter there.  (DROP/IMPACT roll per event, which is correct.) | Roll once per opportunity, or convert the chance to a per-second rate. |
| AV-13 | `auto_vj.py:3892-3920`, `3143` | Mood switches re-read tunables as `float(v or self._old)`, so a new mood's explicit `0` keeps the *previous* mood's value.  Chill/normie set both trigger chances to 0.0; the enable flags gate them off today, but a USER override of 0 is ignored.  Also, the config-menu "Detector log: 0 = off" works live but comes back as 1.0 after a restart (`or 1.0`). | `v if v is not None else default`. |
| AV-14 | `auto_vj.py:5286-5326` | Toggling off mid ping-pong leaves `_pp_active`/`_pp_pinned` set (the core pinned pair stays alive while Auto VJ is off) and `_ppfx_active` stale (an immediate catch-up swap on re-enable). | Exit both ping-pongs in `toggle()`. |
| AV-15 | `auto_vj.py:6128` vs `5273` | DROP's cooldown exit uses the unscaled `_drop_cooldown_s`, while the HUD ETA and every other hold scale by `timing_scale`, so "Action in" is wrong during DROP. | Pick one and apply it to both. |
| AV-16 | `beat_grid.py:579-583`, `3653-3657`, `6660-6664` | Downbeat callbacks run under a bare `except: pass`, so a bug inside a deferred drop, mode entry or finale is invisible. | Throttled DEBUG log, as `_debug_throttled` does. |
| AV-17 | various | Small correctness nits: <br>• track-change detection uses `int(change_counter or -1)` (`5375`), the falsy-0 bug fixed elsewhere in 2026-08-15;<br>• the `drop_cancelled` mark hard-codes `mode=_BUILD` (`8710`);<br>• `_drop_rel_path` can carry into the next scheduled drop (`5945`, `5996`);<br>• `score_profile_candidates` silently drops a candidate that raises (`1708-1712`);<br>• `_kick_phases` isn't cleared on track change, so the previous track's 16 phases shape the next track's kick regularity. | Individually trivial. |
| AV-18 | `auto_vj.py:1747-1801`; `3038` | Latent scoring asymmetry: since the −log σ normalizer, a profile *missing* a mu scores 0.0 on that term while one that has it scores `−log σ − ½x²` (e.g. +1.9 at σ=0.15 before weighting).  Every enabled profile carries every mu today, so this is not live, but the next profile added without one gets a silent bias.  Separately, the decision-log `log_dir` default is `__file__`-relative, ignoring `UNICORNVIZ_APP_ROOT` (the 09-05 O11 class). | Assert at load that every enabled profile defines every weighted mu; derive `log_dir` from the app root. |

Checked and **not** bugs:
- `_exit_drop()` → breakdown is only reached from DROP, where breakdown
  is allowed.
- The mixer doesn't republish a borrowed BPM, and the hint bus expires at
  5 s, so there is no priming echo loop.
- Every division by BPM or duration is guarded.
- The mood presets have no inverted min/max pairs, and every preset key is
  in `_PROFILE_SETTING_KEYS`.
- Config aliasing: `_cfg` is a shallow copy, so menu edits don't leak
  into core `Config`.

## Correction to the main audit

P1-4 of [2026-09-30-bug-audit.md](2026-09-30-bug-audit.md) lists Auto VJ's
`render_celebration_overlay()` among the unguarded render-phase calls.
The call site in `app.py` is unguarded, but the method wraps its own body
in try/except (`auto_vj.py:9700-9707`), so that item carries less risk
than listed.  The other items in P1-4 stand.
