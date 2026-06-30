# Unicorn Viz — Code Audit (2026-05-09)

Scope: performance, logic correctness, syntax/style, and optimization across
the runtime, audio pipeline, app loop, effects, hotkeys, overlays, and registry.

This audit is informational. No behavior was changed by writing this file.

---

## 1. Performance

### 1.1 Analyzer hot path allocates per frame
File: `unicornviz/audio/analyzer.py`

- `np.hanning(n)` is recreated every call to `process(pcm)`.
- `spectrum.copy()`, `self._smoothed.copy()`, and `data.fft = self._smoothed.copy()`
  allocate fresh arrays each frame.
- `_flux_history` is a Python `list` with `.pop(0)` (O(n)) plus
  `np.array(self._flux_history, dtype=np.float32)` rebuilt each frame.

Recommendation:
- Cache window per `n` in a small dict (or assert fixed `_BLOCK_SIZE`).
- Use a `deque(maxlen=_ONSET_WINDOW)` plus a preallocated numpy ring buffer.
- Reuse a preallocated `out_fft` array; copy into the returned `AudioData`
  only when needed.

### 1.2 App loop module import inside hot path
File: `unicornviz/app.py`

- The main loop performs `from unicornviz.effects.ansi_viewer import ANSIViewer`
  inside the per-frame block that updates the name overlay.
- It is also imported again inside `goto_ansi`.

Recommendation: import once at module scope or cache on first use.

### 1.3 Per-effect reactivity allocation
File: `unicornviz/app.py` (`_audio_for_effect`)

- When an override is active, the function allocates a new `AudioData`, plus
  copies of `fft` and `waveform`, every single frame.

Recommendation: mutate a per-effect scratch `AudioData` in place; copy
`waveform`/`fft` only if the effect actually mutates them (none currently do).

### 1.4 `_render` rebuilds `mode_map` per frame
File: `unicornviz/app.py`

- The `mode_map` dict is constructed inside the transition branch each frame.

Recommendation: lift to a module-level constant or class attribute.

### 1.5 Transition speed depends on `1.0/TARGET_FPS`, not real `dt`
File: `unicornviz/app.py`

- `_transition_t += (1.0 / _transition_duration) * (1.0 / TARGET_FPS) * (...)`
  uses a constant frame budget instead of measured `dt`.

Effect: at sustained <60fps, transitions visibly slow down; at >60fps (vsync
off / HDMI 144Hz desktop) they speed up.

Recommendation: substitute `dt` for `(1.0/TARGET_FPS)`.

### 1.6 Per-frame Python allocation in effects
Examples:
- `unicornviz/effects/audio_spectrum.py` `_build_bars`: builds Python list,
  loops in Python over bars and stacked blocks, then `np.array(verts, ...)`.
- `unicornviz/effects/unicorn_tears.py` `render`: builds 4 tuples via
  generator expression every frame from numpy arrays:
  `tuple(float(v) for v in self._tx)`.
- `unicornviz/effects/metaballs.py` `render`: builds a Python list of length
  `_MAX_BALLS*3` each frame and converts to tuple for the uniform.
- `unicornviz/effects/particle_storm.py` and `effects/fire.py` `import math`
  inside the per-frame `update()` path.

Impact is modest individually but adds up across frames.

Recommendations:
- Cache `import math` at top of module (already imported in some, missing in others).
- For Unicorn Tears, write into preallocated tuples once after
  position update using `np.ndarray.tolist()` or pass the ndarray directly to
  moderngl uniform writers.
- For Metaballs, preallocate a `(_MAX_BALLS * 3,)` `np.float32` array and fill
  in place; pass `.tobytes()` to the uniform via `Buffer` if profiling shows
  the tuple conversion to be hot.

### 1.7 FFT runs on the main thread
File: `unicornviz/audio/analyzer.py` (called from the GL frame loop)

- The FFT and beat detection are performed on the render thread each frame.

Recommendation (medium effort): move analysis to the audio worker thread and
publish a lock-free snapshot. This decouples FFT cost from frame budget.

### 1.8 Heavy fragment shaders without resolution divisor
- `rainbow_trance`, `raymarcher`, `fire` (sim is at 256-ish), `unicorn_tears`,
  `particle_storm` are GPU-heavy at 1080p+; only `fire` decouples sim from
  display.

Recommendation: optional `render_scale` parameter (0.5–1.0) per effect, or
global `[render].internal_scale` config knob, scaled via a single FBO blit.

---

## 2. Logic correctness

### 2.1 Per-effect reactivity semantics now correct, but doc text in
`docs/configuration.md` still has a residual line:
"If omitted, per-effect `reactivity` defaults to `1.0`."
This is misleading after the absolute-override change — the effect uses the
global value, not literal 1.0. Same wording softness in
`docs/effect-settings.md`.

### 2.2 Splash config written twice
File: `unicornviz/app.py` `run()`
- Inside the `if Path(splash_path).exists():` branch, `_splash_config` is
  written. Immediately after the branch, it is unconditionally overwritten
  with the version that adds `audio_manager`.
- The first assignment is dead code.

### 2.3 `audio.manager` `numpy` import inside method
- `import numpy as _np` is performed inside `get_audio_data` even though
  `numpy as np` is already imported at module top.

### 2.4 `_candidate_monitor_devices` returns `None` regardless of rank list
- Even if all devices were rank-99 (undesirable), `None` is appended at the
  end, so behavior is correct. But the function silently falls through if
  `sd.query_devices()` raises after the early-return path (handled). Acceptable.

### 2.5 Hotkey cursor visibility relies on tracking only LCTRL/RCTRL keysyms
- Only `Ctrl` toggles cursor visibility. If the user releases Ctrl outside the
  window or alt-tabs, the cursor state can desync.

Recommendation: also reset on `SDL_WINDOWEVENT_FOCUS_LOST/GAINED`.

### 2.6 Effect audio update for `_next_effect` always uses snapshot from this
frame — correct, but during transitions both effects scale FFT independently
and allocate two new `AudioData` objects per frame when both have overrides.
Acceptable but doubled allocation cost.

### 2.7 Auto-advance allow-check imports inside loop
- `from unicornviz.effects.ansi_viewer import ANSIViewer` inside the
  `try/except` per frame; same fix as 1.2.

### 2.8 `goto_ansi` does not initialize `_transition_kind`
- When ANSI Viewer is launched via `,` or `.`, the transition uses whatever
  kind was last set. Usually fine because crossfade default works, but in
  shuffle mode this can pick a stale kind. Minor.

### 2.9 Beat throughput contract
- `AudioData.beat` is `0.0` or `1.0` post-analyzer. Effects often use
  `> 0.5` checks. Consistent. No bug, but worth documenting that beat is
  not scaled by reactivity (intentional).

### 2.10 Hotkey `Ctrl+0` vs `Ctrl+1..9`
- The `Ctrl+0 -> idx 29` branch is handled in a separate elif from the
  `Ctrl+1..9 -> idx 20..28`. The logic for plain `0` is `idx 9` and Shift+0
  is `idx 19`. Consistent.

### 2.11 Logging: a few INFO-level entries fire per stream open and per
keypress. For long sets the file can balloon. No PII concerns observed.

---

## 3. Syntax / style

### 3.1 No syntax errors observed
- `ast.parse` confirms all touched modules compile.
- A `pyflakes`/`ruff` pass would be useful but not required.

### 3.2 Private-member access patterns
- `hotkeys.py` and `app.py` access multiple `_underscored` attributes via
  `# noqa: SLF001`. This is acceptable but could be expressed as small
  public methods (e.g., `app.is_running()`, `app.set_running(False)`,
  `audio_manager.get_reactivity()` is now done; do similar for
  `app._current_effect`).

### 3.3 Mixed quote style
- Codebase mixes `'single'` and `"double"` quotes. Per project style,
  prefer single quotes unless the string contains an apostrophe.

### 3.4 Inline `import math` / `import numpy as _np`
- Should be hoisted to module scope (see 1.6, 2.3).

### 3.5 GLSL section comments
- Most embedded shaders have a brief preamble; `app.py` blend shader does
  not enumerate uniforms explicitly. Consider adding a short comment block
  consistent with project standards.

---

## 4. Optimization opportunities (concrete)

### 4.1 Cache module imports in app loop
- Move `from unicornviz.effects.ansi_viewer import ANSIViewer` to top of
  `app.py`. Saves one resolution per frame.

### 4.2 Mutate per-frame audio in place for `_audio_for_effect`
- Maintain `self._fx_audio_a` and `self._fx_audio_b` scratch buffers.

### 4.3 Make analyzer allocation-free
- Cache hanning window.
- Use `np.empty` + `np.subtract(spectrum, prev, out=tmp)` where possible.

### 4.4 Pre-build `mode_map`
- Lift to module-level constant.

### 4.5 Fix transition timing to use `dt`
- Direct gain to fps-independent transitions.

### 4.6 Optional: thread the analyzer
- Larger refactor; biggest single perf win for low-end GPUs at small block sizes.

### 4.7 Optional: render-scale config
- One global `[render].internal_scale = 0.85` knob with a single composite blit.

### 4.8 Effect-local hot-path tightening
- Unicorn Tears: precompute and reuse tuple buffers, or use ndarray uniform
  writes via moderngl.
- Metaballs: preallocate ndarray for the flat ball array.
- Audio Spectrum: vectorize `_build_bars` using numpy (significant speedup for
  many bars).

---

## 5. Repo hygiene

- `git ls-files` shows zero tracked `.venv` / `__pycache__` / `.pyc` entries.
  The plan.md note about this can be marked resolved.
- `.gitignore` should be reviewed once for `audits/` if you don't want it
  tracked (recommend tracking it; this audit is useful history).

---

## 6. Risk-ranked summary

High value, low risk:
- 1.2 / 4.1 — lift loop import
- 1.5 / 4.5 — fix `dt`-based transition timing
- 1.4 / 4.4 — mode_map constant
- 2.2 — remove dead splash_config write
- 2.3 / 3.4 — hoist inline imports
- 1.3 / 4.2 — preallocate per-effect audio scratch

Medium value, low risk:
- 1.1 / 4.3 — analyzer allocation-free pass
- 1.6 — per-effect Python allocation cleanup

Higher impact, more work:
- 1.7 / 4.6 — analyzer threading
- 1.8 / 4.7 — render-scale config

---

## 7. Suggested follow-up plan.md update lines

(Reflecting concrete audit outcomes; not the whole new-features list.)

- `[todo]` Make audio analyzer allocation-free per frame.
- `[todo]` Move ANSIViewer import to module scope and remove dead splash_config write.
- `[todo]` Use real `dt` for transition timing.
- `[todo]` Cache `mode_map` at module scope.
- `[todo]` Add scratch `AudioData` for per-effect reactivity overrides.
- `[todo]` Optional: thread the FFT/beat analyzer.
- `[todo]` Optional: global `[render].internal_scale` knob.
- `[todo]` Update docs to clarify per-effect reactivity is an absolute override (not a default of 1.0).
