# Auto VJ Training Pack Protocol

Owner: Auto VJ Team
Status: active
Last updated: 2026-05-24

## Purpose

Define a repeatable protocol for serious Auto VJ simulation training using curated
MP3 sets, so tuning changes are evaluated against the same material each time.

## Core Rules

1. Keep one axis of change per run.
2. Use fixed training packs for A/B comparison.
3. Always log decisions during training runs.
4. Score every run with the same tooling.
5. Keep manual interventions minimal and documented.

## Pack Layout

Create one folder per pack under `assets/audio/training-packs/`:

- `warmup/`: 2-3 tracks for startup lock behavior.
- `core/`: 6-10 tracks with clear build/drop structure.
- `edge/`: 3-6 tracks with fakeouts, long builds, broken phrasing, or sparse transients.
- `notes.md`: one-line intent for each track.

Recommended naming:

- `TP01-house-core`
- `TP02-peak-time-core`
- `TP03-edge-cases`

## Track Selection Guidance

Include each of these categories in every serious pack:

1. Clear four-on-floor structure (baseline reliability).
2. Long tension builds (tests premature drop/climax behavior).
3. Fake drop / breakdown trap structure (tests false positives).
4. Dense high-hat/transient content (tests BPM lock stability).
5. Tempo drift or mixed energy sections (tests recommender/profile switching).

## Run Protocol

1. Restart app before each pack run.
2. Set `log_decisions = true` in Auto VJ config.
3. Run all tracks in order without changing tuning mid-pack.
4. If manual intervention is needed, do it and continue, but record it.
5. Save session ID and pack ID together.

Suggested run matrix per candidate change:

- Baseline: 1 full pass on target pack.
- Candidate: 1 full pass on same pack.
- Tie-breaker: 1 additional pass only if results are mixed.

## Required Outputs Per Run

After each pack pass, run:

```bash
python drop-ins/auto-vj-01/tools/session_scorecard.py --latest 12 --focus-profile house --out drop-ins/auto-vj-01/docs/scorecards/latest-training-scorecard.md
python drop-ins/auto-vj-01/tools/director_lint.py --latest 12
python drop-ins/auto-vj-01/tools/analyze_autovj_log.py "$(ls -1t logs/autovj-*.jsonl | head -1)"
```

Capture:

- Latest log filename
- Pack ID
- Candidate ID (baseline or change name)
- Summary of misses (drop, impact, climax)

## Evaluation Rubric

Score each run on a 1-5 scale:

1. BPM lock quality
2. Build-to-drop correctness
3. Impact hit quality
4. Climax timing quality
5. Visual continuity / non-thrashy flow

Add optional tags:

- `late-drop`
- `missed-drop`
- `impact-weak`
- `climax-early`
- `climax-missed`
- `profile-thrash`

## Change Control

When a candidate wins:

1. Commit code/config change.
2. Record winning pack + session IDs in commit body or notes.
3. Do not stack another change until the winner is validated on a second pack.

When a candidate loses:

1. Revert immediately.
2. Record why it failed.
3. Move to next hypothesis.

## Session Note Template

Use this template for each serious run:

```text
Date:
Pack ID:
Candidate ID:
Log file:
Manual interventions (Y/N + brief note):
Rubric (1-5): lock=?, build/drop=?, impact=?, climax=?, flow=?
Miss tags:
Key moments (timestamp + what happened):
Decision: keep / revert / retest
```

## Recommended Cadence

- Build packs first.
- Run at least 2 packs per major strategy change.
- Prefer fewer, high-quality labeled runs over many unlabeled runs.
