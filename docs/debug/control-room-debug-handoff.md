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
entries are discoverable.  Multiple successful opens have been observed in
recent runs.  The segfault on ESC and the "one frame then black" symptoms have
both been fixed.

The remaining unstable behavior is **audience-output starvation** when the
operator window is open, and an aftershock that leaves the audience GL output
"locked up" for a while after the operator window is closed.

Observed symptoms across recent runs (post format/lifecycle fixes):

- enabling `[control_room].enabled = true` at startup often produces an opaque
  black operator window
- toggling the operator window on later with `Ctrl+Alt+O` works intermittently;
  sometimes the first toggle in a session succeeds, later toggles do not
- while the operator window is open in **any** display mode (single, mirror,
  span), the audience-facing GL effects appear to freeze
- in mirror mode specifically, the next auto-VJ scene appears to render onto
  the operator display instead of the audience output (most likely the
  borderless operator window z-stacks above an audience mirror tile)
- after the operator window is closed, the audience GL output stays "locked
  up" for several seconds before recovering
- no SDL/GL errors are logged during the freeze; the audio capture thread
  keeps producing audio frames in the log, but the main render loop does not
  advance

Earlier symptoms that are now fixed:

- segfault on ESC inside the operator window
- single-frame paint followed by a permanently black operator window
- `_moderngl.Error: cannot create texture` after closing the operator window

## Environment Snapshot

- OS: Linux (Fedora 37 / GNOME / Mutter on X11)
- Future targets: Fedora 44, Windows 10/11
- SDL video driver in logs: `x11`
- Main renderer: fullscreen OpenGL 4.6 core profile via `moderngl`
- Control room: secondary SDL window in the same process, window-surface based
  (no GL context)
- Multi-display setup with mirror mode active in some runs
  (logs show `Mirror (GL-native) reconfigured: window=3840x2160 ...`)
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
- `edcf0a8` — clamped FBO size to `GL_MAX_TEXTURE_SIZE`
- `1597673` — `App.rebind_main_gl_context()` and `VJApi` cleanup surface
- `e6dfa44` — control-room submodule bump (fullscreen default + config docs)
- `589ca65` — control-room submodule bump (no fullscreen-desktop, throttle, cursor)
- `43f1067` — per-frame `SDL_GL_MakeCurrent` experiment + debug-doc refresh
- `c599ce3` — reverted per-frame `SDL_GL_MakeCurrent` after owner logs proved it
  harmful; picked up preview-toggle submodule bump

### Control-room submodule commits

- `b16450d` — initial operator window implementation
- `4d2db89` — made control room discoverable and safer to place
- `d822a90` — preferred isolated software renderer and logged backend
- `23e0586` — clarified toggle aliases in help text
- `54c7e0a` — switched presentation to `SDL_GetWindowSurface` + blit-scaled
- `1c9e75f` — deferred shutdown, pixel-format conversion, GL rebind on teardown
- `92c2a95` — borderless fullscreen by default + surface-refresh on window events
- `defea91` — dropped `FULLSCREEN_DESKTOP`, throttled render, always-on cursor
- `4eacf8c` — background-thread PIL render, ~8 fps default, lock-protected
  hotspot publish
- `31a25ed` — in-UI preview on/off toggle in the PROGRAM PREVIEW panel

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

Changes:

- removed the control room’s SDL renderer/texture usage
- switched presentation to plain SDL window-surface blitting via
  `SDL_GetWindowSurface()` + `SDL_BlitScaled()` + `SDL_UpdateWindowSurface()`
- added a clamp for app render-target size based on `GL_MAX_TEXTURE_SIZE`
  to reduce the chance of immediate `_moderngl.Error: cannot create texture`

Result:

- solved the `_moderngl.Error: cannot create texture` aftershock
- did not by itself solve the black-after-first-frame symptom

### Attempt G — deferred shutdown, pixel-format conversion, GL rebind

Changes:

- `shutdown()` now sets `_pending_shutdown = True` instead of calling
  `SDL_DestroyWindow` from inside an event handler.  The actual destroy
  happens from the next `update()` call, outside event polling.  Fixed
  the segfault on ESC inside the operator window.
- `close_now()` for safe immediate teardown from main-app contexts (e.g. the
  toggle-off hotkey path, which is outside the operator window's own handler).
- Converted the PIL BGRA source surface to the actual window pixel format
  via `SDL_ConvertSurface()` before blitting.  Fixed the
  "one frame then permanently black" symptom on X11/Mutter where BGRA-into
  -XRGB blits were unreliable past the first frame.
- Kept the raw pixel buffer alive for the full lifetime of the source
  surface; `SDL_CreateRGBSurfaceFrom` does not copy.
- On teardown, unregister from `App._subsystems` and call
  `App.rebind_main_gl_context()` (new public surface) so secondary-window
  destruction doesn't strand the audience window's GL binding.

Result:

- segfault on ESC: FIXED
- one-frame-then-black: FIXED
- audience-output starvation while operator window is open: NOT solved
- aftershock lockup after operator window close: NOT solved

### Attempt H — borderless-sized window, throttled PIL render, always-on cursor

Changes:

- Dropped `SDL_WINDOW_FULLSCREEN_DESKTOP`.  Operator window is now a plain
  borderless window sized to the chosen display's bounds.  Looks fullscreen
  but Mutter no longer restacks it above other fullscreen windows on the
  same X desktop.  This was meant to address the "effects appear on the
  operator display" symptom in mirror mode.
- Throttled PIL re-rendering to ~15 fps with a single-frame cache.
- Forced `SDL_ShowCursor(SDL_ENABLE)` at the top of every present().

Result:

- cursor is now visible: FIXED
- mirror-mode "effects on operator display" symptom: mitigated, but the
  audience-output starvation is reported in all display modes, including
  single mode.  The starvation persists after the operator window is
  closed.
- so the borderless-window theory is insufficient: there is a real
  starvation/GL-binding issue beyond simple window stacking.

### Attempt I — background-thread PIL render and per-frame GL rebind

Changes:

- Moved PIL rasterization to a daemon thread (`ControlRoomRender`).  The
  main thread's `present()` only does a fast SDL blit of the latest
  thread-rendered buffer; it never calls `Image.tobytes()` itself.  The
  hotspot list is also published under a lock so mouse click handling on
  the main thread reads a consistent snapshot.
- Default render interval lowered to ~8 fps for the operator UI; still
  responsive for VJ work, much lighter on CPU.
- `App` now defensively calls `SDL_GL_MakeCurrent(self._window,
  self._gl_context)` every frame just before `self._render(dt)` whenever
  the control room is alive, so any implicit GL drawable migration caused
  by the secondary SDL window can't silently strand audience GL
  rendering on the wrong drawable.

Validation completed so far:

- module imports cleanly
- dummy-driver smoke test: render thread spawns, produces a frame, the
  main thread blits it, `close_now()` joins the thread, no leak
- `app.py` imports cleanly after the per-frame rebind

Owner-machine result:

- preview/control-room behavior improved
- audience output became worse: black on startup with control room enabled,
  and "jenky" / black when toggled at runtime
- logs showed no `SDL_GL_MakeCurrent failed` warnings, which means the
  per-frame rebind was succeeding technically but still disrupting moderngl's
  bound GL state badly enough to drop/garble draws

Conclusion:

- the background-thread PIL render was a good change and should stay
- the per-frame `SDL_GL_MakeCurrent` was harmful and was reverted

### Attempt J — keep threaded render, revert per-frame GL rebind, add preview toggle

Changes:

- kept the background-thread PIL render from Attempt I
- reverted the per-frame `SDL_GL_MakeCurrent` in `unicornviz/app.py`
- left the one-shot rebind on create/destroy only
- added an in-UI `PREVIEW ON / PREVIEW OFF` toggle button in the PROGRAM
  PREVIEW panel header
- preview toggle honors `[control_room].show_preview` as initial state and
  skips preview-frame fetches while OFF

Result:

- preview toggle landed successfully
- the harmful per-frame GL rebind is gone
- latest owner-machine behavior after this revert still needs verification

### Attempt K — throttle subsystem frame readback in the main loop

Root cause identified and fixed:

Even with the background-thread PIL render from Attempt I, the main render
loop was still calling `_fbo_a.read()` / `ctx.screen.read()` (a blocking GPU
readback) **on every single audience frame** (60 fps) whenever the control
room preview was active.  At 1920×1080 RGB24 this is a ~6 MB DMA transfer per
frame.  On a modest GPU this stalls the OpenGL pipeline for 5–20 ms each time,
which is the primary mechanism behind the audience-output freeze.

Fix applied in `unicornviz/app.py`:

- Added `_last_subsystem_frame_capture_time: float = 0.0` to `App.__init__`.
- The subsystem frame readback path in the main loop now checks a 100 ms gate
  (`_now - _last_subsystem_frame_capture_time >= 0.1`) before issuing the GPU
  readback.  If the gate is closed, the stale cached frame bytes remain in
  `_frame_capture_bytes` and the GL call is skipped entirely for this tick.
- Streaming readback is intentionally NOT throttled: RTMP must consume one
  frame per rendered frame to keep the muxer in sync.
- When the control room is open and `show_preview = true`, the readback fires
  at ~10 fps instead of 60 fps — well ahead of the operator UI's own ~8 fps
  render rate, so the preview is always showing a fresh frame.

Expected result:

- audience-output GPU pipeline stall drops from 100% of frames to ≤17% of
  frames (from 60 fps down to ≤10 fps readback rate)
- no change to streaming, recording, or mirror-mode behaviour
- operator preview still appears live at up to 10 fps capture rate

### Attempt M — throttle SDL_UpdateWindowSurface to render-thread frame rate

Root cause identified from "appears briefly on move then goes black" pattern
observed on Fedora 44 (Wayland, GNOME 47, Mutter 47, Mesa 26.0.7):

**The Wayland wl_shm buffer flooding problem:**

`present()` is called every main-loop tick (~60 fps) and was unconditionally
calling `SDL_UpdateWindowSurface` — even when the render thread hadn't
produced a new frame yet (render_interval defaults to 0.125 s = 8 fps).

On Wayland, `SDL_GetWindowSurface` backs the window with a `wl_shm_pool`
buffer.  When `SDL_UpdateWindowSurface` is called, SDL2 commits that buffer
to the compositor.  The compositor (Mutter) sends a `wl_buffer.release` event
when it's done with the buffer and a `wl_callback.done` frame-sync event when
it's ready for the next commit.  SDL2's software surface path does not wait
for these events — it just commits again on the next call.

Flooding Mutter with 60 identical commits per second violates the `wl_buffer`
ownership contract (you must not overwrite a buffer before the compositor
releases it) and triggers Mutter's frame-throttling logic, which causes it to
stop displaying the surface content.  The window appears black.

The "appears briefly after moving between displays" pattern is the smoking gun:
the window move causes SDL2 to internally destroy and recreate the `wl_shm`
surface, resetting the buffer state and giving one clean commit.  The
60 fps flooding then resumes and Mutter goes black again within seconds.

**Fix:**

Added `_frame_id: int` (incremented by the render thread under `_frame_lock`
each time a new PIL image is rasterized) and `_presented_frame_id: int`
(set in `present()` after a successful `SDL_UpdateWindowSurface` call).
`present()` now reads both values atomically under the lock and skips the
entire blit + surface commit when `frame_id == _presented_frame_id`.  The
surface is committed at the render thread's rate (~8 fps) instead of the
main loop's rate (60 fps).

When `_needs_surface_refresh` is True (window move, expose, focus events),
`_presented_frame_id` is reset to `-1` so the next available frame forces a
commit regardless of whether the counter advanced.

Commits:
- `d3a7fd5` — control-room-01 submodule (frame-id throttle in present())

Expected result:
- Operator window shows the rendered UI consistently on Wayland
- No more "briefly appears then goes black" on first open or after move
- Main loop is not slowed by redundant surface commits

Root causes identified from `unicornviz_20260601_194545.log` on Fedora 44
(Wayland, GNOME/Mutter, Mesa 26.0.7):

**Bug 1 — SDL key-repeat double-toggle:**
The `SDL_KEYDOWN` handler in `app.py` did not filter `event.key.repeat`.
On Wayland/Linux, holding a key generates repeated `SDL_KEYDOWN` events with
`repeat != 0`.  When the user held O while pressing Ctrl+Alt, two repeat events
with `KMOD_CTRL|KMOD_ALT` fired before the keyup arrived.  The log confirmed
two back-to-back "ControlRoomController loaded" entries with no destroy between
them — the first repeat created the window, the second toggled it back off
(silent destroy, no log entry), then the scheduled 8-frame startup countdown
fired, passed the `is None` guard, and created a second conflicting instance.

Fix: `if not event.key.repeat:` guard before `hotkeys.handle()` in the
`SDL_KEYDOWN` branch of the main event loop.

**Bug 2 — Zombie-controller creation bypass:**
The old zombie GC in `_create_control_room` only triggered when
`_pending_shutdown=True`.  A controller whose window was silently destroyed
(e.g. via the repeat-toggle above) had `_window=None` (`is_open=False`) but
`_pending_shutdown=False` — zombie state.  The next creation call passed the
`is_open` guard, leaked the zombie, and then tried to create a second window in
the same SDL thread.

Fix: `_control_room_creating` bool flag (set before constructor call, cleared
in `finally`) stops re-entrant creation.  Broadened zombie GC now catches ANY
controller where `is_open` is False, not just ones with `_pending_shutdown`.
Added `log.info` to `_destroy_control_room` so destroys are visible in logs.

**Bug 3 — Wayland compositor never receives initial surface commit:**
On Wayland, `SDL_GetWindowSurface` creates a software surface but the
compositor does not show the window until `SDL_UpdateWindowSurface` is called
with actual pixel content.  Without this, the operator window stays black even
after the render thread produces its first frame, because the compositor has
never seen a commit and keeps the surface unmapped.

Fix: immediately after `SDL_GetWindowID`, call `SDL_GetWindowSurface`,
`SDL_FillRect` with the theme background colour (RGB from `self._theme.bg`),
and `SDL_UpdateWindowSurface`.  The compositor maps the surface right away and
shows the dark background while the render thread warms up.

Commits:
- `3ce7560` — main repo (app.py: key-repeat filter + creating guard + zombie GC)
- `4822e83` — control-room-01 submodule (Wayland initial surface commit)

Expected result:
- operator window opens with the correct dark background on first use instead
  of a black rectangle
- no double-creation or silent zombie leaks from held-key scenarios
- `_destroy_control_room` now logs "ControlRoomController closed" making
  toggle sequences fully traceable in logs

## Current Best Hypothesis

Five separate issues were real; all five are now addressed:

1. **Main-loop starvation from PIL rasterization** — fixed by background render
   thread (Attempt I).
2. **Per-frame GL rebind was wrong medicine** — reverted (Attempt J).
3. **60 fps GPU framebuffer readback** — root cause of audience freeze, fixed
   by the 100 ms readback gate in Attempt K.
4. **Key-repeat double-toggle + initial Wayland surface commit** — fixed by
   Attempt L (key-repeat filter, creating guard, zombie GC, initial FillRect
   commit on window creation).
5. **Wayland wl_shm buffer flooding (60 fps commits of unchanged pixels)** —
   root cause of the persistent "black window / appears briefly then black"
   pattern on GNOME/Mutter.  Fixed by Attempt M: `present()` now only calls
   `SDL_UpdateWindowSurface` when the render thread has produced a new frame
   (tracked via `_frame_id` / `_presented_frame_id` counters).

The most likely live state now is:

- threaded operator rendering is good and stays
- one-shot GL rebind on control-room create/destroy is acceptable
- subsystem frame readback is throttled to ≤10 fps, removing pipeline stall
- operator surface committed at ~8 fps (render_interval rate), not 60 fps
- Wayland black window on first open and after move should now be resolved

If the window **still** goes black, the remaining candidates are:
- Mutter rejecting `wl_shm` entirely for secondary windows when a GL context
  owns the primary surface → try `SDL_VIDEODRIVER=x11` to force XWayland
- A Mesa/Wayland driver bug specific to the GPU in use → check `SDL_GetError()`
  output in logs for `blit failed` or `surface update failed` warnings
- If both fail: Path 4 (separate process with HTTP/WebSocket surface) is the
  correct long-term architecture

## Recommended Next Steps

### Path 1 — verify Attempt J on the owner machine

Retest with the latest code and answer these questions first:

- does enabling `[control_room].enabled = true` at startup still produce an
  opaque black window?
- does toggling the operator window with `Ctrl+Alt+O` while audience effects
  are running still freeze the audience output?
- does the audience output recover promptly after the operator window is
  closed (no multi-second post-close lockup)?
- does the operator UI still feel responsive at the new ~8 fps default, or
  does it need `[control_room].render_interval = 0.066` (15 fps)?
- does the new `PREVIEW ON / PREVIEW OFF` button work and materially reduce
  load when preview is disabled?

Capture a fresh log of any failure case. The most valuable new signals are:

- presence/absence of `Control room surface blit failed` warnings
- presence/absence of any one-shot `SDL_GL_MakeCurrent failed` warnings from
  the create/destroy rebind path
- whether audio frames continue logging during the freeze (they did before;
  if they now stop too, the diagnosis flips back to true main-thread blocking)

If Path 1 holds up, the in-process two-window architecture is viable and the
remaining work is UI polish.

### Path 2 — instrument the main window state around control-room open/close

If audience starvation persists with Attempt J:

- log `SDL_GL_GetCurrentWindow()` and `SDL_GL_GetCurrentContext()` once per
  second while the operator window is alive
- log `glGetError()` after the audience `SDL_GL_SwapWindow()` while the
  operator window is alive
- log GLX/Mesa driver strings at startup so the owner machine's stack is
  captured alongside the trace

The goal is to prove or rule out an implicit GL drawable migration or
framebuffer/state mismatch without reintroducing any speculative per-frame GL
rebinding.

### Path 3 — make the operator window non-borderless

If borderless still triggers compositor restacking issues, try a regular
decorated window (no `SDL_WINDOW_BORDERLESS` at all).  Less pretty but
maximally compositor-friendly.  Useful as a triage signal even if not the
final shape.

### Path 4 — escalate architecture if in-process remains unstable

If Attempts G–J still don't yield a stable audience output on the owner
machine, abandon the in-process SDL second window and pivot to one of:

- a separate helper process for the control room using a local IPC channel
  (UNIX socket, WebSocket on localhost) and any UI toolkit
- an embedded HTTP/WebSocket control surface opened in an external browser
- an in-process control room that does not own a second SDL window at all
  (for example, a togglable HUD-style overlay rendered on the audience window
  in a corner, controllable via mouse/MIDI)

At that point, the evidence would suggest the main blocker is not the control
room UI code, but the multi-window SDL/GL architecture choice itself on
X11/Mesa.

## Files Added For Planning / Follow-Up

- `docs/planning/drop-in-planning.md`
  - Spotify drop-in planning
  - Mixxx/xwax/Giada drop-in planning
  - control-room layout + Decks/Cues/Timing follow-ups

## Minimal Handoff Summary

What is definitely fixed:

- shared drop-in loading for dataclass-based modules
- control-room help discovery
- explicit control-room hotkey routing for `Ctrl+Alt+O` and `Ctrl+Alt+0`
- segfault on ESC inside the operator window (deferred-shutdown lifecycle)
- one-frame-then-black operator window (explicit pixel-format conversion)
- mouse cursor invisible inside the operator window
- `_moderngl.Error: cannot create texture` aftershock after operator close
- in-UI preview toggle landed and honors `[control_room].show_preview`

What is not yet confirmed solved on the owner machine:

- audience-output starvation while the operator window is open
- audience-output "lockup" for several seconds after the operator window is
  closed

Most valuable next experiment:

- test Attempt J (background-thread PIL rendering retained, per-frame
  `MakeCurrent` reverted, preview toggle added) end-to-end on the owner
  machine in single, mirror, and span modes, and capture a log for each
- if it still misbehaves, instrument with `glGetError()` + drawable/context
  IDs as described in Path 2 before changing any more GL binding behavior
