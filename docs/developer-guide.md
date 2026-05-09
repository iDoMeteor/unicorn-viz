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
│   │   └── acid/       Downloaded ACiD Productions art (18 files)
│   └── fonts/          Optional font8x16.bin (CP437 8×16 VGA font)
├── docs/
│   ├── user-guide.md
│   └── developer-guide.md
├── tools/
│   ├── generate_ansi_art.py   Generates the hand-crafted .ANS files
│   └── fetch_acid_ans.py      Downloads real ACiD art from 16colo.rs
├── unicornviz/
│   ├── __init__.py            Package docstring + layout overview
│   ├── __main__.py            CLI entry point
│   ├── app.py                 Main application class
│   ├── config.py              TOML config loader
│   ├── hotkeys.py             Keyboard + MIDI → action dispatcher
│   ├── midi.py                MidiManager (python-rtmidi wrapper)
│   ├── overlays.py            On-screen HUD rendering
│   ├── playlist.py            Effect playlist management
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
│       ├── ansi_viewer.py
│       ├── audio_spectrum.py
│       ├── copper_bars.py
│       ├── curtains.py
│       ├── cube_3d.py
│       ├── dali.py
│       ├── escher.py
│       ├── fire.py
│       ├── fractal_zoom.py
│       ├── metaballs.py
│       ├── particle_storm.py
│       ├── plasma.py
│       ├── raymarcher.py      ← 2.0: crystalline SDF scene + sparkles
│       ├── sine_scroller.py
│       ├── starfield.py
│       ├── tunnel.py
│       ├── van_gogh.py
│       ├── vector.py
│       ├── water.py
│       ├── wavey_gravy.py
│       └── unicorn_tears.py   ← drop-in, keyed U
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
| `_on_resize(w, h)` | Updates viewport, propagates to active effects and overlays |

**Transitions** are FBO-based:  both the outgoing and incoming effects render
into separate FBOs, then a transition shader composites them to the screen
over `transition_duration` seconds.  Supported modes: `cut`, `crossfade`,
`scanwipe`.

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

See the **Windows 11** section in the user guide.  Key changes needed:

1. `pysdl2-dll` already ships the SDL2 DLL on Windows — nothing extra needed.
2. Replace Wayland driver detection with a Windows-safe default:
   ```python
   if sys.platform != "win32" and "SDL_VIDEODRIVER" not in os.environ:
       os.environ["SDL_VIDEODRIVER"] = "wayland"
   ```
3. Audio: replace `sounddevice` PipeWire monitor with WASAPI loopback.
   `sounddevice` supports WASAPI on Windows; set `device` to the loopback
   device name (see `sounddevice.query_devices()`).
4. `python-rtmidi` has Windows binaries on PyPI — MIDI works out of the box.
5. Packaging: use `PyInstaller` or `cx_Freeze` to bundle the venv.

### macOS

1. SDL driver: remove the `wayland` default entirely; SDL auto-selects Cocoa.
2. Audio: use `sounddevice` with the BlackHole or Loopback virtual device for
   system audio capture.
3. OpenGL 3.3 core is supported on macOS 10.9+, but Apple deprecated OpenGL
   in macOS 10.14.  For long-term support, consider a Metal backend via
   `moderngl-window` with the `pyobjc` backend.

---

## Drop-in Effects

Drop-in effects live under `drop-ins/<name>/` and ship as a separate
unit (planned as git submodules).  They are **not** committed to the main
repository — `drop-ins/` is in `.gitignore`.

Conventions for a drop-in:
- Place the `.py` file in `unicornviz/effects/` (auto-discovered).
- Set `NAME`, `AUTHOR`, `TAGS` on the class.
- Exclude the class name from `Playlist.shortcut_effects` if it deserves a
  dedicated hotkey.
- Add a dedicated hotkey in `hotkeys.py` and a matching line in `Overlays.HELP_TEXT`.

Current drop-ins:

| Name            | Key   | Notes                          |
|-----------------|-------|--------------------------------|
| Unicorn Tears   | `U`   | Prismatic teardrops + starfield |

---

## Release Checklist

- [ ] All effects smoke-tested headless: `python -c "from unicornviz.effects.registry import get_effects; get_effects()"`
- [ ] `config.toml` defaults match `unicornviz/config.py` `_DEFAULTS`
- [ ] `requirements.txt` pins are current and minimal
- [ ] ANSI files present in `assets/ansi/acid/` (run `tools/fetch_acid_ans.py` if missing)
- [ ] `run.sh` is executable (`chmod +x run.sh`)
- [ ] Screenshots taken at 1920×1080 for README
