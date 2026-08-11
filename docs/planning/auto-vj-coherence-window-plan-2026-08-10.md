# Auto VJ: Coherence-Window & Detector-Confidence Plan (2026-08-10)

Owner: unicorn-viz
Status: two experiments shipped tonight, riding along in an overnight
  session; judgment on further tuning deferred until that data exists
Last updated: 2026-08-10

## Context

Started from an LLM tuning recommendation (`favorites/b` session,
`tools/package_training_set.py`) suggesting `_V2_COHERENCE_WINDOW` `32 →
40` to fix a "tempo plausibility" issue. That causal link doesn't hold up
— `_V2_COHERENCE_WINDOW` governs phase-lock *confidence smoothing*, not
which BPM value the detector picks — and turned into a broader discussion
about the detector's confidence machinery: is `_V2_PHASE_TOL` (±18% of
beat period, the tolerance for counting an onset as "on-beat") too wide,
is the `0.4 ACF / 0.6 phase` confidence blend weighted correctly, and
whether a future v3 engine should weight an actual bass/kick-band hit
landing on the grid rather than treating every onset equally. See
`docs/adr/vj-system.md` § "Drop Score Bass-Gated Reweight" and its two
addenda for the full blow-by-blow (including a value that was tried and
reverted mid-session — worth reading before touching any of this again).

This doc is the write-up requested at the end of that discussion — status
of what shipped, what's still open, and what to watch for.

---

## Shipped tonight

### 1. `_V2_PHASE_TOL`: `0.18` → `0.12` (by way of a rejected `0.08`)

Owner's original ask was `0.08` — an aggressive cut, explicitly meant to
*generate* onset-jitter data rather than being a calibrated target, since
no such ground-truth data existed to pick a precise number. Verified
directly before committing to it: a mathematically perfect, zero-jitter
synthetic click track never registered a single phase hit in 120+
simulated seconds at `0.08` (`phase_confidence` stuck at exactly `0.0`,
capping overall confidence at `0.4` — the ACF-only floor — no matter how
long it ran). Root cause, as far as verified: the phase oscillator
advances at the tracker's own *estimated* BPM, not true tempo, so there's
always some small residual mismatch; at `0.18` that residual was
forgivable, at `0.08` it alone was apparently enough to keep phase
permanently out of tolerance — independent of any real off-grid content,
which was the actual thing being filtered for.

Reported before running an unattended overnight session on it (would have
burned a full night's data collection on a config that breaks convergence
outright, not just filters swing/human timing as intended). Owner chose
`0.12` instead; verified convergent the same way, though noticeably
slower than `0.18` — ~120s to fully stabilize in one tested scenario (124
BPM click track) versus the old ~65s baseline. Two existing regression
tests whose settle windows were empirically timed against the old
baseline needed extending to 130s
(`test_locked_bpm_does_not_drift_toward_mismatched_profile`,
`test_v2_drifts_toward_new_profile_but_v3_does_not`); a new
`test_phase_tol_012_converges_reliably_where_008_did_not` guards against a
future edit silently re-tightening past the point this breaks.

**Practical consequence for tonight's session and beyond:** expect real
sessions to take longer to reach full phase lock than they used to, not
just to be pickier about what counts as locked.

### 2. `_V2_COHERENCE_WINDOW`: `32` → `35`

Not an endorsement of the LLM's original `32 → 40` reasoning (rejected —
see Context). Owner chose to try a partial move toward that number anyway
as its own independent experiment ("kinda split the difference"),
unrelated in justification to the phase-tolerance change above.

### 3. New corpus capture: `acf_confidence` / `phase_confidence`, separately

Previously private-only (`BeatTracker._acf_confidence`/`_phase_confidence`)
— only the combined `confidence` was ever exposed anywhere (HUD, corpus,
decision log). Now public properties on `BeatTracker`/`BeatTrackerV3`, and
`_detector_snapshot()` (auto_vj.py) includes both, reaching every sequence
corpus row (heartbeat and keyframe alike, same mechanism as the mixer
track-meta capture from earlier the same day).

**Purpose:** the `0.4/0.6` confidence blend itself is deliberately *not*
touched this pass. Owner: "let's do that [rebalance] and make sure we're
getting the training data we can later judge by for further tweaking
after we first settle issues from point 1" — i.e. get real
`_V2_PHASE_TOL=0.12` session data with both confidence halves visible
before deciding whether `phase_confidence`'s `0.6` weight (owner's
suspicion: possibly too strong, "depends on what acf is i guess") needs to
move.

Versions: `_DETECTOR_VERSION` → `1.0.0-rc.5`, `_VJ_WEIGHTS_DOC_VERSION` →
`18`. Full detail in `weights-and-thresholds.md`'s Detector section and
changelog entry 18.

---

## What to watch in the overnight session

Directly answering the owner's question ("what precisely should i be
watching for the most obvious signals/impacts"):

1. **HUD BPM confidence** — `BPM: xxx (0.xx)`, the blended value. Watch
   for it reading lower or more volatile than usual on material that
   sounds solidly locked; that would suggest `0.12` is still catching real
   lock as "not quite on-grid," not just filtering genuinely loose timing.
2. **Lock churn** — `bpm_lock_gained`/`bpm_lock_lost` counts in the
   scorecard's "Lock event churn" line. Slower phase convergence could
   plausibly show up as more time spent below `_BPM_LOCK_CONFIDENCE`
   (0.55) before a lock registers, or more churn if confidence hovers near
   the acquire/release thresholds longer than before.
3. **Profile-switch frequency** — the scorecard's "VJ profile switches"
   count and the recommender's own accuracy report.
   `detector_trust` (a blend of `lock_rate`/`mean_dconf`) scales how large
   a score margin is required to confirm a switch — a noisier or lower
   confidence signal should show up as *more conservative, less frequent*
   switching, not just a raw confidence-number change. Fewer switches than
   a comparable prior session, especially early in a track, would be the
   tell.
4. **New corpus fields directly** — `acf_confidence`/`phase_confidence`
   per row, once packaged. Compare their distributions against `bpm` /
   `bpm_confidence` (the blended value already captured) to see whether
   phase genuinely lags ACF the way tonight's synthetic tests suggested,
   or converges close enough in practice not to matter for real tracks.

---

## Deferred, explicitly not done tonight

- **`0.4 ACF / 0.6 phase` confidence blend re-weighting.** Owner's
  suspicion (phase may be over-weighted, especially now that its own
  tolerance changed) is plausible but sequenced behind having real
  `acf_confidence`/`phase_confidence` session data to look at, per the new
  corpus capture above. Do not touch until that data exists and has been
  reviewed.
- **Drop/climax decision ladder tuning.** Separate concern raised the same
  conversation: "drop guy not doing so well i think lol... i think it's
  the thresholds not the reweighting..i think that was the right
  direction that might need tweaking but thresholds maybe could use some
  help." A blanket `+4%` raise across the whole ladder (see
  `docs/adr/vj-system.md`'s "Drop Score Bass-Gated Reweight" for the
  current table) was requested and then retracted mid-turn before any
  change was made ("ignore my request to raise the thresholds.. let's
  wait for more data"). Explicitly parked for tomorrow, pending the same
  overnight session's data. The reweight formula itself (`bass_flux_norm`/
  `band_blend` at 0.65 combined weight) is *not* in question — owner
  reads that as the right direction; only the five ladder values
  (floor/threshold/climax-entry/climax-early/fastlane × chill/normie/
  raver) are suspected of needing adjustment.
- **v3-scoped ideas, not started:**
  - Lower `_V2_PHASE_TOL` further than tonight's `0.12`, once real session
    data (not just synthetic clean-audio tests) shows where the real
    off-grid/on-grid boundary sits.
  - Revisit the ACF/phase confidence blend weights properly (not just the
    ratio — whether ACF's `min(1.0, acf_peak_ratio/3.0)` normalization or
    phase's rolling-hit-rate window are themselves the right *shape* of
    signal, not only their blend weight).
  - Add a dedicated term that specifically weights an actual drum/bass hit
    landing on the beat grid, rather than treating every onset (hi-hats,
    vocal consonants, chord attacks) equally for phase-coherence purposes
    — the same "bass presence should be load-bearing" philosophy already
    applied to `drop_score`'s bass-gated reweight, applied instead to the
    detector's own confidence. `bass_flux`/`bass_flux_fast` (already
    computed for `drop_score`) are natural candidate inputs.
  - Owner separately floated a proper v1-vs-v3 (or v2-vs-v3) A/B test
    ("time to do a v2/v3 a/b test because i see problems") as a more
    direct way to investigate engine-level behavioral differences than
    tweaking individual detector constants one at a time. Not scoped yet.

## Tomorrow's agenda, in order

1. Review the overnight session's scorecard + corpus against the "what to
   watch" list above.
2. Decide, from that data: keep `_V2_PHASE_TOL=0.12`, adjust further, or
   revert — and whether the `acf_confidence`/`phase_confidence` split
   supports rebalancing the `0.4/0.6` blend.
3. Separately, review the same session's drop/climax ladder behavior
   ("drop guy") and decide whether/how to adjust the five per-profile
   threshold values — reweight formula stays as shipped.
4. If both of the above raise more questions than they answer, that's the
   signal to scope the v2/v3 A/B test properly rather than continuing to
   tune constants one at a time.
