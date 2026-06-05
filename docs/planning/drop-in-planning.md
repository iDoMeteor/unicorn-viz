# Drop-In Planning

## Control Room Follow-Ups

### Control Room Manager Track (2026-06-05)

- `[active]` Layout and sizing stabilization pass for `control-room-01`.
  Notes:
  - establish a single layout contract with panel min sizes, priority tiers, and deterministic compact fallbacks
  - add explicit breakpoints (wide, medium, compact, tiny-safe)
  - keep critical controls always visible in every breakpoint (transport, display mode switching, effect selection, emergency actions)
  - route all geometry through one cached layout computation path during resize and redraw
  - define explicit item categorization so the surface is organized by control intent instead of current implementation ownership
  - support mixed row structures: some rows remain single-purpose, others intentionally span multiple columns when the data is related and should be scanned together

- `[active]` Control-room information architecture and categorization.
  Notes:
  - classify controls into stable top-level groups:
    - transport / playback
    - scene / effect navigation
    - output / display / recording / streaming
    - reactive tweakables / post FX
    - subsystem editors and utility modals
    - operator status / alerts / diagnostics
  - avoid letting the current implementation order dictate the operator-facing order; layout should reflect live-use priority first
  - plan for a fully loaded package where multiple optional drop-ins are present at the same time without making the primary page unreadable
  - prefer category-level containers that can accept optional rows from drop-ins instead of dedicating one fixed panel per drop-in forever

- `[active]` Special-case controller surfaces for automation and music metadata.
  Notes:
  - Auto VJ should be treated as a first-class special case rather than just another generic subsystem row
  - Spotify / Spotify Pro should also be treated as special cases because transport, metadata, auth, and playlist context are richer than normal toggle-style drop-ins
  - these subsystems may need dedicated panels or pages with denser state, richer action affordances, and stronger operator feedback than generic drop-ins
  - generic drop-in registration should still feed a common surface, but the architecture must allow hand-authored layouts for important subsystems

- `[active]` Operator ergonomics and scaling hardening.
  Notes:
  - derive fonts/padding/button sizes from one clamped UI scale value
  - preserve preview aspect ratio with letterboxing rules
  - enforce min readable text and min click target sizes
  - add a hard "screen too small" guard that switches to an operator-safe fallback instead of trying to cram the full layout into an unusable surface
  - operator-safe fallback should show only critical actions, key state, and a short reason that the full layout is suppressed at the current window size

- `[active]` Layout behavior rules for dense rows.
  Notes:
  - allow some rows to span multiple columns when controls belong together operationally
  - examples: transport + auto-advance, display mode + display target, recording + streaming state, Auto VJ mode + lock/director state
  - multi-column rows must collapse deterministically at compact breakpoints instead of wrapping arbitrarily
  - row behavior should be part of the layout contract, not ad hoc per panel

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
  - include category-aware page planning so future loaded packages can split into pages/banks cleanly without rewriting the whole control-room surface

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
