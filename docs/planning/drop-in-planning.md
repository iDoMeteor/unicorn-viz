# Drop-In Planning

## Control Room Follow-Ups

### Control Room Manager Track (2026-06-05)

- `[active]` Layout and sizing stabilization pass for `control-room-01`.
  Notes:
  - establish a single layout contract with panel min sizes, priority tiers, and deterministic compact fallbacks
  - add explicit breakpoints (wide, medium, compact, tiny-safe)
  - keep critical controls always visible in every breakpoint (transport, display mode switching, effect selection, emergency actions)
  - route all geometry through one cached layout computation path during resize and redraw

- `[active]` Operator ergonomics and scaling hardening.
  Notes:
  - derive fonts/padding/button sizes from one clamped UI scale value
  - preserve preview aspect ratio with letterboxing rules
  - enforce min readable text and min click target sizes

- `[active]` Windows compatibility truth tracking for control room.
  Notes:
  - owner-machine Windows runtime currently passes for operator-window open/close and control flow
  - hotkey model updated: `Shift+M` toggles control room, `M` controls system monitor modal
  - control-room-focused key events now forward to global hotkeys when not consumed locally
  - control-room display mode buttons now render from runtime-supported mode list so new multi-head modes appear without manual UI updates
  - Linux operator-window remains N/A for production pending separate-process architecture

- `[todo]` Add hardware-inspired page layout pass to `control-room-01`.
  Notes:
  - reorganise preview, transport, FX, and effect-selection zones to feel more like standard VJ hardware banks/pages
  - bias toward large hit targets, persistent status strips, and bank/group concepts that later map cleanly to controllers

- `[todo]` Add a dedicated `Decks / Cues / Timing` page to `control-room-01`.
  Notes:
  - use this as the first bridge toward Serato / Mixxx / xwax style workflows
  - include room for deck timing, cue state, phrasing, and transition timing indicators

## Spotify Drop-In

- `[todo]` `spotify-01` — optional Spotify transport / metadata bridge.
  Notes:
  - primary target: ingest currently playing track, artist, title, play/pause state, and coarse timing
  - likely Linux path: MPRIS over D-Bus first; Web API only as an optional secondary path
  - useful follow-ons: bias Auto VJ profile/effect choices from track tempo or section labels when available
  - must remain optional and never block app startup when Spotify is absent

## Mixxx / xwax / Giada Drop-Ins

- `[todo]` `mixxx-01` — deck/transport bridge for Mixxx.
  Notes:
  - read deck state, BPM, transport, crossfader, and cue information when available
  - surface transport/focus cues into Control Room and Auto VJ safely

- `[todo]` `xwax-01` — lightweight vinyl-control / deck-state bridge for xwax.
  Notes:
  - likely smaller scope than Mixxx; prioritise track/deck status and tempo cues
  - keep Linux-first assumptions explicit

- `[todo]` `giada-01` — live-loop / clip-state bridge for Giada.
  Notes:
  - focus on scene/clip launch status, tempo, and section energy hints
  - useful for synchronising visual scene changes to live loop performance structure
