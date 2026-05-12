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
- `[done]` Psychedelic effect (neon palette-sine field split out from the old webcam visual background).
- `[done]` Image Showcase effect (audio-reactive slideshow from bundled or overridden image directory).
- `[todo]` BBS! effect suite (dial-up rituals, ANSI login scenes, retro board status walls).
- `[todo]` Black Hole Cathedral effect (gothic mega-structure orbiting an accretion lens with choir-like pulse reactivity).
- `[todo]` Reactor Breach effect (industrial core meltdown with plasma vents, warning strobes, and containment-wave transitions).

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