# Unicorn Viz — Effect Settings Reference

Owner: Studio Documentation
Status: active
Last updated: 2026-06-04

This document lists every built-in effect and its tweakable values under `[effects.<ClassName>]` in `config.toml`.

Notes:
- Keys are **class names**, not display names.
- If an effect does not list settings here, it currently has no user-tweakable parameters.
- Global audio reactivity and playlist behavior are controlled outside `[effects]`.
- Every effect can optionally define `reactivity` under `[effects.<ClassName>]`.
	This is an absolute override for that effect's reactivity.
	If omitted, the effect uses global `audio.reactivity`.
- Any effect may also define optional randomization bounds under its own
	section.  These keys override the global hotkey defaults only while that
	effect is active:
	- `random_speed_min` / `random_speed_max`
	- `random_zoom_min` / `random_zoom_max`
	- `random_reactivity_min` / `random_reactivity_max`
	If omitted, the effect falls back to the global `[hotkeys]` range values.

## Usage Pattern

```toml
[effects.ClassName]
param_name = value
# Optional for all effects:
# reactivity = 1.0  # absolute override; omit to use global audio.reactivity
```

Example:

```toml
[effects.Fire]
speed = 1.2
intensity = 0.9
zoom = 1.8

# Optional per-effect randomization overrides:
# random_speed_min = 0.8
# random_speed_max = 1.4
# random_zoom_min = 0.9
# random_zoom_max = 1.2
```

## Built-in Effects

### `AlienBiome` (`Wavey Gravy`)

```toml
[effects.AlienBiome]
speed = 1.0
```

### `ANSIViewer` (`ANSI Viewer`)

```toml
[effects.ANSIViewer]
speed = 1.0
# phosphor glow intensity
glow = 0.6
# CRT distortion strength
crt = 0.7
# seconds per file when cycling is enabled
slide_time = 15.0
# 0.0 = stay on one file, 1.0 = cycle files
cycle_files = 0.0
```

### `AudioSpectrum` (`Audio Spectrum`)

```toml
[effects.AudioSpectrum]
# 0=bars, 1=wave, 2=bars+DNA rain+nebula
mode = 2
# reserved visual gain for bars
glow = 1.0
```

### `CopperBars` (`Copper Bars`)

```toml
[effects.CopperBars]
speed = 1.0
```

### `CrystalPyramids` (`Crystal Pyramids`)

```toml
[effects.CrystalPyramids]
speed = 1.0
```

### `Cosmos` (`Cosmos`)

```toml
[effects.Cosmos]
speed = 1.0
```

### `Cube3D` (`3D Cube`)

```toml
[effects.Cube3D]
speed = 1.0
```

### `Dali` (`Dali`)

```toml
[effects.Dali]
speed = 1.0
# seconds between occasional counter-rotation events
rotation_interval = 15.0
```

### `Escher` (`Escher`)

```toml
[effects.Escher]
speed = 1.0
# 0.0 = off by default
vignette = 0.0
```

### `Curtains` (`Curtains`)

```toml
[effects.Curtains]
intensity = 0.82
speed = 1.0
zoom = 1.0
```

### `Fire` (`Fire`)

```toml
[effects.Fire]
# lifelike procedural flame strength
intensity = 0.90
# global flame motion speed
speed = 1.0
# camera zoom multiplier (1.0 = default framing)
zoom = 1.0
# random_speed_min = 0.80
# random_speed_max = 1.35
# random_zoom_min = 0.85
# random_zoom_max = 1.15
```

### `FractalZoom` (`Fractal Zoom`)

```toml
[effects.FractalZoom]
speed = 1.0
max_iter = 180
```

### `Metaballs` (`Metaballs`)

```toml
[effects.Metaballs]
speed = 1.0
# zoom = 1.0   # unset = random startup zoom each run (recommended)
# random_speed_min = 0.75
# random_speed_max = 1.25
# random_zoom_min = 0.70
# random_zoom_max = 1.30
```

### `ParticleStorm` (`Particle Storm`)

```toml
[effects.ParticleStorm]
speed = 1.0
```

### `Plasma` (`Plasma`)

```toml
[effects.Plasma]
speed = 1.0
# internal palette phase (usually auto-driven)
palette = 0.0
```

### `SineScroller` (`Sine Scroller 2.0`)

```toml
[effects.SineScroller]
speed      = 1.5
amplitude  = 0.18
font_scale = 4.0
```

### `Starfield` (`Starfield`)

```toml
[effects.Starfield]
speed = 0.5
warp  = 0.0
```

### `SystemMonitor` (`System Monitor`)

```toml
[effects.SystemMonitor]
speed = 1.0
```

### `Tunnel` (`Tunnel`)

```toml
[effects.Tunnel]
speed = 1.0
```

### `VanGogh` (`Van Gogh`)

```toml
[effects.VanGogh]
speed = 1.0
```

### `Vector` (`Vector`)

```toml
[effects.Vector]
speed = 1.0
```

### `UnicornTears` (`Unicorn Tears`) — drop-in, key `U`

```toml
[effects.UnicornTears]
speed = 1.0
zoom  = 1.0
# random_speed_min = 0.80
# random_speed_max = 1.20
# random_zoom_min = 0.85
# random_zoom_max = 1.15
```

---

## Drop-in Effects

These effects are loaded from `drop-ins/` at startup.  Config keys follow
the same pattern: `[effects.<ClassName>]`.  The same optional randomization
override keys apply here too, so you can narrow the active hotkey ranges on a
per-effect basis without touching the global defaults.

### `AlienInvasion` (`Alien Invasion`)

```toml
[effects.AlienInvasion]
fleet_speed = 1.2
zoom = 1.0
# random_zoom_min = 0.70
# random_zoom_max = 1.30
```

### `CyberWar` (`Cyber War`)

```toml
[effects.CyberWar]
attack_speed = 2.0
zoom = 1.0
# random_zoom_min = 0.70
# random_zoom_max = 1.30
```

### `DiscoBall` (`Disco Ball`)

```toml
[effects.DiscoBall]
speed          = 1.0
rotation_speed = 1.0   # independent mirror ball rotation rate
num_tiles_u    = 16    # tiles across the mirror ball U axis
num_tiles_v    = 12    # tiles across the mirror ball V axis
laser_intensity = 1.0  # brightness of disco laser beams
zoom           = 1.0
# random_speed_min = 0.80
# random_speed_max = 1.20
# random_zoom_min = 0.85
# random_zoom_max = 1.15
```

### `HackerTerminal` (`Hacker Terminal`)

```toml
[effects.HackerTerminal]
text_speed = 80.0   # characters-per-second scroll rate
zoom = 1.0
# random_zoom_min = 0.80
# random_zoom_max = 1.20
```

### `TextureShowcase` (`Texture Showcase`)

```toml
[effects.TextureShowcase]
speed        = 1.0
mix_time     = 7.0            # seconds per texture before crossfade
zoom         = 1.0
texture_dirs = "assets/textures"  # comma-separated image directories
# random_speed_min = 0.85
# random_speed_max = 1.15
# random_zoom_min = 0.85
# random_zoom_max = 1.15
```

### `ImageShowcase` (`Image Showcase`)

```toml
[effects.ImageShowcase]
image_dir = ""    # override path; empty = bundled drop-in images folder
speed     = 1.0
mix_time  = 10.0  # seconds per image before crossfade
zoom      = 1.0
# random_speed_min = 0.80
# random_speed_max = 1.20
# random_zoom_min = 0.85
# random_zoom_max = 1.15
```

Image Showcase shuffles its image order on load and rotates through ten
presentation styles for more motion and variety.

For best performance, keep source images at or below the target display
resolution. The effect caches decoded textures after warmup, but very large
files still cost more to decode the first time they are loaded.

### `ProjectMEffect` (`ProjectM Presets`)

```toml
[effects.ProjectMEffect]
speed = 1.0
preset_duration = 20.0
smooth_transition = true
lock_preset = false
start_clean = false
beat_sensitivity = 1.0
fps_hint = 60
projectm_library = ""   # optional explicit .so/.dll path
preset_dir = ""         # single override dir
preset_dirs = ""        # comma-separated additional preset dirs
texture_dirs = ""       # comma-separated image search paths for presets
start_preset = ""       # optional exact startup preset file/path
```

ProjectM Presets embeds libprojectM into Unicorn Viz as a drop-in effect.
If libprojectM cannot be loaded, or no preset pack is present, the effect
falls back to an internal shader so the playlist remains stable.

The same randomization overrides are supported here as well.  For example,
you can constrain `speed` with `random_speed_min/max` if you want F6 to stay
subtle while ProjectM is active.

Dedicated hotkeys while this effect is active:

- `Ctrl+N` — next preset
- `Ctrl+P` — previous preset
- `Ctrl+R` — random preset

### `TronGrid` (`Tron Grid`)

```toml
[effects.TronGrid]
speed      = 1.0
num_beams  = 8     # sweeping laser beams (1–12)
grid_scale = 1.0
zoom       = 1.0
# random_speed_min = 0.75
# random_speed_max = 1.25
# random_zoom_min = 0.80
# random_zoom_max = 1.20
```

### `WebcamOverlay` (`Webcam Overlay`)

```toml
[effects.WebcamOverlay]
camera_device  = 0
camera_width   = 1280
camera_height  = 720
camera_fps     = 30
pip_position   = "bottom_right"
pip_scale      = 0.33
enabled        = true    # false disables camera worker for this effect
```

> **Note:** This is the standalone playlist *effect*.  The always-on system camera
> overlay is configured under `[webcam]` — see [configuration.md](configuration.md).

### `VideoShowcase` (`Video Showcase`)

```toml
[effects.VideoShowcase]
speed    = 1.0
mix_time = 10.0   # seconds per video clip before crossfade
zoom     = 1.0
# video_dirs = "assets/videos"  # comma-separated video directories
# random_speed_min = 0.80
# random_speed_max = 1.20
# random_zoom_min = 0.85
# random_zoom_max = 1.15
```

### `SimShowcase` (`Sim Showcase`)

```toml
[effects.SimShowcase]
speed         = 1.0
mix_time      = 14.0   # seconds per scene before cut
camera_energy = 1.0    # camera motion intensity multiplier
zoom          = 1.0
# scene_dirs = "drop-ins/sims-01/scenes"  # comma-separated scene directories
# random_speed_min = 0.80
# random_speed_max = 1.20
# random_zoom_min = 0.85
# random_zoom_max = 1.15
```

### `Fireworks` (`Fireworks`)

```toml
[effects.Fireworks]
speed = 1.0
# random_speed_min = 0.80
# random_speed_max = 1.20
```

### `Psychedelic` (`Psychedelic`)

```toml
[effects.Psychedelic]
speed = 1.0
# random_speed_min = 0.70
# random_speed_max = 1.30
```
