---
applyTo: "**"
---

# Unicorn Viz — Agent & Coding Standards

This file governs all AI-assisted development on `unicorn-viz`.
Read it in full before writing or reviewing any code.

---

## Project Identity

**unicorn-viz** is a Linux demoscene visualizer written in Python 3.11+.
It renders fullscreen OpenGL 3.3 core effects via `moderngl`, captures live
audio from PipeWire/ALSA via `sounddevice`, supports MIDI control via
`python-rtmidi`, and displays authentic CP437 ANSI art from the BBS artscene.

Primary target: Fedora / Arch Linux, Wayland compositor, PipeWire audio.
Secondary target: any POSIX system running X11 + ALSA.
Windows and macOS support is planned but not yet primary.

---

## Repository Layout

```
unicornviz/          Python package (all source code)
  effects/           One .py file per visual effect (auto-discovered)
  audio/             PCM capture + FFT/beat analysis pipeline
  ansi/              ANSI art parser, CP437 font, GL texture builder
  app.py             Main loop
  config.py          TOML config loader
  hotkeys.py         Keyboard + MIDI → action dispatch
  midi.py            python-rtmidi wrapper
  overlays.py        On-screen HUD
  playlist.py        Effect sequencer
assets/
  ansi/              Generated demo .ANS files
  ansi/acid/         Downloaded ACiD Productions .ANS files (16colo.rs)
  fonts/             Optional font8x16.bin (CP437 8×16 VGA font atlas)
docs/                User guide, developer guide, config reference
tools/               Standalone helper scripts (not part of the package)
config.toml          Runtime configuration
requirements.txt     Pinned Python dependencies
```

---

## Language & Runtime Standards

- **Python 3.11+** — use `tomllib` (stdlib), `match`/`case` where appropriate.
- `from __future__ import annotations` at the top of every module.
- Type annotations on all public functions and class attributes.
- No `from x import *` except inside `__init__.py` re-exports.
- No `global` state; use instance attributes or class attributes.
- Prefer dataclasses / `__slots__` for data-only types.

---

## Code Style

- **PEP 8** + **Black** default line length (88 chars).
- Single quotes for strings unless the string contains a single quote.
- f-strings for string interpolation; no `%` or `.format()`.
- Constants: `UPPER_SNAKE_CASE` at module level.
- Private attributes/methods: single leading underscore (`_name`).
- Protected/internal API: prefix with `_`; double-underscore only for true
  name-mangling needs (rare).
- Avoid `noqa` suppression comments unless genuinely unavoidable; explain why.

---

## Docstring Standards

Every module, public class, and public function must have a docstring.

**Module docstring:** Explain *what* the module does, *why* it exists, and
list any important non-obvious behaviour.  Include usage examples for library
modules.

**Class docstring:** Describe the class responsibility, its lifecycle, and any
thread-safety guarantees.

**Method/function docstring:** One-line summary, then (if needed) a
description of parameters, return value, and exceptions raised.  Do not
repeat the type annotations in the text.

**GLSL shaders embedded as string constants:** Add a brief comment block at
the top of the GLSL string naming its stage, what uniforms it expects, and
what it produces::

    """
    Vertex shader — transforms fullscreen quad vertices to clip space.
    Outputs v_uv in [0,1]² for use by the fragment shader.
    """

---

## Effect Conventions

Every effect must:

1. Live in a single file under `unicornviz/effects/`.
2. Subclass `BaseEffect` from `unicornviz.effects.base`.
3. Set `NAME` (required), `AUTHOR` (optional), `TAGS` (optional list).
4. Use `_init()` for GL resource allocation — **not** `__init__`.
5. Release every GL resource in `destroy()` (VAOs, VBOs, textures, programs).
6. Call `super().update(dt, audio)` at the start of any `update()` override
   so `self.time` is ticked.
7. Never hold a reference to GL objects outside the effect instance.
8. Declare all runtime-tweakable floats in `self.parameters` in `_init()`.

Effects must **not**:
- Do blocking I/O inside `render()` or `update()`.
- Import modules outside the stdlib or requirements.txt at the module level.
- Write to `stdout`/`stderr` directly — use `logging.getLogger(__name__)`.
- Assume a fixed viewport size; always read `self.width` / `self.height`.

---

## GLSL Conventions

```glsl
#version 330  // OpenGL 3.3 core — no ARB extensions

// Uniforms: camelCase with 'i' prefix (Shadertoy-compatible)
uniform float iTime;
uniform vec2  iResolution;
uniform float iBass;

// Vertex inputs: snake_case with 'in_' prefix
in vec2 in_vert;

// Varyings: snake_case with 'v_' prefix
out vec2 v_uv;

// Fragment output: always fragColor
out vec4 fragColor;

// Transform feedback varyings: 'out_' prefix
out vec2 out_pos;
```

- Use `double` precision only when required (e.g., deep Mandelbrot zoom).
- Keep fragment shaders under 150 lines; split complex scenes into helper
  functions with clear names.
- Name SDF functions with the `sd` prefix (`sdSphere`, `sdBox`, etc.).
- Name palette functions plainly (`palette`, `hsvToRgb`).

---

## Audio Reactivity Guidelines

| Signal      | Useful for                                          |
|-------------|-----------------------------------------------------|
| `audio.bass`   | Scale, bloom, camera shake, emission rate        |
| `audio.mid`    | Colour shift, secondary motion, morph blending   |
| `audio.treble` | Sparkle, high-frequency detail, colour temperature |
| `audio.beat`   | One-shot trigger: flash, explosion, camera cut   |
| `audio.fft`    | Per-band bar heights, frequency-mapped geometry  |
| `audio.waveform` | Oscilloscope, ribbon deformation              |

- Scale audio input with a coefficient and `clamp()` — raw values can exceed 1.
- Use exponential decay for beat signals: `beat = max(0, beat - dt * 4.0)`.
- Never block on audio in the render path.

---

## ANSi Art / CP437 Conventions

- Parser: `unicornviz.ansi.loader.ANSIParser` handles all escape sequences.
  Do not parse ANSI manually anywhere else in the codebase.
- Files are expected to be encoded in **IBM CP437** (not UTF-8).  Do not
  decode ANS bytes with Python's default codec.
- SAUCE records are optional; always handle their absence gracefully.
- Art wider than 80 columns is valid.  The viewer clips at the right edge
  without error.
- Downloaded art from 16colo.rs lives in `assets/ansi/acid/` and is committed
  to the repository.  Re-fetch with `tools/fetch_acid_ans.py` if missing.

---

## MIDI Conventions

- `MidiManager` is optional; the app starts and runs normally when
  `python-rtmidi` is not installed or no MIDI device is present.
- The callback fires on the `rtmidi` internal thread.  Only append to a queue
  or write through a lock — never touch `moderngl` objects from the callback.
- CC→parameter mapping lives in `MidiManager._cc_map` (mutable dict).
- Note→action mapping lives in `MidiManager._note_map` (mutable dict).

---

## Security

- Never construct shell commands from user-supplied strings.
- Never `eval()` or `exec()` config values.
- File paths from config are resolved with `pathlib.Path` and must stay within
  the project root or explicitly whitelisted directories.
- Network access is limited to `tools/fetch_acid_ans.py` (download script).
  The main application does **not** make network requests at runtime.
- Do not log MIDI note data at INFO level or above (may contain sensitive
  controller identifiers).

---

## Performance Constraints

- Main loop budget: **16.67 ms** per frame (60 fps).
- `render()` must not allocate Python objects in the hot path.  Pre-allocate
  numpy arrays in `_init()` and reuse them.
- `update()` may do lightweight numpy work but not FFT (that happens in the
  audio thread).
- If a shader takes > 8 ms on a GTX 1060 in a 1080p window, it is too heavy.
  Reduce complexity or add a resolution divisor parameter.

---

## Commit & Branch Conventions

- Branch names: `feature/<name>`, `fix/<name>`, `docs/<name>`.
- Commit messages: imperative mood, 72-char subject, blank line before body.
  - ✅ `Add Raymarcher effect with fog and audio-reactive shockwave`
  - ❌ `Added raymarcher, fixed some stuff`
- Never commit `*.pyc`, `__pycache__/`, `.venv/`, `.DS_Store`, `notes.txt`, or `todo.txt`.
- Screenshots (`unicornviz_*.png`) are gitignored; don't commit them.
- Commit & push after each substantial change; avoid large monolithic commits.

---

## What the Agent Should NOT Do

- Do not add error handling for situations that cannot occur (e.g., checking
  if a numpy array is None immediately after constructing it).
- Do not add type annotations to code you did not write or modify.
- Do not refactor working code unless the task explicitly asks for it.
- Do not add `print()` statements; use the `logging` module.
- Do not create helper utilities or abstractions for one-time operations.
- Do not suggest installing packages not already in `requirements.txt` without
  confirming with the user first.
- Do not generate or guess external URLs (16colo.rs pack names, etc.) — look
  them up via the fetch tools.
- Do not create new `.md` files to document changes (use code comments /
  docstrings instead), unless the user explicitly asks for documentation.

---

## Preferred Libraries

| Purpose          | Library              | Notes                               |
|------------------|----------------------|-------------------------------------|
| OpenGL           | `moderngl`           | Version 5.x API                     |
| Window / input   | `pysdl2`             | SDL2 bindings — not pygame          |
| Numerics / FFT   | `numpy`              | scipy for signal processing if needed |
| Audio capture    | `sounddevice`        | WASAPI / PipeWire / ALSA            |
| MIDI             | `python-rtmidi`      | Optional; guard with try/except     |
| Images           | `Pillow`             | Screenshots only                    |
| Config           | `tomllib`            | stdlib in Python 3.11+              |

Do **not** use: `pygame`, `tkinter`, `wx`, `pyglet`, `arcade`, `OpenGL.GL`
(PyOpenGL), or any GUI framework.

---

## Drop-In Source Policy

- Every drop-in under `drop-ins/` must live in its own dedicated **private**
  GitHub repository.
- The main `unicorn-viz` repository must track drop-ins as git submodules,
  one submodule per drop-in directory.
- Keep `unicornviz/` compatibility shims lightweight and point canonical
  implementations to the corresponding drop-in submodule paths.
- When adding a new drop-in, the agent should automatically create a new
  private GitHub repository for it and wire it into `drop-ins/` as a submodule.
- When modifying a drop-in, the agent must commit and push changes in the
  drop-in's own repository first, then commit and push the updated submodule
  pointer in the main `unicorn-viz` repository.
