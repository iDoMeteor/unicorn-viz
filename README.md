# Unicorn Viz

**Version 1.0.0-beta.18**

## Contact Me!

If you are using UV, please contact me asap!  This repo is going to move.
DJUnicornTears on X/Gmail.

## Press `H` or `?` for Help

If you're running a live stream or recorded set with Unicorn Viz and upload it
somewhere, let us know and we'll repost it.

A fullscreen OpenGL 3.3 demoscene visualizer written in Python 3.11+, designed for Linux (Wayland-first, X11 fallback). Renders audio-reactive effects, classic CP437 ANSI art, live audio input capture via PipeWire/ALSA, and MIDI control.

## Contact Me

If you are using UV, please contact me!  djunicorntears on X/Gmail.

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
- **43 audio-reactive GPU effects** — a lean audio-analysis core (spectrum, spectrogram, waveforms, centroid) plus themed **category packs**: psychedelic (plasma, kaleidoscope), retro (copper bars, ANSI viewer, fractal zoom, dali, escher, van gogh), particles (starfield, fireworks, particle storm), vector (3D cube, vector, disco ball), cosmic (cosmos, black hole cathedral, alien invasion), tech (tron grid, cyber war, hacker terminal), immersive (tunnel, wormhole, cathedral of bass), and more
- **Standalone drop-in effects** — image / video / texture showcases, USD sim showcase, ProjectM Milkdrop preset host, unicorn tears; plus a system-wide webcam overlay (all tested and working; currently private repositories)
- **Audio reactivity** — all effects respond to bass/mid/treble/beat in real time via FFT analysis
- **Effect startup randomization** — every effect produces a visually distinct appearance each activation; parameters like palette, speed, intensity, zoom vary automatically to prevent repetition

### Audio & Visualization
- **Live audio capture** — startup prefers the current system default input, with fast in-app source switching when needed (`Ctrl+Shift+A`)
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
device = ""                 # "" = no hint; start on system default input
prefer_default_input = true  # startup source policy when device=""
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

Unicorn Viz startup source selection works like this:

1. **System default input first** — safest startup behavior for mixed live rigs
2. **Automatic fallback candidates** — tried only when the active source stays silent
3. **Manual override anytime** — open the source selector (`Ctrl+Shift+A`) to pick another input

By default, Unicorn Viz starts on **Audio Spectrum** (`[playlist].start_effect = "Audio Spectrum"`) specifically so you can immediately verify that the analyzer is receiving signal before moving into other effects.

On **PipeWire**: audio sources are captured via monitor sinks. On **ALSA**: loopback setup required.

For OBS streaming: the app will capture Spotify/Firefox/system audio, **not** OBS's own monitor feed — this prevents feedback loops.

See [User Guide § Audio Setup](docs/user-guide.md#audio-setup) for detailed troubleshooting.

---

## Effects Catalog

All effects are auto-discovered and audio-reactive. Audio analyzers live in the
core package; every other visual lives in a themed **category pack** (its own
private repo, wired in as a submodule). Each effect carries a canonical category
tag as its first tag. Key bindings are **not** listed here — press `H` in-app for
the live hotkey overlay (the single source of truth). See
[docs/drop-ins.md](docs/drop-ins.md) for the full drop-in registry.

**Core — audio analyzers (`unicornviz/effects/`):**

| Effect | Tags | Description |
|--------|------|-------------|
| Audio Spectrum | analyzer, visualizer | FFT frequency bars + oscilloscope waveform |
| Audio Spectrogram | analyzer, visualizer, spectrogram | Reactive scrolling frequency-history heatmap |
| Audio Tracks | analyzer, visualizer, timeline | DAW-style horizontal scrolling track lanes |
| Audio Waveforms | analyzer, visualizer, oscilloscope | Multi-style oscilloscope visualizer |
| Audio Centroid | analyzer, spectrum, reactive | Spectral-brightness (centroid) visualizer |
| Audio Sine | analyzer, neon, lasers | Textless neon wave-lasers with crossing squash |

**`psychedelic-01`:**

| Effect | Tags | Description |
|--------|------|-------------|
| Plasma | psychedelic, classic | Classic sin/cos colour-field shader with palette drift |
| Kaleidoscope | psychedelic, classic | View through a rotating optical kaleidoscope |
| Psychedelic | psychedelic, shader | Animated palette-sine neon field |

**`particles-01`:**

| Effect | Tags | Description |
|--------|------|-------------|
| Starfield | particles, classic | Cinematic multi-layer star field with warp-speed mode |
| Fireworks | particles, classic, celebration | Cinematic night-sky pyrotechnic display |
| Particle Storm | particles | GPU transform-feedback particle system |

**`retro-01`:**

| Effect | Tags | Description |
|--------|------|-------------|
| Copper Bars | retro, classic, amiga | Amiga-style horizontal raster/colour bars |
| ANSI Viewer | retro, ansi, classic | Scrolling CP437 `.ANS` art with CRT phosphor shader |
| Fractal Zoom | retro, psychedelic | Deep Mandelbrot voyage with nebula interior shading |
| Escher | retro, art, optical | Impossible-style tiling corridor illusion |
| Dali | retro, art, surreal | Surreal melting forms and mirage-like distortions |
| Van Gogh | retro, art, shader | Painterly swirling night-sky brushstroke field |

**`feature-01`:**

| Effect | Tags | Description |
|--------|------|-------------|
| Hexy Stars | feature, stars, hex | Reactive pulsing hex/octa star field |
| Rainbow Trance | feature, mythic, crystal | Prismatic pyramid field with rainbow sky rays |
| Metaballs | feature, classic | GLSL SDF orbs that attract and repel |

**`vector-01`:**

| Effect | Tags | Description |
|--------|------|-------------|
| 3D Cube | vector, classic, 3d | Solid neon rotating cube with Phong shading |
| Vector | vector, classic, demoscene, 3d | Classic demoscene spinning wireframe polyhedra |
| Disco Ball | vector, disco, raymarching, reflections | Raymarched mirror-tile ball with rotating spot beams |

**`cosmic-01`:**

| Effect | Tags | Description |
|--------|------|-------------|
| Cosmos | cosmic, shader | Nebula clouds with star field and warp streaks |
| Black Hole Cathedral | cosmic, shader, cathedral | Gothic mega-structure orbiting an accretion lens |
| Wavey Gravy | cosmic, sci-fi, shader | Pulsating organic landscape with bioluminescent veins |
| Alien Invasion | cosmic, sci-fi, procedural | UFO fleets descending with atmospheric probing beams |

**`tech-01`:**

| Effect | Tags | Description |
|--------|------|-------------|
| Tron Grid | tech, tron, laser, grid, raymarching, neon, sci-fi | First-person laser-grid corridor; bass scales grid, beats trigger shockwaves |
| Cyber War | tech, network, cyberpunk | Real-time digital battle-map with AI node attacks |
| Hacker Terminal | tech, cyberpunk, glitch | Animated shell/log streams with audio-reactive glitch |
| Hacker Terminal 2.0 | tech, cyberpunk, glitch, text | Real CP437 scrolling text streams with glitch transitions |
| Threat Matrix | tech, cyberpunk, hacker, network, matrix | War-room IDS threat map: sector heat grid, trace-route packets, radar sweep, beat-driven breach waves |

**`immersive-01`:**

| Effect | Tags | Description |
|--------|------|-------------|
| Tunnel | immersive, classic | Fully procedural infinite rotating tunnel |
| Wormhole | immersive, crystal, prism, lattice | Refractive prism-lattice flight down a shifting light corridor |
| Cathedral of Bass | immersive, bass, shader, raver, cathedral | Layered, room-shaking flight down an infinite nave |

**`games-01`:**

| Effect | Tags | Description |
|--------|------|-------------|
| Breakout | games, arcade | Audio-reactive arcade brick-breaker |

**`holiday-01`:**

| Effect | Tags | Description |
|--------|------|-------------|
| America 250 | holiday, america, patriotic, fireworks | Over-the-top bicentennial-plus-50 celebration |

**Standalone effect drop-ins (one effect per repo):**

| Effect | Source | Tags | Description |
|--------|--------|------|-------------|
| Image Showcase | `images-01` | media, images, slideshow | Image directory with Ken Burns motion and multiple presentation styles |
| Video Clips | `video-clips-01` | media, videos, slideshow | Audio-reactive clip montage with per-activation directory-group selection |
| Video Player | `videos-01` | media, videos, player | Plays whole videos with their own audio (ffpyplayer), letterboxed; manual-only |
| Texture Showcase | `textures-01` | media, textures, modern | Ken Burns pan/zoom with reactive colour grade and beat fade |
| Sim Showcase | `sims-01` | media, 3d, usd, simulation | USD scene carousel with camera orbits (robotics/galaxy scenes) |
| ProjectM Presets | `projectm-01` | projectm, milkdrop | libprojectM Milkdrop preset host with 1000+ community presets |
| Unicorn Tears | `unicorn-tears-01` | psychedelic | Prismatic iridescent teardrops falling through a star-field |

**System & overlay drop-ins (not playlist effects):**

| Drop-in | Purpose |
|---------|---------|
| `webcam-01` | System-wide camera PiP overlay with 5+ visual treatments |
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

## Changelog

- **1.0.0-beta.18** — New `synthwave` audio profile (`unicornviz/audio/profiles.py`): warm analog bass, gated-reverb drums, and a bright 1.4-2.4 kHz lead-synth peak at 85-118 BPM, selectable via `Alt+A` like any other genre profile. First-pass, added after a livestream synthwave training session ran under `generic` all night and sagged into psytrance/trance whenever detected BPM ran hot -- see `docs/adr/training-model.md`.
- **1.0.0-beta.17** — Tour polish: the dim scrim now hugs the dialog like
  every other modal (was a floating 60px skirt), and drop-in slides slot in
  alphabetically *before* the core good-bye slide so "Have a great show!"
  always closes the tour.
- **1.0.0-beta.16** — **Fix: a silent audio source collapsed the frame rate.**  The capture auto-fallback probes a candidate device by spawning a Python subprocess (numpy + sounddevice + opening the device, ~200–800 ms), and `maybe_fallback()` runs from the audio manager's **per-frame** update.  Its cooldown was stamped only after a *successful switch*, so when every candidate was silent — the exact case the fallback exists for — the gate never closed and a probe ran **on every frame, inline on the render thread**.  The cooldown is now stamped when a probe is *attempted*, and the probe runs on a worker thread whose result is collected on a later frame, so the render thread is never blocked by it at all.
- **1.0.0-beta.15** — **Shift+Delete** re-activates the last Delete-key
  deactivation (running session only, LIFO): a disabled effect is re-enabled
  and jumped straight back to; a disabled ProjectM preset is re-enabled while
  ProjectM is still active. For when you fat-finger Delete mid-set.
- **1.0.0-beta.14** — Two `VJApi` passthroughs for controller profiles:
  `midi_preset_name()` (read the active preset) and `midi_apply_preset(name)`
  (switch it). Drop-ins cannot reach the MIDI manager directly, so without
  these a drop-in could neither tell which profile is live at startup nor offer
  a profile switcher. See midi-controllers-01 0.9.0.
- **1.0.0-beta.13** — `MidiManager.apply_preset()`: switch the live CC/note maps
  to a different registered preset at runtime without reopening ports. Rebuilds
  through the same layering `__init__` uses, so a switch never silently drops
  the operator's `[midi.cc_map]` / `[midi.note_map]` overrides. This is the core
  half of controller profiles (see midi-controllers-01 0.8.0).
- **1.0.0-beta.12** — MIDI context-slot fix: the presets browser and effects
  browser now have their own context-slot tables, and a slot a context
  deliberately leaves unbound is swallowed instead of falling back to the
  performance bindings. Previously both modals fell through to performance,
  which re-dispatched the performance chord into the open modal — mostly inert,
  but in the effects browser slot 2 landed on `p` (pin/unpin the selected
  effect) and slot 4 on Space (toggle it enabled), so reaching for "move down
  the list" silently re-pinned or disabled an effect. CC→parameter scaling now
  reads one shared `CC_PARAM_RANGE` constant instead of two divergent literals
  (0.1–4.0 and 0.0–4.0). Core no longer carries its own dead, hardcoded copy of
  the APC controller-help modal.
- **1.0.0-beta.11** — Tour P2 (partial): drop-ins can now contribute slides
  to the first-run tour via module-level `TOUR_SLIDES` (discovered the same
  way as `HELP_ENTRIES`, appended after the core deck when the tour opens).
  control-room-01 0.9.0 ships the first two drop-in slides. Discovery is
  fully fault-isolated: a broken drop-in never breaks the tour.
- **1.0.0-beta.10** — **First-run tour** (v1): a centered slide dialog that
  walks new operators through the core surface — effects, audio sources, the
  help overlay, multi-display, and the right-click menu. Offered automatically
  on the first-ever launch (show-on-startup checkbox controls every run after),
  reopenable any time with **F1** or the context menu's "Open Tour" entry, and
  it resumes at the slide you left off. Slide copy resolves hotkeys from the
  help registry at display time, so bindings are never hardcoded in the tour.
- **1.0.0-beta.9** — New core analyzer: **Audio Chromogram** — real pitch-class
  (chroma) analysis of the live FFT, folding every bin into one of the twelve
  equal-tempered pitch classes (C, C#, D, ... B) regardless of octave. Shown
  as a scrolling chromagram strip (pitch class vs. time) and a circular chroma
  wheel with a dominant-note highlight ring. Uses a soft Gaussian-in-semitone
  weighting with confidence-scaled low-frequency de-weighting rather than
  hard bin rounding, since the shared low-latency 1024-point FFT (46.875 Hz/
  bin) is wider than a semitone below ~800 Hz — verified against synthetic
  tones to be exact from ~D5 up and within one semitone from ~C3 up, with
  sub-bass contributing an honest diffuse glow rather than a falsely precise
  note.
- **1.0.0-beta.8** — Now Spinning platter raised clear of the bottom banner ticker (bottom corners get 72px clearance)
- **1.0.0-beta.7** — Fix the promoted Now Spinning platter never rendering: the lazy overlay create referenced a nonexistent `App.ctx` (AttributeError disabled it on first use since beta.4); it now uses the app GL context directly and waits quietly until GL is up
- **1.0.0-beta.6** — Unknown-source quiet mode: when a now-playing source is playing but cannot name its track, the Now Spinning platter auto-hides and the track banner does not fire
- **1.0.0-beta.5** — `W` hotkey toggles the Now Spinning platter overlay (listed in the `H` help)
- **1.0.0-beta.4** — **Now Spinning overlay promoted to core**
  (`unicornviz/now_spinning.py`): the corner platter card is now fed by the
  now-playing hub, so the DJ mixer, media player and Spotify all get it with
  zero wiring.  Visual glow-up: pulsing cyan↔magenta neon frame with a comet
  sprite racing the border, two-line title/artist, more air around the disc.
  `[now_spinning] enabled/corner` config; `vj_api.set/toggle_now_spinning`.
- **1.0.0-beta.3** — **Now-playing announcement hub**
  (`unicornviz/now_playing.py`): the track banner + HUD pane feed is now a
  registry (`vj_api.register_now_playing`) instead of hard-coded media/spotify
  references in `app.py`.  Sources register a shared-shape snapshot callable
  with a priority (dj mixer 30 > media 20 > spotify 10-ambient); the loudest
  claim wins, ambient sources show while idle, and older drop-ins are
  auto-registered for back-compat.
- **1.0.0-beta.2** — Fix: **ALSA sequencer client leak** in the MIDI core.
  python-rtmidi objects need an explicit `delete()` on Python 3.14 (GC does
  not release the client); every port scan leaked one portless client until
  the kernel's ~64-user-client table filled — MIDI died mid-session
  (controllers unresponsive, selector overlay empty) while open connections
  kept working.  Port enumeration now reuses one cached probe per direction
  and every teardown path (`stop`, `remove_input_device`, aux reconnect,
  `MidiOut.close`) explicitly frees its clients.
- **1.0.0-beta.1** — initial versioned release.
