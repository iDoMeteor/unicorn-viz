# Auto VJ Tag Coverage + Hotkey System Overhaul — Plan

Owner: owner + Claude Opus (master coordinator)
Status: Planned (not started)
Last updated: 2026-07-13

Two independent problems that surfaced together during the effect/hotkey
overflow discussion:

1. **Auto VJ ignores many effects** — a *tag* problem, not a hotkey problem.
2. **Hotkey overflow / ergonomics** — dynamic re-pack + pinning + a full hotkey
   editor.

---

## 1) Auto VJ effect selection — root cause

The Auto VJ never uses number-hotkeys. It picks via
`vj_api.goto_random_effect(tags=…)`, which filters `enabled_effect_classes()` by
**TAG intersection** with the director's per-scene mood tags. Those tag sets come
from the active `AudioProfile` but **no profile overrides them**, so every profile
uses the code defaults in `auto_vj.py`:

| Scene | Default requested tags |
|-------|------------------------|
| Cruise | `[]` → `None` (any enabled effect) |
| Drop | `psychedelic, intense, drop` |
| Impact | = drop |
| Climax | = drop |
| Breakdown | `ambient, art, classic` |

**Two mismatches make the VJ over-select psychedelics:**

- **Vocabulary mismatch.** Effect `TAGS` are *category/style* words (`classic`,
  `tech`, `cosmic`, `shader`, `retro`, `vector`, …). The VJ asks in *energy/mood*
  words (`intense`, `drop`, `ambient`). The namespaces barely overlap.
- **Dead tags.** `intense` and `drop` appear on **zero** effects, so the
  drop/impact/climax set collapses to just `psychedelic` — **5 effects**. Every
  drop/impact/climax is locked to those 5.
- **Tagless effects.** Several rotation effects ship with no `TAGS` at all
  (e.g. `laser_sweep`, `neon_weave`, `plasma_ribbon`, `prism_pulse`,
  `scanline_comb`), so they are invisible to *any* tag-filtered pick — the owner
  reports never having seen some of them.

Cruise is fine (tags `None` → full variety); the *exciting* scenes are the
starved ones, which is why the show feels psychedelic-dominated.

---

## 2) Tag fixes (both, owner-approved)

### 2a. Tag-coverage audit + a mood/energy tag layer
- Give **every rotation effect** `TAGS`, including the currently-tagless ones.
- Add a small, deliberate **mood/energy vocabulary** on top of the existing
  category tags, e.g. `chill`, `ambient`, `groovy`, `energetic`, `intense`,
  `hard`, `uplifting`, `hypnotic`, `glitchy`, so the VJ's mood requests actually
  resolve to a spread of effects.
- Tag each effect with 1–2 mood tags in addition to its category tags.
- Effect files live in core (`unicornviz/effects/`) and in drop-in packs
  (`drop-ins/<pack>/`); pack edits are submodule changes (commit + push + pointer
  bump per SOP).

### 2b. Fix the per-scene tag sets (prefer the core path)
- Set real `*_effect_tags` on the `AudioProfile`s in
  **`unicornviz/audio/profiles.py`** (core) so drops/impacts/climaxes request a
  broad, *existing* energetic vocabulary (e.g. drop →
  `['intense','energetic','glitchy','psychedelic','bass','strobe']`) rather than
  the dead `intense/drop`. Doing this in profiles.py avoids editing the blocked
  `auto-vj-01` submodule, and lets different genres pull different looks.
- Keep breakdown pulling calmer tags (`ambient`, `chill`, `art`, `classic`).

### 2c. VJ tag-fallback (safety net, core)
- In `vj_api.goto_random_effect`, when the tag-filtered pool is empty (or below a
  small floor), **fall back to any enabled effect** (`tags=None`) instead of
  returning `None`/repeating. Optionally give every enabled effect a small
  baseline selection chance regardless of tags.
- This is a **core** change (`vj_api.py`) — no auto-vj submodule edit — and
  permanently hardens the director against future tag gaps.

**Net:** 2a+2b fix the vocabulary so moods map to real effects; 2c guarantees no
effect is ever permanently invisible.

---

## 3) Hotkey overflow — dynamic re-pack + pinning ✅ DONE (commit `0978840`)

**Was:** number-keys mapped into a *snapshot of all effects* taken once at
`HotkeyHandler` construction (`Playlist.shortcut_effects` computed once,
cached in `self._shortcut_effects`). Enabling/disabling an effect **never**
changed the mapping at all — not "36 slots with gaps" as originally guessed;
the real range is a clean **40 slots** (naked/Shift/Ctrl/Alt × 1-9,0), and
`go_index`'s modulo wraparound meant an out-of-range press landed on an
unrelated effect rather than no-op'ing.

**Shipped:**
- `Playlist.shortcut_effects` recomputes fresh on **every access** from the
  *enabled* effect set only — dynamically consolidates/expands, no caching.
- **Pinning:** `Playlist.set_hotkey_pins()`/`hotkey_pins()` — a pinned effect
  claims its slot while enabled; unpinned slots fill with the rest in catalog
  order; a pin whose effect is disabled, or whose slot is unreachable at the
  current enabled count, is simply not honoured until it fits — recomputed
  fresh each time, so nothing goes stale.
- **Pinning UI:** in the effects browser, pressing the *same chord* that would
  jump to a slot outside the browser instead pins/unpins the selected effect to
  that slot (muscle-memory reuse) — `App.effects_browser_toggle_pin_slot()`.
  Pins persist to `runtime/global_state.json` (same store as
  `effects.disabled`, not a separate `settings.json` — matches the existing
  pattern already used for disabled-effects persistence).
- **Overflow escape hatch:** the effects browser (`B`) reaches anything beyond
  slot 40 — confirmed still the right answer; number-keys are fast-access to
  the current working set, the browser reaches everything.
- The VJ is unaffected (it never reads hotkeys).

Tests: `tests/test_hotkey_slot_repack_and_pinning.py` (19 tests — slot
resolver, dynamic re-pack, pin placement/fallback/replacement, browser live
model update).

---

## 4) Effects browser enhancements

- **Pinning UI:** ✅ done above.
- **Category isolation** — ✅ **already existed**, discovered while scoping this
  work. The effects browser already ships a full two-pane `CatalogBrowser`
  layout (left category rail + right filtered list, `PANE_CATEGORIES`/
  `PANE_LIST`, `Tab`/`Left`/`Right` to move focus) — it landed in an earlier
  "Effects browser 2.0" / "migrate ProjectM manager onto the shared
  CatalogBrowser model" pass, before this plan was written. No work needed.

---

## 5) Hotkey editor (GNOME-style)

- **Reuse the config-editor shell** (tabbed modal, sprite border, hover glow,
  animation) — a new tab or sibling modal.
- **Generate the binding list from the help registry** (`CORE_HELP_SECTIONS` +
  drop-in `HELP_ENTRIES`) — single source of truth, same principle as the
  right-click menu; can't drift.
- **UX:** row per action with its current binding; click → "press new keys"
  capture; **live conflict detection**; reset-to-default; per-section grouping.
- **Persist** rebindings to `runtime/settings.json` (sparse overrides).
- **Enabler / main cost:** refactor `hotkeys.py` from the hardcoded
  `if/elif sym == …` dispatch to a **table-driven binding map**
  (`{action → (sym, mod)}`) that the dispatcher consults and the editor mutates.
  The effect number-key re-pack (§3) and right-click menu can read from the same
  table.

---

## 6) Sequencing

1. ✅ **VJ tag fixes** (§2) — done; see `docs/planning/vj-mood-tag-rollout.md`.
2. ✅ **Dynamic number-key re-pack + pinning** (§3) — done, commit `0978840`.
3. ✅ **Effects browser: category isolation + pinning UI** (§4) — pinning UI
   shipped with #2; category isolation turned out to already exist.
4. ⏳ **Refactor `hotkeys.py` to a table-driven binding map** (§5 enabler) — in
   progress.
5. **Hotkey editor** on that table, in the config-editor shell (§5) — next.

Regression tests for each step (tag-fallback behavior, re-pack over enabled set,
pin persistence, binding-table dispatch, help↔binding parity).
