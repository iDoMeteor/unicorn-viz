# BTrack benchmarking adapter — UNBLOCKED

Dev-only tooling wrapping Adam Stark's [BTrack](
https://github.com/adamstark/BTrack) real-time beat tracker so it can be fed
raw PCM audio blocks and report a running BPM estimate, for later comparison
against unicorn-viz's own in-house beat tracker
(`unicornviz/audio/beat_grid.py`, not touched by this tool). BTrack is
**GPL-3.0**, which is why this adapter is dev-only and never bundled into or
imported by the shipped application (see the "compatible in intent" note
below).

**Status (updated 2026-09-03): fully unblocked and working.** The owner
approved writing custom pybind11 bindings on top of BTrack's real causal
C++ API (`BTrack::processAudioFrame` / `BTrack::getCurrentTempoEstimate`),
bypassing the official batch-only `BTrackPythonModule.cpp` bindings
entirely (see "Why custom bindings were needed" below). Those bindings
(`btrack_streaming.cpp`) build and link cleanly, `adapter.py` and `run.py`
implement the same `ExternalBeatTracker` interface as the sibling madmom /
essentia / BeatNet adapters, and the self-test passes at 120 BPM (see
"Self-test results" below for the full picture, including an honest
half-time lock at 174 BPM).

## "Compatible in intent"

The planned adapter interface (shared with sibling madmom / essentia /
BeatNet adapters being built in parallel) is a *causal, real-time* one:
`feed()` is called once per live-cadence PCM block and `bpm`/`confidence`
report the tracker's current running estimate, the same way a live VJ signal
chain would consume it. That's "compatible in intent" with this project's
own beat tracker, which is also causal/streaming. BTrack was chosen for this
comparison because it is one of the few well-known trackers designed
explicitly for real-time, frame-by-frame operation (as opposed to offline
whole-track analysis).

## What was attempted

1. **`pip install btrack-beat-tracker`** (the package the upstream README
   points to, PyPI versions 1.0.6/1.0.7) — **fails immediately**, before any
   compiler/library issue. The published sdist only packages the
   `plugins/python-module/` subdirectory, but that directory's own
   `CMakeLists.txt` does `add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../src)`
   and includes `../../libs/kiss_fft130` — paths that only exist in a full
   checkout of the repo, not in the sdist. This looks like an upstream
   packaging bug in the 1.0.6/1.0.7 releases, not something fixable from our
   side. No pre-built wheels are published for any platform except a single
   macOS arm64/cp311 wheel that happens to be bundled *inside* the sdist
   tarball itself (`dist/btrack_beat_tracker-1.0.7-cp311-cp311-macosx_15_0_arm64.whl`)
   — not usable on Linux/cp314 here, and not something `pip` picks up anyway
   since it isn't hosted as a real wheel on PyPI.

2. **Built from a full shallow clone of the real repo instead** (`git clone
   --depth 1 https://github.com/adamstark/BTrack.git`, into `/tmp`, well
   outside the repo — not committed anywhere), then
   `pip install --no-deps .` from `plugins/python-module/` with `pybind11`,
   `numpy`, and `scikit-build-core` present in the isolated venv. This
   resolves the path problem from step 1, but CMake then fails
   deterministically:

   ```
   CMake Error at /tmp/btrack_src_check/src/CMakeLists.txt:23 (message):
     libsamplerate not found! Please install it.
   ```

   `src/CMakeLists.txt` does `find_library(LIBSAMPLERATE_LIBRARIES NAMES
   samplerate)` and treats a miss as fatal. `libsamplerate` is a genuine,
   load-bearing dependency here, not just linked out of habit — `BTrack.cpp`
   calls `src_simple()` (`SRC_SINC_BEST_QUALITY`) to resample the onset
   detection function during tempo-period estimation.

3. **Checked what's actually on this machine:** the *runtime* shared library
   is present (`/usr/lib64/libsamplerate.so.0`, from Fedora package
   `libsamplerate-0.2.2-12.fc44.x86_64`), but the **`-devel` subpackage is
   not installed** (`rpm -q libsamplerate-devel` → not installed). That
   subpackage is what provides `samplerate.h` and the unversioned
   `libsamplerate.so` symlink that `find_library`/the linker need to compile
   and link against it. Getting a working build would require
   `dnf install libsamplerate-devel`.

4. **Checked for a pip-installable escape hatch:** PyPI has a `samplerate`
   package (CFFI wrapper, versions up to 0.2.4). Its wheel
   (`samplerate-0.2.4-...manylinux....whl`) ships only a pre-built Python
   extension module (`samplerate.cpython-314-x86_64-linux-gnu.so`) — no
   `samplerate.h` header and no general-purpose linkable `.so` that BTrack's
   own CMake build could point at. It's meant for calling libsamplerate
   *from* Python, not for letting other native code link against it. Using
   it here would mean hand-authoring a shim header and pointing CMake at
   internals never meant to be built against this way — a nontrivial,
   fragile system-level workaround, not a real pip-install path.

## Why nothing else was built (at the time)

Per the task's strict rule: if BTrack needs a system package manager
install (`apt`/`dnf`) or `sudo` to get a working C++ toolchain, or there's
no way to get working Python bindings without a nontrivial system-level
change, stop and report instead of doing it. Both conditions were met here —
`dnf install libsamplerate-devel` was exactly that kind of change, and the
one pip-based alternative found didn't provide what the build needs. So the
adapter module (`ExternalBeatTracker`) and CLI runner (`run.py`) described in
the task were **not written** at that point: without a working
`btrack_beat_tracker` import there would be nothing real to call, and writing
untested code against an API that can't be exercised or self-tested here
would go against this project's regression-test discipline (CLAUDE.md: don't
ship code whose behavior can't be verified).

## Retry after `libsamplerate-devel`

The owner reviewed the blocker above and approved installing the missing
system package: `sudo dnf install -y libsamplerate-devel` was run
(**by the owner, outside this tool** — not by an agent), installing
`libsamplerate-devel-0.2.2-12.fc44.x86_64` cleanly. Confirmed present
afterward: `/usr/include/samplerate.h` and the unversioned, linkable
`/usr/lib64/libsamplerate.so`.

**Re-ran the exact CMake configure + build from a fresh clone
(`/tmp/btrack_src_check`, same as before — outside the repo, not
committed).** Two things were tried:

1. **The core BTrack C++ library on its own** (the root `CMakeLists.txt`,
   `cmake -S . -B build_core && cmake --build build_core`) — **this now
   builds and links successfully, with no errors**:

   ```
   -- Using libsamplerate: /usr/lib64/libsamplerate.so
   -- Configuring done (0.4s)
   -- Generating done (0.0s)
   [ 25%] Building C object src/CMakeFiles/BTrack.dir/__/libs/kiss_fft130/kiss_fft.c.o
   [ 75%] Building CXX object src/CMakeFiles/BTrack.dir/OnsetDetectionFunction.cpp.o
   [ 75%] Building CXX object src/CMakeFiles/BTrack.dir/BTrack.cpp.o
   [100%] Linking CXX static library libBTrack.a
   [100%] Built target BTrack
   ```

   `nm` on the resulting `libBTrack.a` confirms both symbols the task's
   planned adapter needs are present and compiled in:
   `BTrack::processAudioFrame(double*)` and
   `BTrack::getCurrentTempoEstimate()`. The `libsamplerate` blocker is fully
   resolved for the core library.

2. **The official pip package** (`pip install --no-deps .` from
   `plugins/python-module/`, same as the earlier attempt) — CMake configure
   now succeeds and reaches the same "Using libsamplerate:
   `/usr/lib64/libsamplerate.so`" line, and three of the four compile steps
   (kiss_fft, `OnsetDetectionFunction.cpp`, `BTrack.cpp`) succeed. **The
   build still fails overall**, but now for a completely different,
   unrelated reason — a real compile error, not a missing dependency:

   ```
   BTrackPythonModule.cpp: In function 'PyObject* detectBeats(PyObject*, PyObject*)':
   BTrackPythonModule.cpp:38:14: error: 'copy_n' is not a member of 'std';
   did you mean 'copy'?
       std::copy_n (audioSampleArray + (i * hopSize), hopSize, buffer.begin());
   ```

   `plugins/python-module/BTrackPythonModule.cpp` uses `std::copy_n` (twice)
   but never includes `<algorithm>`; it relies on getting that header
   transitively through something else it does include. On this system's
   compiler (GCC 16.1.1 / newer libstdc++) that transitive include no longer
   happens, so the file fails to compile as-is. This is a pre-existing
   upstream source bug in `BTrackPythonModule.cpp` itself, independent of
   `libsamplerate` and independent of the missing-streaming-API gap below —
   it would affect anyone building this specific file with a sufficiently
   modern compiler, regardless of platform. **Not fixed here**: it lives
   inside the Python-bindings file, which is explicitly out of scope for
   this pass (the owner asked only to confirm the core C++ library builds,
   and separately asked not to start bindings work yet) — a one-line
   `#include <algorithm>` fix is possible but wasn't made, pending a
   decision on the bindings work as a whole, since patching this file only
   matters in service of that.

**Bottom line: the core BTrack C++ library is no longer blocked and builds
cleanly against `libsamplerate`. The pip-installable `btrack-beat-tracker`
module remains unbuildable, but the reason has moved from "missing system
dependency" to "upstream source bug in a file we'd be rewriting anyway if
custom bindings are approved."**

## A second blocker, independent of the build issue (now resolved)

Even with `libsamplerate-devel` installed and the core library building, the
**official Python bindings don't expose a streaming/frame-by-frame API at
all.** `plugins/python-module/BTrackPythonModule.cpp` binds exactly three
functions, and all three take a *complete* NumPy array up front and run the
whole thing in a C++ loop before returning:

- `detect_beats(audioData)` — full offline beat-time extraction
- `calculate_onset_detection_function(audioData)` — full offline ODF
- `detect_beats_from_odf(odf)` — also full offline; internally constructs a
  **new** `BTrack` instance per call, so there's no way to carry state across
  repeated calls to fake incremental feeding either

The underlying C++ `BTrack` class (`src/BTrack.h`) does have the per-frame
API this project needed — `processAudioFrame(double*)` and
`getCurrentTempoEstimate()` are both real, present methods — but neither was
reachable from Python upstream. The owner approved writing and maintaining
custom pybind11 bindings on top of BTrack's C++ core to close this gap; see
below.

## Custom pybind11 bindings

`btrack_streaming.cpp` in this directory is a small, from-scratch pybind11
binding source file — it does not reuse or patch
`BTrackPythonModule.cpp` (which has its own unrelated `std::copy_n` compile
bug on this system regardless, see above). It exposes one class,
`BTrackStream`, wrapping exactly the slice of `BTrack` needed:

- `BTrackStream(hop_size, frame_size)` → `BTrack::BTrack(int, int)`
- `.process_audio_frame(frame)` → `BTrack::processAudioFrame(double*)`,
  taking a 1-D NumPy array (any dtype, auto-cast to `double` and forced
  contiguous by pybind11)
- `.current_tempo_estimate()` → `BTrack::getCurrentTempoEstimate()`
- `.beat_due_in_current_frame()` → `BTrack::beatDueInCurrentFrame()`
  (not used by `adapter.py`, exposed for completeness/future use)
- `.latest_cumulative_score_value()` → `BTrack::getLatestCumulativeScoreValue()`
  (also not used by `adapter.py` as a confidence value; see "Confidence"
  below for why)

### What BTrack's real constructor/frame-size requirements turned out to be

Reading `src/BTrack.h` and `src/BTrack.cpp` directly (rather than guessing)
turned up two things worth flagging:

1. **`processAudioFrame`'s buffer length is `hop_size`, not `frame_size`,
   despite `BTrack.h`'s own doc comment**, which says "[frame] should match
   the frame size that the algorithm was initialised with." Upstream's own
   `BTrackPythonModule.cpp::detectBeats` allocates a `hopSize`-length buffer
   and passes that — confirmed empirically here too: a `hop_size`-length
   call produces a stable, sane tempo estimate on a synthetic click track,
   matching the official bindings' own usage. `frame_size` is BTrack's
   larger internal analysis window, held and advanced by its own
   `OnsetDetectionFunction` member across successive `hop_size`-length
   calls; callers never see it directly. This binding's own doc comment on
   `process_audio_frame` records this so a future reader doesn't have to
   re-derive it.
2. **BTrack hardcodes a 44100 Hz assumption internally** — `BTrack.cpp`'s
   tempo/beat-period math (`calculateTempo()`, `getBeatTimeInSeconds()`,
   the `hopSize`-to-BPM conversions at lines ~152-154, ~277, and ~435-438
   of `src/BTrack.cpp`) all divide by the literal constant `44100`, not by
   any sample-rate parameter — there isn't one anywhere in the constructor
   or `processAudioFrame`. `adapter.py` therefore always resamples incoming
   audio to 44100 Hz before feeding it to BTrack (see "Adapter design"
   below) rather than trying to scale `hop_size`/`frame_size` to the source
   rate, since BTrack's internal math wouldn't track a scaled hop size
   correctly anyway.

The default constructor (`BTrack()`, no arguments) assumes `hopSize=512`,
`frameSize=1024`; the two/three-argument constructors let the caller set
`hopSize` alone (with `frameSize` defaulting to `2 * hopSize`) or both
explicitly. `adapter.py` uses `hop_size=512, frame_size=1024` — the same
values BTrack's own default constructor, `tests/main.cpp`, and
`BTrackPythonModule.cpp` all use for 44100 Hz audio.

### Exact build command used

From a fresh, disposable clone outside the repo (`/tmp`, deleted after the
build — the resulting `.so` has no runtime dependency on it surviving,
confirmed by re-running the self-test after `rm -rf` on the clone):

```sh
git clone --depth 1 https://github.com/adamstark/BTrack.git /tmp/btrack_bindings_build

# 1. Build the core static library, with -fPIC (required: linking a
#    non-PIC static lib into a shared object fails with
#    "relocation R_X86_64_32 against `.rodata` can not be used when
#    making a shared object" on this toolchain).
cmake -S /tmp/btrack_bindings_build -B /tmp/btrack_bindings_build/build_core \
      -DBUILD_TESTS=OFF -DCMAKE_POSITION_INDEPENDENT_CODE=ON
cmake --build /tmp/btrack_bindings_build/build_core

# 2. Compile and link the custom bindings against it, from this directory.
BTRACK_SRC=/tmp/btrack_bindings_build
EXT_SUFFIX=$(.venv/bin/python -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))")
PYBIND_INCLUDES=$(.venv/bin/python -m pybind11 --includes)

g++ -O2 -Wall -shared -std=c++17 -fPIC \
    -DUSE_KISS_FFT \
    -I"$BTRACK_SRC/src" -I"$BTRACK_SRC/libs/kiss_fft130" \
    $PYBIND_INCLUDES \
    btrack_streaming.cpp \
    "$BTRACK_SRC/build_core/src/libBTrack.a" \
    -lsamplerate \
    -o "btrack_streaming${EXT_SUFFIX}"
```

`-DUSE_KISS_FFT` must match how `libBTrack.a` itself was built
(`src/CMakeLists.txt` sets it as a `PUBLIC` compile definition — its
`kiss_fft.h`/`fftw3.h` branch in `OnsetDetectionFunction.h` must agree with
what the static library was actually compiled with, or the two objects
disagree about struct layouts). `pybind11` and its headers were already
present in this directory's isolated `.venv` (`pip install pybind11`, a
pure-Python package with bundled headers — no system package needed). The
resulting `btrack_streaming.cpython-314-x86_64-linux-gnu.so` links
dynamically only against the system `libsamplerate.so.0` (confirmed with
`ldd`) and is otherwise self-contained; it is **not committed to the repo**
(see this directory's own `.gitignore` — it's a platform-specific,
GPL-3.0-derivative binary, reproducible from the steps above, not something
to check in). Re-running this build requires only re-cloning BTrack into a
scratch directory; nothing else here depends on that clone persisting.

## Adapter design (`adapter.py`)

`ExternalBeatTracker` matches the shared interface exactly
(`warm_up(sample_rate)`, `feed(block, block_start_s)`, `bpm`, `confidence`).
Key decisions, each documented in more depth in the module's own docstring:

- **Always resamples to 44100 Hz** (plain `numpy.interp` linear
  resampling, no anti-aliasing filter — the same lightweight approach the
  sibling essentia adapter uses) before buffering and feeding BTrack, per
  the hardcoded-44100 finding above. Audio already at 44100 Hz (the default
  for both `--synthetic-click` and typical WAV files) never passes through
  the resampler.
- **Buffers incoming blocks and calls `process_audio_frame()` once per 512
  accumulated samples** (`hop_size`), converting to `float64` first (BTrack
  expects `double`).
- **`bpm` reports 0.0 until at least one real hop has been processed.**
  BTrack's own `getCurrentTempoEstimate()` returns a built-in prior of
  **120.0 BPM even on a freshly constructed instance, before any audio is
  fed at all** (confirmed directly: `BTrackStream(512, 1024).current_tempo_estimate()`
  → `120.0`) — it is not a "no estimate yet" sentinel the way `0.0` is for
  the sibling adapters. Reporting BTrack's raw value from the start would
  make an untouched tracker look like it had already locked onto 120 BPM,
  so the adapter tracks whether a real hop has been processed and reports
  `0.0` until then, matching the sibling adapters' convention.
- **`confidence` is always `0.0`.** BTrack exposes no bounded,
  documented confidence/probability value. `getLatestCumulativeScoreValue()`
  exists but is an internal, unnormalised beat-alignment strength signal
  with no fixed scale — observed magnitude in the high hundreds/low
  thousands on a clean synthetic click track (e.g. ~999 at the end of the
  120 BPM self-test run), scaling with signal energy and the internal
  `tightness` parameter. Reporting that as a `[0, 1]`-style "confidence"
  would require an arbitrary, unvalidated normalisation, so per the shared
  interface's own "0.0 if the library doesn't expose one" convention, this
  adapter reports `0.0` rather than inventing a scale.

`run.py` mirrors the other adapters' CLI exactly: `--audio <path>` (a plain
`wave`-module PCM WAV loader — no extra audio-file dependency was added to
this venv, since madmom/librosa aren't installed here and weren't needed for
the self-test) or `--synthetic-click --bpm <N> --duration <seconds>`, plus
`--sample-rate`, `--block-size`, `--seed`, and `--out`. `self_test.py`
mirrors the madmom adapter's self-test shape and structure.

## Self-test results

`.venv/bin/python self_test.py` runs `--synthetic-click` at two tempi (120
and 174 BPM, 30 s each, matching this project's default synthetic-click
generator). Results as of 2026-09-03:

```
PASS   true_bpm= 120.0  final_bpm= 117.45  error= 2.12%
OCTAVE true_bpm= 174.0  final_bpm=  86.13  error=50.50%  (locked onto 0.5x true tempo)
```

**120 BPM lands comfortably inside the +/-4% tolerance** (2.12% error, final
estimate 117.45 BPM after 30 s). **174 BPM does not** — it locks onto
half-time (86.13 BPM, essentially exactly 0.5x true tempo) and stays there
regardless of run length (also checked at 60 s, identical result). This
was the specific behavior the task asked to check for ("BTrack's causal
comb-filter/onset approach may behave differently at faster tempos"), and
it's real: a broader sweep on the same synthetic click track (30 s each,
same seed) shows a clean transition rather than a hard cutoff —

```
bpm= 90.0  ->  final= 87.59
bpm=100.0  ->  final= 99.38
bpm=128.0  ->  final=126.05
bpm=140.0  ->  final=136.00
bpm=150.0  ->  final=147.66
bpm=160.0  ->  final=156.61
bpm=174.0  ->  final= 86.13   (half-time lock)
```

Every tempo from 90-160 BPM tracks correctly (within a few percent) on this
pure click signal; 174 BPM is where it flips to a half-time lock. This
reads as a genuine octave-ambiguity characteristic of BTrack's
autocorrelation/comb-filter tempo estimator on this input (a known,
well-documented failure mode for this class of algorithm, not unique to
BTrack), not a wiring bug in this binding or adapter — the same code path
that produces a correct 156.61 BPM estimate at 160 BPM produces the
half-time lock three tempo steps later. It's also worth noting BTrack was
tuned against real music, not pure synthetic click tracks; a click track
gives the comb filter bank very little spectral variety to disambiguate
octave candidates with, so real audio may behave differently at this tempo
range. Also confirmed working end-to-end: the `--audio` WAV-file path (a
synthesized 128 BPM click track, 15 s, 16-bit PCM WAV — produced 126.05
BPM, 1.5% error) and the resampling path (the same 120 BPM click track
generated at 48000 Hz instead of 44100 Hz produces an identical 117.45 BPM
final estimate, confirming the linear resampler doesn't introduce timing
error here).

## Tempo range widening experiment (2026-09-03) — tried, reverted

A collaborating session hypothesized that BTrack's poor dnb-01 accuracy
(31.25%, 5/16 tracks, Acc1 = within +/-4% of reference) on the 306-track
real-music benchmark was a *configuration ceiling*, not a genuine
detection weakness: every dnb-01 miss folded cleanly to half-time (Acc2 =
100%), and the 174 BPM synthetic click track locked half-time too (see
"Self-test results" above). Re-checking `BTrack.cpp`/`BTrack.h` directly
(fresh clone to `/tmp`, removed afterward, not committed) confirmed
BTrack hardcodes an **80-160 BPM tempo search range**, structurally —
not a simple two-constant tweak:

- `BTrack.h` declares a fixed-size C array
  `double tempoTransitionMatrix[41][41]`.
- The constructor (`initialise()`) fills it from a Gaussian in *bin*
  space, `m_sig = 41 / 8` (integer-truncated to `5.0` bins), centered on
  the diagonal each row (`t_mu = i + 1`, overwriting the pre-loop
  initializer every iteration — that initializer is dead code, both
  upstream and after this patch).
- `setTempo()`/`fixTempo()` clamp/fold any tempo outside 80-160 back into
  range with `while (tempo > 160) tempo /= 2;` / `while (tempo < 80)
  tempo *= 2;`, then map to a bin index via `(tempo - 80.) / 2` (41 bins
  at a 2 BPM step, 80 to 160 inclusive).
- `calculateTempo()`'s comb-filter-to-tempo-lattice mapping computes, for
  bin `i`, `bpm1 = (2*i)+80` (the candidate's own tempo) and
  `bpm2 = (4*i)+160` (exactly `2 * bpm1` — the octave above, sampled from
  the comb filter bank too, for harmonic disambiguation), then converts
  each to a lag-domain index into `combFilterBankOutput[128]`.
  `beatPeriod` at the end is derived from the winning bin the same way.

This target project's own detector (`beat_grid.py`'s v3 lattice,
`_V3_LATTICE_MIN_BPM`/`_V3_LATTICE_MAX_BPM` in
`drop-ins/auto-vj-01/beat_grid.py`) searches 55-210 BPM, so that's the
range this experiment targeted for a fair dnb-01 comparison.

### Bin-count/step decision

Two options were on the table: (a) keep 41 bins and widen the BPM step
to ~3.875, or (b) keep the 2 BPM step and grow the array. **Chose (b)**,
sized deliberately rather than by eyeballing the task's own suggested
arithmetic — `ceil((210-55)/2)+1` actually evaluates to 79 (`ceil(77.5) =
78`, `+ 1 = 79`), not 78 — and picked the low end so a bin sits exactly
on 55: 79 bins, `55.0` to `55.0 + 78*2.0 = 211.0` BPM, 2 BPM/step. This
covers the full 55-210 target range with one bin (211) to spare at the
top, rather than falling 1 BPM short of 210 the way a 78-bin lattice
would.

Reasoning for (b) over (a): the Gaussian transition matrix
(`tempoTransitionMatrix`) operates entirely in *bin*-index space, and
because the loop that fills it re-derives `t_mu = i + 1` per row, its
shape doesn't care what BPM a bin represents — only the two BPM<->bin
conversion formulas and the comb-filter lattice mapping do. Keeping the
2 BPM/bin step means those conversions are simple range/offset edits and
the transition kernel's *real-world-BPM* width — `m_sig` (5 bins) x
`kTempoBinStepBpm` (2 BPM) = 10 BPM std — is preserved exactly from
upstream, deliberately **not** rescaled proportionally to the new bin
count (which would have widened it to ~19.5 BPM std and changed the
tracker's frame-to-frame tempo-continuity/smoothing dynamics, not just
its coverage — an unrequested behavioral change). Option (a) would have
kept 41 bins but silently loosened that same continuity constraint by
having each bin span nearly double the BPM range, so the "same 5-bin
Gaussian" would represent almost 2x the real-world tempo swing per
update — a bigger, harder-to-reason-about departure from upstream's
tuned behavior for the same nominal range-widening goal. (b) touches
fewer independent things and keeps a clean mental model: "same
resolution, same tracking looseness, just more of it."

Implementation: `BTrack.h` gained three `static constexpr` members
(`kNumTempoBins = 79`, `kTempoBinLowBpm = 55.0`, `kTempoBinStepBpm =
2.0`, plus a derived `kTempoBinHighBpm = 211.0`) and the array became
`tempoTransitionMatrix[kNumTempoBins][kNumTempoBins]`. Every load-bearing
site in `BTrack.cpp` was switched to these constants: the four
`.resize(41)` calls in `initialise()`, the Gaussian fill's two loop
bounds (`m_sig` itself intentionally left as the literal `41 / 8`, with a
comment explaining why), `setTempo()`'s and `fixTempo()`'s clamp loops
and bin-index formulas, and `calculateTempo()`'s tempo-observation loop
(rewritten as `bpm1 = kTempoBinLowBpm + i*kTempoBinStepBpm`, `bpm2 =
2.0*bpm1`, preserving the `bpm2 == 2*bpm1` identity explicitly instead of
via the coincidental `(4*i)+160 == 2*((2*i)+80)` upstream algebra), the
`tempoFixed`/delta/max-search loop bounds, and the final `beatPeriod`
formula. Grepped `BTrack.cpp`/`BTrack.h` afterward for remaining `41`,
`80`, `160` literals — the only survivors are comments and the
intentionally-unscaled `m_sig = 41 / 8`. `combFilterBankOutput`'s own
size (128) and the comb-filter-bank computation itself are unrelated to
this range (confirmed all `tempoIndex1`/`tempoIndex2` values stay well
within `[0, 127]` for the new 55-211 BPM lattice, same as the original
80-160 one) and were correctly left untouched.

Build: identical pipeline to "Exact build command used" above, from a
fresh `git clone --depth 1` to `/tmp` (removed after the build, not
committed) — core static lib via CMake with
`-DCMAKE_POSITION_INDEPENDENT_CODE=ON`, then the same `g++` bindings
command against the patched `libBTrack.a`. Both the core library and the
bindings built clean, no warnings.

### Validation: full synthetic sweep (before required trusting dnb at all)

Same `generate_synthetic_click` generator, seed 0, 60 s per tempo, run
through the *widened* build first, self-test-style, across 60-200 BPM
plus below the old floor:

```
bpm= 60.0 -> final=117.45  error=95.76%   (fails both builds -- see below)
bpm= 70.0 -> final= 68.91  error= 1.56%   FIXED (was folding to ~139.7, 99.5% err)
bpm= 90.0 -> final= 89.10  error= 1.00%   ok (was 87.59, 2.67% err -- still ok)
bpm=100.0 -> final= 99.38  error= 0.62%   unchanged, ok
bpm=120.0 -> final=117.45  error= 2.12%   unchanged, ok
bpm=140.0 -> final=136.00  error= 2.86%   unchanged, ok
bpm=160.0 -> final= 79.51  error=50.31%   REGRESSED (was 156.61, 2.12% err -- solid)
bpm=174.0 -> final=172.27  error= 1.00%   FIXED (was folding to 86.13, 50.5% err)
bpm=190.0 -> final= 92.29  error=51.43%   fails both (never in old range either)
bpm=200.0 -> final= 97.51  error=51.25%   fails both (never in old range either)
```

The 174 BPM target case is fixed, as hoped, and so is 70 BPM (previously
folded *up* to ~140 because 70 sat below the old 80 BPM floor). But
**160 BPM — solidly inside the old 80-160 range, previously rock-stable
across a full 60 s run at 156.61 BPM — now drifts to a half-time lock**.
A per-tick trace confirmed this is a genuine mid-run drift, not
noise-seed sensitivity or a one-off: BTrack locks correctly at 156.61 by
t=0.46s, holds it, then flips to 79.51 at t=2.62s and never recovers
(identical across 3 different noise seeds). A finer sweep around the old
80-160 ceiling (145-170 BPM, 3 seeds each, 45 s) localized the damage:

```
bpm=145 -> 143.56  1.00%  ok
bpm=150 -> 147.66  1.56%  ok
bpm=155 ->  77.13 50.24%  REGRESSED
bpm=158 -> 156.61  0.88%  ok (narrow surviving pocket)
bpm=159 ->  79.51 50.00%  REGRESSED
bpm=160 ->  79.51 50.31%  REGRESSED
bpm=161 ->  79.51 50.62%  REGRESSED
bpm=162 ->  79.51 50.92%  REGRESSED
bpm=165 ->  80.75 51.06%  REGRESSED
bpm=170 ->  83.35 50.97%  (outside old range too, not a new regression)
```

Cross-checking against a *fresh, unmodified* 80-160 build on the exact
same seeds/durations confirmed the old build tracks 145-160 solidly with
no drift at any point in a 60 s run — this is a real, reproducible
regression introduced by the widening, concentrated in a ~155-170 BPM
band right where the old lattice's *ceiling* used to sit.

**Why:** in the original 41-bin lattice, 160 BPM sits at the very last
bin (index 40) — there is no higher bin to drift to, so the transition
matrix's Gaussian "friction" only has to resist drifting *down*, and
apparently wins that fight for a full 60 s. In the widened 79-bin
lattice, 160 BPM sits mid-range (bin ~52 of 78) with room to drift both
ways, and the same underlying half-time ambiguity that the comb filter
bank always carries (real periodic signals have real energy at their own
sub-harmonics) is now free to win over several seconds. In other words:
part of the old range's apparent robustness at its own ceiling was an
artifact of having nowhere to go, not genuine tracking strength — a
finding in its own right, independent of the dnb-01 question.

### Validation: dnb-01, 16 tracks (only after the sweep passed the "no gap in 90-150" bar)

Ran the widened adapter over the same 16 dnb-01 tracks and reference BPMs
used for the already-known 31.25% (5/16) baseline, via a temporary
scratch script (not added to this directory) mirroring
`batch_311.py`'s `decode_mono_ffmpeg()` (ffmpeg subprocess, 48 kHz mono
float32, 150 s cap) and its `p50_tail` metric (median BPM over the last
60% of ticks) / Acc1 convention (+/-4% of reference). Confirmed the
already-known baseline first by recomputing Acc1 straight from the
existing `results/batch_311_btrack.json` dnb-01 rows: 5/16 = 31.25%,
exact match.

| Track | Ref BPM | Before (p50_tail) | Acc1 before | After (p50_tail) | Acc1 after |
|---|---|---|---|---|---|
| Anthony David X DJ Queen Bee - For The Longest Time | 108.0 | 156.61 | False | 80.75 | False |
| Circuit Haze - William Byron | 86.0 | 112.35 | False | 166.71 | False |
| H2so4 ft Mavis - Frequency | 86.0 | 86.13 | True | 84.72 | True |
| Hplus - Me Feel | 164.0 | 82.03 | False | 107.67 | False |
| Hplus - What If | 169.0 | 83.35 | False | 166.71 | **True (fixed)** |
| Jordanlivingood - All The Time | 87.0 | 86.13 | True | 87.59 | True |
| Juvenile - Lalalalala (Remix) | 84.0 | 83.35 | True | 83.35 | True |
| Poni Punkflwr & Fisherboi - Pink Tongue | 166.0 | 82.03 | False | 161.50 | **True (fixed)** |
| Poni Punkflwr & Fisherboi - The 2nd Rip | 171.0 | 83.35 | False | 84.72 | False |
| Roderic H - Miss You | 174.0 | 86.13 | False | 172.27 | **True (fixed)** |
| Rodney Kamal Jackson - Turista | 100.0 | 99.38 | True | 99.38 | True |
| Route 94 ft Jess Glynne - My Love (Catchfraze Remix) | 173.0 | 86.13 | False | 87.59 | False |
| Sn - No10 Get The Fuck Out | 174.0 | 86.13 | False | 172.27 | **True (fixed)** |
| Sn - Witch Turning To Myth | 170.0 | 83.35 | False | 83.35 | False |
| Unsolicited Thoughts - The Day Phil Collins Stopped Caring | 148.0 | 147.66 | True | 147.66 | True |
| d - Kennys Sister | 118.0 | 86.13 | False | 87.59 | False |

**dnb-01 Acc1: 31.25% (5/16) before -> 56.25% (9/16) after** — a
meaningful recovery, all four newly-fixed tracks landing in the
160-174 BPM band the widening specifically targeted, exactly as the
"configuration ceiling" hypothesis predicted.

### Decision: reverted, original 80-160 build stays live

The task's own validation gate for this experiment was explicit:
widening the range **must not regress the 80-160 BPM range that was
already fine**. It did — the 155-170 BPM band (previously solid,
including a full 60 s stable lock at 160 BPM) now drifts to a half-time
lock over several seconds, confirmed reproducible across seeds and via a
direct before/after comparison against a freshly-rebuilt, unmodified
80-160 clone. This sits alongside a genuine, meaningful dnb-01 recovery
(31.25% -> 56.25%), so the two outcomes don't collapse cleanly into
either of the task's two anticipated cases ("recovers with no regression,
keep it" / "doesn't recover, revert") — there's a real regression
*and* a real recovery. Per the explicit "must not regress" requirement,
the regression wins: **the widened build was not kept live.**

The live `btrack_streaming*.so` in this directory was rebuilt from a
second fresh, unmodified `git clone --depth 1` (separate from the one
used for the widened patch, to avoid any chance of contamination) and
confirmed **byte-for-byte identical** (`md5sum`) to the `.so` that was
already live before this experiment started. `self_test.py` was re-run
against it and reproduces the exact documented baseline (`PASS
true_bpm=120.0 final_bpm=117.45 error=2.12%` /
`OCTAVE true_bpm=174.0 final_bpm=86.13 error=50.50%`), confirming the
revert is clean. The patched source tree, both `/tmp` clones, and all
intermediate `.so` builds from this experiment were deleted; nothing
from this experiment is committed or left as the live artifact beyond
this README section.

**For the record, not acted on:** the dnb-01 recovery is real evidence
the "configuration ceiling" hypothesis was at least partly right — the
range genuinely was too narrow for this genre's tempo profile — but the
155-170 BPM regression shows the fix isn't free: BTrack's fixed-width
Gaussian tempo-transition prior trades range for stability at whatever
tempo ends up away from the lattice edges, at least on pure synthetic
click material. A narrower, deliberately-targeted range (e.g. widening
only the *upper* bound to cover dnb's 160-180 lane while leaving the
lower bound at 80, so 90-160 keeps its original bin positions and
non-edge tempos in the newly-added 160-210 region don't necessarily
inherit the same problem) was not attempted here and would need its own
full validation pass before being trusted; left for the owner to decide
whether it's worth pursuing.

## License

GNU General Public License v3.0 (GPL-3.0-or-later), per BTrack's repository
license and the `plugins/python-module/README.md` header
("Copyright (c) 2014 Queen Mary University of London"). This is exactly why
the task scoped this as dev-only, isolated tooling: GPL-3.0 code must never
be imported by or bundled into the shipped `unicornviz` application.

The compiled `btrack_streaming*.so` extension in this directory links
directly against BTrack's compiled C++ core (`libBTrack.a`) and is
therefore **itself a GPL-3.0 derivative work**, exactly like `libBTrack.a`
itself — same treatment as this repository's other three benchmarking
adapters' own licensing notes. It is not committed to the repo (see
`.gitignore` in this directory), is built only into this isolated,
gitignored directory, is never imported by `unicornviz/` or any drop-in,
and is never referenced from `requirements.txt`. Treat it exactly like the
madmom/essentia/BeatNet adapters' own isolated venvs: local, reproducible,
dev-only benchmarking tooling only.
