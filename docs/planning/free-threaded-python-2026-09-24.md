# Free-threaded Python (no-GIL) — findings and starting point

Owner: free-threading team (new, 2026-09-24)
Status: Research handoff — nothing ported yet
Last updated: 2026-09-24

This doc hands the free-threaded Python work to the team taking it on. It
records a discussion with the owner on 2026-09-22 and a dependency check
redone on 2026-09-24. Everything marked *verified* was checked against
PyPI, upstream source or the CPython docs on those dates. Everything
marked *not yet read* is still open.

## 1. The five facts to know on day one

1. **One unready compiled module turns the GIL back on for the whole
   process.** The CPython docs: *"The GIL may also automatically be enabled
   when importing a C-API extension module that is not explicitly marked as
   supporting free threading. A warning will be printed in this case."*
   It prints one warning and carries on as an ordinary GIL build. The app
   still runs, still works, and gets no parallelism. A team could believe
   it is on free-threaded Python for months without noticing. **Guard
   against this first** (see §6).
2. **`moderngl` is imported unconditionally at startup** (`unicornviz/app.py`),
   so the main process can never be GIL-free until moderngl, and the
   `glcontext` module it loads, declare support. Getting Pillow and rtmidi
   ready is not enough on its own. The rest will not "go in naturally".
3. **OpenGL is single-threaded no matter what Python does.** A GL context
   can be current on only one thread at a time. That is a driver rule, not
   a GIL rule. A fully free-threading-safe moderngl still would not let two
   threads issue GL calls in parallel. What it buys is that the audio,
   MIDI, analysis and Control Room drawing threads stop losing time to
   whatever GL call is running.
4. **`PYTHON_GIL=0` / `-X gil=0` is not a fix.** It keeps the GIL off
   after an unmarked import. That just removes the safety net: the
   unmarked module's C/C++ internals then run under real concurrent access
   that nobody has audited. The failure mode is silent memory corruption,
   not a clean crash.
5. **It costs something.** The docs put single-thread overhead at *"about
   1% on macOS aarch64 to 8% on x86-64 Linux"* (pyperformance average).
   Memory use is typically higher. Linux x86-64 is our main platform and
   gets the high end of that range.

## 2. Background: what was already done, and why

The trigger was a request to get the Control Room's UI drawing "off the
shared GIL thread" (2026-09-22).

- The Control Room has drawn its UI (PIL) on its own `ControlRoomRender`
  thread since May. A thread doesn't escape the GIL, though: its
  Python-level drawing still takes time slices from the GL and audio
  threads.
- **A separate process was considered and deferred.** Each panel's
  `content()` is collected in the same pass as the pixels are drawn, and
  collecting it needs live objects in the main process (mixer engine,
  webcam, audio manager and roughly 15 panel-owning drop-ins). Splitting
  that means a data model passed to a worker, pixels and hotspots passed
  back, fonts loaded twice, a frame of extra latency, and `spawn` rather
  than `fork` (the app is already multi-threaded when the Control Room
  starts, and forking a multi-threaded process is a known hazard). That is
  a real rewrite.
- **What shipped instead (owner's pick: "cache the panel faces & skip
  static redraws, then profile & decide"):** control-room-01 0.20.0.
  Panels whose content hasn't changed reuse a cached image, and pages
  other than MAIN skip whole frames when nothing on them changed. Measured
  on an 8-panel page: about 450x fewer draw calls when idle, about 4.4x
  with the mouse moving. It builds on the mixer's
  `sys.setswitchinterval(0.001)` change in dj-mixer-01 0.214.3.
- The owner then asked whether a differently compiled Python would give
  real parallelism. That question is this doc.

## 3. Status of free-threaded CPython

- The no-GIL build was added by PEP 703 (experimental in 3.13) and became
  **officially supported in 3.14** (PEP 779). It is still a separate
  build, not the default. Python reports it as `python -VV` / `sys.version`
  containing "free-threading build", or
  `sysconfig.get_config_var("Py_GIL_DISABLED") == 1`.
- Wheels built for it carry a `t` ABI tag (`cp314t`). **The free-threaded
  build does not support the Limited C API or the stable ABI** (docs,
  verified), so `abi3` wheels can't be used and need a real `cp314t` build.
- This machine runs Python 3.14.6 (normal GIL build). **No free-threaded
  interpreter is installed yet.**

## 4. Dependency audit (verified 2026-09-24)

"Loaded" = when the app imports it. Anything loaded at startup must be
ready, or the GIL comes back on every launch.

### Ready today (official `cp314t` wheels)

| Package | Installed | Loaded | Notes |
|---|---|---|---|
| numpy | 2.4.4 | startup | `cp313t` + `cp314t` wheels |
| scipy | 1.17.1 | startup | `cp313t` + `cp314t` wheels |
| Pillow | 12.3.0 | startup | `cp314t` + `cp315t` wheels. Earlier mistake: it was once flagged as needing a rebuild; it doesn't |
| psutil | 7.2.2 | startup | `cp313t` + `cp314t` wheels |
| cffi | 2.0.0 | startup (via sounddevice, soundfile) | `cp314t` wheel. **The original discussion missed this**: sounddevice and soundfile are pure Python, but they sit on cffi's compiled backend, so cffi being ready is what actually matters |
| av (PyAV) | 18.0.0 (18.1.0 latest) | on demand (dj-mixer-01 decks, media-01, videos-01) | `cp314t` wheel |
| PySDL2, sounddevice, soundfile, python-osc | — | startup | Pure Python (ctypes or cffi); nothing of their own to port |

### Blockers

| Package | Installed (latest) | Loaded | Status |
|---|---|---|---|
| **moderngl** | 5.12.0 (5.12.0, last upload 2024-10-17) | **startup, always** | No wheel past cp313 at all. The copy here was compiled from source just to run on normal 3.14. About 424 KB of hand-written C++ (GitHub language stats) and no Cython, so there's no one-line opt-in: needs the `Py_mod_gil` slot (or `PyUnstable_Module_SetGIL`) in its module init plus an audit for shared mutable state. **Source not yet read.** |
| **glcontext** | 3.0.0 (3.0.0, 2024-08-10) | startup (moderngl uses it for context creation) | No wheel past cp313, no `t` build. **Missed in the original discussion**, and it moves with moderngl. Not yet read |
| **python-rtmidi** | 1.5.8 (1.5.8, 2023-11-20) | startup (`unicornviz/midi.py`, guarded) + dj-mixer-01 LED modules | No official wheel past cp312. Unofficial 3.14t wheels exist ([paperisiili/python-rtmidi-wheels](https://github.com/paperisiili/python-rtmidi-wheels)) but *"importing python-rtmidi re-enables the GIL for that process"* |
| **opencv-python-headless** | 4.13.0.92 (5.0.0.93) | loads with webcam-01 (guarded import at module top) | Ships only `cp37-abi3`, which the free-threaded build can't load. Upstream discussion open ([opencv-python#1029](https://github.com/opencv/opencv-python/issues/1029)) |
| **mediapipe** | 1.0.0 | **loads with webcam-01** (guarded import at module top, even if segmentation is never turned on) | Compiled code shipped under a `py3-none` wheel tag; no free-threading declaration. Large upstream C++/Bazel project, not realistic to port ourselves. **Missed in the original discussion** |
| usd-core (`pxr`) | 26.5 (26.8) | on demand (sims-01 `usd_scene.py`) | `cp314-none` wheels, no `t` build |
| essentia | 2.1b6 | training-kit tools only (offline) | No `t` build. Not in the app's runtime path |

Also compiled but outside the app's runtime (LLM SDK deps, tooling):
pydantic_core, jiter, msgpack, yaml, tomli/charset_normalizer (mypyc),
matplotlib/kiwisolver/contourpy. Worth a sweep, not a blocker.

**Bottom line:** for the main app process, moderngl + glcontext are
mandatory. rtmidi is next, since `midi.py` loads it at startup. Then
webcam-01's two startup imports (cv2, mediapipe), which would need to
become lazy or move out of process.

## 5. Per-package notes from the discussion

### Pillow — keep it

Pillow does all the CPU-side 2D drawing: `ImageDraw` shapes and text,
alpha compositing, PNG encode/decode. It's used in 31 files (the Control
Room UI, the mixer's `ui.py`, banner/CTA overlays, fonts, splash, texture
showcases). It is already ready. Switching to something like pycairo or
skia-python might draw faster at scale, but would mean rewriting every
`ImageDraw` call across 31 files for zero unblocking benefit.

### python-rtmidi — the tractable one, recommended first

- Cython + C++ wrapping RtMidi. The whole extension is
  `src/_rtmidi.pyx`, 1,105 lines (upstream
  [SpotlightKid/python-rtmidi](https://github.com/SpotlightKid/python-rtmidi)).
- Cython 3.1+ has the opt-in built in: the directive
  `# cython: freethreading_compatible = True` (the file already has
  module-level directives). The missing directive is exactly why the
  unofficial 3.14t wheels still re-enable the GIL.
- Module-level state sampled so far is immutable integer constants (API
  and error-type enums). **The full file has not been read line by line**,
  so the callback and handle-registration code is still unaudited. Also
  note that Cython's guide labels its free-threading support experimental:
  the directive declares compatibility, it doesn't make the extension's
  code thread-safe.
- Our own MIDI code already treats the RtMidi callback as a foreign
  thread and only hands data over via a queue or lock (CLAUDE.md MIDI
  conventions), which narrows the risk for this app's usage specifically.
- A local fork needs no upstream PR. Precedent: the APC LED fix went
  around a broken kernel path with a direct libusb write rather than
  waiting on upstream.
- Proposed first task (from 2026-09-22): read the whole `.pyx`, add the
  directive, build against a free-threaded interpreter, run upstream's
  test suite, then do a hardware smoke test with the APC mini and DDJ-REV1.

### moderngl (+ glcontext) — the big one

- Every GL call goes through it: contexts, programs, buffers, textures,
  framebuffers.
- There's no Cython shortcut: add the `Py_mod_gil` slot (multi-phase
  init) or `PyUnstable_Module_SetGIL(m, Py_MOD_GIL_NOT_USED)` (single-phase
  init), then audit the C++ for static or global mutable state.
- **Nobody has read the source yet.** Don't commit to a timeline before
  someone has.
- Upstream activity looks thin (last release 2024-10), so plan on
  maintaining a fork.

## 6. How to scope the work (options from 2026-09-22)

1. **Port moderngl + glcontext too**, not just rtmidi. The complete,
   correct path, and the biggest piece of work.
2. **Force `PYTHON_GIL=0` and accept the audit risk** on moderngl's C++.
   Only reasonable after someone has read enough of it to have an opinion
   on whether it's safe. Not a default.
3. **Run a separate free-threaded process that never imports moderngl.**
   The numpy/scipy-heavy audio and analysis work is ready today, so real
   parallelism there is reachable soon without touching GL, as long as it
   lives in its own process apart from the renderer.

Whichever way it goes, suggested first steps:

- **Build the guard before anything else.** Run a free-threaded 3.14
  interpreter, import the full app the way startup does, and assert
  `sys._is_gil_enabled()` is `False`. On failure, report which module was
  imported last. Without this check, a silent fallback is invisible
  (fact 1).
- **Map imports per process.** List what each process imports at startup
  vs on demand (§4's "Loaded" column is a start). A drop-in's guarded
  top-level import still counts at startup when that drop-in loads.
- **Audit our own threaded code.** Several places lean on
  "main thread writes, render thread reads, a one-frame-stale read is
  fine". Built-in containers stay internally safe without the GIL, but any
  check-then-act across threads needs a second look.
- **Keep Windows in view.** Linux comes first (owner's platform), but most
  end users are on Windows, and any forked extension needs Windows builds
  too.

## 7. Open questions

- How big is moderngl's and glcontext's shared-state audit, really? (Needs
  a source read.)
- Is the rest of rtmidi's callback and registration code safe? (Needs the
  full `.pyx` read.)
- webcam-01: make cv2 and MediaPipe imports lazy (only when the webcam is
  shown / segmentation enabled), or move segmentation into its own
  process? Right now just loading the drop-in re-enables the GIL.
- Does OpenCV build from source for `cp314t` without the stable ABI?
- Measure first: how much does the app actually gain? Profiling the
  running app (see the 2026-09-24 perf pass) should come before and after
  any port.

## Sources

- [Python support for free threading (CPython docs)](https://docs.python.org/3/howto/free-threading-python.html)
- [C API extension support for free threading (CPython docs)](https://docs.python.org/3/howto/free-threading-extensions.html)
- [PEP 779 — supported status for free-threaded Python](https://peps.python.org/pep-0779/)
- [Python Free-Threading Guide](https://py-free-threading.github.io/) — [porting extensions](https://py-free-threading.github.io/porting-extensions/), [running with the GIL disabled](https://py-free-threading.github.io/running-gil-disabled/), [compatibility tracking](https://py-free-threading.github.io/tracking/)
- [Cython free-threading guide](https://cython.readthedocs.io/en/latest/src/userguide/freethreading.html)
- [python-rtmidi upstream](https://github.com/SpotlightKid/python-rtmidi) and [unofficial 3.14t wheels](https://github.com/paperisiili/python-rtmidi-wheels)
- [opencv-python free-threading discussion](https://github.com/opencv/opencv-python/issues/1029)
- PyPI JSON API (`https://pypi.org/pypi/<name>/<version>/json`), queried 2026-09-22 and 2026-09-24 for the wheel tags above
