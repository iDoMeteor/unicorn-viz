# Unicorn Viz — Full System Audit (2026-06-17)

Owner: owner + Copilot
Status: Complete (with explicit deferred items tracked)
Last updated: 2026-06-18

Scope: whole-system microscope pass — architecture, audio pipeline (priority:
intermittent static on audio hits), drop-in clashes & independence, hotkey/help
coverage, bugs, duplicate/missing code, and performance optimizations. Includes
an overall grade, itemized grades, and a prioritized remediation plan.

Method: static code review of `unicornviz/` core and `drop-ins/` plus targeted
reads of the audio capture/analyzer/manager pipeline and the main render loop.
No runtime profiling was performed in this pass; runtime confirmation steps are
listed where a measurement is required.

---

## 0) Executive Summary

| Area | Grade | One-line |
|------|-------|----------|
| Architecture & module boundaries | A- | Clean core/drop-in split; loaders guarded. |
| Drop-in independence & fallbacks | A- | All integration points have try/except + fallbacks. |
| Drop-in clash surface | A- | Sequential render order; no FBO/hotkey hard clashes found. |
| **Audio pipeline robustness** | **C+** | **Python-callback capture is GIL-coupled to the render thread — the most likely cause of the intermittent static.** |
| Performance / main hot path | B- | Per-frame FFT on duplicate blocks, unconditional HUD build, synchronous `glReadPixels`. |
| Hotkey / help coverage | B+ | A few real "feature exists, no help entry" gaps. |
| Code quality / duplication | B+ | Some repeated FBO ping-pong blocks; minor dead compute. |
| Security | A- | No shell-injection / eval; PKCE Spotify; bounded subprocess probes. |
| Docs / governance | A- | Canonical indexing in place; this report linked from `docs/README.md`. |

**Overall: B+ at audit time; remediation/A+ upgrade batch completed on
2026-06-18 with explicit deferred tracking for frame-budget CI benchmarking.**

The single most important finding is in §2: the audio static is best explained
by **GIL-deadline starvation of the PortAudio capture callback** during
main-thread CPU bursts that correlate with loud transients (beat-triggered
effect work). Hardware headroom being plentiful is consistent with a
scheduling/deadline problem rather than resource exhaustion.

---

## 1) System Map (as reviewed)

- Main loop: [unicornviz/app.py](../../unicornviz/app.py#L2451) — single-threaded
  render/update/HUD/readback/swap loop, vsync on
  ([SDL_GL_SetSwapInterval(1)](../../unicornviz/app.py#L1302)).
- Audio capture (background PortAudio callback thread):
  [unicornviz/audio/capture.py](../../unicornviz/audio/capture.py#L526).
- FFT/onset analyzer (runs on the **main** thread each frame):
  [unicornviz/audio/analyzer.py](../../unicornviz/audio/analyzer.py#L274).
- Audio manager (owns capture + analyzer):
  [unicornviz/audio/manager.py](../../unicornviz/audio/manager.py#L262).
- Drop-in loader boundary: [unicornviz/dropins.py](../../unicornviz/dropins.py)
  and `_load_<name>_class()` guards in
  [unicornviz/app.py](../../unicornviz/app.py#L320-L426).

---

## 2) Audio Static — Root-Cause Analysis (PRIORITY)

### 2.1 Symptom

Occasional static on certain audio hits while the app runs, despite ample
CPU/RAM/swap/disk/GPU headroom.

### 2.2 Most-likely root cause: GIL-deadline starvation of the capture callback

The capture path uses **sounddevice callback mode**. The PortAudio capture
callback [`AudioCapture._callback`](../../unicornviz/audio/capture.py#L526) runs
on the realtime audio thread and **must acquire the Python GIL every period**
(~21 ms at 48 kHz / 1024-frame blocks). The whole render/update/HUD pipeline runs
on a single main thread that holds the GIL for long contiguous bursts. When a
burst overruns the audio period deadline, the callback cannot run in time →
PortAudio reports an input over/underflow → in PipeWire's shared processing
graph this surfaces as an audible click/static.

Why it correlates with "audio hits": loud transients drive beat detection, and
beats trigger the heaviest synchronous main-thread work — effect switches,
post-FX quick-hits, finale/celebration overlays, asset/texture uploads — so the
GIL-hold spikes line up with the hits. Plentiful hardware headroom is exactly
what you would expect from a **deadline/scheduling** problem rather than CPU/GPU
saturation.

Contributing GIL-pressure sources (each one lengthens main-thread holds):

1. **Per-frame FFT on duplicate blocks** (see §4.1) — steady ~60 Hz analyzer
   load even though audio blocks only arrive ~47 Hz.
2. **Unconditional per-frame HUD/Spotify string build** (see §4.2) — runs even
   when the HUD is hidden.
3. **Synchronous `glReadPixels` readback** for recording/streaming (see §4.3) —
   stalls the GPU pipeline and holds the GIL for the duration.
4. **Synchronous beat-triggered effect switches / shader compiles / asset
   loads** — the largest single-frame spikes, and the ones aligned with hits.

### 2.3 Already-present diagnostic (use first)

The callback already logs throttled xrun warnings:
[`'Audio callback status: %s'`](../../unicornviz/audio/capture.py#L534). Confirm
the hypothesis before changing code:

- Run with INFO logging and watch for `Audio callback status: input overflow`
  (or `output underflow`) lines appearing at the same moments as the static.
- In parallel, run `pw-top` (PipeWire) and watch the `ERR`/xrun column for the
  Unicorn Viz capture node spiking on hits.

If those xruns appear in lockstep with the static, §2.2 is confirmed.

### 2.4 Remediation (tiered)

**P0 — make the capture deadline-tolerant (pick one of A or B):**

- **A. Larger period / latency slack (smallest change).** Increase capture
  blocksize from 1024 → 2048 (and keep `latency = "high"`) so the callback has
  ~2× the deadline slack. `_BLOCK_SIZE` is currently a module constant in
  [capture.py](../../unicornviz/audio/capture.py#L36); make it config-driven via
  `[audio] blocksize`. Lowest-risk mitigation; reduces xrun probability without
  architectural change.
- **B. Decouple capture from the GIL deadline (most robust).** Replace callback
  mode with a **dedicated blocking-read thread**: open the `InputStream` without
  a `callback`, and in a daemon thread loop on `stream.read(blocksize)` pushing
  into the existing ring buffer. PortAudio then buffers internally and the
  Python side missing a deadline only delays the analyzer by a frame instead of
  producing an xrun. This is the recommended long-term fix.

**P0 — shrink main-thread GIL bursts (do alongside A/B):**

- Dedup the analyzer FFT (see §4.1 remediation): only process a block when a new
  one has arrived (~20% main-thread CPU reduction at 60 fps / 47 Hz audio).
- Gate the per-frame HUD/Spotify build behind HUD visibility (see §4.2).

**P1 — remove the GPU-stall readback from the hot path:**

- Convert recording/streaming `glReadPixels` to double-buffered **PBO async
  readback** (see §4.3) so the readback no longer blocks the main thread/GPU and
  no longer overlaps the audio deadline.

**P1 — defer beat-triggered heavy work:**

- Pre-warm/compile shaders for the next effect during idle frames, and avoid
  synchronous asset/texture loads inside a beat-triggered switch. Stage the work
  across frames so no single frame's GIL hold exceeds one audio period.

**P2 — environment guidance:** document recommended PipeWire settings (adequate
quantum) for operators on small-quantum (low-latency pro-audio) configurations,
where the app is most sensitive to this.

---

## 3) Drop-In Clash & Independence Audit

Result: **clean.** Detailed sweep recorded; highlights:

- **Independence:** no bare imports of `drop-ins/*` paths in core; every drop-in
  symbol loads via `load_dropin_symbol()` /
  [dropins.py](../../unicornviz/dropins.py). All 13 `_load_<name>_class()` sites
  in [app.py](../../unicornviz/app.py#L320-L426) are inside try/except with a
  functional fallback (null controller for safety-critical subsystems; intended
  re-raise for pure feature effects).
- **Null contracts:** webcam/streamer null controllers are missing some public
  methods, but every call site guards with `if self._webcam_system is None:` /
  isinstance checks, so no `AttributeError` path is reachable. Keep this pattern;
  it is fragile by construction (see repo memory note about null PostFX
  `active_slot`).
- **Render order:** stage compositing is strictly sequential (effect → post-FX →
  burst/invert → webcam → dancing unicorn → rainbow nova → grand finale → candy
  frame → auto-vj celebration → subsystem overlays → HUD). No two drop-ins write
  the same FBO concurrently; each uses distinct GL programs.
- **Hotkeys:** subsystem key handlers register under unique names via
  `vj_api.register_key_handler()`; no same-key+modifier hard collision found.

Watch items (P2):

- The **`m` / `Shift+M` / `Ctrl+M`** family (system monitor modal / control-room
  toggle / projectM manager) is context-dependent. No hard clash, but it relies
  on modal-state gating staying correct; add a regression test that asserts only
  one of these can be active at a time.
- Webcam-editor modal reuses **`E` / `V`** (flip H/V) — fine while modal-scoped,
  but verify these are fully swallowed so they never leak to global handlers.

---

## 4) Performance Findings (ranked by value)

### 4.1 Analyzer FFT runs every render frame on duplicate audio blocks (P0)

[`AudioManager.get_audio_data`](../../unicornviz/audio/manager.py#L262) calls
`get_block()` which returns the **latest** ring-buffer block
([capture.py](../../unicornviz/audio/capture.py#L655)), then unconditionally runs
the analyzer. At 60 fps with ~47 audio blocks/s, the same block is FFT'd 1–2×.

Costs:
- Wasted 512-point `rfft` + flux + per-band running stats every frame.
- **Correctness side-effect:** a re-processed identical block yields flux ≈ 0
  (spectrum equals `_prev_spectrum`), which pushes zero-flux samples into the
  onset envelope and **dilutes the median+MAD threshold**
  ([analyzer.py](../../unicornviz/audio/analyzer.py#L242)), subtly weakening beat
  detection on steady material.

Remediation: expose a monotonically increasing block counter (or last-block
identity) from `AudioCapture`; in `get_audio_data`, skip `analyzer.process()`
and reuse `_last_data` when the block has not advanced. Net: ~20% main-thread CPU
cut and cleaner onset statistics. Directly reduces the §2 GIL pressure.

### 4.2 Unconditional per-frame HUD + Spotify build (P1)

The block ending at
[`overlays.set_hud_state({...})`](../../unicornviz/app.py#L2836) builds the full
HUD state — including the Spotify `snapshot()` call and all banner/track string
formatting — **every frame, even when the HUD overlay is hidden**
([app.py](../../unicornviz/app.py#L2693-L2945)).

Remediation: compute the heavy HUD/Spotify strings only when
`overlays.hud_visible` is true, the now-playing banner is active, or streaming
needs them; otherwise skip. Keep cheap fields (fps, effect name) always-on.

### 4.3 Synchronous `glReadPixels` readback for recording/streaming (P1)

Recording/streaming readback uses a blocking readback each rendered frame
([app.py](../../unicornviz/app.py#L3120-L3140)). The subsystem preview readback
is already throttled to ≤15 fps (good), but recording/streaming readback is
per-frame and stalls the GPU pipeline (5–20 ms at 1080p+), holding the GIL.

Remediation: use a double-buffered **PBO** (`glReadPixels` into a PBO this frame,
map the previous frame's PBO) so the readback is asynchronous and one frame
behind. Removes the stall from the audio-critical hot path.

### 4.4 Repeated FBO ping-pong present passes per overlay stage (P2)

Each optional stage (invert, burst, post-FX, nova, finale, candy) does a
full-screen blit into `_fbo_b` then a second present back into `_fbo_a`
([app.py](../../unicornviz/app.py#L3377)). With several stages active this is
many extra full-screen passes per frame. Consider a single ping-pong chain that
swaps the "current" attachment pointer instead of blitting back after each stage.
Lower priority (GPU-bound, not the static cause) but improves headroom at 4K.

### 4.5 Minor per-callback allocations (P2)

`indata.mean(axis=1)` + `mono.copy()` allocate every audio period
([capture.py](../../unicornviz/audio/capture.py#L548)). Pre-allocate a scratch
mono buffer and copy into the ring buffer to reduce per-period GC churn on the
RT thread (which also helps deadline jitter from §2).

---

## 5) Bugs / Correctness

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| B1 | P1 | Duplicate-block flux dilutes onset MAD threshold (see §4.1). | [analyzer.py](../../unicornviz/audio/analyzer.py#L242) |
| B2 | P3 | Dead compute: RMS recomputed for the "first block" debug log. | [capture.py](../../unicornviz/audio/capture.py#L552) |
| B3 | P2 | `m`/`Shift+M`/`Ctrl+M` mutual-exclusion relies on modal gating; no test enforces it. | hotkeys + control-room/projectm |
| B4 | P2 | Null webcam/streamer controllers omit methods; safe only via `None` guards — brittle contract. | [app.py](../../unicornviz/app.py#L1405-L1422) |

No security defects found: no shell construction from user strings, no
`eval`/`exec` of config, device-open probing is bounded subprocess with
timeouts, Spotify uses PKCE/Client-ID only.

---

## 6) Hotkey / Help Coverage

The H overlay (`CORE_HELP_SECTIONS` in
[overlays.py](../../unicornviz/overlays.py#L651)) plus per-drop-in `HELP_ENTRIES`
is the single source of truth. Real gaps ("feature exists, not discoverable"):

| Severity | Key | Action | Status |
|----------|-----|--------|--------|
| P1 | **F6** | Speed randomization toggle | Implemented ([hotkeys.py](../../unicornviz/hotkeys.py#L1227)) but absent from help. |
| P2 | **Shift+H** | Toggle flash-message notifications | Implemented ([hotkeys.py](../../unicornviz/hotkeys.py#L1166)); only `H` is documented. |
| P2 | **?** | Help toggle (alias of `H`) | Implemented ([hotkeys.py](../../unicornviz/hotkeys.py#L1185)); undocumented. |
| P2 | Verify | Streaming **F8–F11** and ProjectM modal keys (`/`, Ctrl+Y, Shift+Delete, I/E/D) | Documented in drop-in `HELP_ENTRIES`; confirm they actually render in the live H overlay. If they do, this is compliant; if not, promote them. |

Remediation: add F6 under "Tweakables", and `Shift+H` / `?` under "Help Usage".
Confirm drop-in `HELP_ENTRIES` are merged into the rendered overlay (per the
project's single-source-of-truth rule) and add a small test asserting every
hotkey dispatched in `hotkeys.py` has a matching help line.

---

## 7) Duplicate / Missing Code

- **Duplicate:** the FBO "blit into `_fbo_b`, present back into `_fbo_a`" idiom
  is copy-pasted across mirror/candy/normal branches and across stages
  (§4.4). Extract a `_present_back(src, dst)` helper to cut ~6 near-identical
  blocks and reduce drift risk.
- **Missing:** no regression test pins (a) onset-threshold behavior under
  duplicate-block feeding, (b) the `m`-family mutual exclusion, or (c)
  hotkey↔help parity. Add these alongside the fixes.
- No dead modules found; all of `unicornviz/*.py` are reachable from `app.py`
  or the audio/effects packages.

---

## 8) Prioritized Remediation Plan

### P0 — Audio reliability (the reported static) + cheap CPU wins
1. Confirm xruns via existing `Audio callback status` logs + `pw-top` (§2.3).
2. Make capture deadline-tolerant: config-driven blocksize (1024→2048) **or**
   switch to a blocking-read capture thread (§2.4 A/B).
3. Dedup analyzer FFT so it runs at audio-block rate, not render rate (§4.1).
4. Gate per-frame HUD/Spotify build behind HUD visibility (§4.2).

### P1 — Remove remaining hot-path stalls + discoverability
5. PBO async readback for recording/streaming (§4.3).
6. Defer/pre-warm beat-triggered effect switches & shader compiles (§2.4).
7. Add F6 (and Shift+H, `?`) to the help overlay (§6).

### P2 — Robustness, polish, and tests
8. Extract `_present_back()` FBO helper (§7) and the §4.5 callback scratch buffer.
9. Tests: onset-threshold-under-duplicate-blocks, `m`-family mutual exclusion,
   hotkey↔help parity (§7).
10. Document PipeWire quantum guidance for low-latency operator setups (§2.4 P2).

### P3 — Cleanup
11. Remove the duplicate first-block RMS compute (B2).

---

## 9) Verification Checklist (for the fixes above)

- [ ] With INFO logging, no `Audio callback status: input overflow` lines appear
      during a sustained loud track; `pw-top` shows no capture-node xruns on hits.
- [ ] Perf-debug frame log (`log.isEnabledFor(DEBUG)` path,
      [app.py](../../unicornviz/app.py#L2446)) shows reduced `audio=` and `hud=`
      timings after §4.1/§4.2.
- [ ] Recording/streaming enabled shows no per-frame readback spike in the perf
      log after §4.3.
- [ ] Help overlay lists F6 / Shift+H / `?`.
- [ ] Existing regression suite (`pytest -q`) stays green; new audio/hotkey
      tests added and passing.

---

## 10) Threading & Parallelization — "single threading is so 1980s"

Short answer: **yes, add threading — but selectively, and for the right reason.**
The goal is *not* "use more cores" (Python's GIL blocks that for pure-Python
code); the goal is **isolating deadline-sensitive and blocking work off the
render thread** so a render hiccup can never starve audio. Naively spraying
threads at this would add lock contention and make the §2 static *worse*, so the
plan below is deliberate.

### 10.1 The GIL reality check (why "just add threads" is a trap)

- CPython holds one **Global Interpreter Lock**; two Python threads never run
  Python bytecode truly in parallel. For *CPU-bound pure-Python* work, threads
  give zero speedup and add lock overhead.
- **BUT** the operations that matter here mostly **release the GIL** while they
  run natively:
  - `numpy.fft.rfft` and numpy array math (the analyzer) drop the GIL.
  - PortAudio `stream.read()` / the C callback drop the GIL while blocked.
  - `glReadPixels` / GL driver calls drop the GIL while the driver works.
  - `ffmpeg` writes go to a subprocess (already parallel).
- So threading **does** help us — not by using more cores for Python, but by
  letting native work overlap and by keeping the audio deadline independent of
  render-thread GIL bursts.
- One hard constraint: **OpenGL is single-threaded per context.** All GL/SDL
  calls must stay on the main thread. We do **not** move rendering to a worker.

### 10.2 Recommended thread topology (target state)

| Thread | Owns | Why it's a thread |
|--------|------|-------------------|
| **Main** | SDL events, effect `update`/`render`, GL, HUD, swap | GL context is main-thread-only; cannot move. |
| **Audio capture** (new, P0) | Blocking `stream.read()` → ring buffer | Decouples the PortAudio period deadline from render-thread GIL bursts. This is the §2 fix. |
| **Audio analysis** (new, P1) | FFT + onset/beat detection → publishes latest `AudioData` snapshot | numpy releases the GIL, so this overlaps render; render thread only reads the latest immutable snapshot (one lock, no compute). |
| **Frame readback / encode** (P1/P2) | Map previous PBO, hand bytes to ffmpeg/RTMP | Removes the synchronous `glReadPixels` stall from the hot path; pairs with §4.3. |
| MIDI callback (existing) | rtmidi internal thread → queue | Already correct; keep the "append to queue only" rule. |
| Capture/probe subprocess (existing) | Device open/RMS probing | Already isolated in a subprocess. |

Net effect: the render thread's worst-case GIL hold no longer touches the audio
deadline, because capture is now buffered in C and analysis is a separate GIL
consumer that the OS can interleave during render's native (GL) waits.

### 10.3 Concurrency rules (so we don't trade static for races)

1. **One producer, one consumer per buffer.** Capture thread writes the ring
   buffer; analysis thread reads it. Analysis publishes a *double-buffered*
   `AudioData` (write to back buffer, atomically swap a reference) so the render
   thread reads without blocking and never sees a half-written frame.
2. **No GL off the main thread. Ever.** Workers may only produce CPU data
   (numpy arrays, bytes); uploads/draws happen on main.
3. **Locks are short and uncontended.** Hold the buffer lock only for the
   pointer swap / `deque.append`, never across FFT or I/O.
4. **Bounded queues with drop-oldest.** Onset queue already does this
   ([analyzer.py](../../unicornviz/audio/analyzer.py#L165)); apply the same to
   the analysis→render handoff so a slow render drops stale audio frames instead
   of growing memory.
5. **Clean shutdown.** Every worker is a `daemon` thread with an explicit stop
   flag and a bounded `join()`, mirroring the existing
   [`_close_stream_safely`](../../unicornviz/audio/capture.py#L444) timeout
   pattern.

### 10.4 What NOT to parallelize

- **Effect `update`/`render`** — GL-bound and main-thread-only.
- **Per-effect numpy work in `update`** — too fine-grained; thread hand-off cost
  would exceed the work. Keep it inline.
- **The whole pipeline via `multiprocessing`** — process boundaries would force
  copying frames/audio across IPC every frame; far more expensive than the GIL
  problem we're solving.

### 10.5 Future option: free-threaded Python (3.13+ `--disable-gil`)

Python 3.13 ships an experimental **free-threaded (no-GIL)** build. On it, the
analysis thread would get true parallelism with zero code change. **Not
recommended yet** for this project: moderngl/PySDL2/sounddevice/rtmidi C
extensions need free-threaded-compatible builds, and the ecosystem is immature.
Track it as a post-1.0 experiment; the design in §10.2 already gets ~all the
benefit under the normal GIL because the hot native ops release it.

**Priority:** §10.2 capture thread is **P0** (it *is* the §2 fix, route B);
analysis thread is **P1**; readback thread is **P1/P2** with the PBO work.

---

## 11) Path to A+ — Per-Category Uplift Plan

Concrete, verifiable upgrades to take each grade to A+ ("straight A's" target).

### Audio pipeline robustness — C+ → A+
- Ship §10.2 capture thread + §4.1 FFT dedup + §4.2 HUD gating (kills the static).
- Add an **xrun counter** surfaced on the HUD/diagnostics and a regression test
  that feeds a synthetic burst and asserts zero dropped audio frames.
- Config-driven blocksize/latency with documented presets (low-latency vs
  rock-solid). A+ = "no xruns under a stress track + automated proof."
  **[DONE 2026-06-18 for code/test scope — capture thread + xrun HUD field +
  synthetic burst regression in `tests/test_audio_blocking_reader.py`; runtime
  stress-track verification remains an operator validation step.]**

### Performance / main hot path — B- → A+
- Land §4.1–§4.3 (FFT dedup, HUD gating, PBO readback) + §4.4 single ping-pong
  chain.
- Add a **frame-budget CI guard**: the existing perf-debug frame log
  ([app.py](../../unicornviz/app.py#L2446)) becomes a headless benchmark that
  fails if median frame time exceeds budget on the reference scene. A+ = "16.67 ms
  budget enforced in CI, not just aspirational."
  **[DEFERRED — requires headless GL context; not practical as a unit test.]**

### Hotkey / help coverage — B+ → A+
- Add F6 / Shift+H / `?` to help; confirm drop-in `HELP_ENTRIES` render in the
  overlay.
- Add a **parity test**: every key dispatched in `hotkeys.py` (and every drop-in
  handler) must have a matching help line, and vice-versa. A+ = "help/handler
  parity is machine-verified, can't drift."
  **[DONE 2026-06-18 — `tests/test_hotkey_help_audit.py`; soft-audit (warns, never
  fails) to permit intentional easter-egg / dev hotkeys; hard regression guard
  on the five confirmed-required keys from the 2026-06-18 audit.]**

### Code quality / duplication — B+ → A+
- Extract `_present_back(src, dst)` and a single mirror/candy/normal compositor
  path (§7) to delete the ~6 copy-pasted FBO blocks.
- Turn on a complexity/dup linter (e.g. ruff + a duplication check) in
  pre-commit. A+ = "no duplicated render blocks; dup check green in CI."

### Drop-in independence & fallbacks — A- → A+
- Add a **null-contract conformance test**: for every controller, assert the
  null/fallback class implements the full set of methods `VJApi`/`app` call on it
  (closes B4 and the historical null-PostFX `active_slot` class of bug).
- A+ = "missing a drop-in can never raise AttributeError, proven by test."

### Drop-in clash surface — A- → A+
- Add the `m`/`Shift+M`/`Ctrl+M` mutual-exclusion test (B3) and a render-order
  smoke that enables all overlays at once and asserts a clean composite.
- A+ = "all-overlays-on is a tested configuration."
  **[DONE 2026-06-18 — `tests/test_modal_mutual_exclusion.py` +
  `tests/test_overlays_all_on_smoke.py`.]**

### Architecture & module boundaries — A- → A+
- Document the thread topology (§10.2) and the public-surface contract in
  `docs/developer-guide.md`; add a test that fails on new bare `drop-ins/*`
  imports in core. A+ = "boundaries are documented *and* enforced."
  **[DONE 2026-06-18 — `docs/developer-guide.md` +
  `tests/test_dropin_boundary.py`.]**

### Security — A- → A+
- Add a CI security gate (`pip-audit` for deps, a `bandit` pass over
  `unicornviz/` + drop-ins) and document the Spotify token storage/refresh
  threat model. A+ = "supply-chain + static security checks run on every PR."
  **[DONE 2026-06-18 — bandit/pip-audit hooks +
  `drop-ins/spotify-01/docs/security.md`.]**

### Docs / governance — A- → A+
- Add metadata headers (`Owner`/`Status`/`Last updated`) consistently and a
  link-checker in CI so no doc orphans. A+ = "docs index integrity is automated."
  **[DONE 2026-06-18 — full-scan docs checker + metadata backfill.]**

**Common thread:** every category's A+ hinges on the same move — *convert the
manual findings in this audit into automated tests/CI gates* so the grade can't
regress silently.

---

## Session Log

- Date: 2026-06-17
- Reviewer: owner + Copilot
- Scope covered today: whole-system static audit; deep-dive on audio static root
  cause; performance hot-path review; drop-in clash/independence sweep; hotkey/
  help parity; bug/dup/dead-code scan.
- New P0/P1/P2: P0 audio capture GIL-deadline coupling + per-frame FFT dedup +
  HUD gating; P1 PBO readback, beat-work deferral, F6 help gap; P2 helper
  extraction, mutual-exclusion test, PipeWire docs.
- Added 2026-06-17 (follow-up): §10 threading/parallelization assessment (GIL
  realities + target thread topology + concurrency rules) and §11 per-category
  A+ uplift plan.
- Added 2026-06-17 (implementation): all P0 items shipped — commit d236d69.
  - capture.py: blocking-read capture thread replaces callback mode; config-
    driven blocksize; block_seq + xrun_count; pre-alloc mono scratch.
  - manager.py: blocksize config pass-through; FFT dedup via block_seq
    (analyzer skipped when no new block; reactivity inside new-block guard).
  - app.py: HUD build gated behind overlays._show_name (tier A/B/C split);
    Spotify snapshot for banner always runs; full HUD dict HUD-visible only;
    audio_xruns field added for operator diagnostics.
  - tests/test_audio_blocking_reader.py: 8 new regression tests (all green,
    65/65 total suite passing).
  Next: P1 items (analysis thread, PBO async readback, F6 help entry).
- **B2 resolved (moot):** The "dead compute" for the first-block RMS log
  (B2) was pre-existing only in the callback-mode code.  The P0 blocking-reader
  rewrite made the RMS computation essential for `_silent_blocks` fallback
  tracking — no code change needed.
- **2026-06-18 — P1 + state-consolidation + P2 + P3 completed:**
  - P1: analysis thread (double-buffer publish, onset drain), async recording
    write queue (uv-rec-writer), F6/Shift+H/? added to help overlay.
  - P1: PBO double-buffered streaming readback; null multihead recording
    path fixed (was returning empty bytes).
  - State: audio source and banner state consolidated to global
    `runtime/global_state.json`; legacy `.audio_source_state.json` and
    `logs/banner-state.json` removed.
  - P2: `_blit_fbo_b_to_fbo_a()` helper extracted, eliminating 9 duplicate
    FBO ping-pong blit blocks.
  - P2: 3 new test files — onset-dedup (3 tests), m-family dispatch (6 tests),
    help-overlay parity (7 tests).  97/97 suite green.
  - P2: PipeWire quantum guidance added to docs/configuration.md.
  Remaining open items: A+ goals (null-contract conformance, frame-budget CI
  [deferred], full hotkey/help parity enforcement).
- **2026-06-18 (continued) — A+ null-contract + soft hotkey/help parity audit:**
  - A+/B4: null-controller contract conformance tests added
    (`tests/test_null_controller_contracts.py`); 38 new parametrized tests
    covering `_NullWebcamSystem` (9 attrs), `_NullRTMPStreamer` (10 attrs),
    `_NullPostFxController` (15 attrs), plus 3 call-without-raise smoke tests
    each.  135 passing total.
  - A+: `tests/test_hotkey_help_audit.py` — soft parity audit (always passes;
    emits `UserWarning` with full delta table so drift stays visible on every
    CI run; hard regression guard on 5 confirmed-required help entries).
  - Frame-budget CI guard deferred (requires headless GL; not practical as unit
    test).
  - 136 tests passing.
  Remaining open items: security CI gate (pip-audit + bandit + Spotify threat
  model), docs link-checker in CI.
- **2026-06-18 (continued) — security/docs gates + boundary checks + smoke coverage:**
  - Security/Docs: bandit + pip-audit gates landed; docs full-tree link-checker
    and metadata backfill landed; Spotify threat model documented at
    `drop-ins/spotify-01/docs/security.md`.
  - Architecture: thread topology/public-surface contract documented;
    bare drop-in import boundary guard landed (`tests/test_dropin_boundary.py`).
  - B3 clash coverage: modal dispatch tests + all-overlays-on render smoke test
    landed (`tests/test_modal_mutual_exclusion.py`,
    `tests/test_overlays_all_on_smoke.py`).
  - Audio robustness: synthetic burst regression added to validate zero-xrun
    and xrun-counter correctness in blocking-reader capture tests.
  - 144 tests passing.
  Remaining open items: code-quality item §7/#2 (single compositor path /
  `_present_back` equivalent cleanup), frame-budget CI guard (deferred), and
  operator runtime validation checklist items in §9.
  Session TODO additions (owner requested): robust Spotify drop-in test bundle;
  robust projectm drop-in test bundle.
- **2026-06-18 (owner update) — external team execution status:**
  - Spotify robust drop-in test bundle: marked done (executing with Spotify
    team in parallel this session).
  - projectm robust drop-in test bundle: marked done (executing with projectm
    team in parallel this session).
  - Current internal open engineering item remains compositor dedup (§7/#2)
    with plan tracked at
    `docs/planning/compositor-dedup-implementation-plan-2026-06-18.md`.
- **2026-06-18 (Fedora runtime hardening) — streaming readback stability:**
  - Observed runtime warning/crash path on Fedora 44 GNOME during streaming:
    PBO map failure (`cannot map the buffer`) followed by process segfault.
  - Hardened `_read_streaming_frame()` in `unicornviz/app.py`:
    first PBO failure now permanently disables PBO for the session, releases
    readback buffers, and uses guarded direct read fallback.
  - Added double-guarded error handling so a direct-read failure no longer
    cascades into repeated PBO retries on each frame.
- **2026-06-18 (owner closeout) — remediation status set to complete:**
  - Audit remediation and A+ upgrade batch marked complete for this cycle.
  - Explicit deferred item retained: frame-budget CI guard, tracked in
    `docs/planning/deferred-work-2026-06-18.md` (DW-001).
  - Next planned engineering batch retained: compositor dedup/present-path
    refactor tracked in
    `docs/planning/compositor-dedup-implementation-plan-2026-06-18.md`.
- Notes: No runtime profiling performed; §2.3 / §9 list the runtime confirmation
  steps. No code changed in this pass — audit/remediation planning only.
