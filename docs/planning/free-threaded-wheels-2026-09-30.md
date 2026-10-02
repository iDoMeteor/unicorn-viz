# Free-threaded (cp314t) wheels: moderngl, glcontext, python-rtmidi

Owner: UV Threads
Status: all five Linux and all five Windows wheels built, verified and published.
With the patched Linux wheels (2026-10-02; section 6a), nothing UV imports turns the GIL
back on any more: rtmidi, glcontext, moderngl, sphn, cv2 and MediaPipe all keep it off.
The upstream PRs are open (section 6a). Patched Windows wheels are published too.
Last updated: 2026-10-02

W1 of [the bug remediation plan](bug-remediation-plan-2026-09-30.md) bundles
free-threaded Python 3.14. Three extensions we depend on have no wheel for it
upstream (moderngl and glcontext have none for 3.14 at all, and PyPI shows no
cp314/cp313t wheel for any of the three as of today), so we build our own.

## 1. What exists

*Update 2026-10-02:* patched, free-threading wheels of all five packages now sit
alongside these, for Linux and Windows, with build tags that pip prefers. They are
described in section 6a, and their provenance is in section 7. The table below is the
original 2026-09-30 set.

Published to `~/projects/_software-dist/wheelhouse/cp314t/` (flat,
append-only, `SHA256SUMS` beside it):

| Package | Source | Wheel |
|---|---|---|
| glcontext 3.0.0 | PyPI sdist | `…cp314-cp314t-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl` |
| moderngl 5.12.0 | PyPI sdist | `…cp314-cp314t-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl` |
| python-rtmidi 1.5.8 | PyPI sdist | `python_rtmidi-1.5.8-1-cp314-cp314t-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl` |

The rtmidi wheel carries the PEP 427 build tag `-1-`: a first build used the
C++ pre-generated in the sdist (Cython 3.0.5, which predates free-threading
support), and the wheelhouse never deletes anything, so the rebuild from
Cython 3.3.0 is a distinct file that pip prefers. The superseded file stays.
Compound tags in the filenames are normal; auditwheel lists every manylinux
tag a wheel qualifies for.

| opencv-python-headless 4.13.0.92 | git tag `92` of opencv/opencv-python (no PyPI sdist exists for this version) | `opencv_python_headless-4.13.0.92-cp314-cp314t-manylinux_2_28_x86_64.whl` |
| sphn 0.2.1 | PyPI sdist | `sphn-0.2.1-cp314-cp314t-manylinux_2_28_x86_64.whl` |

Runtime pin, agreed with UV Install: python-build-standalone release
**20260929**, CPython **3.14.7**, `freethreaded-install_only` (Linux asset
sha256 `730c33d387c937bea8995d69d4bc20a24084844120c7d56ed5e0b6f4bfc92641`).
Windows has the same release and variant.

## 2. How they are built

`tools/packaging/build_ft_wheels.sh` (pins, hashes and the whole recipe live
there; `tests/test_ft_wheels_build.py` keeps its versions in step with
`requirements.txt`):

1. A throwaway rootless **podman** container of `quay.io/pypa/manylinux_2_28_x86_64`
   (glibc 2.28, GCC 14, free-threaded CPython 3.14.7 at `/opt/python/cp314-cp314t`).
   Storage is private under the work directory. No sudo, nothing installed on
   the host.
2. Each pinned sdist is fetched and its sha256 checked, then built with
   `--no-build-isolation` in a venv with the build tools (Cython 3.3.0 for
   rtmidi, whose pre-generated C++ is deleted so meson regenerates it).
3. `auditwheel repair --plat manylinux_2_28_x86_64`. The rtmidi wheel vendors
   `libasound`, as upstream's wheels do. moderngl and glcontext need nothing:
   they `dlopen` GL/EGL/X11 at runtime.
4. `--verify-python <interpreter>` installs the result into a scratch venv of
   the bundled PBS interpreter and runs `tools/packaging/ft_wheels_smoke.py`.

The wheels carry the cp314t ABI tag, so the manylinux container's interpreter
and the PBS interpreter are interchangeable for this purpose. That is checked,
not assumed: the smoke test runs on PBS.

Smoke test results (Intel Iris Xe, Mesa 26.1.4): all three import; a standalone
EGL context renders and reads back the expected pixel; rtmidi (ALSA backend)
lists its ports, including the DDJ-REV1.

Two build notes. PBS's recorded build configuration names `clang++`, which a
normal machine lacks, so compiling directly against a PBS interpreter needs
`CC=gcc CXX=g++ LDSHARED="g++ -shared"`; the container route avoids that.
And the shared dev `.venv` is untouched.

### 2b. OpenCV (`build_ft_opencv_wheel.sh`)

PyPI ships opencv-python-headless only as a `cp37-abi3` wheel (OpenCV hard-codes
`-DPYTHON3_LIMITED_API=ON`; the stable ABI does not exist on free-threaded
builds), and has no sdist for the version `requirements.txt` pins. The recipe
builds the matching git tag by commit (`4ddfc013…`, OpenCV submodule `b4c5ec40`
= 4.13.0), removes the limited-API flag from `setup.py`, and builds against
numpy 2.3.2 (oldest release with cp314t wheels; upstream's own pin for 3.14).

Because `video-clips-01` decodes video files through `cv2.VideoCapture`, the
wheel must carry an FFmpeg. `ft-opencv/Containerfile` builds FFmpeg 8.0.1 and
libvpx 1.15.2 (both pinned by hash or commit) into a cached image first.

**License of the bundled FFmpeg: plain LGPL 2.1+.** No `--enable-gpl`,
`--enable-nonfree` or `--enable-version3`, so no libx264 or other GPL codecs.
Upstream's recipe also passes `--enable-openssl`; it is omitted because it only
adds `https://` and its license compatibility depends on the OpenSSL version.
Vendored into the wheel: libavcodec, libavformat, libavutil, libswscale,
libswresample (LGPL), libdrm (MIT), libvpx (BSD). `ft_opencv_smoke.py` asks the
bundled libraries (`avutil_license()` and friends) and asserts no GPL or
non-free library is present; a test pins the configure flags.

Intentional differences from upstream's wheel: no Qt (headless), contrib, AVIF,
LAPACK or https. None is used by this project.

Verified on the PBS runtime: full-API (not limited-API) build; headless; FFmpeg
and V4L2 backends present (a camera opens through V4L2); decodes real H.264
`.mp4` and VP9 `.webm`, including seek-by-frame-index (what `video-clips-01`
does on loop); four threads decoding at once; the image operations
`webcam-01` uses. Importing cv2 re-enables the GIL.

On Windows, OpenCV's own CMake downloads its prebuilt FFmpeg plugin DLL
(`opencv_videoio_ffmpeg*_64.dll`, hash-pinned), which OpenCV documents as an
LGPL build with no GPL components; nothing is built for FFmpeg there.

### 2c. sphn (`build_ft_sphn_wheel.sh`)

sphn 0.2.1 (audio read/write; Rust, pyo3 0.27, maturin) has cp314 wheels but no
cp314t, and demucs (the mixer's stem separation) depends on it. No source change
is needed: pyo3 supports free-threaded builds. The recipe builds the PyPI sdist
with `maturin build --locked` in `ft-sphn/Containerfile` (manylinux_2_28 + Rust
1.98.1 + maturin 1.15.0, installer pinned by hash). Two environment workarounds
are recorded in the script: `CMAKE_POLICY_VERSION_MINIMUM=3.5` (CMake 4 refuses
the bundled libopus's old minimum), and a one-line `CMAKE_TOOLCHAIN_FILE` that
pins the install dir to `lib` (this image uses `lib64`, which the opus crate
does not search).

Verified: WAV write/read round trip, `durations`, `resample`, and
`demucs 4.1.0` imports in a venv with the CPU-only torch cp314t wheel.
`sphn.resample` pads its output to a chunk multiple (49152 samples for 24,000 in
at 2x), identically in upstream's cp314 wheel. The module does not declare
`gil_used = false`, so importing it re-enables the GIL.

## 3. GIL behavior

A free-threaded interpreter starts with the GIL **off** and turns it **on**
the first time it imports an extension module that has not declared it can
run without one (`Py_mod_gil`). Each module was imported alone in a fresh process
on the PBS 3.14.7t runtime:

| Import | Published wheels (2026-09-30) | Patched Linux wheels (2026-10-02) |
|---|---|---|
| `glcontext` (package only; loads no extension) | off | off |
| `glcontext.egl`, `glcontext.x11` | **on** | off (`glcontext-3.0.0-2`) |
| `moderngl` (`moderngl.mgl`) | **on** | off (`moderngl-5.12.0-2`) |
| `rtmidi` (`_rtmidi`) | **on** | off (`python_rtmidi-1.5.8-3`) |
| `cv2` (opencv, 4.13.0) | **on** | off (`opencv_python_headless-4.13.0.92-1`) |
| `sphn` | **on** | off (`sphn-0.2.1-1`) |
| `mediapipe` 1.0.0 (Tasks API; ctypes, no CPython extension) | off | off (unchanged; its numpy, Pillow, matplotlib, kiwisolver and cffi dependencies are free-threading ready) |

**With the published wheels**, any process that imports moderngl or rtmidi runs with
the GIL on. That was the expected state for the main process (plan decision 1), and
it must never happen in the audio helper, which imports none of them.

**With the patched Linux wheels**, the whole main process can run with the GIL off.
MediaPipe was tested the way `webcam-01` uses it (one IMAGE-mode `ImageSegmenter` per
camera worker thread, never closed): masks are bit-identical with the GIL off and on,
and stress tests of that pattern are clean. MediaPipe's Python layer has two crash
bugs, a `close()` racing an in-flight call and a double `close()`. Both exist with the
GIL too, and UV's pattern never triggers them. A fix is prepared upstream-side, on the
`free-threading` branch in `~/Repos/python-free-threading/mediapipe`, submitted as
[google-ai-edge/mediapipe#6374](https://github.com/google-ai-edge/mediapipe/pull/6374)
(it needs a signed Google CLA). The findings are in
`~/Repos/python-free-threading/reports/mediapipe/`. If `webcam-01`
ever starts calling `close()`, stop and join the worker first.

### The startup check (for UV Core)

Python reports the flip itself, with the module name, as a `RuntimeWarning`
("The global interpreter lock (GIL) has been enabled to load module 'X'…").
Suggested guard:

- Wrap the startup imports in `warnings.catch_warnings(record=True)` with an
  `"always"` filter, and keep the `RuntimeWarning`s whose text mentions the GIL.
- Log once, after startup: `sys._is_gil_enabled()` plus the module names from
  those warnings.
- **Audio helper:** log at WARNING if the GIL is on, naming the module. That
  process is where free-threading is supposed to pay off, so a silent fallback
  must not happen.
- **Main process:** with the published wheels, INFO only, listing the known set
  above (`moderngl.mgl`, `glcontext.*`, `rtmidi._rtmidi`, plus `cv2` and `sphn`
  once the webcam or the mixer loads them). With the patched wheels the known set
  is empty, so any GIL flip is worth a WARNING that names the module.
- Guard `sys._is_gil_enabled` with `getattr`: it does not exist before 3.13.

`ft_wheels_smoke.py` implements the same per-module probe and is a reference.

## 4. Windows wheels: options

**Decision (2026-09-30, the owner, relayed by the coordinator):** build them on
GitHub Actions (option 1), with a Windows Python 3.13 GIL build as the interim
fallback. The script is `tools/packaging/build_windows_ft_wheels.py` (section 6);
the options below are kept for the reasoning.

Nothing is built for Windows yet, and no CI is created without owner
approval (workflows are an infrastructure change). All three packages are
plain C or C++; none needs more than MSVC and the PBS Windows interpreter's
headers and import library. Wheel contents would be `win_amd64`, cp314t.
Whatever is chosen, they land in the same wheelhouse.

| # | Option | Reproducible | Needs | Risk / cost |
|---|---|---|---|---|
| 1 | **GitHub Actions `windows-2022` job** (cibuildwheel or a plain MSVC build) publishing the wheels | Yes, fully | Owner approval for a workflow; a place to run it; artifact download step into the wheelhouse | Lowest long-term effort; the only option that rebuilds itself on a version bump. Blocked on the approval. |
| 2 | **Build by hand on the owner's Windows machine** with Visual Studio Build Tools ("Desktop development with C++") and the PBS Windows 3.14t, using a checked-in `build_ft_wheels.ps1` | As reproducible as the script and pinned tool versions | Owner's time (one setup, then a run per version bump) | Quickest to a real result; needs a Windows box for every rebuild. I can write and dry-run the script here, and the owner runs it once. |
| 3 | **Cross-compile on this Linux box with clang-cl + xwin** (MSVC CRT and SDK fetched by xwin) | Yes, once scripted | Microsoft SDK license acceptance; a Windows `python314t.lib` | setuptools cannot cross-build natively, so the compile and link steps would be hand-driven; rtmidi's meson build needs a cross file. Unproven for these three; the highest build effort. |
| 4 | **Wine + msvc-wine** (the MSVC toolchain installed under Wine) and the PBS Windows interpreter run under Wine, then an ordinary setuptools/meson build | Yes, once scripted | Microsoft license acceptance; Wine | Native build tools, so no hand-driven compile steps; unproven here, and Wine plus 3.14t is an extra unknown. |
| 5 | A Windows VM on this box | Yes | A Windows license and ISO; disk and setup time | Heavy for three small extensions. Not recommended. |

Recommendation: **option 2 now**, because it is the least infrastructure and
gets real wheels soonest, with the script committed so the run is repeatable;
move to **option 1** if the owner wants rebuilds to happen without a Windows
machine, since that is a separate approval. If the owner has no Windows
machine to spare, I would spike **option 4** on this box (all under
`/var/tmp`, nothing outside it) before attempting 3.

## 5. What real `Py_mod_gil` support would take (assessment only)

Declaring a module free-threading safe is a one-line promise. The work is
making the promise true. In all three the thread-safety question is mostly one
of use: our GL work happens on a single render thread and MIDI callbacks
arrive on RtMidi's own thread, so most of what follows is hardening, not a
redesign.

### python-rtmidi: tractable, and tested

**Update 2026-10-01: done, and open upstream; see section 6a.** The original
assessment follows; it underestimated the work, because the audit found
lifetime bugs that predate free-threading.

Cython 3.1 and later has a directive: `# cython: freethreading_compatible = True`
at the top of `_rtmidi.pyx`. Experiment (scratch build in `/var/tmp`, not
shipped): regenerating with Cython 3.3.0 and that directive makes
`import rtmidi` leave the GIL **off**. Without the directive the regenerated
module still turns it on. A stress run with the GIL off (six threads sending
through separate output ports to a virtual input with a callback, plus three
threads enumerating ports) finished repeatedly with no crash, hang or abort.
Message counts matched the GIL-on build's order of magnitude. Both overrun
ALSA's queue at that send rate, so this shows robustness, not proof of thread
safety.

What remains before shipping it: read the callback path (`with gil`
trampolines at `_rtmidi.pyx` lines ~173-215) and per-object state in
`MidiBase`/`MidiIn`/`MidiOut` (`_port`, `_callback`, `_error_callback`,
`_deleted`) for check-then-act races,
add a lock where one object can be reached by two threads, and decide the
supported rule (an instance is used by one thread at a time is the normal
one). Estimate: about a day including tests. Upstream-able as a small PR.

### glcontext: small

**Update 2026-10-01: done, and open upstream; see section 6a.** Correction: the package
builds seven single-phase modules, not two: `egl`, `x11`, `headless` and
`windowed` on Linux, plus `wgl` (Windows), `darwin` (macOS) and `empty`. All
need the declaration.

Two single-phase C++ modules, `egl.cpp` (406 lines) and `x11.cpp` (519), each
created with `PyModule_Create`; no `Py_BEGIN_ALLOW_THREADS`. Declaring support
means calling `PyUnstable_Module_SetGIL(module, Py_MOD_GIL_NOT_USED)` in each
init (or moving to multi-phase init with the slot). The state is per context
object (display, window and context handles, dlopen'd function pointers).
GL contexts are bound to a thread by the driver whatever Python does, so the
rule is the existing one: a context is used from one thread. Estimate: half a
day, mostly reading both files for shared handles and adding a note.

### moderngl: the real work

9,509 lines of C++ plus 2,591 of GL method tables, single-phase init
(`PyModule_Create`, `PyType_FromSpec` for 13 types). It never releases the GIL
around GL calls, which means today every call is serialized by the GIL.
Without it:

- **Module globals (safe):** 13 static pointers (types, `helper`,
  `moderngl_error`) written once at init. Nothing else at file scope is
  mutable except constant lookup tables.
- **Per-object state (the audit):** `MGLContext` caches GL state in plain
  fields (`bound_framebuffer`, `enable_flags`, cull, blend and depth
  settings, the default texture unit), and every GL object carries a
  `released` flag. Two threads touching one context race on that cache, and
  `release()` racing with use can double-delete a GL object.
- **Borrowed references (about 60 sites):** 51 `PyTuple_GetItem`, 7
  `PyTuple_GET_ITEM`, 2 `PyDict_GetItem`, 1 `PyList_GET_ITEM` (on a
  user-supplied list at ~line 7033). Tuples are immutable, so most are fine;
  the list and dict reads need the `…Ref` variants or a critical section.
- **Policy:** the honest contract is "a context and everything created from it
  belong to one thread", which is also what OpenGL itself requires. Enforcing
  it cheaply (a per-context owner-thread check, or `Py_BEGIN_CRITICAL_SECTION`
  on the context in entry points) turns a silent race into a clear error.

Estimate: two to four days for the mechanical audit, the critical sections or
owner-thread check, and stress tests, plus the review time. The payoff for us
is narrower than it looks: moderngl being GIL-safe only stops it from
re-enabling the GIL. The main process also loads other extensions with no
free-threaded story today (OpenCV for the webcam, MediaPipe), so removing the
GIL from the main process needs all of them, not just this one. The near-term
win remains the audio helper, which already runs GIL-free and imports none of
these.

*Update 2026-10-02:* this is done. With the patched wheels, OpenCV is fixed too, and
MediaPipe turned out never to flip the GIL, so the main process can run GIL-free
(section 3).

Suggested order, if and when this is taken on: rtmidi first (cheap, testable,
removes one of the four flips), then glcontext, then moderngl as its own
project.

## 6. Where we are (updated 2026-10-01)

**Done and published, `~/projects/_software-dist/wheelhouse/cp314t/`** (append-only,
`SHA256SUMS`): all five wheels for Linux x86-64 (manylinux_2_28) **and** for Windows
x86-64 (`win_amd64`): moderngl, glcontext, python-rtmidi (build tag `-1`),
opencv-python-headless 4.13.0.92 and sphn 0.2.1, each verified against the
python-build-standalone 20260929 / 3.14.7 free-threaded runtime.

**Windows** is built by GitHub Actions (`windows-ft-wheels.yml`, owned by the
installer team) running `tools/packaging/build_windows_ft_wheels.py`. Getting there
took four real fixes, each found from the per-step logs the script writes to
`work/<step>.log`: commands resolved on the build environment's PATH (not the
parent's, which is what Windows subprocess uses); environment names merged
case-insensitively (vcvars reports `Path`, Python `PATH`); `Py_GIL_DISABLED`
defined for OpenCV (setuptools defines it, OpenCV's CMake does not; without it the
module links the wrong library and would use the wrong object layout); and the
OpenCV smoke test's own fixtures. The OpenCV smoke test decodes the checked-in H.264
and VP9 clips (`tools/packaging/ft-fixtures/`) on both platforms. Still not covered
on a Windows runner: the GL render check (no GPU on the runner), which a run of
`ft_wheels_smoke.py` on a Windows machine with a GPU would close.

**Licensing.** Per-wheel facts are in section 7 (Linux) and section 8 (Windows). Notices
for redistribution live in `docs/third-party/`: the sphn crates, libdrm (Linux OpenCV
wheel), and OpenCV's Windows FFmpeg plugin. UV Install owns the releases.

**The `Py_mod_gil` ports** (section 5) are under way, as upstream pull requests:
rtmidi first, then glcontext, then moderngl. Progress is in section 6a.

## 6a. Upstream `Py_mod_gil` work (started 2026-10-01)

Done in the upstream projects, so the fixes reach everyone and our wheels can
eventually come from releases. The clones and working notes live in
`~/Repos/python-free-threading/`. The PRs come from the iDoMeteor GitHub account.

| PR | What | State (2026-10-01) |
|---|---|---|
| [SpotlightKid/python-rtmidi#230](https://github.com/SpotlightKid/python-rtmidi/pull/230) | Free-threaded support, plus lifetime and threading fixes | open; CI waiting for maintainer approval |
| [thestk/rtmidi#395](https://github.com/thestk/rtmidi/pull/395) | ALSA `closePort()` joins the wrong thread (hang) or never joins it (leak) | **merged** 2026-10-02 (retested by the maintainer) |
| [thestk/rtmidi#396](https://github.com/thestk/rtmidi/pull/396) | `cancelCallback()` races the input thread into a null call (crash) | **merged** 2026-10-02 (retested by the maintainer on five platforms) |
| [SpotlightKid/rtmidi#4](https://github.com/SpotlightKid/rtmidi/pull/4) | Both RtMidi fixes, backported to the branch python-rtmidi's submodule tracks | open |
| [moderngl/glcontext#41](https://github.com/moderngl/glcontext/pull/41) | Free-threaded support for all seven modules; `release()` safe to call twice (a second x11 `release()` segfaulted, with the GIL too) | open |
| [moderngl/moderngl#751](https://github.com/moderngl/moderngl/pull/751) | moderngl PR B: eight memory-safety fixes found in the audit (three crash the interpreter today) | open |
| [moderngl/moderngl#752](https://github.com/moderngl/moderngl/pull/752) | moderngl PR A: objects hold their context (and program, index buffer, scope members) until deallocated; fixes the use-after-free and leaks; framebuffer use on a released context raises instead of crashing | open |
| [kyutai-labs/sphn#23](https://github.com/kyutai-labs/sphn/pull/23) | sphn: `gil_used = false` (the audit found nothing the GIL protected) plus a cp314t CI wheel job | open |
| [moderngl/moderngl#754](https://github.com/moderngl/moderngl/pull/754), [glcontext#42](https://github.com/moderngl/glcontext/pull/42), [python-rtmidi#231](https://github.com/SpotlightKid/python-rtmidi/pull/231) | Small fixes found in the audits (2026-10-02): moderngl attribute deletion segfaults and bad-argument handling; glcontext `load()` segfault, contexts leaked on GC (x11 runs out of X clients after about 255), X error handler restore; a python-rtmidi docstring. In the round-2 wheels. #754 later also gained fixes for >64 varyings, unchecked helper results and `ctx.gc()` on released objects. | open |
| [moderngl/moderngl#753](https://github.com/moderngl/moderngl/pull/753) | moderngl PR C: free-threaded support. All 232 entry points lock their context; the guard costs about 5–12 ns per call on 3.14t and nothing on GIL builds. Stacked on #752. | open |
| [moderngl/moderngl#756](https://github.com/moderngl/moderngl/pull/756) | Leaks: external objects never freed, GL query objects never deleted (adds `Query.release()`), and error paths, including about 670 loader ints per context. Stacked on #752. | open |
| [moderngl/moderngl#755](https://github.com/moderngl/moderngl/pull/755), [glcontext#44](https://github.com/moderngl/glcontext/pull/44) | CI: free-threaded test job / build check on 3.13t and 3.14t, and cp313t/cp314t release wheels. The GIL-off assertions follow once #753 / #41 merge. | open |
| [moderngl/glcontext#43](https://github.com/moderngl/glcontext/issues/43) (issue) | `headless`, `windowed` and `empty` are never built: dead code, or meant to be built? | open |
| [google-ai-edge/mediapipe#6374](https://github.com/google-ai-edge/mediapipe/pull/6374) | Tasks Python: `close()` races (use-after-free, double free), `Image` lifetime and non-contiguous input, `ValueError` after `close()`. Needs a signed Google CLA. | open |
| [opencv/opencv#27933](https://github.com/opencv/opencv/issues/27933) (comments) | The binding-layer audit and patch, offered to the maintainers, who plan their own port; plus the Windows `Py_GIL_DISABLED` point. | discussion |

**What python-rtmidi#230 changes.** `import rtmidi` keeps the GIL off. Calls on one
`MidiIn`/`MidiOut` are serialized (a per-instance critical section), so sharing an
instance between threads stays safe. The input callback is read under a small lock,
so replacing it can't free it under the input thread. `delete()` while another
thread is in a call defers the free to that call. A second commit keeps reference
cycles through callbacks collectable: the GC clears them under the same lock. It needs
Cython 3.1 or newer.
Verified on free-threaded 3.14.7 (the python-build-standalone runtime) and regular
3.11, 3.12 and 3.14; Cython 3.1.0 works. An AddressSanitizer build is clean on the
race reproducers.

**Bugs in the wheel we ship today (python-rtmidi 1.5.8, all builds, GIL on or off).**
UV Core should know about these, because the main process imports rtmidi:

- **`MidiIn.close_port()` can hang forever under MIDI input.** It holds the GIL while
  RtMidi's ALSA backend joins the input thread, which may be waiting for the GIL to
  run a callback. Reproduced in seconds with a flooding sender; under gdb,
  `pthread_join` waits on one side and `PyGILState_Ensure` on the other. Fixed by #230.
  Until then, avoid closing an input port while a controller is sending. If it can't
  be avoided, close it on a worker thread, so that a hang there doesn't freeze the UI.
- **`del` never frees a `MidiIn`/`MidiOut`.** Since 1.4.1 the deallocator's guard is
  always false, so the ALSA client, its ports and the input thread outlive the object.
  If a callback was set, a later message calls through freed memory: a reproduced
  use-after-free. Fixed by #230. Until then, call `delete()` explicitly.
- **RtMidi's own races** (#395, #396), present in upstream RtMidi as well. Cancelling a
  callback while messages arrive can crash. Closing a port from a thread other than
  the one that created the `MidiIn` can, rarely, hang or leak a thread.

**What glcontext#41 changes.** The modules declare `Py_MOD_GIL_NOT_USED`. Context
methods are serialized per context, the x11 context create and release take a
process-wide lock (the X error handler is global), and contexts are zero-initialized.
Our render path only uses one context on one thread, so the practical gain is that
importing glcontext no longer turns the GIL on. moderngl still does until it is ported.
One finding for us: calling `release()` twice on an x11 context crashes the process in
the wheel we ship today.

**moderngl: audit (2026-10-01).** Unmodified moderngl builds on 3.14t and its whole
suite (360 tests) behaves the same as on 3.12 even with `PYTHON_GIL=0`. The one
failure, a uniform-ordering check, is Mesa 26.1 and happens on 3.12 too. Several
threads with one standalone context each render correctly. The hazards are in
*sharing* objects across threads:

- `Framebuffer.use()` swaps the context's bound framebuffer, an owning reference,
  without synchronization.
- `release()` is a non-atomic check-then-set: two threads releasing one object delete
  the GL name twice and underflow the refcount.
- Some objects drop their context reference on `release()`, others never drop it (a
  leak). `Sampler.release` reads the context after dropping itself (a use-after-free).

Section 5's estimate holds; the design:

- **Per-context serialization.** Every method of every object takes a critical section
  on its owning `Context`, through guard templates at the method tables, so the
  function bodies don't change. It is a no-op on GIL builds. One context per thread
  runs fully in parallel; one context shared by threads is serialized as the GIL did.
- **Prerequisite:** objects hold their context reference until deallocation.
- **Upstream split into three PRs:**
  - **A:** context reference lifetime, including the `Sampler` use-after-free.
  - **B:** small memory bugs found on the way: an out-of-bounds write in
    `set_color_mask`, unchecked buffer maps, and an unchecked cast in `transform()`.
  - **C:** free-threaded support, stacked on A.
- **Unchanged:** contention blocks rather than raising, and using a released object
  is not newly checked.
- **Documented:** `gc_mode="auto"` releases on whichever thread drops the last
  reference, so the cross-thread pattern is `context_gc`.

**Windows (published 2026-10-02).** The same five patched packages, as `win_amd64`:
`python_rtmidi-1.5.8-3`, `glcontext-3.0.0-2`, `moderngl-5.12.0-2`, `sphn-0.2.1-1` and
`opencv_python_headless-4.13.0.92-1`.

- **Build:** from the same sources as the Linux round-2 wheels, on GitHub Actions
  (`windows-2022`, MSVC 14.44) in the private repo `iDoMeteor/ft-wheels-ci`. Its script
  is adapted from `tools/packaging/build_windows_ft_wheels.py`, and the sources are
  pinned by commit to the `wheels/` branches on the iDoMeteor forks.
- **Verified on the runner:**
  - the GIL stays off after importing each module, and after importing all four
    non-OpenCV modules together in both orders;
  - the OpenCV H.264/VP9 fixtures decode, and the FFmpeg plugin's LGPL check passes;
  - sphn round-trips WAV.
- **Not verified on Windows:**
  - GL rendering (no GPU on the runner);
  - MIDI ports (none on the runner);
  - importing `cv2` together with the other four in one process.
- **Records:** build records are in `~/Repos/python-free-threading/wheels/windows/`.
- **Not needed:** the `windows-ft-wheels.yml` run against the backport branches
  (asked of UV Install above).

**Round 2 (published 2026-10-02, later the same day).** These carry the later fixes,
on top of everything round 1 has:

| Wheel | Adds |
|---|---|
| `python_rtmidi-1.5.8-3` | the `close_port` docstring fix (#231) |
| `glcontext-3.0.0-2` | #42: the `load()` segfault, native contexts leaked on GC (x11 ran out of X clients), X error handler restore, and cleanup after a failed `create_context` |
| `moderngl-5.12.0-2` | #754 (crashes on `del` attributes and with many varyings, unchecked helper results, the buffer-view unmap) and #756 (leaks: external objects, `Query.release()`, error paths, about 670 loader ints per context) |

- **Not rebuilt:** sphn stays at `-1`.
- **Platform tag:** the moderngl wheel's tag moved from manylinux_2_17 to
  manylinux_2_24. That's still fine for our manylinux_2_28 runtime.
- **Verification:** GIL off, both smoke scripts pass, and pip picks these. The
  manifest is `~/Repos/python-free-threading/wheels/patched-wheels-manifest-2.json`.

**For our wheelhouse (published 2026-10-02, Linux x86-64 only).** Patched cp314t wheels
are in `~/projects/_software-dist/wheelhouse/cp314t/` (append-only, `SHA256SUMS`
appended). Each keeps its pinned version, and a PEP 427 build tag makes pip prefer it:

| Wheel | Carries |
|---|---|
| `python_rtmidi-1.5.8-2-…manylinux_2_28_x86_64.whl` | python-rtmidi#230 backported to 1.5.8, plus the RtMidi fixes (#395, #396) |
| `glcontext-3.0.0-1-…manylinux_2_28_x86_64.whl` | glcontext#41 |
| `moderngl-5.12.0-1-…manylinux_2_28_x86_64.whl` | moderngl#751, #752 and #753 backported to 5.12.0, plus one commit reconciling #751 with #753 |
| `sphn-0.2.1-1-…manylinux_2_28_x86_64.whl` | sphn#23 |

With these four, the free-threaded runtime keeps the GIL off after importing `rtmidi`,
`glcontext.egl`, `glcontext.x11`, `moderngl` and `sphn`. That was checked with `-W
error::RuntimeWarning` on the PBS 3.14.7t runtime. `ft_wheels_smoke.py` and
`ft_sphn_smoke.py` pass, and the project test suites pass against the wheels.

- **Previously still turned the GIL on: `cv2` (fixed 2026-10-02).**
  `opencv_python_headless-4.13.0.92-1-…manylinux_2_28_x86_64.whl` is UV's recipe plus
  `~/Repos/python-free-threading/wheels/patches/opencv-4.13.0-free-threading.patch`:
  the GIL declaration, a mutex for `redirectError`, snapshots of caller dicts/lists
  (flann, dnn, the std::map converter, gapi) and locked dnn/highgui registries.
  - **Verified:** with all six patched wheels, `import cv2, rtmidi, glcontext.*,
    moderngl, sphn` keeps the GIL off; `ft_opencv_smoke.py` passes; the crash
    reproducers crash the published wheel and pass on this one.
  - **UV's cv2 usage** (webcam-01, video-clips-01) breaks none of the usage rules in
    `~/Repos/python-free-threading/reports/opencv/ASSESSMENT.md`.
  - **Upstream:** the findings and patch are offered on opencv/opencv#27933.
  - **MediaPipe (2026-10-02):** never turned the GIL on (no CPython extension), and
    works with the GIL off as UV uses it; see section 3.
- **Build provenance:** the build script and manifest (source commits, sha256, image
  digest) are in `~/Repos/python-free-threading/wheels/`. The backport branches
  (`ft-1.5.8`, `ft-5.12.0`) are local to those clones.
- **For UV Install:** `tools/packaging/wheelhouse-cp314t.sha256` and any pins in
  `test_ft_wheels_build.py` are not updated for the new wheels (Linux and Windows).

## 7. Provenance, for release notes

The wheels are redistributed (GitHub release asset, owner-approved), so each
one's source, build and license facts are recorded here to cite. Everything
below was checked against the recipes or the published wheels; the one item
that was not audited is called out.

Common to all Linux wheels: built by `tools/packaging/build_ft_wheels.sh`,
`build_ft_opencv_wheel.sh` or `build_ft_sphn_wheel.sh` in the manylinux_2_28
image (`quay.io/pypa/manylinux_2_28_x86_64`, GCC 14, glibc 2.28) with
free-threaded CPython 3.14.7, repaired with `auditwheel` to `manylinux_2_28`,
and smoke-tested on python-build-standalone 20260929 / 3.14.7 freethreaded
(`ft_wheels_smoke.py`, `ft_opencv_smoke.py`, `ft_sphn_smoke.py`).

| Wheel | Source (pinned) | License (from the wheel's own metadata) |
|---|---|---|
| glcontext 3.0.0 | PyPI sdist, sha256 `57168edc…c1ef` | MIT |
| moderngl 5.12.0 | PyPI sdist, sha256 `52936a98…5129b` | MIT |
| python-rtmidi 1.5.8 (`-1`) | PyPI sdist, sha256 `7f9ade68…04fa`; C++ regenerated from the `.pyx` with Cython 3.3.0 (the sdist's pre-generated file was deleted) | MIT (`LICENSE.md`); vendors `libasound` (LGPL 2.1) |
| opencv-python-headless 4.13.0.92 | git tag `92` of opencv/opencv-python, commit `4ddfc013fd1f13d9b9e379dbebf2cdbeb052e7f8`; OpenCV submodule commit `b4c5ec4042f097e2a5b386b9d413ec7333d0a184` (4.13.0). PyPI has no sdist for this version. | Apache-2.0; bundles FFmpeg (LGPL 2.1+), libvpx (BSD), libdrm (MIT) |
| sphn 0.2.1 | PyPI sdist, sha256 `3b19b1fe…c7fe`, built with `--locked` (the sdist's `Cargo.lock`: 135 crates) | MIT/Apache-2.0 per its `Cargo.toml` |

**Build flags worth quoting**

- opencv: `ENABLE_HEADLESS=1`; the hard-coded `-DPYTHON3_LIMITED_API=ON` removed
  from `setup.py` (the stable ABI cannot exist on a free-threaded build); built
  against numpy 2.3.2; no Qt, contrib, AVIF, LAPACK or https.
- sphn: Rust 1.98.1, maturin 1.15.0, `maturin build --release --locked`;
  `CMAKE_POLICY_VERSION_MINIMUM=3.5` and a toolchain file pinning
  `CMAKE_INSTALL_LIBDIR=lib` for the bundled libopus.

**FFmpeg inside the OpenCV Linux wheel (LGPL 2.1 or later).** FFmpeg 8.0.1,
tarball sha256 `ed1cfade43aab7711c88937a0afc15b7b22efdc528c6ff074b4027c55a3c175c`,
configured exactly as (from `ft-opencv/Containerfile`):

    ./configure --prefix=/ffmpeg_build \
        --extra-cflags=-I/ffmpeg_build/include --extra-ldflags=-L/ffmpeg_build/lib \
        --enable-libvpx --enable-shared --enable-pic \
        --disable-programs --disable-doc

No `--enable-gpl`, `--enable-nonfree` or `--enable-version3`; no libx264 or
OpenSSL. libvpx v1.15.2 (commit `d168454ecd099805c675d4a98c66f4891373302a`),
configured `--disable-examples --disable-unit-tests --enable-vp9-highbitdepth
--as=yasm --enable-pic --enable-shared`. The built libraries report their own
license (`avutil_license()`, `avcodec_license()`, `avformat_license()` all
return "LGPL version 2.1 or later"), and the smoke test asserts that.

**Windows OpenCV** does not build FFmpeg: OpenCV's CMake downloads its
documented-LGPL `opencv_videoio_ffmpeg*_64.dll` plugin, pinned by hash to
opencv_3rdparty commit `d82ad9a54a7b42a1648a9cae8fed5c2f20ea396c`; the license
text is `3rdparty/ffmpeg/license.txt` in the OpenCV tree.

**Gaps to close before the release notes are final**

- ~~The OpenCV wheel's own `LICENSE-3RD-PARTY.txt` does not mention libdrm.~~
  **Done 2026-10-01:** the vendored `libdrm-b0291a67.so.2.4.0` is libdrm
  2.4.115 (`libdrm-2.4.115-2.el8.x86_64`, matched by ELF build-id); its verbatim
  license headers are in
  [`docs/third-party/libdrm-2.4.115-NOTICE.txt`](../third-party/libdrm-2.4.115-NOTICE.txt).
- LGPL source availability: FFmpeg and libvpx sources are the pinned tarball
  and commit above (public, hash-verified). The note should say so.
- ~~sphn's statically linked Rust crates were not audited.~~ **Done 2026-10-01:**
  see "sphn license audit" below. The notice to attach to the release is
  [`docs/third-party/sphn-0.2.1-THIRD-PARTY-NOTICES.md`](../third-party/sphn-0.2.1-THIRD-PARTY-NOTICES.md).

### Patched wheels (2026-10-02)

Same packages, versions and licenses as above, rebuilt from patched sources. Every
change is ours, offered upstream under each project's own license (the PRs in section
6a). The vendored libraries are unchanged: libasound in the Linux rtmidi wheel; FFmpeg
8.0.1 (LGPL 2.1+), libvpx and libdrm in the Linux OpenCV wheel; the OpenCV FFmpeg
plugin DLL in the Windows OpenCV wheel. So the license facts above, and in section 8
for Windows, carry over.

| Wheel | Source (pinned by commit) | Changes vs. the original wheel |
|---|---|---|
| python-rtmidi 1.5.8 (`-3`) | `iDoMeteor/python-rtmidi` branch `wheels/ft-1.5.8-2`, commit `355905673de5`, with RtMidi from `iDoMeteor/rtmidi` branch `wheels/python-rtmidi-ft-1.5.8`, commit `cf53bcae93cc`. The C++ is regenerated with Cython 3.3.0. | python-rtmidi#230 and #231 backported to 1.5.8; RtMidi #395/#396 (via SpotlightKid/rtmidi#4) |
| glcontext 3.0.0 (`-2`) | `iDoMeteor/glcontext` branch `fix-error-paths`, commit `043bf2ef394b` | glcontext#41 and #42 |
| moderngl 5.12.0 (`-2`) | `iDoMeteor/moderngl` branch `wheels/ft-5.12.0-2`, commit `a9b914560638` | moderngl#751–#754 and #756 backported to 5.12.0, plus three reconciling commits |
| sphn 0.2.1 (`-1`) | PyPI sdist (same hash as above, `--locked`) plus a one-line patch, `#[pymodule(gil_used = false)]` (= `iDoMeteor/sphn` commit `638b3386f7f7`, sphn#23) | the module declares free-threading support |
| opencv-python-headless 4.13.0.92 (`-1`) | same tag and commits as above, plus `wheels/patches/opencv-4.13.0-free-threading.patch` (sha256 `1d19d901…53f4`, 7 files in `modules/python`, flann, dnn, gapi) | the free-threading declaration, plus locking and snapshot fixes in the binding layer |

- **Linux build:** UV's recipes, run by `~/Repos/python-free-threading/wheels/`
  `build_patched_ft_wheels.sh` and `build_patched_ft_opencv_wheel.sh`. Manifests with
  every hash are in the same directory (`patched-wheels-manifest-2.json`,
  `opencv-wheel-manifest.json`).
- **Windows build:** GitHub Actions in the private repo `iDoMeteor/ft-wheels-ci`
  (`windows-2022`, MSVC 14.44, python-build-standalone 20260929 / 3.14.7). Build
  records are in `~/Repos/python-free-threading/wheels/windows/`.

### sphn license audit (2026-10-01)

Method: `tools/packaging/audit_sphn_licenses.sh` runs `cargo tree --locked -e normal`
for both wheel targets against the pinned sdist's own `Cargo.lock` (sha256
`aafaf92a…300a`), then `sphn_third_party_notice.py` combines the result with each
crate's own license files.

- **114 third-party crates** are linked (proc-macro crates included although they
  only run at compile time; the Linux and Windows wheels differ by a few
  platform crates). No GPL, LGPL or AGPL.
- **16 crates are MPL-2.0** (every `symphonia*` decoder): weak, file-level
  copyleft. They are used unmodified, so the obligation is to keep the notices and
  tell recipients where the source is (crates.io and the repository, listed in the
  notice). It does not extend to the rest of the wheel.
- The rest are permissive: MIT or Apache-2.0 (87 of them, in various
  combinations), MIT (11), Unlicense OR MIT (3), BSD-2/BSD-3, ISC, Zlib, the
  Unicode license, and `Apache-2.0 WITH LLVM-exception` (`target-lexicon`).
- libopus is compiled in from C source bundled in `audiopus_sys` (ISC), under
  Xiph's BSD 3-clause license; its `COPYING` is in the notice.
- The symphonia crates and `realfft` ship no license file, so the notice carries
  the canonical SPDX text (MPL-2.0, MIT) and the manifest authors for them. The
  generator refuses to produce a notice that would claim a text it lacks.

## 8. Windows wheels: license facts (checked against the built wheels)

Built on GitHub Actions (`windows-ft-wheels.yml` running `build_windows_ft_wheels.py`);
inspected from the downloaded artifacts of runs 36855516862 (sphn) and 36856829020
(the GL/MIDI trio). All four are tag `cp314-cp314t-win_amd64`, contain no DLLs
(one `.pyd` each), and link only against Windows system libraries.

| Wheel | Source pins | License (wheel METADATA) | License file in the wheel | Contents |
|---|---|---|---|---|
| glcontext 3.0.0 | same sdist as Linux | MIT | `dist-info/licenses/LICENSE` | `glcontext/wgl.cp314t-win_amd64.pyd` (the only backend on Windows; Linux builds `egl` and `x11`) |
| moderngl 5.12.0 | same sdist as Linux | MIT | `dist-info/licenses/LICENSE` | `moderngl/mgl.cp314t-win_amd64.pyd` |
| python-rtmidi 1.5.8 (`-1`) | same sdist, Cython 3.3.0 regenerated | "Copyright & License" (classifier MIT) | `dist-info/LICENSE.md` | `rtmidi/_rtmidi.cp314t-win_amd64.pyd` (+ its `.lib`, a build by-product, as in upstream's wheels); uses WinMM, a system component; **no `libasound`** (Linux only) |
| sphn 0.2.1 | same sdist, `Cargo.lock` sha256 `aafaf92a…300a` | (none in METADATA; Cargo.toml says MIT/Apache-2.0) | `dist-info/licenses/LICENSE` | `sphn/sphn.cp314t-win_amd64.pyd`; statically links the same crate set: the [notice](../third-party/sphn-0.2.1-THIRD-PARTY-NOTICES.md) covers both targets (its platform column lists the few Windows-only crates) |

**OpenCV on Windows** (wheel not built yet; the first run compiled everything and
failed only at the link, fixed by defining `Py_GIL_DISABLED`): FFmpeg is **not**
built by us. OpenCV's CMake downloads its pre-built plugin
`opencv_videoio_ffmpeg_64.dll` from opencv_3rdparty commit
`d82ad9a54a7b42a1648a9cae8fed5c2f20ea396c` (md5 pinned by OpenCV). Its LGPL 2.1+
status, FFmpeg 4.4.6 contents, libvpx and aom statically linked, source
pointers and the verbatim license texts are in
[`docs/third-party/opencv-windows-ffmpeg-plugin-NOTICE.txt`](../third-party/opencv-windows-ffmpeg-plugin-NOTICE.txt).
LGPL was confirmed from OpenCV's readme, from the published build recipe, and
from the DLL itself (embedded configure string and license strings), not
assumed. Other bundled DLLs: none expected beyond that plugin and the module;
the built wheel contains exactly two binaries, `cv2/cv2.cp314t-win_amd64.pyd` and
`cv2/opencv_videoio_ffmpeg4130_64.dll`, the latter byte-identical (sha256
`fcc61467…4548`) to the DLL at the pinned opencv_3rdparty commit. The smoke test decodes the checked-in
fixture clips (`tools/packaging/ft-fixtures/`: H.264 `.mp4` and VP9 `.webm`, 20
frames each, a bar whose position encodes the frame number), in order and after
seeks, on Windows and Linux alike, because the CI runner has no system ffmpeg.
