# Unicorn Viz

## Press `H` or `?` for Help

If you're running a live stream or recorded set with Unicorn Viz and upload it
somewhere, let us know and we'll repost it.

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
# Double-click tools\install_windows.bat from Explorer, or run this from PowerShell.
tools\install_windows.bat

# GUI installer (avatar icon + live log panel)
powershell -ExecutionPolicy Bypass -File .\tools\install_windows_gui.ps1

# Any installed Python 3.11+ interpreter is fine; the installer will pick it up
# even if the exact "Python 3.11" launcher entry is missing.

# Run
.\.venv\Scripts\python -m unicornviz

# GUI launcher (avatar icon)
tools\launchers\windows\UnicornVizGUI.bat

# CLI help
.\.venv\Scripts\python -m unicornviz --help
```

Installer options:

```powershell
# Skip ffmpeg install
powershell -ExecutionPolicy Bypass -File .\tools\install_windows.ps1 -SkipFfmpeg

# Skip package manager installs (Python/ffmpeg must already exist)
powershell -ExecutionPolicy Bypass -File .\tools\install_windows.ps1 -SkipPackageManagers

# Force CLI installer mode via batch wrapper (default is GUI)
tools\install_windows.bat --cli
```

If double-clicking the `.ps1` file opens it in an editor, use `tools\install_windows.bat` instead. It launches PowerShell with the correct execution policy and keeps the console open at the end.

Native installer packaging (Inno Setup):

```powershell
# From Windows with Inno Setup installed (ISCC on PATH)
ISCC.exe .\packaging\windows\UnicornViz.iss
```

This produces `packaging\windows\UnicornVizInstaller.exe` with avatar icon,
Start Menu/Desktop shortcuts, and a post-install prompt to run dependency setup.

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

### Visual Effects
- **20+ built-in GPU-accelerated shaders** — classic (plasma, fire, tunnel, starfield), surreal (dali, escher), 3D (raymarcher, cube, metaballs), particle-based (particle storm), text (sine scroller 2.0), and more
- **14 drop-in effects** (tested and working; currently private repositories) — alien invasion, cyber war, disco ball, hacker terminal, texture showcase, tron grid, unicorn tears, webcam overlay, and more
- **Audio reactivity** — all effects respond to bass/mid/treble/beat in real time via FFT analysis
- **Effect startup randomization** — every effect produces a visually distinct appearance each activation; parameters like palette, speed, intensity, zoom vary automatically to prevent repetition

### Audio & Visualization
- **Live audio capture** — PipeWire/ALSA monitor input with automatic source priority (Spotify > Firefox > system)
- **Real-time FFT + beat intelligence** — profile-aware onset weighting, adaptive MAD thresholding, ACF tempo lane scoring with BPM priors, phase-lock confidence tracking, and drop/build energy slope analysis for musically coherent automation
- **Per-effect audio reactivity override** — constrain or amplify responsiveness per effect via config

### Auto VJ Intelligence
- **Sophisticated beat reasoning** — not just onset triggers; Auto VJ continuously fuses BPM lock confidence, phase/downbeat coherence, energy slope, and drop scoring to decide when to build, impact, and climax
- **Context-aware automation** — profile-specific behavior (Chill/Normie/Raver), cooldown governance, and tag-aware effect selection keep transitions intentional instead of random thrash
- **Continuous control surfaces** — post-FX hue shift and rotation are handled like knobs with incremental slew behavior for smoother, performance-friendly motion

### Interactive Controls & Automation
- **Keyboard shortcuts** — effect navigation, pause/resume, fullscreen, recording, and 40+ more commands
- **MIDI support** (optional) — CC parameter mapping, note-to-action binding, dynamic CC→parameter routing
- **Randomization toggles** with armed state — F6/F7/Alt+Z globally randomize speed/reactivity/zoom; armed modes persist across effects even when unsupported, with per-effect override ranges
- **Effect-local parameter overrides** — define custom min/max bounds for randomization, speed, zoom, and reactivity per effect in config
- **Splash screen** — music-reactive animated splash with integrity check

### Display & Streaming
- **ANSI art viewer** — CP437 BBS art rendering with CRT phosphor shader; cycle between personal & downloaded ACiD pack
- **Fullscreen + multi-monitor** — Wayland-native, X11 fallback; single/span/mirror display modes
- **OBS streaming integration** — designed for live capture (24/7 recording, RTMP streaming, scene recording)
- **Webcam overlay** — system-wide camera PiP with 5+ visual treatments, switchable via hotkeys or MIDI
- **Screenshot & screen recording** — direct PNG capture and per-session video recording with codec options

### Customization & Performance
- **Window cursor control** — hide by default (show with Ctrl) or keep visible via config flag
- **Internal render scale** — reduce from 1.0x for performance headroom on heavy shaders; adjust manually with comma/period
- **Per-effect config overrides** — speed, intensity, amplitude, zoom, parameters tuned per effect or globally
- **Fullscreen mode selection** — standard, borderless, or exclusive fullscreen via config

### Developer & Artisan Features
- **Auto-discovered effects** — drop `.py` files in `unicornviz/effects/` or `drop-ins/*/`; they load at startup
- **Drop-in architecture** — submodule-based private drop-ins with independent repositories; core remains decoupled
- **Effect randomization requirements** — built-in per-instance RNG with automatic startup randomization for all visual parameters
- **GLSL 3.3+ shaders** — moderngl 5.x bindings, SDF helpers, palette functions, transform feedback for procedural geometry
- **Configuration-driven workflow** — exhaustive `config.full.example.toml` template documents all effect parameters, hotkey ranges, audio settings

---

## Quick Controls

| Key      | Action                    |
|----------|---------------------------|
| `N` / `→` | Next effect |
| `P` / `←` | Previous effect |
| `1`–`9`, `Shift+1`–`0`, `Ctrl+1`–`0` | Jump to effect |
| `u` / `U` / `Ctrl+U` | Splash / Unicorn Tears / screen burst |
| `a` / `Shift+A` / `Ctrl+A` | ACiD art / ANSI art / audio source |
| `,` / `.` / `<` / `>` | Res scale down / up / MIN / MAX |
| `Ctrl+,` / `Ctrl+.` | Res scale reset |
| `Space` | Pause / resume |
| `F` | Fullscreen |
| `T` | Toggle auto-advance |
| `I` | Invert colours |
| `V` | Toggle recording |
| `S` | Screenshot |
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

- **[Documentation Index](docs/README.md)** — Canonical map of all project docs, ownership, and maintenance workflow
- **[User Guide](docs/user-guide.md)** — Installation, running, keyboard/MIDI controls, audio setup, effects reference, troubleshooting
- **[Configuration Reference](docs/configuration.md)** — All `config.toml` settings
- **[Effect Settings Reference](docs/effect-settings.md)** — Every effect's tweakable config variables
- **[Developer Guide](docs/developer-guide.md)** — Architecture, effects API, GLSL conventions, contributing
- **[Drop-in Documentation Registry](docs/drop-ins.md)** — Per-drop-in docs coverage and deep-dive links

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

### Minimum Recommended (validated baseline)

The following machine is the current baseline used for pre-release testing.
For stable live use, target equivalent or better specs.

| Component | Minimum Recommended |
|---|---|
| OS | Fedora Linux 37 (or equivalent modern Linux distro) |
| Kernel | Linux 6.5.x |
| CPU | Intel Core i7-8809G class CPU (4 cores / 8 threads) |
| RAM | 32 GB system memory |
| GPU | AMD Radeon RX Vega M GH class GPU |
| VRAM | 4 GB dedicated video memory |
| OpenGL | OpenGL 4.6 core profile (Mesa 23.x or newer) |

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

**Drop-in Effects (tested and working; currently private repositories):**

| Effect | Hotkey | Description |
|--------|--------|-------------||
| Alien Invasion (`alien-invasion-01`) | — | UFO fleets descend with probing beams; audio-reactive formation density and radar sweep |
| Cyber War (`cyber-war-01`) | — | Hex-grid digital battlefield with AI node attacks and pulsing defense networks |
| Disco Ball (`disco-ball-01`) | — | Raymarched mirror-tile ball with 3 rotating coloured spot beams and reflective floor |
| Hacker Terminal (`hacker-terminal-01`) | — | Animated shell/log streams with glitch transitions and text-scroll reactivity |
| Texture Showcase (`textures-01`) | — | Ken Burns image pan/zoom with audio-reactive colour grade and beat-triggered fade |
| Prism Storm (`textures-01`) | — | Spinning crystal core with refractive laser beams and electric haze (same drop-in as Texture Showcase) |
| Tron Grid (`tron-grid-01`) | — | First-person laser-grid corridor; bass scales grid size, beats trigger shockwaves |
| Unicorn Tears (`unicorn-tears-01`) | `U` | Prismatic teardrops falling through a star-field with audio-reactive burst |
| Image Showcase (`images-01`) | — | Configurable image directory with Ken Burns motion, 10 presentation styles, audio colour shift |
| Video Showcase (`videos-01`) | — | Video clip sequencer with smooth crossfade, configurable clip directories |
| Webcam Overlay (`webcam-01`) | `KP 0`, `KP .`, `KP -/+` | System-wide camera PiP with 5+ visual treatments (threshold, edge detect, emboss, etc.) |
| WebcamOverlay (playlist effect) (`webcam-01`) | — | Full-playlist camera effect with animated multi-colour background |
| ProjectM Presets (`projectm-01`) | `Ctrl+N/P/R` | libprojectM Milkdrop preset sequencer with 1000+ community presets and smooth transitions |
| SimShowcase (`sims-01`) | — | USD scene carousel with camera orbits; load robotics training datasets or galaxy fallback |

**Multi-head & System Drop-ins:**

| Drop-in | Purpose |
|---------|----------|
| `multi-head-01` | Multi-monitor display controller (single / span / mirror modes) |
| `streaming-01` | RTMP streaming controller (when available) |

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
