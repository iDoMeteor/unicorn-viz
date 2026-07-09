# Control Room / DJ Mixer Second-Window Investigation (2026-07-08 → 2026-07-09)

Owner: owner + Claude Sonnet 5 (master coordinator)
Status: Crash + GL error cascade confirmed fixed (two clean owner-run
sessions, no apitrace, zero GL errors, clean shutdown). Visual black
screen on control-room/mixer's own windows is a **separate, still-open**
bug — see §7.
Last updated: 2026-07-09

Successor to [`control-room-debug-handoff.md`](control-room-debug-handoff.md)
(2026-06-05 and earlier), which chased an overlapping but distinct set of
symptoms on the same in-process-second-SDL-window architecture and left
"audience-output starvation" and "audience-output lockup after close" as
unconfirmed. This document picks up from a fresh owner report on 2026-07-08
and traces two genuinely different bugs to ground, with a live GPU call
trace (`apitrace`) as the deciding piece of evidence for the second one.

---

## 0) TL;DR

Two real, independent bugs were found and fixed in this investigation:

1. **dj-mixer-01 crashed on quit** after its mixer window had been opened.
   Root cause: it cloned control-room-01's second-SDL-window approach but
   never picked up the `rebind_main_gl_context()` call control-room-01
   already needed for exactly this reason. **Fixed and confirmed** by the
   owner (2026-07-08 → 07-09).

2. **Opening control-room-01 or dj-mixer-01 corrupted the entire GL
   context for the rest of the session** — a massive, continuous
   `glUseProgram`/`glBindVertexArray`/`glUniform`/`glBufferSubData` error
   cascade (as many as ~408,000 GL error lines in one session), eventually
   severe enough to crash the process outright. Three earlier fix attempts
   each corrected a real, separate bug without resolving this symptom.
   The actual root cause, found via a live `apitrace` GL call capture, not
   inferred from error text: `SDL_RenderPresent()` on control-room/mixer's
   own SDL window calls `eglMakeCurrent` to switch to their own internal
   EGL context and **never switches back**, so every one of the main app's
   subsequent GL calls that frame (and beyond) runs against the wrong
   context. **Fixed and confirmed** — two clean owner-run sessions with
   zero GL errors and clean shutdown.

**Still open:** control-room/mixer's own windows still render **visually
black** for the owner even after both fixes above, despite the app itself
running perfectly cleanly (no crash, no GL errors, "first frame
produced"/"first frame presented" diagnostics both report success). This
is a separate, unresolved bug — see §7 for the leading theory and
recommended next step.

---

## 1) Background — why this architecture exists

control-room-01 and dj-mixer-01 each open their **own SDL window**, in the
same process as the main audience window, using `SDL_RENDERER_SOFTWARE` +
a streaming ARGB texture fed by a background PIL-rendering thread. This
avoids sharing a GL context/objects between the drop-in and the main
`moderngl` context. dj-mixer-01's own module docstring describes itself as
"cloning the proven control-room-01 approach."

The main app's audience rendering is a `moderngl` (OpenGL 3.3 core) context
created via `moderngl.create_context()` wrapping an SDL-created GL context
(`unicornviz/app.py::_init_moderngl`). This is a **separate, real EGL/GLX
context** from whatever SDL's software renderer uses internally for the
second window.

This "second SDL window in the same process" pattern has a documented
history of being fragile on this codebase — see
`drop-ins/multi-head-01/MATE-X11-MULTIHEAD-NOTES.md`, "Iteration 1", for an
entirely separate feature (mirror-mode per-monitor windows) that was
abandoned after going black/freezing/crashing on three different platforms
using a similar approach, replaced with a single-window GL-native design.
That investigation is referenced in
`docs/audits/2026-07-08-render-pipeline-platform-audit.md` §4 and was
re-examined (and reconfirmed as correctly abandoned) during this
investigation.

---

## 2) Symptom timeline, as reported by the owner

| When | Report |
|---|---|
| 2026-07-08 | Control-room-01 crashes shortly after first frame renders; dj-mixer-01 crashes the same way (previously worked fine on Windows) |
| 2026-07-09 morning | Owner confirms: after the item-1 fix below, no more crash — `faulthandler_*.log` is 0 bytes |
| 2026-07-09 | Owner reports both windows now show **black** instead of crashing — "flash half the room, other half black, then all black... effects lock up but HUD still updates live" |
| 2026-07-09 | Owner tests GNOME Wayland, GNOME Classic, and MATE/X11 — **identical black screen and identical `GL_INVALID_VALUE` PBO error on all three**, including plain X11 with no Mutter/Wayland compositor involved at all |
| 2026-07-09 | Owner captures MESA_DEBUG output directly: reveals a live, continuous GL error flood, not just the one PBO warning already visible in the app's own log |
| 2026-07-09 | Owner runs an isolation test (control-room/mixer never opened): **zero** GL errors, vs. ~408k in an otherwise identical session with them open — proves causation definitively |
| 2026-07-09 | `apitrace` captures of Control Room and DJ Mixer sessions find the real mechanism (§6) |
| 2026-07-09 | Fix lands; owner runs two clean sessions (no apitrace) — **zero GL errors, clean shutdown, no crash** — but **both windows are still visually black** |

---

## 3) Root cause #1 (fixed 2026-07-08/09): dj-mixer-01 missing `rebind_main_gl_context()`

`unicornviz/app.py::rebind_main_gl_context()` exists specifically to
restore `SDL_GL_MakeCurrent` on the main audience window/context after a
subsystem-owned window is created or destroyed, "so any GL binding
implicitly migrated by SDL/X11 is restored." control-room-01 already had
this wired into `_create_control_room()`/`_destroy_control_room()`
(`app.py`) and its own `_destroy_window()` (covers the self-close-via-Esc
path). dj-mixer-01 cloned the rest of control-room-01's window approach
but never picked up this specific call.

**Fix:**
- `drop-ins/dj-mixer-01/dj_mixer_controller.py` — `rebind_main_gl_context()`
  after `open_window()`/`close_window()` (commit `ef48171` /
  `dj-mixer-01@ef48171`… see §9 for full hash list).
- `drop-ins/dj-mixer-01/ui.py` — `MixerWindow._destroy_window()` itself
  calls it too (covers the self-close path, mirroring
  `control-room-01/control_room.py:396`).
- 19 new regression tests in the drop-in (`test_ui_gl_rebind.py`).

**Confirmed fixed** by the owner: opened both windows, quit cleanly, no
crash, `faulthandler_*.log` (see §5) was 0 bytes.

---

## 4) The black screen — three fix attempts that were each real but insufficient

Once the crash was fixed, the owner immediately hit a new symptom: both
windows opened and rendered without error internally, but displayed
**black**. What follows are the three fix attempts made before the real
cause was found — each one is left in place because each fixed a genuine,
independently-confirmed bug; none of them were the actual cause of the
black screen.

### 4.1 Attempt 1 — stale-surface-refresh port (insufficient alone)

control-room-01 already had a `_needs_surface_refresh` mechanism: GNOME/
Mutter can hand a freshly (re)mapped SDL window a stale surface that blits
as black until something forces a fresh commit, so control-room-01 resets
its frame-throttle state on `EXPOSED`/`SHOWN`/`RESTORED`/`FOCUS_GAINED`.
dj-mixer-01 never had this. Ported over, plus first-frame diagnostic
logging ("render thread produced its first frame" / "first frame
presented to the compositor") added to both drop-ins so future reports
show exactly which stage succeeds. Real, valid fix — did not resolve the
black screen alone.

### 4.2 Attempt 2 — ruling out Mutter/Wayland (not the cause)

`journalctl` cross-referenced against session logs showed GNOME Shell
logging its own internal assertion failures (`meta_window_set_stack_
position_no_sync`, `surface_constraint_data_new: code should not be
reached` — a Mutter-internal bug class) and "Client provided invalid
window geometry... Working around" for every window the app creates,
including the *main* audience window, not just control-room/mixer. This
looked like a strong lead. **Ruled out** by owner testing: identical black
screen and identical GL error on GNOME Wayland, GNOME Classic, *and*
MATE/X11 — MATE has no Mutter/Wayland compositor involved at all, so
whatever's happening is not compositor-specific. (The geometry warnings
are real and may still be worth investigating separately — see
`docs/audits/2026-07-08-render-pipeline-platform-audit.md` §4/§5 for the
unrelated GNOME-panel-in-mirror-mode / overlay-migration items that first
surfaced this pattern.)

### 4.3 Attempt 3 — the moderngl default-framebuffer read bug (real, confirmed, insufficient alone)

Enriched PBO-failure diagnostics (see §5) surfaced a deterministic
`GL_INVALID_VALUE` from `glReadBuffer(invalid buffer
GL_COLOR_ATTACHMENT0)`, always on the *second* frame after a subsystem
first requested a frame-preview read. Traced this directly to moderngl's
own upstream C++ source
(`github.com/moderngl/moderngl/blob/main/src/moderngl.cpp`):
`Framebuffer.read()`/`read_into()` unconditionally issue
`glReadBuffer(GL_COLOR_ATTACHMENT0 + attachment)`, which the OpenGL spec
does not allow against the default framebuffer (`framebuffer_obj == 0`).
moderngl's own context-init code carries a code comment acknowledging this
exact bug class for `draw_buffers`:

```c
// GL_COLOR_ATTACHMENT0 is causes error: 1282
// This value is temporarily ignored
```

...and works around it there by querying the real `GL_DRAW_BUFFER` via
`glGetIntegerv` instead of hardcoding an attachment enum — but the
equivalent fix was never applied to the *read* path. By contrast,
moderngl's `copy_framebuffer()` (used for `glBlitFramebuffer`) correctly
uses each framebuffer's already-queried `draw_buffers[i]`, not a hardcoded
enum.

**Fix:** `_read_streaming_frame()` and `read_screenshot_frame()` in
`unicornviz/app.py` never call `.read()`/`.read_into()` on `self._ctx.screen`
directly anymore. They blit it into a real FBO
(`App._ensure_screen_copy_fbo()`) via `copy_framebuffer()` first, and read
from that instead. The first version of this fix was tested live by the
owner (via the shared working tree, mid-edit) before it was committed, and
found a real bug in the fix itself: the new FBO had no depth attachment,
and `copy_framebuffer()`/`glBlitFramebuffer` always blits
`GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT` — moderngl has no color-only
blit option — so a color-only destination FBO produced a *new*
`GL_INVALID_FRAMEBUFFER_OPERATION` ("incomplete draw/read buffers"). Fixed
by adding a `depth_renderbuffer`, mirroring the existing `_make_fbo()`
pattern used for the effect-transition FBOs.

This fix is real and confirmed correct (verified directly in an apitrace
dump — see §6) but **did not stop the black screen or the GL error
flood**, because it was never the dominant cause — the error volume barely
changed (~408k → ~332k in the next session) and the same massive
`glUseProgram` cascade continued.

---

## 5) Diagnostic tooling built along the way

These were added specifically to make this investigation possible and are
expected to remain useful for any future GL-related bug report:

- **`faulthandler.enable()`** at startup (`unicornviz/__main__.py::
  _install_faulthandler`) — writes to `logs/faulthandler_<stamp>.log` when
  logging is enabled. A hard native crash previously left zero forensic
  trace beyond the log stopping mid-line; this is what caught the full
  Python-level stack trace of the eventual segfault (§6.1) including the
  exact C library call chain.
- **`MESA_DEBUG`/`LIBGL_DEBUG`/`EGL_LOG_LEVEL` auto-enabled** when
  `[logging] level = "DEBUG"` (`_install_gl_debug_env`) — previously
  required remembering to export three env vars by hand; this is what
  first surfaced the GL error flood that the app's own log couldn't show
  (Mesa driver errors go to raw stderr, not through Python `logging`).
- **Enriched PBO failure logging** (`App._disable_stream_pbo`) — logs
  which specific call failed (write vs. read), the raw `glGetError()` code,
  buffer size, canvas dimensions, mirror-mode state, and how many frames
  succeeded before the failure, instead of just moderngl's generic
  "cannot map the buffer" message.
- **`apitrace`** (`sudo dnf install apitrace`) — the tool that actually
  found the real root cause. Usage:
  ```
  apitrace trace -a egl -o /tmp/trace.trace -- .venv/bin/python -m unicornviz
  ```
  then `apitrace dump --calls=X-Y trace.trace` for a specific call range,
  or `apitrace dump --grep=REGEX trace.trace` to filter by function name.
  `glretrace --headless trace.trace` replays the trace with real
  `glGetError()` checking after every call and prints the *exact* call
  number where each error first appears — this is what pinpointed the
  `eglMakeCurrent` divergence in §6, and is far faster than re-deriving a
  root cause from Mesa's plain error text a fourth time.
  **Caveat found the hard way:** apitrace's own EGL wrapper library
  (`egltrace.so`) appeared inside a real segfault's C stack trace (§6.1)
  when the owner ran a test *through* `apitrace trace` again — juggling
  two separate EGL contexts (ours + control-room's) through one tracing
  wrapper may itself be a source of instability distinct from the
  underlying app bug. Prefer plain (untraced) runs for confirming whether
  a fix actually resolved a symptom; reserve `apitrace` for capturing a
  fresh trace when new investigation is needed.

---

## 6) The real root cause: `SDL_RenderPresent()` steals the GL context

Two apitrace captures (Control Room and DJ Mixer, `~111-117 MB` each) were
taken and dumped/analyzed directly (`apitrace dump`, `apitrace dump
--grep=...`, `apitrace dump --calls=X-Y` for targeted ranges).

The exact sequence, read straight out of the Control Room trace (call
numbers are apitrace's own):

```
34697  eglSwapBuffers(...)                          # our main app's own frame swap
34698  eglBindAPI(api = EGL_OPENGL_API)
34699  eglMakeCurrent(dpy=..., ctx=0x55c41ca52050)   # <-- switches to a DIFFERENT context
34701  glBindTexture(target = GL_TEXTURE_2D, texture = 1)
34704  glTexSubImage2D(...)                          # uploading control-room's PIL-rendered pixels
34705  glEnableClientState(array = GL_VERTEX_ARRAY)  # legacy fixed-function / client-array calls —
34706  glEnableClientState(array = GL_COLOR_ARRAY)   # NOT how our app renders (core profile 3.3);
34707  glEnableClientState(array = GL_TEXTURE_COORD_ARRAY)  # this is SDL's own internal blit path
34710  glTexCoordPointer(...) / glColorPointer(...) / glVertexPointer(...)
34713  glDrawArrays(mode = GL_TRIANGLES, first = 0, count = 6)
34718  eglSwapBuffers(...)                           # control-room's OWN window swap
                                                      # <-- no eglMakeCurrent switching back, ever
34719+ (texture/sampler/buffer setup for the NEXT frame's normal rendering)
34812  glUseProgram(program = 124)                   # our app's own program — FIRST FAILURE
```

`glretrace --headless` (real replay with error-checking) confirms exactly
where this first breaks:

```
34801: warning: glGetError(glClear) = GL_INVALID_FRAMEBUFFER_OPERATION
34812: warning: glGetError(glUseProgram) = GL_INVALID_VALUE
34813: warning: glGetError(glUniform1fv) = GL_INVALID_OPERATION
... (continues for the rest of the session)
```

**In plain terms:** `SDL_RenderPresent()` on control-room's (or
dj-mixer's) own SDL window, even though it was created with
`SDL_RENDERER_SOFTWARE`, uses an EGL-backed compositing path internally on
Wayland. Presenting that window calls `eglMakeCurrent` to switch to its
own internal EGL context, does its own legacy client-array GL drawing to
blit its texture, swaps its own window — and simply never calls
`eglMakeCurrent` back. Every GL call our own app makes afterward (starting
with the very next `glUseProgram`) operates against the wrong context,
where none of our app's program/VAO/buffer object IDs exist — hence
`GL_INVALID_VALUE`/`GL_INVALID_OPERATION` on essentially everything, for
the rest of the session.

This also fully explains the isolation test result (§2): `present()` is
only ever called for subsystems that have a callable `present` method and
are actually doing something meaningful (in practice, only when
control-room/mixer are open) — so if they're never opened, `SDL_
RenderPresent()` never runs for a second window, and `eglMakeCurrent`
never gets diverted away from the main context.

### 6.1 The segfault (bonus finding, confounded by apitrace itself)

Before the fix, `faulthandler` caught one full native crash, thread-by-
thread, for the first time in this investigation:

```
Fatal Python error: Segmentation fault
Current thread ... (most recent call first):
  File ".../drop-ins/projectm-01/projectm_effect.py", line 225 in configure
  File ".../drop-ins/projectm-01/projectm_effect.py", line 1306 in update
  File ".../unicornviz/app.py", line 4025 in run
Current thread's C stack trace:
  ...
  Binary file ".../apitrace/wrappers/egltrace.so" ...
  Binary file ".../apitrace/wrappers/egltrace.so", at glTexImage2D+0x2f4
  Binary file ".../libprojectM-4.so.4" ...
```

ProjectM (a third-party C++ library, unrelated to control-room/mixer)
crashed inside its own `glTexImage2D` call during a preset-transition
texture reload — plausibly a downstream consequence of the same context
corruption (ProjectM's texture upload landing on the wrong/already-broken
context). However, this specific capture was confirmed to have been taken
**through `apitrace trace` again** (owner-confirmed), so `egltrace.so`
appearing in the crash's own C stack trace is a real confound — this
crash may be partially or wholly an artifact of the tracer itself
struggling with two simultaneous EGL contexts in one process, not
necessarily representative of an untraced run. Not re-investigated further
since the fix's own untraced verification runs (§0, §7) came back clean.

---

## 7) Current status — what's fixed, what's still open

**Fixed and confirmed** (two clean owner-run sessions, no apitrace, both
windows opened, both quit via Escape):

- No crash.
- Zero GL error/warning lines beyond the same 5 pre-existing, unrelated
  warnings every session shows (drop-in loader import quirks, MIDI
  hardware notes) — specifically, **no** `GL_INVALID_*`, no `Streaming PBO
  ... failed` lines.
- `subsys_present` per-frame timing stayed in the 0.01–0.03ms range (the
  `rebind_main_gl_context()` call itself is cheap).
- Clean shutdown log sequence (`AudioManager: analysis thread exited`,
  etc.) both times.

**Still open:** both windows still render **visually black** for the
owner in these same clean sessions, despite:
- `Control room: render thread produced its first frame` /
  `first frame presented to the compositor` (and the dj-mixer equivalents)
  both logging success.
- Zero exceptions or GL errors anywhere in the session.

This means the visual symptom is **not** explained by the GL-context-
stealing bug (that bug is fixed, and the black screen persists), and is
not explained by any of the other three earlier fix attempts either. It
is a distinct, still-unsolved bug in how control-room-01/dj-mixer-01's
own SDL_Renderer-based window actually gets composited to the screen.

### Leading theory for the remaining black screen

The `journalctl` findings from §4.2 — "Client provided invalid window
geometry... Working around" and Mutter-internal assertion failures firing
for every window this app creates — were only used to rule out a
*compositor-specific* explanation (since the black screen reproduces
identically on MATE/X11 too, which has no Mutter). They were **not**
independently explained. Since Mesa/EGL is the common factor across
GNOME Wayland, GNOME Classic, and MATE/X11 (same GPU, same driver stack,
different window managers/protocols), the most likely remaining
explanation is a **Mesa/EGL-level issue specific to presenting a second,
small SDL_RENDERER_SOFTWARE-backed window's surface while a primary
OpenGL-heavy context is simultaneously active in the same process** —
i.e., a narrower, presentation-only version of the same
"second-window-in-one-process" fragility documented for the abandoned
mirror-mode legacy path (§1).

### Recommended next step

Apply the same `apitrace` methodology that found root cause #2, but
targeted specifically at control-room's *own* window surface presentation
rather than the main app's subsequent GL calls:

1. Capture a fresh, short trace with the fix in place (`apitrace trace -a
   egl -o /tmp/cr_visual.trace -- .venv/bin/python -m unicornviz`, open
   Control Room only, wait a few seconds, quit).
2. `apitrace dump --calls=<range around control-room's window creation and
   first few presents>` and specifically inspect: the texture contents
   being uploaded (`glTexSubImage2D`'s pixel blob — apitrace can dump
   this to a file), the exact `eglSwapBuffers` surface/context pairing,
   and whether `glretrace --headless -v` reports anything for *this*
   window's own draw calls (34701-34718 in the original trace looked
   structurally fine, but was never checked with real error-checking
   replay — only the main app's *subsequent* calls were).
3. Consider capturing with `glretrace -s /tmp/snapshot -S calls=<call
   number right after control-room's own eglSwapBuffers>` to get an actual
   pixel dump of what control-room's window buffer contains at that exact
   moment — this would definitively show whether the PIL-rendered content
   ever reaches the GPU correctly, independent of whatever the compositor
   does with it afterward.

---

## 8) Lessons learned / guidance for future drop-in authors

- **Any drop-in that creates its own SDL window and calls
  `SDL_RenderPresent()` (even with `SDL_RENDERER_SOFTWARE`) must be
  assumed to silently steal the current GL context on Wayland.** The
  fix pattern is now centralized: `App._present_subsystems()` calls
  `rebind_main_gl_context()` once per frame after all subsystem
  `present()` calls, gated on whether any subsystem actually presented.
  Any *new* subsystem with its own window should just implement a
  `present()` method and be registered normally — no extra work needed
  per-drop-in now that the fix lives at the call-site level, not
  per-drop-in.
- **A caught exception does not mean the GL context wasn't already
  switched.** `_present_subsystems()` rebinds even if a presenter raised,
  since `SDL_RenderPresent()` could switch context before failing partway
  through.
- **`apitrace` + multiple EGL contexts in one process should be treated
  with suspicion of its own instability** — don't assume a crash captured
  through `apitrace trace` is 100% representative without also
  reproducing (or failing to reproduce) it in a plain, untraced run.
- **When Mesa error text alone doesn't converge after 2-3 targeted fixes,
  switch to `apitrace` rather than continuing to guess.** Three fix
  attempts here were each real, verifiable bugs — but none were found by
  reading error text alone faster than a live call trace would have found
  the actual root cause. In hindsight, reaching for `apitrace` after the
  *second* inconclusive fix attempt (rather than the fourth) would have
  saved real time.
- **`faulthandler.enable()` is worth having on by default going forward**
  — it caught a full, thread-by-thread native crash trace on the first
  segfault after being added, where every prior crash in this
  investigation left zero forensic trail beyond the log stopping mid-line.

---

## 9) Full commit log (chronological)

Main repo (`unicorn-viz`):

| Commit | Date | Summary |
|---|---|---|
| `5ca38d7` | 2026-07-08 | Add render pipeline & platform audit (control-room/dj-mixer/multi-head) — investigation begins |
| `9306fe4` | 2026-07-08 | Enable faulthandler at startup for native-crash diagnostics |
| `51391cf` | 2026-07-09 | Bump dj-mixer-01 + control-room-01: stale-surface refresh + diagnostics (§4.1) |
| `75078b0` | 2026-07-09 | Remove dead legacy mirror-window call sites (unrelated cleanup, same audit) |
| `e69347f` | 2026-07-09 | Auto-enable Mesa/EGL debug env when logging is DEBUG; richer PBO diagnostics (§5) |
| `abd06c1` | 2026-07-09 | Pin explicit read viewport to fix streaming-PBO GL_INVALID_VALUE (superseded theory, §4.3 is the real fix) |
| `6a9c6ec` | 2026-07-09 | Fix moderngl default-framebuffer read bug, confirmed via source (§4.3) |
| `4e26b4c` | 2026-07-09 | Rebind GL context every frame after subsystem present — the real fix (§6) |
| `a31ea5b` | 2026-07-09 | Record item 11 definitive root cause via apitrace investigation (audit doc) |

`drop-ins/dj-mixer-01` (own repo):

| Commit | Summary |
|---|---|
| `ef48171` | Rebind main GL context on mixer window destroy (ui.py) |
| `4603256` | Force compositor re-commit on window re-expose/refocus (stale-surface fix) |

`drop-ins/control-room-01` (own repo):

| Commit | Summary |
|---|---|
| `eee7f0f` | Add first-frame diagnostic logging (render + present) |

See `docs/audits/2026-07-08-render-pipeline-platform-audit.md` §8 for the
full prioritized item tracker this investigation fed into (items 1, 9, 11).

---

## 10) Related docs

- [`control-room-debug-handoff.md`](control-room-debug-handoff.md) — the
  predecessor investigation (2026-06-05 and earlier).
- [`../../audits/2026-07-08-render-pipeline-platform-audit.md`](../../audits/2026-07-08-render-pipeline-platform-audit.md) —
  the live tracked-item audit this investigation was conducted under.
- [`../../../drop-ins/multi-head-01/MATE-X11-MULTIHEAD-NOTES.md`](../../../drop-ins/multi-head-01/MATE-X11-MULTIHEAD-NOTES.md) —
  the earlier, separate second-window architecture that was abandoned for
  a related class of fragility.
