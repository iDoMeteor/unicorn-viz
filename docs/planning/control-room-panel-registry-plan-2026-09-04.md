# Control Room Panel Registry, Pages & Runtime Layout — Plan

Owner: owner + Claude (overlays/core manager)
Status: **P1 shipped (2026-09-04; core beta.112, control-room-01
0.11.0)** — registry + host + page model + runtime-store defaults are
live; deck-sim is the first registered page. Bug-fix pass (§2) landed
first (core beta.111, control-room-01 0.10.1). **P2 complete (2026-09-04).** Auto
VJ migrated (2026-09-04; auto-vj-01 1.0.0-rc.126, control-room-01
0.11.1 removes the old hardcoded panel) — mood/scene/BPM/action-in plus
a BPM-lock and beat-pulse meter, real reco/score rows gated on an
actual scoring pass, ON/OFF/PROFILE/PING-PONG buttons. INFO redesigned
(2026-09-04; control-room-01 0.11.2): dropped the transport/display/
advance/record/stream/react/invert rows (each duplicated a live readout
one panel over on the same screen) and replaced the Spotify-only status
row with a source-agnostic NOW PLAYING line via
`vj_api.active_now_playing()`. Spotify migrated (2026-09-04; spotify-01
1.0.0-rc.4, control-room-01 0.11.3 removes the hardcoded panel, its
row-4 3-column special case, and the two remaining
`get_subsystem('spotify')` `_dispatch_action` branches — auth/logout now
call the registering instance's own methods via `on_action`). Webcam
migrated (2026-09-04; webcam-01 1.5.1, control-room-01 0.11.4 removes
the hardcoded panel, the `_refresh_webcam_state()` poll loop and its
cache, and the per-device select/enable button — PREV/NEXT/REDISC cover
the same ground generically; also deletes `webcam_toggle_device`,
found to be dead code with no button that ever fired it). DROP-INS
migrated (2026-09-04; candy-frame-01 1.1.0-rc.2, cta-01 0.9.0,
unicorn-tears-01 1.0.0-rc.2, control-room-01 0.11.5 removes the
hardcoded panel entirely) — three separate small registered panels
(the packer already handles multiple small panels in one band; no
merge-into-one-panel mechanism was needed after all) replace the six
hardcoded buttons, and the migration surfaced two real bugs along the
way: CTA/LAST SONG called `vj_api.trigger_streaming_cta()`/
`trigger_streaming_song_cta()`, methods that never existed anywhere in
the codebase (every press silently failed); RAINBOW NOVA was always
drawn "active" from a method-existence check on an unrelated method.
Also deleted `_draw_triggers_panel`, dead code with no caller. **P2
complete.** **P3 shipped (2026-09-04; control-room-01 0.12.0)** — an
always-available LAYOUT page tab: hide/show, cycle page, cycle size, and
reorder any registered panel, persisted in the runtime store, plus a
RESET. **This plan's initial scope (P1-P3) is now fully delivered.**
Supersedes the "Control Room Follow-Ups" section of
[drop-in-planning.md](drop-in-planning.md) (archived 2026-07-18), whose
"category containers that accept rows from drop-ins" and "dedicated
pages" items are realized here.
Last updated: 2026-09-04

---

## 0) Why

A three-seat read-only audit (2026-09-04) of `unicornviz/overlays.py`,
`unicornviz/vj_api.py`, `unicornviz/dropins.py`, and
`drop-ins/control-room-01/control_room.py` found:

- **Nothing in Control Room is registered.** Every panel is CR's own
  hardcode: Spotify's snapshot fields, 17 Auto VJ field names, six
  literal DROP-INS buttons, webcam's nine actions, projectM availability.
  Absent drop-ins don't collapse — they leave dead panels ("Subsystem
  unavailable"). The one place CR bypasses `vj_api` entirely is
  `get_subsystem('spotify').snapshot()` — duck-typing another drop-in's
  object.
- **Surface selection is a boolean priority chain**
  (`_monitor_editor_open` → core modal → `_deck_sim_mode` → grid), not a
  page model. Nothing about the active surface persists.
- **User configurability is two scalars** (`control_room.preview_fps_cap`,
  `control_room.preview_scale` in runtime state). No panel order, no
  hide, no page assignment, no UI scale.
- **Three things already exist that make the fix cheap:** the
  `register_deck_sim_layout()` descriptor precedent (shipped 2026-09-04);
  `RuntimeStateStore` (`runtime/global_state.json`, dotted keys, atomic
  writes on every `set`); and CR's per-frame hotspot rebuild + publish
  under `_frame_lock`, which already makes "whatever surface drew last
  owns the clicks" work — paging is only render-branch selection.

The audit's verified bugs are in §2; the rest of this document is the
architecture.

## 1) Decisions (owner, 2026-09-04)

| # | Question | Decision |
|---|---|---|
| 1 | Bug fixes before the refactor? | **Yes, as standalone commits, then commit.** |
| 2 | Panel content model | **Declarative.** Drop-ins register *data* (rows, buttons, meters); CR renders it in its own theme on its own thread. A custom-draw callback is an opt-in second tier, not the default. |
| 3 | Pages | **Yes** — header tabs; drop-ins may claim a whole page; deck-sim becomes the first non-main page. **Tabs in alphabetical order** (main pinned first). |
| 4 | Layout editing | **Easy one first**: persisted hide/order/page-assignment in the runtime store; in-CR layout editor later. |
| 5 | `overlays.py` cleanup (TabStrip/ScrollList primitives, modal-chrome dedup, HUD/DPI scale) | **Separate, isolated track.** Not in this plan. |
| 6 | Dormant `DROPIN_CAPABILITIES` scanner | **Runtime registry only** (Claude's call). `vj_api.list_subsystems()` already answers "what's loaded"; wiring the scanner is a non-blocking follow-up. |
| — | Configuration | **Moving away from `config.toml`** except hardware-type settings. CR **registers its defaults into the runtime store** on first run and reads them back thereafter — the store is the source of truth for layout, pages, and panel prefs. |
| — | INFO / AUTO VJ panels | Need "dressing up": reveal missing data, remove redundancy, more drip. Handled as the first two declarative migrations (§7 P2). |

## 2) Verified bugs — fixed first (standalone commits)

All personally re-verified by reading the code after the audit.

| # | Where | What | Sev |
|---|---|---|---|
| 1 | `control_room.py` ~L1921 | CANDY FRAME button is a no-op — drawn + tooltipped, no `_dispatch_action` branch; `vj_api.toggle_candy_frame()` exists, never called. | High |
| 2 | `vj_api.py` ~L1082 | `auto_vj_snapshot()` reads `self._app._hud_state`, which lives on `Overlays` (~L730), not `App` → mood/scene/profile always `'-'`. CR additionally reads 15 keys the snapshot never returns. | High |
| 3 | `overlays.py` ~L3010 | HUD + recording indicator never render when `[overlays] flash_messages=false` — gated on `_name_text`, only set inside `flash_name()`, which early-returns when flashes are off. | High |
| 4 | `overlays.py` ~L5752 | Presets / effects browser / config editor / tour / context menu vanish on **both** surfaces when CR is open: `render()` suppresses them for CR but `modal_snapshot()` has no branch for them → CR gets `{}`; keys still captured. | High |
| 5 | `overlays.py` ~L6350 | `destroy()` never releases `_font_tex/_prog/_vbo/_vao/_panel_*` or the CTA; the block it does release is CTA attrs that don't exist on `Overlays`. Help icon textures leak per resize across 3840 px. | Med |
| 6 | `control_room.py` ~L346 | Tab pane cycling traps when auto-vj-01 is absent (`'autovj'` in `_pane_order`, never in `_pane_rects`). | Med |

Deferred to the architecture (fixed structurally by §4–§6): one failing
panel freezes the whole CR window (no per-panel isolation); global wheel
scroll; the 15-key Auto VJ contract drift; dead `_draw_triggers_panel` /
`_split_three_columns`; the three known `F841`s.

Deferred to the separate overlays track (§1 #5): CTA `trigger_custom`
replacing the slot deck and its fixed 1600 px quad; non-ASCII aliasing
via `& 0x7F` (tour eyebrow `·` renders as `7`); 8-px-cell centering
drift; unsafe `float()` on HUD state in eight places; `hash()`-salted
help colors; help sections dropped-but-focusable; ~1050 px HUD at 4K; **help overlay
"Extra effects (no direct key): …" line is a single unwrapped join of
every unmapped effect and overruns the panel edge** (owner screenshot
2026-09-04; `overlays.py` `_render_help`, the `self._unmapped_effects`
join) — needs wrap/ellipsis against the card width.

Flagged, not touched: `config.toml:203` has `output_device = "DDJ-REV1…"`
inside `[control_room]` — never read by CR; looks like a mixer key in
the wrong section. **`CLAUDE.md` says `HELP_TEXT` in `overlays.py` is
the hotkey source of truth — no such symbol exists** (it is
`CORE_HELP_SECTIONS` + `register_help_entries` / `HELP_ENTRIES`
discovery). Owner to approve the CLAUDE.md correction.

## 3) Non-goals

- No in-CR drag-and-drop layout editor in the first cut (§1 #4).
- No changes to `overlays.py` beyond the §2 bug fixes (§1 #5).
- No new `config.toml` keys. Existing `[control_room]` hardware-ish keys
  (`enabled`, `display_index`, `fullscreen`, `width`/`height`,
  `render_interval`) stay; `theme`, `preview_*` migrate to the store with
  config as a one-time seed if present.
- Core modals (audio/MIDI selectors, projectM, help, …) stay
  overlays-on-top mirrored from `overlay_modal_snapshot()`; they are not
  pages.
- Programming mode for deck-sim stays deferred
  ([deck-sim-plan.md §7](../../drop-ins/control-room-01/docs/deck-sim-plan.md)).

## 4) The registry (core, `vj_api`)

Mirrors `register_deck_sim_layout()`: a frozen descriptor in a small
core module, a registry on `VJApi`, and CR resolving generically. Lives
in core per Public Runtime Surface rule 1/4; drop-ins reach it via
`getattr(vj, 'register_operator_panel', None)` guards per Drop-In
Independence rules 2/3 (the exact pattern `register_now_playing` uses).

```python
# unicornviz/operator_panels.py  (new; frozen, slotted, no GL, no PIL)

@dataclass(frozen=True, slots=True)
class PanelRow:            # one line of label/value text
    label: str
    value: str = ''
    emphasis: str = ''     # '' | 'accent' | 'warn' | 'danger' | 'success'

@dataclass(frozen=True, slots=True)
class PanelButton:
    action: str            # namespaced by CR as f'{panel.name}:{action}'
    label: str
    tooltip: str = ''
    active: bool = False
    accent: str = ''       # theme token, not RGB
    payload: object = None

@dataclass(frozen=True, slots=True)
class PanelMeter:
    label: str
    value: float           # 0..1
    text: str = ''

@dataclass(frozen=True, slots=True)
class PanelContent:
    rows: tuple[PanelRow, ...] = ()
    buttons: tuple[PanelButton, ...] = ()
    meters: tuple[PanelMeter, ...] = ()
    columns: int = 1       # rows split across N columns
    status: str = ''       # one-line header-right text (e.g. 'LIVE', 'OFF')

@dataclass(frozen=True, slots=True)
class OperatorPanel:
    name: str              # stable id, e.g. 'spotify', 'auto_vj'
    title: str
    page: str = 'main'     # 'main' or a drop-in page id
    priority: int = 0      # lower = earlier in default order
    size: str = 'medium'   # 'small' | 'medium' | 'large' | 'full'  (row-height class)
    content: Callable[[], PanelContent]          # called fresh each CR frame
    on_action: Callable[[str, object], str | None] = None  # returns flash text
    draw: Callable[[PanelCanvas], None] | None = None      # tier-2 opt-in

@dataclass(frozen=True, slots=True)
class OperatorPage:
    name: str              # id; tab label = title; sorted alphabetically by title
    title: str
    owner: str             # drop-in name, for the "what's loaded" listing
```

`VJApi`:

```python
def register_operator_panel(self, panel: OperatorPanel) -> None
def unregister_operator_panel(self, name: str) -> None
def operator_panels(self, page: str | None = None) -> list[OperatorPanel]
def register_operator_page(self, page: OperatorPage) -> None
def operator_pages(self) -> list[OperatorPage]   # alphabetical by title
```

Contract:

- `content()` is called **on CR's render thread**, once per CR frame, and
  must return a plain snapshot of the drop-in's own state — no GL, no
  `vj_api` mutation, no blocking I/O. CR wraps every call in `try/except`
  and renders an error box for that panel only (fixes the whole-window
  freeze). This is the same rule the deck-sim `_on_deck_sim_midi_event`
  listener already documents.
- `on_action()` is called on CR's **main** thread from `_dispatch_action`
  with the un-namespaced action + payload; the returned string is
  flashed. Drop-ins never see hotspots or rects.
- `draw(canvas)` (tier 2) gets a `PanelCanvas(draw, rect, theme, fonts,
  add_hotspot)` — CR's own helpers, not raw PIL ownership. Deck-sim uses
  this; nothing else should need it in P1–P3.
- Registering the same `name` replaces (same as deck-sim layouts).
  Unregistering is for drop-ins that shut down mid-session.

## 5) Pages

Replace the boolean chain (`_render_ui_content` ~L1432–1470) with one
`self._page: str`:

- `'main'` — the primary grid (built-ins + `page='main'` panels).
- Every `OperatorPage` registered by a drop-in (deck-sim registers
  `OperatorPage('deck_sim', 'Deck Sim', 'midi-controllers-01')` and moves
  its view body under a tier-2 `draw`).
- `'monitor_editor'` stays a CR-internal page until multi-head-01 owns it.
- Core modals remain an overlay drawn *on top of* the current page, keyed
  off `overlay_modal_snapshot()['type']` exactly as today.

Header: a tab strip — `MAIN` pinned first, then registered pages
**alphabetically by title**. Tabs render only when ≥1 page is
registered (today's single-button toggle disappears; same gating
guarantee: a page whose owner disconnects still shows its tab while
active, so the operator is never stuck — see deck-sim-plan §6).
Hotspot action `page:<name>`; `Ctrl+Tab`/`Ctrl+Shift+Tab` cycle (added
to CR's `HELP_ENTRIES`, single source of truth). Key routing table keyed
by page. `control_room.page` persisted so CR reopens where it was.

## 6) Runtime store as source of truth

Namespace `control_room.*` in `runtime/global_state.json` via
`vj_api.get_runtime_state()/set_runtime_state()` (every `set` flushes
atomically — fine at click cadence; never write per frame).

Defaults are **registered on first run**: CR builds
`_DEFAULTS: dict[str, object]` and for each key does
`if get_runtime_state(key, _MISSING) is _MISSING: set_runtime_state(key, default)`
so the store always holds a complete, editable record. A
`control_room.schema` int guards future migrations.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `control_room.schema` | int | 1 | store layout version |
| `control_room.page` | str | `'main'` | last active page |
| `control_room.ui_scale` | float | 1.0 | fonts/padding/buttons scale (clamped 0.75–2.0); seeds 4K sanity |
| `control_room.theme` | str | `'dark'` | migrated from config (one-time seed) |
| `control_room.preview_fps_cap` / `.preview_scale` | existing | existing | unchanged |
| `control_room.panels.<name>.hidden` | bool | false | hide a panel |
| `control_room.panels.<name>.order` | int | registration priority | manual order override |
| `control_room.panels.<name>.page` | str | registration page | move a panel to another page |
| `control_room.panels.<name>.size` | str | registration size | row-height override |

Editing (first cut): a **LAYOUT** page (CR-internal, like the monitor
editor) listing every registered panel with HIDE / ▲ / ▼ / PAGE / SIZE
buttons and a RESET (re-seeds defaults). No drag-and-drop.

## 7) Phasing

- **P1 — core registry + CR host (no visible change).**
  `unicornviz/operator_panels.py`, `VJApi` methods, tests mirroring
  `tests/test_deck_sim.py`. CR: `_page` replaces the boolean chain,
  header tab strip (renders only when pages exist), generic panel packer
  (sort by effective order, pack by `size` class into the existing
  right-column row budget), per-panel `try/except`, namespaced
  `panel:<name>:<action>` dispatch, runtime-store defaults registration
  + `ui_scale`. Built-ins (preview, browser, transport, tweakables,
  display, post-FX) untouched. Deck-sim moves to a registered page with
  a tier-2 `draw` — proving the page path with zero new UI.
- **P2 — migrate the drop-in panels + dress up INFO / AUTO VJ. Shipped
  (2026-09-04).** In order: **Auto VJ** (auto-vj-01 registers a
  declarative panel from its own state — reveals the data the former
  15-key drift hid, drops redundant rows), **INFO** (CR built-in,
  redesigned: now-playing from `active_now_playing()` instead of a
  Spotify-only row, session clock, telemetry), **Spotify** (spotify-01
  registers; retires `get_subsystem('spotify')` duck-typing), **Webcam**
  (webcam-01), **DROP-INS buttons** (candy-frame-01, cta-01,
  unicorn-tears-01 each register their own small panel — the packer's
  existing multi-panel band layout placed them side by side with zero
  new mechanism, so the `PanelContent` same-name-merge rule floated here
  originally was never built; simpler and sufficient). CR's hardcoded
  field lists and `_TOOLTIP_BY_ACTION` entries for these moved out with
  them. Each migration landed as its own commit with its own tests, and
  surfaced two real bugs along the way (CTA/LAST SONG calling vj_api
  methods that never existed; RAINBOW NOVA always drawn "active").
- **P3 — LAYOUT page** (hide/order/page/size/reset). **Shipped
  (2026-09-04, control-room-01 0.12.0).** `Ctrl+Tab` paging + persisted
  `control_room.page` had already landed in P1. Docs:
  `drop-ins/control-room-01/docs/configuration.md` rewritten around the
  store; core `docs/configuration.md` gains the `[control_room]`
  hardware keys it was missing.
- **Follow-ups (unscheduled):** wire `discover_runtime_capabilities()`
  so the LAYOUT page can also list loaded-but-panel-less drop-ins;
  multi-head-01 owning the monitor editor as a registered page; the
  `overlays.py` track (§1 #5).

## 8) Tests

- Core: descriptor shapes; register/replace/unregister; page listing
  alphabetical with `main` excluded; `operator_panels(page)` filter;
  provider called fresh each read; raising `content()` isolated.
- CR (hermetic, `object.__new__` + `_FakeVJ`, per
  `tests/test_deck_sim_view.py`): packer order with priority vs. store
  override; hidden panels skipped; page tab set + alphabetical order;
  `page:<name>` and `panel:<name>:<action>` dispatch; defaults
  registration writes only missing keys; error-box path when a
  `content()` raises; tooltip coverage test extended to namespaced
  actions.
- Each P2 migration: the drop-in's panel `content()` against a stubbed
  controller state; the old hardcoded panel removed from CR (assert the
  field list is gone).

## 9) Risks / open questions

| Risk | Note |
|---|---|
| `content()` on CR's render thread reads drop-in state the main thread mutates | Same exposure as today's `auto_vj_snapshot()`/`spotify.snapshot()` reads; the contract says "plain snapshot of your own state", and per-panel isolation turns a torn read into one bad frame, not a frozen window. |
| Packing many panels on `main` | `size` classes + the store's `page` override let the operator push panels to a second page; P3's LAYOUT page is the pressure valve. `drop-in-planning.md`'s breakpoint/compact-fallback ideas remain valid input for the packer. |
| Runtime-store schema drift | `control_room.schema` + RESET; never auto-migrate silently — surface and let the owner reset. |
| Deck-sim moving under a page changes its shipped toggle | Behavior-preserving: same gating, same view body, tab instead of a button. Update deck-sim-plan §5/§6 when P1 lands. |
| Alphabetical tabs vs. operator priority | Owner decision (§1 #3); `main` pinned first covers the live-use case. Revisit only if a page count >4 makes it awkward. |
