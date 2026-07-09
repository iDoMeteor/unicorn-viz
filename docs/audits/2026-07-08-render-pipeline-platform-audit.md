# Unicorn Viz — Video Render Pipeline & Platform Audit (2026-07-08)

Owner: owner + Claude Sonnet 5 (master coordinator)
Status: In progress — items 1/3 confirmed fixed on owner's machine; item 8
(audience lockup) mitigated; dead mirror-window code removed; item 11's
crash/GL-error-cascade sub-symptom is **confirmed fixed** (two clean,
non-apitrace owner sessions: zero GL errors, clean shutdown, no crash) via
the apitrace-confirmed root cause — control-room-01/dj-mixer-01's
SDL_RenderPresent() switches the current EGL context and never switches
back, fixed by `_present_subsystems()` rebinding once per frame. However,
item 11's **visual black-screen symptom is confirmed still open** as a
separate, unresolved bug — it reproduces in the same clean sessions with
zero errors and successful "first frame produced/presented" diagnostics.
See "Status Update 3" below for the full writeup and
`docs/archive/debug/control-room-mixer-second-window-investigation-2026-07-09.md`
for the definitive two-day narrative. Items 4/5 (GNOME panel + overlay
migration) still open, not started.
Last updated: 2026-07-09

Scope: Owner-reported Fedora-44/GNOME/Wayland-only issues — control-room-01
crashing shortly after first frame, dj-mixer-01 crashing shortly after first
frame (previously worked on Windows), the GNOME top panel remaining visible
in mirror mode, and overlays migrating to the wrong monitor after a virtual
desktop switch in mirror/span mode. Plus a general sweep of `logs/` (~1300
files) for anything else worth flagging.

Method: static code review of `drop-ins/control-room-01/`,
`drop-ins/dj-mixer-01/`, `drop-ins/multi-head-01/`, and the relevant
`unicornviz/app.py` / `unicornviz/overlays.py` window/display code, plus
grep-based forensics across the full `logs/` corpus. No live GPU/Wayland
reproduction was run this pass (see §6 for a proposed repro protocol).

---

## Status Update — 2026-07-09

**Item 1 (dj-mixer-01 missing GL rebind) — fixed and confirmed.** Owner
tested: control-room and mixer windows opened, app quit cleanly, no crash,
no ALSA/EGL error trace, and `faulthandler_*.log` was 0 bytes (no native
crash caught). Fix: `rebind_main_gl_context()` calls added to
`dj_mixer_controller.py` (open/close) and `ui.py`'s own `_destroy_window()`
(covers the self-close-via-Esc path too, mirroring control-room-01's
pattern exactly). 19 new tests, `ef48171`/`4603256` in `dj-mixer-01`.

**Item 3 (faulthandler) — fixed and confirmed working** — it's what
produced the empty `faulthandler_*.log` files that confirmed item 1. 4 new
tests, `9306fe4` in the main repo.

**New finding — item 1's fix uncovered a second, previously-masked bug.**
The same owner session that confirmed no more crashes also reported both
control-room and dj-mixer windows rendering **black**. Investigation found
`docs/archive/debug/control-room-debug-handoff.md` had already chased this
exact symptom across six prior fix attempts on control-room-01, concluding
GNOME/Mutter can hand a freshly-(re)mapped SDL window a stale surface that
blits as black until something forces a fresh commit — control-room-01 has
a `_needs_surface_refresh` mechanism for exactly this (reset on
`EXPOSED`/`SHOWN`/`RESTORED`/`FOCUS_GAINED`), but **dj-mixer-01, despite
cloning the rest of control-room-01's window approach, never picked up this
part of it**. Working theory: this bug was always present in both, but the
crash (item 1) killed the process before it became visible; fixing item 1
let execution proceed far enough to hit it.

Action taken: ported the stale-surface-refresh fix into dj-mixer-01's
`ui.py`, and added one-shot "first frame rendered" / "first frame
presented" diagnostic logging to both drop-ins so a future black-window
report shows exactly which stage failed. 6 new tests
(`test_ui_surface_refresh.py`), `4603256`/`eee7f0f` in the respective
drop-in repos, `51391cf` in the main repo. **Not yet confirmed fixed** —
needs a fresh session log to verify (see §8, item 2 revised).

**Dead code cleanup.** Investigating item 4 (GNOME panel suppression)
surfaced that a per-monitor-SDL-window approach for `mirror_all` was already
tried and abandoned (`drop-ins/multi-head-01/MATE-X11-MULTIHEAD-NOTES.md`,
"Iteration 1") — it went black/froze/crashed on Fedora 37/GNOME, Fedora
44/MATE, *and* Windows 11. The dead code from that attempt
(`create_mirror_outputs`/`destroy_mirror_outputs`/`resize_mirror_textures`/
`present_mirror_outputs`/`is_mirror_window_id` in `multihead.py`, and their
no-op call sites in `app.py`) has been removed. The shared-GL-context
variant (never implemented, listed as an alternative in the same doc) is
now explicitly marked as the preferred direction *if* per-monitor windows
are ever revisited for panel suppression — it's architecturally distinct
from the removed CPU-readback approach and shouldn't inherit its failure
history automatically, but remains unproven in this codebase.

**New finding — a third, distinct symptom: audience effects locking up
while the HUD keeps updating.** Owner testing after the above fixes (both
control-room and dj-mixer open simultaneously, `mirror_included` across 3
displays) reported the audience output flashing partial/black then locking
up entirely, while the HUD kept rendering live — i.e. the main loop and
Python were not hung, only effect rendering stalled. `journalctl`
cross-referenced against the session log showed GNOME Shell logging its own
internal assertion failures (`surface_constraint_data_new: code should not
be reached`, a `g_return_if_reached()`-class Mutter bug) and "invalid
window geometry... Working around" for every window opened, including the
*main* audience window at startup — before Control Room or the mixer ever
opened. `coredumpctl`/`dmesg` showed no OOM kill, no GPU reset, no core
dump, and gnome-shell (pid stable throughout) never restarted — ruling out
a hard crash on either side and pointing to a hang. (Owner's monitor layout
— two 1920×1080 @ 200% above a 3840×2160 @ 100–200% — was confirmed
intentional, not a detection bug, so the geometry Mutter is complaining
about is a real mixed-DPI-scaling layout, not bad EDID data.)

Root cause identified in `app.py`'s `_read_streaming_frame()`
(`app.py:5722`): once the async PBO readback path fails once — which it
does reliably every session ("cannot map the buffer") — it permanently
falls back to a **synchronous** full-resolution `source.read(...)`
(effectively `glReadPixels`) for the rest of the session, driven by
control-room's `needs_frame_bytes`. At `mirror_included`'s full spanned
canvas (3840×2160 in the reported session) that's a ~24MB synchronous
GPU→CPU transfer roughly 10×/second (the existing 0.1s throttle) — heavy
enough on integrated graphics to stall the GL command queue for that frame,
matching "effects lock up, HUD keeps going." The comment already at that
call site (`app.py:4476-4481`) documents this exact failure mode as *"the
primary cause of the audience-output freeze observed while the
control-room operator window is open"* — a known, previously only
partially mitigated issue, not something introduced this session.

**Fix landed:** the subsystem-preview capture throttle now checks
`self._stream_pbo_disabled` and widens from 0.1s to 1.0s once the fallback
path is active (`app.py`, in the commit that also added the shared BPM hint
bus — `945a865`), cutting the expensive synchronous read rate ~10×. Not
independently unit-tested (see note below) — this specific branch is a
one-line ternary gating an existing, already-tested code path, and
extracting it into a testable helper was judged not worth another isolation
pass on a heavily-concurrently-edited file; low regression risk.

**Deferred as a follow-up, not investigated further this pass:** *why* the
PBO buffer mapping fails with "cannot map the buffer" in the first place.
That's a Mesa/Iris Xe-under-Wayland driver-behavior question that needs
live GL debugging (`MESA_DEBUG`, checking `glGetError()` around the
`read_into`/`.read()` calls, whether it's a fence/sync timeout vs. a hard
mapping failure) rather than static analysis. The throttle mitigation above
should make the symptom much less severe regardless of the root cause, but
doesn't fix the underlying PBO failure itself.

**Also found, unrelated:** a real, reproducible `KeyError: 'iBass'` crash
in `drop-ins/feature-01/rainbow_trance.py:286` — the shader declares
`uniform float iBass;` (line 31) but never references it in the fragment
logic, so Mesa's GLSL compiler strips it as dead code and
`self._prog['iBass'].value = ...` throws at runtime. Confirmed still
present as of the latest `feature-01` bump (`ee7b4ff`). Not fixed this
pass — flagging for a separate task.

---

## Status Update 2 — 2026-07-09 (apitrace: the real root cause, item 11)

Three targeted fixes (`source.use()`, viewport pinning, the moderngl
default-framebuffer blit workaround) each addressed a real, verifiable bug
but none stopped the black-screen symptom, and owner testing kept showing
the same massive GL error cascade after each one — just with the specific
trigger error shifting. Rather than keep guessing from Mesa's error text,
installed `apitrace` (`sudo dnf install apitrace`) and had the owner
capture two live traces (`apitrace trace -a egl -o trace.trace -- ...`,
opening Control Room / DJ Mixer respectively).

**Definitive finding**, read directly out of the trace, not inferred:
control-room-01/dj-mixer-01's `SDL_RenderPresent()` on their own second SDL
window silently calls `eglMakeCurrent` to switch to their own internal EGL
context — call 34699 in the trace — runs a sequence of legacy
client-array GL calls (`glEnableClientState`/`glTexCoordPointer`/etc., SDL's
own internal blit implementation), calls `eglSwapBuffers` for control-room's
window at call 34718, and **never switches back**. The very next GL call
from our own app (`glUseProgram(124)` at call 34812) immediately fails with
`GL_INVALID_VALUE`, because program 124 — a perfectly valid object in
*our* context — doesn't exist in whatever context is now current. Every GL
call for the rest of the session runs against the wrong context: this is
the actual source of the `glUseProgram`/`glBindVertexArray`/`glUniform`/
`glBufferSubData` cascade chased across items 1, 9, and 11.

This does not invalidate the earlier fixes — `rebind_main_gl_context()` on
control-room create/destroy (item 1) was a real, necessary fix for the
original crash; the moderngl default-framebuffer read bug (item 9) is real
and confirmed against moderngl's own upstream source. Neither one was the
cause of *this* symptom, because both only rebind once per window
open/close, not every frame where `present()` actually runs — and
`present()` runs every single frame control-room/mixer are open.

**Fix** (`4e26b4c`): the per-frame subsystem-present loop in `run()` was
extracted into `App._present_subsystems()`, which now calls
`self.rebind_main_gl_context()` once after the loop, gated on whether any
subsystem has a callable `present()` attribute that frame — and rebinds
even if a presenter raised, since the context can move before a partial
failure.

**Correction (Status Update 3):** the "so it costs nothing when
control-room/mixer aren't open" framing above is not accurate for
dj-mixer-01 specifically. `DjMixerController.present()`
(`dj_mixer_controller.py:287`) is always a callable method once the
drop-in loads — it internally no-ops via `if self._window is not None`
rather than being absent/replaced when the window is closed — and
`[dj_mixer].enabled = true` by default, so `getattr(subsystem, 'present',
None)` is truthy essentially every frame regardless of whether the mixer
window is actually open. The rebind itself is cheap (0.01–0.03ms observed,
see Status Update 3), so this is not a correctness bug, just a stale
claim about when the gate actually engages — left as a known, minor,
not-yet-actioned cleanup opportunity (tighten the gate to check window
open state, e.g. `getattr(subsystem, 'is_open', True)`) rather than
something requiring immediate attention.

See "Status Update 3" immediately below for full owner-confirmed
verification results.

---

## Status Update 3 — 2026-07-09 (owner-confirmed: crash fixed, black screen still open)

Two clean, non-apitrace owner test sessions
(`logs/unicornviz_20260709_143729.log`,
`logs/unicornviz_20260709_143935.log`) — both with control-room and/or
dj-mixer opened and closed during the session — independently confirm:

- **Zero** `GL_INVALID_*` / GL error lines of any kind.
- **Zero** exceptions or crashes; clean shutdown sequence both times.
- `subsys_present` per-frame timing stayed in the 0.01–0.03ms range (the
  `rebind_main_gl_context()` call is not a measurable cost).
- Both sessions' `faulthandler_*.log` files are empty (no native crash).

This is decisive confirmation that the `_present_subsystems()` fix (item
11's crash/cascade sub-symptom) works as intended.

**However**, both sessions — and every clean session run since — still
showed control-room's and dj-mixer's own windows as **visually black**,
despite:

- `Control room: render thread produced its first frame` /
  `first frame presented to the compositor` (and dj-mixer's equivalents)
  logging success with no error.
- No GL errors anywhere in the session.

This rules out the GL-context-stealing bug as an explanation for the
visual symptom (it's fixed, and the symptom persists) and rules out all
three of the earlier fix attempts too (§8 item 9, `abd06c1`, `6a9c6ec`).
**The black screen is a distinct, still-unsolved bug.** It reproduces
identically across GNOME Wayland, GNOME Classic, and MATE/X11, ruling out
a compositor-specific cause. See
`docs/archive/debug/control-room-mixer-second-window-investigation-2026-07-09.md`
§7 for the current leading theory (a Mesa/EGL-level issue specific to
presenting a second small SDL_RENDERER_SOFTWARE-backed window's surface
concurrently with a primary OpenGL-heavy context in the same process) and
the recommended next diagnostic step (a targeted `apitrace` capture of
control-room's own window surface presentation specifically, since the
original trace only proved the *main app's subsequent* calls were
corrupted — it never actually verified control-room's own draw calls
against a real-error-checking replay).

One additional data point folded in from a later, unrelated test session
(`logs/unicornviz_20260709_144802.log`): a third clean run with neither
window opened confirms the baseline app remains fully stable on its own —
consistent with, but not adding new information to, the black-screen
question specifically.

---

## 0) Executive Summary

Both reported "crashes shortly after first frame" bugs trace to the **same
architectural pattern**: opening a second SDL window in the same process as
the main OpenGL window. `control-room-01` and `dj-mixer-01` both do this
(dj-mixer-01's own code comments describe it as cloning the control-room-01
approach), but **only control-room-01 carries the GL-context-rebind fix**
that a prior debug session already had to add for exactly this class of bug.
**dj-mixer-01 is missing that fix entirely** — this is a concrete, high-
confidence, low-risk-to-fix bug, not a mystery.

The two GNOME/Wayland display bugs are both explained by **one design gap**:
mirror/span mode never puts the window into real compositor fullscreen (it's
always just an oversized borderless window), and nothing in the event loop
re-derives display/origin state when the compositor silently moves or
restacks that window (workspace switches send no dedicated event on GNOME
Wayland). These are legitimate architecture decisions to revisit, not one-
line bugs — they need a design conversation (§4, §5) before implementation.

No native crash text (`Segmentation fault`, `SIGSEGV`, `Fatal Python error`,
`core dumped`) appears anywhere in the log corpus, which is *expected* and
consistent with the hypothesis: a hard segfault in Mesa/EGL kills the
process before Python-level logging can record anything — the logs simply
stop mid-line. Also found along the way: 8 distinct Python exceptions
recurring across dated logs that were never traced back to this session's
work (§7) and are worth a look regardless of the platform investigation.

| Area | Grade | One-line |
|------|-------|----------|
| control-room-01 second-window handling | B- | Fix already landed once; Linux/Wayland dual-window-in-process risk still unresolved at the driver level |
| dj-mixer-01 second-window handling | **D** | Missing the exact GL-rebind fix control-room-01 already needed — likely root cause of the reported crash |
| Mirror/span fullscreen compositor integration | C | Never requests real fullscreen; GNOME panel suppression was never architecturally possible as built |
| Multi-monitor display-state cache invalidation | C+ | Refreshes on monitor hotplug only; no path refreshes on workspace switch/window restack |
| Log/crash observability | C | No native-crash markers possible from Python logging alone; recommend `faulthandler` + core dump capture (§6) |
| Test coverage of real window/GL lifecycle (control-room-01, dj-mixer-01) | D+ | Both explicitly rely on "validated manually"; zero automated coverage of the actual crash surface |

---

## 1) control-room-01 — Fedora/GNOME crash

**Architecture:** `control_room.py` opens a *second* SDL window in the main
app's process (`_create_window`, `control_room.py:250-348`), rendering its UI
with PIL onto a background thread (`_render_thread_loop`, line 418) and
blitting via `SDL_CreateRenderer(..., SDL_RENDERER_SOFTWARE)` +
`SDL_UpdateTexture`/`SDL_RenderCopy`/`SDL_RenderPresent` (`present()`, line
516) — deliberately avoiding a second GL context.

**What's already been tried and ruled out** (`docs/archive/debug/control-room-debug-handoff.md`):
- Loader/registration bugs, hotkey collisions — fixed.
- Segfault-on-ESC (destroying the window inside its own event handler) — fixed via deferred `_pending_shutdown` teardown.
- "One frame then black" BGRA/XRGB blit mismatch — fixed.
- Audience-render freeze from 60fps `glReadPixels` while the preview is open — fixed via a 100ms readback gate (`app.py:4479-4494`).
- Per-frame defensive `SDL_GL_MakeCurrent` rebind — tried, made things *worse*, reverted. Only a one-shot rebind on create/destroy remains (`app.py:767`, `794`, calling `rebind_main_gl_context()` at `app.py:639`).
- Key-repeat double-toggle / zombie controller re-creation — fixed with a `_control_room_creating` guard (`app.py:741`).
- Raw `SDL_GetWindowSurface` path replaced entirely with the current `SDL_CreateRenderer(SOFTWARE)` approach specifically because raw window-surface blitting was judged incompatible with Wayland when a GL client owns the primary window.

**Log evidence:** every log where `SDL video driver: wayland` and the
control room is opened (34 of 36 control-room-mentioning logs; examples:
`logs/unicornviz_20260617_065818.log`, `logs/unicornviz_20260707_195801.log`,
`logs/unicornviz_20260707_211138.log`) **ends immediately** at "ControlRoomController loaded from drop-in" / "control room window opened" — no
exception, no shutdown log. The 2 x11-driver control-room logs do not show
this. This is the signature of a native crash (segfault) inside SDL/Mesa/EGL,
not a Python-level failure.

**`logs/unicornviz_20260707_211138.log` also shows a second, separate
symptom:** two consecutive "window opened"/"loaded from drop-in" pairs with
**no destroy logged in between** — the existing zombie-guard
(`_control_room_creating`) may not be closing the loop in every code path
(e.g. a second toggle firing before the flag resets).

**Ranked hypotheses:**
1. **Most likely — Mesa/EGL multi-window crash under Wayland.** Creating a second SDL window + software renderer in the same process as an already-current EGL context crashes natively in Mesa's Wayland EGL backend at window/renderer/texture creation or the first `SDL_RenderPresent`. Every wayland log dies exactly at window-open; every x11 log survives. Not proven from source alone — needs a live repro with `MESA_DEBUG=1`/`WAYLAND_DEBUG=1` (§6).
2. **Double-creation race** — a second `SDL_CreateWindow`/`SDL_CreateRenderer` firing on Wayland while the first window is still alive (per the log above) is independently plausible as a trigger, layered on top of hypothesis 1.
3. Render-thread/main-thread race between the PIL background thread and `rebind_main_gl_context()`'s `SDL_GL_MakeCurrent` call — lower confidence, no direct evidence.

**Other smells (unrelated to the crash):** `troubleshooting.md` and
`test-matrix.md` are dated 2026-06-07 but never mention the hard-crash-on-open
symptom, despite it appearing in logs both before and after that date — docs
are stale relative to reality. Test coverage
(`test_hotkeys_m_family.py`, `test_modal_mutual_exclusion.py`) only exercises
`toggle_control_room()` against a stub `App` — zero automated coverage of
actual window/renderer/texture creation.

---

## 2) dj-mixer-01 — Fedora/GNOME crash (worked on Windows previously)

**This is the same bug class as §1, but with the fix missing.**
`drop-ins/dj-mixer-01/ui.py` (`MixerWindow._create_window`, lines 126-174)
opens its own second SDL window + `SDL_RENDERER_SOFTWARE` renderer, by the
module's own admission cloning control-room-01's approach. But:

```
grep -rn "rebind_main_gl_context" unicornviz/app.py drop-ins/control-room-01/ drop-ins/dj-mixer-01/
unicornviz/app.py:639:    def rebind_main_gl_context(self) -> bool:
unicornviz/app.py:767:            self.rebind_main_gl_context()
unicornviz/app.py:794:        self.rebind_main_gl_context()
drop-ins/control-room-01/control_room.py:396:            self._vj.rebind_main_gl_context()
```

**dj-mixer-01 has zero references to `rebind_main_gl_context` anywhere** —
not in `ui.py`, not in `dj_mixer_controller.py` (`open_window` at line 184,
`close_window` at line 196, `shutdown` at line 259 — none of them call it),
and `app.py` never calls it for the mixer window either (the `_create_control_room`/`_destroy_control_room` call sites at 767/794 are
control-room-specific). Opening or closing the mixer's second SDL window can
leave the main GL context unbound/stale, so the next moderngl draw call on
the main thread — i.e. the very next audience frame — is a highly plausible
segfault trigger. This lines up exactly with "crashes shortly after the
first frame renders when the mixer is opened," and Windows' WGL context
handling is different enough from Linux GLX/EGL that this would plausibly
not reproduce there, matching "worked fine on Windows."

**Log evidence:** `logs/unicornviz_20260708_121750.log` ends at:
```
INFO [dj_mixer_ui] dj-mixer: window opened on display 1 (1280x800)
INFO [...dj_mixer_controller] dj-mixer-01: REV1 input opened (device 'rev1' not found yet)
INFO [...dj_mixer_controller] dj-mixer-01: mixer window opened
INFO [...dj_mixer_controller] dj-mixer-01: REV1 input released
```
— no further logging at all. No exception anywhere in the corpus.

**Independent secondary risk:** `rev1_leds.py` and the REV1 input path open
their own `rtmidi` ports on every window toggle (a prior fix already scoped
this to open-only-while-open, per the "REV1 opened only while mixer window
is open" commit — this was itself a response to a real prior USB-audio/ALSA
`snd_ump` kernel-level destabilization bug, see that commit's message). This
is a plausible source of *other* MIDI flakiness but is lower-probability for
a crash specifically timed to first-frame-after-open.

**Recommendation:** add the same one-shot `rebind_main_gl_context()` calls
dj-mixer-01 is missing — mirroring exactly where control-room-01 calls them
(on window create and on window/renderer destroy) — as the first, cheapest,
highest-confidence fix to try. This alone will not resolve hypothesis 1 in
§1 if that's also in play for dj-mixer-01 (it uses the identical
window/renderer pattern), so plan to re-test control-room-01-style crashes
even after this fix lands.

**Other smells:** `dj-mixer-01/tests/test_ui_accessors.py` states outright
that the real SDL/PIL window is "validated manually" — no automated coverage
of window open/close exists, which is exactly the gap that let the missing
rebind call ship unnoticed.

---

## 3) General log/OS forensics (whole `logs/` corpus, ~1300 files, 476 run logs sampled)

- **Zero** occurrences anywhere of `Segmentation fault`, `SIGSEGV`, `Fatal
  Python error`, `core dumped`, `GLError`, `moderngl.error`,
  `PaAlsaStreamComponent`, `alsa_snd_pcm`, `snd_seq_hw_open`, or `Cannot
  allocate memory`. This absence is itself the evidence for §1/§2's "native
  segfault, not Python exception" theory — see §6 for how to actually catch
  one.
- **25 Python tracebacks** across the corpus, none related to control-room
  or dj-mixer-01. Distinct exception types found (§7) — worth separate
  triage since some look like real, easily-fixable bugs.
- **455 wayland vs 19 x11** sessions logged. Crash-file ratio is
  proportionate to base rate (no signal that x11 is categorically safer),
  but the most recent 100 sessions are 99 wayland — recent x11 comparison
  data doesn't really exist anymore.
- **54 of the most recent 100** run logs end abruptly mid-operation with no
  shutdown-related logging at all (not just control-room/mixer — this is
  the general "silent death" rate for the app on this machine right now).
  42 more show the audio-reader-thread-shutdown warning path (expected/
  benign per the fix landed earlier this week). Only ~2/100 end in an actual
  Python traceback. **The overwhelming majority of exits on this machine
  right now are silent, non-Python-level deaths** — this is bigger than
  control-room/dj-mixer specifically and worth its own investigation (§6).
- Mesa versions seen: 26.0.5 → 26.1.3, monotonically increasing — single
  machine, not multi-machine variance; rules out "different GPU/driver per
  run" as an explanation for the crash's intermittency.
- One log (`logs/unicornviz_20260618_091426.log:62`) contains the line
  "Applying GNOME multi-head desktop fullscreen policy" — this text does not
  exist anywhere in current `app.py`, `multi-head-01`, or any reachable git
  revision (`git log --all` searched). Looks like a previously-tried
  GNOME-specific fullscreen fix that was fully reverted without a trace in
  history, or a stale binary/pyc from an older branch was run that day.
  Worth asking the owner if they remember trying something here — it may be
  directly relevant to §4.

---

## 4) GNOME panel visible in mirror mode

**Root cause:** mirror/span mode never requests real compositor fullscreen.
Both modes create **one borderless SDL window spanning the union of all
display bounds** (`app.py:1221-1229`):

```
1221:        flags = sdl2.SDL_WINDOW_OPENGL | sdl2.SDL_WINDOW_RESIZABLE
1224:            flags = sdl2.SDL_WINDOW_OPENGL | sdl2.SDL_WINDOW_BORDERLESS
1227:                flags |= sdl2.SDL_WINDOW_BORDERLESS
1229:                flags |= sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP   # single-display mode only
```

`SDL_WINDOW_FULLSCREEN_DESKTOP` is only ever applied in **single**-display
mode (also `app.py:5142` in `set_display_mode`). Effects render at one
logical resolution into an FBO and get tile-blitted per-monitor
(`_present_mirror_tiled`, viewport rects from `MultiHeadController.mirror_layout()`, `drop-ins/multi-head-01/multihead.py:142-151`).

Mutter's panel-hiding logic activates only when a client surface enters the
compositor's actual fullscreen state (`xdg_toplevel` fullscreen) on a single
output. A borderless oversized window — no matter how large — never
triggers that, so the panel is never suppressed. The one existing
mitigation, `_prefer_borderless_fullscreen()` (`app.py:1036-1053`, a MATE
workaround), is also never consulted for span/mirror. The Wayland→X11
auto-fallback for multi-head modes (`app.py:1197-1211`) only changes the
video driver, not the fullscreen flag, so it doesn't help either.

**This is a real design constraint, not a one-line fix:** Wayland fullscreen
is inherently per-output — a single window cannot be "exclusively
fullscreen" across multiple physical monitors at once the way X11 allowed.
Two realistic paths forward, worth discussing before picking one:
- **Option A** — one borderless+undecorated window per monitor (instead of
  one big spanning window), each individually requesting real fullscreen on
  its own output. This is architecturally the "correct" Wayland-native
  approach but is a real rework of the mirror/span present path (the dead
  per-display-window code at `multihead.py:294-443` — see §7 — was
  apparently an earlier attempt at exactly this and was abandoned/made a
  no-op; worth understanding why before retrying).
  - **Downside:** you *cannot* have visual continuity/exact one-window
    parity across the two outputs (e.g. seamless offsets or genuinely
    "spanning" imagery) with fully separate per-output windows — a subtle
    but often invisible seam or frame-timing skew can appear at the monitor
    boundary, which single spanning-window mirror mode currently avoids by
    construction.
- **Option B** — keep the single spanning window, but instruct
  GNOME/Mutter to treat it as fullscreen anyway, e.g. via layer-shell/
  `_NET_WM_STATE_FULLSCREEN` hints or an `xdg-shell` fullscreen request
  scoped to the union geometry. This is compositor-specific, fragile, and
  the owner has already tried something in this space once (see the
  orphaned log line in §3) — worth confirming what that was and why it
  didn't stick before re-attempting.

---

## 5) Overlays land on the wrong monitor after a virtual desktop switch (mirror/span)

**Root cause:** cached display/origin state is never invalidated by a
workspace switch, because GNOME/Wayland doesn't send SDL a dedicated
"workspace changed" event, and nothing else in the event loop happens to
catch the resulting drift.

- `App._display_index` and the layout/origin state used for overlay
  placement (`self._window_origin_x/_y`, `_display_layouts`,
  `_primary_active_layout()`) are refreshed only in three places:
  `_init_sdl` (`app.py:1231`, `1296`), `set_display_mode`
  (`app.py:5107-5113`, `5174`), and the `SDL_DISPLAYEVENT` handler
  (`app.py:3824-3830`) — which only reacts to
  `SDL_DISPLAYEVENT_CONNECTED`/`DISCONNECTED` (monitor hotplug), calling
  `_rebuild_multihead_outputs()` (`app.py:1084`,
  `multihead.py:452-462`).
- The `SDL_WINDOWEVENT` handler (`app.py:3604-3620`) only handles `RESIZED`,
  `FOCUS_LOST`, and `FOCUS_GAINED` — and `FOCUS_GAINED` (`app.py:3619`) only
  toggles cursor visibility, it does **not** re-derive display/origin state.
  There is no `SDL_WINDOWEVENT_MOVED` or `SDL_WINDOWEVENT_DISPLAY_CHANGED`
  handling at all.
- `App._primary_display_viewport()` (`app.py:933-947`) deliberately *avoids*
  re-querying `SDL_GetWindowPosition` in favor of the cached layout-space
  origin, specifically "to avoid compositor-dependent drift" — falling back
  to a live query only when the cached origin happens to be `(0,0)`. This
  defensive choice backfires exactly in this scenario: if Mutter silently
  remaps/restacks the window onto a different output arrangement during a
  workspace hide/show cycle, nothing invalidates the stale cache, and
  overlays keep rendering against outdated geometry.

**Recommended direction (for discussion, not yet implemented):** re-derive
display/origin state on `SDL_WINDOWEVENT_FOCUS_GAINED` (which does reliably
fire when the user switches back to this app's workspace, unlike a
workspace-change event) rather than relying solely on cached values seeded
at startup/mode-switch time. This would need to be done carefully given the
existing comment's concern about "compositor-dependent drift" — likely by
querying and only committing the new origin if it's self-consistent (e.g.
matches one of the known display layout rects) rather than trusting any
single live query unconditionally.

---

## 6) Recommended diagnostic protocol before implementing fixes

Given zero native-crash evidence exists in current logs, the fastest path to
confirming §1/§2's Mesa/EGL hypothesis is to actually capture one:

1. Run with `WAYLAND_DEBUG=1` and `MESA_DEBUG=1` (or `EGL_LOG_LEVEL=debug`)
   piped to a file, reproduce the control-room/dj-mixer open, and check
   whether the process dies inside an EGL/Wayland protocol call.
2. Enable a core dump (`ulimit -c unlimited` / `systemd-coredump` if
   configured) for one repro run and inspect the backtrace with `gdb
   python3 core` — this would immediately confirm or refute the "second
   SDL window in-process" theory as the crash site.
3. Add `faulthandler.enable()` (stdlib, already available) at startup so a
   segfault at least prints a Python-level traceback of the frame that was
   executing, which today produces zero forensic trail (§3's silent-death
   finding applies far beyond just these two drop-ins).

---

## 7) Other bugs/opportunities noticed along the way (not part of the platform investigation)

- **25 distinct Python tracebacks** recur across the log corpus, unrelated
  to control-room/dj-mixer. Grouped by exception, with counts: `RuntimeError:
  Audio capture did not become active` (3), `AttributeError: 'Overlays'
  object has no attribute '_quad_vao'` (3), `KeyError: 'iResolution'` /
  `'iSeed'` / `'iSpeed'` (moderngl uniform-not-found, 4 total),
  `IndexError: Replacement index 1 out of range for positional args tuple`
  (2), `AttributeError: 'App' object has no attribute 'goto_next_camera'`
  (2), plus one-off `TypeError`/`struct.error` in moderngl uniform setters,
  a `GLSL Compiler failed` error, `AttributeError: 'ProjectMEffect' object
  has no attribute '_preset_index'`, `AttributeError: 'Overlays' object has
  no attribute '_sample_system_telemetry'`, an `_render_system_monitor_modal`
  typo'd attribute access ("Did you mean '_show_system_monitor_modal'"),
  `UnboundLocalError` for `audio_hud` and `is_sel`, a `ValueError: Unknown
  format code 's'`, `ValueError: not enough image data`, and one
  `IndentationError` (likely a mid-edit save that got run once). None of
  these were investigated further this pass — flagging for separate triage.
- **`_create_mirror_outputs`/`present_mirror_outputs`** (the legacy
  per-display-SDL-renderer mirror path, `multihead.py:294-443`) is dead code
  — `App._create_mirror_outputs` is a no-op per the drop-in's own notes —
  but is still fully wired into `SDL_WINDOWEVENT_CLOSE` handling
  (`app.py:3604-3611`). Worth confirming it's truly unused and removing, or
  documenting why it's kept around (it may be exactly the "Option A"
  per-monitor-window attempt from §4 that was shelved).
- **The overwhelming majority of recent app exits are silent** (§3) — this
  is a bigger and more general reliability gap than either reported bug;
  worth deciding whether to invest in §6's diagnostics regardless of how the
  two specific crashes get fixed.
- **`docs/troubleshooting.md`** for multi-head already documents span-mode
  framing/scaling drift as a known, separately deferred issue (line ~34-40)
  — not investigated this pass, flagging as still open.
- Both control-room-01's and dj-mixer-01's docs (`troubleshooting.md`,
  `test-matrix.md`) are stale relative to the actual crash behavior
  currently reproducing on this machine — worth a documentation pass once
  fixes land, not before (no point documenting symptoms about to change).

---

## 8) Proposed prioritization (updated 2026-07-09)

| # | Item | Confidence | Effort | Status |
| --- | --- | --- | --- | --- |
| 1 | Add missing `rebind_main_gl_context()` calls to dj-mixer-01's window open/close path | High | Low | **Done, confirmed fixed** — no more crash, `faulthandler` log empty |
| 2 | Black-screen follow-on: port control-room-01's stale-surface-refresh fix into dj-mixer-01 + add first-frame diagnostics to both | High (the missing mechanism was confirmed by direct diff; whether it's the *complete* explanation is not) | Low-Medium | **Fix landed; diagnostics confirm it was not the complete explanation** — "first frame produced/presented" now logs successfully every time, but the black screen persists regardless (see item 11 / Status Update 3) |
| 3 | Add `faulthandler.enable()` at startup for future silent-crash forensics | N/A (diagnostic) | Trivial | **Done** |
| 4 | Decide GNOME panel-suppression approach for mirror/span (Option A vs B, §4) | Medium | Medium-High | Open — Option A (per-monitor windows) reconfirmed risky per `MATE-X11-MULTIHEAD-NOTES.md`'s prior 3-platform failure; shared-GL-context variant now documented as preferred *if* revisited, still unbuilt |
| 5 | Re-derive display/origin state on `FOCUS_GAINED` for mirror/span (§5) | Medium-High | Low-Medium | Open — can proceed in parallel with #4 |
| 6 | Triage the 8 distinct recurring tracebacks in §7 | Unknown per-item | Unknown per-item | Open — lower urgency |
| 7 | Confirm/remove dead `_create_mirror_outputs` path | High (it's dead) | Low | **Done** — removed from `app.py` and `multihead.py`, `MATE-X11-MULTIHEAD-NOTES.md` updated with the reconfirmed decision |
| 8 | Throttle the synchronous PBO-fallback readback harder (0.1s → 1.0s) to stop audience effects locking up while control-room is open | High (matches an already-documented failure mode; direct code-level fix) | Low | **Done** — landed in `945a865`, not yet independently confirmed by the owner |
| 9 | Root-cause why PBO buffer mapping fails ("cannot map the buffer") in the first place | Medium | Low | **Root cause found and fixed, confirmed via clean owner logs** — the PBO `GL_INVALID_VALUE` was a downstream symptom of item 11's GL-context-stealing bug, not a bug in the PBO/viewport code itself; the viewport-pinning fix (`abd06c1`) was defensively correct but insufficient alone. Once item 11's real fix (`4e26b4c`) landed, the PBO errors disappeared entirely — zero occurrences in both post-fix clean sessions. The separate moderngl default-framebuffer `glReadBuffer` bug found along the way (`6a9c6ec`) is also real and fixed, confirmed against moderngl's own upstream source |
| 10 | Fix `KeyError: 'iBass'` in `drop-ins/feature-01/rainbow_trance.py:286` (unused uniform stripped by the GLSL compiler) | High | Low | Open — unrelated to the platform investigation, found incidentally |
| 11 | Root-cause control-room/mixer showing black despite successful render+present (per items 1-2's own diagnostics) | Very high — confirmed directly via apitrace GL call trace, not inferred from error text | Low | **Crash/GL-error-cascade sub-symptom: confirmed fixed** (`4e26b4c`), verified via two clean, non-apitrace owner sessions with zero GL errors and clean shutdown — see "Status Update 3". Real root cause: control-room-01/dj-mixer-01's `SDL_RenderPresent()` calls `eglMakeCurrent` to their own internal EGL context and never switches back, so every subsequent GL call in the main render loop runs against the wrong context. `App._present_subsystems()` now calls `rebind_main_gl_context()` once per frame after subsystem presents. **Visual black-screen sub-symptom: confirmed still open**, reproduces in the same clean, error-free sessions — this is a separate, unresolved bug; see the standalone writeup `docs/archive/debug/control-room-mixer-second-window-investigation-2026-07-09.md` §7 for the current leading theory and next diagnostic step. The three earlier fix attempts in this row's history (`source.use()`, moderngl blit-without-depth, blit-with-depth) were each real fixes for real bugs, just not the cause of either sub-symptom |

If item 2's diagnostics show the black screen persists even after the
surface-refresh fix, the next step per the archived handoff's own "Path 2"
is to instrument `SDL_GL_GetCurrentWindow()`/`glGetError()` around
control-room open/close rather than guessing further — see
`docs/archive/debug/control-room-debug-handoff.md` "Path 2" for the exact
protocol.
