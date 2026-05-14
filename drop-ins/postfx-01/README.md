# postfx-01

System-level post-process drop-in stack for Unicorn Viz.

This drop-in hosts post-process effects in `effects/` so new effects can be
added without modifying core app render code.

## Developer Guide

See [DEVELOPER_NOTES.md](DEVELOPER_NOTES.md) for lessons learned building the first four effects,
architecture decisions, common pitfalls, and a checklist for adding new effects.

## Hotkeys

- `Ctrl+Alt+1` -> Post FX slot 1
- `Ctrl+Alt+2` -> Post FX slot 2
- `Ctrl+Alt+3` -> Post FX slot 3
- `Ctrl+Alt+4` -> Post FX slot 4
- `Ctrl+Alt+5` -> Post FX slot 5
- `Ctrl+Alt+6` -> Post FX slot 6
- `Ctrl+Alt+7..8` -> Reserved slots

All post FX in this drop-in are one-shot quick hitters (burst-style), not
latched toggles.

## Effect checklist (8-slot roadmap)

- [x] 1. Temporal Feedback Trail
- [x] 2. Chromatic Aberration
- [x] 3. Film Grain + Dither
- [x] 4. Lens Distortion + Vignette
- [x] 5. Radial Zoom Blur
- [x] 6. Glitch Slices
- [ ] 7. Multi-pass Bloom
- [ ] 8. Heat Haze Refraction

## Layout

- `postfx_controller.py` - slot routing, lifecycle, hotkey-facing selection API
- `effects/base.py` - shared fullscreen pass helpers
- `effects/*.py` - individual post-process effect implementations

## Notes

- The built-in Ctrl+U burst remains in core system code by design.
- This drop-in is optional; app runs normally when absent.
