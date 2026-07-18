# ADR: Auto VJ Training & Model Tuning

Owner: unicorn-viz maintainers
Status: Active
Last updated: 2026-07-18

This document records architectural decisions for the Auto VJ training pipeline:
corpus design, scoring, packager logic, headless session infrastructure, and
tuning protocol.  Update it whenever touching
`drop-ins/training-kit-01/tools/package_training_set.py`,
`drop-ins/training-kit-01/tools/training_daemon.py`,
`drop-ins/training-kit-01/tools/training/training_lib.py`,
`drop-ins/training-kit-01/tools/training/sync_corpus_from_logs.py`,
`drop-ins/training-kit-01/tools/promote_weights.py`, scorecard thresholds,
LLM scoring, Schmidt trigger constants, or adding / changing a training
workflow step.

---

## Corpus Architecture

**Decision: two-corpus design (live + sequence)**

| Corpus | File pattern | Shape | Purpose |
| ------ | ------------ | ----- | ------- |
| Live | `live-corpus-<ts>.jsonl` | One row per track (upserted) | Per-track feature aggregates for ridge model |
| Sequence | `sequence-corpus-<ts>.jsonl` | One row per beat / keyframe event | Time-series for future section / drop models |

The live corpus is keyed by Spotify track ID and upserted in memory; only one
row per track reaches the file.  The sequence corpus appends a heartbeat row
per beat (capped at ~2 rows/s) plus immediate keyframe rows on director events.

**Do not mix these into the same model fit without aggregating the sequence
corpus to one row per track first** — long tracks would otherwise dominate the
ridge regression.

---

## Lock Coverage Metric

**Decision: `bpm_confidence >= 0.45` as the "locked" definition**

`BeatTracker` has no `beat_index` property — `getattr(grid, 'beat_index', -1)`
always returns -1.  The old `beat_index >= 0` metric was permanently 0%.

Replaced in both `_build_detector_payload` and `_write_scorecard` with:

```python
float(row.get('bpm_confidence', 0.0) or 0.0) >= _BPM_LOCK_CONFIDENCE_FLOOR
```

`_BPM_LOCK_CONFIDENCE_FLOOR = 0.45` — midpoint between the Schmidt trigger
release (0.28) and gain (0.52) thresholds.  **Keep this value in sync with the
Schmidt trigger constants in `auto_vj.py`** if those change.

---

## Scorecard Lock Rating

`_score_lock_quality(beat_lock_pct, bpm_conf_med)` rubric:

| Score | Coverage required | Median confidence |
| ----- | ----------------- | ----------------- |
| 5 | ≥ 70% | ≥ 0.60 |
| 4 | ≥ 45% | ≥ 0.45 |
| 3 | ≥ 25% | ≥ 0.30 |
| 2 | ≥ 10% | any |
| 1 | < 10% | any |

Adjust these thresholds if the natural equilibrium confidence (0.375) shifts
after phase_tol or coherence window changes.

---

## LLM Scoring Pipeline

**Decision: GPT-4o primary, claude-opus-4-8 fallback; three subsystems scored in one prompt**

Detection order: `OPENAI_API_KEY` → `ANTHROPIC_API_KEY`.

### Detector (PART 1)

Scores 5 dimensions:

1. `lock_stability` — persistence of beat lock, low churn
2. `tempo_plausibility` — BPM range believable for genre
3. `confidence_reliability` — confidence correlates with actual lock behaviour
4. `musical_alignment` — beat grid aligns with perceived musical structure
5. `external_agreement` — alignment with Essentia reference BPM (null if unavailable)

Per-song `lock_coverage_pct` in the LLM payload uses the same
`_BPM_LOCK_CONFIDENCE_FLOOR = 0.45` threshold as the scorecard.

### Recommender (PART 2) — added 2026-06-20

Scores 4 dimensions:

1. `profile_accuracy` — recommended profiles match actual music genre/tempo
2. `switch_timing` — profile switches happen at sensible BPM/energy transitions
3. `hint_integration` — active profile's BPM hint range aligns with detected BPM
4. `mismatch_management` — rate of recommendation ≠ active profile is reasonable

Payload contains: `stats` (switch count, mismatch_pct, hint_alignment_pct,
recommended vs actual distribution) and `switch_history` (up to 30 switches with
BPM/confidence context and what was being recommended at each switch point).

Output: `recommender_score.{json,md}` written alongside `detector_score.*` and
`director_score.*`.

LLM quality score for recommender replaces the local reversal-rate formula in
the score table when available.

### Director (PART 3)

Scores 4 dimensions:

1. `build_quality` — build entries triggered at genuinely rising energy
2. `drop_quality` — drops/impacts fired at high-energy moments
3. `energy_coherence` — audio signals justify each director action
4. `opportunity_usage` — director acts on high-energy windows

Unicode fix (2026-06-20): GPT-4o was returning en-dashes (U+2013) in
display names as DC3 control characters (U+0013).  The packager now restores
display fields from the original payload after JSON extraction, keyed by song
`key`, before writing `detector_score.json`.

---

## Packaging Workflow

**Decision: immutable timestamped buckets, auto-incremented letters**

```
assets/training/sets/
  <YYYYMMDD>-<playlist-slug>/   ← set directory (one per playlist × date)
    a/                           ← first session (auto-incremented)
    b/                           ← second session
    ...
      live-corpus-<ts>.jsonl
      sequence-corpus-<ts>.jsonl
      scorecard.md
      detector_score.json
      *.log  (all files from logs/)
      screenshots/   (if present)
      recordings/    (if present)
```

Never manually move corpus files.  Always use
`drop-ins/training-kit-01/tools/package_training_set.py`.
The script moves screenshots and recordings in addition to corpus and logs.

CLI non-interactive mode (used by daemon):

```bash
python drop-ins/training-kit-01/tools/package_training_set.py \
    --no-prompt \
    --set-name 20260620-classic-house-2025-2026 \
    --session-notes "baseline run post-tactus-fix"
```

---

## Headless Training Daemon

**Decision: Spotify desktop app (snap) under Xvfb — not spotifyd**

`spotifyd` rejected in favour of the real Spotify app because:
- spotifyd has no crossfade or automix → training data does not represent real listening
- Spotify desktop app appears as a Spotify Connect device → operator controls it remotely
- Full crossfade and DJ-mode continuity → more representative training audio

Infrastructure stack:
1. `pactl load-module module-null-sink sink_name=unicorn-training` — audio isolation
2. `Xvfb :99` — virtual framebuffer (no GPU, Mesa llvmpipe for unicorn-viz)
3. `spotify --no-zygote --disable-gpu` with `PULSE_SINK=unicorn-training`
4. `python -m unicornviz --audio-device unicorn-training` with `DISPLAY=:99 LIBGL_ALWAYS_SOFTWARE=1`
5. Auto-packager runs on unicorn-viz exit

Session directory naming: `<YYYYMMDD>-<playlist-slug>` built from
`--playlist-name` argument by `_slugify()` in
`drop-ins/training-kit-01/tools/training_daemon.py`.

---

## Genre / Audio Profile Protocol

**Decision: always set `[audio] profile` before a training session**

The BPM prior and search range cap (`bpm_hint_max`) must match the genre being
trained.  Without it, the detector uses the wrong prior and corpus BPM data is
unreliable.

| Genre | `[audio] profile` | Expected BPM median | bpm_hint_max |
| ----- | ----------------- | ------------------- | ------------ |
| Classic / tech house | `house` | 120–128 | — |
| Chillstep / downtempo | `chillstep` | 85–105 | 108 |
| Trance | `trance` | 130–142 | — |

Set in the training deploy's `config.toml`.  Recovery: `Alt+A` cycles profiles
in-session, recorded in the corpus `audio_profile_key` field.

---

## Tuning Protocol

One axis of change per session batch.  Recommended sequence:

1. **Baseline** — two sessions with current settings, same playlist.
2. **Candidate** — two sessions with exactly one parameter changed.
3. **Decision** — compare scorecard BPM median, lock coverage, churn, LLM score.
4. If candidate wins: commit + update this ADR's Superseded section.
5. If candidate loses: revert + record reason here.

Do not stack parameter changes before confirming the first one.

---

## Local Detector Stability Scoring

`_compute_local_scores()` scores BPM lock churn as a 1–5 stability dimension:

```python
det_stability = _score_1_to_5(churn_per_hr, [150, 350, 650, 1000], higher_is_better=False)
```

| Score | Churn/hr | Observed baseline |
| ----- | -------- | ----------------- |
| 5 | ≤ 150 | house/a (2026-06-20, ambient misprofile) ~130 |
| 4 | ≤ 350 | chillstep sessions 246–311 |
| 3 | ≤ 650 | house/c (2026-06-20, crossfade ON) 612 |
| 2 | ≤ 1000 | house/b (2026-06-20) 849 |
| 1 | > 1000 | pre-fix era sessions 3000–3700 |

**Previous thresholds `[15, 40, 80, 150]` were orders-of-magnitude too tight** —
every real session scored 1/5.  Recalibrated 2026-06-20 against 12 packaged
sessions.  Update these when the Schmidt trigger or beat-tracker v2 is retuned
substantially.

---

## Baseline Quality Targets (house, June 2026)

These targets represent the floor for proceeding to the 50-session automated run:

| Metric | Target |
| ------ | ------ |
| BPM median | 118–130 |
| Lock event churn | < 100 / session |
| Beat lock coverage (conf ≥ 0.45) | > 20% |
| LLM overall score | ≥ 3.0 / 5 |

Update targets as the detector improves.

---

## Target-Label Mechanism — Manual-Override Penalty (2026-07-18)

**Decision: manual recommender overrides are the implicit `target_score` label**

`fit_ridge_weights()` (`training_lib.py`) has always needed a `target_column`
to fit against, but nothing produced one — `training-capture-strategy.md`
finding #5 flagged this gap in June 2026 and it stayed open. The fix follows
that doc's own proposal and `INTELLIGENCE_TRAINING.md`'s L4 note that human
overrides are "the highest-signal training data we have":

- `auto_vj.py`'s `cycle_profile()` now tags a manual profile switch with
  `reason='manual_override'` on the `profile_switch` sequence-corpus
  keyframe it already emitted (cycling back to `'auto'` re-enables the
  decider but fires no keyframe, so it carries no label either way).
- `training_lib.compute_override_target_scores(sequence_corpus_paths,
  penalty_per_override=0.4)` scans sequence-corpus files for that tag,
  grouped by `spotify_track_id`: no override during a track → `target_score
  = 1.0`; each override subtracts `penalty_per_override`, floored at `0.0`.
  A track never observed in the sequence corpus gets **no score at all**
  (not assumed 1.0) — `fit_ridge_weights()` already skips rows missing the
  target column, so sparse labeling degrades gracefully.
- `sync_corpus_from_logs.py` wires this in: `--sequence-corpus` (default
  glob `assets/training/corpus/sequence-corpus*.jsonl`) and
  `--override-penalty` (default `training_lib.DEFAULT_OVERRIDE_PENALTY =
  0.4`) control it; the sync report gained a `tracks_labeled` count.

`0.4` is a first-pass, hand-picked constant, not yet validated against real
override-timing data — see the L4 "reward = absence of correction within K
seconds" idea in `INTELLIGENCE_TRAINING.md` for a future time-weighted
refinement once real labeled sessions exist to tune against.

---

## Recommender Weight Promotion (2026-07-18)

**Decision: promoted weights live in `auto-vj-01/weights/`, loaded once at startup, never automatically**

Blocker #3 on the Essentia offline pipeline was that nothing consumed
`fit_ridge_weights()`'s output. Rather than have `auto_vj.py` read
training-kit-01's output directly (a drop-in-to-drop-in runtime dependency,
against the independence rules), the fitted weights are **promoted**: a
deliberate, human-triggered copy from training-kit-01's offline output into
auto-vj-01's own directory.

- `auto_vj.py._DEFAULT_RECO_WEIGHTS` names the 13 composite-score terms
  (`lock_rate`, `tempo_fit`, `band_fit`, `centroid_fit`, `zcr_fit`,
  `onset_fit`, `spectral_shape_fit`, `kick_regularity_fit`, `top_cand_fit`,
  `mean_conf`, `mean_dconf`, `vocal_hnr_fit`, `vocal_fmr_fit`) with their
  current hand-tuned values; `_load_recommender_weights()` reads
  `drop-ins/auto-vj-01/weights/recommender-weights.json` at controller
  `__init__` and overrides only the keys present there — a missing or
  malformed file falls back to the defaults entirely.
- `drop-ins/training-kit-01/tools/promote_weights.py <fitted.json>`
  validates the fitted file's shape, archives whatever is currently active
  into `weights/archive/recommender-weights-<UTC timestamp>.json`, and
  writes the new file as the active one. A fresh offline fit has zero
  effect on a live session until this is run by hand.
- `package_training_set.py`'s LLM tuning prompt mirrors
  `_DEFAULT_RECO_WEIGHTS` as `_RECO_WEIGHT_DEFAULTS` (comment-linked, not
  imported — training-kit-01 must not hard-depend on auto-vj-01 either) and
  now renders it through one `_format_reco_weights_line()` helper used in
  both prompt locations that used to be separately hand-typed and could
  drift from each other.

Weights take effect only on the **next Auto VJ startup** — there is no
hot-reload, matching the same "load once at init" pattern as
`unicornviz.audio.profiles.PROFILES`.

---

## Superseded Decisions

| Date | Decision | Reason for reverting |
| ---- | -------- | -------------------- |
| 2026-06-20 | `spotifyd` as Spotify receiver in daemon | No crossfade/automix; replaced with Spotify desktop app same session |
| 2026-06-20 | `beat_index >= 0` as lock coverage metric | `beat_index` property does not exist in v2 tracker; always returned -1 |
| 2026-06-20 | `tactus_preference_ratio = 0.42` globally | Caused 0.75× fold (120→90 BPM) for house; BPM median fell from 122 to 98 |
| 2026-06-20 | Detector stability thresholds `[15, 40, 80, 150]` churn/hr | All real sessions exceeded 150/hr; replaced with `[150, 350, 650, 1000]` |
| 2026-06-20 | `spotify_playlist_name` in every corpus row | Per-row overhead for one-time data; replaced with single `playlist_context` entry in autovj decision log |

---

## Open Questions

- Essentia BPM external agreement not yet wired — `external_agreement` scores null.
- `bpm_locked` field in live corpus rows is not yet set (would require auto_vj.py change to populate from Schmidt trigger state).
- Per-profile `tactus_preference_ratio` override in AudioProfile (avoids global config pollution).
- Automated 50-session genre sweep: pending manual baseline confirmation for house + chillstep.
