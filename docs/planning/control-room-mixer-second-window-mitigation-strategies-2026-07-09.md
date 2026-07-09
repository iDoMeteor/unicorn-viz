# Control Room / DJ Mixer Second-Window — Linux Mitigation Strategies

Owner: owner + Claude (planning/audit)
Status: **M3 implemented, hit a second Linux-specific wall, fixed —
landed** (2026-07-09, same day) — see §8 and §10. First landing used
`moderngl.create_context()` for the second window; owner testing (forced
`SDL_VIDEODRIVER=x11`) confirmed the windowing/present mechanism itself
works, but the real app's default native-Wayland session hit a second,
distinct bug: `moderngl.create_context()` cannot attach to a second,
already-current context on native Wayland at all (its "detect" fallback
is hardcoded to X11/GLX — a `glcontext` limitation, not a settings issue).
Rebuilt without moderngl, loading a minimal OpenGL 3.3 subset directly via
`SDL_GL_GetProcAddress` instead. Verified against real SDL2 + GL with
`SDL_VIDEODRIVER=wayland` forced (the exact condition that broke before)
on this machine. Also fixed while in the area: cursor visibility over
control-room/mixer windows (§10).
Last updated: 2026-07-09

Companion to the investigation record in
[`docs/debug/control-room-mixer-second-window-investigation-2026-07-09.md`](../debug/control-room-mixer-second-window-investigation-2026-07-09.md)
(the crash + GL-cascade fixes and the still-open black-screen symptom). This
document is the result of a follow-up audit of the core rendering pipeline,
the control-room-01 / dj-mixer-01 / multi-head-01 drop-ins, the surviving
session/GL-debug logs, and SDL2's actual source code (v2.32, the exact
version bundled by `pysdl2-dll 2.32.0` that this app runs against). It
proposes concrete, ranked mitigation strategies for every Linux
environment, plus a diagnostics-first plan whose first two experiments
require **zero code changes**.

---

## 1) The decisive new finding: SDL2's hidden "texture framebuffer"

The investigation doc's §7 leading theory ("a Mesa/EGL-level issue specific
to presenting a second SDL_RENDERER_SOFTWARE-backed window while a primary
GL context is active") can now be made much more precise. It is not Mesa —
it is **SDL2's window-framebuffer emulation layer**, verified directly in
SDL2 source (branch `SDL2`, matching the bundled 2.32.0):

**The chain, step by step:**

1. control-room-01 and dj-mixer-01 create their windows *without*
   `SDL_WINDOW_OPENGL` and request `SDL_CreateRenderer(window, -1,
   SDL_RENDERER_SOFTWARE)` — the intent being a pure-CPU path.
2. The software renderer draws into the **window surface** and presents via
   `SDL_UpdateWindowSurface()` — `SW_RenderPresent` is literally
   `return SDL_UpdateWindowSurface(window);` (`SDL_render_sw.c:964-971`).
3. The first `SDL_GetWindowSurface()` call in the process runs
   `ShouldAttemptTextureFramebuffer()` (`SDL_video.c:2678`). **On Linux the
   default answer is TRUE** — the only Linux exception is WSL detection.
   There is no "hardware GL available?" probe anymore in 2.32; it simply
   defaults to the accelerated path on both X11 and Wayland unless the
   `SDL_FRAMEBUFFER_ACCELERATION` hint says otherwise.
4. So SDL silently calls `SDL_CreateWindowTexture()` (`SDL_video.c:234`),
   which creates a **second, hidden `SDL_Renderer`** on the same window
   using the first accelerated driver — `"opengl"` on this system — which
   creates **its own GL context** (EGL on Wayland, GLX/EGL on X11).
5. Every `SDL_UpdateWindowSurface()` afterwards routes through
   `SDL_UpdateWindowTexture()`: upload the CPU surface with
   `glTexSubImage2D`, draw a legacy client-array quad
   (`glEnableClientState`/`glVertexPointer`/`glDrawArrays`), swap. This is
   **exactly, call for call, the sequence apitrace captured** (calls
   34699–34718 in the original trace): `eglMakeCurrent` to a foreign
   context, legacy fixed-function blit, `eglSwapBuffers`, no restore.
6. The hidden renderer evades SDL's own "Renderer already associated with
   window" guard (`SDL_render.c:1022`) because the window surface — and
   with it the hidden renderer — is created *during* our outer
   `SDL_CreateRenderer` call, before the outer renderer's association is
   recorded. Two renderers, one window. SDL's own source carries FIXME
   comments acknowledging this exact scenario is unhandled
   (`SDL_video.c:2744-2747`: *"is it feasible we could have an accelerated
   OpenGL window and a second ends up in software?"*).

**Why this explains everything observed so far:**

- *EGL activity from a nominally "software" renderer* — it is SDL's hidden
  accelerated renderer, not the software renderer, doing the presenting.
- *Identical behavior on GNOME Wayland, GNOME Classic, and MATE/X11* — the
  Linux default in step 3 is TRUE for **both** the wayland and x11 video
  drivers. The compositor was never the variable; SDL's emulation layer is
  common to all three environments.
- *The (now fixed) context stealing* — the hidden renderer's
  `SDL_GL_MakeCurrent` to its own context with no restore.
- *The still-open black window* — whatever is failing lives inside (or
  interacts with) this hidden GL blit path, which we neither chose nor
  control. Two EGL window surfaces + two contexts + one GL-heavy app in
  one process is exactly the fragility class that killed the legacy
  multi-head mirror windows on three platforms
  (`drop-ins/multi-head-01/MATE-X11-MULTIHEAD-NOTES.md`, Iteration 1).

**Two more load-bearing facts from SDL2 source:**

- **SDL2's Wayland driver has no native window framebuffer.** There is no
  `CreateWindowFramebuffer` implementation anywhere in
  `src/video/wayland/` (the `SDL_waylandshmbuffer.c` file serves cursors,
  not window surfaces). Consequence: on native Wayland, disabling the
  texture framebuffer makes `SDL_GetWindowSurface` **fail outright** with
  `"Window framebuffer support not available"` — the same failure string
  tracked in sdl2-compat issue #266. On Wayland + SDL2 there is *no*
  pure-software window path, period.
- **X11 has a real native framebuffer** (`SDL_x11framebuffer.c`,
  XImage/MIT-SHM). With the hint set, second windows on X11 present with
  zero GL involvement.
- The texture-framebuffer decision is **process-sticky**
  (`_this->checked_texture_framebuffer`, checked once per video device) —
  any hint must be set before the first window surface is created anywhere
  in the process.
- Precedent for the mitigation: SDL itself force-sets
  `SDL_FRAMEBUFFER_ACCELERATION=0` + software renderer on Loongson
  integrated graphics (`SDL_render.c:1004-1009`) because the accelerated
  emulation is worse there.

---

## 2) Current state of the pipeline (audit summary)

Audited: `unicornviz/app.py` (window/GL init, `rebind_main_gl_context`,
`_present_subsystems`, streaming/readback paths), `control_room.py`
(window lifecycle + present), `dj-mixer-01/ui.py` (confirmed faithful
clone), `multihead.py` + notes, and the surviving logs.

What is solid:

- Main window: `SDL_WINDOW_OPENGL`, core-profile 3.3 context, moderngl on
  top; never touches `SDL_GetWindowSurface` — **unaffected** by anything
  in §1.
- `_present_subsystems()` rebinds the main context after any subsystem
  present — confirmed working (zero GL errors across three clean owner
  sessions, `subsys_present` 0.01–0.06 ms).
- Deferred teardown, stale-surface refresh, frame-id throttling, first
  frame diagnostics: all present in both drop-ins and correct.
- `app.py` line 21-22 forces `SDL_VIDEODRIVER=wayland` by default on
  non-Windows **unless the env var is already set** — so owner-side env
  overrides work without code changes.

Known minor issues (not causes, worth fixing opportunistically):

- `DjMixerController.present()` is always callable once the drop-in loads,
  so `_present_subsystems()`'s rebind gate effectively runs every frame
  even with no window open (documented in the audit doc's Status Update 3
  correction). Cheap fix: skip subsystems whose `is_open` is False.
- The initial window clear color is the theme background `(8, 10, 18)` —
  **nearly black**. Today we cannot visually distinguish "the initial
  clear reached the screen but later frames don't" from "nothing ever
  reaches the screen." Experiment 0 below exploits this.

---

## 3) Hypotheses for the remaining black window (ranked)

| # | Hypothesis | Evidence | Testable by |
|---|---|---|---|
| H1 | The hidden GL renderer's presents complete but its uploads/draws land wrong (texture path bug inside the two-context process) | apitrace showed structurally valid calls but replay-with-error-check was only ever run against the *main* app's calls | Experiment 4 (targeted apitrace + pixel snapshot) |
| H2 | Presents never reach the screen at all (compositor never receives / maps a usable buffer) | "first frame presented" only proves `SDL_RenderPresent` returned 0 | Experiment 0 (bright clear) |
| H3 | Our per-frame `rebind_main_gl_context()` interacts badly with the hidden renderer's own context caching (SDL TLS current-context cache) | Speculative; both paths go through `SDL_GL_MakeCurrent` so the cache should stay coherent | Experiment 4; also E1 (removes hidden renderer entirely) |
| H4 | Wayland frame-callback inhibition for windows the compositor considers non-visible stalls/blanks the hidden GL path (SDL issue #4335 class) | Windows are on visible monitors, and the symptom also reproduces on X11 — weak | E1 (X11 native path) |
| H5 | Mixed-DPI (200%/100% monitors) buffer-scale mismatch in the hidden renderer | Reproduces identically on X11/MATE without fractional scaling — weak | E1 |

H1/H2 are the live candidates. Either way, **every mitigation below except
"do nothing" removes or bypasses the hidden renderer**, so the mitigation
plan does not depend on resolving H1-vs-H2 first — the experiments mainly
decide how urgently to file an upstream SDL bug and what to put in it.

---

## 4) Mitigation strategies, ranked

### M1 — Force the native software framebuffer on X11 (1-line fix + tests)

Set the hint before any window-surface creation, gated to the x11 driver:

```python
# after SDL_Init, once the active driver is known:
if sdl2.SDL_GetCurrentVideoDriver() == b'x11':
    sdl2.SDL_SetHint(b'SDL_FRAMEBUFFER_ACCELERATION', b'0')
```

- Effect: on any X11 session (MATE, GNOME-on-Xorg, or the whole app run
  under XWayland), control-room/mixer windows present via XImage/MIT-SHM.
  **No hidden GL renderer exists at all** — no second context, no
  stealing, and (if H1–H3 are right) no black window.
- Must be gated: setting it on native Wayland makes `SDL_GetWindowSurface`
  fail (§1) and the operator windows would not open at all.
- Risk: low. The main window never uses window surfaces. CPU cost of
  MIT-SHM blits at operator-window sizes/frame-rates (~8–30 fps, one
  window) is negligible.
- Keep the per-frame rebind regardless — defense in depth, measured cost
  ~0.01–0.03 ms.

### M2 — Zero-code workaround available today (env vars)

SDL2 hints read from the environment. On the GNOME Wayland session this
runs the whole app through XWayland with the native software framebuffer:

```bash
SDL_VIDEODRIVER=x11 SDL_FRAMEBUFFER_ACCELERATION=0 .venv/bin/python -m unicornviz
```

If this displays the operator windows correctly, M1 is validated and the
owner has an immediate usable configuration on every desktop while the
Wayland-native story (M3/M4) is decided. Cost: main window runs under
XWayland (historically fine for this app; the multi-head code actually
*prefers* x11 for placement reliability already — `_init_sdl()` falls back
to x11 for multi-head modes on Wayland).

### M3 — Wayland-native: explicit-GL operator window (medium effort)

On native Wayland there is no software window path in SDL2 (§1), so if
Wayland-native operator windows must work, we should own the GL instead of
letting SDL hide it:

- Create the operator window **with** `SDL_WINDOW_OPENGL` and a dedicated
  context we create and manage.
- `present()` becomes: `SDL_GL_MakeCurrent(win2, ctx2)` → upload BGRA
  bytes with `glTexSubImage2D` → draw one textured quad → `SDL_GL_SwapWindow`
  → `SDL_GL_MakeCurrent(main_window, main_ctx)` restore, all inside one
  bracketed, exception-safe function.
- Set swap interval 0 on the operator context and keep the existing
  frame-id throttle so `eglSwapBuffers` never blocks on frame callbacks
  for an occluded window (the SDL #4335 failure class).
- This is the same amount of GL SDL was already doing behind our backs —
  but deterministic, visible in our own traces, and testable. It is
  architecturally distinct from the abandoned multi-head legacy path
  (which was CPU readback + per-window renderers driven at 60 fps); this
  is one small window at ≤30 fps with explicit context bracketing.
- Effort: ~1–2 days including regression tests (fake-GL fixtures like the
  existing `_FakeStreamCtx` pattern). Applies to both drop-ins via a
  shared helper — consider hoisting a small `SecondWindowGL` utility into
  the core so future drop-ins stop re-cloning window code.

### M4 — Strategic: out-of-process operator windows (most robust)

The 2026-06-05 handoff already named this as the planned direction
("separate-process control room architecture"):

- A helper process (spawned via `subprocess`; own SDL instance, any video
  driver it likes) owns the operator window; the main app streams UI
  frames (and receives input events) over a Unix socket or shared-memory
  ring.
- Immune by construction to every in-process GL/window interaction bug in
  this saga — including whatever is still causing the black screen — on
  every compositor, and it isolates operator-UI crashes from the show.
- Preview frames are already produced as plain BGRA bytes on a background
  thread, so the render side ports cleanly; the work is the IPC channel,
  process lifecycle, and input routing (~1–2 weeks to do well).
- Recommended as the v1.0 architecture; M1/M3 are good interim states and
  M3's explicit-GL present code would be thrown away, so if M4 is chosen
  soon, consider skipping M3 entirely and living with M2 on Wayland in
  the interim.

### M5 — Watch, don't adopt: SDL3

SDL3's Wayland driver has a real wl_shm software window framebuffer (what
SDL2 lacks). But PySDL2 does not support SDL3, and sdl2-compat (SDL2 API
over SDL3, what Fedora now ships) currently fails this exact case —
issue #266, `"Window framebuffer support not available"` on the wayland
driver. Track both; do not migrate for this reason yet.

---

## 5) Diagnostics-first plan (cheap → expensive)

**Experiment 0 — bright initial clear (5-minute diagnostic commit).**
Change the initial `SDL_SetRenderDrawColor` in both drop-ins' window
creation from theme background to magenta `(255, 0, 255)` temporarily.
The current near-black `(8, 10, 18)` clear makes H1 and H2
indistinguishable. Outcome map: window shows magenta → presents reach the
screen; the failure is in the texture upload/copy path (H1). Still black →
presents never reach the screen at all (H2).

**Experiment 1 — M2 env vars, GNOME session (zero code).**
`SDL_VIDEODRIVER=x11 SDL_FRAMEBUFFER_ACCELERATION=0` — if operator windows
work: M1 confirmed; ship it; Wayland-native becomes a scheduling question
(M3/M4) instead of a blocker.

**Experiment 2 — XWayland without the hint (zero code).**
`SDL_VIDEODRIVER=x11` only. Isolates "XWayland vs Wayland" from "hidden GL
renderer vs native framebuffer": if E1 works but E2 is still black, the
hidden GL renderer is definitively the black-screen culprit (strongest
possible evidence for the upstream bug report).

**Experiment 3 — confirm the Wayland constraint (zero code, expected to
"fail informatively").** `SDL_FRAMEBUFFER_ACCELERATION=0` on the default
wayland driver → expect control-room open to fail with `"Window
framebuffer support not available"` in the log, live-proving §1's claim.

**Experiment 4 — targeted apitrace of window-2 (only if E0/E1 leave
ambiguity).** As already specified in the investigation doc §7: trace,
`glretrace --headless -v` over the *operator window's own* draw calls, and
`glretrace -s` pixel snapshots right after its `eglSwapBuffers` to see what
the buffer actually contains.

**Experiment 5 — minimal standalone reproducer (for the upstream report).**
~60 lines of pysdl2: window A with a GL context clearing a color each
frame, window B with `SDL_RENDERER_SOFTWARE` animating a fill. If B goes
black on this machine, that is a clean SDL2 bug report (and worth checking
against system SDL2 / sdl2-compat too). Worth writing only once E0–E2 have
localized the failure.

---

## 6) Recommended sequence

1. Owner runs **E0 + E1 + E2** (one small diagnostic commit + two env-var
   launches — minutes of work).
2. If E1 is clean → land **M1** (gated hint + tests + docs) and make M2 the
   documented Wayland workaround in both drop-ins' troubleshooting pages.
3. Decide **M3 vs M4** for Wayland-native: if v1.0 timeline allows ~2
   weeks, go straight to M4 (separate process) and skip M3; otherwise M3
   as the bridge.
4. File the upstream SDL2 issue with the E2/E5 evidence either way — the
   hidden texture framebuffer breaking a co-resident GL context is
   SDL's own acknowledged FIXME, and a small repro may get it fixed in
   2.32.x or at least documented.
5. Fold results back into the investigation doc (§7) and the audit doc
   (item 11) — whichever experiment resolves the black screen closes that
   item.
6. Opportunistic cleanups alongside M1: `is_open` gating in
   `_present_subsystems()`; consider a shared second-window helper so
   control-room/dj-mixer stop diverging.

## 7) Verification protocol

- Existing regression suites to keep green:
  `tests/test_present_subsystems_gl_rebind.py`,
  `tests/test_stream_pbo_diagnostics.py`, both drop-ins' window/lifecycle
  tests (`test_ui_gl_rebind.py`, `test_ui_surface_refresh.py`).
- New tests with M1: hint set iff driver is x11; hint set before any
  window-surface creation; Wayland leaves the hint untouched.
- Owner acceptance matrix (mirrors the multi-head validation matrix):
  GNOME Wayland (native + M2/XWayland), GNOME on Xorg or Classic, MATE/X11
  — each with: open Control Room alone, Mixer alone, both; toggle
  repeatedly; quit from each state. Confirm: windows visibly render, no GL
  errors, clean shutdown, `faulthandler` log empty.

## 8) Implementation update — M3 landed (2026-07-09, same day)

M3 (explicit-GL operator window) was implemented rather than started with
M1/M2, on the owner's call — M2 (XWayland + `SDL_FRAMEBUFFER_ACCELERATION=0`)
had already been tried and, while it did display the windows, was slow and
left the mixer window largely unresponsive. Since M3 removes the hidden
SDL texture-framebuffer path (and XWayland) entirely rather than working
around it, those two symptoms are a different code path and need
re-testing against this implementation, not assumed fixed or unfixed by it.

**What was built:**

- `unicornviz/secondary_gl_window.py` (new core module) — `SecondaryGLWindow`,
  a shared helper owning a second SDL window with its own explicit,
  independent GL context (`SDL_WINDOW_OPENGL` + `SDL_GL_CreateContext`, no
  `SDL_GL_SHARE_WITH_CURRENT_CONTEXT`). `present(raw_rgba, w, h)` uploads
  into a moderngl texture, draws one textured triangle-strip quad, and
  swaps — bracketed by `SDL_GL_GetCurrentWindow()`/`GetCurrentContext()` +
  restore, so `create()`/`present()`/`destroy()` always leave whatever GL
  context was current before them current again, regardless of success or
  failure. This addresses hypothesis H1/H2/H3 from §3 by removing SDL's
  hidden renderer from the picture entirely rather than diagnosing it
  further — both drop-ins previously duplicated (and once diverged on) this
  window-lifecycle code, so it was hoisted into core instead of cloned a
  third time.
- `control-room-01/control_room.py` and `dj-mixer-01/ui.py` — both
  `_create_window()`/`present()`/`_destroy_window()` rewritten to use
  `SecondaryGLWindow` instead of `SDL_CreateRenderer(...,
  SDL_RENDERER_SOFTWARE)` + `SDL_RenderPresent`. The render-thread PIL
  output changed from `.tobytes('raw', 'BGRA')` to plain `.tobytes()`
  (RGBA) to match `moderngl.texture()`'s upload format — the old BGRA
  order was specific to `SDL_PIXELFORMAT_ARGB8888`, which no longer exists
  in this path.
- `App._present_subsystems()` (`unicornviz/app.py`) is unchanged and still
  calls `rebind_main_gl_context()` after any subsystem presents — now
  redundant for control-room/mixer specifically (`SecondaryGLWindow`
  brackets its own context switches) but left in place as defense-in-depth
  for any future subsystem that doesn't use this helper.

**Verification performed this session:**

- `tests/test_secondary_gl_window.py` (13 tests, main repo) — fakes for
  both `sdl2` and `moderngl`, covering create/present/destroy success and
  failure paths, context-restore-on-every-exit-path, and resize-only-when-
  size-changes. One of these tests caught a real bug before it shipped:
  the first implementation called `moderngl.Context.clear()`, which
  doesn't exist on `Context` (only on `Framebuffer`) — fixed to
  `self._mgl_ctx.screen.clear(...)`.
- `drop-ins/dj-mixer-01/tests/test_ui_gl_rebind.py` and
  `test_ui_surface_refresh.py` rewritten to fake `SecondaryGLWindow`
  itself rather than exercising real GL — SDL's `dummy` video driver (used
  for headless testing throughout this repo) has **no GL support at all**
  (confirmed directly in SDL2 source, `src/video/dummy/SDL_nullvideo.c`),
  so the previous tests, which constructed a real `MixerWindow` under the
  dummy driver, would now fail outright. Real GL mechanics are covered by
  `test_secondary_gl_window.py` instead. Full dj-mixer-01 suite: 101/101
  passing.
- Three manual, real-hardware smoke tests (this machine: Fedora 44, GNOME/
  Wayland, Mesa 26.1.3, Intel Iris Xe) against actual SDL2 + moderngl, not
  fakes — not part of the regression suite, one-off verification: (1) a
  bare `SecondaryGLWindow` presenting solid-color frames alongside a real
  main GL context; (2) the real `MixerWindow` class end-to-end (create,
  10 presents, close); (3) `control_room.py`'s real
  `_create_window`/`present`/`_destroy_window` end-to-end. All three
  passed — windows opened, presented, and closed cleanly, and the main
  context was verified current again (by address, via
  `SDL_GL_GetCurrentWindow()`) after every single call into the second
  window's lifecycle.
- Full main-repo suite: 662/662 passing.

**Not yet verified (at the time this section was first written):** actual
visual confirmation on the owner's machine. See §9 for what happened next.

## 9) Second wall and fix — moderngl can't attach to a second context on native Wayland

Owner testing of the §8 landing found: forcing `SDL_VIDEODRIVER=x11` on
the command line, both windows opened, presented, and worked well (mixer
was hard to fully judge without a music library loaded). But the app's
*default* configuration forces `SDL_VIDEODRIVER=wayland`
(`unicornviz/app.py::_init_sdl`), and under that native-Wayland session
the mixer window failed to open with:

```text
dj-mixer-01: mixer window failed to open: (detect) glXGetCurrentContext: cannot detect OpenGL context
```

**Root cause**, traced directly in `moderngl`'s and `glcontext`'s own
Python source (both pure-Python, no need to guess from a compiled
traceback): `moderngl.create_context()` caches a single context per
process in `glcontext`'s `_store.default_context`. The *first* call in a
process (the main app's own `_init_moderngl()`) takes a fast path that
just wraps whatever context is already current. Every call after that —
including `SecondaryGLWindow.create()`'s call — falls into `mode="detect"`,
and `glcontext.default_backend()` **unconditionally returns the x11
backend on Linux** (`glcontext/__init__.py::default_backend`) — there is
no Wayland branch at all. `glcontext` does ship an `egl` backend, but only
as a `standalone` (headless, pbuffer-based) context creator reachable via
`get_backend_by_name('egl')`, not as a "detect the context SDL just made
current" mode — so there is no way to make the public `moderngl.
create_context()` API attach to a second, already-current, window-bound
EGL context on native Wayland at all. This is a structural gap in
`glcontext`, not a bug in this project's usage of it. Confirmed by
forcing `SDL_VIDEODRIVER=wayland` on the earlier (moderngl-based) smoke
test script and reproducing the exact same exception locally.

**Fix:** rewrote `unicornviz/secondary_gl_window.py` to not use `moderngl`
at all for the second window. It now loads the ~20 OpenGL 3.3 core
entry points it actually needs (one texture, one shader program, one
vertex array, one draw call) directly via `SDL_GL_GetProcAddress`, which
SDL itself implements portably across every video backend it supports
(X11, native Wayland, Windows, macOS) — the exact mechanism SDL's own
examples use for GL, and the same portability guarantee `SDL_GL_
CreateContext`/`SDL_GL_MakeCurrent`/`SDL_GL_SwapWindow` already had (those
were never the problem — only moderngl's separate, GLX-only "attach to an
existing context" path was). The public `SecondaryGLWindow` API
(`create()`/`present()`/`destroy()`/`.width`/`.height`/`.window`/
`.window_id`/`.is_open`) is unchanged, so neither drop-in needed any
further changes beyond this module.

**Verification:** all 15 unit tests (fakes for `sdl2` and the new internal
`_GLBinding`, no `moderngl` involved) plus three real-hardware smoke tests
re-run with `SDL_VIDEODRIVER=wayland` forced explicitly — the exact
condition that broke before. All passed: bare `SecondaryGLWindow`, the
real `MixerWindow`, and `control_room.py`'s real window lifecycle, each
opening/presenting/closing cleanly under native Wayland. Full main-repo
suite: 664/664 (662 + 2 new). Owner's own visual confirmation on native
Wayland is still the only thing left unverified.

## 10) Cursor visibility over control-room/mixer windows

Reported alongside the `SDL_VIDEODRIVER=x11` test: the mouse cursor was
very hard to see over Control Room and effectively invisible over the
mixer window.

**Root cause:** `SDL_ShowCursor` is a single, process-global setting — it
cannot be scoped to one window. `App._set_cursor_visible(App.
_cursor_should_be_visible())` already runs once per frame, early (right
after event polling), and hides the cursor by default (fullscreen VJ
visuals). control-room-01's own `present()` — which runs later in the same
frame, after `SDL_GL_SwapWindow` — called `SDL_ShowCursor(SDL_ENABLE)`
unconditionally on every frame it was open, racing against the main
loop's own decision from earlier that same frame (and again at the start
of the *next* frame, before control-room's next present() call). The net
effect was the cursor flickering shown/hidden every frame rather than
staying reliably visible. dj-mixer-01's `ui.py` had no `SDL_ShowCursor`
call at all, so its window never showed the cursor.

**Fix:** promoted cursor visibility to a single authoritative policy.
Added `DjMixerController.is_open` (mirroring `ControlRoomController.
is_open`, which already existed) and `App._subsystem_window_open()`,
which checks `getattr(subsystem, 'is_open', False)` across every
registered subsystem. `App._cursor_should_be_visible()` now also returns
True whenever any subsystem window is open. Removed control-room-01's own
`SDL_ShowCursor` call entirely — there is now exactly one place per frame
that decides cursor visibility, and it already runs regardless of which
subsystem window (if any) is open. 8 new tests
(`tests/test_cursor_visibility_subsystem_windows.py`) plus 1 for
`DjMixerController.is_open` itself.

## 11) References

- SDL2 source (branch `SDL2` = 2.32.x, verified locally this audit):
  `SDL_video.c` — `ShouldAttemptTextureFramebuffer` (line ~2678),
  `SDL_CreateWindowTexture` (~234), sticky `checked_texture_framebuffer`
  (~2734), FIXME acknowledging our scenario (~2744);
  `SDL_render_sw.c:964-971` (`SW_RenderPresent` →
  `SDL_UpdateWindowSurface`); `SDL_render.c:1016-1024` (association
  guards), `SDL_render.c:1004-1009` (Loongson precedent);
  `src/video/wayland/` (no `CreateWindowFramebuffer`);
  `src/video/x11/SDL_x11framebuffer.c` (native X11 path).
- [sdl2-compat #266 — software renderer fails on wayland driver](https://github.com/libsdl-org/sdl2-compat/issues/266)
- [SDL #4335 — multiple Wayland windows stuck when occluded](https://github.com/libsdl-org/SDL/issues/4335)
- [SDL #15208 — sticky checked_texture_framebuffer behavior](https://github.com/libsdl-org/SDL/issues/15208)
- Investigation record: [`docs/debug/control-room-mixer-second-window-investigation-2026-07-09.md`](../debug/control-room-mixer-second-window-investigation-2026-07-09.md)
- Platform audit: [`docs/audits/2026-07-08-render-pipeline-platform-audit.md`](../audits/2026-07-08-render-pipeline-platform-audit.md)
- Prior second-window failure history: [`drop-ins/multi-head-01/MATE-X11-MULTIHEAD-NOTES.md`](../../drop-ins/multi-head-01/MATE-X11-MULTIHEAD-NOTES.md)
