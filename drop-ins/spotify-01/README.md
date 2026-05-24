# spotify-01

Owner: Drop-in Maintainers
Status: active
Last updated: 2026-05-24

`spotify-01` is an optional runtime subsystem that polls Spotify metadata via
MPRIS (`playerctl`) and exposes now-playing context to automation controllers.

## What It Provides

- Track metadata snapshot (`track_id`, title, artist, album, status)
- Playback timing (`duration_s`, `position_s`, progress)
- Optional per-track feature map (`bpm`, `energy`, `danceability`, `valence`)

## Dependencies

- `playerctl` must be installed and available on `PATH`
- Spotify desktop client (or compatible MPRIS player name)

## Configuration

See `docs/configuration.md`.

## Integration

- Registers as subsystem name `spotify` via `vj_api.register_subsystem`
- Auto VJ can consume this subsystem when both are enabled

## Troubleshooting

See `docs/troubleshooting.md`.
