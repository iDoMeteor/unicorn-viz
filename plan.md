# Unicorn Viz Plan

## Status Legend

- `[todo]` not started
- `[doing]` actively in progress
- `[done]` completed
- `[decision]` needs product/architecture decision

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

- `[doing]` Add first-class Windows support.
  Notes:
  - implemented: Windows-safe SDL driver default path (no forced Wayland)
  - implemented: Windows loopback/stereo-mix candidate audio selection logic
  - implemented: windows-latest CI smoke job for CLI + effect discovery
  - remaining: on-device rendering/audio validation on physical Windows host
- `[doing]` Add multi-monitor support.
  Notes:
  - first slice implemented: explicit `window.display_index` / `--display-index` selection for startup and fullscreen target display
  - implemented: `display_mode` options (`single`, `span_all`, `mirror_all`) with shared readback and mirror output pipeline
  - remaining work: screenshot/recording implications in mixed-mode topologies and long-run mirror performance validation
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

- `[todo]` Add `assets/images/` support.
  Notes:
  - playlist-like loading behavior
  - splash-style animation/reactive presentation
- `[done]` Add `assets/textures/` support.
  Notes:
  - implemented as drop-in `textures-01` with configurable `texture_dirs`
  - includes 20 bundled patterns (including paisley and plaid)
  - implemented audio-reactive texture montage/showcase effect
- `[todo]` Add `assets/videos/` support for MP4 playback.
  Notes:
  - playlist integration
  - fullscreen scaling and transitions
  - audio sync policy
- `[todo]` Add webcam/video capture effect and overlay support.
  Notes:
  - real-time frame capture from /dev/video* (Linux) / camera APIs (Windows/macOS)
  - optional shader processing/distortion/glitch layers
  - picture-in-picture overlay mode alongside effects
  - optional chroma-key / background replacement
- `[todo]` Add `assets/sims/` support for IsaacLab/OpenUSD-style 3D animations.
  Notes:
  - playback/runtime format choice
  - audio sync hooks
  - GPU/runtime cost constraints
- `[todo]` Phase 3 exit gate: complete one full review pass across every existing built-in effect.
  Notes:
  - validate visual quality, audio reactivity, and parameter sanity effect-by-effect
  - capture any per-effect fixes/tuning required after the analyzer modernization
  - close this gate when all Phase 3 asset/media tasks are complete and reviewed together

## Phase 4 — Product and Plugin Architecture

- `[todo]` Review and enhance each existing built-in effect before adding any new effects.
  Notes:
  - performance pass (GPU cost, allocations, frame budget)
  - consistency pass (parameters, naming, audio reactivity behavior)
  - visual polish pass (startup variance, transitions, readability)
  - documentation pass (effect-level options and expected behavior)
- `[todo]` Design a global vignette/post-process system with per-effect overrides.
  Notes:
  - default global vignette strength/shape settings
  - per-effect opt-out/override for effects that already do their own edge darkening
  - decide whether vignette is a post-FBO pass or shader uniform convention
  - document which effects intentionally ignore the global setting
- `[decision]` Design frequency-response tuning system with genre profiles.
  Context:
  - Audio reactivity may currently be tuned toward general pop/mainstream frequencies
  - Testing with house/trance/edm reveals potentially suboptimal frequency targeting
  - Different genres (hip-hop, drill, etc.) may need distinct frequency emphasis
  Open questions:
  - profiles: house/trance/edm, hip-hop/drill, rock, classical/ambient, others?
  - where stored: config presets, hardcoded profiles, user-customizable bands?
  - which analysis parameters affected: FFT bands, smoothing, bass/mid/treble splits, reactivity curves?
  - UI: genre selector in hotkeys, or CLI flag, or audio auto-detect?
  - fallback: should there be a "flat" auto-learn profile from current audio?
- `[decision]` Design external plugin loading for paid effect packs.
  Open questions:
  - local drop-in plugin directory vs hosted/cloud delivery
  - included effects vs third-party/paid effects separation
  - compatibility/version manifest format
  - licensing/entitlement enforcement model
  - security/trust boundary for executable plugin code
- `[todo]` Propose and prototype additional built-in effects and scene ideas.

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
- `[todo]` BBS! effect suite (dial-up rituals, ANSI login scenes, retro board status walls).

## Delivery Strategy

- `[todo]` Start with the lowest-risk operational improvements first: logging, CLI, docs, and installer.
- `[todo]` Tackle platform/display support next: Windows and multi-monitor support affect many subsystems.
- `[todo]` Add media asset pipelines after runtime foundations are stable.
- `[decision]` Finalize plugin/commercial model before implementing paid-effect distribution.