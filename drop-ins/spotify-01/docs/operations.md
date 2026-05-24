# spotify-01 Operations

Owner: Drop-in Maintainers
Status: active
Last updated: 2026-05-24

## Runtime Behavior

- Polls `playerctl` on a throttled interval (default `0.75s`)
- Updates metadata snapshot for other controllers
- Does not render directly and has no hotkeys

## Startup Expectations

- If `[spotify].enabled = false`, subsystem is skipped
- If `playerctl` is missing, subsystem self-disables gracefully

## Shutdown

- No external process is spawned; shutdown is a no-op
