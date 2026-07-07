# Mono-File Refactoring Plan — 2026-06-19

Owner: owner + Claude (multi-session)
Status: In progress — Items A & B shipped; C & D still on hold; **E & F
proposed 2026-07-07, pending owner review — not started**
Last updated: 2026-07-07

Scope: Low-hanging-fruit, safety-first extractions from the largest source
files. No behavioral changes proposed; all items are pure moves, mixin
extractions, or method splits.

---

## Progress

| Item | Status | Notes |
|------|--------|-------|
| **A** — null controllers → `_null_controllers.py` | ✅ **Done** (commit `524c5e5`, 2026-06-20) | Byte-identical move; re-exported from `app.py`. |
| **B** — CTAOverlay → `cta_overlay.py` | ✅ **Done** (commit `524c5e5`, 2026-06-20) | Byte-identical move; re-exported from `overlays.py`. |
| **C** — `App._init_subsystems()` split | ⏸ **On hold** (owner, 2026-06-20) | Medium risk; touches live `run()` control flow. Resume on a branch. Re-verified 2026-07-07: `run()` is still ~1,668 lines, scope unchanged. |
| **D** — `App._build_hud_state()` split | ⏸ **On hold** (owner, 2026-06-20) | Medium risk; do with or after C. Resume on a branch. |
| **E** — Context menu + config editor + hotkey pins → `AppConfigEditorMixin` | 🆕 **Proposed 2026-07-07** | Low-medium risk, mixin-based pure move. See §6. **Not started.** |
| **F** — Help overlay subsystem → `HelpOverlayMixin` | 🆕 **Proposed 2026-07-07** | Medium risk, mixin-based pure move, larger and more scattered than E. See §7. **Not started.** |

Regression coverage for A & B landed in
`tests/test_module_extraction_boundary.py` (6 tests: canonical home, re-export
identity, CTA default codepoints, font-builder placement, no circular import).

**Realized savings from A & B:** `app.py` 4,891 → 4,666; `overlays.py`
4,500 → 4,184. Full suite green at 199 tests (2026-06-20).

When picking C & D back up, start from §2 (Item C / Item D) and follow the
branch + careful-test-pass guidance in §4. For E & F, start from §6/§7.

---

## 0) Current Sizes

| File | 2026-06-19 | 2026-07-01 (audit) | 2026-07-07 |
|------|------|------|------|
| `unicornviz/app.py` | 4,891 | 5,472 | **6,486** |
| `unicornviz/overlays.py` | 4,500 | 4,711 | **6,000** |
| `unicornviz/vj_api.py` | 1,440 | — | 1,584 |
| `unicornviz/hotkeys.py` | 1,467 | — | 1,816 |

`app.py` and `overlays.py` are still the pain points, and both **regrew past
their post-A/B size** despite A & B shipping — a full ~1,600 and ~1,300 lines
respectively were added since 2026-06-20. This isn't drift/bloat in the old
code; it's real new features landing (§1a). `vj_api.py` remains a
wide-but-flat façade with no obvious split; `hotkeys.py` is similarly
structural (one large dispatch chain by design — see
`docs/planning/hotkey-architecture-refactor.md`).

---

## 1a) Why The Files Grew Again (2026-06-20 → 2026-07-07)

Almost none of the growth is `run()` or `_render_hud()` bloating further —
both are essentially the same size as the June audit (`run()` is 1,668 lines
now vs. 1,664 then; see §2 Item C). The growth is genuinely new, mostly
self-contained feature areas added since:

- **Right-click context menu** (generated from the help registry) + the
  **tabbed configuration editor** (Effects/Audio/Visuals/System/Auto VJ tabs)
  + its **in-app hotkey editor** (capture mode, conflict detection,
  reset-to-default) — see `docs/planning/configuration-editor-plan.md`,
  `docs/planning/vj-tags-and-hotkey-system-plan.md`.
- **Delete-key effect deletion**: disable-and-advance action, session
  tracking, stamped log file.
- **Help overlay overhaul**: word-wrap for long labels/descriptions
  (section cards, live shortcut map, Post FX list), left-pane section
  pagination (tabs of ≤10 sections, each capped at ≤7 items with
  overflow split into continuation sections), a new right-pane
  Effects/Post FX/Mouse tab strip, and the combined-sequence
  PageUp/PageDown paging that ties both together.
- Assorted smaller items: audio capture shutdown-race fix, help-section
  drop-in dedup (moving misplaced entries out of `CORE_HELP_SECTIONS` into
  the drop-ins that actually own them).

This matters for prioritization: unlike `run()`/`_render_hud()` (already
correctly judged high-risk to touch — see §3), the context-menu/config-editor
cluster and the help-overlay cluster are **new, additive, and largely
self-contained** — the same profile that made A & B safe. That's the basis
for Items E & F below.

---

## 1) Why These Files Are Large

### app.py

The file has three distinct zones before `class App` even begins:

- **Lines 83–313** (~231 lines): 5 null controller classes  
  `_NullMultiHeadController`, `_NullScreenBurstController`, `_NullWebcamSystem`,  
  `_NullRTMPStreamer`, `_NullPostFxController`
- **Lines 320–433** (~113 lines): 14 module-level drop-in loader functions  
  `_load_multihead_controller_class()` through `_load_control_room_controller_class()`
- **Lines 434–4891**: `class App` itself (~4,457 lines)

Inside `App`:
- `run()` spans lines 2270–3934 — **1,664 lines**
  - Init block (lines 2270–2631): subsystem setup, overlays, hotkeys, midi, playlist, streamer — **361 lines**
  - Main while loop (lines 2632–3934): event pump, update, HUD build, render, recording, swap — **1,303 lines**
    - HUD build Tier A/B/C (lines 2879–3165): ~286 lines embedded in the loop
- `_render()` spans lines 3563–3828 — **265 lines** (manageable on its own)

### overlays.py

The Overlays class bundles *everything overlay-related* — its render pipeline,
all modal state/rendering, the help system, banner animation, and the CTA hype
overlay. The major render methods:

| Method | Lines | Notes |
|---|---|---|
| `_render_hud()` | ~524 | The big one; single method |
| `_render_banner()` | ~389 | Banner animation + neon border |
| `_render_system_monitor_modal()` | ~339 | OS telemetry + rendering |
| `_render_help()` | ~211 | Help panel render |
| `_render_controller_help_modal()` | ~172 | Drop-in key help panel |
| `CTAOverlay` class | ~303 | Fully self-contained nested class |

---

## 2) Proposed Extractions (Safest First)

### Item A — `unicornviz/_null_controllers.py` ✅ DONE (commit `524c5e5`)

**What:** Move the 5 null controller classes from `app.py` (lines 83–313, ~231 lines)
to a new `unicornviz/_null_controllers.py` file.

**Why it's safe:** The classes have zero dependencies on the rest of `app.py`.
They exist only as drop-in fallbacks. The only coupling is:
1. The 14 loader functions return them (same file — resolved by re-exporting).
2. `App` methods use `isinstance(x, _NullWebcamSystem)` etc. — resolved by re-exporting.
3. `tests/test_null_controller_contracts.py` imports 3 of them from `unicornviz.app`
   — stays compatible because we re-export from `app.py`.

**Mechanical change:**
- Create `unicornviz/_null_controllers.py` with the 5 classes.
- In `app.py`, replace the class bodies with:
  ```python
  from unicornviz._null_controllers import (
      _NullMultiHeadController,
      _NullScreenBurstController,
      _NullWebcamSystem,
      _NullRTMPStreamer,
      _NullPostFxController,
  )
  ```
- Zero tests need updating. All `isinstance` checks and loader returns keep working.

**Net savings:** ~231 lines out of `app.py`, no API change, full test coverage maintained.

---

### Item B — `unicornviz/cta_overlay.py` ✅ DONE (commit `524c5e5`)

**What:** Move `CTAOverlay` class from `overlays.py` (lines 326–629, ~303 lines)
to a new `unicornviz/cta_overlay.py` file.

**Why it's safe:** `CTAOverlay` is already documented as "self-contained" in its
own docstring. It has no references from outside `overlays.py` — no external
import in `app.py` or `hotkeys.py` touches `CTAOverlay` directly. The module-level
`_build_font_texture()` function it depends on either moves with it or stays in
`overlays.py` and gets imported.

**Mechanical change:**
- Create `unicornviz/cta_overlay.py` with `CTAOverlay` + `_build_font_texture()`.
- In `overlays.py`, replace the class body with:
  ```python
  from unicornviz.cta_overlay import CTAOverlay
  ```
- `Overlays.__init__` continues using `CTAOverlay(...)` as before.
- No test changes needed.

**Net savings:** ~303 lines out of `overlays.py`, no API change.

**Caution:** `_build_font_texture()` is also called by `Overlays.__init__` — check
whether it stays in `overlays.py` (and is imported by `cta_overlay.py`) or moves
to `cta_overlay.py` (and is imported back). Either way works; the font texture
builder is purely functional with no side effects.

**As shipped:** `CTAOverlay` does not actually use `_build_font_texture()` (it
builds its own PIL textures), so the font builder and `_FONT_8X8` stayed in
`overlays.py` where `Overlays` uses them. Only `CTAOverlay` + the `_CTA_SLOTS` /
`_CTA_SHOW_DURATION` defaults moved; all three are re-exported from `overlays.py`.

---

### Item C — `App._init_subsystems()` method split ⏸ ON HOLD (owner, 2026-06-20)

> **On hold by owner (2026-06-20).** A & B shipped; C is deferred for now.
> When resumed, do it on a dedicated branch with a careful full-suite pass —
> it edits live `run()` control flow, unlike the pure moves in A & B.

**What:** Extract the subsystem init block from `run()` (lines 2270–2631, ~361 lines)
into a private method `App._init_subsystems()`.

**Why it's worth doing:** `run()` at 1,664 lines is unreadable at a glance. After
extraction, `run()` reads as:
```python
def run(self) -> None:
    self._init_sdl()
    self._init_moderngl()
    self._init_subsystems()
    # perf counters ...
    while self._running:
        ...
```

**Why it requires care:** The init block creates local variables (`audio_manager`,
`overlays`, `hotkeys`, `playlist`, `midi_manager`) that the main while loop body
references directly by those names. Each of these is also stored on `self.*`
(confirmed: lines 2319, 2422, 2438, 2491 set `self._audio_manager`, `self._playlist`,
`self._overlays`, `self._hotkeys`). So the extraction is possible via one of
two approaches:

- **Option 1 (cleanest):** Update the while loop to use `self._overlays`,
  `self._audio_manager`, etc. instead of the local variable aliases. Then
  `_init_subsystems()` just stores to `self.*` and returns nothing.
  This requires ~20–30 search-replace-style substitutions in the loop body — 
  mechanical but large surface area.

- **Option 2 (minimal change):** `_init_subsystems()` returns a dataclass/namedtuple
  with the key objects, and `run()` unpacks them:
  ```python
  ss = self._init_subsystems()
  overlays, hotkeys, playlist = ss.overlays, ss.hotkeys, ss.playlist
  ```
  Smaller diff but adds an intermediate data type.

**Recommendation:** Option 1 is the right long-term direction (the `self.*`
attributes exist precisely for this); Option 2 is a quicker win if you want
smaller risk.

**Net savings:** ~361 lines out of `run()`, making it ~1,300 lines (still large
but much more approachable).

---

### Item D — `App._build_hud_state()` method split ⏸ ON HOLD (owner, 2026-06-20)

> **On hold by owner (2026-06-20).** Do with or after Item C, on the same
> branch. Same caveat: this edits live `run()` loop body.

**What:** Extract the 3-tier HUD build block from `run()`'s main loop
(lines 2879–3165, ~286 lines) into `App._build_hud_state(dt, fps_now, overlays)`.

**Why:** The HUD Tier A/B/C logic is already well-commented and self-contained.
It reads Spotify state, builds banner fields, and calls `overlays.set_hud_state()`.
All state references are `self.*` plus the `overlays` local.

**Why it requires care:** The init and HUD blocks share some state that would flow
through `run()` → `_build_hud_state()` as parameters or via `self.*`.
Specifically `fps_now` and `dt` are computed immediately before the HUD block in
the loop — these become clean method parameters.

**Net savings:** ~286 lines out of `run()`, reducing it to roughly 900 lines
(from 1,664). At that point `run()` is a scannable event pump.

---

## 3) Explicitly Not Recommended Now

These would have high value but carry disproportionate risk for a "low-hanging
fruit" pass. Sizes refreshed 2026-07-07 (some shrank since June from unrelated
work elsewhere in the file — not something this plan did):

| Item | Risk | Why Skip |
|---|---|---|
| Split `_render_hud()` (529 lines) | High | Tightly coupled GL state machine; many internal cross-references |
| Split `_render_system_monitor_modal()` (215 lines) | Medium | Standalone logic but changes the Overlays interface |
| Split `_render_banner()` (67 lines, was 389 in June) | Low value now | Already shrank substantially from unrelated work; not worth a dedicated move for what's left |
| Move loaders to `dropins.py` | Medium | Loaders reference null classes from `app.py`; would create a circular dependency unless null classes move first (do A first) |
| Decompose `VJApi` | Low value | Already a well-structured flat façade; no obvious split |

---

## 4) Suggested Order of Execution

1. ✅ **A** — null controllers → `_null_controllers.py` (done, commit `524c5e5`)
2. ✅ **B** — CTAOverlay → `cta_overlay.py` (done, commit `524c5e5`)
3. After A+B: optionally move loaders to `dropins.py` — the null-class circular-import
   risk is now resolved because loaders would import from `_null_controllers.py`
   (not started)
4. 🆕 **E** — context menu + config editor + hotkey pins mixin (proposed; see §6) —
   independent of C/D, can go first since it's the same risk tier as A/B
5. 🆕 **F** — help overlay mixin (proposed; see §7) — independent of C/D/E, do after
   E since both touch `App`/`Overlays` boundaries and are easier to review one at a time
6. ⏸ **C** — `_init_subsystems()` (on hold; medium: do on a branch with careful test pass)
7. ⏸ **D** — `_build_hud_state()` (on hold; medium: do on same branch as C or a follow-up)

A+B realized (measured post-commit):

| File | Before | After A+B |
|------|--------|-----------|
| `app.py` | 4,891 | 4,666 |
| `overlays.py` | 4,500 | 4,184 |

If E+F ship on top of the current sizes, `app.py` would drop from 6,486 to
roughly **5,880** and `overlays.py` from 6,000 to roughly **4,680** — before
C/D are even touched. After all of A–F, `app.py`'s `run()` would still be the
long pole (C/D address that specifically).

---

## 5) Regression Checklist (for any item above)

- `pytest tests/ -q` stays fully green (561 passing as of 2026-07-07; was 199
  at the A+B commit).
- `tests/test_module_extraction_boundary.py` — pins A+B invariants (re-export
  identity, CTA default codepoints, font-builder placement, no circular import).
- `tests/test_null_controller_contracts.py` — parametrized null-contract tests
  continue to pass with imports from `unicornviz.app` (re-exported names).
- `tests/test_dropin_boundary.py` — bare-import boundary test stays green.
- Manual smoke: app starts, audio selector opens, help overlay renders, HUD tab
  shows correct state.
- For Item E specifically: `tests/test_context_menu.py`,
  `tests/test_config_editor_*.py` (shell/effects_tab/globals/profiles/system),
  `tests/test_hotkey_editor_ui.py`, `tests/test_hotkey_rebinding.py`,
  `tests/test_hotkey_slot_repack_and_pinning.py`.
- For Item F specifically: `tests/test_help_tab_pagination.py`,
  `tests/test_help_page_crossover.py`, `tests/test_help_text_wrapping.py`,
  `tests/test_help_section_item_cap.py`, `tests/test_help_right_pane_tabs.py`,
  `tests/test_help_section_dropin_dedup.py`, `tests/test_help_overlay_parity.py`,
  `tests/test_hotkey_help_audit.py`, `tests/test_overlays_help_icons.py`.

---

## 6) Item E — Context Menu + Config Editor + Hotkey Pins → `AppConfigEditorMixin` 🆕 PROPOSED (not started)

**What:** Move ~30 `App` methods (context menu model/activation, the entire
tabbed config editor including its hotkey-rebind tab, numeric-hotkey slot
pins/overrides, and show-preset capture/apply) from `app.py` into a new
`unicornviz/app_config_editor.py`, as a mixin class `App` inherits from
instead of a standalone class.

**Methods (30, 609 lines total, verified 2026-07-07):**
`_build_context_menu_model`, `_context_menu_dropin_sections`,
`_open_context_menu_at`, `_activate_context_menu_entry`,
`load_config_profile`, `config_editor_param_rows`, `_push_config_editor_model`,
`config_editor_info_rows`, `config_editor_hotkey_rows`,
`hotkey_action_for_chord`, `start_hotkey_capture`, `apply_hotkey_capture`,
`cancel_hotkey_capture`, `_config_editor_settings_specs`,
`_config_editor_dropin_specs`, `_config_editor_all_specs`,
`config_editor_global_rows`, `_apply_config_editor_action`,
`_config_editor_adjust`, `hotkey_pins`, `hotkey_pin_slot_for`,
`set_hotkey_pin`, `toggle_hotkey_pin`, `_persist_hotkey_pins`,
`hotkey_overrides`, `set_hotkey_override`, `capture_show_preset`,
`apply_show_preset`, `list_show_presets`, `save_show_preset`,
`delete_show_preset`.

**Why it's safe (same class of move as A/B, not C/D):** Every one of these
methods is called as `self.method_name(...)` from elsewhere (hotkeys.py,
tests) or `app.method_name(...)` externally — Python method resolution order
doesn't care whether a method is defined directly on `App` or on a mixin
`App` inherits from. **No method body needs to change** — this is a pure
textual relocation plus one `class App(AppConfigEditorMixin, ...):` line,
unlike Items C/D which rewire local variables inside a live control-flow
block. The methods reference plenty of `self.*` state (`self.cfg`,
`self._overlays`, `self._effect_config_overrides`,
`self._config_profile_store`, `self._disabled_effects`, `self._hotkey_pins`,
`self._hotkey_overrides`, etc.) but a mixin has full access to `self` — no
new indirection needed.

**Mechanical change:**

1. Create `unicornviz/app_config_editor.py` with `class AppConfigEditorMixin:`
   containing the 30 methods, byte-identical bodies.
2. `from unicornviz.app_config_editor import AppConfigEditorMixin` in
   `app.py`; change `class App:` to `class App(AppConfigEditorMixin):`.
3. Delete the moved method bodies from `app.py`.
4. No changes anywhere else — `hotkeys.py`, `overlays.py`, and every test
   call these as `app.foo(...)`/`self.foo(...)` today and will continue to.

**Risk:** Low-medium. The only real risk is a copy-paste transcription
error (missed method, wrong indentation) — caught immediately by the
regression checklist in §5, since these methods are heavily exercised by
the config-editor/context-menu/hotkey test suites already.

**Net savings:** ~609 lines out of `app.py` (6,486 → ~5,880).

---

## 7) Item F — Help Overlay Subsystem → `HelpOverlayMixin` 🆕 PROPOSED (not started)

**What:** Move the help-overlay subsystem (help icon rail, controller-help
modal, the section-card renderer + word-wrap helpers, left-pane pagination,
the new right-pane Effects/Post FX/Mouse tabs, the combined-sequence
PageUp/PageDown paging, and `register_help_entries()`) from `overlays.py`
into a new `unicornviz/overlays_help.py`, as a mixin class `Overlays`
inherits from — same pattern as Item E, applied to `Overlays` instead of
`App`.

**Scope (55 methods, 1,323 lines total, verified 2026-07-07):** everything
with `help` in its name — `_help_icon_*`, `_render_help*`,
`_draw_help_*`, `_iter_help_sections`, `_help_tab_groups`,
`_current_help_sections`, `help_tab_*`, `set_help_tab`, `move_help_tab`,
`_help_right_tabs`, `help_right_tab_*`, `set_help_right_tab`,
`move_help_right_tab`, `move_help_page`, `_help_text_max_chars`,
`_wrap_help_entry` (+ `_wrap_plain_text`, `_wrap_words_two_budget` — these
two don't have "help" in the name but exist only to serve the help
overlay; would move alongside), `_help_theme_color`,
`register_help_entries`, `handle_help_mouse_click`,
`handle_help_mouse_motion`, `note_help_activity`, `help_visible`,
`controller_help_modal_visible`, `toggle_help*`, plus the class-level
constants `CORE_HELP_SECTIONS`, `HELP_ICON_ENTRIES`, `HELP_SECTION_THEMES`,
`DYNAMIC_THEME_CYCLE`, `HELP_SECTIONS_PER_TAB`, `HELP_MAX_ITEMS_PER_SECTION`.

**Why it's a mixin, not a standalone object (unlike C's Option 2):** Unlike
`CTAOverlay` (Item B), which had zero external references and became a
fully independent class, help-overlay methods are called directly on
`Overlays` instances from `hotkeys.py` (e.g. `o.move_help_page(delta)`,
`o.toggle_help_section(...)`) and from `app.py` — dozens of call sites.
Making it a standalone object (`self._help = HelpOverlayRenderer(...)`)
would mean rewriting every call site to `overlays._help.foo(...)` or adding
thin delegate wrappers on `Overlays` — real work, real risk. A mixin avoids
all of that: `o.move_help_page(...)` keeps working unchanged because it's
still a method on the `Overlays` instance via inheritance.

**Why this is riskier than Item E:** The help methods are **scattered
throughout `overlays.py`** (roughly lines 823–5720), interleaved with
unrelated `Overlays` methods, rather than one contiguous block. Gathering
them correctly requires care — this plan's line/method list above should be
diffed against a fresh `grep -n "    def "` pass immediately before
executing, since other work may have added/renamed help methods in the
meantime (confirm no drift from this document before cutting anything).

**Mechanical change:**

1. Re-verify the current method list (see risk note above).
2. Create `unicornviz/overlays_help.py` with `class HelpOverlayMixin:`
   containing the class-level constants + all listed methods, byte-identical.
3. `from unicornviz.overlays_help import HelpOverlayMixin` in `overlays.py`;
   change `class Overlays:` to `class Overlays(HelpOverlayMixin):`.
4. Delete the moved constants/methods from `overlays.py`.
5. Check `__init__`'s help-related state initialization
   (`self._help_tab_idx`, `self._dynamic_help_sections`,
   `self._postfx_help_entries`, `self._mouse_help_entries`,
   `self._help_active_pane`, etc.) — these can stay in `Overlays.__init__`
   as-is (a mixin doesn't need its own `__init__`; it just needs the
   attributes to exist on `self` by the time its methods run, which they
   already do).

**Risk:** Medium — larger and more scattered than E, but still a pure move
(no method body changes). The main failure mode is an incomplete/incorrect
method list, which the regression checklist (§5) and a full-suite run would
catch immediately (missing methods = `AttributeError` at runtime, not a
silent behavior change).

**Net savings:** ~1,323 lines out of `overlays.py` (6,000 → ~4,680).
