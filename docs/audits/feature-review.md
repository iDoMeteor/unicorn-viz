# Unicorn Viz - Pre-Release Feature Review and Version Tracker

Date baseline: 2026-05-23  
Process: multi-day full-system review  
Primary goal: one canonical checklist for everything (effects, drop-ins, help menu, startup/runtime modes, and system behaviors) so no context switching between documents is required.

---

## How To Use This Tracker

1. Review sections in the execution order below.
2. For each line item, mark PASS or FAIL and add short notes.
3. For each failure, add severity:
   - P0 = release blocker
   - P1 = high-priority pre-release fix
   - P2 = polish/backlog
4. Keep findings in this file only.

Session log template:
- Date:
- Reviewer:
- Scope covered today:
- New P0/P1/P2:
- Notes:

Session log:
- Date: 2026-06-03
- Reviewer: owner + Copilot
- Scope covered today: Help Usage, Basics, Playback, Tweakables, Audio + Visual, Display Modes, Camera Overlay, Drop-in hotkey block status pass
- New P0/P1/P2: P1 candidate display-mode alignment/menu-placement issues on Fedora 44 multi-monitor layout; P2 candidate help scaling at 3840x2160 @ 200%; P2 candidate hotkey/help text cleanup for tweakables/audio/Spotify grouping
- Notes: Operator-confirmed broad hotkey coverage with targeted follow-up items captured in section notes below.

- Date: 2026-06-03
- Reviewer: Copilot
- Scope covered today: Display-mode/menu alignment hardening (primary-centered overlays and splash), mirror logical-canvas sync, topology-change geometry reapply, recording continuity on resize/topology changes
- New P0/P1/P2: P1 display-mode/menu-placement candidate resolved in code path; no new P0 found in automated validation
- Notes: Local regression suite remains green after changes (26 passed); operator runtime validation still required for final signoff.

- Date: 2026-06-03
- Reviewer: Copilot
- Scope covered today: F44 truth-sync cleanup + Auto VJ HUD off-state fix + startup/drop-in independence evidence pass
- New P0/P1/P2: No new P0 from startup/drop-in loader paths; P1 review work remains runtime-validation heavy
- Notes: Auto VJ HUD mode/mood/action labels now report `off`/`--` when toggled off; static code inspection confirms guarded optional loader paths for auto-vj, multi-head, webcam, streaming, postfx, control-room, and grand-finale.

- Date: 2026-06-03
- Reviewer: Copilot
- Scope covered today: bounded baseline startup smoke run (`timeout 20s ./run.sh --start-effect "Audio Spectrum" --log-level INFO`)
- New P0/P1/P2: No startup crash-path finding in this pass
- Notes: Startup reached splash/effect loop/audio capture and initialized optional subsystems (auto-vj, webcam, grand-finale, streaming loader path) without crash.

- Date: 2026-06-03
- Reviewer: Copilot
- Scope covered today: bounded display-startup smokes via CLI overrides (`--display-mode single|span_all|mirror_all`)
- New P0/P1/P2: No startup crash-path finding across startup display modes in this pass
- Notes: All three mode runs reached SDL+OpenGL init and audio-ready markers before timeout cutoff.

- Date: 2026-06-03
- Reviewer: Copilot
- Scope covered today: bounded startup matrix checks with temporary config overrides (Auto VJ disabled, streaming enabled, control-room enabled)
- New P0/P1/P2: No startup crash-path finding in these matrix rows
- Notes: Temporary config files under `/tmp` were used so live `config.toml` values remained untouched.

- Date: 2026-06-04
- Reviewer: owner
- Scope covered today: one-shot visual review batch for built-in + drop-in effects (fractal_zoom through wavey gravy set, plus hacker_terminal/prism_storm/tron_grid/unicorn_tears)
- New P0/P1/P2: P0 on Hacker Terminal, Sine Scroller, System Monitor positioning/role, Unicorn Tears avatar placement; P1 on Fractal Zoom startup variance and framing drift, Starfield depth/reactivity evolution, Vector motion accents; P2 on Psychedelic zoom and Van Gogh long-view variation; P3 on Metaballs default split pacing and Prism Storm naming/theme alignment
- Notes: Assets still pending for images/sims/ansi/video review set.

- Date: 2026-06-04
- Reviewer: owner + Copilot
- Scope covered today: implementation closure pass for the 2026-06-04 effect-priority batch
- New P0/P1/P2: no new findings; implementation updates landed for all listed P0/P1/P2/P3 items from this batch
- Notes: P0/P1/P2/P3 implementation scope from this operator batch is marked complete in code; remaining work is operator visual signoff and any follow-up tuning deltas.

---

## Canonical Runtime Review Order

This order follows the in-app help flow first, then all non-help surfaces.

1. Help Usage
2. Basics
3. Playback
4. Tweakables
5. Audio + Visual
6. Display Modes
7. Camera Overlay
8. Drop-in Help Sections (runtime alphabetical)
9. Startup and Boot Modes (non-help)
10. Drop-in Enable/Disable Matrix (non-help)
11. Built-in Effects One-Shot Review
12. Drop-in Visual Effects One-Shot Review
13. Subsystem Drop-ins (control/streaming/director/finale)
14. Config Edge Cases and Failure Behavior
15. Performance and Stability Sweep
16. Summary Counts

---

## 1) Help Usage

- [ ] Shift+- collapses all sections
- [ ] Shift+= expands all sections
- [ ] Arrow keys move section focus
- [ ] Enter toggles focused section
- [ ] 0-9 toggles section 1-10
- [ ] H toggles notifications/help behavior as documented
- [ ] 60s auto-hide behavior feels correct
- [ ] No overlap/clipping/format issues

Notes:

- 2026-06-03: Overall status `Done`.
- 2026-06-03: Layout looked good at 1920x1080, but help text/UI felt too small at 3840x2160 with 200% scaling; dynamic scaling adjustment needed.

---

## 2) Basics

- [ ] f fullscreen
- [ ] Number jumps 1-9
- [ ] Shift+Number jumps 11-20
- [ ] Ctrl+Number jumps 21-30
- [ ] Alt+Number jumps 31-40
- [ ] n / Right next effect
- [ ] p / Left previous effect
- [ ] ESC quit
- [ ] u replay splash
- [ ] s screenshot
- [ ] TAB HUD toggle
- [ ] v recording toggle

Notes:

- 2026-06-03: Overall status `Done`.
- 2026-06-03: Operator reported all core basics worked; longer recording runs still need additional validation.

---

## 3) Playback

- [ ] ; / ' advance interval -/+ 10s
- [ ] t auto-advance toggle
- [ ] Space pause/resume
- [ ] r random effects mode
- [ ] \\ reset advance interval

Notes:

- 2026-06-03: Overall status `Done`.

---

## 4) Tweakables

- [ ] [ / ] reactivity down/up
- [ ] { / } reactivity min/max
- [ ] F7 reactivity random toggle
- [ ] g reactivity reset
- [ ] , / . resolution scale down/up
- [ ] Shift+, / Shift+. resolution scale min/max
- [ ] Ctrl+, / Ctrl+. resolution scale reset
- [ ] k / K alternate resolution scale up/down
- [ ] + / - speed up/down
- [ ] = / - speed max/min and random behavior matches current implementation
- [ ] Ctrl+G speed reset
- [ ] z / Z zoom in/out
- [ ] Alt+Z zoom random toggle
- [ ] Ctrl+Z zoom reset

Notes:

- 2026-06-03: Overall status `Done`.
- 2026-06-03: `k`/`K` alternative resolution-scale bindings removed from runtime and help text.
- 2026-06-03: Speed min/max help label now shows `Ctrl+= / Ctrl+-`.
- 2026-06-03: Speed random toggle help label now shows `Alt+= / Alt+-`.

---

## 5) Audio + Visual

- [ ] e jump to EQ/Audio Spectrum
- [ ] A / Shift+A open audio source selector menu
- [ ] Ctrl+Shift+A / Ctrl+A open audio source selector menu (alternate)
- [ ] ANSI A-family shortcuts intentionally disabled pending remap plan
- [ ] Alt+A / Alt+Shift+A BPM profile next/prev
- [ ] Ctrl+Alt+1..9 / 0 Post FX quick-hit trigger
- [ ] Mouse wheel hue-shift frame works and expires on idle timer
- [ ] Ctrl+Mouse wheel scene rotation frame works and expires on idle timer
- [ ] Middle click reset and Auto VJ toggle behavior matches implementation
- [ ] Ctrl+Alt+F trigger grand finale
- [ ] Ctrl+Alt+Shift+F abort grand finale
- [ ] m MIDI device selector
- [ ] i invert colors

Notes:

- 2026-06-03: Overall status `Done`.
- 2026-06-03: `Ctrl+Shift+A` alternate audio-selector binding removed; `Ctrl+A` remains.
- 2026-06-03: Spotify help items belong in the Spotify section and the current Spotify items are not working.

---

## 6) Display Modes

- [ ] x single display
- [ ] X span all
- [ ] Ctrl+X mirror all
- [ ] Alt+X config default mode
- [ ] Switching modes repeatedly does not leak/crash

Notes:

- 2026-06-03: Overall status `Engineering pass complete`.
- 2026-06-03: Primary-centered placement landed for overlays/menus in `span_all` and `mirror_all`.
- 2026-06-03: Splash now targets primary viewport in multi-display modes.
- 2026-06-03: Mirror logical canvas sizing now follows primary active layout; topology-change rebuild reapplies geometry/state.
- 2026-06-03: Active recording now rotates across resize/topology dimension changes to preserve continuity.
- 2026-06-03: Final status remains `Pending owner runtime validation` on Fedora 44 monitor topology.

---

## 7) Camera Overlay

- [ ] KP 1-9 PiP position
- [ ] KP 0 / . PiP fullscreen/hide
- [ ] KP / * treatment prev/next
- [ ] KP - / + PiP size
- [ ] KP Enter treatment auto-cycle
- [ ] Webcam unavailable path degrades gracefully

Notes:

- 2026-06-03: Overall status `Done`.

---

## 8) Drop-in Help Sections (Runtime Alphabetical)

2026-06-03 block status: `In progress`.

- Spotify auth still needs work.
- Control Room startup path is now loading on Fedora 44; interactive window-focus/toggle validation is still pending.
- Multi-head help now shows `Shift+X` for span-all.
- Sims / Images / Videos are not fully testable on this machine because assets are missing.
- Streaming hotkey surface is present (`F8`, `Ctrl+F9/F10/F11`); live endpoint verification still pending.
- Unicorn Tears hotkeys were reported good.
- Auto VJ HUD disabled-state labels now explicitly show OFF semantics (mode/mood off, action timer hidden) after runtime toggle.
- ProjectM preset hotkey surface is present (`Ctrl+N`, `Ctrl+P`, `Ctrl+R`) and fallback label path is implemented (`projectM unavailable`).

### Auto VJ
- [ ] Ctrl+Alt+J toggle Auto VJ
- [ ] Ctrl+J then M cycle profile chill/normie/raver/user behavior
- [ ] Status text in HUD header is readable and accurate
- [ ] USER busy-hold only triggers on visual/VJ-affecting input (effect/postfx/tweakables), not modifier-only keys or system combos (Alt+Tab/Ctrl/Shift/record/help)

### Auto VJ Ping-Pong
- [ ] Ctrl+J then A pin slot A
- [ ] Ctrl+J then B pin slot B
- [ ] Ctrl+J then P toggle ping-pong mode
- [ ] Ctrl+J then R auto-pick pair
- [ ] Ctrl+J then C clear slots
- [ ] Leader key timeout/UX feels reliable in live use

### Control Room
- [ ] Ctrl+Alt+O toggles operator window
- [ ] Esc closes control room when focused
- [ ] Main render loop remains smooth while control room open

### Grand Finale
- [ ] Ctrl+Alt+F triggers sequence
- [ ] Ctrl+Alt+Shift+F abort restores state cleanly
- [ ] No stuck state after abort or completion

### Post FX
- [ ] Ctrl+Alt+1 Chromatic Aberration | Rating Before: ___/5 | Rating After: ___/5
- [ ] Ctrl+Alt+2 Film Grain + Dither | Rating Before: ___/5 | Rating After: ___/5
- [ ] Ctrl+Alt+3 Glitch Slices | Rating Before: ___/5 | Rating After: ___/5
- [ ] Ctrl+Alt+4 Heat Haze Refraction | Rating Before: ___/5 | Rating After: ___/5
- [ ] Ctrl+Alt+5 Lens Distortion + Vignette | Rating Before: ___/5 | Rating After: ___/5
- [ ] Ctrl+Alt+6 Multi-pass Bloom | Rating Before: ___/5 | Rating After: ___/5
- [ ] Ctrl+Alt+7 Radial Zoom Blur | Rating Before: ___/5 | Rating After: ___/5
- [ ] Ctrl+Alt+8 Temporal Feedback Trail | Rating Before: ___/5 | Rating After: ___/5
- [ ] Ctrl+Alt+9 Time Scramble Warp | Rating Before: ___/5 | Rating After: ___/5
- [ ] Ctrl+Alt+0 Smoke and Bubbles | Rating Before: ___/5 | Rating After: ___/5

### ProjectM Presets
- [ ] Ctrl+N next preset
- [ ] Ctrl+P previous preset
- [ ] Ctrl+R random preset
- [ ] Fallback mode behaves correctly when projectM unavailable

### Sim Showcase
- [ ] Ctrl+N next scene
- [ ] Ctrl+P previous scene
- [ ] Ctrl+R random scene
- [ ] USD missing fallback visual path is acceptable

### Streaming
- [ ] F8 toggle RTMP streaming
- [ ] Ctrl+F9 provider Rumble
- [ ] Ctrl+F10 provider YouTube
- [ ] Ctrl+F11 provider Custom
- [ ] Stream key redaction in logs/HUD works

### Unicorn Tears
- [ ] Ctrl+U dancing unicorn overlay
- [ ] Alt+U rainbow nova celebration
- [ ] Ctrl+Alt+U screen burst
- [ ] U jump to Unicorn Tears effect

Notes:

- 2026-06-03: Code-level verification confirms key-handler mappings exist for Auto VJ, Control Room, Streaming, and Unicorn Tears controllers.
- 2026-06-03: ProjectM effect exposes next/prev/random preset methods and a graceful fallback mode when libprojectM is unavailable.
- 2026-06-03: Splash incident review found one non-startup replay in `unicornviz_20260603_114423.log`, correlated with a single `U` keypress in `keystrokes-20260603-114434.log`; no repeating loop evidence in recent sessions.

---

## 9) Startup and Boot Modes (Non-Help)

### Baseline Boot
- [x] Clean startup with default config
- [x] Startup with Auto VJ enabled
- [x] Startup with Auto VJ disabled
- [x] Startup with streaming enabled/disabled
- [x] Startup with control room enabled/disabled

### Display Startup
- [x] Startup in single mode
- [x] Startup in span_all mode
- [x] Startup in mirror_all mode
- [x] Excluded display indices config behaves as expected

### Optional Submodule Independence
- [x] Missing auto-vj-01 degrades gracefully
- [x] Missing multi-head-01 degrades gracefully
- [x] Missing webcam-01 degrades gracefully
- [x] Missing streaming-01 degrades gracefully
- [x] Missing postfx-01 degrades gracefully
- [x] Missing control-room-01 degrades gracefully
- [x] Missing grand-finale-01 degrades gracefully

Notes:

- 2026-06-03: Bounded Fedora startup smoke (`timeout 20s`) succeeded using default config with explicit start-effect override for deterministic log capture.
- 2026-06-03: Remaining startup matrix rows still require explicit runtime toggles/mode permutations.
- 2026-06-03: Additional bounded startup checks succeeded for `single`, `span_all`, and `mirror_all` via CLI display-mode override; each run reached SDL/OpenGL/audio-ready state before timeout.
- 2026-06-03: Temporary-config startup checks confirmed Auto VJ disabled startup (`Phase 4 loaded (disabled)`), streamer enabled startup (`enabled=True auto_start=False`), and control-room enabled startup (`scheduled` then `loaded from drop-in`).
- 2026-06-03: Multi-index exclusion validated with temporary configs: `exclude_display_indices = [0, 1]` produced `Excluding displays from mirror_all: 0, 1` and mirror rects reduced to only the remaining display; span_all logged the same exclusion policy.
- 2026-06-03: Missing `auto-vj-01` runtime check (temporary directory hide, debug startup) logged `AutoVJController not available: Drop-in file not found .../drop-ins/auto-vj-01/auto_vj.py` while startup continued to `GrandFinaleController loaded` and `RTMP streamer loaded`.
- 2026-06-03: Missing `streaming-01` runtime check logged `RTMP streamer unavailable: Drop-in file not found .../drop-ins/streaming-01/rtmp_streamer.py` with no startup crash.
- 2026-06-03: Missing `control-room-01` runtime check (with temporary config forcing `[control_room].enabled = true`) logged `ControlRoomController not available: Drop-in file not found .../drop-ins/control-room-01/control_room.py` after scheduled startup frames, with no startup crash.
- 2026-06-03: Missing `multi-head-01` runtime check logged `MultiHeadController unavailable ... falling back to single-display mode`; startup still reached audio-ready state.
- 2026-06-03: Missing `webcam-01` runtime check logged `WebcamSystem not available: Drop-in file not found .../drop-ins/webcam-01/webcam_overlay.py` with startup continuing.
- 2026-06-03: Missing `postfx-01` runtime check logged `PostFxController not available: Drop-in file not found .../drop-ins/postfx-01/postfx_controller.py` with startup continuing.
- 2026-06-03: Missing `grand-finale-01` runtime check logged `GrandFinaleController not available: Drop-in file not found .../drop-ins/grand-finale-01/grand_finale.py` after audio-ready startup.

---

## 10) Drop-in Enable/Disable Matrix (Non-Help)

Track both enabled and disabled behavior for each drop-in.

| Drop-in | Enabled PASS/FAIL | Disabled PASS/FAIL | Notes |
|---|---|---|---|
| alien-invasion-01 | [x] | [x] | Baseline debug startup registered `Alien Invasion`; hidden-dropin run removed registration (`count=0`) while still reaching audio-ready startup. |
| auto-vj-01 | [x] | [x] | Temp-config startups: enabled run logged `AutoVJController loaded from drop-in`; disabled run logged `AutoVJController Phase 4 loaded (disabled)`. |
| control-room-01 | [x] | [x] | Temp-config startups: enabled run logged `ControlRoomController scheduled ...` then `loaded from drop-in`; disabled run skipped controller without startup crash. Multi-head runtime matrix now tracks `single`, `span_included`, `span_all`, `mirror_included`, and `mirror_all`. |
| cyber-war-01 | [x] | [x] | Baseline debug startup registered `Cyber War`; hidden-dropin run removed registration (`count=0`) while still reaching audio-ready startup. |
| disco-ball-01 | [x] | [x] | Baseline debug startup registered `Disco Ball`; hidden-dropin run removed registration (`count=0`) while still reaching audio-ready startup. |
| grand-finale-01 | [x] | [x] | Enabled runs logged `GrandFinaleController loaded from drop-in`; missing-dropin run logged `GrandFinaleController not available .../grand-finale-01/grand_finale.py` with startup continuing. |
| hacker-terminal-01 | [x] | [x] | Baseline debug startup registered `Hacker Terminal`; hidden-dropin run removed registration (`count=0`) while still reaching audio-ready startup. |
| images-01 | [x] | [x] | Baseline debug startup registered `Image Showcase`; hidden-dropin run removed registration (`count=0`) while still reaching audio-ready startup. |
| multi-head-01 | [x] | [x] | Enabled runs show multi-head display topology logs (`Display 0: origin=...`) and mirror/span startup; missing-dropin run logged fallback to single-display mode. |
| postfx-01 | [x] | [x] | Enabled runs logged `PostFxController loaded from drop-in`; missing-dropin run logged `PostFxController not available .../postfx-01/postfx_controller.py` with startup continuing. |
| projectm-01 | [x] | [x] | Baseline debug startup registered `ProjectM Presets`; hidden-dropin run removed registration (`count=0`) while still reaching audio-ready startup. |
| sims-01 | [x] | [x] | Baseline debug startup registered `Sim Showcase`; hidden-dropin run removed registration (`count=0`) while still reaching audio-ready startup. |
| streaming-01 | [x] | [x] | Temp-config startups: enabled run logged `RTMP streamer loaded (enabled=True auto_start=False)`; default disabled run logged `enabled=False auto_start=False`. |
| textures-01 | [x] | [x] | Baseline debug startup registered both `Prism Storm` and `Texture Showcase`; hidden-dropin run removed both registrations (`count=0`) while still reaching audio-ready startup. |
| tron-grid-01 | [x] | [x] | Baseline debug startup registered `Tron Grid`; hidden-dropin run removed registration (`count=0`) while still reaching audio-ready startup. |
| unicorn-tears-01 | [x] | [x] | Enabled runs logged `UnicornTearsController loaded from drop-in`; missing-dropin run logged unavailable warnings for DancingUnicornOverlay/RainbowNova/UnicornTearsController and still reached audio-ready startup. |
| videos-01 | [x] | [x] | Baseline debug startup registered `Video Showcase`; hidden-dropin run removed registration (`count=0`) while still reaching audio-ready startup. |
| webcam-01 | [x] | [x] | Enabled runs logged `WebcamSystem loaded from drop-in`; missing-dropin run logged `WebcamSystem not available .../webcam-01/webcam_overlay.py` with startup continuing. |

---

## 11) Built-in Effects One-Shot Review

Use this for each built-in effect in one pass so all criteria are captured together.

Per-effect one-shot checklist:
- [ ] Rating Before (pre-tuning baseline): ___/5
- [ ] Rating After (post-tuning result): ___/5
- [ ] Visual quality: ___/5
- [ ] Audio response: ___/5
- [ ] Performance single display: ___/5
- [ ] Performance span mode: ___/5
- [ ] Performance mirror mode: ___/5
- [ ] Ping-pong friends mapping: PASS/FAIL (friend list exists, pair quality verified)
- [ ] Startup variance: PASS/FAIL (EXEMPT where noted)
- [ ] Parameter sanity (speed/zoom/reactivity/intensity): PASS/FAIL
- [ ] Hotkey behavior sanity while active: PASS/FAIL
- [ ] Notes
- [ ] Fixes needed (P0/P1/P2)

### Built-in roster

- [x] 3D Cube (cube_3d) | Rating Before: 5/5 | Rating After: N/A (operator: "no need")
   Operator review (2026-06-03, shortcut 1): Visual quality 5/5; Audio response 9/5 (operator-entered); Performance single/span/mirror 5/5; Ping-pong friends PASS; Startup variance PASS; Parameter sanity FAIL (reactivity and zoom appeared non-responsive); Hotkey sanity PASS; Fixes needed: P2 only. Notes: baseline felt 4/5 but "super retro" pushed final to 5/5.
- [ ] Wavey Gravy (alien_biome) | Rating Before: ___/5 | Rating After: ___/5
- [ ] ANSI Viewer (ansi_viewer) | Rating Before: ___/5 | Rating After: ___/5
- [x] Audio Spectrum (audio_spectrum) - startup variance EXEMPT | Rating Before: 8/5 | Rating After: N/A
   Operator review (2026-06-03): Visual quality 8/5; Audio response PASS; Performance single PASS; Performance span PASS; Performance mirror N/A (not scored); Ping-pong friends mapping UNSURE; Startup variance N/A (EXEMPT); Parameter sanity note: max reactivity should be 1.2; Hotkey sanity PASS. Notes: bars/squares should have more life. Fixes needed: all P0.
- [x] Copper Bars (copper_bars) | Rating Before: 8/5 | Rating After: N/A
   Operator review (2026-06-03, shortcut 3): Visual quality 8/5; Audio response PASS; Performance single/span/mirror PASS; Ping-pong friends mapping PASS; Startup variance PASS; Parameter sanity PASS; Hotkey sanity PASS; Fixes needed: none noted. Notes: "pretty cool... nothing super special but still very fun." Operator supplied score points `1) 8`, `2) (blank)`, `3) 8`; all other checklist items passed.
- [ ] Cosmos (cosmos) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Crystal Pyramids (crystal_pyramids) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Dali (dali) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Escher (escher) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Curtains (fire) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Fire (fire_lifelike) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Fireworks (fireworks) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Fractal Zoom (fractal_zoom) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Kaleidoscope (kaleidoscope) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Metaballs (metaballs) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Particle Storm (particle_storm) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Plasma (plasma) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Psychedelic (psychedelic) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Raymarcher (raymarcher) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Sine Scroller 2.0 (sine_scroller) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Starfield (starfield) | Rating Before: ___/5 | Rating After: ___/5
- [ ] System Monitor (system_monitor) - startup variance EXEMPT | Rating Before: ___/5 | Rating After: ___/5
- [ ] Tunnel (tunnel) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Van Gogh (van_gogh) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Vector (vector) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Water (water) | Rating Before: ___/5 | Rating After: ___/5

---

## 12) Drop-in Visual Effects One-Shot Review

Use the same per-effect one-shot checklist as built-ins.

### Drop-in visual roster

- [x] Alien Invasion (alien-invasion-01) | Rating Before: 7/5 | Rating After: N/A
   Operator review (2026-06-03, shortcut 2): Visual quality 7/5; Audio response 7/5; Performance single/span/mirror PASS; Ping-pong friends PASS; Startup variance FAIL; Parameter sanity PASS; Hotkey sanity PASS; Fixes needed: P1 across all requested changes. Notes: left-side highlight source (UFO) should travel around scene rather than hugging edges/hanging in one area; spinning element should be more reactive; increase color variance; add sparkles; improve response to speed/reactivity controls; default zoom should be further out; vertical bars should dance more and vary count. Operator noted reactivity is great in one highlighted area but overall control responsiveness still feels weak.
- [ ] Cyber War (cyber-war-01) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Disco Ball (disco-ball-01) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Hacker Terminal (hacker-terminal-01) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Image Showcase (images-01) | Rating Before: ___/5 | Rating After: ___/5
- [ ] ProjectM Presets (projectm-01) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Sim Showcase (sims-01) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Texture Showcase (textures-01) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Prism Storm (textures-01) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Tron Grid (tron-grid-01) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Unicorn Tears (unicorn-tears-01) | Rating Before: ___/5 | Rating After: ___/5
- [ ] Video Showcase (videos-01) | Rating Before: ___/5 | Rating After: ___/5

---

## 12b) Transition Styles One-Shot Review

Use this section to score transition tuning impact directly.

- [ ] crossfade | Rating Before: ___/5 | Rating After: ___/5
- [ ] smoothfade | Rating Before: ___/5 | Rating After: ___/5
- [ ] scanwipe_x | Rating Before: ___/5 | Rating After: ___/5
- [ ] scanwipe_y | Rating Before: ___/5 | Rating After: ___/5
- [ ] dissolve | Rating Before: ___/5 | Rating After: ___/5
- [ ] zoomblend | Rating Before: ___/5 | Rating After: ___/5
- [ ] radialwipe | Rating Before: ___/5 | Rating After: ___/5
- [ ] lumawipe | Rating Before: ___/5 | Rating After: ___/5
- [ ] stripewipe | Rating Before: ___/5 | Rating After: ___/5
- [ ] anglesweep | Rating Before: ___/5 | Rating After: ___/5
- [ ] glitchsoft | Rating Before: ___/5 | Rating After: ___/5
- [ ] prismsplit | Rating Before: ___/5 | Rating After: ___/5

---

## 13) Subsystem Drop-ins (Control/Runtime)

### Multi-Head Controller
- [ ] Detects displays correctly
- [ ] Span/mirror policies correct
- [ ] Mirror outputs stable over long session
- [ ] No readback or sync regressions

### Webcam Overlay
- [ ] Overlay always-on behavior correct
- [ ] Treatment switching stable
- [ ] Camera reconnect/failure path safe

### Streaming
- [ ] ffmpeg launch/stop robust
- [ ] Audio capture path stable
- [ ] Provider switching while active behaves correctly

### Auto VJ Director
- [ ] Profile presets feel distinct
- [ ] Manual override keys supersede profile defaults correctly
- [ ] Speed/zoom/reactivity drift all active when supported
- [ ] Timed finale behavior correct with and without show duration
- [ ] Post FX usage policy respects config and runtime toggles

### Grand Finale Controller
- [ ] Sequence phase progression clean
- [ ] Abort path restores pre-finale state
- [ ] No persistent blackout or postfx stuck state

### Control Room Window
- [ ] Opens on configured display/index
- [ ] Input events isolated to operator window
- [ ] Preview and controls update without starving main render

---

## 14) Config Edge Cases and Failure Behavior

- [ ] Missing config file fallback startup
- [ ] Malformed TOML startup handling
- [ ] Missing effects directory handling
- [ ] Missing asset directories handling
- [ ] Invalid audio input settings fallback
- [ ] Invalid MIDI device handling
- [ ] Invalid streaming provider/endpoint handling
- [ ] Invalid display mode/index handling

---

## 15) Performance and Stability Sweep

- [ ] No crash on any single keypress
- [ ] No crash on rapid key sequences
- [ ] No crash during Alt+Tab/focus changes
- [ ] Stable at 60fps budget on normal scenes
- [ ] No severe hitch on effect transitions
- [ ] No memory growth regression in long run
- [ ] Recording and streaming do not cause unacceptable frame drops

Long-run checks:
- [ ] 30-minute soak PASS/FAIL
- [ ] 60-minute soak PASS/FAIL

---

## 16) Summary Counts

- Built-in effects tested: ___ / 26
- Drop-in visual effects tested: ___ / 12
- Drop-ins enable/disable matrix completed: 18 / 18
- Help sections fully validated: ___ / 8+dynamic
- Post FX slots validated: ___ / 10
- Startup mode scenarios validated: ___ / 12
- P0 open: ___
- P1 open: ___
- P2 open: ___

Release decision:
- [ ] GO
- [ ] NO-GO

---

## Consolidated Notes (Merged from notes.md)

### Confirmed implementation context to verify during review

- Drop-in zoom support was added across drop-in visual effects; verify zoom range feel and behavior consistency during effect passes.
- Fireworks was significantly retuned (brightness and flare controls); run explicit regression check for runaway white-hot flashes.
- Auto VJ profile system is active (chill/normie/raver plus user-override behavior); verify parity and audible/visual distinctions.
- Auto VJ session-time and timed finale behaviors are implemented; verify enabled/disabled-duration behavior explicitly.
- Leader key timeout for Ctrl+J chains was extended; validate reliability under live pacing.

### Planning carry-overs to validate while reviewing

- Evaluate mapping between effect tags and postfx quick-hit triggers for stronger impact pairings.
- Validate ping-pong friend pairing behavior and friend-map quality.
- Validate scroll-wheel hue-shift/postfx interaction behavior and timer reset semantics.
- Validate middle-click dual behavior (reset vs Auto VJ toggle) for predictability.

### 2026-06-04 Operator Batch (Effect One-Shot Data)

Format:
- Rating = overall score (10-point scale)
- Visual / Audio = 10-point scale
- Single/Span/Mirror/Friends/Startup/Hotkey = pass/fail
- Fix priority = operator-specified urgency

#### Built-in effects

- Fractal Zoom (`fractal_zoom`): Rating 8.5 | Visual 9 | Audio 8 | Single pass | Span pass | Mirror pass | Friends pass | Startup fail | Hotkey pass | Priority P1
   - Notes: Very beautiful fractal now but still starts too similarly and can get stuck in background/foreground framing, losing fractals out of frame over time.

- Kaleidoscope (`kaleidoscope`): Rating 10 | Visual 10 | Audio 10 | Single pass | Span pass | Mirror pass | Friends pass | Startup pass | Hotkey pass | Priority none
   - Notes: Fully dialed-in benchmark quality.

- Metaballs (`metaballs`): Rating 10 | Visual 10 | Audio 10 | Single pass | Span pass | Mirror pass | Friends pass | Startup pass | Hotkey pass | Priority P3
   - Notes: Very intense current version; consider slightly reducing default ball-splitting pace.

- Particle Storm (`particle_storm`): Rating 7.5 | Visual 7.5 | Audio 7.5 | Single pass | Span pass | Mirror pass | Friends pass | Startup pass | Hotkey pass | Priority none
   - Notes: Decent baseline; stronger with VJ support than standalone.

- Plasma (`plasma`): Rating 9 | Visual 9 | Audio 8.5 | Single pass | Span pass | Mirror pass | Friends pass | Startup pass | Hotkey pass | Priority none
   - Notes: Newer version is quite strong.

- Psychedelic (`psychedelic`): Rating 8 | Visual 8 | Audio 8 | Single pass | Span pass | Mirror pass | Friends pass | Startup pass | Hotkey pass | Priority P2
   - Notes: Solid newer pass; zoom control requested.

- Sine Scroller 2.0 (`sine_scroller`): Rating 6 | Visual 5 | Audio 9 | Single pass | Span pass | Mirror pass | Friends pass | Startup fail | Hotkey pass | Priority P0
   - Notes: Concept still good, but operator requests a full 3.0 rewrite toward modern neon/lazer visual identity.

- Starfield (`starfield`): Rating 7 | Visual 7 | Audio 7 | Single pass | Span pass | Mirror pass | Friends pass | Startup pass | Hotkey pass | Priority P1
   - Notes: Pleasant interlude but needs more life over time and stronger music-ray interaction.

- System Monitor (`system_monitor`): Rating 8 | Visual 8 | Audio 8 | Single pass | Span pass | Mirror pass | Friends pass | Startup pass | Hotkey pass | Priority P0
   - Notes: Strong utility value; operator requests clearer labels and a special-tool hotkey path instead of normal rotation.

- Tunnel (`tunnel`): Rating 9 | Visual 9 | Audio 8.5 | Single pass | Span pass | Mirror pass | Friends pass | Startup pass | Hotkey pass | Priority none
   - Notes: Strong favorite and stable in all display modes.

- Van Gogh (`van_gogh`): Rating 9.5 | Visual 9.5 | Audio 9.5 | Single pass | Span pass | Mirror pass | Friends pass | Startup pass | Hotkey pass | Priority P2
   - Notes: Excellent current result; request for longer-view color/variation evolution.

- Vector (`vector`): Rating 8 | Visual 8 | Audio 8 | Single pass | Span pass | Mirror pass | Friends pass | Startup pass | Hotkey pass | Priority P1
   - Notes: Requested enhancement: pulsing beads/racers traveling along vector paths.

- Wavey Gravy (`alien_biome`): Rating 8 | Visual 8 | Audio 8 | Single pass | Span pass | Mirror pass | Friends pass | Startup pass | Hotkey pass | Priority none
   - Notes: Remove lingering references to former name.

#### Drop-in visual effects

- Hacker Terminal (`hacker-terminal-01`): Rating 7 | Visual 7 | Audio 5 | Single pass | Span pass | Mirror pass | Friends pass | Startup fail | Hotkey pass | Priority P0
   - Notes: Strong potential with VJ, weak standalone response; explicit speed control requested; stronger audio-reactive behavior needed.

- Prism Storm (`textures-01`): Rating 8 | Visual 8 | Audio 8 | Single pass | Span pass | Mirror pass | Friends pass | Startup pass | Hotkey pass | Priority P3
   - Notes: Visual quality is strong but naming/theme alignment requested (currently reads more tunnel-like than prism-like).

- Tron Grid (`tron-grid-01`): Rating 9.5 | Visual 9.5 | Audio 9.5 | Single pass | Span pass | Mirror pass | Friends pass | Startup pass | Hotkey pass | Priority none
   - Notes: Operator favorite; considered highly polished.

- Unicorn Tears (`unicorn-tears-01`): Rating 10 | Visual 10 | Audio 10 | Single pass | Span pass | Mirror pass | Friends pass | Startup pass | Hotkey pass | Priority P0
   - Notes: Flagship quality; fix requested for dancing-unicorn avatar anchoring/scale origin to avoid top-edge blank-space drift inside heart composites.

### 2026-06-04 Implementation Status Update (Effect-Priority Batch)

- P0 implemented:
   - Sine Scroller 3.x rewrite/tuning and compile-stability fixes landed.
   - System Monitor split/reposition completed as Hexy Stars visual + dedicated monitor modal UX.
   - Hacker Terminal tuning/controls pass landed in the same effect-priority sequence.
   - Unicorn Tears avatar placement/anchoring follow-up landed.

- P1 implemented:
   - Fractal Zoom startup variance + framing-drift control updates landed.
   - Starfield depth/reactivity evolution updates landed (including stronger music-ray interaction).
   - Vector motion-accent updates landed (pulsing edge racers/beads).

- P2 implemented:
   - Psychedelic zoom tweakable landed.
   - Van Gogh long-view variation/evolution pass landed.

- P3 implemented:
   - Metaballs split-pacing policy landed with raver-profile-specific partial rollback behavior.
   - Prism Storm theme/name alignment landed (`Prism Lattice`).

