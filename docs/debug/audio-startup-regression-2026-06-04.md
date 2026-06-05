# Audio Startup Regression + Validation Hardening (2026-06-04)

Owner: Runtime Team
Status: active
Last updated: 2026-06-04

## Summary

This note captures the June 3-4 audio startup failure investigation, confirmed
root cause, and resulting hardening work.

## What Happened

Observed startup failures:
- `RuntimeError: Audio startup failed after 3 attempts`
- `RuntimeError: Audio capture did not become active`

Failure appeared inconsistent at first because:
- Some runs succeeded earlier on June 4.
- A later run failed with no code changes in between.

## Confirmed Root Cause

Immediate blocker (reproduced directly):
- `audio.latency = "medium"` in `config.toml` reached PortAudio as a raw string.
- Current `sounddevice` / PortAudio path rejected it with:
  `must be real number, not str`
- Every candidate open failed, so capture never became active.

Secondary diagnostics issue:
- INFO-band logging originally suppressed warnings, obscuring candidate-open
  failure details in normal startup logs.

## Key Fixes Landed

1. Audio latency normalization in capture startup:
- Supports `low` / `high` labels directly.
- Maps `medium` to a numeric midpoint (`0.06` seconds) for compatibility.
- Accepts numeric latency values (seconds).

2. Startup diagnostics visibility:
- INFO log band now includes WARNING records.

3. Warmup logging safety:
- Guarded warmup elapsed debug output to avoid meaningless huge elapsed values
  when no stream has opened yet.

4. Centralized config validation:
- Built-in config types and constraints validated before app startup.
- Invalid values now fail fast with a consolidated error list.

5. Drop-in validator extension:
- Drop-ins can contribute optional config validation via
  `drop-ins/<name>/config_validator.py` with `validate_config(config_data)`.

## Behavior Notes

Audio startup policy:
- `audio.require_startup = false` (default) allows degraded startup when audio
  cannot initialize.
- `audio.require_startup = true` enforces fail-closed startup.

Audio source ordering:
- `audio.prefer_default_input` controls whether OS default input is prioritized
  in candidate selection.

## Operator Checks

If startup audio fails again:
1. Set `--log-level INFO` (or DEBUG) and inspect WARNING lines from
   `unicornviz.audio.capture`.
2. Validate config first; ensure `audio.latency` is valid.
3. Check user-session PipeWire state:
   `systemctl --user status pipewire pipewire-pulse wireplumber`
4. Avoid `sudo systemctl --user ...`; that targets root's user session,
   not the logged-in user session running Unicorn Viz.
