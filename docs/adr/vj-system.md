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

**Decision: BeatTracker v2 (ACF + phase-locked oscillator)**

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

**Decision: phase coherence over 32-onset rolling window**

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

**Decision: Schmidt trigger (hysteresis gate) for BPM lock events**

Rationale: a single threshold caused ~1,350 lock-gained / lock-lost events per
session when confidence hovered around the boundary.  The Schmidt trigger
reduced house churn to ~55 events/session (96% reduction).

Current thresholds (mirrored in packager `_BPM_LOCK_CONFIDENCE_FLOOR`):

| Constant | Value | Meaning |
| -------- | ----- | ------- |
| `_BPM_LOCK_CONFIDENCE` | `0.52` | Confidence must reach this to **gain** lock |
| `_BPM_LOCK_RELEASE_CONFIDENCE` | `0.28` | Lock held until confidence drops **below** this |
| `_BPM_LOCK_CONFIDENCE_FLOOR` (packager) | `0.45` | Rows counted as "locked" in scorecard / LLM payload |

The hysteresis band (0.28–0.52) spans the natural equilibrium at 0.375 so the
gate is stable during steady-state cruise.

**Do not narrow the band below ~0.20 width** — the natural 0.375 equilibrium
sits inside the band by design.

---

## Tactus Preference Ratio

**Decision: keep `tactus_preference_ratio` ≥ 0.50 for house/techno material**

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

**Decision: `tempo_hold_s = 10.0`**

Spotify crossfade overlaps last 5–12 s of a track with the incoming track.
During this window, the incoming track's onset pattern conflicts with the
current BPM estimate.  A 10 s hold bridges the overlap so the departing
track's tempo is maintained until the new track stabilises.

Default engine value: 6.0 s.  Overridden in `[auto_vj]` to 10.0.

---

## Audio Profile System

**Decision: two independent profile systems — do not conflate them**

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

## Superseded Decisions

| Date | Decision | Reason for reverting |
| ---- | -------- | -------------------- |
| 2026-06-20 | `tactus_preference_ratio = 0.42` (global) | 0.75× fold mapped 120 → 90 BPM for house; removed in same session |
| — | BeatTracker v1 as primary engine | v2 ACF is more robust; v1 kept as fallback only |

---

## Open Questions

- Should `tactus_preference_ratio` be per-AudioProfile rather than a global config key?
- Consider widening `phase_tol` to 0.22 to nudge the natural equilibrium above 0.40 (closer to the 0.52 lock threshold).
- Essentia BPM cross-validation not yet wired into the scoring pipeline.
