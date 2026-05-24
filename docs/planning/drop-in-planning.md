# Drop-In Planning

## Control Room Follow-Ups

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
