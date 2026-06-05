# spotify-01

Owner: Drop-in Maintainers
Status: active
Last updated: 2026-05-24

`spotify-01` is an optional runtime subsystem that polls Spotify metadata via
MPRIS (`playerctl`) and exposes now-playing context to automation controllers.

Current platform note: this backend is Linux-oriented. It depends on
`playerctl` talking to an MPRIS-exposing desktop player. Windows is not
currently supported by `spotify-01` without a separate Windows media-session
backend.

## What It Provides

- Track metadata snapshot (`track_id`, title, artist, album, status)
- Playback timing (`duration_s`, `position_s`, progress)
- Optional per-track feature map (`bpm`, `energy`, `danceability`, `valence`)

## Dependencies

- `playerctl` must be installed and available on `PATH`
- Spotify desktop client (or compatible MPRIS player name)
- On Windows, installing a package alone is not sufficient because the current
	implementation expects an MPRIS-compatible backend.

## Installer

This drop-in ships a bundle installer script at `install.sh`.

```bash
bash install.sh --root ~/.local/share/unicorn-viz
```

The installer copies the bundle into `~/.local/share/unicorn-viz/drop-ins/spotify-01`
and refuses to run if `playerctl` is missing. Use `--uninstall` to remove the
bundle again.

## Configuration

See `docs/configuration.md`.

## Integration

- Registers as subsystem name `spotify` via `vj_api.register_subsystem`
- Auto VJ can consume this subsystem when both are enabled

## Planning

See `docs/planning.md` for the current/future roadmap, including the planned
authenticated Web API follow-up as a separate `spotify-pro-01` drop-in.

For operator setup prerequisites, see `docs/spotify-pro-auth-prep.md`.

## Troubleshooting

See `docs/troubleshooting.md`.
