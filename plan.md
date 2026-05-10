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

- `[todo]` Add first-class Windows support.
  Notes:
  - windowing/input behavior
  - audio capture strategy on Windows
  - packaging/runtime dependency handling
- `[doing]` Add multi-monitor support.
  Notes:
  - first slice implemented: explicit `window.display_index` / `--display-index` selection for startup and fullscreen target display
  - implemented: `display_mode` options (`single`, `span_all`, `mirror_all`) with shared readback and mirror output pipeline
  - remaining work: screenshot/recording implications in mixed-mode topologies and long-run mirror performance validation
- `[todo]` Refactor multi-monitor implementation into a drop-in subsystem module.
  Notes:
  - extract multi-head responsibilities from `app.py` into a dedicated module (`display/multihead.py`)
  - define clear interfaces for: display discovery, primary window policy, mirror output lifecycle, shared frame fan-out, and SDL event routing
  - perform extraction as behavior-preserving first pass, then do targeted optimizations in a second pass
  - risk: moderate-to-large refactor due to current coupling with app init/render/event/cleanup paths
- `[todo]` Verify recent Ubuntu/Debian and Fedora compatibility matrix.
- `[todo]` Build a robust installer for supported Linux distributions.
- `[todo]` Evaluate packaging for Flatpak and Snap.

## Phase 3 — Assets and Media Expansion

- `[todo]` Add `assets/images/` support.
  Notes:
  - playlist-like loading behavior
  - splash-style animation/reactive presentation
- `[todo]` Add `assets/textures/` support.
  Notes:
  - texture pack discovery and metadata
  - effect-level texture slot binding/conventions
  - optional audio-reactive UV/modulation hooks
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
  - document which effects intentionally ignore the global setting- `[decision]` Design frequency-response tuning system with genre profiles.
  Context:
  - Audio reactivity may currently be tuned toward general pop/mainstream frequencies
  - Testing with house/trance/edm reveals potentially suboptimal frequency targeting
  - Different genres (hip-hop, drill, etc.) may need distinct frequency emphasis
  Open questions:
  - profiles: house/trance/edm, hip-hop/drill, rock, classical/ambient, others?
  - where stored: config presets, hardcoded profiles, user-customizable bands?
  - which analysis parameters affected: FFT bands, smoothing, bass/mid/treble splits, reactivity curves?
  - UI: genre selector in hotkeys, or CLI flag, or audio auto-detect?
  - fallback: should there be a "flat" auto-learn profile from current audio?- `[decision]` Design external plugin loading for paid effect packs.
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
- `[todo]` Performance HUD / diagnostics overlay for FPS, frame time, audio source, and active transition, cpu, ram.
- `[todo]` Add `assets/games/` effect mode for interactive/game-like visual scenes.
- `[todo]` System Monitor effect (audio-reactive CPU/RAM/network/IO cyber dashboard).
- `[todo]` Cyber War effect (digital battle-map style offensive/defensive node animations).
- `[todo]` Hacker Terminal effect (animated shell/log streams with glitch transitions).
- `[todo]` Threat Matrix effect (heatmaps, trace routes, anomaly pulses, breach waves).
- `[todo]` Alien Invasion effect (UFO fleets, atmospheric beams, planetary scan overlays).
- `[todo]` Unicorn Tears effect (iridescent liquid/prism particle trails with dreamy bloom).
- `[todo]` BBS! effect suite (dial-up rituals, ANSI login scenes, retro board status walls).

## Delivery Strategy

- `[todo]` Start with the lowest-risk operational improvements first: logging, CLI, docs, and installer.
- `[todo]` Tackle platform/display support next: Windows and multi-monitor support affect many subsystems.
- `[todo]` Add media asset pipelines after runtime foundations are stable.
- `[decision]` Finalize plugin/commercial model before implementing paid-effect distribution.