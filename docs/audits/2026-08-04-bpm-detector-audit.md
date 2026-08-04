# Unicorn Viz — BPM Detector Audit: the "Consistently 20 Hot" Bug (2026-08-04)

Owner: owner + Claude (master coordinator)
Status: Fixes landed (P0-A, P0-B, P1-C, P1-D, P2-E) — see
  [docs/adr/vj-system.md § "BPM Detector Audit — Hard Clamp Removal +
  Mixer-BPM Hint Bus"](../adr/vj-system.md#bpm-detector-audit--hard-clamp-removal--mixer-bpm-hint-bus-2026-08-04)
  for the implementation record. P2-F regression tests:
  `tests/test_bpm_detector_audit_regressions.py`.
Last updated: 2026-08-04

Symptom (owner-reported): live BPM consistently ~20 high, spiking to +32
(observed this morning, session `logs/unicornviz_20260804_082732.log`);
genre recommendation frequently wrong at the same time. "Dialed in" in the
v1 era; degraded for roughly a month despite the 2026-07-18 BeatTrackerV3
fix. Related ADR history: [docs/adr/vj-system.md](../adr/vj-system.md).

**Verdict: the detector's math is fine. The system around it force-feeds it
a wrong answer.** Genre profiles carry narrow *hard* BPM search windows; the
profile recommender applies them automatically; its tempo evidence is
computed inside the very window it applied — a self-confirming feedback
loop the tracker cannot escape, because every escape mechanism (tactus
descent, full-range ACF, silence reset) is disabled or neutered by the
clamp. The one authoritative tempo source in the building (dj-mixer deck
analysis) is published on the hint bus and never consumed.

---

## 1) The mechanism, end to end

### 1.1 Hints became hard caps — 2026-06-20 (`9d7e631`, auto-vj-01)

"Fix set_profile() to apply AudioProfile bpm_hint_min/max as search caps"
changed profile hints from a *soft* log2-Gaussian prior into **hard clamps
on the ACF candidate space**, in **all three engines** (legacy v1:
`beat_grid.py:387-390`; v2: `beat_grid.py:1262-1267`; v3 inherits and
deliberately keeps them while locked: `beat_grid.py:1400-1408`). This date
matches "failing for a month or so" — and because the caps were added to
v1 too, going back to the v1 engine cannot restore the dialed-in behavior.
Before this commit, a wrong genre could only *nudge* the tempo (broad
prior, σ=0.55 log2); after it, a wrong genre *dictates the answer's range*.

### 1.2 The windows are narrow and often disjoint (`unicornviz/audio/profiles.py`)

House 120-128 · Tech House 122-130 · Peak-Time 126-136 · Trance 134-142 ·
Psytrance 140-149 (σ=0.16) · Hard Techno 142-154 · Hardstyle 145-165
(σ=0.16) · **Generic (the default!) 108-132** · Ambient 84-116.

Psytrance∩Generic = ∅. A profile flip teleports the search range; the
currently locked BPM is often *outside the new window entirely*, so the
tracker is forced to re-lock somewhere inside it. A 116 BPM track under a
Psytrance clamp can only read 140-149: **+24 to +33 — the observed "+32."**
A 124-128 track under Trance/Hard-Techno windows reads +10 to +26 — the
observed "~20 hot." Under Generic, anything slower than 108 (hip-hop, most
ambient) or faster than 132 is *unrepresentable*.

### 1.3 The escape hatches are all disabled by the clamp (`beat_grid.py`)

- **Tactus descent skips out-of-range candidates**: the octave-down /
  2-3 / 3-4 correction `continue`s when `cand_bpm < self._bpm_min`
  (`beat_grid.py:1041-1043`) — the exact mechanism that would bring a hot
  lock back down is turned off by a raised hint floor.
- **Post-EMA hard clip**: `self._bpm = np.clip(self._bpm, self._bpm_min,
  self._bpm_max)` (`beat_grid.py:1164`) — even a correct EMA gets forced
  into the window.
- **The candidate array itself is rebuilt over the clamped range**
  (`_setup_acf_arrays`, `beat_grid.py:660-683`), so `argmax` literally
  cannot see the true tempo, and…
- **…the silence/track-change reset does not restore the range.**
  `_reset_tempo_lock()` zeroes bpm/confidence but the clamped lag array
  persists — the *next track cold-locks inside the previous track's wrong
  window* until the recommender changes profile again. This is why the
  error survives across songs and whole sessions.

### 1.4 The recommender feeds on its own clamp (`auto_vj.py:3110-3131, 3196+`)

The two strongest tempo features in profile scoring are computed from
clamped data:

- `tempo_fit` — Gaussian fit of *detected-BPM history* against each
  profile's μ. Once clamped to 140-149, detected BPM sits at ~145, so
  Psytrance/Hard-Techno/Hardstyle outscore the truth *by construction*.
- `top_cand_fit` — fit against `grid.top_candidates`, which are the top-3
  of the **clamped** score array (`beat_grid.py:1167-1177`). The true tempo
  can never appear as a candidate hypothesis once excluded from the range.

Result: wrong-fast profile → clamped-fast BPM → tempo features confirm the
wrong-fast profile → repeat. The decider then applies it
(`_maybe_apply_recommended_audio_profile`, `auto_vj.py:3327+`, default ON,
20 s cooldown), and the analyzer's per-genre onset tuning is mis-set too
(`manager.set_profile` → `analyzer.set_profile`), degrading onset quality —
the likely reason **genre accuracy collapsed at the same time as BPM**.

### 1.5 The gate is inverted (`auto_vj.py:_sync_grid_audio_profile`, 2828-2830)

The profile→tracker push (12 s hold) requires `grid.confidence >= 0.35` to
proceed — i.e. **a confident, usually-correct lock is the precondition for
applying the clamp that corrupts it**. Low confidence (when a re-prime
might actually help) blocks the push.

### 1.6 v3 fixed the wrong half (2026-07-18, `19cac72`)

The prior "20 BPM hot" investigation correctly found *prior re-priming
drag* and froze the prior while locked (`BeatTrackerV3`,
`beat_grid.py:1392-1413`) — but **explicitly kept applying the hint-range
clamp while locked** ("a genuinely wrong tempo can still be corrected or
bounded"). The clamp is the stronger force; freezing the prior while
leaving the clamp is why v3 shipped and the symptom continued unchanged.

### 1.7 The authoritative answer is on the bus, unread

`dj-mixer-01` publishes its deck-analysis BPM (`vj.publish_bpm('dj_mixer',
eng.bpm)`, `dj_mixer_controller.py:932`) — decimal-accurate, from the
offline analyzer the owner calls "way more than enough analysis."
**Nothing in auto-vj-01 ever calls `get_bpm()`** — the only consumer is the
mixer itself, which *borrows auto-vj's estimate when idle*
(`dj_mixer_controller.py:934-936`). The ground truth flows away from the
detector; the corrupted estimate flows toward the mixer.

### 1.8 Live evidence — this morning's session

`logs/unicornviz_20260804_082732.log`: recommender-driven (no hotkey line)
profile thrash `Generic → Psytrance → Generic → Psytrance` within 80 s
(09:09:18-09:10:31), each Psytrance apply priming the tracker with
`μ=145 σ=0.16` and window [140-149] — during the period the owner reports
reading "32 over." (The 08:29 flurry is Alt+A hotkey cycling — manual,
distinguishable by the `unicornviz.hotkeys` lines.)

---

## 2) Why v1 "once upon a time" was dialed in

Pre-2026-06-20, `set_profile()` set only the octave-symmetric log2 prior
(σ≈0.55 — broad), the ACF always searched the full 60-200 range, tactus
descent could always reach the slower lane, and the recommender didn't
exist as an auto-decider. A wrong genre cost a mild bias, not a mandate.
Every subsequent regression traces to making genre *authoritative over*
tempo, when the causality the system needs is tempo (measured) *informing*
genre (inferred).

---

## 3) Proposed fixes (none applied — for owner sign-off)

**P0-A — Demote hints back to soft evidence.** Remove the hard
search-range clamp from `set_profile()` in all engines (keep the log2
prior; optionally tighten σ slightly when a profile is high-confidence).
The ACF must always search the full 60-200 lane so the truth is always
representable. This single change breaks the feedback loop's spine.

**P0-B — Consume the mixer's BPM.** In auto-vj, read
`vj_api.get_bpm(exclude='auto_vj')` each recommender cycle; when a fresh
`dj_mixer` hint exists (deck playing, analyzed track), treat it as ground
truth: prime/lock the tracker to it (tight prior at the deck BPM) and feed
it to the recommender's tempo features. The DJ's deck analysis should
short-circuit all of this whenever it's available.

**P1-C — Unclamp the recommender's evidence.** Compute `top_candidates`
from an unclamped copy of the score array (full-range), so profile scoring
always sees the true tempo hypothesis even if a lock-side prior is active.

**P1-D — Finish v3's freeze.** While confidently locked, skip the range
clamp too, not just the prior re-prime (make v3's `set_profile` a full
no-op except when unlocked — and on `_reset_tempo_lock()`, restore the
full-range arrays so a new track never cold-locks inside a stale window).

**P2-E — Profile data hygiene.** Remove hints from Generic (it's a
fallback, not a genre); widen or remove σ=0.16-0.22 floors (tightest
priors belong to the *most confusable* genres right now); re-check the
promoted recommender weights after C lands (they were fitted on clamped
corpus data — `bpm`/`top_candidates` columns in every corpus row since
06-20 are contaminated by this bug, so any offline fit on them inherits it).

**P2-F — Regression tests** (auto-vj-01): (1) locked at 124 with high
confidence + Psytrance profile applied → reported BPM stays within ±2 of
124; (2) silence reset after a clamped profile → next lock on a 100 BPM
click is 100±2; (3) recommender never flips profile twice within its
cooldown on a steady synthetic track.

Per the ADR rules, whichever fixes land must update
`docs/adr/vj-system.md` (set_profile semantics + the hint-bus decision)
in the same commit, and any change to what analysis writes does **not**
apply here (live detector only — no `ANALYSIS_VERSION` bump needed).

---

## Session log

- Date: 2026-08-04. Method: full read of `beat_grid.py` (all three
  engines), recommender + profile-sync + decider paths in `auto_vj.py`,
  `unicornviz/audio/profiles.py` hint tables, hint-bus plumbing in
  `app.py`/`vj_api.py`/`dj_mixer_controller.py`, ADR history, git history
  of auto-vj-01 since 2026-06-15, and this morning's session log.
- No code changed; no config changed. Diagnosis + fix plan only.
