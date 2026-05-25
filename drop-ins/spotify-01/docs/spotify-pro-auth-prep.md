# spotify-pro-01 Auth + Web API Prep

Owner: Drop-in Maintainers
Status: draft
Last updated: 2026-05-24

## Goal

Prepare everything needed to add authenticated Spotify Web API support as a
separate drop-in (`spotify-pro-01`) while keeping `spotify-01` as the local
`playerctl` path.

## What You Need To Do (Operator / Account Owner)

### 1. Create a Spotify Developer App

- Go to Spotify Developer Dashboard.
- Create an app for Unicorn Viz integration.
- Save:
  - Client ID
  - App name/description
- Do **not** share a Client Secret in live app configs.
- For the local Unicorn Viz runtime, the Client Secret is not needed because
  the app uses Authorization Code with PKCE.

## 2. Configure Redirect URI(s)

Add the local auth callback redirect URI:

- `http://127.0.0.1:43879/callback`

Notes:

- Redirect URI must match exactly in Spotify app settings and runtime config.
- Use `127.0.0.1`, not `localhost`, for Spotify local development redirects.
- We use loopback + PKCE so no secret is required in runtime.

## 3. Approve Required Scopes

Minimum for playback/queue intelligence:

- `user-read-playback-state`
- `user-read-currently-playing`

For playlist context and full item lists:

- `playlist-read-private`
- `playlist-read-collaborative`

Optional future control scopes (not required for read-only phase):

- `user-modify-playback-state`

## 4. Validate Account + Playback Preconditions

- Spotify desktop app installed and signed in.
- Active playback device available during testing.
- Network access available to Spotify API endpoints.

## 5. Decide Privacy + Logging Policy

Pick policy before implementation:

- Whether track names/artists can be written to logs.
- Whether playlist IDs/names are allowed in logs/HUD.
- Whether private playlist metadata is retained on disk.

## What We Will Build (Implementation Side)

## A. Auth Flow (PKCE)

- Local browser-based OAuth authorization.
- Local callback listener on loopback (`127.0.0.1`).
- PKCE verifier/challenge generation.
- Access token + refresh token lifecycle.

## B. Token Storage

- Local token file under project runtime state.
- Expiry tracking and refresh-on-demand.
- Clear failure states for revoked/expired consent.

## C. Spotify-Pro Runtime Surface

Expose a stable snapshot for app/Auto VJ/HUD:

- current playback state
- context type/URI
- queue items
- optional resolved playlist details (count/order/duration)

## D. Fail-Safe Behavior

- If auth unavailable, `spotify-pro-01` stays disabled gracefully.
- `spotify-01` keeps working independently.
- No hard dependency from core runtime on authenticated mode.

## Initial Runtime Config Sketch (commented)

```toml
[spotify_pro]
enabled = false
client_id = ""
redirect_uri = "http://127.0.0.1:43879/callback"
scopes = [
  "user-read-playback-state",
  "user-read-currently-playing",
  "playlist-read-private",
  "playlist-read-collaborative",
]
token_store = "runtime/spotify-pro-token.json"
poll_interval_s = 1.0
resolve_playlist_context = true
resolve_queue = true
```

## Acceptance Checklist Before Coding

- [ ] Spotify app created
- [ ] Client ID captured
- [ ] Redirect URI added exactly
- [ ] Scope set approved
- [ ] Privacy/logging policy agreed
- [ ] Test account/device ready

## Next Step

Once the above checklist is complete, implementation can start with:

1. `spotify-pro-01` auth bootstrap command
2. token refresh + health checks
3. playback + queue API reads
4. playlist-context resolver
5. Auto VJ / HUD optional consumers
