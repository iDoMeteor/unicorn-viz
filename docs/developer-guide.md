# Unicorn Viz — Developer Guide

Owner: Studio Documentation
Status: active
Last updated: 2026-06-18

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
5. [Stable Public Contracts](#stable-public-contracts)
6. [Registering Help Hotkeys via HELP_ENTRIES](#registering-help-hotkeys-via-help_entries)
7. [GLSL Conventions](#glsl-conventions)
8. [Data Flow Diagram](#data-flow-diagram)
9. [Thread Topology & Module Boundary Contract](#thread-topology--module-boundary-contract)
10. [Test Strategy](#test-strategy)
11. [Adding Platform Support](#adding-platform-support)
12. [Release Checklist](#release-checklist)

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
│       ├── rainbow_trance.py→ Rainbow Trance
│       ├── cube_3d.py         → 3D Cube
│       ├── dali.py            → Dali
│       ├── escher.py          → Escher
│       ├── fire_lifelike.py   → Fire
│       ├── fractal_zoom.py    → Fractal Zoom
│       ├── metaballs.py       → Metaballs
│       ├── particle_storm.py  → Particle Storm
│       ├── plasma.py          → Plasma
│       ├── audio_sine.py   → Sine Scroller 2.0
│       ├── starfield.py       → Starfield
│       ├── system_monitor.py  → System Monitor
│       ├── tunnel.py          → Tunnel
│       ├── van_gogh.py        → Van Gogh
│       ├── vector.py          → Vector
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
| `set_camera_layout(token)` | Delegates to always-on `WebcamSystem` subsystem (`webcam-01`) |
| `scale_pip(delta)` | Adjusts PiP scale in always-on `WebcamSystem` subsystem |
| `set_active_webcam_camera(id)` | Direct camera selection by device id |
| `set_webcam_camera_enabled(id, enabled)` | Enable/disable detected webcam devices |
| `set_webcam_brightness()/set_webcam_contrast()` | Webcam image-control setters |
| `set_webcam_flip_horizontal()/set_webcam_flip_vertical()` | Webcam flip-control setters |
| `get_runtime_state()/set_runtime_state()` | Shared global runtime-state read/write helpers |

### Runtime State

All mutable state that should survive a restart is persisted through a single
shared `RuntimeStateStore` at `runtime/global_state.json`.  The store is
JSON-backed, atomic-write (write-to-`.tmp` then `os.replace()`), and
thread-safe via `threading.RLock`.

**API surface for drop-ins** — always go through `VJApi`:

```python
# Read (dotted path, with safe default)
value = vj_api.get_runtime_state('banner.scroll_speed', default=80.0)

# Write (persists immediately)
vj_api.set_runtime_state('banner.scroll_speed', 95.0)
```

**Namespace conventions**

| Namespace prefix | Owner |
|-----------------|-------|
| `audio.*` | core `AudioCapture` — selected and viable audio source keys |
| `banner.*` | drop-in `banner-01` — text, speed, alpha, font, flags |
| `webcam.*` | drop-in `webcam-01` — camera selection, per-camera settings |
| `multihead.*` | drop-in `control-room-01` — monitor editor exclude list |

**State isolation rules**

- Core code reads and writes via `App.get_runtime_state()` /
  `App.set_runtime_state()`.
- Drop-ins must use `vj_api.get_runtime_state()` / `vj_api.set_runtime_state()`
  — never construct their own `RuntimeStateStore` instance.
- Each drop-in must use its own top-level namespace key (e.g. `banner.*`,
  `webcam.*`) and must never read or write another drop-in's keys.
- **ProjectM is explicitly exempt**: `projectm-01` manages its own state in
  `runtime/projectm/` and `dark_excluded.txt` under its own directory.  Do not
  attempt to move these into the global store.
- **Spotify is explicitly exempt**: the token file `runtime/spotify-pro-token.json`
  is a credential and must never be co-mingled with runtime/UI state.

**Gitignore rules**

The `runtime/` directory is gitignored at the repo root and in every drop-in
that generates runtime files.  Do not commit `global_state.json` or any other
runtime state file.  Per-machine state is local-only by design.

**Transient runtime state that is NOT persisted** (lives only in memory):

- AutoVJ session decisions — written to `logs/autovj-*.jsonl` as append-only
  telemetry; never needs to survive a restart.
- Effect `self.parameters` — reset to defaults on each effect switch by design.
- Grand Finale phase state — intentionally transient.
- Keystroke log — append-only diagnostic log.

**Backup / restore**: copy `runtime/global_state.json` to back up all operator
preferences in one file.  On a fresh machine, drop it back into `runtime/`
before launching.

**Transitions** are FBO-based:  both the outgoing and incoming effects render
into separate FBOs, then a transition shader composites them to the screen
over `transition_duration` seconds.  Supported modes: `crossfade`,
`smoothfade`, `scanwipe`, `scanwipe_x`, `scanwipe_y`, `dissolve`,
`zoomblend`, `shuffle`, `random`.

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

Validation lifecycle:
- `python -m unicornviz` calls `register_dropin_config_validators()` first,
    then `cfg.validate()` before app startup.
- Built-in config sections are validated for type compatibility and key
    constraints (enum/range/list element checks).
- Validation failures raise `ConfigValidationError` and stop startup with a
    consolidated, operator-readable message.

Drop-in config validators:
- A drop-in can provide `drop-ins/<name>/config_validator.py`.
- Export callable: `validate_config(config_data) -> list[str] | None`.
- Errors returned there are automatically namespaced as `dropin:<name>: ...`
    and merged into the same startup validation output.

**Playlist** (`playlist.py`): Wraps a `list[Type[BaseEffect]]`.  `advance()`
is sequential or random depending on `mode`.  Supports a pinned sequence from
config.  All mutations happen on the main thread.

**Overlays** (`overlays.py`): Renders text HUD elements (effect name, help
panel, message toasts) using a bitmap font shader.  Each overlay element has
an alpha timer so it fades out automatically.  `flash_name()` and
`flash_message()` are the primary public API.

Help icon art is loaded from `assets/icons/help/76px/` on sub-4K windows and
`assets/icons/help/152px/` on 4K-or-larger windows.  The loader must use the
source PNGs directly without vertical flipping or extra resizing; the authored
orientation is already correct, and the login/logout slot intentionally swaps
between `login.png` and `logout.png` based on auth state.  Rail ordering keeps
auth controls on the right edge (`... -> settings -> account -> login/logout`);
`account` is currently shown unconditionally with an in-code TODO to auth-gate
it in a follow-up.

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

Declare runtime-tweakable values in `self.parameters`, reading defaults from
`self.config` so operators can tune each effect in `config.toml` without
touching code:

```python
def _init(self) -> None:
    self.parameters = {
        "speed": float(self.config.get("speed", 1.0)),
        "zoom":  float(self.config.get("zoom",  1.0)),
        "glow":  0.6,   # internal-only, no config override needed
    }
```

**Canonical parameter names** — use these exact keys when the concept applies:

| Key | Type | Hotkeys | MIDI default | Notes |
|-----|------|---------|--------------|-------|
| `speed` | float | `+` / `-` / `Ctrl+G` reset | CC74 | Scales animation rate |
| `zoom` | float | `Alt+[` / `Alt+]` / `Alt+Z` random | CC75 | View scale multiplier |

`+`/`-` keys scale `speed`; MIDI CC74 also maps to `speed` by default.

**Per-effect random range overrides** — operators can constrain the F6/F7
random-speed and Alt+Z random-zoom ranges on a per-effect basis in
`config.toml`. These keys are read automatically by the app; no effect code
is needed:

```toml
[effects.MyEffect]
speed = 1.0
zoom  = 1.0
random_speed_min = 0.75   # F6 random-speed lower bound for this effect
random_speed_max = 1.50   # F6 random-speed upper bound for this effect
random_zoom_min  = 0.80   # Alt+Z random-zoom lower bound
random_zoom_max  = 1.20   # Alt+Z random-zoom upper bound
```

If these keys are absent, the global `[hotkeys]` defaults apply.

---

## Stable Public Contracts

The following interfaces are treated as stable runtime contracts for drop-ins
and effect modules. Changes should be backward compatible whenever possible.

1. `unicornviz.effects.base.BaseEffect`
2. `unicornviz.effects.base.AudioData`
3. `unicornviz.vj_api.VJApi`
4. `unicornviz.config.Config`

Notes:

1. Effect drop-ins should import `BaseEffect` and `AudioData` from
    `unicornviz.effects.base` only.
2. System drop-ins should interact with app runtime through `app.vj_api`
    instead of private app attributes.
3. `VJApi.VERSION` (backed by `VJ_API_VERSION`) is the compatibility signal
    for drop-ins that need to enforce a minimum API surface.

---

## Registering Help Hotkeys via HELP_ENTRIES

Drop-ins can publish hotkeys into the `H` help overlay by exposing a module- or
class-level `HELP_ENTRIES` collection.

Accepted entry format:

1. Tuple form: `(section, key, description)`
2. Dict form: `{"section": str, "key": str, "description": str}`

Example:

```python
HELP_ENTRIES = [
     ('Auto VJ', 'Ctrl+Alt+J', 'Toggle Auto VJ on/off'),
     ('Auto VJ', 'Ctrl+J then P', 'Toggle ping-pong mode'),
]
```

Guidelines:

1. Keep section names human-readable; they are grouped/sorted in the help UI.
2. Keep key labels concise and consistent with runtime hotkey notation.
3. Do not mutate help entries at runtime unless the section truly changes.

Discovery path:

1. Startup calls `discover_dropin_help_entries()` from `unicornviz/dropins.py`.
2. Entries are forwarded to `Overlays.register_help_entries()`.
3. Malformed entries are skipped safely; they should still be fixed promptly.

### Runtime Surface Rules

For live runtime code, private fields are owner-module implementation details,
not a general extension surface.

**Preferred call order:**

- `app.vj_api` for drop-ins and system controllers
- public `App` methods/properties for core cross-module callers
- public `Overlays` methods/properties for HUD/selector state

**Policy:**

- Drop-ins should not read or mutate `app._...` state directly when the same
  behavior can be expressed through `VJApi`.
- Cross-module core callers (for example `hotkeys.py`) should not reach into
  unrelated modules' underscore fields when a thin public wrapper on `App` or
  `Overlays` would do.
- `# noqa: SLF001` should be limited to the owner modules that intentionally
  define and centralize runtime state, chiefly `unicornviz/app.py` and
  `unicornviz/vj_api.py`.

**Rule of thumb:** if you need the same underscore-field access pattern in more
than one caller, promote it to a public shim immediately instead of copying it.

`VJApi` compatibility is versioned.  Runtime consumers can check either
`unicornviz.vj_api.VJ_API_VERSION` or `app.vj_api.VERSION` before using newer
capabilities.

Examples:

- good: `app.vj_api.flash_message(...)`
- good: `app.reset_render_scale()`
- good: `overlays.name_overlay_visible`
- avoid in new code: `app._overlays.flash_message(...)`
- avoid in new code: `app._running = False`
- avoid in new code: `app._current_effect.parameters['zoom'] = ...`

### Effect metadata

| Attribute | Type          | Required | Purpose                                      |
|-----------|---------------|----------|----------------------------------------------|
| `NAME`    | `str`         | Yes      | Display name in overlays and playlist        |
| `AUTHOR`  | `str`         | No       | Credit shown in help overlay                 |
| `TAGS`    | `list[str]`   | No       | Used for future filtering; no current effect |
| `PING_PONG_FRIENDS` | `list[str]` | No | Preferred partner effect `NAME`s for Auto VJ/manual ping-pong pairing |

Recommended tag values: `"classic"`, `"futuristic"`, `"audio"`, `"ansi"`,
`"3d"`, `"psychedelic"`, `"particles"`, `"visualizer"`.

`PING_PONG_FRIENDS` should contain effect display names (`NAME` values), not
class names. Example:

```python
PING_PONG_FRIENDS = ['Kaleidoscope', 'Psychedelic', 'Unicorn Tears']
```

### Effect Randomization Requirements

**Every visual effect must produce a visually distinct appearance each activation.**

**BaseEffect provides for free:**
- `self.rng` — per-instance seeded RNG
- `self.time` — starts in [0, 10000) so time-driven shaders vary automatically

**Effects must randomize in `_init()`:**
- Colour/palette offset, starting angle/rotation, discrete mode, intensity/density, media indices

**Exceptions:** `audio_spectrum.py`, `system_monitor.py` (diagnostic).

**Rule of thumb:** If two back-to-back runs look identical for 3 seconds, add `self.rng` calls to `_init()`.

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

### GLSL Validation Workflow

Use `glslangValidator` to catch shader syntax errors before runtime.

Fedora install:

```bash
sudo dnf install -y glslang
```

Validate all embedded shaders in core effects and drop-ins:

```bash
/home/jj/Repos/unicorn-viz/.venv/bin/python tools/validate_glsl.py
```

Validate a narrower scope (example: one drop-in):

```bash
/home/jj/Repos/unicorn-viz/.venv/bin/python tools/validate_glsl.py drop-ins/america-250-01
```

What the script does:

- Scans Python files for embedded GLSL string literals containing `#version`.
- Infers shader stage from symbol names like `_VERT`, `_FRAG`, and keyword args
    such as `vertex_shader=` / `fragment_shader=`.
- Runs `glslangValidator` on each extracted shader.
- Reports totals for scanned files, shaders found, validated shaders, skipped
    unknown-stage shaders, and failures.

Exit codes:

- `0`: all validated shaders passed
- `1`: one or more shader validations failed
- `2`: validator binary missing (`glslangValidator` not on `PATH`)

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

## Thread Topology & Module Boundary Contract

### Thread map (as of 2026-06-18)

```
┌─────────────────────────────────────────────────────────────────────┐
│ MAIN THREAD  (SDL2 event loop + GL + effect pipeline)               │
│                                                                     │
│  SDL_PollEvent ─► HotkeyHandler ─► App actions                     │
│  AudioManager.get_audio_data()  → AudioData snapshot (read-only)   │
│  effect.update(dt, audio)  ──► effect.render()                     │
│  Overlays.render(dt)                                                │
│  SDL_GL_SwapWindow                                                  │
│                                                                     │
│  ┌─ Recording write queue ──────────────────────────────────────┐  │
│  │  uv-rec-writer  (daemon thread)                              │  │
│  │  Drains a queue[bytes] written by the main thread each frame │  │
│  │  Writes to disk via ffmpeg stdin pipe; never touches GL.     │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ uv-audio-reader  (daemon thread — AudioCapture)                     │
│                                                                     │
│  sounddevice.InputStream.read()  blocking-read loop                │
│  → mono-mixes stereo, writes mono PCM block to _block_queue        │
│  → increments block_seq (atomic int) on each new block             │
│  → fires _new_block_event (threading.Event)                        │
│  → tracks xrun_count for operator diagnostics                      │
│  GIL is released during the native read(); audio never competes    │
│  with the render loop for Python bytecode execution.               │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ uv-audio-analyzer  (daemon thread — AudioManager)                  │
│                                                                     │
│  Waits on _new_block_event; skips if block_seq unchanged (dedup).  │
│  Runs FFT → spectral flux → beat detection on the new block.       │
│  Double-buffers result: writes to back AudioData, then atomically  │
│  swaps front ↔ back (lock held only during pointer swap, not FFT). │
│  Appends onset events to a thread-safe queue for main-thread drain. │
│  Never touches moderngl or SDL objects.                            │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ rtmidi callback thread  (MidiManager — optional)                   │
│                                                                     │
│  Fires on MIDI hardware events (note on/off, CC).                  │
│  Only appends to a queue or writes through a lock — never touches  │
│  moderngl objects or Python data structures without synchronization.│
│  Main thread drains the queue each frame in HotkeyHandler.handle().│
└─────────────────────────────────────────────────────────────────────┘
```

### Thread-safety rules

| Rule | Rationale |
|------|-----------|
| moderngl objects are **main-thread-only** | No GL context on audio/MIDI threads |
| `AudioData` snapshots are **read-only** once published | Prevents races with in-flight renders |
| MIDI callbacks **only write to queues** | rtmidi fires on its own thread |
| `RuntimeStateStore` uses `threading.RLock` for all reads/writes | Safe from any thread |
| Recording bytes are passed via `queue.Queue` | Writer thread never reads GL state |

### Module boundary contract

The `unicornviz/` core package must **never hard-import a drop-in**.  All
drop-in symbols are loaded at runtime via `unicornviz.dropins.load_dropin_symbol()`
which uses `importlib.util.spec_from_file_location`.  This is enforced by
`tests/test_dropin_boundary.py`.

```
unicornviz/app.py
  └── unicornviz/dropins.py   ← ONLY file allowed to reference drop-in paths
        └── importlib.util.spec_from_file_location()
              └── drop-ins/<name>/<module>.py   (loaded at runtime, optional)
```

Every drop-in integration in `app.py` follows this pattern:

```python
def _load_foo_class():
    return load_dropin_symbol('drop-ins/foo-01/foo.py', 'FooController')

try:
    FooController = _load_foo_class()
except Exception:
    FooController = None  # app starts normally without the drop-in
```

Null/fallback controller classes are required for every optional drop-in so
that `app.py` can instantiate a no-op object without branching on `None` in
the hot path.  Null contracts are enforced by `tests/test_null_controller_contracts.py`.

---


The project uses pytest with a baseline suite under `tests/`.

Current baseline coverage includes:

- audio fallback state-machine behavior (`tests/test_audio_capture_fallback.py`)
- VJ API safety when optional PostFX drop-in is absent (`tests/test_vj_api_postfx.py`)
- audio startup/fallback defaults (`tests/test_config_audio_defaults.py`)

Run all tests:

```bash
/home/jj/Repos/unicorn-viz/.venv/bin/python -m pytest
```

Run one module:

```bash
/home/jj/Repos/unicorn-viz/.venv/bin/python -m pytest tests/test_audio_capture_fallback.py
```

Install pre-commit hooks (pytest runs before every commit):

```bash
/home/jj/Repos/unicorn-viz/.venv/bin/python -m pip install pre-commit
/home/jj/Repos/unicorn-viz/.venv/bin/pre-commit install
```

Detailed workflow and policy are in [Testing Guide](testing.md).

Recommended expansion approach:

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

### Commit Gate

Test gate is enforced via local pre-commit hooks in this repository.
Use `pre-commit run --all-files` to run the same checks on demand.

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

### Subsystem drop-ins

| Directory     | Class                 | Purpose                              |
|---------------|-----------------------|--------------------------------------|
| `multi-head-01`| `MultiHeadController`| Multi-monitor display topology & mirroring |
| `control-room-01`| `ControlRoomController`| Secondary operator window with preview, transport, FX, and effect-browser controls |

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
