# Free-threaded (cp314t) wheels: moderngl, glcontext, python-rtmidi

Owner: UV Threads
Status: all five Linux wheels and four of five Windows wheels built, verified and published; Windows OpenCV in progress
Last updated: 2026-09-30 (end of day)

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
| `cv2` (opencv, 4.13.0) | **on** |
| `sphn` | **on** |

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

## 6. Where we stopped (end of 2026-09-30) and next steps

**Done and published (Linux x86-64, `~/projects/_software-dist/wheelhouse/cp314t/`):**
moderngl, glcontext, python-rtmidi (build tag `-1`), opencv-python-headless and
sphn, all verified against the exact PBS 20260929 runtime.

**Windows.** `tools/packaging/build_windows_ft_wheels.py` is written
(standard-library only; reads its pins from the Linux scripts; downloads and
verifies the PBS Windows runtime; finds MSVC through vswhere; builds the five
wheels; smoke-tests each in a fresh venv; only verified wheels reach `--out`).
It has been run in `--dry-run` and covered by unit tests on Linux, and has
**not** been run on Windows; expect the first runner run to need a fix or two.
Interface agreed with UV Install: `--out DIR [--work DIR] [--only NAMES]
[--dry-run]`, a `windows-2022` job (150 minute timeout), artifact
`cp314t-win_amd64-wheels` holding the whole `--out` directory. UV Install writes
the workflow file (`workflow_dispatch` only, an optional `only` input passed
through as `--only`); the owner approved building on GitHub Actions. Copying the
artifact into the wheelhouse stays a human or follow-up step (append-only).

**Parked pending the owner:** the `Py_mod_gil` ports (assessment in section 5):
rtmidi first, then glcontext, then moderngl. Nothing is started.

**First thing next session:**
1. Once UV Install's workflow is merged, dispatch it with `only=sphn` first (a
   fast iteration on the whole Windows toolchain) and fix whatever the logs show,
   then `only=moderngl,glcontext,python-rtmidi`, and OpenCV last (the slow one).
2. Place the resulting `win_amd64` wheels into the wheelhouse and append to
   `SHA256SUMS`.
3. Smoke tests that need Windows only: the GL render check is skipped on the
   runner (no GPU), so one real run of `ft_wheels_smoke.py` on a Windows machine
   with a GPU would close that gap.

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
verify against the built wheel.
