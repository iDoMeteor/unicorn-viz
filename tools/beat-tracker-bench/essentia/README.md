# Essentia beat-tracker benchmarking adapter

## What this is

A small, standalone, **dev-only** tool that wraps
[Essentia](https://github.com/MTG/essentia)'s streaming tempo trackers
behind a simple per-block interface so its running BPM estimate can be
compared against unicorn-viz's own in-house beat tracker
(`unicornviz/audio/beat_grid.py`, untouched by this tool). It is not
imported by the shipped application and is not wired into anything under
`unicornviz/`, `drop-ins/auto-vj-01/`, or `drop-ins/training-kit-01/`.

It is one of a set of sibling adapters (this one, plus BTrack, madmom, and
BeatNet) built to the same shared interface so results line up:

```python
class ExternalBeatTracker:
    def warm_up(self, sample_rate: int) -> None: ...
    def feed(self, block: np.ndarray, block_start_s: float) -> None: ...
    @property
    def bpm(self) -> float: ...
    @property
    def confidence(self) -> float: ...  # 0.0 if the library doesn't expose one
```

"Compatible in intent" here means **causal / real-time-oriented
trackers only** — the point of this benchmark is to see how a tracker
that could plausibly run live compares to ours, not to chase the
highest-accuracy offline number. That's why this adapter uses
`RhythmExtractor2013` configured with `method='degara'` (built on
`BeatTrackerDegara` / `TempoTapDegara`), not Essentia's more accurate but
non-causal `method='multifeature'` (`BeatTrackerMultiFeature`).

## License

Essentia is **AGPL-3.0**, which is even stricter than plain GPL (it
extends copyleft to network use, not just distribution). That is a hard
line for this project: **this code must never be imported by, bundled
with, or shipped as part of the unicorn-viz application.** It lives in
its own isolated venv under this directory and is used only as an
offline, dev-side comparison tool. See Essentia's own repository for the
full license text: https://github.com/MTG/essentia/blob/master/COPYING.

## Install

```bash
cd tools/beat-tracker-bench/essentia
python3.11 -m venv .venv     # 3.11, matching the project's runtime; the
                              # PyPI essentia wheel does not (yet) publish
                              # for 3.14, which is what `python3` resolved
                              # to on this machine
source .venv/bin/activate
pip install -r requirements.txt
```

This installs cleanly from the prebuilt PyPI manylinux wheel
(`essentia==2.1b6.dev1389`, `cp311-manylinux_2_17_x86_64`) with no system
packages, `apt`/`dnf`, or `sudo` required. `numpy` comes along as a
declared dependency; `pyyaml` and `six` are Essentia's own transitive
deps. Exact versions are pinned in this directory's `requirements.txt`
(**not** the project's root `requirements.txt` — this tool is
intentionally not part of the main dependency set).

Run everything below through `.venv/bin/python`, e.g.:

```bash
.venv/bin/python run.py --synthetic-click --bpm 120 --duration 30
```

## Bridging the streaming dataflow-graph model into a per-block `feed()`

Essentia's `essentia.streaming` module is not a "call a function per
frame" API — you build a graph of algorithm nodes wired together with
`>>`, then call `essentia.run(source_node)` to drive tokens through the
whole graph until the source (a `VectorInput` here) reaches end-of-stream.
Adapting that into `ExternalBeatTracker.feed()` took some real
investigation (see Quirks below for what was tried and ruled out); the
approach that actually works:

1. `feed()` appends each incoming block to an internal **trailing buffer**
   in Python (capped at 30 s — see `_TRAILING_WINDOW_S`), not directly
   into Essentia.
2. Once enough audio has accumulated (>= 2 s, `_MIN_AUDIO_S`) and the
   recompute throttle allows it (at most once per 1 s of newly fed audio,
   `_RECOMPUTE_INTERVAL_S`), `feed()` builds a **fresh** small streaming
   network — `VectorInput(trailing_buffer) -> RhythmExtractor2013(method
   ='degara') -> Pool` — and calls `essentia.run(vector_input)` **once**,
   processing the whole trailing buffer in that single call.
3. `pool['bpm']` / `pool['confidence']` are read back immediately after
   that `run()` call and cached as the adapter's current `bpm` /
   `confidence`.

So each "checkin" is a single-shot, run-to-completion Essentia streaming
call over recent history, rebuilt from scratch — not a persistent network
that's incrementally topped up over many `run()` calls. That rebuild-per-
checkin shape is what the library's actual behavior forces (next
section); it is still a legitimate "streamed a `VectorInput` and read the
pool after `run()`" usage, just applied to a re-grown window rather than
only the newest samples.

## Quirks / gotchas found while building this

- **The obvious incremental pattern doesn't accumulate for these
  algorithms.** Essentia's own real-time example
  (`tutorial_tensorflow_real-time_auto-tagging.ipynb`) shows a pattern of
  reusing one `VectorInput` backed by a fixed-size numpy buffer, and on
  each new chunk: copy data into the buffer in place, call
  `essentia.reset(vector_input)` (this only re-arms the `VectorInput`
  itself — verified empirically that a plain `FrameCutter`'s hop position
  correctly persists across repeated `reset()+run()` calls, so this is
  not blanket-resetting the whole graph), then `essentia.run
  (vector_input)` again. That pattern works great for simple, stateless
  per-frame algorithms. It does **not** work for `TempoTapDegara` /
  `BeatTrackerDegara` / `RhythmExtractor2013`: their `process()` methods
  literally start with `if (!shouldStop()) return PASS;` (confirmed by
  reading `tempotapdegara.cpp`), meaning they do no incremental work at
  all and only compute once, when the current `run()` call's `VectorInput`
  reaches its own end-of-stream. Repeatedly feeding tiny blocks (e.g. 1024
  samples / ~23 ms) through `reset()+run()` never produced a nonzero BPM
  even after 10 s of cumulative audio, while feeding one big 2-second slab
  in a single `run()` call produced a reasonable estimate immediately.
  Empirically, each successful `run()` call analyzes only what it was
  given in *that* call, not a running history — hence the "rebuild and
  reprocess a trailing window" design above rather than true incremental
  updates.
- **44100 Hz is a hard requirement.** `BeatTrackerDegara`,
  `TempoTapDegara`, and `RhythmExtractor2013` all document that they
  require 44100 Hz input and silently misbehave otherwise. The adapter
  resamples via plain `numpy.interp` (no anti-aliasing filter — adequate
  for a click track or reasonably-behaved music signal, not
  broadcast-quality) if `warm_up()` is called with a different rate.
  `run.py`'s own audio loading (`essentia.standard.MonoLoader`) and
  synthetic click generator both already produce 44100 Hz, so that path
  is not normally exercised.
- **`confidence` is always 0.0 with `method='degara'`.** This is
  documented behavior, not a bug: `RhythmExtractor2013`'s docstring says
  "ignore this value if using 'degara' method". Convenient, since it lines
  up with the shared adapter interface's own convention for libraries
  that don't expose a confidence score.
- **Declared outputs must all be connected before `run()`.**
  `RhythmExtractor2013` also emits `ticks`, `estimates`, and
  `bpmIntervals`; Essentia requires every declared output to be wired
  somewhere (even if it's `>> None` to discard it) before the network can
  run.
- **Runtime cost.** Because each recompute reprocesses the whole trailing
  window from scratch (up to 30 s of audio through FFT + onset detection
  + tempo estimation), the self-test below takes roughly 70-80 s of wall
  time for 30 s of synthetic audio at the default 100 ms block size /
  1 s recompute throttle. That's expected and acceptable for an offline,
  dev-only benchmark; it is not meant to run faster than real time.
- **No system packages needed.** `essentia.standard.MonoLoader` (used for
  `--audio`) decoded a plain WAV file with no `ffmpeg`/`libav` system
  install required beyond what the PyPI wheel already bundles.

## Self-test

```bash
.venv/bin/python run.py --synthetic-click --bpm 120 --duration 30 --out /tmp/result_120.json
.venv/bin/python run.py --synthetic-click --bpm 140 --duration 30 --out /tmp/result_140.json
```

Results on this machine:

| target BPM | final BPM estimate | error |
|---|---|---|
| 120 | 119.95 | 0.04% |
| 140 | 139.97 | 0.02% |

Both land far inside the ±4% tolerance, with no half/double-time lock
observed on these clean synthetic click tracks. A quick sanity pass
against a synthetic 128 BPM click track written to a WAV file and loaded
via `--audio` also converged correctly (128.07 BPM), confirming the
`MonoLoader` ingestion path independently of `--synthetic-click`.

## Output format

`run.py` writes JSON (to `--out <path>` or stdout) shaped like:

```json
{
  "sample_rate": 44100,
  "block_ms": 100.0,
  "duration_s": 30.0,
  "final_bpm": 119.95,
  "final_confidence": 0.0,
  "ticks": [
    {"t": 0.0, "bpm": 0.0, "confidence": 0.0},
    {"t": 0.1, "bpm": 0.0, "confidence": 0.0},
    "...",
    {"t": 29.9, "bpm": 119.95, "confidence": 0.0}
  ]
}
```

`bpm`/`confidence` in each tick entry hold steady between recomputes
(reflecting the actual internal update cadence described above) and jump
when a new trailing-window analysis completes.
