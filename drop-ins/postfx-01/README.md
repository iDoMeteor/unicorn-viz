# postfx-01

System-level post-process drop-in stack for Unicorn Viz.

This drop-in hosts post-process effects in `effects/` so new effects can be
added without modifying core app render code.

## Developer Guide

See [DEVELOPER_NOTES.md](DEVELOPER_NOTES.md) for lessons learned building the first four effects,
architecture decisions, common pitfalls, and a checklist for adding new effects.

## Hotkeys

Slots are ordered alphabetically by effect name:
- `Ctrl+Alt+1` -> Chromatic Aberration
- `Ctrl+Alt+2` -> Film Grain + Dither
- `Ctrl+Alt+3` -> Glitch Slices
- `Ctrl+Alt+4` -> Heat Haze Refraction
- `Ctrl+Alt+5` -> Lens Distortion + Vignette
- `Ctrl+Alt+6` -> Multi-pass Bloom
- `Ctrl+Alt+7` -> Radial Zoom Blur
- `Ctrl+Alt+8` -> Temporal Feedback Trail

All post FX in this drop-in are one-shot quick hitters (burst-style), not
latched toggles.

## Effect checklist (8-slot roadmap)

- [x] 1. Temporal Feedback Trail
- [x] 2. Chromatic Aberration
- [x] 3. Film Grain + Dither
- [x] 4. Lens Distortion + Vignette
- [x] 5. Radial Zoom Blur
- [x] 6. Glitch Slices
- [x] 7. Multi-pass Bloom
- [x] 8. Heat Haze Refraction

## Layout

- `postfx_controller.py` - slot routing, lifecycle, hotkey-facing selection API
- `effects/base.py` - shared fullscreen pass helpers
- `effects/*.py` - individual post-process effect implementations

## Notes

- The built-in Ctrl+U burst remains in core system code by design.
- This drop-in is optional; app runs normally when absent.
