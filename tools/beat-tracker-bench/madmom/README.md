# madmom benchmarking adapter

Dev-only tooling that wraps [madmom](https://github.com/CPJKU/madmom)'s
online beat tracker (`RNNBeatProcessor` feeding
`DBNBeatTrackingProcessor(online=True)`) so it can be fed raw PCM audio
blocks incrementally and report a running BPM estimate, for later
comparison against unicorn-viz's own in-house beat tracker
(`unicornviz/audio/beat_grid.py`, **not touched by this tool**).

This directory is fully self-contained: an isolated venv, no changes to
`requirements.txt`, no changes to `unicornviz/` or any drop-in, and no
audio files committed to the repository (see "Isolation" below).

## Status: working

Installed and validated end-to-end. Both self-test cases lock onto the
correct tempo (see "Self-test results").

## "Compatible in intent"

The adapter interface (shared with sibling BTrack / essentia / BeatNet
adapters being built in parallel under `tools/beat-tracker-bench/`) is a
*causal, real-time* one: `feed()` is called once per live-cadence PCM
block, and `bpm` / `confidence` report the tracker's current running
estimate — the same way a live VJ audio-reactivity chain would consume it.
That's "compatible in intent" with madmom's `online=True` mode specifically
(as opposed to madmom's more common offline whole-file Viterbi decoding),
and with this project's own beat tracker, which is also causal/streaming.

## Why this exists

`unicornviz/audio/beat_grid.py` is this project's own BPM/beat-lock
detector, tuned and versioned independently (see
`docs/adr/vj-system.md`). This adapter exists purely to give that detector
an external point of comparison on the same audio, using a
well-established academic beat tracker, without creating any runtime
dependency between the two. It is dev-only, never imported by the shipped
application, and not referenced from `requirements.txt`.

## Install

### What was attempted, in order

1. **`pip install madmom`** (PyPI 0.16.1) inside a plain venv — fails
   immediately with `ModuleNotFoundError: No module named 'Cython'`,
   because pip's default build isolation hides the Cython we'd already
   installed in the venv from the isolated build environment `setup.py`
   runs in. Fixed with `pip install --no-build-isolation`.
2. With build isolation off, the build reaches `gcc` and fails compiling
   `madmom/ml/nn/layers.c` with `fatal error: longintrepr.h: No such file
   or directory`. This is a known CPython/Cython interaction: Python 3.11+
   moved that header to `cpython/longintrepr.h`, and the `Cython<3` pin
   we'd started with (0.29.37, the newest 0.29.x release) still emits the
   old `#include "longintrepr.h"` for this file. Fixed by using
   **Cython 3.0.11** instead (deleting the stale pre-generated `.c` files
   first so `cythonize()` regenerates them from the `.pyx`/`.py` sources
   with the newer Cython, rather than reusing the broken ones already
   unpacked from the sdist).
3. With that fixed, the build succeeds, but `import madmom` then fails
   with `ImportError: cannot import name 'MutableSequence' from
   'collections'` — `madmom/processors.py` in the PyPI 0.16.1 release
   imports it from the old `collections` location, removed in Python
   3.10+. **This is what actually forced moving off the PyPI release.**
   Rather than patching an installed package by hand, the fix was to
   build from **madmom's `main` branch on GitHub** instead of the PyPI
   sdist — it already has this fix (`from collections.abc import
   MutableSequence`) along with several years of other Python
   3.10/3.11/3.12-compatibility work the 0.16.1 release (2018) predates.
4. The `main` branch's `madmom/models/` directory is a **git submodule**
   (`https://github.com/CPJKU/madmom_models.git`) rather than files
   committed directly to the main repo (unlike the PyPI sdist, which
   bundles the `.pkl` files directly) — needs
   `git submodule update --init --recursive` before building, or
   `RNNBeatProcessor`/`DBNBeatTrackingProcessor` have no trained weights
   to load.

None of this required a system package manager (`apt`/`dnf`) or `sudo` —
every fix was a pip-installable version pin or a different install source,
all inside the isolated venv, exactly as the task called for.

### Exact steps used (see also `install.sh`, which automates this)

```bash
cd tools/beat-tracker-bench/madmom
python3.11 -m venv .venv                       # madmom needs 3.11 or older; see "Python version" below
.venv/bin/pip install --upgrade pip
.venv/bin/pip install "setuptools<70" "numpy<2" "cython==3.0.11"

# madmom's PyPI 0.16.1 release is broken on modern Python (see above);
# build from the main branch instead, with the pretrained-model submodule.
git clone --depth 1 https://github.com/CPJKU/madmom.git /tmp/madmom_src
git -C /tmp/madmom_src submodule update --init --recursive
find /tmp/madmom_src -name "*.c" -delete       # force regeneration with Cython 3.0.11
.venv/bin/pip install --no-build-isolation /tmp/madmom_src
```

Installed versions in the venv used for this benchmark:

| package    | version                                    |
|------------|---------------------------------------------|
| Python     | 3.11.15                                      |
| numpy      | 1.26.4 (pinned `<2`; madmom uses the deprecated `numpy.get_include()` / old C API) |
| Cython     | 3.0.11 (build-time only; not a runtime import) |
| scipy      | 1.17.1 (pulled in by madmom's own `install_requires`) |
| mido       | 1.3.3 (pulled in by madmom's own `install_requires`) |
| setuptools | 69.5.1 (pinned `<70`; newer setuptools removed the bundled `distutils` shim `madmom`'s `setup.py` needs) |
| madmom     | `0.17.dev0`, from `main` @ `27f032e8947204902c675e5e341a3faf5dc86dae` (2024-08-25) |

### Python version

Use **Python 3.11** (or older), not the system default. This machine's
system Python is 3.14, which is far newer than madmom's build tooling has
ever been exercised against; 3.11 was the newest interpreter here that
built cleanly without further surprises. Fedora ships `python3.11` as an
installable alongside the system default, so no source build was needed —
see `PYTHON_BIN` in `install.sh` if a different interpreter is available
in your environment.

### Quirks / gotchas

- **Build isolation must be off** (`pip install --no-build-isolation`).
  madmom's `setup.py` imports `Cython.Build.cythonize` and `numpy` directly
  at setup time; PEP 517's default isolated build environment can't see
  packages installed in the outer venv, so those imports fail unless the
  outer venv's install directory is exposed to the build.
- **Delete pre-shipped `.c` files before installing from source.** Both
  the PyPI sdist and a fresh git checkout may contain Cython-generated
  `.c` files from whatever Cython version last built them upstream;
  `cythonize()` only regenerates a `.c` file if it's missing or older than
  its `.pyx`/`.py` source, so a stale `.c` file generated with an
  incompatible Cython version can silently get reused and fail to compile
  against the current Python's headers.
- **`RuntimeWarning: divide by zero encountered in log`** from
  `madmom/features/beats_hmm.py` appears once, during this adapter's
  `warm_up()`. It's from priming `DBNBeatTrackingProcessor` with a literal
  `0.0` activation before any real audio has been fed; `log(0)` is
  harmless here (the resulting `-inf` is immediately dominated by the
  transition model) and this adapter suppresses that specific warning
  during warm-up only (see `adapter.py`).
- **`origin='stream', num_frames=1` are required on every `RNNBeatProcessor`
  call**, not just implied by `online=True`. Without them, madmom's default
  offline end-of-signal padding produces several extra boundary frames from
  a single fixed-size window instead of exactly one activation value,
  silently breaking the one-hop-in/one-activation-out cadence this adapter
  depends on. This was caught empirically while building the adapter (see
  the design note at the top of `adapter.py`), not documented anywhere
  obvious in madmom's own docs — the closest reference is the "must be set
  to 'stream'" note in `FramedSignalProcessor`'s docstring.

## Usage

```bash
# Self-testable with no external audio file:
.venv/bin/python run.py --synthetic-click --bpm 120 --duration 30

# Against a real audio file:
.venv/bin/python run.py --audio /path/to/track.wav --out result.json

# Automated self-test (both --bpm 120 and --bpm 90 cases):
.venv/bin/python self_test.py
```

`run.py` writes a JSON report (to `--out <path>`, or stdout by default)
containing every `(t, bpm, confidence)` tick plus a `final_bpm` field.
`confidence` is madmom's own RNN beat-activation value at the most recent
frame (already in `[0, 1]`) — madmom doesn't expose a dedicated confidence
score for the DBN's internal state, so this is used as a documented proxy
rather than always reporting `0.0`. See `adapter.py`'s module docstring for
the full reasoning.

Audio loaded via `--audio` is resampled to madmom's expected 44100 Hz
internally if the source file's rate differs (see `adapter.py`); audio
already at 44100 Hz (including the `--synthetic-click` default) skips that
path entirely and is the most faithful case to benchmark against.

## Self-test results

Run via `.venv/bin/python self_test.py` (synthetic click tracks, 30 s each,
default `--block-size 1024`, sample rate 44100 Hz):

```
PASS  true_bpm= 120.0  final_bpm= 120.00  error= 0.00%
PASS  true_bpm=  90.0  final_bpm=  89.55  error= 0.50%
self-test: all cases within tolerance
```

Both cases lock onto the true tempo well inside the +/-4% tolerance, with
no half/double-time (octave) confusion observed. A 48 kHz synthetic
`.wav` file (100 BPM, exercising the resampling path via `--audio` instead
of `--synthetic-click`) was also spot-checked manually and locked onto
exactly 100.0 BPM; that file was generated and deleted from `/tmp` for the
check and is not part of this tool or the repository.

Caveat: madmom's RNN models were trained on real music, not pure synthetic
click tracks. A clean lock-on here is a wiring/sanity check for this
adapter, not a claim about how madmom performs on real audio in general —
that comparison is the point of the later benchmarking work this adapter
is built for, not this task.

## License

madmom is **dual-licensed** between its code and its pretrained models —
this matters because this adapter loads and runs those pretrained models,
not just the code:

- **Source code** (`.py`, `.pyx`, `.c`, etc.): 2-clause BSD. Copyright
  Department of Computational Perception, Johannes Kepler University Linz,
  and OFAI Vienna. Permissive; no restriction on use here.
- **Pretrained model / data files** (`.pkl`, under `madmom/models/`,
  fetched via the `madmom_models` git submodule during install — see
  "Install" above): **Creative Commons Attribution-NonCommercial-ShareAlike
  4.0 (CC BY-NC-SA 4.0)**. Per madmom's own `LICENSE` file: "If you want to
  include any of these files (or a variation or modification thereof) or
  technology which utilises them in a commercial product, please contact
  Gerhard Widmer... Please note that pickled Processors (i.e. saved
  models) fall into this category."

This is a **non-commercial restriction**, distinct from and stricter than
the BSD code license. `RNNBeatProcessor` and `DBNBeatTrackingProcessor`
both load these pickled models at `warm_up()` time, so any use of this
adapter inherits that restriction. That's acceptable for this task's
purpose — local, dev-only benchmarking, never shipped in the built
application, never distributed — but it means this adapter (or its output)
must not be repurposed into anything commercial, and the model files
themselves must never be committed to this (or any other) repository.

## Isolation

- Everything lives under `tools/beat-tracker-bench/madmom/`; nothing was
  written outside this directory.
- The venv is at `tools/beat-tracker-bench/madmom/.venv`, covered by the
  repository's existing `.venv/` gitignore rule — confirmed with
  `git status --ignored` before finishing this task (shows up as `!!`,
  not `??`).
- `requirements.txt`, `unicornviz/`, `drop-ins/auto-vj-01/`, and
  `drop-ins/training-kit-01/` were not read-modified by this task.
- No audio files (synthetic or real) are committed anywhere in this
  directory; `--synthetic-click` generates its click track in memory at
  run time, and the one `.wav` file used to spot-check the `--audio` path
  during development was written to and deleted from `/tmp`, never this
  repository.

## Interface

`adapter.py` implements the shared benchmarking interface used by sibling
adapters (BTrack / essentia / BeatNet) under `tools/beat-tracker-bench/`:

```python
class ExternalBeatTracker:
    def warm_up(self, sample_rate: int) -> None: ...
    def feed(self, block: np.ndarray, block_start_s: float) -> None: ...

    @property
    def bpm(self) -> float: ...

    @property
    def confidence(self) -> float: ...
```

See `adapter.py`'s module and class docstrings for the internal framing
and state-management details (how live PCM blocks are turned into the
fixed-size causal windows madmom's online RNN/DBN pipeline expects).
