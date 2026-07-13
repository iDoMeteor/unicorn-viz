# ADR: VJ System — Beat Detection & Profile Architecture

Owner: unicorn-viz maintainers
Status: Active
Last updated: 2026-07-13

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

ACF blend (2026-07-06 fix — see "Confidence Blend" section below for the
bug this replaced):
`self._confidence = 0.4 * self._acf_confidence + 0.6 * self._phase_confidence`,
where `_acf_confidence` and `_phase_confidence` are each persisted
independently and recomputed whenever either input signal updates — so the
blend can no longer be silently discarded by whichever signal updates last.

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

`tempo_hold_s`: **now the code default `10.0`** (`beat_grid.py`). Was `6.0` with
config.toml overriding to `10.0`; baked as the default 2026-07-13 (see the
2026-07-13 entry below).

`silence_reset_s` (2026-06-20): `_reset_tempo_lock()` fires after this many
seconds with no detected onsets, zeroing `bpm` and `confidence`.  Default 2.0 s
was shorter than a typical Spotify crossfade gap, causing 53% of peak_time
sequence rows to show `bpm=0.0` mid-session.  **Now the code default `15.0`**
(`beat_grid.py`), so the detector holds its tempo through the full crossfade
window without resetting (baked 2026-07-13).

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

**Note (table above is stale):** the table predates the current 20-profile roster (see
`unicornviz/audio/profiles.py` for the authoritative list) and even shows outdated σ values for
`house`/`chillstep`; not rewritten here as out of scope for this entry.

**`rap`/`hyphy`/`r&b` bpm_hint gap fixed (2026-07-08):** these three were the only profiles in the
entire roster with no `bpm_hint_min`/`bpm_hint_max` set at all — meaning their ACF search ran the
full unconstrained `60-200` BPM range (`_V2_BPM_MIN`/`_V2_BPM_MAX` in `beat_grid.py`) relying only
on the soft Gaussian prior, while every other profile hard-caps its search to an 8-40 BPM window.
Discovered while investigating a live Detroit techno (120-135 BPM) track locking the recommender
into `hyphy` despite having no vocal content — the uncapped search meant techno's tempo wasn't
rejected outright, only mildly penalized by the prior (~1.3-1.6σ off-center). Fixed by wiring each
profile's hint range to the tempo pocket already documented in its own code comment: `rap` 70-100,
`hyphy` 90-110, `r&b` 75-100. This is a search-range fix, not a fingerprint fix — it does not by
itself solve non-vocal tracks matching the vocal-forward spectral shape (see the HNR/FMR vocal-
detection work below).

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

## Confidence Blend Bug — `_acf_confidence` / `_phase_confidence` split (2026-07-06)

Decision: split `self._confidence`'s two inputs into independently-persisted fields

**Problem:** `_absorb_onset()` set `self._confidence = sum(coherence_buf) / len(coherence_buf)`
(raw phase coherence) on **every onset**.  `_estimate_tempo_acf()` set
`self._confidence = 0.4 * acf_conf + 0.6 * self._confidence` (the documented ACF blend), but only
when a full ACF update completes — throttled to 1-in-`_V2_ACF_INTERVAL` (8) frames and further
gated by several early-return guards (ambiguous score, low update confidence, tempo-hold window,
candidate-persistence check, jump guards).  Because onsets arrive far more often than completed
ACF updates in real audio, the ACF's contribution was overwritten by the very next onset almost
immediately — the blend was real for a few milliseconds and then vanished.  Effectively:
`confidence` was pure phase coherence in practice, matching the "structural equilibrium ~0.375"
finding above; the ACF peak-ratio signal barely registered downstream.

This same root cause corrupted `_compute_downbeat_confidence()` (analysis mode): its `coh` term
(`sum(coherence_buf)/len(...)`, freshly recomputed) and `base` term (`self._confidence`) were
mathematically identical at call time in the overwhelming majority of frames, since nothing
touches `self._confidence` between the last onset absorption and the downbeat check within the
same beat interval.  The nominal `0.45 * region + 0.30 * coh + 0.15 * base + 0.10 * density`
four-way blend was actually `0.45 * region + 0.45 * (one signal, counted twice) + 0.10 * density`
— phase coherence at ~90% effective weight, region consistency at ~45%, ACF quality contributing
essentially nothing distinguishable from coherence.

**Fix:** two persisted fields, `self._phase_confidence` (refreshed every onset in `_absorb_onset`)
and `self._acf_confidence` (refreshed immediately after `acf_conf` is computed in
`_estimate_tempo_acf`, *before* any of the function's early-return guards — so it updates even on
frames where the guards ultimately reject a BPM change).  `self._confidence` is recomputed as
`0.4 * _acf_confidence + 0.6 * _phase_confidence` at both update sites, so the public property
always reflects the freshest value of both inputs instead of one silently clobbering the other.
`_compute_downbeat_confidence()` now reads `coh = self._phase_confidence` and
`base = self._acf_confidence` directly — four genuinely independent signals as originally
designed. `_reset_tempo_lock()` clears both new fields alongside `self._confidence`.

**Verification:** git-blame traced `_compute_downbeat_confidence` to its introducing commit
(`1e91f4f`, 2026-05-22) — the double-count was present from day one, not a later regression.
Confirmed post-fix with a synthetic 130 BPM onset stream: `_acf_confidence` and
`_phase_confidence` diverge (1.0 vs 0.34 in one run), where pre-fix they were provably identical
by construction.

---

## Analysis Mode — enabled for supervised testing (2026-07-06)

Decision: `analysis_mode_enabled = true`, `analysis_downbeat_confidence_min` lowered `0.55 → 0.42`

Analysis mode (beat-position map, region consistency, real downbeat-confidence gating on
`is_downbeat`, and a stricter region-consistency check on large tempo-lane jumps) had never run in
production — `analysis_mode_enabled` defaulted `False` and was absent from `config.toml`.  Real
confidence percentiles from three live sessions (`logs/autovj-202607*.jsonl`, 1,832 / 6,216 /
43,434 ticks): p50 0.41–0.47, p75 0.57–0.59, p90 ~0.625.  With phase coherence carrying ~45%
effective weight in the blend (see previous section) and typical values sitting at that median,
the un-fixed formula would gate `is_downbeat` closed on roughly half of all beats at the old 0.55
threshold — since `schedule_for_next_downbeat()` is how BUILD/DROP/IMPACT/CLIMAX transitions
actually fire, that risked the director going silent, not just less precise.

**Fix order matters:** the confidence-blend fix (above) had to land first — enabling analysis mode
against the still-broken formula would have tested a blend where 90% of the "four-way" mix was one
double-counted signal, producing misleading results.  With the blend fixed, `0.42` is set as a
training-start value just below the observed real coherence median, not a validated final number —
there is still no production data on the `region` or `density` terms (analysis mode has never
logged them live).  Revisit this threshold once a supervised session's real distribution is in
hand; see `docs/audits/2026-07-06-vj-training-systems-audit.md` P1-4 / Phase 2 step 8.

---

## Downbeat Confidence Gate — 0.42 → 0.35 → 0.30 after live validation (2026-07-08)

Decision: `analysis_downbeat_confidence_min` lowered `0.42 → 0.35 → 0.30`

The `0.42` training-start value above was never validated against production `is_downbeat` firing
behavior — only against a raw confidence percentile. A new HUD element (a downbeat pulse dot next
to the BPM label, driven directly by `_grid.is_downbeat`) let the operator watch the gate live for
the first time, and it showed `is_downbeat` **not firing at all** in a real session at `0.42` — a
hard failure, not a soft near-miss.

A quantitative pass over ~22k post-fix decision-log ticks (2026-07-06 through 2026-07-08, spanning
56 sessions) confirmed it: `downbeat_confidence` median sits at 0.34–0.60 depending on profile, with
most profiles (hyphy, rap, chillstep, ambient, fire_dj, rock) spending 35–70% of signal-present
ticks in the 0.30–0.42 band — below the old gate for a majority of ticks in exactly the genres this
session's fingerprint work targeted. `0.42` was still too strict even with the blend bug fixed.

The first drop to `0.35` was reported as still producing zero fires across two more sessions. Log
inspection showed this was a false negative, not a real second failure: the first of those two
sessions started *before* the `0.35` edit landed on disk (still genuinely running `0.42`, peak
`downbeat_confidence` 0.37 — correctly below gate), and the second started after the edit but never
exceeded 0.39 (below `0.42`, but the config value is read once at `AutoVJController.__init__` and is
**not hot-reloaded** — a running process, or a subsystem-reload path that reuses an already-parsed
config object, keeps the old gate until the next full app restart). A separate, much longer
(~130 min) session that ran fully under the original `0.42` gate fired `is_downbeat` 54 times with a
healthy confidence distribution (median 0.43, max 0.76) — proof the gate mechanism itself works
given enough stable, confident playback; the two short test clips (19s, 42s) simply didn't run long
enough at the intended threshold to prove anything either way.

Moved to `0.30` regardless, both because it's a safe additional margin below the observed median
floor and because the operator explicitly requested it. **Any future test of this value must
confirm a full app restart happened after the config edit** — config.toml is not hot-reloaded for
this key, and matching an observed max-confidence value against the *previous* gate is easy to
mistake for a real gate failure.

This is a live-only regression: unit tests exercise `_compute_downbeat_confidence()` and the gate
comparison directly, so they couldn't have caught a threshold that's mathematically fine but
empirically miscalibrated against the real signal's distribution. The HUD pulse dot is the intended
detection mechanism going forward — watch it during any future threshold change instead of relying
solely on log percentiles.

---

## Per-Bar `downbeat_fire` Decision-Log Event (2026-07-08)

Decision: log every real `is_downbeat` firing as its own edge-triggered `downbeat_fire` event
(`_maybe_log_downbeat_event()` in `auto_vj.py`), in addition to the existing `detector_tick` field.

While investigating the gate-threshold changes above, a 130-minute session logged only 54
`detector_tick`-visible `is_downbeat=True` reads despite an estimated ~3,036 real bars over that
session (~93 BPM average) — a 1.78% apparent fire rate. The cause: `is_downbeat` is a true one-frame
flag (`grid.update()` resets it to `False` every frame, 60fps), but `detector_tick` is only written
once per second (`_detector_log_interval_s`). The odds of the one throttled log write per second
landing on the exact frame the flag was `True` are ~1/60 — almost exactly the 1.78% observed. Cross-
checking against `downbeat_confidence` (which *holds* its value between bar-checks rather than
blinking, so a 1-second sample is a much better proxy) showed ~53% of samples clearing the 0.42 gate
that session — meaning the real fire rate was likely ~30x higher than the log suggested.

**`detector_tick`'s `is_downbeat` field is not a usable instrument for measuring per-bar rate** and
should not be used for that going forward — use `downbeat_fire` events (one per real firing, with a
monotonic `bar_count`) instead. `detector_tick` remains fine for everything else it captures
(confidence, bpm, lock state) since those persist between samples rather than blinking.

---

## Vocal-Presence Heuristics — HNR + FMR (2026-07-08)

Decision: add `vocal_hnr` / `vocal_fmr` to `AudioData` (computed in `unicornviz/audio/analyzer.py`)
and `vocal_hnr_mu` / `vocal_fmr_mu` to `AudioProfile`, wired into the recommender's `_profile_score()`
at low weight (0.3 / 0.4, vs. 1.0+ for the established fit terms).

**Motivation:** a live Detroit techno track (120-135 BPM, no vocals) was observed locking the
recommender into `hyphy` — traced to two causes. First, `hyphy` (along with `rap`/`r&b`) had no
`bpm_hint_min/max`, so its ACF search ran the full unconstrained range (fixed separately, see the
Audio Profile System section above). Second, and more fundamentally: none of the recommender's
existing signals (spectral centroid, ZCR, onset density, or the 64-band cosine-similarity
fingerprint) measure vocal presence as a concept — they measure time-averaged energy *shape*, and a
bass-heavy instrumental track can match a "sustained vocal plateau" fingerprint just as well as an
actual voice, because nothing in that fingerprint encodes periodicity, harmonicity, or
syllable-rate modulation over time.

**What was added:**

- `vocal_hnr`: a harmonic-to-noise-ratio proxy in the vocal-formant band (300 Hz-3.4 kHz), computed
  per-frame by autocorrelating the log-compressed magnitude spectrum in that band (the standard
  cepstral-pitch trick — a harmonic comb produces a periodic ripple across frequency bins, which
  shows up as an autocorrelation peak at a nonzero lag). Cheap: reuses the FFT the analyzer already
  computes, no extra buffering.
- `vocal_fmr`: fraction of the vocal-band energy envelope's modulation concentrated in 3-8 Hz
  (syllabic/vibrato rate), tracked via a dedicated 40 Hz/2s rolling ring (mirroring the existing
  onset-envelope pattern) and recomputed every 8 frames via a small windowed FFT of that ring.

**Known limitations (validated via synthetic signal tests, not real session data):**

- Neither is a true vocal detector. `vocal_hnr` mainly separates "any pitched/harmonic content" from
  "noise-like content" in that band — it will read high for a synth lead or bassline just as readily
  as a voice. `vocal_fmr` is the stronger genre discriminator in principle (steady 4/4 kick-driven
  modulation sits at the beat rate, ~2 Hz at 120 BPM, well below the 3-8 Hz target band) but showed
  real leakage-driven noise in testing: a synthetic *unmodulated* stationary multi-harmonic tone
  scored ~0.5 (should ideally be near the ~0.25 chance baseline for this band's width), vs. ~0.68 for
  a genuinely 5 Hz-modulated tone and ~0.20-0.26 for noise/wrong-rate modulation — real separation,
  but noisier than hoped on a synthetic edge case unlikely to occur in real audio (which has much
  richer natural dynamics than a pure sum of stationary sinusoids).
- Profile `vocal_hnr_mu`/`vocal_fmr_mu` values (rap/hyphy 0.55/0.50, r&b 0.60/0.55, the 14
  instrumental-dominant profiles 0.35/0.25, `ambient`/`chillstep`/`generic` left uncalibrated) are
  first-pass estimates informed by the synthetic test results, **not validated against real session
  data** the way the spectral fingerprints were. Revisit once live sessions accumulate
  `mean_vocal_hnr`/`mean_vocal_fmr` in the `profile_recommendation` decision-log entries.
- A proper fix would use a pretrained vocal-activity-detection model — deferred as DW-005 in
  `docs/planning/deferred-work-2026-06-18.md` pending evidence this heuristic pair isn't sufficient.

---

## Profile Confusability Pass (2026-07-08)

Decision: `electronic.zcr_mu` lowered `0.065 → 0.052`; `fire_dj.bpm_prior_mu` shifted `148 → 152`.

**Methodology:** rather than eyeballing the full profile table (see
`docs/audio-profile-reference.md`) for similar-looking profiles, wrote a standalone script
(`/tmp/.../scratchpad/confusability.py`, not committed) reusing `_profile_score()`'s exact Gaussian
sigmas and composite weights (tempo/centroid/zcr/onset/spectral-shape/vocal-hnr/vocal-fmr fits;
`band_fit` and `kick_regularity_fit` omitted as they need live per-frame samples, not a static
profile spec). For each profile pair (A, B), built a "canonical track" for A from A's own mu values,
scored it against both A's and B's profile, and took the gap (`self_score_A − cross_score_B`,
averaged both directions) as a confusability metric — smaller gap means a track built exactly to A's
spec still scores nearly as well against B.

**Findings (top 3 closest pairs, before any tweak):**

1. `electronic`/`generic` (gap 0.058) — `spectral_centroid_mu` (1600), `zcr_mu` (0.065), and
   `onset_density_mu` (2.5) were all *identical* between the two, plus 98.1% `expected_bands` cosine
   similarity. `electronic` had accidentally inherited `generic`'s exact scalar targets.
2. `hard_techno`/`fire_dj` (gap 0.071) — identical `bpm_prior_mu` (148), 98.8% fingerprint
   similarity. `fire_dj` is an intentional wide multi-genre catch-all (132-170 BPM) but its center
   point exactly copied `hard_techno`'s instead of sitting at its own range's center (~151).
3. `tech_house`/`electronic` (gap 0.081) — same `zcr_mu` (0.065), close centroid/bpm, 98.5%
   similarity — a secondary symptom of the same `electronic` scalar-target issue as #1.

**Fix:** `zcr_mu` was the one dimension both of `electronic`'s neighbors (`generic` and
`tech_house`) shared at exactly 0.065 — lowering it to 0.052 separates from both simultaneously
without trading centroid/onset distance against either (tested numerically before applying).
`fire_dj.bpm_prior_mu` moved to 152, near the true center of its own declared 132-170 range.

**Result:** re-running the same gap calculation after the tweak: `electronic`/`generic` 0.058 →
0.185 (3.2x), `tech_house`/`electronic` 0.081 → 0.208 (2.6x), `hard_techno`/`fire_dj` 0.071 → 0.093
(fire_dj-mu-only fix; residual closeness here is expected — a broad catch-all profile spanning a
narrow genre's range will always sit somewhat close to it). Neither original top-2 pair got pushed
into a *new* top-3 collision after the fix — the post-tweak ranking's new #1 is still
`hard_techno`/`fire_dj`, followed by `hardgroove`/`breaks` and `hardgroove`/`uk_garage` (both
pre-existing, not introduced by this change).

This pass only touched two scalar values on two profiles; `hardgroove`/`breaks` and
`hardgroove`/`uk_garage` are the next-closest pairs and were not addressed here — flagged for a
future pass if it becomes an issue in practice.

---

## Profile Confusability Pass, Round 2 (2026-07-08)

Decision: `hardgroove.zcr_mu` raised `0.068 → 0.086`.

Follow-up to the round-1 pass above, addressing the next two closest pairs it flagged:
`hardgroove`/`breaks` (gap 0.136) and `hardgroove`/`uk_garage` (gap 0.157). Unlike round 1, there was
no single exact-duplicate value across *all* dimensions — `hardgroove` instead sits centrally
between `breaks` and `uk_garage` on bpm, centroid, and onset (each profile's value bracketing
`hardgroove`'s on both sides), meaning any move on those three dimensions trades separation from one
neighbor against the other. `zcr_mu` was the one dimension not in that three-way sandwich: it tied
`uk_garage`'s exactly (0.068) and sat close to `breaks`' (0.075).

Verified numerically (script from round 1) that lowering `zcr_mu` separates from both neighbors
faster than raising it — but raising was chosen instead: `hardgroove`'s own description ("rolling
tribal percussion... busy hats that want motion") implies *more* noise-like/percussive high-frequency
content than its neighbors, not less. `0.086` was chosen as the smallest value clearing both
neighbors on the same side (not landing symmetrically between them, which would cancel out the
separation gain against whichever neighbor it lands equidistant from).

**Result:** `hardgroove`/`breaks` 0.136 → 0.190, `hardgroove`/`uk_garage` 0.157 → 0.400. Confirmed
via a full re-ranking that neither became a new top-3 collision and no other pair regressed;
`hard_techno`/`fire_dj` (0.093, the accepted residual catch-all overlap from round 1) remains the
closest pair in the roster.

---

## First Direct beat_grid.py Test Coverage — Two Findings (2026-07-08)

Status: documented, not fixed. See `tests/test_beat_tracker_v2.py` / `tests/test_beat_grid_tracker_v1.py`.

Writing the first direct unit tests for `beat_grid.py` (previously zero coverage of either
`BeatTracker` or `BeatGridTracker` themselves — only a path-existence check in
`test_corpus_writers.py`) surfaced two real behaviors worth recording, discovered via synthetic
click-track simulation rather than live-session log analysis:

**1. Silence reset does not clear the onset envelope.** `_reset_tempo_lock()` (fired after
`silence_reset_s` of no onsets) clears `bpm`/`confidence`/`phase`/`candidate_history`/
`beat_position_map`/`tempo_hold_until_t`, but never clears `_env_buf`/`_env_write_idx`/
`_env_filled`. Since the onset envelope is an 8-second ring (`_V2_ENV_WINDOW_S`), a periodic ACF
re-estimation running shortly after the reset can still find the pre-silence onset pattern still
resident in the ring and re-lock onto it — confirmed via simulation to happen within under a
second of the reset firing, well before any new real onset has arrived. This likely undermines the
intended purpose of the silence reset (clean state for the next song) for up to ~8s after a gap
begins. Not fixed here — flagging for a decision on whether `_reset_tempo_lock()` should also clear
the envelope ring, at the cost of losing a few seconds of legitimate cross-fade audio history for a
song that resumes quickly.

**2. Phase confidence has no explicit initial sync.** On first BPM lock, the phase oscillator
(`self._phase`) starts wherever it was left (0.0 from `_reset_tempo_lock`/`__init__`), not
synchronized to the actual onset that triggered the lock. `_absorb_onset`'s phase-coherence nudge
only activates once an onset already lands within ±18% (`_V2_PHASE_TOL`) of the current phase, so
if the initial offset is larger than that, the phase can only drift into tolerance opportunistically
via the small BPM-estimate error against true tempo, not through any deliberate re-sync step.
Simulated on a perfectly steady, unambiguous 120 BPM click track: `acf_confidence` reached ~1.0
within ~4s of the first lock, but `phase_confidence` (and therefore the blended `confidence`, and
`downbeat_confidence`'s 30%-weighted `coh` term) took **30-50s** to converge to a comparable level.
This is a plausible structural contributor to the "downbeat gate sits below threshold for extended
stretches even on confidently-locked material" pattern observed in the 2026-07-08 downbeat-gate
investigation above — not the whole explanation (that investigation also found genuine per-genre
struggle concentrated in chillstep/hyphy), but a mechanism that would affect every genre equally
for the first 30-50s after any fresh lock (track start, tempo change, or post-silence re-lock).

Re-entry trigger: revisit if live sessions show downbeat scheduling feels sluggish specifically in
the first ~30-50s after a track starts or after silence, which would corroborate finding #2 as a
practical (not just theoretical) problem.

---

## Recommender Confirm/Decider Margin — softmax-normalized (2026-07-06)

Decision: `profile_auto_reco_score_margin` and `profile_auto_reco_decider_min_margin`
default `0.25 → 0.09`; margin is now a softmax probability margin, not an additive score gap

**Problem:** the confirm gate (`margin >= profile_auto_reco_score_margin`) and decider gate
compared the raw additive composite score gap between the best and current profile.  This
composite has no fixed scale — it's a weighted sum of Gaussian log-likelihood terms, cosine
similarities, and rate fractions (see the weight list in the LLM tuning prompt) whose total spread
depends entirely on how distinguishable the candidate profiles are on the current material.  Real
logged `top_candidates` scores across two sessions (5,734 samples) show best-vs-second-best
margins ranging from 0.06 (p10) to 2.17 (p90) — a single fixed `0.25` threshold means very
different things depending on how spread-out the scores happen to be on a given genre.

**Fix:** the margin used for confirm/decider gating is now `best_prob - current_prob` from a
numerically-stable softmax over the raw composite scores (`exp(s - max_s)`, normalized).  This
bounds the margin to `[0, 1]` and makes it a genuine "how much more likely is the best candidate"
quantity, comparable across sessions regardless of the raw score spread.  `score_current` /
`score_recommended` in HUD display, logging, and the LLM tuning prompt remain the raw additive
values unchanged — the LLM prompt's weight-recommendation reasoning (`tempo_fit × 2.0`, etc.)
operates on that additive scale and would break if it were softmax-transformed too.  Only the
gating margin changes representation.

**New default derivation:** rather than guess a new threshold, the old `0.25` additive default was
located at the 31.3rd percentile of the 5,734 real logged margins; the softmax-margin value at that
same percentile (computed on the same real score arrays) is `0.0915`, rounded to `0.09`.  This
preserves the system's actual historical permissiveness — operators who were happy with how often
the decider fired under `0.25` should see materially the same firing frequency under `0.09`, just
expressed in a scale-stable unit going forward.

Also fixes a related bug: `current_score = dict(candidates).get(current_key, best_score)` fell back
to `best_score` when the active profile key wasn't among the scored candidates, silently collapsing
margin to 0 and permanently blocking the decider.  Both the raw-score fallback (for display) and the
new probability fallback (for gating) now use the second-best candidate instead.

Full analysis: `docs/audits/2026-07-06-vj-training-systems-audit.md` P2-6 / P2-7.

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
| 2026-05-22–2026-07-06 | `_compute_downbeat_confidence()` reading `base = self._confidence` | Identical to `coh` in practice — never an independent third signal; replaced with genuinely independent `_acf_confidence` (see Confidence Blend Bug section) |
| — | `_V2_ANALYSIS_DOWNBEAT_CONFIDENCE_MIN = 0.55` | Never validated against real data; real coherence medians run 0.41-0.47, so 0.55 would have gated `is_downbeat` closed on roughly half of all beats. Lowered to 0.42 as a training-start value (see Analysis Mode section) |
| — | `profile_auto_reco_score_margin` / `_decider_min_margin = 0.25` (additive score gap) | Unbounded scale meant different things across genres (real margins observed 0.06-2.17); replaced with a softmax probability margin, rescaled to 0.09 at the equivalent historical percentile (see Recommender Confirm/Decider Margin section) |

---

## Defaults Baked into Code from config.toml (2026-07-13)

As part of the config.toml consolidation (promote operator-tuned values to code
defaults, then strip the file to non-defaults), these `[auto_vj]` values — long
carried as config overrides — were promoted to their **code defaults** in the
`auto-vj-01` drop-in and removed from `config.toml`.  Values unchanged; only the
*source of truth* moved from config to code.

| Key | Old code default | New code default | File |
| --- | --- | --- | --- |
| `tempo_hold_s` | 6.0 | **10.0** | `beat_grid.py` |
| `silence_reset_s` | 2.0 | **15.0** | `beat_grid.py` |
| `auto_profile_enabled` | False | **True** | `auto_vj.py` |
| `auto_profile_chill_max_bpm` | 110.0 | **105.0** | `auto_vj.py` |
| `auto_profile_raver_min_bpm` | 136.0 | **126.0** | `auto_vj.py` |
| `auto_profile_switch_cooldown_s` | 20.0 | **120.0** | `auto_vj.py` |
| `auto_profile_hold_s` | 0.0 | **8.0** | `auto_vj.py` |

Rationale for the values is documented in the Tempo Hold and Auto-Profile Raver
Threshold sections above; this entry records that they are now defaults, not
overrides. `auto_vj.log_decisions` was intentionally *not* baked (kept in
config.toml).

---

## VJ Mood Profile Effect-Tag Vocabulary Fix (2026-07-13)

**Bug:** the director was reported as spending a disproportionate amount of time
on psychedelic-style effects ("stuck in the psychedelics").

**Root cause:** each mood profile's per-scene `*_effect_tags`
(`cruise`/`breakdown`/`drop`/`impact`/`climax`, resolved via `_profile_value()`
from `_PROFILE_PRESETS`) requested a tag vocabulary — `ambient`, `audio`,
`futuristic`, plus `psychedelic`/`classic`/`art`/`particles`/`neon` — that
barely overlapped with real effect `TAGS` (category/style words like `tech`,
`cosmic`, `retro`). `ambient`, `audio`, and `futuristic` matched **zero**
effects. `psychedelic` was the one tag common to nearly every drop/impact/
climax list, so `goto_random_effect`'s tag filter collapsed to the same ~5
psychedelic-tagged effects whenever a drop, impact, or climax fired.

**Fix (two parts, both landed):**
1. All 44 rotation effects were given one-or-more **mood tags** — `chill`,
   `groovy`, `energetic`, `intense`, `hard` — layered on top of their existing
   category tags. See `docs/planning/vj-mood-tag-rollout.md` for the full
   per-effect assignment (owner Q&A-confirmed, scripted apply, cross-checked
   with zero drift).
2. Each mood profile's per-scene `*_effect_tags` in `_PROFILE_PRESETS` were
   replaced with mood-vocabulary requests (owner-specified per profile):

   | Scene | chill | normie | raver |
   | --- | --- | --- | --- |
   | cruise | chill, groovy | chill, groovy, energetic | groovy, energetic |
   | breakdown | chill | chill, groovy | chill, groovy |
   | drop | groovy, energetic | energetic, intense | energetic, intense |
   | impact | intense, energetic | intense, hard | intense, hard |
   | climax | energetic, hard, intense | energetic, hard, intense | energetic, hard, intense |

3. A safety-net fallback was also added in core (`vj_api.goto_random_effect`):
   when no *enabled* effect matches the requested tags, fall back to any
   enabled effect instead of returning `None`, so a future tag gap can never
   strand the director again.

**Verified:** every scene across all three profiles now matches 16–40 of the 44
rotation effects (was ~5 for every drop/impact/climax before). Regression test:
`tests/test_effect_mood_coverage.py` (main repo) asserts full mood-tag coverage.

---

## Open Questions

- Should `tactus_preference_ratio` be per-AudioProfile rather than a global config key?
- Consider widening `phase_tol` to 0.22 to nudge the natural equilibrium above 0.40 (now closer to the 0.55 gain threshold).
