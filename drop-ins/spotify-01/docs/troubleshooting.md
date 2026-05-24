# spotify-01 Troubleshooting

Owner: Drop-in Maintainers
Status: active
Last updated: 2026-05-24

## Subsystem Not Loading

- Confirm `[spotify].enabled = true`.
- Verify `playerctl` is installed (`command -v playerctl`).
- Check app logs for `SpotifyController` warnings.

## No Track Metadata

- Ensure Spotify desktop app is running.
- Confirm MPRIS player name matches `[spotify].player`.
- Try `playerctl --player=spotify metadata` manually.

## Auto VJ Not Reacting To Track Changes

- Confirm Auto VJ is enabled.
- Confirm Spotify status is `playing` (not paused/stopped).
- Check Auto VJ decision logs for `*_SPOTIFY` effect swap markers.

## Features File Ignored

- Ensure path exists and JSON is valid.
- Keys must match full track id (for example `spotify:track:<id>`).
