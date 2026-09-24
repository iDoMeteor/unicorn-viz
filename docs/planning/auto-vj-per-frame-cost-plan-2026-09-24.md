# Auto VJ per-frame cost — plan

Owner: perf seat (proposal)
Status: **proposed — owner paused it for a conversation; no code changes until then**
Last updated: 2026-09-24

After the GPU console, the audio process and today's tuning, Auto VJ is the
largest single item on the main (GL) thread.  This is the plan to bring it
down without changing what it decides, plus one structural option.  It is
for discussion with the owner; the auto-vj seat would own the changes.

## 1. What the live profile shows

60 s, mixer playing, OBS streaming, through a transition (2026-09-24).
`AutoVJController.update()` is **~22% of the main thread** (inclusive):

| Item | % of main thread | What it is |
|---|---|---|
| `BeatTrackerV3.update` | 4.3 | the detector, fed per frame with the analysis frame + onsets |
| `_now_playing_snapshot` | 3.8 | now-playing lookup — **already reduced** by core beta.164's per-frame memo |
| `_update_director` | 3.6 | director state machine (phrase clock, drop/build logic) |
| `_record_live_training_row` + `_build_live_training_row` | 3.2 (2.5 inside) | a training-corpus row built **every frame** |
| `_phrase_bias` | 2.5 | phrase-role bias multipliers |
| `_current_song_progress` | 1.9 | position within the track |
| `_run_reactivity_drift` | 1.7 | reactivity nudges (its `set_reactivity` is now local and free, core beta.163) |
| `_update_profile_recommendation` | 1.0 | genre/profile recommender |

The main thread also has to fit the visualizer's render in each frame, so
every millisecond here is a millisecond of frame budget and GIL time.

## 2. Principles

* **Decisions must not change unless we mean them to.**  Phase A is pure
  cost work: every change is checked with the replay harness
  (`session_replay`) producing identical decision logs before and after.
* **Detector and director follow CLAUDE.md's versioning duties** —
  anything that alters their numbers bumps `_DETECTOR_VERSION` /
  `_DIRECTOR_VERSION`, updates `weights-and-thresholds.md` and the ADR.
* **The training corpus is not ours to reshape silently** (see A1).

## 3. Phase A — same decisions, less work per frame

| # | Change | Expected | Risk / gate |
|---|---|---|---|
| A1 | **Live training rows at a fixed rate** (e.g. 10-20 Hz) instead of every frame, or build the row lazily only when the writer will keep it | the ~3% above | **Changes the corpus's row counts and timing** — scorecards, packaging and the LLM scoring payload all read it.  Needs the owner's and the training seat's decision; may be "keep per-frame" by design. |
| A2 | Cache per frame the values several director/recommender helpers recompute (`_current_song_progress`, song position, kick regularity, sub level) | 1-2% | none if the cache is per frame; replay-identical |
| A3 | `_phrase_bias` / `_update_profile_recommendation`: recompute on their real triggers (bar/phrase boundary, profile change, a throttle matching their documented cadence) instead of every frame | 1-3% | only where the code already treats them as slow signals; replay-identical |
| A4 | Micro-profile the detector's own per-frame path (`BeatTrackerV3.update`) the way the analyzer was done today (it was ~46% `.mean()` calls) | unknown until measured | detector numerics must stay bit-identical, or the change becomes a versioned detector change |

Method: the live trampoline profile (as today) to pick targets, then the
replay harness to prove each change is decision-identical.

## 4. Phase B (structural option) — the detector in the audio process

The detector consumes the analyzer's output (frames + onsets).  Today that
crosses from the audio process to the main process and the detector runs
at the visual frame rate on the GIL thread.  It could instead run **inside
the audio process, next to the analyzer**:

* at the analysis rate (~47 Hz) on the analyzer's own blocks, with no pipe
  hop and no frame-rate coupling;
* on the free-threaded interpreter once that is switched on (the helper is
  GIL-free-ready — see
  [streaming-and-audio-runtime-recommendations](streaming-and-audio-runtime-recommendations-2026-09-24.md));
* publishing the grid (BPM, phase, confidence, downbeat, section hints) as
  a per-tick value the main side reads, the way `audio_snapshot()` works.

The **director stays main-side** — it drives effects and transitions
through `vj_api` on the GL thread — and reads the published grid.

Costs and gates: running per analysis block rather than per frame is a
timing change to the detector, so its outputs will differ → a versioned
detector change with replay and soak validation, ADR and weights-doc
updates.  The replay harness drives the tracker directly and must keep
working.  This is weeks of careful work, not an afternoon.

## 5. Questions for the owner

1. A1: is per-frame live-training capture deliberate (the corpus design),
   or would a fixed rate serve the training program as well?
2. Phase A only, or is Phase B (detector beside the analyzer) on the table?
3. Should the auto-vj seat own this, with the perf seat supplying profiles
   and review?
