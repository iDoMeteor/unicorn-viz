# Control Room Debug Handoff

## Goal

Ship `drop-ins/control-room-01` as a stable in-process operator window for
Unicorn Viz.

The intended runtime behavior is:

- the audience-facing main window keeps rendering normally
- the control room opens on a separate display/window
- the control room can be toggled at runtime without corrupting the main GL
  presentation path
- closing the control room does not destabilize hotkeys, resizing, or display
  mode switching

## Current Status

The control-room drop-in loads through the shared drop-in loader and its help
entries are now discoverable, but the runtime behavior is still unstable on the
owner's Linux/X11 machine.

Observed symptoms across recent runs:

- control-room window opens but is black
- audience-facing window can become visually corrupted
  Example reported by owner: effect visible only in a diagonal/top-left region
- after closing the black control-room window, later hotkey/display-mode actions
  can leave the app in a bad GL state
- one captured crash path ends in `_moderngl.Error: cannot create texture`

## Environment Snapshot

- OS: Linux
- SDL video driver in logs: `x11`
- Main renderer: fullscreen OpenGL 4.6 core profile via `moderngl`
- Control room: secondary SDL window in the same process
- Webcam subsystem may be retrying V4L2 devices in the background, but current
  evidence does not point to webcam as the primary cause

## Key Logs / Evidence

Recent logs reviewed during debugging:

- `logs/unicornviz_20260520_162315.log`
- `logs/unicornviz_20260520_162354.log`
- `logs/unicornviz_20260520_162438.log` (empty after crash)

Notable evidence:

- `logs/unicornviz_20260520_162315.log:667`
  `Control room window opened on display 1 (1920x1080, renderer=software)`
- `logs/unicornviz_20260520_162354.log:669`
  `Control room window opened on display 1 (1920x1080, renderer=software)`

Owner-reported crash trace from a failing run:

```text
CRITICAL [__main__] Uncaught exception
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "/home/j/Repos/unicorn-viz/unicornviz/__main__.py", line 226, in <module>
    main()
  File "/home/j/Repos/unicorn-viz/unicornviz/__main__.py", line 222, in main
    app.run()
  File "/home/j/Repos/unicorn-viz/unicornviz/app.py", line 1554, in run
    hotkeys.handle(event.key.keysym.sym, event.key.keysym.mod)
  File "/home/j/Repos/unicorn-viz/unicornviz/hotkeys.py", line 763, in handle
    mode = a.set_display_mode('single')
  File "/home/j/Repos/unicorn-viz/unicornviz/app.py", line 2389, in set_display_mode
    self._on_resize(w_i.value or self._width, h_i.value or self._height)
  File "/home/j/Repos/unicorn-viz/unicornviz/app.py", line 2241, in _on_resize
    self._fbo_a = self._make_fbo()
  File "/home/j/Repos/unicorn-viz/unicornviz/app.py", line 1190, in _make_fbo
    tex = self._ctx.texture((self._render_width, self._render_height), 4)
_moderngl.Error: cannot create texture
```

Interpretation:

- the crash is not inside the control-room code itself
- the crash occurs later when the main app tries to rebuild FBOs
- that suggests the secondary-window/control-room path is still perturbing the
  main GL/display-state path enough to poison a later resize/display-mode op

## Relevant Code Surfaces

Main runtime:

- `unicornviz/app.py`
  - `App._create_control_room()`
  - `App.toggle_control_room()`
  - control-room startup scheduling in `run()`
  - `_on_resize()` and `_make_fbo()`
  - display-mode switching in `set_display_mode()`

Hotkeys:

- `unicornviz/hotkeys.py`
  - `Ctrl+Alt+O`
  - `Ctrl+Alt+0`
  - display-mode key handling (`X` branch)

Drop-in loading:

- `unicornviz/dropins.py`
  - `_load_module_from_file()`
  - `discover_dropin_help_entries()`

Control room drop-in:

- `drop-ins/control-room-01/control_room.py`

## What Was Broken Initially

### 1. Shared loader broke dataclass-based drop-ins

`control_room.py` uses `@dataclass`. The shared drop-in loader executed the
module before registering it in `sys.modules`, which caused dataclass internals
to fail.

Effects of that bug:

- `load_dropin_symbol('control-room-01/control_room.py', 'ControlRoomController')`
  could fail
- `discover_dropin_help_entries()` could skip the module entirely

### 2. Control-room help was not advertised

The drop-in originally had no `HELP_ENTRIES`, so even once loading worked the
help overlay had nothing to show.

### 3. `Ctrl+Alt+0` collided with the `0` effect shortcut path

The zero-key effect selection branch in `hotkeys.py` could still win in some
flows. That made the reported behavior look random and was especially confusing
while debugging runtime instability.

## Attempted Fixes So Far

### Main repo commits

- `7f530f6` — initial control-room subsystem support landed
- `1c1d8de` — fixed loader/discovery and added planning follow-ups
- `cc3c5a9` — added control-room follow-ups to drop-in planning
- `3276548` — deferred startup and stopped `Ctrl+Alt+0` collisions
- `27ee1f8` — delayed config-enabled startup further by several frames

### Control-room submodule commits

- `b16450d` — initial operator window implementation
- `4d2db89` — made control room discoverable and safer to place
- `d822a90` — preferred isolated software renderer and logged backend
- `23e0586` — clarified toggle aliases in help text

## Detailed Attempt Log

### Attempt A — make the control room load at all

Changes:

- fixed shared loader in `unicornviz/dropins.py` to register modules in
  `sys.modules` before execution
- verified:
  - help-entry discovery now returns Control Room entries
  - `load_dropin_symbol(...)` now returns `ControlRoomController`

Result:

- solved the loader/discovery problem
- did not solve the black-window/runtime corruption problem

### Attempt B — avoid opening on the same single-display audience output

Changes:

- added fallback logic in `control_room.py` so the control room avoids the same
  display as the audience `single` output when multiple displays exist

Result:

- solved the obvious “window hidden behind the main fullscreen output” case
- did not solve the black-window/runtime corruption case

### Attempt C — add runtime toggles and help entries

Changes:

- added `HELP_ENTRIES` in `control_room.py`
- added `Ctrl+Alt+O` and later explicit `Ctrl+Alt+0` handling in
  `hotkeys.py`
- exposed `toggle_control_room()` through `VJApi`

Result:

- solved discovery/UX issues
- did not solve rendering corruption

### Attempt D — use SDL software renderer instead of accelerated renderer

Changes:

- changed control room to prefer SDL software renderer
- logs now show `renderer=software`

Result:

- black window still reported
- startup/close-related corruption still reported

### Attempt E — defer startup until after the first audience frame

Changes:

- stopped creating the control room during early startup
- instead scheduled creation after audience frames had already begun presenting
- then increased the delay to several frames

Result:

- logs confirm delayed startup scheduling and later control-room creation
- owner still reports black control room and later crash after close/interact

### Attempt F — remove SDL renderer/texture path entirely

Current attempt in workspace:

- removed the control room’s SDL renderer/texture usage
- switched presentation to plain SDL window-surface blitting via
  `SDL_GetWindowSurface()` + `SDL_BlitScaled()` + `SDL_UpdateWindowSurface()`
- added a clamp for app render-target size based on `GL_MAX_TEXTURE_SIZE`
  to reduce the chance of immediate `_moderngl.Error: cannot create texture`

Validation completed so far:

- `control_room.py` imports cleanly
- dummy-driver smoke test can construct and present one frame through the new
  surface path
- `app.py` imports cleanly after the patch

This attempt is the latest unverified-on-owner-machine runtime change.

## Current Best Hypothesis

The control room is still perturbing the main SDL/GL runtime because a second
SDL window is being created inside the same process and same SDL video setup as
the fullscreen OpenGL audience window.

The strongest remaining hypotheses are:

1. Creating any second SDL-managed presentation surface in this runtime is
   destabilizing the main fullscreen GL window on this X11/Mesa stack.
2. Closing the control-room window leaves the main app in a subtly corrupted
   SDL window/display state, which only explodes later when the app rebuilds
   FBOs during display-mode switching or resize.
3. The black-window symptom suggests the control-room presentation path itself
   may not be making it to the display reliably even when the window exists.

## Recommended Next Steps

### Path 1 — verify the new window-surface approach on the owner machine

Retest with the latest code and answer these questions first:

- does the control room still open black?
- does the audience window still corrupt when the control room is opened?
- after closing the control room, does pressing arbitrary keys still destabilize
  the main app?
- what does the newest log say about control-room creation timing and backend?

If this path works, keep iterating in-process.

### Path 2 — instrument the main window state around control-room open/close

If issues remain, add temporary logs for:

- `SDL_GetWindowSize(self._window, ...)` before and after control-room open
- `SDL_GL_GetDrawableSize(self._window, ...)` before and after control-room open
- `_width`, `_height`, `_render_width`, `_render_height` before any `_make_fbo()`
- `GL_MAX_TEXTURE_SIZE` and the requested FBO size when `_make_fbo()` runs
- main-window `SDL_WINDOWEVENT_*` values around control-room close/focus changes

The goal is to prove whether the main window is being resized/invalidated behind
the app’s back.

### Path 3 — temporarily disable display-mode hotkeys after control-room close

If the post-close crash remains tied to resize/display-mode operations, a useful
triage step is to temporarily ignore `X`-family display-mode hotkeys for a short
cooldown after control-room close. That would not be a final fix, but it would
help isolate whether close/focus teardown is the immediate trigger.

### Path 4 — escalate architecture if in-process remains unstable

If the window-surface approach still fails on the owner machine, strongly
consider abandoning the in-process SDL second window and pivoting to one of:

- a separate helper process for the control room using WebSocket/local IPC
- an embedded HTTP/WebSocket control surface opened in an external browser/app
- an in-process control room that does not own a second SDL window at all
  (for example, a toggleable overlay on the main window during development)

At that point, the evidence would suggest the main blocker is not the control
room UI code, but the multi-window SDL/GL architecture choice itself.

## Files Added For Planning / Follow-Up

- `drop-in-planning.md`
  - Spotify drop-in planning
  - Mixxx/xwax/Giada drop-in planning
  - control-room layout + Decks/Cues/Timing follow-ups

## Minimal Handoff Summary

What is definitely fixed:

- shared drop-in loading for dataclass-based modules
- control-room help discovery
- explicit control-room hotkey routing for `Ctrl+Alt+O` and `Ctrl+Alt+0`

What is not yet solved:

- stable operator-window rendering on the owner’s Linux/X11 machine
- preventing the main OpenGL audience window from being destabilized after the
  control room opens/closes

Most valuable next experiment:

- test the latest window-surface-based control-room build on the owner machine
  before spending more time on startup timing heuristics
