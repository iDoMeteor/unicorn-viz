# GPU mixer console + audio process split + multithreading

Owner: perf seat (with the owner, live) · Status: **active — phases 1, 2a, 2b landed; live-profile tuning landed** ·
Last updated: 2026-09-24

Rollback point: tag `checkpoint/pre-gpu-mixer-audio-split-2026-09-24`
(`60235ee`, every submodule pinned). Restore with
`git checkout <tag> && git submodule update --init --recursive`.

Inputs folded in: the 2026-09-24 live perf pass, the free-threading
findings and the perf-team mixer addendum
([free-threaded-python-2026-09-24.md](free-threaded-python-2026-09-24.md)),
and the owner's decisions below.

## 1. Owner decisions (2026-09-24)

1. **The GL process stays on the GIL.** moderngl/glcontext are not being
   rebuilt. Everything that is not GL moves into its own processes, which
   are built so they *can* run free-threaded later.
2. **The audio process owns the whole audio system:** capture, analyzer,
   mixer engine (decks, DSP, FX, sampler, stems playback) and the output
   and headphone streams.
3. **No switch to 3.14t in this mission.** Standard CPython everywhere; new
   code is written free-thread-safe and the audio process's interpreter is
   a config value, so pointing it at `python3.14t` later is a one-line
   change guarded by a GIL check.
4. **Flags default ON, old paths stay one flag away** (Pillow console,
   in-process engine) until we have lived on the new ones.

## 2. Why (measured, not assumed)

Live profile of the running app, 1920x1080, tooltips off, streaming off:

| Thread | CPU | What it spent it on |
|---|---|---|
| `DjMixerRender` | ~66% of a core | Pillow raster at ~50 ms/frame vs a 33 ms budget, every frame over, so it never sleeps and holds the GIL |
| main (`python`) | ~30% | visualizer + drop-in `update()`s (Auto VJ ~23% of it) |
| `uv-audio-analyz` | ~12% | analyzer, ~1 ms per block |
| `DjMixerAudioWriter` | ~4% | engine `render_block()`, 2 ms mean of a 10.7 ms budget |

Three CPU-heavy loops share one interpreter: the audio DSP loop (10.7 ms
deadline), the console raster (33 ms), and the visualizer (16-33 ms).
Real-time priority on the audio thread cannot fix a GIL it has to wait
for. Garbage collection makes it worse: gen-2 pauses of **125 ms** are in
today's logs, and a GC pause stops every thread in the process, so no
amount of threading protects audio from it. Only a process boundary does.

## 3. Target architecture

```
 main process (GIL, owns GL)                 audio process (no moderngl)
 ─────────────────────────────               ───────────────────────────────
 visualizer render loop                      block loop: engine.render_block
 mixer console: draw-list build  ──cmd ring──▶  command drain once per block
   (render thread) + GPU submit              decks / FX / sampler / outputs
   (main thread, 1 draw call)   ◀─state shm──  per-block state struct (seqlock)
 controllers / MIDI / HID                    capture + analyzer ──▶ AudioData shm
 Auto VJ, overlays, drop-ins    ◀─AudioData─   (tap the master mix directly)
                                             decode / stem workers (processes)
                                               └─ PCM into shared memory
```

### 3.1 Console on the GPU (phase 1)

* A core **draw-list recorder** (`unicornviz/gpu2d.py`) implements the
  ImageDraw subset the console uses (`rectangle`, `rounded_rectangle`,
  `line`, `ellipse`, `arc`, `pieslice`, `polygon`, `text`, image paste) by
  appending fixed-size instances to a flat float32 buffer. No pixels on the
  CPU.
* Text and images go through a **texture atlas** (shelf-packed, one RGBA
  texture). Text is cached per `(string, font)` as a white alpha mask and
  tinted on the GPU, so colours don't multiply atlas entries.
* A core **GL batch renderer** draws the whole console as one instanced
  call with an SDF uber-shader (anti-aliased rects, rounded rects,
  ellipses, arcs, capsule lines, textured quads). It uses the raw-GL
  binding `SecondaryGLWindow` already loads via `SDL_GL_GetProcAddress`,
  **not moderngl**: moderngl cannot attach to a second context on native
  Wayland (see that module's docstring).
* The mixer swaps its `_ScaledDraw` target from a Pillow image to the draw
  list. Every one of the ~580 draw calls already goes through that one
  proxy, so the layout code is untouched. The waveform's per-frame numpy
  pixel tile becomes one bulk append of bar instances.
* Per frame the upload drops from **8.3 MB** (full RGBA raster, plus the
  `tobytes` copy) to a few hundred KB of instances plus any new atlas
  entries.
* Flag: `[dj_mixer] gpu_console = true` (default). Pillow stays the
  fallback, and is still used for hosted mode and anything that needs
  pixels on the CPU.
* Next steps inside phase 1: skip submit when the draw list is unchanged;
  cache static sections as retained sub-lists; waveforms as a 1D peak
  texture drawn by a shader (playhead and zoom as uniforms).

### 3.2 Audio process (phase 2)

* **Launch:** `multiprocessing` with the `spawn` context (the app is
  multi-threaded before this starts, so no `fork`). Interpreter configurable
  via `multiprocessing.set_executable` → `[audio_process] python = ""`
  (empty = the running interpreter). A **GIL guard** logs loudly if a
  configured free-threaded interpreter comes up with the GIL enabled, and
  names the module that turned it on.
* **Commands (main → audio):** a single-producer ring in shared memory of
  small records `(target, op, args)`, drained once per block. Setters are
  fire-and-forget. The few calls that need an answer get a request id and
  the answer comes back in state.
* **State (audio → main):** one shared-memory struct written per block
  under a seqlock (position, level, peaks, playing, BPM, beat phase, sync,
  pitch, cue/loop state per deck, master peak, audio diag numbers). Cold
  state (track path, cues, loops, stems, grid, FX chain names) is a
  versioned snapshot republished only when it changes.
* **Proxies:** the main process gets `EngineProxy` / `DeckProxy` with the
  same attribute and method surface the console, controllers, Auto Play and
  LEDs already use (measured: 10-100 distinct members per module). Reads
  come from the state mirror, never a round trip. Calls and attribute
  writes become commands.
* **Decoded audio in shared memory:** a decode worker process decodes and
  resamples into a `SharedMemory` block and hands the audio process a name
  and length. The main process never holds sample arrays. Stems are written
  at 48 kHz at extraction time, so loading them stops resampling.
* **Capture + analyzer move in too.** `AudioData` is published through
  shared memory to the main process (it is a fixed set of floats plus
  `bands`, `fft` and `waveform` arrays). When the mixer is playing, the
  analyzer taps the master mix directly instead of recapturing it from
  PipeWire.
* **Block loop hygiene:** preallocated buffers, no logging, no per-block
  Python allocations beyond what numpy DSP already does. `gc.freeze()`
  after startup and a raised gen-2 threshold in the audio process, whose
  heap stays small.
* Flag: `[dj_mixer] audio_process = true` (default once it passes its soak;
  the in-process engine stays one flag away).

### 3.3 Multithreading

* In the audio process, deck rendering is written so the four decks can
  render on a thread pool (a flag, effective once the process runs
  free-threaded; on the GIL build numpy already releases the GIL inside its
  heavy kernels).
* Loads, decode, analysis and stem work run in worker processes, never on
  the main or audio threads.
* Main process `update()` contract: **O(1) and under 1 ms**. It drains
  queues and reads state. Anything proportional to library size runs on an
  event or timer.

## 4. Phases and landing order

Each phase lands on its own commits with its own version bumps, so any of
them can be reverted on its own.

1. **GPU console.** Core `gpu2d` (recorder, atlas, renderer) → mixer
   `gpu_console` → unchanged-frame skip → retained sections → waveform
   shader.
2. **Audio process.** Shared-memory primitives (ring, seqlock struct, PCM
   blocks) → audio host running the existing `MixerEngine` → proxies → decode
   worker → capture + analyzer move → stems at 48 kHz.
3. **Threads and workers.** Loads, analysis and stems in workers; the
   `update()` audit; the deck thread pool behind its flag.
4. **Free-thread readiness.** The GIL guard test; the interpreter setting;
   an import map per process.

## 4a. Progress

| Step | State | Where |
|---|---|---|
| 1a GPU console (draw list, atlas, instanced SDF renderer, mixer on it) | **landed** | core beta.159 `unicornviz/gpu2d.py`; dj-mixer-01 0.216.0 `gpu_console` |
| 2a Engine in its own process (shadows, shared-memory tracks, crash recovery) | **landed** | core beta.160 `unicornviz/remote_objects.py`; dj-mixer-01 0.217.0 `audio_process` |
| Live-profile tuning (console tooltips/list stats/paths, helper publish scope, cold device lists, local reactivity, now-playing memo) | **landed** | core beta.163-164; dj-mixer-01 0.218.1-0.218.3 |
| Control Room on the GPU draw list | handed to the Control Room seat (unicorn-viz-15) | |
| 1b Skip recording unchanged console sections; waveform shader | next | |
| GC: freeze the long-lived heap (gen-2 124 ms -> 1 ms) | **landed** | core beta.161 `gc_tuning`; dj-mixer-01 0.217.1 |
| 2b Capture + analyzer into the audio process, mixer engine shares it (streams, values, hot snapshots, factories) | **landed** | core beta.162 `unicornviz/audio/process.py`; dj-mixer-01 0.218.0 |
| 2c Decode worker writes straight into shared memory; stems at 48 kHz | next | |
| 3 Worker processes for analysis/stems; `update()` audit | next | |
| 4 GIL guard + per-process import map for a free-threaded helper | **import map done**; helper logs its GIL state | see 4b |

Measured so far: a 1920x1080 console frame builds in 7.1 ms instead of
22.9 ms and uploads 67 KB instead of 7.9 MB (harness); the engine's
`render_block()` no longer shares a GIL with anything in the main process.

### 4b. The audio helper's import map (2026-09-24)

What the helper (core audio process + dj-mixer-01's engine) actually loads,
by replaying its factories' imports and listing compiled extensions:

* **No** moderngl, glcontext, SDL2, Pillow, OpenCV or rtmidi -- none of the
  free-threading blockers.
* Third-party compiled packages: **PyAV, numpy, scipy, cffi** (sounddevice /
  soundfile's backend) -- all with official `cp314t` wheels -- plus
  **charset_normalizer**, pulled in only by `numpy.f2py`'s optional import
  when scipy's array-API layer touches it (`deck.py` -> `scipy.signal`);
  it also ships `cp314t` wheels (3.5.1).
* Everything else is stdlib.

So the helper can run GIL-free as soon as a free-threaded interpreter with
those wheels exists: point `[audio] process_python` (core) and
`[dj_mixer] audio_process_python` at it, and the helper's startup log line
says whether the GIL really stayed off.  Not done here: installing
`python3.14-freethreading` and building that environment is an owner call.

## 5. How we know it worked

| Metric | Now | Target |
|---|---|---|
| Console frame build (render thread) | ~50 ms | < 5 ms per rebuilt frame, ~0 when unchanged |
| Console upload per frame | 8.3 MB | < 0.5 MB |
| Audio block CPU | ~19% of budget, spiky (max 369 ms) | < 30% of budget, no spikes from other threads |
| Main `update()` | multi-ms | < 1 ms |

Measured the same way as today: the mixer's own `ui` and `audio` diag
lines, plus a live `perf` profile with Python frames (Python 3.14
`sys.remote_exec` into the running app to call
`sys.activate_stack_trampoline('perf')`, record, then deactivate).

## 6. Risks

* **Visual drift.** GPU shapes are anti-aliased, Pillow's are not; blending
  follows standard alpha. Expected: slightly cleaner edges. Pillow stays one
  flag away while we compare.
* **Two GL contexts.** Every GL call for the console runs on the main
  thread with the console's context current, and the previous context is
  restored after, exactly as `SecondaryGLWindow.present()` does today.
* **Proxy surface.** Some engine calls return values the caller uses
  immediately. Each one is either served from the state mirror or
  restructured; none may block on the audio process.
* **Windows.** `spawn` is Windows' default already; shared memory and the
  raw-GL binding both work there. Checked per phase, not assumed.
