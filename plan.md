# Unicorn Viz Plan

## Status Legend

- `[todo]` not started
- `[doing]` actively in progress
- `[done]` completed
- `[decision]` needs product/architecture decision

## Current Focus (May 18, 2026)

- `[doing]` **Pre-release future-proofing pass** — see `plan-future-proofing.md` for the full audit
  and remediation checklist (FP-01 through FP-13).  Must complete all 🔴 and 🟠 items before v1.0 tag.
- `[todo]` Effect review pass — systematic quality/perf pass across existing built-in effects.
- `[done]` RTMP streaming subsystem drop-in.
- `[todo]` Validate ProjectM on primary F44 machine and continue polish there.
- `[todo]` Design vignette/post-process system (see Phase 4).
- `[todo]` Design external plugin loading for paid effect packs.
- `[done]` Hotkey UX remap pass (mnemonic grouping + live-performance ergonomics).
- `[done]` Add optional global keystroke logging (`logs/keystrokes-*.log`) with beat-context snapshot (bpm, beat_phase, energy, vj_mode) per keypress; gated by `[keystrokes] enabled = false`.
- `[todo]` Plan multi-display overlay policy so help/HUD/flash render only on primary display in `span_all` / `mirror_all` when enabled.
- `[todo]` Design a "grand finale" effect sequence for set-ending moments (audio-linked crescendo + controlled cooldown).
- `[todo]` Design Drop strategy pivot from effect-tag targeting toward post-fx profile targeting (hard-hit look first, effect swap second).
- `[done]` Add effect metadata concept `PING_PONG_FRIENDS` for preferred pairings when randomizing ping-pong slots.
- `[todo]` Design scroll-wheel hue-shift post-fx control (wheel direction shifts hue, idle timeout clears, middle-click clears; middle-click toggles Auto VJ only when hue-shift inactive).

## Phase 1 — Runtime, CLI, and Operational Foundations

- `[done]` Audit the codebase for optimization opportunities, architectural inconsistencies, and cleanup candidates.
  Current findings:
  - runtime/logging/config/docs drift was corrected
  - low-risk runtime cleanup and allocation cleanup landed in the app/audio/effect hot paths
  - built-in recording landed with auto-record, configurable output, live-only indicator behavior, and Linux audio mux support
  - stale helper cleanup (for superseded audio-device logic) can be folded into a future cleanup PR
- `[done]` Add structured log output under `logs/`.
- `[done]` Add configurable log level via config and command line.
- `[done]` Add command-line overrides for common config values.
- `[done]` Add a robust `-h` / `--help` CLI entrypoint.
- `[done]` Update all documentation to reflect runtime/config/CLI behavior.
- `[done]` Add built-in MP4 recording with configurable directory and auto-record support.

## Phase 2 — Platform and Display Support

- `[done]` Add first-class Windows support.
  Notes:
  - implemented: Windows-safe SDL driver default path (no forced Wayland)
  - implemented: Windows loopback/stereo-mix candidate audio selection logic
  - implemented: windows-latest CI smoke job for CLI + effect discovery
  - implemented: Windows installer + launcher hardening (`install_windows.ps1` + `.bat` wrapper)
  - validated: installer and runtime tested on physical Windows 11 host
- `[done]` Add multi-monitor support.
  Notes:
  - implemented: explicit `window.display_index` / `--display-index` selection for startup and fullscreen target display
  - implemented: `display_mode` options (`single`, `span_all`, `mirror_all`)
  - implemented: runtime display-mode hotkeys (`X`, `Shift+X`, `Ctrl+X`, `Alt+X`)
  - implemented: GL-native single-window `mirror_all` tile-blit path (cross-platform stable)
  - validated: mirror mode works on Fedora 37/GNOME, Fedora 44/MATE, and Windows 11
- `[done]` Refactor multi-monitor implementation into a drop-in subsystem module.
  Notes:
  - canonical implementation now lives in `drop-ins/multi-head-01` private submodule
  - app runtime now loads multi-head controller directly from drop-in source
  - remaining optimization pass tracked under multi-monitor implementation work
- `[done]` Verify recent Ubuntu/Debian and Fedora compatibility matrix.
  Notes:
  - implemented: `tools/compat_matrix.sh` (Ubuntu 22.04, Debian 12, Fedora 44)
  - implemented: `.github/workflows/compat-matrix.yml` for CI validation
- `[done]` Build a robust installer for supported Linux distributions.
  Notes:
  - implemented: `tools/install_linux.sh` distro-aware bootstrap (apt/dnf/pacman)
  - includes venv creation and requirements installation
- `[done]` Evaluate packaging for Flatpak and Snap.
  Notes:
  - implemented: initial manifests under `packaging/flatpak` and `packaging/snap`
  - documented beta recommendation and current posture in developer docs
- `[todo]` Add config-gated overlay display scoping.
  Notes:
  - new global config flag to constrain help/HUD/flash overlays to primary display only
  - behavior applies in `span_all` and `mirror_all`; keep current behavior as fallback
  - land as opt-in first to avoid breaking current live workflows

## Phase 3 — Assets and Media Expansion

- `[done]` Add Performance HUD / diagnostics overlay for FPS, frame time, audio source, active transition, CPU, and RAM.
  Notes:
  - implemented modern TAB overlay branded `Unicorn Viz HUD`
  - implemented live runtime status feed (effect/transition/fps/frame-time/resolution/render-scale/playlist/state/reactivity/speed/audio source/recording/audio bands/display state)
  - includes system-monitor style diagnostics and modern game-UI presentation
- `[done]` Create Cyber War effect (drop-in: digital battle-map style with offensive/defensive node animations).
- `[done]` Create Hacker Terminal effect (drop-in: animated shell/log streams with glitch transitions).
- `[done]` Create Alien Invasion effect (drop-in: UFO fleets, atmospheric beams, planetary scan overlays).
- `[done]` Revamp Sine Scroller to Sine Scroller 2.0 (in-tree).
  Notes:
  - implemented multi-line wave animation with independent frequency per line
  - implemented polished color-per-beat transitions and bass-responsive amplification
  - implemented configurable text/font/speed behavior and reduced background dominance

- `[done]` Add `assets/images/` support.
  Notes:
  - implemented as drop-in `images-01`
  - loads still images from its own bundled `images/` folder by default
  - supports a single user-configurable `image_dir` override path (override, not addition)
  - implemented audio-reactive slideshow / Ken Burns style image presentation
- `[done]` Add `assets/textures/` support.
  Notes:
  - implemented as drop-in `textures-01` with configurable `texture_dirs`
  - includes 20 bundled patterns (including paisley and plaid)
  - implemented audio-reactive texture montage/showcase effect
- `[done]` Add `assets/videos/` support for MP4 playback.
  Notes:
  - implemented as drop-in `videos-01` (`Video Showcase`)
  - playlist integration complete
  - clip loading/playback integrated with effect transitions
  - baseline cross-platform validation performed during mirror-mode regression testing
- `[done]` Add webcam/video capture effect and overlay support.
  Notes:
  - implemented as subsystem drop-in `webcam-01` loaded at startup (not a playlist effect)
  - live camera PiP is rendered above every main effect, below the HUD
  - keypad layout control integrated (`KP0`, `KP.`, `KP1-9`, `KP-`, `KP+`)
  - camera treatments cycle with `KP/` and `KP*`; auto-cycle via `KP Enter`
  - the old webcam background visual was split into built-in effect `Psychedelic`
  - remaining: chroma-key/background replacement and cross-platform camera tuning
- `[todo]` Add `assets/sims/` support for IsaacLab/OpenUSD-style 3D animations.
  Notes:
  - playback/runtime format choice
  - audio sync hooks
  - GPU/runtime cost constraints
- `[todo]` Phase 3 review milestone: complete one full review pass across every existing built-in effect.
  Notes:
  - validate visual quality, audio reactivity, and parameter sanity effect-by-effect
  - capture any per-effect fixes/tuning required after the analyzer modernization
  - close this milestone when all Phase 3 asset/media tasks are complete and reviewed together

## Phase 4 — Product and Plugin Architecture

- `[todo]` Review and enhance each existing built-in effect before adding any new effects.
  Notes:
  - performance pass (GPU cost, allocations, frame budget)
  - consistency pass (parameters, naming, audio reactivity behavior)
  - visual polish pass (startup variance, transitions, readability)
  - documentation pass (effect-level options and expected behavior)
- `[todo]` Add global vignette / post-process pass system.
  Notes:
  - default global vignette strength/shape settings
  - per-effect opt-out/override for effects that already do their own edge darkening
  - decide whether vignette is a post-FBO pass or shader uniform convention
  - document which effects intentionally ignore the global setting
- `[done]` Add Ctrl+U screen burst effect (DJ-trigger: full 360° spin + 4× zoom, elastic recovery).
  Notes:
  - system-level post-process shader applied over the effect layer (0.60s animation)
  - works in all display modes: single, span_all, mirror_all
  - restartable mid-animation; does not interrupt the active effect
  - triggered by Ctrl+U; listed in `H` help overlay
- `[done]` Design frequency-response tuning system with genre profiles.
  Notes:
  - implemented `unicornviz/audio/profiles.py` with 12 genre-tuned profiles:
    house (default), trance, electronic, rap, hyphy, r&b, rock, generic,
    classical, ambient, pop, metal
  - each profile tunes bass/mid/treble frequency ranges, per-band weights,
    beat detection threshold, and FFT smoothing
  - Analyzer uses profile frequency splits instead of hardcoded Hz constants;
    `set_profile()` recalculates band slices at runtime
  - AudioManager loads profile from config (`audio.profile`)
  - `Alt+A` / `Alt+Shift+A` hotkeys cycle profiles at runtime; HUD shows active profile
  - `O` / `Shift+O` retained as legacy profile-cycle aliases
  - config.toml default: `profile = "house"`

- `[done]` Hotkey UX remap and consistency pass.
  Notes:
  - unicorn mnemonic layout: `u` = splash, `U` = Unicorn Tears, `Ctrl+u` = burst
  - art/source grouping: `a` = ACiD art, `Shift+A` = own ANSI art, `Ctrl+A` = audio source
  - audio profile cycling moved to `Alt+A` / `Alt+Shift+A` (legacy `O` aliases kept)
  - speed controls unified: `+/-` nudge, `Ctrl+=/-` max/min, `Alt+=/-` random on/off, `Ctrl+G` reset
  - render-scale controls moved to `,` / `.` cluster with Shift/Ctrl/Alt modifiers
  - display mode controls remapped for recovery-first behavior: `X` single, `Shift+X` span, `Ctrl+X` mirror, `Alt+X` config
  - help overlay and user docs updated with explicit lowercase/uppercase key labels
- `[decision]` Design external plugin loading for paid effect packs.
  Open questions:
  - local drop-in plugin directory vs hosted/cloud delivery
  - included effects vs third-party/paid effects separation
  - compatibility/version manifest format
  - licensing/entitlement enforcement model
  - security/trust boundary for executable plugin code
- `[todo]` Propose and prototype additional built-in effects and scene ideas.
- `[todo]` Add global scroll-wheel hue-shift post-fx interaction.
  Notes:
  - wheel up/down shifts global hue in opposite directions
  - effect stays active for X seconds after last scroll event (new scroll resets timer)
  - middle-click clears hue-shift immediately
  - when hue-shift is inactive, middle-click toggles Auto VJ if loaded
- `[todo]` Extend effect metadata with optional `ping_pong_friends` list.
  Notes:
  - used by ping-pong randomization to bias compatible pairings
  - fallback remains generic random when friend data is absent
  - keep backwards compatibility for effects that only define `TAGS`
- `[todo]` Rebalance Auto VJ Drop emphasis toward post-fx profiles.
  Notes:
  - prioritize selecting post-fx behavior families for Drop impact
  - treat effect-tag targeting as secondary/assistive signal
  - ensure cooldown/anti-storm logic still prevents visual spam
- `[todo]` Design and prototype "Grand Finale" system effect.
  Notes:
  - intent: end-of-set cinematic closer with deterministic progression
  - should blend system overlays, post-fx hits, and one dedicated finale visual
  - must include safe abort/exit path and configurable duration/intensity

## Phase 5 — Pre-Release Future-Proofing

> Full audit, findings, and remediation checklist in **`plan-future-proofing.md`**.
> Complete all 🔴 Critical and 🟠 Pre-release items (FP-01 → FP-13) before tagging v1.0.

- `[todo]` **FP-01/02/03** — Fix `grand-finale-01` private attr violations.
  Notes:
  - add `ctx`, `render_width`, `render_height`, `has_postfx()` to `VJApi`
  - update `grand_finale.py` to use only `vj_api`; remove all `# noqa: SLF001` private accesses
- `[todo]` **FP-04** — Standardize `_load_*_class()` loaders in `app.py`.
  Notes:
  - move try/except + null fallback inside each loader function (match multi-head pattern)
  - removes reliance on all call sites individually remembering to guard
- `[todo]` **FP-05/06** — Add `[postfx]` and `[grand_finale]` config skeleton sections.
  Notes:
  - add commented-out blocks to `config.toml` so users can see available knobs
  - verify `config.full.example.toml` has both sections complete and accurate
- `[done]` **FP-07** — Add show-duration API to `VJApi`.
  Notes:
  - implemented `set_show_duration()`, `get_elapsed_time()`, `get_time_remaining()`
  - session timer state wired in app run loop
  - consumed by Auto VJ timed-finale path via `VJState.session_remaining_s`
- `[todo]` **FP-08** — Add `VJ_API_VERSION = (1, 0, 0)` constant.
  Notes:
  - exposes `VJApi.VERSION` for drop-in compatibility checks
  - bump on any breaking change to the public surface
- `[todo]` **FP-09/10** — Formalize `BaseEffect` / `AudioData` as stable public contracts.
  Notes:
  - add `__all__` to `unicornviz/effects/base.py`
  - add "Stable Public Contracts" section to `docs/developer-guide.md`
- `[todo]` **FP-11** — Document `HELP_ENTRIES` registration in developer guide.
- `[done]` **FP-12/13** — Auto VJ P5: `Ctrl+J` leader hotkeys + HELP_TEXT additions.
  Notes:
  - leader + child bindings implemented in `hotkeys.py`
  - `Ctrl+J` chain help entries now registered from the Auto VJ drop-in
  - leader arming window currently set to 3.0s

## Feature Ideas to Explore

- `[todo]` Image playlist mode with shader-based transitions and audio-reactive treatment.
- `[todo]` Video-reactive overlays/effect compositing pipeline.
- `[todo]` Preset system for show setups (streaming, performance, ANSI-only, ambient, etc.).
- `[todo]` Scene scheduler with timed sections and transition choreography.
- `[done]` Performance HUD / diagnostics overlay for FPS, frame time, audio source, and active transition, cpu, ram.
- `[todo]` Add `assets/games/` effect mode for interactive/game-like visual scenes.
- `[done]` System Monitor effect (audio-reactive CPU/RAM/network/IO cyber dashboard).
- `[done]` Cyber War effect (digital battle-map style offensive/defensive node animations).
- `[done]` Hacker Terminal effect (animated shell/log streams with glitch transitions).
- `[todo]` Threat Matrix effect (heatmaps, trace routes, anomaly pulses, breach waves).
- `[done]` Alien Invasion effect (UFO fleets, atmospheric beams, planetary scan overlays).
- `[done]` Unicorn Tears effect (iridescent liquid/prism particle trails with dreamy bloom).
- `[done]` Psychedelic effect (neon palette-sine field split out from the old webcam visual background).
- `[done]` Image Showcase effect (audio-reactive slideshow from bundled or overridden image directory).
- `[todo]` BBS! effect suite (dial-up rituals, ANSI login scenes, retro board status walls).
- `[todo]` Black Hole Cathedral effect (gothic mega-structure orbiting an accretion lens with choir-like pulse reactivity).
- `[todo]` Reactor Breach effect (industrial core meltdown with plasma vents, warning strobes, and containment-wave transitions).
- `[todo]` Grand Finale effect suite (staged crescendo, hard drop, cooldown outro).
- `[done]` Optional keystroke telemetry log for training Auto VJ behavior models.
  Notes:
  - implemented append-only log under `logs/` with key + beat-context snapshot
  - controlled by global `[keystrokes] enabled` flag; default OFF
  - future follow-up: redact/omit any sensitive text-input paths if added later
- `[todo]` **Control Room drop-in** (`drop-ins/control-room-01`) — dedicated VJ operator monitor.
  Notes:

  **Concept:** A secondary SDL2 window pinned to a designated "operator" display, showing a
  persistent full HUD and sub-menus so the VJ can control the system without touching the
  audience-facing output. The audience sees effects single/span/mirror as normal; the VJ's
  secondary monitor shows the control room at all times.

  **API capability audit (as of May 2026):**

  What `VJApi` already supports and the control room can use *today* without any core changes:
  - `vj_api.state()` → full `VJState` snapshot (effect name, speed, zoom, reactivity, FPS,
    transitions, recording state, streaming state, postfx slot, auto-advance timer, session
    elapsed/remaining, all flags)
  - `vj_api.goto_effect()`, `goto_random_effect()`, `list_effects()` → effect selection menus
  - `vj_api.set_speed()`, `set_zoom()`, `set_reactivity()`, `set_invert()` → parameter sliders
  - `vj_api.set_advance_interval()`, `set_auto_advance()`, `reset_advance_interval()` → playlist controls
  - `vj_api.trigger_rainbow_nova()`, `trigger_screen_burst()`, `trigger_dancing_unicorn()`,
    `trigger_grand_finale()` → one-shot triggers
  - `vj_api.set_postfx_slot()`, `clear_postfx()`, `hold_postfx_slot()` → post-FX controls
  - `vj_api.flash_message()`, `set_status_pill()` → overlay messaging
  - `vj_api.is_user_busy()`, `mark_user_action()` → grace-period / busy-state awareness
  - `app.start_recording()`, `stop_recording()`, `toggle_recording()` → record controls
  - `app.start_streaming()`, `stop_streaming()`, `set_stream_provider()` → RTMP streaming
  - `app.toggle_pause()`, `toggle_fullscreen()`, `set_display_mode()` → transport

  **What is NOT yet in the public API (gaps that need to be filled before implementation):**

  1. **No per-frame subsystem hook.** The control room window needs to repaint every frame
     (like auto-vj.update but also drive its own SDL_RenderPresent). Currently there is no
     general mechanism — the auto-vj, grand-finale, etc. are hardcoded in the main loop.
     Needed: `vj_api.register_subsystem(name, subsystem)` where the app loop calls
     `subsystem.update(dt, audio)` and `subsystem.present()` each frame. This replaces the
     hardcoded per-subsystem calls with a generalizable registry.

  2. **No secondary window event routing.** The event loop dispatches every `SDL_KEYDOWN` /
     `SDL_MOUSEBUTTONDOWN` to `hotkeys.handle()` regardless of which window it came from.
     If the operator types in the control room window, those keystrokes must NOT trigger
     effects in the main window. Needed: `vj_api.claim_window_events(window_id, handler)`
     — marks a window ID as "owned" by a subsystem; the event loop routes SDL events for
     that window to `handler(event)` instead of `hotkeys.handle()`.

  3. **No live preview frame access.** The control room should show a scaled-down thumbnail
     of the current output. The GL readback path already exists (used by legacy mirror outputs
     in `multi-head-01`), but it's not exposed via `VJApi`. Needed: `vj_api.get_frame_bytes()`
     returning the last readback RGBA bytes, or a callback `vj_api.subscribe_frames(fn)` that
     delivers bytes each frame. The readback already happens when mirror outputs are active;
     sharing the result with the control room is low cost.

  4. **No `VJApi.VERSION` constant.** (Already tracked as FP-08.) Needed before any
     drop-in can safely do compatibility-gated feature detection.

  **Window + rendering approach:**

  Use the proven `multi-head-01` pattern:
  - `SDL_CreateWindow()` on the designated operator display (configurable index)
  - `SDL_CreateRenderer()` (accelerated, fallback to software) — no GL sharing needed
  - Render the UI with SDL2's 2D renderer: `SDL_RenderFillRect`, `SDL_RenderCopy`
    for the thumbnail, and a custom lightweight immediate-mode UI layer
  - OR: embed Dear ImGui via `imgui-bundle` which has a first-class SDL2+SDL_Renderer
    backend — gives proper text rendering, sliders, buttons, sub-menus without building
    a widget system from scratch
  - The control room window does NOT share the main GL context and does NOT affect
    the main render path

  **Core changes required (small, surgical):**
  - `unicornviz/app.py`: Add `_subsystem_registry` list; loop calls `s.update(dt, audio)`
    and (after present) `s.present()` for each registered subsystem.
  - `unicornviz/app.py`: Event loop checks `_claimed_window_ids` dict before dispatching
    hotkeys; routes to claim owner's `on_sdl_event()` if matched.
  - `unicornviz/vj_api.py`: Add `register_subsystem()`, `claim_window_events()`,
    `get_frame_bytes()`.
  - `unicornviz/vj_api.py`: Add `VJApi.VERSION = (1, 0, 0)` (FP-08).

  **Config:** `[control_room]` section under `config.toml`:
  ```toml
  [control_room]
  enabled = true
  display_index = 1       # operator monitor index (0-based)
  width = 1280
  height = 720
  show_preview = true     # live thumbnail of current output
  preview_scale = 0.25    # fraction of control room width
  theme = "dark"          # dark | light | high_contrast
  ```

  **Drop-in location:** `drop-ins/control-room-01/` as a private GitHub submodule.
  Main class: `ControlRoomController` — not a `BaseEffect`; a standalone subsystem
  registered via `vj_api.register_subsystem()` during app init.

  **Implementation phases:**
  - Phase A: Core API additions (register_subsystem, claim_window_events, get_frame_bytes,
    VERSION) — prerequisites, implement in main repo first.
  - Phase B: Minimal control room window: opens on configured display, shows VJState
    readout as text (SDL2_ttf or imgui), closes cleanly on app exit.
  - Phase C: Effect selector grid, speed/zoom/reactivity sliders, postfx toggle row,
    one-shot trigger buttons.
  - Phase D: Live preview thumbnail (scaled from get_frame_bytes()).
  - Phase E: Sub-menu panels: playlist editor, show-duration timer, streaming controls,
    recording controls, MIDI device selector.



## Delivery Strategy

- `[todo]` Start with the lowest-risk operational improvements first: logging, CLI, docs, and installer.
- `[todo]` Tackle platform/display support next: Windows and multi-monitor support affect many subsystems.
- `[todo]` Add media asset pipelines after runtime foundations are stable.
- `[decision]` Finalize plugin/commercial model before implementing paid-effect distribution.

## Config Policy Note

- `[decision]` Define and enforce config source-of-truth policy.
  Notes:
  - maintain a project default config profile (or set of defaults/examples)
  - allow user-local config overrides at runtime
  - do not commit user-customized `config.toml` values to mainline
  - document which config files are defaults/templates vs user-local state
