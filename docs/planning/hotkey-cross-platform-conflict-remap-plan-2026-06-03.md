# Cross-Platform Hotkey Conflict Remap Plan (2026-06-03)

Owner: Runtime/Input
Status: proposed
Last updated: 2026-06-03

## Objective

Reduce collisions between Unicorn Viz hotkeys and desktop/global shortcuts on:

- GNOME (Wayland/X11)
- KDE Plasma (Wayland/X11)
- macOS
- Windows

without relying on compositor keyboard-grab behavior.

## Scope

This proposal covers high-friction combinations currently used by core and drop-ins:

- Ctrl+Alt chords (especially numbers and letter combos)
- Alt+Shift profile combos
- Function-key combos likely to collide with OS/media layers

## Current High-Risk Hotkeys

- Ctrl+Alt+1..9,0 (Post FX quick slots)
- Ctrl+Alt+J (Auto VJ)
- Ctrl+Alt+O (Control Room)
- Ctrl+Alt+S / Ctrl+Alt+Shift+S (Spotify Pro auth/logout)
- Ctrl+Alt+F / Ctrl+Alt+Shift+F (Grand Finale)
- Ctrl+Alt+U (Screen Burst)
- Alt+A / Alt+Shift+A (Audio profile cycling)
- F8/F9/F10/F11 (+ Ctrl variants)

## Proposed Remap Strategy

### 1) Introduce a dedicated app chord prefix

Use a consistent "app leader" prefix for system-level actions:

- Suggested leader: Ctrl+Shift+Alt

Rationale:

- Less frequently reserved by GNOME/KDE global defaults than Ctrl+Alt
- Distinctive enough to avoid accidental triggers
- Cross-platform workable with fewer desktop collisions

### 2) Move high-risk Ctrl+Alt actions to leader equivalents

| Current | Proposed | Feature |
|---|---|---|
| Ctrl+Alt+J | Ctrl+Shift+Alt+J | Auto VJ toggle |
| Ctrl+Alt+O | Ctrl+Shift+Alt+O | Control Room toggle |
| Ctrl+Alt+S | Ctrl+Shift+Alt+S | Spotify auth |
| Ctrl+Alt+Shift+S | Ctrl+Shift+Alt+L | Spotify logout |
| Ctrl+Alt+F | Ctrl+Shift+Alt+F | Grand Finale trigger |
| Ctrl+Alt+Shift+F | Ctrl+Shift+Alt+X | Grand Finale abort |
| Ctrl+Alt+U | Ctrl+Shift+Alt+U | Screen Burst |
| Ctrl+Alt+C | Ctrl+Shift+Alt+C | Candy Frame toggle |
| Ctrl+Alt+K | Ctrl+Shift+Alt+K | Webcam editor modal |

### 3) Replace Post FX numeric chords

Post FX quick slots currently collide heavily with WM bindings in some setups.

Proposed:

- Ctrl+Shift+Alt+1..0 for direct slot triggers

Alternative if number rows conflict in specific layouts:

- Ctrl+Shift+Alt+Q/W/E/R/T/Y/U/I/O/P mapped to slots 1..0

### 4) Move audio profile cycling off Alt+Shift family

| Current | Proposed |
|---|---|
| Alt+A | Ctrl+Shift+Alt+A |
| Alt+Shift+A | Ctrl+Shift+Alt+Shift+A |

Rationale: Alt+Shift often controls input-language switching on Linux/Windows.

### 5) Keep effect-local Ctrl+N/P/R as-is

- ProjectM and Sim scene/preset controls via Ctrl+N/Ctrl+P/Ctrl+R should remain
  unchanged.
- These are app-context controls with relatively low OS-level collision risk.

### 6) Keep F8/F9/F10/F11 but add robust alternates

Retain current streaming keys, plus alternates for laptop/macOS Fn-media contexts:

- F8 (stream toggle) alternate: Ctrl+Shift+Alt+8
- F9 (CTA) alternate: Ctrl+Shift+Alt+9
- Ctrl+F9/F10/F11 provider shortcuts alternates:
  - Ctrl+Shift+Alt+R (Rumble)
  - Ctrl+Shift+Alt+Y (YouTube)
  - Ctrl+Shift+Alt+E (Custom endpoint)

## Rollout Plan

1. Add remapped bindings in handlers while keeping legacy bindings temporarily.
2. Expose both in HELP_TEXT during transition.
3. Add config flag to disable legacy hotkeys once validated.
4. Remove legacy bindings after one stabilization cycle.

## Validation Checklist

- Verify all remapped combos are detected on GNOME Wayland.
- Verify same on KDE Wayland.
- Validate macOS with and without "Use F1, F2, ... as standard function keys".
- Validate Windows with common OEM media-key layers.
- Confirm no regressions for effect-local Ctrl+N/P/R and number-jump hotkeys.

## Notes

This plan intentionally avoids compositor shortcut inhibition and keyboard-grab
mechanisms. The design goal is compatibility-first behavior under standard desktop
shortcut policies.
