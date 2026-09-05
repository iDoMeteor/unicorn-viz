# Control Room — Drop-In Integration & Uplift Plan

Owner: owner + Claude (overlays/core manager)
Status: **proposed (2026-09-05)** — audit complete, no code changed;
awaiting owner decisions in §7 before P0.
Last updated: 2026-09-05

Follows [control-room-panel-registry-plan-2026-09-04.md](control-room-panel-registry-plan-2026-09-04.md)
(P1–P3 delivered: registry, pages, LAYOUT page). That plan migrated the
panels the Control Room (CR) already had. This one covers **everything
else**: every technical (non-visual) drop-in that has an operator surface
but no CR presence, plus the three CR built-ins that are really drop-in
data wearing a CR costume.

---

## 0) What the audit found (2026-09-05)

Read-only pass over `unicornviz/operator_panels.py`, `VJApi`'s registry,
`control_room.py` 0.12.0, `unicornviz/dropins.py`, and all 30 non-`effects-*`
drop-ins.

**The registry is healthy and cheap to adopt.** Six panels and two pages
are registered today; the reference pattern (spotify-01) is ~80 lines
including tests: deferred import inside `try/except`, a
`_operator_panel_content()` that reads the same `snapshot()` every other
consumer uses, a `_operator_panel_action()` that returns flash text, a
`tooltips=` dict. CR reads the registry **every frame**
(`_registered_panels`), so registration order vs. CR startup does not
matter.

**Registered today:** `auto_vj`, `spotify` (40, medium), `webcam`,
`candy_frame` (60, small), `cta` (70, small), `unicorn_tears` (80, small);
pages `deck_sim` (CR-owned tier-2 draw, gated on MIDI + a deck-sim
layout) and `layout` (CR-owned).

**Unregistered but panel-worthy — 17 drop-ins**, every one of which
already exposes the state and verbs a panel needs (§2). Ten are
"toggle + status" subsystems with a `snapshot()` or two properties —
the cheapest possible migrations. Three are page-scale (media-01,
dj-mixer-01, multi-head-01).

**Three CR built-ins are drop-in data in disguise:** POST FX
(`_draw_postfx_panel` → postfx-01 via `vj_api.postfx_slots()`), OUTPUT
(`_draw_output_panel` + the monitor-editor modal → multi-head-01), and
the STREAM button in TRANSPORT (streaming-01 via
`vj_api.toggle_streaming()`). Same shape as the P2 retirements.

**Gaps in the migrated set worth fixing in passing:**

- **Nobody unregisters.** None of the six migrated drop-ins call
  `vj_api.unregister_operator_panel()` from `shutdown()`. CR's per-panel
  `try/except` turns a dead `content()` into an error box rather than a
  freeze, but a drop-in that shuts down mid-session leaves a red box
  behind. The contract in `operator_panels.py` already says
  "Unregistering is for drop-ins that shut down mid-session" — it just
  isn't followed.
- **Two registration idioms.** Drop-ins constructed with `app` register
  in `__init__`; the nine that receive the API later via `set_vj_api()`
  (beat-flash, color-grade, lyrics, postfx, video-postfx, streaming,
  webcam, audio-out, banner, video-out) must register *there*. Both are
  fine; the plan just names the rule so migrations don't guess.
- **multi-head-01 is unreachable from `vj_api`.** `MULTIHEAD_RUNTIME_CAPABILITY`
  in `unicornviz/dropins.py` declares no `subsystem_name`, so
  `get_subsystem('multihead')` is `None`; CR drives display mode through
  core's `set_display_mode()` and the monitor editor writes a runtime key
  (`multihead.monitor_editor.exclude_display_indices`) that **nothing
  ever reads** — the 2026-09-05 multi-head audit's #1 bug. A Displays page
  owned by multi-head-01 is the natural home for the fix, but it is a
  behavior change, not just UI (§7).
- **Main page will overflow.** The registered band on MAIN is capped at
  35 % of the right column and packs ≤3 panels per row. Six panels fit;
  six plus seventeen do not. This plan therefore ships **shared standard
  pages** (§3.7) before the first migration, and LAYOUT already lets the
  operator move anything anywhere.

## 1) Non-goals

- No changes to the registry descriptor types beyond §3.7's page
  constants. `PanelContent` rows/buttons/meters express every surface in
  §2; tier-2 `draw` is used only where a page is a live mirror (deck-sim
  today; the hosted-mixer preview in P4).
- No new `config.toml` keys. Panel placement is the runtime store's job
  (LAYOUT page), per the 2026-09-04 decision.
- No hotkey changes. Panels are mouse surfaces on a second window;
  `HELP_ENTRIES` stay the single source of truth for keys.
- No `overlays.py` work (still the separate track).
- Visual effect packs (`effects-*`) and content-source drop-ins are out
  of scope (§5).

## 2) Inventory — every non-visual drop-in

Columns: what the panel reads (**must be a cheap, read-only snapshot —
`content()` runs on CR's render thread**), what buttons it exposes (each
maps to an existing public method), proposed page / size / priority, and
phase. Priorities leave gaps so LAYOUT overrides and future panels slot
in. Existing registrations are listed first for the ordering picture.

| Drop-in | Reads (content) | Buttons (on_action → method) | Page | Size | Pri | Phase |
|---|---|---|---|---|---|---|
| auto-vj-01 *(registered)* | HUD/grid state | ON/OFF, PROFILE, PING-PONG | main | medium | 10 | done |
| spotify-01 *(registered)* | `snapshot()` | AUTH, LOGOUT | main | medium | 40 | done |
| webcam-01 *(registered)* | camera state | PREV/NEXT/REDISC, modes | main | medium | 50 | done |
| candy-frame-01 *(registered)* | enabled, pattern | TOGGLE, CYCLE | main | small | 60 | done |
| cta-01 *(registered)* | — | HYPE, LAST SONG, ONE MORE | main | small | 70 | done |
| unicorn-tears-01 *(registered)* | — | DANCING, NOVA, BURST | main | small | 80 | done |
| **grand-finale-01** | `is_active()` | TRIGGER → `trigger()`, ABORT → `abort/restore` | main | small | 85 | P1 |
| **beat-flash-01** | `snapshot()`: enabled, mode, level, max_hz, max_brightness (meter: level) | TOGGLE, MODE → `cycle_mode()`, −/+ brightness | fx | small | 110 | P1 |
| **color-grade-01** | `is_active()`, `active_name`, `intensity` (meter) | TOGGLE, PREV/NEXT → `prev_grade()/next_grade()`, −/+ → `set_intensity()` | fx | small | 120 | P1 |
| **video-postfx-01** | `is_active()`, `active_count`, `debug_summary` | SHUFFLE → `trigger_shuffle()`, CLEAR | fx | small | 130 | P1 |
| **postfx-01** | `SLOT_MAP`, `active_slot`, `is_hue_active`, `is_rotation_active` | one button per enabled slot → `trigger_slot()`, CLR → `clear_active_slot()` | fx | large | 100 | P2 (retires CR POST FX) |
| **streaming-01** | `enabled`, `is_streaming`, `provider`, `destination_label`, `last_error` | START/STOP → `start()/stop()`, RUMBLE/YOUTUBE/CUSTOM → `set_provider()` | output | medium | 210 | P2 (retires TRANSPORT STREAM) |
| **video-out-01** | `enabled`, `is_publishing`, `status_line`, `last_error` | TOGGLE | output | small | 220 | P1 |
| **audio-out-01** | `snapshot()`: enabled, sfx_count, active_voices, status, params (meters: LPF/HPF) | TOGGLE → `toggle_enabled()`, REVERB → `toggle_reverb()`, SFX → `trigger_sfx()` | output | medium | 230 | P1 |
| **osc-bridge-01** | `snapshot()`: enabled, host, port, feedback, queued, last_address | TOGGLE → `toggle_enabled()` | output | small | 240 | P1 |
| **multi-head-01** | `display_mode`, `requested_mode`, `display_index`, `display_layouts`, excludes | mode buttons, per-display INCLUDE/EXCLUDE, SAVE | **displays** (own page, tier-2 draw) | full | — | P3 (retires OUTPUT + monitor editor) |
| **banner-01** | enabled, line count, `max_line_chars`, `font_px`, beat color | TOGGLE, EDIT (opens config modal), RESET | overlays | small | 310 | P1 |
| **chat-01** | enabled, position, (message count if cheap) | TOGGLE, POS → cycle, T/L/R/B → set position | overlays | small | 320 | P1 |
| **lyrics-01** | `snapshot()`: enabled, track, has_lyrics, position_s | TOGGLE | overlays | small | 330 | P1 |
| **media-01** | `snapshot()` (Spotify-shaped), shuffle/repeat/crossfade/auto-level flags | PLAY/PAUSE, PREV, NEXT, SHUFFLE, REPEAT, XFADE, OPEN DECK → `toggle_window()` | main | medium | 42 | P3 |
| **dj-mixer-01** | `session_snapshot()`, `now_playing_snapshot()`, keep-playing, `is_open` | OPEN/CLOSE → `toggle_window()`, KEEP PLAYING → `toggle_keep_playing()` | main | medium | 44 | P3 |
| **midi-controllers-01** | manager: `is_open`, `is_armed`, `selected_action`, active port, preset name | LEARN (arm), SELECTOR → `vj_api.open_midi_selector()` | output | small | 250 | P2 |
| training-kit-01 | — | — | — | — | — | excluded (§5) |

Notes on specific rows:

- **Now-playing dedupe.** media-01 and dj-mixer-01 already feed the
  now-playing hub; INFO shows the active source. Their panels must **not**
  repeat title/artist — they show transport/deck state and buttons only.
- **banner-01 EDIT** flips the drop-in's own `_show_config`; no `vj_api`
  method needed (`on_action` runs on the main thread, same as the hotkey).
- **postfx-01** stays the owner of `vj_api.postfx_slots()`/`set_postfx_slot()`
  (other callers may exist); the panel simply stops CR from being one of
  them.
- **midi-controllers-01** vs. the `deck_sim` page: CR registers that page
  today with `owner='control-room-01'` and its own `draw`. Moving
  ownership to midi-controllers-01 (as the registry plan §5 originally
  sketched) is cosmetic — the view body would still be CR code — so it is
  **not** in scope unless the owner wants the tab to disappear when the
  drop-in is absent (it already does, via `available`).
- **multi-head-01** needs core wiring first (§4 P0): a `subsystem_name`
  on `MULTIHEAD_RUNTIME_CAPABILITY` so `vj_api` can reach the instance, and
  a `set_vj_api()`/registration hook (it has neither `set_vj_api` nor
  `handle_key` today).

## 3) Uplift rules (apply to every migration)

1. **Register where the API first exists.** `__init__(app)` drop-ins
   register in `__init__`; `set_vj_api()` drop-ins register in
   `set_vj_api()`. Always `getattr(vj, 'register_operator_panel', None)`
   + `try/except` + deferred import of `unicornviz.operator_panels`
   (Drop-In Independence rules 2/3), exactly as spotify-01 does.
2. **Unregister in `shutdown()`.** `vj_api.unregister_operator_panel(name)`,
   guarded the same way. Retro-fit the six existing registrations in the
   same P0 commit that documents the rule.
3. **`content()` is a snapshot, never a computation.** Read attributes or
   an existing `snapshot()`; no locks that the main thread holds for
   long, no GL, no I/O, no `vj_api` calls that mutate. Where a controller's
   `snapshot()` reaches into an engine (audio-out `active_voices`, osc
   queue depth), confirm it is a plain read before using it, or expose a
   cached counter updated in `update()` instead.
4. **`on_action()` calls the same public method the hotkey/MIDI action
   calls.** No new state paths. Return the same flash string the hotkey
   returns so CR and the audience window agree.
5. **Tooltips for every button** via `tooltips=` (or `PanelButton.tooltip`).
   CR's `test_every_dispatched_action_has_tooltip_coverage` is extended
   per migration to namespaced actions (registry plan §8 already says so;
   it is a test to add, not a habit to assume).
6. **Retire the duplicate.** When a panel lands that a CR built-in already
   showed, the *same* PR/commit pair removes the built-in (P2 pattern:
   "control-room-01 0.x.y removes the hardcoded X" + a CR test asserting
   the field list / dispatch branch is gone). Applies to POST FX, OUTPUT +
   monitor editor, and TRANSPORT's STREAM button. Core `vj_api` methods
   stay (other callers), CR just stops calling them.
7. **Shared standard pages, registered by CR.** Add to
   `unicornviz/operator_panels.py`:

   ```python
   STANDARD_PAGES: tuple[tuple[str, str], ...] = (
       ('fx', 'FX'), ('output', 'Output'), ('overlays', 'Overlays'),
   )
   ```

   CR registers them in `_register_builtin_pages()` (owner
   `'control-room-01'`, no `draw`, so they render registered panels), the
   way it registers `layout`. Drop-ins then just set `page='fx'`. Tabs
   stay alphabetical with MAIN pinned. A page with no panels registered
   shows "No panels registered on this page" — acceptable, and LAYOUT can
   move panels there. (Alternative considered: each drop-in re-registers
   an identical `OperatorPage` idempotently — works, but three copies of
   the same title string in three repos is the kind of drift the registry
   was built to end.)
8. **Versioning & tests per CLAUDE.md.** Each drop-in: MINOR bump,
   README changelog line, hermetic test in the main repo
   (`tests/test_<dropin>_operator_panel.py`, the
   `test_auto_vj_operator_panel.py` shape: importlib-load the module,
   `object.__new__` or a fake-API constructor, assert `content()` rows/
   buttons against a stubbed state and `on_action()` routing). CR: PATCH
   for a pure retirement, MINOR when it gains a page. One drop-in per
   commit; drop-in repo first, then the main-repo submodule bump.
9. **No `get_subsystem()` duck-typing from CR.** The registry exists so CR
   never imports or introspects a drop-in instance; a migration that
   still needs `get_subsystem('x')` in `control_room.py` is incomplete.

## 4) Phasing

**P0 — core + CR groundwork (one core commit, one CR commit).**
`STANDARD_PAGES` + CR registration (§3.7); document the unregister rule
in `operator_panels.py` and retro-fit `unregister_operator_panel()` into
the six migrated drop-ins' `shutdown()` (six tiny drop-in commits, or
batched with their first P1/P2 touch); `subsystem_name='multihead'` on
`MULTIHEAD_RUNTIME_CAPABILITY` plus a `set_vj_api()` on
`MultiHeadController` (core–drop-in boundary change → verify the three
guarded load sites per Drop-In Independence rule 5). Tests: core page
constants; CR registers them; multihead reachable via
`vj_api.get_subsystem('multihead')`.

**P1 — the ten cheap declarative panels (no CR changes).** In this
order, smallest surface first so the pattern is proven before the
busier ones: lyrics, osc-bridge, video-out, grand-finale, chat, banner,
beat-flash, color-grade, video-postfx, audio-out. Each is one drop-in
commit + one submodule bump. Expect ~40–90 lines of drop-in code and a
~60-line test each.

**P2 — uplift CR built-ins into their owners (paired commits).**
postfx-01 panel + CR retires `_draw_postfx_panel`/`postfx` dispatch/
`test_postfx_distinguishes_clear_from_slots` moves to the drop-in;
streaming-01 panel + CR retires TRANSPORT's STREAM button (RECORD stays —
it is core); midi-controllers-01 panel (no CR retirement — the combined
MIDI/audio selector mirror is a core modal, not a panel).

**P3 — page-scale surfaces.** media-01 and dj-mixer-01 declarative
panels on MAIN (transport + window controls, no now-playing repeat).
multi-head-01 registers `OperatorPage('displays', 'Displays',
owner='multi-head-01')` with a tier-2 `draw` that replaces both
`_draw_output_panel` and `_draw_monitor_editor_modal`, and **reads its
own exclude key on construction** so SAVE actually does something on the
next launch — closing the audit bug. Gate: owner decision §7 #2.

**P4 — optional.** LAYOUT lists loaded-but-panel-less subsystems from
`vj_api.list_subsystems()` (after P1–P3 that set is just
`training-kit`/content packs, so this may not be worth it — cheaper than
wiring `discover_runtime_capabilities()`); a MIXER page drawing
`hosted_frame()` as a live preview (needs frame hand-off across windows
— measure first).

Suggested landing order across the shared tree: P0 → P1 → P2 → P3, one
drop-in at a time, because every P2/P3 item pairs a drop-in commit with a
CR commit and interleaving two of those invites the submodule-pointer
collisions seen on 2026-09-05.

## 5) Excluded, and why

- **training-kit-01** — not a runtime subsystem: `KeystrokeLogger` is
  loaded by `app.py` directly, has no `vj_api`, no subsystem name, no
  operator verbs. Nothing to register.
- **projectm-01** — its preset manager is already a core modal mirrored
  fullscreen in CR with a PROJECTM launcher button and full undo/redo/
  enable/disable dispatch; a panel would duplicate it.
- **images-01, sims-01, textures-01, video-clips-01, videos-01,
  grand-finale-01's pack siblings, `effects-*`** — visual effect /
  content sources; they are reached through the effect browser, which is
  a CR built-in already. (grand-finale-01 itself is a *moment* trigger
  like unicorn-tears, so it is in §2.)
- **control-room-01's own built-ins** (preview, effect browser, INFO,
  MODALS launcher, TRANSPORT minus STREAM, TWEAKABLES, RECORD) — core
  state, correctly CR-owned.

## 6) Tests

- Core: `STANDARD_PAGES` shape; unchanged registry behavior.
- CR: standard pages registered and tab-ordered; each retirement asserts
  the old draw method / dispatch branch / tooltip key is gone (P2 style);
  tooltip coverage extended to `panel:<name>:<action>` for every button
  a registered `content()` emits in a stubbed state.
- Per drop-in: `content()` against stubbed state (rows, meters within
  0..1, status text); every `on_action` routes to the public method and
  returns its flash text; registration is skipped cleanly on a fake API
  without `register_operator_panel`; `shutdown()` unregisters.
- multi-head-01 (P3): excludes written by the Displays page are honored
  on the next construction — the first regression test the drop-in has.

## 7) Owner decisions needed before P0

| # | Question | Recommendation |
|---|---|---|
| 1 | Shared pages registered by CR (§3.7) vs. drop-ins re-registering identical pages? | CR registers `fx` / `output` / `overlays`. |
| 2 | multi-head-01: fold the "excludes are never read" fix into the Displays page (behavior change), or fix it standalone first? | **Standalone first** (it's a bug; users hit it today), then P3 moves the UI. |
| 3 | Retire TRANSPORT's STREAM button when the streaming panel lands, or keep both? | Retire — same dedupe rule as INFO. RECORD stays. |
| 4 | Default page for beat-flash: `fx` (with the other post passes) or `main` (it's a "moment")? | `fx`; LAYOUT moves it in one click if MAIN is preferred live. |
| 5 | media-01 / dj-mixer-01 on MAIN at priority 42/44 (next to Spotify) or on `output`? | MAIN — they are the show's transport. |
| 6 | Move `deck_sim` page ownership to midi-controllers-01? | No (cosmetic; `available` already hides it). |

## 8) Related

- [control-room-panel-registry-plan-2026-09-04.md](control-room-panel-registry-plan-2026-09-04.md) — the registry this builds on
- `unicornviz/operator_panels.py` — descriptor contract
- `drop-ins/spotify-01/spotify_controller.py` — reference declarative migration
- `tests/test_auto_vj_operator_panel.py` — reference migration test
- `drop-ins/control-room-01/docs/configuration.md` — runtime-store layout keys
- 2026-09-05 multi-head-01 audit (session report; excludes bug, span drift)
