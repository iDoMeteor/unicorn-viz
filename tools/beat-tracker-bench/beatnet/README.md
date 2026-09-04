# BeatNet benchmarking adapter

Dev-only tooling. Wraps [BeatNet](https://github.com/mjhydri/BeatNet)
(CRNN + particle filtering, ISMIR 2021) behind the shared
`ExternalBeatTracker` interface so it can be benchmarked against
unicorn-viz's own in-house beat tracker. This directory is fully
standalone: nothing under `unicornviz/` imports it, it is not installed
into the shipped app's environment, and it is not added to the project's
`requirements.txt`.

"Compatible in intent" here means causal/real-time trackers only. BeatNet
exposes four modes; this adapter drives only **"online" mode**, which runs
the exact same causal algorithm as "realtime" mode but reads a supplied
in-memory array faster than real time instead of pacing to a live clock.
It deliberately never uses BeatNet's mic-capturing **"streaming" mode**
(see "pyaudio stub" below for how that's avoided even at import time).

## License (read this before any use beyond this dev tool)

BeatNet's repository ships a `LICENSE` file containing the **Creative
Commons Attribution 4.0 International Public License (CC BY 4.0)** in
full, and both the GitHub README and the PyPI project badge tag the
project `License: CC BY 4.0`
([badge source](https://github.com/mjhydri/BeatNet/blob/main/README.md),
[LICENSE file](https://github.com/mjhydri/BeatNet/blob/main/LICENSE)).
This is **not** the "research/non-commercial only" framing sometimes
attached to BeatNet elsewhere -- CC BY 4.0 is a permissive license that
allows commercial use, but it is a *content* license (designed for
creative works, not source code) whose core requirement is attribution:
"You must give appropriate credit, provide a link to the license, and
indicate if changes were made." It carries no explicit patent grant and
none of the warranty/liability language typical of software licenses
(MIT, Apache-2.0, BSD). Applying CC BY 4.0 to a Python package is unusual
and is the license authors' own explicit stated position (Creative
Commons recommends against using its licenses for software), but it is
what the repository actually declares, so it's what governs use of
BeatNet's code and pretrained model weights.

**Practical takeaway:** dev-only benchmarking use (this tool) is fine.
Before BeatNet's code, weights, or output are used for anything beyond
this comparison -- shipped in the app, redistributed, used to generate
training data that leaves this dev context -- confirm attribution is
given as CC BY 4.0 requires, and flag the license's software-atypical
terms (no patent grant, ambiguous "Adapted Material" scope for a
CRNN model's weights) to the owner for an explicit decision.

## Install steps actually used

```bash
cd tools/beat-tracker-bench/beatnet
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install cython numpy
pip install --no-build-isolation madmom   # madmom's setup.py needs Cython
                                           # visible outside pip's isolated
                                           # build env; --no-build-isolation
                                           # lets it see the cython/numpy
                                           # already installed above.
pip install librosa
pip install BeatNet
```

This is a normal `pip install` chain into an isolated venv -- no `apt`,
`dnf`, or `sudo` was used or needed. `pip install BeatNet` pulled in
`torch` (2.14.0, including its bundled CUDA 13 wheels even though this
machine has no GPU -- that's simply what the default PyPI `torch` wheel
ships; it runs fine on CPU), `madmom`, `librosa`, `matplotlib`, and
BeatNet's three pretrained CRNN weight files (`models/model_1_weights.pt`,
`model_2_weights.pt`, `model_3_weights.pt`, bundled inside the `BeatNet`
wheel itself via `include_package_data=True` -- no separate download step,
no untrusted third-party host).

Total venv size is several GB, dominated by torch's CUDA dependencies.
That is expected and confined entirely to `.venv/`, which the repo's
existing `.venv/` `.gitignore` rule already covers (verified with
`git status` -- nothing under this `.venv/` appears as untracked).

### Compatibility patches required (all applied only inside this isolated venv)

BeatNet 1.1.1 (the latest release on PyPI at the time of writing; note
the GitHub `main` branch's `setup.py` already declares `version="1.2.0"`
for an unreleased next version) was published against older NumPy /
setuptools, and needed four fixes to actually import and run on this
machine's Python 3.11 + NumPy 2.4.6 + setuptools 84 stack. None of these
required a system package install; all were applied inside
`.venv/lib64/python3.11/site-packages/`:

1. **`pkg_resources` missing.** `setuptools` 84 (the version `pip install
   --upgrade setuptools` picked up) no longer bundles `pkg_resources`,
   which `madmom/__init__.py` imports unconditionally. Fixed by pinning
   `pip install "setuptools<81"` (the last line before `pkg_resources`
   was slated for removal).
2. **`np.float` / `np.int` removed.** `madmom/io/__init__.py` uses the
   long-removed NumPy aliases. This is the *exact* fix BeatNet's own
   README documents under "Note on madmom compatibility": a
   `sitecustomize.py` dropped into the venv's site-packages restoring
   `np.float = np.float64` and `np.int = np.int_` if absent.
3. **`np.in1d` removed.** Not mentioned in BeatNet's README (which
   predates NumPy 2.4), but the same category of issue:
   `BeatNet/particle_filtering_cascade.py` calls `np.in1d`, deprecated
   since NumPy 1.20 in favor of `np.isin` and fully removed in the NumPy
   version installed here. Same `sitecustomize.py` adds
   `np.in1d = np.isin` if absent (`in1d`/`isin` have identical
   `(ar1, ar2) -> bool array` semantics, so this is a direct,
   behavior-preserving restore, not a functional change).
4. **`pyaudio` missing, and not installable here.** See below.

The full `sitecustomize.py` lives at
`.venv/lib64/python3.11/site-packages/sitecustomize.py` with inline
comments explaining each shim.

### `pyaudio` stub (why, and what it does)

`BeatNet/BeatNet.py` does an unconditional module-level `import pyaudio`
(line 14), even though pyaudio is only ever touched inside BeatNet's
microphone-based **"stream"** mode
(`pyaudio.PyAudio().open(...)`, line 84). This adapter never uses
"stream" mode. Installing the real `pyaudio` package failed here because
it needs to compile against the system PortAudio headers
(`portaudio.h: No such file or directory`), which are not present and
would require a system package manager install (`dnf install
portaudio-devel` or similar) that this tool is not permitted to run.

Instead, `.venv/lib64/python3.11/site-packages/pyaudio.py` is a ~20-line
stub module (not the real PyPI package) that defines just enough
(`pyaudio.paFloat32`, `pyaudio.PyAudio`) to satisfy the import. Its
`PyAudio.open()` raises `NotImplementedError` if ever called, so if
"stream" mode were accidentally exercised it would fail loudly rather
than silently doing nothing or touching a real microphone. This adapter's
own code (`adapter.py`) never constructs `BeatNet(..., mode='stream')`,
so this code path is never reached in normal use.

## Interface

`adapter.py` implements the shared benchmarking interface:

```python
class ExternalBeatTracker:
    def warm_up(self, sample_rate: int) -> None: ...
    def feed(self, block: np.ndarray, block_start_s: float) -> None: ...
    @property
    def bpm(self) -> float: ...
    @property
    def confidence(self) -> float: ...  # always 0.0 -- BeatNet exposes none
```

### Why buffer-and-periodically-recompute instead of true incremental feeding

BeatNet's public API (`BeatNet.process(audio_path)`) takes a whole
in-memory array or file path per call -- there is no documented way to
push one small PCM block at a time into a persistent causal state. Even
in "online" mode, each call extracts CRNN activations for the entire
given array in one forward pass and decodes them with a particle filter
that (per BeatNet's own `process()` implementation) starts fresh for that
call.

This adapter takes the fallback explicitly allowed by the task brief:
`feed()` appends each block to an internal buffer, and every
`recompute_stride_s` seconds of *newly* buffered audio (default 0.5s,
after a `min_analysis_s` warm-up floor of 2.0s), it re-runs BeatNet's
online algorithm -- CRNN activation extraction plus a freshly reset
particle filter (`particle_filter_cascade`) -- over the **entire buffer
collected so far**, exactly as BeatNet's own `process()` would do if
handed that buffer as a brand-new file. This preserves BeatNet's own
causality guarantee (it never sees audio beyond "now"), but has two
fairness caveats worth keeping in mind when comparing against a tracker
that updates every single block:

- **Redundant reprocessing.** Every recompute reprocesses all earlier
  audio, not just the new increment, so wall-clock cost grows
  super-linearly with track length -- this is fine for a dev benchmarking
  run but is not how a real streaming deployment of BeatNet would be
  built.
- **Update cadence and tail lag.** The running BPM only changes once per
  `recompute_stride_s` (a plateau of identical values between recomputes
  in the tick series is expected, not a bug), and the very last
  `<recompute_stride_s` seconds of fed audio never triggers a final
  recompute, so the reported `final_bpm` can lag the true end of the
  input by up to `recompute_stride_s` seconds. In both 30-second
  self-tests below this made no observable difference to the final
  estimate.

`feed()` internally resamples each block from the sample rate passed to
`warm_up()` to BeatNet's fixed 22050 Hz operating rate via
`librosa.resample` if they differ.

`confidence` is hardcoded to `0.0`: BeatNet's public output from "online"
+ "PF" mode is a `(num_beats, 2)` array of `(time_s, beat_number)` rows
with no per-beat or per-call confidence score.

## CLI usage

```bash
# Synthetic self-test, no external audio file needed:
.venv/bin/python run.py --synthetic-click --bpm 120 --duration 30 --out out.json

# Real audio file:
.venv/bin/python run.py --audio /path/to/track.wav --out out.json
```

`--synthetic-click` generates, in memory with numpy, a periodic click
track: a short (15ms) exponentially-decaying 1800 Hz tone burst at every
beat interval (`60 / bpm` seconds), mixed over a low-level Gaussian noise
floor. No audio files are read, generated on disk, or committed anywhere
in this repo.

Blocks are streamed through the adapter in a plain `for` loop at
`--block-size` samples (default 1024, no wall-clock pacing/sleeping) and
every tick's `(t, bpm, confidence)` is recorded. Output JSON has the full
tick series plus `final_bpm` / `final_confidence` / `elapsed_wall_s`.

## Self-test results

Run on this machine (CPU-only inference, `device='cpu'`):

| True BPM | Duration | `final_bpm` | Error | Wall time |
|---:|---:|---:|---:|---:|
| 120 | 30s | 120.00 | 0.00% | 49.9s |
| 100 | 30s | 100.00 | -0.00% | 72.0s |

Both land exactly on the true synthetic BPM, well inside the requested
+/-4% tolerance.

**Caveat, reported honestly rather than hidden:** the *early* part of
each run is noisy -- before the particle filter has enough audio to
settle, intermediate tick values pass through half-time and
double/near-double-time hypotheses (e.g. the 120 BPM run's tick series
transiently reads 80.0, 115.38, and 117.65 before locking to 120.0; the
100 BPM run transiently reads 50.85 -- essentially half-time -- and
181.82/187.5 -- near double-time -- before locking to 100.0). This is
expected behavior for a particle-filter tempo tracker warming up on a
short buffer and is not specific to this adapter's implementation; it
does mean a naive "read `bpm` at an arbitrary early timestamp" comparison
against the in-house tracker would be unfair to BeatNet during its first
few seconds. BeatNet is also a CRNN trained on real mastered music, not
pure synthetic clicks, so the fact that it locks on cleanly here is a
reasonably favorable case rather than proof of robustness on harder real
audio -- that comparison is exactly what this tool exists to enable next,
against real tracks and against the in-house tracker.

## Known deviations / things to double check before trusting comparisons

- BeatNet was installed as version **1.1.1** (latest PyPI release); the
  GitHub `main` branch is ahead at `1.2.0` with an added training
  pipeline not relevant here. The "online" mode API used by this adapter
  is unchanged between the two per the README.
- Pretrained model `1` (GTZAN-trained) was used by default
  (`adapter.py`'s `_DEFAULT_MODEL`); BeatNet ships two alternatives
  (`2` = Ballroom, `3` = Rock_corpus) that may perform differently on
  specific genres -- worth sweeping if BeatNet's numbers look off for a
  particular test track.
- `recompute_stride_s` (0.5s) and `min_analysis_s` (2.0s) are this
  adapter's own tuning knobs, not part of BeatNet itself -- see the
  fairness caveats above before reading too much into fast/early ticks.
