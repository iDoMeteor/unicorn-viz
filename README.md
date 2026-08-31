# Unicorn Viz

**Version 1.0.0-beta.94**

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

Unicorn Viz is MIT licensed — see [`LICENSE`](LICENSE).

Third-party dependencies keep their own licenses; the full texts ship in
[`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md), which is generated by
`tools/gen_third_party_licenses.py` and installed by every packaging target.
Regenerate it whenever `requirements.txt` pins change.

Some bundled assets are **not** covered by the project's MIT license: the ANSi
art in `assets/ansi/acid/` remains the copyright of its individual artists (see
[`assets/ansi/README.md`](assets/ansi/README.md) for credits). Restricted asset
packs — NVIDIA Omniverse USD characters, MilkDrop presets — are deliberately
not redistributed here; each operator fetches their own. Licensing posture for
the whole project is reviewed in
[`docs/audits/2026-08-08-licensing-audit.md`](docs/audits/2026-08-08-licensing-audit.md).

---

## Contact & Contributing

Issues and PRs welcome. See [Developer Guide § Contributing](docs/developer-guide.md) for code standards.

---

**Happy demoscene visualizing!** 🦄✨

## Changelog

- **1.0.0-beta.100** — dubstep `zcr_mu` `0.095 → 0.093`
  (unicornviz/audio/profiles.py): owner-approved LLM tuning
  recommendation, applied by the training session as part of the
  auto-vj rc.101 batch (see that drop-in's changelog).

- **1.0.0-beta.99** — New detector-facing `AudioData.bass_level_raw`
  channel: log1p of the profile-weighted RAW bass-band mean, read
  before the per-frame max-normalization (the same lesson flux learned
  — normalization erases magnitude). Feeds auto-vj-01's new drop
  trigger/sustain split (audit F1); effects keep reading bass/bass_n
  unchanged.

- **1.0.0-beta.98** — Fixed a runaway onset-strength bug in
  `unicornviz/audio/analyzer.py`: `Analyzer._onset_threshold()`'s MAD
  floor was `+ 1e-6` (a literal-division-by-zero guard, not a reasoned
  floor) -- during a near-silent/degenerate flux stretch, real MAD
  collapses toward zero, and the next real transient's strength
  computation (`(flux - threshold) / mad`) divides by almost nothing.
  Caught live via new training-corpus logging: a real session's
  `onset_strength_max_raw` hit 1,171,176,147. Simulated candidate fixes
  against synthetic pathological/quiet/normal-material scenarios
  (`tools/onset_strength_mad_floor_harness.py`) before landing:
  `mad = max(raw_mad, _BEAT_ABS_FLOOR)` (reuses the existing threshold
  floor rather than a fresh arbitrary constant; `max()` — the same floor
  idiom `beat_grid.py` uses throughout — makes it a true no-op once real
  MAD already exceeds the floor, unlike the old `+`-shaped floor, which
  kept dulling strength even on well-populated material). Landed
  alongside a defense-in-depth `_ONSET_STRENGTH_CAP = 50.0` hard clamp,
  independent of the floor fix, protecting every consumer of raw
  strength (not just `beat_grid.py`'s own log-compression). Owner: "look
  into that mad floor/clamp issue.. what is the most proper? can u sim
  it up and give us the best running start?"
- **1.0.0-beta.97** — Audio Bass Machine tuning pass, from screenshots.
  - **Subwoofer**: the woofer was oversized and its basket rim ran under the
    tweeters. Driver shrunk and the tweeters pulled clear, so nothing overlaps.
    Tweeters gained domes and highlights (they read as drivers now, not holes)
    and **fire sparkle bursts on the highs**. The cone's **individual rings now
    colour-pulse outward from the dust cap on each bass hit** instead of
    sitting as a flat gradient.
  - **Boombox**: EQ ladder height trimmed, and **drips no longer leak past the
    woofers** — the drivers composite on top, but their coverage has thin gaps
    (between surround and basket rim, and outside the rim) that an unmasked
    drip bled through, so the drip layer is now masked by the speaker discs.
  - **Record player**: platter, record, label, rim blocks and tonearm all
    scaled down, and **the arm twitches on every beat** — a quick angular kick
    that settles, the way a stylus jumps in a groove, with a flash at the
    headshell.

- **1.0.0-beta.96** — swept the collapsed sparkle hash out of every remaining
  effect. Audio Chromogram used the same
  `hash21(floor(frag * 0.5) + floor(t * 20.0))` idiom fixed in beta.95, and
  three more (`tech-01`'s Threat Matrix and Reactor Breach, `vector-01`'s
  Laser Tunnel) used the sin-based `hash11(floor(t * ~30))` variant, whose
  argument reaches ~300000 and degrades `sin()` into GPU-dependent mush.
  Both hashes now wrap their input before hashing. Measured over a 40x40
  patch, the sparkle field goes from **1 distinct value at t=10000 to 1234** —
  it was not merely banded at a typical randomised start time, it was
  completely dead. Eleven files in total across four repos (games-01 0.13.2,
  tech-01, vector-01, core); one line each, no visual design changed.

- **1.0.0-beta.95** — Audio Bass Machine 2.0, from screenshot review.
  - **The spectrum bars were upside down.** They hung *down* from the top
    edge, which reads as an inverted analyser and made both the subwoofer and
    the record player look flipped. They are now real bars pegged flush to
    each cabinet's **bottom** edge and growing upward, with peak caps. Drips
    are a separate layer again — wet paint with a heavy bead, running down
    from the top edge, where gravity actually points.
  - **Colours pulled from the mixer palette** (`drop-ins/dj-mixer-01/ui.py`):
    cyan / pink / green / amber / magenta. The old wood-and-olive tints read
    as mud; cabinets are now dark and neutral so the neon carries the frame.
  - **Boombox refitted** — shrunk so the carry handle clears the frame instead
    of being cropped, woofers pulled outward, and the EQ moved to the full
    width of the bottom edge, so nothing overlaps anything.
  - **Subwoofer**: the grey pulsing badge is now a neon level trough with a
    bead dancing along it; ports moved up to flank the driver; feet added so
    the box can never read upside down.
  - **Record player**: brushed-metal plinth with a lit seam and corner glow
    instead of a flat slab; a travelling group of rim blocks lights up in
    colour and chases around with the platter glow; a pitch fader fills the
    dead space.
  - Backdrops react now — the speaker wall's cells and the skyline's towers
    pump off the spectrum instead of sitting there as static camouflage.
  - **Fixed the "ASCII dots".** The sparkle idiom
    `hash21(floor(frag * 0.5) + floor(t * 20.0))` feeds a term reaching
    ~12000 into a hash whose first multiply is x123.34, landing past
    float32's usable mantissa. Measured over a 40x40 patch it degrades from
    **1197 distinct values at t=0 to 15 at t=600s** — a fixed lattice, i.e.
    the regular dotted grid. Because `self.time` starts at a random value up
    to 10000, nearly every instance began in the collapsed regime. `hash21`
    now wraps its input, and the field is replaced with shooting laser
    streaks and rainbow edge drips. **The same idiom appears in 8 other
    effects and is deliberately not touched here.**

- **1.0.0-beta.94** — BPM tapper Enter-confirm: pressing `Enter` while
  the KP-0 tap readout is live now sends the tapped BPM to the Auto VJ
  detector as a 30-second elevated-trust window (degrades to a flash
  message when auto-vj-01 is absent). New `Overlays.bpm_tap_value`
  property; help overlay line added. Also: `dubstep` audio profile's
  BPM hint band widened `138-142` → `70-160` from real session data
  (the genre's two genuine tempo bands; detector-side prior unchanged),
  and detector-facing analyzer feedback unchanged — see auto-vj-01
  `1.0.0-rc.90` for the paired drop-in changes.
- **1.0.0-beta.93** — New shared track-path hint bus on `App`/`VJApi`
  (`publish_track_path`/`get_track_path`, mirrors the existing
  `publish_bpm`/`get_bpm` bus exactly): lets a source that knows a real
  local file for what's playing (dj-mixer-01) publish it for an offline
  consumer (training-kit-01's packaging step) to run independent
  analysis (Essentia) against, without either side depending on the
  other. Also corrects a version-header gap: `unicornviz/__init__.py`
  was never bumped to `1.0.0-beta.92` when that entry below landed.
  See [docs/adr/vj-system.md](docs/adr/vj-system.md).
- **1.0.0-beta.92** — `unicornviz/audio/analyzer.py`: new public
  `Analyzer.refractory_s` property exposing the BPM-fed onset refractory
  (`set_expected_bpm()`'s internal `_refractory_s`) without a drop-in
  needing to reach across the module boundary. Added to test a candidate
  root-cause mechanism for BPM-lock entrenchment flagged by
  `docs/audits/2026-08-13-bpm-tempo-detection-audit.md` (finding T4): a
  confident-but-wrong BPM estimate can suppress every other true beat at
  the source, making the onset evidence itself agree with the wrong
  lock. See [docs/adr/vj-system.md](docs/adr/vj-system.md).
- **1.0.0-beta.91** — `unicornviz/audio/analyzer.py`: `_ASSUMED_SAMPLE_RATE`
  was a hardcoded `48000` constant used directly for the FFT bin→Hz
  mapping and onset/vocal-envelope `dt` math, never reconciled with
  `AudioCapture`'s actual detected device rate. New
  `Analyzer.set_sample_rate()`, synced by `AudioManager` every analysis
  frame (cheap no-op when unchanged) so a mid-session device/fallback
  switch to a differently-rated device can't go stale. Found auditing a
  live session for a suspected sample-rate-mismatch bug — that specific
  incident turned out not to be this, but the mismatch risk itself was
  real and latent. See [docs/adr/vj-system.md](docs/adr/vj-system.md).
- **1.0.0-beta.90** — `unicornviz/audio/profiles.py`: sigma-matches-
  hint-band pass across all 16 audio profiles — `bpm_prior_sigma` now
  derives from each profile's own hand-dialed `bpm_hint_min`/`max`
  instead of being independently authored. `electronic` re-confirmed
  enabled (deliberate vocal-presence control pair against `house`);
  `hardstyle` `bpm_hint_min` 145→155 (mu 150→160); `drum_and_bass`
  `bpm_hint` 168-178→165-180. See auto-vj-01's own changelog (rc.59)
  and [docs/adr/vj-system.md](docs/adr/vj-system.md).
- **1.0.0-beta.89** — `unicornviz/audio/capture.py`'s
  `_candidate_monitor_devices()` now logs a `WARNING` (naming the
  unmatched hint and every visible input device) when a configured
  `--audio-device` hint matches nothing and silently falls back to the
  system default input. Previously silent — a headless/unattended
  session (e.g. training-kit-01's daemon) could run an entire session
  against the wrong device with zero errors in the log. Found live-
  probing the exact media-01 + training-daemon code path (VLC +
  `PULSE_SINK` + this device-matching function) after a session came
  back with zero audio energy across every tick.
- **1.0.0-beta.88** — `unicornviz/audio/analyzer.py`'s `OnsetEvent` gains
  `band_weight` (bass fraction of the onset's flux, 0..1, computed from
  the already-existing `data.bass_flux`) — feeds auto-vj-01's new
  strength/band-weighted phase coherence (the real fix for
  `phase_confidence`'s structural cap). Default `1.0` keeps existing
  onset consumers unaffected. See auto-vj-01's own changelog and
  [docs/adr/vj-system.md](docs/adr/vj-system.md).
- **1.0.0-beta.87** — New `--media-favorites` CLI flag: pairs with
  `--media-source` to boot media-01 into its named `favorites` playlist,
  unshuffled, no repeat, instead of the shuffled full library --
  training-daemon `--source media` now always uses it. See media-01
  0.21.0 and training-kit-01 0.15.9's own changelogs.
- **1.0.0-beta.85** — New detector-facing band channel: `unicornviz/audio/analyzer.py` gains `AudioData.bass_det`/`mid_det`/`treble_det` (`unicornviz/effects/base.py`), computed from the same pre-curve input as `bass`/`mid`/`treble` but through a separately-tuned `_shape()` gain (bass `2.0` vs. the effects-facing `6.6`; mid/treble unchanged, already well-tuned) -- fixes real `bass` readings pegging near ceiling almost always (median `0.97-0.98` across every director mode, verified against real session data) by giving the detector a channel with actual dynamic range instead of sharing the effects-tuned saturating curve. Effects and existing `bass`/`mid`/`treble` consumers are unaffected. Companion change in auto-vj-01 (`band_blend`'s z-score now reads the new channel) -- see that drop-in's own changelog and [docs/planning/auto-vj-drop-score-redesign-plan-2026-08-11.md](docs/planning/auto-vj-drop-score-redesign-plan-2026-08-11.md).
- **1.0.0-beta.84** — Fixed the `centroid_fit` formula-mismatch bug: `unicornviz/audio/analyzer.py` gains a public `PERC_BAND_CENTERS_HZ` constant (geometric-mean center Hz of the 64 log-spaced perceptual bands, matching `tools/gen_spectral_fingerprints.py`'s own `_centers`), which the Auto VJ recommender now uses to compute the live spectral centroid over `audio.bands` instead of the raw linear-FFT bin array -- the same basis every profile's `spectral_centroid_mu` was already derived in, closing the structural mismatch. Purely additive to core; no existing analyzer output changed. Companion change in auto-vj-01 -- see that drop-in's own changelog and [docs/adr/vj-system.md](docs/adr/vj-system.md) § "Recommender centroid_fit Weight Cut + tech_house Disabled" (addendum).
- **1.0.0-beta.83** — `tech_house` disabled in `unicornviz/audio/profiles.py` (`enabled=False`, same disable-not-delete pattern as `hyphy`), pending a library with enough tech_house-specific material to recalibrate `spectral_centroid_mu` against a real measured average -- it sat closest of any profile to `peak_time` on `bpm_prior_mu` and leaned on a known-buggy centroid signal to break that tie. Still directly resolvable via `get_profile('tech_house')`. Companion change in auto-vj-01 (recommender `centroid_fit` weight `0.8 → 0.5`, same open formula-mismatch bug) -- see that drop-in's own changelog and [docs/adr/vj-system.md](docs/adr/vj-system.md) § "Recommender centroid_fit Weight Cut + tech_house Disabled".
- **1.0.0-beta.82** — `hardgroove` eliminated entirely from `unicornviz/audio/profiles.py` (not disabled -- no dict entry survives): zero validated library examples across every recent session, plus heavy overlap with `tech_house`/`peak_time`/`hard_techno` on BPM, spectral centroid, and an onset-density value identical to `peak_time`'s. Live profile count: 16 (was 20). `docs/audio-profile-reference.md` fully regenerated from live code in the same pass -- it had drifted stale, including an outdated claim that `bpm_hint` hard-caps the ACF search range (removed 2026-08-04). See [docs/adr/vj-system.md](docs/adr/vj-system.md). Companion change in auto-vj-01 (`_RECOMMENDER_VERSION` bump) -- see that drop-in's own changelog.
- **1.0.0-beta.81** — `hyphy` tightened (`bpm_prior_sigma` 0.20→0.15, `spectral_centroid_sigma` 600→400 Hz) and disabled in `unicornviz/audio/profiles.py`, pending real trap/hyphy library material -- a real session found the recommender picking it for hip-hop tracks (987x) that should land on `rap_rnb`, with zero known hyphy/trap tracks in the library to validate any pick against. Still directly resolvable via `get_profile('hyphy')`, same disable-not-delete pattern as `electronic`/`generic` before. Companion changes in auto-vj-01 (`drop_score` bass-gated reweight, mood-profile drop/climax ladder reboot, `onset_fit` weight bump) -- see that drop-in's own changelog and [docs/adr/vj-system.md](docs/adr/vj-system.md) § "Drop Score Bass-Gated Reweight".
- **1.0.0-beta.78** — `uk_garage`, `breaks`, and `generic` profiles eliminated entirely from `unicornviz/audio/profiles.py` (not disabled -- no dict entry survives), a same-day follow-on to the house-family consolidation below. `get_profile()`'s unknown-key fallback moved from `generic` (now gone) to `house`. Live profile count: 17 (was 20). See [docs/adr/vj-system.md](docs/adr/vj-system.md) § "House-Family Consolidation" addendum. Companion changes in training-kit-01 (dead genre-map entries removed) and auto-vj-01 (`_RECOMMENDER_VERSION` bump) -- see those drop-ins' own changelogs.
- **1.0.0-beta.77** — House-family consolidation in `unicornviz/audio/profiles.py` (multi-session investigation with `dj-mixer-01`, see [docs/adr/vj-system.md](docs/adr/vj-system.md) § "House-Family Consolidation" for the full account). `deep_house`/`house`/`tech_house` BPM bands moved from soft/overlapping to adjacent (112-118/118-126/127-134) with tightened `bpm_prior_sigma`; `electronic` revived and renamed `dance` (re-enabled, same band as `house`, split via vocal-presence terms alone -- the first real use of the `vocal_hnr_fit`/`vocal_fmr_fit` copy-bug fix from the day before); `rap_rnb` mu set to an explicit owner judgment call rather than fit from a session sample later found unrepresentative; `hyphy` relabeled "Hyphy / Trap" with a widened band. New drift-canary test asserts every profile's `bpm_prior_mu` falls inside its own `bpm_hint_min`/`max`. Companion change in auto-vj-01 (`centroid_fit` weight cut) -- see that drop-in's own changelog.
- **1.0.0-beta.76** — Two core bugs reported by the owner in another session ("both are the same family as the vocal_hnr/vocal_fmr bug your other session just fixed... uber critical, please address now"): (1) `AudioData.bpm` was dead -- `Analyzer.process()` never assigned it, so every effect read the constructor default (`120.0`) forever regardless of the real track tempo (Auto VJ never noticed, since it runs its own independent beat tracker and never reads `data.bpm` back out). Fixed by wiring the existing `set_expected_bpm()` feedback hook (Auto VJ already calls it every frame) through to `data.bpm`, sticky across low-confidence and silent frames. (2) `App._fill_audio_scratch()` turned out to be a *second*, independently hand-written `AudioData` copy list with the exact same gap `_copy_audio_into()` had (missing `vocal_hnr`/`vocal_fmr`) -- found the same day the first one was fixed. Structural fix this time, not just a second patch: new `unicornviz.effects.base.copy_audio_data()` is the single source of truth for `AudioData`'s field list; both copy sites now delegate to it. See [docs/adr/vj-system.md](docs/adr/vj-system.md) § "Same-Day Second Occurrence."
- **1.0.0-beta.74** — **Selecting the DJ controller as an audio source no longer kills the app.** The mixer opens that interface directly at real-time priority, bypassing PipeWire; opening the same hardware again for capture does not raise — it takes the process down inside the native audio stack, leaving no exception, no traceback and an empty faulthandler dump, with the log ending mid-line after `Audio: opening stream`. Since it cannot be caught, it is now refused: any controller exposing `owned_audio_device_names()` contributes to a claimed-device set (convention only — core imports no drop-in), and claimed devices are rejected for manual selection, for auto-fallback, and in the selector's viability flags. Matching is by distinctive token rather than substring, because the layers name the same box differently and share no substring at all: `DDJ-REV1: USB Audio` vs `DDJ-REV1 Analog Surround 4.0`. Also explains the same session's other symptom — the monitor really was silent (`rms=0.00000`), so auto-selection was right to refuse it.
- **1.0.0-beta.73** — `tech_house.spectral_centroid_mu` (`unicornviz/audio/profiles.py`) adjusted `2550 → 2900`, an LLM tuning recommendation from a real training session (observed 2910.5). Checked for overlap before applying: increases tech_house's distance from `house`'s own mu (100 → 250), the exact profile pair behind that session's #1 confusion (`Tech House → house`, 1060x). Part of a larger director/detector/recommender refinement batch landed the same day in auto-vj-01 and training-kit-01 -- see [docs/adr/vj-system.md](docs/adr/vj-system.md) § "Director/Detector/Recommender Refinement Batch" and [docs/planning/auto-vj-director-detector-refinement-plan-2026-08-09.md](docs/planning/auto-vj-director-detector-refinement-plan-2026-08-09.md).
- **1.0.0-beta.72** — `spectral_centroid_mu` recalibrated for all 20 audio profiles (`unicornviz/audio/profiles.py`) -- was independently hand/LLM-authored and disagreed with each profile's own `expected_bands` fingerprint by up to 1.9x, the real premise behind a spectral-centroid recommender term dominating composite scores in a live auto-vj-01 session. Now derived directly from `expected_bands` (same weighted-mean-frequency formula the live recommender uses), so the two "brightness" representations can't disagree by construction. See [docs/adr/vj-system.md](docs/adr/vj-system.md) § "`spectral_centroid_mu` Recalibrated" (auto-vj-01).
- **1.0.0-beta.71** — Config Editor honors an optional per-row `step` in
  drop-in settings rows, making 0/1 toggles (webcam-01 1.1.2 selfie-seg)
  actually flippable — the default (max-min)/40 notch was floored back
  to 0 by quantizing setters on every nudge. The BPM tapper readout now
  repeats on **every mirror tile**, not just the resolved primary — the
  field no-show was the window moving displays one second before the
  taps, relocating the primary overlay tile away from the watched head.
- **1.0.0-beta.70** — New public `AudioManager.sample_rate` property (delegates to `AudioCapture.sample_rate`) so consumers computing a frequency axis from FFT bin indices can derive Nyquist from the real capture rate instead of assuming a fixed one -- auto-vj-01's spectral centroid calc was assuming 22050 Hz (44.1kHz) regardless of what the device/PipeWire actually negotiates, understating readings ~8.8% against this project's own documented 48kHz default. See [docs/adr/vj-system.md](docs/adr/vj-system.md) § "Live-Session Follow-Up" (auto-vj-01).
- **1.0.0-beta.69** — BPM tapper hardening after a field no-show: the
  readout now renders on the audience window even while the control room
  mirrors the HUD/modals (recording-indicator parity — the modal gate
  previously hid it entirely), uses real glyph metrics so it sits flush
  right instead of drifting, is a third bigger, and logs
  'BPM tapper: tap sequence started' so a missing readout is diagnosable
  from the log alone.
- **1.0.0-beta.68** — **Fixed: `vocal_hnr`/`vocal_fmr` audio fields were always zero.** `AudioManager._copy_audio_into()` (the hand-written field-by-field copy that publishes the analysis thread's snapshot to the main-thread audio buffers) never copied these two fields -- added after the copy function was written, never added to it. Any effect or drop-in reading `audio.vocal_hnr`/`audio.vocal_fmr` (not just Auto VJ's recommender, where this was found) has been silently getting `0.0` regardless of what's actually playing. New regression test enumerates every `AudioData` slot dynamically so a future field added without a matching copy line fails loudly instead of the same way these two did.
- **1.0.0-beta.67** — **KP 0 is a BPM tapper**: tap along on keypad-zero and
  a cyan readout appears in the top-right corner with the tapped tempo
  (averaged over up to 8 consecutive intervals; a 2.5 s pause starts a fresh
  measurement). The readout shows only while tapping (lingers 3 s) and drops
  below the recording indicator when that occupies the corner. Also removed
  the COMPOSE debug line from the HUD tweakables block.
- **1.0.0-beta.66** — **Headless runs record training data by default.** `--dj-mixer-source` and `--media-source` now imply `--training`; `--no-training` opts out. A headless source *is* a training run — that is what the flag group exists for — and requiring a separate opt-in failed silently: the session looked healthy, recorded video and audio correctly, and produced no training data at all, which is only discoverable once the set is over and no longer repeatable. The group description, both source flags and the configuration reference all now state it, and `docs/configuration.md` gains a *Headless / training runs* section (which also folds away a duplicate `[render]` heading).
- **1.0.0-beta.65** — **`--training`**: enable Auto VJ training capture for a run. There was no way to do this from the command line, so an unattended run recorded **zero** training data unless a human pressed the in-app toggle — which is precisely what headless operation is supposed to remove. The flag turns on all three streams together (decision log, live corpus, sequence corpus), because a decision log without the corpora cannot be scored and a corpus without decisions cannot be explained; partial capture is what makes a run unusable after the fact.
- **1.0.0-beta.64** — `--dj-mixer-set` and `--dj-mixer-start-delay`, pairing with dj-mixer-01 0.166.0: headless autoplay can now be told **which set to play**, ejects both decks first, and waits (default 3s) before the first track so audio, recording and deck loads settle. Previously it armed a mode but selected nothing, so an unattended run played a random walk of the whole library — watchable, but not a repeatable basis for training. Also pairs with immersive-01 0.10.1, which removes the dead `iMid` uniform that made Tunnel crash on its first frame and get quarantined mid-session.
- **1.0.0-beta.63** — **Stop killing ffmpeg while it is still writing the file.** `-movflags +faststart` moves the index to the front of the MP4, which means **rewriting the entire file** once recording stops. A long set is many gigabytes, so that pass legitimately takes tens of seconds — but stop() allowed a fixed 10 s, then SIGINT, then **SIGKILL after 10 s more**. On a ~13 GB capture (2 hours at the measured rate) the rewrite needs roughly 15-30 s, so the safeguard would have destroyed the very recording it was closing, and the longer the set the likelier it got. Finalizing is now judged by **progress, not elapsed time**: while the output file keeps changing ffmpeg is working and is left alone; escalation happens only when it goes quiet for 20 s, with a 10-minute absolute ceiling. Found by asking what happens at the end of a live 2-hour headless run, before it got there.
- **1.0.0-beta.62** — CLI flags for the two settings added this week: `--record-codec` (auto / libx264 / h264_vaapi / …) and `--fps-limit` (0 follows the display vsync). Recording already had `--record`/`--no-record`, `--record-audio`, `--record-dir`, `--record-fps`, `--record-crf`, `--ffmpeg-path` and `--record-audio-device`, so a headless capture no longer needs `config.toml` touched at all — as does the mixer, via the existing `--dj-mixer-autoplay-mode {autoload,cut,crossfade,smart}`.
- **1.0.0-beta.61** — **Hardware video encoding for recordings.** `[recording] codec` now defaults to `"auto"`, which probes for a working H.264 encoder (NVENC, then VA-API, then QSV) and falls back to software x264 when none is usable. The probe *encodes a real frame* rather than trusting `ffmpeg -encoders`: being built in says nothing about whether it runs here — Fedora's stock VA-API driver reports `No usable encoding profile found` only when you actually try. Each backend gets the command shape it needs: VA-API opens its device before any input and has the frame uploaded after the flip (`vflip,format=nv12,hwupload`), and `-crf`/`-preset` are dropped for hardware encoders that reject them. If a hardware encoder passes the probe but still fails to spawn at full resolution, the recorder retries once in software — losing the acceleration is better than losing the recording. Verified end-to-end on Intel Iris Xe: both paths produce valid, correct-length files.
- **1.0.0-beta.60** — **Render frame cap, defaulting to a locked 30.** New `[render] fps_limit`, also on the config editor's Visuals tab (display/24/30/60). Measured on the owner's rig, frames were landing at ~35 ms in both single and mirror modes — past the 60 Hz vblank, so the loop missed it and took the next one anyway, but *unevenly*: the effective rate was already ~30 with jitter on top, and jitter is what reads as judder. Requesting every second vblank up front makes that cadence exact and tear-free, and leaves GPU headroom for a capture tool on the same adapter. Implemented as a swap interval rather than a sleep loop, since a timer drifts against the vblank and reintroduces the very judder this removes; caps that do not divide the refresh rate evenly round to the nearest interval that does and say so in the log.
- **1.0.0-beta.59** — Recording **fps is now a named choice** in the config editor (24/25/30/48/50/60) instead of a free 15-120 slider — the rate has to land on something an editor will accept, and the row shows the full list with the active one bracketed. A value set by hand in `config.toml` is left alone; the row just snaps to the nearest choice for display. Documents **hardware video encoding** in the configuration reference: Fedora's `libva-intel-media-driver` ships *without* H.264 encode, which is why VA-API probes report `No usable encoding profile found` — RPM Fusion's `intel-media-driver` replaces it and needs **no reboot**, only an application restart. Paired with projectm-01 0.10.3, which moves the preset-catalog rebuild off the render thread entirely.
- **1.0.0-beta.58** — **Third-party attribution now ships with every bundle.** MIT, BSD and Apache dependencies all require their copyright notices to travel with any binary distribution, and none of the three packaging targets carried them. `tools/gen_third_party_licenses.py` generates `THIRD_PARTY_LICENSES.md` from the validated virtualenv — the full license text of all 16 runtime packages, including the twelve bundled-library notices inside `pysdl2-dll` — and the Flatpak, Snap and Windows installer each install it alongside `LICENSE`. The Windows installer also stops sweeping the entire working tree into the package: restricted third-party assets (NVIDIA USD packs, MilkDrop presets), operator secrets and runtime state (`.env`, `runtime/`, `logs/`, `recordings/`) and build junk are now excluded, and setup shows the MIT license. ANSi art from ACiD Productions is credited to its individual artists in `assets/ansi/README.md`, generated from the SAUCE records. Full review in `docs/audits/2026-08-08-licensing-audit.md`.
- **1.0.0-beta.58** — **Quitting no longer core-dumps.** `AudioManager.stop()` called `sounddevice.terminate()`, which does not exist — the real name is `_terminate` — so the deliberate PortAudio teardown raised into its own `except` on every single shutdown and never ran. Python's atexit then ran it during interpreter exit instead, at which point a stream whose close had already timed out made PortAudio's JACK host API assert and abort (`pa_jack.c:869: Terminate: Assertion 'err == 0' failed`). Teardown now uses the correct name, and runs **only when the capture closed cleanly**; otherwise it unregisters the atexit hook and lets the OS reclaim the device, because terminating with a stream still open is worse than not terminating at all. Also: **audio selector labels no longer overflow the panel** — long device names are trimmed from the middle, always preserving the last few characters, since 'DDJ-REV1 Analog Surround **4.0**' and 'DDJ-REV1 Analog **Stereo**' differ only at the tail. Paired with projectm-01 0.10.2, which removes an 11-second freeze when trashing a preset.
- **1.0.0-beta.57** — **Auto-selection ranks outputs ahead of microphones.** The Linux tiers identify a monitor by looking for `monitor` in the device name and by hostapi. PipeWire endpoints reached through the **JACK** hostapi satisfy neither — they arrive as plain descriptions like `DDJ-REV1 Analog Surround 4.0` — so on such a machine every candidate fell into one tier and the order collapsed to USB enumeration order. Measured on the owner's rig, that put the DJ controller's output **7th, below five microphones**, and booted the app onto a headphone-output monitor that is silent unless something plays to it; the silence fallback then walked straight into a webcam mic. Ranking now applies the same pactl-backed output/input classification added in beta.56, so every output precedes every input while the order inside each group is untouched. On the owner's rig the controller's output moves from 7th to 2nd. Where nothing can be classified (no pactl, no name hints) the previous order is preserved exactly.
- **1.0.0-beta.56** — **Selecting an audio source can no longer kill the app.** Picking a webcam microphone from the Alt+A selector ended the process with `Fatal Python error: Aborted` — a heap-corruption abort surfacing from the reader thread's numpy math, with no Python exception to catch and no clue at the abort site. Cause: the switch replaced the stream while the reader could still be inside `stream.read()` on it. `_stop_reader_thread`'s own docstring already said callers must not do this; the switch path logged a warning and did it anyway. Three fixes: the switch is now **refused** when the reader has not exited, a reader thread **binds its stream once** instead of re-reading `self._stream` each iteration (it could pick up a stream that was never its own), and each block is **copied before any arithmetic** so numpy never runs over PortAudio-owned memory. **The selector is also no longer a minefield**: real inputs (microphones, line-ins) are **non-viable by default** — only outputs being monitored are enabled — non-viable rows can no longer be activated by Return or reached by cycling, and the menu now lists outputs first, then a non-selectable divider, then inputs, each group sorted alphabetically. Classification uses pactl's sink table, since PipeWire endpoints reach sounddevice by description with no hint of their role. Auto-selection ranking is untouched.
- **1.0.0-beta.55** — **Keep shader compiles out of scene crossfades.** New `BaseEffect.transition_active`, set by the app on both the outgoing and incoming effect for the duration of a blend. During a crossfade two effects render every frame, so it is the worst moment for an effect to do expensive deferrable work — and ProjectM's preset advance calls `projectm_load_preset_file`, which compiles the preset's shaders synchronously on the render thread. Paired with projectm-01 0.10.1, which holds its advance until the blend finishes (its timer keeps running, so the switch lands a second or two later at most). Most effects ignore the flag and are unaffected.
- **1.0.0-beta.54** — **Recording actually produces a usable file.** Three faults, each independently enough to ruin a capture. (1) *Silent audio*: the recorder always captured the **default** sink's monitor, so a set playing through a DJ controller recorded a valid, entirely empty audio stream (measured at -91 dB — digital silence — in the owner's own captures). It now follows the source the **visualizer is analyzing**, falling back to an output that is actually playing, and only then to the default; verified end-to-end at -21 dB from a non-default sink. (2) *Wrong playback speed*: video was muxed as constant-rate while frames arrived at the variable render rate, so a loop running at 26 fps produced a file playing 2.3x too fast and drifting away from its real-time audio. A wallclock-paced writer now holds the declared rate, duplicating the newest frame when the render loop falls behind — a 5.01 s capture fed at 12 fps yields a 5.03 s file where the old path gave 2.00 s. (3) *Invisible failures*: ffmpeg's stderr went to `DEVNULL` and liveness never checked `poll()`, so a dead encoder kept REC lit while every frame was dropped; both are now surfaced with ffmpeg's own explanation. Recording readback is also capped at the muxed frame rate (it previously forced a full-resolution ~25 MB GPU→CPU transfer on *every* rendered frame), and a new **Recording** tab in the config editor exposes fps, quality, preset, audio capture, and an audio-source picker.
- **1.0.0-beta.53** — **Performance remediation, measured** (see `docs/planning/performance-remediation-plan-2026-08-08.md`). The secondary-window present guard no longer starves the mixer: it degrades to every *other* frame instead of one in four, and its threshold derives from the **real display refresh** rather than a hardcoded 60 Hz — on a 30 Hz output the old figure sat below the display's own frame interval, so the guard throttled the mixer permanently by construction. The per-frame perf instrumentation is gated on a real `[logging] perf_frames` key instead of `isEnabledFor(DEBUG)`, which was always True at INFO because the log bands filter at the handlers — it ran in every session forever. `[audio] latency` now defaults to **low** (beta.38 only changed a fallback that never fired) and is selectable from the config editor. Paired with webcam-01 1.0.0-rc.4, which stops re-uploading unchanged camera frames — the measured top of the profile.
- **1.0.0-beta.52** — video-out-01 0.4.1 fixes the `buffer overflow` warning seen on a live run: the v4l2 format struct was 4 bytes short of what the ioctl encodes (Python 3.14 caught it, preventing a kernel write past the buffer), and the resulting `SystemError` slipped past an `except OSError` so the device fd leaked and stayed held open — which is why retries then reported the device busy.
- **1.0.0-beta.51** — **Webcam drop-in restored** (webcam-01 1.0.0-rc.3): the rc.2 privacy change made `__init__` reach the capture worker before it existed, and the resulting `AttributeError` was swallowed by the guarded loader — silently disabling the entire webcam subsystem. Core now logs that failure with a full traceback and says plainly that the subsystem is DISABLED, rather than emitting a bare one-line message. video-out-01 0.4.0 makes its own failures visible too: the toggle reports whether publishing actually started instead of always claiming success.
- **1.0.0-beta.50** — Mixer-only boot got ~0.7s faster: the help-entry and
  tour-slide discovery scans (which import every drop-in module they visit —
  ~1.5s cold across the whole repo) are now scoped by the boot profile, so
  the mixer profile only scans the drop-ins it can actually load. Normal
  boot's scan is unchanged.
- **1.0.0-beta.49** — video-out-01 0.3.0: libfunnel now builds **locally, without sudo** (`drop-ins/video-out-01/install.sh`) into a gitignored `vendor/` at a pinned commit, and the drop-in prefers it over any system copy — v4l2loopback keeps its own sudo-requiring script since a kernel module has no app-local equivalent. Building it for real found five binding bugs the header alone hid, including EGL symbols living in a second shared object, a dequeue return code that would have discarded every frame, a buffering mode that blocks the render thread, and — the dangerous one — libfunnel `assert()`ing on misordered calls, which aborts the process uncatchably. Stream setup is now verified against a live PipeWire daemon; the EGL import and GPU blit still need a consumer attached.
- **1.0.0-beta.48** — **Zero-copy video out.** video-out-01 0.2.0 adds the PipeWire/DMA-BUF backend — the real Linux equivalent of Spout/Syphon — and core now hands it the GL framebuffer directly each frame. Nothing is read back to the CPU, so unlike the v4l2 path it costs no frame-tap subscription at all; OBS consumes it via the obs-pwvideo plugin, GStreamer via `pipewiresrc`. Needs a Wayland session and a locally-built libfunnel, and fails closed on either. **Unverified against real hardware** — v4l2loopback remains the dependable path until someone has watched this one work.
- **1.0.0-beta.47** — **The show can leave the window.** New `video-out-01` drop-in publishes the output as a virtual V4L2 camera (v4l2loopback), so OBS takes it as an ordinary *Video Capture Device* with **no plugin** — closing the worst row on the competitive scorecard, where every rival except projectM could already hand its output to another app and we could not. It rides the frame tap, so with recording or streaming already live it costs **no extra GPU readback at all**. Opt-in on both switches; a missing kernel module logs once and disables. First of four planned backends (PipeWire/DMA-BUF, NDI, Spout/Syphon to follow).
  **Screenshots no longer freeze the show:** the PNG encode and disk write moved to a daemon thread (that was the half-second stall, not the readback), pixels come from the frame tap when one is already in hand, and the capture switched off `ctx.screen.read()` — the default-framebuffer path moderngl gets wrong and which the rest of the codebase already routes around.
- **1.0.0-beta.46** — **One GPU readback per frame instead of one per consumer.** Recording and RTMP streaming each pulled the identical full-resolution frame off the GPU independently — with both live that was two transfers of the same picture every frame (~12 MB/frame at 1080p), and recording's was the *synchronous* path the 2026-08-03 audit flagged as a frame-budget problem. A new `unicornviz.frame_tap.FrameTap` now decides who is due (per-consumer rate caps included), the loop reads back **once**, and everyone due shares that buffer; the subsystem preview keeps reusing it when present. Recording moves onto the double-buffered PBO path as a side effect, which also fixes a latent size mismatch — it was fed drawable-sized bytes while ffmpeg was told the tracked canvas size, which differ under mixed-DPI scaling and mirror/span. Groundwork for the video-interop outputs (v4l2loopback, PipeWire/DMA-BUF, NDI), which would otherwise have made it four or five readbacks per frame.
- **1.0.0-beta.45** — `--dj-mixer-source`/`--media-source` now automatically set `[auto_vj] auto_exit_after_finale = true` (`_build_overrides()`, `__main__.py`) -- a headless source *is* a headless run, so no separate flag or `config.toml` edit is needed to get the auto-exit behavior shipped in beta.44. The config key itself is unchanged and still available directly for non-headless-source use (e.g. a Spotify session with a configured `show_duration_min`).
- **1.0.0-beta.44** — Closes `docs/planning/headless-auto-exit-plan-2026-08-07.md`: new `VjApi.grand_finale_active` property exposes the grand-finale sequence's active/idle completion edge, letting a consumer (auto-vj-01's new `auto_exit_after_finale`) request an unattended app exit once a *timed* finale actually finishes, instead of reaching into `app._grand_finale` directly. See [docs/adr/vj-system.md](docs/adr/vj-system.md) § "Auto-Exit on Set End: the Grand-Finale Completion Watcher".
- **1.0.0-beta.42** — **Mixer-only mode** (P1 of the mixer-only plan):
  `[dj_mixer] mixer_only = true`, the `--mixer` flag, or the new `unicorn-mix`
  entrypoint boots straight into the DJ mixer console — no splash (new
  `[splash] enabled` gate, honored in normal mode too), no audio capture, no
  effect discovery, no visual drop-ins; only `[dj_mixer] mixer_allow`-listed
  drop-ins load. The mixer window auto-opens, its title reads "Unicorn Mix",
  help shows only the sections that still apply, and closing the console
  quits the app. Normal boot is unchanged (default off). Hosted single-window
  mode (P2) remains with the mixer team.
- **1.0.0-beta.41** — `unicornviz/__main__.py` gains `--dj-mixer-source`/`--media-source` CLI flags (plus `--dj-mixer-autoplay-mode`/`--dj-mixer-music-dir`/`--dj-mixer-output-device`/`--media-dir`) that force-enable and configure dj-mixer-01/media-01 for a single run via the existing `Config(overrides=...)` mechanism, mirroring `--record`/`--no-record`'s existing shape. New `App._maybe_auto_play_media()` boot trigger for `[media] auto_play`. Built so `tools/training_daemon.py` (training-kit-01) can drive dj-mixer-01/media-01 as fully unattended headless training sources instead of only Spotify -- see `drop-ins/training-kit-01/docs/headless-training.md` and [docs/adr/vj-system.md](docs/adr/vj-system.md) § "Headless Training: dj-mixer-01/media-01 as Audio Sources".
- **1.0.0-beta.40** — New `App`/`VjApi` capability: `pin_effect_pair()`/`cut_to_pinned_effect()`/`unpin_effect_pair()` -- instantiate two effects once and hard-cut between them (a pointer swap) instead of a full instantiate+destroy transition on every switch. Built for auto-vj-01's effect ping-pong, which alternates between the same two effects for its whole run and was paying that cost on every single swap. `_switch_effect()` defensively releases a pinned pair left behind by an interrupting normal transition (e.g. a manual "next effect" hotkey), so the off-screen instance can't leak. See [docs/adr/vj-system.md](docs/adr/vj-system.md) § "Effect Ping-Pong Hard-Cuts Between Two Pinned Instances".
- **1.0.0-beta.39** — `unicornviz/now_playing.py`'s now-playing snapshot contract gains an optional `genre` key (dj-mixer-01 0.158.0 is the first source to populate it, from the loaded track's ID3 tag) -- feeds auto-vj-01's new Tier 2 recommender accuracy tracking (training-kit-01 0.10.0). See [docs/adr/vj-system.md](docs/adr/vj-system.md) § "Tier 2: Genre-Tag Ground-Truth Accuracy Tracking".
- **1.0.0-beta.38** — Audio stream latency now defaults to `"low"` (was
  `"high"`) everywhere in code: the `[audio] latency` config default, the
  capture constructor, and the unsupported-value fallback. An explicit
  `latency` in config.toml still wins.
- **1.0.0-beta.37** — ProjectM now respects being disabled in the effects
  browser. Auto VJ's projectM-affinity path calls `goto_effect('ProjectM
  Presets')` directly, and a direct goto bypasses the playlist's disabled set
  (which only gates auto-rotation), so switching ProjectM off in the browser
  did not stop the director from pulling it straight back up.
  `VJApi.projectm_available()` now carries the enablement check as well as the
  registration check, and a new `VJApi.effect_enabled()` exposes the operator
  disable state to drop-ins through the public surface. The boot-time preset
  prescan (a ~10k-file disk walk) and the GL bridge warm-up are also gated on
  it, so a disabled ProjectM no longer pays either cost at startup.

- **1.0.0-beta.36** — New `publish_session()`/`get_session()` bus on `App`/`VjApi` (plan §6.3), mirroring `publish_section()`/`get_section()` exactly. Lets a source that knows when the set ends (dj-mixer-01's set clock, 0.152.0) publish set-level phase/timing and grand-finale cue data for a finale-aware consumer to read. Mixer side was already written and guarded, so it lit up with no further coordination. Consumer side (auto-vj-01 arming the finale off it) is not part of this change -- the channel exists, nothing reads it yet. See [docs/adr/vj-system.md](docs/adr/vj-system.md) § "Set-Clock Hint Bus".
- **1.0.0-beta.35** — The Now Spinning platter no longer flickers between
  tracks during DJ crossfades: it switches only after the new track has been
  reported continuously for `[now_spinning] switch_hold_s` (default 5 s), so
  dominance flapping mid-fade never commits and a real change shows once.
- **1.0.0-beta.34** — `rap` and `r&b` audio profiles merged into `rap_rnb` (owner call: genuine siblings, 0.9856 cosine similarity, 3 BPM apart -- not a false catch-all pairing). `hyphy` and `chillstep` got freshly-regenerated `expected_bands` (via `tools/gen_spectral_fingerprints.py`, scoped LLM rerun) targeting their real acoustic differences -- similarity improved 0.9788 → 0.9703 (real but modest gain; see the ADR for the honest caveat on a structural ceiling in cosine-similarity discrimination across this genre cluster). Drop-in pointer: auto-vj-01 1.0.0-rc.17 (`_VJ_WEIGHTS_DOC_VERSION` bump only). See [docs/adr/vj-system.md](docs/adr/vj-system.md) § "`rap`/`r&b` Merged; `hyphy`/`chillstep` Fingerprints Regenerated".
- **1.0.0-beta.33** — `electronic` audio profile disabled (owner call, confirmed by a cosine-similarity audit against the whole catalog): its spectral fingerprint was more similar to far-tempo profiles (`trance`, `hyphy`, `psytrance`) than to its own close-tempo neighbors, and its BPM range was already fully covered by `house`/`tech_house`/`deep_house`/`peak_time` -- a non-discriminating catch-all, not a genre with a real identity. Same disable-not-delete pattern as `generic`: excluded from `enabled_profiles()`/`Alt+A` cycling, still resolvable by direct key lookup. `hyphy` and `chillstep` flagged with the same audit finding but not yet acted on; `rap`/`r&b` checked and found borderline (real sibling relationship, not the same case). See [docs/adr/vj-system.md](docs/adr/vj-system.md) § "Wide-Tier Catch-All Profiles: `electronic` Disabled".
- **1.0.0-beta.32** — `fire_dj` audio profile removed entirely from `unicornviz/audio/profiles.py` (owner call). Its recommender-driven Fire DJ celebration trigger is replaced by a direct, profile-independent easter egg: fires when the DJ spans a wide BPM range within a rolling window. See [docs/adr/vj-system.md](docs/adr/vj-system.md) § "Fire DJ Profile Removed, Replaced by a Wide-BPM-Range Easter Egg". Drop-in pointer: auto-vj-01 1.0.0-rc.16.
- **1.0.0-beta.31** — `[audio] profile` default reverted `"generic"` → `"house"` (owner call, live during a training session): `"generic"` is `enabled=False` in `PROFILES` on purpose -- a disabled, loose/uninformative catch-all never meant to be a real starting analyzer profile, and it made for a noticeably weaker start to training sessions specifically. Reverts the `1.0.0-beta.26` default across all three sites (`config.py`'s `DEFAULT_CONFIG`, `AudioManager.__init__`'s kwarg default, `Analyzer.__init__`'s fallback) plus the HUD's stale-fallback string and both config file comments. No `config.toml` setting added -- this is a code-default-only fix.
- **1.0.0-beta.30** — Per-profile `spectral_centroid_sigma` added to `unicornviz/audio/profiles.py` (tight/medium/wide tiers by genre feel) so the recommender's `centroid_fit` discriminates per genre instead of using one fixed 400 Hz sigma for all 22 profiles. Ships Tier 1 of the recommender accuracy-tracking spec ([docs/planning/auto-vj-recommender-accuracy-tracking-2026-08-06.md](docs/planning/auto-vj-recommender-accuracy-tracking-2026-08-06.md)) -- per-term signal-activity logging rolled up in `session_scorecard.py`. Drop-in pointer: auto-vj-01 1.0.0-rc.14.
- **1.0.0-beta.29** — Recommender weight review: `breaks`/`rap`/`synthwave` `bpm_prior_sigma` tightened (`0.28`/`0.30`/`0.40` → `0.22`/`0.24`/`0.34`; `fire_dj` intentionally left at `0.32` -- its wide tempo span is by design, see [drop-ins/auto-vj-01/docs/weights-and-thresholds.md](drop-ins/auto-vj-01/docs/weights-and-thresholds.md)). New versioned reference doc covers every detector/director/recommender weight and threshold with a glossary up front, kept in sync with `_VJ_WEIGHTS_DOC_VERSION` in `auto_vj.py` per a new CLAUDE.md agent rule ("VJ Weights & Thresholds Documentation"). Also adds a spec for recommender accuracy tracking ([docs/planning/auto-vj-recommender-accuracy-tracking-2026-08-06.md](docs/planning/auto-vj-recommender-accuracy-tracking-2026-08-06.md)) covering a term-discrimination proxy and a future tag-genre-as-ground-truth tier. Drop-in pointer: auto-vj-01 1.0.0-rc.13 (`centroid_fit` weight raise).
- **1.0.0-beta.28** — New shared song-structure hint bus (`App`/`VjApi` `publish_section()`/`get_section()`, mirrors the existing BPM bus exactly -- 5s TTL, validated against the canonical `HOLD`/`RISE`/`PEAK`/`FALL`/`CLOSE` role set) so a source that has pre-analyzed a whole track (dj-mixer-01's new section detector) can tell auto-vj-01's director where the playhead is in the song's phrase structure. See [docs/planning/auto-vj-phrase-structure-plan-2026-08-05.md](docs/planning/auto-vj-phrase-structure-plan-2026-08-05.md) §6 for the full contract and [docs/adr/vj-system.md](docs/adr/vj-system.md) for the implementation record. Drop-in pointer: auto-vj-01 1.0.0-rc.11 (the consumer side).
- **1.0.0-beta.27** — HUD/Monitor tab surfaces the active audio profile's own recommender score (`audio_profile_score`) alongside the existing recommendation, in the overlay's `BPM PROF` line, the `Auto VJ` Monitor tab's new "Profile score" row, and `vj_api.auto_vj_snapshot()` for control-room/operator surfaces -- previously only the alternate ("what would the recommender switch to") was visible, not what the current pick's own score is. Also fixed the overlay's stale `'house'` fallback default (now `'generic'`, matching `1.0.0-beta.26`).
- **1.0.0-beta.26** — `[audio] profile` now defaults to `"generic"` (a wide/uninformative prior) instead of a hardcoded `"house"` -- seeding a real genre's tight prior at startup meant a mismatched profile had to be actively argued out of by auto-vj-01's recommender, and the documented workaround (manually set/restore `[audio] profile` per session) was easy to forget. Mirrors how the BPM detector itself starts with no lock rather than a seeded guess; the recommender converges onto the real genre from evidence within its first eval cycle regardless. `config.full.example.toml`'s misplaced `profile` example (previously under `[midi]`, a documentation bug) moved to `[audio]` and updated.
- **1.0.0-beta.25** — event-driven display-state refresh (July item 5, finally): `SDL_WINDOWEVENT_MOVED`/`DISPLAY_CHANGED`/`FOCUS_GAINED` now re-derive the display index and window origin from live SDL state, validity-gated against known display layouts and throttled — fixes stale overlays/tiling after workspace switches and monitor drags (needs owner multi-monitor verification). Ships `tools/install/windows_deps.ps1` (the field-notes bridge installer) and CLAUDE.md platform/font-asset updates. Drop-in pointer bumps: videos-01 0.7.1 (EOF sentinel leak, no-audio clock, observable reached_bottom), images-01 0.8.1 (cache caps), tech-01 0.10.0 (three precision-dead layers restored + glyph dirty-flag).
- **1.0.0-beta.24** — `generic` audio profile's `bpm_hint_min`/`bpm_hint_max` removed -- it's a disabled catch-all fallback (not a genre) and those fields are no longer read by any BPM tracker engine as of auto-vj-01 1.0.0-rc.7's [BPM detector audit fixes](docs/audits/2026-08-04-bpm-detector-audit.md).
- **1.0.0-beta.23** — RC1 P1 stability/hygiene batch: a dead ffmpeg no longer leaves REC lit silently dropping frames (writer-thread failure latch, flashed once + recorder stopped); FBO rebuilds release their color/depth attachments (`_release_fbo`) instead of leaking ~16 MB per render-scale change; all six implemented transitions + `radial`/`cut` aliases now pass config/CLI validation; `requirements.txt` pinned to the validated versions (floors stay in pyproject); push/PR CI now runs ruff + the core suite (`.github/workflows/tests.yml`); drop-in registry gains its 4 missing entries. Drop-in pointer bumps: chat-01 0.5.1 (inbound-text-inert tests), spotify-01 1.0.0-rc.3 (429/Retry-After + 0600 token store), webcam-01 1.0.0-rc.2 (no camera while hidden), tech-01 0.9.1 (cyber_war seed fix).
- **1.0.0-beta.22** — New `VjApi.active_now_playing()` wraps the existing now-playing hub (`unicornviz.now_playing.NowPlayingHub.active()`) with a read accessor -- the hub already had a write side (`register_now_playing`/`unregister_now_playing`) but nothing to read the currently-active source back, so drop-ins had to reach into `app._private` state to know what's playing. Degrades to `None` on older cores/when nothing is registered.
- **1.0.0-beta.21** — Windows platform P0s: new shared `unicornviz.fonts` resolver (bundled ui-font.ttf first, then per-platform system dirs incl. `C:\Windows\Fonts` and `seguiemj.ttf` for emoji) adopted across core and the control-room/media/banner drop-ins; per-monitor-v2 DPI awareness on Windows (crisp output on scaled displays, correct 76/152px icon bucket); recording remaps the Linux `pulse` default to DirectShow with loopback-device discovery on Windows (video-only degrade when none) and stops ffmpeg via CTRL_BREAK_EVENT + kill escalation instead of the Windows-unsupported SIGINT; pyproject version now single-sourced from `unicornviz.__version__` with the four missing runtime deps added.
- **1.0.0-beta.20** — New `deep_house` audio profile (118-124 BPM, warmer/lower-centroid than `house`, chord-stab-driven fingerprint) -- the house family previously only had `house`/`tech_house`, leaving the slower/warmer end uncovered. `AudioProfile` gains a capability-aware `enabled` flag (disable, don't delete -- still resolvable by direct lookup); `generic` is now disabled from discovery (`Alt+A` cycling and the Auto VJ recommender's candidate pool) since it was competing with, and getting confused with, genuinely calibrated genre profiles.
- **1.0.0-beta.19** — Crash containment: a broken effect (constructor, `update()`, or `render()`) is quarantined and the show advances instead of dying; hotkey handler crashes drop the keypress instead of the app; teardown now runs even when the main loop raises (`ensure_shutdown()`), so audio/MIDI/recorder threads and SDL are never left dangling.
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
