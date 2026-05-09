# Unicorn Viz — Effect Settings Reference

This document lists every built-in effect and its tweakable values under `[effects.<ClassName>]` in `config.toml`.

Notes:
- Keys are **class names**, not display names.
- If an effect does not list settings here, it currently has no user-tweakable parameters.
- Global audio reactivity and playlist behavior are controlled outside `[effects]`.
- Every effect can optionally define `reactivity` under `[effects.<ClassName>]`.
	This is an absolute override for that effect's reactivity.
	If omitted, the effect uses global `audio.reactivity`.

## Usage Pattern

```toml
[effects.ClassName]
param_name = value
# Optional for all effects:
# reactivity = 1.0
```

Example:

```toml
[effects.Fire]
speed = 1.2
intensity = 0.9
zoom = 1.8
```

## Built-in Effects

### `WaveyGravy` (`Wavey Gravy`)

```toml
[effects.WaveyGravy]
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

### `Raymarcher` (`Raymarcher`)

```toml
[effects.Raymarcher]
speed = 1.0
```

### `SineScroller` (`Sine Scroller`)

```toml
[effects.SineScroller]
speed = 1.5
amplitude = 0.18
font_scale = 4.0
```

### `Starfield` (`Starfield`)

```toml
[effects.Starfield]
speed = 0.5
warp = 0.0
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
```

### `Water` (`Water`)

```toml
[effects.Water]
amplitude = 1.0
speed = 1.0
```
