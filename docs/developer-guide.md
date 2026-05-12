# Unicorn Viz — Developer Guide

## Contents

1. [Architecture Overview](#architecture-overview)
2. [Repository Layout](#repository-layout)
3. [Core Subsystems](#core-subsystems)
   - [App Loop](#app-loop)
   - [Effects System](#effects-system)
   - [Audio Pipeline](#audio-pipeline)
   - [ANSI Subsystem](#ansi-subsystem)
   - [MIDI](#midi)
   - [Config, Playlist, Overlays](#config-playlist-overlays)
4. [Writing a New Effect](#writing-a-new-effect)
5. [GLSL Conventions](#glsl-conventions)
6. [Data Flow Diagram](#data-flow-diagram)
7. [Test Strategy](#test-strategy)
8. [Adding Platform Support](#adding-platform-support)
9. [Release Checklist](#release-checklist)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                          App (app.py)                            │
│  SDL2 window ─── moderngl context ─── fixed-timestep main loop  │
│       │                                        │                 │
│  HotkeyHandler ◄── SDL events            Overlays (HUD)         │
│  MidiManager   ◄── rtmidi thread                                 │
│       │                                        │                 │
│  Playlist ──► effect_class ──► BaseEffect ──► render()           │
│                                    │                             │
│  AudioManager ──────────────► update(dt, AudioData)              │
└──────────────────────────────────────────────────────────────────┘
```

The main loop runs at **60 fps** with a fixed-timestep accumulator capped at
100 ms (spiral-of-death prevention).  Every frame:

1. SDL events are polled → dispatched to `HotkeyHandler`.
2. `AudioManager.get_audio_data()` returns the latest `AudioData` snapshot.
3. `effect.update(dt, audio)` advances effect state.
4. `effect.render()` draws to the screen (or to an FBO during transitions).
5. `Overlays.render(dt)` draws the HUD on top.
6. `SDL_GL_SwapWindow` flips the buffer.

---

## Repository Layout

```
unicorn-viz/
├── assets/
│   ├── ansi/           Hand-crafted .ANS demo files
│   │   └── acid/       Downloaded ACiD Productions art
│   ├── fonts/          Optional font8x16.bin (CP437 8×16 VGA font)
│   └── icons/          unicorn-viz.png / .ico application icon
├── docs/
│   ├── user-guide.md
│   ├── developer-guide.md
│   ├── configuration.md
│   └── effect-settings.md
├── drop-ins/           Each folder is a git submodule
│   ├── alien-invasion-01/
│   ├── cyber-war-01/
│   ├── disco-ball-01/
│   ├── hacker-terminal-01/
│   ├── multi-head-01/      (subsystem: display controller)
│   ├── textures-01/
│   ├── tron-grid-01/
│   ├── unicorn-tears-01/
│   └── webcam-01/
├── tools/
│   ├── generate_ansi_art.py   Generates the hand-crafted .ANS files
│   ├── fetch_acid_ans.py      Downloads real ACiD art from 16colo.rs
│   └── launchers/             Linux .sh/.desktop, Windows .bat/.ps1
├── unicornviz/
│   ├── __init__.py
│   ├── __main__.py
│   ├── app.py                 Main application class
│   ├── config.py              TOML config loader
│   ├── dropins.py             Drop-in loader utility
│   ├── hotkeys.py             Keyboard + MIDI → action dispatcher
│   ├── midi.py                MidiManager (python-rtmidi wrapper)
│   ├── overlays.py            On-screen HUD rendering
│   ├── playlist.py            Effect playlist management
│   ├── recording.py           ffmpeg recording pipeline
│   ├── splash.py              Animated splash screen
│   ├── audio/
│   │   ├── analyzer.py        FFT + beat detector
│   │   ├── capture.py         sounddevice PipeWire/ALSA capture
│   │   └── manager.py         Thread-safe audio bridge
│   ├── ansi/
│   │   ├── loader.py          ANSI escape parser + SAUCE reader
│   │   ├── font.py            CP437 8×16 font atlas builder
│   │   └── renderer.py        Canvas → RGBA OpenGL texture
│   └── effects/
│       ├── base.py            BaseEffect ABC + AudioData
│       ├── registry.py        Auto-discovery of effect subclasses
│       ├── alien_biome.py     → Wavey Gravy
│       ├── ansi_viewer.py     → ANSI Viewer
│       ├── audio_spectrum.py  → Audio Spectrum
│       ├── copper_bars.py     → Copper Bars
│       ├── cosmos.py          → Cosmos
│       ├── crystal_pyramids.py→ Crystal Pyramids
│       ├── cube_3d.py         → 3D Cube
│       ├── dali.py            → Dali
│       ├── escher.py          → Escher
│       ├── fire.py            → Curtains
│       ├── fire_lifelike.py   → Fire
│       ├── fractal_zoom.py    → Fractal Zoom
│       ├── metaballs.py       → Metaballs
│       ├── particle_storm.py  → Particle Storm
│       ├── plasma.py          → Plasma
│       ├── raymarcher.py      → Raymarcher
│       ├── sine_scroller.py   → Sine Scroller 2.0
│       ├── starfield.py       → Starfield
│       ├── system_monitor.py  → System Monitor
│       ├── tunnel.py          → Tunnel
│       ├── van_gogh.py        → Van Gogh
│       ├── vector.py          → Vector
│       ├── water.py           → Water
│       └── (+ drop-in effects loaded at runtime via dropins.py)
├── config.toml
├── requirements.txt
└── run.sh
```

---

## Core Subsystems

### App Loop

`unicornviz/app.py` — `class App`

**Key methods:**

| Method | Purpose |
|--------|---------|
| `run()` | Initialises subsystems, enters main loop, tears down on exit |
| `_init_sdl()` | Creates SDL2 window (Wayland-first, X11 fallback) |
| `_init_moderngl()` | Creates OpenGL 3.3 core context via `moderngl.create_context()` |
| `_switch_effect(cls)` | Instantiates a new effect and starts a transition |
| `_render()` | Routes rendering through the transition FBO system |
| `goto_effect(cls)` | Public — called by HotkeyHandler and tests |
| `toggle_fullscreen()` | Calls `SDL_SetWindowFullscreen` |
| `toggle_pause()` | Freezes `dt` accumulation |
| `_on_resize(w, h)` | Updates viewport; propagates to active effects and overlays |
| `set_camera_layout(token)` | Delegates to `current_effect.set_camera_layout()` (WebcamOverlay drop-in) |
| `scale_pip(delta)` | Adjusts `current_effect.parameters['pip_scale']` (WebcamOverlay drop-in) |

**Transitions** are FBO-based:  both the outgoing and incoming effects render
into separate FBOs, then a transition shader composites them to the screen
over `transition_duration` seconds.  Supported modes: `crossfade`,
`smoothfade`, `scanwipe_x`, `scanwipe_y`, `dissolve`, `zoomblend`,
`radialwipe`, `lumawipe`, `stripewipe`, `anglesweep`, `glitchsoft`,
`prismsplit`, `shuffle` (random pick each transition).

### Effects System

See [Writing a New Effect](#writing-a-new-effect) below.

`BaseEffect` provides:
- `self.ctx` — the `moderngl.Context`
- `self.width`, `self.height` — current viewport size
- `self.config` — the per-effect config dict from `config.toml`
- `self.time` — monotonically increasing seconds since effect start
- `self.parameters` — dict of runtime-tweakable floats (exposed to MIDI)
- `_fullscreen_quad()` → `(VAO, VBO)` for shader-based fullscreen effects
- `_make_program(vert, frag)` → compiled `moderngl.Program`

**Auto-discovery:** `registry.py` uses `importlib` to import every `.py` in
the package directory, then inspects for non-abstract `BaseEffect` subclasses.
No registration table to maintain.

### Audio Pipeline

```
sounddevice callback
       │  float32 mono PCM chunks (thread)
       ▼
AudioCapture._ring_buffer (deque, lock-protected)
       │  get_latest_pcm()
       ▼
Analyzer.process(pcm)
       │  FFT → smoothed spectrum → spectral flux → beat
       ▼
AudioData snapshot  ──►  effect.update(dt, audio)
```

**Beat detection** uses spectral flux onset: the RMS of positive differences
between consecutive FFT frames is compared against a rolling mean + threshold
*k·σ*.  A 200 ms cooldown prevents double-triggers.

**Thread safety:** `AudioCapture` uses a `threading.Lock` on its ring buffer.
`AudioManager.get_audio_data()` is called from the main thread and returns a
consistent snapshot.

### ANSI Subsystem

```
raw .ANS bytes
       │
ANSIParser.parse()
       │  ─ strips SAUCE record
       │  ─ walks ESC[ sequences (SGR / CUP / cursor movement)
       │  ─ interprets CP437 printable bytes
       ▼
ANSICanvas  (grid of Cell(codepoint, fg, bg))
       │
canvas_to_texture(ctx, canvas, font_atlas)
       │  ─ for each cell: blit glyph pixels in fg/bg CGA colour
       ▼
moderngl.Texture (RGBA, canvas.width×8 × canvas.height×16 px)
       │
ANSIViewer effect  ─  CRT shader (barrel, scanlines, phosphor glow)
```

**Font atlas:** `font.py` builds a 2048×16 single-channel texture (all 256
CP437 glyphs side-by-side, 8 px wide each).  If `assets/fonts/font8x16.bin`
exists (raw 256×16 bytes, MSB-first), it is used verbatim; otherwise a
built-in Python glyph table covering all block/box-drawing characters is used.

**SAUCE:** The SAUCE record is a 128-byte footer (plus 1-byte `\x1a` SUB
prefix) at the very end of the file.  Fields read: title, author, group,
width, height.  The viewer uses width/height to constrain the canvas, then
falls back to 80×25 if they are zero.

### MIDI

`unicornviz/midi.py` — `class MidiManager`

- Opens the first available `rtmidi.MidiIn` port matching `device_hint`.
- Registers a C-level callback that fires on the `rtmidi` internal thread.
- Callback converts raw status bytes into typed `MidiEvent` dataclasses.
- Distributes events to registered listener callables (thread-safe via a lock).

`HotkeyHandler.attach_midi(midi)` registers itself as a listener and maps
CC → `effect.parameters[*]` and Note → same actions as keyboard hotkeys.

### Config, Playlist, Overlays

**Config** (`config.py`): Deep-merges `config.toml` over `_DEFAULTS`.  All
access via `cfg.get("section", "key", default=x)` — never raises.

**Playlist** (`playlist.py`): Wraps a `list[Type[BaseEffect]]`.  `advance()`
is sequential or random depending on `mode`.  Supports a pinned sequence from
config.  All mutations happen on the main thread.

**Overlays** (`overlays.py`): Renders text HUD elements (effect name, help
panel, message toasts) using a bitmap font shader.  Each overlay element has
an alpha timer so it fades out automatically.  `flash_name()` and
`flash_message()` are the primary public API.

---

## Writing a New Effect

### Minimal example

```python
# unicornviz/effects/my_ripple.py
"""
A simple ripple-wave fullscreen effect.
"""
from __future__ import annotations
import moderngl
from unicornviz.effects.base import BaseEffect, AudioData

_VERT = """
#version 330
in vec2 in_vert;
out vec2 v_uv;
void main() { v_uv = in_vert * 0.5 + 0.5; gl_Position = vec4(in_vert, 0, 1); }
"""

_FRAG = """
#version 330
uniform float iTime;
uniform float iBass;
in  vec2 v_uv;
out vec4 fragColor;
void main() {
    float r = length(v_uv - 0.5);
    float wave = sin(r * 30.0 - iTime * 4.0 + iBass * 8.0);
    fragColor = vec4(vec3(0.5 + 0.5 * wave), 1.0);
}
"""

class MyRipple(BaseEffect):
    NAME   = "My Ripple"
    AUTHOR = "yourhandle"
    TAGS   = ["audio"]

    def _init(self) -> None:
        self._prog = self._make_program(_VERT, _FRAG)
        self._vao, self._vbo = self._fullscreen_quad()
        self._bass = 0.0

    def update(self, dt: float, audio: AudioData) -> None:
        super().update(dt, audio)   # ticks self.time
        self._bass = audio.bass

    def render(self) -> None:
        self._prog["iTime"].value = self.time
        self._prog["iBass"].value = self._bass
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def destroy(self) -> None:
        self._vao.release()
        self._vbo.release()
        self._prog.release()
```

That is all.  The effect is auto-discovered and appears in the playlist
immediately.

### Parameters and MIDI mapping

Declare runtime-tweakable values in `self.parameters`:

```python
def _init(self) -> None:
    self.parameters = {"speed": 1.0, "glow": 0.6}
```

`+`/`-` keys scale `speed`; MIDI CC74 also maps to `speed` by default.  Any
parameter name that matches a CC-map entry in `MidiManager._cc_map` is
automatically controlled by that CC knob.

### Effect metadata

| Attribute | Type          | Required | Purpose                                      |
|-----------|---------------|----------|----------------------------------------------|
| `NAME`    | `str`         | Yes      | Display name in overlays and playlist        |
| `AUTHOR`  | `str`         | No       | Credit shown in help overlay                 |
| `TAGS`    | `list[str]`   | No       | Used for future filtering; no current effect |

Recommended tag values: `"classic"`, `"futuristic"`, `"audio"`, `"ansi"`,
`"3d"`, `"psychedelic"`, `"particles"`, `"visualizer"`.

---

## GLSL Conventions

All GLSL shaders follow these conventions:

```glsl
#version 330                   // OpenGL 3.3 core — no ARB extensions

// Uniforms — camelCase with 'i' prefix (Shadertoy-compatible where sensible)
uniform float iTime;
uniform vec2  iResolution;
uniform float iBass;
uniform float iBeat;

// Vertex input — snake_case with 'in_' prefix
in vec2 in_vert;
in vec2 in_pos;
in float in_life;

// Varyings — snake_case with 'v_' prefix
out vec2 v_uv;

// Fragment output — always named fragColor
out vec4 fragColor;
```

Use `double` / `dvec2` only where precision is truly required (i.e.,
`FractalZoom`).  Double precision is slower on many consumer GPUs.

Avoid `discard` in performance-critical per-pixel paths; use alpha blending.

---

## Data Flow Diagram

```
                ┌─────────────────────────────────────────┐
                │           MAIN THREAD                   │
                │                                         │
  config.toml ──► Config ──► App.__init__                 │
                              │                           │
                    SDL2 window + moderngl ctx             │
                              │                           │
              ┌───────────────┼───────────────┐           │
              │               │               │           │
        AudioManager    MidiManager      Overlays         │
              │               │               │           │
              │   callback    │   callback    │           │
              │  (sounddevice │  (rtmidi      │           │
  PipeWire ───►  thread)      │   thread)     │           │
              │               │               │           │
              └───────────────┴───────────────┘           │
                              │ poll / get                │
                              ▼                           │
                         main loop                        │
                         ├── SDL_PollEvent                │
                         ├── HotkeyHandler.handle()       │
                         ├── audio_manager.get_audio_data()│
                         ├── effect.update(dt, audio)     │
                         ├── effect.render()              │
                         └── overlays.render(dt)          │
                                                          │
                └─────────────────────────────────────────┘
```

---

## Test Strategy

The project does not yet have a `tests/` directory.  Recommended approach:

### Unit tests (headless)

```python
# tests/test_ansi_loader.py
from unicornviz.ansi.loader import ANSIParser
from pathlib import Path

def test_parses_sauce_title():
    raw = Path("assets/ansi/acid/acid-56_GS-ACID.ANS").read_bytes()
    canvas = ANSIParser().parse(raw)
    assert getattr(canvas, "_sauce", {}).get("title") == "Ghengis' Final ANSI"
```

Audio, config, playlist, and ANSI subsystems are all GL-free and can be unit
tested without a display.  Use `pytest` with `pytest-cov`.

### Integration tests (headless GL)

Use an offscreen moderngl context:

```python
import moderngl
ctx = moderngl.create_standalone_context()
from unicornviz.effects.plasma import Plasma
effect = Plasma(ctx, 320, 240, {})
effect.render()
ctx.release()
```

### CI

Recommended CI matrix (GitHub Actions):
- `ubuntu-latest` with `libgl1-mesa-dri` (software renderer for GL tests)
- `windows-latest` for basic import smoke tests (no GL)

---

## Adding Platform Support

### Windows 11

Current status:

1. `pysdl2-dll` already ships SDL2 DLLs on Windows.
2. Audio auto-selection includes Windows loopback-style sources
    (WASAPI loopback / Stereo Mix / What-U-Hear style devices).
3. CLI and pure-Python startup smoke paths are platform-neutral.
4. Full rendering/audio runtime validation is still required on a physical
    Windows machine before GA.

### macOS

1. SDL driver: remove the `wayland` default entirely; SDL auto-selects Cocoa.
2. Audio: use `sounddevice` with the BlackHole or Loopback virtual device for
   system audio capture.
3. OpenGL 3.3 core is supported on macOS 10.9+, but Apple deprecated OpenGL
   in macOS 10.14.  For long-term support, consider a Metal backend via
   `moderngl-window` with the `pyobjc` backend.

---

## Drop-in Effects

Drop-ins live under `drop-ins/<name>/` and each one is tracked as its own
private GitHub repository via a git submodule.

Conventions for a drop-in:
- Keep canonical source in `drop-ins/<name>/`.
- Add it as a submodule in the main repository.
- Set `NAME`, `AUTHOR`, `TAGS` on the class.
- Ensure the main app can discover/load it through `unicornviz/dropins.py`.
- Any hotkeys the drop-in introduces **must** be added to `HELP_TEXT` in
  `unicornviz/overlays.py` — that is the single source of truth.

### Visual effect drop-ins

| Directory          | Class             | Effect Name      | Key |
|--------------------|-------------------|------------------|-----|
| `alien-invasion-01`| `AlienInvasion`   | Alien Invasion   | —   |
| `cyber-war-01`     | `CyberWar`        | Cyber War        | —   |
| `disco-ball-01`    | `DiscoBall`       | Disco Ball       | —   |
| `hacker-terminal-01`| `HackerTerminal` | Hacker Terminal  | —   |
| `textures-01`      | `TextureShowcase` | Texture Showcase | —   |
| `tron-grid-01`     | `TronGrid`        | Tron Grid        | —   |
| `unicorn-tears-01` | `UnicornTears`    | Unicorn Tears    | `U` |
| `webcam-01`        | `WebcamSystem`    | Webcam System    | keypad |
| `images-01`        | `ImageShowcase`   | Image Showcase   | —   |
| `webcam-01`        | `WebcamOverlay`   | Webcam Overlay   | —   |

### Subsystem drop-ins

| Directory     | Class                 | Purpose                              |
|---------------|-----------------------|--------------------------------------|
| `multi-head-01`| `MultiHeadController`| Multi-monitor display topology & mirroring |

## Packaging Evaluation

Phase 2 includes evaluation scaffolds (not GA packaging):

- Flatpak manifest: `packaging/flatpak/io.unicornviz.UnicornViz.yml`
- Snap manifest: `packaging/snap/snapcraft.yaml`

Recommendation for beta: keep shipping source + venv workflow, and use these
manifests as iterative packaging baselines while compatibility matrix checks
continue to mature.

---

## Release Checklist

- [ ] All effects smoke-tested headless: `python -c "from unicornviz.effects.registry import get_effects; get_effects()"`
- [ ] `config.toml` defaults match `unicornviz/config.py` `_DEFAULTS`
- [ ] `requirements.txt` pins are current and minimal
- [ ] ANSI files present in `assets/ansi/acid/` (run `tools/fetch_acid_ans.py` if missing)
- [ ] `run.sh` is executable (`chmod +x run.sh`)
- [ ] All drop-in submodules committed and pushed in their own repos before main-repo pointer update
- [ ] Every new hotkey is listed in `HELP_TEXT` in `unicornviz/overlays.py`
- [ ] Screenshots taken at 1920×1080 for README
