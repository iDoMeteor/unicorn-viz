# Unicorn Viz — User Guide

## Contents

1. [Requirements](#requirements)
2. [Installation](#installation)
3. [Running](#running)
4. [Keyboard Shortcuts](#keyboard-shortcuts)
5. [MIDI Control](#midi-control)
6. [Configuration](#configuration)
7. [ANSI Art](#ansi-art)
8. [Audio Setup](#audio-setup)
9. [Effects Reference](#effects-reference)
10. [Troubleshooting](#troubleshooting)

---

## Requirements

| Dependency      | Minimum version | Purpose                          |
|-----------------|-----------------|----------------------------------|
| Python          | 3.11            | `tomllib` is stdlib in 3.11+     |
| SDL2            | 2.0.18          | Window creation, Wayland/X11     |
| OpenGL          | 3.3 core        | All rendering                    |
| PipeWire / ALSA | any             | Audio loopback capture           |

Python packages (see `requirements.txt`):

```
moderngl >= 5.11
pysdl2
pysdl2-dll
numpy
scipy
sounddevice >= 0.4
python-rtmidi >= 1.5   (optional — MIDI control)
Pillow                 (screenshots)
```

---

## Installation

```bash
git clone https://github.com/yourname/unicorn-viz
cd unicorn-viz
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Wayland / X11

Unicorn Viz defaults to the **Wayland** SDL driver.  If your compositor does
not support XWayland GL, it falls back to X11 automatically.  Force X11 with:

```bash
SDL_VIDEODRIVER=x11 python -m unicornviz
```

---

## Running

```bash
./run.sh                     # convenience wrapper
python -m unicornviz         # explicit
.venv/bin/python -m unicornviz
```

Pass a custom config file:

```bash
python -m unicornviz --config /path/to/myconfig.toml
```

Common runtime overrides:

```bash
python -m unicornviz \
	--mode random \
	--transition shuffle \
	--effect-duration 45 \
	--reactivity 2.0 \
	--audio-device spotify \
	--log-level DEBUG
```

Show all available options:

```bash
python -m unicornviz --help
```

---

## Keyboard Shortcuts

| Key               | Action                                                        |
|-------------------|---------------------------------------------------------------|
| `N` / `→`         | Next effect                                                   |
| `P` / `←`         | Previous effect                                               |
| `1`–`9`           | Jump directly to effect #1–9                                 |
| `Shift+1`–`Shift+0` | Jump directly to effect #10–20                            |
| `Ctrl+1`–`Ctrl+0` | Jump directly to effect #21–30                               |
| `,`               | ANSI Viewer — own art                                         |
| `.`               | ANSI Viewer — ACiD art                                        |
| `U`               | Jump to Unicorn Tears                                         |
| `Shift+U`         | Replay splash screen                                          |
| `R`               | Toggle random / sequential playlist mode                      |
| `T`               | Toggle auto-advance on / off                                  |
| `Space`           | Pause / resume                                                |
| `F`               | Toggle fullscreen                                             |
| `G` / `Shift+G`   | Audio reactivity +0.1 / −0.1                                  |
| `Ctrl+G`          | Reset audio reactivity to configured default                   |
| `+` / `=`         | Speed up current effect (×1.25)                               |
| `-`               | Slow down current effect (×0.8)                               |
| `V`               | Toggle video recording on / off                               |
| `Tab`             | Toggle effect-name overlay                                    |
| `H`               | Toggle help panel                                             |
| `A`               | Audio device selector                                         |
| `M`               | MIDI device selector                                          |
| `S`               | Save screenshot (`screenshots/unicornviz_YYYYMMDD_HHMMSS.png`)|
| `Esc`             | Quit                                                          |

---

## Recording

Unicorn Viz can record the final on-screen output to MP4 using `ffmpeg`.

Defaults:
- recordings are saved under `recordings/`
- auto-record is off by default
- recording is video-only in the current version

When enabled, recording captures:
- effects
- transitions
- invert pass
- overlays that are visible on screen

Recording can reduce performance because the current implementation reads back
frames synchronously from the final screen output.

---

## MIDI Control

Unicorn Viz listens on the first available MIDI input port (or the port
matching the `device` substring in `config.toml`).

### Default CC mapping

| CC  | Parameter        | Effect                   |
|-----|------------------|--------------------------|
| 74  | `speed`          | Animation rate           |
| 71  | `intensity`      | Effect-specific intensity|
| 91  | `glow`           | Phosphor glow (ANSI)     |
| 93  | `crt`            | CRT barrel distortion     |
| 7   | `volume`         | (reserved)               |

### Default Note mapping (channel 1)

| Note | Name | Action        |
|------|------|---------------|
| C4 (60) | —  | Next effect   |
| D4 (62) | —  | Prev effect   |
| F4 (65) | —  | Random mode   |
| G4 (67) | —  | Pause         |
| A4 (69) | —  | Fullscreen    |

Tested with the Novation LaunchControl XL and a generic USB MIDI keyboard.
Any class-compliant USB MIDI device should work.

---

## Configuration

All settings live in `config.toml` in the project root.  Unknown keys are
ignored; missing keys use built-in defaults.

For an exhaustive template with every section and all effect overrides:

- `config.full.example.toml`

For a per-effect parameter guide:

- [Effect Settings Reference](effect-settings.md)

```toml
[window]
width      = 1920
height     = 1080
fullscreen = false
title      = "Unicorn Viz"

[demo]
mode               = "sequential"   # or "random"
effect_duration    = 20             # seconds before auto-advance
transition         = "crossfade"    # "cut" | "crossfade" | "scanwipe"
transition_duration = 1.0           # seconds

[audio]
device         = ""      # empty = auto-detect PipeWire monitor
fft_bands      = 512
buffer_seconds = 10.0

[midi]
device = ""             # empty = disabled, or name substring

[logging]
level = "INFO"
directory = "logs"

[ansi]
ansi_dir_auto = "assets/ansi/acid"   # directory (or comma-separated list) of .ans files for normal ANSIViewer autoplay

[playlist]
sequence = []           # empty = all effects; e.g. ["Plasma", "Fire", "Tunnel"]

[effects]
# Per-effect overrides, keyed by Python class name:
# [effects.Plasma]
# speed = 2.0
```

---

## ANSI Art

Drop any `.ANS` file into the directory configured by `ansi_dir_auto` and it will
be picked up automatically the next time the **ANSI Viewer** effect is active.

The viewer rotates through all files every 15 seconds (configurable via the
`slide_time` parameter), scrolling vertically through tall pieces.

### Downloaded art

The project ships with 18 real ACiD Productions pieces in `assets/ansi/acid/`,
fetched from [16colo.rs](https://16colo.rs) (`/pack/{id}/raw/`).  Original
hand-crafted demos are in `assets/ansi/`.

### Adding your own

Any ANSI art saved with a SAUCE record will have its title displayed in the
on-screen overlay (`Tab` key).  Files without SAUCE use the filename as title.
Art wider than 80 columns is supported but may be cropped at the right edge.

---

## Audio Setup

Unicorn Viz captures audio from a **monitor** (loopback) device — it listens
to whatever is playing on your system rather than the microphone.

### PipeWire (recommended)

PipeWire automatically exposes a monitor source named like
`alsa_output.*.monitor`.  Leave `device = ""` in config.toml and it will be
auto-detected.

If auto-detection fails, list devices and set the name substring:

```bash
.venv/bin/python -c "import sounddevice; print(sounddevice.query_devices())"
```

Then in `config.toml`:

```toml
[audio]
device = "monitor"   # or whatever substring matches your device
```

### JACK

Set `SDL_AUDIODRIVER=jack` and configure JACK connections manually.

## Logs

Each run writes a timestamped log file under `logs/`.

Set the level in `config.toml`:

```toml
[logging]
level = "DEBUG"
directory = "logs"
```

Or override on the command line:

```bash
python -m unicornviz --log-level DEBUG
```

---

## Effects Reference

| Effect            | Tags                  | Description                                      |
|-------------------|-----------------------|--------------------------------------------------|
| ANSI Viewer       | ansi, classic, audio  | Scrolling CP437 art with CRT phosphor shader     |
| Audio Spectrum    | audio, visualizer     | FFT bars + oscilloscope (mode 0/1/2)             |
| Copper Bars       | classic, audio        | Amiga-style oscillating colour bars              |
| Fire              | classic               | Cellular-automaton fire with palette             |
| Fractal Zoom      | futuristic, audio     | Mandelbrot deep zoom with beat-burst             |
| Metaballs         | futuristic, audio     | GLSL SDF metaball field                          |
| Particle Storm    | futuristic, audio     | 100k GPU particles, curl noise, transform feedback |
| Plasma            | classic, audio        | Sin/cos colour-field with palette drift          |
| Raymarcher        | futuristic, audio, 3d | SDF scene: torus, spheres, morphing box          |
| Sine Scroller     | classic, audio        | Multi-sine bouncing text with rainbow colours    |
| Starfield         | classic, audio        | 3-D warp-speed star tunnel                       |
| Tunnel            | classic, audio        | Texture-mapped rotating tunnel with depth scroll |

---

## Troubleshooting

### Black window on Wayland

```bash
SDL_VIDEODRIVER=x11 python -m unicornviz
```

### No audio reactivity

1. Check that your system is playing audio.
2. Run the device query above to verify a monitor source exists.
3. Set `device` in config.toml to a substring of the monitor name.

### MIDI not working

1. Verify `python-rtmidi` is installed: `.venv/bin/pip show python-rtmidi`
2. Check `dmesg` or `aconnect -l` for your device.
3. Set `device` to a substring of the port name shown by `aconnect -l`.

### Low frame rate

- Reduce `[window] width/height` to 1280×720.
- The Raymarcher and Particle Storm are heavy; skip them via `[playlist] sequence`.
- Reduce `Fractal Zoom` max_iter: `[effects.FractalZoom] max_iter = 80`.

### Screenshot is blank / upside-down

This is a known cosmetic issue with some GL drivers; the image is flipped
during save so it should appear correct.  If it is blank, your driver may not
support `ctx.screen.read()` — file an issue with your GPU and driver version.
