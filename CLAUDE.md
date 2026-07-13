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

## Help Icon Assets

- Help icons live in `assets/icons/help/76px/` and `assets/icons/help/152px/`.
- Use `76px` for windows below 3840 pixels wide and `152px` for 3840-wide or
  larger displays.
- Load the source PNGs directly and do not vertically flip or resample them in
  code; the authored orientation is already correct.
- The login/logout rail item is stateful and should switch between
  `login.png` and `logout.png` based on auth state.

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

## Security Findings (bandit / pip-audit)

- **Never automatically remediate bandit or pip-audit findings** without
  explicit owner instruction.  When findings are present, report them clearly
  (tool name, finding ID, file/line, severity, brief description) and stop.
- Do not add `# nosec` annotations, upgrade packages, or refactor code to
  suppress a finding until the owner has reviewed it and explicitly approved
  the remediation approach.
- If a finding is a false positive, say so and explain why — do not silently
  annotate it away.
- For `pip-audit` CVEs, report the affected package, CVE ID, fixed version, and
  whether upgrading it would break any pinned constraints in `requirements.txt`.
  Let the owner decide whether and when to upgrade.

## Spotify Web API Rules

- Refer to Spotify's OpenAPI spec for endpoint paths, parameters, and field
  names; do not guess Spotify endpoint shapes.
- Use Authorization Code with PKCE for local/user-specific Spotify data.
  Do not use the deprecated Implicit Grant flow.
- For local development, use loopback redirect URIs on `http://127.0.0.1`.
  Do not use `http://localhost` or wildcard redirect URIs.
- Request only the minimum scopes needed for the feature being implemented.
- Never store or expose the Spotify Client Secret in client-side/runtime code.
  The local Unicorn Viz runtime should prefer PKCE and operate on Client ID
  only.
- Store Spotify tokens securely in ignored local runtime files and implement
  refresh logic so auth does not silently expire.
- Respect Spotify rate limits: handle HTTP 429, honor `Retry-After`, and use
  exponential backoff instead of tight retry loops.
- Avoid deprecated Spotify endpoints; prefer current playlist/item/library
  endpoints.
- Handle documented Spotify HTTP errors and surface meaningful operator-facing
  feedback.
- Do not cache Spotify content beyond immediate runtime needs, and do not use
  Spotify API data/content to train machine learning models.

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

## Versioning & Release Standards

The project follows **Semantic Versioning 2.0.0** (`MAJOR.MINOR.PATCH`).  The
**core package and every drop-in are versioned independently** — each ships its
own version and moves at its own pace.

**Alpha stage (current).** Every component stays in the `0.MINOR.PATCH` range
until its **first feature-complete, validated release, which is `1.0.0`**.  While
a component is `0.x` its API/config is considered unstable.

**Bump rules.**
- Pre-1.0 (alpha): **never bump MAJOR** (stays `0`).  A user-facing feature bumps
  **MINOR** (and resets PATCH to 0); a fix/tweak bumps **PATCH**.
- 1.0+: **MAJOR** = incompatible API / behaviour / config change; **MINOR** =
  backward-compatible feature; **PATCH** = backward-compatible fix.
- Bump the touched component's version **in the same commit** as the user-facing
  change, and mention the new version in the commit message.

**Where the version lives (single source of truth per component).**
- Core: `unicornviz.__version__` in `unicornviz/__init__.py`.
- Each drop-in: `__version__` in its primary module (e.g. the controller), and
  echoed in the drop-in `README.md` status/version header.

**Changelog.** Each component keeps a short, newest-first **Changelog** section in
its `README.md` — one line per version.  Keep it lightweight during alpha; every
MINOR/PATCH bump adds a line.  Do not restate git history; capture the
user-visible change.

**Agent duties.** When landing a user-facing change to a component, bump that
component's version per the rules above, add the changelog line, and keep the
README header in sync.  Purely internal refactors, tests, or docs need no bump.

## Regression Test Discipline

- Any commit that changes runtime behavior must include corresponding updates to
  regression tests in the same task when practical (add or adjust tests to
  encode the intended behavior).
- Before committing, agents should run the most relevant regression tests for
  touched areas (for example hotkeys/overlays/audio) and report the exact
  failing tests if any fail.
- If any regression test fails at any point, the agent must immediately report
  it to the user with file/test names and stop claiming success until resolved
  or explicitly deferred by the user.
- Do not silently proceed past known red tests; unresolved failures must be
  called out in commit notes and user updates.
- **Never implement production code solely to make pre-existing failing tests
  pass.** If the agent encounters tests it did not write and does not fully
  understand, it must stop, report the failing test names and file paths to the
  user, and wait for explicit instruction before touching either the tests or
  the code they exercise. Guessing at an implementation to clear a red test is
  strictly forbidden — the tests may represent a planned API, a work-in-progress
  contract, or a deliberate design decision from another contributor that the
  agent has no context for.

## Git Hook Discipline

- When git hooks (for example pre-commit hooks) emit warnings or errors, agents
  must treat them as immediate action items: address the findings, rerun hooks,
  and only then proceed to push.
- Do not push with known unresolved hook warnings/errors unless the owner
  explicitly approves a defer for that specific warning/error set.

## Git History Safety (Hard Stop)

- Agents must **never** intentionally detach `HEAD`.
- Agents must **never** do work while in detached `HEAD` state.
- Agents must **never** run `git rebase`.
- Agents must **never** run `git cherry-pick`.
- Agents must **never** run any force-push variant (`git push --force`,
  `git push --force-with-lease`, or equivalent).
- Agents must **never** rewrite branch history in any repository (main repo or
  drop-in submodule repos).
- If an operation would require any of the above, the agent must stop
  immediately and report:
  1. the exact conflict/blocker,
  2. the impacted repository and branch,
  3. the safe non-history-rewrite options,
  then wait for explicit user instruction before taking further git action.

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

## Agent Autonomy — Tool Execution

The agent does **not** need to ask permission before:

- Running any GNU coreutils, shell utilities, or POSIX tools (grep, find, ls,
  awk, sed, cat, diff, wc, etc.)
- Running Python scripts, test suites, or one-off diagnostic commands
  (`python -m pytest`, `python -c "..."`, etc.)
- Reading files, listing directories, or inspecting git status/log/diff

Permission **is required** before any action that deletes, destroys, or
irreversibly overwrites data — including `rm`, `git reset --hard`, force-push,
dropping tables, overwriting committed history, or any destructive shell
invocation.

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

## Session Review Logging

Session review logs are maintained in a separate training clone/repository,
not in this runtime repository.

---

## Architecture Decision Records (ADRs)

Two living ADR documents track the *why* behind key numeric values and design
choices.  **Agents must update the relevant ADR in the same commit whenever
they touch any of the listed triggers.**

### `docs/adr/vj-system.md` — beat detection & profile architecture

Update this file when changing:

- Any constant in `beat_grid.py`: `_V2_COHERENCE_WINDOW`, `_V2_PHASE_TOL`,
  `_BPM_LOCK_CONFIDENCE`, `_BPM_LOCK_RELEASE_CONFIDENCE`, `_SPOTIFYD_WARMUP_S`
  or any similar threshold / window size.
- `tactus_preference_ratio`, `tempo_hold_s`, `phase_tolerance`, or any other
  `[auto_vj]` BPM-detector key in `config.toml`.
- The `set_profile()` method in either tracker class (what the profile applies).
- Adding, removing, or changing any `AudioProfile` in `unicornviz/audio/profiles.py`
  (especially `bpm_prior_mu`, `bpm_prior_sigma`, `bpm_hint_min`, `bpm_hint_max`).
- The choice between BeatTracker v1 and v2 as the active engine.
- The Schmidt trigger gain / release thresholds in `auto_vj.py`.
- The distinction between audio profiles and VJ mood profiles, if the system changes.

### `docs/adr/training-model.md` — training pipeline & model tuning

Update this file when changing:

- `_BPM_LOCK_CONFIDENCE_FLOOR` in
  `drop-ins/training-kit-01/tools/package_training_set.py` (must stay
  in sync with Schmidt trigger thresholds in `auto_vj.py`).
- Any scorecard metric formula: `_score_lock_quality`, `_score_director_quality`,
  or the `beat_lock` coverage calculation.
- The LLM scoring pipeline: provider order, model IDs, prompt rubric, or
  JSON extraction logic in `_score_detector_with_llm`.
- The packaging workflow in
  `drop-ins/training-kit-01/tools/package_training_set.py`: what gets moved,
  naming conventions, or `--session-notes` / `--no-prompt` behaviour.
- The headless training daemon
  (`drop-ins/training-kit-01/tools/training_daemon.py`): infrastructure
  choices, audio routing, or session directory naming.
- The genre / audio profile protocol for training sessions.
- Baseline quality targets or the tuning protocol sequence.
- Any decision that is reverted — add a row to the Superseded Decisions table.

### ADR update format

When adding a new entry, append to the relevant section (or Superseded table).
Include the date, the specific value or decision, and the reason.  Do not
rewrite history — old decisions stay in the Superseded table with a reason.

---

## VJ Training

- Every packaged Auto VJ training bucket under `assets/training/sets/<set>/<bucket>/`
  must include a markdown scorecard at `scorecard.md`.
- Scorecards must include at minimum: row counts, start/end time, detector lock
  behavior summary, director event counts, profile mix, and lock/director
  ratings.
- Use `drop-ins/training-kit-01/tools/package_training_set.py` to package
  corpus + session logs; do not manually move these files when the script can
  perform the operation.
- Packaging must move all files currently under `logs/` (not only JSONL) into
  the destination bucket.
- Packaging must auto-generate `scorecard.md` from the moved corpus files;
  agents then append human interpretation notes as needed.
- When trimming accidental tail data, preserve evidence of the trim boundary in
  the scorecard notes and avoid broad ID-based filtering that can remove valid
  earlier rows.
- Keep each run immutable by using timestamped corpus filenames and packaging
  each run into the next available bucket letter.
