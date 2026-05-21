# Auto VJ Handoff Package (2026-05-21)

## Purpose

This document prepares external debugging handoff for the Auto VJ transition/BPM
accuracy effort in `unicorn-viz`.

Primary unresolved issue:

- BPM harmonic mis-lock on some tracks (example: expected ~96 BPM, observed ~155-170 BPM)

Secondary status:

- Transition pacing/churn is substantially improved vs earlier baseline.

## Code Areas In Scope

- `drop-ins/auto-vj-01/beat_grid.py`
- `drop-ins/auto-vj-01/auto_vj.py`
- `unicornviz/audio/analyzer.py`
- `tools/analyze_autovj_log.py`
- `docs/debug/auto-vj-drop-detection-debug-2026-05-21.md`

## Current Behavior Snapshot

Latest session analyzed:

- `logs/autovj-20260521T153837.jsonl`

High-level metrics:

- Entries: 454
- detector ticks: 359
- mode transitions: 26
- transition bursts (`>=3 transitions in 2s windows`): 0
- chain presence: BUILD/DROP/IMPACT/CLIMAX all present

Detector profile summary (latest session):

- BPM median clustered around ~156 despite suspected slower song
- `CRUISE` mode BPM median: 156.4
- potential missed drop windows: 1

## Timeline of Relevant Changes

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

## What Is Working

- Detector no longer consumes reactivity-scaled channels.
- Drop-score saturation issue is reduced.
- State chains are coherent and no longer thrashing rapidly.
- Profile pacing is more musically sustained.

## What Is Not Fully Solved

- BPM can still land in fast harmonic lane with moderate confidence.
- This affects profile auto-switching behavior and beat-aware timing nuance.

## Hypotheses (For Next Team)

1. Onset stream in analyzer is still over-triggering subdivisions for some source content.
2. IOI family scoring in BeatGrid may need stronger tempo prior or longer memory window.
3. Candidate scoring tie-breaks are too permissive for high-BPM lanes in mid confidence.
4. Profile-specific tempo priors are missing (e.g. house profile should resist 150+ unless confidence is very high).

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

3. Play known slower material (~90-110 BPM) and observe HUD BPM.

4. After 5-15 minutes, analyze latest JSONL:

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

## Recommended Next Experiments

1. Tempo-prior gating by profile and confidence
- Example: if confidence < 0.8, discourage >145 BPM lanes for house/chill material.

2. Extended IOI memory for BPM scoring
- Evaluate 64->128 beat-time window and weighted recency scoring.

3. Stronger harmonic rejection logic
- Penalize candidate lanes that imply implausible beat_phase behavior over time.

4. Analyzer onset refinement
- Reduce subdivision sensitivity using spectral-band onset weighting and adaptive refractory by estimated tempo.

5. Ground-truth benchmark harness
- Add offline test corpus with known BPM tracks and report absolute BPM error + octave/harmonic error rate.

## Deliverables Requested From Receiving Team

- Patch proposal for BPM lane accuracy on slower tracks.
- Before/after metrics on:
  - median BPM error
  - harmonic/octave mis-lock rate
  - confidence calibration quality
- Any profile-specific prior strategy that avoids false fast locks without harming genuine high-BPM material.

## Contact Context

This handoff follows iterative live tuning with telemetry-heavy runs on Fedora/Linux,
with Auto VJ currently stable in transition pacing but still inaccurate on certain BPM lanes.
