# Unicorn Viz — v1.0-RC1 Release Task List (2026-08-03)

Owner: owner (solo studio) + agents
Status: Active — the working checklist for the first public release
Last updated: 2026-08-04 (all non-decision P0s + 10 P1s complete)

Sources: [2026-08-03 full-system audit](../audits/2026-08-03-full-system-audit.md),
[2026-08-03 Windows platform report](../audits/2026-08-03-windows-platform-report.md),
[installers plan](installers.md),
[Windows native-deps field notes](../packaging/windows-native-deps-2026-07-11.md).

Legend: **[P0]** ship-blocker for RC1 · **[P1]** should land in RC1 ·
**[P2]** acceptable to slip to RC2/1.0 · **(D)** owner decision needed first.
Effort: S < half day · M ≈ 1-2 days · L ≈ 3+ days.

---

## A. Stability — crash/data-loss fixes (code)

- [x] **[P0][M]** Crash-isolate the main loop: wrap effect
      `update()`/`render()`/instantiation and hotkey dispatch in per-call
      guards that skip/advance past a broken effect instead of killing the
      show; put post-loop cleanup in `try/finally`; fix `_switch_effect`
      destroy-before-instantiate ordering. (`app.py:4377/5097/3965/3094/4957`) *(done — beta.19)*
- [x] **[P0][S-M]** streaming-01: move the ffmpeg stdin write off the render
      thread onto a bounded-queue writer thread with frame dropping (clone
      the recording.py pattern). (`rtmp_streamer.py:274`) *(done — streaming-01 0.5.1)*
- [x] **[P1][S]** streaming-01 `stop()`: escalate to `kill()` after the
      SIGINT/timeout rung so a wedged ffmpeg can't keep streaming. *(done — streaming-01 0.5.1)*
- [x] **[P1][S]** Surface recorder death: writer thread sets a failed flag;
      `is_recording`/HUD shows it instead of a lit REC over dropped frames.
      (`recording.py:78/267`) *(done — beta.23)*
- [x] **[P1][M]** Fix FBO rebuild leaks (release color texture + depth
      renderbuffer everywhere `_rebuild_fbos`/`_ensure_*_fbo` recreate, or
      set `ctx.gc_mode`). (`app.py:5440/6033/6114/6838`) *(done — beta.23: _release_fbo helper at all rebuild sites)*
- [x] **[P1][S]** Transition validation drift: add the six implemented
      transitions + aliases to `config.py` `_TRANSITIONS` and the CLI
      choices. (`config.py:143`) *(done — beta.23)*
- [x] **[P1][M]** videos-01: fix decoder-thread EOF blocking-put leak, the
      no-audio-device frozen-clock path, and the dead `reached_bottom`
      contract (auto-advance parks otherwise). *(done — videos-01 0.7.1)*
- [ ] **[P2][M]** Recording capture: reuse the existing streaming PBO path
      instead of the synchronous per-frame drawable read.
- [ ] **[P2][S]** video-clips-01: move `cap.read()`/seek off `render()`.

## B. Windows platform (primary target — see the Windows report)

- [x] **[P0][S]** Fonts: shared font-resolver that tries bundled
      `assets/fonts/ui-font.ttf` first, then platform dirs incl.
      `C:\Windows\Fonts` (+ `seguiemj.ttf` for the emoji path); adopt in
      dj-mixer/control-room/media/banner/now-spinning/CTA/tour loaders. *(done — beta.21 + control-room 0.9.1 / media 0.16.1 / banner 0.8.1; dj-mixer adoption handed to the mixer team — their tree is in flight)*
- [x] **[P0][S-M]** DPI awareness: `SDL_HINT_WINDOWS_DPI_AWARENESS=
      "permonitorv2"` + `SDL_WINDOW_ALLOW_HIGHDPI` + drawable-size audit;
      re-verify the 3840 icon-bucket threshold. *(done — beta.21; verify on scaled display per test protocol)*
- [x] **[P0][M]** ffmpeg audio capture on Windows: platform-aware default
      (`dshow`), device resolution without `pactl`, and a Windows-safe
      graceful stop (`CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT` — no
      `send_signal(SIGINT)`). *(done — beta.21 + streaming-01 0.5.2)*
- [ ] **[P1][M]** Multi-head state re-derivation: handle
      `SDL_WINDOWEVENT_MOVED`/`DISPLAY_CHANGED`, re-derive display/origin on
      `FOCUS_GAINED` (July item 5); re-test span/mirror under mixed DPI. *(code landed — beta.25, conservative/validity-gated; NEEDS owner multi-monitor verification)*
- [ ] **[P1][—]** Run the Windows test protocol (report §3) end-to-end on a
      mixed-DPI two-monitor machine; file whatever it shakes out.
- [ ] **[P2][—]** Verify WASAPI system-audio loopback capture on real
      hardware; document the setup path (Stereo Mix / VB-Cable) or build a
      loopback-specific capture path.
- [ ] **[P2][—]** Verify APC mini LEDs over plain rtmidi on Windows; verify
      DDJ-REV1 device naming under WASAPI.

## C. Distribution & packaging

- [ ] **[P0][D]** Decide the public drop-in channel: all 39 submodules are
      private SSH — a public clone gets zero drop-ins. Options: public
      mirrors, HTTPS deploy keys, or the installers.md model (core tarball +
      per-channel drop-in packages via `unicorn-viz dropins install`). Then
      build the chosen path.
- [x] **[P0][S]** Fix `pyproject.toml`: version → current (single-source it
      from `unicornviz.__version__` if possible); add missing deps (psutil,
      opencv-python-headless, soundfile, python-osc). *(done — beta.21: dynamic version from unicornviz.__version__, deps added)*
- [ ] **[P0][D]** Repo identity: resolve the README dev-repo vs
      `djunicorntears` canonical-repo confusion and the "repo will move"
      banner before strangers read it.
- [x] **[P1][S]** Pin `requirements.txt` (`==` or constraints file) for the
      RC; keep `>=` floors in pyproject. *(done — beta.23: == pins, floors stay in pyproject)*
- [ ] **[P1][L]** Windows installer ★1 → ★3 per installers.md P3: curated
      payload, embedded Python 3.11/3.12 (dodges the cp314 wheel gap in the
      field notes), bundled ffmpeg, prebuilt rtmidi/moderngl wheels; or, as
      the bridge, ship `tools/install/windows_deps.ps1` from the field notes. *(bridge shipped — tools/install/windows_deps.ps1, untested on real Windows; ★3 payload work remains)*
- [ ] **[P1][S]** Scrub `config.toml` shipped defaults for first-boot on a
      stranger's machine: `display_index = 3`, hardware device strings,
      dj-mixer `enabled/start_enabled = true`, `"DDJ-REV1, Windows WASAPI"`.
      **(D — owner edits their own config; needs a "shipped defaults vs owner
      rig" split, e.g. config.toml.example.)**
- [ ] **[P2][S]** Delete projectm-01's untracked `preset-trash/`; decide
      whether `plan.md` moves to `docs/planning/` (root-docs rule).

## D. Security & tests

- [x] **[P1][S]** chat-01: add the inbound-text-is-inert regression test
      (SECURITY.md asserts it in writing; nothing encodes it). *(done — chat-01 0.5.1)*
- [x] **[P1][S]** spotify-01: handle HTTP 429 + `Retry-After` with backoff;
      chmod the token store 0600. *(done — spotify-01 1.0.0-rc.3)*
- [x] **[P1][S]** webcam-01: don't open the camera while nothing renders
      (`pip_position = "hidden"` + enabled default = webcam LED on at first
      boot — privacy optics for a public release). *(done — webcam-01 1.0.0-rc.2)*
- [ ] ~~CI: push/PR pytest workflow~~ **WITHDRAWN (2026-08-06, owner rule):**
      **no GitHub workflows except by the installer team.** The tests.yml
      added in beta.23 is removed; test gating stays local (pre-commit).
- [x] **[P2][S]** images-01: cap the image cache (count/resolution) before
      strangers point it at photo libraries. *(done — images-01 0.8.1)*
- [ ] **[P2][S]** Clean the stale `# nosec` (training_daemon.py:203) and
      justify the four bare `# nosec B310` (spotify ×3, lyrics ×1). **(D —
      report-only per CLAUDE.md until owner approves.)**

## E. Effects quality (one systemic pass)

- [x] **[P1][M]** Float32 time/hash pass across ~15 effects (audit §8): (a)
      integrate audio-modulated speeds in `update()` (nebula_drift pattern)
      — sun_ship_3000, asteroid_run, canyon_run, portal_flight, warp_drive,
      wingsuit_dive, tunnel; (b) `mod()` time-derived hash inputs
      (asteroid_run pattern) — threat_matrix, hacker_terminal_v2,
      reactor_breach, vector, alien_invasion, cosmos, cloud_surfer,
      america_250, van_gogh. Several currently ship with their signature
      layer dead or strobing. *(done — flying-01 0.2.0, cosmic-01 0.11.0, immersive-01 0.10.0, holiday-01 0.5.1, retro-01 0.9.1, vector-01 0.9.1; tech-01 Class-B fixed earlier in 0.10.0. Fixes are pattern-faithful to nebula_drift but visual — worth one live eyeball pass.)*
- [x] **[P1][S]** cyber_war: replace `np.random.seed(42)` global reseed with
      `self.rng`; randomize the node board. *(done — tech-01 0.9.1)*
- [x] **[P2][S]** hacker_terminal_v2: dirty-flag the glyph upload (~2,560
      allocs/frame today); consider an integer texture (uniform-component
      limit risk). *(done — tech-01 0.10.0)*
- [ ] **[P2][S-M]** wormhole: fix shell occlusion (dead core/materials) and
      drop the dead soft-shadow pass; fractal_zoom: lower `_zoom_ceiling` to
      ~3×10⁴ pending a perturbation path.
- [ ] **[P2][S]** Randomization polish: kaleidoscope segments/zoom,
      copper_bars start mode, dali palette/layout, sim_showcase seed-42
      galaxy, ansi_viewer/projectm `random`-module slips.

## F. Docs & governance

- [x] **[P1][S]** docs/drop-ins.md: add the 4 missing drop-ins
      (candy-frame-01, chat-01, cta-01, training-kit-01). *(done — beta.23)*
- [ ] **[P1][S]** Review the 11 help-less named hotkeys — bless or document
      each (H overlay is the single source of truth).
- [ ] **[P2][S]** Update CLAUDE.md: requirements "pinned" claim, primary
      target platform wording (Windows-first for release), font8x16/font8x8
      atlas naming drift.
- [ ] **[P2][S]** control-room/dj-mixer/multi-head troubleshooting docs: one
      refresh pass now that the July second-window fixes are confirmed.

## G. Deferred (explicitly not RC1)

- Mono-file split items C/D/E (app.py 7,120 / overlays.py 6,321 — resume
  after RC1, before the context-menu mission grows them again).
- Frame-budget CI guard (DW-001) and compositor dedup (standing deferred).
- macOS channel (☆ today) — per installers.md, post-RC1.
- Test dirs for multi-head-01/midi-controllers-01.
- Screenshot path fix + async PNG encode; log-band `isEnabledFor` gating;
  public-surface stragglers; icon-set leak on DPI-bucket change.

---

## Suggested sequencing

1. **Week 1 — stability + Windows P0s** (A1-A2, B1-B3): all S/M items,
   independently landable, each removes a whole failure class.
2. **Week 2 — distribution decisions + plumbing** (C1-C4, D4): the (D) items
   need owner calls first; CI and pyproject are mechanical.
3. **Week 3 — Windows installer bridge + full Windows test protocol**
   (B4-B5, C5), effects systemic pass (E1) in parallel.
4. **RC1 tag** once: Windows protocol passes on a clean machine, a stranger
   can install by following README alone, and the P0/P1 stability list is
   empty. Everything in §G rides to RC2/1.0.
