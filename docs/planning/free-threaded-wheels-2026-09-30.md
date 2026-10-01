# Free-threaded (cp314t) wheels: moderngl, glcontext, python-rtmidi

Owner: UV Threads
Status: Linux wheels built, verified and published; Windows options awaiting a decision
Last updated: 2026-09-30

W1 of [the bug remediation plan](bug-remediation-plan-2026-09-30.md) bundles
free-threaded Python 3.14. Three extensions we depend on have no wheel for it
upstream (moderngl and glcontext have none for 3.14 at all, and PyPI shows no
cp314/cp313t wheel for any of the three as of today), so we build our own.

## 1. What exists

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

## 3. GIL behavior today

A free-threaded interpreter starts with the GIL **off** and turns it **on**
the first time it imports an extension module that has not declared it can
run without one (`Py_mod_gil`). Measured with each module imported alone in a
fresh process:

| Import | GIL afterwards |
|---|---|
| `glcontext` (package only; loads no extension) | off |
| `glcontext.egl`, `glcontext.x11` | **on** |
| `moderngl` (`moderngl.mgl`) | **on** |
| `rtmidi` (`_rtmidi`) | **on** |

So any process that imports moderngl or rtmidi runs with the GIL on. That is
the expected state for the main process (plan decision 1). It must never
happen in the audio helper, which imports none of them.

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
- **Main process:** INFO only, listing the known set above
  (`moderngl.mgl`, `glcontext.*`, `rtmidi._rtmidi`). A module outside the
  known set (for example `cv2` once the webcam loads) is worth a WARNING.
- Guard `sys._is_gil_enabled` with `getattr`: it does not exist before 3.13.

`ft_wheels_smoke.py` implements the same per-module probe and is a reference.

## 4. Windows wheels: options

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

Suggested order, if and when this is taken on: rtmidi first (cheap, testable,
removes one of the four flips), then glcontext, then moderngl as its own
project.
