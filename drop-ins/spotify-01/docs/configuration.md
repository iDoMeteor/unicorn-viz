# spotify-01 Configuration

Owner: Drop-in Maintainers
Status: active
Last updated: 2026-05-24

```toml
[spotify]
enabled = false
player = "spotify"
poll_interval_s = 0.75
command_timeout_s = 0.25
# features_file = "assets/audio/spotify_features.json"
```

## Keys

- `enabled`: Master toggle for subsystem startup.
- `player`: MPRIS player name passed to `playerctl --player=<name>`.
- `poll_interval_s`: Metadata poll cadence in seconds.
- `command_timeout_s`: Per-command timeout guard in seconds.
- `features_file`: Optional JSON map keyed by Spotify track id with feature payload.

## Optional Features File Format

```json
{
  "spotify:track:2TpxZ7JUBn3uw46aR7qd6V": {
    "bpm": 128,
    "energy": 0.82,
    "danceability": 0.71,
    "valence": 0.64,
    "confidence": 0.90,
    "tags": ["house", "peak-time"],
    "genres": ["electronic", "dance"],
    "tag_confidence": 0.85
  }
}
```
