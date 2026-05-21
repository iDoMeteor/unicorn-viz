# Auto VJ Beat Detection — Full Rebuild Plan (2026-05-21)

> Solutions planning document for the team taking over the beat-detection
> rewrite in `unicorn-viz`. Read this end-to-end before writing code.
>
> Companion documents:
> - `docs/debug/auto-vj-handoff-2026-05-21.md` — deep failure-mode analysis
> - `docs/debug/auto-vj-drop-detection-debug-2026-05-21.md` — running debug log
>
> If anything below conflicts with `.github/copilot-instructions.md`, the
> repo coding standards win.

---

## 1. Mission

Replace the current "spectral-flux + IOI-median" beat detector with a
proper real-time tempo tracker that:

1. Produces accurate BPM on the **musical pulse** of varied source material
   (electronic, rock, pop, ambient, breakbeat, half-time, double-time).
2. Stays **phase-locked** to that pulse so downbeats line up with bars.
3. Exposes a **calibrated confidence** signal that the director can trust.
4. Survives FPS variation, audio block jitter, and silent gaps without
   silently corrupting state.
5. Can be **measured offline** against ground-truth audio so progress is
   provable.

Non-goals for this rewrite:

- Replacing the audio capture layer.
- Changing the Auto VJ state machine (it already works well).
- Adding ML-based beat tracking models (out of scope; keep this dependency-light).

---

## 2. Background You Must Read First

Before changing any code, read in order:

1. `docs/debug/auto-vj-handoff-2026-05-21.md`
   - Failure mode evidence (multi-session telemetry).
   - 8 structural root-cause hypotheses (H1–H8). The plan below maps each
     phase back to those hypotheses.
2. `unicornviz/audio/analyzer.py`
   - Current spectral-flux onset detector.
3. `unicornviz/audio/manager.py`
   - Audio block delivery, `data.beat` level-vs-event semantics (H6).
4. `drop-ins/auto-vj-01/beat_grid.py`
   - Current IOI-based tempo estimator.
5. `unicornviz/effects/base.py` (`AudioData` class)
   - Public contract consumed by every effect — **must remain compatible**.
6. `drop-ins/auto-vj-01/auto_vj.py`
   - Director side that reads `grid.bpm`, `grid.confidence`,
     `grid.is_beat`, `grid.is_downbeat`, `grid.beat_phase`.
7. `tools/analyze_autovj_log.py`
   - Postmortem analyzer that consumes JSONL detector logs.

You should also re-read the relevant sections of
`.github/copilot-instructions.md`:

- "Effect Conventions" (no blocking I/O in render path)
- "Performance Constraints" (16.67 ms frame budget; pre-allocate numpy in
  `_init()`; no allocations in the hot path)
- "Drop-In Independence Rules" (core never hard-imports a drop-in)
- "Public Runtime Surface Rules"
- "config.toml Editing Policy" (do not silently change user settings)

---

## 3. Architecture Vision (Target End State)

```
                   ┌─────────────────────────────┐
PipeWire/ALSA ───▶ │ AudioCapture (existing)     │
                   └─────────────┬───────────────┘
                                 │ float32 block
                                 ▼
                   ┌─────────────────────────────┐
                   │ Analyzer                    │
                   │ - FFT + per-band energy     │
                   │ - spectral-flux onset env.  │  ◀── (R4) time-based window
                   │ - resample env. to 100 Hz   │  ◀── (R1) fixed grid
                   │ - emit onset *events*       │  ◀── (R5) queued, not level
                   │ - bass/snare sub-envelopes  │  ◀── (R6) downbeat features
                   └─────────────┬───────────────┘
                                 │ AudioData (effects use this)
                                 │ OnsetEvent[] (BeatTracker uses this)
                                 │ envelope_buffer (BeatTracker uses this)
                                 ▼
                   ┌─────────────────────────────┐
                   │ BeatTracker (rewrite of     │
                   │ BeatGridTracker)            │
                   │ - autocorrelation tempogram │  ◀── (R1)
                   │ - tempo prior + peak picker │  ◀── (R1)
                   │ - phase-locked oscillator   │  ◀── (R2)
                   │ - tempo-aware refractory    │  ◀── (R3)
                   │ - downbeat by bass/snare    │  ◀── (R6)
                   │ - calibrated confidence     │  ◀── (R1/R2)
                   └─────────────┬───────────────┘
                                 │ bpm, confidence, beat_phase,
                                 │ is_beat, is_downbeat
                                 ▼
                   ┌─────────────────────────────┐
                   │ Auto VJ Director            │  (unchanged contract)
                   └─────────────────────────────┘

Offline harness (R7):  WAV/MP3 + known_bpm  ──▶  same Analyzer+BeatTracker
                                                 ──▶  metrics report
```

Effects continue to consume `AudioData` exactly as today. The contract
extension is internal: Analyzer exposes a structured onset stream and a
sampled envelope buffer for the BeatTracker, alongside the existing
`AudioData` snapshot.

---

## 4. Phased Plan

Phases are ordered so each one delivers value alone, and so that later
phases can be measured against earlier baselines using the harness.

Recommended ordering:

| Phase | Title                                | Maps to | Risk   | Ship gate |
|-------|--------------------------------------|---------|--------|-----------|
| P0    | Offline ground-truth harness         | R7      | low    | required first |
| P1    | Event-based onset stream             | R5, H6  | low    | unit-tested |
| P2    | Time-based onset envelope + threshold| R4, H4, H5 | low | harness improves |
| P3    | Tempo-aware adaptive refractory      | R3, H1  | low    | harness improves |
| P4    | Autocorrelation tempo estimator      | R1, H1, H3 | medium | harness improves significantly |
| P5    | Phase-locked oscillator + downbeat   | R2, H2, H7 | medium | harness shows phase coherence |
| P6    | Downbeat detection from bass/snare   | R6      | medium | optional polish |
| P7    | Confidence calibration + telemetry   | R1/R2 outputs | low | harness shows ECE |

Each phase must:

1. Land behind a feature flag in `config.toml` (`[beat_tracker] engine =
   "legacy" | "v2"` etc.) so we can A/B against the legacy detector.
2. Be measured by the harness before merge.
3. Preserve the public `BeatGridTracker` properties currently consumed by
   Auto VJ (`bpm`, `confidence`, `beat_phase`, `is_beat`, `is_downbeat`,
   `energy`, `energy_slope`, `drop_score`, `schedule_for_next_downbeat`).

---

## 5. Phase Detail

Each phase has the same structure:

- **Theory** — why this works.
- **Design** — what to build.
- **Code touchpoints** — files to change.
- **Skeleton** — illustrative code shape (not final).
- **Validation** — how the harness should prove it works.
- **Acceptance criteria** — what must be true to merge.

### Phase 0 — Offline Ground-Truth Harness (R7)

**Theory.** You cannot iterate on tempo estimation without measurement.
Live listening produces opinions, not numbers. Every other phase depends
on this.

**Design.**

- New `tools/bpm_eval.py` that:
  - Accepts a corpus directory containing audio files plus per-file
    ground truth (BPM, optional downbeat offsets).
  - Ground truth via sidecar JSON next to each audio file
    (`track.wav` + `track.bpm.json`), with schema
    `{ "bpm": 120.0, "downbeat_offset_s": 0.45 }`. `downbeat_offset_s` is
    optional.
  - Streams each file through the production Analyzer + BeatTracker in a
    deterministic offline loop (no real-time audio).
  - Records per-file:
    - time-to-lock (seconds until BPM within ±2% of truth)
    - absolute BPM error
    - octave/harmonic error (predicted / truth nearest in
      {1/3, 1/2, 2/3, 3/4, 1, 4/3, 3/2, 2, 3})
    - phase coherence (if downbeat truth available)
    - confidence at lock vs error (for calibration)
  - Emits a Markdown report `tools/bpm_eval_report.md` and a JSON dump.
- Corpus living under `assets/audio/bpm_eval/` (gitignored by default for
  size). A small CC-licensed seed set should be committed (3–5 short clips
  across genres / tempos).

**Code touchpoints.**

- `tools/bpm_eval.py` (new)
- `tools/bpm_eval_seed_corpus.md` (new — list of seed files + provenance)
- `.gitignore` update for `assets/audio/bpm_eval/` (keep seed set explicit)
- A `make` / shell entry point: `tools/run_bpm_eval.sh`

**Skeleton.**

```python
# tools/bpm_eval.py
def evaluate_file(audio_path: Path, truth: dict, cfg: dict) -> dict:
    pcm, sr = load_audio_mono(audio_path, target_sr=48000)
    analyzer = Analyzer(...)
    tracker = BeatTracker(...)
    bpm_track = []
    block_size = 1024
    for block_start in range(0, len(pcm) - block_size, block_size):
        block = pcm[block_start:block_start + block_size]
        dt = block_size / sr
        audio = analyzer.process(block)
        tracker.update(dt, audio, onsets=analyzer.drain_onsets())
        bpm_track.append((block_start / sr, tracker.bpm, tracker.confidence))
    return compute_metrics(bpm_track, truth)
```

**Validation.**

- Run on seed corpus.
- Snapshot output as the *baseline* before any beat-detection changes.
- All subsequent phases compare against this baseline.

**Acceptance criteria.**

- Harness reproduces a stable per-file metric set across two consecutive runs.
- Baseline numbers checked into repo (`tools/bpm_eval_baseline.json`).
- Documented in `docs/developer-guide.md` under "Beat tracker evaluation".

---

### Phase 1 — Event-Based Onset Stream (R5, H6)

**Theory.** Today `audio.beat` is a per-frame *level* (`0.0` or `1.0`)
that depends on whether a new audio block was available that frame. Fast
render frames can miss onsets entirely; slow frames can double-count or
mask them. This silently corrupts the IOI stream.

**Design.**

- Analyzer keeps emitting `data.beat` for backward effect compatibility.
- Analyzer additionally maintains an internal **onset event queue**: a
  bounded deque of `(t_monotonic, strength)` tuples written when the
  threshold is crossed.
- Analyzer exposes:
  - `drain_onsets() -> list[OnsetEvent]` — pops and returns all queued
    events.
  - `peek_onsets()` — for the harness/diagnostics.
- BeatTracker consumes `drain_onsets()` each update, *not*
  `audio.beat`.
- Queue is bounded (e.g. 256 events). On overflow, log a warning and drop
  the oldest.

**Code touchpoints.**

- `unicornviz/audio/analyzer.py`
- `unicornviz/audio/manager.py` (forward `drain_onsets()` access, or
  passthrough on `AudioData`)
- `drop-ins/auto-vj-01/beat_grid.py` (new consumer path)

**Skeleton.**

```python
# analyzer.py
from dataclasses import dataclass

@dataclass(frozen=True)
class OnsetEvent:
    t: float       # time.monotonic() at detection
    strength: float  # z-score above flux mean

class Analyzer:
    def __init__(...):
        self._onset_queue: deque[OnsetEvent] = deque(maxlen=256)

    def process(self, pcm):
        ...
        if onset_detected:
            self._onset_queue.append(OnsetEvent(now, strength))
            data.beat = 1.0
        return data

    def drain_onsets(self) -> list[OnsetEvent]:
        events = list(self._onset_queue)
        self._onset_queue.clear()
        return events
```

```python
# beat_grid.py (transitional)
def update(self, dt, audio, onsets=None):
    if onsets is None:
        # legacy fallback: derive a synthetic event from audio.beat
        if audio.beat >= self._beat_threshold:
            onsets = [OnsetEvent(time.monotonic(), 1.0)]
        else:
            onsets = []
    for ev in onsets:
        self._ingest_onset(ev)
    ...
```

**Validation.**

- Unit test: drive analyzer with synthetic PCM (impulse train at known
  IOI), confirm exactly N onsets recovered with timestamps matching
  expected within a small tolerance.
- Harness: BPM error should not regress; jitter (BPM frame-to-frame stddev)
  should drop because no events are missed.

**Acceptance criteria.**

- Zero detected onsets lost across a 60-second synthetic test.
- Existing `data.beat` level kept (effects unaffected).
- Legacy path still works when `onsets=None`.

---

### Phase 2 — Time-Based Onset Envelope + Threshold (R4, H4, H5)

**Theory.** Onset detection today uses a fixed-length sample ring
(`_ONSET_WINDOW = 43`) and a `mean + 1.25*std` adaptive threshold. Under
steady electronic material the std collapses, the threshold becomes
trivially crossable, and false sub-beat onsets enter the stream. The
sample-count window also drifts in real time with FPS.

**Design.**

- Build the onset envelope on a **fixed time grid** (e.g. 100 Hz internal
  rate). On each Analyzer call, resample / accumulate the latest flux
  value into the envelope grid using elapsed `dt`.
- Maintain a **time-bounded** ring (e.g. last 1.5 s of envelope).
- Adaptive threshold becomes `median + k * MAD` (median-absolute-deviation)
  rather than `mean + std`. MAD is robust to flux spikes.
- Add a **minimum absolute floor** to the threshold so silence + noise do
  not yield a parade of weak onsets.
- Keep peak-pick semantics: an onset fires when the new envelope sample is
  a local max *and* exceeds the adaptive threshold.

**Code touchpoints.**

- `unicornviz/audio/analyzer.py`

**Skeleton.**

```python
ENV_RATE = 100.0
ENV_WINDOW_S = 1.5
ENV_LEN = int(ENV_RATE * ENV_WINDOW_S)

class Analyzer:
    def __init__(...):
        self._env_buf = np.zeros(ENV_LEN, dtype=np.float32)
        self._env_write_idx = 0
        self._env_t_acc = 0.0

    def _push_envelope(self, dt: float, flux_value: float) -> None:
        self._env_t_acc += dt
        step = 1.0 / ENV_RATE
        while self._env_t_acc >= step:
            self._env_t_acc -= step
            self._env_buf[self._env_write_idx] = flux_value
            self._env_write_idx = (self._env_write_idx + 1) % ENV_LEN

    def _onset_threshold(self) -> float:
        med = np.median(self._env_buf)
        mad = np.median(np.abs(self._env_buf - med)) + 1e-6
        return med + 1.8 * mad + 0.02  # floor prevents silence triggers
```

**Validation.**

- Harness: false-onset rate on a silence segment must drop to ~0.
- Harness: per-file BPM error should not regress; on dense electronic
  material, the median IOI distribution should shift toward the musical
  pulse rather than the half-beat.

**Acceptance criteria.**

- Per-file onset density on silence < 0.5 Hz.
- No regression in baseline BPM error from the harness.

---

### Phase 3 — Tempo-Aware Adaptive Refractory (R3, H1)

**Theory.** Once any BPM estimate exists, the analyzer should refuse to
fire onsets faster than ~0.7× the beat period. This single change starves
the sub-beat IOI pollution that is the proximate cause of the 155-lane
lock.

**Design.**

- Analyzer accepts a soft hint: `set_expected_bpm(bpm: float,
  confidence: float)`. Called by BeatTracker each frame.
- Internal refractory:
  - if `bpm > 0 and confidence >= 0.5`: refractory =
    `clip(0.70 * 60.0 / bpm, 0.18, 0.50)` seconds.
  - else: refractory = current 0.10–0.20 s heuristic.
- Refractory acts as a hard gate after onset firing.

**Code touchpoints.**

- `unicornviz/audio/analyzer.py`
- `drop-ins/auto-vj-01/beat_grid.py` (call `set_expected_bpm`)

**Skeleton.**

```python
class Analyzer:
    def set_expected_bpm(self, bpm: float, confidence: float) -> None:
        if bpm > 0 and confidence >= 0.5:
            self._refractory_s = float(np.clip(0.70 * 60.0 / bpm, 0.18, 0.50))
        else:
            self._refractory_s = None  # fall back to dynamic cooldown
```

**Validation.**

- Harness: on tracks where ground truth BPM ≤ 110, the onset rate after
  10 seconds of playback should approach `bpm / 60`, not 2–3× that value.
- BPM lane occupancy in `tools/bpm_eval_report.md` should show meaningful
  population below 120 BPM on slow tracks.

**Acceptance criteria.**

- Per-file octave/harmonic error rate at least 30% lower than baseline.
- No regression on tracks with ground truth BPM ≥ 140.

---

### Phase 4 — Autocorrelation Tempo Estimator (R1, H1, H3)

**Theory.** Autocorrelation of the onset envelope is the standard,
robust foundation for tempo estimation. Peaks at lag τ correspond to
periodicities of period τ. Combined with a perceptual tempo prior, this
replaces median-IOI shopping with a real estimator.

**Design.**

- New `BeatTracker` class (rewrite of `BeatGridTracker`):
  - Maintains a long onset envelope (e.g. 8 s at 100 Hz → 800 samples).
  - Each update: compute autocorrelation across lag range corresponding
    to 60–200 BPM (lags ≈ 0.30–1.00 s).
  - Multiply by a **perceptual prior**: Gaussian over BPM with
    `mu = 120`, `sigma = 28`. (Configurable; profile-aware in P7.)
  - Pick the top-K peaks. Score each by `acf_value * prior(bpm)`.
  - Resolve octave ambiguity by checking if 2x/3x candidates are within
    a tolerance of comparable scoring; if so prefer the slower one
    (octave-down bias: humans tend to track slower pulses).
- Smooth the chosen BPM with a slow EMA only after octave resolution.
- Replace the entire `_estimate_bpm` block in current `beat_grid.py`.

**Code touchpoints.**

- `drop-ins/auto-vj-01/beat_grid.py` (substantial rewrite, hidden behind
  the feature flag).

**Skeleton.**

```python
class BeatTracker:
    BPM_MIN, BPM_MAX = 60.0, 200.0
    PRIOR_MU, PRIOR_SIGMA = 120.0, 28.0

    def _estimate_tempo(self) -> tuple[float, float]:
        env = self._envelope_buffer()  # 800 samples @ 100Hz
        env = env - env.mean()
        # Limit to positive lags inside BPM range
        lag_min = int(60.0 / self.BPM_MAX * 100)  # ~30
        lag_max = int(60.0 / self.BPM_MIN * 100)  # ~100
        acf = np.correlate(env, env, mode='full')
        acf = acf[len(env)-1:]  # zero lag at 0
        acf = acf[lag_min:lag_max+1]
        # Convert each lag to BPM and weight by prior
        lags = np.arange(lag_min, lag_max+1)
        bpms = 60.0 / (lags / 100.0)
        prior = np.exp(-0.5 * ((bpms - self.PRIOR_MU) / self.PRIOR_SIGMA) ** 2)
        score = np.clip(acf, 0.0, None) * prior
        peak_idx = int(np.argmax(score))
        best_bpm = float(bpms[peak_idx])
        # Octave-down preference
        for fold in (0.5, 2.0/3.0):
            target_bpm = best_bpm * fold
            if target_bpm < self.BPM_MIN: continue
            target_lag = int(round(60.0 / target_bpm * 100))
            if target_lag < lag_min or target_lag > lag_max: continue
            j = target_lag - lag_min
            if score[j] >= 0.85 * score[peak_idx]:
                best_bpm = target_bpm
                peak_idx = j
        conf = float(score[peak_idx] / (score.sum() + 1e-9))
        return best_bpm, conf
```

**Validation.**

- Harness must show **at least 50% reduction in median BPM error** vs
  baseline on the seed corpus.
- The 155-BPM lane bias visible in current telemetry must disappear on a
  varied corpus.

**Acceptance criteria.**

- All seed-corpus tracks within ±3 BPM at lock.
- No track shows persistent harmonic error (predicted bpm /
  ground-truth bpm not in {0.99 – 1.01}) after 10 s.

---

### Phase 5 — Phase-Locked Oscillator + Bar Phase (R2, H2, H7)

**Theory.** Even with the right tempo, the system needs to know *where*
the beats are. A phase-locked oscillator running at the estimated tempo
that snaps to onsets within a tolerance window provides the beat grid
and naturally rejects sub-beat noise.

**Design.**

- Maintain `phase ∈ [0, 1)` advancing at `bpm / 60` Hz per second.
- Each ingested onset:
  - if `|phase - 0| < 0.18 or |phase - 1| < 0.18`: treat as on-beat,
    nudge phase toward 0 by a small fraction (e.g. 0.25 of the error).
  - else: ignore for phase update (do not desync to sub-beat onsets).
- `is_beat` fires for one frame whenever phase wraps past 0.
- `is_downbeat` fires every 4th `is_beat`, with `bar_phase` advanced and
  reset on a clean bar boundary (Phase 6 improves this with spectral
  downbeat detection).
- `beat_phase` is the oscillator phase directly (replaces interpolation
  from last onset).
- Confidence becomes **phase coherence**: rolling fraction of onsets that
  landed inside the tolerance window over the last N onsets.

**Code touchpoints.**

- `drop-ins/auto-vj-01/beat_grid.py`

**Skeleton.**

```python
class BeatTracker:
    def _advance_phase(self, dt: float) -> None:
        if self._bpm <= 0: return
        self._phase += dt * (self._bpm / 60.0)
        if self._phase >= 1.0:
            self._phase -= 1.0
            self._is_beat = True
            self._bar_beat_count = (self._bar_beat_count + 1) % 4
            self._is_downbeat = self._bar_beat_count == 0
        else:
            self._is_beat = False
            self._is_downbeat = False

    def _absorb_onset(self, ev: OnsetEvent) -> None:
        err = self._phase if self._phase < 0.5 else self._phase - 1.0
        if abs(err) <= 0.18:
            self._phase -= 0.25 * err
            self._phase_hits.append(1)
        else:
            self._phase_hits.append(0)
        self._confidence = float(np.mean(self._phase_hits))
```

**Validation.**

- Harness with downbeat ground truth: measure
  `phase_offset_at_downbeat_s`. Target |offset| < 50 ms.
- BPM jitter (frame-to-frame stddev) should drop further because phase
  drives `is_beat`, not raw onset events.

**Acceptance criteria.**

- Phase coherence ≥ 0.7 on majority of seed-corpus tracks at steady state.
- `bar_phase_error_s` median < 80 ms on tracks with downbeat truth.

---

### Phase 6 — Downbeat Detection from Bass/Snare (R6)

**Theory.** Mod-4 counting cannot identify which of the four beats is
"1". A simple spectral cue does: kick energy on the downbeat, snare/clap
energy on 2 and 4 (in 4/4). Cross-correlating beat-aligned bass-flux
against a downbeat template gives the bar phase.

**Design.**

- Analyzer additionally emits per-frame `bass_flux` and `mid_flux`
  (already computable from `_flux_delta * _flux_weights[bass_slice]`).
- BeatTracker keeps a rolling per-beat history (e.g. last 16 beats) of
  `(bass_flux_at_beat, mid_flux_at_beat)`.
- Choose downbeat offset `k ∈ {0,1,2,3}` that maximizes:
  `sum_{i} bass_at_beat[i] * (1 if (i-k) % 4 == 0 else -0.25)`
- Snap `_bar_beat_count` so beat `k` becomes downbeat. Only correct when
  the score margin is meaningful (e.g. > 1.4× second-best).

**Code touchpoints.**

- `unicornviz/audio/analyzer.py` (expose sub-band flux on `AudioData`)
- `drop-ins/auto-vj-01/beat_grid.py`

**Validation.**

- Harness with downbeat truth: bar-phase correctness rate ≥ 85%.

**Acceptance criteria.**

- Improvement over P5 mod-4 baseline on downbeat-labeled tracks.
- No regression on tracks without strong kick/snare differentiation
  (must fall back to P5 behavior, not produce worse phase).

---

### Phase 7 — Confidence Calibration + Telemetry (R1/R2)

**Theory.** Director logic gates on `confidence`. If confidence is
miscalibrated (e.g. 0.85 confidence at 30% BPM accuracy) the director
makes bad decisions. The harness can produce a **reliability diagram**
and we can calibrate confidence to actual error rates.

**Design.**

- Harness computes Expected Calibration Error (ECE) over the corpus.
- BeatTracker exposes raw signals: phase coherence, autocorrelation peak
  ratio, tempo prior weight at chosen BPM.
- Combine into final `confidence` via a small monotonic mapping
  (e.g. weighted geometric mean), then **fit a temperature scaling**
  parameter from the harness so confidence approximates P(error ≤ 2 BPM).
- Extend `detector_tick` log to include the raw component signals so
  later analysis can refine the mapping.

**Code touchpoints.**

- `drop-ins/auto-vj-01/beat_grid.py`
- `drop-ins/auto-vj-01/auto_vj.py` (detector telemetry payload)
- `tools/analyze_autovj_log.py` (read new fields)
- `tools/bpm_eval.py` (ECE metric)

**Validation.**

- Harness: ECE ≤ 0.10 across corpus.

**Acceptance criteria.**

- Director confidence gating in `auto_vj.py` no longer needs ad-hoc
  thresholds; defaults align with calibrated probabilities (e.g. 0.7
  means "70% chance BPM error ≤ 2").

---

## 6. Public Contract & Compatibility

The following symbols **must remain present and semantically compatible**
for Auto VJ and effects to keep working:

- `BeatGridTracker` (alias `BeatTracker` either replaces it or is exposed
  via a thin shim):
  - `update(dt, audio, onsets=None) -> None`
  - properties: `bpm`, `confidence`, `beat_phase`, `is_beat`, `is_downbeat`,
    `energy`, `energy_slope`, `drop_score`
  - methods: `schedule_for_next_downbeat(cb)`, `clear_pending()`
- `AudioData`:
  - existing `bass`, `mid`, `treble`, `beat`, `bpm`, `fft`, `waveform`
    fields unchanged in semantics.
  - optional additions (`bass_flux`, `mid_flux`) must default to `0.0`
    when unset; effects should not need to opt in.
- `unicornviz.audio.analyzer.Analyzer`:
  - existing `process(pcm) -> AudioData` unchanged.
  - new methods (`drain_onsets`, `set_expected_bpm`) are additive.

Drop-in independence rules: the core analyzer must not import from
`drop-ins/`. Communication remains one-way (`Analyzer` produces data,
`BeatTracker` consumes it).

---

## 7. Configuration

Add a single new section to `config.toml` (commented-out by default,
per the editing policy):

```toml
# [beat_tracker]
# engine = "v2"            # "legacy" | "v2"
# bpm_min = 60.0
# bpm_max = 200.0
# prior_mu = 120.0
# prior_sigma = 28.0
# phase_tolerance = 0.18
# refractory_factor = 0.70
# envelope_seconds = 8.0
```

Do not change any existing values in the user's `config.toml`. Adding a
new commented section is allowed by the editing policy.

---

## 8. Testing & Validation Strategy

1. **Unit tests** (new, under `tests/audio/`):
   - synthetic impulse trains at known BPM → tempo estimator output
   - silence input → no onsets, no spurious BPM updates
   - tempo step change (e.g. 100 → 140 BPM mid-clip) → recovery time
     measured
2. **Offline harness** (Phase 0):
   - per-file metrics
   - corpus-level summary
   - regression gate: any phase merge must not worsen median BPM error
3. **Live validation**:
   - run for at least 30 minutes on real material with telemetry on
   - compare `detector_tick` distributions to the prior baseline using
     `tools/analyze_autovj_log.py`

---

## 9. Risk Register

| Risk | Mitigation |
|------|------------|
| Autocorrelation cost on every frame too high | Compute every Nth frame (e.g. every 4 frames at 60fps); pre-allocate buffers; use `np.correlate` with valid slices only. |
| Tempo prior overfits to electronic music | Make `prior_mu`, `prior_sigma` profile-aware (chill ~100, normie ~120, raver ~138). |
| Octave-down preference defeats genuinely fast genres | Only apply when slower fold is ≥ 85% of fast peak score; gate by profile prior. |
| Phase oscillator gets stuck on wrong tempo | If phase coherence < 0.3 for N seconds, force re-estimation with widened tolerance. |
| Backward-compat regression for effects | Keep `data.beat` level emission unchanged; add new fields with safe defaults. |
| Drop-in independence violation | Onset queue lives on `Analyzer`, exposed via `AudioManager`. BeatTracker stays drop-in side. |
| Performance regression (frame budget) | Measure with `time.perf_counter` blocks; document budget per phase; reject if `update()` p99 > 1 ms. |

---

## 10. Telemetry Additions

Extend `detector_tick` payload with:

- `engine` (`"legacy"` | `"v2"`)
- `acf_peak_ratio` (top peak / second-best)
- `phase_coherence`
- `prior_weight_at_bpm`
- `onsets_per_sec`

Update `tools/analyze_autovj_log.py` to summarize these.

This makes live runs comparable to offline harness runs.

---

## 11. Glossary

- **IOI** — Inter-Onset Interval; time between two consecutive detected
  onsets.
- **Onset** — A point in time where energy rises sharply; not necessarily
  on the beat.
- **Beat** — A pulse on the musical grid; what musicians count.
- **Downbeat** — Beat 1 of a bar.
- **Tempo prior** — Probability distribution expressing perceptual
  expectation of typical tempos (musicians overwhelmingly perceive
  pulses in roughly 80–160 BPM).
- **Phase coherence** — Fraction of recent onsets that landed near the
  predicted beat phase.
- **Octave error** — Reporting BPM as half / double / 2/3 / 3/2 of the
  true tempo.
- **Tempogram** — A 2D representation of local tempo estimates over time
  (out of scope here; autocorrelation is the per-window slice of one).

---

## 12. Definition of Done

Beat detection rewrite is considered complete when **all** of the
following are true:

1. `tools/bpm_eval.py` exists, runs on the committed seed corpus, and
   produces a stable report.
2. On the seed corpus:
   - median absolute BPM error ≤ 1.5 BPM
   - octave/harmonic error rate ≤ 10%
   - time-to-lock ≤ 8 s on tracks with a clear pulse
   - confidence ECE ≤ 0.10
3. Live runs show BPM lane occupancy roughly matching the corpus
   distribution (no systemic ~155-lane bias).
4. Auto VJ director behavior is at least as good as today (no regression
   in chain integrity or transition pacing).
5. Documentation updated:
   - `docs/developer-guide.md` — "Beat tracker" section.
   - `docs/debug/auto-vj-drop-detection-debug-2026-05-21.md` — closing
     summary with before/after metrics.
6. `[beat_tracker] engine = "v2"` becomes the default (after at least one
   long live run shows no regressions).

---

## 13. Suggested Branch / Commit Layout

- One feature branch per phase (`feature/beat-tracker-p0`, etc.).
- Each branch lands behind the feature flag; default stays `legacy` until
  P4 ships and harness clears regression gate.
- Commit messages follow repo convention (imperative, 72-char subject,
  body explaining *why*).
- Each PR includes: harness metric delta, sample log analysis, and the
  acceptance criteria checked off.

---

## 14. What NOT To Do

- Do not write a clever heuristic on top of the current IOI estimator
  hoping to "trick" it into the right lane. The estimator is the
  problem.
- Do not introduce `librosa`, `aubio`, or any other heavy DSP dependency
  without an explicit owner approval (see "Preferred Libraries").
- Do not silently change values in the user's `config.toml`.
- Do not add error handling for situations that cannot occur. Validate at
  boundaries only.
- Do not log MIDI note data or raw audio frames at INFO+ level.
- Do not couple core `unicornviz/` to drop-in imports. Use the existing
  loader pattern.

---

## 15. v2 Regression Watchlist

The v2 engine already proved it can eliminate the old ~155 BPM harmonic lock
on the seed corpus, but a later live 124 BPM run exposed two transient
regressions that need guarding before v2 can become the default:

1. **phantom 200 BPM spikes** when the ACF score is near-zero across all lags
2. **96 BPM dips** when a single bad frame moves the EMA too far

Planned hardening steps:

- raise the minimum score floor before `np.argmax(score)` is trusted
- cap BPM movement per update so one frame cannot swing the estimate by
  double digits
- require a confidence floor before applying any BPM update

Treat these as mandatory stabilization work for P5/P7 before flipping the
feature flag in production.

### Current v2 hardening (2026-05-21 live follow-up)

The v2 tracker is currently being hardened against two live regressions on a
steady 124 BPM track:

- phantom 200 BPM spikes when the ACF is effectively flat
- transient dips to 96 BPM when one bad frame pulls the EMA off target

The precise fixes being applied now are:

- raise the minimum ACF score floor so `np.argmax(score)` never defaults to
  the lag_min / 200 BPM ceiling on near-zero frames
- cap per-update BPM movement so a single bad frame cannot swing the estimate
  by double digits
- require a confidence floor before any BPM update is applied

If v2 is promoted later, these guardrails must be part of the final merged
state; they are not optional polish.

Observed result after applying the hardening pass:

- seed corpus remains strong (v2 still beats legacy decisively)
- a 124 BPM synthetic click track is now stable with no 200-spike / 96-dip
  regression, though it is slightly conservative in the 120 BPM vicinity

This is the right trade-off for the current phase: eliminate instability
first, then tune exact calibration in the next pass if needed.

---

End of plan. Build it phase by phase, measure every change, keep effects
working, and the 155-lane bias will be a historical footnote.
