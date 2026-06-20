# ADR: Auto VJ Training & Model Tuning

Owner: unicorn-viz maintainers
Status: Active
Last updated: 2026-06-20

This document records architectural decisions for the Auto VJ training pipeline:
corpus design, scoring, packager logic, headless session infrastructure, and
tuning protocol.  Update it whenever touching `tools/package_training_set.py`,
`tools/training_daemon.py`, scorecard thresholds, LLM scoring, Schmidt trigger
constants, or adding / changing a training workflow step.

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

## LLM Detector Scoring

**Decision: GPT-4o primary, claude-opus-4-8 fallback**

Detection order: `OPENAI_API_KEY` → `ANTHROPIC_API_KEY`.  Scores 5 dimensions:

1. `lock_stability` — persistence of beat lock, low churn
2. `tempo_plausibility` — BPM range believable for genre
3. `confidence_reliability` — confidence correlates with actual lock behaviour
4. `musical_alignment` — beat grid aligns with perceived musical structure
5. `external_agreement` — (not yet wired; requires Essentia reference data)

**Unicode fix (2026-06-20):** GPT-4o was returning en-dashes (U+2013) in
display names as DC3 control characters (U+0013).  The packager now restores
display fields from the original payload after JSON extraction, keyed by song
`key`, before writing `detector_score.json`.

Per-song `lock_coverage_pct` in the LLM payload uses the same
`_BPM_LOCK_CONFIDENCE_FLOOR = 0.45` threshold as the scorecard.

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

Never manually move corpus files.  Always use `tools/package_training_set.py`.
The script moves screenshots and recordings in addition to corpus and logs.

CLI non-interactive mode (used by daemon):

```bash
python tools/package_training_set.py \
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
`--playlist-name` argument by `_slugify()` in `training_daemon.py`.

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
