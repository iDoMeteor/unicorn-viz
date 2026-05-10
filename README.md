# Unicorn Viz

A fullscreen OpenGL 3.3 demoscene visualizer written in Python 3.11+, designed for Linux (Wayland-first, X11 fallback). Renders audio-reactive effects, classic CP437 ANSI art, live audio input capture via PipeWire/ALSA, and MIDI control.

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
# Install Python 3.11+ and ffmpeg (winget)
winget install -e --id Python.Python.3.11
winget install -e --id Gyan.FFmpeg

# Clone and set up
git clone https://github.com/iDoMeteor/unicorn-viz
cd unicorn-viz
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip wheel
.\.venv\Scripts\python -m pip install -r requirements.txt

# Run
.\.venv\Scripts\python -m unicornviz

# CLI help
.\.venv\Scripts\python -m unicornviz --help
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
| `N` / Right arrow | Next effect |
| `P` / Left arrow  | Previous effect |
| `1-9`, `!@#$%^&*(` | Jump to effect |
| `,` | ANSI art |
| `.` | ACiD art |
| `Space` | Pause/resume |
| `F` | Fullscreen |
| `T` | Toggle auto-advance |
| `U` | Show splash anytime |
| `H` | Help overlay |
| `S` | Screenshot |
| `ESC` | Quit |

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

**Geometric:**
Copper Bars, Raymarcher, 3D Vector Field, 3D Cube

**Procedural:**
Fire, Water, Plasma, Noise, Perlin

**Reactive:**
EQ Visualizer, Spectrum Analyzer, Matrix Rain, Waveform

**Themed:**
Alien, Cosmos, Van Gogh, Escher, Dali

**Other:**
ANSI Viewer (CP437 art), Tunnel, Checkerboard, Solid Color

See [User Guide § Effects Reference](docs/user-guide.md#effects-reference) for descriptions and parameters.

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
