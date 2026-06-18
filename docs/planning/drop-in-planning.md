# Drop-In Planning

Owner: Studio Documentation
Status: archive
Last updated: 2026-06-18


## Control Room Follow-Ups

### Control Room Manager Track (2026-06-05)

- `[active]` Layout and sizing stabilization pass for `control-room-01`.
  Notes:
  - establish a single layout contract with panel min sizes, priority tiers, and deterministic compact fallbacks
  - add explicit breakpoints (wide, medium, compact, tiny-safe)
  - keep critical controls always visible in every breakpoint (transport, display mode switching, effect selection, emergency actions)
  - route all geometry through one cached layout computation path during resize and redraw
  - define explicit item categorization so the surface is organized by control intent instead of current implementation ownership
  - support mixed row structures: some rows remain single-purpose, others intentionally span multiple columns when the data is related and should be scanned together

- `[active]` Control-room information architecture and categorization.
  Notes:
  - classify controls into stable top-level groups:
    - transport / playback
    - scene / effect navigation
    - output / display / recording / streaming
    - reactive tweakables / post FX
    - subsystem editors and utility modals
    - operator status / alerts / diagnostics
  - avoid letting the current implementation order dictate the operator-facing order; layout should reflect live-use priority first
  - plan for a fully loaded package where multiple optional drop-ins are present at the same time without making the primary page unreadable
  - prefer category-level containers that can accept optional rows from drop-ins instead of dedicating one fixed panel per drop-in forever

- `[active]` Special-case controller surfaces for automation and music metadata.
  Notes:
  - Auto VJ should be treated as a first-class special case rather than just another generic subsystem row
  - Spotify should be treated as a first-class special case because transport, metadata, auth, and playlist context are richer than normal toggle-style drop-ins
  - Spotify is now a single consolidated drop-in surface (not split spotify + spotify-pro panels)
  - these subsystems may need dedicated panels or pages with denser state, richer action affordances, and stronger operator feedback than generic drop-ins
  - generic drop-in registration should still feed a common surface, but the architecture must allow hand-authored layouts for important subsystems

- `[active]` Operator ergonomics and scaling hardening.
  Notes:
  - derive fonts/padding/button sizes from one clamped UI scale value
  - preserve preview aspect ratio with letterboxing rules
  - enforce min readable text and min click target sizes
  - add a hard "screen too small" guard that switches to an operator-safe fallback instead of trying to cram the full layout into an unusable surface
  - operator-safe fallback should show only critical actions, key state, and a short reason that the full layout is suppressed at the current window size
  - operator resolution priority (2026-06-07): treat 1920x1080 as the primary target profile; keep 1440x900 and 4K as first-class secondary profiles

- `[active]` Layout behavior rules for dense rows.
  Notes:
  - allow some rows to span multiple columns when controls belong together operationally
  - examples: transport + auto-advance, display mode + display target, recording + streaming state, Auto VJ mode + lock/director state
  - multi-column rows must collapse deterministically at compact breakpoints instead of wrapping arbitrarily
  - row behavior should be part of the layout contract, not ad hoc per panel

- `[active]` Intrinsic row packing and dynamic in-row sizing for the control column.
  Notes:
  - stop assuming one logical control group equals one full-width row in the right column
  - introduce row items with intrinsic width hints, min/max width guidance, priority, and optional full-row preference
  - second-column rows should be able to subdivide into dynamic internal columns so narrow controls do not create comically wide buttons while denser groups get squeezed
  - some groups should explicitly request full-row treatment when operationally justified, for example transport and other high-priority control clusters
  - taller/high-information surfaces should be allowed to share a row footprint or consume extra vertical space intentionally rather than inheriting equal-height treatment from unrelated panels
  - optional drop-ins must participate through the same contract so additional controls pack predictably instead of just appending more tall rows

- `[active]` Utility modal launcher strip for control room.
  Notes:
  - add a compact, always-discoverable button group that launches routed sub-modals from one place
  - initial targets: audio selector, MIDI selector, ProjectM manager when available, HUD/help/controller help, system monitor, webcam editor where available
  - launcher strip should degrade gracefully when a subsystem is unavailable instead of leaving broken gaps
  - launcher placement should support both wide and compact breakpoints without stealing too much vertical space from primary controls
  - operator decision (2026-06-07): default to an always-visible strip and adjust placement later if needed

- `[active]` Global configuration editor initiative.
  Notes:
  - design a shared configuration editing model that can power both a control-room editor and a main-app editor
  - editor should be schema-driven where possible so config sections can render consistently instead of hand-authoring each form twice
  - control-room version should prioritize live-safe runtime/operator settings and guarded apply flows
  - main-app version can expose the fuller configuration surface, including richer documentation and validation messaging
  - treat this as a cross-surface system, not a one-off modal, so validation, defaults, comments, and writeback rules stay consistent
  - operator decision (2026-06-07): first implementation scope is runtime-safe controls

- `[active]` Declarable control-room layout and modal capability for drop-ins.
  Notes:
  - operator direction (2026-06-07): drop-ins should be able to declare layout intent rather than relying only on central hardcoded placement
  - start with declarable layout metadata for row/cluster/modal participation and keep central fallback behavior when metadata is absent
  - evaluate a modal-first extension point where drop-ins can declare a control-room modal surface instead of requiring persistent row residency
  - preserve consistency by routing declared modals through the same themed fullscreen/routed modal framework used by core control-room utility modals

- `[active]` Windows compatibility truth tracking for control room.
  Notes:
  - owner-machine Windows runtime currently passes for operator-window open/close and control flow
  - hotkey model updated: `Shift+M` toggles control room, `M` controls system monitor modal
  - control-room-focused key events now forward to global hotkeys when not consumed locally
  - control-room display mode buttons now render from runtime-supported mode list so new multi-head modes appear without manual UI updates
  - Linux operator-window remains N/A for production pending separate-process architecture

---

## Control Room Design Specification (pre-implementation)

### Panel category model

Four top-level categories. Every panel belongs to exactly one.

```
TRANSPORT      — playback, scene navigation, display output, recording, streaming
EFFECTS        — effect browser, post FX, tweakables, moments/triggers
UTILITIES      — webcam, MIDI, audio source, subsystem editors
DIAGNOSTICS    — system status, operator log viewer, session info, modal route status
```

All items in the current "transport" panel that are not about playback
control or output routing belong in a different category. Specific moves:

| Item currently in transport | Should move to |
|---|---|
| RANDOM FX button | EFFECTS (top of effect browser) |
| ADV ON/OFF toggle | TRANSPORT (stays — it's playback policy) |
| RECORD button | TRANSPORT (stays — output) |
| STREAM button | TRANSPORT (stays — output) |
| Display mode buttons | TRANSPORT (stays — output routing) |

---

### Panel layout plan (wide breakpoint, 1440×900)

Left column (preview side):

```
┌─────────────────────┐
│  PROGRAM PREVIEW    │  (aspect-locked letterbox, PREVIEW ON/OFF toggle)
│                     │
│                     │
├─────────────────────┤
│  EFFECT BROWSER     │  (scrollable list + random + load; multi-column tag row)
│                     │
└─────────────────────┘
```

Right column (controls side) — ordered by live-use priority, top to bottom:

```
┌──────────────┬──────────────┐
│  TRANSPORT   (multi-column row)
│  PLAY/PAUSE  │  AUTO ADV    │
│  NEXT SCENE  │  PREV SCENE  │
│  FULL SCR    │  DISPLAY OSD │
│  RECORD      │  STREAM      │
│──────────────┴──────────────┤
│  SPOTIFY (special, prominent) │
│  health/status + now playing  │
│  progress + transport actions │
├─────────────────────────────┤
│  OUTPUT (multi-column)      │
│  display mode buttons       │  (dynamic from supported_display_modes())
│  D-INDEX  │  DISPLAY STATUS │
├─────────────────────────────┤
│  TWEAKABLES                 │  (single panel, column layout)
│  SPEED   ZOOM   REACT   INVERT │
│   █       █       █      █/■   │
│  1.00    1.00    1.00    OFF   │
│   [−][+] per column controls   │
├─────────────────────────────┤
│  POST FX                    │  (dynamic slot buttons from postfx_slots())
├─────────────────────────────┤
│  AUTO VJ        (special)   │
│  mode  │ lock  │ director   │  (multi-column)
│  status pill + on/off       │
├─────────────────────────────┤
│  UTILITIES (collapsed rows) │
│  Webcam row                 │
│  MIDI / Audio row           │
├─────────────────────────────┤
│  STATUS / INFO              │  (was "SYSTEM STATUS")
│  Effect  │  FPS  │  BPM     │  (multi-column)
│  Audio   │  Bass │  Treble  │
│  Record  │  Stream│ Display │
│  Session timer + pill       │
└─────────────────────────────┘
```

---

### Tweakables panel — single-row column design

All core tweakables are always shown in one panel row as vertical columns,
so the operator can scan relative values left-to-right without moving between rows.

Panel structure:
```
SPEED   ZOOM   REACTIVITY   INVERT
  █       █        █        █/■
 1.00    1.00     1.00      OFF
[−][+]  [−][+]   [−][+]    [TOGGLE]
```

- Each vertical bar fill = (value − min) / (max − min), clamped to [0, 1].
- Value range constants:
  - speed: 0.05 – 10.0, neutral 1.0
  - zoom: 0.1 – 3.0 (from config zoom_min/zoom_max), neutral 1.0
  - reactivity: 0.1 – 5.0, neutral 1.0
- invert is represented as a binary bar/toggle column in the same panel so
  hardware mapping can treat it as part of the tweakables bank.
- [RAND] and [RST] remain per-parameter actions for speed/zoom/reactivity.
- Unavailable = greyed out column, value shows "N/A".
- Source for MIDI reference: Akai APC Mini MK2 CC map uses CC 48–56 as
  general parameter knobs; CC 48=speed, 49=intensity, 50=zoom,
  51=reactivity, 52=glow, 53=crt, 54=volume, 55=pan, 56=master vol.
  Only speed/zoom/reactivity are core system tweakables; the rest are
  per-effect parameters not exposed in this panel.

---

### INFO / STATUS panel — items from HUD worth surfacing

The HUD state dict has richer content than the current status panel.
Fields worth adding to the operator status panel:

| Field | Source | Notes |
|---|---|---|
| effect | hud_state['effect'] | current effect name |
| previous_effect | hud_state['previous_effect'] | useful during transitions |
| transition / transition_t | hud_state['transition_t'] | % progress bar |
| fps / frame_ms | hud_state['fps'] + ['frame_ms'] | multi-column |
| resolution + render_scale | hud_state['resolution'] + ['render_scale'] | |
| auto_advance + advance_time | hud_state['auto_advance'] + ['advance_time'] | multi-column |
| audio_source + audio_profile | hud_state['audio_source'] + ['audio_profile'] | multi-column |
| bass / mid / treble | hud_state['bass'] / ['mid'] / ['treble'] | mini bar row |
| display_mode + display_index | hud_state['display_mode'] + ['display_index'] | multi-column |
| spotify status | hud_state['spotify_status'] etc | mirrored here for diagnostics even when Spotify panel is prominent |
| session clock (elapsed + remaining) | VJState.session_elapsed_s | |
| vj_status pill | hud_state['vj_status'] | Auto VJ status line |

Panel name: **SYSTEM STATUS** → rename to **INFO** for implementation.

---

### Auto VJ special-case panel

Not a generic subsystem row. Needs its own dedicated mini-panel:

```
AUTO VJ   [ON]   mode: RAVE   lock: 4   director: 3
          [A] [B] [P] [R] [C] [M]   manual hold: 12s
```

Actions: toggle on/off, mode/profile cycle, lock/director adjust, view
manual-hold countdown. All through `vj_api.toggle_auto_vj()` and
subsystem getattr access for state.

---

### Spotify special-case panel (prominent)

When consolidated Spotify is loaded and healthy, show a prominent panel near
the top of the right column (just below Transport) with:
- health/auth state
- now playing (track + artist)
- progress and timing
- transport controls relevant to live operation

When Spotify is unavailable/unhealthy, collapse this panel to a compact
status strip instead of removing it entirely, so operator context remains clear.

---

### Screen too-small guard

Minimum usable dimensions: **960 × 540**. Below that, render an
operator-safe fallback that shows only:
- Current effect name
- PAUSE / NEXT / RECORD / STREAM as 4 large buttons
- "Window too small — resize to 960×540 or larger"
- Modal routing badge if a modal is currently active

Implementation: compute in `_render_ui()` before any panel layout.
If `self._width < 960 or self._height < 540`, call `_draw_too_small_fallback(draw)`
instead of the normal layout path and return early.

---

### Breakpoints

| Name | Min width | Behaviour |
|---|---|---|
| wide | ≥ 1280 | full two-column layout with all panels |
| medium | ≥ 960 | right column collapses UTILITIES to icons-only row; tweakables shrink |
| compact | ≥ 720 | single column; INFO panel reduced to 4 fields; effect browser shorter |
| too-small | < 720 or < 540h | operator-safe fallback only |

---

### Multi-column rows

Rows that must stay multi-column at all breakpoints above too-small:

- transport: PAUSE + AUTO-ADV (2-col)
- Spotify: health + now-playing + progress (3 logical columns)
- output: RECORD + STREAM (2-col)
- display mode buttons: up to 5 across, wrap to 2 rows at compact
- tweakables: one panel row with vertical value bars as columns
- status: effect + fps, audio + bass/treble, record + stream (all 2-col pairs)
- Auto VJ: mode + lock + director (3-col)

---

- `[todo]` Add hardware-inspired page layout pass to `control-room-01`.
  Notes:
  - reorganise preview, transport, FX, and effect-selection zones to feel more like standard VJ hardware banks/pages
  - bias toward large hit targets, persistent status strips, and bank/group concepts that later map cleanly to controllers
  - include category-aware page planning so future loaded packages can split into pages/banks cleanly without rewriting the whole control-room surface

- `[todo]` Add a dedicated `Decks / Cues / Timing` page to `control-room-01`.
  Notes:
  - use this as the first bridge toward Serato / Mixxx / xwax style workflows
  - include room for deck timing, cue state, phrasing, and transition timing indicators

- `[todo]` Add full control-room mouse support across all pages and routed modals.
  Notes:
  - every primary action currently available by keyboard should have an equivalent clickable control
  - routed overlay modals (audio selector, midi selector, webcam editor, projectm manager where feasible) must support row/item click selection and commit actions
  - preserve keyboard-first speed while ensuring pointer interactions never conflict with modal routing or focus rules
  - include explicit hit-region tests for dense layouts and compact breakpoints to avoid dead zones

## Spotify Drop-In

- `[todo]` `spotify-01` — optional Spotify transport / metadata bridge.
  Notes:
  - primary target: ingest currently playing track, artist, title, play/pause state, and coarse timing
  - likely Linux path: MPRIS over D-Bus first; Web API only as an optional secondary path
  - useful follow-ons: bias Auto VJ profile/effect choices from track tempo or section labels when available
  - must remain optional and never block app startup when Spotify is absent

## Mixxx / xwax / Giada Drop-Ins

- `[todo]` `mixxx-01` — deck/transport bridge for Mixxx.
  Notes:
  - read deck state, BPM, transport, crossfader, and cue information when available
  - surface transport/focus cues into Control Room and Auto VJ safely

- `[todo]` `xwax-01` — lightweight vinyl-control / deck-state bridge for xwax.
  Notes:
  - likely smaller scope than Mixxx; prioritise track/deck status and tempo cues
  - keep Linux-first assumptions explicit

- `[todo]` `giada-01` — live-loop / clip-state bridge for Giada.
  Notes:
  - focus on scene/clip launch status, tempo, and section energy hints
  - useful for synchronising visual scene changes to live loop performance structure
