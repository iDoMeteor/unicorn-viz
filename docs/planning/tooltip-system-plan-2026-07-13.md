# Tooltip System — Plan & Full-Surface Audit

Owner: owner + Claude (planning)
Status: **approved — ready for implementation.** All §9 questions decided
by the owner (2026-07-13, recorded inline). §3.4/§5 revised same day to
build on dj-mixer-01's freshly-landed `_Hit` region foundation
(`dj-mixer-01@50a3d4b`, mouse-draggable faders/EQ/crossfader) instead of
proposing a parallel one.
Last updated: 2026-07-13

A unified hover-tooltip system for the three operator-facing UI surfaces:
**control-room-01**, **dj-mixer-01**, and the main window's **overlay
system** (modals, browsers, help rail). This document audits every element
that should carry a tooltip, specifies the text, and designs the shared
implementation in accordance with the project's coding standards and
drop-in policies.

---

## 1) Current state (audit findings)

The three surfaces have three different render stacks and three different
levels of existing mouse support — the design must serve all of them from
one core mechanism:

| Surface | Render stack | Hit-testing today | Mouse motion today |
|---|---|---|---|
| Overlays (main window) | moderngl immediate primitives (`_draw_rect`/`_draw_text` bitmap font), drawn every frame in `Overlays.render()` | Per-modal handlers (`_help_icon_hit_test`, `handle_effects_browser_mouse_motion`, `handle_presets_mouse_motion`, `handle_config_editor_motion`, `handle_context_menu_motion`) | Routed per-modal from `app.py`'s event loop through `_overlay_mouse_coords()` (viewport-corrected) |
| control-room-01 | PIL rasterization on a background thread (~30 fps), uploaded via `SecondaryGLWindow` | `_HitRegion(action, payload, rect)` hotspot list rebuilt every rendered frame, published under `_frame_lock`; **all buttons flow through the single `_draw_button()` choke point** | `SDL_MOUSEMOTION` handled only for slider drags; cursor position not stored |
| dj-mixer-01 | Same PIL-thread + `SecondaryGLWindow` pattern | `_Hit` region list (`50a3d4b`, 2026-07-12): plain `__slots__` regions with `get`/`set` value bindings, rebuilt each render pass beside the widget they mirror, published under `_frame_lock`; drives mouse-draggable faders/EQ/crossfader/master | `SDL_MOUSEMOTION` handled for drags (`_begin_drag`/`_drag_to`/`_end_drag`); cursor position not yet stored outside a drag |

**Existing prior art to generalize, not duplicate:** the help-icon rail in
`unicornviz/overlays.py` already implements a complete one-off tooltip:
entry dicts carry `tooltip` / `tooltip_logged_in` / `tooltip_logged_out`
keys, `handle_help_mouse_motion()` stores a hover index + position, and
`_draw_help_icon_tooltip()` draws an immediate (no-delay) bubble with the
GL primitives. The new system must absorb this call site so there is one
tooltip implementation, not two.

**Hotkey documentation constraint:** per `CLAUDE.md`, `HELP_TEXT` (in
practice `Overlays.CORE_HELP_SECTIONS` plus drop-in `HELP_ENTRIES`
collected into `DROPIN_HELP_SECTIONS`/dynamic sections) is the single
source of truth for key bindings. **Tooltip strings must not hardcode key
names.** Where a tooltip should mention a hotkey (e.g. "Toggle Auto VJ"),
the key hint must be resolved at display time from the help registry and
appended (e.g. "Toggle Auto VJ — hotkey: Shift+D"), so a future remap
never leaves stale keys in tooltips.

**Known coordinate caveat (pre-existing, affects clicks today too):**
control-room/mixer hotspot rects are in PIL pixel space, which since the
drawable-size fix equals *physical* pixels, while SDL mouse events arrive
in *logical* points. On unscaled displays these are identical; on scaled
displays the existing click hit-testing already has a latent mismatch.
Tooltip hit-testing must use whatever transform clicks use so the two
never disagree; actually fixing the scale mismatch is a separate,
pre-existing issue and explicitly out of scope here (noted so it isn't
rediscovered as a "tooltip bug").

---

## 2) Goals and non-goals

Goals:

- One shared hover state machine and one visual language across all three
  surfaces (respecting each surface's palette).
- Every interactive element on the operator surfaces gets a tooltip; the
  genuinely cryptic *informational* readouts (mixer meters, AUTO VJ stats)
  get explanatory tooltips too.
- Zero cost when idle: no allocations or hit-tests on frames where the
  mouse hasn't moved and no tooltip is armed.
- Config-gated (`[tooltips]`), on by default, with a tunable hover delay.

Non-goals:

- **No tooltips on the bare audience HUD.** The main window is the show;
  the cursor is hidden there by default and hover bubbles over live
  visuals would be a regression. Main-window tooltips activate only
  inside opened modals/browsers/help overlay, where the cursor is already
  visible and interaction is expected.
- No rich content (images, multi-column) — single short text block,
  wrapped, max ~3 lines.
- No touch/long-press support (no touch targets exist in this app).
- Not fixing the logical-vs-physical click coordinate caveat (§1).

---

## 3) Architecture

### 3.1 Core module: `unicornviz/tooltips.py`

New core module (main repo — drop-ins already import core modules like
`unicornviz.secondary_gl_window`, and core never imports drop-ins, per
the Drop-In Independence Rules). Three pieces, deliberately decoupled
from SDL, GL, and PIL so the state machine is testable with no fakes:

```python
@dataclass(slots=True)
class TooltipRegion:
    """One hoverable region: a rect in surface-pixel space plus its text."""
    rect: tuple[int, int, int, int]   # x, y, w, h
    text: str
    hotkey_ref: str = ''              # optional help-registry lookup key
```

```python
class TooltipHoverTracker:
    """Pure hover state machine: feed mouse position + regions, get the
    active tooltip (or None) back.

    - Arms after ``delay_s`` of the cursor resting inside one region
      (movement beyond ``jitter_px`` inside the region restarts the timer;
      leaving the region disarms immediately).
    - Once shown, stays shown while the cursor remains in the region;
      moving directly to an adjacent region re-shows after ``rearm_s``
      (shorter than the initial delay — standard tooltip "warm" behavior).
    - Any click event disarms until the cursor leaves and re-enters.
    - Time comes from an injected ``now()`` callable (``time.monotonic``
      by default) so tests never sleep.
    """
    def update(self, x: int | None, y: int | None,
               regions: Sequence[TooltipRegion]) -> TooltipRegion | None: ...
    def notify_click(self) -> None: ...
```

```python
def draw_tooltip_pil(draw, text, anchor_xy, bounds, *, colors, fonts) -> None:
    """Shared PIL bubble renderer for control-room/mixer render threads.
    Wraps text to max_width, clamps the bubble inside ``bounds``, offsets
    below-right of the anchor, flips above/left near edges."""
```

Defaults (config-overridable): `delay_s = 0.55`, `rearm_s = 0.15`,
`jitter_px = 6`, `max_width_px = 360`, bubble style follows each
surface's own theme (control-room `_Theme`, mixer palette constants,
overlays' existing bubble colors) — the core renderer takes colors as
parameters; it owns geometry/wrapping, not branding.

### 3.2 Overlays integration (main repo)

- Add one `TooltipHoverTracker` to `Overlays`; add a generalized
  `_draw_tooltip_bubble(text, anchor)` using the existing
  `_draw_rect`/`_draw_text` primitives (this is `_draw_help_icon_tooltip`
  made surface-generic — same visual style, kept).
- Each modal that already has a mouse-motion handler contributes a
  region provider (a `list[TooltipRegion]` rebuilt when its layout
  changes, mirroring the geometry its hit-test already computes):
  help-icon rail (migrated from the bespoke code), effects browser,
  presets browser, config editor, projectM manager, audio/MIDI
  selectors.
- `app.py`'s existing per-modal `SDL_MOUSEMOTION` routing feeds the
  tracker (one added call per branch); `Overlays.render()` draws the
  active bubble last, above everything.
- Hotkey hints resolve through a small `Overlays.lookup_help_key(ref)`
  that searches the merged help sections (`_iter_help_sections()`), so
  the single-source-of-truth rule holds.

### 3.3 control-room-01 integration (own repo)

- `_HitRegion` gains a `tooltip: str = ''` field. `_draw_button()` gains
  an optional `tooltip=` parameter; when omitted it falls back to a
  module-level `_TOOLTIP_BY_ACTION: dict[str, str]` table (most buttons)
  with payload-aware formatting for parameterized actions (`'effect'` →
  "Switch to {payload}", `'display'` → per-mode text, `'postfx'` → slot
  text). One table, one choke point — no per-call-site edits for the
  common case.
- Mouse: `on_sdl_event` stores the latest cursor position on
  `SDL_MOUSEMOTION` and clears it on `SDL_WINDOWEVENT_LEAVE`; clicks call
  `tracker.notify_click()`.
- The render thread (which already consumes main-thread-mutable state
  under the established one-frame-stale convention) runs the tracker
  against the previous frame's hotspot list and draws the bubble with
  `draw_tooltip_pil` as the final compositing step in `_render_ui()`.
  At ~30 fps on the background thread this is comfortably within budget
  and touches the main loop not at all.
- Informational (non-button) tooltips — INFO rows, AUTO VJ stats — are
  plain `TooltipRegion`s appended alongside the text draws.

### 3.4 dj-mixer-01 integration (own repo)

Revised 2026-07-13: the mixer landed its own hit-region foundation the
day before this plan (`50a3d4b` — `_Hit` regions driving mouse-draggable
faders/EQ knobs/crossfader/master). Tooltips build on it rather than
adding a parallel structure:

- **Draggable controls:** add a `tip: str = ''` slot to `_Hit` so each
  control carries its tooltip alongside its geometry and value binding —
  one list, one rebuild, no drift between drag targets and tooltip
  targets. (`_Hit` is deliberately a plain `__slots__` class, *not* a
  dataclass — `ui.py` is imported by path via `importlib` without
  `sys.modules` registration, which breaks dataclass string-annotation
  resolution under `from __future__ import annotations`. Keep it that
  way; see §8.)
- **Informational elements** (waveform, VU/MST meters, PLAY/CUE state,
  time, browser rows, REV1 badge): a second, plain
  `list[TooltipRegion]` built in `_render_ui()` where those rects are
  already computed, published under `_frame_lock` beside `_hits`. The
  render thread feeds the tracker the union of both lists (mapping
  `_Hit` → `TooltipRegion` is a comprehension over `x0..y1` + `tip`).
- **Coordinates:** `50a3d4b` already settled the space — draw
  coordinates are full-window pixels matching SDL mouse coordinates, no
  `ui_scale` conversion needed (the `ui_scale` raster divisor from
  `7116bd8` affects the PIL raster size only; the tooltip bubble is
  drawn on the raster, so `draw_tooltip_pil` receives raster-space
  anchor/bounds — divide by the same factor the widgets already use).
- Extend `on_sdl_event`'s existing `SDL_MOUSEMOTION` branch to always
  store the cursor position (currently only consumed mid-drag) + clear
  on `SDL_WINDOWEVENT_LEAVE`; drags call `tracker.notify_click()` so a
  tooltip never sits over a fader being dragged.
- Render thread: same tracker + `draw_tooltip_pil` pattern as control
  room. Mixer tooltips are mostly informational (clicks are deck toggle
  and drags), which is exactly where tooltips earn their keep — the
  owner's own test feedback ("mixer was hard to tell") shows the
  surface is under-explained.

### 3.5 What deliberately stays out of core

The region *content* (what text, where) lives with each surface; core owns
only the state machine and the PIL bubble geometry. This keeps the
Drop-In Independence Rules intact (core never knows drop-in UI exists)
and lets each surface restyle freely.

---

## 4) Tooltip inventory — control-room-01

Text conventions: imperative for actions, present tense for state
descriptions; `{…}` marks payload-formatted values; "(key: …)" suffixes
are resolved from the help registry at display time, never hardcoded.

### TRANSPORT

| Element | Tooltip |
|---|---|
| PAUSE / RESUME | Pause or resume effect playback; audio analysis keeps running |
| ADV ON/OFF | Auto-advance: automatically move to the next effect on the playlist timer |
| RECORD | Toggle recording the audience output to disk |
| STREAM | Toggle live streaming via the configured provider |
| RANDOM FX | Jump to a random effect immediately |

### PREVIEW

| Element | Tooltip |
|---|---|
| PREVIEW ON/OFF | Toggle the live audience-output preview (saves CPU/GPU when off) |

### EFFECTS (browser list)

| Element | Tooltip |
|---|---|
| Effect row | Switch to '{effect name}' |
| Scroll indicators | Scroll the effect list (Up/Down keys work too) |

### INFO (informational — the cryptic rows only)

| Element | Tooltip |
|---|---|
| React | Audio reactivity multiplier applied to all effects |
| Busy | Manual-action grace time remaining before Auto VJ resumes control |
| Advance | Whether the playlist auto-advance timer is running |
| Session | Time since this VJ session started |

### AUTO VJ (informational)

| Element | Tooltip |
|---|---|
| STATE | Whether Auto VJ is directing the show |
| MOOD / SCENE | Current Auto VJ mood profile and scene phase |
| B / M / T | Raw bass / mid / treble band energy |
| Bn/Mn/Tn | Normalized band energy (0.5 = rolling average) |
| INPUT RMS | Raw input loudness from the capture device |
| BPM PROF / REC PROF | Active audio profile / profile the detector recommends |
| TRANSIT. | Current effect transition and its progress |
| RENDER | Render scale (below 1.00 = resolution reduced for performance) |
| PRESET / VARIANT | Active projectM preset slot / effect variant slot |

### DISPLAY

| Element | Tooltip |
|---|---|
| SINGLE | Output on one display only |
| SPAN INCL / SPAN ALL | One canvas stretched across included displays / all displays |
| MIRROR INCL / MIRROR ALL | Same output duplicated on included displays / all displays |
| MONITORS | Open the monitor editor: exclude displays and switch modes |

### MOMENTS

| Element | Tooltip |
|---|---|
| RAINBOW NOVA | One-shot rainbow shockwave over the current effect |
| SCREEN BURST | One-shot screen spin/scale burst |
| DANCING UNICORN | Summon the dancing unicorn overlay |
| GRAND FINALE | Trigger the configured end-of-set finale sequence |

### TWEAKABLES

| Element | Tooltip |
|---|---|
| COLOR slider | Hue offset applied to the final output (drag to set; * = scroll-FX active) |
| INVERT toggle | Invert output colors |
| REACTIVITY slider | How strongly effects respond to audio |
| ROTATION slider | Output rotation in degrees (* = scroll-FX active) |
| SPEED slider | Global effect animation speed multiplier |
| ZOOM slider | Output zoom level |

### POST FX

| Element | Tooltip |
|---|---|
| Slot {n} | Apply post-FX preset slot {n} |
| CLR | Clear the active post-FX |

### WEBCAM

| Element | Tooltip |
|---|---|
| PREV / NEXT | Switch to the previous / next detected camera |
| REDISC | Re-scan for connected cameras |
| B- / B+ / C- / C+ | Decrease/increase webcam brightness / contrast |
| FLIP H / FLIP V | Mirror the webcam image horizontally / vertically |
| Device row | Enable or select this camera device |

### SPOTIFY

| Element | Tooltip |
|---|---|
| AUTH | Start Spotify login (opens the auth flow) |
| LOGOUT | Disconnect the Spotify account |

### DROP-INS

| Element | Tooltip |
|---|---|
| CANDY FRAME | Toggle the candy frame border overlay |
| CTA | Show the streaming call-to-action overlay |
| LAST SONG / ONE MORE | Announce the last song; press again for "one more" |
| (NOVA / BURST / UNICORN as in MOMENTS) | (same text, single table entry in code) |

### MODALS launcher

| Element | Tooltip |
|---|---|
| EFFECTS / PRESETS | Open the effects / presets browser on the audience output |
| AUDIO / MIDI | Open the audio-source / MIDI-device selector |
| PROJECTM | Open the projectM preset manager |
| HELP | Show the help overlay with all hotkeys |

### Fullscreen modals & monitor editor

Selector rows ("Switch to this audio source / MIDI port"), projectM
manager buttons (PREV/NEXT/RANDOM: "Change preset"; UNDO/REDO;
ENABLE/DISABLE/ISOLATE: "Include, exclude, or solo this category/preset
in rotation"), monitor-editor mode buttons (same text as DISPLAY),
E/S/R buttons ("Toggle exclusion for the selected display" / "Save
exclusions" / "Reset to config"). Close buttons: "Close (Esc)".

---

## 5) Tooltip inventory — dj-mixer-01

Mostly informational plus the draggable controls; this is the surface
where tooltips add the most immediate value. Draggable controls (per
`50a3d4b`) state their drag semantics: sliders jump to the cursor, EQ
knobs turn with a relative vertical drag. (Decks 3/4 and the pad
VU-screensaver/beat-flasher from the recent commits are engine/REV1-LED
features with no window UI yet — if on-screen decks C/D land later, the
deck-scoped texts below apply unchanged via their `{deck}` parameter.)

| Element | Tooltip |
|---|---|
| Header REV1 badge | DDJ-REV1 status — the controller is claimed only while this window is open |
| Deck panel (click zone) | Click to toggle play/cue for deck {A\|B} |
| PLAY / CUE state | Deck transport state (PLAY flashes on the beat via the REV1 LEDs) |
| Track title | Currently loaded track (Artist - Title from tags) |
| Waveform | Track overview — bright = played, line = playhead |
| Time display | Elapsed / total track time |
| PITCH | Tempo adjustment from the pitch fader ({±range}%) |
| HI / MID / LOW knobs | 3-band EQ for this deck — drag vertically; REV1 knobs drive the same value |
| CH bar | Channel gain (trim) for this deck — drag or click to set |
| FLT bar | Bipolar color filter — left of center: low-pass, right: high-pass; drag to set |
| Deck VU | Post-EQ channel level; red = clipping risk |
| MST meter | Master output level — drag to set |
| BROWSER | Track library ({n} tracks) — set [dj_mixer].music_dir if empty; navigate/load via the REV1 |
| Browser row | {track name} |
| Crossfader | Blend between deck A (left) and deck B (right) — drag or click to set |

---

## 6) Tooltip inventory — overlay system (main window, modal-scoped only)

| Surface | Element | Tooltip |
|---|---|---|
| Help icon rail | About / Contact / Share / Shop / Drop-ins / Settings / Account / Login–Logout | **Migrate existing texts** from the entry dicts unchanged; the rail becomes the first consumer of the shared tracker |
| Effects browser | Category row | Filter to the '{category}' category |
| | Effect row | Switch the audience output to '{name}' |
| | Thumbnail | Live preview of the highlighted effect |
| | Search field | Type to filter effects |
| Presets browser | Preset row | Load preset '{name}' |
| | Name field | Name for saving the current state as a preset |
| Config editor | Tab | Edit {tab name} settings |
| | Effect row / param row | Select this effect / drag or arrow-key to change '{param}' |
| | Footer actions | Per-action text (save / revert / capture etc., from the existing footer labels) |
| ProjectM manager | Category / preset rows + action buttons | As in the control-room modal table (§4) — same registry shared, not duplicated: control room renders these modals from the same overlay snapshot |
| Audio / MIDI selector | Source/port row | Switch capture to '{name}' / Connect to '{port}' |
| | Viability toggle | Show all devices, including ones that failed the probe |
| System monitor | Metric labels | **Skipped per owner decision (§9.3)** — modal judged self-explanatory |
| Context menu | — | **Deferred** — entries are already self-labeled and have hover glow; add only if labels prove insufficient |
| Ambient HUD | — | **Excluded by design** (§2 non-goals) |

---

## 7) Configuration

New commented-out sample appended to `config.toml` (permitted without
approval per the config policy — no existing values touched):

```toml
# [tooltips]
# enabled = true        # master switch for all hover tooltips
# delay_s = 0.55        # hover time before a tooltip appears
# rearm_s = 0.15        # delay when moving between adjacent controls
# max_width_px = 360    # wrap width for tooltip text
```

Each surface reads the shared `[tooltips]` table (control room and mixer
via their `cfg` dicts / `app.cfg`); no per-surface duplication of keys.

---

## 8) Testing, phasing, and repo mechanics

**Tests** (following the fake-based conventions already in
`tests/test_secondary_gl_window.py` and the drop-ins' suites):

- `tests/test_tooltip_tracker.py` — pure unit tests, injected clock, no
  fakes needed: arm delay, jitter re-arm, leave disarm, warm re-arm
  between regions, click suppression, empty-region behavior.
- `tests/test_tooltip_pil_renderer.py` — wrapping, edge clamping, and
  flip-above-cursor behavior asserted against a real PIL image (PIL is a
  hard dependency already).
- Control room (own repo): table-completeness test — every action name
  dispatched in `_dispatch_action` has an entry in `_TOOLTIP_BY_ACTION`
  or an explicit exemption list, so new buttons can't silently ship
  tooltip-less; hover-plumbing tests with the existing `_FakeVJ` pattern.
- Mixer (own repo): regions rebuilt per frame, motion capture, tracker
  wiring — extending `test_ui_keyboard_forwarding.py`'s fixtures.
- Overlays: region-provider geometry matches the existing hit-tests
  (assert the same rect math), help-icon-rail migration keeps its texts.

**Phases** (each independently shippable, drop-in repos committed first,
then submodule bumps, per the Drop-In Source Policy):

1. Core `unicornviz/tooltips.py` + tests + config sample.
2. Overlays: migrate the help-icon rail onto the shared tracker
   (behavior-preserving), then add effects browser + presets + config
   editor + selectors + projectM manager regions.
3. control-room-01: `_draw_button` tooltip fallback table + hotspot
   field + mouse capture + render-thread bubble; inventory texts from §4.
4. dj-mixer-01: region list + motion capture + bubble; texts from §5.
5. Docs: update both drop-ins' `operations.md`, this doc's status, and
   the configuration reference.

**Standards compliance checklist** (from CLAUDE.md, encoded here so the
implementing session doesn't rediscover it):

- Dataclasses with `__slots__`; type annotations on public surface;
  module/class/method docstrings; single quotes; f-strings; `logging`
  only. **Exception, learned from `dj-mixer-01@50a3d4b`:** modules
  imported by path without `sys.modules` registration (dj-mixer's
  sibling-module loading of `ui.py`) cannot use `@dataclass` under
  `from __future__ import annotations` (string-annotation resolution
  breaks) — use plain `__slots__` classes there. Core modules
  (`unicornviz/tooltips.py`) and control-room (registered in
  `sys.modules` by the shared drop-in loader) are unaffected.
- No `render()`-hot-path allocations in the main loop: the overlay
  tracker updates only on `SDL_MOUSEMOTION` events, and region lists are
  rebuilt only when a modal's layout changes, not per frame.
- Core→drop-in independence preserved (§3.5); drop-ins reach runtime
  state through `vj_api` only.
- Hotkey text single-source-of-truth preserved (§1).
- No new root-level markdown; this plan is linked from `docs/README.md`.

---

## 9) Decisions (owner, 2026-07-13)

1. **Help-icon rail delay: keep instant.** The rail stays 0-delay (it's
   a discovery surface); the 0.55 s default applies everywhere else. The
   tracker's per-surface `delay_s` parameter covers this.
2. **Informational tooltips: mixer gets the full pass (actions +
   informational) in phase 4; control room ships actions-first, with
   §4's INFO/AUTO VJ informational tables as a fast-follow** once the
   action tooltips have been used live for a bit.
3. **System monitor metric tooltips: skipped.** Removed from scope; the
   §6 row stays in the inventory only as a record of the decision.
4. **Context menu: no tooltips, confirmed.** Entries are self-labeled
   with hover glow; permanently out of scope unless labels prove
   insufficient later.
