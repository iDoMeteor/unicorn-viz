# Shippability / licensing matrix — OSS beat-tracker comparison

Dev-only benchmarking tools under `tools/beat-tracker-bench/`. None of these
are wired into the shipped app or `requirements.txt` — see each adapter's own
README for full install notes. This table exists to answer one question per
model: could this ever ship in unicorn-viz (a Linux-first open-source
product), separate from how well it scores.

| Model   | Code license | Weights license | Streaming-capable | Wall-clock / 120 s track (uncapped) | Wall-clock / 120 s track (capped: `taskset -c 0-7`, `nice -n 10`, 8 BLAS/OMP threads) | Shippable in unicorn-viz as-is? |
|---------|---------------|------------------|--------------------|--------------------------------------|------------------------------------------------------------------------------|----------------------------------|
| BTrack  | GPL-3.0 | n/a (algorithmic, not ML) | **Yes — true causal**, but only via custom bindings written for this project. C++ core is causal by design (`processAudioFrame`/`getCurrentTempoEstimate`); upstream's official Python bindings only expose three batch functions and were never touched — new pybind11 bindings (`btrack_streaming.cpp`) bind the real causal API directly. | ~4.3 s avg (217 s / 51 tracks, uncapped) / ~3.2 s avg (974 s / 306 tracks, uncapped) — cheapest of the four by a wide margin, no cap was needed | Not capped — uncapped pace already well under any budget concern | **No.** GPL-3.0 is copyleft; would obligate the whole app regardless of how cheap or accurate it is. The onset function it uses (Bello et al. complex spectral difference) is a published, reimplementable algorithm independent of BTrack's own GPL code, if this project ever wants it without the license. |
| madmom  | BSD (2-clause), permissive | **CC BY-NC-SA 4.0 — non-commercial** (pretrained `.pkl` weights, in the `madmom_models` submodule, explicitly called out by madmom's own `LICENSE`) | **Yes — true causal.** `DBNBeatTrackingProcessor(online=True)` is a genuine per-frame streaming API, not a buffer-rerun approximation. | ~29.6 s avg (1512 s / 51 tracks, uncapped, all cores) | ~23.5 s avg (7181 s / 306 tracks, `taskset -c 0-7`/`nice -n 10`/8 BLAS-OMP threads) — capped run was not slower than uncapped on this machine | **Conditional.** Architecture (BSD) is shippable. Current pretrained weights are not (non-commercial) — would need unicorn-viz to train its own weights on a compatible license, or find/train replacement weights, before this could ship. |
| Essentia | **AGPL-3.0** | n/a (feature-engineered algorithm, not ML) | **No — not true streaming**, despite the `essentia.streaming` module name. Confirmed by reading `tempotapdegara.cpp`: `RhythmExtractor2013`/`TempoTapDegara` only compute once, at end-of-stream, with no persistent state across `run()` calls. This adapter approximates online behavior by rebuilding and reprocessing a trailing buffer roughly every 1 s — real cost, not real streaming. | ~414.5 s avg (21142 s / 51 tracks, uncapped) — by far the slowest, this is why the 311-track set wasn't attempted for Essentia | Not measured — uncapped pace alone already ruled out the larger run | **No.** AGPL-3.0 is stricter than GPL (network-use copyleft). Also structurally not a real-time engine as shipped — would need to become one before the license question even matters. |
| BeatNet | **CC BY 4.0** (a Creative Commons *content* license applied to code — unusual; no software patent grant, terms weren't written for this use case) | Same CC BY 4.0 (weights bundled in the same repo/package) | **No — not true streaming.** No incremental call in its public API even in "online" mode; this adapter buffers and re-runs BeatNet's online algorithm over the accumulated buffer every 0.5 s. | Could not complete 120 s clips at a usable rate even at 45 s clips (owner directive: deferred for the night, "needs >3x realtime, not a live candidate") | n/a — deferred | **No**, on two independent grounds: not real-time as shipped, and CC BY 4.0's atypical terms for software would need explicit legal review before any use beyond benchmarking. |

## Notes

- "Streaming-capable" here means *this project's actual product requirement*
  — a genuine per-frame update with no lookahead into the whole file — not
  just "the vendor calls it real-time." Two of the four (Essentia, BeatNet)
  advertise real-time/streaming modes that turned out, on inspection of the
  actual API surface, not to provide incremental per-frame computation. Only
  madmom's online DBN is a true match for how this project's own
  `beat_grid.py` tracker actually has to run.
- BTrack's C++ core is architecturally the closest peer to this project's
  own comb-filter tracker (and one of aubio's own methodological
  ancestors), but its published bindings don't expose that architecture to
  Python at all — the gap is packaging, not the algorithm.
- Every model here except madmom's code is either copyleft (GPL/AGPL) or
  carries non-standard terms (CC BY applied to software) — none were built
  in this comparison with an eye toward being embedded in a shipped
  product; that's expected of academic MIR tooling, not a flaw specific to
  any one of them.
