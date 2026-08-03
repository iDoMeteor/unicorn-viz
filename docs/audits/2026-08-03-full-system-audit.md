# Unicorn Viz — Full System Audit (2026-08-03) — Final Pre-RC1

Owner: owner + Claude (master coordinator)
Status: Complete
Last updated: 2026-08-03

Scope: whole-system final pass before **v1.0-RC1, the first public release** —
core runtime, core UI/ANSI, audio pipeline, all 39 drop-ins, effects (all ~44
read at GLSL level), security posture, live tooling (pytest/bandit/pip-audit),
release/packaging readiness, and prior-audit open-item verification. Extra
diligence on bugs and performance per owner direction. A dedicated companion
report covers Windows:
[2026-08-03-windows-platform-report.md](2026-08-03-windows-platform-report.md).
The actionable rollup lives in
[docs/planning/rc1-release-task-list-2026-08-03.md](../planning/rc1-release-task-list-2026-08-03.md).

Prior audit: [2026-07-01-full-system-audit.md](2026-07-01-full-system-audit.md)
(plus the closed [2026-07-08 render-pipeline/platform audit](2026-07-08-render-pipeline-platform-audit.md)).

Method: parallel area reviews (core runtime, UI, audio, controllers,
media/network drop-ins, effect packs, Windows portability, live tooling)
synthesized and spot-verified by the coordinator. Live tooling was actually
run (full pytest, bandit, pip-audit, submodule status). No GPU profiling this
pass. Note: in-flight config-menu work in `dj-mixer-01` was excluded from
findings per owner direction.

---

## 0) Executive Summary

Since 2026-07-01: **+471 commits**, drop-ins **35 → 39**, core at
**1.0.0-beta.17**, core tests **298 → 1,083 (all green, 8 s)**. The system's
internals are in the best shape they have ever been — threading discipline,
drop-in independence, security posture, and test count are all strong. What
stands between this codebase and a credible first public RC is **not** core
quality: it is (a) a handful of specific crash/perf bugs listed below, (b) the
**release plumbing** (private SSH submodules, stale pyproject, unpinned deps,
no push-CI), and (c) the **Windows platform gap** (primary target platform,
★1 installer, several Linux-only defaults — see companion report).

| Area | Grade | One-line |
|------|-------|----------|
| Core runtime (app/main loop) | B- | Strong threading + independence, but **no crash isolation around effects/hotkeys** (P1), FBO-attachment VRAM leak, sync recording readback. |
| Core UI / overlays / ANSI | A- | Atlas-based text, one-shot icon loads, thorough destroy; one small icon-set leak on DPI-bucket change. |
| Audio pipeline | A | Double-buffered snapshots, epsilon-guarded math, preallocated buffers, blocking-read reader thread — textbook. |
| Controller drop-ins | B+ | July second-window GL architecture intact and consistently applied; display-state invalidation gap (July item 5) still open; multi-head/midi-controllers lack test dirs. |
| Media/network drop-ins | B | One P1 (streaming blocking pipe write on render thread); videos-01 leak/freeze pair; webcam capture-while-hidden default; several A-grade members. |
| Effect packs (~44 effects) | B- | Zero crash-class bugs; **systemic float32 time/hash degradation** silently kills or scrambles layers in ~15 effects (§8). |
| Overlay/frame drop-ins | A- | Proper FBO resize/destroy structure, idle gating; no hot-path violations found. |
| Security (static + deps + runtime) | A- | bandit clean, pip-audit clean, chat-01 default flipped off + inbound text verified inert (test still missing). |
| Tests / CI | B+ | 1,083 green core tests, but **no push/PR CI test gate** — local pre-commit is the only automatic gate. |
| Release / packaging readiness | C | Private SSH submodule URLs, pyproject stale at beta.1 + missing deps, unpinned requirements, Windows installer at ★1. |

**Overall: B+.** Down from A- on 07-01 — not because the code got worse (it
got better), but because this audit grades against a harder bar: "ready for
strangers." The remediation list (§10) is concrete and finite.

---

## 1) Scale Delta Since 2026-07-01

| Metric | 2026-07-01 | 2026-08-03 |
|--------|-----------|-----------|
| Commits in window | — | **+471** |
| Drop-ins | 35 | **39** |
| Core version | 1.0.0-beta.x | **1.0.0-beta.17** |
| Core `app.py` | 5,472 | **7,120** (+30%) |
| Core `overlays.py` | 4,711 | **6,321** (+34%) |
| Core tests (green) | 298 | **1,083** |
| dj-mixer-01 | new | **0.137.0**, 38 test files |

Major landings this window: dj-mixer-01 matured into the largest drop-in
(analysis pipeline with `ANALYSIS_VERSION` discipline, stems, pad-face cache,
rtkit realtime audio), first-run tour, tooltips system, config editor,
secondary-GL-window architecture (July), audio-out/program-feed work, and the
second-window crash/black-screen investigation closed owner-confirmed.

---

## 2) Live Tooling Results

- **pytest:** `tests/` → **1,083 passed, 0 failed, 0 skipped** (7.9 s). The
  hotkey-parity test warns (does not fail) that 11 named keys have no help
  entry — intentional easter-egg carve-out, worth one pre-RC1 review.
  `drop-ins/control-room-01/tests` → 12 passed.
- **bandit:** `-ll` clean on both `unicornviz/` and `drop-ins/` (note:
  `pyproject.toml` skips B101/B404/B603/B607). 9 non-test `# nosec`
  annotations; one is **stale** (training_daemon.py:203 suppresses nothing)
  and four `# nosec B310` (spotify-01 ×3, lyrics-01 ×1) lack justification
  text. Reported only, per policy — no remediation performed.
- **pip-audit:** no known vulnerabilities. The pre-commit hook's broken `-q`
  flag (07-01 P2) is **fixed**, but the hook is `stages: [manual]` — it never
  runs automatically.
- **Submodules:** all **39 pointers in sync** (zero ahead/uninitialized). The
  `?` on projectm-01 is an uncommitted `preset-trash/` dir inside that
  submodule's working tree — litter, not a pointer problem.

### Prior-audit (2026-07-01) open items — verified

| Item | Status |
|---|---|
| chat-01 `enabled = true` default | **Fixed** — `config.toml` ships `enabled = false`. |
| SECURITY.md network enumeration | **Fixed** — enumerates fetch tool, spotify, chat (Ably), lyrics; auto-vj has no runtime network I/O so the list is accurate. |
| pip-audit hook `-q` flag | **Fixed.** |
| chat-01 / media-01 `docs/` dirs | **Fixed** — both exist. |
| Submodule pointers uncommitted | **Fixed** — all 39 committed. |
| chat-01 inbound-text-inert regression test | **Still open** — chat-01 has no tests at all; SECURITY.md makes the inertness claim in writing with no test encoding it. |
| Mono-file growth (resume items C/D/E) | **Worse** — app.py +30%, overlays.py +34% since 07-01. |

---

## 3) Core Runtime — B-

Verified clean: all drop-in load sites try/except-guarded with functional
fallbacks, no bare drop-in imports; MIDI callback → locked deque → main-thread
dispatch; audio snapshots lock-copied; recorder frames written off-thread on a
bounded queue.

### P1

1. **No exception isolation around effect `update()`/`render()`/instantiation
   or hotkey dispatch; post-loop cleanup is not in `try/finally`**
   (`app.py:4377`, `:5097`, `:3965`, `:3094`, `:4957`). One driver-dependent
   shader-compile failure or one bug in any of ~44 effects kills the live show
   and skips audio/MIDI/recorder/SDL teardown. Secondary: `_switch_effect`
   destroys the outgoing effect before instantiating the incoming one, so a
   raise mid-switch leaves a destroyed instance current. Every *subsystem* is
   individually guarded — effects and hotkeys, the highest-churn code in the
   process, are not. **This is the single most important pre-RC1 fix.**

### P2

2. **FBO rebuilds leak color textures + depth renderbuffers**
   (`app.py:5440`, `:6033`, `:6114`, `:6838`); no `ctx.gc_mode` is set, so
   each render-scale nudge/resize leaks ~16 MB at 1080p until VRAM exhaustion
   (`_make_or_get_mirror_composite_fbo` shows the correct release-attachments
   pattern).
3. **Recording does a synchronous full-drawable readback every recorded
   frame** (`app.py:4845 → 6088 → 6292`) while the streaming path already has
   double-buffered PBOs — recording a spanned show degrades the live output.
4. **A dead ffmpeg is silently ignored** (`recording.py:78`, `:267`): REC
   stays lit, frames keep being read and dropped; the operator learns after
   the show. Writer thread should flip a failed flag surfaced by the HUD.
5. **Transition validation drift** (`config.py:143` vs `app.py:94/3098`): six
   implemented transitions (`radialwipe`, `lumawipe`, `stripewipe`,
   `anglesweep`, `glitchsoft`, `prismsplit`) are rejected by `cfg.validate()`
   with a fatal exit; `--transition` CLI choices have the same drift.
6. **`S` screenshot uses the broken default-framebuffer read path**
   (`hotkeys.py:1899`) that `app.py:531` documents and works around with
   `read_screenshot_frame()` — plus synchronous PNG encode on the render
   thread (visible hitch).

### P3 (summarized)

Log-band design defeats `isEnabledFor` gating (per-frame debug records built
then discarded); streaming-indicator drawn into staging FBO on single display;
subsystem-present budget guard misfires at ≤40 Hz refresh (secondary windows
throttled to ~7.5 fps on 30 Hz outputs); transition composite feeds stale
`fbo_a` to overlay layers; double-invoke on renderer TypeError; playlist
`--sequence` silently ignores display names; a handful of public-surface
stragglers (`a._auto_advance`, `overlays._name_text`); double JSON persist per
runtime-state keypress; `now_playing.active()` runs every source snapshot
twice per frame.

---

## 4) Core UI / Overlays / ANSI — A-

- **Hot path is disciplined:** HUD text renders from a one-shot glyph atlas
  (bundled `assets/fonts/ui-font.ttf` first candidate); tooltips draw via
  atlas `_draw_text`, no per-frame PIL or texture churn; now-spinning card
  rebuilds its PIL texture on a timer, not per frame; help icons load once
  per bucket, unflipped/unresampled per the asset rule.
- **P3:** `_load_help_icon_textures()` (`overlays.py:860`) resets the texture
  dict without releasing the old set; the bucket-change path
  (`overlays.py:6146`) therefore leaks one full icon set each time the window
  crosses the 3840 px width boundary.
- **P3:** `Overlays.destroy()` is thorough for its tracked objects, but the
  tour/splash big-text path (`overlays.py:6272`) builds one-shot PIL textures
  whose release depends on local call-site hygiene — worth one sweep.
- **ANSI/CP437 compliant:** single parser, `cp437` decode everywhere
  (`ansi/loader.py:81-83`), SAUCE detected/stripped with graceful absence
  handling. retro-01's viewer uses the canonical loader (its cycle-mode
  blocking-load P2 is filed under effects, §8).
- Doc nit: CLAUDE.md names `font8x16.bin` as the CP437 atlas; the overlay
  fallback actually reads `font8x8.bin` (both ship in `assets/fonts/`).

---

## 5) Audio Pipeline — A

- Capture is a **blocking-read daemon thread** draining PortAudio into a
  bounded deque under a lock — a GIL hold on the render thread cannot xrun;
  buffer swap on device change is lock-protected (`capture.py:395`).
- Analysis publishes via **double buffer + in-place field copy** — zero
  allocation per frame on either side (`manager.py:95-128`).
- Every division/log in the analyzer is epsilon-guarded (silence-safe); FFT
  work buffers and Hann windows are preallocated/cached
  (`analyzer.py:113-183`, `:410`).
- Device ranking is deliberately platform-aware (Linux: PipeWire/Pulse
  monitors first, raw ALSA excluded; Windows: WASAPI loopback → stereo mix).
- No findings at P1/P2. This subsystem is release-ready.

---

## 6) Controller Drop-ins — B+

- **July second-window GL architecture verified intact:**
  `rebind_main_gl_context()` on open/close in both control-room-01 and
  dj-mixer-01 (`dj_mixer_controller.py:739/756`, `ui.py:862`,
  `control_room.py:594`), plus the per-frame `_present_subsystems()`
  rebind-on-any-attempt with its frame-budget skip guard (`app.py:895-935`).
  The known cosmetic gate looseness (mixer `present()` is always callable →
  rebind fires even with the window closed) is unchanged and still cheap.
- **P2 — July item 5 never landed:** `SDL_WINDOWEVENT_FOCUS_GAINED` still
  only toggles cursor visibility (`app.py:3988`); there is still no
  `MOVED`/`DISPLAY_CHANGED` handling, and multi-head display-layout state
  still refreshes only on hotplug. This is the standing wrong-monitor-overlay
  bug on Linux workspace switches **and** the leading code-level suspect for
  the Windows multi-head misbehavior (see companion report).
- **P3:** multi-head-01 (`1.0.0-rc.1`) and midi-controllers-01 have **no
  tests/ dirs** — the two most hardware/geometry-dependent drop-ins are only
  indirectly covered by core tests.
- midi-controllers-01's LED stack is well-layered (libusb → rawmidi →
  rawmidi-out → rtmidi fallback) with the snd_ump rationale documented.
- osc-bridge-01: default-off, enqueue-only server thread, clean
  shutdown/close. dj-mixer-01: `ANALYSIS_VERSION = 2` carries the required
  history block; store writes use atomic `Path.replace`.

---

## 7) Media / Network Drop-ins — B

### P1

1. **streaming-01: synchronous, untimed `proc.stdin.write()` of a full RGB
   frame on the main render thread** (`rtmp_streamer.py:274-284`, called from
   `app.py:4896`). A stalled RTMP endpoint back-pressures ffmpeg → the pipe
   write blocks forever → **the whole show freezes**, unrecoverable in-app.
   Recording already has the correct pattern (dedicated writer thread,
   bounded queue); streaming needs the same.

### P2 (full detail in the area report; headlines)

- **videos-01:** decoder-thread EOF sentinel does a blocking `put` into a
  full queue → leaked thread + ~24-95 MB per activation switch; audio-clock
  design freezes video on first frame when no output device opens;
  `reached_bottom` contract is dead (EOF flag reset same-tick), so
  auto-advance parks on VideoPlayer.
- **video-clips-01:** synchronous `cap.read()`/seek for two clips inside
  `render()` — blows the frame budget on real 1080p material.
- **webcam-01:** ships capturing at 30 fps while hidden (`pip_position =
  "hidden"` + enabled default) — webcam LED on at first boot is a privacy
  optics problem for a public release; also double-copy/upload per displayed
  frame and inverted `flip_horizontal` semantics.
- **spotify-01:** no HTTP 429/`Retry-After` handling (violates the CLAUDE.md
  Spotify rule); token store written world-readable (0644); two blocking
  `playerctl` subprocess calls on the main thread per 0.75 s poll.
- **streaming-01:** `stop()` never escalates to SIGKILL → orphaned live
  ffmpeg keeps streaming with no in-app remedy.
- **images-01:** unbounded module-level RAM/VRAM cache of the entire
  configured image tree — needs a cap before strangers point it at photo
  libraries.

### Clean bills

spotify-01 auth is textbook PKCE (S256, loopback 127.0.0.1, state check,
minimal scopes, timeouts on every request). lyrics-01 has the best network
posture in the tree. chat-01 inbound text confirmed inert (truncated, glyph
atlas, control chars mapped to space). All network drop-ins degrade
gracefully offline. No secrets committed anywhere.

---

## 8) Effects — B- (packs) / A- (overlay drop-ins)

All ~44 effects were read at GLSL level. **Zero crash-class findings** — the
July `KeyError: 'iBass'` bug in feature-01/rainbow_trance is **fixed** (the
shader now uses the uniform), destroy() coverage is complete everywhere
sampled, no stripped-uniform writes remain unguarded, and no divide-by-zero
at silent audio exists anywhere.

### The systemic finding: float32 time/hash degradation (~15 effects)

`BaseEffect.time` starts at uniform(0, 10,000) and grows forever. Two
recurring GLSL patterns interact badly with that:

- **Class A — audio-varying multiplier on unbounded time** (`t * (k +
  audioTerm)`): a per-frame audio delta shifts phase by hundreds of cycles,
  so the element *teleports* every frame while music plays. Affects:
  sun_ship_3000, asteroid_run, canyon_run, portal_flight, warp_drive,
  wingsuit_dive (ridge), tunnel (hue strobe). Fix pattern already exists
  in-tree: integrate speed in `update()` (nebula_drift's `_depth`).
- **Class B — hash-input magnitude collapse** (time-scaled coords through
  `fract(sin(dot(...)*bigK))` past 2²³): the hash flatlines, silently killing
  the layer. Affects: threat_matrix (rain layer renders black — its signature
  visual), hacker_terminal_v2 (glitch row frozen), reactor_breach (sparks
  static), vector.py (sparkles dead), alien_invasion (motes frozen), cosmos
  (starfield banding), cloud_surfer (fbm octaves collapse), america_250
  (sparkle), van_gogh (stars/streaks), dali/wavey_gravy (mild). Fix pattern
  also in-tree: `mod()` the time term pre-hash (asteroid_run/nebula_drift).

These are quiet visual-quality regressions, not crashes — but several kill an
effect's *headline* layer, and for a first public release the fix is one
systemic pass, not 15 individual ones.

### Other notable effect findings

- **P2 cyber_war.py:160:** `np.random.seed(42)` + legacy global `np.random`
  builds the node board — identical every run *and* reseeds the process-wide
  legacy RNG for any other consumer.
- **P2 hacker_terminal_v2.py:387:** ~2,560 Python object allocations per
  frame re-uploading a mostly-static 2,400-int uniform array (dirty-flag +
  `write()` fixes it); its 2,560-component uniform block also exceeds the GL
  3.3 guaranteed minimum (link risk on conservative drivers).
- **P2 wormhole.py:** the opaque bounding shell occludes the entire
  refractive core/ring/arc content (dead materials), and an unconditional
  36-step soft-shadow on dead geometry makes it the most expensive shader in
  the sweep — likely over the 8 ms budget.
- **P2 fractal_zoom.py:187:** zoom ceiling (up to 3.2×10⁶) is ~1.5 orders of
  magnitude past float32 precision at 1080p — the last ~35-90 s of every
  cycle renders precision mush, contradicting the docstring's own claim.
- **P2 starfield.py:151 / ansi_viewer.py:198:** 180-iteration beat-gated
  per-pixel loop near the budget; blocking file-I/O ANSI reload inside
  `update()` when `cycle_files` is enabled (default off).
- **Randomization compliance** is broadly good (galaga/games-01 and
  fractal_zoom exemplary); violators worth one pass: kaleidoscope (fixed
  12-fold symmetry), copper_bars (fixed first 15 s), dali (fixed layout/
  palette), sim_showcase's seed-42 fallback galaxy, ansi_viewer + projectm
  `random`-module slips.
- **games-01:** fully compliant on lifecycle/rng/bounded-CPU-sim checks
  (structural pass; GLSL bodies not individually re-read this cycle).
- **Overlay drop-ins** (banner/beat-flash/candy/color-grade/cta/finale/
  postfx/tears): FBO+resize+destroy structure sound, postfx gates its passes
  on `is_active()`, banner reuses textures via `_ensure_texture`. No hot-path
  violations found.

---

## 9) Release / Packaging Readiness — C

1. **P1 — All 39 submodule URLs are SSH to private repos**
   (`git@github.com:iDoMeteor/unicorn-viz-dropin-*`). A public
   `git clone --recurse-submodules` cannot fetch a single drop-in. This is
   consistent with the private drop-in policy, but the release channel
   (public mirrors? HTTPS? the installers.md core-tarball + per-channel
   drop-in packaging model?) must be **decided and built** before RC1.
2. **P1 — pyproject.toml is wrong for any packaged install:** version
   `1.0.0-beta.1` (16 betas stale) and `[project] dependencies` missing
   psutil, opencv-python-headless, soundfile, python-osc.
3. **P2 — requirements.txt is fully unpinned** (`>=` only) — contradicts
   CLAUDE.md's "pinned" claim; RC installs are not reproducible.
4. **P2 — No push/PR CI test run** — only nightly installer smoke + manual
   compat matrix exist; the 1,083-test suite gates nothing automatically.
5. **P2 — config.toml ships machine-specific uncommented values** a fresh
   user inherits: `[control_room] display_index = 3`, `output_device =
   "DDJ-REV1, Windows WASAPI"`, APC/REV1 device names, dj-mixer
   `enabled/start_enabled = true` (mixer window + REV1 open at first boot).
6. **P2 — docs/drop-ins.md registry missing 4 of 39** (candy-frame-01,
   chat-01, cta-01, training-kit-01); root-level `plan.md` violates the
   root-docs rule and is stale (May 18 focus header).
7. **P3 —** README repo-identity confusion (Quick Start clones the dev repo
   while the notice declares djunicorntears canonical + "repo will move"
   banner); stale/bare `# nosec` annotations (§2); projectm-01
   `preset-trash/` litter; Windows installer at ★1 vs Linux ★3-4 (see the
   Windows report and installers.md).

---

## 10) Prioritized Remediation Plan

The full actionable breakdown (owner decisions, effort estimates, sequencing)
is in the RC1 task list. Summary:

**P1 — release blockers**
1. Crash-isolate effects + hotkeys in the main loop; `try/finally` the
   cleanup path (§3.1).
2. Fix streaming-01's render-thread pipe write (§7.1).
3. Decide + implement the public drop-in distribution channel (§9.1).
4. Fix pyproject version/dependencies (§9.2).
5. Windows P1 set (fonts, DPI awareness, ffmpeg audio defaults + stop path)
   — see companion report.

**P2 — should fix before RC1**
FBO-attachment leak; recorder-death surfacing; recording readback via
existing PBO path; transition-validation drift; videos-01 leak/freeze pair;
webcam capture-while-hidden default; spotify 429 + token perms; streaming
stop escalation; images-01 cache cap; systemic effects time/hash pass;
cyber_war global reseed; multi-head display-state re-derivation (July item
5); pin requirements; add push CI running pytest; scrub config.toml defaults;
chat-01 inertness regression test; docs registry + plan.md relocation.

**P3 — post-RC1 acceptable**
Mono-file split resumption (items C/D/E — app.py is 7,120 lines and the
context-menu mission will grow it again); log-band gating; screenshot path;
public-surface stragglers; effect randomization polish pass; icon-set
leak-on-bucket-change; hotkey help-entry review for the 11 unlisted keys;
test dirs for multi-head-01/midi-controllers-01.

---

## Session Log

- Date: 2026-08-03
- Reviewer: Claude (master coordinator), parallel area reviews + direct
  verification of all cited call sites.
- Tooling run: full pytest (1,083 green), bandit (clean at -ll), pip-audit
  (clean), submodule reconciliation (39/39 in sync).
- Headline: internals strong (audio A, UI A-, security A-); release blockers
  are concentrated in main-loop crash isolation, streaming back-pressure,
  distribution plumbing, and the Windows platform gap.
- Prior-audit items: 5 of 7 closed; chat-01 inertness test and mono-file
  growth remain open.
- No code changed in this pass — audit + reports only.
