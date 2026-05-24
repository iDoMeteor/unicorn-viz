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

## Documentation SOP

- Canonical user/developer documentation lives under `docs/`.
- Root-level markdown files are reserved for top-level project entry docs only
  (for example `README.md`); planning/debug/audit files belong under
  `docs/planning/`, `docs/debug/`, `docs/audits/`, or `docs/archive/`.
- Every new or moved documentation file must be linked from at least one
  canonical index page (`docs/README.md`, `docs/drop-ins.md`, or a scoped
  section index).
- Complex drop-ins (for example controllers and automation subsystems) should
  keep structured docs in `drop-ins/<name>/docs/` with at least:
  `operations.md`, `configuration.md`, `integration.md`, and
  `troubleshooting.md`.
- Maintained docs should include a short metadata header block with:
  `Owner`, `Status`, and `Last updated`.
- Superseded docs must be marked clearly and moved to `docs/archive/` instead
  of remaining in active locations.
- When code or behavior changes, agents must update the relevant canonical
  docs in the same task whenever practical; avoid creating duplicate docs that
  restate existing guidance.

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
- Do not create new `.md` files for routine code-only changes (use code
  comments / docstrings instead), unless the user explicitly asks for
  documentation or the task is explicitly documentation governance.

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

## config.toml Editing Policy

The owner makes their own edits to `config.toml` at any time.

- **Never modify or overwrite the user's existing `config.toml` settings without
  explicitly asking first.**
- Adding new commented-out sections (e.g., to document a new drop-in's options)
  **is permitted without asking**, as long as the addition is clearly commented
  and does not change any existing value.
- Removing, reordering, or changing any uncommented value always requires
  explicit user confirmation.

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
- **Every drop-in that introduces hotkeys must add its control lines to
  `HELP_TEXT` in `unicornviz/overlays.py`** so they appear in the `H` help
  overlay automatically.  This is the single source of truth for all key
  bindings; do not document keys anywhere else (no separate README sections,
  no docstrings listing keys).

---

## Drop-In Independence Rules

The `unicornviz/` core package must **never hard-depend** on any drop-in.
Every reference to drop-in code must follow this SOP:

1. **All drop-in symbols must be loaded via `load_dropin_symbol()`** in
   `unicornviz/dropins.py` — never via a direct import.
2. **Every `load_dropin_symbol()` call must be wrapped in `try/except`** with
   a graceful `None` or fallback value so the app starts cleanly when the
   drop-in submodule is absent.
3. **The fallback path must be fully functional** — missing a drop-in must
   degrade gracefully (e.g., feature disabled, null controller used), never
   crash or raise at startup.
4. When adding a new optional drop-in integration to core, follow the existing
   pattern in `app.py`: a private loader function `_load_<name>_class()` that
   raises on missing file, called inside a `try/except` block that sets the
   attribute to `None` on failure.
5. After making any change to the core–drop-in boundary, verify independence by
   confirming all three load sites (`multi-head-01`, `webcam-01`,
   `streaming-01`) still have `try/except` guards and no new bare imports of
   drop-in paths have been introduced.

---

## Public Runtime Surface Rules

Runtime-facing code must use the project's public control surfaces instead of
reaching into unrelated modules' private fields.

1. **Drop-ins and system controllers must prefer `app.vj_api` first.**
  If a controller needs app/runtime functionality, add a small capability to
  `VJApi` before touching `app._private` state directly.
2. **Core cross-module callers should prefer public `App` / `Overlays` methods
  and properties over direct underscore access.**
  Example: `HotkeyHandler` should call an `App` wrapper such as
  `apply_random_zoom()` or `request_exit()` instead of mutating
  `app._zoom_randomized` or `app._running` itself.
3. **`# noqa: SLF001` is owner-module-only.**
  It is acceptable inside the modules that intentionally own the runtime state
  (`unicornviz/app.py`, `unicornviz/vj_api.py`, and equivalent low-level
  owner modules), but should not appear in live drop-in code or in unrelated
  runtime callers when a public surface can reasonably be added.
4. **When a new runtime behavior needs private state in more than one place,
  stop and promote that behavior to a public shim.**
  Prefer a thin method/property on `App`, `VJApi`, or `Overlays` over copying
  underscore-field access to multiple call sites.
5. **Pre-release policy:** live runtime code under `drop-ins/` and
  cross-module callers under `unicornviz/` should be kept free of direct
  `app._...` / `_app._...` access except in the owner modules that define the
  canonical state.

This rule exists to keep drop-ins independently testable, reduce coupling, and
let the runtime surface stabilize before v1.0.

---

## Effect Randomization Requirements

Every visual effect must produce a **visually distinct appearance each time it
becomes active** (on first load and on every scene transition back to it).
`audio_spectrum.py` and `system_monitor.py` are explicitly exempt.

**What `BaseEffect` already provides for free:**
- `self.seed` — unique per instance from `np.random.SeedSequence()`
- `self.rng` — `np.random.default_rng(self.seed)` — use this for all
  per-instance randomisation; do not call `random` or `np.random` directly.
- `self.time` — initialised to `rng.uniform(0.0, 10_000.0)` so purely
  time-driven shaders already start at a random phase.

**What effects must add themselves:**
- Any parameter that is visible at frame 0 and does not vary purely with
  `iTime` must be randomised in `_init()` using `self.rng`.  Examples:
  - Colour/palette offset (`palette`, `hue_shift`, `color_phase`)
  - Starting angle or rotation
  - Discrete mode / style selection
  - Intensity or density parameters with a meaningful visible range
- Media showcase effects (images, videos, textures) must start at a random
  index into their content list so the same asset is not always shown first.
- Simulation effects that build state over time (fire, water, particles) should
  seed their initial state with `self.rng` so runs never look identical at t=0.

**Rule of thumb:** if two runs of the effect, viewed side-by-side from frame 0,
are indistinguishable for the first several seconds, add startup randomisation.

---

## Session Review Logging (Required)

When an agent reviews an Auto VJ session (for example by analyzing
`logs/autovj-*.jsonl`), it must append one line to:

- `drop-ins/auto-vj-01/SESSION_TRAINING_LOG.md`

Required one-line format:

- `YYYY-MM-DD | session=<log-file-or-id> | style=<genre/mix tag> | lock=<1-5> | director=<1-5> | notes=<optional short summary>`

Rules:

- Add exactly one new line per reviewed session.
- Keep `notes` concise and optional; use it when a short summary adds value.
- Do not replace prior entries; only append.
- If no session log exists yet, use the best available session identifier in
  the `session=` field.
