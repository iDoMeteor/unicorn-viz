# spotify-01 Planning

Owner: Drop-in Maintainers
Status: active
Last updated: 2026-05-24

## Purpose

Track the current scope of `spotify-01`, define near-term follow-up work, and
separate baseline live-safe metadata support from future authenticated Spotify
Web API work.

## Current State

`spotify-01` currently implements the low-friction live runtime path:

- Poll Spotify desktop metadata via `playerctl` / MPRIS
- Expose current playback snapshot through `snapshot()`
- Surface current track title/artist/album/status/progress
- Support optional local per-track feature metadata from a JSON file
- Feed Auto VJ with:
  - pause-aware automation hold
  - track-change cues
  - optional per-track `bpm` / `energy` / `danceability` / `valence`
- Feed the HUD with a now-playing sub-pane

This path was chosen first because it:

- has no OAuth flow
- works well for local live performance setups
- fails gracefully when Spotify or `playerctl` is unavailable
- avoids introducing token refresh, auth storage, and Web API rate-limit logic

## Confirmed Limits Of Current Path

The current `playerctl` / MPRIS path is intentionally limited to *currently
playing* metadata.

What we can read now:

- active playback state
- current track identity and timing
- locally curated feature metadata keyed by track id

What we do not currently have in a reliable way:

- current queue
- upcoming tracks before they start
- current playlist membership/order
- total playlist size / time remaining in playlist
- playback context details suitable for planning logic

## Why The Web API Path Should Be A Separate Drop-In

Future authenticated Spotify work should ship as a separate optional drop-in,
currently planned as `spotify-pro-01`.

Reasons for separation:

- OAuth/token handling is operationally different from `playerctl`
- failures and expiry behavior are different and need separate UX
- Web API rate limits and network failure need distinct guardrails
- some operators may want local metadata only with no account linking
- the core app should keep the zero-config live-safe path available

Recommended model:

- `spotify-01` = local desktop metadata path (`playerctl`)
- `spotify-pro-01` = authenticated Spotify Web API context/queue/intelligence

## Proposed spotify-pro-01 Scope

### Phase 1: Authenticated Playback Context

- OAuth token acquisition and refresh
- current playback state (`/me/player`)
- playback context object (playlist / album / artist / radio when present)
- richer device state, shuffle, repeat, and context URI

### Phase 2: Queue Awareness

- current queue (`/me/player/queue`)
- near-future track lookahead for Auto VJ planning
- pre-cue transitions based on queue item features

### Phase 3: Playlist Intelligence

- playlist item enumeration when playback context is a playlist
- total item count
- total duration and estimated remaining duration
- optional retrieval of track-level planning metadata before playback

### Phase 4: Automation Intelligence

- "up next" styling in HUD / Control Room
- Auto VJ pre-roll planning based on the next 1-3 tracks
- context-aware end-of-playlist / final-song behavior
- optional genre arc planning when playlist order is known and stable

## Data Model Direction

### spotify-01 snapshot

Keep the existing snapshot lightweight and runtime-safe:

- `available`
- `is_playing`
- `status`
- `track_id`
- `title`
- `artist`
- `album`
- `duration_s`
- `position_s`
- `progress`
- optional local features/tags

### spotify-pro-01 snapshot

Proposed richer payload:

- `context_type`
- `context_uri`
- `queue_items[]`
- `playlist_id`
- `playlist_name`
- `playlist_total_tracks`
- `playlist_total_duration_s`
- `playlist_remaining_duration_s`
- `next_track_features[]`
- `shuffle_state`
- `repeat_state`
- `device`

## Product Notes

Queue and playlist should be treated differently.

- Queue answers: "what will likely play soon?"
- Playlist answers: "what is the broader ordered source context?"

Important live behavior note:

- playlist order is not necessarily playback order when shuffle, radio,
  recommendations, autoplay, or manual queue modifications are active
- Auto VJ should prefer queue data over playlist order whenever both exist

## API/Scope Notes For spotify-pro-01

Expected Spotify Web API scopes:

- `user-read-playback-state`
- `user-read-currently-playing`
- `playlist-read-private` when playlist contents are needed

## Open Questions

- Where should OAuth tokens be stored locally?
- Should `spotify-pro-01` expose controls or remain read-only first?
- Should Control Room show queue/playlist context directly?
- How should private playlists be handled in logs and HUDs?
- Should Auto VJ have a hard dependency on queue data for any behavior, or
  only use it as an enhancement layer?

## Recommended Next Step

When ready, create `spotify-pro-01` as a dedicated drop-in repository with:

- its own docs set
- explicit auth/config flow
- separate failure handling
- a compatibility contract back to `spotify-01` / Auto VJ / Control Room
