# Unicorn Viz

A fullscreen OpenGL 3.3 demoscene visualizer written in Python 3.11+, designed for Linux (Wayland-first, X11 fallback). Renders audio-reactive effects, classic CP437 ANSI art, live audio input capture via PipeWire/ALSA, and MIDI control.

## Repository Notice

- Primary and stable repository: https://github.com/djunicorntears/unicorn-viz
- Development and unstable repository: https://github.com/idometeor/unicorn-viz (developers only)

## Demo Video

<iframe
  src="https://rumble.com/embed/v79jc7e"
  title="Unicorn Viz Beta Demo"
  width="100%"
  height="480"
  frameborder="0"
  allowfullscreen>
</iframe>

If the embed does not render in your Markdown viewer, watch it here:
https://rumble.com/v79jc7e-unicorn-viz-beta-made-by-me.html

**Perfect for:** live music performances, streaming/recording with OBS, BBS nostalgia, synth/electronic art.

---

## Quick Start

### Install on Fedora

```bash
# Install system dependencies
sudo dnf install -y python3.11 python3.11-pip python3.11-devel \
  SDL2-devel opengl-devel libffi-devel \
  pipewire-devel alsa-lib-devel

# Clone and set up
git clone https://github.com/iDoMeteor/unicorn-viz
cd unicorn-viz
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip wheel
.venv/bin/pip install -r requirements.txt

# Run
./run.sh

# CLI help
.venv/bin/python -m unicornviz --help
```

### Install on Ubuntu 22.04+

```bash
# Install system dependencies
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev \
  libsdl2-dev libgl1-mesa-dev libffi-dev \
  libpipewire-0.3-dev libasound2-dev

# Clone and set up
git clone https://github.com/iDoMeteor/unicorn-viz
cd unicorn-viz
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip wheel
.venv/bin/pip install -r requirements.txt

# Run
./run.sh

# CLI help
.venv/bin/python -m unicornviz --help
```

### Install on Windows 11 (Preview)

```powershell
git clone https://github.com/iDoMeteor/unicorn-viz
cd unicorn-viz

# Automated installer (Python + ffmpeg + venv + pip deps)
powershell -ExecutionPolicy Bypass -File .\tools\install_windows.ps1

# Run
.\.venv\Scripts\python -m unicornviz

# CLI help
.\.venv\Scripts\python -m unicornviz --help
```

Installer options:

```powershell
# Skip ffmpeg install
powershell -ExecutionPolicy Bypass -File .\tools\install_windows.ps1 -SkipFfmpeg

# Skip package manager installs (Python/ffmpeg must already exist)
powershell -ExecutionPolicy Bypass -File .\tools\install_windows.ps1 -SkipPackageManagers
```

### Common CLI Overrides

```bash
.venv/bin/python -m unicornviz \
  --windowed \
  --width 2560 --height 1440 \
  --mode random \
  --transition shuffle \
  --effect-duration 30 \
  --reactivity 2.5 \
  --audio-device spotify \
  --log-level DEBUG
```

---

## Features

- **Audio-reactive effects** — 20+ GPU-accelerated shaders responding to bass/mid/treble
- **Live capture** — PipeWire/ALSA monitor input, FFT analysis, beat detection
- **ANSI art viewer** — CP437 BBS art + downloaded ACiD pack
- **MIDI control** — CC parameters, note-to-action mapping
- **Splash screen** — music-reactive animated splash with integrity check
- **Fullscreen + multi-monitor** — Wayland-native, X11 fallback
- **OBS integration** — designed for live streaming

---

## Quick Controls

| Key      | Action                    |
|----------|---------------------------|
| `N` / `→` | Next effect |
| `P` / `←` | Previous effect |
| `1`–`9`, `Shift+1`–`0`, `Ctrl+1`–`0` | Jump to effect |
| `,` / `.` | ANSI own / ACiD art |
| `Space` | Pause / resume |
| `F` | Fullscreen |
| `T` | Toggle auto-advance |
| `I` | Invert colours |
| `V` | Toggle recording |
| `S` | Screenshot |
| `U` | Unicorn Tears |
| `Shift+U` | Replay splash |
| `Tab` | Legacy HUD panel |
| `H` | Help overlay |
| `ESC` | Quit |
| `KP 1`–`9` | Camera PiP position |
| `KP 0` / `KP .` | Camera fullscreen / hide |
| `KP -` / `+` | Camera PiP size |
| `KP /` / `*` | Webcam effect prev / next |
| `KP Enter` | Webcam effect auto-cycle |

See [User Guide](docs/user-guide.md#keyboard-shortcuts) for full hotkey list.

---

## Documentation

- **[User Guide](docs/user-guide.md)** — Installation, running, keyboard/MIDI controls, audio setup, effects reference, troubleshooting
- **[Configuration Reference](docs/configuration.md)** — All `config.toml` settings
- **[Effect Settings Reference](docs/effect-settings.md)** — Every effect's tweakable config variables
- **[Developer Guide](docs/developer-guide.md)** — Architecture, effects API, GLSL conventions, contributing

---

## Project Layout

```
unicorn-viz/
├── unicornviz/           # Main package
│   ├── effects/          # 20+ visual effects (auto-discovered)
│   ├── audio/            # Audio capture + FFT + beat detection
│   ├── ansi/             # ANSI art parser + CP437 font
│   ├── app.py            # Main loop + SDL2/moderngl
│   ├── config.py         # Config loader
│   ├── hotkeys.py        # Keyboard + MIDI dispatch
│   ├── midi.py           # MIDI input
│   ├── overlays.py       # HUD rendering
│   ├── playlist.py       # Effect sequencer
│   └── splash.py         # Animated splash screen
├── assets/
│   └── ansi/             # BBS art (generated + ACiD pack)
├── docs/                 # Documentation
├── tools/                # Standalone utilities
├── config.toml           # Runtime configuration
├── requirements.txt      # Python dependencies
└── run.sh                # Launch script

```

---

## Requirements

| Dependency      | Minimum | Purpose                          |
|-----------------|---------|----------------------------------|
| Python          | 3.11    | `tomllib` standard library       |
| SDL2            | 2.0.18  | Window & input                   |
| OpenGL          | 3.3     | GPU rendering                    |
| PipeWire/ALSA   | any     | Audio loopback capture           |

Python packages:
- `moderngl >= 5.11` — OpenGL wrapper
- `pysdl2`, `pysdl2-dll` — SDL2 bindings
- `numpy`, `scipy` — Numerics & signal processing
- `sounddevice >= 0.4` — Audio I/O
- `opencv-python-headless >= 4.9` — Camera overlay
- `python-rtmidi >= 1.5` (optional) — MIDI control
- `Pillow` — Screenshots

---

## Configuration

Create a custom `config.toml` or edit the default one:

```toml
[window]
fullscreen = false
width = 1920
height = 1080

[demo]
effect_duration = 20        # auto-advance every 20 seconds
mode = "sequential"         # or "random"

[audio]
device = ""                 # "" = auto-detect (Spotify > default)
reactivity = 1.0            # 0.5x to 5.0x audio sensitivity
```

See [Configuration Reference](docs/configuration.md) for all options.

For a fully documented, exhaustive template including all effect overrides, see:

- `config.full.example.toml`

## Logging

Runtime logs are written to `logs/` automatically, with one timestamped file per run.

You can control verbosity from config or CLI:

```bash
.venv/bin/python -m unicornviz --log-level DEBUG
```

## Platform / Packaging Tooling

- Linux installer script (distro-aware):
  - `./tools/install_linux.sh`
- Containerized compatibility matrix (Ubuntu/Debian/Fedora):
  - `./tools/compat_matrix.sh`
- CI workflow for the matrix:
  - `.github/workflows/compat-matrix.yml`
- Packaging evaluation artifacts:
  - `packaging/flatpak/io.unicornviz.UnicornViz.yml`
  - `packaging/snap/snapcraft.yaml`

---

## Audio Setup

Unicorn Viz automatically detects and prioritizes audio sources:

1. **Spotify** (if running) — native app audio
2. **Firefox/Chrome** — web audio (YouTube, web radio, etc.)
3. **System default** — fallback if no app sources available

On **PipeWire**: audio sources are captured via monitor sinks. On **ALSA**: loopback setup required.

For OBS streaming: the app will capture Spotify/Firefox/system audio, **not** OBS's own monitor feed — this prevents feedback loops.

See [User Guide § Audio Setup](docs/user-guide.md#audio-setup) for detailed troubleshooting.

---

## Effects Catalog

**Built-in effects (auto-discovered from `unicornviz/effects/`):**

| Effect | Tags | Description |
|--------|------|-------------|
| ANSI Viewer | ansi, classic | Scrolling CP437 art with CRT phosphor shader |
| Audio Spectrum | audio, visualizer | FFT bars + oscilloscope (3 modes) |
| Copper Bars | classic, audio | Amiga-style oscillating colour bars |
| Cosmos | space, audio | Deep-space nebula and stellar drift |
| Crystal Pyramids | futuristic, audio | Audio-reactive crystalline geometry |
| 3D Cube | classic, 3d | Rotating wireframe cube |
| Curtains | classic, audio | Multi-colour sine-wave curtain effect |
| Dali | art, surreal | Melting-clock surrealist scene |
| Escher | art, optical | Impossible architecture tile shader |
| Fire | classic, audio | Cellular-automaton lifelike flame |
| Fractal Zoom | futuristic, audio | Deep Mandelbrot zoom with beat-burst |
| Metaballs | futuristic, audio | GLSL SDF metaball field |
| Particle Storm | futuristic, particles | 100 k GPU particles with curl noise |
| Plasma | classic, audio | Sin/cos colour-field with palette drift |
| Raymarcher | futuristic, 3d | SDF scene: torus, spheres, morphing geometry |
| Sine Scroller 2.0 | classic, audio | Multi-sine bouncing text with rainbow colours |
| Starfield | classic, audio | 3D warp-speed star tunnel |
| System Monitor | diagnostic, hud | Live CPU/RAM/GPU + audio graphs |
| Tunnel | classic, audio | Texture-mapped rotating tunnel |
| Van Gogh | art, audio | Post-impressionist flowing brush-stroke field |
| Vector | futuristic, audio | 3D vector-field flow simulation |
| Water | simulation, audio | Procedural ripple surface |
| Wavey Gravy | psychedelic, audio | Psychedelic waving sine-noise field |

**Drop-in effects (`drop-ins/`):**

| Effect | Key | Description |
|--------|-----|-------------|
| Alien Invasion | — | UFO fleets + atmospheric probing beams |
| Cyber War | — | Digital battle-map with hex-grid node attacks |
| Disco Ball | — | Raymarched mirror-tile ball with spot beams |
| Hacker Terminal | — | Animated shell/log streams with glitch transitions |
| Texture Showcase | — | Ken Burns image montage with audio colour grade |
| Tron Grid | — | First-person laser-grid corridor with shockwaves |
| Unicorn Tears | `U` | Prismatic teardrops through a star-field |
| Webcam System | KP controls | System-wide camera PiP with switchable treatments |
| Image Showcase | — | Audio-reactive still-image slideshow |
| Webcam Overlay | — | Live camera feed with animated background |

**Subsystem drop-ins:**

| Drop-in | Purpose |
|---------|---------|
| multi-head-01 | Multi-monitor display controller (single / span / mirror) |

---

## Troubleshooting

**Black screen?**
- Check OpenGL version: `glxinfo | grep "OpenGL version"`
- Try X11: `SDL_VIDEODRIVER=x11 ./run.sh`

**No audio?**
- Check devices: `python3 -c "import sounddevice as sd; print([d['name'] for d in sd.query_devices()])"`
- Check PipeWire: `pw-dump | grep "monitor"`

**Crash on startup?**
- Ensure Python 3.11+: `python3 --version`
- Verify virtualenv: `.venv/bin/python --version`

See [User Guide § Troubleshooting](docs/user-guide.md#troubleshooting) for more.

---

## Development

To write a new effect:

1. Create `unicornviz/effects/my_effect.py`
2. Subclass `BaseEffect`, set `NAME = "My Effect"`
3. Implement `_init()`, `update()`, `render()`, `destroy()`
4. It's auto-discovered at runtime

See [Developer Guide § Writing a New Effect](docs/developer-guide.md#writing-a-new-effect).

---

## License

MIT (see LICENSE if present in repo).

---

## Contact & Contributing

Issues and PRs welcome. See [Developer Guide § Contributing](docs/developer-guide.md) for code standards.

---

**Happy demoscene visualizing!** 🦄✨
