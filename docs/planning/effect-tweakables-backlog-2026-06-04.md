# Effect Tweakables Backlog (Zoom/Speed/Reactivity)

Owner: Runtime Systems
Status: draft
Last updated: 2026-06-04

## Scope

Audit target: all core effects and visual drop-in effects/systems.

Categories tracked per component:
- `zoom` tweakable exposed
- `speed` tweakable exposed
- `reactivity` tweakable exposed

## Summary

Snapshot note: counts below reflect the original 2026-06-04 audit pass before
legacy effect removals listed at the bottom of this document.

- Components audited: 38
- Full coverage (`zoom` + `speed` + `reactivity`): 2
- Missing exactly 1 category: 7
- Missing exactly 2 categories: 28
- Missing all 3 categories: 3

## Full Coverage (No Immediate Work)

- Sim Showcase (`drop-ins/sims-01/sim_showcase.py`)
- Unicorn Tears (`drop-ins/unicorn-tears-01/unicorn_tears.py`)

## Low-Lift Backlog

These are closest to complete and should be the first implementation batch.

- Kaleidoscope (`unicornviz/effects/kaleidoscope.py`) — missing `reactivity`
- Metaballs (`unicornviz/effects/metaballs.py`) — missing `reactivity`
- Sine Scroller (`unicornviz/effects/audio_sine.py`) — missing `zoom`
- Disco Ball (`drop-ins/disco-ball-01/disco_ball.py`) — missing `reactivity`
- Prism Storm (`drop-ins/textures-01/prism_storm.py`) — missing `reactivity`
- Tron Grid (`drop-ins/tron-grid-01/tron_grid.py`) — missing `reactivity`

## Medium-Lift Backlog

- Wavey Gravy (`unicornviz/effects/wavey_gravy.py`) — missing `zoom`, `reactivity`
- ANSI Viewer (`unicornviz/effects/ansi_viewer.py`) — missing `zoom`, `reactivity`
- Copper Bars (`unicornviz/effects/copper_bars.py`) — missing `zoom`, `reactivity`
- Cosmos (`unicornviz/effects/cosmos.py`) — missing `zoom`, `reactivity`
- Rainbow Trance (`unicornviz/effects/rainbow_trance.py`) — missing `zoom`, `reactivity`
- Cube 3D (`unicornviz/effects/cube_3d.py`) — missing `zoom`, `reactivity`
- Dali (`unicornviz/effects/dali.py`) — missing `zoom`, `reactivity`
- Escher (`unicornviz/effects/escher.py`) — missing `zoom`, `reactivity`
- Fire Lifelike (`unicornviz/effects/fire_lifelike.py`) — missing `zoom`, `reactivity`
- Fireworks (`unicornviz/effects/fireworks.py`) — missing `zoom`, `reactivity`
- Particle Storm (`unicornviz/effects/particle_storm.py`) — missing `zoom`, `reactivity`
- Plasma (`unicornviz/effects/plasma.py`) — missing `zoom`, `reactivity`
- Psychedelic (`unicornviz/effects/psychedelic.py`) — missing `zoom`, `reactivity`
- Starfield (`unicornviz/effects/starfield.py`) — missing `zoom`, `reactivity`
- Tunnel (`unicornviz/effects/tunnel.py`) — missing `zoom`, `reactivity`
- Van Gogh (`unicornviz/effects/van_gogh.py`) — missing `zoom`, `reactivity`
- Vector (`unicornviz/effects/vector.py`) — missing `zoom`, `reactivity`
- ProjectM Presets (`drop-ins/projectm-01/projectm_effect.py`) — missing `zoom`, `reactivity`
- Dancing Unicorn Overlay (`drop-ins/unicorn-tears-01/dancing_unicorn_overlay.py`) — missing `zoom`, `speed`
- Alien Invasion (`drop-ins/alien-invasion-01/alien_invasion.py`) — missing `speed`, `reactivity`
- Cyber War (`drop-ins/cyber-war-01/cyber_war.py`) — missing `speed`, `reactivity`
- Hacker Terminal (`drop-ins/hacker-terminal-01/hacker_terminal.py`) — missing `speed`, `reactivity`
- Image Showcase (`drop-ins/images-01/image_showcase.py`) — missing `speed`, `reactivity`
- Texture Showcase (`drop-ins/textures-01/texture_showcase.py`) — missing `speed`, `reactivity`
- Video Showcase (`drop-ins/videos-01/video_showcase.py`) — missing `speed`, `reactivity`

## High-Lift Backlog

- Fractal Zoom (`unicornviz/effects/fractal_zoom.py`) — missing `zoom`, `speed`, `reactivity`
- Rainbow Nova Overlay (`drop-ins/unicorn-tears-01/rainbow_nova.py`) — missing `zoom`, `speed`, `reactivity`
- Screen Burst Controller (`drop-ins/unicorn-tears-01/screen_burst_controller.py`) — missing `zoom`, `speed`, `reactivity`

## Exclusions

- Audio Spectrum (`unicornviz/effects/audio_spectrum.py`) — exempt by project policy
- System Monitor (`unicornviz/effects/system_monitor.py`) — exempt by project policy

Non-visual controllers/managers were not included in this backlog.

## Removed Effects (Not Actionable)

The original audit included these legacy effects, which were deleted on
2026-06-04 and are intentionally not part of implementation work:

- Fire (`unicornviz/effects/fire.py`)
- Raymarcher (`unicornviz/effects/raymarcher.py`)
- Water (`unicornviz/effects/water.py`)
