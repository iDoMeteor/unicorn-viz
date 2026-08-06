# Unicorn Viz — User Guide

Owner: Studio Documentation
Status: active
Last updated: 2026-07-07

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
| `u`               | Replay splash screen                                          |
| `U`               | Jump to Unicorn Tears                                         |
| `Ctrl+U`          | Screen burst                                                  |
| `R`               | Toggle random / sequential playlist mode                      |
| `T`               | Toggle auto-advance on / off                                  |
| `Space`           | Pause / resume                                                |
| `F`               | Toggle fullscreen                                             |
| `I`               | Toggle invert colours                                         |
| `[` / `]`         | Reactivity −/+                                                |
| `{` / `}`         | Reactivity MIN / MAX                                          |
| `G`               | Reset reactivity to default                                   |
| `+` / `=`         | Speed up current effect (×1.25)                               |
| `-`               | Slow down current effect (×0.8)                               |
| `Alt+=` / `Alt+-` | Toggle random speed ON / OFF                                  |
| `Ctrl+=` / `Ctrl+-` | Speed MAX / MIN                                             |
| `Ctrl+G`          | Reset speed to default                                        |
| `Z` / `Shift+Z`   | Zoom in / out (affects supported effects)                     |
| `Ctrl+Z`          | Reset zoom to default                                         |
| `Alt+Z`           | Toggle randomize zoom (armed state persists)                  |
| `,`               | Res scale down                                                |
| `.`               | Res scale up                                                  |
| `Shift+,`         | Res scale MIN                                                 |
| `Shift+.`         | Res scale MAX                                                 |
| `Ctrl+,` / `Ctrl+.` | Reset internal render scale                                  |
| `E`               | Jump directly to Audio Spectrum / EQ                          |
| `V`               | Toggle video recording on / off                               |
| `Delete`          | Disable current effect & skip (ProjectM: disable preset)      |
| `Tab`             | Toggle Legacy HUD panel                                       |
| `H`               | Toggle help panel                                             |
| `A` / `Shift+A`   | Open audio source selector menu                               |
| `Ctrl+A`          | Open audio source selector menu (legacy fallback)             |
| `Alt+A` / `Alt+Shift+A` | Cycle audio profile (next / prev)                    |
| `M`               | MIDI device selector                                          |
| `S`               | Save screenshot (`screenshots/unicornviz_YYYYMMDD_HHMMSS.png`)|
| `Esc`             | Quit                                                          |

---

## Help Panel Navigation

Press `H` to toggle the help panel. It has two sides:

- **Left pane** — sections (core shortcuts, plus one section per drop-in that
  registers `HELP_ENTRIES`). Click a section or press Enter/arrows to
  expand/collapse it. If there are more than 10 sections, they page into tabs
  (`PageUp` / `PageDown`).
  - A section with more than 7 entries doesn't grow the card — instead its
    items page into an inner accordion ("Items 1-7", "8-14", ...). Expanding
    the section opens the first page and shows a "press Enter to see more
    items" hint under the title; click a page header (or press Enter again)
    to cycle to the next page. Only one page is open at a time, and moving
    focus to another section auto-closes it.
- **Right pane** — tabbed: `Effects` (the live effect hotkey map, 1-40) is
  always present; `Post FX` and `Mouse` tabs appear only when a drop-in has
  registered entries for them. Click a tab to switch.

---

## Global Randomization Modes (Armed State)

The randomization controls work as a **global armed state** that persists across effect transitions. Here’s how it works:

**When a randomization mode is ON:**
- If the current effect supports that parameter (speed, reactivity, or zoom), it randomizes within the configured range
- If the current effect doesn't support it, the HUD displays `N/A *` (not just `N/A`), indicating the mode is globally armed but unavailable for this effect
- When you switch to an effect that does support it, the parameter randomizes automatically using the armed randomization range

**Armed state persists until you toggle it OFF** — you don't have to enable it for each effect. This is different from manual adjustments (Z/Shift+Z for zoom, comma/period for render scale, and +/- for speed nudges), which never affect the armed state.

**Per-effect customization:**
Each effect can define its own randomization ranges in `config.toml` to override the global defaults:

```toml
[effects.Fire]
# Narrow the global Alt+=/Alt+- speed randomization range for this effect only
random_speed_min = 0.80
random_speed_max = 1.35
# Narrow the global Alt+Z zoom randomization range
random_zoom_min = 0.85
random_zoom_max = 1.15
```

When these are omitted, the effect falls back to the global `[hotkeys]` randomization ranges. The primary mnemonic bindings are `Alt+=/Alt+-` for speed randomization, `Alt+Z` for zoom randomization, and `Ctrl+,/Ctrl+.` for render-scale reset.

## Effect Startup Randomization

Every visual effect produces a **visually distinct appearance** each time it becomes active. The app achieves this by:

- Randomizing visible startup parameters (palette offset, starting angle, intensity, etc.) in the effect's `_init()` method
- Initializing `self.time` to a random value so time-driven shaders don't always start at frame 0
- Using the effect's per-instance RNG (`self.rng`)

This ensures that viewing the same effect twice never produces identical motion or visual styling from the start.

**Exceptions:** `Audio Spectrum` and `System Monitor` are diagnostic/informational and do not randomize.

---

## Audio Profiles (Frequency-Response Tuning)

Different music genres have distinct frequency characteristics. Unicorn Viz includes **21 audio profiles** that optimize bass/mid/treble detection, BPM priors, and spectral genre-matching for each style (19 discoverable via `Alt+A` cycling and the recommender; `generic` and `electronic` are disabled catch-alls kept resolvable by name only — see their rows below). The set is deliberately focused on electronic dance music and its closely adjacent DJ-culture genres (hip-hop, R&B) rather than covering every possible genre — this keeps the Auto VJ profile recommender's candidate pool tight and its matches confident, rather than diluted across genres the system will rarely encounter.

| Profile         | Description                                                                      |
|-----------------|----------------------------------------------------------------------------------|
| `house`         | Deep bass emphasis, steady mid kick, treble for hi-hats                          |
| `tech_house`    | Punchy low-end, clipped claps, tight hats, and steady 4/4 pressure               |
| `peak_time`     | Festival-ready kick, bright tops, and no patience for low-energy lanes           |
| `hardgroove`    | Rolling tribal percussion, fast low-end groove, and busy hats that want motion   |
| `uk_garage`     | Swinging kick-snare, vocal chops, and crisp tops around the 130 pocket           |
| `breaks`        | Broken-beat energy, syncopated mids, and sharp hats with higher tempo tolerance  |
| `trance`        | Elevated mids, strong highs for synth leads, reactive bass                       |
| `psytrance`     | Relentless rolling kick, psychedelic mids, and hyper-detailed tops               |
| `hard_techno`   | Punishing kick, clipped industrial mids, and high-BPM insistence                 |
| `hardstyle`     | Distorted/pitched kick, reverse-bass sweep, and euphoric screech leads           |
| `drum_and_bass` | Fast break transients, subs, and bright hats at full sprint                      |
| `dubstep`       | Half-time wobble bass, scooped growl mids, and sparse syncopated hits            |
| `electronic`    | Balanced across all frequencies with emphasis on detail (disabled -- see below)  |
| `chillstep`     | Slow electronic groove: sub-bass kick, atmospheric pads, soft hi-hats            |
| `ambient`       | Smooth, subtle reactivity with slight bass emphasis                              |
| `rap`           | Heavy sub-bass (808 kick), sustained vocal presence, moderate treble             |
| `hyphy`         | Aggressive sub-bass, sustained hype-vocal chops, bright treble                   |
| `r&b`           | Warm low-mids, sustained vocal-forward mids, smooth low-noise treble             |
| `generic`       | Balanced profile for unknown or mixed content (default fallback)                 |

**Switch profiles with `Alt+A` (next) / `Alt+Shift+A` (previous)** — profiles cycle with wraparound.

**Set default profile in config:** `[audio] profile = "house"`

**`generic` and `electronic` are disabled**, not deleted — excluded from `Alt+A` cycling and the Auto VJ recommender's candidate pool, but still resolvable if referenced directly (e.g. an explicit `[audio] profile` setting). `generic` was never a real genre, just a loose fallback. `electronic` was cut 2026-08-06 after a cosine-similarity audit against the rest of the catalog found its spectral fingerprint more similar to unrelated-tempo profiles than to its own close-tempo neighbors — a flat, non-discriminating catch-all rather than a genre with a real identity, and its BPM range was already fully covered by `house`/`tech_house`/`deep_house`/`peak_time`. See `docs/adr/vj-system.md` for the analysis.

### Where these numbers come from

Each profile carries more than a frequency-range guess: a BPM prior, a target
spectral centroid and zero-crossing rate, an expected onset density, and a
64-band spectral fingerprint that the Auto VJ profile recommender compares
against live audio via cosine similarity. Those targets are synthesized from
published music-information-retrieval research rather than invented by
ear — grounded in AcousticBrainz's per-genre spectral descriptor corpus, the
GTZAN genre dataset (Tzanetakis & Cook, 2002), the FMA dataset (Defferrard et
al., 2017 — 106,000+ tracks across 161 genres), and EDM-specific
classification literature (Sturm 2012; Bonnin & Jannach 2014; Schedl et al.
2018) that characterizes house/techno/trance/DnB and related styles by their
sub-bass-to-treble energy distribution. See
`tools/gen_spectral_fingerprints.py` for the synthesis methodology and the
full acoustic reasoning behind each profile.

Each profile independently tunes:
- FFT frequency band analysis (bass/mid/treble split points)
- Beat detection sensitivity thresholds
- Per-band emphasis weights for normalized cross-genre reactivity

This ensures audio reactivity remains accurate and visually responsive regardless of source material.

---

## Camera / Webcam Controls (Numpad)

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
matching the `device` substring in `config.toml`).  The `M` key opens a
live device selector — use **↑/↓** to navigate and **Enter** to hot-swap the
active port without restarting.

### Built-in presets

Select a preset in `config.toml` under `[midi] preset = "..."`.

| Preset                | Targets                              |
|-----------------------|--------------------------------------|
| `akai_apc_mini_mk2`   | Akai APC mini mk2 (Notes + Control) |
| `akai_mpk_mini`       | Akai MPK Mini MK2/MK3 (default)     |
| `novation_launchcontrol` | Novation LaunchControl XL         |
| `generic`             | Generic USB keyboard (C4–A4 layout) |
| `""`                  | No preset — hardcoded defaults only |

### Akai APC mini mk2 — LED feedback

When the `akai_apc_mini_mk2` preset is active, the app drives every pad LED
to reflect real-time state:

- Pads light with an **idle colour** when their action is available.
- Pads switch to an **active colour** while the action is engaged (e.g. paused,
  fullscreen on, a display mode selected).
- Recording or streaming overlays turn specific pads red or magenta.

All 84 bound notes light up within ~100 ms of startup.  If pads show only the
APC's own standalone colours (cyan bottom row) see the
[LED troubleshooting](#apc-mini-mk2-leds-not-lighting-up) section below.

Idle colours can be cycled per-pad in the MIDI Learn modal (`Ctrl+Alt+H`) with
the `[` and `]` keys.

### Akai APC mini mk2 maximal mapping

The APC preset is now a full-surface mapping.

- Grid pads `0..63`: fully mapped (transport, display modes, PostFX quick-hits,
  selectors, contextual navigation, and utility actions).
- Bottom track buttons `100..107`: contextual nav cluster + selector shortcuts.
- Scene launch buttons `112..119`: high-priority live controls.
- Faders `48..56`: speed, intensity, zoom, reactivity, glow, crt, volume, pan,
  and master volume.

Recommended device settings:

- `device = "apc mini mk2"` to allow robust paired Notes + Control port binding.
- `preset = "akai_apc_mini_mk2"`.
- Controller help modal: `Ctrl+Alt+H` (also available via APC mapped pad/context slot).

### Akai MPK Mini default mapping

**Knobs (K1–K8 = CC 70–77)**

| Knob | CC | Parameter         |
|------|----|-------------------|
| K1   | 70 | `speed`           |
| K2   | 71 | `intensity`       |
| K3   | 72 | `zoom`            |
| K4   | 73 | `reactivity`      |
| K5   | 74 | `glow`            |
| K6   | 75 | `crt`             |
| K7   | 76 | *(reserved)*      |
| K8   | 77 | *(reserved)*      |

**Pads — Bank A (notes 36–43 / C2–G2)**

| Pad | Note | Action        |
|-----|------|---------------|
| 1   | 36   | Next effect   |
| 2   | 37   | Prev effect   |
| 3   | 38   | Random mode   |
| 4   | 39   | Pause / resume |
| 5   | 40   | Fullscreen    |
| 6   | 41   | ANSI art      |
| 7   | 42   | Audio Spectrum |
| 8   | 43   | *(reserved)*  |

**Pads — Bank B (notes 44–51 / G#2–D#3)** — unmapped by default; add
overrides in `[midi.note_map]` as needed.

### Per-device config overrides

Individual CC and note assignments can be overridden without changing the
preset.  In `config.toml`:

```toml
[midi]
device = "akai"           # port name substring; empty = disabled
preset = "akai_mpk_mini"  # built-in preset name (see above)

[midi.cc_map]
70 = "speed"
71 = "reactivity"
72 = "zoom"

[midi.note_map]
36 = "next"
37 = "prev"
38 = "random"
39 = "pause"
44 = "fullscreen"
```

Keys are raw CC/note numbers.  The override layer is applied on top of the
preset so you only need to list the values you want to change.

Tested with the Akai MPK Mini MK2/MK3, the Novation LaunchControl XL, and a
generic USB MIDI keyboard.  Any class-compliant USB MIDI device should work.

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
device = "akai"           # empty = disabled, or name substring
preset = "akai_mpk_mini"  # akai_mpk_mini | novation_launchcontrol | generic | ""
# [midi.cc_map]   # uncomment to override individual CCs
# 70 = "speed"
# [midi.note_map] # uncomment to override individual notes
# 36 = "next"

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
# random_speed_min = 0.75
# random_speed_max = 1.25
#
# Any effect may also provide optional random_*_min/max bounds to override the
# global hotkey ranges while that effect is active:
# random_speed_min/max, random_zoom_min/max,
# random_reactivity_min/max
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

Pressing `Delete` to disable an effect is logged immediately, and a session
summary (count + timestamped list) is logged at shutdown. When
`[logging] level` is not `"NONE"`, the same records are also mirrored live to
a stamped `logs/deleted-effects_<stamp>.log` file so the record survives a
crash rather than only existing in memory. This only tracks the
effect-rotation Delete-key path; ProjectM preset disables are unaffected.

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
| Rainbow Trance  | `RainbowTrance`   | futuristic, audio, crystal     | Audio-reactive crystalline pyramids                  |
| 3D Cube           | `Cube3D`            | classic, 3d, audio             | Rotating wireframe cube                              |
| Curtains          | `Curtains`          | classic, audio                 | Multi-colour oscillating curtain waves               |
| Dali              | `Dali`              | art, surreal, audio            | Melting-clock surrealist scene                       |
| Escher            | `Escher`            | art, optical, audio            | Impossible architecture tile shader                  |
| Fire              | `Fire`              | classic, audio                 | Cellular-automaton lifelike flame                    |
| Fireworks         | `Fireworks`         | classic, audio, particles      | Shell launches, glitter bursts, and spark trails     |
| Fractal Zoom      | `FractalZoom`       | futuristic, audio              | Deep Mandelbrot zoom with beat-burst                 |
| Metaballs         | `Metaballs`         | futuristic, audio              | GLSL SDF metaball field                              |
| Particle Storm    | `ParticleStorm`     | futuristic, particles, audio   | 100k GPU particles, curl noise, transform feedback   |
| Plasma            | `Plasma`            | classic, audio                 | Sin/cos colour-field with palette drift              |
| Sine Scroller 2.0 | `AudioSine`      | classic, audio                 | Multi-sine bouncing text with rainbow colours        |
| Starfield         | `Starfield`         | classic, audio                 | 3D warp-speed star tunnel                            |
| System Monitor    | `HexyStars`     | diagnostic, hud, system        | Live CPU/RAM/GPU/audio performance graphs            |
| Tunnel            | `Tunnel`            | classic, audio                 | Texture-mapped rotating tunnel with depth scroll     |
| Van Gogh          | `VanGogh`           | art, audio                     | Post-impressionist flowing brush-stroke field        |
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

### APC mini mk2 LEDs not lighting up

**Symptom:** MIDI input works (pad presses trigger actions) but no LEDs light
up — pads show only the APC's own standalone colours or stay dark.

**Cause (Fedora 44 / kernel 7.0+):** `snd_usb_audio` wraps all USB MIDI
devices in the `snd_ump` UMP bridge.  The bridge's output pipeline is broken:
bytes are accepted by the kernel but never reach the USB endpoint.  The app log
will show this warning at startup:

```text
WARNING APCLedFeedback: APC Notes port is wrapped by the snd_ump legacy bridge
(Type: Legacy). On kernel 7.0+ the snd_ump OUTPUT path is broken…
```

**Fix:**

```bash
# Make the fix permanent
echo "options snd_usb_audio midi2_enable=N" \
    | sudo tee /etc/modprobe.d/snd-usb-midi2.conf

# Apply it — a reboot is required (the parameter is read-only at runtime)
sudo reboot
```

After reboot, `/proc/asound/card*/midi0` should no longer show `Type: Legacy`
for the APC, and LEDs should light up within 100 ms of app startup.

Setting `midi2_enable=N` disables MIDI 2.0 / UMP wrapping for all USB MIDI
devices.  This is safe on any system without USB MIDI 2.0 hardware (uncommon
as of 2026).

For the full technical explanation see
[midi-controllers-01 Troubleshooting](../drop-ins/midi-controllers-01/docs/troubleshooting.md).

### Low frame rate

- Reduce `[window] width/height` to 1280×720.
- Particle Storm is heavy; skip it via `[playlist] sequence`.
- Reduce `Fractal Zoom` max_iter: `[effects.FractalZoom] max_iter = 80`.

### Camera / Webcam not working

1. Webcam is an always-on subsystem (`webcam-01`), not a playlist effect.
2. Check `[webcam] device = 0`; try `1`, `2` if needed.
3. Open the webcam editor modal (`Ctrl+Alt+K`) to rediscover devices and enable/disable cameras.
4. Close any app holding the camera (OBS, Teams, browser tabs using camera).
5. Run with `--log-level DEBUG` to see camera open/read/switch details.

### Screenshot is blank / upside-down

This is a known cosmetic issue with some GL drivers; the image is flipped
during save so it should appear correct.  If it is blank, your driver may not
support `ctx.screen.read()` — file an issue with your GPU and driver version.
