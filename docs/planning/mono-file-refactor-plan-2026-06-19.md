# Mono-File Refactoring Plan — 2026-06-19

Owner: owner + Claude Sonnet 4.6
Status: In progress — Items A & B shipped; Items C & D on hold (owner, 2026-06-20)
Last updated: 2026-06-20

Scope: Low-hanging-fruit, safety-first extractions from the three largest source
files. No behavioral changes proposed; all items are pure moves or method splits.

---

## Progress

| Item | Status | Notes |
|------|--------|-------|
| **A** — null controllers → `_null_controllers.py` | ✅ **Done** (commit `524c5e5`, 2026-06-20) | Byte-identical move; re-exported from `app.py`. |
| **B** — CTAOverlay → `cta_overlay.py` | ✅ **Done** (commit `524c5e5`, 2026-06-20) | Byte-identical move; re-exported from `overlays.py`. |
| **C** — `App._init_subsystems()` split | ⏸ **On hold** (owner, 2026-06-20) | Medium risk; touches live `run()` control flow. Resume on a branch. |
| **D** — `App._build_hud_state()` split | ⏸ **On hold** (owner, 2026-06-20) | Medium risk; do with or after C. Resume on a branch. |

Regression coverage for A & B landed in
`tests/test_module_extraction_boundary.py` (6 tests: canonical home, re-export
identity, CTA default codepoints, font-builder placement, no circular import).

**Realized savings from A & B:** `app.py` 4,891 → 4,666; `overlays.py`
4,500 → 4,184. Full suite green at 199 tests.

When picking C & D back up, start from §2 (Item C / Item D) and follow the
branch + careful-test-pass guidance in §4.

---

## 0) Current Sizes

| File | Lines |
|------|-------|
| `unicornviz/app.py` | 4,891 |
| `unicornviz/overlays.py` | 4,500 |
| `unicornviz/vj_api.py` | 1,440 |
| `unicornviz/hotkeys.py` | 1,467 |

`app.py` and `overlays.py` are the pain points. `vj_api.py` is a wide-but-flat
façade and doesn't have an obvious split; `hotkeys.py` is similarly structural.

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
fruit" pass:

| Item | Risk | Why Skip |
|---|---|---|
| Split `_render_hud()` (524 lines) | High | Tightly coupled GL state machine; many internal cross-references |
| Split `_render_system_monitor_modal()` (339 lines) | Medium | Standalone logic but changes the Overlays interface |
| Split `_render_banner()` (389 lines) | Medium | Neon border drawing helpers are shared state |
| Move loaders to `dropins.py` | Medium | Loaders reference null classes from `app.py`; would create a circular dependency unless null classes move first (do A first) |
| Decompose `VJApi` | Low value | Already a well-structured flat façade; no obvious split |

---

## 4) Suggested Order of Execution

1. ✅ **A** — null controllers → `_null_controllers.py` (done, commit `524c5e5`)
2. ✅ **B** — CTAOverlay → `cta_overlay.py` (done, commit `524c5e5`)
3. After A+B: optionally move loaders to `dropins.py` — the null-class circular-import
   risk is now resolved because loaders would import from `_null_controllers.py`
   (not started)
4. ⏸ **C** — `_init_subsystems()` (on hold; medium: do on a branch with careful test pass)
5. ⏸ **D** — `_build_hud_state()` (on hold; medium: do on same branch as C or a follow-up)

A+B realized (measured post-commit):

| File | Before | After A+B |
|------|--------|-----------|
| `app.py` | 4,891 | 4,666 |
| `overlays.py` | 4,500 | 4,184 |

After A+B+C+D, `app.py` approaches ~3,700 lines with `run()` at ~900 lines —
a meaningful improvement in navigability with no behavioral change.

---

## 5) Regression Checklist (for any item above)

- `pytest tests/ -q` stays fully green (199 passing as of the A+B commit).
- `tests/test_module_extraction_boundary.py` — pins A+B invariants (re-export
  identity, CTA default codepoints, font-builder placement, no circular import).
- `tests/test_null_controller_contracts.py` — parametrized null-contract tests
  continue to pass with imports from `unicornviz.app` (re-exported names).
- `tests/test_dropin_boundary.py` — bare-import boundary test stays green.
- Manual smoke: app starts, audio selector opens, help overlay renders, HUD tab
  shows correct state.
