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
opencv-python-headless >= 4.9  (camera overlay)
python-rtmidi >= 1.5           (optional — MIDI control)
Pillow                         (screenshots)
```

---

## Installation

```bash
git clone https://github.com/yourname/unicorn-viz
cd unicorn-viz
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Windows 11

```powershell
git clone https://github.com/iDoMeteor/unicorn-viz
cd unicorn-viz
tools\install_windows.bat
```

Run:

```powershell
.\.venv\Scripts\python -m unicornviz
```

The installer accepts any installed Python 3.11+ interpreter; it no longer
depends on the exact `Python 3.11` launcher entry being present.

If `.ps1` files open in an editor on your machine, use the `.bat` wrapper.
It launches the installer through PowerShell and keeps the window open so you
can see failures instead of having the console vanish.

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
	--display-index 1 \
	--reactivity 2.0 \
	--audio-device spotify \
	--log-level DEBUG
```

On multi-monitor setups, use `--display-index N` or `[window].display_index` in
`config.toml` to target a specific SDL display for startup and fullscreen.

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
| `I`               | Toggle invert colours                                         |
| `[` / `]`         | Reactivity −/+                                               |
| `{` / `}`         | Reactivity MIN / MAX                                          |
| `G`               | Reset reactivity to default                                   |
| `Shift+G`         | Reset current effect speed to default                         |
| `+` / `=`         | Speed up current effect (×1.25)                               |
| `-`               | Slow down current effect (×0.8)                               |
| `Ctrl++`          | Speed to MAX                                                  |
| `Ctrl+-`          | Speed to MIN                                                  |
| `E`               | Jump directly to Audio Spectrum / EQ                          |
| `V`               | Toggle video recording on / off                               |
| `Tab`             | Toggle Legacy HUD panel                                       |
| `H`               | Toggle help panel                                             |
| `A`               | Audio device selector                                         |
| `M`               | MIDI device selector                                          |
| `S`               | Save screenshot (`screenshots/unicornviz_YYYYMMDD_HHMMSS.png`)|
| `Esc`             | Quit                                                          |

### Camera / Webcam Controls (Numpad)

These controls only take effect while the **Webcam Overlay** drop-in effect is active.

| Key         | Action                           |
|-------------|----------------------------------|
| `KP 7/8/9`  | PiP to top row                   |
| `KP 4/5/6`  | PiP to middle row                |
| `KP 1/2/3`  | PiP to bottom row                |
| `KP 0`      | Camera fullscreen                |
| `KP .`      | Hide camera                      |
| `KP -`      | Shrink PiP                       |
| `KP +`      | Grow PiP                         |
| `KP /`      | Previous webcam effect           |
| `KP *`      | Next webcam effect               |
| `KP Enter`  | Toggle webcam effect auto-cycle  |
| `E`               | Jump directly to Audio Spectrum / EQ                          |
| `V`               | Toggle video recording on / off                               |
| `Tab`             | Toggle Legacy HUD panel                                       |
| `H`               | Toggle help panel                                             |
| `A`               | Audio device selector                                         |
| `M`               | MIDI device selector                                          |
| `S`               | Save screenshot (`screenshots/unicornviz_YYYYMMDD_HHMMSS.png`)|
| `Esc`             | Quit                                                          |

---

## Multi-Monitor

Unicorn Viz currently supports three display layout modes:

- `single`: render on one selected display
- `span_all`: spread one large window across all detected displays
- `mirror_all`: show the main output on the selected display and mirror it to the others

Use `window.display_index` to choose the targeted display, and `window.display_mode`
to select the layout mode.

---

## Recording

Unicorn Viz can record the final on-screen output to MP4 using `ffmpeg`.

Defaults:
- recordings are saved under `recordings/`
- auto-record is off by default
- audio capture is off by default

When enabled, recording captures:
- effects
- transitions
- invert pass
- standard overlays that are visible before frame capture

Audio recording:
- on Linux/PipeWire, set `capture_audio = true` under `[recording]`
- if no audio source is specified, Unicorn Viz records from the default sink monitor so desktop playback is captured instead of the default microphone

Live recording indicator:
- when the name overlay is visible, a small red recording dot and elapsed timer are shown live on screen
- that dot is not included in saved recordings

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

### Built-in Effects

| Effect            | Class               | Tags                           | Description                                          |
|-------------------|---------------------|--------------------------------|------------------------------------------------------|
| ANSI Viewer       | `ANSIViewer`        | ansi, classic, audio           | Scrolling CP437 BBS art with CRT phosphor shader     |
| Audio Spectrum    | `AudioSpectrum`     | audio, visualizer              | FFT bars + oscilloscope (mode 0/1/2), key `E`        |
| Copper Bars       | `CopperBars`        | classic, amiga, audio          | Amiga-style oscillating colour bars                  |
| Cosmos            | `Cosmos`            | space, audio                   | Deep-space nebula and stellar drift                  |
| Crystal Pyramids  | `CrystalPyramids`   | futuristic, audio, crystal     | Audio-reactive crystalline pyramids                  |
| 3D Cube           | `Cube3D`            | classic, 3d, audio             | Rotating wireframe cube                              |
| Curtains          | `Curtains`          | classic, audio                 | Multi-colour oscillating curtain waves               |
| Dali              | `Dali`              | art, surreal, audio            | Melting-clock surrealist scene                       |
| Escher            | `Escher`            | art, optical, audio            | Impossible architecture tile shader                  |
| Fire              | `Fire`              | classic, audio                 | Cellular-automaton lifelike flame                    |
| Fractal Zoom      | `FractalZoom`       | futuristic, audio              | Deep Mandelbrot zoom with beat-burst                 |
| Metaballs         | `Metaballs`         | futuristic, audio              | GLSL SDF metaball field                              |
| Particle Storm    | `ParticleStorm`     | futuristic, particles, audio   | 100k GPU particles, curl noise, transform feedback   |
| Plasma            | `Plasma`            | classic, audio                 | Sin/cos colour-field with palette drift              |
| Raymarcher        | `Raymarcher`        | futuristic, audio, 3d          | SDF scene with torus, spheres, morphing geometry     |
| Sine Scroller 2.0 | `SineScroller`      | classic, audio                 | Multi-sine bouncing text with rainbow colours        |
| Starfield         | `Starfield`         | classic, audio                 | 3D warp-speed star tunnel                            |
| System Monitor    | `SystemMonitor`     | diagnostic, hud, system        | Live CPU/RAM/GPU/audio performance graphs            |
| Tunnel            | `Tunnel`            | classic, audio                 | Texture-mapped rotating tunnel with depth scroll     |
| Van Gogh          | `VanGogh`           | art, audio                     | Post-impressionist flowing brush-stroke field        |
| Vector            | `Vector`            | futuristic, audio, 3d          | 3D vector-field flow simulation                      |
| Water             | `Water`             | simulation, audio, gpu         | Procedural ripple-wave surface                       |
| Wavey Gravy       | `WaveyGravy`        | psychedelic, audio             | Psychedelic waving sine-noise field                  |

### Drop-in Effects

| Effect            | Class              | Key | Tags                         | Description                                       |
|-------------------|--------------------|-----|------------------------------|---------------------------------------------------|
| Alien Invasion    | `AlienInvasion`    | —   | scifi, audio, cosmic         | UFO fleets + atmospheric probing beams            |
| Cyber War         | `CyberWar`         | —   | cyberpunk, audio, network    | Digital hex-grid battle-map                       |
| Disco Ball        | `DiscoBall`        | —   | disco, raymarching, audio    | Raymarched mirror-tile ball with spot beams       |
| Hacker Terminal   | `HackerTerminal`   | —   | cyberpunk, audio, glitch     | Animated shell/log streams with glitch transitions|
| Texture Showcase  | `TextureShowcase`  | —   | textures, audio              | Ken Burns image montage with audio colour grade   |
| Tron Grid         | `TronGrid`         | —   | tron, laser, raymarching     | First-person neon laser grid with shockwaves      |
| Unicorn Tears     | `UnicornTears`     | `U` | psychedelic, audio           | Prismatic teardrops through a deep star-field     |
| Webcam System     | `WebcamSystem`     | keypad | System-wide camera PiP with switchable treatments | 
| Image Showcase    | `ImageShowcase`    | —   | images, audio, slideshow     | Audio-reactive still-image slideshow              |
| Webcam Overlay    | `WebcamOverlay`    | —   | webcam, overlay, camera      | Live camera feed with animated background          |

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

### Camera / Webcam not working

1. The Webcam Overlay is a **drop-in effect** — navigate to it in the playlist.
2. Check device index in `[effects.WebcamOverlay] camera_device = 0`; try `1`, `2` if needed.
3. Close any app holding the camera (Cheese, OBS) — the drop-in retries automatically every 3 s.
4. Run with `--log-level DEBUG` to see V4L2 open/read details.

### Screenshot is blank / upside-down

This is a known cosmetic issue with some GL drivers; the image is flipped
during save so it should appear correct.  If it is blank, your driver may not
support `ctx.screen.read()` — file an issue with your GPU and driver version.
