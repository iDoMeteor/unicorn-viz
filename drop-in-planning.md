# Drop-In Planning

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
