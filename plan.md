# Unicorn Viz Plan

## Status Legend

- `[todo]` not started
- `[doing]` actively in progress
- `[done]` completed
- `[decision]` needs product/architecture decision

## Current Focus (May 18, 2026)

- `[done]` 2026-06-05 MIDI controller hardening: APC mini mk2 robust input bind (Item 1).
  Notes:
  - `MidiManager` now supports multi-port opens and APC pair auto-binding (Notes + Control) under `akai_apc_mini_mk2`.
  - Runtime maintenance reconnect is active for MIDI hotplug/disconnect handling.
  - App frame loop now runs MIDI maintenance checks and reports all active MIDI ports in selector feedback.
  - Regression coverage added in `tests/test_midi_port_resolution.py` for APC/generic port-target resolution.
- `[done]` 2026-06-05 MIDI action dispatch expansion (Item 2).
  Notes:
  - `HotkeyHandler` note-on dispatch now uses a named action registry instead of a tiny hardcoded branch set.
  - Added built-in named mappings for transport, selectors/modals, display modes, finale triggers, and randomization toggles.
  - Added contextual navigation actions (`context_up/down/left/right/select/back`) and `postfx_N` dispatch support.
  - Regression coverage extended in `tests/test_hotkeys_behavior.py` for named/contextual/unmapped note actions.
- `[done]` **Pre-release future-proofing pass** — all FP-01 through FP-13 items verified complete
  (loaders guarded, config skeletons present, stable contracts declared, HELP_ENTRIES docs written,
  VJApi versioned, grand-finale private-attr violations resolved).  `plan-future-proofing.md`
  retired; individual FP items tracked in Phase 5 below.
- `[todo]` Effect review pass — systematic quality/perf pass across existing built-in effects.
- `[done]` 2026-06-04 effect review priority round (P0-P3 targeted set) completed and operator signed off.
  Scope closed this round:
  - P0: Sine Scroller 3.x, System Monitor -> Hexy Stars/modal split, Hacker Terminal, Unicorn Tears follow-up
  - P1: Fractal Zoom, Starfield, Vector
  - P2: Psychedelic zoom, Van Gogh long-view variation
  - P3: Metaballs pacing policy, Prism Storm -> Prism Lattice theme/name alignment
- `[done]` RTMP streaming subsystem drop-in.
- `[todo]` Validate ProjectM on primary F44 machine and continue polish there.
- `[todo]` Design vignette/post-process system (see Phase 4).
- `[todo]` Design external plugin loading for paid effect packs.
- `[done]` Hotkey UX remap pass (mnemonic grouping + live-performance ergonomics).
- `[done]` Add optional global keystroke logging (`logs/keystrokes-*.log`) with beat-context snapshot (bpm, beat_phase, energy, vj_mode) per keypress; gated by `[keystrokes] enabled = false`.
- `[todo]` Add config gate for multi-display overlay scoping (base behavior is landed: help/HUD now render on primary display in `span_all` / `mirror_all`).
- `[done]` Design and implement a "grand finale" effect sequence for set-ending moments (audio-linked crescendo + controlled cooldown).
- `[todo]` Design Drop strategy pivot from effect-tag targeting toward post-fx profile targeting (hard-hit look first, effect swap second).
- `[done]` Add effect metadata concept `PING_PONG_FRIENDS` for preferred pairings when randomizing ping-pong slots.
- `[done]` Implement scroll-wheel hue-shift post-fx control (wheel direction shifts hue, idle timeout clears, middle-click clears; middle-click toggles Auto VJ when hue-shift is inactive).
- `[done]` Design `spotify-01` drop-in for track metadata / transport / tempo-aware visual cues.
  Notes:
  - base subsystem landed: optional `spotify-01` runtime controller via `playerctl` + snapshot API for controllers
  - Auto VJ bridge landed for coexistence mode (pause-aware hold + track-change scene cue)
  - HUD strip landed with Spotify status, track, artist, and progress fields
  - Phase 1 supplemental intelligence landed: Auto VJ decision/training logs now carry Spotify track metadata/features when available, and recommender ranking can apply a weak Spotify BPM hint without depending on it
  - open polish: tune HUD truncation/label style, decide final line ordering, evaluate if strip collapses when unavailable
  - open decision: define operator-facing policy for paused transport behavior during live sets (hard hold vs soft hold)
- `[todo]` Design `serato-01` drop-in for DJ deck / transport / cue integration with Control Room and Auto VJ.
- `[todo]` Design `mixxx-01` / `xwax-01` / `giada-01` integration drop-ins for open DJ/live-loop hosts.

## Phase 1 — Runtime, CLI, and Operational Foundations

- `[done]` Audit the codebase for optimization opportunities, architectural inconsistencies, and cleanup candidates.
  Current findings:
  - runtime/logging/config/docs drift was corrected
  - low-risk runtime cleanup and allocation cleanup landed in the app/audio/effect hot paths
  - built-in recording landed with auto-record, configurable output, live-only indicator behavior, and Linux audio mux support
  - stale helper cleanup (for superseded audio-device logic): `_find_monitor_device()` removed from `unicornviz/audio/capture.py` (2026-06-01); superseded by `_candidate_monitor_devices()` which was already the sole caller path.
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
- `[done]` Add `assets/sims/` support for IsaacLab/OpenUSD-style 3D animations.
  Notes:
  - implemented as drop-in `sims-01` (`Sim Showcase`)
  - OpenUSD scene loading and fallback visual path are in place
  - remaining work is quality/performance review under the global pre-release review pass
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
- `[done]` Add global scroll-wheel hue-shift post-fx interaction.
  Notes:
  - wheel up/down shifts global hue in opposite directions
  - effect stays active for X seconds after last scroll event (new scroll resets timer)
  - middle-click clears hue-shift immediately
  - when hue-shift is inactive, middle-click toggles Auto VJ if loaded
  - remaining follow-up: tune defaults and evaluate Auto VJ usage policy for scroll FX
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
- `[done]` Design and prototype "Grand Finale" system effect.
  Notes:
  - implemented in drop-in `grand-finale-01` with trigger/abort integration
  - blends system overlays, post-fx hits, and dedicated sequence phases
  - future work: polish, tuning, and final pre-release review signoff

## Phase 5 — Pre-Release Future-Proofing

> Full audit, findings, and remediation checklist in **`plan-future-proofing.md`**.
> Complete all 🔴 Critical and 🟠 Pre-release items (FP-01 → FP-13) before tagging v1.0.

- `[done]` **FP-01/02/03** — Fix `grand-finale-01` private attr violations.
  Notes:
  - added `ctx`, `render_width`, `render_height`, `has_postfx()` to `VJApi`
  - updated `grand_finale.py` to use only `vj_api`; live drop-in code no longer uses direct private app access
- `[done]` **FP-04** — Standardize `_load_*_class()` loaders in `app.py`.
  Notes:
  - `_load_webcam_system_class`, `_load_rtmp_streamer_class`, and `_load_postfx_controller_class` now guard load errors internally and return safe null fallbacks
  - call sites no longer depend on repeated symbol-load try/except blocks
- `[done]` **FP-05/06** — Add `[postfx]` and `[grand_finale]` config skeleton sections.
  Notes:
  - `config.toml` now includes user-facing skeleton sections
  - `config.full.example.toml` now includes complete default sections
- `[done]` **FP-07** — Add show-duration API to `VJApi`.
  Notes:
  - implemented `set_show_duration()`, `get_elapsed_time()`, `get_time_remaining()`
  - session timer state wired in app run loop
  - consumed by Auto VJ timed-finale path via `VJState.session_remaining_s`
- `[done]` **FP-08** — Add `VJ_API_VERSION = (1, 0, 0)` constant.
  Notes:
  - implemented module constant `VJ_API_VERSION = (1, 0, 0)` in `unicornviz/vj_api.py`
  - exposes `VJApi.VERSION` for drop-in compatibility checks
  - bump on any breaking change to the public surface
- `[done]` **FP-09/10** — Formalize `BaseEffect` / `AudioData` as stable public contracts.
  Notes:
  - `__all__ = ['BaseEffect', 'AudioData']` added to `unicornviz/effects/base.py`
  - "Stable Public Contracts" section added to `docs/developer-guide.md`
- `[done]` **FP-11** — Document `HELP_ENTRIES` registration in developer guide.
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
- `[doing]` **Control Room drop-in** (`drop-ins/control-room-01`) — dedicated VJ operator monitor.
  Notes:
  - MVP implemented: SDL operator window with live preview, transport controls, post-FX bank,
    effect browser, tweakable controls.
  - Runtime validation on Windows is currently a pass on owner machine runs.
  - Core API surface landed and complete: `register_subsystem()`, `unregister_subsystem()`,
    `has_subsystem()`, `get_subsystem()`, `list_subsystems()`, `claim_window_events()`,
    `get_frame_bytes()` all in `vj_api.py`; `VJApi.VERSION` present.  `has_subsystem` /
    `get_subsystem` now delegate through proper `app.py` methods (SLF001 noqa removed).
  - **Starvation fix landed (Attempt K):** root cause was 60 fps GPU readback (`glReadPixels`) on
    every audience frame while preview was active. `app.py` now throttles subsystem frame capture
    to ≤10 fps via a 100 ms gate. `enabled` can be set to `true` for beta testing.
  - Remaining UX: hardware-inspired bank/page layout pass, Decks/Cues/Timing panel,
    richer sub-menu panels, remote-control options.
  - Linux operator-window support remains N/A; planned direction is a separate-process control room on Linux.
  - Routing policy requirement: when control-room gating takes ownership of modals/messages,
    modal surfaces on control room must be fullscreen.
  - Config: `[control_room]` section in `config.toml`.



## Delivery Strategy

- `[done]` Start with the lowest-risk operational improvements first: logging, CLI, docs, and installer.
- `[done]` Tackle platform/display support next: Windows and multi-monitor support affect many subsystems.
- `[done]` Add media asset pipelines after runtime foundations are stable.
- `[decision]` Finalize plugin/commercial model before implementing paid-effect distribution.

## Config Policy Note

- `[decision]` Define and enforce config source-of-truth policy.
  Notes:
  - maintain a project default config profile (or set of defaults/examples)
  - allow user-local config overrides at runtime
  - do not commit user-customized `config.toml` values to mainline
  - document which config files are defaults/templates vs user-local state
