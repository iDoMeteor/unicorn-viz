# ADR: VJ System — Beat Detection & Profile Architecture

Owner: unicorn-viz maintainers
Status: Active
Last updated: 2026-06-20

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
available as fallback but is not tuned for current genre targets.

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

ACF blend: `self._confidence = 0.4 * acf_conf + 0.6 * self._confidence` — ACF
peak ratio is secondary; phase coherence is primary.

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

Default engine `tempo_hold_s`: 6.0 s.  Overridden in `[auto_vj]` to 10.0.

`silence_reset_s` (2026-06-20): `_reset_tempo_lock()` fires after this many
seconds with no detected onsets, zeroing `bpm` and `confidence`.  Default 2.0 s
was shorter than a typical Spotify crossfade gap, causing 53% of peak_time
sequence rows to show `bpm=0.0` mid-session.  Raised to 15.0 s in `config.toml`
so the detector holds its tempo through the full crossfade window without
resetting.

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

### 2. VJ mood profiles (director)

Set with `Ctrl+J` → `M`.  Called **moods**: `chill`, `normie`, `raver`.
Controls director visual intensity and transition aggression.
**Has no effect on BPM prior or detection range.**

These systems are independent.  Audio profile ≠ VJ mood.

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

---

## Open Questions

- Should `tactus_preference_ratio` be per-AudioProfile rather than a global config key?
- Consider widening `phase_tol` to 0.22 to nudge the natural equilibrium above 0.40 (now closer to the 0.55 gain threshold).
