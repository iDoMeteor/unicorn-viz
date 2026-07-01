# ProjectM-Only Mode + Effects Browser — Design Examination

Owner: Effects
Status: ProjectM-only mode IMPLEMENTED (Method A); effects browser IMPLEMENTED
(keyboard + mouse, live-thumbnail preview, pin/unpin, enable/disable) — see §4
Last updated: 2026-07-01

> **Implemented 2026-06-30 (Method A).** Generic effect-lock at `_switch_effect`
> (`App._effect_lock`, exposed via `vj_api.lock_effect/unlock_effect/effect_lock`).
> Toggle: **Ctrl+L** (`App.toggle_projectm_only`) — on = switch to ProjectM +
> lock; off = unlock + advance to next effect immediately (owner decision #3).
> Auto-advance is suppressed while locked. A blocked switch redirects into a
> locked-effect variation (ProjectM `next_preset`), so Auto VJ keeps running its
> normal cadence but expresses it through pM presets (owner decision #2) with no
> Auto VJ code changes. Startup lock via `[effects.ProjectMEffect] only_mode`.
> Tests in `tests/test_hotkeys_projectm_only.py`.

Two related items:

1. **ProjectM-only mode** — a toggle that keeps the system in ProjectM the whole
   time, skipping system effects and other drop-in effects. ProjectM's own
   controls (preset next/prev, the `Ctrl+M` preset manager, search) keep working
   unchanged; the only new control is the mode toggle itself.
2. **Effects browser/loader** — a ProjectM-manager-style browser for *our*
   system effects + drop-in effects. Deferred ("todo soon") — see §4.

---

## 1. How effect switching works today (the relevant facts)

- ProjectM is a **playlist effect** (`ProjectMEffect`, display name
  `ProjectM Presets`), not a subsystem. It already owns a preset-manager modal.
- **Every** effect switch funnels through one chokepoint:
  `App._switch_effect(cls)` ([app.py](../../unicornviz/app.py)). Callers:
  - auto-advance (main loop, `playlist.advance()` → `_switch_effect`);
  - hotkeys / playlist nav → `App.goto_effect(cls)` → `_switch_effect`;
  - Auto VJ → `vj_api.goto_effect(name|cls)` → `goto_effect` → `_switch_effect`.
- `_switch_effect` **already blocks switches** while the ProjectM preset manager
  modal is open (`_projectm_manager_modal_active`). That is the exact precedent
  for a lock.
- Auto-advance is separately gated in the loop:
  `if not manager_modal_active and not self._paused and self._next_effect is None
  and self._auto_advance:`.

Implication: a single guard at `_switch_effect` (plus suppressing the
auto-advance timer) covers **all** switch sources at once.

---

## 2. Methods examined

### Method A — Generic effect-lock at the switch chokepoint  ✅ recommended

Add a generic `_effect_lock: str | None` to `App` (the locked display name).

- `_switch_effect(cls)`: if a lock is set and `cls.NAME != lock`, log + return
  (mirrors the existing manager-modal guard).
- Auto-advance loop gains `and self._effect_lock is None` so the timer doesn't
  even fire while locked.
- Entering pM-only: `goto_effect('ProjectM Presets')` once, then set
  `_effect_lock = 'ProjectM Presets'`. Exiting: clear the lock (stay on pM;
  rotation resumes on the next advance/hotkey).
- Expose via VJApi: `lock_effect(name)` / `unlock_effect()` / `effect_lock`
  property, so drop-ins and the control room use the public surface.

**Pros:** ~20 lines, central, reuses a proven pattern, covers every path
(hotkeys, number-jumps, auto-advance, Auto VJ) in one place. ProjectM's own
controls are untouched (they never call `_switch_effect`). **Generic** — not
hardcoded to ProjectM, so the future effects browser reuses the same lock to
"pin" any effect.
**Cons:** Auto VJ keeps evaluating and will attempt (blocked) swaps, producing
harmless "switch blocked" log lines. Optional refinement: have Auto VJ honor
`effect_lock` and stand down (it already reads `vj_api`), or demote the block
log to debug.

### Method B — Restrict the playlist to a single entry

On enter, swap the active playlist for a one-item `[ProjectM]` list (and restore
on exit).

**Pros:** auto-advance naturally never leaves ProjectM; no per-switch guard.
**Cons:** does **not** stop hotkey next/prev/random, number-jump-by-index, or
Auto VJ's `goto_effect(specificClass)` — those bypass the playlist. So it needs
the Method-A guard anyway. Adds save/restore playlist state. More moving parts
for strictly less coverage. Rejected as a standalone.

### Method C — ProjectM as an exclusive subsystem takeover

Promote pM-only to a modal/subsystem mode (like control-room) that suspends the
playlist/effect system entirely and routes rendering straight to ProjectM.

**Pros:** strongest "it is the only thing running"; could skip instantiating
other effects entirely (memory/CPU).
**Cons:** large change — pM is a playlist effect, not a subsystem; needs a
parallel render/ownership path and careful HUD/overlay/transition handling.
Overkill for the requirement. Revisit only if we want pM to run with the whole
effect pipeline torn down.

### Method D — Auto-VJ "lock to current effect" only

Use/extend an Auto VJ lock so automation stops swapping.

**Pros:** trivial if Auto VJ already has the concept.
**Cons:** covers Auto VJ only — manual hotkeys + auto-advance still switch.
Incomplete alone; would be a complement to A, not a substitute.

---

## 3. Recommendation

**Method A (generic effect-lock)**, because the architecture already centralizes
switching and already has the manager-modal precedent. Make the lock generic
(`lock_effect(name)`) rather than pM-specific so it doubles as the "pin this
effect" primitive the effects browser will want — keeping core drop-in-agnostic.

Open decisions for the owner:

- **Toggle surface.** The toggle must work from *any* active effect (you can't
  rely on ProjectM's own `handle_key` to enter the mode from elsewhere). Options:
  (a) one global hotkey in core `hotkeys.py`; (b) a control-room button via
  `vj_api.lock_effect`; (c) a `[effects.ProjectMEffect] only_mode = true` for
  startup-locked installs. Likely (a) + (c), with (b) when the control room grows
  the button. Pick the hotkey (a free, WM-safe chord).
- **Auto VJ behavior while locked.** Honor the lock and stand down (quietest), or
  leave it attempting blocked swaps (simplest). Recommend: Auto VJ checks
  `vj_api.effect_lock` and pauses swap decisions.
- **Exit behavior.** Stay on the current ProjectM preset and resume rotation, or
  also restore the pre-lock effect. Recommend: just unlock; stay on pM.

Estimated effort for A: core guard + auto-advance gate + VJApi surface + toggle
hotkey + config + a couple of unit tests (lock blocks non-pM, allows pM,
auto-advance suppressed). ~half a focused session.

---

## 4. Effects browser / loader  — `[IMPLEMENTED 2026-07-01]`

> **Shipped 2026-07-01.** Full-screen modal opened with **naked `B`** (core
> naked-key policy; banner moved to `Shift+B` toggle / `Ctrl+B` editor). Keyboard
> **and** mouse: category tabs (Left/Right focus panes, Up/Down browse), `/`
> name/tag/category search, mouse hover/click/scroll. **Live-thumbnail preview** —
> the selected effect is instantiated at 480×270 and rendered to its own offscreen
> FBO (the active on-screen effect is never touched); `Enter`/click commits.
> **`P`** pins/unpins (reuses `lock_effect`; shows `[pin]`); **`Space`** toggles
> enable/disable, persisted in the global `RuntimeStateStore` (`effects.disabled`)
> and skipped by playlist rotation, `vj_api.goto_random_effect`, and auto-vj
> ping-pong. Built on the shared GL-free `CatalogBrowser` model
> (`unicornviz/catalog_browser.py`) fed by `registry.browser_entries()`; the
> projectM preset manager was **migrated onto the same model**. HUD-style frame
> decorators added. Tests: `test_catalog_browser`, `test_registry_browser_entries`,
> `test_hotkeys_effects_browser`, `test_playlist_disabled`. The design notes below
> are retained as the record of how it was built.

### Original design notes  — `[prep complete]`

A ProjectM-manager-style, full-screen modal browser for **all effects** (core
analyzers + every category pack + standalone drop-ins): search/filter by
name/tag/category, jump-to, and pin (reusing the Method-A `lock_effect`
primitive). Mirrors `drop-ins/projectm-01`'s preset-manager UX but over
`registry.get_effects()`.

**Input: keyboard *and* mouse (owner requirement).** Full keyboard nav
(arrows/Tab/`/`-search/Enter/Esc) *and* full mouse support (hover-highlight,
click-to-select, click category tabs, scroll-wheel, click search box). And it
should be **premium/polished** — smooth, live-previewing, thumbnail-rich.

### Prerequisites — DONE

- **Unified discovery.** `registry.get_effects()` already merges core +
  `discover_dropin_effect_classes()`; one flat list of 43 effect classes.
- **Generic effect-lock.** `App.lock_effect/unlock_effect/effect_lock` (Method A,
  §1–3) is the "pin" action — already landed and test-covered.
- **Normalized tags (2026-07-01).** Every effect now carries a canonical
  category-first tag plus clean descriptors (no `audio`/`drop-in`/`futuristic`
  noise). This is what makes the browser's category tabs + tag search coherent —
  it was the gating prep for this feature.

### Template — the projectM preset manager (all in core)

The pM manager is the exact pattern to mirror; it already lives in core, not the
drop-in:

- **`overlays.py`** — `_render_projectm_manager()` (~161 lines), entry store +
  filtering (`set_projectm_manager_entries`, `_projectm_filtered_entries` — which
  already filters on `display_name` / `pack_name` / `category_key` / **`tags`**),
  category tabs, `_projectm_search_query`, selection sync.
- **`hotkeys.py`** — the `projectm_manager` key context (up/down/left/right =
  nav + category, `/` = search, Return = commit, Tab = focus, Esc = close) and
  the `_sync_projectm_manager()` catalog-build + preview/commit/revert flow.
- **`app.py`** — `_projectm_manager_modal_active` (blocks `_switch_effect`, gates
  auto-advance), `set_projectm_manager_modal_active`, `open_projectm_manager`.

Mouse comes from the **control-room** pattern (`_HitRegion` hotspots +
click/hover hit-testing); the new modal fuses both input styles.

### Catalog mapping (effects → browser entries)

`registry.get_effects()` → entries of `{display_name: NAME, pack_name: <pack or
'core'>, category_key: <category>, tags: TAGS, cls: <class>}`. Category is
derivable from the effect's source path (pack dir) or its first (category) tag;
recommend a small `registry` helper so control-room and the modal share one
catalog source.

### Where it lives — CORE (no new drop-in)

Unlike recent work, this is a core feature: it browses the core registry, uses
the core `lock_effect` primitive, and renders through core `overlays.py`. No new
private repo / submodule.

### Existing related surface — reconcile, don't duplicate

`drop-ins/control-room-01` already has a **mouse-driven, embedded** effect list
(`_draw_effect_browser`: name + up-to-3 tag chips + click-to-activate, no
search). The new modal is the **searchable, keyboard-and-mouse** surface. Both
should read the same catalog helper and use `lock_effect` so they never diverge.

### Design decisions (owner — settled 2026-07-01)

1. **Modal code: generalize now (DECIDED).** Extract one shared
   `_render_catalog_browser` (+ generic entry store / filter / category / search /
   selection) in `overlays.py` that BOTH the projectM preset manager and the new
   effects browser drive. DRY. Because this edits a shipped feature, gate it on
   the pre-work below (characterization tests for the current pM manager) so the
   refactor can't silently regress it.
2. **Preview: debounced live preview (DECIDED).** Hover/arrow to an entry →
   switch to it live after ~250 ms idle; Enter/click commits; Esc reverts to the
   pre-open effect. Feels live without GL thrash.
3. **Input: keyboard + mouse (DECIDED).** Keyboard context (arrows/Tab/`/`/Enter/
   Esc) fused with mouse hotspots (hover-highlight, click-select, click tabs,
   scroll) via the control-room `_HitRegion` pattern.
4. **Thumbnails (the "pimp" factor) — v2.** Per-effect live-FBO preview tiles
   (or a cached-screenshot cache dir). Best-looking, highest cost; land after the
   text+live-preview browser works.
5. **v1 scope.** Shared generic browser + effects catalog + search/filter by
   name/tag/category + debounced live preview + jump + pin (`lock_effect`) +
   keyboard&mouse. **v2:** thumbnail tiles, enable/disable-from-rotation (touches
   playlist + `[dropins] exclude` persistence).
6. **Trigger surface.** Global open hotkey (added to `HELP_TEXT`), e.g. `Ctrl+B`
   "Browse effects", plus a control-room button.

### Pre-work (do first, because we're generalizing a shipped modal)

1. **Characterization tests for the current projectM manager** — lock in its
   filtering (category + name/tag/pack search), selection sync, and open/commit/
   revert behavior *before* extracting the shared browser, so the refactor is
   provably behavior-preserving.
2. **Shared catalog helper in `registry`** — `browser_entries()` returning
   `{name, cls, pack, category, tags}`; adopt it in control-room's existing list
   too so the two surfaces share one source of truth.

Then: extract the generic browser, re-point the pM manager at it (tests stay
green), add the effects catalog + debounced preview + pin + open hotkey, and
finally the control-room button.
