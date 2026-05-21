# Auto VJ Beat Detection — Deep Analysis & Handoff (2026-05-21)

## Purpose

Deep technical analysis of the Auto VJ beat / BPM detection subsystem, grounded
in multi-session live telemetry from 2026-05-21. Intended both as a working
debug record and as a hand-off package for a fresh team to take a crack at it.

Primary unresolved issue: **BPM is systematically biased into a fast harmonic
lane (~140–160 BPM)** regardless of the underlying musical tempo. A track of
~96 BPM was reported as ~155 BPM during live observation.

Secondary status: transition pacing/churn is substantially improved vs earlier
baseline; chains (BUILD → DROP → IMPACT → CLIMAX) are coherent. The remaining
failure is concentrated specifically in the **tempo estimator**, not in the
state machine.

## TL;DR — What is actually broken

1. The "beat detector" is two stacked, weakly-coupled detectors:
   - **Analyzer** (`unicornviz/audio/analyzer.py`): spectral-flux onset
     detector with adaptive threshold and a short cooldown, producing a
     binary `audio.beat` event.
   - **BeatGrid** (`drop-ins/auto-vj-01/beat_grid.py`): IOI-based tempo
     estimator that consumes `audio.beat`, accumulates inter-onset intervals,
     and uses median IOI + harmonic candidate scoring to pick a BPM.
2. Neither stage uses a true tempo tracker (no autocorrelation, no
   comb-filter tempogram, no phase-locked oscillator). The whole system is
   "find onsets, divide 60 by median IOI, then shop for a harmonic" — which
   is structurally fragile on dense electronic material.
3. The IOI stream the BeatGrid sees is contaminated by sub-beat onsets
   (8th-note hats, percussion). With the current refractory windows, the
   stream tends to cluster around ~0.36–0.40 s IOI → ~150–165 BPM. That is
   exactly the lane we keep getting stuck in.
4. The harmonic candidate scoring and de-alias heuristics are local repairs
   on a fundamentally weak signal — they cannot recover a stable tempo if
   the IOI stream itself is dominated by sub-beat onsets.
5. There is no ground-truth harness, so iteration is purely empirical against
   live audio.

## Evidence — Multi-Session Telemetry (16 logs, 2026-05-21)

Aggregated across all `logs/autovj-20260521T*.jsonl` files:

- total detector ticks (logged at ~1 Hz): 17,669
- locked-BPM ticks (bpm > 0): 17,612
- BPM distribution:
  - p10 = 124.2
  - p25 = 128.6
  - p50 = 138.5
  - p75 = 154.9
  - p90 = 156.8
  - max = 177.1
- BPM lane occupancy:
  - fast (≥140 BPM): **47.4 %**
  - mid (120–140): 48.7 %
  - slow (<120): **3.9 %**
- BPM frame-to-frame jump within a session:
  - p50 = 0.15
  - p90 = 3.01
  - p99 = 14.2
  - max = 51.3
- Confidence distribution:
  - p10 = 0.42
  - p50 = 0.63
  - p90 = 0.85

Per-session BPM mode buckets (5-BPM bins, top-3):

- `120410`: (120, 125, 155) — 155 already a prominent bucket
- `130145`: (155, 125, 135) — 155 dominant
- `133326`: (125, 140, 155)
- `143809`: (155, 125, 140) — 155 dominant
- `153837`: (155, 140, 150) — 155 dominant

The `~155 BPM` bucket recurs across every session today, even when the music
library spans a wide tempo range. The slow-tempo lane is structurally
under-represented (only 3.9 % of all locked ticks).

## Structural Root-Cause Hypotheses

### H1. Sub-beat onsets dominate the IOI stream

- `unicornviz/audio/analyzer.py` enforces a beat cooldown of `cooldown_frames / 60.0`
  seconds where `cooldown_frames ∈ [6, 12]`. That is **0.10–0.20 s** raw
  rate, i.e. up to ~600 BPM admissible onset rate.
- `drop-ins/auto-vj-01/beat_grid.py` has its own refractory at `0.16 s` and
  filters IOIs to `[bpm_min=70, bpm_max=180]`, i.e. IOI in `[0.333, 0.857] s`.
- On dense electronic music with 8th-note hats and percussion, onsets fire
  well inside one beat. Cooldown bouncing tends to admit one extra onset
  between beats. That produces IOIs around **0.38–0.40 s ≈ 150–158 BPM** —
  exactly the lane we keep locking to.
- The IOI median is then "honest" — it really is the median of the observed
  IOI stream — but the stream is reporting sub-beat structure, not the
  musical pulse.

### H2. The tempo estimator has no phase model

- `_estimate_bpm()` only looks at intervals between successive onsets.
- It has no notion of "I expected a beat near time T; this onset is 30 ms
  early/late". A phase-locked tempo tracker would heavily down-weight onsets
  that don't land on the expected grid.
- Without that, every onset has equal voting weight, and the densest mode in
  the IOI distribution wins — which is the half-beat mode on busy material.

### H3. Harmonic candidate scoring rewards what is already wrong

- The candidate families `(0.5, 2/3, 0.75, 1.0, 4/3, 1.5, 2.0)` rescore the
  same IOI population that is biased toward sub-beat IOIs.
- A candidate at ~155 BPM trivially fits IOIs near 0.39 s (its base period)
  and IOIs near 0.77 s (2× the base period).
- A candidate at ~96 BPM only fits IOIs near 0.625 s plus harmonic neighbors.
  If the IOI stream has very few entries near 0.625 s (because the analyzer
  fired sub-beat), 96 BPM scores poorly.
- The estimator cannot reach ground truth from a sub-beat-dominated IOI
  population, no matter how clever the candidate set.

### H4. Adaptive flux threshold becomes too easy as music steadies

- The flux beat threshold is `mean + 1.25 * std` over a fixed-length ring of
  43 flux samples (`_ONSET_WINDOW`).
- On steady electronic material the flux std becomes small, so the threshold
  drops, and small sub-beat fluctuations clear it. Consistent with the high
  fast-lane occupancy and the persistent ~155 lock.

### H5. `_ONSET_WINDOW` is a fixed sample count, not a fixed time

- 43 samples ≈ 1 s only if the analyzer is called at exactly 60 Hz.
- The analyzer is called once per `AudioManager.get_audio_data()`, which runs
  on the render loop. Frame rate variations change the actual observation
  window in seconds, which slowly biases threshold and onset density.

### H6. `audio.beat` is a level, not an event

- The Analyzer sets `data.beat = 1.0` for the one call where the threshold is
  crossed, otherwise `0.0`. `AudioManager.get_audio_data()` produces a fresh
  snapshot on every render frame by calling `analyzer.process(block)`.
- If `block` is `None` (no new audio available since last poll), `process()`
  short-circuits and returns a blank `AudioData()` — i.e. `beat = 0.0`.
- This means: on fast render frames where audio has not produced a new block,
  the beat signal silently flat-lines and BeatGrid never sees the event.
  Conversely, on slow render frames more than one audio block can be consumed
  but only the last one is reflected in `data.beat`.
- Both are silent failure modes that distort the observed IOI stream.

### H7. Bar tracking is naive mod-4 counting

- `_bar_beat_count >= 4` triggers a "downbeat" regardless of musical phrase.
- Outlier handling tries to skip off-grid onsets but `dev > 0.35` is
  permissive. A single phantom sub-beat onset can advance the counter and
  desync downbeats from the music.

### H8. No ground-truth feedback loop

- Iteration today is "play, watch HUD, tune thresholds" — open-loop. There
  is no offline test corpus of known-BPM material with measurable absolute
  / octave error rates, so even good fixes can look like regressions on the
  next track.

## What Has Already Been Tried (and why it is not enough)

- Decoupling detector input from reactivity-scaled audio. ✅ Real fix, kept.
- Drop-score normalization. ✅ Helped pacing, unrelated to BPM accuracy.
- BPM continuity guard + EMA smoothing in BeatGrid. ✅ Reduces jitter but
  does not change which mode the estimator locks to.
- Harmonic candidate-family scoring. ✅ Catches some octave errors, but the
  scoring substrate (IOI population) is itself biased.
- High-BPM low-confidence de-alias (prefer 0.5 / 0.66 / 0.75 folds when
  confidence < 0.78 and BPM > 145). ⚠ Helps in some cases, but telemetry
  shows confidence frequently climbs above the gate while the lock is still
  wrong, because the wrong lane really does fit the polluted IOI stream well.
- Time-based analyzer cooldown. ✅ Removes FPS coupling on cooldown only.
- Detector-side per-band normalization. ✅ Reduces bass bias in *director*
  scoring; orthogonal to tempo accuracy.

## Recommended Path Forward (in expected-impact order)

Treat this as a *tempo tracker rewrite*, not another threshold pass. Local
heuristic tuning will continue to chase its tail.

### R1. Onset envelope autocorrelation tempo estimator

- In `Analyzer`, maintain the spectral-flux time-series as a real onset
  envelope sampled on a fixed time grid (e.g. resample to ~100 Hz internal
  rate using elapsed `dt` between calls).
- Keep a rolling window of 6–8 s.
- Compute autocorrelation across lags corresponding to 60–180 BPM
  (~0.33–1.0 s).
- Peak-pick the autocorrelation, score each peak with a perceptual tempo
  prior (e.g. Gaussian centered at ~120 BPM, σ ≈ 30 BPM, weighted by peak
  height).
- Replaces "median IOI + harmonic shopping" with a real tempo estimator
  that is far more robust on dense material.

### R2. Phase-locked oscillator for beat alignment

- Maintain a phase oscillator at the chosen BPM.
- Each onset updates phase only if it lands within tolerance of the predicted
  beat (e.g. ±15 % of beat period).
- Use phase coherence as the new confidence metric, not "fraction of IOIs
  near median".
- Removes sub-beat onsets from beat counting almost entirely.

### R3. Tempo-aware adaptive refractory in the analyzer

- Once BPM is locked with reasonable confidence, the analyzer's beat cooldown
  should be set to roughly `0.7 × beat period`. Today it is fixed at
  0.10–0.20 s, which admits 300–600 BPM raw rate.
- Even without R1/R2, this alone should sharply reduce sub-beat contamination
  on tracks where any tempo is established.

### R4. Replace `_ONSET_WINDOW` with a time-based ring

- Store `(t, flux)` pairs and compute mean/std over a window of fixed
  duration (e.g. 1.5 s).
- Eliminates FPS-induced bias in threshold behavior.

### R5. Promote `audio.beat` to a queued event, not a level

- Producer: analyzer pushes onsets with timestamps into a small queue when
  detected.
- Consumer: BeatGrid drains the queue at update time, so no onset is missed
  on fast frames and no level is double-counted.
- Eliminates H6.

### R6. Spectral-based downbeat detection

- Replace `bar_beat_count >= 4` with a kick/snare-pattern model: bass-band
  flux on downbeats, mid-band flux on upbeats. Cross-correlate with beat
  grid to identify bar phase.
- Follow-up after R1/R2 land.

### R7. Ground-truth harness

- Add `tools/bpm_eval.py` that:
  - takes a directory of audio files with known BPM (from filename or
    sidecar JSON),
  - replays through the offline analyzer + BeatGrid in a deterministic way,
  - reports absolute BPM error, octave/harmonic error rate, and time-to-lock.
- Required to evaluate any change without burning live-listening time.

## Lower-Risk Interim Mitigations

If a full rewrite is not yet possible, these are the smallest changes most
likely to reduce wrong-lane bias today:

- Set BeatGrid `_beat_refractory_s` dynamically from BPM once locked
  (e.g. `0.55 * 60 / bpm`), instead of fixed `0.16 s`.
- Strengthen the high-lane prior: require confidence ≥ 0.85 (instead of
  current 0.78) to remain in any lane above ~145 BPM; otherwise prefer the
  best fold candidate in the 90–135 BPM band.
- Bias BPM continuity smoothing toward the *modal* lane over a longer window
  (e.g. 8–16 s), not the current EMA which can drift through the 155-lane.
- Add a profile-aware tempo prior (e.g. chill ~100, normie ~125, raver ~140)
  when confidence is moderate.

These are local repairs and will not solve the structural problem, but they
should noticeably reduce mis-lock rate while R1/R2 are in flight.

## Code Areas In Scope

- `drop-ins/auto-vj-01/beat_grid.py` — tempo estimator, IOI scoring, BPM smoothing
- `unicornviz/audio/analyzer.py` — spectral-flux onset detector, beat threshold
- `unicornviz/audio/manager.py` — audio block delivery, `data.beat` semantics
- `drop-ins/auto-vj-01/auto_vj.py` — director consuming BPM/confidence
- `tools/analyze_autovj_log.py` — postmortem analyzer (current)
- `docs/debug/auto-vj-drop-detection-debug-2026-05-21.md` — running debug log

## Timeline of Relevant Changes (already shipped)

Recent main-repo commits:

- `3cd3ad7` — submodule bump: BPM de-alias heuristic
- `4938320` — submodule bump: BPM harmonic candidate fix
- `3becacd` — submodule bump: final profile suite retune
- `39e2aeb` — submodule bump: BPM-timed pacing + band normalization
- `65847ae` — BPM detector stability + pacing retune (time-based cooldown)
- `594efba` — debug report + analyzer hardening
- `f4faf69` — analyzer: transition-burst and band diagnostics
- `13c32e2` — decouple detector from reactivity-scaled audio

Recent auto-vj submodule commits (chronological):

- `1d8e56a` — final profile pacing retune
- `2681e2b` — harmonic candidate-family BPM scoring
- `7af1f1d` — de-alias high-BPM lock at moderate confidence

## Reproduction Procedure

1. Start app:

```bash
cd /home/j/Repos/unicorn-viz
source .venv/bin/activate
./run.sh
```

2. Ensure Auto VJ and telemetry are enabled in `config.toml`:

- `[auto_vj] enabled = true`
- `log_decisions = true`
- `detector_log_interval_s = 1.0`

3. Play known slower material (~90–110 BPM) and observe HUD BPM.

4. After 5–15 minutes, analyze latest JSONL:

```bash
cd /home/j/Repos/unicorn-viz
python3 tools/analyze_autovj_log.py
```

5. For raw tick inspection:

```bash
python3 - << 'EOF'
import json
from pathlib import Path
p=sorted(Path('logs').glob('autovj-*.jsonl'), key=lambda x:x.stat().st_mtime, reverse=True)[0]
rows=[json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]
for r in [x for x in rows if x.get('action')=='detector_tick'][-40:]:
    print(r.get('t'), r.get('bpm'), r.get('confidence'), r.get('beat_phase'))
EOF
```

## Deliverables Requested From Receiving Team

- Patch proposal for BPM lane accuracy on slower tracks (preferably along R1
  and/or R2).
- Before/after metrics on:
  - median BPM error vs ground truth
  - harmonic/octave mis-lock rate
  - confidence calibration quality (does high confidence correlate with low
    error?)
- A profile-agnostic tempo-prior strategy that avoids false fast locks
  without harming genuinely fast material.
- A small offline evaluation harness (R7) so changes can be measured.

## Contact Context

This handoff follows iterative live tuning with telemetry-heavy runs on
Fedora / Linux. Auto VJ is currently stable in transition pacing but
inaccurate on tempo estimation, with measurable bias toward the ~150–160 BPM
lane across varied musical material.

## Post-handoff v2 regression note

While validating the rebuild plan, the new v2 engine solved the old 155-lane
problem on the synthetic seed corpus, but a steadier 124 BPM live track later
exposed two transient regressions:

- phantom 200 BPM spikes when the ACF score is effectively zero across all
  lags
- 96 BPM dips when a single bad frame pulls the EMA away from the correct
  tempo

The next guardrails to land are:

1. a higher ACF score floor
2. a per-update BPM step cap
3. a confidence floor before applying updates

Keep this note attached to the v2 workstream; it is the current highest-value
debug target.

Implementation status: these guardrails are now being added to the v2 engine.
The next validation step is a fresh run of `tools/bpm_eval.py --engine v2`
against the same seed corpus, then a live 124 BPM check to ensure the 96 BPM
dips and 200 BPM spikes are gone without reintroducing the old 155-lane bias.

Verification note: a 124 BPM synthetic sanity check now shows neither the
phantom 200 BPM spike nor the 96 BPM dip. The estimator is conservative on
that test (steady at ~120 BPM), but it is now stable and no longer thrashes.

Live note after that hardening: a real steady 124 BPM song and a steady 96 BPM
song still oscillate in the live meter between roughly 111 and 158 BPM within
seconds. The remaining problem is not zero-score spikes anymore; it is too-
eager candidate replacement. Add hysteresis / candidate persistence before
changing the BPM lock.

Checkpoint update after the startup-confidence gate: the seed corpus remains
strong on v2 (median absolute BPM error 1.15 BPM; 96 BPM seed locks at 96.0
BPM; 155 BPM seed at 153.8 BPM). The live oscillation still needs a fresh log
after restart, but the offline regression surface is currently under control.

Checkpoint update after re-lock/pause controls:

- v2 now includes a tempo-hold window and silence-reset lock clearing so BPM
  does not churn multiple times per second and does not carry stale state
  across pause/song switches.
- Seed corpus quality remains high (90=89.5, 96=95.9, 120=120.0, 140=139.5,
  155=153.8).
- Remaining open item: one synthetic 96 variant settles low, so low-tempo
  calibration still needs additional tuning against fresh live logs.

Latest follow-up:

- Live log `autovj-20260521T182407.jsonl` confirms over-relocking (not
  oversampling): repeated lane cycling with low-to-mid confidence produced the
  observed meter creep/reset behavior and raver-mode drift on slow songs.
- Added a stronger large-jump ACF confidence gate plus auto-profile switch
  hysteresis (`auto_profile_hold_s`) so transient BPM spikes cannot immediately
  force profile changes.
- Seed corpus remains acceptable after these changes, but low-tempo edge
  calibration (96-class underlock variants) is still open work.

Newest field report after additional user test pass:

- First two steady songs improved noticeably versus earlier runs.
- Third steady fast song (164 BPM) mis-locked around ~111 BPM.
- Auto-profile remained in non-raver because detector never produced stable
  high-BPM evidence with sufficient confidence.

Conclusion for handoff:

- The unresolved blocker is fast-tempo under-lock with incorrect stable lane
  selection, not timing jitter from the source tracks.
- Next team should evaluate replacing or augmenting v2 with a sequence model
  approach (RNN activations + DBN decoding) as implemented in open references
  such as `CPJKU/madmom`, or multi-candidate histogram confidence approaches
  like `MTG/essentia`.

## RESOLUTION (2026-05-21, final session)

**Root cause identified and fixed.** The 164 BPM under-lock to 111 BPM was a
classic metric-ambiguity failure mode: 164 BPM has a dotted-half period at
109 BPM (164 * 2/3). With the previous Gaussian-in-linear-BPM prior (mu=120,
sigma=28), 109 BPM scored exp(-0.077) = 0.93 in the prior, while 164 BPM
scored exp(-1.23) = 0.29. The 3.2x prior bias meant a metric-ambiguous lower
lane peak would always beat the true fundamental peak.

Fix (aubio-style harmonic comb filter, see `src/tempo/beattracking.c`):

1. Replaced single-peak argmax with comb-filter scoring that sums ACF
   strength at the fundamental lag plus 2x, 3x, 4x harmonic lags. A true
   tempo has consistently strong correlation across its harmonic stack;
   a metric-ambiguous lane has only the single ambiguous peak.
2. Switched the perceptual prior from linear-BPM Gaussian to log2-BPM
   Gaussian (sigma=0.55 in log2 units). This is octave-symmetric and gives
   comparable weight to 75 BPM and 185 BPM, removing the structural bias
   against fast tempos.

Benchmark results (12-tempo synthetic sweep 75-185 BPM):

- All tempos lock within 3 BPM of truth
- Mean absolute error: 1.28 BPM
- 164 BPM specifically: 162.2 BPM (was 111 BPM in live)

Seed corpus (`tools/bpm_eval.py --engine v2`):

- 90 = 90.5, 96 = 96.5, 120 = 117.7, 140 = 137.1, 155 = 153.8
- Mean abs error: 1.48 BPM

This is production-quality for a dependency-light real-time tracker and
resolves the open blocker. The handoff to a sequence-model implementation
(madmom/essentia) is no longer required for current music material; v2
with comb-filter scoring is sufficient.

### Follow-up: live 96 BPM → 150 lock and tactus preference

First live test of the comb-filter v2 showed a 96 BPM track locking at
150.00 BPM immediately and staying pinned by tempo-hold. Synthetic click
tracks (clean impulses at the beat) and real dense electronic music (with
hi-hat / percussion sub-beat onsets) produce very different onset envelopes.
The comb filter correctly found the strongest periodicity in the live onset
stream — but in dense music that strongest period is often the sub-beat
rate (8th/16th note hats), not the musical pulse.

Fix: tactus (octave-down) preference, matching aubio/madmom. After the
comb filter picks a peak, if the peak is above `tactus_check_bpm` (default
130), also evaluate 0.5x, 2/3, and 3/4 candidates. If any has comb-filter
score ≥ `tactus_preference_ratio` (default 0.70) of the picked score, the
slower candidate is preferred as the musical tactus.

Validated on 15-tempo synthetic sweep 75-185 BPM (all within 5 BPM, max
error 4.0). True fast tempos with strong fundamental ACF are not pulled
down; only metric-ambiguous lanes are corrected.

### Director threshold rescale (one-shot, no re-tuning required)

After v2 detector accuracy fix, BPM-coupled director thresholds were
rescaled in one pass to canonical musical values. Important finding:
**CRUISE/DROP/IMPACT/CLIMAX state-machine thresholds are NOT BPM-coupled**
— they are driven by `drop_score`, `energy`, and `energy_slope`, which are
audio features independent of tempo. That tuning work is preserved.

Only four defaults needed rescaling (typed values shown are new defaults):

| Setting | Old | New | Rationale |
|---|---|---|---|
| `auto_profile_chill_max_bpm` | 110 | 100 | canonical chill upper |
| `auto_profile_raver_min_bpm` | 136 | 128 | canonical raver lower |
| `pingpong_auto_bpm_min` (×3 profiles) | 138 | 128 | canonical raver threshold |
| `_timing_scale_from_bpm` centre | 128 | 115 | matches new typical median |

Tactus preference was also tightened from the initial conservative defaults:

| Setting | Old | New |
|---|---|---|
| `tactus_check_bpm` | 130 | 115 |
| `tactus_preference_ratio` | 0.70 | 0.55 |

All values remain overridable via `config.toml`.

## Final status (session close)

Live testing showed v2 still locked at 150 BPM on at least one dense
electronic track even with iterative tactus descent. Synthetic clean-click
benchmarks pass cleanly across 75-185 BPM (max err 4.0). The gap between
synthetic and live is the analyzer onset detector: on dense material the
spectral-flux + MAD-threshold pipeline admits enough sub-beat onsets
(hi-hats, percussion) that the comb-filter ACF finds a genuine, strong
periodicity at the sub-beat rate — not the musical pulse.

What v2 currently provides:

- Correct lock on clean / kick-driven material across the full 75-185 BPM
  range (validated by synthetic harness).
- Resolves the original 164 BPM under-lock blocker for material with a
  clear fundamental.
- Tactus preference (iterative descent) catches multi-step metric traps in
  synthetic data and on live tracks with clearly separated bass content.

What v2 does NOT yet solve:

- Dense electronic material with strong hi-hat / 16th-note percussion can
  still lock at the sub-beat rate (~150 BPM) when that periodicity in the
  onset envelope is stronger than the kick rate. The root cause is upstream
  in `unicornviz/audio/analyzer.py`: spectral-flux onset detection is not
  kick-biased enough on this material.

### V1 fallback (recommended for production for now)

Set in `config.toml`:

```toml
beat_tracker_engine = "v1"
```

(`"v1"` and `"legacy"` are both accepted and map to the original
`BeatGridTracker` IOI-median estimator.)

### Director defaults reverted to pre-v2 v1 calibration

During v2 work the BPM-coupled director thresholds were rescaled to v2's
accurate-BPM space, which broke profile/mode behavior on v1 (v1 reads
systematically high, so the lowered thresholds kept profile pinned). All
four have been reverted to their pre-v2 v1-calibrated defaults:

| Setting | v1 default (restored) |
|---|---|
| `auto_profile_chill_max_bpm` | 110 |
| `auto_profile_raver_min_bpm` | 136 |
| `pingpong_auto_bpm_min` (×3 profiles) | 138 |
| `_timing_scale_from_bpm` centre | 128 |
| `auto_profile_hold_s` | 0 (immediate switching) |

If you later run v2 in a long session and want to recalibrate the BPM-
coupled thresholds for v2's accurate-BPM space, override the four values
in `config.toml` to roughly: `chill_max=100`, `raver_min=128`,
`pingpong_auto_bpm_min=128`, and optionally set `auto_profile_hold_s=8.0`
for hysteresis. The hysteresis code is retained but only active when
`hold_s > 0`.

### Next steps for whoever picks this up

The v2 design itself is sound (comb-filter ACF + log2 prior + tactus
preference matches aubio/madmom). The remaining work is in the upstream
onset detector — the BeatTracker can only be as good as its onset stream.
Options in priority order:

1. **Kick-biased onset detector** in `unicornviz/audio/analyzer.py`.
   Compute a separate bass-band spectral flux (e.g. low quarter of
   `_bass_slice`) and emit onset events only when bass-band flux passes
   threshold. This is the single most impactful change and is well-scoped.
2. **Multi-band onset detection** (madmom-style): separate detectors for
   bass / mid / treble that vote, with bass weighted heavily for beat
   tracking and treble used only for downbeat features.
3. **Increase MAD threshold k** from 1.80 toward 2.4-2.8 for v2 only.
   Would require splitting the analyzer threshold so v1 stays calibrated.
4. **Sequence-model branch** (madmom RNN + DBN). Heaviest lift; only
   justified if (1)-(3) prove insufficient.
